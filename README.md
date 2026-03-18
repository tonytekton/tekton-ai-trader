# 📘 Tekton AI Trader — Developer README
## v4.7 — March 2026

---

## 🚀 System Overview

Tekton AI Trader (v4.7) is a modular, multi-strategy quantitative trading framework built on a three-tier Python architecture hosted on Google Cloud. It decouples market analysis from execution using a Single-Step Atomic Order model and AI-driven position management.

The Base44 UI is a **skin-only frontend** — all trading logic lives on the VM. Never put trading logic in the UI.

---

## 🏗️ Architecture

| Service | File | Description |
|---|---|---|
| Bridge | `tekton_bridge.py` | REST-to-Protobuf gateway. Port 8080 (REST) / 5035 (cTrader). Atomic orders via `rel_sl`/`rel_tp`. |
| Executor | `tekton_executor.py` | Risk orchestration. Polls PENDING signals, calculates volume, calls Bridge. |
| Monitor | `tekton_monitor.py` | AI-driven position management + circuit breaker. Calls `aiPositionReview` Base44 function. |
| Backfill | `tekton_backfill.py` | Fills `market_data` gaps every 15min via cron. 50 symbols × 5 timeframes. |
| Daily Report | `tekton_daily_report.py` | Sends Telegram P&L summary. Cron: `0 22 * * *` (22:00 UTC = 06:00 KL). |

**Database:** PostgreSQL at `172.16.64.3` (internal IP). DB name: `tekton-trader`.  
**Bridge auth:** Header `X-Bridge-Key` (env var `BRIDGE_KEY`).

---

## 🛠️ Service Management

| Service | Command |
|---|---|
| Bridge | `sudo systemctl restart tekton-ai-trader-bridge.service` |
| Executor | `sudo systemctl restart tekton-executor.service` |
| Monitor | `sudo systemctl restart tekton-monitor.service` |
| **Full stack restart** | `bash /home/tony/tekton-ai-trader/start_tekton.sh` |

`start_tekton.sh` starts all services, all 7 strategies, runs an immediate backfill, and re-registers both cron jobs.

---

## 🧠 Active Strategies

| File | Name | Logic | Session |
|---|---|---|---|
| `strat_ict_fvg_v1.py` | Tekton-ICT-FVG-v1 | Fair Value Gap + MSS + Liquidity Grab | 24/7 |
| `strat_ema_pullback_v1.py` | Tekton-EPS-v1 | 4H EMA trend + 15min pullback rejection | 24/7 |
| `strat_session_orb_v1.py` | Tekton-SORB-v1 | London/NY session open range breakout | London 07:00 / NY 13:00 UTC |
| `strat_vwap_reversion_v1.py` | Tekton-VR-v1 | VWAP deviation ≥1.5×ATR + reversal candle | 24/7 |
| `strat_breakout_retest_v1.py` | Tekton-BRT-v1 | S/R breakout + confirmed retest flip | 24/7 |
| `strat_rsi_divergence_v1.py` | Tekton-RSID-v1 | RSI divergence at structure | 24/7 |
| `strat_lester_v1.py` | Tekton-LSV-v1 | Liquidity sweep + ChoCH + volume confirmation | London 07-12 / NY 13-18 UTC |

**Entry quality gate (all strategies):** MIN_RR = 1.5 — signals with `tp_pips/sl_pips < 1.5` are rejected.

---

## 📐 Standard Signal Schema

All strategies MUST insert signals in this format:

```json
{
  "symbol":           "EURUSD",
  "strategy":         "Tekton-ICT-FVG-v1",
  "signal_type":      "BUY",
  "timeframe":        "15min",
  "confidence_score": 80,
  "sl_pips":          15.0,
  "tp_pips":          27.0,
  "status":           "PENDING"
}
```

**CRITICAL:** `sl_pips` and `tp_pips` are REQUIRED and must never be NULL.  
**Bridge field:** `side` (not `direction`). Values: `BUY` or `SELL`.

---

## ⚙️ Settings — Single Source of Truth

All settings live in the `settings` table (row `id=1`) in the SQL DB.

| Field | Default | Description |
|---|---|---|
| `auto_trade` | false | Enable autonomous execution |
| `friday_flush` | false | Close all positions at 16:00 UTC on Fridays |
| `risk_pct` | 0.01 | Risk per trade (1% = 0.01) |
| `target_reward` | 1.8 | Target R:R ratio |
| `daily_drawdown_limit` | 0.05 | Max daily drawdown (5% = 0.05) |
| `max_session_exposure_pct` | 4.0 | Max total open risk at any time (%) |

**Base44 entities `UserConfig` and `SystemSettings` are DEPRECATED.** Do not use.

---

## 🤖 AI Position Management

The monitor calls `aiPositionReview` (Base44 backend function) per open position.

**Trigger conditions (delta-based):**
- R-value moved ≥ 0.25 since last review
- Price within 20% of SL or TP
- New candle formed
- 15 minutes elapsed (max interval)

**Actions:** `HOLD` | `CLOSE` | `ADJUST_SL` | `ADJUST_TP` | `PARTIAL_CLOSE`

Every decision logged to `AiIntervention` entity in Base44.

---

## 🚨 Drawdown Autopsy

When circuit breaker fires:
1. All positions closed immediately
2. Snapshot taken (open positions + last 50 signals + last 20 AI interventions)
3. `drawdownAutopsy` Base44 function performs AI forensic analysis
4. Report written to `DrawdownAutopsy` entity
5. Trading frozen until status set to `APPROVED_RESUME` in UI

**Status flow:** `ANALYSING` → `AWAITING_REVIEW` → `APPROVED_RESUME` | `DISMISSED`

---

## 🛡️ Safety Rules

- **Atomic orders only** — always use `rel_sl` and `rel_tp` in the initial request. Never modify after open.
- **No hardcoded credentials** — all via `os.getenv()` from `.env` file.
- **Volume from equity** — calculated from `free_margin × risk_pct`. Never hardcoded.
- **Dynamic pip sizing** — all strategies fetch `pipPosition` from bridge `/symbols/list`. No hardcoded pip maps.
- **Signals expire** after 30 minutes if still PENDING.
- **Session exposure cap** — executor rejects new trades if total open risk ≥ `max_session_exposure_pct`.

---

## 🚦 Operational Protocols

**Monday Morning:** Check all service statuses, SQL heartbeat, confirm backfill is current.  
**Friday:** Friday Flush closes all positions at 16:00 UTC automatically (if enabled).  
**Emergency Panic:** `pkill -f tekton` + `UPDATE signals SET status='CANCELLED' WHERE status='PENDING'`

---

## 📁 Repository Structure

```
/                          # VM scripts (Python)
├── tekton_bridge.py       # Bridge service
├── tekton_executor.py     # Executor service
├── tekton_monitor.py      # Monitor service
├── tekton_backfill.py     # Market data backfill
├── tekton_daily_report.py # Telegram daily report
├── start_tekton.sh        # Full stack restart
├── strat_*.py             # Strategy scripts
├── systemd/               # Systemd service files
├── base44-ui/pages/       # Base44 frontend page source
└── *.ts                   # Base44 backend functions
```

---

**Project Owner:** Tony  
**System Version:** 4.7  
**GitHub:** https://github.com/tonytekton/tekton-ai-trader/
