---
type: note
tags: [process, sql-learn, tests-first, agents, workflow, retrospective]
summary: "Batch B process review of the sql_learn_test attempt: orchestrator-and-subagent roles, TODO queue, 11-step tests-first pipeline, and which rules to keep or drop"
related: [docs/questions/archived/earlier-attempts/sql_learn_test/notes/B-process.md]
mdindex: [type=edb465, tags=322d2c, summary=9ef961, related=e102a8]
---
# sql_learn_test, batch B: process

Source (read only): OLD =
`/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/toosiaus_ducks_learnas/sql_learn_test`.
Paths below are relative to OLD. Line numbers are the file's own. Inference is
marked "(inference)". The git log is cited by sha.

## Summary

- The restart put the war room's lesson "process outgrew the product" to the
  test and failed it again: in 59 commits over four days there is no library
  code, only a scaffold (`f6b90ee`), two lint bans (`f7529d5`, `8383109`) and
  two shell/Python gates. 31 of 59 commits are `chore`, 15 mention `TODO`.
- Its organising idea: one orchestrator (the main session) owns a hand-kept
  `TODO.md` queue; eight read-mostly subagents each return one line pointing
  at a report file; a fixed 11-step pipeline (intake, plan, plan review, tests,
  test review, code, suite, honesty gate, diff review, fix loop, harden).
- The main change from the war room is mechanical enforcement: a before/after
  hash gate on the test suite and config, a runtime import tripwire, `ruff`
  bans with the replacement in the message. It reacted to "a deterministic
  checker beat agent reviewers" and to "docs with hand-typed numbers were
  wrong" (rules cite primary URLs and measure claims).
- It did not react to "status kept by hand in several places drifts": `TODO.md`
  is by-hand status, made mandatory to the point of capturing every question
  before it is asked (`BRIEFING.md:20-79`). Its own review sweeps still found
  contradictions (`3ae16fe`, `342a907`, `a2a7cd3`).
- Tests-first with a blind test author, a live scikit-learn call as the only
  independent oracle, a frozen test set and a two-round fix cap are the ideas
  worth carrying over. The pipeline "has never run end to end"
  (`rules/coding-workflow.md:519-522`); every cost in it is predicted.
- The oracle is still one estimator slice against scikit-learn, not a whole
  pipeline, so the baseline's "no attempt compared a whole pipeline" stands.
- It stopped after 24 August with the next attempt on 26 August (the README
  maps `sql_learn_27.08.2026`). No log message says why; the evidence points
  to a research-and-rules phase with nothing yet built to run (inference).
- Several rule and agent files cite files that are not in OLD's process
  folders (`.claude/playbooks/debugging.md`,
  `.claude/agent-roster/SOURCES.yaml`,
  `WORKFLOWS.md`): the restructure left dangling references.

## How work ran

**Roles.** One orchestrator, the main session, injected at start by a
`SessionStart` hook that prints `BRIEFING.md` plus live counts of open `TODO.md`
rows and unread reports (`.claude/settings.json:8-19`;
`.claude/orchestrator/hooks/session-start.sh:27-91`). Subagents never see the
briefing, by construction: the hook does not fire for them and it keeps
main-session rules out of `CLAUDE.md`, which every subagent loads
(`session-start.sh:2-7`). Eight agent definitions, none able to dispatch (no
Task tool in `tools:`): `planner`, `coder`, `executor`, `reviewer`,
`test-author`, `rules`, `finder` and the meta-role `roster-auditor`
(`BRIEFING.md:107-115`). Models: opus for all, effort `max` for planner, coder,
test-author, reviewer and roster-auditor; `xhigh` for rules; `high` for finder
and executor (front matter of each file).

