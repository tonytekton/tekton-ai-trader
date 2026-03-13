import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');
    const headers = { 'X-Bridge-Key': bridgeKey, 'Content-Type': 'application/json' };

    // 1. Get symbols list
    const symRes = await fetch(`${bridgeUrl}/symbols/list`, { headers });
    const symData = await symRes.json();
    const symbols = symData.symbols || [];
    const names = symbols.map(s => s.name);

    // 2. Try EURJPY price
    const eurjpyRes = await fetch(`${bridgeUrl}/prices/current`, {
      method: 'POST', headers, body: JSON.stringify({ symbols: ['EURJPY'] })
    });
    const eurjpyPrice = await eurjpyRes.json();

    // 3. Try JPYEUR price
    const jpyeurRes = await fetch(`${bridgeUrl}/prices/current`, {
      method: 'POST', headers, body: JSON.stringify({ symbols: ['JPYEUR'] })
    });
    const jpyeurPrice = await jpyeurRes.json();

    // 4. Try fetching prices for all JPY-related symbols
    const jpySymbols = names.filter(n => n.includes('JPY'));
    let jpyPrices = null;
    if (jpySymbols.length > 0) {
      const jpyRes = await fetch(`${bridgeUrl}/prices/current`, {
        method: 'POST', headers, body: JSON.stringify({ symbols: jpySymbols })
      });
      jpyPrices = await jpyRes.json();
    }

    return Response.json({
      total_symbols: names.length,
      all_symbols: names,
      jpy_symbols: jpySymbols,
      eurjpy_price_response: eurjpyPrice,
      jpyeur_price_response: jpyeurPrice,
      jpy_prices: jpyPrices
    });

  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
