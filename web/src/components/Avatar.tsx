import { memo, useEffect, useRef } from "react";

import { type AvatarParts, startAvatarLoop } from "../lib/avatarLoop";
import type { Signals } from "../lib/signals";
import { ThinkingDots } from "./ThinkingDots";

/*
 * Mika, the Delivery Desk host: an original character drawn as layered SVG.
 *
 * Every moving part is its own group. Groups with an `av-*` class get their mood pose from CSS
 * transitions (driven by data-mood on the <svg>); groups with a ref are moved each frame by the
 * single loop in lib/avatarLoop.ts. The two never share an element, so they can't fight.
 * The component renders once: its only prop is the stable `signals` object.
 */

const SKIN = "#f7d6c1";
const HAIR = "#2b2f6e";

// Eye in local coordinates, centred on (0, 0), outer corner on the left.
const EYE = "M-26 -8 C-22 -26 -6 -30 6 -29 C17 -28 25 -22 26 -12 C27 6 18 24 0 25 C-16 25 -26 10 -26 -8 Z";
const LASH = "M-26 -8 C-22 -26 -6 -30 6 -29 C17 -28 25 -22 26 -12";
const LID = "M-36 -96 L36 -96 L36 -12 L26 -12 C25 -22 17 -28 6 -29 C-6 -30 -22 -26 -26 -8 L-36 -8 Z";

interface EyeProps {
  x: number;
  mirror: boolean;
  irisRef: (el: SVGGElement | null) => void;
  lidRef: (el: SVGGElement | null) => void;
}

function Eye({ x, mirror, irisRef, lidRef }: EyeProps) {
  const flip = mirror ? "scale(-1 1)" : undefined;
  const clipId = mirror ? "eye-clip-r" : "eye-clip-l";
  return (
    <g transform={`translate(${x} 224) ${flip ?? ""}`}>
      <g className="av-eye">
        <clipPath id={clipId}>
          <path d={EYE} />
        </clipPath>
        <g clipPath={`url(#${clipId})`}>
          <path d={EYE} fill="#fbfdff" />
          <path d="M-26 -8 C-22 -26 -6 -30 6 -29 C17 -28 25 -22 26 -12 L26 -4 C14 -18 -12 -20 -26 0 Z" fill="#d9def0" />
          {/* Undo the mirror for the iris, so both eyes glance the same way. */}
          <g transform={flip}>
            <g className="av-glance">
              <g ref={irisRef}>
                <ellipse cx="0" cy="3" rx="15.5" ry="19" fill="url(#iris)" />
                <ellipse cx="0" cy="3" rx="15.5" ry="19" fill="none" stroke="#123047" strokeWidth="1.5" />
                <ellipse cx="0" cy="5" rx="7" ry="9" fill="#0d1b2e" />
                <circle cx="-6" cy="-6" r="5" fill="#ffffff" />
                <circle cx="6" cy="11" r="2.4" fill="#ffffff" opacity="0.85" />
              </g>
            </g>
          </g>
        </g>
        <path d="M-12 25 Q0 28 12 24" fill="none" stroke="#c48c7a" strokeWidth="1.6" strokeLinecap="round" />
        {/* Eyelid: skin above the lash line. Sliding it down closes the eye. */}
        <g ref={lidRef}>
          <path d={LID} fill={SKIN} />
          <path d={LASH} fill="none" stroke="#1a1d33" strokeWidth="4.5" strokeLinecap="round" />
          <path d="M-25 -10 L-33 -15" stroke="#1a1d33" strokeWidth="3.5" strokeLinecap="round" />
        </g>
      </g>
    </g>
  );
}

type PartName = Exclude<keyof AvatarParts, "mouths">;

interface AvatarProps {
  signals: Signals;
}

