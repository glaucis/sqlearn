---
type: adr
tags: [api, warnings, opt-in, defaults, refusals, principles]
summary: "Records that sqlearn never changes on its own what the user asked for or the method a step uses: it keeps the default, raises a SqlearnWarning in the house form naming the better choice, and the user opts in; an explicit choice is never warned about."
related: [docs/adr/0003-scikit-learn-style-api.md, docs/adr/0019-custom-steps-and-failure-feedback.md, docs/adr/0032-the-median-is-exact-by-sorting.md, docs/adr/archived/0045-datasets-are-relations-built-in-sql.md]
---
# 0046: sqlearn warns, the user chooses

Status: accepted (2026-11-10). Decided with Tomas while ruling on the
library-breadth builds (#27, #31, #45, #47). Amended by
[ADR 0064](0064-the-gpu-runs-by-itself-only-when-the-answer-is-the-same.md)
(2026-11-21): on Apple silicon the GPU runs by itself when its answer is bit
for bit the CPU's.

## Context

Several builds met the same question: when sqlearn can see that another
setting or method would serve better, should it switch by itself? The cases:
a faster category lookup above a few thousand categories (#31), an
approximate median when the exact one runs out of memory (#27), an
impossible `n_informative` that scikit-learn quietly clips (#47). Switching
silently is convenient, and in #31 the results would even be identical. But a
user who cannot see what ran cannot trust it, reproduce it, or explain it.

## Decision

- **sqlearn never changes on its own what the user asked for**: not a
  setting, not the method a step uses, not the data a result is computed
  from, even when the result would be identical.
- **When a different choice would serve better, sqlearn keeps the default and
  raises a `SqlearnWarning`** in the house form (what happened, why, and a
  `Fix:` line naming the setting to pass). The user opts in.
- **An explicit choice is not warned about.** The warning is for a default
  the user did not choose; passing the setting, either value, silences it.
- **An impossible setting may be adjusted to the nearest possible one only
  with a warning** saying what was used instead (#47); otherwise it is
  refused in the house form.
- **When sqlearn must act to keep results correct**, it acts and says so: a
  table edited since it was prepared is prepared again, with a warning (#50).
- **A failure names the choices that would avoid it**: an exact median that
  runs out of memory says to give DuckDB more memory, use fewer threads, or
  pass `approx=True` (#27).

## Consequences

- New options are opt-in parameters with today's behaviour as the default:
  `lookup="hash"` (#31), `approx=True` (#27), `ordered=True` (#48).
- Where scikit-learn adjusts silently, sqlearn warns or refuses: a departure
  from [ADR 0003](0003-scikit-learn-style-api.md) that this record covers.
- Warnings must stay rare and worth acting on, or users learn to ignore them:
  each says what to do, and a repeated one is raised once per process or per
  configuration, not once per fold.
- The existing warnings already follow this: `sq.bin`'s adjusted bins, the
  memory limit of a passed connection (model selection R22), and
  `DefaultsUsedWarning` in `sq.search`.
