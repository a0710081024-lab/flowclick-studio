from __future__ import annotations

import json
from pathlib import Path

from .models import Workflow


def load_workflow(path: str | Path) -> Workflow:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("format") not in (None, "flowclick-workflow"):
        raise ValueError("这不是 FlowClick 流程文件")
    workflow = Workflow.from_dict(data)
    workflow.source_path = str(file_path.resolve())
    return workflow


def save_workflow(workflow: Workflow, path: str | Path) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", encoding="utf-8") as handle:
        json.dump(workflow.to_dict(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    workflow.source_path = str(file_path.resolve())


def resolve_asset_path(workflow: Workflow, asset_path: str) -> Path:
    candidate = Path(asset_path)
    if candidate.is_absolute() or not workflow.source_path:
        return candidate
    return Path(workflow.source_path).parent / candidate
