// See full source in Base44 app — pages/Signals
// This file is auto-synced from the Base44 UI layer.
import React, { useState, useEffect, useCallback } from 'react';
import { base44 } from '@/api/base44Client';
import { Brain, TrendingUp, TrendingDown, RefreshCw, ChevronRight } from 'lucide-react';
import ConfidenceBar from '../components/signals/ConfidenceBar';
import SignalDetailModal from '../components/signals/SignalDetailModal';

const STATUS_STYLES = {
  PENDING:   'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  EXECUTED:  'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  FAILED:    'bg-red-500/10 text-red-400 border-red-500/20',
  EXPIRED:   'bg-slate-700/30 text-slate-500 border-slate-700/50',
  CANCELLED: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
};

export default function Signals() {
  const [signals, setSignals] = useState([]);
  const [statsData, setStatsData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [symbolFilter, setSymbolFilter] = useState('');

  useEffect(() => {
    base44.functions.invoke('getSignalStats').then(res => setStatsData(res.data)).catch(() => setStatsData(null));
  }, []);

  const fetchSignals = useCallback(async (status = statusFilter, symbol = symbolFilter) => {
    setLoading(true);
    try {
      const res = await base44.functions.invoke('getSignals', { status, symbol });
      const payload = res.data;
      const arr = Array.isArray(payload) ? payload : Array.isArray(payload?.signals) ? payload.signals : Array.isArray(payload?.data) ? payload.data : [];
      setSignals(arr);
    } catch { setSignals([]); } finally { setLoading(false); }
  }, [statusFilter, symbolFilter]);

  useEffect(() => { fetchSignals('', ''); }, []);

  // Full component — see Base44 source for complete render
  return <div>Signals Page — see Base44 source</div>;
}