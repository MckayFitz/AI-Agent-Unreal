from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable
from uuid import uuid4

from app.code_patch_bundle_drafter import build_code_patch_bundle_draft
from app.task_orchestrator import build_agent_task_plan

AgentTool = Callable[[dict[str, Any]], None]


def start_agent_task_session(
    *,
    goal: str,
    files: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    matched_files: list[dict[str, Any]],
    family_summaries: dict[str, Any],
) -> dict[str, Any]:
    session = build_initial_session(
        goal=goal,
        files=files,
        assets=assets,
        matched_files=matched_files,
        family_summaries=family_summaries,
    )
    return run_agent_session_loop(session)


def confirm_agent_task_session(session: dict[str, Any], *, decision: str) -> dict[str, Any]:
    normalized_decision = (decision or "").strip().lower()
    if normalized_decision not in {"approve", "reject"}:
        return {"error": "Decision must be `approve` or `reject`."}

    pending = session.get("pending_confirmation")
    if not pending:
        return {"error": "This agent task does not have a pending confirmation."}

    session["steps"].append(
        build_step(
            tool_name="resolve_confirmation",
            status="completed",
            summary=f"User chose to {normalized_decision} the pending action.",
            output={"decision": normalized_decision, "action_type": pending.get("editor_action", {}).get("action_type")},
        )
    )

    session["pending_confirmation"] = None
    session["tool_state"]["awaiting_editor_apply"] = False
    session["tool_state"]["resume_requested"] = False

    if normalized_decision == "approve":
        session["approved_editor_action"] = deepcopy(pending.get("editor_action"))
        session["result"] = {
            "summary": "The previewed action was approved and is ready for editor-side execution. Resume the session to continue with follow-up planning.",
            "next_action": "resume_agent_session",
        }
        session["status"] = "ready_for_editor_apply"
        session["tool_state"]["awaiting_editor_apply"] = True
    else:
        session["approved_editor_action"] = None
        session["result"] = {
            "summary": "The previewed action was rejected. Narrow the task or regenerate a different draft before continuing.",
            "next_action": "revise_or_redraft",
        }
        session["status"] = "blocked"

    session["available_tools"] = determine_available_tools(session)
    return session


def resume_agent_task_session(session: dict[str, Any]) -> dict[str, Any]:
    if session.get("status") != "ready_for_editor_apply":
        return {"error": "Only approved agent task sessions can be resumed right now."}

    session["status"] = "running"
    session["tool_state"]["resume_requested"] = True
    session["available_tools"] = determine_available_tools(session)
    return run_agent_session_loop(session)


def build_initial_session(
    *,
    goal: str,
    files: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    matched_files: list[dict[str, Any]],
    family_summaries: dict[str, Any],
) -> dict[str, Any]:
    normalized_goal = (goal or "").strip()
    session = {
        "task_id": str(uuid4()),
        "goal": normalized_goal,
        "execution_mode": "agent_loop",
        "status": "running",
        "steps": [],
        "plan": None,
        "pending_confirmation": None,
        "approved_editor_action": None,
        "result": None,
        "available_tools": [],
        "tool_state": {
            "files": files,
            "assets": assets,
            "matched_files": matched_files,
            "family_summaries": family_summaries,
            "context_summary": None,
            "draft_bundle": None,
            "followup_assets": [],
            "supporting_asset_scaffolds": [],
            "resume_requested": False,
            "awaiting_editor_apply": False,
        },
    }
    session["available_tools"] = determine_available_tools(session)
    return session


def run_agent_session_loop(session: dict[str, Any], *, max_iterations: int = 8) -> dict[str, Any]:
    iterations = 0
    while iterations < max_iterations:
        tool_name = select_next_tool(session)
        session["available_tools"] = determine_available_tools(session)
        if not tool_name:
            finalize_session(session)
            session["available_tools"] = determine_available_tools(session)
            return session

        tool = TOOL_REGISTRY[tool_name]
        tool(session)
        session["available_tools"] = determine_available_tools(session)
        iterations += 1

        if session.get("status") in {"awaiting_confirmation", "ready_for_editor_apply", "blocked", "completed"}:
            return session

    session["status"] = "blocked"
    session["result"] = {
        "summary": "The agent session hit its current loop limit before reaching a stable next step.",
        "next_action": "refresh_or_resume_agent_session",
    }
    session["steps"].append(
        build_step(
            tool_name="loop_guard",
            status="blocked",
            summary="Paused because the current tool loop exceeded its safety limit.",
            output={"max_iterations": max_iterations},
        )
    )
    session["available_tools"] = determine_available_tools(session)
    return session


