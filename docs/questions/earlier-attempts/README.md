---
type: question
tags: [earlier-attempts, library-core, tracking]
summary: "Map of every earlier sqlearn attempt: where it lives, how far its review has got, and what was left unread."
related: [docs/architecture/overview.md, docs/questions/fit-execution-model.md, docs/questions/multi-engine-support.md, docs/questions/scikit-learn-api-survey.md, docs/questions/validation-method.md]
---
# Earlier attempts

sqlearn was attempted several times before this repository. Each attempt is
read for what is worth keeping and what went wrong, so that the library core
(part 3.2 of [the overview](../../architecture/overview.md)) is designed with
those lessons. This page is the map: every attempt has a row, and a row is
finished when its status is **merged**. Overall progress, with the decisions,
spec and build that follow, is tracked in the GitHub issue
[#8, Library core (3.2)](https://github.com/glaucis/sqlearn/issues/8).

## Status

| Attempt | Source | Status | Review | Not read |
|---|---|---|---|---|
| `sqlearn_000` | GitHub `glaucis/sqlearn_000` | merged | [review](sqlearn_000/review.md) | `sqlearn-private`, which it quotes |
| sqlearn v0.4 | local `sqlearn-ecosystem_old/sqlearn` | merged | [review](sqlearn-v04/review.md), [exploration helpers](sqlearn-v04/exploration-helpers.md), [batch notes](sqlearn-v04/notes/) | two standards files; long plans read by heading; 139 test files skimmed |

Statuses: **to do** (known, not started), **mapped** (files listed and sorted
into batches), **read** (batch notes written), **merged** (review written,
committed, row complete).

## How an attempt is drained

1. **Map.** List every file with size and date; set aside generated folders
   (`.venv`, caches, build output, mutation copies). Note duplicates of an
   attempt already read. Add the row here as **mapped**.
2. **Batch.** Sort the files into batches by what they answer (design and
   decisions, core code, transformers, validation and tests, process, other).
   One agent per batch reads only, never runs anything in the source, and is
   told what earlier reviews already found, so it reports what is new or
   different.
3. **Notes.** Each batch writes cited notes and a checklist of every file it
   covered to `<attempt>/notes/`.
4. **Review.** The notes are merged into `<attempt>/review.md`. DuckDB claims
   are rechecked on the current DuckDB.
5. **Commit.** One commit per attempt; the row becomes **merged**.

When every row is merged, the reviews are combined into the core spec's
answers to the four open questions. Each question file and each review is then
deleted, following [the questions rule](../README.md); this map stays as the
record of what was read.
