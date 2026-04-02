# UE5 Copilot Assistant Plugin

This is a starter Unreal Editor plugin scaffold for the FastAPI app in this repo.

What it includes:
- Editor module
- Dockable tab under `Window`
- Content Browser right-click actions for selected assets
- Backend base URL input with per-project persistence
- Prompt box
- Asset scaffold planner inputs
- Deep asset text box
- Output panel
- Editor action preview panel
- HTTP `POST` to the backend `/ask` route
- Current editor selection bridge for selected actors or Content Browser assets
- Selection payload `POST` to the backend `/plugin/selection-context` route
- Selected asset inspector payload `POST` to the backend `/plugin/asset-details` route
- Selected asset edit-plan payload `POST` to the backend `/plugin/asset-edit-plan` route
- Asset scaffold payload `POST` to the backend `/asset-scaffold` route
- Deep asset analysis payload `POST` to the backend `/asset-deep-analysis` route
- Reflected deep-analysis fallback synthesized from the current selected asset's class and interesting properties when no graph/state export text is pasted
- Structured response formatting for scaffold plans, edit plans, and deep-analysis summaries
- Read-only preview output for future backend `editor_action` dry runs
- Confirmation buttons for acting on previewed editor actions

Current plugin/backend contract docs:
- Human-readable contract: [Docs/command_contract.md](/C:/Users/mckay/OneDrive/Documents/GitHub/AI-Agent-Unreal/ue5_copilot/plugin/UE5CopilotAssistant/Docs/command_contract.md)
- Machine-readable schema: [Docs/command_contract.json](/C:/Users/mckay/OneDrive/Documents/GitHub/AI-Agent-Unreal/ue5_copilot/plugin/UE5CopilotAssistant/Docs/command_contract.json)

How to try it:
1. Copy `plugin/UE5CopilotAssistant` into your Unreal project's `Plugins` folder.
2. Regenerate project files if needed.
3. Build the editor target.
4. Enable the plugin in Unreal.
5. Open `Window -> UE5 Copilot`.
6. Make sure the FastAPI backend is running and the project has already been scanned.
7. Use `Ask Backend` for free-form questions.
8. Use `Analyze Current Selection` after selecting an actor in the level or an asset in the Content Browser.
9. Use `Explain Selected Asset` to inspect the current asset with references, inferred owners, and gameplay role.
10. Write a requested change in the prompt box and use `Plan Asset Change` for a safe asset-specific edit plan.
11. Choose an asset kind, paste exported graph/state text, and use `Deep Analyze Selected Asset` for Phase 2-style asset analysis.
12. You can also right-click a Content Browser asset and use the `UE5 Copilot` entries to inspect it or plan a change.

What the backend can already plan today:
- Explain selected assets with references, linked C++ classes, and gameplay role
- Deep analysis for Blueprint, Material, Behavior Tree, Enhanced Input, StateTree, Control Rig, Niagara, EQS, Sequencer, MetaSound, PCG, Motion Matching, IK Rig, DataAsset, and AnimBP exports
- Asset scaffolds for Blueprint classes, AnimBPs, DataAssets, Materials, Behavior Trees, Input Actions, Input Mapping Contexts, StateTrees, Control Rig, Niagara, EQS, Sequencer, MetaSounds, PCG, Motion Matching, and IK Rig
- Controlled edit plans for DataAssets, Enhanced Input, Blueprints, Materials, Behavior Trees, AnimBPs, StateTrees, Control Rig, Niagara, EQS, Sequencer, MetaSounds, PCG, Motion Matching, and IK Rig

What that means in practice:
- The backend is now broad enough to act as the planning and analysis layer for most of the asset families shown in the project UI.
- The current remaining gap is mostly Unreal-side execution and extraction, not backend family coverage.

What the plugin does not do yet:
- It does not execute general asset mutations yet.
- It only applies a narrow set of editor actions today: `rename_asset`, Blueprint-class `create_asset`, `input_action` `create_asset`, `input_mapping_context` `create_asset`, `material_instance` `create_asset`, and narrow `tweak_material_parameter` updates for selected Material Instances. Those parameter tweaks currently support scalar, vector, and texture values when the backend can infer a concrete value. Other backend-proposed editor actions are still preview-only.
- Deep asset analysis is still best when you paste/export graph or state text; when you do not, the plugin now falls back to reflected selected-asset properties instead of sending an empty request.
- Most editor action previews are informational only right now and do not validate or apply anything yet.

Current execution status:
- The plugin now includes the first confirmation-and-apply path for `rename_asset`.
- It also includes confirmation-and-apply paths for scaffolded Blueprint-class, Input Action, Input Mapping Context, and Material Instance `create_asset` actions.
- It now includes a confirmation-and-apply path for narrow Material Instance scalar/vector parameter tweaks when the backend can infer a concrete value.
- Other `editor_action` types are still preview-only until dedicated validation and execution handlers are added.

The intended next step is a dry-run and confirmation flow where the backend can suggest an `editor_action`, and the plugin validates and executes it through Unreal editor APIs.

Good next plugin steps:
- Add right-click actions for find references and analyze system
- Persist backend URL in editor settings
- Add richer selection metadata for Blueprints, components, and folders
- Replace pasted export text with direct graph/state extraction where Unreal APIs allow it
- Add plugin-side dry-run and confirmation UI for future `editor_action` responses
- Add family-specific execution handlers for the safest first mutations, starting with asset create/rename and narrow value/parameter edits
