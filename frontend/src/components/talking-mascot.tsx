"use client";

import { useId } from "react";

/** Articulated vector adaptation of the approved browser-window mascot. */
export function TalkingMascot({
  phase,
  level,
  muted,
}: {
  phase: string;
  level: number;
  muted: boolean;
}) {
  const id = useId();
  return (
    <svg
      className="talking-mascot"
      data-phase={muted && phase !== "speaking" ? "muted" : phase}
      viewBox="0 0 320 360"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={id} x1="0" y1="1" x2="1" y2="0">
          <stop stopColor="var(--feature-top)" />
          <stop offset=".52" stopColor="var(--feature-middle)" />
          <stop offset="1" stopColor="var(--feature-bottom)" />
        </linearGradient>
      </defs>
      <ellipse
        cx="160"
        cy="338"
        rx="89"
        ry="9"
        fill="var(--foreground)"
        opacity=".08"
      />
      <g
        className="mascot-character"
        stroke="var(--mascot-ink)"
        strokeWidth="2.5"
        strokeLinejoin="round"
      >
        <path
          d="M126 279v26h22v-26m32 0v26h22v-26"
          fill="var(--mascot-paper)"
        />
        <path d="M126 289h22v8h-22m54-8h22v8h-22" fill="var(--marigold)" />
        <path
          d="M139 301c-29-10-60 7-66 31h77v-16c0-6-5-12-11-15Zm54 0c-29-10-60 7-66 31h98v-11c-1-12-13-19-32-20Z"
          fill="var(--marigold)"
        />
        <path
          d="m97 308 10 11m-1-16 10 12m35-6 10 11m-2-17 10 12"
          fill="none"
        />
        <path
          d="m119 221-5 66h47l3-49 1 49h47l-7-66Z"
          fill="var(--mascot-teal)"
        />
        <path d="M119 235q20 2 20-13m51 0q-2 17 18 17" fill="none" />
        <g className="mascot-window">
          <path d="M57 80h238l-25 152H31Z" fill="var(--mascot-paper)" />
          <path d="M43 67h239l-25 155H18Z" fill={`url(#${id})`} />
          <path d="M43 67h239l-4 25H39Z" fill="var(--mascot-paper)" />
          <circle cx="229" cy="80" r="4" fill="none" />
          <circle cx="245" cy="80" r="4" fill="none" />
          <circle cx="261" cy="80" r="4" fill="none" />
          <path d="M157 66q1-32 20-29 17 1 18 31Z" fill="var(--marigold)" />
          <path d="m138 64 58 4" />
          <g className="mascot-eyes">
            <ellipse
              cx="125"
              cy="139"
              rx="13"
              ry="15"
              fill="var(--mascot-paper)"
            />
            <ellipse
              cx="161"
              cy="139"
              rx="13"
              ry="15"
              fill="var(--mascot-paper)"
            />
            <ellipse
              cx="128"
              cy="140"
              rx="7"
              ry="10"
              fill="var(--mascot-ink)"
            />
            <ellipse
              cx="164"
              cy="140"
              rx="7"
              ry="10"
              fill="var(--mascot-ink)"
            />
          </g>
          <path
            d="M110 116q14-15 28-2m9 0q17-14 28 2"
            fill="none"
            strokeLinecap="round"
          />
          <path
            className="mascot-smile"
            d="M132 169q12 12 25-1"
            fill="none"
            strokeLinecap="round"
          />
          <g
            className="mascot-speaking-mouth"
            style={{ transform: `scaleY(${0.15 + Math.min(1, level) * 0.85})` }}
          >
            <ellipse
              cx="145"
              cy="174"
              rx="12"
              ry="14"
              fill="var(--mascot-ink)"
            />
            <path
              d="M138 181q7-5 14 0"
              stroke="var(--feature-top)"
              strokeWidth="5"
              strokeLinecap="round"
            />
          </g>
        </g>
      </g>
    </svg>
  );
}
