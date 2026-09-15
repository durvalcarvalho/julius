# Review PR: $ARGUMENTS

Run the repo's own reviewer subagents against an open PR's diff and post their findings as real
GitHub review comments — a self-hosted reviewer pass, alongside whatever bots/humans also review
the same PR.

**Invoke:** `/review-pr <pr-url-or-number> [--repo owner/repo] [--dry-run]`

Examples:
- `/review-pr https://github.com/ed-ambiente/ed-ambiente/pull/204`
- `/review-pr 204 --repo ed-ambiente/ed-ambiente`
- `/review-pr 26 --repo <fork-owner>/ed-ambiente --dry-run`

Flags:
- `--repo owner/repo` — required when the PR argument is a bare number (a URL is unambiguous on its own)
- `--dry-run` — run the subagents and build the comment payloads, print what would be posted, write nothing (no GitHub post, no ledger write)

## Role in the bigger picture

This command only **lists**. It does not verify or triage its own findings before posting — it
casts a wide net, the same way any of the SaaS review bots does. Rigorous verification lives
entirely in `/apply-pr-reviews`, which re-checks *every* finding from *every* source (this
command's own, plus whatever bots/humans commented) against the real code before anything gets
fixed or dismissed. Don't add a verification pass here — it would just duplicate that command's job
and risk drifting out of sync with it.

`/ship-pr-via-fork` invokes this command as its "local review" sub-phase against the fork PR. It
is also meant to be run standalone against any open PR.

## Phase 0: Resolve target

1. Parse `$ARGUMENTS`. If the PR argument is a full URL, extract `owner`, `repo`, `pr_number` from
   it directly. If it's a bare number, require `--repo owner/repo`; stop and ask if missing.
2. `gh pr view <pr_number> --repo <owner>/<repo> --json number,headRefName,baseRefName,state,headRepositoryOwner` —
   stop if the PR doesn't exist or is already closed/merged (nothing to review).
3. `branch=<headRefName>`; derive `branch-slug` by replacing `/` with `-` (used for the ledger
   filename in Phase 4).

## Phase 1: Establish the real diff

Do **not** use local `git diff` — the local checkout can be behind what's actually pushed.

```bash
gh pr diff <pr_number> --repo <owner>/<repo> > /tmp/review-pr-<pr_number>.diff
gh pr view <pr_number> --repo <owner>/<repo> --json headRefOid -q .headRefOid   # commit_id for the review payload
```

Parse the diff to build a map of `path -> set of line numbers that are part of a hunk` (the
"postable" lines — anything else is out-of-diff, see Phase 3). Keep the `--name-only` file list too:

```bash
gh pr diff <pr_number> --repo <owner>/<repo> --name-only
```

## Phase 2: Run the reviewer subagents

Split the changed-files list into backend (`backend/`) and frontend (`frontend/`) paths.

- If any backend file changed: launch `backend-reviewer` (Agent tool) with the PR's backend diff
  and file list.
- If any frontend file changed: launch `frontend-reviewer` similarly, in parallel with the above.
- Skip either agent entirely when its area has zero changed files — don't spawn it just to get an
  empty report.

Give each agent: the diff for its area (`gh pr diff <pr_number> --repo <owner>/<repo> -- backend/`
and `-- frontend/`), the full changed-file list for context, and — same as `/ship-pr-via-fork`
Phase 2b — a summary of any decisions already known to be intentional in this branch, if you have
that context, so agents don't re-flag settled decisions as new bugs.

**Hard constraint, same as `/ship-pr-via-fork` Phase 2b:** these subagents are review-only. They
must return a ranked list — `file:line — severity — one-line defect — concrete failure scenario` —
and must never edit files, commit, or call `gh` themselves. Only this command's orchestrating turn
posts anything. Don't loosen this even though the subagent already has `Bash` access for its own
investigation (running tests, grepping, checking library versions) — investigation reads, it never
writes or posts.

## Phase 3: Classify each finding as in-diff or out-of-diff

For each finding, check whether `path:line` is in the postable-lines map from Phase 1.

- **In-diff**: postable as an inline review comment.
- **Out-of-diff**: a pre-existing line the diff doesn't touch (a systemic pattern the PR merely
  extends, or something the reviewer noticed while reading around the change). GitHub's review API
  rejects (422) an inline comment outside the diff hunk — **never** fall back to dumping these into
  the review's general body text either; that turns into a dumping ground when there are several,
  and it's redundant work if the batch POST partially fails (see Phase 5). These just go straight
  into the ledger in Phase 4 with no GitHub post at all — `/apply-pr-reviews` still triages and can
  still fix them, it just never attempts to reply to a thread that doesn't exist.

## Phase 4: Build the ledger entries

