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
- **Model file:** the file beside a saved pipeline's JSON that holds the
  trained estimator, written only when asked (`model="pickle"`) and opened
  only when trusted (`trust_model=True`). The JSON names it and its SHA-256.
