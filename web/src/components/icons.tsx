/** Inline icons: no library, no network, and they inherit `currentColor` in both themes. */

interface IconProps {
  size?: number;
  className?: string;
}

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 16 16",
  fill: "none" as const,
  stroke: "currentColor" as const,
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
});

export function Chevron({ size = 12, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M6 3.5 10.5 8 6 12.5" />
    </svg>
  );
}

export function Plus({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M8 3.5v9M3.5 8h9" />
    </svg>
  );
}

export function ArrowUp({ size = 15 }: IconProps) {
  return (
    <svg {...base(size)} strokeWidth={1.8}>
      <path d="M8 12.5v-9M4 7.5 8 3.5l4 4" />
    </svg>
  );
}

export function ArrowDown({ size = 14 }: IconProps) {
  return (
    <svg viewBox="0 0 16 16" width={size} height={size} fill="none" aria-hidden="true">
      <path
        d="M8 3v10M4 9l4 4 4-4"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function ArrowRight({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M3.5 8h9M9 4.5 12.5 8 9 11.5" />
    </svg>
  );
}

export function Spinner({ size = 12, className }: IconProps) {
  return (
    <svg {...base(size)} className={className} strokeWidth={2}>
      <path d="M8 1.8a6.2 6.2 0 1 1-4.4 1.8" />
    </svg>
  );
}

export function Trash({ size = 13 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M2.8 4.2h10.4M6.2 4.2V2.9h3.6v1.3M4.3 4.2l.6 8.2h6.2l.6-8.2" />
    </svg>
  );
}

export function Sun({ size = 15 }: IconProps) {
  return (
    <svg {...base(size)}>
      <circle cx="8" cy="8" r="3.1" />
      <path d="M8 1.4v1.3M8 13.3v1.3M14.6 8h-1.3M2.7 8H1.4M12.7 3.3l-.9.9M4.2 11.8l-.9.9M12.7 12.7l-.9-.9M4.2 4.2l-.9-.9" />
    </svg>
  );
}

export function Moon({ size = 15 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.7 5.7 0 1 0 6.8 6.8Z" />
    </svg>
  );
}

export function Menu({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M2.4 4.4h11.2M2.4 8h11.2M2.4 11.6h11.2" />
    </svg>
  );
}

export function Close({ size = 16 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M4 4l8 8M12 4l-8 8" />
    </svg>
  );
}

/**
 * The run's own mark: three hyphae growing out of a node, the way mycelium explores.
 *
 * Animated by `stroke-dashoffset` in CSS, one branch per delay, so it reads as reaching
 * outward rather than spinning. A spinner says "waiting"; this says "searching", which is
 * what a delegating run is actually doing.
 */
const STEM = "M8 8.6V13";
const LEFT = "M8 8.6 4.1 5.4M4.1 5.4V2.9M4.1 5.4H1.9";
const RIGHT = "M8 8.6 12.1 5.9M12.1 5.9l1.9-1.6M12.1 5.9l.5 2.3";

export function Mycelium({ size = 19, className }: IconProps) {
  return (
    <svg {...base(size)} className={className} strokeWidth={1.3}>
      {/* The faint full shape underneath, so a retracted branch reads as dormant
          rather than as a hole in the mark. */}
      <g className="dormant">
        <path d={STEM} />
        <path d={LEFT} />
        <path d={RIGHT} />
      </g>
      <path className="hypha" d={STEM} />
      <path className="hypha" d={LEFT} />
      <path className="hypha" d={RIGHT} />
      <circle cx="8" cy="8.6" r="1.25" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function Chat({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M13.5 8.5a4.5 4.5 0 0 1-4.5 4.5H5.5L2.5 15v-3.2A4.5 4.5 0 0 1 2.5 8V7a4.5 4.5 0 0 1 4.5-4.5h2A4.5 4.5 0 0 1 13.5 7Z" />
    </svg>
  );
}

export function Digest({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M3.5 2.5h6l3 3v8a1 1 0 0 1-1 1h-8a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1Z" />
      <path d="M9.5 2.5v3h3M5.5 8.5h5M5.5 11h3" />
    </svg>
  );
}

export function Bars({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M2.5 13.5h11M4.5 13.5V9M8 13.5V4M11.5 13.5V7" />
    </svg>
  );
}

export function SignOut({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <path d="M6 13.5H3.5a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1H6M10 11l3-3-3-3M13 8H6" />
    </svg>
  );
}

export function Person({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <circle cx="8" cy="5.2" r="2.6" />
      <path d="M2.9 13.6a5.1 5.1 0 0 1 10.2 0" />
    </svg>
  );
}

export function Gear({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.6v1.7M8 12.7v1.7M14.4 8h-1.7M3.3 8H1.6M12.5 3.5l-1.2 1.2M4.7 11.3l-1.2 1.2M12.5 12.5l-1.2-1.2M4.7 4.7 3.5 3.5" />
    </svg>
  );
}

export function Question({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <circle cx="8" cy="8" r="6.2" />
      <path d="M6.3 6.3a1.75 1.75 0 1 1 2.3 1.66c-.4.14-.6.5-.6.92v.3" />
      <path d="M8 11.7h.01" />
    </svg>
  );
}

export function Key({ size = 14 }: IconProps) {
  return (
    <svg {...base(size)}>
      <circle cx="5.2" cy="10.8" r="2.8" />
      <path d="M7.2 8.8 13 3m-1.7 1.7 1.4 1.4m-3 .3 1.4 1.4" />
    </svg>
  );
}
