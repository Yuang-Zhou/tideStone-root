"""Local paths only. TIDESTONE_PROJECTS isolates tests from the formal library."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECTS_ROOT = Path(os.environ.get('TIDESTONE_PROJECTS', REPO_ROOT / 'Projects')).expanduser().resolve()
SYSTEM_DIR = PROJECTS_ROOT / '_system'
SOURCE_SCRIPTS = Path(__file__).resolve().parent
