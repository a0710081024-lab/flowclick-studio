from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


ACTION_LABELS: dict[str, str] = {
    "wait": "等待",
    "click": "鼠标点击",
    "scroll": "滚动滚轮",
    "key_press": "按下按键",
    "hotkey": "组合键",
    "type_text": "输入文字",
    "wait_text": "等待文字",
    "click_text": "识别文字并点击",
    "wait_text_choice": "等待文字结果",
    "wait_image": "等待图片",
    "click_image": "识别图片并点击",
    "text_router": "识别页面并跳转",
    "label": "流程标签",
    "watchdog": "启动托管看门狗",
    "loop_start": "循环开始",
    "loop_end": "循环结束",
    "comment": "说明",
}


DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "wait": {"seconds": 1.0},
    "click": {"x": 0, "y": 0, "clicks": 1, "interval": 0.1, "button": "left"},
    "scroll": {"amount": -3, "x": None, "y": None},
    "key_press": {"key": "enter", "presses": 1, "interval": 0.1},
    "hotkey": {"keys": "ctrl,s"},
    "type_text": {"text": "", "interval": 0.03, "paste": True},
    "wait_text": {
        "text": "",
        "match": "contains",
        "timeout": 10.0,
        "poll": 0.7,
        "region": "",
        "min_score": 0.5,
        "on_timeout": "stop",
    },
    "click_text": {
        "text": "",
        "match": "contains",
        "timeout": 10.0,
        "poll": 0.7,
        "region": "",
        "min_score": 0.5,
        "button": "left",
        "on_timeout": "stop",
    },
    "wait_text_choice": {
        "continue_text": "自动隐藏",
        "break_text": "前往开箱",
        "match": "contains",
        "timeout": 60.0,
        "poll": 0.7,
        "region": "",
        "min_score": 0.5,
        "on_timeout": "stop",
    },
    "wait_image": {
        "path": "",
        "confidence": 0.85,
        "timeout": 10.0,
        "poll": 0.5,
        "region": "",
        "on_timeout": "stop",
    },
    "click_image": {
        "path": "",
        "confidence": 0.85,
        "timeout": 10.0,
        "poll": 0.5,
        "region": "",
        "button": "left",
        "on_timeout": "stop",
    },
    "text_router": {
        "routes": "前往开箱=>开箱\n点击快速开箱=>快速开箱\n领取=>领奖\n继续=>继续\n再来一局=>再来",
        "match": "contains",
        "timeout": 1.5,
        "poll": 0.3,
        "region": "",
        "min_score": 0.45,
    },
    "label": {"name": "阶段名称"},
    "watchdog": {
        "stuck_seconds": 60.0,
        "sample_interval": 3.0,
        "region": "",
        "watch_texts": "确认出价,前往开箱,点击快速开箱,领取,继续,再来一局",
        "change_threshold": 2.0,
        "recovery": "restart_workflow",
        "process_name": "",
        "executable": "",
        "arguments": "",
        "restart_wait": 30.0,
        "max_restarts": 10,
    },
    "loop_start": {"count": 2},
    "loop_end": {},
    "comment": {"text": ""},
}


@dataclass
class Step:
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid4().hex)

    @classmethod
    def create(cls, action: str) -> "Step":
        return cls(action=action, params=dict(DEFAULT_PARAMS.get(action, {})))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        action = str(data.get("action", "comment"))
        defaults = dict(DEFAULT_PARAMS.get(action, {}))
        defaults.update(dict(data.get("params", {})))
        return cls(
            id=str(data.get("id") or uuid4().hex),
            action=action,
            params=defaults,
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "enabled": self.enabled,
            "params": self.params,
        }


@dataclass
class Workflow:
    name: str = "未命名流程"
    steps: list[Step] = field(default_factory=list)
    version: int = 1
    source_path: str | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Workflow":
        return cls(
            name=str(data.get("name", "未命名流程")),
            version=int(data.get("version", 1)),
            steps=[Step.from_dict(item) for item in data.get("steps", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "flowclick-workflow",
            "version": self.version,
            "name": self.name,
            "steps": [step.to_dict() for step in self.steps],
        }


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action)


def step_summary(step: Step) -> str:
    p = step.params
    action = step.action
    if action == "wait":
        return f"{p.get('seconds', 0)} 秒"
    if action == "click":
        buttons = {"left": "左键", "right": "右键", "middle": "中键"}
        return (
            f"({p.get('x')}, {p.get('y')}) · {buttons.get(str(p.get('button')), p.get('button'))}"
            f" × {p.get('clicks', 1)}"
        )
    if action == "scroll":
        return f"滚动 {p.get('amount', 0)} 格"
    if action == "key_press":
        return f"{p.get('key', '')} × {p.get('presses', 1)}"
    if action == "hotkey":
        return str(p.get("keys", "")).replace(",", " + ")
    if action == "type_text":
        text = str(p.get("text", ""))
        return (text[:32] + "…") if len(text) > 32 else text
    if action in {"wait_text", "click_text"}:
        return f"“{p.get('text', '')}” · 最长 {p.get('timeout', 0)} 秒"
    if action == "wait_text_choice":
        return (
            f"继续“{p.get('continue_text', '')}” / "
            f"跳出“{p.get('break_text', '')}” · 最长 {p.get('timeout', 0)} 秒"
        )
    if action in {"wait_image", "click_image"}:
        return f"{p.get('path', '')} · 相似度 {p.get('confidence', 0.85)}"
    if action == "text_router":
        routes = [line.strip() for line in str(p.get("routes", "")).splitlines() if line.strip()]
        return f"{len(routes)} 条页面规则 · 最长 {p.get('timeout', 0)} 秒"
    if action == "label":
        return str(p.get("name", ""))
    if action == "watchdog":
        recovery = {
            "restart_workflow": "重启流程",
            "restart_program": "重启程序和流程",
        }.get(str(p.get("recovery")), str(p.get("recovery")))
        return f"画面卡住 {p.get('stuck_seconds', 60)} 秒 → {recovery}"
    if action == "loop_start":
        return f"重复 {p.get('count', 1)} 次"
    if action == "loop_end":
        return "返回对应的循环开始"
    if action == "comment":
        return str(p.get("text", ""))
    return str(p)
