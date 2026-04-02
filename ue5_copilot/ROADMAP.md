# UE5 Copilot Short Roadmap

## Goal

Move the project from a strong analysis/planning prototype into a safer end-to-end Unreal workflow assistant.

## Next 2 Weeks

### Week 1

1. Stabilize the plugin/backend contract
   - Add route-level tests for the plugin-facing FastAPI endpoints.
   - Lock down expected response shapes for selection context, asset details, asset edit plans, and deep analysis.
   - Document the current supported editor actions and preview-only actions in one place.

2. Break risk out of the backend surface
   - Start splitting `app/main.py` into smaller route and service modules.
   - Move plugin-facing request handling behind a thin service layer so new actions do not require editing one giant file.
   - Keep the public HTTP contract stable while refactoring.

3. Tighten local developer setup
   - Add a simple documented test command and environment bootstrap path.
   - Make it easy to verify backend behavior before touching the Unreal plugin.

### Week 2

1. Ship one more safe Unreal-side execution path
   - Add a narrow editor action that is easy to validate and undo.
   - Good candidates: asset creation from scaffold metadata, adding an input asset entry, or a constrained material parameter update.
   - Keep confirmation and dry-run behavior mandatory.

2. Reduce manual asset-analysis friction
   - Replace at least one pasted-text workflow with plugin-side extraction from the current Unreal selection.
   - Start with the asset family that has the cleanest editor API and highest value.

3. Improve scan/index quality
   - Add lightweight caching or incremental refresh for large projects.
   - Preserve current behavior, but avoid full rescans when only a small part of the project changes.

## Recommended First Slice

Add backend contract tests for the plugin routes, then use those tests as the safety net for the next Unreal-side execution handler.

Why this first:

- The plugin already depends on several backend routes.
- The current backend is feature-rich but centralized, so regressions are easy to introduce.
- A contract safety net makes the next execution feature much safer to ship.

## Suggested Execution Order

1. Land API contract tests.
2. Extract plugin routes into a dedicated backend module.
3. Implement one additional editor action end to end.
4. Add direct extraction for one deep-analysis flow.
