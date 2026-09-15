# Implement Epic Next Step: $ARGUMENTS

Implement the next actionable item from an epic folder containing multiple markdown specs, then finish with local verification, commit(s), and a clean working tree.

**Invoke:** `/implement <epic-folder-or-index.md> [--safe] [--with-tests] [--dry-run] [--allow-dirty]`

Examples:
- `/implement docs/financeiro/design/workflows`
- `/implement docs/financeiro/design/workflows/index.md --with-tests`

If `--dry-run` is provided, stop after plan and do not edit files.

---

## Goal

Given an epic directory with many spec files, this command must:
1. Discover the current epic status
2. Decide the **next best implementation step**
3. Implement end-to-end (backend/frontend as needed)
4. Verify locally (quality gates + tests)
5. Commit the implementation
6. Update ticket/spec status bookkeeping (if present)
7. End with `git status` clean

Keep scope to **one meaningful next step** per invocation.

---

## Mindset

You are a senior engineer working through an epic incrementally. Trust each spec's intent but not its stale details. The codebase may have changed since the specs were written. Deliver what each ticket *means*, not blindly what it *says*.

After selecting the next step, follow the same rigor as `/implement-sprint`: validate against reality, adjust when needed, ship clean code, and leave the repo clean.

---

## Specialist Personas (mandatory coordination)

Use coordinated specialists when useful:
- **Backend scope**: follow patterns from `.claude/agents/backend-engineer.md`
- **Frontend scope**: follow patterns from `.claude/agents/frontend-engineer.md`
- **Full-stack**: split responsibilities and converge into one coherent implementation

Always enforce:
- Multi-tenant safety (`organization=request.user.organization` boundaries)
- Portuguese for user-facing text, English for code
- Existing project conventions over speculative patterns
- CLAUDE.md rules: services layer, ApiError pattern, thin views/serializers

---

## Phase 0: Preflight

1. Parse flags from `$ARGUMENTS`:
   - `--safe` — prefer minimal deltas; explicit migrations/tests before broad refactors
   - `--with-tests` — add/expand tests even when the spec under-specifies them
   - `--dry-run` — plan only; no file edits
   - `--allow-dirty` — proceed with dirty tree; commit **only files touched by this run**
2. Resolve epic input (path after stripping flags):
   - If folder: scan for `index.md` and spec/ticket `.md` files
   - If file: treat it as epic index or specific ticket context
3. Validate path exists. If not, stop and report.
4. Check git state:
   - Default: require clean tree at start
   - If dirty and `--allow-dirty` is NOT provided: stop and tell user to stash/commit first
   - If `--allow-dirty`: proceed, but never commit unrelated dirty files

---

## Phase 1: Discover Epic State

Read epic docs and build a task map:
- Parse `index.md` (if present) and all ticket/spec markdown files in the epic folder
- Detect status markers such as:
  - `DONE - ...` in index rows
  - HTML comments like `<!-- status:done ... -->`
  - textual markers (`pending`, `blocked`, `in progress`)
- Detect dependency signals:
  - "Depends on", "blocked by", "requires", references to prior ticket IDs

Produce an internal structured list for each ticket/spec:
- id/path/title
- status: done | pending | blocked | unknown
- dependencies
- domain: backend | frontend | full-stack | docs-only
- risk/impact estimate

If no explicit status model exists, infer from code + tests + docs references.

If the selected ticket is already `status: done`, skip it and pick the next eligible item.

---

## Phase 2: Decide Next Step

Choose exactly **one** next ticket/spec to implement using this priority:
1. Not done
2. Not blocked by unresolved dependency
3. Highest unblock value for remaining epic items
4. Smallest safe vertical slice first (prefer mergeable increments)
5. Align with current codebase readiness (existing models/services/routes/components)

If multiple candidates tie, choose the one with:
- stronger acceptance criteria
- lower ambiguity
- higher probability of completing with green verification in one run

If all remaining items are blocked, stop and report blockers clearly.

Write a concise selection rationale before proceeding (or as the dry-run output).

If `--dry-run`, stop here. Report:
- epic path
- selected next step + why
- blocked items (if any)
- suggested implementation order for next 2-3 steps

---

## Phase 3: Validate Spec vs Reality

