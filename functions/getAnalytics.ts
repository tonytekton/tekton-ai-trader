/**
 * getAnalytics — Tekton Trading Hub
 *
 * Queries the signals table directly via the bridge proxy
 * and computes per-strategy performance stats.
 *
 * Returns:
 *  - summary: overall totals (total, completed, failed, win_rate, avg_confidence)
 *  - by_strategy: array of { strategy, total, completed, failed, win_rate, avg_confidence, avg_sl, avg_tp, avg_rr }
 *  - by_symbol: top 15 symbols by total signals
 *  - by_timeframe: breakdown by timeframe
 *  - confidence_buckets: win rate grouped by confidence band (0-49, 50-59, 60-69, 70-79, 80-89, 90-100)
 *  - recent_signals: last 200 COMPLETED signals for scatter chart
 *  - daily_volume: signal count per day, last 30 days
 */

Deno.serve(async (req) => {
  try {
    const bridgeUrl = Deno.env.get('BRIDGE_URL') || 'http://localhost:8080';
    const bridgeKey = Deno.env.get('BRIDGE_KEY') || '';

    // Fetch all signals (up to 2000) from the bridge signals proxy
    // We'll page through to get a full picture
    const allSignals: any[] = [];
    const pageSize = 200;
    let offset = 0;
    let hasMore = true;

    while (hasMore && offset < 2000) {
      const res = await fetch(
        `${bridgeUrl}/proxy/signals/list?limit=${pageSize}&offset=${offset}`,
        { headers: { 'X-Bridge-Key': bridgeKey }, signal: AbortSignal.timeout(10000) }
      );
      if (!res.ok) break;
      const data = await res.json();
      const batch = data.signals || [];
      allSignals.push(...batch);
      hasMore = batch.length === pageSize;
      offset += pageSize;
    }

    // ── Per-strategy aggregation ─────────────────────────────────────────────
    const stratMap: Record<string, {
      total: number; completed: number; failed: number;
      conf_sum: number; conf_count: number;
      sl_sum: number; tp_sum: number; rr_count: number;
    }> = {};

    const symbolMap: Record<string, number> = {};
    const tfMap: Record<string, number> = {};
    const confBuckets: Record<string, { total: number; completed: number }> = {
      '0-49': { total: 0, completed: 0 },
      '50-59': { total: 0, completed: 0 },
      '60-69': { total: 0, completed: 0 },
      '70-79': { total: 0, completed: 0 },
      '80-89': { total: 0, completed: 0 },
      '90-100': { total: 0, completed: 0 },
    };

    // Daily volume — last 30 days
    const dailyMap: Record<string, number> = {};

    // Recent completed signals for scatter
    const recentCompleted: any[] = [];

    let totalCompleted = 0;
    let totalFailed = 0;
    let totalConf = 0;
    let totalConfCount = 0;

    for (const sig of allSignals) {
      const strat = sig.strategy || sig.direction || 'Unknown';
      const status = sig.status || '';
      const conf = typeof sig.confidence === 'number' ? sig.confidence : null;
      const sl = typeof sig.sl_pips === 'number' ? sig.sl_pips : null;
      const tp = typeof sig.tp_pips === 'number' ? sig.tp_pips : null;
      const sym = sig.symbol || 'Unknown';
      const tf = sig.timeframe || 'Unknown';

      // Strategy map
      if (!stratMap[strat]) {
        stratMap[strat] = { total: 0, completed: 0, failed: 0, conf_sum: 0, conf_count: 0, sl_sum: 0, tp_sum: 0, rr_count: 0 };
      }
      stratMap[strat].total++;
      if (status === 'COMPLETED') { stratMap[strat].completed++; totalCompleted++; }
      if (status === 'FAILED')    { stratMap[strat].failed++;    totalFailed++;    }
      if (conf !== null) {
        stratMap[strat].conf_sum   += conf;
        stratMap[strat].conf_count++;
        totalConf += conf;
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
      if (conf !== null) {
        let bucket = '0-49';
        if (conf >= 90) bucket = '90-100';
        else if (conf >= 80) bucket = '80-89';
        else if (conf >= 70) bucket = '70-79';
        else if (conf >= 60) bucket = '60-69';
        else if (conf >= 50) bucket = '50-59';
        confBuckets[bucket].total++;
        if (status === 'COMPLETED') confBuckets[bucket].completed++;
      }

      // Daily volume
      if (sig.created_at) {
        const day = sig.created_at.substring(0, 10);
        dailyMap[day] = (dailyMap[day] || 0) + 1;
      }

      // Recent completed for scatter (last 500)
      if (status === 'COMPLETED' && recentCompleted.length < 500) {
        recentCompleted.push({
          symbol:     sym,
          strategy:   strat,
          confidence: conf,
          sl_pips:    sl,
          tp_pips:    tp,
          rr:         (sl && tp && sl > 0) ? +(tp / sl).toFixed(2) : null,
          created_at: sig.created_at,
        });
      }
    }

    // ── Format by_strategy ───────────────────────────────────────────────────
    const by_strategy = Object.entries(stratMap)
      .map(([strategy, d]) => ({
        strategy,
        total:           d.total,
        completed:       d.completed,
        failed:          d.failed,
        win_rate:        d.total > 0 ? +((d.completed / d.total) * 100).toFixed(1) : 0,
        avg_confidence:  d.conf_count > 0 ? +(d.conf_sum / d.conf_count).toFixed(1) : null,
        avg_sl:          d.rr_count > 0 ? +(d.sl_sum / d.rr_count).toFixed(1) : null,
        avg_tp:          d.rr_count > 0 ? +(d.tp_sum / d.rr_count).toFixed(1) : null,
        avg_rr:          d.rr_count > 0 ? +((d.tp_sum / d.sl_sum)).toFixed(2) : null,
      }))
      .sort((a, b) => b.total - a.total);

    // ── Format by_symbol (top 15) ────────────────────────────────────────────
    const by_symbol = Object.entries(symbolMap)
      .map(([symbol, count]) => ({ symbol, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 15);

    // ── Format by_timeframe ──────────────────────────────────────────────────
    const by_timeframe = Object.entries(tfMap)
      .map(([timeframe, count]) => ({ timeframe, count }))
      .sort((a, b) => b.count - a.count);

    // ── Format confidence buckets ────────────────────────────────────────────
    const confidence_buckets = Object.entries(confBuckets).map(([band, d]) => ({
      band,
      total:     d.total,
      completed: d.completed,
      win_rate:  d.total > 0 ? +((d.completed / d.total) * 100).toFixed(1) : 0,
    }));

    // ── Format daily volume (last 30 days sorted) ────────────────────────────
    const daily_volume = Object.entries(dailyMap)
      .map(([date, count]) => ({ date, count }))
      .sort((a, b) => a.date.localeCompare(b.date))
      .slice(-30);

    // ── Summary ─────────────────────────────────────────────────────────────
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
      recent_signals: recentCompleted,
      daily_volume,
    });

  } catch (error) {
    return Response.json({ error: (error as Error).message }, { status: 500 });
  }
});
