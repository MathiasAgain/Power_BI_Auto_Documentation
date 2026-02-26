"""Base MCP client for communicating with MCP servers over stdio."""

import json
import logging
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPClient:
    """Async client for communicating with MCP servers via stdio transport."""

    def __init__(self, server_command: list[str], env: dict[str, str] | None = None):
        """
        Args:
            server_command: Command to start the MCP server, e.g.
                           ["python", "-m", "pbixray_server"]
            env: Optional environment variables for the server process.
        """
        self.server_params = StdioServerParameters(
            command=server_command[0],
            args=server_command[1:] if len(server_command) > 1 else [],
            env=env,
        )
        self.session: ClientSession | None = None

    @asynccontextmanager
    async def connect(self):
        """Establish connection to the MCP server.

        Usage::

            async with MCPClient(cmd).connect() as client:
                result = await client.call_tool("get_tables")
        """
        try:
            async with stdio_client(self.server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.session = session
                    logger.info("Connected to MCP server")
                    yield self
                    self.session = None
        except Exception as e:
            raise RuntimeError(f"Failed to connect to MCP server: {e}") from e

    async def call_tool(self, tool_name: str, arguments: dict | None = None) -> dict | list:
        """Invoke an MCP tool and return the parsed JSON result.

        Args:
            tool_name: Name of the MCP tool to invoke.
            arguments: Optional arguments dict for the tool.

        Returns:
            Parsed JSON response (dict or list).
        """
        if not self.session:
            raise RuntimeError("Not connected to MCP server. Use `async with client.connect():`")

        logger.debug(f"Calling tool: {tool_name} with args: {arguments}")

        try:
            result = await self.session.call_tool(
                tool_name,
                arguments=arguments or {},
            )

            for content in result.content:
                if content.type == "text":
                    try:
                        return json.loads(content.text)
                    except json.JSONDecodeError:
                        # Return raw text wrapped in a dict if not valid JSON
                        return {"raw_text": content.text}

            return {}

        except Exception as e:
            raise RuntimeError(f"Tool call '{tool_name}' failed: {e}") from e

    async def list_tools(self) -> list[dict]:
        """List all available tools on the connected server.

        Returns:
            List of dicts with 'name' and 'description' keys.
        """
        if not self.session:
            raise RuntimeError("Not connected to MCP server.")

        result = await self.session.list_tools()
        return [
            {"name": tool.name, "description": getattr(tool, "description", "")}
            for tool in result.tools
        ]
