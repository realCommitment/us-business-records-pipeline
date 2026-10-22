---
description: Implement a spec in this fresh session, keep implementation notes, prove it against the running app, run /code-review, and leave one evidence-bearing commit
disable-model-invocation: true
---

The spec is `$ARGUMENTS`: a name like `01-auth` meaning `docs/specs/01-auth/spec.md`, or a path. Read it in full. If `docs/specs/00-product/spec.md` exists, read its architecture decisions and anti-goals too; they bind this work.

Implement that spec and while you do, keep a running `implementation-notes.md` next to the spec with decisions you had to make that weren't in the spec, things you had to change, tradeoffs you had to make, or anything else I should know.

Work rules:

- The spec is the scope. If finishing it needs something the spec does not cover, decide, write the decision into the notes, and keep going. If a decision would change the data model or what the user can do, stop and ask.
- Before you start, start the app and confirm the baseline works: use the recorded run skill under `.claude/skills/run-*/` if one exists, otherwise the Commands in `CLAUDE.md`. Fix a broken baseline before adding anything. If there is nothing to run yet (a new project), skip this step.
- When the tests pass, prove the spec against the running app yourself: start it, perform the spec's end-to-end verification step exactly as written, and capture the real output (response body, CLI output, screenshot). Tests and type checks alone do not count. If a project skill named `verify` exists, run it as well.
- Then run `/code-review` and fix the findings that affect correctness; list the ones you skipped and why in the implementation notes.
- Commit freely while working. Before you stop, squash this session's commits into one commit on the current branch. If `docs/specs/00-product/spec.md` has a `## Specs` line for this spec, tick its checkbox in that same commit. Change nothing else in the product spec.

The final commit message is how I review the work. Its body must contain, in this order: the spec path; a `Verified` list with every check you ran, the exact command, and its result (for test suites, passed and failed counts; for the end-to-end step, what you drove and what you saw); a `Not verified` list with what you could not check here and why; and the path of the implementation notes.

Never open a pull request and never push. I decide when the branch is a cohesive theme and run `/commit-push-pr` myself.
