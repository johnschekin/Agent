# Indebtedness Covenant — Multi-Source Concept Trace

## Purpose

This trace documents the analysis of the Indebtedness Covenant (Negative Covenants – Indebtedness) across all corpus tiers. The indebtedness covenant is the **largest basket ecosystem** in a credit agreement — typically 10-15 separate baskets, each with its own sizing, conditions, and structural protections. Analyzed as Batch B alongside Liens because liens baskets mechanically mirror debt baskets.

The indebtedness covenant interacts with essentially every other analyzed concept area:
- **Incremental Facilities** (Phase 2) — IED and ratio debt are external analogues of the accordion
- **Available Amount** (Phase 1) — AA creates a debt prong; contribution debt levers equity contributions that also build AA
- **ECF Sweep** (Phase 3) — voluntary prepayments build incremental capacity; debt sweep captures non-permitted debt
- **Financial Definitions** (Batch A) — EBITDA growers inflate every basket simultaneously
- **Financial Covenant** (Batch A) — debt basket exclusions allow unrecognized leverage

---

## Key Discovery: Basket Stacking

The most important finding from the indebtedness analysis is that **individual basket sizes are misleading**. Total debt capacity is determined by the **combinatorial maximum** of all baskets including reclassification.

KCT Category 2 identifies these stacking vectors:
- Opening first lien leverage multiple / 1L incurrence ratio basket
- Pari passu capacity from multiple baskets
- Structurally senior capacity from multiple baskets
- Investment basket reclassification to debt
- Restricted payment reclassification to debt
- Grandfathered contribution debt capacity

In the most aggressive deals, a borrower can incur debt under the general basket + ratio debt + IED + acquisition debt + contribution debt + AA debt prong + reclassified RP capacity + reclassified investment capacity — each from a separate provision.

---

## Tier 1 — Institutional Authority

### Key Credit Terms

Multiple risk items across 3 categories:

- **Cat 1 Item 5**: Debt incurred under fixed baskets excluded from financial covenant calculation — allows hidden leverage
- **Cat 2**: Stacking and reclassification opportunities (detailed above)
- **Cat 2 (DDTL)**: "once a DDTL commitment or DDTL is tested via a ratio debt incurrence test...then such incurrence test (and all ratio debt incurrence tests going forward) should account for all DDTL commitments or DDTLs at all times going forward" — permanent ratchet risk
- **Cat 4 Item 13**: No maturity/WAL limitations for ratio-based baskets — maturity wall risk
- **Cat 4 Item 14**: Ability to incur debt secured by non-collateral assets — strips unencumbered value

### DLS Preferred Financing Terms

**Row 79 — Indebtedness:**
- Bank preferred: (i) credit facilities, (ii) fixed dollar general basket, (iii) acquisition debt on agreed terms
- Alternative: Add IED, ratio debt basket (unlimited subject to leverage), incurred acquisition ratio basket

**Row 12 — IED:**
- Bank preferred: "No such basket"
- Alternative: IED in form of notes/loans, pari or junior, subject to same incremental terms, no MFN on pari notes

### PC Term Comparison

**Lines 380-405 — Detailed indebtedness market standards:**
- IED/Ratio Debt: MFN generally applies even in Aggressive UMM/BSLR; 'no worse' and FCCR prongs rejected
- Sale-leaseback: Aggressive UMM/BSLR often uncapped; otherwise capped
- Securitization: Typically capped; avoid all-asset securitizations
- Seller debt/earnouts: Aggressive — if not 'Indebtedness', no cap; otherwise capped/subordinated
- Intercompany: Loans to non-loan parties capped/shared with investments; subordination required
- Contribution debt: Flag for client; Aggressive = 100% unsecured, no outside date
- **Line 405 focus**: Non-loan-party debt, structurally senior debt, debt secured by non-collateral, pari debt not subject to closing leverage

---

## Tier 2 — Analytical Methodology

### Review Template

13 dedicated rows (72-84) — the most comprehensive coverage of any single covenant:

- **Row 72**: Main indebtedness covenant — list all baskets
- **Row 73**: Ratio debt — amount, aligned with incremental ratio prongs
- **Row 74**: Ratio debt — non-guarantor cap (shared with acquisition debt)
- **Row 75**: Ratio debt — terms (WAL/M, MFN, intercreditor)
- **Row 76**: Contribution debt — reduce to 100%, remove liens carveout
- **Row 77**: Incurred acquisition debt — amount
- **Row 78**: Incurred acquisition debt — non-guarantor cap
- **Row 79**: Assumed acquisition debt — uncapped if not in contemplation
- **Row 80**: Securitization facilities
- **Row 81**: Sale-leaseback debt
- **Row 82**: General basket — size with growers, flex to reduce
- **Row 83**: Non-guarantor/foreign subsidiary debt
- **Row 84**: Other — AA basket, Available RP Capacity basket, earnout treatment

