"""Azure Pipelines YAML template for auto-deploying wiki generation."""

from .git_helpers import TOOL_REPO, validate_repo_slug

_PIPELINE_YAML = """\
# Azure Pipeline: Generate Power BI Wiki Documentation
#
# Automatically regenerates Azure DevOps Wiki documentation whenever
# Power BI project files (PBIP/TMDL/PBIX) are changed.
#
# IMPORTANT: Your project must have an initialized wiki before this
# pipeline can push to it. Go to Project > Wiki > "Create project wiki".
#
# Deployed by Power BI Auto-Documentation tool.
# Source: https://github.com/{tool_repo}

trigger:
  paths:
    include:
      - '**/*.pbix'
      - '**/*.pbip'
      - '**/*.SemanticModel/**'
      - '**/*.Dataset/**'
      - '**/definition/**/*.tmdl'
      - '**/model.bim'
      - 'azure-pipelines.yml'

pool:
  vmImage: 'ubuntu-latest'

variables:
  - name: ANTHROPIC_API_KEY
    value: $[variables.AnthropicApiKey]

steps:
  - checkout: self
    fetchDepth: 0

  - script: |
      git clone https://github.com/{tool_repo}.git _doc_tool
    displayName: 'Checkout documentation tool'

  - task: UsePythonVersion@0
    inputs:
      versionSpec: '3.11'
    displayName: 'Setup Python 3.11'

  - script: |
      pip install -r _doc_tool/requirements.txt
    displayName: 'Install dependencies'

  - script: |
      # Auto-detect: PBIP first, then SemanticModel, then PBIX
      pbip=$(find . -name "*.pbip" -not -path "./_doc_tool/*" -type f | head -1)
      if [ -n "$pbip" ]; then
        echo "##vso[task.setvariable variable=PBI_INPUT]$pbip"
        echo "Auto-detected PBIP: $pbip"
        exit 0
      fi

      sm_dir=$(find . -type d -name "*.SemanticModel" -not -path "./_doc_tool/*" | head -1)
      if [ -n "$sm_dir" ]; then
        echo "##vso[task.setvariable variable=PBI_INPUT]$sm_dir"
        echo "Auto-detected SemanticModel: $sm_dir"
        exit 0
      fi

      pbix=$(find . -name "*.pbix" -not -path "./_doc_tool/*" -type f | head -1)
      if [ -n "$pbix" ]; then
        echo "##vso[task.setvariable variable=PBI_INPUT]$pbix"
        echo "Auto-detected PBIX: $pbix"
        exit 0
      fi

      echo "##vso[task.logissue type=error]No Power BI files found in repository"
      exit 1
    displayName: 'Find Power BI files'

  - script: |
      python _doc_tool/generate_wiki.py \\
        "$(PBI_INPUT)" \\
        -o ./wiki-output \\
        -v
    displayName: 'Generate documentation'

  - script: |
      # Clone wiki, update content, push
      ORG_URL=$(echo "$(System.TeamFoundationCollectionUri)" | sed 's|/$||')
      WIKI_REPO="$ORG_URL/$(System.TeamProject)/_git/$(System.TeamProject).wiki"

      git -c http.extraHeader="Authorization: Bearer $(System.AccessToken)" clone "$WIKI_REPO" wiki_clone || {{
        echo "Wiki clone failed. Ensure the project wiki is initialized."
        exit 1
      }}

      rm -f wiki_clone/*.md wiki_clone/.order
      cp wiki-output/*.md wiki_clone/
      [ -f wiki-output/.order ] && cp wiki-output/.order wiki_clone/

      cd wiki_clone
      git config user.name "PBI Auto-Doc"
      git config user.email "pbi-auto-doc@noreply.github.com"
      git add -A
      git diff --staged --quiet || {{
        git commit -m "docs: update Power BI documentation from $(Build.SourceVersion)"
        git -c http.extraHeader="Authorization: Bearer $(System.AccessToken)" push
      }}
    displayName: 'Push to Azure DevOps Wiki'
"""


def render_pipeline(tool_repo: str | None = None) -> str:
    """Return the pipeline YAML with the tool repo substituted."""
    repo = tool_repo or TOOL_REPO
    validate_repo_slug(repo)
    return _PIPELINE_YAML.format(tool_repo=repo)
