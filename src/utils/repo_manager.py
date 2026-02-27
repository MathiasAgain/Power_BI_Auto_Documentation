"""Repository creation and git initialization utilities.

Handles creating repos on GitHub/Azure DevOps and initializing local git repos
so users never need to interact with git directly.
"""

import logging
import os
import subprocess
from pathlib import Path

import requests

from .cli_auth import find_gh_cli, get_gh_token, find_az_cli, get_az_access_token
from .git_helpers import (
    run_git, committer_env, parse_github_url, GIT_COMMITTER_NAME, GIT_COMMITTER_EMAIL,
)

logger = logging.getLogger(__name__)

# Files that should never be committed
_SENSITIVE_PATTERNS = {".env", ".env.local", "credentials.json", ".app_settings.json"}


# ---------------------------------------------------------------------------
# Git status detection
# ---------------------------------------------------------------------------
def detect_git_status(folder: str | Path) -> dict:
    """Detect the git state of a folder (read-only, never modifies anything).

    Returns:
        {
            "is_repo": bool,
            "remote_url": str | None,
            "has_commits": bool,
            "branch": str | None,
        }
    """
    folder = Path(folder)
    result = {"is_repo": False, "remote_url": None, "has_commits": False, "branch": None}

    if not (folder / ".git").exists():
        return result

    result["is_repo"] = True

    try:
        r = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(folder), capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            result["remote_url"] = r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(folder), capture_output=True, text=True, timeout=10,
        )
        result["has_commits"] = r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        r = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(folder), capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            result["branch"] = r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return result


def _check_sensitive_files(folder: Path) -> list[str]:
    """Return list of sensitive files found in the folder (top-level only)."""
    found = []
    for name in _SENSITIVE_PATTERNS:
        if (folder / name).exists():
            found.append(name)
    return found


