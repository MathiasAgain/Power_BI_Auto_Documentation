"""CLI authentication helpers for GitHub (gh) and Azure DevOps (az)."""

import shutil
import subprocess


# ---------------------------------------------------------------------------
# Azure CLI
# ---------------------------------------------------------------------------
def find_az_cli() -> str | None:
    """Locate the az CLI executable. Returns path or None."""
    return shutil.which("az") or shutil.which("az.cmd")


def check_az_cli_status() -> str | None:
    """Check if az CLI is logged in. Returns username or None."""
    az = find_az_cli()
    if not az:
        return None
    try:
        result = subprocess.run(
            [az, "account", "show", "--query", "user.name", "-o", "tsv"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        pass
    return None


def run_az_login() -> str | None:
    """Run az login (opens browser). Returns username on success, None on failure."""
    az = find_az_cli()
    if not az:
        return None
    try:
        result = subprocess.run(
            [az, "login", "--query", "[0].user.name", "-o", "tsv"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        pass
    return None


def get_az_access_token() -> str | None:
    """Get an Azure DevOps access token from az CLI. Returns token or None."""
    az = find_az_cli()
    if not az:
        return None
    try:
        result = subprocess.run(
            [az, "account", "get-access-token",
             "--resource", "499b84ac-1321-427f-aa17-267ca6975798",
             "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        pass
    return None


# ---------------------------------------------------------------------------
# GitHub CLI
# ---------------------------------------------------------------------------
def find_gh_cli() -> str | None:
    """Locate the gh CLI executable. Returns path or None."""
    return shutil.which("gh") or shutil.which("gh.exe")


def check_gh_cli_status() -> str | None:
    """Check if gh CLI is authenticated. Returns username or None."""
    gh = find_gh_cli()
    if not gh:
        return None
    try:
        result = subprocess.run(
            [gh, "api", "user", "--jq", ".login"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        pass
    return None


def run_gh_login() -> str | None:
    """Run gh auth login (opens browser). Returns username on success, None on failure."""
    gh = find_gh_cli()
    if not gh:
        return None
    try:
        result = subprocess.run(
            [gh, "auth", "login", "--web"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return check_gh_cli_status()
    except subprocess.TimeoutExpired:
        pass
    return None


def get_gh_token() -> str | None:
    """Retrieve a GitHub token from gh CLI. Returns token or None."""
    gh = find_gh_cli()
    if not gh:
        return None
    try:
        result = subprocess.run(
            [gh, "auth", "token"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        pass
    return None
