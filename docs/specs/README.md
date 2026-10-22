# Specs

`00-product/spec.md`, when the build is big: goal, users, anti-goals, architecture decisions, and the ordered `## Specs` list with one checkbox per feature spec. Written by `/interview-me-engineering 00-product …`, ticked by `/implement`, changed only through another interview or by hand.

One folder per feature spec, numbered in the order you build them: `docs/specs/<nn>-<feature>/spec.md`, plus `implementation-notes.md` written by the implementing session.

Start a spec with one sentence, then run `/interview-me-engineering docs/specs/<nn>-<feature>/spec.md`. Status is git: a spec is done when its commit is on the theme branch, and shipped when the branch is merged. Delete or archive the folder when the code is the better source of truth.
