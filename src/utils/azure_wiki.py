"""Azure DevOps Wiki git operations — clone, update, commit, push."""

import base64
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests

from .cli_auth import find_az_cli, get_az_access_token
from .git_helpers import run_git, committer_env

logger = logging.getLogger(__name__)


def parse_azure_devops_url(url: str) -> tuple[str, str]:
    """Extract (org, project) from an Azure DevOps URL.

    Supports:
        https://dev.azure.com/{org}/{project}
        https://dev.azure.com/{org}/{project}/
        https://dev.azure.com/{org}/{project}/_git/...
        https://{org}.visualstudio.com/{project}
    """
    # Modern format: dev.azure.com
    match = re.match(
        r"https://dev\.azure\.com/(?P<org>[A-Za-z0-9][A-Za-z0-9 _.-]*)/(?P<project>[A-Za-z0-9][A-Za-z0-9 _.-]*)",
        url.strip(),
    )
    if match:
        return match.group("org"), match.group("project")

    # Legacy format: {org}.visualstudio.com
    match = re.match(
        r"https://(?P<org>[A-Za-z0-9][A-Za-z0-9_.-]*)\.visualstudio\.com/(?P<project>[A-Za-z0-9][A-Za-z0-9 _.-]*)",
        url.strip(),
    )
    if match:
        return match.group("org"), match.group("project")

    raise ValueError(
        f"Cannot parse Azure DevOps URL: {url}. "
        f"Expected: https://dev.azure.com/org/project (HTTPS required)"
    )


def build_wiki_git_url(org: str, project: str, token: str | None = None) -> str:
    """Build the git URL for an Azure DevOps project wiki."""
    if token:
        return f"https://{token}@dev.azure.com/{org}/{project}/_git/{project}.wiki"
    return f"https://dev.azure.com/{org}/{project}/_git/{project}.wiki"


def ensure_wiki_exists(org: str, project: str, token: str | None = None) -> str:
    """Create the project wiki if it doesn't exist. Returns the wiki name.

    Unlike GitHub, Azure DevOps supports creating wikis programmatically.
    Tries `az` CLI first (uses existing Azure login), falls back to REST API with PAT.
    If the wiki already exists, this is a no-op.
    """
    wiki_name = f"{project}.wiki"

    # Try az CLI first — works without PAT if user is logged in
    if _ensure_wiki_via_az_cli(org, project, wiki_name):
        return wiki_name

    # Fall back to REST API (requires PAT)
    if not token:
        logger.warning(
            "Could not create wiki via az CLI and no PAT provided. "
            "The wiki push may fail if the wiki doesn't exist yet."
        )
        return wiki_name

    return _ensure_wiki_via_rest_api(org, project, token, wiki_name)


