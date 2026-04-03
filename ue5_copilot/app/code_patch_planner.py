from __future__ import annotations

import os
import re
from typing import Any


def build_code_patch_plan(
    *,
    goal: str,
    files: list[dict[str, Any]],
    matched_files: list[dict[str, Any]],
    target_path: str = "",
) -> dict[str, Any]:
    normalized_goal = (goal or "").strip()
    if not normalized_goal:
        return {"error": "Describe the code task first."}
    if not files:
        return {"error": "No project has been scanned yet."}

    selected_files = select_target_files(files, matched_files, target_path)
    if not selected_files:
        return {
            "goal": normalized_goal,
            "execution_mode": "plan_only",
            "summary": "No clear code owner was found yet. Try a more specific goal or target file.",
            "task_kind": "general_patch",
            "target_files": [],
            "proposed_edits": [],
            "validation_steps": [],
            "risks": [],
        }

    task_kind = infer_code_task_kind(normalized_goal)
    target_header = pick_file_by_extension(selected_files, ".h")
    target_source = pick_file_by_extension(selected_files, ".cpp")
    proposed_edits = build_proposed_edits(normalized_goal, task_kind, target_header, target_source)

    return {
        "goal": normalized_goal,
        "execution_mode": "plan_only",
        "task_kind": task_kind,
        "summary": build_summary(task_kind, target_header, target_source),
        "target_files": [
            {
                "path": file_record["path"],
                "name": file_record["name"],
                "file_type": file_record.get("file_type", ""),
                "symbols": file_record.get("analysis", {}).get("all_symbol_names", [])[:8],
            }
            for file_record in selected_files[:4]
        ],
        "proposed_edits": proposed_edits,
        "validation_steps": build_validation_steps(task_kind),
        "risks": build_risks(task_kind),
    }


def select_target_files(files: list[dict[str, Any]], matched_files: list[dict[str, Any]], target_path: str) -> list[dict[str, Any]]:
    file_by_path = {file_record["path"]: file_record for file_record in files}
    selected = []

    normalized_target = (target_path or "").strip().lower()
    if normalized_target:
        for file_record in files:
            if file_record["path"].lower() == normalized_target or file_record["name"].lower() == os.path.basename(normalized_target):
                selected.append(file_record)
                selected.extend(find_counterpart_files(files, file_record))
                return dedupe_files(selected)

    for match in matched_files:
        file_record = file_by_path.get(match.get("path", ""))
        if not file_record:
            continue
        selected.append(file_record)
        selected.extend(find_counterpart_files(files, file_record))

    return dedupe_files(selected)


def find_counterpart_files(files: list[dict[str, Any]], file_record: dict[str, Any]) -> list[dict[str, Any]]:
    base_path = file_record["path"]
    stem, extension = os.path.splitext(base_path)
    counterpart_ext = ".cpp" if extension == ".h" else ".h" if extension == ".cpp" else ""
    if not counterpart_ext:
        return []

    counterparts = []
    for candidate in files:
        if candidate["path"] == stem + counterpart_ext:
            counterparts.append(candidate)
    return counterparts


def dedupe_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for file_record in files:
        path = file_record.get("path")
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(file_record)
    result.sort(key=lambda item: item.get("analysis", {}).get("centrality_score", 0), reverse=True)
    return result


def pick_file_by_extension(files: list[dict[str, Any]], extension: str) -> dict[str, Any] | None:
    for file_record in files:
        if file_record.get("extension") == extension:
            return file_record
    return None


def infer_code_task_kind(goal: str) -> str:
    lowered = goal.lower()
    if "input" in lowered and any(token in lowered for token in ("hook", "bind", "wire", "sprint", "jump", "fire")):
        return "wire_input_binding"
    if any(token in lowered for token in ("add function", "new function", "create function", "handler")):
        return "add_function_stub"
    if any(token in lowered for token in ("add property", "add variable", "uprop", "uproperty")):
        return "add_property"
    return "general_patch"


