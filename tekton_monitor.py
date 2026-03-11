import time, requests, os, base64, json, sys
from dotenv import load_dotenv

load_dotenv()

# --- LOGGING CONFIGURATION ---
sys.stdout = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stderr = sys.stdout

# --- CONFIGURATION ---
BACKEND_FUNC_URL = "https://tekton-trade-hub.base44.app/api/functions/getBase64Config"
BRIDGE_URL = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY = os.getenv("BRIDGE_KEY")

BASE44_HEADERS = {
    "Content-Type": "application/json",
    "api_key": "3636548f91ad4225bf0d8bfbc13b0eeb"
}
BRIDGE_HEADERS = {"X-Bridge-Key": BRIDGE_KEY}

def fetch_base64_config():
    """Fetches and decodes the Base64 configuration. No fallbacks."""
    response = requests.post(BACKEND_FUNC_URL, json={}, headers=BASE44_HEADERS, timeout=10)
    response.raise_for_status()
    data = response.json()
    encoded_str = data.get("config")
    
    if not encoded_str:
        raise ValueError("Base44 returned an empty 'config' field.")

    decoded_json = base64.b64decode(encoded_str).decode('utf-8')
    config = json.loads(decoded_json)
    # Debug print remains to confirm live updates
    print(f"DEBUG: Raw config from Base44: {config}")
    return config

def check_circuit_breaker():
    """Checks drawdown using UPPERCASE keys from Base44."""
    try:
        config = fetch_base64_config()
        # FIXED: Using UPPERCASE key to match your specific Base44 output
        max_dd_raw = config.get("DAILY_DRAWDOWN_LIMIT")
        
        if max_dd_raw is None:
            raise KeyError("Field 'DAILY_DRAWDOWN_LIMIT' missing from response.")
            
        max_dd = float(max_dd_raw) * 100
        
        # Verify Bridge status
        res_raw = requests.get(f"{BRIDGE_URL}/account/status", headers=BRIDGE_HEADERS)
        res_raw.raise_for_status()
        res = res_raw.json()
        
        current_dd = float(res.get("drawdown_pct", 0))
        if current_dd >= max_dd:
            print(f"🚨 CIRCUIT BREAKER: {current_dd}% drawdown exceeds {max_dd}% limit!")
            return True
        return False
    except Exception as e:
        print(f"❌ MONITOR HALTED: {e}")
        return True

def manage_risk():
    """Manages active positions using UPPERCASE keys."""
    try:
        config = fetch_base64_config()
        # FIXED: Using UPPERCASE key
        target_r = float(config.get("TARGET_REWARD", 1.5))

        # FIXED: Added error handling for empty Bridge response
        res_raw = requests.get(f"{BRIDGE_URL}/positions/list", headers=BRIDGE_HEADERS)
        if not res_raw.text.strip():
            print("⚠️ Bridge returned empty response for positions/list")
            return

        positions = res_raw.json().get("positions", [])
        if positions:
            print(f"🛡️ Monitoring {len(positions)} positions for {target_r}R")
            
    except Exception as e:
        print(f"⚠️ Risk Management Error: {e}")

