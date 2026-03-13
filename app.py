# app.py
import os
import time
import json
import httpx
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

from github_helper import (create_repo, push_file, enable_pages,
                            get_latest_commit, get_pages_url)
from llm_helper import (generate_app, generate_readme,
                        generate_app_revision, MIT_LICENSE)

app = FastAPI()

SECRET = os.environ.get("MY_SECRET", "mysecret")
GITHUB_USER = os.environ.get("GITHUB_USER")

# simple file-based storage for round 2
# stores {task_id: repo_name}
TASK_STORE = "task_store.json"

def load_store() -> dict:
    if os.path.exists(TASK_STORE):
        return json.load(open(TASK_STORE))
    return {}

def save_store(data: dict):
    json.dump(data, open(TASK_STORE, "w"))

class TaskRequest(BaseModel):
    email: str
    secret: str
    task: str
    round: int
    nonce: str
    brief: str
    checks: list[str] = []
    evaluation_url: str
    attachments: list[dict] = []

def post_to_evaluation(eval_url: str, payload: dict):
    """Post results with exponential backoff retry"""
    delay = 1
    for attempt in range(5):
        try:
            r = httpx.post(eval_url, json=payload, timeout=10)
            if r.status_code == 200:
                print(f"Evaluation posted successfully")
                return True
        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
        time.sleep(delay)
        delay *= 2
    return False

def process_round1(payload: TaskRequest):
    """Full pipeline: generate → deploy → notify"""
    print(f"Starting round 1 for task: {payload.task}")
    
    try:
        # 1. generate the app
        print("Generating app with Gemini...")
        app_code = generate_app(
            payload.brief, 
            payload.checks, 
            payload.attachments
        )
        
        # 2. generate readme
        readme = generate_readme(
            payload.brief, 
            payload.task, 
            app_code
        )
        
        # 3. create github repo
        repo_name = payload.task.replace("/", "-")[:50]
        print(f"Creating repo: {repo_name}")
        create_repo(repo_name)
        time.sleep(3)  # wait for repo to initialize
        
        # 4. push files
        push_file(repo_name, "index.html", app_code, 
                  "Add generated app")
        push_file(repo_name, "README.md", readme, 
                  "Add README")
        push_file(repo_name, "LICENSE", 
                  MIT_LICENSE.format(user=GITHUB_USER), 
                  "Add MIT license")
        
        # 5. enable github pages
        enable_pages(repo_name)
        
        # 6. get commit sha and pages url
        commit_sha = get_latest_commit(repo_name)
        pages_url = get_pages_url(repo_name)
        repo_url = f"https://github.com/{GITHUB_USER}/{repo_name}"
        
        # 7. save to store for round 2
        store = load_store()
        store[payload.task] = repo_name
        save_store(store)
        
        # 8. post to evaluation url
        eval_payload = {
            "email": payload.email,
            "task": payload.task,
            "round": payload.round,
            "nonce": payload.nonce,
            "repo_url": repo_url,
            "commit_sha": commit_sha,
            "pages_url": pages_url
        }
        post_to_evaluation(payload.evaluation_url, eval_payload)
        print(f"Round 1 complete: {pages_url}")
        
    except Exception as e:
        print(f"Round 1 failed: {e}")

def process_round2(payload: TaskRequest):
    """Revise existing repo based on new brief"""
    print(f"Starting round 2 for task: {payload.task}")
    
    try:
        # get existing repo name from store
        store = load_store()
        repo_name = store.get(payload.task)
        
        if not repo_name:
            print(f"No repo found for task {payload.task}")
            return
        
        # get existing code
        import httpx as _httpx
        TOKEN = os.environ.get("GITHUB_TOKEN")
        r = _httpx.get(
            f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}/contents/index.html",
            headers={"Authorization": f"token {TOKEN}"}
        )
        import base64
        existing_code = base64.b64decode(
            r.json()["content"]
        ).decode("utf-8")
        
        # revise with gemini
        revised_code = generate_app_revision(
            payload.brief,
            payload.checks,
            payload.attachments,
            existing_code
        )
        
        # update readme too
        new_readme = generate_readme(
            payload.brief, payload.task, revised_code
        )
        
        # push updates
        push_file(repo_name, "index.html", revised_code,
                  "Revise app for round 2")
        push_file(repo_name, "README.md", new_readme,
                  "Update README for round 2")
        
        # get new commit sha
        commit_sha = get_latest_commit(repo_name)
        pages_url = get_pages_url(repo_name)
        repo_url = f"https://github.com/{GITHUB_USER}/{repo_name}"
        
        # post to evaluation
        eval_payload = {
            "email": payload.email,
            "task": payload.task,
            "round": payload.round,
            "nonce": payload.nonce,
            "repo_url": repo_url,
            "commit_sha": commit_sha,
            "pages_url": pages_url
        }
        post_to_evaluation(payload.evaluation_url, eval_payload)
        print(f"Round 2 complete: {pages_url}")
        
    except Exception as e:
        print(f"Round 2 failed: {e}")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/api")
def handle(payload: TaskRequest, bt: BackgroundTasks):
    if payload.secret != SECRET:
        raise HTTPException(
            status_code=401, 
            detail="invalid secret"
        )
    
    # route to correct handler based on round
    if payload.round == 1:
        bt.add_task(process_round1, payload)
    else:
        bt.add_task(process_round2, payload)
    
    return {"status": "accepted"}