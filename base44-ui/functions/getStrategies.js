// getStrategies — Phase 18
// Proxies GET /strategies from the bridge
import { base44 } from "../base44-sdk/index.js";

const BRIDGE_URL  = Deno.env.get("BRIDGE_URL")  || "";
const BRIDGE_KEY  = Deno.env.get("BRIDGE_KEY")  || "";

export default async function handler(req) {
  try {
    const res = await fetch(`${BRIDGE_URL}/strategies`, {
      headers: { "X-Bridge-Key": BRIDGE_KEY }
    });
    const data = await res.json();
    return data;
  } catch (e) {
    return { success: false, error: e.message };
  }
}
