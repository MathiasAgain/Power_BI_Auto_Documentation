"""Deploy an Azure Pipelines YAML to an Azure DevOps repository via REST API."""

import base64
import logging

import requests

from .azure_wiki import parse_azure_devops_url
from .azure_pipeline_template import render_pipeline
from .cli_auth import get_az_access_token

logger = logging.getLogger(__name__)

PIPELINE_PATH = "azure-pipelines.yml"
PIPELINE_NAME = "Power BI Wiki Generator"


def _try_create_pipeline_definition(
    org: str,
    project: str,
    repo: str,
    headers: dict[str, str],
    base_api: str,
) -> str:
    """Try to create an Azure Pipelines definition from the YAML file.

    Returns a human-readable status message.
    """
    # Get the repository ID (needed for pipeline creation)
    try:
        repo_resp = requests.get(f"{base_api}?api-version=7.1", headers=headers, timeout=15)
        if repo_resp.status_code != 200:
            return "Go to Pipelines in Azure DevOps to create a pipeline from this file."
        repo_id = repo_resp.json()["id"]
    except Exception:
        return "Go to Pipelines in Azure DevOps to create a pipeline from this file."

    # Check if a pipeline with this name already exists
    pipelines_api = f"https://dev.azure.com/{org}/{project}/_apis/pipelines"
    try:
        list_resp = requests.get(
            f"{pipelines_api}?api-version=7.1", headers=headers, timeout=15
        )
        if list_resp.status_code == 200:
            for p in list_resp.json().get("value", []):
                if p.get("name") == PIPELINE_NAME:
                    return (
                        f"Pipeline '{PIPELINE_NAME}' already exists. "
                        f"Wiki will auto-update when you push Power BI file changes."
                    )
    except Exception:
        pass

    # Create the pipeline
    try:
        create_resp = requests.post(
            f"{pipelines_api}?api-version=7.1",
            headers=headers,
            json={
                "folder": "\\",
                "name": PIPELINE_NAME,
                "configuration": {
                    "type": "yaml",
                    "path": f"/{PIPELINE_PATH}",
                    "repository": {
                        "id": repo_id,
                        "type": "azureReposGit",
                    },
                },
            },
            timeout=15,
        )
        if create_resp.status_code in (200, 201):
            logger.info(f"Created pipeline '{PIPELINE_NAME}' in {org}/{project}")
            return (
                f"Pipeline '{PIPELINE_NAME}' created automatically. "
                f"Wiki will auto-update when you push Power BI file changes."
            )
        else:
            body = (create_resp.text or "")[:150]
            logger.debug(f"Pipeline creation failed (HTTP {create_resp.status_code}): {body}")
            return "Go to Pipelines in Azure DevOps to create a pipeline from this file."
    except Exception as e:
        logger.debug(f"Pipeline creation failed: {e}")
        return "Go to Pipelines in Azure DevOps to create a pipeline from this file."


def deploy_azure_pipeline(
    devops_url: str,
    token: str | None = None,
    repo_name: str | None = None,
    tool_repo: str | None = None,
) -> str:
    """Deploy the wiki-generation pipeline to an Azure DevOps repository.

    Uses the Azure DevOps Git Push API to create or update azure-pipelines.yml.
    Falls back to Azure CLI access token if no PAT is provided.

    Args:
        devops_url: Azure DevOps project URL (https://dev.azure.com/org/project).
        token: Optional PAT with Code (Read & Write) scope. Falls back to az CLI.
        repo_name: Repository name within the project. Defaults to the project name.
        tool_repo: Override the tool repo (default: MathiasAgain/Power_BI_Auto_Documentation).

    Returns:
        A human-readable result message.
    """
    org, project = parse_azure_devops_url(devops_url)
    repo = repo_name or project
    pipeline_content = render_pipeline(tool_repo)

    api_token = token or get_az_access_token()
    if not api_token:
        raise RuntimeError(
            "Cannot deploy pipeline: no PAT provided and Azure CLI is not logged in. "
            "Run 'az login' or enter a PAT in Step 2."
        )

    auth = base64.b64encode(f":{api_token}".encode()).decode("ascii")
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }

    base_api = f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}"

    # Get the default branch ref — try 'main' first, then 'master'
    refs_data = None
    for branch_name in ("main", "master"):
        refs_resp = requests.get(
            f"{base_api}/refs?filter=heads/{branch_name}&api-version=7.1",
            headers=headers,
            timeout=15,
        )
        if refs_resp.status_code != 200:
            raise RuntimeError(
                f"Failed to access repo {org}/{project}/{repo} (HTTP {refs_resp.status_code}). "
                f"Ensure the PAT has 'Code: Read & Write' scope."
            )
        data = refs_resp.json()
        if data.get("value"):
            refs_data = data
            break

    if refs_data is None:
        # Repo is empty (no commits yet) — we can create the initial commit
        logger.info(f"Repo {org}/{project}/{repo} is empty — creating initial commit")
        old_object_id = "0" * 40
        ref_name = "refs/heads/main"
        file_exists = False
    else:
        branch_ref = refs_data["value"][0]
        old_object_id = branch_ref["objectId"]
        ref_name = branch_ref["name"]

        # Check if the file already exists
        item_resp = requests.get(
            f"{base_api}/items?path={PIPELINE_PATH}&api-version=7.1",
            headers=headers,
            timeout=15,
        )
        file_exists = item_resp.status_code == 200

    # Build the push payload
    change_type = "edit" if file_exists else "add"
    content_b64 = base64.b64encode(pipeline_content.encode("utf-8")).decode("ascii")

    push_payload = {
        "refUpdates": [
            {
                "name": ref_name,
                "oldObjectId": old_object_id,
            }
        ],
        "commits": [
            {
                "comment": "ci: add Power BI wiki auto-generation pipeline"
                if not file_exists
                else "ci: update Power BI wiki auto-generation pipeline",
                "changes": [
                    {
                        "changeType": change_type,
                        "item": {"path": f"/{PIPELINE_PATH}"},
                        "newContent": {
                            "content": content_b64,
                            "contentType": "base64encoded",
                        },
                    }
                ],
            }
        ],
    }

    push_resp = requests.post(
        f"{base_api}/pushes?api-version=7.1",
        headers=headers,
        json=push_payload,
        timeout=30,
    )

    if push_resp.status_code in (200, 201):
        action = "Updated" if file_exists else "Created"
        logger.info(f"{action} {PIPELINE_PATH} in {org}/{project}/{repo}")

        # Try to auto-create the pipeline definition (so user doesn't have to do it manually)
        pipeline_msg = _try_create_pipeline_definition(
            org, project, repo, headers, base_api
        )

        msg = (
            f"{action} pipeline YAML at {org}/{project}/{PIPELINE_PATH}. "
            f"{pipeline_msg}"
        )
        logger.info(msg)
        return msg

    if push_resp.status_code == 401:
        raise RuntimeError(
            "Authentication failed (HTTP 401). Check your Azure DevOps PAT."
        )
    if push_resp.status_code == 403:
        raise RuntimeError(
            "Permission denied (HTTP 403). Ensure your PAT has 'Code: Read & Write' scope."
        )

    body = (push_resp.text or "")[:200]
    raise RuntimeError(
        f"Failed to deploy pipeline (HTTP {push_resp.status_code}): {body}"
    )
