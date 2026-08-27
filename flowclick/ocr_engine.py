from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any


class OCRUnavailable(RuntimeError):
    """Raised when optional OCR dependencies cannot be loaded."""


@dataclass(frozen=True)
class TextMatch:
    text: str
    score: float
    center_x: int
    center_y: int
    box: tuple[tuple[float, float], ...]


def _matches(candidate: str, target: str, mode: str) -> bool:
    left = "".join(candidate.casefold().split())
    right = "".join(target.casefold().split())
    if mode == "exact":
        return left == right
    return right in left


class OCREngine:
    """Lazy RapidOCR wrapper so normal click workflows stay lightweight."""

    def __init__(self) -> None:
        self._engine: Any | None = None
        self._lock = Lock()

    def _get_engine(self) -> Any:
        with self._lock:
            if self._engine is not None:
                return self._engine
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise OCRUnavailable(
                    "文字识别组件未安装。请运行 install.bat，或执行 pip install rapidocr onnxruntime。"
                ) from exc
            try:
                self._engine = RapidOCR()
            except Exception as exc:  # model/backend errors should be user readable
                raise OCRUnavailable(f"文字识别组件初始化失败：{exc}") from exc
            return self._engine

    def find_text(
        self,
        image: Any,
        target: str,
        *,
        match_mode: str = "contains",
        min_score: float = 0.5,
        offset: tuple[int, int] = (0, 0),
    ) -> TextMatch | None:
        try:
            import numpy as np
        except ImportError as exc:
            raise OCRUnavailable("缺少 numpy，无法执行文字识别。") from exc

        engine = self._get_engine()
        result = engine(np.asarray(image.convert("RGB")))
        boxes = getattr(result, "boxes", None)
        texts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        if boxes is None or texts is None or scores is None:
            return None

        found: list[TextMatch] = []
        offset_x, offset_y = offset
        for raw_box, raw_text, raw_score in zip(boxes, texts, scores):
            text = str(raw_text)
            score = float(raw_score)
            if score < min_score or not _matches(text, target, match_mode):
                continue
            points = tuple((float(point[0]), float(point[1])) for point in raw_box)
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            found.append(
                TextMatch(
                    text=text,
                    score=score,
                    center_x=round(sum(xs) / len(xs)) + offset_x,
                    center_y=round(sum(ys) / len(ys)) + offset_y,
                    box=points,
                )
            )
        return max(found, key=lambda item: item.score, default=None)
