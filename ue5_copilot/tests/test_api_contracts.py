import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.search_index import build_search_index
from app.ue_analysis import build_project_analysis
from app import main as app_main


def build_sample_analysis():
    files = [
        {
            "path": "Source/MyGame/Public/Player/MyPlayerCharacter.h",
            "name": "MyPlayerCharacter.h",
            "extension": ".h",
            "file_type": "header",
            "content": """
                UCLASS(Blueprintable)
                class AMyPlayerCharacter : public ACharacter
                {
                    GENERATED_BODY()
                public:
                    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Movement")
                    float MaxSprintSpeed;

                    UFUNCTION(BlueprintCallable, Category="Animation")
                    void RefreshAnimationState();
                };
            """,
        },
        {
            "path": "Source/MyGame/Private/Player/MyPlayerCharacter.cpp",
            "name": "MyPlayerCharacter.cpp",
            "extension": ".cpp",
            "file_type": "source",
            "content": """
                #include "MyPlayerCharacter.h"
                void AMyPlayerCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
                {
                    Super::SetupPlayerInputComponent(PlayerInputComponent);
                }

                void AMyPlayerCharacter::RefreshAnimationState() {}
                // BP_PlayerCharacter owns the player-facing runtime behavior.
            """,
        },
    ]
    assets = [
        {
            "name": "BP_PlayerCharacter.uasset",
            "path": "C:/Project/Content/Blueprints/BP_PlayerCharacter.uasset",
            "relative_path": "Content/Blueprints/BP_PlayerCharacter.uasset",
            "extension": ".uasset",
            "asset_type": "blueprint",
            "likely_blueprint": True,
        },
        {
            "name": "MS_WeaponFire.uasset",
            "path": "C:/Project/Content/Audio/MetaSounds/MS_WeaponFire.uasset",
            "relative_path": "Content/Audio/MetaSounds/MS_WeaponFire.uasset",
            "extension": ".uasset",
            "asset_type": "metasound",
            "likely_blueprint": False,
        },
        {
            "name": "MI_WeaponGlow.uasset",
            "path": "C:/Project/Content/Materials/Instances/MI_WeaponGlow.uasset",
            "relative_path": "Content/Materials/Instances/MI_WeaponGlow.uasset",
            "extension": ".uasset",
            "asset_type": "material_instance",
            "likely_blueprint": False,
        },
    ]
    return build_project_analysis(files, assets)


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        self.previous_cache = dict(app_main.PROJECT_CACHE)
        analysis = build_sample_analysis()
        self.load_analysis(analysis)

    def tearDown(self):
        app_main.PROJECT_CACHE.clear()
        app_main.PROJECT_CACHE.update(self.previous_cache)
        app_main.AGENT_TASK_CACHE.clear()

    def load_analysis(self, analysis):
        app_main.PROJECT_CACHE["project_path"] = "C:/Project"
        app_main.PROJECT_CACHE["files"] = analysis["files"]
        app_main.PROJECT_CACHE["assets"] = analysis["assets"]
        app_main.PROJECT_CACHE["analysis"] = analysis
        app_main.PROJECT_CACHE["conversation_history"] = []
        app_main.PROJECT_CACHE["current_focus"] = None
        app_main.PROJECT_CACHE["search_index"] = build_search_index(analysis["files"])

    def test_status_reports_loaded_cache(self):
        response = self.client.get("/status")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["project_path"], "C:/Project")
        self.assertEqual(payload["file_count"], 2)
        self.assertEqual(payload["asset_count"], 3)
        self.assertIn("indexed_terms", payload)

    def test_asset_scaffold_supports_blueprint_alias(self):
        response = self.client.post(
            "/asset-scaffold",
            json={"asset_kind": "bp", "name": "InteractableDoor", "purpose": "Door actor"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["asset_kind"], "blueprint_class")
        self.assertEqual(payload["recommended_asset_name"], "BP_InteractableDoor")
        self.assertEqual(payload["editor_action"]["action_type"], "create_asset")
        self.assertEqual(payload["editor_action"]["arguments"]["asset_kind"], "blueprint_class")
        self.assertEqual(payload["editor_action"]["arguments"]["asset_name"], "BP_InteractableDoor")

    def test_asset_scaffold_returns_create_action_for_input_action(self):
        response = self.client.post(
            "/asset-scaffold",
            json={"asset_kind": "input_action", "name": "Sprint", "purpose": "Player sprint"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["asset_kind"], "input_action")
        self.assertEqual(payload["recommended_asset_name"], "IA_Sprint")
        self.assertEqual(payload["editor_action"]["action_type"], "create_asset")
        self.assertEqual(payload["editor_action"]["arguments"]["asset_kind"], "input_action")
        self.assertEqual(payload["editor_action"]["arguments"]["asset_name"], "IA_Sprint")

    def test_asset_scaffold_returns_create_action_for_mapping_context(self):
        response = self.client.post(
            "/asset-scaffold",
            json={"asset_kind": "input_mapping_context", "name": "PlayerDefault", "purpose": "Default player controls"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["asset_kind"], "input_mapping_context")
        self.assertEqual(payload["recommended_asset_name"], "IMC_PlayerDefault")
        self.assertEqual(payload["editor_action"]["action_type"], "create_asset")
        self.assertEqual(payload["editor_action"]["arguments"]["asset_kind"], "input_mapping_context")
        self.assertEqual(payload["editor_action"]["arguments"]["asset_name"], "IMC_PlayerDefault")

    def test_asset_scaffold_returns_create_action_for_material_instance(self):
        response = self.client.post(
            "/asset-scaffold",
            json={"asset_kind": "material_instance", "name": "WeaponGlow", "purpose": "Weapon variant", "class_name": "M_WeaponBase"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["asset_kind"], "material_instance")
        self.assertEqual(payload["recommended_asset_name"], "MI_WeaponGlow")
        self.assertEqual(payload["editor_action"]["action_type"], "create_asset")
        self.assertEqual(payload["editor_action"]["arguments"]["asset_kind"], "material_instance")
        self.assertEqual(payload["editor_action"]["arguments"]["asset_name"], "MI_WeaponGlow")
        self.assertEqual(payload["editor_action"]["arguments"]["parent_material"], "M_WeaponBase")

    def test_asset_scaffold_returns_create_action_for_data_asset(self):
        response = self.client.post(
            "/asset-scaffold",
            json={"asset_kind": "data_asset", "name": "WeaponConfig", "purpose": "Weapon tuning", "class_name": "UWeaponConfigDataAsset"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["asset_kind"], "data_asset")
        self.assertEqual(payload["recommended_asset_name"], "DA_WeaponConfig")
        self.assertEqual(payload["editor_action"]["action_type"], "create_asset")
        self.assertEqual(payload["editor_action"]["arguments"]["asset_kind"], "data_asset")
        self.assertEqual(payload["editor_action"]["arguments"]["asset_name"], "DA_WeaponConfig")
        self.assertEqual(payload["editor_action"]["arguments"]["asset_class"], "UWeaponConfigDataAsset")

    def test_plugin_asset_details_returns_blueprint_asset_payload(self):
        response = self.client.post(
            "/plugin/asset-details",
            json={
                "selection_name": "BP_PlayerCharacter",
                "asset_path": "Content/Blueprints/BP_PlayerCharacter.uasset",
                "class_name": "Blueprint",
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["resolved_asset_name"], "BP_PlayerCharacter")
        self.assertEqual(payload["asset"]["family"], "blueprint")

    def test_plugin_asset_details_auto_scans_project_when_project_path_is_provided(self):
        app_main.PROJECT_CACHE["project_path"] = None
        app_main.PROJECT_CACHE["files"] = []
        app_main.PROJECT_CACHE["assets"] = []
        app_main.PROJECT_CACHE["analysis"] = None
        app_main.PROJECT_CACHE["search_index"] = None

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            (project_root / "Source" / "MyGame" / "Public").mkdir(parents=True, exist_ok=True)
            (project_root / "Content" / "Blueprints").mkdir(parents=True, exist_ok=True)
            (project_root / "Source" / "MyGame" / "Public" / "MyPlayerCharacter.h").write_text(
                "UCLASS(Blueprintable) class AMyPlayerCharacter : public ACharacter { GENERATED_BODY() };",
                encoding="utf-8",
            )
            (project_root / "Content" / "Blueprints" / "BP_PlayerCharacter.uasset").write_bytes(b"\x00")

            response = self.client.post(
                "/plugin/asset-details",
                json={
                    "selection_name": "BP_PlayerCharacter",
                    "asset_path": "Content/Blueprints/BP_PlayerCharacter.uasset",
                    "class_name": "Blueprint",
                    "project_path": str(project_root),
                    "source": "ue5_plugin",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resolved_asset_name"], "BP_PlayerCharacter")
        self.assertEqual(app_main.PROJECT_CACHE["project_path"], str(project_root))

    def test_plugin_asset_edit_plan_returns_blueprint_variable_plan(self):
        response = self.client.post(
            "/plugin/asset-edit-plan",
            json={
                "selection_name": "BP_PlayerCharacter",
                "asset_path": "Content/Blueprints/BP_PlayerCharacter.uasset",
                "change_request": "add a sprinting bool variable",
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["asset_kind"], "blueprint_variable_edit")
        self.assertEqual(payload["linked_cpp_owner"], "AMyPlayerCharacter")
        self.assertEqual(payload["asset_name"], "BP_PlayerCharacter.uasset")

    def test_plugin_asset_edit_plan_returns_material_instance_editor_action(self):
        response = self.client.post(
            "/plugin/asset-edit-plan",
            json={
                "selection_name": "MI_WeaponGlow",
                "asset_path": "Content/Materials/Instances/MI_WeaponGlow.uasset",
                "change_request": "set roughness to 0.35",
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["asset_kind"], "material_edit")
        self.assertEqual(payload["editor_action"]["action_type"], "tweak_material_parameter")
        self.assertEqual(payload["editor_action"]["arguments"]["parameter_name"], "Roughness")
        self.assertEqual(payload["editor_action"]["arguments"]["parameter_value"], "0.35")

    def test_plugin_asset_edit_plan_returns_material_instance_texture_editor_action(self):
        response = self.client.post(
            "/plugin/asset-edit-plan",
            json={
                "selection_name": "MI_WeaponGlow",
                "asset_path": "Content/Materials/Instances/MI_WeaponGlow.uasset",
                "change_request": "set base texture to \"T_WeaponAlbedo\"",
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["asset_kind"], "material_edit")
        self.assertEqual(payload["editor_action"]["action_type"], "tweak_material_parameter")
        self.assertEqual(payload["editor_action"]["arguments"]["parameter_name"], "BaseTexture")
        self.assertEqual(payload["editor_action"]["arguments"]["parameter_type"], "texture")
        self.assertEqual(payload["editor_action"]["arguments"]["parameter_value"], "T_WeaponAlbedo")

    def test_plugin_selection_context_returns_selection_analysis_and_matches(self):
        response = self.client.post(
            "/plugin/selection-context",
            json={
                "selection_name": "BP_PlayerCharacter",
                "selection_type": "asset",
                "asset_path": "Content/Blueprints/BP_PlayerCharacter.uasset",
                "class_name": "Blueprint",
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["selection_name"], "BP_PlayerCharacter")
        self.assertEqual(payload["selection_analysis"]["selection_type"], "asset")
        self.assertTrue(payload["matched_files"])
        self.assertIn("specialized_family", payload)

    def test_asset_deep_analysis_auto_detects_metasound(self):
        response = self.client.post(
            "/asset-deep-analysis",
            json={
                "asset_kind": "auto",
                "selection_name": "MS_WeaponFire",
                "asset_path": "Content/Audio/MetaSounds/MS_WeaponFire.uasset",
                "exported_text": """
                    Graph Input: Pitch
                    Trigger On Play
                    Wave Player: RifleShot
                    Envelope Follower
                    Graph Output: Audio
                """,
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["resolved_asset_kind"], "metasound")
        self.assertIn("MetaSound", payload["summary"])

    def test_plugin_chat_routes_multi_step_request_to_agent_session(self):
        response = self.client.post(
            "/plugin/chat",
            json={
                "message": "add sprint input and hook it to the player character",
                "selection_name": "BP_PlayerCharacter",
                "selection_type": "asset",
                "asset_path": "Content/Blueprints/BP_PlayerCharacter.uasset",
                "class_name": "Blueprint",
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["intent"], "agent_session")
        self.assertTrue(payload["task_id"])
        self.assertEqual(payload["status"], "awaiting_confirmation")
        self.assertEqual(payload["execution_mode"], "agent_loop")
        self.assertEqual(payload["steps"][0]["tool_name"], "inspect_project_context")
        self.assertEqual(payload["steps"][1]["tool_name"], "plan_task")
        self.assertEqual(payload["available_tools"], ["confirm_agent_step"])
        self.assertEqual(payload["pending_confirmation"]["editor_action"]["action_type"], "apply_code_patch_bundle_preview")
        self.assertEqual(payload["result"]["code_patch_bundle"]["draft_files"][0]["path"], "Source/MyGame/Public/Player/MyPlayerCharacter.h")
        self.assertEqual(payload["session"]["execution_mode"], "agent_loop")
        self.assertEqual(payload["session"]["orchestration"]["phase"], "awaiting_confirmation")
        self.assertEqual(payload["session"]["orchestration"]["progress"]["current"], "confirm_agent_step")
        self.assertEqual(payload["session"]["orchestration"]["proposed_plan"][0]["tool_name"], "inspect_project_context")
        self.assertEqual(
            app_main.AGENT_TASK_CACHE[payload["task_id"]]["status"],
            "awaiting_confirmation",
        )

    def test_plugin_tool_catalog_returns_agent_and_unreal_tools(self):
        response = self.client.post(
            "/plugin/tool",
            json={"tool_name": "tool_catalog", "source": "ue5_plugin"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["tool_name"], "tool_catalog")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["payload"]["agent_profile"], "tool_using_agent")
        self.assertTrue(payload["payload"]["orchestration_tools"])
        self.assertTrue(payload["payload"]["unreal_tool_catalog"])
        self.assertTrue(payload["payload"]["confirmation_policy"]["dry_run_before_apply"])

    def test_plugin_tool_read_current_selection_routes_through_normalized_dispatch(self):
        response = self.client.post(
            "/plugin/tool",
            json={
                "tool_name": "read_current_selection",
                "selection_name": "BP_PlayerCharacter",
                "selection_type": "asset",
                "asset_path": "Content/Blueprints/BP_PlayerCharacter.uasset",
                "class_name": "Blueprint",
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["tool_name"], "read_current_selection")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["payload"]["selection_name"], "BP_PlayerCharacter")
        self.assertEqual(payload["payload"]["selection_analysis"]["selection_type"], "asset")
        self.assertTrue(payload["payload"]["matched_files"])

    def test_plugin_tool_open_asset_in_editor_returns_open_asset_action(self):
        response = self.client.post(
            "/plugin/tool",
            json={
                "tool_name": "open_asset_in_editor",
                "selection_name": "BP_PlayerCharacter",
                "selection_type": "asset",
                "asset_path": "Content/Blueprints/BP_PlayerCharacter.uasset",
                "class_name": "Blueprint",
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["tool_name"], "open_asset_in_editor")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["editor_action"]["action_type"], "open_asset")
        self.assertFalse(payload["editor_action"]["requires_user_confirmation"])
        self.assertEqual(
            payload["editor_action"]["arguments"]["asset_path"],
            "Content/Blueprints/BP_PlayerCharacter.uasset",
        )

    def test_plugin_tool_compile_project_returns_compile_action(self):
        response = self.client.post(
            "/plugin/tool",
            json={
                "tool_name": "compile_project_and_surface_errors",
                "project_path": "C:/Project",
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["tool_name"], "compile_project_and_surface_errors")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["editor_action"]["action_type"], "compile_project")
        self.assertEqual(payload["editor_action"]["arguments"]["project_path"], "C:/Project")
        self.assertEqual(payload["editor_action"]["arguments"]["configuration"], "Development")
        self.assertEqual(payload["editor_action"]["arguments"]["platform"], "Win64")

    def test_plugin_tool_report_compile_result_summarizes_failure(self):
        response = self.client.post(
            "/plugin/tool",
            json={
                "tool_name": "report_compile_result",
                "project_path": "C:/Project",
                "tool_args": {
                    "exit_code": 6,
                    "target_name": "MyGameEditor",
                    "platform": "Win64",
                    "configuration": "Development",
                    "log_path": "C:/Project/Saved/Logs/compile_test.log",
                    "output_text": (
                        "Source/MyGame/Private/Player/MyPlayerCharacter.cpp(42): error C2664: "
                        "cannot convert argument 1 from 'int' to 'FName'\n"
                        "Build failed."
                    ),
                },
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["tool_name"], "report_compile_result")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["payload"]["exit_code"], 6)
        self.assertTrue(payload["payload"]["diagnosis"])
        self.assertTrue(payload["payload"]["error_lines"])
        self.assertIn(
            "Source/MyGame/Private/Player/MyPlayerCharacter.cpp",
            payload["payload"]["file_hints"][0],
        )
        self.assertTrue(payload["payload"]["next_steps"])
        self.assertTrue(payload["payload"]["suggested_tool_invocations"])
        self.assertTrue(payload["payload"]["suggested_agent_goal"])
        self.assertEqual(
            payload["payload"]["preferred_target_path"],
            "Source/MyGame/Private/Player/MyPlayerCharacter.cpp",
        )
        self.assertEqual(
            payload["payload"]["suggested_tool_invocations"][0]["tool_name"],
            "plan_code_changes",
        )
        self.assertEqual(
            payload["payload"]["suggested_tool_invocations"][0]["tool_args"]["target_path"],
            "Source/MyGame/Private/Player/MyPlayerCharacter.cpp",
        )

    def test_plugin_tool_report_compile_result_can_auto_start_followup_agent_session(self):
        response = self.client.post(
            "/plugin/tool",
            json={
                "tool_name": "report_compile_result",
                "project_path": "C:/Project",
                "tool_args": {
                    "exit_code": 6,
                    "target_name": "MyGameEditor",
                    "platform": "Win64",
                    "configuration": "Development",
                    "log_path": "C:/Project/Saved/Logs/compile_test.log",
                    "auto_start_agent_session": True,
                    "output_text": (
                        "Source/MyGame/Private/Player/MyPlayerCharacter.cpp(42): error C2664: "
                        "cannot convert argument 1 from 'int' to 'FName'\n"
                        "Build failed."
                    ),
                },
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["tool_name"], "report_compile_result")
        self.assertEqual(payload["status"], "error")
        self.assertTrue(payload["payload"]["followup_agent_task_id"])
        self.assertEqual(payload["payload"]["followup_agent_session"]["intent"], "agent_session")
        self.assertIn("fix the Unreal compile error", payload["payload"]["followup_agent_session"]["goal"])
        self.assertEqual(
            app_main.AGENT_TASK_CACHE[payload["payload"]["followup_agent_task_id"]]["task_id"],
            payload["payload"]["followup_agent_task_id"],
        )

    def test_plugin_tool_plan_code_changes_returns_preview_editor_action(self):
        response = self.client.post(
            "/plugin/tool",
            json={
                "tool_name": "plan_code_changes",
                "tool_args": {"goal": "add sprint input and hook it to the player character"},
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["tool_name"], "plan_code_changes")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["editor_action"]["action_type"], "apply_code_patch_bundle_preview")
        self.assertTrue(payload["payload"]["draft_files"])

    def test_plugin_tool_plan_code_changes_honors_target_path(self):
        response = self.client.post(
            "/plugin/tool",
            json={
                "tool_name": "plan_code_changes",
                "tool_args": {
                    "goal": "fix the compile error in the player character source",
                    "target_path": "Source/MyGame/Private/Player/MyPlayerCharacter.cpp",
                },
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["tool_name"], "plan_code_changes")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            payload["payload"]["preferred_target_path"],
            "Source/MyGame/Private/Player/MyPlayerCharacter.cpp",
        )
        self.assertEqual(
            payload["payload"]["draft_files"][0]["path"],
            "Source/MyGame/Private/Player/MyPlayerCharacter.cpp",
        )

    def test_plugin_chat_keeps_simple_asset_edit_plan_flow(self):
        response = self.client.post(
            "/plugin/chat",
            json={
                "message": "set roughness to 0.35",
                "selection_name": "MI_WeaponGlow",
                "selection_type": "asset",
                "asset_path": "Content/Materials/Instances/MI_WeaponGlow.uasset",
                "class_name": "MaterialInstance",
                "source": "ue5_plugin",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["asset_kind"], "material_edit")
        self.assertEqual(payload["editor_action"]["action_type"], "tweak_material_parameter")
        self.assertEqual(payload["editor_action"]["arguments"]["parameter_name"], "Roughness")
        self.assertEqual(payload["editor_action"]["arguments"]["parameter_value"], "0.35")

    def test_agent_task_returns_structured_hybrid_plan(self):
        response = self.client.post(
            "/agent-task",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["task_type"], "hybrid_feature")
        self.assertEqual(payload["execution_mode"], "plan_only")
        self.assertIn("/asset-scaffold", payload["suggested_backend_routes"])
        self.assertIn("/plugin/asset-edit-plan", payload["suggested_backend_routes"])
        self.assertTrue(payload["candidate_files"])
        self.assertTrue(payload["candidate_assets"])
        self.assertTrue(payload["stages"])

    def test_agent_task_exposes_tool_using_agent_catalog(self):
        response = self.client.post(
            "/agent-task",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["agent_profile"], "tool_using_agent")
        self.assertTrue(payload["recommended_tool_chain"])
        self.assertTrue(payload["unreal_tool_catalog"])
        self.assertTrue(payload["confirmation_policy"]["dry_run_before_apply"])
        self.assertEqual(payload["unreal_tool_catalog"][0]["recommended"], True)
        self.assertIn(
            "read_current_selection",
            [item["name"] for item in payload["unreal_tool_catalog"]],
        )
        self.assertIn(
            "compile_project_and_surface_errors",
            [item["name"] for item in payload["unreal_tool_catalog"]],
        )

    def test_agent_task_requires_scanned_project(self):
        app_main.PROJECT_CACHE["analysis"] = None
        app_main.PROJECT_CACHE["files"] = []
        app_main.PROJECT_CACHE["assets"] = []

        response = self.client.post(
            "/agent-task",
            json={"goal": "add sprint input"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error"], "No project has been scanned yet.")

    def test_agent_session_runs_tool_sequence_and_waits_for_confirmation(self):
        response = self.client.post(
            "/agent-session",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["execution_mode"], "agent_loop")
        self.assertEqual(payload["status"], "awaiting_confirmation")
        self.assertTrue(payload["task_id"])
        self.assertEqual([step["tool_name"] for step in payload["steps"][:8]], [
            "inspect_project_context",
            "plan_task",
            "search_project",
            "read_file_context",
            "analyze_selection",
            "draft_asset_plan",
            "draft_code_patch_bundle",
            "request_confirmation",
        ])
        self.assertEqual(payload["available_tools"], ["confirm_agent_step"])
        self.assertEqual(payload["pending_confirmation"]["editor_action"]["action_type"], "apply_code_patch_bundle_preview")
        self.assertIn("Source/MyGame/Public/Player/MyPlayerCharacter.h", payload["pending_confirmation"]["target_paths"])
        self.assertEqual(payload["orchestration"]["phase"], "awaiting_confirmation")
        self.assertEqual(payload["orchestration"]["progress"]["current"], "confirm_agent_step")
        self.assertEqual(payload["orchestration"]["tool_catalog"][0]["name"], "inspect_project_context")
        self.assertEqual(payload["orchestration"]["tool_catalog"][0]["execution_target"], "backend_orchestrator")
        self.assertTrue(payload["orchestration"]["tool_catalog"][0]["capability_tags"])
        self.assertEqual(payload["orchestration"]["execution_trace"][0]["tool_name"], "inspect_project_context")
        self.assertEqual(payload["orchestration"]["proposed_plan"][7]["tool_name"], "request_confirmation")
        self.assertEqual(payload["orchestration"]["ranked_candidates"][0]["tool_name"], "confirm_agent_step")
        self.assertEqual(payload["context"]["file_contexts"][0]["path"], "Source/MyGame/Public/Player/MyPlayerCharacter.h")
        self.assertEqual(payload["last_tool_result"]["tool_name"], "request_confirmation")

    def test_agent_tools_endpoint_returns_orchestration_and_unreal_catalogs(self):
        response = self.client.get("/agent-tools")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["agent_profile"], "tool_using_agent")
        self.assertEqual(payload["execution_mode"], "tool_catalog")
        self.assertTrue(payload["orchestration_tools"])
        self.assertTrue(payload["unreal_tool_catalog"])
        self.assertTrue(payload["confirmation_policy"]["resume_after_approval"])
        self.assertIn(
            "plan_code_changes",
            [item["name"] for item in payload["unreal_tool_catalog"]],
        )
        self.assertIn(
            "draft_code_patch_bundle",
            [item["name"] for item in payload["orchestration_tools"]],
        )

    def test_agent_session_status_and_confirmation_flow(self):
        create_response = self.client.post(
            "/agent-session",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(create_response.status_code, 200)
        created_payload = create_response.json()
        task_id = created_payload["task_id"]

        status_response = self.client.get(f"/agent-session/{task_id}")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["task_id"], task_id)
        self.assertEqual(status_response.json()["status"], "awaiting_confirmation")

        post_status_response = self.client.post(f"/agent-session/{task_id}/status")
        self.assertEqual(post_status_response.status_code, 200)
        self.assertEqual(post_status_response.json()["task_id"], task_id)
        self.assertEqual(post_status_response.json()["status"], "awaiting_confirmation")

        confirm_response = self.client.post(
            f"/agent-session/{task_id}/confirm",
            json={"decision": "approve"},
        )
        self.assertEqual(confirm_response.status_code, 200)
        confirmed_payload = confirm_response.json()
        self.assertEqual(confirmed_payload["status"], "ready_for_editor_apply")
        self.assertIsNone(confirmed_payload["pending_confirmation"])
        self.assertEqual(confirmed_payload["approved_editor_action"]["action_type"], "apply_code_patch_bundle_preview")
        self.assertEqual(confirmed_payload["steps"][-1]["tool_name"], "resolve_confirmation")
        self.assertEqual(confirmed_payload["available_tools"], ["resume_agent_session"])
        self.assertEqual(confirmed_payload["result"]["next_action"], "resume_agent_session")
        self.assertEqual(confirmed_payload["orchestration"]["phase"], "approved_waiting_for_resume")
        self.assertEqual(confirmed_payload["orchestration"]["progress"]["current"], "resume_agent_session")
        self.assertEqual(confirmed_payload["pending_decision"], None)
        self.assertEqual(confirmed_payload["artifacts"]["session_approval"]["task_id"], task_id)
        self.assertTrue(confirmed_payload["artifacts"]["session_approval"]["approval_token"])
        self.assertEqual(
            confirmed_payload["orchestration"]["execution_state"]["current_stage"],
            "approved_waiting_for_resume",
        )
        self.assertEqual(
            confirmed_payload["orchestration"]["execution_state"]["next_required_action"],
            "resume_agent_session",
        )

    def test_agent_session_execution_state_endpoint_tracks_lifecycle(self):
        app_main.PROJECT_CACHE["project_path"] = None
        app_main.PROJECT_CACHE["files"] = []
        app_main.PROJECT_CACHE["assets"] = []
        app_main.PROJECT_CACHE["analysis"] = None
        app_main.PROJECT_CACHE["search_index"] = None

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            header_path = project_root / "Source" / "MyGame" / "Public" / "MyPlayerCharacter.h"
            source_path = project_root / "Source" / "MyGame" / "Private" / "MyPlayerCharacter.cpp"
            header_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.parent.mkdir(parents=True, exist_ok=True)
            header_path.write_text(
                """
                UCLASS(Blueprintable)
                class AMyPlayerCharacter : public ACharacter
                {
                    GENERATED_BODY()
                public:
                    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Movement")
                    float MaxSprintSpeed;
                };
                """,
                encoding="utf-8",
            )
            source_path.write_text(
                """
                #include "MyPlayerCharacter.h"
                void AMyPlayerCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
                {
                    Super::SetupPlayerInputComponent(PlayerInputComponent);
                }
                """,
                encoding="utf-8",
            )

            scan_response = self.client.post("/scan-project", json={"project_path": str(project_root)})
            self.assertEqual(scan_response.status_code, 200)

            create_response = self.client.post(
                "/agent-session",
                json={"goal": "add sprint input and hook it to the player character"},
            )
            self.assertEqual(create_response.status_code, 200)
            task_id = create_response.json()["task_id"]

            initial_execution_state = self.client.get(f"/agent-session/{task_id}/execution-state")
            self.assertEqual(initial_execution_state.status_code, 200)
            self.assertEqual(
                initial_execution_state.json()["execution_state"]["current_stage"],
                "awaiting_confirmation",
            )

            confirm_response = self.client.post(
                f"/agent-session/{task_id}/confirm",
                json={"decision": "approve"},
            )
            self.assertEqual(confirm_response.status_code, 200)

            approved_execution_state = self.client.post(f"/agent-session/{task_id}/execution-state")
            self.assertEqual(approved_execution_state.status_code, 200)
            self.assertEqual(
                approved_execution_state.json()["execution_state"]["current_stage"],
                "approved_waiting_for_resume",
            )

            resume_response = self.client.post(f"/agent-session/{task_id}/resume")
            self.assertEqual(resume_response.status_code, 200)
            apply_ready_preview = resume_response.json()["result"]["apply_ready_preview"]

            apply_ready_execution_state = self.client.get(f"/agent-session/{task_id}/execution-state")
            self.assertEqual(apply_ready_execution_state.status_code, 200)
            self.assertEqual(
                apply_ready_execution_state.json()["execution_state"]["current_stage"],
                "approved_waiting_for_dry_run",
            )

            dry_run_response = self.client.post(
                "/code-patch-bundle-apply-dry-run",
                json=apply_ready_preview["dry_run_request"],
            )
            self.assertEqual(dry_run_response.status_code, 200)
            receipt_token = dry_run_response.json()["dry_run_receipt"]["receipt_token"]

            dry_run_execution_state = self.client.get(f"/agent-session/{task_id}/execution-state")
            self.assertEqual(dry_run_execution_state.status_code, 200)
            self.assertEqual(
                dry_run_execution_state.json()["execution_state"]["current_stage"],
                "dry_run_verified",
            )

            apply_request = dict(apply_ready_preview["final_apply_request"])
            apply_request["receipt_token"] = receipt_token
            apply_response = self.client.post(
                "/code-patch-bundle-apply",
                json=apply_request,
            )
            self.assertEqual(apply_response.status_code, 200)

            applied_execution_state = self.client.post(f"/agent-session/{task_id}/execution-state")
            self.assertEqual(applied_execution_state.status_code, 200)
            self.assertEqual(
                applied_execution_state.json()["execution_state"]["current_stage"],
                "applied",
            )

    def test_agent_session_events_endpoint_supports_incremental_polling(self):
        app_main.PROJECT_CACHE["project_path"] = None
        app_main.PROJECT_CACHE["files"] = []
        app_main.PROJECT_CACHE["assets"] = []
        app_main.PROJECT_CACHE["analysis"] = None
        app_main.PROJECT_CACHE["search_index"] = None

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            header_path = project_root / "Source" / "MyGame" / "Public" / "MyPlayerCharacter.h"
            source_path = project_root / "Source" / "MyGame" / "Private" / "MyPlayerCharacter.cpp"
            header_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.parent.mkdir(parents=True, exist_ok=True)
            header_path.write_text(
                """
                UCLASS(Blueprintable)
                class AMyPlayerCharacter : public ACharacter
                {
                    GENERATED_BODY()
                public:
                    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Movement")
                    float MaxSprintSpeed;
                };
                """,
                encoding="utf-8",
            )
            source_path.write_text(
                """
                #include "MyPlayerCharacter.h"
                void AMyPlayerCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
                {
                    Super::SetupPlayerInputComponent(PlayerInputComponent);
                }
                """,
                encoding="utf-8",
            )

            scan_response = self.client.post("/scan-project", json={"project_path": str(project_root)})
            self.assertEqual(scan_response.status_code, 200)

            create_response = self.client.post(
                "/agent-session",
                json={"goal": "add sprint input and hook it to the player character"},
            )
            self.assertEqual(create_response.status_code, 200)
            task_id = create_response.json()["task_id"]

            initial_events = self.client.get(f"/agent-session/{task_id}/events")
            self.assertEqual(initial_events.status_code, 200)
            initial_payload = initial_events.json()
            self.assertGreaterEqual(len(initial_payload["events"]), 1)
            self.assertEqual(initial_payload["events"][0]["event_type"], "tool_step")
            cursor = initial_payload["next_cursor"]

            continue_response = self.client.post(
                f"/agent-session/{task_id}/confirm-and-continue",
                json={"decision": "approve"},
            )
            self.assertEqual(continue_response.status_code, 200)
            apply_ready_preview = continue_response.json()["result"]["apply_ready_preview"]

            orchestration_events = self.client.get(f"/agent-session/{task_id}/events?after={cursor}")
            self.assertEqual(orchestration_events.status_code, 200)
            orchestration_payload = orchestration_events.json()
            self.assertGreaterEqual(len(orchestration_payload["events"]), 1)
            self.assertEqual(orchestration_payload["events"][0]["event_type"], "tool_step")
            cursor = orchestration_payload["next_cursor"]

            dry_run_response = self.client.post(
                "/code-patch-bundle-apply-dry-run",
                json=apply_ready_preview["dry_run_request"],
            )
            self.assertEqual(dry_run_response.status_code, 200)

            dry_run_events = self.client.post(f"/agent-session/{task_id}/events?after={cursor}")
            self.assertEqual(dry_run_events.status_code, 200)
            dry_run_payload = dry_run_events.json()
            self.assertEqual(dry_run_payload["events"][-1]["event_type"], "dry_run_verified")
            self.assertEqual(
                dry_run_payload["execution_state"]["current_stage"],
                "dry_run_verified",
            )
            cursor = dry_run_payload["next_cursor"]

            apply_request = dict(apply_ready_preview["final_apply_request"])
            apply_request["receipt_token"] = dry_run_response.json()["dry_run_receipt"]["receipt_token"]
            apply_response = self.client.post(
                "/code-patch-bundle-apply",
                json=apply_request,
            )
            self.assertEqual(apply_response.status_code, 200)

            applied_events = self.client.get(f"/agent-session/{task_id}/events?after={cursor}")
            self.assertEqual(applied_events.status_code, 200)
            applied_payload = applied_events.json()
            self.assertEqual(applied_payload["events"][-1]["event_type"], "applied")
            self.assertEqual(
                applied_payload["execution_state"]["current_stage"],
                "applied",
            )

    def test_agent_session_resume_continues_after_approval(self):
        create_response = self.client.post(
            "/agent-session",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(create_response.status_code, 200)
        task_id = create_response.json()["task_id"]

        confirm_response = self.client.post(
            f"/agent-session/{task_id}/confirm",
            json={"decision": "approve"},
        )
        self.assertEqual(confirm_response.status_code, 200)

        resume_response = self.client.post(f"/agent-session/{task_id}/resume")
        self.assertEqual(resume_response.status_code, 200)

        resumed_payload = resume_response.json()
        self.assertEqual(resumed_payload["status"], "completed")
        self.assertEqual(resumed_payload["steps"][-6]["tool_name"], "stage_editor_execution_package")
        self.assertEqual(resumed_payload["steps"][-5]["tool_name"], "stage_apply_ready_preview")
        self.assertEqual(resumed_payload["steps"][-4]["tool_name"], "stage_validation_commands")
        self.assertEqual(resumed_payload["steps"][-3]["tool_name"], "prepare_editor_handoff")
        self.assertEqual(resumed_payload["steps"][-2]["tool_name"], "draft_supporting_asset_scaffolds")
        self.assertEqual(resumed_payload["steps"][-1]["tool_name"], "summarize_progress")
        self.assertEqual(resumed_payload["available_tools"], [])
        self.assertEqual(resumed_payload["result"]["next_action"], "apply_in_editor_and_validate")
        self.assertEqual(resumed_payload["result"]["followup_asset_plans"][0]["recommended_name"], "IA_Sprint")
        self.assertEqual(resumed_payload["result"]["followup_asset_plans"][1]["recommended_name"], "IMC_PlayerDefault")
        self.assertEqual(
            resumed_payload["result"]["editor_execution_package"]["approved_editor_action"]["action_type"],
            "apply_code_patch_bundle_preview",
        )
        self.assertEqual(
            resumed_payload["result"]["apply_ready_preview"]["action_type"],
            "apply_code_patch_bundle_preview",
        )
        self.assertEqual(
            resumed_payload["result"]["apply_ready_preview"]["dry_run_route"],
            "/code-patch-bundle-apply-dry-run",
        )
        self.assertEqual(
            resumed_payload["result"]["apply_ready_preview"]["dry_run_request"]["files"][0]["target_path"],
            "Source/MyGame/Public/Player/MyPlayerCharacter.h",
        )
        self.assertEqual(
            resumed_payload["result"]["apply_ready_preview"]["final_apply_route"],
            "/code-patch-bundle-apply",
        )
        self.assertTrue(
            resumed_payload["result"]["apply_ready_preview"]["final_apply_request"]["dry_run_verified"]
        )
        self.assertEqual(
            resumed_payload["result"]["apply_ready_preview"]["final_apply_request"]["verification_token"],
            resumed_payload["result"]["apply_ready_preview"]["verification_bundle"]["verification_token"],
        )
        self.assertEqual(
            resumed_payload["result"]["apply_ready_preview"]["session_approval"]["task_id"],
            task_id,
        )
        self.assertEqual(
            resumed_payload["result"]["apply_ready_preview"]["final_apply_request"]["approval_token"],
            resumed_payload["result"]["apply_ready_preview"]["session_approval"]["approval_token"],
        )
        self.assertTrue(
            resumed_payload["result"]["apply_ready_preview"]["dry_run_receipt"]["required_for_final_apply"]
        )
        self.assertIsNone(
            resumed_payload["result"]["apply_ready_preview"]["final_apply_request"]["receipt_token"]
        )
        self.assertEqual(
            resumed_payload["result"]["validation_commands"][0]["kind"],
            "verify_targets",
        )
        self.assertEqual(
            resumed_payload["result"]["validation_commands"][1]["command"],
            ".\\venv\\Scripts\\python.exe -m unittest tests.test_api_contracts",
        )
        self.assertEqual(resumed_payload["result"]["supporting_asset_scaffolds"][0]["asset_kind"], "input_action")
        self.assertEqual(
            resumed_payload["result"]["supporting_asset_scaffolds"][0]["editor_action"]["action_type"],
            "create_asset",
        )
        self.assertEqual(
            resumed_payload["result"]["supporting_asset_scaffolds"][1]["editor_action"]["arguments"]["package_path"],
            "/Game/Input/Contexts",
        )
        self.assertEqual(resumed_payload["orchestration"]["phase"], "completed")
        self.assertEqual(resumed_payload["orchestration"]["progress"]["current"], None)
        self.assertEqual(
            resumed_payload["orchestration"]["execution_state"]["current_stage"],
            "approved_waiting_for_dry_run",
        )
        self.assertEqual(
            resumed_payload["orchestration"]["execution_state"]["next_required_action"],
            "code_patch_bundle_apply_dry_run",
        )
        self.assertTrue(
            any(item["tool_name"] == "prepare_editor_handoff" for item in resumed_payload["orchestration"]["execution_trace"])
        )

    def test_command_contract_lists_tool_catalog_and_richer_editor_actions(self):
        contract_path = Path("plugin/UE5CopilotAssistant/Docs/command_contract.json")
        contract = json.loads(contract_path.read_text(encoding="utf-8"))

        commands = {item["name"]: item for item in contract["commands"]}
        self.assertIn("tool_catalog", commands)
        self.assertIn("plugin_tool", commands)
        self.assertEqual(commands["tool_catalog"]["mapped_backend_route"], "/agent-tools")
        self.assertEqual(commands["plugin_tool"]["mapped_backend_route"], "/plugin/tool")
        self.assertIn("open_asset_in_editor", commands["plugin_tool"]["payload_schema"]["tool_name"])
        self.assertIn("compile_project_and_surface_errors", commands["plugin_tool"]["payload_schema"]["tool_name"])
        self.assertIn("report_compile_result", commands["plugin_tool"]["payload_schema"]["tool_name"])
        execute_schema = commands["execute_editor_action"]["payload_schema"]
        self.assertIn("open_asset", execute_schema["action_type"])
        self.assertIn("compile_project", execute_schema["action_type"])
        self.assertIn("create_module", execute_schema["action_type"])
        self.assertIn("apply_code_patch_bundle_preview", execute_schema["action_type"])

    def test_agent_session_confirm_and_continue_collapses_approve_and_resume(self):
        create_response = self.client.post(
            "/agent-session",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(create_response.status_code, 200)
        task_id = create_response.json()["task_id"]

        continue_response = self.client.post(
            f"/agent-session/{task_id}/confirm-and-continue",
            json={"decision": "approve"},
        )
        self.assertEqual(continue_response.status_code, 200)

        payload = continue_response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["steps"][-7]["tool_name"], "resolve_confirmation")
        self.assertEqual(payload["steps"][-6]["tool_name"], "stage_editor_execution_package")
        self.assertEqual(payload["steps"][-5]["tool_name"], "stage_apply_ready_preview")
        self.assertEqual(payload["steps"][-4]["tool_name"], "stage_validation_commands")
        self.assertEqual(payload["steps"][-3]["tool_name"], "prepare_editor_handoff")
        self.assertEqual(payload["steps"][-2]["tool_name"], "draft_supporting_asset_scaffolds")
        self.assertEqual(payload["steps"][-1]["tool_name"], "summarize_progress")
        self.assertEqual(payload["available_tools"], [])
        self.assertEqual(payload["result"]["next_action"], "apply_in_editor_and_validate")
        self.assertEqual(payload["approved_editor_action"]["action_type"], "apply_code_patch_bundle_preview")
        self.assertEqual(payload["result"]["editor_execution_package"]["goal"], "add sprint input and hook it to the player character")
        self.assertEqual(payload["result"]["apply_ready_preview"]["requires_confirmation"], True)
        self.assertEqual(payload["result"]["apply_ready_preview"]["dry_run_route"], "/code-patch-bundle-apply-dry-run")
        self.assertEqual(payload["result"]["apply_ready_preview"]["final_apply_route"], "/code-patch-bundle-apply")
        self.assertEqual(payload["result"]["apply_ready_preview"]["final_apply_request"]["task_id"], task_id)
        self.assertIsNone(payload["result"]["apply_ready_preview"]["final_apply_request"]["receipt_token"])
        self.assertEqual(payload["result"]["followup_asset_plans"][0]["recommended_name"], "IA_Sprint")
        self.assertEqual(payload["orchestration"]["phase"], "completed")

    def test_agent_session_completes_without_confirmation_for_non_code_goal(self):
        response = self.client.post(
            "/agent-session",
            json={"goal": "explain the player character ownership and linked assets"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertIsNone(payload["pending_confirmation"])
        self.assertEqual([step["tool_name"] for step in payload["steps"][:2]], [
            "inspect_project_context",
            "plan_task",
        ])
        self.assertEqual(payload["available_tools"], [])
        self.assertEqual(payload["orchestration"]["phase"], "completed")
        self.assertEqual(payload["orchestration"]["proposed_plan"][0]["state"], "completed")
        self.assertEqual(payload["steps"][-1]["tool_name"], "summarize_progress")

    def test_agent_session_step_advances_one_tool_at_a_time(self):
        create_response = self.client.post(
            "/agent-session",
            json={"goal": "add sprint input and hook it to the player character", "auto_run": False},
        )
        self.assertEqual(create_response.status_code, 200)
        created_payload = create_response.json()
        task_id = created_payload["task_id"]

        self.assertEqual(created_payload["status"], "running")
        self.assertEqual(created_payload["steps"], [])
        self.assertEqual(created_payload["available_tools"], ["inspect_project_context"])
        self.assertEqual(created_payload["orchestration"]["ranked_candidates"][0]["tool_name"], "inspect_project_context")

        first_step = self.client.post(f"/agent-session/{task_id}/step")
        self.assertEqual(first_step.status_code, 200)
        first_payload = first_step.json()
        self.assertEqual(first_payload["steps"][-1]["tool_name"], "inspect_project_context")
        self.assertEqual(first_payload["available_tools"], ["plan_task"])
        self.assertEqual(first_payload["orchestration"]["ranked_candidates"][0]["tool_name"], "plan_task")

        second_step = self.client.post(f"/agent-session/{task_id}/step")
        self.assertEqual(second_step.status_code, 200)
        second_payload = second_step.json()
        self.assertEqual(second_payload["steps"][-1]["tool_name"], "plan_task")
        self.assertEqual(second_payload["available_tools"], ["search_project"])
        self.assertEqual(second_payload["subtasks"][2]["tool_name"], "search_project")
        self.assertEqual(second_payload["orchestration"]["tool_catalog"][0]["input_schema"]["properties"]["goal"]["type"], "string")
        self.assertEqual(second_payload["subtasks"][7]["tool_name"], "request_confirmation")
        self.assertEqual(second_payload["orchestration"]["ranked_candidates"][0]["tool_name"], "search_project")

    def test_agent_session_registry_planning_keeps_investigation_flow_narrow(self):
        response = self.client.post(
            "/agent-session",
            json={"goal": "explain the player character ownership and linked assets"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        planned_tools = [item["tool_name"] for item in payload["subtasks"]]
        self.assertIn("search_project", planned_tools)
        self.assertIn("analyze_selection", planned_tools)
        self.assertNotIn("request_confirmation", planned_tools)
        self.assertNotIn("draft_code_patch_bundle", planned_tools)
        self.assertIn("search_project", payload["context"]["tool_preferences"]["preferred_tools"])
        self.assertIn("draft_code_patch_bundle", payload["context"]["tool_preferences"]["suppressed_tools"])
        self.assertIn("analyze_selection", payload["context"]["tool_preferences"]["stop_after_tools"])

    def test_planner_preferences_influence_ranked_candidates_for_investigation(self):
        create_response = self.client.post(
            "/agent-session",
            json={"goal": "explain the player character ownership and linked assets", "auto_run": False},
        )
        self.assertEqual(create_response.status_code, 200)
        task_id = create_response.json()["task_id"]

        self.client.post(f"/agent-session/{task_id}/step")
        second_step = self.client.post(f"/agent-session/{task_id}/step")
        self.assertEqual(second_step.status_code, 200)
        payload = second_step.json()

        self.assertEqual(payload["steps"][-1]["tool_name"], "plan_task")
        self.assertEqual(payload["context"]["tool_preferences"]["score_boosts"]["search_project"], 120)
        self.assertEqual(payload["orchestration"]["ranked_candidates"][0]["tool_name"], "search_project")

    def test_planner_gating_requires_search_results_before_read_context(self):
        create_response = self.client.post(
            "/agent-session",
            json={"goal": "add sprint input and hook it to the player character", "auto_run": False},
        )
        self.assertEqual(create_response.status_code, 200)
        task_id = create_response.json()["task_id"]

        self.client.post(f"/agent-session/{task_id}/step")
        second_step = self.client.post(f"/agent-session/{task_id}/step")
        payload = second_step.json()

        ranked_tools = [item["tool_name"] for item in payload["orchestration"]["ranked_candidates"]]
        self.assertIn("search_project", ranked_tools)
        self.assertNotIn("read_file_context", ranked_tools)

    def test_investigation_session_stops_after_analysis_stage(self):
        response = self.client.post(
            "/agent-session",
            json={"goal": "explain the player character ownership and linked assets"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["steps"][-2]["tool_name"], "analyze_selection")
        self.assertEqual(payload["steps"][-1]["tool_name"], "summarize_progress")
        self.assertNotIn("draft_code_patch_bundle", [step["tool_name"] for step in payload["steps"]])

    def test_code_patch_plan_returns_preview_for_input_task(self):
        response = self.client.post(
            "/code-patch-plan",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["task_kind"], "wire_input_binding")
        self.assertEqual(payload["execution_mode"], "plan_only")
        self.assertTrue(payload["target_files"])
        self.assertTrue(payload["proposed_edits"])
        self.assertTrue(any("IA_Sprint" in item["patch_preview"] for item in payload["proposed_edits"]))

    def test_code_patch_plan_supports_target_path_override(self):
        response = self.client.post(
            "/code-patch-plan",
            json={
                "goal": "add sprint input handlers",
                "target_path": "Source/MyGame/Public/Player/MyPlayerCharacter.h",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["target_files"][0]["path"], "Source/MyGame/Public/Player/MyPlayerCharacter.h")

    def test_code_patch_draft_returns_unified_diff_for_header(self):
        response = self.client.post(
            "/code-patch-draft",
            json={
                "goal": "add sprint input and hook it to the player character",
                "target_path": "Source/MyGame/Public/Player/MyPlayerCharacter.h",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["execution_mode"], "preview_only")
        self.assertEqual(payload["target_file"]["path"], "Source/MyGame/Public/Player/MyPlayerCharacter.h")
        self.assertIn("--- Source/MyGame/Public/Player/MyPlayerCharacter.h", payload["unified_diff"])
        self.assertIn("IA_Sprint", payload["unified_diff"])
        self.assertIn("HandleSprintStarted", payload["unified_diff"])
        self.assertTrue(payload["original_content_hash"])
        self.assertEqual(payload["editor_action"]["action_type"], "apply_code_patch_preview")
        self.assertEqual(payload["editor_action"]["arguments"]["target_path"], "Source/MyGame/Public/Player/MyPlayerCharacter.h")
        self.assertEqual(payload["editor_action"]["arguments"]["original_content_hash"], payload["original_content_hash"])
        self.assertIn("+    virtual void SetupPlayerInputComponent(class UInputComponent* PlayerInputComponent) override;", payload["unified_diff"])
        self.assertIn("+    TObjectPtr<class UInputAction> IA_Sprint = nullptr;", payload["unified_diff"])
        self.assertIn("+    void HandleSprintStarted();", payload["unified_diff"])

    def test_code_patch_draft_inserts_input_bindings_into_setup_function(self):
        response = self.client.post(
            "/code-patch-draft",
            json={
                "goal": "add sprint input and hook it to the player character",
                "target_path": "Source/MyGame/Private/Player/MyPlayerCharacter.cpp",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["target_file"]["path"], "Source/MyGame/Private/Player/MyPlayerCharacter.cpp")
        self.assertIn("SetupPlayerInputComponent", payload["unified_diff"])
        self.assertIn('+#include "EnhancedInputComponent.h"', payload["unified_diff"])
        self.assertIn("if (UEnhancedInputComponent* EnhancedInputComponent = Cast<UEnhancedInputComponent>(PlayerInputComponent))", payload["unified_diff"])
        self.assertIn("EnhancedInputComponent->BindAction(IA_Sprint, ETriggerEvent::Started, this, &AMyPlayerCharacter::HandleSprintStarted);", payload["unified_diff"])
        self.assertIn("EnhancedInputComponent->BindAction(IA_Sprint, ETriggerEvent::Completed, this, &AMyPlayerCharacter::HandleSprintCompleted);", payload["unified_diff"])
        self.assertIn("+void AMyPlayerCharacter::HandleSprintStarted()", payload["unified_diff"])
        self.assertIn("+void AMyPlayerCharacter::HandleSprintCompleted()", payload["unified_diff"])

    def test_code_patch_draft_generates_setup_override_when_source_is_missing_it(self):
        analysis = build_sample_analysis()
        source_file = next(item for item in analysis["files"] if item["path"] == "Source/MyGame/Private/Player/MyPlayerCharacter.cpp")
        source_file["content"] = """
                #include "MyPlayerCharacter.h"

                void AMyPlayerCharacter::RefreshAnimationState() {}
                // BP_PlayerCharacter owns the player-facing runtime behavior.
            """
        self.load_analysis(analysis)

        response = self.client.post(
            "/code-patch-draft",
            json={
                "goal": "add sprint input and hook it to the player character",
                "target_path": "Source/MyGame/Private/Player/MyPlayerCharacter.cpp",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertIn("+void AMyPlayerCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)", payload["unified_diff"])
        self.assertIn("+    Super::SetupPlayerInputComponent(PlayerInputComponent);", payload["unified_diff"])
        self.assertIn("EnhancedInputComponent->BindAction(IA_Sprint, ETriggerEvent::Started, this, &AMyPlayerCharacter::HandleSprintStarted);", payload["unified_diff"])
        self.assertIn("+void AMyPlayerCharacter::HandleSprintStarted()", payload["unified_diff"])

    def test_code_patch_draft_requires_scanned_project(self):
        app_main.PROJECT_CACHE["analysis"] = None
        app_main.PROJECT_CACHE["files"] = []
        app_main.PROJECT_CACHE["assets"] = []

        response = self.client.post(
            "/code-patch-draft",
            json={"goal": "add sprint input"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error"], "No project has been scanned yet.")

    def test_code_patch_bundle_draft_returns_header_and_source_diffs(self):
        response = self.client.post(
            "/code-patch-bundle-draft",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["execution_mode"], "preview_only")
        self.assertEqual(len(payload["draft_files"]), 2)
        self.assertIn("IA_Sprint", payload["combined_unified_diff"])
        self.assertIn("HandleSprintCompleted", payload["combined_unified_diff"])
        self.assertEqual(payload["editor_action"]["action_type"], "apply_code_patch_bundle_preview")
        self.assertEqual(len(payload["editor_action"]["arguments"]["files"]), 2)

    def test_code_patch_bundle_apply_dry_run_verifies_staged_preview(self):
        draft_response = self.client.post(
            "/code-patch-bundle-draft",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(draft_response.status_code, 200)
        draft_payload = draft_response.json()

        response = self.client.post(
            "/code-patch-bundle-apply-dry-run",
            json={"files": draft_payload["editor_action"]["arguments"]["files"]},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["execution_mode"], "dry_run")
        self.assertEqual(payload["action_type"], "apply_code_patch_bundle_preview")
        self.assertEqual(payload["verified"], True)
        self.assertEqual(payload["verified_files"][0]["status"], "verified")

    def test_code_patch_bundle_apply_dry_run_reports_stale_hash(self):
        draft_response = self.client.post(
            "/code-patch-bundle-draft",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(draft_response.status_code, 200)
        draft_payload = draft_response.json()
        staged_files = draft_payload["editor_action"]["arguments"]["files"]
        staged_files[0]["original_content_hash"] = "stale-hash"

        response = self.client.post(
            "/code-patch-bundle-apply-dry-run",
            json={"files": staged_files},
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["verified"], False)
        self.assertEqual(payload["verified_files"][0]["status"], "stale")

    def test_code_patch_bundle_apply_requires_verified_dry_run(self):
        draft_response = self.client.post(
            "/code-patch-bundle-draft",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(draft_response.status_code, 200)
        draft_payload = draft_response.json()

        response = self.client.post(
            "/code-patch-bundle-apply",
            json={
                "files": draft_payload["editor_action"]["arguments"]["files"],
                "dry_run_verified": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["error"],
            "Run a clean dry run first and send `dry_run_verified: true` before applying.",
        )

    def test_code_patch_bundle_apply_rejects_invalid_verification_token(self):
        draft_response = self.client.post(
            "/code-patch-bundle-draft",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(draft_response.status_code, 200)
        draft_payload = draft_response.json()

        response = self.client.post(
            "/code-patch-bundle-apply",
            json={
                "files": draft_payload["editor_action"]["arguments"]["files"],
                "dry_run_verified": True,
                "verification_token": "invalid-token",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["error"],
            "The verification token does not match the staged preview payload.",
        )

    def test_code_patch_bundle_apply_dry_run_rejects_invalid_session_approval_token(self):
        session_response = self.client.post(
            "/agent-session",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(session_response.status_code, 200)
        task_id = session_response.json()["task_id"]

        continue_response = self.client.post(
            f"/agent-session/{task_id}/confirm-and-continue",
            json={"decision": "approve"},
        )
        self.assertEqual(continue_response.status_code, 200)
        apply_ready_preview = continue_response.json()["result"]["apply_ready_preview"]

        response = self.client.post(
            "/code-patch-bundle-apply-dry-run",
            json={
                "files": apply_ready_preview["dry_run_request"]["files"],
                "task_id": task_id,
                "approval_token": "invalid-session-token",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["error"],
            "The session approval token does not match the approved agent session.",
        )

    def test_code_patch_bundle_apply_requires_dry_run_receipt_for_session_scoped_apply(self):
        session_response = self.client.post(
            "/agent-session",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(session_response.status_code, 200)
        task_id = session_response.json()["task_id"]

        continue_response = self.client.post(
            f"/agent-session/{task_id}/confirm-and-continue",
            json={"decision": "approve"},
        )
        self.assertEqual(continue_response.status_code, 200)
        apply_ready_preview = continue_response.json()["result"]["apply_ready_preview"]

        response = self.client.post(
            "/code-patch-bundle-apply",
            json=apply_ready_preview["final_apply_request"],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["error"],
            "Session-scoped final apply requests must include the latest dry-run `receipt_token`.",
        )

    def test_code_patch_bundle_apply_accepts_latest_session_dry_run_receipt(self):
        app_main.PROJECT_CACHE["project_path"] = None
        app_main.PROJECT_CACHE["files"] = []
        app_main.PROJECT_CACHE["assets"] = []
        app_main.PROJECT_CACHE["analysis"] = None
        app_main.PROJECT_CACHE["search_index"] = None

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            header_path = project_root / "Source" / "MyGame" / "Public" / "MyPlayerCharacter.h"
            source_path = project_root / "Source" / "MyGame" / "Private" / "MyPlayerCharacter.cpp"
            header_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.parent.mkdir(parents=True, exist_ok=True)
            header_path.write_text(
                """
                UCLASS(Blueprintable)
                class AMyPlayerCharacter : public ACharacter
                {
                    GENERATED_BODY()
                public:
                    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Movement")
                    float MaxSprintSpeed;
                };
                """,
                encoding="utf-8",
            )
            source_path.write_text(
                """
                #include "MyPlayerCharacter.h"
                void AMyPlayerCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
                {
                    Super::SetupPlayerInputComponent(PlayerInputComponent);
                }
                """,
                encoding="utf-8",
            )

            scan_response = self.client.post("/scan-project", json={"project_path": str(project_root)})
            self.assertEqual(scan_response.status_code, 200)

            session_response = self.client.post(
                "/agent-session",
                json={"goal": "add sprint input and hook it to the player character"},
            )
            self.assertEqual(session_response.status_code, 200)
            task_id = session_response.json()["task_id"]

            continue_response = self.client.post(
                f"/agent-session/{task_id}/confirm-and-continue",
                json={"decision": "approve"},
            )
            self.assertEqual(continue_response.status_code, 200)
            apply_ready_preview = continue_response.json()["result"]["apply_ready_preview"]

            dry_run_response = self.client.post(
                "/code-patch-bundle-apply-dry-run",
                json=apply_ready_preview["dry_run_request"],
            )
            self.assertEqual(dry_run_response.status_code, 200)
            dry_run_payload = dry_run_response.json()
            self.assertTrue(dry_run_payload["verified"])
            self.assertEqual(dry_run_payload["dry_run_receipt"]["task_id"], task_id)
            self.assertEqual(
                app_main.AGENT_TASK_CACHE[task_id]["orchestration"]["execution_state"]["current_stage"],
                "dry_run_verified",
            )

            apply_request = dict(apply_ready_preview["final_apply_request"])
            apply_request["receipt_token"] = dry_run_payload["dry_run_receipt"]["receipt_token"]
            apply_response = self.client.post(
                "/code-patch-bundle-apply",
                json=apply_request,
            )
            self.assertEqual(apply_response.status_code, 200)
            self.assertTrue(apply_response.json()["applied"])
            self.assertIsNone(app_main.AGENT_TASK_CACHE[task_id]["artifacts"]["session_dry_run_receipt"])
            self.assertEqual(
                app_main.AGENT_TASK_CACHE[task_id]["orchestration"]["execution_state"]["current_stage"],
                "applied",
            )

    def test_code_patch_bundle_apply_writes_files_after_clean_dry_run(self):
        app_main.PROJECT_CACHE["project_path"] = None
        app_main.PROJECT_CACHE["files"] = []
        app_main.PROJECT_CACHE["assets"] = []
        app_main.PROJECT_CACHE["analysis"] = None
        app_main.PROJECT_CACHE["search_index"] = None

        with TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            header_path = project_root / "Source" / "MyGame" / "Public" / "MyPlayerCharacter.h"
            source_path = project_root / "Source" / "MyGame" / "Private" / "MyPlayerCharacter.cpp"
            header_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.parent.mkdir(parents=True, exist_ok=True)
            header_path.write_text(
                """
                UCLASS(Blueprintable)
                class AMyPlayerCharacter : public ACharacter
                {
                    GENERATED_BODY()
                public:
                    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Movement")
                    float MaxSprintSpeed;
                };
                """,
                encoding="utf-8",
            )
            source_path.write_text(
                """
                #include "MyPlayerCharacter.h"
                void AMyPlayerCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
                {
                    Super::SetupPlayerInputComponent(PlayerInputComponent);
                }
                """,
                encoding="utf-8",
            )

            scan_response = self.client.post("/scan-project", json={"project_path": str(project_root)})
            self.assertEqual(scan_response.status_code, 200)

            draft_response = self.client.post(
                "/code-patch-bundle-draft",
                json={"goal": "add sprint input and hook it to the player character"},
            )
            self.assertEqual(draft_response.status_code, 200)
            draft_payload = draft_response.json()

            dry_run_response = self.client.post(
                "/code-patch-bundle-apply-dry-run",
                json={"files": draft_payload["editor_action"]["arguments"]["files"]},
            )
            self.assertEqual(dry_run_response.status_code, 200)
            self.assertTrue(dry_run_response.json()["verified"])

            apply_response = self.client.post(
                "/code-patch-bundle-apply",
                json={
                    "files": draft_payload["editor_action"]["arguments"]["files"],
                    "dry_run_verified": True,
                },
            )
            self.assertEqual(apply_response.status_code, 200)
            apply_payload = apply_response.json()
            self.assertTrue(apply_payload["applied"])
            self.assertEqual(apply_payload["file_count"], len(draft_payload["editor_action"]["arguments"]["files"]))

            updated_header = header_path.read_text(encoding="utf-8")
            updated_source = source_path.read_text(encoding="utf-8")
            combined_text = f"{updated_header}\n{updated_source}"
            self.assertIn("IA_Sprint", combined_text)
            self.assertIn("HandleSprintStarted", combined_text)

    def test_code_patch_bundle_draft_is_idempotent_after_reapplying_same_preview(self):
        first_response = self.client.post(
            "/code-patch-bundle-draft",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(first_response.status_code, 200)

        first_payload = first_response.json()
        analysis = build_sample_analysis()
        file_by_path = {item["path"]: item for item in analysis["files"]}
        for draft_file in first_payload["draft_files"]:
            file_by_path[draft_file["path"]]["content"] = draft_file["updated_content"]
        self.load_analysis(analysis)

        second_response = self.client.post(
            "/code-patch-bundle-draft",
            json={"goal": "add sprint input and hook it to the player character"},
        )
        self.assertEqual(second_response.status_code, 200)

        second_payload = second_response.json()
        self.assertEqual(second_payload["combined_unified_diff"], "")
        self.assertTrue(any("already exist" in warning for warning in second_payload["warnings"]))
        self.assertTrue(all(item["unified_diff"] == "" for item in second_payload["draft_files"]))


if __name__ == "__main__":
    unittest.main()
