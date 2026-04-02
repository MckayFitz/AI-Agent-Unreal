import os
import re
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

from app.file_indexer import scan_project
from app.asset_actions import run_asset_action
from app.code_reader import search_files
from app.plugin_routes import build_plugin_router
from app.search_index import build_search_index
from app.prompts import (
    CRASH_LOG_SYSTEM_PROMPT,
    DEEP_ASSET_ANALYSIS_SYSTEM_PROMPT,
    FILE_EXPLAIN_SUMMARY_PROMPT,
    FILE_EXPLAIN_SYSTEM_PROMPT,
    OUTPUT_LOG_SYSTEM_PROMPT,
    SPECIALIZED_FAMILY_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    TASK_WORKFLOW_SYSTEM_PROMPT,
)
from app.ue_analysis import (
    analyze_reflection_text,
    build_file_explanation,
    build_asset_details,
    build_folder_summary,
    build_project_analysis,
    build_dependency_map,
    explain_blueprint_nodes,
    find_matching_assets,
    find_references,
    generate_code_suggestions,
    summarize_specialized_assets,
    build_task_workflow,
)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
env_path = os.path.join(BASE_DIR, ".env")

load_dotenv(dotenv_path=env_path)

app = FastAPI()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app.mount("/static", StaticFiles(directory="static"), name="static")

PROJECT_CACHE = {
    "project_path": None,
    "files": [],
    "assets": [],
    "analysis": None,
    "conversation_history": [],
    "current_focus": None,
    "search_index": None,
}


class ScanRequest(BaseModel):
    project_path: str


class AskRequest(BaseModel):
    question: str


class ErrorRequest(BaseModel):
    error_text: str


class ReferenceRequest(BaseModel):
    symbol: str


class FileRequest(BaseModel):
    path: str
    mode: str = "beginner"


class BlueprintLinkRequest(BaseModel):
    class_name: str


class SelectionRequest(BaseModel):
    selection: str


class BlueprintNodeRequest(BaseModel):
    nodes_text: str


class FolderRequest(BaseModel):
    folder_path: str


class TextRequest(BaseModel):
    text: str


class ReflectionRequest(BaseModel):
    path: str | None = None
    text: str | None = None


class TaskRequest(BaseModel):
    goal: str


class AssetFamilyRequest(BaseModel):
    family: str


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/status")
def status():
    return {
        "project_path": PROJECT_CACHE["project_path"],
        "file_count": len(PROJECT_CACHE["files"]),
        "asset_count": len(PROJECT_CACHE["assets"]),
        "indexed_terms": len((PROJECT_CACHE["search_index"] or {}).get("postings", {})),
        "api_key_configured": bool(os.getenv("OPENAI_API_KEY"))
    }


@app.post("/scan-project")
def scan_project_endpoint(request: ScanRequest):
    project_path = request.project_path.strip()
    if not project_path:
        return {"error": "Project path is required."}

    try:
        result = scan_project(project_path)

        if "error" in result:
            return result

        PROJECT_CACHE["project_path"] = result["project_path"]
        PROJECT_CACHE["files"] = result["files"]
        PROJECT_CACHE["assets"] = result["asset_files"]
        PROJECT_CACHE["analysis"] = build_project_analysis(result["files"], result["asset_files"])
        PROJECT_CACHE["search_index"] = build_search_index(PROJECT_CACHE["analysis"]["files"])
        PROJECT_CACHE["conversation_history"] = []
        PROJECT_CACHE["current_focus"] = None

        return {
            "message": "Project scanned successfully.",
            "project_path": result["project_path"],
            "file_count": result["file_count"],
            "asset_count": len(result["asset_files"]),
            "loaded_count": result["loaded_count"],
            "total_files_seen": result["total_files_seen"],
            "skipped_generated_count": result["skipped_generated_count"],
            "skipped_binary_count": result["skipped_binary_count"],
            "skipped_unknown_count": result["skipped_unknown_count"],
            "skipped_large_count": result["skipped_large_count"],
            "unreadable_count": result["unreadable_count"],
            "loaded_files": result["loaded_files"],
            "top_extensions": result["top_extensions"],
        }
    except Exception as exc:
        return {"error": f"Scan failed: {exc}"}


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

    matches = search_files(files, question, max_results=5, index_data=PROJECT_CACHE["search_index"])

    context_text = "\n\n".join(
        f"FILE: {match['path']}\nSNIPPET:\n{match['snippet']}"
        for match in matches
    )

    if not context_text:
        context_text = "No directly matching file snippets were found."

    user_prompt = f"""
User question:
{question}

Recent context:
{format_recent_history()}

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
    remember_interaction(question, answer)

    return {
        "answer": answer,
        "matches": matches,
        "project_path": PROJECT_CACHE["project_path"]
    }


@app.post("/task-workflow")
def task_workflow(request: TaskRequest):
    goal = request.goal.strip()
    if not goal:
        return {"error": "Describe the task first."}

    analyzed_files = get_analyzed_files()
    if not analyzed_files:
        return {"error": "No project has been scanned yet."}

    matches = search_files(analyzed_files, goal, max_results=8, index_data=PROJECT_CACHE["search_index"])
    scoped_files = []
    for match in matches:
        file_record = find_file_record(match["path"])
        if file_record:
            scoped_files.append(file_record)

    workflow = build_task_workflow(goal, scoped_files)
    if os.getenv("OPENAI_API_KEY") and scoped_files:
        workflow["ai_plan"] = summarize_task_with_llm(goal, scoped_files, workflow)

    remember_interaction(goal, workflow.get("ai_plan") or workflow["summary"])
    return workflow


@app.post("/references")
def references(request: ReferenceRequest):
    symbol = request.symbol.strip()
    if not symbol:
        return {"error": "Enter a class, function, variable, macro, or asset name."}

    analyzed_files = get_analyzed_files()
    if not analyzed_files:
        return {"error": "No project has been scanned yet."}

    result = find_references(analyzed_files, symbol)
    asset_matches = [
        asset for asset in PROJECT_CACHE["assets"]
        if symbol.lower() in asset["name"].lower() or symbol.lower() in asset["path"].lower()
    ]
    return {"symbol": symbol, "asset_matches": asset_matches[:12], **result}


@app.post("/explain-file")
def explain_file(request: FileRequest):
    file_record = find_file_record(request.path)
    if not file_record:
        return {"error": "That file was not found in the scanned project cache."}

    explanation = build_file_explanation(file_record, mode=request.mode.strip().lower() or "beginner")

    if os.getenv("OPENAI_API_KEY"):
        llm_summary = summarize_file_with_llm(file_record, explanation, request.mode)
        explanation["llm_summary"] = llm_summary

    PROJECT_CACHE["current_focus"] = file_record["path"]
    return explanation


@app.post("/review-file")
def review_file(request: FileRequest):
    file_record = find_file_record(request.path)
    if not file_record:
        return {"error": "That file was not found in the scanned project cache."}

    return {
        "path": file_record["path"],
        "suggestions": generate_code_suggestions(file_record),
        "explanation": build_file_explanation(file_record, mode="refactor"),
    }


@app.post("/blueprint-links")
def blueprint_links(request: BlueprintLinkRequest):
    return run_asset_action(
        "blueprint_links",
        analysis=PROJECT_CACHE["analysis"],
        class_name=request.class_name,
    )


@app.get("/architecture-map")
def architecture_map():
    analysis = PROJECT_CACHE["analysis"]
    if not analysis:
        return {"error": "No project has been scanned yet."}
    return analysis["architecture"]


@app.get("/dependency-map")
def dependency_map():
    analyzed_files = get_analyzed_files()
    if not analyzed_files:
        return {"error": "No project has been scanned yet."}
    return build_dependency_map(analyzed_files)


@app.post("/folder-explainer")
def folder_explainer(request: FolderRequest):
    analyzed_files = get_analyzed_files()
    if not analyzed_files:
        return {"error": "No project has been scanned yet."}
    folder_path = request.folder_path.strip()
    if not folder_path:
        return {"error": "Enter a folder path first."}
    return build_folder_summary(analyzed_files, folder_path)


@app.get("/blueprint-awareness")
def blueprint_awareness():
    analysis = PROJECT_CACHE["analysis"]
    if not analysis:
        return {"error": "No project has been scanned yet."}

    asset_families = {}
    for asset in analysis["assets"]:
        asset_families.setdefault(asset["family"], []).append(asset)

    return {
        "families": {
            family: assets[:10]
            for family, assets in asset_families.items()
        }
    }


@app.get("/specialized-assets")
def specialized_assets():
    analysis = PROJECT_CACHE["analysis"]
    if not analysis:
        return {"error": "No project has been scanned yet."}
    return summarize_specialized_assets(analysis["files"], analysis["assets"])


@app.post("/specialized-assets/family")
def specialized_asset_family(request: AssetFamilyRequest):
    return run_asset_action(
        "specialized_asset_family",
        analysis=PROJECT_CACHE["analysis"],
        family=request.family,
        include_ai_summary=bool(os.getenv("OPENAI_API_KEY")),
        summarize_with_llm=summarize_specialized_family_with_llm,
    )


@app.post("/selection-analysis")
def selection_analysis(request: SelectionRequest):
    selection = request.selection.strip()
    if not selection:
        return {"error": "Enter a currently selected file, class, or asset name."}

    file_record = find_file_record(selection)
    if file_record:
        return {
            "selection": selection,
            "selection_type": "file",
            "explanation": build_file_explanation(file_record, mode="technical"),
            "suggestions": generate_code_suggestions(file_record),
        }

    analysis = PROJECT_CACHE["analysis"]
    if not analysis:
        return {"error": "No project has been scanned yet."}

    asset_matches = find_matching_assets(analysis["assets"], selection, limit=8)
    if asset_matches and asset_matches[0].get("match_score", 0) >= 8:
        summaries = summarize_specialized_assets(analysis["files"], analysis["assets"])
        asset_detail = build_asset_details(
            selection=selection,
            asset=asset_matches[0],
            files=analysis["files"],
            assets=analysis["assets"],
            blueprint_links=analysis["blueprint_links"],
            family_summaries=summaries,
        )
        asset_detail["selection"] = selection
        asset_detail["selection_type"] = "asset"
        asset_detail["asset_matches"] = asset_matches[:8]
        return asset_detail

    reference_result = find_references(get_analyzed_files(), selection, max_results=8)
    blueprint_result = []
    for item in analysis["blueprint_links"]:
        if selection.lower() in item["class_name"].lower():
            blueprint_result.append(item)

    return {
        "selection": selection,
        "selection_type": "symbol_or_asset",
        "references": reference_result,
        "blueprint_links": blueprint_result,
        "assets": asset_matches[:8],
    }


@app.post("/explain-blueprint-nodes")
def explain_nodes(request: BlueprintNodeRequest):
    nodes_text = request.nodes_text.strip()
    if not nodes_text:
        return {"error": "Paste copied Blueprint node text first."}
    return explain_blueprint_nodes(nodes_text)


@app.post("/reflection-analyzer")
def reflection_analyzer(request: ReflectionRequest):
    text = (request.text or "").strip()
    if not text and request.path:
        file_record = find_file_record(request.path)
        if not file_record:
            return {"error": "That file was not found in the scanned project cache."}
        text = file_record.get("content", "")
    if not text:
        return {"error": "Provide a file path or paste Unreal reflection code first."}
    return analyze_reflection_text(text)


@app.post("/analyze-crash-log")
def analyze_crash_log(request: TextRequest):
    text = request.text.strip()
    if not text:
        return {"error": "Paste a crash log or stack trace first."}

    if not os.getenv("OPENAI_API_KEY"):
        return {"analysis": heuristic_log_summary(text, log_type="crash")}

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": CRASH_LOG_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
    )
    return {"analysis": response.choices[0].message.content}


@app.post("/analyze-output-log")
def analyze_output_log(request: TextRequest):
    text = request.text.strip()
    if not text:
        return {"error": "Paste a UE output log first."}

    if not os.getenv("OPENAI_API_KEY"):
        return {"analysis": heuristic_log_summary(text, log_type="output")}

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": OUTPUT_LOG_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
    )
    return {"analysis": response.choices[0].message.content}


def get_analyzed_files():
    analysis = PROJECT_CACHE["analysis"]
    if not analysis:
        return []
    return analysis["files"]


def find_file_record(path_or_name: str):
    needle = path_or_name.strip().lower()
    for file_record in get_analyzed_files():
        if file_record["path"].lower() == needle or file_record["name"].lower() == needle:
            return file_record
    for file_record in get_analyzed_files():
        if needle in file_record["path"].lower():
            return file_record
    return None


def summarize_file_with_llm(file_record, explanation, mode):
    content = file_record.get("content", "")
    chunks = chunk_text(content, chunk_size=7000, overlap=400)
    chunk_notes = []

    for index, chunk in enumerate(chunks, start=1):
        prompt = f"""
