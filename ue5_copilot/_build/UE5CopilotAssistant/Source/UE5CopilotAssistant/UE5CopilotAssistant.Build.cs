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
                "AssetRegistry",
                "AssetTools",
                "ContentBrowser",
                "EnhancedInput",
                "EditorStyle",
                "HTTP",
                "InputCore",
                "Json",
                "JsonUtilities",
                "MaterialEditor",
                "Projects",
                "ToolMenus",
                "UnrealEd",
                "WorkspaceMenuStructure"
            }
        );
    }
}
