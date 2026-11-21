
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("DevPilot MCP Diagnostic")


@mcp.tool()
def say_hello() -> str:
    """Return a simple message."""
    return "Hello! MCP tool execution is working."


if __name__ == "__main__":
    mcp.run(transport="stdio")
