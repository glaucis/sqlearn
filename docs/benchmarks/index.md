---
type: note
tags: [benchmarks, performance, sqlearn, index]
summary: "Index page listing sqlearn benchmark pages against similar libraries, with archived old-Python measurements and their rerun status."
mdindex: [type=edb465, tags=8a3784, summary=db9933]
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
