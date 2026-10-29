#!/usr/bin/env bash
# Install the Valuation Model engine at the commit pinned in ENGINE, as an editable checkout
# (the engine reads its configs/ folder from the repo, so a plain wheel install can't run it).
set -euo pipefail
cd "$(dirname "$0")/.."
rev="$(cat ENGINE)"
if [ ! -d .engine/valuation/.git ]; then
  git clone --quiet https://github.com/Courtizy/valuation .engine/valuation
fi
git -C .engine/valuation fetch --quiet --depth 1 origin "$rev"
git -C .engine/valuation checkout --quiet "$rev"
pip install --quiet -e .engine/valuation
echo "engine: valuation @ ${rev:0:7}"
