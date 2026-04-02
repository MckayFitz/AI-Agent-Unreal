import re
from collections import Counter, defaultdict


CLASS_PATTERN = re.compile(
    r"\bclass\s+(?:\w+_API\s+)?([A-Za-z_]\w+)(?:\s*:\s*public\s+([A-Za-z_]\w+))?"
)
STRUCT_PATTERN = re.compile(r"\bstruct\s+(?:\w+_API\s+)?([A-Za-z_]\w+)")
ENUM_PATTERN = re.compile(r"\benum(?:\s+class)?\s+([A-Za-z_]\w+)")
MACRO_PATTERN = re.compile(r"^\s*#define\s+([A-Za-z_]\w+)", re.MULTILINE)
INCLUDE_PATTERN = re.compile(r'^\s*#include\s+[<"]([^">]+)[">]', re.MULTILINE)
FUNCTION_PATTERN = re.compile(
    r"^\s*(?:virtual\s+|static\s+|FORCEINLINE\s+|inline\s+)*"
    r"[\w:<>\*&,\s]+\s+([A-Za-z_]\w+)\s*\(([^;\n]*)\)\s*(?:const)?\s*(?:override)?\s*[{;]",
    re.MULTILINE,
)
UPROPERTY_PATTERN = re.compile(
    r"UPROPERTY\s*\(([^)]*)\)\s*([\w:<>\*\&\s,]+?)\s+([A-Za-z_]\w+)\s*(?:=[^;]+)?;",
    re.MULTILINE | re.DOTALL,
)
UFUNCTION_PATTERN = re.compile(
    r"UFUNCTION\s*\(([^)]*)\)\s*([\w:<>\*&\s,]+?)\s+([A-Za-z_]\w+)\s*\(",
    re.MULTILINE | re.DOTALL,
)
UCLASS_PATTERN = re.compile(r"UCLASS\s*\(([^)]*)\)", re.MULTILINE | re.DOTALL)
USTRUCT_PATTERN = re.compile(r"USTRUCT\s*\(([^)]*)\)", re.MULTILINE | re.DOTALL)
UENUM_PATTERN = re.compile(r"UENUM\s*\(([^)]*)\)", re.MULTILINE | re.DOTALL)
DELEGATE_PATTERN = re.compile(
    r"DECLARE_[A-Z0-9_]*DELEGATE(?:_[A-Z0-9_]+)?\s*\(\s*([A-Za-z_]\w+)",
    re.MULTILINE,
)

ROLE_RULES = {
    "ui": ("widget", "hud", "menu", "ui", "viewport", "screen", "wbp_"),
    "player": ("player", "pawn", "character", "controller"),
    "ai": ("ai", "behavior", "bt_", "blackboard", "perception", "enemy"),
    "combat": ("weapon", "damage", "combat", "ability", "projectile"),
    "animation": ("anim", "abp_", "montage"),
    "systems": ("manager", "subsystem", "service", "gameinstance", "gamemode"),
    "save": ("save", "load", "checkpoint", "profile"),
    "networking": ("replicate", "net", "server", "client", "multicast"),
    "input": ("enhancedinput", "inputaction", "inputmappingcontext", "bindaction", "ia_", "imc_"),
    "data": ("dataasset", "primarydataasset", "datatable", "da_"),
    "materials": ("material", "dynamicmaterial", "materialinstance", "mi_", "m_"),
    "effects": ("niagara", "niagarasystem", "niagaracomponent", "ns_"),
    "cinematics": ("levelsequence", "sequencer", "moviescene", "ls_"),
    "rigging": ("controlrig", "cr_", "rigvm"),
    "queries": ("envquery", "eqs", "eqs_"),
    "state": ("statetree", "state tree", "st_"),
}


def build_project_analysis(files, assets):
    analyzed_files = []
    annotated_assets = [annotate_asset(asset) for asset in assets]
    symbol_index = defaultdict(list)
    include_graph = defaultdict(set)
    inbound_references = Counter()

    for file_record in files:
        metadata = extract_file_metadata(file_record)
        analyzed = {**file_record, "analysis": metadata}
        analyzed_files.append(analyzed)

        for symbol_type in ("classes", "structs", "enums", "delegates", "properties", "functions", "macros"):
            for item in metadata.get(symbol_type, []):
                symbol = item["name"] if isinstance(item, dict) else item
                symbol_index[symbol.lower()].append(
                    {"path": file_record["path"], "type": symbol_type[:-1] if symbol_type.endswith("s") else symbol_type}
                )

        for include_name in metadata["includes"]:
            include_graph[file_record["path"]].add(include_name)
            inbound_references[include_name.lower()] += 1

    for file_record in analyzed_files:
        file_name_lower = file_record["name"].lower()
        inbound = inbound_references[file_name_lower]
        symbol_hits = 0
        for symbol in file_record["analysis"]["all_symbol_names"]:
            symbol_hits += len(symbol_index.get(symbol.lower(), []))
        file_record["analysis"]["centrality_score"] = inbound + symbol_hits

    blueprint_links = infer_blueprint_links(analyzed_files, annotated_assets)
    architecture = summarize_architecture(analyzed_files, annotated_assets, blueprint_links)

    return {
        "files": analyzed_files,
        "assets": annotated_assets,
        "symbol_index": dict(symbol_index),
        "blueprint_links": blueprint_links,
        "architecture": architecture,
    }


def extract_file_metadata(file_record):
    content = file_record.get("content", "")
    path = file_record.get("path", "")
    name = file_record.get("name", "")
    lowered = f"{path} {name}".lower()

    classes = []
    for class_name, base_class in CLASS_PATTERN.findall(content):
        classes.append(
            {
                "name": class_name,
                "base_class": base_class or "",
                "is_interface": class_name.startswith("I"),
            }
        )

    structs = [{"name": item} for item in STRUCT_PATTERN.findall(content)]
    enums = [{"name": item} for item in ENUM_PATTERN.findall(content)]
    macros = [{"name": item} for item in MACRO_PATTERN.findall(content)]
    delegates = [{"name": item} for item in DELEGATE_PATTERN.findall(content)]

    properties = []
    for specifiers, prop_type, prop_name in UPROPERTY_PATTERN.findall(content):
        properties.append(
            {
                "name": prop_name,
                "type": normalize_space(prop_type),
                "specifiers": [part.strip() for part in specifiers.split(",") if part.strip()],
            }
        )

    functions = []
    for specifiers, return_type, function_name in UFUNCTION_PATTERN.findall(content):
        functions.append(
            {
                "name": function_name,
                "return_type": normalize_space(return_type),
                "specifiers": [part.strip() for part in specifiers.split(",") if part.strip()],
            }
        )

    generic_functions = []
    for function_name, params in FUNCTION_PATTERN.findall(content):
        generic_functions.append(
            {
                "name": function_name,
                "signature_hint": normalize_space(params),
            }
        )

    unreal_flags = {
        "uclass_specifiers": extract_macro_specifiers(UCLASS_PATTERN, content),
        "ustruct_specifiers": extract_macro_specifiers(USTRUCT_PATTERN, content),
        "uenum_specifiers": extract_macro_specifiers(UENUM_PATTERN, content),
    }

    asset_links = infer_asset_links(path, name, content)
    roles = infer_roles(lowered, content)
    all_symbol_names = [
        item["name"]
        for group in (classes, structs, enums, delegates, properties, functions, generic_functions, macros)
        for item in group
    ]

    return {
        "classes": classes,
        "structs": structs,
        "enums": enums,
        "macros": macros,
        "delegates": delegates,
        "properties": properties,
        "functions": merge_function_lists(functions, generic_functions),
        "includes": INCLUDE_PATTERN.findall(content),
        "unreal_flags": unreal_flags,
        "line_count": len(content.splitlines()),
        "roles": roles,
        "asset_links": asset_links,
        "all_symbol_names": dedupe_preserve_order(all_symbol_names),
    }


def merge_function_lists(ufunctions, generic_functions):
    seen = {item["name"] for item in ufunctions}
    merged = list(ufunctions)
    for item in generic_functions:
        if item["name"] not in seen:
            merged.append(item)
    return merged


def extract_macro_specifiers(pattern, content):
    specifiers = []
    for match in pattern.findall(content):
        parts = [part.strip() for part in match.split(",") if part.strip()]
        specifiers.extend(parts)
    return dedupe_preserve_order(specifiers)


def normalize_space(text):
    return " ".join(text.split())


def dedupe_preserve_order(values):
    seen = set()
    ordered = []
    for value in values:
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(value)
    return ordered


def infer_roles(lowered_path, content):
    role_hits = []
    lowered_content = content.lower()
    for role, tokens in ROLE_RULES.items():
        if any(token in lowered_path or token in lowered_content for token in tokens):
            role_hits.append(role)
    return role_hits


def infer_asset_links(path, name, content):
    hints = []
    lowered = f"{path} {name} {content}".lower()

    if "blueprintcallable" in lowered or "blueprintimplementableevent" in lowered or "blueprintnativeevent" in lowered:
        hints.append("exposes_blueprint_hooks")
    if "blueprintable" in lowered or "blueprinttype" in lowered:
        hints.append("blueprint_friendly_type")
    if "editanywhere" in lowered or "blueprintreadwrite" in lowered:
        hints.append("editable_in_blueprint")

    return dedupe_preserve_order(hints)


def infer_blueprint_links(files, assets):
    asset_candidates = [annotate_asset(asset) for asset in assets]
    links = []

    for file_record in files:
        analysis = file_record["analysis"]
        class_names = [item["name"] for item in analysis["classes"]]
        if not class_names:
            continue

        exposed_functions = [
            item["name"]
            for item in analysis["functions"]
            if any(spec.startswith("Blueprint") for spec in item.get("specifiers", []))
        ]
        editable_properties = [
            item["name"]
            for item in analysis["properties"]
            if any("Blueprint" in spec or "Edit" in spec for spec in item.get("specifiers", []))
        ]

        for class_name in class_names:
            likely_blueprints = []
            class_stem = class_name.lower().lstrip("au")
            class_tokens = extract_name_tokens(class_name)
            for asset in asset_candidates:
                asset_name = asset["name"].rsplit(".", 1)[0].lower()
                asset_tokens = extract_name_tokens(asset_name)
                if (
                    asset_name.endswith(class_stem)
                    or class_stem in asset_name
                    or (class_tokens and asset_tokens and len(class_tokens.intersection(asset_tokens)) >= 2)
                ):
                    likely_blueprints.append(asset)

            if analysis["asset_links"] or likely_blueprints:
                links.append(
                    {
                        "class_name": class_name,
                        "path": file_record["path"],
                        "blueprint_hooks": dedupe_preserve_order(analysis["asset_links"]),
                        "exposed_functions": exposed_functions,
                        "editable_properties": editable_properties,
                        "likely_blueprints": likely_blueprints[:6],
                    }
                )

    return links


def annotate_asset(asset):
    asset_copy = dict(asset)
    asset_copy["family"] = infer_asset_family(asset_copy["name"], asset_copy["path"])
    return asset_copy


def infer_asset_family(name, path):
    lowered = f"{name} {path}".lower()
    if "metasound" in lowered or "ms_" in lowered:
        return "metasound"
    if "pcg" in lowered:
        return "pcg"
    if "motionmatching" in lowered or "motion_matching" in lowered or "mm_" in lowered:
        return "motion_matching"
    if "ikrig" in lowered or "ik_rig" in lowered or "ikr_" in lowered:
        return "ik_rig"
    if "st_" in lowered or "statetree" in lowered:
        return "state_tree"
    if "cr_" in lowered or "controlrig" in lowered:
        return "control_rig"
    if "ns_" in lowered or "niagara" in lowered:
        return "niagara"
    if "eqs_" in lowered or "envquery" in lowered or "eqs" in lowered:
        return "eqs"
    if "ls_" in lowered or "levelsequence" in lowered or "sequencer" in lowered or "moviescene" in lowered:
        return "sequencer"
    if "ia_" in lowered or "inputaction" in lowered:
        return "enhanced_input"
    if "imc_" in lowered or "mappingcontext" in lowered:
        return "enhanced_input"
    if "bt_" in lowered or "behaviortree" in lowered:
        return "behavior_tree"
    if "bb_" in lowered or "blackboard" in lowered:
        return "blackboard"
    if "da_" in lowered or "dataasset" in lowered:
        return "data_asset"
    if "mi_" in lowered:
        return "material_instance"
    if "m_" in lowered or "material" in lowered:
        return "material"
    if "wbp_" in lowered or "widget" in lowered or "hud" in lowered or "menu" in lowered:
        return "ui"
    if "bpi_" in lowered or "bp_" in lowered or "blueprint" in lowered:
        return "blueprint"
    if "abp_" in lowered or "anim" in lowered:
        return "animation"
    if "weapon" in lowered or "rifle" in lowered or "gun" in lowered:
        return "weapon"
    if "enemy" in lowered or "ai" in lowered or "npc" in lowered:
        return "ai"
    if "character" in lowered or "player" in lowered or "pawn" in lowered:
        return "character"
    if "game" in lowered and "mode" in lowered:
        return "game_mode"
    if "controller" in lowered:
        return "controller"
    return "general"


