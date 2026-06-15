# MA Driver's Manual Updates — Project Brief, PRD & Tradeoffs Analysis

**Status:** Working prototype (internal)

**Audience:** RMV leadership and IT/web stakeholders

**Purpose:** Decision-support for finishing and extending the tool

**Prepared:** June 2026 by Lab @ MassDOT Fellow Samuel Grunebaum

---

## Executive brief

*One page for decision-makers. The full product requirements and cost analysis
follow as backup ([Sections 1–8](#1-executive-summary)).*

> **See it live:** **https://szgrune.github.io/rmv-manual-updates/web/** — the
> working app is the fastest way to grasp this.

### The problem

Massachusetts has on the order of **5 million licensed drivers**. Most earned
their license as teenagers and haven't opened the driver's manual since. Yet the
rules keep changing — hands-free phone requirements, new protections for cyclists
and other vulnerable road users, cannabis and impaired-driving guidance — and
today there is **no easy way for a driver to find out what changed since they learned to drive.** The official manual is ~140 pages, republished as a whole, with the
changes buried inside it.

### The solution

A simple public website answers one question: *"What has changed in the driver's
manual since I got my license?"* A driver enters the year they were licensed and
immediately sees a clear, organized summary of what's new, updated, or removed —
with **every item linked straight to the exact page of the official RMV manual.**
It is an access-and-orientation layer on top of the RMV's own content; the manual
remains the source of truth.

### Why MassDOT, why now

- **It serves people the RMV already serves** — whether court-mandated
  driver-education participants or newly relocated drivers — and routes them to
  official content faster.
- **It's a low-risk, high-visibility example of responsible AI in state
  government:** built quickly with AI assistance, grounded in the official
  document, with a citation on every claim, and designed intentionally to serve public interest.
- **A working prototype already exists.** This prototype was built in the first week of the fellowship — a demonstration of what AI-assisted development makes possible. Production-quality work — security, accessibility, self-service tools for RMV staff, additional languages — is addressed in the subsequent sections of this brief.

### What it costs

- **To operate: under $100 a year.** The only recurring cost is the AI analysis
  that runs when a new manual is released — a few dollars per run.
- **To finish: one intern-summer**, with light in-house IT/web follow-up. No new
  budget of consequence.
- **IT footprint: negligible.** The public site is static — no new server,
  database, or software licenses required (it relies only on the existing MassDOT OpenAI license to stay operational).

### What we're asking

Help move this from prototype to public service by:

1. **Endorsing it to the RMV** and connecting us with the right digital/content owners;
2. **Approve completion** of the remaining work through this summer's internship plus
   light in-house follow-up.

*Questions of accuracy, equity, and legal exposure are real and have been thought
through; they are addressed candidly in [Section 3](#3-concerns--counterarguments)
and the appendix.*

---

*Full PRD & tradeoffs analysis follows.*

---

> **Note on figures.** Time and cost figures in this document are planning
> estimates, expressed as ranges. Labor rates reflect the assumptions confirmed
> for this project (see [Cost & effort model](#4-cost--effort-model)). LLM/API
> pricing is approximate and should be verified against current vendor rates
> before budgeting.

---

## 1. Executive summary

The **Driver's Manual Updates by Year** app answers a single, common question for
Massachusetts drivers: *"What has changed in the driver's manual since I got my
license?"* A user enters the year they were licensed, and the app shows a clear,
organized summary of what is new, updated, expanded, or removed in the current
manual compared to the edition closest to that year — with each quoted change
linked back to the exact page of the official RMV PDF.

**How it works (in brief).** A small Python pipeline ingests each manual PDF,
uses a large language model (LLM) to compare a newer edition against an older one
and describe the substantive changes, and exports the result to a lightweight
website. Every quoted change carries a **page-level citation** that deep-links to
the official manual PDF, so the authoritative source is always one click away.

**How it was built.** The prototype was developed rapidly by co-developing with
agentic AI coding tools (Claude Code / Codex). This is the same workflow proposed
for finishing the product, and it is the primary reason the build estimates below
are well under traditional software timelines.

**Primary users.** Newly relocated and returning drivers, driver-education
students and instructors, citizens taking court mandated driving education, mature drivers or people who have had their licenses for a long time, and RMV content owners — see [user typologies](#key-user-typologies).

**Current status.** The English app is functional with four editions (2007, 2017,
2023, 2026), search, change-type filters, share/print-to-PDF, page citations, and
a curated content pass that removes low-value "statistics changed" noise. What
remains is to make it **operationally self-service** (so RMV staff can add a new
manual each year without a developer), to make the **images and text content easily editable**, and
to **broaden coverage** (more editions, accessibility, and languages).

---

## 2. Project brief

### Overview

The tool turns a tedious, error-prone task — manually comparing a ~140-page legal
document against a prior edition — into a guided, citable summary. It is designed
to be **informational**, not authoritative: the official RMV manual remains the
source of truth, and the app's job is to *route users to the relevant official
content faster*, with citations on every claim.

The system has two halves:

- **Build pipeline (back office).** `extract_pdfs.py` → `analyze_changes.py` →
  `export_json.py` (~1,900 lines of Python) over a local SQLite database, plus a
  permanent **manual-override layer** so any human correction survives future
  re-runs, and a **citation matcher** that pins each quoted change to its physical
  PDF page (currently matching 296 of 300 quotes, ~98%).
- **Public website (front office).** A fast, dependency-light static site
  (`index.html`, `app.js`, `styles.css`) — no server or database required to
  serve the public experience.

### Key user typologies

| User | What they need | How the app serves them |
|---|---|---|
| **Returning driver** (licensed years ago, re-engaging) | A quick read on what's changed during their time away | Enter your license year → "Changes Since {year}" |
| **Newly relocated driver** | Orientation to MA-specific rules | Closest-edition comparison + Rules of the Road surfaced first |
| **Driver-education student / instructor** | Teach to the *current* manual, flag what's new | Filterable, search-able change list with citations |
| **Court-mandated driving-education participant** | Confirm the current rules they're required to learn | Authoritative, citation-backed summary of what's current |
| **Mature / long-licensed driver** | Catch up on rules that changed over many years | Earliest-edition comparison surfaces the most accumulated change |
| **RMV content owner / staff** | Add each new manual; fix misplaced images and text | Self-service admin + image/content CMS (planned) |

### How it works (pipeline detail)

1. **Extract** — each manual PDF is parsed into structured sections, text, page
   numbers, and images.
2. **Analyze** — the newer manual is chunked and compared, chunk-by-chunk,
   against the *complete* text of the older manual; the LLM returns a structured
   list of substantive changes (new / updated / expanded / removed).
3. **Curate** — human corrections are captured permanently in an overrides layer;
   low-value items (e.g., refreshed statistics) are pruned.
4. **Cite & export** — every quote is matched to its PDF page; results are written to a JSON file that the website reads.

---

## 3. Concerns & counterarguments

This section anticipates the questions a careful reviewer should raise, with the
mitigation for each.

| Concern | Assessment & mitigation |
|---|---|
| **It may not be exhaustive** — could the AI miss a change? | Correct — this is an *assistive summary*, not a substitute for the manual. Mitigations: (1) every claim links to the official PDF page; (2) a permanent human-override layer lets staff add, edit, or remove items; (3) a prominent "informational only — consult the official manual" disclaimer. The tool's value is *triage and access*. |
| **AI accuracy / hallucination** | The analysis quotes the manual directly and pins each quote to a page; reviewers can verify in one click. Quotes that cannot be matched to a page are shown without a (broken) link rather than with a guessed one. A human QA pass is built into the per-edition workflow. |
| **English/Spanish-only — an equity issue?** | Framed neutrally: language access is an accessibility and service-delivery question. The RMV already publishes the manual in multiple languages; the roadmap mirrors that. The tool is built so additional languages are incremental, without requiring rewrites (see Phase 2). Prioritization is a policy decision for RMV, not a technical constraint. |
| **English/Spanish-only — a political issue?** | The recommended posture is to follow the RMV's existing published-language set and official translations, so the tool inherits the agency's language policy rather than setting its own. Where no official translation exists, machine translation of legal content is **not** recommended without human review. |
| **Content freshness** | Updates are tied to manual releases (infrequent). The self-service admin (Phase 1) ensures a new edition can be added the same week it's published, without developer involvement. |
| **Legal exposure** | Mitigated by an explicit "informational, not legal advice; the official RMV manual governs" disclaimer and visible source citations. |
| **Privacy** | The public app collects no personal information and requires no login; a year typed into a box is not stored or transmitted with identity. |
| **Accessibility** | A dedicated Phase 1 work item brings the app to WCAG 2.1 AA (keyboard, screen-reader, contrast), appropriate for a public-sector service. |

---

## 4. Cost & effort model

**Labor assumptions (confirmed):**

- **Intern:** $22/hr → **~$176 per 8-hour day**. Availability this summer: ~8
  weeks ≈ **320 hours ≈ ~40 developer-days**.
- **In-house IT/web follow-on:** ~$40/hr → **~$320 per day**.
- **1 "dev-day" = 8 focused hours.** Ranges are low–high; "expected" is the
  planning midpoint.

**AI acceleration.** All effort estimates assume the developer co-develops with
agentic AI (Claude Code / Codex), consistent with how the prototype was built. A
**traditional, no-AI baseline (~2–3×)** is shown alongside to make the savings
explicit.

**The only required non-labor cost: annual LLM tokens.** When a new manual is
released, the comparison is re-run. Because each chunk of the new manual is
compared against the *full* text of each older edition, a single comparison pair
costs roughly **0.7M–1.0M input tokens**. Today's three pairs total ≈ **2.5M
input + ~0.4M output tokens** per full re-run.

| Model class (approx. pricing) | Cost per full annual re-run (today, 3 pairs) | At larger scale (~8 pairs) |
|---|---|---|
| Premium (Opus-class, ~$15/M in, ~$75/M out) | **~$65–75** | ~$150–200 |
| Mid (Sonnet-class, ~$3/M in, ~$15/M out) | **~$15** | ~$35–45 |
| Efficient (Haiku-class, ~$1/M in, ~$5/M out) | **~$5** | ~$10–15 |

The prototype currently defaults to the premium model. For production, a mid-tier
model is recommended for this extraction task, cutting cost ~5×. **Net: the
recurring operating cost is on the order of $15–75/year now, and likely under a
few hundred dollars/year even at full multi-edition scale** — a rounding error
compared to labor. A small one-time token budget during development (re-running the
analysis while tuning) is similarly minor (~$15–75 total).

**Hosting** is negligible: the public site is static and can run on existing state
web infrastructure or a static host; the admin backend (Phase 1) needs only a
small server/runtime.

---

## 5. Phase 1 — Finalize the existing product

These items make the tool **self-service, accurate, accessible, and bilingual**.

### 5.1 Self-service admin backend (upload a manual → run → publish)

Today, adding a manual requires a developer to run command-line scripts. This
builds a simple, authenticated web admin where RMV staff **upload a new manual
PDF, kick off the extract→analyze→export pipeline as a background job, watch
progress, review the results, and publish** — wrapping the existing, proven
scripts rather than rewriting them.

### 5.2 Image CMS (easy, visual image editing)

Extracted images frequently land in the wrong update or position. The override
layer already supports image edits in data; this adds a **friendly visual editor**
to drag images to the correct change, reorder, add, or remove them, with live
preview — no JSON editing.

### 5.3 Include all editions 2007–2026

Ingest and QA every available edition in the range so any driver lands on a
genuinely close comparison. *Estimate is per-edition.*

### 5.4 Accessibility improvements (WCAG 2.1 AA)

Keyboard navigation, ARIA roles/landmarks, focus management, color-contrast, and
screen-reader testing — appropriate for a public-sector service.

### 5.5 More accurate / streamlined content

Refine the analysis prompts and add a light relevance-curation step so results
emphasize the **most decision-relevant** changes (rules and laws) and continue to
suppress low-value noise (e.g., refreshed statistics), with a human review pass.

### 5.6 Spanish version

Ingest the official RMV Spanish manual(s), run the (reusable) pipeline, and add UI
internationalization with a language toggle and Spanish-language QA. **This item
also builds the one-time i18n framework** that makes every later language cheap.

### Phase 1 estimates

| Work item | Effort w/ AI (days) | Effort no-AI (days) |
|---|---|---|
| 5.1 Admin backend | 10–18 | 25–45 |
| 5.2 Image CMS | 8–15 | 20–38 |
| 5.3 All editions 2007–2026 | 6–12 | 12–24 |
| 5.4 Accessibility (WCAG 2.1 AA) | 5–9 | 10–18 |
| 5.5 Streamlined content | 5–10 | 10–20 |
| 5.6 Spanish version (incl. i18n) | 8–14 | 20–35 |
| **Phase 1 total** | **42–78** (≈59) | **97–180** (≈138) |

**Reading the table.** With AI, Phase 1 is roughly **42–78 developer-days** (≈59).
The traditional, no-AI baseline is **~97–180 days**, so the AI workflow removes on
the order of **55–60% of the effort**.

---

## 6. Phase 2 — Potential add-ons (optional)

These extend reach but are not required for a credible launch. They become
inexpensive *because* Phase 1 builds the admin, image CMS, and i18n framework.

### 6.1 Additional languages

Mandarin, Arabic, Korean, Haitian Creole, Portuguese, French, Russian, etc. Once
the Spanish work establishes the i18n framework, each language is mostly: ingest
the official translated manual, run the pipeline, translate UI strings, and QA.

- **Per language: ~3–6 days.** **Arabic adds right-to-left (RTL) layout: ~5–9 days.**
- **Gating caveat:** this assumes an **official translated manual exists** to ingest.
  Where one does not, machine-translating official legal content is **not
  recommended** without human review — that becomes a larger, policy-gated effort.

### 6.2 Digitize pre-2007 manuals (OCR)

Older editions may exist only as scanned images, requiring OCR plus heavier
extraction QA before they can enter the pipeline.

- **Per manual: ~3–6 days**, OCR-quality dependent.
- **Caveat:** source availability and scan quality drive the range; old scans need
  more human QA than born-digital PDFs.

### Phase 2 estimates

| Work item | Effort w/ AI (days) | Effort no-AI (days) |
|---|---|---|
| 6.1 Languages (per language) | 3–6 | 7–14 |
| 6.1 Arabic (RTL premium) | 5–9 | 11–20 |
| 6.1 All 7 listed languages (sources permitting) | 30–40 | 60–85 |
| 6.2 Pre-2007 manuals (per manual) | 3–6 | 6–12 |
| 6.2 Pre-2007 (≈2–3 older editions) | 8–18 | 16–36 |

---

## 7. Roll-up & recommendation

| Scope | Effort w/ AI (days) | Effort no-AI (days) |
|---|---|---|
| **Phase 1 (committed)** | 42–78 | 97–180 |
| Phase 2 — all 7 languages | +30–40 | +60–85 |
| Phase 2 — pre-2007 (≈2–3) | +8–18 | +16–36 |

**Recurring (annual):** ~$15–75/yr in LLM tokens (mid-tier model) — the only
required non-labor operating cost.

**What fits the internship.** The intern's ~40 available days covers a large
share of Phase 1 but not all of it. A practical split:

1. **Intern (this summer, ~40 days):** Admin backend (5.1), Image CMS (5.2), and
   the all-editions ingest (5.3) — the operational core that makes the tool
   self-sustaining.
2. **In-house IT/web follow-on:** finish accessibility (5.4), streamlined content
   (5.5), and the Spanish version + i18n framework (5.6).
3. **Later / as prioritized:** Phase 2 languages and pre-2007 digitization, each
   cheap once the framework exists.

**Bottom line.** Finishing the initial scope is roughly a **one-summer-plus
effort (~42–78 developer-days)**, with a recurring cost measured in **tens of
dollars per year**. The AI-co-development workflow roughly halves the labor versus
a traditional build, and the architecture is deliberately structured so that
breadth (more editions, more languages) is additive rather than a rebuild.

---

## 8. Appendix

### Assumptions

- 1 dev-day = 8 focused hours. Intern $22/hr ($176/day); in-house $40/hr ($320/day).
- AI-accelerated effort assumes co-development with Claude Code / Codex; no-AI
  baseline ≈ 2–3×.
- "All editions 2007–2026" assumes that PDFs are obtainable from the RMV.
- Additional-language and pre-2007 estimates assume an **official source document
  exists**; absence of an official source materially changes scope and policy risk.

### Pricing / model note

LLM token prices are approximate and tiered by model (premium / mid / efficient);
**verify current vendor rates before budgeting.** The prototype defaults to a
premium model; a mid-tier model is recommended for production extraction, reducing
recurring cost ~5×.

### Grounded reference figures (current build)

- Editions: 2007 (159 pp), 2017 (166 pp), 2023 (120 pp), 2026 (140 pp).
- Per comparison pair: ~0.7M–1.0M input tokens; current 3 pairs ≈ 2.5M in + ~0.4M out/run.
- Citation match rate: 296/300 quotes (~98%).
- Codebase: ~1,900 lines of pipeline Python; static frontend; SQLite + JSON output.

### Glossary

- **Edition / pair** — a manual year; a "pair" is one older→newer comparison.
- **Override layer** — stored human corrections that always win over AI output and
  survive re-runs.
- **Citation** — a quote's deep link to the exact page of the official RMV PDF.
- **i18n** — internationalization; the one-time framework enabling multiple languages.
- **WCAG 2.1 AA** — the accessibility standard targeted for the public service.
