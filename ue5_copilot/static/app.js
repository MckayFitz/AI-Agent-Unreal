const projectPathInput = document.getElementById("projectPath");
const promptInput = document.getElementById("promptInput");
const filePathInput = document.getElementById("filePathInput");
const explainModeInput = document.getElementById("explainMode");
const classLinkInput = document.getElementById("classLinkInput");
const selectionInput = document.getElementById("selectionInput");
const folderPathInput = document.getElementById("folderPathInput");
const assetFamilySelect = document.getElementById("assetFamilySelect");
const assetScaffoldKindSelect = document.getElementById("assetScaffoldKindSelect");
const deepAssetKindSelect = document.getElementById("deepAssetKindSelect");
const actionSelect = document.getElementById("actionSelect");
const modeHelpTitle = document.getElementById("modeHelpTitle");
const modeHelpText = document.getElementById("modeHelpText");
const modeHelpExample = document.getElementById("modeHelpExample");

const scanButton = document.getElementById("scanButton");
const submitButton = document.getElementById("submitButton");

const scanStatus = document.getElementById("scanStatus");
const apiStatus = document.getElementById("apiStatus");
const chatThread = document.getElementById("chatThread");

const MODE_HELP = {
    ask: {
        title: "Ask AI",
        text: "Ask a general question about the scanned project and get a context-aware answer.",
        example: "How does my weapon system work?",
        placeholder: "Ask about your project, architecture, systems, or gameplay flow.",
    },
    assetDetails: {
        title: "Explain Asset",
        text: "Use this for one selected asset when you want type, role, references, and linked C++ context.",
        example: "BP_PlayerCharacter",
        placeholder: "Enter an asset name like BP_PlayerCharacter, DA_WeaponStats, IMC_Default, or M_Master.",
    },
    assetEditPlan: {
        title: "Edit Asset Values",
        text: "Plan a safe change for the selected asset. Put the selected asset in Advanced Options, then describe the change here.",
        example: "Add a sprint input action and wire it into the default mapping context.",
        placeholder: "Describe the edit you want, like add a bool variable, rename this asset, tweak roughness, or change a DataAsset value.",
    },
    assetScaffold: {
        title: "Generate Asset Scaffold",
        text: "Generate a safe starter scaffold for a new asset type without mutating the project yet. Use Advanced Options for asset kind, purpose, and optional class/parent context.",
        example: "EnemyCombatSettings",
        placeholder: "Enter the new asset name you want to scaffold.",
    },
    deepAsset: {
        title: "Deep Asset Analysis",
        text: "Paste exported graph or state text for a selected asset. Use Advanced Options to force a kind when auto-detect is ambiguous.",
        example: "Paste copied Blueprint graph text or a Behavior Tree export here.",
        placeholder: "Paste exported Blueprint, Material, Behavior Tree, Enhanced Input, StateTree, Control Rig, Niagara, EQS, Sequencer, MetaSound, PCG, Motion Matching, IK Rig, DataAsset, or AnimBP text here.",
    },
    references: {
        title: "Find References",
        text: "Search scanned code for symbol or asset-name usage.",
        example: "HealthComponent",
        placeholder: "Enter a symbol, asset name, function, class, or macro to search for.",
    },
    explainFile: {
        title: "Explain File",
        text: "Explain one scanned file. Use a path in the box or in Advanced Options.",
        example: "Source/MyGame/Player/MyPlayerCharacter.cpp",
        placeholder: "Enter a scanned file path or file name to explain.",
    },
};

const SCAFFOLD_KIND_HELP = {
    blueprint_class: { example: "BP_InteractableDoor", note: "Good for gameplay-facing Blueprint classes with a clear parent class." },
    animbp: { example: "ABP_PlayerLocomotion", note: "Best when you want a starter animation-state plan instead of graph generation." },
    data_asset: { example: "DA_WeaponStats", note: "Use this for designer-editable config assets and strongly-owned data." },
    material: { example: "M_WeaponGlow", note: "Starts with a small parameterized material plan you can later instance." },
    behavior_tree: { example: "BT_EnemyCombat", note: "Creates a Behavior Tree plus Blackboard-oriented starter plan." },
    input_action: { example: "IA_Sprint", note: "Good for a single Enhanced Input action with minimal assumptions." },
    input_mapping_context: { example: "IMC_PlayerDefault", note: "Use this when you need a context-level binding plan." },
    state_tree: { example: "ST_EnemyDecision", note: "Good for structured AI or gameplay state flow." },
    control_rig: { example: "CR_PlayerUpperBody", note: "Use this for procedural rig ownership and starter control planning." },
    niagara: { example: "NS_ImpactDust", note: "Best for gameplay VFX systems with clear spawn/update ownership." },
    eqs: { example: "EQS_FindCover", note: "Use this when the gameplay goal is an AI query or position-scoring flow." },
    sequencer: { example: "LS_Intro", note: "Good for cinematic or event-timed presentation assets." },
    metasound: { example: "MS_WeaponFire", note: "Use this for reactive audio graphs and runtime parameter-driven sound." },
    pcg: { example: "PCG_ForestScatter", note: "Best for procedural generation rules and spawn/filter flows." },
    motion_matching: { example: "MM_PlayerLocomotion", note: "Use this for pose-search driven locomotion or animation selection." },
    ik_rig: { example: "IKR_PlayerRetarget", note: "Good for IK chain, goal, and retarget setup planning." },
};

