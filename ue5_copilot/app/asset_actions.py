from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.ue_analysis import (
    analyze_deep_asset,
    build_asset_details,
    find_matching_assets,
    infer_deep_asset_kind,
    summarize_specialized_assets,
)


AssetActionHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class AssetAction:
    name: str
    handler: AssetActionHandler

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        return self.handler(**kwargs)


def handle_asset_details(*, analysis: dict[str, Any] | None, selection: str, source: str | None = None) -> dict[str, Any]:
    selection = (selection or "").strip()
    if not selection:
        return {"error": "Enter an asset name or scanned asset path."}
    if not analysis:
        return {"error": "No project has been scanned yet."}

    asset_matches = find_matching_assets(analysis["assets"], selection, limit=8)
    if not asset_matches:
        return {"error": "No matching scanned asset was found."}

    summaries = summarize_specialized_assets(analysis["files"], analysis["assets"])
    result = build_asset_details(
        selection=selection,
        asset=asset_matches[0],
        files=analysis["files"],
        assets=analysis["assets"],
        blueprint_links=analysis["blueprint_links"],
        family_summaries=summaries,
    )
    result["asset_matches"] = asset_matches[:8]
    if source:
        result["source"] = source
    return result


def handle_plugin_asset_details(
    *,
    analysis: dict[str, Any] | None,
    selection_name: str = "",
    asset_path: str = "",
    class_name: str = "",
    source: str | None = None,
) -> dict[str, Any]:
    if not analysis:
        return {"error": "No project has been scanned yet."}

    lookup_terms = [
        term.strip()
        for term in [selection_name or "", asset_path or "", class_name or ""]
        if term and term.strip()
    ]
    for term in lookup_terms:
        result = handle_asset_details(analysis=analysis, selection=term, source=source)
        if "error" not in result:
            return result

    return {"error": "No matching scanned asset was found for the current plugin selection."}


def handle_specialized_asset_family(*, analysis: dict[str, Any] | None, family: str, include_ai_summary: bool = False, summarize_with_llm: Callable[[dict[str, Any]], str] | None = None) -> dict[str, Any]:
    if not analysis:
        return {"error": "No project has been scanned yet."}

    summaries = summarize_specialized_assets(analysis["files"], analysis["assets"])
    family = family.strip().lower()
    aliases = {
        "blueprints": "blueprints",
        "animbps": "animbps",
        "behavior trees": "behavior_trees",
        "behavior_trees": "behavior_trees",
        "dataassets": "data_assets",
        "data_assets": "data_assets",
        "enhanced input": "enhanced_input",
        "enhanced_input": "enhanced_input",
        "materials": "materials",
        "statetrees": "state_trees",
        "state_trees": "state_trees",
        "control rig": "control_rig",
        "control_rig": "control_rig",
        "niagara": "niagara",
        "eqs": "eqs",
        "sequencer": "sequencer",
        "metasounds": "metasounds",
        "metasound": "metasounds",
        "pcg": "pcg",
        "motion matching": "motion_matching",
        "motion_matching": "motion_matching",
        "ik rig": "ik_rig",
        "ik_rig": "ik_rig",
    }
    resolved = aliases.get(family, family)
    if resolved not in summaries:
        return {"error": "Unknown family. Try enhanced_input, behavior_trees, data_assets, materials, animbps, state_trees, control_rig, niagara, eqs, sequencer, metasounds, pcg, motion_matching, or ik_rig."}
    summary = summaries[resolved]
    if include_ai_summary and summarize_with_llm and (summary["assets"] or summary["code_signals"]):
        summary["ai_summary"] = summarize_with_llm(summary)
    return summary


def handle_blueprint_links(*, analysis: dict[str, Any] | None, class_name: str) -> dict[str, Any]:
    lowered = class_name.strip().lower()
    if not lowered:
        return {"error": "Enter a C++ class name first."}
    if not analysis:
        return {"error": "No project has been scanned yet."}

    matches = [item for item in analysis["blueprint_links"] if lowered in item["class_name"].lower()]
    asset_fallback = []
    for asset in analysis["assets"]:
        asset_name = asset["name"].lower()
        if lowered in asset_name or asset_name.endswith(lowered.lstrip("au")):
            asset_fallback.append(asset)

    return {
        "class_name": class_name,
        "matches": matches,
        "asset_fallback": asset_fallback[:8],
    }


