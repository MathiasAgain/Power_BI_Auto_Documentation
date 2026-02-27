"""Parser for Power BI Project (PBIP) files — supports both BIM (JSON) and TMDL formats."""

import json
import logging
import re
from pathlib import Path

from ..models import Column, Measure, Relationship, Table, ModelMetadata

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_input_type(path: str | Path) -> str:
    """Detect the input type: 'pbix', 'pbip_bim', 'pbip_tmdl', or 'unknown'.

    Args:
        path: Path to a .pbix file, .pbip file, or semantic model directory.

    Returns:
        One of: 'pbix', 'pbip_bim', 'pbip_tmdl', 'unknown'.
    """
    p = Path(path)

    if p.suffix.lower() == ".pbix":
        return "pbix"

    if p.suffix.lower() == ".pbip":
        # .pbip is a pointer file — find the semantic model folder next to it
        sm_dir = _find_semantic_model_dir(p.parent)
        if sm_dir:
            return _detect_format_in_dir(sm_dir)
        return "unknown"

    if p.is_dir():
        # Could be the semantic model dir itself, or a parent containing it
        fmt = _detect_format_in_dir(p)
        if fmt != "unknown":
            return fmt
        sm_dir = _find_semantic_model_dir(p)
        if sm_dir:
            return _detect_format_in_dir(sm_dir)

    return "unknown"


def extract_metadata_from_path(path: str | Path) -> ModelMetadata:
    """Extract ModelMetadata from a PBIP project (BIM or TMDL).

    Args:
        path: Path to .pbip file, semantic model directory, or model.bim file.

    Returns:
        Populated ModelMetadata.
    """
    parser = PBIPParser()
    return parser.parse(path)


# ---------------------------------------------------------------------------
# Parser class
# ---------------------------------------------------------------------------

