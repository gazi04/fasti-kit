---
name: commit-style
description: Draft fasti-kit commit messages in this repo's existing gitmoji style (:bug:, :lock:, :zap:, :sparkles:, :recycle:, :art:, :fire:, :white_check_mark: — see git log) with an imperative-mood subject and a body that explains why, not a restatement of the diff. Keep commits small and atomic — one logical change per commit, don't bundle unrelated fixes. Only draft the message; never run git commit unless the user has explicitly asked to commit in this turn. Use whenever drafting or discussing a commit message or PR description.
---

# Commit style

## Never auto-commit

Drafting a commit message is not the same as committing. Write the message and show it; only run `git commit` when the user has explicitly asked for a commit in this turn, not because a message was requested or approved earlier.

## Format

This repo uses gitmoji + a short imperative subject, no scope prefix. Pick from what's already in the log (`git log --oneline`) rather than inventing a new convention:

- `:bug:` — bug fix
- `:sparkles:` — new feature
- `:lock:` — security-related change
- `:zap:` — performance improvement
- `:recycle:` — refactor
- `:art:` — formatting/structure with no behavior change
- `:fire:` — removing code/files
- `:white_check_mark:` — tests

Subject: imperative mood, no trailing period, states the change (e.g. `:bug: Fix login timing leak and non-atomic token revocation`).

Body (when the why isn't obvious from the subject alone): explain the reasoning — what was wrong and why this fix addresses it — not a line-by-line restatement of the diff. See recent commits (`git log -n 10`) for the target length and tone: a couple of sentences on the mechanism/motivation, occasionally a short bullet list when multiple unrelated-but-bundled fixes are in one commit (avoid this shape going forward — see atomicity below).

## Atomicity

One logical change per commit. Don't bundle an unrelated fix into a commit about something else, even a small one — split them, even if it means two commits instead of one. If asked to commit and the staged/pending changes span more than one logical change, say so and propose the split rather than writing one commit that covers both.

## Why

Confirmed preference: match this repo's existing gitmoji log rather than switching to plain Conventional Commits, and never run `git commit` without an explicit go-ahead in the current turn (a previously drafted/approved message doesn't carry standing permission to commit later).
