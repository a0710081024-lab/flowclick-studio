from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .models import ACTION_LABELS, DEFAULT_PARAMS, Step


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str = "text"
    choices: tuple[tuple[str, str], ...] = ()
    hint: str = ""


BUTTONS = (("左键", "left"), ("右键", "right"), ("中键", "middle"))
TIMEOUTS = (("停止流程", "stop"), ("跳过此步", "skip"))
MATCHES = (("包含目标文字", "contains"), ("完全一致", "exact"))


FIELDS: dict[str, list[FieldSpec]] = {
    "wait": [FieldSpec("seconds", "等待秒数", "float")],
    "click": [
        FieldSpec("x", "X 坐标", "int"),
        FieldSpec("y", "Y 坐标", "int"),
        FieldSpec("clicks", "点击次数", "int"),
        FieldSpec("interval", "多次点击间隔（秒）", "float"),
        FieldSpec("button", "鼠标按键", "choice", BUTTONS),
    ],
    "scroll": [
        FieldSpec("amount", "滚动格数", "int", hint="负数向下，正数向上"),
        FieldSpec("x", "可选 X 坐标", "optional_int"),
        FieldSpec("y", "可选 Y 坐标", "optional_int"),
    ],
    "key_press": [
        FieldSpec("key", "按键名称", hint="例如 enter、space、f5"),
        FieldSpec("presses", "按下次数", "int"),
        FieldSpec("interval", "按键间隔（秒）", "float"),
    ],
    "hotkey": [FieldSpec("keys", "组合键", hint="用英文逗号分隔，例如 ctrl,shift,s")],
    "type_text": [
        FieldSpec("text", "输入内容", "multiline"),
        FieldSpec("interval", "每个字符间隔（秒）", "float"),
        FieldSpec("paste", "使用剪贴板粘贴", "bool", hint="输入中文时建议启用"),
    ],
    "wait_text": [
        FieldSpec("text", "目标文字"),
        FieldSpec("match", "匹配方式", "choice", MATCHES),
        FieldSpec("timeout", "最长等待（秒）", "float"),
        FieldSpec("poll", "识别间隔（秒）", "float"),
        FieldSpec("region", "识别区域", hint="可留空；格式：x,y,宽,高"),
        FieldSpec("min_score", "最低文字置信度", "float"),
        FieldSpec("on_timeout", "超时后", "choice", TIMEOUTS),
    ],
    "click_text": [
        FieldSpec("text", "目标文字"),
        FieldSpec("match", "匹配方式", "choice", MATCHES),
        FieldSpec("timeout", "最长等待（秒）", "float"),
        FieldSpec("poll", "识别间隔（秒）", "float"),
        FieldSpec("region", "识别区域", hint="可留空；格式：x,y,宽,高"),
        FieldSpec("min_score", "最低文字置信度", "float"),
        FieldSpec("button", "鼠标按键", "choice", BUTTONS),
        FieldSpec("on_timeout", "超时后", "choice", TIMEOUTS),
    ],
    "wait_text_choice": [
        FieldSpec("continue_text", "正常继续文字", hint="识别到它时继续执行循环内的下一步"),
        FieldSpec("break_text", "提前结束文字", hint="识别到它时立即跳到循环结束之后"),
        FieldSpec("match", "匹配方式", "choice", MATCHES),
        FieldSpec("timeout", "最长等待（秒）", "float"),
        FieldSpec("poll", "识别间隔（秒）", "float"),
        FieldSpec("region", "识别区域", hint="可留空；格式：x,y,宽,高"),
        FieldSpec("min_score", "最低文字置信度", "float"),
        FieldSpec("on_timeout", "超时后", "choice", TIMEOUTS),
    ],
    "wait_image": [
        FieldSpec("path", "图片文件", "file"),
        FieldSpec("confidence", "最低相似度", "float"),
        FieldSpec("timeout", "最长等待（秒）", "float"),
        FieldSpec("poll", "识别间隔（秒）", "float"),
        FieldSpec("region", "识别区域", hint="可留空；格式：x,y,宽,高"),
        FieldSpec("on_timeout", "超时后", "choice", TIMEOUTS),
    ],
    "click_image": [
        FieldSpec("path", "图片文件", "file"),
        FieldSpec("confidence", "最低相似度", "float"),
        FieldSpec("timeout", "最长等待（秒）", "float"),
        FieldSpec("poll", "识别间隔（秒）", "float"),
        FieldSpec("region", "识别区域", hint="可留空；格式：x,y,宽,高"),
        FieldSpec("button", "鼠标按键", "choice", BUTTONS),
        FieldSpec("on_timeout", "超时后", "choice", TIMEOUTS),
    ],
    "loop_start": [FieldSpec("count", "循环次数", "int")],
    "loop_end": [],
    "comment": [FieldSpec("text", "说明内容", "multiline")],
}


class StepDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, step: Step | None = None, initial_action: str = "wait") -> None:
        super().__init__(parent)
        self.title("编辑步骤" if step else "添加步骤")
        self.geometry("600x650")
        self.minsize(540, 480)
        self.transient(parent)
        self.grab_set()
        self.result: Step | None = None
        self._original = Step.from_dict(step.to_dict()) if step else None
        selected_action = step.action if step else initial_action
        self.action_var = tk.StringVar(value=selected_action)
        self.enabled_var = tk.BooleanVar(value=step.enabled if step else True)
        self._widgets: dict[str, Any] = {}
        self._specs: dict[str, FieldSpec] = {}
        self._current_values = dict(step.params) if step else dict(DEFAULT_PARAMS[selected_action])

        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="操作类型").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=6)
        self.action_combo = ttk.Combobox(
            outer,
            state="readonly",
            values=[ACTION_LABELS[key] for key in ACTION_LABELS],
            width=28,
        )
        self.action_combo.set(ACTION_LABELS[selected_action])
        self.action_combo.grid(row=0, column=1, sticky="ew", pady=6)
        self.action_combo.bind("<<ComboboxSelected>>", self._on_action_change)
        ttk.Checkbutton(outer, text="启用这一步", variable=self.enabled_var).grid(
            row=1, column=1, sticky="w", pady=(0, 8)
        )

        self.form = ttk.LabelFrame(outer, text="参数", padding=12)
        self.form.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 12))
        self.help_var = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.help_var, foreground="#666666", wraplength=520).grid(
            row=3, column=0, columnspan=2, sticky="w"
        )

        buttons = ttk.Frame(outer)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="确定", command=self._submit).pack(side="right")

        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(2, weight=1)
        self._build_form(selected_action, self._current_values)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())

    @staticmethod
    def _action_from_label(label: str) -> str:
        for action, display in ACTION_LABELS.items():
            if display == label:
                return action
        return "wait"

    def _on_action_change(self, _event: tk.Event) -> None:
        action = self._action_from_label(self.action_combo.get())
        values = dict(DEFAULT_PARAMS[action])
        if self._original and action == self._original.action:
            values.update(self._original.params)
        self.action_var.set(action)
        self._build_form(action, values)

    def _build_form(self, action: str, values: dict[str, Any]) -> None:
        for child in self.form.winfo_children():
            child.destroy()
        self._widgets.clear()
        self._specs.clear()
        self.form.columnconfigure(1, weight=1)

        specs = FIELDS[action]
        if not specs:
            ttk.Label(self.form, text="这一步不需要额外参数。", foreground="#666666").grid(
                row=0, column=0, columnspan=3, sticky="w", pady=8
            )
        for row, spec in enumerate(specs):
            self._specs[spec.key] = spec
            ttk.Label(self.form, text=spec.label).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=6)
            value = values.get(spec.key, DEFAULT_PARAMS[action].get(spec.key, ""))
            if spec.kind == "multiline":
                widget = tk.Text(self.form, height=5, wrap="word")
                widget.insert("1.0", str(value))
                widget.grid(row=row, column=1, columnspan=2, sticky="nsew", pady=6)
            elif spec.kind == "bool":
                variable = tk.BooleanVar(value=bool(value))
                widget = ttk.Checkbutton(self.form, variable=variable)
                widget._flowclick_var = variable  # type: ignore[attr-defined]
                widget.grid(row=row, column=1, sticky="w", pady=6)
            elif spec.kind == "choice":
                variable = tk.StringVar(value=str(value))
                widget = ttk.Combobox(
                    self.form,
                    state="readonly",
                    values=[label for label, _raw in spec.choices],
                )
                label = next((label for label, raw in spec.choices if raw == str(value)), spec.choices[0][0])
                widget.set(label)
                widget.grid(row=row, column=1, columnspan=2, sticky="ew", pady=6)
            else:
                variable = tk.StringVar(value="" if value is None else str(value))
                widget = ttk.Entry(self.form, textvariable=variable)
                widget.grid(row=row, column=1, sticky="ew", pady=6)
                if spec.kind == "file":
                    ttk.Button(self.form, text="浏览…", command=lambda key=spec.key: self._browse_file(key)).grid(
                        row=row, column=2, padx=(8, 0), pady=6
                    )
            self._widgets[spec.key] = widget
            if spec.hint:
                widget.bind("<FocusIn>", lambda _event, text=spec.hint: self.help_var.set(text))

        if action == "click":
            extra_row = len(specs)
            ttk.Button(self.form, text="3 秒后读取鼠标位置", command=self._capture_point).grid(
                row=extra_row, column=1, sticky="w", pady=(12, 4)
            )
        self.help_var.set("鼠标移到字段上可查看填写提示。F10 可在流程运行时紧急停止。")

    def _browse_file(self, key: str) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="选择用于识别的小图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")],
        )
        if path:
            widget = self._widgets[key]
            widget.delete(0, "end")
            widget.insert(0, path)

    def _capture_point(self) -> None:
        self.help_var.set("请在 3 秒内把鼠标移动到目标位置…")
        self.withdraw()

        def finish() -> None:
            try:
                import pyautogui

                point = pyautogui.position()
                for key, value in (("x", point.x), ("y", point.y)):
                    widget = self._widgets[key]
                    widget.delete(0, "end")
                    widget.insert(0, str(value))
                self.help_var.set(f"已记录位置：({point.x}, {point.y})")
            except Exception as exc:
                messagebox.showerror("无法读取鼠标位置", str(exc), parent=self)
            finally:
                self.deiconify()
                self.lift()
                self.grab_set()

        self.after(3000, finish)

    def _raw_value(self, spec: FieldSpec) -> Any:
        widget = self._widgets[spec.key]
        if spec.kind == "multiline":
            return widget.get("1.0", "end-1c")
        if spec.kind == "bool":
            return bool(widget._flowclick_var.get())  # type: ignore[attr-defined]
        if spec.kind == "choice":
            label = widget.get()
            return next(raw for display, raw in spec.choices if display == label)
        return widget.get().strip()

    def _submit(self) -> None:
        action = self.action_var.get()
        params: dict[str, Any] = {}
        try:
            for key, spec in self._specs.items():
                raw = self._raw_value(spec)
                if spec.kind == "int":
                    params[key] = int(raw)
                elif spec.kind == "optional_int":
                    params[key] = None if raw == "" else int(raw)
                elif spec.kind == "float":
                    params[key] = float(raw)
                else:
                    params[key] = raw
        except (TypeError, ValueError):
            messagebox.showerror("参数有误", "请检查数字字段是否填写正确。", parent=self)
            return
        step_id = self._original.id if self._original else None
        self.result = Step(
            action=action,
            params=params,
            enabled=self.enabled_var.get(),
            **({"id": step_id} if step_id else {}),
        )
        self.destroy()


def edit_step(parent: tk.Misc, step: Step | None = None, initial_action: str = "wait") -> Step | None:
    dialog = StepDialog(parent, step=step, initial_action=initial_action)
    parent.wait_window(dialog)
    return dialog.result
