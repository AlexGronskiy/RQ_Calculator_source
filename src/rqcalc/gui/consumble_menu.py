from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, List, Tuple, Any, Dict, Iterable

from PySide6.QtCore import Qt, QRect, QPoint, Signal, QEvent, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QFontMetrics, QBitmap
from PySide6.QtWidgets import (
    QWidget, QLabel, QApplication, QLineEdit, QScrollArea, QVBoxLayout, QFrame
)

try:
    from .weapon_equipment_button import ImageVScrollBar, _find_scroll_dir  # type: ignore
except Exception:
    ImageVScrollBar = None  # type: ignore
    _find_scroll_dir = None  # type: ignore


def _resolve_resource(rel: str) -> str:
    p = Path(rel)
    for c in (
        Path.cwd() / p,
        Path(__file__).resolve().parents[2] / p,
        Path(__file__).resolve().parents[3] / p,
    ):
        if c.exists():
            return str(c)
    return str(p)


def _to_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        try:
            return int(float(str(v).strip()))
        except Exception:
            return int(default)


def _to_str(v) -> str:
    try:
        return str(v or "")
    except Exception:
        return ""


def _load_db_image_pixmap(conn, image_id: int) -> QPixmap:
    iid = int(image_id or 0)
    if conn is None or iid <= 0:
        return QPixmap()

    try:
        row = conn.execute("SELECT Data FROM Image WHERE Id=? LIMIT 1", (iid,)).fetchone()
    except Exception:
        row = None

    if not row:
        return QPixmap()

    try:
        data = row["Data"] if hasattr(row, "keys") else row[0]
        if isinstance(data, memoryview):
            data = data.tobytes()
        elif not isinstance(data, (bytes, bytearray)):
            data = bytes(data)
    except Exception:
        return QPixmap()

    pm = QPixmap()
    try:
        pm.loadFromData(data)
    except Exception:
        return QPixmap()
    return pm


_PLACEHOLDER_RE = re.compile(r"\{0\}")


def _format_bonus_line(template: str, value: int | float) -> str:
    tpl = _to_str(template).strip()
    try:
        val_num = int(value)
    except Exception:
        try:
            val_num = float(value)
        except Exception:
            val_num = value

    signed = f"+{val_num}" if str(val_num)[0] != "-" else str(val_num)

    if "{0}" not in tpl:
        return f"{tpl} {signed}".strip() if tpl else signed

    idx = tpl.find("{0}")
    left_char = tpl[idx - 1] if idx > 0 else ""
    if left_char in ("+", "-"):
        repl = str(val_num)
    else:
        repl = signed

    return _PLACEHOLDER_RE.sub(repl, tpl, count=1).strip()

def _to_optional_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        s = str(v).strip()
    except Exception:
        return None
    if s == "":
        return None
    try:
        return int(v)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return None