const DEEP_KIND_HELP = {
    auto: { example: "Leave this on auto when the selection name or asset path is clear.", note: "Auto-detect uses selection name, asset path, and family signals." },
    blueprint: { example: "Paste copied Blueprint graph text with events, branches, and calls.", note: "Best for execution flow and data access reasoning." },
    material: { example: "Paste parameter, texture, and math-node export text.", note: "Useful for parameterization and runtime override checks." },
    behavior_tree: { example: "Paste tree/task/service/decorator export text.", note: "Best for AI flow, Blackboard, and branch ownership." },
    enhanced_input: { example: "Paste Input Action or Mapping Context export text.", note: "Useful for bindings, triggers, and context ownership." },
    state_tree: { example: "Paste states, evaluators, conditions, and task text.", note: "Best for transition logic and state ownership." },
    control_rig: { example: "Paste controls, hierarchy, and solve-stage text.", note: "Useful for control ownership and rig-flow debugging." },
    niagara: { example: "Paste emitter/system spawn-update-render text.", note: "Best for effect flow and parameter-driven behavior." },
    eqs: { example: "Paste generator, context, and test/scoring text.", note: "Useful for AI query intent and scoring issues." },
    sequencer: { example: "Paste track, section, event, and binding text.", note: "Best for timing, binding, and presentation flow." },
    metasound: { example: "Paste graph inputs, playback, envelope, and output text.", note: "Useful for trigger flow and audio-parameter ownership." },
    pcg: { example: "Paste source, filter, attribute, and spawn/output text.", note: "Best for generation ownership and filter-chain reasoning." },
    motion_matching: { example: "Paste pose database, trajectory, chooser, and scoring text.", note: "Useful for movement input and pose-selection debugging." },
    ik_rig: { example: "Paste chains, goals, solvers, and retarget text.", note: "Best for pose-correction and retarget ownership issues." },
    data_asset: { example: "Paste exported fields, ids, references, and values.", note: "Useful for config ownership and reference-shape checks." },
    animbp: { example: "Paste state machine, transition, montage, and notify text.", note: "Best for animation-state flow and gameplay bridge analysis." },
};

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function nl2br(value) {
    return escapeHtml(value).replace(/\n/g, "<br>");
}

function scrollThreadToBottom() {
    chatThread.scrollTop = chatThread.scrollHeight;
}

function addMessage(role, title, bodyHtml, meta = "") {
    const article = document.createElement("article");
    article.className = `message ${role}-message`;
    article.innerHTML = `
        <div class="message-avatar">${escapeHtml(role === "user" ? "Y" : "AI")}</div>
        <div class="message-stack">
            <div class="message-role">${escapeHtml(role === "user" ? "You" : "Assistant")}</div>
            <div class="message-card">
                ${title ? `<h2>${escapeHtml(title)}</h2>` : ""}
                ${meta ? `<p class="message-meta">${escapeHtml(meta)}</p>` : ""}
                <div class="message-body">${bodyHtml}</div>
            </div>
        </div>
    `;
    chatThread.appendChild(article);
    scrollThreadToBottom();
    return article;
}

function addUserMessage(modeLabel, promptText) {
    addMessage("user", modeLabel, `<p>${nl2br(promptText)}</p>`);
}

function addAssistantText(title, text, meta = "") {
    return addMessage("assistant", title, `<p>${nl2br(text)}</p>`, meta);
}

function updateAssistantMessage(messageEl, title, bodyHtml, meta = "") {
    const card = messageEl.querySelector(".message-card");
    card.innerHTML = `
        ${title ? `<h2>${escapeHtml(title)}</h2>` : ""}
        ${meta ? `<p class="message-meta">${escapeHtml(meta)}</p>` : ""}
        <div class="message-body">${bodyHtml}</div>
    `;
    scrollThreadToBottom();
}

