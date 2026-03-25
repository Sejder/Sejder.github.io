#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/sejder/nix.git"
CLONE_DIR="$HOME/nix"

# Guard: must be NixOS
if ! [[ -f /etc/os-release ]] || ! grep -q '^ID=nixos' /etc/os-release; then
  echo "[ERROR] This script is for NixOS only."
  exit 1
fi

# Guard: clone dir must not exist
if [[ -d "$CLONE_DIR" ]]; then
  echo "[ERROR] $CLONE_DIR already exists. Remove it or resume manually:"
  echo "  sudo nixos-rebuild switch --flake \"$CLONE_DIR#<hostname>\" --install-bootloader"
  exit 1
fi

echo "[INFO] Installing git temporarily..."
nix-env -iA nixos.git

echo "[INFO] Cloning repo..."
git clone "$REPO_URL" "$CLONE_DIR"

echo "[INFO] Removing temporary git..."
nix-env -e git

# Discover nixosConfigurations
echo "[INFO] Discovering available NixOS configurations..."
CONFIGS=$(nix eval \
  --extra-experimental-features 'nix-command flakes' \
  --raw "$CLONE_DIR#nixosConfigurations" \
  --apply 'attrs: builtins.concatStringsSep "\n" (builtins.attrNames attrs)' \
  2>/dev/null) || { echo "[ERROR] Failed to evaluate flake. Check $CLONE_DIR/flake.nix."; exit 1; }

if [[ -z "$CONFIGS" ]]; then
  echo "[ERROR] No nixosConfigurations found in flake."
  exit 1
fi

# Build menu options
mapfile -t CONFIG_LIST <<< "$CONFIGS"
OPTIONS=("${CONFIG_LIST[@]}" "Create new")

echo ""
echo "Available NixOS configurations:"
select CHOICE in "${OPTIONS[@]}"; do
  if [[ -n "$CHOICE" ]]; then
    break
  fi
  echo "Invalid selection, try again."
done

if [[ "$CHOICE" == "Create new" ]]; then
  read -rp "Enter new hostname: " NEW_HOST
  if [[ -z "$NEW_HOST" ]]; then
    echo "[ERROR] Hostname cannot be empty."
    exit 1
  fi
  if [[ -d "$CLONE_DIR/hosts/$NEW_HOST" ]]; then
    echo "[ERROR] hosts/$NEW_HOST already exists."
    exit 1
  fi

  echo "Choose a base configuration to copy from:"
  select BASE in "${CONFIG_LIST[@]}"; do
    if [[ -n "$BASE" ]]; then
      break
    fi
    echo "Invalid selection, try again."
  done

  echo "[INFO] Copying hosts/$BASE to hosts/$NEW_HOST..."
  cp -r "$CLONE_DIR/hosts/$BASE" "$CLONE_DIR/hosts/$NEW_HOST"

  echo "[INFO] Adding $NEW_HOST to flake.nix..."
  sed -i "s|\(nixosConfigurations = {\)|\1\n        $NEW_HOST = mkHost \"$NEW_HOST\";|" "$CLONE_DIR/flake.nix"

  echo "[INFO] Remember to update networking.hostName in hosts/$NEW_HOST/configuration.nix before rebooting."
  CHOSEN="$NEW_HOST"
else
  CHOSEN="$CHOICE"
fi

echo "[INFO] Copying hardware-configuration.nix..."
cp /etc/nixos/hardware-configuration.nix "$CLONE_DIR/hosts/$CHOSEN/hardware-configuration.nix"

echo "[INFO] Running nixos-rebuild switch..."
sudo nixos-rebuild switch \
  --extra-experimental-features 'nix-command flakes' \
  --flake "$CLONE_DIR#$CHOSEN" \
  --install-bootloader

echo "[DONE] Rebooting..."
reboot
