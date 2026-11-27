"""Files a result is written to: ``out=sq.out.parquet(path)`` and its kin."""

from sqlearn._output import out_csv as csv
from sqlearn._output import out_json as json
from sqlearn._output import out_parquet as parquet

__all__ = ["csv", "json", "parquet"]
