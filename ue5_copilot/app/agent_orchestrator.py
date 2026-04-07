from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from app.code_patch_bundle_drafter import build_code_patch_bundle_draft
from app.code_patch_bundle_verification import (
    build_agent_session_approval_token,
    build_code_patch_bundle_file_checksums,
    build_code_patch_bundle_verification_token,
)
from app.task_orchestrator import build_agent_task_plan

Session = dict[str, Any]
ToolInputBuilder = Callable[[Session], dict[str, Any]]
ToolRunner = Callable[[Session, dict[str, Any]], dict[str, Any]]
AvailabilityRule = Callable[[Session], bool]


@dataclass(frozen=True)
class AgentToolSpec:
    name: str
    description: str
    phase: str
    input_schema: dict[str, Any]
    safety_level: str
    requires_confirmation: bool
    safe_to_autorun: bool
    build_input: ToolInputBuilder
    run: ToolRunner
    can_run: AvailabilityRule
    execution_target: str = "backend_orchestrator"
    mutates_project: bool = False
    capability_tags: tuple[str, ...] = ()
    backend_route: str | None = None
    editor_action_types: tuple[str, ...] = ()
    planner_task_types: tuple[str, ...] = ()
    planner_when_resumed: bool = False
    planner_when_approved: bool = False


def start_session(
    *,
    goal: str,
    files: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    matched_files: list[dict[str, Any]],
    family_summaries: dict[str, Any],
    auto_run: bool = True,
) -> Session:
    session = build_initial_session(
        goal=goal,
        files=files,
        assets=assets,
        matched_files=matched_files,
        family_summaries=family_summaries,
    )
    if auto_run:
        return run_session_loop(session)
    return session


def step_session(session: Session) -> Session:
    if session.get("status") in {"awaiting_confirmation", "ready_for_editor_apply", "blocked", "completed"}:
        refresh_orchestration_state(session)
        return session

    tool_name = select_next_tool(session)
    if not tool_name:
        finalize_session(session)
        refresh_orchestration_state(session)
        return session

    execute_tool(session, tool_name)
    refresh_orchestration_state(session)
    if not select_next_tool(session) and session.get("status") == "running":
        finalize_session(session)
        refresh_orchestration_state(session)
    return session


def run_session_loop(session: Session, *, max_iterations: int = 12) -> Session:
    iterations = 0
    while iterations < max_iterations:
        if session.get("status") in {"awaiting_confirmation", "ready_for_editor_apply", "blocked", "completed"}:
            refresh_orchestration_state(session)
            return session

        tool_name = select_next_tool(session)
        if not tool_name:
            finalize_session(session)
            refresh_orchestration_state(session)
            return session

        execute_tool(session, tool_name)
        refresh_orchestration_state(session)
        iterations += 1

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
    refresh_orchestration_state(session)
    return session


def confirm_session(session: Session, *, decision: str) -> Session:
    normalized_decision = (decision or "").strip().lower()
    if normalized_decision not in {"approve", "reject"}:
        return {"error": "Decision must be `approve` or `reject`."}

    pending = session.get("pending_confirmation")
    if not pending:
        return {"error": "This agent task does not have a pending confirmation."}

    session["pending_confirmation"] = None
    session["pending_decision"] = None
    session["tool_state"]["awaiting_editor_apply"] = False
    session["tool_state"]["confirmation_resolved"] = True

    session["steps"].append(
        build_step(
            tool_name="resolve_confirmation",
            status="completed",
            summary=f"User chose to {normalized_decision} the pending action.",
            output={
                "decision": normalized_decision,
                "action_type": pending.get("editor_action", {}).get("action_type"),
            },
        )
    )
    remember_tool_result(
        session,
        tool_name="resolve_confirmation",
        tool_input={"decision": normalized_decision},
        tool_output={"decision": normalized_decision},
    )

    if normalized_decision == "approve":
        session["approved_editor_action"] = deepcopy(pending.get("editor_action"))
        approved_files = deepcopy((session["approved_editor_action"] or {}).get("arguments", {}).get("files", []))
        verification_token = build_code_patch_bundle_verification_token(approved_files) if approved_files else ""
        approval_nonce = str(uuid4())
        session["artifacts"]["session_approval"] = {
            "task_id": session["task_id"],
            "approval_nonce": approval_nonce,
            "verification_token": verification_token,
            "approval_token": build_agent_session_approval_token(
                task_id=session["task_id"],
                verification_token=verification_token,
                approval_nonce=approval_nonce,
            ) if verification_token else "",
            "action_type": (session["approved_editor_action"] or {}).get("action_type"),
        }
        session["subtasks"] = build_subtasks_from_plan(session, session.get("plan") or {})
        session["result"] = {
            "summary": "The previewed action was approved and is ready for editor-side execution. Resume the session to continue with follow-up planning.",
            "next_action": "resume_agent_session",
        }
        session["status"] = "ready_for_editor_apply"
        session["tool_state"]["awaiting_editor_apply"] = True
    else:
        session["approved_editor_action"] = None
        session["artifacts"]["session_approval"] = None
        session["result"] = {
            "summary": "The previewed action was rejected. Narrow the task or regenerate a different draft before continuing.",
            "next_action": "revise_or_redraft",
        }
        session["status"] = "blocked"

    refresh_orchestration_state(session)
    return session


def resume_session(session: Session) -> Session:
    if session.get("status") != "ready_for_editor_apply":
        return {"error": "Only approved agent task sessions can be resumed right now."}

    session["status"] = "running"
    session["tool_state"]["resume_requested"] = True
    session["pending_decision"] = None
    session["subtasks"] = build_subtasks_from_plan(session, session.get("plan") or {})
    refresh_orchestration_state(session)
    return run_session_loop(session)


def confirm_and_continue_session(session: Session, *, decision: str) -> Session:
    updated_session = confirm_session(session, decision=decision)
    if updated_session.get("error"):
        return updated_session
    if (decision or "").strip().lower() != "approve":
        return updated_session
    return resume_session(updated_session)


def build_initial_session(
    *,
    goal: str,
    files: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    matched_files: list[dict[str, Any]],
    family_summaries: dict[str, Any],
) -> Session:
    normalized_goal = (goal or "").strip()
    session: Session = {
        "task_id": str(uuid4()),
        "goal": normalized_goal,
        "execution_mode": "agent_loop",
        "status": "running",
        "steps": [],
        "plan": None,
        "context": {
            "project_summary": None,
            "matched_files": deepcopy(matched_files),
            "candidate_files": [],
            "candidate_assets": [],
            "file_contexts": [],
            "selection_summary": None,
            "tool_preferences": {
                "preferred_tools": [],
                "suppressed_tools": [],
                "score_boosts": {},
                "required_artifacts": {},
                "stop_after_tools": [],
            },
        },
        "subtasks": [],
        "artifacts": {
            "search_results": [],
            "code_patch_bundle": None,
            "asset_plan": None,
            "editor_execution_package": None,
            "apply_ready_preview": None,
            "validation_commands": [],
            "supporting_asset_scaffolds": [],
            "progress_summary": None,
            "session_approval": None,
            "session_dry_run_receipt": None,
            "session_apply_status": None,
            "session_event_log": [],
        },
        "pending_confirmation": None,
        "pending_decision": None,
        "approved_editor_action": None,
        "result": None,
        "available_tools": [],
        "completed_tools": [],
        "last_tool_result": None,
        "tool_state": {
            "files": files,
            "assets": assets,
            "matched_files": matched_files,
            "family_summaries": family_summaries,
            "followup_assets": [],
            "resume_requested": False,
            "awaiting_editor_apply": False,
            "confirmation_resolved": False,
        },
        "orchestration": {
            "phase": "scoping",
            "progress": {"completed": 0, "total": 0, "current": None},
            "execution_state": {},
            "tool_catalog": [],
            "proposed_plan": [],
            "ranked_candidates": [],
            "execution_trace": [],
            "planner_summary": None,
        },
    }
    session["orchestration"]["tool_catalog"] = build_tool_catalog()
    refresh_orchestration_state(session)
    return session


