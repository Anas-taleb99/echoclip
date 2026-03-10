#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/echoclip"
BIN_DIR="$PREFIX/bin"
APP_BIN="$BIN_DIR/echoclip"
APPLICATIONS_DIR="$PREFIX/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"

command -v python3 >/dev/null
python3 - <<'PY'
import gi
gi.require_version("Gtk", "3.0")
PY

mkdir -p "$APP_DIR" "$BIN_DIR" "$APPLICATIONS_DIR" "$AUTOSTART_DIR"

rm -rf "$APP_DIR/echoclip"
cp -R "$ROOT_DIR/src/echoclip" "$APP_DIR/"
cp "$ROOT_DIR/LICENSE" "$APP_DIR/"
cp "$ROOT_DIR/README.md" "$APP_DIR/"

python3 - <<PY
from pathlib import Path

target = Path("$APP_BIN")
app_dir = Path("$APP_DIR")
target.write_text(
    "#!/usr/bin/env python3\n"
    "import sys\n"
    f"sys.path.insert(0, {str(app_dir)!r})\n"
    "from echoclip.app import main\n"
    "raise SystemExit(main())\n",
    encoding="utf-8",
)
PY
chmod +x "$APP_BIN"

sed "s|Exec=echoclip|Exec=$APP_BIN|g" \
    "$ROOT_DIR/assets/echoclip.desktop" \
    > "$APPLICATIONS_DIR/echoclip.desktop"

sed "s|Exec=echoclip|Exec=$APP_BIN|g" \
    "$ROOT_DIR/assets/echoclip-autostart.desktop" \
    > "$AUTOSTART_DIR/echoclip.desktop"

echo "Installed EchoClip to $PREFIX"
