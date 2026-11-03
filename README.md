# sqlearn

sqlearn is a machine-learning library in the style of scikit-learn whose
computation runs as SQL inside DuckDB. It works on data larger than memory,
because DuckDB spills to disk and the data never has to leave it.

sqlearn is pre-alpha and holds no usable library yet.

It needs Python 3.12 or newer; see
[the Python versions page](docs/architecture/python-versions.md).

To work on it:

```sh
brew install uv just commitlint
just setup
just --list
```

sqlearn is licensed under the Apache License 2.0.
