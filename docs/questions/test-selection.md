---
type: question
tags: [test-selection, ci, build-graph, validation, sqlearn]
summary: "Open question on how sqlearn should choose which tests and validation run for a change, with research on how large projects select tests."
related: [docs/specs/selection-by-group.md, docs/architecture/testing.md, docs/architecture/overview.md, HANDOFF.md, docs/adr/0043-repeatable-within-rounding.md]
mdindex: [type=1f5087, tags=1bbbb9, summary=0f79bd, related=505c16]
---
# How should sqlearn choose which tests and validation run for a change?

Open. Research of 2026-11-27: two reports, merged here; no decision taken
yet. The current design is "selecting by group"
([spec](../specs/selection-by-group.md),
[testing](../architecture/testing.md#selecting-by-group)). The question was
asked with sqlearn's growth in mind: past scikit-learn's scope, with the
applications, exploration and possibly its own models
([overview](../architecture/overview.md)).

## The short answer

Large projects do not run everything for every change. They pick tests in
four ways, often together (part A):

- **By the build graph**: every test downstream of what changed (Google's TAP
  with Blaze/Bazel, Chromium's `gn analyze`, Meta's Buck2 target
  determinator), or a hand-kept table of what to test when a part changes
  (LLVM, Mozilla's `SCHEDULES`).
- **By caching results** keyed on the hash of a test's inputs (Bazel).
- **By deferring**: fast tests before a change lands, the rest after it, in
  batches, with culprit finding when a batch fails (Google, Meta, Chromium,
  Mozilla, Microsoft).
- **By prediction**: a model trained on past failures skips the tests least
  likely to fail (Meta, Mozilla's bugbug, Microsoft's THEO and FastLane).

Every one of them also **runs everything on a schedule and checks what the
selection missed**: Mozilla every 20 pushes or 4 hours, Meta every few hours,
Azure's Test Impact Analysis at an interval it recommends, THEO with every
test at least once before trunk.

sqlearn's groups are the first two ways at the grain of a group: the TAP and
Bazel model, at the coarse grain the literature finds cheapest and safest.
The claims are a hand-kept table of LLVM's and Mozilla's kind, with
Mozilla's default (unknown means affected); the audit is a stronger guard
than LLVM's, which has none; the comment stripping with line numbers kept is
Ekstazi's "smart checksum", with the exception Ekstazi names.

No tool fits sqlearn's stack better today (part B). Bazel is the only real
replacement, and only later: DuckDB has no Bazel build, a Python test would
depend on the whole binary (coarser than the claims), and a comment edit
would rerun its tests again. Keeping groups aligned with directories and
`DEPENDS` honest keeps a later move mechanical.

## What could be added now

Proposals from the two reports, none decided:

1. **Run the audit** (`just audit-groups`): the only check that a claim is
   not too small (B §7.1). It awaits Tomas's go-ahead (`HANDOFF.md`).
2. **A full run at a set cadence**, not only `just verify` before `1.0.0`:
   for example every N commits on `main`, or before each group of the port
   merges (A §9). The cadence is Tomas's call; the sources give no number
   for a project of this size.
3. **Compare that full run with the selection**: a test or runner that fails
   in the full run but that the selection would have skipped is a selection
   miss, and should fail loudly naming the missing claim or input (A §9).
4. **Validation runners failed-first, then longest-first**, as CTest's
   scheduler orders tests; it selects nothing away. It needs each runner's
   wall time, already in "Next up" (B §5).
5. **pytest `--ff`** on each Python set: one flag; its gain under xdist is
   not confirmed (B §3.4).
6. **Record the files each set and runner opens**, with Python's audit
   hooks, to check the hand-kept input lists; blind to files DuckDB opens
   from C++ (B §3.7).
7. **Record thread-order anomalies as flakes**, not discard them: a selector
   that skips on a passed record cannot tell a skipped failure from a flake
   (A §7, §9).
8. **Parallel validation runners**, only after measuring them: DuckDB's
   threads, memory limits and ADR 0043's order dependence make the gain
   unknown (B §5).

## What does not fit yet, and the signs it would

Predictive selection, merge queues, batching with culprit finding, and
per-test coverage selection inside a group each need something the docs do
not state: a failure history to train on, several people or agents landing
on `main` at once, a CI machine, or a group whose tests are slow. Part A §9
has a table of the signs for each; part B §7.4 the signs that Bazel is worth
its cost, and what of today's design would carry over.

---

## Part A: how large projects choose


Research for sqlearn, 2026-11-27. Primary sources only: papers (venue and
year given), official documentation, the companies' own engineering posts, and
source code. Where a claim could not be confirmed from a primary source, it says
so. Quotations are kept short; most of the text paraphrases.

Contents: 1. build-graph selection; 2. caching results by input; 3. tiering,
batching, culprit finding and merge queues; 4. predictive (ML) selection;
5. coverage-based test impact analysis; 6. static selection and the
safety/precision literature; 7. flaky tests; 8. the Linux kernel; 9. what this
means for sqlearn.

---

### 1. Build-graph selection: "test everything downstream of what changed"

#### Google TAP with Blaze/Bazel

**What it is.** TAP, Google's Test Automation Platform, takes the files a change
touches, walks the build graph's reverse dependencies, and calls every test
target that directly or indirectly depends on them an *affected* test target.
The grain is the test target as the BUILD files declare it (a JUnit suite, a
single Python test, an end-to-end script), so the precision of the selection is
whatever precision the BUILD files have. Source: Memon et al., "Taming
Google-Scale Continuous Testing", ICSE-SEIP 2017, §II
([PDF from Google](https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/45861.pdf);
[Google Research page](https://research.google/pubs/taming-google-scale-continuous-testing/)).
Forge and Blaze keep a near-real-time global dependency graph, so TAP can run
the minimal set of tests downstream of a change
([Software Engineering at Google, ch. 23](https://abseil.io/resources/swe-book/html/ch23.html)).
In open-source Bazel the same question is `rdeps(universe, x)` with `tests()`
([Bazel query language](https://bazel.build/query/language)).

**How it decides.** Purely structurally: a declared dependency path from a
changed file to a test means the test runs. It does not look at what the test
executes.

**Cost.** The graph is maintained as part of the build, so selection itself is
cheap, but the selected set is large: milestones of up to 4.2 million tests
selected by reverse dependencies, and delays of up to 9 hours under
infrastructure trouble (Memon et al., §I). In the period studied, 5.5 million
affected tests were seen and only 63 thousand ever failed; 1.23% of executions
found a breakage or a fix; test targets more than 10 dependency edges from the
change hardly ever broke (Memon et al., §I). Google's response was not to
narrow the graph but to schedule it (milestones, §3 below) and to study which
signals predict failure.

**How it can miss.** A dependency the BUILD files do not declare. Memon et al.
note that the affected set exists only because of defined dependencies.
Bazel's own contract says tests should touch only declared inputs, but that
this is not enforced yet; a test with external dependencies is tagged
`external`, which turns off result caching
([Bazel test encyclopedia](https://bazel.build/reference/test-encyclopedia)).

#### Buck2 (Meta) and its target determinator

Meta's open-source `buck2-change-detector` dumps the Buck2 target graph before
and after a change and computes the targets that transitively depend on what
changed (`btd`, bundled as `supertd`). Each impacted target carries a `depth`.
Its README warns that a large change to a key dependency yields too many
targets, and that trimming by depth lowers cost at the risk of letting a
breakage in. Running the selected builds and tests is left to an internal tool,
Citadel, not released
([facebookincubator/buck2-change-detector](https://github.com/facebookincubator/buck2-change-detector)).
Meta's own paper (§4) explains why it went beyond this.

#### Pants

`--changed-since=<ref>` picks files changed since a commit;
`--changed-dependents=direct|transitive` adds targets that depend on them. The
docs list two caveats: transitive third-party dependencies are not fully
understood, and a change to one entry in a lockfile marks every user of any
dependency in it as changed
([Pants: advanced target selection](https://www.pantsbuild.org/stable/docs/using-pants/advanced-target-selection)).

#### Chromium: `gn analyze` and location filters

Most tests on Chromium's commit queue are selected by `gn analyze` from the
build graph
([Chromium CQ docs](https://chromium.googlesource.com/chromium/src/+/main/docs/infra/cq.md)).
`gn analyze` takes the changed files and the candidate test and compile targets
and returns the affected ones, with a status of "Found dependency", "No
dependency" or "Found dependency (all)"; the last means GN could not tell and
returned the whole input to be safe
([GN reference](https://gn.googlesource.com/gn/+/main/docs/reference.md#cmd_analyze)).
In the source, a change to the dot file, the build config file or a file the
build args depend on returns "all" before any graph analysis; a changed file
that no target references (as a source, header, data, script, input or build
file) yields "No dependency"
([gn/analyzer.cc](https://gn.googlesource.com/gn/+/main/src/gn/analyzer.cc)).
So the graph is only as safe as the declared `data` and `inputs` of each target.

For tests the graph cannot place, Chromium uses hand-written path regexps
(`location_filters` in `//infra/config`): on try builders such a test runs only
if a modified file matches; CI builders and the larger "Mega CQ" always run them
([Chromium CQ docs](https://chromium.googlesource.com/chromium/src/+/main/docs/infra/cq.md)).

#### LLVM: a hand-kept project table

LLVM's pre-merge CI maps each changed path to its top-level project, then uses
two hand-maintained tables: what each project needs built
(`PROJECT_DEPENDENCIES`, direct dependencies only, closed transitively by the
code) and what to test when a project changes (`DEPENDENTS_TO_TEST`; for
example a change in `llvm` tests clang, lld, lldb, mlir, flang and others).
A change to the CI scripts tests everything; `docs` and the GN build directory
trigger nothing; some projects are excluded per platform because their tests
are unstable or too expensive
([.ci/compute_projects.py](https://raw.githubusercontent.com/llvm/llvm-project/main/.ci/compute_projects.py);
introduced in
[PR #132634](https://lists.llvm.org/pipermail/llvm-commits/Week-of-Mon-20250317/1593986.html)).
Nothing in the script checks that the tables are complete; I found no audit of
them.

#### Mozilla: `SCHEDULES` in moz.build

Firefox maps file patterns to task "components" in `moz.build` files
(`SCHEDULES.inclusive`, `SCHEDULES.exclusive`); a task not tagged with a
component the change touches is dropped. The design is described as
conservative: a file with no `SCHEDULES` is assumed to affect every exclusive
component, so only opt-in (inclusive) components need explicit annotations
([Firefox: schedules optimization](https://firefox-source-docs.mozilla.org/taskcluster/optimization/schedules.html)).

**Summary of the family.** All of these are safe exactly to the extent that the
declared graph or table is complete; none uses execution data. The ones with a
hand-kept mapping (LLVM, Chromium's location filters, Mozilla's `SCHEDULES`)
fall back to "everything" for files they do not know (Mozilla), for CI files
(LLVM), or always run the hand-filtered tests on CI (Chromium).

---

### 2. Caching results by input

**Bazel.** With the default `--cache_test_results=auto`, Bazel reruns a test
only when it detects a change in the test or its dependencies, when the test is
tagged `external`, when several runs are requested, or when it failed last time;
otherwise the cached result stands
([Bazel user manual](https://bazel.build/docs/user-manual)). This is selection
by content hash of declared inputs, the same idea as sqlearn's records. Its
known hole is the one in §1: inputs the test reads but does not declare.

**Ekstazi's "smart checksum"** (§5) is the closest published analogue to
sqlearn's comment-stripped fingerprint: it hashes Java bytecode and can ignore
debug information, so an added blank line does not rerun tests; the authors
note the exception of tests that observe debug info, such as through exceptions
that check line numbers (Gligoric et al., ISSTA 2015, §3.5).

---

### 3. Tiering, batching, culprit finding, merge queues

#### Google

Presubmit runs only fast, reliable tests, usually a project's unit tests; a
change that passes presubmit has a 95%+ likelihood of passing the rest, so
changes are integrated optimistically and TAP runs the larger tests after
submission. Because TAP sees more than one change a second, it batches related
changes; a failing batch is split and the changes rerun in isolation, and
developers can binary-search a batch. The Build Cop's first fix is a rollback,
and TAP now rolls back automatically when it is highly confident of the culprit
([SWE at Google, ch. 23](https://abseil.io/resources/swe-book/html/ch23.html)).

TAP's batching unit is the milestone: affected tests left unrun since the last
milestone are run together, each at its latest affecting change, typically every
45 minutes at peak; a test affected by five changes runs once (Memon et al.,
§I–II). The cost: a failure points at a range of changes, not one.

Culprit finding over that range is itself a selection problem. Google's
"Flake Aware Culprit Finding" (Henderson et al., ICST 2023 industry track) first
uses the build graph to drop changes that cannot affect the failing test, then
runs a Bayesian noisy binary search with a "no culprit" (flake) hypothesis,
priors from graph distance and from historical flake rates; on about 13,600
breakages it was more accurate than deflaked bisection, at slightly higher cost
than plain one-run bisection
([authors' page](https://hackthology.com/flake-aware-culprit-finding.html);
[Google Research](https://research.google/pubs/flake-aware-culprit-finding/)).

#### Meta

Meta describes four stages: hand-picked tests before review; diff-time
(selected tests on every version of a diff, rebased onto a known-green master,
ideally within ten minutes); land-time (a possibly larger subset, rejecting the
diff on failure); and stabilisation, where every few hours all tests run on the
latest master and failures become tickets. Release candidates come only from
stabilised versions, so the earlier stages need not be conservative. Diff- and
land-time use an order of magnitude more machines than stabilisation, and their
cost grows at least linearly with the number of developers. Stabilisation is a
batch test, with the batch costs that implies: a later diff can mask an
earlier break, and a failure does not name its culprit. Changes landed
concurrently can each pass and still break together
(Machalica et al., "Predictive Test Selection", ICSE-SEIP 2019, §II;
[arXiv:1810.05286](https://arxiv.org/abs/1810.05286)).

#### Microsoft (Windows, Office, Dynamics)

THEO skips a test on a branch when the expected cost of running it exceeds the
expected cost of not running it, but only on the condition that every test
scenario still runs at least once for each change before it reaches trunk: a
test may be skipped on branch B2 only if it will run on B3 for the same change.
Replaying past development of Windows, Office and Dynamics it cut test
executions by 50% (Herzig, Greiler, Czerwonka, Murphy, "The Art of Testing Less
without Sacrificing Quality", ICSE 2015;
[PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2015/05/The-Art-of-Testing-Less-without-Sacrificing-Quality.pdf)).
Skipping is deferring, never dropping.

Echelon's paper describes the same tiering a decade earlier: pre-check-in
tests, verification tests after the build, then full testing that may take days
or weeks (Srivastava and Thiagarajan, ISSTA 2002;
[MSR-TR-2002-15](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-2002-15.pdf)).

#### Chromium

Dry run and full run of the CQ run the same tests; the dry run only reports.
Some tests are CI-only (after submission) and can be pulled in with a footer.
A failing shard is retried, then the failing suites are rebuilt and rerun
without the patch; the CL fails only if the tests failed with the patch, failed
again on retry, and passed without it
([Chromium CQ docs](https://chromium.googlesource.com/chromium/src/+/main/docs/infra/cq.md)).
After submission, LUCI Bisection (formerly Findit) finds culprits of compile and
test failures and can create reverts, within per-project limits
([luci-go/bisection](https://chromium.googlesource.com/infra/luci/luci-go/+/fc10b0436339/bisection/);
[Chromium's luci-bisection.cfg](https://chromium.googlesource.com/chromium/src/+/bbad3a62162765c67780c4337a2bdcdb5ab8e760/infra/config/generated/luci/luci-bisection.cfg)).
I did not find an end-to-end document of its revert policy.

#### Mozilla: backstops

On integration branches, pushes run a selected subset, and a *backstop* push
runs everything: every 20th push or after 4 hours, whichever comes first
(`BACKSTOP_PUSH_INTERVAL = 20`, `BACKSTOP_TIME_INTERVAL = 60 * 4` minutes); an
"expanded" push at half the interval runs a middle tier
([util/backstop.py](https://searchfox.org/firefox-main/source/taskcluster/gecko_taskgraph/util/backstop.py);
[optimize/backstop.py](https://searchfox.org/firefox-main/source/taskcluster/gecko_taskgraph/optimize/backstop.py)).
Missed regressions are found by code sheriffs, who backfill the skipped tests
on older pushes to find the culprit and back it out
([Mozilla Hacks, July 2020](https://hacks.mozilla.org/2020/07/testing-firefox-more-efficiently-with-machine-learning/)).

#### Merge queues

GitHub's merge queue tests each queued pull request on a temporary branch made
of the base plus the PRs ahead of it; if that fails, the PR leaves the queue and
the next one is rebuilt without it; build concurrency is capped from 1 to 100;
optionally a failed PR may merge as part of a group whose last PR passed
([GitHub docs: managing a merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)).
Uber's SubmitQueue (Ananthanarayanan et al., "Keeping Master Green at Scale",
EuroSys 2019, DOI 10.1145/3302424.3303970) keeps master green for every commit
while thousands of commits a day land in monorepos, by speculating which
pending changes will succeed. I could not fetch Uber's page or the full text in
this session, so I give no further detail on its model.
The problem merge queues solve is the one Meta names: changes that pass alone
and break together.

---

### 4. Predictive (machine-learned) selection

#### Meta: Predictive Test Selection

**What it is.** A gradient-boosted decision-tree classifier that, for a (change,
test target) pair, predicts the probability of failure; a threshold turns it
into a selection. Candidates are the tests the build graph says depend on the
change; almost 99.9% of those pass, which is the room it exploits.
Features: change history of the modified files over 3, 14 and 56 days; files
touched; number of test targets triggered; file extensions; distinct authors;
the target's failure rates over 7–56 days; project name; number of tests in the
target; minimal graph distance between a changed file and the target; and
common tokens in their paths (Machalica et al., ICSE-SEIP 2019, §IV-A;
[arXiv:1810.05286](https://arxiv.org/abs/1810.05286)).

**Cost.** Running it saves half the infrastructure cost, while still reporting
over 95% of individual test failures and over 99.9% of faulty changes
(abstract). Meta's post says it runs about a third of the tests that
transitively depend on the change
([Meta engineering, Nov 2018](https://engineering.fb.com/2018/11/21/developer-tools/predictive-test-selection/)).
The maintenance cost is a data pipeline: measuring recall requires knowing the
outcome of every dependent test, so Meta runs "learning" full runs on close to a
quarter of changes, off-peak; it retrains weekly, checks the new model against
fixed criteria (for example a selection rate below 0.3 at test recall 0.9), and
pages a person if it fails (§IV-C, §IV-D). Training needs failed tests to be
retried aggressively, since a model trained on flaky results predicts poorly
(§V).

**How it misses, and what catches it.** By design it is not conservative; the
stabilisation runs and release gating catch what it misses (§II–III, §3 above).

#### Mozilla: bugbug

An XGBoost model predicts fail / not fail for (test, patch); features include
how often a test failed when the same files changed, directory distance between
source and test, and how often they changed together. It is retrained every two
weeks on a chronological split. A second step picks configurations, and a
mixed-integer solver picks the cheapest configurations to run the selected
tests on. Against the previous heuristic, integration-branch test tasks fell by
70%; against no selection, by almost 99%. The reported scale: about 85,000 test
files, over 90 configurations, nearly 300 pushes a day. Candidate schedulers are
run in "shadow" mode and compared on detection rate per machine-hour before
going live. Misses are caught by the periodic full runs (backstops) and by
sheriffs' backfills (§3)
([Mozilla Hacks, July 2020](https://hacks.mozilla.org/2020/07/testing-firefox-more-efficiently-with-machine-learning/)).
`mach try auto` exposes the same selection for try pushes; the decision task
computes it, not the developer's machine
([Firefox: try auto](https://firefox-source-docs.mozilla.org/tools/try/selectors/auto.html)).
Its fallback strategy in code, when bugbug gives no answer, is
`skip-unless-has-relevant-tests`
([gecko_taskgraph.optimize](https://firefox-source-docs.mozilla.org/python/gecko_taskgraph.optimize.html)).

#### Google

Memon et al. (ICSE-SEIP 2017) found that failures cluster near the change in
the graph, around frequently modified files, certain file types and users, and
files recently changed by three or more developers; they turned this into
advice to developers, and into signals for running rarely failing tests less
often. They rejected "rerun recently failed tests" because it mostly reruns
flaky tests. Leong et al., "Assessing Transition-based Test Selection
Algorithms at Google" (ICSE-SEIP 2019), replayed TAP history with flaky runs
filtered out and found that heuristics based on recent commits affecting a test
did best, and those based on prior test results did worse
([Google Research](https://research.google/pubs/assessing-transition-based-test-selection-algorithms-at-google/);
[authors' PDF](https://mpapad.github.io/publications/pdfs/ICSE-SEIP2019.pdf)).
I read only the abstract of the latter.

#### Microsoft: THEO and FastLane

THEO (§3) uses only historic test results and cost factors, deliberately no
coverage, to avoid runtime overhead (Herzig et al., ICSE 2015, §III). FastLane
(Philip et al., ICSE 2019) predicts commit risk and test outcomes for Office 365
from test and commit logs and skips tests whose outcome it predicts; it saved
18.04% of test time at 99.99% outcome accuracy
([PDF](https://www.microsoft.com/en-us/research/uploads/prod/2018/12/PID5783051.pdf)).

**Common prerequisites.** Every predictive system above rests on a large
history of failures with flakes separated out, a periodic full run to measure
what it misses and to catch it, and someone to retrain and watch it.

---

### 5. Coverage-based test impact analysis

#### Microsoft Echelon (binary, basic-block level)

Echelon diffs two builds' binaries at basic-block level and orders the existing
tests to cover the changed blocks first, using coverage recorded on the old
binary. For new blocks it has no coverage, so it guesses: a test may cover a new
block if it covers one of its predecessors and one of its successors. The paper
names two weaknesses: the path may bypass the new block, and when a new block is
the target of an indirect call its predecessors are not in the static graph
(Srivastava and Thiagarajan, ISSTA 2002, §3;
[MSR-TR-2002-15](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-2002-15.pdf)).
It prioritises, it does not drop tests.

#### Azure DevOps Test Impact Analysis

TIA builds a per-test map of the source files each test ran, and selects
impacted tests, previously failing tests and new tests. Its fallback: for
changes it cannot reason about (for example HTML or CSS, or any unknown file
type) it runs all tests. It supports only managed code on one machine; not
data-driven tests, not tests of an app on another machine. Microsoft recommends
a run of all tests at a set interval, and validating the selection by running
the selected tests and then all tests and comparing. Users can supply their own
dependency map for C++ or other languages
([Microsoft Learn: Test Impact Analysis](https://learn.microsoft.com/en-us/azure/devops/pipelines/test/test-impact-analysis)).

#### Ekstazi (file-level dynamic dependencies)

Ekstazi records, for each test class, the names and checksums of every file it
used while running: class files and also other files on the file system. A test
is selected when any of those checksums changed. Working at file granularity
selects more tests than method-level techniques but has the lowest end-to-end
time; method-level intersection is unsafe (an added overriding method, or a
changed final field, can change a test that never executed the changed method).
Instrumentation points include static initialisers, static field access, class
literals and reflection. Evaluated on 615 revisions of 32 projects, it cut
end-to-end test time by 32% on average and 54% for longer suites (Gligoric,
Eloussi, Marinov, "Practical Regression Test Selection with Dynamic File
Dependencies", ISSTA 2015, §2–3;
[PDF from the author](https://users.ece.utexas.edu/~gligoric/papers/GligoricETAL15Ekstazi.pdf)).

#### How coverage selection handles its holes

| Hole | Who names it | What they do |
| --- | --- | --- |
| New code with no coverage yet | Echelon (§3) | neighbour-block heuristic; weak at indirect calls |
| New tests | Azure TIA | always run new tests |
| Static initialisation | Ekstazi (§3) | instruments static initialisers and static field access |
| Data and configuration files | Ekstazi (§2); Azure TIA | Ekstazi tracks every file read; TIA does not support data-driven tests and falls back to all for unknown file types |
| Non-determinism (a path not taken in the recorded run) | Legunsen et al., FSE 2016, §1 | names it as a reason dynamic selection can be unsafe |
| Cost of instrumenting at scale, across languages | Memon et al. (§I) | TAP did not use coverage at all |
| Coverage recorded on the previous version | Machalica et al. (Fig. 2) | dynamic analysis misses failures for this reason |

The pattern in practice: either run everything when the tool is unsure (TIA,
gn analyze "all", Mozilla's default), or accept misses and catch them in a later
full run (Meta, Mozilla, THEO's "at least once before trunk").

---

### 6. Static selection and the safety/precision trade-off

**Definitions.** A selection technique is *safe* if it selects every test that
may be affected by the change; it may also select unaffected tests
(Legunsen et al., FSE 2016, abstract;
[PDF](https://mir.cs.illinois.edu/~marinov/publications/LegunsenETAL16StaticRTS.pdf)).
The framework of safety (inclusiveness), precision, efficiency and generality
comes from Rothermel and Harrold, "Analyzing Regression Test Selection
Techniques", IEEE TSE 22(8), 1996 (DOI 10.1109/32.536955); I did not read its
full text in this session.

**STARTS and the FSE 2016 study.** Class-level static selection builds a
dependency graph of types from compiled code and selects tests that can reach a
changed type, with no instrumentation
([STARTS tool](https://github.com/TestingResearchIllinois/starts); Legunsen,
Shi, Marinov, ASE 2017 tool demo, DOI 10.1109/ASE.2017.8115710). On 985
revisions of 22 projects, class-level static selection matched Ekstazi's savings
but was occasionally unsafe; method-level static selection was slower and more
often unsafe. The authors recommend coarse granularity, classes "if not modules
or projects" (FSE 2016, §1). Static analysis needs no previous run, so it works
on the first revision, and it is not fooled by non-deterministic runs.

**Reflection.** Static selection that ignores reflection misses tests; Shi et
al., "Reflection-Aware Static Regression Test Selection", OOPSLA 2019 (PACMPL 3,
DOI 10.1145/3360613), evaluate purely static and hybrid fixes built on STARTS
([SPLASH 2019 page](https://2019.splashcon.org/details/splash-2019-oopsla/68/Reflection-Aware-Static-Regression-Test-Selection)).
I read only the abstract.

**The consistent finding** across Ekstazi, the FSE 2016 study and Meta's paper
(Fig. 2: coarse build-target dependencies are less precise than code
references): coarser grain is cheaper to compute and safer to maintain, and its
cost is selecting more tests than strictly needed.

---

### 7. Flaky tests

At Google, about 1.5% of test runs report a flaky result, almost 16% of tests
have some flakiness, and about 84% of observed pass-to-fail transitions in
postsubmit involve a flaky test. Mitigations: rerun only failing tests,
automatic reruns, marking a test flaky so it reports failure only after three
failures in a row (which delays real breakages), and automatic quarantine,
which can hide a real race (John Micco,
[Google Testing Blog, May 2016](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html)).
Bazel retries tests carrying the `flaky` attribute up to three times and
reports a later pass as `FLAKY`
([Bazel user manual](https://bazel.build/docs/user-manual)). Chromium retries
and compares against a run without the patch (§3). THEO treats false alarms as a
cost in its model (Herzig et al., §IV). Flakiness matters to selection in two
ways: history-based selectors learn noise unless flakes are filtered (Meta §V;
Memon §I), and a skipped run cannot later be told apart from a flaky one.

---

### 8. The Linux kernel

The kernel has no central per-change test selection that I could find in its
own documentation. Integration happens in subsystem trees and in linux-next, a
snapshot of what mainline should look like after the next merge window
([kernel docs: development process](https://docs.kernel.org/process/2.Process.html)).
Developers choose suites by hand: kselftest runs one subsystem's tests with
`TARGETS=` and leaves some out with `SKIP_TARGETS=`
([kernel docs: kselftest](https://docs.kernel.org/dev-tools/kselftest.html)).
Testing is after the fact and by robots: Intel's 0-day robot tests every pushed
branch head of the git trees it follows and, on an error, walks back to a good
point (the branch base or a release) and bisects, giving up on bugs found in
too old a kernel (Fengguang Wu, LKML, 18 September 2017,
[archive](https://lists.openwall.net/linux-kernel/2017/09/18/42)). KernelCI
ran automated bisection of boot regressions from 2018, first curated by hand
because false positives could send developers after the wrong change; build
failures on intermediate revisions and wide ranges with several breakages
mislead the search (Guillaume Tucker,
[Collabora, January 2018](https://www.collabora.com/news-and-blog/blog/2018/01/16/kernelci-automated-bisection/)).
Linaro's 2026 post describes automated bisection as starting work again in
KernelCI
([Linaro](https://www.linaro.org/blog/scaling-linux-kernel-quality-automating-bisection-in-kernelci/));
I read only its search summary.

---

### 9. What this means for sqlearn

What sqlearn has today, from `docs/specs/selection-by-group.md` and
`docs/architecture/testing.md`: three hand-declared C++ groups (`core`, `raw`,
`crash`) growing with the port; a fingerprint per group of comment-stripped
sources with line numbers kept, compile entries and the fingerprints of the
groups it depends on; a shared part (bindings, extension, pins, build tables,
compiler, flags) that reruns everything; Python test sets and 24 runners that
claim groups, with "unknown means affected"; records of passed runs keyed by
those identities; a coverage-instrumented `just audit-groups` that fails when a
claim is too small; and full tiers (`just full`, `just validate-all`,
`just verify`) run by hand. There is no CI yet (spec §2); the full validation
takes about 47 minutes; benchmarks run only on Tomas's go-ahead (ADR 0072).

#### Where the design already sits among the industry's

- **It is build-graph selection plus input-keyed caching**, the TAP/Bazel
  model (§1–2) at the grain of a group, which is the coarse grain the
  literature recommends for safety and cost (§6). The shared part's "rerun
  everything" plays the role of gn analyze's "Found dependency (all)" for build
  configuration and LLVM's "test everything if CI scripts change".
- **The hand-declared claims are of the same kind as LLVM's
  `DEPENDENTS_TO_TEST`, Chromium's `location_filters` and Mozilla's
  `SCHEDULES`.** Of these, Mozilla shares sqlearn's default (an undeclared file
  affects everything), and Chromium runs its hand-filtered tests on CI anyway.
  LLVM's tables have no check I could find. sqlearn's audit is the
  stronger guard: it is the analogue of Azure TIA's advice to run the selection
  and then everything and compare, done by coverage instead of by a second run.
- **The comment-stripping with line numbers kept** is Ekstazi's smart checksum
  with the very exception Ekstazi names, tests that observe line numbers through
  exceptions (§2), decided the conservative way.
- **The known holes of coverage selection** (static initialisation, data files,
  new code, compiled code: the spec's option C) are the ones the literature
  lists (§5 table). Industry tools that use coverage either fall back to "run
  everything" when unsure or accept misses and run everything later.

#### Ideas that fit today (one developer, one machine, a few groups)

1. **A backstop: a full run at a fixed cadence, not only at release.** Every
   system that skips tests pairs it with a periodic full run: Mozilla every 20
   pushes or 4 hours, Meta's stabilisation every few hours, Azure TIA's
   recommended periodic run, THEO's "every test at least once before trunk",
   TAP's milestones. In sqlearn the full tiers exist but are run by hand
   (`just verify` before `1.0.0`). A cadence (every N commits on `main`, or
   before each group of the port merges) bounds how long a too-small claim or
   an undeclared input can hide. Its cost is the 47-minute validation plus the
   suites; the cadence is Tomas's call, and the sources give no number for a
   project of this size.
2. **Measure misses from those full runs.** Meta measures recall by running
   all dependent tests on a sample of changes (§4); Azure suggests comparing a
   selected run with a full one (§5). sqlearn can do this from records it
   already keeps: when a full run fails a test or runner that selection would
   have skipped, that is a selection miss, and it should fail loudly and name
   the missing claim or input, as the audit does for claims.
3. **Keep the fallbacks that the sources use.** "Unknown means affected"
   matches Mozilla's default and gn analyze's "all"; the line in
   `testing.md` that everything reruns when `compile_commands.json` or the
   manifest is missing matches TIA's fallback. Bazel's `external` tag is a
   reminder that any check reading something outside its recorded inputs must
   be marked as always-run; the tooling set's hand-kept `TOOLING_INPUTS`, with
   its test that scans for literal paths, is sqlearn's guard against the gn
   analyze hole (a file no target references counts as no dependency).
4. **Treat thread-order anomalies as flakes, explicitly.** `HANDOFF.md` records
   that a `just verify` rerun can flip a large-set result to "anomaly" by
   thread order (ADR 0016). The flakiness literature (§7) shows why this
   matters for selection: a selector that skips on a passed record cannot tell
   a skipped real failure from a flake. Recording such reruns as flaky, rather
   than discarding them silently, would keep the record honest; the cost is
   small at this size.

#### Ideas that do not fit today, and why

- **Predictive / ML selection (Meta, Mozilla, FastLane, THEO).** Each needs a
  large history of failures with flakes separated, regular full runs to
  measure recall, and retraining with someone watching (§4). sqlearn keeps the
  20 newest records per runner, a pass/fail memory, not a training set; the
  docs do not say how often sqlearn's checks fail, so whether enough data would
  ever exist is unknown. Its gain is also on a selection already much smaller
  than "everything", which sqlearn does not have yet (today every Python test
  and runner depends on all three groups).
- **Batching with culprit finding, merge queues, auto-revert.** These exist
  because many changes land concurrently and tests run after landing (TAP: more
  than one change a second; Meta: concurrent lands; Uber: thousands a day).
  sqlearn's checks run before each commit and before work is called done, on
  one machine, so a failure already names one change. They become relevant
  only with item 1: a failing backstop covers N commits, and `git bisect` over
  them, with the records' identities telling which commits could affect the
  failing set (as FACF drops changes the graph rules out), is the small
  version of culprit finding.
- **Per-test coverage selection inside a group (spec approach B), Echelon-
  or Ekstazi-style.** The spec leaves it for later; the sources show what it
  would cost: an instrumented build and a record per test, a policy for new
  code (Echelon's heuristic, TIA's "always run new tests"), tracking of files
  read (Ekstazi), and a full run behind it. Google chose not to use coverage at
  its scale; Microsoft's TIA is limited to managed code on one machine.
- **Depth-trimmed graph selection (BTD's `depth`, TAP's "more than 10 edges
  hardly ever break").** Both are statements about graphs with millions of
  targets. With up to about fifteen groups, the closure is small; trimming it
  would trade safety for little.

#### When a heavier approach would be worth it (the signs)

The project is meant to grow beyond scikit-learn's scope: an exploration app, a
node-based workflow editor, possibly its own models
(`docs/architecture/overview.md`). The sources tie each heavier mechanism to a
condition; whether sqlearn reaches it depends on facts the docs do not state
(contributors, CI machines, suite sizes).

| Mechanism | Worth adopting when | Evidence from the sources |
| --- | --- | --- |
| Backstop full runs at a cadence | as soon as selection skips anything a full run would catch; that is now | Mozilla, Meta, Azure TIA, THEO |
| Finer groups or per-test selection inside a group | when one group's claimed tests take long enough that `just test` while working is slowed by tests of code you did not touch, and the group cannot sensibly be split | Ekstazi saved 32% of end-to-end time on average, 54% on longer suites; class-level static selection matched it (§5–6). The sources do not say at what suite size this pays off |
| Splitting presubmit from postsubmit (fast checks before commit, slow ones on CI after) | when a CI machine exists (Phase 1 step 3 brings release-tier workflows started by hand) and the slow tier no longer fits before every commit | Google's 95%+ presubmit pass-through; Chromium's CI-only tests; Meta's stages |
| Merge queue | when several people or agents land on `main` concurrently, so changes that pass alone can break together | Meta §II; GitHub merge queue; SubmitQueue |
| Culprit finding beyond `git bisect`, and flake-aware bisection | when failures are found after several commits (from a backstop or postsubmit) and some checks are non-deterministic | Google FACF; KernelCI's notes on misleading bisections |
| Predictive selection | only after all of the above, with a failure history large enough to train on and full runs to measure recall; none of the sources ran it without both | Meta, Mozilla, FastLane |
| Language-aware graphs for the applications (a front end, a second language) | when a new part's tests cannot be placed by the C++ group graph; then a per-part mapping with "unknown means everything" (Mozilla `SCHEDULES`, Pants' changed-dependents), checked as the audit checks claims | §1 |

One caution recurs in every source: selection is only as safe as its declared
inputs, and every organisation that skips tests also runs everything regularly
and has a way to notice what it skipped. sqlearn has the first half (the
audit, the fallbacks); a regular full run, and comparing it with what selection
would have done, is the part the industry has and sqlearn does not yet.

---

## Part B: tools for sqlearn's stack

Researched 2026-11-27. No build, test or benchmark of sqlearn was run (only
`cmake --version`, `ninja --version`, `ninja -d list`, `ninja -t list`, and
reading `engine/build/dev/Testing/Temporary/CTestCostData.txt`).

### 0. What sqlearn does now (the baseline every option is compared with)

From `docs/specs/selection-by-group.md`, `docs/architecture/testing.md`
("Selecting by group", "The validation runners"), `engine/cmake/groups.cmake`,
`validation/_groups.py`, `validation/__main__.py`, `validation/_ctest.py`,
`validation/_audit.py`:

- **Grain = C++ group.** `sq_add_group(name SOURCES … DEPENDS … PYTHON_TESTS …
  VALIDATION … BENCH …)` builds an object library per `engine/src/<name>/` and
  writes `<build>/sq_groups.json` (the manifest with the claims).
- **Fingerprints** (`validation/_groups.py`): per group, the SHA-256 of its
  sources and the in-tree headers its compile entries read, with comments
  stripped via `clang -Xclang -dump-raw-tokens` but line numbers kept, plus its
  normalised compile entries from `compile_commands.json`, plus the
  fingerprints of the groups it depends on; a **shared part** covering every
  other compile entry, generated files, submodule pins, `pyproject.toml`'s build
  tables, the compiler and the module's link command. Headers come from `-M`,
  falling back to Ninja's deps log. CMake text is never read. Anything
  unreadable raises `Unreadable` and everything reruns.
- **Python**: tests run in sets (tooling, `group:<name>`, unclaimed), each with
  its own record; any change under `src/` reruns every library set (the Python
  library is frozen, ADR 0070). Unclaimed means "depends on every group".
- **Validation runners**: each records the SHA-256 of every repository module
  it imported, `uv.lock`, every file under `devdata/data/`, the environment and
  the group fingerprints; a matching passed record skips it. Runners run **one
  after another**, each in its own process (`validation/__main__.py`, the
  `for name in runners:` loop with `subprocess.run`), and a failing one does not
  stop the rest.
- **C++ tests**: CTest labels are groups; a label's identity hashes commands,
  program bytes, loaded libraries, `REQUIRED_FILES` and compile entries
  (`validation/_ctest.py`). Each label runs as its own `ctest -L ^label$
  --output-on-failure`, without `-j` (`_run_label`).
- **The audit** (`just audit-groups`, `validation/_audit.py`): a wheel with
  sqlearn's C++ under clang source-based coverage, each set and runner run with
  its own `LLVM_PROFILE_FILE`, `llvm-cov export -summary-only` mapping covered
  files to groups; fails when a claim is too small. Its first real run awaits
  the owner's go-ahead (`HANDOFF.md`).

In the vocabulary of the literature this is **module-level (group-level),
static, conservative selection with content-addressed result records**, plus a
**dynamic audit** that checks the static declarations. Keep that in mind: most
tools below are either a different grain of the same idea, or a different way
to learn the dependency edges.

---

### 1. Whole build systems

#### 1.1 Bazel (+ rules_cc, rules_python, nanobind-bazel, bazel-diff, target-determinator)

**What it does.** Every build and test is an action keyed by the hash of its
declared inputs; a test's result is reused while its inputs are unchanged
(`--cache_test_results=auto`, the default, reruns a test only when its inputs
changed or it failed; the `external` tag forces a rerun:
https://bazel.build/docs/user-manual,
https://bazel.build/reference/test-encyclopedia). A local `--disk_cache` holds
action results across clean builds (https://bazel.build/remote/caching).
`bazel query 'rdeps(//..., //engine/src/core:x.cpp)'` gives the reverse
dependencies of a file within a universe; plain `query` ignores configurations
and over-approximates `select()`, `cquery` resolves them
(https://bazel.build/query/language). Sharding: `shard_count`, with the runner
reading `TEST_TOTAL_SHARDS`/`TEST_SHARD_INDEX`
(https://bazel.build/reference/test-encyclopedia).

- **bazel-diff** (https://github.com/Tinder/bazel-diff): hashes every target
  from its rule implementation, attributes, source contents (directories hashed
  as trees) and the `.bzl` files that instantiated it, recursively; diffing two
  revisions' hash files gives the impacted targets. Needs Bazel 8+ and Bzlmod
  for its module integration. Module extensions are coarse: one generated repo
  bump can impact much of the workspace.
- **target-determinator**
  (https://github.com/bazel-contrib/target-determinator): runs `cquery` on both
  commits and hashes the results; cache keyed on git tree SHA, pattern, Bazel
  version and options; warns that environment variables and bazelrc can give
  spurious differences; tested exhaustively only on the latest LTS.

**Fit for sqlearn.**
- C++: `cc_library` per group would replace `sq_add_group`; the `DEPENDS`
  closure, header tracking and flag tracking would come from Bazel's graph
  instead of `_groups.py`. Catch2, RapidCheck, cpptrace and nanobind are in the
  Bazel Central Registry (checked with `gh api` against
  `bazelbuild/bazel-central-registry/modules`: `catch2`, `rapidcheck`,
  `cpptrace`, `nanobind`, `nanobind_bazel` present). nanobench was not found
  there.
- **DuckDB has no Bazel build**: no `duckdb` module in the BCR (404), no
  `BUILD`/`MODULE.bazel` at the top of `duckdb/duckdb`, and
  `duckdb/duckdb-python` builds with CMake through `pyproject.toml` (directory
  listing via `gh api`). sqlearn's own DuckDB build is the `duckdb` module built
  from source with sqlearn's C++ inside one binary (CLAUDE.md, ADR 0060/0061).
  Under Bazel this means either writing and maintaining BUILD files for DuckDB
  and duckdb-python's bindings (the submodules are "never edited", so overlay
  BUILD files), or wrapping their CMake build with `rules_foreign_cc` as one
  opaque action (then any submodule change is one big input, which is what the
  shared part already does). rules_foreign_cc was not researched in depth here.
- Python: `nanobind_extension` builds the `.so` and is used as a `data`
  dependency of a `py_library`/`py_test`
  (https://github.com/nicholasjng/nanobind-bazel, v3.1.0.bcr.1, 2026-10-05), so
  **yes, a `py_test` that loads one C++ extension module is supported**, but
  the test then depends on the whole `.so`: any change in any group linked into
  it reruns every Python test that loads it. That is **coarser** than today's
  scheme, where a Python set depends only on its claimed groups' fingerprints
  plus the shared part. Getting group grain back under Bazel would need the
  same hand-declared claims (a set "depends on" `//engine/src/decomposition`
  without really linking it separately), i.e. today's design re-expressed in
  Starlark.
- uv: rules_python's `pip.parse` accepts `uv.lock`
  (https://rules-python.readthedocs.io/en/latest/pypi/lock.html), so the lock
  can stay; but `uv run`, `uv sync` and the scikit-build wheel build (the
  shipped artefact, ADR 0005) would either be replaced by Bazel rules or run
  beside Bazel, i.e. two build systems.
- Validation runners: each would be a `py_test` with `devdata/data/**` as
  `data`; Bazel's result cache would replace `validation/_record.py`. A
  runner's failure-handling rule ("a failing case reruns every time") matches
  Bazel's default.
- Comment-insensitivity: Bazel hashes file **contents**; a comment edit changes
  the input and reruns the compile and the tests downstream (unless the
  compiled output is byte-identical; Bazel does prune on unchanged outputs, but
  a line-number change in `PreconditionError`'s message would not be
  byte-identical, which matches sqlearn's chosen rule anyway). No source found
  for an option to strip comments before hashing; sqlearn's `stripped()` has no
  Bazel counterpart.

**Cost.** Migration: rewrite `engine/CMakeLists.txt`, `engine/cmake/*.cmake`,
presets (sanitizers, coverage, Mull, fuzzing, LLVM vs Apple clang toolchains),
the `just` recipes and the `validation/` check machinery that reads CTest and
`compile_commands.json`; write or wrap DuckDB's build; keep a CMake build for
the wheel or move wheel-building to Bazel. Maintenance: Bazel version upgrades,
BCR pins, a JDK for bazel-diff's Bazel. Not quantified by any source found.

**What it can miss.** Anything not declared: tests "ought to access only those
resources on which they have a declared dependency"
(test encyclopedia); on macOS, sandboxing is weaker than Linux's (not
confirmed in depth here). Environment drift (target-determinator's own
warning). Same class of risk as sqlearn's hand-kept `TOOLING_INPUTS`, but
enforced by the sandbox where it works.

#### 1.2 Buck2

**What it does.** Single dynamic graph, remote execution as the primary model,
local execution as a special case; its own docs say the open-source use without
remote execution "may be less polished", toolchains are not open-sourced, and
there are no release-mode mechanisms yet (https://buck2.build/docs/about/why/).
The prelude has `cxx_python_extension.bzl`, `python_test.bzl` and
`python_needed_coverage_test.bzl` (directory listing of
`facebook/buck2/prelude/python` via `gh api`), so Python tests over a C++
extension are modelled. Releases are date-tagged pre-releases
(`gh release list -R facebook/buck2`: `2026-11-15`, `2026-11-01`, all marked
Pre-release).

**Fit.** Same migration as Bazel (DuckDB BUILD files, toolchains), with fewer
ready rules (no nanobind ruleset found) and a model built for a remote farm,
which sqlearn does not have (CLAUDE.md: one machine, no CI yet).

**Cost / miss.** Higher than Bazel for this stack; same declared-input caveats.

#### 1.3 Pants

**What it does.** `--changed-since=<ref> --changed-dependents=transitive` runs
targets affected by files changed in git; dependencies are inferred from
imports; a lockfile or `python_requirements` change marks all users of a
dependency as changed
(https://www.pantsbuild.org/stable/docs/using-pants/advanced-target-selection).
Pants' own welcome page lists Python, Go, Java, Scala, Kotlin and Shell, and
does not mention C or C++
(https://www.pantsbuild.org/stable/docs/introduction/welcome-to-pants).

**Fit.** It would not build the engine; the C++ would stay under CMake and
reach Pants as one opaque artefact, so every Python test would depend on the
whole module again. Not a fit while the library is being rewritten into C++
(ADR 0070).

---

### 2. CMake/CTest/Ninja-native options

#### 2.1 CTest labels, `--rerun-failed`, fixtures, `--out-of-date`

From https://cmake.org/cmake/help/latest/manual/ctest.1.html and
https://cmake.org/cmake/help/latest/release/4.5.html:

- `-L`/`-LE` regexes, combined with "and" when repeated: sqlearn already uses
  labels as groups.
- `--rerun-failed`: only last run's failures; ignores other filters.
- `--tests-from-file`/`--exclude-from-file`: exact names; a selection computed
  outside CTest can be handed in this way.
- `--show-only=json-v1`: sqlearn already reads it (`_ctest.py`).
- Fixtures (`FIXTURES_SETUP/REQUIRED`, `-FA/-FS/-FC`): ordering and setup, not
  selection.
- **`--out-of-date` (new in CMake 4.5)**: "run only tests whose recorded build
  dependencies are newer than the last time the tests ran", where dependencies
  are the executables in the test's `COMMAND`, `BUILD_DEPENDS` outputs and
  discovered executables; tests with no known dependencies are excluded. The
  local CMake is 4.5.1. This is **timestamp-based on the test program**, so a
  ccache hit or a touched header that rebuilds identical objects can still
  relink; sqlearn already defeats that by hashing program bytes with
  `ZERO_AR_DATE` (`sq_stable_link`). It does not see `REQUIRED_FILES` data
  unless declared, and excludes rather than includes unknowns, the opposite of
  sqlearn's "unknown means affected". **Adds nothing** over `_ctest.py`'s
  identities; worth knowing, not adopting.

**Cost to add:** none needed.

#### 2.2 `cmake --graphviz` and the file API

The file API's codemodel (targets, sources, link dependencies) could replace
the hand-written `sq_groups.json` writer for the "sources and DEPENDS" half; the
claims (`PYTHON_TESTS`, `VALIDATION`, `BENCH`) are not build facts and would
still need a custom property. Spec §6 already leaves "CTest properties, a
generated file, `cmake --graphviz`" to the builder. Not fetched in detail in
this research; the claim that the file API exposes target sources and
dependencies is from general knowledge of CMake and **not confirmed against the
docs here**.

#### 2.3 Ninja's logs (`-t deps`, `-t query`, `-t multi-inputs`, `-d explain`)

Ninja 1.13.2 is installed (`ninja -t list`): `deps` (the `.ninja_deps` header
lists), `query` (inputs/outputs of a path), `inputs` (all inputs needed to
rebuild targets), `multi-inputs` (per-target input sets; the manual notes this
"can be helpful if one would like to know which targets that are affected by a
certain input"), `-d explain` (why a command ran), and `-n` (dry run)
(https://ninja-build.org/manual.html; `ninja -d list`). sqlearn already falls
back to the deps log when `-M` fails (`docs/architecture/testing.md`).
`multi-inputs` could replace part of `_groups.py`'s per-entry header discovery
(one call for all objects rather than one `-M` per source), and `ninja -n -d
explain <test target>` would say whether a test program is stale. Neither is
content-based, so comments still count; they are speed-ups for the existing
fingerprint, not a different design.

#### 2.4 Ordering by cost and failures: `CTestCostData.txt`, `COST`, `--schedule-random`

CMake's scheduler (`Source/CTest/cmCTestMultiProcessHandler.cxx`, master,
https://gitlab.kitware.com/cmake/cmake/-/raw/master/Source/CTest/cmCTestMultiProcessHandler.cxx):
in parallel runs, "previously failed tests [are added] to the front", then tests
by descending cost (a weighted average kept in
`Testing/Temporary/CTestCostData.txt`, with failed names after `---`); in serial
runs stored costs are not used and failed tests get no priority
(https://cmake.org/cmake/help/latest/prop_test/COST.html confirms descending
cost order under `-j`). `--schedule-random` randomises order to expose hidden
inter-test dependencies. sqlearn runs each label without `-j`, so none of this
applies; and its C++ tests are quick today (the `dev` cost file holds averages
of 0.1–1.6 s per test). **Not worth changing now**; worth `-j` with cost data
once a group's tests take minutes.

---

### 3. Python side

#### 3.1 pytest-testmon (current state)

Latest v2.4.1 (2026-11-26); v2.4.0 adds teeing testmon.net results to
`.testmondata`; v2.3.1 makes the xdist controller decide the selection once and
send it to workers; v2.3.0(b0) performance and fingerprint lookup fixes; v2.2.0
drops Python 3.8/3.9, adds pytest 9 (`gh release view` on
`tarpas/pytest-testmon`). Mechanism, from its blog and source: per-file blocks
with checksums, coverage.py lines per test
(https://testmon.org/blog/determining-affected-tests/); the environment key
includes every installed distribution's version (`get_system_packages` over
`importlib.metadata.distributions()` in `testmon/common.py`); `SourceTree` reads
Python source files only (`testmon/testmon_core.py`, `process_code.py`).
Options: `--testmon`, `--testmon-noselect`, `--testmon-nocollect`,
`--testmon-forceselect`, `--no-testmon`, `--testmon-env`,
`--testmon-singleprocess`, `--tmnet` (`testmon/pytest_testmon.py`).

**Holes from `HANDOFF.md` re-checked:** no release note or source path found
that tracks data files or compiled code; the per-package version key still
means sqlearn's version (which carries the commit hash, `HANDOFF.md`) changes
the environment on every commit. The xdist change in 2.3.1/2.3.0b0 concerns
the selection decision, not the "tests left out by marker are never recorded"
hole; **not confirmed fixed**. Verdict unchanged: not usable alone.

#### 3.2 pytest-difftest, pytest-rts, pytest-ekstazi

- **pytest-difftest** (https://github.com/PaulM5406/pytest-difftest, pushed
  2026-02-23): testmon's idea with a Rust AST parser, block-level checksums,
  xdist support, failing tests always reselected. Same coverage-of-Python-lines
  basis, so the same holes for C++ and data files.
- **pytest-rts** (WithSecureOpenSource, last push 2021-05-17) and
  **pytest-ekstazi** (Igorxp5, last push 2022-10-08; per-test file
  dependencies stored in `ekstazi.json`): unmaintained by their push dates.
  Ekstazi's real idea (file-level dependencies, including non-code files) is
  better done by hand, below.

#### 3.3 pytest-picked

Runs tests from test files and folders that git reports as changed
(unstaged or branch mode), or those first (`--picked=first`); it does not
follow source changes (README of `anapaulagomes/pytest-picked`, v0.5.1,
2024-11-06). Useful only as an ordering hint.

#### 3.4 pytest's cache: `--lf`, `--ff`, `--nf`, `--sw`, `--lfnf`

https://docs.pytest.org/en/stable/how-to/cache.html: `--lf` reruns only last
failures; `--ff` runs the whole suite with last failures first; `--nf` new
tests first; both `--ff` and `--nf` then sort by file mtime; `--sw` stops at the
first failure and resumes there; `--lfnf=none` runs nothing when nothing failed.
**Fit:** `--ff` (and possibly `--nf`) on each Python set costs one flag in
`validation/_pytest_sets.py` (`PASSES`, which already passes `-n auto`), selects
nothing away, and surfaces a repeat failure earlier. How xdist's scheduler
treats collection order under `-n auto` was **not confirmed** here, so the gain
under xdist is uncertain. `--lf` is not a selection substitute (it skips tests
whose code changed).

#### 3.5 coverage.py dynamic contexts

`dynamic_context = test_function` records per-test line coverage into the
`.coverage` SQLite file
(https://coverage.readthedocs.io/en/latest/contexts.html). The `sysmon` core
(default from 3.14) "does not yet support plugins, dynamic contexts", and on
3.12/3.13 not branch coverage
(https://coverage.readthedocs.io/en/latest/config.html), so per-test contexts
need the slower `ctrace` core. This is the raw material of "approach B" (spec
§4); it adds nothing to group selection, and only Python lines.

#### 3.6 Import graphs: grimp, import-linter, pydeps

grimp builds a queryable import graph of a package, with
`find_downstream_modules` / `find_upstream_modules` and an option to exclude
`TYPE_CHECKING` imports (README and `docs/usage.rst` of `seddonym/grimp`,
pushed 2026-11-13); import-linter is built on it (pushed 2026-11-18); pydeps
draws graphs (v3.0.9, 2026-10-01). **Fit:** static and cheap, it could split
"any change under `src/` reruns every library set" by package. But sqlearn's
docs say `import sqlearn` loads the whole package (spec §5.3) and the Python
library is frozen and shrinking (ADR 0070), so the payoff is small and falling;
it also misses `importlib`/string imports and data files. The validation
records already capture the **dynamic** import set per runner, which is
stronger than grimp's static one.

#### 3.7 Ekstazi-style file tracking with audit hooks (no maintained tool)

CPython's audit events include `open(path, mode, flags)`, `import(module,
filename, …)`, `os.listdir(path)` and `ctypes.dlopen(name)`; files opened in C
(an extension's `fopen`) are not audited unless that code calls `PySys_Audit`
(https://docs.python.org/3/library/audit_events.html). A `sys.addaudithook`
in a pytest plugin could record, per test set or runner, every file opened from
Python (data files under `devdata/`, `tests.json`, CMake files read by tooling
tests). **Fit:** a dynamic check of the hand-kept `TOOLING_INPUTS` list and of
each runner's data inputs, complementing the existing static scan of literal
paths (`docs/architecture/testing.md`, "The Python sets"). It cannot see
DuckDB reading a Parquet or CSV file from C++, which is exactly how much of the
validation data would be read. Note also `HANDOFF.md`: a `-p` pytest plugin
loads before coverage and testmon start, so it must import nothing of sqlearn.

---

### 4. C++ coverage for selection

Clang source-based coverage: `LLVM_PROFILE_FILE` with `%p`/`%Nm`/`%b` per
process, `%c` continuous mode (Darwin only) that survives crashes and signals,
`llvm-profdata merge -sparse`, `llvm-cov export` JSON; exceptions and
`longjmp` can make counts inaccurate; the page gives no overhead figures
(https://clang.llvm.org/docs/SourceBasedCodeCoverage.html). sqlearn's audit
already uses this per set and per runner (`validation/_audit.py`).

Tools that select C++ tests from coverage: **BinaryRTS**
(https://github.com/tum-i4/binary-rts, research tool, last push 2023-07-25):
DynamoRIO-based per-test function and file-access traces, Linux/Windows, macOS
only through Docker, GoogleTest-oriented listener. Not usable on Apple silicon
macOS natively by its README. A search found RTS++ (static call-graph LLVM pass,
GoogleTest) only as a paper (https://par.nsf.gov/biblio/10099901); no
maintained open-source tool for Catch2 + llvm-cov selection was found.

**Fit:** the audit's machinery could, if wanted, produce per-test-case maps
(Catch2 test case → covered files) and drive approach B for C++, but today the
C++ suites take seconds, so selection inside a group buys nothing yet. The
valuable use of coverage stays what it is now: **checking** declared groups,
not choosing tests. One gap worth noting: if a coverage run crashes or a child
calls `_exit`, profiles may be lost; `%c` continuous mode (Darwin) is the
documented remedy, and could make the audit robust to the crash tests.

---

### 5. Ordering and parallelism instead of (or beside) selection

- **pytest `--ff`/`--nf`**: §3.4.
- **CTest** failed-first and cost order only under `-j`: §2.4.
- **Validation runners**: today they run serially and all of them run even
  after a failure (`validation/__main__.py`). Two cheap changes the sources
  support in principle: (a) run first the runners whose newest record failed
  (the records already know: "a run with a failing case reruns every time"),
  then by descending recorded wall time, CTest-style; (b) run several runner
  processes at once. (b) is uncertain: each runner drives DuckDB, which uses
  threads, and DuckDB sums doubles in thread-finish order (`HANDOFF.md`, ADR
  0043), and memory limits matter (`HANDOFF.md`'s `memory_limit` traps). How
  many cores a runner already uses is **not known from the docs**; `HANDOFF.md`
  lists "record each validation runner's wall time" as next up, which is the
  prerequisite for both (a)'s ordering and for judging (b). Measuring wall time
  inside the normal validation is not a benchmark run, but whether it counts as
  one under ADR 0072 is for the owner to say.
- **Bazel-style sharding** (`TEST_TOTAL_SHARDS`) is the same idea as (b) with
  a protocol; adds nothing without Bazel.

---

### 6. Content-addressed caching of results

- **Bazel** caches a test's result keyed by the hash of its declared input
  closure, locally (`--disk_cache`) or remotely; `--cache_test_results=auto`
  reruns on input change or failure (§1.1).
- **Nix**: a derivation's identity is its content-addressed serialisation,
  including its inputs (https://nix.dev/manual/nix/latest/store/derivation/);
  a test written as a derivation is cached by that identity; on macOS the
  sandbox has Darwin-specific profile and host-path settings (same page). It
  would need sqlearn's whole toolchain (Apple clang via `xcrun`, Homebrew LLVM)
  inside Nix or declared impure; not researched further.
- **How sqlearn's records differ:**
  1. **The key is chosen, not complete.** Bazel and Nix key on every declared
     input byte; sqlearn keys on a *semantic* fingerprint (comments stripped,
     line numbers kept, checkout path and uv's random build path removed,
     version cut to its release, `release()`), which is why a comment edit
     reruns nothing. No source found for an equivalent in Bazel or Nix.
  2. **The key is learned after the run for runners** (the modules a runner
     actually imported, hashed before import), close to Ekstazi; Bazel's is
     declared before.
  3. **Records are shared across worktrees** through git's common directory,
     like a local disk cache, and never leave the machine (ADR 0006), like a
     disk cache without a remote.
  4. **Failure semantics** match Bazel's: failures are not cached as passes.
  5. **What Bazel/Nix add**: a sandbox that turns an undeclared input into a
     failure rather than a silent stale pass. sqlearn's equivalents are the
     audit (C++), the literal-path scan (tooling) and the dynamic import record
     (runners). An audit-hook record (§3.7) would close part of the remaining
     Python-side gap.

---

### 7. Ranked shortlist

The direction (Tomas, 2026-11-27, and
`docs/architecture/overview.md` §1, §2, §3.6, §3.7): sqlearn grows beyond
scikit-learn's scope, with an EDA application and a node-based workflow editor
that "bring a browser front end"; "more packages later, the applications among
them, laid out so that adding one moves nothing"; where the applications live
is an open question (`docs/questions/applications-home.md`). No CI farm, team
size or front-end language is stated, so the "later" ranking says where it
depends on them.

#### 7.1 Worth adding to the current approach

| Rank | What | Today (one machine, 3 → ~15 groups) | Later (multi-part repo) | Reason |
|---|---|---|---|---|
| 1 | **Run the audit** (`just audit-groups`) and keep it the check of claims | Highest value | Still needed while groups are hand-declared | It is the only thing that proves a claim is not too small; already built, awaiting go-ahead (`HANDOFF.md`). |
| 2 | **Failed-first, then longest-first ordering of validation runners**, from the records plus recorded wall time | Cheap; earlier feedback in a 47-minute run | Same | Mirrors CTest's documented scheduler; selects nothing away, so it cannot miss anything. Needs the wall-time recording already in "Next up". |
| 3 | **pytest `--ff` on each Python set** | One flag | Same | Documented pytest behaviour; no selection risk. Gain under xdist not confirmed. |
| 4 | **Audit-hook file recording** (`open`/`import` events) for the tooling set and runners | Small plugin | More valuable as non-C++ inputs grow | Dynamic check of hand-kept input lists; blind to files opened from C++ (DuckDB), so it complements, never replaces, the records. |
| 5 | **Ninja `-t multi-inputs`/deps log** as the header source in `_groups.py` | Optional speed-up | Same | Same facts, fewer clang calls; does not change what is fingerprinted. |
| 6 | **Parallel validation runners** | Only after wall time and per-runner core use are known | Same | Could cut wall time, but DuckDB threading, memory and ADR 0043's order-dependence make the gain unknown; measure first. |

#### 7.2 Would replace it

| What | Today | Later | Reason |
|---|---|---|---|
| **Bazel** (+ nanobind-bazel, rules_python with `uv.lock`, bazel-diff or target-determinator) | Not worth it | The candidate if the repo becomes several packages and languages | Handles C++, Python and (with rulesets not researched here) front-end code in one graph with content-addressed test caching. But DuckDB has no Bazel build, the wheel and `uv run` flow would be duplicated or replaced, a Python test depends on the whole `.so` (coarser than group claims unless the claims are re-expressed), and comment-insensitivity is lost. |
| **Buck2** | Not worth it | Only with a remote-execution setup, which nothing in the docs plans | Its docs call local-only use less polished and toolchains not open-sourced; releases are pre-releases. |

#### 7.3 Not worth it

| What | Reason |
|---|---|
| pytest-testmon, pytest-difftest | Python-line coverage only; blind to C++ (where the code is moving, ADR 0070) and data files; testmon's environment key changes each commit. |
| pytest-rts, pytest-ekstazi | Unmaintained (last pushes 2021, 2022). |
| pytest-picked | Changed test files only, not sources. |
| grimp/import-linter for selection | `import sqlearn` loads the whole package and the Python library is frozen and shrinking; runners already record dynamic imports. (import-linter may still be useful for architecture rules, outside this question.) |
| CTest `--out-of-date` | Timestamp-based, excludes unknowns; `_ctest.py`'s byte identities are stricter. |
| Pants | No C/C++ support on its own pages. |
| BinaryRTS / per-test C++ coverage selection | Research tool, DynamoRIO, not native on macOS; C++ suites take seconds today. |
| Nix for test caching | Would have to own the whole Apple toolchain; adds a sandbox but no comment-insensitive key. |

#### 7.4 Migration path if groups are kept now and Bazel (or Buck2) is wanted later

**Carries over:**
- The **group boundaries** (`engine/src/<group>/` with `DEPENDS`) map one to one
  onto `cc_library` targets; the inventory
  (`docs/architecture/engine-inventory.md`) is already the package layout.
- The **claims** (`PYTHON_TESTS`, `VALIDATION`, `BENCH`) become `deps`/`data`
  or tags on `py_test` targets; the audit's per-set coverage mapping
  (`validation/_audit.py`) stays useful to check them, since Bazel cannot tell
  which code inside one `.so` a Python test runs either.
- **CTest labels and `REQUIRED_FILES`** map to `cc_test` and `data`.
- The runners' **"each in its own process, one result file"** shape maps to one
  `py_test` per runner; their failure semantics match Bazel's.
- The **rules**: unknown means affected; nothing leaves the machine (a local
  `--disk_cache` only); benchmarks never run from a check (Bazel tags such as
  `manual` would keep them out of `//...`; not checked against Bazel docs here).

**Thrown away:**
- `validation/_groups.py` (fingerprints, comment stripping, `release()`),
  `_ctest.py`'s identities, `_record.py`, `_checks.py`'s records,
  `sq_groups.json`: Bazel's action keys replace them, and with them the
  comment-insensitive key.
- The CMake build of sqlearn's C++ (unless kept for the wheel), the presets
  and the `just` glue that drives them.

**Kept regardless:** DuckDB's own build would need BUILD overlays or a
wrapped CMake action; this is the largest single cost and does not shrink by
waiting.

**Signs it is time** (each is observable in the repository; none is asserted
to have happened):
- A second compiled language or a front-end build joins the repo and needs its
  own selection logic beside `_groups.py`.
- Several packages (the applications, ADR-level "more packages later") whose
  tests depend on each other across package lines, so per-package records
  start re-implementing a cross-package graph.
- `_groups.py`'s special cases grow (each new generated file, path or version
  rule like `release()`), or the audit keeps finding under-declared claims.
- A shared cache across machines becomes wanted (CI from Phase 1 step 3, more
  than one developer machine): Bazel's disk/remote cache does this natively;
  sqlearn's records are per clone's git directory. Whether and when this
  happens depends on facts the docs do not state.
- Clean-build or cold-cache time, not test time, dominates (the ~24 s rebuild
  per commit in `HANDOFF.md` is the current data point).

Until then, the cheapest insurance is to keep groups aligned with directories
and `DEPENDS` honest (the audit enforces the latter), so a later move is a
mechanical translation rather than a redesign.