def summarize_specialized_assets(files, assets):
    families = {
        "blueprint": [],
        "enhanced_input": [],
        "behavior_tree": [],
        "blackboard": [],
        "data_asset": [],
        "material": [],
        "material_instance": [],
        "animation": [],
        "ui": [],
        "state_tree": [],
        "control_rig": [],
        "niagara": [],
        "eqs": [],
        "sequencer": [],
        "metasound": [],
        "pcg": [],
        "motion_matching": [],
        "ik_rig": [],
    }

    for asset in assets:
        family = asset.get("family", "general")
        if family in families:
            families[family].append(asset)

    code_signals = {
        "blueprint": find_family_code_signals(
            files,
            ("Blueprint", "Blueprintable", "BlueprintReadWrite", "BlueprintCallable", "TSubclassOf", "SpawnActor", "FClassFinder", "UBlueprintGeneratedClass")
        ),
        "enhanced_input": find_family_code_signals(
            files,
            ("EnhancedInput", "UInputAction", "UInputMappingContext", "BindAction", "AddMappingContext", "EnhancedInputComponent", "EnhancedInputSubsystem")
        ),
        "behavior_tree": find_family_code_signals(
            files,
            ("BehaviorTree", "Blackboard", "UBTTask", "UBTService", "UBTDecorator", "UBlackboardComponent", "RunBehaviorTree", "UseBlackboard")
        ),
        "data_asset": find_family_code_signals(
            files,
            ("UDataAsset", "UPrimaryDataAsset", "DataAsset", "PrimaryDataAsset", "TSoftObjectPtr", "TSoftClassPtr")
        ),
        "material": find_family_code_signals(
            files,
            ("UMaterial", "UMaterialInstance", "UMaterialInterface", "CreateDynamicMaterialInstance", "SetScalarParameterValue", "SetVectorParameterValue", "MaterialParameterCollection")
        ),
        "animation": find_family_code_signals(
            files,
            ("UAnimInstance", "AnimMontage", "AnimationBlueprint", "PlayAnimMontage", "BlendSpace", "AnimNotify")
        ),
        "state_tree": find_family_code_signals(
            files,
            ("StateTree", "UStateTree", "StateTreeComponent", "FStateTreeReference", "StateTreeTask", "StateTreeEvaluator", "StateTreeCondition")
        ),
        "control_rig": find_family_code_signals(
            files,
            ("ControlRig", "UControlRig", "RigVM", "ControlRigComponent", "URigHierarchy", "ControlRigBlueprint")
        ),
        "niagara": find_family_code_signals(
            files,
            ("Niagara", "UNiagaraSystem", "UNiagaraComponent", "SpawnSystemAtLocation", "SpawnSystemAttached", "SetNiagaraVariable", "NiagaraFunctionLibrary")
        ),
        "eqs": find_family_code_signals(
            files,
            ("EnvQuery", "EQS", "UEnvQuery", "UEnvQueryManager", "RunEQSQuery", "FEnvQueryRequest", "EnvQueryContext")
        ),
        "sequencer": find_family_code_signals(
            files,
            ("LevelSequence", "ULevelSequence", "MovieScene", "SequencePlayer", "Sequencer", "ALevelSequenceActor", "ULevelSequencePlayer")
        ),
        "metasound": find_family_code_signals(
            files,
            ("MetaSound", "UMetaSoundSource", "UMetaSoundPatch", "AudioComponent", "SetFloatParameter", "SetWaveParameter")
        ),
        "pcg": find_family_code_signals(
            files,
            ("PCG", "UPCGComponent", "UPCGGraph", "Generate", "Cleanup", "Procedural Content Generation")
        ),
        "motion_matching": find_family_code_signals(
            files,
            ("MotionMatching", "PoseSearch", "UPoseSearchDatabase", "MotionTrajectory", "Chooser", "AnimNode_MotionMatching")
        ),
        "ik_rig": find_family_code_signals(
            files,
            ("IKRig", "UIKRigDefinition", "UIKRetargeter", "FullBodyIK", "IKGoal", "Retarget")
        ),
    }

    summaries = {
        "blueprints": build_family_summary(
            "blueprints",
            "Blueprint Classes",
            families["blueprint"] + families["ui"],
            code_signals["blueprint"],
            "These assets likely represent Blueprint-authored gameplay classes, designer logic, or UI-facing Blueprint types.",
            [
                "Look for owning C++ base classes, spawned actor references, and Blueprint-facing functions together.",
                "Blueprint classes often bridge designer-authored flow with reusable C++ systems.",
            ],
            [
                "Too much gameplay logic in Blueprint can make ownership and performance harder to reason about.",
                "Review variable exposure and class inheritance when Blueprint behavior feels scattered.",
            ]
        ),
        "enhanced_input": build_family_summary(
            "enhanced_input",
            "Enhanced Input",
            families["enhanced_input"],
            code_signals["enhanced_input"],
            "Input actions and mapping contexts likely define modern player input bindings.",
            [
                "Look for Input Actions, Mapping Contexts, and subsystem setup together.",
                "Player Controller, Pawn, and Character files often share ownership of input flow.",
            ],
            [
                "Check whether mapping contexts are added at the right lifecycle moment.",
                "Watch for duplicated bindings across pawn and controller layers.",
            ]
        ),
        "behavior_trees": build_family_summary(
            "behavior_trees",
            "Behavior Trees / Blackboards",
            families["behavior_tree"] + families["blackboard"],
            code_signals["behavior_tree"],
            "These assets and files likely drive AI decision flow, tasks, and blackboard state.",
            [
                "Behavior Trees usually coordinate services, decorators, and tasks around Blackboard keys.",
                "AIController and pawn/enemy classes are common entry points for tree execution.",
            ],
            [
                "Confirm Blackboard keys stay in sync with task expectations.",
                "Service-heavy trees can become noisy if too much logic is hidden outside tasks.",
            ]
        ),
        "data_assets": build_family_summary(
            "data_assets",
            "Data Assets",
            families["data_asset"],
            code_signals["data_asset"],
            "These assets usually hold designer-authored configuration or content data.",
            [
                "Data Assets are often used to separate tuning values from gameplay code.",
                "Soft references are common when assets should load lazily or remain decoupled.",
            ],
            [
                "Validate that runtime code handles missing or null data assets clearly.",
                "Large data hierarchies can hide ownership unless naming is consistent.",
            ]
        ),
        "materials": build_family_summary(
            "materials",
            "Materials",
            families["material"] + families["material_instance"],
            code_signals["material"],
            "These assets and files likely control visuals, parameter updates, or dynamic material behavior.",
            [
                "Look for dynamic material instance creation near actor/component initialization.",
                "Material parameter collections often indicate globally coordinated visuals.",
            ],
            [
                "Repeated dynamic material creation can be wasteful if instances are not reused.",
                "Parameter updates in Tick should be reviewed for cost and necessity.",
            ]
        ),
        "animbps": build_family_summary(
            "animbps",
            "Animation Blueprints",
            families["animation"],
            code_signals["animation"],
            "These assets and files likely drive animation state, montages, and animation graph logic.",
            [
                "AnimBPs often consume movement/combat state from the pawn or character.",
                "Montages, notifies, and anim instance variables usually form the gameplay bridge.",
            ],
            [
                "Duplicating gameplay state in both character code and anim code can drift over time.",
                "Montage-driven gameplay events should be audited for race conditions.",
            ]
        ),
        "state_trees": build_family_summary(
            "state_trees",
            "StateTrees",
            families["state_tree"],
            code_signals["state_tree"],
            "These assets and files likely drive hierarchical gameplay state logic and decision flow.",
            [
                "StateTrees usually centralize conditions, evaluators, and tasks around explicit state transitions.",
                "They often replace sprawling Tick or ad hoc state logic with a structured runtime graph.",
            ],
            [
                "State ownership can become unclear if code still duplicates the same transitions elsewhere.",
                "Evaluator/task boundaries should stay small so debugging remains tractable.",
            ]
        ),
        "control_rig": build_family_summary(
            "control_rig",
            "Control Rig",
            families["control_rig"],
            code_signals["control_rig"],
            "These assets and files likely support runtime or editor rig logic and procedural animation controls.",
            [
                "Control Rig often sits between animation authoring and runtime procedural adjustment.",
                "Look for rig components, hierarchy access, and animation pipeline glue code.",
            ],
            [
                "Be careful about mixing editor-only rig assumptions into runtime code.",
                "Procedural rig updates can become expensive if evaluated too broadly.",
            ]
        ),
        "niagara": build_family_summary(
            "niagara",
            "Niagara",
            families["niagara"],
            code_signals["niagara"],
            "These assets and files likely control particle, VFX, and spawned visual systems.",
            [
                "Niagara systems are usually spawned from gameplay events, weapon fire, movement, or damage responses.",
                "Function library calls and variable-setting code often reveal effect ownership.",
            ],
            [
                "Transient effect spam can become a gameplay and performance problem quickly.",
                "Audit whether spawned systems need pooling, attachment, or explicit cleanup.",
            ]
        ),
        "eqs": build_family_summary(
            "eqs",
            "EQS",
            families["eqs"],
            code_signals["eqs"],
            "These assets and files likely support environmental queries for AI decision-making.",
            [
                "EQS is commonly used for target selection, cover queries, and position scoring.",
                "AIController and behavior logic usually coordinate the query request lifecycle.",
            ],
            [
                "Frequent or redundant queries can be expensive without careful timing.",
                "Context mismatches can make query results look random or brittle.",
            ]
        ),
        "sequencer": build_family_summary(
            "sequencer",
            "Sequencer",
            families["sequencer"],
            code_signals["sequencer"],
            "These assets and files likely drive cinematics, scripted sequences, or timeline-based events.",
            [
                "LevelSequence actors and players usually indicate cinematic or scripted event ownership.",
                "Sequencer often coordinates camera work, animation, and one-off gameplay presentation.",
            ],
            [
                "Watch for gameplay logic hidden inside cinematic flow that needs runtime-safe fallbacks.",
                "Sequence timing can conflict with multiplayer or stateful systems if not gated carefully.",
            ]
        ),
        "metasounds": build_family_summary(
            "metasounds",
            "MetaSounds",
            families["metasound"],
            code_signals["metasound"],
            "These assets and files likely drive procedural or parameterized audio behavior.",
            [
                "Look for audio component setup, runtime parameter writes, and event-driven playback paths together.",
                "MetaSounds often bridge gameplay state into reactive sound design through named parameters.",
            ],
            [
                "Audio parameters can silently drift from gameplay intent if names or update timing stop matching.",
                "Heavy procedural audio graphs should be reviewed when many actors can trigger them at once.",
            ]
        ),
        "pcg": build_family_summary(
            "pcg",
            "PCG",
            families["pcg"],
            code_signals["pcg"],
            "These assets and files likely control procedural content generation setup and runtime generation triggers.",
            [
                "Look for PCG component ownership, graph assignment, and generation trigger timing together.",
                "PCG often bridges authored rules with runtime or editor generation passes.",
            ],
            [
                "Generation timing and cleanup ownership can become expensive or confusing if multiple systems trigger the same graph.",
                "Procedural outputs can hide dependencies on tags, landscape layers, or source actors that are easy to miss.",
            ]
        ),
        "motion_matching": build_family_summary(
            "motion_matching",
            "Motion Matching",
            families["motion_matching"],
            code_signals["motion_matching"],
            "These assets and files likely support pose-search driven locomotion or animation selection.",
            [
                "Look for pose databases, chooser/trajectory inputs, and character locomotion state together.",
                "Motion matching usually sits at the boundary between movement state and animation selection.",
            ],
            [
                "Bad trajectory or state inputs can make motion-matched animation look noisy or unstable.",
                "Pose databases and chooser logic can drift from gameplay movement assumptions over time.",
            ]
        ),
        "ik_rig": build_family_summary(
            "ik_rig",
            "IK Rig / Retargeting",
            families["ik_rig"],
            code_signals["ik_rig"],
            "These assets and files likely support IK setup, retargeting, or runtime pose adjustment.",
            [
                "Look for rig definitions, retarget assets, and character skeletal-mesh ownership together.",
                "IK assets often bridge authored skeleton data into runtime pose correction or retargeting paths.",
            ],
            [
                "IK assumptions can fail subtly when skeletons, goals, or retarget profiles drift apart.",
                "Runtime IK updates can become expensive if they are evaluated more broadly than needed.",
            ]
        ),
    }

    for key, summary in summaries.items():
        summary.update(build_deep_family_details(key, summary, assets, files))

    return summaries


def find_matching_assets(assets, selection, limit=8):
    selection_lower = (selection or "").strip().lower()
    if not selection_lower:
        return []

    scored = []
    for asset in assets:
        name = asset.get("name", "")
        path = asset.get("path", "")
        relative_path = asset.get("relative_path", "")
        stem = name.rsplit(".", 1)[0]
        name_lower = name.lower()
        path_lower = path.lower()
        relative_path_lower = relative_path.lower()
        stem_lower = stem.lower()
        score = 0

        if selection_lower == stem_lower:
            score += 14
        if selection_lower == name_lower:
            score += 12
        if selection_lower == path_lower:
            score += 14
        if selection_lower == relative_path_lower:
            score += 14
        if path_lower.endswith(selection_lower):
            score += 10
        if relative_path_lower.endswith(selection_lower):
            score += 10
        if name_lower.startswith(selection_lower):
            score += 8
        if selection_lower in stem_lower:
            score += 6
        if selection_lower in name_lower:
            score += 4
        if selection_lower in path_lower:
            score += 3
        if selection_lower in relative_path_lower:
            score += 3

        if score > 0:
            scored.append(
                {
                    **asset,
                    "match_score": score,
                }
            )

    scored.sort(key=lambda item: (item["match_score"], len(item.get("name", ""))), reverse=True)
    return scored[:limit]


