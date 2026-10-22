---
allowed-tools: Bash(git checkout --branch:*), Bash(git add:*), Bash(git status:*), Bash(git push:*), Bash(git commit:*), Bash(git log:*), Bash(gh pr create:*)
description: Commit, push, and open a PR for the whole branch
---

## Context

- Current git status: !`git status`
- Current git diff (staged and unstaged changes): !`git diff HEAD`
- Current branch: !`git branch --show-current`
- Commits on this branch, with their evidence bodies: !`git log main..HEAD --format='--- %h %s%n%b'`

## Your task

Based on the above:
1. Create a new branch if on main
2. If there are uncommitted changes, create a single commit with an appropriate message
3. Push the branch to origin
4. Create a pull request using `gh pr create`. The PR body lists the specs this branch delivers, merges the `Verified` and `Not verified` sections from the commit bodies above into one list each, and links the implementation notes.
5. You have the capability to call multiple tools in a single response. You MUST do all of the above in a single message. Do not use any other tools or do anything else. Do not send any other text or messages besides these tool calls.
