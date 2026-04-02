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
        app_main.PROJECT_CACHE["project_path"] = "C:/Project"
        app_main.PROJECT_CACHE["files"] = analysis["files"]
        app_main.PROJECT_CACHE["assets"] = analysis["assets"]
        app_main.PROJECT_CACHE["analysis"] = analysis
        app_main.PROJECT_CACHE["conversation_history"] = []
        app_main.PROJECT_CACHE["current_focus"] = None
        app_main.PROJECT_CACHE["search_index"] = build_search_index(analysis["files"])

    def tearDown(self):
        app_main.PROJECT_CACHE.clear()
        app_main.PROJECT_CACHE.update(self.previous_cache)

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


if __name__ == "__main__":
    unittest.main()
