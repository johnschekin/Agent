"use client";

import { useCallback, useState } from "react";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge";
import { useExportLinksMutation, useImportLabelsMutation } from "@/lib/queries";

interface ExportImportDialogProps {
  open: boolean;
  onClose: () => void;
  familyFilter?: string;
}

const EXPORT_FORMATS = [
  { value: "csv", label: "CSV" },
  { value: "jsonl", label: "JSONL" },
  { value: "json", label: "JSON" },
  { value: "replay", label: "Replay (audit)" },
];

/** Parse the first N lines of a text file into row arrays (CSV or JSONL). */
function parsePreviewRows(text: string, maxRows: number): string[][] {
  const lines = text.split("\n").filter((l) => l.trim().length > 0);
  const rows: string[][] = [];
  for (let i = 0; i < Math.min(lines.length, maxRows); i++) {
    const line = lines[i];
    // Try JSON first
    try {
      const obj = JSON.parse(line);
      if (typeof obj === "object" && obj !== null && !Array.isArray(obj)) {
        rows.push(Object.values(obj).map(String));
        continue;
      }
    } catch {
      // Not JSON -- treat as CSV
    }
    // Simple CSV split (handles basic comma-separated values)
    rows.push(line.split(",").map((c) => c.trim().replace(/^"|"$/g, "")));
  }
  return rows;
}

