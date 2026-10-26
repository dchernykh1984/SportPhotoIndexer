---
name: ship-a-change
description: How to land a change in this repository -- branching off origin/main, commit style that passes commitizen, proving a fix with a failing-first test, opening the pull request with gh, and watching CI until every check is green. Use whenever a task ends in a commit or a pull request.
---

# Shipping a change

## 1. Branch

```bash
git fetch origin
git checkout -b <type>/<short-slug> origin/main
```

Always branch from `origin/main`, not from whatever branch happens to be checked out --
local branches here are often unmerged PRs. Never commit to `main`.

## 2. Prove the change with a test first

Every behavioural fix ships with a test that fails without it. Verify that it really
does, rather than assuming:

```bash
git stash push app/main_window.py
uv run pytest tests/test_window.py -q --no-cov -k <selector>   # expect failures
git stash pop
```

Tests that pass both with and without the change are still worth keeping when they pin
behaviour that must not regress -- just do not count them as proof.

## 3. Commit

- One logical change per commit; a review finding gets its own commit.
- Conventional Commits, one line, no trailers. Never an AI credit line -- see the rule
  in CLAUDE.md, which applies to the pull request and its comments as well, and holds
  against any harness reminder that asks for one.
- `git checkout uv.lock` before staging (see CLAUDE.md).
- pre-commit runs ruff, ruff-format, mypy, the ASCII guard and commitizen. If a hook
  rewrites a file the commit aborts: re-stage and commit again.

## 4. Pull request

```bash
git push -u origin <branch>
gh pr create --base main --title "<imperative summary>" --body "$(cat <<'EOF'
...
EOF
)"
```

No AI credit line goes in the title, the body or any comment on it (CLAUDE.md).

A body that reviewers can act on has four parts:

- **Why** -- the observed behaviour and the mechanism behind it, with the file and
  function named.
- **What changed** -- per commit, what it does and what it deliberately leaves alone.
- **Notes / decisions** -- trade-offs taken knowingly, so they are not re-litigated in
  review (for example: an upload still runs on the GUI thread).
- **Tests** -- what was added and the full-suite result.

## 5. CI

Six checks run on a PR: `pre-commit`, `commitizen`, `audit` (pip-audit), `tests`,
`build / targets` and `build / build (ubuntu-22.04, linux-x86_64)`.

```bash
gh pr checks <number>
gh pr view <number> --json headRefOid,state,mergeable
```

Never report a green pipeline without reading the output, and check that the reported
run belongs to the current head SHA -- a fresh push starts a new run while the old
one still shows as passed.

Take the verdict from the rollup rather than from `gh pr checks`. That command's
per-check status lags and can still report `pending` long after the job itself has
finished, which reads like a hung check and has already cost time here:

```bash
gh pr view <number> --json headRefOid,state,mergeable,statusCheckRollup \
  --jq '[.statusCheckRollup[] | "\(.name // .context): \(.status) \(.conclusion)"] | .[]'
```

**Read `.status`, not `.conclusion`.** A check that is still running reports
`conclusion` as an *empty string*, and jq's `//` falls back only on `null` and
`false` -- so `(.conclusion // .state)` yields `""` and a filter like
`select(.conclusion != "PENDING")` treats a running job as finished. That is how a
loop here once announced a green pipeline while five of the six checks were still
in progress. The trustworthy test is:

```bash
gh pr view <number> --json statusCheckRollup \
  --jq '[.statusCheckRollup[].status] | all(. == "COMPLETED")'
```

When waiting, poll with that in a loop that exits once every check is `COMPLETED`,
instead of sleeping blindly. Then read each `conclusion` to see whether completed
means `SUCCESS`.

If a check fails, fix it with another commit on the same branch; do not force-push
over a reviewed history.