function renderList(items) {
    if (!items || items.length === 0) {
        return "<p class=\"muted\">None detected.</p>";
    }

    return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function renderMatches(matches) {
    if (!matches || matches.length === 0) {
        return "<p class=\"muted\">No strong file matches were found.</p>";
    }

    return `
        <section class="result-section">
            <h3>Retrieved Files</h3>
            ${matches.map((match) => `
                <article class="result-card">
                    <div class="result-path">${escapeHtml(match.path)}</div>
                    <p>${escapeHtml(match.snippet || "")}</p>
                </article>
            `).join("")}
        </section>
    `;
}

function renderKeyValueList(items) {
    return `<ul>${items.map((item) => `<li><strong>${escapeHtml(item.label)}:</strong> ${escapeHtml(item.value)}</li>`).join("")}</ul>`;
}

async function apiCall(url, payload, method = "POST") {
    const options = { method, headers: { "Content-Type": "application/json" } };
    if (method !== "GET") {
        options.body = JSON.stringify(payload || {});
    }

    const response = await fetch(url, options);
    return response.json();
}

function setScanStatus(text, type = "") {
    scanStatus.textContent = text;
    scanStatus.classList.remove("success", "error");
    if (type) {
        scanStatus.classList.add(type);
    }
}

async function loadStatus() {
    try {
        const data = await apiCall("/status", null, "GET");

        if (data.project_path) {
            projectPathInput.value = data.project_path;
            setScanStatus(
                `Scanned: ${data.project_path} | Files: ${data.file_count} | Assets: ${data.asset_count || 0}`,
                "success"
            );
        }

        apiStatus.textContent = data.api_key_configured ? "API Ready" : "API Missing";
    } catch (error) {
        apiStatus.textContent = "Status Error";
    }
}

async function scanProject() {
    const projectPath = projectPathInput.value.trim();
    if (!projectPath) {
        setScanStatus("Enter a UE5 project folder path first.", "error");
        return;
    }

    scanButton.disabled = true;
    setScanStatus("Scanning project files...");
    const progressMessage = addAssistantText("Project Scan", "Scanning your project and building the workspace index...");

    try {
        const data = await apiCall("/scan-project", { project_path: projectPath });

        if (data.error) {
            setScanStatus(data.error, "error");
            updateAssistantMessage(progressMessage, "Project Scan", `<p>${nl2br(data.error)}</p>`);
            return;
        }

        const summary = `Project: ${data.project_path}
Loaded text files: ${data.loaded_count}
Detected assets: ${data.asset_count || 0}
Skipped generated folders: ${data.skipped_generated_count}
Skipped binary assets: ${data.skipped_binary_count}
Skipped unknown or empty: ${data.skipped_unknown_count}
Skipped large files: ${data.skipped_large_count}
Unreadable: ${data.unreadable_count}`;

        setScanStatus(
            `Scanned: ${data.project_path} | Files: ${data.loaded_count} | Assets: ${data.asset_count || 0}`,
            "success"
        );
        updateAssistantMessage(progressMessage, "Project Scan Complete", `<p>${nl2br(summary)}</p>`);
    } catch (error) {
        setScanStatus("Scan failed. Check the server and path, then try again.", "error");
        updateAssistantMessage(
            progressMessage,
            "Project Scan",
            "<p>Scan failed. Check the server and path, then try again.</p>"
        );
    } finally {
        scanButton.disabled = false;
    }
}

function currentModeLabel() {
    return actionSelect.options[actionSelect.selectedIndex].text;
}

function updateModeGuide() {
    const help = MODE_HELP[actionSelect.value] || MODE_HELP.ask;
    let text = help.text;
    let example = help.example;

    if (actionSelect.value === "assetScaffold") {
        const kindHelp = SCAFFOLD_KIND_HELP[assetScaffoldKindSelect.value];
        if (kindHelp) {
            text = `${help.text} ${kindHelp.note}`;
            example = kindHelp.example;
        }
    }

    if (actionSelect.value === "deepAsset") {
        const kindHelp = DEEP_KIND_HELP[deepAssetKindSelect.value];
        if (kindHelp) {
            text = `${help.text} ${kindHelp.note}`;
            example = kindHelp.example;
        }
    }

    modeHelpTitle.textContent = help.title;
    modeHelpText.textContent = text;
    modeHelpExample.textContent = example;
    promptInput.placeholder = help.placeholder;
}

function readPrimaryPrompt() {
    return promptInput.value.trim();
}

async function submitAction() {
    const action = actionSelect.value;
    const prompt = readPrimaryPrompt();
    const modeLabel = currentModeLabel();

    if (requiresPrompt(action) && !prompt) {
        addAssistantText("Missing Input", "Type or paste something into the main box first.");
        return;
    }

    addUserMessage(modeLabel, prompt || "(Used current mode without extra text)");
    submitButton.disabled = true;
    const pending = addAssistantText(modeLabel, "Working...");

    try {
        const result = await runAction(action, prompt);
        updateAssistantMessage(pending, modeLabel, result.html, result.meta || "");
        if (result.clearPrompt !== false) {
            promptInput.value = "";
        }
    } catch (error) {
        updateAssistantMessage(
            pending,
            modeLabel,
            "<p>That request failed. Check the server logs and try again.</p>"
        );
    } finally {
        submitButton.disabled = false;
    }
}

function requiresPrompt(action) {
    return !["architecture", "dependency", "blueprintAwareness", "assetFamily"].includes(action);
}

async function runAction(action, prompt) {
    switch (action) {
        case "ask":
            return askQuestion(prompt);
        case "task":
            return analyzeTaskWorkflow(prompt);
        case "error":
            return analyzeError(prompt);
        case "crash":
            return analyzeCrashLog(prompt);
        case "outputLog":
            return analyzeOutputLog(prompt);
        case "references":
            return findReferences(prompt);
        case "assetDetails":
            return explainAsset(prompt);
        case "assetScaffold":
            return generateAssetScaffold(prompt);
        case "assetEditPlan":
            return generateAssetEditPlan(prompt);
        case "explainFile":
            return explainFile(prompt);
        case "reviewFile":
            return reviewFile(prompt);
        case "blueprintLinks":
            return showBlueprintLinks(prompt);
        case "architecture":
            return mapArchitecture();
        case "selection":
            return analyzeSelection(prompt);
        case "blueprintAwareness":
            return showBlueprintAwareness();
        case "assetFamily":
            return inspectAssetFamily();
        case "blueprintNodes":
            return explainBlueprintNodes(prompt);
        case "deepAsset":
            return deepAnalyzeAsset(prompt);
        case "folder":
            return explainFolder(prompt);
        case "dependency":
            return showDependencyMap();
        case "reflection":
            return analyzeReflection(prompt);
        default:
            return {
                html: "<p>That mode is not wired yet.</p>",
            };
    }
}

async function askQuestion(question) {
    const data = await apiCall("/ask", { question });
    return {
        html: `
            <section class="result-section">
                <h3>Answer</h3>
                <p>${nl2br(data.answer || "No answer returned.")}</p>
            </section>
            ${renderMatches(data.matches || [])}
        `,
    };
}

async function analyzeError(errorText) {
    const data = await apiCall("/analyze-error", { error_text: errorText });
    return {
        html: `<p>${nl2br(data.analysis || data.error || "No analysis returned.")}</p>`,
    };
}

async function findReferences(symbol) {
    const data = await apiCall("/references", { symbol });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>References for ${escapeHtml(data.symbol)}</h3>
                ${(data.exact_matches || []).map((match) => `
                    <article class="result-card">
                        <div class="result-path">${escapeHtml(match.path)}</div>
                        <p class="muted">${escapeHtml(match.count)} exact hit(s)</p>
                        <ul>${(match.hits || []).map((hit) => `<li>Line ${hit.line}: ${escapeHtml(hit.preview)}</li>`).join("")}</ul>
                    </article>
                `).join("") || "<p class=\"muted\">No exact matches found.</p>"}
            </section>
            <section class="result-section">
                <h3>Likely Semantic Matches</h3>
                ${(data.semantic_matches || []).map((match) => `
                    <article class="result-card">
                        <div class="result-path">${escapeHtml(match.path)}</div>
                        <p>${escapeHtml(match.preview || "")}</p>
                    </article>
                `).join("") || "<p class=\"muted\">No semantic matches found.</p>"}
            </section>
        `,
    };
}

async function explainAsset(primaryInput) {
    const selection = selectionInput.value.trim() || primaryInput;
    const data = await apiCall("/asset-details", { selection });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: renderAssetDetails(data),
        meta: data.asset_type_label || "Selected asset",
    };
}

async function generateAssetScaffold(primaryInput) {
    const name = primaryInput;
    const data = await apiCall("/asset-scaffold", {
        asset_kind: assetScaffoldKindSelect.value,
        name,
        purpose: selectionInput.value.trim(),
        class_name: classLinkInput.value.trim(),
    });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: renderAssetScaffold(data),
        meta: data.asset_kind || "Scaffold",
        clearPrompt: true,
    };
}

async function generateAssetEditPlan(primaryInput) {
    const selection = selectionInput.value.trim();
    const data = await apiCall("/asset-edit-plan", {
        selection,
        change_request: primaryInput,
    });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: renderAssetEditPlan(data),
        meta: data.asset_kind || "Edit plan",
    };
}

async function explainFile(primaryInput) {
    const path = filePathInput.value.trim() || primaryInput;
    const mode = explainModeInput.value;
    const data = await apiCall("/explain-file", { path, mode });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>${escapeHtml(data.path)}</h3>
                <p>${escapeHtml(data.what_it_is_for || "")}</p>
                ${renderKeyValueList([
                    { label: "Classes", value: (data.main_classes_functions?.classes || []).join(", ") || "None" },
                    { label: "Functions", value: (data.main_classes_functions?.functions || []).join(", ") || "None" },
                    { label: "Properties", value: (data.main_classes_functions?.properties || []).join(", ") || "None" },
                ])}
            </section>
            <section class="result-section">
                <h3>Important Unreal Pieces</h3>
                ${renderList(data.important_unreal_pieces || [])}
            </section>
            <section class="result-section">
                <h3>Dependencies</h3>
                ${renderList(data.dependencies || [])}
            </section>
            <section class="result-section">
                <h3>Gameplay Connections</h3>
                ${renderList(data.gameplay_connections || [])}
            </section>
            <section class="result-section">
                <h3>Potential Risks</h3>
                ${renderList(data.potential_risks || [])}
            </section>
            ${data.llm_summary ? `<section class="result-section"><h3>AI Summary</h3><p>${nl2br(data.llm_summary)}</p></section>` : ""}
        `,
        meta: mode === "beginner" ? "Beginner mode" : mode === "technical" ? "Technical mode" : "Refactor notes",
    };
}