# ---------------------------------------------------------------------------
# Repository creation
# ---------------------------------------------------------------------------
def create_github_repo(
    name: str,
    private: bool = True,
    token: str | None = None,
) -> str:
    """Create a new GitHub repository.

    Tries gh CLI first, falls back to REST API with token.

    Returns:
        The repository URL (https://github.com/<owner>/<name>).
    """
    # Try gh CLI first
    gh = find_gh_cli()
    if gh:
        visibility = "--private" if private else "--public"
        try:
            result = subprocess.run(
                [gh, "repo", "create", name, visibility, "--clone=false",
                 "--confirm"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                # gh outputs the URL on stdout
                url = result.stdout.strip()
                if url.startswith("https://"):
                    logger.info(f"Created GitHub repo via CLI: {url}")
                    return url
                # Fallback: construct URL from gh api user
                user_result = subprocess.run(
                    [gh, "api", "user", "--jq", ".login"],
                    capture_output=True, text=True, timeout=10,
                )
                if user_result.returncode == 0:
                    owner = user_result.stdout.strip()
                    url = f"https://github.com/{owner}/{name}"
                    logger.info(f"Created GitHub repo via CLI: {url}")
                    return url
            else:
                stderr = result.stderr or ""
                if "already exists" in stderr.lower():
                    raise RuntimeError(
                        f"Repository '{name}' already exists on GitHub. "
                        f"Use 'existing repo' instead."
                    )
                logger.warning(f"gh repo create failed: {stderr[:200]}")
        except subprocess.TimeoutExpired:
            logger.warning("gh repo create timed out")

    # Fallback: REST API
    api_token = token or get_gh_token()
    if not api_token:
        raise RuntimeError(
            "Cannot create GitHub repo: GitHub CLI (gh) is not available and no token provided. "
            "Install gh CLI (https://cli.github.com) or provide a Personal Access Token."
        )

    resp = requests.post(
        "https://api.github.com/user/repos",
        headers={
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"name": name, "private": private, "auto_init": False},
        timeout=15,
    )
    if resp.status_code == 201:
        url = resp.json().get("html_url", f"https://github.com/{name}")
        logger.info(f"Created GitHub repo via API: {url}")
        return url
    if resp.status_code == 422:
        body = (resp.text or "")[:200]
        if "already exists" in body.lower():
            raise RuntimeError(
                f"Repository '{name}' already exists. Use 'existing repo' instead."
            )
        raise RuntimeError(f"GitHub repo creation failed (422): {body}")
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"GitHub authentication failed ({resp.status_code}). "
            f"Check your token has 'repo' scope."
        )
    body = (resp.text or "")[:200]
    raise RuntimeError(f"GitHub repo creation failed ({resp.status_code}): {body}")


def parse_azure_org_url(url: str) -> str:
    """Extract organization name from an Azure DevOps org URL.

    Accepts:
        https://dev.azure.com/org
        https://dev.azure.com/org/
        https://dev.azure.com/org/project  (returns just org)

    Returns:
        The organization name.
    """
    import re
    url = url.strip().rstrip("/")
    match = re.match(r"https://dev\.azure\.com/([A-Za-z0-9][A-Za-z0-9 _.-]*)", url)
    if match:
        return match.group(1)
    # Legacy format
    match = re.match(r"https://([A-Za-z0-9][A-Za-z0-9_.-]*)\.visualstudio\.com", url)
    if match:
        return match.group(1)
    raise ValueError(
        f"Cannot parse Azure DevOps org URL: {url}. "
        f"Expected: https://dev.azure.com/org"
    )


def create_azure_project(
    org_url: str,
    name: str,
    token: str | None = None,
) -> str:
    """Create a new Azure DevOps project.

    Tries az CLI first, falls back to REST API with token.

    Args:
        org_url: Organization URL (https://dev.azure.com/org).
        name: Project name.
        token: Optional PAT.

    Returns:
        The project URL (https://dev.azure.com/org/project).
    """
    org = parse_azure_org_url(org_url)

    # Try az CLI first
    az = find_az_cli()
    if az:
        try:
            result = subprocess.run(
                [az, "devops", "project", "create",
                 "--name", name,
                 "--org", f"https://dev.azure.com/{org}",
                 "-o", "json"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                url = f"https://dev.azure.com/{org}/{name}"
                logger.info(f"Created Azure DevOps project via CLI: {url}")
                return url
            else:
                stderr = result.stderr or ""
                if "already exists" in stderr.lower():
                    raise RuntimeError(
                        f"Project '{name}' already exists in organization '{org}'. "
                        f"Use 'existing project' instead."
                    )
                logger.warning(f"az devops project create failed: {stderr[:200]}")
        except subprocess.TimeoutExpired:
            logger.warning("az devops project create timed out")

    # Fallback: REST API
    api_token = token or get_az_access_token()
    if not api_token:
        raise RuntimeError(
            "Cannot create Azure DevOps project: Azure CLI (az) is not available and no token provided. "
            "Install Azure CLI or provide a Personal Access Token."
        )

    import base64
    auth_header = base64.b64encode(f":{api_token}".encode()).decode("ascii")
    resp = requests.post(
        f"https://dev.azure.com/{org}/_apis/projects?api-version=7.1",
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/json",
        },
        json={
            "name": name,
            "visibility": "private",
            "capabilities": {
                "versioncontrol": {"sourceControlType": "Git"},
                "processTemplate": {
                    "templateTypeId": "6b724908-ef14-45cf-84f8-768b5384da45"  # Agile
                },
            },
        },
        timeout=30,
    )
    if resp.status_code in (200, 201, 202):
        url = f"https://dev.azure.com/{org}/{name}"
        logger.info(f"Created Azure DevOps project via API: {url}")
        return url
    if resp.status_code == 409:
        raise RuntimeError(
            f"Project '{name}' already exists in organization '{org}'. "
            f"Use 'existing project' instead."
        )
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"Azure DevOps authentication failed ({resp.status_code}). "
            f"Check your token or run 'az login'."
        )
    body = (resp.text or "")[:200]
    raise RuntimeError(f"Azure DevOps project creation failed ({resp.status_code}): {body}")


def _wait_for_azure_repo(
    devops_url: str,
    repo_name: str,
    token: str | None = None,
    log: logging.Logger | None = None,
    max_wait: int = 60,
) -> None:
    """Poll Azure DevOps until the repository is accessible (up to max_wait seconds).

    After creating a new project, the default repo can take 10-30s to be provisioned.
    This prevents downstream git operations from failing or hanging.
    """
    from .azure_wiki import parse_azure_devops_url
    import time

    _log = log or logger
    org, project = parse_azure_devops_url(devops_url)
    repo = repo_name or project

    api_token = token or get_az_access_token()
    if not api_token:
        _log.info("No token available for polling — waiting 15 seconds instead")
        time.sleep(15)
        return

    import base64
    auth = base64.b64encode(f":{api_token}".encode()).decode("ascii")
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }
    url = f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}?api-version=7.1"

    _log.info(f"Polling {url}")
    start = time.time()
    attempt = 0
    while time.time() - start < max_wait:
        attempt += 1
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                _log.info(f"Repository '{repo}' is ready (after {int(time.time() - start)}s)")
                return
            _log.info(f"  Attempt {attempt}: repo not ready (HTTP {resp.status_code}), retrying in 5s...")
        except requests.RequestException as e:
            _log.info(f"  Attempt {attempt}: connection error ({e}), retrying in 5s...")
        time.sleep(5)

    _log.warning(f"Repository polling timed out after {max_wait}s — proceeding anyway")


