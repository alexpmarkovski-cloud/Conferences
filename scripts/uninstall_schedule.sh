#!/usr/bin/env bash
# Remove the weekly updater launchd agent.
set -euo pipefail

LABEL="com.conferences.weekly"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$TARGET"
echo "Removed $LABEL."
