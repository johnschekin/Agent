import { cn } from "@/lib/cn";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "default" | "blue" | "green" | "red" | "orange" | "amber" | "purple" | "cyan" | "teal";
  className?: string;
}

const variantStyles: Record<string, string> = {
  default: "bg-surface-3 text-text-secondary",
  blue: "bg-glow-blue text-accent-blue",
  green: "bg-glow-green text-accent-green",
  red: "bg-glow-red text-accent-red",
  orange: "bg-glow-amber text-accent-orange",
  amber: "bg-glow-amber text-accent-amber",
  purple: "bg-glow-purple text-accent-purple",
  cyan: "bg-glow-cyan text-accent-cyan",
  teal: "bg-glow-cyan text-accent-teal",
};

export function Badge({ children, variant = "default", className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2.5 py-0.5 rounded-[10px] text-xs font-medium",
        variantStyles[variant],
        className
      )}
    >
      {children}
    </span>
  );
}
