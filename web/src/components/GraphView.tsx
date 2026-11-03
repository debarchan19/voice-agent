import { memo } from "react";

import type { CallController } from "../lib/call";
import { useStore } from "../lib/store";
import { formatMs, lastOf, nodePath } from "../lib/trace";
import type { Span, Turn } from "../lib/types";

/*
 * The LangGraph graph from wismo/graph.py (see docs/graph.mmd), drawn by hand so it reads at a
 * glance in a recording. Nodes light up while they run and edges light up as the run moves along
 * them, both driven by the spans wismo/trace.py streams for the latest turn.
 */

type Kind = "io" | "code" | "llm" | "tools";

interface NodeDef {
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  kind: Kind;
}

const NODES: Record<string, NodeDef> = {
  __start__: { x: 320, y: 24, w: 76, h: 24, label: "START", kind: "io" },
  begin_turn: { x: 320, y: 92, w: 150, h: 34, label: "begin_turn", kind: "code" },
  confirmation_email: { x: 548, y: 92, w: 150, h: 34, label: "confirmation_email", kind: "code" },
  greeter: { x: 110, y: 180, w: 150, h: 44, label: "Greeter", kind: "llm" },
  order_status: { x: 320, y: 180, w: 150, h: 44, label: "Order Status", kind: "llm" },
  resolution: { x: 530, y: 180, w: 150, h: 44, label: "Resolution", kind: "llm" },
  greeter_tools: { x: 110, y: 280, w: 140, h: 32, label: "tools", kind: "tools" },
  order_status_tools: { x: 320, y: 280, w: 140, h: 32, label: "tools", kind: "tools" },
  resolution_tools: { x: 530, y: 280, w: 140, h: 32, label: "tools", kind: "tools" },
  __end__: { x: 320, y: 380, w: 76, h: 24, label: "END", kind: "io" },
};

/** Every edge in the compiled graph, as [from, to, path]. Kept in step with docs/graph.mmd. */
const EDGES: [string, string, string][] = [
  ["__start__", "begin_turn", "M320 36 L320 75"],
  ["begin_turn", "greeter", "M285 109 C250 135 130 130 110 158"],
  ["begin_turn", "order_status", "M320 109 L320 158"],
  ["begin_turn", "resolution", "M355 109 C390 135 510 130 525 158"],
  ["begin_turn", "confirmation_email", "M395 92 L473 92"],
  ["confirmation_email", "resolution", "M556 109 L548 158"],
  ["greeter", "greeter_tools", "M98 202 L98 264"],
  ["greeter_tools", "greeter", "M122 264 L122 202"],
  ["order_status", "order_status_tools", "M308 202 L308 264"],
  ["order_status_tools", "order_status", "M332 264 L332 202"],
  ["resolution", "resolution_tools", "M518 202 L518 264"],
  ["resolution_tools", "resolution", "M542 264 L542 202"],
  ["greeter_tools", "order_status", "M180 272 C215 262 240 230 262 202"],
  ["order_status_tools", "resolution", "M390 274 C420 262 450 232 468 202"],
  ["resolution_tools", "order_status", "M460 288 C425 288 398 242 384 202"],
  ["resolution_tools", "confirmation_email", "M600 280 C638 280 638 92 623 92"],
  ["greeter", "__end__", "M35 186 C0 270 130 380 282 380"],
  ["order_status", "__end__", "M262 202 C222 240 226 340 292 370"],
  ["resolution", "__end__", "M472 202 C420 240 418 340 348 370"],
];

const KIND_LABEL: Record<Kind, string> = { io: "", code: "code", llm: "LLM", tools: "ToolNode" };

/** The edges a turn travelled, in order: START, each node it ran, then END if it finished. */
function travelled(turn: Turn | undefined): string[] {
  if (!turn) return [];
  const path = ["__start__", ...nodePath(turn).map((s) => s.name)];
  if (turn.end !== null && turn.status === "ok") path.push("__end__");
  const keys: string[] = [];
  for (let i = 1; i < path.length; i++) keys.push(`${path[i - 1]}->${path[i]}`);
  return keys;
}

