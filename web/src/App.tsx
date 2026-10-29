import { useState } from "react";

import { Avatar } from "./components/Avatar";
import { Captions } from "./components/Captions";
import { ControlBar, StatusPill } from "./components/ControlBar";
import { DebugOverlay } from "./components/DebugOverlay";
import { SidePanel } from "./components/SidePanel";
import { CallController } from "./lib/call";
import type { Mood } from "./lib/types";

/**
 * A 16:9 stage: avatar on the left, transparency panel on the right. App renders once; each
 * child subscribes only to the store it shows.
 */
export default function App() {
  const [call] = useState(() => {
    const c = new CallController();
    // Dev only: preview a pose without a call, e.g. http://localhost:5173/?mood=thinking
    const mood = import.meta.env.DEV && new URLSearchParams(location.search).get("mood");
    if (mood) c.signals.mood = mood as Mood;
    return c;
  });

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <main className="stage grid w-full gap-4 lg:aspect-video lg:grid-cols-[minmax(0,1fr)_22rem]">
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
        </section>
        <SidePanel call={call} />
      </main>
      <DebugOverlay signals={call.signals} />
    </div>
  );
}
