# Generate Implementation Tickets: $ARGUMENTS

Break down an architecture assessment into agent-ready implementation tickets — precise enough that an autonomous agent can implement each one without under- or over-delivering.

## Input

`$ARGUMENTS` is a file path to an architecture assessment document (e.g., `docs/assessments/workflow-management-system-assessment.md`).

Read the assessment first. If the file does not exist or is not an architecture assessment, stop and tell the user.

## Your Task

Transform the architecture assessment into a folder of numbered, self-contained implementation tickets — split into `backend/` and `frontend/` tracks — with a root `index.md` that maps the full plan.

This is NOT implementation. This is the detailed breakdown that enables implementation.

## Process

1. **Read the assessment** — internalize the proposed approach, data models, API contracts, sequencing, risks, and decisions
2. **Read the original spec** — if the assessment references a spec document, read it too for business context
3. **Explore the codebase** — verify the assessment's claims about existing patterns, files, and conventions. Use multiple agents in parallel for efficiency. You need concrete knowledge of:
   - Existing model patterns (field types, constraints, mixins, Meta classes)
   - Existing service patterns (method signatures, error handling, transaction usage)
   - Existing ViewSet patterns (mixins, serializer mapping, actions, permissions, filters)
   - Existing frontend feature structure (pages, components, hooks, queries, types, services)
   - Existing test patterns (fixtures, factories, assertion styles, mocking)
   - Route registration patterns (backend urls.py, frontend routes.tsx)
   - Import conventions and module boundaries
4. **Decompose into tickets** — break the work into small, ordered, independently-implementable units
5. **Write each ticket** with surgical precision — an agent reading only that ticket plus the codebase should be able to implement it correctly
6. **Write the index** — map the full plan, dependencies, and critical path

## Decomposition Rules

### Sizing — Session-Sized Tickets (CRITICAL)

Tickets are implemented by AI agents in a single session with limited context window. A ticket that is too large will cause the agent to lose context, skip steps, or produce incomplete work. **Err on the side of too small, never too large.**

- Each ticket should be completable in **a single focused agent session** — roughly **1-3 hours of equivalent human work**
- A good heuristic: if the ticket touches more than **3-4 files to create** or **5-6 files to modify**, it is probably too large — split it
- If a ticket requires both a model AND its ViewSet AND its serializers AND its tests, that is too much — split into (1) model + migration + model tests, (2) service + service tests, (3) ViewSet + serializers + URL + API tests
- If a ticket has more than **8-10 test cases**, consider splitting the implementation from the tests, or splitting by sub-feature
- **Never combine backend and frontend in a single ticket** — they are always separate tracks
- If a ticket feels trivial (< 30 min, e.g., adding one field to an existing model), merge it with an adjacent ticket
- A complex interactive component (e.g., Kanban board) should be split into: (1) static rendering, (2) drag-and-drop interaction, (3) API integration + optimistic updates — not one mega-ticket

### Ordering

- Tickets are numbered sequentially within each track: `001-`, `002-`, `003-`, etc.
- Order by dependency: ticket N should only depend on tickets < N within its track
- Cross-track dependencies (frontend needs backend API) are declared explicitly
- The first backend ticket is always the data model + migrations
- The first frontend ticket is always types + API service stubs

### Scope Boundaries

Every ticket MUST define what is IN scope and what is OUT of scope. This is critical — agents will do exactly what the ticket says. If you don't exclude something, the agent might add it. Common exclusions:

- "Do NOT add frontend components — this ticket is backend only"
- "Do NOT implement the trigger engine — that is ticket 007"
- "Do NOT add indexes or constraints beyond what is specified here"
- "Do NOT create admin UI — configuration is done via Django admin for now"
- "Do NOT handle file uploads — the Document model is a separate ticket"
- "Do NOT add WebSocket/real-time — use polling for now"

### Granularity Guidelines

**Backend tickets typically cover ONE of:**
- Data models + migrations for a small bounded context (e.g., Sector + Stage models — 2-3 closely related models max)
- A single service module with its unit tests (e.g., CardMoveService)
- A single ViewSet + its serializers + URL registration + API tests (e.g., SectorViewSet)
- A complex algorithm or engine split into core logic + tests (e.g., TriggerEngine core, then TriggerEngine chain tests separately)
- Admin configuration or seed data for a module

