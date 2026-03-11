import os
import sys
import time
import json
import base64
import requests
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Redirect stdout/stderr to log file AFTER imports
sys.stdout = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stderr = sys.stdout

# --- CONFIGURATION ---
BACKEND_FUNC_URL = "https://tekton-trade-hub.base44.app/api/functions/getBase64Config"
BASE44_HEADERS = {
    "Content-Type": "application/json",
    "api_key": "3636548f91ad4225bf0d8bfbc13b0eeb"
}

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
def fetch_base44_settings():
    """Fetches and decodes live settings from the Base44 Hub."""
    try:
        response = requests.post(BACKEND_FUNC_URL, json={}, headers=BASE44_HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        encoded_str = data.get("config")
        if not encoded_str:
            raise ValueError("❌ Base44 'config' key is missing.")
        decoded_bytes = base64.b64decode(encoded_str)
        return json.loads(decoded_bytes.decode("utf-8"))
    except Exception as e:
        print(f"⚠️ Base44 Fetch Error: {e}")
        raise

# ---------------------------------------------------------------------------
def get_live_pip_value(symbol, account_currency):
    """
    Calculates pip value by deriving the quote currency from the symbol name
    and finding the conversion rate to the account currency.
    """
    spec_res = requests.post(f"{BRIDGE_BASE_URL}/contract/specs", json={"symbol": symbol}, headers=HEADERS)
    symbol_spec = spec_res.json().get("contract_specifications", {})

    pip_pos  = symbol_spec.get("pipPosition", symbol_spec.get("digits", 5))
    pip_size = 10 ** -pip_pos

    # Derive quote currency from symbol name (last 3 chars for standard forex pairs)
    quote_currency = symbol[-3:].upper()
    acc_currency   = account_currency.upper()

    if quote_currency == acc_currency:
        return pip_size * 1.0

    # Build candidate conversion symbol names
    direct   = f"{quote_currency}{acc_currency}"
    indirect = f"{acc_currency}{quote_currency}"

    all_symbols_res  = requests.get(f"{BRIDGE_BASE_URL}/symbols/list", headers=HEADERS)
    available_names  = {s["name"].upper() for s in all_symbols_res.json().get("symbols", [])}

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
        price_res  = requests.post(f"{BRIDGE_BASE_URL}/prices/current", json={"symbols": [conv_symbol]}, headers=HEADERS)
        price_json = price_res.json()
        prices_list = price_json.get("prices", [])
        if prices_list:
            price_data = prices_list[0]
            break
        if conv_symbol in (price_json.get("missing_symbols") or []) + (price_json.get("warming_up_symbols") or []):
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
    """Calculates volume in centilots based on live equity and risk %."""
    settings = fetch_base44_settings()
    risk_pct  = float(settings.get("RISK_PCT", 0.005))

    acc_res      = requests.get(f"{BRIDGE_BASE_URL}/account/status", headers=HEADERS)
    acc_data     = acc_res.json()
    free_margin  = float(acc_data.get("free_margin", 0))
    acc_currency = acc_data.get("currency", "EUR")

    total_risk_cash   = free_margin * risk_pct
    pip_value_per_unit = get_live_pip_value(symbol, acc_currency)

    required_units  = total_risk_cash / (sl_pips * pip_value_per_unit)
    protocol_volume = int(required_units * 10_000_000)

    spec_res = requests.post(f"{BRIDGE_BASE_URL}/contract/specs", json={"symbol": symbol}, headers=HEADERS)
    spec     = spec_res.json().get("contract_specifications", {})
    step     = spec.get("stepVolume_centilots", 100)
    min_v    = spec.get("minVolume_centilots", 100)

    final_vol = max((protocol_volume // step) * step, min_v)

    # VOLUME SANITY CAP (10M centilots)
    if final_vol > 10_000_000:
        final_vol = 10_000_000

    print(f"📊 Risk: {acc_currency} {total_risk_cash:,.2f} | PipVal/Unit: {pip_value_per_unit:.6f} | Vol: {final_vol}")
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

        # cTrader relativeStopLoss/relativeTakeProfit are in POINTS (0.1 pip = 1 point)
        # So 1 pip = 10 points
        rel_sl = int(sl_pips * 10)
        rel_tp = int(tp_pips * 10)

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
            print(f"✅ Trade & Protection Verified: {symbol} ID: {pos_id}")
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
                        cur.execute("UPDATE signals SET status = 'PENDING' WHERE signal_uuid = %s", (str(s_uuid),))
                    conn.commit()

        except Exception as e:
            print(f"⚠️ Loop Error: {e}")
        finally:
            if cur: cur.close()
            if conn: conn.close()
        time.sleep(5)

if __name__ == "__main__":
    poll_signals()
