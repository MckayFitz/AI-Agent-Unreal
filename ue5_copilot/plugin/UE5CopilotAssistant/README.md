# UE5 Copilot Assistant Plugin

This is a starter Unreal Editor plugin scaffold for the FastAPI app in this repo.

What it includes:
- Editor module
- Dockable tab under `Window`
- Backend base URL input
- Prompt box
- Deep asset text box
- Output panel
- HTTP `POST` to the backend `/ask` route
- Current editor selection bridge for selected actors or Content Browser assets
- Selection payload `POST` to the backend `/plugin/selection-context` route
- Deep asset analysis payload `POST` to the backend `/asset-deep-analysis` route

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
9. Choose an asset kind, paste exported graph/state text, and use `Deep Analyze Selected Asset` for Phase 2-style asset analysis.

What the backend can already plan today:
- Explain selected assets with references, linked C++ classes, and gameplay role
- Deep analysis for Blueprint, Material, Behavior Tree, Enhanced Input, and AnimBP exports
- Asset scaffolds for Blueprint classes, DataAssets, Input Actions, and Input Mapping Contexts
- Controlled edit plans for DataAssets, Enhanced Input, Blueprints, Materials, and Behavior Trees

What the plugin does not do yet:
- It does not execute asset mutations.
- It does not directly call `/asset-scaffold` or `/asset-edit-plan` yet.
- It does not apply backend-proposed editor actions.

The intended next step is a dry-run and confirmation flow where the backend can suggest an `editor_action`, and the plugin validates and executes it through Unreal editor APIs.

Good next plugin steps:
- Add dedicated buttons for `/asset-details`, `/asset-scaffold`, and `/asset-edit-plan`
- Add right-click actions for explain/find references/analyze system
- Persist backend URL in editor settings
- Add richer selection metadata for Blueprints, components, and folders
- Replace pasted export text with direct graph/state extraction where Unreal APIs allow it
- Add plugin-side dry-run and confirmation UI for future `editor_action` responses
