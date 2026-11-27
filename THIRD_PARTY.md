---
type: note
tags: [licences, third-party, dependencies, compliance, duckdb]
summary: "Lists every third-party library compiled into sqlearn's wheel with its version, SPDX licence, licence text and source paths, plus development-only libraries."
related: [ADR 0066, NOTICE, validation/_licences.py, uv.lock, engine/CMakeLists.txt, engine/cmake/cpptrace.cmake, engine/duckdb-python/external/duckdb/extension/icu/README.md]
mdindex: [type=edb465, tags=0c9b92, summary=0ad6f9, related=9914e3]
---
# Third-party code

sqlearn's wheel compiles other projects' code into its one binary, `_duckdb`
(DuckDB, its Python module and sqlearn's own C++, built from the submodules
under `engine/`). Each library compiled in is listed here with its version,
its licence as an SPDX expression and its licence text. Each carries a
permissive licence the Open Source Initiative approves, never a copyleft one
(ADR 0066); where a library offers a choice, sqlearn takes the permissive one
(zstd: BSD-3-Clause; mbedtls: Apache-2.0). `NOTICE` holds each one's
licence text and notices.

`just check-licences` (`validation/_licences.py`) checks this file against
the wheel's last build: every source file it compiled and every include
directory it read lies in a library below, in sqlearn's own code or in the
system's SDK; every input of `_duckdb`'s link (`build.ninja`) was built in
that build or is the system's; every licence is one ADR 0066 allows; and
numpy, the one runtime dependency, declares licences it allows too (ADR
0066's amendment allows its 0BSD and CC0-1.0 for numpy alone). The paths are
those of the build's compile database
(`build/<cache tag>/compile_commands.json`): `<build>` is that build
directory, and a path holding `*` is a pattern for a directory outside the
repository, such as the build environment's `site-packages`.

## Compiled into the wheel

| Library | Version | Licence | Licence text | Compiled from |
| --- | --- | --- | --- | --- |
| DuckDB | 2.0.1 (`8d78114e90`) | MIT | [LICENSE](engine/duckdb-python/external/duckdb/LICENSE) | `engine/duckdb-python/external/duckdb/src` `engine/duckdb-python/external/duckdb/extension/core_functions` `engine/duckdb-python/external/duckdb/extension/json` `engine/duckdb-python/external/duckdb/extension/parquet` `engine/duckdb-python/external/duckdb/extension/icu` `engine/duckdb-python/external/duckdb/extension/loader` `engine/duckdb-python/external/duckdb/tools` `<build>/duckdb-python/duckdb` |
| Unicode CLDR 48 and UCD 17.0.0 data, Unicode's time zone data (IANA 2026f), in DuckDB's icu extension | DuckDB 2.0.1's | Unicode-3.0 | [Unicode License v3](https://www.unicode.org/license.txt) | `engine/duckdb-python/external/duckdb/extension/icu/collation/generated` `engine/duckdb-python/external/duckdb/extension/icu/datetime/generated` |
| duckdb-python | 2.0.1 (`de8eed7`) | MIT | [LICENSE](engine/duckdb-python/LICENSE) | `engine/duckdb-python/src` `<build>/duckdb-python` |
| Brotli | 1.1.0 | MIT | [LICENSE](engine/duckdb-python/external/duckdb/third_party/brotli/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/brotli` |
| concurrentqueue | DuckDB 2.0.1's | (BSD-2-Clause OR BSL-1.0) AND Zlib | [LICENSE](engine/duckdb-python/external/duckdb/third_party/concurrentqueue/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/concurrentqueue` |
| fast_float | DuckDB 2.0.1's | MIT | [LICENSE](engine/duckdb-python/external/duckdb/third_party/fast_float/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/fast_float` |
| FastPFor | DuckDB 2.0.1's | Apache-2.0 | [LICENSE](engine/duckdb-python/external/duckdb/third_party/fastpforlib/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/fastpforlib` |
| {fmt} | 6.1.2 | MIT | [LICENSE](engine/duckdb-python/external/duckdb/third_party/fmt/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/fmt` |
| FSST | DuckDB 2.0.1's | MIT | [LICENSE](engine/duckdb-python/external/duckdb/third_party/fsst/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/fsst` |
| cpp-httplib | 0.53.1 | MIT | [LICENSE](engine/duckdb-python/external/duckdb/third_party/httplib/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/httplib` |
| HyperLogLog, with Redis's sds | DuckDB 2.0.1's | MIT AND BSD-3-Clause | [LICENSE](engine/duckdb-python/external/duckdb/third_party/hyperloglog/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/hyperloglog` |
| jaro_winkler | DuckDB 2.0.1's | MIT | [LICENSE](engine/duckdb-python/external/duckdb/third_party/jaro_winkler/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/jaro_winkler` |
| LZ4 | 1.9.4 | BSD-2-Clause | [LICENSE](engine/duckdb-python/external/duckdb/third_party/lz4/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/lz4` |
| Mbed TLS | 3.6.7 | Apache-2.0 OR GPL-2.0-or-later | [LICENSE](engine/duckdb-python/external/duckdb/third_party/mbedtls/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/mbedtls` |
| miniz | 10.0.3 | MIT | [LICENSE](engine/duckdb-python/external/duckdb/third_party/miniz/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/miniz` |
| Apache Parquet's Thrift definitions | DuckDB 2.0.1's | Apache-2.0 | [LICENSE](engine/duckdb-python/external/duckdb/third_party/parquet/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/parquet` |
| PCG random | DuckDB 2.0.1's | MIT | [LICENSE](engine/duckdb-python/external/duckdb/third_party/pcg/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/pcg` |
| pdqsort | DuckDB 2.0.1's | Zlib | [LICENSE](engine/duckdb-python/external/duckdb/third_party/pdqsort/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/pdqsort` |
| RE2 | DuckDB 2.0.1's | BSD-3-Clause | [LICENSE](engine/duckdb-python/external/duckdb/third_party/re2/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/re2` |
| ska_sort | DuckDB 2.0.1's | BSL-1.0 | [LICENSE](engine/duckdb-python/external/duckdb/third_party/ska_sort/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/ska_sort` |
| SkipList | DuckDB 2.0.1's | MIT | [LICENSE](engine/duckdb-python/external/duckdb/third_party/skiplist/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/skiplist` |
| Snappy | 1.2.1 | BSD-3-Clause | [LICENSE](engine/duckdb-python/external/duckdb/third_party/snappy/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/snappy` |
| t-digest | DuckDB 2.0.1's | Apache-2.0 | [LICENSE](engine/duckdb-python/external/duckdb/third_party/tdigest/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/tdigest` |
| Apache Thrift (C++ library) | DuckDB 2.0.1's | Apache-2.0 | [LICENSE](engine/duckdb-python/external/duckdb/third_party/thrift/thrift/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/thrift` |
| utf8proc | 2.9.0 | MIT AND Unicode-DFS-2015 | [LICENSE](engine/duckdb-python/external/duckdb/third_party/utf8proc/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/utf8proc` |
| vergesort | DuckDB 2.0.1's | MIT | [LICENSE](engine/duckdb-python/external/duckdb/third_party/vergesort/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/vergesort` |
| yyjson | 0.9.0 | MIT | [LICENSE](engine/duckdb-python/external/duckdb/third_party/yyjson/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/yyjson` |
| Zstandard | 1.5.6 | BSD-3-Clause OR GPL-2.0-only | [LICENSE](engine/duckdb-python/external/duckdb/third_party/zstd/LICENSE) | `engine/duckdb-python/external/duckdb/third_party/zstd` |
| nanobind | 3.1.0 | BSD-3-Clause | [LICENSE](https://github.com/wjakob/nanobind/blob/v3.1.0/LICENSE) | `*/site-packages/nanobind` |
| robin-map (nanobind's) | 1.4.0 | MIT | [LICENSE](https://github.com/Tessil/robin-map/blob/v1.4.0/LICENSE) | `*/site-packages/nanobind/ext/robin_map` |
| NumPy's C headers | 2.5.4 | BSD-3-Clause | [LICENSE.txt](https://github.com/numpy/numpy/blob/v2.5.4/LICENSE.txt) | `*/site-packages/numpy` |
| CPython's C API headers | 3.12 (the stable ABI) | PSF-2.0 | [LICENSE](https://docs.python.org/3/license.html) | `*/include/python3.*` |
| cpptrace, with its libdl symbol back-end | 1.0.4 (`3db8da8`) | MIT | [LICENSE](engine/third_party/cpptrace/LICENSE) | `engine/third_party/cpptrace` `<build>/third_party/cpptrace` |

Notes:

- **DuckDB's icu extension** no longer builds ICU: it carries its own code
  (DuckDB's, MIT) and tables generated from Unicode's data
  (`extension/icu/README.md`, and the headers of
  `collation/generated/collation_data.cpp` and
  `datetime/generated/tz_data.cpp`). The submodule has no separate licence
  file for that data; the row gives Unicode's licence for its data files.
- **utf8proc's** data (`utf8proc_data.c`) is derived from Unicode's data
  files under Unicode's 1991-2007 terms, whose text matches SPDX's
  Unicode-DFS-2015. ADR 0066's amendment (2026-11-24) counts Unicode's data
  licence as permissive; `validation/_licences.py` allows it for utf8proc's
  row alone.
- **cpptrace** is built with its symbol back-end set to libdl (the
  system's `dladdr`) and, on macOS, its unwinding to the system's libunwind
  (`engine/cmake/cpptrace.cmake`). Its default back-end on macOS and Linux,
  libdwarf, is LGPL-2.1 and would be fetched at configure time with zstd;
  neither is configured, fetched or compiled. Of cpptrace's own files, those
  for libdwarf compile to nothing without it.
- **Not compiled in:** DuckDB's `third_party/catch` and `third_party/imdb`
  (its tests), `third_party/jemalloc` (a Linux extension the wheel does not
  build) and its other extensions. A Linux build that compiles jemalloc
  would fail the check until a row is added.
- `engine/duckdb-python/external/duckdb/third_party` itself is on
  duckdb-python's include path, as the parent of the libraries above; no
  file includes through it, so it is no library of its own.

## Development only, never shipped

These build or test sqlearn's C++ and are never compiled into the wheel:
the test programs and the benchmarks link them, in a preset's build alone
(`engine/CMakeLists.txt`). The Python tools of development (ruff, gersemi
and the rest) are in `uv.lock`'s development groups, not here.

| Library | Version | Licence | Licence text |
| --- | --- | --- | --- |
| Catch2 | 3.16.1 | BSL-1.0 | [LICENSE.txt](engine/third_party/catch2/LICENSE.txt) |
| RapidCheck | commit `2c3c436` (no tags) | BSD-2-Clause | [LICENSE.md](engine/third_party/rapidcheck/LICENSE.md) |
| nanobench | 4.6.0 | MIT | [LICENSE](engine/third_party/nanobench/LICENSE) |
| Mull (`just fetch-mull`, not a submodule) | 0.39.1 | Apache-2.0 | [LICENSE](https://github.com/mull-project/mull/blob/0.39.1/LICENSE) |
