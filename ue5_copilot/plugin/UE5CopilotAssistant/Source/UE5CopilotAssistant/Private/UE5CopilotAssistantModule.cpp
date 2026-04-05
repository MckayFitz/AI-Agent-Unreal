#include "UE5CopilotAssistantModule.h"

#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "IAssetTools.h"
#include "AssetToolsModule.h"
#include "ContentBrowserModule.h"
#include "Components/ActorComponent.h"
#include "Editor.h"
#include "EnhancedInput/Public/InputAction.h"
#include "EnhancedInput/Public/InputMappingContext.h"
#include "Engine/Blueprint.h"
#include "Engine/DataAsset.h"
#include "Engine/Selection.h"
#include "Factories/DataAssetFactory.h"
#include "Factories/MaterialInstanceConstantFactoryNew.h"
#include "Framework/Docking/TabManager.h"
#include "Framework/MultiBox/MultiBoxBuilder.h"
#include "GameFramework/Actor.h"
#include "GameFramework/Character.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "HAL/PlatformProcess.h"
#include "Http.h"
#include "HttpModule.h"
#include "IContentBrowserSingleton.h"
#include "Interfaces/IPluginManager.h"
#include "Interfaces/IHttpResponse.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Misc/MessageDialog.h"
#include "Misc/PackageName.h"
#include "Misc/ConfigCacheIni.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/SecureHash.h"
#include "Materials/MaterialInterface.h"
#include "Materials/MaterialInstanceConstant.h"
#include "MaterialEditingLibrary.h"
#include "Engine/Texture.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Styling/AppStyle.h"
#include "ToolMenus.h"
#include "Containers/Ticker.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UnrealType.h"
#include "UObject/SoftObjectPath.h"
#include "Widgets/Docking/SDockTab.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Input/SMultiLineEditableTextBox.h"
#include "Widgets/Input/SComboBox.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SExpandableArea.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Text/STextBlock.h"
#include "WorkspaceMenuStructureModule.h"
#include "WorkspaceMenuStructure.h"

static const FName UE5CopilotAssistantTabName(TEXT("UE5CopilotAssistant"));
static const TCHAR* UE5CopilotSettingsSection = TEXT("/Script/UE5CopilotAssistant.UE5CopilotAssistant");
static const TCHAR* UE5CopilotBackendUrlKey = TEXT("BackendBaseUrl");
static const TCHAR* UE5CopilotBackendLaunchCommandKey = TEXT("BackendLaunchCommand");

#define LOCTEXT_NAMESPACE "FUE5CopilotAssistantModule"

namespace UE5CopilotAssistant
{
    FString FormatEditorActionPreview(const TSharedPtr<FJsonObject>& JsonObject);
    FString SerializeJsonObject(const TSharedPtr<FJsonObject>& JsonObject);

    FString JoinLines(const TArray<FString>& Lines)
    {
        FString Result;
        for (int32 Index = 0; Index < Lines.Num(); ++Index)
        {
            Result += Lines[Index];
            if (Index + 1 < Lines.Num())
            {
                Result += TEXT("\n");
            }
        }
        return Result;
    }

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

    FString BuildSuggestedBackendLaunchCommand()
    {
        const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("UE5CopilotAssistant"));
        if (!Plugin.IsValid())
        {
            return FString();
        }

        const FString RepoRoot = FPaths::ConvertRelativePathToFull(FPaths::Combine(Plugin->GetBaseDir(), TEXT(".."), TEXT("..")));
        const FString PythonPath = FPaths::Combine(RepoRoot, TEXT("venv"), TEXT("Scripts"), TEXT("python.exe"));
        const FString MainPath = FPaths::Combine(RepoRoot, TEXT("app"), TEXT("main.py"));
        if (!FPaths::FileExists(PythonPath) || !FPaths::FileExists(MainPath))
        {
            return FString();
        }

