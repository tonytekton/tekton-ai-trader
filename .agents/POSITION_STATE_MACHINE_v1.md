# Position State Machine — Design Document v1.0
## Tekton AI Trader — Trade Management Architecture
### Agreed: 2026-03-28

---

## Core Principle

All trade management parameters (partial exit trigger, partial size, trail distance) are
**configurable and AI-learnable** — not hardcoded. The AI reads outcomes over time and
adjusts recommendations. The state machine enforces authority rules to prevent conflicts
between concurrent systems.

---

## Position States

```
OPEN
  │
  ├─ tp2_pips set AND current_r >= partial_exit_r  ──> PARTIAL_DONE
  │   (close partial_exit_pct%, move SL to entry)
  │
  ├─ no tp2_pips AND pct_to_tp >= 0.5              ──> BE_APPLIED
  │   (move SL to entry only — single-TP path)
  │
  └─ AI review (CLOSE / ADJUST_SL / ADJUST_TP)     ──> stays OPEN or CLOSED
  │
PARTIAL_DONE
  │   (50% closed, SL at entry, runner still live)
  ├─ trail_pips move fires                         ──> TRAILING
  └─ AI review (CLOSE remaining / ADJUST_TP only)
  │
BE_APPLIED
  │   (full position, SL at entry)
  ├─ trail_pips move fires                         ──> TRAILING
  └─ AI review (CLOSE / ADJUST_TP only)
  │
TRAILING
  │   (SL owned by trail logic)
  ├─ trail SL moves up each cycle
  ├─ AI can CLOSE or ADJUST_TP
  ├─ AI can override SL in extreme cases (black swan)
  └─ SL hit or TP hit                              ──> CLOSED
  │
CLOSED
    (terminal — no actions)
```

---

## DB Schema Changes

### signals table — new columns

```sql
-- Position state machine
ALTER TABLE signals ADD COLUMN IF NOT EXISTS position_phase   TEXT    DEFAULT 'OPEN';
-- values: OPEN | PARTIAL_DONE | BE_APPLIED | TRAILING | CLOSED

-- Partial exit config (set by strategy or AI, overrides settings default)
ALTER TABLE signals ADD COLUMN IF NOT EXISTS tp2_pips         DOUBLE PRECISION DEFAULT NULL;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS partial_exit_r   DOUBLE PRECISION DEFAULT NULL;
-- NULL = use settings default. AI can write a learned value here per signal.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS partial_exit_pct DOUBLE PRECISION DEFAULT NULL;
-- NULL = use settings default (50%). AI can adjust per signal.

-- Trail config (set by AI, overrides settings default)
ALTER TABLE signals ADD COLUMN IF NOT EXISTS trail_pips_override DOUBLE PRECISION DEFAULT NULL;
-- NULL = use settings.trail_pips default. AI writes learned value here.

-- Tracking
ALTER TABLE signals ADD COLUMN IF NOT EXISTS partial_closed_at  TIMESTAMPTZ DEFAULT NULL;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS be_applied_at      TIMESTAMPTZ DEFAULT NULL;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS trailing_since     TIMESTAMPTZ DEFAULT NULL;
```

### settings table — new defaults (AI learning baseline)

```sql
ALTER TABLE settings ADD COLUMN IF NOT EXISTS partial_exit_r   DOUBLE PRECISION NOT NULL DEFAULT 1.0;
ALTER TABLE settings ADD COLUMN IF NOT EXISTS partial_exit_pct DOUBLE PRECISION NOT NULL DEFAULT 50.0;
ALTER TABLE settings ADD COLUMN IF NOT EXISTS trail_pips        DOUBLE PRECISION NOT NULL DEFAULT 10.0;
ALTER TABLE settings ADD COLUMN IF NOT EXISTS trail_enabled     BOOLEAN          NOT NULL DEFAULT TRUE;
ALTER TABLE settings ADD COLUMN IF NOT EXISTS partial_enabled   BOOLEAN          NOT NULL DEFAULT TRUE;
```

---

## Authority Matrix

| State        | Partial Close | Move SL to BE | Trail SL   | AI ADJUST_SL    | AI CLOSE          | AI ADJUST_TP |
|--------------|---------------|---------------|------------|-----------------|-------------------|--------------|
| OPEN         | ✅ at r trigger| ✅ at 50% dist | ❌         | ✅              | ✅                | ✅           |
| PARTIAL_DONE | ❌ done        | ❌ done        | ✅ activates| ❌ locked       | ✅ remaining %    | ✅           |
| BE_APPLIED   | ❌             | ❌ done        | ✅ activates| ❌ locked       | ✅                | ✅           |
| TRAILING     | ❌             | ❌             | ✅ owns SL | ⚠️ override only | ✅               | ✅           |
| CLOSED       | ❌             | ❌             | ❌         | ❌              | ❌                | ❌           |

