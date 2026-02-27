"""Mermaid diagram generation for Power BI model visualization."""

from ..models import Measure, Relationship, Table


def _sanitize_name(name: str | None) -> str:
    """Sanitize a name for use as a Mermaid entity identifier.

    Mermaid erDiagram chokes on spaces, hyphens, and most special chars.
    """
    if not name:
        return "UNKNOWN"
    return (
        name.replace(" ", "_")
        .replace("-", "_")
        .replace(".", "_")
        .replace("(", "")
        .replace(")", "")
        .replace("[", "")
        .replace("]", "")
        .replace("/", "_")
        .replace('"', "")
        .replace("'", "")
        .replace("#", "")
        .replace(";", "")
        .replace("%", "pct")
        .replace("&", "and")
        .replace("+", "plus")
        .replace("@", "at")
        .replace("=", "_")
        .replace("{", "")
        .replace("}", "")
    )


def _sanitize_label(text: str | None) -> str:
    """Sanitize text for use inside Mermaid quoted labels."""
    if not text:
        return ""
    return text.replace('"', "'").replace("#", "")


def generate_er_diagram(
    relationships: list[Relationship],
    tables: list[Table],
    include_columns: bool = True,
    max_columns_per_table: int = 10,
) -> str:
    """Generate a Mermaid ER diagram from model relationships.

    Args:
        relationships: Model relationships.
        tables: All tables in the model.
        include_columns: Whether to show columns inside entity blocks.
        max_columns_per_table: Limit columns shown per table (avoids huge diagrams).
    """
    lines = ["erDiagram"]

    connected_tables: set[str] = set()
    table_lookup = {t.name: t for t in tables}

    # Render relationship lines
    for rel in relationships:
        connected_tables.add(rel.from_table)
        connected_tables.add(rel.to_table)

        # Active relationships use solid lines, inactive use dotted
        cardinality = "||--o{" if rel.is_active else "||..o{"

        from_name = _sanitize_name(rel.from_table)
        to_name = _sanitize_name(rel.to_table)
        label = _sanitize_label(rel.from_column)

        lines.append(f"    {to_name} {cardinality} {from_name} : \"{label}\"")

    # Render table entity blocks with columns
    if include_columns:
        for table in tables:
            safe_name = _sanitize_name(table.name)
            if table.columns:
                lines.append(f"    {safe_name} {{")
                shown = table.columns[:max_columns_per_table]
                for col in shown:
                    dtype = _sanitize_name(col.data_type) if col.data_type else "unknown"
                    col_name = _sanitize_name(col.name)
                    lines.append(f"        {dtype} {col_name}")
                if len(table.columns) > max_columns_per_table:
                    remaining = len(table.columns) - max_columns_per_table
                    lines.append(f"        string ___plus_{remaining}_more___")
                lines.append("    }")
            elif table.name not in connected_tables:
                # Orphaned table with no columns — still show it
                lines.append(f"    {safe_name} {{")
                lines.append("        string orphan_table")
                lines.append("    }")

    return "\n".join(lines)


def generate_table_diagram(
    table_name: str,
    relationships: list[Relationship],
) -> str:
    """Generate a focused ER diagram showing only one table's relationships."""
    relevant = [
        r for r in relationships
        if r.from_table == table_name or r.to_table == table_name
    ]

    if not relevant:
        return ""

    lines = ["erDiagram"]
    for rel in relevant:
        cardinality = "||--o{" if rel.is_active else "||..o{"
        label = _sanitize_label(rel.from_column)
        lines.append(
            f"    {_sanitize_name(rel.to_table)} {cardinality} "
            f"{_sanitize_name(rel.from_table)} : \"{label}\""
        )

    return "\n".join(lines)


def generate_measure_dependency_graph(measures: list[Measure]) -> str:
    """Generate a Mermaid flowchart showing measure-to-measure dependencies.

    Detects references by looking for [MeasureName] patterns in DAX expressions.
    """
    measure_names = {m.name for m in measures}

    edges: list[tuple[str, str]] = []
    for measure in measures:
        for other_name in measure_names:
            if other_name != measure.name and f"[{other_name}]" in measure.expression:
                edges.append((measure.name, other_name))

    if not edges:
        return ""

    lines = ["flowchart LR"]
    for source, target in edges:
        safe_source = _sanitize_name(source)
        safe_target = _sanitize_name(target)
        safe_label_src = _sanitize_label(source)
        safe_label_tgt = _sanitize_label(target)
        lines.append(f"    {safe_source}[\"{safe_label_src}\"] --> {safe_target}[\"{safe_label_tgt}\"]")

    return "\n".join(lines)
