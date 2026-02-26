Generate GitHub Wiki documentation from a Power BI PBIX file.

Walk me through these steps interactively:

## Step 1: Locate the PBIX file

Ask me for the path to the PBIX file (or directory of PBIX files for multi-model mode).
Verify the file exists. If I provide a directory, list all .pbix files found recursively and confirm.

## Step 2: Configure output

Ask me:
- Output directory (suggest `./wiki-output` as default)
- Model display name (suggest the filename stem as default)
- If multiple PBIX files: organization name for the portal

## Step 3: GitHub Wiki target (optional)

Ask if I want to push to a GitHub Wiki. If yes, ask for:
- GitHub repository URL (e.g., https://github.com/org/repo)
- Whether I have a Personal Access Token or will rely on git credential helper

## Step 4: AI enrichment (optional)

Ask if I want AI-generated descriptions for DAX measures. If yes:
- Check if ANTHROPIC_API_KEY is set in the environment
- If not, ask me to provide it

## Step 5: Execute

Based on my answers, run the appropriate command:

For single model:
```bash
python generate_wiki.py "<pbix_path>" -o "<output_dir>" -n "<name>" -v
```

For multi-model:
```bash
python generate_wiki_multi.py "<input_dir>" -o "<output_dir>" --org-name "<org>" -v
```

Add `--ai-descriptions` if AI enrichment was requested.
If ANTHROPIC_API_KEY needs to be set, prefix with `export ANTHROPIC_API_KEY="<key>"`.

## Step 6: Review output

After generation:
1. List generated files in the output directory
2. Show me Home.md so I can verify
3. Report the statistics (tables, measures, relationships, pages)

## Step 7: Push to Wiki (if requested)

If I wanted to push to GitHub Wiki:
```bash
git clone <repo_url>.wiki.git .wiki-repo
rm -f .wiki-repo/*.md
cp <output_dir>/*.md .wiki-repo/
cd .wiki-repo && git add -A
git diff --staged --quiet || git commit -m "docs: update Power BI documentation"
git push
cd .. && rm -rf .wiki-repo
```

## Important notes

- The virtual environment should be activated before running
- The PBIXRay MCP server must be installed (`pip install -e ./pbixray-mcp-server`)
- Server command default: `python pbixray-mcp-server/src/pbixray_server.py`
