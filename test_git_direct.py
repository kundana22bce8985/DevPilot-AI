
import asyncio
import sys
import traceback
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import (
    StdioServerParameters,
    stdio_client,
)

# DevPilot project directory
BASE_DIR = Path(__file__).resolve().parent

# Git MCP server file
SERVER_FILE = (
    BASE_DIR / "mcp_servers" / "git_server.py"
)


async def main():

    # Configure Git MCP server
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_FILE)],
        cwd=str(BASE_DIR),
    )

    print("Starting Git MCP server...", flush=True)

    async with stdio_client(params) as (read, write):

        async with ClientSession(read, write) as session:

            # Initialize MCP connection
            await asyncio.wait_for(
                session.initialize(),
                timeout=15,
            )

            print(
                "MCP connected successfully!",
                flush=True,
            )

            # List available tools
            tools = await session.list_tools()

            print("\nAvailable tools:")

            tool_names = []

            for tool in tools.tools:
                print("-", tool.name)
                tool_names.append(tool.name)

            # Check git_status tool
            if "git_status" not in tool_names:
                print(
                    "\nERROR: git_status tool is missing."
                )
                return

            # Call git_status
            print(
                "\nCalling git_status...",
                flush=True,
            )

            try:
                result = await asyncio.wait_for(
                    session.call_tool(
                        "git_status",
                        arguments={
                            "project_path": str(BASE_DIR)
                        },
                    ),
                    timeout=20,
                )

                print(
                    "\nGIT STATUS RESULT:",
                    flush=True,
                )

                print("Is error:", result.isError)

                for item in result.content:
                    if hasattr(item, "text"):
                        print(item.text)
                    else:
                        print(item)

            except asyncio.TimeoutError:
                print(
                    "\nERROR: git_status timed out.",
                    flush=True,
                )

            except Exception as error:
                print(
                    "\nORIGINAL TOOL ERROR:",
                    repr(error),
                    flush=True,
                )

                traceback.print_exc()

            print(
                "\nMCP test completed.",
                flush=True,
            )


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except BaseException as error:
        print(
            "\nMCP SESSION ERROR:",
            repr(error),
        )

        traceback.print_exception(error)
