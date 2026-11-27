---
type: note
tags: [python, legacy, archive, sqlearn, cpp-rewrite]
summary: "Explains that the frozen Python sqlearn library and its tests, validation, data and docs are kept as unrun reference during the C++ rewrite."
related: [old_python/src/sqlearn, old_python/tests, old_python/validation, old_python/devdata, old_python/docs, docs/adr/0073-the-old-python-moves-to-old-python.md]
mdindex: [type=edb465, tags=a7e791, summary=b26bcb, related=cec291]
---
# The old Python

The frozen Python library and everything that tested, validated or
documented it: its code (`src/sqlearn/`), its tests (`tests/`), the
validation runners (`validation/`), the development data (`devdata/`), the
examples and the API docs (`docs/`). Each tree keeps the path it had at the
root. sqlearn is being rebuilt from scratch in C++, and this is kept only as
reference while that happens: nothing here is run, imported or checked, and
each piece is deleted when what replaces it lands.
