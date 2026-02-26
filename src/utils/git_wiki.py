"""GitHub Wiki git operations — clone, update, commit, push."""

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_wiki_git_url(repo_url: str, token: str | None = None) -> str:
    """Convert a GitHub repo URL to its wiki git URL.

    Supports https://github.com/org/repo, .git suffix, and git@ SSH format.
    Optionally embeds a PAT for authentication.
    """
    match = re.match(
        r"(?:https?://github\.com/|git@github\.com:)"
        r"(?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?/?$",
        repo_url.strip(),
    )
    if not match:
        raise ValueError(
            f"Cannot parse GitHub repo URL: {repo_url}. "
            f"Expected: https://github.com/org/repo"
        )
    owner, repo = match.group("owner"), match.group("repo")
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

    try:
        logger.info(f"Cloning wiki from {safe_url}...")
        _run_git(["git", "clone", wiki_url, str(wiki_dir)], cwd=str(clone_dir))

        # Remove existing markdown files
        for existing in wiki_dir.glob("*.md"):
            existing.unlink()

        # Copy new files
        for md_file in md_files:
            shutil.copy2(md_file, wiki_dir / md_file.name)

        logger.info(f"Copied {len(md_files)} pages to wiki repo")

        _run_git(["git", "add", "-A"], cwd=str(wiki_dir))

        # Check for changes
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            cwd=str(wiki_dir),
            capture_output=True,
        )
        if result.returncode == 0:
            msg = "No changes to push — wiki is already up to date."
            logger.info(msg)
            return msg

        _run_git(
            ["git", "commit", "-m", commit_message],
            cwd=str(wiki_dir),
            env_override={
                "GIT_AUTHOR_NAME": "PBI Auto-Doc",
                "GIT_AUTHOR_EMAIL": "pbi-auto-doc@noreply.github.com",
                "GIT_COMMITTER_NAME": "PBI Auto-Doc",
                "GIT_COMMITTER_EMAIL": "pbi-auto-doc@noreply.github.com",
            },
        )
        _run_git(["git", "push"], cwd=str(wiki_dir))

        msg = f"Successfully pushed {len(md_files)} pages to {safe_url}"
        logger.info(msg)
        return msg

    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)


def _run_git(
    cmd: list[str],
    cwd: str,
    env_override: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a git command, raising RuntimeError on failure."""
    env = os.environ.copy()
    if env_override:
        env.update(env_override)

    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        # Sanitize to avoid leaking tokens
        safe_cmd = " ".join(cmd[:3])
        stderr = result.stderr
        for val in env_override.values() if env_override else []:
            stderr = stderr.replace(val, "***")
        raise RuntimeError(f"Git command failed: {safe_cmd}...\n{stderr}")
    return result
