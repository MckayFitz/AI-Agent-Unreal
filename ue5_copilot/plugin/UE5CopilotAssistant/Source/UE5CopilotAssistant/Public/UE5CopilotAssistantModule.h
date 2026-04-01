#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

class FUE5CopilotAssistantModule : public IModuleInterface
{
public:
    virtual void StartupModule() override;
    virtual void ShutdownModule() override;

private:
    void RegisterMenus();
    TSharedRef<class SDockTab> SpawnAssistantTab(const class FSpawnTabArgs& SpawnTabArgs);
};
