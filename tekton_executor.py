import os
import sys
import time
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Redirect stdout/stderr to log file
sys.stdout = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stderr = sys.stdout

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
BRIDGE_BASE_URL   = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_EXECUTE_URL = f"{BRIDGE_BASE_URL}/trade/execute"
BRIDGE_KEY        = os.getenv("BRIDGE_KEY")
HEADERS           = {"X-Bridge-Key": BRIDGE_KEY}

DB_PARAMS = {
    "host":     os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
    "database": "tekton-trader",
    "user":     "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD")
}

# Known quote currencies for index/commodity symbols (can't derive from last 3 chars).
INDEX_QUOTE_MAP = {
    "UK100":  "GBP", "DE40":   "EUR", "FR40":   "EUR", "EU50":   "EUR",
    "JP225":  "JPY", "US30":   "USD", "US500":  "USD", "USTEC":  "USD",
    "AUS200": "AUD", "HK50":   "HKD",
    "XAUUSD": "USD", "XAGUSD": "USD", "XTIUSD": "USD", "XBRUSD": "USD",
}

# cTrader: relativeStopLoss/relativeTakeProfit are in POINTS.
# 1 pip = 10 points for all instruments (pipPosition handles the scaling).
POINTS_PER_PIP = 10

# ---------------------------------------------------------------------------
# SETTINGS  —  single source of truth: /data/system-settings
# ---------------------------------------------------------------------------
def fetch_settings():
    """Fetches live trading settings from the bridge."""
    try:
        response = requests.get(f"{BRIDGE_BASE_URL}/data/system-settings", headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        return {
            "auto_trade":               data.get("auto_trade", False),
            "friday_flush":             data.get("friday_flush", False),
            "risk_pct":                 float(data.get("risk_pct", 0.01)),
            "target_reward":            float(data.get("target_reward", 1.8)),
            "daily_drawdown_limit":     float(data.get("daily_drawdown_limit", 0.05)),
            "max_session_exposure_pct": float(data.get("max_session_exposure_pct", 4.0))
        }
    except Exception as e:
        print(f"⚠️ Settings Fetch Error: {e}")
        raise

# ---------------------------------------------------------------------------
# PIP SIZE  —  always from bridge, never hardcoded
# ---------------------------------------------------------------------------
def get_pip_size(symbol):
    """
    Returns pip size derived from live bridge pipPosition.
    Formula: pip_size = 10^-pipPosition
    e.g. pipPosition=4 → pip_size=0.0001 (standard forex)
         pipPosition=2 → pip_size=0.01   (JPY pairs, indices)
    """
    try:
        spec_res = requests.post(
            f"{BRIDGE_BASE_URL}/contract/specs",
            json={"symbol": symbol},
            headers=HEADERS,
            timeout=10
        )
        spec = spec_res.json().get("contract_specifications", {})
        pip_pos = spec.get("pipPosition", 4)
        return 10 ** (-pip_pos)
    except Exception as e:
        print(f"⚠️ get_pip_size error for {symbol}: {e} — using default 0.0001")
        return 0.0001

# ---------------------------------------------------------------------------
# PIP VALUE  —  value of 1 pip per 1 lot in account currency
# ---------------------------------------------------------------------------
def get_live_pip_value(symbol, account_currency):
    """
    Returns pip value per 1 lot in account currency.
    Uses live pipPosition from bridge for all instruments.
    """
    sym_upper    = symbol.upper()
    acc_currency = account_currency.upper()
    pip_size     = get_pip_size(symbol)

    # Determine quote currency
    quote_currency = INDEX_QUOTE_MAP.get(sym_upper, sym_upper[-3:])

    if quote_currency == acc_currency:
        # No conversion needed
        return pip_size

    # Need conversion rate: quote_currency → account_currency
    direct   = f"{quote_currency}{acc_currency}"
    indirect = f"{acc_currency}{quote_currency}"

    all_symbols_res = requests.get(f"{BRIDGE_BASE_URL}/symbols", headers=HEADERS)
    available_names = {s["name"].upper() for s in all_symbols_res.json().get("symbols", [])}

    if direct in available_names:
        conv_symbol = direct
        invert = False
    elif indirect in available_names:
        conv_symbol = indirect
        invert = True
    else:
        raise ValueError(f"Conversion failed for {symbol}: no symbol for {direct} or {indirect}")

    # Fetch price with retry for subscription warm-up
    price_data = {}
    for attempt in range(5):
        price_res   = requests.post(f"{BRIDGE_BASE_URL}/prices/current", json={"symbols": [conv_symbol]}, headers=HEADERS)
        price_json  = price_res.json()
        prices_list = price_json.get("prices", [])
        if prices_list:
            price_data = prices_list[0]
            break
        warming = (price_json.get("missing_symbols") or []) + (price_json.get("warming_up_symbols") or [])
        if conv_symbol in warming:
            print(f"⏳ Waiting for price subscription: {conv_symbol} (attempt {attempt+1}/5)")
            time.sleep(2)
        else:
            break

    avg_price = (price_data.get("bid_raw", 0) + price_data.get("ask_raw", 0)) / 2 / 1_000_000
    if avg_price == 0:
        raise ValueError(f"Conversion failed for {symbol}: no price for {conv_symbol}")

    conversion_rate = (1.0 / avg_price) if invert else avg_price
    return pip_size * conversion_rate

# ---------------------------------------------------------------------------
# LOT SIZE CALCULATION
# ---------------------------------------------------------------------------
def calculate_professional_lot_size(symbol, sl_pips):
    """
    Calculates volume in centilots based on live equity and risk %.

    cTrader volume units: centilots (100 = 1 standard lot).
    Formula: required_lots = risk_cash / (sl_pips * pip_value_per_lot)
             centilots = required_lots * 100
    """
    settings         = fetch_settings()
    risk_pct         = settings.get("risk_pct", 0.01)

    acc_res          = requests.get(f"{BRIDGE_BASE_URL}/account/status", headers=HEADERS)
    acc_data         = acc_res.json()
    free_margin      = float(acc_data.get("free_margin", 0))
    acc_currency     = acc_data.get("currency", "EUR")

    total_risk_cash    = free_margin * risk_pct
    pip_value_per_unit = get_live_pip_value(symbol, acc_currency)

    required_lots   = total_risk_cash / (sl_pips * pip_value_per_unit)
    protocol_volume = int(required_lots * 100)

    spec_res = requests.post(f"{BRIDGE_BASE_URL}/contract/specs", json={"symbol": symbol}, headers=HEADERS)
    spec     = spec_res.json().get("contract_specifications", {})
    step     = spec.get("stepVolume_centilots", 100)
    min_v    = spec.get("minVolume_centilots", 100)
    max_v    = spec.get("maxVolume_centilots", 100_000)

    final_vol = max((protocol_volume // step) * step, min_v)
    final_vol = min(final_vol, max_v)

    print(f"📊 Risk: {acc_currency} {total_risk_cash:,.2f} | PipVal/Unit: {pip_value_per_unit:.6f} | Lots: {final_vol/100:.2f} | Vol: {final_vol}")
    return final_vol

# ---------------------------------------------------------------------------
# DUPLICATE CHECK
# ---------------------------------------------------------------------------
def is_symbol_already_open(symbol):
    """Checks if a position for this symbol is already open."""
    try:
        res = requests.get(f"{BRIDGE_BASE_URL}/positions/list", headers=HEADERS, timeout=10)
        positions = res.json().get("positions", [])
        return any(p.get("symbol") == symbol for p in positions)
    except Exception as e:
        print(f"⚠️ is_symbol_already_open error: {e}")
        return False

# ---------------------------------------------------------------------------
# SESSION EXPOSURE CHECK
# ---------------------------------------------------------------------------
def get_current_session_exposure_pct():
    """
    Returns total current session exposure as a percentage of account equity.
    Counts all open positions from the bridge and estimates each position's
    risk as risk_pct (since all positions are sized to exactly risk_pct per trade).
    Uses live position count × risk_pct as the exposure estimate.
    """
    try:
        res = requests.get(f"{BRIDGE_BASE_URL}/positions/list", headers=HEADERS, timeout=10)
        positions = res.json().get("positions", [])
        settings = fetch_settings()
        risk_pct_per_trade = settings.get("risk_pct", 0.01)
        # Each open position represents exactly risk_pct exposure
        total_exposure_pct = len(positions) * risk_pct_per_trade * 100
        return total_exposure_pct, len(positions)
    except Exception as e:
        print(f"⚠️ get_current_session_exposure_pct error: {e} — assuming 0%")
        return 0.0, 0

# ---------------------------------------------------------------------------
# TRADE EXECUTION
# ---------------------------------------------------------------------------
def execute_trade(s_uuid, symbol, side, timeframe, sl_pips, tp_pips):
    try:
        if is_symbol_already_open(symbol):
            print(f"🚫 {symbol} already open. Skipping.")
            return True

        vol = calculate_professional_lot_size(symbol, sl_pips)

        # cTrader relativeStopLoss/relativeTakeProfit are in POINTS (1 pip = 10 points)
        rel_sl = int(sl_pips * POINTS_PER_PIP)
        rel_tp = int(tp_pips * POINTS_PER_PIP)

        payload = {
            "symbol":  symbol,
            "side":    side.upper(),
            "volume":  vol,
            "comment": str(s_uuid),
            "rel_sl":  rel_sl,
            "rel_tp":  rel_tp
        }

        print(f"🚀 Executing {symbol} | SL: {sl_pips}p ({rel_sl}pts) | TP: {tp_pips}p ({rel_tp}pts)")
        response = requests.post(BRIDGE_EXECUTE_URL, json=payload, headers=HEADERS, timeout=30)
        result   = response.json()
        print(f"🔍 Bridge response: {result}")

        if result.get("success"):
            print(f"✅ Trade Executed: {symbol} ID: {result.get('position_id')}")
            return True
        else:
            print(f"❌ Execution Failed: {result.get('error')}")
            return False

    except Exception as e:
        print(f"❌ CRITICAL ERROR in execute_trade: {e}")
        return False

# ---------------------------------------------------------------------------
# SIGNAL POLL LOOP
# ---------------------------------------------------------------------------
def poll_signals():
    print(f"🧠 Tekton Executor Active. [{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    while True:
        conn, cur = None, None
        try:
            settings = fetch_settings()
            if not settings.get("auto_trade"):
                print("🚫 AUTO_TRADE disabled — skipping signal processing.")
                time.sleep(30)
                continue

            # --- SESSION EXPOSURE GATE ---
            max_exposure = settings.get("max_session_exposure_pct", 4.0)
            current_exposure, open_count = get_current_session_exposure_pct()
            if current_exposure >= max_exposure:
                print(f"🛑 Session exposure cap reached: {current_exposure:.1f}% / {max_exposure:.1f}% max ({open_count} open positions). No new trades.")
                time.sleep(30)
                continue

            conn = psycopg2.connect(**DB_PARAMS)
            cur  = conn.cursor()

            cur.execute("""
                SELECT signal_uuid, symbol, signal_type, timeframe, sl_pips, tp_pips
                FROM signals
                WHERE status = 'PENDING'
                AND sl_pips IS NOT NULL
                AND tp_pips IS NOT NULL
                LIMIT 1;
            """)
            signal = cur.fetchone()

            if signal:
                s_uuid, sym, s_type, tf, sl_pips, tp_pips = signal

                if sl_pips <= 0 or tp_pips <= 0:
                    print(f"⚠️ Invalid SL/TP for {sym}: sl={sl_pips} tp={tp_pips}. Marking FAILED.")
                    cur.execute("UPDATE signals SET status = 'FAILED' WHERE signal_uuid = %s", (str(s_uuid),))
                    conn.commit()
                else:
                    cur.execute("UPDATE signals SET status = 'EXECUTING' WHERE signal_uuid = %s", (str(s_uuid),))
                    conn.commit()

                    if execute_trade(s_uuid, sym, s_type, tf, float(sl_pips), float(tp_pips)):
                        cur.execute("UPDATE signals SET status = 'COMPLETED' WHERE signal_uuid = %s", (str(s_uuid),))
                    else:
                        cur.execute("UPDATE signals SET status = 'FAILED' WHERE signal_uuid = %s", (str(s_uuid),))
                    conn.commit()

        except Exception as e:
            print(f"⚠️ Loop Error: {e}")
        finally:
            if cur:  cur.close()
            if conn: conn.close()
        time.sleep(5)

if __name__ == "__main__":
    poll_signals()
