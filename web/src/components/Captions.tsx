import { memo } from "react";

import type { CallController } from "../lib/call";
import { useStore } from "../lib/store";

/** Live captions from LiveKit's "lk.transcription" text streams, newest at the bottom. */
export const Captions = memo(function Captions({ call }: { call: CallController }) {
  const captions = useStore(call.captions);
  return (
    <div className="flex h-24 flex-col justify-end gap-1 overflow-hidden px-2 text-center" aria-live="polite">
      {captions.length === 0 ? (
        <p className="text-sm text-slate-500">Captions will appear here.</p>
      ) : (
        captions.slice(-2).map((c) => (
          <p key={c.id} className="rise text-[15px] leading-snug">
            <span className={`mr-2 text-[11px] font-semibold uppercase tracking-wider ${c.who === "user" ? "text-sky-300" : "text-teal-300"}`}>
              {c.who === "user" ? "You" : "Mika"}
            </span>
            <span className={c.who === "user" ? "text-slate-200" : "text-white"}>{c.text}</span>
          </p>
        ))
      )}
    </div>
  );
});