def execute_tool(session: Session, tool_name: str) -> None:
    tool_spec = TOOL_REGISTRY[tool_name]
    tool_input = tool_spec.build_input(session)
    session["orchestration"]["execution_trace"].append(
        {
            "tool_name": tool_name,
            "phase": tool_spec.phase,
            "safe_to_autorun": tool_spec.safe_to_autorun,
        }
    )
    tool_output = tool_spec.run(session, tool_input)
    remember_tool_result(session, tool_name=tool_name, tool_input=tool_input, tool_output=tool_output)


def remember_tool_result(session: Session, *, tool_name: str, tool_input: dict[str, Any], tool_output: dict[str, Any]) -> None:
    session["last_tool_result"] = {
        "tool_name": tool_name,
        "input": deepcopy(tool_input),
        "output": deepcopy(tool_output),
    }
    if tool_name not in session["completed_tools"]:
        session["completed_tools"].append(tool_name)


def refresh_orchestration_state(session: Session) -> None:
    ranked_candidates = rank_candidate_tools(session)
    next_tool = ranked_candidates[0]["tool_name"] if ranked_candidates else None
    session["available_tools"] = determine_available_tools(session, next_tool=next_tool)
    session["orchestration"]["phase"] = determine_phase(session, next_tool=next_tool)
    session["orchestration"]["proposed_plan"] = build_proposed_plan(session, next_tool=next_tool)
    session["orchestration"]["progress"] = build_progress(session, next_tool=next_tool)
    session["orchestration"]["execution_state"] = build_execution_state(session)
    session["orchestration"]["ranked_candidates"] = ranked_candidates
    session["orchestration"]["execution_report"] = build_execution_report(session, next_tool=next_tool)


def select_next_tool(session: Session) -> str | None:
    if session.get("status") in {"awaiting_confirmation", "blocked", "completed"}:
        return None
    ranked_candidates = rank_candidate_tools(session)
    return ranked_candidates[0]["tool_name"] if ranked_candidates else None


def build_execution_state(session: Session) -> dict[str, Any]:
    artifacts = session.get("artifacts") or {}
    session_approval = artifacts.get("session_approval") or {}
    dry_run_receipt = artifacts.get("session_dry_run_receipt") or {}
    apply_status = artifacts.get("session_apply_status") or {}
    apply_ready_preview = artifacts.get("apply_ready_preview") or {}
    approved = bool(session_approval.get("approval_token"))
    resumed = "stage_apply_ready_preview" in session.get("completed_tools", [])
    dry_run_verified = bool(dry_run_receipt.get("receipt_token"))
    applied = bool(apply_status.get("applied"))
    apply_ready = bool(apply_ready_preview) and approved and not applied

    current_stage = "planning"
    next_required_action = None
    if applied:
        current_stage = "applied"
    elif dry_run_verified:
        current_stage = "dry_run_verified"
        next_required_action = "code_patch_bundle_apply"
    elif session.get("status") == "awaiting_confirmation":
        current_stage = "awaiting_confirmation"
        next_required_action = "confirm_agent_step"
    elif session.get("status") == "ready_for_editor_apply":
        current_stage = "approved_waiting_for_resume"
        next_required_action = "resume_agent_session"
    elif apply_ready:
        current_stage = "approved_waiting_for_dry_run"
        next_required_action = "code_patch_bundle_apply_dry_run"
    elif approved:
        current_stage = "approved"
    elif session.get("status") == "completed":
        current_stage = "completed"

    return {
        "approved": approved,
        "resumed": resumed,
        "dry_run_verified": dry_run_verified,
        "apply_ready": apply_ready,
        "applied": applied,
        "current_stage": current_stage,
        "next_required_action": next_required_action,
        "task_id": session.get("task_id"),
    }


def rank_candidate_tools(session: Session) -> list[dict[str, Any]]:
    if session.get("status") == "awaiting_confirmation":
        return [
            {
                "tool_name": "confirm_agent_step",
                "score": 1000,
                "phase": "confirmation",
                "reason": "Resolve the pending confirmation before any other orchestration step can continue.",
            }
        ]
    if session.get("status") == "ready_for_editor_apply":
        return [
            {
                "tool_name": "resume_agent_session",
                "score": 1000,
                "phase": "handoff",
                "reason": "Resume the approved session to prepare the editor handoff and validation package.",
            }
        ]
    if session.get("status") in {"blocked", "completed"}:
        return []

    ranked = []
    for tool in TOOL_SPECS:
        if not tool.can_run(session):
            continue
        if not planner_allows_tool(session, tool.name):
            continue
        score = score_tool_candidate(session, tool)
        ranked.append(
            {
                "tool_name": tool.name,
                "score": score,
                "phase": tool.phase,
                "reason": build_candidate_reason(session, tool),
            }
        )

    ranked.sort(key=lambda item: (-item["score"], item["tool_name"]))
    return ranked


def score_tool_candidate(session: Session, tool: AgentToolSpec) -> int:
    score = 0
    subtask_index = find_subtask_index(session, tool.name)
    if subtask_index is not None:
        score += max(0, 300 - (subtask_index * 10))

    if tool.name in {"request_confirmation", "resume_agent_session"}:
        score += 200

    phase_priority = {
        "scoping": 120,
        "planning": 90,
        "execution": 70,
        "confirmation": 110,
        "handoff": 60,
        "reporting": 20,
    }
    score += phase_priority.get(tool.phase, 0)

    if session.get("tool_state", {}).get("resume_requested") and tool.phase == "handoff":
        score += 80

    if tool.name == "summarize_progress" and len(session.get("completed_tools", [])) >= 3:
        score -= 40

    preferences = session.get("context", {}).get("tool_preferences", {})
    preferred_tools = preferences.get("preferred_tools", [])
    suppressed_tools = preferences.get("suppressed_tools", [])
    score_boosts = preferences.get("score_boosts", {})

    if tool.name in preferred_tools:
        score += 100
    if tool.name in suppressed_tools:
        score -= 200
    score += int(score_boosts.get(tool.name, 0))

    return score


def build_candidate_reason(session: Session, tool: AgentToolSpec) -> str:
    for item in session.get("subtasks", []):
        if item.get("tool_name") == tool.name:
            return item.get("reason", tool.description)
    return tool.description


