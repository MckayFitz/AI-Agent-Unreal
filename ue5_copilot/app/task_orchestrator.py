from __future__ import annotations

import re
from collections import Counter
from typing import Any


def build_agent_task_plan(
    *,
    goal: str,
    files: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    matched_files: list[dict[str, Any]],
    family_summaries: dict[str, Any],
) -> dict[str, Any]:
    normalized_goal = (goal or "").strip()
    lowered_goal = normalized_goal.lower()

    candidate_files = build_candidate_files(files, matched_files)
    candidate_assets = build_candidate_assets(assets, lowered_goal)
    task_type = classify_task_type(lowered_goal, candidate_assets)
    systems = infer_systems(candidate_files)
    suggested_routes = infer_suggested_routes(task_type, candidate_assets)
    suggested_editor_actions = infer_suggested_editor_actions(task_type, candidate_assets)
    stages = build_execution_stages(task_type, candidate_files, candidate_assets, systems)
    risks = infer_task_risks(task_type, candidate_assets, systems)
    unreal_tool_catalog = build_unreal_tool_catalog(task_type=task_type, candidate_assets=candidate_assets)

    result = {
        "goal": normalized_goal,
        "task_type": task_type,
        "execution_mode": "plan_only",
        "agent_profile": "tool_using_agent",
        "summary": build_summary(task_type, candidate_files, candidate_assets, systems),
        "systems": systems,
        "candidate_files": candidate_files[:8],
        "candidate_assets": candidate_assets[:8],
        "suggested_backend_routes": suggested_routes,
        "suggested_editor_actions": suggested_editor_actions,
        "tool_preferences": infer_tool_preferences(task_type, lowered_goal, candidate_assets),
        "unreal_tool_catalog": unreal_tool_catalog,
        "recommended_tool_chain": build_recommended_tool_chain(unreal_tool_catalog),
        "confirmation_policy": infer_confirmation_policy(task_type),
        "stages": stages,
        "risks": risks[:8],
    }

    family_hints = infer_family_hints(candidate_assets, family_summaries)
    if family_hints:
        result["family_hints"] = family_hints[:6]

    return result


