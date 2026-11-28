---
type: note
tags: [process-retrospective, sqlearn, git-history, agents, skills, documentation]
summary: "Retrospective of the Tomosius/sqlearn build (Mar 13 - Apr 9 2026): workflow, commit history, process overhead, review sweep, and the pause."
related: []
mdindex: [type=edb465, tags=ed881b, summary=468b04]
---
# E-process notes: Tomosius/sqlearn (Mar 13 - Apr 9 2026)

OLD = "/Users/tomas/Desktop/Desktop - Tomas’s MacBook
Air/toosiaus_ducks_learnas/sqlearn-desktop" (paths below are relative to it).
LOG = the 271-line commit list at `scratchpad/tomosius-git-log.txt` (cited by
short sha). Depth caveat: the six agents, both settings files, the registry and
the sqlearn-specific skills (core, commit, backlog, review, structure, test,
transformer, docs, work-tracker, ideas-intake, deepthink, deep-project-audit,
sqlglot) were read in full or in large part (long ones by head, headings and
tail). The imported marketplace skills and their `references/` were read by head
or by name only; they are third-party text, not Tomas's process.
`settings.local.json` was read; no token or secret is copied here.

## Summary

- The build was spec -> reviewed plan -> per-module commits -> a `BACKLOG.md`
  tick -> a GitHub issue closed, repeated for schema, transformer, errors,
  backend, compiler, pipeline (Mar 14-15, e.g. 9daa6b9, 86aa9b5, 335a4f2,
  f93b23e). Four milestones (v0.1.0 to v0.3.0) shipped in four days
  (658617d Mar 15, a276ebd Mar 15, 8990ef1 Mar 16).
- Throughput came from parallel worktree agents: 18 `Merge branch
  'worktree-agent-*'` commits, all on Mar 16, after a review sweep
  (0e8e06a ... 17da97b). `settings.local.json` shows the agents' output being
  copied out of worktrees by hand (OLD:.claude/settings.local.json:L47-L48).
- - Process grew faster than product. Of 271 commits, 77 are `docs`, about 25
  touch skills or agents, 19 mention the backlog, 19 the architecture tree, 16
  ideas; only 88 are `feat`. The last code commit is Mar 18 (1b120cf). Mar 17
  alone was 32 commits, nearly all reorganising documents and skills.
- Nothing was reverted (no `revert` in LOG), but documents were rewritten
  repeatedly: the architecture tree was made, split, renumbered, archived,
  deleted and rebuilt inside Mar 17 (e5a7abe ... 4b156a9). Skills went 41 -> 24
  (OLD:.claude/skills/SKILLS-REGISTRY.md:L3).
- Six project agents were written (debugger, decision-critic, doc-checker,
  project-writer, sqlearn-reviewer, test-planner). They are checklists that
  restate the skills; nothing in the repository shows one being run.
- The strongest process asset is the Mar 16 review sweep: it found real
  correctness bugs (shared AST nodes, wrong default type, unquoted columns,
  OHE name sanitising; a823cdc, f6b91e8, 60a60ff, 5207a84, caf361e) that the
  per-module tests had missed.
- Work stopped on Mar 19: "pause project database ... approach under review"
  (59d0b1d). Three weeks of silence, then two docs-only commits on Apr 9
  (895d78c, abe78d2), the day the planning repo begins (README table). The log
  never says why; see History.
- The fit design in the `core` skill batches `Imputer` and `StandardScaler`
  aggregates into one layer-0 query (OLD:.claude/skills/core/SKILL.md:L188),
  which is the "later step learns from raw input" defect the baseline records.
  The same skill's own test advice (`test/SKILL.md:L343-L360`) tests the
  transform SQL only. This confirms the baseline and shows the defect was
  invisible to this attempt's tests (inference: no fit-stat assertion).
- Standards worth carrying: atomic semantic commits with a "no Co-Authored-By"
  rule, a fixed per-transformer test checklist, "SQL via AST, never strings",
  open (not yes/no) debugging questions, and an anti-sycophancy rule for design
  critics. See Worth keeping.
