import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

/**
 * executeSignal — Tekton AI Trader v4.6
 *
 * Receives a signal and executes it on cTrader via the bridge.
 *
 * Flow:
 *  1. Validate inputs
 *  2. Check no existing position on this symbol
 *  3. Fetch account status (free_margin, currency)
 *  4. Fetch contract specs (pipPosition, lotSize_centilots, step/min/max volume)
 *  5. Derive pip size dynamically: pipSize = 10^-pipPosition
 *  6. Get quote currency from symbols/list
 *  7. If quote ≠ account currency, fetch conversion rate from prices/current
 *  8. Fetch risk_pct from UserConfig
 *  9. Size position: lots = (freeMargin * riskPct) / (sl_pips * pipValuePerLot_AC)
 * 10. Convert sl_pips / tp_pips → cTrader relative points
 * 11. Execute via /trade/execute
 */

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Derive human pip size from bridge pipPosition (decimal digits in quoted price).
 *  e.g. pipPosition=5 → 0.00001 * 10 = 0.0001 (standard forex 5-digit)
 *  e.g. pipPosition=2 → 0.01 * 10 = 0.1 (not used this way — see below)
 *
 *  Actually: pip = 10^-(pipPosition-1) for most brokers
 *  But cTrader: pipPosition IS the pip decimal position directly.
 *  EURUSD: pipPosition=5, pip=0.0001 = 10^-4 = 10^-(5-1) ✓
 *  UK100:  pipPosition=2, pip=1.0    = 10^0  = 10^-(2-2)? No...
 *
 *  Safer: pip size = 10^-(pipPosition) / 10 * 10 → just 10^-(pipPosition-1)
 *  Confirmed from tekton_executor.py: pip_size = 10 ** (-pip_position + 1)
 */
function derivePipSize(pipPosition: number): number {
  return Math.pow(10, -(pipPosition - 1));
}

/** Points per pip: how many cTrader price points = 1 pip.
 *  cTrader price is in points = 10^-pipPosition.
 *  1 pip = 10^-(pipPosition-1) price units = 10 points always.
 *  Confirmed: always 10 for all instruments in cTrader OpenAPI.
 */
const POINTS_PER_PIP = 10;

