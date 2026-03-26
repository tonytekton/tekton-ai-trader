import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');
    if (!bridgeUrl || !bridgeKey) return Response.json({ error: 'Bridge not configured' }, { status: 500 });
    const res = await fetch(`${bridgeUrl}/data/settings`, {
      headers: { 'X-Bridge-Key': bridgeKey }
    });
    if (!res.ok) return Response.json({ error: `Bridge error ${res.status}` }, { status: 502 });
    const data = await res.json();
    return Response.json(data);
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
