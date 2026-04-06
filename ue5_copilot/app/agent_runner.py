from __future__ import annotations

from typing import Any

from app.agent_orchestrator import (
    confirm_and_continue_session,
    confirm_session,
    resume_session,
    step_session,
    start_session,
)


def start_agent_task_session(
    *,
    goal: str,
    files: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    matched_files: list[dict[str, Any]],
    family_summaries: dict[str, Any],
    auto_run: bool = True,
) -> dict[str, Any]:
    return start_session(
        goal=goal,
        files=files,
        assets=assets,
        matched_files=matched_files,
        family_summaries=family_summaries,
        auto_run=auto_run,
    )


def confirm_agent_task_session(session: dict[str, Any], *, decision: str) -> dict[str, Any]:
    return confirm_session(session, decision=decision)


def resume_agent_task_session(session: dict[str, Any]) -> dict[str, Any]:
    return resume_session(session)


def step_agent_task_session(session: dict[str, Any]) -> dict[str, Any]:
    return step_session(session)


def confirm_and_continue_agent_task_session(session: dict[str, Any], *, decision: str) -> dict[str, Any]:
    return confirm_and_continue_session(session, decision=decision)
