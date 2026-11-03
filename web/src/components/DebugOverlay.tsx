import { memo, useEffect, useState } from "react";

import type { Signals } from "../lib/signals";

/**
 * Press D to toggle. The avatar loop writes fps, loop time and the last reply gap straight into
 * this element twice a second, so the overlay itself never re-renders while open.
 */
export const DebugOverlay = memo(function DebugOverlay({ signals }: { signals: Signals }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "d" && !e.metaKey && !e.ctrlKey && !e.altKey) setOpen((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!open) return null;
  return (
    <pre
      ref={(el) => {
        signals.debugEl = el;
      }}
      className="pointer-events-none fixed bottom-3 left-3 z-50 rounded-lg bg-black/75 px-3 py-2 font-mono text-[11px] leading-relaxed text-lime-300"
    >
      measuring…
    </pre>
  );
});
