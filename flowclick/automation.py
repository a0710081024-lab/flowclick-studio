from __future__ import annotations

import ctypes
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .models import Step, Workflow, action_label
from .ocr_engine import OCREngine, TextMatch
from .storage import resolve_asset_path
from .validator import build_loop_map, parse_region, validate_workflow


class WorkflowRuntimeError(RuntimeError):
    pass


def enable_dpi_awareness() -> None:
    """Keep recorded coordinates aligned with physical pixels on Windows."""
    if not hasattr(ctypes, "windll"):
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class WorkflowRunner:
    def __init__(
        self,
        *,
        on_status: Callable[[str], None] | None = None,
        on_step: Callable[[int], None] | None = None,
        on_finished: Callable[[str | None], None] | None = None,
    ) -> None:
        self.on_status = on_status or (lambda _message: None)
        self.on_step = on_step or (lambda _index: None)
        self.on_finished = on_finished or (lambda _error: None)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._ocr = OCREngine()
        self._workflow: Workflow | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def paused(self) -> bool:
        return self.running and not self._resume.is_set()

    def start(self, workflow: Workflow) -> None:
        issues = validate_workflow(workflow)
        if issues:
            raise ValueError("\n".join(issue.display() for issue in issues))
        with self._lock:
            if self.running:
                raise RuntimeError("已有流程正在运行")
            self._workflow = workflow
            self._stop.clear()
            self._resume.set()
            self._thread = threading.Thread(target=self._run, daemon=True, name="flowclick-runner")
            self._thread.start()

    def toggle_pause(self) -> bool:
        if not self.running:
            return False
        if self._resume.is_set():
            self._resume.clear()
            self.on_status("已暂停（F9 继续）")
            return True
        self._resume.set()
        self.on_status("继续运行")
        return False

    def stop(self) -> None:
        self._stop.set()
        self._resume.set()
        if self.running:
            self.on_status("正在停止…")

    def _wait_if_paused(self) -> None:
        while not self._resume.wait(0.1):
            if self._stop.is_set():
                raise InterruptedError
        if self._stop.is_set():
            raise InterruptedError

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            self._wait_if_paused()
            if self._stop.wait(min(0.05, max(0.0, end - time.monotonic()))):
                raise InterruptedError

    @staticmethod
    def _pyautogui() -> Any:
        try:
            import pyautogui
        except ImportError as exc:
            raise WorkflowRuntimeError("缺少 pyautogui，请先运行 install.bat。") from exc
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.03
        return pyautogui

    def _run(self) -> None:
        error: str | None = None
        try:
            assert self._workflow is not None
            workflow = self._workflow
            loop_map = build_loop_map(workflow.steps)
            remaining: dict[int, int] = {}
            pc = 0
            self.on_status("流程运行中（F9 暂停，F10 停止）")
            while pc < len(workflow.steps):
                self._wait_if_paused()
                step = workflow.steps[pc]
                if not step.enabled:
                    pc += 1
                    continue
                self.on_step(pc)
                self.on_status(f"第 {pc + 1} 步：{action_label(step.action)}")

                if step.action == "loop_start":
                    remaining.setdefault(pc, int(step.params.get("count", 1)))
                    pc += 1
                    continue
                if step.action == "loop_end":
                    start = loop_map[pc]
                    remaining[start] -= 1
                    if remaining[start] > 0:
                        pc = start + 1
                    else:
                        remaining.pop(start, None)
                        pc += 1
                    continue

                control = self._execute(step, workflow)
                if control == "break_loop":
                    active_starts = [
                        start
                        for start in remaining
                        if start < pc < loop_map.get(start, -1)
                    ]
                    if not active_starts:
                        raise WorkflowRuntimeError("“等待文字结果”必须放在循环开始和结束之间")
                    start = max(active_starts)
                    remaining.pop(start, None)
                    pc = loop_map[start] + 1
                    self.on_status("识别到提前结束文字，已跳出循环")
                    continue
                pc += 1
            self.on_status("流程执行完成")
        except InterruptedError:
            self.on_status("流程已停止")
        except Exception as exc:
            error = str(exc)
            self.on_status(f"运行失败：{error}")
        finally:
            self.on_finished(error)

    def _execute(self, step: Step, workflow: Workflow) -> str | None:
        p = step.params
        action = step.action
        gui = self._pyautogui() if action not in {"wait", "comment"} else None

        if action == "wait":
            self._sleep(float(p.get("seconds", 1)))
        elif action == "comment":
            return
        elif action == "click":
            assert gui is not None
            gui.click(
                x=int(p["x"]),
                y=int(p["y"]),
                clicks=int(p.get("clicks", 1)),
                interval=float(p.get("interval", 0.1)),
                button=str(p.get("button", "left")),
            )
        elif action == "scroll":
            assert gui is not None
            x, y = p.get("x"), p.get("y")
            if x not in (None, "") and y not in (None, ""):
                gui.moveTo(int(x), int(y))
            gui.scroll(int(p.get("amount", -3)))
        elif action == "key_press":
            assert gui is not None
            gui.press(
                str(p.get("key", "enter")),
                presses=int(p.get("presses", 1)),
                interval=float(p.get("interval", 0.1)),
            )
        elif action == "hotkey":
            assert gui is not None
            keys = [key.strip() for key in str(p.get("keys", "")).split(",") if key.strip()]
            gui.hotkey(*keys)
        elif action == "type_text":
            assert gui is not None
            text = str(p.get("text", ""))
            if bool(p.get("paste", False)):
                try:
                    import pyperclip
                except ImportError as exc:
                    raise WorkflowRuntimeError("粘贴输入需要 pyperclip，请重新运行 install.bat。") from exc
                pyperclip.copy(text)
                gui.hotkey("ctrl", "v")
            else:
                gui.write(text, interval=float(p.get("interval", 0.03)))
        elif action in {"wait_text", "click_text"}:
            match = self._wait_for_text(p)
            if match is not None and action == "click_text":
                assert gui is not None
                gui.click(match.center_x, match.center_y, button=str(p.get("button", "left")))
        elif action == "wait_text_choice":
            return self._wait_for_text_choice(p)
        elif action in {"wait_image", "click_image"}:
            box = self._wait_for_image(p, workflow)
            if box is not None and action == "click_image":
                assert gui is not None
                point = gui.center(box)
                gui.click(point.x, point.y, button=str(p.get("button", "left")))
        else:
            raise WorkflowRuntimeError(f"不支持的操作：{action}")
        return None

    def _wait_for_text(self, params: dict[str, Any]) -> TextMatch | None:
        gui = self._pyautogui()
        region = parse_region(params.get("region", ""))
        offset = (region[0], region[1]) if region else (0, 0)
        deadline = time.monotonic() + float(params.get("timeout", 10))
        target = str(params.get("text", ""))
        while time.monotonic() <= deadline:
            self._wait_if_paused()
            screenshot = gui.screenshot(region=region)
            match = self._ocr.find_text(
                screenshot,
                target,
                match_mode=str(params.get("match", "contains")),
                min_score=float(params.get("min_score", 0.5)),
                offset=offset,
            )
            if match is not None:
                return match
            self._sleep(float(params.get("poll", 0.7)))
        return self._timeout_result(params, f"未在规定时间内识别到文字“{target}”")

    def _wait_for_image(self, params: dict[str, Any], workflow: Workflow) -> Any | None:
        gui = self._pyautogui()
        region = parse_region(params.get("region", ""))
        image_path = resolve_asset_path(workflow, str(params.get("path", "")))
        if not image_path.exists():
            raise WorkflowRuntimeError(f"找不到识别图片：{image_path}")
        deadline = time.monotonic() + float(params.get("timeout", 10))
        while time.monotonic() <= deadline:
            self._wait_if_paused()
            try:
                box = gui.locateOnScreen(
                    str(image_path),
                    confidence=float(params.get("confidence", 0.85)),
                    region=region,
                )
            except Exception as exc:
                if "confidence" in str(exc).casefold() or "opencv" in str(exc).casefold():
                    raise WorkflowRuntimeError("图片相似度识别需要 OpenCV，请重新运行 install.bat。") from exc
                box = None
            if box is not None:
                return box
            self._sleep(float(params.get("poll", 0.5)))
        return self._timeout_result(params, f"未在规定时间内识别到图片“{Path(image_path).name}”")

    def _wait_for_text_choice(self, params: dict[str, Any]) -> str | None:
        gui = self._pyautogui()
        region = parse_region(params.get("region", ""))
        offset = (region[0], region[1]) if region else (0, 0)
        deadline = time.monotonic() + float(params.get("timeout", 60))
        continue_text = str(params.get("continue_text", ""))
        break_text = str(params.get("break_text", ""))
        targets = [break_text, continue_text]
        while time.monotonic() <= deadline:
            self._wait_if_paused()
            screenshot = gui.screenshot(region=region)
            matches = self._ocr.find_texts(
                screenshot,
                targets,
                match_mode=str(params.get("match", "contains")),
                min_score=float(params.get("min_score", 0.5)),
                offset=offset,
            )
            # 两个结果同时出现时，优先保证“提前结束”不被错过。
            if break_text in matches:
                return "break_loop"
            if continue_text in matches:
                return None
            self._sleep(float(params.get("poll", 0.7)))
        return self._timeout_result(
            params,
            f"未在规定时间内识别到“{continue_text}”或“{break_text}”",
        )

    @staticmethod
    def _timeout_result(params: dict[str, Any], message: str) -> None:
        if params.get("on_timeout", "stop") == "skip":
            return None
        raise WorkflowRuntimeError(message)