**Queue.** `TODO.md` is the work queue and the orchestrator is its only writer.
Read before substantive work; write "the moment something surfaces ... before
the next tool call, message, or question" (`BRIEFING.md:7-18`). The capture rule
grew over four commits on 21 August (`dbe7c7b`, `67ebd0a`, `794ffab`,
`605cd6c`) from guidance to "a MUST - no exceptions, no permission, no delay"
(`BRIEFING.md:20`). It covers questions about to be asked, answers received
but not built, and things noticed in passing (`BRIEFING.md:30-42`). Rows are
deleted only after verifying the thing is true now (`BRIEFING.md:14-15`).

**Reports.** Each agent returns exactly one line (`ok:`, `issue:`, `failed:`
plus a path in `.claude/reports/`, or `blocked: <question>`) and writes its
findings to a report named `<utc>-<agent>-<slug>-<pid>.md` that the
orchestrator assigns (`BRIEFING.md:81-103,150-162`; `rules/naming.md:36-47`).
Triage is by front matter (`status`, `needs_todo`); `## Noticed, not acted on`
is "the highest-yield section" (`BRIEFING.md:92-94`). Extract, then delete
(`BRIEFING.md:95-97`). Briefs may not ask for inline answers
(`BRIEFING.md:119-126`).

**Pipeline** (`rules/coding-workflow.md:20-300`), each step a fresh dispatch
passing a path, never the conversation:

0. Intake block written by the orchestrator (oracle, observable, tolerance with
   reason, non-goals). Block on anything a test will fossilise; assume-and-flag
   what parity would catch (`:74-91`).
1. `planner` writes the plan with a Contract section and a separate Build
   notes section, and names one executor: `coder` if any step writes Python
   under `src/`, else `executor`; arguable goes to `coder` (`:93-121`).
2. Plan review: "can this be executed from this file alone?" Two rounds, then
   Tomas. Called "the highest-value step" (`:128-135`).
3. `test-author` writes tests from the contract and a live scikit-learn call,
   never reading `src/`; values in priority order: live oracle, metamorphic
   relation, hand-written with origin (`:137-166`). Proven red (`:163`).
4. Review of the tests before any implementation exists (`:168-175`).
5. `coder` reads plan and tests read-only, may run `pytest`, may not write
   under `tests/`. The orchestrator wraps every coder dispatch in
   `tools/gate-tests-frozen.sh snapshot` / `verify` (`:177-209`).
6. The orchestrator runs the suite, not the coder's claim (`:211-212`).
7. Honesty gate `tools/gate-sql-data-path.py` (`:214-232`).
8. `reviewer` gets plan and diff only; asks "does it match the plan, does it
   honour the SQL data path", not "does it work" (`:234-239`).
9. Fix loop, cap two rounds, escalate sooner if the same failure repeats, back
   to `planner` with a fresh context (`:241-256`).
10. Harden on a green suite: metamorphic and generative parity by the
    test-author, mutants applied and run with `PYTHONPATH` set, surviving
    mutants go to the test-author, implementation frozen (`:262-297`).
11. Tomas reads the diff and commits (`:299-300`).

**Rules corpus.** `rules/*.md`, flat, with `id`, `keywords`, `applies_to`,
`enforced_by`, `status`; required sections "What to do", "Rationale including
what was rejected", "Consequences" (`rules/README.md:43-87`). Found by
coverage (grep `applies_to` per domain) then keyword lookup
(`rules/README.md:10-41`). Changing a rule is an edit; `git log -p` is the
decision log (`rules/README.md:100-106`), replacing `DECISIONS.md`
(`a40e633`).

**Evidence of use.** A "probe" dispatch on 21 August (`741e865`, `de3c6d0`)
found the report-discipline and `setseed()` traps (`BRIEFING.md:87-91,119-124`).
The tests-first pipeline was designed from six research agents on 23 August
(`5216386`) and 34 reports plus 17 syntheses on 24 August (`5bdfd48`), then
reviewed (`3ae16fe`). It was never run on a real estimator (inference from
`rules/coding-workflow.md:519-522` and from no `feat` commit touching
`src/`).

## Rules

One line each: rule, keep or drop, why.

- `rules/README.md` coverage by `applies_to` domain, then keywords: keep the
  idea, with the repo's own docs index (`qmd`) doing the lookup. The flat-corpus
  reason (`globstar` misses top-level) is sound for grep, moot with the index.