async function reviewFile(primaryInput) {
    const path = filePathInput.value.trim() || primaryInput;
    const data = await apiCall("/review-file", { path, mode: "refactor" });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>Reviewer Suggestions</h3>
                <p class="muted">${escapeHtml(data.path)}</p>
                ${renderList(data.suggestions || [])}
            </section>
            <section class="result-section">
                <h3>Risks</h3>
                ${renderList(data.explanation?.potential_risks || [])}
            </section>
        `,
    };
}

async function showBlueprintLinks(primaryInput) {
    const className = classLinkInput.value.trim() || primaryInput;
    const data = await apiCall("/blueprint-links", { class_name: className });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>Blueprint Links for ${escapeHtml(data.class_name)}</h3>
                ${(data.matches || []).map((match) => `
                    <article class="result-card">
                        <div class="result-path">${escapeHtml(match.class_name)}</div>
                        <p class="muted">${escapeHtml(match.path)}</p>
                        <p><strong>Blueprint hooks:</strong> ${escapeHtml((match.blueprint_hooks || []).join(", ") || "None detected")}</p>
                        <p><strong>Exposed functions:</strong> ${escapeHtml((match.exposed_functions || []).join(", ") || "None detected")}</p>
                        <p><strong>Editable properties:</strong> ${escapeHtml((match.editable_properties || []).join(", ") || "None detected")}</p>
                    </article>
                `).join("") || "<p class=\"muted\">No direct Blueprint-facing match was found.</p>"}
            </section>
        `,
    };
}