def handle_asset_deep_analysis(
    *,
    analysis: dict[str, Any] | None,
    asset_kind: str,
    exported_text: str = "",
    selection_name: str = "",
    class_name: str = "",
    asset_path: str = "",
    source: str | None = None,
    include_ai_summary: bool = False,
    summarize_with_llm: Callable[[dict[str, Any], str], str] | None = None,
) -> dict[str, Any]:
    if not analysis:
        return {"error": "No project has been scanned yet."}

    asset_kind = asset_kind.strip().lower()
    exported_text = (exported_text or "").strip()
    selection_name = (selection_name or "").strip()
    class_name = (class_name or "").strip()
    asset_path = (asset_path or "").strip()
    matched_asset = None

    lookup_term = selection_name or asset_path
    if lookup_term:
        matches = find_matching_assets(analysis["assets"], lookup_term, limit=1)
        matched_asset = matches[0] if matches else None

    asset_kind = infer_deep_asset_kind(
        asset=matched_asset,
        selection_name=selection_name,
        asset_path=asset_path,
        asset_kind=asset_kind,
    )
    if not asset_kind:
        return {"error": "Asset kind could not be inferred. Pick a deep asset kind or provide a clearer selected asset name/path."}

    summaries = summarize_specialized_assets(analysis["files"], analysis["assets"])
    family_aliases = {
        "blueprint": "blueprints",
        "animbp": "animbps",
        "animation_blueprint": "animbps",
        "behavior_tree": "behavior_trees",
        "material": "materials",
        "enhanced_input": "enhanced_input",
        "input": "enhanced_input",
        "state_tree": "state_trees",
        "control_rig": "control_rig",
        "niagara": "niagara",
        "eqs": "eqs",
        "sequencer": "sequencer",
        "metasound": "metasounds",
        "pcg": "pcg",
        "motion_matching": "motion_matching",
        "ik_rig": "ik_rig",
        "data_asset": "data_assets",
    }
    family_summary = summaries.get(family_aliases.get(asset_kind, asset_kind))

    result = analyze_deep_asset(
        asset_kind=asset_kind,
        exported_text=exported_text,
        selection_name=selection_name or (matched_asset or {}).get("name", ""),
        class_name=class_name,
        family_summary=family_summary,
    )
    result["asset_path"] = asset_path or (matched_asset or {}).get("path", "")
    result["resolved_asset_kind"] = asset_kind
    if matched_asset:
        result["resolved_asset_name"] = matched_asset.get("name", "")
    result["source"] = source or "web"

    if include_ai_summary and summarize_with_llm and exported_text:
        result["ai_summary"] = summarize_with_llm(result, exported_text)
    return result


