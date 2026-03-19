# Tekton Bridge — Option C Refactor Design
**Date:** 2026-03-19  
**Status:** APPROVED — pending implementation

---

## What We Are Fixing and Why

### Root cause of recurring bugs
The bridge has no single price normalisation layer. Every endpoint handles raw↔decimal conversion independently. This has already caused:
- SL/TP sent as raw integers to ProtoOAAmendPositionSLTPReq (expects decimal double)
- Entry price divided by 10^digits when it was already a double (ProtoOAOrder)
- Inconsistent scale checks scattered across 8 different functions

### Root cause of polling inefficiency
Every call to `/proxy/executions`, `/positions/list`, and `/trade/modify` fires serial blocking ProtoOA requests. The monitor polls `/positions/list` every 60s — this means ReconcileReq fires continuously, burning rate limits and adding 2-4s latency.

---

## The New Architecture

### Principle: cTrader pushes, bridge serves from state

```
BEFORE:
Request → Bridge → ReconcileReq → DealListReq → OrderListReq → SQL → Response
          (3-4 serial cTrader calls, 3-4 seconds, rate limit pressure)

AFTER:
cTrader → ExecutionEvent (push) ──→ bridge updates position_state{}
cTrader → SpotEvent (push)     ──→ bridge updates last_spot_prices{}  [already done]
cTrader → TraderUpdatedEvent   ──→ bridge updates account balance/equity

Request → Bridge → reads position_state{} + SQL enrichment → Response
          (<100ms, zero cTrader calls, no rate limit pressure)
```

---

## Three Key Changes

### Change 1: Price Normalisation Layer

Single source of truth for all price conversions. Added near top of file after imports.

```python
# ─── PRICE NORMALISATION ─────────────────────────────────────────────────────
# cTrader uses two price formats depending on the message type:
#   RAW INTEGER : ProtoOADeal.executionPrice, ProtoOAPosition.stopLoss/takeProfit,
#                 ProtoOATradeData.openPrice, market data candles
#   DECIMAL DOUBLE: ProtoOAOrder.executionPrice, ProtoOAAmendPositionSLTPReq fields,
#                   ProtoOANewOrderReq absolute SL/TP (not used — we use relative)
#
# Rule: raw_int / 10^digits = decimal. decimal * 10^digits = raw_int.
# Always use these helpers — never inline the conversion.

def raw_to_decimal(raw_int, digits):
    """Convert cTrader raw integer price to human-readable decimal."""
    if not raw_int:
        return None
    val = raw_int / (10 ** digits)
    return round(val, digits) if val >= 0.0001 else None  # discard bogus values

def decimal_to_raw(decimal_price, digits):
    """Convert human-readable decimal price to cTrader raw integer."""
    if not decimal_price:
        return None
    return int(round(float(decimal_price) * (10 ** digits)))
```

**Impact on existing bugs:**
- `modify_trade`: `req.stopLoss = float(sl_val)` — no conversion, it's already decimal ✅
- `execute_trade`: `entry_price = raw_to_decimal(entry_raw, digits)` ← only if from Deal; from Order it's already decimal ✅
- `/proxy/executions` closed trades: `raw_to_decimal(deal.executionPrice, digits)` ✅
- All position SL/TP from ReconcileReq: `raw_to_decimal(pos.stopLoss, digits)` ✅

---

### Change 2: Event-Driven Position State

Replace polling with push. Subscribe to `ProtoOAExecutionEvent` at startup (no extra message needed — it fires automatically after account auth). Add handler in `on_message`.

#### New state entries
```python
state = {
    ...existing...
    "position_state": {},        # positionId(str) → full position dict (live, always current)
    "position_state_ready": False,  # True after initial ReconcileReq seed at startup
}
```

#### Startup: seed position_state from ReconcileReq (one-time, at auth)
After account auth completes (where we currently do AssetListReq → TraderReq → SymbolsListReq), add:
```
→ ProtoOAReconcileReq  (one-time seed of open positions into position_state)
```
This runs once at bridge startup. After that, position_state is maintained purely by ExecutionEvent.

#### ExecutionEvent handler (in on_message, alongside SpotEvent)
```python
if pt == openapi.ProtoOAExecutionEvent().payloadType:
    ev = openapi.ProtoOAExecutionEvent()
    ev.ParseFromString(msg.payload)
    _handle_execution_event(ev)
    return
```