        return FString::Printf(
            TEXT("\"%s\" -m uvicorn app.main:app --app-dir \"%s\" --host 127.0.0.1 --port 8000 --reload"),
            *PythonPath,
            *RepoRoot
        );
    }

    UClass* ResolveBlueprintParentClass(const FString& ParentClassName)
    {
        const FString TrimmedName = ParentClassName.TrimStartAndEnd();
        if (TrimmedName.IsEmpty())
        {
            return nullptr;
        }

        if (TrimmedName == TEXT("Actor"))
        {
            return AActor::StaticClass();
        }
        if (TrimmedName == TEXT("Pawn"))
        {
            return APawn::StaticClass();
        }
        if (TrimmedName == TEXT("Character"))
        {
            return ACharacter::StaticClass();
        }
        if (TrimmedName == TEXT("PlayerController"))
        {
            return APlayerController::StaticClass();
        }
        if (TrimmedName == TEXT("ActorComponent"))
        {
            return UActorComponent::StaticClass();
        }

        return FindFirstObject<UClass>(*TrimmedName, EFindFirstObjectOptions::None);
    }

    bool CreateBlueprintAsset(const FString& PackagePath, const FString& AssetName, const FString& ParentClassName, FString& OutError)
    {
        if (!PackagePath.StartsWith(TEXT("/Game")))
        {
            OutError = TEXT("Create-asset actions currently require a /Game package path.");
            return false;
        }

        if (AssetName.IsEmpty())
        {
            OutError = TEXT("Create-asset actions require a non-empty asset name.");
            return false;
        }

        UClass* ParentClass = ResolveBlueprintParentClass(ParentClassName);
        if (!ParentClass)
        {
            OutError = FString::Printf(TEXT("The parent class `%s` could not be resolved in the editor."), *ParentClassName);
            return false;
        }

        if (!FKismetEditorUtilities::CanCreateBlueprintOfClass(ParentClass))
        {
            OutError = FString::Printf(TEXT("The parent class `%s` does not support regular Blueprint creation."), *ParentClassName);
            return false;
        }

        const FString ObjectPath = PackagePath / AssetName;
        if (FindObject<UObject>(nullptr, *ObjectPath))
        {
            OutError = FString::Printf(TEXT("An asset already exists at `%s`."), *ObjectPath);
            return false;
        }

        UPackage* Package = CreatePackage(*ObjectPath);
        if (!Package)
        {
            OutError = FString::Printf(TEXT("The package `%s` could not be created."), *ObjectPath);
            return false;
        }

        UBlueprint* Blueprint = FKismetEditorUtilities::CreateBlueprint(
            ParentClass,
            Package,
            *AssetName,
            BPTYPE_Normal,
            UBlueprint::StaticClass(),
            UBlueprintGeneratedClass::StaticClass(),
            FName(TEXT("UE5CopilotAssistant"))
        );
        if (!Blueprint)
        {
            OutError = FString::Printf(TEXT("Blueprint creation failed for `%s`."), *ObjectPath);
            return false;
        }

        FAssetRegistryModule::AssetCreated(Blueprint);
        Package->MarkPackageDirty();
        return true;
    }

    bool CreateEnhancedInputAsset(const FString& PackagePath, const FString& AssetName, const FString& AssetKind, FString& OutError)
    {
        if (!PackagePath.StartsWith(TEXT("/Game")))
        {
            OutError = TEXT("Create-asset actions currently require a /Game package path.");
            return false;
        }

        if (AssetName.IsEmpty())
        {
            OutError = TEXT("Create-asset actions require a non-empty asset name.");
            return false;
        }

        const FString ObjectPath = PackagePath / AssetName;
        if (FindObject<UObject>(nullptr, *ObjectPath))
        {
            OutError = FString::Printf(TEXT("An asset already exists at `%s`."), *ObjectPath);
            return false;
        }

        UPackage* Package = CreatePackage(*ObjectPath);
        if (!Package)
        {
            OutError = FString::Printf(TEXT("The package `%s` could not be created."), *ObjectPath);
            return false;
        }

        UObject* CreatedObject = nullptr;
        if (AssetKind == TEXT("input_action"))
        {
            CreatedObject = NewObject<UInputAction>(Package, *AssetName, RF_Public | RF_Standalone | RF_Transactional);
        }
        else if (AssetKind == TEXT("input_mapping_context"))
        {
            CreatedObject = NewObject<UInputMappingContext>(Package, *AssetName, RF_Public | RF_Standalone | RF_Transactional);
        }
        else
        {
            OutError = FString::Printf(TEXT("Unsupported create-asset kind `%s`."), *AssetKind);
            return false;
        }

        if (!CreatedObject)
        {
            OutError = FString::Printf(TEXT("Asset creation failed for `%s`."), *ObjectPath);
            return false;
        }

        FAssetRegistryModule::AssetCreated(CreatedObject);
        Package->MarkPackageDirty();
        return true;
    }

    UClass* ResolveDataAssetClass(const FString& ClassName)
    {
        const FString TrimmedName = ClassName.TrimStartAndEnd();
        if (TrimmedName.IsEmpty())
        {
            return nullptr;
        }

        if (TrimmedName.StartsWith(TEXT("/")))
        {
            if (UClass* LoadedClass = LoadObject<UClass>(nullptr, *TrimmedName))
            {
                return LoadedClass;
            }
        }

        return FindFirstObject<UClass>(*TrimmedName, EFindFirstObjectOptions::None);
    }

    bool CreateDataAsset(const FString& PackagePath, const FString& AssetName, const FString& AssetClassName, FString& OutError)
    {
        if (!PackagePath.StartsWith(TEXT("/Game")))
        {
            OutError = TEXT("Create-asset actions currently require a /Game package path.");
            return false;
        }

        if (AssetName.IsEmpty())
        {
            OutError = TEXT("Create-asset actions require a non-empty asset name.");
            return false;
        }

        if (AssetClassName.IsEmpty())
        {
            OutError = TEXT("Data Asset creation requires an `asset_class` argument.");
            return false;
        }

        UClass* AssetClass = ResolveDataAssetClass(AssetClassName);
        if (!AssetClass)
        {
            OutError = FString::Printf(TEXT("The Data Asset class `%s` could not be resolved in the editor."), *AssetClassName);
            return false;
        }

        if (!AssetClass->IsChildOf(UDataAsset::StaticClass()))
        {
            OutError = FString::Printf(TEXT("`%s` is not a UDataAsset-derived class."), *AssetClassName);
            return false;
        }

        const FString ObjectPath = PackagePath / AssetName;
        if (FindObject<UObject>(nullptr, *ObjectPath))
        {
            OutError = FString::Printf(TEXT("An asset already exists at `%s`."), *ObjectPath);
            return false;
        }

        UDataAssetFactory* Factory = NewObject<UDataAssetFactory>();
        if (!Factory)
        {
            OutError = TEXT("The Data Asset factory could not be created.");
            return false;
        }
        Factory->DataAssetClass = AssetClass;

        FAssetToolsModule& AssetToolsModule = FModuleManager::LoadModuleChecked<FAssetToolsModule>(TEXT("AssetTools"));
        UObject* CreatedObject = AssetToolsModule.Get().CreateAsset(
            AssetName,
            PackagePath,
            AssetClass,
            Factory
        );

        if (!CreatedObject)
        {
            OutError = FString::Printf(TEXT("Data Asset creation failed for `%s`. Check that `%s` is compiled and available in the editor."), *ObjectPath, *AssetClassName);
            return false;
        }

        return true;
    }

    bool CreateMaterialInstanceAsset(const FString& PackagePath, const FString& AssetName, const FString& ParentMaterialPathOrName, FString& OutError)
    {
        if (!PackagePath.StartsWith(TEXT("/Game")))
        {
            OutError = TEXT("Create-asset actions currently require a /Game package path.");
            return false;
        }

        if (AssetName.IsEmpty())
        {
            OutError = TEXT("Create-asset actions require a non-empty asset name.");
            return false;
        }

        const FString ObjectPath = PackagePath / AssetName;
        if (FindObject<UObject>(nullptr, *ObjectPath))
        {
            OutError = FString::Printf(TEXT("An asset already exists at `%s`."), *ObjectPath);
            return false;
        }

        UMaterialInterface* ParentMaterial = nullptr;
        const FString ParentHint = ParentMaterialPathOrName.TrimStartAndEnd();
        if (!ParentHint.IsEmpty())
        {
            if (ParentHint.StartsWith(TEXT("/")))
            {
                ParentMaterial = LoadObject<UMaterialInterface>(nullptr, *ParentHint);
            }
            if (!ParentMaterial)
            {
                ParentMaterial = FindFirstObject<UMaterialInterface>(*ParentHint, EFindFirstObjectOptions::None);
            }
        }

        UMaterialInstanceConstantFactoryNew* Factory = NewObject<UMaterialInstanceConstantFactoryNew>();
        if (!Factory)
        {
            OutError = TEXT("The Material Instance factory could not be created.");
            return false;
        }
        Factory->InitialParent = ParentMaterial;

        FAssetToolsModule& AssetToolsModule = FModuleManager::LoadModuleChecked<FAssetToolsModule>(TEXT("AssetTools"));
        UObject* CreatedObject = AssetToolsModule.Get().CreateAsset(
            AssetName,
            PackagePath,
            UMaterialInstanceConstant::StaticClass(),
            Factory
        );

        if (!CreatedObject)
        {
            OutError = ParentHint.IsEmpty()
                ? FString::Printf(TEXT("Material Instance creation failed for `%s`."), *ObjectPath)
                : FString::Printf(TEXT("Material Instance creation failed for `%s`. Check that the parent material `%s` exists and is loadable."), *ObjectPath, *ParentHint);
            return false;
        }

        return true;
    }

    bool ParseVectorParameterValue(const FString& ValueText, FLinearColor& OutColor)
    {
        TArray<FString> Parts;
        ValueText.ParseIntoArray(Parts, TEXT(","), true);
        if (Parts.Num() < 3)
        {
            return false;
        }

        double Components[4] = {0.0, 0.0, 0.0, 1.0};
        for (int32 Index = 0; Index < FMath::Min(Parts.Num(), 4); ++Index)
        {
            const FString Part = Parts[Index].TrimStartAndEnd();
            if (!LexTryParseString(Components[Index], *Part))
            {
                return false;
            }
        }

        OutColor = FLinearColor(
            static_cast<float>(Components[0]),
            static_cast<float>(Components[1]),
            static_cast<float>(Components[2]),
            static_cast<float>(Components[3])
        );
        return true;
    }

    bool TweakMaterialInstanceParameter(const FString& AssetPath, const FString& ParameterName, const FString& ParameterType, const FString& ParameterValue, FString& OutError)
    {
        if (AssetPath.IsEmpty() || ParameterName.IsEmpty() || ParameterType.IsEmpty() || ParameterValue.IsEmpty())
        {
            OutError = TEXT("Material parameter edits require `asset_path`, `parameter_name`, `parameter_type`, and `parameter_value`.");
            return false;
        }

        UMaterialInstanceConstant* MaterialInstance = LoadObject<UMaterialInstanceConstant>(nullptr, *AssetPath);
        if (!MaterialInstance)
        {
            OutError = FString::Printf(TEXT("The Material Instance `%s` could not be loaded."), *AssetPath);
            return false;
        }

        const FName ParameterFName(*ParameterName);
        const FString NormalizedType = ParameterType.ToLower();

        if (NormalizedType == TEXT("scalar"))
        {
            double ParsedScalar = 0.0;
            if (!LexTryParseString(ParsedScalar, *ParameterValue))
            {
                OutError = FString::Printf(TEXT("`%s` is not a valid scalar parameter value."), *ParameterValue);
                return false;
            }

            UMaterialEditingLibrary::SetMaterialInstanceScalarParameterValue(MaterialInstance, ParameterFName, static_cast<float>(ParsedScalar));
            MaterialInstance->MarkPackageDirty();
            return true;
        }

        if (NormalizedType == TEXT("vector"))
        {
            FLinearColor ParsedColor;
            if (!ParseVectorParameterValue(ParameterValue, ParsedColor))
            {
                OutError = FString::Printf(TEXT("`%s` is not a valid vector parameter value. Expected comma-separated RGB or RGBA floats."), *ParameterValue);
                return false;
            }

            UMaterialEditingLibrary::SetMaterialInstanceVectorParameterValue(MaterialInstance, ParameterFName, ParsedColor);
            MaterialInstance->MarkPackageDirty();
            return true;
        }

        if (NormalizedType == TEXT("texture"))
        {
            UTexture* Texture = nullptr;
            if (ParameterValue.StartsWith(TEXT("/")))
            {
                Texture = LoadObject<UTexture>(nullptr, *ParameterValue);
            }
            if (!Texture)
            {
                Texture = FindFirstObject<UTexture>(*ParameterValue, EFindFirstObjectOptions::None);
            }
            if (!Texture)
            {
                OutError = FString::Printf(TEXT("The texture `%s` could not be resolved in the editor."), *ParameterValue);
                return false;
            }

            UMaterialEditingLibrary::SetMaterialInstanceTextureParameterValue(MaterialInstance, ParameterFName, Texture);
            MaterialInstance->MarkPackageDirty();
            return true;
        }

        OutError = FString::Printf(TEXT("Material parameter editing is not implemented yet for `%s` parameters."), *ParameterType);
        return false;
    }

    FString BuildAskPayload(const FString& Prompt)
    {
        return FString::Printf(TEXT("{\"question\":\"%s\"}"), *EscapeJson(Prompt));
    }

    FString GetCurrentProjectPathForPayload()
    {
        return FPaths::ConvertRelativePathToFull(FPaths::ProjectDir());
    }

    FString BuildPluginChatPayload(
        const FString& Message,
        const FString& SelectionName,
        const FString& SelectionType,
        const FString& AssetPath,
        const FString& ClassName,
        const FString& ExportedText)
    {
        const FString ProjectPath = GetCurrentProjectPathForPayload();
        return FString::Printf(
            TEXT("{\"message\":\"%s\",\"selection_name\":\"%s\",\"selection_type\":\"%s\",\"asset_path\":\"%s\",\"class_name\":\"%s\",\"exported_text\":\"%s\",\"project_path\":\"%s\",\"source\":\"ue5_plugin\"}"),
            *EscapeJson(Message),
            *EscapeJson(SelectionName),
            *EscapeJson(SelectionType),
            *EscapeJson(AssetPath),
            *EscapeJson(ClassName),
            *EscapeJson(ExportedText),
            *EscapeJson(ProjectPath)
        );
    }

    FString BuildSelectionPayload(const FString& SelectionName, const FString& SelectionType, const FString& AssetPath, const FString& ClassName)
    {
        const FString ProjectPath = GetCurrentProjectPathForPayload();
        return FString::Printf(
            TEXT("{\"selection_name\":\"%s\",\"selection_type\":\"%s\",\"asset_path\":\"%s\",\"class_name\":\"%s\",\"project_path\":\"%s\",\"source\":\"ue5_plugin\"}"),
            *EscapeJson(SelectionName),
            *EscapeJson(SelectionType),
            *EscapeJson(AssetPath),
            *EscapeJson(ClassName),
            *EscapeJson(ProjectPath)
        );
    }

    FString BuildDeepAssetPayload(const FString& AssetKind, const FString& ExportedText, const FString& SelectionName, const FString& AssetPath, const FString& ClassName)
    {
        const FString ProjectPath = GetCurrentProjectPathForPayload();
        return FString::Printf(
            TEXT("{\"asset_kind\":\"%s\",\"exported_text\":\"%s\",\"selection_name\":\"%s\",\"asset_path\":\"%s\",\"class_name\":\"%s\",\"project_path\":\"%s\",\"source\":\"ue5_plugin\"}"),
            *EscapeJson(AssetKind),
            *EscapeJson(ExportedText),
            *EscapeJson(SelectionName),
            *EscapeJson(AssetPath),
            *EscapeJson(ClassName),
            *EscapeJson(ProjectPath)
        );
    }

    FString FormatPropertyValue(FProperty* Property, const void* Container)
    {
        if (!Property || !Container)
        {
            return TEXT("None");
        }

        FString ExportedValue;
        Property->ExportTextItem_Direct(ExportedValue, Property->ContainerPtrToValuePtr<void>(Container), nullptr, nullptr, PPF_None);
        ExportedValue = ExportedValue.Replace(TEXT("\r"), TEXT(" ")).Replace(TEXT("\n"), TEXT(" "));
        ExportedValue = ExportedValue.TrimStartAndEnd();
        if (ExportedValue.IsEmpty())
        {
            ExportedValue = TEXT("None");
        }
        if (ExportedValue.Len() > 180)
        {
            ExportedValue = ExportedValue.Left(177) + TEXT("...");
        }
        return ExportedValue;
    }

    FString BuildReflectedAssetSummary(const FAssetData& AssetData)
    {
        const FString AssetName = AssetData.AssetName.ToString();
        const FString AssetClassName = AssetData.AssetClassPath.GetAssetName().ToString();
        const FString AssetObjectPath = AssetData.GetSoftObjectPath().ToString();

        UObject* AssetObject = AssetData.FastGetAsset();
        TArray<FString> Lines;
        Lines.Add(FString::Printf(TEXT("Selected Asset: %s"), *AssetName));
        Lines.Add(FString::Printf(TEXT("Asset Class: %s"), *AssetClassName));
        Lines.Add(FString::Printf(TEXT("Asset Path: %s"), *AssetObjectPath));

        if (!AssetObject)
        {
            Lines.Add(TEXT("Asset Object: Could not be loaded in the editor; using metadata-only fallback context."));
            return JoinLines(Lines);
        }

        Lines.Add(FString::Printf(TEXT("Loaded Class: %s"), *AssetObject->GetClass()->GetName()));

        const FString LoweredAssetClassName = AssetClassName.ToLower();
        const FString LoweredAssetName = AssetName.ToLower();
        const bool bBlueprintAsset =
            LoweredAssetClassName.Contains(TEXT("blueprint")) ||
            LoweredAssetName.StartsWith(TEXT("bp_")) ||
            LoweredAssetName.StartsWith(TEXT("wbp_")) ||
            LoweredAssetName.StartsWith(TEXT("abp_"));
        const bool bInputActionAsset = LoweredAssetClassName.Contains(TEXT("inputaction")) || LoweredAssetName.StartsWith(TEXT("ia_"));
        const bool bInputMappingContextAsset = LoweredAssetClassName.Contains(TEXT("inputmappingcontext")) || LoweredAssetName.StartsWith(TEXT("imc_"));
        const bool bMaterialInstanceAsset = LoweredAssetClassName.Contains(TEXT("materialinstance")) || LoweredAssetName.StartsWith(TEXT("mi_"));

        if (bBlueprintAsset)
        {
            Lines.Add(FString::Printf(TEXT("Blueprint Asset: %s"), *AssetName));
            Lines.Add(FString::Printf(TEXT("Blueprint Class: %s"), *AssetObject->GetClass()->GetName()));

            int32 StructuredFieldCount = 0;
            for (TFieldIterator<FProperty> It(AssetObject->GetClass(), EFieldIterationFlags::IncludeSuper); It; ++It)
            {
                FProperty* Property = *It;
                if (!Property)
                {
                    continue;
                }

                const FString PropertyName = Property->GetName();
                const FString LoweredPropertyName = PropertyName.ToLower();
                if (!(
                    LoweredPropertyName.Contains(TEXT("state")) ||
                    LoweredPropertyName.Contains(TEXT("target")) ||
                    LoweredPropertyName.Contains(TEXT("owner")) ||
                    LoweredPropertyName.Contains(TEXT("component")) ||
                    LoweredPropertyName.Contains(TEXT("widget")) ||
                    LoweredPropertyName.Contains(TEXT("class")) ||
                    LoweredPropertyName.Contains(TEXT("tag")) ||
                    LoweredPropertyName.Contains(TEXT("active")) ||
                    LoweredPropertyName.Contains(TEXT("visible")) ||
                    LoweredPropertyName.Contains(TEXT("enabled")) ||
                    LoweredPropertyName.Contains(TEXT("health")) ||
                    LoweredPropertyName.Contains(TEXT("speed"))
                ))
                {
                    continue;
                }

                Lines.Add(FString::Printf(TEXT("Blueprint Property: %s = %s"), *PropertyName, *FormatPropertyValue(Property, AssetObject)));
                ++StructuredFieldCount;
                if (StructuredFieldCount >= 8)
                {
                    break;
                }
            }
        }

        if (bInputActionAsset || bInputMappingContextAsset)
        {
            Lines.Add(bInputActionAsset
                ? FString::Printf(TEXT("Input Action: %s"), *AssetName)
                : FString::Printf(TEXT("Input Mapping Context: %s"), *AssetName));

            int32 StructuredFieldCount = 0;
            for (TFieldIterator<FProperty> It(AssetObject->GetClass(), EFieldIterationFlags::IncludeSuper); It; ++It)
            {
                FProperty* Property = *It;
                if (!Property)
                {
                    continue;
                }

                const FString PropertyName = Property->GetName();
                const FString LoweredPropertyName = PropertyName.ToLower();
                FString Label;
                if (LoweredPropertyName.Contains(TEXT("valuetype")))
                {
                    Label = TEXT("Value Type");
                }
                else if (LoweredPropertyName.Contains(TEXT("trigger")))
                {
                    Label = TEXT("Trigger");
                }
                else if (LoweredPropertyName.Contains(TEXT("modifier")))
                {
                    Label = TEXT("Modifier");
                }
                else if (LoweredPropertyName.Contains(TEXT("mapping")))
                {
                    Label = TEXT("Mapping");
                }
                else if (LoweredPropertyName.Contains(TEXT("action")))
                {
                    Label = TEXT("Action");
                }
                else if (LoweredPropertyName.Contains(TEXT("key")))
                {
                    Label = TEXT("Key");
                }
                else
                {
                    continue;
                }

                Lines.Add(FString::Printf(TEXT("%s: %s"), *Label, *FormatPropertyValue(Property, AssetObject)));
                ++StructuredFieldCount;
                if (StructuredFieldCount >= 8)
                {
                    break;
                }
            }
        }

        if (bMaterialInstanceAsset)
        {
            Lines.Add(FString::Printf(TEXT("Material Instance: %s"), *AssetName));

            int32 StructuredFieldCount = 0;
            for (TFieldIterator<FProperty> It(AssetObject->GetClass(), EFieldIterationFlags::IncludeSuper); It; ++It)
            {
                FProperty* Property = *It;
                if (!Property)
                {
                    continue;
                }

                const FString PropertyName = Property->GetName();
                const FString LoweredPropertyName = PropertyName.ToLower();
                FString Label;
                if (LoweredPropertyName.Contains(TEXT("parent")))
                {
                    Label = TEXT("Parent Material");
                }
                else if (LoweredPropertyName.Contains(TEXT("scalar")))
                {
                    Label = TEXT("Scalar Parameter");
                }
                else if (LoweredPropertyName.Contains(TEXT("vector")))
                {
                    Label = TEXT("Vector Parameter");
                }
                else if (LoweredPropertyName.Contains(TEXT("texture")))
                {
                    Label = TEXT("Texture Parameter");
                }
                else if (LoweredPropertyName.Contains(TEXT("parameter")))
                {
                    Label = TEXT("Parameter");
                }
                else if (LoweredPropertyName.Contains(TEXT("material")))
                {
                    Label = TEXT("Material Reference");
                }
                else
                {
                    continue;
                }

                Lines.Add(FString::Printf(TEXT("%s: %s"), *Label, *FormatPropertyValue(Property, AssetObject)));
                ++StructuredFieldCount;
                if (StructuredFieldCount >= 8)
                {
                    break;
                }
            }
        }

        int32 ExportedPropertyCount = 0;
        for (TFieldIterator<FProperty> It(AssetObject->GetClass(), EFieldIterationFlags::IncludeSuper); It; ++It)
        {
            FProperty* Property = *It;
            if (!Property)
            {
                continue;
            }

            const bool bInterestingProperty =
                Property->HasAnyPropertyFlags(CPF_Edit | CPF_BlueprintVisible) ||
                Property->IsA(FArrayProperty::StaticClass()) ||
                Property->IsA(FObjectPropertyBase::StaticClass()) ||
                Property->GetName().Contains(TEXT("Trigger")) ||
                Property->GetName().Contains(TEXT("Modifier")) ||
                Property->GetName().Contains(TEXT("Mapping")) ||
                Property->GetName().Contains(TEXT("Action"));

            if (!bInterestingProperty)
            {
                continue;
            }

            Lines.Add(FString::Printf(
                TEXT("Property: %s [%s] = %s"),
                *Property->GetName(),
                *Property->GetClass()->GetName(),
                *FormatPropertyValue(Property, AssetObject)));
            ++ExportedPropertyCount;

            if (ExportedPropertyCount >= 18)
            {
                Lines.Add(TEXT("Property Export: Truncated after 18 interesting properties to keep the payload compact."));
                break;
            }
        }

        if (ExportedPropertyCount == 0)
        {
            Lines.Add(TEXT("Property Export: No editor-visible or obviously relevant properties were detected; using metadata-only fallback context."));
        }

        return JoinLines(Lines);
    }

    FString BuildPluginAssetDetailsPayload(const FString& SelectionName, const FString& SelectionType, const FString& AssetPath, const FString& ClassName)
    {
        const FString ProjectPath = GetCurrentProjectPathForPayload();
        return FString::Printf(
            TEXT("{\"selection_name\":\"%s\",\"selection_type\":\"%s\",\"asset_path\":\"%s\",\"class_name\":\"%s\",\"project_path\":\"%s\",\"source\":\"ue5_plugin\"}"),
            *EscapeJson(SelectionName),
            *EscapeJson(SelectionType),
            *EscapeJson(AssetPath),
            *EscapeJson(ClassName),
            *EscapeJson(ProjectPath)
        );
    }

    FString BuildPluginAssetEditPlanPayload(const FString& SelectionName, const FString& SelectionType, const FString& AssetPath, const FString& ClassName, const FString& ChangeRequest)
    {
        const FString ProjectPath = GetCurrentProjectPathForPayload();
        return FString::Printf(
            TEXT("{\"selection_name\":\"%s\",\"selection_type\":\"%s\",\"asset_path\":\"%s\",\"class_name\":\"%s\",\"change_request\":\"%s\",\"project_path\":\"%s\",\"source\":\"ue5_plugin\"}"),
            *EscapeJson(SelectionName),
            *EscapeJson(SelectionType),
            *EscapeJson(AssetPath),
            *EscapeJson(ClassName),
            *EscapeJson(ChangeRequest),
            *EscapeJson(ProjectPath)
        );
    }

    FString BuildAssetScaffoldPayload(const FString& AssetKind, const FString& Name, const FString& Purpose, const FString& ClassName)
    {
        return FString::Printf(
            TEXT("{\"asset_kind\":\"%s\",\"name\":\"%s\",\"purpose\":\"%s\",\"class_name\":\"%s\"}"),
            *EscapeJson(AssetKind),
            *EscapeJson(Name),
            *EscapeJson(Purpose),
            *EscapeJson(ClassName)
        );
    }

    FString BuildAgentTaskPayload(const FString& Goal)
    {
        const FString ProjectPath = GetCurrentProjectPathForPayload();
        return FString::Printf(
            TEXT("{\"goal\":\"%s\",\"project_path\":\"%s\"}"),
            *EscapeJson(Goal),
            *EscapeJson(ProjectPath)
        );
    }

    FString BuildAgentDecisionPayload(const FString& Decision)
    {
        return FString::Printf(
            TEXT("{\"decision\":\"%s\"}"),
            *EscapeJson(Decision)
        );
    }

    FString BuildCodePatchPlanPayload(const FString& Goal, const FString& TargetPath)
    {
        return FString::Printf(
            TEXT("{\"goal\":\"%s\",\"target_path\":\"%s\"}"),
            *EscapeJson(Goal),
            *EscapeJson(TargetPath)
        );
    }

    FString HashStringAsMd5(const FString& Content)
    {
        FTCHARToUTF8 Utf8(*Content);
        return FMD5::HashBytes(reinterpret_cast<const uint8*>(Utf8.Get()), Utf8.Length());
    }

    bool ApplyPreviewCodePatch(const FString& TargetPath, const FString& EditKind, const FString& OriginalContentHash, const FString& UpdatedContent, FString& OutError)
    {
        const FString NormalizedTarget = TargetPath.TrimStartAndEnd().Replace(TEXT("/"), TEXT("\\"));
        if (NormalizedTarget.IsEmpty() || OriginalContentHash.IsEmpty() || UpdatedContent.IsEmpty())
        {
            OutError = TEXT("Code patch application requires a target path, original content hash, and updated content.");
            return false;
        }

        if (EditKind != TEXT("header_additions") && EditKind != TEXT("source_additions"))
        {
            OutError = FString::Printf(TEXT("Code patch apply is not enabled yet for `%s`."), *EditKind);
            return false;
        }

        if (!(NormalizedTarget.EndsWith(TEXT(".h")) || NormalizedTarget.EndsWith(TEXT(".cpp"))))
        {
            OutError = TEXT("Only .h and .cpp preview patches can be applied right now.");
            return false;
        }

        FString ProjectRoot = FPaths::ConvertRelativePathToFull(FPaths::ProjectDir());
        FString AbsoluteTarget = FPaths::ConvertRelativePathToFull(FPaths::Combine(ProjectRoot, NormalizedTarget));
        FPaths::NormalizeFilename(ProjectRoot);
        FPaths::NormalizeFilename(AbsoluteTarget);
        if (!AbsoluteTarget.StartsWith(ProjectRoot))
        {
            OutError = TEXT("The previewed code patch target resolves outside the current Unreal project.");
            return false;
        }

        if (!FPaths::FileExists(AbsoluteTarget))
        {
            OutError = FString::Printf(TEXT("The target source file `%s` does not exist under the current project."), *NormalizedTarget);
            return false;
        }

        FString CurrentContent;
        if (!FFileHelper::LoadFileToString(CurrentContent, *AbsoluteTarget))
        {
            OutError = FString::Printf(TEXT("Failed to read the current contents of `%s` before applying the previewed patch."), *NormalizedTarget);
            return false;
        }

        const FString CurrentHash = HashStringAsMd5(CurrentContent);
        if (!CurrentHash.Equals(OriginalContentHash, ESearchCase::IgnoreCase))
        {
            OutError = FString::Printf(TEXT("The target file `%s` changed after the diff was drafted. Draft a fresh code diff before applying."), *NormalizedTarget);
            return false;
        }

        if (!FFileHelper::SaveStringToFile(UpdatedContent, *AbsoluteTarget))
        {
            OutError = FString::Printf(TEXT("Failed to write the previewed code patch to `%s`."), *NormalizedTarget);
            return false;
        }

        return true;
    }

    bool ApplyPreviewCodePatchBundle(const TArray<TSharedPtr<FJsonValue>>& FileEntries, FString& OutError)
    {
        if (FileEntries.Num() == 0)
        {
            OutError = TEXT("The code patch bundle action did not include any files.");
            return false;
        }

        for (const TSharedPtr<FJsonValue>& EntryValue : FileEntries)
        {
            const TSharedPtr<FJsonObject> EntryObject = EntryValue.IsValid() ? EntryValue->AsObject() : nullptr;
            if (!EntryObject.IsValid())
            {
                OutError = TEXT("One of the code patch bundle entries was invalid.");
                return false;
            }

            FString TargetPath;
            FString EditKind;
            FString OriginalContentHash;
            FString UpdatedContent;
            EntryObject->TryGetStringField(TEXT("target_path"), TargetPath);
            EntryObject->TryGetStringField(TEXT("edit_kind"), EditKind);
            EntryObject->TryGetStringField(TEXT("original_content_hash"), OriginalContentHash);
            EntryObject->TryGetStringField(TEXT("updated_content"), UpdatedContent);

            if (!ApplyPreviewCodePatch(TargetPath, EditKind, OriginalContentHash, UpdatedContent, OutError))
            {
                return false;
            }
        }

        return true;
    }

    FString BuildCodePatchBundleDiffPreview(const TArray<TSharedPtr<FJsonValue>>& FileEntries)
    {
        TArray<FString> Diffs;
        for (const TSharedPtr<FJsonValue>& EntryValue : FileEntries)
        {
            const TSharedPtr<FJsonObject> EntryObject = EntryValue.IsValid() ? EntryValue->AsObject() : nullptr;
            if (!EntryObject.IsValid())
            {
                continue;
            }

            FString UnifiedDiff;
            if (EntryObject->TryGetStringField(TEXT("unified_diff"), UnifiedDiff) && !UnifiedDiff.IsEmpty())
            {
                Diffs.Add(UnifiedDiff);
            }
        }
        return Diffs.Num() > 0 ? FString::Join(Diffs, TEXT("\n\n")) : TEXT("No code diff preview yet.");
    }

    int32 FindCodePatchBundleEntryIndex(const TArray<TSharedPtr<FJsonValue>>& FileEntries, const FString& TargetPath)
    {
        const FString NormalizedTarget = TargetPath.TrimStartAndEnd().Replace(TEXT("/"), TEXT("\\"));
        if (NormalizedTarget.IsEmpty())
        {
            return INDEX_NONE;
        }

        for (int32 Index = 0; Index < FileEntries.Num(); ++Index)
        {
            const TSharedPtr<FJsonObject> EntryObject = FileEntries[Index].IsValid() ? FileEntries[Index]->AsObject() : nullptr;
            if (!EntryObject.IsValid())
            {
                continue;
            }

            FString EntryTargetPath;
            if (!EntryObject->TryGetStringField(TEXT("target_path"), EntryTargetPath))
            {
                continue;
            }

            const FString NormalizedEntry = EntryTargetPath.TrimStartAndEnd().Replace(TEXT("/"), TEXT("\\"));
            if (NormalizedEntry.Equals(NormalizedTarget, ESearchCase::IgnoreCase))
            {
                return Index;
            }
        }

        return INDEX_NONE;
    }

    FString BuildCodePatchBundleActionJson(const TArray<TSharedPtr<FJsonValue>>& FileEntries)
    {
        if (FileEntries.Num() == 0)
        {
            return FString();
        }

        const TSharedPtr<FJsonObject> ArgumentsObject = MakeShared<FJsonObject>();
        ArgumentsObject->SetArrayField(TEXT("files"), FileEntries);

        const TSharedPtr<FJsonObject> ActionObject = MakeShared<FJsonObject>();
        ActionObject->SetStringField(TEXT("action_type"), TEXT("apply_code_patch_bundle_preview"));
        ActionObject->SetBoolField(TEXT("dry_run"), false);
        ActionObject->SetBoolField(TEXT("requires_user_confirmation"), true);
        ActionObject->SetObjectField(TEXT("arguments"), ArgumentsObject);
        return SerializeJsonObject(ActionObject);
    }

    FString BuildEditorActionPreviewFromSerializedAction(const FString& SerializedActionJson)
    {
        if (SerializedActionJson.IsEmpty())
        {
            return TEXT("No editor action proposed yet.");
        }

        TSharedPtr<FJsonObject> ActionObject;
        const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(SerializedActionJson);
        if (!FJsonSerializer::Deserialize(Reader, ActionObject) || !ActionObject.IsValid())
        {
            return TEXT("No editor action proposed yet.");
        }

        const TSharedPtr<FJsonObject> WrapperObject = MakeShared<FJsonObject>();
        WrapperObject->SetObjectField(TEXT("editor_action"), ActionObject);
        return FormatEditorActionPreview(WrapperObject);
    }

    FString GetFirstCodePatchBundleTargetPath(const TArray<TSharedPtr<FJsonValue>>& FileEntries)
    {
        for (const TSharedPtr<FJsonValue>& EntryValue : FileEntries)
        {
            const TSharedPtr<FJsonObject> EntryObject = EntryValue.IsValid() ? EntryValue->AsObject() : nullptr;
            if (!EntryObject.IsValid())
            {
                continue;
            }

            FString TargetPath;
            if (EntryObject->TryGetStringField(TEXT("target_path"), TargetPath) && !TargetPath.IsEmpty())
            {
                return TargetPath;
            }
        }

        return FString();
    }

    TArray<FString> ExtractCodePatchBundleTargetPaths(const TArray<TSharedPtr<FJsonValue>>& FileEntries)
    {
        TArray<FString> TargetPaths;
        for (const TSharedPtr<FJsonValue>& EntryValue : FileEntries)
        {
            const TSharedPtr<FJsonObject> EntryObject = EntryValue.IsValid() ? EntryValue->AsObject() : nullptr;
            if (!EntryObject.IsValid())
            {
                continue;
            }

            FString TargetPath;
            if (EntryObject->TryGetStringField(TEXT("target_path"), TargetPath) && !TargetPath.IsEmpty())
            {
                TargetPaths.Add(TargetPath);
            }
        }
        return TargetPaths;
    }

    FString JsonValueToCompactString(const TSharedPtr<FJsonValue>& Value)
    {
        if (!Value.IsValid())
        {
            return TEXT("None");
        }

        switch (Value->Type)
        {
        case EJson::String:
            return Value->AsString();
        case EJson::Number:
            return FString::SanitizeFloat(Value->AsNumber());
        case EJson::Boolean:
            return Value->AsBool() ? TEXT("true") : TEXT("false");
        case EJson::Array:
        {
            TArray<FString> Parts;
            for (const TSharedPtr<FJsonValue>& Entry : Value->AsArray())
            {
                Parts.Add(JsonValueToCompactString(Entry));
            }
            return FString::Printf(TEXT("[%s]"), *FString::Join(Parts, TEXT(", ")));
        }
        case EJson::Object:
        {
            FString PrettyJson;
            TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&PrettyJson);
            FJsonSerializer::Serialize(Value->AsObject().ToSharedRef(), Writer);
            return PrettyJson;
        }
        case EJson::Null:
        default:
            return TEXT("None");
        }
    }

    void AppendStringArrayField(const TSharedPtr<FJsonObject>& JsonObject, const FString& FieldName, const FString& Label, TArray<FString>& Lines)
    {
        const TArray<TSharedPtr<FJsonValue>>* Items = nullptr;
        if (!JsonObject.IsValid() || !JsonObject->TryGetArrayField(FieldName, Items) || !Items || Items->Num() == 0)
        {
            return;
        }

        Lines.Add(FString::Printf(TEXT("%s:"), *Label));
        for (const TSharedPtr<FJsonValue>& Item : *Items)
        {
            Lines.Add(FString::Printf(TEXT("- %s"), *JsonValueToCompactString(Item)));
        }
    }

    FString FormatStructuredPayload(const TSharedPtr<FJsonObject>& JsonObject)
    {
        if (!JsonObject.IsValid())
        {
            return TEXT("");
        }

        TArray<FString> Lines;
        const TSharedPtr<FJsonObject>* PayloadObject = nullptr;
        const TSharedPtr<FJsonObject> SourceObject = JsonObject->TryGetObjectField(TEXT("payload"), PayloadObject) && PayloadObject ? *PayloadObject : JsonObject;

        auto AddIfPresent = [&SourceObject, &Lines](const FString& FieldName, const FString& Label)
        {
            FString Value;
            if (SourceObject.IsValid() && SourceObject->TryGetStringField(FieldName, Value) && !Value.IsEmpty())
            {
                Lines.Add(FString::Printf(TEXT("%s: %s"), *Label, *Value));
            }
        };

        AddIfPresent(TEXT("title"), TEXT("Title"));
        AddIfPresent(TEXT("summary"), TEXT("Summary"));
        AddIfPresent(TEXT("asset_kind"), TEXT("Kind"));
        AddIfPresent(TEXT("recommended_asset_name"), TEXT("Recommended Asset"));
        AddIfPresent(TEXT("recommended_asset_path"), TEXT("Recommended Path"));
        AddIfPresent(TEXT("recommended_class_name"), TEXT("Recommended Class"));
        AddIfPresent(TEXT("recommended_parent_class"), TEXT("Recommended Parent"));
        AddIfPresent(TEXT("asset_name"), TEXT("Asset"));
        AddIfPresent(TEXT("asset_path"), TEXT("Path"));
        AddIfPresent(TEXT("linked_cpp_owner"), TEXT("Linked Owner"));
        AddIfPresent(TEXT("suggested_new_name"), TEXT("Suggested New Name"));
        AddIfPresent(TEXT("suggested_variable_type"), TEXT("Suggested Variable Type"));
        AddIfPresent(TEXT("suggested_function_name"), TEXT("Suggested Function"));
        AddIfPresent(TEXT("suggested_function_signature"), TEXT("Suggested Signature"));
        AddIfPresent(TEXT("suggested_parameter_name"), TEXT("Suggested Parameter"));
        AddIfPresent(TEXT("suggested_parameter_type"), TEXT("Suggested Parameter Type"));
        AddIfPresent(TEXT("suggested_node_kind"), TEXT("Suggested Node Kind"));
        AddIfPresent(TEXT("suggested_node_name"), TEXT("Suggested Node Name"));
        AddIfPresent(TEXT("change_request"), TEXT("Requested Change"));
        AddIfPresent(TEXT("resolved_asset_kind"), TEXT("Resolved Kind"));
        AddIfPresent(TEXT("selection_name"), TEXT("Selection"));
        AddIfPresent(TEXT("task_id"), TEXT("Task ID"));
        AddIfPresent(TEXT("status"), TEXT("Status"));
        AddIfPresent(TEXT("task_kind"), TEXT("Task Kind"));
        AddIfPresent(TEXT("execution_mode"), TEXT("Execution Mode"));
        AddIfPresent(TEXT("next_action"), TEXT("Next Action"));
        AddIfPresent(TEXT("edit_summary"), TEXT("Edit Summary"));
        AddIfPresent(TEXT("original_content_hash"), TEXT("Original Content Hash"));

        AppendStringArrayField(SourceObject, TEXT("what_to_change"), TEXT("What To Change"), Lines);
        AppendStringArrayField(SourceObject, TEXT("fields_to_check"), TEXT("Fields To Check"), Lines);
        AppendStringArrayField(SourceObject, TEXT("risks"), TEXT("Risks"), Lines);
        AppendStringArrayField(SourceObject, TEXT("validation_steps"), TEXT("Validation Steps"), Lines);
        AppendStringArrayField(SourceObject, TEXT("key_elements"), TEXT("Key Elements"), Lines);
        AppendStringArrayField(SourceObject, TEXT("flow_summary"), TEXT("Flow Summary"), Lines);
        AppendStringArrayField(SourceObject, TEXT("what_looks_wrong"), TEXT("What Looks Wrong"), Lines);
        AppendStringArrayField(SourceObject, TEXT("what_is_missing"), TEXT("What Is Missing"), Lines);
        AppendStringArrayField(SourceObject, TEXT("steps"), TEXT("Steps"), Lines);

        const TArray<TSharedPtr<FJsonValue>>* StepObjects = nullptr;
        if (SourceObject.IsValid() && SourceObject->TryGetArrayField(TEXT("steps"), StepObjects) && StepObjects && StepObjects->Num() > 0)
        {
            Lines.Add(TEXT("Agent Steps:"));
            for (const TSharedPtr<FJsonValue>& StepValue : *StepObjects)
            {
                const TSharedPtr<FJsonObject> StepObject = StepValue.IsValid() ? StepValue->AsObject() : nullptr;
                if (!StepObject.IsValid())
                {
                    continue;
                }

                FString ToolName;
                FString Status;
                FString Summary;
                StepObject->TryGetStringField(TEXT("tool_name"), ToolName);
                StepObject->TryGetStringField(TEXT("status"), Status);
                StepObject->TryGetStringField(TEXT("summary"), Summary);
                if (!ToolName.IsEmpty() || !Summary.IsEmpty())
                {
                    Lines.Add(FString::Printf(TEXT("- [%s] %s: %s"), *Status, *ToolName, *Summary));
                }
            }
        }

        const TSharedPtr<FJsonObject>* PendingConfirmationObject = nullptr;
        if (SourceObject.IsValid()
            && SourceObject->TryGetObjectField(TEXT("pending_confirmation"), PendingConfirmationObject)
            && PendingConfirmationObject
            && PendingConfirmationObject->IsValid())
        {
            FString Message;
            if ((*PendingConfirmationObject)->TryGetStringField(TEXT("message"), Message) && !Message.IsEmpty())
            {
                Lines.Add(FString::Printf(TEXT("Pending Confirmation: %s"), *Message));
            }
        }

        const TArray<TSharedPtr<FJsonValue>>* Files = nullptr;
        if (SourceObject.IsValid() && SourceObject->TryGetArrayField(TEXT("files"), Files) && Files && Files->Num() > 0)
        {
            Lines.Add(TEXT("Starter Files:"));
            for (const TSharedPtr<FJsonValue>& FileValue : *Files)
            {
                const TSharedPtr<FJsonObject> FileObject = FileValue.IsValid() ? FileValue->AsObject() : nullptr;
                if (FileObject.IsValid())
                {
                    const FString Label = FileObject->GetStringField(TEXT("label"));
                    Lines.Add(FString::Printf(TEXT("- %s"), *Label));
                }
            }
        }

        return JoinLines(Lines);
    }

    FString ExtractUnifiedDiff(const TSharedPtr<FJsonObject>& JsonObject)
    {
        if (!JsonObject.IsValid())
        {
            return TEXT("No code diff preview yet.");
        }

        const TSharedPtr<FJsonObject>* PayloadObject = nullptr;
        const TSharedPtr<FJsonObject> SourceObject = JsonObject->TryGetObjectField(TEXT("payload"), PayloadObject) && PayloadObject ? *PayloadObject : JsonObject;
        FString CombinedUnifiedDiff;
        if (SourceObject.IsValid() && SourceObject->TryGetStringField(TEXT("combined_unified_diff"), CombinedUnifiedDiff) && !CombinedUnifiedDiff.IsEmpty())
        {
            return CombinedUnifiedDiff;
        }
        FString UnifiedDiff;
        if (SourceObject.IsValid() && SourceObject->TryGetStringField(TEXT("unified_diff"), UnifiedDiff) && !UnifiedDiff.IsEmpty())
        {
            return UnifiedDiff;
        }

        return TEXT("No code diff preview yet.");
    }

    FString FormatEditorActionPreview(const TSharedPtr<FJsonObject>& JsonObject)
    {
        if (!JsonObject.IsValid())
        {
            return TEXT("No editor action proposed yet.");
        }

        const TSharedPtr<FJsonObject>* EditorActionObject = nullptr;
        if (!JsonObject->TryGetObjectField(TEXT("editor_action"), EditorActionObject) || !EditorActionObject || !EditorActionObject->IsValid())
        {
            return TEXT("No editor action proposed yet.");
        }

        TArray<FString> Lines;
        FString ActionType;
        if ((*EditorActionObject)->TryGetStringField(TEXT("action_type"), ActionType))
        {
            Lines.Add(FString::Printf(TEXT("Action Type: %s"), *ActionType));
        }

        if (ActionType == TEXT("apply_code_patch_bundle_preview"))
        {
            const TSharedPtr<FJsonObject>* ArgumentsObject = nullptr;
            const TArray<TSharedPtr<FJsonValue>>* FileEntries = nullptr;
            if ((*EditorActionObject)->TryGetObjectField(TEXT("arguments"), ArgumentsObject) && ArgumentsObject && ArgumentsObject->IsValid()
                && (*ArgumentsObject)->TryGetArrayField(TEXT("files"), FileEntries) && FileEntries)
            {
                Lines.Add(FString::Printf(TEXT("Bundle Files: %d"), FileEntries->Num()));
                for (const TSharedPtr<FJsonValue>& EntryValue : *FileEntries)
                {
                    const TSharedPtr<FJsonObject> EntryObject = EntryValue.IsValid() ? EntryValue->AsObject() : nullptr;
                    if (!EntryObject.IsValid())
                    {
                        continue;
                    }

                    FString TargetPath;
                    FString EditKind;
                    EntryObject->TryGetStringField(TEXT("target_path"), TargetPath);
                    EntryObject->TryGetStringField(TEXT("edit_kind"), EditKind);
                    if (!TargetPath.IsEmpty())
                    {
                        Lines.Add(FString::Printf(TEXT("- %s (%s)"), *TargetPath, EditKind.IsEmpty() ? TEXT("unknown") : *EditKind));
                    }
                }
            }
        }

        bool bDryRun = false;
        if ((*EditorActionObject)->TryGetBoolField(TEXT("dry_run"), bDryRun))
        {
            Lines.Add(FString::Printf(TEXT("Dry Run: %s"), bDryRun ? TEXT("true") : TEXT("false")));
        }

        bool bRequiresConfirmation = false;
        if ((*EditorActionObject)->TryGetBoolField(TEXT("requires_user_confirmation"), bRequiresConfirmation))
        {
            Lines.Add(FString::Printf(TEXT("Requires Confirmation: %s"), bRequiresConfirmation ? TEXT("true") : TEXT("false")));
        }

        const TSharedPtr<FJsonObject>* ArgumentsObject = nullptr;
        if ((*EditorActionObject)->TryGetObjectField(TEXT("arguments"), ArgumentsObject) && ArgumentsObject && ArgumentsObject->IsValid())
        {
            Lines.Add(TEXT("Arguments:"));
            for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*ArgumentsObject)->Values)
            {
                Lines.Add(FString::Printf(TEXT("- %s: %s"), *Pair.Key, *JsonValueToCompactString(Pair.Value)));
            }
        }

        return JoinLines(Lines);
    }

    TSharedPtr<FJsonObject> ExtractPreviewEditorAction(const TSharedPtr<FJsonObject>& JsonObject)
    {
        if (!JsonObject.IsValid())
        {
            return nullptr;
        }

        const TSharedPtr<FJsonObject>* EditorActionObject = nullptr;
        if (JsonObject->TryGetObjectField(TEXT("editor_action"), EditorActionObject) && EditorActionObject && EditorActionObject->IsValid())
        {
            return *EditorActionObject;
        }

        const TSharedPtr<FJsonObject>* PendingConfirmationObject = nullptr;
        const TSharedPtr<FJsonObject>* PendingConfirmationEditorAction = nullptr;
        if (JsonObject->TryGetObjectField(TEXT("pending_confirmation"), PendingConfirmationObject)
            && PendingConfirmationObject
            && PendingConfirmationObject->IsValid()
            && (*PendingConfirmationObject)->TryGetObjectField(TEXT("editor_action"), PendingConfirmationEditorAction)
            && PendingConfirmationEditorAction
            && PendingConfirmationEditorAction->IsValid())
        {
            return *PendingConfirmationEditorAction;
        }

        const TSharedPtr<FJsonObject>* ApprovedEditorActionObject = nullptr;
        if (JsonObject->TryGetObjectField(TEXT("approved_editor_action"), ApprovedEditorActionObject)
            && ApprovedEditorActionObject
            && ApprovedEditorActionObject->IsValid())
        {
            return *ApprovedEditorActionObject;
        }

        const TSharedPtr<FJsonObject>* ResultObject = nullptr;
        const TSharedPtr<FJsonObject>* ResultApprovedEditorActionObject = nullptr;
        if (JsonObject->TryGetObjectField(TEXT("result"), ResultObject)
            && ResultObject
            && ResultObject->IsValid()
            && (*ResultObject)->TryGetObjectField(TEXT("approved_editor_action"), ResultApprovedEditorActionObject)
            && ResultApprovedEditorActionObject
            && ResultApprovedEditorActionObject->IsValid())
        {
            return *ResultApprovedEditorActionObject;
        }

        return nullptr;
    }

    void SyncPreviewEditorAction(
        const TSharedPtr<FJsonObject>& JsonObject,
        const TSharedPtr<SEditableTextBox>& BundleApplyTargetPathTextBox,
        FString* PendingEditorActionJsonPtr,
        FString& EditorActionPreview)
    {
        if (!PendingEditorActionJsonPtr)
        {
            return;
        }

        const TSharedPtr<FJsonObject> PreviewEditorAction = ExtractPreviewEditorAction(JsonObject);
        if (!PreviewEditorAction.IsValid())
        {
            PendingEditorActionJsonPtr->Reset();
            if (FUE5CopilotAssistantModule* Module = FModuleManager::GetModulePtr<FUE5CopilotAssistantModule>(TEXT("UE5CopilotAssistant")))
            {
                Module->ClearPendingCodePatchBundleTargets();
            }
            return;
        }

        *PendingEditorActionJsonPtr = SerializeJsonObject(PreviewEditorAction);
        const TSharedPtr<FJsonObject> WrapperObject = MakeShared<FJsonObject>();
        WrapperObject->SetObjectField(TEXT("editor_action"), PreviewEditorAction);
        EditorActionPreview = FormatEditorActionPreview(WrapperObject);

        FString ActionType;
        if (BundleApplyTargetPathTextBox.IsValid()
            && PreviewEditorAction->TryGetStringField(TEXT("action_type"), ActionType)
            && ActionType == TEXT("apply_code_patch_bundle_preview"))
        {
            const TSharedPtr<FJsonObject>* ArgumentsObject = nullptr;
            const TArray<TSharedPtr<FJsonValue>>* FileEntries = nullptr;
            if (PreviewEditorAction->TryGetObjectField(TEXT("arguments"), ArgumentsObject) && ArgumentsObject && ArgumentsObject->IsValid()
                && (*ArgumentsObject)->TryGetArrayField(TEXT("files"), FileEntries) && FileEntries)
            {
                if (FUE5CopilotAssistantModule* Module = FModuleManager::GetModulePtr<FUE5CopilotAssistantModule>(TEXT("UE5CopilotAssistant")))
                {
                    Module->RefreshPendingCodePatchBundleTargets(UE5CopilotAssistant::ExtractCodePatchBundleTargetPaths(*FileEntries));
                }
                return;
            }
        }

        if (FUE5CopilotAssistantModule* Module = FModuleManager::GetModulePtr<FUE5CopilotAssistantModule>(TEXT("UE5CopilotAssistant")))
        {
            Module->ClearPendingCodePatchBundleTargets();
        }
    }

    FString FormatAgentSessionPreview(const TSharedPtr<FJsonObject>& JsonObject)
    {
        if (!JsonObject.IsValid() || !JsonObject->HasField(TEXT("task_id")))
        {
            return TEXT("No live agent session yet.");
        }

        TArray<FString> Lines;
        FString TaskId;
        FString Status;
        FString NextAction;
        JsonObject->TryGetStringField(TEXT("task_id"), TaskId);
        JsonObject->TryGetStringField(TEXT("status"), Status);

        const TSharedPtr<FJsonObject>* ResultObject = nullptr;
        if (JsonObject->TryGetObjectField(TEXT("result"), ResultObject) && ResultObject && ResultObject->IsValid())
        {
            (*ResultObject)->TryGetStringField(TEXT("next_action"), NextAction);
        }

        if (!TaskId.IsEmpty())
        {
            Lines.Add(FString::Printf(TEXT("Task ID: %s"), *TaskId));
        }
        if (!Status.IsEmpty())
        {
            Lines.Add(FString::Printf(TEXT("Status: %s"), *Status));
        }
        if (!NextAction.IsEmpty())
        {
            Lines.Add(FString::Printf(TEXT("Next Action: %s"), *NextAction));
        }

        FString ApprovedActionType;
        const TSharedPtr<FJsonObject> ApprovedEditorAction = ExtractPreviewEditorAction(JsonObject);
        if (ApprovedEditorAction.IsValid()
            && ApprovedEditorAction->TryGetStringField(TEXT("action_type"), ApprovedActionType)
            && !ApprovedActionType.IsEmpty())
        {
            Lines.Add(FString::Printf(TEXT("Previewed Action: %s"), *ApprovedActionType));
        }

        const TSharedPtr<FJsonObject>* PendingConfirmationObject = nullptr;
        if (JsonObject->TryGetObjectField(TEXT("pending_confirmation"), PendingConfirmationObject) && PendingConfirmationObject && PendingConfirmationObject->IsValid())
        {
            FString PendingMessage;
            if ((*PendingConfirmationObject)->TryGetStringField(TEXT("message"), PendingMessage) && !PendingMessage.IsEmpty())
            {
                Lines.Add(FString::Printf(TEXT("Pending Confirmation: %s"), *PendingMessage));
            }
        }

        const TArray<TSharedPtr<FJsonValue>>* StepObjects = nullptr;
        if (JsonObject->TryGetArrayField(TEXT("steps"), StepObjects) && StepObjects && StepObjects->Num() > 0)
        {
            const TSharedPtr<FJsonObject> LatestStep = (*StepObjects)[StepObjects->Num() - 1].IsValid() ? (*StepObjects)[StepObjects->Num() - 1]->AsObject() : nullptr;
            if (LatestStep.IsValid())
            {
                FString ToolName;
                FString StepStatus;
                FString Summary;
                LatestStep->TryGetStringField(TEXT("tool_name"), ToolName);
                LatestStep->TryGetStringField(TEXT("status"), StepStatus);
                LatestStep->TryGetStringField(TEXT("summary"), Summary);
                if (!ToolName.IsEmpty() || !Summary.IsEmpty())
                {
                    Lines.Add(FString::Printf(TEXT("Latest Step: [%s] %s"), *StepStatus, *ToolName));
                    Lines.Add(Summary);
                }
            }
        }

        return Lines.Num() > 0 ? JoinLines(Lines) : TEXT("No live agent session yet.");
    }

    FString SerializeJsonObject(const TSharedPtr<FJsonObject>& JsonObject)
    {
        if (!JsonObject.IsValid())
        {
            return FString();
        }

        FString Output;
        TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
        FJsonSerializer::Serialize(JsonObject.ToSharedRef(), Writer);
        return Output;
    }

    void HandleJsonResponse(
        const FString& ResponseText,
        const TSharedPtr<SMultiLineEditableTextBox>& OutputTextBox,
        const TSharedPtr<SMultiLineEditableTextBox>& AgentSessionTextBox,
        const TSharedPtr<SMultiLineEditableTextBox>& CodeDiffPreviewTextBox,
        const TSharedPtr<SMultiLineEditableTextBox>& EditorActionPreviewTextBox,
        const TSharedPtr<SEditableTextBox>& BundleApplyTargetPathTextBox,
        FString* PendingEditorActionJsonPtr,
        const TSharedPtr<STextBlock>& StatusText)
    {
        TSharedPtr<FJsonObject> JsonObject;
        TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(ResponseText);
        FString DisplayText = ResponseText;
        FString AgentSessionPreview = TEXT("No live agent session yet.");
        FString CodeDiffPreview = TEXT("No code diff preview yet.");
        FString EditorActionPreview = TEXT("No editor action proposed yet.");

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
                const FString StructuredText = FormatStructuredPayload(JsonObject);
                if (!StructuredText.IsEmpty())
                {
                    DisplayText = StructuredText;
                }
                else
                {
                    FString PrettyJson;
                    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&PrettyJson);
                    FJsonSerializer::Serialize(JsonObject.ToSharedRef(), Writer);
                    DisplayText = PrettyJson;
                }
            }

            AgentSessionPreview = FormatAgentSessionPreview(JsonObject);
            CodeDiffPreview = ExtractUnifiedDiff(JsonObject);
            if (FUE5CopilotAssistantModule* Module = FModuleManager::GetModulePtr<FUE5CopilotAssistantModule>(TEXT("UE5CopilotAssistant")))
            {
                FString TaskId;
                if (JsonObject->TryGetStringField(TEXT("task_id"), TaskId) && !TaskId.IsEmpty())
                {
                    Module->SetCurrentAgentTaskId(TaskId);
                }
                else
                {
                    Module->ClearCurrentAgentTaskId();
                }
            }
            SyncPreviewEditorAction(JsonObject, BundleApplyTargetPathTextBox, PendingEditorActionJsonPtr, EditorActionPreview);
        }
        else if (PendingEditorActionJsonPtr)
        {
            PendingEditorActionJsonPtr->Reset();
            if (FUE5CopilotAssistantModule* Module = FModuleManager::GetModulePtr<FUE5CopilotAssistantModule>(TEXT("UE5CopilotAssistant")))
            {
                Module->ClearCurrentAgentTaskId();
                Module->ClearPendingCodePatchBundleTargets();
            }
        }

        if (OutputTextBox.IsValid())
        {
            OutputTextBox->SetText(FText::FromString(DisplayText));
        }
        if (AgentSessionTextBox.IsValid())
        {
            AgentSessionTextBox->SetText(FText::FromString(AgentSessionPreview));
        }
        if (CodeDiffPreviewTextBox.IsValid())
        {
            CodeDiffPreviewTextBox->SetText(FText::FromString(CodeDiffPreview));
        }
        if (EditorActionPreviewTextBox.IsValid())
        {
            EditorActionPreviewTextBox->SetText(FText::FromString(EditorActionPreview));
        }

        if (StatusText.IsValid())
        {
            StatusText->SetText(LOCTEXT("UE5CopilotStatusDone", "Response received."));
        }
    }

    void SendPostRequest(
        const FString& Url,
        const FString& Payload,
        const TSharedPtr<SMultiLineEditableTextBox>& OutputTextBox,
        const TSharedPtr<SMultiLineEditableTextBox>& AgentSessionTextBox,
        const TSharedPtr<SMultiLineEditableTextBox>& CodeDiffPreviewTextBox,
        const TSharedPtr<SMultiLineEditableTextBox>& EditorActionPreviewTextBox,
        const TSharedPtr<SEditableTextBox>& BundleApplyTargetPathTextBox,
        FString* PendingEditorActionJsonPtr,
        const TSharedPtr<STextBlock>& StatusText)
    {
        TSharedRef<IHttpRequest, ESPMode::ThreadSafe> Request = FHttpModule::Get().CreateRequest();
        Request->SetURL(Url);
        Request->SetVerb(TEXT("POST"));
        Request->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
        Request->SetContentAsString(Payload);

        Request->OnProcessRequestComplete().BindLambda(
            [OutputTextBox, AgentSessionTextBox, CodeDiffPreviewTextBox, EditorActionPreviewTextBox, BundleApplyTargetPathTextBox, PendingEditorActionJsonPtr, StatusText](FHttpRequestPtr HttpRequest, FHttpResponsePtr HttpResponse, bool bSucceeded)
            {
                if (!bSucceeded || !HttpResponse.IsValid())
                {
                    if (StatusText.IsValid())
                    {
                        StatusText->SetText(LOCTEXT("UE5CopilotStatusFailed", "Request failed. Make sure the backend is running."));
                    }
                    if (CodeDiffPreviewTextBox.IsValid())
                    {
                        CodeDiffPreviewTextBox->SetText(LOCTEXT("UE5CopilotCodeDiffPreviewFailed", "No code diff preview available because the request failed."));
                    }
                    if (AgentSessionTextBox.IsValid())
                    {
                        AgentSessionTextBox->SetText(LOCTEXT("UE5CopilotAgentSessionFailed", "No live agent session available because the request failed."));
                    }
                    if (EditorActionPreviewTextBox.IsValid())
                    {
                        EditorActionPreviewTextBox->SetText(LOCTEXT("UE5CopilotEditorActionPreviewFailed", "No editor action preview available because the request failed."));
                    }
                    if (PendingEditorActionJsonPtr)
                    {
                        PendingEditorActionJsonPtr->Reset();
                    }
                    if (FUE5CopilotAssistantModule* Module = FModuleManager::GetModulePtr<FUE5CopilotAssistantModule>(TEXT("UE5CopilotAssistant")))
                    {
                        Module->ClearPendingCodePatchBundleTargets();
                    }
                    return;
                }

                HandleJsonResponse(HttpResponse->GetContentAsString(), OutputTextBox, AgentSessionTextBox, CodeDiffPreviewTextBox, EditorActionPreviewTextBox, BundleApplyTargetPathTextBox, PendingEditorActionJsonPtr, StatusText);
            }
        );

        Request->ProcessRequest();
    }

    bool GetSelectedAssetData(FAssetData& OutAssetData)
    {
        FContentBrowserModule& ContentBrowserModule = FModuleManager::LoadModuleChecked<FContentBrowserModule>(TEXT("ContentBrowser"));
        TArray<FAssetData> SelectedAssets;
        ContentBrowserModule.Get().GetSelectedAssets(SelectedAssets);
        if (SelectedAssets.Num() == 0)
        {
            return false;
        }

        OutAssetData = SelectedAssets[0];
        return true;
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

        FAssetData AssetData;
        if (GetSelectedAssetData(AssetData))
        {
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
    LoadSettings();

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
    SaveSettings();
    UToolMenus::UnRegisterStartupCallback(this);
    UToolMenus::UnregisterOwner(this);
    FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(UE5CopilotAssistantTabName);
}

void FUE5CopilotAssistantModule::LoadSettings()
{
    FString SavedBackendBaseUrl;
    if (GConfig && GConfig->GetString(UE5CopilotSettingsSection, UE5CopilotBackendUrlKey, SavedBackendBaseUrl, GEditorPerProjectIni))
    {
        const FString NormalizedUrl = UE5CopilotAssistant::NormalizeBaseUrl(SavedBackendBaseUrl);
        if (!NormalizedUrl.IsEmpty())
        {
            CurrentBackendBaseUrl = NormalizedUrl;
        }
    }

    FString SavedBackendLaunchCommand;
    if (GConfig && GConfig->GetString(UE5CopilotSettingsSection, UE5CopilotBackendLaunchCommandKey, SavedBackendLaunchCommand, GEditorPerProjectIni))
    {
        BackendLaunchCommand = SavedBackendLaunchCommand.TrimStartAndEnd();
    }
    if (BackendLaunchCommand.IsEmpty())
    {
        BackendLaunchCommand = UE5CopilotAssistant::BuildSuggestedBackendLaunchCommand();
    }
}

void FUE5CopilotAssistantModule::SaveSettings() const
{
    if (!GConfig)
    {
        return;
    }

    GConfig->SetString(UE5CopilotSettingsSection, UE5CopilotBackendUrlKey, *CurrentBackendBaseUrl, GEditorPerProjectIni);
    GConfig->SetString(UE5CopilotSettingsSection, UE5CopilotBackendLaunchCommandKey, *BackendLaunchCommand, GEditorPerProjectIni);
    GConfig->Flush(false, GEditorPerProjectIni);
}

void FUE5CopilotAssistantModule::RegisterMenus()
{
    FToolMenuOwnerScoped OwnerScoped(this);

    UToolMenu* Menu = UToolMenus::Get()->ExtendMenu("LevelEditor.MainMenu.Window");
    FToolMenuSection& Section = Menu->FindOrAddSection("WindowLayout");
    Section.AddMenuEntry(
        "OpenUE5CopilotAssistant",
        LOCTEXT("OpenUE5CopilotAssistant", "FitzAI"),
        LOCTEXT("OpenUE5CopilotAssistantTooltip", "Open the FitzAI assistant tab."),
        FSlateIcon(FAppStyle::GetAppStyleSetName(), "LevelEditor.Tabs.Details"),
        FUIAction(FExecuteAction::CreateLambda([]()
        {
            FGlobalTabmanager::Get()->TryInvokeTab(UE5CopilotAssistantTabName);
        }))
    );

    FContentBrowserModule& ContentBrowserModule = FModuleManager::LoadModuleChecked<FContentBrowserModule>(TEXT("ContentBrowser"));
    ContentBrowserModule.GetAllAssetViewContextMenuExtenders().Add(
        FContentBrowserMenuExtender_SelectedAssets::CreateRaw(this, &FUE5CopilotAssistantModule::OnExtendContentBrowserAssetSelectionMenu)
    );
}

void FUE5CopilotAssistantModule::HandleBackendBaseUrlChanged(const FText& NewText)
{
    CurrentBackendBaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(NewText.ToString());
    SaveSettings();
}

void FUE5CopilotAssistantModule::HandleBackendLaunchCommandChanged(const FText& NewText)
{
    BackendLaunchCommand = NewText.ToString().TrimStartAndEnd();
    SaveSettings();
}

bool FUE5CopilotAssistantModule::StartBackendProcess(FString& OutError)
{
    const FString LaunchCommand = BackendLaunchCommand.TrimStartAndEnd();
    if (LaunchCommand.IsEmpty())
    {
        OutError = TEXT("Enter a backend launch command first. Example: \"C:\\path\\to\\python.exe\" -m uvicorn app.main:app --host 127.0.0.1 --port 8000");
        return false;
    }

    const FString ComSpec = FPlatformMisc::GetEnvironmentVariable(TEXT("ComSpec"));
    if (ComSpec.IsEmpty())
    {
        OutError = TEXT("Could not resolve the system command shell for launching the backend.");
        return false;
    }

    const FString Params = FString::Printf(TEXT("/C start \"UE5CopilotBackend\" %s"), *LaunchCommand);
    FProcHandle ProcHandle = FPlatformProcess::CreateProc(*ComSpec, *Params, true, false, false, nullptr, 0, nullptr, nullptr);
    if (!ProcHandle.IsValid())
    {
        OutError = TEXT("Failed to launch the backend process from the configured command.");
        return false;
    }

    FPlatformProcess::CloseProc(ProcHandle);
    return true;
}

void FUE5CopilotAssistantModule::EnsureBackendAvailable(TFunction<void()> OnReady, const TSharedPtr<STextBlock>& StatusText)
{
    if (CurrentBackendBaseUrl.IsEmpty())
    {
        CurrentBackendBaseUrl = TEXT("http://127.0.0.1:8000");
    }

    TSharedRef<IHttpRequest, ESPMode::ThreadSafe> StatusRequest = FHttpModule::Get().CreateRequest();
    StatusRequest->SetURL(CurrentBackendBaseUrl + TEXT("/status"));
    StatusRequest->SetVerb(TEXT("GET"));
    StatusRequest->OnProcessRequestComplete().BindLambda(
        [this, OnReady, StatusText](FHttpRequestPtr, FHttpResponsePtr HttpResponse, bool bSucceeded)
        {
            if (bSucceeded && HttpResponse.IsValid() && EHttpResponseCodes::IsOk(HttpResponse->GetResponseCode()))
            {
                if (StatusText.IsValid())
                {
                    StatusText->SetText(LOCTEXT("UE5CopilotBackendConnected", "Connected."));
                }
                OnReady();
                return;
            }

            if (bBackendStartupInProgress)
            {
                if (StatusText.IsValid())
                {
                    StatusText->SetText(LOCTEXT("UE5CopilotBackendStillStarting", "Backend is still starting. Please wait a moment."));
                }
                return;
            }

            FString LaunchError;
            if (!StartBackendProcess(LaunchError))
            {
                if (StatusText.IsValid())
                {
                    StatusText->SetText(FText::FromString(LaunchError));
                }
                return;
            }

            bBackendStartupInProgress = true;
            if (StatusText.IsValid())
            {
                StatusText->SetText(LOCTEXT("UE5CopilotBackendStarting", "Starting backend automatically..."));
            }

            TSharedPtr<int32> AttemptsRemaining = MakeShared<int32>(20);
            FTSTicker::GetCoreTicker().AddTicker(
                FTickerDelegate::CreateLambda([this, OnReady, StatusText, AttemptsRemaining](float)
                {
                    TSharedRef<IHttpRequest, ESPMode::ThreadSafe> PollRequest = FHttpModule::Get().CreateRequest();
                    PollRequest->SetURL(CurrentBackendBaseUrl + TEXT("/status"));
                    PollRequest->SetVerb(TEXT("GET"));
                    PollRequest->OnProcessRequestComplete().BindLambda(
                        [this, OnReady, StatusText, AttemptsRemaining](FHttpRequestPtr, FHttpResponsePtr PollResponse, bool bPollSucceeded)
                        {
                            if (bPollSucceeded && PollResponse.IsValid() && EHttpResponseCodes::IsOk(PollResponse->GetResponseCode()))
                            {
                                bBackendStartupInProgress = false;
                                if (StatusText.IsValid())
                                {
                                    StatusText->SetText(LOCTEXT("UE5CopilotBackendConnectedAfterStart", "Connected."));
                                }
                                OnReady();
                                return;
                            }

                            *AttemptsRemaining -= 1;
                            if (*AttemptsRemaining <= 0)
                            {
                                bBackendStartupInProgress = false;
                                if (StatusText.IsValid())
                                {
                                    StatusText->SetText(LOCTEXT("UE5CopilotBackendStartTimeout", "Backend launch was attempted, but it is not reachable yet. Open More Tools > Setup if needed."));
                                }
                            }
                        });
                    PollRequest->ProcessRequest();
                    return *AttemptsRemaining > 0 && bBackendStartupInProgress;
                }),
                0.5f);
        });
    StatusRequest->ProcessRequest();
}

void FUE5CopilotAssistantModule::EnsureBackendAndSendRequest(
    const FString& Url,
    const FString& Payload,
    const TSharedPtr<SMultiLineEditableTextBox>& OutputTextBox,
    const TSharedPtr<SMultiLineEditableTextBox>& AgentSessionTextBox,
    const TSharedPtr<SMultiLineEditableTextBox>& CodeDiffPreviewTextBox,
    const TSharedPtr<SMultiLineEditableTextBox>& EditorActionPreviewTextBox,
    const TSharedPtr<SEditableTextBox>& BundleApplyTargetPathTextBox,
    FString* PendingEditorActionJsonPtr,
    const TSharedPtr<STextBlock>& StatusText)
{
    EnsureBackendAvailable(
        [Url, Payload, OutputTextBox, AgentSessionTextBox, CodeDiffPreviewTextBox, EditorActionPreviewTextBox, BundleApplyTargetPathTextBox, PendingEditorActionJsonPtr, StatusText]()
        {
            UE5CopilotAssistant::SendPostRequest(Url, Payload, OutputTextBox, AgentSessionTextBox, CodeDiffPreviewTextBox, EditorActionPreviewTextBox, BundleApplyTargetPathTextBox, PendingEditorActionJsonPtr, StatusText);
        },
        StatusText);
}

void FUE5CopilotAssistantModule::OpenAssistantTab()
{
    FGlobalTabmanager::Get()->TryInvokeTab(UE5CopilotAssistantTabName);
}

void FUE5CopilotAssistantModule::RefreshPendingCodePatchBundleTargets(const TArray<FString>& TargetPaths, const FString& PreferredTargetPath)
{
    PendingCodePatchBundleTargets.Reset();
    SelectedPendingCodePatchBundleTarget.Reset();

    for (const FString& TargetPath : TargetPaths)
    {
        if (!TargetPath.IsEmpty())
        {
            PendingCodePatchBundleTargets.Add(MakeShared<FString>(TargetPath));
        }
    }

    if (PendingCodePatchBundleTargets.Num() > 0)
    {
        const FString DesiredTarget = !PreferredTargetPath.IsEmpty() ? PreferredTargetPath : *PendingCodePatchBundleTargets[0];
        for (const TSharedPtr<FString>& TargetOption : PendingCodePatchBundleTargets)
        {
            if (TargetOption.IsValid() && TargetOption->Equals(DesiredTarget, ESearchCase::IgnoreCase))
            {
                SelectedPendingCodePatchBundleTarget = TargetOption;
                break;
            }
        }
        if (!SelectedPendingCodePatchBundleTarget.IsValid())
        {
            SelectedPendingCodePatchBundleTarget = PendingCodePatchBundleTargets[0];
        }
    }

    if (BundleApplyTargetComboBoxPtr.IsValid())
    {
        BundleApplyTargetComboBoxPtr->RefreshOptions();
        BundleApplyTargetComboBoxPtr->SetSelectedItem(SelectedPendingCodePatchBundleTarget);
    }

    if (BundleApplyTargetPathTextBoxPtr.IsValid())
    {
        BundleApplyTargetPathTextBoxPtr->SetText(FText::FromString(SelectedPendingCodePatchBundleTarget.IsValid() ? *SelectedPendingCodePatchBundleTarget : FString()));
    }
}

void FUE5CopilotAssistantModule::ClearPendingCodePatchBundleTargets()
{
    PendingCodePatchBundleTargets.Reset();
    SelectedPendingCodePatchBundleTarget.Reset();

    if (BundleApplyTargetComboBoxPtr.IsValid())
    {
        BundleApplyTargetComboBoxPtr->RefreshOptions();
        BundleApplyTargetComboBoxPtr->SetSelectedItem(nullptr);
    }

    if (BundleApplyTargetPathTextBoxPtr.IsValid())
    {
        BundleApplyTargetPathTextBoxPtr->SetText(FText::GetEmpty());
    }
}

TSharedRef<FExtender> FUE5CopilotAssistantModule::OnExtendContentBrowserAssetSelectionMenu(const TArray<FAssetData>& SelectedAssets)
{
    TSharedRef<FExtender> Extender = MakeShared<FExtender>();
    if (SelectedAssets.Num() == 0)
    {
        return Extender;
    }

    Extender->AddMenuExtension(
        "GetAssetActions",
        EExtensionHook::After,
        nullptr,
        FMenuExtensionDelegate::CreateRaw(this, &FUE5CopilotAssistantModule::AddAssetContextMenuEntries, SelectedAssets)
    );
    return Extender;
}

void FUE5CopilotAssistantModule::AddAssetContextMenuEntries(FMenuBuilder& MenuBuilder, TArray<FAssetData> SelectedAssets)
{
    if (SelectedAssets.Num() == 0)
    {
        return;
    }

    const FAssetData AssetData = SelectedAssets[0];
    MenuBuilder.BeginSection("UE5CopilotAssistant", LOCTEXT("UE5CopilotContextSection", "FitzAI"));
    MenuBuilder.AddMenuEntry(
        LOCTEXT("UE5CopilotContextExplain", "Explain Selected Asset"),
        LOCTEXT("UE5CopilotContextExplainTooltip", "Inspect this asset with FitzAI."),
        FSlateIcon(),
        FUIAction(FExecuteAction::CreateRaw(this, &FUE5CopilotAssistantModule::RequestAssetDetailsForSelection, AssetData))
    );
    MenuBuilder.AddMenuEntry(
        LOCTEXT("UE5CopilotContextPlan", "Plan Asset Change"),
        LOCTEXT("UE5CopilotContextPlanTooltip", "Build an edit plan for this asset using the current prompt text in the FitzAI tab."),
        FSlateIcon(),
        FUIAction(FExecuteAction::CreateRaw(this, &FUE5CopilotAssistantModule::RequestAssetEditPlanForSelection, AssetData))
    );
    MenuBuilder.EndSection();
}

void FUE5CopilotAssistantModule::RequestAssetDetailsForSelection(FAssetData AssetData)
{
    OpenAssistantTab();

    const FString BaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(
        BackendBaseUrlTextBoxPtr.IsValid() ? BackendBaseUrlTextBoxPtr->GetText().ToString() : CurrentBackendBaseUrl
    );
    CurrentBackendBaseUrl = BaseUrl;

    if (BaseUrl.IsEmpty())
    {
        if (StatusTextPtr.IsValid())
        {
            StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusMissingBaseUrlAssetDetailsContext", "Enter a backend base URL first."));
        }
        return;
    }

    if (SelectionPreviewTextPtr.IsValid())
    {
        SelectionPreviewTextPtr->SetText(FText::FromString(FString::Printf(TEXT("Current selection: %s [asset]"), *AssetData.AssetName.ToString())));
    }
    if (StatusTextPtr.IsValid())
    {
        StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusSendingAssetDetailsContext", "Inspecting the selected asset..."));
    }

    EnsureBackendAndSendRequest(
        BaseUrl + TEXT("/plugin/asset-details"),
        UE5CopilotAssistant::BuildPluginAssetDetailsPayload(
            AssetData.AssetName.ToString(),
            TEXT("asset"),
            AssetData.GetSoftObjectPath().ToString(),
            AssetData.AssetClassPath.GetAssetName().ToString()
        ),
        OutputTextBoxPtr,
        AgentSessionTextBoxPtr,
        CodeDiffPreviewTextBoxPtr,
        EditorActionPreviewTextBoxPtr,
        BundleApplyTargetPathTextBoxPtr,
        &PendingEditorActionJson,
        StatusTextPtr
    );
}

void FUE5CopilotAssistantModule::RequestAssetEditPlanForSelection(FAssetData AssetData)
{
    OpenAssistantTab();

    const FString BaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(
        BackendBaseUrlTextBoxPtr.IsValid() ? BackendBaseUrlTextBoxPtr->GetText().ToString() : CurrentBackendBaseUrl
    );
    const FString ChangeRequest = PromptTextBoxPtr.IsValid() ? PromptTextBoxPtr->GetText().ToString() : FString();
    CurrentBackendBaseUrl = BaseUrl;

    if (BaseUrl.IsEmpty())
    {
        if (StatusTextPtr.IsValid())
        {
            StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusMissingBaseUrlAssetEditContext", "Enter a backend base URL first."));
        }
        return;
    }
    if (ChangeRequest.IsEmpty())
    {
        if (StatusTextPtr.IsValid())
        {
            StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusMissingPromptAssetEditContext", "Type the requested asset change in the FitzAI prompt box first."));
        }
        return;
    }

    if (SelectionPreviewTextPtr.IsValid())
    {
        SelectionPreviewTextPtr->SetText(FText::FromString(FString::Printf(TEXT("Current selection: %s [asset]"), *AssetData.AssetName.ToString())));
    }
    if (StatusTextPtr.IsValid())
    {
        StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusSendingAssetEditContext", "Building an edit plan for the selected asset..."));
    }

    EnsureBackendAndSendRequest(
        BaseUrl + TEXT("/plugin/asset-edit-plan"),
        UE5CopilotAssistant::BuildPluginAssetEditPlanPayload(
            AssetData.AssetName.ToString(),
            TEXT("asset"),
            AssetData.GetSoftObjectPath().ToString(),
            AssetData.AssetClassPath.GetAssetName().ToString(),
            ChangeRequest
        ),
        OutputTextBoxPtr,
        AgentSessionTextBoxPtr,
        CodeDiffPreviewTextBoxPtr,
        EditorActionPreviewTextBoxPtr,
        BundleApplyTargetPathTextBoxPtr,
        &PendingEditorActionJson,
        StatusTextPtr
    );
}

TSharedRef<SDockTab> FUE5CopilotAssistantModule::SpawnAssistantTab(const FSpawnTabArgs& SpawnTabArgs)
{
    TSharedPtr<SMultiLineEditableTextBox> DeepAssetTextBox;
    if (DeepAssetKinds.Num() == 0)
    {
        DeepAssetKinds = {
            MakeShared<FString>(TEXT("blueprint")),
            MakeShared<FString>(TEXT("material")),
            MakeShared<FString>(TEXT("behavior_tree")),
            MakeShared<FString>(TEXT("enhanced_input")),
            MakeShared<FString>(TEXT("state_tree")),
            MakeShared<FString>(TEXT("control_rig")),
            MakeShared<FString>(TEXT("niagara")),
            MakeShared<FString>(TEXT("eqs")),
            MakeShared<FString>(TEXT("sequencer")),
            MakeShared<FString>(TEXT("metasound")),
            MakeShared<FString>(TEXT("pcg")),
            MakeShared<FString>(TEXT("motion_matching")),
            MakeShared<FString>(TEXT("ik_rig")),
            MakeShared<FString>(TEXT("data_asset")),
            MakeShared<FString>(TEXT("animbp"))
        };
    }
    if (!SelectedDeepAssetKind.IsValid() && DeepAssetKinds.Num() > 0)
    {
        SelectedDeepAssetKind = DeepAssetKinds[0];
    }
    if (AssetScaffoldKinds.Num() == 0)
    {
        AssetScaffoldKinds = {
            MakeShared<FString>(TEXT("blueprint_class")),
            MakeShared<FString>(TEXT("animbp")),
            MakeShared<FString>(TEXT("data_asset")),
            MakeShared<FString>(TEXT("material")),
            MakeShared<FString>(TEXT("material_instance")),
            MakeShared<FString>(TEXT("behavior_tree")),
            MakeShared<FString>(TEXT("input_action")),
            MakeShared<FString>(TEXT("input_mapping_context")),
            MakeShared<FString>(TEXT("state_tree")),
            MakeShared<FString>(TEXT("control_rig")),
            MakeShared<FString>(TEXT("niagara")),
            MakeShared<FString>(TEXT("eqs")),
            MakeShared<FString>(TEXT("sequencer")),
            MakeShared<FString>(TEXT("metasound")),
            MakeShared<FString>(TEXT("pcg")),
            MakeShared<FString>(TEXT("motion_matching")),
            MakeShared<FString>(TEXT("ik_rig"))
        };
    }
    if (!SelectedAssetScaffoldKind.IsValid() && AssetScaffoldKinds.Num() > 0)
    {
        SelectedAssetScaffoldKind = AssetScaffoldKinds[0];
    }

    return SNew(SDockTab)
        .TabRole(ETabRole::NomadTab)
        [
            SNew(SBorder)
            .Padding(12.0f)
            [
                SNew(SVerticalBox)

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 20.0f, 0.0f, 6.0f)
                [
                    SNew(STextBlock)
                    .Text(LOCTEXT("UE5CopilotHeader", "Let's build"))
                    .Font(FAppStyle::GetFontStyle("HeadingMedium"))
                    .Justification(ETextJustify::Center)
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SNew(STextBlock)
                    .Text(LOCTEXT("UE5CopilotIntro", "FitzAI"))
                    .Justification(ETextJustify::Center)
                    .AutoWrapText(true)
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SAssignNew(StatusTextPtr, STextBlock)
                    .Text(LOCTEXT("UE5CopilotStatusDefault", "Ask anything."))
                    .Justification(ETextJustify::Center)
                    .AutoWrapText(true)
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 10.0f)
                [
                    SNew(SHorizontalBox)

                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    .VAlign(VAlign_Center)
                    [
                        SNew(STextBlock)
                        .Text_Lambda([this]()
                        {
                            const FString DisplayUrl = CurrentBackendBaseUrl.IsEmpty() ? TEXT("http://127.0.0.1:8000") : CurrentBackendBaseUrl;
                            return FText::FromString(FString::Printf(TEXT("Backend: %s"), *DisplayUrl));
                        })
                    ]

                    + SHorizontalBox::Slot()
                    .AutoWidth()
                    .Padding(8.0f, 0.0f, 0.0f, 0.0f)
                    [
                        SNew(SButton)
                        .Text(LOCTEXT("UE5CopilotConnectBackend", "Connect"))
                        .OnClicked_Lambda([this]()
                        {
                            const FString BaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(
                                BackendBaseUrlTextBoxPtr.IsValid() ? BackendBaseUrlTextBoxPtr->GetText().ToString() : CurrentBackendBaseUrl
                            );
                            CurrentBackendBaseUrl = BaseUrl.IsEmpty() ? TEXT("http://127.0.0.1:8000") : BaseUrl;
                            SaveSettings();

                            EnsureBackendAvailable(
                                [this]()
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotConnectBackendReady", "Connected. You can start chatting."));
                                    }
                                },
                                StatusTextPtr
                            );
                            return FReply::Handled();
                        })
                    ]
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 8.0f, 0.0f, 10.0f)
                [
                    SNew(SHorizontalBox)

                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    .Padding(0.0f, 0.0f, 6.0f, 0.0f)
                    [
                        SNew(SButton)
                        .Text(LOCTEXT("UE5CopilotSuggestionOne", "Explain the selected Blueprint"))
                        .OnClicked_Lambda([this]()
                        {
                            if (PromptTextBoxPtr.IsValid())
                            {
                                PromptTextBoxPtr->SetText(LOCTEXT("UE5CopilotSuggestionOnePrompt", "Explain what the selected Blueprint does and point out any likely issues."));
                            }
                            return FReply::Handled();
                        })
                    ]

                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    .Padding(3.0f, 0.0f, 3.0f, 0.0f)
                    [
                        SNew(SButton)
                        .Text(LOCTEXT("UE5CopilotSuggestionTwo", "Plan a new gameplay feature"))
                        .OnClicked_Lambda([this]()
                        {
                            if (PromptTextBoxPtr.IsValid())
                            {
                                PromptTextBoxPtr->SetText(LOCTEXT("UE5CopilotSuggestionTwoPrompt", "Create a step-by-step plan for a new gameplay feature in this project."));
                            }
                            return FReply::Handled();
                        })
                    ]

                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    .Padding(6.0f, 0.0f, 0.0f, 0.0f)
                    [
                        SNew(SButton)
                        .Text(LOCTEXT("UE5CopilotSuggestionThree", "Help me change code"))
                        .OnClicked_Lambda([this]()
                        {
                            if (PromptTextBoxPtr.IsValid())
                            {
                                PromptTextBoxPtr->SetText(LOCTEXT("UE5CopilotSuggestionThreePrompt", "Help me change the code for the selected gameplay system."));
                            }
                            return FReply::Handled();
                        })
                    ]
                ]

                + SVerticalBox::Slot()
                .FillHeight(0.48f)
                .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                [
                    SAssignNew(OutputTextBoxPtr, SMultiLineEditableTextBox)
                    .IsReadOnly(true)
                    .HintText(LOCTEXT("UE5CopilotOutputHint", "Replies show up here."))
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
                        SNew(SBox)
                        .MinDesiredHeight(72.0f)
                        [
                            SAssignNew(PromptTextBoxPtr, SMultiLineEditableTextBox)
                            .HintText(LOCTEXT("UE5CopilotPromptHint", "Ask anything about your project, or describe the change you want..."))
                        ]
                    ]

                    + SHorizontalBox::Slot()
                    .AutoWidth()
                    .VAlign(VAlign_Bottom)
                    [
                        SNew(SButton)
                        .Text(LOCTEXT("UE5CopilotSendAsk", "Send"))
                        .OnClicked_Lambda([this]()
                        {
                            const FString BaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(BackendBaseUrlTextBoxPtr.IsValid() ? BackendBaseUrlTextBoxPtr->GetText().ToString() : FString());
                            const FString Prompt = PromptTextBoxPtr.IsValid() ? PromptTextBoxPtr->GetText().ToString() : FString();
                            if (BaseUrl.IsEmpty() || Prompt.IsEmpty())
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusMissingAskInput", "Enter a backend URL and a prompt first."));
                                }
                                return FReply::Handled();
                            }
                            CurrentBackendBaseUrl = BaseUrl;

                            FString SelectionName, SelectionType, AssetPath, ClassName;
                            const bool bHasSelection = UE5CopilotAssistant::GetCurrentSelection(SelectionName, SelectionType, AssetPath, ClassName);
                            if (SelectionPreviewTextPtr.IsValid())
                            {
                                SelectionPreviewTextPtr->SetText(
                                    bHasSelection
                                        ? FText::FromString(FString::Printf(TEXT("Current selection: %s [%s]"), *SelectionName, *SelectionType))
                                        : LOCTEXT("UE5CopilotSelectionNone", "Current selection: none")
                                );
                            }

                            if (StatusTextPtr.IsValid())
                            {
                                StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusSendingAsk", "Sending chat request..."));
                            }

                            EnsureBackendAndSendRequest(
                                BaseUrl + TEXT("/plugin/chat"),
                                UE5CopilotAssistant::BuildPluginChatPayload(
                                    Prompt,
                                    bHasSelection ? SelectionName : FString(),
                                    bHasSelection ? SelectionType : FString(),
                                    bHasSelection ? AssetPath : FString(),
                                    bHasSelection ? ClassName : FString(),
                                    FString()
                                ),
                                OutputTextBoxPtr,
                                AgentSessionTextBoxPtr,
                                CodeDiffPreviewTextBoxPtr,
                                EditorActionPreviewTextBoxPtr,
                                BundleApplyTargetPathTextBoxPtr,
                                &PendingEditorActionJson,
                                StatusTextPtr
                            );
                            return FReply::Handled();
                        })
                    ]
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                [
                    SNew(SExpandableArea)
                    .InitiallyCollapsed(true)
                    .AreaTitle(LOCTEXT("UE5CopilotMoreToolsHeader", "More Tools"))
                    .BodyContent()
                    [
                        SNew(SVerticalBox)

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                        [
                            SNew(STextBlock)
                            .Text(LOCTEXT("UE5CopilotMoreToolsHelp", "Power tools for setup, selected assets, previews, and advanced workflows."))
                            .AutoWrapText(true)
                        ]

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                        [
                            SNew(SExpandableArea)
                            .InitiallyCollapsed(true)
                            .AreaTitle(LOCTEXT("UE5CopilotBackendHeader", "Setup"))
                            .BodyContent()
                            [
                                SNew(SVerticalBox)

                                + SVerticalBox::Slot()
                                .AutoHeight()
                                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                                [
                                    SNew(STextBlock)
                                    .Text(LOCTEXT("UE5CopilotBackendHelp", "Use this only when you need to change the backend URL or launch command."))
                                    .AutoWrapText(true)
                                ]

                                + SVerticalBox::Slot()
                                .AutoHeight()
                                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                                [
                                    SAssignNew(BackendBaseUrlTextBoxPtr, SEditableTextBox)
                                    .Text(FText::FromString(CurrentBackendBaseUrl))
                                    .HintText(LOCTEXT("UE5CopilotBackendHint", "Backend URL, for example http://127.0.0.1:8000"))
                                    .OnTextChanged_Raw(this, &FUE5CopilotAssistantModule::HandleBackendBaseUrlChanged)
                                ]

                                + SVerticalBox::Slot()
                                .AutoHeight()
                                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                                [
                                    SAssignNew(BackendLaunchCommandTextBoxPtr, SEditableTextBox)
                                    .Text(FText::FromString(BackendLaunchCommand))
                                    .HintText(LOCTEXT("UE5CopilotBackendLaunchHint", "Optional auto-start command, for example \"C:\\path\\to\\python.exe\" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"))
                                    .OnTextChanged_Raw(this, &FUE5CopilotAssistantModule::HandleBackendLaunchCommandChanged)
                                ]

                                + SVerticalBox::Slot()
                                .AutoHeight()
                                [
                                    SNew(SButton)
                                    .Text(LOCTEXT("UE5CopilotStartBackend", "Start Backend"))
                                    .OnClicked_Lambda([this]()
                                    {
                                        FString LaunchError;
                                        if (!StartBackendProcess(LaunchError))
                                        {
                                            if (StatusTextPtr.IsValid())
                                            {
                                                StatusTextPtr->SetText(FText::FromString(LaunchError));
                                            }
                                            return FReply::Handled();
                                        }

                                        if (StatusTextPtr.IsValid())
                                        {
                                            StatusTextPtr->SetText(LOCTEXT("UE5CopilotBackendStartingManual", "Backend launch requested."));
                                        }
                                        return FReply::Handled();
                                    })
                                ]
                            ]
                        ]

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                        [
                            SNew(SExpandableArea)
                            .InitiallyCollapsed(false)
                            .AreaTitle(LOCTEXT("UE5CopilotSelectionToolsHeader", "Selected Asset And Workflow"))
                            .BodyContent()
                            [
                                SNew(SVerticalBox)

                                + SVerticalBox::Slot()
                                .AutoHeight()
                                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                                [
                                    SNew(STextBlock)
                                    .Text(LOCTEXT("UE5CopilotSelectionToolsHelp", "Use these when you want to inspect the current selection, plan a change, or force workflow mode."))
                                    .AutoWrapText(true)
                                ]

                                + SVerticalBox::Slot()
                                .AutoHeight()
                                .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                                [
                            SAssignNew(SelectionPreviewTextPtr, STextBlock)
                            .Text(LOCTEXT("UE5CopilotSelectionDefault", "Current selection: none"))
                                ]

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                        [
                            SAssignNew(CodePatchTargetPathTextBoxPtr, SEditableTextBox)
                            .HintText(LOCTEXT("UE5CopilotCodeTargetPathHint", "Optional code target path, for example Source/MyGame/Public/Player/MyPlayerCharacter.h"))
                        ]

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                        [
                            SNew(SButton)
                            .Text(LOCTEXT("UE5CopilotPlanTask", "Force Agent Workflow"))
                            .ToolTipText(LOCTEXT("UE5CopilotPlanTaskTooltip", "Start a multi-step backend agent session immediately for this prompt."))
                            .OnClicked_Lambda([this]()
                            {
                                const FString BaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(BackendBaseUrlTextBoxPtr.IsValid() ? BackendBaseUrlTextBoxPtr->GetText().ToString() : FString());
                                const FString Prompt = PromptTextBoxPtr.IsValid() ? PromptTextBoxPtr->GetText().ToString().TrimStartAndEnd() : FString();
                                const FString TargetPath = CodePatchTargetPathTextBoxPtr.IsValid() ? CodePatchTargetPathTextBoxPtr->GetText().ToString().TrimStartAndEnd() : FString();
                                if (BaseUrl.IsEmpty() || Prompt.IsEmpty())
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusMissingTaskPlanInput", "Enter a backend URL and a broader task prompt first."));
                                    }
                                    return FReply::Handled();
                                }
                                CurrentBackendBaseUrl = BaseUrl;

                                FString SelectionName, SelectionType, AssetPath, ClassName;
                                const bool bHasSelection = UE5CopilotAssistant::GetCurrentSelection(SelectionName, SelectionType, AssetPath, ClassName);
                                if (SelectionPreviewTextPtr.IsValid())
                                {
                                    SelectionPreviewTextPtr->SetText(
                                        bHasSelection
                                            ? FText::FromString(FString::Printf(TEXT("Current selection: %s [%s]"), *SelectionName, *SelectionType))
                                            : LOCTEXT("UE5CopilotSelectionNone", "Current selection: none")
                                    );
                                }

                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusSendingTaskPlan", "Forcing backend agent workflow mode..."));
                                }

                                EnsureBackendAndSendRequest(
                                    BaseUrl + TEXT("/agent-session"),
                                    UE5CopilotAssistant::BuildAgentTaskPayload(Prompt),
                                    OutputTextBoxPtr,
                                    AgentSessionTextBoxPtr,
                                    CodeDiffPreviewTextBoxPtr,
                                    EditorActionPreviewTextBoxPtr,
                                    BundleApplyTargetPathTextBoxPtr,
                                    &PendingEditorActionJson,
                                    StatusTextPtr
                                );
                                return FReply::Handled();
                            })
                        ]

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 4.0f)
                        [
                            SNew(STextBlock)
                            .Text(LOCTEXT("UE5CopilotSelectionWorkflowHeader", "Quick Actions"))
                            .Font(FAppStyle::GetFontStyle("BoldFont"))
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
                                .Text(LOCTEXT("UE5CopilotExplainAsset", "Inspect Selected Asset"))
                                .ToolTipText(LOCTEXT("UE5CopilotExplainAssetTooltip", "Inspect the selected asset with asset-specific context."))
                                .OnClicked_Lambda([this]()
                                {
                                    const FString BaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(BackendBaseUrlTextBoxPtr.IsValid() ? BackendBaseUrlTextBoxPtr->GetText().ToString() : FString());
                                    if (BaseUrl.IsEmpty())
                                    {
                                        if (StatusTextPtr.IsValid())
                                        {
                                            StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusMissingBaseUrlAssetDetails", "Enter a backend base URL first."));
                                        }
                                        return FReply::Handled();
                                    }
                                    CurrentBackendBaseUrl = BaseUrl;

                                    FString SelectionName, SelectionType, AssetPath, ClassName;
                                    if (!UE5CopilotAssistant::GetCurrentSelection(SelectionName, SelectionType, AssetPath, ClassName))
                                    {
                                        if (StatusTextPtr.IsValid())
                                        {
                                            StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusNoSelectionAssetDetails", "Select an asset before using the asset inspector."));
                                        }
                                        return FReply::Handled();
                                    }

                                    if (SelectionPreviewTextPtr.IsValid())
                                    {
                                        SelectionPreviewTextPtr->SetText(FText::FromString(FString::Printf(TEXT("Current selection: %s [%s]"), *SelectionName, *SelectionType)));
                                    }
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusSendingAssetDetails", "Inspecting the selected asset..."));
                                    }

                                    EnsureBackendAndSendRequest(
                                        BaseUrl + TEXT("/plugin/asset-details"),
                                        UE5CopilotAssistant::BuildPluginAssetDetailsPayload(SelectionName, SelectionType, AssetPath, ClassName),
                                        OutputTextBoxPtr,
                                        AgentSessionTextBoxPtr,
                                        CodeDiffPreviewTextBoxPtr,
                                        EditorActionPreviewTextBoxPtr,
                                        BundleApplyTargetPathTextBoxPtr,
                                        &PendingEditorActionJson,
                                        StatusTextPtr
                                    );
                                    return FReply::Handled();
                                })
                            ]

                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    .Padding(4.0f, 0.0f, 0.0f, 0.0f)
                    [
                        SNew(SButton)
                        .Text(LOCTEXT("UE5CopilotPlanAssetEdit", "Suggest Changes For Selected Asset"))
                        .ToolTipText(LOCTEXT("UE5CopilotPlanAssetEditTooltip", "Use the text box above as your requested change, then generate a plan for the selected asset."))
                        .OnClicked_Lambda([this]()
                        {
                            const FString BaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(BackendBaseUrlTextBoxPtr.IsValid() ? BackendBaseUrlTextBoxPtr->GetText().ToString() : FString());
                            const FString ChangeRequest = PromptTextBoxPtr.IsValid() ? PromptTextBoxPtr->GetText().ToString() : FString();
                            if (BaseUrl.IsEmpty())
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusMissingBaseUrlAssetEdit", "Enter a backend base URL first."));
                                }
                                return FReply::Handled();
                            }
                            CurrentBackendBaseUrl = BaseUrl;
                            if (ChangeRequest.IsEmpty())
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusMissingAssetEditRequest", "Describe the asset change in the prompt box first."));
                                }
                                return FReply::Handled();
                            }

                            FString SelectionName, SelectionType, AssetPath, ClassName;
                            if (!UE5CopilotAssistant::GetCurrentSelection(SelectionName, SelectionType, AssetPath, ClassName))
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusNoSelectionAssetEdit", "Select an asset before planning an asset change."));
                                }
                                return FReply::Handled();
                            }

                            if (SelectionPreviewTextPtr.IsValid())
                            {
                                SelectionPreviewTextPtr->SetText(FText::FromString(FString::Printf(TEXT("Current selection: %s [%s]"), *SelectionName, *SelectionType)));
                            }
                            if (StatusTextPtr.IsValid())
                            {
                                StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusSendingAssetEdit", "Building an edit plan for the selected asset..."));
                            }

                            EnsureBackendAndSendRequest(
                                BaseUrl + TEXT("/plugin/asset-edit-plan"),
                                UE5CopilotAssistant::BuildPluginAssetEditPlanPayload(SelectionName, SelectionType, AssetPath, ClassName, ChangeRequest),
                                OutputTextBoxPtr,
                                AgentSessionTextBoxPtr,
                                CodeDiffPreviewTextBoxPtr,
                                EditorActionPreviewTextBoxPtr,
                                BundleApplyTargetPathTextBoxPtr,
                                &PendingEditorActionJson,
                                StatusTextPtr
                            );
                            return FReply::Handled();
                        })
                    ]
                ]

                                ]
                            ]
                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 4.0f)
                [
                    SNew(SExpandableArea)
                    .InitiallyCollapsed(true)
                    .AreaTitle(LOCTEXT("UE5CopilotScaffoldHeader", "Create New Asset"))
                    .BodyContent()
                    [
                        SNew(SVerticalBox)

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                        [
                            SNew(STextBlock)
                            .Text(LOCTEXT("UE5CopilotScaffoldHelp", "Build a starter plan for a brand-new asset."))
                            .AutoWrapText(true)
                        ]

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                        [
                            SNew(SComboBox<TSharedPtr<FString>>)
                    .OptionsSource(&AssetScaffoldKinds)
                    .InitiallySelectedItem(SelectedAssetScaffoldKind)
                    .OnGenerateWidget_Lambda([](TSharedPtr<FString> Item)
                    {
                        return SNew(STextBlock).Text(FText::FromString(Item.IsValid() ? *Item : TEXT("")));
                    })
                    .OnSelectionChanged_Lambda([this](TSharedPtr<FString> NewValue, ESelectInfo::Type)
                    {
                        if (NewValue.IsValid())
                        {
                            SelectedAssetScaffoldKind = NewValue;
                        }
                    })
                    [
                        SNew(STextBlock)
                        .Text_Lambda([this]()
                        {
                            return FText::FromString(SelectedAssetScaffoldKind.IsValid() ? *SelectedAssetScaffoldKind : TEXT("blueprint_class"));
                        })
                    ]
                        ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SAssignNew(ScaffoldNameTextBoxPtr, SEditableTextBox)
                    .HintText(LOCTEXT("UE5CopilotScaffoldNameHint", "New asset name, for example BT_EnemyCombat or NS_ImpactDust"))
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SAssignNew(ScaffoldPurposeTextBoxPtr, SEditableTextBox)
                    .HintText(LOCTEXT("UE5CopilotScaffoldPurposeHint", "Why this asset exists, for example combat AI flow or impact effect"))
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                [
                    SAssignNew(ScaffoldClassNameTextBoxPtr, SEditableTextBox)
                    .HintText(LOCTEXT("UE5CopilotScaffoldClassHint", "Optional parent or class context, for example Character or UWeaponDataAsset"))
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                    [
                        SNew(SButton)
                    .Text(LOCTEXT("UE5CopilotGenerateScaffold", "Create Asset Plan"))
                    .OnClicked_Lambda([this]()
                    {
                        const FString BaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(BackendBaseUrlTextBoxPtr.IsValid() ? BackendBaseUrlTextBoxPtr->GetText().ToString() : FString());
                        const FString AssetName = ScaffoldNameTextBoxPtr.IsValid() ? ScaffoldNameTextBoxPtr->GetText().ToString().TrimStartAndEnd() : FString();
                        const FString Purpose = ScaffoldPurposeTextBoxPtr.IsValid() ? ScaffoldPurposeTextBoxPtr->GetText().ToString().TrimStartAndEnd() : FString();
                        const FString ClassName = ScaffoldClassNameTextBoxPtr.IsValid() ? ScaffoldClassNameTextBoxPtr->GetText().ToString().TrimStartAndEnd() : FString();
                        if (BaseUrl.IsEmpty())
                        {
                            if (StatusTextPtr.IsValid())
                            {
                                StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusMissingScaffoldBaseUrl", "Enter a backend base URL first."));
                            }
                            return FReply::Handled();
                        }
                        if (AssetName.IsEmpty())
                        {
                            if (StatusTextPtr.IsValid())
                            {
                                StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusMissingScaffoldName", "Enter the new asset name before generating a scaffold."));
                            }
                            return FReply::Handled();
                        }

                        CurrentBackendBaseUrl = BaseUrl;
                        if (StatusTextPtr.IsValid())
                        {
                            StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusSendingScaffold", "Generating an asset scaffold plan..."));
                        }

                        EnsureBackendAndSendRequest(
                            BaseUrl + TEXT("/asset-scaffold"),
                            UE5CopilotAssistant::BuildAssetScaffoldPayload(
                                SelectedAssetScaffoldKind.IsValid() ? *SelectedAssetScaffoldKind : FString(TEXT("blueprint_class")),
                                AssetName,
                                Purpose,
                                ClassName
                            ),
                            OutputTextBoxPtr,
                            AgentSessionTextBoxPtr,
                            CodeDiffPreviewTextBoxPtr,
                            EditorActionPreviewTextBoxPtr,
                            BundleApplyTargetPathTextBoxPtr,
                            &PendingEditorActionJson,
                            StatusTextPtr
                        );
                        return FReply::Handled();
                    })
                ]
                        ]
                ]
                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SNew(SExpandableArea)
                    .InitiallyCollapsed(true)
                    .AreaTitle(LOCTEXT("UE5CopilotAdvancedHeader", "Execution And Deep Analysis"))
                    .BodyContent()
                    [
                        SNew(SVerticalBox)

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                        [
                            SNew(STextBlock)
                            .Text(LOCTEXT("UE5CopilotAdvancedHelp", "Technical tools for applying previewed actions or sending detailed exported asset data."))
                            .AutoWrapText(true)
                        ]

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                        [
                            SNew(SHorizontalBox)

                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    .Padding(0.0f, 0.0f, 4.0f, 0.0f)
                    [
                        SNew(SButton)
                        .Text(LOCTEXT("UE5CopilotExecutePreviewedAction", "Apply Previewed Action"))
                        .OnClicked_Lambda([this]()
                        {
                            if (PendingEditorActionJson.IsEmpty())
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotNoPendingEditorAction", "There is no previewed editor action to execute."));
                                }
                                return FReply::Handled();
                            }

                            TSharedPtr<FJsonObject> EditorActionObject;
                            TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(PendingEditorActionJson);
                            if (!FJsonSerializer::Deserialize(Reader, EditorActionObject) || !EditorActionObject.IsValid())
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotInvalidEditorActionPreview", "The previewed editor action could not be parsed."));
                                }
                                return FReply::Handled();
                            }

                            FString ActionType;
                            if (!EditorActionObject->TryGetStringField(TEXT("action_type"), ActionType) || ActionType.IsEmpty())
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotMissingActionType", "The previewed editor action is missing an action type."));
                                }
                                return FReply::Handled();
                            }

                            bool bDryRun = false;
                            if (EditorActionObject->TryGetBoolField(TEXT("dry_run"), bDryRun) && bDryRun)
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotPreviewOnlyDryRun", "This previewed editor action is marked as dry-run only and cannot be executed yet."));
                                }
                                return FReply::Handled();
                            }

                            if (ActionType != TEXT("rename_asset") && ActionType != TEXT("create_asset") && ActionType != TEXT("tweak_material_parameter") && ActionType != TEXT("apply_code_patch_preview") && ActionType != TEXT("apply_code_patch_bundle_preview"))
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(FText::FromString(FString::Printf(TEXT("`%s` previewed successfully, but this plugin only executes `rename_asset`, a small set of safe `create_asset` actions, narrow material-instance parameter tweaks, and narrow single-file code patch previews right now."), *ActionType)));
                                }
                                return FReply::Handled();
                            }

                            const TSharedPtr<FJsonObject>* ArgumentsObject = nullptr;
                            if (!EditorActionObject->TryGetObjectField(TEXT("arguments"), ArgumentsObject) || !ArgumentsObject || !ArgumentsObject->IsValid())
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotMissingRenameArguments", "The rename action is missing its argument payload."));
                                }
                                return FReply::Handled();
                            }

                            if (ActionType == TEXT("rename_asset"))
                            {
                                FString TargetAssetPath;
                                FString NewName;
                                (*ArgumentsObject)->TryGetStringField(TEXT("asset_path"), TargetAssetPath);
                                (*ArgumentsObject)->TryGetStringField(TEXT("new_name"), NewName);

                                if (TargetAssetPath.IsEmpty() || NewName.IsEmpty())
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotIncompleteRenameArguments", "The rename action needs both `asset_path` and `new_name`."));
                                    }
                                    return FReply::Handled();
                                }

                                FString SelectionName, SelectionType, SelectedAssetPath, SelectedClassName;
                                if (!UE5CopilotAssistant::GetCurrentSelection(SelectionName, SelectionType, SelectedAssetPath, SelectedClassName) || SelectionType != TEXT("asset"))
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotRenameNeedsSelectedAsset", "Select the target asset in the Content Browser before executing a rename."));
                                    }
                                    return FReply::Handled();
                                }

                                if (SelectedAssetPath != TargetAssetPath)
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotRenameSelectionMismatch", "The currently selected asset does not match the previewed rename target."));
                                    }
                                    return FReply::Handled();
                                }

                                const EAppReturnType::Type ConfirmResult = FMessageDialog::Open(
                                    EAppMsgType::OkCancel,
                                    FText::FromString(FString::Printf(
                                        TEXT("Rename the selected asset\n\nFrom: %s\nTo: %s\n\nThis action will use Unreal editor APIs and should only be applied if the preview still looks correct."),
                                        *TargetAssetPath,
                                        *NewName))
                                );
                                if (ConfirmResult != EAppReturnType::Ok)
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotRenameCancelled", "Rename cancelled."));
                                    }
                                    return FReply::Handled();
                                }

                                const FSoftObjectPath SoftObjectPath(TargetAssetPath);
                                UObject* AssetObject = SoftObjectPath.TryLoad();
                                if (!AssetObject)
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotRenameLoadFailed", "The target asset could not be loaded for rename."));
                                    }
                                    return FReply::Handled();
                                }

                                const FString CurrentPackageName = FPackageName::ObjectPathToPackageName(TargetAssetPath);
                                const FString DestinationPackagePath = FPackageName::GetLongPackagePath(CurrentPackageName);
                                TArray<FAssetRenameData> RenameData;
                                RenameData.Emplace(AssetObject, DestinationPackagePath, NewName);

                                FAssetToolsModule& AssetToolsModule = FModuleManager::LoadModuleChecked<FAssetToolsModule>(TEXT("AssetTools"));
                                AssetToolsModule.Get().RenameAssets(RenameData);

                                const bool bRenameSucceeded = AssetObject->GetName() == NewName;
                                PendingEditorActionJson.Reset();
                                if (EditorActionPreviewTextBoxPtr.IsValid())
                                {
                                    EditorActionPreviewTextBoxPtr->SetText(
                                        bRenameSucceeded
                                            ? LOCTEXT("UE5CopilotEditorActionPreviewConsumed", "Rename action executed. No previewed editor action is pending.")
                                            : LOCTEXT("UE5CopilotEditorActionPreviewRenameUnverified", "Rename was attempted, but the plugin could not verify that the asset name changed.")
                                    );
                                }
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(
                                        bRenameSucceeded
                                            ? LOCTEXT("UE5CopilotRenameExecuted", "Rename action executed through Unreal editor APIs.")
                                            : LOCTEXT("UE5CopilotRenameUnverified", "Rename was attempted, but the result could not be verified. Check the Content Browser before continuing.")
                                    );
                                }
                                return FReply::Handled();
                            }

                            if (ActionType == TEXT("apply_code_patch_preview"))
                            {
                                FString TargetPath;
                                FString EditKind;
                                FString OriginalContentHash;
                                FString UpdatedContent;
                                FString UnifiedDiff;
                                (*ArgumentsObject)->TryGetStringField(TEXT("target_path"), TargetPath);
                                (*ArgumentsObject)->TryGetStringField(TEXT("edit_kind"), EditKind);
                                (*ArgumentsObject)->TryGetStringField(TEXT("original_content_hash"), OriginalContentHash);
                                (*ArgumentsObject)->TryGetStringField(TEXT("updated_content"), UpdatedContent);
                                (*ArgumentsObject)->TryGetStringField(TEXT("unified_diff"), UnifiedDiff);

                                if (TargetPath.IsEmpty() || EditKind.IsEmpty() || OriginalContentHash.IsEmpty() || UpdatedContent.IsEmpty())
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotIncompleteCodePatchArguments", "The code patch preview action requires `target_path`, `edit_kind`, `original_content_hash`, and `updated_content`."));
                                    }
                                    return FReply::Handled();
                                }

                                const EAppReturnType::Type ConfirmCodePatchResult = FMessageDialog::Open(
                                    EAppMsgType::OkCancel,
                                    FText::FromString(FString::Printf(
                                        TEXT("Apply previewed code patch\n\nFile: %s\nEdit Kind: %s\n\nThis will overwrite the target file inside the current Unreal project using the previewed diff. Review the diff in the output panel before continuing."),
                                        *TargetPath,
                                        *EditKind))
                                );
                                if (ConfirmCodePatchResult != EAppReturnType::Ok)
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotCodePatchCancelled", "Code patch apply cancelled."));
                                    }
                                    return FReply::Handled();
                                }

                                FString CodePatchError;
                                const bool bCodePatchSucceeded = UE5CopilotAssistant::ApplyPreviewCodePatch(TargetPath, EditKind, OriginalContentHash, UpdatedContent, CodePatchError);
                                PendingEditorActionJson.Reset();
                                if (EditorActionPreviewTextBoxPtr.IsValid())
                                {
                                    EditorActionPreviewTextBoxPtr->SetText(
                                        bCodePatchSucceeded
                                            ? LOCTEXT("UE5CopilotEditorActionPreviewCodePatchConsumed", "Code patch action executed. No previewed editor action is pending.")
                                            : LOCTEXT("UE5CopilotEditorActionPreviewCodePatchFailed", "Code patch execution failed. Review the status message for details.")
                                    );
                                }
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(
                                        bCodePatchSucceeded
                                            ? LOCTEXT("UE5CopilotCodePatchExecuted", "Previewed code patch written to the Unreal project.")
                                            : FText::FromString(CodePatchError.IsEmpty() ? TEXT("Code patch execution failed.") : CodePatchError)
                                    );
                                }
                                return FReply::Handled();
                            }

                            if (ActionType == TEXT("apply_code_patch_bundle_preview"))
                            {
                                const TArray<TSharedPtr<FJsonValue>>* FileEntries = nullptr;
                                if (!(*ArgumentsObject)->TryGetArrayField(TEXT("files"), FileEntries) || !FileEntries || FileEntries->Num() == 0)
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotIncompleteCodePatchBundleArguments", "The code patch bundle preview action requires a non-empty `files` array."));
                                    }
                                    return FReply::Handled();
                                }

                                const EAppReturnType::Type ConfirmCodePatchBundleResult = FMessageDialog::Open(
                                    EAppMsgType::OkCancel,
                                    FText::FromString(FString::Printf(
                                        TEXT("Apply previewed code patch bundle\n\nFiles: %d\n\nThis will overwrite each target file inside the current Unreal project using the previewed diffs. Review the Code Diff Preview pane before continuing."),
                                        FileEntries->Num()))
                                );
                                if (ConfirmCodePatchBundleResult != EAppReturnType::Ok)
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotCodePatchBundleCancelled", "Code patch bundle apply cancelled."));
                                    }
                                    return FReply::Handled();
                                }

                                FString CodePatchBundleError;
                                const bool bCodePatchBundleSucceeded = UE5CopilotAssistant::ApplyPreviewCodePatchBundle(*FileEntries, CodePatchBundleError);
                                PendingEditorActionJson.Reset();
                                if (EditorActionPreviewTextBoxPtr.IsValid())
                                {
                                    EditorActionPreviewTextBoxPtr->SetText(
                                        bCodePatchBundleSucceeded
                                            ? LOCTEXT("UE5CopilotEditorActionPreviewCodePatchBundleConsumed", "Code patch bundle executed. No previewed editor action is pending.")
                                            : LOCTEXT("UE5CopilotEditorActionPreviewCodePatchBundleFailed", "Code patch bundle execution failed. Review the status message for details.")
                                    );
                                }
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(
                                        bCodePatchBundleSucceeded
                                            ? LOCTEXT("UE5CopilotCodePatchBundleExecuted", "Previewed code patch bundle written to the Unreal project.")
                                            : FText::FromString(CodePatchBundleError.IsEmpty() ? TEXT("Code patch bundle execution failed.") : CodePatchBundleError)
                                    );
                                }
                                return FReply::Handled();
                            }

                            if (ActionType == TEXT("tweak_material_parameter"))
                            {
                                FString TargetAssetPath;
                                FString ParameterName;
                                FString ParameterType;
                                FString ParameterValue;
                                (*ArgumentsObject)->TryGetStringField(TEXT("asset_path"), TargetAssetPath);
                                (*ArgumentsObject)->TryGetStringField(TEXT("parameter_name"), ParameterName);
                                (*ArgumentsObject)->TryGetStringField(TEXT("parameter_type"), ParameterType);
                                (*ArgumentsObject)->TryGetStringField(TEXT("parameter_value"), ParameterValue);

                                if (TargetAssetPath.IsEmpty() || ParameterName.IsEmpty() || ParameterType.IsEmpty() || ParameterValue.IsEmpty())
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotIncompleteMaterialEditArguments", "The material-parameter action requires `asset_path`, `parameter_name`, `parameter_type`, and `parameter_value`."));
                                    }
                                    return FReply::Handled();
                                }

                                FString SelectionName, SelectionType, SelectedAssetPath, SelectedClassName;
                                if (!UE5CopilotAssistant::GetCurrentSelection(SelectionName, SelectionType, SelectedAssetPath, SelectedClassName) || SelectionType != TEXT("asset"))
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotMaterialEditNeedsSelectedAsset", "Select the target Material Instance in the Content Browser before executing a parameter edit."));
                                    }
                                    return FReply::Handled();
                                }

                                if (SelectedAssetPath != TargetAssetPath)
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotMaterialEditSelectionMismatch", "The currently selected asset does not match the previewed Material Instance target."));
                                    }
                                    return FReply::Handled();
                                }

                                const EAppReturnType::Type ConfirmMaterialEditResult = FMessageDialog::Open(
                                    EAppMsgType::OkCancel,
                                    FText::FromString(FString::Printf(
                                        TEXT("Edit a Material Instance parameter\n\nAsset: %s\nParameter: %s\nType: %s\nValue: %s\n\nThis action will update the selected Material Instance through Unreal editor APIs."),
                                        *TargetAssetPath,
                                        *ParameterName,
                                        *ParameterType,
                                        *ParameterValue))
                                );
                                if (ConfirmMaterialEditResult != EAppReturnType::Ok)
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotMaterialEditCancelled", "Material parameter edit cancelled."));
                                    }
                                    return FReply::Handled();
                                }

                                FString MaterialEditError;
                                const bool bMaterialEditSucceeded = UE5CopilotAssistant::TweakMaterialInstanceParameter(
                                    TargetAssetPath,
                                    ParameterName,
                                    ParameterType,
                                    ParameterValue,
                                    MaterialEditError
                                );
                                PendingEditorActionJson.Reset();
                                if (EditorActionPreviewTextBoxPtr.IsValid())
                                {
                                    EditorActionPreviewTextBoxPtr->SetText(
                                        bMaterialEditSucceeded
                                            ? LOCTEXT("UE5CopilotEditorActionPreviewMaterialEditConsumed", "Material parameter action executed. No previewed editor action is pending.")
                                            : LOCTEXT("UE5CopilotEditorActionPreviewMaterialEditFailed", "Material parameter execution failed. Review the status message for details.")
                                    );
                                }
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(
                                        bMaterialEditSucceeded
                                            ? LOCTEXT("UE5CopilotMaterialEditExecuted", "Material Instance parameter updated through Unreal editor APIs.")
                                            : FText::FromString(MaterialEditError.IsEmpty() ? TEXT("Material parameter execution failed.") : MaterialEditError)
                                    );
                                }
                                return FReply::Handled();
                            }

                            FString AssetKind;
                            FString AssetName;
                            FString PackagePath;
                            FString ParentClass;
                            FString ParentMaterial;
                            FString AssetClassName;
                            (*ArgumentsObject)->TryGetStringField(TEXT("asset_kind"), AssetKind);
                            (*ArgumentsObject)->TryGetStringField(TEXT("asset_name"), AssetName);
                            (*ArgumentsObject)->TryGetStringField(TEXT("package_path"), PackagePath);
                            (*ArgumentsObject)->TryGetStringField(TEXT("parent_class"), ParentClass);
                            (*ArgumentsObject)->TryGetStringField(TEXT("parent_material"), ParentMaterial);
                            (*ArgumentsObject)->TryGetStringField(TEXT("asset_class"), AssetClassName);

                            if (AssetName.IsEmpty() || PackagePath.IsEmpty())
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotIncompleteCreateArguments", "The create-asset action currently requires `asset_kind`, `asset_name`, and `package_path`."));
                                }
                                return FReply::Handled();
                            }

                            FString ConfirmationBody;
                            if (AssetKind == TEXT("blueprint_class"))
                            {
                                if (ParentClass.IsEmpty())
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotMissingCreateParentClass", "Blueprint create-asset actions require a `parent_class`."));
                                    }
                                    return FReply::Handled();
                                }
                                ConfirmationBody = FString::Printf(
                                    TEXT("Create a Blueprint asset\n\nName: %s\nPath: %s\nParent Class: %s\n\nThis action will create a new Blueprint asset through Unreal editor APIs."),
                                    *AssetName,
                                    *PackagePath,
                                    *ParentClass);
                            }
                            else if (AssetKind == TEXT("input_action"))
                            {
                                ConfirmationBody = FString::Printf(
                                    TEXT("Create an Input Action asset\n\nName: %s\nPath: %s\n\nThis action will create a new Enhanced Input Action asset through Unreal editor APIs."),
                                    *AssetName,
                                    *PackagePath);
                            }
                            else if (AssetKind == TEXT("input_mapping_context"))
                            {
                                ConfirmationBody = FString::Printf(
                                    TEXT("Create an Input Mapping Context asset\n\nName: %s\nPath: %s\n\nThis action will create a new Enhanced Input Mapping Context asset through Unreal editor APIs."),
                                    *AssetName,
                                    *PackagePath);
                            }
                            else if (AssetKind == TEXT("material_instance"))
                            {
                                ConfirmationBody = FString::Printf(
                                    TEXT("Create a Material Instance asset\n\nName: %s\nPath: %s\nParent Material: %s\n\nThis action will create a new Material Instance asset through Unreal editor APIs."),
                                    *AssetName,
                                    *PackagePath,
                                    ParentMaterial.IsEmpty() ? TEXT("None specified") : *ParentMaterial);
                            }
                            else if (AssetKind == TEXT("data_asset"))
                            {
                                if (AssetClassName.IsEmpty())
                                {
                                    if (StatusTextPtr.IsValid())
                                    {
                                        StatusTextPtr->SetText(LOCTEXT("UE5CopilotMissingDataAssetClass", "Data Asset create-asset actions require an `asset_class`."));
                                    }
                                    return FReply::Handled();
                                }
                                ConfirmationBody = FString::Printf(
                                    TEXT("Create a Data Asset\n\nName: %s\nPath: %s\nClass: %s\n\nThis action will create a new Data Asset through Unreal editor APIs."),
                                    *AssetName,
                                    *PackagePath,
                                    *AssetClassName);
                            }
                            else
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(FText::FromString(FString::Printf(TEXT("Create-asset execution is not implemented yet for `%s`."), *AssetKind)));
                                }
                                return FReply::Handled();
                            }

                            const EAppReturnType::Type ConfirmCreateResult = FMessageDialog::Open(
                                EAppMsgType::OkCancel,
                                FText::FromString(ConfirmationBody)
                            );
                            if (ConfirmCreateResult != EAppReturnType::Ok)
                            {
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotCreateCancelled", "Asset creation cancelled."));
                                }
                                return FReply::Handled();
                            }

                            FString CreateError;
                            bool bCreateSucceeded = false;
                            if (AssetKind == TEXT("blueprint_class"))
                            {
                                bCreateSucceeded = UE5CopilotAssistant::CreateBlueprintAsset(PackagePath, AssetName, ParentClass, CreateError);
                            }
                            else if (AssetKind == TEXT("data_asset"))
                            {
                                bCreateSucceeded = UE5CopilotAssistant::CreateDataAsset(PackagePath, AssetName, AssetClassName, CreateError);
                            }
                            else if (AssetKind == TEXT("material_instance"))
                            {
                                bCreateSucceeded = UE5CopilotAssistant::CreateMaterialInstanceAsset(PackagePath, AssetName, ParentMaterial, CreateError);
                            }
                            else
                            {
                                bCreateSucceeded = UE5CopilotAssistant::CreateEnhancedInputAsset(PackagePath, AssetName, AssetKind, CreateError);
                            }
                            PendingEditorActionJson.Reset();
                            if (EditorActionPreviewTextBoxPtr.IsValid())
                            {
                                EditorActionPreviewTextBoxPtr->SetText(
                                    bCreateSucceeded
                                        ? LOCTEXT("UE5CopilotEditorActionPreviewCreateConsumed", "Create-asset action executed. No previewed editor action is pending.")
                                        : LOCTEXT("UE5CopilotEditorActionPreviewCreateFailed", "Create-asset execution failed. Review the status message for details.")
                                );
                            }
                            if (StatusTextPtr.IsValid())
                            {
                                StatusTextPtr->SetText(
                                    bCreateSucceeded
                                        ? LOCTEXT("UE5CopilotCreateExecuted", "Asset created through Unreal editor APIs.")
                                        : FText::FromString(CreateError.IsEmpty() ? TEXT("Create-asset execution failed.") : CreateError)
                                );
                            }
                            return FReply::Handled();
                        })
                    ]

                    + SHorizontalBox::Slot()
                    .FillWidth(1.0f)
                    .Padding(4.0f, 0.0f, 0.0f, 0.0f)
                    [
                        SNew(SButton)
                        .Text(LOCTEXT("UE5CopilotClearPreviewedAction", "Clear Preview"))
                        .OnClicked_Lambda([this]()
                        {
                            CurrentAgentTaskId.Reset();
                            PendingEditorActionJson.Reset();
                            ClearPendingCodePatchBundleTargets();
                            if (CodeDiffPreviewTextBoxPtr.IsValid())
                            {
                                CodeDiffPreviewTextBoxPtr->SetText(LOCTEXT("UE5CopilotCodeDiffPreviewCleared", "No code diff preview yet."));
                            }
                            if (AgentSessionTextBoxPtr.IsValid())
                            {
                                AgentSessionTextBoxPtr->SetText(LOCTEXT("UE5CopilotAgentSessionPreviewCleared", "No live agent session yet."));
                            }
                            if (EditorActionPreviewTextBoxPtr.IsValid())
                            {
                                EditorActionPreviewTextBoxPtr->SetText(LOCTEXT("UE5CopilotEditorActionPreviewCleared", "No editor action proposed yet."));
                            }
                            if (StatusTextPtr.IsValid())
                            {
                                StatusTextPtr->SetText(LOCTEXT("UE5CopilotEditorActionPreviewClearedStatus", "Editor action preview cleared."));
                            }
                            return FReply::Handled();
                        })
                    ]
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SNew(STextBlock)
                    .Text(LOCTEXT("UE5CopilotDeepAnalysisHeader", "Deep Asset Analysis"))
                    .Font(FAppStyle::GetFontStyle("BoldFont"))
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SNew(STextBlock)
                    .Text(LOCTEXT("UE5CopilotDeepAnalysisHelp", "Paste exported graph or state text here only when the normal asset tools are not detailed enough."))
                    .AutoWrapText(true)
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SNew(SComboBox<TSharedPtr<FString>>)
                    .OptionsSource(&DeepAssetKinds)
                    .InitiallySelectedItem(SelectedDeepAssetKind)
                    .OnGenerateWidget_Lambda([](TSharedPtr<FString> Item)
                    {
                        return SNew(STextBlock).Text(FText::FromString(Item.IsValid() ? *Item : TEXT("")));
                    })
                    .OnSelectionChanged_Lambda([this](TSharedPtr<FString> NewValue, ESelectInfo::Type)
                    {
                        if (NewValue.IsValid())
                        {
                            SelectedDeepAssetKind = NewValue;
                        }
                    })
                    [
                        SNew(STextBlock)
                        .Text_Lambda([this]()
                        {
                            return FText::FromString(SelectedDeepAssetKind.IsValid() ? *SelectedDeepAssetKind : TEXT("blueprint"));
                        })
                    ]
                ]

                + SVerticalBox::Slot()
                .FillHeight(0.20f)
                .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                [
                    SAssignNew(DeepAssetTextBox, SMultiLineEditableTextBox)
                    .HintText(LOCTEXT("UE5CopilotDeepAssetHint", "Paste exported graph or state text for the selected asset here if you have it..."))
                ]

                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 8.0f)
                [
                    SNew(SButton)
                    .Text(LOCTEXT("UE5CopilotDeepAnalyze", "Run Deep Analysis"))
                    .OnClicked_Lambda([this, DeepAssetTextBox]()
                    {
                        const FString BaseUrl = UE5CopilotAssistant::NormalizeBaseUrl(BackendBaseUrlTextBoxPtr.IsValid() ? BackendBaseUrlTextBoxPtr->GetText().ToString() : FString());
                        FString ExportedText = DeepAssetTextBox.IsValid() ? DeepAssetTextBox->GetText().ToString() : FString();
                        if (BaseUrl.IsEmpty())
                        {
                            if (StatusTextPtr.IsValid())
                            {
                                StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusMissingDeepBaseUrl", "Enter a backend base URL first."));
                            }
                            return FReply::Handled();
                        }
                        CurrentBackendBaseUrl = BaseUrl;

                        FString SelectionName, SelectionType, AssetPath, ClassName;
                        if (!UE5CopilotAssistant::GetCurrentSelection(SelectionName, SelectionType, AssetPath, ClassName))
                        {
                            if (StatusTextPtr.IsValid())
                            {
                                StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusNoSelectionDeep", "Select an actor or asset before deep analysis."));
                            }
                            return FReply::Handled();
                        }

                        if (SelectionPreviewTextPtr.IsValid())
                        {
                            SelectionPreviewTextPtr->SetText(FText::FromString(FString::Printf(TEXT("Current selection: %s [%s]"), *SelectionName, *SelectionType)));
                        }

                        if (ExportedText.TrimStartAndEnd().IsEmpty() && SelectionType == TEXT("asset"))
                        {
                            FAssetData SelectedAssetData;
                            if (UE5CopilotAssistant::GetSelectedAssetData(SelectedAssetData))
                            {
                                ExportedText = UE5CopilotAssistant::BuildReflectedAssetSummary(SelectedAssetData);
                                if (StatusTextPtr.IsValid())
                                {
                                    StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusUsingFallbackDeepContext", "No pasted export text was provided, so the plugin is sending reflected property data from the selected asset."));
                                }
                            }
                        }

                        if (StatusTextPtr.IsValid())
                        {
                            StatusTextPtr->SetText(LOCTEXT("UE5CopilotStatusSendingDeep", "Sending deep asset analysis request..."));
                        }

                        EnsureBackendAndSendRequest(
                            BaseUrl + TEXT("/asset-deep-analysis"),
                            UE5CopilotAssistant::BuildDeepAssetPayload(
                                SelectedDeepAssetKind.IsValid() ? *SelectedDeepAssetKind : FString(TEXT("blueprint")),
                                ExportedText,
                                SelectionName,
                                AssetPath,
                                ClassName
                            ),
                            OutputTextBoxPtr,
                            AgentSessionTextBoxPtr,
                            CodeDiffPreviewTextBoxPtr,
                            EditorActionPreviewTextBoxPtr,
                            BundleApplyTargetPathTextBoxPtr,
                            &PendingEditorActionJson,
                            StatusTextPtr
                        );
                        return FReply::Handled();
                    })
                ]
                + SVerticalBox::Slot()
                .AutoHeight()
                .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                [
                    SNew(SExpandableArea)
                    .InitiallyCollapsed(true)
                    .AreaTitle(LOCTEXT("UE5CopilotPreviewGroupHeader", "Session And Previews"))
                    .BodyContent()
                    [
                        SNew(SVerticalBox)

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                        [
                            SNew(STextBlock)
                            .Text(LOCTEXT("UE5CopilotPreviewGroupHelp", "See the current agent session, code diff drafts, and previewed editor actions here."))
                            .AutoWrapText(true)
                        ]

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                        [
                            SNew(STextBlock)
                            .Text(LOCTEXT("UE5CopilotAgentSessionHeader", "Agent Session"))
                            .Font(FAppStyle::GetFontStyle("BoldFont"))
                        ]

                        + SVerticalBox::Slot()
                        .FillHeight(0.20f)
                        .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                        [
                            SAssignNew(AgentSessionTextBoxPtr, SMultiLineEditableTextBox)
                            .IsReadOnly(true)
                            .Text(LOCTEXT("UE5CopilotAgentSessionDefault", "No live agent session yet."))
                            .HintText(LOCTEXT("UE5CopilotAgentSessionHint", "Live agent-task state, next actions, and pending confirmations appear here."))
                        ]

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                        [
                            SNew(STextBlock)
                            .Text(LOCTEXT("UE5CopilotCodeDiffPreviewHeader", "Code Diff Preview"))
                            .Font(FAppStyle::GetFontStyle("BoldFont"))
                        ]

                        + SVerticalBox::Slot()
                        .FillHeight(0.28f)
                        .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                        [
                            SAssignNew(CodeDiffPreviewTextBoxPtr, SMultiLineEditableTextBox)
                            .IsReadOnly(true)
                            .HintText(LOCTEXT("UE5CopilotCodeDiffPreviewHint", "Previewed unified diffs appear here for narrow code patch drafts."))
                        ]

                        + SVerticalBox::Slot()
                        .AutoHeight()
                        .Padding(0.0f, 0.0f, 0.0f, 6.0f)
                        [
                            SNew(STextBlock)
                            .Text(LOCTEXT("UE5CopilotEditorActionPreviewHeader", "Editor Action Preview"))
                            .Font(FAppStyle::GetFontStyle("BoldFont"))
                        ]

                        + SVerticalBox::Slot()
                        .FillHeight(0.22f)
                        [
                            SAssignNew(EditorActionPreviewTextBoxPtr, SMultiLineEditableTextBox)
                            .IsReadOnly(true)
                            .HintText(LOCTEXT("UE5CopilotEditorActionPreviewHint", "Previewed editor actions appear here before you decide whether to apply them."))
                        ]
                    ]
                ]
                ]
                ]
            ]
        ]
    ]
];
}

void FUE5CopilotAssistantModule::SetCurrentAgentTaskId(const FString& TaskId)
{
    CurrentAgentTaskId = TaskId;
}

void FUE5CopilotAssistantModule::ClearCurrentAgentTaskId()
{
    CurrentAgentTaskId.Reset();
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FUE5CopilotAssistantModule, UE5CopilotAssistant)
