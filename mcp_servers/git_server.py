
import asyncio
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("DevPilot Git Tools")

APPROVED_ROOT = Path(r"D:\DevPilot").resolve()


def execute_git(
    project: Path,
    arguments: list[str],
) -> str:
    """Execute a read-only Git command."""

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(project),
                "-c",
                "core.fsmonitor=false",
                "--no-pager",
                *arguments,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            stdin=subprocess.DEVNULL,
        )

    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Git command timed out."
        ) from exc

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or "Git command failed."
        )

    return result.stdout[:20000]


async def run_git(
    project: Path,
    arguments: list[str],
) -> str:
    """Run Git without blocking the MCP event loop."""

    return await asyncio.to_thread(
        execute_git,
        project,
        arguments,
    )


async def validate_repo(project_path: str) -> Path:

    project = Path(project_path).resolve()

    if not project.is_dir():
        raise ValueError("Project directory does not exist.")

    if not project.is_relative_to(APPROVED_ROOT):
        raise ValueError(
            "Project must be inside D:\\DevPilot."
        )

    root = await run_git(
        project,
        ["rev-parse", "--show-toplevel"],
    )

    repo_root = Path(root.strip()).resolve()

    if not repo_root.is_relative_to(APPROVED_ROOT):
        raise ValueError(
            "Repository is outside the approved directory."
        )

    return project


@mcp.tool()
async def git_ping() -> str:
    """Check MCP server communication."""
    return "Git MCP server is responding!"


@mcp.tool()
async def git_subprocess_test() -> str:
    """Test Git execution inside MCP."""

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            stdin=subprocess.DEVNULL,
        )

        return (
            result.stdout.strip()
            or result.stderr.strip()
        )

    except subprocess.TimeoutExpired:
        return "Git subprocess timed out."


@mcp.tool()
async def git_status(project_path: str) -> str:
    """Show tracked Git changes."""

    project = await validate_repo(project_path)

    result = await run_git(
        project,
        ["status", "--short", "-uno"],
    )

    return result if result.strip() else "No tracked-file changes."


@mcp.tool()
async def git_diff(project_path: str) -> str:
    """Show unstaged Git changes."""

    project = await validate_repo(project_path)

    result = await run_git(
        project,
        ["diff", "--no-ext-diff", "--"],
    )

    return result if result.strip() else "No unstaged changes."


@mcp.tool()
async def git_log(project_path: str) -> str:
    """Show recent Git commits."""

    project = await validate_repo(project_path)

    result = await run_git(
        project,
        ["log", "-5", "--oneline"],
    )

    return result if result.strip() else "No commits found."


if __name__ == "__main__":
    mcp.run(transport="stdio")
