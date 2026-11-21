
import os

import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

model = None


def get_model():
    global model

    if model is None:
        model = SentenceTransformer(MODEL_NAME)

    return model


def get_connection():
    password = os.getenv("DEVPILOT_DB_PASSWORD")

    if not password:
        raise ValueError(
            "Set DEVPILOT_DB_PASSWORD in your .env file."
        )

    connection = psycopg.connect(
        host="localhost",
        port=5432,
        dbname="devpilot_db",
        user="postgres",
        password=password
    )

    register_vector(connection)

    return connection


def generate_embedding(text):
    embedding = get_model().encode(text)
    return embedding


def store_code(filename, function_name, code_content):
    embedding = generate_embedding(code_content)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO code_embeddings
                (filename, function_name, code_content, embedding)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    filename,
                    function_name,
                    code_content,
                    embedding
                )
            )

    print("Code embedding stored successfully!")


def search_code(query, limit=3):
    query_embedding = generate_embedding(query)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT filename,
                       function_name,
                       code_content,
                       embedding <=> %s AS distance
                FROM code_embeddings
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (
                    query_embedding,
                    query_embedding,
                    limit
                )
            )

            return cursor.fetchall()


if __name__ == "__main__":
    store_code(
        "calculator.py",
        "divide",
        "def divide(a, b): return a / b"
    )

    results = search_code(
        "Find the function that divides two numbers"
    )

    for filename, function_name, code, distance in results:
        print("\nFile:", filename)
        print("Function:", function_name)
        print("Code:", code)
        print("Distance:", distance)
