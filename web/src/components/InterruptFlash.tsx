import { memo, useEffect, useState } from "react";

import type { CallController } from "../lib/call";
import { useStore } from "../lib/store";

const SHOW_MS = 2400;

/**
 * A barge-in, made obvious for a recording: a ring around the avatar card and a banner. Shown for
 * a moment on every interruption, then removed. It sits over the avatar and never touches it.
 */
export const InterruptFlash = memo(function InterruptFlash({ call }: { call: CallController }) {
  const { count } = useStore(call.interrupts);
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (count === 0) return;
    setShown(count);
    const id = window.setTimeout(() => setShown(0), SHOW_MS);
    return () => window.clearTimeout(id);
  }, [count]);

  if (shown === 0) return null;
  return (
    <div key={shown} className="pointer-events-none absolute inset-0 z-10" aria-live="assertive">
      <div className="interrupt-ring absolute inset-0 rounded-3xl" />
      <div className="interrupt-banner absolute left-1/2 top-[5.5rem] flex -translate-x-1/2 items-center gap-2 whitespace-nowrap rounded-full px-4 py-1.5 text-sm font-semibold">
        <span aria-hidden="true">✋</span>
        Caller cut in · Sam stopped mid-sentence
      </div>
    </div>
  );
});
