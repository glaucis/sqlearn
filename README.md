# sqlearn

sqlearn is a machine-learning library in the style of scikit-learn whose
computation runs as SQL inside DuckDB. It works on data larger than memory,
because DuckDB spills to disk and the data never has to leave it.

sqlearn is pre-alpha: it is being built and is not ready for use. There is no
release yet, and anything may still change. Outside contributions wait for a
contributor licence agreement.

It needs Python 3.12 or newer; see
[the Python versions page](https://glaucis.github.io/sqlearn/dev/architecture/python-versions.html).

To work on it:

```sh
brew install uv just commitlint
just setup
just --list
```

sqlearn is licensed under the Apache License 2.0.
