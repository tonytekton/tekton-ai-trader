/**
 * getUsageStats — Tekton Trading Hub
 * Phase 18 — AI Credits Monitor
 *
 * Returns Base44 platform usage stats:
 *  - AI integration credits (75,000/month)
 *  - Message credits (monthly plan)
 *  - Daily budget calculations
 *
 * The Base44 SDK exposes usage via base44.usage.getStats()
 * Daily budget: 900,000 ÷ 260 working days = 3,461 credits/day
 */

import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';

const AI_MONTHLY_BUDGET  = 75000;
const AI_YEARLY_BUDGET   = 900000;
const AI_DAILY_BUDGET    = Math.round(AI_YEARLY_BUDGET / 260); // 3461
const MSG_MONTHLY_BUDGET = 1925;

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: 'Unauthorized' }, { status: 401 });

    // Attempt to fetch usage from Base44 SDK
    let aiUsed: number | null = null;
    let msgUsed: number | null = null;

    try {
      // Base44 SDK usage endpoint
      const usage = await (base44 as any).usage?.getStats?.();
      if (usage) {
        aiUsed  = usage.integration_credits_used  ?? usage.ai_credits_used  ?? null;
        msgUsed = usage.message_credits_used ?? usage.msg_credits_used ?? null;
      }
    } catch {
      // SDK may not expose usage — fall back to null (widget shows placeholders)
    }

    const now = new Date();
    const dayOfMonth = now.getDate();
    const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    const daysRemaining = daysInMonth - dayOfMonth;

    const aiDailyBurn    = aiUsed != null && dayOfMonth > 0 ? Math.round(aiUsed / dayOfMonth) : null;
    const aiProjectedEOM = aiDailyBurn != null ? Math.round(aiUsed! + aiDailyBurn * daysRemaining) : null;

    return Response.json({
      ok: true,
      ai_credits_used:   aiUsed,
      ai_credits_total:  AI_MONTHLY_BUDGET,
      ai_credits_remaining: aiUsed != null ? AI_MONTHLY_BUDGET - aiUsed : null,
      ai_daily_budget:   AI_DAILY_BUDGET,
      ai_daily_burn:     aiDailyBurn,
      ai_projected_eom:  aiProjectedEOM,
      msg_credits_used:  msgUsed,
      msg_credits_total: MSG_MONTHLY_BUDGET,
      day_of_month:      dayOfMonth,
      days_remaining:    daysRemaining,
    });

  } catch (error) {
    return Response.json({ error: (error as Error).message }, { status: 500 });
  }
});
