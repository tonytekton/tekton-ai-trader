/**
 * getAccountStatus — Tekton Trading Hub
 *
 * Calls bridge /account/status which serves live in-memory state:
 *   - balance: account balance (cents/100)
 *   - equity: balance + sum of unrealized net P&L from position_state{}
 *   - free_margin: equity - margin_used
 *   - margin_used: sum of usedMargin across open positions
 *   - drawdown_pct: (starting_equity - equity) / starting_equity * 100
 *   - daily_pnl: equity - starting_equity (today's P&L in account currency)
 *   - open_count: number of live open positions in position_state{}
 *   - currency: account deposit currency
 *
 * NOTE: Previously called /proxy/account-summary which reads a stale SQL table.
 * Fixed 2026-03-27 to use /account/status (live state{} in bridge memory).
 */

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

    // /account/status serves live in-memory state — correct endpoint
    const res = await fetch(`${bridgeUrl}/account/status`, {
      headers: { 'X-Bridge-Key': bridgeKey }
    });

    if (!res.ok) {
      const text = await res.text();
      return Response.json({ error: `Bridge error: ${text}` }, { status: res.status });
    }

    const data = await res.json();
    return Response.json({ data });

  } catch (error) {
    return Response.json({ error: (error as Error).message }, { status: 500 });
  }
});
