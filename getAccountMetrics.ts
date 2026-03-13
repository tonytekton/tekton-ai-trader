import { createClientFromRequest } from 'npm:@base44/sdk@0.8.6';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');

    const res = await fetch(`${bridgeUrl}/proxy/account-summary`, {
      headers: { 'X-Bridge-Key': bridgeKey },
    });

    if (!res.ok) {
      const text = await res.text();
      return Response.json({ error: `Bridge error: ${text}` }, { status: res.status });
    }

    const data = await res.json();
    return Response.json({ data });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
