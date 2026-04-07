using UnrealBuildTool;

public class UE5CopilotAssistant : ModuleRules
{
    public UE5CopilotAssistant(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(
            new[]
            {
                "Core",
                "CoreUObject",
                "Engine",
                "Slate",
                "SlateCore"
            }
        );

        PrivateDependencyModuleNames.AddRange(
            new[]
            {
                "ApplicationCore",
                "AIModule",
                "AssetRegistry",
                "AssetTools",
                "ContentBrowser",
                "EnhancedInput",
                "EditorStyle",
                "GameProjectGeneration",
                "HTTP",
                "InputCore",
                "Json",
                "JsonUtilities",
                "MaterialEditor",
                "Niagara",
                "Projects",
                "StateTreeEditorModule",
                "StateTreeModule",
                "ToolMenus",
                "UnrealEd",
                "WorkspaceMenuStructure"
            }
        );
    }
}
