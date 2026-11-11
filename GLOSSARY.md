---
type: note
tags: [glossary, terminology, saved-pipelines, learned-store]
summary: "Glossary defining sqlearn domain terms: recipe, learned part, stable key, and trained model for saved pipelines."
related: [docs/adr/0047-a-pipeline-saves-as-json.md, docs/adr/0048-the-user-saves-the-model-and-imports-its-packages.md]
mdindex: [type=edb465, tags=6224d6, summary=3ac000, related=d90684]
---
# Glossary

Terms of sqlearn's domain, in the sense the code and the docs use them.

- **Recipe:** the part of a saved pipeline that says what to build: each
  step's class and settings, in order, and the model by its class and
  parameters. It holds no data and no learned value, and can be shared
  (`sq.save(pipe, path, learned=False)`).
- **Learned part:** the part of a saved pipeline that holds what its steps
  learned (each step's learned values, the columns and types `apply` needs)
  and the fingerprint of the data they came from. Absent from a recipe.
- **Stable key:** the second key under which the learning store files a
  step's learned values, made of facts that mean the same in every process
  (a file's real path, size and modification time), as opposed to the live
  key, which holds a connection token that only one process knows. Loading a
  saved pipeline fills the store by it.
- **Trained model:** the model library's own object after `train`
  (`pipe.model_`). The user saves and opens it, in any format; a saved
  pipeline never holds it, and `use_model` puts it back.
  _Avoid_: model file.
