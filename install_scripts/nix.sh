#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/sejder/nix.git"
CLONE_DIR="$HOME/nix"

# Function to detect NixOS
is_nixos() {
  [[ -f /etc/os-release ]] && grep -q '^ID=nixos' /etc/os-release
}

if is_nixos; then
  echo "[INFO] Detected NixOS."

  echo "[INFO] Cloning Repo ..."
  nix-env -iA nixos.git
  
  git clone "$REPO_URL" "$CLONE_DIR"

  nix-env -e git

  echo "[INFO] Copying hardware-configuration.nix..."
  cp /etc/nixos/hardware-configuration.nix nix/hosts/galaxybook/

  echo "[INFO] Running nixos-rebuild with flake..."
  sudo nixos-rebuild switch --flake "path:nix/#galaxybook" --install-bootloader

  echo "[DONE]"

  reboot

else
  echo "[INFO] Non-NixOS system detected. Proceeding with Nix installation and home-manager setup..."

  echo "Installing Nix..."
  curl -fsSL https://install.determinate.systems/nix | sh -s -- install --determinate

  echo "Loading Nix environment..."
  . /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh

  echo "Cloning config..."
  git clone "$REPO_URL" "$CLONE_DIR"

  echo "Switching config..."
  nix run nixpkgs#home-manager -- switch -b backup --flake ~/nix#mikke

  ZSH_PATH="$HOME/.nix-profile/bin/zsh"

  if [ -x "$ZSH_PATH" ]; then
    # Ensure Zsh path is listed in /etc/shells
    if ! grep -Fxq "$ZSH_PATH" /etc/shells; then
      echo "Adding $ZSH_PATH to /etc/shells (needs sudo)..."
      echo "$ZSH_PATH" | sudo tee -a /etc/shells
    fi

    echo "Setting default shell to Zsh..."
    chsh -s "$ZSH_PATH"
  else
    echo "Zsh not found at $ZSH_PATH"
  fi

  echo "Done!"
fi