Before coding, validate the selected spec against current code:
- Referenced files exist?
- Patterns still current? (Read actual files — don't trust descriptions.)
- Dependency tickets appear completed? (Models/services/endpoints actually exist?)
- Data model assumptions still valid?
- Security/multi-tenancy constraints satisfied?
- Test plan sufficient?

Build a delta:
- **Stale** — things the spec says that are no longer true
- **Missing** — things the spec should have said but didn't
- **Wrong** — things the spec got backwards
- **Correct** — things that check out

Decide:
- **Yes, as-is** — proceed
- **Yes, with adjustments** — list adjustments, proceed
- **Blocked** — write status block on ticket (`<!-- status:blocked ... -->`), stop and report blocker
- **Needs clarification** — ask ONE focused question and wait (only for genuine product ambiguity)

If minor mismatches exist, adjust to current project conventions and note adjustments in the final report.

---

## Phase 4: Plan

Write a concise implementation plan — YOUR plan, not a copy of the spec:

```
## Implementation Plan

### Goal
One sentence: what this delivers.

### Selected Step
<ticket id + title + path>

### Adjustments from Spec
- [deviations and why, or "Spec matches codebase — implementing as specified."]

### Files
| Action | Path | What |
|--------|------|------|
| Create | ... | ... |
| Modify | ... | ... |

### Test Strategy
What to test and how — your assessment of what matters.

### Risks
Anything that could go wrong or needs extra care.
```

Do NOT ask the user to approve the plan unless you have a genuine blocking question from Phase 3.

---

## Phase 5: Implement End-to-End

Execute implementation with this order:
1. Backend foundations (models/migrations/services/serializers/viewsets/tests)
2. Frontend contracts (types/schemas/services/hooks/components/pages/tests)
3. Docs/spec notes needed for traceability

Required implementation standards:
- Thin views/serializers, business logic in services
- Explicit serializer fields (no accidental data exposure)
- Query performance hygiene (`select_related` / `prefetch_related`)
- API error mapping aligned with shared patterns
- Accessibility and responsive behavior for UI changes
- Match codebase conventions exactly — don't introduce new patterns
- Before calling a milestone done, check the `duplicate`/`coupling`/`brittle`/`orphan` smells from `CLAUDE.md`'s Critical Rules against the code you just wrote — same threshold discipline, no exceptions for "just this once"

If `--with-tests` is present, add/expand tests even when the spec under-specifies them.

If `--safe` is enabled, prefer minimal vertical slices; avoid broad refactors.

Run targeted tests incrementally as you go — don't wait until the end.

---

## Phase 6: Verify

Run targeted checks first, then full verification:

- Backend (if changed):
  - `cd backend && make verify`
  - `cd backend && make test`
- Frontend (if changed):
  - `cd frontend && make verify`

Fix failures and re-run until green. Never skip failing checks. Never fabricate results.

---

## Non-interactive execution (MANDATORY)

Agents run without a TTY. **Any command that blocks on stdin will hang forever.** Never pipe `yes` into a hung process — fix the command instead.

| Tool | Do | Don't |
|------|----|-------|
| Django tests | `make test` or `manage.py test … --noinput --keepdb` | `manage.py test` without `--noinput` |
| Django migrate/makemigrations | `--noinput` when flags exist | Commands that prompt to confirm |
| Stale test DB | `docker compose exec -T db psql -U postgres -c "DROP DATABASE IF EXISTS test_ed_ambiente;"` then re-run | Waiting for Django's interactive recreate prompt |
| Docker | `docker compose exec -T …` | `docker compose exec` without `-T` when scripted |
| Git | Normal `git commit`, `git add` | `git commit -i`, `git rebase -i`, `git add -i` |
| npm/Vitest | `npm test -- --run <file>` | `npm test` in watch mode without `--run` |

**Before running shell commands, ask:** "Will this prompt for input?" If yes, add `--noinput`, `--yes`, `-y`, `-T`, or use `make` targets that already encode safe flags.

---

## Phase 7: Commit Implementation

Unless `--dry-run`, commit the implementation once verification passes.

1. Inspect `git status`, `git diff`, and recent commit style (`git log -5`)
2. Stage only implementation-related files (be specific — don't `git add .`)
3. Commit message format:
   - `feat(<epic-scope>): implement <ticket-id-or-step>`
   - or `fix(<epic-scope>): implement <ticket-id-or-step>`
4. Let hooks run normally; if hook modifies files, include updates and create follow-up commit if needed (no bypass)
5. Record the commit hash: `git rev-parse --short HEAD` — needed for bookkeeping

---

## Phase 8: Update Epic Bookkeeping

If epic docs maintain status markers, update them:

### Step 1: Add status block to ticket header

Insert immediately after the ticket title and before the summary quote (`>`). If a status block already exists, replace it.

```markdown
# 001: Ticket Title

<!-- status:done implemented:2026-05-31 commit:abc1234 -->
<!-- adjustments: none -->

> Summary quote...
```

Schema:
- `status:done` | `status:blocked` | `status:pending`
- `implemented:YYYY-MM-DD`
- `commit:<short-hash>` — from the implementation commit (Phase 7), NOT the bookkeeping commit
- `adjustments:` — one-line summary, or `none`

Always write exactly TWO comment lines: status + adjustments.

### Step 2: Update index

Read the epic `index.md`. Find the row for this ticket and prepend a status marker to the Description column:
- Done: `DONE - <original description>`

### Step 3: Commit bookkeeping separately

```
docs(<epic-scope>): mark <ticket-id-or-step> as done

Ticket: <ticket filename>
Implementation: <short-hash from Phase 7>
```

---

## Phase 9: Final Cleanliness Gate (mandatory)

1. Run final `git status`
2. If any file from this run remains uncommitted:
   - stage + commit with appropriate message
3. End only when working tree is clean

If clean state cannot be achieved automatically (conflict, lock, permission), stop and report exact blocker plus next command to run.

---

## Final Report Format

```
## Epic Step Implemented

- Epic: <path>
- Selected next step: <ticket/spec id + title>
- Why this step: <short rationale>
- Adjustments from spec: <none or bullets>
- Verification: <commands run + PASS/FAIL>
- Commits:
  - <hash> <message>
  - <hash> <message> (bookkeeping, if any)
- Final git status: CLEAN
- Next suggested step: <next ticket/spec>
```

---

## Non-Negotiable Constraints

- Never fabricate completion or test results
- Never bypass hooks (`--no-verify`) or use destructive git commands
- Never commit unrelated dirty files when `--allow-dirty` is used
- Never leave the repo dirty at the end of the command
- Never push — commit locally, let the user decide when to push
- Never implement beyond the selected step's scope — mention adjacent issues in the report, don't fix them
- Keep scope to one meaningful next step per invocation