function toolOf(turn: Turn | undefined, node: string): Span | undefined {
  if (!turn) return undefined;
  const ids = new Set(turn.spans.filter((s) => s.kind === "node" && s.name === node).map((s) => s.id));
  return lastOf(turn.spans.filter((s) => s.kind === "tool" && s.parent !== null && ids.has(s.parent)));
}

function GraphNode({ id, def, turn }: { id: string; def: NodeDef; turn: Turn | undefined }) {
  const runs = turn ? turn.spans.filter((s) => s.kind === "node" && s.name === id) : [];
  const last = lastOf(runs);
  const running = last?.status === "running";
  const visited = runs.length > 0 || (id === "__start__" && !!turn) || (id === "__end__" && turn?.status === "ok" && turn.end !== null);
  const state = running ? "running" : last?.status === "cancelled" ? "cancelled" : visited ? "visited" : "idle";
  const tool = def.kind === "tools" ? toolOf(turn, id) : undefined;
  const x = def.x - def.w / 2;
  const y = def.y - def.h / 2;
  return (
    <g className="gnode" data-kind={def.kind} data-state={state}>
      <rect className="gnode-glow" x={x - 4} y={y - 4} width={def.w + 8} height={def.h + 8} rx={def.kind === "io" ? 16 : 14} />
      <rect className="gnode-box" x={x} y={y} width={def.w} height={def.h} rx={def.kind === "io" ? 12 : 10} />
      <text className="gnode-label" x={def.x} y={def.kind === "llm" ? def.y - 2 : def.y + 4} textAnchor="middle">
        {def.label}
      </text>
      {def.kind === "llm" && (
        <text className="gnode-sub" x={def.x} y={def.y + 13} textAnchor="middle">
          {last?.end != null ? `${KIND_LABEL.llm} · ${formatMs(last.end - last.start)}${runs.length > 1 ? ` · ×${runs.length}` : ""}` : KIND_LABEL.llm}
        </text>
      )}
      {def.kind === "code" && (
        <text className="gnode-tag" x={x + def.w - 6} y={y - 4} textAnchor="end">
          plain code
        </text>
      )}
      {tool && (
        <g className="gtool" data-status={tool.status}>
          <text x={def.x} y={y + def.h + 15} textAnchor="middle">
            {tool.status === "blocked" ? `⛔ ${tool.name} · blocked by gate` : tool.name}
          </text>
        </g>
      )}
    </g>
  );
}

export const GraphView = memo(function GraphView({ call }: { call: CallController }) {
  const { turns } = useStore(call.trace);
  const turn = lastOf(turns);
  const lit = travelled(turn);
  const latest = lastOf(lit);
  const running = turn?.end === null;

  return (
    <section className="card relative flex min-h-0 flex-col overflow-hidden p-3">
      <header className="flex items-center justify-between gap-2 px-1">
        <div>
          <h2 className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-400">LangGraph · live run</h2>
          <p className="text-xs text-slate-500">
            {turn ? `Turn ${turn.index} · ${running ? "running" : turn.status === "cancelled" ? "cancelled by barge-in" : "done"}` : "Waiting for the caller's first turn"}
          </p>
        </div>
        <div className="flex items-center gap-3 text-[10px] uppercase tracking-wider text-slate-400">
          <span className="flex items-center gap-1.5"><i className="legend legend-llm" />LLM agent</span>
          <span className="flex items-center gap-1.5"><i className="legend legend-tools" />tools</span>
          <span className="flex items-center gap-1.5"><i className="legend legend-code" />code</span>
        </div>
      </header>
      <svg viewBox="0 0 640 400" className="graph min-h-0 w-full flex-1" role="img" aria-label="Live view of the LangGraph run">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" fill="#475569" />
          </marker>
          <marker id="arrow-lit" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" fill="#5eead4" />
          </marker>
        </defs>
        {EDGES.map(([from, to, d]) => {
          const key = `${from}->${to}`;
          const on = lit.includes(key);
          return (
            <path
              key={key}
              d={d}
              className="gedge"
              data-lit={on}
              data-latest={on && key === latest && running}
              markerEnd={on ? "url(#arrow-lit)" : "url(#arrow)"}
            />
          );
        })}
        {Object.entries(NODES).map(([id, def]) => (
          <GraphNode key={id} id={id} def={def} turn={turn} />
        ))}
      </svg>
    </section>
  );
});
