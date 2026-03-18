import React, { useState, useEffect } from 'react';
import { base44 } from '@/api/base44Client';
import {
  ClipboardList, CheckCircle, Circle, Clock, AlertTriangle,
  ChevronDown, ChevronRight, RefreshCw, Save
} from 'lucide-react';

const PHASES = [
  {
    id: 'p1', title: 'Phase 1 — Bridge: New Endpoints', color: 'blue',
    desc: 'Add GET /data/settings and POST /data/settings to tekton_bridge.py.',
    tasks: [
      { id: 't1_1', title: 'Add GET /data/settings to tekton_bridge.py', detail: 'Query settings table WHERE id=1, return all columns as JSON', file: 'tekton_bridge.py' },
      { id: 't1_2', title: 'Add POST /data/settings to tekton_bridge.py', detail: 'Accept JSON body with any subset of settings fields, UPDATE settings SET ... WHERE id=1', file: 'tekton_bridge.py' },
      { id: 't1_3', title: 'Ensure settings table row id=1 exists in DB', detail: 'INSERT INTO settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING', file: 'PostgreSQL (tekton-trader DB)' },
      { id: 't1_4', title: 'Test GET /data/settings via curl', detail: "curl -H 'X-Bridge-Key: <key>' http://localhost:8080/data/settings", file: 'Terminal' },
      { id: 't1_5', title: 'Test POST /data/settings via curl', detail: "curl -X POST -H 'X-Bridge-Key: <key>' -d '{\"auto_trade\": true}' http://localhost:8080/data/settings", file: 'Terminal' },
    ],
  },
  {
    id: 'p2', title: 'Phase 2 — Executor: Read Settings from SQL', color: 'purple',
    desc: 'Patch tekton_executor.py so all config is read from the SQL settings table.',
    tasks: [
      { id: 't2_1', title: 'Add fetch_settings() to tekton_executor.py', detail: 'Uses psycopg2 to run SELECT * FROM settings WHERE id=1', file: 'tekton_executor.py' },
      { id: 't2_2', title: 'Gate poll_signals() on AUTO_TRADE toggle', detail: 'Before processing any PENDING signal: check auto_trade from settings', file: 'tekton_executor.py' },
      { id: 't2_3', title: "Replace hardcoded risk_pct with settings['risk_pct']", detail: 'Replace all literals with fetch_settings() lookup', file: 'tekton_executor.py' },
      { id: 't2_4', title: 'Remove Base44 getBase64Config HTTP call from executor', detail: 'All config is local SQL now', file: 'tekton_executor.py' },
      { id: 't2_5', title: 'Test executor with AUTO_TRADE = false in DB', detail: 'Confirm executor logs skip and does NOT execute any signal', file: 'tekton_executor.py' },
      { id: 't2_6', title: 'Test executor with AUTO_TRADE = true in DB', detail: 'Insert a TEST signal. Confirm executor picks it up', file: 'tekton_executor.py' },
    ],
  },
  {
    id: 'p3', title: 'Phase 3 — Base44 UI: Settings Page Wired to SQL', color: 'cyan',
    desc: 'Verify the TradingSettings page successfully reads and writes to SQL via the bridge.',
    tasks: [
      { id: 't3_1', title: 'Test loadAllSettings → GET bridge /data/settings', detail: 'Open TradingSettings page. Confirm values load from SQL.', file: 'Base44 UI → TradingSettings page' },
      { id: 't3_2', title: 'Test saveAllSettings → POST bridge /data/settings', detail: 'Change risk_pct to 0.02, click Save. Verify SQL row updated.', file: 'Base44 UI → TradingSettings page' },
      { id: 't3_3', title: 'Test Auto Trade toggle persists to SQL', detail: 'Toggle Auto Trade ON → Save. Verify auto_trade = true in DB.', file: 'Base44 UI → TradingSettings page' },
      { id: 't3_4', title: 'Verify Dashboard toggles also use new settings source', detail: 'Confirm they call loadAllSettings / saveAllSettings (not old entities).', file: 'Base44 UI → Dashboard page' },
      { id: 't3_9', title: 'Remove execution controls from Command Center Dashboard', detail: 'These toggles already exist in Trading Settings. Remove duplicates from Dashboard.', file: 'Base44 UI → Dashboard page' },
      { id: 't3_7', title: 'Fix Auto Trade toggle not persisting on page refresh', detail: 'BUG: Auto Trade toggles revert to default after refresh.', file: 'TradingSettings page + saveAllSettings + loadAllSettings + tekton_bridge.py' },
      { id: 't3_8', title: 'Fix Friday Flush toggle not persisting on page refresh', detail: 'Same bug pattern as Auto Trade.', file: 'TradingSettings page + tekton_bridge.py + PostgreSQL' },
      { id: 't3_5', title: 'Test Portfolio Heat display on Command Center', detail: 'Confirm the margin gauge widget loads and displays a real value.', file: 'Base44 UI → Dashboard page → getAccountMetrics function' },
      { id: 't3_6', title: 'Verify Portfolio Heat updates on refresh / auto-poll', detail: 'With an open position, confirm the margin gauge value changes.', file: 'Base44 UI → Dashboard page' },
    ],
  },
  {
    id: 'p4', title: 'Phase 4 — Bridge Filename & Service References', color: 'yellow',
    desc: 'The bridge was renamed to tekton_bridge.py. Ensure all references are updated.',
    tasks: [
      { id: 't4_1', title: 'Update systemd service file to reference tekton_bridge.py', detail: 'Edit /etc/systemd/system/tekton-ai-trader-bridge.service', file: '/etc/systemd/system/tekton-ai-trader-bridge.service' },
      { id: 't4_2', title: 'Update start_tekton.sh if it references old filename', detail: "Check: grep 'tekton-bridge-v4' start_tekton.sh", file: 'start_tekton.sh' },
      { id: 't4_3', title: 'Confirm bridge service running after rename', detail: 'sudo systemctl status tekton-ai-trader-bridge.service', file: 'Terminal' },
    ],
  },
  {
    id: 'p5', title: 'Phase 5 — Backfill Script: Verify tekton_backfill.py', color: 'green',
    desc: 'Confirm tekton_backfill.py is still working correctly after all changes.',
    tasks: [
      { id: 't5_1', title: 'Review tekton_backfill.py for hardcoded config references', detail: 'Check if backfill reads risk_pct, auto_trade from Base44 entities', file: 'tekton_backfill.py' },
      { id: 't5_2', title: 'Verify cron job is still active', detail: 'Run: crontab -l', file: 'crontab' },
      { id: 't5_3', title: 'Check backfill output in combined_trades.log', detail: 'tail -f combined_trades.log | grep backfill', file: 'combined_trades.log' },
    ],
  },
  {
    id: 'p6', title: 'Phase 6 — End-to-End Smoke Test', color: 'red',
    desc: 'Full system integration test after all phases complete.',
    tasks: [
      { id: 't6_1', title: 'Set AUTO_TRADE = true in TradingSettings UI', detail: 'Open TradingSettings → toggle Auto Trade ON → Save', file: 'Base44 UI' },
      { id: 't6_2', title: 'Insert a test signal via ManualSignal page', detail: 'Confirm it appears in Signals Log as PENDING', file: 'Base44 UI → ManualSignal page' },
      { id: 't6_3', title: 'Confirm executor picks up signal and executes', detail: 'Watch combined_trades.log. Signal status: PENDING → EXECUTED', file: 'combined_trades.log + DB' },
      { id: 't6_4', title: 'Confirm execution appears in Execution Journal', detail: 'New trade entry should be visible with correct symbol, volume, SL/TP', file: 'Base44 UI → Executions page' },
      { id: 't6_5', title: 'Set AUTO_TRADE = false and confirm no new executions', detail: 'Toggle off → insert another test signal → confirm executor skips it', file: 'Base44 UI + DB + combined_trades.log' },
    ],
  },
  {
    id: 'p7', title: 'Phase 7 — Strategy Expansion', color: 'blue',
    desc: 'Deploy and validate the full strategy library: ICT FVG, EMA Pullback, Session ORB, VWAP Reversion, Breakout Retest, RSI Divergence, Lester LSV.',
    tasks: [
      { id: 't7_1', title: 'Verify all 7 strategy services running on VM', detail: 'sudo systemctl status tekton-strat-*.service', file: 'VM systemd' },
      { id: 't7_2', title: 'Confirm MIN_RR=1.5 gate active on all strategies', detail: 'Review each strat_*.py — confirm tp_pips/sl_pips >= 1.5 check before signal insert', file: 'All strat_*.py files' },
      { id: 't7_3', title: 'Verify confidence_score stored as integer (0-100)', detail: 'SELECT strategy, confidence_score FROM signals ORDER BY created_at DESC LIMIT 20', file: 'PostgreSQL' },
      { id: 't7_4', title: 'Validate session exposure cap gate in executor', detail: 'Confirm 🛑 log appears when open positions × risk_pct >= max_session_exposure_pct', file: 'combined_trades.log' },
      { id: 't7_5', title: 'Document strategy onboarding process', detail: 'Update SystemContext page with strategy checklist and signal schema rules', file: 'SystemContext page + README' },
    ],
  },
  {
    id: 'p8', title: 'Phase 8 — Economic Calendar (Passive)', color: 'orange',
    desc: 'Integrate ForexFactory economic calendar into the UI. Display upcoming high-impact events on the Dashboard and Analytics page. No trade gating yet.',
    tasks: [
      { id: 't8_1', title: 'Create economic_events table in PostgreSQL', detail: 'CREATE TABLE economic_events (id SERIAL PRIMARY KEY, event_date TIMESTAMPTZ, currency VARCHAR(10), indicator_name TEXT, impact_level VARCHAR(10), source VARCHAR(50) DEFAULT \'forexfactory\', created_at TIMESTAMPTZ DEFAULT NOW())', file: 'PostgreSQL (tekton-trader DB)' },
      { id: 't8_2', title: 'Write tekton_calendar.py VM fetcher script', detail: 'Fetches ForexFactory XML feed (nfs.faireconomy.media/ff_calendar_thisweek.xml), parses medium+high impact events, upserts to economic_events table. Port from V3 logic.', file: 'tekton_calendar.py (new)' },
      { id: 't8_3', title: 'Add cron job for calendar refresh', detail: 'Run every 6 hours: 0 */6 * * * /path/to/venv/bin/python /opt/tekton/tekton_calendar.py', file: 'crontab' },
      { id: 't8_4', title: 'Add GET /calendar/events bridge endpoint', detail: 'Query economic_events WHERE event_date BETWEEN NOW()-1hr AND NOW()+7days, return JSON array ordered by event_date', file: 'tekton_bridge.py' },
      { id: 't8_5', title: 'Deploy getEconomicCalendar Base44 backend function', detail: 'Proxies GET /calendar/events from bridge. Returns events array to UI.', file: 'Base44 backend function' },
      { id: 't8_6', title: 'Add Economic Calendar widget to Dashboard', detail: 'Strip showing next 3 high-impact events today/tomorrow. Coloured by impact (red=high, amber=medium). Shows time until event.', file: 'Base44 UI → Dashboard page' },
      { id: 't8_7', title: 'Add full Economic Calendar view to Analytics page', detail: 'Grouped by day. All currencies. Countdown timers. 7-day view.', file: 'Base44 UI → Analytics page' },
      { id: 't8_8', title: 'Add manual import fallback', detail: 'Port V3 manualCalendarImport function — accepts Myfxbook XML or tab-separated text, writes to SQL economic_events table', file: 'tekton_calendar.py + Base44 backend function' },
    ],
  },
  {
    id: 'p9', title: 'Phase 9 — Economic Calendar (Active Gating)', color: 'red',
    desc: 'Wire the economic calendar into the executor and monitor. Block new trades and tighten position management around high-impact news events.',
    tasks: [
      { id: 't9_1', title: 'Add news_filter_enabled column to settings table', detail: 'ALTER TABLE settings ADD COLUMN news_filter_enabled BOOLEAN DEFAULT TRUE; ALTER TABLE settings ADD COLUMN news_buffer_mins INT DEFAULT 15;', file: 'PostgreSQL (tekton-trader DB)' },
      { id: 't9_2', title: 'Add news_filter_enabled + news_buffer_mins to TradingSettings UI', detail: 'Toggle + number input. Saves via saveAllSettings. Hint: "Block new trades within X min of high-impact events"', file: 'Base44 UI → TradingSettings page' },
      { id: 't9_3', title: 'Add is_news_window() helper to tekton_executor.py', detail: 'Queries economic_events for any HIGH impact event on traded currency within ±news_buffer_mins. Returns True/False.', file: 'tekton_executor.py' },
      { id: 't9_4', title: 'Gate signal execution on news window check', detail: 'Before executing any signal: if news_filter_enabled and is_news_window(currency): log skip reason, leave signal PENDING, retry after window passes', file: 'tekton_executor.py' },
      { id: 't9_5', title: 'Add news awareness to tekton_monitor.py', detail: 'If position currency has HIGH impact event within 10 min: set intervention bias to HOLD. No ADJUST_SL or ADJUST_TP during news window.', file: 'tekton_monitor.py' },
      { id: 't9_6', title: 'Test news gate with simulated upcoming event', detail: 'Insert a test high-impact event 5 min from now in economic_events. Fire a test signal. Confirm executor skips it with news gate log.', file: 'PostgreSQL + combined_trades.log' },
      { id: 't9_7', title: 'Add news window indicator to Dashboard', detail: 'If any HIGH impact event for an open position currency is within 30 min: show amber warning banner on Command Center.', file: 'Base44 UI → Dashboard page' },
    ],
  },
  {
    id: 'p10', title: 'Phase 10 — Analytics Page', color: 'purple',
    desc: 'Build a dedicated Analytics page with AI-driven performance attribution and recommendations. Dashboard shows exec summary; Analytics goes deep.',
    tasks: [
      { id: 't10_1', title: 'Create getAnalytics Base44 backend function', detail: 'Queries signals + executions from SQL. Returns: win_rate per strategy, avg_r per strategy, profit_factor, confidence_vs_r correlation, symbol breakdown, session breakdown.', file: 'Base44 backend function' },
      { id: 't10_2', title: 'Build Analytics page — Strategy Performance section', detail: 'Table: strategy | signals | win_rate | avg_r | profit_factor | status (Active/Underperforming). Sortable.', file: 'Base44 UI → Analytics page (new)' },
      { id: 't10_3', title: 'Build Analytics page — Confidence vs R scatter', detail: 'Show correlation between confidence_score and actual outcome_r. Does high confidence = better results?', file: 'Base44 UI → Analytics page' },
      { id: 't10_4', title: 'Build Analytics page — Symbol/Session breakdown', detail: 'Bar charts: P&L by symbol, P&L by session (London/NY/Asian). Where is money made vs lost?', file: 'Base44 UI → Analytics page' },
      { id: 't10_5', title: 'Build AI Recommendations section', detail: 'Lester analyses current stats and generates 3-5 plain English recommendations. Stored in a AnalyticsSnapshot entity. Refreshed on demand.', file: 'Base44 UI → Analytics page + Base44 backend function' },
      { id: 't10_6', title: 'Add Key Insights strip to Dashboard', detail: 'Show latest 3 AI recommendations as bullet points on Command Center. Read from AnalyticsSnapshot entity. Updated when Analytics page is refreshed.', file: 'Base44 UI → Dashboard page' },
      { id: 't10_7', title: 'Add News Correlation analysis to Analytics page', detail: 'For each closed trade: was it within 30 min of a high-impact event? Show win rate inside vs outside news windows.', file: 'Base44 UI → Analytics page' },
    ],
  },
];