def build_asset_details(selection, asset, files, assets, blueprint_links, family_summaries=None):
    family_summaries = family_summaries or summarize_specialized_assets(files, assets)
    family_summary = family_summaries.get(resolve_asset_summary_key(asset))
    stem = asset.get("name", "").rsplit(".", 1)[0]
    reference_terms = build_asset_reference_terms(asset)
    references = merge_reference_results(files, reference_terms)
    linked_cpp = infer_asset_specific_cpp_links(asset, files, blueprint_links, family_summary)
    depending_files = collect_depending_files(references)
    asset_type = humanize_asset_type(asset.get("asset_type") or asset.get("family") or "asset")
    does_this_do = infer_asset_purpose_notes(asset, family_summary, linked_cpp)
    looks_wrong = infer_asset_problem_notes(asset, family_summary, references, linked_cpp)
    missing = infer_asset_missing_notes(asset, family_summary, references, linked_cpp)

    return {
        "selection": selection,
        "selection_type": "asset",
        "asset": {
            "name": asset.get("name", ""),
            "path": asset.get("path", ""),
            "asset_type": asset.get("asset_type", ""),
            "family": asset.get("family", ""),
            "likely_blueprint": asset.get("likely_blueprint", False),
        },
        "resolved_asset_name": stem or asset.get("name", ""),
        "asset_type_label": asset_type,
        "family_key": resolve_asset_summary_key(asset),
        "title": f"{stem or asset.get('name', 'Asset')} ({asset_type})",
        "summary": build_asset_summary_text(asset, family_summary, linked_cpp),
        "what_does_this_do": does_this_do,
        "gameplay_role": (family_summary or {}).get("role_guess", "No strong gameplay role was inferred yet."),
        "linked_cpp_classes": linked_cpp,
        "references": references,
        "depending_files": depending_files,
        "what_depends_on_it": [item["reason"] for item in depending_files[:6]],
        "what_looks_wrong": looks_wrong,
        "related_assets": infer_related_assets(asset, assets),
        "what_is_missing": missing,
        "what_it_might_be_missing": missing,
    }


def resolve_asset_summary_key(asset):
    family = (asset.get("family") or "").lower()
    asset_type = (asset.get("asset_type") or "").lower()
    if family in {"blueprint", "ui"} or "blueprint" in asset_type:
        return "blueprints"
    if family == "animation" or "animation_blueprint" in asset_type:
        return "animbps"
    if family == "metasound":
        return "metasounds"
    if family == "pcg":
        return "pcg"
    if family == "motion_matching":
        return "motion_matching"
    if family == "ik_rig":
        return "ik_rig"
    if family in {"behavior_tree", "blackboard"}:
        return "behavior_trees"
    if family == "data_asset":
        return "data_assets"
    if family in {"material", "material_instance"}:
        return "materials"
    if family == "enhanced_input":
        return "enhanced_input"
    return family


def build_asset_reference_terms(asset):
    name = asset.get("name", "")
    stem = name.rsplit(".", 1)[0]
    terms = [stem, name]
    for separator in ("_", " "):
        if separator in stem:
            terms.extend(part for part in stem.split(separator) if len(part) >= 3)
    return dedupe_preserve_order([term for term in terms if term and len(term) >= 3])


def merge_reference_results(files, terms, max_results=8):
    merged_exact = {}
    merged_semantic = {}

    for term in terms[:4]:
        result = find_references(files, term, max_results=max_results)
        for match in result.get("exact_matches", []):
            current = merged_exact.setdefault(
                match["path"],
                {"path": match["path"], "name": match["name"], "count": 0, "hits": []},
            )
            current["count"] += match.get("count", 0)
            current["hits"].extend(match.get("hits", []))
        for match in result.get("semantic_matches", []):
            current = merged_semantic.setdefault(
                match["path"],
                {"path": match["path"], "name": match["name"], "likely_symbols": [], "preview": match.get("preview", "")},
            )
            current["likely_symbols"].extend(match.get("likely_symbols", []))
            if not current.get("preview") and match.get("preview"):
                current["preview"] = match["preview"]

    exact_matches = list(merged_exact.values())
    for item in exact_matches:
        item["hits"] = item["hits"][:10]
    exact_matches.sort(key=lambda item: item["count"], reverse=True)

    semantic_matches = list(merged_semantic.values())
    for item in semantic_matches:
        item["likely_symbols"] = dedupe_preserve_order(item["likely_symbols"])[:8]
    semantic_matches.sort(key=lambda item: len(item["likely_symbols"]), reverse=True)

    return {
        "exact_matches": exact_matches[:max_results],
        "semantic_matches": semantic_matches[:max_results],
    }


def infer_asset_specific_cpp_links(asset, files, blueprint_links, family_summary=None):
    stem = asset.get("name", "").rsplit(".", 1)[0].lower()
    stem_tokens = extract_name_tokens(stem)
    scored = {}

    for item in blueprint_links:
        class_name_lower = item["class_name"].lower()
        class_tokens = extract_name_tokens(class_name_lower)
        names = [bp.get("name", "").rsplit(".", 1)[0].lower() for bp in item.get("likely_blueprints", [])]
        if stem and any(stem == name or stem in name or name in stem for name in names):
            scored[item["class_name"]] = {
                "class_name": item["class_name"],
                "path": item.get("path", ""),
                "reason": "Matched inferred Blueprint pairing.",
                "score": 12 + len(item.get("blueprint_hooks", [])),
            }
            continue
        if stem_tokens and class_tokens and len(stem_tokens.intersection(class_tokens)) >= 2:
            scored[item["class_name"]] = {
                "class_name": item["class_name"],
                "path": item.get("path", ""),
                "reason": "Matched class and asset naming tokens.",
                "score": 10 + len(item.get("exposed_functions", [])) + len(item.get("editable_properties", [])),
            }

    for file_record in files:
        path_lower = file_record.get("path", "").lower()
        content_lower = file_record.get("content", "").lower()
        analysis = file_record.get("analysis", {})
        class_hits = []
        for class_info in analysis.get("classes", []):
            class_tokens = extract_name_tokens(class_info["name"])
            if stem_tokens and class_tokens and stem_tokens.intersection(class_tokens):
                class_hits.append(class_info["name"])

        if stem and stem in f"{path_lower} {content_lower}" or class_hits:
            analysis = file_record.get("analysis", {})
            for class_info in analysis.get("classes", []):
                class_name = class_info["name"]
                entry = scored.setdefault(
                    class_name,
                    {
                        "class_name": class_name,
                        "path": file_record.get("path", ""),
                        "reason": "Asset name appears in this file.",
                        "score": 0,
                    },
                )
                entry["score"] += 6 if class_name in class_hits else 4

            if analysis.get("asset_links"):
                for class_info in analysis.get("classes", []):
                    entry = scored.setdefault(
                        class_info["name"],
                        {
                            "class_name": class_info["name"],
                            "path": file_record.get("path", ""),
                            "reason": "Blueprint-facing Unreal metadata detected in this file.",
                            "score": 0,
                        },
                    )
                    entry["score"] += len(analysis["asset_links"])

    ranked = sorted(scored.values(), key=lambda item: item["score"], reverse=True)
    supporting = [item["class_name"] for item in ranked[:6]]
    primary = ranked[0] if ranked else None
    fallback = family_summary.get("linked_cpp_classes", {}) if family_summary else {}

    return {
        "primary_owner": primary["class_name"] if primary else fallback.get("primary_owner", "None"),
        "primary_owner_path": primary["path"] if primary else fallback.get("primary_owner_path", "None"),
        "primary_owner_reason": primary["reason"] if primary else fallback.get("primary_owner_reason", "No ranked owner was inferred."),
        "runtime_classes": supporting or fallback.get("runtime_classes", []),
        "supporting_classes": supporting[1:6] if len(supporting) > 1 else fallback.get("supporting_classes", []),
    }


def collect_depending_files(references):
    exact = references.get("exact_matches", [])
    semantic = references.get("semantic_matches", [])
    items = []
    for match in exact[:5]:
        items.append(
            {
                "path": match["path"],
                "reason": f"{match['count']} exact reference hit(s) for the asset name.",
            }
        )
    for match in semantic[:3]:
        if any(existing["path"] == match["path"] for existing in items):
            continue
        items.append(
            {
                "path": match["path"],
                "reason": "File has related symbol or filename signals that likely depend on the asset.",
            }
        )
    return items[:8]


def infer_related_assets(asset, assets):
    family = asset.get("family", "")
    stem = asset.get("name", "").rsplit(".", 1)[0].lower()
    related = []
    for candidate in assets:
        if candidate.get("path") == asset.get("path"):
            continue
        if candidate.get("family") != family:
            continue
        candidate_stem = candidate.get("name", "").rsplit(".", 1)[0]
        candidate_lower = candidate_stem.lower()
        if stem and (stem in candidate_lower or candidate_lower in stem):
            related.append({"name": candidate["name"], "path": candidate["path"], "family": candidate.get("family", "")})
        elif len(related) < 4:
            related.append({"name": candidate["name"], "path": candidate["path"], "family": candidate.get("family", "")})
    return related[:6]


def infer_asset_purpose_notes(asset, family_summary, linked_cpp):
    notes = []
    family = (asset.get("family") or "").lower()
    owner = linked_cpp.get("primary_owner", "None")

    if family in {"blueprint", "ui"}:
        notes.append("This asset likely defines designer-authored gameplay or UI behavior on top of a parent class.")
    elif family == "animation":
        notes.append("This asset likely converts gameplay state into animation states, transitions, montages, or blend behavior.")
    elif family in {"behavior_tree", "blackboard"}:
        notes.append("This asset likely drives AI decisions, blackboard state, and task flow for an AI controller or pawn.")
    elif family == "data_asset":
        notes.append("This asset likely stores designer-editable gameplay data or tuning values that runtime code reads.")
    elif family in {"material", "material_instance"}:
        notes.append("This asset likely controls runtime visuals through textures, material instances, or parameter updates.")
    elif family == "enhanced_input":
        notes.append("This asset likely defines player input actions, mappings, and trigger behavior.")

    if family_summary:
        notes.extend(family_summary.get("usage_notes", [])[:2])
    if owner and owner != "None":
        notes.append(f"{owner} looks like the strongest C++ owner or bridge for this asset.")
    return dedupe_preserve_order(notes)[:5]


def infer_asset_problem_notes(asset, family_summary, references, linked_cpp):
    notes = []
    family = (asset.get("family") or "").lower()

    if not references.get("exact_matches"):
        notes.append("No exact code references were found, which can mean the asset is unhooked, indirectly loaded, or only connected through other assets.")
    if linked_cpp.get("primary_owner", "None") == "None":
        notes.append("No clear C++ owner was inferred yet, so ownership may be too implicit right now.")

    if family == "enhanced_input":
        notes.append("Input assets are easy to misconfigure when the action exists but the mapping context is never added for the active player.")
    elif family in {"behavior_tree", "blackboard"}:
        notes.append("Behavior Tree issues often come from blackboard keys, start-up timing, or services/decorators hiding too much logic.")
    elif family == "animation":
        notes.append("AnimBP issues often come from character state not being updated before the animation graph reads it.")
    elif family in {"material", "material_instance"}:
        notes.append("Material issues often come from wrong parameter names, repeated dynamic instance creation, or updates happening in the wrong place.")
    elif family == "data_asset":
        notes.append("DataAsset issues often come from the wrong asset being assigned or null/default handling being too weak.")
    elif family in {"blueprint", "ui"}:
        notes.append("Blueprint issues often come from spawn paths, parent classes, or exposed defaults not matching runtime assumptions.")

    if family_summary:
        notes.extend(family_summary.get("risks", [])[:2])
    return dedupe_preserve_order(notes)[:5]


def infer_asset_missing_notes(asset, family_summary, references, linked_cpp=None):
    notes = []
    if not references.get("exact_matches"):
        notes.append("No exact code references were found, so this asset may be unhooked, indirectly loaded, or only referenced from other assets.")
    linked_cpp = linked_cpp or (family_summary or {}).get("linked_cpp_classes", {})
    if not linked_cpp.get("primary_owner") or linked_cpp.get("primary_owner") == "None":
        notes.append("No obvious owning C++ class was inferred yet.")
    if asset.get("family") == "enhanced_input":
        notes.append("Confirm a mapping context is added at runtime, not just created in content.")
        notes.append("Check that the intended pawn/controller layer actually binds the input action.")
    if asset.get("family") in {"behavior_tree", "blackboard"}:
        notes.append("Confirm the expected blackboard keys, services, and startup path are all present.")
    if asset.get("family") == "animation":
        notes.append("Check whether the expected state variables, transitions, or montage triggers are actually fed from gameplay code.")
    if asset.get("family") == "data_asset":
        notes.append("Confirm the asset is assigned in the owning class and that fallback/default handling exists for incomplete data.")
    if asset.get("family") in {"material", "material_instance"}:
        notes.append("Check whether runtime parameter names and dynamic material instance setup are actually present.")
    if asset.get("family") in {"blueprint", "ui"}:
        notes.append("Check whether the intended parent class, exposed variables, and spawn path are all wired together.")
    return notes[:4]


def build_asset_summary_text(asset, family_summary, linked_cpp):
    asset_type = humanize_asset_type(asset.get("asset_type") or asset.get("family") or "asset")
    role = (family_summary or {}).get("role_guess", "")
    owner = linked_cpp.get("primary_owner", "None")
    summary = [f"This selected asset looks like a {asset_type.lower()}."]
    if role:
        summary.append(role)
    if owner and owner != "None":
        summary.append(f"It most likely connects to C++ through {owner}.")
    return " ".join(summary)


