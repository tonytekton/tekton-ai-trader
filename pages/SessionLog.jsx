import { useState } from "react";

const SESSION_DATE = "2026-03-19";
const SESSION_TITLE = "Tekton Session — March 19, 2026";

const TRANSCRIPT = [
  {
    role: "SYSTEM",
    content: "Session started. Context loaded from memory.md and SYSTEM_CONTEXT_v4.8.md."
  },
  {
    role: "USER",
    content: "[EARLIER IN SESSION — context was compressed by platform]\n\nTony provided terminal output showing volume calculation issues. Analysis revealed pip size calculations were wrong by factor of 10 due to hardcoded PIP_SIZE_MAP. Decision made to remove PIP_SIZE_MAP entirely and rely on live pipPosition data from bridge /contract/specs."
  },
  {
    role: "LESTER",
    content: "Comprehensive rewrite of tekton_executor.py completed:\n- Removed hardcoded PIP_SIZE_MAP\n- Added get_contract_specs() — fetches live specs from bridge per symbol, cached per session\n- Standardised pip_size = 10^(-(pipPosition-1)) across all 50 instruments\n- Dynamic lot size calc: volume_lots = risk_cash / (sl_pips × pip_value_per_lot)\n- Pushed to GitHub feature/bridge-v4.8-event-driven"
  },
  {
    role: "USER",
    content: "of course do the documentation catch up. without it you cant maintain context. it's obvious you were struggling already."
  },
  {
    role: "LESTER",
    content: "You're right. Reading all current docs and the full feature branch code before writing anything.\n\n[Read tekton_bridge.py — 1775 lines on feature branch]\n[Read BRIDGE_REFACTOR_DESIGN.md]\n[Checked git log — commits: 2d1f6b4, bed0ea1, e56acf3]\n[Checked executor on feature branch — POINTS_PER_PIP=10 still present, relativeStopLoss fix NOT merged from main]\n\nConfirmed state:\n- Phase 11a ✅ e56acf3: raw_to_decimal, decimal_to_raw, _position_to_dict, position_state{}\n- Phase 11b ✅ bed0ea1 + 2d1f6b4: ExecutionEvent handler, TraderUpdatedEvent, ReconcileReq seed\n- Phase 11c ❌ TODO NEXT: refactor endpoints to serve from position_state{}\n- Phase 11d ❌ TODO: DealListReq pagination, smoke tests, merge to main\n- CRITICAL GAP: relativeStopLoss fix (SHA 869f71d on main) NOT merged to feature branch\n\nWrote full SYSTEM_CONTEXT_v4.8.md — complete rewrite with all agreed decisions, known gaps, change log.\nUpdated memory.md — all 20 entries accurate."
  },
  {
    role: "USER",
    content: "why is there a limit to our conversation? it means context gets lost mid-build. our conversation only goes back about 3 hours."
  },
  {
    role: "LESTER",
    content: "Base44 compresses older messages to save memory/tokens. The conversation window is finite — older messages get summarised and the verbatim text is lost.\n\nDefences:\n1. Keep SYSTEM_CONTEXT_v4.8.md current — that's the technical truth that survives compression\n2. Keep memory.md updated — decisions, project state, key facts\n3. Keep sessions shorter and more focused — end when a chunk of work is done\n4. Document BEFORE we code, not after\n\nThe compression is why I was struggling earlier — key context about the volume bug investigation had already been compressed before I could reference it."
  },
  {
    role: "USER",
    content: "can't conversations be archived to GitHub? it's only really a text file."
  },
  {
    role: "LESTER",
    content: "Yes — good idea. Build a skill that exports session logs as markdown and pushes to a /sessions folder in a GitHub repo.\n\nChecked available secrets — GITHUB_TOKEN confirmed present.\n\nBuilt archive_session.py skill. The Base44 session API isn't directly accessible via HTTP — sessions are read through my built-in read_session_log tool. Rewrote the skill accordingly: I read session → format as markdown → push via GitHub API.\n\nChecked if tonytekton/tekton-sessions repo exists — 404, doesn't exist yet.\nAttempted to create repo via API — failed (fine-grained token scoped to tekton-ai-trader only, can't create repos).\n\nExplained two options:\n- Option A: Put sessions in tekton-ai-trader repo under /sessions\n- Option B: Create new private tekton-sessions repo (cleaner separation)\n\nRecommended Option B. Token access works for private repos as long as it has repo scope — fine-grained token just needs to be updated to include the new repo."
  },
  {
    role: "USER",
    content: "tekton-sessions repo created"
  },
  {
    role: "LESTER",
    content: "Verified token access: HTTP 200 ✅\n\nArchived all 5 prior sessions:\n- 2026-03-12_69b38bc28b134dbaf4964a25.md\n- 2026-03-13_69b78e0a51ac0d30bcc14eb3.md\n- 2026-03-16_69b8c44f135ff9c9651cc831.md\n- 2026-03-17_69b9fd7afc14ed99a0a73894.md\n- 2026-03-18_69bad1870d99bf4254de2ec0.md\n\nAll pushed to tonytekton/tekton-sessions (private)."
  },
  {
    role: "USER",
    content: "can you check i've set it up the right way. it's set as private"
  },
  {
    role: "LESTER",
    content: "Verified via GitHub API:\n- Name: tekton-sessions ✅\n- Private: True ✅\n- Owner: tonytekton ✅\n- Default branch: main ✅\n- 6 session files in /sessions/ ✅\n\nNote: older session files only 480-600 bytes — summary only, not full transcripts. The Base44 read_session_log tool truncates at ~50KB, so 190+ message sessions don't fit in one read."
  },
  {
    role: "USER",
    content: "yes do that but today's should be much larger than 1360 bytes, we've been talking all day"
  },
  {
    role: "LESTER",
    content: "Re-read all 5 sessions and re-pushed with fuller content. Confirmed all 7 files now in repo:\n- 5 older sessions: 1.7–2.8 KB each (faithful summaries with key terminal outputs)\n- 2026-03-19_current.md: 1.3 KB (old placeholder)\n- 2026-03-19_main.md: 5.2 KB (today's session reconstruction)\n\nHonest note: read_session_log truncates at ~50KB. Older sessions had 190-200 messages each so what was archived is a clean accurate summary, not verbatim transcripts."
  },
  {
    role: "USER",
    content: "the whole point is to have the full conversations from each session. it may mean that we need to push our tekton sessions every couple of hours"
  },
  {
    role: "LESTER",
    content: "Agreed. The value is the verbatim conversation — every message, every terminal output, every code block.\n\nProblem: read_session_log truncates at ~50KB. Sessions with 190+ messages blow past that.\n\nFix: push incrementally during the session every 2 hours — each push is small enough to capture in full before truncation. Append-only so nothing gets overwritten.\n\nOnly gap: current session ID isn't available while session is still open — list_sessions doesn't show the active session until it closes."
  },
  {
    role: "USER",
    content: "If I say checkpoint now does that mean you can push our current session?"
  },
  {
    role: "LESTER",
    content: "No — current session isn't in list_sessions while still open. Can't read it back via read_session_log.\n\nWhat I CAN do on a checkpoint: write everything I remember from the conversation right now — from memory, while it's fresh. Not verbatim copy-paste but faithful reconstruction with all technical content: what you said, what I said, every terminal output, every decision.\n\nWorkflow:\n- You say 'checkpoint' every couple of hours\n- I write detailed reconstruction and push to GitHub\n- When session closes it becomes readable — I can do final pass comparing reconstruction against actual log\n\nOffered to do full checkpoint push for today's entire session."
  },
  {
    role: "USER",
    content: "how does a session end"
  },
  {
    role: "LESTER",
    content: "Not 100% certain of exact mechanics. Likely ends when:\n1. You close the chat tab/browser\n2. Period of inactivity (timeout)\n3. You start a new chat\n\nConfirmed: today's session still NOT showing in list_sessions — still open and unreadable.\n\nMost pragmatic solution: when done for the day, close chat, wait a few minutes, open new chat and say 'archive yesterday's session'. Then it's in list_sessions and readable.\n\n50KB truncation still a problem for very long sessions."
  },
  {
    role: "USER",
    content: "right now i want our conversation from today's session archived asap. it's too important. not happy with the proposed way forward. what about building a page with our entire conversation?"
  },
  {
    role: "LESTER",
    content: "Building a SessionLog page now that renders the full today's conversation. Will also push to GitHub as markdown. The page lives in the Base44 app and is always accessible."
  }
];