def _ensure_wiki_via_az_cli(org: str, project: str, wiki_name: str) -> bool:
    """Try to ensure the wiki exists using `az devops wiki` CLI. Returns True on success."""
    az = find_az_cli()
    if not az:
        logger.debug("az CLI not found")
        return False

    try:
        # Check if az CLI is available and list wikis
        result = subprocess.run(
            [az, "devops", "wiki", "list",
             "--project", project,
             "--org", f"https://dev.azure.com/{org}",
             "-o", "json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            import json
            wikis = json.loads(result.stdout)
            for wiki in wikis:
                if wiki.get("type", "").lower() == "projectwiki":
                    logger.info(f"Wiki already exists: {wiki.get('name', wiki_name)}")
                    return True

            # Wiki doesn't exist — create it
            create_result = subprocess.run(
                [az, "devops", "wiki", "create",
                 "--name", wiki_name,
                 "--type", "projectwiki",
                 "--project", project,
                 "--org", f"https://dev.azure.com/{org}",
                 "-o", "json"],
                capture_output=True, text=True, timeout=15,
            )
            if create_result.returncode == 0:
                logger.info(f"Created project wiki via az CLI: {wiki_name}")
                return True
            else:
                logger.debug(f"az wiki create failed: {create_result.stderr}")
                return False
        else:
            logger.debug(f"az wiki list failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        logger.debug("az CLI timed out")
        return False


def _ensure_wiki_via_rest_api(org: str, project: str, token: str, wiki_name: str) -> str:
    """Create the wiki using the Azure DevOps REST API with a PAT."""
    auth = base64.b64encode(f":{token}".encode()).decode("ascii")
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }
    base_url = f"https://dev.azure.com/{org}/{project}/_apis/wiki/wikis"

    # Check if a project wiki already exists
    list_resp = requests.get(f"{base_url}?api-version=7.1", headers=headers, timeout=15)
    if list_resp.status_code == 200:
        wikis = list_resp.json().get("value", [])
        for wiki in wikis:
            if wiki.get("type", "").lower() == "projectwiki":
                logger.info(f"Wiki already exists: {wiki['name']}")
                return wiki["name"]

    # Get the project ID (required for wiki creation)
    project_resp = requests.get(
        f"https://dev.azure.com/{org}/_apis/projects/{project}?api-version=7.1",
        headers=headers,
        timeout=15,
    )
    if project_resp.status_code != 200:
        raise RuntimeError(
            f"Could not fetch project info for {org}/{project} (HTTP {project_resp.status_code}). "
            f"Ensure the PAT has project read access."
        )
    project_id = project_resp.json()["id"]

    # Create the project wiki
    create_resp = requests.post(
        f"{base_url}?api-version=7.1",
        headers=headers,
        json={
            "type": "projectWiki",
            "name": wiki_name,
            "projectId": project_id,
        },
        timeout=15,
    )

    if create_resp.status_code == 201:
        logger.info(f"Created project wiki: {wiki_name}")
        return wiki_name
    elif create_resp.status_code == 409:
        # Wiki already exists (race condition)
        logger.info("Wiki already exists (409 conflict)")
        return wiki_name
    else:
        body = (create_resp.text or "")[:200]
        raise RuntimeError(
            f"Failed to create wiki (HTTP {create_resp.status_code}): {body}"
        )


def push_to_azure_wiki(
    source_dir: str | Path,
    devops_url: str,
    token: str | None = None,
    commit_message: str = "docs: update Power BI documentation",
) -> str:
    """Clone the Azure DevOps wiki repo, copy markdown files, commit, and push.

    Auth fallback chain:
      1. PAT embedded in clone URL (if provided)
      2. az CLI access token via http.extraHeader (if az is logged in)
      3. git credential helper (system default)

    Args:
        source_dir: Directory containing generated .md files.
        devops_url: Azure DevOps project URL (https://dev.azure.com/org/project).
        token: Azure DevOps Personal Access Token.
        commit_message: Git commit message.

    Returns:
        Result message string.
    """
    source_dir = Path(source_dir)
    org, project = parse_azure_devops_url(devops_url)

    # Auto-initialize wiki if it doesn't exist (tries az CLI first, then REST API with PAT)
    ensure_wiki_exists(org, project, token)

    safe_url = build_wiki_git_url(org, project, None)

    # Determine auth method for git operations
    az_token = None
    if token:
        wiki_url = build_wiki_git_url(org, project, token)
        auth_method = "PAT"
    else:
        wiki_url = safe_url
        az_token = get_az_access_token()
        auth_method = "az CLI token" if az_token else "credential helper"

    logger.info(f"Using {auth_method} for git authentication")

    md_files = list(source_dir.glob("*.md"))
    if not md_files:
        raise RuntimeError(f"No .md files found in {source_dir}")

    clone_dir = Path(tempfile.mkdtemp(prefix="azwiki-push-"))
    wiki_dir = clone_dir / "wiki"

    # Collect secrets to sanitize from any error messages
    secrets = [s for s in [token, az_token] if s]

    # Extra git config for az CLI token auth (like the Azure Pipelines template uses)
    extra_header_cfg = []
    if az_token:
        import base64 as _b64
        bearer = _b64.b64encode(f":{az_token}".encode()).decode("ascii")
        extra_header_cfg = [
            "-c", f"http.extraHeader=Authorization: Basic {bearer}",
            "-c", "credential.helper=",  # Disable GCM — we provide auth via header
        ]

    def _git(cmd: list[str], **kwargs):
        """Run git with optional extra header for az CLI auth."""
        full_cmd = ["git"] + extra_header_cfg + cmd
        return run_git(full_cmd, cwd=str(wiki_dir), secrets=secrets, **kwargs)

    try:
        logger.info(f"Cloning Azure DevOps wiki from {safe_url}...")
        clone_cmd = ["git"] + extra_header_cfg + ["clone", wiki_url, str(wiki_dir)]
        run_git(clone_cmd, cwd=str(clone_dir), secrets=secrets)

        # Remove existing markdown and .order files
        for existing in wiki_dir.glob("*.md"):
            existing.unlink()
        order_file = wiki_dir / ".order"
        if order_file.exists():
            order_file.unlink()

        # Copy new files
        for md_file in md_files:
            shutil.copy2(md_file, wiki_dir / md_file.name)

        # Copy .order file (controls Azure DevOps wiki sidebar ordering)
        source_order = source_dir / ".order"
        if source_order.exists():
            shutil.copy2(source_order, wiki_dir / ".order")
            logger.info(f"Copied {len(md_files)} pages + .order file to wiki repo")
        else:
            logger.info(f"Copied {len(md_files)} pages to wiki repo")

        _git(["add", "-A"])

        # Check for changes
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            cwd=str(wiki_dir),
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            msg = "No changes to push — wiki is already up to date."
            logger.info(msg)
            return msg

        _git(
            ["commit", "-m", commit_message],
            env_override=committer_env(),
        )
        _git(["push"])

        msg = f"Successfully pushed {len(md_files)} pages to {safe_url}"
        logger.info(msg)
        return msg

    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)