def create_azure_repo(
    devops_url: str,
    name: str,
    token: str | None = None,
) -> str:
    """Create a new Azure DevOps repository.

    Tries az CLI first, falls back to REST API with token.

    Args:
        devops_url: Azure DevOps project URL (https://dev.azure.com/org/project).
        name: Repository name.
        token: Optional PAT.

    Returns:
        The clone URL (https://dev.azure.com/org/project/_git/name).
    """
    from .azure_wiki import parse_azure_devops_url
    org, project = parse_azure_devops_url(devops_url)

    # Try az CLI first
    az = find_az_cli()
    if az:
        try:
            result = subprocess.run(
                [az, "repos", "create",
                 "--name", name,
                 "--project", project,
                 "--org", f"https://dev.azure.com/{org}",
                 "-o", "json"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                import json
                repo_data = json.loads(result.stdout)
                url = repo_data.get("remoteUrl", "")
                if url:
                    logger.info(f"Created Azure DevOps repo via CLI: {url}")
                    return url
                # Construct URL
                url = f"https://dev.azure.com/{org}/{project}/_git/{name}"
                logger.info(f"Created Azure DevOps repo via CLI: {url}")
                return url
            else:
                stderr = result.stderr or ""
                if "already exists" in stderr.lower():
                    raise RuntimeError(
                        f"Repository '{name}' already exists in project '{project}'. "
                        f"Use 'existing repo' instead."
                    )
                logger.warning(f"az repos create failed: {stderr[:200]}")
        except subprocess.TimeoutExpired:
            logger.warning("az repos create timed out")

    # Fallback: REST API
    api_token = token or get_az_access_token()
    if not api_token:
        raise RuntimeError(
            "Cannot create Azure DevOps repo: Azure CLI (az) is not available and no token provided. "
            "Install Azure CLI or provide a Personal Access Token."
        )

    import base64
    auth_header = base64.b64encode(f":{api_token}".encode()).decode("ascii")
    resp = requests.post(
        f"https://dev.azure.com/{org}/{project}/_apis/git/repositories?api-version=7.1",
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/json",
        },
        json={"name": name},
        timeout=15,
    )
    if resp.status_code in (200, 201):
        url = resp.json().get("remoteUrl", f"https://dev.azure.com/{org}/{project}/_git/{name}")
        logger.info(f"Created Azure DevOps repo via API: {url}")
        return url
    if resp.status_code == 409:
        raise RuntimeError(
            f"Repository '{name}' already exists in project '{project}'. "
            f"Use 'existing repo' instead."
        )
    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"Azure DevOps authentication failed ({resp.status_code}). "
            f"Check your token or run 'az login'."
        )
    body = (resp.text or "")[:200]
    raise RuntimeError(f"Azure DevOps repo creation failed ({resp.status_code}): {body}")