async function mapArchitecture() {
    const data = await apiCall("/architecture-map", null, "GET");
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>Architecture Overview</h3>
                ${renderList(data.overview || [])}
            </section>
            <section class="result-section">
                <h3>Detected Systems</h3>
                <ul>${(data.systems || []).map((item) => `<li>${escapeHtml(item.name)} (${item.count})</li>`).join("")}</ul>
            </section>
            <section class="result-section">
                <h3>High-Centrality Files</h3>
                <ul>${(data.high_centrality_files || []).map((item) => `<li>${escapeHtml(item.path)} [score ${item.score}]</li>`).join("")}</ul>
            </section>
        `,
    };
}

async function analyzeSelection(primaryInput) {
    const selection = selectionInput.value.trim() || primaryInput;
    const data = await apiCall("/selection-analysis", { selection });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    if (data.selection_type === "asset") {
        return {
            html: renderAssetDetails(data),
            meta: data.asset_type_label || "Selected asset",
        };
    }

    if (data.selection_type === "file") {
        return {
            html: `
                <section class="result-section">
                    <h3>Selection: ${escapeHtml(data.selection)}</h3>
                    <p>${escapeHtml(data.explanation?.what_it_is_for || "No explanation available.")}</p>
                </section>
                <section class="result-section">
                    <h3>Suggestions</h3>
                    ${renderList(data.suggestions || [])}
                </section>
            `,
        };
    }

    return {
        html: `
            <section class="result-section">
                <h3>Selection: ${escapeHtml(data.selection)}</h3>
                <p><strong>Reference files:</strong> ${(data.references?.exact_matches || []).length}</p>
                <p><strong>Blueprint links:</strong> ${(data.blueprint_links || []).length}</p>
                <p><strong>Assets:</strong> ${(data.assets || []).length}</p>
            </section>
        `,
    };
}

function renderAssetDetails(data) {
    return `
        <section class="result-section">
            <h3>${escapeHtml(data.title || data.resolved_asset_name || "Selected Asset")}</h3>
            <p class="muted">${escapeHtml(data.asset?.path || "")}</p>
            <p>${escapeHtml(data.summary || "")}</p>
        </section>
        <section class="result-section">
            <h3>What Does This Do?</h3>
            ${renderList(data.what_does_this_do || [])}
        </section>
        <section class="result-section">
            <h3>Gameplay Role</h3>
            <p>${escapeHtml(data.gameplay_role || "No strong gameplay role was inferred yet.")}</p>
        </section>
        <section class="result-section">
            <h3>Linked C++ Classes</h3>
            <p><strong>Primary owner:</strong> ${escapeHtml(data.linked_cpp_classes?.primary_owner || "None")}</p>
            <p><strong>Owner path:</strong> ${escapeHtml(data.linked_cpp_classes?.primary_owner_path || "None")}</p>
            <p><strong>Why:</strong> ${escapeHtml(data.linked_cpp_classes?.primary_owner_reason || "No ranked owner was inferred.")}</p>
            ${renderList(data.linked_cpp_classes?.runtime_classes || [])}
        </section>
        <section class="result-section">
            <h3>What Depends On It</h3>
            ${renderList(data.what_depends_on_it || [])}
            ${(data.depending_files || []).map((item) => `
                <article class="result-card">
                    <div class="result-path">${escapeHtml(item.path)}</div>
                    <p>${escapeHtml(item.reason || "")}</p>
                </article>
            `).join("") || "<p class=\"muted\">No likely dependent files were found yet.</p>"}
        </section>
        <section class="result-section">
            <h3>References</h3>
            ${(data.references?.exact_matches || []).map((match) => `
                <article class="result-card">
                    <div class="result-path">${escapeHtml(match.path)}</div>
                    <p class="muted">${escapeHtml(match.count)} exact hit(s)</p>
                    <ul>${(match.hits || []).slice(0, 5).map((hit) => `<li>Line ${hit.line}: ${escapeHtml(hit.preview)}</li>`).join("")}</ul>
                </article>
            `).join("") || "<p class=\"muted\">No exact references were found.</p>"}
        </section>
        <section class="result-section">
            <h3>What Looks Wrong?</h3>
            ${renderList(data.what_looks_wrong || [])}
        </section>
        <section class="result-section">
            <h3>What Is Missing?</h3>
            ${renderList(data.what_is_missing || data.what_it_might_be_missing || [])}
        </section>
        <section class="result-section">
            <h3>Related Assets</h3>
            ${(data.related_assets || []).map((item) => `
                <article class="result-card">
                    <div class="result-path">${escapeHtml(item.name)}</div>
                    <p class="muted">${escapeHtml(item.path || "")}</p>
                </article>
            `).join("") || "<p class=\"muted\">No closely related assets were inferred.</p>"}
        </section>
    `;
}

function renderAssetScaffold(data) {
    return `
        <section class="result-section">
            <h3>${escapeHtml(data.title || "Asset Scaffold")}</h3>
            <p>${escapeHtml(data.summary || "")}</p>
            <p><strong>Asset kind:</strong> ${escapeHtml(data.asset_kind || "Unknown")}</p>
            <p><strong>Recommended asset name:</strong> ${escapeHtml(data.recommended_asset_name || "None")}</p>
            <p><strong>Recommended asset path:</strong> ${escapeHtml(data.recommended_asset_path || "None")}</p>
            ${data.recommended_class_name ? `<p><strong>Recommended class:</strong> ${escapeHtml(data.recommended_class_name)}</p>` : ""}
            ${data.recommended_parent_class ? `<p><strong>Recommended parent class:</strong> ${escapeHtml(data.recommended_parent_class)}</p>` : ""}
        </section>
        <section class="result-section">
            <h3>Steps</h3>
            ${renderList(data.steps || [])}
        </section>
        <section class="result-section">
            <h3>Starter Files</h3>
            ${(data.files || []).map((item) => `
                <article class="result-card">
                    <div class="result-path">${escapeHtml(item.label || "Generated file")}</div>
                    <pre>${escapeHtml(item.content || "")}</pre>
                </article>
            `).join("") || "<p class=\"muted\">No starter files were generated.</p>"}
        </section>
    `;
}

function renderAssetEditPlan(data) {
    return `
        <section class="result-section">
            <h3>${escapeHtml(data.title || "Asset Edit Plan")}</h3>
            <p>${escapeHtml(data.summary || "")}</p>
            <p><strong>Edit kind:</strong> ${escapeHtml(data.asset_kind || "Unknown")}</p>
            <p><strong>Asset:</strong> ${escapeHtml(data.asset_name || "None")}</p>
            <p><strong>Path:</strong> ${escapeHtml(data.asset_path || "None")}</p>
            <p><strong>Linked owner:</strong> ${escapeHtml(data.linked_cpp_owner || "None")}</p>
            ${data.suggested_new_name ? `<p><strong>Suggested new name:</strong> ${escapeHtml(data.suggested_new_name)}</p>` : ""}
            ${data.suggested_variable_type ? `<p><strong>Suggested variable type:</strong> ${escapeHtml(data.suggested_variable_type)}</p>` : ""}
            ${data.suggested_function_name ? `<p><strong>Suggested function name:</strong> ${escapeHtml(data.suggested_function_name)}</p>` : ""}
            ${data.suggested_function_signature ? `<p><strong>Suggested function signature:</strong> ${escapeHtml(data.suggested_function_signature)}</p>` : ""}
            ${data.suggested_parameter_name ? `<p><strong>Suggested parameter name:</strong> ${escapeHtml(data.suggested_parameter_name)}</p>` : ""}
            ${data.suggested_parameter_type ? `<p><strong>Suggested parameter type:</strong> ${escapeHtml(data.suggested_parameter_type)}</p>` : ""}
            ${data.suggested_node_kind ? `<p><strong>Suggested node kind:</strong> ${escapeHtml(data.suggested_node_kind)}</p>` : ""}
            ${data.suggested_node_name ? `<p><strong>Suggested node name:</strong> ${escapeHtml(data.suggested_node_name)}</p>` : ""}
        </section>
        <section class="result-section">
            <h3>Requested Change</h3>
            <p>${escapeHtml(data.change_request || "")}</p>
        </section>
        <section class="result-section">
            <h3>What To Change</h3>
            ${renderList(data.what_to_change || [])}
        </section>
        <section class="result-section">
            <h3>Fields To Check</h3>
            ${renderList(data.fields_to_check || [])}
        </section>
        <section class="result-section">
            <h3>Risks</h3>
            ${renderList(data.risks || [])}
        </section>
        <section class="result-section">
            <h3>Validation Steps</h3>
            ${renderList(data.validation_steps || [])}
        </section>
    `;
}

async function showBlueprintAwareness() {
    const data = await apiCall("/blueprint-awareness", null, "GET");
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>Blueprint Awareness</h3>
                ${Object.entries(data.families || {}).map(([family, assets]) => `
                    <article class="result-card">
                        <div class="result-path">${escapeHtml(family)}</div>
                        <ul>${assets.map((asset) => `<li>${escapeHtml(asset.name)}</li>`).join("")}</ul>
                    </article>
                `).join("") || "<p class=\"muted\">No Blueprint-related assets were detected.</p>"}
            </section>
        `,
    };
}

