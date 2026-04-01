#include "UE5CopilotAssistantModule.h"

#include "AssetRegistry/AssetData.h"
#include "ContentBrowserModule.h"
#include "Editor.h"
#include "Engine/Selection.h"
#include "Framework/Docking/TabManager.h"
#include "HttpModule.h"
#include "IContentBrowserSingleton.h"
#include "Interfaces/IHttpResponse.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Styling/AppStyle.h"
#include "ToolMenus.h"
#include "Widgets/Docking/SDockTab.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Input/SMultiLineEditableTextBox.h"
#include "Widgets/Input/SComboBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Text/STextBlock.h"
#include "WorkspaceMenuStructure.h"

static const FName UE5CopilotAssistantTabName(TEXT("UE5CopilotAssistant"));

#define LOCTEXT_NAMESPACE "FUE5CopilotAssistantModule"

namespace UE5CopilotAssistant
{
    FString EscapeJson(const FString& Value)
    {
        return Value.ReplaceCharWithEscapedChar();
    }

    FString NormalizeBaseUrl(const FString& Value)
    {
        FString Result = Value.TrimStartAndEnd();
        while (Result.EndsWith(TEXT("/")))
        {
            Result.LeftChopInline(1);
        }
        return Result;
    }

    FString BuildAskPayload(const FString& Prompt)
    {
        return FString::Printf(TEXT("{\"question\":\"%s\"}"), *EscapeJson(Prompt));
    }

    FString BuildSelectionPayload(const FString& SelectionName, const FString& SelectionType, const FString& AssetPath, const FString& ClassName)
    {
        return FString::Printf(
            TEXT("{\"selection_name\":\"%s\",\"selection_type\":\"%s\",\"asset_path\":\"%s\",\"class_name\":\"%s\",\"source\":\"ue5_plugin\"}"),
            *EscapeJson(SelectionName),
            *EscapeJson(SelectionType),
            *EscapeJson(AssetPath),
            *EscapeJson(ClassName)
        );
    }

    FString BuildDeepAssetPayload(const FString& AssetKind, const FString& ExportedText, const FString& SelectionName, const FString& AssetPath, const FString& ClassName)
    {
        return FString::Printf(
            TEXT("{\"asset_kind\":\"%s\",\"exported_text\":\"%s\",\"selection_name\":\"%s\",\"asset_path\":\"%s\",\"class_name\":\"%s\",\"source\":\"ue5_plugin\"}"),
            *EscapeJson(AssetKind),
            *EscapeJson(ExportedText),
            *EscapeJson(SelectionName),
            *EscapeJson(AssetPath),
            *EscapeJson(ClassName)
        );
    }

    void HandleJsonResponse(const FString& ResponseText, const TSharedPtr<SMultiLineEditableTextBox>& OutputTextBox, const TSharedPtr<STextBlock>& StatusText)
    {
        TSharedPtr<FJsonObject> JsonObject;
        TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(ResponseText);
        FString DisplayText = ResponseText;

        if (FJsonSerializer::Deserialize(Reader, JsonObject) && JsonObject.IsValid())
        {
            if (JsonObject->HasField(TEXT("answer")))
            {
                DisplayText = JsonObject->GetStringField(TEXT("answer"));
            }
            else if (JsonObject->HasField(TEXT("analysis")))
            {
                DisplayText = JsonObject->GetStringField(TEXT("analysis"));
            }
            else
            {
                FString PrettyJson;
                TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&PrettyJson);
                FJsonSerializer::Serialize(JsonObject.ToSharedRef(), Writer);
                DisplayText = PrettyJson;
            }
        }

        if (OutputTextBox.IsValid())
        {
            OutputTextBox->SetText(FText::FromString(DisplayText));
        }

