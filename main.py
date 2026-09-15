#!/usr/bin/env python3
"""
zjjjzx-watcher: 智能家教需求抓取、测距与语义匹配系统
Unified Entrypoint supporting CLI, TUI, and backward compatibility.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure package directory is in sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from zjjjzx.cli import main as cli_main
from zjjjzx.tui import run_tui


def main() -> int:
    # If user explicitly requests TUI via flag or argument
    if "--tui" in sys.argv:
        sys.argv.remove("--tui")
        run_tui()
        return 0

    if "--web" in sys.argv:
        sys.argv.remove("--web")
        from zjjjzx.web import run_web_server
        run_web_server()
        return 0

    # If first argument is 'tui'
    if len(sys.argv) > 1 and sys.argv[1] == "tui":
        run_tui()
        return 0

    # Backward compatibility: if flags like --dry-run or --loop are given without subcommand
    legacy_flags = {"--dry-run", "--loop", "--config", "-c", "--force", "--no-llm"}
    if len(sys.argv) > 1 and sys.argv[1] in legacy_flags:
        sys.argv.insert(1, "run")

    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
