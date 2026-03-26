import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { base44 } from '@/api/base44Client';
import { Shield, AlertTriangle, RefreshCw, Link2Off, Search, X } from 'lucide-react';

export default function Executions() {
  const [executions, setExecutions] = useState([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);

  // ── Filters ──────────────────────────────────────────────────────────────────
  const [filterSymbol,   setFilterSymbol]   = useState('');
  const [filterPosId,    setFilterPosId]    = useState('');
  const [filterStatus,   setFilterStatus]   = useState('all');   // all | open | closed | failed
  const [filterPnl,      setFilterPnl]      = useState('all');   // all | positive | negative

  const fetchExecutions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await base44.functions.invoke('getExecutions');
      const d = res.data;
      setExecutions(Array.isArray(d?.executions) ? d.executions : Array.isArray(d?.data) ? d.data : []);
    } catch (err) {
      setError(err?.response?.data?.error || err.message || 'Failed to load executions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchExecutions();
    const id = setInterval(fetchExecutions, 30000);
    return () => clearInterval(id);
  }, [fetchExecutions]);

  // ── Apply filters ─────────────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    return executions.filter(ex => {
      if (filterSymbol && !ex.symbol?.toLowerCase().includes(filterSymbol.toLowerCase())) return false;
      if (filterPosId  && !String(ex.id || '').includes(filterPosId)) return false;
      if (filterStatus !== 'all' && ex.status !== filterStatus) return false;
      if (filterPnl === 'positive' && (ex.pnl == null || parseFloat(ex.pnl) < 0))  return false;
      if (filterPnl === 'negative' && (ex.pnl == null || parseFloat(ex.pnl) >= 0)) return false;
      return true;
    });
  }, [executions, filterSymbol, filterPosId, filterStatus, filterPnl]);

  const clearFilters = () => {
    setFilterSymbol('');
    setFilterPosId('');
    setFilterStatus('all');
    setFilterPnl('all');
  };
  const hasActiveFilters = filterSymbol || filterPosId || filterStatus !== 'all' || filterPnl !== 'all';

  // ── Helpers ───────────────────────────────────────────────────────────────────
  const isUnlinked   = (row) => !row.signal_uuid;
  const pnlColor     = (val) => val == null ? 'text-slate-500' : parseFloat(val) >= 0 ? 'text-emerald-400' : 'text-red-400';
  const fmt          = (n)   => n != null ? `€${parseFloat(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';
  const fmtPrice     = (n, digits) => n != null && n !== 0 ? parseFloat(n).toFixed(digits || 5) : '—';

  const signalUuidCell = (ex) => {
    if (ex.signal_uuid) {
      return <span className="font-mono text-xs text-slate-500">{ex.signal_uuid.slice(0, 16)}…</span>;
    }
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-slate-600">
        <Link2Off className="w-3 h-3" />
        <span className="font-mono text-slate-500 italic">No UUID</span>
      </span>
    );
  };

  const statusPill = (status) => {
    const cls =
      status === 'open'   ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
      status === 'closed' ? 'bg-slate-700 text-slate-400 border-slate-600' :
      status === 'failed' ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                            'bg-slate-800 text-slate-500 border-slate-700';
    return <span className={`text-xs px-2 py-0.5 rounded-full border font-semibold ${cls}`}>{status || '—'}</span>;
  };

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-7xl mx-auto">

      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Shield className="w-6 h-6 text-cyan-400" />
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Execution Journal</h1>
          <span className="text-xs font-semibold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 px-2 py-0.5 rounded-full">
            {filtered.length}{filtered.length !== executions.length ? ` / ${executions.length}` : ''}
          </span>
        </div>
        <button onClick={fetchExecutions} className="p-2 rounded-lg border border-slate-800 text-slate-500 hover:text-slate-300 hover:border-slate-600 transition-all">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />{error}
        </div>
      )}

      {/* ── Filter bar ── */}
      <div className="flex flex-wrap items-center gap-3 mb-4">

        {/* Symbol search */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
          <input
            type="text"
            placeholder="Symbol…"
            value={filterSymbol}
            onChange={e => setFilterSymbol(e.target.value)}
            className="pl-7 pr-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-cyan-500 w-36"
          />
        </div>

        {/* Position ID search */}
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
          <input
            type="text"
            placeholder="Position ID…"
            value={filterPosId}
            onChange={e => setFilterPosId(e.target.value)}
            className="pl-7 pr-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-cyan-500 w-36"
          />
        </div>

        {/* Status */}
        <select
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 focus:outline-none focus:border-cyan-500"
        >
          <option value="all">All Statuses</option>
          <option value="open">Open</option>
          <option value="closed">Closed</option>
          <option value="failed">Failed</option>
        </select>

        {/* P&L filter */}
        <select
          value={filterPnl}
          onChange={e => setFilterPnl(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 focus:outline-none focus:border-cyan-500"
        >
          <option value="all">All P&amp;L</option>
          <option value="positive">P&amp;L +ve</option>
          <option value="negative">P&amp;L -ve</option>
        </select>

        {/* Clear filters */}
        {hasActiveFilters && (
          <button
            onClick={clearFilters}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-all"
          >
            <X className="w-3 h-3" /> Clear
          </button>
        )}
      </div>

      {/* ── Legend ── */}
      <div className="flex items-center gap-2 mb-4 text-xs text-slate-600">
        <Link2Off className="w-3 h-3" />
        <span>"No UUID" = position opened outside the Tekton system (e.g. direct cTrader order). Tekton-generated trades always have a signal UUID.</span>
      </div>

      {/* ── Table ── */}
      <div className="card-dark overflow-hidden">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800">
                {['POS ID', 'Signal UUID', 'Symbol', 'Side', 'Lots', 'Entry', 'Close', 'SL', 'TP', 'P&L', 'Status', 'Open Time', 'Close Time'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold tracking-widest uppercase text-slate-600">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && executions.length === 0 ? (
                Array(8).fill(0).map((_, i) => (
                  <tr key={i} className="border-b border-slate-800/50 shimmer">
                    {Array(13).fill(0).map((_, j) => (<td key={j} className="px-4 py-4"><div className="h-3 bg-slate-800 rounded w-full" /></td>))}
                  </tr>
                ))
              ) : filtered.length === 0 ? (
                <tr><td colSpan={13} className="px-4 py-12 text-center text-slate-600">
                  {hasActiveFilters ? 'No executions match the current filters' : 'No executions found'}
                </td></tr>
              ) : (
                filtered.map((ex) => {
                  const unlinked = isUnlinked(ex);
                  return (
                    <tr key={ex.id} className={`border-b transition-colors ${unlinked ? 'border-slate-800/30 bg-slate-900/30' : 'border-slate-800/50 hover:bg-slate-800/40'}`}>
                      {/* POS ID — bridge returns this as 'id' */}
                      <td className="px-4 py-3.5 font-mono text-xs text-slate-400">{ex.id || '—'}</td>
                      <td className="px-4 py-3.5">{signalUuidCell(ex)}</td>
                      <td className="px-4 py-3.5 font-semibold text-slate-200">{ex.symbol || '—'}</td>
                      <td className="px-4 py-3.5">
                        <span className={`text-xs font-bold ${ex.side === 'BUY' || ex.side === 'LONG' ? 'text-emerald-400' : 'text-red-400'}`}>{ex.side || '—'}</span>
                      </td>
                      <td className="px-4 py-3.5 text-slate-400 font-mono text-xs">{ex.volume ?? '—'}</td>
                      <td className="px-4 py-3.5 text-slate-400 font-mono text-xs">{fmtPrice(ex.entry_price, ex.digits)}</td>
                      <td className="px-4 py-3.5 text-slate-400 font-mono text-xs">{fmtPrice(ex.close_price, ex.digits)}</td>
                      <td className="px-4 py-3.5 text-red-400 font-mono text-xs">
                        {ex.stop_loss
                          ? Number(ex.stop_loss).toFixed(ex.digits || 5)
                          : ex.sl_pips
                            ? <span title="SL price unavailable — showing pips" className="text-slate-500">{ex.sl_pips}p</span>
                            : '—'}
                      </td>
                      <td className="px-4 py-3.5 text-emerald-400 font-mono text-xs">
                        {ex.take_profit
                          ? Number(ex.take_profit).toFixed(ex.digits || 5)
                          : ex.tp_pips
                            ? <span title="TP price unavailable — showing pips" className="text-slate-500">{ex.tp_pips}p</span>
                            : '—'}
                      </td>
                      <td className={`px-4 py-3.5 font-semibold font-mono text-xs ${pnlColor(ex.pnl)}`}>{fmt(ex.pnl)}</td>
                      <td className="px-4 py-3.5">{statusPill(ex.status)}</td>
                      <td className="px-4 py-3.5 text-slate-600 text-xs whitespace-nowrap">{ex.created_at ? new Date(ex.created_at).toLocaleString() : '—'}</td>
                      <td className="px-4 py-3.5 text-slate-600 text-xs whitespace-nowrap">{ex.closed_at  ? new Date(ex.closed_at).toLocaleString()  : '—'}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