        if (StatusText.IsValid())
        {
            StatusText->SetText(LOCTEXT("UE5CopilotStatusDone", "Response received."));
        }
    }

    void SendPostRequest(const FString& Url, const FString& Payload, const TSharedPtr<SMultiLineEditableTextBox>& OutputTextBox, const TSharedPtr<STextBlock>& StatusText)
    {
        TSharedRef<IHttpRequest, ESPMode::ThreadSafe> Request = FHttpModule::Get().CreateRequest();
        Request->SetURL(Url);
        Request->SetVerb(TEXT("POST"));
        Request->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
        Request->SetContentAsString(Payload);

        Request->OnProcessRequestComplete().BindLambda(
            [OutputTextBox, StatusText](FHttpRequestPtr HttpRequest, FHttpResponsePtr HttpResponse, bool bSucceeded)
            {
                if (!bSucceeded || !HttpResponse.IsValid())
                {
                    if (StatusText.IsValid())
                    {
                        StatusText->SetText(LOCTEXT("UE5CopilotStatusFailed", "Request failed. Make sure the backend is running."));
                    }
                    return;
                }

                HandleJsonResponse(HttpResponse->GetContentAsString(), OutputTextBox, StatusText);
            }
        );

        Request->ProcessRequest();
    }

    bool GetCurrentSelection(FString& OutSelectionName, FString& OutSelectionType, FString& OutAssetPath, FString& OutClassName)
    {
        OutSelectionName.Reset();
        OutSelectionType.Reset();
        OutAssetPath.Reset();
        OutClassName.Reset();

        if (GEditor)
        {
            USelection* SelectedActors = GEditor->GetSelectedActors();
            if (SelectedActors && SelectedActors->Num() > 0)
            {
                if (AActor* Actor = Cast<AActor>(SelectedActors->GetSelectedObject(0)))
                {
                    OutSelectionName = Actor->GetActorLabel();
                    OutSelectionType = TEXT("actor");
                    OutClassName = Actor->GetClass() ? Actor->GetClass()->GetName() : TEXT("");
                    return true;
                }
            }
        }

        FContentBrowserModule& ContentBrowserModule = FModuleManager::LoadModuleChecked<FContentBrowserModule>(TEXT("ContentBrowser"));
        TArray<FAssetData> SelectedAssets;
        ContentBrowserModule.Get().GetSelectedAssets(SelectedAssets);
        if (SelectedAssets.Num() > 0)
        {
            const FAssetData& AssetData = SelectedAssets[0];
            OutSelectionName = AssetData.AssetName.ToString();
            OutSelectionType = TEXT("asset");
            OutAssetPath = AssetData.GetSoftObjectPath().ToString();
            OutClassName = AssetData.AssetClassPath.GetAssetName().ToString();
            return true;
        }

        return false;
    }
}

void FUE5CopilotAssistantModule::StartupModule()
{
    FGlobalTabmanager::Get()->RegisterNomadTabSpawner(
        UE5CopilotAssistantTabName,
        FOnSpawnTab::CreateRaw(this, &FUE5CopilotAssistantModule::SpawnAssistantTab)
    )
    .SetDisplayName(LOCTEXT("UE5CopilotAssistantTabTitle", "UE5 Copilot"))
    .SetMenuType(ETabSpawnerMenuType::Hidden)
    .SetGroup(WorkspaceMenu::GetMenuStructure().GetDeveloperToolsMiscCategory());

    UToolMenus::RegisterStartupCallback(
        FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FUE5CopilotAssistantModule::RegisterMenus)
    );
}

void FUE5CopilotAssistantModule::ShutdownModule()
{
    UToolMenus::UnRegisterStartupCallback(this);
    UToolMenus::UnregisterOwner(this);
    FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(UE5CopilotAssistantTabName);
}

void FUE5CopilotAssistantModule::RegisterMenus()
{
    FToolMenuOwnerScoped OwnerScoped(this);

    UToolMenu* Menu = UToolMenus::Get()->ExtendMenu("LevelEditor.MainMenu.Window");
    FToolMenuSection& Section = Menu->FindOrAddSection("WindowLayout");
    Section.AddMenuEntry(
        "OpenUE5CopilotAssistant",
        LOCTEXT("OpenUE5CopilotAssistant", "UE5 Copilot"),
        LOCTEXT("OpenUE5CopilotAssistantTooltip", "Open the UE5 Copilot assistant tab."),
        FSlateIcon(FAppStyle::GetAppStyleSetName(), "LevelEditor.Tabs.Details"),
        FUIAction(FExecuteAction::CreateLambda([]()
        {
            FGlobalTabmanager::Get()->TryInvokeTab(UE5CopilotAssistantTabName);
        }))
    );
}

