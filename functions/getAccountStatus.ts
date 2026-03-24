import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');

    if (!bridgeUrl || !bridgeKey) {
      return Response.json({ error: 'Bridge not configured' }, { status: 500 });
    }

    // Fetch account status (balance, equity, margin_used, free_margin, drawdown_pct)
    const accountRes = await fetch(`${bridgeUrl}/account/status`, {
      headers: { 'X-Bridge-Key': bridgeKey },
    });

    if (!accountRes.ok) {
      const text = await accountRes.text();
      return Response.json({ error: `Bridge error: ${text}` }, { status: accountRes.status });
    }

    const accountData = await accountRes.json();

    // Fetch live positions for open count + live margin sum
    let openCount = 0;
    let marginUsed = accountData.margin_used ?? 0;

    try {
      const posRes = await fetch(`${bridgeUrl}/positions/list`, {
        headers: { 'X-Bridge-Key': bridgeKey },
      });
      if (posRes.ok) {
        const posData = await posRes.json();
        const positions = posData.positions ?? [];
        openCount = positions.length;
        // Sum live margin from positions (in cents → euros)
        const marginCents = positions.reduce((sum: number, p: any) => sum + (p.marginUsed_cents ?? 0), 0);
        if (marginCents > 0) marginUsed = marginCents / 100;
      }
    } catch { /* fallback to account status margin */ }

    const balance = accountData.balance ?? 0;
    const equity  = balance + (accountData.unrealisedPnL ?? 0);

    return Response.json({
      data: {
        balance:      accountData.balance      ?? 0,
        equity:       accountData.equity       ?? accountData.balance ?? 0,
        free_margin:  accountData.free_margin  ?? 0,
        margin_used:  marginUsed,
        drawdown_pct: accountData.drawdown_pct ?? 0,
        currency:     accountData.currency     ?? 'EUR',
        open_count:   openCount,
      }
    });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