async function inspectAssetFamily() {
    const family = assetFamilySelect.value;
    const data = await apiCall("/specialized-assets/family", { family });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>${escapeHtml(data.title || family)}</h3>
                <p>${escapeHtml(data.description || "")}</p>
                <p><strong>Role:</strong> ${escapeHtml(data.role_guess || "")}</p>
                <p><strong>Assets:</strong> ${escapeHtml(data.asset_count ?? 0)} | <strong>Signals:</strong> ${escapeHtml(data.signal_count ?? 0)}</p>
            </section>
            <section class="result-section">
                <h3>Likely Entry Points</h3>
                ${renderList(data.likely_entry_points || [])}
            </section>
            <section class="result-section">
                <h3>Risks</h3>
                ${renderList(data.risks || [])}
            </section>
        `,
    };
}

async function explainBlueprintNodes(nodesText) {
    const data = await apiCall("/explain-blueprint-nodes", { nodes_text: nodesText });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>Blueprint Node Summary</h3>
                <p>${escapeHtml(data.summary || "")}</p>
            </section>
            <section class="result-section">
                <h3>Execution Flow</h3>
                ${renderList(data.execution_flow || [])}
            </section>
            <section class="result-section">
                <h3>Common Mistakes</h3>
                ${renderList(data.common_mistakes || [])}
            </section>
        `,
    };
}

