"use client";

interface MetadataItem {
  label: string;
  value: string | number | boolean | null | undefined;
}

interface MetadataGridProps {
  items: MetadataItem[];
}

export function MetadataGrid({ items }: MetadataGridProps) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-2">
      {items.map((item) => (
        <div key={item.label}>
          <dt className="text-[11px] text-text-muted uppercase tracking-wide">
            {item.label}
          </dt>
          <dd className="text-sm text-text-primary truncate" title={String(item.value ?? "—")}>
            {item.value === true
              ? "Yes"
              : item.value === false
                ? "No"
                : item.value != null
                  ? String(item.value)
                  : "—"}
          </dd>
        </div>
      ))}
    </div>
  );
}