class PBIPParser:
    """Parses PBIP projects in both BIM (JSON) and TMDL folder formats."""

    def parse(self, path: str | Path) -> ModelMetadata:
        """Parse a PBIP project and return ModelMetadata.

        Args:
            path: Path to .pbip file, .SemanticModel directory, model.bim, or definition/ folder.
        """
        p = Path(path)
        input_type = detect_input_type(p)

        if input_type == "pbip_bim":
            bim_path = self._find_bim_file(p)
            logger.info(f"Parsing BIM (JSON) file: {bim_path}")
            return self._parse_bim(bim_path)

        elif input_type == "pbip_tmdl":
            tmdl_dir = self._find_tmdl_dir(p)
            logger.info(f"Parsing TMDL folder: {tmdl_dir}")
            return self._parse_tmdl(tmdl_dir)

        else:
            raise ValueError(
                f"Cannot detect PBIP format at: {p}. "
                f"Expected a .pbip file, a directory with model.bim, or a definition/ folder with .tmdl files."
            )

    # -----------------------------------------------------------------------
    # BIM (JSON / TMSL) parsing
    # -----------------------------------------------------------------------

    def _parse_bim(self, bim_path: Path) -> ModelMetadata:
        """Parse a model.bim JSON file."""
        data = json.loads(bim_path.read_text(encoding="utf-8-sig"))
        model = data.get("model", data)  # Some BIM files wrap in {"model": ...}
        model_name = data.get("name", bim_path.parent.name)

        tables = []
        measures = []

        for t in model.get("tables", []):
            table_name = t.get("name", "")
            is_hidden = t.get("isHidden", False)
            description = t.get("description", "")

            columns = []
            for c in t.get("columns", []):
                columns.append(Column(
                    name=c.get("name", ""),
                    data_type=c.get("dataType", "unknown"),
                    table=table_name,
                    is_hidden=c.get("isHidden", False),
                    description=c.get("description", ""),
                ))

            for m in t.get("measures", []):
                expr = m.get("expression", "")
                if isinstance(expr, list):
                    expr = "\n".join(expr)
                measures.append(Measure(
                    name=m.get("name", ""),
                    expression=expr,
                    table=table_name,
                    description=m.get("description", ""),
                    format_string=m.get("formatString", ""),
                    is_hidden=m.get("isHidden", False),
                    display_folder=m.get("displayFolder", ""),
                ))

            tables.append(Table(
                name=table_name,
                columns=columns,
                is_hidden=is_hidden,
                description=description,
            ))

        relationships = []
        for r in model.get("relationships", []):
            relationships.append(Relationship(
                from_table=r.get("fromTable", ""),
                from_column=r.get("fromColumn", ""),
                to_table=r.get("toTable", ""),
                to_column=r.get("toColumn", ""),
                is_active=r.get("isActive", True),
                cross_filter_direction=r.get("crossFilteringBehavior", "Single"),
            ))

        # Power Query / M expressions
        power_query: dict[str, str] = {}
        for expr_obj in model.get("expressions", []):
            name = expr_obj.get("name", "")
            expr = expr_obj.get("expression", "")
            if isinstance(expr, list):
                expr = "\n".join(expr)
            if name and expr:
                power_query[name] = expr

        # Also extract M expressions from table partitions
        for t in model.get("tables", []):
            for part in t.get("partitions", []):
                source = part.get("source", {})
                if source.get("type") == "m":
                    expr = source.get("expression", "")
                    if isinstance(expr, list):
                        expr = "\n".join(expr)
                    if expr:
                        power_query[t.get("name", "")] = expr

        logger.info(f"BIM parsed: {len(tables)} tables, {len(measures)} measures, {len(relationships)} relationships")

        return ModelMetadata(
            name=model_name,
            file_path=str(bim_path),
            tables=tables,
            measures=measures,
            relationships=relationships,
            power_query=power_query,
        )

    # -----------------------------------------------------------------------
    # TMDL parsing
    # -----------------------------------------------------------------------

    def _parse_tmdl(self, definition_dir: Path) -> ModelMetadata:
        """Parse a TMDL definition folder."""
        model_name = definition_dir.parent.name

        tables: list[Table] = []
        measures: list[Measure] = []

        # Parse table files
        power_query: dict[str, str] = {}
        tables_dir = definition_dir / "tables"
        if tables_dir.is_dir():
            for tmdl_file in sorted(tables_dir.glob("*.tmdl")):
                table, table_measures, table_pq = self._parse_tmdl_table(tmdl_file)
                tables.append(table)
                measures.extend(table_measures)
                power_query.update(table_pq)

        # Parse relationships
        relationships = self._parse_tmdl_relationships(definition_dir / "relationships.tmdl")

        # Parse expressions.tmdl (shared M expressions, if present)
        power_query.update(self._parse_tmdl_expressions(definition_dir / "expressions.tmdl"))

        logger.info(f"TMDL parsed: {len(tables)} tables, {len(measures)} measures, {len(relationships)} relationships")

        return ModelMetadata(
            name=model_name,
            file_path=str(definition_dir),
            tables=tables,
            measures=measures,
            relationships=relationships,
            power_query=power_query,
        )

    def _parse_tmdl_table(self, tmdl_path: Path) -> tuple[Table, list[Measure], dict[str, str]]:
        """Parse a single table .tmdl file. Returns (Table, list of Measures, power_query dict)."""
        text = tmdl_path.read_text(encoding="utf-8-sig")
        lines = text.splitlines()

        table_name = ""
        table_hidden = False
        table_desc = ""
        columns: list[Column] = []
        measures: list[Measure] = []
        power_query: dict[str, str] = {}

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Table declaration
            if stripped.startswith("table "):
                table_name = self._unquote(stripped[6:].strip())

            # Table-level properties
            elif stripped == "isHidden" and not columns and not measures:
                table_hidden = True

            # Description (/// comments before an object)
            elif stripped.startswith("///"):
                desc_lines = []
                while i < len(lines) and lines[i].strip().startswith("///"):
                    desc_lines.append(lines[i].strip()[3:].strip())
                    i += 1
                # The description belongs to the next object
                next_stripped = lines[i].strip() if i < len(lines) else ""
                desc_text = " ".join(desc_lines)

                if next_stripped.startswith("table "):
                    table_desc = desc_text
                elif next_stripped.startswith("column "):
                    col, i = self._parse_tmdl_column(lines, i, table_name, desc_text)
                    columns.append(col)
                elif next_stripped.startswith("measure "):
                    meas, i = self._parse_tmdl_measure(lines, i, table_name, desc_text)
                    measures.append(meas)
                continue  # already advanced i

            # Column
            elif stripped.startswith("column "):
                col, i = self._parse_tmdl_column(lines, i, table_name)
                columns.append(col)
                continue

            # Measure
            elif stripped.startswith("measure "):
                meas, i = self._parse_tmdl_measure(lines, i, table_name)
                measures.append(meas)
                continue

            # M partition (Power Query expression)
            elif stripped.startswith("partition ") and stripped.endswith("= m"):
                expr, i = self._parse_tmdl_partition_m(lines, i)
                if expr:
                    power_query[table_name] = expr
                continue

            i += 1

        table = Table(
            name=table_name,
            columns=columns,
            is_hidden=table_hidden,
            description=table_desc,
        )
        return table, measures, power_query

    def _parse_tmdl_column(
        self, lines: list[str], start: int, table_name: str, description: str = ""
    ) -> tuple[Column, int]:
        """Parse a column declaration and its properties. Returns (Column, next line index)."""
        line = lines[start].strip()
        # Calculated columns: column 'Name' = Expression
        # Regular columns:    column 'Name'
        col_part = line[7:].strip()
        match = re.match(r"(.+?)\s*=\s*", col_part)
        if match:
            name = self._unquote(match.group(1).strip())
        else:
            name = self._unquote(col_part)
        data_type = "unknown"
        is_hidden = False
        indent = self._indent_level(lines[start])

        i = start + 1
        while i < len(lines):
            l = lines[i]
            if not l.strip():
                i += 1
                continue
            if self._indent_level(l) <= indent:
                break
            prop = l.strip()
            if prop.startswith("dataType:"):
                data_type = prop.split(":", 1)[1].strip()
            elif prop == "isHidden":
                is_hidden = True
            i += 1

        return Column(
            name=name,
            data_type=data_type,
            table=table_name,
            is_hidden=is_hidden,
            description=description,
        ), i

    def _parse_tmdl_measure(
        self, lines: list[str], start: int, table_name: str, description: str = ""
    ) -> tuple[Measure, int]:
        """Parse a measure declaration and its properties. Returns (Measure, next line index)."""
        line = lines[start].strip()
        # measure 'Name' = EXPR  or  measure 'Name' = \n multi-line
        match = re.match(r"measure\s+(.+?)\s*=\s*(.*)", line)
        if not match:
            # measure with no expression (shouldn't happen but be safe)
            name = self._unquote(line[8:].strip())
            expression = ""
        else:
            name = self._unquote(match.group(1).strip())
            expression = match.group(2).strip()

        format_string = ""
        display_folder = ""
        is_hidden = False
        indent = self._indent_level(lines[start])

        i = start + 1

        # If expression is empty, collect multi-line expression
        if not expression:
            expr_lines = []
            while i < len(lines):
                l = lines[i]
                if not l.strip():
                    expr_lines.append("")
                    i += 1
                    continue
                if self._indent_level(l) <= indent + 1:
                    # Check if it's a property (has colon) or next object
                    if ":" in l.strip() or l.strip() == "isHidden" or self._indent_level(l) <= indent:
                        break
                expr_lines.append(l.strip())
                i += 1
            expression = "\n".join(expr_lines).strip()

        # Parse properties after expression
        while i < len(lines):
            l = lines[i]
            if not l.strip():
                i += 1
                continue
            if self._indent_level(l) <= indent:
                break
            prop = l.strip()
            if prop.startswith("formatString:"):
                format_string = prop.split(":", 1)[1].strip()
            elif prop.startswith("displayFolder:"):
                display_folder = self._unquote(prop.split(":", 1)[1].strip())
            elif prop == "isHidden":
                is_hidden = True
            i += 1

        return Measure(
            name=name,
            expression=expression,
            table=table_name,
            description=description,
            format_string=format_string,
            is_hidden=is_hidden,
            display_folder=display_folder,
        ), i

    def _parse_tmdl_partition_m(
        self, lines: list[str], start: int
    ) -> tuple[str, int]:
        """Parse an M partition block and extract the Power Query expression.

        Returns (expression, next line index).
        """
        indent = self._indent_level(lines[start])
        expression = ""

        i = start + 1
        while i < len(lines):
            l = lines[i]
            if not l.strip():
                i += 1
                continue
            if self._indent_level(l) <= indent:
                break
            prop = l.strip()
            if prop.startswith("source"):
                # source = <expression> or source = \n <multi-line>
                match = re.match(r"source\s*=\s*(.*)", prop)
                if match:
                    first_line = match.group(1).strip()
                    i += 1
                    expr_lines = [first_line] if first_line else []
                    source_indent = self._indent_level(l)
                    while i < len(lines):
                        el = lines[i]
                        if not el.strip():
                            expr_lines.append("")
                            i += 1
                            continue
                        if self._indent_level(el) <= source_indent:
                            break
                        expr_lines.append(el.strip())
                        i += 1
                    expression = "\n".join(expr_lines).strip()
                    continue
            i += 1

        return expression, i

    def _parse_tmdl_relationships(self, rel_path: Path) -> list[Relationship]:
        """Parse relationships.tmdl file."""
        if not rel_path.exists():
            return []

        text = rel_path.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        relationships: list[Relationship] = []

        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("relationship "):
                rel, i = self._parse_single_relationship(lines, i)
                relationships.append(rel)
                continue
            i += 1

        return relationships

    def _parse_single_relationship(self, lines: list[str], start: int) -> tuple[Relationship, int]:
        """Parse a single relationship block."""
        indent = self._indent_level(lines[start])
        from_col = ""
        to_col = ""
        is_active = True
        cross_filter = "Single"

        i = start + 1
        while i < len(lines):
            l = lines[i]
            if not l.strip():
                i += 1
                continue
            if self._indent_level(l) <= indent:
                break
            prop = l.strip()
            if prop.startswith("fromColumn:"):
                from_col = prop.split(":", 1)[1].strip()
            elif prop.startswith("toColumn:"):
                to_col = prop.split(":", 1)[1].strip()
            elif prop.startswith("isActive:"):
                is_active = prop.split(":", 1)[1].strip().lower() != "false"
            elif prop.startswith("crossFilteringBehavior:"):
                cross_filter = prop.split(":", 1)[1].strip()
            i += 1

        # Parse Table.'Column' references
        from_table, from_column = self._parse_column_ref(from_col)
        to_table, to_column = self._parse_column_ref(to_col)

        return Relationship(
            from_table=from_table,
            from_column=from_column,
            to_table=to_table,
            to_column=to_column,
            is_active=is_active,
            cross_filter_direction=cross_filter,
        ), i

    def _parse_tmdl_expressions(self, expr_path: Path) -> dict[str, str]:
        """Parse expressions.tmdl for Power Query / M expressions."""
        if not expr_path.exists():
            return {}

        text = expr_path.read_text(encoding="utf-8-sig")
        lines = text.splitlines()
        expressions: dict[str, str] = {}

        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith("expression "):
                match = re.match(r"expression\s+(.+?)\s*=\s*(.*)", stripped)
                if match:
                    name = self._unquote(match.group(1).strip())
                    # Check for meta tag and strip it
                    first_line = match.group(2).strip()
                    meta_match = re.match(r"(.*?)\s+meta\s+\[.*\]\s*$", first_line)
                    if meta_match:
                        first_line = meta_match.group(1).strip()

                    indent = self._indent_level(lines[i])
                    i += 1
                    expr_lines = [first_line] if first_line else []
                    while i < len(lines):
                        l = lines[i]
                        if not l.strip():
                            expr_lines.append("")
                            i += 1
                            continue
                        if self._indent_level(l) <= indent:
                            break
                        expr_lines.append(l.strip())
                        i += 1
                    expressions[name] = "\n".join(expr_lines).strip()
                    continue
            i += 1

        return expressions

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _parse_column_ref(ref: str) -> tuple[str, str]:
        """Parse a TMDL column reference like Sales.'Product Key' into (table, column)."""
        # Format: TableName.'Column Name' or 'Table Name'.'Column Name'
        parts = ref.split(".", 1)
        if len(parts) == 2:
            table = PBIPParser._unquote(parts[0].strip())
            column = PBIPParser._unquote(parts[1].strip())
            return table, column
        return "", ref

    @staticmethod
    def _unquote(name: str) -> str:
        """Remove surrounding single quotes from a TMDL name."""
        if name.startswith("'") and name.endswith("'"):
            return name[1:-1].replace("''", "'")
        # Also strip double quotes
        if name.startswith('"') and name.endswith('"'):
            return name[1:-1]
        return name

    @staticmethod
    def _indent_level(line: str) -> int:
        """Count the indentation level (tabs or groups of 4 spaces)."""
        spaces = len(line) - len(line.lstrip())
        tabs = line.count("\t", 0, spaces)
        if tabs > 0:
            return tabs
        return spaces // 4

    def _find_bim_file(self, path: Path) -> Path:
        """Locate the model.bim file from various input paths."""
        if path.is_file() and path.name == "model.bim":
            return path
        if path.suffix.lower() == ".pbip":
            sm_dir = _find_semantic_model_dir(path.parent)
            if sm_dir:
                bim = sm_dir / "model.bim"
                if bim.exists():
                    return bim
        if path.is_dir():
            bim = path / "model.bim"
            if bim.exists():
                return bim
            sm_dir = _find_semantic_model_dir(path)
            if sm_dir:
                bim = sm_dir / "model.bim"
                if bim.exists():
                    return bim
        raise FileNotFoundError(f"model.bim not found at: {path}")

    def _find_tmdl_dir(self, path: Path) -> Path:
        """Locate the TMDL definition folder from various input paths."""
        if path.is_dir() and (path / "tables").is_dir():
            return path
        defn = path / "definition"
        if defn.is_dir() and (defn / "tables").is_dir():
            return defn
        if path.suffix.lower() == ".pbip":
            sm_dir = _find_semantic_model_dir(path.parent)
            if sm_dir:
                defn = sm_dir / "definition"
                if defn.is_dir():
                    return defn
        if path.is_dir():
            sm_dir = _find_semantic_model_dir(path)
            if sm_dir:
                defn = sm_dir / "definition"
                if defn.is_dir():
                    return defn
        raise FileNotFoundError(f"TMDL definition folder not found at: {path}")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _find_semantic_model_dir(parent: Path) -> Path | None:
    """Find a *.SemanticModel or *.Dataset directory inside parent."""
    for d in parent.iterdir():
        if d.is_dir() and (
            d.name.endswith(".SemanticModel")
            or d.name.endswith(".Dataset")
        ):
            return d
    # Also check if parent itself is the semantic model dir
    if (parent / "model.bim").exists() or (parent / "definition").is_dir():
        return parent
    return None


def _detect_format_in_dir(sm_dir: Path) -> str:
    """Detect whether a semantic model directory uses BIM or TMDL format."""
    if (sm_dir / "definition" / "tables").is_dir():
        return "pbip_tmdl"
    if (sm_dir / "definition").is_dir():
        # definition exists but no tables subfolder — could still be TMDL with model.tmdl
        if any((sm_dir / "definition").glob("*.tmdl")):
            return "pbip_tmdl"
    if (sm_dir / "model.bim").exists():
        return "pbip_bim"
    return "unknown"
