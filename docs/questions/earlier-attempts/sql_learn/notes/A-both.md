---
type: note
tags: [sql-learn, process, agent-harness, earlier-attempts, retrospective]
summary: "Comparative review of two earlier sql_learn attempts (OLD1 and OLD2), mostly about agent harness and process rather than the library itself."
related: [docs/questions/earlier-attempts/sql_learn/notes/A-both.md, "OLD1:CLAUDE.md", "OLD2:README.md", "OLD2:TODO.json", "OLD2:plans/review-estimator-contract.md"]
mdindex: [type=edb465, tags=6af363, summary=256ed2, related=ef8777]
---
# sql_learn: batch A, both histories

Attempt: `sql_learn` in two parts, both GitHub `glaucis/sql_learn` with
separate histories, read for the earlier-attempts drain. Tier light, one batch.

- OLD1 = ROOT `sql_learn_27.08.2026`: 26 August 2026 (the commits all carry
  that date; the folder name says 27), 47 commits, 8 files.
- OLD2 = ROOT `sql_learn`: 27 to 30 August 2026, 68 commits, 75 files.
- ROOT = `/Users/tomas/Desktop/Desktop - Tomas’s MacBook Air/` then
  `toosiaus_ducks_learnas`.
- Citations: `OLD1:path:Lnn`, `OLD2:path:Lnn` (file-relative lines), or a sha.
  `OLD2:TODO.json:notes[n]` is the n-th note (from 0) of its single entry.
  "(inference)" marks my reading, not the text. "Baseline" is **What we know
  so far** in the README.
- The two git logs list commits oldest first (inference from content: in OLD1
  `3add633`, the first line, builds the hook that `3528d48`, further down,
  removes). Neither repository was touched; nothing was run there.
- Not rechecked: every DuckDB claim below was measured by the old agents on
  DuckDB 1.5.5. The baseline was checked on 2.0.0. The review step must
  recheck them (see Worth keeping).

## Summary

- Both restarts are about the harness, not the library. OLD1 has 8 files and no
  code; OLD2 has 73 files, of which `src/` is one docstring and `tests/` an
  empty `.gitkeep` (`OLD2:src/sql_learn/__init__.py:L1-L5`). About 5,000 lines
  of Python went into a task-tracker CLI (`scripts/todo`, 388 tests) and 13
  agent definitions instead. Of 68 commits, 3 touch the library
  (`88b250a`, `0985f6f`, `c02ad8d`); 37 are scoped `todo`.
- OLD1 set out to make "Tomas is the sole creator" mechanically true, then to
  build a four-agent git roster. The first commit enforces sole authorship at
  commit time (`3add633`); the last substantive one deletes the whole roster
  and the hook (`3528d48`). OLD1's own `CLAUDE.md` ends by saying the rule
  "is NOT enforced" (`OLD1:CLAUDE.md:L45-L56`).
- OLD1 measured the cost: a `git` agent dispatched to commit one Markdown file
  ran 10.5 minutes and was cancelled with no commit (`OLD1:TODO.md:L71-L78`).
  That is the stated reason for the deletion.
- OLD1 left the real design to a pipeline it did not build: plan, independent
  review, implement, and "a filed bug stops the line" (`OLD1:TODO.md:L46-L56`).
  OLD2, started the next day, builds that pipeline with new names.
- OLD2 designed one library document, the estimator contract plan, and its
  reviewer measured the strongest new fact: a lazy chain of DuckDB relations
  has `sql_query()` text that grows about 4x per step for any step that reads
  its input twice (a scaler: 173 characters at depth 1, 2,916,231 at depth 14)
  (`OLD2:plans/review-estimator-contract.md:L88-L115`). This bears directly on
  "can fit be lazy".
- OLD2 parked every library question (eight, in `ORIGINAL_TODO.json`) behind a
  phase marker that only Tomas may close, so the library never started
  (`OLD2:.claude/ORCHESTRATOR.md:L131-L159`).
- The "orchestrator brief hook" is a SessionStart hook that injects a
  main-session-only brief (OLD1 `BRIEFING.md`, OLD2 `ORCHESTRATOR.md`) and, in
  OLD2, the output of `./todo next`. The "jq oracles" were two jq
  implementations of the task-dependency logic kept as test references; they
  were deleted in the last commit (`29f0d36`).
- Neither names an earlier attempt (no hit for sqlearn, ducklearn, sqlglot or
  "earlier attempt" in their prose). The only visible inheritance is the
  orchestrator hook, the authorship rule and the commit skill passing from OLD1
  to OLD2 (inference from the commit subjects).
- Neither stopped for a stated reason. OLD1 ends mid-redesign with a long
  "Now" list; OLD2 ends with a clean tree, 388 passing tests and four bug
  reports filed after the last commit, all three "blocks" (inference: dated
  31 August, after `29f0d36`).
- Baseline: the process lesson repeats (harness outgrew product, hand-kept
  state drifted, a different agent reading the work caught what
  self-verification passed); two new facts (exponential relation text, the
  differential-oracle trap) and one new design option (fitted state as a lazy
  relation, shown to refit silently).

## sql_learn_27.08.2026

**What it was.** A fresh repository on 26 August whose only product is process.
It has `CLAUDE.md`, a 653-line `TODO.md`, `.gitignore` and `.claude/` (settings,
an orchestrator briefing, two hooks, a capture log). `README`, `pyproject` and
`src` do not exist. Its `CLAUDE.md` calls itself "Project instructions" and
says nothing about what sql_learn is (`OLD1:CLAUDE.md:L1-L7`); no file in it
says it is a SQL machine-learning library (inference: only OLD2's README does,
`OLD2:README.md:L3-L5`).

**What it set out to do, and why.** Two aims, both about control of the AI
agents rather than about the library:

- Keep the history free of AI attribution. "Tomas is the sole creator. HARD
  RULE, no exceptions" (`OLD1:CLAUDE.md:L9-L14`). This is the same rule as the
  global `CLAUDE.md` of this repository (same wording family: no
  `Co-Authored-By`, no `Claude-Session`, no "Generated with"), here made
  project-local because `~/.claude/` "is not loaded in cloud sessions"
  (`OLD1:CLAUDE.md:L35-L38`).
- Make the main session a dispatcher that never loses a finding. The briefing
  says the orchestrator's context is "the scarce resource" and the default is
  to dispatch (`OLD1:.claude/orchestrator/BRIEFING.md:L9-L15`), and that every
  warning, question, answer and anomaly gets a `TODO.md` row "the moment it
  appears" (`BRIEFING.md:L32-L56`).

