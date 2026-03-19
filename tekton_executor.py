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
# IN-MEMORY CACHE  —  reduces cTrader API calls significantly
# ---------------------------------------------------------------------------
# contract specs never change mid-session → cached forever (cleared on restart)
# conversion prices change slowly         → 5-minute TTL
# account status (free margin, equity)    → 30-second TTL
_cache = {}

def _cache_get(key, ttl_seconds=None):
    """Return cached value if fresh, else None."""
    entry = _cache.get(key)
    if entry is None:
        return None
    if ttl_seconds is not None and (time.time() - entry["ts"]) > ttl_seconds:
        return None
    return entry["value"]

def _cache_set(key, value):
    """Store value with current timestamp."""
    _cache[key] = {"value": value, "ts": time.time()}

# ---------------------------------------------------------------------------
# SETTINGS  —  single source of truth: /data/system-settings
# ---------------------------------------------------------------------------
def fetch_settings():
    """
    Fetches live trading settings.
    Primary: bridge /data/system-settings (proxies SQL row id=1).
    Fallback: direct SQL if bridge unavailable.
    Never raises — always returns a safe dict.
    """
    try:
        response = requests.get(f"{BRIDGE_BASE_URL}/data/system-settings", headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()
        return {
            "auto_trade":               bool(data.get("auto_trade", False)),
            "friday_flush":             bool(data.get("friday_flush", False)),
            "risk_pct":                 float(data.get("risk_pct", 0.01)),
            "target_reward":            float(data.get("target_reward", 1.8)),
            "daily_drawdown_limit":     float(data.get("daily_drawdown_limit", 0.05)),
            "max_session_exposure_pct": float(data.get("max_session_exposure_pct", 4.0)),
            "max_lots":                 float(data.get("max_lots", 50.0)),
            "min_sl_pips":              float(data.get("min_sl_pips", 8.0)),
            "news_blackout_mins":        int(data.get("news_blackout_mins", 30))
        }
    except Exception as bridge_err:
        print(f"⚠️ Settings bridge unavailable: {bridge_err} — falling back to direct SQL")
        try:
            conn = psycopg2.connect(**DB_PARAMS)
            cur  = conn.cursor()
            cur.execute("SELECT auto_trade, friday_flush, risk_pct, target_reward, daily_drawdown_limit, max_session_exposure_pct, max_lots, news_blackout_mins FROM settings WHERE id=1")
            row = cur.fetchone()
            cur.close(); conn.close()
            if row:
                print("✅ Settings loaded from SQL directly")
                return {
                    "auto_trade":               bool(row[0]),
                    "friday_flush":             bool(row[1]),
                    "risk_pct":                 float(row[2]),
                    "target_reward":            float(row[3]),
                    "daily_drawdown_limit":     float(row[4]),
                    "max_session_exposure_pct": float(row[5]),
                    "max_lots":                 float(row[6]),
                    "min_sl_pips":              8.0,
                    "news_blackout_mins":        int(row[7]) if row[7] is not None else 30
                }
        except Exception as sql_err:
            print(f"⚠️ Settings SQL fallback failed: {sql_err} — using safe hardcoded defaults")
        print("⚠️ Using hardcoded safe defaults — auto_trade=False, max_lots=50")
        return {
            "auto_trade": False, "friday_flush": False,
            "risk_pct": 0.01, "target_reward": 1.8,
            "daily_drawdown_limit": 0.05, "max_session_exposure_pct": 4.0,
            "max_lots": 50.0, "min_sl_pips": 8.0, "news_blackout_mins": 30
        }

# ---------------------------------------------------------------------------
# PIP SIZE  —  always from bridge, never hardcoded
# ---------------------------------------------------------------------------
def get_contract_specs(symbol):
    """
    Returns full contract spec dict for symbol.
    Cached forever — specs never change mid-session.
    """
    cache_key = f"specs:{symbol}"
    cached = _cache_get(cache_key)  # no TTL = permanent until restart
    if cached is not None:
        return cached
    spec_res = requests.post(
        f"{BRIDGE_BASE_URL}/contract/specs",
        json={"symbol": symbol},
        headers=HEADERS,
        timeout=10
    )
    if not spec_res.text.strip(): raise ValueError(f"Empty response from /contract/specs for {symbol}")
    spec = spec_res.json().get("contract_specifications", {})
    _cache_set(cache_key, spec)
    print(f"📦 Cache MISS specs:{symbol} — fetched from bridge")
    return spec

def get_pip_size(symbol):
    """
    Returns pip size derived from live bridge pipPosition.
    Formula: pip_size = 10^-pipPosition
    e.g. pipPosition=4 → pip_size=0.0001 (standard forex)
         pipPosition=2 → pip_size=0.01   (JPY pairs, indices)
    """
    try:
        spec = get_contract_specs(symbol)
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

    # Fetch price with retry for subscription warm-up (5-min cache TTL)
    price_data = {}
    cache_key_price = f"price:{conv_symbol}"
    cached_price = _cache_get(cache_key_price, ttl_seconds=300)
    if cached_price is not None:
        price_data = cached_price
    else:
        for attempt in range(15):
            price_res   = requests.post(f"{BRIDGE_BASE_URL}/prices/current", json={"symbols": [conv_symbol]}, headers=HEADERS)
            if not price_res.text.strip(): raise ValueError(f"Empty response from /prices/current for {conv_symbol}")
            price_json  = price_res.json()
            prices_list = price_json.get("prices", [])
            if prices_list:
                price_data = prices_list[0]
                _cache_set(cache_key_price, price_data)
                print(f"📦 Cache MISS price:{conv_symbol} — fetched from bridge")
                break
            warming = (price_json.get("missing_symbols") or []) + (price_json.get("warming_up_symbols") or [])
            if conv_symbol in warming:
                print(f"⏳ Waiting for price subscription: {conv_symbol} (attempt {attempt+1}/5)")
                time.sleep(2)
            else:
                break

    avg_price = (price_data.get("bid_raw", 0) + price_data.get("ask_raw", 0)) / 2 / 100_000

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
            avg_price = (price_data.get("bid_raw", 0) + price_data.get("ask_raw", 0)) / 2 / 100_000
            if avg_price == 0:
                raise ValueError(f"Conversion failed for {symbol}: no price for {conv_symbol} (USD fallback leg 1)")
        else:
            raise ValueError(f"Conversion failed for {symbol}: no price for {conv_symbol} and no USD cross available")

    if avg_price == 0:
        raise ValueError(f"Conversion failed for {symbol}: no price for {conv_symbol}")

    if not two_leg:
        conversion_rate = (1.0 / avg_price) if invert else avg_price
        return pip_size * conversion_rate

    # Two-leg: fetch second price leg (5-min cache TTL)
    price_data2 = {}
    cache_key_price2 = f"price:{conv_symbol2}"
    cached_price2 = _cache_get(cache_key_price2, ttl_seconds=300)
    if cached_price2 is not None:
        price_data2 = cached_price2
    else:
        for attempt in range(5):
            pr2 = requests.post(f"{BRIDGE_BASE_URL}/prices/current", json={"symbols": [conv_symbol2]}, headers=HEADERS)
            pj2 = pr2.json()
            pl2 = pj2.get("prices", [])
            if pl2:
                price_data2 = pl2[0]
                _cache_set(cache_key_price2, price_data2)
                print(f"📦 Cache MISS price:{conv_symbol2} — fetched from bridge")
                break
            if conv_symbol2 in ((pj2.get("missing_symbols") or []) + (pj2.get("warming_up_symbols") or [])):
                print(f"Waiting for price: {conv_symbol2} (attempt {attempt+1}/5)")
                time.sleep(2)
            else:
                break
    avg_price2 = (price_data2.get("bid_raw", 0) + price_data2.get("ask_raw", 0)) / 2 / 100_000
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

    cached_acc = _cache_get("account_status", ttl_seconds=30)
    if cached_acc is not None:
        acc_data = cached_acc
    else:
        acc_res  = requests.get(f"{BRIDGE_BASE_URL}/account/status", headers=HEADERS)
        if not acc_res.text.strip(): raise ValueError("Empty response from /account/status")
        acc_data = acc_res.json()
        _cache_set("account_status", acc_data)
        print(f"📦 Cache MISS account_status — fetched from bridge")
    free_margin      = float(acc_data.get("free_margin", 0))
    acc_currency     = acc_data.get("currency", "EUR")

    total_risk_cash    = free_margin * risk_pct
    pip_value_per_unit = get_live_pip_value(symbol, acc_currency)

    # pip_value_per_unit = pip value for 1 raw unit in account currency
    # required_units = how many raw units to risk exactly risk_cash over sl_pips
    # 1 standard lot = 100,000 raw units
    # cTrader volume is in centilots where lotSize_centilots centilots = 1 lot
    required_units  = total_risk_cash / (sl_pips * pip_value_per_unit)

    spec          = get_contract_specs(symbol)   # cached — no extra API call
    lot_size_cl   = spec.get("lotSize_centilots", 10_000_000)   # centilots per 1 standard lot
    step          = spec.get("stepVolume_centilots", 100_000)
    min_v         = spec.get("minVolume_centilots", 100_000)
    max_v         = spec.get("maxVolume_centilots", 10_000_000_000)

    # Convert raw units → centilots  (100,000 raw units = 1 lot = lot_size_cl centilots)
    protocol_volume = int(required_units * lot_size_cl / 100_000)

    final_vol = max((protocol_volume // step) * step, min_v)
    final_vol = min(final_vol, max_v)

    # Hard lot cap (max_lots from SQL settings, default 50)
    max_lots      = settings.get("max_lots", 50.0)
    max_vol_cl    = int(max_lots * lot_size_cl)   # centilots equivalent of max_lots
    if final_vol > max_vol_cl:
        actual_lots = final_vol / lot_size_cl
        print(f"WARNING: Vol capped: {actual_lots:.2f} lots -> {max_lots:.0f} lots (max_lots cap)")
        final_vol = max_vol_cl

    actual_lots = final_vol / lot_size_cl
    print(f"📊 Risk: {acc_currency} {total_risk_cash:,.2f} | PipVal/Unit: {pip_value_per_unit:.8f} | Lots: {actual_lots:.4f} | Vol: {final_vol}")
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
    """
    Executes a trade via the bridge and returns (position_id, fill_price) on success.
    Returns None on failure or if symbol already open.

    FIX 1: return None (not True) when symbol already open — prevents boolean
            being written as position_id in signals table.
    FIX 2: validate position_id is numeric before accepting — guards against any
            future case where success=true but position_id is missing or malformed.
            Also unpacks and returns fill_price so caller can store avg_fill_price.
    """
    try:
        if is_symbol_already_open(symbol):
            print(f"🚫 {symbol} already open. Skipping.")
            return None  # FIX 1: was incorrectly returning True (boolean)

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
            pos_id     = result.get("position_id")
            fill_price = result.get("entry_price")  # FIX 2: bridge now returns scaled decimal

            # Validate pos_id is a real numeric position ID, not a boolean or junk value
            if not pos_id or not str(pos_id).strip().lstrip('-').isdigit():
                print(f"⚠️ Invalid position_id in bridge response: '{pos_id}' — marking FAILED")
                return None

            print(f"✅ Trade Executed: {symbol} ID: {pos_id} @ {fill_price}")
            return (str(pos_id), fill_price)  # FIX 2: return tuple (pos_id, fill_price)
        else:
            print(f"❌ Execution Failed: {result.get('error')}")
            return None

    except ValueError as e:
        if "Conversion failed" in str(e):
            print(f"⚠️ UNSUPPORTED symbol {symbol}: {e} — marking FAILED (will not retry)")
        else:
            print(f"❌ CRITICAL ERROR in execute_trade: {e}")
        return None
    except Exception as e:
        print(f"❌ CRITICAL ERROR in execute_trade: {e}")
        return None

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

            # --- ECONOMIC CALENDAR GATE ---
            # Block new executions within news_blackout_mins of any HIGH impact event
            blackout_mins = settings.get("news_blackout_mins", 30)
            try:
                cal_conn = psycopg2.connect(**DB_PARAMS)
                cal_cur  = cal_conn.cursor()
                cal_cur.execute("""
                    SELECT indicator_name, event_date, currency
                    FROM economic_events
                    WHERE impact_level = 'HIGH'
                    AND event_date BETWEEN NOW() - INTERVAL '%s minutes'
                                      AND NOW() + INTERVAL '%s minutes'
                    ORDER BY event_date ASC
                    LIMIT 1
                """, (blackout_mins, blackout_mins))
                news_event = cal_cur.fetchone()
                cal_cur.close()
                cal_conn.close()
                if news_event:
                    ev_name, ev_date, ev_ccy = news_event
                    print(f"📰 NEWS BLACKOUT: {ev_name} ({ev_ccy}) at {ev_date.strftime('%H:%M')} UTC — no new trades within {blackout_mins}min window.")
                    time.sleep(30)
                    continue
            except Exception as cal_err:
                print(f"⚠️ Calendar gate check failed: {cal_err} — proceeding without news filter.")

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

                min_sl = settings.get("min_sl_pips", 8.0)
                rr = float(tp_pips) / float(sl_pips) if float(sl_pips) > 0 else 0

                if sl_pips <= 0 or tp_pips <= 0:
                    print(f"⚠️ Invalid SL/TP for {sym}: sl={sl_pips} tp={tp_pips}. Marking FAILED.")
                    cur.execute("UPDATE signals SET status = 'FAILED' WHERE signal_uuid = %s", (str(s_uuid),))
                    conn.commit()
                elif float(sl_pips) < min_sl:
                    print(f"🚫 SL too tight for {sym}: {sl_pips}p < {min_sl}p minimum. Marking FAILED.")
                    cur.execute("UPDATE signals SET status = 'FAILED' WHERE signal_uuid = %s", (str(s_uuid),))
                    conn.commit()
                elif rr < 1.5:
                    print(f"🚫 RR too low for {sym}: {rr:.2f} < 1.5 minimum. Marking FAILED.")
                    cur.execute("UPDATE signals SET status = 'FAILED' WHERE signal_uuid = %s", (str(s_uuid),))
                    conn.commit()
                else:
                    cur.execute("UPDATE signals SET status = 'EXECUTING' WHERE signal_uuid = %s", (str(s_uuid),))
                    conn.commit()

                    result = execute_trade(s_uuid, sym, s_type, tf, float(sl_pips), float(tp_pips))
                    if result:
                        # FIX 2: unpack (pos_id, fill_price) tuple and store avg_fill_price
                        pos_id, fill_price = result
                        cur.execute(
                            "UPDATE signals SET status = 'COMPLETED', position_id = %s, avg_fill_price = %s WHERE signal_uuid = %s",
                            (pos_id, fill_price if fill_price else None, str(s_uuid))
                        )
                        print(f"✅ signals updated: pos_id={pos_id} fill={fill_price}")
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