def planner_allows_tool(session: Session, tool_name: str) -> bool:
    preferences = session.get("context", {}).get("tool_preferences", {})
    required_artifacts = preferences.get("required_artifacts", {})
    requirements = required_artifacts.get(tool_name, [])
    for requirement in requirements:
        if not session_has_artifact(session, requirement):
            return False
    return True


def session_has_artifact(session: Session, artifact_name: str) -> bool:
    artifacts = session.get("artifacts", {})
    context = session.get("context", {})
    tool_state = session.get("tool_state", {})

    if artifact_name == "search_results":
        return bool(artifacts.get("search_results"))
    if artifact_name == "candidate_files_or_assets":
        return bool(context.get("candidate_files") or context.get("candidate_assets"))
    if artifact_name == "selection_summary":
        return bool(context.get("selection_summary"))
    if artifact_name == "code_patch_bundle":
        return bool(artifacts.get("code_patch_bundle"))
    if artifact_name == "approved_editor_action":
        return bool(session.get("approved_editor_action"))
    if artifact_name == "editor_execution_package":
        return bool(artifacts.get("editor_execution_package"))
    if artifact_name == "apply_ready_preview":
        return bool(artifacts.get("apply_ready_preview"))
    if artifact_name == "validation_commands":
        return bool(artifacts.get("validation_commands"))
    if artifact_name == "followup_assets":
        return bool(tool_state.get("followup_assets"))
    if artifact_name == "analysis_complete":
        return "analyze_selection" in session.get("completed_tools", [])
    return False


def find_subtask_index(session: Session, tool_name: str) -> int | None:
    for index, item in enumerate(session.get("subtasks", [])):
        if item.get("tool_name") == tool_name:
            return index
    return None


def determine_available_tools(session: Session, *, next_tool: str | None) -> list[str]:
    if session.get("status") == "awaiting_confirmation":
        return ["confirm_agent_step"]
    if session.get("status") == "ready_for_editor_apply":
        return ["resume_agent_session"]
    if session.get("status") in {"blocked", "completed"}:
        return []
    return [next_tool] if next_tool else []


def determine_phase(session: Session, *, next_tool: str | None) -> str:
    if session.get("status") == "awaiting_confirmation":
        return "awaiting_confirmation"
    if session.get("status") == "ready_for_editor_apply":
        return "approved_waiting_for_resume"
    if session.get("status") == "completed":
        return "completed"
    if session.get("status") == "blocked":
        return "blocked"
    if next_tool:
        return TOOL_REGISTRY[next_tool].phase
    last_tool_name = (session.get("last_tool_result") or {}).get("tool_name")
    if last_tool_name and last_tool_name in TOOL_REGISTRY:
        return TOOL_REGISTRY[last_tool_name].phase
    return "planning"


def build_progress(session: Session, *, next_tool: str | None) -> dict[str, Any]:
    proposed_plan = session["orchestration"].get("proposed_plan", [])
    completed = len([item for item in proposed_plan if item.get("state") == "completed"])
    total = len(proposed_plan)
    current = next_tool
    if session.get("status") == "awaiting_confirmation":
        current = "confirm_agent_step"
    elif session.get("status") == "ready_for_editor_apply":
        current = "resume_agent_session"
    return {"completed": completed, "total": total, "current": current}


def build_execution_report(session: Session, *, next_tool: str | None) -> dict[str, Any]:
    context = session.get("context") or {}
    plan = session.get("plan") or {}
    orchestration = session.get("orchestration") or {}
    artifacts = session.get("artifacts") or {}
    pending_confirmation = session.get("pending_confirmation") or {}
    approved_editor_action = session.get("approved_editor_action") or {}
    next_tool_spec = TOOL_REGISTRY.get(next_tool) if next_tool else None
    ranked_candidates = orchestration.get("ranked_candidates", [])
    candidate_files = context.get("candidate_files", [])[:3]
    candidate_assets = context.get("candidate_assets", [])[:3]
    progress = orchestration.get("progress", {})
    execution_state = orchestration.get("execution_state", {})

    return {
        "goal": session.get("goal", ""),
        "status": session.get("status"),
        "phase": orchestration.get("phase"),
        "task_type": plan.get("task_type"),
        "summary": (session.get("result") or {}).get("summary")
        or artifacts.get("progress_summary")
        or plan.get("summary", ""),
        "project_context": {
            "project_summary": deepcopy(context.get("project_summary")),
            "candidate_files": deepcopy(candidate_files),
            "candidate_assets": deepcopy(candidate_assets),
            "selection_summary": deepcopy(context.get("selection_summary")),
        },
        "tooling": {
            "available_tools": deepcopy(session.get("available_tools", [])),
            "next_tool": next_tool,
            "next_tool_description": next_tool_spec.description if next_tool_spec else "",
            "top_ranked_candidates": deepcopy(ranked_candidates[:3]),
            "proposed_plan": deepcopy(orchestration.get("proposed_plan", [])),
        },
        "progress": {
            "completed": progress.get("completed", 0),
            "total": progress.get("total", 0),
            "current": progress.get("current"),
            "completed_tools": deepcopy(session.get("completed_tools", [])),
        },
        "confirmation": {
            "awaiting_confirmation": session.get("status") == "awaiting_confirmation",
            "pending_action_type": (pending_confirmation.get("editor_action") or {}).get("action_type"),
            "pending_target_paths": deepcopy(pending_confirmation.get("target_paths", [])),
            "approved_action_type": approved_editor_action.get("action_type"),
            "ready_for_editor_apply": session.get("status") == "ready_for_editor_apply",
        },
        "handoff": {
            "execution_state": deepcopy(execution_state),
            "has_editor_execution_package": bool(artifacts.get("editor_execution_package")),
            "has_apply_ready_preview": bool(artifacts.get("apply_ready_preview")),
            "validation_command_labels": [item.get("label") for item in artifacts.get("validation_commands", [])],
            "followup_asset_names": [item.get("recommended_name") for item in session.get("tool_state", {}).get("followup_assets", [])],
        },
    }


def build_proposed_plan(session: Session, *, next_tool: str | None) -> list[dict[str, Any]]:
    proposed = []
    for subtask in session.get("subtasks", []):
        tool_name = subtask.get("tool_name")
        if not tool_name or tool_name not in TOOL_REGISTRY:
            continue
        state = "completed" if tool_name in session.get("completed_tools", []) else "pending"
        if tool_name == next_tool and session.get("status") == "running":
            state = "in_progress"
        if tool_name == "request_confirmation" and session.get("status") == "awaiting_confirmation":
            state = "in_progress"
        if tool_name == "prepare_editor_handoff" and session.get("status") == "ready_for_editor_apply":
            state = "pending"
        proposed.append(
            {
                "tool_name": tool_name,
                "description": TOOL_REGISTRY[tool_name].description,
                "phase": TOOL_REGISTRY[tool_name].phase,
                "state": state,
                "reason": subtask.get("reason", ""),
            }
        )
    return proposed


