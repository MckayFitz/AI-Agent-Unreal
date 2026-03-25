import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

from app.file_indexer import scan_project
from app.code_reader import search_files
from app.prompts import SYSTEM_PROMPT

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
env_path = os.path.join(BASE_DIR, ".env")

load_dotenv(dotenv_path=env_path)

app = FastAPI()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app.mount("/static", StaticFiles(directory="static"), name="static")

PROJECT_CACHE = {
    "project_path": None,
    "files": []
}


class ScanRequest(BaseModel):
    project_path: str


class AskRequest(BaseModel):
    question: str


class ErrorRequest(BaseModel):
    error_text: str


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/status")
def status():
    return {
        "project_path": PROJECT_CACHE["project_path"],
        "file_count": len(PROJECT_CACHE["files"]),
        "api_key_configured": bool(os.getenv("OPENAI_API_KEY"))
    }


@app.post("/scan-project")
def scan_project_endpoint(request: ScanRequest):
    project_path = request.project_path.strip()
    if not project_path:
        return {"error": "Project path is required."}

    result = scan_project(project_path)

    if "error" in result:
        return result

    PROJECT_CACHE["project_path"] = result["project_path"]
    PROJECT_CACHE["files"] = result["files"]

    return {
        "message": "Project scanned successfully.",
        "project_path": result["project_path"],
        "file_count": result["file_count"]
    }


@app.post("/analyze-error")
def analyze_error(request: ErrorRequest):
    error_text = request.error_text.strip()

    if not error_text:
        return {"analysis": "Paste a UE5 or Visual Studio compile/build error first."}

    if not os.getenv("OPENAI_API_KEY"):
        return {"analysis": "OPENAI_API_KEY is not configured yet."}

    error_prompt = f"""
You are a UE5 C++ debugging assistant.

The user pasted a build/compile/runtime error from Unreal Engine or Visual Studio.

Your job:
- Explain the error in simple terms
- Identify the most likely cause
- Mention the likely file/class/module involved if visible
- Suggest specific steps to fix it
- If the log is incomplete, say what extra part of the log would help

Error log:
{error_text}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "You are a practical Unreal Engine 5 debugging assistant."},
            {"role": "user", "content": error_prompt}
        ]
    )

    analysis = response.choices[0].message.content

    return {"analysis": analysis}


@app.post("/ask")
def ask_question(request: AskRequest):
    question = request.question.strip()
    if not question:
        return {"answer": "Ask a question about the scanned UE5 project."}

    files = PROJECT_CACHE["files"]

    if not files:
        return {"answer": "No project has been scanned yet."}

    if not os.getenv("OPENAI_API_KEY"):
        return {
            "answer": "OPENAI_API_KEY is not configured yet.",
            "matches": []
        }

    matches = search_files(files, question, max_results=5)

    context_text = "\n\n".join(
        f"FILE: {match['path']}\nSNIPPET:\n{match['snippet']}"
        for match in matches
    )

    if not context_text:
        context_text = "No directly matching file snippets were found."

    user_prompt = f"""
User question:
{question}

Relevant project context:
{context_text}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
    )

    answer = response.choices[0].message.content

    return {
        "answer": answer,
        "matches": matches,
        "project_path": PROJECT_CACHE["project_path"]
    }