def handle_asset_edit_plan(
    *,
    analysis: dict[str, Any] | None,
    selection: str,
    change_request: str,
    looks_like_rename_request: Callable[[str], bool],
    looks_like_function_request: Callable[[str], bool],
    build_asset_rename_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_data_asset_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_enhanced_input_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_behavior_tree_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_material_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_animbp_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_state_tree_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_control_rig_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_niagara_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_eqs_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_sequencer_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_metasound_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_pcg_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_motion_matching_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_ik_rig_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_blueprint_function_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    build_blueprint_variable_edit_plan: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    selection = (selection or "").strip()
    change_request = (change_request or "").strip()

    if not selection:
        return {"error": "Select an asset first."}
    if not change_request:
        return {"error": "Describe the change you want first."}
    if not analysis:
        return {"error": "No project has been scanned yet."}

    asset_matches = find_matching_assets(analysis["assets"], selection, limit=4)
    if not asset_matches:
        return {"error": "No matching scanned asset was found."}

    asset = asset_matches[0]
    family = asset.get("family", "")
    asset_type = asset.get("asset_type", "")
    details = handle_asset_details(analysis=analysis, selection=selection)

    if looks_like_rename_request(change_request):
        return build_asset_rename_edit_plan(asset, change_request, details)
    if family == "data_asset" or asset_type == "data_asset":
        return build_data_asset_edit_plan(asset, change_request, details)
    if family == "enhanced_input" or asset_type in {"input_action", "input_mapping_context"}:
        return build_enhanced_input_edit_plan(asset, change_request, details)
    if family in {"behavior_tree", "blackboard"} or asset_type in {"behavior_tree", "blackboard"}:
        return build_behavior_tree_edit_plan(asset, change_request, details)
    if family in {"material", "material_instance"} or "material" in asset_type:
        return build_material_edit_plan(asset, change_request, details)
    if family == "animation" or asset_type in {"animation_blueprint", "animation_asset"}:
        return build_animbp_edit_plan(asset, change_request, details)
    if family == "state_tree" or asset_type == "state_tree":
        return build_state_tree_edit_plan(asset, change_request, details)
    if family == "control_rig" or asset_type == "control_rig":
        return build_control_rig_edit_plan(asset, change_request, details)
    if family == "niagara" or asset_type == "niagara_system":
        return build_niagara_edit_plan(asset, change_request, details)
    if family == "eqs" or asset_type == "eqs":
        return build_eqs_edit_plan(asset, change_request, details)
    if family == "sequencer" or asset_type == "sequencer":
        return build_sequencer_edit_plan(asset, change_request, details)
    if family == "metasound" or asset_type == "metasound":
        return build_metasound_edit_plan(asset, change_request, details)
    if family == "pcg" or asset_type == "pcg":
        return build_pcg_edit_plan(asset, change_request, details)
    if family == "motion_matching" or asset_type == "motion_matching":
        return build_motion_matching_edit_plan(asset, change_request, details)
    if family == "ik_rig" or asset_type == "ik_rig":
        return build_ik_rig_edit_plan(asset, change_request, details)
    if family in {"blueprint", "ui"} or "blueprint" in asset_type:
        if looks_like_function_request(change_request):
            return build_blueprint_function_edit_plan(asset, change_request, details)
        return build_blueprint_variable_edit_plan(asset, change_request, details)
    return {"error": "Controlled edit plans currently support rename planning plus DataAssets, Enhanced Input, Behavior Trees, Materials, AnimBPs, StateTrees, Control Rig, Niagara, EQS, Sequencer, MetaSounds, PCG, Motion Matching, IK Rig, and Blueprint variable/function planning."}


def handle_plugin_specialized_family(
    *,
    analysis: dict[str, Any] | None,
    selection_name: str = "",
    class_name: str = "",
    asset_path: str = "",
) -> dict[str, Any] | None:
    if not analysis:
        return None

    summaries = summarize_specialized_assets(analysis["files"], analysis["assets"])
    haystack = " ".join(term for term in [selection_name, class_name, asset_path] if term).lower()
    if not haystack:
        return None

    for summary in summaries.values():
        title = summary.get("title", "").lower()
        family_key = summary.get("family_key", "").lower()
        if family_key in haystack or any(asset["name"].lower() in haystack for asset in summary.get("assets", [])):
            return summary
        if title and any(part in haystack for part in title.split()):
            return summary
    return None


ASSET_ACTIONS = {
    "asset_details": AssetAction("asset_details", handle_asset_details),
    "plugin_asset_details": AssetAction("plugin_asset_details", handle_plugin_asset_details),
    "specialized_asset_family": AssetAction("specialized_asset_family", handle_specialized_asset_family),
    "blueprint_links": AssetAction("blueprint_links", handle_blueprint_links),
    "asset_deep_analysis": AssetAction("asset_deep_analysis", handle_asset_deep_analysis),
    "asset_edit_plan": AssetAction("asset_edit_plan", handle_asset_edit_plan),
    "plugin_specialized_family": AssetAction("plugin_specialized_family", handle_plugin_specialized_family),
}


def run_asset_action(name: str, **kwargs: Any) -> dict[str, Any]:
    action = ASSET_ACTIONS.get(name)
    if not action:
        return {"error": f"Unknown asset action: {name}"}
    return action.execute(**kwargs)
