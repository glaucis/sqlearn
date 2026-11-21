---
type: adr
tags: [licence, apache-2-0, open-source, dependencies, cla]
summary: "ADR 0004 records the decision to license sqlearn under Apache-2.0, with rules on dependencies, trademark, contributor CLA and credit."
mdindex: [type=0fc814, tags=927ddc, summary=38c1e4, related=bc4d08]
related: [docs/adr/0057-numpy-is-a-runtime-dependency.md, docs/adr/0005-runtime-dependencies.md, ADR-0057, ADR-0005]
---
# 0004: Apache-2.0 licence

Status: accepted (decided 2026-10-01 in the earlier attempt; carried over
2026-11-03). Amended by
[ADR 0066](0066-permissive-licences-never-copyleft.md) (2026-11-21): runtime
code may carry any permissive licence the OSI approves, never copyleft.

## Context

sqlearn is meant to be used as widely as scikit-learn is, by companies and
public bodies included. Any money is to come from products built on top of it,
never from the library itself.

## Decision

- The library is licensed Apache-2.0, free for any use.
- Money, if it comes, comes from a product on top: the applications, a
  professional edition of them, support. Anything paid is a separate package
  from the start, since what is released free stays free.
- Every runtime dependency is permissively licensed: MIT, BSD, Apache, PSF
  (`duckdb` and `numpy`, [ADR 0057](0057-numpy-is-a-runtime-dependency.md)).
  Copyleft is allowed in development tools only.
- The name is protected by a trademark, registered when there is something to
  protect.
- A CLA covers every outside contributor before their first contribution, so
  that relicensing, and a sale, stay possible.
- Credit is asked for, never required: `CITATION.cff` and an acknowledgement
  page at the first release.

## Consequences

- `LICENSE` holds the Apache-2.0 text from the foundation onwards; `NOTICE`
  and `CITATION.cff` arrive with the first release.
- A new runtime dependency's licence is checked before it is added
  ([ADR 0005](0005-runtime-dependencies.md)).
- No outside contribution is merged before the CLA exists.