def humanize_asset_type(value):
    lowered = (value or "asset").replace("_", " ").strip().lower()
    mapping = {
        "animation blueprint": "AnimBP",
        "input action": "Input Action",
        "input mapping context": "Input Mapping Context",
        "widget blueprint": "Widget Blueprint",
        "blueprint interface": "Blueprint Interface",
        "data asset": "DataAsset",
        "behavior tree": "Behavior Tree",
        "material instance": "Material Instance",
        "metasound": "MetaSound",
        "pcg": "PCG",
        "motion matching": "Motion Matching",
        "ik rig": "IK Rig",
    }
    return mapping.get(lowered, " ".join(part.capitalize() for part in lowered.split()))


def infer_deep_asset_kind(asset=None, selection_name="", asset_path="", asset_kind=""):
    explicit = (asset_kind or "").strip().lower()
    if explicit and explicit not in {"auto", "detect", "auto_detect"}:
        return explicit

    asset_type = ((asset or {}).get("asset_type") or "").strip().lower()
    family = ((asset or {}).get("family") or "").strip().lower()
    haystack = " ".join(
        part for part in [
            asset_type,
            family,
            (asset or {}).get("name", ""),
            (asset or {}).get("path", ""),
            selection_name,
            asset_path,
        ] if part
    ).lower()

    if any(token in haystack for token in ("animation_blueprint", "animbp", "abp_", "anim blueprint")):
        return "animbp"
    if any(token in haystack for token in ("behavior_tree", "behaviortree", "bt_", "blackboard", "bb_")):
        return "behavior_tree"
    if any(token in haystack for token in ("input_action", "input_mapping_context", "enhanced_input", "ia_", "imc_", "mappingcontext")):
        return "enhanced_input"
    if any(token in haystack for token in ("metasound", "meta_sound", "ms_")):
        return "metasound"
    if any(token in haystack for token in ("pcg", "procedural content generation")):
        return "pcg"
    if any(token in haystack for token in ("motionmatching", "motion_matching", "pose search", "posesearch", "mm_")):
        return "motion_matching"
    if any(token in haystack for token in ("state_tree", "statetree", "st_")):
        return "state_tree"
    if any(token in haystack for token in ("control_rig", "controlrig", "cr_")):
        return "control_rig"
    if any(token in haystack for token in ("niagara", "niagara_system", "ns_")):
        return "niagara"
    if any(token in haystack for token in ("eqs", "envquery", "eqs_")):
        return "eqs"
    if any(token in haystack for token in ("sequencer", "levelsequence", "movie scene", "moviescene", "ls_")):
        return "sequencer"
    if any(token in haystack for token in ("ik_rig", "ikrig", "retarget", "ikr_")):
        return "ik_rig"
    if any(token in haystack for token in ("data_asset", "dataasset", "primarydataasset", "da_")):
        return "data_asset"
    if any(token in haystack for token in ("material_instance", "material", "mi_", "m_")):
        return "material"
    if any(token in haystack for token in ("blueprint", "bp_", "wbp_", "bpi_")):
        return "blueprint"
    return ""


def find_family_code_signals(files, terms):
    signals = []
    for file_record in files:
        haystack = f"{file_record['path']} {file_record['name']} {file_record.get('content', '')}".lower()
        matched = [term for term in terms if term.lower() in haystack]
        if matched:
            signals.append(
                {
                    "path": file_record["path"],
                    "matches": matched[:6],
                    "symbols": file_record["analysis"]["all_symbol_names"][:8],
                    "score": len(matched) * 3 + file_record["analysis"].get("centrality_score", 0),
                }
            )
    signals.sort(key=lambda item: item["score"], reverse=True)
    return signals[:12]


def build_family_summary(family_key, title, assets, signals, description, usage_notes=None, risks=None):
    role_guess = infer_family_role(title, assets, signals)
    confidence = infer_family_confidence(assets, signals)
    owner_files = build_owner_files(signals)
    linked_cpp_classes = infer_linked_cpp_classes(family_key, signals)
    related_families = infer_related_families(family_key, assets, signals)
    likely_entry_points = infer_likely_entry_points(family_key, signals)
    workflow_chain = infer_family_workflow_chain(family_key)
    return {
        "family_key": family_key,
        "title": title,
        "description": description,
        "role_guess": role_guess,
        "confidence": confidence,
        "asset_count": len(assets),
        "signal_count": len(signals),
        "assets": [{"name": asset["name"], "path": asset["path"], "type": asset.get("asset_type", "")} for asset in assets[:12]],
        "code_signals": signals[:10],
        "owner_files": owner_files,
        "linked_cpp_classes": linked_cpp_classes,
        "related_families": related_families,
        "likely_entry_points": likely_entry_points,
        "workflow_chain": workflow_chain,
        "usage_notes": usage_notes or [],
        "risks": risks or [],
    }


def infer_family_role(title, assets, signals):
    lowered = title.lower()
    if "blueprint" in lowered:
        return "This appears to support Blueprint-authored gameplay classes, designer-authored flow, or Blueprint-based integration on top of C++ systems."
    if "statetree" in lowered:
        return "This appears to support StateTree-driven state logic and structured gameplay decision flow."
    if "control rig" in lowered:
        return "This appears to support rig logic, procedural animation control, or editor rig tooling."
    if "niagara" in lowered:
        return "This appears to support Niagara VFX systems, spawned effects, and runtime particle behavior."
    if "eqs" in lowered:
        return "This appears to support environmental query evaluation for AI choices and target selection."
    if "sequencer" in lowered:
        return "This appears to support level sequences, cinematic events, or time-based scripted presentation."
    if "input" in lowered:
        return "This appears to support Enhanced Input actions, mapping contexts, and player control bindings."
    if "behavior" in lowered:
        return "This appears to support AI logic, behavior-tree execution, and blackboard-driven decisions."
    if "data asset" in lowered:
        return "This appears to support structured gameplay data that designers can edit without changing code."
    if "material" in lowered:
        return "This appears to support rendering setup, material instances, or runtime visual parameter changes."
    if "animation" in lowered:
        return "This appears to support animation state, montage playback, or character animation flow."
    if assets or signals:
        return "This family has meaningful Unreal-specific signals in the current project."
    return "No strong signals were detected for this family yet."


def infer_family_confidence(assets, signals):
    score = len(assets) * 2 + len(signals)
    if score >= 10:
        return "high"
    if score >= 4:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def build_owner_files(signals):
    return [
        {
            "path": item["path"],
            "reason": ", ".join(item.get("matches", [])[:3]) or "matched family signals",
            "score": item.get("score", 0),
        }
        for item in signals[:5]
    ]


def infer_linked_cpp_classes(family_key, signals):
    scored = {}
    for item in signals:
        signal_score = item.get("score", 0)
        raw_path = item.get("path", "")
        path = raw_path.lower()
        for symbol in item.get("symbols", []):
            if not looks_like_cpp_class(symbol):
                continue
            reason_parts = []
            score = signal_score + class_priority_bonus(symbol, path, family_key, reason_parts)
            current = scored.get(symbol)
            candidate = {
                "score": score,
                "path": raw_path,
                "reason": "; ".join(reason_parts) if reason_parts else "matched strong family signals",
            }
            if current is None or candidate["score"] > current["score"]:
                scored[symbol] = candidate

    ordered = sorted(scored.items(), key=lambda pair: pair[1]["score"], reverse=True)
    ordered_names = [name for name, _ in ordered]

    primary_owner = ordered_names[0] if ordered_names else None
    runtime_classes = [name for name in ordered_names if is_runtime_focused_class(name)][:8]
    support_classes = [name for name in ordered_names if name not in runtime_classes][:8]
    primary_details = scored.get(primary_owner) if primary_owner else None

    return {
        "primary_owner": primary_owner,
        "primary_owner_path": primary_details["path"] if primary_details else None,
        "primary_owner_reason": primary_details["reason"] if primary_details else None,
        "primary_owner_confidence": infer_owner_confidence(primary_details["score"] if primary_details else 0),
        "runtime_classes": runtime_classes,
        "supporting_classes": support_classes,
        "all_classes": ordered_names[:12],
    }


def looks_like_cpp_class(symbol):
    if not symbol:
        return False
    if symbol[0] not in {"A", "U", "F", "I", "S"}:
        return False
    if len(symbol) < 3:
        return False
    return symbol[1].isupper() or symbol.startswith("UInput") or symbol.startswith("UNiagara")


def class_priority_bonus(symbol, path, family_key, reason_parts=None):
    bonus = 0
    if is_runtime_focused_class(symbol):
        bonus += 5
        if reason_parts is not None:
            reason_parts.append("runtime-focused Unreal class")
    if any(token in path for token in ("editor", "factory", "customization", "detail")):
        bonus -= 3
        if reason_parts is not None:
            reason_parts.append("editor-oriented path penalty")
    if symbol.startswith("A") or symbol.startswith("U"):
        bonus += 2
        if reason_parts is not None:
            reason_parts.append("Actor/UObject-style class")
    bonus += family_class_bonus(symbol, path, family_key, reason_parts)
    return bonus


def is_runtime_focused_class(symbol):
    runtime_prefixes = ("A", "U")
    support_prefixes = ("F", "I", "S")
    if symbol.startswith(runtime_prefixes):
        return True
    if symbol.startswith(support_prefixes):
        return False
    return False


def family_class_bonus(symbol, path, family_key, reason_parts=None):
    symbol_lower = symbol.lower()
    bonus = 0

    family_preferences = {
        "enhanced_input": ("playercontroller", "controller", "character", "pawn", "input", "localplayer"),
        "behavior_trees": ("aicontroller", "controller", "character", "pawn", "enemy", "blackboard"),
        "eqs": ("aicontroller", "controller", "character", "pawn", "enemy", "query"),
        "animbps": ("animinstance", "character", "pawn", "mesh", "movement"),
        "control_rig": ("controlrig", "character", "skeletal", "mesh", "rig"),
        "state_trees": ("component", "controller", "character", "pawn", "state"),
        "niagara": ("component", "actor", "weapon", "projectile", "effect", "fx"),
        "materials": ("component", "actor", "character", "mesh", "material"),
        "sequencer": ("levelsequence", "sequenceplayer", "actor", "camera", "cinematic"),
        "data_assets": ("manager", "subsystem", "component", "data", "settings"),
        "metasounds": ("audio", "component", "sound", "music", "voice"),
        "pcg": ("pcg", "component", "generator", "world", "level"),
        "motion_matching": ("character", "movement", "anim", "pose", "trajectory"),
        "ik_rig": ("skeletal", "mesh", "anim", "rig", "retarget"),
    }

    penalties = {
        "enhanced_input": ("widget", "hud", "menu"),
        "behavior_trees": ("widget", "hud", "menu"),
        "eqs": ("widget", "hud", "menu"),
        "animbps": ("manager", "settings"),
        "control_rig": ("manager", "settings"),
        "niagara": ("settings",),
        "sequencer": ("settings",),
    }

    for token in family_preferences.get(family_key, ()):
        if token in symbol_lower or token in path:
            bonus += 4
            if reason_parts is not None:
                reason_parts.append(f"matches {family_key} ownership pattern: {token}")

    for token in penalties.get(family_key, ()):
        if token in symbol_lower or token in path:
            bonus -= 2
            if reason_parts is not None:
                reason_parts.append(f"less likely owner pattern: {token}")

    if family_key in {"behavior_trees", "eqs"} and symbol.startswith("A"):
        bonus += 2
    if family_key == "animbps" and ("anim" in symbol_lower or symbol.startswith("U")):
        bonus += 3
    if family_key in {"niagara", "materials"} and "component" in symbol_lower:
        bonus += 3
    if family_key == "sequencer" and ("sequence" in symbol_lower or "camera" in symbol_lower):
        bonus += 3

    return bonus


def infer_owner_confidence(score):
    if score >= 22:
        return "high"
    if score >= 12:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def infer_related_families(family_key, assets, signals):
    text = " ".join(
        [asset.get("name", "") for asset in assets] +
        [signal.get("path", "") + " " + " ".join(signal.get("matches", [])) for signal in signals]
    ).lower()

    relationships = {
        "enhanced_input": ["player", "ui", "data_assets"],
        "behavior_trees": ["eqs", "state_trees", "niagara"],
        "data_assets": ["enhanced_input", "materials", "niagara"],
        "materials": ["niagara", "sequencer", "animbps"],
        "animbps": ["control_rig", "state_trees", "materials"],
        "state_trees": ["behavior_trees", "eqs", "animbps"],
        "control_rig": ["animbps", "sequencer"],
        "niagara": ["materials", "sequencer", "behavior_trees"],
        "eqs": ["behavior_trees", "state_trees"],
        "sequencer": ["niagara", "control_rig", "materials"],
        "metasounds": ["sequencer", "materials", "animbps"],
        "pcg": ["state_trees", "niagara", "materials"],
        "motion_matching": ["animbps", "control_rig", "ik_rig"],
        "ik_rig": ["control_rig", "animbps", "motion_matching"],
    }

    result = []
    for relation in relationships.get(family_key, []):
        result.append(relation)

    if "widget" in text or "hud" in text:
        result.append("ui")
    if "weapon" in text or "damage" in text:
        result.append("combat")
    if "player" in text or "character" in text:
        result.append("player")

    return dedupe_preserve_order(result)