TSharedRef<SDockTab> FUE5CopilotAssistantModule::SpawnAssistantTab(const FSpawnTabArgs& SpawnTabArgs)
{
    TSharedPtr<SEditableTextBox> BackendBaseUrlTextBox;
    TSharedPtr<SMultiLineEditableTextBox> PromptTextBox;
    TSharedPtr<SMultiLineEditableTextBox> DeepAssetTextBox;
    TSharedPtr<SMultiLineEditableTextBox> OutputTextBox;
    TSharedPtr<STextBlock> StatusText;
    TSharedPtr<STextBlock> SelectionPreviewText;

    TArray<TSharedPtr<FString>> AssetKinds;
    AssetKinds.Add(MakeShared<FString>(TEXT("blueprint")));
    AssetKinds.Add(MakeShared<FString>(TEXT("material")));
    AssetKinds.Add(MakeShared<FString>(TEXT("behavior_tree")));
    AssetKinds.Add(MakeShared<FString>(TEXT("enhanced_input")));
    AssetKinds.Add(MakeShared<FString>(TEXT("animbp")));
    TSharedPtr<FString> SelectedAssetKind = AssetKinds[0];

    return SNew(SDockTab)
        .TabRole(ETabRole::NomadTab)
        [
            SNew(SBorder)
            .Padding(12.0f)
            [
                SNew(SVerticalBox)

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                [
                    SNew(STextBlock)
                    .Text(LOCTEXT("UE5CopilotHeader", "UE5 Copilot Assistant"))
                    .Font(FAppStyle::GetFontStyle("HeadingExtraSmall"))
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SAssignNew(StatusText, STextBlock)
                    .Text(LOCTEXT("UE5CopilotStatusDefault", "Point this tab at the FastAPI backend, ask a question, analyze current selection, or send deep asset text."))
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SAssignNew(BackendBaseUrlTextBox, SEditableTextBox)
                    .Text(FText::FromString(TEXT("http://127.0.0.1:8000")))
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SAssignNew(SelectionPreviewText, STextBlock)
                    .Text(LOCTEXT("UE5CopilotSelectionDefault", "Current selection: none"))
                ]

                + SVerticalBox::Slot()
                .FillHeight(0.20f)
                .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                [
                    SAssignNew(PromptTextBox, SMultiLineEditableTextBox)
                    .HintText(LOCTEXT("UE5CopilotPromptHint", "Ask about the project or current selection..."))
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                [
                    SNew(SHorizontalBox)

                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    .Padding(0.0f, 0.0f, 4.0f, 0.0f)
                    [
                        SNew(SButton)
                        .Text(LOCTEXT("UE5CopilotSendAsk", "Ask Backend"))
                        .OnClicked_Lambda([BackendBaseUrlTextBox, PromptTextBox, OutputTextBox, StatusText]()
                        {
                            const FString BaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(BackendBaseUrlTextBox.IsValid() ? BackendBaseUrlTextBox->GetText().ToString() : FString());
                            const FString Prompt = PromptTextBox.IsValid() ? PromptTextBox->GetText().ToString() : FString();
                            if (BaseUrl.IsEmpty() || Prompt.IsEmpty())
                            {
                                if (StatusText.IsValid())
                                {
                                    StatusText->SetText(LOCTEXT("UE5CopilotStatusMissingAskInput", "Enter a backend URL and a prompt first."));
                                }
                                return FReply::Handled();
                            }

                            if (StatusText.IsValid())
                            {
                                StatusText->SetText(LOCTEXT("UE5CopilotStatusSendingAsk", "Sending question to backend..."));
                            }

                            UE5CopilotAssistant::SendPostRequest(
                                BaseUrl + TEXT("/ask"),
                                UE5CopilotAssistant::BuildAskPayload(Prompt),
                                OutputTextBox,
                                StatusText
                            );
                            return FReply::Handled();
                        })
                    ]

                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    .Padding(4.0f, 0.0f, 0.0f, 0.0f)
                    [
                        SNew(SButton)
                        .Text(LOCTEXT("UE5CopilotSendSelection", "Analyze Current Selection"))
                        .OnClicked_Lambda([BackendBaseUrlTextBox, OutputTextBox, StatusText, SelectionPreviewText]()
                        {
                            const FString BaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(BackendBaseUrlTextBox.IsValid() ? BackendBaseUrlTextBox->GetText().ToString() : FString());
                            if (BaseUrl.IsEmpty())
                            {
                                if (StatusText.IsValid())
                                {
                                    StatusText->SetText(LOCTEXT("UE5CopilotStatusMissingBaseUrl", "Enter a backend base URL first."));
                                }
                                return FReply::Handled();
                            }

                            FString SelectionName, SelectionType, AssetPath, ClassName;
                            if (!UE5CopilotAssistant::GetCurrentSelection(SelectionName, SelectionType, AssetPath, ClassName))
                            {
                                if (StatusText.IsValid())
                                {
                                    StatusText->SetText(LOCTEXT("UE5CopilotStatusNoSelection", "No actor or asset is currently selected in the editor."));
                                }
                                if (SelectionPreviewText.IsValid())
                                {
                                    SelectionPreviewText->SetText(LOCTEXT("UE5CopilotSelectionNone", "Current selection: none"));
                                }
                                return FReply::Handled();
                            }

                            if (SelectionPreviewText.IsValid())
                            {
                                SelectionPreviewText->SetText(FText::FromString(FString::Printf(TEXT("Current selection: %s [%s]"), *SelectionName, *SelectionType)));
                            }
                            if (StatusText.IsValid())
                            {
                                StatusText->SetText(LOCTEXT("UE5CopilotStatusSendingSelection", "Sending current editor selection to backend..."));
                            }

                            UE5CopilotAssistant::SendPostRequest(
                                BaseUrl + TEXT("/plugin/selection-context"),
                                UE5CopilotAssistant::BuildSelectionPayload(SelectionName, SelectionType, AssetPath, ClassName),
                                OutputTextBox,
                                StatusText
                            );
                            return FReply::Handled();
                        })
                    ]
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SNew(SComboBox<TSharedPtr<FString>>)
                    .OptionsSource(&AssetKinds)
                    .InitiallySelectedItem(SelectedAssetKind)
                    .OnGenerateWidget_Lambda([](TSharedPtr<FString> Item)
                    {
                        return SNew(STextBlock).Text(FText::FromString(Item.IsValid() ? *Item : TEXT("")));
                    })
                    .OnSelectionChanged_Lambda([&SelectedAssetKind](TSharedPtr<FString> NewValue, ESelectInfo::Type)
                    {
                        SelectedAssetKind = NewValue;
                    })
                    [
                        SNew(STextBlock)
                        .Text_Lambda([&SelectedAssetKind]()
                        {
                            return FText::FromString(SelectedAssetKind.IsValid() ? *SelectedAssetKind : TEXT("blueprint"));
                        })
                    ]
                ]

                + SVerticalBox::Slot()
                .FillHeight(0.20f)
                .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                [
                    SAssignNew(DeepAssetTextBox, SMultiLineEditableTextBox)
                    .HintText(LOCTEXT("UE5CopilotDeepAssetHint", "Paste exported graph/state text for the selected asset here..."))
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                [
                    SNew(SButton)
                    .Text(LOCTEXT("UE5CopilotDeepAnalyze", "Deep Analyze Selected Asset"))
                    .OnClicked_Lambda([BackendBaseUrlTextBox, DeepAssetTextBox, OutputTextBox, StatusText, SelectionPreviewText, &SelectedAssetKind]()
                    {
                        const FString BaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(BackendBaseUrlTextBox.IsValid() ? BackendBaseUrlTextBox->GetText().ToString() : FString());
                        const FString ExportedText = DeepAssetTextBox.IsValid() ? DeepAssetTextBox->GetText().ToString() : FString();
                        if (BaseUrl.IsEmpty())
                        {
                            if (StatusText.IsValid())
                            {
                                StatusText->SetText(LOCTEXT("UE5CopilotStatusMissingDeepBaseUrl", "Enter a backend base URL first."));
                            }
                            return FReply::Handled();
                        }

                        FString SelectionName, SelectionType, AssetPath, ClassName;
                        if (!UE5CopilotAssistant::GetCurrentSelection(SelectionName, SelectionType, AssetPath, ClassName))
                        {
                            if (StatusText.IsValid())
                            {
                                StatusText->SetText(LOCTEXT("UE5CopilotStatusNoSelectionDeep", "Select an actor or asset before deep analysis."));
                            }
                            return FReply::Handled();
                        }

                        if (SelectionPreviewText.IsValid())
                        {
                            SelectionPreviewText->SetText(FText::FromString(FString::Printf(TEXT("Current selection: %s [%s]"), *SelectionName, *SelectionType)));
                        }

                        if (StatusText.IsValid())
                        {
                            StatusText->SetText(LOCTEXT("UE5CopilotStatusSendingDeep", "Sending deep asset analysis request..."));
                        }

                        UE5CopilotAssistant::SendPostRequest(
                            BaseUrl + TEXT("/asset-deep-analysis"),
                            UE5CopilotAssistant::BuildDeepAssetPayload(
                                SelectedAssetKind.IsValid() ? *SelectedAssetKind : FString(TEXT("blueprint")),
                                ExportedText,
                                SelectionName,
                                AssetPath,
                                ClassName
                            ),
                            OutputTextBox,
                            StatusText
                        );
                        return FReply::Handled();
                    })
                ]

                + SVerticalBox::Slot()
                .FillHeight(0.60f)
                [
                    SAssignNew(OutputTextBox, SMultiLineEditableTextBox)
                    .IsReadOnly(true)
                    .HintText(LOCTEXT("UE5CopilotOutputHint", "Backend responses and deep asset analysis will appear here."))
                ]
            ]
        ];
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FUE5CopilotAssistantModule, UE5CopilotAssistant)
