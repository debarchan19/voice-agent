import { memo, useEffect, useRef } from "react";

import type { CallController } from "../lib/call";
import { useStore } from "../lib/store";
import type { LogLine } from "../lib/types";
import { useFlash } from "../lib/useFlash";
import { SummaryCard } from "./SummaryCard";

const STATUS: Record<string, [string, string]> = {
  processing: ["Processing", "bg-slate-500/15 text-slate-300 ring-slate-400/30"],
  shipped: ["Shipped", "bg-blue-500/15 text-blue-300 ring-blue-400/30"],
  out_for_delivery: ["Out for delivery", "bg-teal-500/15 text-teal-300 ring-teal-400/30"],
  delivered: ["Delivered", "bg-emerald-500/15 text-emerald-300 ring-emerald-400/30"],
  delayed: ["Delayed", "bg-amber-500/15 text-amber-300 ring-amber-400/30"],
  cancelled: ["Cancelled", "bg-red-500/15 text-red-300 ring-red-400/30"],
  returned: ["Returned", "bg-violet-500/15 text-violet-300 ring-violet-400/30"],
};

/** The tools wismo/tools.py's require_verified() guards. */
const GATED_TOOLS = ["get_tracking_events", "transfer_to_resolution", "reschedule_delivery", "request_refund", "create_ticket"];

const TONE: Record<NonNullable<LogLine["tone"]>, string> = {
  good: "text-emerald-300",
  warn: "text-amber-300",
  blocked: "font-semibold text-rose-300",
};

function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function Heading({ children }: { children: string }) {
  return <h2 className="mb-1.5 px-1 text-[11px] font-medium uppercase tracking-[0.18em] text-slate-400">{children}</h2>;
}

function Field({ label, children, value }: { label: string; children: React.ReactNode; value: unknown }) {
  const ref = useFlash<HTMLDivElement>(value);
  return (
    <div ref={ref} className="row flex items-center justify-between gap-3 rounded-lg px-2 py-1">
      <dt className="text-slate-400">{label}</dt>
      <dd className="flex min-w-0 items-center gap-2 text-right">{children}</dd>
    </div>
  );
}

function NoteRow({ name, value }: { name: string; value: string }) {
  const ref = useFlash<HTMLDivElement>(value);
  return (
    <div ref={ref} className="row flex justify-between gap-3 rounded-md px-2 py-0.5">
      <dt className="shrink-0 text-slate-400">{name}</dt>
      <dd className="min-w-0 break-words text-right text-slate-200" title={value}>
        {value}
      </dd>
    </div>
  );
}

function LockIcon({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d={open ? "M8 11V7a4 4 0 0 1 7.5-2" : "M8 11V7a4 4 0 0 1 8 0v4"} />
    </svg>
  );
}

/** Verification is enforced in code: this shows the gate's state, failed attempts and refused calls. */
interface GateProps {
  verified: boolean;
  failed: number;
  max: number;
  blocked: number;
  blockedTool: string | null;
}

function Gate({ verified, failed, max, blocked, blockedTool }: GateProps) {
  const ref = useFlash<HTMLDivElement>(blocked + failed);
  return (
    <div ref={ref} className="gate card p-2.5" data-open={verified} data-blocked={blocked > 0}>
      <div className="flex items-center justify-between gap-2">
        <span className="gate-badge inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold uppercase tracking-wider">
          <LockIcon open={verified} />
          {verified ? "Unlocked" : "Locked"}
        </span>
        <span className="flex items-center gap-1.5 text-[11px] text-slate-400" title={`${failed} wrong attempt(s), ${max} allowed`}>
          {failed > 0 && <span className="text-rose-300">{failed} wrong</span>}
          {Array.from({ length: max }, (_, i) => (
            <span
              key={i}
              className={`h-2.5 w-2.5 rounded-full ${i < failed ? "bg-rose-400" : verified && i === failed ? "bg-emerald-400" : "bg-white/15"}`}
            />
          ))}
        </span>
      </div>
      <p className="mt-1.5 text-[11px] leading-snug text-slate-400">
        {verified
          ? "Caller matched the phone on the order. Order details and actions are open for this order only."
          : `${GATED_TOOLS.length} tools refuse to run until the last four digits match. A prompt can't talk past it.`}
      </p>
      {blocked > 0 && (
        <p className="mt-1 text-[11px] font-semibold text-rose-300">
          ⛔ {blocked} call{blocked === 1 ? "" : "s"} blocked{blockedTool ? `, last: ${blockedTool}` : ""}
        </p>
      )}
    </div>
  );
}

function Activity({ log }: { log: LogLine[] }) {
  const ref = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [log]);
  return (
    <ol ref={ref} className="card flex max-h-44 min-h-[5.5rem] flex-col gap-1 overflow-y-auto p-2.5 font-mono text-[11px]">
      {log.length === 0 && <li className="m-auto text-slate-500">Tool calls will appear here.</li>}
      {log.map((line) => (
        <li key={line.id} className="rise flex gap-2 text-slate-300">
          <span className="shrink-0 text-slate-500">{line.time}</span>
          <span className={line.tone ? TONE[line.tone] : undefined}>{line.text}</span>
        </li>
      ))}
    </ol>
  );
}

/** The transparency panel. It subscribes only to panel data, so it never re-renders the avatar. */
export const SidePanel = memo(function SidePanel({ call }: { call: CallController }) {
  const { state, log, blocked, blockedTool, failedVerifications } = useStore(call.panel);
  const summary = useStore(call.summary);
  const [statusLabel, statusStyle] = (state?.status && STATUS[state.status]) || ["—", ""];

  return (
    <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto pr-1">
      <SummaryCard call={call} />

      <section>
        <Heading>Call details</Heading>
        <dl className="card flex flex-col p-1.5 text-sm">
          <Field label="Agent" value={state?.agent}>
            <span className="font-semibold text-slate-100">{state?.agent ?? "—"}</span>
          </Field>
          <Field label="Customer" value={state?.customer}>
            <span className={state?.verified ? "truncate text-slate-100" : "text-slate-400"}>
              {state?.verified ? state.customer : "Not verified"}
            </span>
          </Field>
          <Field label="Order" value={state?.order_id}>
            <span className="font-mono text-slate-100">{state?.order_id || "—"}</span>
          </Field>
          <Field label="Status" value={state?.status}>
            <span className={statusStyle ? `inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${statusStyle}` : "text-slate-400"}>
              {statusLabel}
            </span>
          </Field>
          <Field label="Delivery" value={state?.promised_date}>
            <span className="text-slate-100">{state?.promised_date ? formatDate(state.promised_date) : "—"}</span>
          </Field>
        </dl>
      </section>

      <section>
        <Heading>Verification gate</Heading>
        <Gate
          verified={!!state?.verified}
          failed={failedVerifications}
          max={state?.max_verify_attempts ?? 3}
          blocked={blocked}
          blockedTool={blockedTool}
        />
      </section>

      <section>
        <Heading>Activity</Heading>
        <Activity log={log} />
      </section>

      {summary.phase !== "done" && (
        <section>
          <Heading>Graph state</Heading>
          <dl className="card flex flex-col gap-0.5 p-2 font-mono text-[11px]">
            {state ? (
              Object.entries(state.notepad).map(([k, v]) => <NoteRow key={k} name={k} value={String(v)} />)
            ) : (
              <p className="px-2 py-1 text-slate-500">Shared call data appears once the call starts.</p>
            )}
          </dl>
        </section>
      )}

      <p className="mt-auto px-1 text-[11px] text-slate-500">Press D for the performance overlay.</p>
    </aside>
  );
});
