"""GitHub Actions workflow template for auto-deploying wiki generation."""

from .git_helpers import TOOL_REPO, validate_repo_slug

_WORKFLOW_YAML = """\
name: Generate Power BI Wiki Documentation
#
# Automatically regenerates GitHub Wiki documentation whenever
# Power BI project files (PBIP/TMDL/PBIX) are changed.
#
# IMPORTANT: Your repo must have an initialized wiki (create at least one page
# via the GitHub web UI) before this workflow can push to it.
#
# Deployed by Power BI Auto-Documentation tool.
# Source: https://github.com/{tool_repo}

on:
  push:
    paths:
      - '**/*.pbix'
      - '**/*.pbip'
      - '**/*.SemanticModel/**'
      - '**/*.Dataset/**'
      - '**/definition/**/*.tmdl'
      - '**/model.bim'
      - '.github/workflows/generate-wiki.yml'
  workflow_dispatch:
    inputs:
      ai_descriptions:
        description: 'Generate AI descriptions for measures'
        required: false
        type: boolean
        default: false

jobs:
  generate-docs:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    env:
      ANTHROPIC_API_KEY: ${{{{ secrets.ANTHROPIC_API_KEY }}}}

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Checkout documentation tool
        uses: actions/checkout@v4
        with:
          repository: {tool_repo}
          path: _doc_tool

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
          cache-dependency-path: _doc_tool/requirements.txt

      - name: Install dependencies
        run: |
          pip install -r _doc_tool/requirements.txt

      - name: Find Power BI files
        id: find-input
        run: |
          pbip=$(find . -name "*.pbip" -not -path "./_doc_tool/*" -type f | head -1)
          if [ -n "$pbip" ]; then
            echo "path=$pbip" >> $GITHUB_OUTPUT
            echo "Auto-detected PBIP: $pbip"
            exit 0
          fi

          sm_dir=$(find . -type d -name "*.SemanticModel" -not -path "./_doc_tool/*" | head -1)
          if [ -n "$sm_dir" ]; then
            echo "path=$sm_dir" >> $GITHUB_OUTPUT
            echo "Auto-detected SemanticModel: $sm_dir"
            exit 0
          fi

          pbix=$(find . -name "*.pbix" -not -path "./_doc_tool/*" -type f | head -1)
          if [ -n "$pbix" ]; then
            echo "path=$pbix" >> $GITHUB_OUTPUT
            echo "Auto-detected PBIX: $pbix"
            exit 0
          fi

          echo "::error::No Power BI files found in repository"
          exit 1

      - name: Generate documentation
        run: |
          AI_FLAG=""
          if [ "${{{{ github.event.inputs.ai_descriptions }}}}" = "true" ]; then
            AI_FLAG="--ai-descriptions"
          fi

          python _doc_tool/generate_wiki.py \
            "${{{{ steps.find-input.outputs.path }}}}" \
            -o ./wiki-output \
            $AI_FLAG \
            -v

      - name: Checkout wiki
        uses: actions/checkout@v4
        with:
          repository: ${{{{ github.repository }}}}.wiki
          path: wiki
          token: ${{{{ secrets.GITHUB_TOKEN }}}}

      - name: Update wiki content
        run: |
          find wiki -maxdepth 1 -type f -name "*.md" -delete
          cp wiki-output/*.md wiki/

      - name: Commit and push wiki
        run: |
          cd wiki
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add -A
          git diff --staged --quiet || git commit -m "docs: update Power BI documentation from ${{{{ github.sha }}}}"
          git push
"""


def render_workflow(tool_repo: str | None = None) -> str:
    """Return the workflow YAML with the tool repo substituted."""
    repo = tool_repo or TOOL_REPO
    validate_repo_slug(repo)
    return _WORKFLOW_YAML.format(tool_repo=repo)
