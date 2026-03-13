import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

// ── Pip size map: matches strat_ict_fvg_v1.py exactly ──
// These are the "human" pip sizes in price terms.
const PIP_SIZE_MAP = {
  XAUUSD: 0.1,
  XAGUSD: 0.01,
  XTIUSD: 0.01,
  XBRUSD: 0.01,
  US30:   1.0,
  US500:  0.1,
  USTEC:  0.1,
  UK100:  1.0,
  DE40:   1.0,
  JP225:  1.0,
  AUS200: 1.0,
  HK50:   1.0,
  SPX500: 0.1,
};

// Quote currency for non-forex symbols (can't derive from symbol name)
const INDEX_QUOTE_MAP = {
  UK100:  'GBP',
  DE40:   'EUR',
  US30:   'USD',
  US500:  'USD',
  USTEC:  'USD',
  SPX500: 'USD',
  JP225:  'JPY',
  AUS200: 'AUD',
  HK50:   'HKD',
  XAUUSD: 'USD',
  XAGUSD: 'USD',
  XTIUSD: 'USD',
  XBRUSD: 'USD',
};

function getPipSize(symbol) {
  if (symbol in PIP_SIZE_MAP) return PIP_SIZE_MAP[symbol];
  if (symbol.endsWith('JPY')) return 0.01;
  return 0.0001; // standard forex
}

function getQuoteCurrency(symbol) {
  if (symbol in INDEX_QUOTE_MAP) return INDEX_QUOTE_MAP[symbol];
  return symbol.slice(-3).toUpperCase(); // forex: last 3 chars
}