**What it enforced.** Sole authorship at commit time: yes, for part of the day.
`3add633 build(authorship): enforce sole authorship at commit time` is the first
commit of the log. From OLD1's own text the mechanism was
`.githooks/commit-msg`:
it "reject[ed] any commit carrying AI attribution, and any commit whose author
or committer was not Tomas", and it was inert until `core.hooksPath` was set
(`OLD1:CLAUDE.md:L47-L52`). Later commits tuned it: report the offending line
(`17a18bd`), keep the phrase check over-strict (`5742801`), record that a hook
committed as mode 100644 is inert on clone (`16f6d6e`). It also had a
behavioural test, run immediately before deletion (`OLD1:TODO.md:L388-L391`).

It was deleted on 26 August in `3528d48 build: remove the git roster, commit
protocol and hooks`, and `core.hooksPath` was unset (`OLD1:CLAUDE.md:L47-L50`).
After that the file states, in bold, "It is NOT enforced. Nothing checks it but
you", with no hook, no CI gate and no second copy (`OLD1:CLAUDE.md:L45-L56`,
`L70-L73`). The repository ends with the rule held by one prose paragraph.

**What else it enforced or built, then removed.** Between `3add633` and
`3528d48` it built, and then deleted, `git` (a coordinator that only spawned),
`git-committer`, `github-curator` (a flat `issues/` store mirroring GitHub
issues), `repo-auditor` (18 drift checks), `INVARIANTS.md`, a commit protocol
with amendments A1 to A6, and a `commit-message` skill (`OLD1:TODO.md:L71-L78`,
`L393-L408`). What survived is the orchestrator hooks.

**What it left open** (all in `OLD1:TODO.md`, every one a row, none done):

- Whether the authorship hook stays gone. The row calls it "the highest-
  consequence item in the file" and gives the recovery commands
  (`L379-L392`).
