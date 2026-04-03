#pragma once

#include "CoreMinimal.h"
#include "AssetRegistry/AssetData.h"
#include "Modules/ModuleManager.h"
#include "Widgets/Input/SComboBox.h"

class FUE5CopilotAssistantModule : public IModuleInterface
{
public:
    virtual void StartupModule() override;
    virtual void ShutdownModule() override;

private:
    bool StartBackendProcess(FString& OutError);
    void EnsureBackendAndSendRequest(
        const FString& Url,
        const FString& Payload,
        const TSharedPtr<class SMultiLineEditableTextBox>& OutputTextBox,
        const TSharedPtr<class SMultiLineEditableTextBox>& AgentSessionTextBox,
        const TSharedPtr<class SMultiLineEditableTextBox>& CodeDiffPreviewTextBox,
        const TSharedPtr<class SMultiLineEditableTextBox>& EditorActionPreviewTextBox,
        const TSharedPtr<class SEditableTextBox>& BundleApplyTargetPathTextBox,
        FString* PendingEditorActionJson,
        const TSharedPtr<class STextBlock>& StatusText);
    void LoadSettings();
    void SaveSettings() const;
    void HandleBackendBaseUrlChanged(const FText& NewText);
    void HandleBackendLaunchCommandChanged(const FText& NewText);
    void RegisterMenus();
    TSharedRef<class FExtender> OnExtendContentBrowserAssetSelectionMenu(const TArray<FAssetData>& SelectedAssets);
    void AddAssetContextMenuEntries(class FMenuBuilder& MenuBuilder, TArray<FAssetData> SelectedAssets);
    void OpenAssistantTab();
    void RequestAssetDetailsForSelection(FAssetData AssetData);
    void RequestAssetEditPlanForSelection(FAssetData AssetData);
    TSharedRef<class SDockTab> SpawnAssistantTab(const class FSpawnTabArgs& SpawnTabArgs);
    void RefreshPendingCodePatchBundleTargets(const TArray<FString>& TargetPaths, const FString& PreferredTargetPath = FString());
    void ClearPendingCodePatchBundleTargets();

    FString CurrentBackendBaseUrl = TEXT("http://127.0.0.1:8000");
    FString BackendLaunchCommand;
    TSharedPtr<class SEditableTextBox> BackendBaseUrlTextBoxPtr;
    TSharedPtr<class SEditableTextBox> BackendLaunchCommandTextBoxPtr;
    TSharedPtr<class SEditableTextBox> ScaffoldNameTextBoxPtr;
    TSharedPtr<class SEditableTextBox> ScaffoldPurposeTextBoxPtr;
    TSharedPtr<class SEditableTextBox> ScaffoldClassNameTextBoxPtr;
    TSharedPtr<class SEditableTextBox> CodePatchTargetPathTextBoxPtr;
    TSharedPtr<class SEditableTextBox> BundleApplyTargetPathTextBoxPtr;
    TSharedPtr<SComboBox<TSharedPtr<FString>>> BundleApplyTargetComboBoxPtr;
    TSharedPtr<class SMultiLineEditableTextBox> PromptTextBoxPtr;
    TSharedPtr<class SMultiLineEditableTextBox> OutputTextBoxPtr;
    TSharedPtr<class SMultiLineEditableTextBox> AgentSessionTextBoxPtr;
    TSharedPtr<class SMultiLineEditableTextBox> CodeDiffPreviewTextBoxPtr;
    TSharedPtr<class SMultiLineEditableTextBox> EditorActionPreviewTextBoxPtr;
    TSharedPtr<class STextBlock> StatusTextPtr;
    TSharedPtr<class STextBlock> SelectionPreviewTextPtr;
    TArray<TSharedPtr<FString>> DeepAssetKinds;
    TSharedPtr<FString> SelectedDeepAssetKind;
    TArray<TSharedPtr<FString>> AssetScaffoldKinds;
    TSharedPtr<FString> SelectedAssetScaffoldKind;
    TArray<TSharedPtr<FString>> PendingCodePatchBundleTargets;
    TSharedPtr<FString> SelectedPendingCodePatchBundleTarget;
    FString CurrentAgentTaskId;
    FString PendingEditorActionJson;
    bool bBackendStartupInProgress = false;
};
