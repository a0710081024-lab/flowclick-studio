from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import ACTION_LABELS, Step, Workflow


@dataclass(frozen=True)
class ValidationIssue:
    step_index: int | None
    message: str

    def display(self) -> str:
        if self.step_index is None:
            return self.message
        return f"第 {self.step_index + 1} 步：{self.message}"


def parse_region(value: Any) -> tuple[int, int, int, int] | None:
    if value in (None, "", []):
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        parts = value
    else:
        parts = [part.strip() for part in str(value).split(",")]
    if len(parts) != 4:
        raise ValueError("区域应填写为 x,y,宽,高")
    x, y, width, height = (int(float(part)) for part in parts)
    if width <= 0 or height <= 0:
        raise ValueError("区域宽度和高度必须大于 0")
    return x, y, width, height


def build_loop_map(steps: list[Step]) -> dict[int, int]:
    stack: list[int] = []
    mapping: dict[int, int] = {}
    for index, step in enumerate(steps):
        if not step.enabled:
            continue
        if step.action == "loop_start":
            stack.append(index)
        elif step.action == "loop_end":
            if not stack:
                raise ValueError(f"第 {index + 1} 步缺少对应的循环开始")
            start = stack.pop()
            mapping[start] = index
            mapping[index] = start
    if stack:
        first = stack[-1]
        raise ValueError(f"第 {first + 1} 步缺少对应的循环结束")
    return mapping


def _positive_number(params: dict[str, Any], key: str, label: str, allow_zero: bool = False) -> str | None:
    try:
        value = float(params.get(key))
    except (TypeError, ValueError):
        return f"{label}必须是数字"
    if allow_zero and value < 0:
        return f"{label}不能小于 0"
    if not allow_zero and value <= 0:
        return f"{label}必须大于 0"
    return None


def validate_workflow(workflow: Workflow) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not workflow.steps:
        issues.append(ValidationIssue(None, "流程中还没有步骤"))
        return issues

    try:
        build_loop_map(workflow.steps)
    except ValueError as exc:
        issues.append(ValidationIssue(None, str(exc)))

    for index, step in enumerate(workflow.steps):
        if not step.enabled:
            continue
        p = step.params
        if step.action not in ACTION_LABELS:
            issues.append(ValidationIssue(index, f"不支持的操作：{step.action}"))
            continue
        error: str | None = None
        if step.action == "wait":
            error = _positive_number(p, "seconds", "等待时间", allow_zero=True)
        elif step.action == "click":
            try:
                int(p.get("x"))
                int(p.get("y"))
                if int(p.get("clicks", 1)) <= 0:
                    error = "点击次数必须大于 0"
            except (TypeError, ValueError):
                error = "点击坐标和次数必须是整数"
        elif step.action == "scroll":
            try:
                int(p.get("amount"))
            except (TypeError, ValueError):
                error = "滚动格数必须是整数"
        elif step.action == "key_press":
            if not str(p.get("key", "")).strip():
                error = "请填写按键名称"
        elif step.action == "hotkey":
            if not [k for k in str(p.get("keys", "")).split(",") if k.strip()]:
                error = "请填写组合键，例如 ctrl,s"
        elif step.action == "type_text":
            if p.get("text") is None:
                error = "输入内容不能为 null"
        elif step.action in {"wait_text", "click_text"}:
            if not str(p.get("text", "")).strip():
                error = "请填写要识别的文字"
            else:
                error = _positive_number(p, "timeout", "超时时间")
        elif step.action in {"wait_image", "click_image"}:
            if not str(p.get("path", "")).strip():
                error = "请选择要识别的图片"
            else:
                error = _positive_number(p, "timeout", "超时时间")
            try:
                confidence = float(p.get("confidence", 0.85))
                if not 0 < confidence <= 1:
                    error = "图片相似度必须在 0 到 1 之间"
            except (TypeError, ValueError):
                error = "图片相似度必须是数字"
        elif step.action == "loop_start":
            try:
                if int(p.get("count", 1)) <= 0:
                    error = "循环次数必须大于 0"
            except (TypeError, ValueError):
                error = "循环次数必须是整数"

        if step.action in {"wait_text", "click_text", "wait_image", "click_image"}:
            try:
                parse_region(p.get("region", ""))
            except ValueError as exc:
                error = str(exc)
            if p.get("on_timeout", "stop") not in {"stop", "skip"}:
                error = "超时处理只能是停止或跳过"

        if error:
            issues.append(ValidationIssue(index, error))
    return issues
