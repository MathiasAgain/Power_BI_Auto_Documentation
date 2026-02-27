"""Shared git subprocess helper with token sanitization and timeouts."""

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

# Matches tokens embedded in https URLs (e.g., https://TOKEN@github.com/...)
_TOKEN_IN_URL_RE = re.compile(r"(https?://)([^@]+)(@)")

GIT_TIMEOUT_SECONDS = 120

# Shared committer identity used across all wiki push operations
GIT_COMMITTER_NAME = "PBI Auto-Doc"
GIT_COMMITTER_EMAIL = "pbi-auto-doc@noreply.github.com"

# Default tool repository for CI/CD templates
TOOL_REPO = "MathiasAgain/Power_BI_Auto_Documentation"


def committer_env() -> dict[str, str]:
    """Return env vars for a consistent git committer identity."""
    return {
        "GIT_AUTHOR_NAME": GIT_COMMITTER_NAME,
        "GIT_AUTHOR_EMAIL": GIT_COMMITTER_EMAIL,
        "GIT_COMMITTER_NAME": GIT_COMMITTER_NAME,
        "GIT_COMMITTER_EMAIL": GIT_COMMITTER_EMAIL,
    }


def parse_github_url(repo_url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub URL.

    Supports https://github.com/org/repo, .git suffix, and git@ SSH format.
    Only HTTPS URLs are accepted (not HTTP) for security.
    """
    match = re.match(
        r"(?:https://github\.com/|git@github\.com:)"
        r"(?P<owner>[^/]+)/(?P<repo>[^/.]+)(?:\.git)?/?$",
        repo_url.strip(),
    )
    if not match:
        raise ValueError(
            f"Cannot parse GitHub repo URL: {repo_url}. "
            f"Expected: https://github.com/org/repo (HTTPS required)"
        )
    return match.group("owner"), match.group("repo")


def validate_repo_slug(repo: str) -> None:
    """Ensure a repo slug looks like 'owner/repo' and contains no injection."""
    if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo):
        raise ValueError(
            f"Invalid tool_repo format: {repo!r}. Expected 'owner/repo'."
        )


def run_git(
    cmd: list[str],
    cwd: str,
    env_override: dict[str, str] | None = None,
    secrets: list[str] | None = None,
    timeout: int = GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    """Run a git command, raising RuntimeError on failure.

    All error messages are sanitized to prevent token leakage:
    - Tokens embedded in URLs (https://TOKEN@host) are replaced with ***
    - Explicit secrets passed via the `secrets` parameter are scrubbed
    - Values from `env_override` are scrubbed
    """
    env = os.environ.copy()
    # Prevent git from ever prompting interactively (hangs in subprocess)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"  # Git Credential Manager
    env["GIT_ASKPASS"] = ""  # Prevent askpass programs from prompting
    if env_override:
        env.update(env_override)

    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, env=env, timeout=timeout,
    )
    if result.returncode != 0:
        stderr = _sanitize(result.stderr, env_override, secrets)
        safe_cmd = _sanitize(" ".join(cmd), env_override, secrets)
        raise RuntimeError(f"Git command failed: {safe_cmd}\n{stderr}")
    # Sanitize returned output so callers never see raw tokens
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=_sanitize(result.stdout, env_override, secrets),
        stderr=_sanitize(result.stderr, env_override, secrets),
    )


def _sanitize(
    text: str,
    env_override: dict[str, str] | None = None,
    secrets: list[str] | None = None,
) -> str:
    """Remove sensitive values from a string."""
    # Replace tokens embedded in URLs
    text = _TOKEN_IN_URL_RE.sub(r"\1***\3", text)

    # Scrub env_override values (e.g., author names aren't secrets, but be safe)
    if env_override:
        for val in env_override.values():
            if val:
                text = text.replace(val, "***")

    # Scrub explicit secrets
    if secrets:
        for secret in secrets:
            if secret:
                text = text.replace(secret, "***")

    return text
