---
type: adr
tags: [licence, permissive, copyleft, third-party, duckdb, architecture-decision]
summary: "Records that runtime code may carry any permissive OSI-approved licence and never copyleft, widening ADR 0004's list so that DuckDB's bundled libraries fit; amended 2026-11-24 to count Unicode's data licence as permissive and allow numpy's 0BSD and CC0-1.0 for numpy alone."
related: [docs/adr/0004-apache-2-licence.md, docs/adr/0061-sqlearn-ships-its-own-duckdb-build.md, docs/specs/native-engine.md]
---
# 0066: Permissive licences, never copyleft

Status: accepted (2026-11-21). Decided by Tomas on 2026-11-21 with the
[native engine spec](../specs/native-engine.md) (§3.7).
Amends [ADR 0004](0004-apache-2-licence.md). Amended by Tomas
(2026-11-24): Unicode's data licence counts as permissive; numpy's 0BSD and
CC0-1.0 are allowed for numpy alone until numpy leaves the runtime (below).

## Context

[ADR 0004](0004-apache-2-licence.md) allows four licences for runtime
dependencies: MIT, BSD, Apache and PSF. Bundling DuckDB (see
[ADR 0061](0061-sqlearn-ships-its-own-duckdb-build.md)) brings what DuckDB
2.0.0 carries, read from its source package: 26 libraries that ship, plus
ICU. By licence: MIT 13, BSD 6 (jemalloc on Linux only), Apache-2.0 5,
Boost 1, zlib 1. Catch and the IMDB data are test-only.

Three of these sit outside ADR 0004's list: Boost, zlib and Unicode (ICU).
They are as permissive as MIT. Two others offer a choice of licence: zstd
and mbedtls.

Keeping ADR 0004's four licences was considered. It would rule out bundling
DuckDB as it is.

## Decision

- Runtime code may carry any permissive licence the Open Source Initiative
  approves: MIT, BSD, Apache-2.0, PSF, Boost, zlib, Unicode, ISC. Never
  copyleft.
- A library offered under a choice takes the permissive one (zstd: BSD;
  mbedtls: Apache-2.0).
- A third-party file lists every compiled-in library with its version,
  licence and licence text.
- `NOTICE` arrives with the first build that ships third-party code
  (Phase 1). It keeps each library's notices and marks any file sqlearn
  changed, for example code adapted from Sirius (Apache-2.0).

## Consequences

- Phase 1 writes the third-party file and `NOTICE`. It also confirms where
  ICU's source comes from in DuckDB 2.0, and its exact licence.
- A copyleft library, such as GEOS in DuckDB's spatial extension, is never
  compiled in. A user may still install such an extension (ADR 0061).

## Amended (Tomas, 2026-11-24)

- Unicode's data licence (SPDX `Unicode-DFS-2015`, the terms of utf8proc's
  tables inside DuckDB) counts as permissive.
- numpy declares `0BSD` and `CC0-1.0` beside its BSD-3-Clause. Both stay
  allowed for numpy alone until numpy leaves the runtime, after Phase 3, by
  an ADR replacing [ADR 0057](0057-numpy-is-a-runtime-dependency.md).
- `validation/_licences.py` allows each for those rows alone.
