/**
 * getAnalytics — Tekton Trading Hub v2
 * Phase 10/16 — Full strategy performance attribution
 *
 * Returns:
 *  summary, by_strategy, by_symbol (with completion rate),
 *  by_timeframe, confidence_buckets, daily_volume,
 *  by_day_of_week, by_session, strategy_league
 */

import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

const SESSIONS: Record<string, { label: string; start: number; end: number }> = {
  asian:   { label: 'Asian',          start: 0,  end: 8  },
  london:  { label: 'London',         start: 8,  end: 12 },
  overlap: { label: 'London/NY Overlap', start: 12, end: 16 },
  ny:      { label: 'New York',       start: 16, end: 21 },
  off:     { label: 'Off-Hours',      start: 21, end: 24 },
};

const DAYS = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];

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
    while (hasMore && offset < 20000) {
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
    type Stats = { total: number; completed: number; failed: number; sl_sum: number; tp_sum: number; rr_count: number; conf_sum: number; conf_count: number };
    const newStats = (): Stats => ({ total:0, completed:0, failed:0, sl_sum:0, tp_sum:0, rr_count:0, conf_sum:0, conf_count:0 });

    const stratMap:  Record<string, Stats> = {};
    const symbolMap: Record<string, Stats> = {};
    const tfMap:     Record<string, Stats> = {};
    const dayMap:    Record<string, Stats> = {};
    const sessMap:   Record<string, Stats> = {};
    const confBuckets: Record<string, { total: number; completed: number; sl_sum: number; tp_sum: number; rr_count: number }> = {
      '0-49':  { total:0, completed:0, sl_sum:0, tp_sum:0, rr_count:0 },
      '50-59': { total:0, completed:0, sl_sum:0, tp_sum:0, rr_count:0 },
      '60-69': { total:0, completed:0, sl_sum:0, tp_sum:0, rr_count:0 },
      '70-79': { total:0, completed:0, sl_sum:0, tp_sum:0, rr_count:0 },
      '80-89': { total:0, completed:0, sl_sum:0, tp_sum:0, rr_count:0 },
      '90-100':{ total:0, completed:0, sl_sum:0, tp_sum:0, rr_count:0 },
    };
    const dailyMap: Record<string, number> = {};

    let totalCompleted=0, totalFailed=0, totalConf=0, totalConfCount=0;

    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 30);
    const cutoffStr = cutoff.toISOString().substring(0,10);

    const addStats = (map: Record<string, Stats>, key: string, status: string, conf: number|null, sl: number|null, tp: number|null) => {
      if (!map[key]) map[key] = newStats();
      const s = map[key];
      s.total++;
      if (status === 'COMPLETED') s.completed++;
      if (status === 'FAILED')    s.failed++;
      if (conf !== null && !isNaN(conf)) { s.conf_sum += conf; s.conf_count++; }
      // Filter out corrupted pip values (pre-fix bad data)
      if (sl && tp && sl > 0 && sl < 1000) { s.sl_sum += sl; s.tp_sum += tp; s.rr_count++; }
    };

    for (const sig of allSignals) {
      const strat  = sig.strategy || 'Unknown';
      const status = sig.status   || '';
      const conf   = sig.confidence !== null && sig.confidence !== undefined ? parseInt(sig.confidence, 10) : null;
      const sl     = typeof sig.sl_pips === 'number' ? sig.sl_pips : null;
      const tp     = typeof sig.tp_pips === 'number' ? sig.tp_pips : null;
      const sym    = sig.symbol    || 'Unknown';
      const tf     = sig.timeframe || 'Unknown';

      addStats(stratMap,  strat,  status, conf, sl, tp);
      addStats(symbolMap, sym,    status, conf, sl, tp);
      addStats(tfMap,     tf,     status, conf, sl, tp);

      // Day of week + session from created_at (UTC)
      if (sig.created_at) {
        const dt = new Date(sig.created_at.replace(' ','T') + 'Z');
        const day = DAYS[dt.getUTCDay()];
        addStats(dayMap, day, status, conf, sl, tp);

        const hr = dt.getUTCHours();
        let sess = 'off';
        for (const [k, v] of Object.entries(SESSIONS)) {
          if (hr >= v.start && hr < v.end) { sess = k; break; }
        }
        addStats(sessMap, sess, status, conf, sl, tp);

        // Daily volume (last 30d)
        const day30 = sig.created_at.substring(0,10);
        if (day30 >= cutoffStr) dailyMap[day30] = (dailyMap[day30] || 0) + 1;
      }

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
        if (sl && tp && sl > 0 && sl < 1000) {
          confBuckets[bucket].sl_sum  += sl;
          confBuckets[bucket].tp_sum  += tp;
          confBuckets[bucket].rr_count++;
        }
      }

      if (status === 'COMPLETED') totalCompleted++;
      if (status === 'FAILED')    totalFailed++;
      if (conf !== null && !isNaN(conf)) { totalConf += conf; totalConfCount++; }
    }

    // ── Format helpers ───────────────────────────────────────────────────────
    const fmt = (s: Stats, key: string) => ({
      [key]:          key,
      total:          s.total,
      completed:      s.completed,
      failed:         s.failed,
      completion_rate: s.total > 0 ? +((s.completed/s.total)*100).toFixed(1) : 0,
      avg_confidence: s.conf_count > 0 ? +(s.conf_sum/s.conf_count).toFixed(1) : null,
      avg_sl:         s.rr_count > 0 ? +(s.sl_sum/s.rr_count).toFixed(1) : null,
      avg_tp:         s.rr_count > 0 ? +(s.tp_sum/s.rr_count).toFixed(1) : null,
      avg_rr:         s.rr_count > 0 ? +(s.tp_sum/s.sl_sum).toFixed(2)   : null,
    });

    // by_strategy
    const by_strategy = Object.entries(stratMap)
      .map(([k,v]) => fmt(v, 'strategy') as any)
      .map((r: any, _: number, __: any[]) => ({
        ...r,
        strategy: Object.keys(stratMap)[Object.values(stratMap).indexOf(Object.values(stratMap)[Object.keys(stratMap).indexOf(r.strategy)])],
      }));

    // Rebuild cleanly
    const by_strategy2 = Object.entries(stratMap).map(([strategy, s]) => ({
      strategy,
      total:           s.total,
      completed:       s.completed,
      failed:          s.failed,
      completion_rate: s.total > 0 ? +((s.completed/s.total)*100).toFixed(1) : 0,
      avg_confidence:  s.conf_count > 0 ? +(s.conf_sum/s.conf_count).toFixed(1) : null,
      avg_sl:          s.rr_count > 0 ? +(s.sl_sum/s.rr_count).toFixed(1) : null,
      avg_tp:          s.rr_count > 0 ? +(s.tp_sum/s.rr_count).toFixed(1) : null,
      avg_rr:          s.rr_count > 0 ? +(s.tp_sum/s.sl_sum).toFixed(2)   : null,
      quality_score:   (() => {
        const cr = s.total > 0 ? (s.completed/s.total) : 0;
        const rr = s.rr_count > 0 ? (s.tp_sum/s.sl_sum) : 0;
        return +(cr * rr).toFixed(3);
      })(),
    })).sort((a,b) => b.total - a.total);

    // Strategy league (ranked by quality_score)
    const strategy_league = [...by_strategy2].sort((a,b) => b.quality_score - a.quality_score)
      .map((s,i) => ({ rank: i+1, ...s }));

    // by_symbol (top 20, with completion rate)
    const by_symbol = Object.entries(symbolMap)
      .map(([symbol, s]) => ({
        symbol,
        total:           s.total,
        completed:       s.completed,
        completion_rate: s.total > 0 ? +((s.completed/s.total)*100).toFixed(1) : 0,
        avg_rr:          s.rr_count > 0 ? +(s.tp_sum/s.sl_sum).toFixed(2) : null,
      }))
      .filter(s => s.total >= 5)
      .sort((a,b) => b.completion_rate - a.completion_rate)
      .slice(0, 20);

    // by_timeframe
    const by_timeframe = Object.entries(tfMap).map(([timeframe, s]) => ({
      timeframe,
      total:           s.total,
      completed:       s.completed,
      completion_rate: s.total > 0 ? +((s.completed/s.total)*100).toFixed(1) : 0,
      avg_rr:          s.rr_count > 0 ? +(s.tp_sum/s.sl_sum).toFixed(2) : null,
    })).sort((a,b) => b.total - a.total);

    // by_day_of_week (Mon-Fri only, ordered)
    const dayOrder = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
    const by_day_of_week = dayOrder
      .filter(d => dayMap[d])
      .map(day => {
        const s = dayMap[day];
        return {
          day,
          total:           s.total,
          completed:       s.completed,
          completion_rate: s.total > 0 ? +((s.completed/s.total)*100).toFixed(1) : 0,
          avg_rr:          s.rr_count > 0 ? +(s.tp_sum/s.sl_sum).toFixed(2) : null,
        };
      });

    // by_session
    const sessOrder = ['asian','london','overlap','ny','off'];
    const by_session = sessOrder.filter(k => sessMap[k]).map(k => {
      const s = sessMap[k];
      return {
        session:         SESSIONS[k].label,
        total:           s.total,
        completed:       s.completed,
        completion_rate: s.total > 0 ? +((s.completed/s.total)*100).toFixed(1) : 0,
        avg_rr:          s.rr_count > 0 ? +(s.tp_sum/s.sl_sum).toFixed(2) : null,
      };
    });

    // confidence_buckets with avg_rr
    const confidence_buckets = Object.entries(confBuckets).map(([band, d]) => ({
      band,
      total:     d.total,
      completed: d.completed,
      win_rate:  d.total > 0 ? +((d.completed/d.total)*100).toFixed(1) : 0,
      avg_rr:    d.rr_count > 0 ? +(d.tp_sum/d.sl_sum).toFixed(2) : null,
    }));

    const daily_volume = Object.entries(dailyMap)
      .map(([date, count]) => ({ date, count }))
      .sort((a,b) => a.date.localeCompare(b.date));

    const total = allSignals.length;
    const summary = {
      total,
      completed:      totalCompleted,
      failed:         totalFailed,
      pending:        allSignals.filter(s => s.status === 'PENDING').length,
      win_rate:       total > 0 ? +((totalCompleted/total)*100).toFixed(1) : 0,
      avg_confidence: totalConfCount > 0 ? +(totalConf/totalConfCount).toFixed(1) : null,
      strategies:     by_strategy2.length,
      symbols:        Object.keys(symbolMap).length,
    };

    return Response.json({
      ok: true,
      summary,
      by_strategy: by_strategy2,
      strategy_league,
      by_symbol,
      by_timeframe,
      by_day_of_week,
      by_session,
      confidence_buckets,
      daily_volume,
    });

  } catch (error) {
    return Response.json({ error: (error as Error).message }, { status: 500 });
  }
});
