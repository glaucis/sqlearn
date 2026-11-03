---
type: note
tags: [process, workflow, retrospective, agents, sqlearn, v0.4]
summary: "Retrospective on the sqlearn v0.4 spec/plan/agent workflow, noting process-heavy planning, unticked plans, and standards worth keeping."
related: [docs/questions/earlier-attempts/sqlearn-v04/notes/E-process.md]
mdindex: [type=edb465, tags=c367c6, summary=8f6d04, related=709a27]
---
# E-process notes
OLD = "/Users/tomas/Desktop/Desktop - Tomas’s MacBook
Air/toosiaus_ducks_learnas/sqlearn-ecosystem_old/sqlearn" (paths below relative
to it). Depth caveat: I read READMEs, specs README, release summary, spec head,
agents/skills heads fully or in large part; the long numbered plans only by
headings, checkbox counts and heads (inference where stated).

## Summary
- Work was spec -> phase-file plans (gitignored `plans/`) -> agents executing,
  one atomic commit per task; v0.4 shipped 98 commits / 67 files / ~19.4k
  insertions in one day (OLD:docs/releases/2026-04-12-v0.4-summary.md:L40-47).
- The plan text far outweighs the product text per unit of work: v0.4 plans
  ~7.1k lines (+2.7k DESIGN-SPEC) for 11 phases; the "process" plan set is 5.0k
  lines of plan plus an 872-line spec for a docs-only change.
- A whole release-sized effort (spec + 8-phase plan, 10 new files, 8 commits)
  went into execution standards, a verification ledger, release summaries and
  "agent awareness" -- pure process, zero product
  (OLD:plans/2026-04-12-execution-workflow/README.md:L8-14).
- Plans were written as copy-paste: "exact content inline", full code blocks,
  "You do not need to invent anything"
  (OLD:plans/2026-04-12-v0.4-implementation/README.md:L113-122). Plans so
  detailed they are the implementation.
- No checkbox in any plan is ticked (2 of ~190); adherence is untrackable from
  the plans. Evidence of adherence is only the git history, and the release
  summary admits agent dispatch and per-phase commits "are not recorded"
  (summary L ~330).
- The v0.4 summary's own review checklist is 100% unticked and the review file
  never existed: "pending review". The review loop was designed but not run.
- Four near-identical agents (dev/compiler/tests/docs, all opus, effort max,
  maxTurns 30-80) plus a huge `coding-standards` skill; plan-awareness text was
  appended verbatim to all four (a copy, not a shared include).
- Strong content worth keeping: test-class template per component, comparison
  tests vs reference libs with dtype-matching and tolerance ladder, "format
  first then check", atomic commits, commit-protocol skill.
- Guard against: process-about-process plans, frozen-spec dogma that blocks
  fixing spec bugs, giant verbatim plans, release docs backfilled from git,
  "public-safety scrub" rituals, test-count vanity (~2700 target, 2934 reached).

## How work ran
- Flow: brainstormed design spec -> README + numbered phase files -> executor
  (README says `superpowers:executing-plans` for v0.4,
  `subagent-driven-development` recommended for the process plan) ->
  `just check` after each phase -> release summary + review brief
  (OLD:plans/2026-04-12-execution-workflow/README.md:L1-5;
  OLD:plans/2026-04-12-v0.4-implementation/README.md:L1-5).
- Specs "frozen during execution": spec bug => stop and escalate to user; never
  edit (OLD:docs/specs/README.md:L26-29;
  OLD:plans/2026-04-12-execution-workflow/README.md:L34-36). The v0.4 spec
  itself was a "grandfather case" kept inside the plan folder (gitignored), so
  it is not in history (OLD:docs/specs/README.md:L67-70). Summary even notes the
  spec "may no longer exist at review time" (summary checklist section 1).
- Plans are ephemeral/gitignored; "safe to delete after release"
  (OLD:docs/specs/README.md:L50-55). Consequence: the record of what was planned
  and what was executed is lost; a summary was reconstructed from git
  afterwards.
