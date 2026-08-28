from __future__ import annotations

import ctypes
import os
import shlex
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .models import Step, Workflow, action_label
from .ocr_engine import OCREngine, TextMatch
from .storage import resolve_asset_path
from .validator import build_loop_map, parse_region, validate_workflow


class WorkflowRuntimeError(RuntimeError):
    pass


class WatchdogRecovery(RuntimeError):
    def __init__(self, reason: str, config: dict[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.config = config


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
        self._ocr_lock = threading.Lock()
        self._workflow: Workflow | None = None
        self._lock = threading.Lock()
        self._watchdog_thread: threading.Thread | None = None
        self._watchdog_stop = threading.Event()
        self._recovery_requested = threading.Event()
        self._recovery_reason = ""
        self._recovery_config: dict[str, Any] = {}

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
            self._recovery_requested.clear()
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
        self._stop_watchdog()
        self._resume.set()
        if self.running:
            self.on_status("正在停止…")

    def _wait_if_paused(self) -> None:
        while not self._resume.wait(0.1):
            if self._stop.is_set():
                raise InterruptedError
        if self._stop.is_set():
            raise InterruptedError
        if self._recovery_requested.is_set():
            reason = self._recovery_reason
            config = dict(self._recovery_config)
            self._recovery_requested.clear()
            raise WatchdogRecovery(reason, config)

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
            restart_count = 0
            while True:
                try:
                    self._run_once()
                    break
                except WatchdogRecovery as recovery:
                    restart_count += 1
                    self._recover(recovery, restart_count)
            self.on_status("流程执行完成")
        except InterruptedError:
            self.on_status("流程已停止")
        except Exception as exc:
            error = str(exc)
            self.on_status(f"运行失败：{error}")
        finally:
            self._stop_watchdog()
            self.on_finished(error)

    def _run_once(self) -> None:
        assert self._workflow is not None
        workflow = self._workflow
        loop_map = build_loop_map(workflow.steps)
        labels = {
            str(step.params.get("name", "")).strip(): index
            for index, step in enumerate(workflow.steps)
            if step.enabled and step.action == "label"
        }
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
            if isinstance(control, str) and control.startswith("jump:"):
                target_name = control.removeprefix("jump:")
                if target_name not in labels:
                    raise WorkflowRuntimeError(f"找不到流程标签“{target_name}”")
                target = labels[target_name]
                for start in list(remaining):
                    end = loop_map.get(start, -1)
                    if not (start < target < end):
                        remaining.pop(start, None)
                pc = target
                self.on_status(f"识别到页面状态，已跳到标签“{target_name}”")
                continue
            pc += 1

    def _execute(self, step: Step, workflow: Workflow) -> str | None:
        p = step.params
        action = step.action
        gui = self._pyautogui() if action not in {"wait", "comment", "label", "watchdog"} else None

        if action == "wait":
            self._sleep(float(p.get("seconds", 1)))
        elif action == "comment":
            return
        elif action == "label":
            return
        elif action == "watchdog":
            self._start_watchdog(p)
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
        elif action == "text_router":
            return self._route_text(p)
        elif action in {"wait_image", "click_image"}:
            box = self._wait_for_image(p, workflow)
            if box is not None and action == "click_image":
                assert gui is not None
                point = gui.center(box)
                gui.click(point.x, point.y, button=str(p.get("button", "left")))
        else:
            raise WorkflowRuntimeError(f"不支持的操作：{action}")
        return None

    def _route_text(self, params: dict[str, Any]) -> str | None:
        routes: list[tuple[str, str]] = []
        for raw_line in str(params.get("routes", "")).splitlines():
            line = raw_line.strip()
            if not line or "=>" not in line:
                continue
            text, target = (part.strip() for part in line.split("=>", 1))
            routes.append((text, target))
        gui = self._pyautogui()
        region = parse_region(params.get("region", ""))
        offset = (region[0], region[1]) if region else (0, 0)
        deadline = time.monotonic() + float(params.get("timeout", 1.5))
        targets = [text for text, _target in routes]
        while time.monotonic() <= deadline:
            self._wait_if_paused()
            screenshot = gui.screenshot(region=region)
            with self._ocr_lock:
                matches = self._ocr.find_texts(
                    screenshot,
                    targets,
                    match_mode=str(params.get("match", "contains")),
                    min_score=float(params.get("min_score", 0.45)),
                    offset=offset,
                )
            for text, target in routes:
                if text in matches:
                    return f"jump:{target}"
            self._sleep(float(params.get("poll", 0.3)))
        return None

    def _start_watchdog(self, params: dict[str, Any]) -> None:
        self._stop_watchdog()
        self._watchdog_stop = threading.Event()
        stop_event = self._watchdog_stop
        config = dict(params)
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_worker,
            args=(config, stop_event),
            daemon=True,
            name="flowclick-watchdog",
        )
        self._watchdog_thread.start()
        self.on_status(f"托管看门狗已启动：卡住 {config.get('stuck_seconds', 60)} 秒自动恢复")

    def _stop_watchdog(self) -> None:
        self._watchdog_stop.set()
        thread = self._watchdog_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._watchdog_thread = None

    def _watchdog_worker(self, config: dict[str, Any], stop_event: threading.Event) -> None:
        try:
            from PIL import ImageChops, ImageStat

            gui = self._pyautogui()
            region = parse_region(config.get("region", ""))
            interval = max(0.5, float(config.get("sample_interval", 3.0)))
            stuck_seconds = float(config.get("stuck_seconds", 60.0))
            threshold = float(config.get("change_threshold", 2.0))
            raw_texts = str(config.get("watch_texts", ""))
            watch_texts = [
                item.strip()
                for item in raw_texts.replace("，", ",").replace("\n", ",").split(",")
                if item.strip()
            ]
            previous = None
            unchanged_since: float | None = None
            same_text = ""
            same_text_since: float | None = None

            while not stop_event.wait(interval):
                if self._stop.is_set():
                    return
                if not self._resume.is_set():
                    previous = None
                    unchanged_since = None
                    same_text = ""
                    same_text_since = None
                    continue
                screenshot = gui.screenshot(region=region)
                small = screenshot.convert("L").resize((96, 54))
                now = time.monotonic()
                if previous is not None:
                    difference = ImageStat.Stat(ImageChops.difference(previous, small)).mean[0]
                    if difference <= threshold:
                        unchanged_since = unchanged_since or now
                    else:
                        unchanged_since = None
                previous = small

                detected = ""
                if watch_texts:
                    with self._ocr_lock:
                        matches = self._ocr.find_texts(
                            screenshot,
                            watch_texts,
                            match_mode="contains",
                            min_score=0.4,
                            offset=(region[0], region[1]) if region else (0, 0),
                        )
                    detected = next((text for text in watch_texts if text in matches), "")
                if detected and detected == same_text:
                    same_text_since = same_text_since or now
                elif detected:
                    same_text = detected
                    same_text_since = now
                else:
                    same_text = ""
                    same_text_since = None

                screen_stuck = unchanged_since is not None and now - unchanged_since >= stuck_seconds
                text_stuck = same_text_since is not None and now - same_text_since >= stuck_seconds
                if screen_stuck or text_stuck:
                    reason = (
                        f"页面文字“{same_text}”持续 {int(now - same_text_since)} 秒"
                        if text_stuck and same_text_since is not None
                        else f"画面持续 {int(now - unchanged_since)} 秒无明显变化"
                    )
                    self._record_recovery(reason, screenshot)
                    self._recovery_reason = reason
                    self._recovery_config = config
                    self._recovery_requested.set()
                    return
        except Exception as exc:
            self.on_status(f"托管看门狗异常：{exc}")

    def _recover(self, recovery: WatchdogRecovery, restart_count: int) -> None:
        self._stop_watchdog()
        config = recovery.config
        maximum = int(config.get("max_restarts", 10))
        if maximum > 0 and restart_count > maximum:
            raise WorkflowRuntimeError(f"自动恢复已达到上限 {maximum} 次，流程停止")
        self.on_status(f"检测到卡住：{recovery.reason}；正在第 {restart_count} 次自动恢复")
        mode = str(config.get("recovery", "restart_workflow"))
        if mode == "restart_program":
            executable = Path(str(config.get("executable", ""))).expanduser()
            if not executable.exists():
                raise WorkflowRuntimeError(f"找不到要重启的程序：{executable}")
            process_name = str(config.get("process_name", "")).strip() or executable.name
            subprocess.run(
                ["taskkill", "/F", "/T", "/IM", process_name],
                capture_output=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._recovery_sleep(2.0)
            arguments = shlex.split(str(config.get("arguments", "")), posix=False)
            subprocess.Popen([str(executable), *arguments], cwd=str(executable.parent))
        self._recovery_sleep(float(config.get("restart_wait", 30.0)))

    def _recovery_sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            if self._stop.wait(min(0.2, max(0.0, deadline - time.monotonic()))):
                raise InterruptedError

    @staticmethod
    def _record_recovery(reason: str, screenshot: Any) -> None:
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FlowClickStudio" / "recovery"
        base.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        screenshot.save(base / f"stuck-{stamp}.png")
        with (base / "recovery.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat(timespec='seconds')}  {reason}\n")

    def _wait_for_text(self, params: dict[str, Any]) -> TextMatch | None:
        gui = self._pyautogui()
        region = parse_region(params.get("region", ""))
        offset = (region[0], region[1]) if region else (0, 0)
        deadline = time.monotonic() + float(params.get("timeout", 10))
        target = str(params.get("text", ""))
        while time.monotonic() <= deadline:
            self._wait_if_paused()
            screenshot = gui.screenshot(region=region)
            with self._ocr_lock:
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
            with self._ocr_lock:
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
