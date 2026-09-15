# Implement Vertical Sprint: $ARGUMENTS

You are a senior engineer assigned a vertical sprint. Your first obligation is to **understand before acting** — the spec may be stale, incomplete, or just wrong. Read it critically, question it, then execute with the right tools.

A vertical sprint is a folder like `<specs-dir>/sprint-NN-*/` containing `backend.md` + `frontend.md` + `dependencies.md` — a slice that is only "done" when it's usable end to end: "**nunca** só backend ou só frontend." This command always implements both stacks for the sprint; it does not have a backend-only or frontend-only mode.

---

## Input

`$ARGUMENTS` is a path to a sprint folder. Read `backend.md`, `frontend.md`, and `dependencies.md` immediately, in full. If the folder or any of the three files doesn't exist, stop and tell the user.

**Pre-flight git check:** Run `git status` before touching anything. If the working tree is dirty (uncommitted changes, staged files, untracked files that belong to the project), stop and tell the user: "Working tree is not clean — commit or stash your changes before I proceed." A dirty start means a dirty end, and the session must end with a clean tree.

**Pre-flight status check:** Check the header of both `backend.md` and `frontend.md` independently — a prior partial run can leave one done and the other not.
- Both `<!-- status:done ... -->` → stop, the sprint is already implemented.
- One done, one not → only implement the missing stack's milestones (Phase 3 still runs both stacks' Socratic validation/planning, since the frontend depends on the backend's actual shape either way).
- Either `<!-- status:blocked ... -->` → check whether the blocker has been resolved before proceeding.

**Create the sprint branch (MANDATORY, before any milestone work):** never implement a sprint directly on `main`. Branch name is the sprint folder's basename — e.g. `sprint-07-terceirizados` for `<specs-dir>/sprint-07-terceirizados/` (matches this repo's existing convention, see `git branch -a`/`git log --all --simplify-by-decoration`).

- If resuming a partial run (one stack already `status:done`), the branch should already exist — `git checkout <branch>` rather than creating it again.
- Otherwise: `git checkout -b <branch>` off an up-to-date `main`. If `main`/`origin/main` have diverged, sync first (fast-forward `main`, do not force anything) before branching.
- All Phase 3/4 milestone commits land on this branch, never on `main`. Opening/pushing a PR from it is a separate, later step (a different command / an explicit user request) — this command only commits locally, per the "NEVER push" constraint.

---

## Phase 0: Read the Sprint

Read all three files fully, then check `dependencies.md`'s "Depende de sprints anteriores" — for each one listed, confirm it's actually merged (its own `backend.md`/`frontend.md` status headers say `done`), not just assumed. A dependency that's only partially done is a blocker, not a detail to route around.

**Activate skills now** by loading the relevant skill files from `.claude/skills/` before proceeding — don't guess at conventions, the skills tell you exactly what the project expects:
- Always: `application-context`
- Backend: `django-core`, `api-endpoint`, `smart-testing`
- Frontend: `templates-components`, `form-builder`, `accessibility`, `ui-ux-principles`, `smart-testing`
- If the sprint's backend milestone involves new/changed schema relationships (not just a straightforward new model): pull in `data-modeler` for that milestone specifically, before `backend-engineer` implements it.

---

## Phase 0.5: Socratic Validation (MANDATORY — do this before writing a single line of code)

You must challenge the spec before trusting it. Answer these five questions by reading `backend.md` + `frontend.md` + `dependencies.md` AND the codebase:

**Q1 — Is the spec internally consistent?**
Does `backend.md` contradict `frontend.md` (e.g. different field names for the same concept, or an action the frontend expects that the backend endpoints section doesn't list)? If yes: stop, quote the contradiction, ask the user to resolve it.

**Q2 — Is the spec current?**
Every file path, model name, endpoint, component, or pattern the sprint references — does it actually exist in the codebase today? Check them. If a referenced file is gone or renamed, or a described pattern no longer matches reality: note it as a stale delta, adjust silently if the fix is obvious, stop and ask if it's load-bearing.

**Q3 — Is the "why" clear enough to make judgment calls?**
You will hit ambiguity during implementation. Can you infer the intent well enough to resolve it yourself? If the spec is so vague that two reasonable engineers would implement completely different things: stop, ask ONE focused question that unlocks the path.

**Q4 — Is the scope implementable without missing dependencies?**
Are all referenced models, endpoints, services, and types from earlier sprints already in the codebase? If a dependency isn't there: stop, write `<!-- status:blocked ... -->` in the affected file(s), tell the user what's missing.

**Q5 — Does this spec make business sense?**
Given what you know about the application (ERP for custom furniture manufacturing), does this sprint describe something coherent? If it would break an existing flow, duplicate something that already exists, or solve a problem the system doesn't have: stop and flag it.

**Decision gate:**
- All five: OK → proceed to Phase 1
- Any: unclear but fixable by reading code → fix it yourself, note as adjustment, proceed
- Any: genuinely ambiguous, contradictory, or blocked → **STOP. Ask ONE focused question.** Do not ask questions you can answer by reading the codebase.

**What counts as a genuine question (ask):**
- "The spec says create a new `ShippingAddress` model, but `Customer` already has `address` fields. Should this replace those or exist alongside them?"
- "`frontend.md` expects a `confirm` action to take a partner-supplied due date, but `backend.md`'s model has no such field. Add it, or is the frontend spec stale?"

**What does NOT count (figure it out yourself):**
- "Should I use UUIDField?" (See `.claude/rules/backend-models.md` — integer PK by default, UUID needs a justified need.)
- "What migration number?" (Django auto-generates it.)
- "Should verbose_name be in Portuguese?" (CLAUDE.md says yes.)

---

## Phase 1: Deep Codebase Validation

With the spec validated, go deeper. Use parallel exploration for speed — one pass over backend patterns, one over frontend patterns, run together.

1. **Verify every referenced file** — read it, don't trust the description. If the pattern described has evolved, follow the current pattern.
2. **Check dependency sprints** — verify the model/endpoint a dependency claims to provide actually exists in the code (per Phase 0), not just that its status header says done.
3. **Find the closest existing pattern for each stack** — what's the most similar thing already in the codebase (backend: a sibling model+service+viewset; frontend: a sibling section+hooks+component)? Read it fully. Your implementation should look like a sibling, not a stranger.
4. **Build your delta list** (covering both `backend.md` and `frontend.md`):
   - **Stale** — spec says X, codebase has Y
   - **Missing** — spec should have mentioned X but didn't
   - **Wrong** — spec got something backwards
   - **Correct** — checks out

---

## Phase 2: Plan

Write a concise plan based on what YOU found — not a copy of the spec.

```
## Implementation Plan

### Goal
One sentence: what this vertical slice delivers, end to end.

### Adjustments from Spec
- [List deviations across backend.md/frontend.md and why — or "Spec matches codebase — implementing as specified."]

### Backend Milestones
| # | Milestone | Files |
|---|-----------|-------|
| 1 | Data layer (model + migration) | ... |
| 2 | Business logic (services, incidents) | ... |
| 3 | API surface (serializers, ViewSets, URLs) | ... |
| 4 | RBAC (if a new perm) | ... |

### Frontend Milestones
| # | Milestone | Files |
|---|-----------|-------|
| 1 | Data layer (types, service) | ... |
| 2 | Query hooks | ... |
| 3 | UI (components, wiring) | ... |

### Test Strategy
What to test and why, per milestone — your assessment, not a copy of the spec's list.

### Risks
Anything that could go wrong or needs extra care.
```

**Do NOT ask the user to approve the plan.** If you have a genuine blocking question from Phase 0.5, ask it now and wait. Otherwise, proceed immediately.

---

## Phase 3: Implement — one milestone at a time, commit between each, backend before frontend

**Implementation happens in milestone-sized slices, not one giant subagent call per stack.** Each slice is small enough to review and commit on its own, and its commit message is where the *why* behind that slice's decisions gets documented — that record is the point, not a formality. Never dispatch "implement the whole backend" (or "the whole frontend") in a single subagent call; dispatch one milestone, let it return, commit, then continue the same agent for the next milestone.

Backend milestones always run before frontend milestones — the frontend agent needs the backend's *actual* shape (real endpoint paths, serializer field names, perm codes), not the spec's guess at them.

### Milestones per stack

**Backend** (skip any that don't apply to this sprint):
1. **Data layer** — model(s) + migration + admin registration (if any)
2. **Business logic** — services, incident materializers, any domain rules
3. **API surface** — serializers + ViewSets + URLs
4. **RBAC** (only if the sprint adds a new perm) — registry entry + `SYSTEM_TEMPLATES` grant + add-only backfill migration
5. **Any remaining hardening** the earlier slices exposed (edge cases, follow-up fixes from a failing test)

Write each milestone's tests **in the same milestone**, not deferred to a final "tests" pass — model tests land with the model, service/incident tests land with the service, endpoint/perm tests land with the API surface.

**Frontend** (skip any that don't apply):
1. **Data layer** — types + API service (+ their tests, if the service has meaningful branching)
2. **Query hooks** (TanStack Query keys + hooks)
3. **UI** — components/pages + wiring into the page + component tests

### How to run a milestone

1. Spawn (or continue, via `SendMessage` to the same agent) the subagent with **only that milestone's scope** — be explicit that it should implement just this slice, run whatever scoped check applies (`manage.py check`, a targeted test module, `tsc`/lint on the touched files), report back, and **not commit anything** (see Constraints — subagents never commit; a prior session had a subagent run its own clean-tree preflight and sweep up unrelated dirty files into its own commit).
2. When it returns, read the actual diff yourself (`git status` / `git diff`) — don't take the subagent's file list on faith.
3. Stage precisely the files that milestone touched (explicit paths, no `git add -A`/`.`).
4. Commit (see Phase 4) with a message that captures what this slice does *and why* — any adjustment, assumption, or non-obvious decision made while building it.
5. Move to the next milestone, continuing the same subagent conversation so it keeps full context instead of re-deriving it.

Run the full `make verify && make test` gate (see "Verification" below) once per stack, near the end of that stack's milestones — not after every single micro-commit, that's wasteful. A quick scoped check per milestone is enough to catch breakage early; the full suite is the final gate before moving from backend to frontend, and again before Phase 5.

### Dispatch

- **Backend milestones** → `backend-engineer` subagent, one milestone at a time per the breakdown above. Pass: goal, adjustments, the milestone's file list, test strategy for that slice, and any specific patterns to follow from the codebase exploration. If milestone 1 needs schema/relationship decisions beyond a straightforward model, run `data-modeler` first for that milestone only, then hand its decision to `backend-engineer`.
- **Frontend milestones** → `frontend-engineer` subagent, one milestone at a time, started only once the backend's API surface milestone is committed. Pass: goal, adjustments, the milestone's file list, test strategy for that slice, component patterns found in exploration, and the backend's *actual* endpoint paths/serializer shapes/perm codes (not the spec's).

---

### Code Quality Rules (apply regardless of subagent)

- **Match codebase conventions exactly.** Read the closest existing pattern and make yours look like a sibling.
- **All user-facing text in Portuguese** — verbose_name, help_text, error messages, labels, placeholders. All code in English.
- **Multi-tenancy is non-negotiable.** Every model has `organization` FK. Every queryset filters by `request.user.organization`. Every `perform_create` sets organization from request. No exceptions.
- **Services layer for business logic.** Views and serializers stay thin.
- **No gold-plating.** Implement what the sprint asks. Nothing more.
- **No half-measures.** If the sprint says comprehensive tests, write comprehensive tests.
- **Check `duplicate`/`coupling`/`brittle`/`orphan`** (see `CLAUDE.md`'s Critical Rules) before calling a milestone done — same threshold discipline as everywhere else, applies to subagent output too.

### Testing
- Run tests incrementally — don't wait until the end
- Backend: `cd backend && uv run python manage.py test <app>.tests.<module> --noinput --keepdb -v 2`
- Frontend: `cd frontend && npm test -- --run src/features/<feature>/<test-file>`
- Fix the **implementation** when tests fail, not the tests — unless the test itself is wrong
- Add tests the spec missed, especially multi-tenancy isolation tests

### Non-interactive execution (MANDATORY)

Agents run without a TTY. Any command that blocks on stdin will hang forever.

| Tool | Do | Don't |
|------|----|-------|
| Django tests | `make test` or `manage.py test … --noinput --keepdb` | `manage.py test` without `--noinput` |
| Django migrate | `manage.py migrate --noinput` | Commands that prompt to confirm |
| Stale test DB | `docker compose exec -T db psql -U postgres -c "DROP DATABASE IF EXISTS test_ed_ambiente;"` | Waiting for Django's interactive recreate prompt |
| Docker | `docker compose exec -T …` | `docker compose exec` without `-T` |
| npm/Vitest | `npm test -- --run <file>` | `npm test` in watch mode without `--run` |

### Verification
- Backend, once all backend milestones are committed: `cd backend && make verify && make test`
- Frontend, once all frontend milestones are committed: `cd frontend && make verify`

If anything fails, fix it. Repeat until green. Never skip this step.

---

## Phase 4: Commit Per Milestone

**One commit per milestone from Phase 3, not one commit for the whole sprint.** The point is that the commit log becomes a readable history of how the feature was built and why each decision was made — a single end-of-task mega-commit throws that away. Only the orchestrator commits — never a subagent (see Constraints).

### During implementation: one commit per milestone

After each milestone lands (Phase 3):

1. **Stage precisely** the files that milestone touched — explicit paths, never `git add -A`/`git add .`.
2. **Commit** with a message shaped like:
   ```
   <type>(<scope>): <what this slice delivers>

   <1-4 lines: any non-obvious decision, assumption, or deviation made in
   this slice specifically, and why. Skip this body if the slice was
   completely mechanical and the subject line already says it all.>
   ```
   Examples of what belongs in that body: "grace period defaulted to 3 days, spec doesn't specify one"; "used `parties.Counterparty` — the spec's `Party` model doesn't exist"; "kept X and Y in one dedup key because they're mutually exclusive, like deadline_approaching/overdue." This is where the Phase 0.5/Phase 1 judgment calls get preserved for whoever reads `git log` later — don't let them evaporate into a single generic final message.
3. **Handle pre-commit hook failures** the same way every time: read the error, fix the underlying issue (never `--no-verify`), re-stage the fixed files, commit again. A hook auto-fixing files (prettier/eslint `--fix`) after a failed commit means: re-stage those exact files and commit again — the commit did not happen the first time, so this is a normal retry, not an amend.
4. Move on to the next milestone.

If a later milestone reveals that an earlier one needs a fix (a test written in milestone 3 catches a bug from milestone 1), commit that fix on its own with a message explaining what was wrong and why — don't silently fold it backwards into the earlier commit.

### At the very end: sprint status + index as their own final commit

Once every milestone for both stacks is committed and green, close out the sprint bookkeeping as one last, separate commit — it's documentation-only and shouldn't be mixed into a code commit.

**Step 1 — update the sprint files.** Insert a status block immediately after the title, before any `>` quote, in both `backend.md` and `frontend.md`:

```markdown
# Sprint NN — Backend: My Sprint Title

<!-- status:done implemented:2026-06-01 -->
<!-- adjustments: <one-line summary of deviations, or "none"> -->

> Summary of what this sprint does...
```

Schema:
- `status:done` | `status:blocked` | `status:pending`
- `implemented:YYYY-MM-DD`
- `adjustments:` — deviations from spec, or `none` (this is the *summary* of the same decisions already documented in full across the milestone commits — not the first place they appear)

**Step 2 — update the index.** Read the sprint folder's sibling `README.md` (one level up, e.g. `<specs-dir>/README.md`)'s sprint table. Find the row for this sprint and prepend `DONE - ` to the "Entrega utilizável" column.

**Step 3 — stage and commit** just the spec/index files:

```
docs(<scope>): mark sprint NN done

Implements: <sprint folder path>
```

### Verify the tree is clean

Run `git status`. The output must show nothing uncommitted — no modified files, no untracked files that belong to the project. If anything is left over, stage it and fold it into a follow-up commit explaining what was missed (don't amend a commit that already passed its hooks, unless the leftover is trivially part of that same commit and hasn't been reported yet). **The session ends with a clean working tree. No exceptions.**

---

## Phase 6: Report

```
## Done: Sprint NN — <title>

### Branch
`<branch-name>` (not pushed — commit locally, let the user decide when to open a PR)

### What was built
- Bullet list of what was created/modified, backend then frontend

### Adjustments from spec
- [Deviations and why — or "None — implemented as specified"]

### Verification
- Backend `make verify`/`make test`: PASS (N tests added, M total)
- Frontend `make verify`: PASS (N tests added, M total)

### Commits
- `<hash>` <type>(<scope>): <message>
- `<hash>` <type>(<scope>): <message>
- ... (one line per milestone commit, in order — this list IS the development history, not just a receipt)
- `<hash>` docs(<scope>): mark sprint NN done

### Next sprints
- [1-2 sprints now unblocked by this one, per the specs README's dependency table]
```

---

## Constraints

- **NEVER start on a dirty tree** — run `git status` first; stop if there are uncommitted changes
- **NEVER commit sprint work directly to `main`** — create/checkout the sprint branch first (see Input); every milestone and the final bookkeeping commit land there
- **NEVER skip Phase 0.5** — question the spec before touching the keyboard
- **NEVER implement only one stack** — this command is for vertical sprints; backend and frontend both ship, in that order, unless one is already `status:done` from a prior partial run
- **NEVER block on stdin** — `--noinput`, `--keepdb`, `-T`. Prefer `make test` over raw `manage.py test`
- **NEVER leave the working tree dirty** — clean `git status` at end of session
- **NEVER bypass pre-commit hooks** — fix the underlying issue, never `--no-verify`; if a hook fails, read the error, fix it, re-stage, re-commit
- **COMMIT PER MILESTONE, never one mega-commit** — each backend/frontend milestone from Phase 3 gets its own commit as it lands, with a message documenting what and why; the sprint status/index update is its own final, separate commit. A single end-of-task commit that bundles the whole sprint is exactly what this workflow must NOT produce.
- **Subagents never commit** — they implement and report back; the orchestrator reviews the real diff and commits. A subagent's own "clean tree" preflight can otherwise sweep up unrelated files into its commit.
- **NEVER push** — commit locally, let the user decide
- **NEVER implement beyond scope** — flag it in the report, don't fix it
- **NEVER ask the user to approve the plan** unless you have a genuine blocking question
- **NEVER fake test results** — if tests fail, fix or explain
- Follow CLAUDE.md absolutely: Portuguese UI text, English code, multi-tenancy, services layer, ApiError pattern
