---
type: guide
tags: [agents, collaboration, decisions, explanations, tracking]
summary: "How an agent works with Tomas on sqlearn: explain choices with concrete examples, keep his terms, ask one plain question, keep status in one tracker, record everything in repo files."
related: [CLAUDE.md, HANDOFF.md, docs/adr/0046-sqlearn-warns-the-user-chooses.md]
---
# Working with Tomas

Tomas makes sqlearn's decisions himself. These are the habits that let him do
that, learned over the sessions so far.

## Explain with examples

- When a design question is abstract, lead with a small concrete example: a
  pipeline such as impute, scale, one-hot, the SQL it produces, or the code a
  step writes. Then a short table of the options with what each costs, a
  recommendation, and one plain question.
- Say what the thing is for before the trade-off: who uses it (users, the
  docs, the tests, the applications) and when it matters.
- Use his definitions exactly (static and dynamic steps; learn, apply, train,
  predict). Play his words back unchanged before adding anything, and mark
  your own additions as yours. Twice his terms were muddled by mapping them
  onto earlier attempts' meanings.
- Measure before claiming a cost or a speed-up, and say when a number is an
  estimate or the machine was loaded.

## Keep track in one place

- The current state is `HANDOFF.md`; the work is GitHub issues. Status is not
  scattered over many files: before creating a doc, say which issue or
  handoff item it belongs to, update that in the same commit, and prefer
  extending an existing file.
- One ADR per real decision is fine; ADRs stay flat and numbered, and
  `docs/adr/index.md` groups them by topic.
- Rulings made during a build are put to him with their costs; his answers
  go on the issue and, when they set a rule, into an ADR.

## Everything in files, nothing in memory

Nothing is kept in an agent's private memory. What a later session needs is
written into the repository: rules in `CLAUDE.md` and the ADRs, the state of
work in `HANDOFF.md`, decisions on the issues, habits on this page. Web
sessions and other contributors see only the repository.
