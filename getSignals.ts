import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');

    const res = await fetch(`${bridgeUrl}/proxy/signals`, {
      headers: { 'X-Bridge-Key': bridgeKey },
    });

    const data = await res.json();

    // Bridge now returns all statuses (PENDING, EXECUTED, FAILED, EXPIRED, CANCELLED)
    // with sl_pips, tp_pips included — last 200 records ordered newest first
    const signals = (data.signals || []).map(s => ({
      signal_uuid: s.uuid,
      symbol:      s.symbol,
      direction:   s.direction,
      timeframe:   s.timeframe,
      confidence:  s.confidence,
      status:      s.status || 'PENDING',
      sl_pips:     s.sl_pips ?? null,
      tp_pips:     s.tp_pips ?? null,
      created_at:  s.created_at,
    }));

    return Response.json(signals);
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