def infer_likely_entry_points(family_key, signals):
    path_hints = []
    for signal in signals[:8]:
        path = signal.get("path", "")
        lowered = path.lower()
        if any(token in lowered for token in ("controller", "character", "pawn", "player")):
            path_hints.append(f"{path} looks like a runtime gameplay entry point.")
        if any(token in lowered for token in ("component", "subsystem", "manager")):
            path_hints.append(f"{path} looks like a reusable owner or coordinator for this family.")
        if any(token in lowered for token in ("widget", "hud", "menu")):
            path_hints.append(f"{path} may surface this family into UI or player-facing flow.")

    defaults = {
        "enhanced_input": ["Look in PlayerController, Character, Pawn, and local-player subsystem setup first."],
        "behavior_trees": ["Look in AIController startup and enemy/pawn setup for Behavior Tree execution."],
        "data_assets": ["Look in managers, subsystems, or gameplay classes that load configuration at startup."],
        "materials": ["Look in actor/component construction and visual-effect update code first."],
        "animbps": ["Look in character movement/combat code and anim instance variables first."],
        "state_trees": ["Look in owning components or controllers that initialize state logic."],
        "control_rig": ["Look in animation pipeline or character rig setup code first."],
        "niagara": ["Look in gameplay event handlers that spawn effects or attach components."],
        "eqs": ["Look in AIController, behavior tasks, or target-selection code first."],
        "sequencer": ["Look in sequence actor/player setup and scripted event triggers first."],
        "metasounds": ["Look in audio component setup and gameplay event handlers that push sound parameters first."],
        "pcg": ["Look in PCG component ownership and generation trigger points first."],
        "motion_matching": ["Look in character locomotion code, trajectory generation, and anim node setup first."],
        "ik_rig": ["Look in skeletal mesh setup, retarget ownership, and animation pipeline glue first."],
    }

    return dedupe_preserve_order(path_hints + defaults.get(family_key, []))[:6]


def infer_family_workflow_chain(family_key):
    chains = {
        "enhanced_input": ["Input Action", "Mapping Context", "Controller/Pawn binding", "Gameplay reaction"],
        "behavior_trees": ["AIController", "Blackboard", "Behavior Tree", "Task/Service/Decorator", "AI action"],
        "data_assets": ["Data Asset", "Loader/manager", "Gameplay class", "Runtime tuning or content use"],
        "materials": ["Material asset", "Dynamic material instance", "Parameter update", "Visible gameplay feedback"],
        "animbps": ["Character state", "Anim instance variables", "Anim graph or montage", "On-screen animation result"],
        "state_trees": ["Owner/component", "StateTree", "Evaluator/Condition", "Task", "Gameplay state transition"],
        "control_rig": ["Rig asset", "Rig component or anim pipeline", "Control update", "Pose/animation output"],
        "niagara": ["Gameplay event", "Niagara spawn/setup", "Variable update", "Visible effect"],
        "eqs": ["AI request", "Context", "Query execution", "Scored result", "Decision/action"],
        "sequencer": ["Trigger", "LevelSequence actor/player", "Track evaluation", "Cinematic/gameplay event"],
        "metasounds": ["Gameplay event", "Audio component/MetaSound", "Parameter update", "Audible feedback"],
        "pcg": ["Source actors/data", "PCG graph", "Generation trigger", "Spawned/generated result"],
        "motion_matching": ["Movement state", "Trajectory input", "Pose search/database", "Animation selection"],
        "ik_rig": ["Skeleton/mesh", "IK Rig or retarget asset", "Goal/solver update", "Pose result"],
    }
    return chains.get(family_key, [])


def build_deep_family_details(family_key, summary, all_assets, files):
    return {
        "linked_assets": infer_linked_assets(summary, all_assets),
        "bridge_points": infer_bridge_points(family_key, summary),
        "debugging_checklist": infer_debugging_checklist(family_key, summary),
    }


def infer_linked_assets(summary, all_assets):
    family_assets = summary.get("assets", [])
    if not family_assets:
        return []

    seed_tokens = set()
    for asset in family_assets:
        seed_tokens.update(extract_name_tokens(asset["name"]))

    linked = []
    for asset in all_assets:
        asset_name = asset.get("name", "")
        asset_family = asset.get("family", "")
        if any(token in extract_name_tokens(asset_name) for token in seed_tokens):
            linked.append(
                {
                    "name": asset_name,
                    "family": asset_family,
                    "path": asset.get("path", ""),
                }
            )

    filtered = []
    seen = set()
    for item in linked:
        key = (item["name"].lower(), item["family"])
        if key in seen:
            continue
        seen.add(key)
        filtered.append(item)
    return filtered[:12]


def extract_name_tokens(name):
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]+", name.lower())
    return {token for token in tokens if len(token) > 2}


def infer_bridge_points(family_key, summary):
    owner_files = summary.get("owner_files", [])
    file_paths = [item["path"].lower() for item in owner_files]
    bridges = []

    if family_key == "blueprints":
        bridges.append("Blueprint parent classes, spawned actor paths, and exposed variables likely form the main runtime bridge.")
        if any("character" in path or "actor" in path or "component" in path for path in file_paths):
            bridges.append("Actor/component code looks like the strongest bridge into this Blueprint family.")

    if family_key in {"behavior_trees", "eqs"}:
        if any("controller" in path for path in file_paths):
            bridges.append("AIController files likely bridge asset logic into runtime behavior.")
        bridges.append("Look for Blackboard keys or query results being translated into actions or movement targets.")

    if family_key in {"animbps", "control_rig"}:
        bridges.append("Character or pawn state likely feeds animation/control variables across the gameplay-animation boundary.")
        if any("character" in path or "pawn" in path for path in file_paths):
            bridges.append("Character-facing code looks like the strongest bridge into the animation pipeline.")

    if family_key == "enhanced_input":
        bridges.append("PlayerController, Pawn, and local-player subsystem setup likely share the input bridge.")

    if family_key == "state_trees":
        bridges.append("A component, subsystem, or controller likely initializes the StateTree and consumes transitions.")

    if family_key == "niagara":
        bridges.append("Gameplay events such as weapon fire, impacts, or movement bursts likely trigger Niagara systems.")

    if family_key == "sequencer":
        bridges.append("Sequence player setup and trigger logic likely bridge cinematics into gameplay or UI.")

    if family_key == "materials":
        bridges.append("Actors/components likely bridge material parameters to runtime visual feedback.")

    if family_key == "metasounds":
        bridges.append("Gameplay events and audio component parameters likely bridge runtime state into MetaSound playback.")

    if family_key == "pcg":
        bridges.append("A component, actor, or world-generation owner likely bridges PCG graphs into spawned content.")

    if family_key in {"motion_matching", "ik_rig"}:
        bridges.append("Character movement and skeletal-animation state likely bridge these assets into runtime pose selection or correction.")

    return dedupe_preserve_order(bridges)


def infer_debugging_checklist(family_key, summary):
    checklist = []

    if family_key == "blueprints":
        checklist.extend([
            "Confirm the expected parent class and spawn path are actually used at runtime.",
            "Check exposed variables/default values before assuming the graph logic is wrong.",
            "Inspect Blueprint-callable hooks and event flow where gameplay hands off from C++.",
        ])
    elif family_key == "enhanced_input":
        checklist.extend([
            "Verify the expected Mapping Context is added for the active player.",
            "Confirm the Input Action is bound on the correct controller/pawn layer.",
            "Check for duplicate or overridden bindings across ownership layers.",
        ])
    elif family_key == "behavior_trees":
        checklist.extend([
            "Confirm the Behavior Tree actually starts on the expected AIController.",
            "Validate Blackboard keys exist and are written before tasks/services need them.",
            "Inspect decorators and services first when behavior looks inconsistent.",
        ])
    elif family_key == "eqs":
        checklist.extend([
            "Verify the EQS context and query parameters match the intended target/search space.",
            "Check how often the query runs and whether stale results are reused safely.",
            "Inspect the controller/task that consumes the scored results.",
        ])
    elif family_key == "animbps":
        checklist.extend([
            "Check the anim instance variables that bridge gameplay state into the AnimBP.",
            "Inspect montage triggers and notifies when gameplay timing feels off.",
            "Confirm the owning character updates state before the animation graph reads it.",
        ])
    elif family_key == "state_trees":
        checklist.extend([
            "Confirm the StateTree owner initializes the asset and required context data.",
            "Inspect evaluator and condition outputs before assuming task logic is wrong.",
            "Check for duplicate state logic still living outside the StateTree.",
        ])
    elif family_key == "control_rig":
        checklist.extend([
            "Verify runtime code is not depending on editor-only rig assumptions.",
            "Inspect the rig component or animation pipeline stage that updates controls.",
            "Check whether pose/control updates are happening more often than necessary.",
        ])
    elif family_key == "niagara":
        checklist.extend([
            "Verify the effect spawn path is actually called by the gameplay event you expect.",
            "Check attachment, pooling, and cleanup when effects persist too long or never appear.",
            "Inspect Niagara variable setup if the effect plays but looks wrong.",
        ])
    elif family_key == "sequencer":
        checklist.extend([
            "Confirm the LevelSequence actor/player is created and triggered when expected.",
            "Check whether sequence timing conflicts with gameplay state or replication.",
            "Inspect bound objects and track ownership when only parts of the sequence work.",
        ])
    elif family_key == "materials":
        checklist.extend([
            "Verify dynamic material instances are created once and reused.",
            "Check parameter names and update timing if visuals do not react.",
            "Inspect Tick-driven parameter updates for unnecessary cost.",
        ])
    elif family_key == "metasounds":
        checklist.extend([
            "Verify the intended gameplay event actually triggers the MetaSound playback path.",
            "Check parameter names and update timing if the sound plays but does not react as expected.",
            "Inspect the owning audio component or sound manager before assuming the asset graph is wrong.",
        ])
    elif family_key == "pcg":
        checklist.extend([
            "Confirm the PCG graph is assigned to the expected component or actor owner.",
            "Check what event or lifecycle moment triggers generation and cleanup.",
            "Inspect source actors, tags, or terrain/context inputs before assuming the graph logic is wrong.",
        ])
    elif family_key == "motion_matching":
        checklist.extend([
            "Verify trajectory and locomotion inputs are updated before pose selection runs.",
            "Check the pose database/chooser assumptions when animation selection feels unstable.",
            "Inspect the owning character and anim pipeline before blaming the database alone.",
        ])
    elif family_key == "ik_rig":
        checklist.extend([
            "Confirm the correct rig or retarget asset is assigned to the expected skeletal mesh path.",
            "Check goal/solver assumptions when limbs or retargeted poses look subtly wrong.",
            "Inspect character mesh, skeleton, and retarget profile compatibility before changing solver values.",
        ])
    elif family_key == "data_assets":
        checklist.extend([
            "Confirm the correct Data Asset is loaded and assigned at runtime.",
            "Check soft-reference loading behavior if data appears missing intermittently.",
            "Inspect fallback/default handling for null or incomplete data.",
        ])

    return checklist


def summarize_architecture(files, assets, blueprint_links):
    role_counter = Counter()
    central_files = []

    for file_record in files:
        role_counter.update(file_record["analysis"]["roles"])
        central_files.append(
            {
                "path": file_record["path"],
                "score": file_record["analysis"]["centrality_score"],
                "symbols": file_record["analysis"]["all_symbol_names"][:8],
            }
        )

    central_files.sort(key=lambda item: item["score"], reverse=True)
    assets_by_family = Counter(asset["family"] for asset in assets)

    overview = []
    if role_counter:
        overview.append(
            "This project appears to be organized around "
            + ", ".join(f"{role} ({count})" for role, count in role_counter.most_common(5))
            + "."
        )
    if blueprint_links:
        overview.append(
            f"{len(blueprint_links)} C++ classes look intentionally exposed to Blueprints or likely paired with Blueprint assets."
        )
    if assets_by_family:
        overview.append(
            "Blueprint-aware asset families detected: "
            + ", ".join(f"{family} ({count})" for family, count in assets_by_family.most_common(5))
            + "."
        )

    return {
        "overview": overview,
        "systems": [{"name": role, "count": count} for role, count in role_counter.most_common()],
        "high_centrality_files": central_files[:8],
        "asset_families": [{"name": family, "count": count} for family, count in assets_by_family.most_common()],
    }


def find_references(files, query, max_results=30):
    query_lower = query.lower().strip()
    if not query_lower:
        return {"exact_matches": [], "semantic_matches": []}

    exact_matches = []
    semantic_matches = []

    for file_record in files:
        content = file_record.get("content", "")
        if not content:
            continue

        file_exact_hits = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            lowered = line.lower()
            if query_lower in lowered:
                file_exact_hits.append(
                    {
                        "line": line_number,
                        "preview": line.strip()[:240],
                    }
                )

        analysis = file_record.get("analysis", {})
        symbol_hits = [
            symbol
            for symbol in analysis.get("all_symbol_names", [])
            if query_lower in symbol.lower() and symbol.lower() != query_lower
        ]

        if file_exact_hits:
            exact_matches.append(
                {
                    "path": file_record["path"],
                    "name": file_record["name"],
                    "count": len(file_exact_hits),
                    "hits": file_exact_hits[:10],
                }
            )
        elif symbol_hits or query_lower in file_record["name"].lower():
            semantic_matches.append(
                {
                    "path": file_record["path"],
                    "name": file_record["name"],
                    "likely_symbols": dedupe_preserve_order(symbol_hits)[:8],
                    "preview": make_semantic_preview(file_record, query),
                }
            )

    exact_matches.sort(key=lambda item: item["count"], reverse=True)
    semantic_matches.sort(key=lambda item: len(item["likely_symbols"]), reverse=True)

    return {
        "exact_matches": exact_matches[:max_results],
        "semantic_matches": semantic_matches[:max_results],
    }


def make_semantic_preview(file_record, query):
    content = file_record.get("content", "")
    lowered = content.lower()
    query_lower = query.lower()
    index = lowered.find(query_lower[: max(3, min(len(query_lower), 12))])
    if index == -1:
        return content[:220].strip()
    start = max(0, index - 100)
    end = min(len(content), index + 120)
    return content[start:end].strip()


