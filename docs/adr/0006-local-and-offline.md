---
type: adr
tags: [local-first, offline, privacy, data-residency, architecture]
summary: "ADR 0006 decides sqlearn runs locally and offline with no cloud, telemetry, or network access, so data never leaves the machine."
mdindex: [type=0fc814, tags=50d3e9, summary=ea14d2, related=98b680]
related: [docs/adr/0053-sqlearn-ships-no-datasets.md, docs/architecture/overview.md]
---
# 0006: Local and offline

Status: accepted (2026-11-03, from the earlier attempt's blueprint). Its line on
example datasets is replaced by [ADR 0053](0053-sqlearn-ships-no-datasets.md).

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
