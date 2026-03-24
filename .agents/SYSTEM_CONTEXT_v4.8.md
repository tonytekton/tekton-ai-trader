# System Context & Developer Dossier
## Tekton AI Trader v4.8 — Read this before making ANY changes.
### Last updated: 2026-03-24

---

## Instructions for AI Assistant

1. Read this entire document before making ANY changes to this app or any script.
2. Never contradict the "Agreed Decisions" section without explicit user approval.
3. GitHub repo: https://github.com/tonytekton/tekton-ai-trader/ (public)
   - `main` branch = production stable (v4.7 + all hotfixes)
   - `feature/bridge-v4.8-event-driven` = active development branch for v4.8 bridge refactor
4. Always update this document to reflect any approved changes made to the system.
5. Always append a new entry to the Change Log when a change is made.
6. Gate Protocol: Discuss → Agree → Implement → Verify. Never skip steps.

---

## System Architecture

Three-tier Python architecture on Google Cloud VM (Debian/Ubuntu). The Base44 UI is a read-only reporting skin — it never contains trading logic.

| Service | File | Description | Restart Command |
|---|---|---|---|
| Bridge | tekton_bridge.py | REST-to-Protobuf gateway. Port 8080 (REST) / 5035 (cTrader). Single-Step Atomic Orders via rel_sl/rel_tp. | `sudo systemctl restart tekton-ai-trader-bridge.service` |
| Executor | tekton_executor.py | Risk orchestration. Polls PENDING signals. Calculates volume from equity × risk_pct ÷ pip_value. | `sudo systemctl restart tekton-executor.service` |
| Monitor | tekton_monitor.py | AI-driven position management. Circuit breaker. Calls aiPositionReview per position. | `nohup python3 tekton_monitor.py >> monitor.log 2>&1 &` |
| Backfill | tekton_backfill.py | Fills market_data gaps. Polls bridge /prices/historical every 15min via cron. | cron: `*/15 * * * *` |
| Daily Report | tekton_daily_report.py | Sends P&L summary to Telegram. | cron: `0 22 * * *` (22:00 UTC = 06:00 KL) |

### Full Stack Restart
```bash
bash /home/tony/tekton-ai-trader/start_tekton.sh
```

---

## Infrastructure & Access

| | |
|---|---|
| Server | Google Cloud Compute Engine — tony@tekton-ai-trader |
| Project Dir | /home/tony/tekton-ai-trader/ |
| DB Host | 172.16.64.3 (internal IP) |
| DB Name | tekton-trader |
| DB Auth | CLOUD_SQL_DB_USER / CLOUD_SQL_DB_PASSWORD (env vars via .env) |
| Bridge URL | BRIDGE_URL (env var) — local: http://localhost:8080, external: http://35.234.132.174:8080 |
| Bridge Auth | Header: X-Bridge-Key (BRIDGE_KEY env var) |
| GitHub | https://github.com/tonytekton/tekton-ai-trader/ (public) |
| Sessions Archive | https://github.com/tonytekton/tekton-sessions/ |
| Timezone | Asia/Kuala Lumpur (UTC+8) |
| Python venv | /home/tony/tekton-ai-trader/venv/bin/python |

### psql access pattern
```bash
source ~/tekton-ai-trader/.env && PGPASSWORD=$CLOUD_SQL_DB_PASSWORD psql \
  -h $CLOUD_SQL_HOST -U $CLOUD_SQL_DB_USER -d $CLOUD_SQL_DB_NAME -p ${CLOUD_SQL_PORT:-5432}
```

---

## Branch Strategy

| Branch | Purpose | Status |
|---|---|---|
| `main` | Production. All live scripts run from here. | Stable — v4.7 + hotfixes through 2026-03-20 |
| `feature/bridge-v4.8-event-driven` | Bridge v4.8 refactor only. Nothing else. | Active development — paused pending hotfix stability |

- **Tag:** `v4.7-stable` (SHA: 6e54b7d) — permanent rollback point on main
- **Rollback procedure:** `git checkout main -- tekton_bridge.py && sudo systemctl restart tekton-ai-trader-bridge.service`
- All Phase 11 work goes to the feature branch. `main` is untouched until full smoke test passes and Tony signs off.

---

## Data Flow & Signal Lifecycle

