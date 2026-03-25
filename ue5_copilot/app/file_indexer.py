from pathlib import Path

ALLOWED_EXTENSIONS = {".h", ".cpp", ".cs", ".uproject"}

def scan_project(project_path: str):
    root = Path(project_path)
    if not root.exists():
        return {"error": "Project path does not exist."}

    files_data = []

    for file_path in root.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in ALLOWED_EXTENSIONS:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                files_data.append({
                    "path": str(file_path),
                    "name": file_path.name,
                    "extension": file_path.suffix.lower(),
                    "content": content
                })
            except Exception as e:
                files_data.append({
                    "path": str(file_path),
                    "name": file_path.name,
                    "extension": file_path.suffix.lower(),
                    "content": "",
                    "error": str(e)
                })

    return {
        "project_path": project_path,
        "file_count": len(files_data),
        "files": files_data
    }