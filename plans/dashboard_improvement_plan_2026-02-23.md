# Dashboard Improvement Plan (2026-02-23)

## Objective

Upgrade the dashboard into a reliable, fast operator console for ongoing ontology-linking waves on the current full corpus baseline (12,583 docs), with clear quality and release gates.

## Current Baseline (Observed)

- Frontend is route-rich and feature-rich, but large table/list views are mostly non-virtualized.
- Backend serves broad analytics and review endpoints, but several routes recompute expensive scans per request.
- Review endpoints repeatedly scan evidence JSONL files in Python.
- Job orchestration is in-memory and restart-volatile.
- API test coverage is concentrated in review ops; many endpoints have no integration coverage.
- Observability is minimal (limited structured logging, no request/query latency metrics).

## Target Outcomes

- P95 dashboard page load (cached) under 1.5s for overview/explorer/review views.
- P95 API latency under 500ms for common endpoints and under 1.5s for heavy analytic endpoints.
- No browser jank on 1,000+ row interactions (virtualized rendering).
- Job state survives restarts and remains race-safe under concurrent polling/SSE.
- Contract-tested API surface with deterministic schemas and CI gates.

## Workstreams

### WS1: Frontend Performance and UX

#### Scope

- Virtualize large row collections in reusable table/list primitives.
- Upgrade document picker UX for reader flows.
- Reduce perceived latency via selective query prefetch.
- Normalize loading/error behavior across pages.

#### Primary files

- `dashboard/src/components/tables/DataTable.tsx`
- `dashboard/src/app/search/page.tsx`
- `dashboard/src/app/reader/page.tsx`
- `dashboard/src/components/detail/DocumentDetailPanel.tsx`
- `dashboard/src/components/strategy/StrategyDetailPanel.tsx`
- `dashboard/src/app/layout.tsx`
- `dashboard/src/components/layout/ViewContainer.tsx`

#### Milestones

1. Virtualized `DataTable` with stable row heights and overscan controls.
2. Virtualized KWIC/search result rendering for grouped and flat modes.
3. Searchable, virtualized reader document picker (replace large native select behavior).
4. Hover/focus prefetch for document and strategy detail panels.
5. Shared page shell for loading/error states with one top-level error boundary.

#### Acceptance criteria

- Smooth scroll at 60fps target on 1,000-row datasets on standard dev hardware.
- Time-to-interactive improvement of at least 30% on explorer/search pages.
- No full-page error crashes from API failures; graceful fallback shown in shell.

### WS2: Backend Performance and Caching

#### Scope

- Add TTL caching for high-cost aggregate endpoints.
- Minimize repeated evidence scans by introducing an indexed cache layer.
- Add pagination short-circuit behavior and bounded responses.

#### Primary files

- `dashboard/api/server.py`

#### Milestones

1. TTL cache wrappers on overview/stats/quality/edge-case aggregates.
2. Evidence cache/index abstraction for review endpoints.
3. Early-exit pagination behavior once page limit is satisfied.
4. Optional filtered heatmap parameters to bound query and payload sizes.

#### Acceptance criteria

- Aggregate endpoint cache-hit ratio above 70% under normal dashboard usage.
- `review/evidence` P95 response time cut by at least 50% on repeated queries.
- `rows_scanned` drops materially for paginated endpoints (instrumented and logged).

### WS3: Reliability, Jobs, and Concurrency Safety

#### Scope

- Harden in-memory job manager with persistence and lock discipline.
- Improve health endpoint to include corpus/ontology/workspace readiness checks.

#### Primary files

- `dashboard/api/server.py`

#### Milestones

1. Persist job metadata/state (lightweight local backing store).
2. Add lock-protected job mutation/read paths for runner + SSE + polling.
3. Expand `/api/health` payload with dependency-level readiness.

#### Acceptance criteria

- Jobs survive process restart with status/history intact.
- No inconsistent job states under concurrent stream + poll load tests.
- Health endpoint indicates actionable readiness for corpus, ontology, strategies, feedback caches.

### WS4: API Contracts, Testing, and Observability

#### Scope

- Add response models for major API surfaces.
- Expand integration test coverage beyond review routes.
- Add structured request/query latency logging and slow-query alerts.

#### Primary files

- `dashboard/api/server.py`
- `tests/test_dashboard_review_ops.py`
- new: `tests/test_dashboard_api.py`

#### Milestones

1. Pydantic response models for high-traffic endpoints.
2. Integration tests for overview/documents/search/definitions/quality/jobs/ontology/review.
3. Structured request logging (request_id, endpoint, duration, status).
4. Query timing instrumentation for heavy DuckDB operations and threshold alerts.

#### Acceptance criteria

- CI has passing integration coverage for core dashboard endpoints.
- Contract regressions fail fast in CI.
- Endpoint and query latency logs are present and searchable.

## Phased Execution Plan

### Phase A (Week 1): Baseline and Fast Wins

- Add latency instrumentation and structured request logs.
- Add benchmark script/checklist for key API endpoints and front-end routes.
- Implement pagination short-circuit in evidence endpoints.
- Add virtualized rendering for the largest table/list path first (`DataTable`).

Gate:
- Baseline + post-change latency report checked into `plans/`.

### Phase B (Weeks 2-3): Core Performance and Reliability

- Complete virtualization for search/KWIC and reader picker upgrade.
- Add TTL caches for heavy aggregate endpoints.
- Introduce evidence cache/index layer.
- Add job persistence + lock safety.

Gate:
- P95 API and page-load targets met for primary routes.

### Phase C (Weeks 4-5): Contracts and QA Hardening

- Add response models and endpoint integration tests.
- Extend health checks and operational diagnostics.
- Add slow-query detection/alerts and runbook updates.

Gate:
- CI contract suite green; no critical dashboard watchdog items.

### Phase D (Week 6): Operator Polish and Release

- Cohort/filter state consistency improvements across pages.
- Final UX polish for review workflows and failure states.
- Release checklist completion and handoff docs.

Gate:
- Release checklist items for dashboard marked complete.

## Prioritized Backlog (Top 12)

1. Virtualize `DataTable` rows.
2. Virtualize search/KWIC lists.
3. Replace reader doc selector with searchable virtualized picker.
4. Add request and query latency instrumentation.
5. Add aggregate TTL caching.
6. Add evidence cache/index for review routes.
7. Add early-exit pagination in evidence feeds.
8. Persist jobs and add concurrency locks.
9. Expand `/api/health` dependency checks.
10. Add API response models for major routes.
11. Add broad dashboard API integration test suite.
12. Add slow-query alerting thresholds and runbook ops notes.

## Success Metrics (Track Weekly)

- Frontend:
  - P95 route load time by page.
  - Browser memory footprint on 1,000-row interactions.
  - UI thread long-task count.
- Backend:
  - P95 latency by endpoint.
  - Cache hit ratio by endpoint group.
  - Average rows scanned per paginated response.
  - Query slow-log count by threshold bucket.
- Quality:
  - Dashboard API test pass rate and coverage trend.
  - Production error rate by route.
  - Job recovery success after restart.

## Risks and Mitigations

- Risk: virtualization refactor changes table behavior.
- Mitigation: snapshot tests for sorting/filter/pagination interactions before merge.

- Risk: cache staleness in review flows.
- Mitigation: explicit TTL + file timestamp invalidation + manual refresh controls.

- Risk: job persistence introduces migration complexity.
- Mitigation: start with append-only JSON store and migrate to SQLite only if needed.

## Deliverables

- Code changes in frontend and API layers.
- New dashboard API integration tests.
- Performance benchmark report before/after.
- Updated runbook + release checklist dashboard section sign-off.
