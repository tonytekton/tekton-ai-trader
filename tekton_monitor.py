import time
import sys
import requests
import os
import psycopg2
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# Redirect stdout/stderr to combined log
sys.stdout = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stderr = sys.stdout

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
BRIDGE_URL   = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY   = os.getenv("BRIDGE_KEY")
HEADERS      = {"X-Bridge-Key": BRIDGE_KEY}

BASE44_SERVICE_TOKEN = os.getenv("BASE44_SERVICE_TOKEN", "")
BASE44_HEADERS       = {"Authorization": f"Bearer {BASE44_SERVICE_TOKEN}"}
BASE44_FUNCTIONS_URL = "https://lester-fd0cd5bc.base44.app/functions"

DB_PARAMS = {
    "host":     os.getenv("CLOUD_SQL_HOST", "172.16.64.3"),
    "database": "tekton-trader",
    "user":     "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD"),
}

# ---------------------------------------------------------------------------
# STATE  —  circuit breaker latch so we only trigger autopsy once per breach
# ---------------------------------------------------------------------------
_circuit_broken    = False
_autopsy_triggered = False


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def _ts():
    return datetime.now().strftime("%H:%M:%S")

def get_pip_size(symbol):
    """Returns (pip_size, price_scale) from live bridge pipPosition."""
    try:
        spec_res = requests.post(
            f"{BRIDGE_URL}/contract/specs",
            json={"symbol": symbol},
            headers=HEADERS,
            timeout=10
        )
        spec        = spec_res.json().get("contract_specifications", {})
        pip_pos     = spec.get("pipPosition", 4)
        pip_size    = 10 ** (-pip_pos)
        price_scale = 10 ** pip_pos
        return pip_size, price_scale
    except Exception as e:
        print(f"[{_ts()}] ⚠️ get_pip_size error for {symbol}: {e} — using defaults")
        return 0.0001, 100000

def norm_price(p, price_scale):
    """Normalise raw cTrader integer price to real price."""
    return p / price_scale if p > 1000 else p

def get_recent_candles(symbol, count=20):
    """Fetch recent candles for a symbol from the bridge."""
    try:
        res = requests.post(
            f"{BRIDGE_URL}/candles",
            json={"symbol": symbol, "timeframe": "M15", "count": count},
            headers=HEADERS,
            timeout=10
        )
        return res.json().get("candles", [])
    except Exception:
        return []