async function deepAnalyzeAsset(exportedText) {
    const selectionName = selectionInput.value.trim();
    const data = await apiCall("/asset-deep-analysis", {
        asset_kind: deepAssetKindSelect.value,
        exported_text: exportedText,
        selection_name: selectionName,
        class_name: classLinkInput.value.trim(),
        asset_path: filePathInput.value.trim(),
        source: "web",
    });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>Deep Asset Analysis</h3>
                <p><strong>${escapeHtml(data.resolved_asset_name || data.selection_name || data.asset_kind)}</strong></p>
                <p>${escapeHtml(data.summary || "")}</p>
                <p><strong>Gameplay role:</strong> ${escapeHtml(data.gameplay_role || "Not inferred")}</p>
                <p><strong>Asset path:</strong> ${escapeHtml(data.asset_path || "Not provided")}</p>
            </section>
            <section class="result-section">
                <h3>Resolved Kind</h3>
                <p>${escapeHtml(data.resolved_asset_kind || data.asset_kind || "Unknown")}</p>
            </section>
            <section class="result-section">
                <h3>Key Elements</h3>
                ${renderList(data.key_elements || [])}
            </section>
            <section class="result-section">
                <h3>Flow Summary</h3>
                ${renderList(data.flow_summary || [])}
            </section>
            <section class="result-section">
                <h3>What Looks Wrong</h3>
                ${renderList(data.what_looks_wrong || [])}
            </section>
            <section class="result-section">
                <h3>What Is Missing</h3>
                ${renderList(data.what_is_missing || [])}
            </section>
        `,
    };
}

async function explainFolder(primaryInput) {
    const folderPath = folderPathInput.value.trim() || primaryInput;
    const data = await apiCall("/folder-explainer", { folder_path: folderPath });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>Folder Summary</h3>
                <p><strong>${escapeHtml(data.folder)}</strong></p>
                <p>${escapeHtml(data.summary || "")}</p>
            </section>
            <section class="result-section">
                <h3>Systems</h3>
                <ul>${(data.systems || []).map((item) => `<li>${escapeHtml(item.name)} (${item.count})</li>`).join("")}</ul>
            </section>
        `,
    };
}

