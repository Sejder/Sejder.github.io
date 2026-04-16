#!/usr/bin/env python3
"""
NixOS install script with optional disko partitioning.

Run on a fresh NixOS live ISO (as root or via sudo):
    curl -fsSL https://sejder.github.io/install_scripts/nix.py | python3

What it does:
  1. Optionally partitions the disk using a disko config (LUKS-encrypted ext4)
  2. Clones the nix config repo
  3. Lets you pick an existing NixOS host config or create a new one
  4. Runs nixos-rebuild switch with your chosen config
  5. Reboots
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
RAW_BASE = "https://raw.githubusercontent.com/Sejder/nix/main"

DISKO_CONFIGS = [
    {
        "label": "LUKS encrypted ext4 on /dev/nvme0n1  (GPT, 1G EF00 boot + full disk LUKS root)",
        "path": "disko/luks-nvme.nix",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def info(msg: str) -> None:
    print(f"[INFO] {msg}", flush=True)


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr, flush=True)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, raising on non-zero exit."""
    return subprocess.run(cmd, check=True, **kwargs)


def ask(prompt: str) -> str:
    return input(prompt).strip()


def pick(options: list[str], prompt: str = "Enter number: ") -> int:
    """Show a numbered menu and return the 0-based index of the chosen item."""
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

def guard_nixos() -> None:
    try:
        with open("/etc/os-release") as f:
            if not any(line.strip() == "ID=nixos" for line in f):
                error("This script is for NixOS only.")
                sys.exit(1)
    except FileNotFoundError:
        error("Cannot read /etc/os-release. Are you on NixOS?")
        sys.exit(1)


def guard_clone_dir() -> None:
    if os.path.isdir(CLONE_DIR):
        error(f"{CLONE_DIR} already exists. Remove it or resume manually:")
        print(f"  sudo nixos-rebuild switch --flake \"{CLONE_DIR}#<hostname>\" --install-bootloader")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Disko partitioning
# ---------------------------------------------------------------------------

def maybe_partition() -> None:
    answer = ask("Partition this disk with disko before installing? [y/N] ").lower()
    if answer not in ("y", "yes"):
        info("Skipping partitioning.")
        return

    print("\nAvailable disko configs:")
    idx = pick([c["label"] for c in DISKO_CONFIGS])
    chosen = DISKO_CONFIGS[idx]

    url = f"{RAW_BASE}/{chosen['path']}"
    info(f"Downloading disko config from {url} ...")
    with urllib.request.urlopen(url) as resp:
        config_content = resp.read().decode()

    with tempfile.NamedTemporaryFile(suffix=".nix", delete=False, mode="w") as tmp:
        tmp.write(config_content)
        tmp_path = tmp.name

    try:
        info("Running disko (this will ERASE the target disk) ...")
        run([
            "nix", "run", "github:nix-community/disko",
            "--extra-experimental-features", "nix-command flakes",
            "--", "--mode", "disko", tmp_path,
        ])
    finally:
        os.unlink(tmp_path)

    info("Partitioning complete.")


# ---------------------------------------------------------------------------
# Repo clone
# ---------------------------------------------------------------------------

def clone_repo() -> None:
    info("Installing git temporarily...")
    run(["nix-env", "-iA", "nixos.git"])

    info("Cloning repo...")
    run(["git", "clone", REPO_URL, CLONE_DIR])

    info("Removing temporary git...")
    run(["nix-env", "-e", "git"])


# ---------------------------------------------------------------------------
# Host selection
# ---------------------------------------------------------------------------

def discover_configs() -> list[str]:
    info("Discovering available NixOS configurations...")
    result = subprocess.run(
        [
            "nix", "eval",
            "--extra-experimental-features", "nix-command flakes",
            "--raw", f"{CLONE_DIR}#nixosConfigurations",
            "--apply", "attrs: builtins.concatStringsSep \"\\n\" (builtins.attrNames attrs)",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        error(f"Failed to evaluate flake:\n{result.stderr}")
        sys.exit(1)
    configs = [c for c in result.stdout.strip().splitlines() if c]
    if not configs:
        error("No nixosConfigurations found in flake.")
        sys.exit(1)
    return configs


def select_host(configs: list[str]) -> str:
    options = configs + ["Create new"]
    print("\nAvailable NixOS configurations:")
    idx = pick(options)
    choice = options[idx]

    if choice != "Create new":
        return choice

    # --- create new host ---
    new_host = ask("Enter new hostname: ")
    if not new_host:
        error("Hostname cannot be empty.")
        sys.exit(1)
    host_dir = os.path.join(CLONE_DIR, "hosts", new_host)
    if os.path.isdir(host_dir):
        error(f"hosts/{new_host} already exists.")
        sys.exit(1)

    print("\nChoose a base configuration to copy from:")
    base_idx = pick(configs)
    base = configs[base_idx]

    info(f"Copying hosts/{base} to hosts/{new_host}...")
    shutil.copytree(os.path.join(CLONE_DIR, "hosts", base), host_dir)

    info(f"Adding {new_host} to flake.nix...")
    flake_path = os.path.join(CLONE_DIR, "flake.nix")
    with open(flake_path) as f:
        content = f.read()
    content = re.sub(
        r"(nixosConfigurations\s*=\s*\{)",
        rf"\1\n        {new_host} = mkHost \"{new_host}\";",
        content,
        count=1,
    )
    with open(flake_path, "w") as f:
        f.write(content)

    info(f"Remember to update networking.hostName in hosts/{new_host}/configuration.nix before rebooting.")
    return new_host


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

def copy_hardware_config(host: str) -> None:
    src = "/etc/nixos/hardware-configuration.nix"
    dst = os.path.join(CLONE_DIR, "hosts", host, "hardware-configuration.nix")
    info(f"Copying {src} -> {dst} ...")
    shutil.copy2(src, dst)


def nixos_rebuild(host: str) -> None:
    info("Running nixos-rebuild switch...")
    env = os.environ.copy()
    env["NIX_CONFIG"] = "experimental-features = nix-command flakes"
    run(
        [
            "sudo", "nixos-rebuild", "switch",
            "--flake", f"{CLONE_DIR}#{host}",
            "--install-bootloader",
        ],
        env=env,
    )


def switch_flake() -> None:
    info("Running switch-flake...")
    env = os.environ.copy()
    env["NH_FLAKE"] = CLONE_DIR
    run(["switch-flake"], env=env)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    guard_nixos()
    guard_clone_dir()

    maybe_partition()
    clone_repo()

    configs = discover_configs()
    host = select_host(configs)

    copy_hardware_config(host)
    nixos_rebuild(host)
    switch_flake()

    info("Done. Rebooting...")
    run(["reboot"])


if __name__ == "__main__":
    main()
