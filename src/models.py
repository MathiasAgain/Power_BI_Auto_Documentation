"""Data models for Power BI metadata extracted via MCP."""

from dataclasses import dataclass, field


@dataclass
class Column:
    """A column in a Power BI table."""
    name: str
    data_type: str
    table: str = ""
    is_hidden: bool = False
    description: str = ""


@dataclass
class Measure:
    """A DAX measure in the Power BI model."""
    name: str
    expression: str
    table: str
    description: str = ""
    format_string: str = ""
    is_hidden: bool = False
    display_folder: str = ""


@dataclass
class Relationship:
    """A relationship between two tables."""
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    is_active: bool = True
    cross_filter_direction: str = "Single"


@dataclass
class Table:
    """A table in the Power BI model."""
    name: str
    columns: list[Column] = field(default_factory=list)
    row_count: int | None = None
    is_hidden: bool = False
    description: str = ""


@dataclass
class ModelMetadata:
    """Complete metadata for a Power BI model."""
    name: str
    file_path: str
    tables: list[Table] = field(default_factory=list)
    measures: list[Measure] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    power_query: dict[str, str] = field(default_factory=dict)
    size_bytes: int | None = None
