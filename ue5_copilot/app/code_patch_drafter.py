from __future__ import annotations

import hashlib
import re
from difflib import unified_diff
from typing import Any

from app.code_patch_planner import build_code_patch_plan


def build_code_patch_draft(
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
            "summary": "No draftable code patch was produced yet.",
            "target_file": None,
            "unified_diff": "",
            "warnings": ["The planner did not produce a concrete single-file edit preview."],
        }

    target_edit = proposed_edits[0]
    target_file = next((item for item in files if item["path"] == target_edit["path"]), None)
    if not target_file:
        return {
            "goal": goal,
            "execution_mode": "preview_only",
            "summary": "The selected target file was not found in the scanned project cache.",
            "target_file": target_edit["path"],
            "unified_diff": "",
            "warnings": ["Rescan the project before drafting a code patch."],
        }

    original_content = target_file.get("content", "")
    updated_content, warnings = apply_preview_edit(
        original_content=original_content,
        edit_kind=target_edit.get("edit_kind", ""),
        patch_preview=target_edit.get("patch_preview", ""),
    )

    diff_text = "\n".join(
        unified_diff(
            original_content.splitlines(),
            updated_content.splitlines(),
            fromfile=target_file["path"],
            tofile=target_file["path"],
            lineterm="",
        )
    )

    result = {
        "goal": goal,
        "execution_mode": "preview_only",
        "task_kind": plan.get("task_kind", "general_patch"),
        "summary": f"Drafted a preview-only single-file diff for `{target_file['name']}`.",
        "target_file": {
            "path": target_file["path"],
            "name": target_file["name"],
            "file_type": target_file.get("file_type", ""),
        },
        "edit_kind": target_edit.get("edit_kind", ""),
        "edit_summary": target_edit.get("summary", ""),
        "original_content_hash": hash_content(original_content),
        "unified_diff": diff_text,
        "patch_preview": target_edit.get("patch_preview", ""),
        "warnings": warnings,
        "validation_steps": plan.get("validation_steps", []),
        "risks": plan.get("risks", []),
    }
    editor_action = build_apply_code_patch_action(
        target_path=target_file["path"],
        edit_kind=target_edit.get("edit_kind", ""),
        original_content_hash=hash_content(original_content),
        updated_content=updated_content,
        unified_diff=diff_text,
    )
    if editor_action:
        result["editor_action"] = editor_action
    return result


def build_apply_code_patch_action(*, target_path: str, edit_kind: str, original_content_hash: str, updated_content: str, unified_diff: str) -> dict[str, Any] | None:
    if edit_kind not in {"header_additions", "source_additions"}:
        return None
    return {
        "action_type": "apply_code_patch_preview",
        "dry_run": False,
        "requires_user_confirmation": True,
        "arguments": {
            "target_path": target_path,
            "edit_kind": edit_kind,
            "original_content_hash": original_content_hash,
            "updated_content": updated_content,
            "unified_diff": unified_diff,
        },
    }


