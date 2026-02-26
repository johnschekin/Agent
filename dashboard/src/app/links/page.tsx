"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { cn } from "@/lib/cn";
import {
  useLinks,
  useLinkSummary,
  useOntologyTree,
  useUnlinkMutation,
  useRelinkMutation,
  useBookmarkMutation,
  useAddNoteMutation,
  useDeferMutation,
  useBatchUnlinkMutation,
  useBatchRelinkMutation,
  useBatchBookmarkMutation,
  useUndoMutation,
  useRedoMutation,
  useLinkRuns,
  useCreateSessionMutation,
  useUpdateCursorMutation,
  useAddReviewMarkMutation,
  useClaimSessionBatchMutation,
  useSession,
  useContextStrip,
  useComparables,
  useWhyMatched,
  useCoverageGaps,
  useConflicts,
  useConflictPolicies,
  useValidateDslMutation,
  useUpdateRuleMutation,
  useQueryCountWithMeta,
  usePreviewCandidates,
  useCreatePreviewFromAstMutation,
  useUpdateVerdictsMutation,
  useApplyPreviewMutation,
  useCanaryApplyMutation,
  useSaveAsRuleMutation,
  useCounterfactualMutation,
  useLinkRules,
  useLinkRule,
  useSemanticCandidates,
  useReaderSection,
  useReaderDefinitions,
  usePublishRuleMutation,
  useArchiveRuleMutation,
  useStarterKit,
  useCloneRuleMutation,
  useDeleteRuleMutation,
  useSubmitLinkJobMutation,
} from "@/lib/queries";
import type {
  FamilyLink,
  LinkStatus,
  ConfidenceTier,
  LinkRole,
  FilterExpressionNode,
  CoverageGap,
  ConflictGroup,
  PreviewCandidate,
  OntologyTreeNode,
} from "@/lib/types";
import { KpiCard, KpiCardGrid } from "@/components/ui/KpiCard";
import { SkeletonTableRows, SkeletonPanel } from "@/components/ui/Spinner";
import { Badge } from "@/components/ui/Badge";
import { ReviewPane } from "@/components/links/ReviewPane";
import { BatchActionBar } from "@/components/links/BatchActionBar";
import { KeyboardHelpBar } from "@/components/links/KeyboardHelpBar";
import { SessionProgressBar } from "@/components/links/SessionProgressBar";
import { FocusModeToggle } from "@/components/links/FocusModeToggle";
import { DetachableReader } from "@/components/links/DetachableReader";
import { ReassignDialog } from "@/components/links/ReassignDialog";
import { WhyMatchedPopover } from "@/components/links/WhyMatchedPopover";
import { TextQueryBar } from "@/components/links/TextQueryBar";
import { WhyNotMatchedPanel } from "@/components/links/WhyNotMatchedPanel";
import { ConflictResolver } from "@/components/links/ConflictResolver";
import { CompoundCovenantOverlay } from "@/components/links/CompoundCovenantOverlay";
import { UnlinkReasonDialog } from "@/components/links/UnlinkReasonDialog";
import { CommandPalette, type CommandPaletteTarget } from "@/components/links/CommandPalette";
import { TriageMode } from "@/components/links/TriageMode";
import { RuleCompareView } from "@/components/links/RuleCompareView";
import { StarterKitPanel } from "@/components/links/StarterKitPanel";
import { BatchRunDashboard } from "@/components/links/BatchRunDashboard";
import { ExportImportDialog } from "@/components/links/ExportImportDialog";
import { tokenizeDsl, DSL_TOKEN_CLASSES } from "@/lib/rule-dsl-highlight";
import { DslCheatSheet } from "@/components/links/DslCheatSheet";
import { OntologyIntelligencePanel } from "@/components/links/OntologyIntelligencePanel";
import { DataTable } from "@/components/tables/DataTable";
import { OntologyTree } from "@/components/ontology/OntologyTree";

// ── Tab definitions ────────────────────────────────────────────────────────

type TabId = "review" | "query" | "rules" | "dashboard" | "coverage" | "conflicts";

interface TabDef {
  id: TabId;
  label: string;
}

const TABS: TabDef[] = [
  { id: "coverage", label: "Coverage" },
  { id: "conflicts", label: "Conflicts" },
  { id: "review", label: "Review" },
  { id: "query", label: "Query" },
  { id: "rules", label: "Rules" },
  { id: "dashboard", label: "Dashboard" },
];

const PRIMARY_TABS: TabDef[] = [
  { id: "review", label: "Review" },
  { id: "query", label: "Query" },
  { id: "rules", label: "Rules" },
  { id: "dashboard", label: "Dashboard" },
];

// ── Confidence tier filter values ──────────────────────────────────────────

const TIER_CYCLE: (ConfidenceTier | "all")[] = ["all", "high", "medium", "low"];

// ── Status filter chips ────────────────────────────────────────────────────

const STATUS_FILTERS: { value: LinkStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "pending_review", label: "Pending Review" },
  { value: "unlinked", label: "Unlinked" },
];

type ReviewColumnId =
  | "doc"
  | "section"
  | "heading"
  | "scope"
  | "confidence"
  | "status"
  | "actions";

const REVIEW_COLUMN_LABELS: Record<ReviewColumnId, string> = {
  doc: "Doc",
  section: "Section",
  heading: "Heading",
  scope: "Scope",
  confidence: "Confidence",
  status: "Status",
  actions: "Actions",
};

const DEFAULT_REVIEW_COLUMNS: Record<ReviewColumnId, boolean> = {
  doc: true,
  section: true,
  heading: true,
  scope: true,
  confidence: true,
  status: true,
  actions: true,
};

type QueryColumnId = "borrower" | "section" | "heading" | "confidence" | "tier" | "verdict";

const QUERY_COLUMN_LABELS: Record<QueryColumnId, string> = {
  borrower: "Borrower",
  section: "Section",
  heading: "Heading",
  confidence: "Confidence",
  tier: "Tier",
  verdict: "Verdict",
};

const DEFAULT_QUERY_COLUMNS: Record<QueryColumnId, boolean> = {
  borrower: true,
  section: true,
  heading: true,
  confidence: true,
  tier: true,
  verdict: true,
};

// ── Role badge variant map ─────────────────────────────────────────────────

const ROLE_BADGE_VARIANT: Record<LinkRole, "default" | "blue" | "cyan" | "default"> = {
  primary_covenant: "default",
  definitions_support: "blue",
  secondary_signal: "default",
  xref_support: "cyan",
};

const LAST_SESSION_STORAGE_KEY = "links:last-session-id";
const LAST_CURSOR_STORAGE_KEY = "links:last-cursor-id";

// ── Page component ─────────────────────────────────────────────────────────

export default function LinksPage() {
  return (
    <Suspense fallback={<LinksPageFallback />}>
      <LinksPageInner />
    </Suspense>
  );
}

function LinksPageFallback() {
  return (
    <div className="h-screen flex items-center justify-center bg-canvas">
      <div className="text-sm text-text-muted animate-pulse">Loading links...</div>
    </div>
  );
}

function canonicalFamilyToken(value?: string | null): string {
  const raw = String(value ?? "").trim().toLowerCase();
  if (!raw) return "";
  const stripped = raw
    .replace(/^fam[-_.]/, "")
    .replace(/[^a-z0-9]+/g, ".")
    .replace(/\.+/g, ".")
    .replace(/^\./, "")
    .replace(/\.$/, "");
  if (!stripped) return "";
  const parts = stripped.split(".").filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : stripped;
}

function formatSectionWithClause(
  sectionNumber: string,
  clausePath?: string | null,
  clauseLabel?: string | null,
): string {
  const section = String(sectionNumber || "").trim();
  const rawPath = String(clausePath || "").trim();
  if (rawPath) {
    // Convert canonical clause path (e.g., "a.iii.A") into display form "(a)(iii)(A)".
    // Keep fallback behavior for path strings that already include bracket labels.
    if (rawPath.includes("(") || rawPath.includes("[")) {
      return `${section}${rawPath}`;
    }
    const pathText = rawPath
      .split(".")
      .filter(Boolean)
      .map((part) => part.replace(/_dup\d+$/i, ""))
      .filter(Boolean)
      .map((part) => `(${part})`)
      .join("");
    if (pathText) {
      return `${section}${pathText}`;
    }
  }

  const rawLabel = String(clauseLabel || "").trim();
  if (!rawLabel) return section;
  if (rawLabel.startsWith("(") || rawLabel.startsWith("[") || rawLabel.startsWith(".")) {
    return `${section}${rawLabel}`;
  }
  return `${section}.${rawLabel}`;
}

function collectAstMatchValues(node: unknown, values: Set<string>): void {
  if (!node || typeof node !== "object") return;
  const raw = node as Record<string, unknown>;
  const value = raw.value;
  if (typeof value === "string" && value.trim()) {
    values.add(value.trim());
  }
  const children = raw.children;
  if (Array.isArray(children)) {
    for (const child of children) {
      collectAstMatchValues(child, values);
    }
  }
}

function LinksPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();

  // Tab state
  const pathTab: TabId | null = pathname.endsWith("/coverage")
    ? "coverage"
    : pathname.endsWith("/conflicts")
      ? "conflicts"
      : null;
  const rawTab = searchParams.get("tab") ?? pathTab;
  const activeTab = (TABS.some((tab) => tab.id === rawTab) ? rawTab : "review") as TabId;
  const setActiveTab = useCallback(
    (tab: TabId) => {
      if (tab === "coverage") {
        router.push("/links/coverage");
        return;
      }
      if (tab === "conflicts") {
        router.push("/links/conflicts");
        return;
      }
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", tab);
      router.push(`/links?${params.toString()}`);
    },
    [router, searchParams],
  );

  // Cross-tab: load a rule into the query tab
  const loadRuleId = searchParams.get("loadRuleId") || undefined;

  // Filter state
  const [familyFilter, setFamilyFilter] = useState<string | undefined>();
  const [ontologySearch, setOntologySearch] = useState("");
  const [selectedTreeNodeId, setSelectedTreeNodeId] = useState<string | null>(null);
  const [ontologyPanelOpen, setOntologyPanelOpen] = useState(true);
  const [ontologyPanelPinned, setOntologyPanelPinned] = useState(true);
  const [statusFilter, setStatusFilter] = useState<LinkStatus | "all">("all");
  const [tierFilter, setTierFilter] = useState<ConfidenceTier | "all">("all");
  const [sortBy, setSortBy] = useState<"created_at" | "confidence">("created_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);

  const openRuleInQuery = useCallback(
    (ruleId: string, scopeId?: string) => {
      if (scopeId) setFamilyFilter(scopeId);
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", "query");
      params.set("loadRuleId", ruleId);
      router.push(`/links?${params.toString()}`);
    },
    [router, searchParams],
  );

  // Selection state
  const [focusedIdx, setFocusedIdx] = useState(0);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [lastSelectedIdx, setLastSelectedIdx] = useState<number | null>(null);

  // UI state
  const [readerOpen, setReaderOpen] = useState(false);
  const [detachedReader, setDetachedReader] = useState(false);
  const [focusMode, setFocusMode] = useState(false);
  const [folded, setFolded] = useState(false);
  const [redlineActive, setRedlineActive] = useState(false);
  const [noteInputLinkId, setNoteInputLinkId] = useState<string | null>(null);
  const [noteText, setNoteText] = useState("");
  const [reassignLinkId, setReassignLinkId] = useState<string | null>(null);
  const [unlinkDialogLinkId, setUnlinkDialogLinkId] = useState<string | null>(null);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [triageActive, setTriageActive] = useState(false);
  const [exportDialogOpen, setExportDialogOpen] = useState(false);
  const [intelligencePanelOpen, setIntelligencePanelOpen] = useState(true);
  const [rulesCompareRequestId, setRulesCompareRequestId] = useState(0);
  const [claimedLinkIds, setClaimedLinkIds] = useState<Set<string> | null>(null);
  const [resumeCursorLinkId, setResumeCursorLinkId] = useState<string | null>(null);
  const [resumePromptOpen, setResumePromptOpen] = useState(false);
  const [sessionBootstrapped, setSessionBootstrapped] = useState(false);
  const noteInputRef = useRef<HTMLInputElement>(null!);  // eslint-disable-line @typescript-eslint/no-non-null-assertion

  // Session state
  const [sessionId, setSessionId] = useState<string | null>(null);
  const createSessionMut = useCreateSessionMutation();
  const updateCursorMut = useUpdateCursorMutation();
  const addReviewMarkMut = useAddReviewMarkMutation();
  const claimBatchMut = useClaimSessionBatchMutation();
  const submitJobMut = useSubmitLinkJobMutation();
  const sessionQuery = useSession(sessionId);
  const sessionData = sessionQuery.data;
  const { data: paletteRulesData } = useLinkRules({ familyId: familyFilter });

  // Data fetching
  const linksQuery = useLinks({
    familyId: familyFilter,
    status: statusFilter === "all" ? undefined : statusFilter,
    confidenceTier: tierFilter === "all" ? undefined : tierFilter,
    sortBy,
    sortDir,
    page,
    pageSize: 50,
  });
  const summaryQuery = useLinkSummary();
  const ontologyTreeQuery = useOntologyTree();

  // Mutations
  const unlinkMut = useUnlinkMutation();
  const relinkMut = useRelinkMutation();
  const bookmarkMut = useBookmarkMutation();
  const addNoteMut = useAddNoteMutation();
  const deferMut = useDeferMutation();
  const batchUnlinkMut = useBatchUnlinkMutation();
  const batchRelinkMut = useBatchRelinkMutation();
  const batchBookmarkMut = useBatchBookmarkMutation();
  const undoMut = useUndoMutation();
  const redoMut = useRedoMutation();

  const links = linksQuery.data?.links ?? [];
  const displayedLinks = useMemo(
    () =>
      claimedLinkIds && claimedLinkIds.size > 0
        ? links.filter((link) => claimedLinkIds.has(link.link_id))
        : links,
    [links, claimedLinkIds],
  );
  const totalLinks = linksQuery.data?.total ?? 0;
  const summary = summaryQuery.data;

  // Derive families: link store families first (authoritative IDs), then
  // ontology families that aren't yet in the link store.
  const allFamilies = useMemo(() => {
    const linkFamilies = summary?.by_family ?? [];
    const seen = new Set(linkFamilies.map((f) => f.family_id));

    const ontologyExtras: { family_id: string; family_name: string; count: number; pending: number }[] = [];
    for (const domain of ontologyTreeQuery.data?.roots ?? []) {
      for (const child of domain.children ?? []) {
        if (child.type === "family" && !seen.has(child.id)) {
          ontologyExtras.push({ family_id: child.id, family_name: child.name, count: 0, pending: 0 });
        }
      }
    }
    return [...linkFamilies, ...ontologyExtras];
  }, [summary, ontologyTreeQuery.data]);

  const ontologyNodeById = useMemo(() => {
    const map = new Map<string, OntologyTreeNode>();
    const stack: OntologyTreeNode[] = [...(ontologyTreeQuery.data?.roots ?? [])];
    while (stack.length > 0) {
      const node = stack.pop()!;
      map.set(node.id, node);
      for (const child of node.children ?? []) {
        stack.push(child);
      }
    }
    return map;
  }, [ontologyTreeQuery.data]);

  const ontologyParentById = useMemo(() => {
    const map = new Map<string, string>();
    const walk = (nodes: OntologyTreeNode[], parentId: string | null) => {
      for (const node of nodes) {
        if (parentId) map.set(node.id, parentId);
        walk(node.children ?? [], node.id);
      }
    };
    walk(ontologyTreeQuery.data?.roots ?? [], null);
    return map;
  }, [ontologyTreeQuery.data]);

  const selectedOntologyNode = selectedTreeNodeId
    ? ontologyNodeById.get(selectedTreeNodeId) ?? null
    : null;

  const selectedScopeNode = useMemo(() => {
    if (selectedOntologyNode) return selectedOntologyNode;
    if (familyFilter) return ontologyNodeById.get(familyFilter) ?? null;
    return null;
  }, [selectedOntologyNode, familyFilter, ontologyNodeById]);

  const selectedScopeSummary = useMemo(
    () => (familyFilter ? allFamilies.find((f) => f.family_id === familyFilter) ?? null : null),
    [allFamilies, familyFilter],
  );
  const showIntelligencePanel = activeTab === "review" || activeTab === "query" || activeTab === "dashboard";
  const intelligenceScopeId = familyFilter ?? selectedTreeNodeId ?? undefined;

  const queryParentFamilyId = useMemo(() => {
    if (selectedTreeNodeId) {
      const selected = ontologyNodeById.get(selectedTreeNodeId);
      if (selected?.type === "family") return undefined;
      let cursor = ontologyParentById.get(selectedTreeNodeId) ?? null;
      while (cursor) {
        const ancestor = ontologyNodeById.get(cursor);
        if (ancestor?.type === "family") return ancestor.id;
        cursor = ontologyParentById.get(cursor) ?? null;
      }
      return undefined;
    }
    if (familyFilter && familyFilter.includes(".")) {
      const parts = familyFilter.split(".");
      if (parts.length > 1) return parts.slice(0, -1).join(".");
    }
    return undefined;
  }, [selectedTreeNodeId, ontologyParentById, ontologyNodeById, familyFilter]);

  useEffect(() => {
    if (!familyFilter) return;
    if (!selectedTreeNodeId) {
      if (ontologyNodeById.has(familyFilter)) setSelectedTreeNodeId(familyFilter);
      return;
    }
    const selected = ontologyNodeById.get(selectedTreeNodeId);
    const selectedScopeId = selected?.id;
    if (selectedScopeId !== familyFilter && ontologyNodeById.has(familyFilter)) {
      setSelectedTreeNodeId(familyFilter);
    }
  }, [familyFilter, selectedTreeNodeId, ontologyNodeById]);

  const handleOntologySelect = useCallback(
    (nodeId: string) => {
      setSelectedTreeNodeId(nodeId);
      const node = ontologyNodeById.get(nodeId);
      if (!node) return;
      setFamilyFilter(node.id);
      if (!ontologyPanelPinned) {
        setOntologyPanelOpen(false);
      }
      setPage(1);
    },
    [ontologyNodeById, ontologyPanelPinned],
  );

  useEffect(() => {
    if (ontologyPanelPinned) setOntologyPanelOpen(true);
  }, [ontologyPanelPinned]);

  const focusedLink = displayedLinks[focusedIdx] ?? null;

  // Ensure focused index stays in bounds
  useEffect(() => {
    if (focusedIdx >= displayedLinks.length && displayedLinks.length > 0) {
      setFocusedIdx(displayedLinks.length - 1);
    }
  }, [displayedLinks.length, focusedIdx]);

  // Bootstrap session from localStorage once per mount.
  useEffect(() => {
    if (sessionBootstrapped) return;
    const stored = typeof window !== "undefined" ? window.localStorage.getItem(LAST_SESSION_STORAGE_KEY) : null;
    if (stored) {
      setSessionId(stored);
      setSessionBootstrapped(true);
      return;
    }
    if (!sessionId) {
      setSessionBootstrapped(true);
      createSessionMut.mutate(familyFilter, {
        onSuccess: (data) => {
          setSessionId(data.session.session_id);
          if (typeof window !== "undefined") {
            window.localStorage.setItem(LAST_SESSION_STORAGE_KEY, data.session.session_id);
          }
        },
      });
      return;
    }
    setSessionBootstrapped(true);
  }, [sessionBootstrapped, sessionId, createSessionMut, familyFilter]);

  // Persist session id for resume on refresh.
  useEffect(() => {
    if (!sessionId || typeof window === "undefined") return;
    window.localStorage.setItem(LAST_SESSION_STORAGE_KEY, sessionId);
  }, [sessionId]);

  // Fallback when restored session is stale/missing.
  useEffect(() => {
    if (!sessionBootstrapped || sessionId || createSessionMut.isPending) return;
    createSessionMut.mutate(familyFilter, {
      onSuccess: (data) => {
        setSessionId(data.session.session_id);
        if (typeof window !== "undefined") {
          window.localStorage.setItem(LAST_SESSION_STORAGE_KEY, data.session.session_id);
        }
      },
    });
  }, [sessionBootstrapped, sessionId, createSessionMut, familyFilter]);

  useEffect(() => {
    if (!sessionId || !sessionQuery.isError) return;
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(LAST_SESSION_STORAGE_KEY);
    }
    setSessionId(null);
    setSessionBootstrapped(false);
  }, [sessionId, sessionQuery.isError]);

  // Update session cursor when focus changes
  useEffect(() => {
    if (sessionId && focusedLink) {
      updateCursorMut.mutate({
        sessionId,
        cursor: focusedLink.link_id,
      });
      if (typeof window !== "undefined") {
        window.localStorage.setItem(LAST_CURSOR_STORAGE_KEY, focusedLink.link_id);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, focusedLink?.link_id]);

  // Resume prompt from saved server cursor (or local fallback).
  useEffect(() => {
    if (!sessionData || displayedLinks.length === 0) return;
    const cursorFromSession =
      typeof sessionData.session.last_cursor === "string" && sessionData.session.last_cursor
        ? sessionData.session.last_cursor
        : null;
    const cursorFromLocal =
      typeof window !== "undefined" ? window.localStorage.getItem(LAST_CURSOR_STORAGE_KEY) : null;
    const candidateCursor = cursorFromSession ?? cursorFromLocal;
    if (!candidateCursor || candidateCursor === resumeCursorLinkId) return;
    const idx = displayedLinks.findIndex((link) => link.link_id === candidateCursor);
    if (idx > 0 && idx !== focusedIdx) {
      setResumeCursorLinkId(candidateCursor);
      setResumePromptOpen(true);
    }
  }, [sessionData, displayedLinks, focusedIdx, resumeCursorLinkId]);

  useEffect(() => {
    setResumeCursorLinkId(null);
    setResumePromptOpen(false);
  }, [sessionId]);

  // ── Action helpers ─────────────────────────────────────────────────────

  const recordMark = useCallback(
    (linkId: string, action: string, reason?: string) => {
      if (sessionId) {
        addReviewMarkMut.mutate({
          sessionId,
          data: { link_id: linkId, action, reason },
        });
      }
    },
    [sessionId, addReviewMarkMut]
  );

  const advanceFocus = useCallback(() => {
    setFocusedIdx((prev) => Math.min(prev + 1, displayedLinks.length - 1));
  }, [displayedLinks.length]);

  const handleUnlink = useCallback(
    (linkId: string, reason: string) => {
      unlinkMut.mutate({ linkId, reason });
      recordMark(linkId, "unlinked", reason);
    },
    [unlinkMut, recordMark]
  );

  const handleRelink = useCallback(
    (linkId: string) => {
      relinkMut.mutate(linkId);
      recordMark(linkId, "relinked");
    },
    [relinkMut, recordMark]
  );

  const handleBookmark = useCallback(
    (linkId: string) => {
      bookmarkMut.mutate(linkId);
      recordMark(linkId, "bookmarked");
    },
    [bookmarkMut, recordMark]
  );

  // Command palette navigation handler
  const handlePaletteNavigate = useCallback(
    (target: CommandPaletteTarget) => {
      if (target.type === "tab") {
        setActiveTab(target.id as TabId);
      } else if (target.type === "family") {
        setFamilyFilter(target.id);
        setActiveTab("review");
        setPage(1);
      } else if (target.type === "rule") {
        setActiveTab("rules");
      } else if (target.type === "action") {
        switch (target.id) {
          case "preview-links":
            setActiveTab("query");
            break;
          case "apply-high-tier":
            setActiveTab("review");
            setTierFilter("high");
            setPage(1);
            break;
          case "unlink-selected":
            if (selectedIds.size > 0) {
              batchUnlinkMut.mutate({
                linkIds: Array.from(selectedIds),
                reason: "palette_unlink_selected",
              });
              setSelectedIds(new Set());
            }
            break;
          case "compare-rules":
            setActiveTab("rules");
            setRulesCompareRequestId((prev) => prev + 1);
            break;
          case "run-all-rules":
            submitJobMut.mutate({ job_type: "batch_run", params: {} });
            setActiveTab("dashboard");
            break;
          case "export-view":
            setActiveTab("dashboard");
            setExportDialogOpen(true);
            break;
        }
      }
    },
    [setActiveTab, selectedIds, batchUnlinkMut, submitJobMut],
  );

  // ── Keyboard handler ──────────────────────────────────────────────────

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;

      // Global: Cmd+K opens command palette
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCommandPaletteOpen((prev) => !prev);
        return;
      }

      // Global: Cmd+F toggles triage mode (only on review tab)
      if ((e.metaKey || e.ctrlKey) && e.key === "f" && !e.shiftKey && activeTab === "review") {
        e.preventDefault();
        setTriageActive((prev) => !prev);
        return;
      }

      // Triage mode owns the keyboard while open.
      if (triageActive) return;

      // Query tab: `/` focuses the text query bar from anywhere
      if (activeTab === "query" && e.key === "/" && target.tagName !== "INPUT" && target.tagName !== "TEXTAREA") {
        e.preventDefault();
        const bar = document.querySelector("[data-testid='text-query-bar']") as HTMLElement & { focusInput?: () => void } | null;
        if (bar?.focusInput) bar.focusInput();
        else bar?.querySelector("input")?.focus();
        return;
      }

      // Only process remaining review shortcuts when on review tab
      if (activeTab !== "review") return;

      // Disable shortcuts when in input/textarea
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        return;
      }

      const link = displayedLinks[focusedIdx];
      if (!link && !["j", "k", "ArrowDown", "ArrowUp"].includes(e.key)) return;

      switch (e.key) {
        // Navigation
        case "j":
        case "ArrowDown":
          e.preventDefault();
          if (e.shiftKey) {
            // Block select: select current and move down
            if (link) {
              setSelectedIds((prev) => new Set(prev).add(link.link_id));
              setLastSelectedIdx(focusedIdx);
            }
            setFocusedIdx((prev) => Math.min(prev + 1, displayedLinks.length - 1));
          } else {
            setFocusedIdx((prev) => Math.min(prev + 1, displayedLinks.length - 1));
          }
          break;

        case "k":
        case "ArrowUp":
          e.preventDefault();
          if (e.shiftKey) {
            if (link) {
              setSelectedIds((prev) => new Set(prev).add(link.link_id));
              setLastSelectedIdx(focusedIdx);
            }
            setFocusedIdx((prev) => Math.max(prev - 1, 0));
          } else {
            setFocusedIdx((prev) => Math.max(prev - 1, 0));
          }
          break;

        // Jump to next/prev pending_review or low-confidence
        case "[":
          e.preventDefault();
          for (let i = focusedIdx + 1; i < displayedLinks.length; i++) {
            if (displayedLinks[i].status === "pending_review" || displayedLinks[i].confidence_tier === "low") {
              setFocusedIdx(i);
              break;
            }
          }
          break;

        case "]":
          e.preventDefault();
          for (let i = focusedIdx - 1; i >= 0; i--) {
            if (displayedLinks[i].status === "pending_review" || displayedLinks[i].confidence_tier === "low") {
              setFocusedIdx(i);
              break;
            }
          }
          break;

        // Toggle selection
        case "x":
          e.preventDefault();
          if (link) {
            setSelectedIds((prev) => {
              const next = new Set(prev);
              if (next.has(link.link_id)) next.delete(link.link_id);
              else next.add(link.link_id);
              return next;
            });
          }
          break;

        // Reader pane
        case " ":
          e.preventDefault();
          if (e.shiftKey) {
            // Approve + advance
            if (link) {
              recordMark(link.link_id, "reviewed");
              advanceFocus();
            }
          } else {
            setReaderOpen((prev) => !prev);
          }
          break;

        case "Backspace":
          if (e.shiftKey) {
            e.preventDefault();
            // Reject as false_positive + advance
            if (link) {
              handleUnlink(link.link_id, "false_positive");
              advanceFocus();
            }
          }
          break;

        // Actions
        case "u":
          e.preventDefault();
          if (e.shiftKey) {
            // Batch unlink selected
            if (selectedIds.size > 0) {
              batchUnlinkMut.mutate({
                linkIds: Array.from(selectedIds),
                reason: "batch_unlink",
              });
              setSelectedIds(new Set());
            }
          } else if (link) {
            setUnlinkDialogLinkId(link.link_id);
          }
          break;

        case "r":
          e.preventDefault();
          if (link) handleRelink(link.link_id);
          break;

        case "b":
          e.preventDefault();
          if (e.shiftKey) {
            // Bookmark + advance
            if (link) {
              handleBookmark(link.link_id);
              advanceFocus();
            }
          } else if (link) {
            handleBookmark(link.link_id);
          }
          break;

        case "n":
          e.preventDefault();
          if (link) {
            setNoteInputLinkId(link.link_id);
            setNoteText("");
            setTimeout(() => noteInputRef.current?.focus(), 50);
          }
          break;

        case "p":
          e.preventDefault();
          if (link) {
            if (e.shiftKey) {
              recordMark(link.link_id, "pinned_tn");
            } else {
              recordMark(link.link_id, "pinned_tp");
            }
          }
          break;

        case "d":
          if (e.shiftKey) {
            e.preventDefault();
            // Defer + advance
            if (link) {
              deferMut.mutate(link.link_id);
              recordMark(link.link_id, "deferred");
              advanceFocus();
            }
          } else {
            e.preventDefault();
            setRedlineActive((prev) => !prev);
          }
          break;

        case "m":
          e.preventDefault();
          if (link) {
            setReassignLinkId(link.link_id);
          }
          break;

        case "c":
          e.preventDefault();
          setActiveTab("query");
          break;

        case "f":
        case "F":
          if ((e.metaKey || e.ctrlKey) && e.shiftKey) {
            e.preventDefault();
            setFocusMode((prev) => !prev);
          } else {
            e.preventDefault();
            setFolded((prev) => !prev);
          }
          break;

        case "t":
          e.preventDefault();
          setTierFilter((prev) => {
            const idx = TIER_CYCLE.indexOf(prev);
            return TIER_CYCLE[(idx + 1) % TIER_CYCLE.length];
          });
          setPage(1);
          break;

        case "Enter":
          e.preventDefault();
          if (e.shiftKey) {
            // Open in current tab
            if (link) {
              router.push(`/reader?doc_id=${link.doc_id}&section=${link.section_number}`);
            }
          } else {
            // Open in new tab
            if (link) {
              window.open(
                `/reader?doc_id=${link.doc_id}&section=${link.section_number}`,
                "_blank"
              );
            }
          }
          break;

        case "z":
          if (e.metaKey || e.ctrlKey) {
            e.preventDefault();
            if (e.shiftKey) {
              redoMut.mutate();
            } else {
              undoMut.mutate();
            }
          }
          break;

        case "U":
          if (e.metaKey || e.ctrlKey) {
            e.preventDefault();
            setDetachedReader(true);
          }
          break;
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    activeTab, displayedLinks, focusedIdx, selectedIds, sessionId, triageActive,
    handleUnlink, handleRelink, handleBookmark, recordMark, advanceFocus,
    batchUnlinkMut, deferMut, undoMut, redoMut, router, setActiveTab,
  ]);

  // Handle note submission
  const submitNote = useCallback(() => {
    if (noteInputLinkId && noteText.trim()) {
      addNoteMut.mutate({ linkId: noteInputLinkId, note: noteText.trim() });
      recordMark(noteInputLinkId, "noted");
    }
    setNoteInputLinkId(null);
    setNoteText("");
  }, [noteInputLinkId, noteText, addNoteMut, recordMark]);

  const toggleConfidenceSort = useCallback(() => {
    setPage(1);
    setSortBy((prevSortBy) => {
      if (prevSortBy !== "confidence") {
        setSortDir("desc");
        return "confidence";
      }
      setSortDir((prevSortDir) => (prevSortDir === "desc" ? "asc" : "desc"));
      return prevSortBy;
    });
  }, []);

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-screen bg-canvas">
      {/* Header */}
      {!focusMode && (
        <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-surface-1">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">Ontology Links</h1>
            <p className="text-sm text-text-secondary mt-0.5">
              Section and clause linking to ontology scopes and review
            </p>
          </div>
          <div className="flex items-center gap-3">
            {sessionData && activeTab === "review" && (
              <SessionProgressBar
                totalReviewed={sessionData.session.total_reviewed}
                totalLinks={sessionData.session.total_links}
                unlinked={sessionData.session.total_unlinked}
                bookmarked={sessionData.session.total_bookmarked}
              />
            )}
            {activeTab === "review" && sessionId && (
              <button
                type="button"
                onClick={() => {
                  claimBatchMut.mutate(
                    { sessionId, batchSize: 50 },
                    {
                      onSuccess: (result) => {
                        const claimed = Array.isArray(result.claimed) ? result.claimed : [];
                        setClaimedLinkIds(new Set(claimed.map((id) => String(id))));
                        if (claimed.length > 0) setFocusedIdx(0);
                      },
                    },
                  );
                }}
                disabled={claimBatchMut.isPending}
                className="px-3 py-1.5 bg-surface-2 text-text-secondary text-xs rounded-lg hover:text-text-primary transition-colors disabled:opacity-50"
              >
                {claimBatchMut.isPending ? "Claiming..." : "Claim Batch"}
              </button>
            )}
            {activeTab === "review" && claimedLinkIds && claimedLinkIds.size > 0 && (
              <button
                type="button"
                onClick={() => setClaimedLinkIds(null)}
                className="px-2 py-1 text-[11px] rounded bg-glow-blue text-accent-blue"
                title="Show full queue"
              >
                Batch: {claimedLinkIds.size}
              </button>
            )}
            <FocusModeToggle active={focusMode} onToggle={() => setFocusMode((p) => !p)} />
          </div>
        </div>
      )}

      {!focusMode && activeTab === "review" && resumePromptOpen && resumeCursorLinkId && (
        <div className="flex items-center justify-between gap-2 px-6 py-2 border-b border-border bg-surface-2">
          <p className="text-xs text-text-secondary">
            Resume from row{" "}
            <span className="text-text-primary font-medium">
              {Math.max(1, displayedLinks.findIndex((link) => link.link_id === resumeCursorLinkId) + 1)}
            </span>
            ?
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                const idx = displayedLinks.findIndex((link) => link.link_id === resumeCursorLinkId);
                if (idx >= 0) setFocusedIdx(idx);
                setResumePromptOpen(false);
              }}
              className="px-2.5 py-1 text-xs rounded bg-accent-blue text-white"
            >
              Resume
            </button>
            <button
              type="button"
              onClick={() => setResumePromptOpen(false)}
              className="px-2.5 py-1 text-xs rounded bg-surface-3 text-text-muted"
            >
              Start Here
            </button>
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div className="flex items-center gap-0 px-6 bg-surface-1 border-b border-border">
        {PRIMARY_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            data-testid={`tab-${tab.id}`}
            className={cn(
              "px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px",
              activeTab === tab.id
                ? "text-accent-blue border-b-accent-blue"
                : "text-text-muted hover:text-text-primary border-b-transparent"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden flex">
        {ontologyPanelOpen ? (
          <aside className="w-72 flex-shrink-0 border-r border-border bg-surface-1 flex flex-col">
            <div className="px-4 py-3 border-b border-border space-y-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold text-text-muted uppercase tracking-wider">Ontology</p>
                <div className="flex items-center gap-2">
                  {(familyFilter || selectedTreeNodeId) && (
                    <button
                      type="button"
                      onClick={() => {
                        setFamilyFilter(undefined);
                        setSelectedTreeNodeId(null);
                        setPage(1);
                      }}
                      className="text-[11px] text-accent-blue hover:underline"
                    >
                      Clear
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setOntologyPanelPinned((prev) => !prev)}
                    className={cn(
                      "text-[11px] transition-colors",
                      ontologyPanelPinned ? "text-accent-blue" : "text-text-muted hover:text-text-primary",
                    )}
                    title={ontologyPanelPinned ? "Unpin ontology panel" : "Pin ontology panel"}
                    data-testid="ontology-panel-pin"
                  >
                    {ontologyPanelPinned ? "Pinned" : "Pin"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setOntologyPanelOpen(false)}
                    className="text-[11px] text-text-muted hover:text-text-primary"
                    title="Collapse ontology panel"
                    data-testid="ontology-panel-collapse"
                  >
                    Collapse
                  </button>
                </div>
              </div>
              <input
                value={ontologySearch}
                onChange={(e) => setOntologySearch(e.target.value)}
                placeholder="Search ontology nodes..."
                className="w-full bg-surface-2 border border-border rounded px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted"
                data-testid="ontology-search"
              />
              {selectedOntologyNode ? (
                <div className="space-y-1">
                  <p className="text-xs text-text-primary font-medium truncate">{selectedOntologyNode.name}</p>
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {selectedScopeNode ? (
                      <>
                        <Badge variant="blue">
                          {selectedScopeNode.name}
                          {selectedScopeSummary && selectedScopeSummary.count > 0
                            ? ` · ${selectedScopeSummary.count}`
                            : ""}
                        </Badge>
                        <Badge variant="default" className="text-[10px]">
                          {selectedScopeNode.type.replace(/_/g, " ")}
                        </Badge>
                      </>
                    ) : (
                      <Badge variant="default">Unscoped</Badge>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-text-muted">
                  Select a node to scope review, query, rules, and dashboard data.
                </p>
              )}
            </div>

            <OntologyTree
              roots={ontologyTreeQuery.data?.roots ?? []}
              selectedId={selectedTreeNodeId}
              onSelectNode={handleOntologySelect}
              searchQuery={ontologySearch}
            />
          </aside>
        ) : (
          <aside className="w-10 flex-shrink-0 border-r border-border bg-surface-1 flex flex-col items-center py-2">
            <button
              type="button"
              onClick={() => setOntologyPanelOpen(true)}
              className="text-xs text-text-muted hover:text-text-primary px-1"
              title="Expand ontology panel"
              data-testid="ontology-panel-expand"
            >
              ▶
            </button>
          </aside>
        )}

        <div
          className="flex-1 overflow-hidden flex flex-col"
          onClick={() => {
            if (!ontologyPanelPinned && ontologyPanelOpen) {
              setOntologyPanelOpen(false);
            }
          }}
        >
          <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-surface-1 text-xs">
            {!ontologyPanelOpen && (
              <button
                type="button"
                onClick={() => setOntologyPanelOpen(true)}
                className="text-[11px] px-2 py-0.5 rounded bg-surface-2 text-text-secondary hover:text-text-primary"
                title="Expand ontology panel"
              >
                Ontology
              </button>
            )}
            {selectedScopeNode ? (
              <Badge variant="blue">
                {selectedScopeNode.name}
                {selectedScopeSummary && selectedScopeSummary.count > 0
                  ? ` · ${selectedScopeSummary.count} links`
                  : ""}
              </Badge>
            ) : (
              <Badge variant="default">All Ontology Scopes</Badge>
            )}
            {!familyFilter && activeTab === "query" && (
              <span className="text-text-muted italic">
                Select an ontology node to enable Preview
              </span>
            )}
            {showIntelligencePanel && (
              <button
                type="button"
                onClick={() => setIntelligencePanelOpen((prev) => !prev)}
                className={cn(
                  "ml-auto text-[11px] px-2 py-0.5 rounded transition-colors",
                  intelligencePanelOpen
                    ? "bg-glow-blue text-accent-blue"
                    : "bg-surface-2 text-text-secondary hover:text-text-primary",
                )}
                data-testid="toggle-intelligence-panel"
              >
                {intelligencePanelOpen ? "Hide Intelligence" : "Show Intelligence"}
              </button>
            )}
          </div>

          <div className="flex-1 overflow-hidden flex">
            <div className="flex-1 overflow-hidden">
              {activeTab === "review" ? (
                <ReviewTabContent
                  links={displayedLinks}
                  totalLinks={claimedLinkIds ? displayedLinks.length : totalLinks}
                  summary={summary ?? null}
                  page={page}
                  onPageChange={setPage}
                  familyFilter={familyFilter}
                  onFamilyFilter={(family) => {
                    setFamilyFilter(family);
                    setPage(1);
                  }}
                  statusFilter={statusFilter}
                  onStatusFilter={(status) => {
                    setStatusFilter(status);
                    setPage(1);
                  }}
                  tierFilter={tierFilter}
                  onTierCycle={() => {
                    setTierFilter((prev) => {
                      const idx = TIER_CYCLE.indexOf(prev);
                      return TIER_CYCLE[(idx + 1) % TIER_CYCLE.length];
                    });
                    setPage(1);
                  }}
                  sortBy={sortBy}
                  sortDir={sortDir}
                  onToggleConfidenceSort={toggleConfidenceSort}
                  focusedIdx={focusedIdx}
                  onFocusedIdxChange={setFocusedIdx}
                  selectedIds={selectedIds}
                  onSelectedIdsChange={setSelectedIds}
                  lastSelectedIdx={lastSelectedIdx}
                  onLastSelectedIdxChange={setLastSelectedIdx}
                  readerOpen={readerOpen}
                  detachedReader={detachedReader}
                  onDetach={() => setDetachedReader(true)}
                  onReattach={() => setDetachedReader(false)}
                  focusMode={focusMode}
                  folded={folded}
                  redlineActive={redlineActive}
                  focusedLink={focusedLink}
                  noteInputLinkId={noteInputLinkId}
                  noteText={noteText}
                  noteInputRef={noteInputRef}
                  onNoteTextChange={setNoteText}
                  onNoteSubmit={submitNote}
                  onNoteCancel={() => setNoteInputLinkId(null)}
                  reassignLinkId={reassignLinkId}
                  onReassignClose={() => setReassignLinkId(null)}
                  loading={linksQuery.isLoading}
                  showFamilySidebar={false}
                />
              ) : activeTab === "query" ? (
                <QueryTabContent
                  familyFilter={familyFilter}
                  parentFamilyId={queryParentFamilyId}
                  selectedNodeId={selectedTreeNodeId}
                  selectedNodeType={selectedOntologyNode?.type ?? null}
                  loadRuleId={loadRuleId}
                  onFamilySelect={(nextFamilyId) => {
                    setFamilyFilter(nextFamilyId);
                    setPage(1);
                  }}
                />
              ) : activeTab === "coverage" ? (
                <CoverageTabContent familyFilter={familyFilter} />
              ) : activeTab === "conflicts" ? (
                <ConflictsTabContent familyFilter={familyFilter} />
              ) : activeTab === "rules" ? (
                <RulesTabContent
                  familyFilter={familyFilter}
                  compareRequestId={rulesCompareRequestId}
                  onOpenInQuery={openRuleInQuery}
                />
              ) : activeTab === "dashboard" ? (
                <DashboardTabContent
                  familyFilter={familyFilter}
                  onOpenExport={() => setExportDialogOpen(true)}
                />
              ) : null}
            </div>

            {showIntelligencePanel && intelligencePanelOpen && (
              <OntologyIntelligencePanel scopeId={intelligenceScopeId} />
            )}
          </div>
        </div>
      </div>

      {/* Keyboard help bar */}
      {!focusMode && <KeyboardHelpBar activeTab={activeTab} />}

      {/* Batch action bar */}
      <BatchActionBar
        selectedCount={selectedIds.size}
        onUnlink={() => {
          batchUnlinkMut.mutate({
            linkIds: Array.from(selectedIds),
            reason: "batch_unlink",
          });
          setSelectedIds(new Set());
        }}
        onRelink={() => {
          batchRelinkMut.mutate(Array.from(selectedIds));
          setSelectedIds(new Set());
        }}
        onBookmark={() => {
          batchBookmarkMut.mutate(Array.from(selectedIds));
          setSelectedIds(new Set());
        }}
        onClear={() => setSelectedIds(new Set())}
      />

      {/* Unlink reason dialog */}
      <UnlinkReasonDialog
        open={!!unlinkDialogLinkId}
        onConfirm={(reason) => {
          if (unlinkDialogLinkId) {
            handleUnlink(unlinkDialogLinkId, reason);
          }
          setUnlinkDialogLinkId(null);
        }}
        onClose={() => setUnlinkDialogLinkId(null)}
      />

      {/* Command palette */}
      <CommandPalette
        open={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={handlePaletteNavigate}
        families={summary?.by_family.map((f) => ({ family_id: f.family_id, family_name: f.family_name })) ?? []}
        rules={(paletteRulesData?.rules ?? []).map((rule) => ({
          rule_id: rule.rule_id,
          family_name: rule.family_name,
          heading_filter_dsl: rule.filter_dsl || rule.heading_filter_dsl,
        }))}
      />

      {/* Triage mode */}
      {triageActive && (
        <TriageMode
          links={displayedLinks}
          initialIdx={focusedIdx}
          sessionId={sessionId}
          onApprove={(linkId) => {
            recordMark(linkId, "reviewed");
          }}
          onReject={(linkId) => {
            handleUnlink(linkId, "false_positive");
          }}
          onDefer={(linkId) => {
            deferMut.mutate(linkId);
            recordMark(linkId, "deferred");
          }}
          onNote={(linkId, note) => {
            addNoteMut.mutate({ linkId, note });
            recordMark(linkId, "noted");
          }}
          onExit={() => setTriageActive(false)}
        />
      )}

      {/* Export/import dialog */}
      <ExportImportDialog
        open={exportDialogOpen}
        onClose={() => setExportDialogOpen(false)}
        familyFilter={familyFilter}
      />
    </div>
  );
}

// ── Review tab content ─────────────────────────────────────────────────────

interface ReviewTabContentProps {
  links: FamilyLink[];
  totalLinks: number;
  summary: import("@/lib/types").FamilyLinkSummary | null;
  page: number;
  onPageChange: (p: number) => void;
  familyFilter: string | undefined;
  onFamilyFilter: (f: string | undefined) => void;
  statusFilter: LinkStatus | "all";
  onStatusFilter: (s: LinkStatus | "all") => void;
  tierFilter: ConfidenceTier | "all";
  onTierCycle: () => void;
  sortBy: "created_at" | "confidence";
  sortDir: "asc" | "desc";
  onToggleConfidenceSort: () => void;
  focusedIdx: number;
  onFocusedIdxChange: (i: number) => void;
  selectedIds: Set<string>;
  onSelectedIdsChange: (s: Set<string>) => void;
  lastSelectedIdx: number | null;
  onLastSelectedIdxChange: (i: number | null) => void;
  readerOpen: boolean;
  detachedReader: boolean;
  onDetach: () => void;
  onReattach: () => void;
  focusMode: boolean;
  folded: boolean;
  redlineActive: boolean;
  focusedLink: FamilyLink | null;
  noteInputLinkId: string | null;
  noteText: string;
  noteInputRef: React.RefObject<HTMLInputElement>;
  onNoteTextChange: (t: string) => void;
  onNoteSubmit: () => void;
  onNoteCancel: () => void;
  reassignLinkId: string | null;
  onReassignClose: () => void;
  loading: boolean;
  showFamilySidebar?: boolean;
}

function ReviewTabContent({
  links,
  totalLinks,
  summary,
  page,
  onPageChange,
  familyFilter,
  onFamilyFilter,
  statusFilter,
  onStatusFilter,
  tierFilter,
  onTierCycle,
  sortBy,
  sortDir,
  onToggleConfidenceSort,
  focusedIdx,
  onFocusedIdxChange,
  selectedIds,
  onSelectedIdsChange,
  lastSelectedIdx,
  onLastSelectedIdxChange,
  readerOpen,
  detachedReader,
  onDetach,
  onReattach,
  focusMode,
  folded,
  redlineActive,
  focusedLink,
  noteInputLinkId,
  noteText,
  noteInputRef,
  onNoteTextChange,
  onNoteSubmit,
  onNoteCancel,
  reassignLinkId,
  onReassignClose,
  loading,
  showFamilySidebar = true,
}: ReviewTabContentProps) {
  const totalPages = Math.ceil(totalLinks / 50);
  const [reviewColumnsOpen, setReviewColumnsOpen] = useState(false);
  const [reviewColumns, setReviewColumns] = useState<Record<ReviewColumnId, boolean>>(DEFAULT_REVIEW_COLUMNS);
  const reviewColumnsRef = useRef<HTMLDivElement | null>(null);
  const visibleReviewColumnCount = Object.values(reviewColumns).filter(Boolean).length;

  useEffect(() => {
    if (!reviewColumnsOpen) return;
    const handleOutsideClick = (event: MouseEvent) => {
      if (!reviewColumnsRef.current) return;
      if (!reviewColumnsRef.current.contains(event.target as Node)) {
        setReviewColumnsOpen(false);
      }
    };
    window.addEventListener("mousedown", handleOutsideClick);
    return () => window.removeEventListener("mousedown", handleOutsideClick);
  }, [reviewColumnsOpen]);

  const toggleReviewColumn = useCallback((columnId: ReviewColumnId) => {
    setReviewColumns((prev) => {
      const currentlyVisible = Object.values(prev).filter(Boolean).length;
      if (prev[columnId] && currentlyVisible <= 1) return prev;
      return { ...prev, [columnId]: !prev[columnId] };
    });
  }, []);

  // Fetch context data for the focused link
  const { data: contextData } = useContextStrip(focusedLink?.link_id ?? null);
  const { data: comparablesData } = useComparables(focusedLink?.link_id ?? null);
  const { data: whyMatchedData } = useWhyMatched(focusedLink?.link_id ?? null);

  // Build sectionFamilies from context data
  const sectionFamilies = useMemo(() => {
    if (!focusedLink) return [];
    const familiesFromContext = Array.isArray(contextData?.section_families)
      ? contextData.section_families
      : [];
    if (familiesFromContext.length > 0) {
      return familiesFromContext.map((family) => ({
        family_id: family.family_id,
        family_name: family.family_name,
        is_current: !!family.is_current || family.family_id === focusedLink.family_id,
      }));
    }

    const sameSectionFamilies = links
      .filter(
        (link) =>
          link.doc_id === focusedLink.doc_id &&
          link.section_number === focusedLink.section_number,
      )
      .map((link) => ({
        family_id: link.family_id,
        family_name: link.family_name,
        is_current: link.link_id === focusedLink.link_id,
      }));
    if (sameSectionFamilies.length > 0) {
      const unique = new Map<string, { family_id: string; family_name: string; is_current?: boolean }>();
      for (const family of sameSectionFamilies) {
        if (!unique.has(family.family_id)) {
          unique.set(family.family_id, family);
        }
      }
      return Array.from(unique.values());
    }

    return [
      {
        family_id: focusedLink.family_id,
        family_name: focusedLink.family_name,
        is_current: true,
      },
    ];
  }, [contextData, focusedLink, links]);

  // Build definitions from context data
  const definitions = useMemo(() => {
    if (!contextData) return [];
    return contextData.definitions.map((d) => ({
      term: d.term,
      definition_text: d.definition_text,
      char_start: 0,
      char_end: 0,
    }));
  }, [contextData]);

  const sectionText = useMemo(() => {
    if (!contextData || typeof contextData.section_text !== "string") {
      return null;
    }
    return contextData.section_text;
  }, [contextData]);

  // Click-to-select with shift for range
  const handleRowClick = useCallback(
    (idx: number, e: React.MouseEvent) => {
      if (e.shiftKey && lastSelectedIdx !== null) {
        // Range select
        const start = Math.min(lastSelectedIdx, idx);
        const end = Math.max(lastSelectedIdx, idx);
        const next = new Set(selectedIds);
        for (let i = start; i <= end; i++) {
          if (links[i]) next.add(links[i].link_id);
        }
        onSelectedIdsChange(next);
      } else {
        onFocusedIdxChange(idx);
      }
      onLastSelectedIdxChange(idx);
    },
    [links, lastSelectedIdx, selectedIds, onSelectedIdsChange, onFocusedIdxChange, onLastSelectedIdxChange]
  );

  return (
    <div className="flex h-full">
      {/* Left: Scope sidebar */}
      {showFamilySidebar && !focusMode && (
        <div className="w-52 flex-shrink-0 bg-surface-1 border-r border-border overflow-y-auto">
          {/* KPI tiles */}
          {summary && (
            <div className="p-3 border-b border-border space-y-2">
              <SidebarKpi label="Total links" value={summary.total} color="blue" />
              <SidebarKpi label="Unique docs" value={summary.unique_docs} color="green" />
              <SidebarKpi label="Pending review" value={summary.pending_review} color="orange" />
              <SidebarKpi label="Unlinked" value={summary.unlinked} color="red" />
            </div>
          )}

          {/* Scope list */}
          <div className="p-2">
            <button
              onClick={() => onFamilyFilter(undefined)}
              className={cn(
                "w-full text-left px-3 py-2 rounded-md text-sm transition-colors",
                !familyFilter
                  ? "bg-glow-blue text-accent-blue font-medium"
                  : "text-text-secondary hover:text-text-primary hover:bg-surface-3"
              )}
            >
              All Scopes
              {summary && (
                <span className="float-right tabular-nums text-text-muted">
                  {summary.total}
                </span>
              )}
            </button>
            {summary?.by_family.map((fam) => (
              <button
                key={fam.family_id}
                onClick={() => onFamilyFilter(fam.family_id)}
                className={cn(
                  "w-full text-left px-3 py-2 rounded-md text-sm transition-colors",
                  familyFilter === fam.family_id
                    ? "bg-glow-blue text-accent-blue font-medium"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-3"
                )}
              >
                <span className="truncate">{fam.family_name}</span>
                <span className="float-right flex items-center gap-1.5 tabular-nums">
                  <span className="text-text-muted">{fam.count}</span>
                  {fam.pending > 0 && (
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-accent-orange" title={`${fam.pending} pending`} />
                  )}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Center: Table + Filters */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Status filter bar */}
        <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-surface-1">
          {STATUS_FILTERS.map((sf) => (
            <button
              key={sf.value}
              onClick={() => onStatusFilter(sf.value)}
              className={cn(
                "filter-chip",
                statusFilter === sf.value && "active"
              )}
            >
              {sf.label}
            </button>
          ))}
          <div className="w-px h-5 bg-border mx-1" />
          <button
            className={cn(
              "filter-chip",
              tierFilter !== "all" && "active"
            )}
            onClick={onTierCycle}
            title="Press 't' to cycle tiers"
          >
            Tier: {tierFilter === "all" ? "All" : tierFilter}
          </button>
          <div className="ml-auto relative" ref={reviewColumnsRef}>
            <button
              type="button"
              onClick={() => setReviewColumnsOpen((prev) => !prev)}
              className={cn(
                "filter-chip",
                reviewColumnsOpen && "active",
              )}
            >
              Columns
            </button>
            {reviewColumnsOpen && (
              <div className="absolute top-full right-0 mt-1 z-30 w-44 rounded-lg border border-border bg-surface-1 shadow-xl p-2 space-y-1">
                {(Object.keys(REVIEW_COLUMN_LABELS) as ReviewColumnId[]).map((columnId) => {
                  const checked = reviewColumns[columnId];
                  const disableToggle = checked && visibleReviewColumnCount <= 1;
                  return (
                    <label
                      key={columnId}
                      className={cn(
                        "flex items-center justify-between gap-2 px-2 py-1 rounded text-xs text-text-secondary",
                        disableToggle ? "opacity-60" : "hover:bg-surface-2",
                      )}
                    >
                      <span>{REVIEW_COLUMN_LABELS[columnId]}</span>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleReviewColumn(columnId)}
                        disabled={disableToggle}
                        className="accent-accent-blue"
                      />
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        </div>
        {/* Table area + Reader pane */}
        <div className="flex-1 flex overflow-hidden">
          {/* Table */}
          <div className={cn("flex-1 overflow-auto", readerOpen && "w-1/2")}>
            <table className="w-full border-collapse">
              <thead className="sticky top-0 z-10 bg-surface-2">
                <tr>
                  <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border w-8">
                    {/* checkbox col */}
                  </th>
                  {reviewColumns.doc && (
                    <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Doc</th>
                  )}
                  {reviewColumns.section && (
                    <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Section</th>
                  )}
                  {reviewColumns.heading && (
                    <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Heading</th>
                  )}
                  {reviewColumns.scope && (
                    <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Scope</th>
                  )}
                  {reviewColumns.confidence && (
                    <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                      <button
                        type="button"
                        onClick={onToggleConfidenceSort}
                        className="inline-flex items-center gap-1 hover:text-text-primary transition-colors"
                        title="Sort by confidence"
                      >
                        Confidence
                        <span aria-hidden="true">
                          {sortBy === "confidence" ? (sortDir === "asc" ? "▲" : "▼") : "⇅"}
                        </span>
                      </button>
                    </th>
                  )}
                  {reviewColumns.status && (
                    <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Status</th>
                  )}
                  {reviewColumns.actions && (
                    <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Actions</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <SkeletonTableRows rows={10} cols={1 + visibleReviewColumnCount} />
                ) : links.length === 0 ? (
                  <tr>
                    <td colSpan={1 + visibleReviewColumnCount} className="px-3 py-12 text-center text-text-muted text-sm">
                      No links found
                    </td>
                  </tr>
                ) : (
                  links.map((link, idx) => {
                    const isFocused = idx === focusedIdx;
                    const isSelected = selectedIds.has(link.link_id);
                    const tierColor =
                      link.confidence_tier === "high"
                        ? "green"
                        : link.confidence_tier === "medium"
                        ? "orange"
                        : "red";

                    return (
                      <tr
                        key={link.link_id}
                        data-row-id={link.link_id}
                        data-testid={`link-row-${link.link_id}`}
                        onClick={(e) => handleRowClick(idx, e)}
                        className={cn(
                          "border-b border-border/30 transition-colors cursor-pointer",
                          isFocused && "shadow-inset-blue bg-glow-blue",
                          isSelected && !isFocused && "border-l-2 border-l-accent-blue bg-glow-blue",
                          !isSelected && !isFocused && "border-l-2 border-l-transparent hover:bg-surface-2/50"
                        )}
                      >
                        <td className="px-3 py-2">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => {
                              const next = new Set(selectedIds);
                              if (next.has(link.link_id)) next.delete(link.link_id);
                              else next.add(link.link_id);
                              onSelectedIdsChange(next);
                            }}
                            className="accent-accent-blue"
                            onClick={(e) => e.stopPropagation()}
                          />
                        </td>
                        {reviewColumns.doc && (
                          <td className="px-3 py-2 text-sm text-text-primary font-mono text-xs">
                            {link.doc_id}
                          </td>
                        )}
                        {reviewColumns.section && (
                          <td className="px-3 py-2 text-sm text-text-primary tabular-nums">
                            {link.section_number}
                          </td>
                        )}
                        {reviewColumns.heading && (
                          <td className="px-3 py-2 text-sm text-text-primary truncate max-w-48">
                            {link.heading}
                          </td>
                        )}
                        {reviewColumns.scope && (
                          <td className="px-3 py-2">
                            <div className="flex items-center gap-1.5">
                              <Badge variant="blue">{link.family_name}</Badge>
                              <Badge variant={ROLE_BADGE_VARIANT[link.link_role]} className="text-[10px]">
                                {link.link_role === "primary_covenant" ? "" : link.link_role.replace(/_/g, " ")}
                              </Badge>
                            </div>
                          </td>
                        )}
                        {reviewColumns.confidence && (
                          <td className="px-3 py-2">
                            <WhyMatchedPopover
                              factors={
                                link.link_id === focusedLink?.link_id
                                  ? whyMatchedData?.factors ?? toWhyMatchedFactors(link.confidence_breakdown)
                                  : toWhyMatchedFactors(link.confidence_breakdown)
                              }
                              confidence={link.confidence}
                              confidenceTier={link.confidence_tier}
                              trigger={
                                <Badge variant={tierColor as "green" | "orange" | "red"}>
                                  {(link.confidence * 100).toFixed(0)}%
                                </Badge>
                              }
                            />
                          </td>
                        )}
                        {reviewColumns.status && (
                          <td className="px-3 py-2">
                            <Badge
                              variant={
                                link.status === "active"
                                  ? "green"
                                  : link.status === "pending_review"
                                    ? "orange"
                                    : link.status === "unlinked"
                                      ? "red"
                                      : "default"
                              }
                            >
                              {link.status.replace(/_/g, " ")}
                            </Badge>
                          </td>
                        )}
                        {reviewColumns.actions && (
                          <td className="px-3 py-2">
                            {noteInputLinkId === link.link_id ? (
                              <input
                                ref={noteInputRef}
                                value={noteText}
                                onChange={(e) => onNoteTextChange(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter") {
                                    e.preventDefault();
                                    onNoteSubmit();
                                  } else if (e.key === "Escape") {
                                    onNoteCancel();
                                  }
                                }}
                                placeholder="Type note, Enter to save"
                                className="bg-surface-3 border border-border rounded px-2 py-1 text-xs text-text-primary w-32 focus:outline-none focus:ring-1 focus:ring-accent-blue"
                                onClick={(e) => e.stopPropagation()}
                              />
                            ) : (
                              <span className="text-xs text-text-muted">
                                {link.note ? `📌 ${link.note.slice(0, 20)}...` : ""}
                              </span>
                            )}
                          </td>
                        )}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between px-3 py-2 border-t border-border bg-surface-1">
                <span className="text-xs text-text-muted tabular-nums">
                  {totalLinks.toLocaleString()} total links
                </span>
                <div className="flex items-center gap-2">
                  <button
                    className="btn-ghost"
                    onClick={() => onPageChange(page - 1)}
                    disabled={page <= 1}
                  >
                    Prev
                  </button>
                  <span className="text-xs text-text-secondary tabular-nums px-2">
                    {page} / {totalPages}
                  </span>
                  <button
                    className="btn-ghost"
                    onClick={() => onPageChange(page + 1)}
                    disabled={page >= totalPages}
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Reader pane */}
          {readerOpen && (
            <div className="w-1/2 border-l border-border">
              <DetachableReader
                detached={detachedReader}
                onDetach={onDetach}
                onReattach={onReattach}
                currentLinkId={focusedLink?.link_id ?? null}
              >
                <ReviewPane
                  link={focusedLink}
                  sectionText={sectionText}
                  sectionFamilies={sectionFamilies}
                  definitions={definitions}
                  comparables={comparablesData?.comparables ?? []}
                  folded={folded}
                  redlineActive={redlineActive}
                  templateFamily={focusedLink?.family_id ?? null}
                />
              </DetachableReader>
            </div>
          )}
        </div>
      </div>

      {/* Reassign dialog */}
      {reassignLinkId && focusedLink && (
        <ReassignDialog
          linkId={reassignLinkId}
          currentFamilyId={focusedLink.family_id}
          currentFamilyName={focusedLink.family_name}
          open={!!reassignLinkId}
          onClose={onReassignClose}
        />
      )}
    </div>
  );
}

// ── Query tab content ───────────────────────────────────────────────────────

function QueryTabContent({
  familyFilter,
  parentFamilyId,
  selectedNodeId,
  selectedNodeType,
  loadRuleId,
  onFamilySelect,
}: {
  familyFilter?: string;
  parentFamilyId?: string;
  selectedNodeId?: string | null;
  selectedNodeType?: string | null;
  loadRuleId?: string;
  onFamilySelect?: (familyId: string) => void;
}) {
  const [dslText, setDslText] = useState("");
  const [currentAst, setCurrentAst] = useState<FilterExpressionNode | null>(null);
  const [currentTextFields, setCurrentTextFields] = useState<Record<string, unknown> | null>(null);
  const [currentMetaFilters, setCurrentMetaFilters] = useState<Record<string, unknown> | null>(null);
  const [validationResult, setValidationResult] = useState<{ errors: import("@/lib/types").DslError[]; query_cost?: number } | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [previewCandidateHash, setPreviewCandidateHash] = useState<string>("");
  const [previewTierFilter, setPreviewTierFilter] = useState<ConfidenceTier | "all">("all");
  const [previewCursor, setPreviewCursor] = useState<{
    afterScore: number;
    afterDocId: string;
  } | null>(null);
  const [cursorHistory, setCursorHistory] = useState<
    Array<{
      afterScore: number;
      afterDocId: string;
    } | null>
  >([]);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [scopeMode, setScopeMode] = useState<"corpus" | "inherited">("corpus");
  const [resultGranularity, setResultGranularity] = useState<"section" | "clause">("section");
  const [resultSearch, setResultSearch] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [queryReaderOpen, setQueryReaderOpen] = useState(false);
  const [queryDetachedReader, setQueryDetachedReader] = useState(false);
  const [selectedCandidateRowId, setSelectedCandidateRowId] = useState<string | null>(null);
  const [focusedCandidate, setFocusedCandidate] = useState<PreviewCandidate | null>(null);
  const [queryColumnsOpen, setQueryColumnsOpen] = useState(false);
  const [queryColumnsVisibility, setQueryColumnsVisibility] = useState<Record<QueryColumnId, boolean>>(DEFAULT_QUERY_COLUMNS);
  const queryColumnsRef = useRef<HTMLDivElement | null>(null);

  const getPreviewCandidateRowId = useCallback((candidate: PreviewCandidate) => {
    const clauseRef = candidate.clause_id || candidate.clause_path || candidate.clause_label || "section";
    return `${candidate.doc_id}::${candidate.section_number}::${clauseRef}::${candidate.existing_link_id ?? "new"}`;
  }, []);

  const PREVIEW_PAGE_SIZE = 10000;

  // Derive validated DSL text for API calls (only when validation passes)
  const validDslText = validationResult && validationResult.errors.length === 0 ? dslText.trim() : "";
  const visibleQueryColumnCount = Object.values(queryColumnsVisibility).filter(Boolean).length;

  useEffect(() => {
    if (!queryColumnsOpen) return;
    const handleOutsideClick = (event: MouseEvent) => {
      if (!queryColumnsRef.current) return;
      if (!queryColumnsRef.current.contains(event.target as Node)) {
        setQueryColumnsOpen(false);
      }
    };
    window.addEventListener("mousedown", handleOutsideClick);
    return () => window.removeEventListener("mousedown", handleOutsideClick);
  }, [queryColumnsOpen]);

  const toggleQueryColumn = useCallback((columnId: QueryColumnId) => {
    setQueryColumnsVisibility((prev) => {
      const currentlyVisible = Object.values(prev).filter(Boolean).length;
      if (prev[columnId] && currentlyVisible <= 1) return prev;
      return { ...prev, [columnId]: !prev[columnId] };
    });
  }, []);

  const { data: publishedRulesData } = useLinkRules({ status: "published" });
  const parentPublishedRule = useMemo(() => {
    if (!parentFamilyId) return null;
    const targetToken = canonicalFamilyToken(parentFamilyId);
    const candidates = (publishedRulesData?.rules ?? []).filter((rule) => {
      if (rule.status !== "published") return false;
      if (rule.family_id === parentFamilyId) return true;
      if (!targetToken) return false;
      const ruleToken = canonicalFamilyToken(rule.family_id || rule.family_name);
      return ruleToken === targetToken;
    });
    if (candidates.length === 0) return null;
    return [...candidates].sort((a, b) => {
      const av = Number(a.version ?? 0);
      const bv = Number(b.version ?? 0);
      if (av !== bv) return bv - av;
      return String(b.updated_at ?? b.created_at).localeCompare(String(a.updated_at ?? a.created_at));
    })[0];
  }, [publishedRulesData?.rules, parentFamilyId]);
  const resolvedParentFamilyId = parentPublishedRule?.family_id ?? parentFamilyId;
  const inheritedAvailable = !!resolvedParentFamilyId && !!parentPublishedRule;
  const { data: parentRunsData } = useLinkRuns({ familyId: resolvedParentFamilyId, limit: 50 });
  const parentRunId = useMemo(
    () => parentRunsData?.runs.find((run) => run.status === "completed")?.run_id ?? null,
    [parentRunsData?.runs],
  );
  const effectiveScopeMode: "corpus" | "inherited" =
    scopeMode === "inherited" && inheritedAvailable ? "inherited" : "corpus";
  const previewScope = useMemo(
    () => ({
      scopeMode: effectiveScopeMode,
      parentFamilyId: effectiveScopeMode === "inherited" ? (resolvedParentFamilyId ?? null) : null,
      parentRuleId: effectiveScopeMode === "inherited" ? (parentPublishedRule?.rule_id ?? null) : null,
      parentRunId: effectiveScopeMode === "inherited" ? parentRunId : null,
    }),
    [effectiveScopeMode, resolvedParentFamilyId, parentPublishedRule?.rule_id, parentRunId],
  );
  const scopeContextRef = useRef<string>("");
  const scopeTouchedRef = useRef(false);
  const isChildNodeSelected = !!selectedNodeType && selectedNodeType !== "family";
  const ontologyNodeIdForPersistence = selectedNodeId ?? familyFilter ?? null;
  const scopeContextKey = `${familyFilter ?? ""}|${parentFamilyId ?? ""}|${selectedNodeId ?? ""}|${selectedNodeType ?? ""}`;

  const validateMut = useValidateDslMutation();
  const queryCountResult = useQueryCountWithMeta(
    familyFilter,
    currentAst as unknown as Record<string, unknown> | null,
    currentMetaFilters,
    validDslText || undefined,
    {
      scopeMode: previewScope.scopeMode,
      parentFamilyId: previewScope.parentFamilyId,
      parentRunId: previewScope.parentRunId,
    },
  );
  const createPreviewMut = useCreatePreviewFromAstMutation();
  const { data: candidatesData } = usePreviewCandidates(previewId, {
    pageSize: PREVIEW_PAGE_SIZE,
    confidenceTier: previewTierFilter === "all" ? undefined : previewTierFilter,
    afterScore: previewCursor?.afterScore ?? null,
    afterDocId: previewCursor?.afterDocId ?? null,
  });
  const updateVerdictsMut = useUpdateVerdictsMutation();
  const applyMut = useApplyPreviewMutation();
  const canaryMut = useCanaryApplyMutation();
  const saveRuleMut = useSaveAsRuleMutation();
  const [loadRuleDropdownOpen, setLoadRuleDropdownOpen] = useState(false);
  const { data: availableRulesData } = useLinkRules({ familyId: familyFilter });
  const { data: allRulesData } = useLinkRules();
  const availableRules = availableRulesData?.rules ?? [];
  const allRules = allRulesData?.rules ?? [];
  const fallbackRules = useMemo(() => {
    if (!familyFilter || availableRules.length > 0) return [];
    const target = canonicalFamilyToken(familyFilter);
    if (!target) return [];
    return allRules.filter((rule) => {
      const ruleToken = canonicalFamilyToken(rule.family_id || rule.family_name);
      return ruleToken === target;
    });
  }, [familyFilter, availableRules, allRules]);
  const loadableRules = useMemo(
    () =>
      [...(familyFilter ? (availableRules.length > 0 ? availableRules : fallbackRules) : availableRules)].sort((a, b) => {
        if (a.family_id !== b.family_id) return a.family_id.localeCompare(b.family_id);
        const av = Number(a.version ?? 0);
        const bv = Number(b.version ?? 0);
        if (av !== bv) return bv - av;
        return String(b.updated_at ?? b.created_at).localeCompare(String(a.updated_at ?? a.created_at));
      }),
    [familyFilter, availableRules, fallbackRules],
  );

  // Load rule from URL param (set by Rules tab "Open in Query")
  const { data: loadedRuleData } = useLinkRule(loadRuleId ?? null);
  const loadedRuleIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (scopeContextRef.current === scopeContextKey) return;
    scopeContextRef.current = scopeContextKey;
    scopeTouchedRef.current = false;
  }, [scopeContextKey]);

  useEffect(() => {
    if (scopeTouchedRef.current) return;
    if (isChildNodeSelected && inheritedAvailable) {
      setScopeMode("inherited");
    } else {
      setScopeMode("corpus");
    }
  }, [isChildNodeSelected, inheritedAvailable, scopeContextKey]);

  useEffect(() => {
    if (loadedRuleData && loadRuleId && loadRuleId !== loadedRuleIdRef.current) {
      loadedRuleIdRef.current = loadRuleId;
      const ruleDsl = loadedRuleData.filter_dsl || loadedRuleData.heading_filter_dsl;
      if (ruleDsl) {
        setDslText(ruleDsl);
        setPreviewId(null);
        setApplyError(null);
      }
      if (loadedRuleData.scope_mode === "inherited" && inheritedAvailable) {
        scopeTouchedRef.current = true;
        setScopeMode("inherited");
      } else {
        scopeTouchedRef.current = true;
        setScopeMode("corpus");
      }
      // Clean loadRuleId from URL to prevent re-triggering on navigation
      if (typeof window !== "undefined") {
        const params = new URLSearchParams(window.location.search);
        params.delete("loadRuleId");
        params.set("tab", "query");
        window.history.replaceState(null, "", `/links?${params.toString()}`);
      }
    }
  }, [loadedRuleData, loadRuleId, inheritedAvailable]);

  // Debounced validation
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!dslText.trim()) {
      setCurrentAst(null);
      setCurrentMetaFilters(null);
      setValidationResult(null);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      validateMut.mutate(dslText, {
        onSuccess: (result) => {
          setValidationResult({ errors: result.errors, query_cost: result.query_cost });
          if (result.errors.length === 0) {
            // Pick the heading AST if present; otherwise use the first available text field
            const tf = result.text_fields as Record<string, unknown>;
            const headingAst = tf.heading ?? null;
            const firstFieldAst = headingAst
              ?? tf.article ?? tf.clause ?? tf.section ?? tf.defined_term
              ?? null;
            setCurrentAst(
              firstFieldAst
                ? (firstFieldAst as unknown as FilterExpressionNode)
                : null,
            );
            setCurrentTextFields(tf ?? null);
            setCurrentMetaFilters((result.meta_fields as Record<string, unknown>) ?? {});
          } else {
            setCurrentAst(null);
            setCurrentTextFields(null);
            setCurrentMetaFilters(null);
          }
        },
      });
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dslText]);

  const hasAnyFilter = !!(validDslText || currentAst || (currentTextFields && Object.keys(currentTextFields).length > 0) || (currentMetaFilters && Object.keys(currentMetaFilters).length > 0));
  const clauseHighlightTerms = useMemo(() => {
    const values = new Set<string>();
    const clauseNode =
      currentTextFields && typeof currentTextFields === "object"
        ? (currentTextFields as Record<string, unknown>).clause
        : null;
    collectAstMatchValues(clauseNode, values);
    return Array.from(values).filter((term) => term.length >= 2).sort((a, b) => b.length - a.length);
  }, [currentTextFields]);

  const handleCreatePreview = useCallback(() => {
    if (!familyFilter || !hasAnyFilter) return;
    setPreviewCursor(null);
    setCursorHistory([]);
    setPreviewCandidateHash("");
    setApplyError(null);
    createPreviewMut.mutate(
      {
        familyId: familyFilter,
        ast: (currentAst as unknown as Record<string, unknown>) ?? {},
        metaFilters: currentMetaFilters ?? undefined,
        textFields: currentTextFields ?? undefined,
        filterDsl: validDslText || undefined,
        resultGranularity,
        ontologyNodeId: ontologyNodeIdForPersistence,
        scope: previewScope,
      },
      {
        onSuccess: (data) => {
          const raw = data as unknown as Record<string, unknown>;
          if (!raw.preview_id) {
            setApplyError("Preview queued asynchronously. Poll job status to continue.");
            setPreviewId(null);
            return;
          }
          setPreviewId(String(raw.preview_id));
          setPreviewCandidateHash(String(raw.candidate_set_hash ?? ""));
        },
      },
    );
  }, [familyFilter, currentAst, currentMetaFilters, currentTextFields, hasAnyFilter, createPreviewMut, validDslText, resultGranularity, ontologyNodeIdForPersistence, previewScope]);

  const candidates = candidatesData?.items ?? [];
  const totalResults = candidatesData?.total ?? candidates.length;
  const nextCursor = candidatesData?.next_cursor ?? null;
  const hasPrev = cursorHistory.length > 0;
  const hasNext = !!nextCursor;
  const currentPage = cursorHistory.length;
  const totalPages = Math.max(1, Math.ceil(totalResults / PREVIEW_PAGE_SIZE));

  useEffect(() => {
    setPreviewCursor(null);
    setCursorHistory([]);
    setSelectedCandidateRowId(null);
    setFocusedCandidate(null);
    setQueryReaderOpen(false);
    setQueryDetachedReader(false);
  }, [previewId, previewTierFilter]);

  // Client-side filtering on loaded results
  const filteredCandidates = useMemo(() => {
    if (!resultSearch.trim()) return candidates;
    const q = resultSearch.toLowerCase();
    return candidates.filter((c) =>
      c.doc_id.toLowerCase().includes(q) ||
      c.borrower.toLowerCase().includes(q) ||
      c.heading.toLowerCase().includes(q) ||
      c.section_number.includes(q) ||
      String(c.clause_path ?? "").toLowerCase().includes(q) ||
      String(c.clause_label ?? "").toLowerCase().includes(q)
    );
  }, [candidates, resultSearch]);

  // Client-side sorting on loaded page
  const sortedCandidates = useMemo(() => {
    if (sorting.length === 0) return filteredCandidates;
    const { id, desc } = sorting[0];
    return [...filteredCandidates].sort((a, b) => {
      const aVal = (a as Record<string, unknown>)[id];
      const bVal = (b as Record<string, unknown>)[id];
      if (aVal == null && bVal == null) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;
      if (aVal < bVal) return desc ? 1 : -1;
      if (aVal > bVal) return desc ? -1 : 1;
      return 0;
    });
  }, [filteredCandidates, sorting]);

  // Verdicts progress tracker
  const verdictCounts = useMemo(() => ({
    accepted: candidates.filter((c) => c.verdict === "accepted").length,
    rejected: candidates.filter((c) => c.verdict === "rejected").length,
    deferred: candidates.filter((c) => c.verdict === "deferred").length,
  }), [candidates]);

  useEffect(() => {
    if (!selectedCandidateRowId || !focusedCandidate) return;
    const nextFocused = candidates.find((candidate) => getPreviewCandidateRowId(candidate) === selectedCandidateRowId);
    if (nextFocused && nextFocused !== focusedCandidate) {
      setFocusedCandidate(nextFocused);
    }
  }, [candidates, selectedCandidateRowId, focusedCandidate, getPreviewCandidateRowId]);

  const focusedPreviewLink = useMemo<FamilyLink | null>(() => {
    if (!focusedCandidate) return null;
    const timestamp = new Date().toISOString();
    const familyId = String(familyFilter ?? "").trim() || "preview";
    const familyName = familyId || "Preview";
    return {
      link_id: focusedCandidate.existing_link_id ?? "",
      doc_id: focusedCandidate.doc_id,
      borrower: focusedCandidate.borrower || focusedCandidate.doc_id,
      section_number: focusedCandidate.section_number,
      ontology_node_id: ontologyNodeIdForPersistence,
      clause_id: focusedCandidate.clause_id ?? null,
      clause_char_start: focusedCandidate.clause_char_start ?? null,
      clause_char_end: focusedCandidate.clause_char_end ?? null,
      clause_text: focusedCandidate.clause_text ?? null,
      heading: focusedCandidate.heading,
      family_id: familyId,
      family_name: familyName,
      confidence: focusedCandidate.confidence,
      confidence_tier: focusedCandidate.confidence_tier,
      confidence_breakdown: null,
      link_role: "primary_covenant",
      status: "pending_review",
      rule_id: null,
      run_id: previewId,
      created_at: timestamp,
      updated_at: timestamp,
      reviewed_at: null,
      reviewed_by: null,
      note: null,
      section_text_hash: null,
    } satisfies FamilyLink;
  }, [focusedCandidate, familyFilter, ontologyNodeIdForPersistence, previewId]);

  const focusedPreviewLinkId =
    focusedPreviewLink?.link_id && focusedPreviewLink.link_id.length > 0
      ? focusedPreviewLink.link_id
      : null;
  const { data: contextData } = useContextStrip(focusedPreviewLinkId);
  const { data: comparablesData } = useComparables(focusedPreviewLinkId);
  const { data: readerSectionData } = useReaderSection(
    focusedPreviewLinkId ? null : focusedCandidate?.doc_id ?? null,
    focusedPreviewLinkId ? null : focusedCandidate?.section_number ?? null,
  );
  const { data: readerDefinitionsData } = useReaderDefinitions(
    focusedPreviewLinkId ? null : focusedCandidate?.doc_id ?? null,
  );

  const sectionFamilies = useMemo(() => {
    if (!focusedPreviewLink) return [];
    const familiesFromContext = Array.isArray(contextData?.section_families)
      ? contextData.section_families
      : [];
    if (familiesFromContext.length > 0) {
      return familiesFromContext.map((family) => ({
        family_id: family.family_id,
        family_name: family.family_name,
        is_current: !!family.is_current || family.family_id === focusedPreviewLink.family_id,
      }));
    }
    return [
      {
        family_id: focusedPreviewLink.family_id,
        family_name: focusedPreviewLink.family_name,
        is_current: true,
      },
    ];
  }, [contextData, focusedPreviewLink]);

  const definitions = useMemo(() => {
    if (contextData?.definitions?.length) {
      return contextData.definitions.map((d) => ({
        term: d.term,
        definition_text: d.definition_text,
        char_start: 0,
        char_end: 0,
      }));
    }
    if (readerDefinitionsData?.definitions?.length) {
      return readerDefinitionsData.definitions.map((d) => ({
        term: d.term,
        definition_text: d.definition_text,
        char_start: d.char_start,
        char_end: d.char_end,
      }));
    }
    return [];
  }, [contextData, readerDefinitionsData]);

  const sectionText = useMemo(() => {
    if (typeof contextData?.section_text === "string" && contextData.section_text.length > 0) {
      return contextData.section_text;
    }
    if (typeof readerSectionData?.text === "string" && readerSectionData.text.length > 0) {
      return readerSectionData.text;
    }
    return null;
  }, [contextData, readerSectionData]);

  const queryFocusRange = useMemo(() => {
    if (!focusedCandidate) return null;
    const clauseStart = focusedCandidate.clause_char_start;
    const clauseEnd = focusedCandidate.clause_char_end;
    const sectionStart = readerSectionData?.section_char_start;
    if (
      clauseStart === null ||
      clauseStart === undefined ||
      clauseEnd === null ||
      clauseEnd === undefined ||
      sectionStart === null ||
      sectionStart === undefined
    ) {
      return null;
    }
    const relStart = Number(clauseStart) - Number(sectionStart);
    const relEnd = Number(clauseEnd) - Number(sectionStart);
    if (!Number.isFinite(relStart) || !Number.isFinite(relEnd) || relEnd <= relStart) {
      return null;
    }
    return {
      start: Math.max(0, Math.floor(relStart)),
      end: Math.max(0, Math.floor(relEnd)),
    };
  }, [
    focusedCandidate,
    readerSectionData?.section_char_start,
  ]);

  const handleCandidateRowClick = useCallback((candidate: PreviewCandidate) => {
    setFocusedCandidate(candidate);
    setSelectedCandidateRowId(getPreviewCandidateRowId(candidate));
    setQueryReaderOpen(true);
  }, [getPreviewCandidateRowId]);

  // Cursor-based pagination mapped to page numbers
  const handlePageChange = useCallback((targetPage: number) => {
    if (targetPage > currentPage && nextCursor) {
      setCursorHistory((prev) => [...prev, previewCursor]);
      setPreviewCursor({
        afterScore: nextCursor.after_score,
        afterDocId: nextCursor.after_doc_id,
      });
    } else if (targetPage < currentPage && hasPrev) {
      const prevCur = cursorHistory[cursorHistory.length - 1] ?? null;
      setCursorHistory((prev) => prev.slice(0, -1));
      setPreviewCursor(prevCur);
    }
  }, [currentPage, nextCursor, previewCursor, hasPrev, cursorHistory]);

  // Column definitions for DataTable
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const queryColumns = useMemo<ColumnDef<PreviewCandidate, any>[]>(() => [
    {
      id: "borrower",
      accessorKey: "borrower",
      header: "Borrower",
      enableSorting: true,
      cell: ({ row }: { row: { original: PreviewCandidate } }) => {
        const borrower = row.original.borrower;
        const docId = row.original.doc_id;
        return (
          <span className="text-xs truncate max-w-48 block" title={docId}>
            {borrower || docId.slice(0, 16)}
          </span>
        );
      },
    },
    {
      id: "section",
      accessorKey: "section_number",
      header: "Section",
      enableSorting: true,
      cell: ({ row }: { row: { original: PreviewCandidate } }) => {
        const c = row.original;
        const display =
          resultGranularity === "clause"
            ? formatSectionWithClause(c.section_number, c.clause_path, c.clause_label)
            : c.section_number;
        return <span className="tabular-nums">{display}</span>;
      },
    },
    {
      id: "heading",
      accessorKey: "heading",
      header: "Heading",
      enableSorting: true,
      cell: ({ getValue }: { getValue: () => unknown }) => (
        <span className="truncate max-w-64 block" title={String(getValue())}>
          {String(getValue())}
        </span>
      ),
    },
    {
      id: "confidence",
      accessorKey: "confidence",
      header: "Confidence",
      enableSorting: true,
      cell: ({ row }: { row: { original: PreviewCandidate } }) => {
        const tier = row.original.confidence_tier;
        return (
          <Badge variant={tier === "high" ? "green" : tier === "medium" ? "orange" : "red"}>
            {(row.original.confidence * 100).toFixed(0)}%
          </Badge>
        );
      },
    },
    {
      id: "tier",
      accessorKey: "confidence_tier",
      header: "Tier",
      enableSorting: true,
      cell: ({ row }: { row: { original: PreviewCandidate } }) => {
        const tier = row.original.confidence_tier;
        return (
          <Badge variant={tier === "high" ? "green" : tier === "medium" ? "orange" : "red"}>
            {tier}
          </Badge>
        );
      },
    },
    {
      id: "verdict",
      header: "Verdict",
      enableSorting: false,
      cell: ({ row }: { row: { original: PreviewCandidate } }) => {
        const c = row.original;
        return (
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                updateVerdictsMut.mutate({
                  previewId: previewId!,
                  verdicts: [{ doc_id: c.doc_id, section_number: c.section_number, verdict: "accepted" }],
                });
              }}
              className={cn(
                "px-1.5 py-0.5 rounded text-xs transition-colors",
                c.verdict === "accepted" ? "bg-glow-green text-accent-green" : "text-text-muted hover:text-accent-green",
              )}
              data-testid={`verdict-accept-${c.doc_id}`}
            >
              Accept
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                updateVerdictsMut.mutate({
                  previewId: previewId!,
                  verdicts: [{ doc_id: c.doc_id, section_number: c.section_number, verdict: "rejected" }],
                });
              }}
              className={cn(
                "px-1.5 py-0.5 rounded text-xs transition-colors",
                c.verdict === "rejected" ? "bg-glow-red text-accent-red" : "text-text-muted hover:text-accent-red",
              )}
              data-testid={`verdict-reject-${c.doc_id}`}
            >
              Reject
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                updateVerdictsMut.mutate({
                  previewId: previewId!,
                  verdicts: [{ doc_id: c.doc_id, section_number: c.section_number, verdict: "deferred" }],
                });
              }}
              className={cn(
                "px-1.5 py-0.5 rounded text-xs transition-colors",
                c.verdict === "deferred" ? "bg-glow-amber text-accent-orange" : "text-text-muted hover:text-accent-orange",
              )}
              data-testid={`verdict-defer-${c.doc_id}`}
            >
              Defer
            </button>
          </div>
        );
      },
    },
  ], [previewId, updateVerdictsMut, resultGranularity]);

  const visibleQueryColumns = useMemo(
    () =>
      queryColumns.filter((column) => {
        const columnId = String(column.id ?? "") as QueryColumnId;
        return queryColumnsVisibility[columnId] ?? true;
      }),
    [queryColumns, queryColumnsVisibility],
  );

  return (
    <div className="h-full flex flex-col overflow-hidden" data-testid="query-tab">
      {/* ── Compact query bar ─────────────────────────────────── */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-surface-1 flex-shrink-0">
        <TextQueryBar
          dsl={dslText}
          onDslChange={setDslText}
          familyId={familyFilter}
          matchCount={queryCountResult.data?.count}
          matchCountLoading={queryCountResult.isFetching}
          errors={validationResult?.errors ?? validateMut.data?.errors ?? []}
          queryCost={queryCountResult.data?.query_cost ?? validationResult?.query_cost}
          className="flex-1 min-w-0"
        />
        <div className="flex items-center gap-1.5">
          <div className="flex items-center gap-0.5 rounded-lg bg-surface-2 p-0.5">
            <button
              type="button"
              onClick={() => {
                scopeTouchedRef.current = true;
                setScopeMode("corpus");
              }}
              className={cn(
                "px-2 py-1 text-xs rounded-md transition-colors",
                effectiveScopeMode === "corpus"
                  ? "bg-surface-0 text-text-primary shadow-sm"
                  : "text-text-muted hover:text-text-secondary",
              )}
              data-testid="query-scope-corpus"
            >
              Corpus
            </button>
            <button
              type="button"
              onClick={() => {
                scopeTouchedRef.current = true;
                setScopeMode("inherited");
              }}
              disabled={!inheritedAvailable}
              className={cn(
                "px-2 py-1 text-xs rounded-md transition-colors disabled:opacity-40",
                effectiveScopeMode === "inherited"
                  ? "bg-surface-0 text-text-primary shadow-sm"
                  : "text-text-muted hover:text-text-secondary",
              )}
              data-testid="query-scope-inherited"
              title={
                inheritedAvailable
                  ? "Scope to parent node results"
                  : "No published parent rule found"
              }
            >
              Inherited
            </button>
          </div>
          {effectiveScopeMode === "inherited" && previewScope.parentFamilyId && (
            <Badge variant="blue" className="text-[10px]">
              from {previewScope.parentFamilyId}
            </Badge>
          )}
        </div>
        <button
          type="button"
          onClick={handleCreatePreview}
          disabled={!familyFilter || !hasAnyFilter || createPreviewMut.isPending}
          className="px-3 py-1.5 bg-accent-blue text-white text-sm rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 flex-shrink-0"
          data-testid="query-preview-btn"
        >
          {createPreviewMut.isPending ? "Creating..." : "Preview"}
        </button>
        <div className="flex items-center gap-0.5 rounded-lg bg-surface-2 p-0.5 flex-shrink-0">
          <button
            type="button"
            onClick={() => setResultGranularity("section")}
            className={cn(
              "px-2 py-1 text-xs rounded-md transition-colors",
              resultGranularity === "section"
                ? "bg-surface-0 text-text-primary shadow-sm"
                : "text-text-muted hover:text-text-secondary",
            )}
          >
            Section
          </button>
          <button
            type="button"
            onClick={() => setResultGranularity("clause")}
            className={cn(
              "px-2 py-1 text-xs rounded-md transition-colors",
              resultGranularity === "clause"
                ? "bg-surface-0 text-text-primary shadow-sm"
                : "text-text-muted hover:text-text-secondary",
            )}
          >
            Clause
          </button>
        </div>
      </div>

      {/* ── Query tools ───────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 py-1.5 border-b border-border bg-surface-1 flex-shrink-0">
        <DslCheatSheet />
        <div className="w-px h-4 bg-border" />
        <div className="relative">
          <button
            type="button"
            onClick={() => setLoadRuleDropdownOpen((p) => !p)}
            className={cn(
              "text-xs transition-colors",
              loadRuleDropdownOpen ? "text-accent-blue" : "text-text-muted hover:text-accent-blue",
            )}
            data-testid="load-rule-dropdown-btn"
          >
            Load Rule...
          </button>
          {loadRuleDropdownOpen && (
            <div className="absolute top-full left-0 mt-1 z-30 w-80 max-h-48 overflow-auto bg-surface-1 border border-border rounded-lg shadow-xl">
              {loadableRules.length === 0 ? (
                <div className="p-3 text-xs text-text-muted">
                  {familyFilter ? "No rules for this scope" : "No rules available"}
                </div>
              ) : (
                loadableRules.map((r) => (
                  <button
                    key={r.rule_id}
                    type="button"
                    onClick={() => {
                      const ruleDsl = r.filter_dsl || r.heading_filter_dsl;
                      if (ruleDsl) setDslText(ruleDsl);
                      const nextScope = (r.ontology_node_id || r.family_id || "").trim();
                      if (nextScope && nextScope !== familyFilter) {
                        onFamilySelect?.(nextScope);
                      }
                      if (r.scope_mode === "inherited" && inheritedAvailable) {
                        scopeTouchedRef.current = true;
                        setScopeMode("inherited");
                      } else {
                        scopeTouchedRef.current = true;
                        setScopeMode("corpus");
                      }
                      setLoadRuleDropdownOpen(false);
                    }}
                    className="w-full text-left px-3 py-2 hover:bg-surface-2 border-b border-border/30 last:border-0"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-text-primary">{r.name || r.rule_id}</span>
                      {!familyFilter && (
                        <Badge variant="default">{r.ontology_node_id || r.family_name || r.family_id}</Badge>
                      )}
                      <Badge variant={r.status === "published" ? "green" : r.status === "draft" ? "orange" : "default"}>
                        {r.status}
                      </Badge>
                    </div>
                    <div className="text-[10px] text-text-muted truncate mt-0.5 font-mono">
                      {(r.filter_dsl || r.heading_filter_dsl).slice(0, 80)}
                    </div>
                  </button>
                ))
              )}
            </div>
          )}
        </div>
        {applyError && (
          <>
            <div className="w-px h-4 bg-border" />
            <span className="text-xs text-accent-red" data-testid="apply-error">{applyError}</span>
          </>
        )}
      </div>

      {/* ── Results area ─────────────────────────────────────── */}
      {previewId ? (
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Tier tabs + search + verdicts */}
          <div className="flex items-center gap-2 px-4 py-2 bg-surface-1 border-b border-border flex-shrink-0">
            {(["all", "high", "medium", "low"] as const).map((tier) => (
              <button
                key={tier}
                type="button"
                onClick={() => setPreviewTierFilter(tier)}
                className={cn(
                  "filter-chip",
                  previewTierFilter === tier && "active",
                )}
                data-testid={`preview-tier-${tier}`}
              >
                {tier === "all" ? "All" : tier.charAt(0).toUpperCase() + tier.slice(1)}
              </button>
            ))}
            <div className="w-px h-4 bg-border" />
            <input
              type="text"
              value={resultSearch}
              onChange={(e) => setResultSearch(e.target.value)}
              placeholder="Filter results..."
              className="px-2 py-1 text-xs bg-surface-2 border border-border rounded-md text-text-primary placeholder:text-text-muted/60 w-48 focus:outline-none focus:ring-1 focus:ring-accent-blue"
              data-testid="result-search"
            />
            <div className="relative" ref={queryColumnsRef}>
              <button
                type="button"
                onClick={() => setQueryColumnsOpen((prev) => !prev)}
                className={cn(
                  "filter-chip",
                  queryColumnsOpen && "active",
                )}
              >
                Columns
              </button>
              {queryColumnsOpen && (
                <div className="absolute top-full left-0 mt-1 z-30 w-44 rounded-lg border border-border bg-surface-1 shadow-xl p-2 space-y-1">
                  {(Object.keys(QUERY_COLUMN_LABELS) as QueryColumnId[]).map((columnId) => {
                    const checked = queryColumnsVisibility[columnId];
                    const disableToggle = checked && visibleQueryColumnCount <= 1;
                    return (
                      <label
                        key={columnId}
                        className={cn(
                          "flex items-center justify-between gap-2 px-2 py-1 rounded text-xs text-text-secondary",
                          disableToggle ? "opacity-60" : "hover:bg-surface-2",
                        )}
                      >
                        <span>{QUERY_COLUMN_LABELS[columnId]}</span>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleQueryColumn(columnId)}
                          disabled={disableToggle}
                          className="accent-accent-blue"
                        />
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
            <div className="ml-auto flex items-center gap-3 text-xs text-text-muted">
              {(verdictCounts.accepted > 0 || verdictCounts.rejected > 0 || verdictCounts.deferred > 0) && (
                <span className="flex items-center gap-1.5">
                  {verdictCounts.accepted > 0 && <span className="text-accent-green">{verdictCounts.accepted} accepted</span>}
                  {verdictCounts.rejected > 0 && <span className="text-accent-red">{verdictCounts.rejected} rejected</span>}
                  {verdictCounts.deferred > 0 && <span className="text-accent-orange">{verdictCounts.deferred} deferred</span>}
                  <span className="text-text-muted">/ {candidates.length}</span>
                </span>
              )}
              <span className="tabular-nums">{totalResults.toLocaleString()} total</span>
            </div>
          </div>

          <div className="flex-1 flex overflow-hidden">
            <div className={cn("flex-1 flex flex-col overflow-hidden", queryReaderOpen && "w-1/2")}>
              {/* DataTable fills remaining space */}
              <div className="flex-1 overflow-hidden">
                <DataTable<PreviewCandidate>
                  columns={visibleQueryColumns}
                  data={sortedCandidates}
                  sorting={sorting}
                  onSortingChange={setSorting}
                  onRowClick={handleCandidateRowClick}
                  selectedRowId={selectedCandidateRowId ?? undefined}
                  focusedRowId={selectedCandidateRowId ?? undefined}
                  getRowId={getPreviewCandidateRowId}
                  emptyMessage="No matching candidates"
                />
              </div>

              {/* Footer: pagination + action buttons */}
              <div className="flex items-center justify-between px-4 py-2 border-t border-border bg-surface-1 flex-shrink-0">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      if (!previewId || !candidatesData) return;
                      setApplyError(null);
                      const hash = previewCandidateHash || candidatesData.candidate_set_hash || "";
                      applyMut.mutate(
                        { previewId, candidateSetHash: hash },
                        {
                          onError: (err) => {
                            const msg = err?.message ?? "Unknown error";
                            if (msg.includes("409") || msg.toLowerCase().includes("expired") || msg.toLowerCase().includes("hash")) {
                              setApplyError("Preview expired or hash mismatch. Please re-create the preview.");
                            } else {
                              setApplyError(msg);
                            }
                          },
                        },
                      );
                    }}
                    disabled={applyMut.isPending}
                    className="px-3 py-1.5 bg-accent-green text-white text-sm rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
                    data-testid="query-apply-btn"
                  >
                    {applyMut.isPending ? "Applying..." : "Apply"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (!previewId) return;
                      canaryMut.mutate({ previewId, limit: 10 });
                    }}
                    disabled={canaryMut.isPending}
                    className="px-3 py-1.5 bg-surface-2 text-text-secondary text-sm rounded-lg hover:text-text-primary transition-colors disabled:opacity-50"
                    data-testid="query-canary-btn"
                  >
                    Canary Apply
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (!familyFilter || !validDslText) return;
                      saveRuleMut.mutate({
                        family_id: familyFilter,
                        ontology_node_id: ontologyNodeIdForPersistence ?? undefined,
                        filter_dsl: validDslText,
                        result_granularity: resultGranularity,
                        heading_filter_ast: currentAst as unknown as Record<string, unknown>,
                        scope_mode: previewScope.scopeMode,
                        parent_family_id: previewScope.parentFamilyId,
                        parent_rule_id: previewScope.parentRuleId,
                        parent_run_id: previewScope.parentRunId,
                      });
                    }}
                    disabled={saveRuleMut.isPending || !familyFilter || !validDslText}
                    className="px-3 py-1.5 bg-surface-2 text-text-secondary text-sm rounded-lg hover:text-text-primary transition-colors disabled:opacity-50"
                    data-testid="query-save-rule-btn"
                  >
                    Save as Rule
                  </button>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-text-muted tabular-nums">
                    {totalResults.toLocaleString()} total rows
                  </span>
                  {totalPages > 1 && (
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        className="btn-ghost"
                        disabled={!hasPrev}
                        onClick={() => handlePageChange(currentPage - 1)}
                        aria-label="Previous page"
                      >
                        Prev
                      </button>
                      <span className="text-xs text-text-secondary tabular-nums px-1">
                        {currentPage + 1} / {totalPages}
                      </span>
                      <button
                        type="button"
                        className="btn-ghost"
                        disabled={!hasNext}
                        onClick={() => handlePageChange(currentPage + 1)}
                        aria-label="Next page"
                      >
                        Next
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {queryReaderOpen && (
              <div className="w-1/2 border-l border-border overflow-hidden">
                <DetachableReader
                  detached={queryDetachedReader}
                  onDetach={() => setQueryDetachedReader(true)}
                  onReattach={() => setQueryDetachedReader(false)}
                  currentLinkId={focusedPreviewLinkId}
                >
                <ReviewPane
                  link={focusedPreviewLink}
                  sectionText={sectionText}
                  sectionFamilies={sectionFamilies}
                  definitions={definitions}
                  comparables={comparablesData?.comparables ?? []}
                  folded={false}
                  redlineActive={false}
                  templateFamily={focusedPreviewLink?.family_id ?? null}
                  highlightMode="query"
                  queryHighlightTerms={clauseHighlightTerms}
                  queryFocusRange={queryFocusRange}
                  queryFocusText={focusedCandidate?.clause_text ?? null}
                />
              </DetachableReader>
            </div>
            )}
          </div>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-sm text-text-muted">
          Enter a DSL query and click Preview to see results
        </div>
      )}
    </div>
  );
}

// ── Coverage tab content ────────────────────────────────────────────────────

function CoverageTabContent({ familyFilter }: { familyFilter?: string }) {
  const [selectedGap, setSelectedGap] = useState<CoverageGap | null>(null);
  const [whyNotOpen, setWhyNotOpen] = useState(false);
  const [selectedRuleId, setSelectedRuleId] = useState<string>("");

  const { data: coverageData, isLoading } = useCoverageGaps(familyFilter);
  const { data: rulesData } = useLinkRules({ familyId: familyFilter });
  const { data: semanticData } = useSemanticCandidates(selectedGap?.family_id ?? "");

  const gaps = coverageData?.gaps ?? [];
  // Sort by facility_size_mm DESC (null last)
  const sortedGaps = useMemo(
    () =>
      [...gaps].sort((a, b) => {
        if (a.facility_size_mm === null && b.facility_size_mm === null) return 0;
        if (a.facility_size_mm === null) return 1;
        if (b.facility_size_mm === null) return -1;
        return b.facility_size_mm - a.facility_size_mm;
      }),
    [gaps],
  );

  // Group gaps by template for display
  const groupedGaps = useMemo(() => {
    const groups = new Map<string, typeof sortedGaps>();
    for (const gap of sortedGaps) {
      const key = gap.template || "Unknown";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(gap);
    }
    return groups;
  }, [sortedGaps]);

  const ruleIdByFamily = useMemo(() => {
    const mapping = new Map<string, string>();
    for (const rule of rulesData?.rules ?? []) {
      const scopeId = String(rule.ontology_node_id || rule.family_id || "").trim();
      if (scopeId && !mapping.has(scopeId)) {
        mapping.set(scopeId, rule.rule_id);
      }
    }
    return mapping;
  }, [rulesData]);

  const effectiveRuleId =
    selectedRuleId ||
    (selectedGap ? (ruleIdByFamily.get(selectedGap.family_id) ?? "") : "") ||
    (rulesData?.rules?.[0]?.rule_id ?? "");

  return (
    <div className="h-full flex flex-col overflow-hidden" data-testid="coverage-tab">
      {/* KPI row */}
      <div className="px-4 pt-3">
        <KpiCardGrid className="grid-cols-3">
          <KpiCard
            title="Total Gaps"
            value={coverageData?.total_gap_docs ?? 0}
            color="red"
          />
          <KpiCard
            title="Gap by Scope"
            value={Object.keys(coverageData?.gap_by_family ?? {}).length}
            color="orange"
          />
          <KpiCard
            title="Coverage %"
            value={`${((coverageData?.coverage_pct ?? 0) * 100).toFixed(1)}%`}
            color="green"
          />
        </KpiCardGrid>
      </div>

      {/* Gap table — grouped by template */}
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10 bg-surface-2">
            <tr>
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Doc</th>
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Heading</th>
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Template</th>
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Nearest Miss</th>
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Fixable</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={5} className="px-3 py-12 text-center text-text-muted text-sm">
                  Loading...
                </td>
              </tr>
            ) : sortedGaps.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-12 text-center text-text-muted text-sm">
                  No coverage gaps found
                </td>
              </tr>
            ) : (
              Array.from(groupedGaps.entries()).map(([template, templateGaps]) => (
                <>
                  {/* Template group header */}
                  <tr key={`group-${template}`} data-testid={`template-group-${template}`}>
                    <td colSpan={5} className="px-3 py-1.5 bg-surface-2/50 text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                      {template} ({templateGaps.length})
                    </td>
                  </tr>
                  {templateGaps.map((gap) => (
                    <tr
                      key={`${gap.doc_id}-${gap.heading}`}
                      onClick={() => {
                        setSelectedGap(gap);
                        setSelectedRuleId(ruleIdByFamily.get(gap.family_id) ?? "");
                        setWhyNotOpen(true);
                      }}
                      className={cn(
                        "border-b border-border/30 transition-colors cursor-pointer hover:bg-surface-2/50",
                        selectedGap?.doc_id === gap.doc_id && "bg-glow-blue",
                      )}
                      data-testid={`gap-row-${gap.doc_id}`}
                    >
                      <td className="px-3 py-2 text-xs font-mono text-text-primary">{gap.doc_id}</td>
                      <td className="px-3 py-2 text-sm text-text-primary truncate max-w-48">{gap.heading}</td>
                      <td className="px-3 py-2 text-sm text-text-secondary">{gap.template}</td>
                      <td className="px-3 py-2">
                        <Badge
                          variant={
                            gap.nearest_miss_score > 0.7
                              ? "orange"
                              : gap.nearest_miss_score > 0.4
                              ? "red"
                              : "default"
                          }
                        >
                          {(gap.nearest_miss_score * 100).toFixed(0)}%
                        </Badge>
                      </td>
                      <td className="px-3 py-2">
                        {gap.is_trivially_fixable && (
                          <Badge variant="green" data-testid={`trivially-fixable-${gap.doc_id}`}>
                            Trivially fixable
                          </Badge>
                        )}
                      </td>
                    </tr>
                  ))}
                </>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Semantic candidates sidebar when gap is selected */}
      {selectedGap && semanticData && semanticData.candidates.length > 0 && !whyNotOpen && (
        <div className="border-t border-border p-3" data-testid="coverage-semantic-candidates">
          <p className="text-xs font-semibold text-text-muted mb-2">Semantic Candidates for {selectedGap.heading}</p>
          <div className="flex gap-2 overflow-x-auto">
            {semanticData.candidates.slice(0, 5).map((c) => (
              <div key={`${c.doc_id}-${c.section_number}`} className="flex-shrink-0 px-2 py-1.5 bg-surface-2 rounded text-xs">
                <p className="text-text-primary truncate max-w-32">{c.heading}</p>
                <Badge variant={c.similarity > 0.8 ? "green" : c.similarity > 0.5 ? "orange" : "red"}>
                  {(c.similarity * 100).toFixed(0)}%
                </Badge>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* WhyNot panel */}
      {whyNotOpen && selectedGap && (
        <WhyNotMatchedPanel
          docId={selectedGap.doc_id}
          sectionNumber={selectedGap.section_number ?? "1.01"}
          ruleId={effectiveRuleId}
          familyId={selectedGap.family_id}
          onClose={() => {
            setWhyNotOpen(false);
            setSelectedGap(null);
          }}
        />
      )}
    </div>
  );
}

// ── Conflicts tab content ───────────────────────────────────────────────────

function ConflictsTabContent({ familyFilter }: { familyFilter?: string }) {
  const [selectedConflict, setSelectedConflict] = useState<ConflictGroup | null>(null);
  const [resolverOpen, setResolverOpen] = useState(false);
  const queryClient = useQueryClient();

  const { data: conflictsData, isLoading } = useConflicts();
  const { data: policiesData } = useConflictPolicies();

  const conflicts = conflictsData?.conflicts ?? [];
  const policies = policiesData?.policies ?? [];

  const POLICY_COLORS: Record<string, "green" | "orange" | "red" | "purple" | "default"> = {
    coexist: "green",
    shared_ok: "green",
    subsumes: "orange",
    warn: "orange",
    exclusive: "red",
    compound_covenant: "purple",
  };

  return (
    <div className="h-full flex flex-col overflow-hidden" data-testid="conflicts-tab">
      {/* Conflicts table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10 bg-surface-2">
            <tr>
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Doc</th>
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Section</th>
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Heading</th>
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Families</th>
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Policy</th>
              <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={6} className="px-3 py-12 text-center text-text-muted text-sm">
                  Loading...
                </td>
              </tr>
            ) : conflicts.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-12 text-center text-text-muted text-sm">
                  No conflicts found
                </td>
              </tr>
            ) : (
              conflicts.map((conflict) => {
                // Find dominant policy
                const dominantPolicy = conflict.policies[0];
                const policyName = dominantPolicy?.policy ?? "unknown";

                return (
                  <tr
                    key={`${conflict.doc_id}-${conflict.section_number}`}
                    onClick={() => {
                      setSelectedConflict(conflict);
                      setResolverOpen(true);
                    }}
                    className={cn(
                      "border-b border-border/30 transition-colors cursor-pointer hover:bg-surface-2/50",
                      selectedConflict?.doc_id === conflict.doc_id &&
                        selectedConflict?.section_number === conflict.section_number &&
                        "bg-glow-blue",
                    )}
                    data-testid={`conflict-row-${conflict.doc_id}`}
                  >
                    <td className="px-3 py-2 text-xs font-mono text-text-primary">
                      {conflict.doc_id}
                    </td>
                    <td className="px-3 py-2 text-sm text-text-primary tabular-nums">
                      {conflict.section_number}
                    </td>
                    <td className="px-3 py-2 text-sm text-text-primary truncate max-w-48">
                      {conflict.heading}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        {conflict.families.map((fam) => (
                          <Badge key={fam} variant="blue">
                            {fam}
                          </Badge>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <Badge variant={POLICY_COLORS[policyName] ?? "default"}>
                        {policyName}
                      </Badge>
                    </td>
                    <td className="px-3 py-2">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedConflict(conflict);
                          setResolverOpen(true);
                        }}
                        className="text-xs text-accent-blue hover:underline"
                        data-testid={`resolve-btn-${conflict.doc_id}`}
                      >
                        Resolve
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Conflict resolver panel */}
      {resolverOpen && selectedConflict && (
        <ConflictResolver
          conflict={selectedConflict}
          policies={policies}
          onResolve={() => {
            setResolverOpen(false);
            setSelectedConflict(null);
            queryClient.invalidateQueries({ queryKey: ["links", "conflicts"] });
            queryClient.invalidateQueries({ queryKey: ["links"] });
          }}
          onClose={() => {
            setResolverOpen(false);
            setSelectedConflict(null);
          }}
        />
      )}
    </div>
  );
}

// ── Sidebar KPI tile — compact KpiCard with sparkline + trend ─────────────

function SidebarKpi({
  label,
  value,
  color,
  sparkline,
  trend,
}: {
  label: string;
  value: number;
  color?: "blue" | "green" | "orange" | "red" | "purple" | "teal";
  sparkline?: number[];
  trend?: number;
}) {
  return (
    <KpiCard
      title={label}
      value={value.toLocaleString()}
      color={color ?? "blue"}
      sparkline={sparkline ?? [value * 0.6, value * 0.7, value * 0.75, value * 0.8, value * 0.85, value * 0.92, value]}
      trend={trend}
    />
  );
}

function toWhyMatchedFactors(
  confidenceBreakdown: Record<string, unknown> | null | undefined,
): import("@/lib/types").WhyMatchedFactor[] {
  if (!confidenceBreakdown || typeof confidenceBreakdown !== "object") {
    return [];
  }
  const breakdown = confidenceBreakdown as Record<string, unknown>;
  const rawFactors = breakdown.factors;
  if (Array.isArray(rawFactors)) {
    return rawFactors
      .filter((item): item is Record<string, unknown> => !!item && typeof item === "object")
      .map((item) => ({
        factor: String(item.factor ?? ""),
        score: Number(item.score ?? 0),
        weight: Number(item.weight ?? 1),
        detail: String(item.detail ?? ""),
        evidence: Array.isArray(item.evidence)
          ? item.evidence.map((entry) => String(entry))
          : [],
      }));
  }

  const numericEntries = Object.entries(breakdown).filter(
    ([key, value]) => key !== "final" && typeof value === "number",
  );
  return numericEntries.map(([key, value]) => ({
    factor: key,
    score: Number(value),
    weight: 1,
    detail: "",
    evidence: [],
  }));
}

// ── Rules tab content ──────────────────────────────────────────────────────

function RulesTabContent({
  familyFilter,
  compareRequestId,
  onOpenInQuery,
}: {
  familyFilter?: string;
  compareRequestId?: number;
  onOpenInQuery?: (ruleId: string, familyId?: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "draft" | "published" | "archived">("all");
  const [compareRuleIds, setCompareRuleIds] = useState<[string, string] | null>(null);
  const [starterKitOpen, setStarterKitOpen] = useState(false);
  const [detailRuleId, setDetailRuleId] = useState<string | null>(null);
  const [deleteConfirmRuleId, setDeleteConfirmRuleId] = useState<string | null>(null);
  const [editingDsl, setEditingDsl] = useState<string | null>(null);
  const [editValidationErrors, setEditValidationErrors] = useState<string[]>([]);

  const { data: rulesData, isLoading } = useLinkRules({
    familyId: familyFilter,
    status: statusFilter === "all" ? undefined : statusFilter,
  });
  const publishMut = usePublishRuleMutation();
  const archiveMut = useArchiveRuleMutation();
  const cloneMut = useCloneRuleMutation();
  const deleteMut = useDeleteRuleMutation();
  const updateRuleMut = useUpdateRuleMutation();
  const validateDslMut = useValidateDslMutation();

  const [focusedRuleIdx, setFocusedRuleIdx] = useState(0);
  const editDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset edit state when detail panel changes
  useEffect(() => {
    setEditingDsl(null);
    setEditValidationErrors([]);
  }, [detailRuleId]);

  const rules = rulesData?.rules ?? [];
  const filteredRules = useMemo(() => {
    if (!search.trim()) return rules;
    const q = search.toLowerCase();
    return rules.filter(
      (r) =>
        r.rule_id.toLowerCase().includes(q) ||
        r.family_name.toLowerCase().includes(q) ||
        String(r.ontology_node_id ?? "").toLowerCase().includes(q) ||
        (r.filter_dsl || r.heading_filter_dsl).toLowerCase().includes(q),
    );
  }, [rules, search]);

  useEffect(() => {
    if (!compareRequestId || filteredRules.length < 2) return;
    setCompareRuleIds([filteredRules[0].rule_id, filteredRules[1].rule_id]);
  }, [compareRequestId, filteredRules]);

  // Keyboard shortcuts
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;

      switch (e.key) {
        case "j":
        case "ArrowDown":
          e.preventDefault();
          setFocusedRuleIdx((prev) => Math.min(prev + 1, filteredRules.length - 1));
          break;

        case "k":
        case "ArrowUp":
          e.preventDefault();
          setFocusedRuleIdx((prev) => Math.max(prev - 1, 0));
          break;

        case "p":
          e.preventDefault();
          // Publish focused rule
          if (filteredRules.length > 0) {
            const rule = filteredRules[focusedRuleIdx];
            if (rule && rule.status === "draft") publishMut.mutate(rule.rule_id);
          }
          break;

        case "c":
          e.preventDefault();
          // Compare focused rule with the next rule
          if (filteredRules.length >= 2 && focusedRuleIdx < filteredRules.length - 1) {
            const ruleA = filteredRules[focusedRuleIdx];
            const ruleB = filteredRules[focusedRuleIdx + 1];
            if (ruleA && ruleB) setCompareRuleIds([ruleA.rule_id, ruleB.rule_id]);
          }
          break;

        case "a":
          e.preventDefault();
          // Archive focused rule if it's published
          if (filteredRules.length > 0) {
            const rule = filteredRules[focusedRuleIdx];
            if (rule && rule.status === "published") archiveMut.mutate(rule.rule_id);
          }
          break;

        case "Enter":
          e.preventDefault();
          // Toggle detail panel for focused rule
          if (filteredRules.length > 0) {
            const rule = filteredRules[focusedRuleIdx];
            if (rule) setDetailRuleId((prev) => prev === rule.rule_id ? null : rule.rule_id);
          }
          break;

        case "d":
          e.preventDefault();
          // Delete focused rule (non-published only)
          if (filteredRules.length > 0) {
            const rule = filteredRules[focusedRuleIdx];
            if (rule && rule.status !== "published") setDeleteConfirmRuleId(rule.rule_id);
          }
          break;

        case "Escape":
          e.preventDefault();
          if (deleteConfirmRuleId) {
            setDeleteConfirmRuleId(null);
          } else {
            setDetailRuleId(null);
          }
          break;
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [filteredRules, focusedRuleIdx, publishMut, archiveMut, deleteConfirmRuleId]);

  return (
    <div className="h-full flex overflow-hidden" data-testid="rules-tab">
      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Filters */}
        <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-surface-1">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search rules..."
            className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-text-primary w-48 focus:outline-none focus:ring-1 focus:ring-accent-blue"
            data-testid="rules-search"
          />
          {(["all", "draft", "published", "archived"] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(s)}
              className={cn("filter-chip", statusFilter === s && "active")}
              data-testid={`rules-status-${s}`}
            >
              {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>

        {/* Rules table */}
        <div className="flex-1 overflow-auto">
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10 bg-surface-2">
              <tr>
                <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Rule</th>
                <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Scope</th>
                <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">DSL</th>
                <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Status</th>
                <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">v</th>
                <th className="px-3 py-2.5 text-left text-[10px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <SkeletonTableRows rows={8} cols={6} />
              ) : filteredRules.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-12 text-center text-text-muted text-sm">
                    No rules found
                  </td>
                </tr>
              ) : (
                filteredRules.map((rule, ruleIdx) => {
                  return (
                    <tr
                      key={rule.rule_id}
                      className={cn(
                        "border-b border-border/30 hover:bg-surface-2/50 cursor-pointer",
                        ruleIdx === focusedRuleIdx && "bg-surface-2/80 ring-1 ring-accent-blue/30",
                        detailRuleId === rule.rule_id && "border-l-2 border-l-accent-blue"
                      )}
                      onClick={() => {
                        setFocusedRuleIdx(ruleIdx);
                        setDetailRuleId((prev) => prev === rule.rule_id ? null : rule.rule_id);
                      }}
                      data-testid={`rule-row-${rule.rule_id}`}
                    >
                      <td className="px-3 py-2">
                        <div className="text-xs font-semibold text-text-primary" title={rule.rule_id}>
                          {rule.name || rule.rule_id}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant="blue">{rule.ontology_node_id || rule.family_name || rule.family_id}</Badge>
                      </td>
                      <td className="px-3 py-2 max-w-48">
                        <code className="text-xs" data-testid={`rule-dsl-${rule.rule_id}`}>
                          {tokenizeDsl(rule.filter_dsl || rule.heading_filter_dsl).map((tok, idx) => (
                            <span key={idx} className={DSL_TOKEN_CLASSES[tok.type]}>
                              {tok.text}
                            </span>
                          ))}
                        </code>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1">
                          <Badge
                            variant={
                              rule.status === "published"
                                ? "green"
                                : rule.status === "draft"
                                  ? "orange"
                                  : "default"
                            }
                          >
                            {rule.status}
                          </Badge>
                          {rule.status === "published" && (
                            <span className="text-[10px] text-text-muted" title="Locked — published rules cannot be edited">
                              {rule.locked_by ? `locked by ${rule.locked_by}` : "locked"}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-xs text-text-muted tabular-nums">
                        v{rule.version}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1.5">
                          {rule.status === "draft" && (
                            <button
                              type="button"
                              onClick={() => publishMut.mutate(rule.rule_id)}
                              disabled={publishMut.isPending}
                              className="text-xs text-accent-green hover:underline"
                              data-testid={`rule-publish-${rule.rule_id}`}
                            >
                              Publish
                            </button>
                          )}
                          {rule.status === "published" && (
                            <button
                              type="button"
                              onClick={() => archiveMut.mutate(rule.rule_id)}
                              disabled={archiveMut.isPending}
                              className="text-xs text-text-muted hover:text-accent-red"
                              data-testid={`rule-archive-${rule.rule_id}`}
                            >
                              Archive
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => {
                              if (filteredRules.length >= 2) {
                                const other = filteredRules.find((r) => r.rule_id !== rule.rule_id);
                                if (other) setCompareRuleIds([rule.rule_id, other.rule_id]);
                              }
                            }}
                            className="text-xs text-text-muted hover:text-accent-blue"
                            data-testid={`rule-compare-${rule.rule_id}`}
                          >
                            Compare
                          </button>
                          <button
                            type="button"
                            onClick={() => cloneMut.mutate(rule.rule_id)}
                            disabled={cloneMut.isPending}
                            className="text-xs text-text-muted hover:text-accent-blue"
                            data-testid={`rule-clone-${rule.rule_id}`}
                          >
                            Clone
                          </button>
                          {rule.status !== "published" && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setDeleteConfirmRuleId(rule.rule_id);
                              }}
                              className="text-xs text-text-muted hover:text-accent-red"
                              data-testid={`rule-delete-${rule.rule_id}`}
                            >
                              Delete
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpenInQuery?.(rule.rule_id, rule.ontology_node_id || rule.family_id);
                            }}
                            className="text-xs text-text-muted hover:text-accent-blue"
                            data-testid={`rule-open-query-${rule.rule_id}`}
                          >
                            Query
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Rule detail panel */}
        {detailRuleId && (() => {
          const rule = rules.find((r) => r.rule_id === detailRuleId);
          if (!rule) return null;
          const dsl = rule.filter_dsl || rule.heading_filter_dsl;
          return (
            <div className="border-t border-border bg-surface-1 flex-shrink-0 max-h-72 overflow-auto" data-testid="rule-detail-panel">
              <div className="flex items-center justify-between px-4 py-2 border-b border-border/50">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-text-primary">{rule.name || rule.rule_id}</span>
                  <span className="text-[10px] font-mono text-text-muted" title={rule.rule_id}>{rule.rule_id.slice(0, 8)}</span>
                  <Badge variant="blue">{rule.ontology_node_id || rule.family_name || rule.family_id}</Badge>
                  <Badge variant={rule.status === "published" ? "green" : rule.status === "draft" ? "orange" : "default"}>
                    {rule.status}
                  </Badge>
                  <span className="text-xs text-text-muted tabular-nums">v{rule.version}</span>
                </div>
                <button
                  type="button"
                  onClick={() => setDetailRuleId(null)}
                  className="text-xs text-text-muted hover:text-text-primary"
                  aria-label="Close detail panel"
                >
                  Esc to close
                </button>
              </div>
              <div className="px-4 py-3 space-y-3">
                {/* Editable rule name */}
                <div>
                  <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">Name</span>
                  <input
                    type="text"
                    defaultValue={rule.name || ""}
                    placeholder={rule.rule_id}
                    onBlur={(e) => {
                      const newName = e.target.value.trim();
                      if (newName !== (rule.name || "")) {
                        updateRuleMut.mutate({ ruleId: rule.rule_id, data: { name: newName } });
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                    }}
                    className="mt-1 w-full text-xs bg-surface-2 rounded-lg px-3 py-1.5 border border-border focus:border-accent-blue focus:outline-none"
                    data-testid="rule-name-input"
                  />
                </div>
                {/* Full DSL — editable for draft/archived rules */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">DSL</span>
                    <div className="flex items-center gap-2">
                      {editingDsl === null && (
                        <button
                          type="button"
                          onClick={() => {
                            if (rule.status === "published") return;
                            setEditingDsl(dsl);
                            setEditValidationErrors([]);
                          }}
                          disabled={rule.status === "published"}
                          title={rule.status === "published" ? "Archive or clone to edit" : "Edit DSL"}
                          className={cn(
                            "text-[10px] hover:underline",
                            rule.status === "published"
                              ? "text-text-muted/50 cursor-not-allowed"
                              : "text-accent-blue",
                          )}
                        >
                          Edit
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => navigator.clipboard.writeText(editingDsl ?? dsl)}
                        className="text-[10px] text-accent-blue hover:underline"
                      >
                        Copy
                      </button>
                      <button
                        type="button"
                        onClick={() => onOpenInQuery?.(rule.rule_id, rule.ontology_node_id || rule.family_id)}
                        className="text-[10px] text-accent-blue hover:underline"
                      >
                        Open in Query
                      </button>
                    </div>
                  </div>
                  {editingDsl !== null ? (
                    <div className="space-y-2">
                      <textarea
                        value={editingDsl}
                        onChange={(e) => {
                          const val = e.target.value;
                          setEditingDsl(val);
                          if (editDebounceRef.current) clearTimeout(editDebounceRef.current);
                          editDebounceRef.current = setTimeout(() => {
                            if (!val.trim()) {
                              setEditValidationErrors(["DSL cannot be empty"]);
                              return;
                            }
                            validateDslMut.mutate(val, {
                              onSuccess: (result) => {
                                setEditValidationErrors(
                                  result.errors?.map((err: { message: string }) => err.message) ?? [],
                                );
                              },
                              onError: () => {
                                setEditValidationErrors(["Validation request failed"]);
                              },
                            });
                          }, 300);
                        }}
                        className="w-full text-xs font-mono bg-surface-2 rounded-lg p-3 border border-accent-blue/50 focus:border-accent-blue focus:outline-none resize-y min-h-[60px]"
                        rows={3}
                        data-testid="rule-edit-dsl-textarea"
                      />
                      {editValidationErrors.length > 0 && (
                        <div className="text-xs text-accent-red space-y-0.5">
                          {editValidationErrors.map((err, i) => (
                            <p key={i}>{err}</p>
                          ))}
                        </div>
                      )}
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => {
                            updateRuleMut.mutate(
                              { ruleId: rule.rule_id, data: { filter_dsl: editingDsl } },
                              {
                                onSuccess: () => {
                                  setEditingDsl(null);
                                  setEditValidationErrors([]);
                                },
                              },
                            );
                          }}
                          disabled={
                            updateRuleMut.isPending ||
                            editValidationErrors.length > 0 ||
                            !editingDsl.trim() ||
                            editingDsl === dsl
                          }
                          className="px-3 py-1 text-xs bg-accent-blue text-white rounded-lg hover:bg-accent-blue/90 disabled:opacity-50"
                          data-testid="rule-edit-save"
                        >
                          {updateRuleMut.isPending ? "Saving..." : "Save"}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setEditingDsl(null);
                            setEditValidationErrors([]);
                          }}
                          className="px-3 py-1 text-xs text-text-secondary hover:text-text-primary"
                          data-testid="rule-edit-cancel"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <pre className="text-xs font-mono bg-surface-2 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-words border border-border">
                      <code>
                        {tokenizeDsl(dsl).map((tok, idx) => (
                          <span key={idx} className={DSL_TOKEN_CLASSES[tok.type]}>
                            {tok.text}
                          </span>
                        ))}
                      </code>
                    </pre>
                  )}
                </div>
                {/* Metadata grid */}
                <div className="grid grid-cols-3 gap-x-4 gap-y-1 text-xs">
                  <div>
                    <span className="text-text-muted">Granularity</span>
                    <p className="text-text-primary">{rule.result_granularity}</p>
                  </div>
                  <div>
                    <span className="text-text-muted">Pass rate</span>
                    <p className="text-text-primary tabular-nums">{rule.last_eval_pass_rate != null ? `${(rule.last_eval_pass_rate * 100).toFixed(0)}%` : "—"}</p>
                  </div>
                  <div>
                    <span className="text-text-muted">Created</span>
                    <p className="text-text-primary">{rule.created_at ? new Date(rule.created_at).toLocaleDateString() : "—"}</p>
                  </div>
                </div>
                {/* Keyword anchors */}
                {rule.keyword_anchors.length > 0 && (
                  <div>
                    <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">Keyword anchors</span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {rule.keyword_anchors.map((kw) => (
                        <Badge key={kw} variant="default">{kw}</Badge>
                      ))}
                    </div>
                  </div>
                )}
                {/* DNA phrases */}
                {rule.dna_phrases.length > 0 && (
                  <div>
                    <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">DNA phrases</span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {rule.dna_phrases.map((ph) => (
                        <Badge key={ph} variant="default">{ph}</Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })()}

        {/* Starter kit panel */}
        {familyFilter && starterKitOpen && (
          <div className="border-t border-border p-3">
            <StarterKitPanel
              familyId={familyFilter}
              onCreateRule={(dsl) => {
                // Clone the generated DSL as a new draft rule via the search bar
                setSearch(dsl);
              }}
              onClose={() => setStarterKitOpen(false)}
            />
          </div>
        )}
        {familyFilter && !starterKitOpen && (
          <div className="border-t border-border px-4 py-2">
            <button
              type="button"
              onClick={() => setStarterKitOpen(true)}
              className="text-xs text-accent-blue hover:underline"
              data-testid="show-starter-kit"
            >
              Show Starter Kit
            </button>
          </div>
        )}
      </div>

      {/* Rule compare overlay */}
      {compareRuleIds && (
        <RuleCompareView
          ruleIdA={compareRuleIds[0]}
          ruleIdB={compareRuleIds[1]}
          onClose={() => setCompareRuleIds(null)}
        />
      )}

      {/* Delete confirmation dialog */}
      {deleteConfirmRuleId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-surface-1 border border-border rounded-xl p-6 max-w-sm shadow-xl">
            <h3 className="text-sm font-semibold text-text-primary mb-2">Delete Rule?</h3>
            <p className="text-xs text-text-secondary mb-4">
              This will permanently delete rule{" "}
              <code className="font-mono text-text-primary">{deleteConfirmRuleId}</code>. This cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeleteConfirmRuleId(null)}
                className="px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  deleteMut.mutate(deleteConfirmRuleId, {
                    onSuccess: () => {
                      if (detailRuleId === deleteConfirmRuleId) setDetailRuleId(null);
                      setDeleteConfirmRuleId(null);
                    },
                  });
                }}
                disabled={deleteMut.isPending}
                className="px-3 py-1.5 bg-accent-red text-white text-xs rounded-lg hover:bg-accent-red/90 disabled:opacity-50"
              >
                {deleteMut.isPending ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Dashboard tab content ──────────────────────────────────────────────────

function DashboardTabContent({
  familyFilter,
  onOpenExport,
}: {
  familyFilter?: string;
  onOpenExport: () => void;
}) {
  return (
    <div className="h-full flex flex-col overflow-auto" data-testid="dashboard-tab">
      {/* Header with export button */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-surface-1">
        <h3 className="text-sm font-semibold text-text-primary">Analytics Dashboard</h3>
        <button
          type="button"
          onClick={onOpenExport}
          className="px-3 py-1.5 bg-surface-2 text-text-secondary text-sm rounded-lg hover:text-text-primary transition-colors"
          data-testid="dashboard-export-btn"
        >
          Export / Import
        </button>
      </div>

      {/* Main content */}
      <div className="flex-1 p-4 space-y-4">
        <BatchRunDashboard scopeFilter={familyFilter} />
      </div>
    </div>
  );
}