def load_consumble_entries_from_db(conn) -> List[Dict[str, Any]]:
    """
    Возвращает entries для меню расходников:
    [
        {
            "consumble": {"Id":..., "Name":..., "Image_Id":..., "Exeption":...},
            "bonuses": [...],
            "icon_pm": QPixmap(...)
        },
        ...
    ]
    """
    if conn is None:
        return []

    try:
        rows = conn.execute(
            """
            SELECT Id, Name, Image_Id, Exeption
            FROM Consumable
            ORDER BY Name COLLATE NOCASE, Name
            """
        ).fetchall()
    except Exception:
        rows = []

    if not rows:
        return []

    out: List[Dict[str, Any]] = []
    ids: List[int] = []
    icon_cache: Dict[int, QPixmap] = {}

    for r in rows or []:
        try:
            if hasattr(r, "keys"):
                cid = _to_int(r["Id"], 0)
                name = _to_str(r["Name"])
                image_id = _to_int(r["Image_Id"], 0)
                ex = _to_optional_int(r["Exeption"])
            else:
                cid = _to_int(r[0], 0)
                name = _to_str(r[1])
                image_id = _to_int(r[2], 0)
                ex = _to_optional_int(r[3])
        except Exception:
            continue

        if cid <= 0:
            continue

        if image_id not in icon_cache:
            icon_cache[image_id] = _load_db_image_pixmap(conn, image_id)

        out.append(
            {
                "consumble": {
                    "Id": int(cid),
                    "Name": str(name),
                    "Image_Id": int(image_id),
                    "Exeption": ex,
                },
                "bonuses": [],
                "icon_pm": icon_cache.get(image_id) or QPixmap(),
            }
        )
        ids.append(int(cid))

    if not ids:
        return out

    ph = ",".join(["?"] * len(ids))

    try:
        bonus_rows = conn.execute(
            f"""
            SELECT Consumable_Id, Type_Id, Value, OrderIndex
            FROM ConsumableBonus
            WHERE Consumable_Id IN ({ph})
            ORDER BY Consumable_Id, OrderIndex
            """,
            tuple(int(x) for x in ids),
        ).fetchall()
    except Exception:
        bonus_rows = []

    type_ids: List[int] = []
    raw_bonus: List[Tuple[int, int, int]] = []

    for r in bonus_rows or []:
        try:
            if hasattr(r, "keys"):
                cons_id = _to_int(r["Consumable_Id"], 0)
                type_id = _to_int(r["Type_Id"], 0)
                value = _to_int(r["Value"], 0)
            else:
                cons_id = _to_int(r[0], 0)
                type_id = _to_int(r[1], 0)
                value = _to_int(r[2], 0)
        except Exception:
            continue

        if cons_id <= 0 or type_id <= 0:
            continue

        raw_bonus.append((int(cons_id), int(type_id), int(value)))
        type_ids.append(int(type_id))

    templates: Dict[int, str] = {}
    uniq_type_ids = sorted(set(type_ids))

    if uniq_type_ids:
        ph2 = ",".join(["?"] * len(uniq_type_ids))
        try:
            bt_rows = conn.execute(
                f"""
                SELECT Id, Template
                FROM BonusType
                WHERE Id IN ({ph2})
                """,
                tuple(int(x) for x in uniq_type_ids),
            ).fetchall()
        except Exception:
            bt_rows = []

        for r in bt_rows or []:
            try:
                if hasattr(r, "keys"):
                    bt_id = _to_int(r["Id"], 0)
                    template = _to_str(r["Template"])
                else:
                    bt_id = _to_int(r[0], 0)
                    template = _to_str(r[1])
            except Exception:
                continue
            if bt_id > 0:
                templates[int(bt_id)] = str(template)

    bonus_map: Dict[int, List[str]] = {}
    for cons_id, type_id, value in raw_bonus:
        line = _format_bonus_line(templates.get(int(type_id), ""), value)
        bonus_map.setdefault(int(cons_id), []).append(line)

    for e in out:
        try:
            cid = int((e.get("consumble") or {}).get("Id") or 0)
        except Exception:
            cid = 0
        e["bonuses"] = list(bonus_map.get(cid, []))

    return out


@dataclass
class ConsumbleChooseConfig:
    bg_path: str = "resources/consumble_menu/consumble_choose.png"
    fallback_size: Tuple[int, int] = (552, 372)

    search_rect: Tuple[int, int, int, int] = (18, 55, 500, 28)
    content_rect: Tuple[int, int, int, int] = (17, 114, 499, 241)

    block_bg_path: str = "resources/consumble_menu/consumble_block.png"
    block_size: Tuple[int, int] = (499, 89)
    block_gap_y: int = 1

    vscroll_rect: Optional[Tuple[int, int, int, int]] = (519, 115, 18, 239)
    vscroll_margin: int = 6

    close_rect: Tuple[int, int, int, int] = (525, 4, 24, 24)
    close_active_path: str = "resources/helper_buttons/close_button_active.png"

    icon_rect: Tuple[int, int, int, int] = (9, 20, 50, 50)
    name_rect: Tuple[int, int, int, int] = (66, 8, 160, 34)
    bonuses_rect: Tuple[int, int, int, int] = (240, 4, 165, 77)
    selected_rect: Tuple[int, int, int, int] = (430, 8, 74, 73)

    bonus_scrollbar_w: int = 10
    bonus_scrollbar_gap: int = 4
    bonus_wheel_step_px: int = 24


