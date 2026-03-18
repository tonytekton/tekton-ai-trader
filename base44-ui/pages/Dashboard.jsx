import React, { useState, useEffect, useCallback } from 'react';
import { base44 } from '@/api/base44Client';
import { DollarSign, Activity, Zap, RefreshCw, ShieldAlert, TrendingDown, Layers, AlertTriangle, PowerOff, Calendar } from 'lucide-react';

// ── Helpers ──────────────────────────────────────────────────────────────────
const fmt = (n, prefix = '$') =>
  n != null ? `${prefix}${parseFloat(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';

const fmtPct = (n) => n != null ? `${parseFloat(n).toFixed(2)}%` : '—';

function fmtCountdown(mins) {
  if (mins < 0) return `${Math.abs(mins)}m ago`;
  if (mins < 60) return `in ${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m > 0 ? `in ${h}h ${m}m` : `in ${h}h`;
}

// ── Sub-components ────────────────────────────────────────────────────────────
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
    <div className={`rounded-xl border p-4 flex flex-col gap-2 ${c}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-widest opacity-70">{label}</span>
        {Icon && <Icon className="w-4 h-4 opacity-60" />}
      </div>
      <div className="text-2xl font-bold tracking-tight">{value ?? '—'}</div>
      {sub && <div className="text-xs opacity-50">{sub}</div>}
    </div>
  );
}

function GaugeBar({ label, value, max, color, suffix = '%' }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  const barColors = {
    red:    'bg-red-500',
    amber:  'bg-amber-500',
    emerald:'bg-emerald-500',
    blue:   'bg-blue-500',
  };
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex justify-between text-xs text-slate-400">
        <span>{label}</span>
        <span className="font-mono font-semibold">{value != null ? `${parseFloat(value).toFixed(2)}${suffix}` : '—'} / {max}{suffix}</span>
      </div>
      <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${barColors[color] || 'bg-blue-500'}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function StatusBadge({ online }) {
  return (
    <div className={`flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border ${online ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' : 'text-red-400 bg-red-500/10 border-red-500/20'}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${online ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
      {online ? 'Bridge Online' : 'Bridge Offline'}
    </div>
  );
}

