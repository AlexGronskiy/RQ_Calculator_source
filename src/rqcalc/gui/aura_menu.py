from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any

from PySide6.QtCore import Qt, QRect, QEvent, Signal, QPoint, QSize
from PySide6.QtGui import QPixmap, QBitmap, QPainter, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QWidget,
    QScrollArea,
    QVBoxLayout,
    QApplication,
)


def _resolve_resource(rel_path: str) -> str:
    p = Path(rel_path)
    if p.exists():
        return str(p)

    here = Path(__file__).resolve()
    for i in range(1, 7):
        try:
            cand = here.parents[i] / rel_path
        except Exception:
            break
        if cand.exists():
            return str(cand)

    return str(p)


def _safe_int(v, default: int = 0) -> int:
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


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        try:
            return float(str(v).strip().replace(",", "."))
        except Exception:
            return float(default)


def _format_number_for_bonus(v: Any) -> str:
    fv = _safe_float(v, 0.0)
    if abs(fv - round(fv)) < 1e-9:
        return str(int(round(fv)))
    return f"{fv:.4f}".rstrip("0").rstrip(".")


def _format_bonus_template(template: str, value: Any) -> str:
    tpl = _to_str(template).strip()
    if not tpl:
        return ""

    raw_value = _safe_float(value, 0.0)
    sval = _format_number_for_bonus(value)

    def _repl(m):
        # Если первым значимым содержимым шаблона является этот плейсхолдер,
        # и значение положительное — добавляем "+" перед числом.
        #
        # Пример:
        #   "{0}% к Скорости бега" -> "+2% к Скорости бега"
        #
        # Если перед {0} уже есть знак, то второй плюс не добавляем.
        try:
            prefix = tpl[:m.start()]
            is_first_meaningful = prefix.strip() == ""

            if is_first_meaningful and raw_value > 0:
                return f"+{sval}"
        except Exception:
            pass

        return sval

    return __import__("re").sub(r"\{(\d+)\}", _repl, tpl).strip()


def _load_db_image_pixmap(conn, image_id: int) -> QPixmap:
    iid = _safe_int(image_id, 0)
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


