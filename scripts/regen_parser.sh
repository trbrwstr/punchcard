#!/usr/bin/env bash
# Regenerate the vendored COBOL85 lexer/parser from grammar/Cobol85.g4.
#
# The generated files are committed so runtime and CI need only
# antlr4-python3-runtime. This script is for maintainers regenerating after a
# grammar change or an ANTLR version bump. Requires a JDK.
set -euo pipefail

# Keep this in sync with antlr4-python3-runtime in pyproject.toml.
ANTLR_VERSION="4.13.2"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
grammar_dir="${repo_root}/punchcard/backend/parser/grammar"
out_dir="${repo_root}/punchcard/backend/parser/_generated"
jar="$(mktemp -d)/antlr-${ANTLR_VERSION}-complete.jar"

echo "Fetching ANTLR ${ANTLR_VERSION} tool jar from Maven Central..."
curl -fsSL -o "${jar}" \
  "https://repo1.maven.org/maven2/org/antlr/antlr4/${ANTLR_VERSION}/antlr4-${ANTLR_VERSION}-complete.jar"

echo "Generating Python lexer/parser/listener..."
tmp_out="$(mktemp -d)"
for grammar in Cobol85.g4 Cobol85Preprocessor.g4; do
  java -jar "${jar}" -Dlanguage=Python3 -o "${tmp_out}" \
    -lib "${grammar_dir}" "${grammar_dir}/${grammar}"
done

# Keep only the runtime Python modules; drop .interp/.tokens build artifacts.
cp "${tmp_out}"/Cobol85Lexer.py "${tmp_out}"/Cobol85Parser.py "${tmp_out}"/Cobol85Listener.py "${out_dir}/"
cp "${tmp_out}"/Cobol85PreprocessorLexer.py "${tmp_out}"/Cobol85PreprocessorParser.py \
   "${tmp_out}"/Cobol85PreprocessorListener.py "${out_dir}/"

echo "Done. Generated modules refreshed in ${out_dir}."
echo "Review the diff and run: uv run pytest"
