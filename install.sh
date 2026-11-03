#!/usr/bin/env bash
# Install mdindex and the project-init skill globally.
#   ./install.sh            install
#   ./install.sh --dry-run  show what would change, change nothing
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
dry=""
[[ "${1:-}" == "--dry-run" ]] && dry="--dry-run"

bin="$HOME/.local/bin/mdindex"
skill="$HOME/.claude/skills/project-init"

if [[ -n "$dry" ]]; then
  echo "would copy   $here/tools/mdindex/mdindex.py -> $bin (mode 755)"
  echo "would link   $skill -> $here/skills/project-init"
else
  mkdir -p "$(dirname "$bin")" "$(dirname "$skill")"
  install -m 755 "$here/tools/mdindex/mdindex.py" "$bin"
  if [[ -e "$skill" && ! -L "$skill" ]]; then
    echo "error: $skill exists and is not a symlink; move it away first" >&2
    exit 1
  fi
  ln -sfn "$here/skills/project-init" "$skill"
  echo "installed    $bin"
  echo "linked       $skill"
fi

python3 "$here/tools/install_hooks.py" $dry

command -v qmd >/dev/null || echo "note: qmd not found; run: npm install -g @tobilu/qmd"
