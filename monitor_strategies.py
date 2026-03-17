"""
monitor_strategies.py — Tekton Unified Strategy Monitor
========================================================
Watches all strategy log files in real-time, colour-codes output by strategy,
and prints a rolling summary every 60 seconds.

Features:
  - Live colour-coded log tailing (blue=FVG, green=EPS)
  - Per-strategy signal / cooldown / HTF block counters
  - Process watchdog: detects dead strategies and AUTO-RESTARTS them
  - 30-second cooldown between restart attempts (no restart loops)
  - Prints restart command used so you have a full audit trail

Usage:
  python3 monitor_strategies.py

Press Ctrl+C to exit.
"""

import os
import time
import subprocess
import re
from datetime import datetime

# ─── CONFIG ────────────────────────────────────────────────────────────────────

LOG_DIR = "/home/tony/tekton-ai-trader"

STRATEGIES = [
    {
        "name":    "FVG",
        "label":   "ICT FVG+MSS",
        "log":     os.path.join(LOG_DIR, "strategy.log"),
        "process": "strat_ict_fvg_v1.py",
        "script":  os.path.join(LOG_DIR, "strat_ict_fvg_v1.py"),
        "color":   "\033[94m",   # blue
    },
    {
        "name":    "EPS",
        "label":   "EMA Pullback",
        "log":     os.path.join(LOG_DIR, "strat_eps.log"),
        "process": "strat_ema_pullback_v1.py",
        "script":  os.path.join(LOG_DIR, "strat_ema_pullback_v1.py"),
        "color":   "\033[92m",   # green
    },
]

SUMMARY_INTERVAL      = 60    # seconds between summary prints
POLL_INTERVAL         = 0.3   # seconds between log polls
RESTART_COOLDOWN_SEC  = 30    # seconds to wait before retrying a restart

# ─── ANSI COLOURS ──────────────────────────────────────────────────────────────

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
CYAN    = "\033[96m"
WHITE   = "\033[97m"
GREEN   = "\033[92m"

# ─── STATE ─────────────────────────────────────────────────────────────────────

class StrategyState:
    def __init__(self, cfg):
        self.name         = cfg["name"]
        self.label        = cfg["label"]
        self.log_path     = cfg["log"]
        self.process      = cfg["process"]
        self.script       = cfg["script"]
        self.color        = cfg["color"]
        self.file_pos     = 0
        self.last_scan    = None
        self.last_line    = None
        # Rolling counters (reset each summary cycle)
        self.signals      = 0
        self.cooldowns    = 0
        self.htf_blocks   = 0
        self.no_setup     = 0
        self.errors       = 0
        # Session totals
        self.total_signals   = 0
        self.total_cooldowns = 0
        self.total_htf       = 0
        self.restart_count   = 0
        # Watchdog
        self.last_restart_attempt = 0   # epoch seconds
        self.recent_signals  = []       # last 10 signal strings

    def reset_cycle(self):
        self.signals    = 0
        self.cooldowns  = 0
        self.htf_blocks = 0
        self.no_setup   = 0
        self.errors     = 0


# ─── HELPERS ───────────────────────────────────────────────────────────────────

def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def is_process_alive(process_name: str) -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", process_name],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False

def restart_strategy(state: StrategyState):
    """
    Attempt to restart a dead strategy process.
    Uses a subprocess to launch it detached (equivalent of nohup ... &).
    Respects RESTART_COOLDOWN_SEC to prevent restart loops.
    """
    now = time.time()
    if now - state.last_restart_attempt < RESTART_COOLDOWN_SEC:
        return  # Still in cooldown — don't spam restarts

    state.last_restart_attempt = now

    log_path = state.log_path
    script   = state.script

    print(f"\n{RED}{BOLD}[{ts()}] ⚠️  {state.name} is DEAD — attempting auto-restart...{RESET}")

    try:
        # Open log file for append
        log_fd = open(log_path, "a")

        proc = subprocess.Popen(
            ["python3", "-u", script],
            stdout=log_fd,
            stderr=log_fd,
            start_new_session=True,   # detach from terminal (equivalent of nohup)
            cwd=LOG_DIR,
        )

        state.restart_count += 1
        print(f"{YELLOW}{BOLD}[{ts()}] 🔄 {state.name} restarted — PID {proc.pid} "
              f"(attempt #{state.restart_count}){RESET}\n")

    except Exception as e:
        print(f"{RED}[{ts()}] ❌ Failed to restart {state.name}: {e}{RESET}\n")


def seek_to_end(state: StrategyState):
    if os.path.exists(state.log_path):
        state.file_pos = os.path.getsize(state.log_path)

def read_new_lines(state: StrategyState) -> list:
    if not os.path.exists(state.log_path):
        return []
    try:
        size = os.path.getsize(state.log_path)
        if size < state.file_pos:
            state.file_pos = 0   # log was truncated/rotated
        if size == state.file_pos:
            return []
        with open(state.log_path, "r", errors="replace") as f:
            f.seek(state.file_pos)
            new_content = f.read()
            state.file_pos = f.tell()
        return [l for l in new_content.split("\n") if l.strip()]
    except Exception:
        return []

