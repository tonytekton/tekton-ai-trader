import React, { useState, useEffect, useCallback } from 'react';
import { base44 } from '@/api/base44Client';
import { DollarSign, Activity, Zap, RefreshCw } from 'lucide-react';
import MetricCard from '../components/dashboard/MetricCard';
import MarginGauge from '../components/dashboard/MarginGauge';
import FridayCountdown from '../components/dashboard/FridayCountdown';
import ToggleSwitch from '../components/dashboard/ToggleSwitch';

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);

  const fetchAll = useCallback(async () => {
    const mRes = await base44.functions.invoke('getAccountMetrics');
    if (mRes.status === 'fulfilled' || mRes.data) setMetrics(mRes.data?.data ?? mRes.data);
    setLastUpdated(new Date());
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 30000);
    return () => clearInterval(id);
  }, [fetchAll]);

  const fmt = (n, prefix = '$') => n != null ? `${prefix}${parseFloat(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Command Center</h1>
          <p className="text-xs text-slate-600 mt-1">
            {lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : 'Loading...'}
          </p>
        </div>
        <button onClick={fetchAll} className="p-2 rounded-lg border border-slate-800 text-slate-500 hover:text-slate-300 hover:border-slate-600 transition-all">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="flex flex-col gap-4 lg:col-span-1">
          <MarginGauge used={metrics?.margin_used} total={metrics?.balance} />
          <FridayCountdown />
        </div>
        <div className="grid grid-cols-2 gap-4 lg:col-span-2">
          <MetricCard label="Balance" value={fmt(metrics?.balance)} sub="Account balance" icon={DollarSign} color="green" />
          <MetricCard label="Equity" value={fmt(metrics?.equity)} sub="Net asset value" icon={Activity} color="blue" />
          <MetricCard label="Margin Used" value={fmt(metrics?.margin_used)} sub="Open exposure" icon={Zap} color="yellow" />
          <MetricCard label="Free Margin" value={fmt(metrics?.free_margin)} sub="Available capital" icon={DollarSign} color="cyan" />
        </div>
        <div className="flex flex-col gap-4 lg:col-span-2">
          {metrics?.open_positions != null && (
            <MetricCard label="Open Positions" value={metrics.open_positions} sub="Live trades" icon={Activity} color="purple" />
          )}
          {metrics?.daily_pnl != null && (
            <MetricCard label="Daily P&L" value={fmt(metrics.daily_pnl)} sub="Today's performance" icon={DollarSign} color={metrics.daily_pnl >= 0 ? 'green' : 'red'} />
          )}
        </div>
      </div>
    </div>
  );
}