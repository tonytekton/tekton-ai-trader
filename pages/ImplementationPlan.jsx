import React, { useState, useEffect } from 'react';
import { base44 } from '@/api/base44Client';
import {
  ClipboardList, CheckCircle, Circle, Clock, AlertTriangle,
  ChevronDown, ChevronRight, RefreshCw, Save
} from 'lucide-react';

const PHASES = [
  {
    id: 'p1', title: 'Phase 1 — Bridge: New Endpoints', color: 'blue',
    desc: 'Add GET /data/settings and POST /data/settings to tekton_bridge.py.',
    tasks: [
      { id: 't1_1', title: 'Add GET /data/settings to tekton_bridge.py', detail: 'Query settings table WHERE id=1, return all columns as JSON', file: 'tekton_bridge.py' },
      { id: 't1_2', title: 'Add POST /data/settings to tekton_bridge.py', detail: 'Accept JSON body with any subset of settings fields, UPDATE settings SET ... WHERE id=1', file: 'tekton_bridge.py' },
      { id: 't1_3', title: 'Ensure settings table row id=1 exists in DB', detail: 'INSERT INTO settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING', file: 'PostgreSQL (tekton-trader DB)' },
      { id: 't1_4', title: 'Test GET /data/settings via curl', detail: "curl -H 'X-Bridge-Key: <key>' http://localhost:8080/data/settings", file: 'Terminal' },
      { id: 't1_5', title: 'Test POST /data/settings via curl', detail: "curl -X POST -H 'X-Bridge-Key: <key>' -d '{\"auto_trade\": true}' http://localhost:8080/data/settings", file: 'Terminal' },
    ],
  },
  {
    id: 'p2', title: 'Phase 2 — Executor: Read Settings from SQL', color: 'purple',
    desc: 'Patch tekton_executor.py so all config is read from the SQL settings table.',
    tasks: [
      { id: 't2_1', title: 'Add fetch_settings() to tekton_executor.py', detail: 'Uses psycopg2 to run SELECT * FROM settings WHERE id=1', file: 'tekton_executor.py' },
      { id: 't2_2', title: 'Gate poll_signals() on AUTO_TRADE toggle', detail: 'Before processing any PENDING signal: check auto_trade from settings', file: 'tekton_executor.py' },
      { id: 't2_3', title: "Replace hardcoded risk_pct with settings['risk_pct']", detail: 'Replace all literals with fetch_settings() lookup', file: 'tekton_executor.py' },
      { id: 't2_4', title: 'Remove Base44 getBase64Config HTTP call from executor', detail: 'All config is local SQL now', file: 'tekton_executor.py' },
      { id: 't2_5', title: 'Test executor with AUTO_TRADE = false in DB', detail: 'Confirm executor logs skip and does NOT execute any signal', file: 'tekton_executor.py' },
      { id: 't2_6', title: 'Test executor with AUTO_TRADE = true in DB', detail: 'Insert a TEST signal. Confirm executor picks it up', file: 'tekton_executor.py' },
    ],
  },
  {
    id: 'p3', title: 'Phase 3 — Base44 UI: Settings Page Wired to SQL', color: 'cyan',
    desc: 'Verify the TradingSettings page successfully reads and writes to SQL via the bridge.',
    tasks: [
      { id: 't3_1', title: 'Test loadAllSettings → GET bridge /data/settings', detail: 'Open TradingSettings page. Confirm values load from SQL.', file: 'Base44 UI → TradingSettings page' },
      { id: 't3_2', title: 'Test saveAllSettings → POST bridge /data/settings', detail: 'Change risk_pct to 0.02, click Save. Verify SQL row updated.', file: 'Base44 UI → TradingSettings page' },
      { id: 't3_3', title: 'Test Auto Trade toggle persists to SQL', detail: 'Toggle Auto Trade ON → Save. Verify auto_trade = true in DB.', file: 'Base44 UI → TradingSettings page' },
      { id: 't3_4', title: 'Verify Dashboard toggles also use new settings source', detail: 'Confirm they call loadAllSettings / saveAllSettings (not old entities).', file: 'Base44 UI → Dashboard page' },
      { id: 't3_9', title: 'Remove execution controls from Command Center Dashboard', detail: 'These toggles already exist in Trading Settings. Remove duplicates from Dashboard.', file: 'Base44 UI → Dashboard page' },
      { id: 't3_7', title: 'Fix Auto Trade toggle not persisting on page refresh', detail: 'BUG: Auto Trade toggles revert to default after refresh.', file: 'TradingSettings page + saveAllSettings + loadAllSettings + tekton_bridge.py' },
      { id: 't3_8', title: 'Fix Friday Flush toggle not persisting on page refresh', detail: 'Same bug pattern as Auto Trade.', file: 'TradingSettings page + tekton_bridge.py + PostgreSQL' },
      { id: 't3_5', title: 'Test Portfolio Heat display on Command Center', detail: 'Confirm the margin gauge widget loads and displays a real value.', file: 'Base44 UI → Dashboard page → getAccountMetrics function' },
      { id: 't3_6', title: 'Verify Portfolio Heat updates on refresh / auto-poll', detail: 'With an open position, confirm the margin gauge value changes.', file: 'Base44 UI → Dashboard page' },
    ],
  },
  {
    id: 'p4', title: 'Phase 4 — Bridge Filename & Service References', color: 'yellow',
    desc: 'The bridge was renamed to tekton_bridge.py. Ensure all references are updated.',
    tasks: [
      { id: 't4_1', title: 'Update systemd service file to reference tekton_bridge.py', detail: 'Edit /etc/systemd/system/tekton-ai-trader-bridge.service', file: '/etc/systemd/system/tekton-ai-trader-bridge.service' },
      { id: 't4_2', title: 'Update start_tekton.sh if it references old filename', detail: "Check: grep 'tekton-bridge-v4' start_tekton.sh", file: 'start_tekton.sh' },
      { id: 't4_3', title: 'Confirm bridge service running after rename', detail: 'sudo systemctl status tekton-ai-trader-bridge.service', file: 'Terminal' },
    ],
  },
  {
    id: 'p5', title: 'Phase 5 — Backfill Script: Verify tekton_backfill.py', color: 'green',
    desc: 'Confirm tekton_backfill.py is still working correctly after all changes.',
    tasks: [
      { id: 't5_1', title: 'Review tekton_backfill.py for hardcoded config references', detail: 'Check if backfill reads risk_pct, auto_trade from Base44 entities', file: 'tekton_backfill.py' },
      { id: 't5_2', title: 'Verify cron job is still active', detail: 'Run: crontab -l', file: 'crontab' },
      { id: 't5_3', title: 'Check backfill output in combined_trades.log', detail: 'tail -f combined_trades.log | grep backfill', file: 'combined_trades.log' },
    ],
  },
  {
    id: 'p6', title: 'Phase 6 — End-to-End Smoke Test', color: 'red',
    desc: 'Full system integration test after all phases complete.',
    tasks: [
      { id: 't6_1', title: 'Set AUTO_TRADE = true in TradingSettings UI', detail: 'Open TradingSettings → toggle Auto Trade ON → Save', file: 'Base44 UI' },
      { id: 't6_2', title: 'Insert a test signal via ManualSignal page', detail: 'Confirm it appears in Signals Log as PENDING', file: 'Base44 UI → ManualSignal page' },
      { id: 't6_3', title: 'Confirm executor picks up signal and executes', detail: 'Watch combined_trades.log. Signal status: PENDING → EXECUTED', file: 'combined_trades.log + DB' },
      { id: 't6_4', title: 'Confirm execution appears in Execution Journal', detail: 'New trade entry should be visible with correct symbol, volume, SL/TP', file: 'Base44 UI → Executions page' },
      { id: 't6_5', title: 'Set AUTO_TRADE = false and confirm no new executions', detail: 'Toggle off → insert another test signal → confirm executor skips it', file: 'Base44 UI + DB + combined_trades.log' },
    ],
  },
  {
    id: 'p7', title: 'Phase 7 — Strategy Expansion', color: 'blue',
    desc: 'Deploy and validate the full strategy library: ICT FVG, EMA Pullback, Session ORB, VWAP Reversion, Breakout Retest, RSI Divergence, Lester LSV.',
    tasks: [
      { id: 't7_1', title: 'Verify all 7 strategy services running on VM', detail: 'sudo systemctl status tekton-strat-*.service', file: 'VM systemd' },
      { id: 't7_2', title: 'Confirm MIN_RR=1.5 gate active on all strategies', detail: 'Review each strat_*.py — confirm tp_pips/sl_pips >= 1.5 check before signal insert', file: 'All strat_*.py files' },
      { id: 't7_3', title: 'Verify confidence_score stored as integer (0-100)', detail: 'SELECT strategy, confidence_score FROM signals ORDER BY created_at DESC LIMIT 20', file: 'PostgreSQL' },
      { id: 't7_4', title: 'Validate session exposure cap gate in executor', detail: 'Confirm 🛑 log appears when open positions × risk_pct >= max_session_exposure_pct', file: 'combined_trades.log' },
      { id: 't7_5', title: 'Document strategy onboarding process', detail: 'Update SystemContext page with strategy checklist and signal schema rules', file: 'SystemContext page + README' },
    ],
  },
  {
    id: 'p8', title: 'Phase 8 — Economic Calendar (Passive)', color: 'orange',
    desc: 'Integrate ForexFactory economic calendar into the UI. Display upcoming high-impact events on the Dashboard and Analytics page. No trade gating yet.',
    tasks: [
      { id: 't8_1', title: 'Create economic_events table in PostgreSQL', detail: 'CREATE TABLE economic_events (id SERIAL PRIMARY KEY, event_date TIMESTAMPTZ, currency VARCHAR(10), indicator_name TEXT, impact_level VARCHAR(10), source VARCHAR(50) DEFAULT \'forexfactory\', created_at TIMESTAMPTZ DEFAULT NOW())', file: 'PostgreSQL (tekton-trader DB)' },
      { id: 't8_2', title: 'Write tekton_calendar.py VM fetcher script', detail: 'Fetches ForexFactory XML feed (nfs.faireconomy.media/ff_calendar_thisweek.xml), parses medium+high impact events, upserts to economic_events table. Port from V3 logic.', file: 'tekton_calendar.py (new)' },
      { id: 't8_3', title: 'Add cron job for calendar refresh', detail: 'Run every 6 hours: 0 */6 * * * /path/to/venv/bin/python /opt/tekton/tekton_calendar.py', file: 'crontab' },
      { id: 't8_4', title: 'Add GET /calendar/events bridge endpoint', detail: 'Query economic_events WHERE event_date BETWEEN NOW()-1hr AND NOW()+7days, return JSON array ordered by event_date', file: 'tekton_bridge.py' },
      { id: 't8_5', title: 'Deploy getEconomicCalendar Base44 backend function', detail: 'Proxies GET /calendar/events from bridge. Returns events array to UI.', file: 'Base44 backend function' },
      { id: 't8_6', title: 'Add Economic Calendar widget to Dashboard', detail: 'Strip showing next 3 high-impact events today/tomorrow. Coloured by impact (red=high, amber=medium). Shows time until event.', file: 'Base44 UI → Dashboard page' },
      { id: 't8_7', title: 'Add full Economic Calendar view to Analytics page', detail: 'Grouped by day. All currencies. Countdown timers. 7-day view.', file: 'Base44 UI → Analytics page' },
      { id: 't8_8', title: 'Add manual import fallback', detail: 'Port V3 manualCalendarImport function — accepts Myfxbook XML or tab-separated text, writes to SQL economic_events table', file: 'tekton_calendar.py + Base44 backend function' },
    ],
  },
  {
    id: 'p9', title: 'Phase 9 — Economic Calendar (Active Gating)', color: 'red',
    desc: 'Wire the economic calendar into the executor and monitor. Block new trades and tighten position management around high-impact news events.',
    tasks: [
      { id: 't9_1', title: 'Add news_filter_enabled column to settings table', detail: 'ALTER TABLE settings ADD COLUMN news_filter_enabled BOOLEAN DEFAULT TRUE; ALTER TABLE settings ADD COLUMN news_buffer_mins INT DEFAULT 15;', file: 'PostgreSQL (tekton-trader DB)' },
      { id: 't9_2', title: 'Add news_filter_enabled + news_buffer_mins to TradingSettings UI', detail: 'Toggle + number input. Saves via saveAllSettings. Hint: "Block new trades within X min of high-impact events"', file: 'Base44 UI → TradingSettings page' },
      { id: 't9_3', title: 'Add is_news_window() helper to tekton_executor.py', detail: 'Queries economic_events for any HIGH impact event on traded currency within ±news_buffer_mins. Returns True/False.', file: 'tekton_executor.py' },
      { id: 't9_4', title: 'Gate signal execution on news window check', detail: 'Before executing any signal: if news_filter_enabled and is_news_window(currency): log skip reason, leave signal PENDING, retry after window passes', file: 'tekton_executor.py' },
      { id: 't9_5', title: 'Add news awareness to tekton_monitor.py', detail: 'If position currency has HIGH impact event within 10 min: set intervention bias to HOLD. No ADJUST_SL or ADJUST_TP during news window.', file: 'tekton_monitor.py' },
      { id: 't9_6', title: 'Test news gate with simulated upcoming event', detail: 'Insert a test high-impact event 5 min from now in economic_events. Fire a test signal. Confirm executor skips it with news gate log.', file: 'PostgreSQL + combined_trades.log' },
      { id: 't9_7', title: 'Add news window indicator to Dashboard', detail: 'If any HIGH impact event for an open position currency is within 30 min: show amber warning banner on Command Center.', file: 'Base44 UI → Dashboard page' },
    ],
  },
  {
    id: 'p10', title: 'Phase 10 — Analytics Page', color: 'purple',
    desc: 'Build a dedicated Analytics page with AI-driven performance attribution and recommendations. Dashboard shows exec summary; Analytics goes deep.',
    tasks: [
      { id: 't10_1', title: 'Create getAnalytics Base44 backend function', detail: 'Queries signals + executions from SQL. Returns: win_rate per strategy, avg_r per strategy, profit_factor, confidence_vs_r correlation, symbol breakdown, session breakdown.', file: 'Base44 backend function' },
      { id: 't10_2', title: 'Build Analytics page — Strategy Performance section', detail: 'Table: strategy | signals | win_rate | avg_r | profit_factor | status (Active/Underperforming). Sortable.', file: 'Base44 UI → Analytics page (new)' },
      { id: 't10_3', title: 'Build Analytics page — Confidence vs R scatter', detail: 'Show correlation between confidence_score and actual outcome_r. Does high confidence = better results?', file: 'Base44 UI → Analytics page' },
      { id: 't10_4', title: 'Build Analytics page — Symbol/Session breakdown', detail: 'Bar charts: P&L by symbol, P&L by session (London/NY/Asian). Where is money made vs lost?', file: 'Base44 UI → Analytics page' },
      { id: 't10_5', title: 'Build AI Recommendations section', detail: 'Lester analyses current stats and generates 3-5 plain English recommendations. Stored in a AnalyticsSnapshot entity. Refreshed on demand.', file: 'Base44 UI → Analytics page + Base44 backend function' },
      { id: 't10_6', title: 'Add Key Insights strip to Dashboard', detail: 'Show latest 3 AI recommendations as bullet points on Command Center. Read from AnalyticsSnapshot entity. Updated when Analytics page is refreshed.', file: 'Base44 UI → Dashboard page' },
      { id: 't10_7', title: 'Add News Correlation analysis to Analytics page', detail: 'For each closed trade: was it within 30 min of a high-impact event? Show win rate inside vs outside news windows.', file: 'Base44 UI → Analytics page' },
    ],
  },
  {
    id: 'p11', title: 'Phase 11 — Bridge Architectural Refactor (v4.8)', color: 'red', status: 'complete',
    desc: 'Full event-driven rewrite of tekton_bridge.py. Eliminates all polling of cTrader on read paths. Introduces price normalisation layer. Fixes 4 known bugs. Design in BRIDGE_REFACTOR_DESIGN.md.',
    tasks: [
      { id: 't11_1', title: 'Phase 11a — Add price normalisation helpers', detail: 'Add raw_to_decimal(raw_int, digits) and decimal_to_raw(decimal, digits) near top of bridge. All price conversions must go through these — never inline. Agreed Decision #13/#20/#21.', file: 'tekton_bridge.py' },
      { id: 't11_2', title: 'Phase 11a — Add position_state{} to state dict', detail: 'Add position_state: {} and position_state_ready: False to the state dict at top of bridge.', file: 'tekton_bridge.py' },
      { id: 't11_3', title: 'Phase 11a — Add _position_to_dict() helper', detail: 'Single normalisation function that converts a ProtoOAPosition protobuf object into a clean dict using raw_to_decimal(). All position normalisation goes through here.', file: 'tekton_bridge.py' },
      { id: 't11_4', title: 'Phase 11a — Add ExecutionEvent handler in on_message', detail: 'Handle ProtoOAExecutionEvent in on_message (alongside SpotEvent). Call _handle_execution_event(ev) to upsert/remove from position_state{}. Register ProtoOAExecutionEvent payload type in router.', file: 'tekton_bridge.py' },
      { id: 't11_5', title: 'Phase 11a — Add TraderUpdatedEvent handler in on_message', detail: 'Handle ProtoOATraderUpdatedEvent to keep balance_cents, equity_cents, margin_used_cents live in state{}. Register payload type in router.', file: 'tekton_bridge.py' },
      { id: 't11_6', title: 'Phase 11a — Seed position_state at startup via ReconcileReq', detail: 'After symbols load completes, fire one ProtoOAReconcileReq. Process each position through _position_to_dict() into position_state{}. Set position_state_ready=True. This is the ONLY ReconcileReq after startup.', file: 'tekton_bridge.py' },
      { id: 't11_7', title: 'Phase 11b — Fix modify_trade SL/TP format bug', detail: 'BUG: Was passing raw integers to ProtoOAAmendPositionSLTPReq which expects decimal doubles. Fix: req.stopLoss = float(sl_val), req.takeProfit = float(tp_val). Remove the * (10**digits) conversion. Also remove ReconcileReq — use position_state{} for digits lookup.', file: 'tekton_bridge.py' },
      { id: 't11_8', title: 'Phase 11b — Fix execute_trade entry price scaling bug', detail: 'BUG: Was dividing ProtoOAOrder.executionPrice by 10^digits — it is already a decimal double. Fix: store it directly. Only ProtoOADeal.executionPrice needs raw_to_decimal().', file: 'tekton_bridge.py' },
      { id: 't11_9', title: 'Phase 11c — Refactor /positions/list to serve from position_state{}', detail: 'Remove ReconcileReq + GetPositionUnrealizedPnLReq serial calls. Serve open positions directly from position_state{}. Optionally call PnL req for live PnL only.', file: 'tekton_bridge.py' },
      { id: 't11_10', title: 'Phase 11c — Refactor /proxy/executions open trades from position_state{}', detail: 'Remove ReconcileReq and OrderListReq serial calls from get_executions(). Serve open trades from position_state{}. SQL enrichment (sl_pips, tp_pips, strategy) retained.', file: 'tekton_bridge.py' },
      { id: 't11_11', title: 'Phase 11c — Refactor /trade/close to use position_state{}', detail: 'Remove ReconcileReq used only to get volume. Look up position_state[position_id][volume_raw] instead. One fewer cTrader call per close.', file: 'tekton_bridge.py' },
      { id: 't11_12', title: 'Phase 11c — Refactor /account/info to serve from state{}', detail: 'Remove ProtoOATraderReq on every call. Serve balance/equity/margin from state{} (kept live by TraderUpdatedEvent). Add ?refresh=true param to force a live fetch if needed.', file: 'tekton_bridge.py' },
      { id: 't11_13', title: 'Phase 11d — Add DealListReq pagination', detail: 'Replace single DealListReq with fetch_all_deals() helper that loops on hasMore. Apply in /proxy/executions closed trades and /positions/history. Fixes silent data loss for accounts with >500 deals in 30 days.', file: 'tekton_bridge.py' , status: 'complete'},
      { id: 't11_14', title: 'Phase 11d — Push BRIDGE_REFACTOR_DESIGN.md to GitHub', detail: 'Ensure BRIDGE_REFACTOR_DESIGN.md is committed to repo root so it is version-controlled alongside the code.', file: 'GitHub' , status: 'complete'},
      { id: 't11_15', title: 'Phase 11d — Smoke test: execute trade, verify position_state populated', detail: 'Execute a test trade. Confirm ExecutionEvent fires, position appears in position_state{}, /positions/list returns it without any ReconcileReq call in logs.', file: 'Terminal + combined_trades.log', status: 'complete' },
      { id: 't11_16', title: 'Phase 11d — Smoke test: modify SL/TP, verify correct prices sent', detail: 'Call /trade/modify with decimal SL/TP. Confirm bridge sends decimal double to cTrader. Confirm position_state{} updates via ExecutionEvent.', file: 'Terminal + combined_trades.log', status: 'complete' },
      { id: 't11_17', title: 'Phase 11d — Verify monitor poll latency improvement', detail: 'Time a full monitor loop before and after refactor. Target: <100ms per poll vs ~3s before. Check combined_trades.log for zero ReconcileReq calls during normal operation.', file: 'combined_trades.log' , status: 'complete'},
    ],
  },
  {
    id: 'p12', title: 'Phase 12 — cTrader API Rate Monitor', color: 'cyan',
    desc: 'Track cTrader Open API request rate in real-time. After the Phase 11 refactor this should be near-zero on read paths. Monitor confirms the improvement and guards against future regressions.',
    tasks: [
      { id: 't12_1', title: 'Verify rate reduction after Phase 11 refactor', detail: 'Check /stats/api-usage. Confirm calls-per-minute drops significantly vs pre-refactor baseline. Document before/after numbers.', file: 'Bridge /stats/api-usage endpoint' },
      { id: 't12_2', title: 'Add rate limit warning log in bridge', detail: 'If requests_last_60s > 60, log WARNING. If > 70, log CRITICAL and throttle non-essential calls.', file: 'tekton_bridge.py' },
      { id: 't12_3', title: 'Add API Rate Monitor widget to Dashboard', detail: 'Gauge showing requests/min vs limit. Green <50, Amber 50-65, Red >65. Auto-refreshes every 10s.', file: 'Base44 UI → Dashboard page' },
      { id: 't12_4', title: 'Add api_rate_limit column to settings table', detail: 'Store the rate limit value in SQL so it can be updated from UI. ALTER TABLE settings ADD COLUMN api_rate_limit INT DEFAULT 75.', file: 'PostgreSQL + TradingSettings page' },
    ],
  },

{
    id: 'ph', title: 'Hotfixes — Production Patches (2026-03-16 to 2026-03-20)', color: 'red',
    desc: 'Critical bugs fixed directly on main branch to restore system stability. Each fix documented in System Context change log.',
    tasks: [
      { id: 'th_1', title: 'HF-01: Restore .env file after repo reset', detail: 'Missing .env caused Bridge to lose config and auth tokens. Restored and added to .gitignore.', file: 'VM: /home/tony/tekton-ai-trader/.env' },
      { id: 'th_2', title: 'HF-02: Fix API auth header (Bearer → X-Bridge-Key)', detail: 'UI was sending Authorization: Bearer but bridge expects X-Bridge-Key header.', file: 'tekton_bridge.py + Base44 backend functions' },
      { id: 'th_3', title: 'HF-03: Fix pipPosition value (4 → 5 for EURUSD)', detail: 'Incorrect pipPosition caused 10× position sizing errors on 5-digit pairs.', file: 'tekton_bridge.py (symbol spec lookup)' },
      { id: 'th_4', title: 'HF-04: Add max_lots column to settings table', detail: 'Column was missing — executor defaulted to 50 lots causing undersizing on large accounts.', file: 'PostgreSQL settings table' },
      { id: 'th_5', title: 'HF-05: Replace hardcoded PIP_SIZE_MAP with live bridge specs', detail: 'Static map was wrong for many symbols. Executor now fetches live pipPosition from bridge per symbol.', file: 'tekton_executor.py' },
      { id: 'th_6', title: 'HF-06: Fix volume calculation (centilots formula)', detail: 'cTrader volume = centilots. 1 lot = 10,000,000 centilots. Was using wrong multiplier causing massive sizing errors.', file: 'tekton_executor.py' },
      { id: 'th_7', title: 'HF-07: Fix relativeStopLoss "invalid precision" error', detail: 'Executor was multiplying pips × 10 before sending. Bridge was multiplying again. Fix: executor sends raw pips (float 1dp), bridge converts to int points (pips × 10).', file: 'tekton_executor.py + tekton_bridge.py — SHA 869f71d then 353328f' },
      { id: 'th_8', title: 'HF-08: Fix relativeStopLoss int32 rejection (float not accepted)', detail: 'After HF-07, bridge still sent float. cTrader int32 rejects floats. Fix: int(round(pips × 10)) in bridge.', file: 'tekton_bridge.py — SHA 353328f' },
      { id: 'th_9', title: 'HF-09: Fix P&L showing €0.00 on closed trades', detail: 'closePositionDetail.closePrice field name fallback needed. Added fallback to try price and closedBalance.', file: 'tekton_bridge.py — SHA 353328f' },
      { id: 'th_10', title: 'HF-10: Fix SL/TP showing None on all open positions in UI', detail: 'ReconcileReq does not return SL/TP on this broker. Fix: enrich from position_state{} after ReconcileReq loop in get_executions().', file: 'tekton_bridge.py — SHA 6dfc562' },
      { id: 'th_11', title: 'HF-11: Fix TradingSettings max_lots default (5 → 50)', detail: 'UI default was 5.0 — would reset DB to 5 if page loaded during bridge downtime. Fixed default and fallback to 50 (safe cap, not 5000).', file: 'pages/TradingSettings.jsx' },
      { id: 'th_12', title: 'HF-12: Fix Execution Journal duplicate rows', detail: 'open_trades (ReconcileReq) and closed_trades (DealListReq) were merged with no deduplication. cTrader DealListReq returns opening deals for currently-open positions. Fix: strip open position IDs from closed_trades before merge, deduplicate within closed_trades by position ID.', file: 'tekton_bridge.py — SHA 157cd42' },,
{
    id: 'p13', title: 'Phase 13 — Signals Log Fix (FAILED status bug)', color: 'red', status: 'complete',
    desc: 'BUG DIAGNOSED (20 Mar 2026): All 196 of 200 signals showing FAILED. Root cause: executor queries column signal_type but signals table stores direction in column named direction. Mismatch → executor SQL exception → every signal marked FAILED. Fix: align column name.',
    tasks: [
      { id: 't13_1', title: 'Confirm DB column name: direction vs signal_type', detail: "Run: SELECT column_name FROM information_schema.columns WHERE table_name='signals' ORDER BY ordinal_position; — confirm actual column name.", file: 'PostgreSQL (tekton-trader DB)' },
      { id: 't13_2', title: 'Fix executor SELECT — use correct column name', detail: "tekton_executor.py ~line 251: change 'signal_type' → 'direction' in SELECT. Query: SELECT signal_uuid, symbol, direction, timeframe, sl_pips, tp_pips FROM signals WHERE status='PENDING'", file: 'tekton_executor.py' },
      { id: 't13_3', title: 'Verify bridge /proxy/signals direction field consistent with DB column', detail: 'Bridge already returns "direction" field from /proxy/signals. Confirm bridge INSERT and SELECT both use same column name.', file: 'tekton_bridge.py ~line 695' },
      { id: 't13_4', title: 'Test: insert PENDING signal → confirm COMPLETED not FAILED', detail: 'After fix: insert test signal via ManualSignal page. Watch combined_trades.log. Status should go PENDING → EXECUTING → COMPLETED.', file: 'ManualSignal page + combined_trades.log' },
      { id: 't13_5', title: 'Verify Signals Log UI shows correct statuses', detail: 'Open Signals page. Confirm new signals show PENDING/COMPLETED/EXECUTING, not FAILED.', file: 'Base44 UI → Signals page' },
    ],
  },
  {
  {
    id: 'p13b', title: 'Phase 13.5 — Friday Flush Implementation', color: 'red',
    desc: 'BUG DIAGNOSED (21 Mar 2026): Friday Flush feature is entirely unimplemented. The friday_flush flag is stored in DB and read by executor on every loop, but never acted upon. Two separate failure modes: (1) new trades continue to open after 16:00 UTC Friday — no time gate exists; (2) existing open positions are never closed at 16:00 UTC Friday — no close-all logic exists. All 5 positions currently open over the weekend were opened after the Friday cutoff.',
    tasks: [
      { id: 't13b_1', title: 'Add Friday new-trade gate to executor loop', detail: "Insert after auto_trade check in while True loop: from datetime import datetime, timezone; now = datetime.now(timezone.utc); if settings.get('friday_flush') and now.weekday() == 4 and now.hour >= 16: print('🚫 Friday cutoff — no new trades after 16:00 UTC.'); time.sleep(30); continue", file: 'tekton_executor.py — while True loop, after auto_trade gate' },
      { id: 't13b_2', title: 'Add Friday Flush close-all logic to executor loop', detail: "At exactly 16:00 UTC on Friday (weekday==4, hour==16, minute<1): fetch all open positions from bridge /positions/list, call bridge /trade/close for each position_id. Log each close. Mark signals CLOSED in DB. Use a DB flag or in-memory set to ensure flush only fires once per Friday (not every 30s loop iteration).", file: 'tekton_executor.py — while True loop, new flush block' },
      { id: 't13b_3', title: 'Add flush_fired_date tracking to prevent duplicate flushes', detail: 'Keep a module-level variable: last_flush_date = None. After flush fires, set last_flush_date = date.today(). Only fire if last_flush_date != today. Survives restarts if also written to DB settings.', file: 'tekton_executor.py — module level + DB settings' },
      { id: 't13b_4', title: 'Test Friday Flush in staging', detail: 'Test by temporarily setting flush time to NOW+2min. Confirm: (a) new signals blocked, (b) all open positions closed, (c) flush does not re-fire on next loop iteration. Reset to 16:00 UTC after test.', file: 'tekton_executor.py + cTrader mobile' },
      { id: 't13b_5', title: 'Also gate Saturday/Sunday — no new trades over weekend', detail: 'While implementing Friday gate, also add: if now.weekday() in (5, 6): no new trades on Saturday or Sunday. Markets are closed — executor should sleep over the weekend entirely.', file: 'tekton_executor.py — same gate block' },
    ],
  },
    id: 'p14', title: 'Phase 14 — Command Center Dashboard Fixes', color: 'orange',
    status: 'complete',
    desc: 'COMPLETE 2026-03-24. /account/status now returns balance + margin_used. Dashboard openCount + margin_used sourced from live /positions/list. getAccountStatus backend function updated. Bridge v5.0: pos.price/stopLoss/takeProfit correct doubles. All display values now live-sourced.',
    tasks: [
      { id: 't14_1', title: 'Fix balance display — add balance to /account/status', detail: 'DONE: Bridge /account/status now returns balance field (balance_cents/100). SHA 654bf04c.', file: 'tekton_bridge.py', status: 'complete' },
      { id: 't14_2', title: 'Fix margin_used — sum from /positions/list marginUsed_cents', detail: 'DONE: getAccountStatus.ts fetches /positions/list, sums marginUsed_cents, converts to euros. Fallback to account/status margin_used.', file: 'getAccountStatus.ts', status: 'complete' },
      { id: 't14_3', title: 'Fix open trade count — read from /positions/list', detail: 'DONE: Dashboard openCount now reads status.open_count (populated from /positions/list length). Removed stale signal-counting approach.', file: 'Dashboard.jsx + getAccountStatus.ts', status: 'complete' },
      { id: 't14_4', title: 'Fix position prices — doubles not integers', detail: 'DONE: Bridge v5.0 — pos.price (entry), stopLoss, takeProfit are doubles. No integer division. SHA a48487e.', file: 'tekton_bridge.py', status: 'complete' },
      { id: 't14_5', title: 'Fix balance = equity (unrealised PnL not reflected)', detail: 'PARTIAL: equity field from bridge currently equals balance (TraderUpdatedEvent does not separately track unrealised PnL). Full fix deferred to Phase 11c (event-driven refactor).', file: 'tekton_bridge.py (TraderUpdatedEvent)', status: 'in-progress' },
      { id: 't14_6', title: 'Add daily P&L display — updates as trades close', detail: 'DEFERRED to Phase 16 (Analytics). Needs closed_trades history.', file: 'Dashboard.jsx + getAccountStatus.ts', status: 'todo' },
      { id: 't14_7', title: 'Add Upcoming News strip to Command Center', detail: 'BLOCKED on Phase 8 (economic calendar). Once /calendar/events exists, show next 5 high-impact events.', file: 'Dashboard.jsx + getEconomicCalendar.ts', status: 'todo' },
    ],
  },
  {
    id: 'p15', title: 'Phase 15 — Multi-Timeframe Signals + Metals/Indices', color: 'purple',
    desc: 'DIAGNOSED: All 200 signals are 15min-only. Root cause: all strategy scripts hardcode LTF_TIMEFRAME="15min". Market data exists for 15min + 4H only (no 1H or Daily). Metals (XAUUSD, XAGUSD) and indices (US30, US500, UK100, JP225, AUS200) have 4,999+ 15min candles but are generating zero signals — 4H data availability unknown. Fix: backfill 1H/Daily data, create MTF strategy variants.',
    tasks: [
      { id: 't15_1', title: 'Audit market_data — confirm what timeframes exist per symbol', detail: "SELECT timeframe, COUNT(DISTINCT symbol), MIN(created_at), MAX(created_at) FROM market_data GROUP BY timeframe ORDER BY timeframe; — confirm 15min/4H coverage and whether metals/indices have 4H data.", file: 'PostgreSQL (tekton-trader DB)' },
      { id: 't15_2', title: 'Backfill 4H candles for metals and indices if missing', detail: 'Check if XAUUSD, US30 etc have 4H data. If not, extend tekton_backfill.py to fetch 4H for all 50 symbols. Strategies require both 15min AND 4H to generate signals.', file: 'tekton_backfill.py + VM crontab' },
      { id: 't15_3', title: 'Backfill 1H candles for all 50 active symbols', detail: 'Add 1H timeframe to backfill script. Min 200 candles per symbol. Enables 1H entry strategies with Daily trend filter.', file: 'tekton_backfill.py + VM crontab' },
      { id: 't15_4', title: 'Backfill Daily (1D) candles for all 50 active symbols', detail: 'Add Daily timeframe to backfill. Min 100 candles per symbol. Used as HTF trend filter for 1H entry strategies.', file: 'tekton_backfill.py + VM crontab' },
      { id: 't15_5', title: 'Create 1H EMA Pullback strategy variant', detail: 'Clone strat_ema_pullback_v1.py. Set HTF_TIMEFRAME=Daily, LTF_TIMEFRAME=1H. Signal INSERT with timeframe=1H. Deploy as new systemd service. Targets swing trade setups.', file: 'strat_ema_pullback_1h.py + new systemd service' },
      { id: 't15_6', title: 'Diagnose why metals/indices not generating signals', detail: 'Metals (XAUUSD etc) and indices (US30 etc) have 15min data confirmed. Check: (a) does get_active_symbols() SQL query return them? (b) do they have 4H data? (c) are they passing trend/entry filters? Add debug logging.', file: 'strat_ema_pullback_v1.py + strat_ict_fvg_v1_rewrite.py + combined_trades.log' },
      { id: 't15_7', title: 'Add USTEC, DE40, STOXX50, F40 to active symbol lists', detail: '4 additional instruments available from broker (confirmed via /symbols/list). Backfill market data and add to strategy symbol lists once data available.', file: 'strat_*.py + tekton_backfill.py' },
    ],
  },
  {
    id: 'p16', title: 'Phase 16 — Analytics Page + AI Recommendations', color: 'cyan',
    desc: 'Build the full Analytics page with AI-powered trade analysis, strategy attribution, and actionable recommendations. Lester analyses closed trade history and recommends settings/strategy changes. AI recommendations become meaningful after 100+ closed trades — gate behind minimum count.',
    tasks: [
      { id: 't16_1', title: 'Build Analytics page skeleton — tabbed layout', detail: 'Analytics.jsx with tabs: Performance | By Symbol | By Session | AI Recommendations. Connect to getAnalytics backend function.', file: 'Base44 UI → Analytics.jsx' },
      { id: 't16_2', title: 'Strategy performance table', detail: 'Table: strategy | signals | executed | win_rate | avg_r | profit_factor. Source: SQL GROUP BY strategy on signals + closed_trades. Sortable columns. Highlight underperformers in red.', file: 'Analytics.jsx + getAnalytics.ts' },
      { id: 't16_3', title: 'Symbol and session P&L breakdown', detail: 'Bar charts: P&L by symbol (top 15), P&L by session (London/NY/Asian/Pacific), P&L by day of week. Show best/worst performers visually.', file: 'Analytics.jsx + getAnalytics.ts' },
      { id: 't16_4', title: 'Confidence score vs actual R scatter', detail: 'X=confidence_score (0-100), Y=outcome_r. Colour by strategy. Does high confidence predict better outcomes? Include trend line.', file: 'Analytics.jsx + getAnalytics.ts' },
      { id: 't16_5', title: 'AI Recommendations engine', detail: 'Call AI with: strategy stats, top/worst symbols, confidence correlation, recent drawdown events. Generate 5 plain-English recommendations with priority (CRITICAL/HIGH/MEDIUM). Store in AnalyticsSnapshot entity. Refresh on demand.', file: 'Analytics.jsx + Base44 AI backend function + AnalyticsSnapshot entity' },
      { id: 't16_6', title: 'Gate AI analysis behind 100 closed trade minimum', detail: 'DECISION: AI recommendations only meaningful with sufficient data. Show progress bar "X/100 trades needed for AI analysis" until threshold reached. After 100: unlock full analysis.', file: 'Analytics.jsx' },
      { id: 't16_7', title: 'Surface top 3 AI recommendations on Command Center', detail: 'Show latest Lester recommendations as a strip on Dashboard. Clickable through to full Analytics page.', file: 'Dashboard.jsx' },
    ],
  },,
];
const STATUS_CONFIG = {
  todo:        { label: 'To Do',       icon: Circle,        color: 'text-slate-500',   bg: 'bg-slate-500/10 border-slate-500/20' },
  in_progress: { label: 'In Progress', icon: Clock,         color: 'text-yellow-400',  bg: 'bg-yellow-500/10 border-yellow-500/20' },
  done:        { label: 'Done',        icon: CheckCircle,   color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' },
  blocked:     { label: 'Blocked',     icon: AlertTriangle, color: 'text-red-400',     bg: 'bg-red-500/10 border-red-500/20' },
};

const PHASE_COLORS = {
  blue:   'text-blue-400 border-blue-500/20 bg-blue-500/10',
  purple: 'text-purple-400 border-purple-500/20 bg-purple-500/10',
  cyan:   'text-cyan-400 border-cyan-500/20 bg-cyan-500/10',
  yellow: 'text-yellow-400 border-yellow-500/20 bg-yellow-500/10',
  green:  'text-emerald-400 border-emerald-500/20 bg-emerald-500/10',
  red:    'text-red-400 border-red-500/20 bg-red-500/10',
  orange: 'text-orange-400 border-orange-500/20 bg-orange-500/10',
};

export default function ImplementationPlan() {
  const [taskStatus, setTaskStatus] = useState({});
  const [openPhases, setOpenPhases] = useState(() => Object.fromEntries(PHASES.map(p => [p.id, true])));
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [savedMsg, setSavedMsg] = useState(false);

  useEffect(() => { loadStatus(); }, []);

  const loadStatus = async () => {
    setLoading(true);
    const records = await base44.entities.ImplementationTask.list();
    const map = {};
    records.forEach(r => { map[r.task_id] = r.status; });
    setTaskStatus(map);
    setLoading(false);
  };

  const setStatus = (taskId, status) => setTaskStatus(prev => ({ ...prev, [taskId]: status }));

  const saveAll = async () => {
    setSaving(true);
    const existing = await base44.entities.ImplementationTask.list();
    const existingMap = Object.fromEntries(existing.map(r => [r.task_id, r.id]));
    for (const [taskId, status] of Object.entries(taskStatus)) {
      if (existingMap[taskId]) {
        await base44.entities.ImplementationTask.update(existingMap[taskId], { task_id: taskId, status });
      } else {
        await base44.entities.ImplementationTask.create({ task_id: taskId, status });
      }
    }
    setSaving(false); setSavedMsg(true);
    setTimeout(() => setSavedMsg(false), 2500);
  };

  const totalTasks = PHASES.reduce((acc, p) => acc + p.tasks.length, 0);
  const doneTasks = Object.values(taskStatus).filter(s => s === 'done').length;
  const pct = Math.round((doneTasks / totalTasks) * 100);
  const togglePhase = (id) => setOpenPhases(prev => ({ ...prev, [id]: !prev[id] }));

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-5xl mx-auto">
      <div className="flex items-start gap-4 mb-6">
        <div className="p-2 rounded-xl bg-blue-500/10 border border-blue-500/20 shrink-0"><ClipboardList className="w-6 h-6 text-blue-400" /></div>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Implementation Plan</h1>
          <p className="text-slate-500 text-sm mt-0.5">v4.8.0 — Phases 1–12 + Hotfixes</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={loadStatus} className="p-2 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 transition-colors"><RefreshCw className="w-4 h-4" /></button>
          <button onClick={saveAll} disabled={saving} className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold transition-colors disabled:opacity-50">
            <Save className="w-4 h-4" />{saving ? 'Saving…' : savedMsg ? '✓ Saved' : 'Save Progress'}
          </button>
        </div>
      </div>
      <div className="card-dark p-4 mb-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-semibold text-slate-300">Overall Progress</span>
          <span className="text-sm font-bold text-blue-400">{doneTasks} / {totalTasks} tasks ({pct}%)</span>
        </div>
        <div className="h-2.5 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-gradient-to-r from-blue-600 to-emerald-500 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
        </div>
        <div className="flex gap-4 mt-3 flex-wrap">
          {Object.entries(STATUS_CONFIG).map(([key, cfg]) => {
            const count = Object.values(taskStatus).filter(s => s === key).length;
            const Icon = cfg.icon;
            return (<div key={key} className="flex items-center gap-1.5 text-xs"><Icon className={`w-3.5 h-3.5 ${cfg.color}`} /><span className="text-slate-400">{cfg.label}:</span><span className="font-bold text-slate-200">{count}</span></div>);
          })}
        </div>
      </div>
      {loading && <div className="text-center text-slate-500 text-sm py-8">Loading saved progress…</div>}
      {!loading && PHASES.map(phase => {
        const phaseDone = phase.tasks.filter(t => taskStatus[t.id] === 'done').length;
        const isOpen = openPhases[phase.id];
        return (
          <div key={phase.id} className="card-dark mb-4">
            <button onClick={() => togglePhase(phase.id)} className="w-full flex items-center justify-between px-5 py-4 text-left">
              <div className="flex items-center gap-3">
                <span className={`p-1.5 rounded-lg border text-xs font-bold ${PHASE_COLORS[phase.color]}`}>{phaseDone}/{phase.tasks.length}</span>
                <span className="font-semibold text-slate-200 text-sm">{phase.title}</span>
              </div>
              {isOpen ? <ChevronDown className="w-4 h-4 text-slate-600" /> : <ChevronRight className="w-4 h-4 text-slate-600" />}
            </button>
            {isOpen && (
              <div className="px-5 pb-5 border-t border-slate-800/60 pt-4 space-y-3">
                <p className="text-xs text-slate-500 mb-4">{phase.desc}</p>
                {phase.tasks.map(task => {
                  const status = taskStatus[task.id] || 'todo';
                  const cfg = STATUS_CONFIG[status];
                  const StatusIcon = cfg.icon;
                  return (
                    <div key={task.id} className="bg-slate-900/60 rounded-lg p-3 border border-slate-800 hover:border-slate-700 transition-colors">
                      <div className="flex items-start gap-3">
                        <div className="flex flex-col gap-1 shrink-0 mt-0.5">
                          {Object.entries(STATUS_CONFIG).map(([key, c]) => {
                            const Ic = c.icon;
                            return (<button key={key} onClick={() => setStatus(task.id, key)} title={c.label} className={`w-5 h-5 rounded flex items-center justify-center border transition-all ${status === key ? c.bg : 'border-transparent opacity-25 hover:opacity-60'}`}><Ic className={`w-3 h-3 ${status === key ? c.color : 'text-slate-500'}`} /></button>);
                          })}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className={`text-xs font-semibold border rounded px-1.5 py-0.5 ${cfg.bg} ${cfg.color}`}>{cfg.label}</span>
                            <span className={`text-sm font-medium ${status === 'done' ? 'line-through text-slate-600' : 'text-slate-200'}`}>{task.title}</span>
                          </div>
                          <p className="text-xs text-slate-500 mb-1.5">{task.detail}</p>
                          <span className="text-[10px] font-mono text-slate-600 bg-slate-800/60 px-1.5 py-0.5 rounded">{task.file}</span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
      <div className="text-center text-xs text-slate-700 mt-8 pb-4 font-mono">Implementation Plan v4.8.0 — Updated 25 Mar 2026 · Click status icons to update · Press Save Progress to persist</div>
    </div>
  );
}
