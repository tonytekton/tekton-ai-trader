export default function SystemContext() {
  return (
    <div className="p-6 max-w-5xl mx-auto space-y-8 font-mono text-sm">

      <div>
        <h1 className="text-2xl font-bold text-slate-800">🧠 System Context & Developer Dossier</h1>
        <p className="text-slate-500 mt-1">Tekton AI Trader <span className="font-bold text-indigo-600">v4.9</span> — Last updated: 2026-03-28</p>
        <div className="mt-2 px-3 py-2 bg-red-50 border border-red-200 rounded text-red-700 text-xs font-bold">
          ⚠️ Read this entire document before making ANY changes to this system.
        </div>
      </div>

      {/* ARCHITECTURE */}
      <Section title="🏗️ System Architecture">
        <p className="text-slate-600 mb-3">Three-tier Python architecture on Google Cloud VM. Base44 UI is a <strong>read-only reporting skin</strong> — never contains trading logic.</p>
        <Table headers={["Service","File","Description","Restart"]} rows={[
          ["Bridge","tekton_bridge.py","REST-to-Protobuf gateway. Port 8080 / cTrader 5035. Event-driven position_state{}.","systemctl restart tekton-ai-trader-bridge.service"],
          ["Executor","tekton_executor.py","Risk orchestration. Polls PENDING signals. News gating. Time gating. Volume calc.","systemctl restart tekton-executor.service"],
          ["Monitor","tekton_monitor.py","Position management. Circuit breaker. Phase state machine. aiPositionReview wiring (Phase 20).","nohup python3 tekton_monitor.py >> monitor.log 2>&1 &"],
          ["Strategies","strat_*.py × 7","Independent signal generators. Each runs as its own systemd service.","systemctl restart tekton-strat-<name>.service"],
          ["Backfill","tekton_backfill.py","Fills market_data gaps. Cron every 15min.","cron: */15 * * * *"],
        ]} />
        <Code>{`# Full stack restart
bash /home/tony/tekton-ai-trader/start_tekton.sh`}</Code>
      </Section>

      {/* INFRASTRUCTURE */}
      <Section title="🌐 Infrastructure & Access">
        <Table headers={["","Value"]} rows={[
          ["Server","Google Cloud Compute Engine — tony@tekton-ai-trader"],
          ["Project Dir","/home/tony/tekton-ai-trader/"],
          ["DB Host","172.16.64.3 (internal)  |  DB: tekton-trader"],
          ["Bridge URL","BRIDGE_URL env var — internal: http://localhost:8080"],
          ["Bridge Auth","Header: X-Bridge-Key (BRIDGE_KEY env var)"],
          ["GitHub","https://github.com/tonytekton/tekton-ai-trader/ (public)"],
          ["Sessions Archive","https://github.com/tonytekton/tekton-sessions/"],
          ["Timezone","Asia/Kuala Lumpur (UTC+8)"],
          ["Python venv","/home/tony/tekton-ai-trader/venv/bin/python"],
        ]} />
        <Code>{`source ~/tekton-ai-trader/.env && PGPASSWORD=$CLOUD_SQL_DB_PASSWORD psql \\
  -h $CLOUD_SQL_HOST -U $CLOUD_SQL_DB_USER -d $CLOUD_SQL_DB_NAME -p \${CLOUD_SQL_PORT:-5432}`}</Code>
      </Section>

      {/* SIGNAL LIFECYCLE */}
      <Section title="🔄 Signal Lifecycle">
        <ol className="space-y-2 text-slate-700 text-xs list-none">
          {[
            "Strategy inserts PENDING signal → signals table (symbol, signal_type, sl_pips, tp_pips, confidence_score, strategy, timeframe, tp2_pips optional)",
            "Executor polls PENDING → checks: AUTO_TRADE, news gate (/calendar/gating), time gate (Friday cutoff), drawdown limit, session exposure, min_sl_pips, max_lots",
            "Executor calls Bridge POST /trade/execute with side, volume, rel_sl, rel_tp (pips float)",
            "Bridge converts rel_sl/rel_tp → integer points (pips × 10), sends ProtoOANewOrderReq to cTrader",
            "Bridge returns { success, position_id, entry_price }. Executor writes back to signals row. position_phase set to OPEN.",
            "Bridge receives ProtoOAExecutionEvent push → updates position_state{} in real time",
            "Monitor reads position_phase per position → runs state machine (OPEN→PARTIAL_DONE→BE_APPLIED→TRAILING→CLOSED)",
            "Monitor calls aiPositionReview (Phase 20) — authority depends on current phase (see Trade Management section)",
            "Circuit breaker: drawdown > limit → close all → drawdownAutopsy → freeze trading",
            "Base44 UI reads via /proxy/executions, /proxy/signals, /data/settings — read-only",
          ].map((s, i) => (
            <li key={i} className="flex gap-2"><span className="text-indigo-500 font-bold shrink-0">{i+1}.</span><span>{s}</span></li>
          ))}
        </ol>
      </Section>

      {/* SIGNAL SCHEMA */}
      <Section title="📋 Standard Signal Schema">
        <Code>{`{
  "signal_uuid":      "AUTO_GENERATED_BY_DB",
  "symbol":           "EURUSD",
  "strategy":         "Tekton-ICT-FVG-v1",
  "signal_type":      "BUY",           // NOT 'direction'
  "timeframe":        "15min",          // 5min | 15min | 60min | 4H | Daily
  "confidence_score": 82,               // INTEGER 0-100, NOT decimal
  "sl_pips":          15.0,             // REQUIRED — never NULL
  "tp_pips":          27.0,             // REQUIRED — never NULL (TP1 / single-TP)
  "tp2_pips":         45.0,             // OPTIONAL — set for partial-exit path (Phase 19+)
  "status":           "PENDING",
  "position_phase":   "OPEN"            // AUTO — managed by monitor state machine
}`}</Code>
        <div className="mt-2 text-xs text-red-600 font-bold">⚠️ NULL sl_pips or tp_pips = skipped by executor. confidence_score must be INTEGER. "1H" does not exist — use "60min". tp2_pips = NULL means legacy single-TP mode.</div>
      </Section>

      {/* TRADE MANAGEMENT — NEW SECTION */}
      <Section title="🎛️ Trade Management — Position State Machine">
        <p className="text-xs text-slate-600 mb-3">The monitor enforces a one-way state machine per position. Each state controls which systems have authority to act. All parameters are AI-learnable over time — settings hold defaults, signals hold per-trade overrides.</p>
        <Table headers={["State","Trigger","Partial Close","Move SL","Trail SL","AI ADJUST_SL","AI CLOSE"]} rows={[
          ["OPEN","Entry","✅ at partial_exit_r","✅ at 50% TP dist","❌","✅ full authority","✅"],
          ["PARTIAL_DONE","50% closed, SL at BE","❌ done","❌ done","✅ activates","❌ locked","✅ remaining %"],
          ["BE_APPLIED","SL at entry (single-TP)","❌","❌ done","✅ activates","❌ locked","✅"],
          ["TRAILING","SL trailing price","❌","❌","✅ owns SL","⚠️ OVERRIDE only","✅"],
          ["CLOSED","Terminal","❌","❌","❌","❌","❌"],
        ]} />
        <div className="mt-3 text-xs text-slate-600 font-bold mb-1">Configurable parameters (settings defaults + per-signal AI overrides):</div>
        <Table headers={["Parameter","Default","Notes"]} rows={[
          ["partial_exit_r","1.0","R level to trigger partial close. AI learns optimal value per strategy."],
          ["partial_exit_pct","50%","How much to close at TP1. AI can adjust."],
          ["trail_pips","10.0","Trail distance after BE. AI sets dynamically per position."],
          ["trail_enabled","TRUE","Global toggle"],
          ["partial_enabled","TRUE","Global toggle"],
        ]} />
        <div className="mt-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">⚠️ TRAILING override rule: AI can write ADJUST_SL only if reasoning contains keyword "OVERRIDE". Prevents accidental SL interference while allowing black-swan intervention.</div>
      </Section>

      {/* PRICE FORMATS */}
      <Section title="💱 cTrader Price Formats (most common bug source)">
        <Table headers={["Format","Type","Used In"]} rows={[
          ["RAW INTEGER","int ÷ 10^digits = decimal","ProtoOADeal.executionPrice, candles, stopLoss/takeProfit on positions"],
          ["DECIMAL DOUBLE","Use as-is","ProtoOAOrder.executionPrice, AmendSLTPReq, bridge execute response entry_price"],
        ]} />
        <div className="mt-3 font-bold text-slate-700 text-xs mb-1">relativeStopLoss / relativeTakeProfit — DEFINITIVE RULE:</div>
        <Table headers={["Layer","Format","Example (15 pip SL)"]} rows={[
          ["Signal in DB","sl_pips float","15.0"],
          ["Executor → Bridge (rel_sl)","PIPS float 1dp","15.0"],
          ["Bridge → cTrader protobuf","INTEGER POINTS = int(round(pips × 10))","150"],
        ]} />
        <div className="mt-2 text-xs text-red-600">relativeStopLoss is int32 — NEVER send float. Always use HasField() for optional protobuf fields.</div>
      </Section>

      {/* SETTINGS */}
      <Section title="⚙️ Settings Architecture">
        <p className="text-xs text-slate-600 mb-2">All settings live in SQL <code className="bg-slate-100 px-1 rounded">settings</code> table (row id=1). Base44 entities DEPRECATED.</p>
        <Table headers={["Field","Current Value","Notes"]} rows={[
          ["auto_trade","FALSE","Master kill switch"],
          ["friday_flush","TRUE","Closes all at 16:00 UTC Friday"],
          ["risk_pct","0.01","1% per trade — fixed until Phase 25 Dynamic Risk"],
          ["target_reward","1.8","Min RR before executor approves"],
          ["daily_drawdown_limit","0.05","5% — circuit breaker threshold"],
          ["max_session_exposure_pct","4.0","Blocks new trades when reached"],
          ["max_lots","6","Testing cap (default 5000 for live)"],
          ["min_sl_pips","8","Rejects signals below this SL"],
          ["news_blackout_mins","60","Window around high-impact events"],
          ["news_filter_enabled","TRUE","Enables Phase 9 news gating"],
          ["partial_exit_r","1.0","R trigger for partial close (Phase 19+)"],
          ["partial_exit_pct","50.0","% to close at TP1 (Phase 19+)"],
          ["trail_pips","10.0","Trail distance after BE (Phase 21+)"],
          ["trail_enabled","TRUE","Global trailing stop toggle (Phase 21+)"],
          ["partial_enabled","TRUE","Global partial exit toggle (Phase 19+)"],
        ]} />
        <p className="text-xs text-slate-500 mt-2">Write path: UI → POST bridge /data/settings → SQL. Read path: bridge /data/settings (GET).</p>
      </Section>

      {/* ANALYTICS & AI */}
      <Section title="📊 Analytics & AI Systems">
        <Table headers={["Component","Description"]} rows={[
          ["getAnalytics","Backend fn — strategy league, day/session/symbol/confidence breakdowns. quality_score = completion_rate × avg_rr"],
          ["generateAnalyticsInsights","Backend fn — GPT-4o analysis. Saves to AnalyticsRecommendation entity. Runs daily 09:00 KL (weekdays)."],
          ["AnalyticsRecommendation","Base44 entity — AI strategy audit trail with status (new/reviewed/applied/dismissed) + outcome_notes"],
          ["aiPositionReview","Backend fn — per-position AI review. Actions: HOLD/CLOSE/ADJUST_SL/ADJUST_TP/PARTIAL_CLOSE. Phase-aware (Phase 20)."],
          ["AiIntervention","Base44 entity — logs every AI position decision with reasoning, outcome, outcome_r"],
          ["drawdownAutopsy","Backend fn — forensic circuit breaker analysis. Saves to DrawdownAutopsy entity"],
        ]} />
        <div className="mt-2 text-xs text-slate-500">AI learning loop: all parameters (partial_exit_r, partial_exit_pct, trail_pips) are logged per decision. AI suggests refinements in reasoning field. Phase 25 enables auto-application of consistent winners.</div>
      </Section>

      {/* STRATEGIES */}
      <Section title="🎯 Active Strategies">
        <Table headers={["Name","File","Timeframes","Notes"]} rows={[
          ["Tekton-SMC-v1","strat_lester_v1.py","15min HTF: 60min","Structure & liquidity"],
          ["Tekton-ICT-FVG-v1","strat_ict_fvg_v1.py","15min HTF: 60min","Fair value gaps"],
          ["Tekton-EPS-v1","strat_ema_pullback_v1.py","15min HTF: 4H","EMA pullback trend-following"],
          ["Tekton-BRT-v1","strat_breakout_retest_v1.py","15min HTF: 60min","Breakout retest"],
          ["Tekton-VR-v1","strat_vwap_reversion_v1.py","15min HTF: 60min","VWAP reversion"],
          ["Tekton-SORB-v1","strat_session_orb_v1.py","15min HTF: Daily","Session opening range"],
          ["Tekton-RSID-v1","strat_rsi_divergence_v1.py","15min HTF: 60min","RSI divergence"],
        ]} />
        <p className="text-xs text-slate-500 mt-2">Strategy enable/disable: <strong>Phase 18 — strategies table in DB with enabled flag. No service restart required.</strong></p>
      </Section>

      {/* GATE PROTOCOL */}
      <Section title="🔐 Gate Protocol">
        <ol className="space-y-1 text-xs text-slate-700 list-none">
          {["Tony brings question/change to Lester","Lester discusses options, pros/cons, risks — no touching anything","Tony and Lester agree on exact approach","Lester produces code/change","Tony takes to VM or Base44 editor","Tony reports back — Lester verifies"].map((s,i) => (
            <li key={i} className="flex gap-2"><span className="text-indigo-500 font-bold">{i+1}.</span><span>{s}</span></li>
          ))}
        </ol>
      </Section>

      {/* CHANGE LOG */}
      <Section title="📝 Change Log">
        <div className="space-y-2 text-xs">
          {[
            ["2026-03-28","v4.9","Position State Machine designed (Phases 19/20/21). All 6 trade management features mapped to roadmap. Phase 17 (Market Hours Gate) complete — all services idle Fri 16:00–Sun 22:00 UTC. ICT FVG renamed Tekton-FVG-v1. Automations weekdays only."],
            ["2026-03-27","v4.9","Phase 8/9: Economic Calendar gating. Phase 10/16: Analytics + AI insights. generateAnalyticsInsights fn. Dashboard AI recommendations widget."],
            ["2026-03-26","v4.8.1","Phase 11d smoke tests. Friday Flush logic. loadAllSettings/saveAllSettings fns. TradingSettings persistence fixed."],
            ["2026-03-25","v4.8","Phase 11 complete (11a-11d). Multi-timeframe signals (all 7 strategies). Phase 15 complete."],
            ["2026-03-20","v4.7","Execution journal deduplication. SL/TP display fix. 6-lot cap. relativeStopLoss int32 fix."],
            ["2026-03-17","v4.6","AI Position Management (AiIntervention + aiPositionReview). Drawdown Autopsy. EPS strategy."],
          ].map(([date, ver, note]) => (
            <div key={date} className="border-l-2 border-indigo-200 pl-3">
              <span className="font-bold text-slate-700">{date}</span>
              <span className="ml-2 px-1 bg-indigo-100 text-indigo-600 rounded text-xs">{ver}</span>
              <p className="text-slate-500 mt-0.5">{note}</p>
            </div>
          ))}
        </div>
      </Section>

    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
      <h2 className="font-bold text-slate-800 mb-3 text-base border-b border-slate-100 pb-2">{title}</h2>
      {children}
    </div>
  );
}

function Table({ headers, rows }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-200">
            {headers.map(h => <th key={h} className="text-left py-1.5 pr-4 text-slate-500 font-semibold uppercase tracking-wide">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
              {row.map((cell, j) => <td key={j} className="py-1.5 pr-4 text-slate-700 align-top">{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Code({ children }) {
  return (
    <pre className="mt-2 bg-slate-900 text-green-400 rounded-lg p-3 text-xs overflow-x-auto leading-relaxed">{children}</pre>
  );
}
