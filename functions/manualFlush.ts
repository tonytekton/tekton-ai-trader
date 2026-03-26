import { base44 } from "../src/base44Client.ts";

/**
 * manualFlush — close all open positions via the bridge immediately.
 * Called by the Dashboard "Manual Flush" button.
 * Returns { flushed: N, failed: N, details: [...] }
 */
export default async function manualFlush(req: Request): Promise<Response> {
  const BRIDGE_URL = Deno.env.get("BRIDGE_URL") || "http://localhost:8080";
  const BRIDGE_KEY = Deno.env.get("BRIDGE_KEY") || "";
  const headers    = { "X-Bridge-Key": BRIDGE_KEY, "Content-Type": "application/json" };

  try {
    // 1. Fetch all open positions
    const posResp = await fetch(`${BRIDGE_URL}/positions/list`, { headers });
    if (!posResp.ok) {
      return Response.json({ error: `Bridge /positions/list returned ${posResp.status}` }, { status: 502 });
    }
    const posData   = await posResp.json();
    const positions = posData.positions ?? [];

    if (positions.length === 0) {
      return Response.json({ flushed: 0, failed: 0, details: [], message: "No open positions to close." });
    }

    // 2. Close each position
    let flushed = 0;
    let failed  = 0;
    const details: { symbol: string; position_id: string | number; status: string; error?: string }[] = [];

    for (const pos of positions) {
      const pid = pos.position_id ?? pos.id;
      const sym = pos.symbol ?? "?";
      if (!pid) { failed++; details.push({ symbol: sym, position_id: "?", status: "failed", error: "no position_id" }); continue; }

      try {
        const closeResp = await fetch(`${BRIDGE_URL}/trade/close`, {
          method: "POST",
          headers,
          body: JSON.stringify({ position_id: pid }),
        });
        if (closeResp.ok) {
          flushed++;
          details.push({ symbol: sym, position_id: pid, status: "closed" });
        } else {
          const txt = await closeResp.text();
          failed++;
          details.push({ symbol: sym, position_id: pid, status: "failed", error: txt.slice(0, 100) });
        }
      } catch (e) {
        failed++;
        details.push({ symbol: sym, position_id: pid, status: "failed", error: String(e) });
      }
    }

    return Response.json({ flushed, failed, details });

  } catch (e) {
    return Response.json({ error: String(e) }, { status: 500 });
  }
}
