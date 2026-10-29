import { memo, useEffect, useRef } from "react";

import type { CallController } from "../lib/call";
import { useStore } from "../lib/store";
import type { AgentName, LogLine } from "../lib/types";
import { useFlash } from "../lib/useFlash";

const AGENTS: { name: AgentName; role: string }[] = [
  { name: "Greeter", role: "Takes your order or phone number" },
  { name: "Order Status", role: "Verifies you, explains the status" },
  { name: "Resolution", role: "Reschedules, refunds, opens tickets" },
];

const STATUS: Record<string, [string, string]> = {
  processing: ["Processing", "bg-slate-500/15 text-slate-300 ring-slate-400/30"],
  shipped: ["Shipped", "bg-blue-500/15 text-blue-300 ring-blue-400/30"],
  out_for_delivery: ["Out for delivery", "bg-teal-500/15 text-teal-300 ring-teal-400/30"],
  delivered: ["Delivered", "bg-emerald-500/15 text-emerald-300 ring-emerald-400/30"],
  delayed: ["Delayed", "bg-amber-500/15 text-amber-300 ring-amber-400/30"],
  cancelled: ["Cancelled", "bg-red-500/15 text-red-300 ring-red-400/30"],
  returned: ["Returned", "bg-violet-500/15 text-violet-300 ring-violet-400/30"],
};

function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function Heading({ children }: { children: string }) {
  return <h2 className="mb-2 px-1 text-[11px] font-medium uppercase tracking-[0.18em] text-slate-400">{children}</h2>;
}

function AgentStep({ index, name, role, active, done }: { index: number; name: string; role: string; active: boolean; done: boolean }) {
  const ref = useFlash<HTMLLIElement>(active, active); // pulse on hand-off to this agent
  return (
    <li ref={ref} className="step flex items-center gap-3 rounded-xl px-3 py-2" data-active={active} data-done={done}>
      <span className="num flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold">{index + 1}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold">{name}</span>
        <span className="role block truncate text-xs text-slate-400">{role}</span>
      </span>
      {active && (
        <span className="inline-flex items-center gap-1 rounded-full bg-white/20 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" />
          Live
        </span>
      )}
    </li>
  );
}

function Field({ label, children, value }: { label: string; children: React.ReactNode; value: unknown }) {
  const ref = useFlash<HTMLDivElement>(value);
  return (
    <div ref={ref} className="row flex items-center justify-between gap-3 rounded-lg px-2 py-1.5">
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

function Activity({ log }: { log: LogLine[] }) {
  const ref = useRef<HTMLOListElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [log]);
  return (
    <ol ref={ref} className="card flex h-40 flex-col gap-1 overflow-y-auto p-3 font-mono text-xs">
      {log.length === 0 && <li className="m-auto text-slate-500">Tool calls will appear here.</li>}
      {log.map((line) => (
        <li key={line.id} className="rise flex gap-2 text-slate-300">
          <span className="shrink-0 text-slate-500">{line.time}</span>
          <span
            className={
              /failed|not found/i.test(line.text)
                ? "text-amber-300"
                : /passed|sent|rescheduled|handed off/i.test(line.text)
                  ? "text-emerald-300"
                  : undefined
            }
          >
            {line.text}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** The transparency panel. It subscribes only to panel data, so it never re-renders the avatar. */
export const SidePanel = memo(function SidePanel({ call }: { call: CallController }) {
  const { state, log } = useStore(call.panel);
  const { agentState } = useStore(call.status);
  // Every call opens with the Greeter. The backend's first panel update ("Call started") is sent
  // before its room connection is up, so it never arrives; highlight the Greeter until one does.
  const activeIdx = state ? AGENTS.findIndex((a) => a.name === state.agent) : agentState ? 0 : -1;
  const [statusLabel, statusStyle] = (state?.status && STATUS[state.status]) || ["—", ""];

  return (
    <aside className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-1">
      <section>
        <Heading>Active agent</Heading>
        <ol className="flex flex-col gap-1.5">
          {AGENTS.map((a, i) => (
            <AgentStep key={a.name} index={i} name={a.name} role={a.role} active={i === activeIdx} done={activeIdx > i} />
          ))}
        </ol>
      </section>

      <section>
        <Heading>Call details</Heading>
        <dl className="card flex flex-col p-2 text-sm">
          <Field label="Customer" value={state?.customer}>
            <span className={state?.verified ? "truncate text-slate-100" : "text-slate-400"}>
              {state?.verified ? state.customer : "Not verified"}
            </span>
            {state?.verified && (
              <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-300 ring-1 ring-inset ring-emerald-400/30">
                Verified
              </span>
            )}
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
        <Heading>Activity</Heading>
        <Activity log={log} />
      </section>

      <section>
        <Heading>Notepad</Heading>
        <dl className="card flex flex-col gap-0.5 p-2 font-mono text-xs">
          {state ? (
            Object.entries(state.notepad).map(([k, v]) => <NoteRow key={k} name={k} value={String(v)} />)
          ) : (
            <p className="px-2 py-1 text-slate-500">Shared call data appears once the call starts.</p>
          )}
        </dl>
      </section>

      <p className="mt-auto px-1 text-[11px] text-slate-500">Press D for the performance overlay.</p>
    </aside>
  );
});
