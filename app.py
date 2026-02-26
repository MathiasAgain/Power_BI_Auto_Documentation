"""Streamlit web application for Power BI auto-documentation."""

import asyncio
import logging
import queue
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
):
    """Run wiki generation in a new thread with its own event loop."""
    handler = QueueLogHandler(log_queue)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        gen = WikiGenerator(
            output_dir=output_dir,
            server_command=server_command,
            enrich_with_ai=enrich_with_ai,
            anthropic_api_key=anthropic_api_key,
            ai_model=ai_model,
        )
        stats = loop.run_until_complete(gen.generate(input_path, model_name))
        result_container["stats"] = stats
    except Exception as e:
        result_container["error"] = e
    finally:
        loop.close()
        root.removeHandler(handler)


def run_generate_and_push(
    input_path: Path,
    repo_url: str,
    token: str | None,
    server_command: list[str],
    enrich_with_ai: bool,
    anthropic_api_key: str | None,
    ai_model: str,
    model_name: str | None,
    log_queue: queue.Queue,
    result_container: dict,
):
    """Generate docs into a temp dir, then push directly to GitHub Wiki."""
    handler = QueueLogHandler(log_queue)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    tmp_dir = Path(tempfile.mkdtemp(prefix="pbi-wiki-"))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Step 1: Generate into temp dir
        gen = WikiGenerator(
            output_dir=tmp_dir,
            server_command=server_command,
            enrich_with_ai=enrich_with_ai,
            anthropic_api_key=anthropic_api_key,
            ai_model=ai_model,
        )
        stats = loop.run_until_complete(gen.generate(input_path, model_name))
        result_container["stats"] = stats

        # Collect generated files for preview
        result_container["files"] = {
            f.name: f.read_text(encoding="utf-8")
            for f in sorted(tmp_dir.glob("*.md"))
        }

        # Step 2: Push to wiki
        logging.getLogger(__name__).info("Pushing to GitHub Wiki...")
        push_msg = push_to_wiki(
            source_dir=tmp_dir,
            repo_url=repo_url,
            token=token,
        )
        result_container["push_result"] = push_msg

    except Exception as e:
        result_container["error"] = e
    finally:
        loop.close()
        root.removeHandler(handler)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.title("Power BI Auto-Documentation")
st.caption("Generate GitHub Wiki documentation from Power BI files (PBIX or PBIP)")
st.divider()

settings: AppSettings = st.session_state.settings

# -- Sidebar: persistent settings ------------------------------------------
with st.sidebar:
    st.header("Settings")
    settings.server_command = st.text_input(
        "MCP Server Command (PBIX only)",
        value=settings.server_command,
        help="Only used for .pbix files. PBIP files are parsed directly.",
    )
    settings.ai_model = st.text_input(
        "Claude Model",
        value=settings.ai_model,
    )
    settings.save_secrets = st.checkbox(
        "Remember API keys between sessions",
        value=settings.save_secrets,
    )
    if st.button("Save Settings"):
        save_settings(settings)
        st.success("Saved!")

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
                "pbix": "PBIX (will use PBIXRay MCP server)",
                "pbip_bim": "PBIP — model.bim (JSON, parsed directly)",
                "pbip_tmdl": "PBIP — TMDL (parsed directly)",
            }
            st.success(f"Detected: **{type_labels.get(input_type, input_type)}**")
        else:
            st.warning("Could not detect Power BI format. Provide a .pbix, .pbip, or semantic model directory.")
    else:
        st.warning("Path not found")

# -- Step 2: GitHub repo ---------------------------------------------------
st.header("Step 2 — GitHub Wiki Target")

settings.github_repo_url = st.text_input(
    "GitHub Repository URL",
    value=settings.github_repo_url,
    placeholder="https://github.com/org/repo",
)
settings.github_token = st.text_input(
    "GitHub Personal Access Token (optional)",
    value=settings.github_token,
    type="password",
    help="Only needed if your git credential helper doesn't have access",
)

# Validate URL early
wiki_url_valid = False
if settings.github_repo_url:
    try:
        parse_wiki_git_url(settings.github_repo_url)
        wiki_url_valid = True
    except ValueError:
        st.warning("Invalid GitHub repo URL format. Expected: https://github.com/org/repo")

# -- Step 3: AI enrichment -------------------------------------------------
st.header("Step 3 — AI Enrichment (Optional)")

enable_ai = st.checkbox("Enable AI-generated measure descriptions")
if enable_ai:
    settings.anthropic_api_key = st.text_input(
        "Anthropic API Key",
        value=settings.anthropic_api_key,
        type="password",
    )
    if not settings.anthropic_api_key:
        st.warning("An API key is required for AI descriptions")

# -- Action buttons ---------------------------------------------------------
st.divider()

can_run = input_path is not None
has_wiki = wiki_url_valid and settings.github_repo_url

col_gen, col_push = st.columns(2)

with col_gen:
    generate_local = st.button(
        "Generate (local preview only)",
        disabled=not can_run,
        help="Generate wiki pages locally for preview without pushing",
    )

with col_push:
    generate_and_push = st.button(
        "Generate & Publish to Wiki",
        type="primary",
        disabled=not (can_run and has_wiki),
        help="Generate and push directly to your GitHub Wiki" if has_wiki else "Enter a valid GitHub repo URL first",
    )


def _run_with_ui(direct_push: bool):
    """Execute the generation (and optional push) with live log streaming."""
    settings.last_pbix_path = str(input_path)
    save_settings(settings)

    st.session_state.generation_complete = False
    st.session_state.generation_stats = None
    st.session_state.generated_files = {}
    st.session_state.push_result = None

    server_cmd = settings.server_command.split()
    log_queue: queue.Queue = queue.Queue()
    result_container: dict = {}

    if direct_push:
        target_fn = run_generate_and_push
        kwargs = dict(
            input_path=input_path,
            repo_url=settings.github_repo_url,
            token=settings.github_token or None,
            server_command=server_cmd,
            enrich_with_ai=enable_ai,
            anthropic_api_key=settings.anthropic_api_key if enable_ai else None,
            ai_model=settings.ai_model,
            model_name=model_name_input or None,
            log_queue=log_queue,
            result_container=result_container,
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

        if "error" in result_container:
            status.update(label="Failed!", state="error")
            st.error(str(result_container["error"]))
        else:
            st.session_state.generation_complete = True
            st.session_state.generation_stats = result_container.get("stats", {})

            if direct_push:
                st.session_state.generated_files = result_container.get("files", {})
                st.session_state.push_result = result_container.get("push_result", "")
                status.update(label="Published to GitHub Wiki!", state="complete")
            else:
                # Load files from temp dir
                st.session_state.generated_files = {
                    f.name: f.read_text(encoding="utf-8")
                    for f in sorted(tmp_out.glob("*.md"))
                }
                status.update(label="Generation complete!", state="complete")
                shutil.rmtree(tmp_out, ignore_errors=True)


if generate_local:
    _run_with_ui(direct_push=False)

if generate_and_push:
    _run_with_ui(direct_push=True)

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
        tab_raw, tab_rendered = st.tabs(["Raw Markdown", "Rendered"])
        with tab_raw:
            st.code(files[selected], language="markdown")
        with tab_rendered:
            st.markdown(files[selected], unsafe_allow_html=True)
