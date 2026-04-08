#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/sejder/nix.git"
CLONE_DIR="$HOME/nix"

# Guard: clone dir must not exist
if [[ -d "$CLONE_DIR" ]]; then
  echo "[ERROR] $CLONE_DIR already exists. Remove it or resume manually:"
  echo "  nix run nixpkgs#home-manager --extra-experimental-features 'nix-command flakes' -- switch -b backup --flake \"$CLONE_DIR#<config>\""
  exit 1
fi

# Guard: git must be available
if ! command -v git &>/dev/null; then
  echo "[ERROR] git is not installed. Install it and re-run."
  exit 1
fi

echo "[INFO] Installing Nix via Determinate..."
curl -fsSL https://install.determinate.systems/nix | sh -s -- install --determinate

NIX_DAEMON_PROFILE="/nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh"
if [[ ! -f "$NIX_DAEMON_PROFILE" ]]; then
  echo "[ERROR] Nix daemon profile not found at $NIX_DAEMON_PROFILE. Installation may have failed."
  exit 1
fi

echo "[INFO] Loading Nix environment..."
# shellcheck source=/dev/null
. "$NIX_DAEMON_PROFILE"

echo "[INFO] Cloning repo..."
git clone "$REPO_URL" "$CLONE_DIR"

# Discover homeConfigurations
echo "[INFO] Discovering available home-manager configurations..."
CONFIGS=$(nix eval \
  --extra-experimental-features 'nix-command flakes' \
  --raw "$CLONE_DIR#homeConfigurations" \
  --apply 'attrs: builtins.concatStringsSep "\n" (builtins.attrNames attrs)' \
  2>/dev/null) || { echo "[ERROR] Failed to evaluate flake. Check $CLONE_DIR/flake.nix."; exit 1; }

if [[ -z "$CONFIGS" ]]; then
  echo "[ERROR] No homeConfigurations found in flake."
  exit 1
fi

# Build menu options
mapfile -t CONFIG_LIST <<< "$CONFIGS"
OPTIONS=("${CONFIG_LIST[@]}" "Create new")

echo ""
echo "Available home-manager configurations:"
select CHOICE in "${OPTIONS[@]}"; do
  if [[ -n "$CHOICE" ]]; then
    break
  fi
  echo "Invalid selection, try again."
done

if [[ "$CHOICE" == "Create new" ]]; then
  read -rp "Enter new config name (username or user@host): " NEW_CONFIG
  if [[ -z "$NEW_CONFIG" ]]; then
    echo "[ERROR] Config name cannot be empty."
    exit 1
  fi

  echo "Choose a base configuration to copy from:"
  select BASE in "${CONFIG_LIST[@]}"; do
    if [[ -n "$BASE" ]]; then
      break
    fi
    echo "Invalid selection, try again."
  done

  # Find source file
  if [[ -f "$CLONE_DIR/users/$BASE.nix" ]]; then
    SRC="$CLONE_DIR/users/$BASE.nix"
  elif [[ -f "$CLONE_DIR/users/$BASE-wsl.nix" ]]; then
    SRC="$CLONE_DIR/users/$BASE-wsl.nix"
  else
    echo "[ERROR] Could not find source file for base config '$BASE' in $CLONE_DIR/users/."
    exit 1
  fi

  DEST="$CLONE_DIR/users/$NEW_CONFIG.nix"
  echo "[INFO] Copying $SRC to $DEST..."
  cp "$SRC" "$DEST"

  echo "[INFO] Adding $NEW_CONFIG to flake.nix homeConfigurations..."
  # Append new homeConfigurations entry before the final closing braces
  FLAKE="$CLONE_DIR/flake.nix"
  LINES=$(wc -l < "$FLAKE")
  head -n "$((LINES - 2))" "$FLAKE" > "$FLAKE.tmp"
  cat >> "$FLAKE.tmp" <<EOF

      homeConfigurations."$NEW_CONFIG" = homeManagerConfiguration {
        pkgs = nixpkgs.legacyPackages.x86_64-linux;
        extraSpecialArgs = { inherit inputs; };
        modules = [ ./users/$NEW_CONFIG.nix ];
      };
EOF
  # Append the last 2 lines back
  tail -n 2 "$FLAKE" >> "$FLAKE.tmp"
  mv "$FLAKE.tmp" "$FLAKE"

  CHOSEN="$NEW_CONFIG"
else
  CHOSEN="$CHOICE"
fi

echo "[INFO] Switching home-manager configuration..."
nix run nixpkgs#home-manager \
  --extra-experimental-features 'nix-command flakes' \
  -- switch -b backup --flake "$CLONE_DIR#$CHOSEN"

echo "[INFO] Running switch-flake..."
export NH_FLAKE="$CLONE_DIR"
switch-flake

# Set default shell to zsh if available
ZSH_PATH="$HOME/.nix-profile/bin/zsh"
if [[ -x "$ZSH_PATH" ]]; then
  if ! grep -Fxq "$ZSH_PATH" /etc/shells; then
    echo "[INFO] Adding $ZSH_PATH to /etc/shells (needs sudo)..."
    echo "$ZSH_PATH" | sudo tee -a /etc/shells
  fi
  echo "[INFO] Setting default shell to zsh..."
  chsh -s "$ZSH_PATH"
else
  echo "[INFO] zsh not found at $ZSH_PATH, skipping shell change."
fi

echo "[DONE]"
