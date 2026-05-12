#stamp_window.py
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from pickle import GLOBAL
from typing import Dict, Tuple, Optional, List, Iterable, Any

from PySide6.QtCore import Qt, QRect, QPoint, Signal, QSize, QEvent, QTimer
from PySide6.QtGui import QPixmap, QIcon, QPainter, QColor, QImage
from PySide6.QtWidgets import (
    QWidget, QLabel, QToolButton, QApplication,
    QGridLayout, QFrame, QHBoxLayout, QVBoxLayout, QScrollArea, QSizePolicy, QLineEdit
)

import inspect
# бонусные строки (как в main/reforge)
from .weapon_equipment_button import _render_bonus_lines as _render_bonus_lines_helper, ImageVScrollBar, \
    _find_scroll_dir  # type: ignore
from .choose_menu_all import ChooseMenuAll, ChooseMenuConfig, ChooseStampMenu, StampChooseConfig, _MiniVScroll

# ============ UI CONFIG ============
STAMP_UI: Dict[str, object] = {
    "window_size": (858, 510),
    "bg_path": "resources/stamp_menu/bg_stamp.png",
    "bg_path_chosen": "resources/stamp_menu/bg_stamp_choose.png",
    "buttons": {
        "close": {"rect": (767, 23, 24, 24),
                  "icon_hover": "resources/helper_buttons/close_button_active.png"},
    },
    "areas": {
        "pick_item":            {"rect": (137, 255, 48, 48),    "cols": 4, "icon_px": 56 , "hgap": 8, "vgap": 8},
        "pick_stamp":           {"rect": (224, 187, 48, 48),    "cols": 3, "icon_px": 56 , "hgap": 8, "vgap": 8},
        "pick_arcon":           {"rect": (308, 325, 48, 48),    "cols": 3, "icon_px": 56 , "hgap": 8, "vgap": 8},
        "stamp_color_preview":  {"rect": (543, 181, 197, 197),  "cols": 1, "icon_px": 195, "hgap": 0, "vgap": 0},
        "out_stamp":            {"rect": (616, 255, 48, 48),    "cols": 4, "icon_px": 56 , "hgap": 8, "vgap": 8},
        "stamp_details":        {"rect": (290, 115, 260, 130),  "cols": 1, "icon_px": 0 ,  "hgap": 0, "vgap": 0},
    },
    "glow_icon_path": "resources/stamp_menu/blue_icon.png",
    "glows": [
        {"rect": (167, 129, 163, 163), "speed_deg_per_sec": 5},
        {"rect": (251, 267, 163, 163), "speed_deg_per_sec": 5},
    ],
    "color_circles": [
        {"x": 364, "y": 332, "diameter": 28, "color_id": 0},
        {"x": 403, "y": 332, "diameter": 28, "color_id": 1},
        {"x": 440, "y": 332, "diameter": 28, "color_id": 2},
        {"x": 479, "y": 332, "diameter": 28, "color_id": 3},
        {"x": 516, "y": 332, "diameter": 28, "color_id": 4},
    ],
}

STAMP_COLOR_ICON = {
    1: "resources/stamp_menu/stamp_green.png",
    2: "resources/stamp_menu/stamp_blue.png",
    3: "resources/stamp_menu/stamp_purple.png",
    4: "resources/stamp_menu/stamp_orange.png",
}

_EXCLUDE_SLOTS = {"costume", "ornament", "mount"}

STAMP_COLOR_META = {
    1: {"hex": "#32CD32", "icon_img_id": 896},
    2: {"hex": "#4169E1", "icon_img_id": 897},
    3: {"hex": "#8A2BE2", "icon_img_id": 898},
    4: {"hex": "#FF9600", "icon_img_id": 899},
}

GEM_PATHS = {"C": "resources/stamp_menu/Изумруд.png",
             "B": "resources/stamp_menu/Сапфир.png",
             "A": "resources/stamp_menu/Морион.png"}
ARCON_PATH = "resources/stamp_menu/Arcon.png"

def _resolve_resource(rel: str) -> str:
    p = Path(rel)
    for c in (Path.cwd() / p,
              Path(__file__).resolve().parents[2] / p,
              Path(__file__).resolve().parents[3] / p):
        if c.exists():
            return str(c)
    return str(p)

def _load_file_image(path: str) -> QPixmap | None:
    pm = QPixmap(path)
    return pm if not pm.isNull() else None

def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower().replace("ё", "е")

def _to_int(val, default=0) -> int:
    try: return int(val)
    except Exception: return default

def _to_float(val, default=0.0) -> float:
    try: return float(val)
    except Exception: return default


