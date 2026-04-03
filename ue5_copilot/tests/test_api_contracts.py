import unittest

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
        self.assertEqual([step["tool_name"] for step in payload["steps"][:4]], [
            "inspect_project_context",
            "plan_task",
            "draft_code_patch_bundle",
            "request_confirmation",
        ])
        self.assertEqual(payload["available_tools"], ["confirm_agent_step"])
        self.assertEqual(payload["pending_confirmation"]["editor_action"]["action_type"], "apply_code_patch_bundle_preview")
        self.assertIn("Source/MyGame/Public/Player/MyPlayerCharacter.h", payload["pending_confirmation"]["target_paths"])

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
        self.assertEqual(resumed_payload["steps"][-3]["tool_name"], "prepare_editor_handoff")
        self.assertEqual(resumed_payload["steps"][-2]["tool_name"], "plan_supporting_assets")
        self.assertEqual(resumed_payload["steps"][-1]["tool_name"], "draft_supporting_asset_scaffolds")
        self.assertEqual(resumed_payload["available_tools"], [])
        self.assertEqual(resumed_payload["result"]["next_action"], "apply_in_editor_and_validate")
        self.assertEqual(resumed_payload["result"]["followup_asset_plans"][0]["recommended_name"], "IA_Sprint")
        self.assertEqual(resumed_payload["result"]["followup_asset_plans"][1]["recommended_name"], "IMC_PlayerDefault")
        self.assertEqual(resumed_payload["result"]["supporting_asset_scaffolds"][0]["asset_kind"], "input_action")
        self.assertEqual(
            resumed_payload["result"]["supporting_asset_scaffolds"][0]["editor_action"]["action_type"],
            "create_asset",
        )
        self.assertEqual(
            resumed_payload["result"]["supporting_asset_scaffolds"][1]["editor_action"]["arguments"]["package_path"],
            "/Game/Input/Contexts",
        )

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