- Guard against: tracking the same fact in four places, skills that duplicate
  the architecture docs, a 1,446-line audit skill whose own lesson is that it
  exhausts tokens, and ideas files that grew to 273 entries before the core
  existed.

## How work ran

- **Three layers of docs drove the work.** `CLAUDE.md` (status), `BACKLOG.md`
  (milestone checklist, `[ ] [~] [x] [!] [-]`), `ideas/` (INDEX, active,
  rejected), `CURRENT_WORK.md` (a LIFO task stack), plus `docs/superpowers/`
  specs and plans (OLD:.claude/skills/backlog/SKILL.md:L10-L39;
  OLD:.claude/skills/work-tracker/SKILL.md:L10-L14). The review skill reads all
  of them to check drift (OLD:.claude/skills/review/SKILL.md:L18-L26).
- **Four systems kept in sync by hand.** BACKLOG.md, GitHub Issues, Milestones
  and Project board #22. The skill itself names forgetting the board add "the
  #1 source of sync drift" and calls completion "the most failure-prone
  workflow" (OLD:.claude/skills/backlog/SKILL.md:L10, L45, L90). The log shows
  the cost: one `chore: mark ... complete in backlog` after almost every
  feature group (f93b23e, 12f8e17, 2c88f2f, 6f664fc, 064e907, cd0d6bf, f1df179,
  4df9267, e592d5e ...).
- **Spec-and-plan per module.** Each core module has a design spec commit and
  an implementation plan commit before code (schema 9daa6b9/86aa9b5;
  transformer 1c87898/12082b8; compiler 1e7ba2e, a spec-fix after review
  ee36eb1, then "reviewed implementation plan" a99fc12; pipeline 30d9a3e,
  8cb24b9). From M3 on, plans and specs were skipped for families of simple
  transformers: feat, export, tests, docs, backlog tick in five commits each
  (scalers 0ae1be6 ... cd0d6bf).
- **Commit shape.** Conventional Commits with domain scopes; a `commit` skill
  with a fixed scope table and banned scopes (`utils`, `common`, `helpers`...)
  and rule 6, "No Co-Authored-By lines"
  (OLD:.claude/skills/commit/SKILL.md:L13-L20, L72-L98). It requires format and
  lint before staging because pre-commit hooks
  otherwise fail the commit (L22-L45). Hooks: a PostToolUse hook formats and
  fixes every `.py` file Claude writes (OLD:.claude/settings.json:L3-L12).
- **Permissions were wide.** The allow list grew to cover `git:*`, `git
  filter-branch`, `git push`, `gh project`, `python:*`, `curl` of third-party
  repositories, and a skills-marketplace MCP (OLD:.claude/settings.local.json:
  L20-L28, L83-L87). `git filter-branch` suggests history was rewritten at
  least once (inference; the log shows one oddity, `98137f7 chore: trigger
  contributor recalculation`).
- **Tooling gates before any code.** Day one (Mar 13) set up uv, ruff, mypy,
  pyright, interrogate, vulture, hypothesis, mutmut, a Makefile, CI and a
  three-tier test strategy (28e506e, fbd08b0, 82f260b, e4a6ef0). 14 commits,
  zero library code.