export const Avatar = memo(function Avatar({ signals }: AvatarProps) {
  const parts = useRef<Partial<AvatarParts>>({ mouths: [] });
  const bind = (name: PartName) => (el: SVGElement | null) => {
    if (el) (parts.current as Record<string, SVGElement>)[name] = el;
  };
  const bindMouth = (i: number) => (el: SVGGElement | null) => {
    if (el) parts.current.mouths![i] = el;
  };

  useEffect(() => startAvatarLoop(parts.current as AvatarParts, signals), [signals]);

  return (
    <svg
      ref={bind("root")}
      data-mood="idle"
      viewBox="0 0 400 420"
      className="avatar h-full w-full"
      role="img"
      aria-label="Mika, the Delivery Desk assistant"
    >
      <defs>
        <radialGradient id="ring" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0.8" stopColor="#5eead4" stopOpacity="0" />
          <stop offset="0.9" stopColor="#5eead4" stopOpacity="0.55" />
          <stop offset="1" stopColor="#5eead4" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="iris" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#123a5c" />
          <stop offset="0.55" stopColor="#1f7a8c" />
          <stop offset="1" stopColor="#5eead4" />
        </linearGradient>
        <linearGradient id="hair" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3a43a0" />
          <stop offset="1" stopColor={HAIR} />
        </linearGradient>
        <linearGradient id="jacket" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#2f3d66" />
          <stop offset="1" stopColor="#1c2644" />
        </linearGradient>
      </defs>

      {/* Listening ring: opacity and scale follow the caller's mic level. */}
      <g ref={bind("ring")} opacity="0">
        <circle cx="200" cy="210" r="190" fill="url(#ring)" />
      </g>

      {/* Back hair moves with the head but is drawn behind the neck and shoulders. */}
      <g className="av-mood av-head">
        <g ref={bind("headBack")}>
          <g ref={bind("hairBack")}>
            <path
              d="M96 196 C88 118 138 66 200 66 C262 66 312 118 304 196 C308 250 302 300 290 336 L250 336
                 C262 292 262 250 256 222 L144 222 C138 250 138 292 150 336 L110 336 C98 300 92 250 96 196 Z"
              fill="#1e2252"
            />
          </g>
        </g>
      </g>

      <g ref={bind("shoulders")}>
        <path d="M54 420 C66 362 118 332 172 324 L228 324 C282 332 334 362 346 420 Z" fill="url(#jacket)" />
        <path d="M172 324 L200 372 L228 324 Z" fill="#e9edf7" />
        <path d="M172 324 L190 380 L160 360 Z M228 324 L210 380 L240 360 Z" fill="#3a4a7a" />
        <path d="M180 282 L180 328 Q200 344 220 328 L220 282 Z" fill={SKIN} />
        <path d="M180 288 Q200 308 220 288 L220 302 Q200 318 180 302 Z" fill="#e3ad95" />
        {/* Name badge with a little parcel: she works the delivery desk. */}
        <g transform="translate(250 372)">
          <rect x="0" y="0" width="44" height="18" rx="4" fill="#e9edf7" />
          <path d="M6 6 L13 3 L20 6 L20 13 L13 16 L6 13 Z" fill="#f2b36b" />
          <path d="M6 6 L13 9 L20 6 M13 9 L13 16" fill="none" stroke="#b9772f" strokeWidth="1" />
          <rect x="24" y="6" width="14" height="2.5" rx="1" fill="#8a94b0" />
          <rect x="24" y="10.5" width="10" height="2.5" rx="1" fill="#b4bcd2" />
        </g>
      </g>

      <g className="av-mood av-head">
        <g ref={bind("head")}>
          <ellipse cx="129" cy="218" rx="10" ry="16" fill={SKIN} />
          <ellipse cx="271" cy="218" rx="10" ry="16" fill={SKIN} />
          <path
            d="M128 182 C128 122 160 96 200 96 C240 96 272 122 272 182 C272 226 258 258 232 280
               C220 290 210 295 200 295 C190 295 180 290 168 280 C142 258 128 226 128 182 Z"
            fill={SKIN}
          />

          <Eye x={163} mirror={false} irisRef={bind("irisL")} lidRef={bind("lidL")} />
          <Eye x={237} mirror irisRef={bind("irisR")} lidRef={bind("lidR")} />

          <ellipse cx="148" cy="260" rx="14" ry="6" fill="#f59ca3" opacity="0.45" />
          <ellipse cx="252" cy="260" rx="14" ry="6" fill="#f59ca3" opacity="0.45" />
          <path d="M200 246 L197 253 L201 254" fill="none" stroke="#d49a82" strokeWidth="1.6" strokeLinecap="round" />

          {/* Mouth shapes, closed to wide open, plus an "o" for the interrupted reaction. One is visible. */}
          <g className="av-mouth" ref={bindMouth(0)}>
            <path d="M189 271 Q200 277 211 271" fill="none" stroke="#a24b5a" strokeWidth="2.6" strokeLinecap="round" />
          </g>
          <g className="av-mouth" ref={bindMouth(1)} opacity="0">
            <path d="M190 269 Q200 267 210 269 Q200 279 190 269 Z" fill="#7b2f3d" />
          </g>
          <g className="av-mouth" ref={bindMouth(2)} opacity="0">
            <path d="M188 268 Q200 265 212 268 Q209 285 200 285 Q191 285 188 268 Z" fill="#7b2f3d" />
            <ellipse cx="200" cy="281" rx="6.5" ry="3" fill="#e07a83" />
          </g>
          <g className="av-mouth" ref={bindMouth(3)} opacity="0">
            <path d="M186 266 Q200 262 214 266 Q211 293 200 293 Q189 293 186 266 Z" fill="#7b2f3d" />
            <path d="M189 267 Q200 264 211 267 L210 270 Q200 268 190 270 Z" fill="#ffffff" />
            <ellipse cx="200" cy="288" rx="8" ry="3.6" fill="#e07a83" />
          </g>
          <g className="av-mouth" ref={bindMouth(4)} opacity="0">
            <ellipse cx="200" cy="273" rx="5.5" ry="7" fill="#7b2f3d" />
          </g>

          <g ref={bind("brows")}>
            <g className="av-mood av-brow-l">
              <path d="M142 190 Q160 180 182 186" fill="none" stroke="#23265a" strokeWidth="4" strokeLinecap="round" />
            </g>
            <g className="av-mood av-brow-r">
              <path d="M218 186 Q240 180 258 190" fill="none" stroke="#23265a" strokeWidth="4" strokeLinecap="round" />
            </g>
          </g>

          <g ref={bind("lockL")}>
            <path d="M124 168 C108 210 110 262 126 304 C131 272 135 232 142 196 Z" fill="url(#hair)" />
          </g>
          <g ref={bind("lockR")}>
            <path d="M276 168 C292 210 290 262 274 304 C269 272 265 232 258 196 Z" fill="url(#hair)" />
          </g>
          <g ref={bind("bangs")}>
            <path
              d="M118 198 C108 120 150 76 205 76 C264 78 296 128 284 202 C280 180 272 164 260 154
                 C262 168 258 176 252 182 C244 162 234 148 220 140 C220 156 212 168 202 176
                 C202 160 194 148 184 142 C180 158 170 168 158 174 C160 162 156 152 150 148
                 C140 162 128 180 118 198 Z"
              fill="url(#hair)"
            />
            <path d="M150 106 C170 93 196 88 222 91" fill="none" stroke="#6f7ee0" strokeWidth="5" strokeLinecap="round" opacity="0.5" />
          </g>
          <g ref={bind("ahoge")}>
            <path d="M202 80 C196 60 210 44 230 42 C216 52 210 64 212 80 Z" fill="#343a8a" />
          </g>

          {/* Headset */}
          <path d="M120 176 C116 100 158 64 200 64 C242 64 284 100 280 176" fill="none" stroke="#d6dcea" strokeWidth="6" strokeLinecap="round" />
          <rect x="110" y="196" width="18" height="36" rx="8" fill="#39425a" />
          <rect x="272" y="196" width="18" height="36" rx="8" fill="#39425a" />
          <rect x="276" y="206" width="3" height="16" rx="1.5" fill="#5eead4" />
          <path d="M284 226 C290 262 266 284 236 286" fill="none" stroke="#39425a" strokeWidth="4" strokeLinecap="round" />
          <circle ref={bind("micTip")} cx="234" cy="286" r="5" fill="#5eead4" opacity="0.2" />
        </g>
      </g>

      <ThinkingDots />
    </svg>
  );
});
