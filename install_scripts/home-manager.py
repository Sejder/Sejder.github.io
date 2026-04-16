#!/usr/bin/env python3
"""
Home-manager install script for non-NixOS Linux systems.

Installs Nix via Determinate Systems, clones the nix config repo,
and applies the chosen home-manager configuration.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

REPO_URL = "https://github.com/sejder/nix.git"
CLONE_DIR = os.path.expanduser("~/nix")
NIX_DAEMON_PROFILE = "/nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def info(msg: str) -> None:
    print(f"[INFO] {msg}", flush=True)


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr, flush=True)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def ask(prompt: str) -> str:
    return input(prompt).strip()


def pick(options: list[str], prompt: str = "Enter number: ") -> int:
    for i, opt in enumerate(options, 1):
        print(f"  {i}) {opt}")
    while True:
        raw = ask(prompt)
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print("  Invalid selection, try again.")


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def guard_clone_dir() -> None:
    if os.path.isdir(CLONE_DIR):
        error(f"{CLONE_DIR} already exists. Remove it or resume manually:")
        print(
            f"  nix run nixpkgs#home-manager "
            f"--extra-experimental-features 'nix-command flakes' "
            f"-- switch -b backup --flake \"{CLONE_DIR}#<config>\""
        )
        sys.exit(1)


def guard_git() -> None:
    if not shutil.which("git"):
        error("git is not installed. Install it and re-run.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Nix installation
# ---------------------------------------------------------------------------

def install_nix() -> None:
    info("Installing Nix via Determinate Systems...")
    with urllib.request.urlopen("https://install.determinate.systems/nix") as resp:
        installer = resp.read().decode()

    with tempfile.NamedTemporaryFile(suffix=".sh", delete=False, mode="w") as tmp:
        tmp.write(installer)
        tmp_path = tmp.name

    try:
        run(["bash", tmp_path, "install", "--determinate"])
    finally:
        os.unlink(tmp_path)


def load_nix_env() -> dict[str, str]:
    """Source the nix-daemon profile and return the updated environment."""
    if not os.path.isfile(NIX_DAEMON_PROFILE):
        error(f"Nix daemon profile not found at {NIX_DAEMON_PROFILE}. Installation may have failed.")
        sys.exit(1)

    info("Loading Nix environment...")
    result = subprocess.run(
        ["bash", "-c", f". {NIX_DAEMON_PROFILE} && env"],
        capture_output=True,
        text=True,
        check=True,
    )
    env = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            env[key] = value
    return env


# ---------------------------------------------------------------------------
# Config selection
# ---------------------------------------------------------------------------

def discover_configs(nix_env: dict[str, str]) -> list[str]:
    info("Discovering available home-manager configurations...")
    result = subprocess.run(
        [
            "nix", "eval",
            "--extra-experimental-features", "nix-command flakes",
            "--raw", f"{CLONE_DIR}#homeConfigurations",
            "--apply", "attrs: builtins.concatStringsSep \"\\n\" (builtins.attrNames attrs)",
        ],
        capture_output=True,
        text=True,
        env=nix_env,
    )
    if result.returncode != 0:
        error(f"Failed to evaluate flake:\n{result.stderr}")
        sys.exit(1)
    configs = [c for c in result.stdout.strip().splitlines() if c]
    if not configs:
        error("No homeConfigurations found in flake.")
        sys.exit(1)
    return configs


def select_config(configs: list[str], nix_env: dict[str, str]) -> str:
    options = configs + ["Create new"]
    print("\nAvailable home-manager configurations:")
    idx = pick(options)
    choice = options[idx]

    if choice != "Create new":
        return choice

    new_config = ask("Enter new config name (username or user@host): ")
    if not new_config:
        error("Config name cannot be empty.")
        sys.exit(1)

    print("\nChoose a base configuration to copy from:")
    base_idx = pick(configs)
    base = configs[base_idx]

    # Find source file
    users_dir = os.path.join(CLONE_DIR, "users")
    src = None
    for candidate in [f"{base}.nix", f"{base}-wsl.nix"]:
        path = os.path.join(users_dir, candidate)
        if os.path.isfile(path):
            src = path
            break
    if src is None:
        error(f"Could not find source file for base config '{base}' in {users_dir}.")
        sys.exit(1)

    dest = os.path.join(users_dir, f"{new_config}.nix")
    info(f"Copying {src} -> {dest} ...")
    shutil.copy2(src, dest)

    info(f"Adding {new_config} to flake.nix homeConfigurations...")
    flake_path = os.path.join(CLONE_DIR, "flake.nix")
    with open(flake_path) as f:
        content = f.read()

    new_entry = (
        f'\n      homeConfigurations."{new_config}" = '
        f'home-manager.lib.homeManagerConfiguration {{\n'
        f'        pkgs = nixpkgs.legacyPackages.x86_64-linux;\n'
        f'        extraSpecialArgs = {{ inherit inputs; }};\n'
        f'        modules = [ ./users/{new_config}.nix ];\n'
        f'      }};\n'
    )
    # Insert before the last closing braces
    lines = content.rstrip().splitlines()
    insert_at = len(lines) - 2
    lines.insert(insert_at, new_entry)
    with open(flake_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return new_config


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_home_manager(config: str, nix_env: dict[str, str]) -> None:
    info("Switching home-manager configuration...")
    run(
        [
            "nix", "run", "nixpkgs#home-manager",
            "--extra-experimental-features", "nix-command flakes",
            "--", "switch", "-b", "backup",
            "--flake", f"{CLONE_DIR}#{config}",
        ],
        env=nix_env,
    )


def switch_flake(nix_env: dict[str, str]) -> None:
    info("Running switch-flake...")
    env = nix_env.copy()
    env["NH_FLAKE"] = CLONE_DIR
    run(["switch-flake"], env=env)


def set_default_shell(nix_env: dict[str, str]) -> None:
    zsh_path = os.path.expanduser("~/.nix-profile/bin/zsh")
    if not os.path.isfile(zsh_path):
        info("zsh not found in nix profile, skipping shell change.")
        return

    shells_file = "/etc/shells"
    try:
        with open(shells_file) as f:
            shells = f.read()
    except FileNotFoundError:
        shells = ""

    if zsh_path not in shells.splitlines():
        info(f"Adding {zsh_path} to /etc/shells (needs sudo)...")
        run(["sudo", "tee", "-a", shells_file], input=zsh_path + "\n",
            text=True, env=nix_env)

    info("Setting default shell to zsh...")
    run(["chsh", "-s", zsh_path], env=nix_env)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    guard_clone_dir()
    guard_git()

    install_nix()
    nix_env = load_nix_env()

    info("Cloning repo...")
    run(["git", "clone", REPO_URL, CLONE_DIR])

    configs = discover_configs(nix_env)
    config = select_config(configs, nix_env)

    apply_home_manager(config, nix_env)
    switch_flake(nix_env)
    set_default_shell(nix_env)

    info("Done.")


if __name__ == "__main__":
    main()
