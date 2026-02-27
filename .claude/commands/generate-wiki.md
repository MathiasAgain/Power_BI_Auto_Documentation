Generate wiki documentation from a Power BI file (PBIX or PBIP) and publish to GitHub or Azure DevOps.

Before starting, briefly explain:

> **This tool will:**
> 1. Create a repository (or use an existing one)
> 2. Push your Power BI files to it
> 3. Generate wiki documentation
> 4. Publish the wiki
> 5. Optionally set up automatic updates so the wiki stays in sync
>
> No git knowledge required — the tool handles everything.

## Prerequisites

Before running, ensure:

- The virtual environment is activated (`./venv/Scripts/activate` on Windows)
- Required packages are installed (`pip install -r requirements.txt`)

Then walk through these steps interactively:

## Step 1: Locate the Power BI file

Recommend the user to create a dedicated folder for their project first:
- **PBIX:** Create a new folder and move the `.pbix` file into it.
- **PBIP:** Create a new folder and move the `.pbip` file along with its companion folders (`.SemanticModel/`, `.Report/`) into it.

Then ask for the path to the Power BI file. Supported inputs:

- `.pbip` file (recommended — parsed directly)
- `.pbix` file (binary format — requires PBIXRay server)
- Semantic model directory (`*.SemanticModel` or `*.Dataset`)

Verify the file/directory exists and detect the input type.

## Step 2: Choose platform and authenticate

Ask: **GitHub or Azure DevOps?**

### If GitHub:

- Check if `gh` CLI is logged in by running: `gh api user --jq .login`
  - If logged in: no further auth needed — the tool uses `gh auth token` for all operations
  - If not logged in: run `gh auth login --web` (opens browser) or ask for a personal access token

### If Azure DevOps:

- Ask for the Azure DevOps project URL (e.g., `https://dev.azure.com/org/project`)
- Check if `az` CLI is logged in by running: `az account show --query user.name -o tsv`
  - If logged in: no further auth needed — the tool uses `az` CLI for all operations
  - If not logged in: run `az login` (opens browser) or ask for a personal access token

## Step 3: Create or select a repository

Ask: **Create a new repo or use an existing one?**

### If creating a new repo:

- Ask for the repo name (suggest the Power BI filename stem as default)
- Ask if they want it private (default: yes)

**Azure DevOps only:** Ask if they want to create a new project or use an existing one.

If creating a new project:
```bash
python -c "from src.utils.repo_manager import create_azure_project; print(create_azure_project('https://dev.azure.com/<org>', '<project_name>'))"
```

Then create the repo:

```bash
# GitHub:
python -c "from src.utils.repo_manager import create_github_repo; print(create_github_repo('<name>', private=True))"

# Azure DevOps (use the project URL from above or an existing one):
python -c "from src.utils.repo_manager import create_azure_repo; print(create_azure_repo('https://dev.azure.com/<org>/<project>', '<name>'))"
```

### If using an existing repo:

- Ask for the repository URL

### Push source files to the repo:

```bash
python -c "from src.utils.repo_manager import init_and_push; print(init_and_push('<folder_path>', '<repo_url>', platform='<platform>'))"
```

This handles git init, add, commit, and push automatically. If the folder is already a git repo, it skips what's already done.

## Step 4: Initialize wiki (GitHub only)

**GitHub:** The wiki must be initialized manually (one-time). Tell the user:

1. Go to `https://github.com/<org>/<repo>/wiki`
2. Click "Create the first page" and save it (content doesn't matter)
3. This is a one-time GitHub limitation

**Azure DevOps:** Skip this step — the wiki is created automatically.

## Step 5: Model display name

Ask for the model display name (suggest the filename stem as default).

## Step 6: AI descriptions (optional)

Ask if they want AI-generated descriptions for their measures. If yes:

- Check if `ANTHROPIC_API_KEY` is set in the environment
- If not, ask them to provide it (get one at console.anthropic.com)
- Mention this adds a few seconds per measure

## Step 7: Generate and publish

```bash
python generate_wiki.py "<file_path>" -o wiki-output -n "<name>" --platform <platform> -v
```

- Replace `<platform>` with `github` or `azure_devops` based on the user's choice in Step 2. **This is required** — it controls link syntax and diagram rendering.
- Add `--ai-descriptions` if AI descriptions were requested.

After generation:

1. List generated files in the output directory
2. Show the Home.md so they can verify
3. Report the statistics (tables, measures, relationships, pages)

## Step 8: Push to Wiki

### GitHub:

```bash
python -c "from src.utils.git_wiki import push_to_wiki; print(push_to_wiki('wiki-output', '<repo_url>'))"
```

**If the push fails with "Repository not found":**

1. The wiki hasn't been initialized — go back to Step 4
2. After creating the page, retry the push

### Azure DevOps:

```bash
python -c "from src.utils.azure_wiki import push_to_azure_wiki; print(push_to_azure_wiki('wiki-output', '<devops_url>'))"
```

## Step 9: Set up automatic updates (optional)

Ask if they want the wiki to auto-update whenever they push changes to their Power BI files.

### GitHub:

```bash
python -c "from src.utils.deploy_workflow import deploy_workflow; print(deploy_workflow('<repo_url>', '<token>'))"
```

The token comes from `gh auth token` if no personal access token was provided.

To enable AI descriptions in automatic updates, they can add `ANTHROPIC_API_KEY` as a repository secret (Settings > Secrets and variables > Actions).

### Azure DevOps:

If `az` CLI is logged in, **no PAT is needed** — pass `None` as the token:

```bash
python -c "from src.utils.deploy_pipeline import deploy_azure_pipeline; print(deploy_azure_pipeline('<devops_url>'))"
```

Only pass a token if `az` CLI is not logged in:

```bash
python -c "from src.utils.deploy_pipeline import deploy_azure_pipeline; print(deploy_azure_pipeline('<devops_url>', '<token>'))"
```

The pipeline is created automatically — no manual setup needed.

To enable AI descriptions in automatic updates, they can add `AnthropicApiKey` as a pipeline variable.

## Important notes

- **Never ask for a PAT if the user is already logged in via `gh` or `az` CLI.** All operations (repo creation, wiki push, pipeline deploy) work with CLI auth alone.
- PBIP files are parsed directly — no server needed
- PBIX files require the PBIXRay server
- GitHub wikis must be initialized manually (one-time); Azure DevOps wikis are auto-created
- The virtual environment should be activated before running
- Credentials are never stored in the wiki or logged in output
