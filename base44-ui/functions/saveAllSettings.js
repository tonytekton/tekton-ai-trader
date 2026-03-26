import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const body = await req.json();
    const { auto_trade, friday_flush, risk_pct, target_reward, daily_drawdown_limit,
            max_session_exposure_pct, max_lots, min_sl_pips, news_blackout_mins } = body;
    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');
    if (!bridgeUrl || !bridgeKey) return Response.json({ error: 'Bridge not configured' }, { status: 500 });
    const res = await fetch(`${bridgeUrl}/data/settings`, {
      method: 'POST',
      headers: { 'X-Bridge-Key': bridgeKey, 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_trade, friday_flush, risk_pct, target_reward,
        daily_drawdown_limit, max_session_exposure_pct, max_lots, min_sl_pips, news_blackout_mins }),
    });
    if (!res.ok) { const text = await res.text(); return Response.json({ error: `Bridge error ${res.status}: ${text.slice(0,300)}` }, { status: 502 }); }
    const data = await res.json();
    return Response.json(data);
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
