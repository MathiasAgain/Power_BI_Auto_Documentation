# Power BI Auto-Documentation

## Project Overview

Automated documentation pipeline for Power BI. Extracts metadata from PBIX or PBIP files and generates GitHub Wiki pages with Mermaid ER diagrams, DAX measure references, and optional AI-generated descriptions.

## Architecture

Two input paths, same output:

```
PBIX File  → PBIXRay MCP Server (stdio) → ModelMetadata ─┐
                                                          ├→ Wiki Generator → GitHub Wiki
PBIP File  → Direct BIM/TMDL Parser     → ModelMetadata ─┘
```

### Layers

1. **Parsers** (`src/parsers/`) — PBIP/BIM/TMDL direct parsing (no MCP needed)
2. **MCP Client** (`src/mcp_client/`) — async JSON-RPC 2.0 over stdio (PBIX only)
3. **Generators** (`src/generators/`) — transforms metadata into wiki pages
4. **AI Enrichment** (`src/enrichment/`) — Claude API for business-friendly DAX descriptions
5. **Utilities** (`src/utils/`) — markdown helpers, settings persistence, git wiki push
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
    └── git_wiki.py              # GitHub Wiki clone/commit/push

app.py                           # Streamlit web UI
generate_wiki.py                 # CLI: single model
generate_wiki_multi.py           # CLI: multi-model portal
.claude/commands/generate-wiki.md  # Claude Code slash command
.github/workflows/generate-wiki.yml  # GitHub Actions
```

## How to Run

### Streamlit App (recommended)
```bash
./venv/Scripts/streamlit run app.py
```

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

### Claude Code
```
/generate-wiki
```

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

## Dependencies

- `mcp>=1.0.0,<2.0.0` — Anthropic MCP SDK
- `anthropic>=0.40.0` — Claude API client
- `pbixray>=0.3.0` — PBIX file parsing
- `streamlit>=1.30.0` — Web UI

## Settings

The Streamlit app persists settings to `.app_settings.json` (gitignored). API keys are only saved if the user opts in.

## Testing

```bash
# Verify imports
python -c "from src.generators.wiki_generator import WikiGenerator; print('OK')"

# Discover MCP tools
python generate_wiki.py --discover dummy.pbix
```