export function ExportImportDialog({ open, onClose, familyFilter }: ExportImportDialogProps) {
  const [activeTab, setActiveTab] = useState<"export" | "import">("export");
  const [exportFormat, setExportFormat] = useState("csv");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPreviewRows, setImportPreviewRows] = useState<string[][]>([]);
  const [isDragOver, setIsDragOver] = useState(false);

  const exportMut = useExportLinksMutation();
  const importMut = useImportLabelsMutation();

  const handleExport = useCallback(() => {
    exportMut.mutate(
      { format: exportFormat, familyId: familyFilter },
      {
        onSuccess: () => {
          // The API returns a job_id; in a real implementation we'd poll for completion
          // and trigger a download. For now, we show success.
        },
      },
    );
  }, [exportFormat, familyFilter, exportMut]);

  const processFile = useCallback((file: File) => {
    setImportFile(file);
    setImportPreviewRows([]);
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result;
      if (typeof text === "string") {
        const rows = parsePreviewRows(text, 5);
        setImportPreviewRows(rows);
      }
    };
    // Read only the first 8KB for preview (enough for 5 lines)
    reader.readAsText(file.slice(0, 8192));
  }, []);

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0] ?? null;
      if (file) {
        processFile(file);
      } else {
        setImportFile(null);
        setImportPreviewRows([]);
      }
    },
    [processFile],
  );

  const handleImport = useCallback(() => {
    if (!importFile) return;
    importMut.mutate(importFile, {
      onSuccess: () => {
        setImportFile(null);
        setImportPreviewRows([]);
      },
    });
  }, [importFile, importMut]);

  // Drag-and-drop handlers
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);
      const file = e.dataTransfer.files?.[0];
      if (file) {
        processFile(file);
      }
    },
    [processFile],
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={onClose}
      data-testid="export-import-dialog"
    >
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" />
      <div
        className="relative w-full max-w-md bg-surface-1 rounded-xl shadow-overlay border border-border overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h3 className="text-sm font-semibold text-text-primary">Export / Import</h3>
          <button
            type="button"
            onClick={onClose}
            className="text-text-muted hover:text-text-primary text-lg leading-none"
            data-testid="export-import-close"
          >
            &times;
          </button>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-0 px-5 border-b border-border">
          <button
            type="button"
            onClick={() => setActiveTab("export")}
            className={cn(
              "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              activeTab === "export"
                ? "text-accent-blue border-b-accent-blue"
                : "text-text-muted hover:text-text-primary border-b-transparent",
            )}
            data-testid="export-tab"
          >
            Export
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("import")}
            className={cn(
              "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              activeTab === "import"
                ? "text-accent-blue border-b-accent-blue"
                : "text-text-muted hover:text-text-primary border-b-transparent",
            )}
            data-testid="import-tab"
          >
            Import
          </button>
        </div>

        {/* Content */}
        <div className="p-5">
          {activeTab === "export" ? (
            <div className="space-y-4">
              {/* Format selector */}
              <div>
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
                  Format
                </p>
                <div className="flex flex-wrap gap-2">
                  {EXPORT_FORMATS.map((f) => (
                    <button
                      key={f.value}
                      type="button"
                      onClick={() => setExportFormat(f.value)}
                      className={cn(
                        "px-3 py-1.5 rounded-lg text-sm transition-colors border",
                        exportFormat === f.value
                          ? "border-accent-blue bg-glow-blue text-accent-blue"
                          : "border-border text-text-secondary hover:bg-surface-2",
                      )}
                      data-testid={`export-format-${f.value}`}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Family filter indicator */}
              {familyFilter && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-text-muted">Filter:</span>
                  <Badge variant="blue">{familyFilter}</Badge>
                </div>
              )}

              {/* Export button */}
              <button
                type="button"
                onClick={handleExport}
                disabled={exportMut.isPending}
                className="w-full px-4 py-2.5 bg-accent-blue text-white text-sm font-medium rounded-lg hover:opacity-90 disabled:opacity-50"
                data-testid="export-btn"
              >
                {exportMut.isPending
                  ? "Exporting..."
                  : exportMut.isSuccess
                    ? "Export started"
                    : "Export Links"}
              </button>

              {exportMut.isError && (
                <p className="text-xs text-accent-red">
                  Export failed: {exportMut.error?.message ?? "Unknown error"}
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              {/* File upload with drag-and-drop */}
              <div>
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">
                  Upload File
                </p>
                <label
                  className={cn(
                    "flex flex-col items-center justify-center w-full h-32 border-2 border-dashed rounded-lg cursor-pointer transition-colors",
                    isDragOver
                      ? "border-accent-blue bg-glow-blue"
                      : importFile
                        ? "border-accent-blue bg-glow-blue"
                        : "border-border hover:border-text-muted hover:bg-surface-2",
                  )}
                  data-testid="import-dropzone"
                  onDragOver={handleDragOver}
                  onDragEnter={handleDragEnter}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                >
                  <input
                    type="file"
                    accept=".csv,.jsonl,.json"
                    onChange={handleFileChange}
                    className="hidden"
                    data-testid="import-file-input"
                  />
                  {importFile ? (
                    <div className="text-center">
                      <p className="text-sm text-text-primary">{importFile.name}</p>
                      <p className="text-xs text-text-muted mt-0.5">
                        {(importFile.size / 1024).toFixed(1)} KB
                      </p>
                    </div>
                  ) : isDragOver ? (
                    <div className="text-center">
                      <p className="text-sm text-accent-blue font-medium">
                        Drop file to upload
                      </p>
                    </div>
                  ) : (
                    <div className="text-center">
                      <p className="text-sm text-text-secondary">
                        Drop file here or click to browse
                      </p>
                      <p className="text-xs text-text-muted mt-0.5">
                        CSV, JSONL, or JSON
                      </p>
                    </div>
                  )}
                </label>
              </div>

              {/* Import preview table */}
              {importPreviewRows.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-1">
                    Preview ({importPreviewRows.length} rows)
                  </p>
                  <div className="overflow-x-auto max-h-36 border border-border rounded-lg">
                    <table
                      className="w-full border-collapse text-xs"
                      data-testid="import-preview-table"
                    >
                      <tbody>
                        {importPreviewRows.map((row, idx) => (
                          <tr
                            key={idx}
                            className="border-b border-border/30 last:border-b-0"
                            data-testid={`import-preview-row-${idx}`}
                          >
                            {row.map((cell, ci) => (
                              <td
                                key={ci}
                                className="px-2 py-1 text-text-secondary truncate max-w-[120px]"
                              >
                                {cell}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Import button */}
              <button
                type="button"
                onClick={handleImport}
                disabled={!importFile || importMut.isPending}
                className="w-full px-4 py-2.5 bg-accent-blue text-white text-sm font-medium rounded-lg hover:opacity-90 disabled:opacity-50"
                data-testid="import-btn"
              >
                {importMut.isPending
                  ? "Importing..."
                  : importMut.isSuccess
                    ? "Import complete"
                    : "Import Links"}
              </button>

              {importMut.isError && (
                <p className="text-xs text-accent-red">
                  Import failed: {importMut.error?.message ?? "Unknown error"}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
