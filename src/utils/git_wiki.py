"""GitHub Wiki git operations — clone, update, commit, push."""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from .git_helpers import run_git, parse_github_url, committer_env

logger = logging.getLogger(__name__)


def parse_wiki_git_url(repo_url: str, token: str | None = None) -> str:
    """Convert a GitHub repo URL to its wiki git URL.

    Supports https://github.com/org/repo, .git suffix, and git@ SSH format.
    Optionally embeds a PAT for authentication.
    """
    owner, repo = parse_github_url(repo_url)
    if token:
        return f"https://{token}@github.com/{owner}/{repo}.wiki.git"
    return f"https://github.com/{owner}/{repo}.wiki.git"


def push_to_wiki(
    source_dir: str | Path,
    repo_url: str,
    token: str | None = None,
    commit_message: str = "docs: update Power BI documentation",
) -> str:
    """Clone the wiki repo, copy markdown files, commit, and push.

    Args:
        source_dir: Directory containing generated .md files.
        repo_url: GitHub repository URL (not the wiki URL).
        token: Optional GitHub PAT for authentication.
        commit_message: Git commit message.

    Returns:
        Result message string.
    """
    source_dir = Path(source_dir)
    wiki_url = parse_wiki_git_url(repo_url, token)
    safe_url = parse_wiki_git_url(repo_url, None)

    md_files = list(source_dir.glob("*.md"))
    if not md_files:
        raise RuntimeError(f"No .md files found in {source_dir}")

    clone_dir = Path(tempfile.mkdtemp(prefix="wiki-push-"))
    wiki_dir = clone_dir / "wiki"

    # Collect secrets to sanitize from any error messages
    secrets = [token] if token else []

    try:
        logger.info(f"Cloning wiki from {safe_url}...")
        run_git(
            ["git", "clone", wiki_url, str(wiki_dir)],
            cwd=str(clone_dir),
            secrets=secrets,
        )

        # Remove existing markdown files
        for existing in wiki_dir.glob("*.md"):
            existing.unlink()

        # Copy new files
        for md_file in md_files:
            shutil.copy2(md_file, wiki_dir / md_file.name)

        logger.info(f"Copied {len(md_files)} pages to wiki repo")

        run_git(["git", "add", "-A"], cwd=str(wiki_dir), secrets=secrets)

        # Check for changes
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            cwd=str(wiki_dir),
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            msg = "No changes to push — wiki is already up to date."
            logger.info(msg)
            return msg

        run_git(
            ["git", "commit", "-m", commit_message],
            cwd=str(wiki_dir),
            env_override=committer_env(),
            secrets=secrets,
        )
        run_git(["git", "push"], cwd=str(wiki_dir), secrets=secrets)

        msg = f"Successfully pushed {len(md_files)} pages to {safe_url}"
        logger.info(msg)
        return msg

    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)
