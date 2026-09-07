#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND_ROOT="${FRONTEND_ROOT:-$REPOSITORY_ROOT/../frontend}"
UI_PACKAGE="$FRONTEND_ROOT/packages/apps/workflow-mcp-ui"
RUNTIME_PACKAGE="$FRONTEND_ROOT/packages/cdns/for-workflow-settings"
ASSET_DIRECTORY="$REPOSITORY_ROOT/mcp_server/assets"

if [[ ! -f "$FRONTEND_ROOT/pnpm-workspace.yaml" ]]; then
  echo "Frontend workspace not found at: $FRONTEND_ROOT" >&2
  echo "Set FRONTEND_ROOT to the absolute frontend repository path." >&2
  exit 1
fi

echo "Building Workflow MCP UI and settings runtime..."
(
  cd "$FRONTEND_ROOT"
  pnpm --filter @jotforminc/workflow-mcp-ui build:mcp
)

mkdir -p "$ASSET_DIRECTORY"
cp "$UI_PACKAGE/build/mcp-app.html" "$ASSET_DIRECTORY/workflow-mcp-ui.html"
cp "$RUNTIME_PACKAGE/build/for-workflow-settings.js" "$ASSET_DIRECTORY/workflow-settings-runtime.js"

echo "Updated packaged assets:"
echo "  $ASSET_DIRECTORY/workflow-mcp-ui.html"
echo "  $ASSET_DIRECTORY/workflow-settings-runtime.js"
