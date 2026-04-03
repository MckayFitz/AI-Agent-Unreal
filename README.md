# UE5 AI Agent

An AI-powered assistant designed to help Unreal Engine 5 developers understand their projects, debug errors, and navigate complex C++ codebases.

This tool scans a UE5 project, extracts relevant source files, and allows developers to ask questions about their code or paste build errors for instant analysis.

---


## 🚀 Features

### 🔍 Project Scanner
- Scans Unreal Engine projects
- Indexes C++ files, config files, and build files
- Skips unnecessary/generated files automatically
- Provides insight into project structure

### 💬 Code Assistant
- Ask questions about your project:
  - "How does movement work?"
  - "Where is damage handled?"
  - "Explain this class"

### 🧠 Context-Aware Answers
- Searches relevant files before answering
- Returns explanations, matched files, and code snippets

### 🛠️ Error Analyzer
- Paste Unreal or Visual Studio errors
- Get:
  - simple explanation
  - likely cause
  - fix suggestions

---

## 🏗️ Tech Stack

- Python
- FastAPI
- OpenAI API
- JavaScript (Frontend)
- HTML/CSS
- Unreal Engine 5

---

## ⚙️ Setup & Installation

### 🔑 1. Get an OpenAI API Key

This project **requires an API key**.

1. Go to: https://platform.openai.com/api-keys  
2. Create a key  
3. Copy it (starts with `sk-...`)

---

### 📥 2. Clone the Repository

```bash
git clone https://github.com/yourusername/ue5-ai-copilot.git
cd ue5-ai-copilot
```

---

### 🐍 3. Create a Virtual Environment

```bash
python -m venv venv
```

---

### ▶️ 4. Activate the Virtual Environment

**PowerShell:**
```bash
.\venv\Scripts\Activate.ps1
```

**Command Prompt:**
```bash
venv\Scripts\activate
```

You should see:
```bash
(venv)
```

---

### 📦 5. Install Dependencies

```bash
pip install fastapi uvicorn python-dotenv openai pydantic
```

---

### 🔐 6. Add Your API Key

Create a `.env` file in the root folder:

```env
OPENAI_API_KEY=your_api_key_here
```

⚠️ Important:
- No quotes
- Do NOT upload this file to GitHub

---

### 🚀 7. Run the Server

```bash
python -m uvicorn app.main:app --reload
```

---

### 🌐 8. Open the App

Go to:
http://127.0.0.1:8000

---

## 🧪 Usage

### 🔍 Scan a Project

Enter your Unreal project path:
C:\Users\YourName\Documents\Unreal Projects\YourProject

Click **Scan Project**

---

### 💬 Ask Questions

Example:
Where is player movement handled?

---

### 🛠️ Analyze Errors

Paste errors from:
- Unreal Engine
- Visual Studio

---

## ⚠️ Limitations

- Cannot read Blueprint `.uasset` node graphs directly
- Focused on C++ and config files
- Blueprint support is limited

---

## 🔮 Future Improvements

- UE5 Editor Plugin integration
- Blueprint node analysis
- Find usage feature
- Code generation
- Project visualization tools

---

## 🎯 Why This Project Matters

This tool helps developers:
- understand large codebases
- debug faster
- improve development workflow

---

## 👤 Author

McKay Fitzgerald  
Computer Science / Software Development  

---

## ⭐ Notes

This project is under active development and will continue improving with new AI-assisted features. 

Future Improvements Under work:

Find Usage / References

Locate where classes, functions, or variables are used

Explain Selected File

Click a file → get full breakdown

Project Architecture Mapping

Visualize systems, modules, and dependencies

Auto Code Suggestions

Suggest improvements or missing log

Blueprint Awareness (Phase 1)

Detect Blueprint assets

Infer roles (Character, Weapon, UI, etc.)

Blueprint Node Explainer

Paste copied nodes → get explanation + flow

C++ ↔ Blueprint Linking

Show which Blueprints inherit from C++ classes

UE5 Editor Plugin

Dockable AI assistant inside Unreal

Current Selection Awareness

Detect selected actor, Blueprint, or file
One-Click Analysis
Right-click → “Explain this”
Live Debug Assistant
Help while editing in real time
