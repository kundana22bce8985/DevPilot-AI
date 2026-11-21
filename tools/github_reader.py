
import requests
from urllib.parse import urlparse

MAX_FILES = 15
MAX_CHARS = 20000

def read_github_repo(repo_url):
    parsed = urlparse(repo_url.strip())

    if parsed.scheme != "https":
        raise ValueError("Use an HTTPS GitHub URL.")

    if parsed.hostname != "github.com":
        raise ValueError("Only github.com URLs are supported.")

    parts = parsed.path.strip("/").split("/")

    if len(parts) != 2:
        raise ValueError(
            "Use a repository URL like "
            "https://github.com/owner/repository"
        )

    owner, repo = parts
    repo = repo.removesuffix(".git")

    if not owner or not repo:
        raise ValueError("Invalid repository URL.")

    api_url = (
        f"https://api.github.com/repos/{owner}/{repo}"
    )

    response = requests.get(api_url, timeout=15)
    response.raise_for_status()

    repo_info = response.json()
    branch = repo_info["default_branch"]

    tree_url = (
        f"https://api.github.com/repos/"
        f"{owner}/{repo}/git/trees/{branch}"
    )

    response = requests.get(
        tree_url,
        params={"recursive": 1},
        timeout=20
    )
    response.raise_for_status()

    tree = response.json()

    if tree.get("truncated"):
        raise ValueError(
            "Repository is too large for this reader."
        )

    files = []
    total_chars = 0

    for item in tree.get("tree", []):

        if len(files) >= MAX_FILES:
            break

        if item.get("type") != "blob":
            continue

        path = item["path"]

        if not path.endswith(".py"):
            continue

        if item.get("size", 0) > 50000:
            continue

        if any(
            part in {
                ".venv", "venv", "tests",
                "__pycache__", "node_modules"
            }
            for part in path.split("/")
        ):
            continue

        raw_url = (
            f"https://raw.githubusercontent.com/"
            f"{owner}/{repo}/{branch}/{path}"
        )

        file_response = requests.get(
            raw_url,
            timeout=15
        )
        file_response.raise_for_status()

        content = file_response.text

        remaining = MAX_CHARS - total_chars

        if remaining <= 0:
            break

        content = content[:remaining]
        total_chars += len(content)

        files.append(
            f"FILE: {path}\n"
            f"```python\n{content}\n```"
        )

    if not files:
        raise ValueError(
            "No readable Python files found."
        )

    return "\n\n".join(files)


if __name__ == "__main__":
    url = input("Enter GitHub repository URL: ")

    try:
        result = read_github_repo(url)
        print(result)
    except Exception as error:
        print("Error:", error)
