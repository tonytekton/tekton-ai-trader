#!/usr/bin/env python3
"""
tekton_tail.py — Combined live log stream for all Tekton components
Usage: python3 ~/tekton-ai-trader/tekton_tail.py
"""

import os, sys, time, threading
from collections import deque

DIR = os.path.expanduser("~/tekton-ai-trader")

SOURCES = [
    ("strat_fvg.log",     "FVG    ", "\033[0;36m"),    # cyan
    ("strat_eps.log",     "EPS    ", "\033[0;32m"),    # green
    ("strat_sorb.log",    "SORB   ", "\033[1;33m"),    # yellow
    ("strat_vwap.log",    "VWAP   ", "\033[0;35m"),    # magenta
    ("strat_brt.log",     "BRT    ", "\033[0;34m"),    # blue
    ("strat_rsid.log",    "RSID   ", "\033[0;31m"),    # red
    ("strat_lester.log",  "LESTER ", "\033[1;37m"),    # white bold
    ("executor.log",      "EXEC   ", "\033[1;32m"),    # green bold
    ("monitor.log",       "MONITOR", "\033[1;33m"),    # yellow bold
    ("bridge.log",        "BRIDGE ", "\033[0;37m"),    # grey
]

NC = "\033[0m"
LOCK = threading.Lock()

def tail_file(filepath, label, color):
    try:
        with open(filepath, "r") as f:
            f.seek(0, 2)  # seek to end
            while True:
                line = f.readline()
                if line:
                    with LOCK:
                        print(f"{color}[{label}]{NC} {line}", end="", flush=True)
                else:
                    time.sleep(0.1)
    except FileNotFoundError:
        pass  # file doesn't exist yet, skip silently
    except Exception as e:
        with LOCK:
            print(f"[{label}] ⚠️ Error: {e}")

print(f"\033[1;37m🎩 Tekton Combined Log — {time.strftime('%Y-%m-%d %H:%M:%S')} KL\033[0m")
print("──────────────────────────────────────────────────────────────────")

active = 0
threads = []
for filename, label, color in SOURCES:
    fp = os.path.join(DIR, filename)
    t = threading.Thread(target=tail_file, args=(fp, label, color), daemon=True)
    t.start()
    threads.append(t)
    active += 1

print(f"👁  Watching {active} log files. Ctrl+C to stop.\n")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n🛑 Stopped.")
