"""Streamlit web application for Power BI auto-documentation."""

import asyncio
import logging
import queue
import shlex
import shutil
import tempfile
import threading
import time
from pathlib import Path

import streamlit as st

from src.generators.wiki_generator import WikiGenerator
from src.parsers.pbip_parser import detect_input_type
from src.utils.settings import AppSettings, load_settings, save_settings
from src.utils.git_wiki import push_to_wiki, parse_wiki_git_url
from src.utils.azure_wiki import push_to_azure_wiki, parse_azure_devops_url
from src.utils.deploy_workflow import deploy_workflow
from src.utils.workflow_template import render_workflow
from src.utils.deploy_pipeline import deploy_azure_pipeline
from src.utils.azure_pipeline_template import render_pipeline
from src.utils.cli_auth import (
    check_az_cli_status, run_az_login,
    check_gh_cli_status, run_gh_login, get_gh_token,
)
from src.utils.repo_manager import (
    create_github_repo, create_azure_repo, create_azure_project,
    init_and_push, detect_git_status,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Power BI Auto-Documentation",
    page_icon=":bar_chart:",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "settings" not in st.session_state:
    st.session_state.settings = load_settings()
if "generation_complete" not in st.session_state:
    st.session_state.generation_complete = False
if "generation_stats" not in st.session_state:
    st.session_state.generation_stats = None
if "generated_files" not in st.session_state:
    st.session_state.generated_files = {}
if "push_result" not in st.session_state:
    st.session_state.push_result = None
if "deploy_result" not in st.session_state:
    st.session_state.deploy_result = None
if "az_user" not in st.session_state:
    st.session_state.az_user = None
if "az_checked" not in st.session_state:
    st.session_state.az_checked = False
if "gh_user" not in st.session_state:
    st.session_state.gh_user = None
if "gh_checked" not in st.session_state:
    st.session_state.gh_checked = False


# ---------------------------------------------------------------------------
# Auth helpers (thin wrappers around cli_auth for backward compatibility)
# ---------------------------------------------------------------------------
_check_az_cli_status = check_az_cli_status
_run_az_login = run_az_login
_check_gh_cli_status = check_gh_cli_status
_run_gh_login = run_gh_login
_get_gh_token = get_gh_token


# ---------------------------------------------------------------------------
# Logging bridge
# ---------------------------------------------------------------------------
class QueueLogHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            self.handleError(record)


# ---------------------------------------------------------------------------
# Generation runner (background thread)
# ---------------------------------------------------------------------------
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_GEN_LOGGER_NAME = "pbi_autodoc"


def _setup_thread_logging(log_queue: queue.Queue) -> tuple[logging.Logger, QueueLogHandler]:
    """Attach a queue handler to the generation logger. Returns (logger, handler)."""
    handler = QueueLogHandler(log_queue)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    gen_logger = logging.getLogger(_GEN_LOGGER_NAME)
    gen_logger.addHandler(handler)
    gen_logger.setLevel(logging.INFO)
    # Also attach to root so third-party loggers (git_helpers, etc.) are captured
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return root, handler


def _run_generation_core(
    input_path: Path,
    output_dir: Path,
    server_command: list[str],
    enrich_with_ai: bool,
    anthropic_api_key: str | None,
    ai_model: str,
    model_name: str | None,
    platform: str = "github",
) -> dict:
    """Core generation logic. Returns stats dict."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        gen = WikiGenerator(
            output_dir=output_dir,
            server_command=server_command,
            enrich_with_ai=enrich_with_ai,
            anthropic_api_key=anthropic_api_key,
            ai_model=ai_model,
            platform=platform,
        )
        return loop.run_until_complete(gen.generate(input_path, model_name))
    finally:
        loop.close()


def run_generation(
    input_path: Path,
    output_dir: Path,
    server_command: list[str],
    enrich_with_ai: bool,
    anthropic_api_key: str | None,
    ai_model: str,
    model_name: str | None,
    log_queue: queue.Queue,
    result_container: dict,
    platform: str = "github",
):
    """Run wiki generation in a new thread with its own event loop."""
    root, handler = _setup_thread_logging(log_queue)
    try:
        stats = _run_generation_core(
            input_path, output_dir, server_command,
            enrich_with_ai, anthropic_api_key, ai_model, model_name,
            platform=platform,
        )
        result_container["stats"] = stats
    except Exception as e:
        result_container["error"] = e
    finally:
        root.removeHandler(handler)


def run_generate_and_push(
    input_path: Path,
    repo_url: str,
    token: str | None,
    platform: str,
    server_command: list[str],
    enrich_with_ai: bool,
    anthropic_api_key: str | None,
    ai_model: str,
    model_name: str | None,
    log_queue: queue.Queue,
    result_container: dict,
    repo_mode: str = "existing",
    new_repo_name: str = "",
    new_repo_private: bool = True,
    devops_url: str = "",
    azure_project_mode: str = "existing",
    azure_org_url: str = "",
    new_project_name: str = "",
):
    """Generate docs into a temp dir, then push to wiki (GitHub or Azure DevOps).

    If repo_mode == "new", creates the repo and pushes the input folder first.
    If azure_project_mode == "new", creates the Azure DevOps project first.
    """
    root, handler = _setup_thread_logging(log_queue)
    gen_log = logging.getLogger(_GEN_LOGGER_NAME)
    tmp_dir = Path(tempfile.mkdtemp(prefix="pbi-wiki-"))
    try:
        # -- Step 0: Create Azure DevOps project if needed --
        if (platform == "azure_devops" and repo_mode == "new"
                and azure_project_mode == "new" and new_project_name):
            gen_log.info(f"Creating new Azure DevOps project: {new_project_name}...")
            import time as _time
            devops_url = create_azure_project(
                org_url=azure_org_url, name=new_project_name, token=token,
            )
            gen_log.info(f"Project created: {devops_url}")
            # Azure DevOps needs time for the project + default repo to be provisioned
            gen_log.info("Waiting for project to be fully provisioned...")
            from src.utils.repo_manager import _wait_for_azure_repo
            _wait_for_azure_repo(devops_url, new_repo_name, token, gen_log)

        # -- Step A: Create repo if needed --
        if repo_mode == "new" and new_repo_name:
            if platform == "github":
                gen_log.info(f"Creating new repository: {new_repo_name}...")
                repo_url = create_github_repo(
                    name=new_repo_name, private=new_repo_private, token=token,
                )
            elif azure_project_mode == "new" and new_repo_name == new_project_name:
                # Azure DevOps auto-creates a default repo with the project name
                from src.utils.azure_wiki import parse_azure_devops_url
                org, project = parse_azure_devops_url(devops_url)
                repo_url = f"https://dev.azure.com/{org}/{project}/_git/{new_repo_name}"
                gen_log.info(f"Using default project repository: {repo_url}")
            else:
                gen_log.info(f"Creating new repository: {new_repo_name}...")
                repo_url = create_azure_repo(
                    devops_url=devops_url, name=new_repo_name, token=token,
                )
            result_container["created_repo_url"] = repo_url
            gen_log.info(f"Repository ready: {repo_url}")

        # -- Step B: Git init + push source folder --
        input_folder = input_path.parent if input_path.is_file() else input_path
        git_status = detect_git_status(input_folder)
        if not git_status["has_commits"] or not git_status["remote_url"]:
            gen_log.info("Initializing git and pushing source files...")
            push_msg = init_and_push(
                folder=input_folder, repo_url=repo_url, token=token, platform=platform,
            )
            gen_log.info(push_msg)

        # -- Step C: Generate wiki docs --
        stats = _run_generation_core(
            input_path, tmp_dir, server_command,
            enrich_with_ai, anthropic_api_key, ai_model, model_name,
            platform=platform,
        )
        result_container["stats"] = stats

        # Collect generated files for preview
        result_container["files"] = {
            f.name: f.read_text(encoding="utf-8")
            for f in sorted(tmp_dir.glob("*.md"))
        }

        # -- Step D: Push wiki pages --
        if platform == "azure_devops":
            gen_log.info("Pushing to Azure DevOps Wiki...")
            wiki_push_msg = push_to_azure_wiki(
                source_dir=tmp_dir,
                devops_url=devops_url or repo_url,
                token=token,
            )
        else:
            gen_log.info("Pushing to GitHub Wiki...")
            wiki_push_msg = push_to_wiki(
                source_dir=tmp_dir,
                repo_url=repo_url,
                token=token,
            )
        result_container["push_result"] = wiki_push_msg

    except Exception as e:
        result_container["error"] = e
    finally:
        root.removeHandler(handler)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("Power BI Auto-Documentation")
st.caption("Generate wiki documentation from Power BI files — no git knowledge required")

# -- User guide (expandable) ------------------------------------------------
with st.expander("How to use this tool", expanded=False):
    st.markdown("""
### Getting Started

**1. Prepare your Power BI file**
> Create a new folder for your project and move your Power BI file into it:
> - **PBIX:** Move the `.pbix` file into the new folder.
> - **PBIP:** Move the `.pbip` file and its companion folders (`.SemanticModel/`, `.Report/`) into the new folder.
>
> Then enter the file path below. PBIP is recommended
> — save in Power BI Desktop via *File > Save as > Power BI Project (.pbip)*.

**2. Choose a platform and log in**
> Select **GitHub** or **Azure DevOps**, then click the **Login** button.
> A browser window opens — sign in and you're done. No tokens to create.

**3. Create or select a repository**
> Choose **Create a new repository** (the tool handles everything) or
> **Use an existing repository** if you already have one.

**4. Click "Create Repo & Publish Wiki"**
> The tool will: create the repo (if new), push your files, generate
> documentation, and publish it as a wiki. One click, done.
>
> **GitHub only:** After the repo is created, you need to initialize the wiki once
> (go to the Wiki tab and click "Create the first page"). This is a GitHub limitation.

**5. (Optional) Deploy a CI/CD pipeline**
> After publishing, deploy a GitHub Action or Azure Pipeline so the wiki
> auto-updates whenever you push changes to your Power BI files.
""")

st.divider()

settings: AppSettings = st.session_state.settings

# -- Sidebar: persistent settings ------------------------------------------
with st.sidebar:
    st.header("Settings")
    settings.save_secrets = st.checkbox(
        "Remember API keys between sessions",
        value=settings.save_secrets,
    )
    if st.button("Save Settings"):
        save_settings(settings)
        st.success("Saved!")

    with st.expander("Advanced"):
        settings.server_command = st.text_input(
            "PBIX server command",
            value=settings.server_command,
            help="Command to start the PBIXRay server. Only used for .pbix files.",
        )
        settings.ai_model = st.text_input(
            "AI model",
            value=settings.ai_model,
            help="The Claude model used for AI descriptions.",
        )

# -- Step 1: Select input file ---------------------------------------------
st.header("Step 1 — Select Power BI File")

file_input = st.text_input(
    "Path to PBIX file, PBIP file, or semantic model folder",
    value=settings.last_pbix_path,
    placeholder=r"C:\path\to\model.pbix  or  C:\path\to\project.pbip  or  C:\path\to\Model.SemanticModel",
)
model_name_input = st.text_input(
    "Model display name (optional)",
    placeholder="Defaults to filename",
)

input_path: Path | None = None
input_type = "unknown"

if file_input:
    p = Path(file_input)
    if p.exists():
        input_type = detect_input_type(p)
        if input_type != "unknown":
            input_path = p
            type_labels = {
                "pbix": "PBIX file (binary format)",
                "pbip_bim": "PBIP project (model.bim)",
                "pbip_tmdl": "PBIP project (TMDL)",
            }
            st.success(f"Detected: **{type_labels.get(input_type, input_type)}**")
        else:
            st.warning("Could not detect Power BI format. Provide a .pbix, .pbip, or semantic model directory.")
    else:
        st.warning("Path not found")

# -- Step 2: Wiki Target ---------------------------------------------------
st.header("Step 2 — Where to Publish")

platform_options = {"GitHub": "github", "Azure DevOps": "azure_devops"}
platform_label = st.radio(
    "Platform",
    list(platform_options.keys()),
    index=0 if settings.platform == "github" else 1,
    horizontal=True,
)
settings.platform = platform_options[platform_label]

wiki_url_valid = False

# -- Authentication (shared for both platforms) --
if settings.platform == "github":
    if not st.session_state.gh_checked:
        st.session_state.gh_user = _check_gh_cli_status()
        st.session_state.gh_checked = True

    st.markdown("**Authentication**")
    if st.session_state.gh_user:
        st.success(f"Logged in as **{st.session_state.gh_user}** (GitHub CLI)")
    else:
        st.warning("Not logged in — click below to sign in")

    col_login, col_refresh = st.columns([1, 1])
    with col_login:
        if st.button("Login to GitHub", help="Opens a browser window for GitHub authentication"):
            with st.spinner("Waiting for browser login..."):
                user = _run_gh_login()
            if user:
                st.session_state.gh_user = user
                st.rerun()
            else:
                st.error("GitHub login failed. Check that GitHub CLI (gh) is installed.")
    with col_refresh:
        if st.button("Refresh login status", key="gh_refresh"):
            st.session_state.gh_user = _check_gh_cli_status()
            st.rerun()

    with st.expander("Use a personal access token instead (advanced)"):
        settings.github_token = st.text_input(
            "GitHub Personal Access Token",
            value=settings.github_token,
            type="password",
            help="Only needed if the Login button above doesn't work for you.",
        )

else:  # azure_devops
    if not st.session_state.az_checked:
        st.session_state.az_user = _check_az_cli_status()
        st.session_state.az_checked = True

    st.markdown("**Authentication**")
    if st.session_state.az_user:
        st.success(f"Logged in as **{st.session_state.az_user}** (Azure CLI)")
    else:
        st.warning("Not logged in — click below to sign in")

    col_login, col_refresh = st.columns([1, 1])
    with col_login:
        if st.button("Login to Azure", help="Opens a browser window for Azure authentication"):
            with st.spinner("Waiting for browser login..."):
                user = _run_az_login()
            if user:
                st.session_state.az_user = user
                st.rerun()
            else:
                st.error("Azure login failed. Check that Azure CLI is installed.")
    with col_refresh:
        if st.button("Refresh login status"):
            st.session_state.az_user = _check_az_cli_status()
            st.rerun()

    with st.expander("Use a personal access token instead (advanced)"):
        settings.azure_devops_token = st.text_input(
            "Azure DevOps Personal Access Token",
            value=settings.azure_devops_token,
            type="password",
            help="Only needed if the Login button above doesn't work for you.",
        )

# -- Repository --
st.markdown("**Repository**")
repo_mode_options = {"Create a new repository": "new", "Use an existing repository": "existing"}
repo_mode_label = st.radio(
    "Repository",
    list(repo_mode_options.keys()),
    index=0 if settings.repo_mode == "new" else 1,
    horizontal=True,
    label_visibility="collapsed",
)
settings.repo_mode = repo_mode_options[repo_mode_label]

if settings.repo_mode == "new":
    settings.new_repo_name = st.text_input(
        "New repository name",
        value=settings.new_repo_name,
        placeholder="my-powerbi-project",
    )
    settings.new_repo_private = st.checkbox("Private repository", value=settings.new_repo_private)
    if settings.platform == "azure_devops":
        project_mode_opts = {
            "Use an existing project": "existing",
            "Create a new project": "new",
        }
        project_mode_label = st.radio(
            "Azure DevOps Project",
            list(project_mode_opts.keys()),
            index=0 if settings.azure_project_mode == "existing" else 1,
            horizontal=True,
        )
        settings.azure_project_mode = project_mode_opts[project_mode_label]

        if settings.azure_project_mode == "new":
            settings.azure_devops_org_url = st.text_input(
                "Azure DevOps Organization URL",
                value=settings.azure_devops_org_url,
                placeholder="https://dev.azure.com/your-org",
                help="The organization where the new project will be created",
            )
            settings.new_project_name = st.text_input(
                "New project name",
                value=settings.new_project_name,
                placeholder="MyPowerBIProject",
            )
            # Construct the full project URL for downstream use
            if settings.azure_devops_org_url and settings.new_project_name:
                org_base = settings.azure_devops_org_url.rstrip("/")
                settings.azure_devops_url = f"{org_base}/{settings.new_project_name}"
        else:
            settings.azure_devops_url = st.text_input(
                "Azure DevOps Project URL",
                value=settings.azure_devops_url,
                placeholder="https://dev.azure.com/org/project",
                help="The project where the new repo will be created",
            )
    # Validate
    if settings.new_repo_name:
        wiki_url_valid = True
        if settings.platform == "azure_devops":
            if settings.azure_project_mode == "new":
                if not settings.azure_devops_org_url or not settings.new_project_name:
                    wiki_url_valid = False
                    st.warning("Enter the organization URL and a project name")
                else:
                    from src.utils.repo_manager import parse_azure_org_url
                    try:
                        parse_azure_org_url(settings.azure_devops_org_url)
                    except ValueError:
                        wiki_url_valid = False
                        st.warning(
                            "Invalid organization URL. Expected: "
                            "`https://dev.azure.com/your-org`"
                        )
            else:
                if not settings.azure_devops_url:
                    wiki_url_valid = False
                    st.warning("Enter an Azure DevOps project URL")
                else:
                    try:
                        parse_azure_devops_url(settings.azure_devops_url)
                    except ValueError:
                        wiki_url_valid = False
                        st.warning(
                            "Invalid Azure DevOps URL. Include the project name: "
                            "`https://dev.azure.com/org/project`"
                        )

else:  # existing repo
    if settings.platform == "github":
        settings.github_repo_url = st.text_input(
            "GitHub Repository URL",
            value=settings.github_repo_url,
            placeholder="https://github.com/org/repo",
        )
        if settings.github_repo_url:
            try:
                parse_wiki_git_url(settings.github_repo_url)
                wiki_url_valid = True
            except ValueError:
                st.warning("Invalid GitHub repo URL format. Expected: https://github.com/org/repo")

    else:  # azure_devops
        settings.azure_devops_url = st.text_input(
            "Azure DevOps Project URL",
            value=settings.azure_devops_url,
            placeholder="https://dev.azure.com/org/project",
        )
        settings.azure_devops_repo_name = st.text_input(
            "Repository name (optional)",
            value=settings.azure_devops_repo_name,
            placeholder="Defaults to project name",
            help="Only needed if your repo name differs from the project name",
        )
        if settings.azure_devops_url:
            try:
                parse_azure_devops_url(settings.azure_devops_url)
                wiki_url_valid = True
            except ValueError:
                st.warning("Invalid Azure DevOps URL format. Expected: https://dev.azure.com/org/project")

# GitHub wiki init reminder
if settings.platform == "github" and settings.repo_mode == "new" and settings.new_repo_name:
    st.info(
        "After the repository is created, you'll need to initialize the wiki once: "
        "go to the repo's **Wiki** tab and click **Create the first page** (content doesn't matter). "
        "This is a one-time GitHub limitation."
    )

# -- Step 3: AI enrichment -------------------------------------------------
st.header("Step 3 — AI Descriptions (Optional)")
st.caption("Add plain-language descriptions to your DAX measures using Claude AI")

enable_ai = st.checkbox("Enable AI-generated descriptions")
if enable_ai:
    settings.anthropic_api_key = st.text_input(
        "API Key (Claude AI)",
        value=settings.anthropic_api_key,
        type="password",
        help="Get a key at console.anthropic.com — used to generate business-friendly descriptions for your measures.",
    )
    if not settings.anthropic_api_key:
        st.warning("An API key is required for AI descriptions")

# -- Action buttons ---------------------------------------------------------
st.divider()

can_run = input_path is not None
active_repo_url = ""
active_token = None
has_wiki = False
has_auth = False

# Resolve auth and repo URL for both modes
if settings.platform == "github":
    active_token = settings.github_token or _get_gh_token()
    has_auth = bool(active_token) or bool(st.session_state.gh_user)
    if settings.repo_mode == "new":
        has_wiki = wiki_url_valid and bool(settings.new_repo_name)
        active_repo_url = settings.github_repo_url or ""  # set after creation
    else:
        has_wiki = wiki_url_valid and bool(settings.github_repo_url)
        active_repo_url = settings.github_repo_url
else:
    active_token = settings.azure_devops_token or None
    has_auth = bool(active_token) or bool(st.session_state.az_user)
    if settings.repo_mode == "new":
        has_wiki = wiki_url_valid and bool(settings.new_repo_name) and bool(settings.azure_devops_url)
        active_repo_url = settings.azure_devops_url
    else:
        has_wiki = wiki_url_valid and bool(settings.azure_devops_url)
        active_repo_url = settings.azure_devops_url

col_gen, col_push = st.columns(2)

with col_gen:
    generate_local = st.button(
        "Generate (local preview only)",
        disabled=not can_run,
        help="Generate wiki pages locally for preview without pushing",
    )

with col_push:
    if settings.repo_mode == "new":
        _creating_project = (
            settings.platform == "azure_devops"
            and settings.azure_project_mode == "new"
        )
        push_label = (
            "Create Project, Repo & Publish Wiki" if _creating_project
            else "Create Repo & Publish Wiki"
        )
        push_help = (
            f"Create a new {'project + ' if _creating_project else ''}repo, push your files, generate docs, and publish to "
            f"{'GitHub' if settings.platform == 'github' else 'Azure DevOps'} Wiki"
            if has_wiki
            else "Fill in the required fields above"
        )
    else:
        push_label = "Generate & Publish to Wiki"
        push_help = (
            f"Generate and push directly to your {'GitHub' if settings.platform == 'github' else 'Azure DevOps'} Wiki"
            if has_wiki
            else "Enter a valid repo URL first"
        )
    generate_and_push = st.button(
        push_label,
        type="primary",
        disabled=not (can_run and has_wiki),
        help=push_help,
    )


def _run_with_ui(direct_push: bool, _repo_url: str = "", _token: str | None = None):
    """Execute the generation (and optional push) with live log streaming."""
    settings.last_pbix_path = str(input_path)
    save_settings(settings)

    st.session_state.generation_complete = False
    st.session_state.generation_stats = None
    st.session_state.generated_files = {}
    st.session_state.push_result = None
    st.session_state.deploy_result = None

    server_cmd = shlex.split(settings.server_command) if settings.server_command.strip() else []
    log_queue: queue.Queue = queue.Queue()
    result_container: dict = {}

    if direct_push:
        target_fn = run_generate_and_push
        kwargs = dict(
            input_path=input_path,
            repo_url=_repo_url,
            token=_token,
            platform=settings.platform,
            server_command=server_cmd,
            enrich_with_ai=enable_ai,
            anthropic_api_key=settings.anthropic_api_key if enable_ai else None,
            ai_model=settings.ai_model,
            model_name=model_name_input or None,
            log_queue=log_queue,
            result_container=result_container,
            repo_mode=settings.repo_mode,
            new_repo_name=settings.new_repo_name,
            new_repo_private=settings.new_repo_private,
            devops_url=settings.azure_devops_url,
            azure_project_mode=settings.azure_project_mode,
            azure_org_url=settings.azure_devops_org_url,
            new_project_name=settings.new_project_name,
        )
        status_label = "Generating & publishing..."
    else:
        target_fn = run_generation
        tmp_out = Path(tempfile.mkdtemp(prefix="pbi-preview-"))
        kwargs = dict(
            input_path=input_path,
            output_dir=tmp_out,
            server_command=server_cmd,
            enrich_with_ai=enable_ai,
            anthropic_api_key=settings.anthropic_api_key if enable_ai else None,
            ai_model=settings.ai_model,
            model_name=model_name_input or None,
            log_queue=log_queue,
            result_container=result_container,
            platform=settings.platform,
        )
        status_label = "Generating documentation..."

    with st.status(status_label, expanded=True) as status:
        log_area = st.empty()
        log_lines: list[str] = []

        thread = threading.Thread(target=target_fn, kwargs=kwargs, daemon=True)
        thread.start()

        while thread.is_alive():
            while not log_queue.empty():
                log_lines.append(log_queue.get_nowait())
                log_area.code("\n".join(log_lines[-60:]))
            time.sleep(0.1)

        while not log_queue.empty():
            log_lines.append(log_queue.get_nowait())
        if log_lines:
            log_area.code("\n".join(log_lines[-60:]))

        thread.join()

        try:
            if "error" in result_container:
                status.update(label="Failed!", state="error")
                st.error(str(result_container["error"]))
            else:
                st.session_state.generation_complete = True
                st.session_state.generation_stats = result_container.get("stats", {})

                if direct_push:
                    st.session_state.generated_files = result_container.get("files", {})
                    st.session_state.push_result = result_container.get("push_result", "")
                    # If a new repo was created, save its URL for deploy step
                    created_url = result_container.get("created_repo_url")
                    if created_url:
                        if settings.platform == "github":
                            settings.github_repo_url = created_url
                        settings.save_secrets = False
                        save_settings(settings)
                    wiki_label = "GitHub" if settings.platform == "github" else "Azure DevOps"
                    status.update(label=f"Published to {wiki_label} Wiki!", state="complete")
                else:
                    # Load files from temp dir
                    st.session_state.generated_files = {
                        f.name: f.read_text(encoding="utf-8")
                        for f in sorted(tmp_out.glob("*.md"))
                    }
                    status.update(label="Generation complete!", state="complete")
        finally:
            if not direct_push:
                shutil.rmtree(tmp_out, ignore_errors=True)


if generate_local:
    _run_with_ui(direct_push=False)

if generate_and_push:
    _run_with_ui(direct_push=True, _repo_url=active_repo_url, _token=active_token)

# -- Results ----------------------------------------------------------------
if st.session_state.push_result:
    st.success(st.session_state.push_result)

if st.session_state.generation_complete and st.session_state.generated_files:
    st.divider()
    st.header("Results")

    stats = st.session_state.generation_stats
    if stats:
        cols = st.columns(len(stats))
        for col, (key, val) in zip(cols, stats.items()):
            col.metric(key.replace("_", " ").title(), val)

    files = st.session_state.generated_files
    selected = st.selectbox("Preview page", list(files.keys()))
    if selected:
        tab_raw, tab_rendered = st.tabs(["Source", "Rendered"])
        with tab_raw:
            st.code(files[selected], language="markdown")
        with tab_rendered:
            st.markdown(files[selected], unsafe_allow_html=False)

# -- Deploy CI/CD pipeline --------------------------------------------------
if st.session_state.push_result and has_wiki and has_auth:
    st.divider()

    if settings.platform == "github":
        st.header("Step 4 — Auto-Update Pipeline (Optional)")
        st.markdown(
            "Set up automatic updates so your wiki stays in sync "
            "whenever you push changes to your Power BI files."
        )
        with st.expander("Preview pipeline configuration"):
            st.code(render_workflow(), language="yaml")

        if active_token:
            deploy_btn = st.button(
                "Deploy Auto-Update Pipeline",
                help="Adds an automation file to your repository",
            )
            if deploy_btn:
                with st.spinner("Deploying auto-update pipeline..."):
                    try:
                        result_msg = deploy_workflow(
                            repo_url=settings.github_repo_url,
                            token=active_token,
                        )
                        st.session_state.deploy_result = result_msg
                    except (ValueError, RuntimeError) as e:
                        st.session_state.deploy_result = None
                        st.error(f"Failed to deploy: {e}")
        else:
            st.info(
                "To deploy automatically, log in with GitHub CLI or enter a token in Step 2. "
                "You can also copy the configuration above and add it to your repo manually."
            )

    else:  # azure_devops
        st.header("Step 4 — Auto-Update Pipeline (Optional)")
        st.markdown(
            "Set up automatic updates so your wiki stays in sync "
            "whenever you push changes to your Power BI files."
        )
        with st.expander("Preview pipeline configuration"):
            st.code(render_pipeline(), language="yaml")

        if has_auth:
            deploy_btn = st.button(
                "Deploy Auto-Update Pipeline",
                help="Adds an automation file to your repository",
            )
            if deploy_btn:
                with st.spinner("Deploying auto-update pipeline..."):
                    try:
                        # Use new_repo_name when in "new repo" mode, else the optional repo name field
                        effective_repo_name = (
                            settings.new_repo_name
                            if settings.repo_mode == "new" and settings.new_repo_name
                            else settings.azure_devops_repo_name or None
                        )
                        result_msg = deploy_azure_pipeline(
                            devops_url=settings.azure_devops_url,
                            token=settings.azure_devops_token or None,
                            repo_name=effective_repo_name,
                        )
                        st.session_state.deploy_result = result_msg
                    except (ValueError, RuntimeError) as e:
                        st.session_state.deploy_result = None
                        st.error(f"Failed to deploy: {e}")
        else:
            st.info(
                "To deploy automatically, log in with Azure CLI or enter a token in Step 2. "
                "You can also copy the configuration above and add it to your repo manually."
            )

    if st.session_state.deploy_result:
        st.success(st.session_state.deploy_result)
        if settings.platform == "github":
            st.info(
                "**Tip:** To enable AI descriptions in automatic updates, "
                "add `ANTHROPIC_API_KEY` as a repository secret "
                "(Settings > Secrets and variables > Actions)."
            )
        else:
            deploy_msg = st.session_state.deploy_result or ""
            if "created automatically" in deploy_msg or "already exists" in deploy_msg:
                st.info(
                    "**Tip:** To enable AI descriptions in automatic updates, "
                    "add `AnthropicApiKey` as a pipeline variable in Azure DevOps."
                )
            else:
                st.info(
                    "**Next steps:** \n"
                    "1. Go to **Pipelines** in Azure DevOps and create a pipeline from the configuration file.\n"
                    "2. To enable AI descriptions, add `AnthropicApiKey` as a pipeline variable."
                )

elif st.session_state.push_result and has_wiki and not has_auth:
    st.divider()
    st.info(
        "**Tip:** To set up automatic wiki updates, "
        "log in or enter a token in Step 2 above."
    )

# -- Feature summary (shown after successful push) --------------------------
if st.session_state.push_result and st.session_state.generation_complete:
    st.divider()
    st.header("What was generated")

    stats = st.session_state.generation_stats or {}
    files = st.session_state.generated_files or {}

    wiki_platform = "GitHub" if settings.platform == "github" else "Azure DevOps"
    pipeline_deployed = bool(st.session_state.deploy_result)

    features = []
    features.append(f"**Wiki published** to {wiki_platform} with {len(files)} pages")

    if stats.get("Tables"):
        features.append(f"**{stats['Tables']} tables** documented with columns, data types, and relationships")
    if stats.get("Measures"):
        features.append(f"**{stats['Measures']} measures** listed with their formulas")
    if stats.get("Relationships"):
        features.append(f"**{stats['Relationships']} relationships** mapped in an interactive diagram")

    pq_count = stats.get("Power Query") or stats.get("Power_Query")
    if pq_count:
        features.append(f"**{pq_count} data source expressions** documented")

    features.append("**Sidebar navigation** with organized page ordering")

    if pipeline_deployed:
        features.append("**Auto-update pipeline** deployed — wiki stays in sync on every push")
    features.append("**Your credentials are not stored** in the wiki or repository")

    for feat in features:
        st.markdown(f"- {feat}")