def build_file_explanation(file_record, mode="beginner"):
    analysis = file_record["analysis"]
    class_names = ", ".join(item["name"] for item in analysis["classes"][:5]) or "No major classes detected"
    function_names = ", ".join(item["name"] for item in analysis["functions"][:8]) or "No major functions detected"
    dependencies = ", ".join(analysis["includes"][:8]) or "No include dependencies detected"
    unreal_bits = []
    for key, values in analysis["unreal_flags"].items():
        if values:
            unreal_bits.append(f"{key}: {', '.join(values[:6])}")
    if analysis["asset_links"]:
        unreal_bits.append(", ".join(analysis["asset_links"]))

    role_summary = ", ".join(analysis["roles"]) or "general gameplay/system code"
    line_count = analysis["line_count"]
    refactor_notes = infer_refactor_notes(file_record)
    risk_notes = infer_risk_notes(file_record)

    if mode == "technical":
        purpose = (
            f"This file looks like {role_summary} with {line_count} lines. "
            f"It defines {class_names} and exposes {function_names}."
        )
    elif mode == "refactor":
        purpose = (
            f"This file likely supports {role_summary}. Focus review on function size, coupling, and Unreal macro exposure."
        )
    else:
        purpose = (
            f"This file appears to help with {role_summary}. "
            f"The main things to look at are {class_names} and {function_names}."
        )

    return {
        "path": file_record["path"],
        "what_it_is_for": purpose,
        "main_classes_functions": {
            "classes": [item["name"] for item in analysis["classes"][:8]],
            "functions": [item["name"] for item in analysis["functions"][:12]],
            "properties": [item["name"] for item in analysis["properties"][:12]],
        },
        "important_unreal_pieces": unreal_bits or ["No strong Unreal macro usage detected"],
        "dependencies": analysis["includes"][:12] or [dependencies],
        "potential_risks": risk_notes,
        "gameplay_connections": build_gameplay_connections(file_record),
        "refactor_notes": refactor_notes,
    }


def infer_refactor_notes(file_record):
    content = file_record.get("content", "")
    analysis = file_record["analysis"]
    notes = []

    if analysis["line_count"] > 400:
        notes.append("Large file size suggests this may be doing more than one job.")
    if len(analysis["functions"]) > 18:
        notes.append("This file exposes many functions, which may be a signal to split responsibilities.")
    if "tick(" in content.lower() or "tickcomponent(" in content.lower():
        notes.append("Tick-based behavior is present; validate whether event-driven alternatives are possible.")
    if not notes:
        notes.append("No obvious structural refactor target was detected from heuristics alone.")
    return notes


def infer_risk_notes(file_record):
    content = file_record.get("content", "")
    lowered = content.lower()
    notes = []

    if "tick(" in lowered or "tickcomponent(" in lowered:
        notes.append("Tick usage can become expensive if this runs on many actors/components.")
    if "cast<" in lowered:
        notes.append("Repeated Cast<> usage may hide coupling or null-handling risks.")
    if "getworld()" in lowered and "if (" not in lowered:
        notes.append("World access is present; sanity-check null handling around lifecycle-sensitive code.")
    if "ue_log" not in lowered and ("check(" in lowered or "ensure(" in lowered):
        notes.append("Assertion-style guards exist, but there may be room for clearer diagnostics/logging.")
    if not notes:
        notes.append("No strong risk pattern stood out from lightweight static heuristics.")
    return notes


def build_gameplay_connections(file_record):
    analysis = file_record["analysis"]
    connections = []

    if "player" in analysis["roles"]:
        connections.append("Likely participates in player control, pawn behavior, or character flow.")
    if "ui" in analysis["roles"]:
        connections.append("Likely influences HUD, widget, or menu behavior.")
    if "combat" in analysis["roles"]:
        connections.append("Likely connects to weapons, damage, or ability flow.")
    if "ai" in analysis["roles"]:
        connections.append("Likely connects to AI decision-making, enemy logic, or behavior trees.")
    if analysis["asset_links"]:
        connections.append("This file exposes hooks that Blueprints or designers may use directly.")
    if not connections:
        connections.append("Gameplay linkage is not obvious from naming alone; inspect call sites and owning module.")
    return connections


def generate_code_suggestions(file_record):
    analysis = file_record["analysis"]
    content = file_record.get("content", "")
    suggestions = []

    if analysis["line_count"] > 450:
        suggestions.append("Consider splitting this file into smaller responsibilities.")
    if "tick(" in content.lower() or "tickcomponent(" in content.lower():
        suggestions.append("Review Tick usage and move repeated logic to events, timers, or state changes where possible.")
    if content.count("UE_LOG") == 0 and ("return false;" in content or "return nullptr;" in content):
        suggestions.append("Add logs around failure paths to improve debugging in editor and packaged builds.")
    if "const " not in content and ".cpp" in file_record["path"].lower():
        suggestions.append("Check whether read-only helpers or parameters can be marked const.")
    if content.lower().count("if (") + content.lower().count("if(") > 18:
        suggestions.append("There is a lot of branching here; some logic may be easier to test if extracted into helper functions.")
    if not suggestions:
        suggestions.append("No high-confidence suggestion was detected from simple heuristics.")

    return suggestions


def explain_blueprint_nodes(node_text):
    lines = [line.strip() for line in node_text.splitlines() if line.strip()]
    node_names = []
    for line in lines:
        parts = [part.strip() for part in re.split(r"[:>|,-]", line) if part.strip()]
        node_names.extend(parts[:2])

    ordered_nodes = dedupe_preserve_order(node_names)[:12]
    if not ordered_nodes:
        return {
            "summary": "No Blueprint node names were recognized from the pasted text.",
            "nodes": [],
            "execution_flow": [],
            "common_mistakes": ["Paste copied Blueprint node text or a node list from the editor."],
        }

    return {
        "summary": f"The pasted Blueprint snippet appears to involve {', '.join(ordered_nodes[:6])}.",
        "nodes": [
            {
                "name": node,
                "explanation": describe_node_name(node),
            }
            for node in ordered_nodes
        ],
        "execution_flow": ordered_nodes,
        "common_mistakes": [
            "Check execution pin order if the behavior seems to stop early.",
            "Watch for null object references feeding into function or component nodes.",
            "Validate whether the logic belongs in Blueprint or should move to C++ for reuse/performance.",
        ],
    }


def describe_node_name(node_name):
    lowered = node_name.lower()
    if "cast" in lowered:
        return "Attempts to convert one object type to another; usually fails when the source is not that class."
    if "branch" in lowered or "if" == lowered:
        return "Controls execution flow based on a condition."
    if "set " in lowered or lowered.startswith("set"):
        return "Writes a new value into a variable or property."
    if "get " in lowered or lowered.startswith("get"):
        return "Reads a variable, object reference, or property value."
    if "spawn" in lowered:
        return "Creates an actor, object, or gameplay effect during runtime."
    if "event" in lowered:
        return "Acts as an execution entry point triggered by engine or gameplay events."
    if "delay" in lowered or "timer" in lowered:
        return "Defers execution and can affect ordering bugs or race conditions."
    return "This node likely contributes one step in the Blueprint's data or execution flow."


def build_folder_summary(files, folder_path):
    folder_lower = folder_path.lower().rstrip("\\/")
    matching_files = [file_record for file_record in files if file_record["path"].lower().startswith(folder_lower)]

    if not matching_files:
        return {
            "folder": folder_path,
            "summary": "No scanned files were found under that folder.",
            "key_files": [],
            "systems": [],
            "connections": [],
        }

    role_counter = Counter()
    key_files = []
    include_targets = Counter()

    for file_record in matching_files:
        analysis = file_record["analysis"]
        role_counter.update(analysis["roles"])
        key_files.append(
            {
                "path": file_record["path"],
                "score": analysis["centrality_score"],
                "symbols": analysis["all_symbol_names"][:6],
            }
        )
        include_targets.update(analysis["includes"])

    key_files.sort(key=lambda item: item["score"], reverse=True)

    summary_parts = [
        f"This folder contains {len(matching_files)} scanned file(s).",
    ]
    if role_counter:
        summary_parts.append(
            "It appears focused on "
            + ", ".join(f"{role} ({count})" for role, count in role_counter.most_common(4))
            + "."
        )

    return {
        "folder": folder_path,
        "summary": " ".join(summary_parts),
        "key_files": key_files[:10],
        "systems": [{"name": role, "count": count} for role, count in role_counter.most_common()],
        "connections": [{"name": target, "count": count} for target, count in include_targets.most_common(10)],
    }


def build_dependency_map(files):
    include_to_file = defaultdict(list)
    for file_record in files:
        include_to_file[file_record["name"].lower()].append(file_record["path"])

    relationships = []
    central = []

    for file_record in files:
        analysis = file_record["analysis"]
        resolved = []
        for include_name in analysis["includes"]:
            include_basename = include_name.split("/")[-1].split("\\")[-1].lower()
            if include_basename in include_to_file:
                resolved.extend(include_to_file[include_basename])
        relationships.append(
            {
                "path": file_record["path"],
                "includes": analysis["includes"][:12],
                "resolved_dependencies": dedupe_preserve_order(resolved)[:12],
            }
        )
        central.append(
            {
                "path": file_record["path"],
                "score": analysis["centrality_score"],
                "usage_frequency": len(analysis["includes"]) + len(analysis["all_symbol_names"]),
            }
        )

    central.sort(key=lambda item: (item["score"], item["usage_frequency"]), reverse=True)
    relationships.sort(key=lambda item: len(item["resolved_dependencies"]), reverse=True)

    return {
        "core_files": central[:10],
        "relationships": relationships[:20],
    }


def analyze_reflection_text(text):
    properties = []
    for specifiers, prop_type, prop_name in UPROPERTY_PATTERN.findall(text):
        flags = [part.strip() for part in specifiers.split(",") if part.strip()]
        properties.append(
            {
                "name": prop_name,
                "type": normalize_space(prop_type),
                "flags": flags,
                "explanations": [explain_reflection_flag(flag) for flag in flags],
            }
        )

    functions = []
    for specifiers, return_type, function_name in UFUNCTION_PATTERN.findall(text):
        flags = [part.strip() for part in specifiers.split(",") if part.strip()]
        functions.append(
            {
                "name": function_name,
                "return_type": normalize_space(return_type),
                "flags": flags,
                "explanations": [explain_reflection_flag(flag) for flag in flags],
            }
        )

    replication = []
    lowered = text.lower()
    for keyword in ("replicated", "replicatedusing", "getlifetimereplicatedprops", "server", "client", "netmulticast"):
        if keyword in lowered:
            replication.append(
                {
                    "keyword": keyword,
                    "explanation": explain_reflection_flag(keyword),
                }
            )

    return {
        "properties": properties,
        "functions": functions,
        "replication": replication,
    }


def explain_reflection_flag(flag):
    lowered = flag.strip().lower()
    explanations = {
        "editanywhere": "Editable in the editor on defaults and placed instances, but this does not by itself make it writable at runtime in Blueprint.",
        "editdefaultsonly": "Editable only on class defaults, not per-instance in a level.",
        "editinstanceonly": "Editable per placed instance, which is useful when designers need per-level variation.",
        "blueprintreadwrite": "Readable and writable in Blueprint graphs.",
        "blueprintreadonly": "Visible to Blueprints but not writable from Blueprint graphs.",
        "blueprintcallable": "This function can be called directly from Blueprint.",
        "blueprintimplementableevent": "Blueprint provides the implementation; C++ declares the hook.",
        "blueprintnativeevent": "C++ can provide a default implementation and Blueprint can override it.",
        "blueprintable": "The class is intended to be subclassed in Blueprint.",
        "blueprinttype": "The type is intended to be used as a Blueprint variable/pin type.",
        "visibleanywhere": "Visible in the editor for inspection but not directly editable.",
        "replicated": "This property participates in Unreal replication and should be registered in GetLifetimeReplicatedProps.",
        "replicatedusing": "This property replicates and triggers a notifier function when updated on clients.",
        "server": "RPC intended to run on the server.",
        "client": "RPC intended to run on a client.",
        "netmulticast": "RPC intended to execute on server and relevant clients.",
        "getlifetimereplicatedprops": "This is the Unreal hook where replicated properties are registered.",
    }
    return explanations.get(lowered, "This flag affects Unreal reflection, editor exposure, Blueprint access, or networking behavior.")


def build_task_workflow(goal, files):
    if not files:
        return {
            "goal": goal,
            "summary": "No clearly relevant files were found yet. Try a more specific task description or scan a larger project scope.",
            "relevant_files": [],
            "systems": [],
            "how_it_works": [],
            "next_steps": [],
            "risks": [],
        }

    role_counter = Counter()
    relevant_files = []
    how_it_works = []
    risks = []

    for file_record in files:
        analysis = file_record["analysis"]
        role_counter.update(analysis["roles"])
        relevant_files.append(
            {
                "path": file_record["path"],
                "file_type": file_record.get("file_type", ""),
                "score": analysis.get("centrality_score", 0),
                "symbols": analysis["all_symbol_names"][:8],
            }
        )
        if analysis["classes"] or analysis["functions"]:
            how_it_works.append(
                f"{file_record['name']} exposes {', '.join(analysis['all_symbol_names'][:5]) or 'core symbols'}."
            )
        risks.extend(infer_risk_notes(file_record))

    relevant_files.sort(key=lambda item: item["score"], reverse=True)
    systems = [{"name": role, "count": count} for role, count in role_counter.most_common()]

    next_steps = [
        "Review the highest-centrality files first to confirm the ownership of the task.",
        "Trace any Blueprint-facing functions or editable properties before changing gameplay behavior.",
        "Validate Tick, replication, and null-handling around the affected flow.",
    ]
    if "combat" in role_counter:
        next_steps.append("Check damage, weapon, and ability call paths together so the full combat chain stays consistent.")
    if "player" in role_counter:
        next_steps.append("Inspect controller, pawn/character, and component boundaries before changing player logic.")

    return {
        "goal": goal,
        "summary": f"This task most likely touches {', '.join(role for role, _ in role_counter.most_common(4)) or 'general gameplay code'}.",
        "relevant_files": relevant_files[:8],
        "systems": systems,
        "how_it_works": dedupe_preserve_order(how_it_works)[:8],
        "next_steps": dedupe_preserve_order(next_steps)[:8],
        "risks": dedupe_preserve_order(risks)[:8],
    }


