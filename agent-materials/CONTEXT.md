# Leveraged Finance Corpus — Reference Inventory

> **Portability**: This document is self-contained. It provides everything needed to understand the corpus without accessing the underlying files. Structural snapshots and representative excerpts are authoritative summaries — not placeholders for "go read the file."

---

## 1. Corpus Overview

This directory contains a curated collection of leveraged finance materials spanning bank negotiating positions, risk taxonomies, market positioning guides, analytical methodologies, educational references, deal data, labeled credit agreements, and live negotiation transcripts.

The materials originate from different institutional vantage points — a bank's internal legal team, a law firm's private credit practice, an analyst's extraction methodology, a training program for junior attorneys — and cover both private credit and broadly syndicated loan (BSL) markets.

A domain expert is available for clarification on any concept in these materials.

---

## 2. Document Hierarchy & Provenance

Not all documents carry equal weight. When documents present different views of the same concept, this hierarchy reflects provenance and reliability:

### Tier 1 — Institutional Authority (What the bank's position IS)

| Document | Role | Provenance |
|----------|------|------------|
| **PC Term Comparison** | Term background and market positioning guide across 4 segments (LMM/CMM/UMM/BSL) | Developed by industry-leading partners at a law firm expert in both private credit and broadly syndicated loans. Intended to introduce syndicated loan partners to the private credit context. |
| **Key Credit Terms** | Risk taxonomy — the bank's internal checklist of what constitutes lender risk | Bank internal legal. 50 items across 5 risk categories + Appendix I. Shows what the bank actually escalates on. |


### Tier 2 — Analytical Methodology (How terms are analyzed)

| Document | Role | Provenance |
|----------|------|------------|
| **Review Template** | 163-term extraction + analysis methodology with expert guidelines | Analyst methodology. Three layers per term: template_fields, analysis_guidelines, background. **Scope limitation**: relevant to engagement papers, term sheets, and fee letters — NOT credit agreements. |
| **LME Provision Language** | Liability management exercise protection definitions, drafting guidance, and sample clauses | Legal practitioner reference. Covers all major LME protection types with real credit agreement language. |

### Tier 3 — Educational Foundation (Domain knowledge)

| Document | Role | Provenance |
|----------|------|------------|
| **Learning Material** | Comprehensive reference (362KB, 119 sections) | Broadest coverage of leveraged finance concepts — ~10x more topics than the Intro Guide. |
| **Intro Guide (Signal)** | Training primer on negative covenants and leakage | Written as secondment training material for junior attorneys. Educational, not authoritative on market position. Defines relationships between concepts and the "leakage" framework. |



---

## 3. Term Categorization Framework

### By Functional Role

Terms serve different functions in a credit agreement:

**Economic Terms** (lender-facing):
- Basket sizes (dollar amounts, EBITDA percentages)
- Ratios (leverage ratios, coverage ratios)
- Pricing (margins, floors, fees)
- Sweep mechanics (ECF sweep percentages, stepdowns)
- These are the terms discussed in credit committee. They determine the lender's actual economic exposure.

**Internal Legal Issues** (handled on issues-list calls):
- Sacred rights formulations
- Cured default provisions
- Net short lender disenfranchisement
- Assignment consent mechanics
- These can live anywhere in the agreement and often don't appear in high-level term summaries.

