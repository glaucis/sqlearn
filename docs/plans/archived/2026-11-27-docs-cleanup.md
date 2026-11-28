---
type: note
tags: [docs-cleanup, archiving, adr, markdown-links, implementation-plan]
summary: "Implementation plan to archive outdated ADRs, specs, plans and questions into archived/ folders, with a link-check test and archiving rules."
related: [docs/plans/archived/2026-11-27-old-python.md, docs/plans/archived/2026-11-27-bazel-prototype.md, docs/adr/index.md, docs/architecture/workflow.md, CLAUDE.md, HANDOFF.md, tests/docs/test_links.py]
mdindex: [type=edb465, tags=399bd1, summary=9782f5, related=15558a]
---
# The docs cleanup: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** The active docs say only what is true now. Every plan that is
implemented, spec that is built or belongs to the old Python, question that
is answered, and ADR that no longer holds moves to an `archived/` folder
beside it, so `docs/adr/`, `docs/specs/`, `docs/plans/` and
`docs/questions/` list only current work. A permanent check keeps every link
working.

**Architecture:** First a link check, test-first, so every later move is
proved not to break a link. Then a classification of every document, shown
to Tomas before anything moves. Then the moves with `git mv`, the links
rewritten, the ADRs' status lines and index updated, and the rule for
archiving written down so future work follows it.

**Tech Stack:** Markdown, MyST, Sphinx, pytest, `git mv`, `just`.

**Spec:** Tomas's request of 2026-11-27: review the ADRs, specs, plans and
other Markdown; remove what is old or redundant; consolidate; an `archived/`
subfolder beside each, so there is less clutter. ADR numbers are kept (they
are cited in code, tests, commits and GitHub issues); consolidating means a
new ADR that supersedes several, never a renumbering.

## Global Constraints

- `git mv`, never copy-and-delete. Nothing is deleted: what is out of date
  is archived.
- **ADR numbers never change**, and an archived ADR keeps its file name.
- An archived document is not edited, except its status line (ADRs) and its
  links where a move broke them.
- Every task runs through `just`; before each commit `just check` and
  `just test` pass; at the end `just done`.
- British English in prose. Commit messages: Conventional Commits, scopes
  only `hooks`, `site`, `deps`, lines at most 72 characters, no attribution.
- The docs tagger's frontmatter is committed on its own, as
  `docs: refresh the docs index frontmatter`, after checking each
  `related:` path exists.
- No reason is attributed to Tomas that he did not give.

## Review Focus

1. **A link broken by a move**: a relative Markdown link in an active or
   archived file pointing at a file that moved. Task 1's test pins it.
2. **A `related:` path in frontmatter that no longer exists**: the tagger
   and humans both rely on them. Task 1's second test pins it.
3. **An ADR archived that a current rule still rests on**: `CLAUDE.md`'s
   "Rules from the ADRs" cites it. Task 2's list checks each archived ADR
   against `CLAUDE.md`; Task 4's grep pins it.
4. **The site losing an ADR page**: archived ADRs stay on the site, under
   their own heading. Task 4's `just build-docs` (warnings as errors) pins
   it.
5. **Tooling that reads a docs path**: only `validation/_audit.py`'s
   docstring names one today (`docs/specs/selection-by-group.md`). Task 3's
   grep pins it.

---

### Task 1: A check that every link resolves

**Files:**

- Create: `tests/docs/test_links.py`
- Modify: `validation/_checks.py` (`TOOLING_INPUTS`: add `docs`, every
  tracked `*.md` the test reads), only if the tooling-input scan asks for it

**Interfaces:**

- Produces: `broken_links(root: Path) -> list[str]` and
  `missing_related(root: Path) -> list[str]` in `tests/docs/test_links.py`,
  each a list of `"<file>:<line>: <target>"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_relative_link_resolves():
    """A relative link in any tracked Markdown file names a file that exists."""
    assert broken_links(REPO) == []


def test_every_related_path_exists():
    """Every path in a file's `related:` frontmatter exists."""
    assert missing_related(REPO) == []


def test_a_broken_link_is_found(tmp_path):
    """The check finds a link to a missing file, with its line."""
    (tmp_path / "a.md").write_text("See [b](b.md).\n")
    assert broken_links(tmp_path) == ["a.md:1: b.md"]
```

      Scope: Markdown files git tracks, outside `engine/duckdb-python`,
      `engine/third_party` and `old_python/`; links without a scheme
      (`http:`, `https:`, `mailto:`), the `#anchor` cut off; a `related:`
      entry is a path from the root. `tmp_path` is not a git repository:
      walk it with `rglob` when `git ls-files` fails.
- [ ] **Step 2:** `uv run --locked pytest tests/docs/test_links.py -q`:
      expect the third to fail (no function) and, once written, the first
      two to name today's broken links, if any. Name each.
- [ ] **Step 3:** Write the two functions; fix each broken link or
      `related:` path the first run names (in an archived or old document,
      fix the link only).
- [ ] **Step 4:** `just check`, `just test`: PASS. Commit:
      `test: check that every Markdown link and related path resolves`.

### Task 2: The classification, shown to Tomas

**Files:**

