
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser


PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)

MAX_FILES = 30
MAX_FILE_BYTES = 100_000

IGNORED = {
    ".git", ".venv", "venv",
    "__pycache__", "node_modules",
    "dist", "build"
}


def extract_symbols(source_code, filename="uploaded.py"):
    """
    Extract Python classes, functions and methods.
    """

    if isinstance(source_code, str):
        source = source_code.encode("utf-8")
    else:
        source = source_code

    tree = parser.parse(source)
    symbols = []

    def get_name(node):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return "unknown"
        return source[
            name_node.start_byte:name_node.end_byte
        ].decode("utf-8", errors="replace")

    def visit(node, parent_class=None):
        if node.type == "class_definition":
            name = get_name(node)

            symbols.append({
                "file": filename,
                "type": "class",
                "name": name,
                "line": node.start_point.row + 1
            })

            for child in node.children:
                visit(child, name)

            return

        if node.type == "function_definition":
            name = get_name(node)

            symbol_type = (
                "method" if parent_class else "function"
            )

            symbols.append({
                "file": filename,
                "type": symbol_type,
                "name": (
                    f"{parent_class}.{name}"
                    if parent_class else name
                ),
                "line": node.start_point.row + 1
            })

            # Continue scanning nested definitions
            for child in node.children:
                visit(child, None)

            return

        for child in node.children:
            visit(child, parent_class)

    visit(tree.root_node)
    return symbols


def map_repository(project_path):
    project = Path(project_path).expanduser().resolve()

    if not project.is_dir():
        raise ValueError("Project folder not found.")

    repository_map = []
    count = 0

    for file_path in sorted(project.rglob("*.py")):
        if count >= MAX_FILES:
            break

        relative = file_path.relative_to(project)

        if any(part in IGNORED for part in relative.parts):
            continue

        if file_path.is_symlink():
            continue

        if file_path.stat().st_size > MAX_FILE_BYTES:
            continue

        content = file_path.read_text(
            encoding="utf-8",
            errors="replace"
        )

        symbols = extract_symbols(
            content,
            str(relative)
        )

        repository_map.extend(symbols)
        count += 1

    return repository_map


def format_repository_map(symbols):
    if not symbols:
        return "No Python symbols found."

    lines = []

    for symbol in symbols:
        lines.append(
            f"{symbol['file']}:{symbol['line']} "
            f"[{symbol['type']}] {symbol['name']}"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    path = input(
        "Enter Python project folder path: "
    ).strip().strip('"')

    try:
        symbols = map_repository(path)

        print("\n===== REPOSITORY MAP =====\n")
        print(format_repository_map(symbols))

        print(
            f"\nTotal symbols found: {len(symbols)}"
        )

    except Exception as error:
        print("Error:", error)
