#!/usr/bin/env python3
"""Validate local skill discovery fields, local links, and preserved upstream files."""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[4]
SKILLS = ROOT / ".agents" / "skills"
manifest = json.loads((SKILLS / "tidestone-research/references/upstream-manifest.json").read_text())
errors = []
checked = 0
for path in sorted(SKILLS.glob("*/SKILL.md")):
    text = path.read_text()
    checked += 1
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        errors.append(str(path) + ": missing frontmatter")
        continue
    front = match.group(1)
    name = re.search(r"^name:\s*(.+)$", front, re.M)
    if not name or name.group(1).strip() != path.parent.name:
        errors.append(str(path) + ": name does not match directory")
    if not re.search(r"^description:\s*\S", front, re.M):
        errors.append(str(path) + ": missing description")
    for link in re.findall(r"\]\(([^)]+)\)", text):
        link = link.split("#", 1)[0]
        if link and not re.match(r"[a-z]+://", link) and not (path.parent / link).exists():
            errors.append(str(path) + ": broken link " + link)
for skill in manifest["skills"]:
    base = SKILLS / skill["name"]
    original = base / "references/original.md"
    source = ROOT / skill["source"]
    if not original.is_file() or not source.is_file():
        errors.append(skill["name"] + ": original/source missing")
    elif hashlib.sha256(original.read_bytes()).hexdigest() != skill["original_sha256"] or original.read_bytes() != source.read_bytes():
        errors.append(skill["name"] + ": upstream original mismatch")
    for res in skill["resources"]:
        path = base / res.get("preserved_original", res["path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != res["sha256"]:
            errors.append(str(path) + ": resource hash mismatch")
        if "adapter_sha256" in res:
            adapter = base / res["path"]
            if not adapter.is_file() or hashlib.sha256(adapter.read_bytes()).hexdigest() != res["adapter_sha256"]:
                errors.append(str(adapter) + ": adapter hash mismatch")
result = {"ok": not errors, "entrypoints": checked, "preserved_upstream_skills": len(manifest["skills"]), "errors": errors, "known_missing_upstream_references": manifest["missing_upstream_references"], "excluded_upstream_placeholders": manifest["excluded_placeholders"]}
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(1 if errors else 0)
