# Power BI Auto-Documentation

Automatically generate GitHub Wiki documentation from Power BI PBIX files. Every table, measure, relationship, and data source is extracted and published as navigable Markdown pages with Mermaid ER diagrams.

## How It Works

```
PBIX File → PBIXRay MCP Server → Python Client → Markdown + Mermaid → GitHub Wiki
```

1. **MCP Client** connects to the PBIXRay MCP server and extracts all model metadata
2. **Wiki Generator** transforms metadata into structured Markdown pages
3. **GitHub Actions** automates the process on every commit

## Features

- Multi-page wiki: Home, per-table pages, Measures, Relationships, Data Sources
- Mermaid ER diagrams rendered natively in GitHub Wiki
- Measure dependency graphs (detects DAX cross-references)
- **AI enrichment** (optional): Claude generates business-friendly descriptions for DAX measures
- **Multi-model portal**: unified index, cross-model measure search, duplicate detection
- Persistent caching for AI descriptions (only regenerates when DAX changes)

## Prerequisites

- Python 3.10+
- [PBIXRay MCP Server](https://github.com/jonaolden/pbixray-mcp-server)
- (Optional) Anthropic API key for AI descriptions

## Installation

```bash
# Clone this repo
git clone https://github.com/your-org/powerbi-auto-documentation.git
cd powerbi-auto-documentation

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install the PBIXRay MCP server
git clone https://github.com/jonaolden/pbixray-mcp-server.git
pip install -e ./pbixray-mcp-server

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Single Model

```bash
python generate_wiki.py ./models/Sales.pbix -o ./wiki-output -n "Sales Analytics"
```

### Single Model with AI Descriptions

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python generate_wiki.py ./models/Sales.pbix -o ./wiki-output --ai-descriptions
```

### Multiple Models (Unified Portal)

```bash
python generate_wiki_multi.py ./models/ -o ./wiki-portal --org-name "Contoso"
```

### Discover Available MCP Tools

```bash
python generate_wiki.py --discover dummy.pbix
```

## CLI Options

### `generate_wiki.py` (single model)

| Flag | Description |
|------|-------------|
| `pbix_file` | Path to the PBIX file |
| `-o, --output` | Output directory (default: `./wiki-output`) |
| `-n, --name` | Model display name |
| `--server-command` | PBIXRay MCP server command |
| `--ai-descriptions` | Enable AI measure descriptions |
| `--ai-model` | Claude model (default: `claude-sonnet-4-20250514`) |
| `--cache-path` | AI description cache file path |
| `--discover` | List MCP tools and exit |
| `-v, --verbose` | Verbose logging |

### `generate_wiki_multi.py` (multi-model portal)

| Flag | Description |
|------|-------------|
| `input_dir` | Directory containing PBIX files (recursive) |
| `-o, --output` | Output directory (default: `./wiki-portal`) |
| `--org-name` | Organization name for portal header |
| `--server-command` | PBIXRay MCP server command |
| `--ai-descriptions` | Enable AI measure descriptions |
| `--ai-model` | Claude model |
| `-v, --verbose` | Verbose logging |

## Generated Wiki Structure

### Single Model

```
wiki-output/
├── Home.md              # Model overview + navigation
├── Table-{name}.md      # One page per table (columns, measures, diagram)
├── Measures.md          # All DAX measures with dependency graph
├── Relationships.md     # ER diagram + relationship details
├── Data-Sources.md      # Power Query/M expressions
└── _Sidebar.md          # Wiki navigation
```

### Multi-Model Portal

```
wiki-portal/
├── Home.md              # Portal index with all models
├── Measure-Index.md     # Cross-model measure search
├── Duplicate-Report.md  # Duplicate measure detection
├── _Sidebar.md          # Portal navigation
├── ModelA-Home.md       # Per-model pages (prefixed)
├── ModelA-Table-*.md
├── ModelA-Measures.md
└── ...
```

## GitHub Actions

The included workflow (`.github/workflows/generate-wiki.yml`) triggers on:

- Push of any `*.pbix` file
- Manual dispatch (workflow_dispatch)

### Setup

1. Ensure your repo has a wiki (create at least one page via the GitHub UI)
2. Add `ANTHROPIC_API_KEY` as a repository secret (only if using AI descriptions)
3. Place PBIX files in a `models/` directory (or adjust the workflow path)

### Secrets

| Secret | Required | Description |
|--------|----------|-------------|
| `ANTHROPIC_API_KEY` | Only for AI descriptions | Anthropic API key |

## Project Structure

```
├── src/
│   ├── models.py                  # Data models (Table, Measure, Relationship, etc.)
│   ├── mcp_client/
│   │   ├── client.py              # Base MCP protocol client
│   │   └── pbixray_tools.py       # PBIXRay-specific tool wrappers
│   ├── generators/
│   │   ├── wiki_generator.py      # Single-model wiki orchestrator
│   │   ├── multi_model.py         # Multi-model portal generator
│   │   ├── pages.py               # Individual page generators
│   │   └── mermaid.py             # Mermaid diagram generation
│   ├── enrichment/
│   │   └── ai_descriptions.py     # Claude AI description generator
│   └── utils/
│       └── markdown.py            # Markdown formatting helpers
├── generate_wiki.py               # CLI: single model
├── generate_wiki_multi.py         # CLI: multi-model portal
├── .github/workflows/
│   └── generate-wiki.yml          # GitHub Actions workflow
└── requirements.txt
```

## Cost Considerations (AI Descriptions)

| Model | Cost per 200 measures | Notes |
|-------|----------------------|-------|
| Claude Sonnet 4 | ~$0.89 | Recommended for cost efficiency |
| Claude Haiku 3.5 | ~$0.10 | Faster, less nuanced descriptions |

Persistent caching reduces costs by 80-90% on subsequent runs (only new/changed measures hit the API).

## License

MIT
