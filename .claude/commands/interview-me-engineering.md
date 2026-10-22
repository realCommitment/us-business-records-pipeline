---
description: Create a spec folder from a name and one sentence, interview me until the spec is complete, write it
disable-model-invocation: true
---

Arguments: `$ARGUMENTS`. The first word is the spec name, like `01-auth`. Everything after it is my one-sentence idea.

Create `docs/specs/<name>/spec.md` containing that sentence if the file does not exist yet. If the first word is a path to an existing file, use that file instead.

Then read the spec file and interview me in detail, in prose, about literally anything. Be very in-depth and continue interviewing me until it's complete. Then write the spec to the file.

Rules for the interview:

- Ask in plain text, never with the AskUserQuestion tool: I answer by voice (`/voice`), which does not work inside that tool. You may list numbered options in the question; I will answer in prose.
- One question at a time. Ask first about anything that would change the architecture, the data model, or what is out of scope.
- Ask about the hard parts I might not have considered: failure modes, edge cases, what happens on the second run, what breaks when there is more than one user.
- Before writing, summarize the outline and ask me to confirm.

Two kinds of spec:

**Product spec**, when the name is `00-product`. This is the overarching plan for something big. Interview me about who the users are, what the product does and does not do, the architecture (stack, data model, tenancy, deployment), the riskiest unknowns, and what "version one" means. The finished file contains: goal; users and what they can do; anti-goals; architecture decisions, each with a one-line reason; and a `## Specs` section listing the feature specs to build, in order, one line each with a checkbox, named `01-<feature>`, `02-<feature>`, and so on. Each line is small enough for one implementation session and says what will be observable when it is done. The first spec is always the skeleton (app runs, one real test, lint, one end-to-end check). Ask me to confirm the list before writing. Do not interview about implementation details of individual specs; that happens when each one is written.

**Skeleton spec**, when the name is `00-skeleton`. Read `docs/skeleton-checklist.md` first. After settling the stack, walk the checklist item by item and decide adopt, adapt or skip for this project, asking me only where the stack does not make the answer obvious. The finished spec contains a `## Checklist decisions` section: one line per item, the decision, and the reason. Adopted items become acceptance criteria. Skipped items stay listed with the reason, so a later spec can pick them up.

**Feature spec**, any other name. If `docs/specs/00-product/spec.md` exists, read it first and keep the interview inside its decisions; if what I ask for contradicts the product spec, say so before continuing, and when I confirm, update the product spec too. The finished spec contains, in this order: the goal in one paragraph; what the user can do afterwards and the exact command or request that shows it working; anti-goals (what this spec deliberately does not do); the files and interfaces involved; and an end-to-end verification step that proves the feature works against the running app, not against unit tests alone.

Do not implement anything in this session. Tell me the spec path and that the next step is `/clear` then `/implement <name>`.
