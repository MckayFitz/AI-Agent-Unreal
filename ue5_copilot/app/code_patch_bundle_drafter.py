from __future__ import annotations

from typing import Any

from app.code_patch_drafter import apply_preview_edit, hash_content
from app.code_patch_planner import build_code_patch_plan


def build_code_patch_bundle_draft(
    *,
    goal: str,
    files: list[dict[str, Any]],
    matched_files: list[dict[str, Any]],
    target_path: str = "",
) -> dict[str, Any]:
    plan = build_code_patch_plan(
        goal=goal,
        files=files,
        matched_files=matched_files,
        target_path=target_path,
    )
    if plan.get("error"):
        return plan

    proposed_edits = plan.get("proposed_edits", [])
    if not proposed_edits:
        return {
            "goal": goal,
            "execution_mode": "preview_only",
            "summary": "No draftable code patch bundle was produced yet.",
            "draft_files": [],
            "combined_unified_diff": "",
            "warnings": ["The planner did not produce concrete code edits for this task yet."],
        }

    file_by_path = {item["path"]: item for item in files}
    draft_files = []
    warnings: list[str] = []

    for edit in proposed_edits:
        target_file = file_by_path.get(edit["path"])
        if not target_file:
            warnings.append(f"Skipped `{edit['path']}` because it was not found in the scanned project cache.")
            continue

        original_content = target_file.get("content", "")
        updated_content, edit_warnings = apply_preview_edit(
            original_content=original_content,
            edit_kind=edit.get("edit_kind", ""),
            patch_preview=edit.get("patch_preview", ""),
        )
        unified_diff = build_unified_diff(target_file["path"], original_content, updated_content)
        warnings.extend(edit_warnings)
        draft_files.append(
            {
                "path": target_file["path"],
                "name": target_file["name"],
                "file_type": target_file.get("file_type", ""),
                "edit_kind": edit.get("edit_kind", ""),
                "edit_summary": edit.get("summary", ""),
                "original_content_hash": hash_content(original_content),
                "updated_content": updated_content,
                "unified_diff": unified_diff,
                "patch_preview": edit.get("patch_preview", ""),
            }
        )

    combined_unified_diff = "\n\n".join(item["unified_diff"] for item in draft_files if item["unified_diff"])
    result = {
        "goal": goal,
        "execution_mode": "preview_only",
        "task_kind": plan.get("task_kind", "general_patch"),
        "summary": f"Drafted a preview-only code diff bundle with {len(draft_files)} file(s).",
        "draft_files": draft_files,
        "combined_unified_diff": combined_unified_diff,
        "warnings": dedupe_strings(warnings),
        "validation_steps": plan.get("validation_steps", []),
        "risks": plan.get("risks", []),
    }
    editor_action = build_apply_code_patch_bundle_action(draft_files)
    if editor_action:
        result["editor_action"] = editor_action
    return result


def build_apply_code_patch_bundle_action(draft_files: list[dict[str, Any]]) -> dict[str, Any] | None:
    supported = [item for item in draft_files if item.get("edit_kind") in {"header_additions", "source_additions"}]
    if not supported:
        return None
    return {
        "action_type": "apply_code_patch_bundle_preview",
        "dry_run": False,
        "requires_user_confirmation": True,
        "arguments": {
            "files": [
                {
                    "target_path": item["path"],
                    "edit_kind": item["edit_kind"],
                    "original_content_hash": item["original_content_hash"],
                    "updated_content": item["updated_content"],
                    "unified_diff": item["unified_diff"],
                }
                for item in supported
            ]
        },
    }


def build_unified_diff(path: str, original_content: str, updated_content: str) -> str:
    from difflib import unified_diff

    return "\n".join(
        unified_diff(
            original_content.splitlines(),
            updated_content.splitlines(),
            fromfile=path,
            tofile=path,
            lineterm="",
        )
    )


def dedupe_strings(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        value = (item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