Mode: {mode}
Path: {file_record['path']}
Chunk {index} of {len(chunks)}
Heuristic explanation:
{explanation}

Code chunk:
{chunk}
"""
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": FILE_EXPLAIN_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
        chunk_notes.append(f"Chunk {index} notes:\n{response.choices[0].message.content}")

    consolidation_prompt = f"""
Mode: {mode}
Path: {file_record['path']}
Heuristic explanation:
{explanation}

Chunk notes:
{chr(10).join(chunk_notes)}
"""
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": FILE_EXPLAIN_SUMMARY_PROMPT},
            {"role": "user", "content": consolidation_prompt},
        ]
    )
    return response.choices[0].message.content


def summarize_task_with_llm(goal, scoped_files, workflow):
    context_blocks = []
    for file_record in scoped_files[:6]:
        snippet = file_record.get("content", "")[:3000]
        context_blocks.append(
            f"FILE: {file_record['path']}\nSYMBOLS: {', '.join(file_record['analysis']['all_symbol_names'][:8])}\nCODE:\n{snippet}"
        )

    prompt = f"""
Task goal:
{goal}

Recent context:
{format_recent_history()}

Heuristic workflow:
{workflow}

Relevant files:
{chr(10).join(context_blocks)}
"""
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": TASK_WORKFLOW_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
    )
    return response.choices[0].message.content


def summarize_specialized_family_with_llm(summary):
    prompt = f"""
Family:
{summary['title']}

Structured summary:
{summary}
"""
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": SPECIALIZED_FAMILY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
    )
    return response.choices[0].message.content


def summarize_deep_asset_with_llm(result, exported_text):
    prompt = f"""
Deep asset analysis request:
{result}

Exported text:
{exported_text[:16000]}
"""
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": DEEP_ASSET_ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
    )
    return response.choices[0].message.content


def build_data_asset_scaffold(name, purpose="", class_name=""):
    clean_name = sanitize_asset_name(name, "DA_")
    base_class = class_name or f"U{clean_name[3:]}DataAsset"
    header_path = f"Source/YourGame/Public/Data/{base_class}.h"

    header = f"""#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"
#include "{base_class}.generated.h"

UCLASS(BlueprintType)
class YOURGAME_API {base_class} : public UPrimaryDataAsset
{{
    GENERATED_BODY()

public:
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Config")
    FName Id = NAME_None;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Config")
    FText DisplayName;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Config")
    FString Description;
}};
"""

    steps = [
        f"Create the C++ class `{base_class}` and compile the project.",
        f"In Unreal, create a new Data Asset from `{base_class}` named `{clean_name}`.",
        "Fill in the exposed properties and assign the asset in the owning system or manager.",
        "Use soft references if the asset should stay decoupled from always-loaded gameplay code.",
    ]
    if purpose:
        steps.insert(2, f"Model the fields around this purpose: {purpose}")

    return {
        "asset_kind": "data_asset",
        "title": f"{clean_name} DataAsset Scaffold",
        "summary": "This scaffold gives you a safe starting point for a designer-editable gameplay data asset.",
        "recommended_asset_name": clean_name,
        "recommended_class_name": base_class,
        "recommended_asset_path": f"Content/Data/{clean_name}",
        "steps": steps,
        "files": [
            {
                "label": header_path,
                "language": "cpp",
                "content": header,
            }
        ],
    }


def build_blueprint_class_scaffold(name, purpose="", class_name=""):
    clean_name = sanitize_asset_name(name, "BP_")
    parent_class = class_name or infer_blueprint_parent_class(clean_name, purpose)
    variable_notes = infer_blueprint_variable_suggestions(clean_name, purpose)
    function_notes = infer_blueprint_function_suggestions(clean_name, purpose)

    outline = f"""Asset: {clean_name}
Type: Blueprint Class
Parent Class: {parent_class}
Purpose: {purpose or "Gameplay Blueprint class"}

Recommended starter variables:
{chr(10).join(f"- {item}" for item in variable_notes)}

Recommended starter events/functions:
{chr(10).join(f"- {item}" for item in function_notes)}
"""

    steps = [
        f"In Unreal, create a new Blueprint Class named `{clean_name}`.",
        f"Use `{parent_class}` as the parent class unless your project already has a better custom base type.",
        "Add only the variables and functions that establish the ownership boundary for this Blueprint.",
        "Keep reusable or performance-sensitive logic in C++ and reserve Blueprint for orchestration, tuning, and project-specific behavior.",
        "After creation, validate the spawn path, exposed defaults, and parent-class assumptions together.",
    ]

    return {
        "asset_kind": "blueprint_class",
        "title": f"{clean_name} Blueprint Class Scaffold",
        "summary": "This scaffold gives you a safe starter plan for a simple Blueprint gameplay class without attempting graph generation.",
        "recommended_asset_name": clean_name,
        "recommended_asset_path": f"Content/Blueprints/{clean_name}",
        "recommended_parent_class": parent_class,
        "steps": steps,
        "files": [
            {
                "label": "Blueprint Class Outline",
                "language": "text",
                "content": outline,
            }
        ],
    }


def build_input_action_scaffold(name, purpose=""):
    clean_name = sanitize_asset_name(name, "IA_")
    description = purpose or "Player input action"

    outline = f"""Asset: {clean_name}
Type: Input Action
Value Type: Boolean (change if this should be Axis1D/Axis2D/Axis3D)
Description: {description}

Recommended setup:
- Triggers: Pressed
- Modifiers: None by default
- Consume Input: Enabled
"""

    steps = [
        f"Create an Input Action asset named `{clean_name}` under `Content/Input/Actions`.",
        "Choose the smallest value type that matches the gameplay need.",
        "Add triggers/modifiers only when the raw input should be transformed at the asset level.",
        "Bind the action in the owning pawn, character, or controller and verify the mapping context is active.",
    ]

    return {
        "asset_kind": "input_action",
        "title": f"{clean_name} Input Action Scaffold",
        "summary": "This scaffold gives you a safe starter layout for a single Enhanced Input action.",
        "recommended_asset_name": clean_name,
        "recommended_asset_path": f"Content/Input/Actions/{clean_name}",
        "steps": steps,
        "files": [
            {
                "label": "Input Action Outline",
                "language": "text",
                "content": outline,
            }
        ],
    }


def build_input_mapping_context_scaffold(name, purpose=""):
    clean_name = sanitize_asset_name(name, "IMC_")
    description = purpose or "Gameplay mapping context"

    outline = f"""Asset: {clean_name}
Type: Input Mapping Context
Description: {description}

Recommended starter mappings:
- IA_Move -> W/A/S/D or Left Stick
- IA_Look -> Mouse Delta or Right Stick
- IA_Jump -> Space Bar / Gamepad Face Bottom
- IA_Interact -> E / Gamepad Face Right
"""

    steps = [
        f"Create an Input Mapping Context asset named `{clean_name}` under `Content/Input/Contexts`.",
        "Add only the actions needed for this gameplay layer so ownership stays clear.",
        "Apply the mapping context from the local-player subsystem at the right lifecycle moment.",
        "Set priority intentionally if this context overlaps with menus, vehicles, or temporary interaction modes.",
    ]

    return {
        "asset_kind": "input_mapping_context",
        "title": f"{clean_name} Input Mapping Context Scaffold",
        "summary": "This scaffold gives you a safe starter mapping context for Enhanced Input.",
        "recommended_asset_name": clean_name,
        "recommended_asset_path": f"Content/Input/Contexts/{clean_name}",
        "steps": steps,
        "files": [
            {
                "label": "Input Mapping Context Outline",
                "language": "text",
                "content": outline,
            }
        ],
    }


def build_material_scaffold(name, purpose=""):
    clean_name = sanitize_asset_name(name, "M_")
    description = purpose or "Gameplay-facing base material"

    outline = f"""Asset: {clean_name}
Type: Material
Purpose: {description}

Recommended starter parameters:
- BaseColorTint (Vector Parameter)
- Roughness (Scalar Parameter)
- Metallic (Scalar Parameter)
- NormalStrength (Scalar Parameter, only if needed)

Recommended starter graph shape:
- Base Color <- Vector Parameter or tinted texture sample
- Roughness <- Scalar Parameter
- Metallic <- Scalar Parameter
- Keep the first version cheap, readable, and easy to instance
"""

    steps = [
        f"Create a Material asset named `{clean_name}` under `Content/Materials`.",
        "Start with parameterized scalar/vector values so instances and gameplay code can tune the look later.",
        "Keep the first version visually simple before adding layered functions, switches, or runtime-heavy math.",
        "If only one actor variant needs tuning, consider pairing this with a Material Instance immediately after the base material exists.",
    ]

    return {
        "asset_kind": "material",
        "title": f"{clean_name} Material Scaffold",
        "summary": "This scaffold gives you a safe starter plan for a simple parameterized material.",
        "recommended_asset_name": clean_name,
        "recommended_asset_path": f"Content/Materials/{clean_name}",
        "steps": steps,
        "files": [
            {
                "label": "Material Outline",
                "language": "text",
                "content": outline,
            }
        ],
    }


def build_material_instance_scaffold(name, purpose="", class_name=""):
    clean_name = sanitize_asset_name(name, "MI_")
    parent_material = (class_name or "").strip() or "Choose an existing base material in Unreal"
    description = purpose or "Variant material instance for actor- or context-specific tuning"

    outline = f"""Asset: {clean_name}