def get_signal_for_position(pos_id, symbol):
    """Look up the most recent signal for this symbol in EXECUTING/COMPLETED state."""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur  = conn.cursor()
        cur.execute("""
            SELECT strategy, signal_type, sl_pips, tp_pips, created_at
            FROM signals
            WHERE status IN ('EXECUTING', 'COMPLETED')
              AND symbol = %s
            ORDER BY created_at DESC
            LIMIT 1;
        """, (symbol,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {
                "strategy":   row[0],
                "direction":  row[1],
                "sl_pips":    float(row[2]) if row[2] else None,
                "tp_pips":    float(row[3]) if row[3] else None,
                "created_at": row[4],
            }
    except Exception as e:
        print(f"[{_ts()}] ⚠️ get_signal_for_position error: {e}")
    return {}

def get_recent_signals(limit=50):
    """Fetch recent signals from DB for autopsy context."""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur  = conn.cursor()
        cur.execute("""
            SELECT symbol, signal_type, strategy, status, confidence_score,
                   sl_pips, tp_pips, created_at
            FROM signals
            ORDER BY created_at DESC
            LIMIT %s;
        """, (limit,))
        cols = ["symbol","direction","strategy","status","confidence",
                "sl_pips","tp_pips","created_at"]
        rows = [dict(zip(cols, [str(v) for v in row])) for row in cur.fetchall()]
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        print(f"[{_ts()}] ⚠️ get_recent_signals error: {e}")
        return []

def get_recent_interventions(limit=20):
    """Fetch recent AI interventions from Base44 for autopsy context."""
    try:
        res = requests.get(
            "https://lester-fd0cd5bc.base44.app/api/entities/AiIntervention",
            params={"limit": limit, "sort": "-created_date"},
            headers=BASE44_HEADERS,
            timeout=10
        )
        return res.json().get("items", [])
    except Exception:
        return []

def update_intervention_outcome(intervention_id, outcome, outcome_r):
    """Update a logged AI intervention with its final outcome."""
    try:
        requests.patch(
            f"https://lester-fd0cd5bc.base44.app/api/entities/AiIntervention/{intervention_id}",
            json={"outcome": outcome, "outcome_r": outcome_r, "executed": True},
            headers=BASE44_HEADERS,
            timeout=10
        )
    except Exception as e:
        print(f"[{_ts()}] ⚠️ update_intervention_outcome error: {e}")

def close_all_positions():
    """Emergency close all open positions before freeze."""
    try:
        res       = requests.get(f"{BRIDGE_URL}/positions/list", headers=HEADERS, timeout=10)
        positions = res.json().get("positions", [])
        for pos in positions:
            pos_id = pos.get("position_id") or pos.get("id")
            symbol = pos.get("symbol", "?")
            close_res = requests.post(
                f"{BRIDGE_URL}/trade/close",
                json={"position_id": pos_id},
                headers=HEADERS,
                timeout=10
            )
            if close_res.json().get("success"):
                print(f"[{_ts()}] 🔴 Emergency closed {symbol} [{pos_id}]")
            else:
                print(f"[{_ts()}] ⚠️ Emergency close failed for {symbol} [{pos_id}]")
        return positions
    except Exception as e:
        print(f"[{_ts()}] ❌ close_all_positions error: {e}")
        return []


# ---------------------------------------------------------------------------
# SETTINGS  —  single source of truth: bridge /data/system-settings
# ---------------------------------------------------------------------------
def fetch_config():
    res = requests.get(f"{BRIDGE_URL}/data/system-settings", headers=HEADERS, timeout=10)
    res.raise_for_status()
    return res.json()


# ---------------------------------------------------------------------------
# CIRCUIT BREAKER  —  triggers autopsy, freezes trading
# ---------------------------------------------------------------------------
def check_circuit_breaker(config):
    """
    Returns True if daily drawdown limit is breached.
    On first breach: closes all positions, triggers AI autopsy, latches state.
    Trading stays frozen until autopsy status is set to APPROVED_RESUME via UI.
    """
    global _circuit_broken, _autopsy_triggered

    # If already broken, stay frozen until manually approved
    if _circuit_broken:
        print(f"[{_ts()}] 🔒 Trading frozen — awaiting autopsy review and approval to resume.")
        return True

    max_dd_raw = config.get("daily_drawdown_limit")
    if max_dd_raw is None:
        raise KeyError("Field 'daily_drawdown_limit' missing from bridge config.")

    max_dd = float(max_dd_raw) * 100  # e.g. 0.05 → 5.0%

    acct_res   = requests.get(f"{BRIDGE_URL}/account/status", headers=HEADERS, timeout=10)
    acct_data  = acct_res.json()
    current_dd = float(acct_data.get("drawdown_pct", 0))

    if current_dd < max_dd:
        return False

    # ── BREACH ──────────────────────────────────────────────────────────────
    _circuit_broken = True
    print(f"[{_ts()}] 🚨 CIRCUIT BREAKER FIRED: {current_dd:.2f}% ≥ {max_dd:.2f}% limit.")
    print(f"[{_ts()}] 🔴 Closing all open positions...")

    open_positions = close_all_positions()

    if not _autopsy_triggered:
        _autopsy_triggered = True
        print(f"[{_ts()}] 🔬 Triggering AI drawdown autopsy...")

        try:
            autopsy_res = requests.post(
                f"{BASE44_FUNCTIONS_URL}/drawdownAutopsy",
                json={
                    "drawdown_pct":        current_dd,
                    "drawdown_limit_pct":  max_dd,
                    "account_balance":     acct_data.get("balance"),
                    "account_equity":      acct_data.get("equity"),
                    "open_positions":      open_positions,
                    "recent_signals":      get_recent_signals(50),
                    "recent_interventions": get_recent_interventions(20),
                },
                headers=BASE44_HEADERS,
                timeout=60
            )
            data = autopsy_res.json()
            if data.get("ok"):
                print(f"[{_ts()}] ✅ Autopsy report created: {data.get('autopsy_id')}")
                print(f"[{_ts()}] 📋 Root causes: {data.get('summary','')[:200]}")
            else:
                print(f"[{_ts()}] ⚠️ Autopsy function error: {data.get('error')}")
        except Exception as e:
            print(f"[{_ts()}] ❌ Autopsy request failed: {e}")

    return True


# ---------------------------------------------------------------------------
# AI POSITION REVIEW  —  calls Lester for each open position
# ---------------------------------------------------------------------------
def ai_review_position(pos, signal_info, pip_size, price_scale, minutes_open):
    """
    Sends position context to the AI review backend function.
    Returns the AI decision dict or None on error.
    """
    entry   = norm_price(pos.get("entry_price", 0), price_scale)
    sl      = norm_price(pos.get("stop_loss", 0),   price_scale)
    tp      = norm_price(pos.get("take_profit", 0), price_scale)
    current = norm_price(pos.get("current_price", 0), price_scale)
    side    = pos.get("side", "").upper()
    symbol  = pos.get("symbol", "?")

    risk_dist = abs(entry - sl)
    if risk_dist == 0:
        return None

    reward_dist = (current - entry) if side == "BUY" else (entry - current)
    current_r   = reward_dist / risk_dist

    recent_candles = get_recent_candles(symbol)

    payload = {
        "position_id":    pos.get("position_id") or pos.get("id"),
        "symbol":         symbol,
        "strategy":       signal_info.get("strategy", "unknown"),
        "direction":      signal_info.get("direction", side),
        "entry_price":    entry,
        "current_price":  current,
        "sl_price":       sl,
        "tp_price":       tp,
        "current_r":      current_r,
        "minutes_open":   minutes_open,
        "recent_candles": recent_candles,
        "pip_size":       pip_size,
    }

    try:
        res = requests.post(
            f"{BASE44_FUNCTIONS_URL}/aiPositionReview",
            json=payload,
            headers=BASE44_HEADERS,
            timeout=30
        )
        data = res.json()
        if data.get("ok"):
            decision                 = data.get("decision", {})
            decision["_intervention_id"] = data.get("intervention_id")
            decision["_current_r"]       = current_r
            return decision
        else:
            print(f"[{_ts()}] ⚠️ AI review error for {symbol}: {data.get('error')}")
    except Exception as e:
        print(f"[{_ts()}] ⚠️ AI review request failed for {symbol}: {e}")

    return None


# ---------------------------------------------------------------------------
# EXECUTE AI DECISION
# ---------------------------------------------------------------------------
def execute_decision(pos, decision, pip_size, price_scale):
    """Acts on the AI decision — modify SL/TP or close position."""
    pos_id = pos.get("position_id") or pos.get("id")
    symbol = pos.get("symbol", "?")
    action = decision.get("action", "HOLD")
    iid    = decision.get("_intervention_id")
    curr_r = decision.get("_current_r", 0)

    if action == "HOLD":
        print(f"[{_ts()}] 🤖 {symbol} [{pos_id}] HOLD | {curr_r:.2f}R | {decision.get('reasoning','')[:80]}")
        return

    print(f"[{_ts()}] 🤖 {symbol} [{pos_id}] {action} | {curr_r:.2f}R | {decision.get('reasoning','')[:80]}")

    if action == "CLOSE":
        res  = requests.post(
            f"{BRIDGE_URL}/trade/close",
            json={"position_id": pos_id},
            headers=HEADERS,
            timeout=10
        )
        data = res.json()
        if data.get("success"):
            print(f"[{_ts()}] ✅ AI closed {symbol} [{pos_id}]")
            outcome = "WIN" if curr_r > 0 else "LOSS" if curr_r < -0.1 else "BREAKEVEN"
            if iid:
                update_intervention_outcome(iid, outcome, curr_r)
        else:
            print(f"[{_ts()}] ⚠️ AI close failed for {symbol}: {data.get('error')}")

    elif action == "ADJUST_SL" and decision.get("new_sl"):
        new_sl_raw = int(decision["new_sl"] * price_scale)
        res  = requests.post(
            f"{BRIDGE_URL}/trade/modify",
            json={"position_id": pos_id, "stop_loss": new_sl_raw},
            headers=HEADERS,
            timeout=10
        )
        data = res.json()
        if data.get("success"):
            print(f"[{_ts()}] ✅ AI adjusted SL for {symbol} → {decision['new_sl']}")
        else:
            print(f"[{_ts()}] ⚠️ AI SL adjust failed for {symbol}: {data.get('error')}")

    elif action == "ADJUST_TP" and decision.get("new_tp"):
        new_tp_raw = int(decision["new_tp"] * price_scale)
        res  = requests.post(
            f"{BRIDGE_URL}/trade/modify",
            json={"position_id": pos_id, "take_profit": new_tp_raw},
            headers=HEADERS,
            timeout=10
        )
        data = res.json()
        if data.get("success"):
            print(f"[{_ts()}] ✅ AI adjusted TP for {symbol} → {decision['new_tp']}")
        else:
            print(f"[{_ts()}] ⚠️ AI TP adjust failed for {symbol}: {data.get('error')}")

    elif action == "PARTIAL_CLOSE":
        # Partial close not yet supported by bridge — log intent, hold for now
        print(f"[{_ts()}] ⏳ PARTIAL_CLOSE not yet supported by bridge — holding {symbol}")


# ---------------------------------------------------------------------------
# MAIN RISK MANAGER  —  AI-driven, no hard trade rules
# ---------------------------------------------------------------------------
def manage_risk(config):
    res = requests.get(f"{BRIDGE_URL}/positions/list", headers=HEADERS, timeout=10)
    if not res.text.strip():
        print(f"[{_ts()}] ⚠️ Empty response from positions/list")
        return

    positions = res.json().get("positions", [])
    if not positions:
        return

    print(f"[{_ts()}] 🛡️ Reviewing {len(positions)} open positions with AI")

    for pos in positions:
        pos_id = pos.get("position_id") or pos.get("id")
        symbol = pos.get("symbol", "?")

        pip_size, price_scale = get_pip_size(symbol)
        signal_info = get_signal_for_position(pos_id, symbol)

        # Calculate minutes open
        minutes_open = 0
        opened_at    = pos.get("opened_at") or pos.get("open_time")
        if opened_at:
            try:
                opened_dt    = datetime.fromisoformat(str(opened_at).replace("Z", "+00:00"))
                minutes_open = (datetime.now(timezone.utc) - opened_dt).seconds // 60
            except Exception:
                pass

        decision = ai_review_position(pos, signal_info, pip_size, price_scale, minutes_open)
        if decision:
            execute_decision(pos, decision, pip_size, price_scale)


# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"[{_ts()}] 🛡️ Tekton AI Monitor Engine Active. [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    while True:
        print(f"[{_ts()}] ⏱️ Heartbeat")
        try:
            config = fetch_config()
            if not check_circuit_breaker(config):
                manage_risk(config)
        except Exception as e:
            print(f"[{_ts()}] ❌ MONITOR ERROR: {e}")
        time.sleep(60)
