
from typing import TypedDict
from pathlib import Path

from langgraph.graph import StateGraph, START, END

from agents.planner import planner_agent
from agents.coder import coder_agent
from agents.reviewer import reviewer_agent

from tools.code_search import build_code_context


# ==========================================
# STEP 1: SHARED STATE
# ==========================================

class DevPilotState(TypedDict):
    issue: str
    project_path: str
    code_context: str
    plan: str
    solution: str
    review: str


# ==========================================
# STEP 2: RETRIEVER NODE
# ==========================================

def retrieval_node(state: DevPilotState):

    print("\nRetrieving relevant code from pgvector...")

    project_path = state.get("project_path", "").strip()

    if not project_path:
        print("No project path provided.")
        return {"code_context": "No repository selected."}

    context = build_code_context(
        state["issue"],
        project_path
    )

    print("Relevant code retrieved successfully!")

    return {"code_context": context}


# ==========================================
# STEP 3: PLANNER AGENT
# ==========================================

def planning_node(state: DevPilotState):

    print("\nPlanner Agent is analyzing the issue...")

    issue_with_context = (
        f"USER ISSUE:\n{state['issue']}\n\n"
        f"RETRIEVED REPOSITORY CODE:\n"
        f"{state['code_context']}\n\n"
        "Analyze the issue using the repository code. "
        "Identify possible causes and prepare a plan. "
        "Do not assume retrieved code is necessarily faulty."
    )

    plan = planner_agent(issue_with_context)

    return {"plan": plan}


# ==========================================
# STEP 4: CODER AGENT
# ==========================================

def coding_node(state: DevPilotState):

    print("\nCoder Agent is generating a solution...")

    issue_with_context = (
        f"USER ISSUE:\n{state['issue']}\n\n"
        f"RETRIEVED REPOSITORY CODE:\n"
        f"{state['code_context']}\n\n"
        "Suggest a fix based on the available code. "
        "Do not invent missing files or functions."
    )

    solution = coder_agent(
        issue_with_context,
        state["plan"]
    )

    return {"solution": solution}


# ==========================================
# STEP 5: REVIEWER AGENT
# ==========================================

def reviewing_node(state: DevPilotState):

    print("\nReviewer Agent is checking the solution...")

    issue_with_context = (
        f"USER ISSUE:\n{state['issue']}\n\n"
        f"RETRIEVED REPOSITORY CODE:\n"
        f"{state['code_context']}\n\n"
        "Review the proposed solution against the "
        "retrieved code. Mention possible risks and "
        "tests needed to verify the fix."
    )

    review = reviewer_agent(
        issue_with_context,
        state["plan"],
        state["solution"]
    )

    return {"review": review}


# ==========================================
# STEP 6: CREATE LANGGRAPH WORKFLOW
# ==========================================

workflow = StateGraph(DevPilotState)

workflow.add_node("retriever", retrieval_node)
workflow.add_node("planner", planning_node)
workflow.add_node("coder", coding_node)
workflow.add_node("reviewer", reviewing_node)

workflow.add_edge(START, "retriever")
workflow.add_edge("retriever", "planner")
workflow.add_edge("planner", "coder")
workflow.add_edge("coder", "reviewer")
workflow.add_edge("reviewer", END)

app = workflow.compile()


# ==========================================
# STEP 7: RUN DEVPILOT
# ==========================================

if __name__ == "__main__":

    print("\n===== DEVPILOT AI ASSISTANT =====")

    project_path = input(
        "\nEnter indexed project folder path: "
    ).strip().strip('"')

    issue = input(
        "\nEnter your coding problem: "
    ).strip()

    if not issue:
        print("Please enter a coding problem.")
        raise SystemExit(1)

    if not Path(project_path).is_dir():
        print("Project folder not found.")
        raise SystemExit(1)

    try:
        result = app.invoke({
            "issue": issue,
            "project_path": project_path,
            "code_context": "",
            "plan": "",
            "solution": "",
            "review": ""
        })

        print("\n===== RETRIEVED CODE =====\n")
        print(result["code_context"])

        print("\n===== PLANNER AGENT OUTPUT =====\n")
        print(result["plan"])

        print("\n===== CODER AGENT OUTPUT =====\n")
        print(result["solution"])

        print("\n===== REVIEWER AGENT OUTPUT =====\n")
        print(result["review"])

        print("\n===== DEVPILOT COMPLETED =====")

    except Exception as error:
        print("\nError:", error)
