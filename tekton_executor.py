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
            "max_session_exposure_pct": float(data.get("max_session_exposure_pct", 4.0)),
            "max_lots":                 float(data.get("max_lots", 50.0))
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
        if not spec_res.text.strip(): raise ValueError(f"Empty response from /contract/specs for {symbol}")
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

    all_symbols_res = requests.get(f"{BRIDGE_BASE_URL}/symbols/list", headers=HEADERS)
    if not all_symbols_res.text.strip(): raise ValueError("Empty response from /symbols/list")
    available_names = {s["name"].upper() for s in all_symbols_res.json().get("symbols", [])}

    two_leg = False
    conv_symbol2 = None
    invert2 = False
    if direct in available_names:
        conv_symbol = direct
        invert = False
    elif indirect in available_names:
        conv_symbol = indirect
        invert = True
    else:
        # Try cross via USD (e.g. GBPAUD -> GBPUSD * USDEUR)
        leg1_sym = f"{quote_currency}USD" if f"{quote_currency}USD" in available_names else (f"USD{quote_currency}" if f"USD{quote_currency}" in available_names else None)
        leg2_sym = f"USD{acc_currency}" if f"USD{acc_currency}" in available_names else (f"{acc_currency}USD" if f"{acc_currency}USD" in available_names else None)
        if leg1_sym and leg2_sym:
            conv_symbol  = leg1_sym
            invert       = leg1_sym.startswith("USD")
            conv_symbol2 = leg2_sym
            invert2      = leg2_sym.startswith(acc_currency)
            two_leg      = True
        else:
            raise ValueError(f"Conversion failed for {symbol}: no path {direct}/{indirect} or via USD")

    # Fetch price with retry for subscription warm-up
    price_data = {}
    for attempt in range(15):
        price_res   = requests.post(f"{BRIDGE_BASE_URL}/prices/current", json={"symbols": [conv_symbol]}, headers=HEADERS)
        if not price_res.text.strip(): raise ValueError(f"Empty response from /prices/current for {conv_symbol}")
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

    # If single-leg price unavailable (e.g. EURAUD warming up), fall through to two-leg USD cross
    if avg_price == 0 and not two_leg:
        print(f"⚠️ No price for {conv_symbol} — falling back to USD cross-rate")
        leg1_sym = f"{quote_currency}USD" if f"{quote_currency}USD" in available_names else (f"USD{quote_currency}" if f"USD{quote_currency}" in available_names else None)
        leg2_sym = f"USD{acc_currency}" if f"USD{acc_currency}" in available_names else (f"{acc_currency}USD" if f"{acc_currency}USD" in available_names else None)
        if leg1_sym and leg2_sym:
            conv_symbol  = leg1_sym
            invert       = leg1_sym.startswith("USD")
            conv_symbol2 = leg2_sym
            invert2      = leg2_sym.startswith(acc_currency)
            two_leg      = True
            # Re-fetch leg1 price
            price_data = {}
            for attempt in range(5):
                pr = requests.post(f"{BRIDGE_BASE_URL}/prices/current", json={"symbols": [conv_symbol]}, headers=HEADERS)
                pl = pr.json().get("prices", [])
                if pl:
                    price_data = pl[0]
                    break
                time.sleep(2)
            avg_price = (price_data.get("bid_raw", 0) + price_data.get("ask_raw", 0)) / 2 / 1_000_000
            if avg_price == 0:
                raise ValueError(f"Conversion failed for {symbol}: no price for {conv_symbol} (USD fallback leg 1)")
        else:
            raise ValueError(f"Conversion failed for {symbol}: no price for {conv_symbol} and no USD cross available")

    if avg_price == 0:
        raise ValueError(f"Conversion failed for {symbol}: no price for {conv_symbol}")

    if not two_leg:
        conversion_rate = (1.0 / avg_price) if invert else avg_price
        return pip_size * conversion_rate

    # Two-leg: fetch second price leg
    price_data2 = {}
    for attempt in range(5):
        pr2 = requests.post(f"{BRIDGE_BASE_URL}/prices/current", json={"symbols": [conv_symbol2]}, headers=HEADERS)
        pj2 = pr2.json()
        pl2 = pj2.get("prices", [])
        if pl2:
            price_data2 = pl2[0]
            break
        if conv_symbol2 in ((pj2.get("missing_symbols") or []) + (pj2.get("warming_up_symbols") or [])):
            print(f"Waiting for price: {conv_symbol2} (attempt {attempt+1}/5)")
            time.sleep(2)
        else:
            break
    avg_price2 = (price_data2.get("bid_raw", 0) + price_data2.get("ask_raw", 0)) / 2 / 1_000_000
    if avg_price2 == 0:
        raise ValueError(f"Conversion failed for {symbol}: no price for {conv_symbol2} (leg 2)")
    rate1 = (1.0 / avg_price) if invert else avg_price
    rate2 = (1.0 / avg_price2) if invert2 else avg_price2
    return pip_size * rate1 * rate2

