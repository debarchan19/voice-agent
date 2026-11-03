import { useEffect, useState } from "react";

import { Avatar } from "./components/Avatar";
import { Captions } from "./components/Captions";
import { ControlBar, StatusPill } from "./components/ControlBar";
import { DebugOverlay } from "./components/DebugOverlay";
import { GraphView } from "./components/GraphView";
import { InterruptFlash } from "./components/InterruptFlash";
import { SidePanel } from "./components/SidePanel";
import { TraceView } from "./components/TraceView";
import { CallController } from "./lib/call";
import { startReplay } from "./lib/replay";
import type { Mood } from "./lib/types";

/**
 * A 16:9 stage in three columns, laid out for a screen recording:
 *   the experience (Sam, captions, controls) | the system (live graph, trace waterfall) | the data
 * App renders once; each child subscribes only to the store it shows.
 */
export default function App() {
  const [call] = useState(() => {
    const c = new CallController();
    // Dev only: preview a pose without a call, e.g. http://localhost:5173/?mood=thinking
    const mood = import.meta.env.DEV && new URLSearchParams(location.search).get("mood");
    if (mood) c.signals.mood = mood as Mood;
    return c;
  });

  // Dev only: replay a recorded call, e.g. http://localhost:5173/?replay or ?replay=other.json&speed=2
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (!import.meta.env.DEV || !params.has("replay")) return;
    let stop = () => {};
    let run = 0; // only the latest run may start its timers (StrictMode mounts effects twice)
    const play = () => {
      stop();
      const mine = ++run;
      startReplay(call, params.get("replay") || "replay.json", Number(params.get("speed")) || 1, () => mine === run)
        .then((s) => (stop = s))
        .catch((err) => console.error(err));
    };
    const onKey = (e: KeyboardEvent) => e.key.toLowerCase() === "r" && !e.metaKey && !e.ctrlKey && play(); // R restarts
    play();
    window.addEventListener("keydown", onKey);
    return () => {
      run++;
      stop();
      window.removeEventListener("keydown", onKey);
    };
  }, [call]);

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <main className="stage grid w-full gap-3 lg:aspect-video lg:grid-cols-[minmax(0,0.82fr)_minmax(0,1.3fr)_19rem]">
        <section className="relative flex min-h-[36rem] flex-col overflow-hidden rounded-3xl border border-white/10 bg-[#11182b] lg:min-h-0">
          <div className="glow" aria-hidden="true" />
          <header className="relative flex items-center justify-between gap-3 px-5 pt-4">
            <div>
              <h1 className="text-lg font-semibold tracking-tight">Delivery Desk</h1>
              <p className="text-xs text-slate-400">Voice support for late and missing deliveries</p>
            </div>
            <StatusPill call={call} />
          </header>
          <div className="relative min-h-0 flex-1 px-4">
            <Avatar signals={call.signals} />
          </div>
          <div className="relative flex flex-col gap-3 px-5 pb-5">
            <Captions call={call} />
            <ControlBar call={call} />
          </div>
          <InterruptFlash call={call} />
        </section>
        <div className="grid min-h-[40rem] gap-3 lg:min-h-0 lg:grid-rows-[minmax(0,1.1fr)_minmax(0,1fr)]">
          <GraphView call={call} />
          <TraceView call={call} />
        </div>
        <SidePanel call={call} />
      </main>
      <DebugOverlay signals={call.signals} />
    </div>
  );
}
