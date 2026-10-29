/** Three dots beside the head. Shown by CSS while data-mood="thinking"; each dot bobs with a transform. */
export function ThinkingDots() {
  return (
    <g transform="translate(286 92)">
      <g className="av-dots">
        <rect x="0" y="0" width="66" height="28" rx="14" fill="#ffffff" fillOpacity="0.12" />
        <rect x="0.5" y="0.5" width="65" height="27" rx="13.5" fill="none" stroke="#c4b5fd" strokeOpacity="0.45" />
        <circle className="av-dot" cx="17" cy="14" r="4" fill="#ddd6fe" />
        <circle className="av-dot" cx="33" cy="14" r="4" fill="#ddd6fe" />
        <circle className="av-dot" cx="49" cy="14" r="4" fill="#ddd6fe" />
        <circle cx="-6" cy="34" r="4" fill="#ffffff" fillOpacity="0.12" />
      </g>
    </g>
  );
}
