#!/usr/bin/env python3
"""
Bootstrap a complete Python automation environment on Windows, macOS, or Linux.

This single file will:
1. Detect an existing Python runtime or install a portable Miniforge build if none is found.
2. Create (or reuse) a virtual environment with upgraded packaging tooling.
3. Install a curated set of commonly used automation libraries.

It is designed to be compiled or packaged so that teams can run it on systems
without a pre-installed Python interpreter.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Iterable, List, Optional

MINIFORGE_BASE_URL = "https://github.com/conda-forge/miniforge/releases/latest/download"

# Core building blocks that most automation scripts rely on.
BASE_LIBRARIES: List[str] = [
    "requests",
    "urllib3",
    "python-dotenv",
    "pydantic",
    "pandas",
    "numpy",
    "pyyaml",
    "schedule",
    "rich",
    "loguru",
    "click",
    "boto3",
    "paramiko",
    "beautifulsoup4",
    "lxml",
    "selenium",
    "openpyxl",
    "psutil",
]

# Platform-specific helpers.
WINDOWS_ONLY: List[str] = ["pywin32"]
UNIX_ONLY: List[str] = []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install Python (if necessary), create a virtual environment, and install automation libraries."
    )
    parser.add_argument(
        "--env-dir",
        default=".venv",
        help="Directory for the virtual environment (default: %(default)s).",
    )
    parser.add_argument(
        "--runtime-dir",
        default="python-runtime",
        help="Directory for the portable Python runtime if installation is required (default: %(default)s).",
    )
    parser.add_argument(
        "--python-bin",
        default=None,
        help="Optional path to an existing python interpreter to use (skip auto-detect/install logic).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the commands that would run without executing them.",
    )
    parser.add_argument(
        "--extra",
        action="append",
        default=[],
        metavar="PACKAGE",
        help="Additional packages to install (can be repeated).",
    )
    return parser.parse_args()


def run_command(command: List[str], *, cwd: Path | None = None, dry_run: bool = False) -> None:
    cmd_str = " ".join(command)
    print(f"\n$ {cmd_str}")
    if dry_run:
        return

    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {cmd_str}")


def determine_platform() -> str:
    system_name = platform.system().lower()
    if "windows" in system_name:
        return "windows"
    if "darwin" in system_name:
        return "mac"
    return "linux"


def detect_existing_python(explicit: Optional[str] = None) -> Optional[Path]:
    """Return a usable python interpreter path if one already exists."""
    candidates = [explicit, sys.executable, "python3", "python", "py"]
    for candidate in candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if candidate_path.exists():
            return candidate_path
        resolved = shutil.which(str(candidate))
        if resolved:
            return Path(resolved)
    return None


def gather_packages(current_platform: str, extras: Iterable[str]) -> List[str]:
    packages = list(BASE_LIBRARIES)
    if current_platform == "windows":
        packages.extend(WINDOWS_ONLY)
    else:
        packages.extend(UNIX_ONLY)

    for pkg in extras:
        if pkg and pkg not in packages:
            packages.append(pkg)

    return packages


def build_miniforge_filename(current_platform: str, machine: str) -> str:
    arch = machine.lower()
    if current_platform == "windows":
        if arch in {"x86_64", "amd64"}:
            return "Miniforge3-Windows-x86_64.exe"
        if arch in {"arm64", "aarch64"}:
            return "Miniforge3-Windows-arm64.exe"
    elif current_platform == "mac":
        if arch in {"x86_64", "amd64"}:
            return "Miniforge3-MacOSX-x86_64.sh"
        if arch in {"arm64", "aarch64"}:
            return "Miniforge3-MacOSX-arm64.sh"
    else:  # linux
        if arch in {"x86_64", "amd64"}:
            return "Miniforge3-Linux-x86_64.sh"
        if arch in {"arm64", "aarch64"}:
            return "Miniforge3-Linux-aarch64.sh"
    raise RuntimeError(f"Unsupported architecture '{machine}' for platform '{current_platform}'.")


def download_file(url: str, destination: Path, *, dry_run: bool) -> None:
    print(f"Downloading {url} -> {destination}")
    if dry_run:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, open(destination, "wb") as output_file:
        shutil.copyfileobj(response, output_file)


def install_miniforge(runtime_dir: Path, current_platform: str, *, dry_run: bool) -> None:
    filename = build_miniforge_filename(current_platform, platform.machine())
    url = f"{MINIFORGE_BASE_URL}/{filename}"
    with tempfile.TemporaryDirectory(prefix="python-bootstrap-") as tmpdir:
        installer_path = Path(tmpdir) / filename
        download_file(url, installer_path, dry_run=dry_run)
        if dry_run:
            return

        if current_platform == "windows":
            target = str(runtime_dir)
            args = [
                str(installer_path),
                "/InstallationType=JustMe",
                "/AddToPath=0",
                "/S",
                f"/D={target}",
            ]
            run_command(args, dry_run=False)
        else:
            installer_path.chmod(installer_path.stat().st_mode | 0o111)
            args = ["bash", str(installer_path), "-b", "-p", str(runtime_dir)]
            run_command(args, dry_run=False)


def ensure_python_runtime(
    explicit_python: Optional[str],
    runtime_dir: Path,
    current_platform: str,
    *,
    dry_run: bool,
) -> Path:
    if explicit_python:
        path = Path(explicit_python).expanduser().resolve()
        if dry_run or path.exists():
            print(f"Using user-specified python interpreter: {path}")
            return path
        raise FileNotFoundError(f"Specified python interpreter not found: {path}")

    existing = detect_existing_python()
    if existing:
        print(f"Detected existing python interpreter: {existing}")
        return existing

    runtime_python = runtime_dir / (
        "python.exe" if current_platform == "windows" else "bin/python"
    )
    if runtime_python.exists():
        print(f"Reusing portable runtime at {runtime_python}")
        return runtime_python

    print(f"No python detected. Installing portable runtime into {runtime_dir}...")
    install_miniforge(runtime_dir, current_platform, dry_run=dry_run)
    return runtime_python


def ensure_venv(env_dir: Path, python_bin: Path, dry_run: bool) -> Path:
    if not env_dir.exists():
        print(f"Creating virtual environment at {env_dir}...")
        run_command([str(python_bin), "-m", "venv", str(env_dir)], dry_run=dry_run)
    else:
        print(f"Using existing virtual environment at {env_dir}.")

    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    env_python = env_dir / scripts_dir / ("python.exe" if os.name == "nt" else "python")
    if not dry_run and not env_python.exists():
        raise FileNotFoundError(f"Cannot locate interpreter inside venv: {env_python}")
    return env_python


def upgrade_tooling(env_python: Path, dry_run: bool) -> None:
    print("Upgrading pip, setuptools, and wheel...")
    run_command(
        [str(env_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        dry_run=dry_run,
    )


def install_packages(env_python: Path, packages: List[str], dry_run: bool) -> None:
    if not packages:
        print("No packages requested.")
        return

    print(f"Installing {len(packages)} packages...")
    run_command(
        [str(env_python), "-m", "pip", "install", "--upgrade", *packages],
        dry_run=dry_run,
    )


def main() -> None:
    args = parse_args()
    env_dir = Path(args.env_dir).expanduser().resolve()
    runtime_dir = Path(args.runtime_dir).expanduser().resolve()
    current_platform = determine_platform()

    python_bin = ensure_python_runtime(
        args.python_bin,
        runtime_dir,
        current_platform,
        dry_run=args.dry_run,
    )
    env_python = ensure_venv(env_dir, python_bin, args.dry_run)
    upgrade_tooling(env_python, args.dry_run)

    packages = gather_packages(current_platform, args.extra)
    install_packages(env_python, packages, args.dry_run)

    print("\nEnvironment ready!")
    if current_platform == "windows":
        activation_hint = f"{env_dir}\\Scripts\\activate"
    else:
        activation_hint = f"source {env_dir}/bin/activate"
    print("Activate it with:")
    print(f"  {activation_hint}")


if __name__ == "__main__":
    main()
