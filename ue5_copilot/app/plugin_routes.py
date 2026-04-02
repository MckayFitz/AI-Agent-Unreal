from fastapi import APIRouter
from pydantic import BaseModel


class AssetDetailRequest(BaseModel):
    selection: str


class AssetScaffoldRequest(BaseModel):
    asset_kind: str
    name: str
    purpose: str | None = None
    class_name: str | None = None


class AssetEditRequest(BaseModel):
    selection: str
    change_request: str


class PluginSelectionRequest(BaseModel):
    selection_name: str | None = None
    selection_type: str | None = None
    asset_path: str | None = None
    class_name: str | None = None
    change_request: str | None = None
    source: str | None = None


class DeepAssetAnalysisRequest(BaseModel):
    asset_kind: str = ""
    exported_text: str | None = None
    selection_name: str | None = None
    class_name: str | None = None
    asset_path: str | None = None
    source: str | None = None


SCAFFOLD_ALIASES = {
    "blueprint": "blueprint_class",
    "blueprint_class": "blueprint_class",
    "bp": "blueprint_class",
    "animbp": "animbp",
    "animation_blueprint": "animbp",
    "dataasset": "data_asset",
    "data_asset": "data_asset",
    "material": "material",
    "material_instance": "material_instance",
    "materialinstance": "material_instance",
    "mi": "material_instance",
    "mat": "material",
    "behavior_tree": "behavior_tree",
    "behaviortree": "behavior_tree",
    "bt": "behavior_tree",
    "input_action": "input_action",
    "inputaction": "input_action",
    "input_mapping_context": "input_mapping_context",
    "inputmappingcontext": "input_mapping_context",
    "mapping_context": "input_mapping_context",
    "imc": "input_mapping_context",
    "state_tree": "state_tree",
    "statetree": "state_tree",
    "control_rig": "control_rig",
    "controlrig": "control_rig",
    "niagara": "niagara",
    "niagara_system": "niagara",
    "eqs": "eqs",
    "env_query": "eqs",
    "sequencer": "sequencer",
    "level_sequence": "sequencer",
    "metasound": "metasound",
    "meta_sound": "metasound",
    "pcg": "pcg",
    "motion_matching": "motion_matching",
    "motionmatching": "motion_matching",
    "ik_rig": "ik_rig",
    "ikrig": "ik_rig",
}


