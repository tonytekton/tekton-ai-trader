import { useState, useEffect } from "react";
import { base44 } from '@/api/base44Client';
import { AnalyticsRecommendation } from '@/api/entities';

const STRAT_COLORS = ["#6366f1","#10b981","#f59e0b","#ef4444","#3b82f6","#8b5cf6","#ec4899","#14b8a6","#f97316","#06b6d4","#84cc16","#a855f7"];

function StatCard({ label, value, sub, color = "indigo" }) {
  const colors = {
    indigo: "bg-indigo-50 border-indigo-200 text-indigo-700",
    green:  "bg-green-50  border-green-200  text-green-700",
    red:    "bg-red-50    border-red-200    text-red-700",
    amber:  "bg-amber-50  border-amber-200  text-amber-700",
    slate:  "bg-slate-50  border-slate-200  text-slate-700",
    purple: "bg-purple-50 border-purple-200 text-purple-700",
  };
  return (
    <div className={`rounded-xl border p-4 ${colors[color]}`}>
      <div className="text-xs font-medium uppercase tracking-wide opacity-70">{label}</div>
      <div className="text-3xl font-bold mt-1">{value ?? "—"}</div>
      {sub && <div className="text-xs mt-1 opacity-60">{sub}</div>}
    </div>
  );
}

function WrBadge({ wr, suffix="%" }) {
  if (wr === null || wr === undefined) return <span className="text-slate-400">—</span>;
  const color = wr >= 50 ? "text-green-600 bg-green-50 border-green-200" : wr >= 30 ? "text-amber-600 bg-amber-50 border-amber-200" : "text-red-600 bg-red-50 border-red-200";
  return <span className={`px-2 py-0.5 rounded border text-xs font-bold ${color}`}>{wr}{suffix}</span>;
}

function RankBadge({ rank }) {
  const medals = { 1: "🥇", 2: "🥈", 3: "🥉" };
  if (medals[rank]) return <span className="text-lg">{medals[rank]}</span>;
  return <span className="text-sm font-bold text-slate-500">#{rank}</span>;
}

