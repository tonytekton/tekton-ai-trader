import React, { useState, useEffect, useCallback } from 'react';
import { base44 } from '@/api/base44Client';
import { Shield, AlertTriangle, RefreshCw, Link2Off } from 'lucide-react';

export default function Executions() {
  const [executions, setExecutions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

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

  // A trade has no signal UUID when it was opened outside the system (e.g. manual cTrader order)
  // Closed trades by SL/TP/AI will have their UUID resolved from the signals table via position_id
  const isUnlinked = (row) => !row.signal_uuid;

  const pnlColor = (val) => { if (val == null) return 'text-slate-500'; return parseFloat(val) >= 0 ? 'text-emerald-400' : 'text-red-400'; };
  const fmt = (n) => n != null ? `€${parseFloat(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';
  const fmtPrice = (n, digits) => n != null && n !== 0 ? parseFloat(n).toFixed(digits || 5) : '—';

  const signalUuidCell = (ex) => {
    if (ex.signal_uuid) {
      return <span className="font-mono text-xs text-slate-500">{ex.signal_uuid.slice(0, 16)}…</span>;
    }
    // No signal UUID — trade was opened outside the Tekton system (e.g. direct cTrader order)
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-slate-600">
        <Link2Off className="w-3 h-3" />
        <span className="font-mono text-slate-500 italic">Not a Tekton trade</span>
      </span>
    );
  };

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <Shield className="w-6 h-6 text-cyan-400" />
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Execution Journal</h1>
          <span className="text-xs font-semibold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 px-2 py-0.5 rounded-full">{executions.length}</span>
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

      <div className="flex items-center gap-2 mb-4 text-xs text-slate-600">
        <Link2Off className="w-3 h-3" />
        <span>
          "Not a Tekton trade" = position opened outside the system (e.g. direct cTrader order).
          Tekton-generated trades always have a signal UUID.
        </span>
      </div>

      <div className="card-dark overflow-hidden">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800">
                {['Pos ID', 'Signal UUID', 'Symbol', 'Side', 'Lots', 'Entry', 'Close', 'SL', 'TP', 'P&L', 'Status', 'Open Time', 'Close Time'].map(h => (
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
              ) : executions.length === 0 ? (
                <tr><td colSpan={13} className="px-4 py-12 text-center text-slate-600">No executions found</td></tr>
              ) : (
                executions.map((ex) => {
                  const unlinked = isUnlinked(ex);
                  return (
                    <tr key={ex.id || ex.position_id} className={`border-b transition-colors ${unlinked ? 'border-slate-800/30 bg-slate-900/30' : 'border-slate-800/50 hover:bg-slate-800/40'}`}>
                      <td className="px-4 py-3.5 font-mono text-xs text-slate-600">{ex.position_id || '—'}</td>
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
                      <td className="px-4 py-3.5">
                        <span className={`text-xs px-2 py-0.5 rounded-full border font-semibold ${
                          ex.status === 'open'   ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                          ex.status === 'closed' ? 'bg-slate-700 text-slate-400 border-slate-600' :
                                                   'bg-slate-800 text-slate-500 border-slate-700'
                        }`}>{ex.status || '—'}</span>
                      </td>
                      <td className="px-4 py-3.5 text-slate-600 text-xs whitespace-nowrap">{ex.created_at ? new Date(ex.created_at).toLocaleString() : '—'}</td>
                      <td className="px-4 py-3.5 text-slate-600 text-xs whitespace-nowrap">{ex.closed_at ? new Date(ex.closed_at).toLocaleString() : '—'}</td>
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

