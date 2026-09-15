# Apply PR Reviews: $ARGUMENTS

Read every review comment currently on an open PR — from `/review-pr`'s own local pass, from any
of the fork's bots, from a human, from anywhere — reconcile them against a local ledger, triage
each one against the real code, then fix what's real and reply to (and resolve) every thread.

**Invoke:** `/apply-pr-reviews <pr-url-or-number> [--dry-run]`

Examples:
- `/apply-pr-reviews https://github.com/<fork-owner>/ed-ambiente/pull/26`
- `/apply-pr-reviews 26 --dry-run`

Flags:
- `--dry-run` — classify every open item and report the plan; touch no file, no git state, no GitHub thread, no ledger

## Role in the bigger picture

This command holds the **only copy** of the triage rubric (Mindset, below). `/review-pr` doesn't
verify its own findings — it relies entirely on this command to do that, exactly as it would for a
bot's comment. `/ship-pr-via-fork` invokes this command as its "consolidate + triage" sub-phase
against the fork PR, right after `/review-pr` has posted. It's also meant to run standalone against
any open PR with review comments on it, regardless of who or what posted them.

Always fetch fresh from GitHub before triaging — never trust the local ledger alone. Other review
vectors (a bot, a human) can comment between runs; the ledger is a cache of *this command's own*
prior work, not the source of truth.

## Mindset

You are triaging automated *and* human-adjacent review comments, not obeying them. Every comment —
regardless of severity label or source — gets checked against the real code, not accepted on
confidence alone:

- Read the actual current file, not just the diff hunk shown in the comment.
- If the comment makes a factual claim about a library/framework API, **verify it empirically**
  against the installed version (e.g. `python -c "import django; print(django.VERSION)"` + inspect
  the real signature) rather than trusting either the commenter's or your own training-data memory —
  APIs get renamed across major versions and a stale-trained reviewer will confidently suggest
  reverting a correct, current call to a deprecated one. This exact thing happened before: a bot
  flagged `CheckConstraint(condition=...)` as a `TypeError` risk when Django 5.1+ renamed `check` to
  `condition` — `condition=` was the correct, current code, and applying the "fix" would have
  reintroduced deprecated API usage.
- Check git history/tickets/docs for whether something is intentional before calling it a bug
  (`git log -p`, `git show <commit>`, ticket docs under `docs/tickets/`).
- Trace the actual call sites (`grep`) before accepting a suggested refactor — a service reassigning
  its parameter instead of mutating it in place is only safe if every caller captures the return
  value; check every caller, not just the one shown in the diff.
- It's fine — expected — to reply "not a bug, here's why" and resolve the thread. It's also fine to
  reply "real gap, but the right fix needs a product decision" and leave the thread **unresolved**
  on purpose, so it doesn't silently vanish.
- This applies identically to a `claude-review`-sourced finding as to a bot's — don't wave a finding
  through just because "we" (a Claude session) found it, and don't dismiss it either just because it
  came from the same model family. Same evidence bar, both directions.

## Phase 0: Resolve target

1. Parse `$ARGUMENTS` for the PR URL/number (+ `--dry-run`). If a bare number, infer `owner/repo`
   from context if unambiguous, otherwise stop and ask.
2. `gh pr view <pr_number> --repo <owner>/<repo> --json number,headRefName,state,url` — stop if
   closed/merged.
3. `branch-slug` = `headRefName` with `/` replaced by `-` (same derivation as `/review-pr`).

## Phase 1: Load the ledger

Read `.claude/pr-review-notes/<branch-slug>.jsonl` if it exists (one JSON object per line).

**Discard any entry whose `pr_number` doesn't match the current PR's number.** The fork PR closes
and reopens with a new number every round (`/ship-pr-via-fork` Phase 1g); an entry from a previous
round's closed PR must never be treated as live — its `github_comment_id`/`thread_id` point at a
thread that may not even resolve the same way (or may not exist) on the new PR. Keep the file (for
history) but don't reconcile against those entries.

## Phase 2: Fetch fresh from GitHub and reconcile

```bash
gh api graphql -f query='
query {
  repository(owner: "<owner>", name: "<repo>") {
    pullRequest(number: <pr_number>) {
      reviewThreads(first: 100) {
        nodes {
          id isResolved path line
          comments(first: 5) { nodes { id databaseId author { login } body url } }
        }
      }
    }
  }
}'
```

For each thread's first comment:

