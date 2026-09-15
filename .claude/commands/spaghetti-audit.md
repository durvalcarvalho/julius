# Spaghetti Audit: $ARGUMENTS

Whole-repo, one-shot scan for the maintainability smells no existing gate already catches:
duplication past the rule of three, complexity×churn hotspots, cross-app coupling gaps,
OCP-violating branch fan-out, and code kept alive only by its own test. Reports and files
candidates into `docs/technical-debts/index.md` —
**never fixes in the same run**. This is the structural counterpart to `/ponytail-audit`: that
skill finds what to delete (over-engineering, bloat); this one finds what to disentangle
(under-structuring, spaghetti).

**Invoke:** `/spaghetti-audit [scope]`

Examples:
- `/spaghetti-audit` — scan the whole repo
- `/spaghetti-audit backend` — scan only `backend/`
- `/spaghetti-audit inventory` — scan one app/module

---

## Why this exists

This codebase already runs several architecture fitness functions as *regression guards*:
`complexipy` and `sonarjs/cognitive-complexity` cap per-function complexity at 15, `check-max-lines*.sh`
caps file size at 800 lines, and `import-linter`'s 3 contracts (`django-layers`,
`authz-no-domain-imports`, `parties-is-leaf`) cap layering/leaf-module violations at 0. All of
these block *new* regressions. None of them *search* for where the same category of problem
already accumulated before the gate existed, or in the gaps the gate doesn't cover.

The model to follow is the 2026-08-01 dead-code sweep (`docs/technical-debts/index.md`, items
055/056): search for a smell, evaluate any tool's cost/benefit honestly (`vulture` was evaluated
and *rejected* — 100% false-positive rate on this codebase's reflection patterns, ongoing
maintenance cost exceeded the benefit), and file only what survives scrutiny. This command
generalizes that one-off sweep into a repeatable, narrowly-scoped audit.

**Do NOT re-detect what already runs in CI/pre-commit** — that's alert fatigue, not a finding:

- Per-function complexity → `complexipy` (backend, ceiling 15) / `sonarjs/cognitive-complexity` (frontend, ceiling 15)
- File size → `scripts/check-max-lines.sh` / `check-max-lines-frontend.sh` (800 lines, pre-commit)
- Layering / leaf-module boundaries → `import-linter`'s 3 existing contracts

This audit exists only for what those miss.

---

## Tags

- `duplicate:` — the same logic/shape repeated in **3+** places (Fowler/Don Roberts' Rule of
  Three: 2 copies isn't yet worth abstracting, 3 is — abstracting at 2 risks the wrong
  abstraction). Name the extraction point — the fix is a shared function/interface *because* a
  3rd real instance just proved the shape is stable, never speculatively ahead of that.
- `hotspot:` — high complexity score **and** high git churn on the same file/function (Tornhill's
  method: complexity only costs you if you keep touching it). Cite both numbers — high complexity
  with near-zero churn is not a finding, don't report it.
- `coupling:` — one app reaching into a sibling app's internals (model fields, private helpers)
  instead of its public service/serializer surface, in an app pair the 3 existing `import-linter`
  contracts don't already cover. Name the two apps and the exact reach.
- `brittle:` — the same type/enum discriminator branched on (`if`/`elif`/`match`) at **3+** call
  sites — adding a new case means editing all of them (OCP violation in practice). Name the
  discriminator and the call sites — the fix is usually extracting a shared interface/protocol
  (a strategy map, a `Protocol`/ABC, a registry) so a new case is added in ONE place and every
  call site respects it automatically, instead of touching N places by hand.
- `orphan:` — a function/class/module whose only referrers, anywhere in the repo, are its own
  test file(s) — kept alive by a test that exercises nothing real (item 055's exact finding,
  generalized). Name the symbol and confirm the referrer count with the technique in Hunt §5
  before reporting — this is the one tag it's tempting to over-report on a bad grep.

## Hunt

