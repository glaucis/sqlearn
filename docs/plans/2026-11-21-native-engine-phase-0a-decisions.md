---
type: adr
tags: [native-engine, duckdb, cpp, decisions, phase-0a]
summary: "Implementation plan recording the native engine's nine decisions as ADRs 0060-0068, with amendments to older ADRs and CLAUDE.md rules."
related: [docs/specs/native-engine.md, docs/plans/2026-11-21-native-engine-phase-0b-inventory.md, docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md, docs/adr/0002-sql-on-duckdb-execution-engine.md, docs/adr/index.md, docs/questions/multi-engine-support.md, CLAUDE.md, docs/adr/0061-sqlearn-ships-its-own-duckdb-build.md]
mdindex: [type=0fc814, tags=38e4ea, summary=81c817, related=e608c3]
---
# Native engine, Phase 0a: the decisions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** record the native engine's nine decisions as ADRs 0060 to 0068,
with their amendments to older ADRs and to `CLAUDE.md`'s rules in the same
commits, and bring the overview, the layout page, the glossary and the open
questions in line with them.

**Architecture:** documentation only, no code. One task per ADR: write the
record from the spec's §3.N, add one "Amended by" sentence to each ADR it
amends, change the `CLAUDE.md` rule lines it changes (exact wording below),
and list it in `docs/adr/index.md`. Then the overview, the layout page and
the glossary follow the records.

**Tech Stack:** Markdown (MyST) on the Sphinx site; `just` (`fmt`, `check`,
`test`, `build-docs`); `git`; `gh`.

**Spec:** `docs/specs/native-engine.md` (approved 2026-11-21), §1, §3 and
§5.2 to §5.6. Read it beside this plan; section numbers below are the
spec's. Phase 0's issue is #78. The second plan,
`docs/plans/2026-11-21-native-engine-phase-0b-inventory.md`, runs after this
one on the same branch and closes Phase 0.

## Global Constraints

- All work on the branch `engine-phase-0`, in the worktree
  `.worktrees/engine-phase-0`, made from `main` at or after `e0f1a7d` with
  superpowers:using-git-worktrees.
- Every task runs through `just`; Python through `uv run`, never pip or a
  bare `python` (ADR 0001, 0008).
- British English in prose, American spelling in identifiers (ADR 0010).
  Short sentences, in the house style of the existing ADRs: `# NNNN: Title`,
  a `Status:` paragraph, then `## Context`, `## Decision`, `## Consequences`.
  What was weighed and lost goes in Context, as in ADR 0058.
