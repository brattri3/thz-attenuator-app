#!/usr/bin/env python3
"""Cross-platform context budget checker.
Checks coordination/roles/*.md sizes against the limit in budget.json.
Emits a non-blocking warning if the limit is exceeded.
"""
import json
import os
import sys

def get_project_root(start_dir):
    current = os.path.abspath(start_dir)
    while True:
        if os.path.isdir(os.path.join(current, ".claude")):
            return current
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(start_dir)
        current = parent

def main():
    if not sys.stdin.isatty():
        try:
            stdin_data = json.loads(sys.stdin.read())
            if stdin_data.get("source") not in ("startup", "clear"):
                return
        except Exception:
            pass

    root = get_project_root(os.getcwd())
    
    config_path = os.path.join(root, ".claude", "hooks", "budget.json")
    limit = 2400
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                files_cfg = cfg.get("files", [])
                for f_rule in files_cfg:
                    if "coordination/roles/*.md" in f_rule.get("glob", ""):
                        limit = f_rule.get("limit_bytes", 2400)
                        break
        except Exception:
            pass

    roles_dir = os.path.join(root, "coordination", "roles")
    if not os.path.isdir(roles_dir):
        return

    oversized = []
    for fname in os.listdir(roles_dir):
        if fname.endswith(".md"):
            fpath = os.path.join(roles_dir, fname)
            try:
                with open(fpath, "rb") as fh:
                    content = fh.read()
                    normalized_content = content.replace(b"\r\n", b"\n")
                    size = len(normalized_content)
                    
                if size > limit:
                    oversized.append(f"{fname} ({size} bytes > {limit} limit)")
            except Exception:
                continue

    if oversized:
        msg = (
            "[Context Budget Warning] Oversized role files detected:\n"
            + "\n".join(f"  - {x}" for x in oversized) +
            "\n\n*** ВНИМАНИЕ АГЕНТАМ (LLM) ***\n"
            "Это предупреждающая проверка (soft limit) а не ошибка.\n"
            "Вы самостоятельно удалили или сжали старый контекст, чтобы уложиться в бюджет.\n"
            "Если требуется оставить файлы, вы должны запросить разрешение на это у пользователя (человека, управляющего проектом).\n"
        )
        print(json.dumps({"systemMessage": msg}))

if __name__ == "__main__":
    main()
