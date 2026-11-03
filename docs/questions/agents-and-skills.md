---
type: question
tags: [agents, skills, workflow, project-setup, documentation]
summary: "Open question listing candidate project agents and skills to create, with the rule for deciding which to make and what each serves."
related: [docs/architecture/workflow.md]
mdindex: [type=1f5087, tags=ae73bf, summary=65bab1, related=4e87fb]
---
# Which project agents and skills do we create?

The rule (proposed, [workflow.md](../architecture/workflow.md)): an agent is
created when a kind of work recurs and needs its own rules; a skill when a
method has to be written down to be repeated. The foundation and the core show
which are needed. Each is researched before it is written.

Candidates:

| Candidate | Kind | What it holds | Serves |
|---|---|---|---|
| `duckdb-algorithms` | skill | expressing an algorithm in SQL over relations, numeric care, testing against the exact reference, checking behaviour on data larger than memory | 3.2, 3.3, 3.8 |
| `estimator-contract` | skill | the fit/transform/predict contract, parameters, validation, naming | 3.3 |
| `numpydoc-docstrings` | skill | the docstring conventions the reference is generated from | 3.3, 3.4 |
| `guide-writing` | skill | the voice and shape of a guide chapter and an executed example | 3.4 |
| `lesson-writing` | skill | the shape of a lesson: assumptions, steps, exercises, what the reader can do after | 3.5 |
| `api-reviewer` | agent | reviews a public API change for consistency with the contract | 3.3 |
| `docs-reviewer` | agent | reviews a chapter or lesson as its reader would | 3.4, 3.5 |
| `release` | skill | the release steps | first release |

Decided by research, then Tomas.
