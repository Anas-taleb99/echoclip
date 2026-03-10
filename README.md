# EchoClip

EchoClip is a searchable clipboard manager for Linux desktops. It keeps clipboard history in the background, opens a quick-open palette, previews full entries, supports pinning, and can paste the selected item back into the previously focused X11 application.

## Features

- Searchable clipboard history palette
- Full-text preview pane
- Pin, delete, clear, and copy-only actions
- Instant re-paste into the previously focused window on X11
- JSON-backed history with legacy migration support
- CLI commands for history inspection, copy, delete, pin toggling, and smoke testing

## Desktop Requirements

- Linux desktop session with GTK 3
- `python3`
- `python3-gi`
- `gir1.2-gtk-3.0`
- X11 for the automatic paste-back behavior

Wayland users can still use history, copy, pin, delete, and preview, but synthetic paste into the previously focused app is X11-only.

## Alpha Release Matrix

The current channel is `0.2.0-alpha.3`.

Release bundles are generated for:

- Ubuntu 24.04
- Debian 12
- Fedora 41
- Arch Linux

Each distro bundle contains a distro-specific dependency installer plus the normal app installer.

## Install

### User-local install

```bash
./scripts/install-deps-ubuntu.sh
./scripts/install.sh
```

This installs:

- the launcher to `~/.local/bin/echoclip`
- a compatibility wrapper at `~/.local/bin/winv_clipboard.py` for old shortcuts
- the Python package to `~/.local/share/echoclip`
- the desktop entry to `~/.local/share/applications`
- the autostart entry to `~/.config/autostart`

The installer also removes the legacy `~/.config/autostart/winv-clipboard.desktop` entry so older local installs stop launching the pre-EchoClip script.

### Remove

```bash
./scripts/uninstall.sh
```

## Usage

Start the daemon manually:

```bash
echoclip daemon
```

Open the palette:

```bash
echoclip show
```

Useful CLI commands:

```bash
echoclip history --limit 10
echoclip history --json --query ssh
echoclip copy "hello"
echoclip toggle-pin <item-id>
echoclip delete <item-id>
echoclip clear --keep-pinned
echoclip smoke-test
```

## Release Artifacts

Build all distro-specific alpha tarballs:

```bash
./scripts/build-release.sh
```

That creates versioned `tar.gz` archives plus `sha256` checksums in `dist/` for Ubuntu, Debian, Fedora, and Arch.

## Tests

Run unit tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Repo Description

Searchable clipboard manager for Linux with pinning, preview, and instant paste.