- Each new ADR's Status paragraph is exactly: `Status: accepted (2026-11-21).
  Decided by Tomas on 2026-11-21 with the [native engine
  spec](../specs/native-engine.md) (§3.N).`, then, for each ADR it amends,
  `Amends [ADR NNNN](NNNN-file-name.md).`
- An amended ADR changes in one place only: one sentence added at the end of
  its Status paragraph, `Amended by [ADR 00NN](00NN-file-name.md)
  (2026-11-21): <clause>.`, with the clause this plan gives. The only other
  edit allowed in an accepted ADR is a link that would break (Task 3).
- An ADR records what the spec decided and nothing more. Every bullet of its
  Decision traces to the spec's §3.N; what the spec marks "the agent's call"
  stays marked so.
- `CLAUDE.md`'s rules change in the same commit as the ADR that changes them,
  with the exact wording given here.
- Before every commit: `just fmt`, `just check`, `just test`, and
  `just build-docs` (the ADRs and the overview are on the site, and the build
  fails on a broken link; it takes several minutes). Name every failure.
- Stage only the files the task lists, and read `git diff --cached` before
  committing. The docs tagger writes frontmatter into Markdown files: keep it
  on files this branch creates, leave its edits to existing files out of the
  commit (`git add -p`), and never write an `mdindex:` line by hand.
- Commits: Conventional Commits, no scope but `hooks`, `site`, `deps`; header
  and body lines at most 72 characters; `(#78)` in the header; no AI
  attribution, no `Co-Authored-By`. Never `--no-verify`; never a bare
  `git stash` (the stash is shared by every worktree).

## Review Focus

1. **A link that breaks:** the deleted site-hosting question, an ADR file
   named other than this plan names it, or the inventory page, which exists
   only after plan 0b. `just build-docs` runs in every task, and Task 3 greps
   for what is left.
2. **`CLAUDE.md` contradicting an ADR at any commit:** each rule changes with
   its ADR, and Task 11 reads every rule line against the ADRs it cites.
3. **The docs tagger's edits slipping into a commit:** frontmatter changes to
   existing files stay out; `git diff --cached` is read before each commit.
4. **An ADR deciding more than the spec:** the task's reviewer reads each
   Decision against §3.N; anything the spec does not say is cut, or put back
   to Tomas.
5. **An amended ADR rewritten:** each amended ADR's diff shows the one added
   sentence, and nothing else but Task 3's link.

---

### Task 0: The branch and the handoff

**Files:**
- Modify: `HANDOFF.md`

- [ ] **Step 1:** Make the worktree `.worktrees/engine-phase-0` on a new
  branch `engine-phase-0` from `main` (superpowers:using-git-worktrees), and
  run `just setup` in it.
- [ ] **Step 2:** In `HANDOFF.md`, under "In progress", replace "None." with:
  "- Phase 0 of the native engine (#78), branch `engine-phase-0`: plan 0a
  (the decisions) running, then plan 0b (the inventory). Spec
  `docs/specs/native-engine.md`." Set the "Updated:" line's branch to
  `engine-phase-0`.
- [ ] **Step 3:** `just fmt`, `just check`, `just test` pass. Commit
  `docs: start Phase 0 of the native engine (#78)`.

### Task 1: ADR 0060, the engine

**Files:**
- Create: `docs/adr/0060-a-native-engine-in-cpp-inside-duckdb.md`
- Modify: `docs/adr/0002-sql-on-duckdb-execution-engine.md` (Status),
  `docs/adr/index.md`, `docs/questions/multi-engine-support.md`, `CLAUDE.md`

**Interfaces:**
- Produces: the file name above, which later tasks and plan 0b link to; the
  index topic "The native engine", which Tasks 2 to 9 append to.

- [ ] **Step 1: Write the ADR**, titled `# 0060: A native engine in C++,
  inside DuckDB`, from spec §1 and §3.1.
  - Context: what there is today (only the Gram learn computes in Python;
    the rest is SQL in DuckDB; Python finishes a few numbers), what SQL does
    badly (wide aggregates, missing functions), and why C++ over Rust. What
    was weighed: DuckDB's stable C API, Rust, a binding layer.
  - Decision: §3.1's bullets, the speed-first rule for apply and its
    plain-SQL twins included.
  - Consequences: the generated SQL can always be inspected, and runs in any
    DuckDB where its plain twin exists; a pipeline whose apply has no twin
    says it needs sqlearn's DuckDB; the compositor stays the one renderer
    (ADR 0015); each DuckDB release costs an upgrade branch (ADR 0061).
- [ ] **Step 2: Amend ADR 0002.** Add to its Status paragraph: "Amended by
      [ADR 0060](../adr/0060-a-native-engine-in-cpp-inside-duckdb.md)
      (2026-11-21): the native engine's C++ functions join DuckDB's own, reached
      only through SQL."
- [ ] **Step 3: The index.** In `docs/adr/index.md`, after the section
  "Execution in DuckDB", add:

  ```markdown
  ## The native engine

  sqlearn's computation in C++, inside its own DuckDB build.

  - [0060: A native engine in C++, inside DuckDB](0060-a-native-engine-in-cpp-inside-duckdb.md)
  ```

- [ ] **Step 4: The multi-engine question.** At the end of
  `docs/questions/multi-engine-support.md`, add a section "## Tomas's intent,
  2026-11-21": a later option such as `engine="postgresql"`, chosen when
  training, through a translator (sqlglot or another). Nothing is written for
  other engines now. ADR 0060 keeps the option open: the compositor stays the
  one renderer, and every engine function used in apply keeps a plain-SQL twin
  where one exists. Learning on another engine would run without the native
  engine's functions.
- [ ] **Step 5: `CLAUDE.md`.** Replace the rule "Computation is SQL executed
  by DuckDB; Python is the glue (0002). The one exception: a Gram step's
  learn, where numpy sums XᵀX from batches DuckDB streams (0058)." with:

  ```markdown
  - Computation runs inside DuckDB: SQL, and the native engine's C++
    functions (`sqlearn_*`), which Python reaches only through the SQL it
    builds (0002, 0060). Apply SQL may call the engine where a benchmark
    shows it faster; each such function keeps a plain-SQL twin where one
    exists. Until the engine's Phase 2, a Gram step's learn sums XᵀX in
    numpy from batches DuckDB streams (0058).
  ```

- [ ] **Step 6:** `just fmt`, `just check`, `just test`, `just build-docs`
  pass, and ADR 0002's diff is the one sentence. Commit
  `docs: record the native engine as ADR 0060 (#78)`.

### Task 2: ADR 0061, sqlearn's own DuckDB build

**Files:**
- Create: `docs/adr/0061-sqlearn-ships-its-own-duckdb-build.md`
- Modify: `docs/adr/0005-runtime-dependencies.md`,
  `docs/adr/0006-local-and-offline.md`,
  `docs/adr/0057-numpy-is-a-runtime-dependency.md` (Status each),
  `docs/adr/index.md`, `CLAUDE.md`

- [ ] **Step 1: Write the ADR**, titled `# 0061: sqlearn ships its own DuckDB
  build`, from §3.2.
  - Context: why bundle (signing and version matching avoided; full control;
    the drop-in keeps users' code and the tests; two packages for releases
    and daily builds, at the same speed), and what was weighed (the official
    DuckDB with the engine loaded, a private name, one package).
  - Decision: every bullet of §3.2, the accepted cost and its ways round
    included.
  - Consequences: one DuckDB shared by the user and sqlearn; no package that
    needs the official `duckdb` in the same environment; an upgrade branch
    per DuckDB release; DuckDB's third-party code in sqlearn's builds (ADR
    0066).
- [ ] **Step 2: Amend three ADRs**, one sentence each at the end of the
  Status paragraph:
  - 0005: "Amended by
    [ADR 0061](../adr/0061-sqlearn-ships-its-own-duckdb-build.md) (2026-11-21):
    sqlearn's own DuckDB build replaces `duckdb` from PyPI."
  - 0006: "Amended by
    [ADR 0061](../adr/0061-sqlearn-ships-its-own-duckdb-build.md) (2026-11-21):
    sqlearn's DuckDB never downloads an extension by itself; one the user
    installs works."
  - 0057: "Amended by
    [ADR 0061](../adr/0061-sqlearn-ships-its-own-duckdb-build.md) (2026-11-21):
    numpy stays until the engine's linear algebra (Phase 3), when this is
    decided again."
- [ ] **Step 3:** Append `- [0061: sqlearn ships its own DuckDB
  build](0061-sqlearn-ships-its-own-duckdb-build.md)` to the index's "The
  native engine".
- [ ] **Step 4: `CLAUDE.md`.** Replace the rule "The runtime dependencies are
  `duckdb` and `numpy`; any other needs a written reason and a permissive
  licence (0004, 0005, 0057)." with:

  ```markdown
  - sqlearn runs on its own DuckDB build: the `duckdb` module, built from
    DuckDB's source at a pinned release with the engine compiled in, shipped
    as a second package beside sqlearn. With numpy it is the whole runtime;
    anything else needs a written reason and a permissive licence (0004,
    0005, 0057, 0061).
  ```

  and the rule "Nothing needs the network: no telemetry, no cloud, data never
  leaves the machine (0006)." with:

  ```markdown
  - Nothing needs the network: no telemetry, no cloud, data never leaves the
    machine. sqlearn's DuckDB never downloads an extension by itself; one the
    user installs works (0006, 0061).
  ```

- [ ] **Step 5:** `just fmt`, `just check`, `just test`, `just build-docs`
  pass, and each amended ADR's diff is its one sentence. Commit
  `docs: record sqlearn's own DuckDB build as ADR 0061 (#78)`.

### Task 3: ADR 0062, the platforms, and the site-hosting answer

**Files:**
- Create: `docs/adr/0062-apple-silicon-first.md`
- Modify: `docs/adr/0009-sphinx-documentation-site.md` (Status, one
  Consequences bullet, its frontmatter `related`),
  `docs/architecture/overview.md` (§2's "One static site" bullet),
  `docs/specs/foundation.md` (one link, its frontmatter `related`),
  `docs/adr/index.md`, `CLAUDE.md`
- Delete: `docs/questions/site-hosting.md`

- [ ] **Step 1: Write the ADR**, titled `# 0062: Apple silicon first, a safe
  CPU build elsewhere`, from §3.3.
  - Context: Tomas's reasons (unified memory; Apple users miss out today);
    the platforms DuckDB itself builds for; why not macOS 14 or 26.
  - Decision: every bullet of §3.3, with the public repository: CI and code
    scanning are free, and the site is served by GitHub Pages from it. That
    answers the site-hosting question.
  - Consequences: Phase 1's CI covers five platforms; validation results are
    kept per platform; Apple-only code paths are allowed where a benchmark
    and the tests back them; #4 and #6 follow Phase 1's CI.
- [ ] **Step 2: Amend ADR 0009.**
  - Add to its Status paragraph: "Amended by
    [ADR 0062](../adr/0062-apple-silicon-first.md) (2026-11-21): the repository
    is public, and the site is served by GitHub Pages from it."
  - Replace its Consequences bullet "Hosting while the repository is private is
    open: [questions/site-hosting.md](../adr/0062-apple-silicon-first.md)." with
    "Hosting while the repository was private was open;
    [ADR 0062](../adr/0062-apple-silicon-first.md) settles it: the repository is
    public."
  - In its frontmatter, replace `docs/questions/site-hosting.md` in `related`
    with `docs/adr/0062-apple-silicon-first.md`.
- [ ] **Step 3: Move the answer, delete the question** (the questions
  folder's rule).
  - In the overview's §2 bullet "One static site", replace "The repository is
    private, and GitHub Pages serves a private repository only on a paid plan.
    Open: [questions/site-hosting.md](../adr/0062-apple-silicon-first.md)." with
    "The repository is public (2026-11-21), and Pages serves the site from it,
    deployed with the CI the native engine's Phase 1 sets up
    ([ADR 0062](../adr/0062-apple-silicon-first.md); #4, #6)."
  - In `docs/specs/foundation.md`, replace
    "([questions/site-hosting.md](../adr/0062-apple-silicon-first.md))" with
    "(settled since by [ADR 0062](../adr/0062-apple-silicon-first.md): the
    repository is public)", and in its frontmatter `related` replace
    `docs/questions/site-hosting.md` with
    `docs/adr/0062-apple-silicon-first.md`.
  - `git rm docs/questions/site-hosting.md`.
- [ ] **Step 4:** Append `- [0062: Apple silicon first, a safe CPU build
  elsewhere](0062-apple-silicon-first.md)` to the index's "The native
  engine".
- [ ] **Step 5: `CLAUDE.md`.** After the network rule, add:

  ```markdown
  - Apple silicon first: macOS 15 or later gets the tuned build (CPU,
    matrix units, GPU); Linux and Windows get the safe CPU build; no Intel
    Macs, and no musl for now (0062).
  ```

- [ ] **Step 6: Check the links.**
  `grep -rn "site-hosting" --include='*.md' docs CLAUDE.md HANDOFF.md` finds
  only the spec's §5.6, which names the file in a code span. `just fmt`,
  `just check`, `just test`, `just build-docs` pass. Commit
  `docs: record Apple silicon first as ADR 0062 (#78)`.

### Task 4: ADR 0063, the compute libraries

**Files:**
- Create: `docs/adr/0063-the-engines-compute-libraries.md`
- Modify: `docs/questions/engine-compute-libraries.md` (a line under its
  title), `docs/questions/README.md`, `docs/adr/index.md`, `CLAUDE.md`

- [ ] **Step 1: Write the ADR**, titled `# 0063: The engine's compute
  libraries: Accelerate, OpenBLAS and Metal`, from §3.4 and the research
  page.
  - Context: the M3's numbers: 52, 19 and 36 ms for XᵀX of 400,000 × 200;
    the small eigenvalues wrong by 10 to 44 times their size in float32;
    MLX's float32 `exp` and `erf`; its 214 MB; a first kernel in 44 ms, then
    0.5 ms; the 65,536-row case where MLX's GPU won, 2.9 against 3.5 ms. Then
    what was weighed: MLX, the cross-platform GPU layers, Eigen (MPL-2.0),
    JAX and XLA.
  - Decision: every bullet of §3.4.
  - Consequences: no MLX dependency; Xcode's Metal toolchain on the Macs that
    build sqlearn; validation per platform; #77 sets each kernel's threshold.
- [ ] **Step 2: The research page.** Under its title, add: "Answered by [ADR
  0063](../adr/0063-the-engines-compute-libraries.md) on 2026-11-21, and kept
  as the research behind it."
- [ ] **Step 3: The questions folder's rule.** Replace the text of
  `docs/questions/README.md` with: "Open questions. Move the answer into the
  right doc, then delete the question. A question whose research an ADR
  cites stays, marked as answered by that ADR."
- [ ] **Step 4:** Append `- [0063: The engine's compute libraries:
  Accelerate, OpenBLAS and Metal](0063-the-engines-compute-libraries.md)` to
  the index's "The native engine".
- [ ] **Step 5: `CLAUDE.md`.** After the Apple silicon rule, add:

  ```markdown
  - float64 runs on the CPU: Accelerate on macOS, OpenBLAS elsewhere. No
    MLX. GPU kernels are Metal, compiled ahead of time. Never `-ffast-math`
    (0063).
  ```

- [ ] **Step 6:** `just fmt`, `just check`, `just test`, `just build-docs`
  pass. Commit `docs: record the engine's compute libraries as ADR 0063 (#78)`.

### Task 5: ADR 0064, when the GPU runs

**Files:**
- Create:
  `docs/adr/0064-the-gpu-runs-by-itself-only-when-the-answer-is-the-same.md`
- Modify: `docs/adr/0046-sqlearn-warns-the-user-chooses.md` (Status),
  `docs/adr/index.md`, `CLAUDE.md`

- [ ] **Step 1: Write the ADR**, titled `# 0064: The GPU runs by itself only
  when the answer is the same`, from §3.5.
  - Context: ADR 0046's rule, "even when the result would be identical";
    that Apple GPUs have no float64 (Metal Shading Language 4.1, §2.1); which
    of sqlearn's kernels can match the CPU bit for bit; and the speed most
    users would never get if the GPU were opt-in.
  - Decision: every bullet of §3.5.
  - Consequences: the tests require exact equality between each automatic
    kernel's CPU and GPU versions; a setting shows and forces the device; #77
    sets the thresholds; a float32 GPU version needs the user's choice and its
    own bounds (ADR 0016).
- [ ] **Step 2: Amend ADR 0046.** Add to its Status paragraph: "Amended by
  [ADR 0064](../adr/0064-the-gpu-runs-by-itself-only-when-the-answer-is-the-same.md)
  (2026-11-21): on Apple silicon the GPU runs by itself when its answer is bit
  for bit the CPU's."
- [ ] **Step 3:** Append `- [0064: The GPU runs by itself only when the
  answer is the
  same](0064-the-gpu-runs-by-itself-only-when-the-answer-is-the-same.md)` to
  the index's "The native engine".
- [ ] **Step 4: `CLAUDE.md`.** Replace the rule "sqlearn never changes on its
  own what the user asked for: it keeps the default, warns with a `Fix:`
  line, and the user opts in (0046)." with:

  ```markdown
  - sqlearn never changes on its own what the user asked for: it keeps the
    default, warns with a `Fix:` line, and the user opts in (0046). The one
    exception: on Apple silicon a kernel runs on the GPU by itself when its
    answer is bit for bit the CPU's (0064).
  ```

- [ ] **Step 5:** `just fmt`, `just check`, `just test`, `just build-docs`
  pass, and ADR 0046's diff is the one sentence. Commit
  `docs: record when the GPU runs as ADR 0064 (#78)`.

### Task 6: ADR 0065, the safety rules

**Files:**
- Create: `docs/adr/0065-safety-rules-for-the-cpp.md`
- Modify: `docs/adr/index.md`, `CLAUDE.md`

- [ ] **Step 1: Write the ADR**, titled `# 0065: Safety rules for the C++`,
  from §3.6.
  - Context: memory safety is Tomas's main worry about C++; the engine runs
    inside the user's Python process, where a crash kills their notebook.
  - Decision: every rule of §3.6, the sanitizer line as the agent's call.
  - Consequences: Phase 1 sets up a CI job per rule; Phase 1's spec names
    the thin layer for raw memory; Phase 1 measures the hardened library's
    cost, and Tomas rules on it.
- [ ] **Step 2:** Append `- [0065: Safety rules for the
  C++](0065-safety-rules-for-the-cpp.md)` to the index's "The native engine".
- [ ] **Step 3: `CLAUDE.md`.** After the float64 rule, add:

  ```markdown
  - The C++ follows the safety rules from its first commit: RAII, no raw
    `new` or `delete`, one thin layer for raw memory, warnings as errors,
    clang-tidy and the static analyser, sanitizers and fuzzing in CI, a
    hardened standard library, and no crash reaching the user (0065).
  ```

- [ ] **Step 4:** `just fmt`, `just check`, `just test`, `just build-docs`
  pass. Commit `docs: record the C++ safety rules as ADR 0065 (#78)`.

### Task 7: ADR 0066, the licences

**Files:**
- Create: `docs/adr/0066-permissive-licences-never-copyleft.md`
- Modify: `docs/adr/0004-apache-2-licence.md` (Status), `docs/adr/index.md`,
  `CLAUDE.md`

- [ ] **Step 1: Write the ADR**, titled `# 0066: Permissive licences, never
  copyleft`, from §3.7.
  - Context: bundling DuckDB brings 26 libraries and ICU (the counts by
    licence in §3.7). Three of them sit outside ADR 0004's list, although
    they are as permissive as MIT: Boost (ska_sort), zlib (pdqsort) and
    Unicode (ICU). Two others offer a choice of licence.
  - Decision: every bullet of §3.7.
  - Consequences: the third-party file and `NOTICE` arrive in Phase 1, which
    also confirms ICU's source and licence. A copyleft library, such as GEOS
    in DuckDB's spatial extension, is never compiled in; a user may still
    install such an extension (ADR 0061).
- [ ] **Step 2: Amend ADR 0004.** Add to its Status paragraph: "Amended by
      [ADR 0066](../adr/0066-permissive-licences-never-copyleft.md)
      (2026-11-21): runtime code may carry any permissive licence the OSI
      approves, never copyleft."
- [ ] **Step 3:** Append `- [0066: Permissive licences, never
  copyleft](0066-permissive-licences-never-copyleft.md)` to the index's "The
  native engine".
- [ ] **Step 4: `CLAUDE.md`.** In the runtime rule from Task 2, replace
  "anything else needs a written reason and a permissive licence (0004,
  0005, 0057, 0061)." with "anything else needs a written reason (0005,
  0057, 0061).", and add after that rule:

  ```markdown
  - Runtime code carries only permissive licences approved by the OSI (MIT,
    BSD, Apache-2.0, PSF, Boost, zlib, Unicode, ISC), never copyleft, each
    listed in the third-party file (0004, 0066).
  ```

- [ ] **Step 5:** `just fmt`, `just check`, `just test`, `just build-docs`
  pass, and ADR 0004's diff is the one sentence. Commit
  `docs: record the widened licences as ADR 0066 (#78)`.

### Task 8: ADR 0067, how computation moves

**Files:**
- Create: `docs/adr/0067-how-computation-moves-to-the-engine.md`
- Modify: `docs/adr/index.md`, `CLAUDE.md`

- [ ] **Step 1: Write the ADR**, titled `# 0067: How computation moves to the
  engine`, from §3.8 and §4's order of work.
  - Context: the contract the current tests and validation runners give; the
    earlier attempts' big rewrites; Tomas's order: the migration first, over
    sqlearn's whole current state, piece by piece.
  - Decision: every bullet of §3.8, and §4's order: Python stays the API;
    HANDOFF's three small fixes before Phase 1 (the agent's call); new library
    areas wait until the migration is done; work that needs an engine function
    waits for the phase that brings it.
  - Consequences: a test of an internal deleted with its code is named in its
    phase's spec; every move has a benchmark; the inventory (plan 0b) is the
    migration's map.
