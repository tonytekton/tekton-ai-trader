import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const isAuthenticated = await base44.auth.isAuthenticated();
    if (!isAuthenticated) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');

    const res = await fetch(`${bridgeUrl}/data/settings`, {
      headers: { 'X-Bridge-Key': bridgeKey },
    });

    const row = await res.json();

    const payload = {
      AUTO_TRADE:           row.auto_trade   ?? false,
      FRIDAY_FLUSH:         row.friday_flush ?? false,
      RISK_PCT:             row.risk_pct             ?? 0.01,
      TARGET_REWARD:        row.target_reward        ?? 1.8,
      DAILY_DRAWDOWN_LIMIT: row.daily_drawdown_limit ?? 0.05,
    };

    const base64String = btoa(JSON.stringify(payload));
    return Response.json({ config: base64String });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
