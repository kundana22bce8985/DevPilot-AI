
import asyncio
import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from tools.mcp_client import get_mcp_tools


class MCPState(TypedDict):
    project_path: str
    files: list[str]
    code: str
    git_status: str
    test_results: str


def extract_text(result):
    """Convert MCP output into readable text."""

    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        if "content" in result:
            return extract_text(result["content"])

        if "text" in result:
            return extract_text(result["text"])

        return json.dumps(result, indent=2)

    if isinstance(result, list):
        return "\n".join(
            extract_text(item)
            for item in result
        )

    return str(result)


def extract_files(result):
    """Convert MCP output into a list of filenames."""

    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return [result]

        return extract_files(parsed)

    if isinstance(result, dict):
        if "result" in result:
            return extract_files(result["result"])

        if "content" in result:
            return extract_files(result["content"])

        if "text" in result:
            return extract_files(result["text"])

        raise ValueError(
            f"Unexpected MCP file response: {result}"
        )

    if isinstance(result, list):
        files = []

        for item in result:
            files.extend(extract_files(item))

        return files

    raise ValueError(
        f"Unsupported MCP result: {type(result)}"
    )


def get_tool(tools, name):
    """Find an MCP tool by name."""

    for tool in tools:
        if tool.name == name:
            return tool

    raise ValueError(
        f"MCP tool not found: {name}"
    )


async def invoke_tool(tool, arguments):
    """Execute an MCP tool and check for errors."""

    result = await tool.ainvoke(arguments)
    text = extract_text(result)

    if text.startswith("Error executing tool"):
        raise RuntimeError(text)

    return result


async def list_files_agent(state: MCPState):
    """Find Python files through Code Search MCP."""

    tools = await get_mcp_tools()

    tool = get_tool(tools, "list_python_files")

    result = await invoke_tool(
        tool,
        {
            "project_path": state["project_path"]
        }
    )

    files = extract_files(result)

    return {"files": files}


async def read_code_agent(state: MCPState):
    """Read Python source code through MCP."""

    files = state["files"]

    if not files:
        return {"code": "No Python files found."}

    filename = (
        "calculator.py"
        if "calculator.py" in files
        else files[0]
    )

    tools = await get_mcp_tools()

    tool = get_tool(tools, "read_python_file")

    result = await invoke_tool(
        tool,
        {
            "project_path": state["project_path"],
            "relative_path": filename
        }
    )

    return {"code": extract_text(result)}


async def git_agent(state: MCPState):
    """Check repository status through Git MCP."""

    tools = await get_mcp_tools()

    tool = get_tool(tools, "git_status")

    result = await invoke_tool(
        tool,
        {
            "project_path": state["project_path"]
        }
    )

    return {
        "git_status": extract_text(result)
    }


async def test_agent(state: MCPState):
    """Run Python tests through Test Runner MCP."""

    tools = await get_mcp_tools()

    tool = get_tool(tools, "run_project_tests")

    result = await invoke_tool(
        tool,
        {
            "project_path": state["project_path"]
        }
    )

    return {
        "test_results": extract_text(result)
    }


async def main():

    workflow = StateGraph(MCPState)

    workflow.add_node(
        "list_files",
        list_files_agent
    )

    workflow.add_node(
        "read_code",
        read_code_agent
    )

    workflow.add_node(
        "git_status",
        git_agent
    )

    workflow.add_node(
        "run_tests",
        test_agent
    )

    workflow.add_edge(START, "list_files")
    workflow.add_edge("list_files", "read_code")
    workflow.add_edge("read_code", "git_status")
    workflow.add_edge("git_status", "run_tests")
    workflow.add_edge("run_tests", END)

    app = workflow.compile()

    project = Path(r"D:\DevPilot\bug_demo")

    result = await app.ainvoke({
        "project_path": str(project),
        "files": [],
        "code": "",
        "git_status": "",
        "test_results": ""
    })

    print("\n" + "=" * 50)
    print("DEV PILOT MCP + LANGGRAPH")
    print("=" * 50)

    print("\nPYTHON FILES:")
    print(result["files"])

    print("\nSOURCE CODE:")
    print(result["code"])

    print("\nGIT STATUS:")
    print(result["git_status"])

    print("\nTEST RESULTS:")
    print(result["test_results"])

    print("\nWorkflow completed!")


if __name__ == "__main__":
    asyncio.run(main())