def build_plugin_router(deps):
    router = APIRouter()

    def build_blueprint_scaffold_editor_action(response):
        asset_name = response.get("recommended_asset_name", "")
        asset_path = response.get("recommended_asset_path", "")
        parent_class = response.get("recommended_parent_class", "")
        if not asset_name or not asset_path or not parent_class:
            return None

        package_path = asset_path.replace("\\", "/")
        if package_path.startswith("Content/"):
            package_path = f"/Game/{package_path[len('Content/'):]}"

        package_name = package_path.rsplit("/", 1)[0] if "/" in package_path else "/Game"
        return {
            "action_type": "create_asset",
            "dry_run": False,
            "requires_user_confirmation": True,
            "arguments": {
                "asset_kind": "blueprint_class",
                "asset_name": asset_name,
                "package_path": package_name,
                "parent_class": parent_class,
            },
        }

    def build_simple_scaffold_editor_action(response, asset_kind):
        asset_name = response.get("recommended_asset_name", "")
        asset_path = response.get("recommended_asset_path", "")
        if not asset_name or not asset_path:
            return None

        package_path = asset_path.replace("\\", "/")
        if package_path.startswith("Content/"):
            package_path = f"/Game/{package_path[len('Content/'):]}"

        package_name = package_path.rsplit("/", 1)[0] if "/" in package_path else "/Game"
        return {
            "action_type": "create_asset",
            "dry_run": False,
            "requires_user_confirmation": True,
            "arguments": {
                "asset_kind": asset_kind,
                "asset_name": asset_name,
                "package_path": package_name,
            },
        }

    def build_asset_scaffold_response(request: AssetScaffoldRequest):
        asset_kind = request.asset_kind.strip().lower()
        name = request.name.strip()
        purpose = (request.purpose or "").strip()
        class_name = (request.class_name or "").strip()

        if not asset_kind:
            return {"error": "Choose an asset kind first."}
        if not name:
            return {"error": "Provide an asset name first."}

        resolved = SCAFFOLD_ALIASES.get(asset_kind, asset_kind)

        if resolved == "blueprint_class":
            response = deps["build_blueprint_class_scaffold"](name=name, purpose=purpose, class_name=class_name)
            editor_action = build_blueprint_scaffold_editor_action(response)
            if editor_action:
                response["editor_action"] = editor_action
            return response
        if resolved == "data_asset":
            return deps["build_data_asset_scaffold"](name=name, purpose=purpose, class_name=class_name)
        if resolved == "animbp":
            return deps["build_animbp_scaffold"](name=name, purpose=purpose, class_name=class_name)
        if resolved == "material":
            return deps["build_material_scaffold"](name=name, purpose=purpose)
        if resolved == "material_instance":
            response = deps["build_material_instance_scaffold"](name=name, purpose=purpose, class_name=class_name)
            editor_action = build_simple_scaffold_editor_action(response, "material_instance")
            if editor_action:
                if class_name:
                    editor_action["arguments"]["parent_material"] = class_name
                response["editor_action"] = editor_action
            return response
        if resolved == "behavior_tree":
            return deps["build_behavior_tree_scaffold"](name=name, purpose=purpose)
        if resolved == "input_action":
            response = deps["build_input_action_scaffold"](name=name, purpose=purpose)
            editor_action = build_simple_scaffold_editor_action(response, "input_action")
            if editor_action:
                response["editor_action"] = editor_action
            return response
        if resolved == "input_mapping_context":
            response = deps["build_input_mapping_context_scaffold"](name=name, purpose=purpose)
            editor_action = build_simple_scaffold_editor_action(response, "input_mapping_context")
            if editor_action:
                response["editor_action"] = editor_action
            return response
        if resolved == "state_tree":
            return deps["build_state_tree_scaffold"](name=name, purpose=purpose)
        if resolved == "control_rig":
            return deps["build_control_rig_scaffold"](name=name, purpose=purpose)
        if resolved == "niagara":
            return deps["build_niagara_scaffold"](name=name, purpose=purpose)
        if resolved == "eqs":
            return deps["build_eqs_scaffold"](name=name, purpose=purpose)
        if resolved == "sequencer":
            return deps["build_sequencer_scaffold"](name=name, purpose=purpose)
        if resolved == "metasound":
            return deps["build_metasound_scaffold"](name=name, purpose=purpose)
        if resolved == "pcg":
            return deps["build_pcg_scaffold"](name=name, purpose=purpose)
        if resolved == "motion_matching":
            return deps["build_motion_matching_scaffold"](name=name, purpose=purpose)
        if resolved == "ik_rig":
            return deps["build_ik_rig_scaffold"](name=name, purpose=purpose)

        return {
            "error": "Scaffolding currently supports blueprint_class, animbp, data_asset, material, material_instance, behavior_tree, input_action, input_mapping_context, state_tree, control_rig, niagara, eqs, sequencer, metasound, pcg, motion_matching, and ik_rig."
        }

    def build_asset_edit_plan_response(selection: str, change_request: str):
        return deps["run_asset_action"](
            "asset_edit_plan",
            analysis=deps["project_cache"]["analysis"],
            selection=selection,
            change_request=change_request,
            looks_like_rename_request=deps["looks_like_rename_request"],
            looks_like_function_request=deps["looks_like_function_request"],
            build_asset_rename_edit_plan=deps["build_asset_rename_edit_plan"],
            build_data_asset_edit_plan=deps["build_data_asset_edit_plan"],
            build_enhanced_input_edit_plan=deps["build_enhanced_input_edit_plan"],
            build_behavior_tree_edit_plan=deps["build_behavior_tree_edit_plan"],
            build_material_edit_plan=deps["build_material_edit_plan"],
            build_animbp_edit_plan=deps["build_animbp_edit_plan"],
            build_state_tree_edit_plan=deps["build_state_tree_edit_plan"],
            build_control_rig_edit_plan=deps["build_control_rig_edit_plan"],
            build_niagara_edit_plan=deps["build_niagara_edit_plan"],
            build_eqs_edit_plan=deps["build_eqs_edit_plan"],
            build_sequencer_edit_plan=deps["build_sequencer_edit_plan"],
            build_metasound_edit_plan=deps["build_metasound_edit_plan"],
            build_pcg_edit_plan=deps["build_pcg_edit_plan"],
            build_motion_matching_edit_plan=deps["build_motion_matching_edit_plan"],
            build_ik_rig_edit_plan=deps["build_ik_rig_edit_plan"],
            build_blueprint_function_edit_plan=deps["build_blueprint_function_edit_plan"],
            build_blueprint_variable_edit_plan=deps["build_blueprint_variable_edit_plan"],
        )

    @router.post("/asset-details")
    def asset_details(request: AssetDetailRequest):
        return deps["run_asset_action"](
            "asset_details",
            analysis=deps["project_cache"]["analysis"],
            selection=request.selection,
        )

    @router.post("/plugin/asset-details")
    def plugin_asset_details(request: PluginSelectionRequest):
        return deps["run_asset_action"](
            "plugin_asset_details",
            analysis=deps["project_cache"]["analysis"],
            selection_name=request.selection_name or "",
            asset_path=request.asset_path or "",
            class_name=request.class_name or "",
            source=request.source or "plugin",
        )

    @router.post("/asset-scaffold")
    def asset_scaffold(request: AssetScaffoldRequest):
        return build_asset_scaffold_response(request)

    @router.post("/asset-edit-plan")
    def asset_edit_plan(request: AssetEditRequest):
        return build_asset_edit_plan_response(
            selection=request.selection,
            change_request=request.change_request,
        )

    @router.post("/plugin/asset-edit-plan")
    def plugin_asset_edit_plan(request: PluginSelectionRequest):
        selection = (request.selection_name or request.asset_path or request.class_name or "").strip()
        change_request = (request.change_request or "").strip()
        return build_asset_edit_plan_response(selection=selection, change_request=change_request)

    @router.post("/plugin/selection-context")
    def plugin_selection_context(request: PluginSelectionRequest):
        analysis = deps["project_cache"]["analysis"]
        if not analysis:
            return {"error": "No project has been scanned yet."}

        selection_name = (request.selection_name or "").strip()
        selection_type = (request.selection_type or "unknown").strip()
        asset_path = (request.asset_path or "").strip()
        class_name = (request.class_name or "").strip()

        lookup_terms = [term for term in [selection_name, class_name, asset_path] if term]
        if not lookup_terms:
            return {"error": "The plugin did not send enough selection information."}

        primary_term = selection_name or class_name or asset_path
        base_result = deps["selection_analysis"](deps["selection_request_class"](selection=primary_term))
        specialized_summary = deps["run_asset_action"](
            "plugin_specialized_family",
            analysis=analysis,
            selection_name=selection_name,
            class_name=class_name,
            asset_path=asset_path,
        )

        matched_files = deps["search_files"](
            analysis["files"],
            " ".join(lookup_terms),
            max_results=6,
            index_data=deps["project_cache"]["search_index"],
        )

        return {
            "selection_name": selection_name,
            "selection_type": selection_type,
            "asset_path": asset_path,
            "class_name": class_name,
            "source": request.source or "plugin",
            "selection_analysis": base_result,
            "matched_files": matched_files,
            "specialized_family": specialized_summary,
        }

    @router.post("/asset-deep-analysis")
    def asset_deep_analysis(request: DeepAssetAnalysisRequest):
        return deps["run_asset_action"](
            "asset_deep_analysis",
            analysis=deps["project_cache"]["analysis"],
            asset_kind=request.asset_kind,
            exported_text=request.exported_text or "",
            selection_name=request.selection_name or "",
            class_name=request.class_name or "",
            asset_path=request.asset_path or "",
            source=request.source or "web",
            include_ai_summary=deps["include_ai_summary"](),
            summarize_with_llm=deps["summarize_deep_asset_with_llm"],
        )

    return router
