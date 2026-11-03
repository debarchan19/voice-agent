import { memo } from "react";

import type { CallController } from "../lib/call";
import { useStore } from "../lib/store";
import type { CallSummary } from "../lib/types";

const SENTIMENT: Record<CallSummary["sentiment"], [string, string, string]> = {
  positive: ["Positive", "😊", "bg-emerald-500/15 text-emerald-200 ring-emerald-400/40"],
  neutral: ["Neutral", "😐", "bg-slate-500/15 text-slate-200 ring-slate-400/40"],
  frustrated: ["Frustrated", "😣", "bg-amber-500/15 text-amber-200 ring-amber-400/40"],
  angry: ["Angry", "😠", "bg-rose-500/15 text-rose-200 ring-rose-400/40"],
};

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-400">{label}</dt>
      <dd className="text-right text-slate-100">{children}</dd>
    </div>
  );
}

/** The after-call note: written while End call waits, then kept on screen. */
export const SummaryCard = memo(function SummaryCard({ call }: { call: CallController }) {
  const summary = useStore(call.summary);
  if (summary.phase === "idle") return null;

  if (summary.phase !== "done") {
    return (
      <section className="summary-card rise">
        <h2 className="mb-1 text-[11px] font-medium uppercase tracking-[0.18em] text-teal-200">After-call summary</h2>
        <p className="text-sm text-slate-300">
          {summary.phase === "writing" ? (
            <span className="inline-flex items-center gap-2">
              <span className="h-2 w-2 animate-pulse rounded-full bg-teal-300" />
              Writing the summary from the transcript…
            </span>
          ) : (
            "The summary couldn't be fetched for this call."
          )}
        </p>
      </section>
    );
  }

  const n = summary.note;
  const [label, emoji, style] = SENTIMENT[n.sentiment] ?? SENTIMENT.neutral;
  return (
    <section className="summary-card rise">
      <header className="mb-2 flex items-start justify-between gap-2">
        <div>
          <h2 className="text-[11px] font-medium uppercase tracking-[0.18em] text-teal-200">After-call summary</h2>
          <p className="text-sm font-semibold text-white">{n.outcome}</p>
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${style}`}>
          <span aria-hidden="true">{emoji}</span>
          {label}
        </span>
      </header>
      <p className="text-[13px] leading-snug text-slate-200">{n.summary}</p>
      <p className="mt-1 text-[11px] italic text-slate-400">Sentiment: {n.sentiment_reason}</p>
      {n.next_steps.length > 0 && (
        <>
          <h3 className="mb-1 mt-2.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">Next steps</h3>
          <ol className="flex flex-col gap-1">
            {n.next_steps.map((step, i) => (
              <li key={i} className="flex gap-2 text-[13px] leading-snug text-slate-200">
                <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-teal-400/20 text-[10px] font-bold text-teal-200">
                  {i + 1}
                </span>
                {step}
              </li>
            ))}
          </ol>
        </>
      )}
      <dl className="mt-2.5 flex flex-col gap-0.5 border-t border-white/10 pt-2 text-xs">
        <Fact label="Ticket">{n.ticket_id ?? "—"}</Fact>
        <Fact label="Confirmation email">{n.email_sent ? "sent" : "not sent"}</Fact>
        <Fact label="Failed verifications">{n.failed_verifications}</Fact>
        <Fact label="Blocked by gate">{n.gate_blocks}</Fact>
      </dl>
      <p className="mt-2 text-[10px] text-slate-500">Facts from code · summary, sentiment and next steps written by Claude</p>
    </section>
  );
});
