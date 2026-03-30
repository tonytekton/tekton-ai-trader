export default function ImplementationPlan() {

  const phases = [
    { id: 1,  title: "Foundation — Bridge + Executor + Signal Schema",            status: "complete",     date: "2026-03-10", notes: "Three-tier architecture live. Signal schema set." },
    { id: 2,  title: "Strategy Framework + First Strategy (SMC)",                  status: "complete",     date: "2026-03-11", notes: "First strategy live. Systemd pattern set." },
    { id: 3,  title: "Base44 UI — Dashboard + Signals + Executions",              status: "complete",     date: "2026-03-12", notes: "Reporting pages + bridge proxy endpoints live." },
    { id: 4,  title: "Risk Controls — Drawdown Limit + Session Exposure",          status: "complete",     date: "2026-03-13", notes: "Circuit breaker, session exposure cap, drawdown gate." },
    { id: 5,  title: "Volume Calculation Fix — Dynamic pip sizing",                status: "complete",     date: "2026-03-19", notes: "Removed hardcoded PIP_SIZE_MAP. Live contract specs from bridge." },
    { id: 6,  title: "Multi-Strategy Rollout (6 additional strategies)",           status: "complete",     date: "2026-03-17", notes: "ICT-FVG, EPS, BRT, VR, SORB, RSID live." },
    { id: 7,  title: "AI Position Management — aiPositionReview + AiIntervention", status: "complete",     date: "2026-03-17", notes: "aiPositionReview fn built. AiIntervention entity logs all decisions. Not yet wired into monitor — see Phase 20." },
    { id: 8,  title: "Economic Calendar — Passive Display (CalendarStrip)",        status: "complete",     date: "2026-03-27", notes: "CalendarStrip widget on Dashboard. next 24h economic events." },
    { id: 9,  title: "Economic Calendar — Active News Gating",                     status: "complete",     date: "2026-03-27", notes: "Bridge /calendar/gating. Per-pair currency filter. 60-min blackout. Marks signals FAILED. news_filter_enabled toggle." },
    { id: 10, title: "Analytics Page — Strategy Performance Attribution",          status: "complete",     date: "2026-03-27", notes: "Analytics page: Overview, League Table, Best Of, Confidence. getAnalytics v2 with quality_score." },
    { id: 11, title: "Event-Driven Bridge (position_state{})",                     status: "complete",     date: "2026-03-25", notes: "position_state{} seeded at startup. Push handler live. All /positions serve from state." },
    { id: 12, title: "API Rate Monitor Widget — cTrader",                          status: "complete",     date: "2026-03-20", notes: "cTrader API Rate widget. calls/min vs 75/min, 5m/1h/24h totals, sparkbar." },
    { id: 13, title: "Signals FAILED Status Bug",                                  status: "complete",     date: "2026-03-25", notes: "Executor marks failed signals FAILED not PENDING." },
    { id: 14, title: "Dashboard Fixes — Deduplication + SL/TP Display",           status: "complete",     date: "2026-03-20", notes: "Execution journal dedup. SL/TP from position_state{}." },
    { id: 15, title: "Multi-Timeframe Signals + Metals/Indices",                   status: "complete",     date: "2026-03-25", notes: "All 7 strategies: LTF+HTF timeframes. 50 symbols." },
    { id: 16, title: "AI Strategy Recommendations + Audit Trail",                  status: "complete",     date: "2026-03-27", notes: "GPT-4o insights fn. AnalyticsRecommendation entity. Daily 09:00 KL. Dashboard widget + AI Insights tab." },
    { id: "13.5", title: "Friday Flush — Time-Based Gating",                      status: "in_progress",  date: "2026-03-27", notes: "friday_flush toggle + time gate (16:00 UTC cutoff, close-all). Deployed. Awaiting next Friday verification." },
    { id: 17, title: "Market Hours Gate — All Services",                           status: "complete",     date: "2026-03-28", notes: "All services idle Fri 16:00–Sun 22:00 UTC. is_market_open() gating throughout. Automations weekdays only." },
    { id: 18, title: "Strategy Toggle — Enable/Disable Without Restart",           status: "complete",     date: "2026-03-30", notes: "strategies table in DB. GET /strategies + POST /strategies/toggle bridge endpoints. Executor is_strategy_enabled() gate. Analytics page Strategy Controls tab with live toggles. No service restart required." },
    { id: 19, title: "Partial Exits — TP1/TP2 + Break-Even Protection",           status: "planned",      date: null,         notes: "tp2_pips in signal schema (null = single-TP legacy). Close partial_exit_pct% at partial_exit_r R. SL to BE. Runner to TP2. Bridge /trade/partial_close endpoint. Both values AI-learnable." },
    { id: 20, title: "AI Monitor Wiring — Phase-Aware Position Review",           status: "planned",      date: null,         notes: "Wire aiPositionReview into monitor per position. AI receives position_phase in context. Authority depends on state: full ADJUST_SL in OPEN, locked in TRAILING (OVERRIDE keyword only). AI logs suggested parameter refinements (partial_exit_r, trail_pips) for learning loop." },
    { id: 21, title: "Trailing Stops — Post Break-Even SL Trail",                 status: "planned",      date: null,         notes: "After BE: SL trails by trail_pips distance. Dynamic — AI sets per position. Locks profit, allows runners. Phase transitions: PARTIAL_DONE/BE_APPLIED → TRAILING." },
    { id: 22, title: "AI Credits Monitor — Dashboard Widget",                      status: "planned",      date: null,         notes: "AI credits widget. 75k/month budget. Monthly/daily/per-automation burn. Gauge like cTrader Rate." },
    { id: 23, title: "True P&L Win Rate — Execution Outcome Data",                status: "planned",      date: null,         notes: "Needs outcome enrichment (TP/SL hit or manual close). completion_rate = trade placed. Deferred until outcome data available." },
    { id: 24, title: "WhatsApp Trade Alerts — Per-Execution Notifications",        status: "planned",      date: null,         notes: "WhatsApp alert per execution: symbol, direction, entry, SL, TP, lots, strategy." },
    { id: 27, title: "Signal Staleness Gate — Max Age Filter",                    status: "complete",     date: "2026-03-30", notes: "is_signal_stale() in executor. Rejects PENDING signals older than max_signal_age_mins (default 5 min). Marks FAILED with reason STALE_SIGNAL. Deployed same session as Phase 18." },
    { id: 28, title: "Market Regime Filter — System-Level Chop Detection",        status: "planned",      date: null,         notes: "System-level (not per-strategy) gate in executor. Before accepting any signal, checks HTF structure for that symbol. If ranging/choppy: reject or require higher confidence_score threshold. Uses existing market_data. Targets >65% win rate by filtering low-probability environments." },
    { id: 29, title: "Strategy Performance Circuit Breaker",                      status: "planned",      date: null,         notes: "If a strategy's recent quality_score drops below threshold OR it hits N consecutive losses, automatically flag it for review and suspend new signals. Uses analytics data already computed. Prevents a degraded strategy from continuing to fire. Separate from account-level drawdown circuit breaker." },
    { id: 25, title: "Dynamic Risk Adjustment — Performance-Based Sizing",         status: "future",       date: null,         notes: "Reduce risk_pct after losing streaks, increase after winners. Needs streak tracking in executor + new DB fields. AI-learnable sizing. Builds on Phase 29 circuit breaker data." },
    { id: 26, title: "Multi-User SaaS — Tenant Isolation",                        status: "future",       date: null,         notes: "Per-user strategies + settings. Stripe subscriptions. Tenant isolation." },
    { id: 30, title: "AI Parameter Tuning Loop — Autonomous Optimisation",        status: "future",       date: null,         notes: "Phase 25 of state machine learning. AI suggestions with consistent positive outcome_r get auto-applied to signal schema. Per-strategy learned defaults stored in strategies table. Full audit trail: before/after + AI reasoning. Requires Phase 20 + 23 outcome data." },
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

  const successTarget = (
    <div className="bg-indigo-50 border border-indigo-200 rounded-lg p-4 mb-2">
      <h3 className="font-bold text-indigo-800 mb-2">🎯 Success Definition</h3>
      <p className="text-xs text-indigo-700 leading-relaxed">
        Tekton is not a strategy runner — it is a <strong>trading system</strong>. A system answers IF/THEN/WHEN, not just buy/sell.
        The market is 90% algorithmic. To compete, Tekton must think and adapt like an algorithm.
      </p>
      <div className="grid grid-cols-3 gap-3 mt-3">
        {[
          ["🎯 Min RR", "1.5–2.0 R", "Every signal must clear this before execution"],
          ["📈 Win Rate", "> 65%", "High-confidence entries only. Regime + staleness filters."],
          ["🧠 Learns", "Continuously", "AI tunes partial_exit_r, trail_pips, regime thresholds over time"],
        ].map(([icon, val, desc]) => (
          <div key={val} className="bg-white rounded border border-indigo-100 p-2 text-center">
            <div className="text-lg">{icon}</div>
            <div className="font-bold text-indigo-700 text-sm">{val}</div>
            <div className="text-xs text-slate-500 mt-0.5">{desc}</div>
          </div>
        ))}
      </div>
      <div className="mt-3 text-xs text-indigo-600 font-semibold">Three pillars of a system (not a strategy):</div>
      <div className="grid grid-cols-3 gap-2 mt-1">
        {[
          ["1. Momentum Detection", "Is the market trending or chopping? Regime filter gates all entries."],
          ["2. Conditional Entry", "IF setup valid THEN enter — multiple valid branches, not one fixed trigger."],
          ["3. Trade Management", "Partial exits → BE → trailing runner. AI owns parameters. State machine enforces authority."],
        ].map(([title, desc]) => (
          <div key={title} className="bg-indigo-100 rounded p-2">
            <div className="font-bold text-indigo-800 text-xs">{title}</div>
            <div className="text-xs text-indigo-600 mt-0.5">{desc}</div>
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-800">🗺️ Implementation Plan</h1>
        <p className="text-slate-500 text-sm mt-1">Tekton AI Trader v4.9 — 2026-03-28</p>
      </div>

      {successTarget}

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
            "Dedicated Calendar page — full week view, filterable by currency/impact level",
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
