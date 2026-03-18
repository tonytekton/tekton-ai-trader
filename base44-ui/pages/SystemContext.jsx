import React, { useState } from 'react';
import {
  BookOpen, Server, Database, Zap, Shield, Brain, GitBranch,
  AlertTriangle, CheckCircle, ChevronDown, ChevronRight, Terminal, Clock, Layers, ScrollText
} from 'lucide-react';

const Section = ({ icon: Icon, title, color = 'blue', children }) => {
  const [open, setOpen] = useState(true);
  const colors = {
    blue:   'text-blue-400 border-blue-500/20 bg-blue-500/10',
    green:  'text-emerald-400 border-emerald-500/20 bg-emerald-500/10',
    yellow: 'text-yellow-400 border-yellow-500/20 bg-yellow-500/10',
    purple: 'text-purple-400 border-purple-500/20 bg-purple-500/10',
    red:    'text-red-400 border-red-500/20 bg-red-500/10',
    cyan:   'text-cyan-400 border-cyan-500/20 bg-cyan-500/10',
  };
  return (
    <div className="card-dark mb-4">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center justify-between px-5 py-4 text-left">
        <div className="flex items-center gap-3">
          <span className={`p-1.5 rounded-lg border ${colors[color]}`}><Icon className="w-4 h-4" /></span>
          <span className="font-semibold text-slate-200 text-sm">{title}</span>
        </div>
        {open ? <ChevronDown className="w-4 h-4 text-slate-600" /> : <ChevronRight className="w-4 h-4 text-slate-600" />}
      </button>
      {open && <div className="px-5 pb-5 border-t border-slate-800/60 pt-4 text-sm text-slate-400 space-y-3">{children}</div>}
    </div>
  );
};

const Row = ({ label, value, mono }) => (
  <div className="flex items-start gap-3 py-1.5 border-b border-slate-800/40 last:border-0">
    <span className="text-slate-600 w-44 shrink-0 text-xs uppercase tracking-wider font-semibold mt-0.5">{label}</span>
    <span className={`text-slate-300 ${mono ? 'font-mono text-xs bg-slate-800/60 px-2 py-0.5 rounded' : ''}`}>{value}</span>
  </div>
);

const Decision = ({ id, text }) => (
  <div className="flex items-start gap-3 py-2 border-b border-slate-800/40 last:border-0">
    <span className="text-xs font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded px-1.5 py-0.5 shrink-0">#{id}</span>
    <span className="text-slate-300 flex-1">{text}</span>
  </div>
);

const Code = ({ children }) => (
  <pre className="bg-slate-900 border border-slate-800 rounded-lg p-3 text-xs text-emerald-400 font-mono overflow-x-auto whitespace-pre-wrap">{children}</pre>
);

