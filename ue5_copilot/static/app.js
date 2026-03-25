const projectPathInput = document.getElementById("projectPath");
const questionInput = document.getElementById("questionInput");
const scanButton = document.getElementById("scanButton");
const askButton = document.getElementById("askButton");
const scanStatus = document.getElementById("scanStatus");
const answerOutput = document.getElementById("answerOutput");
const matchesOutput = document.getElementById("matchesOutput");
const apiStatus = document.getElementById("apiStatus");

function setText(element, text, empty = false) {
    element.textContent = text;
    element.classList.toggle("empty", empty);
}

function escapeHtml(value) {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

async function loadStatus() {
    const response = await fetch("/status");
    const data = await response.json();

    if (data.project_path) {
        projectPathInput.value = data.project_path;
        setText(
            scanStatus,
            `Scanned: ${data.project_path} (${data.file_count} files)`
        );
    }

    apiStatus.textContent = data.api_key_configured ? "API key ready" : "Missing API key";
}

async function scanProject() {
    const projectPath = projectPathInput.value.trim();
    if (!projectPath) {
        setText(scanStatus, "Enter a UE5 project folder path first.");
        return;
    }

    scanButton.disabled = true;
    setText(scanStatus, "Scanning project files...");

    try {
        const response = await fetch("/scan-project", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ project_path: projectPath })
        });
        const data = await response.json();

        if (data.error) {
            setText(scanStatus, data.error);
            return;
        }

        setText(
            scanStatus,
            `Scanned: ${data.project_path} (${data.file_count} files)`
        );
        setText(
            answerOutput,
            "Project scanned. Ask about gameplay systems, classes, modules, or architecture.",
            true
        );
        setText(
            matchesOutput,
            "Relevant files will show up here after your first question.",
            true
        );
    } catch (error) {
        setText(scanStatus, "Scan failed. Check the server and path, then try again.");
    } finally {
        scanButton.disabled = false;
    }
}

function renderMatches(matches) {
    if (!matches || matches.length === 0) {
        setText(matchesOutput, "No strong file matches were found for that question.", true);
        return;
    }

    matchesOutput.classList.remove("empty");
    matchesOutput.innerHTML = matches
        .map(
            (match) => `
                <article class="match">
                    <div class="match-path">${escapeHtml(match.path)}</div>
                    <pre>${escapeHtml(match.snippet || "")}</pre>
                </article>
            `
        )
        .join("");
}
async function analyzeError() {
  const errorText = document.getElementById("errorText").value;
  const errorAnalysisBox = document.getElementById("errorAnalysisBox");

  errorAnalysisBox.textContent = "Analyzing error...";

  const response = await fetch("/analyze-error", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ error_text: errorText })
  });

  const data = await response.json();
  errorAnalysisBox.textContent = data.analysis || "No analysis returned.";
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

loadStatus();
