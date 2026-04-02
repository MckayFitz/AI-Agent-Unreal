#pragma once

#include "CoreMinimal.h"
#include "AssetRegistry/AssetData.h"
#include "Modules/ModuleManager.h"

class FUE5CopilotAssistantModule : public IModuleInterface
{
public:
    virtual void StartupModule() override;
    virtual void ShutdownModule() override;

private:
    void LoadSettings();
    void SaveSettings() const;
    void HandleBackendBaseUrlChanged(const FText& NewText);
    void RegisterMenus();
    TSharedRef<class FExtender> OnExtendContentBrowserAssetSelectionMenu(const TArray<FAssetData>& SelectedAssets);
    void AddAssetContextMenuEntries(class FMenuBuilder& MenuBuilder, TArray<FAssetData> SelectedAssets);
    void OpenAssistantTab();
    void RequestAssetDetailsForSelection(FAssetData AssetData);
    void RequestAssetEditPlanForSelection(FAssetData AssetData);
    TSharedRef<class SDockTab> SpawnAssistantTab(const class FSpawnTabArgs& SpawnTabArgs);

    FString CurrentBackendBaseUrl = TEXT("http://127.0.0.1:8000");
    TSharedPtr<class SEditableTextBox> BackendBaseUrlTextBoxPtr;
    TSharedPtr<class SEditableTextBox> ScaffoldNameTextBoxPtr;
    TSharedPtr<class SEditableTextBox> ScaffoldPurposeTextBoxPtr;
    TSharedPtr<class SEditableTextBox> ScaffoldClassNameTextBoxPtr;
    TSharedPtr<class SMultiLineEditableTextBox> PromptTextBoxPtr;
    TSharedPtr<class SMultiLineEditableTextBox> OutputTextBoxPtr;
    TSharedPtr<class SMultiLineEditableTextBox> EditorActionPreviewTextBoxPtr;
    TSharedPtr<class STextBlock> StatusTextPtr;
    TSharedPtr<class STextBlock> SelectionPreviewTextPtr;
    TArray<TSharedPtr<FString>> DeepAssetKinds;
    TSharedPtr<FString> SelectedDeepAssetKind;
    TArray<TSharedPtr<FString>> AssetScaffoldKinds;
    TSharedPtr<FString> SelectedAssetScaffoldKind;
    FString PendingEditorActionJson;
};
