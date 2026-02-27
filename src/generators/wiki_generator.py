"""Main wiki generator — orchestrates metadata extraction and page generation."""

import logging
from pathlib import Path

from ..mcp_client.client import MCPClient
from ..mcp_client.pbixray_tools import PBIXRayClient
from ..enrichment.ai_descriptions import MeasureDescriptionGenerator
from ..models import ModelMetadata
from ..parsers.pbip_parser import detect_input_type, PBIPParser
from .pages import (
    slugify,
    generate_home_page,
    generate_table_page,
    generate_measures_page,
    generate_relationships_page,
    generate_data_sources_page,
    generate_sidebar,
    generate_order_file,
)

logger = logging.getLogger(__name__)


class WikiGenerator:
    """Generates a complete GitHub Wiki from a PBIX or PBIP file."""

    def __init__(
        self,
        output_dir: str | Path,
        server_command: list[str] | None = None,
        enrich_with_ai: bool = False,
        anthropic_api_key: str | None = None,
        ai_model: str = "claude-sonnet-4-20250514",
        cache_path: str | Path | None = None,
        platform: str = "github",
    ):
        """
        Args:
            output_dir: Directory to write wiki Markdown files.
            server_command: Command to start the PBIXRay MCP server (PBIX only).
            enrich_with_ai: Whether to generate AI descriptions for measures.
            anthropic_api_key: Anthropic API key (or set ANTHROPIC_API_KEY env var).
            ai_model: Claude model for AI enrichment.
            cache_path: Path for persistent AI description cache.
            platform: Target wiki platform ('github' or 'azure_devops').
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.server_command = server_command or ["python", "pbixray-mcp-server/src/pbixray_server.py"]
        self.enrich_with_ai = enrich_with_ai
        self.anthropic_api_key = anthropic_api_key
        self.ai_model = ai_model
        self.cache_path = cache_path
        self.platform = platform

        # Populated after generate() runs — used by multi-model generator
        self.metadata: ModelMetadata | None = None

    async def generate(
        self,
        input_path: str | Path,
        model_name: str | None = None,
        page_prefix: str = "",
    ) -> dict:
        """Generate wiki documentation from a PBIX or PBIP file.

        Automatically detects the input type:
        - .pbix → extracts via PBIXRay MCP server
        - .pbip / TMDL / model.bim → parses directly (no MCP needed)

        Args:
            input_path: Path to .pbix, .pbip, or semantic model directory.
            model_name: Display name (defaults to filename/folder stem).
            page_prefix: Optional prefix for page filenames (multi-model support).

        Returns:
            Dict with generation statistics.
        """
        input_path = Path(input_path).resolve()
        if not model_name:
            model_name = input_path.stem

        logger.info(f"Generating documentation for: {model_name}")

        # Detect input type and extract metadata
        input_type = detect_input_type(input_path)
        logger.info(f"Detected input type: {input_type}")

        if input_type == "pbix":
            metadata = await self._extract_via_mcp(input_path)
        elif input_type in ("pbip_bim", "pbip_tmdl"):
            parser = PBIPParser()
            metadata = parser.parse(input_path)
        else:
            raise ValueError(
                f"Unsupported input: {input_path}. "
                f"Provide a .pbix file, .pbip file, or PBIP semantic model directory."
            )

        metadata.name = model_name
        return await self._generate_pages(metadata, page_prefix)

    async def generate_from_metadata(
        self,
        metadata: ModelMetadata,
        page_prefix: str = "",
    ) -> dict:
        """Generate wiki pages from pre-extracted ModelMetadata.

        Useful when metadata has already been extracted externally.
        """
        return await self._generate_pages(metadata, page_prefix)

    async def _extract_via_mcp(self, pbix_path: Path) -> ModelMetadata:
        """Extract metadata from a PBIX file via MCP."""
        client = MCPClient(self.server_command)
        try:
            async with client.connect() as connected_client:
                pbi = PBIXRayClient(connected_client)
                return await pbi.get_model_metadata(str(pbix_path))
        except FileNotFoundError:
            raise
        except RuntimeError as e:
            logger.error(f"MCP Error: {e}")
            logger.error("Ensure the pbixray-mcp-server is installed and accessible.")
            raise

    async def _generate_pages(self, metadata: ModelMetadata, page_prefix: str = "") -> dict:
        """Generate all wiki pages from metadata and write to output_dir."""
        # Optional AI enrichment
        if self.enrich_with_ai:
            logger.info("Enriching measures with AI-generated descriptions...")
            cache = self.cache_path or self.output_dir / ".ai_cache.json"
            generator = MeasureDescriptionGenerator(
                api_key=self.anthropic_api_key,
                model=self.ai_model,
                cache_path=cache,
            )
            metadata.measures = await generator.enrich_measures(
                metadata.measures, metadata.tables
            )

        # Store for multi-model access
        self.metadata = metadata

        # Generate all pages
        p = page_prefix
        plat = self.platform
        self._write_page(f"{p}Home", generate_home_page(metadata, page_prefix=p, platform=plat))

        for table in metadata.tables:
            slug = slugify(table.name)
            self._write_page(
                f"{p}Table-{slug}",
                generate_table_page(table, metadata.measures, metadata.relationships, page_prefix=p, platform=plat),
            )

        self._write_page(f"{p}Measures", generate_measures_page(metadata.measures, page_prefix=p, platform=plat))
        self._write_page(
            f"{p}Relationships",
            generate_relationships_page(metadata.relationships, metadata.tables, page_prefix=p, platform=plat),
        )
        self._write_page(f"{p}Data-Sources", generate_data_sources_page(metadata.power_query, page_prefix=p, platform=plat))
        self._write_page(f"{p}_Sidebar", generate_sidebar(metadata, page_prefix=p, platform=plat))

        # Azure DevOps Wiki uses .order file for sidebar page ordering
        if plat == "azure_devops":
            order_content = generate_order_file(metadata, page_prefix=p)
            (self.output_dir / ".order").write_text(order_content, encoding="utf-8")
            logger.debug("Wrote .order file for Azure DevOps Wiki")

        page_count = 5 + len(metadata.tables)
        logger.info(f"Wiki generated: {page_count} pages in {self.output_dir}")

        return {
            "tables": len(metadata.tables),
            "measures": len(metadata.measures),
            "relationships": len(metadata.relationships),
            "pages": page_count,
        }

    def _write_page(self, name: str, content: str) -> None:
        """Write a single wiki page to the output directory."""
        path = self.output_dir / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        logger.debug(f"Wrote {path}")
