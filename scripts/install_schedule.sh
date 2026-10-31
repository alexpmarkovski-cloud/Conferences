#!/usr/bin/env bash
# Install the weekly updater as a launchd agent for the current user.
set -euo pipefail

LABEL="com.conferences.weekly"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$REPO/.venv/bin/python"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ ! -x "$PYTHON" ]]; then
  echo "No virtualenv at $REPO/.venv. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

mkdir -p "$REPO/data/logs" "$HOME/Library/LaunchAgents"
sed -e "s|__REPO__|$REPO|g" -e "s|__PYTHON__|$PYTHON|g" \
  "$REPO/launchd/$LABEL.plist.template" > "$TARGET"
plutil -lint "$TARGET" >/dev/null

# Reload if already installed.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$TARGET"

echo "Installed $LABEL → runs Mondays at 08:00."
echo "Run it now:  launchctl kickstart gui/$(id -u)/$LABEL"
echo "Logs:        $REPO/data/logs/"