- [ ] **Step 2:** Append `- [0067: How computation moves to the
  engine](0067-how-computation-moves-to-the-engine.md)` to the index's "The
  native engine".
- [ ] **Step 3: `CLAUDE.md`.** After the safety rule, add:

  ```markdown
  - Computation moves to the engine piece by piece, with `main` green: a
    piece moves when its C++ passes the same tests unchanged and is not
    slower, then its Python is deleted. A test of the public API changes
    only with an ADR (0067).
  ```

- [ ] **Step 4:** `just fmt`, `just check`, `just test`, `just build-docs`
  pass. Commit `docs: record how computation moves as ADR 0067 (#78)`.

### Task 9: ADR 0068, sqlearn's own models

**Files:**
- Create: `docs/adr/0068-sqlearns-own-models.md`
- Modify: `docs/adr/0017-models-from-other-libraries.md` (Status),
  `docs/adr/index.md`, `CLAUDE.md`

- [ ] **Step 1: Write the ADR**, titled `# 0068: sqlearn's own models, in the
  engine`, from §3.9.
  - Context: ADR 0017's "for now" and the hand-over's limit: training holds
    the prepared data in memory.
  - Decision: every bullet of §3.9.
  - Consequences: each model is its own spec in Phase 4; each is validated and
    benchmarked against scikit-learn; outside models and the hand-over stay
    supported.