function HBar({ value, max, color = "#6366f1", label }) {
  const pct = max > 0 ? Math.max(3, (value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2 text-sm">
      <div className="w-32 truncate text-slate-600 text-xs shrink-0">{label}</div>
      <div className="flex-1 bg-slate-100 rounded-full h-5 relative">
        <div className="h-5 rounded-full flex items-center pl-2 text-xs text-white font-medium transition-all"
          style={{ width: `${pct}%`, backgroundColor: color }}>
          {value}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <h3 className="font-semibold text-slate-700 mb-4">{title}</h3>
      {children}
    </div>
  );
}

// ── TABS ─────────────────────────────────────────────────────────────────────
const TABS = [
  { id: "overview",    label: "📊 Overview" },
  { id: "league",      label: "🏆 League Table" },
  { id: "bestof",      label: "⭐ Best Of" },
  { id: "confidence",  label: "🎯 Confidence" },
  { id: "insights",    label: "🤖 AI Insights" },
];

export default function Analytics() {
  const [data, setData]           = useState(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [tab, setTab]             = useState("overview");
  const [recs, setRecs]           = useState([]);
  const [recsLoading, setRecsLoading] = useState(false);
  const [generating, setGenerating]   = useState(false);
  const [genMsg, setGenMsg]           = useState(null);

  const loadAnalytics = async () => {
    setLoading(true); setError(null);
    try {
      const res = await base44.functions.invoke('getAnalytics');
      if (res?.ok) setData(res);
      else setError(res?.error || "Unknown error");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const loadRecs = async () => {
    setRecsLoading(true);
    try {
      const r = await AnalyticsRecommendation.list({ sort: "-created_date", limit: 20 });
      setRecs(r || []);
    } catch (e) { console.error(e); }
    finally { setRecsLoading(false); }
  };

  const generateInsights = async () => {
    setGenerating(true); setGenMsg(null);
    try {
      const res = await base44.functions.invoke('generateAnalyticsInsights', { trigger: 'on_demand' });
      if (res?.ok) {
        setGenMsg("✅ Insights generated and saved to audit log.");
        await loadRecs();
      } else {
        setGenMsg(`❌ ${res?.error || 'Generation failed'}`);
      }
    } catch (e) { setGenMsg(`❌ ${e.message}`); }
    finally { setGenerating(false); }
  };

  const markRecStatus = async (id, status) => {
    await AnalyticsRecommendation.update(id, { status, reviewed_at: new Date().toISOString() });
    await loadRecs();
  };

  useEffect(() => { loadAnalytics(); loadRecs(); }, []);

  if (loading) return (
    <div className="flex items-center justify-center h-64 text-slate-500">
      <div className="text-center"><div className="text-4xl mb-3">📊</div><div>Loading analytics...</div></div>
    </div>
  );
  if (error) return (
    <div className="p-6 text-center">
      <div className="text-4xl mb-3">⚠️</div>
      <div className="text-red-600 font-medium mb-2">Failed to load analytics</div>
      <div className="text-slate-500 text-sm mb-4">{error}</div>
      <button onClick={loadAnalytics} className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm">Retry</button>
    </div>
  );

  const { summary, by_strategy, strategy_league, by_symbol, by_timeframe, by_day_of_week, by_session, confidence_buckets, daily_volume } = data;

  return (
    <div className="p-4 max-w-7xl mx-auto space-y-5">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">📊 Analytics</h1>
          <p className="text-slate-500 text-sm mt-0.5">Strategy performance — all time · {summary.total.toLocaleString()} signals</p>
        </div>
        <button onClick={loadAnalytics} className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm font-medium">🔄 Refresh</button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="Total Signals"   value={summary.total.toLocaleString()} color="slate" />
        <StatCard label="Completed"       value={summary.completed.toLocaleString()} color="green" sub="Trade was placed" />
        <StatCard label="Failed/Rejected" value={summary.failed.toLocaleString()} color="red" sub="Filtered out" />
        <StatCard label="Completion Rate" value={`${summary.win_rate}%`} color="indigo" sub={`${summary.strategies} strategies`} />
        <StatCard label="Avg Confidence"  value={summary.avg_confidence ? `${summary.avg_confidence}%` : "—"} color="purple" sub={`${summary.symbols} symbols`} />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-100 rounded-xl p-1 flex-wrap">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${tab === t.id ? "bg-white shadow text-indigo-700" : "text-slate-600 hover:text-slate-800"}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* ── OVERVIEW TAB ── */}
      {tab === "overview" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {/* Daily volume */}
          <Section title="Daily Signal Volume (last 30 days)">
            {daily_volume.length === 0 ? <div className="text-slate-400 text-sm">No data</div> : (
              <div className="flex items-end gap-0.5 h-28">
                {daily_volume.map((d, i) => {
                  const max = Math.max(...daily_volume.map(x => x.count), 1);
                  const pct = (d.count / max) * 100;
                  return (
                    <div key={i} className="flex-1 flex flex-col items-center gap-1 group">
                      <div className="w-full bg-indigo-400 hover:bg-indigo-600 rounded-t transition-colors cursor-pointer"
                        style={{ height: `${Math.max(4, pct)}%` }} title={`${d.date}: ${d.count}`} />
                      {i % 5 === 0 && <div className="text-xs text-slate-400">{d.date.slice(5)}</div>}
                    </div>
                  );
                })}
              </div>
            )}
          </Section>

          {/* Timeframe */}
          <Section title="Signals by Timeframe">
            <div className="space-y-2">
              {by_timeframe.map((d, i) => (
                <div key={i} className="flex items-center gap-3 text-sm">
                  <div className="w-16 text-slate-600 text-xs shrink-0">{d.timeframe}</div>
                  <div className="flex-1 bg-slate-100 rounded-full h-5">
                    <div className="h-5 rounded-full flex items-center pl-2 text-xs text-white font-medium"
                      style={{ width: `${Math.max(4,(d.total/by_timeframe[0]?.total||1)*100)}%`, backgroundColor: STRAT_COLORS[i] }}>
                      {d.total}
                    </div>
                  </div>
                  <WrBadge wr={d.completion_rate} />
                </div>
              ))}
            </div>
          </Section>

          {/* Strategy summary table */}
          <div className="md:col-span-2">
            <Section title="Strategy Summary">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-slate-500 uppercase border-b border-slate-100">
                      <th className="text-left py-2 pr-3">Strategy</th>
                      <th className="text-right px-2">Total</th>
                      <th className="text-right px-2">Done</th>
                      <th className="text-right px-2">Failed</th>
                      <th className="text-right px-2">Completion</th>
                      <th className="text-right px-2">Avg Conf</th>
                      <th className="text-right px-2">Avg RR</th>
                      <th className="text-right px-2">Quality</th>
                    </tr>
                  </thead>
                  <tbody>
                    {by_strategy.map((s, i) => (
                      <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                        <td className="py-2 pr-3">
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: STRAT_COLORS[i % STRAT_COLORS.length] }} />
                            <span className="font-medium text-slate-700 text-xs">{s.strategy}</span>
                          </div>
                        </td>
                        <td className="text-right px-2 text-slate-600">{s.total.toLocaleString()}</td>
                        <td className="text-right px-2 text-green-600">{s.completed.toLocaleString()}</td>
                        <td className="text-right px-2 text-red-500">{s.failed.toLocaleString()}</td>
                        <td className="text-right px-2"><WrBadge wr={s.completion_rate} /></td>
                        <td className="text-right px-2 text-slate-600">{s.avg_confidence ? `${s.avg_confidence}%` : "—"}</td>
                        <td className="text-right px-2 text-slate-600">{s.avg_rr ?? "—"}</td>
                        <td className="text-right px-2 font-bold text-indigo-600">{s.quality_score}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-slate-400 mt-2">*Completion = trade was placed. Quality = completion_rate × avg_rr. True P&L win rate coming when execution outcome data available.</p>
            </Section>
          </div>
        </div>
      )}

      {/* ── LEAGUE TABLE TAB ── */}
      {tab === "league" && (
        <div className="space-y-4">
          <Section title="🏆 Strategy League Table — Ranked by Quality Score (completion rate × avg RR)">
            <div className="space-y-3">
              {strategy_league.map((s) => (
                <div key={s.strategy} className={`rounded-xl border p-4 ${s.rank <= 3 ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-white'}`}>
                  <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="flex items-center gap-3">
                      <RankBadge rank={s.rank} />
                      <div>
                        <div className="font-bold text-slate-800">{s.strategy}</div>
                        <div className="text-xs text-slate-500">{s.total.toLocaleString()} signals · {s.completed} completed · {s.failed} failed</div>
                      </div>
                    </div>
                    <div className="flex gap-4 flex-wrap">
                      <div className="text-center">
                        <div className="text-xs text-slate-500 uppercase">Completion</div>
                        <WrBadge wr={s.completion_rate} />
                      </div>
                      <div className="text-center">
                        <div className="text-xs text-slate-500 uppercase">Avg RR</div>
                        <div className="font-bold text-slate-700">{s.avg_rr ?? "—"}</div>
                      </div>
                      <div className="text-center">
                        <div className="text-xs text-slate-500 uppercase">Avg Conf</div>
                        <div className="font-bold text-slate-700">{s.avg_confidence ? `${s.avg_confidence}%` : "—"}</div>
                      </div>
                      <div className="text-center">
                        <div className="text-xs text-slate-500 uppercase">Quality</div>
                        <div className={`font-bold text-lg ${s.quality_score >= 1 ? 'text-green-600' : s.quality_score >= 0.3 ? 'text-amber-600' : 'text-red-500'}`}>
                          {s.quality_score}
                        </div>
                      </div>
                    </div>
                  </div>
                  {/* Quality bar */}
                  <div className="mt-3 bg-slate-200 rounded-full h-2">
                    <div className="h-2 rounded-full transition-all"
                      style={{ width: `${Math.min(100, (s.quality_score / (strategy_league[0]?.quality_score || 1)) * 100)}%`, backgroundColor: s.quality_score >= 1 ? '#10b981' : s.quality_score >= 0.3 ? '#f59e0b' : '#ef4444' }} />
                  </div>
                </div>
              ))}
            </div>
          </Section>
        </div>
      )}

      {/* ── BEST OF TAB ── */}
      {tab === "bestof" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">

          {/* Best day */}
          <Section title="📅 Best Day to Trade">
            <div className="space-y-2">
              {by_day_of_week.map((d, i) => (
                <div key={i} className="flex items-center gap-3">
                  <div className="w-24 text-sm font-medium text-slate-600 shrink-0">{d.day}</div>
                  <div className="flex-1 bg-slate-100 rounded-full h-6">
                    <div className="h-6 rounded-full flex items-center pl-2 text-xs text-white font-medium"
                      style={{ width: `${Math.max(4,(d.completion_rate/100)*100)}%`, backgroundColor: d.completion_rate >= 60 ? '#10b981' : d.completion_rate >= 40 ? '#f59e0b' : '#6366f1' }}>
                      {d.completion_rate}%
                    </div>
                  </div>
                  <div className="text-xs text-slate-400 w-16 text-right shrink-0">{d.total} sigs</div>
                </div>
              ))}
            </div>
          </Section>

          {/* Best session */}
          <Section title="🕐 Best Session to Trade">
            <div className="space-y-2">
              {by_session.map((s, i) => (
                <div key={i} className="rounded-lg border border-slate-200 p-3 flex items-center justify-between">
                  <div>
                    <div className="font-medium text-slate-700">{s.session}</div>
                    <div className="text-xs text-slate-400">{s.total} signals</div>
                  </div>
                  <div className="text-right">
                    <WrBadge wr={s.completion_rate} />
                    <div className="text-xs text-slate-400 mt-1">avg RR {s.avg_rr ?? "—"}</div>
                  </div>
                </div>
              ))}
            </div>
          </Section>

          {/* Best symbols */}
          <Section title="💱 Best Symbols (≥5 signals, by completion rate)">
            <div className="space-y-2">
              {by_symbol.slice(0,15).map((s, i) => (
                <div key={i} className="flex items-center gap-3">
                  <div className="w-20 text-xs font-mono font-bold text-slate-700 shrink-0">{s.symbol}</div>
                  <div className="flex-1 bg-slate-100 rounded-full h-5">
                    <div className="h-5 rounded-full flex items-center pl-2 text-xs text-white font-medium"
                      style={{ width: `${Math.max(4,s.completion_rate)}%`, backgroundColor: STRAT_COLORS[i % STRAT_COLORS.length] }}>
                      {s.completion_rate}%
                    </div>
                  </div>
                  <div className="text-xs text-slate-400 shrink-0">RR {s.avg_rr ?? "—"}</div>
                </div>
              ))}
            </div>
          </Section>

          {/* Best R:R by strategy */}
          <Section title="📐 Best R:R by Strategy">
            <div className="space-y-2">
              {[...by_strategy].filter(s => s.avg_rr).sort((a,b) => (b.avg_rr||0)-(a.avg_rr||0)).map((s, i) => (
                <div key={i} className="flex items-center justify-between border-b border-slate-50 py-2">
                  <div className="text-sm text-slate-700 font-medium">{s.strategy}</div>
                  <div className="flex items-center gap-3">
                    <div className="text-xs text-slate-400">{s.total} signals</div>
                    <div className={`font-bold text-sm ${(s.avg_rr||0) >= 2 ? 'text-green-600' : (s.avg_rr||0) >= 1.5 ? 'text-amber-600' : 'text-red-500'}`}>
                      {s.avg_rr}:1
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Section>
        </div>
      )}

      {/* ── CONFIDENCE TAB ── */}
      {tab === "confidence" && (
        <div className="space-y-5">
          <Section title="🎯 Win Rate & R:R by Confidence Band">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 uppercase border-b border-slate-100">
                    <th className="text-left py-2 pr-4">Confidence Band</th>
                    <th className="text-right px-3">Total Signals</th>
                    <th className="text-right px-3">Completed</th>
                    <th className="text-right px-3">Completion Rate</th>
                    <th className="text-right px-3">Avg R:R</th>
                  </tr>
                </thead>
                <tbody>
                  {confidence_buckets.map((b, i) => (
                    <tr key={i} className="border-b border-slate-50 hover:bg-slate-50">
                      <td className="py-3 pr-4 font-medium text-slate-700">{b.band}</td>
                      <td className="text-right px-3 text-slate-600">{b.total.toLocaleString()}</td>
                      <td className="text-right px-3 text-green-600">{b.completed.toLocaleString()}</td>
                      <td className="text-right px-3"><WrBadge wr={b.win_rate} /></td>
                      <td className="text-right px-3 font-medium text-slate-700">{b.avg_rr ? `${b.avg_rr}:1` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-slate-400 mt-3">Higher confidence should correlate with higher completion rate. If not, strategy confidence calibration needs review.</p>
          </Section>

          {/* Confidence visual */}
          <Section title="Completion Rate by Confidence Band">
            <div className="space-y-3">
              {confidence_buckets.map((b, i) => (
                <div key={i} className="flex items-center gap-3">
                  <div className="w-16 text-xs font-mono font-bold text-slate-600 shrink-0">{b.band}</div>
                  <div className="flex-1 bg-slate-100 rounded-full h-6">
                    <div className="h-6 rounded-full flex items-center pl-2 text-xs text-white font-medium transition-all"
                      style={{ width: `${Math.max(2, b.win_rate)}%`, backgroundColor: b.win_rate >= 60 ? '#10b981' : b.win_rate >= 40 ? '#f59e0b' : '#ef4444' }}>
                      {b.win_rate}%
                    </div>
                  </div>
                  <div className="text-xs text-slate-400 w-20 text-right shrink-0">{b.total.toLocaleString()} signals</div>
                </div>
              ))}
            </div>
          </Section>
        </div>
      )}

      {/* ── AI INSIGHTS TAB ── */}
      {tab === "insights" && (
        <div className="space-y-5">
          {/* Generate button */}
          <div className="bg-gradient-to-r from-indigo-50 to-purple-50 border border-indigo-200 rounded-xl p-5">
            <div className="flex items-start justify-between flex-wrap gap-3">
              <div>
                <h3 className="font-bold text-indigo-800">🤖 AI Strategy Analysis</h3>
                <p className="text-indigo-600 text-sm mt-1">Auto-generates daily at 09:00 KL. Each analysis is saved as an audit trail entry.</p>
              </div>
              <button onClick={generateInsights} disabled={generating}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white rounded-lg text-sm font-medium flex items-center gap-2">
                {generating ? <><span className="animate-spin">⏳</span> Generating...</> : "⚡ Generate Now"}
              </button>
            </div>
            {genMsg && <div className={`mt-3 text-sm font-medium ${genMsg.startsWith('✅') ? 'text-green-700' : 'text-red-600'}`}>{genMsg}</div>}
          </div>

          {/* Recommendations list */}
          {recsLoading ? (
            <div className="text-center text-slate-400 py-8">Loading audit log...</div>
          ) : recs.length === 0 ? (
            <div className="text-center text-slate-400 py-12">
              <div className="text-4xl mb-3">🤖</div>
              <div>No AI insights yet. Hit "Generate Now" or wait for the daily 09:00 KL run.</div>
            </div>
          ) : (
            <div className="space-y-4">
              {recs.map((rec) => (
                <div key={rec.id} className={`bg-white rounded-xl border p-5 ${rec.status === 'new' ? 'border-indigo-300' : rec.status === 'applied' ? 'border-green-300' : rec.status === 'dismissed' ? 'border-slate-200 opacity-60' : 'border-slate-200'}`}>
                  <div className="flex items-start justify-between flex-wrap gap-3 mb-4">
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-bold text-slate-800">{new Date(rec.generated_at || rec.created_date).toLocaleString('en-GB', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' })}</span>
                        <span className={`px-2 py-0.5 rounded text-xs font-bold border ${
                          rec.status === 'new' ? 'bg-indigo-50 border-indigo-200 text-indigo-700' :
                          rec.status === 'applied' ? 'bg-green-50 border-green-200 text-green-700' :
                          rec.status === 'reviewed' ? 'bg-amber-50 border-amber-200 text-amber-700' :
                          'bg-slate-50 border-slate-200 text-slate-500'
                        }`}>{rec.status?.toUpperCase()}</span>
                        <span className="px-2 py-0.5 rounded text-xs bg-slate-100 text-slate-500">{rec.trigger}</span>
                      </div>
                      {rec.flagged_strategies?.length > 0 && (
                        <div className="mt-1 flex gap-1 flex-wrap">
                          {rec.flagged_strategies.map(s => (
                            <span key={s} className="px-2 py-0.5 bg-red-50 border border-red-200 text-red-600 text-xs rounded">⚠️ {s}</span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="flex gap-2">
                      {rec.status === 'new' && (
                        <>
                          <button onClick={() => markRecStatus(rec.id, 'reviewed')} className="px-3 py-1 bg-amber-100 hover:bg-amber-200 text-amber-700 rounded text-xs font-medium">Mark Reviewed</button>
                          <button onClick={() => markRecStatus(rec.id, 'applied')} className="px-3 py-1 bg-green-100 hover:bg-green-200 text-green-700 rounded text-xs font-medium">Applied</button>
                          <button onClick={() => markRecStatus(rec.id, 'dismissed')} className="px-3 py-1 bg-slate-100 hover:bg-slate-200 text-slate-600 rounded text-xs font-medium">Dismiss</button>
                        </>
                      )}
                      {rec.status === 'reviewed' && (
                        <button onClick={() => markRecStatus(rec.id, 'applied')} className="px-3 py-1 bg-green-100 hover:bg-green-200 text-green-700 rounded text-xs font-medium">Mark Applied</button>
                      )}
                    </div>
                  </div>

                  {/* Recommendations text */}
                  <div className="prose prose-sm max-w-none text-slate-700">
                    <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed bg-slate-50 rounded-lg p-4 border border-slate-100">{rec.recommendations}</pre>
                  </div>

                  {/* Strategy improvements */}
                  {rec.strategy_improvements && Object.keys(rec.strategy_improvements).length > 0 && (
                    <div className="mt-4 border-t border-slate-100 pt-4">
                      <div className="text-xs font-bold text-slate-500 uppercase mb-2">Strategy Improvement Details</div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {Object.entries(rec.strategy_improvements).map(([strat, imp]: [string, any]) => (
                          <div key={strat} className="bg-amber-50 border border-amber-200 rounded-lg p-3">
                            <div className="font-bold text-amber-800 text-sm">{strat}</div>
                            <div className="text-xs text-amber-600 mt-1">Completion: {imp.current_completion_rate}% · RR: {imp.current_avg_rr} · Conf: {imp.current_avg_confidence}%</div>
                            {imp.suggestions?.length > 0 && (
                              <ul className="mt-2 space-y-1">
                                {imp.suggestions.map((s: string, i: number) => (
                                  <li key={i} className="text-xs text-amber-700 flex gap-1"><span>→</span><span>{s}</span></li>
                                ))}
                              </ul>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Outcome notes input */}
                  {(rec.status === 'applied' || rec.status === 'reviewed') && (
                    <div className="mt-4 border-t border-slate-100 pt-3">
                      <div className="text-xs font-bold text-slate-500 uppercase mb-1">Outcome Notes (for AI learning)</div>
                      <OutcomeNotes rec={rec} onSave={loadRecs} />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function OutcomeNotes({ rec, onSave }) {
  const [notes, setNotes] = useState(rec.outcome_notes || '');
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    await AnalyticsRecommendation.update(rec.id, { outcome_notes: notes });
    setSaving(false);
    onSave();
  };
  return (
    <div className="flex gap-2">
      <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={2}
        placeholder="What happened after applying these recommendations? Did win rates improve?"
        className="flex-1 text-sm border border-slate-200 rounded-lg p-2 resize-none focus:outline-none focus:ring-1 focus:ring-indigo-400" />
      <button onClick={save} disabled={saving} className="px-3 py-1 bg-slate-700 hover:bg-slate-800 text-white rounded-lg text-xs font-medium self-start mt-1">
        {saving ? '...' : 'Save'}
      </button>
    </div>
  );
}
