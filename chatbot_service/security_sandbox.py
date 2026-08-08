import os
from pathlib import Path
from typing import List
import database

# Root workspace path
BASE_DIR = Path(__file__).resolve().parent.parent

# Default Whitelisted Directories & Files (Only public-accessible documentation)
ALLOWED_PATHS: List[Path] = [
    BASE_DIR / "docs",
    BASE_DIR / "media" / "public_docs",
    BASE_DIR / "README.md",
    BASE_DIR / "testing_guide.md",
    BASE_DIR / "simple_feature_summary_report.md"
]

FORBIDDEN_EXTENSIONS = {".env", ".sqlite3", ".py", ".pem", ".key", ".sh", ".zip", ".git"}
FORBIDDEN_FILENAMES = {"db.sqlite3", ".env", "LightsailDefaultKey-ap-southeast-1.pem"}

def is_path_safe(target_path: str) -> bool:
    """
    Validates if target_path is within allowed directories or files,
    preventing path traversal and access to sensitive/system files.
    """
    try:
        resolved_path = Path(target_path).resolve()
        
        # Check forbidden filenames and extensions
        if resolved_path.name in FORBIDDEN_FILENAMES or resolved_path.suffix.lower() in FORBIDDEN_EXTENSIONS:
            return False

        # Check if resolved path is inside any allowed path
        for allowed in ALLOWED_PATHS:
            allowed_resolved = allowed.resolve()
            if allowed_resolved.is_file():
                if resolved_path == allowed_resolved:
                    return True
            elif allowed_resolved.is_dir():
                if allowed_resolved in resolved_path.parents or resolved_path == allowed_resolved:
                    return True
        return False
    except Exception:
        return False

def get_allowed_documents_content() -> str:
    """
    Safely reads allowed public knowledge documents AND custom admin knowledge base entries
    to provide as context for Gemini AI.
    """
    context_chunks = []
    
    # 1. Custom Knowledge Base entries created by System Admin
    try:
        entries = database.get_custom_knowledge_entries()
        for entry in entries:
            if entry.get("is_active"):
                context_chunks.append(f"--- Custom Guide: {entry['title']} ---\n{entry['content']}\n")
    except Exception:
        pass

    # 2. File-based public documentation
    for path_item in ALLOWED_PATHS:
        try:
            resolved = path_item.resolve()
            if resolved.exists():
                if resolved.is_file() and is_path_safe(str(resolved)):
                    with open(resolved, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read(15000) # Read up to 15k chars per file
                        context_chunks.append(f"--- Document File: {resolved.name} ---\n{content}\n")
                elif resolved.is_dir():
                    for root, _, files in os.walk(resolved):
                        for file in files:
                            file_path = Path(root) / file
                            if is_path_safe(str(file_path)):
                                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read(10000)
                                    context_chunks.append(f"--- Document File: {file_path.name} ---\n{content}\n")
        except Exception:
            continue

    if not context_chunks:
        return "No system guide documentation available."
    
    return "\n".join(context_chunks)

if __name__ == "__main__":
    print("Testing Security Sandbox...")
    print("Is README.md safe?", is_path_safe(str(BASE_DIR / "README.md")))
    print("Is .env safe?", is_path_safe(str(BASE_DIR / ".env")))
    print("Is /etc/passwd safe?", is_path_safe("/etc/passwd"))
    print("\n--- Knowledge Base Content Preview ---")
    print(get_allowed_documents_content()[:300])
