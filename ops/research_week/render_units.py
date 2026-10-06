#!/usr/bin/env python3
"""Render reviewable unit files locally; never install, enable or start them."""
import json
from pathlib import Path

base = Path(__file__).resolve().parent
repo = base.parent.parent
output = base / "rendered"
output.mkdir(exist_ok=True)
templates = sorted((base / "units").glob("*.in")) + sorted((base.parent / "continuous_monitor").glob("*.in"))
rendered = []
for template in templates:
    target = output / template.name.removesuffix(".in")
    content = (template.read_text()
               .replace("@REPO@", str(repo))
               .replace("@MOBILE_LAB@", str(repo.parent / "usa-atlas-design-lab" / "mobile-lab")))
    target.write_text(content, encoding="utf-8")
    rendered.append(str(target))
print(json.dumps({"rendered": rendered, "installed": False}))