- The design itself: plans, bugs and reports stores, `plan-writer`,
  `plan-reviewer`, `bug-reviewer`, `report-reviewer` (rows 1 to 6,
  `L108-L206`). All eight decisions "MADE", none built; the build "was started
  and deliberately reverted mid-flight" so that it would go through the new
  pipeline (`L38-L42`). Row 6 asks where the ownership table ("who may write
  what") now lives after `INVARIANTS.md` was deleted (`L180-L206`).
- Release plumbing researched but not chosen: type-to-bump mapping, pre-1.0
  policy, static versus tag-derived version (recommend static, 0.1.0, stay in
  0.x), first version pinned in config (`L230-L342`). No `pyproject.toml`
  exists, so these are decisions about a package with no files.
- "Never push" cannot be enforced by deny rules or tool lists; at best it is
  a speed bump and an audit trail (`L343-L375`). `origin` is configured and
  there are no tags and no `permissions` block (`L479-L491`).
- A path-versus-type CI check and a drift-assertion job (`L414-L437`), a check
  that invariants are not restated (`L438-L450`).
- The `TODO.md` preamble and about eight rows describe an agent roster that no
  longer exists (`L452-L477`).
- Subagent-return capture gaps: only the last message of an agent is kept, so
  an agent that corrects itself in a final addendum loses its earlier report
  (`L495-L509`); the claim that `SubagentStop` misses 42% of calls is
  unverified and contradicted locally (`L519-L533`); it fires for non-returns
  (`L535-L543`).

**The capture log.** `returns.jsonl` has 195 rows captured from 26 August 15:59
to 27 August 01:44: 14 genuine subagent returns (7 `general-purpose`, 3
`claude-code-guide`, 3 `git-committer`, 1 `git`) and 181 `unknown` events with
an empty agent type, 15 rows marked drained. The notes of the drained ones show
what the agents were used for: six research agents on versioning tools
(release-please, uv, python-semantic-release, setuptools-scm, hatch-vcs), one
on `skills:` preloading, one on deny rules, three `git-committer` runs, and one
`git` run "killed mid-run by request" at 19:40 (row 189). It is a 240 KB file,
gitignored on purpose (`OLD1:.gitignore:L1-L4`).

**What was valuable in it.** Operational rules learned under load, mostly in
`BRIEFING.md`:

- A structural check (row count, heading count) passes on a hollowed-out file;
  diff the whole file after any scripted edit (`BRIEFING.md:L124-L179`). A
  drain script deleted the file's H1 and preamble silently and only a
  subagent reading the diff caught it (`L145-L150`).
- "A false FAIL costs one investigation. A false PASS ends the investigation"
  (`L139-L141`).
- The same fact in three files will drift, "and nothing detects it" (`CLAUDE.md`
  L40-L43; `TODO.md` L10-L14 "a fact you can re-derive in one command is not
  stored").
- "Document a finding in TODO.md and stop there. Fixing is a separate
  decision" (`BRIEFING.md:L110-L122`), then reconciled with the stop-the-line
  rule (`TODO.md:L93-L106`).
- A decision made but not built is the most dangerous state (`TODO.md:L15-L18`).

**Why it stopped** (inference; no file says). The last commit is `e5d918a docs:
record what the removal left open`, on the same day as the deletion. The queue
had become the product: 47 commits, 8 files, zero library files. The measured
10.5-minute commit, the agent run killed at 19:40, and the decision to rebuild
the design "through the pipeline this design creates" (`TODO.md:L38-L42`) point
to a restart that begins with that pipeline. The next day a new repository,
OLD2, starts with the same hook and builds that pipeline.

## sql_learn: design, code, reports

**What it set out to do, and why.** `README.md` states the idea in one
paragraph: "a Python library for building machine learning models, intended to
replace scikit-learn", with computation executing as SQL and DuckDB "the primary
target"; no pandas or numpy in the library; polars rejected because "its eager
and lazy paths diverge under aggressive optimisation"; scikit-learn, numpy,
pandas and polars only as reference implementations for development and tests
(`OLD2:README.md:L3-L19`). It says "Status: Early. The architecture, the
estimator contract, and the rest of this README are not written yet"
(`L21-L24`). So the restart, in the text, is the original goal restated; what
it actually built first was the harness that would build it (inference from the
history, below). The harness is the OLD1 pipeline reborn: a bug inbox that
freezes new work, `plan-writer` and `plan-reviewer`, and a frozen-contract
build with blind test-writing.

**Source and tests (what was built).** Almost nothing.

- `src/sql_learn/__init__.py` is a five-line docstring: "Nothing is exported
  yet. The estimator contract is frozen here once its open decisions land"
  (`OLD2:src/sql_learn/__init__.py:L1-L5`).
- `tests/` holds an empty `.gitkeep`.
- `pyproject.toml`: package `sql_learn`, version 0.0.0, hatchling, Python
  `>=3.11` (ADR 0007 says 3.12 here), one runtime dependency
  `duckdb>=1.5.5,<1.6`, and a `test` extra of pytest, hypothesis, scikit-learn,
  numpy, pandas, polars (`OLD2:pyproject.toml:L1-L32`). The ceiling is
  deliberate: several assumptions are "undocumented DuckDB internals" (the shape
  of `sql_query()` text, the `ColumnDataCollection` marker, an empty
  `duckdb_views().sql`, binder message wording) and a floor alone "lets any
  future release change all of them silently" (`L13-L19`). The review had asked
  for exactly this (`OLD2:plans/review-estimator-contract.md:L179-L187`).
- The only real code is the harness, `scripts/todo/`: nine modules (`store`,
  `graph`, `edit`, `query`, `checks`, `gate`, `render`, `__main__`) and
  13 test files, about 5,000 lines with 388 passing tests (`OLD2:TODO.json:
  notes[3]`). Details under Process and tooling.

**Designed: architecture.** `architecture/` holds only a README and a template.
Its rule is the useful part: "nothing is written here until it exists"; intent
goes in `plans/`, because a stale plan is old but a stale architecture file is
wrong, "written in the voice of a fact" (`OLD2:architecture/README.md:L3-L16`,
`L37-L41`). Each file must carry `covers:` (what to search for) and `files:`
(real paths, so `rg -l -f <(git diff --name-only) architecture/` finds stale
pages) (`L25-L35`). No architecture file was ever written because nothing was
built.

**Designed: plans.** One plan and its review.

`plans/estimator-contract.md` (status draft, marked PARKED, `L3-L14`). It
declares that no assumption rests on library code because none exists; every
DuckDB behaviour "names the check that established it" (`L16-L28`). Its
Assumes section is a measured catalogue on DuckDB 1.5.5:

- Relations are lazy and compose without executing, but construction binds
  eagerly against the catalog, so a live connection is needed to build
  (`L53-L76`).
- A relation held as fitted state re-evaluates on every execution: a sum over
  rows 0 to 4 returns 10, then 110 after an insert, then 1110; a z-score
  relation returns different values for the same object after one outlier is
  inserted (`L101-L115`).
- `params=` executes at once and materialises, so bind parameters cannot carry
  fitted values lazily (`L117-L122`). Floats round-trip exactly through
  `repr`, but bare `inf` and `nan` parse as column names and raise;
  `'nan'::DOUBLE` works (`L123-L127`).
- Row order is not preserved by `JOIN`, `GROUP BY`, `ORDER BY`, multi-table
  `FROM`, subqueries and scalar subqueries; `rowid` exists only on materialised
  tables; `row_number() OVER ()` is the documented remedy (`L131-L147`).
- Relations and connections cannot be pickled or deep-copied, die with their
  connection, and a relation carries a mutable shared fetch cursor
  (`L148-L160`).
- `read_only=True` rejects `CREATE TABLE` and non-temp macros; TEMP tables are
  per connection and invisible to `con.cursor()`; relation-created views are
  durable but `duckdb_views().sql` is empty, while macros are durable and
  readable (`L165-L182`).
- With only duckdb installed, `df()` and `fetch_record_batch()` fail on the
  missing library (`L191-L198`).

Its 13 steps (pin DuckDB, relation as the single handle, input adapter, ban
executing members outside one module, estimator base class, `fit` and the
target, row identity, state writer, execution module, `Pipeline.fit` with "no
execution between steps", duplicate-column check, a conformance test that
nothing executes, a first scaler checked against `StandardScaler`)
(`L234-L321`) and eight Open decisions (`L323-L406`): `fit(X, y)` or one
relation plus a target column; where fitted state lives (five candidates);
laziness in the public API; persistence; whether `fit` executes; row identity;
SQL strings versus relation API; naming of library objects.

`plans/review-estimator-contract.md` (verdict "sound with fixes", `L14`). It
re-ran every claim on a clean venv: most hold "to the digit" (`L19-L24`), four
are wrong. The findings that matter for sqlearn:

- Finding 1: "text growth is linear" holds only for unary chains. For any
  operator that reads its input twice (every fitted transform: aggregate then
  join back) `sql_query()` text duplicates the whole subtree, because it does
  no CTE sharing. Scaler chain: depth 1 is 173 characters, depth 4 is 2,665,
  depth 8 is 45,385, depth 12 is 728,919, depth 14 is 2,916,231; depth 12 took
  0.262 s to build and 0.688 s to run; depth 20 hung for 8 minutes and was
  killed; scans double per level (`L88-L115`). The plan's guard against
  `max_expression_depth` (1000) "watches the wrong limit".
- Finding 2: duplicate column names do not fail downstream, they resolve
  silently to the first match once the join is a subquery
  (`SELECT k FROM (SELECT * FROM k1 JOIN k2 ...)` returns a row; `order('k')`
  renames the duplicate `k_1`) (`L117-L132`).
- Finding 3: the list of executing members is incomplete (`execute`,
  `insert_into`, `update`, the frame and arrow family), and the frame family
  runs the query before failing without the library (`L134-L148`).
- Finding 4: `profiling_output` is one file overwritten per query, so the
  plan's way of counting queries cannot work (`L150-L155`).
- Finding 5: a relation exposes no connection; the real handle is
  `(relation, connection)` (`L157-L169`).
- Findings 5, 6, 8: decisions buried in steps that declare no blocker (step 2
  settles "laziness in the public API", step 10 presupposes "fit stays lazy",
  step 3 invents three API choices) (`L157-L208`).
- Finding 9: `row_number() OVER ()` costs 5.7x to 7.2x on a scan at 2 M to
  60 M rows, not the 2x quoted from one measurement; compounded with finding 1
  that lands on exponentially many scans (`L210-L225`).
- Finding 10: `search and model selection` and `predict` and `fit_transform`
  have no step (`L227-L236`).

The review's note that "a plan is never a bug" (nothing is built, so nothing
breaks) is a process rule, repeated in `CLAUDE.md` and the agents.

**Found: reports.** 15 files, of which only these carry content:

- `reports/research/2026-08-27-duckdb-relation-limits.md`: the four DuckDB
  behaviours above, written as constraints "tied to a version, not documented
  guarantees" (`OLD2:reports/research/2026-08-27-duckdb-relation-limits.md:
  L19-L104`).
- `reports/research/2026-08-29-mcp-in-web-and-cloud-sessions.md`: stdio MCP
  servers cannot run in web and cloud sessions, and the cloud sandbox allows
  only `api.anthropic.com` and `registry.npmjs.org`; so the harness is a plain
  checked-in script, not an MCP server (`L1-L8`, `L41-L44`).
- Four bug reports filed 31 August 00:04 to 00:06 by the orchestrator, "reading
  the whole of `scripts/todo/` on Tomas's request": two `./todo` writes
  launched together silently lose one (read-modify-write without a lock,
  `store.py:193`); `set --name` writes then crashes with a traceback;
  `set --field` bypasses every validator and can wedge the file (so the only
  repair is a hand edit); `WORKFLOWS.md` still tells you to file `kind: bug`,
  which the script refuses. All severity "blocks" except the last
  ("annoying"). They post-date the last commit (`29f0d36`, 30 August), so they
  are probably uncommitted (inference) and would have frozen the project under
  its own stop-the-line rule.
- `benchmarks/README.md`: rules for recording runs against a reference ("keep
  the numbers, not a verdict"; record divergence in full; name the versions)
  (`L1-L29`). No benchmark was ever run.
- `reviews/README.md`: a standing artefact gets one file overwritten each round,
  a diff gets a dated file that accumulates (`L1-L54`).
- Templates for bug, investigation and research; `.gitkeep` files.

**What it knew of its predecessor.** Nothing is cited (no hit in README,
`CLAUDE.md`, `ORCHESTRATOR.md`, `WORKFLOWS.md`, plans or architecture for any
earlier project). The commit skill it re-added mirrors the one OLD1 deleted
(inference, `5814436` the day after `3e71e2d`); its settings keep OLD1's
`attribution` block (`OLD2:.claude/settings.json:L2-L7`).

## Process and tooling

**Orchestrator brief hook.** A SessionStart hook that puts a file in front of
the main session only. SessionStart does not fire for subagents, so what it
injects is "orchestrator-private by construction" (`OLD1:.claude/orchestrator/
hooks/session-start.sh:L1-L7`); `CLAUDE.md`, the only file every agent loads,
is kept small for the same reason (`OLD1:CLAUDE.md:L3-L7`).

- OLD1: `session-start.sh` reads `BRIEFING.md` and emits a JSON
  `hookSpecificOutput.additionalContext`, appending a count of undrained
  subagent returns from `returns.jsonl` (`session-start.sh:L27-L72`). Verified
  on Claude Code 2.1.241 and 2.1.246 (`L15-L21`).
- OLD2: `orchestrator.sh` prints `ORCHESTRATOR.md` as plain text on `startup|
  resume|clear|compact` (`OLD2:.claude/settings.json:L9-L19`), then the output
  of `./todo -f TODO.json next` as "What should happen now", and exits 0 so a
  frozen state is text, not a failure (`OLD2:.claude/hooks/orchestrator.sh:
  L19-L45`). Plain text because a JSON payload "errors on the first message of
  a session" (claude-code#17550, `L10-L11`). This contradicts OLD1's local
  verification of the JSON form on 2.1.246; neither is rechecked here.
- Re-injection after compaction is why the brief is allowed to grow: "a router
  only loads when something decides to load it, and that decision is the first
  thing to go wrong in a degraded context" (`OLD2:.claude/ORCHESTRATOR.md:
  L7-L24`).

**Return capture (OLD1).** A `SubagentStop` hook appends every subagent return
to an append-only `returns.jsonl` so a finding the orchestrator skips is
"undrained rather than lost". Traps recorded in the hook header: `transcript_
path` is the main session's, `agent_transcript_path` the agent's; the hook can
fire more than once per agent; it fires for non-returns (`OLD1:.claude/
orchestrator/hooks/subagent-stop.sh:L17-L33`). The OLD1 queue then shows the
limits: only the last message is captured (`TODO.md:L495-L509`).

**The OLD2 harness.** Everything below is the machinery around an empty
library.

- Authorship: a short section in `CLAUDE.md` plus the commit skill's
  attribution paragraph and its message-anatomy file (`OLD2:CLAUDE.md:L3-L15`,
  `.claude/skills/commit/SKILL.md:L220-L222`). Three copies, no hook, no check;
  OLD1 had written that this exact pattern drifts.
- Bug inbox and freeze: any agent files one Markdown file per bug in
  `reports/bugs/` named `<timestamp with nanoseconds>-<slug>.md` ("needs no
  locking", `OLD2:CLAUDE.md:L17-L38`); only "a defect in something that already
  exists" counts, never a plan or a third-party defect (`L40-L52`); while any
  file is open, `plan-writer`, `contract-writer` and `code-writer` stop on
  `ls reports/bugs/2*.md` (`L54-L77`); closing is four steps: investigate in
  `reports/bug-fixes/<same name>`, fix, mark stale plans through a grep of the
  real diff, delete both files (`L79-L100`).
- Thirteen agents (`architecture-finder`, `architecture-writer`,
  `benchmark-writer`, `bug-investigator`, `code-reviewer`, `code-writer`,
  `contract-reviewer`, `contract-writer`, `plan-reviewer`, `plan-writer`,
  `researcher`, `test-hardener`, `test-writer`), each with an **Opens:** and
  **Writes:** pair under its first line, the rule being that nothing is read by
  default because "reading widely looks like diligence and costs like waste"
  (`OLD2:CLAUDE.md:L133-L158`). Reviewers have no Write or Edit tool so author
  and reviewer stay two opinions (`OLD2:.claude/agents/plan-reviewer.md:L9-L15`,
  `contract-reviewer.md:L16-L20`).
- Six workflows in `WORKFLOWS.md` (a map "not authority"; no agent reads it):
  design, freeze, build, verify, bug, blast radius, with three human gates
  (Tomas answers open questions; Tomas commits the contract; Tomas reads the
  diff) (`OLD2:WORKFLOWS.md:L3-L28`).
- Freeze and blind build: the contract is a Python file of signatures with
  `NotImplementedError` bodies; Tomas commits it and that sha is "the freeze";
  `test-writer` reads it with `git show <sha>:path` and never sees the
  implementation, `code-writer` fills in bodies and may not touch tests or
  `conftest.py`, and the two never share cases (`OLD2:.claude/ORCHESTRATOR.md:
  L327-L398`; `WORKFLOWS.md` BUILD). Hidden inputs in a signature (clock,
  global connection) are the first thing the contract reviewer checks.
- Verify ladder: the red run is the orchestrator's, in a worktree at the freeze
  sha with the new tests copied in, and it must print the resolved `__file__`
  of the package first because an editable install can resolve back to the
  main tree and silently measure the in-flight implementation (`ORCHESTRATOR.md:
  L400-L437`); the kind of failure is the signal (`NotImplementedError` or
  `AssertionError` is correct, `ImportError` or `TypeError` is a contract gap,
  a pass means the test asserts nothing) (`L431-L437`); then green run,
  `code-reviewer`, `test-hardener` (the one rung allowed to fail; expectations
  must come from a reference implementation, a metamorphic relation or a quoted
  rule, never from the code), `benchmark-writer`; Tomas's `/code-review`
  pass is user-triggered and billed, so the orchestrator never launches it.
- Services: `architecture-finder` and `researcher` are called mid-workflow and
  their answer is pasted into the next prompt, which is how an agent gets
  context it is not allowed to read (`ORCHESTRATOR.md:L462-L476`).
- A limit found on the way: the built-in Plan and Explore agents do not load
  `CLAUDE.md`, so they never learn the bug-filing rule; `plan-writer` stands
  in for Plan (`ORCHESTRATOR.md:L278-L286`).

**`./todo`, the task tracker (the bulk of the code).** `TODO.json` holds one
entry; the earlier 15 entries were frozen as `ORIGINAL_TODO.json` as a
"sandbox" for the redesign (`OLD2:TODO.json:notes[63]`, `notes[64]`). The
script is "the orchestrator's gate and sole writer", designed for an LLM
consumer: everything needed to act in one call, help text that carries the
rule behind each refusal, so docs cannot drift from enforcement
(`OLD2:TODO.json:spec`, `scripts/todo/__main__.py:L1-L9`). Python, standard
library only, chosen over bash+jq because Python "removes a toolchain rather
than adding one"; DuckDB and SQLite rejected for a 16-entry file (`notes[57]`,
`notes[67]`). Features: numeric ids that are never reused plus a `name` slug,
`needs`/`needed_by` dependency web with cycle refusal, `todo/doing/blocked/
done` where `todo` guarantees startable, `kind` of task, question or idea,
parked questions hidden by default, atomic temp-file-and-rename writes
(`scripts/todo/store.py:L1-L9`), a blocking and an advisory validation tier,
`stop`, a `fields` block generated from code. 12 commands. The reason for the
single writer: 20 concurrent `jq ... > TODO.tmp && mv` writers lost every
entry and left a zero-byte file (`ORCHESTRATOR.md:L254-L263`); and on 27
August `TODO.json` was renamed to a fragment of chat text mid-edit
(`store.py:L1-L9`, `ORIGINAL_TODO.json` entry `stray-todo-file`).

**The jq oracles.** The dependency logic first lived in jq: the reindex
(`needed_by`, the blocked/todo split) in `.claude/todo-reindex.jq`, and a cycle
detector written as a `reduce` fixpoint loop inside the session hook
(`OLD2:scripts/todo/graph.py:L1-L28`; `OLD2:.claude/hooks/orchestrator.sh:
L13-L17`). When it was ported to Python (`2d16843`, "with a differential
suite") the two jq files were kept as "FROZEN ORACLE"s under
`scripts/todo/tests/` and a `test_graph_vs_jq` compared outputs (`notes[83]`).

- The differential paid off at once: both jq files had the same bug, `index(f)`
  evaluating its argument against its own input, so the blocked/todo split
  worked only while nothing was `done` (`notes[76]`). Nothing had ever been
  `done`, so it went unseen.
- Lesson recorded: "identical output proves the port is faithful is only sound
  while the reference is correct". Write the port from what the code means,
  then diff (`notes[77]`).
- In the last commit (`29f0d36 refactor(todo): delete the jq oracles, and
  drop the migration from scope`) both were deleted, reversing the freeze
  decision an hour earlier. Reasons (`notes[1]`, `notes[2]`): Tomas asked what
  `reindex.jq` was for and "the fact that he could not tell from reading the
  repo was the argument"; their one job, proving the port, was done; what
  remained was "a second copy of the semantics nobody maintains"; keeping them
  was "a hedge".
- Deleting them immediately exposed a defect no differential could: replacing
  the oracle with properties over every fixture (reindex is idempotent,
  `needed_by` agrees with `needs`, `todo` means every dependency is satisfied)
  failed at once, because a phase-tagged entry with an unfinished need sat on
  `todo`. The old jq had the same bug, so the differential "would have agreed
  with itself forever". "A property that states the invariant catches what a
  second implementation of the same misunderstanding cannot" (`notes[2]`).
  `test_graph.py` now says it "is the whole definition" (`OLD2:scripts/todo/
  tests/test_graph.py` docstring).

**Scripts, in one line each** (skimmed, not read in full): `__main__.py` is the
CLI and holds the help text; `store.py` loads and atomically saves
`TODO.json`; `graph.py` computes `needed_by`, status, stuck entries, chains and
cascade delete; `edit.py` the five write operations and their refusals;
`query.py` filters, keyword search and "similar to"; `checks.py` repo
conditions (open bug reports, orphaned investigations, stray JSON, stale
index); `gate.py` the ordered decision behind `next`; `render.py` the text
output. Tests: `cases.py` builds edge-case documents, `conftest.py` puts
`scripts/` on the path, and one file each for chains (the most important),
checks, CLI, edit, gate, graph, hook (runs the shell hook), ideas, query,
scenario (the freeze walked end to end), store. `todo` is the 10-line entry
script.

**Method notes recorded by the work.** Of seven bugs found building `./todo`,
none was found by a test written from the same mental model as the code: three
came from running commands by hand and reading the output, two from chasing a
failing test, two from Tomas asking why something was so (`notes[8]`). `kind:
bug` was removed after it made a prepended bug entry invisible to the gate
forever (`notes[13]`).

## History (both, phases with dates and shas)

OLD1, 26 August, 47 commits, oldest first:

- Authorship and roster: `3add633` enforce sole authorship at commit time;
  `81b8958` commit protocol and shared invariants; `2d43110` coordinator,
  committer, curator, auditor; `7f4d0b0` inject the briefing into the main
  session; `b662a3a` the work queue.
- Queue and agent fixes: `17a18bd` to `d2dd787` (offending line on rejection;
  delete completed rows; restore rules the queue depends on; `4150633` records
  that `git log` misstates the preamble deletion; the curator and auditor
  fixes; commit counts replaced by a standing rule; regroup by state).
- Rules and capture: `5742801` to `3866257` (authorship notes, whole-file diffs
  after scripted edits, dissolve the settled section; `dcfc95f` capture every
  subagent return, `8186e9f` report undrained returns, `574a461` ignore the
  log, `0ffddcf` require draining).
- Research and recording: `fedb4f1` to `55fb562` (unexplained firings, correct
  the versioning rows, deny rules stop accident, what `skills:` preloads, two
  gaps in capture, `70c7bd0` capture without fixing on sight).
- Decisions and removal: `8bd43a1`, `69c7ee0` the decided capture and review
  architecture, `3e71e2d` the commit-message skill, `a0ae28d` two findings,
  `3528d48` remove the git roster, commit protocol and hooks, `e5d918a` record
  what the removal left open.

OLD2, 27 to 30 August, 68 commits (26, 6, 19, 17 per day):

- 27 August, set-up: `26a2e7b` project instructions and orchestrator brief hook;
  `5814436` commit skill; `35e147a` inject once per session; `3f35c3f`
  `TODO.json`; `de834a0` record what sql_learn is and replaces.
- 27 August, pipeline: `e15b9a5` bug inbox that freezes new work; `53d6d1a`
  plan-writer; `0cf4116` benchmarks home; `401bc7c` plan-reviewer; `be2e938`
  investigate before fixing; `7ee1b8c`, `c3440f6`, `c6c587e` the stray-rename
  incident and guard; `ab20ca3` reviews on disk beside plans; `648aee8` agents
  read nothing they were not asked to; `88b250a` the estimator contract plan and
  its review; `0985f6f` DuckDB relation limits research; `61c7a0b`, `5e17d26`,
  `68dc69b` decisions and the roster; `ca62328` Opens/Writes; `dea3aa0`
  `architecture/`; `d1bc677` contract-writer; `1fb7a41` reviews home.
- 28 August: `ae7e46c` the nine remaining agents; `c02ad8d` `pyproject.toml`,
  src layout, ceilinged DuckDB pin; `3f92d56` stop tracking build artefacts;
  the rest `chore(todo)` entries.
- 29 August, workflows and the redesign: `4d88557` six workflows encoded into
  the roster; `daeaabc`, `5df1f2b` park library design behind a marker only
  Tomas closes; `45c5789` surface entries that can never unblock; `928fb43`
  the two reviewers; `9c4e8f6` test-hardener rewritten as the sighted pass;
  `bdf77c1`, `37f8454` bidirectional dependency web; `0a6417b` freeze
  `TODO.json` and open a sandbox; `bc95cbc` rule out MCP; `0bf54cd` specify
  `./todo` in ten commands.
- 30 August, the script: `b1c1e64`, `2d16843` Python port with differential
  suite; `af6cfd5` pytest; `b857991`, `ea78dbd` read and write halves;
  `65072f0` chains and cycle refusal; `9ee8f1a` the gate; `820ecdf` hook runs
  `./todo next`; `aee5531` schema validation in two tiers; `9222e2f` `kind:
  idea`; `4f07d70` self-describing fields, drop `kind: bug`; `6410d82`,
  `12847e0` rewrite the TODO section, add `stop`; `29f0d36` delete the jq
  oracles and drop the migration. Last commit.

Why each stopped is not stated (inference): OLD1 stopped when its roster was
judged slower than the work and had to be rebuilt through its own new design;
OLD2 stopped at a clean boundary (the resume point reads "WORKING TREE CLEAN,
388 tests passing, none skipped, no open bugs", `notes[3]`) with the library
parked and the tracker still the product. The next dated attempt in the
README table is `sqlearn` of 30 September to 4 October (not read here).

## Bearing on the four open questions

**fit-execution-model.** OLD2 is the first evidence on the "lazy fit" idea.
- The plan assumes `Pipeline.fit` "threading one relation through each step
  with no execution between steps" (step 10) while asking, in Open 5, whether
  `fit` executes at all. The reviewer calls this a buried decision and shows
  that the lazy answer is the expensive one: relation text and scans grow about
  4x and 2x per step for aggregate-then-join-back transforms
  (`OLD2:plans/review-estimator-contract.md:L88-L115`, `L171-L177`). A fit that
  executes between steps, or SQL text that shares CTEs (the open question
  "string building could share CTEs where the relation API does not",
  `OLD2:ORIGINAL_TODO.json`, entry `q-sql-text-vs-relation-api`), avoids it.
  This does not contradict the baseline's "staged fit can be one query with
  WITH clauses"; it argues that the relation API is the wrong way to compose it
  (inference).
- Fitted state as a lazy relation re-fits on every execution, so a changed
  base table silently changes a "fitted" model (10, 110, 1110)
  (`OLD2:plans/estimator-contract.md:L103-L115`). New against the baseline,
  which lists attributes, relations-for-CV and tables only.
- Five candidates for state are listed and all verified: Python attributes,
  lazy relation, real table, TEMP table, macro; a macro is the only one whose
  definition reads back as SQL (`L336-L356`, `L165-L187`). None chosen.
- `inf` and `nan` do not survive as bare SQL literals; a zero-variance column
  produces one (`L123-L127`, step 8 at `L284-L288`). The baseline says no
  attempt handled NaN; OLD2 handled the literal, not the NaN-versus-NULL
  aggregate behaviour.
- The Impute-then-Scale defect is not mentioned. The plan's first estimator is
  a scaler alone (step 13), so the case never arose (inference).
- "What does one massive SQL promise": OLD2 never states it; README says only
  that the work stays in SQL.

**multi-engine-support.** Little, all negative. README calls DuckDB "primary
target" (`OLD2:README.md:L5`) and the plan notes this "implies other backends
without naming any", and that "no non-DuckDB backend was tested"
(`OLD2:plans/estimator-contract.md:L223-L225`). Open 3 says a raw
`DuckDBPyRelation` in the public signature makes a second backend a breaking
change (`L358-L364`); Open 7 says hand-built SQL means the library owns
"generation, quoting and dialect, which is most of what a second backend would
need anyway" (`L394-L399`). No sqlglot anywhere in either folder, and the only
dependency is `duckdb`. Consistent with ADR 0004; contradicts the baseline line
that every attempt used sqlglot (see below).

**scikit-learn-api-survey.** README keeps the shape: `fit`, `transform`,
`predict`, composable pipelines, search and model selection
(`OLD2:README.md:L7-L9`). The plan settles `fit` returns `self` so `Pipeline`
and chaining work (step 5), leaves `(X, y)` versus relation-plus-target-column
open with the SQL reason (no positional alignment, so two relations need a key
and a mistake mislabels silently) (`L328-L334`), and the review notes that
`predict`, `fit_transform`, search and model selection have no step
(`OLD2:plans/review-estimator-contract.md:L227-L236`). No `get_params`,
`clone`, `set_output` or feature names are discussed. Confirms the baseline
that `y` as a column name is the natural departure and needs an ADR.

**validation-method.** Rules, no runs. `benchmark-writer` records "numbers, not
a verdict", full divergence, versions, and a command (`OLD2:.claude/agents/
benchmark-writer.md`; `reports/benchmarks/README.md:L17-L21`); `test-writer`
takes expectations from "a reference implementation" or the spec, never from
the code under test; `test-hardener` adds metamorphic relations and may not
read the code to choose what to assert. scikit-learn and the others are a
test-only extra (`pyproject.toml:L22-L32`). No exact (`Fraction`) reference,
no iterative-algorithm rule, no error table, no benchmark ever run. The one
new methodological fact is the oracle trap: a reference implementation that
shares the code's misunderstanding makes a differential agree "with itself
forever", and a property stating the invariant found the defect (`notes[2]`,
`notes[77]`). That is a reason to check scikit-learn's own output against an
invariant, not only against sqlearn.

## New against the baseline

- Relation `sql_query()` text and scan counts grow geometrically for any step
  that reads its input twice; no CTE sharing; the guard on
  `max_expression_depth` watches the wrong limit (DuckDB 1.5.5; recheck on
  2.0.0).
- A relation exposes no connection, so the working handle is
  `(relation, connection)`; relations cannot be pickled or shared across
  connections or cursors.
- Duplicate column names resolve silently to the first match once a join is a
  subquery, giving a wrong answer with no error.
- `params=` on a relation executes and materialises, so bind parameters are no
  lazy way to carry fitted values.
- `profiling_output` is one overwritten file; counting queries that way fails.
  The frame and arrow members of a relation run the query, then fail without
  their library.
- `read_only=True` rejects `CREATE TABLE` and non-temp macros; TEMP tables are
  per connection; relation-created views cannot be read back as SQL; macros
  can.
- `row_number() OVER ()` costs 5.7x to 7.2x on a scan, not 2x.
- Fitted state as a lazy relation is a design option, shown to refit silently.
- The oracle trap and the property fix (see validation-method above).
- A ceiling pin on DuckDB (`<1.6`) justified by undocumented internals. The
  repository's ADRs do not say if a ceiling is wanted.
- A sole-writer, single-gate task tracker with a self-describing schema; a
  bug-freeze rule; the blind-build ladder and its red-run traps (editable
  install resolving to the wrong tree). Process, not library.
- Built-in Plan and Explore agents do not load `CLAUDE.md`; SessionStart fires
  for the main session only; `skills:` frontmatter preloads full skill content
  (OLD1 research, `OLD1:TODO.md:L544-L563`, to be verified).
- Both restarts show the cost of letting agents build commit machinery: 10.5
  minutes to commit one file (`OLD1:TODO.md:L76-L78`).

## Contradicts the baseline

- "Every attempt used sqlglot": OLD2 has none; it plans on DuckDB's relation API
  or hand-built SQL and has only `duckdb` as a dependency (`pyproject.toml`
  L19). It never built the expression layer, so this is a plan, not a test.
- "No attempt handled NaN": OLD2 handled `inf` and `nan` as SQL literals (step
  8) though not their aggregate behaviour. A partial correction.
- ADR 0007 (Python 3.12 floor) and "tests run through just": OLD2 uses Python
  `>=3.11` and `./todo`, not a task runner. Not a baseline claim; noted for
  the decisions.

## Confirms the baseline

- Harness and process outgrew the product, and status kept by hand in several
  places drifted (`OLD1:TODO.md:L452-L477` rows describing a deleted roster;
  `OLD2` bug `workflows-map-shows-removed-kind`).
- A different agent reading the work found what self-verification passed
  (`OLD1:TODO.md:L80-L91`; `OLD2:plans/review-estimator-contract.md` finding
  that four "verified" claims were wrong).
- A deterministic checker stopped drift where prose rules had not: `./todo
  check` and the gate; OLD1's behavioural-test hook before deletion.
- Hand-typed numbers rot: OLD1 replaced commit counts with a standing rule
  (`bcab369`) and says "derive counts from the array, do not recall them"
  (`TODO.md:L393-L398`).
- Validation: a strong method written and never enforced; scikit-learn as test
  reference; no whole-pipeline comparison and no run.
- A learning step reading a value an earlier step changed was not even raised;
  the first estimator was a single scaler, so fit-order defects had no chance
  to show (inference).
- `fit` taking a target as a column name is the natural departure.
- DuckDB `ATTACH` or federation: not touched; ADR 0004 (one dependency) matches
  OLD2's choice.

## Worth keeping

- The relation-limits findings, as tests to run on DuckDB 2.0.0 before they
  are trusted: text growth with a scaler chain, duplicate-column silent
  resolution, `profiling_output` single file, refit of a held relation,
  `params=` materialising, `inf` and `nan` literals, `rowid` only on tables,
  `row_number() OVER ()` cost at three sizes. The commands are in the review.
- A fit design must not rely on relation-API composition between steps; either
  execute per stage or build text with shared CTEs.
- The oracle-trap lesson and the property-over-fixtures fix, for the validation
  spec.
- Blind test-writing from a frozen contract, the red-run-in-a-worktree check
  with the printed package path, and reading the kind of failure as the signal.
- File-per-report for concurrent writers (nanosecond name, no locking); the
  atomic temp-file-and-rename write; a sole writer for a shared file.
- A stale architecture page is worse than none: write it only after the thing
  exists, with `covers:` and `files:` so a diff finds it.
- Plan versus architecture split; review files beside plans, overwritten each
  round; a plan is never a bug.
- A `Opens:` and `Writes:` pair per agent as the first line of its definition.
- Whole-file diff after any scripted edit; a false PASS is worse than a false
  FAIL.
- "A decision made but not built is not done" as an explicit state.

## Guard against

- Building the machinery that builds the library before any library: OLD1 had
  zero library files in 47 commits, OLD2 three library commits in 68.
- Letting an agent do commits: 10.5 minutes for one Markdown file, and the
  authorship rule ended up unenforced (`OLD1:CLAUDE.md:L45-L56`).
- A rule stated in three files; the one place all agents load (`CLAUDE.md`) is
  the only reliable home, and a check is the only thing that proves it holds.
- A phase marker that only Tomas can close, used to park every library
  question: the project then runs forever in its "current phase", the machinery
  (`OLD2:.claude/ORCHESTRATOR.md:L131-L159`).
- A tracker rebuilt in Python with 388 tests while GitHub Issues exist; OLD1's
  planned `issues/` mirror of GitHub issues (inference; this repository uses
  GitHub Issues, `docs/agents/issue-tracker.md`).
- A "read-only" bug rule that freezes everything: four "blocks" bug reports on
  the tracker itself would freeze a project; filing needs a severity release
  (OLD1 row 2 had one, `TODO.md:L130-L141`; OLD2 does not).
- A differential against an old implementation as the only check of a port.
- Plans with measured claims taken as fact: four of the plan's "verified"
  claims were wrong when re-run (`review L25-L84`).
- A floor-only dependency pin where undocumented internals are used.
- Unverified citations driving a design change (OLD1's "42% miss rate" with
  issue numbers never checked, `TODO.md:L519-L533`).

## Files covered

[x] read, [~] skimmed. A git log counts as one file. Generated and local files
(`.venv/`, 632 files, `.pytest_cache/`, `__pycache__/`, `.DS_Store`) were
counted,
not read, except `.pytest_cache/v/cache/lastfailed` (two failing test ids, one
about help output and one about an empty title).

OLD1 (8 files and the log):

- [x] `OLD1:CLAUDE.md`: authorship rule, "not enforced", no agents or skills.
- [x] `OLD1:TODO.md`: 653 lines read in full; the queue and all research rows.
- [x] `OLD1:.gitignore`: ignores the returns log and Python artefacts.
- [x] `OLD1:.claude/settings.json`: attribution block plus two orchestrator
  hooks; no permissions block.
- [x] `OLD1:.claude/orchestrator/BRIEFING.md`: the main-session brief.
- [~] `OLD1:.claude/orchestrator/returns.jsonl`: 195 rows parsed; the 14
  subagent returns read in their first 350 characters, 181 `unknown` rows
  sampled.
- [x] `OLD1:.claude/orchestrator/hooks/subagent-stop.sh`: capture hook.
- [x] `OLD1:.claude/orchestrator/hooks/session-start.sh`: briefing injection.
- [x] `sql_learn_27.08.2026-git-log.txt` (scratchpad): 47 commits, 26 August.

OLD2 root and library:

- [x] `OLD2:README.md`: the goal and the Early status.
- [x] `OLD2:CLAUDE.md`: authorship, bug filing, freeze, read scope.
- [x] `OLD2:WORKFLOWS.md`: six workflows and routing table.
- [~] `OLD2:TODO.json`: single entry, 85 notes; notes 0 to 3, 8, 13, 76, 77, 83
  read in full, the rest to about 330 characters; the `spec` field's first
  1,500 characters.
- [~] `OLD2:ORIGINAL_TODO.json`: 15 entries, titles and first two notes each (to
  about 420 characters); the eight parked questions read there.
- [x] `OLD2:todo`: 10-line entry script.
- [x] `OLD2:pyproject.toml`: duckdb ceiling, test extra.
- [x] `OLD2:.gitignore`.
- [x] `OLD2:src/sql_learn/__init__.py`: docstring only.
- [x] `OLD2:tests/.gitkeep`: empty.
- [x] `OLD2:architecture/README.md`.
- [x] `OLD2:architecture/TEMPLATE.md`.
- [x] `OLD2:plans/estimator-contract.md`.
- [x] `OLD2:plans/review-estimator-contract.md`.
- [x] `OLD2:plans/TEMPLATE.md`.
- [x] `OLD2:plans/TEMPLATE-review.md`.

OLD2 reports (15 files):

- [x] `OLD2:reports/research/2026-08-27-duckdb-relation-limits.md`.
- [x] `OLD2:reports/research/2026-08-29-mcp-in-web-and-cloud-sessions.md`.
- [x] `OLD2:reports/bugs/20260831-000459-913731000-concurrent-set-silently-
  loses-writes.md`.
- [x] `OLD2:reports/bugs/20260831-000529-044960000-set-rename-crashes-after-
  writing.md`.
- [x] `OLD2:reports/bugs/20260831-000529-051256000-field-flag-bypasses-every-
  validator.md`.
- [x] `OLD2:reports/bugs/20260831-000622-631470000-workflows-map-shows-removed-
  kind.md`.
- [x] `OLD2:reports/benchmarks/README.md`.
- [x] `OLD2:reports/reviews/README.md`.
- [x] `OLD2:reports/TEMPLATE-bug.md`.
- [x] `OLD2:reports/TEMPLATE-investigation.md`.
- [x] `OLD2:reports/TEMPLATE-research.md`.
- [x] `OLD2:reports/bug-fixes/.gitkeep`: empty.
- [x] `OLD2:reports/bugs/.gitkeep`: empty.
- [x] `OLD2:reports/research/.gitkeep`: empty.
- [x] `OLD2:reports/reviews/.gitkeep`: empty.

OLD2 `.claude/` (21 files):

- [x] `OLD2:.claude/ORCHESTRATOR.md`: the orchestrator brief.
- [x] `OLD2:.claude/hooks/orchestrator.sh`: injects the brief and `./todo next`.
- [x] `OLD2:.claude/settings.json`: attribution, one SessionStart hook.
- [x] `OLD2:.claude/agents/architecture-finder.md`.
- [x] `OLD2:.claude/agents/architecture-writer.md`.
- [x] `OLD2:.claude/agents/benchmark-writer.md`.
- [x] `OLD2:.claude/agents/bug-investigator.md`.
- [x] `OLD2:.claude/agents/code-reviewer.md`.
- [~] `OLD2:.claude/agents/code-writer.md`: first 60 lines.
- [~] `OLD2:.claude/agents/contract-reviewer.md`: first 60 lines.
- [~] `OLD2:.claude/agents/contract-writer.md`: first 60 lines.
- [~] `OLD2:.claude/agents/plan-reviewer.md`: first 60 lines.
- [~] `OLD2:.claude/agents/plan-writer.md`: first 60 lines.
- [~] `OLD2:.claude/agents/researcher.md`: first 60 lines.
- [~] `OLD2:.claude/agents/test-hardener.md`: lines 1 to 140.
- [~] `OLD2:.claude/agents/test-writer.md`: first 60 lines.
- [~] `OLD2:.claude/skills/commit/SKILL.md`: header, workflow, attribution
  paragraph (L215-L235); a generic Conventional Commits skill.
- [~] `OLD2:.claude/skills/commit/reference/examples.md`: heading list.
- [~] `OLD2:.claude/skills/commit/reference/message-anatomy.md`: heading list,
  attribution lines (L142, L169).
- [~] `OLD2:.claude/skills/commit/reference/special-cases.md`: heading list.
- [~] `OLD2:.claude/skills/commit/reference/types-and-scopes.md`: heading list.

OLD2 `scripts/todo/` (22 files, all skimmed by docstring and header):

- [~] `scripts/todo/__init__.py`: one-line docstring.
- [~] `scripts/todo/__main__.py`: CLI and help texts.
- [~] `scripts/todo/checks.py`: repo conditions (bugs, orphans, stray JSON).
- [~] `scripts/todo/edit.py`: write operations and refusals.
- [~] `scripts/todo/gate.py`: the ordered `next` decision.
- [~] `scripts/todo/graph.py`: dependency web, reindex, stuck, cascade delete.
- [~] `scripts/todo/query.py`: filters, search, similar-to, parking.
- [~] `scripts/todo/render.py`: text output.
- [~] `scripts/todo/store.py`: atomic load and save.
- [~] `scripts/todo/tests/cases.py`: edge-case documents.
- [~] `scripts/todo/tests/conftest.py`: path set-up.
- [~] `scripts/todo/tests/test_chains.py`.
- [~] `scripts/todo/tests/test_checks.py`.
- [~] `scripts/todo/tests/test_cli.py`.
- [~] `scripts/todo/tests/test_edit.py`.
- [~] `scripts/todo/tests/test_gate.py`.
- [~] `scripts/todo/tests/test_graph.py`.
- [~] `scripts/todo/tests/test_hook.py`.
- [~] `scripts/todo/tests/test_ideas.py`.
- [~] `scripts/todo/tests/test_query.py`.
- [~] `scripts/todo/tests/test_scenario.py`.
- [~] `scripts/todo/tests/test_store.py`.
- [x] `sql_learn-git-log.txt` (scratchpad): 68 commits, 27 to 30 August.
