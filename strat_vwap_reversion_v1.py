import psycopg2
import pandas as pd
import numpy as np
import os, time, requests
import warnings
warnings.simplefilter(action='ignore', category=UserWarning)
import sys

sys.stdout = open('/home/tony/tekton-ai-trader/strat_vwap.log', 'a', buffering=1)
sys.stderr = sys.stdout

from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ────────────────────────────────────────────────────────────────────
#
#  VWAP Reversion (VR) Strategy
#  ─────────────────────────────
#  Logic:
#    1. Calculate intraday VWAP from session open on 15min data
#    2. Price deviates significantly from VWAP (≥ 1.5 × ATR away)
#    3. A reversal candle forms AT the deviation extreme (pin bar or engulf)
#    4. Entry back toward VWAP
#    5. SL: beyond the reversal candle wick
#    6. TP: VWAP midpoint (natural reversion target)
#
#  Why this works:
#    - VWAP is the institutional reference price — price always gravitates back
#    - Extreme deviations are typically caused by stop hunts or news spikes
#    - Reversal candle confirms the move is exhausted
#    - Only trade pairs with sufficient volume (active pairs, not exotics)
#
#  Best on: EURUSD, GBPUSD, USDJPY, XAUUSD during active sessions
#
# ─────────────────────────────────────────────────────────────────────────────

DB_PARAMS = {
    "host":     os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
    "database": "tekton-trader",
    "user":     "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD"),
}

BRIDGE_URL        = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY        = os.getenv("BRIDGE_KEY", "")

SCAN_INTERVAL_SEC  = 300
SIGNAL_COOLDOWN_HR = 4
LTF_TIMEFRAME      = "15min"
LTF_CANDLES        = 60        # one full session worth of 15min candles
ATR_PERIOD         = 14
VWAP_DEVIATION_ATR = 1.5       # price must be ≥ 1.5×ATR from VWAP to qualify
MIN_RR             = 1.5
MIN_SL_PIPS        = 3.0
MAX_SL_PIPS        = 150.0
CONFIDENCE_BASE    = 73
STRATEGY_NAME      = "Tekton-VR-v1"

# Pairs best suited for VWAP reversion (liquid, tight spread)
PREFERRED_SYMBOLS = {
    "EURUSD","GBPUSD","USDJPY","USDCHF","USDCAD",
    "AUDUSD","NZDUSD","EURJPY","GBPJPY","XAUUSD",
    "GBPCHF","EURGBP","AUDNZD","EURCAD","GBPCAD"
}

_symbol_specs_cache = {}
_specs_cache_ts     = 0
SPECS_CACHE_TTL     = 300


def _ts():
    return datetime.now().strftime("%H:%M:%S")

def _db():
    return psycopg2.connect(**DB_PARAMS)

def notify(msg):
    token   = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": f"📈 *VR Signal*\n{msg}", "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass

def get_symbol_specs():
    global _symbol_specs_cache, _specs_cache_ts
    now = time.time()
    if _symbol_specs_cache and (now - _specs_cache_ts) < SPECS_CACHE_TTL:
        return _symbol_specs_cache
    try:
        resp = requests.get(f"{BRIDGE_URL}/symbols/list",
                            headers={"X-Bridge-Key": BRIDGE_KEY}, timeout=10)
        resp.raise_for_status()
        specs = {}
        for s in resp.json().get("symbols", []):
            sym     = s.get("name", "")
            digits      = s.get("digits") or 5
            pip_pos     = s.get("pipPosition")
            specs[sym] = {
                "pip_size":    10 ** (-pip_pos) if pip_pos else 10 ** -(digits - 1),
                "price_scale": 10 ** digits,
            }
        _symbol_specs_cache = specs
        _specs_cache_ts     = now
        print(f"[{_ts()}] 📋 Bridge specs loaded: {len(specs)} symbols")
        return specs
    except Exception as e:
        print(f"[{_ts()}] ❌ Bridge specs UNAVAILABLE — skipping scan cycle: {e}")
        raise

def get_pip_info(symbol):
    specs = get_symbol_specs()
    if symbol in specs:
        return specs[symbol]["pip_size"], specs[symbol]["price_scale"]
    if symbol.endswith("JPY"):
        return 0.01, 100
    return 0.0001, 10000

