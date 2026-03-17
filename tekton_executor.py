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
# PIP_SIZE_MAP removed. All pip sizes are derived dynamically from cTrader
# contract specs using: pip_size = 10 ^ -pipPosition
# This is correct for all instrument types:
#   Forex 4-digit (EURUSD):  pipPosition=4 → pip_size=0.0001
#   JPY pairs:               pipPosition=2 → pip_size=0.01
#   Indices (UK100, DE40..): pipPosition=1 → pip_size=0.1
#   Gold/Silver/Oil:         pipPosition=2 → pip_size=0.01
#   Natural Gas:             pipPosition=3 → pip_size=0.001
# ---------------------------------------------------------------------------

# Known quote currencies for index/commodity symbols (can't derive from last 3 chars).
INDEX_QUOTE_MAP = {
    "UK100":  "GBP", "DE40":   "EUR", "FR40":   "EUR", "EU50":   "EUR",
    "JP225":  "JPY", "US30":   "USD", "US500":  "USD", "USTEC":  "USD",
    "AUS200": "AUD", "HK50":   "HKD", "F40":    "EUR", "STOXX50": "EUR",
    "XAUUSD": "USD", "XAGUSD": "USD", "XTIUSD": "USD", "XBRUSD": "USD",
    "XNGUSD": "USD", "XPDUSD": "USD", "XPTUSD": "USD",
}

# cTrader: relativeStopLoss/relativeTakeProfit are in POINTS.
# 1 pip = 10 points for all instruments (pipPosition handles the scaling per instrument).
# sl_pips and tp_pips from strategies are always true pips → multiply by POINTS_PER_PIP.
POINTS_PER_PIP = 10

# ---------------------------------------------------------------------------
def fetch_settings():
    """Fetches live settings from the SQL settings table via bridge."""
    try:
        response = requests.get(f"{BRIDGE_BASE_URL}/data/system-settings", headers=HEADERS, timeout=10)
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
def get_contract_specs(symbol):
    """
    Fetches contract specifications for a symbol from the bridge.
    Returns the contract_specifications dict.
    Raises on failure — callers must not proceed without valid specs.
    """
    res = requests.post(
        f"{BRIDGE_BASE_URL}/contract/specs",
        json={"symbol": symbol},
        headers=HEADERS,
        timeout=10
    )
    res.raise_for_status()
    specs = res.json().get("contract_specifications", {})
    if not specs:
        raise ValueError(f"Empty contract specs returned for {symbol}")
    return specs

# ---------------------------------------------------------------------------
def get_pip_size(symbol_spec):
    """
    Derives pip size from cTrader pipPosition in contract specs.

    cTrader pipPosition is the decimal place of 1 pip:
        pipPosition=4 → pip_size=0.0001  (EURUSD, GBPUSD, most forex)
        pipPosition=2 → pip_size=0.01    (JPY pairs, XAUUSD, XAGUSD, oils)
        pipPosition=1 → pip_size=0.1     (indices: UK100, DE40, JP225 etc)
        pipPosition=3 → pip_size=0.001   (XNGUSD)

    Formula: pip_size = 10 ^ -pipPosition
    """
    pip_pos = symbol_spec.get("pipPosition")
    if pip_pos is None:
        raise ValueError("pipPosition missing from contract specs")
    return 10 ** -pip_pos

# ---------------------------------------------------------------------------
def get_live_pip_value(symbol, symbol_spec, account_currency, lot_size_units):
    """
    Returns pip value per 1 LOT in account currency.
    Derives pip size dynamically from contract specs — no hardcoded values.

    pip_value_per_lot = pip_size * lot_size_units (if quote == account currency)
    pip_value_per_lot = pip_size * lot_size_units * conversion_rate (if conversion needed)

    lot_size_units = lotSize_centilots / 100
        EURUSD: 10,000,000 / 100 = 100,000 units per lot
        UK100:  100 / 100        = 1 unit per lot
        XAUUSD: 10,000 / 100     = 100 units per lot
    """
    sym_upper    = symbol.upper()
    acc_currency = account_currency.upper()

    # pip_size derived from live contract specs — no hardcoding
    pip_size = get_pip_size(symbol_spec)

    # Determine quote currency
    quote_currency = INDEX_QUOTE_MAP.get(sym_upper, sym_upper[-3:]).upper()

    if quote_currency == acc_currency:
        # No conversion needed — pip value per lot = pip_size * units per lot
        return pip_size * lot_size_units

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
    return pip_size * lot_size_units * conversion_rate

