"""
FVG Strategy Diagnostic
Run on VM: python3 diag_fvg.py
Tells you exactly why each symbol is being rejected.
"""
import psycopg2
import pandas as pd
import os, time
from dotenv import load_dotenv
load_dotenv()

DB_PARAMS = {
    "host":     os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
    "database": "tekton-trader",
    "user":     "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD"),
}

ATR_PERIOD    = 14
ATR_MIN_RATIO = 0.2
FVG_LOOKBACK  = 10
MIN_SL_PIPS   = 3.0
MAX_SL_PIPS   = 600.0

def _db():
    return psycopg2.connect(**DB_PARAMS)

def get_ohlc(symbol, timeframe, limit):
    conn = _db()
    df = pd.read_sql(
        "SELECT timestamp, open, high, low, close FROM market_data "
        "WHERE symbol=%s AND timeframe=%s ORDER BY timestamp DESC LIMIT %s",
        conn, params=(symbol, timeframe, limit)
    )
    conn.close()
    if df.empty: return df
    return df.sort_values("timestamp").reset_index(drop=True)

def calc_atr(df, period=ATR_PERIOD):
    high = df["high"]; low = df["low"]; prev = df["close"].shift(1)
    tr = pd.concat([high-low, (high-prev).abs(), (low-prev).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])

def get_active_symbols():
    conn = _db(); cur = conn.cursor()
    cur.execute("SELECT symbol FROM market_data WHERE timeframe='15min' GROUP BY symbol HAVING COUNT(*) >= 30 ORDER BY symbol")
    syms = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()
    return syms

# Run on a sample — test 10 symbols in detail
symbols = get_active_symbols()
print(f"Testing {len(symbols)} symbols\n")
print(f"{'SYMBOL':<12} {'PRICE_SCALE':>12} {'ATR_RAW':>12} {'ATR_PIPS':>10} {'BEST_GAP_P':>12} {'PASS_ATR':>10} {'PASS_MSS':>10} {'PASS_SL':>10} {'VERDICT'}")
print("-" * 110)

for symbol in symbols:
    df_raw = get_ohlc(symbol, "15min", 60)
    if df_raw is None or len(df_raw) < 20:
        print(f"{symbol:<12} {'NO DATA':>12}")
        continue

    # Detect price scale from actual data
    # cTrader raw prices: EURUSD ~= 1.08 → raw 108000 (scale=100000)
    # We need to find scale. Use median close value.
    median_close = df_raw["close"].median()
    if median_close > 10000:
        price_scale = 100000
    elif median_close > 1000:
        price_scale = 10000
    elif median_close > 100:
        price_scale = 1000
    elif median_close > 10:
        price_scale = 100
    else:
        price_scale = 1

    df = df_raw.copy()
    for col in ["open","high","low","close"]:
        df[col] = df[col] / price_scale

    pip_size = df["close"].median() * 0.0001  # rough pip estimate

    atr_val = calc_atr(df)
    current_close = float(df["close"].iloc[-1])

    end_idx   = len(df) - 1
    start_idx = max(1, len(df) - FVG_LOOKBACK)

    best_gap_p = 0
    best_pass_atr = False
    best_pass_mss = False
    best_pass_sl  = False
    verdict = "NO_FVG"

    for i in range(end_idx - 1, start_idx, -1):
        c_prev = df.iloc[i-1]
        c_mid  = df.iloc[i]
        c_next = df.iloc[i+1]

        # Bullish
        gap_b = float(c_next["low"]) - float(c_prev["high"])
        if gap_b > 0:
            gap_pips = round(gap_b / pip_size, 1)
            pass_atr = gap_b >= atr_val * ATR_MIN_RATIO
            pass_mss = current_close > float(c_prev["high"]) and current_close > float(c_mid["high"])
            sl_price = float(c_prev["high"]) - gap_b * 0.1
            sl_pips  = round((current_close - sl_price) / pip_size, 1)
            pass_sl  = MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS

            if gap_pips > best_gap_p:
                best_gap_p = gap_pips
                best_pass_atr = pass_atr
                best_pass_mss = pass_mss
                best_pass_sl  = pass_sl
                if pass_atr and pass_mss and pass_sl:
                    verdict = f"PASS BUY i={i}"
                elif not pass_atr:
                    verdict = f"FAIL_ATR BUY gap={gap_pips:.1f}p atr={round(atr_val/pip_size,1)}p"
                elif not pass_mss:
                    verdict = f"FAIL_MSS BUY close={round(current_close,5)} need>{round(float(c_prev['high']),5)}"
                elif not pass_sl:
                    verdict = f"FAIL_SL BUY sl={sl_pips}p"

        # Bearish
        gap_s = float(c_prev["low"]) - float(c_next["high"])
        if gap_s > 0:
            gap_pips = round(gap_s / pip_size, 1)
            pass_atr = gap_s >= atr_val * ATR_MIN_RATIO
            pass_mss = current_close < float(c_prev["low"]) and current_close < float(c_mid["low"])
            sl_price = float(c_prev["low"]) + gap_s * 0.1
            sl_pips  = round((sl_price - current_close) / pip_size, 1)
            pass_sl  = MIN_SL_PIPS <= sl_pips <= MAX_SL_PIPS

            if gap_pips > best_gap_p:
                best_gap_p = gap_pips
                best_pass_atr = pass_atr
                best_pass_mss = pass_mss
                best_pass_sl  = pass_sl
                if pass_atr and pass_mss and pass_sl:
                    verdict = f"PASS SELL i={i}"
                elif not pass_atr:
                    verdict = f"FAIL_ATR SELL gap={gap_pips:.1f}p atr={round(atr_val/pip_size,1)}p"
                elif not pass_mss:
                    verdict = f"FAIL_MSS SELL close={round(current_close,5)} need<{round(float(c_prev['low']),5)}"
                elif not pass_sl:
                    verdict = f"FAIL_SL SELL sl={sl_pips}p"

    print(f"{symbol:<12} {price_scale:>12} {atr_val:>12.6f} {round(atr_val/pip_size,1):>10} {best_gap_p:>12.1f} {str(best_pass_atr):>10} {str(best_pass_mss):>10} {str(best_pass_sl):>10} {verdict}")
