"""Individual wiki page generators for Power BI model documentation."""

from datetime import datetime, timezone

from ..models import Table, Measure, Relationship, ModelMetadata
from ..utils.markdown import MarkdownHelper as md
from .mermaid import generate_er_diagram, generate_table_diagram, generate_measure_dependency_graph


def slugify(text: str) -> str:
    """Convert text to a URL-safe wiki page slug."""
    return text.lower().replace(" ", "-").replace("_", "-").replace("/", "-").replace("\\", "-")


def generate_home_page(metadata: ModelMetadata, page_prefix: str = "") -> str:
    """Generate the wiki Home page with model overview and navigation."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    p = page_prefix

    table_count = len(metadata.tables)
    measure_count = len(metadata.measures)
    rel_count = len(metadata.relationships)

    # Navigation links to individual table pages
    table_links = "\n".join(
        f"- [[{t.name}|{p}Table-{slugify(t.name)}]]"
        for t in sorted(metadata.tables, key=lambda t: t.name)
    )

    # Summary table
    summary_rows = [
        ["Tables", str(table_count)],
        ["Measures", str(measure_count)],
        ["Relationships", str(rel_count)],
    ]
    if metadata.size_bytes:
        size_mb = metadata.size_bytes / (1024 * 1024)
        summary_rows.append(["Model Size", f"{size_mb:.1f} MB"])

    summary_table = md.table(["Metric", "Value"], summary_rows)

    return f"""# {metadata.name} - Semantic Model Documentation

> Auto-generated on {timestamp}

## Model Overview

{summary_table}

## Quick Navigation

### Tables

{table_links}

### Other Pages

- [[All Measures|{p}Measures]]
- [[Relationships|{p}Relationships]]
- [[Data Sources|{p}Data-Sources]]

---

_This documentation is automatically generated from the PBIX file.
Do not edit manually — changes will be overwritten on next generation._
"""


def generate_table_page(
    table: Table,
    measures: list[Measure],
    relationships: list[Relationship],
    page_prefix: str = "",
) -> str:
    """Generate a documentation page for a single table."""
    p = page_prefix

    # Column listing
    col_headers = ["Column", "Data Type", "Description"]
    col_rows = [
        [
            col.name,
            col.data_type,
            col.description or "",
        ]
        for col in table.columns
    ]
    columns_table = md.table(col_headers, col_rows) if col_rows else "_No columns found._"

    # Measures belonging to this table
    table_measures = [m for m in measures if m.table == table.name]
    measures_section = ""
    if table_measures:
        measures_section = "\n## Measures\n\n"
        for m in table_measures:
            measures_section += f"### {m.name}\n\n"
            if m.description:
                measures_section += f"_{m.description}_\n\n"
            measures_section += md.code_block(m.expression, "dax") + "\n\n"
            if m.format_string:
                measures_section += f"**Format:** `{m.format_string}`\n\n"

    # Focused relationship diagram for this table
    table_diagram = generate_table_diagram(table.name, relationships)
    diagram_section = ""
    if table_diagram:
        diagram_section = f"\n## Relationships\n\n{md.code_block(table_diagram, 'mermaid')}\n"

    description = f"\n_{table.description}_\n" if table.description else ""

    row_info = ""
    if table.row_count is not None:
        row_info = f"\n**Row count:** {table.row_count:,}\n"

    return f"""# {table.name}
{description}{row_info}
## Columns

{columns_table}
{measures_section}{diagram_section}

---