1. **Hotspots**: `cd backend && uv run complexipy . -i -s desc --output-csv` for the ranked
   complexity list (already-installed tool, no new dependency). Cross-reference the top ~20
   against 6-month churn: `git log --since="6 months ago" --name-only --pretty=format: -- backend
   | sort | uniq -c | sort -rn`. A file/function high on both lists is a hotspot.
2. **Duplication**: grep for repeated literal blocks or near-identical function bodies (same
   shape, different names/values) within an app or across sibling apps — the same technique
   `/tech-debt` Phase 2 already uses to find sibling occurrences of one *bug* shape, applied here
   to one *logic* shape. Only report at 3+ real occurrences.
3. **Coupling**: for sibling-app pairs in `backend/pyproject.toml`'s `root_packages` not already
   covered by an `import-linter` leaf contract, grep for cross-app imports reaching past
   `serializers`/`services` straight into another app's `models` or internal helpers.
4. **Brittle branches**: grep for the same enum/type name used as a discriminator across multiple
   files (e.g. `grep -rn "== .*Status\."` or whatever shape the actual code uses) — 3+ call sites
   doing the same case-by-case logic is the signal.
5. **Orphans (test-only code)**: this codebase already decided *not* to run a generic AST
   dead-code tool as a trusted verdict — `vulture`, evaluated in tech debt 056, had a 100%
   false-positive rate on this codebase's reflection patterns (`TYPE_CHECKING` string
   annotations, DRF nested-route `@action` kwargs, pytest fixture name-shadowing — see
   `ERRORS_FROM_THE_PAST.md`). That decision stands; don't re-litigate it or wire `vulture`'s
   output straight into a finding. Use it only as an optional *candidate generator*
   (`uv run vulture . --min-confidence 80 --exclude ".venv,migrations,tests"`, backend), then
   confirm every candidate — from vulture or from your own reading — with the technique item 055
   already proved for frontend, generalized: grep the exact **defined identifier name** (not its
   import path — barrel/re-export-proof) across the whole repo. An `orphan:` finding requires
   every hit outside the definition site to live under `tests/`/`test_*.py`. Frontend: re-run
   `npx knip` (already zero-cost) plus the same identifier-grep for its documented blind spot
   (a component/hook whose only importer is its own test file, item 055).

## Output

One line per finding, ranked worst first: `<tag> <what's tangled>. <fix direction>. [path(s)]`.
Cite the actual numbers (complexity score, churn count, occurrence count) — a finding without a
number behind it is a guess, not a finding, drop it. End with:
`net: N hotspots, M duplication clusters, K coupling gaps, L brittle branches, P orphans.`
Nothing found: `Estruturado. Nada a reportar.`

## Filing

For each finding that clears its objective threshold (not "a pattern would look nicer here"):

1. Write it as its own numbered spec (`0NN-slug-{easy|normal|hard}.md`) in
   `docs/technical-debts/`, following `/tech-debt`'s own Phase 6 step 6 convention. Register it in
   `docs/technical-debts/index.md`'s tracking table as `⬜ Pendente`, under a new "Fora da ordem
   original — achados em `<date>` (spaghetti-audit)" section — same shape as the 2026-08-01
   dead-code sweep (items 055/056).
2. Do not fix anything in this run — filing only. Implementation happens later through
   `/tech-debt`, which treats a filed finding as a valid "active signal" pick (see its Phase 1).

## Boundaries

- Scope: entanglement, duplication, coupling, OCP fan-out, and test-only orphans. Over-engineering and bloat are
  `/ponytail-audit`'s job — don't re-report what that skill would flag. Correctness bugs,
  security, and performance are out of scope — route them to a normal review pass or `/tech-debt`
  directly.
- Never report a finding without a measured number backing it. "This violates SRP" with no number
  is not a finding here — that instinct is real, but it belongs in review of a diff you're already
  writing, not in this sweep.
- One-shot. Lists and files candidates. Fixes nothing.
- If `$ARGUMENTS` narrows scope to one app/module, still check `coupling:` in both directions —
  what that app reaches into, and what reaches into it.
