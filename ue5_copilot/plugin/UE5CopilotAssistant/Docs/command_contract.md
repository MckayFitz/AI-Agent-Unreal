# UE5 Copilot Safe Command Contract

This document explains the near-term command contract between the Unreal plugin and the FastAPI backend. The machine-readable schema lives in [command_contract.json](/C:/Users/mckay/OneDrive/Documents/GitHub/AI-Agent-Unreal/ue5_copilot/plugin/UE5CopilotAssistant/Docs/command_contract.json).

## Current state

Today the plugin already sends:
- tool catalog requests
- selection context requests
- deep asset analysis requests
- plugin chat requests that can answer directly or escalate into a live agent session
- scaffold requests for create-ready asset plans

The backend also supports plan-oriented routes for:
- asset scaffolds
- asset edit plans

Current backend family coverage now includes:
- `Blueprints`
- `AnimBPs`
- `Materials`
- `Material Instances`
- `Behavior Trees`
- `Enhanced Input`
- `DataAssets`
- `StateTrees`
- `Control Rig`
- `Niagara`
- `EQS`
- `Sequencer`
- `MetaSounds`
- `PCG`
- `Motion Matching`
- `IK Rig`

Those newer flows began as web-app-first and plan-only, but the plugin now executes a narrow safe subset of editor actions after preview and confirmation.

The backend now also exposes a richer Unreal-oriented tool catalog so the plugin can understand the difference between:
- backend orchestration steps
- currently implemented Unreal-facing tools
- planned editor capabilities that still need native plugin handlers

## Contract shape

1. The plugin sends a `plugin_request` envelope.
It includes a command name, request id, current selection metadata, and a command-specific payload.

2. The backend returns a `backend_response` envelope.
It includes a status, user-facing message, structured payload, and an optional `editor_action`.

3. The plugin decides whether to execute the `editor_action`.
The backend can propose actions, but the plugin is always the final safety gate.

## Execution model

Phase A: `plan_only`
- Backend returns structured plans only.
- Plugin or web UI displays the plan and does not mutate the project.

Phase B: `dry_run`
- Backend can return an `editor_action` with `dry_run=true`.
- Plugin validates asset existence, asset class, and current selection match.
- Plugin previews the exact action before mutation.

Phase C: confirmed execution
- Plugin shows a confirmation UI.
- Plugin executes the action through Unreal editor APIs.
- Plugin reports success or failure back to the user.

## Initial safe action candidates

- `rename_asset`
- `create_asset`
- `add_input_action`
- `create_material_instance`
- `add_blueprint_variable`
- `add_blueprint_function_stub`
- `tweak_material_parameter`
- `modify_behavior_tree`
- `modify_state_tree`
- `modify_control_rig`
- `modify_niagara_system`
- `modify_eqs_query`
- `modify_level_sequence`
- `modify_metasound`
- `modify_pcg_graph`
- `modify_motion_matching_asset`
- `modify_ik_rig`

## Current route expectations

The backend currently exposes these planning and analysis routes for plugin use:
- `/agent-tools`
- `/plugin/tool`
- `/plugin/chat`
- `/plugin/selection-context`
- `/plugin/asset-details`
- `/plugin/asset-edit-plan`
- `/asset-scaffold`
- `/asset-deep-analysis`
- `/agent-session`
- `/agent-session/{task_id}/status`
- `/agent-session/{task_id}/confirm-and-continue`
- `/agent-session/{task_id}/confirm`
- `/agent-session/{task_id}/resume`

The backend can already return scaffold, inspection, and edit-plan payloads for the supported asset families listed above. Plugin-side mutation and confirmation UX is still the next phase.

`/plugin/chat` is now the broad front door for the plugin. It can still return a direct answer or a single asset plan, but it can also return a live `agent_session` payload for multi-step goals that span project context, code drafts, confirmation, and follow-up asset work.

`/agent-tools` is the capability-discovery route. It returns:
- orchestration tools such as planning, search, confirmation, handoff, and reporting
- Unreal-facing tools such as selection reads, asset metadata inspection, graph extraction, reference search, asset scaffolding, safe asset edit planning, and preview-only code bundle planning
- confirmation policy metadata so the plugin knows which steps must stay previewed or user-approved

`/plugin/tool` is the normalized tool-dispatch route. It lets the plugin request one concrete capability by `tool_name` and receive a structured response envelope with:
- `status`
- `message`
- `payload`
- optional `editor_action` when the tool produced a safe previewable mutation

The first plugin-native editor action now wired through that route is:
- `open_asset_in_editor`, which returns an `open_asset` editor action the plugin can execute through Unreal's asset editor subsystem
- `compile_project_and_surface_errors`, which returns a `compile_project` editor action the plugin executes in the background and reports back into the assistant panel

After compile finishes, the plugin now posts `report_compile_result` back through `/plugin/tool` so the backend can summarize the failure, point at likely files, and suggest the next fix step.

For approval-driven workflows, `/agent-session/{task_id}/confirm-and-continue` is now the preferred path. It records approval and immediately continues backend-side follow-up planning in one round trip. The separate `/confirm` and `/resume` routes still exist for manual or advanced control flows.

The plugin currently executes these safe editor actions:
- `rename_asset`
- `create_asset` for `blueprint_class`
- `create_asset` for `data_asset`
- `create_asset` for `input_action`
- `create_asset` for `input_mapping_context`
- `create_asset` for `material_instance`
- `tweak_material_parameter` for selected `material_instance` assets when the backend can infer a concrete scalar or vector value

The expanded near-term Unreal tool surface is:
- read current selection and resolve likely code/asset owners
- inspect asset or Blueprint metadata
- extract Blueprint, graph, or state text into structured analysis
- search project references and symbols
- scan project context and rebuild search state
- create scaffold-ready asset plans
- create preview-only multi-file code bundles
- apply safe editor edits only after confirmation and dry-run validation

Planned plugin-native tools after that are:
- open assets directly in the editor
- create native C++ classes, plugins, and modules
- run compile/build validation and surface errors back into the agent loop

## Example flow

1. User selects `BT_EnemyCombat` in the Content Browser.
2. Plugin sends `asset_edit_plan` with the current selection and a request like `add a patrol branch when the player is lost`.
3. Backend returns `plan_only` plus structured guidance and may later include a proposed `editor_action` such as `modify_behavior_tree`.
4. Plugin checks that the selected asset is still `BT_EnemyCombat`.
5. Plugin shows a dry-run preview.
6. Plugin applies the change only after explicit confirmation.

## Rules for implementation

- Never mutate `.uasset` binaries directly on disk.
- Resolve all asset writes through Unreal editor APIs and asset tools.
- Require explicit confirmation before mutation.
- Prefer the smallest possible mutation that satisfies the request.
- Reject stale actions when the current editor selection no longer matches the planned target.
- Keep request and response payloads structured so the UI can render plans without guessing.