1. **Market Data** — `tekton_backfill.py` runs every 15min, fills candle gaps in `market_data` table across all 50 symbols × 5 timeframes (5min, 15min, 60min, 4H, Daily). Data arrives as raw integers from cTrader — divide by `10^digits` before price calculations.
2. **Strategy generates signal** — strategy script inserts PENDING signal into `signals` table with sl_pips + tp_pips populated.
3. **Executor picks up signal** — `tekton_executor.py` polls for PENDING signals, checks AUTO_TRADE flag, calculates volume, calls Bridge /trade/execute.
4. **Bridge executes order** — sends Single-Step Protobuf to cTrader with relativeStopLoss + relativeTakeProfit as **integer POINTS** (pips × 10). Signal UUID used as cTrader comment field.
5. **Bridge returns result** — `{ success, position_id, entry_price }`. entry_price is a scaled decimal (NOT raw integer). Executor writes position_id and avg_fill_price back to signals table.
6. **position_state{} updated** — bridge receives ProtoOAExecutionEvent push from cTrader, updates in-memory position_state{} dict in real time. This is the authoritative source for open position SL/TP.
7. **Monitor manages position** — `tekton_monitor.py` reviews each open position via `aiPositionReview` Base44 function. AI decides: HOLD / CLOSE / ADJUST_SL / ADJUST_TP / PARTIAL_CLOSE. Every decision logged to AiIntervention entity.
8. **Circuit Breaker** — if daily drawdown exceeds limit, all positions closed, `drawdownAutopsy` function called, full forensic snapshot written to DrawdownAutopsy entity. Trading frozen until manually resumed.
9. **Base44 UI reads results** — frontend fetches from bridge /proxy/executions — read-only reporting layer. Open position SL/TP enriched from position_state{} (ReconcileReq is unreliable for SL/TP on this broker).

---

## Standard Signal Schema (All strategies MUST follow this)

```json
{
  "signal_uuid":      "AUTO_GENERATED_BY_DB",
  "symbol":           "EURUSD",
  "strategy":         "Tekton-ICT-FVG-v1",
  "signal_type":      "BUY",
  "timeframe":        "15min",
  "confidence_score": 82,
  "sl_pips":          15.0,
  "tp_pips":          27.0,
  "status":           "PENDING"
}
```

**CRITICAL:** Never insert signals with NULL sl_pips or tp_pips. The Executor skips them and manual execution returns 400.
**CRITICAL:** confidence_score is an integer (0–100). Not a decimal like 0.82.

---

## cTrader Price Formats — Critical Reference

This is the most common source of bugs. Two formats exist:

| Format | Type | Used in |
|---|---|---|
| **RAW INTEGER** | `int / 10^digits = decimal` | `ProtoOADeal.executionPrice`, `ProtoOAPosition.stopLoss/takeProfit`, `ProtoOATradeData.openPrice`, market data candles |
| **DECIMAL DOUBLE** | Use as-is | `ProtoOAOrder.executionPrice`, `ProtoOAAmendPositionSLTPReq.stopLoss/takeProfit` |

**Rule:** Always use `raw_to_decimal(raw_int, digits)` and `decimal_to_raw(decimal, digits)` helpers. Never inline the conversion.

### relativeStopLoss / relativeTakeProfit — DEFINITIVE RULE (confirmed 2026-03-20)

This has been the source of repeated bugs. The definitive agreed format:

| Layer | Format | Example (15 pip SL) |
|---|---|---|
| Signal in DB | `sl_pips` float | `15.0` |
| Executor → Bridge payload (`rel_sl`) | PIPS, float, 1dp | `15.0` |
| Bridge → cTrader protobuf (`relativeStopLoss`) | INTEGER POINTS = `int(round(pips × 10))` | `150` |

- `ProtoOANewOrderReq.relativeStopLoss` is **int32** — MUST be an integer, no floats accepted
- 1 pip = 10 points for all standard instruments (5-digit pairs, JPY 3-digit, etc.)
- Error `"has type float, but expected one of: int"` = float was sent instead of int
- Error `"Relative stop loss has invalid precision"` = integer points were sent directly without × 10 conversion

### SL/TP on Open Positions
- **ReconcileReq**: does NOT reliably return stopLoss/takeProfit for this broker — do not rely on it
- **position_state{}**: authoritative source — populated from live ProtoOAExecutionEvent pushes
- `get_executions()` enriches open trade SL/TP from position_state{} after ReconcileReq loop

---

## Settings Architecture — Single Source of Truth

All settings live in the `settings` table in the SQL DB (row id=1).

```sql
CREATE TABLE IF NOT EXISTS settings (
  id                       SERIAL PRIMARY KEY,
  auto_trade               BOOLEAN          NOT NULL DEFAULT FALSE,
  friday_flush             BOOLEAN          NOT NULL DEFAULT FALSE,
  risk_pct                 DOUBLE PRECISION NOT NULL DEFAULT 0.01,
  target_reward            DOUBLE PRECISION NOT NULL DEFAULT 1.8,
  daily_drawdown_limit     DOUBLE PRECISION NOT NULL DEFAULT 0.05,
  max_session_exposure_pct DOUBLE PRECISION NOT NULL DEFAULT 4.0,
  max_lots                 DOUBLE PRECISION NOT NULL DEFAULT 5000,
  min_sl_pips              DOUBLE PRECISION NOT NULL DEFAULT 8.0,
  news_blackout_mins       INT              NOT NULL DEFAULT 30,
  updated_at               TIMESTAMPTZ      DEFAULT NOW()
);
INSERT INTO settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
```

