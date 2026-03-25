import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

/**
 * AI Position Review Function
 * 
 * Called by tekton_monitor.py for each open position.
 * Packages position context, recent candle data, and intervention history,
 * then asks Lester (the AI) to make a trade management decision.
 * 
 * Returns a structured decision:
 *   { action, new_sl, new_tp, close_pct, reasoning }
 * 
 * Actions: HOLD | CLOSE | ADJUST_SL | ADJUST_TP | PARTIAL_CLOSE
 */

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);

    const body = await req.json().catch(() => ({}));
    const {
      position_id,
      symbol,
      strategy,
      direction,         // BUY or SELL
      entry_price,
      current_price,
      sl_price,
      tp_price,
      current_r,
      minutes_open,
      recent_candles,    // array of {time, open, high, low, close} last 20 candles
      pip_size,
    } = body;

    if (!position_id || !symbol) {
      return Response.json({ error: 'position_id and symbol required' }, { status: 400 });
    }

    // ── Load recent intervention history for this symbol+strategy ──────────
    let intervention_history: any[] = [];
    try {
      const history = await base44.asServiceRole.entities.AiIntervention.filter(
        { symbol, strategy },
        { sort: { created_date: -1 }, limit: 10 }
      );
      intervention_history = history.map((h: any) => ({
        action:     h.action,
        current_r:  h.current_r,
        reasoning:  h.reasoning,
        outcome:    h.outcome,
        outcome_r:  h.outcome_r,
        date:       h.created_date,
      }));
    } catch (_) {}

    // ── Build AI prompt ─────────────────────────────────────────────────────
    const prompt = `You are the AI trade manager for the Tekton automated trading system operating on a demo account. Your purpose is to learn what works — build knowledge through every decision.

## Current Position
- Symbol: ${symbol}
- Strategy: ${strategy}
- Direction: ${direction}
- Entry Price: ${entry_price}
- Current Price: ${current_price}
- Stop Loss: ${sl_price}
- Take Profit: ${tp_price}
- Current R: ${current_r?.toFixed(2)}R
- Minutes Open: ${minutes_open}
- Pip Size: ${pip_size}

## Recent Candles (newest last)
${recent_candles ? JSON.stringify(recent_candles, null, 2) : 'Not available'}

## Your Recent Intervention History (this symbol/strategy)
${intervention_history.length > 0 ? JSON.stringify(intervention_history, null, 2) : 'No history yet — this is early learning phase.'}

## Your Mandate
- This is a demo account. Your goal is to learn what maximises R over time.
- You have full autonomy. No hard rules constrain you.
- Consider: price structure, momentum, time open, distance to SL/TP, candle patterns.
- Build on your history — if past HOLDs led to losses, factor that in.
- Only intervene if you have a clear structural reason. HOLD is always valid.
- If unrealised loss exceeds 5× original SL distance, closing is justified to preserve learning capital.

## Response Format (JSON only, no other text)
{
  "action": "HOLD" | "CLOSE" | "ADJUST_SL" | "ADJUST_TP" | "PARTIAL_CLOSE",
  "new_sl": <number or null>,
  "new_tp": <number or null>,
  "close_pct": <0-100 or null, for PARTIAL_CLOSE>,
  "reasoning": "<concise explanation of your decision>"
}`;

    // ── Call AI ─────────────────────────────────────────────────────────────
    const aiResponse = await base44.asServiceRole.ai.complete({
      messages: [{ role: 'user', content: prompt }],
      model: 'claude-3-5-sonnet',
      response_format: 'json',
    });

    let decision: any;
    try {
      decision = typeof aiResponse === 'string' ? JSON.parse(aiResponse) : aiResponse;
    } catch (_) {
      decision = { action: 'HOLD', reasoning: 'AI response parse error — holding position.' };
    }

    // ── Log intervention to DB ───────────────────────────────────────────────
    const record = await base44.asServiceRole.entities.AiIntervention.create({
      position_id: String(position_id),
      symbol,
      strategy:    strategy || 'unknown',
      direction,
      entry_price,
      current_price,
      sl_price,
      tp_price,
      current_r,
      minutes_open,
      action:      decision.action || 'HOLD',
      new_sl:      decision.new_sl || null,
      new_tp:      decision.new_tp || null,
      close_pct:   decision.close_pct || null,
      reasoning:   decision.reasoning || '',
      outcome:     'PENDING',
      executed:    false,
    });

    return Response.json({
      ok:              true,
      intervention_id: record.id,
      decision,
    });

  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
