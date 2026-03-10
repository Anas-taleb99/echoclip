#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/echoclip"
APP_BIN="$PREFIX/bin/echoclip"
LEGACY_BIN="$PREFIX/bin/winv_clipboard.py"
APPLICATION_DESKTOP="$PREFIX/share/applications/echoclip.desktop"
AUTOSTART_DESKTOP="$HOME/.config/autostart/echoclip.desktop"
LEGACY_AUTOSTART_DESKTOP="$HOME/.config/autostart/winv-clipboard.desktop"

rm -rf "$APP_DIR"
rm -f "$APP_BIN" "$LEGACY_BIN" "$APPLICATION_DESKTOP" "$AUTOSTART_DESKTOP" "$LEGACY_AUTOSTART_DESKTOP"

echo "Removed EchoClip from $PREFIX"
