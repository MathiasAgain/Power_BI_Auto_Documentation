"""CLI entry point — generate wiki documentation from a single PBIX file."""

import argparse
import asyncio
import logging
import sys

from src.generators.wiki_generator import WikiGenerator


def main():
    parser = argparse.ArgumentParser(
        description="Generate GitHub Wiki documentation from a Power BI PBIX file.",
    )
    parser.add_argument(
        "pbix_file",
        help="Path to the PBIX file",
    )
    parser.add_argument(
        "-o", "--output",
        default="./wiki-output",
        help="Output directory for wiki pages (default: ./wiki-output)",
    )
    parser.add_argument(
        "-n", "--name",
        help="Model display name (default: PBIX filename)",
    )
    parser.add_argument(
        "--server-command",
        default="python pbixray-mcp-server/src/pbixray_server.py",
        help="Command to start the PBIXRay MCP server (default: python pbixray-mcp-server/src/pbixray_server.py)",
    )
    parser.add_argument(
        "--ai-descriptions",
        action="store_true",
        help="Generate AI descriptions for measures (requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--ai-model",
        default="claude-sonnet-4-20250514",
        help="Claude model for AI enrichment (default: claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--cache-path",
        help="Path to AI description cache file (default: <output>/.ai_cache.json)",
    )
    parser.add_argument(
        "--platform",
        choices=["github", "azure_devops"],
        default="github",
        help="Target wiki platform (default: github). Affects link syntax and mermaid rendering.",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="List available MCP server tools and exit",
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

    server_cmd = args.server_command.split()

    if args.discover:
        asyncio.run(_discover_tools(server_cmd))
        return

    generator = WikiGenerator(
        output_dir=args.output,
        server_command=server_cmd,
        enrich_with_ai=args.ai_descriptions,
        ai_model=args.ai_model,
        cache_path=args.cache_path,
        platform=args.platform,
    )

    try:
        stats = asyncio.run(generator.generate(args.pbix_file, args.name))
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nGeneration complete:")
    print(f"  Tables:        {stats['tables']}")
    print(f"  Measures:      {stats['measures']}")
    print(f"  Relationships: {stats['relationships']}")
    print(f"  Pages written: {stats['pages']}")
    print(f"  Output:        {args.output}")


async def _discover_tools(server_cmd: list[str]):
    """Connect to MCP server and list available tools."""
    from src.mcp_client.client import MCPClient

    client = MCPClient(server_cmd)
    async with client.connect() as c:
        tools = await c.list_tools()
        print(f"Available MCP tools ({len(tools)}):\n")
        for tool in tools:
            print(f"  {tool['name']}")
            if tool.get("description"):
                print(f"    {tool['description']}")
            print()


if __name__ == "__main__":
    main()