class _MiniVScroll(QWidget):
    valueChanged = Signal(int)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_NoMouseReplay, True)

        self._content_h = 0
        self._view_h = 0
        self._max_value = 0
        self._value = 0
        self._dragging = False
        self._drag_off = 0

        self.setFixedWidth(10)

    def set_range(self, content_h: int, view_h: int) -> None:
        self._content_h = max(0, int(content_h))
        self._view_h = max(0, int(view_h))
        self._max_value = max(0, self._content_h - self._view_h)
        if self._value > self._max_value:
            self._value = self._max_value
            self.valueChanged.emit(int(self._value))
        self.setVisible(self._max_value > 0)
        self.update()

    def set_value(self, v: int) -> None:
        v = max(0, min(int(v), int(self._max_value)))
        if v == self._value:
            return
        self._value = v
        self.valueChanged.emit(int(self._value))
        self.update()

    def value(self) -> int:
        return int(self._value)

    def maximum(self) -> int:
        return int(self._max_value)

    def _track_rect(self) -> QRect:
        return self.rect().adjusted(2, 2, -2, -2)

    def _thumb_h(self) -> int:
        tr = self._track_rect()
        if tr.height() <= 0 or self._content_h <= 0:
            return 10
        if self._max_value <= 0:
            return tr.height()
        ratio = float(self._view_h) / float(self._content_h) if self._content_h else 1.0
        h = int(tr.height() * ratio)
        return max(12, min(tr.height(), h))

    def _thumb_rect(self) -> QRect:
        tr = self._track_rect()
        th = self._thumb_h()
        if self._max_value <= 0:
            return QRect(tr.x(), tr.y(), tr.width(), tr.height())

        span = max(1, tr.height() - th)
        y = tr.y() + int(span * (float(self._value) / float(self._max_value)))
        return QRect(tr.x(), y, tr.width(), th)

    def _value_from_thumb_top(self, y_top: int) -> int:
        tr = self._track_rect()
        th = self._thumb_h()
        span = max(1, tr.height() - th)
        rel = max(0, min(y_top - tr.y(), span))
        return int(round(float(rel) * float(self._max_value) / float(span))) if self._max_value > 0 else 0

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        tr = self._track_rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 35))
        p.drawRoundedRect(tr, 4, 4)

        th = self._thumb_rect()
        p.setBrush(QColor(255, 255, 255, 120))
        p.drawRoundedRect(th, 4, 4)
        p.end()

    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)

        th = self._thumb_rect()
        if th.contains(ev.pos()):
            self._dragging = True
            self._drag_off = int(ev.pos().y() - th.y())
            ev.accept()
            return

        tr = self._track_rect()
        y_top = int(ev.pos().y() - self._thumb_h() // 2)
        y_top = max(tr.y(), min(y_top, tr.bottom() - self._thumb_h() + 1))
        self.set_value(self._value_from_thumb_top(y_top))
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        if not self._dragging:
            return super().mouseMoveEvent(ev)

        tr = self._track_rect()
        y_top = int(ev.pos().y() - self._drag_off)
        y_top = max(tr.y(), min(y_top, tr.bottom() - self._thumb_h() + 1))
        self.set_value(self._value_from_thumb_top(y_top))
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            ev.accept()
            return
        super().mouseReleaseEvent(ev)


class _ConsumbleBlock(QWidget):
    hovered = Signal(object)
    unhovered = Signal(object)
    clicked = Signal(object)

    def __init__(
        self,
        parent: QWidget,
        *,
        cfg: ConsumbleChooseConfig,
        bg_pm: Optional[QPixmap],
        size: Tuple[int, int],
    ):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_NoMouseReplay, True)

        self.cfg = cfg
        self._bg_pm = bg_pm if (bg_pm and not bg_pm.isNull()) else None

        w, h = int(size[0]), int(size[1])
        self.setFixedSize(w, h)

        self._hover = False
        self._selected = False

        self.consumble: Optional[Dict[str, Any]] = None
        self.bonus_lines: List[str] = []
        self._icon_pm: Optional[QPixmap] = None

        self._bonus_text: str = ""
        self._bonus_scroll = 0
        self._bonus_total_h = 0
        self._font_bonus = QFont("Segoe UI", 9)

        self._mini = _MiniVScroll(self)
        self._mini.valueChanged.connect(self._on_mini_scroll)
        self._mini.hide()

    def set_selected(self, on: bool) -> None:
        on = bool(on)
        if self._selected == on:
            return
        self._selected = on
        self.update()

    def set_payload(self, consumble: Dict[str, Any], bonus_lines: List[str], icon_pm: Optional[QPixmap]) -> None:
        self.consumble = dict(consumble) if isinstance(consumble, dict) else None
        self.bonus_lines = list(bonus_lines or [])
        self._icon_pm = icon_pm if (icon_pm and not icon_pm.isNull()) else None

        lines = [str(x) for x in (self.bonus_lines or []) if str(x).strip()]
        self._bonus_text = "\n".join(lines).replace("\r", "").strip()
        self._bonus_scroll = 0

        bx, by, bw, bh = self.cfg.bonuses_rect
        view_h = int(bh)

        sb_w = int(self.cfg.bonus_scrollbar_w)
        gap = int(self.cfg.bonus_scrollbar_gap)

        fm = QFontMetrics(self._font_bonus)

        total_h = 0
        if self._bonus_text:
            br = fm.boundingRect(QRect(0, 0, int(bw), 10000), Qt.TextWordWrap, self._bonus_text)
            total_h = int(br.height())

        use_sb = (total_h > view_h)

        if use_sb and self._bonus_text:
            text_w = max(10, int(bw) - (sb_w + gap))
            br2 = fm.boundingRect(QRect(0, 0, text_w, 10000), Qt.TextWordWrap, self._bonus_text)
            total_h = int(br2.height())

        self._bonus_total_h = int(total_h)
        max_scroll = max(0, self._bonus_total_h - view_h)

        if use_sb and max_scroll > 0:
            sb_x = int(bx + bw - sb_w)
            sb_y = int(by)
            sb_h = int(bh)

            self._mini.setFixedWidth(sb_w)
            self._mini.setGeometry(sb_x, sb_y, sb_w, sb_h)
            self._mini.set_range(self._bonus_total_h, view_h)
            self._mini.set_value(0)
            self._mini.show()
            self._mini.raise_()
        else:
            self._mini.hide()

        self.update()

    def _on_mini_scroll(self, v: int) -> None:
        self._bonus_scroll = int(v)
        self.update()

    def _set_hover(self, on: bool) -> None:
        on = bool(on)
        if self._hover == on:
            return
        self._hover = on
        self.update()
        if on:
            self.hovered.emit(self)
        else:
            self.unhovered.emit(self)

    def enterEvent(self, _ev) -> None:
        self._set_hover(True)
        super().enterEvent(_ev)

    def leaveEvent(self, _ev) -> None:
        self._set_hover(False)
        super().leaveEvent(_ev)

    def wheelEvent(self, ev) -> None:
        bx, by, bw, bh = self.cfg.bonuses_rect
        br = QRect(int(bx), int(by), int(bw), int(bh))
        if br.contains(ev.position().toPoint()) and self._mini.isVisible() and self._mini.maximum() > 0:
            step = int(self.cfg.bonus_wheel_step_px)
            dy = ev.angleDelta().y()
            if dy > 0:
                self._mini.set_value(self._mini.value() - step)
            elif dy < 0:
                self._mini.set_value(self._mini.value() + step)
            ev.accept()
            return
        super().wheelEvent(ev)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._pressed = bool(isinstance(self.consumble, dict) and self.consumble)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(ev)

        was_pressed = bool(getattr(self, "_pressed", False))
        self._pressed = False

        if not was_pressed:
            ev.accept()
            return

        over = self.rect().contains(ev.position().toPoint()) if hasattr(ev, "position") else self.rect().contains(
            ev.pos())

        if over and isinstance(self.consumble, dict) and self.consumble:
            self.clicked.emit(self)

        ev.accept()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        r = self.rect()

        if self._bg_pm and not self._bg_pm.isNull():
            p.drawPixmap(r, self._bg_pm)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 20, 24, 235))
            p.drawRoundedRect(r.adjusted(0, 0, -1, -1), 8, 8)

        if self._selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(235, 190, 70, 32))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 6, 6)

            pen = QPen(QColor(235, 190, 70, 230))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 6, 6)
        elif self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(240, 220, 140, 35))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 6, 6)

            pen = QPen(QColor(240, 220, 140, 200))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 6, 6)

        it = self.consumble or {}

        ix, iy, iw, ih = self.cfg.icon_rect
        icon_r = QRect(int(ix), int(iy), int(iw), int(ih))
        if self._icon_pm and not self._icon_pm.isNull():
            scaled = self._icon_pm.scaled(icon_r.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            dst = QRect(0, 0, scaled.width(), scaled.height())
            dst.moveCenter(icon_r.center())
            p.drawPixmap(dst, scaled)

        nx, ny, nw, nh = self.cfg.name_rect
        name_r = QRect(int(nx), int(ny), int(nw), int(nh))
        f = QFont()
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(235, 235, 235, 235))
        p.drawText(name_r, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter, str(it.get("Name") or ""))

        px, py, pw, ph = self.cfg.bonuses_rect
        sb_w = int(self.cfg.bonus_scrollbar_w)
        gap = int(self.cfg.bonus_scrollbar_gap)

        text_w = int(pw)
        scroll_mode = bool(self._mini.isVisible() and self._mini.maximum() > 0)
        if scroll_mode:
            text_w = max(10, text_w - (sb_w + gap))

        bon_r = QRect(int(px), int(py), int(text_w), int(ph))
        p.setFont(self._font_bonus)
        p.setPen(QColor(207, 230, 165, 235))

        if not self._bonus_text:
            p.drawText(bon_r, Qt.AlignLeft | Qt.AlignVCenter, "—")
        elif scroll_mode:
            p.save()
            p.setClipRect(bon_r)
            p.translate(0, -int(self._bonus_scroll))
            big = QRect(
                bon_r.x(),
                bon_r.y(),
                bon_r.width(),
                max(10000, bon_r.height() + int(self._bonus_total_h) + 100),
            )
            p.drawText(big, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, self._bonus_text)
            p.restore()
        else:
            fm = QFontMetrics(self._font_bonus)
            br = fm.boundingRect(QRect(0, 0, bon_r.width(), 10000), Qt.TextWordWrap, self._bonus_text)
            text_h = max(1, int(br.height()))
            y0 = bon_r.y() + max(0, (bon_r.height() - text_h) // 2)
            centered = QRect(bon_r.x(), y0, bon_r.width(), text_h)
            p.drawText(centered, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, self._bonus_text)

        sx, sy, sw, sh = self.cfg.selected_rect
        sel_r = QRect(int(sx), int(sy), int(sw), int(sh))

        f2 = QFont("Segoe UI", 9)
        f2.setBold(True)
        p.setFont(f2)

        if self._selected:
            p.setPen(QColor(240, 210, 122, 235))
            p.drawText(sel_r, Qt.AlignCenter, "✓")
        else:
            p.setPen(QColor(150, 150, 150, 220))
            p.drawText(sel_r, Qt.AlignCenter, "—")

        p.end()


class ChooseConsumbleMenu(QWidget):
    picked = Signal(dict)
    closed = Signal()

    def __init__(self, parent: QWidget, *, config: Optional[ConsumbleChooseConfig] = None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoMouseReplay, True)

        self.cfg = config or ConsumbleChooseConfig()

        bg_path = _resolve_resource(self.cfg.bg_path)
        self._bg_pm = QPixmap(bg_path)
        if self._bg_pm.isNull():
            w, h = self.cfg.fallback_size
            self._bg_pm = QPixmap(int(w), int(h))
            self._bg_pm.fill(QColor(0, 0, 0, 0))

        self.setFixedSize(self._bg_pm.size())
        self._apply_window_mask_from_bg()

        self._bg = QLabel(self)
        self._bg.setPixmap(self._bg_pm)
        self._bg.setScaledContents(True)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        self._bg.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        block_path = _resolve_resource(self.cfg.block_bg_path)
        self._block_pm = QPixmap(block_path)
        if self._block_pm.isNull():
            self._block_pm = None

        self._close_active_pm = QPixmap(_resolve_resource(self.cfg.close_active_path))

        self._on_pick: Optional[Callable[[Dict[str, Any], List[str]], None]] = None
        self._on_hover_enter: Optional[Callable[[QWidget, Dict[str, Any], List[str]], None]] = None
        self._on_hover_leave: Optional[Callable[[QWidget], None]] = None

        self._blocks: List[_ConsumbleBlock] = []
        self._index_text: Dict[_ConsumbleBlock, str] = {}
        self._last_hover: Optional[_ConsumbleBlock] = None
        self._selected_ids: set[int] = set()
        self._exception_by_id: Dict[int, int] = {}
        self._close_down: bool = False

        cx, cy, cw, ch = self.cfg.close_rect
        self._close = QLabel(self)
        self._close.setGeometry(int(cx), int(cy), int(cw), int(ch))
        self._close.setAttribute(Qt.WA_TranslucentBackground, True)
        self._close.setAutoFillBackground(False)
        self._close.setStyleSheet("background-color: rgba(0, 0, 0, 0); border: none;")
        self._close.setScaledContents(False)
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.installEventFilter(self)

        sx, sy, sw, sh = self.cfg.search_rect
        self.search_edit = QLineEdit(self)
        self.search_edit.setGeometry(int(sx), int(sy), int(sw), int(sh))
        self.search_edit.setPlaceholderText("Поиск расходника (название / бонусы)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setStyleSheet(
            "QLineEdit{background: rgba(0,0,0,0); border: 0px; color:#eaeaea; padding-left:6px;}"
            "QLineEdit:focus{outline:none;}"
        )
        self.search_edit.textChanged.connect(self._apply_filter)

        cx, cy, cw, ch = self.cfg.content_rect
        self._area = QScrollArea(self)
        self._area.setGeometry(int(cx), int(cy), int(cw), int(ch))
        self._area.setFrameShape(QFrame.NoFrame)
        self._area.setWidgetResizable(True)
        self._area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._area.setAttribute(Qt.WA_TranslucentBackground, True)
        self._area.setAutoFillBackground(False)

        try:
            self._area.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
            self._area.viewport().setAutoFillBackground(False)
            self._area.viewport().setStyleSheet("background: transparent;")
        except Exception:
            pass

        self._cont = QWidget()
        self._cont.setAttribute(Qt.WA_TranslucentBackground, True)
        self._cont.setAutoFillBackground(False)
        self._cont.setStyleSheet("background: transparent;")
        self._area.setWidget(self._cont)

        self._vbox = QVBoxLayout(self._cont)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(int(self.cfg.block_gap_y))

        self._sv_custom = None
        if ImageVScrollBar is not None and callable(_find_scroll_dir):
            try:
                self._sv_custom = ImageVScrollBar(
                    self._area.verticalScrollBar(),
                    _find_scroll_dir(),
                    parent=self,
                )
                self._sv_custom.hide()
            except Exception:
                self._sv_custom = None

        vb = self._area.verticalScrollBar()
        vb.setSingleStep(24)
        vb.setPageStep(120)
        vb.rangeChanged.connect(lambda _a, _b: self._sync_scrollbar_visible())

        self.installEventFilter(self)
        QTimer.singleShot(0, self._place_vscroll)
        self.hide()

    def _apply_window_mask_from_bg(self) -> None:
        try:
            pm = self._bg_pm
        except Exception:
            pm = None

        if pm is None or pm.isNull():
            return

        try:
            img = pm.toImage()
        except Exception:
            return

        try:
            if not img.hasAlphaChannel():
                return
        except Exception:
            return

        try:
            mask_img = img.createAlphaMask()
            mask_bm = QBitmap.fromImage(mask_img, Qt.AutoColor)
            if mask_bm is not None and not mask_bm.isNull():
                self.setMask(mask_bm)
        except Exception:
            pass

    def _set_close_pixmap(self, pm: Optional[QPixmap]) -> None:
        try:
            self._close.clear()
        except Exception:
            pass

        if pm is None or pm.isNull():
            return

        try:
            scaled = pm.scaled(
                self._close.size(),
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
        except Exception:
            return

        canvas = QPixmap(self._close.size())
        canvas.fill(Qt.GlobalColor.transparent)

        p = QPainter(canvas)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(0, 0, scaled)
        p.end()

        self._close.setPixmap(canvas)

    def selected_ids(self) -> List[int]:
        return sorted(int(x) for x in self._selected_ids)

    def set_selected_ids(self, ids: Iterable[int]) -> None:
        new_ids: List[int] = []
        for x in list(ids or []):
            try:
                v = int(x)
            except Exception:
                continue
            if v > 0:
                new_ids.append(v)

        selected: List[int] = []
        seen_groups: Dict[int, int] = {}

        for cid in new_ids:
            grp = self._exception_by_id.get(int(cid), None)

            if grp is not None and int(grp) >= 0:
                prev = seen_groups.get(int(grp))
                if prev is not None and prev in selected:
                    selected.remove(prev)
                seen_groups[int(grp)] = int(cid)

            if int(cid) not in selected:
                selected.append(int(cid))

        self._selected_ids = set(selected)
        self._sync_block_selection()

    def open_for(
        self,
        *,
        anchor_widget: QWidget,
        conn=None,
        on_pick: Callable[[Dict[str, Any], List[str]], None],
        on_hover_enter: Optional[Callable[[QWidget, Dict[str, Any], List[str]], None]] = None,
        on_hover_leave: Optional[Callable[[QWidget], None]] = None,
        initial_search: str = "",
        selected_ids: Iterable[int] = (),
        focus_search: bool = True,
    ) -> None:
        self._on_pick = on_pick
        self._on_hover_enter = on_hover_enter
        self._on_hover_leave = on_hover_leave

        try:
            self.search_edit.blockSignals(True)
            self.search_edit.setText(str(initial_search or ""))
        finally:
            self.search_edit.blockSignals(False)

        entries = load_consumble_entries_from_db(conn)
        self.set_entries(entries)
        self.set_selected_ids(selected_ids)

        hint = self.sizeHint()
        tl = anchor_widget.mapToGlobal(anchor_widget.rect().bottomLeft())
        x, y = tl.x(), tl.y() - 420

        scr = (
            anchor_widget.window().screen().availableGeometry()
            if anchor_widget.window()
            else QApplication.primaryScreen().availableGeometry()
        )

        if x + hint.width() > scr.right() - 6:
            x = max(scr.left() + 6, scr.right() - hint.width() - 6)
        if y + hint.height() > scr.bottom() - 6:
            y = anchor_widget.mapToGlobal(anchor_widget.rect().topLeft()).y() - hint.height() - 6

        self.move(int(x), int(y))
        self.show()
        self.raise_()
        self.activateWindow()

        QTimer.singleShot(0, self._place_vscroll)

        if focus_search:
            QTimer.singleShot(0, self._focus_search)

    def set_entries(self, entries: List[Dict[str, Any]]) -> None:
        self._build_blocks(entries or [])
        self._apply_filter(self.search_edit.text())
        QTimer.singleShot(0, self._sync_scrollbar_visible)

    def _norm(self, s: str) -> str:
        return (s or "").casefold().replace("ё", "е").strip()

    def _make_index_text(self, consumble: Dict[str, Any], bonus_lines: List[str]) -> str:
        name = str(consumble.get("Name") or "")
        body = "  ".join([str(x) for x in (bonus_lines or [])])
        return self._norm(f"{name} {body}")

    def _clear_blocks(self) -> None:
        self._blocks = []
        self._index_text = {}
        self._last_hover = None
        self._exception_by_id = {}
        while self._vbox.count():
            it = self._vbox.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _build_blocks(self, entries: List[Dict[str, Any]]) -> None:
        self._clear_blocks()
        bsz = self.cfg.block_size

        for e in entries or []:
            consumble = dict(e.get("consumble") or {})
            if not consumble:
                continue

            cid = _to_int(consumble.get("Id"), 0)
            ex = consumble.get("Exeption", None)
            ex = _to_optional_int(ex)

            if cid > 0:
                self._exception_by_id[int(cid)] = ex

            lines = list(e.get("bonuses") or [])
            icon_pm = e.get("icon_pm")
            if not isinstance(icon_pm, QPixmap) or icon_pm.isNull():
                icon_pm = None

            blk = _ConsumbleBlock(self._cont, cfg=self.cfg, bg_pm=self._block_pm, size=bsz)
            blk.set_payload(consumble, lines, icon_pm)
            blk.clicked.connect(self._on_block_clicked)
            blk.hovered.connect(self._on_block_hover)
            blk.unhovered.connect(self._on_block_unhover)

            self._vbox.addWidget(blk)
            self._blocks.append(blk)
            self._index_text[blk] = self._make_index_text(consumble, lines)

        self._vbox.addStretch(1)
        self._sync_block_selection()

    def _sync_block_selection(self) -> None:
        sel = {int(x) for x in self._selected_ids}
        for blk in self._blocks:
            try:
                cid = int((blk.consumble or {}).get("Id") or 0)
            except Exception:
                cid = 0
            blk.set_selected(cid > 0 and cid in sel)

    def _toggle_selected(self, cid: int) -> None:
        cid = int(cid or 0)
        if cid <= 0:
            return

        sel = set(int(x) for x in self._selected_ids)

        if cid in sel:
            sel.discard(cid)
            self._selected_ids = set(sel)
            self._sync_block_selection()
            return

        grp = self._exception_by_id.get(cid, None)

        if grp is not None and int(grp) >= 0:
            to_remove: List[int] = []
            for other in sel:
                other_grp = self._exception_by_id.get(int(other), None)
                if other_grp is not None and int(other_grp) == int(grp):
                    to_remove.append(int(other))
            for other in to_remove:
                sel.discard(other)

        sel.add(cid)
        self._selected_ids = set(sel)
        self._sync_block_selection()

    def _on_block_clicked(self, blk: _ConsumbleBlock) -> None:
        if not isinstance(getattr(blk, "consumble", None), dict) or not blk.consumble:
            return

        try:
            picked_id = int(blk.consumble.get("Id") or 0)
        except Exception:
            picked_id = 0

        if picked_id <= 0:
            return

        self._toggle_selected(int(picked_id))

        cb = self._on_pick
        if callable(cb):
            try:
                cb(dict(blk.consumble), list(getattr(blk, "bonus_lines", []) or []))
            except Exception:
                pass

        try:
            self.picked.emit(dict(blk.consumble))
        except Exception:
            pass

    def _on_block_hover(self, blk: _ConsumbleBlock) -> None:
        self._last_hover = blk
        cb = self._on_hover_enter
        if callable(cb) and isinstance(getattr(blk, "consumble", None), dict) and blk.consumble:
            try:
                cb(blk, dict(blk.consumble), list(getattr(blk, "bonus_lines", []) or []))
            except Exception:
                pass

    def _on_block_unhover(self, blk: _ConsumbleBlock) -> None:
        if self._last_hover is blk:
            self._last_hover = None
        cb = self._on_hover_leave
        if callable(cb):
            try:
                cb(blk)
            except Exception:
                pass

    def _apply_filter(self, txt: str) -> None:
        qn = self._norm(str(txt or ""))
        if not qn:
            for b in self._blocks:
                b.setVisible(True)
            return

        toks = [t for t in qn.split() if t]
        for b in self._blocks:
            blob = self._index_text.get(b, "")
            ok = all(t in blob for t in toks)
            b.setVisible(ok)

    def _focus_search(self) -> None:
        try:
            self.search_edit.setFocus(Qt.ActiveWindowFocusReason)
            self.search_edit.selectAll()
        except Exception:
            pass

    def _sync_scrollbar_visible(self) -> None:
        if self._sv_custom is None:
            return
        try:
            vb = self._area.verticalScrollBar()
            self._sv_custom.setVisible(vb.maximum() > 0)
        except Exception:
            pass

    def _place_vscroll(self) -> None:
        if self._sv_custom is None:
            return
        try:
            if self.cfg.vscroll_rect:
                x, y, w, h = self.cfg.vscroll_rect
                self._sv_custom.setGeometry(int(x), int(y), int(w), int(h))
                self._sync_scrollbar_visible()
                return

            cx, cy, cw, ch = self.cfg.content_rect
            margin = int(self.cfg.vscroll_margin)
            ar = QRect(int(cx), int(cy), int(cw), int(ch))
            x = ar.right() - self._sv_custom.width() - margin
            y = ar.top() + margin
            h = max(1, ar.height() - margin * 2)
            self._sv_custom.setGeometry(int(x), int(y), int(self._sv_custom.width()), int(h))
            self._sync_scrollbar_visible()
        except Exception:
            pass

    def _is_over_widget(self, w: QWidget, ev) -> bool:
        try:
            gp = ev.globalPosition().toPoint()
        except Exception:
            try:
                gp = ev.globalPos()
            except Exception:
                return False
        try:
            lp = w.mapFromGlobal(gp)
        except Exception:
            return False
        return w.rect().contains(lp)

    def eventFilter(self, obj, ev) -> bool:
        if obj is self and ev.type() == QEvent.Resize:
            QTimer.singleShot(0, self._place_vscroll)
            return False

        if obj is self._close:
            if ev.type() == QEvent.Enter:
                if not self._close_active_pm.isNull():
                    self._set_close_pixmap(self._close_active_pm)
                return False

            if ev.type() == QEvent.Leave:
                if not self._close_down:
                    self._set_close_pixmap(None)
                return False

            if ev.type() == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
                self._close_down = True
                if not self._close_active_pm.isNull():
                    self._set_close_pixmap(self._close_active_pm)
                return True

            if ev.type() == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
                was_down = self._close_down
                self._close_down = False
                over = self._is_over_widget(self._close, ev)

                if not over:
                    self._set_close_pixmap(None)

                if was_down and over:
                    self.hide()
                    try:
                        self.closed.emit()
                    except Exception:
                        pass
                return True

            return False

        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            self.hide()
            try:
                self.closed.emit()
            except Exception:
                pass
            ev.accept()
            return
        super().keyPressEvent(ev)

    def hideEvent(self, ev) -> None:
        blk = self._last_hover
        self._last_hover = None
        cb = self._on_hover_leave
        if blk is not None and callable(cb):
            try:
                cb(blk)
            except Exception:
                pass

        try:
            self.search_edit.clearFocus()
        except Exception:
            pass

        try:
            self._set_close_pixmap(None)
        except Exception:
            pass
        self._close_down = False

        super().hideEvent(ev)