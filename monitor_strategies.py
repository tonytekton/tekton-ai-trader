"""
monitor_strategies.py — Tekton Unified Strategy Monitor
========================================================
Watches all strategy log files in real-time, colour-codes output by strategy,
and prints a rolling summary every 60 seconds showing:
  - Signals fired per strategy
  - Cooldowns / HTF blocks / no_setup counts
  - Whether each strategy process is alive
  - Last scan time per strategy

Usage:
  python3 monitor_strategies.py

Press Ctrl+C to exit.
"""

import os
import time
import subprocess
import re
from datetime import datetime
from collections import defaultdict

# ─── CONFIG ────────────────────────────────────────────────────────────────────

LOG_DIR = "/home/tony/tekton-ai-trader"

STRATEGIES = [
    {
        "name":    "FVG",
        "label":   "ICT FVG+MSS",
        "log":     os.path.join(LOG_DIR, "strategy.log"),
        "process": "strat_ict_fvg_v1.py",
        "color":   "\033[94m",   # blue
    },
    {
        "name":    "EPS",
        "label":   "EMA Pullback",
        "log":     os.path.join(LOG_DIR, "strat_eps.log"),
        "process": "strat_ema_pullback_v1.py",
        "color":   "\033[92m",   # green
    },
]

SUMMARY_INTERVAL = 60   # seconds between summary prints
POLL_INTERVAL    = 0.3  # seconds between log polls

# ─── ANSI COLOURS ──────────────────────────────────────────────────────────────

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
CYAN    = "\033[96m"
WHITE   = "\033[97m"
MAGENTA = "\033[95m"

# ─── STATE ─────────────────────────────────────────────────────────────────────

class StrategyState:
    def __init__(self, cfg):
        self.name      = cfg["name"]
        self.label     = cfg["label"]
        self.log_path  = cfg["log"]
        self.process   = cfg["process"]
        self.color     = cfg["color"]
        self.file_pos  = 0          # byte position in log file
        self.last_scan = None       # datetime of last scan
        self.last_line = None       # last log line seen
        # rolling counters (reset each summary cycle)
        self.signals   = 0
        self.cooldowns = 0
        self.htf_blocks= 0
        self.no_setup  = 0
        self.errors    = 0
        # session totals
        self.total_signals  = 0
        self.total_cooldowns= 0
        self.total_htf      = 0
        # signal log for summary
        self.recent_signals = []    # list of signal strings (last 10)

    def reset_cycle(self):
        self.signals    = 0
        self.cooldowns  = 0
        self.htf_blocks = 0
        self.no_setup   = 0
        self.errors     = 0


# ─── HELPERS ───────────────────────────────────────────────────────────────────

def ts():
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

def seek_to_end(state: StrategyState):
    """Position file pointer at end of log so we only see new lines."""
    if os.path.exists(state.log_path):
        state.file_pos = os.path.getsize(state.log_path)

def read_new_lines(state: StrategyState) -> list:
    """Read any new lines written since last poll."""
    if not os.path.exists(state.log_path):
        return []
    try:
        size = os.path.getsize(state.log_path)
        if size < state.file_pos:
            # Log was rotated/truncated
            state.file_pos = 0
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
    """Update state counters based on log line content."""
    if "Scan started" in line or "scan started" in line:
        state.last_scan = datetime.now()

    elif "📡 SIGNAL:" in line:
        state.signals       += 1
        state.total_signals += 1
        # Extract signal details for recent list
        # Format: [HH:MM:SS] 📡 SIGNAL: BUY  EURUSD     | SL:  12.0p TP:  21.6p | Conf:78%
        state.recent_signals.append(f"[{ts()}] {line.strip()}")
        if len(state.recent_signals) > 10:
            state.recent_signals.pop(0)

    elif "⏳ COOLDOWN:" in line:
        state.cooldowns       += 1
        state.total_cooldowns += 1

    elif "🚫 HTF BLOCK:" in line or "🚫 HTF block:" in line:
        state.htf_blocks   += 1
        state.total_htf    += 1

    elif "Scan done" in line:
        # Parse the summary line for no_setup count
        m = re.search(r"no_setup=(\d+)", line)
        if m:
            state.no_setup += int(m.group(1))

    elif "💥" in line or "❌" in line:
        state.errors += 1

    state.last_line = line.strip()