- [ ] **Step 2: Amend ADR 0017.** Add to its Status paragraph: "Amended by
      [ADR 0068](../adr/0068-sqlearns-own-models.md) (2026-11-21): sqlearn's own
      models become a goal; outside models stay supported."
- [ ] **Step 3:** Append `- [0068: sqlearn's own models, in the
  engine](0068-sqlearns-own-models.md)` to the index's "The native engine".
- [ ] **Step 4: `CLAUDE.md`.** In the opening paragraph, replace "Models stay
  with outside libraries (ADR 0017)." with "sqlearn's own models are a goal,
  built in the engine; outside models stay supported (ADR 0017, 0068)."
- [ ] **Step 5:** `just fmt`, `just check`, `just test`, `just build-docs`
  pass, and ADR 0017's diff is the one sentence. Commit
  `docs: record sqlearn's own models as ADR 0068 (#78)`.

### Task 10: The overview follows the records

**Files:**
- Modify: `docs/architecture/overview.md`

- [ ] **Step 1: §2's constraints.**
  - "Python and DuckDB" becomes "Python, C++ and DuckDB": computation inside
    DuckDB as SQL and the native engine's C++ functions (ADR 0060), with
    Python as the API and the glue (ADR 0002), and the Gram exception until
    Phase 2 (ADR 0058).
  - "Two runtime dependencies" becomes sqlearn's own DuckDB build and numpy
    (ADR 0061, 0057, 0005).
  - "Licence" gains: runtime code under permissive licences only, never
    copyleft (ADR 0066).
  - "Tooling" gains: CMake and a C++ toolchain for the engine, and Xcode's
    Metal toolchain on the Macs that build its GPU kernels (ADR 0060, 0063).