- **UI Read:** TradingSettings page → GET bridge /data/settings
- **UI Write:** TradingSettings page → POST bridge /data/settings
- **Executor Read:** fetch_settings() → direct psycopg2 query on settings WHERE id=1
- Base44 entities UserConfig and SystemSettings are **DEPRECATED** — do not use.

### max_lots — Critical Note
- Default in DB schema: **5000** (for large accounts like this demo at €3.4M)
- Current live value: **6 lots** (set by Tony 2026-03-20 for controlled testing)
- TradingSettings UI default and fallback: **5000** (updated 2026-03-20)
- If DB ever shows 50 or 5 — it has been incorrectly reset. Fix via POST /data/settings.

---

## Bridge /trade/execute Payload

```json
{
  "symbol":  "EURUSD",
  "side":    "BUY",
  "volume":  0.43,
  "comment": "signal-uuid-here",
  "rel_sl":  12.5,
  "rel_tp":  22.5
}
```

Field is `side` not `direction`. Values: BUY or SELL.
`rel_sl` / `rel_tp` are in **PIPS** (float, rounded to 1 decimal). NOT integer points.
Bridge converts to integer points internally before sending to cTrader protobuf.

### Bridge execute response
```json
{
  "success":     true,
  "position_id": 593655453,
  "entry_price": 1.08432
}
```
`entry_price` is a **scaled decimal** — already divided by 10^digits. Store directly as avg_fill_price in signals table.

---

## v4.8 Bridge Architecture — Event-Driven Position State

The v4.8 refactor replaces ReconcileReq polling with push-based position_state{}.

### How it works
```
BEFORE (v4.7):
Every request → Bridge → ReconcileReq → DealListReq → OrderListReq → Response
                         (3-4 serial cTrader calls, 2-4s latency, rate limit pressure)

AFTER (v4.8):
cTrader → ProtoOAExecutionEvent (push) ──→ _handle_execution_event() → position_state{}
cTrader → ProtoOATraderUpdatedEvent    ──→ updates balance/equity/margin in state{}
cTrader → ProtoOASpotEvent             ──→ updates last_spot_prices{} [was already done]

Every request → Bridge → reads position_state{} + SQL enrichment → Response
                          (0 cTrader calls, <100ms, no rate limit pressure)
```

### position_state{} structure
```python
state["position_state"] = {
    "593186578": {
        "id":          "593186578",
        "symbol":      "EURAUD",
        "symbol_id":   12345,
        "side":        "SELL",
        "volume":      0.65,           # lots (human-readable)
        "volume_raw":  6500000,        # centilots (cTrader native)
        "entry_price": 1.62450,        # decimal (from ProtoOAOrder.executionPrice via ExecutionEvent)
        "stop_loss":   1.62306,        # decimal (from raw_to_decimal)
        "take_profit": 1.61997,        # decimal (from raw_to_decimal)
        "comment":     "4afbcc84-...", # signal_uuid
        "open_ts":     1773822838456,  # Unix ms
        "digits":      5,
        "pnl":         None,
    }
}
state["position_state_ready"] = True  # False until startup ReconcileReq seed completes
```

---

## Agreed Decisions (DO NOT change without explicit approval)

| Decision | Detail |
|---|---|
| relativeStopLoss format | Executor sends pips (float). Bridge converts to int points (pips×10) before protobuf. |
| SL/TP source for UI | position_state{} is authoritative. ReconcileReq unreliable on this broker. |
| Settings source of truth | SQL settings table id=1 only. Base44 entities DEPRECATED. |
| max_lots DB default | 5000 (large account). Current live: 6 (testing cap). |
| Volume formula | risk_cash / (sl_pips × pip_value_per_unit). pip_value from live bridge spec. |
| entry_price | From ProtoOAOrder.executionPrice via ExecutionEvent — decimal double, use as-is. |
| ReconcileReq openPrice | Unreliable for many brokers — use ExecutionEvent entry price instead. |
| MIN_RR | 1.5 minimum on all strategies. |
| Friday Flush | 16:00 UTC every Friday. |
| Feature branch policy | feature/bridge-v4.8-event-driven only for Phase 11. main untouched until smoke test. |

---

## Implementation Plan Status

