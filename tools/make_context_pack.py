"""Tool to generate a consolidated context pack for AI session handoff.

Pure Python standard library implementation.
Combines AGENTS.md, docs/HANDOFF.md, the last 40 lines of docs/VERIFICATION_LOG.md,
and git log --oneline -10 into output/context_pack.md.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def get_git_log(limit: int = 10, cwd: Path | None = None) -> str:
    """Retrieve git log output or a fallback message if git fails."""
    try:
        res = subprocess.run(
            ["git", "log", "--oneline", f"-{limit}"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(cwd) if cwd else None,
        )
        return res.stdout.strip()
    except Exception as e:
        return f"[Git log error or not a git repository: {e}]"


def get_last_n_lines(file_path: Path, n: int = 40) -> str:
    """Read the last n lines of a file safely."""
    if not file_path.exists():
        return f"[File not found: {file_path}]"
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return "".join(lines[-n:]).strip()
    except Exception as e:
        return f"[Error reading file {file_path}: {e}]"


def read_full_file(file_path: Path) -> str:
    """Read full file contents safely."""
    if not file_path.exists():
        return f"[File not found: {file_path}]"
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception as e:
        return f"[Error reading file {file_path}: {e}]"


def generate_context_pack(
    root_dir: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """Generate output/context_pack.md combining core governance and handoff state."""
    base_dir = root_dir or Path.cwd()
    target_output = output_path or (base_dir / "output" / "context_pack.md")

    agents_path = base_dir / "AGENTS.md"
    handoff_path = base_dir / "docs" / "HANDOFF.md"
    verification_path = base_dir / "docs" / "VERIFICATION_LOG.md"

    agents_content = read_full_file(agents_path)
    handoff_content = read_full_file(handoff_path)
    verification_tail = get_last_n_lines(verification_path, 40)
    git_log_content = get_git_log(10, cwd=base_dir)

    pack_content = f"""# AI AFFILIATE CONTENT FACTORY — CONTEXT PACK

## 1. AGENTS.md
{agents_content}

---

## 2. docs/HANDOFF.md
{handoff_content}

---

## 3. Last 40 lines of docs/VERIFICATION_LOG.md
```markdown
{verification_tail}
```

---

## 4. Git Log (Last 10 commits)
```text
{git_log_content}
```
"""

    target_output.parent.mkdir(parents=True, exist_ok=True)
    with open(target_output, "w", encoding="utf-8") as f:
        f.write(pack_content)

    return target_output


if __name__ == "__main__":
    out = generate_context_pack()
    print(f"Context pack generated successfully at: {out}")