- `rules/README.md` "Rationale including what was rejected" mandatory: keep.
  It stops a later session "improving" a rule that was already refused. Fits
  our ADRs.
- `rules/README.md` `enforced_by` names a test, or says `prose`: keep. Honest
  about what is a request and what a constraint (`:89-98`).
- `rules/README.md` change a rule by editing it, git as the log: drop. We use
  ADRs; reversing a rule needs a new ADR (ADR 0003 precedent).
- `rules/naming.md` Python `snake_case`, everything else kebab: drop. It
  contradicts nothing but we have ADR 0010 for naming; the report filename
  `<utc>-<agent>-<slug>-<pid>` format (no colons, `$$` built in the top-level
  shell) is a small useful trick, keep that detail only.
- `rules/naming.md` rule `id` equals filename, checked by a one-line loop: keep
  if we adopt rule files; the checker belongs in `just check`.
- `rules/code-style.md` three tiers by how a rule is checked (mechanical,
  reviewable, explained-never-instructed): keep. Its argument that an
  unverifiable instruction yields the appearance of the property is the best
  sentence in the repo (`:12-15`).
- `rules/code-style.md` ban numpy/pandas/sklearn from `src/` via `TID251`
  with replacement in the message: keep. Matches ADR 0002 and 0004.
- `rules/code-style.md` all SQL behind one choke-point module; values bound,
  identifiers through one quoting helper; no `SELECT *`; explicit `ORDER BY`
  for any observed order: keep as library-core input (decide in the spec).
- `rules/code-style.md` every estimator carries NULL, NaN, empty-relation and
  single-row fixtures: keep. Closes the baseline's NaN gap.
- `rules/code-style.md` "no logic or validation in `__init__`": keep (ADR 0003).
- `rules/code-style.md` rejected: full-word names, assertion density, comment
  density, complexity limits, coverage floor, strict DRY: keep as "do not write
  these rules"; each cites a primary source (`:97-148`, not re-verified).
- `rules/code-style.md` float aggregation is not reproducible across thread
  counts, `fsum` included; pin `threads=1` when reproducing (`:178-194`): keep
  as a fact to recheck on current DuckDB before use.
- `rules/coding-workflow.md` tests before code so the test author's blindness
  is structural: keep, with the reason (exposure, not test-first as such,
  `:339-359`).
- `rules/coding-workflow.md` expected values from a live oracle call first,
  metamorphic second, hand-written with stated origin last: keep.
- `rules/coding-workflow.md` parity fixtures small, a convention error shrinks
  with n (`ddof`: 15% at n=4, 5e-6 at n=100000, `:158-161`): keep; matches the
  size rule from `sqlearn_000` in a sharper form.
- `rules/coding-workflow.md` tolerance fixed in the plan with its reason, never
  widened to pass: keep (`:258-260`, `:560-566`).
- `rules/coding-workflow.md` gate on the frozen set must be before/after
  hashing, not post-hoc `git status`, and the set includes `pyproject.toml`,
  `pytest.ini`, `uv.lock`, gate scripts: keep the idea; our pre-commit hook
  and `just` make the snapshot simpler (inference).
- `rules/coding-workflow.md` plan review as the highest-value step, because the
  plan is the common-mode failure (`:132-135`, `:547-550`): keep.
- `rules/coding-workflow.md` reviewer sees plan and diff only, no `Edit` tool,
  asks "matches the plan?" not "works?": keep.
- `rules/coding-workflow.md` fix loop capped at two rounds, escalate on the
  same failure twice, fresh context: keep; note its own admitted hole, "same
  failure" is undefined (`:482-486`).
- `rules/coding-workflow.md` mutation hardening as a periodic audit, never a
  rate; `PYTHONPATH` must point at the mutated copy or no mutant runs
  (`:266-282`): keep the trap, defer the practice.
- `rules/coding-workflow.md` no coverage or mutation-score floor (`:488-501`):
  keep.
