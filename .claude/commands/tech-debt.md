# Resolve Technical Debt: $ARGUMENTS

End-to-end workflow for `docs/technical-debts/`: pick the next item (or a named one), find its **real** scope before trusting the doc, decide how to fix it, implement, verify, and close out the bookkeeping — tracking table, spec lifecycle, `ERRORS_FROM_THE_PAST.md`, `CLAUDE.md`/`.claude/rules/*.md` updates, and any *new* debt discovered along the way.

**Invoke:** `/tech-debt [item-number-or-slug] [--report-only] [--dry-run]`

Examples:
- `/tech-debt` — pick the next item automatically, explain the pick, then resolve it
- `/tech-debt 038` — resolve a specific item by number
- `/tech-debt 035-vehicle-model-portuguese-field-names-hard` — resolve by slug
- `/tech-debt --report-only` — just report the candidate + reasoning, don't implement
- `/tech-debt 017 --dry-run` — investigate real scope and plan, stop before editing

---

## Why this command exists

Every run of this workflow so far has found the doc's stated scope wrong — sometimes by 3-4x (item 017: doc said 64 sites/16 files, real was 223/43; item 018/025 similarly blew past their initial file counts). The doc captures *intent* and a *first guess*; this command's whole value is refusing to trust the guess and verifying against the live codebase before committing effort, then leaving the tracking doc more accurate than it found it.

---

## Phase 0: Preflight

1. `git status` — if the tree isn't clean, note exactly what's dirty. Don't assume it's yours: an unfamiliar untracked file or an unexpected diff in a shared file (`index.md`, `ERRORS_FROM_THE_PAST.md`) may be another session's in-flight work. Investigate before touching it — never delete, overwrite, or silently fold it into your own commit. If it's genuinely foreign, surface it to the user in your final report; don't stage or edit it.
2. Read `docs/technical-debts/index.md` in full (the "Ordem proposta" phases/gates AND the "Tracking" table — the table's ✅/⬜ status is the ground truth, the ordering list is a proposal that's been deliberately deviated from before).
3. Check the current branch (`git branch --show-current`). If it's `main`/`master`, this run must not commit directly to it — Phase 1 will create a dedicated branch once the item is picked. If already on a non-`main` branch, keep using it: never create a second branch on top of active work.

---

## Phase 1: Select the item

If `$ARGUMENTS` names a specific item (number or slug), that's the target — still run Phase 2 on it, don't skip investigation just because it was named explicitly.

Otherwise, pick automatically:

