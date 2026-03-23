import time
import sys
import requests
import os
from dotenv import load_dotenv

load_dotenv()

# Redirect stdout/stderr to combined log
sys.stdout = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stderr = sys.stdout

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------
BRIDGE_URL = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY = os.getenv("BRIDGE_KEY")
HEADERS    = {"X-Bridge-Key": BRIDGE_KEY}


# ---------------------------------------------------------------------------
# SETTINGS  —  single source of truth: /data/system-settings
# ---------------------------------------------------------------------------
def fetch_config():
    """Fetches runtime config from the bridge."""
    res = requests.get(f"{BRIDGE_URL}/data/system-settings", headers=HEADERS, timeout=10)
    res.raise_for_status()
    return res.json()


# ---------------------------------------------------------------------------
# CIRCUIT BREAKER
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# PIP SIZE  —  always from bridge, never hardcoded
# ---------------------------------------------------------------------------
def get_pip_size(symbol):
    """
    Returns pip size from live bridge pipPosition.
    Formula: pip_size = 10^-pipPosition  (consistent with executor and strategy)
    """
    try:
        spec_res = requests.post(
            f"{BRIDGE_URL}/contract/specs",
            json={"symbol": symbol},
            headers=HEADERS,
            timeout=10
        )
        spec    = spec_res.json().get("contract_specifications", {})
        pip_pos = spec.get("pipPosition", 4)
        return 10 ** (-pip_pos)
    except Exception as e:
        print(f"⚠️ get_pip_size error for {symbol}: {e} — using default 0.0001")
        return 0.0001


# ---------------------------------------------------------------------------
# RISK MANAGER  —  monitors positions and closes at target R
# ---------------------------------------------------------------------------
def manage_risk(config):
    """
    Monitors open positions and closes any that have reached the Target Reward (R).
    Target R is read from bridge config (e.g. 1.5 = close at 1.5R).
    Prices are normalised from raw cTrader integers using pipPosition.
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

        # Safety check — positions with no SL are unprotected, log loudly and skip
        tp = pos.get("take_profit", 0)
        if not sl or sl == 0:
            print(f"🚨 NO SL ON OPEN POSITION: {symbol} pos_id={pos_id} entry={entry} — UNPROTECTED, skipping AI management")
            continue
        if not tp or tp == 0:
            print(f"⚠️ NO TP ON OPEN POSITION: {symbol} pos_id={pos_id} — position has no take profit set")
            # Don't skip — still manage SL and R tracking
        if not all([pos_id, entry, sl, current]):
            continue

        # Normalise raw cTrader integer prices → real prices using pipPosition
        # pip_size = 10^-pipPosition, price_scale = 10^pipPosition
        pip_size    = get_pip_size(symbol)
        price_scale = int(round(1 / pip_size))  # e.g. pip_size=0.0001 → scale=10000... wait, use 10^pipPosition directly

        # Safer: fetch pipPosition directly
        try:
            spec_res = requests.post(
                f"{BRIDGE_URL}/contract/specs",
                json={"symbol": symbol},
                headers=HEADERS,
                timeout=10
            )
            pip_pos     = spec_res.json().get("contract_specifications", {}).get("pipPosition", 4)
            price_scale = 10 ** pip_pos
        except Exception:
            price_scale = 100000  # safe default

        def norm(p):
            return p / price_scale if p > 1000 else p

        entry   = norm(entry)
        sl      = norm(sl)
        current = norm(current)

        risk_distance = abs(entry - sl)
        if risk_distance == 0:
            continue

        reward_distance = (current - entry) if side == "BUY" else (entry - current)
        current_r       = reward_distance / risk_distance

        if current_r >= target_r:
            print(f"🎯 {symbol} [{pos_id}] hit {current_r:.2f}R ≥ {target_r}R — closing position.")
            close_res  = requests.post(
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


# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------
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
        time.sleep(15)
