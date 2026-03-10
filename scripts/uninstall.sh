#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/echoclip"
APP_BIN="$PREFIX/bin/echoclip"
APPLICATION_DESKTOP="$PREFIX/share/applications/echoclip.desktop"
AUTOSTART_DESKTOP="$HOME/.config/autostart/echoclip.desktop"

rm -rf "$APP_DIR"
rm -f "$APP_BIN" "$APPLICATION_DESKTOP" "$AUTOSTART_DESKTOP"

echo "Removed EchoClip from $PREFIX"