def analyze_deep_asset(asset_kind, exported_text, selection_name="", class_name="", family_summary=None):
    kind = (asset_kind or "").strip().lower()
    text = (exported_text or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    tokens = dedupe_preserve_order(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text))
    common_deps = [token for token in tokens if token.startswith(("BP_", "ABP_", "WBP_", "IA_", "IMC_", "BT_", "BB_", "DA_", "M_", "MI_"))][:12]

    result = {
        "asset_kind": kind,
        "selection_name": selection_name,
        "class_name": class_name,
        "summary": "",
        "depends_on": common_deps,
        "what_looks_wrong": [],
        "what_is_missing": [],
        "key_elements": [],
        "flow_summary": [],
        "linked_cpp_classes": (family_summary or {}).get("linked_cpp_classes", {}),
    }

    if kind == "blueprint":
        result.update(analyze_blueprint_export(lines, text))
    elif kind == "material":
        result.update(analyze_material_export(lines, text))
    elif kind in {"behavior_tree", "behavior tree"}:
        result.update(analyze_behavior_tree_export(lines, text))
    elif kind in {"enhanced_input", "input", "input_mapping"}:
        result.update(analyze_input_export(lines, text))
    elif kind in {"metasound", "meta_sound"}:
        result.update(analyze_metasound_export(lines, text))
    elif kind == "pcg":
        result.update(analyze_pcg_export(lines, text))
    elif kind in {"motion_matching", "motion matching"}:
        result.update(analyze_motion_matching_export(lines, text))
    elif kind in {"state_tree", "state tree"}:
        result.update(analyze_state_tree_export(lines, text))
    elif kind in {"control_rig", "control rig"}:
        result.update(analyze_control_rig_export(lines, text))
    elif kind in {"niagara", "niagara_system"}:
        result.update(analyze_niagara_export(lines, text))
    elif kind == "eqs":
        result.update(analyze_eqs_export(lines, text))
    elif kind == "sequencer":
        result.update(analyze_sequencer_export(lines, text))
    elif kind in {"ik_rig", "ik rig"}:
        result.update(analyze_ik_rig_export(lines, text))
    elif kind == "data_asset":
        result.update(analyze_data_asset_export(lines, text))
    elif kind in {"animbp", "animbp", "animation_blueprint", "anim_blueprint"}:
        result.update(analyze_animbp_export(lines, text))
    else:
        result["summary"] = "This asset kind is not yet deeply analyzed. Paste exported graph/state text for Blueprint, Material, Behavior Tree, Enhanced Input, StateTree, Control Rig, Niagara, EQS, Sequencer, MetaSound, PCG, Motion Matching, IK Rig, DataAsset, or AnimBP."

    if family_summary:
        result["gameplay_role"] = family_summary.get("role_guess", "")
        result["linked_assets"] = family_summary.get("linked_assets", [])
    else:
        result["gameplay_role"] = ""
        result["linked_assets"] = []

    return result


def extract_reflected_properties(lines):
    properties = []
    for line in lines:
        if not line.startswith("Property: "):
            continue
        payload = line[len("Property: "):]
        name_and_type, _, value = payload.partition("=")
        prop_name, _, prop_type = name_and_type.partition("[")
        properties.append(
            {
                "name": prop_name.strip(),
                "type": prop_type.rstrip("] ").strip(),
                "value": value.strip(),
            }
        )
    return properties


def analyze_blueprint_export(lines, text):
    nodes = extract_prefixed_items(lines, ("Event", "Branch", "Sequence", "Delay", "Cast", "Set ", "Get ", "Spawn", "Call "))
    events = [line for line in lines if "event" in line.lower()][:8]
    reflected_properties = extract_reflected_properties(lines)
    structured_blueprint_lines = [
        line for line in lines
        if line.startswith("Blueprint Asset:") or line.startswith("Blueprint Class:") or line.startswith("Blueprint Property:")
    ]
    missing = []
    wrong = []
    lowered = text.lower()
    if "branch" not in lowered and "if" not in lowered and not reflected_properties and not structured_blueprint_lines:
        missing.append("No obvious branching/guard logic was detected in the exported Blueprint text.")
    if "cast" in lowered and "is valid" not in lowered:
        wrong.append("Cast nodes appear present without obvious validity guarding.")
    if "delay" in lowered:
        wrong.append("Delay nodes can hide ordering bugs if this Blueprint controls gameplay-critical flow.")

    summary = "This Blueprint appears to coordinate gameplay logic through graph execution and object/property access."
    key_elements = nodes[:12]
    flow_summary = events + nodes[:6]

    if structured_blueprint_lines:
        property_lines = [line for line in structured_blueprint_lines if line.startswith("Blueprint Property:")]
        key_elements = dedupe_preserve_order(property_lines + key_elements)[:12]
        flow_summary = dedupe_preserve_order(structured_blueprint_lines[:8] + flow_summary)[:8]
        summary = "This Blueprint appears to come from structured plugin-side Blueprint fallback data rather than a pasted graph export."
        if property_lines:
            property_names = [line.split(":", 1)[1].split("=", 1)[0].strip() for line in property_lines[:3]]
            summary += f" Blueprint properties like {', '.join(property_names)} give clues about runtime state and collaborators."
        if not any(any(token in line.lower() for token in ("state", "active", "enabled", "visible")) for line in property_lines):
            missing.append("The structured Blueprint fallback did not surface obvious state-style properties.")
        if not any(any(token in line.lower() for token in ("target", "owner", "component", "widget")) for line in property_lines):
            missing.append("The structured Blueprint fallback did not surface obvious collaborator/reference properties.")

    if reflected_properties:
        blueprint_properties = [
            item for item in reflected_properties
            if any(token in item["name"].lower() for token in ("state", "target", "owner", "component", "widget", "class", "tag", "enabled", "visible", "active", "speed", "health", "sprint", "move", "weapon", "interact"))
        ]
        key_lines = [
            f"{item['name']}: {item['value']}"
            for item in blueprint_properties[:12]
        ]
        key_elements = dedupe_preserve_order(key_lines + key_elements)[:12]
        flow_summary = dedupe_preserve_order(
            [f"Property-driven context: {item['name']} = {item['value']}" for item in blueprint_properties[:8]] + flow_summary
        )[:8]

        property_names = [item["name"].lower() for item in reflected_properties]
        summary = "This Blueprint appears to come from reflected Unreal property data rather than a pasted graph export."
        if blueprint_properties:
            summary += f" Exposed properties such as {', '.join(item['name'] for item in blueprint_properties[:3])} give clues about the Blueprint's runtime role."

        if not any(name.startswith(("b", "is", "has")) or "state" in name for name in property_names):
            missing.append("No obvious state or guard-style properties were surfaced from the reflected Blueprint data.")
        if not any(token in name for name in property_names for token in ("component", "target", "owner", "widget")):
            missing.append("No obvious owner/reference-style properties were surfaced, so the Blueprint's collaborators may still be implicit.")
        if any("class" in item["name"].lower() and item["value"] in {"None", ""} for item in reflected_properties):
            wrong.append("A class-related Blueprint property appears unset in the reflected data, which can hide spawn or ownership issues.")

    return {
        "summary": summary,
        "key_elements": key_elements,
        "flow_summary": flow_summary,
        "what_looks_wrong": dedupe_preserve_order(wrong),
        "what_is_missing": dedupe_preserve_order(missing),
    }


def analyze_material_export(lines, text):
    params = [line for line in lines if any(word in line.lower() for word in ("parameter", "scalar", "vector", "texture", "lerp", "multiply"))][:12]
    reflected_properties = extract_reflected_properties(lines)
    structured_material_lines = [
        line for line in lines
        if line.startswith("Material Instance:") or line.startswith("Parent Material:") or line.startswith("Scalar Parameter:") or line.startswith("Vector Parameter:") or line.startswith("Texture Parameter:") or line.startswith("Material Reference:")
    ]
    wrong = []
    missing = []
    lowered = text.lower()
    if "parameter" not in lowered and not any("parameter" in item["name"].lower() for item in reflected_properties) and not structured_material_lines:
        missing.append("No obvious parameter nodes were detected, so runtime tuning hooks may be limited.")
    if lowered.count("texture") > 3 and "parameter" not in lowered:
        wrong.append("This material may be texture-heavy without clear parameterization for runtime control.")

    summary = "This material appears to define visual output through texture/math/parameter nodes."
    key_elements = params
    flow_summary = params[:8]

    if structured_material_lines:
        key_elements = dedupe_preserve_order(structured_material_lines + key_elements)[:12]
        flow_summary = dedupe_preserve_order(structured_material_lines[:8] + flow_summary)[:8]
        summary = "This material appears to come from structured plugin-side material fallback data rather than a pasted graph export."
        if not any("parent material" in line.lower() for line in structured_material_lines):
            missing.append("The structured material fallback did not surface a parent material reference.")
        if not any(any(token in line.lower() for token in ("scalar parameter", "vector parameter", "texture parameter")) for line in structured_material_lines):
            missing.append("The structured material fallback did not surface any obvious parameter-style entries.")

    if reflected_properties:
        material_properties = [
            item for item in reflected_properties
            if any(token in item["name"].lower() for token in ("parameter", "texture", "material", "rough", "metal", "emiss", "opacity", "color", "base", "normal"))
        ]
        key_lines = [f"{item['name']}: {item['value']}" for item in material_properties[:12]]
        key_elements = dedupe_preserve_order(key_lines + key_elements)[:12]
        flow_summary = dedupe_preserve_order(
            [f"Material property context: {item['name']} = {item['value']}" for item in material_properties[:8]] + flow_summary
        )[:8]

        property_names = [item["name"].lower() for item in reflected_properties]
        summary = "This material appears to come from reflected Unreal property data rather than a pasted graph export."
        if material_properties:
            summary += f" Reflected properties such as {', '.join(item['name'] for item in material_properties[:3])} hint at the material's tunable surface inputs."

        if not any("parameter" in name for name in property_names):
            missing.append("No obvious parameter-style properties were surfaced from the reflected material data.")
        if not any(token in name for name in property_names for token in ("texture", "base", "normal")):
            missing.append("No obvious texture/reference-style properties were surfaced, so the material input chain may still be unclear.")
        if any("texture" in item["name"].lower() and item["value"] in {"None", ""} for item in reflected_properties):
            wrong.append("A texture-related material property appears unset in the reflected data, which can hide broken visual inputs.")

    return {
        "summary": summary,
        "key_elements": key_elements,
        "flow_summary": flow_summary,
        "what_looks_wrong": dedupe_preserve_order(wrong),
        "what_is_missing": dedupe_preserve_order(missing),
    }


def analyze_behavior_tree_export(lines, text):
    tasks = [line for line in lines if any(word in line.lower() for word in ("task", "service", "decorator", "selector", "sequence", "blackboard"))][:12]
    wrong = []
    missing = []
    lowered = text.lower()
    if "blackboard" not in lowered:
        missing.append("No Blackboard references were detected, which is unusual for many behavior trees.")
    if "selector" not in lowered and "sequence" not in lowered:
        missing.append("No obvious composite flow nodes were detected in the exported tree text.")
    if lowered.count("service") > 3:
        wrong.append("Many service nodes may indicate distributed logic that is harder to debug.")
    return {
        "summary": "This Behavior Tree appears to drive AI decisions through composites, decorators, services, and tasks.",
        "key_elements": tasks,
        "flow_summary": tasks[:8],
        "what_looks_wrong": wrong,
        "what_is_missing": missing,
    }


def analyze_input_export(lines, text):
    actions = [line for line in lines if any(word in line.lower() for word in ("input action", "mapping", "trigger", "modifier", "action", "context"))][:12]
    reflected_properties = extract_reflected_properties(lines)
    wrong = []
    missing = []
    lowered = text.lower()
    if "mapping" not in lowered and not any("mapping" in item["name"].lower() for item in reflected_properties):
        missing.append("No obvious mapping context information was detected.")
    if "trigger" not in lowered and not any("trigger" in item["name"].lower() for item in reflected_properties):
        missing.append("No trigger information was detected, so input timing rules may be unclear.")
    if lowered.count("action") > 0 and "context" not in lowered and not any("context" in item["name"].lower() for item in reflected_properties):
        wrong.append("Input actions appear present without clear mapping context ownership.")

    summary = "This input asset appears to define actions, mappings, and trigger/modifier behavior for player input."
    if reflected_properties:
        action_names = [item["value"] for item in reflected_properties if "action" in item["name"].lower() and item["value"] not in {"None", ""}]
        mapping_names = [item["value"] for item in reflected_properties if "mapping" in item["name"].lower() and item["value"] not in {"None", ""}]
        trigger_names = [item["value"] for item in reflected_properties if "trigger" in item["name"].lower() and item["value"] not in {"None", ""}]
        modifier_names = [item["value"] for item in reflected_properties if "modifier" in item["name"].lower() and item["value"] not in {"None", ""}]

        parts = ["This input asset appears to come from reflected Unreal property data"]
        if action_names:
            parts.append(f"with action-related values such as {', '.join(action_names[:2])}.")
        elif mapping_names:
            parts.append(f"with mapping-related values such as {', '.join(mapping_names[:2])}.")
        else:
            parts.append("rather than a pasted export.")
        summary = " ".join(parts)

        key_lines = [
            f"{item['name']}: {item['value']}"
            for item in reflected_properties
            if any(token in item["name"].lower() for token in ("action", "mapping", "trigger", "modifier"))
        ]
        actions = dedupe_preserve_order(key_lines + actions)[:12]

        if mapping_names and not trigger_names and not any("trigger" in line.lower() for line in lines):
            missing.append("Mapping-related properties were detected, but no clear trigger configuration was surfaced from the reflected asset data.")
        if action_names and not mapping_names and "input action" in lowered:
            wrong.append("This looks like an Input Action payload without a visible owning Mapping Context, so runtime hookup still needs verification.")
        if modifier_names and not trigger_names:
            missing.append("Modifier-related properties were detected without obvious trigger data, so timing and activation behavior may still be unclear.")

    return {
        "summary": summary,
        "key_elements": actions,
        "flow_summary": actions[:8],
        "what_looks_wrong": dedupe_preserve_order(wrong),
        "what_is_missing": dedupe_preserve_order(missing),
    }


