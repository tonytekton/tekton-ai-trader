import React, { useState, useEffect, useCallback } from 'react';
import { base44 } from '@/api/base44Client';
import { Brain, TrendingUp, TrendingDown, RefreshCw, ChevronRight, AlertCircle } from 'lucide-react';
import ConfidenceBar from '../components/signals/ConfidenceBar';
import SignalDetailModal from '../components/signals/SignalDetailModal';

const STATUS_STYLES = {
  PENDING:   'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  EXECUTED:  'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  COMPLETED: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  FAILED:    'bg-red-500/10 text-red-400 border-red-500/20',
  EXPIRED:   'bg-slate-700/30 text-slate-500 border-slate-700/50',
  CANCELLED: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  CANCELED:  'bg-orange-500/10 text-orange-400 border-orange-500/20',
  EXECUTING: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
};

const STAT_CARDS = [
  { key: 'TOTAL',     label: 'Total',     style: 'text-slate-100 border-slate-700/50 bg-slate-800/30' },
  { key: 'PENDING',   label: 'Pending',   style: 'text-yellow-400 border-yellow-500/20 bg-yellow-500/5' },
  { key: 'EXECUTED',  label: 'Executed',  style: 'text-emerald-400 border-emerald-500/20 bg-emerald-500/5' },
  { key: 'FAILED',    label: 'Failed',    style: 'text-red-400 border-red-500/20 bg-red-500/5' },
  { key: 'EXPIRED',   label: 'Expired',   style: 'text-slate-500 border-slate-700/50 bg-slate-800/20' },
  { key: 'CANCELLED', label: 'Cancelled', style: 'text-orange-400 border-orange-500/20 bg-orange-500/5' },
];

// Map DB statuses to friendly labels for the FAILED badge tooltip
const FAILURE_SHORT = {
  'SL below minimum': 'SL < min',
  'RR ratio below': 'RR < 1.5',
  'Invalid SL/TP': 'Bad SL/TP',
  'Bridge execution': 'Bridge err',
  'Execution error': 'Exec err',
};

function failureLabel(reason) {
  if (!reason) return null;
  for (const [key, label] of Object.entries(FAILURE_SHORT)) {
    if (reason.startsWith(key)) return label;
  }
  return reason.slice(0, 18);
}