### LME Provision Language

Line 142: Intercompany debt subordination — "any intercompany debt incurred under any debt basket that is owed by a loan party to a nonloan party subsidiary be subordinated to the loans."

---

## Tier 3 — Educational Foundation

### Learning Material

Sections 25.1-25.8 cover the full basket taxonomy:
1. Ratio Debt / IED
2. Capital leases / purchase money debt
3. General Debt
4. Contribution Debt
5. Restricted Payments Debt basket
6. Assumed Debt
7. Acquisition Debt
8. Debt of Non-Loan Parties, Foreign Subs, and JV Debt

**Key insights:**
- Line 1417: General debt basket unused capacity reallocates to incremental
- Line 1574: Refinancing indebtedness requires no financial metric or basket usage
- Line 1126: Borrowers add subsidiaries as guarantors for additional debt flexibility
- Line 805: Capital leases and small foreign working capital lines typically grandfathered

---

## Tier 4 — Deal Data

### DealData.json (62 private credit deals)

**100% coverage** on all major basket fields — the highest data completeness of any concept area:

| Basket | Coverage | Key Pattern |
|--------|----------|-------------|
| General Debt Basket | 62/62 | $X / Y% EBITDA (15-40% range) |
| Capital Lease | 62/62 | $X / Y% EBITDA (12-24% range) |
| IED | 62/62 | Unlimited subject to leverage test + structural protections |
| Incurred Acquisition Debt | 62/62 | Mix of 'None' and complex ratio provisions |
| Assumed Acquisition Debt | 62/62 | Small dollar or unlimited subject to leverage |
| Non-Guarantor Debt | 62/62 | $X / Y% EBITDA, often shared caps |
| Contribution Debt | 62/62 | 'None' or '100%; must be unsecured' |
| Earn-Out/Seller Notes | 62/62 | Unsecured, dollar cap |
| Other Debt Baskets | 62/62 | Intercompany carve-outs, guarantee nuances |
| Ratio Debt | 0/62 | Empty — data embedded in IED/acquisition fields |

### Expert Extractions

| Feature | Geneva | Rinchem | Scientific Games |
|---------|--------|---------|------------------|
| **General Basket** | $450M / 100% EBITDA with pari liens | Reallocates to incremental | — |
| **Contribution Debt** | 100% cash + FMV contributions | — | 100% (same as Geneva) |
| **Intercompany** | Note + pledged if >$25M | — | — |
| **Foreign Sub** | — | $10M / 10% foreign total assets | — |
| **Material Indebtedness** | $113M / 25% EBITDA | $30M / 50% EBITDA | — |

---

## Model Implications

### What generalizes

1. **Component decomposition works**: 13 structural components (plus reclassification), each with corpus statistics and market ranges. The largest component set so far.

2. **Relationship types sufficient**: 6 of 8 types used. `shares_capacity_with` and `reclassifiable_to` are heavily used — these are the stacking/redesignation relationships that define the indebtedness covenant's unique behavior.

3. **Market segmentation holds**: Clear LMM→BSL progression from small fixed baskets to unlimited ratio-based capacity.

### Indebtedness-specific observations

1. **Stacking is the real risk model**: Individual baskets are building blocks; the risk comes from their combinatorial usage. A data model that only tracks individual basket sizes misses the stacking dimension.

2. **Ratio debt converts a finite system to infinite**: Below ratio debt, the indebtedness covenant is a collection of fixed baskets with EBITDA growers. Ratio debt makes capacity infinite (subject only to leverage), which fundamentally changes the covenant's protective value.

3. **100% DealData coverage**: The indebtedness covenant has the richest and most structured DealData of any concept area — every deal has every basket field populated. This makes it the best candidate for systematic extraction and comparison.

---

## Data Quality Notes

1. **Ratio Debt field empty**: The DealData "Ratio Debt" field is empty across all 62 deals, but ratio-based capacity appears within IED and acquisition debt definitions. Future parsing should extract ratio provisions from these fields.

2. **Shared caps require careful parsing**: Non-guarantor caps are often "shared with acquisition debt and general debt" — the effective cap for any one basket depends on usage of others.

3. **Reclassification not separately captured**: DealData has a "Permitted re-designation" field but it's sparse. Reclassification rights are embedded in basket definitions and require text parsing.