1. Walk the "Ordem proposta" phases in order, but **skip any phase/item sitting behind an explicit "Gate de negócio" note** (an infra-cost gate, e.g. Redis/Celery/Prometheus items deferred until there's a 2nd client) unless the gate's own trigger condition is now demonstrably met. Do not advance a phase just because it's "next in the numbered list" — the list is a proposal, not a queue.
2. Among currently-unblocked candidates, prefer one with an **active signal** — a failing test, a live bug, a violation of a rule already stated in `CLAUDE.md`, or an objective maintainability hotspot (a duplication cluster past the rule of three, a complexity×churn hotspot, a coupling gap, a brittle branch — typically filed by `/spaghetti-audit`) — over purely cosmetic/speculative debt. A red test, a documented-but-violated rule, or a hotspot with a measured number behind it is worth more than an item nobody's hit yet or a stylistic preference with no number to back it.
3. Skip anything already `✅ Feito`, `⏸️ Bloqueado`, or `❌ Descartado` in the tracking table (even if the ordering list still shows a stale link — that's exactly the kind of drift this command's own Phase 6 exists to fix).
4. If an item's resolution needs a **business/product/architecture decision** (e.g. "ratificar SLA com o cliente", "decidir se um enum legado pode ser renomeado", "escolher direção de migração de PK", "vira feature ou remove"), first verify the decision wasn't already made elsewhere and the doc is just stale (mirrors item 005 — check the actual code/commit history before accepting "needs a decision" at face value). If it's genuinely open, **do not skip it and move to the next item, and do not stop at "reporting it as a candidate needing a decision" either** — that's avoidance dressed up as caution. Ask the user directly, right now, in this same run: use `AskUserQuestion` when the options are concrete and enumerable (the doc usually already lists 2-3 real trade-offs), or plain conversation when the question needs more nuance than that tool's shape allows. Frame the actual trade-off (the options the doc lists, the real cost/risk of each) so the user can answer in one message. Once answered, that decision **is** the pick — continue through Phase 2 onward in the same run, don't treat the question as the finish line.
5. If several items tie, prefer the smaller one — a quick, high-signal win over a large speculative one, unless the user's `$ARGUMENTS`/recent conversation clearly asked for depth over speed.

State the pick, why (2-4 sentences, referencing the doc + what you found), and the planned approach — **then keep going**. Don't stop and wait for a go-ahead; the user can redirect you. Do stop, though, the moment a genuine decision-only-the-user-can-make surfaces (whether spotted in Phase 1 step 4 or found later in Phase 2/4) — and when you stop, **ask the concrete question, in the exact same message, not a follow-up turn**. Writing "this needs a decision" — or any paraphrase of it ("isso é uma decisão de arquitetura", "isso precisa de alinhamento de produto") — and then ending your turn without the literal question and its 2-3 concrete options attached is a failure of this command, not a cautious stopping point. The user has said directly, in response to exactly this failure mode: they are here to make these calls, asking costs one message, so don't dress up avoidance as diligence. If you catch yourself typing the diagnosis, the next words out — same message, same turn — must be the question itself (`AskUserQuestion` when 2-4 concrete options exist, plain conversation only when the trade-off genuinely doesn't fit that shape).

If Phase 0 found you on `main`/`master`, create and check out the branch now, before Phase 2 touches anything: `git checkout -b tech-debt/<item-slug>` (e.g. `tech-debt/037-cron-jobs-mask-per-item-failures-normal`). Skip this if you were already on a non-`main` branch — keep using it.

If `--report-only`, stop after this phase and present 2-3 ranked candidates with one-line reasoning each instead of committing to one. This does not relax step 4's ask-mandate: if one of those candidates needs a decision, ask it right now, in the same message as the report, instead of just noting "precisa de decisão" as one of the ranked lines. `--report-only` skips implementation, not the question.

---

## Phase 2: Investigate the REAL scope — never trust the doc's numbers

This is the phase that has caught every real surprise so far. Do not skip or shortcut it, even for an item that looks small.

1. Read the item's own spec file in full.
2. Grep for the pattern the doc's examples show — then **assume there are other shapes of the same bug the doc didn't enumerate**, and go looking for them:
   - A string/config construction usually has more than one call shape (direct literal, named parameter, default parameter, positional argument to a local helper). A grep tuned to one shape silently undercounts.
   - The same bug class often exists in **sibling files/classes** the ticket never named (a shared `setTimeout`-based hack copy-pasted into a second component; the same English-message leak in `ApiError`/`AuthenticationError`/a bare `Error`, not just the one class the doc calls out). Grep the surrounding directory/module for the same shape before declaring scope closed.
   - Check for **other paths that reach the user** beyond the one the doc assumes — a component reading `error?.message` directly instead of going through the shared formatter is exactly this kind of gap.
3. When the scope estimate materially changes (order of magnitude, or the fix mechanism turns out different from what the doc assumed), call `advisor()` before committing more effort — it's caught real gaps in this exact spot every time it's been used this way.
4. Decide: is everything you're finding genuinely **this item**, or does some of it belong to a **separate, new** piece of debt? Don't scope-creep the current fix to cover an unrelated finding — file it as a new item instead (see Phase 6, step 5). Signs it's separate: different root cause, different owner/decision needed, or fixing it would change response/behavior shape rather than just translating/adjusting existing behavior.
5. Write down the closed scope precisely (exact file list + count) before moving on — you'll need it for the tracking-table entry and to size Phase 3.

If `--dry-run`, stop here and report: real scope found, how it differs from the doc, and the plan from Phase 3 below — no edits.

---

## Phase 3: Plan the fix

**Small/contained** (roughly ≤15 changes across ≤3 files): just fix it directly. No batching, no guard test unless the bug is a genuine recurring mechanism.

**Large mechanical fix across many files** (the common case once Phase 2 does its job):

1. If the bug is systemic (the same mistake could be reintroduced later), **write a regression guard first** and confirm it's RED (catches the real count of current violations) before fixing anything. A text/source scan for the failure *shape* (not just one function/class name) is usually more robust than an AST check here — see `frontend/src/shared/utils/apiErrors/NetworkError.messages.test.ts` for the reference pattern (scans raw source for marker words across all three call shapes it found, not just one constructor name).
2. Split the file list into **disjoint batches** (no two batches touch the same file) sized evenly by **edit count**, not file count — a file with 13 occurrences and a file with 1 don't belong in the same-sized batch as their neighbors.
3. Dispatch via the `Agent` tool, **multiple invocations in one message** for true parallelism. Do **not** reach for the `Workflow` tool unless the user has explicitly opted into multi-agent orchestration this session (an "ultracode" cue or an explicit ask) — a `/tech-debt` invocation alone is not that opt-in.
4. Each batch's prompt must give the agent: the exact assigned file list with expected occurrence counts, the exact pattern(s)/shapes to find (including any non-obvious shape Phase 2 discovered — call out by name any file that needs special handling, e.g. "this file's message is a positional argument to a local helper, read the whole file, don't just grep"), the house terminology/style to match (point at one concrete already-correct exemplar file in the codebase to calibrate tone/verb choice), explicit boundaries (only change the string/value in question, never touch identifiers/imports/other logic, never touch test files, skip anything already correct), and a request for a structured `file:line: old → new` report back plus a self-verification grep.
5. Decide up front whether this item also needs: a new test, an `ERRORS_FROM_THE_PAST.md` entry, a `CLAUDE.md`/`.claude/rules/*.md` convention update. Note it now so Phase 6 isn't a surprise.

---

## Phase 4: Implement

- If agents were dispatched, wait for their completion notifications — don't poll, don't fabricate a result before it lands.
- After batches land (or right after a direct fix), **re-run the scope-closing check from Phase 2 with a couple of *different* phrasings/shapes** than the original marker list, not just the original grep. Agents (and greps) tuned to one shape reliably miss a sibling shape — e.g. a marker list built around `"Failed to ..."` will miss `"Login failed"`/`"<Noun> failed"` unless you deliberately widen it after the first pass comes back clean.
- Fix any small residue (a handful of stray lines) yourself directly — don't spin up a whole new batch of agents for 2-3 leftover strings.
- If Phase 0/1 flagged a concurrent foreign change in a file you also need to edit (e.g. `index.md`), keep your edit physically separate from theirs (different section/row) so the hunks stay separable for `git add -p` later — don't rewrite their content.

---

## Phase 5: Verify

Run, in this order, stopping to fix and re-run on any failure:

1. The guard/regression test from Phase 3, if one was written — must be fully green (zero offenders), not "mostly green."
2. Type-check (`tsc --noEmit` / `mypy` as applicable to what changed).
3. `git diff --stat` — confirm **only the expected files** changed and the line-change counts roughly match the expected occurrence counts per file. A surprise file in the stat is a red flag: read it before proceeding.
4. Full `make verify` (backend and/or frontend, whichever was touched). If it risks exceeding the tool's timeout, run it with `run_in_background: true` and wait for the notification — don't poll, don't shrink the check to fit the timeout.
5. If the item started from a specific failing symptom (a named flaky test, a specific bug report), re-run **that exact symptom** 2-3 times before declaring it fixed — a guard test proving "no English text remains" is not the same evidence as "the originally-flaky test now passes reliably."

Never report a check as passing without having actually run it in this turn.

---

## Phase 6: Close out the bookkeeping

This is the ceremony specific to this doc set — don't skip steps because the code fix is already done.

1. **Tracking table** (`docs/technical-debts/index.md`): update the item's row — status `✅ Feito`, today's date, and an Observações cell that records what *actually* happened, especially where it diverges from the original doc (real scope found, root cause, decisions made, anything deliberately left out of scope and why). Terse but complete — this cell is often the *only* record once the spec file is deleted (step 2).
2. If the item had a markdown link in the "Ordem proposta"/"Fora da ordem" list, convert it to plain backtick text with a trailing `(✅ feito, spec removida, ver tracking)` — matching the convention already used for every other closed item without a surviving spec file.
3. **Delete the item's own spec `.md` file — always, no exceptions.** The user tracks outstanding debt by which `.md` files still exist in `docs/technical-debts/`; a done item's spec left in place reads as unfinished work and defeats that signal. There is no "but it's cited elsewhere so keep it" case: `git grep` the **whole repo** (not just `docs/`) for its filename first, and for every hit — a code comment/docstring, `CLAUDE.md`, `ERRORS_FROM_THE_PAST.md`, another `docs/technical-debts/*.md` file (a `spaghetti-audit-*.md` report, another item's spec, `investigar-depois.md`) — redirect the citation to `docs/technical-debts/index.md` item N (plain backtick name + trailing `(✅ feito, spec removida, ver tracking)`, matching the "Ordem proposta"/"Fora da ordem" convention) rather than leaving a dangling reference, then delete the file. Do this even for a doc that reads like a "worked incident record" — the record lives on in the tracking table's Observações cell (step 1), which is exactly why that cell has to be complete, not the spec file.
4. If a genuinely reusable root-cause lesson surfaced (a *mechanism* that could recur — not "we translated some strings"), append an entry to `ERRORS_FROM_THE_PAST.md` following its template exactly (Symptom/Root cause/Rule/Guardrail/Refs). Write the **Rule** line about the general shape of the failure, not about this specific ticket or function name — that's what makes it reusable instead of reading like a changelog entry.
5. If the lesson is area-specific (frontend or backend) and something a future implementer needs to know without reading the ledger, add it to that area's `CLAUDE.md` — or, if it only applies to one file type/pattern (e.g. only `models.py`), to the matching `.claude/rules/*.md` file instead, so it doesn't add noise to unrelated edits.
6. If Phase 2 or 4 surfaced a genuinely separate piece of debt (not in scope of the item you just closed), write it as its own numbered spec — `0NN-slug-{easy|normal|hard}.md`, matching the existing template shape (Contexto/Objetivo/Investigação necessária/Critérios de aceite/Riscos se nada for feito) — and register it in both the ordering list (under a new "Fora da ordem original — achado em <date> durante a execução do item N" section) and the tracking table, marked `⬜ Pendente`. Do not implement it in the same run unless the user says otherwise.

---

## Phase 7: Git hygiene and commit

1. Re-check `git status` immediately before staging. If anything unfamiliar appeared since Phase 0 that this run didn't create, stop and surface it — don't fold it into your commit.
2. **Never `git add -A` or `git add .`** — stage explicit paths. If a shared file (typically `index.md`) carries both your edits and a foreign, still-unstaged change in separate hunks, use `git add -p` to select only your hunks and leave the rest for its owner to commit.
3. Expect the pre-commit hook's auto-fix two-pass: formatters/linters may rewrite staged files, which blocks the first commit attempt. Re-`git add` the same explicit paths and commit again — this is normal, not a failure to investigate. Never bypass with `--no-verify`.
4. **Confirm the commit actually landed with `git log --oneline -1` showing a NEW commit hash** — do not trust a hook's stdout alone as proof; a blocked commit's hook output can look superficially identical to a successful one, especially through any output-compressing proxy.
5. One commit for the fix itself. A separate commit for a newly-discovered/newly-filed debt item (step 6 above) if it's substantial — keep milestones separable, matching this project's "commits por milestone" convention. Trivial tracking-only edits can ride in the same commit as the fix.
6. Never push — commit locally, the user decides when to push.

---

## Final Report Format

```
## Tech Debt Resolved: <item number> — <title>

- Why this item: <one-line rationale from Phase 1>
- Doc's stated scope vs. real scope: <e.g. "64 sites/16 files → 223/43">
- Root cause / mechanism: <one or two sentences>
- Fix approach: <direct edit | N parallel batches, guard test written>
- Verification: <checks run + PASS/FAIL, exact commands>
- Bookkeeping: tracking row updated, spec deleted (citations redirected: <list|none found>), EP-NNN <added|n/a>, CLAUDE.md/rules update <yes (files)|n/a>
- New debt filed: <item number(s) + one line, or "none">
- Commits: <hash> <message> [, <hash> <message> ...]
- Final git status: <CLEAN | note on anything deliberately left for the user>
```

If `--report-only`: report the ranked candidates and stop — no implementation section.

---

## Non-Negotiable Constraints

- Never trust the doc's stated scope/count without re-verifying against the live codebase (Phase 2 is mandatory, not optional for "obviously small" items).
- Never leave a closed item's spec `.md` file in place — deletion is mandatory, no "cited elsewhere so keep it" exception. Never delete it without a repo-wide `git grep` for inbound references first, and never leave a dangling reference: redirect every hit (code comment, `CLAUDE.md`, `ERRORS_FROM_THE_PAST.md`, another `docs/technical-debts/*.md`) to the tracking table entry before deleting.
- Never `git add -A`/`git add .`.
- Never treat a hook's text output as proof a commit landed — check `git log` for a new SHA.
- Never silently edit, delete, or commit an unfamiliar file/change you didn't create this run — surface it.
- Never expand the current item to cover an unrelated finding — file it as new debt instead (Phase 6.6).
- Never invoke the `Workflow` tool for the parallel-batch step without an explicit user opt-in this session.
- Never skip the "explain the pick before implementing" step, even in auto mode.
- Never fabricate a verification result or skip re-running the original failing symptom when one existed.
- Never push, and never bypass pre-commit hooks.
- Never commit directly on `main`/`master` — create `tech-debt/<item-slug>` first (Phase 0/1), unless already on a non-`main` branch.
- Never label an item "needs a decision" and quietly move to the next one, or stop at a report-only note, without actually asking the user the concrete question in the same run — surfacing without asking is the failure mode this rule exists to kill.
- Never end a turn on the diagnosis alone ("this needs an architecture/product decision"). The question and its concrete options belong in that same message. This has already failed once in practice — the user had to interrupt and say "just ask me" — so treat it as a proven failure mode, not a hypothetical one.
