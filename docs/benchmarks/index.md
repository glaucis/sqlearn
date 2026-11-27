---
type: note
tags: [benchmarks, performance, sqlearn, comparison]
summary: Index page listing sqlearn benchmark documents that measure speed against the libraries sqlearn imitates.
mdindex: [type=edb465, tags=48b2d8, summary=d0c89c]
related: [docs/benchmarks/onehot-second-run.md, docs/benchmarks/archived/category-lookup.md, docs/benchmarks/standard-deviation.md, docs/benchmarks/median-reach.md, docs/benchmarks/archived/generators-on-many-threads.md]
---
# Benchmarks

How fast sqlearn runs, measured against the libraries it imitates. The pages
measured the old Python, now in `old_python/`
([ADR 0073](../adr/0073-the-old-python-moves-to-old-python.md)), and those
[ADR 0072](../adr/0072-benchmarks-run-on-tomass-go-ahead.md) names are rerun
when their group is rewritten in C++.

```{toctree}
:maxdepth: 1

onehot-second-run
standard-deviation
median-reach
gram-batches
gram-streaming
explore-correlations
explore-larger-than-memory
engine-profile
```

## Archived

Pages that measured only the old Python, which nothing reruns.

```{toctree}
:maxdepth: 1

archived/category-lookup
archived/generators-on-many-threads
```
