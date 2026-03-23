#  Tekton AI Trader Bridge v4.5
# Date: 2026-03-06
# MERGED: HOME + PROJECT with all fixes applied cleanly

import psycopg2
from twisted.internet import task
import os, traceback, time, uuid
import threading
import requests
import sys

sys.stdout = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stderr = sys.stdout

from datetime import datetime, timezone
from functools import wraps
from collections import deque
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from twisted.internet import reactor, threads, defer
from twisted.web.server import Site
from twisted.web.wsgi import WSGIResource
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages import OpenApiMessages_pb2 as openapi

try:
    from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoOAOrderType, ProtoOATradeSide
    ORDER_TYPE_MARKET, TRADE_SIDE_BUY, TRADE_SIDE_SELL = ProtoOAOrderType.MARKET, ProtoOATradeSide.BUY, ProtoOATradeSide.SELL
except ImportError:
    ORDER_TYPE_MARKET, TRADE_SIDE_BUY, TRADE_SIDE_SELL = 1, 1, 2

load_dotenv()

CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
ACCOUNT_ID = int(os.getenv("CTRADER_ACCOUNT_ID")) if os.getenv("CTRADER_ACCOUNT_ID") else None
ENV = (os.getenv("CT_ENV") or "demo").lower()
HOST = os.getenv("CTRADER_HOST") or (EndPoints.PROTOBUF_LIVE_HOST if ENV == "live" else EndPoints.PROTOBUF_DEMO_HOST)
PORT = int(os.getenv("CTRADER_PORT") or EndPoints.PROTOBUF_PORT)
BRIDGE_KEY = os.getenv("BRIDGE_KEY", "")
BRIDGE_HOST = os.getenv("BRIDGE_HOST", "0.0.0.0")
BRIDGE_PORT = int(os.getenv("BRIDGE_PORT", "8080"))

PERIOD_CODE = {"5min": 4, "15min": 7, "60min": 9, "4H": 10, "Daily": 12}

MASTER_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF", "EURCAD", "EURAUD", "EURNZD", "EURSGD",
    "GBPJPY", "GBPCHF", "GBPCAD", "GBPAUD", "GBPNZD", "GBPSGD",
    "CHFJPY", "CADJPY", "AUDJPY", "NZDJPY", "SGDJPY",
    "AUDCAD", "AUDCHF", "AUDNZD", "AUDSGD", "CADCHF", "NZDCAD", "NZDCHF", "CHFSGD", "USDSGD",
    "XAUUSD", "XAGUSD", "XTIUSD", "XBRUSD", "XNGUSD", "XPTUSD", "XPDUSD",
    "US30", "US500", "USTEC", "UK100", "DE40", "JP225", "STOXX50", "F40", "AUS200"
]

state = {
    "connected": False,
    "authenticated": False,
    "symbols_cache": {},
    "symbol_id_to_spec_map": {},
    "symbol_id_to_name_map": {},
    "asset_map": {},
    "account_type": "Unknown",
    "account_currency": "EUR",
    "deposit_asset_id": None,
    "last_spot_prices": {},
    "auto_trade_enabled": False,
    "friday_flush_enabled": False,
    "balance_cents": 0,
    "equity_cents": 0,
    "margin_used_cents": 0,
    "starting_equity_cents": 0,
    # ── v4.8 event-driven position state ──────────────────────────────────────
    "position_state": {},            # positionId(str) → normalised position dict
    "position_state_ready": False,   # True after startup ReconcileReq seed completes
    # ── v4.8 closed trades cache ─────────────────────────────────────────────
    # Populated once at startup + refreshed every 5 min in background.
    # /proxy/executions reads from here — zero on-demand DealListReq calls.
    "closed_trades_cache": [],
    "closed_trades_cache_ts": 0,
}

# Lock to prevent concurrent cache refreshes
_closed_cache_lock = threading.Lock()

# ===== API CALL TRACKING =====
api_call_log = deque(maxlen=100000)

def log_ctrader_call(endpoint, duration_ms, success=True):
    api_call_log.append({
        "timestamp": time.time(),
        "endpoint": endpoint,
        "duration_ms": duration_ms,
        "success": success
    })

def cleanup_old_calls():
    cutoff = time.time() - (24 * 60 * 60)
    while api_call_log and api_call_log[0]["timestamp"] < cutoff:
        api_call_log.popleft()

def get_calls_in_window(seconds):
    cutoff = time.time() - seconds
    return [call for call in api_call_log if call["timestamp"] >= cutoff]

def safe_hasfield(obj, field_name):
    return hasattr(obj, field_name) and getattr(obj, field_name) is not None

def safe_get_field(obj, field_name, default_value=0):
    if hasattr(obj, field_name):
        return getattr(obj, field_name)
    return default_value


# ═══════════════════════════════════════════════════════════════════════════════
# PRICE NORMALISATION HELPERS (v4.8)
# ═══════════════════════════════════════════════════════════════════════════════
# cTrader uses two distinct price formats — mixing them up causes silent bugs.
#
# RAW INTEGER format (divide by 10^digits to get decimal):
#   ProtoOADeal.executionPrice, ProtoOAPosition.stopLoss/takeProfit,
#   ProtoOATradeData.openPrice, market data candles
#
# DECIMAL DOUBLE format (use as-is — do NOT divide):
#   ProtoOAOrder.executionPrice
#   ProtoOAAmendPositionSLTPReq.stopLoss / .takeProfit  ← pass float directly
#   ProtoOANewOrderReq.relativeStopLoss / .relativeTakeProfit (points, not price)
#
# RULE: Always use these helpers. Never inline the conversion anywhere else.
# ═══════════════════════════════════════════════════════════════════════════════

def raw_to_decimal(raw_int, digits):
    """Convert a cTrader raw integer price to a human-readable decimal.
    Use for: ProtoOADeal.executionPrice, ProtoOAPosition.stopLoss/takeProfit,
             ProtoOATradeData.openPrice, market data candle prices.
    Returns None if raw_int is falsy or the result looks bogus (<0.0001).
    """
    if not raw_int:
        return None
    val = raw_int / (10 ** digits)
    return round(val, digits) if val >= 0.0001 else None


def decimal_to_raw(decimal_price, digits):
    """Convert a human-readable decimal price to a cTrader raw integer.
    Use when you need to store or compare against raw integer fields.
    Returns None if decimal_price is falsy.
    """
    if not decimal_price:
        return None
    return int(round(float(decimal_price) * (10 ** digits)))


def _position_to_dict(pos, spec, digits):
    """Normalise a ProtoOAPosition protobuf object into a clean Python dict.
    Single source of truth for position normalisation — all callers use this.
    entry_price comes from ProtoOATradeData.openPrice (raw int) — use raw_to_decimal.
    stop_loss / take_profit from position object are raw ints — use raw_to_decimal.
    Note: entry_price from ExecutionEvent's order field is a decimal double and
    will be patched onto position_state separately (see _handle_execution_event).
    """
    side_val = getattr(pos.tradeData, 'tradeSide', None)
    side = 'BUY' if side_val == TRADE_SIDE_BUY else 'SELL'

    return {
        'id':           str(pos.positionId),
        'symbol':       spec.get('symbolName', f'UNKNOWN_{pos.tradeData.symbolId}'),
        'symbol_id':    pos.tradeData.symbolId,
        'side':         side,
        'volume':       round(pos.tradeData.volume / 10_000_000, 4),
        'volume_raw':   pos.tradeData.volume,
        'entry_price':  raw_to_decimal(getattr(pos.tradeData, 'openPrice', None), digits),
        'stop_loss':    raw_to_decimal(getattr(pos, 'stopLoss', None), digits),
        'take_profit':  raw_to_decimal(getattr(pos, 'takeProfit', None), digits),
        'comment':      getattr(pos.tradeData, 'comment', None),   # contains signal_uuid
        'open_ts':      getattr(pos.tradeData, 'openTimestamp', None),
        'digits':       digits,
        'pnl':          None,   # populated later from PnL event or spot calc
        'status':       'open',
    }


def wait_for_deferred(d, timeout_seconds=30):
    gate = defer.Deferred()
    timeout_call = [None]

    def handle_result(res):
        if timeout_call[0] and timeout_call[0].active():
            timeout_call[0].cancel()
        if not gate.called:
            gate.callback(res)
        return res

    def handle_timeout():
        if not gate.called:
            gate.errback(defer.TimeoutError(f"Timeout after {timeout_seconds}s"))

    timeout_call[0] = reactor.callLater(timeout_seconds, handle_timeout)
    d.addBoth(handle_result)
    return gate

def send_subscription(client, msg):
    return lambda: client.send(msg)

# --- SQL HEARTBEAT FUNCTION ---
def sync_to_cloud_sql():
    if not state.get("authenticated"):
        return
    try:
        conn = psycopg2.connect(
            host=os.getenv("CLOUD_SQL_HOST"),
            database=os.getenv("CLOUD_SQL_DB_NAME", "tekton-trader"),
            user=os.getenv("CLOUD_SQL_DB_USER", "postgres"),
            password=os.getenv("CLOUD_SQL_DB_PASSWORD"),
            port=os.getenv("CLOUD_SQL_PORT", "5432"),
            sslmode='disable',
        )
        cur = conn.cursor()
        balance = state.get("balance_cents", 0) / 100
        equity = state.get("equity_cents", 0) / 100
        margin = state.get("margin_used_cents", 0) / 100
        cur.execute(
            "INSERT INTO account_metrics (balance, equity, margin_used, free_margin) VALUES (%s, %s, %s, %s)",
            (balance, equity, margin, (equity - margin))
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"✅ SQL Heartbeat Sent: €{balance}")
    except Exception as e:
        print(f"⚠️ SQL Sync Error: {e}")

