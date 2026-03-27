#  Tekton AI Trader Bridge v5.0
# Date: 2026-03-24
# FIX: pos.price (double) for entry, stopLoss/takeProfit are doubles — no division

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
    "api_rate_limit": 75,  # cached from settings table, updated on POST /data/settings
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
    "position_state": {},           # Phase 11c: keyed by str(positionId)
    "position_state_ready": False,  # True after live ReconcileReq seed completes
}

# ===== API CALL TRACKING =====
api_call_log = deque(maxlen=100000)

def log_ctrader_call(endpoint, duration_ms, success=True):
    api_call_log.append({
        "timestamp": time.time(),
        "endpoint": endpoint,
        "duration_ms": duration_ms,
        "success": success
    })
    # Rate limit guardrail — warn if approaching cTrader API rate limit
    rate  = len(get_calls_in_window(60))
    limit = state.get("api_rate_limit", 75)
    if rate > int(limit * 0.93):
        print(f"🚨 CRITICAL: cTrader API rate {rate}/min — THROTTLE NON-ESSENTIAL CALLS (limit={limit})")
    elif rate > int(limit * 0.80):
        print(f"⚠️  WARNING: cTrader API rate {rate}/min — approaching limit (limit={limit})")

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


def seed_position_state_from_db():
    """
    DISABLED — was seeding ALL COMPLETED signals including closed trades, causing ghost positions.
    position_state{} is now seeded exclusively from seed_position_state_from_live_reconcile()
    which uses a live ReconcileReq and correctly filters positionStatus == 1 (OPEN only).
    This stub is kept so the callLater reference at startup doesn't break.
    """
    print("ℹ️  seed_position_state_from_db: skipped (superseded by live ReconcileReq seed)")


# ---------------------------------------------------------------------------
# Phase 11c: position_state{} helpers
# ---------------------------------------------------------------------------

def _position_to_dict(pos, spec, digits):
    """Normalise a ProtoOAPosition protobuf into a clean position_state dict.
    Single source of truth — all callers (seed, ExecutionEvent handler) use this.
    ProtoOAPosition.price = decimal double (entry VWAP — use as-is).
    ProtoOAPosition.stopLoss/takeProfit = decimal double (use HasField, no division).
    ProtoOAPosition.tradeData.volume = raw centilots integer.
    """
    pip_pos  = spec.get("pipPosition", digits - 1)
    side_val = getattr(pos.tradeData, "tradeSide", None)
    side     = "BUY" if side_val == 1 else "SELL"

    entry    = round(float(pos.price), digits)      if pos.HasField("price")      else None
    sl       = round(float(pos.stopLoss), digits)   if pos.HasField("stopLoss")   and float(pos.stopLoss)   > 0 else None
    tp       = round(float(pos.takeProfit), digits) if pos.HasField("takeProfit") and float(pos.takeProfit) > 0 else None

    return {
        "id":               str(pos.positionId),
        "symbol":           spec.get("symbolName", f"UNKNOWN_{pos.tradeData.symbolId}"),
        "symbol_id":        pos.tradeData.symbolId,
        "side":             side,
        "volume_raw":       pos.tradeData.volume,
        "entry_price":      entry,
        "stop_loss":        sl,
        "take_profit":      tp,
        "comment":          getattr(pos.tradeData, "comment", None),
        "open_ts":          getattr(pos.tradeData, "openTimestamp", None),
        "digits":           digits,
        "pip_position":     pip_pos,
        "margin_used_cents": getattr(pos, "usedMargin", 0),
    }


def seed_position_state_from_live_reconcile():
    """
    On bridge startup, seed position_state{} from a live ReconcileReq.
    Runs after authentication — gives us accurate volume_raw, digits, pip_position,
    entry_price, sl, tp for all currently open positions.
    Sets state['position_state_ready'] = True when complete so /positions/list
    can serve from cache rather than falling back to a fresh ReconcileReq.
    """
    try:
        req = openapi.ProtoOAReconcileReq()
        req.ctidTraderAccountId = ACCOUNT_ID
        d, mid = defer.Deferred(), str(uuid.uuid4())
        pending_requests[mid] = d
        reactor.callFromThread(lambda: bridge.client.send(req, clientMsgId=mid))
        result = threads.blockingCallFromThread(reactor, wait_for_deferred, d, 15)

        if "position_state" not in state:
            state["position_state"] = {}

        seeded = 0
        for pos in result.position:
            if hasattr(pos, "positionStatus") and pos.positionStatus != 1:
                continue
            pos_id = str(pos.positionId)
            spec   = state["symbol_id_to_spec_map"].get(pos.tradeData.symbolId, {})
            digits = spec.get("digits", 5)
            d_pos  = _position_to_dict(pos, spec, digits)
            # Merge — don't overwrite fields already enriched by ExecutionEvents
            ps = state["position_state"].setdefault(pos_id, {})
            for k, v in d_pos.items():
                if v is not None and ps.get(k) is None:
                    ps[k] = v
            seeded += 1

        state["position_state_ready"] = True
        print(f"🌱 position_state seeded from live ReconcileReq: {seeded} positions hydrated")

    except Exception as e:
        # Non-fatal — /positions/list will fall back to direct ReconcileReq
        state["position_state_ready"] = False
        print(f"⚠️  seed_position_state_from_live_reconcile error: {e}")