# ---------------------------------------------------------------------------
# LOT SIZE CALCULATION
# ---------------------------------------------------------------------------
def calculate_professional_lot_size(symbol, sl_pips):
    """
    Calculates volume in centilots based on live equity and risk %.

    cTrader volume units: raw units where 100000 = 1 standard lot.
    Formula: required_lots = risk_cash / (sl_pips * pip_value_per_lot)
             volume_units = risk_cash / (sl_pips * pip_value_per_unit)
    """
    settings         = fetch_settings()
    risk_pct         = settings.get("risk_pct", 0.01)

    acc_res          = requests.get(f"{BRIDGE_BASE_URL}/account/status", headers=HEADERS)
    if not acc_res.text.strip(): raise ValueError("Empty response from /account/status")
    acc_data         = acc_res.json()
    free_margin      = float(acc_data.get("free_margin", 0))
    acc_currency     = acc_data.get("currency", "EUR")

    total_risk_cash    = free_margin * risk_pct
    pip_value_per_unit = get_live_pip_value(symbol, acc_currency)

    required_lots   = total_risk_cash / (sl_pips * pip_value_per_unit)
    protocol_volume = int(required_lots)  # volume in cTrader units; pip_value_per_unit * units * sl_pips = risk_cash

    spec_res = requests.post(f"{BRIDGE_BASE_URL}/contract/specs", json={"symbol": symbol}, headers=HEADERS)
    if not spec_res.text.strip(): raise ValueError(f"Empty response from /contract/specs (lot calc)")
    spec     = spec_res.json().get("contract_specifications", {})
    step     = spec.get("stepVolume_centilots", 10_000_000)
    min_v    = spec.get("minVolume_centilots", 10_000_000)
    max_v    = spec.get("maxVolume_centilots", 10_000_000_000)

    final_vol = max((protocol_volume // step) * step, min_v)
    final_vol = min(final_vol, max_v)

    # Hard lot cap (max_lots from SQL settings, default 50)
    max_lots      = settings.get("max_lots", 50.0)
    max_vol_units = int(max_lots * 100_000)
    if final_vol > max_vol_units:
        print(f"WARNING: Vol capped: {final_vol/100_000:.2f} lots -> {max_lots:.0f} lots (max_lots cap)")
        final_vol = max_vol_units

    print(f"📊 Risk: {acc_currency} {total_risk_cash:,.2f} | PipVal/Unit: {pip_value_per_unit:.6f} | Lots: {final_vol/100_000:.4f} | Vol: {final_vol}")
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
    Returns true live session exposure as a percentage of account balance.
    Formula: sum(unrealizedNetPnL) / account_balance * 100
    Negative = drawdown. Gate fires when loss exceeds max_session_exposure_pct.
    Also returns open position count for logging.
    """
    try:
        # Fetch positions and account status in parallel
        pos_res = requests.get(f"{BRIDGE_BASE_URL}/positions/list", headers=HEADERS, timeout=10)
        acc_res = requests.get(f"{BRIDGE_BASE_URL}/account/status", headers=HEADERS, timeout=10)
        positions = pos_res.json().get("positions", [])
        account_balance = acc_res.json().get("equity", 0)
        if account_balance <= 0:
            print("⚠️ Could not fetch account balance for exposure calc — assuming 0%")
            return 0.0, len(positions)
        # Sum unrealised P&L across all open positions (bridge returns cents)
        total_unrealised_cents = sum(p.get("unrealizedNetPnL_cents", 0) for p in positions)
        total_unrealised_eur   = total_unrealised_cents / 100.0
        # Exposure as % of balance — negative means drawdown
        exposure_pct = (total_unrealised_eur / account_balance) * 100
        return exposure_pct, len(positions)
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

    except ValueError as e:
        if "Conversion failed" in str(e):
            print(f"⚠️ UNSUPPORTED symbol {symbol}: {e} — marking FAILED (will not retry)")
        else:
            print(f"❌ CRITICAL ERROR in execute_trade: {e}")
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
            # max_session_exposure_pct = max drawdown % allowed across all open positions
            # Gate fires when live unrealised loss exceeds the limit (e.g. -4.0%)
            max_exposure = settings.get("max_session_exposure_pct", 4.0)
            current_exposure, open_count = get_current_session_exposure_pct()
            if current_exposure <= -abs(max_exposure):
                print(f"🛑 Session exposure cap reached: {current_exposure:.2f}% live drawdown / -{max_exposure:.1f}% limit ({open_count} open positions). No new trades.")
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

                    result = execute_trade(s_uuid, sym, s_type, tf, float(sl_pips), float(tp_pips))
                    if result:
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