```python
def _handle_execution_event(ev):
    """
    Fires on: ORDER_FILLED, POSITION_OPENED, POSITION_CLOSED,
              POSITION_AMENDED, ORDER_CANCELLED, STOP_OUT, etc.
    Updates position_state{} in real time — no polling needed.
    """
    exec_type = ev.executionType  # ProtoOAExecutionType enum

    POSITION_OPENED  = 2
    POSITION_AMENDED = 7   # SL/TP changed
    POSITION_CLOSED  = 3
    ORDER_FILLED     = 2   # same as POSITION_OPENED for market orders

    if hasattr(ev, 'position') and ev.position:
        pos = ev.position
        pos_id = str(pos.positionId)
        spec = state['symbol_id_to_spec_map'].get(pos.tradeData.symbolId, {})
        digits = spec.get('digits', 5)

        if exec_type in (POSITION_OPENED, POSITION_AMENDED, 7, 8):
            # Upsert into position_state
            state['position_state'][pos_id] = _position_to_dict(pos, spec, digits)
            # If we have entry_price from the order, store it too
            if hasattr(ev, 'order') and ev.order and ev.order.executionPrice:
                state['position_state'][pos_id]['entry_price'] = round(ev.order.executionPrice, digits)

        elif exec_type in (POSITION_CLOSED, 3):
            # Remove from state — position is gone
            state['position_state'].pop(pos_id, None)
```

#### `_position_to_dict` helper — single place that normalises a position object
```python
def _position_to_dict(pos, spec, digits):
    """Normalise a ProtoOAPosition into a clean dict. Single source of truth."""
    return {
        'id': str(pos.positionId),
        'symbol': spec.get('symbolName', f'UNKNOWN_{pos.tradeData.symbolId}'),
        'symbol_id': pos.tradeData.symbolId,
        'side': 'BUY' if pos.tradeData.tradeSide == TRADE_SIDE_BUY else 'SELL',
        'volume': round(pos.tradeData.volume / 10_000_000, 2),
        'volume_raw': pos.tradeData.volume,
        'entry_price': raw_to_decimal(getattr(pos.tradeData, 'openPrice', None), digits),
        'stop_loss': raw_to_decimal(getattr(pos, 'stopLoss', None), digits),
        'take_profit': raw_to_decimal(getattr(pos, 'takeProfit', None), digits),
        'comment': getattr(pos.tradeData, 'comment', None),   # signal_uuid
        'open_ts': getattr(pos.tradeData, 'openTimestamp', None),
        'digits': digits,
        'pnl': None,   # populated from GetPositionUnrealizedPnLRes or SpotEvent calc
        'status': 'open',
    }
```

---

### Change 3: TraderUpdatedEvent for live account balance

cTrader pushes `ProtoOATraderUpdatedEvent` whenever balance/equity/margin changes (on fill, close, deposit, etc.). We subscribe automatically. Handle it to keep state current:

```python
if pt == openapi.ProtoOATraderUpdatedEvent().payloadType:
    payload = openapi.ProtoOATraderUpdatedEvent()
    payload.ParseFromString(msg.payload)
    trader = payload.trader
    state['balance_cents'] = getattr(trader, 'balance', state['balance_cents'])
    state['equity_cents']  = getattr(trader, 'moneyBalance', state['equity_cents'])
    state['margin_used_cents'] = getattr(trader, 'usedMargin', state['margin_used_cents'])
    return
```

This means `/account/status` (polled by executor every loop) always returns live data with zero cTrader calls — it just reads state{}.

---

## Endpoint Changes After Refactor

### `/positions/list`
**Before:** ReconcileReq + GetPositionUnrealizedPnLReq (2 serial cTrader calls)  
**After:** Serve from `position_state{}`. Optionally call GetPositionUnrealizedPnLReq for live PnL (1 call, optional).

### `/proxy/executions` — open trades section
**Before:** ReconcileReq → OrderListReq (2 serial cTrader calls)  
**After:** Serve from `position_state{}`. SQL enrichment only (sl_pips, tp_pips, strategy).

### `/proxy/executions` — closed trades section
**Before:** DealListReq with maxRows=500, no pagination  
**After:** DealListReq with `hasMore` pagination loop. Cap at configurable lookback (default 30 days).

### `/trade/modify`
**Before:** ReconcileReq (just to get symbolId for digits) + AmendPositionSLTPReq  
**After:** Look up `position_state[position_id]` for digits. Direct AmendPositionSLTPReq. No ReconcileReq needed.  
**Bug fix:** `req.stopLoss = float(sl_val)` — pass decimal directly, no raw integer conversion.

### `/trade/close`
**Before:** ReconcileReq (just to get volume) + ClosePositionReq  
**After:** Look up `position_state[position_id]['volume_raw']`. Direct ClosePositionReq. No ReconcileReq needed.

### `/account/info`
**Before:** ProtoOATraderReq on every call  
**After:** Serve from state{} (kept live by TraderUpdatedEvent). Add a `?refresh=true` param to force a TraderReq if needed.