- [ ] **Step 2: §3's new part.** After 3.9 and before "Later: other database
  engines", add "### 3.10 Native engine", in the form of the other parts:
  - **What:** sqlearn's computation in a C++ engine compiled into its own DuckDB
    build, Apple silicon first, in seven phases
    ([spec](../specs/native-engine.md) §4; ADRs 0060 to 0068; milestone "Native
    engine", #78 to #84). Mention "the inventory of every module" in words,
    without a link (plan 0b adds the link once the page exists).
  - **Done when:** sqlearn's current state runs on the engine (Phases 1 to
    3); each later phase is done when its spec says so.
  - **Depends on:** 3.2 and 3.3 for what moves, 3.8 for the validation every
    move passes, 3.9 for the benchmarks.
- [ ] **Step 3: §4's order.** After the numbered list, add: "Now
  (2026-11-21): the native engine (3.10). Its migration of sqlearn's current
  state, Phases 1 to 3, comes before any new area of 3.3 or 3.6, after
  HANDOFF's three small fixes ([spec](../specs/native-engine.md) §4)."
- [ ] **Step 4:** `just fmt`, `just check`, `just test`, `just build-docs`
  pass. Commit `docs: add the native engine to the overview (#78)`.

### Task 11: The layout page, the glossary, and this plan's close

