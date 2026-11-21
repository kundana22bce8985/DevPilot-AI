
from pathlib import Path

from tools.code_indexer import connect_db
from tools.vector_store import generate_embedding


# Maximum number of code blocks to retrieve
MAX_RESULTS = 3

# Approximate token budget for retrieved code
MAX_CONTEXT_TOKENS = 1500

# Rough estimate: 1 token = 4 characters
CHARS_PER_TOKEN = 4


# ==========================================
# STEP 1: SEARCH PGVECTOR
# ==========================================

def search_repository(query, project_path, limit=MAX_RESULTS):

    repository = str(Path(project_path).resolve())

    query_embedding = generate_embedding(query)

    with connect_db() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    filename,
                    symbol_name,
                    code_content,
                    embedding <=> %s AS distance
                FROM repository_embeddings
                WHERE repository = %s
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (
                    query_embedding,
                    repository,
                    query_embedding,
                    limit
                )
            )

            return cur.fetchall()


# ==========================================
# STEP 2: BUILD LIMITED CODE CONTEXT
# ==========================================

def build_code_context(
    query,
    project_path,
    max_tokens=MAX_CONTEXT_TOKENS
):

    results = search_repository(
        query,
        project_path,
        limit=MAX_RESULTS
    )

    if not results:
        return "No indexed code found for this project."

    # Convert approximate token budget into characters
    max_chars = max(0, max_tokens * CHARS_PER_TOKEN)

    sections = []
    used_chars = 0

    for filename, symbol, code, distance in results:

        header = (
            f"File: {filename}\n"
            f"Symbol: {symbol}\n"
            f"Distance: {distance:.4f}\n"
            f"Code:\n"
        )

        separator = "\n\n---\n\n" if sections else ""

        available = (
            max_chars
            - used_chars
            - len(separator)
            - len(header)
        )

        if available <= 0:
            break

        # Truncate code when necessary
        if len(code) > available:
            code = code[:available]

        section = header + code

        sections.append(separator + section)

        used_chars += len(separator) + len(section)

        if used_chars >= max_chars:
            break

    if not sections:
        return "No code fits within the context budget."

    context = "".join(sections)

    print(
        f"Context prepared: "
        f"{len(context)} characters, "
        f"approximately {len(context) // 4} tokens"
    )

    return context


# ==========================================
# STEP 3: TEST SEARCH
# ==========================================

if __name__ == "__main__":

    project = input(
        "Enter project folder path: "
    ).strip().strip('"')

    question = input(
        "Enter your coding question: "
    ).strip()

    print("\nRetrieved code:\n")

    context = build_code_context(
        question,
        project
    )

    print(context)
