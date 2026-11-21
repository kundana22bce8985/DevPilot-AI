
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import (
    StdioServerParameters,
    stdio_client,
)

BASE_DIR = Path(__file__).resolve().parent

SERVER_FILE = (
    BASE_DIR / "mcp_servers" / "test_server.py"
)

TEST_PROJECT = BASE_DIR / "bug_demo"


async def main():

    if not TEST_PROJECT.is_dir():
        print("ERROR: bug_demo folder not found.")
        return

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_FILE)],
        cwd=str(BASE_DIR),
    )

    print("Starting Test Runner MCP Server...")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:

            await session.initialize()

            print("MCP connected successfully!")

            tools = await session.list_tools()

            print("\nAvailable tools:")
            for tool in tools.tools:
                print("-", tool.name)

            print("\nTesting MCP connection...")

            ping = await asyncio.wait_for(
                session.call_tool(
                    "test_ping",
                    arguments={},
                ),
                timeout=15,
            )

            for item in ping.content:
                if hasattr(item, "text"):
                    print(item.text)

            print("\nRunning tests in bug_demo...")

            result = await asyncio.wait_for(
                session.call_tool(
                    "run_project_tests",
                    arguments={
                        "project_path": str(TEST_PROJECT)
                    },
                ),
                timeout=60,
            )

            print("\nTEST RESULTS:")
            print("Is error:", result.isError)

            for item in result.content:
                if hasattr(item, "text"):
                    print(item.text)
                else:
                    print(item)

            print("\nTest Runner MCP completed!")


if __name__ == "__main__":
    asyncio.run(main())
