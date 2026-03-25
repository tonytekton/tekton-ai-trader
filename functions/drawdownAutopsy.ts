import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

/**
 * Drawdown Autopsy Function
 *
 * Called by tekton_monitor.py when the circuit breaker fires.
 * Receives a full snapshot of account state, open positions, and recent signals.
 * I (Lester) analyse what went wrong, identify root causes, and write a report.
 * Trading remains frozen until you approve resumption via the UI.
 */

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);

    const body = await req.json().catch(() => ({}));
    const {
      drawdown_pct,
      drawdown_limit_pct,
      account_balance,
      account_equity,
      open_positions,
      recent_signals,       // last 50 signals from DB
      recent_interventions, // last 20 AI interventions
    } = body;

    // ── Create initial record — status ANALYSING ─────────────────────────
    const record = await base44.asServiceRole.entities.DrawdownAutopsy.create({
      triggered_at:              new Date().toISOString(),
      drawdown_pct:              drawdown_pct,
      drawdown_limit_pct:        drawdown_limit_pct,
      account_balance_at_breach: account_balance,
      account_equity_at_breach:  account_equity,
      open_positions_snapshot:   JSON.stringify(open_positions || []),
      recent_signals_snapshot:   JSON.stringify(recent_signals || []),
      ai_analysis:               'Analysis in progress...',
      status:                    'ANALYSING',
    });

    // ── Build analysis prompt ─────────────────────────────────────────────
    const prompt = `You are the AI risk analyst for the Tekton automated trading system. The circuit breaker has just fired — maximum drawdown has been breached. Your job is to perform a thorough autopsy and extract every lesson possible.

## Breach Details
- Drawdown at breach: ${drawdown_pct?.toFixed(2)}%
- Drawdown limit: ${drawdown_limit_pct?.toFixed(2)}%
- Account balance: ${account_balance}
- Account equity: ${account_equity}

## Open Positions at Time of Breach
${JSON.stringify(open_positions || [], null, 2)}

## Recent Signals (last 50)
${JSON.stringify(recent_signals || [], null, 2)}

## Recent AI Interventions (last 20)
${JSON.stringify(recent_interventions || [], null, 2)}

## Your Task
Perform a deep forensic analysis. Be honest — if your own prior interventions contributed to the loss, say so clearly. This is how we learn.

Answer these questions:
1. What was the proximate cause of the drawdown? (specific trades, symbols, timing)
2. Were there correlated positions all moving against at the same time?
3. Was this a market event (news, session open, volatility spike) or a systematic strategy failure?
4. Did the signal quality deteriorate before the breach? (confidence scores, SL sizes, win rate)
5. Did any of my prior AI interventions make things worse?
6. What should have been done differently?
7. What specific changes to strategy, risk settings, or signal filtering would prevent this repeating?

## Response Format (JSON only)
{
  "ai_analysis": "<full narrative analysis, 200-400 words>",
  "root_causes": "<bullet list of the 2-4 core root causes>",
  "lessons_learned": "<bullet list of concrete lessons>",
  "recommendations": "<specific actionable changes — settings, filters, or logic to adjust>"
}`;

    // ── Call AI ───────────────────────────────────────────────────────────
    const aiResponse = await base44.asServiceRole.ai.complete({
      messages: [{ role: 'user', content: prompt }],
      model: 'claude-3-5-sonnet',
      response_format: 'json',
    });

    let analysis: any;
    try {
      analysis = typeof aiResponse === 'string' ? JSON.parse(aiResponse) : aiResponse;
    } catch (_) {
      analysis = {
        ai_analysis:      'Analysis parse error — raw data preserved for manual review.',
        root_causes:      'Could not parse AI response.',
        lessons_learned:  '',
        recommendations:  '',
      };
    }

    // ── Update record with analysis ───────────────────────────────────────
    await base44.asServiceRole.entities.DrawdownAutopsy.update(record.id, {
      ai_analysis:      analysis.ai_analysis      || '',
      root_causes:      analysis.root_causes      || '',
      lessons_learned:  analysis.lessons_learned  || '',
      recommendations:  analysis.recommendations  || '',
      status:           'AWAITING_REVIEW',
    });

    return Response.json({
      ok:          true,
      autopsy_id:  record.id,
      status:      'AWAITING_REVIEW',
      summary:     analysis.root_causes || '',
    });

  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
