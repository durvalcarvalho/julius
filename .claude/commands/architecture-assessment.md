# Architecture Assessment: $ARGUMENTS

Act as a Staff Engineer / Tech Lead / Software Architect evaluating a new product spec for the first time.

## Input

`$ARGUMENTS` is either:
- A file path to the spec (e.g., `docs/specs/my-feature.md`)
- A brief description of the feature to assess

If a file path is provided, read it first. If a description is provided, use it as the spec.

## Your Task

Analyze the feature spec against the **current ED Ambiente codebase** and produce a single Markdown document: the first technical architecture assessment for this initiative.

This is NOT implementation. This is the macro technical view that comes before detailed execution planning.

## Process

1. **Read the spec** — understand what is being asked
2. **Explore the codebase** — find all relevant models, views, serializers, services, components, pages, queries, types, tests, and configs that relate to the feature
3. **Assess fit** — determine how this feature integrates with existing architecture
4. **Identify reuse** — what already exists vs what needs to be created
5. **Surface risks** — unknowns, dependencies, sequencing concerns
6. **Recommend direction** — the most architecturally sound approach

Use multiple agents in parallel to explore different parts of the codebase (backend models, frontend features, services, tests) for efficiency.

## Rules

- Output ONLY the final Markdown document, UNLESS the Validation Gate below fails — in that case output the gate's blocking questions instead and stop
- Do NOT ask follow-up questions during exploration — make the best assessment and mark uncertainty. The one exception is the Validation Gate's own decision to stop (see below)
- Do NOT generate implementation code (tiny pseudocode snippets are OK to clarify architecture)
- Ground everything in the actual codebase — reference concrete files, modules, components, services, APIs, models, schemas, tests, configs
- Clearly distinguish between: **Confirmed findings**, **Inferences**, **Assumptions**, **Open questions**, **Recommendations**
- Be specific — avoid generic advice
- If the spec conflicts with current architecture, call it out explicitly
- If analogous features exist in the codebase, compare against them
- If multiple competing patterns exist, identify that and recommend one direction

## ED Ambiente Context

Key constraints to evaluate against:
- **Multi-tenancy**: every model needs `organization` FK, every query filters by `request.user.organization`
- **Services layer**: business logic in `app/services/`, views and serializers are thin
- **ApiError pattern**: backend throws `ApiError`, frontend propagates field-level errors via `setError()`
- **Status workflows**: defined state machines (see Project, Environment, PurchaseOrder, DigitalBox, VacationRequest, AssemblyTask)
- **Immutable ledger**: StockMovement is append-only, corrections via cancellation
- **Auto-generated codes**: PROJ-YYYY-NNNN, ENV-{PROJECT}-NNNN, CX-YYYY-NNNNN, PC-YYYY-NNNN
- **Audit trails**: created_by, updated_by, timestamps on all models
- **Validation layers**: DB CheckConstraint -> model.clean() -> serializer -> frontend Zod
- **Portuguese UI**: all user-facing text in Portuguese, all code in English
- **Quality gates**: 0 mypy/ruff errors, max 800 lines/file, max 15 cognitive complexity, 80%+ test coverage

## Validation Gate (MANDATORY before writing the document)

You must challenge the spec and your own findings before shipping the assessment. Answer these
before writing a single section:

**Q1 — Is the spec internally consistent?** Does the request contradict itself (different names
for the same concept, an action mentioned once but never described end to end)? If yes: this is a
blocking question, not something to paper over with an assumption.

**Q2 — Is every reference current?** Every file, model, endpoint, component, or pattern you're
about to cite in the assessment — have you actually verified it exists and looks the way you
think, right now, not from memory or a stale doc? Check them. A reference you haven't verified
doesn't belong in "Confirmed findings" — move it to "Assumptions" or verify it first.

**Q3 — Is the intent clear enough to recommend a direction?** If two reasonable engineers reading
the same request would recommend genuinely different architectures (not just different naming),
that's a blocking ambiguity, not a "note in Open Questions and move on."

**Q4 — Are the dependencies this assessment assumes actually present?** If the feature assumes
another feature/model/service exists and it doesn't, that's a blocker, not a footnote.

**Q5 — Does this make business sense** for an ERP for custom furniture manufacturing? Would it
duplicate an existing flow, break one, or solve a problem the system doesn't have?

