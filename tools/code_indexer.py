
from pathlib import Path
import hashlib
import os

import psycopg
from pgvector.psycopg import register_vector
from dotenv import load_dotenv
from tree_sitter import Language, Parser
import tree_sitter_python

from tools.vector_store import generate_embedding

load_dotenv()

IGNORE_DIRS = {
    ".git", ".venv", "venv",
    "__pycache__", "node_modules",
    "build", "dist"
}

MAX_FILE_BYTES = 200_000

PYTHON = Language(tree_sitter_python.language())
parser = Parser(PYTHON)


def connect_db():
    password = os.getenv("DEVPILOT_DB_PASSWORD")

    if not password:
        raise ValueError(
            "DEVPILOT_DB_PASSWORD is missing in .env"
        )

    conn = psycopg.connect(
        host="localhost",
        port=5432,
        dbname="devpilot_db",
        user="postgres",
        password=password
    )

    register_vector(conn)
    return conn


def create_index_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS repository_embeddings (
                id BIGSERIAL PRIMARY KEY,
                repository TEXT NOT NULL,
                filename TEXT NOT NULL,
                symbol_name TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                code_content TEXT NOT NULL,
                embedding VECTOR(384),
                UNIQUE (repository, filename, symbol_name)
            )
        """)

    conn.commit()


def extract_code_blocks(source):
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)

    blocks = []

    def visit(node):
        if node.type in (
            "function_definition",
            "class_definition"
        ):
            name_node = node.child_by_field_name("name")

            if name_node is not None:
                name = source_bytes[
                    name_node.start_byte:name_node.end_byte
                ].decode("utf-8", errors="replace")

                code = source_bytes[
                    node.start_byte:node.end_byte
                ].decode("utf-8", errors="replace")

                blocks.append((name, code))

        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return blocks


def index_repository(folder):
    root = Path(folder).resolve()

    if not root.is_dir():
        raise ValueError("Project folder not found")

    repository = str(root)
    indexed = 0
    skipped = 0

    with connect_db() as conn:
        create_index_table(conn)

        for file in sorted(root.rglob("*.py")):
            relative = file.relative_to(root)

            if any(
                part in IGNORE_DIRS
                for part in relative.parts
            ):
                continue

            if file.is_symlink():
                continue

            if file.stat().st_size > MAX_FILE_BYTES:
                continue

            source = file.read_text(
                encoding="utf-8",
                errors="replace"
            )

            blocks = extract_code_blocks(source)

            for number, (name, code) in enumerate(blocks):
                symbol_name = f"{name}#{number}"

                content_hash = hashlib.sha256(
                    code.encode("utf-8")
                ).hexdigest()

                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT content_hash
                        FROM repository_embeddings
                        WHERE repository = %s
                          AND filename = %s
                          AND symbol_name = %s
                    """, (
                        repository,
                        str(relative),
                        symbol_name
                    ))

                    existing = cur.fetchone()

                if existing and existing[0] == content_hash:
                    skipped += 1
                    continue

                embedding = generate_embedding(code)

                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO repository_embeddings (
                            repository,
                            filename,
                            symbol_name,
                            content_hash,
                            code_content,
                            embedding
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (
                            repository, filename, symbol_name
                        )
                        DO UPDATE SET
                            content_hash = EXCLUDED.content_hash,
                            code_content = EXCLUDED.code_content,
                            embedding = EXCLUDED.embedding
                    """, (
                        repository,
                        str(relative),
                        symbol_name,
                        content_hash,
                        code,
                        embedding
                    ))

                indexed += 1
                print(f"Indexed: {relative} -> {name}")

        conn.commit()

    print("\nIndexing completed!")
    print("New or updated blocks:", indexed)
    print("Unchanged blocks:", skipped)


if __name__ == "__main__":
    path = input(
        "Enter Python project folder path: "
    ).strip().strip('"')

    index_repository(path)