- `rules/coding-workflow.md` steps may not be collapsed to save dispatches
  (`:543-545`): drop as a hard rule. Our workflow.md allows small work on
  `main` by one agent; the 11-step ritual for one slice is the process cost
  the baseline warns of.
- `rules/coding-workflow.md` pin scikit-learn and duckdb exactly in
  `pyproject.toml` (`:552-558`, commit `a533d7c`): keep for the oracle
  (dev dependency only; ADR 0004 concerns runtime).
- `rules/debugging-workflow.md` reproduce twice with `threads=1` and a pinned
  seed before any fix; diagnosis and fix are separate dispatches; regression
  test by someone other than the fixer; stop after two failed attempts
  (`:21-46,106-120`): keep reproduce-twice and stop-at-two; drop the
  separate-dispatch ceremony.
- `rules/docstrings.md` docstrings written with the code and verified
  structurally against scikit-learn (every parameter documented and nothing
  documented that is not accepted; attributes end with `_`), plus a gate that
  must not be vacuous (`:10-34,121-131`): keep. Adapting scikit-learn text is a
  BSD-3 licensing act and the repo had no `LICENSE` (`:133-138`): keep as a
  guard.
- `rules/docstrings.md` select `D417` explicitly because `select=["D"]` under a
  convention drops it (`:81-95`): keep, recheck on current ruff.
- `rules/docstrings.md` rejected `assert_docstring_consistency` because it
  passes by skipping (`:102-108`): keep as a lesson on gates that pass
  vacuously.
- `BRIEFING.md` capture everything into `TODO.md` before the next tool call:
  drop as written. The principle (nothing lives only in chat) is right; the
  mandatory by-hand file is the status drift the baseline names. Use GitHub
  Issues (ADR/workflow.md) and let a checker count them.
- `BRIEFING.md` never infer an agent's state from its transcript file; a
  newly written agent is not dispatchable until restart, `/clear` does not
  re-read the roster (`:164-183`): keep as environment facts to recheck.
- `BRIEFING.md` never brief coder and test-author in one dispatch (`:142-148`):
  keep with the reasons (knowledge separation, tree contention).
- `.claude/agents/*` one-line return pointing at a report file: drop for us.
  Subagent-driven development already returns a summary; report files
  multiply status files (baseline: status in several places drifts).
- `.claude/agents/coder.md` list of holes past the linter (`duckdb.sql().df()`,
  `.fetchdf()`, `.to_df()`, `.fetchnumpy()`, `.arrow()`, `.pl()`,
  `importlib.import_module`, `# noqa: TID251`, transitive `scipy`): keep
  verbatim as the lint config checklist.
- `.claude/agents/planner.md` "propose, never decide" and the options memo that
  returns `blocked:`; "no placeholders" list; write the SQL out where a
  scikit-learn prior would fill the gap (`:35-39,183-206`): keep.
- `.claude/agents/planner.md` self-review: coverage, placeholders, interface
  consistency, verifiability (`:214-228`): keep.
- `.claude/agents/executor.md` evidence before claims; six ways of skipping
  verification, including "wrong-check" (`pytest` after a docs edit) (`:48-76`):
  keep (superpowers verification-before-completion covers it).
- `.claude/agents/test-author.md` write tests a plausible-wrong implementation
  fails: materialises, assumes row order, mishandles NULL, only float64, only
  data that fits memory (`:52-64`): keep as the test checklist.
- `.claude/agents/rules.md` single reader of `rules/` that quotes verbatim or
  says "no rule covers this" and names what it searched: drop the agent; the
  docs index does it. Keep "say what you searched".
- `.claude/agents/finder.md` returns locations only, never content: drop;
  CodeGraph does this.
- `.claude/agents/roster-auditor.md` audit one agent file for internal
  consistency and unnamed failure modes: drop; a roster this size is the
  problem.
- `tools/gate-tests-frozen.sh`: keep as a design (hash path list as well as
  contents so create or delete changes the digest, `:33-41`).