**Decision gate:**
- All five resolved (by reading the code, not by guessing) → write the assessment
- Resolvable by reading more code → do that, don't stop
- A genuine blocker survives (contradiction, unverifiable dependency, real ambiguity a
  recommendation can't survive) → **stop.** Write a short `## Blocking Questions` section instead
  of the full assessment: number each blocker, state why it blocks a confident recommendation, and
  wait for the user. Don't ship an assessment whose "Overall recommendation" is actually a coin
  flip between two architectures dressed up as confidence.

This is the same discipline `implement-sprint.md`'s Phase 0.5 applies at implementation time —
applied one phase earlier, so `generate-tickets.md` never has to build tickets on an unresolved
contradiction.

## Optional: Adversarial Review Pass (high-risk designs only)

The Validation Gate above is a self-checklist — the same agent checking its own work. For a
**high-risk** design (new schema strategy, a permission-model change, a migration with no clean
rollback, or anything landing more than a couple items in "Decisions That Need Explicit
Alignment"), a self-checklist can't catch a confidently-wrong recommendation the way an
independent reviewer can. In that case, after drafting the assessment but before finalizing it:

1. Dispatch one read-only agent (`system-architect` or `backend-architect`/`data-modeler` per the
   area at risk) with the drafted assessment and the same codebase access, prompted to find the
   strongest reason the recommended approach is wrong — not to rubber-stamp it.
2. Dispatch a second read-only agent (`self-review` or `tech-lead`) prompted adversarially:
   assume the first draft has a flaw and find it, rather than confirm it's fine.
3. Incorporate genuine findings into the assessment (or its "Architectural Risks" / "Decisions
   That Need Explicit Alignment" sections) before writing the final document; don't silently
   overwrite disagreement.

This is a debate between independent agents, not another checklist — use it when the cost of being
confidently wrong (a bad schema, an irreversible migration) is higher than the cost of one extra
round. Skip it for ordinary features; running it by default would just double the cost of every
assessment for no benefit on low-risk work.

## Output Structure

Write the document to `docs/assessments/{feature-slug}-assessment.md` using this structure:

```
# {Feature Name} — Architecture Assessment

## Executive Summary
- What this demand is
- What systems are impacted
- The likely implementation shape
- The biggest risks or complexities
- Overall recommendation for technical direction

## Feature Summary
The feature in technical terms. Focus on system implications, not product language.

## Current State Assessment
Current relevant architecture as found in the codebase:
- Relevant domains, services, modules, bounded contexts
- Existing flows related to this feature
- Current technical patterns in similar areas
- Reusable infrastructure already present
- Notable architectural constraints
- Technical debt that may affect the work

## Relevant Codebase Areas
For each area:
- Path / module / service / component
- What it currently does
- Why it is relevant
- Whether it is likely to be reused, extended, or avoided

## How This Feature Fits Into the Existing Architecture
- Where core logic should live
- Where orchestration should happen
- Where persistence changes belong
- Where API/interface changes are needed
- How frontend/backend boundaries should be respected
- Alignment with existing conventions

If multiple viable approaches exist, compare them and recommend one.

## Proposed Technical Approach
High-level implementation approach:
- Main architectural decisions
- Major moving parts
- Responsibility split across layers
- Extend existing patterns vs introduce new abstraction
- Data flow through the system
- State, events, validation, permissions handling
- Integration points

## Impact Analysis
Break down by area (only include relevant ones):
- Frontend / UI
- Backend / services
- APIs
- Database / persistence
- Auth / permissions
- Test infrastructure
- Migrations / backfills

For each: expected changes, likely complexity, main concerns.

## Reuse vs New Build
### Existing pieces that can be reused
### Existing pieces that need refactoring or extension
### New components or abstractions needed

## Data Model and Contract Considerations
- Data models
- API contracts
- Internal interfaces
- Backward compatibility
- Schema evolution / migration concerns

## Architectural Risks and Complexity
For each risk: why it matters and suggested mitigation.
- Coupling
- State consistency
- Migration complexity
- Performance risk
- Security / multi-tenancy concerns
- Testability concerns

## Unknowns / Gaps Discovered
Major gaps that prevent full confidence:
- Unclear business rules from the spec
- Missing abstractions
- Inconsistent patterns
- Areas under-documented

## Assumptions
Assumptions made during analysis.

## Recommended Sequencing
Macro-level execution order with rationale:
1. Architecture / domain alignment
2. Foundational refactors or prerequisites
3. Core backend support
4. Contract and interface updates
5. UI integration
6. Hardening / cleanup

## Suggested Workstreams
For each workstream:
- Objective
- Likely scope
- Key dependencies
- Risk level

## Decisions That Need Explicit Alignment
Decisions important enough for team discussion:
- New domain abstractions
- Schema strategy
- Permission model
- Migration strategy

## Recommended Next Step
What should happen after this document (deeper design, spike, schema review, API contract definition, PoC, etc.)

## Appendix: Evidence From the Codebase
Concrete evidence:
- Key files and paths
- Modules and services
- Patterns observed
- Analogous implementations
- Notable tests
- Configs
```
