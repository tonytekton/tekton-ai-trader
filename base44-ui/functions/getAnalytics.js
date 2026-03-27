/**
 * getAnalytics — Tekton Trading Hub
 * Phase 10/16 — Strategy performance attribution
 *
 * Pages through ALL signals via /proxy/signals and computes:
 *  - summary: totals, win_rate, avg_confidence
 *  - by_strategy: per-strategy breakdown
 *  - by_symbol: top 15 symbols
 *  - by_timeframe: breakdown by timeframe
 *  - confidence_buckets: win rate by confidence band
 *  - daily_volume: signal count per day, last 30 days
 */

import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const bridgeUrl = Deno.env.get('BRIDGE_URL') || 'http://localhost:8080';
    const bridgeKey = Deno.env.get('BRIDGE_KEY') || '';

    // ── Page through ALL signals ─────────────────────────────────────────────
    const allSignals: any[] = [];
    const pageSize = 500;
    let offset = 0;
    let hasMore = true;

    while (hasMore && offset < 10000) {
      const res = await fetch(
        `${bridgeUrl}/proxy/signals?limit=${pageSize}&offset=${offset}`,
        { headers: { 'X-Bridge-Key': bridgeKey }, signal: AbortSignal.timeout(15000) }
      );
      if (!res.ok) break;
      const data = await res.json();
      const batch: any[] = data.signals || [];
      allSignals.push(...batch);
      hasMore = batch.length === pageSize;
      offset += pageSize;
    }

    // ── Aggregation maps ─────────────────────────────────────────────────────
    type StratStats = {
      total: number; completed: number; failed: number;
      conf_sum: number; conf_count: number;
      sl_sum: number; tp_sum: number; rr_count: number;
    };
    const stratMap: Record<string, StratStats> = {};
    const symbolMap: Record<string, number> = {};
    const tfMap: Record<string, number> = {};
    const confBuckets: Record<string, { total: number; completed: number }> = {
      '0-49':  { total: 0, completed: 0 },
      '50-59': { total: 0, completed: 0 },
      '60-69': { total: 0, completed: 0 },
      '70-79': { total: 0, completed: 0 },
      '80-89': { total: 0, completed: 0 },
      '90-100':{ total: 0, completed: 0 },
    };
    const dailyMap: Record<string, number> = {};

    let totalCompleted = 0;
    let totalFailed = 0;
    let totalConf = 0;
    let totalConfCount = 0;

    // 30-day cutoff for daily volume chart
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 30);
    const cutoffStr = cutoff.toISOString().substring(0, 10);

    for (const sig of allSignals) {
      const strat  = sig.strategy || 'Unknown';
      const status = sig.status   || '';
      // confidence comes back as string from bridge — parse it
      const conf   = sig.confidence !== null && sig.confidence !== undefined
                       ? parseInt(sig.confidence as string, 10)
                       : null;
      const sl  = typeof sig.sl_pips === 'number' ? sig.sl_pips : null;
      const tp  = typeof sig.tp_pips === 'number' ? sig.tp_pips : null;
      const sym = sig.symbol    || 'Unknown';
      const tf  = sig.timeframe || 'Unknown';

      // Strategy map
      if (!stratMap[strat]) {
        stratMap[strat] = { total: 0, completed: 0, failed: 0, conf_sum: 0, conf_count: 0, sl_sum: 0, tp_sum: 0, rr_count: 0 };
      }
      stratMap[strat].total++;
      if (status === 'COMPLETED') { stratMap[strat].completed++; totalCompleted++; }
      if (status === 'FAILED')    { stratMap[strat].failed++;    totalFailed++;    }
      if (conf !== null && !isNaN(conf)) {
        stratMap[strat].conf_sum   += conf;
        stratMap[strat].conf_count++;
        totalConf      += conf;
        totalConfCount++;
      }
      if (sl && tp && sl > 0) {
        stratMap[strat].sl_sum += sl;
        stratMap[strat].tp_sum += tp;
        stratMap[strat].rr_count++;
      }

      // Symbol map
      symbolMap[sym] = (symbolMap[sym] || 0) + 1;

      // Timeframe map
      tfMap[tf] = (tfMap[tf] || 0) + 1;

      // Confidence buckets
      if (conf !== null && !isNaN(conf)) {
        let bucket = '0-49';
        if      (conf >= 90) bucket = '90-100';
        else if (conf >= 80) bucket = '80-89';
        else if (conf >= 70) bucket = '70-79';
        else if (conf >= 60) bucket = '60-69';
        else if (conf >= 50) bucket = '50-59';
        confBuckets[bucket].total++;
        if (status === 'COMPLETED') confBuckets[bucket].completed++;
      }

      // Daily volume — last 30 days only
      if (sig.created_at) {
        const day = (sig.created_at as string).substring(0, 10);
        if (day >= cutoffStr) {
          dailyMap[day] = (dailyMap[day] || 0) + 1;
        }
      }
    }

    // ── Format outputs ───────────────────────────────────────────────────────
    const by_strategy = Object.entries(stratMap)
      .map(([strategy, d]) => ({
        strategy,
        total:          d.total,
        completed:      d.completed,
        failed:         d.failed,
        win_rate:       d.total > 0 ? +((d.completed / d.total) * 100).toFixed(1) : 0,
        avg_confidence: d.conf_count > 0 ? +(d.conf_sum / d.conf_count).toFixed(1) : null,
        avg_sl:         d.rr_count > 0 ? +(d.sl_sum / d.rr_count).toFixed(1) : null,
        avg_tp:         d.rr_count > 0 ? +(d.tp_sum / d.rr_count).toFixed(1) : null,
        avg_rr:         d.rr_count > 0 ? +(d.tp_sum / d.sl_sum).toFixed(2)   : null,
      }))
      .sort((a, b) => b.total - a.total);

    const by_symbol = Object.entries(symbolMap)
      .map(([symbol, count]) => ({ symbol, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 15);

    const by_timeframe = Object.entries(tfMap)
      .map(([timeframe, count]) => ({ timeframe, count }))
      .sort((a, b) => b.count - a.count);

    const confidence_buckets = Object.entries(confBuckets).map(([band, d]) => ({
      band,
      total:     d.total,
      completed: d.completed,
      win_rate:  d.total > 0 ? +((d.completed / d.total) * 100).toFixed(1) : 0,
    }));

    const daily_volume = Object.entries(dailyMap)
      .map(([date, count]) => ({ date, count }))
      .sort((a, b) => a.date.localeCompare(b.date));

    const total = allSignals.length;
    const summary = {
      total,
      completed:      totalCompleted,
      failed:         totalFailed,
      pending:        allSignals.filter(s => s.status === 'PENDING').length,
      win_rate:       total > 0 ? +((totalCompleted / total) * 100).toFixed(1) : 0,
      avg_confidence: totalConfCount > 0 ? +(totalConf / totalConfCount).toFixed(1) : null,
      strategies:     by_strategy.length,
      symbols:        Object.keys(symbolMap).length,
    };

    return Response.json({
      ok: true,
      summary,
      by_strategy,
      by_symbol,
      by_timeframe,
      confidence_buckets,
      daily_volume,
    });

  } catch (error) {
    return Response.json({ error: (error as Error).message }, { status: 500 });
  }
});
