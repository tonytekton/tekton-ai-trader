import os
import sys
import time
import json
import requests
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Redirect stdout/stderr to log file AFTER imports
sys.stdout = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stderr = sys.stdout

# --- CONFIGURATION ---
BRIDGE_BASE_URL = "http://localhost:8080"
BRIDGE_EXECUTE_URL = f"{BRIDGE_BASE_URL}/trade/execute"
BRIDGE_MODIFY_URL  = f"{BRIDGE_BASE_URL}/trade/modify"
BRIDGE_KEY = os.getenv("BRIDGE_KEY")
HEADERS = {"X-Bridge-Key": BRIDGE_KEY}

DB_PARAMS = {
    "host":     "172.16.64.3",
    "database": "tekton-trader",
    "user":     "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD")
}

# ---------------------------------------------------------------------------
# Known pip sizes for non-forex instruments (cTrader).
# Forex pairs derive pip_size from pipPosition via contract specs.
# Indices/commodities use fixed values.
PIP_SIZE_MAP = {
    "UK100":  1.0,   "DE40":   1.0,   "FR40":   1.0,   "EU50":   1.0,
    "JP225":  1.0,   "US30":   1.0,   "US500":  0.1,   "USTEC":  0.1,
    "AUS200": 1.0,   "HK50":   1.0,
    "XAUUSD": 0.1,   "XAGUSD": 0.01,
    "XTIUSD": 0.01,  "XBRUSD": 0.01,
}

# Known quote currencies for index/commodity symbols (can't derive from last 3 chars).
INDEX_QUOTE_MAP = {
    "UK100":  "GBP", "DE40":   "EUR", "FR40":   "EUR", "EU50":   "EUR",
    "JP225":  "JPY", "US30":   "USD", "US500":  "USD", "USTEC":  "USD",
    "AUS200": "AUD", "HK50":   "HKD",
    "XAUUSD": "USD", "XAGUSD": "USD", "XTIUSD": "USD", "XBRUSD": "USD",
}

# cTrader: relativeStopLoss/relativeTakeProfit are in POINTS.
# For standard 5-digit forex: 1 pip = 10 points.
# For JPY pairs (2-digit): 1 pip = 10 points (same — pipPosition handles the scaling).
# For indices with pip_size=1.0: 1 pip = 10 points.
# This constant is correct for all instruments when sl_pips comes from the strategy as true pips.
POINTS_PER_PIP = 10