---

## What We Are NOT Changing

- Trade execution (`ProtoOANewOrderReq` with relativeStopLoss/relativeTakeProfit) — correct and atomic ✅
- Symbol loading at startup — correct ✅  
- SpotEvent subscription for live prices — correct ✅
- DealListReq for closed trade history — correct, just adding pagination ✅
- Flask + Twisted reactor threading pattern — correct ✅
- Authentication sequence — correct ✅

---

## DealListReq Pagination (Issue 5 fix)

```python
def fetch_all_deals(from_ts, to_ts):
    """Paginate DealListReq until hasMore is False."""
    all_deals = []
    current_to = to_ts
    while True:
        req = openapi.ProtoOADealListReq()
        req.ctidTraderAccountId = ACCOUNT_ID
        req.fromTimestamp = from_ts
        req.toTimestamp = current_to
        req.maxRows = 500
        # ... send and wait ...
        result = ...
        all_deals.extend(result.deal)
        if not getattr(result, 'hasMore', False):
            break
        # Move window back — oldest deal timestamp becomes new ceiling
        if result.deal:
            current_to = min(d.executionTimestamp for d in result.deal) - 1
        else:
            break
    return all_deals
```

---

## ExecutionType Values (from ProtoOAExecutionType enum)

| Value | Name | When it fires |
|-------|------|---------------|
| 2 | ORDER_FILLED | Market order filled — position opened |
| 3 | ORDER_CANCELLED | Pending order cancelled |
| 4 | ORDER_EXPIRED | Pending order expired |
| 5 | ORDER_AMENDED | Pending order amended |
| 6 | ORDER_REJECTED | Order rejected by broker |
| 7 | POSITION_CLOSED | Position closed (TP/SL/manual) |
| 8 | POSITION_AMENDED | SL/TP amended on open position |
| 9 | POSITION_PARTIAL_EXECUTION | Partial fill |
| 11 | STOP_OUT | Margin stop-out |

---

## Implementation Plan

**Phase 1 — Foundation (no breaking changes)**
1. Add `raw_to_decimal` / `decimal_to_raw` helpers
2. Add `position_state{}` and `position_state_ready` to state dict
3. Add `_position_to_dict` helper
4. Add ExecutionEvent handler in `on_message`
5. Add TraderUpdatedEvent handler in `on_message`
6. Add ReconcileReq seed at end of startup sequence (after symbols load)
7. Register new payload types in message router

**Phase 2 — Fix the bugs (using new helpers)**
1. Fix `modify_trade` — remove raw integer conversion, pass decimal directly
2. Fix `execute_trade` — use `raw_to_decimal` only for Deal prices; Order prices are already decimal
3. Fix `positions/list` — remove ReconcileReq + PnL req, serve from position_state{}
4. Fix `/proxy/executions` open trades — serve from position_state{}

**Phase 3 — Eliminate unnecessary ReconcileReq calls**
1. Fix `modify_trade` — remove ReconcileReq (use position_state{} for digits lookup)
2. Fix `close_trade` — remove ReconcileReq (use position_state{} for volume)
3. Fix `/account/info` — serve from state{} with optional ?refresh=true

**Phase 4 — Pagination**
1. Add `fetch_all_deals()` helper
2. Use in `/proxy/executions` closed trades
3. Use in `/positions/history`

---

## Risk Assessment

| Change | Risk | Mitigation |
|--------|------|-----------|
| ExecutionEvent handler | Medium — new code path in hot loop | position_state falls back to ReconcileReq if not ready |
| ReconcileReq seed at startup | Low — already used at startup for reconcile | Same pattern, different timing |
| modify_trade decimal fix | Low but impactful | Will fix the monitor's AI SL/TP adjustments |
| close_trade removing ReconcileReq | Low | position_state always has volume |
| TraderUpdatedEvent | Low | Additive only, doesn't replace startup TraderReq |

---

## What This Gives Us

| Metric | Before | After |
|--------|--------|-------|
| Calls per /proxy/executions | 3 cTrader + 1 SQL | 0 cTrader + 1 SQL |
| Calls per /positions/list | 2 cTrader | 0 cTrader |
| Calls per /trade/modify | 2 cTrader | 1 cTrader |
| Calls per /trade/close (no vol) | 2 cTrader | 1 cTrader |
| Calls per /account/status | 0 (already from state) | 0 |
| Monitor poll latency | ~3s | <100ms |
| SL/TP modify correctness | ❌ broken | ✅ fixed |
| Entry price on open trades | ~50% null | ✅ always populated (from ExecutionEvent) |
| Rate limit pressure | High | Minimal |