def build_tool_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "phase": tool.phase,
            "input_schema": deepcopy(tool.input_schema),
            "safety_level": tool.safety_level,
            "requires_confirmation": tool.requires_confirmation,
            "safe_to_autorun": tool.safe_to_autorun,
            "execution_target": tool.execution_target,
            "mutates_project": tool.mutates_project,
            "capability_tags": list(tool.capability_tags),
            "backend_route": tool.backend_route,
            "editor_action_types": list(tool.editor_action_types),
        }
        for tool in TOOL_SPECS
    ]


def finalize_session(session: Session) -> None:
    if session.get("status") in {"awaiting_confirmation", "ready_for_editor_apply", "blocked", "completed"}:
        return

    if should_stop_after_completed_tool(session):
        if "summarize_progress" not in session.get("completed_tools", []) and TOOL_REGISTRY["summarize_progress"].can_run(session):
            execute_tool(session, "summarize_progress")
        session["status"] = "completed"
        session["result"] = {
            "summary": session["artifacts"].get("progress_summary")
            or "The planner stopped the session after the requested analysis stage.",
            "plan": {
                "task_type": (session.get("plan") or {}).get("task_type"),
                "stages": deepcopy((session.get("plan") or {}).get("stages", [])),
            },
            "followup_asset_plans": session["tool_state"].get("followup_assets", []),
            "supporting_asset_scaffolds": session["artifacts"].get("supporting_asset_scaffolds", []),
        }
        return

    if "summarize_progress" not in session.get("completed_tools", []) and TOOL_REGISTRY["summarize_progress"].can_run(session):
        execute_tool(session, "summarize_progress")

    if session.get("tool_state", {}).get("resume_requested"):
        session["status"] = "completed"
        session["result"] = {
            "summary": session["artifacts"].get("progress_summary") or "The agent resumed and completed its planned follow-up work.",
            "next_action": "apply_in_editor_and_validate",
            "followup_asset_plans": session["tool_state"].get("followup_assets", []),
            "editor_execution_package": session["artifacts"].get("editor_execution_package"),
            "apply_ready_preview": session["artifacts"].get("apply_ready_preview"),
            "validation_commands": session["artifacts"].get("validation_commands", []),
            "supporting_asset_scaffolds": session["artifacts"].get("supporting_asset_scaffolds", []),
            "approved_editor_action": deepcopy(session.get("approved_editor_action")),
        }
        session["tool_state"]["resume_requested"] = False
        return

    session["status"] = "completed"
    session["result"] = {
        "summary": session["artifacts"].get("progress_summary")
        or (session.get("plan") or {}).get("summary")
        or "Agent session completed without a confirmation-gated action.",
        "plan": {
            "task_type": (session.get("plan") or {}).get("task_type"),
            "stages": deepcopy((session.get("plan") or {}).get("stages", [])),
        },
        "followup_asset_plans": session["tool_state"].get("followup_assets", []),
        "supporting_asset_scaffolds": session["artifacts"].get("supporting_asset_scaffolds", []),
    }


def should_stop_after_completed_tool(session: Session) -> bool:
    preferences = session.get("context", {}).get("tool_preferences", {})
    stop_after_tools = preferences.get("stop_after_tools", [])
    if session.get("tool_state", {}).get("resume_requested"):
        return False
    if session.get("pending_confirmation"):
        return False
    if not stop_after_tools:
        return False
    completed_tools = session.get("completed_tools", [])
    return any(tool_name in completed_tools for tool_name in stop_after_tools)


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


def build_tool_input_from_goal(session: Session) -> dict[str, Any]:
    return {"goal": session.get("goal", "")}


def build_search_input(session: Session) -> dict[str, Any]:
    return {"query": session.get("goal", ""), "max_results": 6}


def build_read_file_input(session: Session) -> dict[str, Any]:
    search_results = session["artifacts"].get("search_results", [])
    return {
        "paths": [item.get("path") for item in search_results[:3] if item.get("path")],
        "preview_chars": 500,
    }


def build_analyze_selection_input(session: Session) -> dict[str, Any]:
    plan = session.get("plan") or {}
    return {
        "candidate_files": deepcopy(plan.get("candidate_files", [])[:4]),
        "candidate_assets": deepcopy(plan.get("candidate_assets", [])[:4]),
    }


def build_code_patch_input(session: Session) -> dict[str, Any]:
    return {"goal": session.get("goal", "")}


def build_asset_plan_input(session: Session) -> dict[str, Any]:
    return {"goal": session.get("goal", ""), "task_type": (session.get("plan") or {}).get("task_type", "")}


def build_confirmation_input(session: Session) -> dict[str, Any]:
    draft = session["artifacts"].get("code_patch_bundle") or {}
    return {"draft_summary": draft.get("summary", ""), "editor_action": deepcopy(draft.get("editor_action", {}))}


def build_resume_input(session: Session) -> dict[str, Any]:
    return {"approved_editor_action": deepcopy(session.get("approved_editor_action"))}


def build_execution_package_input(session: Session) -> dict[str, Any]:
    return {
        "approved_editor_action": deepcopy(session.get("approved_editor_action")),
        "goal": session.get("goal", ""),
        "followup_assets": deepcopy(session["tool_state"].get("followup_assets", [])),
    }


def build_editor_execution_artifact_input(session: Session) -> dict[str, Any]:
    return {
        "goal": session.get("goal", ""),
        "task_type": (session.get("plan") or {}).get("task_type", ""),
        "editor_execution_package": deepcopy(session["artifacts"].get("editor_execution_package")),
    }


def build_progress_input(session: Session) -> dict[str, Any]:
    return {
        "goal": session.get("goal", ""),
        "completed_tools": deepcopy(session.get("completed_tools", [])),
        "task_type": (session.get("plan") or {}).get("task_type", ""),
    }