def analyze_animbp_export(lines, text):
    states = [line for line in lines if any(word in line.lower() for word in ("state", "transition", "blend", "montage", "notify", "anim graph"))][:12]
    wrong = []
    missing = []
    lowered = text.lower()
    if "transition" not in lowered:
        missing.append("No transition rules were detected, so state-machine flow may be incomplete in the export.")
    if "state" not in lowered:
        missing.append("No obvious state names were detected from the exported AnimBP text.")
    if "montage" in lowered and "notify" not in lowered:
        wrong.append("Montage use is visible but no obvious notify flow was detected.")
    return {
        "summary": "This AnimBP appears to drive animation state and transition behavior from character/anim-instance data.",
        "key_elements": states,
        "flow_summary": states[:8],
        "what_looks_wrong": wrong,
        "what_is_missing": missing,
    }


def analyze_metasound_export(lines, text):
    lowered = text.lower()
    nodes = [
        line for line in lines
        if any(word in line.lower() for word in ("wave", "oscillator", "trigger", "parameter", "mix", "envelope", "delay", "output", "graph input", "graph output"))
    ][:14]
    wrong = []
    missing = []

    if "parameter" not in lowered and "graph input" not in lowered:
        missing.append("No obvious runtime parameter or graph input nodes were detected.")
    if "output" not in lowered:
        missing.append("No obvious audio output path was detected in the exported MetaSound text.")
    if "trigger" not in lowered and "play" not in lowered:
        missing.append("No obvious trigger/play flow was detected, so timing behavior may be unclear.")
    if "delay" in lowered and "trigger" not in lowered:
        wrong.append("Delay-like nodes are visible without a clear trigger flow, which can hide timing bugs.")
    if "wave" in lowered and "mix" not in lowered and "envelope" not in lowered:
        wrong.append("Wave playback is visible, but no obvious shaping or mixing nodes were detected.")

    return {
        "summary": "This MetaSound appears to drive procedural or parameterized audio flow through trigger, parameter, and output nodes.",
        "key_elements": nodes,
        "flow_summary": nodes[:8],
        "what_looks_wrong": wrong,
        "what_is_missing": missing,
    }


def analyze_pcg_export(lines, text):
    lowered = text.lower()
    nodes = [
        line for line in lines
        if any(word in line.lower() for word in ("surface", "points", "spawn", "scatter", "filter", "density", "attribute", "sampler", "volume", "graph input", "graph output"))
    ][:14]
    wrong = []
    missing = []

    if "spawn" not in lowered and "scatter" not in lowered:
        missing.append("No obvious spawn or scatter stage was detected in the exported PCG text.")
    if "points" not in lowered and "surface" not in lowered and "volume" not in lowered:
        missing.append("No obvious point/surface/volume source was detected, so generation inputs may be unclear.")
    if "filter" not in lowered and "attribute" not in lowered:
        missing.append("No obvious filtering or attribute-selection stage was detected.")
    if "density" in lowered and "filter" not in lowered:
        wrong.append("Density controls are visible without a clear filtering stage, which can make outputs noisy or hard to predict.")
    if lowered.count("spawn") > 2 and "cleanup" not in lowered:
        wrong.append("Multiple spawn stages are visible without an obvious cleanup or ownership story.")

    return {
        "summary": "This PCG asset appears to drive procedural generation through source selection, filtering, and spawn/output stages.",
        "key_elements": nodes,
        "flow_summary": nodes[:8],
        "what_looks_wrong": wrong,
        "what_is_missing": missing,
    }


def analyze_motion_matching_export(lines, text):
    lowered = text.lower()
    nodes = [
        line for line in lines
        if any(word in line.lower() for word in ("pose", "trajectory", "database", "chooser", "cost", "query", "schema", "channel", "history"))
    ][:14]
    wrong = []
    missing = []

    if "pose" not in lowered and "database" not in lowered:
        missing.append("No obvious pose database or pose-search stage was detected.")
    if "trajectory" not in lowered:
        missing.append("No obvious trajectory input was detected, so movement-driven matching may be unclear.")
    if "chooser" not in lowered and "query" not in lowered and "cost" not in lowered:
        missing.append("No obvious selection/scoring stage was detected for the motion-matching decision.")
    if "database" in lowered and "trajectory" not in lowered:
        wrong.append("A pose database is visible without a clear trajectory input, which can make matching quality unstable.")
    if "history" in lowered and "pose" not in lowered:
        wrong.append("History-related data is visible without a clear pose-selection stage.")

    return {
        "summary": "This Motion Matching asset appears to drive animation choice through trajectory, pose database, and scoring/selection data.",
        "key_elements": nodes,
        "flow_summary": nodes[:8],
        "what_looks_wrong": wrong,
        "what_is_missing": missing,
    }


def analyze_state_tree_export(lines, text):
    lowered = text.lower()
    nodes = [
        line for line in lines
        if any(word in line.lower() for word in ("state", "transition", "task", "evaluator", "condition", "parameter", "enter state", "exit state"))
    ][:14]
    wrong = []
    missing = []

    if "state" not in lowered:
        missing.append("No obvious states were detected in the exported StateTree text.")
    if "transition" not in lowered and "condition" not in lowered:
        missing.append("No obvious transition or condition logic was detected.")
    if "task" not in lowered:
        missing.append("No obvious task execution stage was detected, so runtime work ownership may be unclear.")
    if "evaluator" in lowered and "parameter" not in lowered:
        wrong.append("Evaluators are visible without obvious shared parameters or input state, which can hide ownership problems.")

    return {
        "summary": "This StateTree appears to drive structured gameplay state transitions through states, evaluators, conditions, and tasks.",
        "key_elements": nodes,
        "flow_summary": nodes[:8],
        "what_looks_wrong": wrong,
        "what_is_missing": missing,
    }


def analyze_control_rig_export(lines, text):
    lowered = text.lower()
    nodes = [
        line for line in lines
        if any(word in line.lower() for word in ("control", "bone", "solver", "hierarchy", "transform", "execute", "forward solve", "backward solve"))
    ][:14]
    wrong = []
    missing = []

    if "control" not in lowered and "bone" not in lowered:
        missing.append("No obvious controls or driven bones were detected in the exported Control Rig text.")
    if "solver" not in lowered and "transform" not in lowered:
        missing.append("No obvious solve or transform stage was detected.")
    if "hierarchy" not in lowered:
        missing.append("No hierarchy access was detected, so rig ownership may be unclear.")
    if "backward solve" in lowered and "forward solve" not in lowered:
        wrong.append("Backward solve is visible without an obvious forward solve path, which can make rig flow harder to reason about.")

    return {
        "summary": "This Control Rig appears to drive procedural rig or pose updates through controls, hierarchy access, and solve stages.",
        "key_elements": nodes,
        "flow_summary": nodes[:8],
        "what_looks_wrong": wrong,
        "what_is_missing": missing,
    }


def analyze_niagara_export(lines, text):
    lowered = text.lower()
    nodes = [
        line for line in lines
        if any(word in line.lower() for word in ("emitter", "spawn", "update", "particle", "system", "parameter", "event", "renderer", "initialize"))
    ][:14]
    wrong = []
    missing = []

    if "emitter" not in lowered and "system" not in lowered:
        missing.append("No obvious emitter/system ownership was detected in the exported Niagara text.")
    if "spawn" not in lowered and "initialize" not in lowered:
        missing.append("No obvious spawn or initialization stage was detected.")
    if "update" not in lowered:
        missing.append("No obvious particle update stage was detected.")
    if "renderer" not in lowered:
        missing.append("No obvious renderer setup was detected, so visual output may be incomplete.")
    if "event" in lowered and "parameter" not in lowered:
        wrong.append("Event-driven behavior is visible without clear parameter inputs, which can make effect control brittle.")

    return {
        "summary": "This Niagara asset appears to drive particle or VFX behavior through emitter setup, spawn/update stages, and runtime parameters.",
        "key_elements": nodes,
        "flow_summary": nodes[:8],
        "what_looks_wrong": wrong,
        "what_is_missing": missing,
    }


def analyze_eqs_export(lines, text):
    lowered = text.lower()
    nodes = [
        line for line in lines
        if any(word in line.lower() for word in ("generator", "test", "context", "score", "query", "item", "distance", "pathfinding"))
    ][:14]
    wrong = []
    missing = []

    if "generator" not in lowered:
        missing.append("No obvious EQS generator was detected.")
    if "test" not in lowered and "score" not in lowered:
        missing.append("No obvious test or scoring stage was detected in the query.")
    if "context" not in lowered:
        missing.append("No obvious context was detected, so the query origin/target assumptions may be unclear.")
    if lowered.count("test") > 4 and "weight" not in lowered and "score" not in lowered:
        wrong.append("Many EQS tests are visible without obvious weighting or scoring hints, which can make query results hard to reason about.")

    return {
        "summary": "This EQS asset appears to drive AI query generation, testing, and scoring for environmental decisions.",
        "key_elements": nodes,
        "flow_summary": nodes[:8],
        "what_looks_wrong": wrong,
        "what_is_missing": missing,
    }


def analyze_sequencer_export(lines, text):
    lowered = text.lower()
    nodes = [
        line for line in lines
        if any(word in line.lower() for word in ("track", "section", "binding", "camera", "event", "sequence", "shot", "key"))
    ][:14]
    wrong = []
    missing = []

    if "track" not in lowered and "section" not in lowered:
        missing.append("No obvious tracks or sections were detected in the exported Sequencer text.")
    if "binding" not in lowered and "camera" not in lowered:
        missing.append("No obvious actor/camera binding was detected.")
    if "event" not in lowered and "key" not in lowered:
        missing.append("No obvious event or keyed timing data was detected.")
    if "shot" in lowered and "camera" not in lowered:
        wrong.append("Shot-like sequencing is visible without obvious camera ownership, which can make cinematic intent unclear.")

    return {
        "summary": "This Sequencer asset appears to drive time-based presentation through tracks, bindings, and keyed sequence events.",
        "key_elements": nodes,
        "flow_summary": nodes[:8],
        "what_looks_wrong": wrong,
        "what_is_missing": missing,
    }


def analyze_ik_rig_export(lines, text):
    lowered = text.lower()
    nodes = [
        line for line in lines
        if any(word in line.lower() for word in ("goal", "chain", "solver", "retarget", "effector", "bone", "root", "pose"))
    ][:14]
    wrong = []
    missing = []

    if "chain" not in lowered and "bone" not in lowered:
        missing.append("No obvious chains or driven bones were detected in the exported IK Rig text.")
    if "goal" not in lowered and "effector" not in lowered:
        missing.append("No obvious IK goals or effectors were detected.")
    if "solver" not in lowered and "retarget" not in lowered:
        missing.append("No obvious solver or retarget stage was detected.")
    if "retarget" in lowered and "chain" not in lowered:
        wrong.append("Retargeting is visible without obvious chain definitions, which can make pose transfer brittle.")

    return {
        "summary": "This IK Rig asset appears to drive chain, goal, and solver-based pose adjustment or retargeting.",
        "key_elements": nodes,
        "flow_summary": nodes[:8],
        "what_looks_wrong": wrong,
        "what_is_missing": missing,
    }


def analyze_data_asset_export(lines, text):
    lowered = text.lower()
    fields = [
        line for line in lines
        if any(word in line.lower() for word in ("name", "id", "tag", "soft", "class", "reference", "value", "row", "entry"))
    ][:14]
    wrong = []
    missing = []

    if "id" not in lowered and "name" not in lowered:
        missing.append("No obvious identifiers or naming fields were detected in the exported DataAsset text.")
    if "soft" not in lowered and "reference" not in lowered and "class" not in lowered:
        missing.append("No obvious reference fields were detected, so ownership of related assets may be unclear.")
    if "value" not in lowered and "entry" not in lowered:
        missing.append("No obvious gameplay/config values were detected from the export.")
    if "class" in lowered and "soft" not in lowered:
        wrong.append("Hard class references may be present without obvious soft-reference decoupling.")

    return {
        "summary": "This DataAsset appears to hold structured gameplay or content configuration fields consumed by runtime systems.",
        "key_elements": fields,
        "flow_summary": fields[:8],
        "what_looks_wrong": wrong,
        "what_is_missing": missing,
    }


def extract_prefixed_items(lines, prefixes):
    items = []
    for line in lines:
        lowered = line.lower()
        if any(lowered.startswith(prefix.lower()) for prefix in prefixes):
            items.append(line)
    return dedupe_preserve_order(items)
