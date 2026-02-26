"""Multi-model wiki generator — unified portal across multiple PBIX files."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..models import Measure, ModelMetadata
from ..utils.markdown import MarkdownHelper as md
from .wiki_generator import WikiGenerator

logger = logging.getLogger(__name__)


@dataclass
class ProcessedModel:
    """Tracks a processed model and its metadata."""
    name: str
    path: Path
    metadata: ModelMetadata
    page_prefix: str


class MultiModelWikiGenerator:
    """Generate unified documentation portal for multiple Power BI models."""

    def __init__(
        self,
        output_dir: str | Path,
        server_command: list[str] | None = None,
        enrich_with_ai: bool = False,
        anthropic_api_key: str | None = None,
        ai_model: str = "claude-sonnet-4-20250514",
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.server_command = server_command
        self.enrich_with_ai = enrich_with_ai
        self.anthropic_api_key = anthropic_api_key
        self.ai_model = ai_model
        self.models: list[ProcessedModel] = []

    async def generate(
        self,
        pbix_paths: list[Path],
        organization_name: str = "Organization",
    ) -> dict:
        """Generate documentation for multiple models with a unified portal.

        Args:
            pbix_paths: List of PBIX file paths.
            organization_name: Name shown in the portal header.

        Returns:
            Generation statistics.
        """
        stats = {
            "models_processed": 0,
            "total_tables": 0,
            "total_measures": 0,
            "duplicate_measures": 0,
        }

        for pbix_path in pbix_paths:
            model_name = pbix_path.stem
            # GitHub Wiki is flat — prefix all pages with model name
            page_prefix = f"{model_name}-"

            logger.info(f"Processing model: {model_name}")

            cache_path = self.output_dir / f".ai_cache_{model_name}.json"
            generator = WikiGenerator(
                output_dir=self.output_dir,
                server_command=self.server_command,
                enrich_with_ai=self.enrich_with_ai,
                anthropic_api_key=self.anthropic_api_key,
                ai_model=self.ai_model,
                cache_path=cache_path,
            )

            try:
                model_stats = await generator.generate(
                    pbix_path, model_name, page_prefix=page_prefix
                )

                self.models.append(ProcessedModel(
                    name=model_name,
                    path=pbix_path,
                    metadata=generator.metadata,
                    page_prefix=page_prefix,
                ))

                stats["models_processed"] += 1
                stats["total_tables"] += model_stats.get("tables", 0)
                stats["total_measures"] += model_stats.get("measures", 0)

            except Exception as e:
                logger.error(f"Failed to process {model_name}: {e}")

        # Generate cross-cutting portal pages
        self._generate_portal_index(organization_name)
        self._generate_measure_index()
        self._generate_duplicate_report()
        self._generate_portal_sidebar()

        stats["duplicate_measures"] = self._count_duplicates()
        return stats

    # ------------------------------------------------------------------
    # Portal pages
    # ------------------------------------------------------------------

    def _generate_portal_index(self, org_name: str) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        headers = ["Model", "Domain", "Tables", "Measures", "Documentation"]
        rows = []
        for model in sorted(self.models, key=lambda m: m.name):
            domain = self._infer_domain(model.path)
            t_count = str(len(model.metadata.tables))
            m_count = str(len(model.metadata.measures))
            link = f"[[View|{model.page_prefix}Home]]"
            rows.append([model.name, domain, t_count, m_count, link])

        model_table = md.table(headers, rows) if rows else "_No models processed._"

        content = f"""# {org_name} — Power BI Documentation Portal

> Last updated: {timestamp}

## Overview

This portal provides unified documentation for all Power BI semantic models.

## Quick Links

- [[Measure Index|Measure-Index]] — search measures across all models
- [[Duplicate Report|Duplicate-Report]] — identify redundant measures

---

## Models

{model_table}

---

_This documentation is automatically generated. Do not edit manually._
"""
        self._write_page("Home", content)

    def _generate_measure_index(self) -> None:
        all_measures: list[tuple[Measure, ProcessedModel]] = []
        for model in self.models:
            for measure in model.metadata.measures:
                all_measures.append((measure, model))

        headers = ["Measure", "Model", "Table", "Description"]
        rows = []
        for measure, model in sorted(all_measures, key=lambda x: x[0].name.lower()):
            desc = (measure.description or "")[:80]
            if len(measure.description or "") > 80:
                desc += "..."
            rows.append([measure.name, model.name, measure.table, desc])

        content = f"""# Measure Index

Search for measures across all Power BI models.

**Total measures:** {len(all_measures)}

## All Measures

{md.table(headers, rows)}

---

[[← Back to Portal|Home]]
"""
        self._write_page("Measure-Index", content)

    def _generate_duplicate_report(self) -> None:
        # Group measures by name across models
        by_name: dict[str, list[tuple[Measure, ProcessedModel]]] = {}
        for model in self.models:
            for measure in model.metadata.measures:
                by_name.setdefault(measure.name, []).append((measure, model))

        duplicates = {k: v for k, v in by_name.items() if len(v) > 1}

        headers = ["Measure Name", "Appears In", "Identical DAX?"]
        rows = []
        for name in sorted(duplicates.keys()):
            occurrences = duplicates[name]
            models_list = ", ".join(m.name for _, m in occurrences)
            expressions = set(occ[0].expression.strip() for occ in occurrences)
            identical = "Yes" if len(expressions) == 1 else "Different"
            rows.append([name, models_list, identical])

        dup_table = md.table(headers, rows) if rows else "_No duplicates found._"

        content = f"""# Duplicate Measure Report

Measures that appear in multiple models — potential consolidation opportunities.

**Duplicates found:** {len(duplicates)}

## Exact Duplicates

{dup_table}

## Recommendations

- **Identical DAX (Yes):** Consider creating a shared dataset or calculation group.
- **Different DAX:** Review for consistency — same name should mean same logic.

---

[[← Back to Portal|Home]]
"""
        self._write_page("Duplicate-Report", content)

    def _generate_portal_sidebar(self) -> None:
        sidebar = "**Portal**\n\n"
        sidebar += "- [[Home]]\n"
        sidebar += "- [[Measure Index|Measure-Index]]\n"
        sidebar += "- [[Duplicate Report|Duplicate-Report]]\n\n"

        sidebar += "**Models**\n\n"
        for model in sorted(self.models, key=lambda m: m.name):
            sidebar += f"- [[{model.name}|{model.page_prefix}Home]]\n"

        self._write_page("_Sidebar", sidebar)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _count_duplicates(self) -> int:
        by_name: dict[str, int] = {}
        for model in self.models:
            for measure in model.metadata.measures:
                by_name[measure.name] = by_name.get(measure.name, 0) + 1
        return sum(1 for count in by_name.values() if count > 1)

    def _write_page(self, name: str, content: str) -> None:
        path = self.output_dir / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        logger.debug(f"Wrote portal page: {path}")

    @staticmethod
    def _infer_domain(path: Path) -> str:
        path_lower = str(path).lower()
        domains = {
            "sales": "Sales",
            "finance": "Finance",
            "hr": "HR",
            "operations": "Operations",
            "marketing": "Marketing",
            "supply": "Supply Chain",
            "logistics": "Logistics",
            "inventory": "Inventory",
        }
        for key, domain in domains.items():
            if key in path_lower:
                return domain
        return "General"