**Files:**
- Modify: `docs/architecture/layout.md`, `GLOSSARY.md`, `HANDOFF.md`

- [ ] **Step 1: The layout page.**
  - In the tree, after the `benchmarks/` lines, add `engine/`: "the native
    engine (C++) and sqlearn's DuckDB build, from the engine's Phase 1 (ADR
    0060, 0061)".
  - Replace "`.github/workflows/` arrives when the repository is public,
    with Actions." with "`.github/workflows/` arrives with the native
    engine's Phase 1; the repository is public (ADR 0062)."
  - Under "What arrives later", replace "`.github/`: nothing while the
    repository is private." with "`.github/`: the CI workflows, with the
    native engine's Phase 1.", and add "`engine/`: with the native engine's
    Phase 1."
- [ ] **Step 2: The glossary.** Append four terms, worded from ADRs 0060 to
  0064 in the glossary's form, each with an _Avoid_ line where a wrong word
  is likely:
  - **Native engine:** sqlearn's C++, compiled into sqlearn's DuckDB build as
    the `sqlearn` extension; its SQL functions start with `sqlearn_`.
  - **sqlearn's DuckDB build:** the `duckdb` module sqlearn installs as a
    second package: DuckDB from its official source at a pinned release, with
    the engine and the extensions sqlearn needs compiled in. _Avoid_: fork.
  - **Kernel:** one of the engine's computations over DuckDB's columns, with
    a CPU version everywhere and, on Apple silicon, perhaps a Metal version
    that gives the same answer.
  - **Plain-SQL twin:** the DuckDB SQL that computes what an engine function
    in apply computes, kept so the SQL runs in any DuckDB (ADR 0060).
- [ ] **Step 3: Read the rules.** Read every rule line in `CLAUDE.md`'s
  "Rules from the ADRs" against the ADRs it cites; fix any line an ADR does
  not say.
- [ ] **Step 4: `HANDOFF.md`.** The "In progress" line: "plan 0a done (ADRs
  0060 to 0068, commits `<first>`..`<last>`); plan 0b next".
- [ ] **Step 5:** `just fmt`, `just check`, `just test`, `just build-docs`
  pass. Commit `docs: the layout and glossary follow the engine's ADRs
  (#78)`.
