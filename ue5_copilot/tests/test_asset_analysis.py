import unittest
from pathlib import Path

from app.asset_actions import run_asset_action
from app.file_indexer import infer_asset_type
from app.ue_analysis import analyze_deep_asset, build_asset_details, build_project_analysis, find_matching_assets, infer_deep_asset_kind
from app.main import (
    build_behavior_tree_scaffold,
    build_control_rig_scaffold,
    build_eqs_scaffold,
    build_ik_rig_scaffold,
    build_material_scaffold,
    build_metasound_scaffold,
    build_motion_matching_scaffold,
    build_niagara_scaffold,
    build_pcg_scaffold,
    build_sequencer_scaffold,
    build_state_tree_scaffold,
)


class AssetAnalysisTests(unittest.TestCase):
    def test_asset_action_registry_rejects_unknown_actions(self):
        result = run_asset_action("does_not_exist")
        self.assertIn("error", result)

    def test_infer_asset_type_uses_relative_path_context(self):
        self.assertEqual(
            infer_asset_type(Path("ABP_Player.uasset"), "Content/Characters/Animation/ABP_Player.uasset"),
            "animation_blueprint",
        )
        self.assertEqual(
            infer_asset_type(Path("M_Master.uasset"), "Content/Art/Materials/M_Master.uasset"),
            "material",
        )
        self.assertEqual(
            infer_asset_type(Path("EnemyCombat.uasset"), "Content/DataAssets/EnemyCombat.uasset"),
            "data_asset",
        )
        self.assertEqual(
            infer_asset_type(Path("MS_WeaponFire.uasset"), "Content/Audio/MetaSounds/MS_WeaponFire.uasset"),
            "metasound",
        )

    def test_find_matching_assets_supports_relative_paths(self):
        assets = [
            {
                "name": "ABP_Player.uasset",
                "path": "C:/Project/Content/Characters/Animation/ABP_Player.uasset",
                "relative_path": "Content/Characters/Animation/ABP_Player.uasset",
                "asset_type": "animation_blueprint",
                "family": "animation",
            }
        ]

        matches = find_matching_assets(assets, "Content/Characters/Animation/ABP_Player.uasset")
        self.assertTrue(matches)
        self.assertGreaterEqual(matches[0]["match_score"], 14)

    def test_blueprint_asset_details_rank_cpp_owner_from_tokens_and_hooks(self):
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
            }
        ]

        analysis = build_project_analysis(files, assets)
        details = build_asset_details(
            selection="BP_PlayerCharacter",
            asset=analysis["assets"][0],
            files=analysis["files"],
            assets=analysis["assets"],
            blueprint_links=analysis["blueprint_links"],
        )

        self.assertEqual(details["linked_cpp_classes"]["primary_owner"], "AMyPlayerCharacter")
        self.assertIn("RefreshAnimationState", analysis["blueprint_links"][0]["exposed_functions"])

    def test_asset_action_registry_returns_asset_details(self):
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
                    };
                """,
            }
        ]
        assets = [
            {
                "name": "BP_PlayerCharacter.uasset",
                "path": "C:/Project/Content/Blueprints/BP_PlayerCharacter.uasset",
                "relative_path": "Content/Blueprints/BP_PlayerCharacter.uasset",
                "extension": ".uasset",
                "asset_type": "blueprint",
                "likely_blueprint": True,
            }
        ]
        analysis = build_project_analysis(files, assets)

        result = run_asset_action(
            "asset_details",
            analysis=analysis,
            selection="BP_PlayerCharacter",
        )

        self.assertEqual(result["resolved_asset_name"], "BP_PlayerCharacter")
        self.assertEqual(result["asset"]["family"], "blueprint")

    def test_asset_edit_plan_registry_routes_to_blueprint_plan(self):
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
                    };
                """,
            }
        ]
        assets = [
            {
                "name": "BP_PlayerCharacter.uasset",
                "path": "C:/Project/Content/Blueprints/BP_PlayerCharacter.uasset",
                "relative_path": "Content/Blueprints/BP_PlayerCharacter.uasset",
                "extension": ".uasset",
                "asset_type": "blueprint",
                "likely_blueprint": True,
            }
        ]
        analysis = build_project_analysis(files, assets)

        def rename_check(_: str) -> bool:
            return False

        def function_check(_: str) -> bool:
            return False

        def unexpected(*args, **kwargs):
            raise AssertionError("Unexpected edit plan builder called")

        def blueprint_variable_plan(asset, change_request, details):
            return {
                "asset_kind": "blueprint_variable_edit",
                "asset_name": asset["name"],
                "change_request": change_request,
                "linked_cpp_owner": details["linked_cpp_classes"]["primary_owner"],
            }

        result = run_asset_action(
            "asset_edit_plan",
            analysis=analysis,
            selection="BP_PlayerCharacter",
            change_request="add a sprinting bool variable",
            looks_like_rename_request=rename_check,
            looks_like_function_request=function_check,
            build_asset_rename_edit_plan=unexpected,
            build_data_asset_edit_plan=unexpected,
            build_enhanced_input_edit_plan=unexpected,
            build_behavior_tree_edit_plan=unexpected,
            build_material_edit_plan=unexpected,
            build_animbp_edit_plan=unexpected,
            build_state_tree_edit_plan=unexpected,
            build_control_rig_edit_plan=unexpected,
            build_niagara_edit_plan=unexpected,
            build_eqs_edit_plan=unexpected,
            build_sequencer_edit_plan=unexpected,
            build_metasound_edit_plan=unexpected,
            build_pcg_edit_plan=unexpected,
            build_motion_matching_edit_plan=unexpected,
            build_ik_rig_edit_plan=unexpected,
            build_blueprint_function_edit_plan=unexpected,
            build_blueprint_variable_edit_plan=blueprint_variable_plan,
        )

        self.assertEqual(result["asset_kind"], "blueprint_variable_edit")
        self.assertEqual(result["asset_name"], "BP_PlayerCharacter.uasset")

    def test_plugin_specialized_family_registry_detects_behavior_tree_family(self):
        files = []
        assets = [
            {
                "name": "BT_EnemyCombat.uasset",
                "path": "C:/Project/Content/AI/BT_EnemyCombat.uasset",
                "relative_path": "Content/AI/BT_EnemyCombat.uasset",
                "extension": ".uasset",
                "asset_type": "behavior_tree",
                "family": "behavior_tree",
            }
        ]
        analysis = {
            "files": files,
            "assets": assets,
            "blueprint_links": [],
        }

        result = run_asset_action(
            "plugin_specialized_family",
            analysis=analysis,
            selection_name="BT_EnemyCombat",
            class_name="",
            asset_path="Content/AI/BT_EnemyCombat.uasset",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["family_key"], "behavior_trees")

    def test_material_scaffold_builder_returns_material_plan(self):
        result = build_material_scaffold("MasterSurface", "Base surface for props")
        self.assertEqual(result["asset_kind"], "material")
        self.assertEqual(result["recommended_asset_name"], "M_MasterSurface")
        self.assertIn("Content/Materials", result["recommended_asset_path"])

    def test_behavior_tree_scaffold_builder_returns_behavior_tree_plan(self):
        result = build_behavior_tree_scaffold("EnemyCombat", "Combat AI flow")
        self.assertEqual(result["asset_kind"], "behavior_tree")
        self.assertEqual(result["recommended_asset_name"], "BT_EnemyCombat")
        self.assertIn("Behavior Tree", result["title"])

    def test_specialized_family_registry_supports_metasounds(self):
        analysis = {
            "files": [],
            "assets": [
                {
                    "name": "MS_WeaponFire.uasset",
                    "path": "C:/Project/Content/Audio/MetaSounds/MS_WeaponFire.uasset",
                    "relative_path": "Content/Audio/MetaSounds/MS_WeaponFire.uasset",
                    "extension": ".uasset",
                    "asset_type": "metasound",
                    "family": "metasound",
                }
            ],
            "blueprint_links": [],
        }

        result = run_asset_action(
            "specialized_asset_family",
            analysis=analysis,
            family="metasounds",
        )

        self.assertEqual(result["family_key"], "metasounds")
        self.assertEqual(result["asset_count"], 1)

    def test_metasound_deep_analysis_detects_and_summarizes(self):
        inferred = infer_deep_asset_kind(
            asset=None,
            selection_name="MS_WeaponFire",
            asset_path="Content/Audio/MetaSounds/MS_WeaponFire.uasset",
            asset_kind="auto",
        )
        self.assertEqual(inferred, "metasound")

        result = analyze_deep_asset(
            asset_kind="metasound",
            exported_text="""
                Graph Input: Pitch
                Trigger On Play
                Wave Player: RifleShot
                Envelope Follower
                Graph Output: Audio
            """,
            selection_name="MS_WeaponFire",
        )

        self.assertEqual(result["asset_kind"], "metasound")
        self.assertIn("MetaSound", result["summary"])
        self.assertTrue(result["key_elements"])

    def test_pcg_deep_analysis_detects_and_summarizes(self):
        inferred = infer_deep_asset_kind(
            asset=None,
            selection_name="PCG_ForestScatter",
            asset_path="Content/World/PCG/PCG_ForestScatter.uasset",
            asset_kind="auto",
        )
        self.assertEqual(inferred, "pcg")

        result = analyze_deep_asset(
            asset_kind="pcg",
            exported_text="""
                Graph Input: Landscape Surface
                Sample Points
                Density Filter
                Spawn Static Mesh PineTree
                Graph Output: Generated Instances
            """,
            selection_name="PCG_ForestScatter",
        )

        self.assertEqual(result["asset_kind"], "pcg")
        self.assertIn("PCG", result["summary"])
        self.assertTrue(result["key_elements"])

    def test_motion_matching_deep_analysis_detects_and_summarizes(self):
        inferred = infer_deep_asset_kind(
            asset=None,
            selection_name="MM_PlayerLocomotion",
            asset_path="Content/Animation/MotionMatching/MM_PlayerLocomotion.uasset",
            asset_kind="auto",
        )
        self.assertEqual(inferred, "motion_matching")

        result = analyze_deep_asset(
            asset_kind="motion_matching",
            exported_text="""
                Pose Search Database: PlayerLocomotionDB
                Trajectory Channel
                Query Schema
                Chooser Table
                Cost Breakdown
            """,
            selection_name="MM_PlayerLocomotion",
        )

        self.assertEqual(result["asset_kind"], "motion_matching")
        self.assertIn("Motion Matching", result["summary"])
        self.assertTrue(result["key_elements"])

    def test_state_tree_deep_analysis_detects_and_summarizes(self):
        inferred = infer_deep_asset_kind(
            asset=None,
            selection_name="ST_EnemyDecision",
            asset_path="Content/AI/StateTrees/ST_EnemyDecision.uasset",
            asset_kind="auto",
        )
        self.assertEqual(inferred, "state_tree")

        result = analyze_deep_asset(
            asset_kind="state_tree",
            exported_text="""
                State: Idle
                Transition: HasTarget
                Evaluator: SenseTarget
                Task: MoveToCover
            """,
            selection_name="ST_EnemyDecision",
        )

        self.assertEqual(result["asset_kind"], "state_tree")
        self.assertIn("StateTree", result["summary"])
        self.assertTrue(result["key_elements"])

    def test_control_rig_deep_analysis_detects_and_summarizes(self):
        inferred = infer_deep_asset_kind(
            asset=None,
            selection_name="CR_PlayerUpperBody",
            asset_path="Content/Animation/Rigs/CR_PlayerUpperBody.uasset",
            asset_kind="auto",
        )
        self.assertEqual(inferred, "control_rig")

        result = analyze_deep_asset(
            asset_kind="control_rig",
            exported_text="""
                Control: HandIK
                Bone: hand_r
                Forward Solve
                Hierarchy
            """,
            selection_name="CR_PlayerUpperBody",
        )

        self.assertEqual(result["asset_kind"], "control_rig")
        self.assertIn("Control Rig", result["summary"])
        self.assertTrue(result["key_elements"])

    def test_niagara_deep_analysis_detects_and_summarizes(self):
        inferred = infer_deep_asset_kind(
            asset=None,
            selection_name="NS_ImpactDust",
            asset_path="Content/VFX/NS_ImpactDust.uasset",
            asset_kind="auto",
        )
        self.assertEqual(inferred, "niagara")

        result = analyze_deep_asset(
            asset_kind="niagara",
            exported_text="""
                System: ImpactDust
                Emitter: DustBurst
                Spawn Burst Instantaneous
                Update Particle Size
                Renderer: Sprite
            """,
            selection_name="NS_ImpactDust",
        )

        self.assertEqual(result["asset_kind"], "niagara")
        self.assertIn("Niagara", result["summary"])
        self.assertTrue(result["key_elements"])

    def test_eqs_deep_analysis_detects_and_summarizes(self):
        inferred = infer_deep_asset_kind(
            asset=None,
            selection_name="EQS_FindCover",
            asset_path="Content/AI/Queries/EQS_FindCover.uasset",
            asset_kind="auto",
        )
        self.assertEqual(inferred, "eqs")

        result = analyze_deep_asset(
            asset_kind="eqs",
            exported_text="""
                Generator: Points Around Querier
                Test: Distance
                Test: Pathfinding
                Context: Querier
            """,
            selection_name="EQS_FindCover",
        )

        self.assertEqual(result["asset_kind"], "eqs")
        self.assertIn("EQS", result["summary"])
        self.assertTrue(result["key_elements"])

    def test_sequencer_deep_analysis_detects_and_summarizes(self):
        inferred = infer_deep_asset_kind(
            asset=None,
            selection_name="LS_Intro",
            asset_path="Content/Cinematics/LS_Intro.uasset",
            asset_kind="auto",
        )
        self.assertEqual(inferred, "sequencer")

        result = analyze_deep_asset(
            asset_kind="sequencer",
            exported_text="""
                Track: Camera Cut
                Binding: CineCameraActor
                Event Track
                Key: 1.0s
            """,
            selection_name="LS_Intro",
        )

        self.assertEqual(result["asset_kind"], "sequencer")
        self.assertIn("Sequencer", result["summary"])
        self.assertTrue(result["key_elements"])

    def test_ik_rig_deep_analysis_detects_and_summarizes(self):
        inferred = infer_deep_asset_kind(
            asset=None,
            selection_name="IKR_PlayerRetarget",
            asset_path="Content/Animation/IK/IKR_PlayerRetarget.uasset",
            asset_kind="auto",
        )
        self.assertEqual(inferred, "ik_rig")

        result = analyze_deep_asset(
            asset_kind="ik_rig",
            exported_text="""
                Chain: LeftArm
                Goal: LeftHandGoal
                Solver: FullBodyIK
                Retarget Pose
            """,
            selection_name="IKR_PlayerRetarget",
        )

        self.assertEqual(result["asset_kind"], "ik_rig")
        self.assertIn("IK Rig", result["summary"])
        self.assertTrue(result["key_elements"])

    def test_specialized_scaffold_builders_return_recommended_names(self):
        self.assertEqual(build_state_tree_scaffold("EnemyDecision")["recommended_asset_name"], "ST_EnemyDecision")
        self.assertEqual(build_control_rig_scaffold("PlayerUpperBody")["recommended_asset_name"], "CR_PlayerUpperBody")
        self.assertEqual(build_niagara_scaffold("ImpactDust")["recommended_asset_name"], "NS_ImpactDust")
        self.assertEqual(build_eqs_scaffold("FindCover")["recommended_asset_name"], "EQS_FindCover")
        self.assertEqual(build_sequencer_scaffold("Intro")["recommended_asset_name"], "LS_Intro")
        self.assertEqual(build_metasound_scaffold("WeaponFire")["recommended_asset_name"], "MS_WeaponFire")
        self.assertEqual(build_pcg_scaffold("ForestScatter")["recommended_asset_name"], "PCG_ForestScatter")
        self.assertEqual(build_motion_matching_scaffold("PlayerLocomotion")["recommended_asset_name"], "MM_PlayerLocomotion")
        self.assertEqual(build_ik_rig_scaffold("PlayerRetarget")["recommended_asset_name"], "IKR_PlayerRetarget")


if __name__ == "__main__":
    unittest.main()
