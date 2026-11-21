
import sys
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

BASE_DIR = Path(__file__).resolve().parent.parent


def create_mcp_client():
    return MultiServerMCPClient({
        "code_search": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                str(
                    BASE_DIR
                    / "mcp_servers"
                    / "code_search_server.py"
                )
            ],
            "cwd": str(BASE_DIR),
        },
        "git": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                str(
                    BASE_DIR
                    / "mcp_servers"
                    / "git_server.py"
                )
            ],
            "cwd": str(BASE_DIR),
        },
        "test_runner": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
                str(
                    BASE_DIR
                    / "mcp_servers"
                    / "test_server.py"
                )
            ],
            "cwd": str(BASE_DIR),
        },
    })


async def get_mcp_tools():
    client = create_mcp_client()
    return await client.get_tools()