class _AuraItemWidget(QFrame):
    clicked = Signal(int)
    checkbox_clicked = Signal(int, bool)

    def __init__(
            self,
            parent: Optional[QWidget],
            *,
            aura_id: int,
            kind: str,
            base_pm: QPixmap,
            active_pm: QPixmap,
            icon_pm: QPixmap,
            name: str,
            bonus_text: str,
            icon_rect: QRect,
            name_rect: QRect,
            bonus_rect: QRect,
            check_rect: Optional[QRect] = None,
    ):
        super().__init__(parent)

        self._aura_id = int(aura_id)
        self._kind = str(kind)
        self._base_pm = QPixmap(base_pm) if not base_pm.isNull() else QPixmap()
        self._active_pm = QPixmap(active_pm) if not active_pm.isNull() else QPixmap()
        self._icon_pm = QPixmap(icon_pm) if not icon_pm.isNull() else QPixmap()

        self._name = str(name or "")
        self._bonus_text = str(bonus_text or "")

        self._icon_rect = QRect(icon_rect)
        self._name_rect = QRect(name_rect)
        self._bonus_rect = QRect(bonus_rect)
        self._check_rect = QRect(check_rect) if isinstance(check_rect, QRect) else None

        self._hover = False
        self._pressed = False
        self._selected = False
        self._checked = False

        # прокрутка текста внутри областей
        self._name_scroll_y = 0
        self._bonus_scroll_y = 0

        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")

        if not self._base_pm.isNull():
            self._render_size = QSize(self._base_pm.size())
        elif not self._active_pm.isNull():
            self._render_size = QSize(self._active_pm.size())
        else:
            self._render_size = QSize(1, 1)

        self.setFixedSize(self._render_size)

    def aura_id(self) -> int:
        return int(self._aura_id)

    def set_selected(self, v: bool) -> None:
        nv = bool(v)
        if nv != self._selected:
            self._selected = nv
            self.update()

    def set_checked(self, v: bool) -> None:
        nv = bool(v)
        if nv != self._checked:
            self._checked = nv
            self.update()

    def _draw_wrapped_left_vcenter_text(
            self,
            p: QPainter,
            rect: QRect,
            text: str,
            *,
            font_px: int,
            color: QColor,
            bold: bool = False,
            scroll_y: int = 0,
    ) -> int:
        """
        Рисует текст в заданной области.
        Возвращает max_scroll_y для этой области.
        """
        if rect.isEmpty():
            return 0

        txt = _to_str(text).strip()
        if not txt:
            return 0

        f = QFont(p.font())
        f.setPixelSize(int(font_px))
        f.setBold(bool(bold))
        p.setFont(f)
        p.setPen(color)

        fm = QFontMetrics(f)
        flags = Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop

        measure_rect = QRect(0, 0, rect.width(), 100000)
        br = fm.boundingRect(measure_rect, flags, txt)

        text_h = max(1, br.height())
        max_scroll = max(0, int(text_h - rect.height()))

        p.save()
        p.setClipRect(rect)

        if max_scroll <= 0:
            draw_rect = QRect(rect)
            if text_h < rect.height():
                draw_rect.moveTop(rect.top() + (rect.height() - text_h) // 2)
        else:
            sy = max(0, min(int(scroll_y), int(max_scroll)))
            draw_rect = QRect(rect.left(), rect.top() - sy, rect.width(), text_h)

        p.drawText(draw_rect, flags, txt)
        p.restore()

        return int(max_scroll)

    def _text_max_scroll(
            self,
            rect: QRect,
            text: str,
            *,
            font_px: int,
            bold: bool = False,
    ) -> int:
        if rect.isEmpty():
            return 0

        txt = _to_str(text).strip()
        if not txt:
            return 0

        f = QFont(self.font())
        f.setPixelSize(int(font_px))
        f.setBold(bool(bold))

        fm = QFontMetrics(f)
        flags = Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop
        measure_rect = QRect(0, 0, rect.width(), 100000)
        br = fm.boundingRect(measure_rect, flags, txt)

        return max(0, int(br.height() - rect.height()))

    def _draw_text_scrollbar(
            self,
            p: QPainter,
            rect: QRect,
            *,
            scroll_y: int,
            max_scroll: int,
    ) -> None:
        if rect.isEmpty() or max_scroll <= 0:
            return

        track_margin = 2
        track_w = 4

        track_rect = QRect(
            rect.right() - track_w - track_margin,
            rect.top() + track_margin,
            track_w,
            max(8, rect.height() - track_margin * 2),
        )

        total_h = rect.height() + max_scroll
        if total_h <= 0:
            return

        thumb_h = int(round(track_rect.height() * (rect.height() / float(total_h))))
        thumb_h = max(16, min(track_rect.height(), thumb_h))

        max_thumb_offset = max(0, track_rect.height() - thumb_h)
        cur_scroll = max(0, min(int(scroll_y), int(max_scroll)))

        if max_scroll > 0 and max_thumb_offset > 0:
            thumb_offset = int(round((cur_scroll / float(max_scroll)) * max_thumb_offset))
        else:
            thumb_offset = 0

        thumb_rect = QRect(
            track_rect.left(),
            track_rect.top() + thumb_offset,
            track_rect.width(),
            thumb_h,
        )

        p.save()
        p.setPen(Qt.NoPen)

        # дорожка
        p.setBrush(QColor(0, 0, 0, 35))
        p.drawRoundedRect(track_rect, 2, 2)

        # бегунок
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawRoundedRect(thumb_rect, 2, 2)

        p.restore()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        use_active = bool(self._hover or self._selected)
        bg_pm = self._active_pm if use_active and (not self._active_pm.isNull()) else self._base_pm

        if not bg_pm.isNull():
            target_rect = QRect(0, 0, self.width(), self.height())
            if bg_pm.size() != target_rect.size():
                draw_pm = bg_pm.scaled(target_rect.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            else:
                draw_pm = bg_pm
            p.drawPixmap(target_rect.topLeft(), draw_pm)

        if not self._icon_pm.isNull() and not self._icon_rect.isEmpty():
            scaled = self._icon_pm.scaled(self._icon_rect.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(self._icon_rect, scaled)

        name_max_scroll = self._draw_wrapped_left_vcenter_text(
            p,
            self._name_rect,
            self._name,
            font_px=14,
            color=QColor("#000000"),
            bold=True,
            scroll_y=self._name_scroll_y,
        )

        bonus_max_scroll = self._draw_wrapped_left_vcenter_text(
            p,
            self._bonus_rect,
            self._bonus_text,
            font_px=13,
            color=QColor("#000000"),
            bold=False,
            scroll_y=self._bonus_scroll_y,
        )

        if name_max_scroll > 0:
            self._draw_text_scrollbar(
                p,
                self._name_rect,
                scroll_y=self._name_scroll_y,
                max_scroll=name_max_scroll,
            )

        if bonus_max_scroll > 0:
            self._draw_text_scrollbar(
                p,
                self._bonus_rect,
                scroll_y=self._bonus_scroll_y,
                max_scroll=bonus_max_scroll,
            )

        if self._kind == "general" and isinstance(self._check_rect, QRect) and not self._check_rect.isEmpty():
            box_rect = self._check_rect.adjusted(0, 0, -1, -1)

            # рамка чекбокса всегда одинаковая
            p.save()
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor("#8a7a52"))
            p.drawRect(box_rect)

            # если активно — рисуем только галочку, без заливки квадрата
            if self._checked:
                mark_pen = p.pen()
                mark_pen.setColor(QColor("#4b3d1f"))
                mark_pen.setWidth(2)
                mark_pen.setCapStyle(Qt.RoundCap)
                mark_pen.setJoinStyle(Qt.RoundJoin)
                p.setPen(mark_pen)

                x = box_rect.left()
                y = box_rect.top()
                w = box_rect.width()
                h = box_rect.height()

                p.drawLine(
                    QPoint(x + int(w * 0.20), y + int(h * 0.55)),
                    QPoint(x + int(w * 0.42), y + int(h * 0.78)),
                )
                p.drawLine(
                    QPoint(x + int(w * 0.42), y + int(h * 0.78)),
                    QPoint(x + int(w * 0.82), y + int(h * 0.22)),
                )

            p.restore()

        p.end()
        super().paintEvent(ev)

    def enterEvent(self, ev) -> None:
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(ev)

        was_pressed = self._pressed
        self._pressed = False

        if not was_pressed:
            ev.accept()
            return

        local_pos = ev.position().toPoint()
        over = self.rect().contains(local_pos)

        if over:
            if self._kind == "general" and isinstance(self._check_rect, QRect) and self._check_rect.contains(local_pos):
                nv = not bool(self._checked)
                self.checkbox_clicked.emit(int(self._aura_id), bool(nv))
            else:
                self.clicked.emit(int(self._aura_id))

        self.update()
        ev.accept()

    def wheelEvent(self, ev) -> None:
        pos = ev.position().toPoint()

        if self._name_rect.contains(pos):
            max_scroll = self._text_max_scroll(
                self._name_rect,
                self._name,
                font_px=14,
                bold=True,
            )
            if max_scroll > 0:
                step = 20 if ev.angleDelta().y() < 0 else -20
                self._name_scroll_y = max(0, min(max_scroll, int(self._name_scroll_y + step)))
                self.update()
                ev.accept()
                return

        if self._bonus_rect.contains(pos):
            max_scroll = self._text_max_scroll(
                self._bonus_rect,
                self._bonus_text,
                font_px=13,
                bold=False,
            )
            if max_scroll > 0:
                step = 20 if ev.angleDelta().y() < 0 else -20
                self._bonus_scroll_y = max(0, min(max_scroll, int(self._bonus_scroll_y + step)))
                self.update()
                ev.accept()
                return

        super().wheelEvent(ev)


class AuraMenu(QFrame):
    """
    Меню аур:
      - personal: личные ауры
      - general: групповые ауры
      - хранит выбранные ауры между открытиями
      - personal фильтруется по current_class_id/current_level
    """

    closed = Signal()
    tab_changed = Signal(str)
    selectionChanged = Signal()

    TAB_PERSONAL = "personal"
    TAB_GENERAL = "general"
    TABS = [TAB_PERSONAL, TAB_GENERAL]

    DEFAULT_SIZE: Tuple[int, int] = (691, 570)

    MENU_IMAGES: Dict[str, str] = {
        TAB_PERSONAL: r"resources/aura_menu/aura_menu_personal.png",
        TAB_GENERAL: r"resources/aura_menu/aura_menu_general.png",
    }

    CLOSE_ACTIVE_IMAGE = r"resources/helper_buttons/close_button_active.png"
    CLOSE2_IMAGE = r"resources/collection/close.png"

    PERSONAL_BLOCK_PATH = r"resources/aura_menu/personal_aura_block.png"
    PERSONAL_BLOCK_ACTIVE_PATH = r"resources/aura_menu/personal_aura_block_active.png"

    GENERAL_BLOCK_PATH = r"resources/aura_menu/general_aura_block.png"
    GENERAL_BLOCK_ACTIVE_PATH = r"resources/aura_menu/general_aura_block_active.png"

    @dataclass
    class LayoutConfig:
        menu_size: Tuple[int, int]
        tab_rects: Dict[str, QRect]
        close1_rect: QRect
        close2_rect: QRect
        list_rect: QRect

        personal_icon_rect: QRect
        personal_name_rect: QRect
        personal_bonus_rect: QRect

        general_icon_rect: QRect
        general_name_rect: QRect
        general_bonus_rect: QRect
        general_check_rect: QRect

    @staticmethod
    def default_layout() -> "AuraMenu.LayoutConfig":
        tab_rects = {
            AuraMenu.TAB_PERSONAL: QRect(92, 40, 95, 28),
            AuraMenu.TAB_GENERAL: QRect(188, 40, 93, 28),
        }

        close1 = QRect(654, 3, 24, 24)
        close2 = QRect(526, 520, 140, 32)

        return AuraMenu.LayoutConfig(
            menu_size=AuraMenu.DEFAULT_SIZE,
            tab_rects=tab_rects,
            close1_rect=close1,
            close2_rect=close2,
            list_rect=QRect(44, 120, 598, 361),

            personal_icon_rect=QRect(10, 35, 48, 48),
            personal_name_rect=QRect(71, 10, 195, 98),
            personal_bonus_rect=QRect(278, 10, 298, 98),

            general_icon_rect=QRect(10, 35, 48, 48),
            general_name_rect=QRect(71, 10, 195, 98),
            general_bonus_rect=QRect(278, 10, 230, 98),
            general_check_rect=QRect(534, 49, 20, 20),
        )

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        layout: Optional["AuraMenu.LayoutConfig"] = None,
        conn=None,
    ):
        super().__init__(parent)
        self.setObjectName("AuraMenu")

        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")

        self._layout = layout or self.default_layout()
        self._active_tab: str = self.TAB_PERSONAL
        self._conn = conn

        self._current_class_id: int = 0
        self._current_level: int = 1

        self._pixmaps: Dict[str, QPixmap] = {}
        self._db_image_cache: Dict[int, QPixmap] = {}
        self._close_active_pix: Optional[QPixmap] = None
        self._close2_pix: Optional[QPixmap] = None
        self._personal_block_pm: Optional[QPixmap] = None
        self._personal_block_active_pm: Optional[QPixmap] = None
        self._general_block_pm: Optional[QPixmap] = None
        self._general_block_active_pm: Optional[QPixmap] = None

        self._close1_down: bool = False
        self._close2_down: bool = False

        self._selected_personal_aura_id: int = 0

        # group auras: можно выбрать несколько
        self._selected_general_aura_ids: set[int] = set()

        # для каждой групповой ауры отдельно храним состояние галочки
        self._general_use_talents_by_aura: Dict[int, bool] = {}

        self._bg = QLabel(self)
        self._bg.setObjectName("AuraMenuBg")
        self._bg.setScaledContents(False)
        self._bg.setStyleSheet("background: transparent;")
        self._bg.setAutoFillBackground(False)

        self._tab_zones: Dict[str, QFrame] = {}
        self._build_tab_zones()

        self._close1 = QLabel(self)
        self._close2 = QLabel(self)
        self._build_close_zones()

        self._scrolls: Dict[str, QScrollArea] = {}
        self._containers: Dict[str, QWidget] = {}
        self._vboxes: Dict[str, QVBoxLayout] = {}
        self._build_scroll_areas()

        self._load_selection_state()
        self.apply_layout()
        self.set_tab(self.TAB_PERSONAL)

    # ---------------- public ----------------

    def set_player_context(self, class_id: Optional[int], level: Optional[int]) -> None:
        self._current_class_id = _safe_int(class_id, 0)
        self._current_level = max(1, _safe_int(level, 1))
        self._rebuild_visible_tab()

    def current_tab(self) -> str:
        return self._active_tab

    def selected_personal_aura_id(self) -> int:
        return int(self._selected_personal_aura_id)

    def selected_general_aura_id(self) -> int:
        """
        Оставлено для совместимости со старым кодом.
        Если выбрано несколько — вернём первый по возрастанию.
        """
        ids = sorted(int(x) for x in (self._selected_general_aura_ids or set()) if _safe_int(x, 0) > 0)
        return ids[0] if ids else 0

    def selected_general_aura_ids(self) -> List[int]:
        return sorted(int(x) for x in (self._selected_general_aura_ids or set()) if _safe_int(x, 0) > 0)

    def general_use_talents(self) -> bool:
        """
        Оставлено для совместимости со старым кодом.
        Вернёт True, если хотя бы у одной выбранной групповой ауры галочка включена.
        """
        mp = getattr(self, "_general_use_talents_by_aura", {}) or {}
        for aid in (self._selected_general_aura_ids or set()):
            if bool(mp.get(int(aid), False)):
                return True
        return False

    def general_use_talents_map(self) -> Dict[int, bool]:
        return {
            int(k): bool(v)
            for k, v in (getattr(self, "_general_use_talents_by_aura", {}) or {}).items()
            if _safe_int(k, 0) > 0
        }

    def set_tab(self, tab: str) -> None:
        tab = str(tab or "").strip().lower()
        if tab not in self.TABS:
            return

        self._active_tab = tab
        self._apply_background_for_tab(tab)
        self._apply_scroll_visibility(tab)
        self._rebuild_visible_tab()
        self.tab_changed.emit(tab)

    def apply_layout(self) -> None:
        try:
            mw, mh = self._layout.menu_size
            mw = int(mw)
            mh = int(mh)
        except Exception:
            mw, mh = self.DEFAULT_SIZE

        self.setFixedSize(mw, mh)
        self._bg.setGeometry(0, 0, self.width(), self.height())

        for tab, w in self._tab_zones.items():
            r = self._layout.tab_rects.get(tab)
            if isinstance(r, QRect):
                w.setGeometry(r)

        self._close1.setGeometry(self._layout.close1_rect)
        self._close2.setGeometry(self._layout.close2_rect)

        for sc in self._scrolls.values():
            sc.setGeometry(self._layout.list_rect)

        self._bg.lower()
        for w in self._tab_zones.values():
            w.raise_()
        for sc in self._scrolls.values():
            sc.raise_()
        self._close1.raise_()
        self._close2.raise_()

        self._apply_background_for_tab(self._active_tab)

    # ---------------- setup ----------------

    def _build_tab_zones(self) -> None:
        colors = {
            self.TAB_PERSONAL: "rgba(255, 0, 0, 0)",
            self.TAB_GENERAL: "rgba(0, 255, 0, 0)",
        }

        for tab in self.TABS:
            z = QFrame(self)
            z.setObjectName(f"aura_tab_zone_{tab}")
            z.setStyleSheet(
                f"background-color: {colors.get(tab, 'rgba(255,255,255,0)')}; "
                f"border: 1px solid rgba(0,0,0,0);"
            )
            z.setCursor(Qt.PointingHandCursor)
            z.installEventFilter(self)
            self._tab_zones[tab] = z

    def _build_close_zones(self) -> None:
        self._close1.setObjectName("aura_close_zone_1")
        self._close2.setObjectName("aura_close_zone_2")

        for w in (self._close1, self._close2):
            w.setStyleSheet("background: transparent; border: none;")
            w.setScaledContents(False)
            w.setCursor(Qt.PointingHandCursor)
            w.installEventFilter(self)

    def _build_scroll_areas(self) -> None:
        for tab in self.TABS:
            sc = QScrollArea(self)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setWidgetResizable(True)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sc.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            sc.setStyleSheet(
                "QScrollArea { border: none; background: transparent; }"
                "QScrollArea > QWidget { background: transparent; }"
                "QScrollArea > QWidget > QWidget { background: transparent; }"
            )
            try:
                sc.viewport().setStyleSheet("background: transparent; border: none;")
            except Exception:
                pass

            cont = QWidget()
            cont.setStyleSheet("background: transparent;")
            v = QVBoxLayout(cont)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)

            sc.setWidget(cont)
            self._scrolls[tab] = sc
            self._containers[tab] = cont
            self._vboxes[tab] = v

    # ---------------- resources ----------------

    def _get_db_conn(self):
        c = getattr(self, "_conn", None)
        if c is not None:
            return c

        p = self.parentWidget()
        seen = set()
        while p is not None and id(p) not in seen:
            seen.add(id(p))
            try:
                data = getattr(p, "data", None)
                conn = getattr(data, "conn", None)
                if conn is not None:
                    self._conn = conn
                    return conn
            except Exception:
                pass
            p = p.parentWidget()

        return None

    def _load_class_base_id(self, class_id: int) -> int:
        conn = self._get_db_conn()
        cid = _safe_int(class_id, 0)
        if conn is None or cid <= 0:
            return 0

        try:
            row = conn.execute(
                'SELECT Base_Id FROM "Class" WHERE Id=? LIMIT 1',
                (int(cid),),
            ).fetchone()
        except Exception:
            row = None

        if not row:
            return 0

        try:
            raw = row["Base_Id"] if hasattr(row, "keys") else row[0]
            return _safe_int(raw, 0)
        except Exception:
            return 0

    def _class_lineage_ids(self, class_id: int) -> List[int]:
        """
        Возвращает цепочку классов:
        [current_class_id, base_id, base_base_id, ...]
        """
        cid = _safe_int(class_id, 0)
        if cid <= 0:
            return []

        out: List[int] = []
        seen: set[int] = set()

        cur = int(cid)
        while cur > 0 and cur not in seen:
            seen.add(cur)
            out.append(int(cur))

            base_id = self._load_class_base_id(cur)
            if base_id <= 0:
                break

            cur = int(base_id)

        return out

    def _image_pm(self, image_id: int) -> QPixmap:
        iid = _safe_int(image_id, 0)
        if iid <= 0:
            return QPixmap()

        if iid in self._db_image_cache:
            return self._db_image_cache[iid]

        pm = _load_db_image_pixmap(self._get_db_conn(), iid)
        self._db_image_cache[iid] = pm
        return pm

    def _pixmap_for_tab(self, tab: str) -> QPixmap:
        tab = str(tab or "").strip().lower()
        if tab in self._pixmaps:
            return self._pixmaps[tab]

        path = self.MENU_IMAGES.get(tab, "")
        pm = QPixmap(_resolve_resource(path)) if path else QPixmap()
        self._pixmaps[tab] = pm
        return pm

    def _close_active_pixmap(self) -> QPixmap:
        if self._close_active_pix is not None:
            return self._close_active_pix
        self._close_active_pix = QPixmap(_resolve_resource(self.CLOSE_ACTIVE_IMAGE))
        return self._close_active_pix

    def _close2_pixmap(self) -> QPixmap:
        if self._close2_pix is not None:
            return self._close2_pix
        self._close2_pix = QPixmap(_resolve_resource(self.CLOSE2_IMAGE))
        return self._close2_pix

    def _personal_block_pixmap(self) -> QPixmap:
        if self._personal_block_pm is not None:
            return self._personal_block_pm
        self._personal_block_pm = QPixmap(_resolve_resource(self.PERSONAL_BLOCK_PATH))
        return self._personal_block_pm

    def _personal_block_active_pixmap(self) -> QPixmap:
        if self._personal_block_active_pm is not None:
            return self._personal_block_active_pm
        self._personal_block_active_pm = QPixmap(_resolve_resource(self.PERSONAL_BLOCK_ACTIVE_PATH))
        return self._personal_block_active_pm

    def _general_block_pixmap(self) -> QPixmap:
        if self._general_block_pm is not None:
            return self._general_block_pm
        self._general_block_pm = QPixmap(_resolve_resource(self.GENERAL_BLOCK_PATH))
        return self._general_block_pm

    def _general_block_active_pixmap(self) -> QPixmap:
        if self._general_block_active_pm is not None:
            return self._general_block_active_pm
        self._general_block_active_pm = QPixmap(_resolve_resource(self.GENERAL_BLOCK_ACTIVE_PATH))
        return self._general_block_active_pm

    def _apply_background_for_tab(self, tab: str) -> None:
        pm = self._pixmap_for_tab(tab)
        if pm.isNull():
            self._bg.clear()
            return
        self._bg.setPixmap(pm.scaled(self._bg.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

    def _apply_scroll_visibility(self, tab: str) -> None:
        for t, sc in self._scrolls.items():
            sc.setVisible(t == tab)

    def _get_active_talent_ids(self) -> List[int]:
        try:
            app = QApplication.instance()
            if app is None:
                return []

            raw = app.property("player_talents")
            if not isinstance(raw, list):
                return []

            ids: List[int] = []
            for row in raw:
                if not isinstance(row, dict):
                    continue
                tid = _safe_int(row.get("Talent_Id") or row.get("talent_id"), 0)
                if tid > 0:
                    ids.append(int(tid))

            return sorted(set(ids))
        except Exception:
            return []

    def _get_talent_aura_override_map(self, aura_id: int, *, shared: bool, selected_only: bool) -> Dict[int, float]:
        """
        selected_only=True  -> личные ауры: берём только TalentBonus от реально выбранных талантов
        selected_only=False -> групповые ауры: если включена галочка, берём ВСЕ TalentBonus этой ауры,
                               даже если сами таланты не выбраны

        Правило:
          - для личных аур одинаковые Type_Id суммируются
          - для групповых аур одинаковые Type_Id НЕ суммируются, а берётся максимум

        NoGroup:
          - если shared=True и TalentBonus.NoGroup=1, этот бонус не показывается
            и не должен попадать в override групповой ауры.
          - для личных аур NoGroup не режет бонус.
        """
        conn = self._get_db_conn()
        aid = _safe_int(aura_id, 0)
        if conn is None or aid <= 0:
            return {}

        has_no_group = False
        try:
            info = conn.execute('PRAGMA table_info("TalentBonus")').fetchall()
            for rr in info or []:
                try:
                    col_name = rr["name"] if hasattr(rr, "keys") else rr[1]
                except Exception:
                    col_name = ""
                if str(col_name or "").strip().lower() == "nogroup":
                    has_no_group = True
                    break
        except Exception:
            has_no_group = False

        no_group_select = ", NoGroup" if has_no_group else ", 0 AS NoGroup"

        sql = f"""
            SELECT Type_Id, Value, SharedValue{no_group_select}
            FROM TalentBonus
            WHERE AuraCondition_Id=?
              AND (BuffCondition_Id IS NULL OR BuffCondition_Id=0)
        """
        params: List[Any] = [int(aid)]

        if selected_only:
            talent_ids = self._get_active_talent_ids()
            if not talent_ids:
                return {}
            ph = ",".join(["?"] * len(talent_ids))
            sql += f" AND Talent_Id IN ({ph})"
            params.extend(int(x) for x in talent_ids)

        sql += " ORDER BY Id"

        try:
            rows = conn.execute(sql, tuple(params)).fetchall()
        except Exception:
            rows = []

        out: Dict[int, float] = {}

        # Только для групповых аур: берём максимум, а не сумму
        use_max_instead_of_sum = bool(shared) and (not bool(selected_only))

        for r in rows or []:
            try:
                if hasattr(r, "keys"):
                    type_id = _safe_int(r["Type_Id"], 0)
                    raw_value = r["Value"]
                    raw_shared = r["SharedValue"]
                    no_group = _safe_int(r["NoGroup"], 0)
                else:
                    type_id = _safe_int(r[0], 0)
                    raw_value = r[1]
                    raw_shared = r[2]
                    no_group = _safe_int(r[3], 0) if len(r) > 3 else 0
            except Exception:
                continue

            if type_id <= 0:
                continue

            # В групповых аурах TalentBonus.NoGroup=1 полностью игнорируем.
            if bool(shared) and int(no_group) == 1:
                continue

            if shared:
                if raw_shared is None:
                    eff_value = _safe_float(raw_value, 0.0)
                else:
                    eff_value = _safe_float(raw_shared, 0.0)
            else:
                eff_value = _safe_float(raw_value, 0.0)

            if abs(float(eff_value)) <= 1e-12:
                continue

            if use_max_instead_of_sum:
                prev = out.get(int(type_id), None)
                if prev is None:
                    out[int(type_id)] = float(eff_value)
                else:
                    out[int(type_id)] = max(float(prev), float(eff_value))
            else:
                out[int(type_id)] = float(out.get(int(type_id), 0.0)) + float(eff_value)

        return out

    def _get_aura_bonus_lines(self, aura_id: int, *, shared: bool, use_talent_overrides: bool = False,
                              selected_only: bool = True) -> List[str]:
        """
        shared=False -> для личных аур используем AuraBonus.Value
        shared=True  -> для групповых аур:
            - если AuraBonus.NoGroup=1 -> строку не показываем
            - если SharedValue IS NULL -> берём Value
            - если SharedValue == 0    -> строку не считаем
            - если SharedValue != 0    -> берём SharedValue

        use_talent_overrides=True:
            если есть TalentBonus с AuraCondition_Id == aura_id,
            то:
              - совпадающие Type_Id заменяют значения AuraBonus
              - новые Type_Id, которых нет в AuraBonus, тоже добавляются в список

        NoGroup действует только для групповых аур.
        """
        conn = self._get_db_conn()
        aid = _safe_int(aura_id, 0)
        if conn is None or aid <= 0:
            return []

        has_no_group = False
        try:
            info = conn.execute('PRAGMA table_info("AuraBonus")').fetchall()
            for rr in info or []:
                try:
                    col_name = rr["name"] if hasattr(rr, "keys") else rr[1]
                except Exception:
                    col_name = ""
                if str(col_name or "").strip().lower() == "nogroup":
                    has_no_group = True
                    break
        except Exception:
            has_no_group = False

        no_group_select = ", ab.NoGroup" if has_no_group else ", 0 AS NoGroup"

        try:
            rows = conn.execute(
                f"""
                SELECT ab.Type_Id, ab.Value, ab.SharedValue, ab.OrderIndex, bt.Template{no_group_select}
                FROM AuraBonus AS ab
                JOIN BonusType AS bt ON bt.Id = ab.Type_Id
                WHERE ab.Aura_Id=?
                ORDER BY ab.OrderIndex, ab.Type_Id
                """,
                (int(aid),),
            ).fetchall()
        except Exception:
            rows = []

        override_map: Dict[int, float] = {}
        if use_talent_overrides:
            try:
                override_map = self._get_talent_aura_override_map(int(aid), shared=shared, selected_only=selected_only)
            except Exception:
                override_map = {}

        out: List[str] = []
        used_override_type_ids: set[int] = set()
        blocked_group_type_ids: set[int] = set()

        for r in rows or []:
            try:
                if hasattr(r, "keys"):
                    type_id = _safe_int(r["Type_Id"], 0)
                    raw_value = r["Value"]
                    raw_shared = r["SharedValue"]
                    tpl = _to_str(r["Template"])
                    no_group = _safe_int(r["NoGroup"], 0)
                else:
                    type_id = _safe_int(r[0], 0)
                    raw_value = r[1]
                    raw_shared = r[2]
                    tpl = _to_str(r[4])
                    no_group = _safe_int(r[5], 0) if len(r) > 5 else 0
            except Exception:
                continue

            if type_id <= 0:
                continue

            # В групповой вкладке бонусы AuraBonus.NoGroup=1 не отрисовываем.
            # Запоминаем Type_Id, чтобы TalentBonus override не добавил эту же строку обратно.
            if bool(shared) and int(no_group) == 1:
                blocked_group_type_ids.add(int(type_id))
                continue

            # Если дальше в той же ауре есть обычная строка с этим Type_Id,
            # значит Type_Id не должен быть полностью заблокирован.
            if int(type_id) in blocked_group_type_ids:
                blocked_group_type_ids.discard(int(type_id))

            if use_talent_overrides and int(type_id) in override_map:
                eff_value = _safe_float(override_map.get(int(type_id)), 0.0)
                used_override_type_ids.add(int(type_id))
            else:
                if shared:
                    if raw_shared is None:
                        eff_value = _safe_float(raw_value, 0.0)
                    else:
                        eff_value = _safe_float(raw_shared, 0.0)
                else:
                    eff_value = _safe_float(raw_value, 0.0)

            if abs(float(eff_value)) <= 1e-12:
                continue

            txt = _format_bonus_template(tpl, eff_value)
            if txt:
                out.append(txt)

        extra_type_ids = [
            int(tid)
            for tid in override_map.keys()
            if int(tid) not in used_override_type_ids
               and int(tid) not in blocked_group_type_ids
        ]

        if extra_type_ids:
            ph = ",".join(["?"] * len(extra_type_ids))
            try:
                tpl_rows = conn.execute(
                    f"""
                    SELECT Id, Template
                    FROM BonusType
                    WHERE Id IN ({ph})
                    ORDER BY Id
                    """,
                    tuple(int(x) for x in extra_type_ids),
                ).fetchall()
            except Exception:
                tpl_rows = []

            tpl_map: Dict[int, str] = {}
            for rr in tpl_rows or []:
                try:
                    if hasattr(rr, "keys"):
                        bt_id = _safe_int(rr["Id"], 0)
                        tpl = _to_str(rr["Template"])
                    else:
                        bt_id = _safe_int(rr[0], 0)
                        tpl = _to_str(rr[1])
                except Exception:
                    continue
                if bt_id > 0 and tpl:
                    tpl_map[int(bt_id)] = str(tpl)

            for bt_id in extra_type_ids:
                eff_value = _safe_float(override_map.get(int(bt_id)), 0.0)
                if abs(float(eff_value)) <= 1e-12:
                    continue
                tpl = _to_str(tpl_map.get(int(bt_id))).strip()
                if not tpl:
                    continue
                txt = _format_bonus_template(tpl, eff_value)
                if txt:
                    out.append(txt)

        return out

    # ---------------- state ----------------

    def _load_selection_state(self) -> None:
        try:
            app = QApplication.instance()
            if app is None:
                return

            self._selected_personal_aura_id = _safe_int(app.property("player_personal_aura_id"), 0)

            # Новый формат
            raw_ids = app.property("player_general_aura_ids")
            ids: set[int] = set()
            if isinstance(raw_ids, (list, tuple, set)):
                for x in raw_ids:
                    v = _safe_int(x, 0)
                    if v > 0:
                        ids.add(int(v))

            raw_map = app.property("player_general_aura_use_talents_map")
            mp: Dict[int, bool] = {}
            if isinstance(raw_map, dict):
                for k, v in raw_map.items():
                    aid = _safe_int(k, 0)
                    if aid > 0:
                        mp[int(aid)] = bool(v)

            # backward compatibility со старым одиночным форматом
            if not ids:
                old_id = _safe_int(app.property("player_general_aura_id"), 0)
                if old_id > 0:
                    ids.add(int(old_id))

            if not mp:
                old_flag = bool(app.property("player_general_aura_use_talents"))
                for aid in ids:
                    mp[int(aid)] = bool(old_flag)

            self._selected_general_aura_ids = set(ids)
            self._general_use_talents_by_aura = dict(mp)

        except Exception:
            pass

    def _publish_selection_state(self) -> None:
        try:
            app = QApplication.instance()
            if app is not None:
                app.setProperty("player_personal_aura_id", int(self._selected_personal_aura_id))

                ids = sorted(int(x) for x in (self._selected_general_aura_ids or set()) if _safe_int(x, 0) > 0)
                app.setProperty("player_general_aura_ids", list(ids))

                mp = {
                    int(k): bool(v)
                    for k, v in (self._general_use_talents_by_aura or {}).items()
                    if _safe_int(k, 0) > 0
                }
                app.setProperty("player_general_aura_use_talents_map", dict(mp))

                app.setProperty("player_general_aura_id", ids[0] if ids else 0)
                any_checked = any(bool(mp.get(int(aid), False)) for aid in ids)
                app.setProperty("player_general_aura_use_talents", bool(any_checked))
        except Exception:
            pass

        try:
            self.selectionChanged.emit()
        except Exception:
            pass

        try:
            host = self.parentWidget()
            seen = set()
            while host is not None and id(host) not in seen:
                seen.add(id(host))
                fn = getattr(host, "refresh_stats_panel", None)
                if callable(fn):
                    fn()
                    break
                host = host.parentWidget()
        except Exception:
            pass

    # ---------------- data ----------------

    def _query_personal_auras(self) -> List[dict]:
        conn = self._get_db_conn()
        if conn is None:
            return []

        cid = int(self._current_class_id)
        lvl = int(self._current_level)

        if cid <= 0 or lvl <= 0:
            return []

        lineage = self._class_lineage_ids(cid)
        if not lineage:
            lineage = [int(cid)]

        ph = ",".join(["?"] * len(lineage))

        try:
            rows = conn.execute(
                f"""
                SELECT Id, Name, Class_Id, Level, Image_Id
                FROM Aura
                WHERE Class_Id IN ({ph}) AND Level<=?
                ORDER BY Level, Name, Id
                """,
                tuple(int(x) for x in lineage) + (int(lvl),),
            ).fetchall()
        except Exception:
            rows = []

        out: List[dict] = []
        for r in rows or []:
            try:
                if hasattr(r, "keys"):
                    out.append(
                        {
                            "Id": _safe_int(r["Id"], 0),
                            "Name": _to_str(r["Name"]),
                            "Class_Id": _safe_int(r["Class_Id"], 0),
                            "Level": _safe_int(r["Level"], 0),
                            "Image_Id": _safe_int(r["Image_Id"], 0),
                        }
                    )
                else:
                    out.append(
                        {
                            "Id": _safe_int(r[0], 0),
                            "Name": _to_str(r[1]),
                            "Class_Id": _safe_int(r[2], 0),
                            "Level": _safe_int(r[3], 0),
                            "Image_Id": _safe_int(r[4], 0),
                        }
                    )
            except Exception:
                continue

        return [x for x in out if _safe_int(x.get("Id"), 0) > 0]

    def _query_general_auras(self) -> List[dict]:
        conn = self._get_db_conn()
        if conn is None:
            return []

        try:
            rows = conn.execute(
                """
                SELECT Id, Name, Class_Id, Level, Image_Id
                FROM Aura
                ORDER BY Level, Name, Id
                """
            ).fetchall()
        except Exception:
            rows = []

        out: List[dict] = []
        for r in rows or []:
            try:
                if hasattr(r, "keys"):
                    out.append(
                        {
                            "Id": _safe_int(r["Id"], 0),
                            "Name": _to_str(r["Name"]),
                            "Class_Id": _safe_int(r["Class_Id"], 0),
                            "Level": _safe_int(r["Level"], 0),
                            "Image_Id": _safe_int(r["Image_Id"], 0),
                        }
                    )
                else:
                    out.append(
                        {
                            "Id": _safe_int(r[0], 0),
                            "Name": _to_str(r[1]),
                            "Class_Id": _safe_int(r[2], 0),
                            "Level": _safe_int(r[3], 0),
                            "Image_Id": _safe_int(r[4], 0),
                        }
                    )
            except Exception:
                continue

        return [x for x in out if _safe_int(x.get("Id"), 0) > 0]

    # ---------------- list build ----------------

    def _clear_layout(self, lay: QVBoxLayout) -> None:
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                try:
                    w.setParent(None)
                except Exception:
                    pass
                try:
                    w.deleteLater()
                except Exception:
                    pass

    def _rebuild_visible_tab(self) -> None:
        if self._active_tab == self.TAB_PERSONAL:
            self._rebuild_personal()
        else:
            self._rebuild_general()

    def _rebuild_personal(self) -> None:
        lay = self._vboxes.get(self.TAB_PERSONAL)
        if lay is None:
            return

        self._clear_layout(lay)

        rows = self._query_personal_auras()

        prepared_rows: List[dict] = []
        visible_ids: set[int] = set()

        for row in rows:
            if not isinstance(row, dict):
                continue

            aura_id = _safe_int(row.get("Id"), 0)
            if aura_id <= 0:
                continue

            bonus_lines = self._get_aura_bonus_lines(
                aura_id,
                shared=False,
                use_talent_overrides=True,
                selected_only=True,
            )
            if not bonus_lines:
                continue

            rr = dict(row)
            rr["_bonus_lines"] = list(bonus_lines)
            prepared_rows.append(rr)
            visible_ids.add(int(aura_id))

        if self._selected_personal_aura_id > 0 and int(self._selected_personal_aura_id) not in visible_ids:
            self._selected_personal_aura_id = 0
            self._publish_selection_state()

        base_pm = self._personal_block_pixmap()
        active_pm = self._personal_block_active_pixmap()

        for row in prepared_rows:
            aura_id = _safe_int(row.get("Id"), 0)
            if aura_id <= 0:
                continue

            icon_pm = self._image_pm(_safe_int(row.get("Image_Id"), 0))
            bonus_text = "\n".join(_to_str(x) for x in (row.get("_bonus_lines") or []) if _to_str(x).strip())

            w = _AuraItemWidget(
                self._containers.get(self.TAB_PERSONAL),
                aura_id=int(aura_id),
                kind="personal",
                base_pm=base_pm,
                active_pm=active_pm,
                icon_pm=icon_pm,
                name=_to_str(row.get("Name")),
                bonus_text=bonus_text,
                icon_rect=self._layout.personal_icon_rect,
                name_rect=self._layout.personal_name_rect,
                bonus_rect=self._layout.personal_bonus_rect,
                check_rect=None,
            )
            w.set_selected(int(aura_id) == int(self._selected_personal_aura_id))
            try:
                w.clicked.connect(self._on_personal_aura_clicked)
            except Exception:
                pass

            lay.addWidget(w, alignment=Qt.AlignTop | Qt.AlignLeft)

        lay.addStretch(1)

    def _rebuild_general(self) -> None:
        lay = self._vboxes.get(self.TAB_GENERAL)
        if lay is None:
            return

        self._clear_layout(lay)

        rows = self._query_general_auras()

        prepared_rows: List[dict] = []
        visible_ids: set[int] = set()

        for row in rows:
            if not isinstance(row, dict):
                continue

            aura_id = _safe_int(row.get("Id"), 0)
            if aura_id <= 0:
                continue

            use_talent_overrides = bool(self._general_use_talents_by_aura.get(int(aura_id), False))

            bonus_lines = self._get_aura_bonus_lines(
                aura_id,
                shared=True,
                use_talent_overrides=use_talent_overrides,
                selected_only=False,
            )
            if not bonus_lines:
                continue

            rr = dict(row)
            rr["_bonus_lines"] = list(bonus_lines)
            prepared_rows.append(rr)
            visible_ids.add(int(aura_id))

        self._selected_general_aura_ids = {
            int(aid)
            for aid in (self._selected_general_aura_ids or set())
            if int(aid) in visible_ids
        }

        self._general_use_talents_by_aura = {
            int(aid): bool(v)
            for aid, v in (self._general_use_talents_by_aura or {}).items()
            if int(aid) in visible_ids
        }

        base_pm = self._general_block_pixmap()
        active_pm = self._general_block_active_pixmap()

        for row in prepared_rows:
            aura_id = _safe_int(row.get("Id"), 0)
            if aura_id <= 0:
                continue

            icon_pm = self._image_pm(_safe_int(row.get("Image_Id"), 0))
            bonus_text = "\n".join(_to_str(x) for x in (row.get("_bonus_lines") or []) if _to_str(x).strip())

            w = _AuraItemWidget(
                self._containers.get(self.TAB_GENERAL),
                aura_id=int(aura_id),
                kind="general",
                base_pm=base_pm,
                active_pm=active_pm,
                icon_pm=icon_pm,
                name=_to_str(row.get("Name")),
                bonus_text=bonus_text,
                icon_rect=self._layout.general_icon_rect,
                name_rect=self._layout.general_name_rect,
                bonus_rect=self._layout.general_bonus_rect,
                check_rect=self._layout.general_check_rect,
            )

            is_selected = int(aura_id) in self._selected_general_aura_ids
            is_checked = bool(self._general_use_talents_by_aura.get(int(aura_id), False))

            w.set_selected(bool(is_selected))
            w.set_checked(bool(is_checked))

            try:
                w.clicked.connect(self._on_general_aura_clicked)
            except Exception:
                pass
            try:
                w.checkbox_clicked.connect(self._on_general_aura_checkbox_clicked)
            except Exception:
                pass

            lay.addWidget(w, alignment=Qt.AlignTop | Qt.AlignLeft)

        lay.addStretch(1)

    # ---------------- interactions ----------------

    def _on_personal_aura_clicked(self, aura_id: int) -> None:
        aid = _safe_int(aura_id, 0)
        if aid <= 0:
            return

        if int(self._selected_personal_aura_id) == int(aid):
            self._selected_personal_aura_id = 0
        else:
            self._selected_personal_aura_id = int(aid)

        self._publish_selection_state()
        self._rebuild_personal()

    def _on_general_aura_clicked(self, aura_id: int) -> None:
        aid = _safe_int(aura_id, 0)
        if aid <= 0:
            return

        if int(aid) in self._selected_general_aura_ids:
            self._selected_general_aura_ids.discard(int(aid))
            self._general_use_talents_by_aura.pop(int(aid), None)
        else:
            self._selected_general_aura_ids.add(int(aid))
            self._general_use_talents_by_aura.setdefault(int(aid), False)

        self._publish_selection_state()
        self._rebuild_general()

    def _on_general_aura_checkbox_clicked(self, aura_id: int, checked: bool) -> None:
        aid = _safe_int(aura_id, 0)
        if aid <= 0:
            return

        # Чекбокс только переключает использование talent override
        # и НЕ выбирает сам блок ауры.
        self._general_use_talents_by_aura[int(aid)] = bool(checked)

        self._publish_selection_state()
        self._rebuild_general()

    # ---------------- close visuals ----------------

    def _reset_close_visuals(self) -> None:
        self._close1_down = False
        self._close2_down = False
        try:
            self._close1.clear()
        except Exception:
            pass
        try:
            self._close2.clear()
        except Exception:
            pass

    # ---------------- event filter ----------------

    def eventFilter(self, watched, event) -> bool:
        et = event.type()

        def _is_over_widget(w: QWidget) -> bool:
            try:
                gp = event.globalPosition().toPoint()
            except Exception:
                try:
                    gp = event.globalPos()
                except Exception:
                    return False
            try:
                lp = w.mapFromGlobal(gp)
            except Exception:
                return False
            return w.rect().contains(lp)

        if watched in self._tab_zones.values():
            if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                watched.setProperty("_pressed_down", True)
                return True

            if et == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                was_down = bool(watched.property("_pressed_down"))
                watched.setProperty("_pressed_down", False)

                if was_down and _is_over_widget(watched):
                    for tab, w in self._tab_zones.items():
                        if w is watched:
                            self.set_tab(tab)
                            return True
                return True

            if et in (QEvent.Leave, QEvent.HoverLeave):
                return False

            return False

        if watched is self._close1:
            if et == QEvent.Enter:
                pm = self._close_active_pixmap()
                if not pm.isNull():
                    watched.setPixmap(pm.scaled(watched.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
                return False

            if et == QEvent.Leave:
                if not self._close1_down:
                    watched.clear()
                return False

            if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._close1_down = True
                pm = self._close_active_pixmap()
                if not pm.isNull():
                    watched.setPixmap(pm.scaled(watched.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
                return True

            if et == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                was_down = self._close1_down
                self._close1_down = False
                over = _is_over_widget(watched)

                watched.clear()

                if was_down and over:
                    self._reset_close_visuals()
                    self.closed.emit()
                return True

            return False

        if watched is self._close2:
            if et == QEvent.Enter:
                pm = self._close2_pixmap()
                if not pm.isNull():
                    watched.setPixmap(pm.scaled(watched.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
                return False

            if et == QEvent.Leave:
                watched.clear()
                return False

            if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._close2_down = True
                pm = self._close2_pixmap()
                if not pm.isNull():
                    watched.setPixmap(pm.scaled(watched.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
                return True

            if et == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                was_down = self._close2_down
                self._close2_down = False
                over = _is_over_widget(watched)
                watched.clear()
                if was_down and over:
                    self._reset_close_visuals()
                    self.closed.emit()
                return True

            return False

        return super().eventFilter(watched, event)


class AuraMenuWindow(QFrame):
    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None, *, layout: Optional["AuraMenu.LayoutConfig"] = None):
        super().__init__(parent)
        self.setObjectName("AuraMenuWindow")

        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")

        self._drag_pos: Optional[QPoint] = None
        self._last_pos: Optional[QPoint] = None

        self._conn = getattr(getattr(parent, "data", None), "conn", None)

        self.menu = AuraMenu(self, layout=layout, conn=self._conn)
        self.menu.move(0, 0)
        self.menu.show()

        try:
            self.menu.closed.connect(self.close)
        except Exception:
            pass

        self.setFixedSize(self.menu.size())

        try:
            self.menu.installEventFilter(self)
            if hasattr(self.menu, "_bg") and self.menu._bg is not None:
                self.menu._bg.installEventFilter(self)
        except Exception:
            pass

    def open_centered(self, parent: Optional[QWidget] = None) -> None:
        host = parent if isinstance(parent, QWidget) else self.parentWidget()

        try:
            if hasattr(self, "menu") and self.menu is not None:
                self.menu._reset_close_visuals()
        except Exception:
            pass

        try:
            if host is not None:
                cid = 0
                lvl = 1
                if hasattr(host, "_current_class_id"):
                    cid = _safe_int(host._current_class_id(), 0)
                if hasattr(host, "level_spin") and host.level_spin is not None:
                    lvl = max(1, _safe_int(host.level_spin.value(), 1))
                self.menu.set_player_context(cid, lvl)
        except Exception:
            pass

        if isinstance(self._last_pos, QPoint):
            try:
                self.move(self._last_pos)
            except Exception:
                pass
        else:
            if host is not None:
                try:
                    host_geo = host.frameGeometry()
                    x = int(host_geo.center().x() - self.width() / 2)
                    y = int(host_geo.center().y() - self.height() / 2)
                    self.move(x, y)
                except Exception:
                    pass

        self.show()
        self.raise_()
        try:
            self.activateWindow()
        except Exception:
            pass

    def eventFilter(self, watched, event) -> bool:
        et = event.type()

        def _pos_in_menu() -> Optional[QPoint]:
            try:
                gp = event.globalPosition().toPoint()
            except Exception:
                try:
                    gp = event.globalPos()
                except Exception:
                    return None

            try:
                lp = event.position().toPoint()
            except Exception:
                try:
                    lp = event.pos()
                except Exception:
                    return None

            try:
                return watched.mapTo(self.menu, lp)
            except Exception:
                try:
                    return self.menu.mapFromGlobal(gp)
                except Exception:
                    return None

        def _can_start_drag(p: QPoint) -> bool:
            lay = getattr(self.menu, "_layout", None)
            if lay is None:
                return False

            try:
                if lay.close1_rect.contains(p) or lay.close2_rect.contains(p):
                    return False
            except Exception:
                pass

            try:
                for r in lay.tab_rects.values():
                    if r.contains(p):
                        return False
            except Exception:
                pass

            return True

        if watched is self.menu or watched is getattr(self.menu, "_bg", None):
            if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                p = _pos_in_menu()
                if p is not None and _can_start_drag(p):
                    try:
                        gp = event.globalPosition().toPoint()
                    except Exception:
                        gp = event.globalPos()
                    self._drag_pos = gp - self.frameGeometry().topLeft()
                    return True

            if et == QEvent.MouseMove and self._drag_pos is not None:
                try:
                    gp = event.globalPosition().toPoint()
                except Exception:
                    gp = event.globalPos()
                self.move(gp - self._drag_pos)
                return True

            if et == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._drag_pos = None
                try:
                    self._last_pos = QPoint(self.pos())
                except Exception:
                    pass
                return False

        return super().eventFilter(watched, event)

    def closeEvent(self, event) -> None:
        try:
            self._last_pos = QPoint(self.pos())
        except Exception:
            pass

        try:
            self.closed.emit()
        except Exception:
            pass

        super().closeEvent(event)