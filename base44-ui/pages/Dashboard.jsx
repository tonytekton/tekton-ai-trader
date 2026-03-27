import React, { useState, useEffect, useCallback } from 'react';
import { base44 } from '@/api/base44Client';
import { AnalyticsRecommendation } from '@/api/entities';
import { DollarSign, Activity, Zap, RefreshCw, ShieldAlert, TrendingDown, Layers, AlertTriangle, PowerOff, Calendar, Radio } from 'lucide-react';

const fmt = (n, prefix = '$') =>
  n != null ? `${prefix}${parseFloat(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '\u2014';

const fmtPct = (n) => n != null ? `${parseFloat(n).toFixed(2)}%` : '\u2014';

function fmtCountdown(mins) {
  if (mins < 0) return `${Math.abs(mins)}m ago`;
  if (mins < 60) return `in ${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m > 0 ? `in ${h}h ${m}m` : `in ${h}h`;
}

function MetricCard({ label, value, sub, icon: Icon, color }) {
  const colors = {
    green:  'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
    blue:   'text-blue-400 bg-blue-500/10 border-blue-500/20',
    yellow: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
    cyan:   'text-cyan-400 bg-cyan-500/10 border-cyan-500/20',
    purple: 'text-purple-400 bg-purple-500/10 border-purple-500/20',
    red:    'text-red-400 bg-red-500/10 border-red-500/20',
    slate:  'text-slate-400 bg-slate-500/10 border-slate-500/20',
  };
  const c = colors[color] || colors.slate;
  return (
    <div className={`rounded-xl border p-4 ${c}`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold tracking-widest uppercase text-slate-500">{label}</span>
        {Icon && <Icon className="w-4 h-4 opacity-60" />}
      </div>
      <div className="text-xl font-bold text-slate-100 font-mono">{value ?? '\u2014'}</div>
      {sub && <div className="text-xs text-slate-600 mt-1">{sub}</div>}
    </div>
  );
}

function GaugeBar({ label, value, max, color, suffix = '%' }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  const barColors = { red: 'bg-red-500', amber: 'bg-amber-500', emerald: 'bg-emerald-500', blue: 'bg-blue-500', cyan: 'bg-cyan-500' };
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-slate-500">{label}</span>
        <span className="text-slate-300 font-mono">{value != null ? `${parseFloat(value).toFixed(1)}${suffix}` : '\u2014'} / {max}{suffix}</span>
      </div>
      <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${barColors[color] || 'bg-blue-500'}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function StatusBadge({ online }) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border ${
      online ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${online ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
      {online ? 'Bridge Online' : 'Bridge Offline'}
    </span>
  );
}

// AI_BUDGET constants
const AI_MONTHLY_BUDGET  = 75000;
const AI_YEARLY_BUDGET   = 900000;
const AI_DAILY_BUDGET    = Math.round(AI_YEARLY_BUDGET / 260); // 3461
const MSG_MONTHLY_BUDGET = 1925;

function AiCreditsMonitor({ data }) {
  // data comes from getUsageStats backend fn
  // fallback: use hardcoded values from last known state if fn not yet built
  const aiUsed   = data?.ai_credits_used   ?? null;
  const aiTotal  = data?.ai_credits_total  ?? AI_MONTHLY_BUDGET;
  const msgUsed  = data?.msg_credits_used  ?? null;
  const msgTotal = data?.msg_credits_total ?? MSG_MONTHLY_BUDGET;

  const aiPct  = aiUsed  != null ? +((aiUsed  / aiTotal)  * 100).toFixed(1) : null;
  const msgPct = msgUsed != null ? +((msgUsed / msgTotal) * 100).toFixed(1) : null;

  // Daily burn estimate: if we know used and days elapsed this month
  const now = new Date();
  const dayOfMonth = now.getDate();
  const aiDailyBurn = aiUsed != null && dayOfMonth > 0 ? Math.round(aiUsed / dayOfMonth) : null;
  const aiDailyPct  = aiDailyBurn != null ? +((aiDailyBurn / AI_DAILY_BUDGET) * 100).toFixed(1) : null;

  const aiColor  = aiPct  != null && aiPct  >= 80 ? 'red' : aiPct  >= 50 ? 'amber' : 'emerald';
  const msgColor = msgPct != null && msgPct >= 80 ? 'red' : msgPct >= 50 ? 'amber' : 'emerald';
  const aiTextColor  = aiPct  >= 80 ? 'text-red-400' : aiPct  >= 50 ? 'text-amber-400' : 'text-emerald-400';
  const msgTextColor = msgPct >= 80 ? 'text-red-400' : msgPct >= 50 ? 'text-amber-400' : 'text-purple-400';

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-slate-500 text-sm">🤖</span>
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">AI Credits</p>
        </div>
        {aiPct != null && <span className={`text-xs font-bold ${aiTextColor}`}>{aiPct}% used</span>}
      </div>

      {/* AI integration credits */}
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-xs">
          <span className="text-slate-500">Integration (monthly)</span>
          <span className="text-slate-300 font-mono">{aiUsed != null ? aiUsed.toLocaleString() : '—'} / {aiTotal.toLocaleString()}</span>
        </div>
        <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
          <div className={`h-full rounded-full transition-all duration-500 ${aiColor === 'red' ? 'bg-red-500' : aiColor === 'amber' ? 'bg-amber-500' : 'bg-emerald-500'}`}
            style={{ width: `${Math.min(aiPct ?? 0, 100)}%` }} />
        </div>
      </div>

      {/* Daily budget gauge */}
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-xs">
          <span className="text-slate-500">Daily budget</span>
          <span className="text-slate-300 font-mono">{aiDailyBurn != null ? aiDailyBurn : '—'} / {AI_DAILY_BUDGET} avg</span>
        </div>
        <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
          <div className={`h-full rounded-full transition-all duration-500 ${aiDailyPct >= 100 ? 'bg-red-500' : aiDailyPct >= 80 ? 'bg-amber-500' : 'bg-cyan-500'}`}
            style={{ width: `${Math.min(aiDailyPct ?? 0, 100)}%` }} />
        </div>
      </div>

      {/* Message credits */}
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-xs">
          <span className="text-slate-500">Messages (monthly)</span>
          <span className={`font-mono text-xs ${msgTextColor}`}>{msgUsed != null ? msgUsed.toLocaleString() : '—'} / {msgTotal.toLocaleString()}</span>
        </div>
        <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
          <div className={`h-full rounded-full transition-all duration-500 ${msgColor === 'red' ? 'bg-red-500' : msgColor === 'amber' ? 'bg-amber-500' : 'bg-purple-500'}`}
            style={{ width: `${Math.min(msgPct ?? 0, 100)}%` }} />
        </div>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 gap-2 text-center">
        <div className="bg-slate-800/40 rounded-lg py-2 px-1">
          <div className="text-sm font-bold font-mono text-slate-200">{AI_DAILY_BUDGET}</div>
          <div className="text-[10px] text-slate-600 mt-0.5">daily budget</div>
        </div>
        <div className="bg-slate-800/40 rounded-lg py-2 px-1">
          <div className={`text-sm font-bold font-mono ${aiDailyPct != null && aiDailyPct > 100 ? 'text-red-400' : 'text-slate-200'}`}>
            {aiUsed != null ? (aiTotal - aiUsed).toLocaleString() : '—'}
          </div>
          <div className="text-[10px] text-slate-600 mt-0.5">remaining</div>
        </div>
      </div>
    </div>
  );
}


function AiRecommendationsWidget({ rec }) {
  if (!rec) return null;
  // Extract just the executive summary and priority actions from the full text
  const text = rec.recommendations || '';
  const execMatch = text.match(/###?\s*1\.\s*Executive Summary[\s\S]*?(?=###?\s*2\.|$)/i);
  const priorityMatch = text.match(/###?\s*7\.\s*Priority Action List[\s\S]*?(?=###?\s*\d+\.|$)/i);
  const execSummary = execMatch ? execMatch[0].replace(/###?\s*1\.\s*Executive Summary\s*/i,'').trim() : '';
  const priorityList = priorityMatch ? priorityMatch[0].replace(/###?\s*7\.\s*Priority Action List\s*/i,'').trim() : '';
  const flagged = rec.flagged_strategies || [];
  const genDate = rec.generated_at ? new Date(rec.generated_at).toLocaleString('en-GB', { day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit' }) : '';

  return (
    <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-5 mb-6">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="text-indigo-400 text-lg">🤖</span>
          <p className="text-xs font-semibold uppercase tracking-widest text-indigo-400">AI Strategy Insights</p>
          {flagged.length > 0 && (
            <span className="px-2 py-0.5 bg-red-500/10 border border-red-500/20 text-red-400 text-xs rounded-full">⚠️ {flagged.length} flagged</span>
          )}
        </div>
        <span className="text-xs text-slate-600">{genDate}</span>
      </div>
      {flagged.length > 0 && (
        <div className="flex gap-1 flex-wrap mb-3">
          {flagged.map(s => (
            <span key={s} className="px-2 py-0.5 bg-red-500/10 border border-red-500/20 text-red-400 text-xs rounded">{s}</span>
          ))}
        </div>
      )}
      {execSummary && (
        <p className="text-xs text-slate-400 leading-relaxed mb-3 line-clamp-3">{execSummary}</p>
      )}
      {priorityList && (
        <div>
          <p className="text-xs font-semibold text-indigo-400/70 uppercase mb-1">Priority Actions</p>
          <pre className="text-xs text-slate-400 whitespace-pre-wrap font-sans leading-relaxed line-clamp-5">{priorityList}</pre>
        </div>
      )}
      <a href="/analytics" className="inline-block mt-3 text-xs text-indigo-400 hover:text-indigo-300 underline">→ Full analysis on Analytics page</a>
    </div>
  );
}


function CalendarStrip({ events }) {
  if (!events || events.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
        <div className="flex items-center gap-2 mb-3">
          <Calendar className="w-4 h-4 text-slate-500" />
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">Upcoming News</p>
        </div>
        <p className="text-xs text-slate-600">No high-impact events in the next 24 hours.</p>
      </div>
    );
  }
  const next24h = events.filter(e => e.minutes_until > -30 && e.minutes_until < 1440).sort((a, b) => a.minutes_until - b.minutes_until).slice(0, 5);
  if (next24h.length === 0) return null;
  const imminentHigh = next24h.find(e => e.impact_level === 'high' && e.minutes_until >= 0 && e.minutes_until <= 30);
  return (
    <div className={`rounded-xl border p-5 ${imminentHigh ? 'border-red-500/30 bg-red-500/5' : 'border-slate-800 bg-slate-900/50'}`}>
      <div className="flex items-center gap-2 mb-3">
        <Calendar className="w-4 h-4 text-slate-500" />
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">Upcoming News {imminentHigh ? '\u2014 \u26a0\ufe0f High Impact Imminent' : ''}</p>
        <span className="text-[10px] text-slate-600 ml-auto">Next 24h</span>
      </div>
      <div className="flex flex-col gap-2">
        {next24h.map(ev => {
          const isHigh = ev.impact_level === 'high';
          const isImminent = ev.minutes_until >= 0 && ev.minutes_until <= 30;
          return (
            <div key={ev.id || `${ev.currency}-${ev.indicator_name}-${ev.minutes_until}`}
              className={`flex items-center justify-between text-xs px-3 py-2 rounded-lg border ${
                isImminent && isHigh ? 'border-red-500/30 bg-red-500/5 text-red-300'
                  : isHigh ? 'border-amber-500/20 bg-amber-500/5 text-amber-300'
                  : 'border-slate-800 bg-slate-800/30 text-slate-400'}`}>
              <div className="flex items-center gap-2">
                <span className="font-bold font-mono w-8">{ev.currency}</span>
                <span>{ev.indicator_name}</span>
              </div>
              <span className="font-mono">{fmtCountdown(ev.minutes_until)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ApiRateMonitor({ data }) {
  if (!data) return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
      <div className="flex items-center gap-2 mb-3">
        <Radio className="w-4 h-4 text-slate-500" />
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">cTrader API Rate</p>
      </div>
      <p className="text-xs text-slate-600">No data</p>
    </div>
  );
  const currentMin = data.current_minute ?? 0;
  const maxPerMin = data.rate_limit_info?.max_per_minute ?? 75;
  const usagePct = data.rate_limit_info?.current_usage_percent ?? 0;
  const last5 = data.last_5_minutes ?? 0;
  const lastHour = data.last_hour ?? 0;
  const last24h = data.last_24_hours ?? 0;
  const sparkline = data.calls_per_minute_last_hour ?? [];
  const byEndpoint = data.by_endpoint ?? {};
  const rateColor = usagePct >= 80 ? 'red' : usagePct >= 50 ? 'amber' : 'emerald';
  const rateTextColor = usagePct >= 80 ? 'text-red-400' : usagePct >= 50 ? 'text-amber-400' : 'text-emerald-400';
  const sparkMax = Math.max(...sparkline, 1);
  const sparkBars = sparkline.slice(-30);
  const topEndpoints = Object.entries(byEndpoint).sort((a, b) => b[1].count_1hour - a[1].count_1hour).slice(0, 4);
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Radio className="w-4 h-4 text-slate-500" />
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">cTrader API Rate</p>
        </div>
        <span className={`text-xs font-bold ${rateTextColor}`}>{usagePct}% of limit</span>
      </div>
      <GaugeBar label={`${currentMin} calls/min`} value={usagePct} max={100} color={rateColor} suffix="%" />
      <div className="grid grid-cols-3 gap-2 text-center">
        {[{ label: '5 min', value: last5 }, { label: '1 hour', value: lastHour }, { label: '24 hours', value: last24h }].map(({ label, value }) => (
          <div key={label} className="bg-slate-800/40 rounded-lg py-2 px-1">
            <div className="text-sm font-bold font-mono text-slate-200">{value.toLocaleString()}</div>
            <div className="text-[10px] text-slate-600 mt-0.5">{label}</div>
          </div>
        ))}
      </div>
      {sparkBars.length > 0 && (
        <div>
          <p className="text-[10px] text-slate-600 mb-1">Calls/min - last 30 min</p>
          <div className="flex items-end gap-px h-10">
            {sparkBars.map((v, i) => {
              const h = Math.max((v / sparkMax) * 100, 4);
              const col = v >= maxPerMin * 0.8 ? 'bg-red-500' : v >= maxPerMin * 0.5 ? 'bg-amber-500' : 'bg-emerald-500/60';
              return <div key={i} className={`flex-1 rounded-sm ${col} transition-all`} style={{ height: `${h}%` }} title={`${v} calls`} />;
            })}
          </div>
        </div>
      )}
      {topEndpoints.length > 0 && (
        <div>
          <p className="text-[10px] text-slate-600 mb-1.5">Top endpoints (1hr)</p>
          <div className="flex flex-col gap-1">
            {topEndpoints.map(([ep, stats]) => (
              <div key={ep} className="flex items-center justify-between text-xs">
                <span className="text-slate-500 font-mono truncate flex-1 mr-2">{ep}</span>
                <div className="flex items-center gap-1.5 shrink-0">
                  <span className="text-slate-300 font-mono">{stats.count_1hour}x</span>
                  {stats.failures > 0 && <span className="text-red-400 text-[10px]">{stats.failures} err</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [status, setStatus] = useState(null);
  const [settings, setSettings] = useState(null);
  const [autopsy, setAutopsy] = useState(null);
  const [openCount, setOpenCount] = useState(null);
  const [calendar, setCalendar] = useState([]);
  const [rateStats, setRateStats] = useState(null);
  const [latestRec, setLatestRec] = useState(null);
  const [usageStats, setUsageStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [halting, setHalting] = useState(false);
  const [haltDone, setHaltDone] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [sRes, settRes, calRes, rateRes] = await Promise.allSettled([
        base44.functions.invoke('getAccountStatus'),
        base44.functions.invoke('loadAllSettings'),
        base44.functions.invoke('getEconomicCalendar'),
        base44.functions.invoke('getApiRateStats'),
      ]);
      if (sRes.status === 'fulfilled' && sRes.value?.data) {
        const d = sRes.value.data?.data ?? sRes.value.data;
        setMetrics(d);   // metrics and status are now the same object
        setStatus(d);
      }
      if (settRes.status === 'fulfilled' && settRes.value?.data && !settRes.value.data.error) { setSettings(settRes.value.data); }
      if (calRes.status === 'fulfilled' && calRes.value?.data) { const raw = calRes.value.data?.data ?? calRes.value.data; setCalendar(Array.isArray(raw) ? raw : []); }
      if (rateRes.status === 'fulfilled' && rateRes.value?.data && !rateRes.value.data.error) { setRateStats(rateRes.value.data); }
      try { const aRes = await base44.entities.DrawdownAutopsy.filter({ status: 'AWAITING_REVIEW' }); setAutopsy(aRes?.length > 0 ? aRes[0] : null); } catch { setAutopsy(null); }
      // open_count comes directly from getAccountStatus — no extra call needed
      setLastUpdated(new Date());
      try { const recRes = await AnalyticsRecommendation.list({ sort: "-created_date", limit: 1 }); setLatestRec(recRes?.length > 0 ? recRes[0] : null); } catch { setLatestRec(null); }
      try { const usageRes = await base44.functions.invoke('getUsageStats'); if (usageRes?.ok) setUsageStats(usageRes); } catch { setUsageStats(null); }
    } catch (e) { console.error('fetchAll error', e); } finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchAll(); const id = setInterval(fetchAll, 30000); return () => clearInterval(id); }, [fetchAll]);

  const handleHalt = async () => {
    if (!window.confirm('HALT ALL TRADING?\n\nThis will disable auto_trade immediately. Confirm?')) return;
    setHalting(true);
    try {
      await base44.functions.invoke('saveAllSettings', { auto_trade: false, friday_flush: settings?.friday_flush ?? false, risk_pct: settings?.risk_pct ?? 0.01, target_reward: settings?.target_reward ?? 1.8, daily_drawdown_limit: settings?.daily_drawdown_limit ?? 0.05, max_session_exposure_pct: settings?.max_session_exposure_pct ?? 4.0 });
      setSettings(prev => prev ? { ...prev, auto_trade: false } : prev);
      setHaltDone(true);
      setTimeout(() => setHaltDone(false), 5000);
    } catch (e) { alert('Halt failed: ' + e.message); } finally { setHalting(false); }
  };

  const drawdownPct = status?.drawdown_pct ?? 0;
  const drawdownLimit = settings?.daily_drawdown_limit != null ? settings.daily_drawdown_limit * 100 : 5.0;
  const derivedOpenCount = status?.open_count ?? openCount ?? 0;
  const sessionExp = derivedOpenCount > 0 && settings?.risk_pct != null ? derivedOpenCount * (settings.risk_pct * 100) : null;
  const sessionLimit = settings?.max_session_exposure_pct ?? 4.0;
  const drawdownColor = drawdownPct >= drawdownLimit * 0.8 ? 'red' : drawdownPct >= drawdownLimit * 0.5 ? 'amber' : 'emerald';
  const sessionColor = sessionExp != null && sessionExp >= sessionLimit * 0.8 ? 'red' : sessionExp != null && sessionExp >= sessionLimit * 0.5 ? 'amber' : 'blue';
  const bridgeOnline = metrics != null && !metrics?.error;
  const autoTrade = settings?.auto_trade ?? false;
  // Daily P&L: equity - balance. If bridge returns equal values, show margin_used as context.
  const rawPnl = (metrics?.equity != null && metrics?.balance != null && metrics.equity !== metrics.balance)
    ? metrics.equity - metrics.balance
    : metrics?.daily_pnl ?? null;
  const dailyPnl = rawPnl;
  const imminentHighEvents = calendar.filter(e => e.impact_level === 'high' && e.minutes_until >= 0 && e.minutes_until <= 30);

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-7xl mx-auto">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Command Center</h1>
          <p className="text-xs text-slate-600 mt-1">{lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : 'Loading\u2026'}</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <StatusBadge online={bridgeOnline} />
          <button onClick={fetchAll} className="p-2 rounded-lg border border-slate-800 text-slate-500 hover:text-slate-300 hover:border-slate-600 transition-all">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>
      {autopsy && (
        <div className="mb-4 px-4 py-3 rounded-xl border border-red-500/40 bg-red-500/10 text-red-300 text-sm flex flex-col gap-1">
          <span className="font-bold">Circuit Breaker Fired - Trading Frozen</span>
          <span>Drawdown autopsy is AWAITING REVIEW. Trading will remain halted until you approve resumption.</span>
          <span className="text-xs text-red-400/70">Triggered: {new Date(autopsy.triggered_at).toLocaleString()}</span>
        </div>
      )}
      {imminentHighEvents.length > 0 && (
        <div className="mb-4 px-4 py-3 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-300 text-sm flex flex-col gap-1">
          <span className="font-bold">High-Impact News Within 30 Minutes</span>
          <span>{imminentHighEvents.map(e => `${e.currency} ${e.indicator_name} (${fmtCountdown(e.minutes_until)})`).join(' - ')}</span>
          <span className="text-xs text-amber-400/70">Consider pausing new entries until the news window clears.</span>
        </div>
      )}
      <div className={`flex flex-wrap items-center justify-between gap-3 px-4 py-3 rounded-xl border mb-6 ${autoTrade ? 'border-emerald-500/20 bg-emerald-500/5' : 'border-slate-800 bg-slate-900/50'}`}>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${autoTrade ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
          <span className={`text-sm font-semibold ${autoTrade ? 'text-emerald-400' : 'text-slate-500'}`}>Auto Trade {autoTrade ? 'ENABLED' : 'DISABLED'}</span>
          {autoTrade && <span className="text-xs text-slate-600">- system is executing signals autonomously</span>}
        </div>
        <button onClick={handleHalt} disabled={!autoTrade || halting || haltDone} className={`flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full border transition-all ${haltDone ? 'bg-slate-800 text-slate-500 border-slate-700' : autoTrade ? 'bg-red-500/10 text-red-400 border-red-500/20 hover:bg-red-500/20' : 'bg-slate-800 text-slate-600 border-slate-700 cursor-not-allowed'}`}>
          <PowerOff className="w-3.5 h-3.5" />
          {haltDone ? 'Trading Halted' : halting ? 'Halting...' : 'Halt Trading'}
        </button>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <MetricCard label="Balance" value={fmt(metrics?.balance)} sub="Account balance" icon={DollarSign} color="green" />
        <MetricCard label="Equity" value={fmt(metrics?.equity)} sub="Net asset value" icon={Activity} color="blue" />
        <MetricCard label="Free Margin" value={fmt(metrics?.free_margin)} sub="Available capital" icon={Zap} color="cyan" />
        <MetricCard label="Daily P&L" value={fmt(dailyPnl)} sub="Today's performance" icon={DollarSign} color={dailyPnl == null ? 'slate' : dailyPnl >= 0 ? 'green' : 'red'} />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 mb-6">
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5 flex flex-col gap-4">
          <div className="flex items-center gap-2"><TrendingDown className="w-4 h-4 text-slate-500" /><p className="text-xs font-semibold uppercase tracking-widest text-slate-500">Drawdown</p></div>
          <GaugeBar label="Daily Drawdown" value={drawdownPct} max={drawdownLimit} color={drawdownColor} />
          <p className="text-xs text-slate-600">Circuit breaker fires at {drawdownLimit}%</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5 flex flex-col gap-4">
          <div className="flex items-center gap-2"><Layers className="w-4 h-4 text-slate-500" /><p className="text-xs font-semibold uppercase tracking-widest text-slate-500">Session Exposure</p></div>
          <GaugeBar label="Open Risk" value={sessionExp ?? 0} max={sessionLimit} color={sessionColor} />
          <p className="text-xs text-slate-600">New trades blocked at {sessionLimit}% total exposure</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-5 flex flex-col gap-4">
          <div className="flex items-center gap-2"><ShieldAlert className="w-4 h-4 text-slate-500" /><p className="text-xs font-semibold uppercase tracking-widest text-slate-500">Exposure</p></div>
          <div className="flex flex-col gap-3">
            <div className="flex justify-between text-xs"><span className="text-slate-500">Open Positions</span><span className="text-slate-200 font-mono font-bold">{derivedOpenCount}</span></div>
            <div className="flex justify-between text-xs"><span className="text-slate-500">Margin Used</span><span className="text-slate-200 font-mono">{fmt(metrics?.margin_used)}</span></div>
            <div className="flex justify-between text-xs"><span className="text-slate-500">Margin / Balance</span><span className="text-slate-200 font-mono">{metrics?.margin_used != null && metrics?.balance != null ? fmtPct((metrics.margin_used / metrics.balance) * 100) : '\u2014'}</span></div>
          </div>
        </div>
        <ApiRateMonitor data={rateStats} />
        <AiCreditsMonitor data={usageStats} />
      </div>
      <AiRecommendationsWidget rec={latestRec} />
      <CalendarStrip events={calendar} />
      <p className="text-center text-xs text-slate-700 mt-6">Auto-refreshes every 30s - To change risk settings go to Trading Settings</p>
    </div>
  );
}