**Frontend tickets typically cover ONE of:**
- TypeScript types + API service functions for a domain (types + services only, no components)
- A single page component with its route registration (e.g., BoardPage — the page shell, not the interactive board)
- A single complex interactive component (e.g., board column with drag-and-drop — not the whole board)
- A shared component or hook (e.g., notification bell, useCardDrag hook)
- Integration of a feature into existing layout (e.g., sidebar menu items, route wiring)
- Form component with its Zod schema and API submission logic

**Splitting large features — example for a Kanban board:**
1. Types + API services (fetching cards, sectors, stages)
2. Board page shell + static column rendering (no DnD)
3. Card component with detail modal
4. Drag-and-drop between columns with optimistic updates
5. Filters and sorting within columns
6. Client grouping within columns

That is 6 tickets, not 1. Each is completable in one session.

## Ticket Format

Each ticket file uses this exact structure:

```markdown
# {NNN}: {Ticket Title}

> {One-line summary of what this ticket delivers}

## Context

Why this ticket exists, what it builds on, and where it fits in the larger epic.
Reference the assessment section that drives this ticket.
If this ticket depends on other tickets, state which ones and what they provide.

## Scope

### In Scope
- Concrete deliverable 1
- Concrete deliverable 2
- ...

### Out of Scope
- Thing that might seem related but is NOT this ticket (→ ticket NNN)
- Another boundary
- ...

## Requirements

### Functional
Bullet list of exact behaviors. Be specific:
- "Sector model has fields: organization (FK), name (CharField max 100), description (TextField blank), color (CharField max 7), icon (CharField max 50 blank), display_order (PositiveIntegerField), is_active (BooleanField default True)"
- NOT "Sector model has the usual fields"

### Validation
Explicit validation rules:
- "name is required, max 100 chars, unique per organization (case-insensitive)"
- "display_order must be >= 0"
- "color must match regex ^#[0-9A-Fa-f]{6}$"

### Permissions
Who can do what:
- "Only users with is_admin=True or role='owner' can create/update/delete sectors"
- "All authenticated users in the organization can list/retrieve sectors"

### Error Handling
Expected error cases and responses:
- "Duplicate name → 400 with field error on 'name': 'Ja existe um setor com este nome'"
- "Sector not found → 404"
- "Sector has active cards → 400 with message 'Nao e possivel excluir setor com cards ativos'"

## Technical Specification

### Files to Create
```
path/to/new/file.py — description of what this file contains
path/to/another/file.py — description
```

### Files to Modify
```
path/to/existing/file.py — what changes and why
```

### Data Model (if applicable)
Full model definition with field types, constraints, indexes, Meta class.
Use actual Django/Python syntax — not pseudocode.

### API Endpoints (if applicable)
For each endpoint:
- Method + URL pattern
- Request body (with types)
- Response body (with types and status codes)
- Query parameters (if any)

### Key Implementation Details
Specific patterns to follow, referencing existing codebase examples:
- "Follow the same mixin pattern as ProjectViewSet in backend/projects/views/project_views.py"
- "Use OrganizationFilterMixin exactly as MaterialViewSet does in backend/inventory/views/material_views.py"
- "Register URLs in the same pattern as backend/projects/urls.py"

## Tests

### Required Test Cases
Numbered list of specific test cases. Each must be concrete:
- "test_create_sector_success — POST with valid data returns 201 and correct fields"
- "test_create_sector_duplicate_name — POST with existing name returns 400 with field error"
- "test_create_sector_unauthorized — non-admin user gets 403"
- "test_list_sectors_filters_by_organization — user only sees own org's sectors"
- "test_reorder_sectors — PATCH reorder updates display_order for all affected sectors"

### Test Patterns
- "Use the same test base class as backend/projects/tests/test_views.py"
- "Use APIClient with force_authenticate"
- "Create fixtures via model factories, not raw .create()"

## Acceptance Criteria

Checklist that must ALL be true for the ticket to be considered done:
- [ ] All files listed in "Files to Create" exist and contain the specified code
- [ ] All modifications listed in "Files to Modify" are applied
- [ ] All test cases pass: `cd backend && uv run python manage.py test {app}.tests.{module}`
- [ ] Static checks pass: `cd backend && make verify`
- [ ] No regressions in existing tests: `cd backend && make test`
- [ ] (Frontend) Type check passes: `cd frontend && npx tsc --noEmit`
- [ ] (Frontend) Lint passes: `cd frontend && npx eslint src/`
- [ ] (Frontend) Tests pass: `cd frontend && npm test -- --run`

## Notes for the Implementing Agent

Specific guidance to prevent common mistakes:
- "Remember: all verbose_name and help_text in Portuguese, all code in English"
- "The organization FK must be set in perform_create via request.user.organization — never trust client input for this"
- "Use transaction.atomic() for the reorder operation"
- "Do not add __str__ methods that expose data from other tenants"
```