- `tools/gate-sql-data-path.py`: keep as a design: a `sys.meta_path` observer
  that records import attempts even when the module is absent, exercises
  estimators rather than importing the package, prints `armed`/`INACTIVE`, and
  has a `--self-test` (`:11-20,86-109`). One flaw: with no estimators it only
  notes "import-only coverage" (`:53`) and passes (inference: vacuous until
  code exists).
- `.claude/settings.json` empty `attribution` and `includeCoAuthoredBy: false`
  (`:2-7`): already ours.

## History

59 commits, 21 to 24 August 2026
(`/private/tmp/.../sql_learn_test-git-log.txt`).
Per day: 39, 5, 15. None on 22 August.

- **A. Orchestration, 21 August, `0a6da18`..`c54c8ef` (39 commits).** Work
  queue (`0a6da18`), report template (`5d5387d`), orchestrator hook
  (`598b176`), `CLAUDE.md` with authorship rule (`91d9b3e`), DEC-001 "X is a SQL
  relation, not an array" (`24eb307`), package scaffold (`f6b90ee`),
  `DECISIONS.md`
  replaced by a rules folder (`a40e633`, `0133ac2`), import ban lint
  (`f7529d5`). Then the agent layer: probe findings (`526c155`..`de3c6d0`),
  five-role roster (`16d3c1a`), dispatch contract (`0e015dd`), executor,
  reviewer and plan pipeline (`5a217bc`), the `/clear` trap (`0f7fd51`), roster
  audit (`86e2a86`), test-ordering research (`517c511`), docs restructure
  (`6d60b2a`), capture rule hardened (`dbe7c7b`..`794ffab`). Rework in this
  phase: the commit agent queued then superseded (`68ac4db`), agent-roster
  rule row added then dropped (`f7edf91`, `adeb5e1`), "rules.md founding-claim
  fix" queued (`c3e1ac1`), return-contract drift across dispatches recorded
  (`777d6c5`).
- **B. Research fan-out, 23 August, `5216386`..`b0d9e2e` (5 commits).** Six
  agents on pipeline design (`5216386`), the coding pipeline moved from
  `WORKFLOWS.md` to `rules/coding.md` (`8eda729`), findings captured and eleven
  rows drained (`7ce35f5`), why writers stay serialised and agents do not
  communicate (`b0d9e2e`).
- **C. Rules and gates, 24 August, `5bdfd48`..`b421d8f` (15 commits).** 34
  research reports, 17 syntheses and 3 review reports in one commit
  (`5bdfd48`); the two gates (`f2563e4`); pipeline and naming rule (`915cf16`);
  `code-style` restored, `debugging-workflow` given front matter,
  `sql-data-path` rule dropped (`00182f5`); "the data loss" and review findings
  recorded in `TODO.md` (`55df55a`); `BLE`, `S110`, `S112`, `ARG` enabled
  (`8383109`); contradictions found by review fixed in H4 to H7 (`3ae16fe`);
  agent step 4 given an owner, plan template and delivery claim corrected
  (`342a907`); exact pins for scikit-learn and duckdb (`a533d7c`); H1 to H7 and
  D4 marked fixed (`a2a7cd3`); `fsum` claim tightened to what measurements
  support (`e2e27d2`); docstring rule and its gate (`ec0b3fb`); last commit
  records the docstring rule, the `D417` correction and the licence gap
  (`b421d8f`).