export default function SystemContext() {
  return (
    <div className="min-h-screen p-4 md:p-8 max-w-5xl mx-auto">
      <div className="flex items-center gap-4 mb-8">
        <div className="p-2 rounded-xl bg-blue-500/10 border border-blue-500/20"><BookOpen className="w-6 h-6 text-blue-400" /></div>
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">System Context & Developer Dossier</h1>
          <p className="text-slate-500 text-sm mt-0.5">Tekton AI Trader v4.7 — Read this before making any changes. Last updated: Mar 18 2026</p>
        </div>
        <div className="ml-auto flex items-center gap-2 text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-3 py-1.5 rounded-full">
          <CheckCircle className="w-3.5 h-3.5" />~98% Functionally Complete
        </div>
      </div>

      <div className="mb-6 p-4 rounded-xl border border-yellow-500/30 bg-yellow-500/5 flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-yellow-400 shrink-0 mt-0.5" />
        <div>
          <p className="text-yellow-300 font-semibold text-sm">Instructions for AI Assistant</p>
          <ul className="text-yellow-600 text-xs mt-1 space-y-1 list-none">
            <li>1. Read this entire page before making ANY changes to this app.</li>
            <li>2. Never contradict the "Agreed Decisions" section without explicit user approval.</li>
            <li>3. GitHub repo: <span className="font-mono text-yellow-400">https://github.com/tonytekton/tekton-ai-trader/</span> (public)</li>
            <li>4. Always update this page to reflect any approved changes.</li>
            <li>5. Always append a new entry to the Change Log when a change is made.</li>
          </ul>
        </div>
      </div>

      <Section icon={Server} title="System Architecture" color="blue">
        <p className="text-slate-500 text-xs mb-3">Three-tier Python architecture on Google Cloud VM. Base44 UI is read-only frontend.</p>
        <div className="space-y-2">
          {[
            { name: 'Bridge',      file: 'tekton_bridge.py',        desc: 'REST port 8080 / cTrader port 5035. Single-Step Atomic Orders.',       cmd: 'sudo systemctl restart tekton-ai-trader-bridge.service', color: 'text-blue-400' },
            { name: 'Executor',    file: 'tekton_executor.py',      desc: 'Polls PENDING signals, calculates volume, calls bridge.',               cmd: 'nohup python3 tekton_executor.py >> executor.log 2>&1 &', color: 'text-purple-400' },
            { name: 'Monitor',     file: 'tekton_monitor.py',       desc: 'AI-driven position management + circuit breaker.',                      cmd: 'nohup python3 tekton_monitor.py >> monitor.log 2>&1 &', color: 'text-emerald-400' },
            { name: 'Backfill',    file: 'tekton_backfill.py',      desc: 'Fills market_data gaps every 15min.',                                   cmd: 'Cron: */15 * * * *', color: 'text-yellow-400' },
            { name: 'Daily Report',file: 'tekton_daily_report.py',  desc: 'Telegram P&L summary.',                                                 cmd: 'Cron: 0 22 * * * (22:00 UTC = 06:00 KL)', color: 'text-cyan-400' },
          ].map(s => (
            <div key={s.name} className="bg-slate-900/60 rounded-lg p-3 border border-slate-800">
              <div className="flex items-center gap-2 mb-1"><div className={`font-bold text-sm ${s.color}`}>{s.name}</div><div className="text-xs text-slate-500 font-mono">{s.file}</div></div>
              <div className="text-xs text-slate-400 mb-1">{s.desc}</div>
              <code className="text-[10px] text-slate-600 font-mono break-all">Start: {s.cmd}</code>
            </div>
          ))}
        </div>
        <div className="mt-3 p-3 rounded-lg bg-blue-500/5 border border-blue-500/20 text-xs text-blue-300">
          <strong>Full stack restart:</strong> <span className="font-mono">bash /home/tony/tekton-ai-trader/start_tekton.sh</span>
        </div>
      </Section>

      <Section icon={Database} title="Infrastructure & Access" color="cyan">
        <Row label="Server" value="Google Cloud Compute Engine — tony@tekton-ai-trader" />
        <Row label="Project Dir" value="/home/tony/tekton-ai-trader/" mono />
        <Row label="DB Host" value="172.16.64.3 (internal IP) | DB Name: tekton-trader" mono />
        <Row label="Bridge URL" value="BRIDGE_URL env var — local: http://localhost:8080" mono />
        <Row label="Bridge Auth" value="Header X-Bridge-Key (BRIDGE_KEY env var)" mono />
        <Row label="GitHub" value="https://github.com/tonytekton/tekton-ai-trader/" mono />
        <Row label="Timezone" value="Asia/Kuala Lumpur (UTC+8)" />
      </Section>

      <Section icon={GitBranch} title="Data Flow & Signal Lifecycle" color="purple">
        <div className="flex flex-col gap-2">
          {[
            { step: '1', label: 'Market Data', detail: 'tekton_backfill.py fills market_data every 15min across 50 symbols x 5 timeframes.' },
            { step: '2', label: 'Strategy generates signal', detail: 'Inserts PENDING signal into signals table with sl_pips + tp_pips.' },
            { step: '3', label: 'Executor picks up signal', detail: 'Checks AUTO_TRADE, calculates volume, calls bridge /trade/execute.' },
            { step: '4', label: 'Bridge executes', detail: 'Single-Step Protobuf to cTrader with rel_sl + rel_tp. Signal UUID as cTrader comment.' },
            { step: '5', label: 'Monitor manages position', detail: 'Calls aiPositionReview per position. Actions: HOLD/CLOSE/ADJUST_SL/ADJUST_TP/PARTIAL_CLOSE.' },
            { step: '6', label: 'Circuit Breaker', detail: 'Drawdown breach closes all positions, calls drawdownAutopsy, freezes trading.' },
            { step: '7', label: 'Base44 UI', detail: 'Read-only reporting layer via bridge /proxy/signals and /executions.' },
          ].map(s => (
            <div key={s.step} className="flex items-start gap-3">
              <span className="w-6 h-6 rounded-full bg-purple-500/20 text-purple-400 text-xs font-bold flex items-center justify-center shrink-0">{s.step}</span>
              <div><span className="text-slate-200 font-medium text-xs">{s.label}</span><p className="text-slate-500 text-xs">{s.detail}</p></div>
            </div>
          ))}
        </div>
      </Section>

      <Section icon={Brain} title="Standard Signal Schema (All strategies MUST follow)" color="green">
        <Code>{`{ "signal_uuid": "AUTO", "symbol": "EURUSD", "strategy": "Tekton-ICT-FVG-v1",\n  "signal_type": "BUY", "timeframe": "15min", "confidence_score": 0.88,\n  "sl_pips": 15.0, "tp_pips": 27.0, "status": "PENDING" }`}</Code>
        <div className="mt-3 p-3 rounded-lg bg-red-500/5 border border-red-500/20 text-xs text-red-400"><strong>CRITICAL:</strong> Never insert signals with NULL sl_pips or tp_pips.</div>
      </Section>

      <Section icon={Database} title="Settings Architecture — Single Source of Truth" color="cyan">
        <p className="text-xs text-slate-500 mb-3">
          Single source of truth: <span className="font-mono text-cyan-400">settings</span> table in SQL DB, row id=1.<br />
          Fields: auto_trade, friday_flush, risk_pct, target_reward, daily_drawdown_limit.<br />
          UI Read: <span className="font-mono text-cyan-400">loadAllSettings → GET bridge /data/settings</span><br />
          UI Write: <span className="font-mono text-cyan-400">saveAllSettings → POST bridge /data/settings</span><br />
          Executor: <span className="font-mono text-cyan-400">fetch_settings() → direct psycopg2 query</span><br />
          Base44 entities UserConfig and SystemSettings are <strong>DEPRECATED</strong>.
        </p>
      </Section>

      <Section icon={Layers} title="Active Strategies (7 live)" color="green">
        <div className="space-y-2">
          {[
            { file: 'strat_ict_fvg_v1.py',        name: 'Tekton-ICT-FVG-v1',  desc: 'FVG + MSS + Liquidity Grab',                        tf: '15min+1H',  session: '24/7' },
            { file: 'strat_ema_pullback_v1.py',    name: 'Tekton-EPS-v1',      desc: '4H EMA trend + 15min pullback rejection',            tf: '15min+4H',  session: '24/7' },
            { file: 'strat_session_orb_v1.py',     name: 'Tekton-SORB-v1',     desc: 'Session open range breakout + retest',               tf: '15min',     session: 'London 07:00 / NY 13:00 UTC' },
            { file: 'strat_vwap_reversion_v1.py',  name: 'Tekton-VR-v1',       desc: 'VWAP deviation >= 1.5xATR + reversal candle',        tf: '15min',     session: '24/7' },
            { file: 'strat_breakout_retest_v1.py', name: 'Tekton-BRT-v1',      desc: 'S/R breakout + confirmed retest flip',               tf: '15min',     session: '24/7' },
            { file: 'strat_rsi_divergence_v1.py',  name: 'Tekton-RSID-v1',     desc: 'RSI divergence at structure',                        tf: '15min',     session: '24/7' },
            { file: 'strat_lester_v1.py',          name: 'Tekton-LSV-v1',      desc: 'Liquidity sweep + CHoCH + volume confirmation',      tf: '15min+1H',  session: 'London+NY sessions' },
          ].map(s => (
            <div key={s.file} className="bg-slate-900/60 rounded-lg p-3 border border-slate-800 flex items-start gap-3">
              <span className="text-[10px] font-bold border rounded px-1.5 py-0.5 shrink-0 mt-0.5 text-emerald-400 bg-emerald-500/10 border-emerald-500/20">LIVE</span>
              <div>
                <div className="text-slate-200 font-mono text-xs">{s.file} — <span className="text-emerald-400">{s.name}</span></div>
                <div className="text-slate-500 text-xs mt-0.5">{s.desc} | {s.tf} | {s.session}</div>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 p-3 rounded-lg bg-yellow-500/5 border border-yellow-500/20 text-xs text-yellow-400">
          <strong>Entry quality gate (ALL strategies):</strong> MIN_RR = 1.5. tp_pips/sl_pips &lt; 1.5 = signal rejected.<br />
          <strong>SL/TP methodology:</strong> Structural — SL at candle wick + ATR buffer, TP at next structural swing.
        </div>
      </Section>

      <Section icon={CheckCircle} title="Agreed Decisions — Do NOT reverse without explicit user approval" color="green">
        {[
          [1,  'Signals expire after 30min if PENDING. maxAgeMs = 30*60*1000 in getSignals.'],
          [2,  'sl_pips and tp_pips REQUIRED on every signal. NULL = invalid.'],
          [3,  "Bridge trade field is 'side' not 'direction'. Values: BUY or SELL."],
          [4,  'Volume from settings.risk_pct — never hardcoded. Uses free_margin not balance.'],
          [5,  'SL/TP structural — from candle wicks + ATR buffer. Never purely ratio-based.'],
          [6,  'Execution errors show as red banner in UI — never swallow silently.'],
          [7,  'Atomic orders only — rel_sl and rel_tp in initial order. Never modify after open.'],
          [8,  'signal_uuid must have DEFAULT gen_random_uuid() in signals table.'],
          [9,  'Target reward 1.8R (tp_pips = sl_pips x 1.8). Monitor AI reviews at any R level.'],
          [10, 'SQL settings table id=1 is single source of truth. Base44 entities deprecated.'],
          [11, 'Executor checks AUTO_TRADE from SQL before every execution. False = skip signal.'],
          [12, 'TradingSettings page manages all settings — saved atomically via saveAllSettings.'],
          [13, 'cTrader prices are raw integers — divide by 10^pipPosition before pip calculations.'],
          [14, 'MIN_RR = 1.5 — entry quality gate on ALL strategies. Below 1.5 = rejected.'],
          [15, 'All strategies fetch pip size dynamically from bridge /symbols/list (pipPosition).'],
          [16, 'Monitor calls aiPositionReview for AI-driven management. Delta-based triggers (~20 calls/hr max).'],
          [17, 'Drawdown autopsy mandatory on every circuit breaker fire. Frozen until APPROVED_RESUME.'],
          [18, 'No hardcoded credentials anywhere. All via os.getenv() from .env file.'],
        ].map(([id, text]) => <Decision key={id} id={id} text={text} />)}
      </Section>

      <Section icon={AlertTriangle} title="Emergency — Panic Protocol" color="red">
        <Code>{`pkill -f tekton_executor.py\nsudo systemctl stop tekton-ai-trader-bridge.service\nUPDATE signals SET status = 'CANCELLED' WHERE status = 'PENDING';\npkill -f tekton_monitor.py\npkill -f "strat_"`}</Code>
      </Section>

      <Section icon={Clock} title="Maintenance Schedule" color="yellow">
        <Row label="Daily" value="Check combined_trades.log for 'Rejection' strings. Verify settings row id=1." />
        <Row label="Weekly (Friday)" value="Archive combined_trades.log. Run performance attribution SQL. Review AiIntervention outcomes." />
        <Row label="Monday" value="Service status, SQL heartbeat, crontab -l verification." />
        <Row label="Monthly" value="signals.confidence_score vs executions.pnl per strategy. Review DrawdownAutopsy records." />
      </Section>

      <Section icon={ScrollText} title="Change Log" color="blue">
        <div className="space-y-0">
          {[
            { date: '2026-03-18', version: 'v4.7.0', author: 'Lester / Tony', changes: [
              'AI Position Management: aiPositionReview Base44 function deployed.',
              'Drawdown Autopsy: drawdownAutopsy Base44 function deployed.',
              '5 new strategies deployed: SORB, VWAP Reversion, Breakout+Retest, RSI Divergence, Lester LSV.',
              'MIN_RR = 1.5 entry quality gate added to all strategies.',
              'Structural SL/TP implemented across all strategies.',
              'Dynamic pip size: all strategies fetch pipPosition from bridge /symbols/list.',
              'start_tekton.sh overhauled: starts all 7 strategies.',
            ]},
            { date: '2026-03-12', version: 'v4.6.0', author: 'AI / Tony', changes: [
              'SQL settings table as single source of truth. Base44 UserConfig + SystemSettings deprecated.',
              'loadAllSettings, saveAllSettings functions added.',
              'TradingSettings page redesigned with autoTrade + fridayFlush toggles.',
              'tekton_executor.py: fetch_settings() reads all config from SQL.',
            ]},
            { date: '2026-03-11', version: 'v4.5.3', author: 'AI / Tony', changes: ['SystemContext page created as persistent developer dossier.'] },
            { date: '2026-03-11', version: 'v4.5.2', author: 'AI / Tony', changes: [
              'strat_ict_fvg_v1.py: sl_pips/tp_pips now correctly written to DB.',
              'getSignals: PENDING signals >30min marked EXPIRED.',
            ]},
          ].map((entry, i) => (
            <div key={i} className="border-b border-slate-800/60 last:border-0 py-3">
              <div className="flex items-center gap-3 mb-2">
                <span className="text-xs font-mono text-blue-400 bg-blue-500/10 border border-blue-500/20 rounded px-2 py-0.5">{entry.version}</span>
                <span className="text-xs text-slate-400 font-semibold">{entry.date}</span>
                <span className="text-xs text-slate-600">by {entry.author}</span>
              </div>
              <ul className="space-y-1">
                {entry.changes.map((c, j) => (<li key={j} className="flex items-start gap-2 text-xs text-slate-400"><span className="text-blue-500 mt-0.5 shrink-0">›</span>{c}</li>))}
              </ul>
            </div>
          ))}
        </div>
      </Section>

      <div className="text-center text-xs text-slate-700 mt-8 pb-4">Tekton AI Trader v4.7 — Owner: Tony — GitHub: github.com/tonytekton/tekton-ai-trader</div>
    </div>
  );
}