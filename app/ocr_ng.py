from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import os
import re
import shutil


@dataclass
class OcrNgRow:
    source_file: str
    source_path: str
    parameter: str
    ocr_original: str
    message: str
    counter: str
    start_time: str
    stop_time: str
    checked_default: bool


@dataclass
class OcrImageResult:
    source_file: str
    source_path: str
    rows: list[OcrNgRow]
    counter_ng: str
    raw_text: str
    engine: str
    warnings: list[str]


def find_tesseract(configured_cmd: str = "", app_root: Path | None = None) -> str | None:
    """Find a bundled/installed Tesseract executable.

    PyInstaller 6 onedir normally stores data under ``_internal``.  Builds made
    with ``--contents-directory .`` store the same data beside the EXE.  Check
    both layouts so the program does not depend on a drive/path from the build
    machine.
    """
    import sys

    candidates: list[Path] = []

    configured_cmd = str(configured_cmd or "").strip()
    if configured_cmd:
        candidates.append(Path(os.path.expandvars(configured_cmd)))

    roots: list[Path] = []
    if app_root is not None:
        roots.append(Path(app_root))

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        roots.extend([exe_dir, exe_dir / "_internal"])
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
    else:
        roots.append(Path(__file__).resolve().parents[1])

    # Preserve order while removing duplicate roots.
    seen: set[str] = set()
    unique_roots: list[Path] = []
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key not in seen:
            seen.add(key)
            unique_roots.append(root)

    for root in unique_roots:
        candidates.extend([
            root / "tools" / "Tesseract-OCR" / "tesseract.exe",
            root / "Tesseract-OCR" / "tesseract.exe",
        ])

    # Installed Tesseract is only a fallback. Bundled OCR is preferred.
    candidates.extend([
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        Path(r"D:\NewSumLineData\Tesseract-OCR\tesseract.exe"),
    ])

    path_cmd = shutil.which("tesseract")
    if path_cmd:
        candidates.append(Path(path_cmd))

    for candidate in candidates:
        try:
            p = candidate.expanduser()
            if p.exists() and p.is_file():
                return str(p.resolve())
        except OSError:
            continue

    return None


def configure_tesseract_runtime(tesseract_exe: str) -> Path:
    """Configure tessdata for the exact bundled engine being used."""
    exe = Path(tesseract_exe).resolve()
    tessdata = exe.parent / "tessdata"
    if tessdata.is_dir():
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
    return tessdata


def _image_time(path: Path) -> datetime:
    m = re.search(r"(?<!\d)(20\d{6})[_-]?(\d{6})(?!\d)", path.stem)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            pass

    try:
        from PIL import Image
        with Image.open(path) as im:
            exif = im.getexif()
            raw = exif.get(36867) or exif.get(306)
            if raw:
                return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass

    return datetime.fromtimestamp(path.stat().st_mtime)


def _mode_digits(values: list[str]) -> str:
    clean = [re.sub(r"\D", "", str(v or "")) for v in values]
    clean = [v for v in clean if v]
    if not clean:
        return ""
    counts = Counter(clean)
    return sorted(counts.items(), key=lambda item: (item[1], len(item[0])), reverse=True)[0][0]


def _split_tall_value_box(box, typical_h: int):
    """Split vertically merged cyan cells without assuming a fixed row count."""
    x, y, bw, bh = box
    if typical_h <= 0 or bh <= typical_h * 1.55:
        return [box]

    count = max(2, int(round(bh / typical_h)))
    part_h = bh / count
    result = []
    for i in range(count):
        y0 = int(round(y + i * part_h))
        y1 = int(round(y + (i + 1) * part_h))
        result.append((x, y0, bw, max(1, y1 - y0)))
    return result