**Operational/Agency Issues** (Article 2 mechanics + Articles 8-9):
- Borrowing notice requirements (# of business days, time cutoffs)
- Repayment timelines and interest period mechanics
- Agent resignation provisions
- Waterfall provisions
- These are the plumbing of the credit facility — critical for loan operations but rarely negotiated.

### By Credit Agreement Article / Operations Function

| Function | Articles | Examples |
|----------|----------|----------|
| **Ops/Agency** | Article 2 (borrowing mechanics) + Articles 8-9 (agent, misc.) | Borrowing notices, repayment, interest periods, agent resignation |
| **Deal Team** | Definitions (Art. 1), Affirmative Covenants (Art. 5), Negative Covenants (Art. 6/7) | EBITDA definition, basket sizes, covenant tests |
| **Internal Legal** | Can live anywhere | Cured defaults, sacred rights, net short provisions, LME protections |

---

## 4. Corpus Inventory — Structural Snapshots

### `Credit Agreement Terms.md` — Blank Extraction Template

**Size**: 7KB | **Type**: Checklist | **Tier**: 5

A blank template listing ~120 fields organized into sections: Facility Structure, Pricing, Mandatory Prepayments, Financial Definitions, each Negative Covenant, Financial Covenants, Events of Default, Voting/Amendments, Assignments, Collateral. Contains no values or analysis.

---


### `Review Template.json` — Analysis Methodology

**Size**: 122KB | **Type**: Structured JSON | **Terms**: 163 | **Tier**: 2

The most granular term inventory in the corpus. Each of 163 terms has three layers:

| Field | Content |
|-------|---------|
| `term` | Term name |
| `template_fields` | What to extract — the sponsor's draft language with `[•]` placeholders |
| `analysis_guidelines` | Expert instructions on what to look for, what to flag, what's market |
| `background` | Educational context, historical evolution, practical implications |

**Scope limitation**: This template is relevant to **engagement papers, term sheets, and fee letters** — NOT credit agreements. A term that only appears in a credit agreement (e.g., deep definitional cross-references, specific covenant sub-baskets) won't be covered here. Conversely, terms like "Commitment and giveaway" and "Countersign date" are engagement-paper concepts that have no analog in a credit agreement.

**Term inventory** (163 terms across ~15 logical sections):

| Section | Terms | Examples |
|---------|-------|----------|
| Commitment/Transaction | 12 | Debt quantum, commitment/giveaway, disqualified institutions, expense reimbursement |
| Facility Structure | 10 | Revolver mechanics, DDTL, swinglines, LCs |
| Incremental | 13 | Freebie, prepayments, ratio, DDTLs, racking/stacking, MFN, ROFR, inside maturity |
| Mandatory Prepayments | 10 | Asset sale sweep (coverage, threshold, reinvestment, stepdowns), ECF sweep (holiday, percentages, threshold, credits) |
| Financial Definitions | 12 | Pro forma calcs, EBITDA (addbacks, synergies, run-rate), leverage definitions, cash netting |
| Negative Covenants — Debt | 12 | General basket, ratio debt, contribution debt, CLO debt, non-guarantor debt |
| Negative Covenants — Liens | 5 | General basket, ratio liens, permitted holders |
| Negative Covenants — RPs/Investments/JDP | 15 | RP baskets, investment baskets, JDP, available amount mechanics |
| Negative Covenants — Asset Sales/Merger/Affiliates | 8 | Disposition baskets, merger covenant, affiliate transactions |
| Financial Covenants | 6 | Test type, levels, equity cure, DDTL testing |
| Events of Default | 5 | Cross-default, judgment, cure provisions |
| Voting/Amendments | 8 | Required lenders, sacred rights, Serta, snooze/drag |
| Assignments | 6 | Consent rights, DQ lenders, buybacks, affiliated lenders |
| Defined Terms | 6 | Available Amount, Change of Control, Material Subsidiaries, Permitted Holders, Required Lenders, Unrestricted Subsidiaries |
| Other | 10 | J. Crew, Chewy, LCT, stacking, reclassification |

---

### `Key Credit Terms.md` — Risk Taxonomy

**Size**: 30KB | **Type**: Markdown | **Items**: 50 across 5 categories + Appendix I | **Tier**: 1

The bank's internal checklist organized into 5 risk categories. Each item describes a specific pattern in credit agreements that constitutes a lender risk, with detailed explanations of what to look for and why it matters.

#### Category 1: Covenant Protection (8 items)

What it covers: Structural weaknesses in financial covenant protections that allow borrowers to avoid meaningful financial testing.

| Item | Risk Pattern | Detail |
|------|-------------|--------|
| 1 | No financial covenants for RCFs/TLAs, or breach only causes drawstop (not Event of Default) | The financial covenant is the only maintenance test — if it's toothless, lenders have no early warning mechanism |
| 2 | Equity cure abuse | (a) Cure doesn't require injection of new equity after closing; (b) Cure documented as subordinated shareholder debt or holdco debt — potentially phantom cures that don't actually strengthen the credit |
| 3 | RCF springer threshold issues | Springing trigger > 40% of RCF size, based on fixed amount instead of proportional, allows cash netting, excludes capex draws, permits post-period repayment to avoid testing |
| 4 | Deemed cure via updated financials | Borrower delivers new management accounts showing compliance "at any point in time" — allows cherry-picking favorable snapshots |
| 5 | Fixed basket debt excluded from financial covenant | Freebie, non-guarantor, general, or acquisition debt not counted in leverage calculations — financial covenant becomes meaningless |
| 6 | Revenue addbacks to EBITDA | COVID/pandemic revenue adjustments, revenue synergies from new contracts — inflates EBITDA beyond economic reality |
| 7 | Uncapped cost savings/synergy addbacks | Including Reg S-X adjustments (2021 expansion) — management gains discretion to override EBITDA caps |
| 8 | Unrestricted sub dividend manipulation | Assets moved to unsub → sold → proceeds returned as "dividend income" → counted in CNI/EBITDA — circular value extraction |

#### Category 2: Ability to Increase Leverage/Debt (4 items)

What it covers: Mechanisms that allow borrowers to incur additional debt beyond what lenders expected at closing — through basket stacking, high-water-mark ratchets, and structural subordination.

| Item | Risk Pattern | Detail |
|------|-------------|--------|
| 1 | Basket stacking and non-true-total-debt calculations | Total debt excludes 2L, revolver, working capital, sub debt, unsecured notes. Baskets can be stacked or reclassified across pari/structurally senior capacity. Specific items: opening 1L leverage multiple, pari passu capacity components, structurally senior capacity, investment → pari reallocation, RP → pari reallocation, grandfathered contribution debt |
| 2 | DDTL ratio test gaming | If ratio test is at commitment (not draw), borrower can obtain $50M commitments on day 1, another $50M on day 2 (ignoring day 1), etc. — circumventing the incurrence test entirely |
| 3 | Preferred stock at non-guarantor subs | Uncapped issuance structurally senior to lenders, excluded from covenant calculations |
| 4 | High-water-mark ratchets | Grower baskets (tied to EBITDA) permanently reset to highest-ever EBITDA, never decrease. If freebie = max($X, 100% EBITDA), one good quarter permanently inflates all future basket capacity |

#### Category 3: Dilution of Lender Rights (15 items)

What it covers: Erosion of lender voting power, sacred rights, consent requirements, and the ability to enforce credit agreement protections. Includes LME (liability management exercise) vulnerability.

| Item | Risk Pattern | Detail |
|------|-------------|--------|
| 1 | Cured Default provisions | See Appendix I — full decision-tree framework |
| 2 | Statute of limitations on defaults | 2-year limit not tied to notice delivery, or no carve-out for known-but-unreported defaults |
| 3 | Net Short Lender disenfranchisement | NSL provisions impacting voting rights and transfer ability without carve-outs for regulated banks, revolving lenders, and market-making |
| 4 | TRS/CDS restrictions on lenders | Bank prohibited from hedging positions via derivatives with disqualified institutions |
| 5 | Sacred rights changes without all-lender vote | Modifications to payment amounts, maturity, pro rata sharing, waterfall without full consent |
| 6 | Snooze & drag/deemed consent | Non-responding lenders deemed to have consented — CLO-accommodation mechanism weaponized for structural changes |
| 7 | Prospective lenders voting pre-commitment | "Pro forma required lenders" formulation allows parties to vote before actually becoming lenders |
| 8 | MAE merger-agreement carve-outs | Requiring "disproportionate" impact — import of M&A standards into credit agreement context |
| 9 | No notice of default covenant | No affirmative obligation to inform lenders of existing defaults |
| 10 | Borrowing despite defaults | No drawstop for continuing defaults (not just Events of Default) |
| 11 | Force majeure guarantee release / MAE carve-outs | War, hostilities, pandemic carve-outs releasing guarantors or negating MAC triggers |
| 12 | Change of control dilution | Non-standard CoC formulations, "permitted change of control" exceptions |
| 13 | Multi-sponsor consent for assignments/participations | Consent rights that don't fall away on payment/bankruptcy EoD, non-voting participations requiring consent, no "not unreasonably withheld" qualifier, DQ list requires naming entities |
| 14 | Excluded Matter/Permitted Transaction carve-outs | Pandemic/terrorism/force majeure carve-outs preventing EoD triggers |
| 15 | Serta subordination | Borrower buyback provisions used for debt-for-debt exchange creating super-priority lender group without non-participating lender consent |

#### Category 4: Impact on Collateral Protection (12 items)

What it covers: Value leakage through restricted payments, investments, and asset transfers that move value from inside the credit group (where lenders have claims) to outside (where they don't). Also covers structural subordination via lien subordination and maturity games.

Key items: Unlimited dividends without baskets/ratios, unlimited unrestricted sub investments, available amount growing from asset sale proceeds or permitted indebtedness, admin agent forced to subordinate liens, holdco debt servicing at opco level, PIK interest mechanics, absence of default blockers on material RP baskets, no maturity/WAL limits on ratio debt, incremental pari capacity via junior debt paydown, ABL pari/senior liens on ABL priority collateral, forced intercreditor without required lender vote, debt secured by non-collateral assets.

#### Category 5: Other Risk (4 items)

What it covers: Residual risk items.

Key items: EoD carve-outs for loss of lien/priority broader than possessory collateral or UCC continuation, limited sanctions representations, P&I payment conditioned on agent notice/invoice, KYC information restrictions limited to commitment signing date.

#### Appendix I: Cured Default Framework

A decision-tree for evaluating cured default provisions across 3 dimensions:
1. **Breadth**: All EoDs curable vs. subset (excluding financial covenant, misrep, loan mechanics) vs. specific EoD only
2. **Carve-outs**: Knowledge qualifier (including deliberate/intentional variants), other protective carve-outs
3. **Other factors**: Post-acceleration cures, precedent with same sponsor, ABL borrowing base certificate coverage

---

### `PC Term Comparison.md` — Market Positioning Guide

**Size**: 29KB | **Type**: Markdown | **Tier**: 1

**Provenance**: Developed by industry-leading partners at a law firm expert in both private credit and broadly syndicated loans. Intended to introduce syndicated loan partners to the private credit context.

Compares credit terms across 4 market segments with Conservative / Typical / Aggressive ranges:

| Segment | Definition | Characteristics |
|---------|-----------|-----------------|
| **LMM** | EBITDA < $50M | Tightest lender protections |
| **CMM** | EBITDA $50-100M | Middle ground |
| **UMM/BSLR** | EBITDA > $100M | Competes with BSL market, more borrower-friendly |
| **BSL** | Broadly syndicated loans | Public market, most borrower-friendly, highly standardized |

**Coverage** (major concept sections): Applicable Margin, Asset Sales (dispositions to non-loan parties, securitizations, sale-leasebacks, 75% test), Available Amount (starter, builder, usage conditions by segment), EBITDA definition (addbacks by segment), Financial Covenant (springing financial covenant, equity cure), Incremental/Accordion (freebie, ratio, MFN, maturity limitations), Indebtedness (general basket, ratio basket, contribution debt, non-guarantor debt), Investments (non-guarantor, permitted acquisitions, general basket, unrestricted subs), Leverage Ratios (definitions, cash netting), Liens (general basket, ratio liens), Restricted Payments (general basket, available amount, ratio basket), Transactions with Affiliates, Unrestricted Subsidiaries.

**Representative snippet** (Available Amount section):
```
Starter:
  UMM/BSLR: Aggressive 40-50% EBITDA; Otherwise 10-30%
  CMM/LMM: Typically 5-25% EBITDA
Builder:
  Typically Retained ECF based but for UMM/BSLR may also be 50% of CNI.
  Retained ECF should only be increased by retained percentage of ECF
  and not the net ECF unswept amount.
```

---

### `Learning_Material.md` — Comprehensive Reference

**Size**: 362KB | **Type**: Markdown | **Sections**: 119 headers, 231 sub-headers, 157 bold emphasis points | **Tier**: 3

The largest single reference document. Covers the full spectrum of leveraged finance concepts from basic facility structure through advanced covenant mechanics, including: credit agreement anatomy, loan types, pricing mechanics, financial covenant mechanics, EBITDA definitions, negative covenant framework, basket mechanics, cross-reference resolution, LCT provisions, collateral packages, intercreditor agreements, syndication, amendments, events of default, and workout mechanics.

---

### `Intro Guide (Signal).md` — Conceptual Foundation

**Size**: 124KB | **Type**: Markdown (noise-stripped variant of 133KB original) | **Tier**: 3

**Framing**: Written as secondment training material for junior attorneys at a law firm. The document teaches concepts progressively, building from fundamentals to advanced mechanics.

Defines the relationships between concepts (negative covenants → baskets → conditions → ratios) and the **leakage framework** — how value moves from inside the credit group to outside.

The Signal variant strips noise (quiz questions, blank grids, rhetorical questions) while preserving all substantive content. The original `Intro Guide.md` is also available.

---

### `LME Provision Language.md` — Liability Management Protections

**Size**: 30KB | **Type**: Markdown (converted from DOCX) | **Tier**: 2

Covers all major Liability Management Exercise (LME) protection types with definitions, drafting considerations, and sample clause language from real credit agreements.

**LME Protection Categories:**

| Category | Protection Type | Named After | What It Prevents |
|----------|----------------|-------------|------------------|
| **Drop-Down** | J.Crew blocker | J.Crew | IP/asset leakage to unrestricted subsidiaries, then monetized through structurally senior debt |
| **Drop-Down** | Chewy blocker | Chewy | Automatic release of subsidiary guarantors when equity is partially transferred (making them non-wholly-owned) |
| **Drop-Down** | Pluralsight extension | Pluralsight | Extends J.Crew protection to ALL non-guarantor subsidiaries (not just unrestricted subs) |
| **Drop-Down** | Envision investment cap | Envision | Caps investment basket usage for unrestricted sub transfers |
| **Uptier** | Serta blocker | Serta (2020) | Requires affected lender consent for amendments subordinating debt in right of lien or payment priority |
| **Uptier** | NYDJ blocker | NYDJ | Includes pro rata sharing and waterfall provisions in sacred rights |
| **Double-Dip/Pari-Plus** | At Home subordination | At Home | Requires all intercompany debt from loan parties to non-loan party subs be subordinated |
| **Double-Dip/Pari-Plus** | Unsub debt restriction | — | Prohibits unrestricted subs from holding debt recourse to restricted group |
| **General** | Non-pro-rata purchase restrictions | — | Limits assignment provisions from being used for non-pro-rata LME exchanges |
| **General** | Wesco/Incora voting manipulation blocker | Wesco/Incora | Restricts issuing additional voting debt to manipulate Required Lender thresholds |
| **General** | "Effect of" sacred rights language | — | Extends sacred rights to amendments that have the "effect of" modifying protected provisions |
| **General** | Better Health amend-and-extend blocker | Better Health | Prevents using extension provisions for non-pro-rata LME exchanges |
| **General** | Omni-Blocker | Spirit Airlines (2025) | Catch-all anti-LME covenant targeting both the end (non-pro-rata LME) and the means (known routes) |

Each protection type includes: definition, drafting considerations, and sample clause language from real credit agreements (Getty Images 2025, RackSpace 2024, Blend Labs 2021, etc.).

---

---

---

---


---

## 6. The Anatomy of a Credit Agreement

| Article | Content | Information Density |
|---------|---------|-------------------|
| **Recitals** | Parties, transaction description, facility sizes, borrowing entities, agreement date, lenders, jurisdiction | **Medium** — NOT boilerplate. Contains or cross-references key deal parameters. |
| **Article 1** | **Definitions** — 30-80 pages of defined terms | Very High — The real covenants live here. "Permitted Indebtedness" might be 5 pages. |
| **Article 2** | Loan mechanics — borrowing, repayment, interest, fees, incremental | High — Borrowing notice requirements, interest periods. |
| **Article 3** | Conditions precedent to closing and borrowing | Medium — Certain funds provisions, solvency certificates. |
| **Article 4** | Representations and warranties | Low-Medium — MAC definitions, sanctions reps. |
| **Article 5** | Affirmative covenants — reporting, insurance, compliance | Medium — Lender calls, financial statement delivery timelines. |
| **Article 6/7** | **Negative covenants** — debt, liens, RPs, investments, dispositions | Very High — Every basket, condition, and exception. |
| **Article 7/8** | **Events of Default** — cross-default, payment default, covenant breach | High — Default blockers, cure provisions, grace periods. |
| **Article 9/10** | Miscellaneous — amendments, voting, assignments, buybacks | High — Sacred rights, DQ lenders. |

### Structural Complexity

1. **Definitions are the real covenants**: The debt covenant says "no Indebtedness except Permitted Indebtedness." The 30-page definition of "Permitted Indebtedness" is where all the baskets and conditions live.

2. **Multi-hop cross-references**: "Subject to the conditions in Section 6.01(b)(xxvi)" requires resolving the reference. But Section 6.01(b)(xxvi) might say "Indebtedness permitted under clause (a) of the definition of 'Permitted Indebtedness'" — which itself cross-references back to another section.

3. **Basket interactions**: The "Available Amount" basket feeds into RPs, investments, AND junior debt prepayments. The "general debt basket" might cross-reference unused capacity from the "general investment basket."

4. **Context-dependent meaning**: "$50 million / 100% of EBITDA" means "the greater of" in some contexts and "the lesser of" in others. The disambiguating word might be paragraphs away.

5. **Meaningful absence**: No MFN protection on incremental debt IS a finding — "None."

6. **Market-segment-dependent interpretation**: A $50M EBITDA deal with a 100% EBITDA freebie basket is aggressive. The same basket in a $500M deal is typical.

### The Leakage Framework

**Leakage** is the movement of value from inside the credit group (where lenders have claims) to outside (where they don't):

- **Up** (to equity holders): Restricted Payments — dividends, buybacks, distributions
- **Down** (to subsidiaries): Investments — particularly in unrestricted subsidiaries
- **Laterally** (to other creditors): Junior Debt Prepayments — paying off subordinated debt early
- **Out** (to third parties): Asset Sales, Transactions with Affiliates

Each negative covenant restricts one leakage vector. Baskets create exceptions. The interplay between restrictions and exceptions is where the complexity lives.

---

## 7. Formatting Metadata as Signals

Highlighting, font formatting, and bold text in source documents carry meaning:

- **Key Credit Terms**: Footnotes contain critical contextual information (e.g., footnote 14 on Serta explains the full mechanics of how the transaction worked).
- **PC Term Comparison**: Bold/underline formatting distinguishes segment names, conservative/typical/aggressive labels, and key warnings.

---

## 8. File Locations

```
/Users/johnchtchekine/Projects/Neutron/docs/Unsupervised Learning Training Set/
├── agent-materials/                          <- Primary corpus directory
│   ├── CONTEXT.md                            <- This file
│   ├── Review Template.json                  <- Analysis methodology, 163 terms
│   ├── Key Credit Terms.md                   <- Risk taxonomy, 50 items
│   ├── PC Term Comparison.md                 <- Term and Market guide (LMM/CMM/UMM/BSL)
│   ├── Learning_Material.md                  <- Comprehensive reference, 362KB
│   ├── Intro Guide (Signal).md               <- Noise-stripped variant, 124KB
│   ├── LME Provision Language.md             <- LME protections
│   
│   
│
│
└── LME Provision Language.md                 <- LME protections (converted from DOCX)

```