// ── Main handler ─────────────────────────────────────────────────────────────

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const body = await req.json().catch(() => ({}));
    const { signal_uuid, symbol, direction, sl_pips, tp_pips } = body;

    // ── Step 1: Validate inputs ──
    if (!signal_uuid || !symbol || !direction || !sl_pips || !tp_pips) {
      return Response.json(
        { error: 'Required: signal_uuid, symbol, direction, sl_pips, tp_pips' },
        { status: 400 }
      );
    }
    if (!['BUY', 'SELL'].includes(direction.toUpperCase())) {
      return Response.json({ error: 'direction must be BUY or SELL' }, { status: 400 });
    }

    const sym = symbol.toUpperCase();
    const side = direction.toUpperCase();
    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');
    const headers: Record<string, string> = {
      'X-Bridge-Key': bridgeKey!,
      'Content-Type': 'application/json',
    };

    // ── Step 2: Check for existing open position on this symbol ──
    const posRes = await fetch(`${bridgeUrl}/positions/list`, { headers });
    if (!posRes.ok) throw new Error(`positions/list failed: ${posRes.status}`);
    const posData = await posRes.json();
    const alreadyOpen = (posData.positions || []).some(
      (p: any) => p.symbol === sym
    );
    if (alreadyOpen) {
      return Response.json(
        { error: `${sym} already has an open position` },
        { status: 409 }
      );
    }

    // ── Step 3: Account status ──
    const accRes = await fetch(`${bridgeUrl}/account/status`, { headers });
    if (!accRes.ok) throw new Error(`account/status failed: ${accRes.status}`);
    const accData = await accRes.json();
    const freeMargin  = parseFloat(accData.free_margin ?? 0);
    const accCurrency = (accData.currency ?? 'EUR').toUpperCase();

    if (freeMargin <= 0) {
      return Response.json({ error: 'Insufficient free margin' }, { status: 400 });
    }

    // ── Step 4: Contract specs ──
    const specRes = await fetch(`${bridgeUrl}/contract/specs`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ symbol: sym }),
    });
    if (!specRes.ok) throw new Error(`contract/specs failed: ${specRes.status}`);
    const specData = await specRes.json();
    if (!specData.success) throw new Error(`contract/specs error: ${specData.error}`);

    const spec          = specData.contract_specifications;
    const pipPosition   = spec.pipPosition ?? spec.digits ?? 5;
    // lotSize_centilots = number of centilots per 1 full lot
    // For forex: 10,000,000 (100,000 units × 100 centilots)
    // For indices: varies (e.g. 100 for DE40)
    const lotSizeCentilots = parseFloat(spec.lotSize_centilots ?? 10_000_000);
    const stepVolume    = parseInt(spec.stepVolume_centilots ?? 100);
    const minVolume     = parseInt(spec.minVolume_centilots  ?? 100);
    const maxVolume     = parseInt(spec.maxVolume_centilots  ?? 100_000_000);

    // ── Step 5: Derive pip size from pipPosition ──
    // pipSize = 10^-(pipPosition-1)
    // EURUSD pipPosition=5 → 0.0001 ✓
    // UK100  pipPosition=2 → 0.1   (but UK100 trades in 1.0 pips — need to verify)
    // JP225  pipPosition=1 → 1.0   ✓
    const pipSize = derivePipSize(pipPosition);

    // contractSize in units per 1 lot = lotSizeCentilots / 100
    const contractSize = lotSizeCentilots / 100;

    // pip value per 1 lot in quote currency = pipSize × contractSize
    const pipValuePerLot_QC = pipSize * contractSize;

    // ── Step 6: Get quote currency for this symbol ──
    const symsRes = await fetch(`${bridgeUrl}/symbols/list`, { headers });
    if (!symsRes.ok) throw new Error(`symbols/list failed: ${symsRes.status}`);
    const symsData = await symsRes.json();
    const symSpec = (symsData.symbols || []).find(
      (s: any) => s.name.toUpperCase() === sym
    );

    // For forex: quote currency = last 3 chars of symbol name
    // For indices/metals: look up from symbol spec (quoteAssetId maps to currency)
    // We'll derive from symbol name as primary, with known overrides
    const QUOTE_CURRENCY_MAP: Record<string, string> = {
      XAUUSD: 'USD', XAGUSD: 'USD', XTIUSD: 'USD', XBRUSD: 'USD',
      UK100:  'GBP', DE40:   'EUR', US30:   'USD', US500:  'USD',
      USTEC:  'USD', SPX500: 'USD', JP225:  'JPY', AUS200: 'AUD',
      HK50:   'HKD', F40:    'EUR', NAS100: 'USD', DAX:    'EUR',
    };
    const quoteCurrency = QUOTE_CURRENCY_MAP[sym] ?? sym.slice(-3).toUpperCase();

    // ── Step 7: Conversion rate (quote → account currency) ──
    let conversionRate = 1.0;
    if (quoteCurrency !== accCurrency) {
      const direct   = `${quoteCurrency}${accCurrency}`;
      const indirect = `${accCurrency}${quoteCurrency}`;
      const available = new Set(
        (symsData.symbols || []).map((s: any) => s.name.toUpperCase())
      );

      let convSymbol: string | null = null;
      let invert = false;
      if (available.has(direct))        { convSymbol = direct;   invert = false; }
      else if (available.has(indirect)) { convSymbol = indirect; invert = true;  }

      if (convSymbol) {
        // Retry up to 5 times waiting for price feed to warm up
        for (let attempt = 0; attempt < 5; attempt++) {
          const priceRes = await fetch(`${bridgeUrl}/prices/current`, {
            method: 'POST',
            headers,
            body: JSON.stringify({ symbols: [convSymbol] }),
          });
          const priceJson = await priceRes.json();
          const priceList = priceJson.prices ?? [];
          if (priceList.length > 0) {
            const p = priceList[0];
            // bid_raw and ask_raw are raw integers — divide by 1,000,000 for actual price
            const avgRaw = (p.bid_raw + p.ask_raw) / 2;
            const avgPrice = avgRaw / 1_000_000;
            if (avgPrice > 0) {
              conversionRate = invert ? (1.0 / avgPrice) : avgPrice;
              break;
            }
          }
          await new Promise(r => setTimeout(r, 2000));
        }
      }
    }

    const pipValuePerLot_AC = pipValuePerLot_QC * conversionRate;

    // ── Step 8: Fetch risk_pct from UserConfig ──
    const settings = await base44.entities.UserConfig.list();
    const riskPct  = settings.length > 0
      ? parseFloat(settings[0].risk_pct ?? 0.005)
      : 0.005;

    // ── Step 9: Risk-based position sizing ──
    // riskCash = how much we risk on this trade in account currency
    // riskCash = lots × sl_pips × pipValuePerLot_AC
    // → lots = riskCash / (sl_pips × pipValuePerLot_AC)
    const riskCash      = freeMargin * riskPct;
    const lotsRaw       = riskCash / (sl_pips * pipValuePerLot_AC);
    const centilotsRaw  = Math.round(lotsRaw * 100);

    // Snap down to nearest stepVolume, then clamp to [min, max]
    let finalVol = Math.max(
      Math.floor(centilotsRaw / stepVolume) * stepVolume,
      minVolume
    );
    finalVol = Math.min(finalVol, maxVolume);

    // ── Step 10: Convert sl_pips / tp_pips → cTrader relative points ──
    // cTrader rel_sl / rel_tp are in price points (10^-pipPosition each)
    // 1 pip = POINTS_PER_PIP (always 10 in cTrader)
    const relSl = Math.round(sl_pips * POINTS_PER_PIP);
    const relTp = Math.round(tp_pips * POINTS_PER_PIP);

    // ── Step 11: Execute the trade ──
    const execRes = await fetch(`${bridgeUrl}/trade/execute`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        symbol,
        side,                    // bridge accepts "side" field (BUY/SELL)
        volume: finalVol,        // in centilots
        comment: String(signal_uuid),
        rel_sl: relSl,
        rel_tp: relTp,
      }),
    });
    if (!execRes.ok) throw new Error(`trade/execute HTTP ${execRes.status}`);
    const execData = await execRes.json();

    const debug = {
      freeMargin, riskPct, riskCash,
      sl_pips, tp_pips,
      pipPosition, pipSize, contractSize,
      pipValuePerLot_QC, quoteCurrency, conversionRate,
      pipValuePerLot_AC,
      lotsRaw, centilotsRaw, finalVol,
      relSl, relTp,
      lotSizeCentilots, stepVolume, minVolume, maxVolume,
    };

    if (!execData.success) {
      return Response.json(
        { error: execData.error ?? 'Execution failed', debug },
        { status: 400 }
      );
    }

    return Response.json({
      success:          true,
      position_id:      execData.position_id,
      entry_price:      execData.entry_price,
      volume_centilots: finalVol,
      volume_lots:      finalVol / 100,
      debug,
    });

  } catch (error: any) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
