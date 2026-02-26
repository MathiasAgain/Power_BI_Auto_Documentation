"""AI-powered description generation for DAX measures using Claude."""

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from anthropic import Anthropic

from ..models import Measure, Table

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Power BI documentation expert. Your task is to explain
DAX measures in clear, business-friendly language.

Guidelines:
- Write 1-2 sentences maximum
- Focus on WHAT the measure calculates, not HOW
- Use business terminology, not technical jargon
- Mention time periods, filters, or conditions if relevant
- Never include DAX syntax in your description
- Be definitive, not approximate (unless mathematically required)

Example:
Input: CALCULATE(SUM(Sales[Amount]), 'Date'[Year] = YEAR(TODAY()))
Output: Total sales revenue for the current year."""


class MeasureDescriptionGenerator:
    """Generate business-friendly descriptions for DAX measures using Claude."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        cache_path: str | Path | None = None,
    ):
        """
        Args:
            api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
            model: Claude model to use.
            cache_path: Path to a JSON file for persistent caching of descriptions.
        """
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.cache_path = Path(cache_path) if cache_path else None
        self._cache: dict[str, str] = {}

        if self.cache_path:
            self._load_cache()

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def _cache_key(self, measure: Measure) -> str:
        """Generate a cache key from table.name + hash of DAX expression."""
        dax_hash = hashlib.sha256(measure.expression.strip().encode()).hexdigest()[:12]
        return f"{measure.table}.{measure.name}:{dax_hash}"

    def _load_cache(self) -> None:
        if self.cache_path and self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
                logger.info(f"Loaded {len(self._cache)} cached descriptions")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load cache: {e}")
                self._cache = {}

    def _save_cache(self) -> None:
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps(self._cache, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(f"Saved {len(self._cache)} descriptions to cache")

    # ------------------------------------------------------------------
    # Description generation
    # ------------------------------------------------------------------

    async def generate_description(
        self,
        measure: Measure,
        table_context: Table | None = None,
        related_measures: list[Measure] | None = None,
    ) -> str:
        """Generate a business-friendly description for a single measure."""

        cache_key = self._cache_key(measure)
        if cache_key in self._cache:
            logger.debug(f"Cache hit: {measure.name}")
            return self._cache[cache_key]

        # Build prompt
        prompt_parts = [
            f"Measure Name: {measure.name}",
            f"Table: {measure.table}",
            f"DAX Expression:\n{measure.expression}",
        ]

        if measure.format_string:
            prompt_parts.append(f"Format: {measure.format_string}")

        if table_context and table_context.columns:
            col_names = ", ".join(c.name for c in table_context.columns[:10])
            prompt_parts.append(f"Table columns: {col_names}")

        if related_measures:
            refs = ", ".join(m.name for m in related_measures[:5])
            prompt_parts.append(f"Related measures: {refs}")

        user_prompt = "\n".join(prompt_parts)
        user_prompt += "\n\nGenerate a brief, business-friendly description:"

        try:
            response = await asyncio.to_thread(self._call_claude, user_prompt)
            description = response.strip()
            self._cache[cache_key] = description
            logger.info(f"Generated description for {measure.name}: {description[:60]}...")
            return description
        except Exception as e:
            logger.warning(f"Failed to generate description for {measure.name}: {e}")
            return ""

    def _call_claude(self, user_prompt: str) -> str:
        """Synchronous Claude API call (run via asyncio.to_thread)."""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=150,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text

    # ------------------------------------------------------------------
    # Batch enrichment
    # ------------------------------------------------------------------

    async def enrich_measures(
        self,
        measures: list[Measure],
        tables: list[Table] | None = None,
        concurrency: int = 5,
    ) -> list[Measure]:
        """Enrich multiple measures with AI-generated descriptions.

        Args:
            measures: Measures to enrich.
            tables: Optional tables for additional context.
            concurrency: Max concurrent API calls.

        Returns:
            New list of Measures with description fields populated.
        """
        table_map = {t.name: t for t in (tables or [])}
        measure_refs = self._find_measure_references(measures)
        semaphore = asyncio.Semaphore(concurrency)

        async def enrich_one(measure: Measure) -> Measure:
            async with semaphore:
                # Skip if already has a description (from the model itself)
                if measure.description:
                    logger.debug(f"Skipping {measure.name} — already has description")
                    return measure

                table_ctx = table_map.get(measure.table)
                related = measure_refs.get(measure.name, [])

                description = await self.generate_description(
                    measure, table_ctx, related
                )

                return Measure(
                    name=measure.name,
                    expression=measure.expression,
                    table=measure.table,
                    description=description or measure.description,
                    format_string=measure.format_string,
                    is_hidden=measure.is_hidden,
                    display_folder=measure.display_folder,
                )

        enriched = await asyncio.gather(*[enrich_one(m) for m in measures])

        # Save cache after processing
        self._save_cache()

        enriched_count = sum(1 for m in enriched if m.description)
        logger.info(f"Enriched {enriched_count}/{len(measures)} measures with AI descriptions")

        return list(enriched)

    @staticmethod
    def _find_measure_references(measures: list[Measure]) -> dict[str, list[Measure]]:
        """Find which measures reference other measures in their DAX."""
        refs: dict[str, list[Measure]] = {}
        for measure in measures:
            refs[measure.name] = [
                other
                for other in measures
                if other.name != measure.name
                and f"[{other.name}]" in measure.expression
            ]
        return refs
