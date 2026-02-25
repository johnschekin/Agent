/**
 * Deterministic seed dataset definitions for E2E tests.
 *
 * All IDs are predictable and stable across runs so tests can reference
 * known values without querying first.
 *
 * Convention:
 * - Link IDs:   LINK-001, LINK-002, ...
 * - Family IDs: FAM-indebtedness, FAM-liens, FAM-dividends, ...
 * - Rule IDs:   RULE-001, RULE-002, ...
 * - Doc IDs:    DOC-001, DOC-002, ...
 * - Run IDs:    RUN-001, RUN-002, ...
 * - Session IDs: SES-001, SES-002, ...
 */

// ─── Families ────────────────────────────────────────────

export const FAMILIES = {
  indebtedness: "FAM-indebtedness",
  liens: "FAM-liens",
  dividends: "FAM-dividends",
  investments: "FAM-investments",
  mergers: "FAM-mergers",
  asset_sales: "FAM-asset-sales",
  affiliate_transactions: "FAM-affiliate-transactions",
  reporting: "FAM-reporting",
} as const;

// ─── Documents ───────────────────────────────────────────

export const DOCS = Array.from({ length: 20 }, (_, i) => ({
  doc_id: `DOC-${String(i + 1).padStart(3, "0")}`,
  borrower: `Test Borrower ${i + 1}`,
}));

// ─── Links ───────────────────────────────────────────────

export const MINIMAL_LINKS = [
  {
    link_id: "LINK-001",
    family_id: FAMILIES.indebtedness,
    doc_id: "DOC-001",
    section_number: "7.01",
    heading: "Indebtedness",
    confidence: 0.92,
    confidence_tier: "high",
    status: "active",
  },
  {
    link_id: "LINK-002",
    family_id: FAMILIES.indebtedness,
    doc_id: "DOC-002",
    section_number: "7.01",
    heading: "Limitation on Indebtedness",
    confidence: 0.85,
    confidence_tier: "high",
    status: "active",
  },
  {
    link_id: "LINK-003",
    family_id: FAMILIES.liens,
    doc_id: "DOC-001",
    section_number: "7.02",
    heading: "Liens",
    confidence: 0.88,
    confidence_tier: "high",
    status: "active",
  },
  {
    link_id: "LINK-004",
    family_id: FAMILIES.liens,
    doc_id: "DOC-003",
    section_number: "7.02",
    heading: "Limitation on Liens",
    confidence: 0.72,
    confidence_tier: "medium",
    status: "active",
  },
  {
    link_id: "LINK-005",
    family_id: FAMILIES.dividends,
    doc_id: "DOC-001",
    section_number: "7.06",
    heading: "Restricted Payments",
    confidence: 0.91,
    confidence_tier: "high",
    status: "active",
  },
  {
    link_id: "LINK-006",
    family_id: FAMILIES.dividends,
    doc_id: "DOC-004",
    section_number: "7.06",
    heading: "Dividends and Distributions",
    confidence: 0.55,
    confidence_tier: "medium",
    status: "pending_review",
  },
  {
    link_id: "LINK-007",
    family_id: FAMILIES.indebtedness,
    doc_id: "DOC-005",
    section_number: "7.01",
    heading: "Debt Limitations",
    confidence: 0.45,
    confidence_tier: "low",
    status: "pending_review",
  },
  {
    link_id: "LINK-008",
    family_id: FAMILIES.investments,
    doc_id: "DOC-001",
    section_number: "7.04",
    heading: "Investments",
    confidence: 0.89,
    confidence_tier: "high",
    status: "active",
  },
  {
    link_id: "LINK-009",
    family_id: FAMILIES.mergers,
    doc_id: "DOC-002",
    section_number: "7.05",
    heading: "Fundamental Changes",
    confidence: 0.78,
    confidence_tier: "medium",
    status: "unlinked",
  },
  {
    link_id: "LINK-010",
    family_id: FAMILIES.asset_sales,
    doc_id: "DOC-003",
    section_number: "7.07",
    heading: "Asset Sales",
    confidence: 0.82,
    confidence_tier: "high",
    status: "active",
  },
];

// ─── Rules ───────────────────────────────────────────────

export const RULES = [
  {
    rule_id: "RULE-001",
    family_id: FAMILIES.indebtedness,
    heading_filter_ast: {
      type: "group",
      operator: "or",
      children: [
        { type: "match", value: "Indebtedness" },
        { type: "match", value: "Limitation on Indebtedness" },
        { type: "match", value: "Debt" },
      ],
    },
    status: "published",
    version: 1,
  },
  {
    rule_id: "RULE-002",
    family_id: FAMILIES.liens,
    heading_filter_ast: {
      type: "group",
      operator: "or",
      children: [
        { type: "match", value: "Liens" },
        { type: "match", value: "Limitation on Liens" },
      ],
    },
    status: "published",
    version: 1,
  },
  {
    rule_id: "RULE-003",
    family_id: FAMILIES.dividends,
    heading_filter_ast: {
      type: "group",
      operator: "or",
      children: [
        { type: "match", value: "Restricted Payments" },
        { type: "match", value: "Dividends" },
      ],
    },
    status: "draft",
    version: 1,
  },
];

// ─── Confidence tiers ────────────────────────────────────

export const CONFIDENCE_THRESHOLDS = {
  high: 0.8,
  medium: 0.5,
  low: 0.0,
} as const;
