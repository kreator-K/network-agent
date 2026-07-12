#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_ROOT="$REPOSITORY_ROOT/vendor/google-calendar-mcp"
NODE_MODULES="$VENDOR_ROOT/node_modules"
PACKAGE_JSON="$NODE_MODULES/@cocal/google-calendar-mcp/package.json"
ENTRYPOINT="$NODE_MODULES/@cocal/google-calendar-mcp/build/index.js"
CACHED_NODE_MODULES="/Users/prashant/.npm/_npx/3d994b5e2877c131/node_modules"

package_version() {
  python3 - "$PACKAGE_JSON" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except (OSError, ValueError):
    print("")
else:
    print(data.get("version", ""))
PY
}

if [[ "$(package_version)" == "2.6.2" && -f "$ENTRYPOINT" ]]; then
  exit 0
fi

if [[ -d "$CACHED_NODE_MODULES" ]]; then
  mkdir -p "$NODE_MODULES"
  cp -a "$CACHED_NODE_MODULES/." "$NODE_MODULES/"
else
  npm install --prefix "$VENDOR_ROOT"
fi

if [[ "$(package_version)" != "2.6.2" ]]; then
  echo "Expected @cocal/google-calendar-mcp version 2.6.2" >&2
  exit 1
fi

if [[ ! -f "$ENTRYPOINT" ]]; then
  echo "Expected Google Calendar MCP entry point is missing" >&2
  exit 1
fi
