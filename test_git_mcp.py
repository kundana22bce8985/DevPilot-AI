
import asyncio
from tools.mcp_client import get_mcp_tools


async def main():
    print("Connecting to Git MCP...")

    tools = await get_mcp_tools()

    git_tool = next(
        tool for tool in tools
        if tool.name == "git_status"
    )

    print("Calling git_status...")

    result = await asyncio.wait_for(
        git_tool.ainvoke({
            "project_path": r"D:\DevPilot"
        }),
        timeout=20
    )

    print("GIT STATUS:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
