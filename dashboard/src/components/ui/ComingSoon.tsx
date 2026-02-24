import { ViewContainer } from "@/components/layout/ViewContainer";

interface ComingSoonProps {
  title: string;
  phase?: string;
}

export function ComingSoon({ title, phase }: ComingSoonProps) {
  return (
    <ViewContainer title={title}>
      <div className="flex flex-col items-center justify-center h-64 text-center">
        <div className="text-2xl text-text-muted mb-2">Under Construction</div>
        <p className="text-sm text-text-secondary max-w-md">
          This view is planned but not yet implemented.
          {phase && (
            <span className="block mt-1 text-text-muted text-xs">
              Scheduled for {phase}
            </span>
          )}
        </p>
      </div>
    </ViewContainer>
  );
}