**Rework seen.** The rules folder was rebuilt at least three times in one
day (`a40e633` from `DECISIONS.md`; `6d60b2a` split rules from architecture and
moved workflows out; `8eda729` moved the pipeline into `rules/coding.md`;
`915cf16` and `00182f5` again, with `code-style.md` deleted then "restored").
The same pipeline was rewritten tests-after-code to tests-first
(`rules/coding-workflow.md:333-337`: the earlier sequence was "deleted
2026-08-24", recoverable with `git log -p -- rules/`).

**Why it stopped (inference).** No commit or document states a reason. The log
ends on a rules commit with a deferred licence gap (`b421d8f`). The pipeline
had run on no real estimator, the library had `__init__.py` and `py.typed`
(`rules/coding-workflow.md:519-522`), and a restart began two days later
(README row `sql_learn_27.08.2026`, 26 August). Like the war room, the
effort ran out in the layer above the product.

## New against the baseline

- A **frozen-set hash gate** around every code dispatch: the first deterministic
  anti-cheating control in any attempt, with the demonstrated evasions
  (`addopts --deselect`; a root `pytest.ini` that pytest prefers over
  `pyproject.toml`) and the rule that the check must be before/after because
  nothing commits mid-pipeline (`rules/coding-workflow.md:191-209`;
  `tools/gate-tests-frozen.sh:17-30`).
- A **runtime import tripwire** that closes what the linter cannot see
  (`importlib.import_module`, `duckdb.sql(...).df()`) and shows `INACTIVE` when
  a banned module is absent (`tools/gate-sql-data-path.py:11-20,86-90`).
- **Tests-first with a blind test author**, and the argument that the live
  scikit-learn call is the only oracle nobody in the loop authored; blinding
  filters slips, not shared misconceptions (`rules/coding-workflow.md:361-384`).
- A **rule on a gate that passes vacuously**: `test_the_gate_is_not_vacuous`
  (`rules/docstrings.md:123-127`) and `assert_docstring_consistency` rejected
  for passing by skipping (`:102-108`).
- **`threads=1` for reproduction**: DuckDB float aggregates (`sum`, `fsum`,
  `favg`) return several values across thread counts at n=1e6, `fsum` more
  accurate but not stable (`rules/code-style.md:178-194`;
  `rules/debugging-workflow.md:24-31`). No earlier attempt recorded this.
- **Tool-environment facts**: `/clear` does not re-read the agent roster;
  `setseed()` never runs through lazy `duckdb.sql(...)`; a transcript file's
  size is no signal of liveness (`BRIEFING.md:87-91,164-183`).
- **Ruff measurement**: `select=["D"]` under a convention silently drops
  `D417` (`rules/docstrings.md:81-95`); `BLE,S110,S112,ARG` take a probe file
  from 1 error to 8 (`rules/code-style.md:203-209`).
- **Pin the oracle and the engine exactly** (`==`) so the specification cannot
  move under a green suite (`rules/coding-workflow.md:552-558`, `a533d7c`).
- **Routing by a single test** (does any step write Python under `src/`?) with
  "arguable goes to the constrained agent" (`rules/coding-workflow.md:108-121`).
- **Small parity fixtures, with numbers**: `ddof` error 15% at n=4, 5e-6 at
  n=100000 (`rules/coding-workflow.md:158-161`).
- **Licence guard**: adapting scikit-learn docstrings creates a BSD-3 notice
  obligation (`rules/docstrings.md:133-138`).
- **Literature-backed rules with primary URLs**, each flagged "none re-verified"
  (`rules/coding-workflow.md:516-518`). New in kind; the figures are unchecked.

## Contradicts the baseline

- Baseline: "A deterministic checker stopped document drift where agent
  reviewers had not." OLD builds two checkers for code behaviour but none for
  its docs: rules, agents, `BRIEFING.md` and `TODO.md` stay prose, and it
  needed repeated agent review rounds to find contradictions (`3ae16fe`,
  `342a907`). The checkable `id`/filename loop is left manual
  (`rules/naming.md:94-97,101-102`). So its evidence for the baseline is
  partial: it confirmed the need and again did not build the checker.
- Baseline: "A separate review sweep after a burst found real bugs every time."
  Confirmed, but OLD's sweep also found its own sweeps' sources wrong: the
  `D417` research claim was reversed by measurement
  (`rules/docstrings.md:93-95`).
  Not a contradiction of the finding; a limit on trusting research reports.
- Baseline: validation tolerance was "fixed" and "hand-tuned". OLD fixes
  tolerance in the plan with a reason and forbids widening it, so it
  contradicts "loosened to hide known mismatches" as a practice, though only on
  paper (never run).
- Baseline treats agent reviewers as the weak control. OLD says the same
  (reviewer false-alarm rate 75 to 98%, `rules/coding-workflow.md:388-391`) but
  still keeps three review stages (2, 4, 8); its answer is to narrow the
  question, not to drop them.

## Confirms the baseline

- **Process outgrew the product.** Four days, 59 commits, no estimator. The
  rules and agent layer is about 147 KB across the 19 files read here, against
  a package with `__init__.py` and `py.typed`.
- **Bursts then stall**: 39, 5 (a day between), 15 commits, then nothing.
- **Status by hand drifts.** `TODO.md` is the status; `BRIEFING.md` needs
  four commits to make capture mandatory; "the data loss" of 24 August is
  recorded (`55df55a`) without detail in the log (inference: a lost session or
  file).
- **Docs with hand-typed numbers were wrong.** The `D417` table
  (`rules/docstrings.md:85-95`), the `fsum` claim tightened (`e2e27d2`), "55
  hyphenated names against 2" (`rules/naming.md:71-75`) all dated facts. The
  research figures are explicitly unverified (`rules/coding-workflow.md:516`).
- **Scope swung by conversation.** The pipeline order was reversed in a day
  (`rules/coding-workflow.md:333-337`); the rule folder was rebuilt several
  times.
- **The fit defect remained invisible.** No document here mentions a learning
  step reading an earlier step's output; the unit of work is "one estimator's
  public surface, one named scikit-learn comparison"
  (`rules/coding-workflow.md:12-15`). A per-estimator oracle cannot catch
  `Impute` then `Scale`.
- **sklearn as the reference** with exact pins, no whole-pipeline parity.
- **The `y` column and fit-takes-a-source departures**: `coder.md:20-22` says
  `fit(X, y)` takes "a DuckDB relation, a table name, a Parquet path", and
  nothing mentions excluding the target from default columns.
- **Test hygiene already in the baseline**: tests that fail when missing,
  skipped parity; here the gate-is-not-vacuous test.

## Worth keeping

1. The three-tier rule classification and the sentence that an unverifiable
   instruction produces its appearance (`rules/code-style.md:12-15`).
2. The frozen-test-set gate design and its seven demonstrated evasions
   (`rules/coding-workflow.md:200-209`).
3. The tripwire design: observe, never block; exercise rather than import;
   show `INACTIVE`; self-test (`tools/gate-sql-data-path.py`).
4. Live-oracle first, metamorphic second, hand value with origin last; small
   parity fixtures; tolerance fixed in the plan.
5. Tests-first reasoned as exposure control, with the shared-misconception
   caveat.
6. Plan review as the one check on the common-mode failure.
7. Reproduce twice at `threads=1`; two failed attempts then stop; fresh context
   on escalation.
8. The coder's checklist of holes past the linter (`.df()`, `.fetchdf()`,
   `.arrow()`, `.pl()`, `importlib`, `# noqa`, transitive imports).
