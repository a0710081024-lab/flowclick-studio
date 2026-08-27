from __future__ import annotations

import copy
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .automation import WorkflowRunner
from .dialogs import edit_step
from .models import ACTION_LABELS, Step, Workflow, action_label, step_summary
from .storage import load_workflow, save_workflow
from .validator import validate_workflow


class FlowClickApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("FlowClick Studio · 可视化自动化")
        self.root.geometry("1120x720")
        self.root.minsize(900, 600)
        self.workflow = Workflow()
        self.current_path: Path | None = None
        self.dirty = False
        self.status_var = tk.StringVar(value="就绪")
        self.name_var = tk.StringVar(value=self.workflow.name)
        self.action_choice = tk.StringVar(value=ACTION_LABELS["click"])
        self._hotkeys_registered = False

        self.runner = WorkflowRunner(
            on_status=lambda message: self.root.after(0, self.status_var.set, message),
            on_step=lambda index: self.root.after(0, self._highlight_step, index),
            on_finished=lambda error: self.root.after(0, self._run_finished, error),
        )

        self._configure_style()
        self._build_menu()
        self._build_layout()
        self._bind_events()
        self._register_global_hotkeys()
        self._refresh_tree()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        available = style.theme_names()
        if "vista" in available:
            style.theme_use("vista")
        style.configure("Treeview", rowheight=30, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Hint.TLabel", foreground="#5f6670")
        style.configure("Run.TButton", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="新建流程   Ctrl+N", command=self.new_workflow)
        file_menu.add_command(label="打开流程…   Ctrl+O", command=self.open_workflow)
        file_menu.add_separator()
        file_menu.add_command(label="保存   Ctrl+S", command=self.save)
        file_menu.add_command(label="另存为…", command=self.save_as)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        menu.add_cascade(label="文件", menu=file_menu)

        run_menu = tk.Menu(menu, tearoff=False)
        run_menu.add_command(label="检查流程", command=self.validate)
        run_menu.add_separator()
        run_menu.add_command(label="开始   F8", command=self.start)
        run_menu.add_command(label="暂停/继续   F9", command=self.pause)
        run_menu.add_command(label="停止   F10", command=self.stop)
        menu.add_cascade(label="运行", menu=run_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="快捷键说明", command=self._show_shortcuts)
        help_menu.add_command(label="关于", command=self._show_about)
        menu.add_cascade(label="帮助", menu=help_menu)
        self.root.config(menu=menu)

    def _build_layout(self) -> None:
        shell = ttk.Frame(self.root, padding=16)
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell)
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="FlowClick Studio", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="流程名称：").pack(side="left", padx=(28, 6))
        name_entry = ttk.Entry(header, textvariable=self.name_var, width=30)
        name_entry.pack(side="left")
        name_entry.bind("<KeyRelease>", lambda _event: self._mark_dirty())
        ttk.Label(
            header,
            text="鼠标移到左上角或按 F10 可紧急停止",
            style="Hint.TLabel",
        ).pack(side="right")

        body = ttk.Panedwindow(shell, orient="horizontal")
        body.pack(fill="both", expand=True)
        main = ttk.Frame(body)
        side = ttk.Frame(body, padding=(14, 0, 0, 0))
        body.add(main, weight=5)
        body.add(side, weight=2)

        addbar = ttk.Frame(main)
        addbar.pack(fill="x", pady=(0, 8))
        ttk.Label(addbar, text="新增操作：").pack(side="left")
        action_combo = ttk.Combobox(
            addbar,
            textvariable=self.action_choice,
            state="readonly",
            values=list(ACTION_LABELS.values()),
            width=20,
        )
        action_combo.pack(side="left", padx=(0, 8))
        ttk.Button(addbar, text="＋ 添加步骤", command=self.add_step).pack(side="left")
        ttk.Button(addbar, text="检查流程", command=self.validate).pack(side="right")

        tree_frame = ttk.Frame(main)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("number", "enabled", "action", "detail"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("number", text="序号")
        self.tree.heading("enabled", text="状态")
        self.tree.heading("action", text="操作")
        self.tree.heading("detail", text="内容")
        self.tree.column("number", width=58, anchor="center", stretch=False)
        self.tree.column("enabled", width=72, anchor="center", stretch=False)
        self.tree.column("action", width=155, anchor="w", stretch=False)
        self.tree.column("detail", width=520, anchor="w")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("disabled", foreground="#999999")
        self.tree.tag_configure("current", background="#dcecff")

        toolbar = ttk.Frame(main)
        toolbar.pack(fill="x", pady=(9, 0))
        for text, command in (
            ("编辑", self.edit_selected),
            ("复制", self.duplicate_selected),
            ("启用/禁用", self.toggle_selected),
            ("删除", self.delete_selected),
            ("上移", lambda: self.move_selected(-1)),
            ("下移", lambda: self.move_selected(1)),
        ):
            ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=(0, 6))

        ttk.Label(side, text="运行控制", font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        ttk.Button(side, text="▶ 开始（F8）", style="Run.TButton", command=self.start).pack(
            fill="x", pady=(12, 6), ipady=5
        )
        ttk.Button(side, text="⏸ 暂停/继续（F9）", command=self.pause).pack(fill="x", pady=6, ipady=3)
        ttk.Button(side, text="■ 停止（F10）", command=self.stop).pack(fill="x", pady=6, ipady=3)

        ttk.Separator(side).pack(fill="x", pady=18)
        ttk.Label(side, text="编辑提示", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        tips = (
            "• 双击步骤可编辑\n"
            "• 点击步骤后可上下移动\n"
            "• 坐标点击支持 3 秒录制\n"
            "• 文字识别支持中英文\n"
            "• 文字结果可提前跳出循环\n"
            "• 图片步骤请选择小范围特征图\n"
            "• 循环开始和结束必须成对"
        )
        ttk.Label(side, text=tips, justify="left", style="Hint.TLabel", wraplength=250).pack(
            anchor="w", pady=(8, 0)
        )

        ttk.Separator(shell).pack(fill="x", pady=(12, 8))
        footer = ttk.Frame(shell)
        footer.pack(fill="x")
        ttk.Label(footer, text="状态：").pack(side="left")
        ttk.Label(footer, textvariable=self.status_var).pack(side="left")
        self.path_var = tk.StringVar(value="尚未保存")
        ttk.Label(footer, textvariable=self.path_var, style="Hint.TLabel").pack(side="right")

    def _bind_events(self) -> None:
        self.tree.bind("<Double-1>", lambda _event: self.edit_selected())
        self.root.bind("<Control-n>", lambda _event: self.new_workflow())
        self.root.bind("<Control-o>", lambda _event: self.open_workflow())
        self.root.bind("<Control-s>", lambda _event: self.save())
        self.root.bind("<Delete>", lambda _event: self.delete_selected())

    def _register_global_hotkeys(self) -> None:
        try:
            import keyboard

            keyboard.add_hotkey("f8", lambda: self.root.after(0, self.start))
            keyboard.add_hotkey("f9", lambda: self.root.after(0, self.pause))
            keyboard.add_hotkey("f10", lambda: self.root.after(0, self.stop))
            self._hotkeys_registered = True
        except Exception as exc:
            self.status_var.set(f"全局快捷键未启用：{exc}")

    def _selected_index(self) -> int | None:
        selected = self.tree.selection()
        if not selected:
            return None
        try:
            return int(selected[0])
        except ValueError:
            return None

    def _refresh_tree(self, select_index: int | None = None) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, step in enumerate(self.workflow.steps):
            tags = () if step.enabled else ("disabled",)
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(index + 1, "启用" if step.enabled else "禁用", action_label(step.action), step_summary(step)),
                tags=tags,
            )
        if select_index is not None and 0 <= select_index < len(self.workflow.steps):
            self.tree.selection_set(str(select_index))
            self.tree.focus(str(select_index))
            self.tree.see(str(select_index))

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._update_title()

    def _update_title(self) -> None:
        suffix = " *" if self.dirty else ""
        self.root.title(f"FlowClick Studio · {self.name_var.get() or '未命名流程'}{suffix}")

    def add_step(self) -> None:
        action = next(
            (key for key, label in ACTION_LABELS.items() if label == self.action_choice.get()),
            "click",
        )
        step = edit_step(self.root, initial_action=action)
        if step is None:
            return
        selected = self._selected_index()
        index = len(self.workflow.steps) if selected is None else selected + 1
        self.workflow.steps.insert(index, step)
        self._mark_dirty()
        self._refresh_tree(index)

    def edit_selected(self) -> None:
        index = self._selected_index()
        if index is None:
            messagebox.showinfo("请选择步骤", "请先在列表中选择一个步骤。", parent=self.root)
            return
        edited = edit_step(self.root, self.workflow.steps[index])
        if edited is not None:
            self.workflow.steps[index] = edited
            self._mark_dirty()
            self._refresh_tree(index)

    def duplicate_selected(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        duplicate = copy.deepcopy(self.workflow.steps[index])
        duplicate.id = Step.create(duplicate.action).id
        self.workflow.steps.insert(index + 1, duplicate)
        self._mark_dirty()
        self._refresh_tree(index + 1)

    def toggle_selected(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        self.workflow.steps[index].enabled = not self.workflow.steps[index].enabled
        self._mark_dirty()
        self._refresh_tree(index)

    def delete_selected(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        del self.workflow.steps[index]
        self._mark_dirty()
        self._refresh_tree(min(index, len(self.workflow.steps) - 1))

    def move_selected(self, delta: int) -> None:
        index = self._selected_index()
        if index is None:
            return
        target = index + delta
        if not 0 <= target < len(self.workflow.steps):
            return
        self.workflow.steps[index], self.workflow.steps[target] = (
            self.workflow.steps[target],
            self.workflow.steps[index],
        )
        self._mark_dirty()
        self._refresh_tree(target)

    def validate(self) -> bool:
        self.workflow.name = self.name_var.get().strip() or "未命名流程"
        issues = validate_workflow(self.workflow)
        if issues:
            messagebox.showerror(
                "流程检查未通过",
                "\n".join(issue.display() for issue in issues),
                parent=self.root,
            )
            return False
        messagebox.showinfo("检查完成", "流程结构和参数检查通过。", parent=self.root)
        return True

    def start(self) -> None:
        if self.runner.running:
            return
        self.workflow.name = self.name_var.get().strip() or "未命名流程"
        issues = validate_workflow(self.workflow)
        if issues:
            messagebox.showerror(
                "无法开始",
                "\n".join(issue.display() for issue in issues),
                parent=self.root,
            )
            return
        try:
            self.runner.start(self.workflow)
        except Exception as exc:
            messagebox.showerror("无法开始", str(exc), parent=self.root)

    def pause(self) -> None:
        self.runner.toggle_pause()

    def stop(self) -> None:
        self.runner.stop()

    def _highlight_step(self, index: int) -> None:
        for item in self.tree.get_children():
            tags = list(self.tree.item(item, "tags"))
            if "current" in tags:
                tags.remove("current")
            if int(item) == index:
                tags.append("current")
            self.tree.item(item, tags=tuple(tags))
        if self.tree.exists(str(index)):
            self.tree.see(str(index))

    def _run_finished(self, error: str | None) -> None:
        for item in self.tree.get_children():
            tags = tuple(tag for tag in self.tree.item(item, "tags") if tag != "current")
            self.tree.item(item, tags=tags)
        if error:
            messagebox.showerror("流程运行失败", error, parent=self.root)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("保存修改", "当前流程有未保存修改，是否先保存？", parent=self.root)
        if answer is None:
            return False
        if answer:
            return self.save()
        return True

    def new_workflow(self) -> None:
        if self.runner.running:
            messagebox.showwarning("流程运行中", "请先停止当前流程。", parent=self.root)
            return
        if not self._confirm_discard():
            return
        self.workflow = Workflow()
        self.current_path = None
        self.name_var.set(self.workflow.name)
        self.path_var.set("尚未保存")
        self.dirty = False
        self._update_title()
        self._refresh_tree()

    def open_workflow(self) -> None:
        if self.runner.running:
            messagebox.showwarning("流程运行中", "请先停止当前流程。", parent=self.root)
            return
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            title="打开 FlowClick 流程",
            filetypes=[("FlowClick 流程", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            workflow = load_workflow(path)
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc), parent=self.root)
            return
        self.workflow = workflow
        self.current_path = Path(path)
        self.name_var.set(workflow.name)
        self.path_var.set(str(self.current_path))
        self.dirty = False
        self._update_title()
        self._refresh_tree()

    def save(self) -> bool:
        if self.current_path is None:
            return self.save_as()
        return self._save_to(self.current_path)

    def save_as(self) -> bool:
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="保存 FlowClick 流程",
            defaultextension=".json",
            filetypes=[("FlowClick 流程", "*.json")],
            initialfile=f"{self.name_var.get().strip() or 'workflow'}.json",
        )
        if not path:
            return False
        return self._save_to(Path(path))

    def _save_to(self, path: Path) -> bool:
        self.workflow.name = self.name_var.get().strip() or "未命名流程"
        try:
            save_workflow(self.workflow, path)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return False
        self.current_path = path
        self.path_var.set(str(path))
        self.dirty = False
        self._update_title()
        self.status_var.set("流程已保存")
        return True

    def _show_shortcuts(self) -> None:
        messagebox.showinfo(
            "快捷键",
            "F8：开始流程\nF9：暂停或继续\nF10：紧急停止\n\n"
            "Ctrl+N：新建\nCtrl+O：打开\nCtrl+S：保存\nDelete：删除选中步骤\n\n"
            "PyAutoGUI 安全保护：把鼠标快速移到屏幕左上角也会终止操作。",
            parent=self.root,
        )

    def _show_about(self) -> None:
        messagebox.showinfo(
            "关于 FlowClick Studio",
            "FlowClick Studio 0.2.0\n\n"
            "本地可视化操作流程工具。普通坐标点击不依赖网络；文字识别首次加载可能需要数秒。",
            parent=self.root,
        )

    def _on_close(self) -> None:
        if self.runner.running:
            if not messagebox.askyesno("流程仍在运行", "要停止流程并退出吗？", parent=self.root):
                return
            self.runner.stop()
        if not self._confirm_discard():
            return
        if self._hotkeys_registered:
            try:
                import keyboard

                keyboard.unhook_all_hotkeys()
            except Exception:
                pass
        self.root.destroy()
