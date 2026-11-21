
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("DevPilot Code Search")


@mcp.tool()
def list_python_files(project_path: str) -> list[str]:
    """
    List Python source files in an approved project folder.

    Args:
        project_path: Absolute path to the project.
    """
    approved_root = Path(
        r"D:\DevPilot"
    ).resolve()

    project = Path(project_path).resolve()

    if (
        not project.is_dir()
        or not project.is_relative_to(approved_root)
    ):
        raise ValueError(
            "Project must be inside D:\\DevPilot."
        )

    excluded = {
        ".venv",
        "venv",
        "__pycache__",
        ".git",
        "node_modules",
        ".pytest_cache"
    }

    files = []

    for path in project.rglob("*.py"):
        if path.is_symlink():
            continue

        if any(
            part in excluded
            for part in path.relative_to(project).parts
        ):
            continue

        files.append(
            str(path.relative_to(project))
        )

        if len(files) >= 100:
            break

    return sorted(files)


@mcp.tool()
def read_python_file(
    project_path: str,
    relative_path: str
) -> str:
    """
    Read a Python file from an approved project.
    Does not allow file modifications.
    """
    approved_root = Path(
        r"D:\DevPilot"
    ).resolve()

    project = Path(project_path).resolve()

    if (
        not project.is_dir()
        or not project.is_relative_to(approved_root)
    ):
        raise ValueError(
            "Project must be inside D:\\DevPilot."
        )

    relative = Path(relative_path)

    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.suffix != ".py"
    ):
        raise ValueError(
            "Invalid Python file path."
        )

    target = (project / relative).resolve()

    if not target.is_relative_to(project):
        raise ValueError(
            "Access outside the project is blocked."
        )

    if not target.is_file():
        raise FileNotFoundError(
            "Python file not found."
        )

    if target.stat().st_size > 100_000:
        raise ValueError(
            "File exceeds the 100 KB limit."
        )

    return target.read_text(
        encoding="utf-8"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