9. Fixture list: NULL, NaN, empty relation, single row, one row, constant
   column, all-NULL.
10. `D417` named explicitly; docstring structure checked against what
    `__init__` accepts; BSD-3 notice obligation.
11. The report filename format and "do not infer agent state from a transcript".

## Guard against

- Building the agent layer before the first estimator. The pipeline's own text
  says "The first real estimator is the experiment that settles more of this
  than further reading will" (`rules/coding-workflow.md:520-522`) and it was
  written anyway.
- A hand-kept queue made mandatory by escalating prose (four commits to harden
  `BRIEFING.md`). Anything that must be true at all times needs a checker, not
  a stronger "MUST".
- Eight roles with a "contract identical for all seven roles" paragraph pasted
  into each file: seven copies to keep in step, and the copies already differ.
- Stale cross-references after restructuring: `coder.md:113` points to
  `.claude/playbooks/debugging.md` (the rule is `rules/debugging-workflow.md`),
  `roster-auditor.md:29` to `.claude/agent-roster/SOURCES.yaml`, `naming.md` to
  `architecture/`, and a fragment of a comment about `WORKFLOWS.md` sits
  orphaned in `session-start.sh:15-22`. These are cited in the files read;
  whether
  the targets exist elsewhere in OLD is outside this batch.