const roleColors = {
  USER: "bg-blue-50 border-blue-200",
  LESTER: "bg-green-50 border-green-200",
  SYSTEM: "bg-gray-50 border-gray-200"
};

const roleBadge = {
  USER: "bg-blue-600 text-white",
  LESTER: "bg-green-700 text-white",
  SYSTEM: "bg-gray-500 text-white"
};

export default function SessionLog() {
  const [filter, setFilter] = useState("ALL");
  const [search, setSearch] = useState("");
  const [copied, setCopied] = useState(false);

  const filtered = TRANSCRIPT.filter(msg => {
    const matchRole = filter === "ALL" || msg.role === filter;
    const matchSearch = search === "" || msg.content.toLowerCase().includes(search.toLowerCase());
    return matchRole && matchSearch;
  });

  const fullText = TRANSCRIPT.map(m => `### ${m.role}\n\n${m.content}\n\n---`).join("\n\n");

  const copyAll = () => {
    navigator.clipboard.writeText(`# ${SESSION_TITLE}\n\n${fullText}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="min-h-screen bg-gray-100 p-4">
      <div className="max-w-4xl mx-auto">

        {/* Header */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 mb-4">
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">🎩 {SESSION_TITLE}</h1>
              <p className="text-sm text-gray-500 mt-1">
                {TRANSCRIPT.length} messages · Tekton AI Trader development session
              </p>
            </div>
            <button
              onClick={copyAll}
              className="px-4 py-2 bg-gray-800 text-white text-sm rounded-lg hover:bg-gray-700 transition-colors"
            >
              {copied ? "✅ Copied!" : "📋 Copy All"}
            </button>
          </div>

          {/* Stats */}
          <div className="flex gap-4 mt-4">
            {["USER", "LESTER", "SYSTEM"].map(role => {
              const count = TRANSCRIPT.filter(m => m.role === role).length;
              return (
                <div key={role} className="flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${roleBadge[role]}`}>{role}</span>
                  <span className="text-sm text-gray-600">{count} messages</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Controls */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 mb-4 flex gap-3">
          <input
            type="text"
            placeholder="Search transcript..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
          />
          <div className="flex gap-2">
            {["ALL", "USER", "LESTER"].map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-2 text-sm rounded-lg font-medium transition-colors ${
                  filter === f ? "bg-gray-800 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        {/* Note banner */}
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-4 text-sm text-amber-800">
          <strong>⚠️ Note:</strong> This page was built during the session as a workaround for the Base44 session archiving limitation.
          The transcript above captures the key exchanges from today's session reconstructed from memory.
          Earlier parts of the session (volume calc rewrite, executor refactor) were already compressed by the platform before this page was built.
          A verbatim export will be pushed to GitHub once the session closes and becomes readable via <code>read_session_log</code>.
        </div>

        {/* Transcript */}
        <div className="space-y-3">
          {filtered.map((msg, i) => (
            <div key={i} className={`rounded-xl border p-4 ${roleColors[msg.role]}`}>
              <div className="flex items-center gap-2 mb-2">
                <span className={`text-xs px-2 py-0.5 rounded-full font-bold ${roleBadge[msg.role]}`}>
                  {msg.role}
                </span>
                <span className="text-xs text-gray-400">Message {i + 1}</span>
              </div>
              <pre className="whitespace-pre-wrap text-sm text-gray-800 font-sans leading-relaxed">
                {msg.content}
              </pre>
            </div>
          ))}
        </div>

        {filtered.length === 0 && (
          <div className="text-center py-12 text-gray-400">No messages match your filter.</div>
        )}

        <div className="mt-6 text-center text-xs text-gray-400 pb-8">
          Session archived · {SESSION_DATE} · Tekton AI Trader v4.8
        </div>
      </div>
    </div>
  );
}
