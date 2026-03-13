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

    // Bridge returns { success, signals: [...] }
    // Normalise to match what the Signals page expects
    const now = Date.now();
    const maxAgeMs = 30 * 60 * 1000; // 30 minutes

    const signals = (data.signals || [])
      .map(s => {
        const createdAt = new Date(s.created_at).getTime();
        const isOld = (now - createdAt) > maxAgeMs;
        const status = isOld && s.status === 'PENDING' ? 'EXPIRED' : (s.status || 'PENDING');
        return {
          signal_uuid: s.uuid,
          symbol:      s.symbol,
          direction:   s.direction,
          timeframe:   s.timeframe,
          confidence:  s.confidence,
          status,
          sl_pips:     s.sl_pips ?? null,
          tp_pips:     s.tp_pips ?? null,
          created_at:  s.created_at,
        };
      })
      .filter(s => s.status !== 'EXPIRED');

    return Response.json(signals);
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