- Internal contradiction on who reads the rules: `rules.md:10` says "You are
  the only reader of `rules/`", yet `planner.md:47-79`, `README.md:10-29` and
  `session-start.sh:17-19` have others reading them.
- "Nothing commits mid-pipeline" (`rules/coding-workflow.md:528-530`) against
  the log, where the orchestrator committed TODO rows continually: the rule
  governs the code pipeline only, which never ran.
- Treating cited research as settled: figures are second-hand and unchecked
  (`rules/coding-workflow.md:516-518`); one reversed on measurement
  (`rules/docstrings.md:93-95`). Recheck any DuckDB or ruff claim on current
  versions.
- Gates that pass when empty: `gate-sql-data-path.py:53` returns clean with no
  estimators; `gate-tests-frozen.sh verify` errors only if a snapshot is
  missing.
- Planning for a quota: hardening was split from a dedicated role "under a
  weekly quota" (`rules/coding-workflow.md:506-510`); design driven by the
  token budget, not by the product.
- Many dispatches per slice (up to nine fresh contexts before commit). The
  cost was predicted, never measured.
- Redoing the same rules folder layout repeatedly in one day (`a40e633`,
  `6d60b2a`, `8eda729`, `00182f5`): decide the layout once in an ADR.

## Files covered

- [x] `rules/README.md`: how rules are found, front matter, required sections,
      enforcement, changing a rule.
- [x] `rules/code-style.md`: three-tier rules, rejected rules with sources,
      thread-count float finding, ruff selectors.
- [x] `rules/coding-workflow.md`: the 11-step pipeline, tests-first reasoning,
      frozen-set gate, fix cap, hardening, not-settled list.
- [x] `rules/debugging-workflow.md`: reproduce-twice ladder, no fix before root
      cause, stop after two attempts.
- [x] `rules/docstrings.md`: docstrings verified not authored, D417 measurement,
      doctest separation, licence gap.
- [x] `rules/naming.md`: separator per language, report filename format, id
      equals filename, rejected options.
- [x] `.claude/settings.json`: empty attribution, SessionStart hook only.
- [x] `.claude/orchestrator/BRIEFING.md`: TODO capture rule, report triage,
      dispatch craft, roster and `/clear` traps.
- [x] `.claude/orchestrator/hooks/session-start.sh`: injects briefing plus TODO
      and report counts into the main session only.
- [x] `.claude/agents/planner.md`: plan template, decided-or-not test, no
      placeholders, self-review.
- [x] `.claude/agents/coder.md`: SQL data-path invariants, holes past the
      linter, block rather than improvise, no tests.
- [x] `.claude/agents/executor.md`: non-`src/` plans, evidence before claims,
      stop on failure.
- [x] `.claude/agents/reviewer.md`: three review modes, severity, no Edit tool,
      no inventing findings.
- [x] `.claude/agents/test-author.md`: tests from spec, never `src/`,
      plausible-wrong implementations.
- [x] `.claude/agents/rules.md`: sole reader of `rules/`, verbatim quotes,
      coverage then keywords, contradictions reported.
- [x] `.claude/agents/finder.md`: citations only, never content, verified line
      ranges.
- [x] `.claude/agents/roster-auditor.md`: meta-role auditing one agent file
      against prior art and itself.
- [x] `tools/gate-tests-frozen.sh`: snapshot/verify hash gate over tests, config
      and gate scripts.
- [x] `tools/gate-sql-data-path.py`: `sys.meta_path` tripwire exercising
      estimators, with self-test.
- [x] `sql_learn_test-git-log.txt` (scratchpad): 59 commits, 21 to 24 August,
      counted by day and phase.
