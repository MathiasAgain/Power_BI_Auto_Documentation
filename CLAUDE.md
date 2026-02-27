# Power BI Auto-Documentation

## Project Overview

Automated documentation pipeline for Power BI. Extracts metadata from PBIX or PBIP files and generates wiki pages (GitHub or Azure DevOps) with Mermaid ER diagrams, DAX measure references, and optional AI-generated descriptions.

## Architecture

Two input paths, two output platforms:

```
PBIX File  → PBIXRay MCP Server (stdio) → ModelMetadata ─┐
                                                          ├→ Wiki Generator → GitHub Wiki / Azure DevOps Wiki
PBIP File  → Direct BIM/TMDL Parser     → ModelMetadata ─┘
```

### Layers

1. **Parsers** (`src/parsers/`) — PBIP/BIM/TMDL direct parsing (no MCP needed)
2. **MCP Client** (`src/mcp_client/`) — async JSON-RPC 2.0 over stdio (PBIX only)
3. **Generators** (`src/generators/`) — transforms metadata into wiki pages
4. **AI Enrichment** (`src/enrichment/`) — Claude API for business-friendly DAX descriptions
5. **Utilities** (`src/utils/`) — markdown helpers, settings, git operations, CI/CD deployment
6. **Entry Points** — CLI scripts, Streamlit web app, Claude Code slash command

## Project Structure

```
src/
├── models.py                    # Dataclasses: Column, Measure, Relationship, Table, ModelMetadata
├── parsers/
│   └── pbip_parser.py           # PBIP parser — BIM (JSON) and TMDL folder formats
├── mcp_client/
│   ├── client.py                # Base MCP protocol client (async, stdio transport)
│   └── pbixray_tools.py         # PBIXRay tool wrappers with PascalCase field mapping
├── generators/
│   ├── wiki_generator.py        # Single-model orchestrator (auto-detects PBIX vs PBIP)
│   ├── multi_model.py           # Multi-model portal generator
│   ├── pages.py                 # Individual page generators + canonical slugify()
│   └── mermaid.py               # Mermaid erDiagram + measure dependency graph
├── enrichment/
│   └── ai_descriptions.py       # Claude AI descriptions with hash-based JSON cache
└── utils/
    ├── markdown.py              # Markdown table/code block helpers
    ├── settings.py              # AppSettings persistence (JSON)
    ├── git_helpers.py           # Shared git helper: run_git(), parse_github_url(), committer_env(), validate_repo_slug(), TOOL_REPO
    ├── git_wiki.py              # GitHub Wiki clone/commit/push
    ├── azure_wiki.py            # Azure DevOps Wiki clone/commit/push (auto-initializes wiki, az CLI auth fallback)
    ├── workflow_template.py     # GitHub Actions YAML template (imports TOOL_REPO/validate from git_helpers)
    ├── deploy_workflow.py       # Deploy GitHub Actions workflow via Contents API
    ├── azure_pipeline_template.py  # Azure Pipelines YAML template (imports TOOL_REPO/validate from git_helpers)
    └── deploy_pipeline.py       # Deploy Azure Pipeline via Push API

app.py                           # Streamlit web UI
generate_wiki.py                 # CLI: single model
generate_wiki_multi.py           # CLI: multi-model portal
.claude/commands/generate-wiki.md  # Claude Code slash command
.github/workflows/generate-wiki.yml  # GitHub Actions
```

## Entry Points

### Streamlit App (recommended for first-time users)

```bash
./venv/Scripts/streamlit run app.py
```
The web UI provides a guided workflow with live log streaming, preview, and one-click deployment. Azure DevOps users can authenticate via an in-app "Login to Azure" button (uses `az` CLI) — no PAT needed.

### CLI
```bash
# PBIX file (uses PBIXRay MCP server)
python generate_wiki.py "path/to/model.pbix" -o ./wiki-output -v

# PBIP file or semantic model folder (parsed directly, no MCP needed)
python generate_wiki.py "path/to/project.pbip" -o ./wiki-output -v
python generate_wiki.py "path/to/Model.SemanticModel" -o ./wiki-output -v

# With AI descriptions (requires ANTHROPIC_API_KEY env var)
python generate_wiki.py "path/to/model.pbix" -o ./wiki-output --ai-descriptions
```

### Claude Code Slash Command

```
/generate-wiki
```
Interactive walkthrough: file selection → platform choice → AI enrichment → generate → push → deploy pipeline.

## Code Conventions

- **`slugify()`** is the canonical slug function, defined in `src/generators/pages.py`. Do not duplicate it.
- All page generators accept `page_prefix: str = ""` for multi-model wiki link correctness.
- GitHub Wiki is flat — multi-model mode uses `{ModelName}-` prefix on all filenames.
- PBIXRay returns **PascalCase** field names (`TableName`, `Name`, `Expression`, `FromTableName`). The `_get()` helper in `pbixray_tools.py` handles fallback lookups.
- PBIXRay's `get_tables` returns a numpy StringArray repr, not JSON. Parsed via `ast.literal_eval`.
- Field naming: `Column.table` and `Measure.table` (not `table_name`).
- Mermaid entity names go through `_sanitize_name()`, labels through `_sanitize_label()`.
- Wiki links use `[[display text|page-slug]]` syntax (no `.md` extension).
- `_Sidebar.md` is a special GitHub Wiki file for navigation.
- All git operations go through `src/utils/git_helpers.py` which sanitizes tokens from error messages (both stdout and stderr).
- Shared constants live in `git_helpers.py`: `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL`, `TOOL_REPO`, `committer_env()`, `parse_github_url()`, `validate_repo_slug()`. Do not duplicate these.
- URL parsers enforce HTTPS only — `http://` URLs are rejected for security.
- `az` CLI is located via `shutil.which("az")` — never use `shell=True` for subprocess calls.

