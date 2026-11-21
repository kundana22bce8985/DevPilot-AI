
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import (
    StdioServerParameters,
    stdio_client,
)

BASE_DIR = Path(__file__).resolve().parent


async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            str(
                BASE_DIR
                / "mcp_servers"
                / "hello_server.py"
            )
        ],
        cwd=str(BASE_DIR),
    )

    print("Starting MCP server...", flush=True)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("MCP connected!", flush=True)

            tools = await session.list_tools()

            print("Available tools:")
            for tool in tools.tools:
                print("-", tool.name)

            print("Calling say_hello...", flush=True)

            result = await asyncio.wait_for(
                session.call_tool(
                    "say_hello",
                    arguments={},
                ),
                timeout=10,
            )

            print("Result:", flush=True)

            for item in result.content:
                if hasattr(item, "text"):
                    print(item.text)


if __name__ == "__main__":
    asyncio.run(main())
