#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(ROOT_DIR="$ROOT_DIR" python3 - <<'PY'
from pathlib import Path
import re
import os

content = Path(os.environ["ROOT_DIR"]) / "pyproject.toml"
content = content.read_text(encoding="utf-8")
match = re.search(r'^version = "([^"]+)"$', content, re.MULTILINE)
if not match:
    raise SystemExit("version not found in pyproject.toml")
print(match.group(1))
PY
)"

DISTROS=(
  "ubuntu:ubuntu-24.04:install-deps-ubuntu.sh"
  "debian:debian-12:install-deps-debian.sh"
  "fedora:fedora-41:install-deps-fedora.sh"
  "arch:archlinux:install-deps-arch.sh"
)

mkdir -p "$ROOT_DIR/dist"
rm -rf "$ROOT_DIR/dist/echoclip-$VERSION"*

create_bundle() {
  local distro_id="$1"
  local distro_label="$2"
  local deps_script="$3"
  local release_dir="$ROOT_DIR/dist/echoclip-$VERSION-$distro_label"
  local archive="$ROOT_DIR/dist/echoclip-$VERSION-$distro_label-x86_64.tar.gz"
  local checksum="$archive.sha256"

  rm -rf "$release_dir" "$archive" "$checksum"
  mkdir -p "$release_dir"

  cp -R "$ROOT_DIR/src" "$release_dir/"
  cp -R "$ROOT_DIR/assets" "$release_dir/"
  mkdir -p "$release_dir/scripts"
  cp "$ROOT_DIR/scripts/install.sh" "$ROOT_DIR/scripts/uninstall.sh" "$ROOT_DIR/scripts/$deps_script" "$release_dir/scripts/"
  cp "$ROOT_DIR/README.md" "$ROOT_DIR/LICENSE" "$ROOT_DIR/pyproject.toml" "$release_dir/"

  cat > "$release_dir/ALPHA-RELEASE.txt" <<EOF
EchoClip $VERSION
Channel: alpha
Target distro: $distro_id

Install dependencies first:
  ./scripts/$deps_script

Then install the app:
  ./scripts/install.sh
EOF

  tar -C "$ROOT_DIR/dist" -czf "$archive" "echoclip-$VERSION-$distro_label"
  sha256sum "$archive" > "$checksum"
  echo "  $archive"
  echo "  $checksum"
}

echo "Created:"
for entry in "${DISTROS[@]}"; do
  IFS=":" read -r distro_id distro_label deps_script <<< "$entry"
  create_bundle "$distro_id" "$distro_label" "$deps_script"
done
