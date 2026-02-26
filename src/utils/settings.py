"""Persistent settings for the Streamlit app."""

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parent.parent.parent / ".app_settings.json"


@dataclass
class AppSettings:
    """User settings persisted between sessions."""

    github_repo_url: str = ""
    github_token: str = ""
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-4-20250514"
    server_command: str = "python pbixray-mcp-server/src/pbixray_server.py"
    output_dir: str = "./wiki-output"
    last_pbix_path: str = ""
    organization_name: str = "Organization"
    save_secrets: bool = False


def load_settings(path: Path | None = None) -> AppSettings:
    """Load settings from JSON file. Returns defaults if file is missing."""
    settings_path = path or DEFAULT_SETTINGS_PATH
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            known = {f for f in AppSettings.__dataclass_fields__}
            filtered = {k: v for k, v in data.items() if k in known}
            return AppSettings(**filtered)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to load settings: {e}")
    return AppSettings()


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    """Save settings to JSON file. Strips secrets unless user opted in."""
    settings_path = path or DEFAULT_SETTINGS_PATH
    data = asdict(settings)
    if not settings.save_secrets:
        data.pop("anthropic_api_key", None)
        data.pop("github_token", None)
    settings_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
