export default function ImplementationPlan() {

  const phases = [
    { id: 1,  title: "Foundation — Bridge + Executor + Signal Schema",       status: "complete", date: "2026-03-10", notes: "Core three-tier architecture live. Signal schema standardised." },
    { id: 2,  title: "Strategy Framework + First Strategy (SMC)",             status: "complete", date: "2026-03-11", notes: "Tekton-SMC-v1 live. Systemd service pattern established." },
    { id: 3,  title: "Base44 UI — Dashboard + Signals + Executions",         status: "complete", date: "2026-03-12", notes: "Core reporting pages live. Bridge proxy endpoints established." },
    { id: 4,  title: "Risk Controls — Drawdown Limit + Session Exposure",     status: "complete", date: "2026-03-13", notes: "Circuit breaker, session exposure cap, daily drawdown gate." },
    { id: 5,  title: "Volume Calculation Fix — Dynamic pip sizing",           status: "complete", date: "2026-03-19", notes: "Removed hardcoded PIP_SIZE_MAP. Live contract spec from bridge. Centilot formula verified." },
    { id: 6,  title: "Multi-Strategy Rollout (6 additional strategies)",      status: "complete", date: "2026-03-17", notes: "ICT-FVG, EPS, BRT, VR, SORB, RSID all live with systemd services." },
    { id: 7,  title: "AI Position Management — aiPositionReview + AiIntervention", status: "complete", date: "2026-03-17", notes: "Monitor calls aiPositionReview per position. HOLD/CLOSE/ADJUST_SL/ADJUST_TP/PARTIAL_CLOSE. AiIntervention entity logs all decisions." },
    { id: 8,  title: "Economic Calendar — Passive Display (CalendarStrip)",   status: "complete", date: "2026-03-27", notes: "getEconomicCalendar fn deployed. CalendarStrip widget on Dashboard showing next 24h events." },
    { id: 9,  title: "Economic Calendar — Active News Gating",                status: "complete", date: "2026-03-27", notes: "Bridge /calendar/gating endpoint. Per-pair filtering (event currency in symbol). 60-min blackout. Marks signals FAILED with reason. news_filter_enabled toggle in settings." },
    { id: 10, title: "Analytics Page — Strategy Performance Attribution",     status: "complete", date: "2026-03-27", notes: "Full Analytics page: Overview, League Table, Best Of (day/session/symbol/RR), Confidence analysis. getAnalytics v2 backend with quality_score ranking." },
    { id: 11, title: "Phase 11 — Event-Driven Bridge (position_state{})",    status: "complete", date: "2026-03-25", notes: "11a: position_state{} seeded at startup. 11b: Live event handler. 11c: /positions endpoints serve from state. 11d: Smoke tests + 3 bug fixes. SL/TP enrichment working." },
    { id: 12, title: "API Rate Monitor Widget — cTrader",                     status: "complete", date: "2026-03-20", notes: "cTrader API Rate widget on Dashboard. Shows calls/min vs 75/min limit, 5m/1h/24h totals, sparkbar, top endpoints." },
    { id: 13, title: "Signals FAILED Status Bug",                             status: "complete", date: "2026-03-25", notes: "Executor correctly marks failed signals as FAILED instead of leaving PENDING." },
    { id: 14, title: "Dashboard Fixes — Deduplication + SL/TP Display",      status: "complete", date: "2026-03-20", notes: "Execution journal deduplication. SL/TP enriched from position_state after ReconcileReq." },
    { id: 15, title: "Multi-Timeframe Signals + Metals/Indices",              status: "complete", date: "2026-03-25", notes: "All 7 strategies have LTF_TIMEFRAME + HTF_TIMEFRAME. 50 symbols including metals/indices. '60min' not '1H'." },
    { id: 16, title: "AI Strategy Recommendations + Audit Trail",             status: "complete", date: "2026-03-27", notes: "generateAnalyticsInsights fn (GPT-4o). AnalyticsRecommendation entity with status/outcome_notes for AI learning loop. Daily 09:00 KL auto-generation. Dashboard summary widget. AI Insights tab on Analytics page." },
    { id: "13.5", title: "Friday Flush — Time-Based Gating",                 status: "in_progress", date: "2026-03-27", notes: "friday_flush toggle in settings. Executor time gate logic added (16:00 UTC cutoff + close-all). Deployed to VM but full end-to-end verification pending next Friday." },
    { id: 17, title: "Strategy Toggle — Enable/Disable Without Restart",      status: "planned", date: null, notes: "strategies table in DB with enabled flag. Executor checks flag before processing signals. TradingSettings UI toggle panel per strategy. No service restart required." },
    { id: 18, title: "AI Credits Monitor — Dashboard Widget",                 status: "planned", date: null, notes: "Base44 AI integration credits monitor on Dashboard. 75,000/month budget. Daily budget = 900,000 (yearly) ÷ 260 working days = 3,461 credits/day. Shows monthly, daily and per-automation burn rate. Visual gauge similar to cTrader API Rate widget. Also shows message credits (monthly plan)." },
    { id: 19, title: "True P&L Win Rate — Execution Outcome Data",           status: "planned", date: null, notes: "Requires execution outcome enrichment (TP hit / SL hit / manual close). Currently completion_rate = trade was placed. True win rate deferred until outcome data available." },
    { id: 20, title: "Multi-User SaaS — Tenant Isolation",                   status: "future", date: null, notes: "Per-user strategies, settings, signal provider model. Stripe subscriptions. Architecture must support tenant isolation." },
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
        <p className="text-slate-500 text-sm mt-1">Tekton AI Trader v4.9 — Updated 2026-03-27</p>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {Object.entries(counts).map(([status, count]) => {
          const cfg = statusConfig[status];
          return (
            <div key={status} className={`rounded-xl border p-4 ${cfg.bg} ${cfg.border}`}>
              <div className={`text-2xl font-bold ${cfg.text}`}>{count}</div>
              <div className={`text-xs font-medium mt-0.5 ${cfg.text}`}>{cfg.label}</div>
            </div>
          );
        })}
      </div>

      <div>
        <div className="flex justify-between text-xs text-slate-500 mb-1">
          <span>Overall Progress</span>
          <span>{counts.complete}/{phases.length} phases complete</span>
        </div>
        <div className="h-3 bg-slate-200 rounded-full overflow-hidden">
          <div className="h-3 bg-gradient-to-r from-green-400 to-emerald-500 rounded-full transition-all"
            style={{ width: `${(counts.complete / phases.length) * 100}%` }} />
        </div>
      </div>

      <div className="space-y-3">
        {phases.map((phase) => {
          const cfg = statusConfig[phase.status];
          return (
            <div key={phase.id} className={`rounded-xl border p-4 ${cfg.bg} ${cfg.border}`}>
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <div className="text-xs font-mono font-bold text-slate-400 shrink-0 w-8 pt-0.5">
                    P{phase.id}
                  </div>
                  <div className="min-w-0">
                    <div className={`font-semibold ${cfg.text}`}>{phase.title}</div>
                    <div className="text-xs text-slate-500 mt-1 leading-relaxed">{phase.notes}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {phase.date && <span className="text-xs text-slate-400 font-mono">{phase.date}</span>}
                  <span className={`px-2 py-0.5 rounded text-xs font-bold ${cfg.badge}`}>{cfg.label}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="bg-white rounded-xl border border-slate-200 p-5">
        <h3 className="font-bold text-slate-700 mb-3">🔭 Future Enhancements (Deferred)</h3>
        <ul className="space-y-2 text-sm text-slate-600">
          {[
            "Dedicated Calendar page — full week view, filterable by currency/impact (CalendarStrip on Dashboard sufficient for now)",
            "Strategy code-level optimisation — requires strategy parameters stored in DB for AI to reference",
            "WhatsApp trade alerts — per-execution notifications",
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
