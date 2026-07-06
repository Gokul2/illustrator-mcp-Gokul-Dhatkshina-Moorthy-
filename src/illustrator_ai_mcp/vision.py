"""Smart screenshot capture of the Adobe Illustrator window.

On macOS: locates the front Illustrator window via System Events and
captures it with the `screencapture` tool. On Windows (experimental):
grabs the primary screen via Pillow's ImageGrab. Returns a downscaled
JPEG suitable for AI vision. Local-only; no network.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image

_APP_NAME = "Adobe Illustrator"

_BOUNDS_SCRIPT = f'''
tell application "{_APP_NAME}" to activate
delay 0.6
tell application "System Events" to tell process "{_APP_NAME}" to get {{position, size}} of front window
'''


def _window_bounds() -> tuple[int, int, int, int] | None:
    """Return (x, y, w, h) of the front Illustrator window, or None on failure."""
    try:
        proc = subprocess.run(
            ["osascript", "-e", _BOUNDS_SCRIPT],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    nums = re.findall(r"-?\d+", proc.stdout)
    if len(nums) < 4:
        return None
    x, y, w, h = (int(n) for n in nums[:4])
    if w <= 0 or h <= 0:
        return None
    return x, y, w, h


def _to_jpeg(img: Image.Image, max_width: int, quality: int) -> bytes:
    """Convert a PIL image to downscaled, optimized JPEG bytes."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    if img.width > max_width:
        new_h = max(1, round(img.height * max_width / img.width))
        img = img.resize((max_width, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _capture_windows(max_width: int, quality: int) -> bytes:
    """EXPERIMENTAL: capture the primary screen on Windows via ImageGrab."""
    try:
        from PIL import ImageGrab
    except ImportError as e:  # pragma: no cover — ImageGrab ships with Pillow on Windows
        raise RuntimeError(f"Screenshot unavailable: {e}") from e
    img = ImageGrab.grab()
    if img is None:
        raise RuntimeError("Screenshot failed — ImageGrab returned no image.")
    return _to_jpeg(img, max_width, quality)


def capture_illustrator(max_width: int = 1200, quality: int = 60) -> bytes:
    """Return JPEG bytes of the Adobe Illustrator window.

    Raises RuntimeError with a human-friendly message on failure.
    """
    if sys.platform == "win32":
        return _capture_windows(max_width, quality)
    bounds = _window_bounds()
    fd, path = tempfile.mkstemp(suffix=".png", prefix="illustrator_ai_")
    os.close(fd)
    try:
        cmd = ["screencapture", "-x"]
        if bounds is not None:
            x, y, w, h = bounds
            cmd += ["-R", f"{x},{y},{w},{h}"]
        cmd.append(path)
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("Screenshot capture timed out.") from e

        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise RuntimeError(
                "Screenshot failed — the capture produced no image. macOS may "
                "require Screen Recording permission for this app (System "
                "Settings > Privacy & Security > Screen Recording)."
            )

        with Image.open(path) as img:
            return _to_jpeg(img, max_width, quality)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