- **Skills were meant to improve themselves.** Most sqlearn skills end with a
  "Self-Improvement" section ("Did this skill give correct guidance? If not, fix
  it", OLD:.claude/skills/core/SKILL.md:L283-L288) and `CLAUDE.md` got a
  "self-improving skills rule" (d6fe3e4). Skills were rewritten against the
  actual code the day after they were first written (f26a5f6, Mar 15).
- **Models.** Opus for debugger, decision-critic, project-writer, test-planner;
  Sonnet for the reviewer; Haiku for the doc-checker (OLD:.claude/agents/*.md:
  L2); "model selection" was its own commit (b1a4983). The audit skill ran
  "all agents on Opus with maximum reasoning" (OLD:.claude/skills/
  deep-project-audit/SKILL.md:L9, L24).

## History

Counts per day (LOG): Mar 13: 14; Mar 14: 40; Mar 15: 85; Mar 16: 67; Mar 17:
32; Mar 18: 30; Mar 19: 1; Apr 9: 2. By type: feat 88, docs 77, chore 25,
fix 22, test 20, refactor 9, build 8, Merge 18, perf/ci/style 1 each.

1. **Scaffold, Mar 13 (f6dfffe ... 5d05992, 14 commits).** Skeleton with a
   strict toolchain, CI, lockfile, skills and hooks (45495d7 is the third
   commit), M1 marked complete (9838d0d), then three commits consolidating
   ideas from the `ducklearn` predecessors into docs (1ea8997, bad66a2,
   5d05992). Design came from earlier attempts, again.
2. **Core, Mar 14 (40 commits).** Schema (335a4f2), Transformer (c22885c),
   errors (55c6203), backend and IO (8957b9f, f98c96f), compiler in three
   phases (c58c0fe, 252b8ba, 8e2176f). Each closes a GitHub issue (#3-#6).
   Late in the day: a documentation strategy and performance roadmap
   (1698453, 6471547) before any pipeline existed.
3. **Pipeline, first transformers, v0.1.0, Mar 15 (to 658617d).** Pipeline
   (c49c5e7 ... cf4ae04), StandardScaler, Imputer, OneHotEncoder (0ae1be6,
   8835db4, 38b8037), sklearn-equivalence and SQL snapshot tests (a3685e3),
   custom transformers, mkdocs. First tagged version in about 36 hours.
4. **M3 breadth, Mar 15 (to a276ebd, v0.2.0).** Scalers, encoders, ops,
   Columns/Union, merge/concat/Lookup, guide and tutorials: about 55 commits
   in one day, with test counts in the subjects (171, 161, 255, 156, 129). The
   regular feat/export/test/docs/backlog rhythm and 18 worktree-agent branches
   later merged on Mar 16 imply parallel agents (inference).
5. **M4 and the review sweep, Mar 15-16 (871c441 ... 8990ef1, v0.3.0).** Feature
   engineering and selection (871c441, a7ca9c3), then a whole-codebase review:
   fixes for OHE column names (a823cdc), DateDiff misdetection (e61914b), shared
   AST references (f6b91e8), a wrong default type (60a60ff), raw column quoting
   (5207a84, caf361e), missing `output_schema` (039227e), thread safety
   (75b8e6a), 23 pyright errors and 1 mypy error (afb6cbf, c1e1550). Rework of
   this kind is the main value of the period; it also shows that the first
   passes shipped with defects across about 25 files (inference from the
   breadth of the fixes). AutoFeatures (0ac95f6 ... 05f56c9) followed the same
   day, and `build: pin sqlglot<30` (4fec65b) records a dependency regression.
6. **Reorganisation, Mar 17 (32 commits).** 17-reference.yaml built in nine
   commits with four "fix N accuracy issues" commits (e5a7abe ... eb93e07), then
   split by category (0ba6d1a), then the numbered chapters turned into
   `planning/` and `design/` files (cbad6e5, e542f41), INDEX.yaml (d4b0093),
   old files archived then deleted (c21f0f9, bfbd15d), then reorganised again
   (4b156a9). Parallel: IDEAS.md split into `ideas/` (0378ace), 164 ideas
   processed (9a6b033), 109 more (98a6c08), skills consolidated (a82fe5b), the
   first agents (1195ca7), work-tracker (237605d). No library code.
7. **Pre-M5 and tooling, Mar 18 (30 commits).** Pre-M5 was shrunk to four items
   because "only step naming blocks Search" (42578b5). Step naming (9e33d34),
   `suffix=` (0ae459f), `condition=` (f4238ce) were built, each with tests and
   a "document limitations" commit; two fixes followed for `condition=`
   colliding with `Filter` (ed6994c, 1b120cf). The same day: the 1,446-line
   deep-project-audit and deepthink skills (16d33ba, de96deb) and a
   DuckDB-backed "project database" with MCP (30d025b ... 63673f5).
8. **Pause, Mar 19 - Apr 9.** 59d0b1d: "pause project database - tasks 0-6
   complete, approach under review". Then nothing for 21 days. On Apr 9 two
   docs commits (895d78c project database design, abe78d2 condition and suffix
   plans) land, the same day the April planning repo starts (README attempts
   table). M5 (Search) was never begun; the last code commit is Mar 18.

**Where time went (inference from commit counts, not clock time).** About a
third on documents of all kinds, a quarter on skills, agents, backlog and
architecture bookkeeping, and the rest on code that was mostly one pattern
repeated. The only genuinely hard design work (compiler, 5 commits) took one
day.

**Why work moved on (inference).** The log gives no reason. Evidence: the last
substantive work was a self-built tooling project (project database) paused as
"approach under review"; the process stack (audit skill, registry, backlog
sync) had absorbed most effort; Pre-M5 had been cut to four items; the Apr 9
commits write the database up rather than finish it. The v0.4 attempt came
next (Apr 10-12, a clean restart by the baseline), so the plausible story is
that the Mar build was judged not worth extending. The notes in the other
batches (code, design) may confirm or reject this.

**Restarts and reverts.** No reverts, no force-push visible, no squash. The
rework was forward: fix commits after review, documents rewritten, and one
whole tree (numbered architecture chapters) deleted and rebuilt on Mar 17.

## Agents and skills

Agents (OLD:.claude/agents/, all frontmatter holds only `model:`; none sets
tools, effort or turn limits):

- **debugger** (opus). Diagnoses, never fixes; 2-4 competing hypotheses; open
  verification questions ("70% accuracy vs 17% for yes/no", an unsourced
  figure); minimum evidence of 5 debug outputs; a `[DEBUGGER:fn:line]` print
  format that must grep to zero before the report; root causes framed as
  conditions, not missing fixes (OLD:.claude/agents/debugger.md:L9-L16, L29-L45,
  L56-L70). It credits "solatis/claude-config".
- **decision-critic** (opus). Decompose, verify, challenge, then STAND, REVISE
  or ESCALATE; sqlearn checklist (composition, NULLs, clone, freeze) and an
  anti-sycophancy rule (OLD:.claude/agents/decision-critic.md:L104-L108).
- **sqlearn-reviewer** (sonnet). Three-axis review (code, docs, tests) with a
  10-item test checklist (OLD:.claude/agents/sqlearn-reviewer.md:L60-L72).
- **test-planner** (opus). Stubs a 20-category test file per transformer
  (OLD:.claude/agents/test-planner.md:L28-L80).
- **doc-checker** (haiku). Checklist that every code change ships with
  docstring, API page, nav entry, architecture entry.
- **project-writer** (opus). "Follow all conventions automatically": a write
  checklist that touches `INDEX.yaml`, `reference/*.yaml`, `docs/api/`,
  `mkdocs.yml` and tests for one new transformer (OLD:.claude/agents/
  project-writer.md:L21-L28).

Did they help? No evidence in the repository that any agent ran: no output
files, no commit subject names one (LOG has 18b4516 "add extreme testing ...
and project agents" and 1195ca7 "add debugger, decision-critic,
project-writer agents" only). The
worktree-agent merges are anonymous implementers, not these types (inference).
Their design is sound but all six are static checklists duplicating `test`,
`transformer` and `docs` skills; the reviewer and doc-checker repeat each other.
`project-writer` exists to remind an agent of the sync burden the architecture
created: the fix for a tracking problem was another agent.

Skills (24 after consolidation, OLD:.claude/skills/SKILLS-REGISTRY.md:L3-L67):

- **Nine custom** (backlog, commit, core, docs, review, sqlglot, structure,
  test, transformer), plus work-tracker, ideas-intake, deepthink and
  deep-project-audit added later and absent from the registry (inference: the
  registry is dated Mar 17, those landed Mar 17-18).
- **Fourteen marketplace, kept** (python-type-safety, advanced-code-quality,
  error-handling-patterns, designing-python-apis, packaging-python-libraries,
  scikit-learn, tuning-hyperparameters, shap, frontend-development,
  tailwind-ui, echarts, websocket-realtime, python-fastapi-ops, ci-release as
  merged). Roughly 670 KB of the ~900 KB under `.claude/` is imported text for
  later parts of the product (Svelte, SHAP, Optuna, FastAPI) that did not
  exist. Nineteen others were dropped (registry L61-L67).
- **Helpful in practice:** `commit` (rules reappear in the new CLAUDE.md),
  `sqlglot` (five safety rules, learned from the Mar 16 bugs: always quote,
  never reuse a node, native nodes not Anonymous, `TableAlias`), `test`
  (checklist of 11 mandatory tests plus pipeline stress tests), `core` (a
  usable map of the compiler).
- **Costly:** `backlog` (fourfold sync), `review` (reads sixteen design docs
  every run), `deep-project-audit` (1,446-line SKILL.md plus 4,093 lines of
  references; its own lesson: "12 parallel Opus agents hits token limits in ~2
  minutes", OLD:.claude/skills/deep-project-audit/SKILL.md:L1419) and the
  project-database it grew into.
- **Skills were self-referential.** The audit skill has a Phase 9 that edits
  skills, an "ecosystem-health" agent that audits CLAUDE.md, skills and memory
  (SKILL.md:L688-L735, near Agent 13), and a rule that a repeat finding means
  the loop failed (L1411-L1413). Process auditing process.
- **Absolute paths** to `/Users/tomas/coding/sqlearn/CURRENT_WORK.md` are baked
  into work-tracker (OLD:.claude/skills/work-tracker/SKILL.md:L18); skills were
  tied to one machine.

## New against the baseline

- **A third, smaller sibling of the plan-heavy process.** The baseline says
  plans and standards outgrew the product. Here it happens in four days and is
  measurable: 77 docs and about 25 skill/agent commits against 88 feats, and
  the product halted while the process grew (Mar 17-19).
- **Review sweeps find what unit tests do not.** One pass by parallel agents
  produced about 24 fix/refactor commits within a day. The per-module tests
  (sometimes hundreds each) had passed. Evidence for an independent review
  gate with a different brief from the author's.
- **Dependency regression recorded in process, not code:** `sqlglot<30` pinned
  (4fec65b) after pyright regressions, in the review skill
  (OLD:.claude/skills/review/SKILL.md:L83). Adds to the baseline's sqlglot
  costs.
- **Agent token economics.** A written lesson that 12 parallel Opus agents burn
  the session in two minutes, answered with step-by-step mode as default.
- **Self-modifying skills as a policy**, and the three-week stall after the
  tooling project it spawned (project DuckDB with MCP). New: the process
  tooling was itself a DuckDB application, built before the library's core
  question was settled.
- **Hooks as the only enforcement.** A PostToolUse formatter hook was the only
  automatic gate; everything else (backlog sync, docs, architecture entries)
  relied on agents remembering a checklist.
- **The ideas pipeline**: INDEX, active, rejected, with a dedup step against
  rejected ideas (OLD:.claude/skills/ideas-intake/SKILL.md:L19-L26). A useful
  idea that was overwhelmed by volume (164 + 109 in two days).

## Contradicts the baseline

- **"Both attempts wrote a strong validation method and never enforced it."**
  Here the sklearn-equivalence tests were written first-class and run in
  integration (a3685e3, eb41f12) with `np.testing.assert_allclose` and a 1e-10
  tolerance named in the planner (OLD:.claude/agents/test-planner.md:L62).
  Partial contradiction: enforcement existed for the 11 per-transformer tests.
  It still missed the Imputer-then-Scaler fit, so the baseline's wider point
  (no ground truth for fit semantics) holds.
- **"Plans and standards outgrew the product, and nobody updated them."** The
  skills *were* updated, repeatedly: rewritten "against actual code" (f26a5f6),
  stale refs fixed (cee54a8), version sync checks added (2a082da). The failure
  here is the opposite: constant updating consumed the time. Nuance, not
  reversal.
- **The baseline's v0.4 had unticked plans; this attempt ticked everything**
  (BACKLOG marks after every group). Tracking discipline was high; it was the
  cost that was wrong.

## Confirms the baseline

- **Fit semantics.** The `core` skill states layer-0 fit is "one batched query
  for Imputer + StandardScaler + OneHotEncoder aggregates"
  (OLD:.claude/skills/core/SKILL.md:L188), and only static steps are composed
  into aggregates (L110-L115). A dynamic step's output is not fed to the next
  dynamic step's statistics. Same defect as `sqlearn_000` and v0.4, found a
  third time (inference from skill text; confirm in the code batch).
- **Layering as the workaround.** The "layer boundary after dynamic +
  schema-changing step" rule (L177) is a narrower boundary than the baseline
  asks for ("a learning step reads a value an earlier step changed").
- **sqlglot from day one**, and its costs: pinned `<30`, type-checker noise
  (23 pyright errors, afb6cbf; five `pyright: ignore` patterns in the
  structure skill), AST aliasing bugs (f6b91e8; skill rule 2).
- **Learned state keyed as `{col}__{stat}`**, which the reviewer enforces
  (OLD:.claude/agents/sqlearn-reviewer.md:L28) and the baseline names as a
  failure (keys split on `__`).
- **Scikit-learn API kept** at first: `get_params`, `clone`, `fit_transform`,
  pickle (Mar 14, 7fddc49, 6eccee9), consistent with ADR 0003, then extended
  with `suffix=`/`condition=` on every transformer (Mar 18).
- **Process heavier than product**, as in v0.4 (see E-process of v0.4).

## Worth keeping

- **Commit rules**: one logical change, imperative subject up to 72 characters,
  domain scope table, banned scopes, no co-author trailers, read the changed
  files before writing the message
  (OLD:.claude/skills/commit/SKILL.md:L13-L20, L47-L55).
- **Format and lint before staging**, so the hook never rewrites a commit
  (L22-L45); the new repo's `just fmt` rule is the same lesson.
- **Test checklist per transformer** (equivalence, SQL snapshot, nulls, clone,
  pickle, not-fitted, composition, extreme edge cases such as 1e308 and
  keyword column names; OLD:.claude/skills/test/SKILL.md:L47-L250), and a
  test for each dependent chain (L343). Needs a fit-time assertion that a later
  step's statistic is computed on the earlier step's output.
- **SQL safety rules** from real bugs (OLD:.claude/skills/sqlglot/SKILL.md:
  L16-L88): quote every identifier, copy not share nodes, `NULLIF` on every
  divisor. These are engine-independent facts about generated SQL.
- **Open verification questions and cleanup attestation** in the debugger
  (a debug marker that must grep to zero), root causes stated as conditions.
- **Anti-sycophancy rule** in a decision critic: if you agree with everything,
  stop. And the verdict set STAND, REVISE, ESCALATE.
- **The review sweep as a distinct step**, run by agents with a fresh brief,
  after a build burst. Its outputs (fixes) were real.
- **Step-by-step as default for agent fleets**, with `--parallel` opt-in.
- **Idea intake**: dedup against rejected ideas with reasons.
- **Docs lead with the SQL output** (OLD:.claude/skills/docs/SKILL.md:L70-L77),
  which suits a SQL-first library.
- **Day-one gates** (strict lint, types, docstring and dead-code checks), as in
  the new repo.

## Guard against

- **Four-way sync.** Do not track one fact in a file, an issue, a milestone
  and a board. One tracker (GitHub Issues, per the new workflow).
- **Skills that mirror the architecture docs.** `core`, `transformer` and
  `structure` copy class signatures and compiler internals; they drifted and
  were rewritten the day after writing (f26a5f6). Point at the doc; do not copy.
- **Imported skills for parts that do not exist** (Svelte, SHAP, Optuna,
  FastAPI, ECharts). Add a skill when the work arrives.
- **Idea volume before the core exists**: 164 + 109 ideas, GPU back ends,
  Vortex, "extreme and bizarre" idea generation inside an audit
  (OLD:.claude/skills/deep-project-audit/references/ideas-generation.md).
  Park outside the repository or in one file.
- **Documentation churn without a reader**: the architecture tree was
  rebuilt three times on Mar 17. Decide the layout (the new `docs/` layout)
  before filling it.
- **Auditing the process.** An agent that audits CLAUDE.md, skills and memory
  (agent 13) is a sign the meta layer has become the project.
- **Milestone velocity as a goal.** Version bumps (v0.1.0 to v0.3.0 in four
  days) with only unit tests show "released" meant "tests written".
- **Machine-specific paths** in skills and permissions (CURRENT_WORK.md path,
  copy-from-worktree commands).
- **Broad permissions** (`git:*`, `filter-branch`, `python:*`, `curl` of third
  party content) and installing community skills through a marketplace MCP.
  ADR 0001 forbids bare `python`; this allow list contradicts it.
- **Trusting equivalence tests alone.** Write a fit-semantics test that fails
  on Imputer then Scaler using raw stats (see Confirms).
- **Agents that restate skills**: if a checklist exists in a skill, an agent
  that reads it adds nothing. Create an agent only where it needs its own tools,
  model or context (matches the proposed rule in `workflow.md`).
- **Unrecorded dispatch.** Worktree agents merged without a record of brief or
  result (the 18 merges are the only trace). The new workflow's reviewer
  verdict should be stored with the work.

## Files covered

The log counts as one file. Paths are relative to OLD/.claude/.

- [x] git log (LOG): 271 commits Mar 13 - Apr 9; read in full (History).

Settings

- [x] settings.json: one PostToolUse hook, ruff format and fix on `.py` writes.
- [x] settings.local.json: allow list (git, gh, uv, make, curl, skills MCP,
  worktree copies); enables the `duckdb` MCP; no secret copied.

Agents

- [x] agents/debugger.md: opus; diagnose-only; hypotheses; debug markers.
- [x] agents/decision-critic.md: opus; four-phase critique; verdicts.
- [x] agents/doc-checker.md: haiku; documentation completeness checklist.
- [x] agents/project-writer.md: opus; convention checklist for every write.
- [x] agents/sqlearn-reviewer.md: sonnet; code, docs, tests review.
- [x] agents/test-planner.md: opus; 20-category test-file generator.

Own skills (read in full or in large part)

- [x] skills/SKILLS-REGISTRY.md: 24 skills after consolidation from 41.
- [x] skills/backlog/SKILL.md: four-system sync; read to line 110.
- [x] skills/commit/SKILL.md: commit protocol, scope table, no co-author.
- [x] skills/core/SKILL.md: compiler map; layer-0 batched fit (L188).
- [x] skills/deep-project-audit/SKILL.md: wave audit; head, agents, lessons.
- [x] skills/deepthink/SKILL.md: 14-step reasoning; read by headings.
- [x] skills/docs/SKILL.md: docs rules; read by headings and tail.
- [x] skills/ideas-intake/SKILL.md: idea list, dedup, classify, file.
- [x] skills/review/SKILL.md: three-phase review; read to line 110.
- [x] skills/sqlglot/SKILL.md: AST rules; read by headings and L1-L90.
- [x] skills/structure/SKILL.md: file layout and boilerplate; read to L110.
- [x] skills/test/SKILL.md: test checklist; headings and L343-L376.
- [x] skills/transformer/SKILL.md: new-transformer checklist; headings, tail.
- [x] skills/work-tracker/SKILL.md: CURRENT_WORK stack; read in full.

deep-project-audit references (headings or size only)

- [x] skills/deep-project-audit/references/agent-prompts.md: 995 lines; named.
- [x] skills/deep-project-audit/references/audit-dimensions.md: 360 lines;
  headings read.
- [x] skills/deep-project-audit/references/ideas-generation.md: 253 lines.
- [x] skills/deep-project-audit/references/python-checklist.md: 273 lines.
- [x] skills/deep-project-audit/references/sharp-edges.md: 281 lines; named.
- [x] skills/deep-project-audit/references/yaml-schemas.md: 485 lines; named.

Marketplace skills (head only; third-party)

- [x] skills/advanced-code-quality/SKILL.md: quality-gate tools (headings).
- [x] skills/designing-python-apis/SKILL.md: generic API design (headings).
- [x] skills/packaging-python-libraries/SKILL.md: generic packaging (headings).
- [x] skills/python-type-safety/SKILL.md: generic typing (head only).
- [x] skills/error-handling-patterns/SKILL.md: generic errors (head only).
- [x] skills/error-handling-patterns/references/error-hierarchy-examples.md:
  not opened; named.
- [x] skills/error-handling-patterns/references/retry-patterns.md: not opened.
- [x] skills/ci-release/SKILL.md: merged CI/release (head only).
- [x] skills/ci-release/references/github-actions.md: not opened; named.
- [x] skills/ci-release/references/release-workflows.md: not opened; named.
- [x] skills/ci-release/references/semver.md: not opened; named.
- [x] skills/ci-release/references/uv-ci.md: not opened; named.
- [x] skills/scikit-learn/SKILL.md: K-Dense sklearn patterns (head only).
- [x] skills/scikit-learn/references/model_evaluation.md: not opened.
- [x] skills/scikit-learn/references/pipelines_and_composition.md: not opened.
- [x] skills/scikit-learn/references/preprocessing.md: not opened.
- [x] skills/scikit-learn/references/quick_reference.md: not opened.
- [x] skills/scikit-learn/references/supervised_learning.md: not opened.
- [x] skills/scikit-learn/references/unsupervised_learning.md: not opened.
- [x] skills/scikit-learn/scripts/classification_pipeline.py: not opened or run.
- [x] skills/scikit-learn/scripts/clustering_analysis.py: not opened or run.
- [x] skills/shap/SKILL.md: SHAP patterns (head only).
- [x] skills/shap/references/explainers.md: not opened.
- [x] skills/shap/references/plots.md: not opened.
- [x] skills/shap/references/theory.md: not opened.
- [x] skills/shap/references/workflows.md: not opened.
- [x] skills/tuning-hyperparameters/SKILL.md: Optuna workflow (head only).
- [x] skills/tuning-hyperparameters/references/optuna_guide.md: not opened.
- [x] skills/tuning-hyperparameters/references/result_analysis.md: not opened.
- [x] skills/tuning-hyperparameters/references/search_space_design.md:
  not opened.
- [x] skills/tuning-hyperparameters/references/strategy_selection.md:
  not opened.
- [x] skills/echarts/SKILL.md: ECharts how-to (head only).
- [x] skills/websocket-realtime/SKILL.md: WebSocket/SSE patterns (head only).
- [x] skills/tailwind-ui/SKILL.md: Tailwind pointers (head only).
- [x] skills/tailwind-ui/references/patterns.md: not opened.
- [x] skills/tailwind-ui/references/sharp_edges.md: not opened.
- [x] skills/tailwind-ui/references/validations.md: not opened.
- [x] skills/python-fastapi-ops/SKILL.md: FastAPI patterns (head only).
- [x] skills/python-fastapi-ops/assets/fastapi-template.py: not opened or run.
- [x] skills/python-fastapi-ops/references/background-tasks.md: not opened.
- [x] skills/python-fastapi-ops/references/dependency-injection.md: not opened.
- [x] skills/python-fastapi-ops/references/middleware-patterns.md: not opened.
- [x] skills/python-fastapi-ops/references/validation-serialization.md:
  not opened.
- [x] skills/python-fastapi-ops/scripts/scaffold-api.sh: not opened or run.
- [x] skills/frontend-development/SKILL.md: multi-framework guide (head only).
- [x] skills/frontend-development/resources/common-patterns.md: not opened.
- [x] skills/frontend-development/resources/complete-examples.md: not opened.
- [x] skills/frontend-development/resources/component-patterns.md: not opened.
- [x] skills/frontend-development/resources/data-fetching.md: not opened.
- [x] skills/frontend-development/resources/file-organization.md: not opened.
- [x] skills/frontend-development/resources/loading-and-error-states.md:
  not opened.
- [x] skills/frontend-development/resources/performance.md: not opened.
- [x] skills/frontend-development/resources/routing-guide.md: not opened.
- [x] skills/frontend-development/resources/styling-guide.md: not opened.
- [x] skills/frontend-development/resources/typescript-standards.md: not opened.
