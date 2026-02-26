"""High-level wrappers around PBIXRay MCP server tools.

Translates raw MCP tool responses into typed dataclasses from src.models.

Field name mappings are based on the actual PBIXRay MCP server which returns
pandas DataFrame records with PascalCase column names like TableName, Name,
Expression, ColumnName, FromTableName, etc.
"""

import logging
from pathlib import Path

from .client import MCPClient
from ..models import Column, Measure, Relationship, Table, ModelMetadata

logger = logging.getLogger(__name__)

# PBIXRay MCP tool name mapping.
# If PBIXRay renames tools, update only this dict.
TOOL_NAMES = {
    "load": "load_pbix_file",
    "tables": "get_tables",
    "columns": "get_schema",
    "measures": "get_dax_measures",
    "relationships": "get_relationships",
    "power_query": "get_power_query",
    "summary": "get_model_summary",
}


def _get(d: dict, *keys, default=""):
    """Try multiple keys on a dict, return the first non-None match or default."""
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return default


class PBIXRayClient:
    """High-level async client for the PBIXRay MCP server."""

    def __init__(self, client: MCPClient):
        self.client = client

    async def load_pbix(self, file_path: str) -> dict:
        """Load a PBIX file for analysis."""
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"PBIX file not found: {path}")

        logger.info(f"Loading PBIX file: {path}")
        return await self.client.call_tool(
            TOOL_NAMES["load"],
            {"file_path": str(path)},
        )

    async def get_tables(self) -> list[Table]:
        """Get all tables in the loaded model.

        PBIXRay returns a JSON array of table name strings.
        """
        result = await self.client.call_tool(TOOL_NAMES["tables"])
        logger.debug(f"get_tables raw result type={type(result).__name__}, value={str(result)[:200]}")

        # PBIXRay may return a raw_text wrapper if the response wasn't valid JSON.
        # get_tables often returns a numpy StringArray repr like:
        #   <StringArray>\n['Table1', 'Table2', ...]
        if isinstance(result, dict) and "raw_text" in result:
            raw = result["raw_text"]
            import ast, json, re
            # Try JSON first
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    result = parsed
            except (json.JSONDecodeError, TypeError):
                # Try to extract a Python list literal from the string
                match = re.search(r"\[.*\]", raw, re.DOTALL)
                if match:
                    try:
                        parsed = ast.literal_eval(match.group(0))
                        if isinstance(parsed, list):
                            result = parsed
                    except (ValueError, SyntaxError):
                        logger.warning(f"Could not parse tables from raw text: {raw[:100]}")

        raw_tables = result if isinstance(result, list) else result.get("tables", [])

        tables = []
        for t in raw_tables:
            if isinstance(t, str):
                tables.append(Table(name=t))
            elif isinstance(t, dict):
                tables.append(Table(
                    name=_get(t, "Name", "name"),
                    row_count=_get(t, "RowCount", "row_count", "rowCount", default=None),
                    is_hidden=_get(t, "IsHidden", "is_hidden", "isHidden", default=False),
                    description=_get(t, "Description", "description"),
                ))
            else:
                tables.append(Table(name=str(t)))
        return tables

    async def get_schema(self, table_name: str | None = None) -> list[dict]:
        """Get raw column schema records, optionally for a specific table.

        PBIXRay returns DataFrame records with columns:
        TableName, ColumnName, DataType, etc.
        """
        args = {"table_name": table_name} if table_name else {}
        result = await self.client.call_tool(TOOL_NAMES["columns"], args)

        # Result is a JSON array of records from pandas .to_json(orient="records")
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("columns", [])
        return []

    async def get_columns_for_table(self, table_name: str) -> list[Column]:
        """Get typed Column objects for a specific table."""
        raw_cols = await self.get_schema(table_name)

        return [
            Column(
                name=_get(c, "ColumnName", "Name", "name") if isinstance(c, dict) else str(c),
                data_type=_get(c, "DataType", "data_type", "dataType", default="Unknown") if isinstance(c, dict) else "Unknown",
                table=table_name,
                is_hidden=_get(c, "IsHidden", "is_hidden", "isHidden", default=False) if isinstance(c, dict) else False,
                description=_get(c, "Description", "description") if isinstance(c, dict) else "",
            )
            for c in raw_cols
            if isinstance(c, (dict, str))
        ]

    async def get_measures(self, table_name: str | None = None) -> list[Measure]:
        """Get DAX measures, optionally filtered by table.

        PBIXRay returns DataFrame records with columns:
        TableName, Name, Expression, (and possibly FormatString, IsHidden, DisplayFolder).
        """
        args = {"table_name": table_name} if table_name else {}
        result = await self.client.call_tool(TOOL_NAMES["measures"], args)
        raw_measures = result if isinstance(result, list) else result.get("measures", [])

        return [
            Measure(
                name=_get(m, "Name", "name"),
                expression=_get(m, "Expression", "expression"),
                table=_get(m, "TableName", "Table", "table", "tableName"),
                description=_get(m, "Description", "description"),
                format_string=_get(m, "FormatString", "format_string", "formatString"),
                is_hidden=_get(m, "IsHidden", "is_hidden", "isHidden", default=False),
                display_folder=_get(m, "DisplayFolder", "display_folder", "displayFolder"),
            )
            for m in raw_measures
            if isinstance(m, dict)
        ]

    async def get_relationships(self) -> list[Relationship]:
        """Get all model relationships.

        PBIXRay returns DataFrame records with columns:
        FromTableName, FromColumnName, ToTableName, ToColumnName,
        IsActive, CrossFilteringBehavior, etc.
        """
        result = await self.client.call_tool(TOOL_NAMES["relationships"])
        raw_rels = result if isinstance(result, list) else result.get("relationships", [])

        return [
            Relationship(
                from_table=_get(r, "FromTableName", "from_table", "fromTable"),
                from_column=_get(r, "FromColumnName", "from_column", "fromColumn"),
                to_table=_get(r, "ToTableName", "to_table", "toTable"),
                to_column=_get(r, "ToColumnName", "to_column", "toColumn"),
                is_active=_get(r, "IsActive", "is_active", "isActive", default=True),
                cross_filter_direction=_get(
                    r, "CrossFilteringBehavior", "CrossFilterDirection",
                    "cross_filter_direction", "crossFilterDirection",
                    default="Single",
                ),
            )
            for r in raw_rels
            if isinstance(r, dict)
        ]

    async def get_power_query(self) -> dict[str, str]:
        """Get Power Query/M code for all tables.

        PBIXRay returns DataFrame records with columns: TableName, Expression.
        We convert to a {table_name: expression} dict.
        """
        result = await self.client.call_tool(TOOL_NAMES["power_query"])

        # PBIXRay returns a JSON array of records from pandas
        if isinstance(result, list):
            return {
                _get(q, "TableName", "Name", "name", default=f"Query_{i}"): _get(q, "Expression", "expression")
                for i, q in enumerate(result)
                if isinstance(q, dict)
            }

        if isinstance(result, dict):
            # Could be {"queries": [...]} or a flat dict
            queries = result.get("queries", result.get("expressions", None))
            if queries is None:
                return {k: v for k, v in result.items() if isinstance(v, str)}
            if isinstance(queries, list):
                return {
                    _get(q, "TableName", "Name", "name", default=f"Query_{i}"): _get(q, "Expression", "expression")
                    for i, q in enumerate(queries)
                    if isinstance(q, dict)
                }
        return {}

    async def get_model_summary(self) -> dict:
        """Get model-level summary info.

        PBIXRay returns a dict with: file_path, file_name, size_bytes,
        size_mb, tables_count, tables, measures_count, relationships_count.
        """
        result = await self.client.call_tool(TOOL_NAMES["summary"])
        return result if isinstance(result, dict) else {}

    async def get_model_metadata(self, pbix_path: str) -> ModelMetadata:
        """Extract complete model metadata from a PBIX file.

        This is the main entry point — orchestrates all tool calls
        and returns a single ModelMetadata object.
        """
        await self.load_pbix(pbix_path)

        model_name = Path(pbix_path).stem

        logger.info("Extracting tables...")
        tables = await self.get_tables()

        logger.info("Extracting measures...")
        measures = await self.get_measures()

        logger.info("Extracting relationships...")
        relationships = await self.get_relationships()

        logger.info("Extracting Power Query expressions...")
        power_query = await self.get_power_query()

        summary = await self.get_model_summary()

        # Enrich tables with column details
        for table in tables:
            logger.info(f"  Fetching columns for table: {table.name}")
            table.columns = await self.get_columns_for_table(table.name)

        logger.info(
            f"Extracted: {len(tables)} tables, {len(measures)} measures, "
            f"{len(relationships)} relationships"
        )

        return ModelMetadata(
            name=model_name,
            file_path=str(Path(pbix_path).resolve()),
            tables=tables,
            measures=measures,
            relationships=relationships,
            power_query=power_query,
            size_bytes=summary.get("size_bytes"),
        )
