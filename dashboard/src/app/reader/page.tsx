"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { Badge } from "@/components/ui/Badge";
import { LoadingState } from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { SectionTOC } from "@/components/reader/SectionTOC";
import { SectionViewer } from "@/components/reader/SectionViewer";
import { ClausePanel } from "@/components/reader/ClausePanel";
import {
  useDocuments,
  useDocument,
  useReaderSection,
  useReaderDefinitions,
  useReaderSearch,
} from "@/lib/queries";
import { formatNumber, formatCurrencyMM } from "@/lib/formatters";
import { cn, SELECT_CLASS } from "@/lib/cn";

export default function ReaderPage() {
  const [selectedDocId, setSelectedDocId] = useState<string>("");
  const [activeSectionNumber, setActiveSectionNumber] = useState<string | null>(
    null
  );
  const [selectedClauseId, setSelectedClauseId] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  // Debounce search
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    debounceRef.current = setTimeout(
      () => setDebouncedSearch(searchInput),
      300
    );
    return () => clearTimeout(debounceRef.current);
  }, [searchInput]);

  // Fetch document list for picker
  const docList = useDocuments({ cohortOnly: true, pageSize: 500 });
  const doc = useDocument(selectedDocId || null);
  const sectionDetail = useReaderSection(
    selectedDocId || null,
    activeSectionNumber
  );
  const definitions = useReaderDefinitions(selectedDocId || null);
  const searchResults = useReaderSearch(
    selectedDocId || null,
    debouncedSearch
  );

  // Sections from document metadata
  const sections = doc.data?.sections ?? [];

  // Search match section set for TOC highlighting
  const searchMatchSections = useMemo(() => {
    if (!searchResults.data?.results.length) return undefined;
    const set = new Set<string>();
    searchResults.data.results.forEach((r) => set.add(r.section_number));
    return set;
  }, [searchResults.data]);

  // Auto-select first section when document loads
  useEffect(() => {
    if (sections.length > 0 && !activeSectionNumber) {
      setActiveSectionNumber(sections[0].section_number);
    }
  }, [sections, activeSectionNumber]);

  // Reset state on document change
  const handleDocChange = useCallback((docId: string) => {
    setSelectedDocId(docId);
    setActiveSectionNumber(null);
    setSelectedClauseId(null);
    setSearchInput("");
    setDebouncedSearch("");
  }, []);

  // Reset clause selection on section change
  const handleSectionSelect = useCallback((sectionNumber: string) => {
    setActiveSectionNumber(sectionNumber);
    setSelectedClauseId(null);
  }, []);

  // Prev/Next section navigation
  const sectionIndex = useMemo(
    () =>
      activeSectionNumber
        ? sections.findIndex(
            (s) => s.section_number === activeSectionNumber
          )
        : -1,
    [sections, activeSectionNumber]
  );

  const handlePrev = useMemo(
    () =>
      sectionIndex > 0
        ? () => {
            setActiveSectionNumber(sections[sectionIndex - 1].section_number);
            setSelectedClauseId(null);
          }
        : null,
    [sectionIndex, sections]
  );

  const handleNext = useMemo(
    () =>
      sectionIndex >= 0 && sectionIndex < sections.length - 1
        ? () => {
            setActiveSectionNumber(sections[sectionIndex + 1].section_number);
            setSelectedClauseId(null);
          }
        : null,
    [sectionIndex, sections]
  );

  // Show clause panel when section has clauses
  const hasClauses = (sectionDetail.data?.clauses.length ?? 0) > 0;

  return (
    <div className="flex flex-col h-full">
      {/* Header: Document picker + metadata */}
      <div className="px-6 py-3 border-b border-border flex items-center gap-4 flex-shrink-0">
        <div className="flex items-center gap-2 flex-shrink-0">
          <label
            htmlFor="doc-picker"
            className="text-xs text-text-muted font-medium"
          >
            Document:
          </label>
          <select
            id="doc-picker"
            value={selectedDocId}
            onChange={(e) => handleDocChange(e.target.value)}
            className={cn(SELECT_CLASS, "w-[340px]")}
            aria-label="Select document"
          >
            <option value="">— Select a document —</option>
            {docList.data?.documents.map((d) => (
              <option key={d.doc_id} value={d.doc_id}>
                {d.borrower} ({d.doc_id})
              </option>
            ))}
          </select>
        </div>

        {/* Doc metadata badges */}
        {doc.data && (
          <div className="flex items-center gap-2 flex-wrap min-w-0">
            <Badge variant="blue">{doc.data.doc.doc_type}</Badge>
            <Badge variant="default">{doc.data.doc.market_segment}</Badge>
            {doc.data.doc.facility_size_mm != null && (
              <Badge variant="green">
                {formatCurrencyMM(doc.data.doc.facility_size_mm)}
              </Badge>
            )}
            <span className="text-xs text-text-muted tabular-nums">
              {formatNumber(doc.data.doc.section_count)} sections
            </span>
            <span className="text-xs text-text-muted tabular-nums">
              {formatNumber(doc.data.doc.definition_count)} defs
            </span>
            <span className="text-xs text-text-muted tabular-nums">
              {formatNumber(doc.data.doc.clause_count)} clauses
            </span>
          </div>
        )}

        {doc.isLoading && (
          <span className="text-xs text-text-muted">Loading…</span>
        )}
      </div>

      {/* Main content */}
      {!selectedDocId ? (
        <div className="flex-1 flex items-center justify-center p-8">
          <EmptyState
            title="Credit Agreement Reader"
            message="Select a document from the dropdown above to begin reading."
          />
        </div>
      ) : doc.isLoading && !doc.data ? (
        <div className="flex-1 flex items-center justify-center p-8">
          <LoadingState message="Loading document…" />
        </div>
      ) : doc.error && !doc.data ? (
        <div className="flex-1 flex items-center justify-center p-8">
          <EmptyState
            title="Failed to load document"
            message="Check the API server connection."
          />
        </div>
      ) : (
        <div className="flex-1 min-h-0 flex">
          {/* Left: Section TOC */}
          <div className="w-[280px] flex-shrink-0 border-r border-border bg-surface-secondary flex flex-col overflow-hidden">
            <SectionTOC
              sections={sections}
              activeSectionNumber={activeSectionNumber}
              onSelectSection={handleSectionSelect}
              searchQuery={searchInput}
              onSearchChange={setSearchInput}
              searchMatchSections={searchMatchSections}
              isSearching={searchResults.isFetching}
            />
          </div>

          {/* Center: Section text */}
          <div className="flex-1 min-w-0 flex flex-col bg-surface-primary overflow-hidden">
            <SectionViewer
              section={sectionDetail.data ?? null}
              isLoading={sectionDetail.isLoading}
              error={sectionDetail.error}
              definitions={definitions.data?.definitions ?? []}
              selectedClauseId={selectedClauseId}
              onSelectClause={setSelectedClauseId}
              onPrevSection={handlePrev}
              onNextSection={handleNext}
            />
          </div>

          {/* Right: Clause panel (conditional) */}
          {hasClauses && (
            <div className="w-[360px] flex-shrink-0 border-l border-border bg-surface-secondary flex flex-col overflow-hidden">
              <ClausePanel
                clauses={sectionDetail.data?.clauses ?? []}
                selectedClauseId={selectedClauseId}
                onSelectClause={setSelectedClauseId}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
