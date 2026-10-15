#!/usr/bin/env bash
# CoolBar installer for Linux (GNOME / KDE / anything with a StatusNotifier tray).
#
#   One-liner (latest release):
#     curl -fsSL https://github.com/Saffron-codes/ac_app_bluestar/releases/latest/download/install.sh | bash
#   From a downloaded tarball:
#     ./install.sh coolbar-linux-x64.tar.gz
#   Remove everything:
#     ./install.sh --uninstall
#
# Installs to ~/.local/opt/coolbar, adds a launcher entry and an autostart entry, starts CoolBar.
# No root, no Python required: the tarball is self-contained. Needs a running BlueZ and, on GNOME,
# the "AppIndicator and KStatusNotifierItem Support" extension so the tray icon is shown.
set -euo pipefail

REPO="Saffron-codes/ac_app_bluestar"
ASSET="coolbar-linux-x64.tar.gz"
PREFIX="${COOLBAR_PREFIX:-$HOME/.local/opt/coolbar}"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

uninstall() {
  say "Stopping CoolBar"
  pkill -f "$PREFIX/coolbar" 2>/dev/null || true
  rm -rf "$PREFIX"
  rm -f "$BIN_DIR/coolbar" "$APPS_DIR/coolbar.desktop" "$AUTOSTART_DIR/coolbar.desktop" "$ICON_DIR/coolbar.svg"
  say "Removed. Your pairing token in ~/.config/coolbar was kept; delete it if you want a clean slate."
  exit 0
}

[[ "${1:-}" == "--uninstall" ]] && uninstall

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if [[ -n "${1:-}" && -f "$1" ]]; then
  tarball="$1"
else
  say "Downloading the latest CoolBar release"
  url="https://github.com/$REPO/releases/latest/download/$ASSET"
  curl -fsSL --retry 3 -o "$tmp/$ASSET" "$url"
  tarball="$tmp/$ASSET"
fi

say "Installing to $PREFIX"
pkill -f "$PREFIX/coolbar" 2>/dev/null || true
rm -rf "$PREFIX"
mkdir -p "$PREFIX" "$BIN_DIR" "$APPS_DIR" "$ICON_DIR" "$AUTOSTART_DIR"
tar -xzf "$tarball" -C "$PREFIX" --strip-components=1
chmod +x "$PREFIX/coolbar"
ln -sf "$PREFIX/coolbar" "$BIN_DIR/coolbar"
[[ -f "$PREFIX/coolbar.svg" ]] && cp "$PREFIX/coolbar.svg" "$ICON_DIR/coolbar.svg"

desktop="[Desktop Entry]
Type=Application
Name=CoolBar
Comment=Control your Blue Star AC from the top bar
Exec=$PREFIX/coolbar
Icon=coolbar
Terminal=false
Categories=Utility;
StartupNotify=false
X-GNOME-Autostart-enabled=true"
printf '%s\n' "$desktop" > "$APPS_DIR/coolbar.desktop"
printf '%s\n' "$desktop" > "$AUTOSTART_DIR/coolbar.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" 2>/dev/null || true

if [[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]] && command -v gnome-extensions >/dev/null 2>&1; then
  if ! gnome-extensions list --enabled 2>/dev/null | grep -q appindicator; then
    say "GNOME needs the 'AppIndicator and KStatusNotifierItem Support' extension to show tray icons:"
    say "  https://extensions.gnome.org/extension/615/appindicator-support/"
  fi
fi

say "Starting CoolBar"
nohup "$PREFIX/coolbar" >/dev/null 2>&1 &
disown || true
say "Done. CoolBar lives in your top bar and will start automatically at login."
say "First time: put the AC in pairing mode and click Pair in the panel (or import a token)."