def tool_inspect_project_context(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    matched_files = session["tool_state"]["matched_files"]
    assets = session["tool_state"]["assets"]
    files = session["tool_state"]["files"]
    context_summary = {
        "matched_file_count": len(matched_files),
        "file_count": len(files),
        "asset_count": len(assets),
        "strongest_file_match": matched_files[0]["path"] if matched_files else None,
    }
    session["context"]["project_summary"] = context_summary
    session["steps"].append(
        build_step(
            tool_name="inspect_project_context",
            status="completed",
            summary="Inspected project context and captured the initial project summary.",
            output=context_summary,
        )
    )
    return context_summary


def tool_plan_task(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    plan = build_agent_task_plan(
        goal=session["goal"],
        files=session["tool_state"]["files"],
        assets=session["tool_state"]["assets"],
        matched_files=session["tool_state"]["matched_files"],
        family_summaries=session["tool_state"]["family_summaries"],
    )
    session["plan"] = plan
    session["context"]["candidate_files"] = deepcopy(plan.get("candidate_files", [])[:6])
    session["context"]["candidate_assets"] = deepcopy(plan.get("candidate_assets", [])[:6])
    session["context"]["tool_preferences"] = deepcopy(plan.get("tool_preferences", {}))
    session["subtasks"] = build_subtasks_from_plan(session, plan)
    session["orchestration"]["planner_summary"] = plan.get("summary", "")
    output = {
        "task_type": plan.get("task_type"),
        "candidate_files": [item.get("path") for item in plan.get("candidate_files", [])[:4]],
        "candidate_assets": [item.get("name") for item in plan.get("candidate_assets", [])[:4]],
        "suggested_backend_routes": plan.get("suggested_backend_routes", []),
        "recommended_tool_chain": plan.get("recommended_tool_chain", []),
        "unreal_tool_catalog": deepcopy(plan.get("unreal_tool_catalog", [])),
        "tool_preferences": deepcopy(plan.get("tool_preferences", {})),
        "proposed_tools": [item.get("tool_name") for item in session["subtasks"]],
    }
    session["steps"].append(
        build_step(
            tool_name="plan_task",
            status="completed",
            summary=plan.get("summary", "Built a staged execution plan."),
            output=output,
        )
    )
    return output


def tool_search_project(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    matches = session["tool_state"].get("matched_files") or search_files_locally(
        session["tool_state"]["files"],
        tool_input.get("query", ""),
        max_results=tool_input.get("max_results", 6),
    )
    session["artifacts"]["search_results"] = deepcopy(matches[:6])
    output = {
        "query": tool_input.get("query", ""),
        "result_count": len(matches[:6]),
        "paths": [item.get("path") for item in matches[:6]],
    }
    session["steps"].append(
        build_step(
            tool_name="search_project",
            status="completed",
            summary="Searched the scanned project for files most relevant to the task.",
            output=output,
        )
    )
    return output


def tool_read_file_context(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    file_contexts = []
    file_map = {item.get("path"): item for item in session["tool_state"]["files"]}
    for path in tool_input.get("paths", []):
        file_record = file_map.get(path)
        if not file_record:
            continue
        content = file_record.get("content", "")
        file_contexts.append(
            {
                "path": path,
                "snippet": content[: tool_input.get("preview_chars", 500)],
                "name": file_record.get("name", ""),
            }
        )
    session["context"]["file_contexts"] = file_contexts
    output = {
        "file_count": len(file_contexts),
        "paths": [item.get("path") for item in file_contexts],
    }
    session["steps"].append(
        build_step(
            tool_name="read_file_context",
            status="completed",
            summary="Read concise file context for the highest-signal files before execution.",
            output=output,
        )
    )
    return output


def tool_analyze_selection(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    candidate_files = tool_input.get("candidate_files", [])
    candidate_assets = tool_input.get("candidate_assets", [])
    selection_summary = {
        "lead_file": candidate_files[0]["path"] if candidate_files else None,
        "lead_asset": candidate_assets[0]["name"] if candidate_assets else None,
        "task_type": (session.get("plan") or {}).get("task_type", ""),
    }
    session["context"]["selection_summary"] = selection_summary
    session["artifacts"]["asset_plan"] = {
        "candidate_assets": deepcopy(candidate_assets),
        "family_hints": deepcopy((session.get("plan") or {}).get("family_hints", [])),
    }
    session["steps"].append(
        build_step(
            tool_name="analyze_selection",
            status="completed",
            summary="Analyzed the strongest file and asset owners for the requested task.",
            output=selection_summary,
        )
    )
    return selection_summary


def tool_draft_asset_plan(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    followup_assets = build_supporting_asset_followups(session)
    session["tool_state"]["followup_assets"] = followup_assets
    asset_plan = {
        "task_type": tool_input.get("task_type", ""),
        "followup_assets": deepcopy(followup_assets),
        "candidate_assets": deepcopy((session["artifacts"].get("asset_plan") or {}).get("candidate_assets", [])),
    }
    session["artifacts"]["asset_plan"] = asset_plan
    session["steps"].append(
        build_step(
            tool_name="draft_asset_plan",
            status="completed",
            summary="Drafted the asset-side plan that complements the requested implementation work.",
            output={
                "followup_asset_names": [item.get("recommended_name") for item in followup_assets],
                "task_type": tool_input.get("task_type", ""),
            },
        )
    )
    return asset_plan


def tool_draft_code_patch_bundle(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    draft = build_code_patch_bundle_draft(
        goal=tool_input.get("goal", ""),
        files=session["tool_state"]["files"],
        matched_files=session["tool_state"]["matched_files"],
    )
    session["artifacts"]["code_patch_bundle"] = draft
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
    return {
        "draft_file_count": len(draft.get("draft_files", [])),
        "requires_confirmation": bool(draft.get("editor_action")),
    }


def tool_request_confirmation(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    draft = session["artifacts"].get("code_patch_bundle") or {}
    editor_action = draft.get("editor_action")
    if not editor_action:
        return {"requested": False}

    pending = build_pending_confirmation(draft)
    session["pending_confirmation"] = pending
    session["pending_decision"] = {
        "decision_type": "confirm_editor_action",
        "tool_name": "request_confirmation",
        "message": pending["message"],
    }
    session["result"] = {
        "draft_summary": draft.get("summary", ""),
        "code_patch_bundle": {
            "draft_files": deepcopy(draft.get("draft_files", [])),
            "combined_unified_diff": draft.get("combined_unified_diff", ""),
        },
    }
    session["status"] = "awaiting_confirmation"
    session["tool_state"]["awaiting_editor_apply"] = True
    session["steps"].append(
        build_step(
            tool_name="request_confirmation",
            status="awaiting_confirmation",
            summary=pending["message"],
            output={"action_type": editor_action.get("action_type"), "target_paths": pending["target_paths"]},
            requires_confirmation=True,
        )
    )
    return {"requested": True, "action_type": editor_action.get("action_type")}


def tool_stage_editor_execution_package(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    approved_action = tool_input.get("approved_editor_action") or {}
    package = {
        "goal": tool_input.get("goal", ""),
        "approved_editor_action": deepcopy(approved_action),
        "followup_assets": deepcopy(tool_input.get("followup_assets", [])),
        "validation_checklist": [
            "Apply the approved editor action against the expected target files or assets.",
            "Verify hashes or target paths still match before mutating anything.",
            "Run the smallest useful validation pass after the apply step.",
        ],
    }
    session["artifacts"]["editor_execution_package"] = package
    session["steps"].append(
        build_step(
            tool_name="stage_editor_execution_package",
            status="completed",
            summary="Staged a concrete editor execution package from the approved action.",
            output={
                "action_type": approved_action.get("action_type"),
                "followup_asset_count": len(package["followup_assets"]),
            },
        )
    )
    return package


def tool_stage_apply_ready_preview(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    execution_package = tool_input.get("editor_execution_package") or {}
    approved_action = execution_package.get("approved_editor_action") or {}
    preview = {
        "goal": tool_input.get("goal", ""),
        "task_type": tool_input.get("task_type", ""),
        "action_type": approved_action.get("action_type"),
        "requires_confirmation": bool(approved_action.get("requires_user_confirmation")),
        "arguments": deepcopy(approved_action.get("arguments", {})),
        "apply_instructions": [
            "Use the staged approved action exactly as previewed.",
            "Verify the target paths or asset package paths still match before applying.",
            "If hashes differ, regenerate the preview instead of forcing the apply.",
        ],
    }
    if approved_action.get("action_type") == "apply_code_patch_bundle_preview":
        files = deepcopy(approved_action.get("arguments", {}).get("files", []))
        verification_token = build_code_patch_bundle_verification_token(files)
        session_approval = deepcopy(session["artifacts"].get("session_approval") or {})
        preview["dry_run_route"] = "/code-patch-bundle-apply-dry-run"
        preview["dry_run_request"] = {
            "files": files,
            "task_id": session_approval.get("task_id"),
            "approval_token": session_approval.get("approval_token"),
        }
        preview["verification_bundle"] = {
            "verification_token": verification_token,
            "file_checksums": build_code_patch_bundle_file_checksums(files),
        }
        preview["session_approval"] = {
            "task_id": session_approval.get("task_id"),
            "approval_token": session_approval.get("approval_token"),
            "action_type": session_approval.get("action_type"),
        }
        preview["dry_run_receipt"] = {
            "required_for_final_apply": True,
            "source": "code-patch-bundle-apply-dry-run response",
            "field": "receipt_token",
        }
        preview["final_apply_route"] = "/code-patch-bundle-apply"
        preview["final_apply_request"] = {
            "files": files,
            "dry_run_verified": True,
            "verification_token": verification_token,
            "task_id": session_approval.get("task_id"),
            "approval_token": session_approval.get("approval_token"),
            "receipt_token": None,
        }
    session["artifacts"]["apply_ready_preview"] = preview
    session["steps"].append(
        build_step(
            tool_name="stage_apply_ready_preview",
            status="completed",
            summary="Staged an apply-ready preview payload from the approved execution package.",
            output={
                "action_type": preview.get("action_type"),
                "requires_confirmation": preview.get("requires_confirmation"),
                "has_dry_run_request": bool(preview.get("dry_run_request")),
            },
        )
    )
    return preview


def tool_stage_validation_commands(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    execution_package = tool_input.get("editor_execution_package") or {}
    approved_action = execution_package.get("approved_editor_action") or {}
    task_type = tool_input.get("task_type", "")

    commands = [
        {
            "kind": "verify_targets",
            "label": "Verify target paths and hashes",
            "command": "Confirm the approved target files or asset package paths still match the staged preview.",
            "safe": True,
        }
    ]
    if approved_action.get("action_type") == "apply_code_patch_bundle_preview":
        commands.append(
            {
                "kind": "backend_tests",
                "label": "Run API contract tests",
                "command": ".\\venv\\Scripts\\python.exe -m unittest tests.test_api_contracts",
                "safe": True,
            }
        )
    if task_type in {"hybrid_feature", "asset_creation", "asset_edit"}:
        commands.append(
            {
                "kind": "editor_validation",
                "label": "Validate in editor",
                "command": "Open the affected asset or gameplay flow in Unreal Editor and validate the smallest end-to-end path.",
                "safe": True,
            }
        )

    session["artifacts"]["validation_commands"] = commands
    session["steps"].append(
        build_step(
            tool_name="stage_validation_commands",
            status="completed",
            summary="Staged safe validation commands and checks for the approved execution package.",
            output={"command_labels": [item["label"] for item in commands]},
        )
    )
    return {"commands": commands}


def tool_prepare_editor_handoff(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    task_type = (session.get("plan") or {}).get("task_type", "")
    output = {
        "approved_action_type": (tool_input.get("approved_editor_action") or {}).get("action_type"),
        "task_type": task_type,
    }
    session["steps"].append(
        build_step(
            tool_name="prepare_editor_handoff",
            status="completed",
            summary="Prepared the approved editor action for Unreal-side execution and continued with follow-up planning.",
            output=output,
        )
    )
    return output


def tool_draft_supporting_asset_scaffolds(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    scaffold_responses = []
    for followup in session["tool_state"].get("followup_assets", []):
        scaffold = build_supporting_asset_scaffold_response(followup)
        if scaffold:
            scaffold_responses.append(scaffold)

    session["artifacts"]["supporting_asset_scaffolds"] = scaffold_responses
    output = {
        "asset_kinds": [item.get("asset_kind") for item in scaffold_responses],
        "recommended_asset_names": [item.get("recommended_asset_name") for item in scaffold_responses],
    }
    session["steps"].append(
        build_step(
            tool_name="draft_supporting_asset_scaffolds",
            status="completed",
            summary="Drafted scaffold responses for the next editor-side asset steps.",
            output=output,
        )
    )
    return output


def tool_summarize_progress(session: Session, tool_input: dict[str, Any]) -> dict[str, Any]:
    task_type = tool_input.get("task_type", "")
    completed_tools = tool_input.get("completed_tools", [])
    followup_assets = session["tool_state"].get("followup_assets", [])
    if session.get("tool_state", {}).get("resume_requested"):
        summary = build_resume_summary(task_type, followup_assets)
    elif session.get("pending_confirmation"):
        summary = "The agent gathered context, drafted a patch preview, and is waiting for confirmation before any editor-side apply step."
    else:
        summary = (
            f"The agent inspected context, planned `{task_type}`, and completed {len(completed_tools)} tool steps "
            f"toward the goal `{tool_input.get('goal', '')}`."
        )
    session["artifacts"]["progress_summary"] = summary
    session["steps"].append(
        build_step(
            tool_name="summarize_progress",
            status="completed",
            summary="Summarized the current orchestration progress and next step.",
            output={"summary": summary},
        )
    )
    return {"summary": summary}


def build_pending_confirmation(draft: dict[str, Any]) -> dict[str, Any]:
    editor_action = deepcopy(draft.get("editor_action", {}))
    target_paths = [item.get("path") for item in draft.get("draft_files", []) if item.get("path")]
    return {
        "kind": "editor_action",
        "message": "Review the previewed code bundle and confirm before the editor applies any file changes.",
        "editor_action": editor_action,
        "target_paths": target_paths,
    }


def build_subtasks_from_plan(session: Session, plan: dict[str, Any]) -> list[dict[str, Any]]:
    task_type = plan.get("task_type", "")
    subtasks = []
    for tool in TOOL_SPECS:
        if not should_include_tool_in_plan(session, plan, tool):
            continue
        subtasks.append({"tool_name": tool.name, "reason": build_plan_reason(tool, task_type)})
    return subtasks


def should_include_tool_in_plan(session: Session, plan: dict[str, Any], tool: AgentToolSpec) -> bool:
    task_type = plan.get("task_type", "")
    resumed = bool(session.get("tool_state", {}).get("resume_requested"))
    approved = bool(session.get("approved_editor_action"))

    if tool.planner_when_resumed:
        return resumed or approved
    if tool.planner_when_approved:
        return approved
    if not tool.planner_task_types:
        return not resumed
    return task_type in tool.planner_task_types and not resumed


def build_plan_reason(tool: AgentToolSpec, task_type: str) -> str:
    reason_map = {
        "inspect_project_context": "Capture project context before any planning.",
        "plan_task": "Turn the goal into explicit subgoals and candidate tools.",
        "search_project": "Search the project for the strongest code owners.",
        "read_file_context": "Read concise context from the highest-signal files.",
        "analyze_selection": "Analyze the strongest file and asset owners.",
        "draft_asset_plan": f"Draft the asset-side plan for `{task_type}` work.",
        "draft_code_patch_bundle": f"Prepare a preview-only code patch bundle for `{task_type}` work.",
        "request_confirmation": "Pause before any editor-side apply step.",
        "stage_editor_execution_package": "Stage a concrete execution package from the approved action.",
        "prepare_editor_handoff": "Prepare the approved editor handoff.",
        "stage_apply_ready_preview": "Stage an apply-ready preview payload from the approved execution package.",
        "stage_validation_commands": "Stage safe validation commands and checks for the approved execution package.",
        "draft_supporting_asset_scaffolds": "Draft supporting asset scaffolds after approval.",
        "summarize_progress": "Summarize execution progress and next steps.",
    }
    return reason_map.get(tool.name, tool.description)


def build_supporting_asset_followups(session: Session) -> list[dict[str, Any]]:
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


def search_files_locally(files: list[dict[str, Any]], query: str, *, max_results: int) -> list[dict[str, Any]]:
    tokens = [token for token in query.lower().split() if len(token) > 2]
    scored = []
    for file_record in files:
        haystack = f"{file_record.get('path', '')}\n{file_record.get('content', '')}".lower()
        score = sum(1 for token in tokens if token in haystack)
        if score <= 0:
            continue
        scored.append(
            {
                "path": file_record.get("path", ""),
                "snippet": file_record.get("content", "")[:300],
                "score": score,
            }
        )
    scored.sort(key=lambda item: item.get("score", 0), reverse=True)
    return scored[:max_results]


def can_run_inspect_project_context(session: Session) -> bool:
    return session.get("status") == "running" and "inspect_project_context" not in session.get("completed_tools", [])


def can_run_plan_task(session: Session) -> bool:
    return session.get("status") == "running" and "inspect_project_context" in session.get("completed_tools", []) and "plan_task" not in session.get("completed_tools", [])


def can_run_search_project(session: Session) -> bool:
    return session.get("status") == "running" and "plan_task" in session.get("completed_tools", []) and "search_project" not in session.get("completed_tools", [])


def can_run_read_file_context(session: Session) -> bool:
    return session.get("status") == "running" and "search_project" in session.get("completed_tools", []) and "read_file_context" not in session.get("completed_tools", [])


def can_run_analyze_selection(session: Session) -> bool:
    return session.get("status") == "running" and "read_file_context" in session.get("completed_tools", []) and "analyze_selection" not in session.get("completed_tools", [])


def can_run_draft_asset_plan(session: Session) -> bool:
    task_type = (session.get("plan") or {}).get("task_type", "")
    return (
        session.get("status") == "running"
        and "analyze_selection" in session.get("completed_tools", [])
        and "draft_asset_plan" not in session.get("completed_tools", [])
        and task_type in {"asset_creation", "asset_edit", "hybrid_feature"}
        and not session.get("tool_state", {}).get("resume_requested")
    )


def can_run_draft_code_patch_bundle(session: Session) -> bool:
    task_type = (session.get("plan") or {}).get("task_type", "")
    return (
        session.get("status") == "running"
        and "analyze_selection" in session.get("completed_tools", [])
        and "draft_code_patch_bundle" not in session.get("completed_tools", [])
        and task_type in {"code_change", "code_generation", "hybrid_feature"}
        and not session.get("tool_state", {}).get("resume_requested")
    )


def can_run_request_confirmation(session: Session) -> bool:
    draft = session["artifacts"].get("code_patch_bundle") or {}
    return (
        session.get("status") == "running"
        and "draft_code_patch_bundle" in session.get("completed_tools", [])
        and "request_confirmation" not in session.get("completed_tools", [])
        and bool(draft.get("editor_action"))
    )


def can_run_prepare_editor_handoff(session: Session) -> bool:
    return (
        session.get("status") == "running"
        and session.get("tool_state", {}).get("resume_requested")
        and "stage_validation_commands" in session.get("completed_tools", [])
        and "prepare_editor_handoff" not in session.get("completed_tools", [])
    )


def can_run_draft_supporting_asset_scaffolds(session: Session) -> bool:
    return (
        session.get("status") == "running"
        and session.get("tool_state", {}).get("resume_requested")
        and "prepare_editor_handoff" in session.get("completed_tools", [])
        and "draft_supporting_asset_scaffolds" not in session.get("completed_tools", [])
        and bool(session["tool_state"].get("followup_assets"))
    )


def can_run_stage_editor_execution_package(session: Session) -> bool:
    return (
        session.get("status") == "running"
        and session.get("tool_state", {}).get("resume_requested")
        and bool(session.get("approved_editor_action"))
        and "stage_editor_execution_package" not in session.get("completed_tools", [])
    )


def can_run_stage_apply_ready_preview(session: Session) -> bool:
    return (
        session.get("status") == "running"
        and session.get("tool_state", {}).get("resume_requested")
        and "stage_editor_execution_package" in session.get("completed_tools", [])
        and "stage_apply_ready_preview" not in session.get("completed_tools", [])
    )


def can_run_stage_validation_commands(session: Session) -> bool:
    return (
        session.get("status") == "running"
        and session.get("tool_state", {}).get("resume_requested")
        and "stage_apply_ready_preview" in session.get("completed_tools", [])
        and "stage_validation_commands" not in session.get("completed_tools", [])
    )


def can_run_summarize_progress(session: Session) -> bool:
    if session.get("status") != "running":
        return False
    if "summarize_progress" in session.get("completed_tools", []):
        return False
    if session.get("tool_state", {}).get("resume_requested"):
        return "prepare_editor_handoff" in session.get("completed_tools", [])
    if session.get("pending_confirmation"):
        return False
    if (session.get("plan") or {}).get("task_type") in {"code_change", "code_generation", "hybrid_feature"}:
        return "draft_code_patch_bundle" in session.get("completed_tools", [])
    return "analyze_selection" in session.get("completed_tools", [])


TOOL_SPECS = [
    AgentToolSpec(
        name="inspect_project_context",
        description="Inspect the current project context before choosing concrete actions.",
        phase="scoping",
        input_schema={"type": "object", "properties": {"goal": {"type": "string"}}},
        safety_level="safe",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="backend_orchestrator",
        capability_tags=("project", "context", "inventory"),
        build_input=build_tool_input_from_goal,
        run=tool_inspect_project_context,
        can_run=can_run_inspect_project_context,
        planner_task_types=("investigation", "task_plan", "code_change", "code_generation", "asset_creation", "asset_edit", "hybrid_feature"),
    ),
    AgentToolSpec(
        name="plan_task",
        description="Translate the user goal into subgoals, candidate tools, and confirmation gates.",
        phase="planning",
        input_schema={"type": "object", "properties": {"goal": {"type": "string"}}},
        safety_level="safe",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="backend_orchestrator",
        capability_tags=("planning", "routing", "tool-selection"),
        build_input=build_tool_input_from_goal,
        run=tool_plan_task,
        can_run=can_run_plan_task,
        planner_task_types=("investigation", "task_plan", "code_change", "code_generation", "asset_creation", "asset_edit", "hybrid_feature"),
    ),
    AgentToolSpec(
        name="search_project",
        description="Search project files to narrow the likely code owners for the request.",
        phase="planning",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}},
        safety_level="safe",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="backend_orchestrator",
        capability_tags=("search", "symbols", "ownership"),
        build_input=build_search_input,
        run=tool_search_project,
        can_run=can_run_search_project,
        planner_task_types=("investigation", "task_plan", "code_change", "code_generation", "asset_creation", "asset_edit", "hybrid_feature"),
    ),
    AgentToolSpec(
        name="read_file_context",
        description="Read concise context from the top relevant files before drafting changes.",
        phase="planning",
        input_schema={"type": "object", "properties": {"paths": {"type": "array"}, "preview_chars": {"type": "integer"}}},
        safety_level="safe",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="backend_orchestrator",
        capability_tags=("read", "files", "context"),
        build_input=build_read_file_input,
        run=tool_read_file_context,
        can_run=can_run_read_file_context,
        planner_task_types=("investigation", "task_plan", "code_change", "code_generation", "asset_creation", "asset_edit", "hybrid_feature"),
    ),
    AgentToolSpec(
        name="analyze_selection",
        description="Analyze the strongest file and asset owners for the task.",
        phase="planning",
        input_schema={"type": "object", "properties": {"candidate_files": {"type": "array"}, "candidate_assets": {"type": "array"}}},
        safety_level="safe",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="backend_orchestrator",
        capability_tags=("selection", "asset", "ownership"),
        build_input=build_analyze_selection_input,
        run=tool_analyze_selection,
        can_run=can_run_analyze_selection,
        planner_task_types=("investigation", "task_plan", "code_change", "code_generation", "asset_creation", "asset_edit", "hybrid_feature"),
    ),
    AgentToolSpec(
        name="draft_asset_plan",
        description="Draft the asset-side work that should happen alongside the requested feature.",
        phase="execution",
        input_schema={"type": "object", "properties": {"goal": {"type": "string"}, "task_type": {"type": "string"}}},
        safety_level="safe",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="backend_orchestrator",
        capability_tags=("asset", "plan", "followup"),
        editor_action_types=("create_asset",),
        build_input=build_asset_plan_input,
        run=tool_draft_asset_plan,
        can_run=can_run_draft_asset_plan,
        planner_task_types=("asset_creation", "asset_edit", "hybrid_feature"),
    ),
    AgentToolSpec(
        name="draft_code_patch_bundle",
        description="Draft a preview-only multi-file code patch bundle.",
        phase="execution",
        input_schema={"type": "object", "properties": {"goal": {"type": "string"}}},
        safety_level="preview_only",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="backend_orchestrator",
        capability_tags=("code", "preview", "multi-file"),
        editor_action_types=("apply_code_patch_bundle_preview",),
        build_input=build_code_patch_input,
        run=tool_draft_code_patch_bundle,
        can_run=can_run_draft_code_patch_bundle,
        planner_task_types=("code_change", "code_generation", "hybrid_feature"),
    ),
    AgentToolSpec(
        name="request_confirmation",
        description="Pause the session and request approval before editor-side application.",
        phase="confirmation",
        input_schema={"type": "object", "properties": {"draft_summary": {"type": "string"}, "editor_action": {"type": "object"}}},
        safety_level="confirmation_required",
        requires_confirmation=True,
        safe_to_autorun=False,
        execution_target="user_confirmation",
        build_input=build_confirmation_input,
        run=tool_request_confirmation,
        can_run=can_run_request_confirmation,
        planner_task_types=("code_change", "code_generation", "hybrid_feature"),
    ),
    AgentToolSpec(
        name="stage_editor_execution_package",
        description="Stage an executable editor handoff package from the approved action.",
        phase="handoff",
        input_schema={"type": "object", "properties": {"approved_editor_action": {"type": "object"}, "goal": {"type": "string"}, "followup_assets": {"type": "array"}}},
        safety_level="safe",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="editor_handoff",
        capability_tags=("handoff", "editor", "execution-package"),
        build_input=build_execution_package_input,
        run=tool_stage_editor_execution_package,
        can_run=can_run_stage_editor_execution_package,
        planner_when_resumed=True,
    ),
    AgentToolSpec(
        name="stage_apply_ready_preview",
        description="Stage an apply-ready preview payload from the approved execution package.",
        phase="handoff",
        input_schema={"type": "object", "properties": {"goal": {"type": "string"}, "task_type": {"type": "string"}, "editor_execution_package": {"type": "object"}}},
        safety_level="safe",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="editor_handoff",
        capability_tags=("handoff", "preview", "dry-run"),
        build_input=build_editor_execution_artifact_input,
        run=tool_stage_apply_ready_preview,
        can_run=can_run_stage_apply_ready_preview,
        planner_when_resumed=True,
    ),
    AgentToolSpec(
        name="stage_validation_commands",
        description="Stage safe validation commands and checks from the approved execution package.",
        phase="handoff",
        input_schema={"type": "object", "properties": {"goal": {"type": "string"}, "task_type": {"type": "string"}, "editor_execution_package": {"type": "object"}}},
        safety_level="safe",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="editor_handoff",
        capability_tags=("validation", "compile", "editor"),
        build_input=build_editor_execution_artifact_input,
        run=tool_stage_validation_commands,
        can_run=can_run_stage_validation_commands,
        planner_when_resumed=True,
    ),
    AgentToolSpec(
        name="prepare_editor_handoff",
        description="Prepare the approved editor-side handoff once the user resumes the session.",
        phase="handoff",
        input_schema={"type": "object", "properties": {"approved_editor_action": {"type": "object"}}},
        safety_level="safe",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="editor_handoff",
        capability_tags=("handoff", "editor", "resume"),
        build_input=build_resume_input,
        run=tool_prepare_editor_handoff,
        can_run=can_run_prepare_editor_handoff,
        planner_when_resumed=True,
    ),
    AgentToolSpec(
        name="draft_supporting_asset_scaffolds",
        description="Draft scaffold payloads for the supporting Unreal assets needed after approval.",
        phase="handoff",
        input_schema={"type": "object", "properties": {}},
        safety_level="safe",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="editor_handoff",
        capability_tags=("asset", "scaffold", "followup"),
        editor_action_types=("create_asset",),
        build_input=lambda session: {},
        run=tool_draft_supporting_asset_scaffolds,
        can_run=can_run_draft_supporting_asset_scaffolds,
        planner_when_resumed=True,
    ),
    AgentToolSpec(
        name="summarize_progress",
        description="Summarize the progress made so far and capture the next action.",
        phase="reporting",
        input_schema={"type": "object", "properties": {"goal": {"type": "string"}, "completed_tools": {"type": "array"}, "task_type": {"type": "string"}}},
        safety_level="safe",
        requires_confirmation=False,
        safe_to_autorun=True,
        execution_target="backend_orchestrator",
        capability_tags=("reporting", "progress"),
        build_input=build_progress_input,
        run=tool_summarize_progress,
        can_run=can_run_summarize_progress,
        planner_task_types=("investigation", "task_plan", "code_change", "code_generation", "asset_creation", "asset_edit", "hybrid_feature"),
        planner_when_resumed=True,
    ),
]

TOOL_REGISTRY = {tool.name: tool for tool in TOOL_SPECS}
