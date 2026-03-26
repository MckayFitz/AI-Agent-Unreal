from pathlib import Path
from collections import Counter

SKIP_FOLDERS = {
    ".vs",
    ".vscode",
    "binaries",
    "deriveddatacache",
    "intermediate",
    "saved",
    "__pycache__",
    "venv",
    ".git",
    ".idea",
    "node_modules",
}

TEXT_EXTENSIONS = {
    ".h",
    ".hpp",
    ".cpp",
    ".c",
    ".cc",
    ".cxx",
    ".hh",
    ".hxx",
    ".inl",
    ".ipp",
    ".cs",
    ".ini",
    ".json",
    ".txt",
    ".md",
    ".uproject",
    ".uplugin",
    ".py",
    ".bat",
    ".ps1",
    ".sh",
    ".yaml",
    ".yml",
    ".xml",
    ".toml",
    ".cfg",
    ".conf",
    ".usf",
    ".ush",
}

BINARY_EXTENSIONS = {
    ".uasset",
    ".umap",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tga",
    ".gif",
    ".dds",
    ".ico",
    ".exe",
    ".dll",
    ".lib",
    ".obj",
    ".pdb",
    ".bin",
    ".pak",
    ".mp3",
    ".wav",
    ".ogg",
    ".mp4",
    ".mov",
    ".avi",
    ".zip",
    ".7z",
    ".rar",
    ".pdf",
    ".fbx",
    ".blend",
    ".psd",
}

MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB


def should_skip_path(path: Path) -> bool:
    return any(part.lower() in SKIP_FOLDERS for part in path.parts)


def is_special_unreal_text_file(file_path: Path) -> bool:
    name = file_path.name.lower()
    return name.endswith(".build.cs") or name.endswith(".target.cs")


def looks_like_text_file(file_path: Path) -> bool:
    suffix = file_path.suffix.lower()

    if is_special_unreal_text_file(file_path):
        return True

    if suffix in TEXT_EXTENSIONS:
        return True

    if suffix in BINARY_EXTENSIONS:
        return False

    return False


def safe_read_text(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8", errors="ignore")


def scan_project(project_path: str):
    root = Path(project_path).expanduser().resolve()

    if not root.exists():
        return {"error": "Project path does not exist."}

    if not root.is_dir():
        return {"error": "Project path is not a folder."}

    files_data = []
    loaded_files = []

    total_files_seen = 0
    loaded_count = 0
    skipped_generated_count = 0
    skipped_binary_count = 0
    skipped_unknown_count = 0
    skipped_large_count = 0
    unreadable_count = 0

    extension_counter = Counter()

    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue

        total_files_seen += 1

        if should_skip_path(file_path):
            skipped_generated_count += 1
            continue

        try:
            if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
                skipped_large_count += 1
                continue
        except OSError:
            unreadable_count += 1
            continue

        suffix = file_path.suffix.lower()
        extension_counter[suffix or "[no extension]"] += 1

        if not looks_like_text_file(file_path):
            if suffix in BINARY_EXTENSIONS:
                skipped_binary_count += 1
            else:
                skipped_unknown_count += 1
            continue

        try:
            content = safe_read_text(file_path)

            if not content.strip():
                skipped_unknown_count += 1
                continue

            loaded_count += 1

            file_record = {
                "path": str(file_path),
                "name": file_path.name,
                "extension": suffix,
                "content": content,
            }

            files_data.append(file_record)
            loaded_files.append(str(file_path))

        except Exception as e:
            unreadable_count += 1
            files_data.append({
                "path": str(file_path),
                "name": file_path.name,
                "extension": suffix,
                "content": "",
                "error": str(e)
            })

    top_extensions = [
        {"extension": ext, "count": count}
        for ext, count in extension_counter.most_common(20)
    ]

    return {
        "project_path": str(root),
        "file_count": len(files_data),
        "loaded_count": loaded_count,
        "total_files_seen": total_files_seen,
        "skipped_generated_count": skipped_generated_count,
        "skipped_binary_count": skipped_binary_count,
        "skipped_unknown_count": skipped_unknown_count,
        "skipped_large_count": skipped_large_count,
        "unreadable_count": unreadable_count,
        "loaded_files": loaded_files[:200],
        "top_extensions": top_extensions,
        "files": files_data,
    }