if __name__ == "__main__":
    print("🛡️ Tekton Monitor Engine Active.")
    while True:
        print(f"⏱️ Heartbeat: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        if not check_circuit_breaker():
            manage_risk()
        time.sleep(15)
import time
import sys
import requests
import os
import base64
import json
from dotenv import load_dotenv

load_dotenv()

# Redirect AFTER imports
sys.stdout = open('/home/tony/tekton-ai-trader/combined_trades.log', 'a', buffering=1)
sys.stderr = sys.stdout

# --- CONFIGURATION ---
BACKEND_FUNC_URL = "https://tekton-trade-hub.base44.app/api/functions/getBase64Config"
BRIDGE_URL       = os.getenv("BRIDGE_URL", "http://localhost:8080")
BRIDGE_KEY       = os.getenv("BRIDGE_KEY")

BASE44_HEADERS  = {"Content-Type": "application/json", "api_key": "3636548f91ad4225bf0d8bfbc13b0eeb"}
BRIDGE_HEADERS  = {"X-Bridge-Key": BRIDGE_KEY}


# ---------------------------------------------------------------------------
def fetch_base64_config():
    """Fetches and decodes the Base64 configuration."""
    response = requests.post(BACKEND_FUNC_URL, json={}, headers=BASE44_HEADERS, timeout=10)
    response.raise_for_status()
    data        = response.json()
    encoded_str = data.get("config")
    if not encoded_str:
        raise ValueError("Base44 returned an empty 'config' field.")
    return json.loads(base64.b64decode(encoded_str).decode("utf-8"))


# ---------------------------------------------------------------------------
def check_circuit_breaker(config):
    """Returns True if drawdown limit is breached (halt trading)."""
    max_dd_raw = config.get("DAILY_DRAWDOWN_LIMIT")
    if max_dd_raw is None:
        raise KeyError("Field 'DAILY_DRAWDOWN_LIMIT' missing from Base44 config.")

    max_dd = float(max_dd_raw) * 100  # e.g. 0.05 → 5.0%

    res = requests.get(f"{BRIDGE_URL}/account/status", headers=BRIDGE_HEADERS, timeout=10)
    res.raise_for_status()
    current_dd = float(res.json().get("drawdown_pct", 0))

    if current_dd >= max_dd:
        print(f"🚨 CIRCUIT BREAKER: {current_dd:.2f}% drawdown exceeds {max_dd:.2f}% limit! Halting.")
        return True
    return False


# ---------------------------------------------------------------------------
def manage_risk(config):
    """
    Monitors open positions and closes any that have reached the Target Reward (R).
    Target R is read from Base44 config (e.g. TARGET_REWARD = 1.5 means 1.5R).
    """
    target_r = float(config.get("TARGET_REWARD", 1.5))

    res = requests.get(f"{BRIDGE_URL}/positions/list", headers=BRIDGE_HEADERS, timeout=10)
    if not res.text.strip():
        print("⚠️ Bridge returned empty response for positions/list")
        return

    positions = res.json().get("positions", [])
    if not positions:
        return

    print(f"🛡️ Monitoring {len(positions)} positions | Target: {target_r}R")

    for pos in positions:
        pos_id     = pos.get("position_id") or pos.get("id")
        symbol     = pos.get("symbol", "?")
        side       = pos.get("side", "").upper()
        entry      = pos.get("entry_price", 0)
        sl         = pos.get("stop_loss", 0)
        current    = pos.get("current_price", 0)
        digits     = pos.get("digits", 5)

        if not all([pos_id, entry, sl, current]):
            continue

        # Normalise raw integer prices if needed (divide by 10^digits)
        def norm(p):
            return p / (10 ** digits) if p > 1000 else p

        entry   = norm(entry)
        sl      = norm(sl)
        current = norm(current)

        risk_distance = abs(entry - sl)
        if risk_distance == 0:
            continue

        if side == "BUY":
            reward_distance = current - entry
        else:
            reward_distance = entry - current

        current_r = reward_distance / risk_distance

        if current_r >= target_r:
            print(f"🎯 {symbol} [{pos_id}] hit {current_r:.2f}R ≥ {target_r}R — closing position.")
            close_res = requests.post(
                f"{BRIDGE_URL}/trade/close",
                json={"position_id": pos_id},
                headers=BRIDGE_HEADERS,
                timeout=10
            )
            close_data = close_res.json()
            if close_data.get("success"):
                print(f"✅ Closed {symbol} [{pos_id}] at {target_r}R target.")
            else:
                print(f"⚠️ Close failed for {symbol} [{pos_id}]: {close_data.get('error')}")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"🛡️ Tekton Monitor Engine Active. [{time.strftime('%Y-%m-%d %H:%M:%S')}]")
    while True:
        print(f"⏱️ Heartbeat: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            config = fetch_base64_config()
            if not check_circuit_breaker(config):
                manage_risk(config)
        except Exception as e:
            print(f"❌ MONITOR ERROR: {e}")
        time.sleep(15)