def select_next_tool(session: dict[str, Any]) -> str | None:
    if session.get("status") in {"awaiting_confirmation", "blocked", "completed"}:
        return None

    if has_tool_run(session, "resolve_confirmation") and session.get("status") == "ready_for_editor_apply":
        return None

    if not has_tool_run(session, "inspect_project_context"):
        return "inspect_project_context"

    if not has_tool_run(session, "plan_task"):
        return "plan_task"

    plan = session.get("plan") or {}
    task_type = plan.get("task_type", "")
    tool_state = session.get("tool_state", {})

    if tool_state.get("resume_requested"):
        if not has_tool_run(session, "prepare_editor_handoff"):
            return "prepare_editor_handoff"
        if should_plan_supporting_assets(session) and not has_tool_run(session, "plan_supporting_assets"):
            return "plan_supporting_assets"
        if tool_state.get("followup_assets") and not has_tool_run(session, "draft_supporting_asset_scaffolds"):
            return "draft_supporting_asset_scaffolds"
        return None

    if task_type in {"code_change", "code_generation", "hybrid_feature"} and not has_tool_run(session, "draft_code_patch_bundle"):
        return "draft_code_patch_bundle"

    draft_bundle = tool_state.get("draft_bundle") or {}
    if (
        draft_bundle.get("editor_action")
        and not session.get("pending_confirmation")
        and not has_tool_run(session, "request_confirmation")
    ):
        return "request_confirmation"

    if should_plan_supporting_assets(session) and not has_tool_run(session, "plan_supporting_assets"):
        return "plan_supporting_assets"

    return None


def determine_available_tools(session: dict[str, Any]) -> list[str]:
    if session.get("status") == "awaiting_confirmation":
        return ["confirm_agent_step"]
    if session.get("status") == "ready_for_editor_apply":
        return ["resume_agent_session"]
    if session.get("status") in {"blocked", "completed"}:
        return []

    available = []
    next_tool = select_next_tool(session)
    if next_tool:
        available.append(next_tool)
    return available


def tool_inspect_project_context(session: dict[str, Any]) -> None:
    tool_state = session["tool_state"]
    matched_files = tool_state["matched_files"]
    assets = tool_state["assets"]
    context_summary = {
        "matched_file_count": len(matched_files),
        "asset_count": len(assets),
        "strongest_file_match": matched_files[0]["path"] if matched_files else None,
    }
    tool_state["context_summary"] = context_summary
    session["steps"].append(
        build_step(
            tool_name="inspect_project_context",
            status="completed",
            summary="Inspected project context and ranked likely file owners before choosing the next tool.",
            output=context_summary,
        )
    )


def tool_plan_task(session: dict[str, Any]) -> None:
    tool_state = session["tool_state"]
    plan = build_agent_task_plan(
        goal=session["goal"],
        files=tool_state["files"],
        assets=tool_state["assets"],
        matched_files=tool_state["matched_files"],
        family_summaries=tool_state["family_summaries"],
    )
    session["plan"] = plan
    session["steps"].append(
        build_step(
            tool_name="plan_task",
            status="completed",
            summary=plan.get("summary", "Built a staged execution plan."),
            output={
                "task_type": plan.get("task_type"),
                "candidate_files": [item.get("path") for item in plan.get("candidate_files", [])[:4]],
                "candidate_assets": [item.get("name") for item in plan.get("candidate_assets", [])[:4]],
                "suggested_backend_routes": plan.get("suggested_backend_routes", []),
            },
        )
    )


def tool_draft_code_patch_bundle(session: dict[str, Any]) -> None:
    tool_state = session["tool_state"]
    draft = build_code_patch_bundle_draft(
        goal=session["goal"],
        files=tool_state["files"],
        matched_files=tool_state["matched_files"],
    )
    tool_state["draft_bundle"] = draft
    session["steps"].append(
        build_step(
            tool_name="draft_code_patch_bundle",
            status="completed",
            summary=draft.get("summary", "Drafted a preview-only code patch bundle."),
            output={
                "draft_file_count": len(draft.get("draft_files", [])),
                "warnings": draft.get("warnings", []),
                "edit_targets": [item.get("path") for item in draft.get("draft_files", [])],
            },
        )
    )


