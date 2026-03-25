#!/usr/bin/env bash
set -euo pipefail

BASE_URL="https://sejder.github.io/install_scripts"

is_nixos() {
  [[ -f /etc/os-release ]] && grep -q '^ID=nixos' /etc/os-release
}

if is_nixos; then
  bash -c "$(curl -fsSL "$BASE_URL/nixos.sh")"
else
  bash -c "$(curl -fsSL "$BASE_URL/home-manager.sh")"
fi
