#!/bin/bash
# Install/reinstall flotte as a uv tool

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Uninstalling existing version..."
uv tool uninstall flotte 2>/dev/null || true

echo "Clearing uv cache..."
uv cache clean

echo "Installing from $SCRIPT_DIR/flotte..."
uv tool install "$SCRIPT_DIR/flotte" --force --reinstall

echo "Done. Run 'flotte' to start."