def get_ohlc(symbol, timeframe, limit):
    try:
        conn = _db()
        df   = pd.read_sql(
            "SELECT timestamp, open, high, low, close, volume FROM market_data "
            "WHERE symbol=%s AND timeframe=%s ORDER BY timestamp DESC LIMIT %s",
            conn, params=(symbol, timeframe, limit)
        )
        conn.close()
        if df.empty:
            return df
        df = df.sort_values("timestamp").reset_index(drop=True)
        _, price_scale = get_pip_info(symbol)
        for col in ["open", "high", "low", "close"]:
            df[col] = df[col] / price_scale
        return df
    except Exception as e:
        print(f"[{_ts()}] ❌ DB ({symbol} {timeframe}): {e}")
        return None

def calc_atr(df, period=ATR_PERIOD):
    high, low, prev = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])

def calc_vwap(df):
    """
    Calculate VWAP using typical price × volume.
    If volume is zero/missing, falls back to equal-weight average.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].fillna(0) if "volume" in df.columns else pd.Series([1.0] * len(df))
    vol = vol.replace(0, 1.0)  # avoid division by zero
    cumulative_tpv = (typical * vol).cumsum()
    cumulative_vol  = vol.cumsum()
    return cumulative_tpv / cumulative_vol

def is_pin_bar(c, direction, atr):
    """Pin bar: small body, long wick in rejection direction."""
    body  = abs(c["close"] - c["open"])
    range_ = c["high"] - c["low"]
    if range_ <= 0:
        return False
    if direction == "BUY":
        lower_wick = min(c["open"], c["close"]) - c["low"]
        return lower_wick >= range_ * 0.6 and body <= range_ * 0.35
    else:
        upper_wick = c["high"] - max(c["open"], c["close"])
        return upper_wick >= range_ * 0.6 and body <= range_ * 0.35

def is_engulfing(prev, curr, direction):
    """Engulfing: current body fully engulfs previous body."""
    if direction == "BUY":
        return (curr["close"] > curr["open"] and
                prev["close"] < prev["open"] and
                curr["close"] > prev["open"] and
                curr["open"]  < prev["close"])
    else:
        return (curr["close"] < curr["open"] and
                prev["close"] > prev["open"] and
                curr["close"] < prev["open"] and
                curr["open"]  > prev["close"])

def get_active_symbols():
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT symbol FROM market_data WHERE timeframe=%s
            GROUP BY symbol HAVING COUNT(*) > 20
            GROUP BY symbol HAVING COUNT(*) >= 30 ORDER BY symbol;
        """, (LTF_TIMEFRAME,))
        syms = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT banned_symbols FROM settings WHERE id = 1;")
        brow = cur.fetchone()
        banned = set(brow[0].split(",")) if brow and brow[0] else set()
        syms = [s for s in syms if s not in banned]
        cur.close(); conn.close()
        return [s for s in syms if s in PREFERRED_SYMBOLS]
    except Exception as e:
        print(f"[{_ts()}] ⚠️ get_active_symbols: {e}")
        return []

def is_on_cooldown(symbol, direction):
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT created_at FROM signals
            WHERE symbol=%s AND signal_type=%s AND strategy=%s
            ORDER BY created_at DESC LIMIT 1;
        """, (symbol, direction, STRATEGY_NAME))
        row = cur.fetchone()
        cur.close(); conn.close()
        if row is None:
            return False
        age_h = (datetime.utcnow() - row[0].replace(tzinfo=None)).total_seconds() / 3600
        return age_h < SIGNAL_COOLDOWN_HR
    except Exception as e:
        print(f"[{_ts()}] ⚠️ Cooldown ({symbol}): {e}")
        return False

def insert_signal(symbol, direction, sl_pips, tp_pips, confidence, reason):
    try:
        conn = _db()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO signals
              (symbol, strategy, signal_type, timeframe, confidence_score,
               sl_pips, tp_pips, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'PENDING')
            RETURNING signal_uuid;
        """, (symbol, STRATEGY_NAME, direction, LTF_TIMEFRAME,
              int(confidence), float(round(sl_pips, 1)), float(round(tp_pips, 1))))
        uuid = cur.fetchone()[0]
        conn.commit(); cur.close(); conn.close()
        msg = (f"{direction} {symbol} | SL:{sl_pips:.1f}p TP:{tp_pips:.1f}p "
               f"| Conf:{confidence}% | {reason}")
        print(f"[{_ts()}] ▶ SIGNAL {msg}")
        notify(msg)
        return uuid
    except Exception as e:
        print(f"[{_ts()}] ❌ insert_signal ({symbol}): {e}")
        return None

