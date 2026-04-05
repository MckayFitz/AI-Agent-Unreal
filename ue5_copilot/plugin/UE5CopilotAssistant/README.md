# FitzAI Plugin

This is a starter Unreal Editor plugin scaffold for the FastAPI app in this repo.

What it includes:
- Editor module
- Dockable tab under `Window`
- Content Browser right-click actions for selected assets
- Backend base URL input with per-project persistence
- Prompt box
- Broad task-planning button for multi-step goals
- Live agent-task session controls for start, refresh, approval, rejection, and resume
- Automatic live agent-session capture when a broad `/plugin/chat` request escalates into workflow mode
- Asset scaffold planner inputs
- Deep asset text box
- Output panel
- Dedicated agent session panel for live task state, next action, and pending confirmations
- Dedicated code diff preview panel for narrow C++ draft responses
- Editor action preview panel
- Pending bundle file picker plus optional single-file apply control for previewed code patch bundles
- HTTP `POST` to the backend `/plugin/chat` route for normal chat, asset help, and auto-escalated agent workflows
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
5. Open `Window -> FitzAI`.
6. Make sure the FastAPI backend is running and the project has already been scanned.
7. Use `Send` for the normal smart path: direct chat for simple questions, or automatic escalation into a live backend agent session for broader work. Use `Force Agent Workflow` when you want to skip straight to staged workflow mode, or `Draft Code Diff` for a narrow C++ diff preview.
8. When the agent session pauses for confirmation, use `Approve And Continue` or `Reject Agent Step` for the current pending action.
9. After approval, the plugin keeps the approved editor action preview alive so you can still apply it through the normal editor-action controls.
10. The plugin now uses the backend `confirm-and-continue` flow for approval, so follow-up planning continues in one round trip. `Refresh Agent Status` and `Resume Agent Task` are still available when you want manual control.
11. Watch the dedicated `Agent Session` panel for the current task id, status, next action, previewed action, recent step, and any pending confirmation summary.
12. When drafting a code diff, optionally fill in the code target path box to point the preview at a specific `.h` or `.cpp` file.
13. When a previewed code patch bundle is pending, the plugin will populate a dropdown of remaining bundle files and auto-select the first one for you.
14. Use `Apply Selected Code File` to execute the selected bundle file while leaving the rest pending. You can still type an override path manually if needed.
15. Use `Analyze Current Selection` after selecting an actor in the level or an asset in the Content Browser.
16. Use `Explain Selected Asset` to inspect the current asset with references, inferred owners, and gameplay role.
17. Write a requested change in the prompt box and use `Plan Asset Change` for a safe asset-specific edit plan.
18. Choose an asset kind, paste exported graph/state text, and use `Deep Analyze Selected Asset` for Phase 2-style asset analysis.
19. You can also right-click a Content Browser asset and use the `FitzAI` entries to inspect it or plan a change.

What the backend can already plan today:
- Structured multi-step task plans through `/agent-task` for natural-language goals that may span code, assets, and validation
- Live multi-step agent sessions through `/agent-session`, including confirmation and resume endpoints
- Structured code patch plans through `/code-patch-plan` for narrow C++ tasks that need file targets and patch previews before edits
- Preview-only code diff bundles through `/code-patch-bundle-draft` for reviewing a small multi-file unified diff set before apply
- Explain selected assets with references, linked C++ classes, and gameplay role
- Deep analysis for Blueprint, Material, Behavior Tree, Enhanced Input, StateTree, Control Rig, Niagara, EQS, Sequencer, MetaSound, PCG, Motion Matching, IK Rig, DataAsset, and AnimBP exports
- Asset scaffolds for Blueprint classes, AnimBPs, DataAssets, Materials, Behavior Trees, Input Actions, Input Mapping Contexts, StateTrees, Control Rig, Niagara, EQS, Sequencer, MetaSounds, PCG, Motion Matching, and IK Rig
- Controlled edit plans for DataAssets, Enhanced Input, Blueprints, Materials, Behavior Trees, AnimBPs, StateTrees, Control Rig, Niagara, EQS, Sequencer, MetaSounds, PCG, Motion Matching, and IK Rig

What that means in practice:
- The backend is now broad enough to act as the planning and analysis layer for most of the asset families shown in the project UI.
- The current remaining gap is mostly Unreal-side execution and extraction, not backend family coverage.

What the plugin does not do yet:
- It does not execute general asset mutations yet.
- It only applies a narrow set of editor actions today: `rename_asset`, Blueprint-class `create_asset`, `data_asset` `create_asset`, `input_action` `create_asset`, `input_mapping_context` `create_asset`, `material_instance` `create_asset`, previewed small-bundle `.h` and `.cpp` code patch actions, and narrow `tweak_material_parameter` updates for selected Material Instances. Those parameter tweaks currently support scalar, vector, and texture values when the backend can infer a concrete value. Other backend-proposed editor actions are still preview-only.
- Deep asset analysis is still best when you paste/export graph or state text; when you do not, the plugin now falls back to reflected selected-asset properties instead of sending an empty request.
- Most editor action previews are informational only right now and do not validate or apply anything yet.

Current execution status:
- The plugin now includes the first confirmation-and-apply path for `rename_asset`.
- It also includes confirmation-and-apply paths for scaffolded Blueprint-class, Data Asset, Input Action, Input Mapping Context, and Material Instance `create_asset` actions.
- It now includes a confirmation-and-apply path for narrow previewed code diff bundles that overwrite a small set of `.h` and `.cpp` files inside the current Unreal project.
  Those code patch applies refuse to run if any target file changed after the diff bundle was drafted.
  You can also apply one file from a previewed bundle at a time by choosing it from the pending bundle file picker or replacing the path manually.
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
