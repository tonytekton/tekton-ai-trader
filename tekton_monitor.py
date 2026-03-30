import time
import sys
from datetime import datetime
import requests
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Redirect stdout/stderr to combined log
_log_file = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stdout = _log_file
sys.stderr = _log_file
class _PrefixedLogger:
    """Wraps a file stream and prepends [MONITOR] to every line written."""
    def __init__(self, stream):
        self._stream = stream
    def write(self, msg):
        if msg and msg != '\n':
            lines = msg.split('\n')
            prefixed = []
            for i, line in enumerate(lines):
                if line:
                    prefixed.append(f"[MONITOR] {line}")
                else:
                    prefixed.append(line)
            self._stream.write('\n'.join(prefixed))
        else:
            self._stream.write(msg)
    def flush(self):
        self._stream.flush()
    def fileno(self):
        return self._stream.fileno()

sys.stdout = _PrefixedLogger(sys.stdout)
sys.stderr = _PrefixedLogger(sys.stderr)

sys.stderr = sys.stdout

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
BRIDGE_URL = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY = os.getenv("BRIDGE_KEY")
HEADERS    = {"X-Bridge-Key": BRIDGE_KEY}

DB_PARAMS = {
    "host":     os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
    "database": "tekton-trader",
    "user":     "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD"),
}

# Known quote currencies for index/commodity symbols
INDEX_QUOTE_MAP = {
    "UK100":  "GBP", "DE40":   "EUR", "FR40":   "EUR", "EU50":   "EUR",
    "JP225":  "JPY", "US30":   "USD", "US500":  "USD", "USTEC":  "USD",
    "AUS200": "AUD", "HK50":   "HKD",
    "XAUUSD": "USD", "XAGUSD": "USD", "XTIUSD": "USD", "XBRUSD": "USD",
}


# ---------------------------------------------------------------------------
# NEWS WINDOW CHECK
# ---------------------------------------------------------------------------
def is_news_window(symbol: str, buffer_mins: int = 10) -> bool:
    """
    Returns True if a HIGH-impact event is within ±buffer_mins for any
    currency in the given symbol.  Failure is silent — returns False so
    trading is never blocked by a DB outage.
    """
    currencies = set()
    if symbol in INDEX_QUOTE_MAP:
        currencies.add(INDEX_QUOTE_MAP[symbol])
    elif len(symbol) == 6 and symbol.isalpha():
        currencies.add(symbol[:3].upper())
        currencies.add(symbol[3:].upper())
    if not currencies:
        return False
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur  = conn.cursor()
        cur.execute("""
            SELECT indicator_name, currency, event_date
            FROM economic_events
            WHERE impact_level = 'HIGH'
            AND currency = ANY(%s)
            AND event_date BETWEEN NOW() - INTERVAL '%s minutes'
                              AND NOW() + INTERVAL '%s minutes'
            ORDER BY event_date ASC
            LIMIT 1
        """, (list(currencies), buffer_mins, buffer_mins))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            ev_name, ev_ccy, ev_dt = row
            print(f"📰 NEWS WINDOW [{symbol}]: {ev_name} ({ev_ccy}) at {ev_dt.strftime('%H:%M')} UTC")
            return True
        return False
    except Exception as e:
        print(f"⚠️ is_news_window check failed: {e} — skipping news gate")
        return False


# ---------------------------------------------------------------------------
# SETTINGS  —  single source of truth: /data/system-settings
# ---------------------------------------------------------------------------
def fetch_config():
    """Fetches runtime config from the bridge."""
    res = requests.get(f"{BRIDGE_URL}/data/system-settings", headers=HEADERS, timeout=10)
    res.raise_for_status()
    return res.json()


# ---------------------------------------------------------------------------
# CIRCUIT BREAKER
# ---------------------------------------------------------------------------
def check_circuit_breaker(config):
    """Returns True if daily drawdown limit is breached — halt all trading."""
    max_dd_raw = config.get("daily_drawdown_limit")
    if max_dd_raw is None:
        raise KeyError("Field 'daily_drawdown_limit' missing from bridge config.")

    max_dd = float(max_dd_raw) * 100  # e.g. 0.05 → 5.0%

    res = requests.get(f"{BRIDGE_URL}/account/status", headers=HEADERS, timeout=10)
    res.raise_for_status()
    current_dd = float(res.json().get("drawdown_pct", 0))

    if current_dd >= max_dd:
        print(f"🚨 CIRCUIT BREAKER: {current_dd:.2f}% drawdown exceeds {max_dd:.2f}% limit! Halting.")
        return True
    return False