- **Body contains `<!-- claude-review:v1 id=<id> -->`**: this is a `/review-pr` finding. Match it to
  the ledger entry with that `id` (same `pr_number`) and fill in `thread_id` if it was null. If the
  ledger has no matching entry (shouldn't normally happen, but the ledger could be missing/stale),
  reconstruct a minimal entry from the thread itself, `source: "claude-review"`.
- **No marker, not already in the ledger**: a new entry. `source` = the comment author's login
  (`coderabbitai`, `cubic-dev-ai`, `qodo-code-review`, or the human's handle). `status: "open"`.
- **Thread `isResolved: true`**: if a human resolved it, leave it — don't re-triage or reopen
  something a person already closed.

Also pull in the ledger's out-of-diff entries (Phase 3 of `/review-pr` — `github_comment_id`/
`thread_id` both `null`). They don't appear in `reviewThreads` at all since they were never posted;
carry them into this run's working set as-is.

If `--dry-run`, stop after building the reconciled set and report it (see Report section) — no
further phase runs.

## Phase 3: Triage every entry with `status: "open"`

Apply the Mindset above. Classify each as exactly one of:

- **Fixed** — real issue, applied a fix
- **False positive** — verified against real code/docs/version; record the evidence
- **Deferred** — real but out of scope for this PR (no write-path exists yet for the code in
  question, or it's a pre-existing systemic pattern this PR only replicates)
- **Needs a decision** — real gap, but the correct fix requires a product/architecture call this
  command can't make unilaterally

## Phase 4: Fix, verify, commit, push

Group fixes into cohesive commits — don't do one comment = one commit if several belong together;
don't cram unrelated fixes into one commit either. For every commit:

1. Apply the fix.
2. Add/update a test that would have caught the issue, when the change has real logic (a branch, a
   loop, a lock, a migration) — skip only for genuinely trivial one-liners.
3. Run targeted tests for the touched area, then the full `make verify` before pushing.
4. `git commit` with a message explaining the *why*, not just the *what*.
5. `git push <remote> <branch>` — the caller (e.g. `/ship-pr-via-fork`) tells you which remote; if
   run standalone, push to the PR's head remote (`gh pr view ... --json headRepositoryOwner`).

## Phase 5: Deferred → durable record

**A "Deferred" classification must leave a durable, searchable record — a PR reply is not enough.**
A fork PR gets closed at the end of its round; even on `origin`, nobody re-reads a merged PR's
thread history when the same bug pattern resurfaces later. Before marking an entry Deferred, check
whether it's already durably tracked some other way (a `# ponytail:` comment in the code, harvested
separately by `/ponytail-debt` — needs nothing further here). If it isn't:

Follow `/tech-debt`'s own convention exactly — **do not duplicate its instructions here, read that
command's Phase 6, item 6** for the up-to-date shape. In short: one
`docs/technical-debts/NNN-slug-{easy|normal|hard}.md` file (numbering, difficulty suffix, and
template matching the existing files in that directory), **and** an entry in
`docs/technical-debts/index.md` (tracking table + ordering list) in the same commit. Read
`index.md` at write time to pick the next free number — not from a listing you cached earlier in
this run — so a concurrent session numbering its own new item doesn't collide with yours. Stage
explicit paths (`git add docs/technical-debts/NNN-slug-{easy|normal|hard}.md docs/technical-debts/index.md`), never
`git add -A`.

Reference the new file's path in the GitHub reply (Phase 6) so both directions are discoverable.

## Phase 6: Reply and resolve

For every entry that has a `github_comment_id` (skip entries with `github_comment_id: null` — those
are out-of-diff findings with no thread to reply to; their disposition lives in the ledger only,
see Phase 7):

In the same language the human PR author uses in this repo (Portuguese):

```bash
gh api repos/<owner>/<repo>/pulls/<pr_number>/comments/<github_comment_id>/replies -f body="<reply>"
```

Reply body must reference concrete evidence — commit SHA if fixed, the grep/test/version-check
output if a false positive, the tech-debt doc path if deferred. Then, unless the entry is a genuine
**Needs a decision** case:

```bash
gh api graphql -f query='mutation { resolveReviewThread(input: {threadId: "<thread_id>"}) { thread { isResolved } } }'
```

Leave **Needs a decision** threads unresolved on purpose.

## Phase 7: Update the ledger

Rewrite `.claude/pr-review-notes/<branch-slug>.jsonl` with: every entry from this run's reconciled
set (Phase 2), each carrying its final `status` (`fixed` / `false-positive` / `deferred` /
`needs-decision`), `resolution` (one line), and `resolution_note` (the evidence referenced in the
reply, or the tech-debt doc path) — **plus every entry from a *different* `pr_number` that Phase 1
discarded from reconciliation**, carried over unchanged. This is what Phase 1's "keep the file for
history" actually means: the old-round entries aren't reconciled against, but they still have to
survive this rewrite or the file silently loses them every round. Include out-of-diff entries too
— they have a disposition even though no GitHub reply exists for them.

## `--dry-run`

Stop after Phase 2. Report the full reconciled set — every entry, its source, and the classification
you *would* apply in Phase 3 — but apply none of Phases 3–7. No file edit, no commit, no push, no
GitHub reply/resolve, no ledger write.

## Constraints

- Never force-push. Regular `git push` only.
- Never merge or approve the PR — not this command's call.
- Never apply a suggestion just because a source flagged it "critical" — severity labels aren't
  reliable signal on their own, from a bot or from `claude-review`. Verify.
- Never leave the working tree dirty between commits.
- Never attempt to reply to or resolve an entry with `github_comment_id: null` — there is no thread.
- Every "Deferred" entry gets a durable artifact (Phase 5), not just a reply.
- Only leave a thread unresolved when it genuinely needs a human decision.

## Report

```markdown
## Apply PR Reviews Complete: <owner>/<repo>#<pr_number>

- Entries: <N> total — <fixed> fixed, <false-positive> false positive, <deferred> deferred, <needs-decision> needs decision
- By source: claude-review <n>, coderabbitai <n>, cubic-dev-ai <n>, qodo-code-review <n>, human <n>, other <n>
- Out-of-diff (ledger-only, no GitHub reply): <N>
- Commits: <sha list>
- Tech debt opened: <docs/technical-debts/NNN-slug.md list>, or "None"

### Open items (need a human decision)
- <thread link — one-line description>, or "None"
```