# ---------------------------------------------------------------------------
def calculate_professional_lot_size(symbol, sl_pips):
    """
    Calculates volume in cTrader native units based on live equity and risk %.

    cTrader volume units are instrument-specific centilots derived from lotSize:
        Forex (EURUSD):  lotSize_centilots = 10,000,000  (1 lot = 10M centilots)
        Indices (UK100): lotSize_centilots = 100
        Gold (XAUUSD):   lotSize_centilots = 10,000
        Silver (XAGUSD): lotSize_centilots = 100,000
        Oil (XTIUSD):    lotSize_centilots = 10,000

    Formula:
        risk_cash       = free_margin * risk_pct
        pip_value       = pip_size * conversion_rate (per lot, in account currency)
        required_lots   = risk_cash / (sl_pips * pip_value)
        protocol_volume = int(required_lots * lotSize_centilots)

    Volume is then snapped to broker step and clamped to min/max.
    """
    settings = fetch_settings()
    risk_pct = settings.get("risk_pct", 0.01)

    acc_res      = requests.get(f"{BRIDGE_BASE_URL}/account/status", headers=HEADERS)
    acc_data     = acc_res.json()
    free_margin  = float(acc_data.get("free_margin", 0))
    acc_currency = acc_data.get("currency", "EUR")

    # Fetch contract specs once — used for pip_size, lot_size, and volume constraints
    symbol_spec = get_contract_specs(symbol)

    # lot_size_units: how many price units make 1 standard lot for this instrument.
    # centilots / 100 = units. EURUSD=100,000 | UK100=1 | XAUUSD=100
    lot_size         = symbol_spec.get("lotSize_centilots", 10_000_000)
    lot_size_units   = lot_size / 100

    pip_value_per_lot = get_live_pip_value(symbol, symbol_spec, acc_currency, lot_size_units)

    total_risk_cash = free_margin * risk_pct
    required_lots   = total_risk_cash / (sl_pips * pip_value_per_lot)

    # Multiply required_lots by lotSize_centilots to get protocol volume in centilots.
    protocol_volume = int(required_lots * lot_size)

    # Snap to broker step, enforce min/max — all values in same centilot units
    step    = symbol_spec.get("stepVolume_centilots", lot_size)
    min_v   = symbol_spec.get("minVolume_centilots",  lot_size)
    max_v   = symbol_spec.get("maxVolume_centilots",  lot_size * 100)

    final_vol = max((protocol_volume // step) * step, min_v)
    final_vol = min(final_vol, max_v)

    final_lots = final_vol / lot_size
    print(f"📊 {symbol} | Risk: {acc_currency} {total_risk_cash:,.2f} | PipVal/Lot: {pip_value_per_lot:.6f} | Lots: {final_lots:.4f} | Vol: {final_vol}")
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
        # sl_pips/tp_pips from strategy are true pips → multiply by POINTS_PER_PIP (10).
        rel_sl = int(sl_pips * POINTS_PER_PIP)
        rel_tp = int(tp_pips * POINTS_PER_PIP)

        payload = {
            "symbol": symbol,
            "side":   side.upper(),
            "volume": vol,
            "comment": str(s_uuid),
            "rel_sl": rel_sl,
            "rel_tp": rel_tp
        }

        print(f"🚀 Executing {symbol} | Side: {side} | SL: {sl_pips} pips ({rel_sl} pts) | TP: {tp_pips} pips ({rel_tp} pts)")
        response = requests.post(BRIDGE_EXECUTE_URL, json=payload, headers=HEADERS, timeout=30)
        result   = response.json()
        print(f"🔍 Bridge response: {result}")

        if result.get("success"):
            pos_id      = result.get("position_id")
            entry_price = result.get("entry_price")
            print(f"✅ Trade Executed: {symbol} | Position ID: {pos_id}")

            # Write broker_position_id back to signals and insert into executions table
            try:
                db_conn = psycopg2.connect(**DB_PARAMS)
                db_cur  = db_conn.cursor()

                # Update signals with broker position ID
                db_cur.execute(
                    "UPDATE signals SET broker_position_id = %s WHERE signal_uuid = %s",
                    (str(pos_id), str(s_uuid))
                )

                # Insert execution record — position_id is the primary key
                db_cur.execute("""
                    INSERT INTO executions (position_id, signal_uuid, symbol, entry_price, status)
                    VALUES (%s, %s, %s, %s, 'OPEN')
                    ON CONFLICT (position_id) DO NOTHING;
                """, (int(pos_id), str(s_uuid), symbol, entry_price))

                db_conn.commit()
                print(f"📝 Recorded: signals.broker_position_id={pos_id} | executions row inserted.")
            except Exception as db_err:
                print(f"⚠️ DB record error (trade still executed): {db_err}")
            finally:
                if db_cur:  db_cur.close()
                if db_conn: db_conn.close()

            return True
        else:
            print(f"❌ Execution Failed: {result.get('error')}")
            return False

    except Exception as e:
        print(f"❌ CRITICAL ERROR in execute_trade: {e}")
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

                # Guard: reject zero or negative SL/TP
                if sl_pips <= 0 or tp_pips <= 0:
                    print(f"⚠️ Invalid SL/TP for {sym}: sl={sl_pips} tp={tp_pips}. Marking FAILED.")
                    cur.execute("UPDATE signals SET status = 'FAILED' WHERE signal_uuid = %s", (str(s_uuid),))
                    conn.commit()
                else:
                    cur.execute("UPDATE signals SET status = 'EXECUTING' WHERE signal_uuid = %s", (str(s_uuid),))
                    conn.commit()
                    time.sleep(1)  # brief pause — lets position list update before duplicate check

                    if execute_trade(s_uuid, sym, s_type, tf, float(sl_pips), float(tp_pips)):
                        cur.execute("UPDATE signals SET status = 'COMPLETED' WHERE signal_uuid = %s", (str(s_uuid),))
                    else:
                        # Mark FAILED — prevents infinite retry on broker-rejected orders
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