Type: Material Instance
Purpose: {description}
Suggested Parent Material: {parent_material}

Recommended starter overrides:
- BaseColorTint
- Roughness
- Metallic
- EmissiveStrength (only if the base material exposes it)

Recommended usage:
- Keep the parent material stable and reusable
- Put actor- or context-specific visual tuning in the material instance
- Prefer a Material Instance over duplicating the whole base material
"""

    steps = [
        f"Create a Material Instance asset named `{clean_name}` under `Content/Materials/Instances`.",
        "Assign a stable parent material before tuning any overrides.",
        "Only override the parameters that differ from the shared base material.",
        "If runtime code writes the same parameter values dynamically, verify the editor override is still the right source of truth.",
    ]
    if class_name:
        steps.insert(1, f"Use `{class_name}` as the initial parent material if it matches the intended visual family.")

    return {
        "asset_kind": "material_instance",
        "title": f"{clean_name} Material Instance Scaffold",
        "summary": "This scaffold gives you a safe starter plan for a Material Instance that reuses a base material and exposes only the needed visual overrides.",
        "recommended_asset_name": clean_name,
        "recommended_asset_path": f"Content/Materials/Instances/{clean_name}",
        "recommended_parent_class": parent_material,
        "steps": steps,
        "files": [
            {
                "label": "Material Instance Outline",
                "language": "text",
                "content": outline,
            }
        ],
    }


def build_behavior_tree_scaffold(name, purpose=""):
    clean_name = sanitize_asset_name(name, "BT_")
    blackboard_name = sanitize_asset_name(name, "BB_")
    description = purpose or "AI decision flow"

    outline = f"""Asset: {clean_name}
Type: Behavior Tree
Purpose: {description}
Blackboard: {blackboard_name}

Recommended starter flow:
- Root
  - Selector
    - Sequence: Combat/Primary goal
    - Sequence: Chase or Move To target
    - Sequence: Patrol or Idle fallback

