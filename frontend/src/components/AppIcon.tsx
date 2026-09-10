import type { CSSProperties, ReactNode, SVGProps } from "react";

export type AppIconName =
  | "launch"
  | "generate"
  | "optimize"
  | "pool"
  | "research"
  | "portfolio"
  | "check"
  | "chevron-down";

const paths: Record<AppIconName, ReactNode> = {
  launch: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
  generate: <><path d="m12 3 1.4 3.6L17 8l-3.6 1.4L12 13l-1.4-3.6L7 8l3.6-1.4L12 3Z" /><path d="m5 14 .8 2.2L8 17l-2.2.8L5 20l-.8-2.2L2 17l2.2-.8L5 14Z" /><path d="m18 14 .8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8L18 14Z" /></>,
  optimize: <><path d="M4 7h10" /><path d="M18 7h2" /><path d="M14 4v6" /><path d="M4 17h2" /><path d="M10 17h10" /><path d="M10 14v6" /></>,
  pool: <><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 8h8" /><path d="M8 12h8" /><path d="M8 16h5" /></>,
  research: <><circle cx="11" cy="11" r="6" /><path d="m16 16 4 4" /><path d="M8 12.5 10.5 10l2 2 2.5-3" /></>,
  portfolio: <><rect x="3" y="7" width="18" height="13" rx="2" /><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /><path d="M3 12h18" /><path d="M10 12v2h4v-2" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  "chevron-down": <path d="m7 10 5 5 5-5" />
};

export function AppIcon({
  name,
  size = 16,
  className = "",
  style,
  ...props
}: {
  name: AppIconName;
  size?: number;
  className?: string;
  style?: CSSProperties;
} & Omit<SVGProps<SVGSVGElement>, "name">) {
  return (
    <svg
      aria-hidden="true"
      className={`app-icon ${className}`.trim()}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
      style={style}
      {...props}
    >
      {paths[name]}
    </svg>
  );
}

export default AppIcon;
