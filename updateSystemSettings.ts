import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const { field, value } = await req.json();

    const allowedFields = ['autoTrade', 'fridayFlush'];
    if (!allowedFields.includes(field)) {
      return Response.json({ error: 'Invalid field' }, { status: 400 });
    }

    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');

    const res = await fetch(`${bridgeUrl}/data/system-settings`, {
      method: 'POST',
      headers: { 'X-Bridge-Key': bridgeKey, 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: value }),
    });

    const data = await res.json();
    return Response.json({ data });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
