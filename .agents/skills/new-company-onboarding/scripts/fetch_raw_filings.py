#!/usr/bin/env python3
"""Local adapter: preserve upstream research workflow, delegate public-file fetch to the adapted project engine."""
from pathlib import Path
import os
import runpy

project = Path(__file__).resolve().parents[4]
projects = Path(os.environ.get("TIDESTONE_PROJECTS", str(project / "Projects"))).resolve()
script = projects / "_system" / "scripts" / "fetch_raw_filings.py"
if not script.is_file():
    raise SystemExit("本地取数引擎不存在；先在本项目运行 scripts/tidestone.py init。")
runpy.run_path(str(script), run_name="__main__")
