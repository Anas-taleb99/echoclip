#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/echoclip"
BIN_DIR="$PREFIX/bin"
APP_BIN="$BIN_DIR/echoclip"
LEGACY_BIN="$BIN_DIR/winv_clipboard.py"
APPLICATIONS_DIR="$PREFIX/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
LEGACY_AUTOSTART="$AUTOSTART_DIR/winv-clipboard.desktop"

command -v python3 >/dev/null
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
if [[ "$PYTHON_BIN" != /* ]]; then
    PYTHON_BIN="$(command -v "$PYTHON_BIN")"
fi

python_has_gtk() {
    "$1" - <<'PY'
import gi
gi.require_version("Gtk", "3.0")
PY
}

if ! python_has_gtk "$PYTHON_BIN"; then
    if [[ "$(uname -s)" == "Linux" ]] && [[ -x /usr/bin/python3 ]] && python_has_gtk /usr/bin/python3; then
        PYTHON_BIN=/usr/bin/python3
    else
        cat >&2 <<'EOF'
EchoClip install failed: Python cannot import gi (PyGObject / GTK bindings).

Install Linux dependencies first, for Arch:
  ./scripts/install-deps-arch.sh

If you use pyenv/venv and system packages are installed, rerun with:
  PYTHON_BIN=/usr/bin/python3 ./scripts/install.sh
EOF
        exit 1
    fi
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$APPLICATIONS_DIR" "$AUTOSTART_DIR"

rm -rf "$APP_DIR/echoclip"
cp -R "$ROOT_DIR/src/echoclip" "$APP_DIR/"
cp "$ROOT_DIR/LICENSE" "$APP_DIR/"
cp "$ROOT_DIR/README.md" "$APP_DIR/"

"$PYTHON_BIN" - <<PY
from pathlib import Path

target = Path("$APP_BIN")
app_dir = Path("$APP_DIR")
python_bin = "$PYTHON_BIN"
target.write_text(
    f"#!{python_bin}\n"
    "import sys\n"
    f"sys.path.insert(0, {str(app_dir)!r})\n"
    "from echoclip.app import main\n"
    "raise SystemExit(main())\n",
    encoding="utf-8",
)
PY
chmod +x "$APP_BIN"

"$PYTHON_BIN" - <<PY
from pathlib import Path

target = Path("$LEGACY_BIN")
app_dir = Path("$APP_DIR")
python_bin = "$PYTHON_BIN"
target.write_text(
    f"#!{python_bin}\n"
    "import sys\n"
    f"sys.path.insert(0, {str(app_dir)!r})\n"
    "from echoclip.app import main\n"
    "raise SystemExit(main())\n",
    encoding="utf-8",
)
PY
chmod +x "$LEGACY_BIN"

sed "s|Exec=echoclip|Exec=$APP_BIN|g" \
    "$ROOT_DIR/assets/echoclip.desktop" \
    > "$APPLICATIONS_DIR/echoclip.desktop"

sed "s|Exec=echoclip|Exec=$APP_BIN|g" \
    "$ROOT_DIR/assets/echoclip-autostart.desktop" \
    > "$AUTOSTART_DIR/echoclip.desktop"

rm -f "$LEGACY_AUTOSTART"

echo "Installed EchoClip to $PREFIX"