# ---------------------------------------------------------------------------
def fetch_settings():
    """Fetches live settings from the SQL settings table via bridge."""
    try:
        response = requests.get(f"{BRIDGE_BASE_URL}/data/settings", headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        return {
            "auto_trade": data.get("auto_trade", False),
            "friday_flush": data.get("friday_flush", False),
            "risk_pct": float(data.get("risk_pct", 0.01)),
            "target_reward": float(data.get("target_reward", 1.8)),
            "daily_drawdown_limit": float(data.get("daily_drawdown_limit", 0.05))
        }
    except Exception as e:
        print(f"⚠️ Settings Fetch Error: {e}")
        raise

# ---------------------------------------------------------------------------
def get_live_pip_value(symbol, account_currency):
    """
    Returns pip value per 1 lot in account currency.
    Uses hardcoded pip sizes for indices/commodities.
    Derives pip size from cTrader pipPosition for forex pairs.
    """
    sym_upper = symbol.upper()
    acc_currency = account_currency.upper()

    # Determine pip size
    if sym_upper in PIP_SIZE_MAP:
        pip_size = PIP_SIZE_MAP[sym_upper]
    else:
        spec_res   = requests.post(f"{BRIDGE_BASE_URL}/contract/specs", json={"symbol": symbol}, headers=HEADERS)
        symbol_spec = spec_res.json().get("contract_specifications", {})
        pip_pos    = symbol_spec.get("pipPosition", 5)
        # cTrader pipPosition: e.g. 5 for EURUSD (0.00001 pip) → pip_size = 0.0001
        # pipPosition is the number of decimal places of the price quote.
        # A pip is 1 unit at (pipPosition - 1) decimal places → 10^-(pipPosition-1)
        pip_size   = 10 ** -(pip_pos - 1)

    # Determine quote currency
    quote_currency = INDEX_QUOTE_MAP.get(sym_upper, sym_upper[-3:])

    if quote_currency == acc_currency:
        # No conversion needed: pip value = pip_size * lot_size (100,000 for forex, 1 for indices)
        # For indices, the lot size is 1, so pip_value = pip_size
        # This is handled correctly — the ratio is 1:1
        return pip_size

    # Need conversion rate: quote_currency → account_currency
    direct   = f"{quote_currency}{acc_currency}"
    indirect = f"{acc_currency}{quote_currency}"

    all_symbols_res = requests.get(f"{BRIDGE_BASE_URL}/symbols/list", headers=HEADERS)
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
def calculate_professional_lot_size(symbol, sl_pips):
    """
    Calculates volume in centilots based on live equity and risk %.

    cTrader volume units: centilots (100 = 1 standard lot).
    Formula: required_lots = risk_cash / (sl_pips * pip_value_per_lot)
    Then: centilots = required_lots * 100
    """
    settings = fetch_settings()
    risk_pct = settings.get("risk_pct", 0.01)

    acc_res      = requests.get(f"{BRIDGE_BASE_URL}/account/status", headers=HEADERS)
    acc_data     = acc_res.json()
    free_margin  = float(acc_data.get("free_margin", 0))
    acc_currency = acc_data.get("currency", "EUR")

    total_risk_cash    = free_margin * risk_pct
    pip_value_per_unit = get_live_pip_value(symbol, acc_currency)

    # required_units is in lots; convert to centilots (* 100)
    required_lots   = total_risk_cash / (sl_pips * pip_value_per_unit)
    protocol_volume = int(required_lots * 100)

    spec_res = requests.post(f"{BRIDGE_BASE_URL}/contract/specs", json={"symbol": symbol}, headers=HEADERS)
    spec     = spec_res.json().get("contract_specifications", {})
    step     = spec.get("stepVolume_centilots", 100)
    min_v    = spec.get("minVolume_centilots", 100)
    max_v    = spec.get("maxVolume_centilots", 100_000)  # honour broker max

    final_vol = max((protocol_volume // step) * step, min_v)
    final_vol = min(final_vol, max_v)  # never exceed broker max

    print(f"📊 Risk: {acc_currency} {total_risk_cash:,.2f} | PipVal/Unit: {pip_value_per_unit:.6f} | Lots: {final_vol/100:.2f} | Vol: {final_vol}")
    return final_vol

# ---------------------------------------------------------------------------
def is_symbol_already_open(symbol):
    """Checks if a position for the given symbol is already open."""
    try:
        res = requests.get(f"{BRIDGE_BASE_URL}/positions/list", headers=HEADERS, timeout=10)
        positions = res.json().get("positions", [])
        return any(p.get("symbol") == symbol for p in positions)
    except Exception as e:
        print(f"⚠️ is_symbol_already_open error: {e}")
        return False

# ---------------------------------------------------------------------------
def execute_trade(s_uuid, symbol, side, timeframe, sl_pips, tp_pips):
    try:
        if is_symbol_already_open(symbol):
            print(f"🚫 {symbol} already open. Skipping.")
            return True

        vol = calculate_professional_lot_size(symbol, sl_pips)

        # cTrader relativeStopLoss/relativeTakeProfit are in POINTS.
        # sl_pips from the strategy are true pips → multiply by POINTS_PER_PIP (10).
        rel_sl = int(sl_pips * POINTS_PER_PIP)
        rel_tp = int(tp_pips * POINTS_PER_PIP)

        payload = {
            "symbol": symbol,
            "side": side.upper(),
            "volume": vol,
            "comment": str(s_uuid),
            "rel_sl": rel_sl,
            "rel_tp": rel_tp
        }

        print(f"🚀 Executing {symbol} | SL: {sl_pips} pips ({rel_sl} pts) | TP: {tp_pips} pips ({rel_tp} pts)")
        response = requests.post(BRIDGE_EXECUTE_URL, json=payload, headers=HEADERS, timeout=30)
        result = response.json()
        print(f"🔍 Bridge response: {result}")

        if result.get("success"):
            pos_id = result.get("position_id")
            print(f"✅ Trade Executed: {symbol} ID: {pos_id}")
            return True
        else:
            print(f"❌ Execution Failed: {result.get('error')}")
            return False

    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        return False

# ---------------------------------------------------------------------------
def poll_signals():
    print("🧠 Tekton Executor Active.")
    while True:
        conn, cur = None, None
        try:
            # Gate on AUTO_TRADE setting
            settings = fetch_settings()
            if not settings.get("auto_trade"):
                print("🚫 AUTO_TRADE disabled — skipping signal processing.")
                time.sleep(30)
                continue

            conn = psycopg2.connect(**DB_PARAMS)
            cur  = conn.cursor()

            # ✅ FIX: Read sl_pips and tp_pips from the signals table
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

                # Guard: reject zero or negative values
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
                        # Mark FAILED not PENDING — prevents infinite retry on broker-rejected orders
                        cur.execute("UPDATE signals SET status = 'FAILED' WHERE signal_uuid = %s", (str(s_uuid),))
                    conn.commit()

        except Exception as e:
            print(f"⚠️ Loop Error: {e}")
        finally:
            if cur: cur.close()
            if conn: conn.close()
        time.sleep(5)

if __name__ == "__main__":
    poll_signals()
