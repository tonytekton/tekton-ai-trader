export default function ImplementationPlan() {

  const phases = [
    { id: 1,  title: "Foundation — Bridge + Executor + Signal Schema",            status: "complete",     date: "2026-03-10", notes: "Three-tier architecture live. Signal schema standardised." },
    { id: 2,  title: "Strategy Framework + First Strategy (SMC)",                  status: "complete",     date: "2026-03-11", notes: "Tekton-SMC-v1 live. Systemd service pattern set." },
    { id: 3,  title: "Base44 UI — Dashboard + Signals + Executions",              status: "complete",     date: "2026-03-12", notes: "Reporting pages live. Bridge proxy endpoints established." },
    { id: 4,  title: "Risk Controls — Drawdown Limit + Session Exposure",          status: "complete",     date: "2026-03-13", notes: "Circuit breaker, session exposure cap, daily drawdown gate." },
    { id: 5,  title: "Volume Calculation Fix — Dynamic pip sizing",                status: "complete",     date: "2026-03-19", notes: "Removed hardcoded PIP_SIZE_MAP. Live contract specs from bridge. Centilot formula verified." },
    { id: 6,  title: "Multi-Strategy Rollout (6 additional strategies)",           status: "complete",     date: "2026-03-17", notes: "ICT-FVG, EPS, BRT, VR, SORB, RSID live with systemd services." },
    { id: 7,  title: "AI Position Management — aiPositionReview + AiIntervention", status: "complete",     date: "2026-03-17", notes: "Monitor calls aiPositionReview per position. HOLD/CLOSE/ADJUST_SL/ADJUST_TP/PARTIAL_CLOSE. AiIntervention entity logs all decisions." },
    { id: 8,  title: "Economic Calendar — Passive Display (CalendarStrip)",        status: "complete",     date: "2026-03-27", notes: "getEconomicCalendar fn deployed. CalendarStrip widget on Dashboard — next 24h events." },
    { id: 9,  title: "Economic Calendar — Active News Gating",                     status: "complete",     date: "2026-03-27", notes: "Bridge /calendar/gating endpoint. Per-pair currency filtering. 60-min blackout. Marks signals FAILED. news_filter_enabled toggle in settings." },
    { id: 10, title: "Analytics Page — Strategy Performance Attribution",          status: "complete",     date: "2026-03-27", notes: "Full Analytics page: Overview, League Table, Best Of, Confidence bands. getAnalytics v2 with quality_score ranking." },
    { id: 11, title: "Event-Driven Bridge (position_state{})",                     status: "complete",     date: "2026-03-25", notes: "position_state{} seeded at startup. Live push handler. /positions serves from state. SL/TP enrichment working." },
    { id: 12, title: "API Rate Monitor Widget — cTrader",                          status: "complete",     date: "2026-03-20", notes: "cTrader API Rate widget on Dashboard. calls/min vs 75/min limit, 5m/1h/24h totals, sparkbar, top endpoints." },
    { id: 13, title: "Signals FAILED Status Bug",                                  status: "complete",     date: "2026-03-25", notes: "Executor marks failed signals as FAILED not PENDING." },
    { id: 14, title: "Dashboard Fixes — Deduplication + SL/TP Display",           status: "complete",     date: "2026-03-20", notes: "Execution journal dedup. SL/TP enriched from position_state{} after ReconcileReq." },
    { id: 15, title: "Multi-Timeframe Signals + Metals/Indices",                   status: "complete",     date: "2026-03-25", notes: "All 7 strategies: LTF+HTF timeframes. 50 symbols incl. metals/indices." },
    { id: 16, title: "AI Strategy Recommendations + Audit Trail",                  status: "complete",     date: "2026-03-27", notes: "generateAnalyticsInsights fn (GPT-4o). AnalyticsRecommendation entity. Daily 09:00 KL schedule. Dashboard summary widget. AI Insights tab on Analytics page." },
    { id: "13.5", title: "Friday Flush — Time-Based Gating",                      status: "in_progress",  date: "2026-03-27", notes: "friday_flush toggle + time gate (16:00 UTC cutoff, close-all). Deployed. Awaiting next Friday verification." },
    { id: 17, title: "Market Hours Gate — All Services",                           status: "complete",     date: "2026-03-28", notes: "All 7 strategies + monitor idle Fri 16:00–Sun 22:00 UTC. is_market_open() in each strategy. Bridge candle sync gated. Daily automations changed to weekdays only." },
    { id: 18, title: "Strategy Toggle — Enable/Disable Without Restart",           status: "planned",      date: null,         notes: "strategies table in DB with enabled flag. Executor checks before processing. UI toggle per strategy. No restart needed." },
    { id: 19, title: "Partial Exits — TP1/TP2 Scaled Exit Logic",                 status: "planned",      date: null,         notes: "Add tp2_pips to signal schema (optional, null = legacy single-TP). Executor: close 50% at TP1, move SL to break-even, runner to TP2. Bridge: /trade/partial_close endpoint. Monitor PARTIAL_CLOSE wired up. Strategies set tp2_pips for higher-conviction setups." },
    { id: 20, title: "AI Credits Monitor — Dashboard Widget",                      status: "planned",      date: null,         notes: "Base44 AI credits widget on Dashboard. 75,000/month budget. Shows monthly, daily and per-automation burn rate. Gauge similar to cTrader API Rate widget." },
    { id: 21, title: "True P&L Win Rate — Execution Outcome Data",                status: "planned",      date: null,         notes: "Needs outcome enrichment (TP/SL hit or manual close). completion_rate currently = trade placed. Deferred until outcome data available." },
    { id: 22, title: "WhatsApp Trade Alerts — Per-Execution Notifications",        status: "planned",      date: null,         notes: "Send WhatsApp message on every execution: symbol, direction, entry, SL, TP, lots, strategy." },
    { id: 23, title: "Multi-User SaaS — Tenant Isolation",                        status: "future",       date: null,         notes: "Per-user strategies, settings, signal provider model. Stripe subscriptions. Tenant isolation required." },
  ];

  const statusConfig = {
    complete:     { label: "✅ Complete",     bg: "bg-green-50",   border: "border-green-200",  text: "text-green-700",  badge: "bg-green-100 text-green-700" },
    in_progress:  { label: "🔄 In Progress",  bg: "bg-amber-50",   border: "border-amber-200",  text: "text-amber-700",  badge: "bg-amber-100 text-amber-700" },
    planned:      { label: "📋 Planned",      bg: "bg-blue-50",    border: "border-blue-200",   text: "text-blue-700",   badge: "bg-blue-100 text-blue-700"   },
    future:       { label: "🔭 Future",       bg: "bg-slate-50",   border: "border-slate-200",  text: "text-slate-500",  badge: "bg-slate-100 text-slate-500" },
  };

  const counts = {
    complete:    phases.filter(p => p.status === 'complete').length,
    in_progress: phases.filter(p => p.status === 'in_progress').length,
    planned:     phases.filter(p => p.status === 'planned').length,
    future:      phases.filter(p => p.status === 'future').length,
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">🗺️ Implementation Plan</h1>
        <p className="text-slate-500 text-sm mt-1">Tekton AI Trader v4.9 — 2026-03-28</p>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {Object.entries(counts).map(([status, count]) => {
          const cfg = statusConfig[status];
          return (
            <div key={status} className={`${cfg.bg} border ${cfg.border} rounded-lg p-3 text-center`}>
              <div className={`text-2xl font-bold ${cfg.text}`}>{count}</div>
              <div className={`text-xs ${cfg.text} mt-1`}>{cfg.label}</div>
            </div>
          );
        })}
      </div>

      <div className="space-y-3">
        {phases.map(phase => {
          const cfg = statusConfig[phase.status];
          return (
            <div key={phase.id} className={`${cfg.bg} border ${cfg.border} rounded-lg p-4`}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-xs font-mono px-2 py-0.5 rounded ${cfg.badge}`}>
                      Phase {phase.id}
                    </span>
                    <span className={`font-semibold text-sm ${cfg.text}`}>{phase.title}</span>
                  </div>
                  {phase.notes && (
                    <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">{phase.notes}</p>
                  )}
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cfg.badge}`}>
                    {cfg.label}
                  </span>
                  {phase.date && (
                    <span className="text-xs text-slate-400">{phase.date}</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className={`${statusConfig.future.bg} border ${statusConfig.future.border} rounded-lg p-4`}>
        <h3 className="font-bold text-slate-700 mb-3">🔭 Future Enhancements (Deferred)</h3>
        <ul className="space-y-2 text-sm text-slate-600">
          {[
            "Dedicated Calendar page — full week view, filterable by currency/impact (CalendarStrip on Dashboard sufficient for now)",
            "Strategy code-level optimisation — requires strategy parameters stored in DB for AI to reference",
            "F40 (CAC 40) symbol fix — EUR-native index, no cross-rate conversion needed",
          ].map((item, i) => (
            <li key={i} className="flex gap-2 items-start">
              <span className="text-slate-400 shrink-0">—</span><span>{item}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
