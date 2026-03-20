# Monday 23 March 2026 — Session Plan & Pre-Diagnostics

**Prepared by Lester | Friday 20 Mar 2026 22:xx KL**

---

## Session Order of Play

1. Lester reads SystemContext + ImplementationPlan (start of session ritual)
2. Signals Log fix (FAST WIN — root cause already diagnosed)
3. Phase 11c refactor (Bridge architectural work)
4. Dashboard Command Center fixes (root causes diagnosed)
5. Multi-timeframe + metals/indices signals
6. Analytics page build
7. Economic Calendar implementation
8. AI recommendations discussion

---

## Pre-Diagnostics Completed Tonight (20 Mar 2026)

### Item 2: Signals Log — All Showing FAILED ✅ DIAGNOSED

**Root cause confirmed:**
- Signals table has column named `direction` (stores BUY/SELL)
- `tekton_executor.py` line ~251 queries column `signal_type` — which doesn't exist
- SQL exception → `except` block marks signal `FAILED`
- This explains 196 FAILED out of 200 total signals

**Evidence:**
- Bridge `/proxy/signals` returns `direction` field
- Strategy scripts INSERT into `signal_type` column (EMA Pullback confirmed)
- Executor SELECT: `SELECT signal_uuid, symbol, signal_type ...` — mismatch
- Only 4 COMPLETED signals (likely manual/direct executions that bypassed executor)

**Fix (1 line in executor):**
```python
# Line ~251 tekton_executor.py — change:
SELECT signal_uuid, symbol, signal_type, timeframe, sl_pips, tp_pips
# To:
SELECT signal_uuid, symbol, direction, timeframe, sl_pips, tp_pips
```
Also update line ~261: `s_uuid, sym, s_type, tf, sl_pips, tp_pips = signal` (variable name doesn't matter, just needs to match)

**Added to Plan:** Phase 13

---

### Item 7: Command Center Dashboard ✅ DIAGNOSED

**Confirmed live data (20 Mar 2026):**
- Balance: €3,472,798.74
- Equity: €3,472,798.74 (WRONG — should be ~€3,491,446 with open PnL)
- Free margin: €3,472,798.74 (WRONG — should be ~€3,410,730)
- Margin used: €0.00 (WRONG — actually €62,069 from 6 open positions)
- Open positions: 6 confirmed live
- Unrealised PnL: +€18,647

**Root causes:**
1. `/account/status` doesn't return `balance` field — Dashboard using wrong endpoint
2. `/proxy/account-summary` returns `margin_used: 0.0` — bridge not tracking this from TraderUpdatedEvent
3. Open trade count: Dashboard not reading from `/positions/list`
4. Session exposure 0%: downstream of margin_used bug
5. Balance = equity: unrealised PnL not being added to equity calculation

**Fix approach:** 
- Switch to `/proxy/account-summary` for balance
- Calculate margin from `/positions/list` sum of `marginUsed_cents / 100`
- Calculate equity = balance + sum of `unrealizedNetPnL_cents / 100`
- Calculate session exposure = margin / balance × 100

**Added to Plan:** Phase 14

---

### Item 5: Why Only 15min Signals? ✅ DIAGNOSED

**Root cause confirmed:**
- All strategy scripts hardcode `LTF_TIMEFRAME = "15min"` 
- Signal INSERT hardcodes `'15min'` as timeframe value
- `get_active_symbols()` requires both 15min AND 4H data — metals/indices may lack 4H candles

**Confirmed market data exists:**
- XAUUSD 15min: ✅ 4,999 candles
- US30 15min: ✅ 4,999 candles
- 4H candles: status unknown — need to query DB on Monday

**To generate 1H/4H/Daily signals:**
1. Backfill 1H and Daily candles into market_data table
2. Create strategy variants with configurable timeframes

**Added to Plan:** Phase 15

---

### Item 9: Metals/Indices Signal Generation ✅ DIAGNOSED (partial)

- XAUUSD, XAGUSD, XPTUSD confirmed in broker symbol list
- US30, US500, UK100, JP225, AUS200 confirmed
- USTEC, DE40, STOXX50, F40 also available
- 15min data confirmed for metals + US30
- **Zero signals generated for any of these** — likely 4H data missing → `get_active_symbols()` returns empty for them
- Monday action: query market_data for 4H coverage of metals/indices

**Added to Plan:** Phase 15

---

### Item 8: AI Recommendations — When to Enable?

**Decision proposed:**
- Enable after 100+ closed trades (meaningful statistical base)
- Current state: insufficient closed trade history
- Gate in Analytics page with progress indicator

**Added to Plan:** Phase 16, task t16_6

---

## Items for Monday Build

| Item | Phase | Status | Complexity |
|------|-------|--------|-----------|
| Signals FAILED bug | Phase 13 | Ready to fix | 🟢 5 min |
| Dashboard fixes | Phase 14 | Diagnosed, ready | 🟡 2-3 hrs |
| Phase 11c refactor | Phase 11 | Design complete | 🔴 Half day |
| Economic Calendar | Phase 8 | In progress | 🟡 2-3 hrs |
| Multi-TF signals | Phase 15 | Needs DB audit first | 🟡 1-2 hrs |
| Analytics page | Phase 16 | Design ready | 🔴 Half day |
| AI Recommendations | Phase 16 | Needs trade history | 🟡 Design + future |

---

## Notes

- Friday Flush fired ~16:00 UTC (midnight KL) — all open positions closed
- Monday session starts fresh (no open positions expected)
- Phase 11c is the biggest architectural item — suggest tackling early while fresh
- Signals fix is the fastest win — do this first to unblock signal tracking

---

*Lester — prepared 20 Mar 2026*
