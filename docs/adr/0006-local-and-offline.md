---
type: adr
tags: [local, offline, privacy, architecture, no-telemetry]
summary: "ADR accepting that sqlearn runs entirely locally and offline, with no cloud, telemetry, or network dependency for data."
mdindex: [type=0fc814, tags=71e655, summary=4431f5, related=3d8346]
related: [docs/architecture/overview.md]
---
# 0006: Local and offline

Status: accepted (2026-11-03, from the earlier attempt's blueprint)

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