export default function Signals() {
  const [signals, setSignals]     = useState([]);
  const [statsData, setStatsData] = useState(null);
  const [loading, setLoading]     = useState(true);
  const [selected, setSelected]   = useState(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [symbolFilter, setSymbolFilter] = useState('');

  useEffect(() => {
    base44.functions.invoke('getSignalStats')
      .then(res => setStatsData(res.data))
      .catch(() => setStatsData(null));
  }, []);

  const fetchSignals = useCallback(async (status = statusFilter, symbol = symbolFilter) => {
    setLoading(true);
    try {
      const res = await base44.functions.invoke('getSignals', { status, symbol });
      const payload = res.data;
      const arr = Array.isArray(payload) ? payload
        : Array.isArray(payload?.signals) ? payload.signals
        : Array.isArray(payload?.data) ? payload.data
        : [];
      setSignals(arr);
    } catch { setSignals([]); } finally { setLoading(false); }
  }, [statusFilter, symbolFilter]);

  useEffect(() => { fetchSignals('', ''); }, []);

  const handleStatusChange = (e) => { const val = e.target.value; setStatusFilter(val); fetchSignals(val, symbolFilter); };
  const handleSymbolChange = (e) => { const val = e.target.value; setSymbolFilter(val); fetchSignals(statusFilter, val); };
  const handleRefresh = () => {
    base44.functions.invoke('getSignalStats').then(res => setStatsData(res.data)).catch(() => setStatsData(null));
    fetchSignals(statusFilter, symbolFilter);
  };

  const directionBadge = (d) => {
    const isLong = d === 'BUY' || d === 'LONG';
    return (
      <span className={`inline-flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded-full ${isLong ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'}`}>
        {isLong ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
        {d || '—'}
      </span>
    );
  };

  const statusBadge = (sig) => {
    const s = sig.status || 'UNKNOWN';
    const style = STATUS_STYLES[s] || STATUS_STYLES.EXPIRED;

    if (s === 'FAILED' && sig.error_reason) {
      const short = failureLabel(sig.error_reason);
      return (
        <span className="relative group inline-flex items-center gap-1">
          <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border ${style}`}>
            <AlertCircle className="w-3 h-3 shrink-0" />
            {s}
          </span>
          {short && (
            <span className="ml-1 text-[10px] text-red-400/70 font-mono hidden sm:inline">
              · {short}
            </span>
          )}
          {/* Full reason tooltip */}
          <span className="absolute bottom-full left-0 mb-1.5 z-50 hidden group-hover:block w-64 bg-slate-900 border border-red-500/30 rounded-lg px-3 py-2 text-xs text-red-300 shadow-xl whitespace-normal pointer-events-none">
            {sig.error_reason}
          </span>
        </span>
      );
    }

    return <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${style}`}>{s}</span>;
  };

  const selectClass = "bg-slate-900 border border-slate-700 text-slate-300 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-slate-500 cursor-pointer";

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Brain className="w-6 h-6 text-purple-400" />
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Signals Log</h1>
          <span className="text-xs font-semibold bg-purple-500/10 text-purple-400 border border-purple-500/20 px-2 py-0.5 rounded-full">{signals.length}</span>
        </div>
        <button onClick={handleRefresh} className="p-2 rounded-lg border border-slate-800 text-slate-500 hover:text-slate-300 hover:border-slate-600 transition-all">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-3 mb-6">
        {STAT_CARDS.map(({ key, label, style }) => (
          <div key={key} className={`rounded-xl border px-4 py-3 ${style}`}>
            <div className="text-[10px] font-semibold tracking-widest uppercase opacity-70 mb-1">{label}</div>
            <div className="text-2xl font-bold font-mono">{statsData ? (statsData.counts?.[key] ?? 0) : <span className="text-sm opacity-40">—</span>}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-5">
        <select value={statusFilter} onChange={handleStatusChange} className={selectClass}>
          <option value="">All Statuses</option>
          <option value="PENDING">Pending</option>
          <option value="EXECUTING">Executing</option>
          <option value="COMPLETED">Completed</option>
          <option value="EXECUTED">Executed</option>
          <option value="FAILED">Failed</option>
          <option value="EXPIRED">Expired</option>
          <option value="CANCELLED">Cancelled</option>
          <option value="CANCELED">Canceled</option>
        </select>
        <select value={symbolFilter} onChange={handleSymbolChange} className={selectClass}>
          <option value="">All Symbols</option>
          {(statsData?.symbols || []).map(sym => (<option key={sym} value={sym}>{sym}</option>))}
        </select>
      </div>

      {/* Table */}
      <div className="card-dark overflow-hidden">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800">
                {['Created At', 'Symbol', 'Direction', 'Timeframe', 'Confidence', 'SL Pips', 'TP Pips', 'Status', ''].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold tracking-widest uppercase text-slate-600">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && signals.length === 0 ? (
                Array(6).fill(0).map((_, i) => (
                  <tr key={i} className="border-b border-slate-800/50 shimmer">
                    {Array(8).fill(0).map((_, j) => (<td key={j} className="px-4 py-4"><div className="h-3 bg-slate-800 rounded w-full" /></td>))}
                  </tr>
                ))
              ) : signals.length === 0 ? (
                <tr><td colSpan={9} className="px-4 py-12 text-center text-slate-600">No signals found</td></tr>
              ) : (
                signals.map((sig) => (
                  <tr key={sig.signal_uuid || sig.uuid || sig.id} onClick={() => setSelected(sig)} className="border-b border-slate-800/50 hover:bg-slate-800/40 cursor-pointer transition-colors group">
                    <td className="px-4 py-3.5 text-slate-500 text-xs whitespace-nowrap">{sig.created_at ? new Date(sig.created_at).toLocaleString() : '—'}</td>
                    <td className="px-4 py-3.5 font-semibold text-slate-200">{sig.symbol || '—'}</td>
                    <td className="px-4 py-3.5">{directionBadge(sig.direction || sig.signal_type)}</td>
                    <td className="px-4 py-3.5 text-slate-500 font-mono text-xs">{sig.timeframe || '—'}</td>
                    <td className="px-4 py-3.5 min-w-[160px]"><ConfidenceBar score={sig.confidence ?? sig.confidence_score ?? 0} /></td>
                    <td className="px-4 py-3.5 font-mono text-xs text-slate-400">{sig.sl_pips != null ? sig.sl_pips : '—'}</td>
                    <td className="px-4 py-3.5 font-mono text-xs text-slate-400">{sig.tp_pips != null ? sig.tp_pips : '—'}</td>
                    <td className="px-4 py-3.5">{statusBadge(sig)}</td>
                    <td className="px-4 py-3.5"><ChevronRight className="w-4 h-4 text-slate-700 group-hover:text-slate-400 transition-colors" /></td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
      {selected && <SignalDetailModal signal={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