async function showDependencyMap() {
    const data = await apiCall("/dependency-map", null, "GET");
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>Core Files</h3>
                <ul>${(data.core_files || []).map((item) => `<li>${escapeHtml(item.path)} [centrality ${item.score}]</li>`).join("")}</ul>
            </section>
            <section class="result-section">
                <h3>Dependency Relationships</h3>
                ${(data.relationships || []).map((item) => `
                    <article class="result-card">
                        <div class="result-path">${escapeHtml(item.path)}</div>
                        <p><strong>Includes:</strong> ${escapeHtml((item.includes || []).join(", ") || "None")}</p>
                        <p><strong>Resolved dependencies:</strong> ${escapeHtml((item.resolved_dependencies || []).join(", ") || "None")}</p>
                    </article>
                `).join("")}
            </section>
        `,
    };
}

async function analyzeReflection(primaryInput) {
    const text = primaryInput;
    const path = filePathInput.value.trim();
    const data = await apiCall("/reflection-analyzer", { text, path });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>UPROPERTY Flags</h3>
                ${(data.properties || []).map((item) => `
                    <article class="result-card">
                        <div class="result-path">${escapeHtml(item.name)} : ${escapeHtml(item.type)}</div>
                        <p><strong>Flags:</strong> ${escapeHtml((item.flags || []).join(", ") || "None")}</p>
                        <ul>${(item.explanations || []).map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>
                    </article>
                `).join("") || "<p class=\"muted\">No UPROPERTY metadata found.</p>"}
            </section>
            <section class="result-section">
                <h3>UFUNCTION Flags</h3>
                ${(data.functions || []).map((item) => `
                    <article class="result-card">
                        <div class="result-path">${escapeHtml(item.name)} : ${escapeHtml(item.return_type)}</div>
                        <p><strong>Flags:</strong> ${escapeHtml((item.flags || []).join(", ") || "None")}</p>
                        <ul>${(item.explanations || []).map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>
                    </article>
                `).join("") || "<p class=\"muted\">No UFUNCTION metadata found.</p>"}
            </section>
        `,
    };
}

async function analyzeCrashLog(text) {
    const data = await apiCall("/analyze-crash-log", { text });
    return {
        html: `<p>${nl2br(data.analysis || data.error || "No crash analysis returned.")}</p>`,
    };
}

async function analyzeOutputLog(text) {
    const data = await apiCall("/analyze-output-log", { text });
    return {
        html: `<p>${nl2br(data.analysis || data.error || "No output-log analysis returned.")}</p>`,
    };
}

async function analyzeTaskWorkflow(goal) {
    const data = await apiCall("/task-workflow", { goal });
    if (data.error) {
        return { html: `<p>${nl2br(data.error)}</p>` };
    }

    return {
        html: `
            <section class="result-section">
                <h3>Task Scope</h3>
                <p><strong>${escapeHtml(data.goal)}</strong></p>
                <p>${escapeHtml(data.summary || "")}</p>
            </section>
            <section class="result-section">
                <h3>Relevant Files</h3>
                <ul>${(data.relevant_files || []).map((item) => `<li>${escapeHtml(item.path)} [${escapeHtml(item.file_type || "file")}]</li>`).join("")}</ul>
            </section>
            <section class="result-section">
                <h3>Suggested Next Steps</h3>
                ${renderList(data.next_steps || [])}
            </section>
        `,
    };
}

scanButton.addEventListener("click", scanProject);
submitButton.addEventListener("click", submitAction);
actionSelect.addEventListener("change", updateModeGuide);
assetScaffoldKindSelect.addEventListener("change", updateModeGuide);
deepAssetKindSelect.addEventListener("change", updateModeGuide);

promptInput.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        submitAction();
    }
});

loadStatus();
updateModeGuide();
