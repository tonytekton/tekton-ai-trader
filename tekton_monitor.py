import time
import sys
import requests
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Redirect stdout/stderr to combined log
sys.stdout = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stderr = sys.stdout

# --- CONFIGURATION ---
BRIDGE_URL  = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY  = os.getenv("BRIDGE_KEY")
HEADERS     = {"X-Bridge-Key": BRIDGE_KEY}

DB_PARAMS = {
    "host":     "172.16.64.3",
    "database": "tekton-trader",
    "user":     "postgres",
    "password": os.getenv("CLOUD_SQL_DB_PASSWORD")
}

# Orphan check runs every N monitor loops (every 15s * 20 = every 5 minutes)
ORPHAN_CHECK_INTERVAL = 20
_orphan_loop_counter  = 0


def fetch_config():
    """Fetches runtime config directly from the bridge's /data/system-settings endpoint."""
    res = requests.get(f"{BRIDGE_URL}/data/system-settings", headers=HEADERS, timeout=10)
    res.raise_for_status()
    return res.json()


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


def manage_risk(config):
    """
    Monitors open positions and closes any that have reached the Target Reward (R).
    Target R is read from bridge config (target_reward, e.g. 1.5 = close at 1.5R).
    Prices are normalised from raw cTrader integers using digits field.
    """
    target_r = float(config.get("target_reward", 1.5))

    res = requests.get(f"{BRIDGE_URL}/positions/list", headers=HEADERS, timeout=10)
    if not res.text.strip():
        print("⚠️ Bridge returned empty response for positions/list")
        return

    positions = res.json().get("positions", [])
    if not positions:
        return

    print(f"🛡️ Monitoring {len(positions)} positions | Target: {target_r}R")

    for pos in positions:
        pos_id  = pos.get("position_id") or pos.get("id")
        symbol  = pos.get("symbol", "?")
        side    = pos.get("side", "").upper()
        entry   = pos.get("entry_price", 0)
        sl      = pos.get("stop_loss", 0)
        current = pos.get("current_price", 0)
        digits  = pos.get("digits", 5)

        if not all([pos_id, entry, sl, current]):
            continue

        # Normalise raw cTrader integer prices → real prices
        def norm(p):
            return p / (10 ** digits) if p > 1000 else p

        entry   = norm(entry)
        sl      = norm(sl)
        current = norm(current)

        risk_distance = abs(entry - sl)
        if risk_distance == 0:
            continue

        reward_distance = (current - entry) if side == "BUY" else (entry - current)
        current_r = reward_distance / risk_distance

        if current_r >= target_r:
            print(f"🎯 {symbol} [{pos_id}] hit {current_r:.2f}R ≥ {target_r}R — closing position.")
            close_res = requests.post(
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


def check_orphans():
    """
    Compares open positions on cTrader against the executions table in the DB.
    Any position with no matching executions row is an orphan — not opened by this system.
    Orphans are inserted into executions with signal_uuid=NULL and status='ORPHAN'.
    Already-flagged orphans are skipped (ON CONFLICT DO NOTHING).
    """
    conn, cur = None, None
    try:
        # Fetch all open positions from bridge
        res = requests.get(f"{BRIDGE_URL}/positions/list", headers=HEADERS, timeout=10)
        if not res.text.strip():
            return
        positions = res.json().get("positions", [])
        if not positions:
            return

        conn = psycopg2.connect(**DB_PARAMS)
        cur  = conn.cursor()

        # Fetch all known position IDs from executions table
        cur.execute("SELECT position_id FROM executions;")
        known_ids = {row[0] for row in cur.fetchall()}

        orphans_found = 0
        for pos in positions:
            pos_id = pos.get("position_id") or pos.get("id")
            if not pos_id:
                continue

            if int(pos_id) not in known_ids:
                # Unknown position — flag as ORPHAN
                symbol = pos.get("symbol", "UNKNOWN")
                print(f"🚨 ORPHAN DETECTED: {symbol} | Position ID: {pos_id} — not in executions table. Flagging.")
                cur.execute("""
                    INSERT INTO executions (position_id, signal_uuid, symbol, status)
                    VALUES (%s, NULL, %s, 'ORPHAN')
                    ON CONFLICT (position_id) DO NOTHING;
                """, (int(pos_id), symbol))
                orphans_found += 1

        if orphans_found:
            conn.commit()
            print(f"⚠️ {orphans_found} orphan(s) flagged in executions table.")
        # No print if zero orphans — keeps log clean

    except Exception as e:
        print(f"❌ ORPHAN CHECK ERROR: {e}")
    finally:
        if cur:  cur.close()
        if conn: conn.close()


if __name__ == "__main__":
    print(f"🛡️ Tekton Monitor Engine Active. [{time.strftime('%Y-%m-%d %H:%M:%S')}]")
    while True:
        print(f"⏱️ Heartbeat: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            config = fetch_config()
            if not check_circuit_breaker(config):
                manage_risk(config)
        except Exception as e:
            print(f"❌ MONITOR ERROR: {e}")

        # Orphan check every 5 minutes (independent of circuit breaker state)
        _orphan_loop_counter += 1
        if _orphan_loop_counter >= ORPHAN_CHECK_INTERVAL:
            _orphan_loop_counter = 0
            try:
                check_orphans()
            except Exception as e:
                print(f"❌ ORPHAN CHECK ERROR: {e}")

        time.sleep(15)
