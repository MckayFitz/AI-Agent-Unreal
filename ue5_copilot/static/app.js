const projectPathInput = document.getElementById("projectPath");
const questionInput = document.getElementById("questionInput");
const errorTextInput = document.getElementById("errorText");
const scanButton = document.getElementById("scanButton");
const askButton = document.getElementById("askButton");
const scanStatus = document.getElementById("scanStatus");
const answerOutput = document.getElementById("answerOutput");
const errorAnalysisBox = document.getElementById("errorAnalysisBox");
const matchesOutput = document.getElementById("matchesOutput");
const apiStatus = document.getElementById("apiStatus");

function setText(element, text, empty = false) {
    element.textContent = text;
    element.classList.toggle("empty", empty);
    element.classList.toggle("muted-output", empty);
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

async function loadStatus() {
    try {
        const response = await fetch("/status");
        const data = await response.json();

        if (data.project_path) {
            projectPathInput.value = data.project_path;
            setText(
                scanStatus,
                `Scanned project: ${data.project_path} | Loaded files: ${data.file_count}`
            );
            scanStatus.classList.remove("error");
            scanStatus.classList.add("success");
        }

        apiStatus.textContent = data.api_key_configured ? "API Ready" : "API Missing";
    } catch (error) {
        apiStatus.textContent = "Status Error";
    }
}

async function scanProject() {
    const projectPath = projectPathInput.value.trim();

    if (!projectPath) {
        setText(scanStatus, "Enter a UE5 project folder path first.");
        scanStatus.classList.remove("success");
        scanStatus.classList.add("error");
        return;
    }

    scanButton.disabled = true;
    setText(scanStatus, "Scanning project files...");
    scanStatus.classList.remove("success", "error");

    try {
        const response = await fetch("/scan-project", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_path: projectPath })
        });

        const data = await response.json();

        if (data.error) {
            setText(scanStatus, data.error);
            scanStatus.classList.remove("success");
            scanStatus.classList.add("error");
            return;
        }

                setText(
            scanStatus,
            `Project: ${data.project_path}
Total files seen: ${data.total_files_seen}
Loaded text files: ${data.loaded_count}
Skipped generated folders: ${data.skipped_generated_count}
Skipped binary assets: ${data.skipped_binary_count}
Skipped unknown/empty: ${data.skipped_unknown_count}
Skipped large files: ${data.skipped_large_count}
Unreadable: ${data.unreadable_count}`
        );
        scanStatus.classList.remove("error");
        scanStatus.classList.add("success");

        setText(
            answerOutput,
            "Project scanned. Ask about gameplay systems, classes, modules, architecture, or build setup.",
            true
        );

        setText(
            errorAnalysisBox,
            "Paste an Unreal or Visual Studio error to get a breakdown and likely fix.",
            true
        );

        setText(
            matchesOutput,
            "Relevant files and snippets will appear here after your first question.",
            true
        );
    } catch (error) {
        setText(scanStatus, "Scan failed. Check the server and path, then try again.");
        scanStatus.classList.remove("success");
        scanStatus.classList.add("error");
    } finally {
        scanButton.disabled = false;
    }
}

function renderMatches(matches) {
    if (!matches || matches.length === 0) {
        setText(matchesOutput, "No strong file matches were found for that question.", true);
        return;
    }

    matchesOutput.classList.remove("empty", "muted-output");
    matchesOutput.innerHTML = matches
        .map(
            (match) => `
                <article class="match-item">
                    <span class="match-path">${escapeHtml(match.path)}</span>
                    <div class="match-snippet">${escapeHtml(match.snippet || "")}</div>
                </article>
            `
        )
        .join("");
}

async function analyzeError() {
    const errorText = errorTextInput.value.trim();

    if (!errorText) {
        setText(errorAnalysisBox, "Paste an Unreal or Visual Studio error first.", false);
        return;
    }

    setText(errorAnalysisBox, "Analyzing error...");

    try {
        const response = await fetch("/analyze-error", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ error_text: errorText })
        });

        const data = await response.json();
        setText(errorAnalysisBox, data.analysis || "No analysis returned.");
    } catch (error) {
        setText(errorAnalysisBox, "Error analysis failed. Check the server logs and try again.");
    }
}

async function askQuestion() {
    const question = questionInput.value.trim();

    if (!question) {
        setText(answerOutput, "Type a question about your scanned UE5 project.", false);
        return;
    }

    askButton.disabled = true;
    setText(answerOutput, "Thinking through your project context...");

    try {
        const response = await fetch("/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question })
        });

        const data = await response.json();

        setText(answerOutput, data.answer || "No answer returned.");
        renderMatches(data.matches || []);
    } catch (error) {
        setText(answerOutput, "Question failed. Check the server logs and try again.");
    } finally {
        askButton.disabled = false;
    }
}

scanButton.addEventListener("click", scanProject);
askButton.addEventListener("click", askQuestion);

questionInput.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        askQuestion();
    }
});

errorTextInput?.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        analyzeError();
    }
});

loadStatus();