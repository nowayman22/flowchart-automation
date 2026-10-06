#!/usr/bin/env bash
# Enable the Wayland input backend for Flowchart Automation on Omarchy/Hyprland.
#
# Screen capture works out of the box (grim ships with Omarchy), but injecting
# mouse clicks and keypresses into native Wayland windows requires ydotool:
# Wayland deliberately blocks one client from driving another, so the X11 route
# pyautogui uses is unavailable. ydotool emulates a real input device through
# uinput instead, which is why the ydotoold daemon needs to be running.
#
# Usage:  ./scripts/setup-wayland.sh
#
# Requires sudo for the package install (you will be prompted).

set -euo pipefail

SOCKET="${YDOTOOL_SOCKET:-${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/.ydotool_socket}"

say() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
ok() { printf '\033[1;32m  ok\033[0m %s\n' "$1"; }
warn() { printf '\033[1;33m  !!\033[0m %s\n' "$1"; }
die() {
  printf '\033[1;31merror:\033[0m %s\n' "$1" >&2
  exit 1
}

[ "${XDG_SESSION_TYPE:-}" = "wayland" ] || warn "Not a Wayland session; the X11 path is used instead."

# --- 1. ydotool -------------------------------------------------------------

if command -v omarchy >/dev/null 2>&1; then
  if omarchy pkg present ydotool >/dev/null 2>&1; then
    ok "ydotool is already installed"
  else
    say "Installing ydotool"
    omarchy pkg add ydotool || die "Could not install ydotool."
  fi
else
  if pacman -Qq ydotool >/dev/null 2>&1; then
    ok "ydotool is already installed"
  else
    say "Installing ydotool (sudo required)"
    sudo pacman -S --needed --noconfirm ydotool || die "Could not install ydotool."
  fi
fi

command -v ydotool >/dev/null 2>&1 || die "ydotool is still not on PATH."

# --- 2. daemon --------------------------------------------------------------
# The Arch package ships a *user* unit named ydotool.service (not ydotoold).

say "Enabling the ydotoold user service"
systemctl --user enable --now ydotool.service ||
  die "Could not start ydotool.service. Inspect: systemctl --user status ydotool"

# --- 3. verify --------------------------------------------------------------

for _ in $(seq 1 10); do
  [ -S "$SOCKET" ] && break
  sleep 0.5
done

if [ -S "$SOCKET" ]; then
  ok "ydotoold is listening on $SOCKET"
else
  die "Daemon started but no socket at $SOCKET. Check: systemctl --user status ydotool"
fi

say "Verifying with a real cursor move"
before=$(hyprctl cursorpos)
ydotool mousemove --absolute -x 5 -y 5 >/dev/null 2>&1 || die "ydotool could not move the cursor."
after=$(hyprctl cursorpos)
ydotool mousemove --absolute -x "${before%%,*}" -y "${before##*, }" >/dev/null 2>&1 || true

if [ "$after" = "5, 5" ]; then
  ok "input injection works (cursor moved $before -> $after, restored)"
else
  warn "Cursor read back as '$after' after moving to '5, 5'; check your setup."
fi

printf '\n\033[1;32mWayland backend ready.\033[0m Launch Flowchart Automation from Walker.\n'
