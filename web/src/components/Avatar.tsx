import { memo, useEffect, useRef } from "react";

import { type AvatarParts, startAvatarLoop } from "../lib/avatarLoop";
import type { Signals } from "../lib/signals";
import { ThinkingDots } from "./ThinkingDots";

/*
 * Sam, the Delivery Desk host: an original courier character in a branded cap and uniform polo,
 * drawn as layered SVG.
 *
 * Every moving part is its own group. Groups with an `av-*` class get their mood pose from CSS
 * transitions (driven by data-mood on the <svg>); groups with a ref are moved each frame by the
 * single loop in lib/avatarLoop.ts. The two never share an element, so they can't fight.
 * The component renders once: its only prop is the stable `signals` object.
 */

const SKIN = "#eebf9f";
const SKIN_SHADE = "#d9a283";
const HAIR = "#2a1d16";
const NAVY = "#1f3a5f";
const TEAL = "#5eead4";

// Eye in local coordinates, centred on (0, 0). Almond shaped, so mirroring is only for the iris.
const EYE = "M-15 0 C-10 -8 8 -9 15 -1 C9 6 -8 7 -15 0 Z";
const LASH = "M-15 0 C-10 -8 8 -9 15 -1";
// Eyelid: skin whose lower edge is the lash line. It sits just above the eye and is clipped to it,
// so sliding it down (see LID_TRAVEL in avatarLoop.ts) closes the eye without spilling onto the face.
const LID = "M-20 -30 L20 -30 L20 -1 L15 -1 C8 -9 -10 -8 -15 0 L-20 0 Z";

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
    <g transform={`translate(${x} 226) ${flip ?? ""}`}>
      <g className="av-eye">
        <clipPath id={clipId}>
          <path d={EYE} />
        </clipPath>
        <path d="M-13 -9 C-6 -14 8 -14 14 -7" fill="none" stroke={SKIN_SHADE} strokeWidth="1.4" strokeLinecap="round" />
        <g clipPath={`url(#${clipId})`}>
          <path d={EYE} fill="#f8f9fb" />
          {/* Undo the mirror for the iris, so both eyes glance the same way. */}
          <g transform={flip}>
            <g className="av-glance">
              <g ref={irisRef}>
                <circle cx="0" cy="-1" r="6.6" fill="url(#iris)" />
                <circle cx="0" cy="-1" r="3" fill="#120b07" />
                <circle cx="-2.2" cy="-3.2" r="1.6" fill="#ffffff" opacity="0.9" />
              </g>
            </g>
          </g>
          <path d="M-15 -8 L15 -8 L15 -1 C8 -9 -10 -8 -15 0 Z" fill="#000" opacity="0.08" />
          <g ref={lidRef}>
            <path d={LID} fill={SKIN} />
            <path d={LASH} fill="none" stroke={HAIR} strokeWidth="2.6" strokeLinecap="round" />
          </g>
        </g>
        <path d={LASH} fill="none" stroke={HAIR} strokeWidth="2.2" strokeLinecap="round" />
        <path d="M-9 5.5 Q0 8 9 4.5" fill="none" stroke={SKIN_SHADE} strokeWidth="1" strokeLinecap="round" />
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
      aria-label="Sam, the Delivery Desk assistant"
    >
      <defs>
        <radialGradient id="ring" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0.8" stopColor={TEAL} stopOpacity="0" />
          <stop offset="0.9" stopColor={TEAL} stopOpacity="0.55" />
          <stop offset="1" stopColor={TEAL} stopOpacity="0" />
        </radialGradient>
        <radialGradient id="iris" cx="0.5" cy="0.45" r="0.5">
          <stop offset="0.3" stopColor="#6b4a2e" />
          <stop offset="1" stopColor="#3b2416" />
        </radialGradient>
        <linearGradient id="cap" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#2c4c78" />
          <stop offset="1" stopColor="#1a3050" />
        </linearGradient>
        <linearGradient id="uniform" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={NAVY} />
          <stop offset="1" stopColor="#14263f" />
        </linearGradient>
      </defs>

      {/* Listening ring: opacity and scale follow the caller's mic level. */}
      <g ref={bind("ring")} opacity="0">
        <circle cx="200" cy="210" r="190" fill="url(#ring)" />
      </g>

      {/* Uniform polo with the company patch and a name tag. */}
      <g ref={bind("shoulders")}>
        <path d="M50 420 C62 360 116 332 170 326 L230 326 C284 332 338 360 350 420 Z" fill="url(#uniform)" />
        <path d="M74 384 C94 362 122 348 154 340" fill="none" stroke={TEAL} strokeWidth="4" strokeLinecap="round" opacity="0.75" />
        <path d="M326 384 C306 362 278 348 246 340" fill="none" stroke={TEAL} strokeWidth="4" strokeLinecap="round" opacity="0.75" />
        <path d="M178 288 L178 330 Q200 346 222 330 L222 288 Z" fill={SKIN} />
        <path d="M178 294 Q200 314 222 294 L222 308 Q200 324 178 308 Z" fill={SKIN_SHADE} />
        <path d="M174 326 L200 360 L226 326 Z" fill={SKIN} />
        <path d="M194 356 L206 356 L206 404 L194 404 Z" fill="#172d4a" />
        <circle cx="200" cy="372" r="2" fill="#e9edf7" />
        <circle cx="200" cy="389" r="2" fill="#e9edf7" />
        <path d="M168 324 L200 360 L184 376 L156 340 Z" fill="#26476f" />
        <path d="M232 324 L200 360 L216 376 L244 340 Z" fill="#26476f" />
        <path d="M168 324 L200 360 M232 324 L200 360" fill="none" stroke={TEAL} strokeWidth="1.5" opacity="0.6" />
        <g transform="translate(112 374)">
          <rect x="0" y="0" width="48" height="18" rx="4" fill="#e9edf7" />
          <text x="24" y="12.5" textAnchor="middle" fontFamily="Inter, system-ui, sans-serif" fontSize="10" fontWeight="700" letterSpacing="1.5" fill="#1c2644">
            SAM
          </text>
        </g>
        <g transform="translate(246 370)">
          <rect x="0" y="0" width="30" height="24" rx="5" fill="#14263f" stroke={TEAL} strokeOpacity="0.5" />
          <path d="M8 8 L15 4.5 L22 8 L22 16 L15 19.5 L8 16 Z" fill={TEAL} />
          <path d="M8 8 L15 11.5 L22 8 M15 11.5 L15 19.5" fill="none" stroke="#14263f" strokeWidth="1.2" />
        </g>
      </g>

      <g className="av-mood av-head">
        <g ref={bind("head")}>
          {/* Short hair, only visible at the temples under the cap. */}
          <path d="M124 180 C121 192 123 202 129 208 L140 182 Z" fill={HAIR} />
          <path d="M276 180 C279 192 277 202 271 208 L260 182 Z" fill={HAIR} />

          <ellipse cx="131" cy="216" rx="10" ry="17" fill={SKIN} />
          <ellipse cx="269" cy="216" rx="10" ry="17" fill={SKIN} />
          <path d="M127 206 C122 214 124 224 129 228" fill="none" stroke={SKIN_SHADE} strokeWidth="2" strokeLinecap="round" />
          <path d="M273 206 C278 214 276 224 271 228" fill="none" stroke={SKIN_SHADE} strokeWidth="2" strokeLinecap="round" />
          <path
            d="M130 182 C130 124 162 100 200 100 C238 100 270 124 270 182 C270 226 264 254 248 274
               C234 292 218 302 200 302 C182 302 166 292 152 274 C136 254 130 226 130 182 Z"
            fill={SKIN}
          />
          <path d="M134 178 L150 180 C148 194 146 204 146 214 C142 208 138 200 136 192 Z" fill={HAIR} />
          <path d="M266 178 L250 180 C252 194 254 204 254 214 C258 208 262 200 264 192 Z" fill={HAIR} />
          {/* Shade from the cap brim. */}
          <path d="M140 200 C170 205 230 205 260 200 C240 214 160 214 140 200 Z" fill={SKIN_SHADE} opacity="0.45" />

          <Eye x={164} mirror={false} irisRef={bind("irisL")} lidRef={bind("lidL")} />
          <Eye x={236} mirror irisRef={bind("irisR")} lidRef={bind("lidR")} />

          {/* Nose and chin. */}
          <path d="M204 232 C206 241 208 247 207 251" fill="none" stroke={SKIN_SHADE} strokeWidth="1.8" strokeLinecap="round" />
          <path d="M193 252 Q200 257 207 252" fill="none" stroke="#c48c74" strokeWidth="1.8" strokeLinecap="round" />
          <path d="M186 292 Q200 297 214 292" fill="none" stroke={SKIN_SHADE} strokeWidth="1.4" strokeLinecap="round" opacity="0.6" />

          {/* Mouth shapes, closed to wide open, plus an "o" for the interrupted reaction. One is visible. */}
          <g className="av-mouth" ref={bindMouth(0)}>
            <path d="M188 266 Q200 271 212 266" fill="none" stroke="#9a5a52" strokeWidth="2.6" strokeLinecap="round" />
            <path d="M194 275 Q200 277 206 275" fill="none" stroke={SKIN_SHADE} strokeWidth="1.5" strokeLinecap="round" />
          </g>
          <g className="av-mouth" ref={bindMouth(1)} opacity="0">
            <path d="M190 265 Q200 263 210 265 Q200 274 190 265 Z" fill="#5a2a2e" />
          </g>
          <g className="av-mouth" ref={bindMouth(2)} opacity="0">
            <path d="M188 264 Q200 261 212 264 Q209 280 200 280 Q191 280 188 264 Z" fill="#5a2a2e" />
            <path d="M190 264.5 Q200 262.5 210 264.5 L209.5 267 Q200 265.5 190.5 267 Z" fill="#ffffff" />
          </g>
          <g className="av-mouth" ref={bindMouth(3)} opacity="0">
            <path d="M186 262 Q200 258 214 262 Q211 287 200 287 Q189 287 186 262 Z" fill="#5a2a2e" />
            <path d="M189 263 Q200 260 211 263 L210 266 Q200 264 190 266 Z" fill="#ffffff" />
            <ellipse cx="200" cy="283" rx="8" ry="3.4" fill="#b5615f" />
          </g>
          <g className="av-mouth" ref={bindMouth(4)} opacity="0">
            <ellipse cx="200" cy="268" rx="5.5" ry="7" fill="#5a2a2e" />
          </g>

          <g ref={bind("brows")}>
            <g className="av-mood av-brow-l">
              <path d="M146 213 Q162 206 182 210" fill="none" stroke={HAIR} strokeWidth="5" strokeLinecap="round" />
            </g>
            <g className="av-mood av-brow-r">
              <path d="M218 210 Q238 206 254 213" fill="none" stroke={HAIR} strokeWidth="5" strokeLinecap="round" />
            </g>
          </g>

          {/* Courier cap: crown with the parcel logo, teal piping, then the brim. */}
          <path d="M126 182 C124 124 160 86 200 86 C240 86 276 124 274 182 C246 172 154 172 126 182 Z" fill="url(#cap)" />
          <path
            d="M200 88 L200 174 M200 88 C180 104 166 136 164 176 M200 88 C220 104 234 136 236 176"
            fill="none"
            stroke="#11233b"
            strokeWidth="1.5"
            opacity="0.6"
          />
          <path d="M154 116 C170 100 194 94 222 96" fill="none" stroke="#4f6f9c" strokeWidth="4" strokeLinecap="round" opacity="0.5" />
          <circle cx="200" cy="88" r="5" fill="#2c4c78" stroke="#11233b" strokeWidth="1" />
          <path d="M189 134 L200 128.5 L211 134 L211 147 L200 152.5 L189 147 Z" fill={TEAL} />
          <path d="M189 134 L200 139.5 L211 134 M200 139.5 L200 152.5" fill="none" stroke={NAVY} strokeWidth="1.6" />
          <path d="M112 186 C150 172 250 172 288 186 C292 190 290 196 284 198 C250 206 150 206 116 198 C110 196 108 190 112 186 Z" fill="#132640" />
          <path d="M118 194 C150 201 250 201 282 194" fill="none" stroke="#2c4c78" strokeWidth="1.5" opacity="0.7" />
          <path d="M126 182 C154 172 246 172 274 182" fill="none" stroke={TEAL} strokeWidth="2.5" strokeLinecap="round" />

          {/* Single-ear headset on the right: band under the cap, earpiece, boom mic. */}
          <path d="M268 200 C272 192 272 186 270 180" fill="none" stroke="#39425a" strokeWidth="3" strokeLinecap="round" />
          <rect x="262" y="198" width="15" height="32" rx="7" fill="#39425a" />
          <rect x="270" y="206" width="3" height="15" rx="1.5" fill={TEAL} />
          <path d="M272 228 C276 262 258 282 232 284" fill="none" stroke="#39425a" strokeWidth="3.5" strokeLinecap="round" />
          <circle ref={bind("micTip")} cx="230" cy="284" r="4.5" fill={TEAL} opacity="0.2" />
        </g>
      </g>

      <ThinkingDots />
    </svg>
  );
});
