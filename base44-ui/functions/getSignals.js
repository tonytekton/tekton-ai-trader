import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });
    const body = await req.json().catch(() => ({}));
    const filterStatus    = body.status    || '';
    const filterSymbol    = body.symbol    || '';
    const filterStrategy  = body.strategy  || '';
    const filterDirection = body.direction || '';
    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');
    const res = await fetch(`${bridgeUrl}/proxy/signals`, { headers: { 'X-Bridge-Key': bridgeKey } });
    const data = await res.json();
    const now = Date.now();
    const maxAgeMs = 30 * 60 * 1000;
    let signals = (data.signals || []).map(s => {
      const createdAt = new Date(s.created_at).getTime();
      const isOld = (now - createdAt) > maxAgeMs;
      const status = isOld && s.status === 'PENDING' ? 'EXPIRED' : (s.status || 'PENDING');
      return { signal_uuid: s.uuid, symbol: s.symbol, direction: s.direction, timeframe: s.timeframe, confidence: s.confidence, strategy: s.strategy || null, status, sl_pips: s.sl_pips ?? null, tp_pips: s.tp_pips ?? null, created_at: s.created_at };
    });
    if (filterStatus)    signals = signals.filter(s => s.status === filterStatus);
    if (filterSymbol)    signals = signals.filter(s => s.symbol === filterSymbol);
    if (filterStrategy)  signals = signals.filter(s => s.strategy === filterStrategy);
    if (filterDirection) signals = signals.filter(s => s.direction === filterDirection);
    signals = signals.sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).slice(0, 200);
    return Response.json(signals);
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
