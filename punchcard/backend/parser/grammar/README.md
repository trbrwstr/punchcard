# COBOL85 grammar

`Cobol85.g4` (the program grammar) and `Cobol85Preprocessor.g4` (the
COPY/REPLACE preprocessor grammar) are from the
[antlr/grammars-v4](https://github.com/antlr/grammars-v4/tree/master/cobol85)
project (© 2017 Ulrich Wolffgang / proleap.io), distributed under the BSD
3-clause license — see the copyright header inside each file.

The Python lexer/parser are generated from it into
`punchcard/backend/parser/_generated/` and committed, so that runtime and CI need
only `antlr4-python3-runtime` (no Java). Punchcard walks the resulting parse tree
in `punchcard/backend/parser/cobol_listener.py` to build its IR.

## Regenerating

The generated files are checked in. To regenerate after changing the grammar or
bumping the ANTLR version, run:

```bash
scripts/regen_parser.sh
```

This requires a JDK (the ANTLR tool is a Java program); the tool jar is fetched
from Maven Central and must match the `antlr4-python3-runtime` version pinned in
`pyproject.toml`.