- Parallelism: plans give dependency graphs and "rounds" for subagent dispatch
  (OLD:plans/2026-04-12-v0.4-implementation/README.md "Parallelization hints").
  Whether followed is unrecorded (summary: "Subagent dispatch strategy ... not
  recorded in git history").
- "Questions you should NOT ask" FAQ lists in both READMEs pre-empt scope
  questions (e.g. no matplotlib, no method='auto').
- Permissions: settings.local.json just allows git, gh, uv run, just check,
  grep, wc (OLD:.claude/settings.local.json:L1-15). Plain.

## Plans: size, adherence, rework
- v0.4 plan (OLD:plans/2026-04-12-v0.4-implementation/): README 442 lines + 11
  phases of 327-1235 lines (largest 02-distribution 1235); 2 phase files each
  list 7-13 tasks; total ~7,100 lines of plan vs DESIGN-SPEC 2,719. Goal: 6
  primitives, orchestrator, explore/explain, 6 transformers, docs, benchmarks --
  "15 scoped items" in one day.
- Execution-workflow plan (OLD:plans/2026-04-12-execution-workflow/): README
  204 + 8 phases (261-1815; 01-standards-doc is 1815 lines to produce a
  ~640-line doc, i.e. the plan contains the doc verbatim, ~3x). Spec 872 lines,
  plus ~56 tasks, 8 commits, for docs-only change. Total ~5,000 lines of plan +
  872 spec to create ~10 markdown files (~1,100 lines) -- inference: ratio 5:1.
- Checkbox counts (ticked/unticked): execution-workflow 01: 2/45, 02: 0/9, 03:
  0/7, 04: 0/10, 05: 0/13, 06: 0/35, 07: 0/8, 08: 0/19; v0.4 01..11:
  0/7,8,7,7,8,10,8,11,11,8,13. Nobody ticked boxes; plans are not live trackers.
- Adherence signals (inference from summary): v0.4 shipped test count 2934 vs
  plan target "~2700" (OLD:plans/2026-04-12-v0.4-implementation/README.md
  acceptance) -- over target; summary lists scope slightly different from plan:
  `sq.explain()` "top-level export", `scipy`/`statsmodels` added as optional
  deps in pyproject (summary Config), while the plan said "No new heavy
  dependencies" and the process spec disallows pingouin. Files: transforms
  placed at `transforms/ratio.py`, `transforms/fill.py`, `string/stats.py`,
  `encoders/count_encode.py` whereas plan layout says `interaction/ratio.py`,
  `imputation/fill.py`, `encoders/count.py` -- divergence from plan layout
  (compare plan README L~100 vs summary). Test counts, dirs and a
  `tests/unit/helpers/test_analyze.py` appear; divergence is not documented
  ("deviations from spec" were to be reported but the summary lists none).
- Rework signs: 98 commits for what the plan sized as 8-12 per phase (~11 phases
  => ~90-130), so roughly on plan. Final commit `chore: sync uv.lock for v0.4.0`
  (summary L~42) hints a forgotten step. Summary says tag "not yet pushed".
  `tests/test_package.py` public-symbol count bumped by hand per feature
  (fragile coupling).
- Scope creep/process-over-product: the whole execution-workflow plan;
  verification ledger (`features/verification/` with 17-column CSV, TEMPLATE,
  INDEX, worked example Scale) for a library that at the time had none of its
  own comparison backfill; v0.4 summary lists 12 features that "should receive
  records in a future backfill". Plan 07 exists only to append the same ~10
  lines to 4 agent files. Plan 08 is CLAUDE.md + indexes only.
- Spec dated and planned the same day as v0.4 shipped (2026-04-12 for all of:
  v0.4 spec, plan, 98 commits, workflow spec, workflow plan, release summary).
  Process work was written while the product plan was "in flight" and had to
  promise not to touch it (README non-negotiable 3). Inference: process was a
  reaction to the v0.4 chaos (no record of agents/commits).

## Agents and skills
- `.claude/agents/`: sqlearn-dev (64 lines, full-stack, opus, effort max,
  maxTurns 80), sqlearn-compiler (78, maxTurns 40), sqlearn-tests (340, tests
  only, maxTurns 80; opens with a "doctors normalizing vitals / hospital"
  justification for precision), sqlearn-docs (83, docstrings, restricted tools,
  maxTurns 30). All load the `coding-standards` skill, permissionMode
  acceptEdits (OLD:.claude/agents/sqlearn-dev.md:L1-13). Terse report rule:
  "done, N tests pass" (sqlearn-dev L15).
- Overlap: dev already covers tests and docs, so tests/docs agents are partly
  redundant; tests agent's 340 lines mostly restates the skill (inference).
- Skills: `coding-standards` (425 lines + 3 reference files totalling ~660) and
  `commit-protocol` (196 lines). The SKILL says "No need to open reference files
  for normal work" yet carries references -- duplication. Agents forced to
  "MANDATORY first step: invoke the skill - read the FULL content" => large
  fixed context per dispatch (inference).
- Did they help? Evidence for: the v0.4 output has uniform test-class names
  (Construction/Contract/EdgeCases/Execution/Numerical/Compare) across all six
  transformers (summary "New test classes") -- the template was followed.
  Evidence against: primitives' classes differ (TestDataclasses etc.), plan
  layout diverged; no data on cost. Inference: standardisation helped
  consistency; weight of text likely hurt cost.
- Plan awareness section: `ls plans/` then read README (sqlearn-dev L40-55).
  Reasonable idea but trivially pushes workflow rules into every agent; a
  CLAUDE.md pointer would do.
- `scripts/new_transformer.py` (289 lines): scaffolds source + test stub +
  __init__ import for categories scalers/encoders/arithmetic/ops. Stale vs v0.4
  layout (datetime, string, interaction, imputation dirs not in
  VALID_CATEGORIES, OLD:scripts/new_transformer.py:L25) -- v0.4 transformers
  were apparently not made with it (inference).

## Standards worth keeping
- Verification order: `ruff format` -> `ruff check --fix` -> type check ->
  `pytest -x -q` (format first, never check-fail-fix)
  (OLD:.claude/skills/coding-standards/SKILL.md:L36-43).
- Every file: `from __future__ import annotations`, module docstring, full
  annotations, explicit `__all__`. (SKILL L47-54; new project is 3.12 so future
  import optional.)
- Test class template per unit: Construction / Contract / EdgeCases / Execution
  / Numerical / Compare; required edge cases (all nulls, single row, unicode
  names, zero variance); AAA; parametrize not loops; no logic in tests (SKILL
  L121-170; references/testing-standards.md L30-97).
- Comparison tests against reference libs with the same numpy dtype both sides,
  start tolerance tight (rtol 1e-14 float64), escalate via a ladder, document
  known DuckDB-vs-reference differences, multi-dtype (float32/64/int64) (SKILL
  L191-300). Strong match for the new project's SQL-vs-sklearn identity.
- Commit protocol: atomic, type priority, scope = domain not folder, banned
  verbs (update/improve/handle), effect not implementation, body WHY not diff,
  never invent ticket numbers
  (OLD:.claude/skills/commit-protocol/SKILL.md:L5-20). New project already has
  commitlint; take the "effect not code", banned vocabulary and scope-as-domain
  ideas; drop the "user is sole author" line since CLAUDE.md covers attribution.
- Tests and implementation in the same commit; one test-implement pair per
  commit (v0.4 README L~140).
- Release summary content (commit range, file list, test delta, divergences) was
  useful but only worth it if auto-generated at tag time, not hand-assembled.
- Non-negotiables as a short list in the plan README (no matplotlib, additive
  API, no auto features) is a good pattern if short.

## Guard against
- A plan whose subject is the workflow (execution standards, agent awareness,
  indexes). If process changes are needed, make them a few lines in
  CLAUDE.md/workflow.md, not a spec+8-phase plan with a 1,815-line phase.
- Plans that contain the deliverable text verbatim (plan 01 is ~3x the doc it
  produces). Plans should name outcomes and acceptance checks; let the
  implementer write.
- Plans that nobody updates (0 ticks in ~190). Either track in issues (the new
  project uses GitHub Issues) or do not use checkboxes.
- Gitignored plans/specs: the contract and the history vanish; release records
  then have to be reverse-engineered. Keep specs and plans committed (new
  project already does docs/specs and docs/plans).
- "Never edit the spec, escalate" rigidity: allow a dated amendment path; the
  grandfathered v0.4 spec shows the rule was already broken in practice.
- Divergence from plan layout going unrecorded (file locations, new optional
  deps scipy/statsmodels vs "no new heavy dependencies"). The new project's ADR
  0004/0005 rule on dependencies should be checked at review.
- Scope breadth per release: 15 items in a day; benchmarks, 9 guide chapters, 3
  notebooks in the same release as the code. Slice smaller; test count (2934)
  used as a success metric rewards volume.
- Agent proliferation: four opus/effort-max agents with overlapping remit and
  mandatory 700-line skill reads on each dispatch. Prefer one implementer
  prompt + the skills already available (tdd, verification).
- Review loop designed but never run (all review checklist boxes empty). Do
  reviews as part of the merge gate, not a later ceremony.
- Hand-maintained counts (public symbol count in tests/test_package.py and
  CLAUDE.md "test count" fields) drifting each commit.
- "Public-safety scrub" and "no roadmap language" rituals added per file (cost
  without product value; irrelevant given ADR 0006 only if repo stays private --
  inference).
- Stale scaffold scripts (new_transformer.py categories out of date): generate
  from the real layout or do not keep.

## Files covered
- [x] plans/2026-04-12-execution-workflow/README.md -- read fully; 8-phase
      docs-only plan, non-negotiables, FAQ
- [x] plans/2026-04-12-execution-workflow/01-standards-doc.md -- 1815 lines,
      head + checkbox counts (2/45); contains doc verbatim
- [x] plans/2026-04-12-execution-workflow/02-adr-009.md -- 414 lines, counts
      only (0/9); ADR for workflow
- [x] plans/2026-04-12-execution-workflow/03-specs-bootstrap.md -- 261 lines,
      counts only (0/7)
- [x] plans/2026-04-12-execution-workflow/04-verification-scaffold.md -- 547
      lines, counts (0/10); verification ledger scaffold
- [x] plans/2026-04-12-execution-workflow/05-scale-backfill.md -- 459 lines,
      headings (0/13); backfill Scale from PRECISION.md
- [x] plans/2026-04-12-execution-workflow/06-releases-backfill.md -- 660 lines,
      counts (0/35); release README+v0.4 summary
- [x] plans/2026-04-12-execution-workflow/07-agent-awareness.md -- 342 lines,
      head; append same section to 4 agents
- [x] plans/2026-04-12-execution-workflow/08-claude-and-indexes.md -- 499 lines,
      counts (0/19); CLAUDE.md + indexes
- [x] plans/2026-04-12-v0.4-implementation/README.md -- read fully; 11 phases,
      TDD mandatory, rounds
- [x] plans/2026-04-12-v0.4-implementation/01-framework.md -- 803 lines, head;
      base class, render, sample
- [x] plans/2026-04-12-v0.4-implementation/02-distribution.md -- 1235 lines,
      counts (0/8); largest phase
- [x] plans/2026-04-12-v0.4-implementation/03-missing-patterns.md -- 525 lines,
      counts only
- [x] plans/2026-04-12-v0.4-implementation/04-outliers.md -- 508 lines, counts
      only
- [x] plans/2026-04-12-v0.4-implementation/05-cardinality.md -- 327 lines,
      counts only
- [x] plans/2026-04-12-v0.4-implementation/06-normality-tests.md -- 743 lines,
      counts only
- [x] plans/2026-04-12-v0.4-implementation/07-target-analysis.md -- 397 lines,
      counts only
- [x] plans/2026-04-12-v0.4-implementation/08-orchestrator.md -- 498 lines,
      counts only
- [x] plans/2026-04-12-v0.4-implementation/09-explore.md -- 625 lines, counts
      only
- [x] plans/2026-04-12-v0.4-implementation/10-transformers.md -- 780 lines,
      counts only
- [x] plans/2026-04-12-v0.4-implementation/11-documentation.md -- 758 lines,
      counts only
- [x] (excluded per brief) plans/2026-04-12-v0.4-implementation/DESIGN-SPEC.md
- [x] docs/specs/README.md -- read fully; spec convention, frozen specs,
      grandfather case
- [x] docs/specs/2026-04-12-execution-workflow-design.md -- 872 lines; read
      sections 1-4 and outline
- [x] docs/releases/README.md -- read fully; summary+review convention, review
      never run
- [x] docs/releases/2026-04-12-v0.4-summary.md -- read fully; commit range,
      files, tests +607, unrun checklist
- [x] .claude/settings.local.json -- allow list only
- [x] .claude/agents/sqlearn-dev.md -- read most; full-stack, plan awareness
- [x] .claude/agents/sqlearn-compiler.md -- head; transformer/sqlglot agent
- [x] .claude/agents/sqlearn-tests.md -- 340 lines, head; test-only agent
- [x] .claude/agents/sqlearn-docs.md -- head; docstring agent
- [x] .claude/skills/coding-standards/SKILL.md -- outline + sections read
- [x] .claude/skills/coding-standards/references/python-standards.md -- not
      opened (outline-level only via SKILL); 227 lines
- [x] .claude/skills/coding-standards/references/testing-standards.md --
      headings read
- [x] .claude/skills/coding-standards/references/documentation-standards.md --
      not opened; 134 lines
- [x] .claude/skills/commit-protocol/SKILL.md -- read fully
- [x] scripts/new_transformer.py -- head read; stale categories