- Create: `docs/plans/2026-11-27-docs-cleanup-list.md`

- [ ] **Step 1:** Classify every file of `docs/adr/` (73), `docs/specs/`
      (21), `docs/plans/` (31) and `docs/questions/` (13 and
      `earlier-attempts/`), and `docs/architecture/`, `docs/agents/`,
      `docs/benchmarks/`, `docs/validation/`, one row each:
      `| file | verdict | why | what replaces it |`. Verdicts:
      - **keep**: true now, or work still ahead.
      - **archive**: a plan implemented; a spec built or of the old Python;
        a question answered (its ADR cited); an ADR superseded, or whose
        subject is only the old Python (for example the Python compositor's
        SQL, `sq.load`'s Python rules), with what replaces it if anything.
      - **amend**: an ADR still true in part: the part that changed, and
        which ADR changed it.
      - **consolidate**: several ADRs on one subject whose current rule is
        spread across them: the proposed new ADR's title and the ones it
        supersedes.
      Read each file; batch the reading to subagents by folder, each told to
      give no reason the file itself does not give, then check their rows.
- [ ] **Step 2:** For each **archive** ADR, `git grep -n "<number>"
      CLAUDE.md docs/architecture`: an ADR a current rule cites is
      **amend**, not archive.
- [ ] **Step 3:** Commit the list alone
      (`docs: list what the docs cleanup keeps and archives`), and stop:
      show Tomas the counts per verdict and every **consolidate** row. The
      next tasks start only on his go-ahead, with his changes to the list.

### Task 3: The moves

**Files:**

- Create: `docs/adr/archived/`, `docs/specs/archived/`,
  `docs/plans/archived/`, `docs/questions/archived/`, each with a
  one-paragraph `README.md`: what is archived here and that it is not
  current
- Move: every **archive** row of the approved list, with `git mv`

- [ ] **Step 1:** `git mv` each archived file into its folder's
      `archived/`. `docs/questions/earlier-attempts/` goes whole.
- [ ] **Step 2:** Rewrite each relative link to a moved file, in every
      tracked Markdown file (a link into `archived/`, or out of it, gains or
      loses `archived/` and `../`), and each `related:` path. Use a one-off
      script in the scratchpad; do not commit it.
- [ ] **Step 3:** `git grep -n -E "docs/(adr|specs|plans|questions)/"
      -- ':!docs' ':!old_python'`: repoint each hit (`validation/_audit.py`'s
      docstring among them).
- [ ] **Step 4:** `uv run --locked pytest tests/docs/test_links.py -q`:
      PASS. `just check`, `just test`: PASS. Commit:
      `docs: archive the implemented plans, built specs and old ADRs`.

### Task 4: The ADRs' status and index

**Files:**

- Modify: each **amend** ADR's status line; each archived ADR's status line;
  `docs/adr/index.md`
- Create: one ADR per approved **consolidate** row (next free numbers)

- [ ] **Step 1:** An archived ADR's status line gains `Archived
      (2026-11-27): <why, from the list>; see ADR <n>` where something
      replaces it. An **amend** ADR's gains `Amended by ADR <n>` with the
      part changed.
- [ ] **Step 2:** Each consolidating ADR states the current rule in full,
      names the ADRs it supersedes, and gives no reason they do not give;
      each superseded one is archived as in Step 1.
- [ ] **Step 3:** `docs/adr/index.md`: the current ADRs by topic as today,
      then one section, "Archived", listing every archived ADR by number
      with its one-line reason.
- [ ] **Step 4:** `git grep -n -E "\b0[0-9]{3}\b" CLAUDE.md`: every ADR the
      rules cite is a current one (not archived), or the rule cites its
      replacement.
- [ ] **Step 5:** `rm -rf docs/_build && just build-docs`: `build
      succeeded`, no warning. `just check`, `just test`: PASS. Commit:
      `docs: mark the archived and amended ADRs, consolidate <subjects>`.

### Task 5: The rule for archiving

**Files:**

- Modify: `CLAUDE.md` ("Project tools", "Docs layout"),
  `docs/architecture/workflow.md`, `docs/specs/README.md`,
  `docs/plans/README.md`, `docs/questions/README.md`, `docs/adr/README.md`,
  `HANDOFF.md`

- [ ] **Step 1:** The rule, in `CLAUDE.md`'s "Docs layout" and in
      `workflow.md`: when a plan is implemented, it moves to
      `docs/plans/archived/` in the work's last commit; a spec when what it
      describes is built or replaced; a question when it is answered (its
      answer moved into the right doc); an ADR when it is superseded or
      its subject is gone, its status line saying why. Each folder's
      `README.md` says the same in one line.
- [ ] **Step 2:** This plan, `2026-11-27-docs-cleanup-list.md` and
      `2026-11-27-old-python.md` move to `docs/plans/archived/` (both
      implemented); `2026-11-27-bazel-prototype.md` stays.
- [ ] **Step 3:** `HANDOFF.md`: "Just finished" gets the cleanup, with its
      commits; remove what no longer applies.
- [ ] **Step 4:** `just fmt`, `just done`: PASS. Commit:
      `docs: archive work when it is done`. Then the tagger's frontmatter
      on its own, if any.