# --- SQL System Settings ---
def get_db_conn():
    return psycopg2.connect(
        host=os.getenv("CLOUD_SQL_HOST"),
        database=os.getenv("CLOUD_SQL_DB_NAME", "tekton-trader"),
        user=os.getenv("CLOUD_SQL_DB_USER", "postgres"),
        password=os.getenv("CLOUD_SQL_DB_PASSWORD"),
        port=os.getenv("CLOUD_SQL_PORT", "5432"),
        sslmode='disable',
    )

# ===== FLASK APP =====
app = Flask(__name__)
CORS(app)

pending_requests = {}

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("X-Bridge-Key")
        if not BRIDGE_KEY or auth_header != BRIDGE_KEY:
            return jsonify({"success": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "success": True,
        "status": "healthy",
        "version": "4.8.0",
        "architecture": "PURE_PASS_THROUGH_FIXED_TRACKING",
        "authenticated": state["authenticated"],
        "symbols_loaded": len(state["symbols_cache"]),
        "ctrader_calls_tracked": len(api_call_log)
    })

@app.route("/stats/api-usage", methods=["GET"])
@require_auth
def get_api_usage_stats():
    try:
        cleanup_old_calls()
        now = time.time()
        calls_1min = get_calls_in_window(60)
        calls_5min = get_calls_in_window(300)
        calls_1hour = get_calls_in_window(3600)
        calls_24hour = list(api_call_log)

        minute_buckets = {}
        for call in calls_1hour:
            minute_key = int(call["timestamp"] // 60)
            minute_buckets[minute_key] = minute_buckets.get(minute_key, 0) + 1

        sorted_minutes = sorted(minute_buckets.items())[-60:]
        calls_per_minute_last_hour = [count for _, count in sorted_minutes]

        endpoint_stats = {}
        for call in calls_1hour:
            ep = call["endpoint"]
            if ep not in endpoint_stats:
                endpoint_stats[ep] = {"count_1hour": 0, "count_1min": 0, "durations": [], "failures": 0}
            endpoint_stats[ep]["count_1hour"] += 1
            endpoint_stats[ep]["durations"].append(call["duration_ms"])
            if not call["success"]:
                endpoint_stats[ep]["failures"] += 1

        for call in calls_1min:
            ep = call["endpoint"]
            if ep in endpoint_stats:
                endpoint_stats[ep]["count_1min"] += 1

        for ep, data in endpoint_stats.items():
            data["avg_duration_ms"] = int(sum(data["durations"]) / len(data["durations"])) if data["durations"] else 0
            del data["durations"]

        return jsonify({
            "success": True,
            "timestamp": now,
            "current_minute": len(calls_1min),
            "last_5_minutes": len(calls_5min),
            "last_hour": len(calls_1hour),
            "last_24_hours": len(calls_24hour),
            "calls_per_minute_last_hour": calls_per_minute_last_hour,
            "by_endpoint": endpoint_stats,
            "rate_limit_info": {
                "max_per_minute": 75,
                "current_usage_percent": int((len(calls_1min) / 75) * 100)
            }
        })
    except Exception as e:
        print(f"ERROR /stats/api-usage: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/positions/list", methods=["GET", "POST"])
@require_auth
def list_positions():
    # Phase 11c: Serve entirely from position_state{} — zero cTrader calls.
    # PnL is optionally fetched with a single GetPositionUnrealizedPnLReq.
    if not state["authenticated"]:
        return jsonify({"success": False, "error": "Not authenticated"}), 503
    try:
        ps_dict = state.get("position_state", {})

        # Optional: fetch live PnL (single call, fast)
        pnl_map = {}
        try:
            start_time = time.time()
            pnl_msg = openapi.ProtoOAGetPositionUnrealizedPnLReq()
            pnl_msg.ctidTraderAccountId = ACCOUNT_ID
            d_pnl, mid_pnl = defer.Deferred(), str(uuid.uuid4())
            pending_requests[mid_pnl] = d_pnl
            reactor.callFromThread(lambda: bridge.client.send(pnl_msg, clientMsgId=mid_pnl))
            pnl_result = threads.blockingCallFromThread(reactor, wait_for_deferred, d_pnl, 5)
            log_ctrader_call("/positions/list_pnl", int((time.time() - start_time) * 1000), True)
            if hasattr(pnl_result, "positionUnrealizedPnL"):
                for entry in pnl_result.positionUnrealizedPnL:
                    pnl_map[str(entry.positionId)] = {
                        "grossPnL_cents": safe_get_field(entry, "grossUnrealizedPnL", 0),
                        "netPnL_cents":   safe_get_field(entry, "netUnrealizedPnL", 0),
                    }
        except Exception as pnl_err:
            print(f"⚠️  PnL fetch failed — returning positions without PnL: {pnl_err}")

        positions = []
        for pos_id, ps in ps_dict.items():
            pnl_data = pnl_map.get(pos_id, {"grossPnL_cents": 0, "netPnL_cents": 0})
            positions.append({
                "positionId":            pos_id,
                "symbol":                ps.get("symbol", "UNKNOWN"),
                "tradeSide":             ps.get("side", "BUY"),
                "unrealizedNetPnL_cents": pnl_data["netPnL_cents"],
                "marginUsed_cents":      ps.get("margin_used_cents", 0),
                "volume":                ps.get("volume_raw", 0),
                "entryPrice":            ps.get("entry_price"),
                "stopLoss":              ps.get("stop_loss"),
                "takeProfit":            ps.get("take_profit"),
                "comment":               ps.get("comment"),
                "openTimestamp":         ps.get("open_ts"),
                "digits":                ps.get("digits", 5),
            })

        return jsonify({"success": True, "positions": positions, "count": len(positions)})

    except Exception as e:
        print(f"❌ ERROR /positions/list: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

def internal_sync_account():
    if not state.get("authenticated"):
        reactor.callLater(5, internal_sync_account)
        return

    def run_sync():
        try:
            trader_msg = openapi.ProtoOATraderReq()
            trader_msg.ctidTraderAccountId = ACCOUNT_ID
            d, client_msg_id = defer.Deferred(), str(uuid.uuid4())
            pending_requests[client_msg_id] = d

            reactor.callFromThread(lambda: bridge.client.send(trader_msg, clientMsgId=client_msg_id))
            trader_result = threads.blockingCallFromThread(reactor, wait_for_deferred, d, 10)
            trader = trader_result.trader

            balance = getattr(trader, 'balance', 0)
            equity = getattr(trader, 'moneyBalance', balance)
            margin_used = getattr(trader, 'usedMargin', 0)

            state["balance_cents"] = balance
            state["equity_cents"] = equity
            state["margin_used_cents"] = margin_used

            if state.get("starting_equity_cents", 0) == 0:
                state["starting_equity_cents"] = equity
                print(f"📈 Baseline Equity Set: €{equity/100}")

        except Exception as e:
            print(f"❌ Internal Sync Error: {e}")

        reactor.callLater(30, internal_sync_account)

    reactor.callInThread(run_sync)

@app.route("/account/info", methods=["GET"])
@require_auth
def get_account_info():
    # Phase 11c: Serve from state{} — kept live by TraderUpdatedEvent pushes.
    # Pass ?refresh=true to force a live TraderReq (e.g. after a deposit).
    if not state["authenticated"]:
        return jsonify({"success": False, "error": "Not authenticated"}), 503
    try:
        force_refresh = request.args.get("refresh", "false").lower() == "true"

        if force_refresh:
            start_time = time.time()
            trader_msg = openapi.ProtoOATraderReq()
            trader_msg.ctidTraderAccountId = ACCOUNT_ID
            d, mid = defer.Deferred(), str(uuid.uuid4())
            pending_requests[mid] = d
            reactor.callFromThread(lambda: bridge.client.send(trader_msg, clientMsgId=mid))
            trader_result = threads.blockingCallFromThread(reactor, wait_for_deferred, d, 15)
            log_ctrader_call("/account/info", int((time.time() - start_time) * 1000), True)
            trader = trader_result.trader
            state["balance_cents"]      = getattr(trader, 'balance', state["balance_cents"])
            state["equity_cents"]       = getattr(trader, 'moneyBalance', state["equity_cents"])
            state["margin_used_cents"]  = getattr(trader, 'usedMargin', state["margin_used_cents"])

        balance_cents     = state.get("balance_cents", 0)
        equity_cents      = state.get("equity_cents", balance_cents)
        margin_used_cents = state.get("margin_used_cents", 0)
        free_margin_cents = max(0, equity_cents - margin_used_cents)

        deposit_asset_id = state.get("deposit_asset_id")
        currency = "EUR"
        if deposit_asset_id and deposit_asset_id in state.get("asset_map", {}):
            currency = state["asset_map"].get(deposit_asset_id, "EUR")

        return jsonify({
            "success": True,
            "account_info": {
                "accountId":        ACCOUNT_ID,
                "balance_cents":    balance_cents,
                "equity_cents":     equity_cents,
                "usedMargin_cents": margin_used_cents,
                "freeMargin_cents": free_margin_cents,
                "currency":         currency,
                "accountType":      "live" if state.get("is_live") else "demo",
            }
        })
    except Exception as e:
        print(f"❌ ERROR /account/info: {str(e)}")
        log_ctrader_call("/account/info", 0, False)
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/contract/specs", methods=["POST"])
@require_auth
def get_contract_specs():
    if not state["authenticated"]:
        return jsonify({"success": False, "error": "Not authenticated"}), 503
    try:
        data = request.get_json()
        symbol = data.get("symbol")
        if not symbol:
            return jsonify({"success": False, "error": "symbol required"}), 400

        spec = state["symbols_cache"].get(symbol, {})
        if not spec:
            return jsonify({"success": False, "error": f"Symbol {symbol} not found"}), 404

        return jsonify({
            "success": True,
            "contract_specifications": {
                "symbol": symbol,
                "symbolId": spec["symbolId"],
                "pipPosition": spec.get("pipPosition", None),
                "digits": spec.get("digits", 5),
                "lotSize_centilots": spec.get("lotSize", 100000),
                "minVolume_centilots": spec.get("minVolume", 1),
                "maxVolume_centilots": spec.get("maxVolume", 10000000),
                "stepVolume_centilots": spec.get("stepVolume", 1),
                "quoteAssetId": spec.get("quoteAssetId", None),
                "baseAssetId": spec.get("baseAssetId", None),
            }
        })
    except Exception as e:
        print(f"ERROR /contract/specs: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/symbols/list", methods=["GET"])
@require_auth
def list_symbols():
    symbols = []
    for name, spec in state["symbols_cache"].items():
        symbols.append({
            "name": name,
            "symbolId": spec["symbolId"],
            "baseAssetId": spec.get("baseAssetId"),
            "quoteAssetId": spec.get("quoteAssetId"),
            "digits": spec.get("digits", 5),
            "pipPosition": spec.get("pipPosition"),
        })
    return jsonify({"success": True, "symbols": symbols, "count": len(symbols)})

@app.route("/account/status", methods=["GET"])
@require_auth
def get_account_status():
    """Endpoint for Executor and Monitor to check account health."""
    equity = state.get("equity_cents", 0) / 100
    margin_used = state.get("margin_used_cents", 0) / 100
    free_margin = equity - margin_used

    start_equity = state.get("starting_equity_cents", 0) / 100
    drawdown_pct = 0.0
    if start_equity > 0:
        drawdown_pct = ((start_equity - equity) / start_equity) * 100

    return jsonify({
        "success": True,
        "equity": round(equity, 2),
        "free_margin": round(free_margin, 2),
        "drawdown_pct": round(max(drawdown_pct, 0.0), 2),
        "currency": state.get("account_currency", "EUR"),
        "depositAssetId": state.get("deposit_asset_id"),
    })

@app.route("/proxy/account-summary", methods=["GET"])
@require_auth
def get_account_summary():
    try:
        conn = psycopg2.connect(
            host=os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
            database=os.getenv("CLOUD_SQL_DB_NAME", "tekton-trader"),
            user=os.getenv("CLOUD_SQL_DB_USER"),
            password=os.getenv("CLOUD_SQL_DB_PASSWORD")
        )
        cur = conn.cursor()
        cur.execute("SELECT balance, equity, margin_used, free_margin FROM account_metrics ORDER BY timestamp DESC LIMIT 1;")
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            return jsonify({
                "success": True,
                "balance": float(row[0]),
                "equity": float(row[1]),
                "margin_used": float(row[2]),
                "free_margin": float(row[3])
            })
        else:
            return jsonify({"success": False, "error": "No data found"}), 404

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/data/settings", methods=["GET", "POST"])
@app.route("/data/system-settings", methods=["GET", "POST"])  # legacy alias
@require_auth
def system_settings():
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        if request.method == "POST":
            data = request.get_json()

            # Read-modify-write: fetch current DB values first so a partial POST
            # cannot silently overwrite fields with hardcoded defaults.
            cur.execute("SELECT auto_trade, friday_flush, risk_pct, target_reward, daily_drawdown_limit, max_session_exposure_pct, max_lots, min_sl_pips, news_blackout_mins FROM settings WHERE id=1")
            existing = cur.fetchone()
            if existing:
                ex_auto_trade, ex_friday_flush, ex_risk_pct, ex_target_reward, ex_dd_limit, ex_exposure_pct, ex_max_lots, ex_min_sl, ex_blackout = existing
            else:
                ex_auto_trade, ex_friday_flush, ex_risk_pct, ex_target_reward, ex_dd_limit, ex_exposure_pct, ex_max_lots, ex_min_sl, ex_blackout = False, False, 0.01, 1.8, 0.05, 4.0, 50.0, 8.0, 30

            auto_trade             = data.get("auto_trade",               data.get("autoTrade",    ex_auto_trade))
            friday_flush           = data.get("friday_flush",             data.get("fridayFlush",  ex_friday_flush))
            risk_pct               = data.get("risk_pct",                 ex_risk_pct)
            target_reward          = data.get("target_reward",            ex_target_reward)
            daily_drawdown_limit   = data.get("daily_drawdown_limit",     ex_dd_limit)
            max_session_exposure_pct = data.get("max_session_exposure_pct", ex_exposure_pct)
            max_lots               = data.get("max_lots",                 ex_max_lots)
            min_sl_pips            = data.get("min_sl_pips",              ex_min_sl)
            news_blackout_mins     = data.get("news_blackout_mins",       ex_blackout)

            cur.execute("""
                INSERT INTO settings (id, auto_trade, friday_flush, risk_pct, target_reward,
                                      daily_drawdown_limit, max_session_exposure_pct, max_lots, min_sl_pips, news_blackout_mins)
                VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    auto_trade               = EXCLUDED.auto_trade,
                    friday_flush             = EXCLUDED.friday_flush,
                    risk_pct                 = EXCLUDED.risk_pct,
                    target_reward            = EXCLUDED.target_reward,
                    daily_drawdown_limit     = EXCLUDED.daily_drawdown_limit,
                    max_session_exposure_pct = EXCLUDED.max_session_exposure_pct,
                    max_lots                 = EXCLUDED.max_lots,
                    min_sl_pips              = EXCLUDED.min_sl_pips,
                    news_blackout_mins       = EXCLUDED.news_blackout_mins
            """, (auto_trade, friday_flush, risk_pct, target_reward,
                    daily_drawdown_limit, max_session_exposure_pct, max_lots, min_sl_pips, news_blackout_mins))
            conn.commit()
        else:
            cur.execute("""
                SELECT auto_trade, friday_flush, risk_pct, target_reward,
                       daily_drawdown_limit, max_session_exposure_pct, max_lots, min_sl_pips, news_blackout_mins
                FROM settings WHERE id = 1
            """)
            row = cur.fetchone()
            if row:
                return jsonify({
                    "success": True,
                    "auto_trade":               row[0],
                    "friday_flush":             row[1],
                    "risk_pct":                 float(row[2]),
                    "target_reward":            float(row[3]),
                    "daily_drawdown_limit":     float(row[4]),
                    "max_session_exposure_pct": float(row[5]),
                    "max_lots":                 float(row[6]),
                    "min_sl_pips":              float(row[7]) if row[7] is not None else 8.0,
                    "news_blackout_mins":        int(row[8]) if row[8] is not None else 30
                })
        cur.close()
        conn.close()
        return jsonify({
            "success": True,
            "auto_trade":               auto_trade,
            "friday_flush":             friday_flush,
            "risk_pct":                 float(risk_pct),
            "target_reward":            float(target_reward),
            "daily_drawdown_limit":     float(daily_drawdown_limit),
            "max_session_exposure_pct": float(max_session_exposure_pct),
            "max_lots":                 float(max_lots),
            "min_sl_pips":              float(min_sl_pips),
            "news_blackout_mins":        int(news_blackout_mins)
        })
    except Exception as e:
        print(f"⚠️ system_settings error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/calendar/events", methods=["GET"])
@require_auth
def get_calendar_events():
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, event_date, currency, indicator_name, impact_level, source
            FROM economic_events
            WHERE event_date BETWEEN NOW() - INTERVAL '1 hour' AND NOW() + INTERVAL '7 days'
            ORDER BY event_date ASC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        events = []
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        for row in rows:
            event_dt = row[1]
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=datetime.timezone.utc)
            minutes_until = int((event_dt - now).total_seconds() / 60)
            events.append({
                "id":             row[0],
                "event_date":     event_dt.isoformat(),
                "currency":       row[2],
                "indicator_name": row[3],
                "impact_level":   row[4],
                "source":         row[5],
                "minutes_until":  minutes_until,
            })
        return jsonify({"success": True, "events": events, "count": len(events)})
    except Exception as e:
        print(f"⚠️ get_calendar_events error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

        
@app.route("/proxy/executions", methods=["GET"])
@require_auth
def get_executions():
    """Serve open + closed trade data entirely from in-memory caches.
    Zero on-demand cTrader API calls — position_state{} for open positions,
    closed_trades_cache for closed positions (refreshed every 5 min).
    """
    try:
        # ── 1. Open trades from position_state{} ─────────────────────────────
        open_trades = []
        for pos_id, ps in state.get("position_state", {}).items():
            open_ts = ps.get("open_ts")
            open_trades.append({
                "id":          pos_id,
                "signal_uuid": ps.get("comment"),
                "symbol":      ps.get("symbol", "UNKNOWN"),
                "side":        ps.get("side", "BUY"),
                "volume":      ps.get("volume", 0),
                "entry_price": ps.get("entry_price"),
                "stop_loss":   ps.get("stop_loss"),
                "take_profit": ps.get("take_profit"),
                "close_price": None,
                "pnl":         None,
                "status":      "open",
                "created_at":  datetime.fromtimestamp(open_ts / 1000).isoformat() if open_ts else None,
                "closed_at":   None,
                "digits":      ps.get("digits", 5),
                "strategy":    None,
                "sl_pips":     None,
                "tp_pips":     None,
            })

        # ── 2. Closed trades from cache (deduplicated against open positions) ─
        open_pos_ids  = {t["id"] for t in open_trades}
        closed_trades = [t for t in state.get("closed_trades_cache", [])
                         if t.get("id") not in open_pos_ids]

        # ── 3. Enrich open trades with signal data from DB ───────────────────
        if open_trades:
            try:
                signal_uuids = [t["signal_uuid"] for t in open_trades if t["signal_uuid"]]
                if signal_uuids:
                    conn = get_db_conn()
                    cur  = conn.cursor()
                    placeholders = ",".join(["%s"] * len(signal_uuids))
                    cur.execute(f"""
                        SELECT signal_uuid, strategy, sl_pips, tp_pips
                        FROM signals WHERE signal_uuid IN ({placeholders})
                    """, signal_uuids)
                    sig_map = {r[0]: r for r in cur.fetchall()}
                    cur.close(); conn.close()
                    for t in open_trades:
                        row = sig_map.get(t["signal_uuid"])
                        if row:
                            t["strategy"] = row[1]
                            t["sl_pips"]  = float(row[2]) if row[2] else None
                            t["tp_pips"]  = float(row[3]) if row[3] else None
            except Exception as enrich_err:
                print(f"⚠️  Signal enrich error (non-fatal): {enrich_err}")

        combined = open_trades + closed_trades
        return jsonify({"open_trades": open_trades, "closed_trades": closed_trades, "combined": combined})

    except Exception as e:
        print(f"❌ Executions Proxy Error: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


def _refresh_closed_trades_cache():
    """Fetch last 30 days of closed positions via DealListReq and update the cache.
    Also backfills entry_price into position_state{} for pre-bridge positions.
    Runs once at startup (via _schedule_cache_refresh) and every 5 minutes after.
    Thread-safe via _closed_cache_lock. No-op if bridge not yet authenticated.
    """
    if not state.get("authenticated"):
        return
    if not _closed_cache_lock.acquire(blocking=False):
        return  # another refresh already running

    try:
        to_ts   = int(time.time() * 1000)
        from_ts = to_ts - (30 * 24 * 60 * 60 * 1000)

        # ── Paginated DealListReq ─────────────────────────────────────────────
        position_deals = {}
        current_to     = to_ts
        pages          = 0
        while True:
            deal_req = openapi.ProtoOADealListReq()
            deal_req.ctidTraderAccountId = ACCOUNT_ID
            deal_req.fromTimestamp = from_ts
            deal_req.toTimestamp   = current_to
            deal_req.maxRows       = 500

            d_deal, cid = defer.Deferred(), str(uuid.uuid4())
            pending_requests[cid] = d_deal
            reactor.callFromThread(lambda r=deal_req, c=cid: bridge.client.send(r, clientMsgId=c))
            result = threads.blockingCallFromThread(reactor, wait_for_deferred, d_deal, 30)
            pages += 1

            for deal in result.deal:
                pid = str(deal.positionId)
                if pid not in position_deals:
                    position_deals[pid] = []
                position_deals[pid].append(deal)

            if not getattr(result, "hasMore", False) or not result.deal:
                break
            current_to = min(d.executionTimestamp for d in result.deal) - 1
            if pages >= 10:
                print("⚠️  DealListReq cache refresh: safety cap (10 pages / ~5000 deals)")
                break

        if pages > 1:
            print(f"📄 DealListReq cache: {pages} pages, {sum(len(v) for v in position_deals.values())} deals")

        # ── Backfill entry_price into position_state{} ───────────────────────
        patched = 0
        for pid, ps in list(state.get("position_state", {}).items()):
            if ps.get("entry_price") is None and pid in position_deals:
                deals_sorted = sorted(position_deals[pid], key=lambda d: d.executionTimestamp)
                opening_deal = deals_sorted[0]
                spec   = state["symbol_id_to_spec_map"].get(opening_deal.symbolId, {})
                digits = spec.get("digits", 5)
                # ProtoOADeal.executionPrice is a decimal double (e.g. 1.08432)
                # NOT a raw integer — use directly, do not pass through raw_to_decimal.
                raw    = getattr(opening_deal, "executionPrice", 0)
                if raw and float(raw) > 0:
                    ps["entry_price"] = round(float(raw), digits)
                    patched += 1
        if patched:
            print(f"✅ position_state backfill: {patched} entry prices patched")

        # ── Build closed_trades_cache ─────────────────────────────────────────
        open_pos_ids = set(state.get("position_state", {}).keys())
        closed = []
        for pid, deals in position_deals.items():
            if pid in open_pos_ids:
                continue  # still open — exclude

            closing_deal = next((d for d in deals if hasattr(d, "closePositionDetail")), None)
            if not closing_deal:
                continue

            deals_sorted = sorted(deals, key=lambda d: d.executionTimestamp)
            opening_deal = deals_sorted[0]
            spec         = state["symbol_id_to_spec_map"].get(closing_deal.symbolId, {})
            symbol_name  = spec.get("symbolName", f"UNKNOWN_{closing_deal.symbolId}")
            digits       = spec.get("digits", 5)

            gross_pnl = commission = swap = 0
            for deal in deals:
                if hasattr(deal, "closePositionDetail"):
                    cpd         = deal.closePositionDetail
                    gross_pnl  += getattr(cpd, "grossProfit", 0)
                    swap       += getattr(cpd, "swap", 0)
                    commission += getattr(cpd, "closedCommission", 0) + getattr(cpd, "commission", 0)
                else:
                    swap       += getattr(deal, "swap", 0)
                    commission += getattr(deal, "commission", 0)

            net_pnl_cents = gross_pnl - abs(commission) + swap

            # Entry price: opening deal executionPrice (decimal double, direct use)
            entry_exec  = getattr(opening_deal, "executionPrice", None)
            entry_price = round(float(entry_exec), digits) if entry_exec and float(entry_exec) > 0 else None

            # Close price: prefer closePositionDetail raw int → scale; fallback executionPrice
            cpd_close = getattr(closing_deal, "closePositionDetail", None)
            close_raw = None
            if cpd_close:
                close_raw = getattr(cpd_close, "closePrice", None) or getattr(cpd_close, "price", None)
            close_exec = getattr(closing_deal, "executionPrice", None)
            if close_raw and float(close_raw) > 0:
                close_price = round(float(close_raw) / (10 ** digits), digits)
            elif close_exec and float(close_exec) > 0:
                close_price = round(float(close_exec), digits)
            else:
                close_price = None

            filled_vol = getattr(closing_deal, "filledVolume", 0)
            open_ts    = getattr(opening_deal, "executionTimestamp", None)
            close_ts   = getattr(closing_deal, "executionTimestamp", None)

            closed.append({
                "id":          pid,
                "signal_uuid": getattr(opening_deal, "comment", None),
                "symbol":      symbol_name,
                "side":        "BUY" if getattr(closing_deal, "tradeSide", 2) == TRADE_SIDE_BUY else "SELL",
                "volume":      round(filled_vol / 10_000_000, 4) if filled_vol else 0,
                "entry_price": entry_price,
                "stop_loss":   None,
                "take_profit": None,
                "close_price": close_price,
                "pnl":         round(net_pnl_cents / 100, 2),
                "status":      "closed",
                "created_at":  datetime.fromtimestamp(open_ts / 1000).isoformat() if open_ts else None,
                "closed_at":   datetime.fromtimestamp(close_ts / 1000).isoformat() if close_ts else None,
                "digits":      digits,
                "strategy":    None,
                "sl_pips":     None,
                "tp_pips":     None,
            })

        closed.sort(key=lambda x: x.get("closed_at") or "", reverse=True)
        state["closed_trades_cache"]    = closed
        state["closed_trades_cache_ts"] = time.time()
        print(f"✅ closed_trades_cache refreshed: {len(closed)} closed positions")

    except Exception as e:
        print(f"⚠️  _refresh_closed_trades_cache error: {e}")
        traceback.print_exc()
    finally:
        _closed_cache_lock.release()


def _schedule_cache_refresh():
    """Kick off a background cache refresh, then reschedule every 5 minutes."""
    threading.Thread(target=_refresh_closed_trades_cache, daemon=True).start()
    reactor.callLater(300, _schedule_cache_refresh)


def sync_latest_candles():
    """
    Background thread: runs every 5 minutes, fetches the 3 most recent candles
    per symbol per timeframe and upserts into market_data.
    Replaces the external tekton_backfill.py cron for ongoing updates.
    Staggered 0.5s between calls to avoid API rate spikes.
    """
    SYNC_INTERVAL_SEC = 300          # run every 5 minutes
    TIMEFRAMES        = ["5min", "15min", "60min", "4H", "Daily"]
    CANDLES_PER_SYNC  = 3            # only fetch last 3 candles per symbol/tf
    CALL_DELAY_SEC    = 0.5          # pause between each API call

    def _get_db():
        return psycopg2.connect(
            host=os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
            database=os.getenv("CLOUD_SQL_DB_NAME", "tekton-trader"),
            user=os.getenv("CLOUD_SQL_DB_USER", "postgres"),
            password=os.getenv("CLOUD_SQL_DB_PASSWORD"),
            port=int(os.getenv("CLOUD_SQL_PORT", 5432))
        )

    def _fetch_and_upsert(symbol, tf, conn, cur):
        """Fetch last CANDLES_PER_SYNC candles for symbol/tf and upsert to DB."""
        try:
            spec = state["symbols_cache"].get(symbol)
            if not spec:
                return 0
            symbol_id = spec["symbolId"]
            digits    = spec["digits"]
            ct_tf     = PERIOD_CODE.get(tf)
            if not ct_tf:
                return 0

            to_ts   = int(time.time() * 1000)
            from_ts = to_ts - (CANDLES_PER_SYNC * _tf_minutes(tf) * 60 * 1000 * 2)

            req = openapi.ProtoOAGetTrendbarsReq()
            req.ctidTraderAccountId = ACCOUNT_ID
            req.symbolId            = symbol_id
            req.period              = ct_tf
            req.fromTimestamp       = from_ts
            req.toTimestamp         = to_ts
            req.count               = CANDLES_PER_SYNC

            d, msg_id = defer.Deferred(), str(uuid.uuid4())
            pending_requests[msg_id] = d
            reactor.callFromThread(lambda: bridge.client.send(req, clientMsgId=msg_id))
            result = threads.blockingCallFromThread(reactor, wait_for_deferred, d, 15)

            log_ctrader_call("/prices/historical", 0, True)

            inserted = 0
            for tb in result.trendbar:
                ts       = tb.utcTimestampInMinutes * 60 * 1000
                low_raw  = tb.low if hasattr(tb, "low") else 0
                open_raw = low_raw + (tb.deltaOpen  if hasattr(tb, "deltaOpen")  else 0)
                high_raw = low_raw + (tb.deltaHigh  if hasattr(tb, "deltaHigh")  else 0)
                close_raw= low_raw + (tb.deltaClose if hasattr(tb, "deltaClose") else 0)
                vol      = tb.volume if hasattr(tb, "volume") else 0
                dt       = datetime.fromtimestamp(ts / 1000.0)
                cur.execute("""
                    INSERT INTO market_data
                      (symbol, timeframe, timestamp, open, high, low, close, volume)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (symbol, timeframe, timestamp) DO UPDATE
                      SET open=EXCLUDED.open, high=EXCLUDED.high,
                          low=EXCLUDED.low,   close=EXCLUDED.close,
                          volume=EXCLUDED.volume;
                """, (symbol, tf, dt, open_raw, high_raw, low_raw, close_raw, vol))
                inserted += 1
            conn.commit()
            return inserted
        except Exception as e:
            try: conn.rollback()
            except: pass
            print(f"[sync_candles] ⚠️  {symbol} {tf}: {e}")
            return 0

    def _tf_minutes(tf):
        return {"5min": 5, "15min": 15, "60min": 60, "4H": 240, "Daily": 1440}.get(tf, 15)

    # ── main loop ──
    print(f"[sync_candles] 🕯️  Candle sync thread started — interval={SYNC_INTERVAL_SEC}s")
    while True:
        time.sleep(SYNC_INTERVAL_SEC)
        if not state.get("authenticated"):
            continue
        try:
            conn = _get_db()
            cur  = conn.cursor()
            cur.execute("SELECT DISTINCT symbol FROM market_data ORDER BY symbol;")
            symbols = [r[0] for r in cur.fetchall()]
            total = 0
            for sym in symbols:
                for tf in TIMEFRAMES:
                    n = _fetch_and_upsert(sym, tf, conn, cur)
                    total += n
                    time.sleep(CALL_DELAY_SEC)
            cur.close()
            conn.close()
            if total > 0:
                print(f"[sync_candles] ✅ Sync complete — {len(symbols)} symbols, {total} candles upserted")
        except Exception as e:
            print(f"[sync_candles] ❌ Sync error: {e}")

@app.route("/proxy/signals", methods=["GET"])
@require_auth
def get_signals():
    try:
        # Optional query params: status, symbol, limit (default 200), offset (default 0)
        status_filter     = request.args.get("status", None)
        symbol_filter     = request.args.get("symbol", None)
        broker_pos_filter = request.args.get("broker_position_id", None) or request.args.get("position_id", None)
        limit = int(request.args.get("limit", 200))
        offset = int(request.args.get("offset", 0))

        conn = get_db_conn()
        cur = conn.cursor()

        # Build dynamic WHERE clause
        conditions = []
        params = []
        if status_filter:
            conditions.append("status = %s")
            params.append(status_filter)
        if symbol_filter:
            conditions.append("symbol = %s")
            params.append(symbol_filter)
        if broker_pos_filter:
            conditions.append("position_id = %s")
            params.append(broker_pos_filter)

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params += [limit, offset]

        cur.execute(f"""
            SELECT signal_uuid, symbol, signal_type, timeframe, confidence_score, sl_pips, tp_pips, status, created_at, position_id, strategy, avg_fill_price
            FROM signals
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s;
        """, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        signals_list = []
        for row in rows:
            signals_list.append({
                "uuid":       row[0],
                "symbol":     row[1],
                "direction":  row[2],
                "timeframe":  row[3],
                "confidence": row[4],
                "sl_pips":    float(row[5]) if row[5] else None,
                "tp_pips":    float(row[6]) if row[6] else None,
                "status":     row[7],
                "created_at":  row[8].strftime("%Y-%m-%d %H:%M:%S") if row[8] else "N/A",
                "position_id": row[9],
                "strategy":    row[10],
            })

        print(f"📡 API HIT: Signals requested. status={status_filter} symbol={symbol_filter} limit={limit} offset={offset}. Found {len(signals_list)} rows.")
        return jsonify({"success": True, "signals": signals_list})

    except Exception as e:
        print(f"❌ Signals Proxy Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/proxy/signals/stats", methods=["GET"])
@require_auth
def get_signals_stats():
    try:
        conn = get_db_conn()
        cur = conn.cursor()

        # Count by status
        cur.execute("""
            SELECT status, COUNT(*) as cnt
            FROM signals
            GROUP BY status;
        """)
        rows = cur.fetchall()

        # Distinct symbols for filter dropdown
        cur.execute("SELECT DISTINCT symbol FROM signals ORDER BY symbol;")
        symbols = [r[0] for r in cur.fetchall()]

        cur.close()
        conn.close()

        counts = {"TOTAL": 0, "PENDING": 0, "EXECUTED": 0, "FAILED": 0, "EXPIRED": 0, "CANCELLED": 0}
        for row in rows:
            status, cnt = row[0], row[1]
            counts["TOTAL"] += cnt
            if status in counts:
                counts[status] = cnt

        print(f"📊 API HIT: Signal stats requested. Total={counts['TOTAL']}")
        return jsonify({"success": True, "counts": counts, "symbols": symbols})

    except Exception as e:
        print(f"❌ Signal Stats Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/trade/execute", methods=["POST"])
@require_auth
def execute_trade():
    if not state["authenticated"]:
        return jsonify({"success": False, "error": "Not authenticated"}), 503

    start_time = time.time()
    try:
        data = request.get_json()

        symbol  = data.get("symbol")
        side    = data.get("signal_type") or data.get("side")
        vol     = data.get("volume_centilots") or data.get("volume")
        comment = data.get("comment", "")

        spec = state["symbols_cache"].get(symbol, {})
        if not spec:
            return jsonify({"success": False, "error": f"Symbol {symbol} not found"}), 404

        symbol_id = spec.get("symbolId") or spec.get("symbol_id")

        req = openapi.ProtoOANewOrderReq()
        req.ctidTraderAccountId = ACCOUNT_ID
        req.symbolId = symbol_id
        req.orderType = ORDER_TYPE_MARKET
        req.tradeSide = TRADE_SIDE_BUY if side == "BUY" else TRADE_SIDE_SELL
        req.volume = vol
        if comment:
            req.comment = comment

        rel_sl = data.get("rel_sl")
        rel_tp = data.get("rel_tp")
        # relativeStopLoss/TP is a protobuf int32 field — must be an integer.
        # cTrader expects integer POINTS (1 pip = 10 points for 5-digit pairs).
        # Convert: points = round(pips * 10) → always an int.
        if rel_sl:
            req.relativeStopLoss = int(round(float(rel_sl) * 10))
        if rel_tp:
            req.relativeTakeProfit = int(round(float(rel_tp) * 10))

        d_exec, client_msg_id = defer.Deferred(), str(uuid.uuid4())
        pending_requests[client_msg_id] = d_exec

        reactor.callFromThread(lambda: bridge.client.send(req, clientMsgId=client_msg_id))
        result = threads.blockingCallFromThread(reactor, wait_for_deferred, d_exec, 30)
        log_ctrader_call("/trade/execute", int((time.time() - start_time) * 1000), True)

        if hasattr(result, 'errorCode') and result.errorCode:
            return jsonify({"success": False, "error": str(result.description)}), 400

        if not hasattr(result, 'order') or result.order is None:
            error_desc = getattr(result, 'description', 'Order not created by broker')
            print(f"❌ Broker Rejected Order: {error_desc}")
            return jsonify({"success": False, "error": error_desc}), 400

        pos_id        = result.position.positionId if hasattr(result, 'position') else 0
        # ProtoOAOrder.executionPrice is 0.0 for MARKET orders (filled async).
        # Use ProtoOAPosition.price instead — it is the decimal fill price set by the broker.
        entry_price   = None
        if hasattr(result, 'position') and result.position:
            raw_pos_price = getattr(result.position, 'price', None)
            if raw_pos_price and raw_pos_price > 0:
                digits = spec.get("digits", 5) if spec else 5
                entry_price = round(float(raw_pos_price), digits)
        digits = spec.get("digits", 5) if spec else 5

        print(f"✅ Executed {symbol}: pos_id={pos_id} raw={raw_pos_price} scaled={entry_price} digits={digits}")

        return jsonify({
            "success":     True,
            "position_id": pos_id,
            "entry_price": entry_price   # scaled decimal, ready to store in signals.avg_fill_price
        })

    except Exception as e:
        log_ctrader_call("/trade/execute", 0, False)
        print(f"❌ ERROR /trade/execute: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/trade/modify", methods=["POST"])
@require_auth
def modify_trade():
    if not state["authenticated"]:
        return jsonify({"success": False, "error": "Not authenticated"}), 503
    try:
        data = request.get_json()
        position_id = data.get("position_id")

        # Accepts sl_price/tp_price (absolute decimal) OR sl_pips/tp_pips (relative to entry).
        # Pips mode takes priority — bridge calculates absolute price from position entry + side.
        sl_price = data.get("sl_price") or data.get("stopLoss_raw")
        tp_price = data.get("tp_price") or data.get("takeProfit_raw")
        sl_pips  = data.get("sl_pips")
        tp_pips  = data.get("tp_pips")

        if not position_id:
            return jsonify({"success": False, "error": "position_id required"}), 400
        if sl_price is None and tp_price is None and sl_pips is None and tp_pips is None:
            return jsonify({"success": False, "error": "At least one of sl_price, tp_price, sl_pips, tp_pips required"}), 400

        # Phase 11c: look up position from position_state{} — no ReconcileReq needed
        ps = state.get("position_state", {}).get(str(position_id))
        if not ps:
            return jsonify({"success": False, "error": f"Position {position_id} not found in position_state — may already be closed"}), 404

        digits  = ps.get("digits", 5)
        pip_pos = ps.get("pip_position", digits - 1)
        pip_size = 10 ** -pip_pos

        # If pips provided, derive absolute price from cached entry
        if sl_pips is not None or tp_pips is not None:
            entry_price = ps.get("entry_price")
            if not entry_price:
                return jsonify({"success": False, "error": "Cannot resolve entry price from position_state — use sl_price/tp_price instead"}), 400
            is_buy = ps.get("side", "BUY") == "BUY"

            if sl_pips is not None:
                sl_price = entry_price - (float(sl_pips) * pip_size) if is_buy else entry_price + (float(sl_pips) * pip_size)
            if tp_pips is not None:
                tp_price = entry_price + (float(tp_pips) * pip_size) if is_buy else entry_price - (float(tp_pips) * pip_size)

        req = openapi.ProtoOAAmendPositionSLTPReq()
        req.ctidTraderAccountId = ACCOUNT_ID
        req.positionId = int(position_id)

        # ProtoOAAmendPositionSLTPReq expects DECIMAL DOUBLE — pass directly, no raw conversion
        if sl_price is not None:
            req.stopLoss = round(float(sl_price), digits)
        if tp_price is not None:
            req.takeProfit = round(float(tp_price), digits)

        print(f"🛠️ Modifying ID {position_id} | sl_pips={sl_pips} tp_pips={tp_pips} | Raw SL: {getattr(req, 'stopLoss', 'N/A')} | Raw TP: {getattr(req, 'takeProfit', 'N/A')}")

        d_mod, mid_mod = defer.Deferred(), str(uuid.uuid4())
        pending_requests[mid_mod] = d_mod
        reactor.callFromThread(lambda: bridge.client.send(req, clientMsgId=mid_mod))
        result = threads.blockingCallFromThread(reactor, wait_for_deferred, d_mod, 15)

        if hasattr(result, 'errorCode'):
            return jsonify({"success": False, "error": f"{result.errorCode}: {getattr(result, 'description', '')}"}), 400

        return jsonify({"success": True, "positionId": position_id, "message": "Protection attached"})

    except Exception as e:
        print(f"❌ ERROR /trade/modify: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/trade/close", methods=["POST"])
@require_auth
def close_trade():
    if not state["authenticated"]:
        return jsonify({"success": False, "error": "Not authenticated"}), 503
    try:
        data = request.get_json()
        position_id = data.get("position_id")
        volume_centilots = data.get("volume_centilots")

        if not position_id:
            return jsonify({"success": False, "error": "position_id required"}), 400

        if not volume_centilots:
            # Phase 11c: get volume from position_state{} — no ReconcileReq needed
            ps = state.get("position_state", {}).get(str(position_id))
            if not ps:
                return jsonify({"success": False, "error": f"Position {position_id} not found in position_state — may already be closed"}), 404
            volume_centilots = ps.get("volume_raw")
            if not volume_centilots:
                return jsonify({"success": False, "error": f"Position {position_id} has no volume in position_state"}), 400

        start_time = time.time()
        req = openapi.ProtoOAClosePositionReq()
        req.ctidTraderAccountId = ACCOUNT_ID
        req.positionId = int(position_id)
        req.volume = int(volume_centilots)

        d_close, client_msg_id_close = defer.Deferred(), str(uuid.uuid4())
        pending_requests[client_msg_id_close] = d_close

        reactor.callFromThread(lambda: bridge.client.send(req, clientMsgId=client_msg_id_close))
        result = threads.blockingCallFromThread(reactor, wait_for_deferred, d_close, 10)
        log_ctrader_call("/trade/close", int((time.time() - start_time) * 1000), True)

        if hasattr(result, 'errorCode') and result.errorCode:
            error_message = result.description if hasattr(result, 'description') else "Unknown error"
            return jsonify({"success": False, "error": error_message}), 500

        return jsonify({"success": True, "positionId": position_id})

    except Exception as e:
        log_ctrader_call("/trade/close", 0, False)
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/positions/history", methods=["POST"])
@require_auth
def get_positions_history():
    if not state["authenticated"]:
        return jsonify({"success": False, "error": "Not authenticated"}), 503
    try:
        data = request.get_json() or {}
        limit = data.get("limit", 100)
        to_timestamp = int(data.get("to_timestamp", time.time() * 1000))
        from_timestamp = int(data.get("from_timestamp", to_timestamp - (30 * 24 * 60 * 60 * 1000)))

        start_time = time.time()
        req = openapi.ProtoOADealListReq()
        req.ctidTraderAccountId = ACCOUNT_ID
        req.fromTimestamp = from_timestamp
        req.toTimestamp = to_timestamp
        req.maxRows = min(limit, 1000)

        d, client_msg_id = defer.Deferred(), str(uuid.uuid4())
        pending_requests[client_msg_id] = d

        reactor.callFromThread(lambda: bridge.client.send(req, clientMsgId=client_msg_id))
        result = threads.blockingCallFromThread(reactor, wait_for_deferred, d, 30)
        log_ctrader_call("/deals/closed", int((time.time() - start_time) * 1000), True)

        positions = []
        position_deals = {}
        for deal in result.deal:
            pos_id = str(deal.positionId)
            if pos_id not in position_deals:
                position_deals[pos_id] = []
            position_deals[pos_id].append(deal)

        for pos_id, deals in position_deals.items():
            closing_deal = deals[-1]
            opening_deal = deals[0] if len(deals) > 1 else closing_deal
            symbol_spec = state["symbol_id_to_spec_map"].get(closing_deal.symbolId, {})
            symbol_name = symbol_spec.get("symbolName", f"UNKNOWN_{closing_deal.symbolId}")

            gross_profit_cents = 0
            swap_cents = 0
            commission_cents = 0

            for deal in deals:
                if hasattr(deal, 'closePositionDetail'):
                    cpd = deal.closePositionDetail
                    gross_profit_cents += getattr(cpd, 'grossProfit', 0)
                    swap_cents += getattr(cpd, 'swap', 0)
                    commission_cents += getattr(cpd, 'closedCommission', 0) + getattr(cpd, 'commission', 0)
                else:
                    swap_cents += getattr(deal, 'swap', 0)
                    commission_cents += getattr(deal, 'commission', 0)

            net_pnl_cents = gross_profit_cents - abs(commission_cents) + swap_cents

            positions.append({
                "positionId": pos_id,
                "symbol": symbol_name,
                "symbolId": closing_deal.symbolId,
                "tradeSide": "BUY" if closing_deal.tradeSide == TRADE_SIDE_BUY else "SELL",
                "entryPrice_raw": getattr(opening_deal, 'executionPrice', 0),
                "exitPrice_raw": getattr(closing_deal, 'executionPrice', 0),
                "volume_centilots": getattr(closing_deal, 'filledVolume', 0),
                "grossProfit_cents": gross_profit_cents,
                "swap_cents": swap_cents,
                "commission_cents": commission_cents,
                "pnl_cents": net_pnl_cents,
                "pnl": net_pnl_cents / 100,
                "comment": getattr(opening_deal, 'comment', None),
                "openTimestamp": getattr(opening_deal, 'executionTimestamp', None),
                "closeTimestamp": getattr(closing_deal, 'executionTimestamp', None),
                "digits": symbol_spec.get("digits", 5)
            })

        positions.sort(key=lambda x: x.get('closeTimestamp', 0), reverse=True)
        return jsonify({
            "success": True,
            "positions": positions[:limit],
            "count": len(positions[:limit])
        })

    except Exception as e:
        print(f"❌ ERROR /positions/history: {str(e)}")
        log_ctrader_call("/deals/closed", 0, False)
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/prices/current", methods=["POST"])
@require_auth
def get_current_prices():
    try:
        symbols = request.json.get("symbols", [])
        if not symbols:
            return jsonify({"success": False, "error": "symbols required"}), 400

        prices = []
        missing = []
        warming_up = []

        for symbol in symbols:
            symbol_upper = symbol.upper()
            if symbol_upper not in state["last_spot_prices"]:
                missing.append(symbol_upper)
                continue

            raw_price_data = state["last_spot_prices"][symbol_upper]
            bid = raw_price_data.get("bid")
            ask = raw_price_data.get("ask")

            if not bid or not ask or bid <= 0 or ask <= 0:
                warming_up.append(symbol_upper)
                continue

            spec = state["symbols_cache"].get(symbol_upper, {})
            prices.append({
                "symbol": symbol_upper,
                "bid_raw": bid,
                "ask_raw": ask,
                "digits": spec.get("digits", 5),
                "timestamp": raw_price_data.get("timestamp")
            })

        if missing:
            print(f"[/prices/current] Auto-subscribing {len(missing)} missing symbols: {missing}")
            subscribe_to_symbols(missing)

        return jsonify({
            "success": True,
            "prices": prices,
            "missing_symbols": missing if missing else None,
            "warming_up_symbols": warming_up if warming_up else None
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/prices/historical", methods=["POST"])
@require_auth
def get_historical_prices():
    if not state["authenticated"]:
        return jsonify({"success": False, "error": "Not authenticated"}), 503
    try:
        data = request.get_json()
        symbol = data.get("symbol")
        timeframe = data.get("timeframe")
        to_timestamp = data.get("to_timestamp")
        from_timestamp = data.get("from_timestamp")

        if not symbol or not timeframe:
            return jsonify({"success": False, "error": "symbol and timeframe required"}), 400
        if timeframe not in PERIOD_CODE:
            return jsonify({"success": False, "error": f"Invalid timeframe: {timeframe}"}), 400

        ct_timeframe = PERIOD_CODE[timeframe]
        spec = state["symbols_cache"].get(symbol, {})
        if not spec:
            return jsonify({"success": False, "error": f"Symbol {symbol} not found"}), 404

        symbol_id = spec["symbolId"]
        digits = spec["digits"]
        to_ts = int(to_timestamp) if to_timestamp else int(time.time() * 1000)
        from_ts = int(from_timestamp) if from_timestamp else to_ts - (100 * 24 * 60 * 60 * 1000)

        start_time = time.time()
        req = openapi.ProtoOAGetTrendbarsReq()
        req.ctidTraderAccountId = ACCOUNT_ID
        req.symbolId = symbol_id
        req.period = ct_timeframe
        req.fromTimestamp = int(from_ts)
        req.toTimestamp = int(to_ts)
        req.count = 5000

        d, client_msg_id = defer.Deferred(), str(uuid.uuid4())
        pending_requests[client_msg_id] = d
        reactor.callFromThread(lambda: bridge.client.send(req, clientMsgId=client_msg_id))
        result = threads.blockingCallFromThread(reactor, wait_for_deferred, d, 30)
        log_ctrader_call("/prices/historical", int((time.time() - start_time) * 1000), True)

        candles = []
        for tb in result.trendbar:
            timestamp = tb.utcTimestampInMinutes * 60 * 1000
            low_raw = tb.low if hasattr(tb, 'low') else 0
            delta_open_raw = tb.deltaOpen if hasattr(tb, 'deltaOpen') else 0
            delta_high_raw = tb.deltaHigh if hasattr(tb, 'deltaHigh') else 0
            delta_close_raw = tb.deltaClose if hasattr(tb, 'deltaClose') else 0
            candles.append({
                "timestamp": timestamp,
                "low_raw": low_raw,
                "open_raw": low_raw + delta_open_raw,
                "high_raw": low_raw + delta_high_raw,
                "close_raw": low_raw + delta_close_raw,
                "volume": tb.volume if hasattr(tb, 'volume') else 0
            })

        return jsonify({
            "success": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "digits": digits,
            "candles": candles,
            "count": len(candles)
        })

    except Exception as e:
        log_ctrader_call("/prices/historical", 0, False)
        return jsonify({"success": False, "error": str(e)}), 500

# === BRIDGE CLASS ===
# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTION EVENT HANDLER (v4.8)
# ═══════════════════════════════════════════════════════════════════════════════
# Called from on_message when ProtoOAExecutionEvent arrives (push, not poll).
# Maintains position_state{} in real time so endpoints never need ReconcileReq.
#
# ProtoOAExecutionType values used here:
#   2  = ORDER_FILLED  (market order filled — new position opened)
#   7  = POSITION_CLOSED
#   8  = POSITION_AMENDED (SL/TP changed on open position)
#   9  = POSITION_PARTIAL_EXECUTION
#   11 = STOP_OUT
# ═══════════════════════════════════════════════════════════════════════════════

def _handle_execution_event(ev):
    """Update position_state{} from a ProtoOAExecutionEvent push.
    Called directly from on_message — runs on the Twisted reactor thread.
    No blocking calls, no cTrader requests — state update only.

    ProtoOAExecutionType confirmed values (from cTrader Open API docs + live observation):
      ORDER_ACCEPTED      = 1
      ORDER_FILLED        = 2   — fires AFTER POSITION_OPENED; pos.tradeData.openPrice may be 0
      POSITION_OPENED     = 3   — fires first on new position; ev.order.executionPrice = entry (decimal)
      POSITION_CLOSED     = 4   — position fully closed
      POSITION_AMENDED    = 5   — SL/TP changed
      ORDER_CANCELLED     = 6
      ORDER_EXPIRED       = 7
      ORDER_REJECTED      = 8
      ORDER_CANCEL_REJECTED = 9
      STOP_OUT            = 10
      POSITION_PARTIAL_CLOSED = 11
    """
    try:
        exec_type = ev.executionType

        # Confirmed values from Open API docs (verified against live logs)
        EXEC_POSITION_OPENED       = 3
        EXEC_POSITION_CLOSED       = 4
        EXEC_POSITION_AMENDED      = 5
        EXEC_STOP_OUT              = 10
        EXEC_PARTIAL_CLOSED        = 11

        if not hasattr(ev, 'position') or not ev.position:
            return  # No position in this event — ignore (e.g. pending order accepted)

        pos = ev.position
        pos_id = str(pos.positionId)
        symbol_id = pos.tradeData.symbolId
        spec = state['symbol_id_to_spec_map'].get(symbol_id, {})
        digits = spec.get('digits', 5)

        if exec_type in (EXEC_POSITION_CLOSED, EXEC_STOP_OUT):
            removed = state['position_state'].pop(pos_id, None)
            if removed:
                print(f"📤 position_state: removed {pos_id} ({removed.get('symbol','?')}) — exec_type={exec_type}")
            return

        # Build fresh dict from position object
        fresh = _position_to_dict(pos, spec, digits)

        # Entry price: prefer ev.order.executionPrice (decimal double, always accurate).
        # ProtoOATradeData.openPrice is a raw integer — but is sometimes 0 on ORDER_FILLED events.
        # Never overwrite a good cached entry_price with None.
        if hasattr(ev, 'order') and ev.order:
            order_price = getattr(ev.order, 'executionPrice', None)
            if order_price and float(order_price) > 0:
                fresh['entry_price'] = round(float(order_price), digits)

        # Merge into existing state — never overwrite good values with None
        existing = state['position_state'].get(pos_id, {})
        for field in ('entry_price', 'stop_loss', 'take_profit'):
            if fresh.get(field) is None and existing.get(field) is not None:
                fresh[field] = existing[field]

        state['position_state'][pos_id] = fresh
        print(f"📥 position_state: upsert {pos_id} {fresh.get('symbol','?')} {fresh.get('side','?')} "
              f"entry={fresh.get('entry_price')} sl={fresh.get('stop_loss')} tp={fresh.get('take_profit')} "
              f"exec_type={exec_type}")

    except Exception as e:
        print(f"⚠️  _handle_execution_event error: {e}")
        traceback.print_exc()


class Bridge:
    def __init__(self):
        self.client = None

    def start(self):
        if not all([CLIENT_ID, CLIENT_SECRET, ACCESS_TOKEN, ACCOUNT_ID]):
            print("ERROR: Missing credentials")
            return

        self.client = Client(HOST, PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.setMessageReceivedCallback(self.on_message)
        reactor.callFromThread(self.client.startService)

    def on_connected(self, *args):
        state["connected"] = True
        self.client.send(openapi.ProtoOAVersionReq())

    def on_disconnected(self, *args):
        state["connected"] = False
        state["authenticated"] = False

    def on_message(self, client, msg):
# Only log critical Protobuf events (skip price updates)
        if hasattr(msg, 'payloadType'):
            # 2104 = ProtoOAOrderErrorEvent, 2105 = ProtoOAOrderFillEvent, etc.
            if msg.payloadType in [2104, 2105, 2106, 2107, 2108]:
                print(f"📡 BRIDGE WIRE LOG | Type: {msg.payloadType} | Payload: {msg}")

        try:
            pt = msg.payloadType
            client_msg_id = getattr(msg, "clientMsgId", None)

            if client_msg_id and client_msg_id in pending_requests:
                d = pending_requests.pop(client_msg_id)
                if pt == openapi.ProtoOAErrorRes().payloadType:
                    error_payload = openapi.ProtoOAErrorRes()
                    error_payload.ParseFromString(msg.payload)
                    d.errback(Exception(f"Error {error_payload.errorCode}: {error_payload.description}"))
                else:
                    payload_class = None
                    if pt == openapi.ProtoOAApplicationAuthRes().payloadType:
                        payload_class = openapi.ProtoOAApplicationAuthRes
                    elif pt == openapi.ProtoOAAccountAuthRes().payloadType:
                        payload_class = openapi.ProtoOAAccountAuthRes
                    elif pt == openapi.ProtoOATraderRes().payloadType:
                        payload_class = openapi.ProtoOATraderRes
                    elif pt == openapi.ProtoOASymbolsListRes().payloadType:
                        payload_class = openapi.ProtoOASymbolsListRes
                    elif pt == openapi.ProtoOASymbolByIdRes().payloadType:
                        payload_class = openapi.ProtoOASymbolByIdRes
                    elif pt == openapi.ProtoOAReconcileRes().payloadType:
                        payload_class = openapi.ProtoOAReconcileRes
                    elif pt == openapi.ProtoOAExecutionEvent().payloadType:
                        payload_class = openapi.ProtoOAExecutionEvent
                    elif pt == openapi.ProtoOAGetPositionUnrealizedPnLRes().payloadType:
                        payload_class = openapi.ProtoOAGetPositionUnrealizedPnLRes
                    elif pt == openapi.ProtoOAGetTrendbarsRes().payloadType:
                        payload_class = openapi.ProtoOAGetTrendbarsRes
                    elif pt == openapi.ProtoOAGetAccountListByAccessTokenRes().payloadType:
                        payload_class = openapi.ProtoOAGetAccountListByAccessTokenRes
                    elif pt == openapi.ProtoOAAssetListRes().payloadType:
                        payload_class = openapi.ProtoOAAssetListRes
                    elif pt == openapi.ProtoOADealListRes().payloadType:
                        payload_class = openapi.ProtoOADealListRes
                    elif pt == openapi.ProtoOAOrderListRes().payloadType:
                        payload_class = openapi.ProtoOAOrderListRes

                    if payload_class:
                        payload = payload_class()
                        payload.ParseFromString(msg.payload)
                        d.callback(payload)
                    else:
                        d.callback(msg)

                return

            if pt == openapi.ProtoOASpotEvent().payloadType:
                spot_payload = openapi.ProtoOASpotEvent()
                spot_payload.ParseFromString(msg.payload)
                symbol_id = spot_payload.symbolId
                if symbol_id in state["symbol_id_to_spec_map"]:
                    spec = state["symbol_id_to_spec_map"][symbol_id]
                    symbol_name = spec["symbolName"]
                    if safe_hasfield(spot_payload, "bid") and safe_hasfield(spot_payload, "ask"):
                        state["last_spot_prices"][symbol_name] = {
                            "bid": spot_payload.bid,
                            "ask": spot_payload.ask,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
                return

            if pt == openapi.ProtoOAExecutionEvent().payloadType:
                # Push event: position opened / amended / closed.
                # Update position_state{} via handler — no cTrader calls needed.
                ev_payload = openapi.ProtoOAExecutionEvent()
                ev_payload.ParseFromString(msg.payload)
                _handle_execution_event(ev_payload)
                return

            if pt == openapi.ProtoOATraderUpdatedEvent().payloadType:
                # Push event: balance / equity / margin changed (on fill, close, deposit).
                # Keeps account state live without polling ProtoOATraderReq.
                trader_payload = openapi.ProtoOATraderUpdatedEvent()
                trader_payload.ParseFromString(msg.payload)
                trader = trader_payload.trader
                state['balance_cents']      = getattr(trader, 'balance',      state['balance_cents'])
                state['equity_cents']       = getattr(trader, 'moneyBalance', state['equity_cents'])
                state['margin_used_cents']  = getattr(trader, 'usedMargin',   state['margin_used_cents'])
                return

            if pt == openapi.ProtoOAVersionRes().payloadType:
                self.client.send(openapi.ProtoOAApplicationAuthReq(clientId=CLIENT_ID, clientSecret=CLIENT_SECRET))
            elif pt == openapi.ProtoOAApplicationAuthRes().payloadType:
                self.client.send(openapi.ProtoOAGetAccountListByAccessTokenReq(accessToken=ACCESS_TOKEN))
            elif pt == openapi.ProtoOAGetAccountListByAccessTokenRes().payloadType:
                payload = openapi.ProtoOAGetAccountListByAccessTokenRes()
                payload.ParseFromString(msg.payload)
                account = next((a for a in payload.ctidTraderAccount if a.ctidTraderAccountId == ACCOUNT_ID), None)
                if not account:
                    reactor.stop()
                    return
                state["account_type"] = "Live" if getattr(account, 'isLive', False) else "Demo"
                self.client.send(openapi.ProtoOAAccountAuthReq(ctidTraderAccountId=ACCOUNT_ID, accessToken=ACCESS_TOKEN))
            elif pt == openapi.ProtoOAAccountAuthRes().payloadType:
                state["authenticated"] = True
                self.client.send(openapi.ProtoOAAssetListReq(ctidTraderAccountId=ACCOUNT_ID))
            elif pt == openapi.ProtoOAAssetListRes().payloadType:
                payload = openapi.ProtoOAAssetListRes()
                payload.ParseFromString(msg.payload)
                for asset in payload.asset:
                    state["asset_map"][asset.assetId] = asset.name
                self.client.send(openapi.ProtoOATraderReq(ctidTraderAccountId=ACCOUNT_ID))
            elif pt == openapi.ProtoOATraderRes().payloadType:
                payload = openapi.ProtoOATraderRes()
                payload.ParseFromString(msg.payload)
                deposit_asset_id = getattr(payload.trader, 'depositAssetId', None)
                state["account_currency"] = state["asset_map"].get(deposit_asset_id, 'EUR') if deposit_asset_id else 'EUR'
                state["deposit_asset_id"] = deposit_asset_id  # stored for /account/status
                self.client.send(openapi.ProtoOASymbolsListReq(ctidTraderAccountId=ACCOUNT_ID))
            elif pt == openapi.ProtoOASymbolsListRes().payloadType:
                payload = openapi.ProtoOASymbolsListRes()
                payload.ParseFromString(msg.payload)
                for s in payload.symbol:
                    symbol_name = getattr(s, 'symbolName', None)
                    symbol_id = getattr(s, 'symbolId', None)
                    if symbol_name and symbol_id:
                        state["symbol_id_to_name_map"][symbol_id] = symbol_name

                master_symbol_ids = []
                for symbol_name in MASTER_SYMBOLS:
                    symbol_id = next((sid for sid, sname in state["symbol_id_to_name_map"].items() if sname == symbol_name), None)
                    if symbol_id:
                        master_symbol_ids.append((symbol_name, symbol_id))

                total_batches = (len(master_symbol_ids) + 9) // 10
                completed_batches = [0]
                loaded_count = [0]

                for i in range(0, len(master_symbol_ids), 10):
                    batch = master_symbol_ids[i:i+10]
                    batch_ids = [sid for _, sid in batch]
                    req = openapi.ProtoOASymbolByIdReq()
                    req.ctidTraderAccountId = ACCOUNT_ID
                    req.symbolId.extend(batch_ids)

                    d_batch, client_msg_id_batch = defer.Deferred(), str(uuid.uuid4())
                    pending_requests[client_msg_id_batch] = d_batch

                    def process_batch(batch_result, batch_names):
                        for idx, symbol_obj in enumerate(batch_result.symbol):
                            symbol_name = batch_names[idx][0]
                            symbol_id = symbol_obj.symbolId
                            spec_data = {
                                "symbolId": symbol_id,
                                "symbolName": symbol_name,
                                "digits": getattr(symbol_obj, "digits", 5),
                                "pipPosition": getattr(symbol_obj, "pipPosition", None),
                                "lotSize": getattr(symbol_obj, "lotSize", 100000),
                                "minVolume": getattr(symbol_obj, "minVolume", 1),
                                "maxVolume": getattr(symbol_obj, "maxVolume", 10000000),
                                "stepVolume": getattr(symbol_obj, "stepVolume", 1),
                                "quoteAssetId": getattr(symbol_obj, "quoteAssetId", None),
                                "baseAssetId": getattr(symbol_obj, "baseAssetId", None),
                            }
                            state["symbols_cache"][symbol_name] = spec_data
                            state["symbol_id_to_spec_map"][symbol_id] = spec_data
                            loaded_count[0] += 1

                        completed_batches[0] += 1
                        if completed_batches[0] == total_batches:
                            if "subscribed_symbol_ids" not in state:
                                state["subscribed_symbol_ids"] = set()

                            symbols_to_subscribe = []
                            for symbol_name in MASTER_SYMBOLS:
                                if symbol_name in state["symbols_cache"]:
                                    symbol_id = state["symbols_cache"][symbol_name]["symbolId"]
                                    if symbol_id not in state["subscribed_symbol_ids"]:
                                        symbols_to_subscribe.append((symbol_name, symbol_id))

                            for j in range(0, len(symbols_to_subscribe), 10):
                                sub_batch = symbols_to_subscribe[j:j+10]
                                subscribe_msg = openapi.ProtoOASubscribeSpotsReq()
                                subscribe_msg.ctidTraderAccountId = ACCOUNT_ID
                                for _, s_id in sub_batch:
                                    subscribe_msg.symbolId.append(s_id)
                                    state["subscribed_symbol_ids"].add(s_id)
                                reactor.callFromThread(send_subscription(self.client, subscribe_msg))
                                time.sleep(0.5)

                            # ── v4.8: Seed position_state{} with current open positions ──────────
                            # One-time ReconcileReq at startup. After this, position_state{} is
                            # maintained exclusively by ProtoOAExecutionEvent push events.
                            def _seed_position_state(reconcile_result):
                                try:
                                    for pos in reconcile_result.position:
                                        symbol_id = pos.tradeData.symbolId
                                        spec = state['symbol_id_to_spec_map'].get(symbol_id, {})
                                        digits = spec.get('digits', 5)
                                        entry = _position_to_dict(pos, spec, digits)
                                        state['position_state'][str(pos.positionId)] = entry
                                    state['position_state_ready'] = True
                                    count = len(state['position_state'])
                                    print(f"✅ position_state seeded: {count} open positions")
                                    # Single DealListReq handles both entry_price backfill
                                    # and closed_trades_cache population — no separate thread.
                                    _schedule_cache_refresh()
                                except Exception as seed_err:
                                    print(f"⚠️  position_state seed error: {seed_err}")
                                    traceback.print_exc()
                                    state['position_state_ready'] = True

                            reconcile_req = openapi.ProtoOAReconcileReq()
                            reconcile_req.ctidTraderAccountId = ACCOUNT_ID
                            d_reconcile, cid_reconcile = defer.Deferred(), str(uuid.uuid4())
                            pending_requests[cid_reconcile] = d_reconcile
                            d_reconcile.addCallback(_seed_position_state)
                            reactor.callFromThread(
                                lambda r=reconcile_req, c=cid_reconcile: self.client.send(r, clientMsgId=c)
                            )

                    d_batch.addCallback(process_batch, batch)
                    reactor.callFromThread(lambda r=req, c=client_msg_id_batch: self.client.send(r, clientMsgId=c))
                    time.sleep(0.2)

        except Exception as e:
            print(f"ERROR: {str(e)}")
            traceback.print_exc()

bridge = Bridge()

def periodic_cleanup():
    cleanup_old_calls()
    print(f"🧹 Cleanup complete: {len(api_call_log)} cTrader calls in memory")
    reactor.callLater(3600, periodic_cleanup)

if __name__ == "__main__":
    reactor.callWhenRunning(bridge.start)
    reactor.callLater(3600, periodic_cleanup)
    resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(resource)
    reactor.listenTCP(BRIDGE_PORT, site, interface=BRIDGE_HOST)
    print(f"🚀 Bridge v4.8.0 — event-driven position state + closed trades cache")
    print(f"   ✅ Tracks: positions, account, execute, modify, close, deals, historical")
    print(f"   ❌ Skips: contract/specs (cache), prices/current (spot subscription)")
    print(f"   API stats: /stats/api-usage")
    task.LoopingCall(sync_to_cloud_sql).start(60.0)
    reactor.callLater(10, internal_sync_account)
    threading.Thread(target=sync_latest_candles, daemon=True).start()
    reactor.run()

