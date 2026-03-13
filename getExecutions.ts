import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');
    const headers = { 'X-Bridge-Key': bridgeKey, 'Content-Type': 'application/json' };

    // Fetch open positions and closed history in parallel
    const [openRes, closedRes] = await Promise.all([
      fetch(`${bridgeUrl}/positions/list`, { headers }),
      fetch(`${bridgeUrl}/positions/history`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ limit: 100 })
      })
    ]);

    const openData = openRes.ok ? await openRes.json() : { positions: [] };
    const closedData = closedRes.ok ? await closedRes.json() : { positions: [] };

    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    const extractUuid = (comment) => (comment && uuidRegex.test(comment.trim())) ? comment.trim() : null;

    // Normalize open positions
    // Note: /positions/list only returns summary fields (no volume, entry price, timestamps, comment)
    // Enrich open positions from history data (matched by positionId)
    const closedMap = {};
    (closedData.positions || []).forEach(p => { closedMap[p.positionId] = p; });

    const openPositions = (openData.positions || []).map(p => {
      const enriched = closedMap[p.positionId] || {};
      const digits = enriched.digits || p.digits || 5;
      return {
        position_id: p.positionId,
        id: p.positionId,
        symbol: p.symbol,
        side: p.tradeSide,
        volume: enriched.volume_centilots != null ? (enriched.volume_centilots / 10000000).toFixed(2) : null,
        entry_price: enriched.entryPrice_raw != null ? enriched.entryPrice_raw : null,
        close_price: null,
        pnl: p.unrealizedNetPnL_cents != null ? p.unrealizedNetPnL_cents / 100 : null,
        stop_loss: p.stop_loss ?? enriched.stop_loss ?? null,
        take_profit: p.take_profit ?? enriched.take_profit ?? null,
        digits,
        status: 'open',
        created_at: enriched.openTimestamp ? new Date(enriched.openTimestamp).toISOString() : null,
        closed_at: null,
        signal_uuid: extractUuid(enriched.comment)
      };
    });

    // Normalize closed positions
    const closedPositions = (closedData.positions || []).map(p => {
      const digits = p.digits || 5;
      return {
        position_id: p.positionId,
        id: p.positionId,
        symbol: p.symbol,
        side: p.tradeSide,
        volume: p.volume_centilots != null ? (p.volume_centilots / 10000000).toFixed(2) : null,
        entry_price: p.entryPrice_raw != null ? p.entryPrice_raw : null,
        close_price: p.exitPrice_raw != null ? p.exitPrice_raw : null,
        pnl: p.pnl != null ? p.pnl : null,
        stop_loss: p.stop_loss,
        take_profit: p.take_profit,
        digits,
        status: 'closed',
        created_at: p.openTimestamp ? new Date(p.openTimestamp).toISOString() : null,
        closed_at: p.closeTimestamp ? new Date(p.closeTimestamp).toISOString() : null,
        signal_uuid: extractUuid(p.comment)
      };
    });

    const executions = [...openPositions, ...closedPositions];

    return Response.json({ executions });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