[[← Back to Home|{p}Home]]
"""


def generate_measures_page(measures: list[Measure], page_prefix: str = "") -> str:
    """Generate consolidated DAX measures reference page."""
    p = page_prefix

    # Group by table
    by_table: dict[str, list[Measure]] = {}
    for m in measures:
        by_table.setdefault(m.table, []).append(m)

    content = "# DAX Measures Reference\n\n"
    content += f"**Total measures:** {len(measures)}\n\n"

    # Table of contents
    content += "## Contents\n\n"
    for table_name in sorted(by_table.keys()):
        anchor = table_name.lower().replace(" ", "-")
        content += f"- [{table_name}](#{anchor}) ({len(by_table[table_name])} measures)\n"
    content += "\n---\n\n"

    # Measure details grouped by table
    for table_name in sorted(by_table.keys()):
        content += f"## {table_name}\n\n"
        for m in sorted(by_table[table_name], key=lambda x: x.name):
            content += f"### {m.name}\n\n"
            if m.description:
                content += f"_{m.description}_\n\n"
            content += md.code_block(m.expression, "dax") + "\n\n"
            if m.format_string:
                content += f"**Format:** `{m.format_string}`\n\n"

    # Measure dependency graph
    dep_graph = generate_measure_dependency_graph(measures)
    if dep_graph:
        content += "---\n\n## Measure Dependencies\n\n"
        content += md.code_block(dep_graph, "mermaid") + "\n"

    content += f"\n---\n\n[[← Back to Home|{p}Home]]\n"
    return content


def generate_relationships_page(
    relationships: list[Relationship],
    tables: list[Table],
    page_prefix: str = "",
) -> str:
    """Generate relationships page with ER diagram and detail table."""
    p = page_prefix

    er_diagram = generate_er_diagram(relationships, tables)

    content = "# Model Relationships\n\n"
    content += "## Entity Relationship Diagram\n\n"
    content += md.code_block(er_diagram, "mermaid") + "\n\n"

    # Detail table
    content += "## Relationship Details\n\n"
    headers = ["From Table", "From Column", "To Table", "To Column", "Active", "Direction"]
    rows = [
        [
            r.from_table,
            r.from_column,
            r.to_table,
            r.to_column,
            "Yes" if r.is_active else "No",
            r.cross_filter_direction,
        ]
        for r in relationships
    ]
    content += md.table(headers, rows) + "\n\n"

    # Statistics
    active_count = sum(1 for r in relationships if r.is_active)
    inactive_count = len(relationships) - active_count
    content += "## Statistics\n\n"
    content += f"- **Total relationships:** {len(relationships)}\n"
    content += f"- **Active:** {active_count}\n"
    content += f"- **Inactive:** {inactive_count}\n"

    content += f"\n---\n\n[[← Back to Home|{p}Home]]\n"
    return content


def generate_data_sources_page(power_query: dict[str, str], page_prefix: str = "") -> str:
    """Generate data sources page from Power Query/M code."""
    p = page_prefix

    content = "# Data Sources\n\n"
    content += "This page documents the Power Query/M expressions used to load data.\n\n"

    if not power_query:
        content += "_No Power Query expressions found._\n"
    else:
        for query_name in sorted(power_query.keys()):
            query_code = power_query[query_name]
            content += f"## {query_name}\n\n"
            content += md.code_block(query_code, "powerquery") + "\n\n"

    content += f"\n---\n\n[[← Back to Home|{p}Home]]\n"
    return content


def generate_sidebar(metadata: ModelMetadata, page_prefix: str = "") -> str:
    """Generate GitHub Wiki _Sidebar.md navigation.

    Args:
        metadata: Model metadata.
        page_prefix: Optional prefix for multi-model wikis (e.g. 'SalesModel-').
    """
    p = page_prefix

    sidebar = "**Navigation**\n\n"
    sidebar += f"- [[Home|{p}Home]]\n"
    sidebar += f"- [[Measures|{p}Measures]]\n"
    sidebar += f"- [[Relationships|{p}Relationships]]\n"
    sidebar += f"- [[Data Sources|{p}Data-Sources]]\n\n"
    sidebar += "**Tables**\n\n"

    for table in sorted(metadata.tables, key=lambda t: t.name):
        slug = slugify(table.name)
        sidebar += f"- [[{table.name}|{p}Table-{slug}]]\n"

    return sidebar
