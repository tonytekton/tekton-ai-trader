/**
 * generateAnalyticsInsights — Tekton Trading Hub
 * Phase 16 — AI-powered strategy recommendations with audit trail
 *
 * Called by: scheduled automation (daily 09:00 KL) or on-demand from Analytics page
 * Saves results to AnalyticsRecommendation entity for audit trail + AI learning
 */

import { createClientFromRequest, createServiceClient } from 'npm:@base44/sdk@0.8.20';

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const svc    = createServiceClient();

    // Auth check
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    const body = await req.json().catch(() => ({}));
    const trigger = body.trigger || 'on_demand';

    const bridgeUrl = Deno.env.get('BRIDGE_URL') || 'http://localhost:8080';
    const bridgeKey = Deno.env.get('BRIDGE_KEY') || '';
    const openaiKey = Deno.env.get('OPENAI_API_KEY') || '';

    // ── 1. Fetch analytics data ──────────────────────────────────────────────
    const analyticsRes = await fetch(
      `${bridgeUrl}/proxy/signals?limit=500&offset=0`,
      { headers: { 'X-Bridge-Key': bridgeKey }, signal: AbortSignal.timeout(15000) }
    );
    if (!analyticsRes.ok) throw new Error('Failed to fetch signals from bridge');

    // ── 2. Fetch current settings ────────────────────────────────────────────
    const settingsRes = await fetch(
      `${bridgeUrl}/data/settings`,
      { headers: { 'X-Bridge-Key': bridgeKey }, signal: AbortSignal.timeout(10000) }
    );
    const settingsData = settingsRes.ok ? await settingsRes.json() : {};
    const settings = settingsData.settings || settingsData || {};

    // ── 3. Fetch last 3 recommendations for learning context ────────────────
    const prevRecs = await svc.entities.AnalyticsRecommendation.filter(
      {}, { sort: '-created_date', limit: 3 }
    ).catch(() => []);

    // ── 4. Build full analytics summary (reuse getAnalytics logic inline) ────
    const allSignals: any[] = [];
    const pageSize = 500;
    let offset = 0;
    let hasMore = true;
    while (hasMore && offset < 20000) {
      const r = await fetch(
        `${bridgeUrl}/proxy/signals?limit=${pageSize}&offset=${offset}`,
        { headers: { 'X-Bridge-Key': bridgeKey }, signal: AbortSignal.timeout(15000) }
      );
      if (!r.ok) break;
      const d = await r.json();
      const batch = d.signals || [];
      allSignals.push(...batch);
      hasMore = batch.length === pageSize;
      offset += pageSize;
    }

    type Stats = { total:number; completed:number; failed:number; sl_sum:number; tp_sum:number; rr_count:number; conf_sum:number; conf_count:number };
    const newStats = (): Stats => ({total:0,completed:0,failed:0,sl_sum:0,tp_sum:0,rr_count:0,conf_sum:0,conf_count:0});
    const stratMap: Record<string,Stats> = {};
    const symbolMap: Record<string,Stats> = {};
    const dayMap: Record<string,Stats> = {};
    const sessMap: Record<string,Stats> = {};
    const DAYS = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
    const SESS: Record<string,{label:string;start:number;end:number}> = {
      asian:{label:'Asian',start:0,end:8},london:{label:'London',start:8,end:12},
      overlap:{label:'London/NY Overlap',start:12,end:16},ny:{label:'New York',start:16,end:21},off:{label:'Off-Hours',start:21,end:24}
    };
    const add = (map: Record<string,Stats>, key:string, status:string, conf:number|null, sl:number|null, tp:number|null) => {
      if (!map[key]) map[key]=newStats();
      const s=map[key]; s.total++;
      if(status==='COMPLETED')s.completed++;
      if(status==='FAILED')s.failed++;
      if(conf!==null&&!isNaN(conf)){s.conf_sum+=conf;s.conf_count++;}
      if(sl&&tp&&sl>0&&sl<1000){s.sl_sum+=sl;s.tp_sum+=tp;s.rr_count++;}
    };
    for (const sig of allSignals) {
      const strat=sig.strategy||'Unknown', status=sig.status||'';
      const conf=sig.confidence!==null&&sig.confidence!==undefined?parseInt(sig.confidence,10):null;
      const sl=typeof sig.sl_pips==='number'?sig.sl_pips:null;
      const tp=typeof sig.tp_pips==='number'?sig.tp_pips:null;
      add(stratMap,strat,status,conf,sl,tp);
      add(symbolMap,sig.symbol||'Unknown',status,conf,sl,tp);
      if(sig.created_at){
        const dt=new Date(sig.created_at.replace(' ','T')+'Z');
        add(dayMap,DAYS[dt.getUTCDay()],status,conf,sl,tp);
        const hr=dt.getUTCHours();
        let sess='off';
        for(const[k,v]of Object.entries(SESS)){if(hr>=v.start&&hr<v.end){sess=k;break;}}
        add(sessMap,sess,status,conf,sl,tp);
      }
    }

    const fmtStrat = (strategy:string, s:Stats) => ({
      strategy,
      total: s.total,
      completion_rate: s.total>0?+((s.completed/s.total)*100).toFixed(1):0,
      avg_rr: s.rr_count>0?+(s.tp_sum/s.sl_sum).toFixed(2):null,
      avg_confidence: s.conf_count>0?+(s.conf_sum/s.conf_count).toFixed(1):null,
      quality_score: +((s.total>0?s.completed/s.total:0)*(s.rr_count>0?s.tp_sum/s.sl_sum:0)).toFixed(3),
    });

    const stratSummary = Object.entries(stratMap).map(([k,v])=>fmtStrat(k,v)).sort((a,b)=>b.total-a.total);
    const bestDay = Object.entries(dayMap).map(([day,s])=>({day,completion_rate:s.total>0?+((s.completed/s.total)*100).toFixed(1):0,total:s.total})).sort((a,b)=>b.completion_rate-a.completion_rate)[0];
    const bestSess = Object.entries(sessMap).map(([k,s])=>({session:SESS[k]?.label||k,completion_rate:s.total>0?+((s.completed/s.total)*100).toFixed(1):0,total:s.total})).sort((a,b)=>b.completion_rate-a.completion_rate)[0];
    const topSymbols = Object.entries(symbolMap).filter(([,s])=>s.total>=10).map(([sym,s])=>({symbol:sym,completion_rate:s.total>0?+((s.completed/s.total)*100).toFixed(1):0,avg_rr:s.rr_count>0?+(s.tp_sum/s.sl_sum).toFixed(2):null})).sort((a,b)=>b.completion_rate-a.completion_rate).slice(0,5);

    const snapshot = {
      total_signals: allSignals.length,
      completion_rate: allSignals.length>0?+((allSignals.filter(s=>s.status==='COMPLETED').length/allSignals.length)*100).toFixed(1):0,
      strategies: stratSummary,
      best_day: bestDay,
      best_session: bestSess,
      top_symbols: topSymbols,
      current_settings: { risk_pct: settings.risk_pct, min_sl_pips: settings.min_sl_pips, max_lots: settings.max_lots, news_filter_enabled: settings.news_filter_enabled },
    };

    // ── 5. Previous recommendations context ─────────────────────────────────
    const prevContext = prevRecs.length > 0
      ? prevRecs.map((r: any, i: number) =>
          `Previous recommendation ${i+1} (${r.generated_at}, status: ${r.status}):\n${r.recommendations?.substring(0,500)}`
        ).join('\n\n')
      : 'No previous recommendations on record.';

    // ── 6. Build AI prompt ───────────────────────────────────────────────────
    const prompt = `You are a professional quantitative trading analyst reviewing an automated FX trading system called Tekton AI Trader.

## System Overview
- Multi-strategy automated FX trader running on cTrader
- Strategies fire signals; signals become trades if they pass filters (news gate, drawdown limit, session exposure, min SL, confidence threshold)
- "Completion rate" = signal was placed as a trade (NOT necessarily profitable — true P&L data deferred)
- "Quality score" = completion_rate × avg_rr (combined efficiency metric)
- Risk per trade: ${settings.risk_pct || '?'}% of account
- Min SL pips: ${settings.min_sl_pips || '?'}
- Max lots: ${settings.max_lots || '?'}
- News filter: ${settings.news_filter_enabled ? 'ENABLED' : 'DISABLED'}

## Current Performance Data
${JSON.stringify(snapshot, null, 2)}

## Previous Recommendations & Outcomes
${prevContext}

## Your Task
Provide a structured analysis with the following sections:

### 1. Executive Summary (3-4 sentences max)
Overall system health and the single most important thing to act on.

### 2. Strategy League Table Commentary
For each strategy, comment on: is it performing well, is it underperforming, should it be paused?
Note: Tekton-SMC-v1 dominates volume — is this healthy diversification?

### 3. Specific Strategy Improvement Recommendations
For each underperforming strategy (completion rate < 20% or quality score < 0.3):
- What parameter changes could improve it? (confidence threshold, SL/TP range, timeframe, symbols to focus on or exclude)
- Should it be paused until improved?

### 4. Best Trading Conditions
Based on the data — best day, best session, best symbols. Are we trading too broadly or should we focus?

### 5. Settings Recommendations
Based on current performance, should any global settings change?
(risk_pct, min_sl_pips, max_lots, news_filter)
Only recommend changes if data strongly supports it.

### 6. Learning from Previous Recommendations
Were previous recommendations applied? Did they work? What does this tell us?
(If no previous data, note this is the first recommendation.)

### 7. Priority Action List
Numbered list of top 5 actions in priority order. Be specific and actionable.

Keep the tone professional but direct. Be data-driven — cite specific numbers.`;

    // ── 7. Call OpenAI ───────────────────────────────────────────────────────
    let recommendations = '';
    let flaggedStrategies: string[] = [];
    let strategyImprovements: Record<string,any> = {};
    let settingsSuggestions: Record<string,any> = {};

    if (openaiKey) {
      const aiRes = await fetch('https://api.openai.com/v1/chat/completions', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${openaiKey}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'gpt-4o',
          messages: [{ role: 'user', content: prompt }],
          max_tokens: 2000,
          temperature: 0.3,
        }),
        signal: AbortSignal.timeout(30000),
      });
      if (aiRes.ok) {
        const aiData = await aiRes.json();
        recommendations = aiData.choices?.[0]?.message?.content || 'No response from AI';
      } else {
        const err = await aiRes.text();
        recommendations = `AI call failed: ${err.substring(0,200)}`;
      }
    } else {
      // Fallback: rule-based recommendations without OpenAI
      const underperforming = stratSummary.filter(s => s.completion_rate < 20 && s.total >= 20);
      const topStrat = stratSummary.sort((a,b) => b.quality_score - a.quality_score)[0];
      recommendations = `## Auto-Generated Analysis (rule-based fallback — no OpenAI key)\n\n`;
      recommendations += `**Executive Summary:** System has ${allSignals.length} total signals with ${snapshot.completion_rate}% completion rate. `;
      recommendations += `Top strategy by quality score: ${topStrat?.strategy} (${topStrat?.quality_score}).\n\n`;
      if (underperforming.length > 0) {
        recommendations += `**Underperforming strategies (< 20% completion):** ${underperforming.map(s=>`${s.strategy} (${s.completion_rate}%)`).join(', ')}.\n\n`;
      }
      recommendations += `**Best trading day:** ${bestDay?.day} (${bestDay?.completion_rate}% completion).\n`;
      recommendations += `**Best session:** ${bestSess?.session} (${bestSess?.completion_rate}% completion).\n\n`;
      recommendations += `**Top symbols:** ${topSymbols.slice(0,3).map(s=>`${s.symbol} ${s.completion_rate}%`).join(', ')}.\n`;
    }

    // Extract flagged strategies (low completion + enough data)
    flaggedStrategies = stratSummary
      .filter(s => s.completion_rate < 15 && s.total >= 30)
      .map(s => s.strategy);

    // Extract improvement suggestions per strategy
    stratSummary.forEach(s => {
      if (s.completion_rate < 20 && s.total >= 20) {
        strategyImprovements[s.strategy] = {
          current_completion_rate: s.completion_rate,
          current_avg_rr: s.avg_rr,
          current_avg_confidence: s.avg_confidence,
          suggestions: [
            s.avg_confidence && s.avg_confidence < 85 ? `Consider raising min confidence threshold to 85+` : null,
            s.avg_rr && s.avg_rr > 5 ? `High avg RR (${s.avg_rr}) suggests TP may be too ambitious — consider tightening` : null,
            s.avg_rr && s.avg_rr < 1.5 ? `RR below 1.5 minimum — review TP targets` : null,
          ].filter(Boolean),
        };
      }
    });

    // ── 8. Save to AnalyticsRecommendation entity ────────────────────────────
    const generatedAt = new Date().toISOString();
    const record = await svc.entities.AnalyticsRecommendation.create({
      generated_at:        generatedAt,
      trigger,
      signal_snapshot:     snapshot,
      recommendations,
      flagged_strategies:  flaggedStrategies,
      strategy_improvements: strategyImprovements,
      settings_suggestions: settingsSuggestions,
      status: 'new',
    });

    return Response.json({
      ok: true,
      generated_at:       generatedAt,
      recommendations,
      flagged_strategies: flaggedStrategies,
      strategy_improvements: strategyImprovements,
      record_id:          record.id,
    });

  } catch (error) {
    console.error('generateAnalyticsInsights error:', (error as Error).message);
    return Response.json({ error: (error as Error).message }, { status: 500 });
  }
});
