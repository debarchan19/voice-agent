import { useEffect, useRef } from "react";

/** Briefly highlights an element whenever `value` changes (not on first render), if `enabled`. */
export function useFlash<T extends HTMLElement>(value: unknown, enabled = true) {
  const ref = useRef<T>(null);
  const prev = useRef(value);
  useEffect(() => {
    if (Object.is(prev.current, value)) return;
    prev.current = value;
    const el = ref.current;
    if (!el || !enabled) return;
    el.classList.remove("flash");
    void el.offsetWidth; // restart the animation
    el.classList.add("flash");
  }, [value, enabled]);
  return ref;
}
