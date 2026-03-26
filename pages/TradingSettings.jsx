import React, { useState, useEffect } from 'react';
import { Settings, Save, CheckCircle, AlertCircle } from 'lucide-react';

// Call bridge directly — avoids Base44 function relay which adds 150s+ latency
const BRIDGE_URL = 'http://35.234.132.174:8080';
const BRIDGE_KEY = import.meta.env.VITE_BRIDGE_KEY || '';

async function bridgeFetch(path, options = {}) {
  const res = await fetch(`${BRIDGE_URL}${path}`, {
    ...options,
    headers: { 'X-Bridge-Key': BRIDGE_KEY, 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  if (!res.ok) throw new Error(`Bridge ${path} returned ${res.status}`);
  return res.json();
}

export default function TradingSettings() {
  const [form, setForm] = useState({
    risk_pct_display: 1.0,
    target_reward: 2.0,
    drawdown_display: 7.5,
    max_session_exposure_pct: 4.0,
    max_lots: 50,
    min_sl_pips: 8.0,
    api_rate_limit: 75,
    auto_trade: false,
    friday_flush: false,
  });
  const [loading, setLoading]   = useState(true);
  const [saving, setSaving]     = useState(false);
  const [saved, setSaved]       = useState(false);
  const [error, setError]       = useState(null);

  useEffect(() => {
    bridgeFetch('/data/settings')
      .then(d => {
        if (d && !d.error) {
          setForm({
            risk_pct_display:         d.risk_pct != null ? parseFloat((d.risk_pct * 100).toPrecision(6)) : 1.0,
            target_reward:            d.target_reward            ?? 2.0,
            drawdown_display:         d.daily_drawdown_limit != null ? parseFloat((d.daily_drawdown_limit * 100).toPrecision(6)) : 7.5,
            max_session_exposure_pct: d.max_session_exposure_pct ?? 4.0,
            max_lots:                 d.max_lots ?? 50,
            min_sl_pips:              d.min_sl_pips              ?? 8.0,
            api_rate_limit:           d.api_rate_limit           ?? 75,
            auto_trade:               d.auto_trade               ?? false,
            friday_flush:             d.friday_flush             ?? false,
          });
        }
      })
      .catch(e => setError(`Load failed: ${e.message}`))
      .finally(() => setLoading(false));
  }, []);

  const handleChange = (field, value) => setForm(prev => ({ ...prev, [field]: parseFloat(value) || 0 }));
  const handleToggle = (field)        => setForm(prev => ({ ...prev, [field]: !prev[field] }));

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      // Route through backend function — BRIDGE_KEY is a server-side secret,
      // not available as a build-time VITE_ env var in the frontend.
      const res = await fetch('/api/functions/saveAllSettings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          auto_trade:               form.auto_trade,
          friday_flush:             form.friday_flush,
          risk_pct:                 form.risk_pct_display / 100,
          target_reward:            form.target_reward,
          daily_drawdown_limit:     form.drawdown_display / 100,
          max_session_exposure_pct: form.max_session_exposure_pct,
          max_lots:                 form.max_lots,
          min_sl_pips:              form.min_sl_pips,
          api_rate_limit:           parseInt(form.api_rate_limit) || 75,
        }),
      });
      const result = await res.json();
      if (result.success) {
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      } else {
        setError(result.error || 'Save failed — unknown error');
      }
    } catch (e) {
      setError(`Save failed: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const numericFields = [
    { key: 'risk_pct_display',         label: 'Risk Percentage (%)',       hint: 'e.g. 1.0 = 1% risk per trade',                             step: '0.1',  suffix: '%'    },
    { key: 'target_reward',            label: 'Target Reward',             hint: 'e.g. 2.0 = 1:2 RR minimum',                                step: '0.1',  suffix: null   },
    { key: 'drawdown_display',         label: 'Daily Drawdown Limit (%)',  hint: 'e.g. 7.5 = 7.5% max daily loss',                           step: '0.1',  suffix: '%'    },
    { key: 'max_session_exposure_pct', label: 'Max Session Exposure (%)',  hint: 'e.g. 4.0 = max 4% total open risk at any time',            step: '0.1',  suffix: '%'    },
    { key: 'max_lots',                 label: 'Max Lot Size',              hint: 'Hard cap on any single trade. DB currently 6 (test). Fallback 50.',step: '1',    suffix: 'lots' },
    { key: 'min_sl_pips',              label: 'Min Stop Loss (pips)',       hint: 'e.g. 8 = reject signals with SL tighter than 8p',          step: '0.5',  suffix: 'pips' },
  { key: 'api_rate_limit',           label: 'API Rate Limit (req/min)',   hint: 'cTrader API max calls/min. Default 75. Warning at 80%, Critical at 93%', step: '1', suffix: 'req/min' },
  ];

  const toggleFields = [
    { key: 'auto_trade',   label: 'Auto Trade',   hint: 'Enable autonomous trade execution',           activeColor: 'emerald' },
    { key: 'friday_flush', label: 'Friday Flush', hint: 'Close all positions at 16:00 UTC on Fridays', activeColor: 'amber'   },
  ];

  if (loading) return (
    <div className="min-h-screen p-4 md:p-8 max-w-2xl mx-auto flex items-center justify-center">
      <div className="text-slate-500 text-sm animate-pulse">Loading settings…</div>
    </div>
  );

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-2xl mx-auto">
      <div className="flex items-center gap-3 mb-8">
        <Settings className="w-6 h-6 text-blue-400" />
        <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Trading Settings</h1>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-2 mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Toggle controls */}
      <div className="card-dark p-6 flex flex-col gap-5 mb-4">
        <p className="text-xs font-semibold tracking-widest uppercase text-slate-500">Execution Controls</p>
        {toggleFields.map(({ key, label, hint, activeColor }) => {
          const active = form[key];
          const colors = {
            emerald: { track: active ? 'bg-emerald-500' : 'bg-slate-700', badge: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' },
            amber:   { track: active ? 'bg-amber-500'  : 'bg-slate-700', badge: 'text-amber-400  bg-amber-500/10  border-amber-500/20'  },
          };
          const c = colors[activeColor];
          return (
            <div key={key} className="flex items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-200">{label}</span>
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${c.badge}`}>{active ? 'ON' : 'OFF'}</span>
                </div>
                <p className="text-xs text-slate-600 mt-0.5">{hint}</p>
              </div>
              <button onClick={() => handleToggle(key)} className={`relative w-11 h-6 rounded-full transition-colors duration-200 shrink-0 ${c.track}`}>
                <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full shadow transition-transform duration-200 bg-white ${active ? 'translate-x-5' : 'translate-x-0'}`} />
              </button>
            </div>
          );
        })}
      </div>

      {/* Numeric fields */}
      <div className="card-dark p-6 flex flex-col gap-6 mb-4">
        <p className="text-xs font-semibold tracking-widest uppercase text-slate-500">Risk Configuration</p>
        {numericFields.map(({ key, label, hint, step, suffix }) => (
          <div key={key} className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-slate-300">{label}</label>
            <div className="relative">
              <input
                type="number" step={step} value={form[key]}
                onChange={e => handleChange(key, e.target.value)}
                className={`w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-blue-500 transition-colors ${suffix ? 'pr-12' : ''}`}
              />
              {suffix && <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 text-sm pointer-events-none">{suffix}</span>}
            </div>
            <p className="text-xs text-slate-600">{hint}</p>
          </div>
        ))}
      </div>

      {/* Save button */}
      <button
        onClick={handleSave}
        disabled={saving}
        className={`w-full flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-all
          ${saved
            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
            : 'bg-blue-500/10 text-blue-400 border border-blue-500/20 hover:bg-blue-500/20'}
          disabled:opacity-50`}
      >
        {saved
          ? <><CheckCircle className="w-4 h-4" /> Saved to Database!</>
          : <><Save className="w-4 h-4" /> {saving ? 'Saving…' : 'Save All Settings'}</>
        }
      </button>
    </div>
  );
}
