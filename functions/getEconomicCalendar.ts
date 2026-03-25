import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

/**
 * getEconomicCalendar
 * ───────────────────
 * Proxies GET /calendar/events from the Tekton bridge.
 * Returns upcoming medium + high impact events for the next 7 days.
 *
 * Response shape:
 * {
 *   data: [
 *     {
 *       id: number,
 *       event_date: string (ISO),
 *       currency: string,
 *       indicator_name: string,
 *       impact_level: "high" | "medium",
 *       source: string,
 *       minutes_until: number   // negative = past
 *     },
 *     ...
 *   ]
 * }
 */
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

    const res = await fetch(`${bridgeUrl}/calendar/events`, {
      headers: { 'X-Bridge-Key': bridgeKey },
    });

    if (!res.ok) {
      const text = await res.text();
      return Response.json({ error: `Bridge error: ${text}` }, { status: res.status });
    }

    const data = await res.json();
    return Response.json({ data: data.events ?? data });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
