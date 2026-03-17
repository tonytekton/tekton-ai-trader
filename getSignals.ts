import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');

    // Forward query params: status, symbol, limit, offset
    const url = new URL(req.url);
    const status = url.searchParams.get('status') || '';
    const symbol = url.searchParams.get('symbol') || '';
    const limit  = url.searchParams.get('limit')  || '200';
    const offset = url.searchParams.get('offset') || '0';

    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (symbol) params.set('symbol', symbol);
    params.set('limit', limit);
    params.set('offset', offset);

    const res = await fetch(`${bridgeUrl}/proxy/signals?${params.toString()}`, {
      headers: { 'X-Bridge-Key': bridgeKey },
    });

    const data = await res.json();

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
