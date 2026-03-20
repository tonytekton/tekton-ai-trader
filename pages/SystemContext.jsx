import React, { useState } from 'react';
import {
  BookOpen, Server, Database, Zap, Shield, Brain, GitBranch,
  AlertTriangle, CheckCircle, ChevronDown, ChevronRight, Terminal, Clock, Layers, ScrollText, Wrench
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
    orange: 'text-orange-400 border-orange-500/20 bg-orange-500/10',
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

const HF = ({ id, sha, text }) => (
  <div className="flex items-start gap-3 py-2 border-b border-slate-800/40 last:border-0">
    <span className="text-xs font-bold text-orange-400 bg-orange-500/10 border border-orange-500/20 rounded px-1.5 py-0.5 shrink-0">HF-{id}</span>
    {sha && <span className="font-mono text-xs text-slate-600 bg-slate-800/60 px-1.5 py-0.5 rounded shrink-0">{sha}</span>}
    <span className="text-slate-300 flex-1 text-xs">{text}</span>
  </div>
);

export default function SystemContext() {
  return (
    <div className="min-h-screen p-4 md:p-8 max-w-5xl mx-auto">
      <div className="flex items-center gap-4 mb-8">
        <div className="p-2 rounded-xl bg-blue-500/10 border border-blue-500/20"><BookOpen className="w-6 h-6 text-blue-400" /></div>
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">System Context & Developer Dossier</h1>
          <p className="text-slate-500 text-sm mt-0.5">Tekton AI Trader v4.8 — Read this before making any changes. Last updated: 20 Mar 2026</p>
        </div>
        <div className="ml-auto flex items-center gap-2 text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-3 py-1.5 rounded-full">
          <CheckCircle className="w-3.5 h-3.5" />Production Stable
        </div>
      </div>

      <div className="mb-6 p-4 rounded-xl border border-yellow-500/30 bg-yellow-500/5 flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-yellow-400 shrink-0 mt-0.5" />
        <div>
          <p className="text-yellow-300 font-semibold text-sm">Instructions for AI Assistant</p>
          <ul className="text-yellow-600 text-xs mt-1 space-y-1 list-none">
            <li>1. Read this entire page before making ANY changes to this app.</li>
            <li>2. Never contradict the "Agreed Decisions" section without explicit user approval.</li>
            <li>3. GitHub: <span className="font-mono text-yellow-400">https://github.com/tonytekton/tekton-ai-trader/</span> — main = production, feature/bridge-v4.8-event-driven = Phase 11 work</li>
            <li>4. Always update this page and append to the Change Log when a change is made.</li>
            <li>5. Gate Protocol: Discuss → Agree → Implement → Verify. Never skip steps.</li>
          </ul>
        </div>
      </div>

      <Section icon={Server} title="System Architecture" color="blue">
        <p className="text-slate-500 text-xs mb-3">Three-tier Python architecture on Google Cloud VM. Base44 UI is a read-only reporting skin — never contains trading logic.</p>
        <div className="space-y-2">
          {[
            { name: 'Bridge',       file: 'tekton_bridge.py',       desc: 'REST port 8080 / cTrader port 5035. Single-Step Atomic Orders via rel_sl/rel_tp.',  cmd: 'sudo systemctl restart tekton-ai-trader-bridge.service', color: 'text-blue-400' },
            { name: 'Executor',     file: 'tekton_executor.py',     desc: 'Polls PENDING signals, calculates volume, calls bridge /trade/execute.',             cmd: 'sudo systemctl restart tekton-executor.service',          color: 'text-purple-400' },
            { name: 'Monitor',      file: 'tekton_monitor.py',      desc: 'AI-driven position management. Circuit breaker. Calls aiPositionReview per position.', cmd: 'nohup python3 tekton_monitor.py >> monitor.log 2>&1 &',  color: 'text-emerald-400' },
            { name: 'Backfill',     file: 'tekton_backfill.py',     desc: 'Fills market_data gaps every 15min across 50 symbols × 5 timeframes.',              cmd: 'Cron: */15 * * * *',                                      color: 'text-yellow-400' },
            { name: 'Daily Report', file: 'tekton_daily_report.py', desc: 'Sends Telegram P&L summary.',                                                        cmd: 'Cron: 0 22 * * * (22:00 UTC = 06:00 KL)',                 color: 'text-cyan-400' },
          ].map(s => (
            <div key={s.name} className="bg-slate-900/60 rounded-lg p-3 border border-slate-800">
              <div className="flex items-center gap-2 mb-1"><div className={`font-bold text-sm ${s.color}`}>{s.name}</div><div className="text-xs text-slate-500 font-mono">{s.file}</div></div>
              <div className="text-xs text-slate-400 mb-1">{s.desc}</div>
              <code className="text-[10px] text-slate-600 font-mono break-all">Restart: {s.cmd}</code>
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
        <Row label="DB Host" value="172.16.64.3 (internal) | DB: tekton-trader" mono />
        <Row label="Bridge URL" value="BRIDGE_URL env var — local: http://localhost:8080" mono />
        <Row label="Bridge Auth" value="Header: X-Bridge-Key (BRIDGE_KEY env var)" mono />
        <Row label="GitHub" value="https://github.com/tonytekton/tekton-ai-trader/" mono />
        <Row label="Sessions" value="https://github.com/tonytekton/tekton-sessions/" mono />
        <Row label="Timezone" value="Asia/Kuala Lumpur (UTC+8)" />
        <div className="mt-3 p-3 rounded-lg bg-slate-900 border border-slate-800 text-xs">
          <p className="text-slate-500 font-semibold mb-1">psql access pattern</p>
          <code className="text-emerald-400 font-mono">source ~/tekton-ai-trader/.env && PGPASSWORD=$CLOUD_SQL_DB_PASSWORD psql -h $CLOUD_SQL_HOST -U $CLOUD_SQL_DB_USER -d $CLOUD_SQL_DB_NAME -p {'${CLOUD_SQL_PORT:-5432}'}</code>
        </div>
      </Section>

      <Section icon={GitBranch} title="Branch Strategy" color="purple">
        <div className="space-y-2">
          {[
            { branch: 'main', desc: 'Production. All live scripts run from here.', status: 'Stable — v4.7 + hotfixes through 2026-03-20', color: 'text-emerald-400' },
            { branch: 'feature/bridge-v4.8-event-driven', desc: 'Bridge v4.8 refactor only. Nothing else.', status: 'Active dev — paused for hotfix stability', color: 'text-yellow-400' },
          ].map(b => (
            <div key={b.branch} className="bg-slate-900/60 rounded-lg p-3 border border-slate-800">
              <div className="flex items-center gap-2 mb-1"><span className={`font-mono text-xs font-bold ${b.color}`}>{b.branch}</span></div>
              <div className="text-xs text-slate-400">{b.desc}</div>
              <div className="text-xs text-slate-600 mt-1">{b.status}</div>
            </div>
          ))}
        </div>
        <div className="mt-2 p-3 rounded-lg bg-red-500/5 border border-red-500/20 text-xs text-red-400">
          <strong>Rollback:</strong> <span className="font-mono">git checkout main -- tekton_bridge.py && sudo systemctl restart tekton-ai-trader-bridge.service</span><br />
          <strong>Tag:</strong> v4.7-stable (SHA: 6e54b7d) — permanent rollback point
        </div>
      </Section>

      <Section icon={Layers} title="Data Flow & Signal Lifecycle" color="purple">
        <div className="flex flex-col gap-2">
          {[
            { step: '1', label: 'Market Data',              detail: 'tekton_backfill.py fills market_data every 15min. Raw integer prices from cTrader — divide by 10^digits before calculations.' },
            { step: '2', label: 'Strategy generates signal', detail: 'Inserts PENDING signal into signals table with sl_pips + tp_pips (never NULL).' },
            { step: '3', label: 'Executor picks up signal',  detail: 'Checks AUTO_TRADE, calculates volume (equity × risk_pct ÷ pip_value), calls bridge /trade/execute.' },
            { step: '4', label: 'Bridge executes',           detail: 'Sends Single-Step Protobuf. rel_sl/rel_tp received as PIPS (float), sent to cTrader as int(round(pips×10)) integer points. Signal UUID as comment.' },
            { step: '5', label: 'position_state{} updated',  detail: 'Bridge receives ProtoOAExecutionEvent push, updates in-memory position_state{}. This is the authoritative SL/TP source.' },
            { step: '6', label: 'Monitor manages position',  detail: 'Calls aiPositionReview per position. Actions: HOLD / CLOSE / ADJUST_SL / ADJUST_TP / PARTIAL_CLOSE. Logged to AiIntervention entity.' },
            { step: '7', label: 'Circuit Breaker',           detail: 'Drawdown breach → close all positions → drawdownAutopsy → freeze trading until APPROVED_RESUME.' },
            { step: '8', label: 'Base44 UI',                 detail: 'Read-only reporting via bridge /proxy/executions. Open position SL/TP enriched from position_state{} + ReconcileReq fallback.' },
          ].map(s => (
            <div key={s.step} className="flex items-start gap-3">
              <span className="w-6 h-6 rounded-full bg-purple-500/20 text-purple-400 text-xs font-bold flex items-center justify-center shrink-0">{s.step}</span>
              <div><span className="text-slate-200 font-medium text-xs">{s.label}</span><p className="text-slate-500 text-xs">{s.detail}</p></div>
            </div>
          ))}
        </div>
      </Section>

      <Section icon={Brain} title="Standard Signal Schema (All strategies MUST follow)" color="green">
        <Code>{`{
  "signal_uuid":      "AUTO_GENERATED_BY_DB",
  "symbol":           "EURUSD",
  "strategy":         "Tekton-ICT-FVG-v1",
  "signal_type":      "BUY",
  "timeframe":        "15min",
  "confidence_score": 82,
  "sl_pips":          15.0,
  "tp_pips":          27.0,
  "status":           "PENDING"
}`}</Code>
        <div className="mt-3 space-y-2">
          <div className="p-3 rounded-lg bg-red-500/5 border border-red-500/20 text-xs text-red-400"><strong>CRITICAL:</strong> Never insert signals with NULL sl_pips or tp_pips — executor skips them.</div>
          <div className="p-3 rounded-lg bg-red-500/5 border border-red-500/20 text-xs text-red-400"><strong>CRITICAL:</strong> confidence_score is an INTEGER (0–100). Not a decimal like 0.82.</div>
          <div className="p-3 rounded-lg bg-blue-500/5 border border-blue-500/20 text-xs text-blue-300"><strong>field name:</strong> signal_type (not side/direction). Values: BUY or SELL. MIN_RR = 1.5 on all strategies.</div>
        </div>
      </Section>

      <Section icon={Zap} title="cTrader Price Formats — Critical Reference" color="red">
        <div className="space-y-2 mb-3">
          <div className="bg-slate-900/60 rounded-lg p-3 border border-slate-800">
            <div className="text-xs font-bold text-red-400 mb-1">RAW INTEGER — divide by 10^digits</div>
            <div className="text-xs text-slate-400">ProtoOADeal.executionPrice, ProtoOAPosition.stopLoss/takeProfit, ProtoOATradeData.openPrice, market data candles</div>
          </div>
          <div className="bg-slate-900/60 rounded-lg p-3 border border-slate-800">
            <div className="text-xs font-bold text-emerald-400 mb-1">DECIMAL DOUBLE — use as-is</div>
            <div className="text-xs text-slate-400">ProtoOAOrder.executionPrice, ProtoOAAmendPositionSLTPReq.stopLoss/takeProfit</div>
          </div>
        </div>
        <div className="p-3 rounded-lg bg-red-500/5 border border-red-500/20 text-xs text-red-300">
          <strong>RULE:</strong> Always use <span className="font-mono">raw_to_decimal()</span> / <span className="font-mono">decimal_to_raw()</span> helpers. Never inline conversions.
        </div>
        <div className="mt-3">
          <p className="text-xs font-bold text-slate-300 mb-2">relativeStopLoss / relativeTakeProfit — DEFINITIVE RULE (confirmed 2026-03-20)</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-slate-700">{['Layer','Format','Example (15 pip SL)'].map(h => <th key={h} className="text-left py-2 pr-4 text-slate-500 font-semibold">{h}</th>)}</tr></thead>
              <tbody>
                {[
                  ['Signal in DB', 'sl_pips float', '15.0'],
                  ['Executor → Bridge (rel_sl)', 'PIPS, float, 1dp', '15.0'],
                  ['Bridge → cTrader (relativeStopLoss)', 'int(round(pips × 10))', '150'],
                ].map(([l,f,e]) => (
                  <tr key={l} className="border-b border-slate-800/40">
                    <td className="py-2 pr-4 text-slate-300">{l}</td>
                    <td className="py-2 pr-4 font-mono text-emerald-400">{f}</td>
                    <td className="py-2 font-mono text-blue-400">{e}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 space-y-1">
            <div className="text-xs text-red-400 p-2 bg-red-500/5 border border-red-500/20 rounded">❌ <strong>"has type float, but expected one of: int"</strong> — float sent instead of int to int32 field</div>
            <div className="text-xs text-red-400 p-2 bg-red-500/5 border border-red-500/20 rounded">❌ <strong>"Relative stop loss has invalid precision"</strong> — integer points sent without ×10 conversion</div>
          </div>
        </div>
        <div className="mt-3 p-3 rounded-lg bg-yellow-500/5 border border-yellow-500/20 text-xs text-yellow-300">
          <strong>SL/TP on open positions:</strong> ReconcileReq does NOT reliably return stopLoss/takeProfit on this broker. Use <span className="font-mono">position_state{'{}'}</span> as primary source. ReconcileReq as fallback after bridge restart.
        </div>
      </Section>

      <Section icon={Database} title="Settings Architecture — Single Source of Truth" color="cyan">
        <p className="text-xs text-slate-500 mb-3">All settings live in the <span className="font-mono text-cyan-400">settings</span> table in SQL DB, row id=1. Base44 entities are <strong className="text-red-400">DEPRECATED</strong> — do not use.</p>
        <Code>{`auto_trade               BOOLEAN   DEFAULT FALSE
friday_flush             BOOLEAN   DEFAULT FALSE
risk_pct                 DOUBLE    DEFAULT 0.01
target_reward            DOUBLE    DEFAULT 1.8
daily_drawdown_limit     DOUBLE    DEFAULT 0.05
max_session_exposure_pct DOUBLE    DEFAULT 4.0
max_lots                 DOUBLE    DEFAULT 5000   ← current live: 6 (testing cap)
min_sl_pips              DOUBLE    DEFAULT 8.0
news_blackout_mins       INT       DEFAULT 30`}</Code>
        <div className="mt-2 p-3 rounded-lg bg-yellow-500/5 border border-yellow-500/20 text-xs text-yellow-300">
          <strong>max_lots warning:</strong> Default = 5000 (large account). Current live value = 6 (Tony's testing cap, set 2026-03-20). If DB shows 50 or 5 it has been incorrectly reset — fix via POST /data/settings.
        </div>
      </Section>

      <Section icon={Zap} title="Bridge /trade/execute Payload" color="yellow">
        <Code>{`// Request
{
  "symbol":  "EURUSD",
  "side":    "BUY",          // NOT "direction"
  "volume":  0.43,
  "comment": "signal-uuid",
  "rel_sl":  12.5,           // PIPS float — bridge converts to int points internally
  "rel_tp":  22.5
}

// Response
{
  "success":     true,
  "position_id": 593655453,
  "entry_price": 1.08432    // decimal double — store directly as avg_fill_price
}`}</Code>
      </Section>

      <Section icon={Shield} title="Agreed Decisions (DO NOT change without explicit approval)" color="green">
        <Decision id="1"  text="relativeStopLoss format: executor sends pips (float 1dp). Bridge converts to int(round(pips×10)) integer points before protobuf. FINAL." />
        <Decision id="2"  text="SL/TP source for UI: position_state{} is primary (live ExecutionEvents). ReconcileReq as fallback after bridge restart. ReconcileReq unreliable on this broker for SL/TP." />
        <Decision id="3"  text="Settings source of truth: SQL settings table id=1 only. Base44 entities DEPRECATED." />
        <Decision id="4"  text="max_lots: default 5000 (large account). Current live: 6 (testing cap). TradingSettings UI default = 5000." />
        <Decision id="5"  text="Volume formula: risk_cash / (sl_pips × pip_value_per_lot). pip_value from live bridge spec. 1 lot = 10,000,000 centilots." />
        <Decision id="6"  text="entry_price: from ProtoOAOrder.executionPrice via ExecutionEvent — decimal double, use as-is. Never divide by 10^digits." />
        <Decision id="7"  text="MIN_RR = 1.5 minimum on all strategies." />
        <Decision id="8"  text="Friday Flush: 16:00 UTC every Friday — closes all open positions." />
        <Decision id="9"  text="Feature branch policy: feature/bridge-v4.8-event-driven for Phase 11 only. main untouched until smoke test passes." />
        <Decision id="10" text="confidence_score is INTEGER 0–100. Never a decimal like 0.82." />
        <Decision id="11" text="Execution Journal deduplication: strip open position IDs from closed_trades before merge. Deduplicate within closed_trades by position ID." />
      </Section>

      <Section icon={Wrench} title="Hotfixes Applied to main (2026-03-16 to 2026-03-20)" color="orange">
        <HF id="01" text="Restore .env file after repo reset — missing .env caused Bridge to lose all config and auth tokens." />
        <HF id="02" text="Fix API auth header: Authorization: Bearer → X-Bridge-Key." />
        <HF id="03" text="Fix pipPosition value (4 → 5 for EURUSD) — incorrect value caused 10× position sizing errors." />
        <HF id="04" text="Add max_lots column to settings table — was missing, executor defaulted to 50 lots." />
        <HF id="05" text="Replace hardcoded PIP_SIZE_MAP with live bridge specs — static map wrong for many symbols." />
        <HF id="06" text="Fix volume calculation: 1 lot = 10,000,000 centilots (not 100,000). Wrong multiplier caused massive sizing errors." />
        <HF id="07" sha="869f71d" text="relativeStopLoss 'invalid precision': executor was multiplying pips×10. Fix: send raw pips as float 1dp." />
        <HF id="08" sha="353328f" text="relativeStopLoss int32 rejection: bridge was still sending float. Fix: int(round(pips×10)) in bridge." />
        <HF id="09" sha="353328f" text="P&L showing €0.00 on closed trades: closePrice field name fallback added." />
        <HF id="10" sha="6dfc562→d8bad81" text="SL/TP showing None on open positions: fixed camelCase→snake_case field names in enrichment + added ReconcileReq fallback layer." />
        <HF id="11" text="TradingSettings max_lots UI default fixed: 5.0 → 5000." />
        <HF id="12" sha="157cd42" text="Execution Journal duplicate rows: deduplicate open_trades vs closed_trades by position ID after merge." />
      </Section>

      <Section icon={ScrollText} title="Change Log" color="blue">
        <div className="space-y-0">
          {[
            { date: '2026-03-20', change: 'HF-07→12: relSL int32 fix, SL/TP enrichment fix, deduplication fix, max_lots UI fix. System Context updated to v4.8.' },
            { date: '2026-03-19', change: 'HF-07: relativeStopLoss "invalid precision" root cause found. Pips sent as float 1dp.' },
            { date: '2026-03-18', change: 'HF-04: max_lots column added to DB. Session exposure cap clarified.' },
            { date: '2026-03-17', change: 'ICT FVG strategy rewrite. EMA Pullback strategy deployed. Price scaling issues identified.' },
            { date: '2026-03-16', change: 'HF-01–03: .env restored, X-Bridge-Key header fix, pipPosition audit.' },
            { date: '2026-03-13', change: 'Git conflict resolved. V3 CR backlog documented. SaaS roadmap noted.' },
            { date: '2026-03-12', change: 'Gate Protocol + Lester roles established. Base44 entities deprecated.' },
          ].map(e => (
            <div key={e.date} className="flex items-start gap-3 py-2 border-b border-slate-800/40 last:border-0">
              <span className="font-mono text-xs text-slate-600 shrink-0 w-24">{e.date}</span>
              <span className="text-xs text-slate-400">{e.change}</span>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
