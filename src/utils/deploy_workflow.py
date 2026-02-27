"""Deploy a GitHub Actions workflow to a target repository via the GitHub Contents API."""

import base64
import logging

import requests

from .git_helpers import parse_github_url, GIT_COMMITTER_NAME, GIT_COMMITTER_EMAIL
from .workflow_template import render_workflow

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
WORKFLOW_PATH = ".github/workflows/generate-wiki.yml"


# Keep backward-compatible alias
parse_owner_repo = parse_github_url


def deploy_workflow(
    repo_url: str,
    token: str,
    tool_repo: str | None = None,
) -> str:
    """Deploy the wiki-generation workflow to the target repository.

    Uses the GitHub Contents API (PUT /repos/{owner}/{repo}/contents/{path}).
    Creates the file if it does not exist; updates it if it does.

    Args:
        repo_url: Target GitHub repository URL.
        token: GitHub Personal Access Token with contents:write scope.
        tool_repo: Override the tool repo (default: MathiasAgain/Power_BI_Auto_Documentation).

    Returns:
        A human-readable result message.
    """
    owner, repo = parse_owner_repo(repo_url)
    workflow_content = render_workflow(tool_repo)
    encoded_content = base64.b64encode(workflow_content.encode("utf-8")).decode("ascii")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    api_url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{WORKFLOW_PATH}"

    # Check if the file already exists (to get its SHA for an update)
    existing_sha = None
    get_resp = requests.get(api_url, headers=headers, timeout=15)
    if get_resp.status_code == 200:
        existing_sha = get_resp.json().get("sha")
        logger.info(f"Workflow already exists (sha={existing_sha[:8]}...), will update.")
    elif get_resp.status_code == 404:
        logger.info("Workflow does not exist yet, will create.")
    elif get_resp.status_code == 401:
        raise RuntimeError(
            "Authentication failed (HTTP 401). Check your GitHub Personal Access Token."
        )
    elif get_resp.status_code == 403:
        raise RuntimeError(
            "Permission denied (HTTP 403). Ensure your PAT has 'Contents: Read and write' permission."
        )
    else:
        body = (get_resp.text or "")[:200]
        raise RuntimeError(
            f"Failed to check workflow file (HTTP {get_resp.status_code}): {body}"
        )

    # Create or update
    payload = {
        "message": "ci: add Power BI wiki auto-generation workflow",
        "content": encoded_content,
        "committer": {
            "name": GIT_COMMITTER_NAME,
            "email": GIT_COMMITTER_EMAIL,
        },
    }
    if existing_sha:
        payload["sha"] = existing_sha
        payload["message"] = "ci: update Power BI wiki auto-generation workflow"

    put_resp = requests.put(api_url, headers=headers, json=payload, timeout=30)

    if put_resp.status_code in (200, 201):
        action = "Updated" if existing_sha else "Created"
        return (
            f"{action} workflow at {owner}/{repo}/{WORKFLOW_PATH}. "
            f"The wiki will now auto-update when you push Power BI file changes."
        )

    if put_resp.status_code == 403:
        raise RuntimeError(
            "Permission denied (HTTP 403). Ensure your Personal Access Token has "
            "'Contents: Read and write' permission for the target repository."
        )
    if put_resp.status_code == 422:
        body = (put_resp.text or "")[:200]
        raise RuntimeError(
            f"Validation failed (HTTP 422). Details: {body}"
        )

    body = (put_resp.text or "")[:200]
    raise RuntimeError(
        f"Failed to deploy workflow (HTTP {put_resp.status_code}): {body}"
    )