# ─── CORE STRATEGY LOGIC ──────────────────────────────────────────────────────

def scan_symbol(symbol):
    pip_size, price_scale = get_pip_info(symbol)

    df = get_ohlc(symbol, LTF_TIMEFRAME, LTF_CANDLES)
    if df is None or len(df) < 20:
        return

    atr_val = calc_atr(df)
    if atr_val <= 0:
        return

    df["vwap"] = calc_vwap(df)

    c_curr = df.iloc[-1]
    c_prev = df.iloc[-2]
    vwap   = float(df["vwap"].iloc[-2])  # use previous candle's VWAP (confirmed)

    current_price = c_curr["close"]
    deviation     = current_price - vwap

    # ── Check for significant deviation from VWAP ────────────────────────────
    if abs(deviation) < atr_val * VWAP_DEVIATION_ATR:
        return  # price too close to VWAP — no mean reversion setup

    direction = "SELL" if deviation > 0 else "BUY"

    if is_on_cooldown(symbol, direction):
        print(f"[{_ts()}] ⏳ COOLDOWN: {symbol} {direction}")
        return

    # ── Reversal candle confirmation ─────────────────────────────────────────
    pin  = is_pin_bar(c_prev, direction, atr_val)
    engulf = is_engulfing(df.iloc[-3], c_prev, direction)

    if not (pin or engulf):
        return  # no reversal confirmation

    pattern = "pin bar" if pin else "engulfing"

    # ── SL / TP ───────────────────────────────────────────────────────────────
    if direction == "BUY":
        sl_price = c_prev["low"] - atr_val * 0.2
        tp_price = vwap  # revert to VWAP
    else:
        sl_price = c_prev["high"] + atr_val * 0.2
        tp_price = vwap

    entry    = current_price
    sl_pips  = abs(entry - sl_price) / pip_size
    tp_pips  = abs(entry - tp_price) / pip_size

    if not (MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS):
        return
    if tp_pips <= 0:
        return
    if sl_pips > 0 and (tp_pips / sl_pips) < MIN_RR:
        return

    rr         = round(tp_pips / sl_pips, 2)
    dev_pips   = round(abs(deviation) / pip_size, 1)
    confidence = min(CONFIDENCE_BASE + int(rr * 2), 90)
    reason     = (f"VR {pattern} dev={dev_pips}p from VWAP "
                  f"ATR={round(atr_val/pip_size,1)}p RR={rr}")

    insert_signal(symbol, direction, sl_pips, tp_pips, confidence, reason)


def main():
    print(f"[{_ts()}] 🧠 VWAP Reversion Strategy Active. [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    while True:
        print(f"[{_ts()}] 🧠 VR scan started")
        try:
            try:
                get_symbol_specs()  # pre-check — raises if bridge specs unavailable
            except Exception as spec_err:
                print(f"[{_ts()}] ❌ BRIDGE SPECS FAILED — skipping scan cycle. Check /symbols/list endpoint. Error: {spec_err}")
                time.sleep(SCAN_INTERVAL_SEC)
                continue
            symbols = get_active_symbols()
            print(f"[{_ts()}] 📊 {len(symbols)} preferred symbols")
            for sym in symbols:
                try:
                    scan_symbol(sym)
                except Exception as e:
                    print(f"[{_ts()}] ⚠️ {sym}: {e}")
            print(f"[{_ts()}] ✅ VR scan done")
        except Exception as e:
            print(f"[{_ts()}] ❌ VR ERROR: {e}")
        time.sleep(SCAN_INTERVAL_SEC)


if __name__ == "__main__":
    main()
