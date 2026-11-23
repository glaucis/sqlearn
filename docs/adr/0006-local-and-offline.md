---
type: adr
tags: [local, offline, privacy, architecture, data-residency]
summary: "ADR 0006 decides sqlearn runs fully local and offline with no cloud, telemetry, or network access, keeping data on the user's machine."
mdindex: [type=0fc814, tags=ed69f3, summary=864277, related=94e2ff]
related: [ADR-0053, docs/adr/0053-sqlearn-ships-no-datasets.md, ADR-0061, docs/adr/0061-sqlearn-ships-its-own-duckdb-build.md, docs/architecture/overview.md]
---
# 0006: Local and offline

Status: accepted (2026-11-03, from the earlier attempt's blueprint). Its line on
example datasets is replaced by [ADR 0053](0053-sqlearn-ships-no-datasets.md).
Amended by [ADR 0061](0061-sqlearn-ships-its-own-duckdb-build.md) (2026-11-21):
sqlearn's DuckDB never downloads an extension by itself; one the user installs
works.

## Context

sqlearn is for people whose data may not leave the building: companies,
government departments, anyone on an on-premises server or a laptop.

## Decision

The library runs locally and offline: no cloud service, no cluster, no
telemetry, and no network access needed for anything it does. Data never
leaves the machine.

## Consequences

- Example datasets are bundled, or fetched only by an explicit call whose name
  says it fetches.
- The applications ([overview 3.6](../architecture/overview.md), 3.7) run as
  local servers on the user's machine.
- The documentation can be downloaded and used without the internet; the site
  bundles MathJax and builds without network access.