def hash_content(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def apply_preview_edit(*, original_content: str, edit_kind: str, patch_preview: str) -> tuple[str, list[str]]:
    had_trailing_newline = original_content.endswith("\n")
    content = original_content.rstrip("\n")
    warnings: list[str] = []

    if edit_kind == "header_additions":
        updated = insert_header_additions(content, patch_preview.strip(), warnings)
        if updated == content:
            return original_content if had_trailing_newline else content, warnings
        return updated + "\n", warnings

    if edit_kind == "source_additions":
        updated = insert_source_additions(content, patch_preview.strip(), warnings)
        if updated == content:
            return original_content if had_trailing_newline else content, warnings
        return updated + "\n", warnings

    if edit_kind == "manual_patch_plan":
        insertion = "\n\n" + patch_preview.strip() + "\n"
        warnings.append("This draft used a fallback append because the task does not yet have a structured patch inserter.")
        return content + insertion + "\n", warnings

    warnings.append("This edit kind does not have a specialized inserter yet, so the preview was appended.")
    return content + "\n\n" + patch_preview.strip() + "\n", warnings


def insert_header_additions(content: str, patch_preview: str, warnings: list[str]) -> str:
    filtered_preview = filter_existing_header_declarations(content, patch_preview)
    if not filtered_preview.strip():
        warnings.append("The requested header declarations already exist, so no new header diff was produced.")
        return content

    insertion = indent_block(filtered_preview, "    ")
    public_match = re.search(r"(^[ \t]*public:\s*$)", content, re.MULTILINE)
    if public_match:
        insert_at = public_match.end()
        return content[:insert_at] + "\n" + insertion + content[insert_at:]

    marker = "\n};"
    if marker in content:
        return content.replace(marker, "\n\n" + insertion + marker, 1)

    warnings.append("Could not find a public section or class closing marker, so the preview was appended to the end of the file.")
    return content + "\n\n" + insertion


def insert_source_additions(content: str, patch_preview: str, warnings: list[str]) -> str:
    binding_block = extract_marked_block(patch_preview, "BIND_ACTIONS")
    handler_block = extract_marked_block(patch_preview, "HANDLER_DEFINITIONS")
    updated = content
    class_name = infer_source_class_name(updated)
    needs_enhanced_input_include = "UEnhancedInputComponent" in patch_preview

    if binding_block:
        normalized_binding_block = binding_block.replace("ThisClass::", f"{class_name}::")
        if needs_enhanced_input_include:
            updated = ensure_source_include(updated, '#include "EnhancedInputComponent.h"')
        updated, inserted = insert_bindings_into_input_setup(updated, normalized_binding_block)
        if not inserted:
            setup_definition = build_setup_player_input_component_definition(class_name, normalized_binding_block)
            if setup_definition in updated:
                warnings.append("The requested input setup definition already exists, so no new setup function was added.")
            else:
                updated = append_block(updated, setup_definition)

    if handler_block:
        normalized_handler_block = handler_block.replace("ThisClass::", f"{class_name}::")
        filtered_handler_block = filter_existing_handler_definitions(updated, normalized_handler_block)
        if filtered_handler_block:
            updated = append_block(updated, filtered_handler_block)
        else:
            warnings.append("The requested handler definitions already exist, so no new handler diff was produced.")

    if not binding_block and not handler_block:
        warnings.append("The source preview did not contain structured sections, so it was appended to the end of the file.")
        updated = append_block(updated, patch_preview)

    return updated


def extract_marked_block(patch_preview: str, marker_name: str) -> str:
    pattern = rf"// {marker_name}\n(?P<body>.*?)(?:\n// END_{marker_name}|$)"
    match = re.search(pattern, patch_preview, re.DOTALL)
    if not match:
        return ""
    return match.group("body").strip()


def insert_bindings_into_input_setup(content: str, binding_block: str) -> tuple[str, bool]:
    setup_signature = "SetupPlayerInputComponent("
    signature_index = content.find(setup_signature)
    if signature_index == -1:
        return content, False

    body_start = content.find("{", signature_index)
    if body_start == -1:
        return content, False

    body_end = find_matching_brace(content, body_start)
    if body_end == -1:
        return content, False

    body_content = content[body_start + 1:body_end]
    filtered_binding_block = filter_existing_bindings(body_content, binding_block)
    if not filtered_binding_block:
        return content, True
    line_indent = determine_body_indent(content, body_start)
    closing_indent = determine_closing_brace_indent(content, body_end)
    indented_bindings = indent_block(filtered_binding_block, line_indent)

    if body_content.strip():
        updated_body = body_content.rstrip() + "\n" + indented_bindings + "\n" + closing_indent
    else:
        updated_body = "\n" + indented_bindings + "\n" + closing_indent

    return content[:body_start + 1] + updated_body + content[body_end:], True


def find_matching_brace(content: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(content)):
        char = content[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def determine_body_indent(content: str, body_start: int) -> str:
    line_start = content.rfind("\n", 0, body_start)
    if line_start == -1:
        line_start = 0
    else:
        line_start += 1
    line_text = content[line_start:body_start]
    base_indent = re.match(r"[ \t]*", line_text).group(0)
    return base_indent + "    "


def determine_closing_brace_indent(content: str, body_end: int) -> str:
    line_start = content.rfind("\n", 0, body_end)
    if line_start == -1:
        line_start = 0
    else:
        line_start += 1
    line_text = content[line_start:body_end]
    return re.match(r"[ \t]*", line_text).group(0)


def append_block(content: str, block: str) -> str:
    return content.rstrip() + "\n\n" + block.strip() + "\n"


def indent_block(block: str, indent: str) -> str:
    return "\n".join(f"{indent}{line}" if line else "" for line in block.splitlines())


def ensure_source_include(content: str, include_line: str) -> str:
    if include_line in content:
        return content

    include_matches = list(re.finditer(r'^[ \t]*#include\s+"[^"]+"\s*$', content, re.MULTILINE))
    if include_matches:
        insert_at = include_matches[-1].end()
        return content[:insert_at] + "\n" + include_line + content[insert_at:]

    return include_line + "\n" + content.lstrip("\n")


def build_setup_player_input_component_definition(class_name: str, binding_block: str) -> str:
    indented_bindings = indent_block(binding_block, "    ")
    return (
        f"void {class_name}::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)\n"
        "{\n"
        "    Super::SetupPlayerInputComponent(PlayerInputComponent);\n\n"
        f"{indented_bindings}\n"
        "}"
    )


def infer_source_class_name(content: str) -> str:
    match = re.search(r"\bvoid\s+([A-Za-z_][A-Za-z0-9_]*)::", content)
    if match:
        return match.group(1)
    return "ThisClass"


def filter_existing_header_declarations(content: str, patch_preview: str) -> str:
    kept_lines: list[str] = []
    pending_blank = False

    for line in patch_preview.splitlines():
        normalized = line.strip()
        if not normalized:
            pending_blank = bool(kept_lines)
            continue
        if normalized in content:
            pending_blank = False
            continue
        if pending_blank and kept_lines and kept_lines[-1] != "":
            kept_lines.append("")
        pending_blank = False
        kept_lines.append(line)

    while kept_lines and kept_lines[-1] == "":
        kept_lines.pop()
    return "\n".join(kept_lines)


def filter_existing_bindings(existing_body: str, binding_block: str) -> str:
    kept_lines = []
    for line in binding_block.splitlines():
        normalized = line.strip()
        if normalized and normalized in existing_body:
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()


def filter_existing_handler_definitions(content: str, handler_block: str) -> str:
    blocks = [item.strip() for item in re.split(r"\n\s*\n", handler_block.strip()) if item.strip()]
    kept_blocks = [block for block in blocks if block not in content]
    return "\n\n".join(kept_blocks)
