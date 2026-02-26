"""CLI entry point — generate unified wiki portal from multiple PBIX files."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from src.generators.multi_model import MultiModelWikiGenerator


def main():
    parser = argparse.ArgumentParser(
        description="Generate a unified wiki portal for multiple Power BI models.",
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Directory containing PBIX files (searched recursively)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("./wiki-portal"),
        help="Output directory (default: ./wiki-portal)",
    )
    parser.add_argument(
        "--org-name",
        default="Organization",
        help="Organization name for the portal header",
    )
    parser.add_argument(
        "--server-command",
        default="python pbixray-mcp-server/src/pbixray_server.py",
        help="Command to start the PBIXRay MCP server",
    )
    parser.add_argument(
        "--ai-descriptions",
        action="store_true",
        help="Generate AI descriptions for measures (requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--ai-model",
        default="claude-sonnet-4-20250514",
        help="Claude model for AI enrichment",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Find all PBIX files
    if not args.input_dir.is_dir():
        print(f"Error: {args.input_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    pbix_files = sorted(args.input_dir.rglob("*.pbix"))
    if not pbix_files:
        print(f"No PBIX files found in {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(pbix_files)} PBIX file(s):")
    for f in pbix_files:
        print(f"  - {f}")
    print()

    server_cmd = args.server_command.split()

    generator = MultiModelWikiGenerator(
        output_dir=args.output,
        server_command=server_cmd,
        enrich_with_ai=args.ai_descriptions,
        anthropic_api_key=None,  # Uses ANTHROPIC_API_KEY env var
        ai_model=args.ai_model,
    )

    try:
        stats = asyncio.run(generator.generate(pbix_files, args.org_name))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nPortal generation complete:")
    print(f"  Models processed:  {stats['models_processed']}")
    print(f"  Total tables:      {stats['total_tables']}")
    print(f"  Total measures:    {stats['total_measures']}")
    print(f"  Duplicate measures: {stats['duplicate_measures']}")
    print(f"  Output:            {args.output}")


if __name__ == "__main__":
    main()
