import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });
    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');

    // Fetch stats and all signals in parallel to build strategies list
    const [statsRes, sigsRes] = await Promise.all([
      fetch(`${bridgeUrl}/proxy/signals/stats`, { headers: { 'X-Bridge-Key': bridgeKey } }),
      fetch(`${bridgeUrl}/proxy/signals`,       { headers: { 'X-Bridge-Key': bridgeKey } }),
    ]);
    const data = await statsRes.json();
    const sigsData = await sigsRes.json();

    // Extract unique strategies from signals
    const strategies = [...new Set(
      (sigsData.signals || [])
        .map(s => s.strategy)
        .filter(Boolean)
    )].sort();

    return Response.json({ ...data, strategies });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