function CalendarStrip({ events }) {
  if (!events || events.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 mb-6">
        <div className="flex items-center gap-2 mb-3">
          <Calendar className="w-4 h-4 text-slate-500" />
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">Upcoming News</p>
        </div>
        <p className="text-xs text-slate-600">No high-impact events in the next 24 hours.</p>
      </div>
    );
  }

  // Show next 5 events — prioritise HIGH impact, within next 24h
  const now = Date.now();
  const next24h = events
    .filter(e => e.minutes_until > -30 && e.minutes_until < 1440)
    .sort((a, b) => a.minutes_until - b.minutes_until)
    .slice(0, 5);

  if (next24h.length === 0) return null;

  // Warn if any HIGH impact event is within 30 minutes
  const imminentHigh = next24h.find(e => e.impact_level === 'high' && e.minutes_until >= 0 && e.minutes_until <= 30);

  return (
    <div className={`rounded-xl border p-4 mb-6 ${imminentHigh ? 'border-red-500/30 bg-red-500/5' : 'border-slate-800 bg-slate-900/50'}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Calendar className={`w-4 h-4 ${imminentHigh ? 'text-red-400' : 'text-slate-500'}`} />
          <p className={`text-xs font-semibold uppercase tracking-widest ${imminentHigh ? 'text-red-400' : 'text-slate-500'}`}>
            Upcoming News {imminentHigh ? '— ⚠️ High Impact Imminent' : ''}
          </p>
        </div>
        <span className="text-[10px] text-slate-600 font-mono">Next 24h</span>
      </div>
      <div className="flex flex-col gap-2">
        {next24h.map(ev => {
          const isHigh = ev.impact_level === 'high';
          const isImminent = ev.minutes_until >= 0 && ev.minutes_until <= 30;
          return (
            <div
              key={ev.id}
              className={`flex items-center justify-between rounded-lg px-3 py-2 border text-xs
                ${isHigh && isImminent ? 'bg-red-500/10 border-red-500/20' :
                  isHigh ? 'bg-slate-800/60 border-slate-700/50' :
                  'bg-slate-900/40 border-slate-800/50'}`}
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className={`shrink-0 font-bold px-1.5 py-0.5 rounded text-[10px] border
                  ${isHigh ? 'text-red-400 bg-red-500/10 border-red-500/20' : 'text-amber-400 bg-amber-500/10 border-amber-500/20'}`}>
                  {ev.currency}
                </span>
                <span className="text-slate-300 truncate">{ev.indicator_name}</span>
              </div>
              <span className={`shrink-0 font-mono font-semibold ml-3 ${isImminent ? 'text-red-400' : 'text-slate-500'}`}>
                {fmtCountdown(ev.minutes_until)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const [metrics, setMetrics]       = useState(null);
  const [status, setStatus]         = useState(null);
  const [settings, setSettings]     = useState(null);
  const [autopsy, setAutopsy]       = useState(null);
  const [openCount, setOpenCount]   = useState(null);
  const [calendar, setCalendar]     = useState([]);
  const [loading, setLoading]       = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [halting, setHalting]       = useState(false);
  const [haltDone, setHaltDone]     = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [mRes, sRes, settRes, calRes] = await Promise.allSettled([
        base44.functions.invoke('getAccountMetrics'),
        base44.functions.invoke('getAccountStatus'),
        base44.functions.invoke('loadAllSettings'),
        base44.functions.invoke('getEconomicCalendar'),
      ]);

      if (mRes.status === 'fulfilled' && mRes.value?.data) {
        const d = mRes.value.data?.data ?? mRes.value.data;
        setMetrics(d);
      }
      if (sRes.status === 'fulfilled' && sRes.value?.data) {
        setStatus(sRes.value.data?.data ?? sRes.value.data);
      }
      if (settRes.status === 'fulfilled' && settRes.value?.data && !settRes.value.data.error) {
        setSettings(settRes.value.data);
      }
      if (calRes.status === 'fulfilled' && calRes.value?.data) {
        const raw = calRes.value.data?.data ?? calRes.value.data;
        setCalendar(Array.isArray(raw) ? raw : []);
      }

      // Check for active DrawdownAutopsy awaiting review
      try {
        const aRes = await base44.entities.DrawdownAutopsy.filter({ status: 'AWAITING_REVIEW' });
        setAutopsy(aRes?.length > 0 ? aRes[0] : null);
      } catch { setAutopsy(null); }

      // Open positions count from signals
      try {
        const sigRes = await base44.functions.invoke('getSignals', { status: 'EXECUTED', limit: 200 });
        const sigs = sigRes?.data;
        const arr = Array.isArray(sigs) ? sigs : Array.isArray(sigs?.signals) ? sigs.signals : [];
        setOpenCount(arr.length);
      } catch { setOpenCount(null); }

      setLastUpdated(new Date());
    } catch (e) {
      console.error('fetchAll error', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 30000);
    return () => clearInterval(id);
  }, [fetchAll]);

  const handleHalt = async () => {
    if (!window.confirm('⚠️ HALT ALL TRADING?\n\nThis will disable auto_trade immediately. Confirm?')) return;
    setHalting(true);
    try {
      await base44.functions.invoke('saveAllSettings', {
        auto_trade: false,
        friday_flush:            settings?.friday_flush ?? false,
        risk_pct:                settings?.risk_pct ?? 0.01,
        target_reward:           settings?.target_reward ?? 1.8,
        daily_drawdown_limit:    settings?.daily_drawdown_limit ?? 0.05,
        max_session_exposure_pct: settings?.max_session_exposure_pct ?? 4.0,
      });
      setSettings(prev => prev ? { ...prev, auto_trade: false } : prev);
      setHaltDone(true);
      setTimeout(() => setHaltDone(false), 5000);
    } catch (e) {
      alert('Halt failed: ' + e.message);
    } finally {
      setHalting(false);
    }
  };

  const drawdownPct   = status?.drawdown_pct ?? 0;
  const drawdownLimit = settings?.daily_drawdown_limit != null ? settings.daily_drawdown_limit * 100 : 5.0;
  const sessionExp    = openCount != null && settings?.risk_pct != null ? openCount * (settings.risk_pct * 100) : null;
  const sessionLimit  = settings?.max_session_exposure_pct ?? 4.0;
  const drawdownColor = drawdownPct >= drawdownLimit * 0.8 ? 'red' : drawdownPct >= drawdownLimit * 0.5 ? 'amber' : 'emerald';
  const sessionColor  = sessionExp != null && sessionExp >= sessionLimit * 0.8 ? 'red' : sessionExp != null && sessionExp >= sessionLimit * 0.5 ? 'amber' : 'blue';
  const bridgeOnline  = metrics != null && !metrics?.error;
  const autoTrade     = settings?.auto_trade ?? false;
  const dailyPnl      = metrics?.daily_pnl ?? null;

  // News window warning — any HIGH impact event on a traded currency within 30 min
  const imminentHighEvents = calendar.filter(e => e.impact_level === 'high' && e.minutes_until >= 0 && e.minutes_until <= 30);

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-7xl mx-auto">

      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Command Center</h1>
          <p className="text-xs text-slate-600 mt-1">
            {lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : 'Loading…'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge online={bridgeOnline} />
          <button onClick={fetchAll} className="p-2 rounded-lg border border-slate-800 text-slate-500 hover:text-slate-300 hover:border-slate-600 transition-all">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* ── Circuit Breaker Alert ── */}
      {autopsy && (
        <div className="mb-6 flex items-start gap-3 bg-red-500/10 border border-red-500/30 rounded-xl p-4">
          <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-bold text-red-400">⚡ Circuit Breaker Fired — Trading Frozen</p>
            <p className="text-xs text-red-300/70 mt-1">
              Drawdown autopsy is <strong>AWAITING REVIEW</strong>. Trading will remain halted until you approve resumption in the Execution Journal.
            </p>
            <p className="text-xs text-slate-500 mt-1">Triggered: {new Date(autopsy.triggered_at).toLocaleString()}</p>
          </div>
        </div>
      )}

      {/* ── News Window Warning Banner ── */}
      {imminentHighEvents.length > 0 && (
        <div className="mb-6 flex items-start gap-3 bg-amber-500/10 border border-amber-500/30 rounded-xl p-4">
          <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-bold text-amber-400">⚠️ High-Impact News Within 30 Minutes</p>
            <p className="text-xs text-amber-300/70 mt-1">
              {imminentHighEvents.map(e => `${e.currency} ${e.indicator_name} (${fmtCountdown(e.minutes_until)})`).join(' · ')}
            </p>
            <p className="text-xs text-slate-500 mt-1">Consider pausing new entries until the news window clears.</p>
          </div>
        </div>
      )}

      {/* ── Auto Trade Status Banner ── */}
      <div className={`mb-6 flex items-center justify-between gap-4 rounded-xl border px-5 py-3 ${autoTrade ? 'bg-emerald-500/10 border-emerald-500/20' : 'bg-slate-800/50 border-slate-700/50'}`}>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${autoTrade ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
          <span className={`text-sm font-semibold ${autoTrade ? 'text-emerald-400' : 'text-slate-500'}`}>
            Auto Trade {autoTrade ? 'ENABLED' : 'DISABLED'}
          </span>
          {autoTrade && <span className="text-xs text-slate-500">— system is executing signals autonomously</span>}
        </div>
        <button
          onClick={handleHalt}
          disabled={halting || !autoTrade}
          className={`flex items-center gap-2 px-4 py-1.5 rounded-lg text-xs font-bold border transition-all
            ${haltDone ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
              autoTrade ? 'bg-red-500/10 text-red-400 border-red-500/20 hover:bg-red-500/20' :
              'bg-slate-800 text-slate-600 border-slate-700 cursor-not-allowed'}`}
        >
          <PowerOff className="w-3.5 h-3.5" />
          {haltDone ? 'Trading Halted' : halting ? 'Halting…' : 'Halt Trading'}
        </button>
      </div>

      {/* ── Account Metrics ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <MetricCard label="Balance"       value={fmt(metrics?.balance)}     sub="Account balance"  icon={DollarSign} color="green" />
        <MetricCard label="Equity"        value={fmt(metrics?.equity)}      sub="Net asset value"  icon={Activity}   color="blue" />
        <MetricCard label="Free Margin"   value={fmt(metrics?.free_margin)} sub="Available capital" icon={Zap}       color="cyan" />
        <MetricCard
          label="Daily P&L"
          value={fmt(dailyPnl)}
          sub="Today's performance"
          icon={DollarSign}
          color={dailyPnl == null ? 'slate' : dailyPnl >= 0 ? 'green' : 'red'}
        />
      </div>

      {/* ── Risk Gauges + Open Positions ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">

        {/* Drawdown Gauge */}
        <div className="lg:col-span-1 rounded-xl border border-slate-800 bg-slate-900/50 p-5 flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <TrendingDown className="w-4 h-4 text-slate-500" />
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">Drawdown</p>
          </div>
          <GaugeBar
            label="Daily Drawdown"
            value={drawdownPct}
            max={drawdownLimit}
            color={drawdownColor}
          />
          <p className="text-xs text-slate-600">Circuit breaker fires at {drawdownLimit}%</p>
        </div>

        {/* Session Exposure Gauge */}
        <div className="lg:col-span-1 rounded-xl border border-slate-800 bg-slate-900/50 p-5 flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <Layers className="w-4 h-4 text-slate-500" />
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">Session Exposure</p>
          </div>
          <GaugeBar
            label="Open Risk"
            value={sessionExp ?? 0}
            max={sessionLimit}
            color={sessionColor}
          />
          <p className="text-xs text-slate-600">New trades blocked at {sessionLimit}% total exposure</p>
        </div>

        {/* Open Positions + Margin */}
        <div className="lg:col-span-1 rounded-xl border border-slate-800 bg-slate-900/50 p-5 flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-4 h-4 text-slate-500" />
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">Exposure</p>
          </div>
          <div className="flex flex-col gap-3">
            <div className="flex justify-between items-center">
              <span className="text-xs text-slate-500">Open Positions</span>
              <span className="text-lg font-bold text-slate-100">{openCount ?? '—'}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-slate-500">Margin Used</span>
              <span className="text-sm font-semibold text-amber-400">{fmt(metrics?.margin_used)}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-slate-500">Margin / Balance</span>
              <span className="text-sm font-semibold text-slate-300">
                {metrics?.margin_used != null && metrics?.balance != null
                  ? fmtPct((metrics.margin_used / metrics.balance) * 100)
                  : '—'}
              </span>
            </div>
          </div>
        </div>

      </div>

      {/* ── Economic Calendar Strip ── */}
      <CalendarStrip events={calendar} />

      {/* ── Footer note ── */}
      <p className="text-xs text-slate-700 text-center">Auto-refreshes every 30s · To change risk settings go to Trading Settings</p>

    </div>
  );
}
