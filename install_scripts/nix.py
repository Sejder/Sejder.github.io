#!/usr/bin/env python3
"""
Entry point: auto-detects NixOS vs generic Linux and runs the appropriate script.

Usage:
    curl -fsSL https://sejder.github.io/install_scripts/nix.py | python3
"""

import os
import sys
import urllib.request
import tempfile
import subprocess

BASE_URL = "https://sejder.github.io/install_scripts"


def is_nixos() -> bool:
    try:
        with open("/etc/os-release") as f:
            return any(line.strip() == "ID=nixos" for line in f)
    except FileNotFoundError:
        return False


def fetch_and_run(script_name: str) -> None:
    url = f"{BASE_URL}/{script_name}"
    print(f"[INFO] Fetching {url} ...")
    with urllib.request.urlopen(url) as resp:
        source = resp.read().decode()

    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as tmp:
        tmp.write(source)
        tmp_path = tmp.name

    try:
        result = subprocess.run([sys.executable, tmp_path], check=False)
        sys.exit(result.returncode)
    finally:
        os.unlink(tmp_path)


def main() -> None:
    if is_nixos():
        fetch_and_run("nixos.py")
    else:
        fetch_and_run("home-manager.py")


if __name__ == "__main__":
    main()