# ---------------------------------------------------------------------------
# Git init and push
# ---------------------------------------------------------------------------
def init_and_push(
    folder: str | Path,
    repo_url: str,
    token: str | None = None,
    platform: str = "github",
) -> str:
    """Initialize a git repo in the folder and push to the remote.

    Handles four cases:
    1. Not a git repo → git init, add, commit, push
    2. Git repo with no remote → add remote, push
    3. Git repo with matching remote, already pushed → no-op
    4. Git repo with different remote → raises error

    Args:
        folder: Path to the local folder.
        repo_url: Remote repository URL.
        token: Optional token for authentication.
        platform: "github" or "azure_devops".

    Returns:
        Status message describing what was done.
    """
    folder = Path(folder).resolve()
    status = detect_git_status(folder)
    env = committer_env()

    # Build clone URL with embedded token for push auth
    if platform == "azure_devops":
        from .azure_wiki import parse_azure_devops_url
        # Parse org/project from the URL (works with both project URLs and _git/ URLs)
        org, project = parse_azure_devops_url(repo_url)
        # Extract repo name from /_git/name, or default to project name
        repo_name = repo_url.rstrip("/").split("/")[-1] if "/_git/" in repo_url else project
        if token:
            push_url = f"https://{token}@dev.azure.com/{org}/{project}/_git/{repo_name}"
        else:
            push_url = f"https://dev.azure.com/{org}/{project}/_git/{repo_name}"
    elif token:
        owner, repo = parse_github_url(repo_url)
        push_url = f"https://{token}@github.com/{owner}/{repo}.git"
    else:
        push_url = repo_url
    secrets = [token] if token else []

    # Warn about sensitive files
    sensitive = _check_sensitive_files(folder)
    warnings = []
    if sensitive:
        warnings.append(
            f"Warning: sensitive files detected ({', '.join(sensitive)}). "
            f"Consider adding them to .gitignore."
        )

    # Ensure .gitignore exists with basic exclusions
    _ensure_gitignore(folder)

    # Case 4: Different remote
    if status["is_repo"] and status["remote_url"]:
        def _normalize_remote(url: str) -> str:
            """Normalize a remote URL for comparison (strip _git/ suffix, .git, trailing /)."""
            url = url.rstrip("/").rstrip(".git").rstrip("/")
            # For Azure DevOps, strip /_git/repo to get project URL for comparison
            if "/_git/" in url:
                url = url[:url.index("/_git/")]
            return url.lower()

        if _normalize_remote(status["remote_url"]) != _normalize_remote(repo_url):
            raise RuntimeError(
                f"This folder is already a git repo with a different remote:\n"
                f"  Current: {status['remote_url']}\n"
                f"  Expected: {repo_url}\n"
                f"Remove the .git folder or use a different folder."
            )
        # Update remote URL to the new one (e.g., project URL → proper _git/ URL)
        if status["remote_url"].rstrip("/") != push_url.rstrip("/"):
            run_git(
                ["git", "remote", "set-url", "origin", push_url],
                cwd=str(folder), env_override=env, secrets=secrets,
            )

    # Case 3: Already pushed
    if status["is_repo"] and status["has_commits"] and status["remote_url"]:
        # Check if remote is up to date
        try:
            run_git(
                ["git", "fetch", "origin"],
                cwd=str(folder), env_override=env, secrets=secrets, timeout=30,
            )
        except RuntimeError:
            pass  # May fail if remote is empty or network issue
        msg = "Repository already initialized and pushed."
        if warnings:
            msg += " " + " ".join(warnings)
        logger.info(msg)
        return msg

    # Case 1: Not a git repo
    if not status["is_repo"]:
        logger.info(f"Initializing git repository in {folder}")
        run_git(["git", "init"], cwd=str(folder), env_override=env, secrets=secrets)
        logger.info("git init done, creating main branch...")
        run_git(
            ["git", "checkout", "-b", "main"],
            cwd=str(folder), env_override=env, secrets=secrets,
        )

    # Stage and commit all files
    if not status["has_commits"]:
        logger.info("Staging files...")
        run_git(
            ["git", "add", "-A"],
            cwd=str(folder), env_override=env, secrets=secrets,
        )
        logger.info("Committing...")
        run_git(
            ["git", "commit", "-m", "Initial commit"],
            cwd=str(folder), env_override=env, secrets=secrets,
        )

    # Case 2: No remote set
    if not status["remote_url"]:
        run_git(
            ["git", "remote", "add", "origin", push_url],
            cwd=str(folder), env_override=env, secrets=secrets,
        )
    elif not token:
        # Remote exists but we might need to update it with token for push
        pass
    else:
        # Update remote URL with token
        run_git(
            ["git", "remote", "set-url", "origin", push_url],
            cwd=str(folder), env_override=env, secrets=secrets,
        )

    # Push
    branch = status["branch"] or "main"

    # For Azure DevOps without explicit token, embed az CLI access token in the push URL
    if platform == "azure_devops" and not token:
        az_token = get_az_access_token()
        if az_token:
            from .azure_wiki import parse_azure_devops_url as _parse_az
            _org, _proj = _parse_az(repo_url)
            _rname = repo_url.rstrip("/").split("/")[-1] if "/_git/" in repo_url else _proj
            push_url = f"https://aztoken:{az_token}@dev.azure.com/{_org}/{_proj}/_git/{_rname}"
            secrets.append(az_token)
            # Update remote to use token URL for push
            run_git(
                ["git", "remote", "set-url", "origin", push_url],
                cwd=str(folder), env_override=env, secrets=secrets,
            )

    push_cmd = ["git", "-c", "credential.helper=", "push", "-u", "origin", branch]
    logger.info(f"Pushing to remote (branch={branch})...")

    # Retry push up to 3 times — newly created repos may not be ready immediately
    import time as _time
    last_error = None
    for attempt in range(3):
        try:
            run_git(push_cmd, cwd=str(folder), env_override=env, secrets=secrets, timeout=300)
            last_error = None
            break
        except RuntimeError as e:
            last_error = e
            if attempt < 2:
                logger.warning(f"Push attempt {attempt + 1} failed, retrying in 5s...")
                _time.sleep(5)
    if last_error:
        raise last_error

    # Remove token from remote URL after push (don't persist token on disk)
    if True:  # Always clean up — az token or PAT may be embedded
        try:
            run_git(
                ["git", "remote", "set-url", "origin", repo_url],
                cwd=str(folder), env_override=env, secrets=secrets,
            )
        except RuntimeError:
            pass  # Non-critical

    msg = f"Initialized and pushed to {repo_url}."
    if warnings:
        msg += " " + " ".join(warnings)
    logger.info(msg)
    return msg


def _ensure_gitignore(folder: Path) -> None:
    """Create a basic .gitignore if one doesn't exist."""
    gitignore = folder / ".gitignore"
    if gitignore.exists():
        return

    content = """\
# Auto-generated by Power BI Auto-Documentation
.env
.env.local
.app_settings.json
credentials.json
__pycache__/
*.pyc
.venv/
venv/

# Power BI local cache (can be 1GB+, never commit)
**/.pbi/cache.abf
**/.pbi/localSettings.json
"""
    gitignore.write_text(content, encoding="utf-8")
    logger.info("Created .gitignore with default exclusions")