// How many cTrader points = 1 pip for this symbol.
// cTrader uses points (1/10th of a pip for 5-digit forex, 1:1 for indices).
// pipPosition from contract specs = number of decimal digits in price.
// points-per-pip = pipSize / (10^-pipPosition)
// e.g. EURUSD: pipSize=0.0001, pipPosition=5 → 0.0001 / 0.00001 = 10 points/pip ✓
// e.g. UK100:  pipSize=1.0,    pipPosition=2 → 1.0 / 0.01 = 100 points/pip ✓
// e.g. JP225:  pipSize=1.0,    pipPosition=0 → 1.0 / 1.0 = 1 point/pip ✓
function pointsPerPip(pipSize, pipPosition) {
  return Math.round(pipSize / Math.pow(10, -pipPosition));
}

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const { signal_uuid, symbol, direction, sl_pips, tp_pips } = await req.json();

    if (!signal_uuid || !symbol || !direction || !sl_pips || !tp_pips) {
      return Response.json({ error: 'signal_uuid, symbol, direction, sl_pips and tp_pips are required' }, { status: 400 });
    }

    const bridgeUrl = Deno.env.get('BRIDGE_URL');
    const bridgeKey = Deno.env.get('BRIDGE_KEY');
    const headers = { 'X-Bridge-Key': bridgeKey, 'Content-Type': 'application/json' };

    // ── Step 1: Check for existing open position on this symbol ──
    const posRes = await fetch(`${bridgeUrl}/positions/list`, { headers });
    const posData = await posRes.json();
    const alreadyOpen = (posData.positions || []).some(p => p.symbol === symbol);
    if (alreadyOpen) {
      return Response.json({ error: `${symbol} already has an open position` }, { status: 409 });
    }

    // ── Step 2: Account status ──
    const accRes = await fetch(`${bridgeUrl}/account/status`, { headers });
    const accData = await accRes.json();
    const freeMargin  = parseFloat(accData.free_margin  || accData.equity || 0);
    const accCurrency = (accData.currency || 'EUR').toUpperCase();

    // ── Step 3: Contract specs ──
    const specRes = await fetch(`${bridgeUrl}/contract/specs`, {
      method: 'POST', headers,
      body: JSON.stringify({ symbol }),
    });
    const specData  = await specRes.json();
    const spec      = specData.contract_specifications || {};

    // pipPosition: decimal digits in quoted price (5 for EURUSD, 2 for UK100, 0 for JP225)
    const pipPosition  = spec.pipPosition ?? spec.digits ?? 5;
    // contractSize: units per 1 lot (100000 for forex, 1 for most indices, varies)
    const contractSize = parseFloat(spec.lotSize ?? spec.contractSize ?? 100_000);
    const stepVolume   = spec.stepVolume_centilots ?? 100;
    const minVolume    = spec.minVolume_centilots  ?? 100;
    const maxVolume    = spec.maxVolume_centilots  ?? 100_000_000; // broker max

    // ── Step 4: Get pip value in account currency ──
    // pip value per 1 lot = pipSize * contractSize (in quote currency)
    // then convert quote → account currency
    const pipSize           = getPipSize(symbol);
    const quoteCurrency     = getQuoteCurrency(symbol);
    const pipValuePerLot_QC = pipSize * contractSize; // in quote currency

    let conversionRate = 1.0;
    if (quoteCurrency !== accCurrency) {
      const direct   = `${quoteCurrency}${accCurrency}`;
      const indirect = `${accCurrency}${quoteCurrency}`;

      const symsRes  = await fetch(`${bridgeUrl}/symbols/list`, { headers });
      const symsData = await symsRes.json();
      const available = new Set((symsData.symbols || []).map(s => s.name.toUpperCase()));

      let convSymbol = null;
      let invert     = false;
      if (available.has(direct))   { convSymbol = direct;   invert = false; }
      else if (available.has(indirect)) { convSymbol = indirect; invert = true;  }

      if (convSymbol) {
        let avgPrice = 0;
        for (let attempt = 0; attempt < 5; attempt++) {
          const priceRes  = await fetch(`${bridgeUrl}/prices/current`, {
            method: 'POST', headers,
            body: JSON.stringify({ symbols: [convSymbol] }),
          });
          const priceJson = await priceRes.json();
          const priceList = priceJson.prices || [];
          if (priceList.length > 0) {
            const p  = priceList[0];
            avgPrice = (p.bid_raw + p.ask_raw) / 2 / 1_000_000;
            break;
          }
          await new Promise(r => setTimeout(r, 2000));
        }
        if (avgPrice > 0) {
          conversionRate = invert ? (1.0 / avgPrice) : avgPrice;
        }
      }
    }

    const pipValuePerLot_AC = pipValuePerLot_QC * conversionRate; // in account currency

    // ── Step 5: Fetch risk % from user config ──
    const settings = await base44.entities.UserConfig.list();
    const riskPct  = settings.length > 0 ? parseFloat(settings[0].risk_pct || 0.005) : 0.005;

    // ── Step 6: Risk-based position sizing ──
    // totalRiskCash = how much cash we're willing to lose on this trade
    // riskCash = lots * sl_pips * pipValuePerLot_AC
    // → lots = riskCash / (sl_pips * pipValuePerLot_AC)
    const totalRiskCash = freeMargin * riskPct;
    const lotsRaw       = totalRiskCash / (sl_pips * pipValuePerLot_AC);

    // Convert lots to centilots (1 lot = 100 centilots in cTrader API)
    const centilots_raw = Math.round(lotsRaw * 100);

    // Snap to nearest stepVolume, clamp to [min, max]
    let finalVol = Math.max(Math.floor(centilots_raw / stepVolume) * stepVolume, minVolume);
    finalVol     = Math.min(finalVol, maxVolume);

    // ── Step 7: Convert sl_pips / tp_pips → cTrader relative points ──
    // cTrader rel_sl/rel_tp are in price points (smallest price increment = 1 point)
    const ppp   = pointsPerPip(pipSize, pipPosition); // points per pip
    const relSl = Math.round(sl_pips * ppp);
    const relTp = Math.round(tp_pips * ppp);

    // ── Step 8: Execute the trade ──
    const execRes = await fetch(`${bridgeUrl}/trade/execute`, {
      method: 'POST', headers,
      body: JSON.stringify({
        symbol,
        side:    direction.toUpperCase(),
        volume:  finalVol,
        comment: String(signal_uuid),
        rel_sl:  relSl,
        rel_tp:  relTp,
      }),
    });

    const execData = await execRes.json();

    if (!execData.success) {
      // Mark the signal as FAILED so it doesn't get retried
      return Response.json({
        error:          execData.error || 'Execution failed',
        debug_sizing: {
          freeMargin, riskPct, totalRiskCash,
          sl_pips, pipValuePerLot_AC, lotsRaw,
          centilots_raw, finalVol, relSl, relTp,
          pipSize, pipPosition, contractSize, quoteCurrency,
          conversionRate, ppp,
        }
      }, { status: 400 });
    }

    return Response.json({
      success:          true,
      position_id:      execData.position_id,
      entry_price:      execData.entry_price,
      volume_centilots: finalVol,
      volume_lots:      finalVol / 100,
      debug_sizing: {
        freeMargin, riskPct, totalRiskCash,
        sl_pips, pipValuePerLot_AC, lotsRaw,
        centilots_raw, finalVol, relSl, relTp,
        pipSize, pipPosition, contractSize, quoteCurrency,
        conversionRate, ppp,
      },
    });

  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
});