def tool_request_confirmation(session: dict[str, Any]) -> None:
    draft = session["tool_state"].get("draft_bundle") or {}
    editor_action = draft.get("editor_action")
    if not editor_action:
        return

    pending = build_pending_confirmation(draft)
    session["pending_confirmation"] = pending
    session["result"] = {
        "draft_summary": draft.get("summary", ""),
        "code_patch_bundle": {
            "draft_files": deepcopy(draft.get("draft_files", [])),
            "combined_unified_diff": draft.get("combined_unified_diff", ""),
        },
    }
    session["steps"].append(
        build_step(
            tool_name="request_confirmation",
            status="awaiting_confirmation",
            summary=pending["message"],
            output={
                "action_type": editor_action.get("action_type"),
                "target_paths": pending["target_paths"],
            },
            requires_confirmation=True,
        )
    )
    session["status"] = "awaiting_confirmation"
    session["tool_state"]["awaiting_editor_apply"] = True


def tool_prepare_editor_handoff(session: dict[str, Any]) -> None:
    task_type = (session.get("plan") or {}).get("task_type", "")
    session["steps"].append(
        build_step(
            tool_name="prepare_editor_handoff",
            status="completed",
            summary="Prepared the approved editor action for Unreal-side execution and continued with follow-up backend planning.",
            output={
                "approved_action_type": (session.get("approved_editor_action") or {}).get("action_type"),
                "task_type": task_type,
            },
        )
    )


def tool_plan_supporting_assets(session: dict[str, Any]) -> None:
    followup_assets = build_supporting_asset_followups(session)
    session["tool_state"]["followup_assets"] = followup_assets
    session["steps"].append(
        build_step(
            tool_name="plan_supporting_assets",
            status="completed",
            summary="Planned the next asset-side work that should follow the approved code/editor action.",
            output={"asset_followups": deepcopy(followup_assets)},
        )
    )


def tool_draft_supporting_asset_scaffolds(session: dict[str, Any]) -> None:
    scaffold_responses = []
    for followup in session["tool_state"].get("followup_assets", []):
        scaffold = build_supporting_asset_scaffold_response(followup)
        if scaffold:
            scaffold_responses.append(scaffold)

    session["tool_state"]["supporting_asset_scaffolds"] = scaffold_responses
    session["steps"].append(
        build_step(
            tool_name="draft_supporting_asset_scaffolds",
            status="completed",
            summary="Drafted concrete supporting asset scaffold responses for the next editor-side steps.",
            output={
                "asset_kinds": [item.get("asset_kind") for item in scaffold_responses],
                "recommended_asset_names": [item.get("recommended_asset_name") for item in scaffold_responses],
            },
        )
    )


TOOL_REGISTRY: dict[str, AgentTool] = {
    "inspect_project_context": tool_inspect_project_context,
    "plan_task": tool_plan_task,
    "draft_code_patch_bundle": tool_draft_code_patch_bundle,
    "request_confirmation": tool_request_confirmation,
    "prepare_editor_handoff": tool_prepare_editor_handoff,
    "plan_supporting_assets": tool_plan_supporting_assets,
    "draft_supporting_asset_scaffolds": tool_draft_supporting_asset_scaffolds,
}


def finalize_session(session: dict[str, Any]) -> None:
    if session.get("status") in {"awaiting_confirmation", "ready_for_editor_apply", "blocked", "completed"}:
        return

    plan = session.get("plan") or {}
    task_type = plan.get("task_type", "")
    followup_assets = session.get("tool_state", {}).get("followup_assets", [])
    supporting_asset_scaffolds = session.get("tool_state", {}).get("supporting_asset_scaffolds", [])

    if session.get("tool_state", {}).get("resume_requested"):
        session["status"] = "completed"
        session["result"] = {
            "summary": build_resume_summary(task_type, followup_assets),
            "next_action": "apply_in_editor_and_validate",
            "followup_asset_plans": followup_assets,
            "supporting_asset_scaffolds": supporting_asset_scaffolds,
            "approved_editor_action": deepcopy(session.get("approved_editor_action")),
        }
        session["tool_state"]["resume_requested"] = False
        return

    session["status"] = "completed"
    session["result"] = {
        "summary": plan.get("summary", "Agent session completed without a confirmation-gated action."),
        "plan": {
            "task_type": plan.get("task_type"),
            "stages": deepcopy(plan.get("stages", [])),
        },
        "followup_asset_plans": followup_assets,
        "supporting_asset_scaffolds": supporting_asset_scaffolds,
    }


def should_plan_supporting_assets(session: dict[str, Any]) -> bool:
    task_type = (session.get("plan") or {}).get("task_type", "")
    return task_type in {"hybrid_feature", "asset_creation", "asset_edit"}


def has_tool_run(session: dict[str, Any], tool_name: str) -> bool:
    return any(step.get("tool_name") == tool_name for step in session.get("steps", []))


def build_step(
    *,
    tool_name: str,
    status: str,
    summary: str,
    output: dict[str, Any] | None = None,
    requires_confirmation: bool = False,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "status": status,
        "summary": summary,
        "requires_confirmation": requires_confirmation,
        "output": output or {},
    }


