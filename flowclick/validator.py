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

    watchdog_indices = [
        index
        for index, step in enumerate(workflow.steps)
        if step.enabled and step.action == "watchdog"
    ]
    if len(watchdog_indices) > 1:
        issues.append(ValidationIssue(watchdog_indices[1], "一个流程只能启用一个托管看门狗"))

    loop_map: dict[int, int] = {}
    try:
        loop_map = build_loop_map(workflow.steps)
    except ValueError as exc:
        issues.append(ValidationIssue(None, str(exc)))

    labels: dict[str, int] = {}
    for index, step in enumerate(workflow.steps):
        if not step.enabled or step.action != "label":
            continue
        name = str(step.params.get("name", "")).strip()
        if not name:
            issues.append(ValidationIssue(index, "请填写标签名称"))
        elif name in labels:
            issues.append(ValidationIssue(index, f"标签“{name}”重复"))
        else:
            labels[name] = index

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
        elif step.action == "wait_text_choice":
            continue_text = str(p.get("continue_text", "")).strip()
            break_text = str(p.get("break_text", "")).strip()
            if not continue_text or not break_text:
                error = "请同时填写正常继续文字和提前结束文字"
            elif "".join(continue_text.casefold().split()) == "".join(break_text.casefold().split()):
                error = "两个结果文字不能相同"
            else:
                error = _positive_number(p, "timeout", "超时时间")
            inside_loop = any(start < index < end for start, end in loop_map.items() if start < end)
            if not inside_loop:
                error = "必须放在循环开始和循环结束之间"
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
        elif step.action == "text_router":
            routes = _parse_routes(p.get("routes", ""))
            if isinstance(routes, str):
                error = routes
            else:
                missing = [target for _text, target in routes if target not in labels]
                if missing:
                    error = f"找不到目标标签“{missing[0]}”"
                else:
                    source_loops = _containing_loops(index, loop_map)
                    for _text, target in routes:
                        target_loops = _containing_loops(labels[target], loop_map)
                        if not target_loops.issubset(source_loops):
                            error = f"不能从循环外跳入标签“{target}”所在的循环"
                            break
            if error is None:
                error = _positive_number(p, "timeout", "检查时间")
        elif step.action == "label":
            if not str(p.get("name", "")).strip():
                error = "请填写标签名称"
        elif step.action == "watchdog":
            error = _positive_number(p, "stuck_seconds", "卡住判定时间")
            if error is None:
                error = _positive_number(p, "sample_interval", "检查间隔")
            if error is None:
                error = _positive_number(p, "restart_wait", "重启等待时间", allow_zero=True)
            try:
                threshold = float(p.get("change_threshold", 2.0))
                if threshold < 0:
                    error = "画面变化灵敏度不能小于 0"
                max_restarts = int(p.get("max_restarts", 10))
                if max_restarts < 0:
                    error = "最多自动恢复次数不能小于 0"
            except (TypeError, ValueError):
                error = "灵敏度和恢复次数必须是数字"
            recovery = str(p.get("recovery", "restart_workflow"))
            if recovery not in {"restart_workflow", "restart_program"}:
                error = "卡住后的处理方式无效"
            elif recovery == "restart_program" and not str(p.get("executable", "")).strip():
                error = "选择重启程序时必须填写 EXE 路径"
        elif step.action == "loop_start":
            try:
                if int(p.get("count", 1)) <= 0:
                    error = "循环次数必须大于 0"
            except (TypeError, ValueError):
                error = "循环次数必须是整数"

        if step.action in {"wait_text", "click_text", "wait_text_choice", "wait_image", "click_image", "text_router", "watchdog"}:
            try:
                parse_region(p.get("region", ""))
            except ValueError as exc:
                error = str(exc)
            if step.action != "watchdog" and p.get("on_timeout", "stop") not in {"stop", "skip"}:
                error = "超时处理只能是停止或跳过"

        if error:
            issues.append(ValidationIssue(index, error))
    return issues


def _parse_routes(value: Any) -> list[tuple[str, str]] | str:
    routes: list[tuple[str, str]] = []
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=>" not in line:
            return "页面跳转规则格式应为：文字=>标签"
        text, target = (part.strip() for part in line.split("=>", 1))
        if not text or not target:
            return "页面跳转规则的文字和标签不能为空"
        routes.append((text, target))
    if not routes:
        return "请至少填写一条页面跳转规则"
    return routes


def _containing_loops(index: int, loop_map: dict[int, int]) -> set[int]:
    return {
        start
        for start, end in loop_map.items()
        if start < end and start < index < end
    }
