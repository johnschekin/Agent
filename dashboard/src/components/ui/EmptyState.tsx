interface EmptyStateProps {
  title?: string;
  message: string;
  action?: React.ReactNode;
}

export function EmptyState({
  title,
  message,
  action,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      {title && (
        <h3 className="text-lg font-medium text-text-primary mb-2">{title}</h3>
      )}
      <p className="text-sm text-text-secondary max-w-md">{message}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