**TRAILING override rule:** AI can write ADJUST_SL only if reasoning contains "OVERRIDE" keyword
and current_r has moved against position by more than 2× trail_pips. This prevents AI from
casually overriding trailing logic while still allowing black-swan intervention.

---

## Monitor Loop Logic (pseudocode)

```python
def manage_position(pos, settings, signal):
    phase        = signal.get('position_phase', 'OPEN')
    tp2_pips     = signal.get('tp2_pips')
    partial_r    = signal.get('partial_exit_r') or settings.get('partial_exit_r', 1.0)
    partial_pct  = signal.get('partial_exit_pct') or settings.get('partial_exit_pct', 50.0)
    trail_pips   = signal.get('trail_pips_override') or settings.get('trail_pips', 10.0)
    trail_on     = settings.get('trail_enabled', True)
    partial_on   = settings.get('partial_enabled', True)

    # ── OPEN ──────────────────────────────────────────────────────────────
    if phase == 'OPEN':
        if partial_on and tp2_pips and current_r >= partial_r:
            partial_close(partial_pct)
            move_sl_to_entry()
            update_phase('PARTIAL_DONE')
            return

        pct_to_tp = (current_price - entry) / (tp - entry)  # BUY example
        if not tp2_pips and pct_to_tp >= 0.5:
            move_sl_to_entry()
            update_phase('BE_APPLIED')
            return

        # AI review — full authority
        ai_review(allow=['CLOSE', 'ADJUST_SL', 'ADJUST_TP', 'PARTIAL_CLOSE'])

    # ── PARTIAL_DONE or BE_APPLIED ─────────────────────────────────────────
    elif phase in ('PARTIAL_DONE', 'BE_APPLIED'):
        if trail_on:
            moved = trail_sl(trail_pips)
            if moved:
                update_phase('TRAILING')
                return
        # AI review — no SL authority
        ai_review(allow=['CLOSE', 'ADJUST_TP'])

    # ── TRAILING ──────────────────────────────────────────────────────────
    elif phase == 'TRAILING':
        trail_sl(trail_pips)  # always runs — owns SL
        # AI review — TP and emergency override only
        ai_review(allow=['CLOSE', 'ADJUST_TP', 'ADJUST_SL_OVERRIDE'])

    # ── Full close at target_r (single-TP path only) ───────────────────────
    if not tp2_pips and current_r >= target_r:
        close_full()
        update_phase('CLOSED')
```

---

## AI Learning Loop

The AI's role evolves across phases:

### Phase 20 (initial wiring)
- AI receives `position_phase` in context
- AI receives `partial_exit_r`, `partial_exit_pct`, `trail_pips` currently set
- AI can recommend new values in its response:
  ```json
  {
    "action": "HOLD",
    "suggested_partial_exit_r": 1.2,
    "suggested_trail_pips": 8.0,
    "reasoning": "..."
  }
  ```
- These suggestions are logged to `AiIntervention.reasoning` for human review — not auto-applied yet.

### Phase 25+ (autonomous tuning — future)
- AI suggestions with consistent positive outcome_r get auto-applied to signal schema
- Per-strategy learned defaults stored in `strategies` table
- Audit trail: every parameter change logged with before/after + AI reasoning

---

## Implementation Order

1. **DB migration** — `ALTER TABLE` statements above (run on VM via psql)
2. **Phase 19** — executor reads `tp2_pips`, bridge gets `/trade/partial_close`
3. **Phase 21** — monitor: trail logic, phase transitions PARTIAL_DONE → TRAILING
4. **Phase 20** — monitor: wire `aiPositionReview`, pass phase + authority context
5. **Phase 25** — AI parameter tuning loop (future)

---

## Key Rules (never break these)

1. `position_phase` is written by monitor only — never by strategy scripts or executor
2. SL in TRAILING state is owned by trail logic — AI needs OVERRIDE keyword to touch it
3. Partial close fires ONCE — state machine prevents double-firing
4. BE move fires ONCE — same protection
5. `tp2_pips = NULL` = legacy single-TP mode — all new partial logic skipped
6. Settings defaults are the AI's starting point — signal-level overrides are AI's learned refinements

---