def build_pending_confirmation(draft: dict[str, Any]) -> dict[str, Any]:
    editor_action = deepcopy(draft.get("editor_action", {}))
    target_paths = [item.get("path") for item in draft.get("draft_files", []) if item.get("path")]
    return {
        "kind": "editor_action",
        "message": "Review the previewed code bundle and confirm before the editor applies any file changes.",
        "editor_action": editor_action,
        "target_paths": target_paths,
    }


def build_supporting_asset_followups(session: dict[str, Any]) -> list[dict[str, Any]]:
    goal = (session.get("goal") or "").lower()
    followups = []

    if "input" in goal or "sprint" in goal or "jump" in goal or "fire" in goal or "interact" in goal:
        action_name = infer_action_name(goal)
        followups.append(
            {
                "asset_kind": "input_action",
                "recommended_name": f"IA_{action_name}",
                "recommended_path": "Content/Input/Actions",
                "purpose": f"{action_name} gameplay input",
                "why_next": "The code draft references an input action asset that should exist before final validation.",
            }
        )
        followups.append(
            {
                "asset_kind": "input_mapping_context",
                "recommended_name": "IMC_PlayerDefault",
                "recommended_path": "Content/Input/Contexts",
                "purpose": f"Default player bindings including {action_name}",
                "why_next": "The new input action still needs to be added to an active mapping context.",
            }
        )

    return followups


def infer_action_name(goal: str) -> str:
    lowered = (goal or "").lower()
    if "sprint" in lowered:
        return "Sprint"
    if "jump" in lowered:
        return "Jump"
    if "fire" in lowered or "shoot" in lowered:
        return "Fire"
    if "interact" in lowered:
        return "Interact"
    return "RequestedAction"


def build_resume_summary(task_type: str, followup_assets: list[dict[str, Any]]) -> str:
    if followup_assets:
        asset_names = ", ".join(item["recommended_name"] for item in followup_assets[:3])
        return (
            f"The agent session resumed after approval, prepared the editor handoff, and planned follow-up asset work "
            f"for `{task_type}`. Next recommended assets: {asset_names}."
        )
    return f"The agent session resumed after approval and prepared the next validation steps for `{task_type}`."


def build_supporting_asset_scaffold_response(followup: dict[str, Any]) -> dict[str, Any] | None:
    asset_kind = (followup.get("asset_kind") or "").strip()
    recommended_name = (followup.get("recommended_name") or "").strip()
    recommended_path = (followup.get("recommended_path") or "").strip()
    purpose = (followup.get("purpose") or "").strip()

    if asset_kind == "input_action":
        return build_simple_supporting_scaffold(
            asset_kind="input_action",
            recommended_name=recommended_name,
            recommended_path=recommended_path or "Content/Input/Actions",
            purpose=purpose,
            title="Input Action",
        )

    if asset_kind == "input_mapping_context":
        return build_simple_supporting_scaffold(
            asset_kind="input_mapping_context",
            recommended_name=recommended_name,
            recommended_path=recommended_path or "Content/Input/Contexts",
            purpose=purpose,
            title="Input Mapping Context",
        )

    return None


def build_simple_supporting_scaffold(
    *,
    asset_kind: str,
    recommended_name: str,
    recommended_path: str,
    purpose: str,
    title: str,
) -> dict[str, Any]:
    clean_name = recommended_name.strip()
    clean_path = normalize_content_path(recommended_path)
    package_name = convert_content_path_to_package_path(clean_path)
    asset_file_path = f"{clean_path.rstrip('/')}/{clean_name}"

    return {
        "asset_kind": asset_kind,
        "summary": f"Prepared a supporting {title} scaffold for the resumed agent task.",
        "recommended_asset_name": clean_name,
        "recommended_asset_path": asset_file_path,
        "purpose": purpose,
        "editor_action": {
            "action_type": "create_asset",
            "dry_run": False,
            "requires_user_confirmation": True,
            "arguments": {
                "asset_kind": asset_kind,
                "asset_name": clean_name,
                "package_path": package_name,
            },
        },
    }


def normalize_content_path(path: str) -> str:
    normalized = (path or "").replace("\\", "/").strip().strip("/")
    if not normalized:
        return "Content"
    if not normalized.startswith("Content/") and normalized != "Content":
        return f"Content/{normalized}"
    return normalized


def convert_content_path_to_package_path(path: str) -> str:
    normalized = normalize_content_path(path)
    if normalized == "Content":
        return "/Game"
    if normalized.startswith("Content/"):
        return f"/Game/{normalized[len('Content/'):]}"
    return f"/Game/{normalized}"
