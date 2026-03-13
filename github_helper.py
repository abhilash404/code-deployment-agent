# github_helper.py
import httpx
import base64
import os
import time

TOKEN = os.environ.get("GITHUB_TOKEN")
USER = os.environ.get("GITHUB_USER")

HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def create_repo(repo_name: str) -> dict:
    """Create a public GitHub repo, return repo info"""
    response = httpx.post(
        "https://api.github.com/user/repos",
        headers=HEADERS,
        json={
            "name": repo_name,
            "private": False,
            "auto_init": True
        }
    )
    return response.json()

def push_file(repo_name: str, file_path: str, 
              content: str, message: str):
    """Push a file to the repo"""
    # GitHub API requires content to be base64 encoded
    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("utf-8")
    
    # check if file already exists (needed for updates)
    check = httpx.get(
        f"https://api.github.com/repos/{USER}/{repo_name}/contents/{file_path}",
        headers=HEADERS
    )
    
    payload = {
        "message": message,
        "content": encoded,
    }
    
    # if file exists, include its sha so GitHub lets you update it
    if check.status_code == 200:
        payload["sha"] = check.json()["sha"]
    
    response = httpx.put(
        f"https://api.github.com/repos/{USER}/{repo_name}/contents/{file_path}",
        headers=HEADERS,
        json=payload
    )
    return response.json()

def enable_pages(repo_name: str):
    """Enable GitHub Pages on main branch"""
    response = httpx.post(
        f"https://api.github.com/repos/{USER}/{repo_name}/pages",
        headers=HEADERS,
        json={"source": {"branch": "main", "path": "/"}}
    )
    return response.json()

def get_latest_commit(repo_name: str) -> str:
    """Get the latest commit SHA"""
    response = httpx.get(
        f"https://api.github.com/repos/{USER}/{repo_name}/commits/main",
        headers=HEADERS
    )
    return response.json()["sha"]

def get_pages_url(repo_name: str) -> str:
    """Get the GitHub Pages URL once it's ready"""
    # pages take 1-2 minutes to activate, poll until ready
    for attempt in range(10):
        response = httpx.get(
            f"https://api.github.com/repos/{USER}/{repo_name}/pages",
            headers=HEADERS
        )
        if response.status_code == 200:
            return response.json().get("html_url", "")
        time.sleep(15)  # wait 15 seconds between attempts
    return f"https://{USER}.github.io/{repo_name}/"