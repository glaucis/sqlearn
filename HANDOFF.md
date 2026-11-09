# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-09 · Branch: `main` · Checks: passing ·
Verify with: `just verify`

## In progress

None.

## Waiting on the user

- Push `main` (the model-selection build, merged locally). Pushing closes
  #21 and #25 (their commits say `Closes`); then a summary on #33 and close
  it. (since 2026-11-09)
- Check the build's rulings, chiefly R8 (no LightGBM: needs `brew install
  libomp`), R11/R22 (a passed connection's DuckDB counts as at most half the
  budget; a warning when its limit is higher, which DuckDB's default is),
  R13 (an in-place UPDATE of a database table keeping its row count is not
  seen by `keep_prepared`), R21 (one-at-a-time searches keep only the current
  preparation's fold tables). (since 2026-11-08)
- File the final review's "can stay" minors as issues? (since 2026-11-08)
- #22 (OneHot as a list column): decide from the numbers in
  `docs/benchmarks/onehot-second-run.md`. (since 2026-11-06)

## Next up

- Ready for an agent: #28 compensated two-pass variance, then #27 (the
  median's reach); #32 (impute's filled copies typed INTEGER); #31 (the
  encoders' linear category lookup).

## Dead ends and traps

- `just test` does not run the Sphinx doctests, and an incremental docs build
  reuses stale generated pages: check docs with
  `rm -rf docs/reference/generated docs/_build && just build-docs`. (2026-11-06)
- A subagent that has handed back can still be running a background step
  while `ListAgents` shows it completed; check the agent panel and stop it
  with `TaskStop`. (2026-11-06)
- Wall-clock tests must warm up first, and set a limit between the normal
  time under load and the regression's, not just above the normal time.
  Never pipe `just test` through `tail` before `&&`: the pipe hides its
  failure. (2026-11-07)
- DuckDB 2.0: NaN sorts greatest, so `max` over a column with NaN is NaN
  (every aggregate filters missing values); a staged result read with
  `any_value` breaks inside another aggregate (plain column there); chained
  quantile stages spill only with the SQL shape of `b633816`. (2026-11-06)
- The git stash is shared by all worktrees: never a bare `git stash`. The
  CodeGraph index covers the main checkout, not the worktrees. (2026-11-06)

## Just finished

- The model-selection build (#33), fast-forwarded into `main` at `2fc0059`;
  worktree and branch removed. Build ledger with every ruling and deferred
  minor: `.superpowers/sdd/2026-11-07-library-model-selection/progress.md`
  (git-ignored). Spec
  `docs/specs/library-model-selection.md`, plan
  `docs/plans/2026-11-07-library-model-selection.md`, ADRs 0039-0041.
  (2026-11-08)
- Model-selection spec approved: `docs/specs/library-model-selection.md`,
  tracked in #33 (#21 and #25 its sub-issues). (2026-11-07)
- #30 closed out: ADRs 0037 (four step-contract additions) and 0038 (target
  encoder's inner folds by row position), the other rulings in a summary
  comment on #30; #26 closed by ADR 0035; #31 and #32 filed; #22, #27, #28
  detached from #30 to stand alone. (2026-11-07)
- Timing test warmed up and its limit raised to 10 s (1.6 s at load 40 against
  85 s when the basis is built; `just test` passes at load 56); merged
  worktrees `library-preprocessing` and `agent-af23…` removed, their branches
  deleted, the build ledger kept in `.superpowers/sdd/`. (2026-11-07)
- `CLAUDE.md` carries the global Handoff and "Skills and routine work" rules
  for web sessions; `main` pushed to `origin` (closes #29). (2026-11-07)
- The preprocessing build: spec `docs/specs/library-preprocessing.md`, plan
  `docs/plans/2026-11-06-library-preprocessing.md`, ADRs 0034–0036, 16 tasks
  each reviewed, final whole-branch review and fix wave; fast-forwarded into
  `main` at `7134303`. `just verify` passed from scratch on that tree (1035
  tests on Python 3.12/3.13/3.14). (2026-11-06)
- Triage of every open issue; hook fixes #1, #2, #3, #5 merged and closed;
  the core's #8, #17, #18 closed; tracker #30 opened. (2026-11-05)