def parse_line(line: str, state: StrategyState):
    if "Scan started" in line or "scan started" in line:
        state.last_scan = datetime.now()
    elif "📡 SIGNAL:" in line:
        state.signals        += 1
        state.total_signals  += 1
        state.recent_signals.append(f"[{ts()}] {line.strip()}")
        if len(state.recent_signals) > 10:
            state.recent_signals.pop(0)
    elif "⏳ COOLDOWN:" in line:
        state.cooldowns       += 1
        state.total_cooldowns += 1
    elif "🚫 HTF BLOCK:" in line or "🚫 HTF block:" in line:
        state.htf_blocks += 1
        state.total_htf  += 1
    elif "Scan done" in line:
        m = re.search(r"no_setup=(\d+)", line)
        if m:
            state.no_setup += int(m.group(1))
    elif "💥" in line or "❌" in line:
        state.errors += 1
    state.last_line = line.strip()

def print_line(line: str, state: StrategyState):
    prefix = f"{state.color}{BOLD}[{state.name}]{RESET} "
    if "📡 SIGNAL:" in line:
        print(f"{prefix}{state.color}{BOLD}{line}{RESET}")
    elif "💥" in line or "❌" in line:
        print(f"{prefix}{RED}{line}{RESET}")
    elif "⏳ COOLDOWN" in line or "🚫 HTF" in line:
        print(f"{prefix}{DIM}{line}{RESET}")
    elif "Scan done" in line or "scan done" in line:
        print(f"{prefix}{CYAN}{line}{RESET}")
    elif "🚀" in line or "🔄" in line:
        print(f"{prefix}{YELLOW}{line}{RESET}")
    else:
        print(f"{prefix}{line}")

def print_summary(states: list):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    width   = 72

    print(f"\n{BOLD}{CYAN}{'─' * width}{RESET}")
    print(f"{BOLD}{CYAN}  📊 STRATEGY SUMMARY  {DIM}{now_str}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}")

    for s in states:
        alive     = is_process_alive(s.process)
        status    = f"{BOLD}{GREEN}● RUNNING{RESET}" if alive else f"{BOLD}{RED}● DEAD{RESET}"
        last_scan = s.last_scan.strftime("%H:%M:%S") if s.last_scan else "never"
        restarts  = f"  {YELLOW}(restarted {s.restart_count}×){RESET}" if s.restart_count > 0 else ""

        print(f"  {s.color}{BOLD}{s.label:<20}{RESET}  {status}  {DIM}last scan: {last_scan}{RESET}{restarts}")
        print(f"    {'Signals:':<14} {BOLD}{WHITE}{s.total_signals:>4}{RESET}  (this cycle: {s.signals})")
        print(f"    {'HTF Blocks:':<14} {s.total_htf:>4}    Cooldowns: {s.total_cooldowns}")
        print()

    # Recent signals (last 5 across all strategies)
    all_recent = []
    for s in states:
        all_recent.extend([(sig, s) for sig in s.recent_signals])

    if all_recent:
        print(f"  {BOLD}Recent Signals:{RESET}")
        for sig, s in all_recent[-5:]:
            clean = re.sub(r"^\[[\d:]+\] ", "", sig)
            clean = re.sub(r"📡 SIGNAL: ", "", clean)
            print(f"    {s.color}▶{RESET} {clean}")
        print()

    print(f"{BOLD}{CYAN}{'─' * width}{RESET}\n")

    for s in states:
        s.reset_cycle()


# ─── WATCHDOG ──────────────────────────────────────────────────────────────────

def check_and_restart(states: list):
    """Called every poll cycle. Restarts any dead strategy process."""
    for s in states:
        if not is_process_alive(s.process):
            restart_strategy(s)


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    states = [StrategyState(cfg) for cfg in STRATEGIES]

    print(f"\n{BOLD}{YELLOW}🎩 Tekton Unified Strategy Monitor{RESET}")
    print(f"{DIM}Watching {len(states)} strategies | "
          f"Summary every {SUMMARY_INTERVAL}s | "
          f"Auto-restart ON (cooldown {RESTART_COOLDOWN_SEC}s) | "
          f"Ctrl+C to exit{RESET}\n")

    for s in states:
        seek_to_end(s)
        alive  = is_process_alive(s.process)
        status = f"{BOLD}{GREEN}RUNNING{RESET}" if alive else f"{RED}NOT RUNNING{RESET}"
        print(f"  {s.color}{BOLD}{s.label}{RESET} — {status}  {DIM}({s.log_path}){RESET}")

    print()

    last_summary  = time.time()
    last_watchdog = time.time()

    try:
        while True:
            # Tail logs
            for s in states:
                new_lines = read_new_lines(s)
                for line in new_lines:
                    parse_line(line, s)
                    print_line(line, s)

            # Watchdog: check every 15 seconds
            if time.time() - last_watchdog >= 15:
                check_and_restart(states)
                last_watchdog = time.time()

            # Summary
            if time.time() - last_summary >= SUMMARY_INTERVAL:
                print_summary(states)
                last_summary = time.time()

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print(f"\n{DIM}Monitor stopped.{RESET}")
        print_summary(states)


if __name__ == "__main__":
    main()
