// toggleStrategy — Phase 18
// Proxies POST /strategies/toggle to the bridge
// Body: { name: string, enabled: boolean }

const BRIDGE_URL = Deno.env.get("BRIDGE_URL") || "";
const BRIDGE_KEY = Deno.env.get("BRIDGE_KEY") || "";

export default async function handler(req) {
  try {
    const { name, enabled } = req.body || {};
    if (!name) return { success: false, error: "name required" };
    const res = await fetch(`${BRIDGE_URL}/strategies/toggle`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Bridge-Key": BRIDGE_KEY
      },
      body: JSON.stringify({ name, enabled })
    });
    const data = await res.json();
    return data;
  } catch (e) {
    return { success: false, error: e.message };
  }
}