# ---------------------------------------------------------------------------
# PIP SIZE  —  always from bridge, never hardcoded
# ---------------------------------------------------------------------------
def get_pip_size(symbol):
    """
    Returns pip size from live bridge pipPosition.
    Formula: pip_size = 10^-pipPosition  (consistent with executor and strategy)
    """
    spec_res = requests.post(
        f"{BRIDGE_URL}/contract/specs",
        json={"symbol": symbol},
        headers=HEADERS,
        timeout=10
    )
    spec_res.raise_for_status()
    spec = spec_res.json().get("contract_specifications", {})
    pip_pos = spec.get("pipPosition")
    if pip_pos is None:
        raise ValueError(f"❌ pipPosition missing for {symbol} in contract specs — cannot calculate pip size")
    return 10 ** (-pip_pos)


# ---------------------------------------------------------------------------
# RISK MANAGER  —  monitors positions and closes at target R
# ---------------------------------------------------------------------------
def manage_risk(config):
    """
    Monitors open positions and closes any that have reached the Target Reward (R).
    - Field names aligned to /positions/list response: positionId, tradeSide, entryPrice, stopLoss, takeProfit
    - Current price fetched separately via /prices/current (bid/ask from state cache)
    - Positions with missing SL/TP trigger reapply_protection() before R management
    - All prices are RAW integers from cTrader — normalised using digits from contract specs
    """
    target_r = float(config.get("target_reward", 1.5))

    # Use /proxy/executions — fully enriched pipeline with position_state{} SL/TP and scaled decimals
    res = requests.get(f"{BRIDGE_URL}/proxy/executions", headers=HEADERS, timeout=15)
    if not res.text.strip():
        print("⚠️ Bridge returned empty response for /proxy/executions")
        return

    data = res.json()
    positions = [t for t in data.get("trades", []) if t.get("status") == "open"]
    if not positions:
        return

    print(f"🛡️ Monitoring {len(positions)} positions | Target: {target_r}R")

    # Fetch current prices for all symbols in one call
    symbols = list({p.get("symbol") for p in positions if p.get("symbol")})
    spot_map = {}
    try:
        price_res = requests.post(f"{BRIDGE_URL}/prices/current", json={"symbols": symbols}, headers=HEADERS, timeout=10)
        for p in price_res.json().get("prices", []):
            spot_map[p["symbol"]] = p
    except Exception as e:
        print(f"⚠️ Could not fetch spot prices: {e}")

    def reapply_protection(p_id, sym, p_side, missing_sl, missing_tp):
        """Look up original signal by broker_position_id, reapply SL/TP via sl_pips/tp_pips.
        If unrecoverable, close the position."""
        print(f"🚨 MISSING PROTECTION on {sym} pos_id={p_id} "
              f"(sl={'MISSING' if missing_sl else 'ok'}, tp={'MISSING' if missing_tp else 'ok'}) "
              f"— attempting recovery from signal record")
        try:
            sig_res = requests.get(
                f"{BRIDGE_URL}/proxy/signals",
                params={"broker_position_id": str(p_id), "limit": 1},
                headers=HEADERS, timeout=10
            )
            signals = sig_res.json().get("signals", [])
            if not signals:
                print(f"🚨 No signal record found for {sym} pos_id={p_id} — closing unprotected position")
                requests.post(f"{BRIDGE_URL}/trade/close", json={"position_id": p_id}, headers=HEADERS, timeout=15)
                print(f"🔴 CLOSED {sym} pos_id={p_id} — no signal record, could not reapply protection")
                return False

            sig     = signals[0]
            sl_pips_raw = sig.get("sl_pips")
            tp_pips_raw = sig.get("tp_pips")
            if not sl_pips_raw or not tp_pips_raw:
                raise ValueError(f"❌ sl_pips or tp_pips missing for signal {sig.get('uuid')} — cannot calculate R")
            sl_pips = float(sl_pips_raw)
            tp_pips = float(tp_pips_raw)

            if missing_sl and sl_pips == 0:
                print(f"🚨 Signal for {sym} pos_id={p_id} has sl_pips=0 — unrecoverable, closing position")
                requests.post(f"{BRIDGE_URL}/trade/close", json={"position_id": p_id}, headers=HEADERS, timeout=15)
                print(f"🔴 CLOSED {sym} pos_id={p_id} — sl_pips=0 in signal, cannot protect")
                return False

            # Bridge calculates absolute SL/TP price from entry + pips internally
            modify_payload = {"position_id": p_id}
            if missing_sl:
                modify_payload["sl_pips"] = sl_pips
            if missing_tp and tp_pips:
                modify_payload["tp_pips"] = tp_pips

            mod_res = requests.post(f"{BRIDGE_URL}/trade/modify", json=modify_payload, headers=HEADERS, timeout=15)
            if mod_res.json().get("success"):
                print(f"✅ Protection reapplied on {sym} pos_id={p_id} | sl_pips={sl_pips} tp_pips={tp_pips}")
                return True
            else:
                err = mod_res.json().get("error", "unknown")
                print(f"🚨 Modify failed for {sym} pos_id={p_id}: {err} — closing position")
                requests.post(f"{BRIDGE_URL}/trade/close", json={"position_id": p_id}, headers=HEADERS, timeout=15)
                print(f"🔴 CLOSED {sym} pos_id={p_id} — modify failed, could not protect")
                return False
        except Exception as ex:
            print(f"🚨 Exception in reapply_protection for {sym} pos_id={p_id}: {ex} — closing position")
            requests.post(f"{BRIDGE_URL}/trade/close", json={"position_id": p_id}, headers=HEADERS, timeout=15)
            print(f"🔴 CLOSED {sym} pos_id={p_id} — exception during recovery, closed for safety")
            return False

    for pos in positions:
        # Field names from /proxy/executions: id, symbol, side, entry_price, stop_loss, take_profit
        pos_id = str(pos.get("id") or "")
        symbol = pos.get("symbol", "?")
        side   = (pos.get("side") or "").upper()
        digits = pos.get("digits", 5)

        if not pos_id:
            print(f"⚠️ Position missing id — skipping: {pos}")
            continue

        # Prices are pre-scaled decimals from bridge (position_state{} enriched)
        entry = pos.get("entry_price")
        sl    = pos.get("stop_loss")
        tp    = pos.get("take_profit")
        if not entry or not sl or not tp:
            print(f"⚠️ Position {pos.get('position_id')} missing entry/sl/tp — skipping display")
            continue

        # SL/TP safety check — reapply or close if missing
        missing_sl = sl == 0
        missing_tp = tp == 0
        if missing_sl or missing_tp:
            recovered = reapply_protection(pos_id, symbol, side, missing_sl, missing_tp)
            if missing_sl and not recovered:
                continue  # position was closed, skip R management

        if not entry or not sl:
            print(f"⚠️ {symbol} [{pos_id}] missing entry or SL after recovery — skipping R management")
            continue

        # Get current mid price from spot cache
        spot = spot_map.get(symbol, {})
        bid_raw = spot.get("bid_raw", 0)
        ask_raw = spot.get("ask_raw", 0)
        if not bid_raw or not ask_raw:
            print(f"⚠️ {symbol} [{pos_id}] no spot price available — skipping R management")
            continue
        spot_digits = spot.get("digits", digits)
        current = ((bid_raw + ask_raw) / 2) / (10 ** spot_digits)

        risk_distance = abs(entry - sl)
        if risk_distance == 0:
            continue

        reward_distance = (current - entry) if side == "BUY" else (entry - current)
        current_r       = reward_distance / risk_distance

        if current_r >= target_r:
            # NEWS WINDOW GUARD: suppress close/modify actions during high-impact events
            if is_news_window(symbol, buffer_mins=10):
                print(f"⏸️ NEWS HOLD [{symbol}] [{pos_id}] — at {current_r:.2f}R but suppressing action during news window.")
                continue
            print(f"🎯 {symbol} [{pos_id}] hit {current_r:.2f}R ≥ {target_r}R — closing position.")
            close_res  = requests.post(
                f"{BRIDGE_URL}/trade/close",
                json={"position_id": pos_id},
                headers=HEADERS,
                timeout=10
            )
            close_data = close_res.json()
            if close_data.get("success"):
                print(f"✅ Closed {symbol} [{pos_id}] at {target_r}R target.")
            else:
                print(f"⚠️ Close failed for {symbol} [{pos_id}]: {close_data.get('error')}")


# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"🛡️ Tekton Monitor Engine Active. [{time.strftime('%Y-%m-%d %H:%M:%S')}]")
    while True:
        # Market hours gate — Fri 16:00 UTC → Sun 22:00 UTC
        now_utc = datetime.utcnow()
        wd = now_utc.weekday()
        hhmm = now_utc.hour * 60 + now_utc.minute
        market_closed = (
            (wd == 4 and hhmm >= 16 * 60) or  # Fri after 16:00
            (wd == 5) or                        # All Saturday
            (wd == 6 and hhmm < 22 * 60)        # Sun before 22:00
        )
        if market_closed:
            print(f"💤 MARKET CLOSED (Fri 16:00–Sun 22:00 UTC) — Monitor idle, sleeping 5 min.")
            time.sleep(300)
            continue
        print(f"⏱️ Heartbeat: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            config = fetch_config()
            if not check_circuit_breaker(config):
                manage_risk(config)
        except Exception as e:
            print(f"❌ MONITOR ERROR: {e}")
        time.sleep(15)