def print_line(line: str, state: StrategyState):
    """Print a log line with strategy colour prefix."""
    prefix = f"{state.color}{BOLD}[{state.name}]{RESET} "

    # Highlight key events
    if "📡 SIGNAL:" in line:
        print(f"{prefix}{state.color}{BOLD}{line}{RESET}")
    elif "💥" in line or "❌" in line:
        print(f"{prefix}{RED}{line}{RESET}")
    elif "⏳ COOLDOWN" in line or "🚫 HTF" in line:
        print(f"{prefix}{DIM}{line}{RESET}")
    elif "Scan done" in line or "scan done" in line:
        print(f"{prefix}{CYAN}{line}{RESET}")
    elif "🚀" in line:
        print(f"{prefix}{YELLOW}{line}{RESET}")
    else:
        print(f"{prefix}{line}")


def print_summary(states: list):
    """Print a formatted summary table for all strategies."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    width   = 72

    print(f"\n{BOLD}{CYAN}{'─' * width}{RESET}")
    print(f"{BOLD}{CYAN}  📊 STRATEGY SUMMARY  {DIM}{now_str}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}")

    for s in states:
        alive      = is_process_alive(s.process)
        status_str = f"{BOLD}\033[92m● RUNNING{RESET}" if alive else f"{BOLD}{RED}● DEAD{RESET}"
        last_scan  = s.last_scan.strftime("%H:%M:%S") if s.last_scan else "never"

        print(f"  {s.color}{BOLD}{s.label:<20}{RESET}  {status_str}  {DIM}last scan: {last_scan}{RESET}")
        print(f"    {'Signals:':<14} {BOLD}{WHITE}{s.total_signals:>4}{RESET}  "
              f"{'(this cycle:'} {s.signals})")
        print(f"    {'HTF Blocks:':<14} {s.total_htf:>4}    "
              f"{'Cooldowns:'} {s.total_cooldowns}")
        print()

    # Recent signals across all strategies
    all_recent = []
    for s in states:
        all_recent.extend([(sig, s) for sig in s.recent_signals])

    if all_recent:
        print(f"  {BOLD}Recent Signals:{RESET}")
        # Show last 5
        for sig, s in all_recent[-5:]:
            # Strip the duplicate timestamp prefix if present
            clean = re.sub(r"^\[[\d:]+\] ", "", sig)
            clean = re.sub(r"📡 SIGNAL: ", "", clean)
            print(f"    {s.color}▶{RESET} {clean}")
        print()

    # Dead process warning
    dead = [s for s in states if not is_process_alive(s.process)]
    if dead:
        print(f"  {RED}{BOLD}⚠️  DEAD PROCESSES: {', '.join(d.name for d in dead)}{RESET}")
        print(f"  {RED}   Restart with: nohup python3 -u <script>.py >> <log>.log 2>&1 &{RESET}")
        print()

    print(f"{BOLD}{CYAN}{'─' * width}{RESET}\n")

    # Reset cycle counters
    for s in states:
        s.reset_cycle()


# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    states = [StrategyState(cfg) for cfg in STRATEGIES]

    print(f"\n{BOLD}{YELLOW}🎩 Tekton Unified Strategy Monitor{RESET}")
    print(f"{DIM}Watching {len(states)} strategies | Summary every {SUMMARY_INTERVAL}s | Ctrl+C to exit{RESET}\n")

    # Seek all logs to end so we don't replay history
    for s in states:
        seek_to_end(s)
        alive = is_process_alive(s.process)
        status = f"{BOLD}\033[92mRUNNING{RESET}" if alive else f"{RED}NOT RUNNING{RESET}"
        print(f"  {s.color}{BOLD}{s.label}{RESET} — {status}  {DIM}({s.log_path}){RESET}")

    print()

    last_summary = time.time()

    try:
        while True:
            # Poll each strategy log for new lines
            for s in states:
                new_lines = read_new_lines(s)
                for line in new_lines:
                    parse_line(line, s)
                    print_line(line, s)

            # Print summary on interval
            if time.time() - last_summary >= SUMMARY_INTERVAL:
                print_summary(states)
                last_summary = time.time()

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print(f"\n{DIM}Monitor stopped.{RESET}")
        print_summary(states)


if __name__ == "__main__":
    main()