const STATUS_CONFIG = {
  todo:        { label: 'To Do',       icon: Circle,        color: 'text-slate-500',   bg: 'bg-slate-500/10 border-slate-500/20' },
  in_progress: { label: 'In Progress', icon: Clock,         color: 'text-yellow-400',  bg: 'bg-yellow-500/10 border-yellow-500/20' },
  done:        { label: 'Done',        icon: CheckCircle,   color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' },
  blocked:     { label: 'Blocked',     icon: AlertTriangle, color: 'text-red-400',     bg: 'bg-red-500/10 border-red-500/20' },
};

const PHASE_COLORS = {
  blue:   'text-blue-400 border-blue-500/20 bg-blue-500/10',
  purple: 'text-purple-400 border-purple-500/20 bg-purple-500/10',
  cyan:   'text-cyan-400 border-cyan-500/20 bg-cyan-500/10',
  yellow: 'text-yellow-400 border-yellow-500/20 bg-yellow-500/10',
  green:  'text-emerald-400 border-emerald-500/20 bg-emerald-500/10',
  red:    'text-red-400 border-red-500/20 bg-red-500/10',
  orange: 'text-orange-400 border-orange-500/20 bg-orange-500/10',
};

export default function ImplementationPlan() {
  const [taskStatus, setTaskStatus] = useState({});
  const [openPhases, setOpenPhases] = useState(() => Object.fromEntries(PHASES.map(p => [p.id, true])));
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [savedMsg, setSavedMsg] = useState(false);

  useEffect(() => { loadStatus(); }, []);

  const loadStatus = async () => {
    setLoading(true);
    const records = await base44.entities.ImplementationTask.list();
    const map = {};
    records.forEach(r => { map[r.task_id] = r.status; });
    setTaskStatus(map);
    setLoading(false);
  };

  const setStatus = (taskId, status) => setTaskStatus(prev => ({ ...prev, [taskId]: status }));

  const saveAll = async () => {
    setSaving(true);
    const existing = await base44.entities.ImplementationTask.list();
    const existingMap = Object.fromEntries(existing.map(r => [r.task_id, r.id]));
    for (const [taskId, status] of Object.entries(taskStatus)) {
      if (existingMap[taskId]) {
        await base44.entities.ImplementationTask.update(existingMap[taskId], { task_id: taskId, status });
      } else {
        await base44.entities.ImplementationTask.create({ task_id: taskId, status });
      }
    }
    setSaving(false); setSavedMsg(true);
    setTimeout(() => setSavedMsg(false), 2500);
  };

  const totalTasks = PHASES.reduce((acc, p) => acc + p.tasks.length, 0);
  const doneTasks = Object.values(taskStatus).filter(s => s === 'done').length;
  const pct = Math.round((doneTasks / totalTasks) * 100);
  const togglePhase = (id) => setOpenPhases(prev => ({ ...prev, [id]: !prev[id] }));

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-5xl mx-auto">
      <div className="flex items-start gap-4 mb-6">
        <div className="p-2 rounded-xl bg-blue-500/10 border border-blue-500/20 shrink-0"><ClipboardList className="w-6 h-6 text-blue-400" /></div>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Implementation Plan</h1>
          <p className="text-slate-500 text-sm mt-0.5">v4.7.0 — Phases 1–10</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={loadStatus} className="p-2 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"><RefreshCw className="w-4 h-4" /></button>
          <button onClick={saveAll} disabled={saving} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold transition-colors disabled:opacity-50">
            <Save className="w-4 h-4" />{saving ? 'Saving…' : savedMsg ? '✓ Saved' : 'Save Progress'}
          </button>
        </div>
      </div>
      <div className="card-dark p-4 mb-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-semibold text-slate-300">Overall Progress</span>
          <span className="text-sm font-bold text-blue-400">{doneTasks} / {totalTasks} tasks ({pct}%)</span>
        </div>
        <div className="h-2.5 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-gradient-to-r from-blue-600 to-emerald-500 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
        </div>
        <div className="flex gap-4 mt-3 flex-wrap">
          {Object.entries(STATUS_CONFIG).map(([key, cfg]) => {
            const count = Object.values(taskStatus).filter(s => s === key).length;
            const Icon = cfg.icon;
            return (<div key={key} className="flex items-center gap-1.5 text-xs"><Icon className={`w-3.5 h-3.5 ${cfg.color}`} /><span className="text-slate-400">{cfg.label}:</span><span className="font-bold text-slate-200">{count}</span></div>);
          })}
        </div>
      </div>
      {loading && <div className="text-center text-slate-500 text-sm py-8">Loading saved progress…</div>}
      {!loading && PHASES.map(phase => {
        const phaseDone = phase.tasks.filter(t => taskStatus[t.id] === 'done').length;
        const isOpen = openPhases[phase.id];
        return (
          <div key={phase.id} className="card-dark mb-4">
            <button onClick={() => togglePhase(phase.id)} className="w-full flex items-center justify-between px-5 py-4 text-left">
              <div className="flex items-center gap-3">
                <span className={`p-1.5 rounded-lg border text-xs font-bold ${PHASE_COLORS[phase.color]}`}>{phaseDone}/{phase.tasks.length}</span>
                <span className="font-semibold text-slate-200 text-sm">{phase.title}</span>
              </div>
              {isOpen ? <ChevronDown className="w-4 h-4 text-slate-600" /> : <ChevronRight className="w-4 h-4 text-slate-600" />}
            </button>
            {isOpen && (
              <div className="px-5 pb-5 border-t border-slate-800/60 pt-4 space-y-3">
                <p className="text-xs text-slate-500 mb-4">{phase.desc}</p>
                {phase.tasks.map(task => {
                  const status = taskStatus[task.id] || 'todo';
                  const cfg = STATUS_CONFIG[status];
                  const StatusIcon = cfg.icon;
                  return (
                    <div key={task.id} className="bg-slate-900/60 rounded-lg p-3 border border-slate-800 hover:border-slate-700 transition-colors">
                      <div className="flex items-start gap-3">
                        <div className="flex flex-col gap-1 shrink-0 mt-0.5">
                          {Object.entries(STATUS_CONFIG).map(([key, c]) => {
                            const Ic = c.icon;
                            return (<button key={key} onClick={() => setStatus(task.id, key)} title={c.label} className={`w-5 h-5 rounded flex items-center justify-center border transition-all ${status === key ? c.bg : 'border-transparent opacity-25 hover:opacity-60'}`}><Ic className={`w-3 h-3 ${status === key ? c.color : 'text-slate-500'}`} /></button>);
                          })}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className={`text-xs font-semibold border rounded px-1.5 py-0.5 ${cfg.bg} ${cfg.color}`}>{cfg.label}</span>
                            <span className={`text-sm font-medium ${status === 'done' ? 'line-through text-slate-600' : 'text-slate-200'}`}>{task.title}</span>
                          </div>
                          <p className="text-xs text-slate-500 mb-1.5">{task.detail}</p>
                          <span className="text-[10px] font-mono text-slate-600 bg-slate-800/60 px-1.5 py-0.5 rounded">{task.file}</span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
      <div className="text-center text-xs text-slate-700 mt-8 pb-4 font-mono">Implementation Plan v4.7.0 — Click status icons to update · Press Save Progress to persist</div>
    </div>
  );
}
