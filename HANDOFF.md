# Handoff

Current state of work, maintained by `/handoff`. Git history keeps earlier
versions.

Updated: 2026-11-07 · Branch: `main` · Last commit:
`7134303 test: record the outcomes of the review's new tests` · Checks: failing
(one timing test, under machine load) Verify with: `just verify`

## In progress

- [verified] Flaky timing test on `main`:
  `tests/src/sqlearn/preprocessing/test_features.py::test_a_wide_spline_learns_fast_when_nothing_reads_it_in_the_run`
  failed in `just test` at load average 13 and passes alone 3/3. It times the
  session's first learn (DuckDB start-up included). Next step: one warm-up learn
  before the timer, as the quantile timing tests in
  `tests/src/sqlearn/test__compose.py` do; then `just test`.
- [verified] Clean-up after the merge, held until the test above is fixed:
  - worktree `.claude/worktrees/library-preprocessing` and branch
    `library-preprocessing` (merged, at `7134303`);
  - its git-ignored build ledger
    `.claude/worktrees/library-preprocessing/.superpowers/sdd/2026-11-06-library-preprocessing/progress.md`
    holds every build ruling and deferred finding: copy it to the main
    checkout's `.superpowers/sdd/` before `git worktree remove`, then
    `git branch -d library-preprocessing`;
  - stale locked worktree `.claude/worktrees/agent-af23cf1a2340d2f71`
    (branch merged earlier at `18b13dd`): `git worktree unlock`, remove,
    delete its branch.

## Waiting on the user

- Harden the timing test, then clean up as above? (since 2026-11-06)
- Push `main` (51 commits ahead of `origin/main`). Pushing closes #29 (its
  commit says `Closes #29`). (since 2026-11-06)
- Where to record the build's rulings (listed in the last session's final
  message and in the ledger). User-visible ones: target encoder's inner folds
  by row position (T10a); text targets refused (T10b); column-order
  differences from scikit-learn for the indicator, the polynomial bias and
  OneHot's missing category (T6a, T13b, T5b); scale's "default" sentinel
  (T7a); `sq.Learned`/`sq.Output` kept at the top level (F5); step-contract
  additions (label pairs, `apply_row` row values, `Step.learned`,
  `keeps_inputs`). Options: ADRs, or a summary comment on #30.
  Recommendation: ADRs for the contract additions and T10a, the rest in #30.
  (since 2026-11-06)
- #22 (OneHot as a list column): decide from the numbers in
  `docs/benchmarks/onehot-second-run.md`. (since 2026-11-06)
- Two issues to file: the encoders' linear `list_position` category lookup
  (slow past ~1,000 categories; Ruling F6), and impute with `keep=True` +
  `indicator=True` + a fill value declaring the filled copies INTEGER.
  (since 2026-11-06)

## Next up

- Close out #30: summary comment, close #26 and #30 (and #29 after the push),
  move `CLAUDE.md`'s "Next" line (it still says the plan is being built) to
  the next 3.3 area. Model selection is the natural one: it owns #21, #25
  and grouping `Grid`/`KFold`/`range`/`Model`.
- #28 compensated two-pass variance (ready for an agent), then #27 (measure
  the median's reach; ready for an agent).

## Dead ends and traps

- `just test` does not run the Sphinx doctests, and an incremental docs build
  reuses stale generated pages: check docs with
  `rm -rf docs/reference/generated docs/_build && just build-docs`. (2026-11-06)
- A subagent that has handed back can still be running a background step
  while `ListAgents` shows it completed; check the agent panel and stop it
  with `TaskStop`. (2026-11-06)
- Wall-clock tests must warm up first; the first learn pays DuckDB's start-up
  and fails under load. (2026-11-07)
- DuckDB 2.0: NaN sorts greatest, so `max` over a column with NaN is NaN
  (every aggregate filters missing values); a staged result read with
  `any_value` breaks inside another aggregate (plain column there); chained
  quantile stages spill only with the SQL shape of `b633816`. (2026-11-06)
- The git stash is shared by all worktrees: never a bare `git stash`. The
  CodeGraph index covers the main checkout, not the worktrees. (2026-11-06)

## Just finished

- The preprocessing build: spec `docs/specs/library-preprocessing.md`, plan
  `docs/plans/2026-11-06-library-preprocessing.md`, ADRs 0034–0036, 16 tasks
  each reviewed, final whole-branch review and fix wave; fast-forwarded into
  `main` at `7134303`. `just verify` passed from scratch on that tree (1035
  tests on Python 3.12/3.13/3.14). (2026-11-06)
- Triage of every open issue; hook fixes #1, #2, #3, #5 merged and closed;
  the core's #8, #17, #18 closed; tracker #30 opened. (2026-11-05)