## Index File Format

The `index.md` file uses this structure:

```markdown
# {Epic Name} — Implementation Tickets

> Generated from: `{path to assessment}`
> Generated on: {date}

## Overview

{2-3 paragraph summary of what this epic delivers, the technical approach chosen, and key architectural decisions}

## Decisions Applied

Decisions from the assessment that were applied when generating tickets:
- Decision 1: {what was decided and why}
- Decision 2: ...

## Backend Track

| # | Ticket | Depends On | Estimated Effort | Description |
|---|--------|------------|-----------------|-------------|
| 001 | [Title](backend/001-slug.md) | — | S/M/L | One-line summary |
| 002 | [Title](backend/002-slug.md) | 001 | S/M/L | One-line summary |
| ... | ... | ... | ... | ... |

## Frontend Track

| # | Ticket | Depends On | Estimated Effort | Description |
|---|--------|------------|-----------------|-------------|
| 001 | [Title](frontend/001-slug.md) | Backend 001 | S/M/L | One-line summary |
| 002 | [Title](frontend/002-slug.md) | 001 | S/M/L | One-line summary |
| ... | ... | ... | ... | ... |

## Cross-Track Dependencies

{Diagram or list showing where frontend tickets depend on backend tickets}

```
Backend:  001 → 002 → 003 → 004 → 005 → ...
                  ↓           ↓
Frontend:       001 → 002 → 003 → 004 → ...
```

## Critical Path

The minimum sequence that must complete for the feature to be usable:
1. Backend 001 (models) → Backend 002 (services) → Backend 003 (API)
2. Frontend 001 (types) → Frontend 002 (page) → ...

## Phase Mapping

How tickets map to the assessment's recommended phases:
- **Phase 1**: Backend 001-005, Frontend 001-004
- **Phase 2**: Backend 006-010, Frontend 005-008
- ...

## Risks & Mitigations

Key risks from the assessment and how tickets address them.

## Open Questions

Questions from the assessment that remain unresolved. For each, state what was assumed when generating tickets and what would change if the assumption is wrong.
```

## Output Structure

Write all files under `docs/tickets/{epic-slug}/`:

```
docs/tickets/{epic-slug}/
  index.md
  backend/
    001-{ticket-slug}.md
    002-{ticket-slug}.md
    ...
  frontend/
    001-{ticket-slug}.md
    002-{ticket-slug}.md
    ...
```

## ED Ambiente Constraints

Apply these to EVERY ticket:

- **Multi-tenancy**: every model has `organization` FK, every queryset filters by `request.user.organization`
- **Services layer**: business logic in `{app}/services/`, ViewSets and serializers are thin
- **ApiError pattern**: backend raises `ApiError`, frontend shows field-level errors via `setError()`
- **Validation layers**: DB CheckConstraint → model.clean() → serializer → frontend Zod
- **Portuguese UI**: all user-facing text (verbose_name, help_text, error messages, labels) in Portuguese
- **English code**: all variable names, functions, classes, comments in English
- **Audit fields**: created_by, updated_by, created_at, updated_at on business models
- **Soft deletes**: deleted_at timestamp pattern where specified
- **Auto-generated codes**: follow existing PROJ-YYYY-NNNN pattern
- **Quality gates**: 0 mypy/ruff errors, max 800 lines/file, max 15 cognitive complexity
- **Test coverage**: 80%+ on new code
- **Pre-commit hooks**: agent must run `make verify` and `make test` — never `--no-verify`

## Rules

- Do NOT ask follow-up questions — make the best decomposition and note assumptions
- Do NOT generate implementation code inside tickets — describe what must be built with enough precision that an agent can write the code
- DO include actual Django field definitions, API request/response shapes, and TypeScript type definitions — these are specifications, not code
- Ground everything in the actual codebase — reference concrete files the agent should use as patterns
- Each ticket must be self-contained: an agent with access to the codebase and that single ticket file should be able to implement it
- If the assessment has unresolved decisions, pick the recommended option and note the assumption
- If the assessment spans multiple phases, generate tickets for all phases but clearly label which phase each belongs to
- Use the assessment's sequencing as the primary ordering guide
- Prefer more tickets with smaller scope over fewer tickets with larger scope