Generate one run-nonce before assigning any IDs — `run_nonce=$(date +%s%N)` (nanosecond
resolution; plain `+%s` can collide when two runs start within the same second) — and assign
every finding this run an `id` of `cr-<run_nonce>-<n>` (sequential `n` within this run). The
nonce makes IDs unique across separate `/review-pr` runs on the same branch/PR; a plain `cr-<n>`
restarting from 1 every run would collide with an earlier run's ledger entry of the same ID and
make `/apply-pr-reviews`'s ID-based matching ambiguous. Build the comment body with the identity marker — required because `gh` posts as the
authenticated human account, so without a marker in the body, `/apply-pr-reviews` cannot tell "the
Claude review posted this" apart from "the PR author left this note" just from `author.login`:

```
<!-- claude-review:v1 id=<id> -->
**[<severity>]** <one-line summary>

<explanation / concrete failure scenario>
```

Append one JSON object per finding to `.claude/pr-review-notes/<branch-slug>.jsonl` (create the
directory if missing):

```json
{"id": "cr-1786100000-1", "pr_number": 204, "source": "claude-review", "path": "backend/x/y.py", "line": 88,
 "severity": "high", "summary": "one-line summary", "body": "full explanation",
 "github_comment_id": null, "thread_id": null, "status": "open", "resolution": null, "resolution_note": null}
```

`github_comment_id`/`thread_id` start `null` for everyone — filled in Phase 5 for whatever actually
gets posted (in-diff findings only).

## Phase 5: Post the in-diff findings

Build one JSON payload for the review:

```json
{
  "commit_id": "<headRefOid from Phase 1>",
  "body": "Revisão automática (Claude) — <N> achados dentro do diff, <M> fora do diff registrados só no ledger local.",
  "event": "COMMENT",
  "comments": [
    {"path": "backend/x/y.py", "line": 88, "body": "<!-- claude-review:v1 id=cr-1786100000-1 -->\n**[high]** ..."}
  ]
}
```

**Never use `event: "APPROVE"` or `"REQUEST_CHANGES"`** — same constraint as `/ship-pr-via-fork`:
this command only comments, it never approves or blocks a PR.

```bash
gh api repos/<owner>/<repo>/pulls/<pr_number>/reviews --input payload.json
```

Capture the created review's `id` from this call's response (`.id`, the REST review ID) — Phase 5's
next step needs it to scope the comment fetch to exactly this run.

**The review is all-or-nothing** — a single invalid `path`/`line` in the `comments` array fails the
*entire* POST, including the valid ones. If the batch call returns 422:
1. Retry posting one comment at a time (`comments` with a single item each) to isolate which
   one(s) are invalid and still get the valid ones posted.
2. For any comment that still 422s alone, log it as out-of-diff in the ledger (Phase 4's
   already-written entry stands; just leave `github_comment_id` null) instead of losing it — your
   line-map from Phase 1 should have already caught this, but the diff can shift between when you
   built the map and when you post if this run took a while.

After a successful post, fetch this review's own comments — scoped by `pull_request_review_id` to
the review `id` captured above, not by grepping every comment on the PR for the marker (a prior
`/review-pr` run's own `cr-<other_nonce>-N` comments would otherwise also match the same loose
pattern):

```bash
gh api repos/<owner>/<repo>/pulls/<pr_number>/comments --jq \
  --arg review_id "<review id from the reviews POST>" \
  '.[] | select((.pull_request_review_id | tostring) == $review_id) | {id, body}'
```

Match each returned comment back to its ledger entry by the `id=cr-<nonce>-N` in the body, and
update that entry's `github_comment_id` (the numeric `id` here — this is the REST `databaseId`).
Thread IDs
(GraphQL node IDs, needed later for `resolveReviewThread`) come from the same
`reviewThreads` query `/apply-pr-reviews` already runs — no need to fetch them here too; leave
`thread_id` null and let `/apply-pr-reviews` fill it in when it reconciles.

## `--dry-run`

Run Phases 0–4 in full, **including writing the ledger** (`github_comment_id`/`thread_id` stay
`null` for every entry, exactly like an out-of-diff finding) — skip only Phase 5's `gh api` POST.
Writing the ledger even in dry-run matters: `/apply-pr-reviews --dry-run`'s reconciled set is built
from GitHub threads plus this ledger, so skipping the ledger write here would make a fork-round
dry-run silently exclude every self-hosted finding from the reported plan. Print, per finding:
severity, path:line, in-diff or out-of-diff, and the comment body that would have been posted.

## Constraints

- Never approve or request changes — `event: "COMMENT"` only, always.
- Never let a reviewer subagent commit, edit, or call `gh` — findings only, posting happens here.
- Never fall back to a general PR-body comment for out-of-diff findings — ledger only.
- Never skip the identity marker — it's the only way `/apply-pr-reviews` can attribute authorship correctly.

## Report (only when not invoked from `/ship-pr-via-fork` — see its Phase 1 for how it folds this in without a duplicate report)

```markdown
## Review PR Complete: <owner>/<repo>#<pr_number>

- Reviewers run: <backend-reviewer|frontend-reviewer|both>
- Findings: <N> total — <in-diff> posted, <out-of-diff> ledger-only
- Ledger: .claude/pr-review-notes/<branch-slug>.jsonl
- Posted review: <review URL, or "none (--dry-run)">
```