Recommended starter Blackboard keys:
- TargetActor (Object)
- TargetLocation (Vector)
- HasLineOfSight (Bool)
- IsAlerted (Bool)
"""

    steps = [
        f"Create a Blackboard asset named `{blackboard_name}` under `Content/AI` first.",
        f"Create a Behavior Tree asset named `{clean_name}` under `Content/AI` and attach `{blackboard_name}`.",
        "Start with one selector and a few small sequences before adding many decorators or services.",
        "Keep ownership clear by deciding which AIController, tasks, and Blackboard keys are responsible for each branch.",
    ]

    return {
        "asset_kind": "behavior_tree",
        "title": f"{clean_name} Behavior Tree Scaffold",
        "summary": "This scaffold gives you a safe starter plan for a simple Behavior Tree and Blackboard pair.",
        "recommended_asset_name": clean_name,
        "recommended_asset_path": f"Content/AI/{clean_name}",
        "steps": steps,
        "files": [
            {
                "label": "Behavior Tree Outline",
                "language": "text",
                "content": outline,
            }
        ],
    }


def sanitize_asset_name(name, prefix):
    raw = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name.strip())
    raw = "_".join(part for part in raw.split("_") if part)
    if not raw:
        raw = prefix.rstrip("_") + "_NewAsset"
    if not raw.lower().startswith(prefix.lower()):
        raw = f"{prefix}{raw}"
    return raw


def build_text_asset_scaffold(asset_kind, name, prefix, folder, title_suffix, purpose="", outline_lines=None, steps=None, extra=None):
    clean_name = sanitize_asset_name(name, prefix)
    outline = "\n".join(outline_lines or [])
    payload = {
        "asset_kind": asset_kind,
        "title": f"{clean_name} {title_suffix} Scaffold",
        "summary": f"This scaffold gives you a safe starter plan for a {title_suffix.lower()} asset.",
        "recommended_asset_name": clean_name,
        "recommended_asset_path": f"{folder}/{clean_name}",
        "steps": steps or [],
        "files": [
            {
                "label": f"{title_suffix} Outline",
                "language": "text",
                "content": outline,
            }
        ],
    }
    if extra:
        payload.update(extra)
    return payload


def build_generic_specialized_edit_plan(
    asset,
    change_request,
    details,
    *,
    asset_kind,
    summary_phrase,
    suggested_focus_name,
    suggested_focus_kind,
    fields_to_check,
    risks,
    validation_steps,
):
    asset_name = asset.get("name", "")
    asset_path = asset.get("path", "")
    owner = details.get("linked_cpp_classes", {}).get("primary_owner", "None")
    validation = list(validation_steps)
    if owner != "None":
        validation.insert(1, f"Inspect `{owner}` first, because it looks like the strongest runtime owner for this asset.")

    return {
        "asset_kind": asset_kind,
        "title": f"Edit Plan for {asset_name}",
        "summary": f"This is a controlled edit plan for {summary_phrase} in `{asset_name}` without guessing at runtime ownership or editor-side side effects.",
        "asset_name": asset_name,
        "asset_path": asset_path,
        "change_request": change_request,
        "linked_cpp_owner": owner,
        "suggested_node_kind": suggested_focus_kind,
        "suggested_node_name": suggested_focus_name,
        "what_to_change": [
            f"Requested change: {change_request}",
            f"Start with the smallest possible `{suggested_focus_kind}` change, using a focus like `{suggested_focus_name}`.",
            "Keep the change localized first so ownership stays obvious and validation stays cheap.",
            "Validate the runtime trigger path before widening the scope of the asset edit.",
        ],
        "fields_to_check": fields_to_check,
        "risks": risks[:5],
        "validation_steps": validation,
    }


def build_animbp_scaffold(name, purpose="", class_name=""):
    clean_name = sanitize_asset_name(name, "ABP_")
    parent_class = class_name or "AnimInstance"
    outline_lines = [
        f"Asset: {clean_name}",
        "Type: Animation Blueprint",
        f"Parent Class: {parent_class}",
        f"Purpose: {purpose or 'Character animation state machine'}",
        "",
        "Recommended starter setup:",
        "- Variables: Speed, bIsInAir, bIsMoving, AimYawOrPitch",
        "- State machine: Idle/Locomotion, Jump/Fall, Action overlay if needed",
        "- Blend spaces or montage hooks only after the base locomotion path works",
    ]
    steps = [
        f"Create an Animation Blueprint named `{clean_name}` under `Content/Animation`.",
        f"Use `{parent_class}` or your project anim instance base class as the parent.",
        "Bridge only the minimum movement/combat variables from character code into the AnimBP first.",
        "Start with a small locomotion state machine before layering montages, additive poses, or aim offsets.",
    ]
    return build_text_asset_scaffold("animbp", name, "ABP_", "Content/Animation", "Animation Blueprint", purpose, outline_lines, steps)


def build_state_tree_scaffold(name, purpose=""):
    outline_lines = [
        f"Asset: {sanitize_asset_name(name, 'ST_')}",
        "Type: StateTree",
        f"Purpose: {purpose or 'Hierarchical gameplay state flow'}",
        "",
        "Recommended starter states:",
        "- Root",
        "- Default/Idle",
        "- Active/Primary goal",
        "- Recovery/Fallback",
        "",
        "Recommended starter graph pieces:",
        "- Shared parameters for actor/controller references",
        "- One evaluator for live state inputs",
        "- Small tasks per state instead of one large task",
    ]
    steps = [
        "Create the StateTree asset under `Content/AI` or `Content/Gameplay/StateTrees`.",
        "Add only a few explicit states first so ownership and transitions stay readable.",
        "Centralize shared input through parameters/evaluators before duplicating checks across tasks.",
        "Verify the owning component or controller starts and updates this StateTree in the target runtime path.",
    ]
    return build_text_asset_scaffold("state_tree", name, "ST_", "Content/Gameplay/StateTrees", "StateTree", purpose, outline_lines, steps)


def build_control_rig_scaffold(name, purpose=""):
    outline_lines = [
        f"Asset: {sanitize_asset_name(name, 'CR_')}",
        "Type: Control Rig",
        f"Purpose: {purpose or 'Procedural rig or pose control'}",
        "",
        "Recommended starter rig pieces:",
        "- Controls for the smallest useful body part or prop rig",
        "- Hierarchy access scoped to the driven bones",
        "- Forward solve first, then optional backward solve only if truly needed",
    ]
    steps = [
        "Create the Control Rig asset under `Content/Animation/Rigs`.",
        "Start with a tiny control set and one clear solve direction before expanding the rig graph.",
        "Keep runtime and editor-only rig assumptions separate if the rig will be reused in gameplay.",
        "Validate which skeletal mesh, anim pipeline, or sequencer flow will own this rig before adding more controls.",
    ]
    return build_text_asset_scaffold("control_rig", name, "CR_", "Content/Animation/Rigs", "Control Rig", purpose, outline_lines, steps)


def build_niagara_scaffold(name, purpose=""):
    outline_lines = [
        f"Asset: {sanitize_asset_name(name, 'NS_')}",
        "Type: Niagara System",
        f"Purpose: {purpose or 'Gameplay VFX system'}",
        "",
        "Recommended starter emitters:",
        "- One emitter with clear spawn/update ownership",
        "- Parameter inputs for color/intensity/rate only if the effect needs runtime tuning",
        "- One renderer path before layering extra emitters",
    ]
    steps = [
        "Create the Niagara System under `Content/VFX`.",
        "Start with one emitter and one renderer so the effect stays debuggable.",
        "Parameterize only the values gameplay code or designers truly need to drive.",
        "Confirm the owning gameplay event, component, or weapon path that will spawn or attach this system.",
    ]
    return build_text_asset_scaffold("niagara", name, "NS_", "Content/VFX", "Niagara System", purpose, outline_lines, steps)


def build_eqs_scaffold(name, purpose=""):
    outline_lines = [
        f"Asset: {sanitize_asset_name(name, 'EQS_')}",
        "Type: EQS Query",
        f"Purpose: {purpose or 'AI position or target query'}",
        "",
        "Recommended starter layout:",
        "- One generator",
        "- Two or three tests max",
        "- A clear query context for querier, target, or world source",
    ]
    steps = [
        "Create the EQS asset under `Content/AI/Queries`.",
        "Start with one generator and the smallest scoring set that answers the gameplay question.",
        "Make context ownership explicit before stacking many distance, visibility, or path tests.",
        "Validate the AIController or behavior logic that requests the query and consumes the result.",
    ]
    return build_text_asset_scaffold("eqs", name, "EQS_", "Content/AI/Queries", "EQS Query", purpose, outline_lines, steps)


def build_sequencer_scaffold(name, purpose=""):
    outline_lines = [
        f"Asset: {sanitize_asset_name(name, 'LS_')}",
        "Type: Level Sequence",
        f"Purpose: {purpose or 'Cinematic or scripted presentation flow'}",
        "",
        "Recommended starter tracks:",
        "- Camera cut track",
        "- One transform or animation track",
        "- Event track only if gameplay must react to timing",
    ]
    steps = [
        "Create the Level Sequence under `Content/Cinematics`.",
        "Bind only the minimum actors/cameras needed for the first pass.",
        "Keep gameplay-critical logic out of the sequence until the presentation path is stable.",
        "Validate the actor/player that triggers the sequence and the exact runtime conditions around it.",
    ]
    return build_text_asset_scaffold("sequencer", name, "LS_", "Content/Cinematics", "Level Sequence", purpose, outline_lines, steps)


def build_metasound_scaffold(name, purpose=""):
    outline_lines = [
        f"Asset: {sanitize_asset_name(name, 'MS_')}",
        "Type: MetaSound",
        f"Purpose: {purpose or 'Reactive or procedural audio'}",
        "",
        "Recommended starter graph:",
        "- Graph Input for one or two runtime parameters",
        "- One playback/oscillator path",
        "- One envelope or shaping stage",
        "- Graph Output to audio",
    ]
    steps = [
        "Create the MetaSound asset under `Content/Audio/MetaSounds`.",
        "Start with one trigger path and one output path before layering modulation.",
        "Name runtime parameters carefully so audio code and content stay in sync.",
        "Validate which audio component or gameplay event will own this sound at runtime.",
    ]
    return build_text_asset_scaffold("metasound", name, "MS_", "Content/Audio/MetaSounds", "MetaSound", purpose, outline_lines, steps)


def build_pcg_scaffold(name, purpose=""):
    outline_lines = [
        f"Asset: {sanitize_asset_name(name, 'PCG_')}",
        "Type: PCG Graph",
        f"Purpose: {purpose or 'Procedural environment or content generation'}",
        "",
        "Recommended starter graph:",
        "- One source input",
        "- One filter stage",
        "- One spawn/output stage",
        "- A named parameter or attribute only if generation must vary at runtime",
    ]
    steps = [
        "Create the PCG graph under `Content/World/PCG`.",
        "Start with one source and one output path so generation ownership stays obvious.",
        "Add filtering before adding multiple spawn branches.",
        "Validate which actor or PCG component owns generation timing and cleanup.",
    ]
    return build_text_asset_scaffold("pcg", name, "PCG_", "Content/World/PCG", "PCG Graph", purpose, outline_lines, steps)


def build_motion_matching_scaffold(name, purpose=""):
    outline_lines = [
        f"Asset: {sanitize_asset_name(name, 'MM_')}",
        "Type: Motion Matching Asset",
        f"Purpose: {purpose or 'Pose-search driven locomotion setup'}",
        "",
        "Recommended starter setup:",
        "- Pose database with a narrow movement focus",
        "- Clear trajectory input expectations",
        "- One chooser/query path before adding many state branches",
    ]
    steps = [
        "Create the Motion Matching asset under `Content/Animation/MotionMatching`.",
        "Start with a small pose database centered on one locomotion scenario.",
        "Confirm the trajectory source and movement-state ownership before broadening the database.",
        "Validate the animation selection path together with the owning character locomotion code.",
    ]
    return build_text_asset_scaffold("motion_matching", name, "MM_", "Content/Animation/MotionMatching", "Motion Matching", purpose, outline_lines, steps)


def build_ik_rig_scaffold(name, purpose=""):
    outline_lines = [
        f"Asset: {sanitize_asset_name(name, 'IKR_')}",
        "Type: IK Rig",
        f"Purpose: {purpose or 'IK setup or retargeting support'}",
        "",
        "Recommended starter setup:",
        "- Explicit chains for the minimum limbs or props you need",
        "- One solver path",
        "- Goals/effectors named after the driven body parts",
    ]
    steps = [
        "Create the IK Rig asset under `Content/Animation/IK`.",
        "Define only the required chains and goals first so debugging stays manageable.",
        "Keep retargeting assumptions explicit if multiple skeletons or profiles are involved.",
        "Validate which skeletal mesh, rig, or anim pipeline path owns this IK setup.",
    ]
    return build_text_asset_scaffold("ik_rig", name, "IKR_", "Content/Animation/IK", "IK Rig", purpose, outline_lines, steps)


def build_data_asset_edit_plan(asset, change_request, details):
    asset_name = asset.get("name", "")
    asset_path = asset.get("path", "")
    owner = details.get("linked_cpp_classes", {}).get("primary_owner", "None")
    fields_to_check = [
        "IDs, names, and enum-like fields that gate lookup logic",
        "Soft object/class references that may affect loading or spawn behavior",
        "Numeric tuning values that may need companion balance changes",
        "Any booleans that unlock optional behaviors or content branches",
    ]
    risks = [
        "Changing a DataAsset can affect every system that reads it, not just one actor or level instance.",
        "Soft-reference or null/default handling can break at runtime if a value is cleared or renamed carelessly.",
        "Balance changes may need companion updates in UI text, AI tuning, or animation timing if those systems also consume this data.",
    ]
    validation = [
        f"Open `{asset_name}` in the editor and make the smallest possible value change first.",
        "Search for the owning runtime class and any managers/components that load this asset.",
        "Play the exact gameplay path that consumes the changed data and verify both normal and fallback behavior.",
        "Check logs for missing references, null data, or unexpected defaults after the change.",
    ]
    if owner != "None":
        validation.insert(1, f"Inspect `{owner}` first, because it looks like the strongest code owner for this DataAsset.")

    return {
        "asset_kind": "data_asset_edit",
        "title": f"Edit Plan for {asset_name}",
        "summary": f"This is a controlled edit plan for changing DataAsset values in `{asset_name}` without blindly editing the binary asset.",
        "asset_name": asset_name,
        "asset_path": asset_path,
        "change_request": change_request,
        "linked_cpp_owner": owner,
        "what_to_change": [
            f"Requested change: {change_request}",
            "Prefer changing only the smallest set of fields needed to achieve the behavior.",
            "Keep old values nearby so you can compare and revert quickly if the runtime result drifts.",
        ],
        "fields_to_check": fields_to_check,
        "risks": risks,
        "validation_steps": validation,
    }


def build_asset_rename_edit_plan(asset, change_request, details):
    asset_name = asset.get("name", "")
    asset_path = asset.get("path", "")
    owner = details.get("linked_cpp_classes", {}).get("primary_owner", "None")
    family = asset.get("family", "")
    current_name = asset_name.rsplit(".", 1)[0]
    suggested_name = infer_rename_target(change_request, current_name)

    what_to_change = [
        f"Requested change: {change_request}",
        f"Rename `{current_name}` to a clearer target like `{suggested_name}` only if the new name improves ownership and matches project naming conventions.",
        "Update the asset display name, any exposed labels/categories, and all human-facing references together so naming stays consistent.",
        "Search for both hard references and naming-based lookups before you commit to the rename.",
    ]

    fields_to_check = [
        "Asset name and path",
        "Any exposed parameter, variable, or label that mirrors the old name",
        "Code or Blueprint references that use the old asset name directly",
        "Soft-reference paths, lookup IDs, tags, or data keys that may embed the old name",
        "UI/debug text or editor-facing labels that designers rely on",
    ]

    risks = [
        "Renames can silently break soft references, string-based lookups, or naming-convention-driven inference.",
        "Blueprint and content references may update differently from code or config references, so the rename can look fine in-editor but fail at runtime.",
        "If the old name carries semantic meaning used by designers or tooling, a rename can create confusion even when technical references are fixed.",
    ]
    if family == "data_asset":
        risks.append("DataAsset renames can break data tables, settings, or lookup maps that expect stable IDs or names.")
    if family in {"blueprint", "ui"}:
        risks.append("Blueprint renames can affect spawn assumptions, asset-search workflows, or parent/child content conventions.")
    if family == "enhanced_input":
        risks.append("Input asset renames can desync naming between IA_/IMC_ assets and the code paths that bind them.")

    validation = [
        f"Search the project for `{current_name}` before renaming so you know every place the old name matters.",
        "Rename the asset in the editor first so Unreal can update asset references where possible.",
        "Re-run reference searches for both the old and new names after the rename to catch missed strings or config paths.",
        "Test the runtime flow that loads, spawns, or binds this asset and confirm no fallback/default path starts firing unexpectedly.",
        "If the asset is designer-facing, confirm the new name still matches existing folder and prefix conventions.",
    ]
    if owner != "None":
        validation.insert(1, f"Inspect `{owner}` first, because it looks like the strongest runtime owner for this asset.")

    return {
        "asset_kind": "asset_rename_edit",
        "title": f"Rename Plan for {asset_name}",
        "summary": f"This is a controlled rename plan for `{asset_name}` focused on references, exposed names, and runtime safety.",
        "asset_name": asset_name,
        "asset_path": asset_path,
        "change_request": change_request,
        "linked_cpp_owner": owner,
        "suggested_new_name": suggested_name,
        "what_to_change": what_to_change,
        "fields_to_check": fields_to_check,
        "risks": risks[:5],
        "validation_steps": validation,
    }


def build_enhanced_input_edit_plan(asset, change_request, details):
    asset_name = asset.get("name", "")
    asset_path = asset.get("path", "")
    owner = details.get("linked_cpp_classes", {}).get("primary_owner", "None")
    is_mapping_context = asset.get("asset_type") == "input_mapping_context"
    subject = "mapping context" if is_mapping_context else "input action"

    what_to_change = [
        f"Requested change: {change_request}",
        f"Add the smallest new {subject}-level definition needed before changing runtime binding code.",
        "Keep naming consistent with existing IA_/IMC_ conventions so the ownership stays obvious.",
    ]

    fields_to_check = [
        "Action name, value type, and any trigger/modifier assumptions",
        "Which mapping context should own the new action",
        "Which pawn/controller/local-player subsystem layer should bind or add it",
        "Whether the input should be contextual, modal, or always active",
    ]

    risks = [
        "New input can conflict with existing bindings or context priorities if it is added in the wrong layer.",
        "An action can exist in content but still do nothing if the mapping context is never applied or the binding code is missing.",
        "Enhanced Input bugs often look intermittent when multiple contexts override or duplicate the same input.",
    ]

    validation = [
        f"Open `{asset_name}` in the editor and add the new {subject} definition in the smallest possible place first.",
        "Confirm the intended mapping context is active for the local player during the gameplay flow you care about.",
        "Verify the owning pawn/controller actually binds the new action and that the callback fires once per expected trigger.",
        "Test input priority conflicts against menus, vehicles, interaction modes, or any temporary contexts.",
    ]
    if owner != "None":
        validation.insert(1, f"Inspect `{owner}` first, because it looks like the strongest runtime owner for this input setup.")

    return {
        "asset_kind": "enhanced_input_edit",
        "title": f"Edit Plan for {asset_name}",
        "summary": f"This is a controlled edit plan for changing Enhanced Input setup in `{asset_name}` without guessing at bindings or context ownership.",
        "asset_name": asset_name,
        "asset_path": asset_path,
        "change_request": change_request,
        "linked_cpp_owner": owner,
        "what_to_change": what_to_change,
        "fields_to_check": fields_to_check,
        "risks": risks,
        "validation_steps": validation,
    }


def build_behavior_tree_edit_plan(asset, change_request, details):
    asset_name = asset.get("name", "")
    asset_path = asset.get("path", "")
    owner = details.get("linked_cpp_classes", {}).get("primary_owner", "None")
    node_kind = infer_behavior_tree_node_kind(change_request)
    suggested_name = infer_behavior_tree_node_name(change_request, node_kind)

    what_to_change = [
        f"Requested change: {change_request}",
        f"Add or adjust the smallest possible `{node_kind}` node first, using a name like `{suggested_name}` if you need a new asset/class.",
        "Decide whether the change belongs in the tree structure, a Blackboard key, or task/service/decorator logic before editing multiple places.",
        "Keep the behavior localized so the tree remains readable and debuggable.",
    ]

    fields_to_check = [
        "Which Blackboard keys the change reads or writes",
        "Where in the tree flow the new or changed node should live",
        "Whether the logic belongs in a Task, Service, or Decorator",
        "Which AIController, pawn, or subsystem starts this tree",
        "Whether the change should be conditional, periodic, or one-shot",
    ]

    risks = [
        "Behavior Tree edits can look correct structurally but still fail if Blackboard keys are missing or written too late.",
        "Adding logic to Services or Decorators can spread behavior across the tree and make debugging much harder.",
        "A small tree change can alter AI priority/order in ways that only show up under gameplay pressure.",
    ]
    if "service" in change_request.lower():
        risks.append("Service-heavy logic can become noisy and expensive if it runs more often than necessary.")
    if "decorator" in change_request.lower():
        risks.append("Decorator conditions can silently gate whole branches, so false assumptions about key values are costly.")

    validation = [
        f"Open `{asset_name}` and make the smallest tree change possible first.",
        "Inspect the Blackboard asset alongside the tree so every key used by the change is present and typed correctly.",
        "Verify the owning AIController or startup path actually runs this tree in the gameplay case you care about.",
        "Use Gameplay Debugger or Blackboard inspection to confirm key values before and after the change.",
        "Test multiple branch outcomes so the new logic does not only work in the happy path.",
    ]
    if owner != "None":
        validation.insert(1, f"Inspect `{owner}` first, because it looks like the strongest runtime owner for this AI behavior.")

    return {
        "asset_kind": "behavior_tree_edit",
        "title": f"Edit Plan for {asset_name}",
        "summary": f"This is a controlled edit plan for changing Behavior Tree flow in `{asset_name}` without guessing at Blackboard state or AI ownership.",
        "asset_name": asset_name,
        "asset_path": asset_path,
        "change_request": change_request,
        "linked_cpp_owner": owner,
        "suggested_node_kind": node_kind,
        "suggested_node_name": suggested_name,
        "what_to_change": what_to_change,
        "fields_to_check": fields_to_check,
        "risks": risks[:5],
        "validation_steps": validation,
    }


def build_material_edit_plan(asset, change_request, details):
    asset_name = asset.get("name", "")
    asset_path = asset.get("path", "")
    owner = details.get("linked_cpp_classes", {}).get("primary_owner", "None")
    parameter_name = infer_material_parameter_name(change_request)
    parameter_type = infer_material_parameter_type(change_request)
    is_instance = asset.get("asset_type") == "material_instance"
    subject = "Material Instance parameter override" if is_instance else "Material parameter"

    what_to_change = [
        f"Requested change: {change_request}",
        f"Adjust the smallest possible {subject.lower()} first, using a parameter like `{parameter_name}` of type `{parameter_type}`.",
        "Prefer parameterized tweaks over hard-wiring constants if this visual may need runtime or per-instance control.",
        "Check whether the change belongs in the base material or only in a specific material instance.",
    ]

    fields_to_check = [
        "Parameter name and parameter type",
        "Default value versus instance override value",
        "Whether gameplay code updates this parameter at runtime",
        "Whether the material is reused broadly and could affect many meshes or actors",
        "Whether the parameter should really live in a Material Parameter Collection instead",
    ]

    risks = [
        "Material tweaks can affect many actors at once if the material or instance is widely reused.",
        "Parameter name mismatches can make runtime updates fail silently even when the visual asset looks correct in the editor.",
        "Visual changes can be overridden immediately by gameplay code if a dynamic material instance sets the same parameter at runtime.",
    ]
    if not is_instance:
        risks.append("Editing the base material may have much wider impact than editing a material instance.")
    if owner != "None":
        risks.append(f"`{owner}` may already drive this material at runtime, so static editor changes may not match play-time results.")

    validation = [
        f"Open `{asset_name}` and change the parameter in the smallest possible place first.",
        "Search code and Blueprint flow for dynamic material instance creation and runtime parameter writes before assuming the editor value will win.",
        "Test the material on the intended mesh/actor in the exact gameplay situation where the visual matters.",
        "Verify the parameter name used in content exactly matches any runtime `SetScalar/SetVector/SetTextureParameterValue` usage.",
        "Compare the change in-editor and in PIE so runtime overrides do not hide the real result.",
    ]

    result = {
        "asset_kind": "material_edit",
        "title": f"Edit Plan for {asset_name}",
        "summary": f"This is a controlled edit plan for tweaking Material parameters in `{asset_name}` without guessing at runtime overrides or reuse impact.",
        "asset_name": asset_name,
        "asset_path": asset_path,
        "change_request": change_request,
        "linked_cpp_owner": owner,
        "suggested_parameter_name": parameter_name,
        "suggested_parameter_type": parameter_type,
        "what_to_change": what_to_change,
        "fields_to_check": fields_to_check,
        "risks": risks[:5],
        "validation_steps": validation,
    }
    editor_action = build_material_parameter_editor_action(asset, change_request, parameter_name, parameter_type)
    if editor_action:
        result["editor_action"] = editor_action
    return result


def build_animbp_edit_plan(asset, change_request, details):
    asset_name = asset.get("name", "")
    asset_path = asset.get("path", "")
    owner = details.get("linked_cpp_classes", {}).get("primary_owner", "None")
    lowered = change_request.lower()
    state_name = infer_animbp_state_name(change_request)
    variable_name = infer_animbp_variable_name(change_request)

    what_to_change = [
        f"Requested change: {change_request}",
        f"Make the smallest AnimBP-side change first, such as a state/transition named `{state_name}` or a bridged variable like `{variable_name}`.",
        "Decide whether the requested behavior belongs in state-machine flow, montage/notifies, or character-to-anim variable bridging before touching multiple graphs.",
        "Keep gameplay authority in character/controller code and use the AnimBP to translate that state into animation behavior.",
    ]

    fields_to_check = [
        "Anim instance variables that mirror movement, combat, locomotion, or action state",
        "State machine names, transition rules, and any blend settings the change depends on",
        "Montage, slot, and notify usage if the request affects attacks, reactions, or one-shot actions",
        "Whether the owning character or pawn updates the needed variables before the AnimBP reads them",
        "Whether the same state already exists in the character, ability, or movement code",
    ]

    risks = [
        "AnimBP changes can look correct in-editor but fail at runtime if the character never updates the bridged variables.",
        "Duplicating gameplay state in both the character and the AnimBP can create drift and hard-to-debug timing bugs.",
        "Transition rule changes can have broad side effects across locomotion or combat graphs, especially when blends and montages interact.",
    ]
    if "montage" in lowered or "notify" in lowered:
        risks.append("Montage or notify changes can desync gameplay timing if damage windows, FX, or movement locks rely on them.")
    if "turn" in lowered or "aim" in lowered or "speed" in lowered:
        risks.append("Locomotion and aim-state changes often need validation across multiple movement speeds and edge-case direction changes.")

    validation = [
        f"Open `{asset_name}` and make the smallest state-machine or variable-bridge change possible first.",
        "Inspect the owning character, pawn, or anim instance code to confirm where the driving variables are written.",
        "Use PIE plus animation debug tools to watch the variable values and active states while reproducing the target behavior.",
        "Test idle, locomotion, and any combat/action transitions that touch the same graph so the change does not only work in one path.",
        "If montages or notifies are involved, verify gameplay events still fire at the expected frame/timing.",
    ]
    if owner != "None":
        validation.insert(1, f"Inspect `{owner}` first, because it looks like the strongest runtime owner for this animation flow.")

    return {
        "asset_kind": "animbp_edit",
        "title": f"Edit Plan for {asset_name}",
        "summary": f"This is a controlled edit plan for changing animation flow in `{asset_name}` without guessing at gameplay-to-animation ownership.",
        "asset_name": asset_name,
        "asset_path": asset_path,
        "change_request": change_request,
        "linked_cpp_owner": owner,
        "suggested_node_kind": "state_or_transition",
        "suggested_node_name": state_name,
        "suggested_parameter_name": variable_name,
        "suggested_parameter_type": "AnimBP Variable",
        "what_to_change": what_to_change,
        "fields_to_check": fields_to_check,
        "risks": risks[:5],
        "validation_steps": validation,
    }


def build_material_parameter_editor_action(asset, change_request, parameter_name, parameter_type):
    if asset.get("asset_type") != "material_instance":
        return None

    inferred_value = infer_material_parameter_value(change_request, parameter_type)
    if inferred_value is None:
        return None

    return {
        "action_type": "tweak_material_parameter",
        "dry_run": False,
        "requires_user_confirmation": True,
        "arguments": {
            "asset_path": asset.get("path", ""),
            "parameter_name": parameter_name,
            "parameter_type": parameter_type.lower(),
            "parameter_value": inferred_value,
        },
    }


def build_state_tree_edit_plan(asset, change_request, details):
    return build_generic_specialized_edit_plan(
        asset,
        change_request,
        details,
        asset_kind="state_tree_edit",
        summary_phrase="changing StateTree flow",
        suggested_focus_name=infer_state_tree_focus_name(change_request),
        suggested_focus_kind="state_or_task",
        fields_to_check=[
            "State names and transition conditions touched by the change",
            "Shared parameters and evaluator inputs the state logic depends on",
            "Task ownership and whether the work belongs in the tree versus runtime code",
            "Which controller/component starts and updates this StateTree",
        ],
        risks=[
            "StateTree edits can duplicate gameplay transitions that already exist in code if ownership is not checked first.",
            "Evaluator and task logic can become hard to debug if too much state is inferred indirectly.",
            "Transition changes can affect multiple gameplay branches even when the visual edit looks small.",
        ],
        validation_steps=[
            f"Open `{asset.get('name', '')}` and make the smallest state or task change possible first.",
            "Inspect the runtime owner to confirm where shared state is written before the tree evaluates it.",
            "Test at least the target branch plus one fallback branch so the change does not only work in one happy path.",
            "Use debug tooling or logging to watch the active state and transition conditions while reproducing the behavior.",
        ],
    )


def build_control_rig_edit_plan(asset, change_request, details):
    return build_generic_specialized_edit_plan(
        asset,
        change_request,
        details,
        asset_kind="control_rig_edit",
        summary_phrase="adjusting procedural rig behavior",
        suggested_focus_name=infer_control_rig_focus_name(change_request),
        suggested_focus_kind="control_or_solver",
        fields_to_check=[
            "Which controls, bones, or chains the edit should affect",
            "Whether the change belongs in forward solve, backward solve, or setup logic",
            "How the rig is consumed by animation, sequencer, or runtime components",
            "Any retarget or hierarchy assumptions that could break when the change lands",
        ],
        risks=[
            "Control Rig edits can look correct in-editor but fail in runtime or cinematic paths if ownership differs.",
            "Solver changes can affect a wider part of the pose than expected.",
            "Hierarchy or naming mismatches can quietly break driven controls and bones.",
        ],
        validation_steps=[
            f"Open `{asset.get('name', '')}` and isolate the smallest control or solver change first.",
            "Validate the driven bones and control names before expanding the graph edit.",
            "Test the rig in the exact animation or sequence path where it matters, not just in isolation.",
            "Confirm the solve direction and order still match the intended procedural animation flow.",
        ],
    )


def build_niagara_edit_plan(asset, change_request, details):
    return build_generic_specialized_edit_plan(
        asset,
        change_request,
        details,
        asset_kind="niagara_edit",
        summary_phrase="changing Niagara VFX behavior",
        suggested_focus_name=infer_niagara_focus_name(change_request),
        suggested_focus_kind="emitter_or_parameter",
        fields_to_check=[
            "Emitter ownership and whether the change belongs in spawn, update, or renderer setup",
            "Parameter names and whether gameplay code drives them at runtime",
            "Attachment/spawn location assumptions and cleanup behavior",
            "Whether the system is reused broadly and could affect many gameplay paths",
        ],
        risks=[
            "Niagara edits can silently drift from gameplay expectations if parameter names or spawn assumptions change.",
            "Emitter or renderer changes may increase runtime cost in every place the effect is used.",
            "Short-lived visual fixes can mask cleanup, pooling, or attachment problems.",
        ],
        validation_steps=[
            f"Open `{asset.get('name', '')}` and make one emitter or parameter change at a time.",
            "Search gameplay code for runtime Niagara variable writes before assuming the editor value will win.",
            "Test the effect in the exact gameplay event that owns it so timing and attachment stay honest.",
            "Compare editor preview and PIE/runtime behavior to catch spawn/setup differences.",
        ],
    )


def build_eqs_edit_plan(asset, change_request, details):
    return build_generic_specialized_edit_plan(
        asset,
        change_request,
        details,
        asset_kind="eqs_edit",
        summary_phrase="changing EQS query behavior",
        suggested_focus_name=infer_eqs_focus_name(change_request),
        suggested_focus_kind="generator_or_test",
        fields_to_check=[
            "Generator ownership and whether the query should produce points, actors, or other items",
            "Tests, weights, and contexts touched by the change",
            "Which AIController, task, or behavior requests this query",
            "How the result is consumed after scoring completes",
        ],
        risks=[
            "EQS edits can look small but radically change AI decision quality if contexts or scores drift.",
            "More tests can add cost quickly when the query already runs often.",
            "Queries may appear random when the generator/context pair is misaligned with gameplay assumptions.",
        ],
        validation_steps=[
            f"Open `{asset.get('name', '')}` and add or adjust one generator/test at a time.",
            "Validate the query context and consuming AI behavior together before widening the change.",
            "Inspect scored results in the intended scenario so you can see why the winning item changed.",
            "Test at least one edge case where the AI has fewer good candidate results.",
        ],
    )


def build_sequencer_edit_plan(asset, change_request, details):
    return build_generic_specialized_edit_plan(
        asset,
        change_request,
        details,
        asset_kind="sequencer_edit",
        summary_phrase="changing Sequencer timing or presentation",
        suggested_focus_name=infer_sequencer_focus_name(change_request),
        suggested_focus_kind="track_or_event",
        fields_to_check=[
            "Track, section, and binding ownership for the requested change",
            "Which event keys or timing windows gameplay depends on",
            "Whether the change belongs in cinematic presentation or in gameplay code",
            "Camera and actor bindings that could break when assets move or rename",
        ],
        risks=[
            "Sequencer edits can hide gameplay dependencies inside presentation timing.",
            "Track timing changes can ripple into animation, audio, or camera behavior together.",
            "Bindings can fail silently if actors/assets differ between editor and runtime contexts.",
        ],
        validation_steps=[
            f"Open `{asset.get('name', '')}` and make one track or event change at a time.",
            "Confirm the same actors and cameras are bound in the runtime scenario you care about.",
            "Play through the full sequence to verify downstream timing still lines up.",
            "If gameplay reacts to sequence events, test both the sequence and the gameplay response together.",
        ],
    )


def build_metasound_edit_plan(asset, change_request, details):
    return build_generic_specialized_edit_plan(
        asset,
        change_request,
        details,
        asset_kind="metasound_edit",
        summary_phrase="changing MetaSound graph behavior",
        suggested_focus_name=infer_metasound_focus_name(change_request),
        suggested_focus_kind="graph_input_or_audio_node",
        fields_to_check=[
            "Graph inputs and whether code/gameplay drives them at runtime",
            "Trigger/playback flow and where timing starts",
            "Shaping, mix, or envelope stages touched by the change",
            "Whether the MetaSound is reused by many actors or one narrow event path",
        ],
        risks=[
            "MetaSound parameter name mismatches can make runtime audio changes fail silently.",
            "Graph edits can change loudness, timing, or layering in more places than expected if the sound is reused.",
            "Trigger and delay changes can create subtle gameplay/audio sync issues.",
        ],
        validation_steps=[
            f"Open `{asset.get('name', '')}` and adjust one graph input or node cluster at a time.",
            "Search for runtime parameter writes before renaming or repurposing any exposed input.",
            "Test the audio in the exact gameplay event flow where timing matters.",
            "Compare editor preview and runtime playback so component-level differences do not surprise you.",
        ],
    )


def build_pcg_edit_plan(asset, change_request, details):
    return build_generic_specialized_edit_plan(
        asset,
        change_request,
        details,
        asset_kind="pcg_edit",
        summary_phrase="changing PCG generation behavior",
        suggested_focus_name=infer_pcg_focus_name(change_request),
        suggested_focus_kind="source_filter_or_spawn_stage",
        fields_to_check=[
            "Generation source inputs and ownership of source actors/data",
            "Filter stages, attributes, and density controls affected by the change",
            "Spawn/output stages and cleanup expectations",
            "Which PCG component or world-generation path owns this graph",
        ],
        risks=[
            "PCG edits can explode output count or cost if spawn/filter balance drifts.",
            "Generation ownership can become unclear when multiple actors or systems trigger the same graph.",
            "Small attribute/filter changes can have broad visual impact across a level.",
        ],
        validation_steps=[
            f"Open `{asset.get('name', '')}` and change one source/filter/spawn stage at a time.",
            "Validate the owning PCG component or trigger path before judging the graph in isolation.",
            "Inspect generated output count and placement, not just whether something spawned.",
            "Test cleanup/regeneration behavior if this graph can run more than once.",
        ],
    )


def build_motion_matching_edit_plan(asset, change_request, details):
    return build_generic_specialized_edit_plan(
        asset,
        change_request,
        details,
        asset_kind="motion_matching_edit",
        summary_phrase="changing motion-matching selection behavior",
        suggested_focus_name=infer_motion_matching_focus_name(change_request),
        suggested_focus_kind="pose_database_or_query_input",
        fields_to_check=[
            "Pose database coverage and whether the requested behavior belongs in this database",
            "Trajectory/query inputs that drive selection quality",
            "Chooser/scoring assumptions touched by the change",
            "Which locomotion state and character code path feed the matcher",
        ],
        risks=[
            "Motion Matching edits can make selection noisy if trajectory inputs and pose coverage drift apart.",
            "Pose database changes may affect many locomotion states at once.",
            "Scoring tweaks can appear fine in one speed range but fail in turns, stops, or transitions.",
        ],
        validation_steps=[
            f"Open `{asset.get('name', '')}` and make the smallest pose/query change possible first.",
            "Confirm the owning locomotion code still feeds the expected trajectory and state inputs.",
            "Test multiple movement speeds and direction changes, not just one showcase path.",
            "Watch debug data for pose choice stability instead of relying only on visible animation quality.",
        ],
    )


def build_ik_rig_edit_plan(asset, change_request, details):
    return build_generic_specialized_edit_plan(
        asset,
        change_request,
        details,
        asset_kind="ik_rig_edit",
        summary_phrase="changing IK Rig or retarget behavior",
        suggested_focus_name=infer_ik_rig_focus_name(change_request),
        suggested_focus_kind="chain_goal_or_solver",
        fields_to_check=[
            "Driven chains and goals touched by the change",
            "Whether the change belongs in chain setup, goal placement, solver tuning, or retarget settings",
            "Which skeleton/mesh pair owns this rig configuration",
            "Any retarget profile assumptions that depend on the current setup",
        ],
        risks=[
            "IK Rig edits can fail subtly when chain names, skeleton assumptions, or retarget profiles drift apart.",
            "Solver changes may affect pose stability more broadly than the local edit suggests.",
            "A rig can appear correct in one animation path but fail in another with different pose inputs.",
        ],
        validation_steps=[
            f"Open `{asset.get('name', '')}` and isolate one chain, goal, or solver change first.",
            "Validate the skeleton and mesh assumptions before widening the edit.",
            "Test the rig in the exact retarget or animation path that depends on it.",
            "Check both rest and exaggerated poses so solver tuning remains stable.",
        ],
    )


def build_blueprint_variable_edit_plan(asset, change_request, details):
    asset_name = asset.get("name", "")
    asset_path = asset.get("path", "")
    owner = details.get("linked_cpp_classes", {}).get("primary_owner", "None")
    lowered = change_request.lower()
    suggested_type = infer_blueprint_variable_type(change_request)
    expose_note = "Expose the variable to the editor only if designers actually need to tune it per asset or instance."

    what_to_change = [
        f"Requested change: {change_request}",
        f"Add one new Blueprint variable with a clear name and a starting type like `{suggested_type}`.",
        "Decide whether the variable is runtime state, config/default data, or a reference to another actor/component/asset before wiring any graph logic.",
        expose_note,
    ]

    fields_to_check = [
        "Variable name and type",
        "Default value on the Blueprint asset or instance",
        "Whether it should be Instance Editable, Expose on Spawn, or Blueprint Read Only/Read Write",
        "Which graph/event/function is responsible for setting it",
        "Which systems read it and what happens if it is unset",
    ]

    risks = [
        "Blueprint variables easily become duplicated state if the same concept already exists in the parent C++ class or another component.",
        "Exposing too many variables can blur ownership and make debugging defaults versus runtime values harder.",
        "Reference variables can introduce null or lifecycle bugs if they are read before initialization.",
    ]
    if "replic" in lowered or "network" in lowered:
        risks.append("Network-facing variables need an explicit replication plan; Blueprint-only variable changes can still break multiplayer assumptions.")
    if "damage" in lowered or "speed" in lowered or "health" in lowered:
        risks.append("Gameplay tuning variables can affect animation, UI, AI, and balance together, so verify dependent systems after the change.")

    validation = [
        f"Open `{asset_name}` in the Blueprint editor and add the variable in the smallest possible scope first.",
        "Set a deliberate default value and test behavior with both the default and an overridden value.",
        "Search the parent class and linked owner code to avoid duplicating an equivalent C++ property or state source.",
        "Check every read/write site in the graph so the variable is initialized before it is consumed.",
        "If the value is designer-facing, confirm the tooltip/category/name make the intent obvious in the Details panel.",
    ]
    if owner != "None":
        validation.insert(1, f"Inspect `{owner}` first, because it looks like the strongest code owner for this Blueprint.")

    return {
        "asset_kind": "blueprint_variable_edit",
        "title": f"Edit Plan for {asset_name}",
        "summary": f"This is a controlled edit plan for adding or adjusting a Blueprint variable in `{asset_name}` without guessing at ownership or graph flow.",
        "asset_name": asset_name,
        "asset_path": asset_path,
        "change_request": change_request,
        "linked_cpp_owner": owner,
        "suggested_variable_type": suggested_type,
        "what_to_change": what_to_change,
        "fields_to_check": fields_to_check,
        "risks": risks[:5],
        "validation_steps": validation,
    }


def build_blueprint_function_edit_plan(asset, change_request, details):
    asset_name = asset.get("name", "")
    asset_path = asset.get("path", "")
    owner = details.get("linked_cpp_classes", {}).get("primary_owner", "None")
    function_name = infer_blueprint_function_name(change_request)
    signature = infer_blueprint_function_signature(change_request)

    what_to_change = [
        f"Requested change: {change_request}",
        f"Add one new Blueprint function stub named `{function_name}` with a starting signature like `{signature}`.",
        "Keep the function narrow and single-purpose so ownership stays obvious.",
        "Decide whether this should be a pure helper function, an impure action function, or a custom event before wiring execution flow.",
    ]

    fields_to_check = [
        "Function name and intent",
        "Input pins and whether they should be value types or object references",
        "Return value or output pins, if any",
        "Where the function is called from and what initializes its inputs",
        "Whether the same behavior already exists in the parent class, another Blueprint, or C++",
    ]

    risks = [
        "Blueprint functions easily become duplicate logic if the same behavior already exists in the parent C++ class or another graph.",
        "Function stubs can hide ownership issues if they mutate too much state or call into too many unrelated systems.",
        "Reference inputs can create null/lifecycle bugs if the caller is allowed to pass invalid objects.",
    ]
    if "server" in change_request.lower() or "client" in change_request.lower() or "replic" in change_request.lower():
        risks.append("Network-sensitive behavior needs a replication/RPC plan; a Blueprint function stub alone does not solve authority flow.")

    validation = [
        f"Open `{asset_name}` in the Blueprint editor and add the function stub with the smallest useful signature first.",
        "Check the parent class and linked owner code before duplicating an existing function or gameplay hook.",
        "Add temporary logging or a breakpoint to verify the function is called from the path you expect.",
        "Confirm all inputs are valid before the function reads them, especially object references and data assets.",
        "If this logic grows beyond orchestration, move reusable or performance-sensitive parts into C++.",
    ]
    if owner != "None":
        validation.insert(1, f"Inspect `{owner}` first, because it looks like the strongest code owner for this Blueprint behavior.")

    return {
        "asset_kind": "blueprint_function_edit",
        "title": f"Edit Plan for {asset_name}",
        "summary": f"This is a controlled edit plan for adding a Blueprint function stub in `{asset_name}` without guessing at ownership or execution flow.",
        "asset_name": asset_name,
        "asset_path": asset_path,
        "change_request": change_request,
        "linked_cpp_owner": owner,
        "suggested_function_name": function_name,
        "suggested_function_signature": signature,
        "what_to_change": what_to_change,
        "fields_to_check": fields_to_check,
        "risks": risks[:5],
        "validation_steps": validation,
    }


def infer_blueprint_parent_class(name, purpose=""):
    lowered = f"{name} {purpose}".lower()
    if any(token in lowered for token in ("component",)):
        return "ActorComponent"
    if any(token in lowered for token in ("widget", "menu", "hud", "ui")):
        return "UserWidget"
    if any(token in lowered for token in ("controller",)):
        return "PlayerController"
    if any(token in lowered for token in ("pawn", "vehicle")):
        return "Pawn"
    if any(token in lowered for token in ("character", "enemy", "npc", "player")):
        return "Character"
    return "Actor"


def infer_blueprint_variable_suggestions(name, purpose=""):
    lowered = f"{name} {purpose}".lower()
    variables = ["Config/Data asset reference", "State enum or gameplay state flag", "Target actor or component reference"]
    if any(token in lowered for token in ("character", "enemy", "npc", "player", "pawn")):
        variables.append("Movement/combat state booleans exposed for animation or UI")
    if any(token in lowered for token in ("interact", "pickup", "usable")):
        variables.append("Interactable prompt text and enabled state")
    if any(token in lowered for token in ("widget", "menu", "hud", "ui")):
        variables.append("Widget references and visibility state")
    return variables[:5]


def infer_blueprint_function_suggestions(name, purpose=""):
    lowered = f"{name} {purpose}".lower()
    functions = ["InitializeFromData", "HandleStateChanged", "RefreshPresentation"]
    if any(token in lowered for token in ("interact", "pickup", "usable")):
        functions.append("Interact")
    if any(token in lowered for token in ("character", "enemy", "npc", "player")):
        functions.append("HandleDeathOrDisable")
    if any(token in lowered for token in ("widget", "menu", "hud", "ui")):
        functions.append("RefreshUI")
    return functions[:5]


def infer_blueprint_variable_type(change_request):
    lowered = (change_request or "").lower()
    if any(token in lowered for token in ("count", "index", "ammo", "stack")):
        return "Integer"
    if any(token in lowered for token in ("speed", "damage", "health", "cooldown", "time", "distance")):
        return "Float"
    if any(token in lowered for token in ("enabled", "visible", "active", "dead", "alive", "can ", "has ")):
        return "Boolean"
    if any(token in lowered for token in ("name", "tag", "id")):
        return "Name"
    if any(token in lowered for token in ("text", "label", "prompt", "description")):
        return "Text"
    if any(token in lowered for token in ("target", "actor", "component", "weapon", "widget", "asset")):
        return "Object Reference"
    return "Boolean or Object Reference"


def looks_like_function_request(change_request):
    lowered = (change_request or "").lower()
    function_tokens = ("function", "stub", "method", "event", "handler", "call", "execute", "run ", "trigger", "invoke")
    variable_tokens = ("variable", "bool", "float", "int", "name", "text", "property")
    if any(token in lowered for token in function_tokens):
        return True
    if any(token in lowered for token in variable_tokens):
        return False
    return "(" in lowered or "return" in lowered


def looks_like_rename_request(change_request):
    lowered = (change_request or "").lower()
    rename_tokens = ("rename", "rename it", "rename this", "change the name", "new name", "exposed parameter", "parameter name", "display name", "label")
    return any(token in lowered for token in rename_tokens)


def infer_blueprint_function_name(change_request):
    lowered = (change_request or "").lower()
    if "interact" in lowered:
        return "HandleInteract"
    if "damage" in lowered:
        return "ApplyDamageResponse"
    if "spawn" in lowered:
        return "HandleSpawnSetup"
    if "fire" in lowered or "shoot" in lowered:
        return "HandleFire"
    if "ui" in lowered or "widget" in lowered or "menu" in lowered:
        return "RefreshUIState"
    if "input" in lowered:
        return "HandleInputAction"
    return "HandleRequestedAction"


def infer_animbp_state_name(change_request):
    lowered = (change_request or "").lower()
    if "jump" in lowered:
        return "JumpOrAirborne"
    if "fall" in lowered:
        return "Falling"
    if "land" in lowered:
        return "Landing"
    if "attack" in lowered or "melee" in lowered:
        return "Attack"
    if "aim" in lowered:
        return "AimOffset"
    if "turn" in lowered:
        return "TurnInPlace"
    return "RequestedState"


def infer_animbp_variable_name(change_request):
    lowered = (change_request or "").lower()
    if "speed" in lowered:
        return "Speed"
    if "jump" in lowered or "fall" in lowered or "air" in lowered:
        return "bIsInAir"
    if "attack" in lowered or "melee" in lowered:
        return "bIsAttacking"
    if "aim" in lowered:
        return "AimYawOrPitch"
    if "turn" in lowered:
        return "TurnOffset"
    return "bRequestedAnimState"


def infer_rename_target(change_request, fallback_name):
    text = (change_request or "").strip()
    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
    extracted = []
    for pair in quoted:
        extracted.extend([item for item in pair if item])
    if extracted:
        candidate = extracted[-1]
    else:
        match = re.search(r"\bto\s+([A-Za-z_][A-Za-z0-9_]*)", text)
        candidate = match.group(1) if match else f"{fallback_name}_Renamed"
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in candidate)
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or f"{fallback_name}_Renamed"


def infer_blueprint_function_signature(change_request):
    lowered = (change_request or "").lower()
    if "damage" in lowered:
        return "Input: DamageAmount (Float), InstigatorActor (Actor Reference) -> Output: None"
    if "interact" in lowered:
        return "Input: InteractingActor (Actor Reference) -> Output: Success (Boolean)"
    if "spawn" in lowered:
        return "Input: SpawnContext (Object Reference) -> Output: None"
    if "ui" in lowered or "widget" in lowered:
        return "Input: None -> Output: None"
    if "input" in lowered:
        return "Input: TriggerValue (Float or Boolean) -> Output: None"
    return "Input: Context (Object Reference or primitive value) -> Output: None"


def infer_material_parameter_name(change_request):
    lowered = (change_request or "").lower()
    if "color" in lowered or "tint" in lowered:
        return "TintColor"
    if "rough" in lowered:
        return "Roughness"
    if "metal" in lowered:
        return "Metallic"
    if "glow" in lowered or "emiss" in lowered:
        return "EmissiveStrength"
    if "opacity" in lowered or "fade" in lowered:
        return "Opacity"
    if "texture" in lowered:
        return "BaseTexture"
    return "TunableParameter"


def infer_material_parameter_type(change_request):
    lowered = (change_request or "").lower()
    if "color" in lowered or "tint" in lowered:
        return "Vector"
    if "texture" in lowered:
        return "Texture"
    return "Scalar"


def infer_material_parameter_value(change_request, parameter_type):
    text = (change_request or "").strip()
    lowered = text.lower()
    normalized_type = (parameter_type or "").strip().lower()

    if normalized_type == "texture":
        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
        extracted = []
        for pair in quoted:
            extracted.extend([item for item in pair if item])
        return extracted[-1] if extracted else None

    if normalized_type == "vector":
        named_colors = {
            "red": "1,0,0,1",
            "green": "0,1,0,1",
            "blue": "0,0,1,1",
            "white": "1,1,1,1",
            "black": "0,0,0,1",
            "yellow": "1,1,0,1",
            "orange": "1,0.5,0,1",
        }
        for color_name, value in named_colors.items():
            if color_name in lowered:
                return value
        number_matches = re.findall(r"-?\d+(?:\.\d+)?", text)
        if len(number_matches) >= 3:
            values = number_matches[:4]
            if len(values) == 3:
                values.append("1")
            return ",".join(values)
        return None

    bool_match = re.search(r"\b(on|off|true|false|enabled|disabled)\b", lowered)
    if bool_match:
        return "1.0" if bool_match.group(1) in {"on", "true", "enabled"} else "0.0"

    number_match = re.search(r"-?\d+(?:\.\d+)?", text)
    if number_match:
        return number_match.group(0)
    return None


def infer_behavior_tree_node_kind(change_request):
    lowered = (change_request or "").lower()
    if "service" in lowered:
        return "Service"
    if "decorator" in lowered or "condition" in lowered:
        return "Decorator"
    if "blackboard" in lowered or "key" in lowered:
        return "Blackboard Key Change"
    return "Task"


def infer_behavior_tree_node_name(change_request, node_kind):
    lowered = (change_request or "").lower()
    if "patrol" in lowered:
        stem = "Patrol"
    elif "attack" in lowered or "combat" in lowered:
        stem = "Attack"
    elif "chase" in lowered or "follow" in lowered:
        stem = "Chase"
    elif "target" in lowered:
        stem = "UpdateTarget"
    elif "cover" in lowered:
        stem = "FindCover"
    else:
        stem = "RequestedBehavior"
    prefix = {
        "Task": "BTTask_",
        "Service": "BTService_",
        "Decorator": "BTDecorator_",
        "Blackboard Key Change": "BB_",
    }.get(node_kind, "BTTask_")
    return f"{prefix}{stem}"


def infer_state_tree_focus_name(change_request):
    lowered = (change_request or "").lower()
    if "patrol" in lowered:
        return "PatrolState"
    if "combat" in lowered or "attack" in lowered:
        return "CombatState"
    if "alert" in lowered:
        return "AlertTransition"
    return "RequestedStateFlow"


def infer_control_rig_focus_name(change_request):
    lowered = (change_request or "").lower()
    if "hand" in lowered or "arm" in lowered:
        return "HandControl"
    if "foot" in lowered or "leg" in lowered:
        return "FootIKSolver"
    if "spine" in lowered:
        return "SpineControl"
    return "RequestedRigControl"


def infer_niagara_focus_name(change_request):
    lowered = (change_request or "").lower()
    if "color" in lowered or "tint" in lowered:
        return "ColorParameter"
    if "smoke" in lowered:
        return "SmokeEmitter"
    if "trail" in lowered:
        return "TrailEmitter"
    if "impact" in lowered:
        return "ImpactBurst"
    return "RequestedEmitterChange"


def infer_eqs_focus_name(change_request):
    lowered = (change_request or "").lower()
    if "cover" in lowered:
        return "CoverScoreTest"
    if "target" in lowered:
        return "TargetSelectionTest"
    if "distance" in lowered:
        return "DistanceFilter"
    return "RequestedQueryAdjustment"


def infer_sequencer_focus_name(change_request):
    lowered = (change_request or "").lower()
    if "camera" in lowered:
        return "CameraTrack"
    if "event" in lowered:
        return "EventTrack"
    if "fade" in lowered:
        return "FadeSection"
    return "RequestedSequenceTrack"


def infer_metasound_focus_name(change_request):
    lowered = (change_request or "").lower()
    if "pitch" in lowered:
        return "PitchInput"
    if "volume" in lowered or "loud" in lowered:
        return "VolumeEnvelope"
    if "loop" in lowered:
        return "LoopTrigger"
    return "RequestedAudioNode"


def infer_pcg_focus_name(change_request):
    lowered = (change_request or "").lower()
    if "density" in lowered:
        return "DensityFilter"
    if "scatter" in lowered or "spawn" in lowered:
        return "ScatterSpawnStage"
    if "slope" in lowered:
        return "SlopeFilter"
    return "RequestedGenerationStage"


def infer_motion_matching_focus_name(change_request):
    lowered = (change_request or "").lower()
    if "turn" in lowered:
        return "TurnDatabase"
    if "stop" in lowered:
        return "StopPoseQuery"
    if "sprint" in lowered or "run" in lowered:
        return "SprintTrajectoryInput"
    return "RequestedPoseSelection"


def infer_ik_rig_focus_name(change_request):
    lowered = (change_request or "").lower()
    if "hand" in lowered or "arm" in lowered:
        return "ArmChainGoal"
    if "foot" in lowered or "leg" in lowered:
        return "FootChainGoal"
    if "retarget" in lowered:
        return "RetargetProfile"
    return "RequestedIKChain"


app.include_router(build_plugin_router({
    "project_cache": PROJECT_CACHE,
    "run_asset_action": run_asset_action,
    "search_files": search_files,
    "selection_analysis": selection_analysis,
    "selection_request_class": SelectionRequest,
    "include_ai_summary": lambda: bool(os.getenv("OPENAI_API_KEY")),
    "summarize_deep_asset_with_llm": summarize_deep_asset_with_llm,
    "looks_like_rename_request": looks_like_rename_request,
    "looks_like_function_request": looks_like_function_request,
    "build_asset_rename_edit_plan": build_asset_rename_edit_plan,
    "build_data_asset_edit_plan": build_data_asset_edit_plan,
    "build_enhanced_input_edit_plan": build_enhanced_input_edit_plan,
    "build_behavior_tree_edit_plan": build_behavior_tree_edit_plan,
    "build_material_edit_plan": build_material_edit_plan,
    "build_animbp_edit_plan": build_animbp_edit_plan,
    "build_state_tree_edit_plan": build_state_tree_edit_plan,
    "build_control_rig_edit_plan": build_control_rig_edit_plan,
    "build_niagara_edit_plan": build_niagara_edit_plan,
    "build_eqs_edit_plan": build_eqs_edit_plan,
    "build_sequencer_edit_plan": build_sequencer_edit_plan,
    "build_metasound_edit_plan": build_metasound_edit_plan,
    "build_pcg_edit_plan": build_pcg_edit_plan,
    "build_motion_matching_edit_plan": build_motion_matching_edit_plan,
    "build_ik_rig_edit_plan": build_ik_rig_edit_plan,
    "build_blueprint_function_edit_plan": build_blueprint_function_edit_plan,
    "build_blueprint_variable_edit_plan": build_blueprint_variable_edit_plan,
    "build_blueprint_class_scaffold": build_blueprint_class_scaffold,
    "build_data_asset_scaffold": build_data_asset_scaffold,
    "build_animbp_scaffold": build_animbp_scaffold,
    "build_material_scaffold": build_material_scaffold,
    "build_material_instance_scaffold": build_material_instance_scaffold,
    "build_behavior_tree_scaffold": build_behavior_tree_scaffold,
    "build_input_action_scaffold": build_input_action_scaffold,
    "build_input_mapping_context_scaffold": build_input_mapping_context_scaffold,
    "build_state_tree_scaffold": build_state_tree_scaffold,
    "build_control_rig_scaffold": build_control_rig_scaffold,
    "build_niagara_scaffold": build_niagara_scaffold,
    "build_eqs_scaffold": build_eqs_scaffold,
    "build_sequencer_scaffold": build_sequencer_scaffold,
    "build_metasound_scaffold": build_metasound_scaffold,
    "build_pcg_scaffold": build_pcg_scaffold,
    "build_motion_matching_scaffold": build_motion_matching_scaffold,
    "build_ik_rig_scaffold": build_ik_rig_scaffold,
}))


def chunk_text(text, chunk_size=7000, overlap=400):
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def remember_interaction(question, answer):
    PROJECT_CACHE["conversation_history"].append(
        {"question": question[:500], "answer": answer[:1000]}
    )
    PROJECT_CACHE["conversation_history"] = PROJECT_CACHE["conversation_history"][-5:]


def format_recent_history():
    items = []
    if PROJECT_CACHE["current_focus"]:
        items.append(f"Current focus file: {PROJECT_CACHE['current_focus']}")
    for item in PROJECT_CACHE["conversation_history"][-3:]:
        items.append(f"Q: {item['question']}\nA: {item['answer']}")
    return "\n\n".join(items) if items else "No recent context."


def heuristic_log_summary(text, log_type="output"):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    errors = [line for line in lines if "error" in line.lower() or "fatal" in line.lower()]
    warnings = [line for line in lines if "warning" in line.lower()]
    stack = [line for line in lines if "::" in line or "!" in line]

    summary = [
        f"{len(errors)} error/fatal line(s) detected.",
        f"{len(warnings)} warning line(s) detected.",
    ]
    if stack:
        summary.append("Possible call stack or symbol lines were found.")
    if log_type == "crash":
        summary.append("Check the first fatal line and the topmost project-specific stack frame first.")
    else:
        summary.append("Prioritize the first real error before later cascading warnings.")

    examples = errors[:5] or warnings[:5] or lines[:5]
    return " ".join(summary) + "\n\nRelevant lines:\n" + "\n".join(examples)
