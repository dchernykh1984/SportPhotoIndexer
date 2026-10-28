---
name: review-cycle
description: How to run a review cycle on a branch or pull request here -- validating findings, landing one commit per valid finding with a failing-first test, fixing failed checks until the pipeline is green, and posting the summary back to the PR. Includes the bug classes this codebase keeps producing. Use when asked to review, to do review cycles, or to act on review findings.
---

# Review cycle

A cycle is: review, validate each finding against the code, fix every valid finding
in its own commit, push, bring the pipeline to green by fixing each failure in another
commit, then report. A cycle is not finished while a valid finding is unfixed or a
check is red; never end one at the list of findings.

Conditions in the request govern what happens after the fixes, never whether to make
them. "If nothing serious turns up, release" and "if something serious is found, tell
me and ask what next" both mean: fix every valid finding, get the pipeline green, then
report what was serious and ask before merging or releasing. Merge, tag or release
only when the person asked for it.

## Reviewing

Use the `code-review` skill against the PR number or the branch. Effort `high` is the
useful default here: the code is small, and the expensive bugs are the ones that only
show up in a specific user workflow.

## Triage

Take every finding seriously, but check the claim against the code before acting -- a
report can be wrong about the mechanism while pointing at a real problem, or right
about the mechanism and irrelevant in practice. State plainly which findings are valid
and why, and fix them all rather than the convenient subset.

A finding is worth a commit when it changes what the program does for a user: wrong
data saved, a crash, an unattended path that blocks on a dialog, work silently lost.
Cosmetic notes about a comment or a name go in with the nearest real fix.

## Fixing

One commit per finding, each with a test that fails without it (see `ship-a-change`
for the stash check). Keep the commit message about the user-visible effect, not the
mechanism: `fix: keep Enter on the photo the user was typing for`.

## Pipeline

Push the fixes and wait for every check on the new head (see `ship-a-change` for
reading the rollup). A failing check is a finding of its own: read its log, fix the
cause in a new commit, push and wait again, until every check passes on the head SHA.
Report the cycle only then.

## Reporting

Post one comment per cycle with a table of finding to fix commit, so the reviewer can
follow what was accepted and how it was closed. Every row names its fix commit, or
the reason the finding was declined after checking it against the code; no finding is
left open:

```bash
gh pr comment <number> --body "$(cat <<'EOF'
### Review cycle 1
| Finding | Fix |
| --- | --- |
| ... | `<sha>` ... |
EOF
)"
```

Then run the next cycle against the fixed branch. Fixes introduce their own bugs: the
second cycle here found that a fix for a leaking value across groups still leaked the
same value across a restart.

## Bug classes this codebase keeps producing

Check these first; each one has already shipped at least once.

- **Exceptions escaping into a Qt slot.** PySide6 terminates the application on an
  unhandled exception in a slot, so anything reached from a timer or a signal must not
  raise. `urllib` only wraps failures raised while sending -- a socket timeout or a
  dropped connection while reading the response arrives as a bare `OSError`, and a
  malformed body turns `int(data.get("count"))` into a `TypeError`.
- **Modal dialogs on unattended paths.** A `QMessageBox` is fine for a button the
  user just pressed. On a timer path it blocks the desk until someone clicks it;
  report there through a status label instead.
- **Timer and debounce state that outlives its subject.** Loading a different backup,
  toggling a mode off, or a successful send must clear whatever was queued for the
  previous state, or the queued work runs against the new one.
- **Widget contents treated as user input.** A value the program wrote into a field
  (a per-group override, a computed time) must not be persisted as if the user had
  typed it. Track what was typed (`textEdited` fires only for real edits) when the two
  can diverge.
- **Side effects in a save path.** `_save_all_data` re-runs the duplicate check, which
  moves the selection in the photo list. Anything that saves on a delay must not
  drag the user's selection with it.
- **The backup file format is positional.** `load_backup` reads its optional tags in a
  fixed order, so a new tag goes last, after `ClientRevision`, and older backups must
  still parse. Add a round-trip test plus one for a backup written without the new tag.