def build_candidate_files(files: list[dict[str, Any]], matched_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    file_by_path = {file_record["path"]: file_record for file_record in files}
    candidates = []

    for match in matched_files:
        file_record = file_by_path.get(match.get("path", ""))
        if not file_record:
            continue
        analysis = file_record.get("analysis", {})
        candidates.append(
            {
                "path": file_record["path"],
                "name": file_record["name"],
                "score": analysis.get("centrality_score", 0),
                "roles": analysis.get("roles", [])[:5],
                "symbols": analysis.get("all_symbol_names", [])[:8],
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    return dedupe_dicts(candidates, key="path")


def build_candidate_assets(assets: list[dict[str, Any]], lowered_goal: str) -> list[dict[str, Any]]:
    goal_tokens = extract_tokens(lowered_goal)
    scored_assets = []

    for asset in assets:
        asset_name = asset.get("name", "")
        asset_path = asset.get("relative_path") or asset.get("path", "")
        haystack = f"{asset_name} {asset_path} {asset.get('asset_type', '')} {asset.get('family', '')}".lower()
        score = 0
        matched_tokens = []
        for token in goal_tokens:
            if token in haystack:
                score += 2
                matched_tokens.append(token)
        family = (asset.get("family") or "").lower()
        if "input" in lowered_goal and family == "enhanced_input":
            score += 4
        if any(token in lowered_goal for token in ("material", "roughness", "texture", "color")) and family in {"material", "material_instance"}:
            score += 4
        if any(token in lowered_goal for token in ("ai", "behavior", "blackboard")) and family == "behavior_tree":
            score += 4
        if any(token in lowered_goal for token in ("animation", "anim", "locomotion")) and family == "animation":
            score += 4
        if score > 0:
            scored_assets.append(
                {
                    "name": asset_name,
                    "path": asset.get("path", ""),
                    "relative_path": asset.get("relative_path", ""),
                    "asset_type": asset.get("asset_type", ""),
                    "family": asset.get("family", ""),
                    "match_score": score,
                    "matched_tokens": matched_tokens[:6],
                }
            )

    scored_assets.sort(key=lambda item: item["match_score"], reverse=True)
    return dedupe_dicts(scored_assets, key="path")


def classify_task_type(lowered_goal: str, candidate_assets: list[dict[str, Any]]) -> str:
    has_asset_candidates = bool(candidate_assets)
    mentions_create = any(has_goal_term(lowered_goal, token) for token in ("create", "new", "generate", "scaffold"))
    mentions_code = any(
        has_goal_term(lowered_goal, token)
        for token in (
            "code",
            "c++",
            "class",
            ".h",
            ".cpp",
            "function",
            "component",
            "system",
            "module",
            "character",
            "controller",
            "pawn",
            "actor",
        )
    )
    mentions_change = any(has_goal_term(lowered_goal, token) for token in ("add", "update", "modify", "change", "hook", "wire", "rename", "set", "fix"))
    mentions_analysis = any(has_goal_term(lowered_goal, token) for token in ("explain", "analyze", "inspect", "understand", "where", "how"))
    mentions_asset_family = any(asset.get("family") for asset in candidate_assets)

    if mentions_create and mentions_code and has_asset_candidates:
        return "hybrid_feature"
    if mentions_change and mentions_code and mentions_asset_family:
        return "hybrid_feature"
    if mentions_create and mentions_code:
        return "code_generation"
    if mentions_create and mentions_asset_family:
        return "asset_creation"
    if mentions_change and mentions_asset_family:
        return "asset_edit"
    if mentions_change and mentions_code:
        return "code_change"
    if mentions_analysis or not has_asset_candidates:
        return "investigation"
    return "task_plan"


def has_goal_term(lowered_goal: str, term: str) -> bool:
    normalized_term = (term or "").strip().lower()
    if not normalized_term:
        return False
    if re.fullmatch(r"[a-z0-9_]+", normalized_term):
        return re.search(rf"\b{re.escape(normalized_term)}\b", lowered_goal) is not None
    return normalized_term in lowered_goal


def infer_systems(candidate_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    role_counter = Counter()
    for item in candidate_files:
        role_counter.update(item.get("roles", []))
    return [{"name": role, "count": count} for role, count in role_counter.most_common(6)]


def infer_suggested_routes(task_type: str, candidate_assets: list[dict[str, Any]]) -> list[str]:
    routes = ["/task-workflow", "/agent-tools", "/scan-project"]
    if task_type in {"investigation", "code_change", "hybrid_feature"}:
        routes.append("/ask")
        routes.append("/references")
    if candidate_assets:
        routes.append("/plugin/selection-context")
        routes.append("/plugin/asset-details")
        routes.append("/asset-deep-analysis")
    if task_type in {"asset_edit", "hybrid_feature"}:
        routes.append("/plugin/asset-edit-plan")
    if task_type in {"asset_creation", "hybrid_feature"}:
        routes.append("/asset-scaffold")
    if task_type in {"code_change", "code_generation", "hybrid_feature"}:
        routes.append("/code-patch-bundle-draft")
        routes.append("/agent-session")
    return dedupe_strings(routes)


def infer_suggested_editor_actions(task_type: str, candidate_assets: list[dict[str, Any]]) -> list[str]:
    actions = []
    families = {(item.get("family") or "").lower() for item in candidate_assets}

    if task_type in {"asset_creation", "hybrid_feature"}:
        actions.append("create_asset")
    if task_type in {"asset_edit", "hybrid_feature"}:
        actions.append("rename_asset")
        actions.append("apply_asset_edit_preview")
    if task_type in {"code_change", "code_generation", "hybrid_feature"}:
        actions.append("apply_code_patch_bundle_preview")
    if "material_instance" in families or "material" in families:
        actions.append("tweak_material_parameter")

    return dedupe_strings(actions)


def build_unreal_tool_catalog(
    *,
    task_type: str,
    candidate_assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    families = {(item.get("family") or "").lower() for item in candidate_assets}
    entries = [
        {
            "name": "read_current_selection",
            "label": "Read current selection",
            "status": "implemented",
            "execution_target": "backend_route",
            "backend_route": "/plugin/selection-context",
            "safe_to_autorun": True,
            "requires_confirmation": False,
            "mutates_project": False,
            "supported_task_types": ["investigation", "asset_edit", "asset_creation", "hybrid_feature", "task_plan"],
            "capability_tags": ["selection", "context", "asset-awareness"],
            "summary": "Resolve the current editor selection into matching files, assets, and specialized family hints.",
        },
        {
            "name": "inspect_asset_metadata",
            "label": "Inspect asset metadata",
            "status": "implemented",
            "execution_target": "backend_route",
            "backend_route": "/plugin/asset-details",
            "safe_to_autorun": True,
            "requires_confirmation": False,
            "mutates_project": False,
            "supported_task_types": ["investigation", "asset_edit", "hybrid_feature", "task_plan"],
            "capability_tags": ["asset", "metadata", "ownership"],
            "summary": "Inspect selected asset metadata, likely code owners, and Blueprint-linked C++ classes.",
        },
        {
            "name": "extract_blueprint_graph_state",
            "label": "Extract Blueprint graph/state data",
            "status": "implemented",
            "execution_target": "backend_route",
            "backend_route": "/asset-deep-analysis",
            "safe_to_autorun": True,
            "requires_confirmation": False,
            "mutates_project": False,
            "supported_task_types": ["investigation", "asset_edit", "hybrid_feature"],
            "capability_tags": ["blueprint", "graph", "state", "deep-analysis"],
            "summary": "Interpret pasted/exported Blueprint, behavior, animation, or graph text as structured analysis.",
        },
        {
            "name": "search_project_symbols",
            "label": "Search references and symbols",
            "status": "implemented",
            "execution_target": "backend_route",
            "backend_route": "/references",
            "safe_to_autorun": True,
            "requires_confirmation": False,
            "mutates_project": False,
            "supported_task_types": ["investigation", "code_change", "code_generation", "hybrid_feature", "task_plan"],
            "capability_tags": ["search", "references", "symbols", "ownership"],
            "summary": "Search project references, symbols, and likely ownership paths before editing.",
        },
        {
            "name": "scan_project_context",
            "label": "Scan project context",
            "status": "implemented",
            "execution_target": "backend_route",
            "backend_route": "/scan-project",
            "safe_to_autorun": True,
            "requires_confirmation": False,
            "mutates_project": False,
            "supported_task_types": ["investigation", "code_change", "code_generation", "asset_creation", "asset_edit", "hybrid_feature", "task_plan"],
            "capability_tags": ["scan", "project", "indexing"],
            "summary": "Scan source and asset inventories so the agent can reason over the current Unreal project.",
        },
        {
            "name": "plan_code_changes",
            "label": "Plan code changes",
            "status": "implemented",
            "execution_target": "backend_route",
            "backend_route": "/code-patch-bundle-draft",
            "safe_to_autorun": True,
            "requires_confirmation": False,
            "mutates_project": False,
            "supported_task_types": ["code_change", "code_generation", "hybrid_feature"],
            "capability_tags": ["code", "preview", "multi-file"],
            "editor_action_types": ["apply_code_patch_bundle_preview"],
            "summary": "Draft a preview-only multi-file code bundle before any editor-side file apply step.",
        },
        {
            "name": "plan_asset_creation",
            "label": "Create assets safely",
            "status": "implemented",
            "execution_target": "backend_route",
            "backend_route": "/asset-scaffold",
            "safe_to_autorun": True,
            "requires_confirmation": False,
            "mutates_project": False,
            "supported_task_types": ["asset_creation", "hybrid_feature"],
            "capability_tags": ["asset", "create", "scaffold"],
            "editor_action_types": ["create_asset"],
            "summary": "Create scaffold-ready Unreal asset plans that stay confirmation-gated before editor mutation.",
        },
        {
            "name": "plan_asset_edits",
            "label": "Apply safe asset edits",
            "status": "implemented",
            "execution_target": "backend_route",
            "backend_route": "/plugin/asset-edit-plan",
            "safe_to_autorun": True,
            "requires_confirmation": False,
            "mutates_project": False,
            "supported_task_types": ["asset_edit", "hybrid_feature"],
            "capability_tags": ["asset", "rename", "edit", "preview"],
            "editor_action_types": ["rename_asset", "tweak_material_parameter", "modify_behavior_tree", "modify_state_tree", "modify_control_rig", "modify_niagara_system", "modify_eqs_query", "modify_level_sequence", "modify_metasound", "modify_pcg_graph", "modify_motion_matching_asset", "modify_ik_rig"],
            "summary": "Produce safe, structured asset edit plans and confirmation-gated editor actions for supported Unreal families.",
        },
        {
            "name": "open_asset_in_editor",
            "label": "Open assets in editor",
            "status": "implemented",
            "execution_target": "backend_route",
            "backend_route": "/plugin/tool",
            "safe_to_autorun": True,
            "requires_confirmation": False,
            "mutates_project": False,
            "supported_task_types": ["investigation", "asset_edit", "asset_creation", "hybrid_feature", "task_plan"],
            "capability_tags": ["editor", "navigation", "asset"],
            "summary": "Open the selected asset or generated follow-up assets directly inside the Unreal Editor.",
        },
        {
            "name": "create_cpp_classes_plugins_modules",
            "label": "Create classes/plugins/modules",
            "status": "planned",
            "execution_target": "plugin_action",
            "safe_to_autorun": False,
            "requires_confirmation": True,
            "mutates_project": True,
            "supported_task_types": ["code_generation", "hybrid_feature"],
            "capability_tags": ["code", "class", "plugin", "module"],
            "summary": "Create native Unreal code artifacts such as C++ classes, plugins, or modules with explicit confirmation.",
        },
        {
            "name": "compile_project_and_surface_errors",
            "label": "Compile and surface errors",
            "status": "implemented",
            "execution_target": "backend_route",
            "backend_route": "/plugin/tool",
            "safe_to_autorun": False,
            "requires_confirmation": False,
            "mutates_project": False,
            "supported_task_types": ["code_change", "code_generation", "hybrid_feature"],
            "capability_tags": ["compile", "validation", "errors"],
            "summary": "Run compile/build validation from the Unreal side and feed the resulting errors back into the agent loop.",
        },
    ]

    for entry in entries:
        entry["recommended"] = is_tool_recommended(entry, task_type=task_type, families=families)

    entries.sort(key=lambda item: (-int(item["recommended"]), item["label"]))
    return entries


def is_tool_recommended(entry: dict[str, Any], *, task_type: str, families: set[str]) -> bool:
    if task_type in entry.get("supported_task_types", []):
        if entry["name"] == "extract_blueprint_graph_state":
            return bool(families & {"blueprint", "animation", "behavior_tree", "state_tree", "control_rig", "niagara", "eqs", "sequencer", "metasound", "pcg", "motion_matching", "ik_rig"})
        return True
    return False


def build_recommended_tool_chain(unreal_tool_catalog: list[dict[str, Any]]) -> list[str]:
    return [item["name"] for item in unreal_tool_catalog if item.get("recommended")][:6]


def infer_confirmation_policy(task_type: str) -> dict[str, Any]:
    requires_apply_confirmation = task_type in {"code_change", "code_generation", "asset_creation", "asset_edit", "hybrid_feature"}
    return {
        "dry_run_before_apply": True,
        "requires_confirmation_for_editor_mutation": requires_apply_confirmation,
        "confirmation_triggers": [
            "code patch apply",
            "asset rename or creation",
            "plugin-side editor mutation",
        ],
        "resume_after_approval": True,
    }


def infer_tool_preferences(task_type: str, lowered_goal: str, candidate_assets: list[dict[str, Any]]) -> dict[str, Any]:
    preferred: list[str] = []
    suppressed: list[str] = []
    boosted: dict[str, int] = {}
    required_artifacts: dict[str, list[str]] = {}
    stop_after_tools: list[str] = []

    if task_type == "investigation":
        preferred = ["search_project", "read_file_context", "analyze_selection", "summarize_progress"]
        suppressed = ["draft_code_patch_bundle", "request_confirmation", "draft_asset_plan"]
        boosted["search_project"] = 90
        boosted["read_file_context"] = 70
        stop_after_tools = ["analyze_selection"]
    elif task_type == "hybrid_feature":
        preferred = ["draft_asset_plan", "draft_code_patch_bundle", "request_confirmation"]
        boosted["draft_asset_plan"] = 60
        boosted["draft_code_patch_bundle"] = 55
    elif task_type in {"code_change", "code_generation"}:
        preferred = ["draft_code_patch_bundle", "request_confirmation", "summarize_progress"]
        suppressed = ["draft_asset_plan"]
        boosted["draft_code_patch_bundle"] = 80
    elif task_type in {"asset_creation", "asset_edit"}:
        preferred = ["draft_asset_plan", "summarize_progress"]
        suppressed = ["draft_code_patch_bundle", "request_confirmation"]
        boosted["draft_asset_plan"] = 80

    if has_goal_term(lowered_goal, "explain") or has_goal_term(lowered_goal, "inspect") or has_goal_term(lowered_goal, "understand"):
        suppressed = dedupe_strings(suppressed + ["draft_code_patch_bundle", "request_confirmation"])
        boosted["search_project"] = max(boosted.get("search_project", 0), 120)
        boosted["analyze_selection"] = max(boosted.get("analyze_selection", 0), 80)

    families = {(item.get("family") or "").lower() for item in candidate_assets}
    if "blueprint" in families:
        boosted["analyze_selection"] = max(boosted.get("analyze_selection", 0), 35)
    if "enhanced_input" in families:
        boosted["draft_asset_plan"] = max(boosted.get("draft_asset_plan", 0), 40)

    required_artifacts["read_file_context"] = ["search_results"]
    required_artifacts["analyze_selection"] = ["candidate_files_or_assets"]
    required_artifacts["draft_asset_plan"] = ["selection_summary"]
    required_artifacts["draft_code_patch_bundle"] = ["selection_summary"]
    required_artifacts["request_confirmation"] = ["code_patch_bundle"]
    required_artifacts["stage_editor_execution_package"] = ["approved_editor_action"]
    required_artifacts["prepare_editor_handoff"] = ["editor_execution_package"]
    required_artifacts["stage_apply_ready_preview"] = ["editor_execution_package"]
    required_artifacts["stage_validation_commands"] = ["editor_execution_package"]
    required_artifacts["draft_supporting_asset_scaffolds"] = ["followup_assets"]
    required_artifacts["summarize_progress"] = ["analysis_complete"]

    return {
        "preferred_tools": dedupe_strings(preferred),
        "suppressed_tools": dedupe_strings(suppressed),
        "score_boosts": boosted,
        "required_artifacts": required_artifacts,
        "stop_after_tools": dedupe_strings(stop_after_tools),
    }


def build_execution_stages(
    task_type: str,
    candidate_files: list[dict[str, Any]],
    candidate_assets: list[dict[str, Any]],
    systems: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lead_file = candidate_files[0]["path"] if candidate_files else ""
    lead_asset = candidate_assets[0]["name"] if candidate_assets else ""
    lead_systems = ", ".join(item["name"] for item in systems[:3]) or "gameplay ownership"

    stages = [
        {
            "name": "Scope",
            "goal": f"Confirm the task owner and entry points across {lead_systems}.",
            "recommended_actions": dedupe_strings(
                [
                    f"Inspect `{lead_file}` first." if lead_file else "",
                    f"Inspect `{lead_asset}` first." if lead_asset else "",
                    "Review current selection, asset links, and high-signal files before changing behavior.",
                ]
            ),
        }
    ]

    if task_type in {"code_generation", "code_change", "hybrid_feature"}:
        stages.append(
            {
                "name": "Code Plan",
                "goal": "Identify the smallest code patch that satisfies the request.",
                "recommended_actions": [
                    "Trace the public entry point, owner class, and adjacent helper/component boundaries.",
                    "Prefer a narrow patch over broad refactors so compile feedback stays actionable.",
                ],
            }
        )

    if task_type in {"asset_creation", "asset_edit", "hybrid_feature"}:
        stages.append(
            {
                "name": "Asset Plan",
                "goal": "Decide which asset-side changes belong in Unreal content versus code.",
                "recommended_actions": [
                    "Generate or review a scaffold/edit plan before mutating assets.",
                    "Keep editor-side actions confirmation-gated and as small as possible.",
                ],
            }
        )

    stages.append(
        {
            "name": "Validation",
            "goal": "Verify compile/runtime/editor behavior after the smallest useful change.",
            "recommended_actions": [
                "Run backend tests or compile checks before broadening the change.",
                "Validate runtime flow in PIE/editor after content or code updates.",
            ],
        }
    )
    return stages


def infer_task_risks(task_type: str, candidate_assets: list[dict[str, Any]], systems: list[dict[str, Any]]) -> list[str]:
    risks = [
        "Ownership can drift quickly if both code and Blueprint/content are edited without a clear source of truth.",
        "Narrow previewed editor actions are safer than broad inferred mutations.",
    ]

    families = {(item.get("family") or "").lower() for item in candidate_assets}
    if task_type in {"code_generation", "code_change", "hybrid_feature"}:
        risks.append("Generated code may compile cleanly but still miss Unreal ownership, registration, or binding paths.")
    if "enhanced_input" in families:
        risks.append("Input changes often fail because the Mapping Context or binding layer is wrong, not because the asset is missing.")
    if "material" in families or "material_instance" in families:
        risks.append("Material edits can be overridden at runtime by dynamic material instances or parameter writes.")
    if any(item["name"] == "player" for item in systems):
        risks.append("Player-facing changes often cross controller, pawn, and component boundaries, so a single-file fix may be incomplete.")
    return dedupe_strings(risks)


def infer_family_hints(candidate_assets: list[dict[str, Any]], family_summaries: dict[str, Any]) -> list[str]:
    hints = []
    summary_key_map = {
        "blueprint": "blueprints",
        "animation": "animbps",
        "behavior_tree": "behavior_trees",
        "data_asset": "data_assets",
        "enhanced_input": "enhanced_input",
        "material": "materials",
        "material_instance": "materials",
        "state_tree": "state_trees",
        "control_rig": "control_rig",
        "niagara": "niagara",
        "eqs": "eqs",
        "sequencer": "sequencer",
        "metasound": "metasounds",
        "pcg": "pcg",
        "motion_matching": "motion_matching",
        "ik_rig": "ik_rig",
    }
    for asset in candidate_assets[:4]:
        family = (asset.get("family") or "").lower()
        summary = family_summaries.get(summary_key_map.get(family, family))
        if not summary:
            continue
        for bridge in summary.get("bridge_points", [])[:2]:
            hints.append(f"{asset['name']}: {bridge}")
    return dedupe_strings(hints)


def build_summary(task_type: str, candidate_files: list[dict[str, Any]], candidate_assets: list[dict[str, Any]], systems: list[dict[str, Any]]) -> str:
    file_part = candidate_files[0]["name"] if candidate_files else "no clear file owner yet"
    asset_part = candidate_assets[0]["name"] if candidate_assets else "no clear asset owner yet"
    system_part = ", ".join(item["name"] for item in systems[:3]) or "general gameplay code"
    return f"This looks like a `{task_type}` task centered on {system_part}, with `{file_part}` and `{asset_part}` as the strongest initial leads."


def extract_tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z][a-z0-9_]{2,}", text.lower()) if len(token) > 2}


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


def dedupe_dicts(items: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        value = item.get(key)
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(item)
    return result
