---
type: adr
tags: [columns, naming, encoders, onehot, duckdb, api]
summary: "Records how steps name the columns they create: column_label, clashes numbered rather than refused, NULL as the missing category, case unified only by its own step, suffix= only where one column comes out per input."
related: [docs/adr/0020-column-selectors.md, docs/adr/0034-a-grouped-api.md, docs/specs/library-preprocessing.md]
---
# 0035: Names of generated columns

Status: accepted (2026-11-05). Settles
[issue #26](https://github.com/glaucis/sqlearn/issues/26).

## Context

Encoders, indicators, binning and feature makers create columns whose names
come from data or settings. DuckDB keeps the values `"Oslo"` and `"oslo"`
distinct but treats column names without regard to case, so `city_Oslo` and
`city_oslo` clash. The core refused such data; scikit-learn accepts it.

```
city   age  income
Oslo   41   52000
oslo   NULL 61000
NULL   33   48000
```

## Decision

1. A created column is named `<column>_<label>`. Names that clash, compared
   without regard to case, are numbered in sorted order of their labels: the
   first keeps its name, the next get `_2`, `_3`. Nothing is refused, and an
   input column is never renamed. `pipe.columns_out_` shows the final names.

   ```python
   sq.encode.onehot("city")  # city_NULL, city_Oslo, city_oslo_2
   ```

2. The missing category is `<column>_NULL`, created only when NULL was seen
   at `learn` (scikit-learn says `_nan`; a text column holds no NaN, and in
   SQL a missing value is NULL). A text value `'NULL'` beside a real NULL is a
   clash, numbered by rule 1.
3. Case is unified only by its own step, chosen by the user:
   `[sq.transform.lower("city"), sq.encode.onehot("city")]` gives `city_NULL`,
   `city_oslo`. No encoder has a case option.
4. `suffix=` exists only on steps that give one column per input (scaling,
   imputing, transforming). Encoders and feature makers do not take it.
5. `keep=True` names the new column `<column>_<step name>`
   (`sq.scale.robust("age", keep=True)` gives `age` and `age_robust`);
   `suffix="z"` gives `age_z`.
6. Feature makers use scikit-learn's labels, which DuckDB quotes as needed:
   `a^2`, `a*b`, `b^2` for polynomials, `x_sp_0`, `x_sp_1`... for splines.

## Consequences

- Every step that creates columns names them through one shared piece of
  code, tested once, so the rule cannot drift between steps.
- A name a user expected may come out numbered; `columns_out_` and the guide
  page on naming say so.
