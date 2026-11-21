
import asyncio
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from tools.test_runner import run_tests

mcp = FastMCP("DevPilot Test Runner")

APPROVED_ROOT = BASE_DIR.resolve()


@mcp.tool()
async def test_ping() -> str:
    """Check whether the Test MCP server works."""
    return "Test Runner MCP is working!"


@mcp.tool()
async def run_project_tests(project_path: str) -> dict:
    """Run Python tests for an approved subproject."""

    project = Path(project_path).resolve()

    if not project.is_dir():
        raise ValueError("Project directory does not exist.")

    if (
        not project.is_relative_to(APPROVED_ROOT)
        or project == APPROVED_ROOT
    ):
        raise ValueError(
            "Select a subproject inside D:\\DevPilot."
        )

    return await asyncio.to_thread(
        run_tests,
        str(project)
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