def build_proposed_edits(
    goal: str,
    task_kind: str,
    target_header: dict[str, Any] | None,
    target_source: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    edits = []

    if task_kind == "wire_input_binding":
        if target_header:
            action_name = infer_action_name(goal)
            edits.append(
                {
                    "path": target_header["path"],
                    "edit_kind": "header_additions",
                    "summary": "Add input asset references and handler declarations to the owning class header.",
                    "patch_preview": build_input_header_preview(action_name, target_header.get("content", "")),
                }
            )
        if target_source:
            action_name = infer_action_name(goal)
            edits.append(
                {
                    "path": target_source["path"],
                    "edit_kind": "source_additions",
                    "summary": "Bind the input action and add handler stub implementations in the source file.",
                    "patch_preview": build_input_source_preview(action_name),
                }
            )
        return edits

    if task_kind == "add_function_stub":
        function_name = infer_function_name(goal)
        if target_header:
            edits.append(
                {
                    "path": target_header["path"],
                    "edit_kind": "header_additions",
                    "summary": "Add the function declaration to the header.",
                    "patch_preview": f"UFUNCTION(BlueprintCallable)\nvoid {function_name}();",
                }
            )
        if target_source:
            class_name = infer_primary_class_name(target_header or target_source)
            edits.append(
                {
                    "path": target_source["path"],
                    "edit_kind": "source_additions",
                    "summary": "Add the function definition stub to the source file.",
                    "patch_preview": f"void {class_name}::{function_name}()\n{{\n    // TODO: implement {function_name}\n}}",
                }
            )
        return edits

    if task_kind == "add_property" and target_header:
        variable_name = infer_variable_name(goal)
        edits.append(
            {
                "path": target_header["path"],
                "edit_kind": "header_additions",
                "summary": "Add a new reflected property to the header.",
                "patch_preview": f"UPROPERTY(EditAnywhere, BlueprintReadWrite, Category=\"Gameplay\")\nbool {variable_name} = false;",
            }
        )
        return edits

    target_file = target_source or target_header
    if target_file:
        edits.append(
            {
                "path": target_file["path"],
                "edit_kind": "manual_patch_plan",
                "summary": "Review this file first and prepare a narrow patch around the task owner.",
                "patch_preview": f"// Goal: {goal}\n// TODO: insert the smallest possible code change near the owning class or entry point.",
            }
        )
    return edits


def infer_action_name(goal: str) -> str:
    lowered = goal.lower()
    if "sprint" in lowered:
        return "Sprint"
    if "jump" in lowered:
        return "Jump"
    if "fire" in lowered or "shoot" in lowered:
        return "Fire"
    if "interact" in lowered:
        return "Interact"
    return "RequestedAction"


def build_input_header_preview(action_name: str, header_content: str) -> str:
    declarations = []
    if "SetupPlayerInputComponent" not in header_content:
        declarations.append("virtual void SetupPlayerInputComponent(class UInputComponent* PlayerInputComponent) override;")
    declarations.extend(
        [
            f'UPROPERTY(EditDefaultsOnly, BlueprintReadOnly, Category="Input")',
            f'TObjectPtr<class UInputAction> IA_{action_name} = nullptr;',
            "",
            f'void Handle{action_name}Started();',
            f'void Handle{action_name}Completed();',
        ]
    )
    return "\n".join(declarations)


def build_input_source_preview(action_name: str) -> str:
    return (
        f'// BIND_ACTIONS\n'
        f'if (UEnhancedInputComponent* EnhancedInputComponent = Cast<UEnhancedInputComponent>(PlayerInputComponent))\n'
        '{\n'
        f'    EnhancedInputComponent->BindAction(IA_{action_name}, ETriggerEvent::Started, this, &ThisClass::Handle{action_name}Started);\n'
        f'    EnhancedInputComponent->BindAction(IA_{action_name}, ETriggerEvent::Completed, this, &ThisClass::Handle{action_name}Completed);\n'
        '}\n'
        f'// END_BIND_ACTIONS\n\n'
        f'// HANDLER_DEFINITIONS\n'
        f'void ThisClass::Handle{action_name}Started()\n'
        '{\n'
        f'    // TODO: begin {action_name.lower()} behavior\n'
        '}\n\n'
        f'void ThisClass::Handle{action_name}Completed()\n'
        '{\n'
        f'    // TODO: end {action_name.lower()} behavior\n'
        '}\n'
        f'// END_HANDLER_DEFINITIONS'
    )


def infer_function_name(goal: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9]+", goal)
    for word in words:
        if word.lower() not in {"add", "create", "new", "function", "handler"}:
            return f"Handle{word[0].upper()}{word[1:]}"
    return "HandleRequestedTask"


def infer_variable_name(goal: str) -> str:
    lowered = goal.lower()
    if "sprint" in lowered:
        return "bIsSprinting"
    if "jump" in lowered:
        return "bWantsToJump"
    if "target" in lowered:
        return "CurrentTarget"
    return "bRequestedState"


def infer_primary_class_name(file_record: dict[str, Any]) -> str:
    symbols = file_record.get("analysis", {}).get("all_symbol_names", [])
    for symbol in symbols:
        if symbol.startswith(("A", "U", "F")):
            return symbol
    stem = os.path.splitext(file_record.get("name", "ThisClass"))[0]
    return stem or "ThisClass"


def build_summary(task_kind: str, target_header: dict[str, Any] | None, target_source: dict[str, Any] | None) -> str:
    parts = [f"This is a `{task_kind}` plan."]
    if target_header:
        parts.append(f"Header lead: `{target_header['name']}`.")
    if target_source:
        parts.append(f"Source lead: `{target_source['name']}`.")
    parts.append("The response is still preview-only and intended for diff generation or review before file edits.")
    return " ".join(parts)


def build_validation_steps(task_kind: str) -> list[str]:
    steps = [
        "Review the owning class and the chosen patch location before editing.",
        "Compile after the smallest useful change instead of batching many edits together.",
        "Verify runtime/editor behavior in the specific flow the request targets.",
    ]
    if task_kind == "wire_input_binding":
        steps.append("Confirm the Mapping Context is active and the Input Action is actually bound on the expected controller/pawn layer.")
    return steps


def build_risks(task_kind: str) -> list[str]:
    risks = [
        "A code patch can compile cleanly while still missing the true gameplay owner or entry point.",
        "Changing generated Unreal-facing code in the wrong class can create duplicate ownership across C++ and Blueprint.",
    ]
    if task_kind == "wire_input_binding":
        risks.append("Input tasks often require both content and code changes, so a code-only patch may be incomplete until the correct IA_/IMC_ assets are present.")
    return risks