def _handle_unsolicited_execution_event(payload):
    """
    Handle push ExecutionEvents from cTrader (no clientMsgId — not a response to a request).
    Updates position_state{} live: new opens add an entry, closes remove it.
    Called from on_message whenever an ExecutionEvent arrives without a pending clientMsgId.
    """
    try:
        exec_type = getattr(payload, "executionType", None)
        # executionType: 2=ORDER_FILLED, 3=ORDER_CANCELLED, 4=ORDER_EXPIRED,
        #                5=ORDER_AMENDED, 6=ORDER_REJECTED
        # For position_state purposes we care about position open/close/amend.
        pos = getattr(payload, "position", None)
        if pos is None:
            return

        pos_id = str(pos.positionId)
        spec   = state["symbol_id_to_spec_map"].get(pos.tradeData.symbolId, {})
        digits = spec.get("digits", 5)

        # positionStatus: 1=OPEN, 2=CLOSED
        pos_status = getattr(pos, "positionStatus", None)

        if pos_status == 2:
            # Position closed — remove from state
            if pos_id in state.get("position_state", {}):
                del state["position_state"][pos_id]
                print(f"📤 position_state: removed closed position {pos_id}")
        else:
            # New or amended position — upsert
            if "position_state" not in state:
                state["position_state"] = {}
            d_pos = _position_to_dict(pos, spec, digits)
            ps    = state["position_state"].setdefault(pos_id, {})
            # Always overwrite with latest from cTrader push (most authoritative).
            # Exception: if spec lookup failed (UNKNOWN symbol), preserve existing
            # symbol/symbol_id from position_state — don't overwrite with UNKNOWN.
            existing_symbol = ps.get("symbol", "")
            for k, v in d_pos.items():
                if v is not None:
                    if k == "symbol" and v.startswith("UNKNOWN_") and existing_symbol and not existing_symbol.startswith("UNKNOWN_"):
                        continue  # keep the known symbol name we already have
                    ps[k] = v
            print(f"📥 position_state: upserted {ps.get('symbol','?')} pos {pos_id} ({d_pos.get('side','?')})")

    except Exception as e:
        print(f"⚠️  _handle_unsolicited_execution_event error: {e}")

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
        "version": "5.0",
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
    if not state["authenticated"]:
        return jsonify({"success": False, "error": "Not authenticated"}), 503
    try:
        # Phase 11c: serve from position_state{} — no ReconcileReq needed.
        # position_state{} is seeded at startup via live ReconcileReq and kept live by
        # push ExecutionEvents. Falls back to a fresh ReconcileReq if seed not yet ready.
        if not state.get("position_state_ready"):
            # Seed not done yet — kick it off in a background thread and return 503.
            # Only fires in the brief window after bridge restart before t+20s seed completes.
            print("⚠️  /positions/list: position_state not ready — kicking background seed")
            threading.Thread(target=seed_position_state_from_live_reconcile, daemon=True).start()
            return jsonify({"success": False, "error": "Bridge still initialising — retry in a few seconds"}), 503

        # Normal path: serve from cached position_state{} + live PnL
        start_time_pnl = time.time()
        pnl_msg = openapi.ProtoOAGetPositionUnrealizedPnLReq()
        pnl_msg.ctidTraderAccountId = ACCOUNT_ID
        d_pnl, mid_pnl = defer.Deferred(), str(uuid.uuid4())
        pending_requests[mid_pnl] = d_pnl
        reactor.callFromThread(lambda: bridge.client.send(pnl_msg, clientMsgId=mid_pnl))
        pnl_result = threads.blockingCallFromThread(reactor, wait_for_deferred, d_pnl, 10)
        log_ctrader_call("/positions/list_pnl", int((time.time() - start_time_pnl) * 1000), True)

        pnl_map = {}
        if hasattr(pnl_result, "positionUnrealizedPnL"):
            for pnl_entry in pnl_result.positionUnrealizedPnL:
                pid = str(pnl_entry.positionId)
                pnl_map[pid] = {
                    "grossPnL_cents": safe_get_field(pnl_entry, "grossUnrealizedPnL", 0),
                    "netPnL_cents":   safe_get_field(pnl_entry, "netUnrealizedPnL", 0),
                }

        positions = []
        for pos_id, ps in state.get("position_state", {}).items():
            pnl_data = pnl_map.get(pos_id, {"grossPnL_cents": 0, "netPnL_cents": 0})
            positions.append({
                "positionId":             pos_id,
                "symbol":                 ps.get("symbol", "UNKNOWN"),
                "tradeSide":              ps.get("side", "BUY"),
                "unrealizedNetPnL_cents": pnl_data["netPnL_cents"],
                "marginUsed_cents":       ps.get("margin_used_cents", 0),
                "volume":                 ps.get("volume_raw", 0),
                "entryPrice":             ps.get("entry_price"),
                "stopLoss":               ps.get("stop_loss"),
                "takeProfit":             ps.get("take_profit"),
                "comment":                ps.get("comment"),
                "openTimestamp":          ps.get("open_ts"),
                "digits":                 ps.get("digits", 5),
            })

        return jsonify({"success": True, "positions": positions, "count": len(positions), "source": "position_state"})

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
    if not state["authenticated"]:
        return jsonify({"success": False, "error": "Not authenticated"}), 503
    try:
        start_time = time.time()
        trader_msg = openapi.ProtoOATraderReq()
        trader_msg.ctidTraderAccountId = ACCOUNT_ID
        d, client_msg_id = defer.Deferred(), str(uuid.uuid4())
        pending_requests[client_msg_id] = d

        reactor.callFromThread(lambda: bridge.client.send(trader_msg, clientMsgId=client_msg_id))
        trader_result = threads.blockingCallFromThread(reactor, wait_for_deferred, d, 30)
        log_ctrader_call("/account/info", int((time.time() - start_time) * 1000), True)

        trader = trader_result.trader
        balance_cents = getattr(trader, 'balance', 0)
        equity_cents = getattr(trader, 'moneyBalance', balance_cents)
        margin_used_cents = getattr(trader, 'usedMargin', 0)
        free_margin_cents = getattr(trader, 'freeMargin', 0)
        deposit_asset_id = getattr(trader, 'depositAssetId', None)

        state["balance_cents"] = balance_cents
        state["equity_cents"] = equity_cents
        state["margin_used_cents"] = margin_used_cents

        currency = "EUR"
        if deposit_asset_id and deposit_asset_id in state.get("asset_map", {}):
            currency = state["asset_map"].get(deposit_asset_id, "EUR")

        account_type = "demo" if not getattr(trader, 'isLive', False) else "live"

        return jsonify({
            "success": True,
            "account_info": {
                "accountId": ACCOUNT_ID,
                "balance_cents": balance_cents,
                "equity_cents": equity_cents,
                "usedMargin_cents": margin_used_cents,
                "freeMargin_cents": free_margin_cents,
                "currency": currency,
                "accountType": account_type
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

    balance = state.get("balance_cents", 0) / 100
    return jsonify({
        "success": True,
        "balance": round(balance, 2),
        "equity": round(equity, 2),
        "free_margin": round(free_margin, 2),
        "margin_used": round(margin_used, 2),
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
            auto_trade             = data.get("auto_trade", data.get("autoTrade", False))
            friday_flush           = data.get("friday_flush", data.get("fridayFlush", False))
            risk_pct               = data.get("risk_pct", 0.01)
            target_reward          = data.get("target_reward", 1.8)
            daily_drawdown_limit   = data.get("daily_drawdown_limit", 0.05)
            max_session_exposure_pct = data.get("max_session_exposure_pct", 4.0)
            max_lots               = data.get("max_lots", 50.0)
            min_sl_pips            = data.get("min_sl_pips", 8.0)
            news_blackout_mins     = data.get("news_blackout_mins", 30)
            news_filter_enabled    = bool(data.get("news_filter_enabled", True))

            cur.execute("""
                INSERT INTO settings (id, auto_trade, friday_flush, risk_pct, target_reward,
                                      daily_drawdown_limit, max_session_exposure_pct, max_lots, min_sl_pips,
                                      news_blackout_mins, news_filter_enabled)
                VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    auto_trade               = EXCLUDED.auto_trade,
                    friday_flush             = EXCLUDED.friday_flush,
                    risk_pct                 = EXCLUDED.risk_pct,
                    target_reward            = EXCLUDED.target_reward,
                    daily_drawdown_limit     = EXCLUDED.daily_drawdown_limit,
                    max_session_exposure_pct = EXCLUDED.max_session_exposure_pct,
                    max_lots                 = EXCLUDED.max_lots,
                    min_sl_pips              = EXCLUDED.min_sl_pips,
                    news_blackout_mins       = EXCLUDED.news_blackout_mins,
                    news_filter_enabled      = EXCLUDED.news_filter_enabled
            """, (auto_trade, friday_flush, risk_pct, target_reward,
                    daily_drawdown_limit, max_session_exposure_pct, max_lots, min_sl_pips,
                    news_blackout_mins, news_filter_enabled))
            conn.commit()
        else:
            cur.execute("""
                SELECT auto_trade, friday_flush, risk_pct, target_reward,
                       daily_drawdown_limit, max_session_exposure_pct, max_lots, min_sl_pips, news_blackout_mins, news_filter_enabled
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
                    "news_blackout_mins":        int(row[8]) if row[8] is not None else 30,
                    "news_filter_enabled":       bool(row[9]) if row[9] is not None else True
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
            "news_blackout_mins":        int(news_blackout_mins),
            "news_filter_enabled":       bool(news_filter_enabled)
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

        
def fetch_all_deals(from_ts: int, to_ts: int, max_rows_per_page: int = 500) -> list:
    """
    Paginate through ProtoOADealListReq until hasMore=False.
    cTrader returns up to max_rows_per_page deals per call, oldest-first.
    We walk forward using the last deal's executionTimestamp as the next fromTimestamp.
    Returns a flat list of all ProtoOADeal objects across all pages.
    """
    all_deals = []
    page_from_ts = from_ts
    page = 0

    while True:
        page += 1
        req = openapi.ProtoOADealListReq()
        req.ctidTraderAccountId = ACCOUNT_ID
        req.fromTimestamp = page_from_ts
        req.toTimestamp   = to_ts
        req.maxRows       = max_rows_per_page

        d, mid = defer.Deferred(), str(uuid.uuid4())
        pending_requests[mid] = d
        reactor.callFromThread(lambda: bridge.client.send(req, clientMsgId=mid))
        result = threads.blockingCallFromThread(reactor, wait_for_deferred, d, 30)

        deals = list(result.deal)
        all_deals.extend(deals)

        has_more = getattr(result, 'hasMore', False)
        print(f"📄 fetch_all_deals page {page}: {len(deals)} deals, hasMore={has_more}")

        if not has_more or not deals:
            break

        # Advance window: next page starts from the timestamp of the last deal returned + 1ms
        last_ts = getattr(deals[-1], 'executionTimestamp', None)
        if not last_ts or last_ts >= to_ts:
            break
        page_from_ts = last_ts + 1

    print(f"✅ fetch_all_deals: {len(all_deals)} total deals across {page} page(s)")
    return all_deals


@app.route("/proxy/executions", methods=["GET"])
@require_auth
def get_executions():
    try:
        # --- 1. Build Open Positions from position_state{} (Phase 11c) ---
        # No live ReconcileReq — position_state{} is authoritative (seeded at startup
        # from ReconcileReq and kept live by ExecutionEvent handler).
        open_trades = []
        position_state = state.get('position_state', {})
        for pid, ps in position_state.items():
            symbol   = ps.get('symbol', 'UNKNOWN')
            side     = ps.get('side', 'BUY')
            volume   = ps.get('volume_raw')
            entry    = ps.get('entry_price')
            sl       = ps.get('stop_loss')
            tp       = ps.get('take_profit')
            open_ts  = ps.get('open_ts')
            comment  = ps.get('comment')
            digits   = ps.get('digits', 5)
            open_trades.append({
                "id":           pid,
                "signal_uuid":  comment if comment else None,
                "symbol":       symbol,
                "side":         side,
                "volume":       round(float(volume) / 10_000_000, 2) if volume else None,
                "entry_price":  entry,
                "stop_loss":    sl,
                "take_profit":  tp,
                "close_price":  None,
                "pnl":          None,
                "status":       "open",
                "created_at":   datetime.fromtimestamp(open_ts / 1000).isoformat() if open_ts else None,
                "closed_at":    None,
                "digits":       digits
            })

        # --- 2. Fetch Closed Positions (Last 30 Days) ---
        closed_trades = []
        to_ts = int(time.time() * 1000)
        from_ts = to_ts - (30 * 24 * 60 * 60 * 1000)

        # Paginated DealListReq — fetches all pages until hasMore=False (Phase 11d)
        all_deals = fetch_all_deals(from_ts, to_ts)

        position_deals = {}
        for deal in all_deals:
            pos_id = str(deal.positionId)
            if pos_id not in position_deals:
                position_deals[pos_id] = []
            position_deals[pos_id].append(deal)

        # OrderListReq removed — entry_price now comes from position_state{} directly.

        for pos_id, deals in position_deals.items():
            closing_deal = next((d for d in deals if hasattr(d, 'closePositionDetail')), None)
            if not closing_deal:
                continue

            opening_deal = deals[0]
            spec = state["symbol_id_to_spec_map"].get(closing_deal.symbolId, {})
            symbol_name = spec.get("symbolName", f"UNKNOWN_{closing_deal.symbolId}")
            digits = spec.get("digits", 5)
            hist_comment = getattr(opening_deal, 'comment', None)

            gross_pnl = 0
            commission = 0
            swap = 0
            for deal in deals:
                if hasattr(deal, 'closePositionDetail'):
                    cpd = deal.closePositionDetail
                    gross_pnl += getattr(cpd, 'grossProfit', 0)
                    swap += getattr(cpd, 'swap', 0)
                    commission += getattr(cpd, 'closedCommission', 0) + getattr(cpd, 'commission', 0)
                else:
                    swap += getattr(deal, 'swap', 0)
                    commission += getattr(deal, 'commission', 0)

            net_pnl_cents = gross_pnl - abs(commission) + swap
            open_ts = getattr(opening_deal, 'executionTimestamp', None)
            close_ts = getattr(closing_deal, 'executionTimestamp', None)

            filled_vol = getattr(closing_deal, 'filledVolume', 0)
            # FIX: ProtoOADeal.executionPrice is already a decimal double (e.g. 1.71536),
            # NOT a raw integer. Dividing by 10^digits was producing values ~0.00001
            # which failed the sanity check and returned None.
            # Use directly — same behaviour confirmed in /positions/history endpoint.
            # ProtoOADeal.executionPrice is a decimal double but is 0.0 for some market orders.
            # For the opening deal: use executionPrice if > 0, else fall back to closePositionDetail.closePrice (raw int → divide)
            # For the closing deal: prefer closePositionDetail.closePrice (raw int) which is always populated.
            #   Fall back to executionPrice if closePrice is missing.
            entry_exec = getattr(opening_deal, 'executionPrice', None)
            entry_raw  = float(entry_exec) if entry_exec and float(entry_exec) > 0 else None

            cpd_close  = getattr(closing_deal, 'closePositionDetail', None)
            # closePositionDetail.closePrice = raw integer price (divide by 10^digits)
            # Try both 'closePrice' and 'price' field names across protobuf versions
            close_cpd_raw = None
            if cpd_close:
                close_cpd_raw = (getattr(cpd_close, 'closePrice', None)
                                 or getattr(cpd_close, 'price', None)
                                 or getattr(cpd_close, 'closedBalance', None))
            close_exec = getattr(closing_deal, 'executionPrice', None)
            if close_cpd_raw and float(close_cpd_raw) > 0:
                # closePrice is a raw integer — divide by 10^digits
                scaled_close = round(float(close_cpd_raw) / (10 ** digits), digits)
            elif close_exec and float(close_exec) > 0:
                scaled_close = round(float(close_exec), digits)
            else:
                scaled_close = None
                print(f"DEBUG cpd_close fields: {[f.name for f in cpd_close.DESCRIPTOR.fields] if cpd_close else 'None'}")

            scaled_entry = round(entry_raw, digits) if entry_raw else None
            closed_trades.append({
                "id": pos_id,
                "signal_uuid": hist_comment if hist_comment else None,
                "symbol": symbol_name,
                "side": "BUY" if opening_deal.tradeSide == TRADE_SIDE_BUY else "SELL",
                "volume": round(filled_vol / 10000000, 2),
                "entry_price": scaled_entry,
                "close_price": scaled_close,
                "stop_loss": None,
                "take_profit": None,
                "pnl": round(net_pnl_cents / 100, 2),
                "status": "closed",
                "created_at": datetime.fromtimestamp(open_ts / 1000).isoformat() if open_ts else None,
                "closed_at": datetime.fromtimestamp(close_ts / 1000).isoformat() if close_ts else None,
                "digits": digits
            })

        # ── Enrich open trades with sl_pips/tp_pips/strategy from SQL ──────────
        try:
            uuids = [t["signal_uuid"] for t in open_trades if t.get("signal_uuid") and isinstance(t["signal_uuid"], str)]
            if uuids:
                enrich_conn = psycopg2.connect(
                    host=os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
                    database=os.getenv("CLOUD_SQL_DB_NAME", "tekton-trader"),
                    user=os.getenv("CLOUD_SQL_DB_USER", "postgres"),
                    password=os.getenv("CLOUD_SQL_DB_PASSWORD")
                )
                enrich_cur = enrich_conn.cursor()
                placeholders = ",".join(["%s"] * len(uuids))
                enrich_cur.execute(
                    f"SELECT signal_uuid::text, sl_pips, tp_pips, strategy, avg_fill_price, sl_price, tp_price FROM signals WHERE signal_uuid::text IN ({placeholders})",
                    uuids
                )
                signal_map = {str(row[0]): {"sl_pips": row[1], "tp_pips": row[2], "strategy": row[3], "avg_fill_price": row[4], "sl_price": row[5], "tp_price": row[6]} for row in enrich_cur.fetchall()}
                enrich_cur.close()
                enrich_conn.close()
                for t in open_trades:
                    sig = signal_map.get(str(t.get("signal_uuid") or ""))
                    if sig:
                        t["sl_pips"] = float(sig["sl_pips"]) if sig["sl_pips"] else None
                        t["tp_pips"] = float(sig["tp_pips"]) if sig["tp_pips"] else None
                        t["strategy"] = sig["strategy"]
                        if t["entry_price"] is None and sig.get("avg_fill_price"):
                            t["entry_price"] = float(sig["avg_fill_price"])
                        # Use stored absolute SL/TP prices from signals as position_state fallback
                        if t["stop_loss"] is None and sig.get("sl_price"):
                            t["stop_loss"]   = float(sig["sl_price"])
                        if t["take_profit"] is None and sig.get("tp_price"):
                            t["take_profit"] = float(sig["tp_price"])
        except Exception as enrich_err:
            import traceback as _tb
            print(f"WARNING Signal enrichment failed (non-fatal): {enrich_err}")
            _tb.print_exc()

        # ── Enrich closed trades with signal_uuid from SQL by position_id ──────
        try:
            pos_ids = [t["id"] for t in closed_trades if not t.get("signal_uuid")]
            if pos_ids:
                enrich_conn2 = psycopg2.connect(
                    host=os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
                    database=os.getenv("CLOUD_SQL_DB_NAME", "tekton-trader"),
                    user=os.getenv("CLOUD_SQL_DB_USER", "postgres"),
                    password=os.getenv("CLOUD_SQL_DB_PASSWORD")
                )
                enrich_cur2 = enrich_conn2.cursor()
                placeholders2 = ",".join(["%s"] * len(pos_ids))
                enrich_cur2.execute(
                    f"SELECT position_id, signal_uuid::text, sl_pips, tp_pips, strategy, sl_price, tp_price, avg_fill_price FROM signals WHERE position_id IN ({placeholders2})",
                    pos_ids
                )
                pos_signal_map = {row[0]: {"signal_uuid": row[1], "sl_pips": row[2], "tp_pips": row[3],
                                           "strategy": row[4], "sl_price": row[5], "tp_price": row[6],
                                           "avg_fill_price": row[7]} for row in enrich_cur2.fetchall()}
                enrich_cur2.close()
                enrich_conn2.close()
                for t in closed_trades:
                    sig = pos_signal_map.get(t["id"])
                    if sig:
                        if not t.get("signal_uuid"):
                            t["signal_uuid"] = sig["signal_uuid"]
                        t["sl_pips"] = float(sig["sl_pips"]) if sig["sl_pips"] else None
                        t["tp_pips"] = float(sig["tp_pips"]) if sig["tp_pips"] else None
                        t["strategy"] = sig["strategy"]
                        # Use stored absolute SL/TP price if available (avoids "Xp" fallback)
                        if sig.get("sl_price") and not t.get("stop_loss"):
                            t["stop_loss"]   = float(sig["sl_price"])
                        if sig.get("tp_price") and not t.get("take_profit"):
                            t["take_profit"] = float(sig["tp_price"])
                        if sig.get("avg_fill_price") and not t.get("entry_price"):
                            t["entry_price"] = float(sig["avg_fill_price"])
        except Exception as enrich_err2:
            print(f"WARNING Closed trade enrichment failed (non-fatal): {enrich_err2}")

        # ── PASS 2: Enrich by UUID (comment field) for trades still missing signal_uuid ──
        # Covers trades where position_id was never written to signals table
        # (pre-fix executor used status=EXECUTED and never stored position_id).
        # The cTrader deal comment field = signal_uuid written at order time.
        try:
            uuids_from_comment = [
                t["signal_uuid"] for t in closed_trades
                if t.get("signal_uuid") and not t.get("strategy")
            ]
            # Also collect trades that got uuid from comment but still lack enrichment
            # Build uuid→trade map for all closed trades that have a uuid but no strategy
            uuid_needs_enrich = {
                t["signal_uuid"]: t for t in closed_trades
                if t.get("signal_uuid") and not t.get("strategy")
            }
            if uuid_needs_enrich:
                enrich_conn3 = psycopg2.connect(
                    host=os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
                    database=os.getenv("CLOUD_SQL_DB_NAME", "tekton-trader"),
                    user=os.getenv("CLOUD_SQL_DB_USER", "postgres"),
                    password=os.getenv("CLOUD_SQL_DB_PASSWORD")
                )
                enrich_cur3 = enrich_conn3.cursor()
                uuid_list = list(uuid_needs_enrich.keys())
                placeholders3 = ",".join(["%s"] * len(uuid_list))
                enrich_cur3.execute(
                    f"""SELECT signal_uuid::text, sl_pips, tp_pips, strategy,
                               sl_price, tp_price, avg_fill_price, position_id
                        FROM signals
                        WHERE signal_uuid::text IN ({placeholders3})""",
                    uuid_list
                )
                uuid_signal_map = {
                    row[0]: {
                        "sl_pips": row[1], "tp_pips": row[2], "strategy": row[3],
                        "sl_price": row[4], "tp_price": row[5],
                        "avg_fill_price": row[6], "position_id": row[7]
                    } for row in enrich_cur3.fetchall()
                }
                enrich_cur3.close()
                enrich_conn3.close()
                enriched_count = 0
                for t in closed_trades:
                    uuid_key = t.get("signal_uuid")
                    if not uuid_key or t.get("strategy"):
                        continue
                    sig = uuid_signal_map.get(uuid_key)
                    if sig:
                        t["sl_pips"]    = float(sig["sl_pips"])    if sig["sl_pips"]    else None
                        t["tp_pips"]    = float(sig["tp_pips"])    if sig["tp_pips"]    else None
                        t["strategy"]   = sig["strategy"]
                        if sig.get("sl_price") and not t.get("stop_loss"):
                            t["stop_loss"]   = float(sig["sl_price"])
                        if sig.get("tp_price") and not t.get("take_profit"):
                            t["take_profit"] = float(sig["tp_price"])
                        if sig.get("avg_fill_price") and not t.get("entry_price"):
                            t["entry_price"] = float(sig["avg_fill_price"])
                        # Backfill position_id into signals table so Pass 1 works next time
                        if sig["position_id"] is None and t.get("id"):
                            try:
                                bp_conn = psycopg2.connect(
                                    host=os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
                                    database=os.getenv("CLOUD_SQL_DB_NAME", "tekton-trader"),
                                    user=os.getenv("CLOUD_SQL_DB_USER", "postgres"),
                                    password=os.getenv("CLOUD_SQL_DB_PASSWORD")
                                )
                                bp_cur = bp_conn.cursor()
                                bp_cur.execute(
                                    "UPDATE signals SET position_id = %s WHERE signal_uuid::text = %s AND position_id IS NULL",
                                    (t["id"], uuid_key)
                                )
                                bp_conn.commit()
                                bp_cur.close()
                                bp_conn.close()
                                enriched_count += 1
                            except Exception as bp_err:
                                print(f"WARNING position_id backfill failed for {uuid_key}: {bp_err}")
                if enriched_count:
                    print(f"INFO Pass2 enrichment: backfilled position_id for {enriched_count} signals")
        except Exception as enrich_err3:
            print(f"WARNING Pass2 UUID enrichment failed (non-fatal): {enrich_err3}")

        closed_trades.sort(key=lambda x: x.get('closed_at') or '', reverse=True)

        # --- Deduplication ---
        # open_trades comes from ReconcileReq (live positions).
        # closed_trades comes from DealListReq (historical deals).
        # A position that is currently open will ALSO appear in DealListReq
        # (as an opening deal without a closePositionDetail) so we must exclude it
        # from closed_trades to prevent duplicate rows in the UI.
        open_pos_ids = {t['id'] for t in open_trades}
        closed_trades_deduped = [t for t in closed_trades if t['id'] not in open_pos_ids]

        # Also deduplicate within closed_trades by position ID — keep only one row per
        # position (the one with the most complete data — preferring non-None close_price).
        seen_closed = {}
        for t in closed_trades_deduped:
            pid = t['id']
            if pid not in seen_closed:
                seen_closed[pid] = t
            else:
                # Prefer the entry with a real close_price and real P&L
                existing = seen_closed[pid]
                if t.get('close_price') and not existing.get('close_price'):
                    seen_closed[pid] = t
                elif t.get('pnl') is not None and existing.get('pnl') is None:
                    seen_closed[pid] = t
        closed_trades_final = list(seen_closed.values())
        closed_trades_final.sort(key=lambda x: x.get('closed_at') or '', reverse=True)

        return jsonify({
            "success": True,
            "executions": open_trades + closed_trades_final
        })

    except Exception as e:
        print(f"❌ Executions Proxy Error: {str(e)}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

def sync_latest_candles():
    while True:
        time.sleep(900)
        # ... candle sync logic ...

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

        conn = psycopg2.connect(
            host=os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
            database=os.getenv("CLOUD_SQL_DB_NAME", "tekton-trader"),
            user=os.getenv("CLOUD_SQL_DB_USER", "postgres"),
            password=os.getenv("CLOUD_SQL_DB_PASSWORD")
        )
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
            SELECT signal_uuid, symbol, signal_type, timeframe, confidence_score, sl_pips, tp_pips, status, created_at, position_id, strategy, avg_fill_price, error_reason
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
                "uuid":        row[0],
                "symbol":      row[1],
                "direction":   row[2],
                "timeframe":   row[3],
                "confidence":  row[4],
                "sl_pips":     float(row[5]) if row[5] else None,
                "tp_pips":     float(row[6]) if row[6] else None,
                "status":      row[7],
                "created_at":  row[8].strftime("%Y-%m-%d %H:%M:%S") if row[8] else "N/A",
                "position_id": row[9],
                "strategy":    row[10],
                "error_reason": row[12],
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
        conn = psycopg2.connect(
            host=os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
            database=os.getenv("CLOUD_SQL_DB_NAME", "tekton-trader"),
            user=os.getenv("CLOUD_SQL_DB_USER", "postgres"),
            password=os.getenv("CLOUD_SQL_DB_PASSWORD")
        )
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
        comment = data.get("comment", "")

        spec = state["symbols_cache"].get(symbol, {})
        if not spec:
            return jsonify({"success": False, "error": f"Symbol {symbol} not found"}), 404

        symbol_id = spec.get("symbolId") or spec.get("symbol_id")

        # Volume: accept either centilots (int) or lots (float).
        # Executor sends centilots already. Direct/manual calls may send lots.
        # Detect: if value is a float OR < 1000, treat as lots and convert.
        raw_vol = data.get("volume_centilots") or data.get("volume")
        if isinstance(raw_vol, float) or (isinstance(raw_vol, (int, float)) and raw_vol < 1000):
            vol = int(round(float(raw_vol) * 10_000_000))  # lots → centilots
        else:
            vol = int(raw_vol)  # already centilots

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

        digits        = spec.get("digits", 5) if spec else 5
        pos_id        = result.position.positionId if hasattr(result, 'position') else 0
        # ProtoOAOrder.executionPrice is 0.0 for MARKET orders (filled async).
        # ProtoOAPosition.price is a decimal double — MUST use HasField(), not getattr().
        # getattr returns 0 (not None) for unset protobuf fields — silently fails the > 0 check.
        entry_price = None
        sl_abs      = None
        tp_abs      = None
        if hasattr(result, 'position') and result.position:
            pos = result.position
            if pos.HasField('price') and float(pos.price) > 0:
                entry_price = round(float(pos.price), digits)
            # Also store SL/TP prices in position_state{} so proxy/executions can serve them
            sl_abs = round(float(pos.stopLoss),   digits) if pos.HasField('stopLoss')   and float(pos.stopLoss)   > 0 else None
            tp_abs = round(float(pos.takeProfit), digits) if pos.HasField('takeProfit') and float(pos.takeProfit) > 0 else None
            pid_str = str(pos_id)
            if pid_str not in state.get('position_state', {}):
                state.setdefault('position_state', {})[pid_str] = {}
            ps = state['position_state'][pid_str]
            if entry_price and ps.get('entry_price') is None:
                ps['entry_price'] = entry_price
            if sl_abs and ps.get('stop_loss') is None:
                ps['stop_loss'] = sl_abs
            if tp_abs and ps.get('take_profit') is None:
                ps['take_profit'] = tp_abs

        print(f"✅ Executed {symbol}: pos_id={pos_id} entry={entry_price} digits={digits}")

        return jsonify({
            "success":     True,
            "position_id": pos_id,
            "entry_price": entry_price,   # scaled decimal, ready to store in signals.avg_fill_price
            "sl_price":    sl_abs,        # absolute SL price (decimal) — store in signals.sl_price
            "tp_price":    tp_abs,        # absolute TP price (decimal) — store in signals.tp_price
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
        # Pips mode takes priority — bridge calculates absolute price from cached entry + side.
        sl_price = data.get("sl_price") or data.get("stopLoss_raw")
        tp_price = data.get("tp_price") or data.get("takeProfit_raw")
        sl_pips  = data.get("sl_pips")
        tp_pips  = data.get("tp_pips")

        if not position_id:
            return jsonify({"success": False, "error": "position_id required"}), 400
        if sl_price is None and tp_price is None and sl_pips is None and tp_pips is None:
            return jsonify({"success": False, "error": "At least one of sl_price, tp_price, sl_pips, tp_pips required"}), 400

        # Phase 11c: look up position from position_state{} — no ReconcileReq needed.
        # position_state{} is seeded at startup and kept live by ProtoOAExecutionEvent pushes.
        ps = state.get("position_state", {}).get(str(position_id))
        if not ps:
            return jsonify({"success": False, "error": f"Position {position_id} not found in position_state — may already be closed"}), 404

        digits   = ps.get("digits", 5)
        pip_pos  = ps.get("pip_position", digits - 1)
        pip_size = 10 ** -pip_pos

        # If pips provided, derive absolute price from cached entry price
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

        # ProtoOAAmendPositionSLTPReq expects DECIMAL DOUBLE — pass directly, no raw conversion.
        # BUG FIX: previous code was sending int(round(price * 10^digits)) — cTrader rejected this.
        if sl_price is not None:
            req.stopLoss   = round(float(sl_price), digits)
        if tp_price is not None:
            req.takeProfit = round(float(tp_price), digits)

        print(f"🛠️ Modifying ID {position_id} | sl_pips={sl_pips} tp_pips={tp_pips} | SL={getattr(req, 'stopLoss', 'N/A')} TP={getattr(req, 'takeProfit', 'N/A')}")

        d_mod, mid_mod = defer.Deferred(), str(uuid.uuid4())
        pending_requests[mid_mod] = d_mod
        reactor.callFromThread(lambda: bridge.client.send(req, clientMsgId=mid_mod))
        result = threads.blockingCallFromThread(reactor, wait_for_deferred, d_mod, 15)

        if hasattr(result, 'errorCode') and result.errorCode:
            desc = getattr(result, 'description', '') or str(result.errorCode)
            return jsonify({"success": False, "error": f"cTrader error {result.errorCode}: {desc}"}), 400

        # Update position_state{} immediately so subsequent reads reflect the change
        if sl_price is not None:
            state["position_state"][str(position_id)]["stop_loss"]   = round(float(sl_price), digits)
        if tp_price is not None:
            state["position_state"][str(position_id)]["take_profit"] = round(float(tp_price), digits)

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
        # Paginated DealListReq — fetches all pages until hasMore=False (Phase 11d)
        all_deals = fetch_all_deals(from_timestamp, to_timestamp)
        log_ctrader_call("/deals/closed", 0, True)

        positions = []
        position_deals = {}
        for deal in all_deals:
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

            # Phase 11c: handle unsolicited push ExecutionEvents (no clientMsgId)
            # Updates position_state{} live — opens add, closes remove, amends update.
            if pt == openapi.ProtoOAExecutionEvent().payloadType:
                exec_payload = openapi.ProtoOAExecutionEvent()
                exec_payload.ParseFromString(msg.payload)
                _handle_unsolicited_execution_event(exec_payload)
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


def ensure_signals_columns():
    """
    Startup migration: ensure sl_price and tp_price columns exist in signals table.
    Safe to run on every startup — uses ADD COLUMN IF NOT EXISTS.
    Also ensures position_id column exists (added in v4.7).
    """
    try:
        conn = psycopg2.connect(
            host=os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
            database=os.getenv("CLOUD_SQL_DB_NAME", "tekton-trader"),
            user=os.getenv("CLOUD_SQL_DB_USER", "postgres"),
            password=os.getenv("CLOUD_SQL_DB_PASSWORD")
        )
        cur = conn.cursor()
        migrations = [
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS sl_price DOUBLE PRECISION",
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS tp_price DOUBLE PRECISION",
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS position_id BIGINT",
            "ALTER TABLE signals ADD COLUMN IF NOT EXISTS avg_fill_price DOUBLE PRECISION",
        ]
        for sql in migrations:
            cur.execute(sql)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ ensure_signals_columns: migrations applied (sl_price, tp_price, position_id, avg_fill_price)")
    except Exception as e:
        print(f"⚠️ ensure_signals_columns error (non-fatal): {e}")

if __name__ == "__main__":
    ensure_signals_columns()  # Safe column migrations on every startup
    reactor.callWhenRunning(bridge.start)
    reactor.callLater(3600, periodic_cleanup)
    resource = WSGIResource(reactor, reactor.getThreadPool(), app)
    site = Site(resource)
    reactor.listenTCP(BRIDGE_PORT, site, interface=BRIDGE_HOST)
    print(f"🚀 Bridge v4.5 - MERGED: HOME + PROJECT with all fixes")
    print(f"   ✅ Tracks: positions, account, execute, modify, close, deals, historical")
    print(f"   ❌ Skips: contract/specs (cache), prices/current (spot subscription)")
    print(f"   API stats: /stats/api-usage")
    task.LoopingCall(sync_to_cloud_sql).start(60.0)
    reactor.callLater(10, internal_sync_account)
    threading.Thread(target=sync_latest_candles, daemon=True).start()
    reactor.callLater(5, lambda: threading.Thread(target=seed_position_state_from_db, daemon=True).start())
    # Phase 11c: seed position_state{} from live ReconcileReq after auth completes (~8s).
    # Runs after DB seed so DB values are the base, live data overwrites with latest.
    reactor.callLater(20, lambda: threading.Thread(target=seed_position_state_from_live_reconcile, daemon=True).start())
    reactor.run()