## PBIP Support

The parser (`src/parsers/pbip_parser.py`) supports both PBIP formats:
- **model.bim** (TMSL/JSON) — single JSON file with full model definition
- **TMDL** — folder with individual .tmdl files per table + relationships.tmdl, expressions.tmdl

Auto-detection works from any of:
- `.pbip` file → finds the `.SemanticModel` directory next to it
- `.SemanticModel` directory directly
- Directory containing `model.bim` or `definition/` folder

PBIP files do NOT require the PBIXRay MCP server — they are parsed directly.

## PBIXRay MCP Server

The MCP server is cloned into `pbixray-mcp-server/` and installed in editable mode. The working server command is:
```
python pbixray-mcp-server/src/pbixray_server.py
```
The `python -m pbixray_server` entry point does not work due to the module being in a `src/` subfolder.

## Key Tool Names (PBIXRay)

Defined in `src/mcp_client/pbixray_tools.py`:
- `load_pbix_file` — load a PBIX file
- `get_tables` — list table names
- `get_schema` — get columns for a table
- `get_dax_measures` — get all DAX measures
- `get_relationships` — get model relationships
- `get_power_query` — get M/Power Query expressions
- `get_model_summary` — get model summary stats

## GitHub Support

- **Wiki push:** `src/utils/git_wiki.py` — clones `{repo}.wiki.git`, copies markdown, commits, pushes
- **Workflow template:** `src/utils/workflow_template.py` — GitHub Actions YAML with `{tool_repo}` substitution
- **Workflow deploy:** `src/utils/deploy_workflow.py` — creates/updates `.github/workflows/generate-wiki.yml` via Contents API
- Auth uses PAT via Bearer token in GitHub API, or embedded in git URL for clone/push

## Azure DevOps Support

- **Wiki push:** `src/utils/azure_wiki.py` — clones/pushes to `dev.azure.com/{org}/{project}/_git/{project}.wiki`
- **Wiki auto-init:** `ensure_wiki_exists()` creates the project wiki if it doesn't exist
  - Tries `az devops wiki create` CLI first (works if user is logged in)
  - Falls back to REST API with PAT
- **Auth fallback chain for git push** (in `push_to_azure_wiki()`):
  1. PAT embedded in clone URL (if provided)
  2. `az` CLI access token via `http.extraHeader` (if `az` is logged in, no PAT needed)
  3. Git credential helper (system default)
- **Pipeline template:** `src/utils/azure_pipeline_template.py` — Azure Pipelines YAML
- **Pipeline deploy:** `src/utils/deploy_pipeline.py` — pushes `azure-pipelines.yml` via Push API + auto-creates pipeline definition; supports empty repos
- Supports both modern (`dev.azure.com`) and legacy (`{org}.visualstudio.com`) URL formats
- **Streamlit UI:** "Login to Azure" button runs `az login` via `shutil.which("az")`; PAT is optional in an expander

## Dependencies

- `mcp>=1.0.0,<2.0.0` — Anthropic MCP SDK
- `anthropic>=0.40.0` — Claude API client
- `pbixray>=0.3.0` — PBIX file parsing
- `requests>=2.28.0` — HTTP for GitHub/Azure DevOps APIs
- `streamlit>=1.30.0` — Web UI

## Known Issues & Troubleshooting

### GitHub Wiki must be initialized manually

GitHub does not expose an API to create a wiki. The `.wiki.git` repo only exists after the first page is created through the web UI. Before the tool can push documentation, the user must:
1. Go to `https://github.com/<org>/<repo>/wiki`
2. Click "Create the first page" and save it (content doesn't matter — it will be overwritten)

This is a GitHub platform limitation. Neither the REST API, GraphQL API, nor `gh` CLI can initialize a wiki programmatically. The tool detects this and gives the user clear instructions if the wiki push fails with "Repository not found".

### Azure DevOps Wiki is auto-initialized

Unlike GitHub, Azure DevOps supports creating wikis via the REST API (`POST /_apis/wiki/wikis`). The tool calls `ensure_wiki_exists()` automatically before pushing — no manual step needed.

### PAT permissions

- **GitHub:** Needs `Contents: Read and write` scope for both wiki push and workflow deploy
- **Azure DevOps:** PAT is optional if `az` CLI is logged in. All operations (wiki push, pipeline deploy) work with CLI auth. When a PAT is used, it needs `Code: Read & Write` and `Wiki: Read & Write` scopes.

### AI enrichment is slow for large models

The tool calls the Claude API once per measure. For models with 1000+ measures, this can take several minutes. Consider running without AI descriptions first, then enabling it in the CI/CD pipeline.

## Settings

The Streamlit app persists settings to `.app_settings.json` (gitignored). API keys are only saved if the user opts in via the "Remember API keys between sessions" checkbox. On Linux/macOS, the file is `chmod 600` when secrets are stored.

## Testing

```bash
# Verify imports
python -c "from src.generators.wiki_generator import WikiGenerator; print('OK')"

# Discover MCP tools
python generate_wiki.py --discover dummy.pbix
```
