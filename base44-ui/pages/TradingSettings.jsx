import React, { useState, useEffect } from "react";
import { base44 } from "@/api/base44Client";
import { Settings, Save, CheckCircle } from "lucide-react";

export default function TradingSettings() {
  const [form, setForm] = useState({
    risk_pct_display: 1.0,
    target_reward: 1.8,
    drawdown_display: 5.0,
    max_session_exposure_pct: 4.0,
    max_lots: 50.0,
    min_sl_pips: 8.0,
    auto_trade: false,
    friday_flush: false,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    base44.functions.invoke("loadAllSettings", {}).then(res => {
      const d = res.data;
      if (d && !d.error) {
        setForm({
          risk_pct_display:         d.risk_pct != null ? parseFloat((d.risk_pct * 100).toPrecision(6)) : 1.0,
          target_reward:            d.target_reward ?? 1.8,
          drawdown_display:         d.daily_drawdown_limit != null ? parseFloat((d.daily_drawdown_limit * 100).toPrecision(6)) : 5.0,
          max_session_exposure_pct: d.max_session_exposure_pct ?? 4.0,
          max_lots:                 d.max_lots ?? 50.0,
          min_sl_pips:              d.min_sl_pips ?? 8.0,
          auto_trade:               d.auto_trade   ?? false,
          friday_flush:             d.friday_flush ?? false,
        });
      }
    }).finally(() => setLoading(false));
  }, []);

  const handleChange = (field, value) => setForm(prev => ({ ...prev, [field]: parseFloat(value) || 0 }));
  const handleToggle = (field) => setForm(prev => ({ ...prev, [field]: !prev[field] }));

  const handleSave = async () => {
    setSaving(true);
    await base44.functions.invoke("saveAllSettings", {
      auto_trade:                form.auto_trade,
      friday_flush:              form.friday_flush,
      risk_pct:                  form.risk_pct_display / 100,
      target_reward:             form.target_reward,
      daily_drawdown_limit:      form.drawdown_display / 100,
      max_session_exposure_pct:  form.max_session_exposure_pct,
      max_lots:                  form.max_lots,
      min_sl_pips:               form.min_sl_pips,
    });
    setSaving(false); setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const numericFields = [
    { key: "risk_pct_display",         label: "Risk Percentage (%)",         hint: "e.g. 1.0 = 1% risk per trade",                   step: "0.1", suffix: "%" },
    { key: "target_reward",            label: "Target Reward",               hint: "e.g. 1.8 = 1:1.8 RR",                            step: "0.1", suffix: null },
    { key: "drawdown_display",         label: "Daily Drawdown Limit (%)",    hint: "e.g. 5.0 = 5% max daily loss",                   step: "0.1", suffix: "%" },
    { key: "max_session_exposure_pct", label: "Max Session Exposure (%)",    hint: "e.g. 4.0 = max 4% total open risk at any time",  step: "0.1", suffix: "%" },
    { key: "max_lots",                 label: "Max Lot Size",                hint: "e.g. 50 = hard cap on any single trade",          step: "1",   suffix: "lots" },
    { key: "min_sl_pips",              label: "Min Stop Loss (pips)",         hint: "e.g. 8 = reject signals with SL tighter than 8p", step: "0.5", suffix: "pips" },
  ];

  const toggleFields = [
    { key: "auto_trade",   label: "Auto Trade",   hint: "Enable autonomous trade execution",          activeColor: "emerald" },
    { key: "friday_flush", label: "Friday Flush", hint: "Close all positions at 16:00 UK on Fridays", activeColor: "amber" },
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
      <div className="card-dark p-6 flex flex-col gap-5 mb-4">
        <p className="text-xs font-semibold tracking-widest uppercase text-slate-500">Execution Controls</p>
        {toggleFields.map(({ key, label, hint, activeColor }) => {
          const active = form[key];
          const colors = {
            emerald: { track: active ? "bg-emerald-500" : "bg-slate-700", badge: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" },
            amber:   { track: active ? "bg-amber-500"  : "bg-slate-700", badge: "text-amber-400 bg-amber-500/10 border-amber-500/20" },
          };
          const c = colors[activeColor];
          return (
            <div key={key} className="flex items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-200">{label}</span>
                  <span className={}>{active ? "ON" : "OFF"}</span>
                </div>
                <p className="text-xs text-slate-600 mt-0.5">{hint}</p>
              </div>
              <button onClick={() => handleToggle(key)} className={}>
                <span className={} />
              </button>
            </div>
          );
        })}
      </div>
      <div className="card-dark p-6 flex flex-col gap-6 mb-4">
        <p className="text-xs font-semibold tracking-widest uppercase text-slate-500">Risk Configuration</p>
        {numericFields.map(({ key, label, hint, step, suffix }) => (
          <div key={key} className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-slate-300">{label}</label>
            <div className="relative">
              <input type="number" step={step} value={form[key]} onChange={e => handleChange(key, e.target.value)} className={} />
              {suffix && (<span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 text-sm pointer-events-none">{suffix}</span>)}
            </div>
            <p className="text-xs text-slate-600">{hint}</p>
          </div>
        ))}
      </div>
      <button onClick={handleSave} disabled={saving} className={}>
        {saved ? (<><CheckCircle className="w-4 h-4" /> Saved to Database!</>) : (<><Save className="w-4 h-4" /> {saving ? "Saving…" : "Save All Settings"}</>)}
      </button>
      <div className="mt-4 card-dark p-4">
        <p className="text-xs font-semibold tracking-widest uppercase text-slate-500 mb-1">Executor Config Endpoint</p>
        <p className="text-xs text-slate-600 font-mono break-all">POST /api/functions/getBase64Config</p>
        <p className="text-xs text-slate-700 mt-1">Returns all settings (including AUTO_TRADE, FRIDAY_FLUSH) as base64 JSON.</p>
      </div>
    </div>
  );
}