| Phase | Description | Status |
|---|---|---|
| Phase 1 | Bridge: Settings endpoints | ✅ COMPLETE |
| Phase 2 | Executor: Read settings from SQL | ✅ COMPLETE |
| Phase 3 | UI: Settings page wired to SQL | ✅ COMPLETE |
| Phase 4 | Bridge filename & service references | ✅ COMPLETE |
| Phase 5 | Backfill verification | ✅ COMPLETE |
| Phase 6 | End-to-end smoke test | ✅ COMPLETE |
| Phase 7 | Strategy expansion | ✅ COMPLETE |
| Phase 8 | Economic Calendar (passive display) | 🔄 IN PROGRESS |
| Phase 9 | Economic Calendar (active trade gating) | ⏳ TODO |
| Phase 10 | Analytics page | ⏳ TODO |
| Phase 11 | Bridge v4.8 event-driven refactor | 🔄 IN PROGRESS (paused for hotfix stability) |
| Phase 12 | API Rate Monitor | ⏳ TODO |
| Phase 13 | Signals FAILED bug — signal_type/direction column mismatch in executor | ✅ COMPLETE (fix was already applied in prior session) |
| Phase 14 | Dashboard fixes — balance/equity/openCount/margin from live bridge | ✅ COMPLETE 2026-03-24 |
| Phase 15 | Multi-timeframe signals + metals/indices candle backfill | ⏳ TODO |
| Phase 16 | Analytics page + AI recommendations (requires 100+ closed trades) | ⏳ TODO |

### Phase 11 Sub-tasks
- 11a ✅ raw_to_decimal, decimal_to_raw, _position_to_dict, position_state{} in state dict
- 11b ✅ ExecutionEvent handler, TraderUpdatedEvent handler, startup ReconcileReq seed
- 11c ⏳ Refactor /positions/list, /proxy/executions, /proxy/signals, /trade/modify, /trade/close, /account/info to serve from position_state{}
- 11d ⏳ DealListReq pagination, smoke tests, merge to main

### Phase 13 Detail (Fast Fix)
- `tekton_executor.py` ~line 251: SELECT query uses column `direction` but signals table stores `signal_type`
- 196/200 signals marked FAILED due to this mismatch
- Fix: change `direction` → `signal_type` in the SELECT query
- No schema changes needed — 1-line fix

---

## Hotfixes Applied to main (2026-03-19 to 2026-03-24)

| SHA | Date | Fix |
|---|---|---|
| 869f71d | 2026-03-19 | relativeStopLoss: pips as float, not int points (fixes "invalid precision") |
| 353328f | 2026-03-20 | relativeStopLoss: must be int32 points — float still rejected. Formula: int(round(pips×10)) |
| 353328f | 2026-03-20 | P&L fix: closePrice tries multiple field names + debug fallback |
| 6dfc562 | 2026-03-20 | SL/TP in Execution Journal: enrich from position_state{} — ReconcileReq unreliable on this broker |
| a48487e | 2026-03-24 | Bridge v5.0: pos.price/stopLoss/takeProfit are doubles — remove integer division |
| 654bf04c | 2026-03-24 | Bridge: /account/status now returns balance + margin_used fields |
| b3e3eec | 2026-03-24 | UI: Dashboard openCount + margin_used sourced from /positions/list (live). getAccountStatus function updated. |

---

## Change Log

| Date | Change | Author |
|---|---|---|
| 2026-03-12 | Gate Protocol + Lester roles established | Tony + Lester |
| 2026-03-13 | Git conflict resolved. V3 CR backlog documented. | Tony + Lester |
| 2026-03-16 | .env restored. X-Bridge-Key header fix. pipPosition audit. | Tony + Lester |
| 2026-03-17 | ICT FVG strategy rewrite. EMA Pullback strategy deployed. Price scaling issues identified. | Tony + Lester |
| 2026-03-18 | max_lots column added to DB (was missing — caused undersizing). Session exposure cap clarified. | Tony + Lester |
| 2026-03-19 | relativeStopLoss "invalid precision" root cause found and fixed. Pips sent as float 1dp. | Tony + Lester |
| 2026-03-20 | relativeStopLoss must be int32 points (float still rejected). SL/TP display fixed using position_state{}. P&L closePrice fix. max_lots set to 6 for testing. TradingSettings UI default fixed. | Tony + Lester |
| 2026-03-23 | Bridge deduplication (execution journal). SL/TP dual-fallback from position_state + ReconcileReq. Settings persist correctly via saveAllSettings. min_sl_pips=8 enforced. | Tony + Lester |
| 2026-03-24 | Bridge v5.0: pos.price/stopLoss/takeProfit double fix. /account/status adds balance+margin_used. Dashboard Phase 14 complete: openCount+margin from live positions/list. GitHub integration established. | Tony + Lester |
