import json
import os

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
    project_path: str | None = None
    source: str | None = None


class PluginChatRequest(BaseModel):
    message: str
    selection_name: str | None = None
    selection_type: str | None = None
    asset_path: str | None = None
    class_name: str | None = None
    exported_text: str | None = None
    project_path: str | None = None
    source: str | None = None


class DeepAssetAnalysisRequest(BaseModel):
    asset_kind: str = ""
    exported_text: str | None = None
    selection_name: str | None = None
    class_name: str | None = None
    asset_path: str | None = None
    project_path: str | None = None
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

    def ensure_project_loaded(request_project_path: str | None = None):
        requested_project_path = (request_project_path or "").strip()
        current_project_path = (deps["project_cache"].get("project_path") or "").strip()
        analysis = deps["project_cache"].get("analysis")

        if analysis:
            if not requested_project_path:
                return None
            if os.path.normcase(current_project_path) == os.path.normcase(requested_project_path):
                return None

        if not requested_project_path:
            return {"error": "No project has been scanned yet."}

        result = deps["load_project_into_cache"](requested_project_path)
        if "error" in result:
            return result
        return None

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

    def build_data_asset_scaffold_editor_action(response):
        editor_action = build_simple_scaffold_editor_action(response, "data_asset")
        if not editor_action:
            return None

        recommended_class_name = (response.get("recommended_class_name") or "").strip()
        if not recommended_class_name:
            return None

        editor_action["arguments"]["asset_class"] = recommended_class_name
        return editor_action

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
            response = deps["build_data_asset_scaffold"](name=name, purpose=purpose, class_name=class_name)
            editor_action = build_data_asset_scaffold_editor_action(response)
            if editor_action:
                response["editor_action"] = editor_action
            return response
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

    def infer_asset_kind_from_text(text: str) -> str:
        lowered = text.strip().lower()
        for alias, resolved in sorted(SCAFFOLD_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            if alias in lowered:
                return resolved
        return ""

    def fallback_chat_intent(message: str, selection_name: str, asset_path: str, class_name: str, exported_text: str):
        lowered = message.strip().lower()
        has_selection = bool(selection_name or asset_path or class_name)

        if should_route_to_agent_session(
            message=message,
            selection_name=selection_name,
            asset_path=asset_path,
            class_name=class_name,
            exported_text=exported_text,
        ):
            return {
                "intent": "agent_session",
                "asset_kind": "",
                "asset_name": "",
                "purpose": "",
                "class_name": class_name,
                "change_request": message,
            }

        if exported_text.strip():
            return {
                "intent": "asset_deep_analysis",
                "asset_kind": infer_asset_kind_from_text(message),
                "asset_name": "",
                "purpose": "",
                "class_name": class_name,
                "change_request": message,
            }

        if any(token in lowered for token in ["create ", "new ", "scaffold", "generate "]):
            return {
                "intent": "asset_scaffold",
                "asset_kind": infer_asset_kind_from_text(message),
                "asset_name": "",
                "purpose": message,
                "class_name": class_name,
                "change_request": "",
            }

        if has_selection and any(token in lowered for token in ["rename", "change", "modify", "update", "fix", "set", "add ", "remove ", "replace", "tweak"]):
            return {
                "intent": "asset_edit_plan",
                "asset_kind": "",
                "asset_name": "",
                "purpose": "",
                "class_name": class_name,
                "change_request": message,
            }

        if has_selection:
            return {
                "intent": "plugin_asset_details",
                "asset_kind": "",
                "asset_name": "",
                "purpose": "",
                "class_name": class_name,
                "change_request": "",
            }

        return {
            "intent": "ask",
            "asset_kind": "",
            "asset_name": "",
            "purpose": "",
            "class_name": class_name,
            "change_request": "",
        }

    def classify_chat_request(message: str, selection_name: str, asset_type: str, asset_path: str, class_name: str, exported_text: str, matched_files):
        if not os.getenv("OPENAI_API_KEY") or "client" not in deps:
            return fallback_chat_intent(message, selection_name, asset_path, class_name, exported_text)

        selection_summary = "\n".join(
            line for line in [
                f"Selection Name: {selection_name or 'None'}",
                f"Selection Type: {asset_type or 'None'}",
                f"Asset Path: {asset_path or 'None'}",
                f"Class Name: {class_name or 'None'}",
                f"Has Exported Text: {'yes' if exported_text.strip() else 'no'}",
            ] if line
        )
        file_context = "\n".join(f"- {match['path']}" for match in matched_files[:6]) or "- None"

        planner_prompt = f"""
You are classifying a UE5 plugin chat request into one backend action.

Return JSON only with these keys:
- intent: one of ask, plugin_asset_details, asset_edit_plan, asset_scaffold, asset_deep_analysis, agent_session
- asset_kind: empty string when unknown
- asset_name: empty string when unknown
- purpose: empty string when unknown
- class_name: empty string when unknown
- change_request: empty string when not relevant

Rules:
- Use ask for general UE5/project questions.
- Use plugin_asset_details when the user wants explanation or inspection of the current selection.
- Use asset_edit_plan when the user wants to change, rename, add to, or fix the selected asset.
- Use asset_scaffold when the user wants a new asset planned or created.
- Use asset_deep_analysis when exported graph/state text is provided or the user explicitly asks for deep analysis.
- Use agent_session when the request is a multi-step implementation task that crosses code plus assets, needs a staged workflow, or should pause for confirmation before editor-side changes.
- Prefer asset_edit_plan over plugin_asset_details when the user asks for a change.
- Prefer agent_session over asset_edit_plan when the user is asking for a broader feature workflow instead of a single asset edit.
- Preserve concrete asset names and class hints when they appear.

User message:
{message}

Current selection:
{selection_summary}

Relevant project files:
{file_context}
"""

        try:
            response = deps["client"].chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "You classify Unreal Engine editor assistant requests into a single best backend action."},
                    {"role": "user", "content": planner_prompt},
                ],
            )
            content = (response.choices[0].message.content or "").strip()
            payload = json.loads(content)
            if isinstance(payload, dict) and payload.get("intent"):
                return {
                    "intent": str(payload.get("intent", "ask")).strip(),
                    "asset_kind": str(payload.get("asset_kind", "")).strip(),
                    "asset_name": str(payload.get("asset_name", "")).strip(),
                    "purpose": str(payload.get("purpose", "")).strip(),
                    "class_name": str(payload.get("class_name", "")).strip() or class_name,
                    "change_request": str(payload.get("change_request", "")).strip(),
                }
        except Exception:
            pass

        return fallback_chat_intent(message, selection_name, asset_path, class_name, exported_text)

    def should_route_to_agent_session(*, message: str, selection_name: str, asset_path: str, class_name: str, exported_text: str) -> bool:
        lowered = (message or "").strip().lower()
        if not lowered or exported_text.strip():
            return False

        if any(token in lowered for token in ("plan only", "just explain", "explain", "inspect")):
            return False

        code_tokens = (
            "code",
            "c++",
            "cpp",
            "class",
            "function",
            "hook",
            "wire",
            "bind",
            "player character",
            "character",
            "controller",
            "component",
        )
        asset_tokens = (
            "asset",
            "blueprint",
            "input action",
            "mapping context",
            "material",
            "behavior tree",
            "state tree",
            "niagara",
            "metasound",
        )
        multi_step_tokens = (
            "add ",
            "implement",
            "set up",
            "setup",
            "create",
            "and hook",
            "and wire",
            "end to end",
        )
        has_code_signal = any(token in lowered for token in code_tokens)
        has_asset_signal = any(token in lowered for token in asset_tokens)
        has_multi_step_signal = any(token in lowered for token in multi_step_tokens)
        has_selection = bool(selection_name or asset_path or class_name)

        if ("input" in lowered and has_code_signal and has_multi_step_signal):
            return True
        if has_code_signal and has_asset_signal and has_multi_step_signal:
            return True
        if has_selection and has_code_signal and any(token in lowered for token in ("follow-up", "workflow", "staged", "confirm")):
            return True
        return False

    def build_plugin_agent_session(message: str):
        session = deps["start_agent_task_session"](
            goal=message,
            files=deps["project_cache"]["analysis"]["files"],
            assets=deps["project_cache"]["analysis"]["assets"],
            matched_files=deps["search_files"](
                deps["project_cache"]["analysis"]["files"],
                message,
                max_results=8,
                index_data=deps["project_cache"]["search_index"],
            ),
            family_summaries=deps["summarize_specialized_assets"](
                deps["project_cache"]["analysis"]["files"],
                deps["project_cache"]["analysis"]["assets"],
            ),
        )
        deps["agent_task_cache"][session["task_id"]] = session
        deps["remember_interaction"](message, session.get("result", {}).get("summary") or session["steps"][-1]["summary"])
        return {
            "intent": "agent_session",
            "answer": session.get("result", {}).get("summary") or session["steps"][-1]["summary"],
            "goal": session["goal"],
            "task_id": session["task_id"],
            "execution_mode": session["execution_mode"],
            "status": session["status"],
            "available_tools": session.get("available_tools", []),
            "steps": session.get("steps", []),
            "plan": session.get("plan"),
            "pending_confirmation": session.get("pending_confirmation"),
            "approved_editor_action": session.get("approved_editor_action"),
            "result": session.get("result"),
            "session": session,
        }

    def build_chat_answer(message: str, selection_name: str, asset_type: str, asset_path: str, class_name: str, matched_files):
        files = deps["project_cache"]["files"]
        if not files:
            return {"answer": "No project has been scanned yet.", "matches": []}

        if not os.getenv("OPENAI_API_KEY") or "client" not in deps:
            return {
                "answer": "OPENAI_API_KEY is not configured yet.",
                "matches": matched_files,
            }

        context_text = "\n\n".join(
            f"FILE: {match['path']}\nSNIPPET:\n{match['snippet']}"
            for match in matched_files
        ) or "No directly matching file snippets were found."

        selection_context = "\n".join([
            f"Selection Name: {selection_name or 'None'}",
            f"Selection Type: {asset_type or 'None'}",
            f"Asset Path: {asset_path or 'None'}",
            f"Class Name: {class_name or 'None'}",
        ])

        user_prompt = f"""
User question or task:
{message}

Current Unreal selection:
{selection_context}

Recent context:
{deps["format_recent_history"]()}

Relevant project context:
{context_text}
"""

        response = deps["client"].chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": deps["system_prompt"]()},
                {"role": "user", "content": user_prompt},
            ],
        )

        answer = response.choices[0].message.content
        deps["remember_interaction"](message, answer)
        return {
            "answer": answer,
            "matches": matched_files,
            "selection_name": selection_name,
            "selection_type": asset_type,
            "asset_path": asset_path,
            "class_name": class_name,
        }

    @router.post("/asset-details")
    def asset_details(request: AssetDetailRequest):
        return deps["run_asset_action"](
            "asset_details",
            analysis=deps["project_cache"]["analysis"],
            selection=request.selection,
        )

    @router.post("/plugin/asset-details")
    def plugin_asset_details(request: PluginSelectionRequest):
        ensure_result = ensure_project_loaded(request.project_path)
        if ensure_result and "error" in ensure_result:
            return ensure_result

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
        ensure_result = ensure_project_loaded(request.project_path)
        if ensure_result and "error" in ensure_result:
            return ensure_result

        selection = (request.selection_name or request.asset_path or request.class_name or "").strip()
        change_request = (request.change_request or "").strip()
        return build_asset_edit_plan_response(selection=selection, change_request=change_request)

    @router.post("/plugin/selection-context")
    def plugin_selection_context(request: PluginSelectionRequest):
        ensure_result = ensure_project_loaded(request.project_path)
        if ensure_result and "error" in ensure_result:
            return ensure_result

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

    @router.post("/plugin/chat")
    def plugin_chat(request: PluginChatRequest):
        ensure_result = ensure_project_loaded(request.project_path)
        if ensure_result and "error" in ensure_result:
            return {"answer": ensure_result["error"]}

        analysis = deps["project_cache"]["analysis"]
        if not analysis:
            return {"answer": "No project has been scanned yet."}

        message = (request.message or "").strip()
        if not message:
            return {"answer": "Ask a question or describe what you want to do in Unreal."}

        selection_name = (request.selection_name or "").strip()
        selection_type = (request.selection_type or "").strip()
        asset_path = (request.asset_path or "").strip()
        class_name = (request.class_name or "").strip()
        exported_text = request.exported_text or ""

        search_query = " ".join(part for part in [message, selection_name, class_name, asset_path] if part)
        matched_files = deps["search_files"](
            analysis["files"],
            search_query,
            max_results=6,
            index_data=deps["project_cache"]["search_index"],
        )

        plan = classify_chat_request(
            message,
            selection_name,
            selection_type,
            asset_path,
            class_name,
            exported_text,
            matched_files,
        )

        intent = plan.get("intent", "ask")
        if intent == "plugin_asset_details":
            if not (selection_name or asset_path or class_name):
                return {
                    "answer": "Select an actor or asset first, or ask a general project question.",
                    "matches": matched_files,
                }
            return deps["run_asset_action"](
                "plugin_asset_details",
                analysis=analysis,
                selection_name=selection_name,
                asset_path=asset_path,
                class_name=class_name,
                source=request.source or "plugin_chat",
            )

        if intent == "asset_edit_plan":
            selection = (selection_name or asset_path or class_name).strip()
            if not selection:
                return {
                    "answer": "I think you want to change an asset, but I need you to select that actor or asset first.",
                    "matches": matched_files,
                }
            return build_asset_edit_plan_response(selection=selection, change_request=plan.get("change_request") or message)

        if intent == "asset_scaffold":
            asset_kind = plan.get("asset_kind", "").strip()
            asset_name = plan.get("asset_name", "").strip()
            if not asset_kind:
                return {
                    "answer": "I think you want to create a new asset, but I could not infer the asset type yet. Try saying something like `Create a Behavior Tree named BT_EnemyCombat`.",
                    "matches": matched_files,
                }
            if not asset_name:
                return {
                    "answer": f"I think you want to create a new `{asset_kind}` asset, but I still need a concrete asset name.",
                    "matches": matched_files,
                }
            return build_asset_scaffold_response(
                AssetScaffoldRequest(
                    asset_kind=asset_kind,
                    name=asset_name,
                    purpose=plan.get("purpose") or message,
                    class_name=plan.get("class_name") or class_name,
                )
            )

        if intent == "asset_deep_analysis":
            if not (selection_name or asset_path or class_name):
                return {
                    "answer": "Select an actor or asset first before running deep analysis.",
                    "matches": matched_files,
                }
            return deps["run_asset_action"](
                "asset_deep_analysis",
                analysis=analysis,
                asset_kind=plan.get("asset_kind", ""),
                exported_text=exported_text,
                selection_name=selection_name,
                class_name=class_name,
                asset_path=asset_path,
                source=request.source or "plugin_chat",
                include_ai_summary=deps["include_ai_summary"](),
                summarize_with_llm=deps["summarize_deep_asset_with_llm"],
            )

        if intent == "agent_session":
            return build_plugin_agent_session(message)

        answer = build_chat_answer(message, selection_name, selection_type, asset_path, class_name, matched_files)
        answer["intent"] = intent
        return answer

    @router.post("/asset-deep-analysis")
    def asset_deep_analysis(request: DeepAssetAnalysisRequest):
        ensure_result = ensure_project_loaded(request.project_path)
        if ensure_result and "error" in ensure_result:
            return ensure_result

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
