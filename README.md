# Power BI Auto-Documentation

Automatically generate wiki documentation from your Power BI files. Tables, measures, relationships, data sources, and interactive diagrams — all published to GitHub or Azure DevOps Wiki with one command.

## What You Get

- **Full model documentation** — every table, column, measure, and relationship
- **Interactive diagrams** — visual relationship maps rendered natively in your wiki
- **Measure formulas** — all DAX expressions with dependency tracking
- **Data sources** — Power Query/M expressions documented
- **Sidebar navigation** — organized, clickable page structure
- **AI descriptions** (optional) — plain-language explanations for your DAX measures
- **Auto-update pipeline** (optional) — wiki regenerates whenever you push changes

Works with both **PBIP** (recommended) and **PBIX** files.

## Prerequisites

Before you start, make sure you have:

| Requirement | How to get it |
|---|---|
| **Python 3.11+** | [python.org/downloads](https://www.python.org/downloads/) |
| **Git** | [git-scm.com/downloads](https://git-scm.com/downloads) |
| **Azure CLI** (for Azure DevOps) | `winget install Microsoft.AzureCLI` or [aka.ms/installazurecliwindows](https://aka.ms/installazurecliwindows) |
| **GitHub CLI** (for GitHub) | `winget install GitHub.cli` or [cli.github.com](https://cli.github.com/) |
| **Claude Code** (for the slash command) | See [claude.ai/claude-code](https://claude.ai/download) |

You only need Azure CLI **or** GitHub CLI, depending on which platform you use.

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/MathiasAgain/Power_BI_Auto_Documentation.git
cd Power_BI_Auto_Documentation

python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Log in to your platform

```bash
# Azure DevOps:
az login

# GitHub:
gh auth login
```

A browser window opens — sign in and you're done. No tokens to create.

### 3. Run the tool

**Option A: Slash command (recommended)**

Open Claude Code in the project folder and type:

```
/generate-wiki
```

Claude walks you through everything interactively — file selection, platform, repo creation, wiki publishing, and pipeline setup.

**Option B: Streamlit app**

```bash
streamlit run app.py
```

A web UI opens with a step-by-step guided workflow.

**Option C: CLI (advanced)**

```bash
# Generate docs from a PBIP file and publish to Azure DevOps
python generate_wiki.py "C:\path\to\project.pbip" -o wiki-output --platform azure_devops -v

# Generate from PBIX and publish to GitHub
python generate_wiki.py "C:\path\to\model.pbix" -o wiki-output --platform github -v
```

Then push to your wiki:

```python
# Azure DevOps:
python -c "from src.utils.azure_wiki import push_to_azure_wiki; print(push_to_azure_wiki('wiki-output', 'https://dev.azure.com/org/project'))"

# GitHub:
python -c "from src.utils.git_wiki import push_to_wiki; print(push_to_wiki('wiki-output', 'https://github.com/org/repo'))"
```

## Supported Input Formats

| Format | Extension | Notes |
|---|---|---|
| **PBIP** (recommended) | `.pbip` | Parsed directly, no extra tools needed. Save from Power BI Desktop via *File > Save as > Power BI Project* |
| **Semantic Model** | `.SemanticModel/` | TMDL or model.bim folder — parsed directly |
| **PBIX** | `.pbix` | Binary format — requires the PBIXRay MCP server (included) |

## Supported Platforms

| Platform | Wiki | Auto-update pipeline | Auth |
|---|---|---|---|
| **Azure DevOps** | Auto-created | Azure Pipelines (auto-created) | `az login` (no token needed) |
| **GitHub** | Must initialize once manually | GitHub Actions | `gh auth login` (no token needed) |

## AI Descriptions (Optional)

The tool can generate plain-language descriptions for your DAX measures using Claude AI. This requires an API key from [console.anthropic.com](https://console.anthropic.com).

```bash
# Set the key as an environment variable:
export ANTHROPIC_API_KEY=sk-ant-...

# Then add --ai-descriptions when generating:
python generate_wiki.py "path/to/model.pbip" -o wiki-output --ai-descriptions
```

Or enable it interactively in the slash command or Streamlit app.

## Generated Wiki Structure

```
wiki-output/
├── Home.md              # Model overview + navigation
├── Table-{name}.md      # One page per table (columns, types, measures, diagram)
├── Measures.md          # All measures with formulas + dependency graph
├── Relationships.md     # Full ER diagram + relationship details
├── Data-Sources.md      # Power Query/M expressions
├── _Sidebar.md          # Wiki navigation (GitHub)
└── .order               # Page ordering (Azure DevOps)
```

## CLI Reference

| Flag | Description |
|---|---|
| `pbix_file` | Path to PBIX file, PBIP file, or SemanticModel folder |
| `-o, --output` | Output directory (default: `./wiki-output`) |
| `-n, --name` | Model display name (default: filename) |
| `--platform` | `github` or `azure_devops` (default: `github`) |
| `--ai-descriptions` | Enable AI measure descriptions |
| `--ai-model` | Claude model (default: `claude-sonnet-4-20250514`) |
| `-v, --verbose` | Show detailed logs |

## Troubleshooting

**"Repository not found" when pushing to GitHub Wiki**
> GitHub wikis must be initialized once manually. Go to the repo's Wiki tab and click "Create the first page" (content doesn't matter). This is a one-time GitHub limitation.

**"Azure login failed"**
> Make sure Azure CLI is installed: `az --version`. If not, run `winget install Microsoft.AzureCLI` and restart your terminal.

**"GitHub login failed"**
> Make sure GitHub CLI is installed: `gh --version`. If not, run `winget install GitHub.cli` and restart your terminal.

**Mermaid diagrams show as text**
> Make sure you're using `--platform azure_devops` when targeting Azure DevOps. The two platforms use different diagram syntax.

## Cost (AI Descriptions Only)

| Model | Cost per 200 measures | Notes |
|---|---|---|
| Claude Sonnet 4 | ~$0.89 | Recommended |
| Claude Haiku 3.5 | ~$0.10 | Faster, less detailed |

Descriptions are cached — subsequent runs only process new or changed measures.

## License

MIT