# ============ ROTATING GLOW ============
class _RotatingGlow(QWidget):
    def __init__(self, parent: QWidget, pixmap: Optional[QPixmap], speed_deg_per_sec: float = 60.0):
        super().__init__(parent)
        self._pm = pixmap if (pixmap and not pixmap.isNull()) else None
        self._speed = float(speed_deg_per_sec)
        self._angle = 0.0
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(16)
        self.hide()

    def setPixmap(self, pm: Optional[QPixmap]): self._pm = pm if (pm and not pm.isNull()) else None; self.update()
    def setSpeed(self, deg_per_sec: float): self._speed = float(deg_per_sec)
    def _on_tick(self): self._angle = (self._angle + self._speed * 0.016) % 360.0; self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        rect = self.rect()
        p.translate(rect.center()); p.rotate(self._angle); p.translate(-rect.center())
        if self._pm:
            p.drawPixmap(rect, self._pm)
        else:
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 150, 255, 120))
            d = min(rect.width(), rect.height())
            r = QRect(rect.center().x() - d//2, rect.center().y() - d//2, d, d)
            p.drawEllipse(r)


# ============ MAIN WINDOW ============
class StampWindow(QWidget):
    closed = Signal()
    stampSaved = Signal(int, dict)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.CustomizeWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

        # ---- базовые размеры/фон ----
        w, h = STAMP_UI.get("window_size", (858, 510))
        self._target_size = QSize(int(w), int(h))

        self._bg_default = _load_file_image(_resolve_resource(STAMP_UI["bg_path"]))
        self._bg_chosen  = _load_file_image(_resolve_resource(STAMP_UI["bg_path_chosen"]))
        self._bg_current: Optional[QPixmap] = self._bg_default

        self.bg_label = QLabel(self)
        self.bg_label.setScaledContents(True)

        # ---- состояние класса игрока ----
        self._player_class_raw: Optional[str] = None
        self._player_class_id: Optional[int] = None
        self._player_class_bucket: str = "unknown"

        # ---- служебные контейнеры (создаём заранее) ----
        self._glow_widgets: List[_RotatingGlow] = []
        self._color_buttons: List[QToolButton] = []

        # areas/slots
        self._area_widgets: Dict[str, QWidget] = {}
        self._pick_item_slot: Optional[QLabel] = None
        self._pick_stamp_slot: Optional[QLabel] = None
        self._pick_arcon_slot: Optional[QLabel] = None
        self._color_preview_slot: Optional[QLabel] = None
        self._out_stamp_slot: Optional[QLabel] = None

        # ---- кнопки окна ----
        self._buttons: Dict[str, QToolButton] = {}
        self._build_buttons()

        # ---- области (pick_item / pick_stamp / …) ----
        self._build_areas()

        # ---- правый борд с названием печати и бонусами ----
        # (теперь areas уже есть, поэтому _build_stamp_details_board не падает)
        self._details_frame: Optional[QFrame] = None
        self._details_title: Optional[QLabel] = None
        self._details_bonuses: Optional[QLabel] = None
        self._build_stamp_details_board()


        # ---- попапы выбора предмета/печати ----
        self._pick_popup: Optional[QFrame] = None
        self._pick_grid: Optional[QGridLayout] = None
        self._make_pick_item_popup()
        # ---- новое меню выбора экипировки (24 слота) ----
        self._choose_menu_all: Optional[ChooseMenuAll] = ChooseMenuAll(self, config=ChooseMenuConfig())
        # ---- меню выбора печатей (фон stamp_choose.png) ----
        self._choose_stamp_menu: Optional[ChooseStampMenu] = ChooseStampMenu(self, config=StampChooseConfig())

        self._stamp_popup: Optional[QFrame] = None
        self._stamp_area: Optional[QScrollArea] = None
        self._stamp_list_box: Optional[QVBoxLayout] = None
        self._stamp_search_edit: Optional[QLineEdit] = None
        self._stamp_search_text: str = ""
        self._make_pick_stamp_popup()

        # штатные полосы скрываем — используем картинковый
        self._stamp_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._stamp_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # шаги прокрутки (колесо/страница)
        vb = self._stamp_area.verticalScrollBar()
        vb.setSingleStep(24)
        vb.setPageStep(120)

        # === кастомный вертикальный скроллбар как в weapon_equipment_button ===
        self._sv_custom = ImageVScrollBar(
            self._stamp_area.verticalScrollBar(),
            _find_scroll_dir(),
            parent=self._stamp_popup,
        )
        self._sv_custom.hide()

        # показывать/прятать полосу в зависимости от диапазона
        vb = self._stamp_area.verticalScrollBar()
        vb.rangeChanged.connect(lambda _a, _b: self._sv_custom.setVisible(vb.maximum() > 0))

        # чтобы полоса правильно вставала при отрисовке/ресайзе
        QTimer.singleShot(0, lambda: self._place_stamp_vscroll())
        self._stamp_popup.installEventFilter(self)

        # ---- текущее выделение/сохранённые печати ----
        self._picked_slot_key: Optional[str] = None
        self._picked_item: Optional[dict] = None
        self._picked_item_id: Optional[int] = None
        self._picked_instance_guid: Optional[str] = None  # ← НОВОЕ
        self._chosen_stamp: Optional[dict] = None
        self._applied_stamps: dict[int, dict] = {}
        self._applied_stamps_by_inst: dict[str, dict] = {}  # ← НОВОЕ (кэш по InstanceGuid)

        # ---- позиция для перетаскивания окна ----
        self._drag_pos: Optional[QPoint] = None

        self._applied_stamps: dict[str, dict] = {}

        # --- element badge cache (как в reforge.py) ---
        self._element_badge_cache: dict[int, QPixmap] = {}

        # опционально: если у тебя уже есть image_loader, оставь как есть;
        # если нет — будем брать parent.data.get_image_bytes
        if not hasattr(self, "_image_loader"):
            self._image_loader = None

        # ---- свечение и круги выбора цвета ----
        self._build_glows()
        self._selected_color_id: int = 0
        self._build_color_circles()
        self._update_color_buttons_enabled()
        self._wire_area_handlers()

        # ---- применяем фон и поднимаем слои ----
        self._apply_background()

        self._last_tip_anchor: Optional[QWidget] = None
        self._tip_last_sig = None
        self._tip_last_t = 0.0

    # =======================
    #  ELEMENT BADGE (как в reforge.py)
    # =======================

    def _db_conn(self):
        parent = self.parent()
        data = getattr(parent, "data", None) if parent else None
        return getattr(data, "conn", None)

    def _element_id_for_item(self, item):
        if not isinstance(item, dict):
            return None
        for k in ("Element_Id", "ElementId", "Element_Type_Id", "ElementType_Id"):
            v = item.get(k)
            if v is not None:
                try:
                    return int(v)
                except Exception:
                    pass
        return None

    def _element_badge_image_id_for_item(self, item):
        """
        Как в reforge.py:
        1) если item содержит ToolTipImage_Id — берём его
        2) иначе Element_Id -> CardType.ToolTipImage_Id (или CardType.Image_Id)
        """
        if not isinstance(item, dict):
            return None

        def _toi(v) -> int:
            try:
                return int(v)
            except Exception:
                return 0

        direct = _toi(
            item.get("ToolTipImage_Id")
            or item.get("TooltipImage_Id")
            or item.get("ToolTip_Image_Id")
            or item.get("Tooltip_Image_Id")
        )
        if direct > 0:
            return direct

        elem_id = _toi(item.get("Element_Id") or item.get("ElementId") or 0)
        if elem_id > 0:
            return self._db_element_badge_image_id(elem_id)

        ct_id = _toi(item.get("CardType_Id") or item.get("CardTypeId") or item.get("Type_Id") or item.get("TypeId"))
        if ct_id > 0:
            return self._db_element_badge_image_id(ct_id)

        return None

    def _db_element_badge_image_id(self, cardtype_or_element_id: int):
        """
        Берём картинку бейджа:
        предпочитаем CardType.ToolTipImage_Id, иначе CardType.Image_Id.
        cardtype_or_element_id может быть CardType.Id ИЛИ CardType.Element_Id.
        """
        try:
            x = int(cardtype_or_element_id)
        except Exception:
            return None
        if x <= 0:
            return None

        conn = self._db_conn()
        if conn is None:
            return None

        def _pick(row):
            if not row:
                return None
            try:
                if hasattr(row, "keys"):
                    tti = row["ToolTipImage_Id"] if "ToolTipImage_Id" in row.keys() else None
                    imi = row["ToolTipImage_Id"] if "Image_Id" in row.keys() else None
                else:
                    tti, imi = row[0], row[1]
            except Exception:
                return None

            val = tti if tti else imi
            try:
                return int(val) if val else None
            except Exception:
                return None

        # 1) считаем, что x = CardType.Id
        try:
            row = conn.execute(
                "SELECT ToolTipImage_Id, Image_Id FROM CardType WHERE Id=? LIMIT 1",
                (x,),
            ).fetchone()
            got = _pick(row)
            if got:
                return got
        except Exception:
            pass

        # 2) считаем, что x = Element_Id
        try:
            row = conn.execute(
                "SELECT ToolTipImage_Id, Image_Id FROM CardType WHERE Element_Id=? LIMIT 1",
                (x,),
            ).fetchone()
            got = _pick(row)
            if got:
                return got
        except Exception:
            pass

        return None

    def _trim_transparent_pixmap(self, pm: QPixmap, pad: int = 2, alpha_thr: int = 6) -> QPixmap:
        if not pm or pm.isNull():
            return pm
        img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
        w, h = img.width(), img.height()

        left, right = w, -1
        top, bottom = h, -1

        for y in range(h):
            for x in range(w):
                if QColor.fromRgba(img.pixel(x, y)).alpha() > alpha_thr:
                    left = min(left, x)
                    right = max(right, x)
                    top = min(top, y)
                    bottom = max(bottom, y)

        if right < left or bottom < top:
            return pm

        left = max(0, left - pad)
        top = max(0, top - pad)
        right = min(w - 1, right + pad)
        bottom = min(h - 1, bottom + pad)

        return pm.copy(QRect(left, top, right - left + 1, bottom - top + 1))

    def _sanitize_badge_pixmap(self, pm: QPixmap) -> QPixmap:
        """
        Как в reforge.py: если есть альфа — кроп по альфе (убираем пустые поля).
        """
        if not pm or pm.isNull():
            return pm

        img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
        w, h = img.width(), img.height()
        has_alpha = False
        for y in range(h):
            for x in range(w):
                if img.pixelColor(x, y).alpha() != 255:
                    has_alpha = True
                    break
            if has_alpha:
                break

        if has_alpha:
            return self._trim_transparent_pixmap(pm, pad=2)

        return pm

    def _load_pm_by_image_id(self, image_id: int):
        """
        Универсальная загрузка картинки по Image.Id:
        1) если есть self._image_loader — используем
        2) иначе parent.data.get_image_bytes
        """
        try:
            iid = int(image_id or 0)
        except Exception:
            return None
        if iid <= 0:
            return None

        raw = None
        loader = getattr(self, "_image_loader", None)
        if callable(loader):
            try:
                raw = loader(iid)
            except Exception:
                raw = None

        if not raw:
            parent = self.parent()
            if parent is not None and hasattr(parent, "data") and hasattr(parent.data, "get_image_bytes"):
                try:
                    raw = parent.data.get_image_bytes(iid)
                except Exception:
                    raw = None

        if not raw:
            return None

        pm = QPixmap()
        if not pm.loadFromData(raw) or pm.isNull():
            return None
        return pm

    def _load_element_badge_pixmap(self, element_id: int, item=None):
        if not element_id:
            return None

        cached = self._element_badge_cache.get(int(element_id))
        if isinstance(cached, QPixmap) and not cached.isNull():
            return cached

        img_id = None
        if item:
            img_id = self._element_badge_image_id_for_item(item)
        if img_id is None:
            img_id = self._db_element_badge_image_id(int(element_id))

        if not img_id:
            return None

        pm = self._load_pm_by_image_id(int(img_id))
        if not pm or pm.isNull():
            return None

        pm = self._sanitize_badge_pixmap(pm)
        if not pm.isNull():
            self._element_badge_cache[int(element_id)] = pm
        return pm if not pm.isNull() else None

    def _compose_with_element_badge(self, base_pm: QPixmap, canvas_size: QSize, element_id: int, item: dict) -> QPixmap:
        """
        1:1 как в reforge.py:
        Базовая иконка + бейдж элемента снизу-слева.
        Бейдж 16/54 относительно клетки, m 4/54, dy 2/54.
        """
        canvas = QPixmap(canvas_size)
        canvas.fill(Qt.transparent)

        p = QPainter(canvas)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        base_scaled = base_pm.scaled(canvas.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (canvas.width() - base_scaled.width()) // 2
        y = (canvas.height() - base_scaled.height()) // 2
        p.drawPixmap(x, y, base_scaled)

        if element_id:
            badge = self._load_element_badge_pixmap(int(element_id), item=item)
            if badge and not badge.isNull():
                base = int(min(canvas.width(), canvas.height()))
                bw = max(1, int(base * (12.0 / 54.0)))
                bh = max(1, int(base * (16.0 / 54.0)))
                m = max(1, int(base * (5.0 / 54.0)))
                badge_scaled = badge.scaled(bw, bh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

                dy = int(base * (2.0 / 54.0))
                by = canvas.height() - badge_scaled.height() - m + dy
                by = min(by, canvas.height() - badge_scaled.height())  # чтобы не вылезло за низ

                bx = m
                p.drawPixmap(bx, by, badge_scaled)

        p.end()
        return canvas


    def _get_saved_stamp_for_instance(self, inst_id):
        if not inst_id:
            return None
        return self._applied_stamps_by_inst.get(inst_id)

    def _cache_current_stamp_for_instance(self) -> Optional[dict]:
        """Кладёт выбранную печать в кэш по InstanceGuid (и синхронизирует с родителем)."""
        item = self._picked_item
        st = self._chosen_stamp
        inst = self._picked_instance_guid
        if not (item and st and inst):
            return None

        payload = {
            "id": int(st.get("Id") or 0),
            "color_id": int(st.get("Color_Id") or st.get("ColorId") or self._selected_color_id or 0),
            "name": st.get("Name") or st.get("name") or "",
            "bonuses": list(st.get("Bonuses") or st.get("BonusLines") or []),
        }

        self._applied_stamps_by_inst[inst] = payload

        # синхронизация с главным окном (его кэш теперь тоже по InstanceGuid)
        parent = self.parent()
        if parent and hasattr(parent, "_applied_stamps"):
            try:
                parent._applied_stamps[inst] = payload
            except Exception:
                pass

        return payload

    def _place_stamp_vscroll(self) -> None:
        if not getattr(self, "_sv_custom", None) or not getattr(self, "_stamp_area", None):
            return
        ar = self._stamp_area.geometry()
        if ar.isEmpty():
            return
        margin = 6
        x = ar.right() - self._sv_custom.width() - margin
        y = ar.top() + margin
        h = max(1, ar.height() - margin * 2)
        self._sv_custom.setGeometry(x, y, self._sv_custom.width(), h)
        vb = self._stamp_area.verticalScrollBar()
        self._sv_custom.setVisible(vb.maximum() > 0)

    def _place_details_vscroll(self) -> None:
        """
        Мини-скролл для правого блока stamp_details.
        Использует такой же _MiniVScroll, как у описания карт,
        а не большой ImageVScrollBar из меню.
        """
        scroll = getattr(self, "_details_scroll_area", None)
        mini = getattr(self, "_details_sv_custom", None)

        if scroll is None or mini is None:
            return

        try:
            reserve = int(mini.width()) + 4
            scroll.setViewportMargins(0, 0, reserve, 0)
        except Exception:
            pass

        try:
            label = getattr(self, "_details_bonuses", None)
            content = getattr(self, "_details_scroll_content", None)

            if label is not None:
                vw = int(scroll.viewport().width())
                label.setFixedWidth(max(20, vw - 2))
                label.adjustSize()

                label_h = max(1, int(label.sizeHint().height()))
                label.setMinimumHeight(label_h)

                if content is not None:
                    content.setMinimumHeight(label_h)
                    content.adjustSize()
        except Exception:
            pass

        ar = scroll.geometry()
        if ar.isEmpty():
            return

        margin = 2
        x = ar.right() - int(mini.width()) - margin
        y = ar.top() + margin
        h = max(1, ar.height() - margin * 2)

        mini.setGeometry(int(x), int(y), int(mini.width()), int(h))

        try:
            vb = scroll.verticalScrollBar()
            content_h = max(
                int(getattr(self, "_details_bonuses", None).sizeHint().height()),
                int(getattr(self, "_details_scroll_content", None).sizeHint().height()),
            )
            view_h = int(scroll.viewport().height())

            mini.set_range(content_h, view_h)

            old = mini.blockSignals(True)
            mini.set_value(int(vb.value()))
            mini.blockSignals(old)

            mini.setVisible(mini.maximum() > 0)
            if mini.maximum() > 0:
                mini.raise_()
        except Exception:
            try:
                mini.hide()
            except Exception:
                pass

    def _on_details_mini_scroll(self, value: int) -> None:
        """
        Когда двигаем мини-скролл мышкой — прокручиваем QScrollArea.
        """
        scroll = getattr(self, "_details_scroll_area", None)
        if scroll is None:
            return

        try:
            scroll.verticalScrollBar().setValue(int(value))
        except Exception:
            pass

    def _sync_details_mini_from_scrollbar(self, value: int) -> None:
        """
        Когда текст прокрутили колесом — синхронизируем положение мини-скролла.
        """
        mini = getattr(self, "_details_sv_custom", None)
        if mini is None:
            return

        try:
            old = mini.blockSignals(True)
            mini.set_value(int(value))
            mini.blockSignals(old)
            mini.update()
        except Exception:
            pass

    def _build_stamp_details_board(self) -> None:
        area = self._area_widgets.get("stamp_details")
        if not area:
            self._details_frame = None
            self._details_title = None
            self._details_bonuses = None
            self._details_icon = None
            self._details_scroll_area = None
            self._details_scroll_content = None
            self._details_sv_custom = None
            return

        self._details_frame = QFrame(area)
        self._details_frame.setObjectName("sdFrame")
        self._details_frame.setGeometry(0, 0, area.width(), area.height())
        self._details_frame.setStyleSheet("""
            QFrame#sdFrame {
                background: rgba(255,255,255,0.00);
                border: 0px solid transparent;
            }
            QLabel#sdTitle {
                color:#e5a04a;
                font-weight:700;
                background: transparent;
                border: none;
            }
            QLabel#sdBonus {
                color:#eaeaea;
                background: transparent;
                border: none;
            }
            QScrollArea#sdScroll {
                background: transparent;
                border: none;
            }
            QWidget#sdScrollContent {
                background: transparent;
            }
        """)

        root = QVBoxLayout(self._details_frame)
        root.setContentsMargins(0, 24, 12, 8)
        root.setSpacing(2)

        # --- заголовок: [иконка][название] ---
        header = QWidget(self._details_frame)
        header.setStyleSheet("background: transparent; border: none;")

        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        self._details_icon = QLabel(header)
        self._details_icon.setFixedSize(20, 20)
        self._details_icon.setScaledContents(True)
        self._details_icon.setStyleSheet("background: transparent; border: none;")
        self._details_icon.hide()

        self._details_title = QLabel("Печать не выбрана", header)
        self._details_title.setObjectName("sdTitle")
        self._details_title.setWordWrap(True)
        self._details_title.setTextFormat(Qt.RichText)
        self._details_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        h.addWidget(self._details_icon, 0, Qt.AlignTop)
        h.addWidget(self._details_title, 1)

        # --- область бонусов со скрытым QScrollArea ---
        self._details_scroll_area = QScrollArea(self._details_frame)
        self._details_scroll_area.setObjectName("sdScroll")
        self._details_scroll_area.setFrameShape(QFrame.NoFrame)
        self._details_scroll_area.setWidgetResizable(True)
        self._details_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._details_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._details_scroll_area.setStyleSheet("background: transparent; border: none;")

        self._details_scroll_content = QWidget()
        self._details_scroll_content.setObjectName("sdScrollContent")
        self._details_scroll_content.setStyleSheet("background: transparent; border: none;")
        self._details_scroll_area.setWidget(self._details_scroll_content)

        scroll_lay = QVBoxLayout(self._details_scroll_content)
        scroll_lay.setContentsMargins(0, 0, 0, 0)
        scroll_lay.setSpacing(0)

        self._details_bonuses = QLabel("—", self._details_scroll_content)
        self._details_bonuses.setObjectName("sdBonus")
        self._details_bonuses.setWordWrap(True)
        self._details_bonuses.setTextFormat(Qt.RichText)
        self._details_bonuses.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._details_bonuses.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self._details_bonuses.setStyleSheet(
            "border:1px solid rgba(255,255,255,0);"
            "border-radius:8px;"
            "padding:8px;"
            "background: rgba(255,255,255,0);"
            "color:#eaeaea;"
        )

        scroll_lay.addWidget(self._details_bonuses, 0, Qt.AlignTop)
        scroll_lay.addStretch(1)

        root.addWidget(header, 0)
        root.addWidget(self._details_scroll_area, 1)

        # --- ВАЖНО: мини-скролл как у описания карт, НЕ ImageVScrollBar ---
        self._details_sv_custom = _MiniVScroll(self._details_frame)
        self._details_sv_custom.valueChanged.connect(self._on_details_mini_scroll)
        self._details_sv_custom.hide()

        vb = self._details_scroll_area.verticalScrollBar()
        vb.setSingleStep(18)
        vb.setPageStep(70)
        vb.rangeChanged.connect(lambda _a, _b: self._place_details_vscroll())
        vb.valueChanged.connect(self._sync_details_mini_from_scrollbar)

        QTimer.singleShot(0, self._place_details_vscroll)

        self._details_frame.hide()
        self._raise_stamp_stack()

    def _reset_details_panel(self) -> None:
        """Полностью очистить и скрыть правую панель 'stamp_details'."""
        if getattr(self, "_details_icon", None):
            self._details_icon.clear()
            self._details_icon.hide()

        if getattr(self, "_details_title", None):
            self._details_title.setText("Печать не выбрана")

        if getattr(self, "_details_bonuses", None):
            self._details_bonuses.setText("—")
            self._details_bonuses.adjustSize()

        try:
            scroll = getattr(self, "_details_scroll_area", None)
            if scroll is not None:
                scroll.verticalScrollBar().setValue(0)
        except Exception:
            pass

        try:
            mini = getattr(self, "_details_sv_custom", None)
            if mini is not None:
                mini.set_value(0)
                mini.hide()
        except Exception:
            pass

        self._apply_details_color(None)

        if getattr(self, "_details_frame", None):
            self._details_frame.hide()

    def _apply_details_color(self, color_hex: Optional[str]) -> None:
        """Красит текст плашки в цвет печати. Если None — нейтральный."""
        if not getattr(self, "_details_frame", None):
            return

        base = "#eaeaea" if not color_hex else color_hex
        q = QColor(base)
        soft = f"rgba({q.red()},{q.green()},{q.blue()},0.85)"

        if getattr(self, "_details_title", None):
            self._details_title.setStyleSheet(f"color: {base}; font-weight: 700;")

        if getattr(self, "_details_bonuses", None):
            self._details_bonuses.setStyleSheet(
                "border:1px solid rgba(255,255,255,0);"
                "border-radius:8px;"
                "padding:8px;"
                "background: rgba(255,255,255,0);"
                f"color: {soft};"
                "font-weight: 700;"
            )

        QTimer.singleShot(0, self._place_details_vscroll)

    def _select_stamp_in_ui(self, stamp_id: int, stamp_name: str, bonuses: list[str], _color_id_unused: int) -> None:
        """
        Выбор печати внутри StampWindow (обновляет UI/правую панель, пересчит. бонусы, превью).
        Не путаем с public _select_stamp_in_ui(...) — тот пишет в кэш родителя по InstanceGuid.
        """
        cur_color = _to_int(self._selected_color_id, 0) or 4
        self._chosen_stamp = {
            "Id": int(stamp_id),
            "Name": stamp_name,
            "Color_Id": int(cur_color),
            "Bonuses": list(bonuses or []),
            "BonusesText": "\n".join(bonuses or []),
            "name": stamp_name,
            "effects": "\n".join(bonuses or []),
        }
        self._selected_color_id = cur_color

        # Подсветка кружка цвета
        for b in self._color_buttons:
            self._style_color_btn(b, selected=(int(b.property("color_id") or -1) == cur_color))

        # Пересчёт бонусов с учётом internal level предмета
        self._recalc_chosen_stamp_bonuses()

        # Обновления UI
        self._update_color_buttons_enabled()
        self._update_color_preview()
        self._refresh_out_stamp_preview()
        self._set_right_details(stamp_name, self._chosen_stamp.get("Bonuses") or [])
        self._update_details_color_from_current()

    def _apply_item_sheet_text_style(self, color_hex: str) -> None:
        """
        Стили как в анкете предмета:
        - заголовок: жирный, крупнее, цвет = цвет печати
        - бонусы: обычный, чуть меньше, светлый текст с 85% непр.
        - одинаковый line-height
        """
        # заголовок: близко к анкете
        self._details_title.setStyleSheet(
            f""" QLabel#sdTitle {{ color: {color_hex}; font-weight: 700; }}"""
        )

        #font-size: 18px;         /* ≈ заголовку анкеты */ font-family: "Segoe UI", "Arial", sans-serif;letter-spacing: 0px;

        # rgba(255, 233, 205, 0.85);
        # бонусы: как в тексте эффектов анкеты
        #self._details_bonuses.setText("—")
        self._details_bonuses.setStyleSheet(
            f""" QLabel#sdBonus {{ color: {color_hex}; font-weight: 700; }}"""
            #font-family: "Segoe UI", "Arial", sans-serif;font-size: 14px;rgba(255, 233, 205, 0.85);font-weight: 700;
        )

    def _set_right_details(self, name: Optional[str], bonuses: Optional[list[str]]) -> None:
        if not getattr(self, "_details_frame", None):
            return

        bon_lines = bonuses or []

        # ----------------------------------------------------------
        # Определяем актуальную печать для правого инфо-блока:
        # 1) новая выбранная печать;
        # 2) сохранённая печать предмета;
        # 3) ничего.
        #
        # В режиме снятия печати НЕ подтягиваем сохранённую печать обратно.
        # ----------------------------------------------------------
        stamp_payload = None

        try:
            if isinstance(getattr(self, "_chosen_stamp", None), dict):
                stamp_payload = self._current_stamp_payload()
        except Exception:
            stamp_payload = None

        allow_saved_fallback = bool(name or bon_lines) and not bool(getattr(self, "_remove_stamp_mode", False))

        if stamp_payload is None and allow_saved_fallback:
            try:
                saved = self._get_saved_stamp_for_item(self._picked_item)
                if saved:
                    stamp_payload = self._to_tip_stamp_payload(saved)
            except Exception:
                stamp_payload = None

        color_id = 0
        color_hex = None
        icon_id = 0

        if isinstance(stamp_payload, dict):
            color_id = _to_int(
                stamp_payload.get("ColorId")
                or stamp_payload.get("Color_Id")
                or stamp_payload.get("color_id")
                or stamp_payload.get("StampColorId")
                or 0,
                0,
            )

            color_hex = (
                stamp_payload.get("HeaderColorHex")
                or stamp_payload.get("header_color_hex")
                or stamp_payload.get("ColorHex")
                or stamp_payload.get("color_hex")
                or None
            )

            icon_id = _to_int(
                stamp_payload.get("HeaderIconImageId")
                or stamp_payload.get("HeaderIconId")
                or stamp_payload.get("icon_id")
                or stamp_payload.get("IconImageId")
                or stamp_payload.get("Icon_Image_Id")
                or 0,
                0,
            )

        if color_id <= 0:
            color_id = _to_int(getattr(self, "_selected_color_id", 0), 0)

        meta = STAMP_COLOR_META.get(int(color_id), {}) if color_id > 0 else {}

        if not color_hex:
            color_hex = meta.get("hex") or "#eaeaea"

        if icon_id <= 0:
            icon_id = _to_int(meta.get("icon_img_id"), 0)

        self._apply_item_sheet_text_style(color_hex)

        title_text = f"Печать {name.strip()}" if name else "Печать не выбрана"

        if getattr(self, "_details_title", None):
            self._details_title.setText(
                f"<span style='line-height:135%;'>{title_text}</span>"
            )

        # --- иконка печати ---
        pm = None

        try:
            if icon_id and self.parent() and hasattr(self.parent(), "data"):
                raw = self.parent().data.get_image_bytes(int(icon_id))
                if raw:
                    pm = QPixmap()
                    pm.loadFromData(raw)
        except Exception:
            pm = None

        if (pm is None or pm.isNull()) and color_id > 0:
            try:
                path = STAMP_COLOR_ICON.get(int(color_id))
                if path:
                    pm = _load_file_image(_resolve_resource(path))
            except Exception:
                pm = None

        if getattr(self, "_details_icon", None):
            if pm is not None and not pm.isNull():
                self._details_icon.setPixmap(
                    pm.scaled(
                        self._details_icon.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
                self._details_icon.show()
            else:
                self._details_icon.clear()
                self._details_icon.hide()

        # --- бонусы / описание ---
        clean_lines: list[str] = []
        for ln in bon_lines:
            s = str(ln or "").strip()
            if s:
                clean_lines.append(s)

        html = "<br/>".join(clean_lines) if clean_lines else "—"

        if getattr(self, "_details_bonuses", None):
            self._details_bonuses.setText(
                f"<div style='margin-top:0px; line-height:135%;'>{html}</div>"
            )

            try:
                self._details_bonuses.adjustSize()
            except Exception:
                pass

        try:
            if getattr(self, "_details_scroll_area", None):
                self._details_scroll_area.verticalScrollBar().setValue(0)
        except Exception:
            pass

        try:
            if getattr(self, "_details_sv_custom", None):
                self._details_sv_custom.set_value(0)
        except Exception:
            pass

        if self._picked_item:
            self._details_frame.show()
            self._details_frame.raise_()

            try:
                if getattr(self, "_details_sv_custom", None):
                    self._details_sv_custom.raise_()
            except Exception:
                pass

            QTimer.singleShot(0, self._place_details_vscroll)
            QTimer.singleShot(30, self._place_details_vscroll)
        else:
            self._details_frame.hide()

    def _update_details_header(self, name: Optional[str], color_id: Optional[int]) -> None:
        """Обновляет заголовок 'Печать {name}' и кладёт цвет по цвету печати."""
        if not getattr(self, "_details_title", None):
            return
        n = (name or "").strip()
        title = f"Печать {n}" if n else "Печать не выбрана"
        self._details_title.setText(title)

        hex_color = (STAMP_COLOR_META.get(int(color_id or 0), {}) or {}).get("hex") or "#e5a04a"
        # только цвет здесь; остальные свойства – как у тебя в стиле
        self._details_title.setStyleSheet(f"color: {hex_color}; font-weight: 700;")

    def _current_color_hex(self) -> Optional[str]:
        """Берём текущий выбранный цвет печати."""
        cid = int(self._selected_color_id or 0)
        if cid == 0 and isinstance(self._chosen_stamp, dict):
            cid = int(self._chosen_stamp.get("Color_Id") or self._chosen_stamp.get("ColorId") or 0)
        meta = self._stamp_color_meta(cid)
        return meta.get("hex") if meta else None

    def _update_details_color_from_current(self) -> None:
        self._apply_details_color(self._current_color_hex())

    def _search_match(self, name: str, bonuses: list[str], query: str) -> bool:
        """true, если ВСЕ токены query встречаются в имени или любом бонусе."""
        q = _norm(query)
        if not q:
            return True
        tokens = [t for t in q.split() if t]
        if not tokens:
            return True
        hay = " ".join([_norm(name)] + [_norm(b) for b in bonuses])
        return all(t in hay for t in tokens)

    def _on_stamp_search_changed(self, txt: str):
        self._stamp_search_text = txt or ""

        # Пересобираем «старый» список в невидимом popup — используем как источник данных
        self._rebuild_pick_stamp_popup()

        # Если открыто новое меню — обновим его entries
        cm = getattr(self, "_choose_stamp_menu", None)
        if cm is not None and cm.isVisible():
            entries: list[dict] = []
            lb = getattr(self, "_stamp_list_box", None)
            if lb is not None:
                for i in range(lb.count()):
                    it = lb.itemAt(i)
                    w = it.widget() if it else None
                    if w is None:
                        continue
                    sid = _to_int(w.property("stamp_id"), 0)
                    if sid <= 0:
                        continue
                    name = w.property("stamp_name") or ""
                    bons = w.property("stamp_bonuses") or []
                    entries.append({"id": int(sid), "name": str(name), "bonuses": list(bons or [])})
            try:
                cm.set_entries(entries)
            except Exception:
                pass

    def _set_color_circles_visible(self, vis: bool) -> None:
        """Показать/скрыть круглые кнопки выбора цвета."""
        for b in getattr(self, "_color_buttons", []) or []:
            b.setVisible(vis)

    def _slot_sort_key(self, slot_key: str, item: dict) -> tuple[int, str]:
        """Ключ сортировки по возрастанию ID слота экипировки.
        Берём из item['Slot_Id'|'SlotId'|'EquipmentSlot_Id'] или тащим из БД по Equipment.Id.
        Если не нашли — отправляем в конец (10**9), чтобы не ломать порядок."""
        # 1) из самого словаря предмета
        for k in ("Slot_Id", "SlotId", "EquipmentSlot_Id"):
            try:
                v = int(item.get(k))  # может быть None/пусто
                if v is not None:
                    return (v, str(slot_key))
            except Exception:
                pass

        # 2) пробуем из БД по Id предмета
        try:
            equip_id = int(item.get("Id") or 0)
            parent = self.parent()
            conn = parent.data.conn if (parent and hasattr(parent, "data")) else None
            if conn and equip_id:
                row = conn.execute(
                    "SELECT Slot_Id FROM Equipment WHERE Id=? LIMIT 1",
                    (equip_id,)
                ).fetchone()
                if row and row[0] is not None:
                    return (int(row[0]), str(slot_key))
        except Exception:
            pass

        # 3) fallback — очень большой ключ + подстраховка вторичным ключом
        return (10 ** 9, str(slot_key))

    def _get_internal_level_for_item(self, item: Optional[dict]) -> int:
        """
        Возвращает internal_level предмета:
        1) item["InternalLevel"]
        2) SELECT Equipment.InternalLevel FROM Equipment WHERE Id=?
        3) fallback: item["Level"] / item["RequiredLevel"] / 1
        """
        try:
            it = item or getattr(self, "_picked_item", None) or {}
            # 1) из словаря предмета
            if isinstance(it, dict) and it.get("InternalLevel") is not None:
                return _to_int(it.get("InternalLevel"), 1)
            # 2) из БД по Id
            equip_id = _to_int(it.get("Id"), 0)
            if equip_id:
                try:
                    parent = self.parent()
                    conn = parent.data.conn if (parent and hasattr(parent, "data")) else None
                    if conn:
                        row = conn.execute(
                            "SELECT InternalLevel FROM Equipment WHERE Id=? LIMIT 1",
                            (equip_id,),
                        ).fetchone()
                        if row and row[0] is not None:
                            return _to_int(row[0], 1)
                except Exception:
                    pass
            # 3) fallback
            return _to_int(it.get("Level") or it.get("RequiredLevel") or 1, 1)
        except Exception:
            return 1

    # ---------- LEVEL / COEFS ----------
    @lru_cache(maxsize=1)
    def _get_max_player_level(self) -> int:
        """Глобальный кап, если нет — 100."""
        parent = self.parent()
        for attr in ("max_player_level", "max_level", "level_cap"):
            if parent is not None and hasattr(parent, attr):
                v = _to_int(getattr(parent, attr), 0)
                if v > 0:
                    return v
        try:
            conn = parent.data.conn if (parent and hasattr(parent, "data")) else None
            if conn:
                for sql in (
                    "SELECT QualityValue FROM Settings WHERE Key='MaxPlayerLevel' LIMIT 1",
                    "SELECT MAX(Level) FROM PlayerLevel",
                    "SELECT MAX(Level) FROM CharacterLevel",
                ):
                    row = conn.execute(sql).fetchone()
                    if row and row[0]:
                        v = _to_int(row[0], 0)
                        if v > 0:
                            return v
        except Exception:
            pass
        return 100

    @lru_cache(maxsize=512)
    def _get_bonus_type_coefs(self, bonus_type_id: int) -> tuple[float, float]:
        """Читает из BonusType.Min/MaxCoef, если нет — (1.0, 1.0)."""
        parent = self.parent()
        try:
            conn = parent.data.conn if (parent and hasattr(parent, "data")) else None
            if not conn:
                return (1.0, 1.0)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(BonusType)").fetchall()}
            if not {"StampQualityMinCoef", "StampQualityMaxCoef"}.issubset(cols):
                return (1.0, 1.0)
            row = conn.execute(
                "SELECT StampQualityMinCoef, StampQualityMaxCoef FROM BonusType WHERE Id=? LIMIT 1",
                (int(bonus_type_id),),
            ).fetchone()
            if row:
                return (_to_float(row[0], 1.0), _to_float(row[1], 1.0))
        except Exception:
            pass
        return (1.0, 1.0)

    def _get_stamp_value(
            self,
            base_value: float | int,
            *,
            min_coef: float,
            max_coef: float,
            item: Optional[dict] = None,
            internal_level: Optional[float] = None,
            min_level: float,
            max_level: Optional[float] = None,
    ) -> int:
        """
        Единый расчёт значения бонуса печати.
        - internal_level: из аргумента, иначе из _get_internal_level_for_item(...)
        - Спец-кейсы: 65 -> value=64.9; 63 -> value=62.5.
        - Шкала [min_level .. max_level]; max_level по умолчанию = min(60, _get_max_player_level()).
        - Округление: ceil, если (ceil(num) - num) < 0.98, иначе trunc.
        """
        try:
            base = float(base_value)
            mn = float(min_coef)
            mx = float(max_coef)

            if max_level is None:
                max_level = float(min(60, self._get_max_player_level()))
            lvl_min = 10.0
            lvl_max = float(max_level)
            d = float((mx - mn) / (lvl_max - lvl_min))

            # правильный internal level
            ilvl = float(internal_level) if internal_level is not None else float(
                self._get_internal_level_for_item(item)
            )

            # значение по шкале (со спец-кейсами)
            value = max(0.0, ilvl - lvl_min)

            num = (mn + d * value) * base
            num2 = math.ceil(num)
            out = num2 if (num2 - num) < 0.98 else math.trunc(num)
            return int(out)

        except Exception:
            try:
                return int(round(float(base_value)))
            except Exception:
                return 0

    # ---------- PUBLIC ----------
    def reset_stamps_cache(self) -> None:
        self._applied_stamps.clear()
        self._chosen_stamp = None
        self._selected_color_id = 0
        self._update_color_preview()
        self._refresh_out_stamp_preview()

    def _is_stamp_allowed_for_player(self, stamp_id: int) -> bool:
        """
        Больше не используем хардкод по id печатей.
        Фактическая фильтрация/сортировка вычисляется в _rebuild_pick_stamp_popup
        и складывается в self._stamp_allowed_map: {StampId: group}.
        """
        try:
            sid = int(stamp_id or 0)
        except Exception:
            return True

        m = getattr(self, "_stamp_allowed_map", None)
        if isinstance(m, dict) and m:
            return sid in m

        # если по какой-то причине кэш ещё не построен — не режем список
        return True

    def set_player_class(self, value) -> None:
        """Пишем сырой класс/ид и определяем корзину (warrior/archer/mage/rogue/unknown).
        ВАЖНО: подхватываем актуальный класс из MainWindow.class_combo (itemData),
        и подписываемся на смену класса, чтобы не править main_window.py.
        """
        # -------- найти owner(MainWindow)-подобный родитель --------
        owner = self.parent()
        while owner is not None and not (hasattr(owner, "class_combo") or hasattr(owner, "_current_class_id")):
            try:
                owner = owner.parent()
            except Exception:
                break

        combo = getattr(owner, "class_combo", None) if owner is not None else None

        # -------- один раз подписаться на изменения комбобокса --------
        if combo is not None and not getattr(self, "_sw_class_combo_hooked", False):
            try:
                self._sw_class_combo_hooked = True

                def _sync_from_combo(*_a):
                    try:
                        # value не важен — ниже мы всё равно считаем из combo
                        self.set_player_class(None)
                    except Exception:
                        pass

                # держим ссылку, чтобы не отвалилось из-за GC
                self._sw_class_combo_sync_cb = _sync_from_combo

                try:
                    combo.currentIndexChanged.connect(self._sw_class_combo_sync_cb)
                except Exception:
                    pass
                try:
                    combo.currentTextChanged.connect(self._sw_class_combo_sync_cb)
                except Exception:
                    pass
            except Exception:
                pass

        # -------- helpers --------
        def _to_int_or_none(v):
            if v is None:
                return None
            if isinstance(v, int):
                return int(v)
            try:
                s = str(v).strip()
            except Exception:
                return None
            if not s:
                return None
            try:
                return int(s)
            except Exception:
                try:
                    return int(float(s.replace(",", ".").strip()))
                except Exception:
                    return None

        # -------- получить актуальный Class.Id + имя --------
        cid = None
        raw_name = ""

        # 1) самый надёжный путь: из main_window.class_combo.itemData / _current_class_id()
        if owner is not None and combo is not None:
            try:
                if hasattr(owner, "_current_class_id") and callable(getattr(owner, "_current_class_id")):
                    cid = owner._current_class_id()
                else:
                    idx = int(combo.currentIndex())
                    cid = combo.itemData(idx) if idx >= 0 else None
            except Exception:
                cid = None

            try:
                raw_name = str(combo.currentText() or "").strip()
            except Exception:
                raw_name = ""

        # 2) fallback: то, что пришло параметром
        if cid is None:
            cid = _to_int_or_none(value)

        if not raw_name:
            try:
                raw_name = str(value or "").strip()
            except Exception:
                raw_name = ""

        # 3) если cid всё ещё None, но есть имя — попробуем найти Id по БД
        if (cid is None or int(cid or 0) <= 0) and raw_name:
            conn = None
            try:
                conn = self._db_conn()
            except Exception:
                conn = None
            if conn is not None:
                try:
                    row = conn.execute(
                        "SELECT Id FROM Class WHERE lower(Name)=lower(?) LIMIT 1",
                        (raw_name,),
                    ).fetchone()
                except Exception:
                    row = None
                if row:
                    try:
                        cid = _to_int_or_none(row["Id"] if hasattr(row, "keys") else row[0])
                    except Exception:
                        cid = None

        # -------- записать поля --------
        self._player_class_raw = raw_name or ""
        self._player_class_id = int(cid) if (cid is not None and int(cid or 0) > 0) else None

        bucket = "unknown"
        if self._player_class_id is not None:
            cc = int(self._player_class_id)
            # твоя текущая схема id -> ведро (НЕ трогаю)
            if cc in (1, 2, 3):       bucket = "мечник"
            elif cc in (4, 5, 6):     bucket = "стрелок"
            elif cc in (7, 8, 9):     bucket = "маг"
            elif cc in (10, 11, 12):   bucket = "вор"

        self._player_class_bucket = bucket

        # если попап открыт — пересобрать список печатей
        if getattr(self, "_stamp_popup", None) and self._stamp_popup.isVisible():
            self._rebuild_pick_stamp_popup()

    def open_centered(self, owner: QWidget | None):
        self._set_right_details(None, None)
        self._reset_details_panel()
        self._ensure_bucket()
        self._reset_selection()
        self._rebuild_pick_item_popup()
        self._rebuild_pick_stamp_popup()
        scr = (owner.window().screen().availableGeometry()
               if owner else QApplication.primaryScreen().availableGeometry())
        gx = scr.x() + (scr.width() - self.width()) // 2
        gy = scr.y() + (scr.height() - self.height()) // 2
        self.move(gx, gy)
        self.show(); self.raise_(); self.activateWindow()
        self._set_color_circles_visible(False)

    # ---------- CLASS BUCKET / FILTER ----------
    def _ensure_bucket(self):
        # Старый смысл «bucket» больше не критичен — нам важен Class.Id.
        if int(getattr(self, "_player_class_id", 0) or 0) > 0:
            return

        parent = self.parent()
        if not parent:
            return

        # сначала пробуем id-шники, потом имена
        for attr in (
                "player_class_id",
                "current_subclass_id",
                "current_class_id",
                "job_id",
                "current_subclass_name",
                "current_class_name",
                "job_name",
        ):
            if not hasattr(parent, attr):
                continue
            val = getattr(parent, attr)
            if val in (None, "", 0):
                continue
            self.set_player_class(val)
            break

    # ---------- STAMP IO ----------
    def _get_saved_stamp_for_item(self, item: dict | None) -> Optional[dict]:
        """
        Найти сохранённую печать предмета.

        Возвращает только реальную печать.
        Пустые записи id=0 / name="" / bonuses=[] игнорируются.
        """
        if not isinstance(item, dict) or not item:
            return None

        # 0) inline-штамп прямо из item
        try:
            raw_inline = item.get("Stamp")
            tip = self._to_tip_stamp_payload(raw_inline) if isinstance(raw_inline, dict) else None
            if tip:
                return tip
        except Exception:
            pass

        try:
            raw_inline = item.get("stamp")
            tip = self._to_tip_stamp_payload(raw_inline) if isinstance(raw_inline, dict) else None
            if tip:
                return tip
        except Exception:
            pass

        inst = item.get("InstanceGuid") or ""
        if not inst:
            return None

        # 1) локальный кэш окна
        try:
            raw = self._applied_stamps.get(inst)
            tip = self._to_tip_stamp_payload(raw) if isinstance(raw, dict) else None
            if tip:
                return tip
        except Exception:
            pass

        parent = self.parent()

        # 2) кэш MainWindow
        try:
            if parent and hasattr(parent, "_applied_stamps") and isinstance(parent._applied_stamps, dict):
                raw = parent._applied_stamps.get(inst)
                tip = self._to_tip_stamp_payload(raw) if isinstance(raw, dict) else None
                if tip:
                    return tip
        except Exception:
            pass

        # 3) DAO по InstanceGuid
        try:
            if parent and hasattr(parent, "data") and hasattr(parent.data, "get_item_stamp_by_instance"):
                raw = parent.data.get_item_stamp_by_instance(inst)
                tip = self._to_tip_stamp_payload(raw) if isinstance(raw, dict) else None
                if tip:
                    return tip
        except Exception:
            pass

        return None

    def _to_tip_stamp_payload(self, payload: dict | None) -> Optional[dict]:
        """
        Приводит сохранённую печать к формату tooltip/UI.

        ВАЖНО:
        Пустая запись вида:
            {"id": 0, "color_id": 0, "name": "", "bonuses": []}
        НЕ является печатью.

        Именно такие пустые записи раньше превращались в визуально
        оранжевую "пустую печать", потому что color_id потом падал в fallback = 4.
        """
        if not isinstance(payload, dict) or not payload:
            return None

        sid = _to_int(
            payload.get("id")
            or payload.get("Id")
            or payload.get("StampId")
            or payload.get("Stamp_Id")
            or payload.get("stamp_id")
            or 0,
            0,
        )

        # Нет Id печати — значит печати нет.
        if sid <= 0:
            return None

        cid = _to_int(
            payload.get("color_id")
            or payload.get("ColorId")
            or payload.get("Color_Id")
            or payload.get("StampColorId")
            or payload.get("StampColor_Id")
            or payload.get("stamp_color_id")
            or 0,
            0,
        )

        # Для старых/битых записей с реальным Id, но без цвета,
        # оставляем прежнюю логику: считаем цвет оранжевым.
        if cid <= 0:
            cid = 4

        name = (
                payload.get("name")
                or payload.get("Name")
                or payload.get("StampName")
                or payload.get("stamp_name")
                or ""
        )
        name = str(name or "").strip()

        bonuses = list(
            payload.get("bonuses")
            or payload.get("Bonuses")
            or payload.get("BonusLines")
            or payload.get("Effects")
            or payload.get("StampBonuses")
            or payload.get("stamp_bonuses")
            or []
        )

        bonuses = [str(x).strip() for x in bonuses if str(x or "").strip()]

        # Если даже при валидном Id нет ни названия, ни бонусов —
        # не показываем пустую печать в UI.
        if not name and not bonuses:
            return None

        meta = self._stamp_color_meta(cid)

        return {
            "Id": int(sid),
            "id": int(sid),

            "Name": name,
            "name": name,

            "ColorId": int(cid),
            "Color_Id": int(cid),
            "color_id": int(cid),

            "Bonuses": list(bonuses),
            "BonusLines": list(bonuses),
            "Effects": list(bonuses),
            "bonuses": list(bonuses),

            "HeaderColorHex": meta.get("hex"),
            "HeaderIconImageId": meta.get("icon_img_id"),
            "icon_id": meta.get("icon_img_id"),
        }

    def _notify_owner_apply_stamp(self) -> None:
        parent = self.parent()
        item = self._picked_item
        inst = (item or {}).get("InstanceGuid") or ""

        if not (parent and item and inst):
            return

        stamp_keys = (
            "Stamp", "stamp",
            "StampId", "Stamp_Id", "stamp_id",
            "StampColorId", "StampColor_Id", "stamp_color_id",
            "StampName", "stamp_name",
            "StampBonuses", "stamp_bonuses",
            "StampBonusLines", "stamp_bonus_lines",
            "StampHeaderColorHex", "StampHeaderIconImageId", "StampHeaderIconId",
            "HeaderColorHex", "HeaderIconImageId", "HeaderIconId",
        )

        def _clear_stamp_fields(obj: Any) -> None:
            if not isinstance(obj, dict):
                return

            for k in stamp_keys:
                try:
                    obj.pop(k, None)
                except Exception:
                    pass

            # Иногда печать могла быть сохранена вложенно/под альтернативными ключами.
            try:
                if isinstance(obj.get("extra"), dict):
                    for k in stamp_keys:
                        obj["extra"].pop(k, None)
            except Exception:
                pass

        def _clear_inst_from_cache(owner: Any) -> None:
            if owner is None:
                return

            for cache_name in ("_applied_stamps", "_applied_stamps_by_inst"):
                try:
                    cache = getattr(owner, cache_name, None)
                    if isinstance(cache, dict):
                        cache.pop(inst, None)
                        cache.pop(str(inst), None)
                except Exception:
                    pass

        def _clear_selected_items() -> None:
            selected = None
            try:
                selected = getattr(parent, "_selected_items", None)
            except Exception:
                selected = None

            if not isinstance(selected, dict):
                return

            # Чистим не только self._picked_slot_key, а вообще любой предмет
            # с тем же InstanceGuid, чтобы не оставить дубль в другом слоте.
            for _slot_key, eq_item in list(selected.items()):
                if not isinstance(eq_item, dict):
                    continue

                try:
                    eq_inst = eq_item.get("InstanceGuid") or ""
                except Exception:
                    eq_inst = ""

                if str(eq_inst) == str(inst):
                    _clear_stamp_fields(eq_item)

        def _refresh_owner_after_stamp_change() -> None:
            # Основные методы, которые уже используются в этом файле.
            for fn_name in (
                "refresh_stats_panel",
                "_update_board_pixmap",
            ):
                try:
                    fn = getattr(parent, fn_name, None)
                    if callable(fn):
                        fn()
                except Exception:
                    pass

        if bool(getattr(self, "_remove_stamp_mode", False)):
            # 1) Чистим локальные данные окна.
            _clear_inst_from_cache(self)
            _clear_stamp_fields(item)

            # 2) Чистим данные MainWindow.
            _clear_inst_from_cache(parent)
            _clear_selected_items()

            # 3) Уведомляем MainWindow штатным способом удаления.
            # Важно: раньше вызывался либо clear_fn, либо apply_fn.
            # Теперь вызываем clear_fn, а затем apply_stamp_to_item(..., 0, 0, [], ""),
            # чтобы и кэш, и математика получили явный сигнал "печати нет".
            try:
                clear_fn = getattr(parent, "_clear_stamp_for_instance", None)
                if callable(clear_fn):
                    clear_fn(inst)
            except Exception:
                pass

            try:
                apply_fn = getattr(parent, "apply_stamp_to_item", None)
                if callable(apply_fn):
                    apply_fn(inst, 0, 0, [], "")
            except Exception:
                pass

            # 4) После apply_fn чистим ещё раз.
            # Если apply_stamp_to_item с id=0 создал пустую запись в _applied_stamps,
            # она не должна остаться как "активная печать".
            _clear_inst_from_cache(self)
            _clear_inst_from_cache(parent)
            _clear_stamp_fields(item)
            _clear_selected_items()

            # 5) Сигнал наружу, если кто-то слушает stampSaved.
            try:
                self.stampSaved.emit(0, {
                    "id": 0,
                    "color_id": 0,
                    "name": "",
                    "bonuses": [],
                    "removed": True,
                    "InstanceGuid": inst,
                })
            except Exception:
                pass

            # 6) Финальный пересчёт/перерисовка.
            _refresh_owner_after_stamp_change()
            return

        st = self._chosen_stamp
        if not isinstance(st, dict):
            return

        stamp_id = _to_int(st.get("Id"), 0)
        color_id = _to_int(st.get("Color_Id") or st.get("ColorId") or self._selected_color_id, 0)
        bonuses = list(st.get("Bonuses") or st.get("BonusLines") or [])
        name = st.get("Name") or ""

        fn = getattr(parent, "apply_stamp_to_item", None)
        if callable(fn):
            try:
                fn(inst, stamp_id, color_id, bonuses, name)
            except Exception:
                pass

    def _recalc_chosen_stamp_bonuses(self) -> None:
        st = self._chosen_stamp
        if not isinstance(st, dict):
            return
        # >>> ключевое: берём именно InternalLevel предмета
        ilvl = self._get_internal_level_for_item(self._picked_item)
        cid = _to_int(self._selected_color_id or st.get("Color_Id") or st.get("ColorId") or 4, 4)
        st_id = _to_int(st.get("Id") or 0, 0)
        if st_id <= 0:
            return
        bons = self._load_stamp_bonuses(st_id, cid, internal_level=ilvl)
        st["Color_Id"] = cid
        st["Bonuses"] = bons
        st["BonusesText"] = "\n".join(bons) if bons else ""
        st["effects"] = st["BonusesText"]

    def _stamp_color_meta(self, color_id: int) -> dict:
        return STAMP_COLOR_META.get(int(color_id) or 0, {"hex": None, "icon_img_id": None})

    def _clear_chosen_stamp(self) -> None:
        self._chosen_stamp = None
        self._selected_color_id = 0
        self._update_color_preview()
        self._refresh_out_stamp_preview()
        self._set_right_details(None, None)

    def _pixmap_for_item_icon(self, item: dict) -> Optional[QPixmap]:
        # защита
        if not isinstance(item, dict):
            return None

        parent = self.parent()
        data = getattr(parent, "data", None) if parent else None
        get_bytes = getattr(data, "get_image_bytes", None) if data else None
        if not callable(get_bytes):
            return None

        # 1) достаём image id (нормально, как в reforge)
        img_id = None
        for k in ("Icon_Image_Id", "IconImageId", "Image_Id", "ImageId", "CostumeImage_Id", "CostumeImageId"):
            v = item.get(k)
            if v is None:
                continue
            try:
                img_id = int(v)
                break
            except Exception:
                img_id = None

        if not img_id or img_id <= 0:
            return None

        # 2) грузим bytes -> QPixmap
        try:
            raw = get_bytes(int(img_id))
        except Exception:
            raw = None

        if not raw:
            return None

        pm = QPixmap()
        if not pm.loadFromData(raw) or pm.isNull():
            return None

        # 3) определяем целевой размер: сначала реальный размер слота, потом fallback к STAMP_UI, потом 54x54
        w = h = 54

        slot = getattr(self, "out_stamp_slot", None)  # если у тебя превью-слот называется иначе — поменяй тут
        if slot is not None:
            s = slot.size()
            if s.width() > 0 and s.height() > 0:
                w, h = s.width(), s.height()
            else:
                sh = slot.sizeHint()
                if sh.width() > 0 and sh.height() > 0:
                    w, h = sh.width(), sh.height()

        if (w, h) == (54, 54):
            try:
                area = (STAMP_UI.get("areas") or {}).get("out_stamp", {})
                rect = area.get("rect", (0, 0, 54, 54))
                w = int(rect[2]);
                h = int(rect[3])
            except Exception:
                w = h = 54

        canvas_size = QSize(max(1, int(w)), max(1, int(h)))

        # 4) если есть элемент и у класса есть методы — делаем бейдж (как в reforge.py)
        try:
            if hasattr(self, "_element_id_for_item") and hasattr(self, "_compose_with_element_badge"):
                eid = int(self._element_id_for_item(item) or 0)
                if eid > 0:
                    composed = self._compose_with_element_badge(pm, canvas_size, eid, item)
                    if composed and not composed.isNull():
                        return composed
        except Exception:
            pass

        # 5) fallback — просто масштабирнуть
        return pm.scaled(canvas_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _commit_current_stamp(self) -> None:
        item = self._picked_item
        st = self._chosen_stamp
        if not item or not st:
            return

        inst = item.get("InstanceGuid") or ""
        if not inst:
            return

        color_id = _to_int(st.get("Color_Id") or st.get("ColorId") or self._selected_color_id, 0)
        payload = {
            "id": _to_int(st.get("Id") or 0, 0),
            "color_id": color_id,
            "name": st.get("Name") or st.get("name") or "",
            "bonuses": list(st.get("Bonuses") or st.get("BonusLines") or []),
        }

        # кэш StampWindow теперь по InstanceGuid
        self._applied_stamps[inst] = payload

        # продублируем хозяину (если у него есть локальный кэш)
        parent = self.parent()
        if parent and hasattr(parent, "_applied_stamps"):
            try:
                parent._applied_stamps[inst] = payload
            except Exception:
                pass

        # уведомим хозяина стандартным путём
        self._notify_owner_apply_stamp()

        # UI
        try:
            self.stampSaved.emit(0, payload)  # id нам уже не критичен
        except Exception:
            pass
        self._refresh_out_stamp_preview()

    # ---------- RIGHT PREVIEWS ----------
    def _refresh_out_stamp_preview(self):
        if not self._out_stamp_slot:
            return

        item = self._picked_item
        if not item:
            self._out_stamp_slot.clear()
            self._out_stamp_slot.hide()
            return

        has_stamp_result = int(self._selected_color_id or 0) > 0
        has_remove_result = bool(getattr(self, "_remove_stamp_mode", False))

        if not has_stamp_result and not has_remove_result:
            self._out_stamp_slot.clear()
            self._out_stamp_slot.hide()
            return

        item_pm = self._pixmap_for_item_icon(item)
        if item_pm:
            self._out_stamp_slot.setPixmap(item_pm)
            self._out_stamp_slot.show()
            self._out_stamp_slot.raise_()
        else:
            self._out_stamp_slot.clear()
            self._out_stamp_slot.hide()

    def _update_color_preview(self):
        slot = self._color_preview_slot
        if not slot: return
        cid = int(self._selected_color_id or 0)
        if cid == 0:
            slot.clear(); slot.hide(); return
        path = STAMP_COLOR_ICON.get(cid)
        pm = _load_file_image(_resolve_resource(path)) if path else None
        if pm:
            slot.setPixmap(pm); slot.show(); slot.raise_()
        else:
            slot.clear(); slot.hide()

    # ---------- APPLY/SELECT ----------
    def _current_stamp_payload(self):
        st = self._chosen_stamp
        if not isinstance(st, dict):
            return None
        cid = _to_int(self._selected_color_id or st.get("ColorId") or st.get("Color_Id") or st.get("Color") or 0, 0)
        meta = self._stamp_color_meta(cid)
        bonuses = st.get("Bonuses") or st.get("bonus_lines") or []
        name_cap = st.get("Name") or st.get("name") or ""
        return {
            "Id": st.get("Id"),
            "Name": name_cap, "name": name_cap,
            "ColorId": cid,
            "Bonuses": bonuses, "BonusLines": bonuses, "Effects": bonuses,
            "HeaderColorHex": meta["hex"], "HeaderIconImageId": meta["icon_img_id"],
            "icon_id": meta["icon_img_id"],
        }

    def apply_stamp_to_item(self, instance_guid: str, stamp_id: int, color_id: int, bonuses: list[str], name: str):
        inst = str(instance_guid or "").strip()
        if not inst:
            return

        sid = _to_int(stamp_id, 0)
        cid = _to_int(color_id, 0)
        clean_name = str(name or "").strip()
        clean_bonuses = [str(x).strip() for x in (bonuses or []) if str(x or "").strip()]

        # id=0 — это не печать, а снятие/отсутствие печати.
        # Не храним такую запись, иначе потом она может отрисоваться как пустая печать.
        if sid <= 0:
            try:
                self._applied_stamps.pop(inst, None)
            except Exception:
                pass
            return

        if cid <= 0:
            cid = 4

        # Защита от битой пустой записи.
        if not clean_name and not clean_bonuses:
            try:
                self._applied_stamps.pop(inst, None)
            except Exception:
                pass
            return

        payload = {
            "id": int(sid),
            "color_id": int(cid),
            "name": clean_name,
            "bonuses": list(clean_bonuses),
        }

        self._applied_stamps[inst] = payload

    def _get_saved_stamp_for_item_main(self, item: dict) -> Optional[dict]:
        inst = (item or {}).get("InstanceGuid") or ""
        if not inst:
            return None

        # 1) локальный кэш (то, что только что сохранили из StampWindow)
        if inst in self._applied_stamps:
            return self._applied_stamps[inst]

        # 2) DAO по инстансу (когда предмет уже сохранён в инвентарь)
        try:
            if hasattr(self.data, "get_item_stamp_by_instance"):
                return self.data.get_item_stamp_by_instance(inst)
        except Exception:
            pass
        return None

    # ---------- RESET/UI ----------
    def _reset_selection(self) -> None:
        self._picked_item = None
        self._picked_item_id = None
        self._picked_slot_key = None
        self._set_pick_slot_icon(None)
        if self._pick_stamp_slot: self._pick_stamp_slot.clear(); self._pick_stamp_slot.hide()
        self._set_arcon_visible(False)
        if self._color_preview_slot: self._color_preview_slot.clear(); self._color_preview_slot.hide()
        if self._out_stamp_slot: self._out_stamp_slot.clear(); self._out_stamp_slot.hide()
        self._set_glows_visible(False); self._set_color_circles_visible(False)
        for b in self._color_buttons: b.hide()
        self._selected_color_id = 0
        self._update_color_buttons_enabled()
        self._switch_background_for_choice(False)
        self._chosen_stamp = None
        self._reset_details_panel()

    # ---------- UI WIRING ----------
    def _wire_area_handlers(self) -> None:
        a_item = self._area_widgets.get("pick_item")
        if a_item:
            a_item.setCursor(Qt.PointingHandCursor)
            try: a_item.removeEventFilter(self)
            except Exception: pass
            a_item.installEventFilter(self)
        a_stamp = self._area_widgets.get("pick_stamp")
        if a_stamp:
            a_stamp.setCursor(Qt.PointingHandCursor)
            try: a_stamp.removeEventFilter(self)
            except Exception: pass
            a_stamp.installEventFilter(self)

    # ---------- BACKGROUND / LAYERS ----------
    def _apply_background(self):
        pm = self._bg_current or self._bg_default
        if pm:
            scaled = pm.scaled(self._target_size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.bg_label.setPixmap(scaled)
            self.bg_label.setGeometry(0, 0, self._target_size.width(), self._target_size.height())
        self.resize(self._target_size); self.setFixedSize(self._target_size)
        self._raise_stamp_stack()

    def _switch_background_for_choice(self, chosen: bool):
        self._bg_current = self._bg_chosen if chosen else self._bg_default
        self._apply_background()

    def _raise_stamp_stack(self):
        for w in self._glow_widgets: w.raise_()
        for key in ("pick_stamp", "pick_arcon", "pick_item"):
            a = self._area_widgets.get(key)
            if a: a.raise_()
        for slot in (self._pick_stamp_slot, self._pick_arcon_slot, self._pick_item_slot,
                     self._out_stamp_slot, self._color_preview_slot):
            if slot: slot.raise_()
        for b in self._color_buttons: b.raise_()
        if self._out_stamp_slot and self._color_preview_slot:
            self._color_preview_slot.raise_()

    def _set_glows_visible(self, vis: bool):
        for w in self._glow_widgets: w.setVisible(vis)
        self._raise_stamp_stack()

    # ---------- BUTTONS ----------
    def _build_buttons(self):
        btns: Dict[str, dict] = STAMP_UI.get("buttons", {})
        for key, conf in btns.items():
            x, y, w, h = conf["rect"]
            b = QToolButton(self)
            b.setCursor(Qt.PointingHandCursor); b.setAutoRaise(True)
            b.setStyleSheet("QToolButton{background:transparent;border:none;padding:0;}")
            b.setGeometry(x, y, w, h)
            ic_path = conf.get("icon_hover")
            if ic_path:
                b.setProperty("_hover_icon_path", _resolve_resource(ic_path))
                b.installEventFilter(self)
            if key == "close": b.clicked.connect(self._on_close)
            self._buttons[key] = b

    # ---------- COLOR CIRCLES ----------
    def _style_color_btn(self, btn: QToolButton, selected: bool) -> None:
        border = "2px solid #121212" if selected else "2px solid rgba(255,255,255,0.30)"
        btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: {border};
                border-radius: {btn.width() // 2}px;
            }}
            QToolButton:hover {{
                border: 2px solid rgba(255,255,255,0.60);
                background: rgba(255,255,255,0.06);
            }}
        """)

    def _build_color_circles(self) -> None:
        self._color_buttons = []; self._selected_color_id = 0
        circles = STAMP_UI.get("color_circles", []) or []
        default_map = [0, 1, 2, 3, 4]
        for idx, cfg in enumerate(circles):
            if "rect" in cfg:
                x, y, w, h = cfg["rect"]; d = min(int(w), int(h))
            else:
                x, y, d = int(cfg.get("x", 0)), int(cfg.get("y", 0)), int(cfg.get("diameter", 30))
            color_id = int(cfg.get("color_id", default_map[idx] if idx < len(default_map) else 0))
            b = QToolButton(self)
            b.setGeometry(int(x), int(y), int(d), int(d))
            b.setCursor(Qt.PointingHandCursor); b.setAutoRaise(True)
            b.setProperty("color_id", color_id)
            b.clicked.connect(self._on_color_circle_clicked)
            self._style_color_btn(b, selected=(color_id == self._selected_color_id))
            b.hide()
            self._color_buttons.append(b)
        for b in self._color_buttons: b.raise_()

    def _on_color_circle_clicked(self):
        btn = self.sender()
        if not isinstance(btn, QToolButton):
            return

        color_id = _to_int(btn.property("color_id"), 0)

        saved_stamp = self._get_saved_stamp_for_item(self._picked_item) if self._picked_item else None

        # ----------------------------------------------------------
        # Если новой печати ещё не выбрали, но на предмете уже есть печать,
        # разрешаем менять цвет именно существующей печати.
        # ----------------------------------------------------------
        if self._chosen_stamp is None and saved_stamp and color_id != 0:
            tip_payload = self._to_tip_stamp_payload(saved_stamp)

            if isinstance(tip_payload, dict) and tip_payload:
                name = tip_payload.get("Name") or tip_payload.get("name") or ""
                bonuses = list(
                    tip_payload.get("Bonuses")
                    or tip_payload.get("BonusLines")
                    or tip_payload.get("Effects")
                    or []
                )

                self._chosen_stamp = {
                    "Id": _to_int(tip_payload.get("Id") or tip_payload.get("id") or 0, 0),
                    "Name": str(name),
                    "name": str(name),
                    "Color_Id": int(color_id),
                    "ColorId": int(color_id),
                    "Bonuses": list(bonuses),
                    "BonusLines": list(bonuses),
                    "BonusesText": "\n".join(bonuses),
                    "effects": "\n".join(bonuses),
                }

        # Если печати нет вообще и новую печать не выбрали — цветные кнопки ничего не делают.
        if self._chosen_stamp is None and color_id != 0:
            return

        self._selected_color_id = int(color_id)

        for b in self._color_buttons:
            self._style_color_btn(
                b,
                selected=(_to_int(b.property("color_id"), -1) == int(color_id)),
            )

        # Цвет 0 — режим снятия печати.
        if color_id == 0:
            self._remove_stamp_mode = bool(saved_stamp or self._chosen_stamp)
            self._clear_chosen_stamp()
            self._update_color_buttons_enabled()
            self._update_color_preview()
            self._refresh_out_stamp_preview()
            self._raise_stamp_stack()
            return

        self._remove_stamp_mode = False

        if isinstance(self._chosen_stamp, dict):
            self._chosen_stamp["Color_Id"] = int(color_id)
            self._chosen_stamp["ColorId"] = int(color_id)

            self._recalc_chosen_stamp_bonuses()

            self._set_right_details(
                self._chosen_stamp.get("Name"),
                self._chosen_stamp.get("Bonuses") or [],
            )

        if getattr(self, "_stamp_popup", None) and self._stamp_popup.isVisible():
            self._rebuild_pick_stamp_popup()

        self._update_color_preview()
        self._refresh_out_stamp_preview()
        self._update_details_color_from_current()
        self._update_color_buttons_enabled()
        self._raise_stamp_stack()

    def _update_color_buttons_enabled(self) -> None:
        """
        Цветные кнопки должны быть доступны не только после выбора новой печати,
        но и когда предмет уже имеет сохранённую печать.

        Это позволяет:
        - положить предмет с печатью;
        - сразу увидеть результат;
        - сразу поменять цвет существующей печати.
        """
        has_item = bool(self._picked_item)

        saved_stamp = None
        try:
            saved_stamp = self._get_saved_stamp_for_item(self._picked_item) if self._picked_item else None
        except Exception:
            saved_stamp = None

        has_stamp_context = bool(self._chosen_stamp is not None or saved_stamp)

        for b in self._color_buttons:
            cid = _to_int(b.property("color_id"), 0)

            if not has_item:
                b.setEnabled(False)
                continue

            # Кнопка 0 нужна для снятия существующей/выбранной печати.
            if cid == 0:
                b.setEnabled(bool(has_stamp_context))
            else:
                b.setEnabled(bool(has_stamp_context))

    # ---------- GLOWS / AREAS ----------
    def _build_glows(self):
        pm = _load_file_image(_resolve_resource(STAMP_UI.get("glow_icon_path", "resources/stamp_menu/blue_icon.png")))
        for w in self._glow_widgets:
            try: w.hide(); w.deleteLater()
            except Exception: pass
        self._glow_widgets = []
        for g in (STAMP_UI.get("glows") or []):
            x, y, w, h = g.get("rect", (0, 0, 40, 40))
            speed = float(g.get("speed_deg_per_sec", 60.0))
            glow = _RotatingGlow(self, pm, speed)
            glow.setGeometry(int(x), int(y), int(w), int(h))
            glow.hide(); self._glow_widgets.append(glow)
        self._raise_stamp_stack()

    def _build_areas(self):
        areas: Dict[str, dict] = STAMP_UI.get("areas", {})
        for name, conf in areas.items():
            x, y, w, h = conf.get("rect", (0, 0, 10, 10))
            area = QWidget(self); area.setObjectName(name)
            area.setGeometry(x, y, w, h)
            area.setAttribute(Qt.WA_TranslucentBackground, True)
            area.setStyleSheet("background: transparent;")
            self._area_widgets[name] = area

            slot = QLabel(area); slot.setScaledContents(True)
            slot.setStyleSheet("background: transparent;"); slot.setGeometry(0, 0, w, h); slot.hide()

            if name == "pick_item":
                self._pick_item_slot = slot
                slot.setAttribute(Qt.WA_TransparentForMouseEvents, False)
                slot.setMouseTracking(True); slot.installEventFilter(self)
            elif name == "pick_stamp":
                self._pick_stamp_slot = slot
            elif name == "pick_arcon":
                self._pick_arcon_slot = slot
            elif name == "stamp_color_preview":
                self._color_preview_slot = slot
            elif name == "out_stamp":
                self._out_stamp_slot = slot
                slot.setAttribute(Qt.WA_TransparentForMouseEvents, False)
                slot.setMouseTracking(True)
                slot.installEventFilter(self)

        self._raise_stamp_stack()

    # ---------- PICK ITEM POPUP ----------
    def _make_pick_item_popup(self):
        self._pick_popup = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        self._pick_popup.setObjectName("pickPopup")
        (self._pick_popup.setStyleSheet("""
            QFrame#pickPopup { background: rgba(15,15,18,0.94);
                               border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; }
            QToolButton { background: rgba(255,255,255,0.05);
                          border: 1px solid rgba(255,255,255,0.12); border-radius: 8px; padding: 6px; }
            QToolButton:hover { border-color: rgba(255,255,255,0.35); background: rgba(255,255,255,0.08); }
        """))
        self._pick_popup.installEventFilter(self); self._pick_popup.hide()
        self._pick_grid = QGridLayout(self._pick_popup)
        self._pick_grid.setContentsMargins(10, 10, 10, 10)
        self._pick_grid.setHorizontalSpacing(8); self._pick_grid.setVerticalSpacing(8)

    def _rebuild_pick_item_popup(self):
        if not self._pick_popup or not self._pick_grid:
            return

        # очистить сетку
        while self._pick_grid.count():
            it = self._pick_grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        parent = self.parent()
        selected = getattr(parent, "_selected_items", None) if parent else None
        if not isinstance(selected, dict):
            self._pick_popup.adjustSize()
            return

        # собрать предметы (исключая costume/ornament/mount)
        items: list[tuple[str, dict]] = []
        for slot_key, item in selected.items():
            if slot_key in _EXCLUDE_SLOTS:
                continue
            if not isinstance(item, dict) or not item:
                continue
            items.append((str(slot_key), item))

        conf = (STAMP_UI.get("areas") or {}).get("pick_item", {}) or {}
        cols = max(1, int(conf.get("cols", 4)))
        icon_px = max(1, int(conf.get("icon_px", 56)))
        icon_size = QSize(icon_px, icon_px)

        # отсортировать по Slot_Id
        items_sorted = sorted(items, key=lambda t: self._slot_sort_key(t[0], t[1]))

        for idx, (slot_key, item) in enumerate(items_sorted):
            r, c = divmod(idx, cols)

            btn = QToolButton(self._pick_popup)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setAutoRaise(True)
            btn.setIconSize(icon_size)

            # --- грузим базовую иконку ---
            base_pm = None
            try:
                img_id = item.get("Icon_Image_Id") or item.get("Image_Id")
                if img_id:
                    base_pm = self._load_pm_by_image_id(int(img_id))
            except Exception:
                base_pm = None

            # --- накладываем бейдж элемента (как в reforge.py), либо просто скейлим ---
            if base_pm and not base_pm.isNull():
                final_pm = None
                try:
                    eid = int(self._element_id_for_item(item) or 0)
                except Exception:
                    eid = 0

                if eid > 0 and hasattr(self, "_compose_with_element_badge"):
                    try:
                        final_pm = self._compose_with_element_badge(base_pm, icon_size, eid, item)
                    except Exception:
                        final_pm = None

                if not final_pm or final_pm.isNull():
                    final_pm = base_pm.scaled(icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

                btn.setIcon(QIcon(final_pm))
            else:
                btn.setIcon(QIcon())

            # ❗️ВАЖНО: НЕ используем property "slot_key"/"item_dict"
            # иначе глобальный обработчик из weapon_equipment_button принимает это за слот экипировки.
            btn.setProperty("_sw_slot_key", slot_key)
            btn.setProperty("_sw_item_dict", item)

            btn.installEventFilter(self)
            btn.clicked.connect(self._on_pick_item_clicked)

            self._pick_grid.addWidget(btn, r, c)

        self._pick_popup.adjustSize()

    def _show_pick_item_popup(self):
        # новый формат: открываем ChooseMenuAll (24 слота на фоне equip_choose.png)
        anchor = self._area_widgets.get("pick_item") or self._pick_item_slot
        if not anchor:
            return

        # убедимся, что инстанс меню существует
        cm = getattr(self, "_choose_menu_all", None)
        if cm is None:
            try:
                self._choose_menu_all = ChooseMenuAll(self, config=ChooseMenuConfig())
                cm = self._choose_menu_all
            except Exception:
                cm = None

        # если по какой-то причине меню не создалось — fallback на старый попап
        if cm is None:
            self._rebuild_pick_item_popup()
            if not self._pick_popup:
                return
            hint = self._pick_popup.sizeHint()
            tl = anchor.mapToGlobal(anchor.rect().bottomLeft())
            x, y = tl.x(), tl.y() + 6
            scr = (self.window().screen().availableGeometry()
                   if self.window() else QApplication.primaryScreen().availableGeometry())
            if x + hint.width() > scr.right() - 6:
                x = max(scr.left() + 6, scr.right() - hint.width() - 6)
            if y + hint.height() > scr.bottom() - 6:
                y = anchor.mapToGlobal(anchor.rect().topLeft()).y() - hint.height() - 6
            self._pick_popup.move(x, y)
            self._pick_popup.show()
            return

        # собрать предметы (исключая costume/ornament/mount)
        parent = self.parent()
        selected = getattr(parent, "_selected_items", None) if parent else None
        items: List[Tuple[str, dict]] = []
        if isinstance(selected, dict):
            for sk, it in selected.items():
                if sk in _EXCLUDE_SLOTS:
                    continue
                if not isinstance(it, dict) or not it:
                    continue
                items.append((str(sk), dict(it)))

        # порядок как в старом попапе: по Slot_Id (и fallback)
        items_sorted = sorted(items, key=lambda t: self._slot_sort_key(t[0], t[1]))

        def _icon_provider(it: dict) -> Optional[QPixmap]:
            try:
                img_id = it.get("Icon_Image_Id") or it.get("Image_Id")
                if not img_id:
                    return None
                base_pm = self._load_pm_by_image_id(int(img_id))
            except Exception:
                base_pm = None

            if not base_pm or base_pm.isNull():
                return None

            canvas = QSize(50, 50)
            try:
                eid = int(self._element_id_for_item(it) or 0)
            except Exception:
                eid = 0

            try:
                if eid > 0:
                    return self._compose_with_element_badge(base_pm, canvas, eid, it)
            except Exception:
                pass

            return base_pm.scaled(canvas, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        def _on_pick(sk: str, it: dict) -> None:
            self._apply_picked_item(sk, it)

        def _on_hover_enter(cell: QWidget, sk: str, it: dict) -> None:
            tip_item = dict(it or {})
            tip_item["slot_key"] = str(sk)

            saved = self._get_saved_stamp_for_item(tip_item)
            stamp_tip = self._to_tip_stamp_payload(saved) if saved else None
            self._show_item_tip(cell, tip_item, force_stamp_payload=stamp_tip)

        def _on_hover_leave(cell: QWidget) -> None:
            self._tip_leave_for(cell)

        cm.open_for(
            anchor_widget=anchor,
            items=items_sorted,
            icon_provider=_icon_provider,
            on_pick=_on_pick,
            on_hover_enter=_on_hover_enter,
            on_hover_leave=_on_hover_leave,
        )

    # ---------- LOAD STAMP BONUSES ----------
    def _load_stamp_bonuses(self, stamp_id: int, color_id: int, internal_level: int | None = None) -> list[str]:
        parent = self.parent()
        if not parent or not hasattr(parent, "data"):
            return []
        conn = parent.data.conn

        # >>> ГЛАВНОЕ: используем internal_level предмета, а не Level
        if internal_level is None:
            internal_level = self._get_internal_level_for_item(self._picked_item)

        # выбрать вариант нужного цвета (fallback: max Color_Id)
        row = conn.execute(
            "SELECT Id FROM StampVariant WHERE Stamp_Id=? AND Color_Id=? LIMIT 1",
            (int(stamp_id), int(color_id)),
        ).fetchone()
        if row:
            variant_id = int(row[0])
        else:
            row = conn.execute(
                "SELECT Id FROM StampVariant WHERE Stamp_Id=? ORDER BY Color_Id DESC LIMIT 1",
                (int(stamp_id),),
            ).fetchone()
            if not row:
                return []
            variant_id = int(row[0])

        # наличие колонок
        def _has_col(table: str, col: str) -> bool:
            try:
                return any((r["name"] if hasattr(r, "keys") else r[1]) == col
                           for r in conn.execute(f"PRAGMA table_info({table})").fetchall())
            except Exception:
                return False

        bt_name_col = None
        try:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='BonusType'").fetchone():
                for cand in ("Name", "Title", "DisplayName", "Template", "Text", "Label"):
                    if _has_col("BonusType", cand):
                        bt_name_col = cand
                        break
        except Exception:
            bt_name_col = None

        join_bonus_type = bt_name_col is not None and _has_col("StampVariantBonus", "Type_Id")
        order_col = "OrderIndex" if _has_col("StampVariantBonus", "OrderIndex") else "rowid"

        if join_bonus_type:
            rows = conn.execute(f"""
                SELECT svb.QualityValue AS val, svb.Type_Id AS type_id, bt.{bt_name_col} AS bname
                FROM StampVariantBonus svb
                LEFT JOIN BonusType bt ON bt.Id = svb.Type_Id
                WHERE svb.StampVariant_Id = ?
                ORDER BY svb.{order_col}
            """, (variant_id,)).fetchall()
        else:
            rows = conn.execute(
                f"SELECT QualityValue AS val FROM StampVariantBonus WHERE StampVariant_Id=? ORDER BY {order_col}",
                (variant_id,),
            ).fetchall()

        out: list[str] = []
        max_level = min(60, self._get_max_player_level())

        import re

        def _format_value_for_template(template: str, value: int) -> str:
            """
            Если первый значимый плейсхолдер в шаблоне — {0},
            то перед положительным значением ставим плюс.

            Примеры:
                "{0} к Силе"              -> "+7 к Силе"
                "Урон увеличен на {0}"    -> "Урон увеличен на 7"
                "+{0} к Силе"             -> "+7 к Силе", без "++7"
            """
            tpl = str(template or "")

            try:
                match = re.search(r"\{0\}", tpl)
            except Exception:
                match = None

            if not match:
                return str(value)

            try:
                prefix = tpl[:match.start()]
                is_first_meaningful = prefix.strip() == ""

                if is_first_meaningful and int(value) > 0:
                    # если перед {0} уже руками стоит знак, второй плюс не добавляем
                    raw_prefix = prefix.rstrip()
                    if raw_prefix.endswith("+") or raw_prefix.endswith("-"):
                        return str(value)
                    return f"+{value}"
            except Exception:
                pass

            return str(value)

        for r in rows or []:
            if hasattr(r, "keys"):
                base_val = r["val"]
                name_tpl = (
                    r.get("bname", "") if isinstance(r, dict) else (r["bname"] if "bname" in r.keys() else "")
                ).strip()
                type_id = r.get("type_id", None) if isinstance(r, dict) else (
                    r["type_id"] if "type_id" in r.keys() else None
                )
            else:
                base_val = r[0]
                name_tpl = ""
                type_id = None

            minc, maxc = self._get_bonus_type_coefs(int(type_id)) if type_id is not None else (1.0, 1.0)
            scaled_val = self._get_stamp_value(
                base_value=_to_float(base_val, 0.0),
                internal_level=float(internal_level or 1),
                min_coef=minc,
                max_coef=maxc,
                min_level=1,
                max_level=float(max_level),
            )

            if name_tpl and "{0}" in name_tpl:
                try:
                    display_val = _format_value_for_template(name_tpl, int(scaled_val))
                    out.append(name_tpl.format(display_val))
                except Exception:
                    out.append(f"{scaled_val} к {name_tpl}")
            elif name_tpl:
                out.append(f"{scaled_val} к {name_tpl}")
            else:
                out.append(str(scaled_val))

        return out

    # ---------- STAMP LIST POPUP ----------
    def _clear_layout(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None); w.deleteLater(); continue
            sub = it.layout()
            if sub is not None: self._clear_layout(sub)

    def _rebuild_pick_stamp_popup(self):
        if not self._stamp_list_box:
            return
        self._ensure_bucket()
        self._clear_layout(self._stamp_list_box)

        self._stamp_allowed_map = {}

        if not self._picked_item:
            placeholder = QLabel("—", self._stamp_area.widget())
            placeholder.setStyleSheet("""
                color:#cfe6a5; border:1px solid rgba(255,255,255,0.10);
                border-radius:8px; padding:8px; background: rgba(255,255,255,0.04);
            """)
            self._stamp_list_box.addWidget(placeholder)
            self._stamp_list_box.addStretch(1)
            self._stamp_popup.adjustSize()
            try:
                self._place_stamp_vscroll()
            except Exception:
                pass
            return

        color_for_list = 4
        type_id = _to_int(self._picked_item.get("Type_Id") or self._picked_item.get("TypeId") or 0, 0)

        parent = self.parent()
        conn = getattr(getattr(parent, "data", None), "conn", None)
        if conn is None or type_id <= 0:
            placeholder = QLabel("—", self._stamp_area.widget())
            placeholder.setStyleSheet("""
                color:#cfe6a5; border:1px solid rgba(255,255,255,0.10);
                border-radius:8px; padding:8px; background: rgba(255,255,255,0.04);
            """)
            self._stamp_list_box.addWidget(placeholder)
            self._stamp_list_box.addStretch(1)
            self._stamp_popup.adjustSize()
            try:
                self._place_stamp_vscroll()
            except Exception:
                pass
            return

        # ------------------------- helpers -------------------------
        def _rows_are_mapping(r) -> bool:
            return hasattr(r, "keys")

        def _table_exists(name: str) -> bool:
            try:
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
                    (name,),
                ).fetchone()
                return bool(row)
            except Exception:
                return False

        def _to_int_or_none(v):
            if v is None:
                return None
            try:
                return int(v)
            except Exception:
                try:
                    return int(float(str(v).strip()))
                except Exception:
                    return None

        def _equip_exists(eid: int) -> bool:
            try:
                row = conn.execute("SELECT 1 FROM Equipment WHERE Id=? LIMIT 1", (int(eid),)).fetchone()
                return bool(row)
            except Exception:
                return False

        def _resolve_equipment_template_id(it: dict) -> int:
            keys = ("Equipment_Id", "Equip_Id", "TemplateId", "Template_Id", "Item_Id", "Id")
            for k in keys:
                if k in it and it[k] not in (None, ""):
                    try:
                        eid = int(float(str(it[k]).strip()))
                    except Exception:
                        continue
                    if eid > 0 and _equip_exists(eid):
                        return int(eid)
            return 0

        def _get_eqcond_cols():
            cached = getattr(self, "_sw_eqcond_cols", None)
            if isinstance(cached, tuple) and len(cached) == 2:
                return cached[0], cached[1]

            if not _table_exists("EquipmentCondition"):
                self._sw_eqcond_cols = (None, None)
                return (None, None)

            try:
                info = conn.execute('PRAGMA table_info("EquipmentCondition")').fetchall()
            except Exception:
                info = []

            cols = []
            for r in info or []:
                try:
                    nm = r["name"] if _rows_are_mapping(r) else r[1]
                except Exception:
                    nm = None
                if nm:
                    cols.append(str(nm))

            cols_lc = {c.lower(): c for c in cols}

            def _pick(cands):
                for c in cands:
                    if c.lower() in cols_lc:
                        return cols_lc[c.lower()]
                return None

            equip_col = _pick(("Equipment_Id", "Equip_Id", "Item_Id", "EquipmentId", "EquipId"))
            class_col = _pick(("Class_Id", "ClassId", "PlayerClass_Id", "RequiredClass_Id", "NeedClass_Id"))

            if equip_col is None:
                for c in cols:
                    lc = c.lower()
                    if "equip" in lc and "id" in lc:
                        equip_col = c
                        break
            if class_col is None:
                for c in cols:
                    lc = c.lower()
                    if "class" in lc and "id" in lc:
                        class_col = c
                        break

            self._sw_eqcond_cols = (equip_col, class_col)
            return equip_col, class_col

        def _load_effective_class_meta(class_id: int):
            """(PrimaryStat_Id, EnergyStat_Id, IsMelee) с наследованием Base_Id."""
            cid0 = int(class_id or 0)
            if cid0 <= 0 or not _table_exists("Class"):
                return (0, 0, None)

            cache = getattr(self, "_sw_class_meta_cache", None)
            if not isinstance(cache, dict):
                cache = {}
                self._sw_class_meta_cache = cache

            if cid0 in cache:
                return cache[cid0]

            visited = set()
            cid = cid0
            ps = 0
            es = 0
            im = None

            hop = 0
            while cid > 0 and cid not in visited and hop < 12:
                hop += 1
                visited.add(cid)
                try:
                    r = conn.execute(
                        "SELECT Base_Id, PrimaryStat_Id, EnergyStat_Id, IsMelee FROM Class WHERE Id=? LIMIT 1",
                        (int(cid),),
                    ).fetchone()
                except Exception:
                    r = None

                if not r:
                    break

                if _rows_are_mapping(r):
                    base_id = _to_int_or_none(r["Base_Id"]) or 0
                    ps_raw = _to_int_or_none(r["PrimaryStat_Id"]) or 0
                    es_raw = _to_int_or_none(r["EnergyStat_Id"]) or 0
                    im_raw = _to_int_or_none(r["IsMelee"])
                else:
                    base_id = _to_int_or_none(r[0]) or 0
                    ps_raw = _to_int_or_none(r[1]) or 0
                    es_raw = _to_int_or_none(r[2]) or 0
                    im_raw = _to_int_or_none(r[3])

                if ps <= 0 and ps_raw > 0:
                    ps = int(ps_raw)
                if es <= 0 and es_raw > 0:
                    es = int(es_raw)
                if im is None and im_raw is not None:
                    im = int(im_raw)

                cid = int(base_id)
                if ps > 0 and es > 0 and im is not None:
                    break

            cache[cid0] = (int(ps), int(es), im)
            return cache[cid0]

        def _all_gate_stats_roots():
            """
            Корневые gate-статы: все PrimaryStat_Id и EnergyStat_Id по всем классам.
            (без потомков)
            """
            cached = getattr(self, "_sw_gate_stats_all", None)
            if isinstance(cached, set) and cached:
                return cached

            s = set()
            if _table_exists("Class"):
                try:
                    rr = conn.execute("SELECT Id FROM Class").fetchall()
                except Exception:
                    rr = []
                for row in rr or []:
                    cid = int(row["Id"] if _rows_are_mapping(row) else row[0])
                    ps, es, _im = _load_effective_class_meta(cid)
                    if ps > 0:
                        s.add(int(ps))
                    if es > 0:
                        s.add(int(es))

            self._sw_gate_stats_all = s
            return s

        # --- NEW: дерево статов по Parent_Id ---
        def _stat_children_map() -> dict:
            """
            parent_stat_id -> set(child_stat_id)
            кешируется на окно, чтобы не долбить БД каждый раз.
            """
            cached = getattr(self, "_sw_stat_children_map", None)
            if isinstance(cached, dict):
                return cached

            ch: dict[int, set[int]] = {}
            if not _table_exists("Stat"):
                self._sw_stat_children_map = ch
                return ch

            try:
                rows = conn.execute(
                    "SELECT Id, Parent_Id FROM Stat WHERE Parent_Id IS NOT NULL"
                ).fetchall()
            except Exception:
                rows = []

            for r in rows or []:
                if _rows_are_mapping(r):
                    sid = _to_int_or_none(r["Id"]) or 0
                    pid = _to_int_or_none(r["Parent_Id"]) or 0
                else:
                    sid = _to_int_or_none(r[0]) or 0
                    pid = _to_int_or_none(r[1]) or 0

                if sid > 0 and pid > 0:
                    ch.setdefault(int(pid), set()).add(int(sid))

            self._sw_stat_children_map = ch
            return ch

        def _expand_stat_family(seed_ids: set[int]) -> set[int]:
            """
            seed + все потомки по цепочке Parent_Id (дети/внуки/…)
            """
            if not seed_ids:
                return set()
            ch = _stat_children_map()
            out = set(int(x) for x in seed_ids if int(x) > 0)
            stack = list(out)
            while stack:
                p = stack.pop()
                kids = ch.get(int(p))
                if not kids:
                    continue
                for c in kids:
                    if c not in out:
                        out.add(int(c))
                        stack.append(int(c))
            return out

        # оружие = EquipmentType.IsMeleeWeapon != NULL или EquipmentType.IsSingleHandWeapon != NULL
        def _is_weapon_type(etid: int) -> bool:
            if etid <= 0 or not _table_exists("EquipmentType"):
                return False
            try:
                r = conn.execute(
                    "SELECT IsMeleeWeapon, IsSingleHandWeapon FROM EquipmentType WHERE Id=? LIMIT 1",
                    (int(etid),),
                ).fetchone()
            except Exception:
                r = None
            if not r:
                return False
            if _rows_are_mapping(r):
                a = r["IsMeleeWeapon"]
                b = r["IsSingleHandWeapon"]
            else:
                a, b = r[0], r[1]
            return (a is not None) or (b is not None)

        weapon_force_filters = _is_weapon_type(int(type_id))

        # ------------------------- rule 1: candidates by type -------------------------
        try:
            rows = conn.execute("""
                SELECT DISTINCT s.Id AS Id, s.Name AS Name
                FROM Stamp s
                JOIN StampEquipment se ON se.Stamp_Id = s.Id
                WHERE s.IsLegacy = 0 AND se.Type_Id = ?
                ORDER BY s.Name COLLATE NOCASE
            """, (type_id,)).fetchall()
        except Exception:
            rows = []

        candidates = []
        for r in rows or []:
            st_id = int(r["Id"] if _rows_are_mapping(r) else r[0])
            st_name = str((r["Name"] if _rows_are_mapping(r) else r[1]) or "")
            if st_id > 0:
                candidates.append((st_id, st_name))

        if not candidates:
            placeholder = QLabel("—", self._stamp_area.widget())
            placeholder.setStyleSheet("""
                color:#cfe6a5; border:1px solid rgba(255,255,255,0.10);
                border-radius:8px; padding:8px; background: rgba(255,255,255,0.04);
            """)
            self._stamp_list_box.addWidget(placeholder)
            self._stamp_list_box.addStretch(1)
            self._stamp_popup.adjustSize()
            try:
                self._place_stamp_vscroll()
            except Exception:
                pass
            return

        # ------------------------- detect universal / allowed classes -------------------------
        equipment_id = _resolve_equipment_template_id(self._picked_item or {})
        equip_col, class_col = _get_eqcond_cols()

        is_universal_item = True
        allowed_class_ids = []

        if equipment_id > 0 and equip_col and _table_exists("EquipmentCondition"):
            try:
                row_any = conn.execute(
                    f'SELECT 1 FROM "EquipmentCondition" WHERE "{equip_col}"=? LIMIT 1',
                    (int(equipment_id),),
                ).fetchone()
                is_universal_item = not bool(row_any)
            except Exception:
                is_universal_item = True

            if not is_universal_item and class_col:
                try:
                    rr = conn.execute(
                        f'SELECT DISTINCT "{class_col}" FROM "EquipmentCondition" WHERE "{equip_col}"=?',
                        (int(equipment_id),),
                    ).fetchall()
                except Exception:
                    rr = []
                for r in rr or []:
                    v = (r[class_col] if _rows_are_mapping(r) else r[0])
                    cid = _to_int_or_none(v) or 0
                    if cid > 0:
                        allowed_class_ids.append(int(cid))

        if equipment_id > 0 and equip_col and _table_exists("EquipmentCondition") and class_col is None:
            try:
                row_any = conn.execute(
                    f'SELECT 1 FROM "EquipmentCondition" WHERE "{equip_col}"=? LIMIT 1',
                    (int(equipment_id),),
                ).fetchone()
                if row_any:
                    is_universal_item = False
            except Exception:
                pass

        player_class_id = int(getattr(self, "_player_class_id", None) or 0)

        if (not is_universal_item) and allowed_class_ids:
            eff_class_ids = []
            seen = set()
            for x in allowed_class_ids:
                xi = int(x)
                if xi > 0 and xi not in seen:
                    seen.add(xi)
                    eff_class_ids.append(xi)
        else:
            eff_class_ids = [player_class_id] if player_class_id > 0 else []

        eff_primary = set()
        eff_energy = set()
        eff_is_melee_vals = set()
        melee_filter_disabled = False

        for cid in eff_class_ids:
            ps, es, im = _load_effective_class_meta(int(cid))
            if ps > 0:
                eff_primary.add(int(ps))
            if es > 0:
                eff_energy.add(int(es))
            if im is None:
                melee_filter_disabled = True
            else:
                try:
                    iv = int(im)
                    if iv in (0, 1):
                        eff_is_melee_vals.add(iv)
                except Exception:
                    melee_filter_disabled = True

        # --- NEW: расширяем “доступные статы класса” по Parent_Id ---
        eff_primary_family = _expand_stat_family(set(eff_primary))
        eff_energy_family = _expand_stat_family(set(eff_energy))

        allowed_gate_stats = set(eff_primary_family) | set(eff_energy_family)

        gate_roots_all = _all_gate_stats_roots()
        gate_stats_all = _expand_stat_family(set(gate_roots_all))

        # ВАЖНО: правило 3 должно работать для оружия даже если предмет "универсальный"
        allowed_melee_vals = None
        if ((not is_universal_item) or weapon_force_filters) and (not melee_filter_disabled) and eff_is_melee_vals:
            allowed_melee_vals = set(eff_is_melee_vals)

        # ------------------------- stamp -> stats (+ Stat.IsMelee set) -------------------------
        stamp_ids = [sid for sid, _ in candidates]
        stamp_to_stats = {int(sid): set() for sid in stamp_ids}
        stamp_to_stat_melee = {int(sid): set() for sid in stamp_ids}

        if stamp_ids and _table_exists("StampVariant") and _table_exists("StampVariantBonus") and _table_exists(
                "BonusTypeStat"):
            step = 500
            for i in range(0, len(stamp_ids), step):
                chunk = stamp_ids[i:i + step]
                ph = ",".join(["?"] * len(chunk))
                try:
                    rr = conn.execute(
                        f"""
                        SELECT sv.Stamp_Id AS stamp_id,
                               bts.Stat_Id AS stat_id,
                               st.IsMelee AS stat_is_melee
                        FROM StampVariant sv
                        JOIN StampVariantBonus svb ON svb.StampVariant_Id = sv.Id
                        JOIN BonusTypeStat bts ON bts.BonusType_Id = svb.Type_Id
                        LEFT JOIN Stat st ON st.Id = bts.Stat_Id
                        WHERE sv.Stamp_Id IN ({ph})
                        """,
                        tuple(int(x) for x in chunk),
                    ).fetchall()
                except Exception:
                    rr = []

                for r in rr or []:
                    if _rows_are_mapping(r):
                        sid = _to_int_or_none(r["stamp_id"]) or 0
                        stid = _to_int_or_none(r["stat_id"]) or 0
                        try:
                            keys = r.keys()
                            ism = r["stat_is_melee"] if ("stat_is_melee" in keys) else None
                        except Exception:
                            try:
                                ism = r["stat_is_melee"]
                            except Exception:
                                ism = None
                    else:
                        sid = _to_int_or_none(r[0]) or 0
                        stid = _to_int_or_none(r[1]) or 0
                        ism = (r[2] if len(r) > 2 else None)

                    if sid <= 0 or stid <= 0:
                        continue

                    stamp_to_stats.setdefault(int(sid), set()).add(int(stid))
                    if ism is not None:
                        try:
                            iv = int(ism)
                            if iv in (0, 1):
                                stamp_to_stat_melee.setdefault(int(sid), set()).add(iv)
                        except Exception:
                            pass

        # ------------------------- apply rules 2/3/4 + strict foreign gate -------------------------
        allowed_list = []  # (group, name, stamp_id)

        for sid, name in candidates:
            sid = int(sid)
            st_stats = stamp_to_stats.get(sid, set()) or set()

            # правило 4 ОТКЛЮЧАЕМ для оружия:
            if is_universal_item and (not weapon_force_filters):
                self._stamp_allowed_map[sid] = 2
                allowed_list.append((2, str(name), sid))
                continue

            # правило 3 (IsMelee) — работает и для оружия
            if allowed_melee_vals is not None:
                smv = stamp_to_stat_melee.get(sid, set()) or set()
                if smv and (not smv.issubset(allowed_melee_vals)):
                    continue

            if not st_stats:
                self._stamp_allowed_map[sid] = 2
                allowed_list.append((2, str(name), sid))
                continue

            touched_gate = bool(st_stats & gate_stats_all)
            if not touched_gate:
                self._stamp_allowed_map[sid] = 2
                allowed_list.append((2, str(name), sid))
                continue

            # строгий запрет "чужих" gate-статов (с учётом Parent_Id)
            foreign_gate = st_stats & (gate_stats_all - allowed_gate_stats)
            if foreign_gate:
                continue

            # --- NEW: группируем тоже по семействам ---
            if eff_primary_family and (st_stats & eff_primary_family):
                self._stamp_allowed_map[sid] = 0
                allowed_list.append((0, str(name), sid))
                continue

            if eff_energy_family and (st_stats & eff_energy_family):
                self._stamp_allowed_map[sid] = 1
                allowed_list.append((1, str(name), sid))
                continue

            continue

        if not allowed_list:
            placeholder = QLabel("—", self._stamp_area.widget())
            placeholder.setStyleSheet("""
                color:#cfe6a5; border:1px solid rgba(255,255,255,0.10);
                border-radius:8px; padding:8px; background: rgba(255,255,255,0.04);
            """)
            self._stamp_list_box.addWidget(placeholder)
            self._stamp_list_box.addStretch(1)
            self._stamp_popup.adjustSize()
            try:
                self._place_stamp_vscroll()
            except Exception:
                pass
            return

        allowed_list.sort(key=lambda x: (int(x[0]), _norm(x[1]), int(x[2])))

        # ------------------------- UI build -------------------------
        q = getattr(self, "_stamp_search_text", "") or ""
        show_count = 0

        for group, name, st_id in allowed_list:
            bonuses = self._load_stamp_bonuses(int(st_id), color_for_list)
            if not self._search_match(str(name), bonuses, q):
                continue

            show_count += 1

            roww = QWidget(self._stamp_area.widget())
            hl = QHBoxLayout(roww)
            hl.setContentsMargins(8, 6, 8, 6)
            hl.setSpacing(16)

            roww.setCursor(Qt.PointingHandCursor)
            roww.setProperty("stamp_id", int(st_id))
            roww.setProperty("stamp_name", str(name))
            roww.setProperty("stamp_bonuses", bonuses)
            roww.installEventFilter(self)

            lbl_name = QLabel(str(name), roww)
            lbl_name.setProperty("nameCol", True)
            lbl_name.setWordWrap(True)
            lbl_name.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
            lbl_name.setAttribute(Qt.WA_TransparentForMouseEvents, True)

            lbl_bon = QLabel("  \n".join(bonuses) if bonuses else "—", roww)
            lbl_bon.setProperty("bonCol", True)
            lbl_bon.setWordWrap(True)
            lbl_bon.setMinimumWidth(280)
            lbl_bon.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lbl_bon.setStyleSheet("""
                color:#cfe6a5; border:1px solid rgba(255,255,255,0.10);
                border-radius:8px; padding:8px; background: rgba(255,255,255,0.04);
            """)

            hl.addWidget(lbl_name, 1)
            hl.addWidget(lbl_bon, 2)
            self._stamp_list_box.addWidget(roww)

        if show_count == 0:
            placeholder = QLabel("Ничего не найдено", self._stamp_area.widget())
            placeholder.setStyleSheet("""
                color:#cfe6a5; border:1px solid rgba(255,255,255,0.10);
                border-radius:8px; padding:8px; background: rgba(255,255,255,0.04);
            """)
            self._stamp_list_box.addWidget(placeholder)

        self._stamp_list_box.addStretch(1)
        self._stamp_popup.adjustSize()
        try:
            self._place_stamp_vscroll()
        except Exception:
            pass

    def _make_pick_stamp_popup(self):
        self._stamp_popup = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        self._stamp_popup.setObjectName("stampPopup")
        self._stamp_popup.setStyleSheet("""
            QFrame#stampPopup { background: rgba(15,15,18,0.96);
                                border: 1px solid rgba(255,255,255,0.12);
                                border-radius: 10px; }
            QLabel[nameCol] { color:#eaeaea; font-weight:600; }
            QLabel[bonCol]  { color:#cbd3df; }
        """)
        self._stamp_popup.installEventFilter(self); self._stamp_popup.hide()

        # поиск
        top_bar = QWidget(self._stamp_popup)
        top_lay = QHBoxLayout(top_bar)
        top_lay.setContentsMargins(10, 10, 10, 6)
        self._stamp_search_edit = QLineEdit(top_bar)
        self._stamp_search_edit.setPlaceholderText("Поиск предмета (название / бонусы)")
        self._stamp_search_edit.setClearButtonEnabled(True)
        self._stamp_search_edit.textChanged.connect(self._on_stamp_search_changed)
        top_lay.addWidget(self._stamp_search_edit)

        self._stamp_area = QScrollArea(self._stamp_popup)
        self._stamp_area.setFrameShape(QFrame.NoFrame)
        self._stamp_area.setWidgetResizable(True)
        self._stamp_area.setMinimumSize(560, 320)

        cont = QWidget()
        self._stamp_area.setWidget(cont)
        self._stamp_list_box = QVBoxLayout(cont)
        self._stamp_list_box.setContentsMargins(12, 12, 12, 12)
        self._stamp_list_box.setSpacing(10)

        # общий лэйаут попапа
        lay = QVBoxLayout(self._stamp_popup)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(top_bar)  # ← добавили панель поиска
        lay.addWidget(self._stamp_area)

    def _show_pick_stamp_popup(self):
        """
        Новый формат: открываем ChooseStampMenu (фон stamp_choose.png + блоки stamp_block.png).
        Данные берём из текущей логики _rebuild_pick_stamp_popup (она строит список и вешает свойства stamp_id/...).
        """
        # сначала пересобрать список печатей (в невидимом popup) — это и фильтр, и поиск
        self._rebuild_pick_stamp_popup()

        anchor = self._area_widgets.get("pick_stamp")
        if not anchor:
            return

        cm = getattr(self, "_choose_stamp_menu", None)
        if cm is None:
            try:
                self._choose_stamp_menu = ChooseStampMenu(self, config=StampChooseConfig())
                cm = self._choose_stamp_menu
            except Exception:
                cm = None

        # Fallback: если меню не создалось — показываем старый popup как раньше
        if cm is None:
            if not self._stamp_popup:
                return
            hint = self._stamp_popup.sizeHint()
            tl = anchor.mapToGlobal(anchor.rect().bottomLeft())
            x, y = tl.x(), tl.y() + 6
            scr = (self.window().screen().availableGeometry()
                   if self.window() else QApplication.primaryScreen().availableGeometry())
            if x + hint.width() > scr.right() - 6:
                x = max(scr.left() + 6, scr.right() - hint.width() - 6)
            if y + hint.height() > scr.bottom() - 6:
                y = anchor.mapToGlobal(anchor.rect().topLeft()).y() - hint.height() - 6
            self._stamp_popup.move(x, y)
            self._stamp_popup.show()
            self._stamp_popup.raise_()
            self._stamp_popup.activateWindow()
            QTimer.singleShot(0, self._place_stamp_vscroll)
            # фокус на старую строку поиска
            if self._stamp_search_edit:
                QTimer.singleShot(0, lambda: (self._stamp_search_edit.setFocus(), self._stamp_search_edit.selectAll()))
            return

        # собрать entries из уже построенных строк (roww.setProperty(...))
        entries: list[dict] = []
        lb = getattr(self, "_stamp_list_box", None)
        if lb is not None:
            for i in range(lb.count()):
                it = lb.itemAt(i)
                w = it.widget() if it else None
                if w is None:
                    continue
                sid = _to_int(w.property("stamp_id"), 0)
                if sid <= 0:
                    continue
                name = w.property("stamp_name") or ""
                bons = w.property("stamp_bonuses") or []
                entries.append({"id": int(sid), "name": str(name), "bonuses": list(bons or [])})

        def _on_pick_stamp(stamp_id: int, stamp_name: str, bonuses: list[str]) -> None:
            self._select_stamp_in_ui(int(stamp_id), str(stamp_name), list(bonuses or []),
                                     int(self._selected_color_id or 0))
            self._hide_pick_stamp_popup()

        cm.open_for(
            anchor_widget=anchor,
            entries=entries,
            on_pick=_on_pick_stamp,
            on_search_changed=self._on_stamp_search_changed,
            initial_search=getattr(self, "_stamp_search_text", "") or "",
            focus_search=True,  # <-- фокус в поиск сразу
        )

    # ---------- VIS UTILS ----------
    def _hide_pick_item_popup(self):
        # старый попап
        if getattr(self, "_pick_popup", None) and self._pick_popup.isVisible():
            self._pick_popup.hide()

        # новое меню
        cm = getattr(self, "_choose_menu_all", None)
        if cm is not None and cm.isVisible():
            try:
                cm.hide()
            except Exception:
                pass

        self._hide_any_tip()

    def _hide_pick_stamp_popup(self):
        # старый попап
        if getattr(self, "_stamp_popup", None) and self._stamp_popup.isVisible():
            self._stamp_popup.hide()

        # новое меню
        cm = getattr(self, "_choose_stamp_menu", None)
        if cm is not None and cm.isVisible():
            try:
                cm.hide()
            except Exception:
                pass

        self._hide_any_tip()

    def _get_class_start_levels(self) -> Dict[int, List[Tuple[int, str]]]:
        """
        Возвращает мапу:
            Type_Id -> [(start_level_0, class_name_0), (start_level_1, class_name_1), ...]
        где список отсортирован по start_level по возрастанию.

        Выбор класса потом делается интервалами:
            Level[i] <= internal_level < Level[i+1]  ->  Name[i]
            для последнего i верхняя граница = +inf

        Если не удаётся понять привязку EquipmentType <-> EquipmentClass,
        строим "глобальную" шкалу по EquipmentClass и кладём её в ключ 0.

        Fallback (если БД недоступна): строим шкалу из CLASS_THRESHOLDS.

        Важно: всегда гарантируем наличие ключа 0 (глобальная шкала),
        чтобы _determine_item_grade не падал на неизвестных Type_Id.
        """
        cached = getattr(self, "_class_start_levels_cache", None)
        if isinstance(cached, dict) and cached:
            return cached

        res: Dict[int, List[Tuple[int, str]]] = {}

        # берём conn так же, как во всём окне: через parent.data.conn
        conn = None
        try:
            p = self.parent()
            conn = p.data.conn if (p and hasattr(p, "data") and hasattr(p.data, "conn")) else None
        except Exception:
            conn = None
        if conn is None:
            conn = getattr(self, "conn", None)

        def _rows_are_mapping(row) -> bool:
            return hasattr(row, "keys")

        def _table_exists(name: str) -> bool:
            try:
                r = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)
                ).fetchone()
                return bool(r)
            except Exception:
                return False

        def _table_names() -> list[str]:
            try:
                rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                return [r["name"] if _rows_are_mapping(r) else r[0] for r in rows]
            except Exception:
                return []

        def _cols_of(tbl: str) -> list[str]:
            try:
                rows = conn.execute(f"PRAGMA table_info('{tbl}')").fetchall()
            except Exception:
                return []
            out: list[str] = []
            for r in rows:
                out.append(r["name"] if _rows_are_mapping(r) else r[1])
            return out

        def _pick_col(cols: list[str], candidates: tuple[str, ...]) -> Optional[str]:
            cols_lc = {c.lower(): c for c in cols}
            for cand in candidates:
                if cand.lower() in cols_lc:
                    return cols_lc[cand.lower()]
            return None

        def _dedupe_and_sort(entries: list[tuple[int, int, str]]) -> list[tuple[int, str]]:
            """
            entries: [(level, class_id, name), ...]
            -> [(level, name), ...] sorted, без дублей по level (берём минимальный class_id на этот level)
            """
            entries_sorted = sorted(entries, key=lambda x: (int(x[0]), int(x[1])))
            out: list[tuple[int, str]] = []
            seen_levels: set[int] = set()
            for lv, _cid, nm in entries_sorted:
                try:
                    ilv = int(lv)
                except Exception:
                    continue
                if ilv in seen_levels:
                    continue
                seen_levels.add(ilv)
                out.append((ilv, str(nm or "").strip()))
            out = [(lv, nm) for (lv, nm) in out if nm]
            return out

        # -------------------------
        # 1) пробуем прямую колонку типа в EquipmentClass
        # -------------------------
        if conn is not None and _table_exists("EquipmentClass"):
            try:
                ec_cols = _cols_of("EquipmentClass")
                col_id = _pick_col(ec_cols, ("Id",))
                col_name = _pick_col(ec_cols, ("Name", "Title", "DisplayName"))
                col_level = _pick_col(ec_cols, ("Level",))
                col_type = _pick_col(ec_cols, ("EquipmentType_Id", "Type_Id", "EquipType_Id"))

                if col_id and col_name and col_level and col_type:
                    rows = conn.execute(
                        f"SELECT {col_type} AS tid, {col_id} AS cid, {col_name} AS nm, {col_level} AS lv "
                        f"FROM EquipmentClass "
                        f"WHERE {col_type} IS NOT NULL"
                    ).fetchall()

                    tmp: dict[int, list[tuple[int, int, str]]] = {}
                    for r in rows or []:
                        if _rows_are_mapping(r):
                            tid = r["tid"]
                            cid = r["cid"]
                            nm = r["nm"]
                            lv = r["lv"]
                        else:
                            tid, cid, nm, lv = r[0], r[1], r[2], r[3]
                        try:
                            tid_i = int(tid)
                            cid_i = int(cid)
                            lv_i = int(lv)
                        except Exception:
                            continue
                        nm_s = str(nm or "").strip()
                        if tid_i <= 0 or not nm_s:
                            continue
                        tmp.setdefault(tid_i, []).append((lv_i, cid_i, nm_s))

                    for tid_i, entries in tmp.items():
                        out = _dedupe_and_sort(entries)
                        if out:
                            res[tid_i] = out
            except Exception:
                pass

        # -------------------------
        # 2) если прямой колонки нет — ищем таблицу-связку (Type_Id + Class_Id)
        # -------------------------
        if conn is not None and not res and _table_exists("EquipmentClass"):
            try:
                tbls = _table_names()

                link_tbl = None
                type_col = None
                class_col = None

                tbls_sorted = sorted(
                    tbls,
                    key=lambda x: (
                        0 if ("equipment" in x.lower() and "class" in x.lower() and "type" in x.lower()) else 1)
                )

                for t in tbls_sorted:
                    cols = _cols_of(t)
                    tc = _pick_col(cols, ("EquipmentType_Id", "Type_Id", "EquipType_Id"))
                    cc = _pick_col(cols, ("EquipmentClass_Id", "Class_Id", "EquipClass_Id"))
                    if tc and cc:
                        link_tbl, type_col, class_col = t, tc, cc
                        break

                if link_tbl and type_col and class_col:
                    cls_rows = conn.execute("SELECT Id, Name, Level FROM EquipmentClass").fetchall()
                    cls_by_id: dict[int, tuple[str, int]] = {}
                    for r in cls_rows or []:
                        if _rows_are_mapping(r):
                            cid = int(r["Id"])
                            nm = str(r["Name"] or "").strip()
                            lv = int(r["Level"])
                        else:
                            cid = int(r[0])
                            nm = str(r[1] or "").strip()
                            lv = int(r[2])
                        if cid > 0 and nm:
                            cls_by_id[cid] = (nm, lv)

                    rows = conn.execute(f"SELECT {type_col}, {class_col} FROM '{link_tbl}'").fetchall()
                    tmp: dict[int, list[tuple[int, int, str]]] = {}
                    for r in rows or []:
                        if _rows_are_mapping(r):
                            tid = r[type_col]
                            cid = r[class_col]
                        else:
                            tid, cid = r[0], r[1]
                        try:
                            tid_i = int(tid)
                            cid_i = int(cid)
                        except Exception:
                            continue
                        nm_lv = cls_by_id.get(cid_i)
                        if not nm_lv:
                            continue
                        nm, lv = nm_lv
                        if tid_i > 0:
                            tmp.setdefault(tid_i, []).append((int(lv), int(cid_i), str(nm)))

                    for tid_i, entries in tmp.items():
                        out = _dedupe_and_sort(entries)
                        if out:
                            res[tid_i] = out
            except Exception:
                pass

        # -------------------------
        # 3) если не нашли привязку — строим глобальную шкалу по EquipmentClass (key=0)
        # -------------------------
        if conn is not None and not res and _table_exists("EquipmentClass"):
            try:
                rows = conn.execute("SELECT Id, Name, Level FROM EquipmentClass").fetchall()
                entries: list[tuple[int, int, str]] = []
                for r in rows or []:
                    if _rows_are_mapping(r):
                        cid = r["Id"]
                        nm = r["Name"]
                        lv = r["Level"]
                    else:
                        cid, nm, lv = r[0], r[1], r[2]
                    try:
                        cid_i = int(cid)
                        lv_i = int(lv)
                    except Exception:
                        continue
                    nm_s = str(nm or "").strip()
                    if cid_i > 0 and nm_s:
                        entries.append((lv_i, cid_i, nm_s))

                out = _dedupe_and_sort(entries)
                if out:
                    res[0] = out
            except Exception:
                pass

        # -------------------------
        # 5) гарантируем глобальную шкалу (key=0) для неизвестных Type_Id
        # -------------------------
        if 0 not in res:
            # попробуем собрать реальную глобальную шкалу из EquipmentClass даже если res уже частично заполнен
            if conn is not None and _table_exists("EquipmentClass"):
                try:
                    rows = conn.execute("SELECT Id, Name, Level FROM EquipmentClass").fetchall()
                    entries: list[tuple[int, int, str]] = []
                    for r in rows or []:
                        if _rows_are_mapping(r):
                            cid = r["Id"]
                            nm = r["Name"]
                            lv = r["Level"]
                        else:
                            cid, nm, lv = r[0], r[1], r[2]
                        try:
                            cid_i = int(cid)
                            lv_i = int(lv)
                        except Exception:
                            continue
                        nm_s = str(nm or "").strip()
                        if cid_i > 0 and nm_s:
                            entries.append((lv_i, cid_i, nm_s))
                    out = _dedupe_and_sort(entries)
                    if out:
                        res[0] = out
                except Exception:
                    pass

            # если всё равно нет — ставим дефолт B->A (как старый дефолт до 40 / после 40)
            if 0 not in res:
                res[0] = [(1, "B"), (41, "A")]

        setattr(self, "_class_start_levels_cache", res)
        return res

    def _determine_item_grade(self, item: dict) -> str:
        """
        Определяет "грейд" (A/B/C) для подстановки камня.

        Приоритет:
        0) если в item уже есть класс (ItemClass / Class / ...), используем его
        1) если доступен EquipmentInfoWindow (parent.equip_info) — берём его алгоритм
        2) fallback: текущая логика по интервалам EquipmentClass.Level (как было раньше)
        """
        import re
        from bisect import bisect_right

        def _normalize_abc(s: str) -> str:
            # на всякий случай поддержим кириллицу (А/В/С) -> латиница (A/B/C)
            if not s:
                return ""
            u = str(s).strip().upper()
            u = u.replace("А", "A").replace("В", "B").replace("С", "C")
            return u

        def _grade_from_any(val) -> Optional[str]:
            if val is None:
                return None
            u = _normalize_abc(val)
            if not u:
                return None
            if u in ("A", "B", "C"):
                return u
            # "Класс: A", "CLASS_A", "A-class" и т.п.
            m = re.search(r"(^|[_\-\s:])([ABC])($|[_\-\s])", u)
            if m:
                return m.group(2)
            # иногда в конце " ... _A"
            if len(u) >= 2 and u[-1] in ("A", "B", "C") and u[-2] in ("_", "-", " ", ":"):
                return u[-1]
            return None

        if not isinstance(item, dict):
            return "B"

        # -------------------------
        # 0) ПРЯМОЕ значение из item
        # -------------------------
        for k in (
                "ItemClass", "item_class",
                "Class", "class",
                "EquipmentClass", "equipment_class",
                "ItemClassName", "ClassName",
                "EquipmentClassName",
        ):
            g = _grade_from_any(item.get(k))
            if g:
                return g

        # Иногда лежит Id класса — попробуем добрать имя из БД
        for kid in ("ItemClass_Id", "ItemClassId", "EquipmentClass_Id", "EquipmentClassId"):
            cid = _to_int(item.get(kid) or 0, 0)
            if cid > 0:
                try:
                    p = self.parent()
                    conn = p.data.conn if (p and hasattr(p, "data") and hasattr(p.data, "conn")) else None
                    if conn:
                        row = conn.execute("SELECT Name FROM EquipmentClass WHERE Id=? LIMIT 1", (int(cid),)).fetchone()
                        if row:
                            nm = row["Name"] if hasattr(row, "keys") else row[0]
                            g = _grade_from_any(nm)
                            if g:
                                return g
                except Exception:
                    pass

        # -------------------------------------------------
        # 1) Источник истины: EquipmentInfoWindow (как reforge)
        # -------------------------------------------------
        try:
            p = self.parent()
            equip_info = getattr(p, "equip_info", None) if p else None
            if equip_info and hasattr(equip_info, "_get_internal_level_for_item") and hasattr(equip_info,
                                                                                              "_class_letter_from_internal"):
                internal_lvl = equip_info._get_internal_level_for_item(item)
                klass = equip_info._class_letter_from_internal(internal_lvl)
                g = _grade_from_any(klass)
                if g:
                    return g
        except Exception:
            pass

        # -------------------------
        # 2) Fallback: твоя текущая шкала
        # -------------------------

        # 1) Type_Id
        t_id = _to_int(item.get("Type_Id") or item.get("TypeId") or item.get("TypeID") or 0, 0)

        # если Type_Id нет — попробуем добрать из Equipment по Id
        if t_id <= 0:
            try:
                equip_id = _to_int(item.get("Id") or 0, 0)
                p = self.parent()
                conn = p.data.conn if (p and hasattr(p, "data") and hasattr(p.data, "conn")) else None
                if conn and equip_id:
                    row = conn.execute("SELECT Type_Id FROM Equipment WHERE Id=? LIMIT 1", (int(equip_id),)).fetchone()
                    if row:
                        t_id = _to_int(row["Type_Id"] if hasattr(row, "keys") else row[0], 0)
            except Exception:
                pass

        # 2) internal level
        lvl = _to_int(self._get_internal_level_for_item(item), 1)
        if lvl <= 0:
            lvl = 1

        # 3) шкала классов: сначала по Type_Id, иначе глобальная (key=0)
        start_map = {}
        try:
            if hasattr(self, "_get_class_start_levels"):
                start_map = self._get_class_start_levels() or {}
        except Exception:
            start_map = {}

        try:
            raw_scale = (start_map.get(int(t_id)) or start_map.get(0) or [])
        except Exception:
            raw_scale = []

        # нормализуем и фильтруем шкалу
        scale: list[tuple[int, str]] = []
        for entry in raw_scale or []:
            try:
                lv, nm = entry
                ilv = int(lv)
                snm = str(nm or "").strip()
                if snm:
                    scale.append((ilv, snm))
            except Exception:
                continue

        # если шкалы нет — дефолт
        if not scale:
            return "B"

        scale.sort(key=lambda x: x[0])

        # индекс класса по интервалам
        levels = [lv for lv, _ in scale]
        idx = bisect_right(levels, int(lvl)) - 1
        if idx < 0:
            idx = 0
        if idx >= len(scale):
            idx = len(scale) - 1

        class_name = scale[idx][1]
        g = _grade_from_any(class_name)
        if g:
            return g

        # если в имени нет A/B/C — fallback по позиции
        if len(scale) >= 3:
            return ("C", "B", "A")[idx] if idx <= 2 else "A"
        if len(scale) == 2:
            return ("B", "A")[idx] if idx <= 1 else "A"
        return "B"

    def _set_pick_slot_icon(self, pm: Optional[QPixmap], item: Optional[Dict[str, Any]] = None) -> None:
        slot = getattr(self, "_pick_item_slot", None)
        if not slot:
            return

        # пусто -> очистить
        if not pm or pm.isNull():
            slot.clear()
            slot.hide()
            return

        # если item не передали — пробуем взять из стейта окна (подстрой под своё имя поля)
        if item is None:
            item = (
                    getattr(self, "_pick_item", None)
                    or getattr(self, "_picked_item", None)
                    or getattr(self, "_item", None)
            )
            if not isinstance(item, dict):
                item = None

        # размер слота
        sz = slot.size()
        if sz.width() <= 0 or sz.height() <= 0:
            # на всякий случай, если виджет ещё не разложен
            sz = slot.sizeHint()

        # 1) если умеем — компонуем с бейджем элемента (как в reforge.py)
        final_pm = None
        try:
            if item and hasattr(self, "_element_id_for_item") and hasattr(self, "_compose_with_element_badge"):
                eid = self._element_id_for_item(item) or 0
                if eid:
                    final_pm = self._compose_with_element_badge(pm, sz, int(eid), item)
        except Exception:
            final_pm = None

        # 2) fallback — обычное масштабирование
        if not final_pm or final_pm.isNull():
            final_pm = pm.scaled(sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        slot.setPixmap(final_pm)
        slot.show()
        slot.raise_()

    def _set_stamp_gem(self, grade: str):
        if not self._pick_stamp_slot: return
        path = GEM_PATHS.get(grade.upper()); pm = _load_file_image(_resolve_resource(path)) if path else None
        if pm:
            self._pick_stamp_slot.setPixmap(pm); self._pick_stamp_slot.show(); self._pick_stamp_slot.raise_()
        else:
            self._pick_stamp_slot.clear(); self._pick_stamp_slot.hide()
        self._raise_stamp_stack()

    def _set_arcon_visible(self, vis: bool):
        if not self._pick_arcon_slot: return
        if vis:
            pm = _load_file_image(_resolve_resource(ARCON_PATH))
            if pm:
                self._pick_arcon_slot.setPixmap(pm)
                self._pick_arcon_slot.show(); self._pick_arcon_slot.raise_()
        else:
            self._pick_arcon_slot.clear(); self._pick_arcon_slot.hide()
        self._raise_stamp_stack()

    # ---------- WINDOW LIFECYCLE ----------
    def _on_close(self):
        self._hide_any_tip()
        self._hide_pick_item_popup(); self._hide_pick_stamp_popup()
        self._reset_selection()
        self._set_glows_visible(False); self._set_color_circles_visible(False)
        for b in self._color_buttons: b.hide()
        self.hide()
        self.closed.emit()

    def hideEvent(self, _ev):
        self._hide_any_tip()
        self._hide_pick_item_popup(); self._hide_pick_stamp_popup()
        self._reset_selection()
        self._set_glows_visible(False); self._set_color_circles_visible(False)
        for b in self._color_buttons: b.hide()
        super().hideEvent(_ev)

    def _apply_picked_item(self, slot_key, item: dict) -> None:
        """
        Применить выбор предмета в pick_item.

        Если на предмете уже есть печать:
        - сразу показываем предмет в слоте результата;
        - сразу показываем активную цветную ауру печати;
        - разрешаем менять цвет печати через кружки цвета;
        - _chosen_stamp заполняем сохранённой печатью, чтобы ПКМ по результату
          мог сохранить перекрашенную/пере рассчитанную печать.
        """
        if not isinstance(item, dict):
            item = {}

        self._picked_item = dict(item)
        self._picked_item_id = int(item.get("Id") or 0)
        self._picked_instance_guid = item.get("InstanceGuid") or None
        self._picked_slot_key = str(slot_key) if slot_key else None
        self._chosen_stamp = None
        self._remove_stamp_mode = False

        pm: Optional[QPixmap] = None
        try:
            img_id = item.get("Icon_Image_Id") or item.get("Image_Id")
            if img_id:
                pm = self._load_pm_by_image_id(int(img_id))
        except Exception:
            pm = None

        self._set_pick_slot_icon(pm, item=item)

        grade = self._determine_item_grade(item)
        self._set_stamp_gem(grade)
        self._set_arcon_visible(True)
        self._set_glows_visible(True)
        self._set_color_circles_visible(True)

        for b in self._color_buttons:
            b.show()

        self._switch_background_for_choice(True)

        # ----------------------------------------------------------
        # Если предмет уже имеет печать — поднимаем её как текущий результат.
        # Это нужно, чтобы:
        #   - out_stamp сразу показывал предмет;
        #   - stamp_color_preview сразу показывал цветную ауру;
        #   - цвет можно было менять кнопками без выбора новой печати.
        # ----------------------------------------------------------
        saved = self._get_saved_stamp_for_item(self._picked_item)
        tip_payload = self._to_tip_stamp_payload(saved) if saved else None

        if isinstance(tip_payload, dict) and tip_payload:
            cid = _to_int(
                tip_payload.get("ColorId")
                or tip_payload.get("Color_Id")
                or tip_payload.get("color_id")
                or 0,
                0,
            )

            if cid <= 0:
                cid = 4

            name = (
                tip_payload.get("Name")
                or tip_payload.get("name")
                or ""
            )

            bonuses = list(
                tip_payload.get("Bonuses")
                or tip_payload.get("BonusLines")
                or tip_payload.get("Effects")
                or []
            )

            self._selected_color_id = int(cid)
            self._chosen_stamp = {
                "Id": _to_int(tip_payload.get("Id") or tip_payload.get("id") or 0, 0),
                "Name": str(name),
                "name": str(name),
                "Color_Id": int(cid),
                "ColorId": int(cid),
                "Bonuses": list(bonuses),
                "BonusLines": list(bonuses),
                "BonusesText": "\n".join(bonuses),
                "effects": "\n".join(bonuses),
            }

            # Пересчёт под текущий internal level предмета и текущий цвет.
            self._recalc_chosen_stamp_bonuses()
        else:
            self._selected_color_id = 0
            self._chosen_stamp = None

        for b in self._color_buttons:
            self._style_color_btn(
                b,
                selected=(_to_int(b.property("color_id"), -1) == int(self._selected_color_id or 0)),
            )

        self._hide_pick_item_popup()
        self._update_color_buttons_enabled()
        self._update_color_preview()
        self._refresh_out_stamp_preview()

        if isinstance(self._chosen_stamp, dict):
            self._set_right_details(
                self._chosen_stamp.get("Name"),
                self._chosen_stamp.get("Bonuses") or [],
            )
            self._update_details_color_from_current()
        else:
            self._set_right_details(None, None)
            self._apply_details_color(None)

        if getattr(self, "_details_frame", None):
            self._details_frame.show()

        self._raise_stamp_stack()

    def _on_pick_item_clicked(self):
        btn = self.sender()
        if not isinstance(btn, QToolButton):
            return

        slot_key = btn.property("_sw_slot_key")
        item = btn.property("_sw_item_dict") or {}
        self._apply_picked_item(slot_key, item)

    def _ei_call(self, fn, **kwargs) -> bool:
        """Как в reforge: передаём только те kwargs, которые метод реально принимает.
        Важно: НЕ делаем 'второй попытки' вне этой функции — это источник глюков."""
        if not callable(fn):
            return False

        try:
            sig = inspect.signature(fn)
        except Exception:
            # сигнатуру не прочитали — попробуем как есть, но ОДИН раз
            try:
                fn(**kwargs)
                return True
            except Exception:
                return False

        params = sig.parameters

        # если есть **kwargs — можно передавать всё
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            try:
                fn(**kwargs)
                return True
            except Exception:
                return False

        filtered = {k: v for k, v in kwargs.items() if k in params}
        try:
            fn(**filtered)
            return True
        except Exception:
            return False

    def _etype_name_by_id(self, tid: int) -> str:
        """Лукап имени типа предмета для анкеты."""
        p = self.parent()
        try:
            conn = p.data.conn if (p and hasattr(p, "data")) else None
            if not conn:
                return "—"
            row = conn.execute("SELECT Name FROM EquipmentType WHERE Id=?", (int(tid),)).fetchone()
            if not row:
                return "—"
            return row["Name"] if hasattr(row, "keys") else row[0]
        except Exception:
            return "—"

    def _build_bonus_lines_for_tip(self, item_payload: dict) -> Optional[list[str]]:
        """Опционально: подтянуть строки бонусов, как в reforge/main."""
        p = self.parent()
        if not p or not hasattr(p, "data") or not hasattr(p.data, "conn"):
            return None

        if not _render_bonus_lines_helper:
            return None

        equip_id = (
                item_payload.get("Equip_Id") or item_payload.get("Equipment_Id")
                or item_payload.get("EquipId") or item_payload.get("EquipmentId")
                or item_payload.get("Id")
        )

        try:
            equip_id = int(equip_id or 0)
        except Exception:
            equip_id = 0

        if not equip_id:
            return None

        try:
            lines = _render_bonus_lines_helper(p.data.conn, equip_id)
            if not lines:
                return None
            # гарантируем list[str]
            return list(lines)
        except Exception:
            return None

    def _hide_any_tip(self) -> None:
        p = self.parent()
        if not p or not hasattr(p, "equip_info"):
            self._last_tip_anchor = None
            self._tip_last_sig = None
            self._tip_sig_item = None
            self._tip_sig_item_t = 0.0
            return

        ei = p.equip_info

        last = getattr(self, "_last_tip_anchor", None)

        try:
            if last is not None:
                ei.end_hover(last)
        except Exception:
            pass

        try:
            ei.hide()
        except Exception:
            pass

        self._last_tip_anchor = None

        # ВАЖНО:
        # сбрасываем оба антидубля. Раньше сбрасывался не тот ключ,
        # из-за чего повторное наведение могло попасть в debounce и не показать анкету.
        self._tip_last_sig = None
        self._tip_sig_item = None
        self._tip_sig_item_t = 0.0

    def _filter_tip_bonus_lines(self, lines: Optional[list[str]]) -> Optional[list[str]]:
        """Убираем точные дубли и строку 'Защита:' из bonus_lines (её equip_info рисует сам).
        Возвращаем исходные строки (включая HTML), чтобы не ломать форматирование."""
        if not lines:
            return lines

        import re
        import html as _html

        def visible(s: str) -> str:
            s = "" if s is None else str(s)
            s = s.replace("&nbsp;", " ").replace("\u00A0", " ").replace("\u202F", " ").replace("\u2007", " ")
            s = s.replace("\u200B", "")  # zero-width space
            s = _html.unescape(s)
            s = re.sub(r"(?i)<br\s*/?>", "\n", s)
            s = re.sub(r"<[^>]+>", "", s)
            s = s.replace("：", ":")
            s = " ".join(s.split())
            return s.strip()

        out: list[str] = []
        seen: set[str] = set()

        for ln in lines:
            vis = visible(ln)
            key = vis.lower().replace("ё", "е")

            if key.startswith("защита:"):
                continue

            if key in seen:
                continue
            seen.add(key)

            out.append(ln)  # сохраняем оригинал (HTML/цвета)

        return out

    def _dedupe_display_lines(self, lines):
        """
        Убирает точные дубли строк (с учётом нормализации пробелов/nbsp).
        НЕ пытается умничать по названиям статов — только exact-дубль.
        """
        if not lines:
            return lines

        def _clean(s: str) -> str:
            if s is None:
                return ""
            s = str(s).replace("\u00A0", " ")  # NBSP -> space
            s = " ".join(s.split())  # схлопнуть пробелы
            return s.strip()

        out = []
        seen = set()
        for s in lines:
            cs = _clean(s)
            if not cs:
                continue
            key = cs.lower().replace("ё", "е")
            if key in seen:
                continue
            seen.add(key)
            out.append(cs)
        return out

    def _dedupe_tip_html_text(self, html: str) -> str:
        """
        Дедуп строк в HTML/QLabel тексте. Убирает ТОЧНЫЕ дубли строк,
        сравнение делаем по "видимому" тексту (без тегов) + нормализация пробелов/NBSP.
        Разные значения (например 53+106 и 53+110) НЕ склеиваются.
        """
        import re

        if not html:
            return html

        # split по <br> (если есть), иначе по \n
        has_br = bool(re.search(r"(?i)<br\s*/?>", html))
        if has_br:
            parts = re.split(r"(?i)<br\s*/?>", html)
            joiner = "<br/>"
        else:
            parts = html.splitlines()
            joiner = "\n"

        def strip_tags(s: str) -> str:
            return re.sub(r"<[^>]+>", "", s or "")

        def norm(s: str) -> str:
            s = strip_tags(s)
            s = s.replace("\u00A0", " ")  # NBSP
            s = s.replace("：", ":")  # fullwidth colon
            s = " ".join(s.split())  # схлопнуть пробелы
            return s.strip().lower().replace("ё", "е")

        out_parts = []
        seen = set()

        for part in parts:
            key = norm(part)
            if not key:
                # пустые куски оставлять не надо
                continue
            if key in seen:
                continue
            seen.add(key)
            out_parts.append(part.strip())

        return joiner.join(out_parts)

    def _post_fix_equip_info_duplicates(self, ei: QWidget) -> None:
        """
        После render'а tooltip: ищем QLabel-строки со статами и скрываем точные дубли.
        ВАЖНО: дубли обычно в РАЗНЫХ QLabel, поэтому считаем по всем labels, а не внутри одного.
        Сейчас целимся только в 'Защита:' — чтобы не поломать другие элементы.
        """
        import re
        import html as _html
        try:
            from PySide6.QtCore import QPoint
            from PySide6.QtWidgets import QLabel
        except Exception:
            return

        def _visible(s: str) -> str:
            s = "" if s is None else str(s)
            s = s.replace("&nbsp;", " ")
            s = s.replace("\u00A0", " ").replace("\u202F", " ").replace("\u2007", " ")
            s = s.replace("\u200B", "")
            s = _html.unescape(s)
            s = re.sub(r"(?i)<br\s*/?>", "\n", s)
            s = re.sub(r"<[^>]+>", "", s)
            s = s.replace("：", ":")
            s = " ".join(s.split())
            return s.strip()

        try:
            labels = ei.findChildren(QLabel)
        except Exception:
            return
        if not labels:
            return

        # упорядочим примерно в порядке отображения (сверху вниз, слева направо)
        def _sort_key(lbl: QLabel):
            try:
                p = lbl.mapToGlobal(QPoint(0, 0))
                return (p.y(), p.x(), lbl.width(), lbl.height())
            except Exception:
                return (10 ** 9, 10 ** 9, 0, 0)

        labels = sorted(labels, key=_sort_key)

        seen_def: set[str] = set()

        for lbl in labels:
            try:
                if not lbl.isVisible():
                    continue
                txt = lbl.text() or ""
            except Exception:
                continue

            vis = _visible(txt)
            key = vis.lower().replace("ё", "е")

            # целимся строго в строки защиты
            if not key.startswith("защита:"):
                continue

            if key in seen_def:
                try:
                    lbl.hide()
                except Exception:
                    pass
            else:
                seen_def.add(key)

    def _show_item_tip(
            self,
            anchor_widget: QWidget,
            item_payload: dict,
            *,
            force_stamp_payload: Optional[dict] = None,
            force_no_stamp: bool = False
    ) -> None:
        import time
        from functools import partial

        p = self.parent()
        if not p or not hasattr(p, "equip_info"):
            return

        ei = p.equip_info
        tip_item = dict(item_payload or {})

        slot_key = (
                tip_item.get("slot_key")
                or tip_item.get("SlotKey")
                or getattr(self, "_picked_slot_key", None)
                or ""
        )
        slot_key = str(slot_key or "").strip()
        if slot_key:
            tip_item["slot_key"] = slot_key

        # --- подтягиваем "живой" предмет из MainWindow._selected_items ---
        # это важно после swap'а, когда popup может держать старый snapshot
        try:
            live_item = None
            if slot_key and hasattr(p, "_selected_items"):
                live_item = (p._selected_items or {}).get(slot_key)

            same_item = False
            if isinstance(live_item, dict):
                live_inst = str(live_item.get("InstanceGuid") or "")
                tip_inst = str(tip_item.get("InstanceGuid") or "")

                if live_inst and tip_inst and live_inst == tip_inst:
                    same_item = True
                else:
                    try:
                        live_id = int(live_item.get("Id") or 0)
                        tip_id = int(tip_item.get("Id") or 0)
                        same_item = bool(live_id > 0 and live_id == tip_id)
                    except Exception:
                        same_item = False

            if same_item and isinstance(live_item, dict):
                important_keys = (
                    "InstanceGuid",
                    "Stamp", "stamp",
                    "StampId", "StampColorId", "StampName", "StampBonuses",
                    "StampHeaderColorHex", "StampHeaderIconImageId", "StampHeaderIconId",
                    "__forge_level", "ForgeLevel", "forge_level", "UpgradeLevel",
                    "__forge_bonus", "ForgeBonus", "forge_bonus", "UpgradeMainBonus",
                    "__forge_hp_bonus", "ForgeHpBonus", "HpBonusFromForge",
                    "__forge_allstat", "ForgeAllStatBonus", "ForgeAllStat", "AllStatBonus",
                    "__forge_atk_bonus", "ForgeAttackBonus", "ForgeAtkBonus",
                    "__forge_def_bonus", "ForgeDefenseBonus", "ForgeDefBonus",
                    "_cards", "cards", "Cards",
                )

                for k in important_keys:
                    if k not in live_item:
                        continue
                    cur = tip_item.get(k)
                    if cur is None or cur == "" or cur == [] or cur == {}:
                        tip_item[k] = live_item[k]
        except Exception:
            pass

        # --- штамп ---
        stamp_payload = force_stamp_payload

        if force_no_stamp:
            stamp_payload = None
        else:
            if stamp_payload is None:
                # 1) сначала inline
                raw_inline = None
                try:
                    raw_inline = tip_item.get("Stamp")
                    if not isinstance(raw_inline, dict) or not raw_inline:
                        raw_inline = tip_item.get("stamp")
                except Exception:
                    raw_inline = None

                if isinstance(raw_inline, dict) and raw_inline:
                    if any(k in raw_inline for k in ("HeaderColorHex", "HeaderIconImageId", "icon_id")):
                        stamp_payload = dict(raw_inline)
                    else:
                        stamp_payload = self._to_tip_stamp_payload(raw_inline)

                # 2) потом выбранная в текущем окне
                if stamp_payload is None:
                    stamp_payload = self._current_stamp_payload()

                # 3) потом сохранённая
                if stamp_payload is None:
                    saved = self._get_saved_stamp_for_item(tip_item)
                    stamp_payload = self._to_tip_stamp_payload(saved) if saved else None

        # --- debounce/signature ---
        item_key = (
                tip_item.get("InstanceGuid")
                or tip_item.get("Id")
                or tip_item.get("Equip_Id")
                or ""
        )

        st_id = 0
        st_cid = 0
        bons_hash = 0

        if isinstance(stamp_payload, dict):
            st_id = _to_int(stamp_payload.get("Id"), 0)
            st_cid = _to_int(stamp_payload.get("ColorId"), 0)
            bons = stamp_payload.get("Bonuses") or stamp_payload.get("BonusLines") or stamp_payload.get("Effects") or []
            try:
                bons_hash = hash(tuple(map(str, bons)))
            except Exception:
                bons_hash = 0

        forge_sig = (
            _to_int(
                tip_item.get("__forge_level")
                or tip_item.get("ForgeLevel")
                or tip_item.get("forge_level")
                or tip_item.get("UpgradeLevel"),
                0
            ),
            _to_int(
                tip_item.get("__forge_bonus")
                or tip_item.get("ForgeBonus")
                or tip_item.get("forge_bonus")
                or tip_item.get("UpgradeMainBonus"),
                0
            ),
            _to_int(
                tip_item.get("__forge_hp_bonus")
                or tip_item.get("ForgeHpBonus")
                or tip_item.get("HpBonusFromForge"),
                0
            ),
            _to_int(
                tip_item.get("__forge_allstat")
                or tip_item.get("ForgeAllStatBonus")
                or tip_item.get("ForgeAllStat")
                or tip_item.get("AllStatBonus"),
                0
            ),
            _to_int(
                tip_item.get("__forge_atk_bonus")
                or tip_item.get("ForgeAttackBonus")
                or tip_item.get("ForgeAtkBonus"),
                0
            ),
            _to_int(
                tip_item.get("__forge_def_bonus")
                or tip_item.get("ForgeDefenseBonus")
                or tip_item.get("ForgeDefBonus"),
                0
            ),
        )

        sig = (
            str(item_key),
            slot_key,
            int(st_id),
            int(st_cid),
            int(bons_hash),
            forge_sig,
            bool(force_no_stamp),
        )

        now = time.monotonic()

        same_sig_recent = (
                sig == getattr(self, "_tip_sig_item", None)
                and (now - getattr(self, "_tip_sig_item_t", 0.0)) < 0.10
        )

        # Если сигнатура та же и анкета реально видна на этом же anchor —
        # можно не перерисовывать.
        # Но если анкета скрылась из-за запоздалого leave — обязательно показываем снова.
        if same_sig_recent:
            try:
                if ei.isVisible() and getattr(self, "_last_tip_anchor", None) is anchor_widget:
                    return
            except Exception:
                pass

        self._tip_sig_item = sig
        self._tip_sig_item_t = now

        bonus_lines = self._build_bonus_lines_for_tip(tip_item)
        bonus_lines = self._filter_tip_bonus_lines(bonus_lines)

        rect_global = QRect(
            anchor_widget.mapToGlobal(anchor_widget.rect().topLeft()),
            anchor_widget.rect().size()
        )

        safe_rect = QRect(rect_global)
        safe_rect.setWidth(max(60, safe_rect.width()))

        gp = safe_rect.center()
        gp.setY(safe_rect.top())

        compact = slot_key in ("costume", "mount")
        image_loader = getattr(getattr(p, "data", None), "get_image_bytes", None)

        # Карты — как в Inventory/Reforge: если cards_window умеет собрать payload,
        # передаём его в анкету.
        cards_payload = None
        try:
            cw = getattr(p, "cards_window", None)
            if cw is not None and hasattr(cw, "build_tooltip_cards_payload_for_item"):
                kind = "weapon" if slot_key in ("weapon", "offhand", "spear") else "equipment"
                cards_payload = cw.build_tooltip_cards_payload_for_item(
                    tip_item,
                    kind=kind,
                    slot_key=slot_key or None,
                )
        except Exception:
            cards_payload = None

        kwargs = dict(
            item=tip_item,
            image_loader=image_loader,
            global_pos=gp,
            type_name=None,
            type_name_lookup=self._etype_name_by_id,
            item_class=tip_item.get("ItemClass"),
            cards=cards_payload,
            bonus_lines=bonus_lines,
            stamp=stamp_payload,
            compact=compact,
            anchor_rect_global=safe_rect,
        )

        # Закрываем старый tooltip только если он был от другого anchor.
        # Это должно происходить ДО нового show_for_item, а leave старой ячейки
        # после этого уже будет проигнорирован в _tip_leave_for().
        try:
            last = getattr(self, "_last_tip_anchor", None)
            if last is not None and last is not anchor_widget:
                try:
                    ei.end_hover(last)
                except Exception:
                    pass
        except Exception:
            pass

        self._last_tip_anchor = anchor_widget

        # Linux/Wayland:
        # show_for_item вызывается напрямую, без begin_hover(),
        # поэтому transientParent надо ставить здесь.
        # Иначе анкета может провалиться под StampWindow/ChooseMenuAll.
        try:
            ei._ctx_root = self

            host_handle = self.windowHandle()
            if host_handle is None:
                self.winId()
                host_handle = self.windowHandle()

            ei.winId()
            tip_handle = ei.windowHandle()

            if tip_handle is not None and host_handle is not None:
                tip_handle.setTransientParent(host_handle)
        except Exception:
            pass

        try:
            self.raise_()
        except Exception:
            pass

        ok = self._ei_call(getattr(ei, "show_for_item", None), **kwargs)
        if not ok:
            try:
                ei.show_for_item(item=tip_item, global_pos=gp)
            except Exception:
                return

        try:
            ei.show()
            ei.raise_()
            ei.update()
        except Exception:
            pass

        if getattr(self, "_fix_ei_duplicates", False):
            QTimer.singleShot(0, partial(self._post_fix_equip_info_duplicates, ei))

    def _tip_enter_for(self, w: QWidget, payload: Optional[dict]) -> None:
        if not payload:
            return
        # весь debounce уже внутри _show_item_tip (и учитывает stamp/color/bonuses)
        self._show_item_tip(w, payload)

    def _tip_leave_for(self, w: QWidget) -> None:
        """
        Закрыть анкету только если leave пришёл от текущего активного anchor.

        Это важно для ChooseMenuAll:
        при быстром движении мыши старый cell может прислать leave уже ПОСЛЕ того,
        как новый cell показал свою анкету. Если без проверки вызвать end_hover(old),
        старая ячейка может спрятать уже новую анкету.
        """
        last = getattr(self, "_last_tip_anchor", None)

        # Запоздалый leave от старой ячейки — игнорируем.
        if last is not None and w is not last:
            return

        p = self.parent()
        if p and hasattr(p, "equip_info"):
            try:
                p.equip_info.end_hover(w)
            except Exception:
                pass

        if getattr(self, "_last_tip_anchor", None) is w:
            self._last_tip_anchor = None

        # Сброс антидубля, чтобы повторный enter по той же вещи мог снова открыть анкету.
        self._tip_last_sig = None
        self._tip_sig_item = None
        self._tip_sig_item_t = 0.0

    # ---------- EVENTS ----------
    def eventFilter(self, obj, ev) -> bool:
        et = ev.type()

        if not hasattr(self, "_pick_item_armed"):
            self._pick_item_armed = False
        if not hasattr(self, "_pick_stamp_armed"):
            self._pick_stamp_armed = False
        if not hasattr(self, "_stamp_row_armed_obj"):
            self._stamp_row_armed_obj = None

        def _btn():
            return getattr(ev, "button", lambda: None)()

        def _inside_widget(w) -> bool:
            if w is None:
                return False
            try:
                return w.rect().contains(ev.position().toPoint())
            except Exception:
                try:
                    return w.rect().contains(ev.pos())
                except Exception:
                    return False

        if isinstance(obj, QToolButton) and obj in self._buttons.values():
            path = obj.property("_hover_icon_path")
            if path:
                if et == QEvent.Enter:
                    obj.setIcon(QIcon(path))
                    obj.setIconSize(obj.size())
                elif et == QEvent.Leave or (et == QEvent.EnabledChange and not obj.isEnabled()):
                    obj.setIcon(QIcon())
            return False

        if (
                isinstance(obj, QToolButton)
                and obj.parent() is getattr(self, "_pick_popup", None)
                and obj.property("_sw_item_dict") is not None
        ):
            if et == QEvent.Enter:
                it = dict(obj.property("_sw_item_dict") or {})
                sk = obj.property("_sw_slot_key")
                if sk:
                    it["slot_key"] = str(sk)

                saved = self._get_saved_stamp_for_item(it)
                stamp_tip = self._to_tip_stamp_payload(saved) if saved else None
                self._show_item_tip(obj, it, force_stamp_payload=stamp_tip)

            elif et == QEvent.Leave:
                self._tip_leave_for(obj)

            return False

        if obj in (self._pick_item_slot, self._out_stamp_slot):
            if et == QEvent.Enter:
                if self._picked_item:
                    force_no_stamp = False
                    force_stamp_payload = None

                    # pick_item_slot показывает исходный предмет как есть.
                    # out_stamp_slot должен показывать именно РЕЗУЛЬТАТ:
                    #   - если выбран режим снятия печати -> без печати;
                    #   - если выбрана новая печать -> с новой печатью;
                    #   - иначе fallback на сохранённую/старую.
                    if obj is self._out_stamp_slot:
                        force_no_stamp = bool(getattr(self, "_remove_stamp_mode", False))

                        if not force_no_stamp and isinstance(getattr(self, "_chosen_stamp", None), dict):
                            force_stamp_payload = self._current_stamp_payload()

                    self._show_item_tip(
                        obj,
                        self._picked_item,
                        force_stamp_payload=force_stamp_payload,
                        force_no_stamp=force_no_stamp,
                    )
                return False

            if et == QEvent.Leave:
                self._tip_leave_for(obj)
                return False

        if obj is self._area_widgets.get("pick_item") or obj is self._pick_item_slot:
            if et == QEvent.MouseButtonPress and _btn() == Qt.LeftButton:
                self._pick_item_armed = True
                return True

            if et == QEvent.MouseButtonRelease and _btn() == Qt.LeftButton:
                armed = bool(getattr(self, "_pick_item_armed", False))
                self._pick_item_armed = False
                if armed and _inside_widget(obj):
                    self._show_pick_item_popup()
                return True

            if et in (QEvent.Leave, QEvent.HoverLeave):
                return False

            return False

        if obj is self._area_widgets.get("pick_stamp"):
            if et == QEvent.MouseButtonPress and _btn() == Qt.LeftButton:
                self._pick_stamp_armed = True
                return True

            if et == QEvent.MouseButtonRelease and _btn() == Qt.LeftButton:
                armed = bool(getattr(self, "_pick_stamp_armed", False))
                self._pick_stamp_armed = False
                if armed and _inside_widget(obj):
                    self._show_pick_stamp_popup()
                return True

            if et in (QEvent.Leave, QEvent.HoverLeave):
                return False

            return False

        if obj is getattr(self, "_pick_popup", None):
            if et in (QEvent.Hide, QEvent.Close):
                self._hide_any_tip()
            return False

        if obj is getattr(self, "_stamp_popup", None):
            if et in (QEvent.Hide, QEvent.Close):
                self._stamp_row_armed_obj = None
                self._hide_any_tip()
                return False
            if et == QEvent.Resize:
                self._place_stamp_vscroll()
                return False
            return False

        if isinstance(obj, QWidget) and obj.property("stamp_id") is not None:
            if et == QEvent.MouseButtonPress and _btn() == Qt.LeftButton:
                self._stamp_row_armed_obj = obj
                return True

            if et == QEvent.MouseButtonRelease and _btn() == Qt.LeftButton:
                armed_obj = getattr(self, "_stamp_row_armed_obj", None)
                self._stamp_row_armed_obj = None

                if armed_obj is obj and _inside_widget(obj):
                    sid = _to_int(obj.property("stamp_id"), 0)
                    sname = obj.property("stamp_name") or ""
                    bons = obj.property("stamp_bonuses") or []
                    if sid > 0:
                        self._select_stamp_in_ui(
                            sid,
                            sname,
                            bons,
                            int(self._selected_color_id or 4),
                        )
                    self._hide_pick_stamp_popup()
                return True

            if et == QEvent.MouseButtonDblClick:
                return True

            return False

        if obj is self._out_stamp_slot:
            if et == QEvent.MouseButtonRelease and _btn() == Qt.RightButton:
                has_remove_result = bool(getattr(self, "_remove_stamp_mode", False)) and bool(
                    self._get_saved_stamp_for_item(self._picked_item)
                )
                has_apply_result = bool(self._chosen_stamp)

                if self._picked_item and self._picked_instance_guid and (has_apply_result or has_remove_result):
                    if has_apply_result:
                        self._cache_current_stamp_for_instance()
                    self._notify_owner_apply_stamp()
                    self._clear_all_slots_after_save()
                    self._switch_background_for_choice(False)
                return True
            return False

        return super().eventFilter(obj, ev)

    # ---------- DRAG WINDOW ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft(); e.accept()
    def mouseMoveEvent(self, e):
        if self._drag_pos and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_pos); e.accept()
    def mouseReleaseEvent(self, e):
        self._drag_pos = None; e.accept()

    # ---------- CLEANUP ----------
    def _clear_all_slots_after_save(self) -> None:
        self._hide_pick_item_popup()
        self._hide_pick_stamp_popup()
        self._picked_item = None
        self._picked_item_id = None
        self._picked_slot_key = None
        self._chosen_stamp = None
        self._selected_color_id = 0
        self._remove_stamp_mode = False
        self._set_pick_slot_icon(None)
        if self._pick_stamp_slot:
            self._pick_stamp_slot.clear()
            self._pick_stamp_slot.hide()
        self._set_arcon_visible(False)
        if self._color_preview_slot:
            self._color_preview_slot.clear()
            self._color_preview_slot.hide()
        if self._out_stamp_slot:
            self._out_stamp_slot.clear()
            self._out_stamp_slot.hide()
        self._set_glows_visible(False)
        self._set_color_circles_visible(False)
        for b in self._color_buttons:
            b.hide()
        self._update_color_buttons_enabled()
        self._switch_background_for_choice(False)
        self._reset_details_panel()