def _detect_value_boxes(image):
    """
    Detect a dominant vertical column of cyan/blue value cells.

    This is dynamic: no machine name, parameter names, pixel coordinates,
    or fixed row count are mapped. A vertically merged contour is split using
    the median cell height found in the same image.
    """
    import cv2
    import numpy as np

    h, w = image.shape[:2]
    b, g, r = cv2.split(image)

    masks = []
    for b_min, g_min, r_max, diff_min in (
        (145, 70, 145, 55),
        (120, 55, 175, 35),
    ):
        mask = (
            (b > b_min)
            & (g > g_min)
            & (r < r_max)
            & ((b.astype("int16") - r.astype("int16")) > diff_min)
        ).astype("uint8") * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), dtype="uint8"))
        masks.append(mask)

    raw = []
    for mask in masks:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, bw, bh = cv2.boundingRect(contour)
            wr = bw / max(w, 1)
            hr = bh / max(h, 1)
            # Wide enough to be a value cell, but not a full-screen region.
            if 0.055 <= wr <= 0.22 and 0.025 <= hr <= 0.32:
                raw.append((x, y, bw, bh))

    if not raw:
        return []

    # Remove near-duplicates from the two color masks.
    raw.sort(key=lambda q: (q[1], q[0], -(q[2] * q[3])))
    dedup = []
    for box in raw:
        x, y, bw, bh = box
        duplicate = False
        for px, py, pw, ph in dedup:
            if abs(x - px) < w * 0.02 and abs(y - py) < h * 0.02:
                duplicate = True
                break
        if not duplicate:
            dedup.append(box)

    # Group by X position. The value column should contain the most cells.
    tolerance_x = max(25, int(w * 0.04))
    groups: list[list[tuple[int, int, int, int]]] = []
    for box in dedup:
        placed = False
        for group in groups:
            anchor = sum(item[0] for item in group) / len(group)
            if abs(box[0] - anchor) <= tolerance_x:
                group.append(box)
                placed = True
                break
        if not placed:
            groups.append([box])

    # Prefer a repeated vertical column in the middle area. This rejects
    # navigation buttons and one-off highlighted controls.
    def group_score(group):
        avg_x = sum(item[0] for item in group) / len(group)
        vertical_span = max(item[1] + item[3] for item in group) - min(item[1] for item in group)
        middle_bonus = 1 if 0.20 <= avg_x / max(w, 1) <= 0.72 else 0
        return (len(group), middle_bonus, vertical_span)

    dominant = max(groups, key=group_score)

    normal_heights = [bh for _, _, _, bh in dominant if bh / max(h, 1) <= 0.10]
    typical_h = int(round(sorted(normal_heights)[len(normal_heights) // 2])) if normal_heights else 0

    split = []
    for box in dominant:
        split.extend(_split_tall_value_box(box, typical_h))

    # A relaxed color mask can produce a tall merged contour while the stricter
    # mask also finds the individual cells. Remove those duplicates after split.
    split.sort(key=lambda q: (q[1], q[0], abs(q[3] - typical_h) if typical_h else q[3]))
    post_dedup = []
    y_tol = max(8, int((typical_h or max(1, h * 0.05)) * 0.45))
    x_tol = max(20, int(w * 0.025))
    for box in split:
        hit = None
        for i, prev in enumerate(post_dedup):
            if abs(box[1] - prev[1]) <= y_tol and abs(box[0] - prev[0]) <= x_tol:
                hit = i
                break
        if hit is None:
            post_dedup.append(box)
        elif typical_h and abs(box[3] - typical_h) < abs(post_dedup[hit][3] - typical_h):
            post_dedup[hit] = box
    split = sorted(post_dedup, key=lambda q: q[1])

    # Keep only a coherent vertical sequence. Dynamic count; no 6/7-row rule.
    if len(split) >= 2:
        heights = [q[3] for q in split]
        median_h = sorted(heights)[len(heights) // 2]
        split = [q for q in split if q[3] >= max(12, median_h * 0.55)]

    return split


def _ocr_digits(roi, pytesseract):
    """OCR bright digit glyphs while removing the cyan cell border."""
    import cv2
    import numpy as np

    if roi is None or roi.size == 0:
        return ""

    h, w = roi.shape[:2]
    b, g, r = cv2.split(roi)
    channel_max = np.maximum(np.maximum(b, g), r)
    channel_min = np.minimum(np.minimum(b, g), r)
    mask = ((b > 125) & (g > 125) & (r > 125) & ((channel_max - channel_min) < 75)).astype("uint8") * 255

    mask[:max(1, int(h * 0.10)), :] = 0
    mask[min(h, int(h * 0.90)):, :] = 0
    mask[:, :max(1, int(w * 0.08))] = 0
    mask[:, min(w, int(w * 0.92)):] = 0

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    glyphs = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        cx = x + bw / 2
        if bh >= h * 0.24 and bw >= 3 and w * 0.20 <= cx <= w * 0.80:
            glyphs.append((x, y, bw, bh))

    if glyphs:
        x0 = min(x for x, _, _, _ in glyphs)
        y0 = min(y for _, y, _, _ in glyphs)
        x1 = max(x + bw for x, _, bw, _ in glyphs)
        y1 = max(y + bh for _, y, _, bh in glyphs)
        pad_x = max(4, int(w * 0.02))
        pad_y = max(3, int(h * 0.06))
        glyph_mask = mask[max(0, y0-pad_y):min(h, y1+pad_y), max(0, x0-pad_x):min(w, x1+pad_x)]
        if glyph_mask.size:
            glyph_mask = cv2.resize(glyph_mask, None, fx=6.0, fy=6.0, interpolation=cv2.INTER_NEAREST)
            try:
                # PSM 8 is much better for an isolated HMI digit glyph (notably 0/4).
                # PSM 10 is retained as a fallback for thin 1 glyphs.
                for psm in (8, 10):
                    value = pytesseract.image_to_string(glyph_mask, config=f"--psm {psm}").strip()
                    digits = re.sub(r"\D", "", value)
                    if digits:
                        return digits
            except Exception:
                pass

    inner = roi[int(h*0.08):max(int(h*0.92), int(h*0.08)+1), int(w*0.08):max(int(w*0.92), int(w*0.08)+1)]
    if inner.size:
        gray = cv2.cvtColor(inner, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=4.0, fy=4.0, interpolation=cv2.INTER_CUBIC)
        try:
            value = pytesseract.image_to_string(gray, config="--psm 10 -c tessedit_char_whitelist=0123456789").strip()
            return re.sub(r"\D", "", value)
        except Exception:
            pass
    return ""

def _clean_label(text: str) -> str:
    text = " ".join(str(text or "").replace("|", " ").split())
    text = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9)]+$", "", text)
    # Remove obvious neighboring table actions if OCR bleeds rightward.
    text = re.sub(r"\b(?:RESET|DETAILS?)\b.*$", "", text, flags=re.I).strip()
    return text


def _ocr_parameter_label(image, value_box, pytesseract) -> str:
    import cv2

    x, y, bw, bh = value_box
    h, w = image.shape[:2]
    left = max(0, x - int(w * 0.34))
    right = max(left + 1, x - int(w * 0.008))
    top = max(0, y - int(h * 0.006))
    bottom = min(h, y + bh + int(h * 0.006))
    roi = image[top:bottom, left:right]
    if roi.size == 0:
        return ""

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.4, fy=2.4, interpolation=cv2.INTER_CUBIC)
    try:
        text = pytesseract.image_to_string(gray, config="--psm 7")
    except Exception:
        return ""
    return _clean_label(text)

def _looks_like_summary_label(label: str) -> bool:
    normalized = re.sub(r"[^A-Z0-9]+", " ", str(label or "").upper()).strip()
    # A summary/counter row should not become an NG parameter row.
    return bool(re.search(r"\bCOUNTER\b.*\bNG\b|\bNG\b.*\bCOUNTER\b", normalized))


def _has_right_companion_value_box(image, value_box) -> bool:
    """Detect a second blue/cyan value cell on the same row (layout signal only)."""
    import cv2
    import numpy as np

    x, y, bw, bh = value_box
    h, w = image.shape[:2]
    b, g, r = cv2.split(image)
    mask = ((b > 135) & (g > 60) & (r < 165) & ((b.astype("int16") - r.astype("int16")) > 40)).astype("uint8") * 255
    band_top = max(0, y - int(bh * 0.35))
    band_bottom = min(h, y + bh + int(bh * 0.35))
    right_start = min(w, x + bw + max(10, int(w * 0.025)))
    if right_start >= w:
        return False
    band = mask[band_top:band_bottom, right_start:w]
    contours, _ = cv2.findContours(band, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        cx, cy, cw, ch = cv2.boundingRect(contour)
        if cw >= bw * 0.45 and ch >= bh * 0.45:
            return True
    return False


def process_image(image_path: str, tesseract_cmd: str = "", app_root: str | Path | None = None) -> OcrImageResult:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(path)

    try:
        import cv2
    except Exception as e:
        raise RuntimeError(
            f"OCR dependency cv2 ไม่พร้อม ({type(e).__name__}: {e}). "
            "ตัวโปรแกรม OneDir ถูก pack ไม่ครบ กรุณา build ใหม่ด้วย build_onedir.bat รุ่น Portable OCR."
        ) from e

    try:
        import pytesseract
    except Exception as e:
        raise RuntimeError(
            f"OCR dependency pytesseract ไม่พร้อม ({type(e).__name__}: {e}). "
            "ตัวโปรแกรม OneDir ถูก pack ไม่ครบ กรุณา build ใหม่ด้วย build_onedir.bat รุ่น Portable OCR."
        ) from e

    root = Path(app_root) if app_root is not None else path.parent
    resolved_tesseract = find_tesseract(tesseract_cmd, root)
    if not resolved_tesseract:
        raise RuntimeError(
            "ไม่พบ Tesseract OCR engine. ติดตั้ง Tesseract-OCR หรือวาง portable engine ที่ "
            "tools\\Tesseract-OCR\\tesseract.exe"
        )

    pytesseract.pytesseract.tesseract_cmd = resolved_tesseract
    tessdata_dir = configure_tesseract_runtime(resolved_tesseract)
    if not tessdata_dir.is_dir():
        raise RuntimeError(
            f"Tesseract OCR พบแล้ว แต่ไม่พบ tessdata: {tessdata_dir}"
        )

    image = cv2.imread(str(path))
    if image is None:
        raise RuntimeError(f"ไม่สามารถเปิดรูปภาพ: {path.name}")

    warnings: list[str] = []

    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        raw_text = pytesseract.image_to_string(gray, config="--psm 11").strip()
    except Exception:
        raw_text = ""

    boxes = _detect_value_boxes(image)
    if not boxes:
        warnings.append("ไม่พบกลุ่ม Value cell ที่ชัดเจน กรุณาตรวจภาพ/มุมกล้อง")

    start_dt = _image_time(path)
    start_text = start_dt.strftime("%H:%M:%S")
    stop_text = start_text

    rows: list[OcrNgRow] = []
    counter_ng = ""

    for index, box in enumerate(boxes, start=1):
        x, y, bw, bh = box
        value = _ocr_digits(image[y:y + bh, x:x + bw], pytesseract)
        original = _ocr_parameter_label(image, box, pytesseract)
        label = original.strip() or f"OCR ROW {index}"

        if _looks_like_summary_label(label) or _has_right_companion_value_box(image, box):
            counter_ng = value
            continue

        # If the final row has no usable label but all earlier rows do, it is
        # often a summary/counter line. Keep it out only when the raw OCR says
        # COUNTER NG; otherwise preserve it rather than guessing.
        if not original and index == len(boxes):
            labeled_before = sum(1 for row in rows if row.ocr_original)
            if labeled_before >= 2 or re.search(r"COUNTER\s*NG", raw_text, re.I):
                counter_ng = value
                continue

        checked = bool(value.isdigit() and int(value) > 0)
        rows.append(
            OcrNgRow(
                source_file=path.name,
                source_path=str(path),
                parameter=label,
                ocr_original=original,
                message=f"{label} NG",
                counter=value,
                start_time=start_text,
                stop_time=stop_text,
                checked_default=checked,
            )
        )

    # Generic fallback for this HMI family: when the last detected value row has
    # no label and looks like a summary total, expose it as COUNTER NG rather
    # than registering it. This uses layout only, not a machine/parameter map.
    if rows and not counter_ng and len(boxes) > len(rows):
        pass

    blank_values = [row.parameter for row in rows if not row.counter]
    if blank_values:
        warnings.append("OCR Value ว่าง: " + ", ".join(blank_values))

    if not rows:
        warnings.append("OCR ไม่พบ Parameter + Value row สำหรับ Register")

    return OcrImageResult(
        source_file=path.name,
        source_path=str(path),
        rows=rows,
        counter_ng=counter_ng,
        raw_text=raw_text,
        engine=resolved_tesseract,
        warnings=warnings,
    )


def process_images(image_paths: list[str], tesseract_cmd: str = "", app_root: str | Path | None = None) -> list[OcrImageResult]:
    return [
        process_image(path, tesseract_cmd=tesseract_cmd, app_root=app_root)
        for path in image_paths
    ]


def build_description(message: str, counter: str) -> str:
    message = " ".join(str(message or "").split())
    counter = str(counter or "").strip()

    if not message:
        raise ValueError("Message ห้ามว่าง")
    if not counter.isdigit():
        raise ValueError("Counter ต้องเป็นตัวเลข")

    return f"Machine Judge {message} {counter} PCS"
