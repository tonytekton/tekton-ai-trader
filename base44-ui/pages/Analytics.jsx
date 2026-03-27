import { useState, useEffect } from "react";
import { base44 } from '@/api/base44Client';

// ── Colour palette per strategy ──────────────────────────────────────────────
const STRAT_COLORS = [
  "#6366f1","#10b981","#f59e0b","#ef4444","#3b82f6","#8b5cf6","#ec4899","#14b8a6",
];

function StatCard({ label, value, sub, color = "indigo" }) {
  const colors = {
    indigo: "bg-indigo-50 border-indigo-200 text-indigo-700",
    green:  "bg-green-50  border-green-200  text-green-700",
    red:    "bg-red-50    border-red-200    text-red-700",
    amber:  "bg-amber-50  border-amber-200  text-amber-700",
    slate:  "bg-slate-50  border-slate-200  text-slate-700",
  };
  return (
    <div className={`rounded-xl border p-4 ${colors[color]}`}>
      <div className="text-xs font-medium uppercase tracking-wide opacity-70">{label}</div>
      <div className="text-3xl font-bold mt-1">{value ?? "—"}</div>
      {sub && <div className="text-xs mt-1 opacity-60">{sub}</div>}
    </div>
  );
}

// Simple bar chart using div widths
function BarChart({ data, labelKey, valueKey, colorFn, maxValue }) {
  const max = maxValue || Math.max(...data.map(d => d[valueKey] || 0), 1);
  return (
    <div className="space-y-2">
      {data.map((d, i) => (
        <div key={i} className="flex items-center gap-2 text-sm">
          <div className="w-28 truncate text-slate-600 text-xs">{d[labelKey]}</div>
          <div className="flex-1 bg-slate-100 rounded-full h-5 relative">
            <div
              className="h-5 rounded-full flex items-center pl-2 text-xs text-white font-medium"
              style={{
                width: `${Math.max(4, (d[valueKey] / max) * 100)}%`,
                backgroundColor: colorFn ? colorFn(d, i) : "#6366f1",
              }}
            >
              {d[valueKey]}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// Win rate badge
function WrBadge({ wr }) {
  if (wr === null || wr === undefined) return <span className="text-slate-400">—</span>;
  const color = wr >= 60 ? "text-green-600 bg-green-50" : wr >= 40 ? "text-amber-600 bg-amber-50" : "text-red-600 bg-red-50";
  return <span className={`px-2 py-0.5 rounded text-xs font-bold ${color}`}>{wr}%</span>;
}

export default function Analytics() {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [tab, setTab]         = useState("overview"); // overview | strategies | symbols | confidence

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await base44.functions.invoke('getAnalytics');
      if (res?.ok) setData(res);
      else setError(res?.error || "Unknown error");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-slate-500">
      <div className="text-center">
        <div className="text-4xl mb-3">📊</div>
        <div>Loading analytics...</div>
      </div>
    </div>
  );

  if (error) return (
    <div className="p-6 text-center">
      <div className="text-4xl mb-3">⚠️</div>
      <div className="text-red-600 font-medium mb-2">Failed to load analytics</div>
      <div className="text-slate-500 text-sm mb-4">{error}</div>
      <button onClick={load} className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm">Retry</button>
    </div>
  );

  const { summary, by_strategy, by_symbol, by_timeframe, confidence_buckets, daily_volume } = data;

  const tabs = [
    { id: "overview",    label: "Overview" },
    { id: "strategies",  label: "Strategies" },
    { id: "symbols",     label: "Symbols" },
    { id: "confidence",  label: "Confidence" },
  ];

  return (
    <div className="p-4 max-w-6xl mx-auto space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">📊 Analytics</h1>
          <p className="text-slate-500 text-sm mt-0.5">Performance attribution across all strategies</p>
        </div>
        <button
          onClick={load}
          className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm font-medium"
        >
          🔄 Refresh
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total Signals"    value={summary.total}           color="slate" />
        <StatCard label="Completed"        value={summary.completed}        color="green" sub={`${summary.win_rate}% of total`} />
        <StatCard label="Failed / Rejected" value={summary.failed}          color="red"   />
        <StatCard label="Avg Confidence"   value={summary.avg_confidence ? `${summary.avg_confidence}%` : "—"} color="indigo" sub={`${summary.strategies} strategies · ${summary.symbols} symbols`} />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-100 rounded-xl p-1 w-fit">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-all ${
              tab === t.id ? "bg-white shadow text-indigo-700" : "text-slate-600 hover:text-slate-800"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* OVERVIEW TAB */}
      {tab === "overview" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

          {/* Daily volume */}
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <h2 className="font-semibold text-slate-700 mb-4">Daily Signal Volume (last 30 days)</h2>
            {daily_volume.length === 0 ? (
              <div className="text-slate-400 text-sm">No data</div>
            ) : (
              <div className="flex items-end gap-1 h-32">
                {daily_volume.map((d, i) => {
                  const max = Math.max(...daily_volume.map(x => x.count), 1);
                  const pct = (d.count / max) * 100;
                  return (
                    <div key={i} className="flex-1 flex flex-col items-center gap-1 group relative">
                      <div
                        className="w-full bg-indigo-400 rounded-t hover:bg-indigo-600 transition-colors cursor-pointer"
                        style={{ height: `${Math.max(4, pct)}%` }}
                        title={`${d.date}: ${d.count} signals`}
                      />
                      {i % 5 === 0 && (
                        <div className="text-xs text-slate-400 rotate-45 origin-left">{d.date.slice(5)}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Timeframe breakdown */}
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <h2 className="font-semibold text-slate-700 mb-4">Signals by Timeframe</h2>
            <BarChart
              data={by_timeframe}
              labelKey="timeframe"
              valueKey="count"
              colorFn={(d, i) => STRAT_COLORS[i % STRAT_COLORS.length]}
            />
          </div>

          {/* Strategy quick summary */}
          <div className="bg-white rounded-xl border border-slate-200 p-5 md:col-span-2">
            <h2 className="font-semibold text-slate-700 mb-4">Strategy Summary</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 uppercase border-b border-slate-100">
                    <th className="text-left py-2 pr-4">Strategy</th>
                    <th className="text-right py-2 px-3">Total</th>
                    <th className="text-right py-2 px-3">Done</th>
                    <th className="text-right py-2 px-3">Failed</th>
                    <th className="text-right py-2 px-3">Win Rate</th>
                    <th className="text-right py-2 px-3">Avg Conf</th>
                    <th className="text-right py-2 px-3">Avg RR</th>
                  </tr>
                </thead>
                <tbody>
                  {by_strategy.map((s, i) => (
                    <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                      <td className="py-2 pr-4">
                        <div className="flex items-center gap-2">
                          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: STRAT_COLORS[i % STRAT_COLORS.length] }} />
                          <span className="font-medium text-slate-700">{s.strategy}</span>
                        </div>
                      </td>
                      <td className="text-right px-3 text-slate-600">{s.total}</td>
                      <td className="text-right px-3 text-green-600">{s.completed}</td>
                      <td className="text-right px-3 text-red-500">{s.failed}</td>
                      <td className="text-right px-3"><WrBadge wr={s.win_rate} /></td>
                      <td className="text-right px-3 text-slate-600">{s.avg_confidence ? `${s.avg_confidence}%` : "—"}</td>
                      <td className="text-right px-3 text-slate-600">{s.avg_rr ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* STRATEGIES TAB */}
      {tab === "strategies" && (
        <div className="space-y-4">
          {by_strategy.map((s, i) => (
            <div key={i} className="bg-white rounded-xl border border-slate-200 p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-3 h-3 rounded-full" style={{ backgroundColor: STRAT_COLORS[i % STRAT_COLORS.length] }} />
                  <h3 className="font-semibold text-slate-800">{s.strategy}</h3>
                </div>
                <WrBadge wr={s.win_rate} />
              </div>
              <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
                <div className="text-center">
                  <div className="text-2xl font-bold text-slate-700">{s.total}</div>
                  <div className="text-xs text-slate-400">Total</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-green-600">{s.completed}</div>
                  <div className="text-xs text-slate-400">Completed</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-red-500">{s.failed}</div>
                  <div className="text-xs text-slate-400">Failed</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-indigo-600">{s.avg_confidence ? `${s.avg_confidence}%` : "—"}</div>
                  <div className="text-xs text-slate-400">Avg Conf</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-slate-600">{s.avg_sl ? `${s.avg_sl}p` : "—"}</div>
                  <div className="text-xs text-slate-400">Avg SL</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-slate-600">{s.avg_rr ?? "—"}</div>
                  <div className="text-xs text-slate-400">Avg RR</div>
                </div>
              </div>
              {/* Mini execution rate bar */}
              <div className="mt-4">
                <div className="flex justify-between text-xs text-slate-400 mb-1">
                  <span>Execution rate</span>
                  <span>{s.total > 0 ? ((s.completed / s.total) * 100).toFixed(0) : 0}%</span>
                </div>
                <div className="w-full bg-slate-100 rounded-full h-2">
                  <div
                    className="h-2 rounded-full"
                    style={{
                      width: `${s.total > 0 ? (s.completed / s.total) * 100 : 0}%`,
                      backgroundColor: STRAT_COLORS[i % STRAT_COLORS.length],
                    }}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* SYMBOLS TAB */}
      {tab === "symbols" && (
        <div className="bg-white rounded-xl border border-slate-200 p-5">
          <h2 className="font-semibold text-slate-700 mb-4">Top 15 Symbols by Signal Count</h2>
          <BarChart
            data={by_symbol}
            labelKey="symbol"
            valueKey="count"
            colorFn={(d, i) => STRAT_COLORS[i % STRAT_COLORS.length]}
          />
        </div>
      )}

      {/* CONFIDENCE TAB */}
      {tab === "confidence" && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <h2 className="font-semibold text-slate-700 mb-2">Execution Rate by Confidence Band</h2>
            <p className="text-xs text-slate-400 mb-4">
              How often signals in each confidence range are executed (COMPLETED / total in band).
              Note: execution is gated by RR ≥1.5 and SL ≥ min_sl_pips — lower confidence signals may be more likely to fail these gates.
            </p>
            <div className="space-y-4">
              {confidence_buckets.map((b, i) => (
                <div key={i}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="font-medium text-slate-700">Confidence {b.band}%</span>
                    <div className="flex items-center gap-3">
                      <span className="text-slate-500 text-xs">{b.completed}/{b.total} signals</span>
                      <WrBadge wr={b.win_rate} />
                    </div>
                  </div>
                  <div className="w-full bg-slate-100 rounded-full h-4">
                    <div
                      className="h-4 rounded-full transition-all"
                      style={{
                        width: `${Math.max(2, b.win_rate)}%`,
                        backgroundColor: b.win_rate >= 60 ? "#10b981" : b.win_rate >= 40 ? "#f59e0b" : "#ef4444",
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Confidence vs RR table (from recent completed) */}
          {data.recent_signals?.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 p-5">
              <h2 className="font-semibold text-slate-700 mb-4">Recent Completed Signals — Confidence vs RR</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-slate-400 uppercase border-b border-slate-100">
                      <th className="text-left py-2 pr-3">Symbol</th>
                      <th className="text-left py-2 pr-3">Strategy</th>
                      <th className="text-right py-2 px-2">Conf</th>
                      <th className="text-right py-2 px-2">SL</th>
                      <th className="text-right py-2 px-2">TP</th>
                      <th className="text-right py-2 px-2">RR</th>
                      <th className="text-right py-2">Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_signals.slice(0, 50).map((s, i) => (
                      <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                        <td className="py-1.5 pr-3 font-medium text-slate-700">{s.symbol}</td>
                        <td className="py-1.5 pr-3 text-slate-500 truncate max-w-28">{s.strategy}</td>
                        <td className="text-right px-2">
                          {s.confidence !== null ? (
                            <span className={`font-medium ${s.confidence >= 70 ? "text-green-600" : s.confidence >= 50 ? "text-amber-600" : "text-red-500"}`}>
                              {s.confidence}%
                            </span>
                          ) : "—"}
                        </td>
                        <td className="text-right px-2 text-slate-500">{s.sl_pips?.toFixed(1)}</td>
                        <td className="text-right px-2 text-slate-500">{s.tp_pips?.toFixed(1)}</td>
                        <td className="text-right px-2 font-medium text-indigo-600">{s.rr ?? "—"}</td>
                        <td className="text-right text-slate-400">{s.created_at?.slice(0, 10)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
