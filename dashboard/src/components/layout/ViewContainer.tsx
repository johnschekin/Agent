import type { ReactNode } from "react";

interface ViewContainerProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}

export function ViewContainer({
  title,
  subtitle,
  actions,
  children,
}: ViewContainerProps) {
  return (
    <div className="flex flex-col h-full bg-canvas">
      <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-surface-1">
        <div>
          <h2 className="text-xl font-semibold text-text-primary">{title}</h2>
          {subtitle && (
            <p className="text-sm text-text-secondary mt-0.5">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      <div className="flex-1 overflow-auto p-6">{children}</div>
    </div>
  );
}
