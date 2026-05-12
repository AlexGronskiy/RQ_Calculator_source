# cards.py
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Union, List, Callable, Dict, Any

from PySide6.QtCore import Qt, QRect, QPoint, QEvent, Signal, QSize, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QFontMetrics, QPen, QGuiApplication, QPainterPath
from PySide6.QtWidgets import QWidget, QMenu, QListWidgetItem, QAbstractItemView, QListWidget, QLabel, QVBoxLayout, \
    QPushButton, QFrame, QHBoxLayout, QSizePolicy, QLineEdit

from .characteristics_math import get_global_current_stats, get_current_stats_bus
from .weapon_equipment_button import _find_scroll_dir, ImageVScrollBar

# ====== КОНФИГ ================================================================
CM_EQUIPMENT_PATH = "resources/cards_menu/cm_equipment.png"
CM_WEAPON_PATH    = "resources/cards_menu/cm_weapon.png"

# Иконка «крестика» при наведении (сам крестик нарисован на фоне)
CLOSE_ICON_HOVER  = "resources/helper_buttons/close_button_active.png"

# Зоны «закрыть» (x, y, w, h) — в координатах PNG
CLOSE_ZONE_EQUIPMENT: Optional[Tuple[int, int, int, int]] = (298, 3, 24, 24)
CLOSE_ZONE_WEAPON:    Optional[Tuple[int, int, int, int]] = (298, 3, 24, 24)

# Где можно хватать окно для перетаскивания. None = везде, кроме зоны «крестика».
DRAG_REGION: Optional[Tuple[int, int, int, int]] = None
DRAG_THRESHOLD_PX = 4

# --- зоны интерфейса ----------------------------------------------------------
# cm_equipment
EQUIP_ZONE_ITEM:  Optional[Tuple[int, int, int, int]] = (37, 61, 50, 50)   # иконка предмета
EQUIP_ZONE_SLOT1: Optional[Tuple[int, int, int, int]] = (42, 143, 50, 50)
EQUIP_ZONE_APPLY: Optional[Tuple[int, int, int, int]] = (25, 212, 136, 29)
EQUIP_ZONE_CLEAR: Optional[Tuple[int, int, int, int]] = (173, 212, 136, 29)

# cm_weapon
WEAPON_ZONE_ITEM:  Optional[Tuple[int, int, int, int]] = (38, 62, 50, 50)
WEAPON_ZONE_SLOT1: Optional[Tuple[int, int, int, int]] = (42, 143, 50, 50)
WEAPON_ZONE_SLOT2: Optional[Tuple[int, int, int, int]] = (42, 215, 50, 50)
WEAPON_ZONE_SLOT3: Optional[Tuple[int, int, int, int]] = (42, 287, 50, 50)
WEAPON_ZONE_APPLY: Optional[Tuple[int, int, int, int]] = (25, 356, 136, 29)
WEAPON_ZONE_CLEAR: Optional[Tuple[int, int, int, int]] = (173, 356, 136, 29)
# ==============================================================================
RectLike = Union[QRect, Tuple[int, int, int, int]]

def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default

def _resolve_resource(rel_path: str) -> str:
    p = Path(rel_path)
    for base in (Path.cwd(), Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[3]):
        cand = base / p
        if cand.exists():
            return str(cand)
    return rel_path

def _load_file_image(path: str) -> Optional[QPixmap]:
    pm = QPixmap(_resolve_resource(path))
    return pm if not pm.isNull() else None

def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower().replace("ё", "е")

def _tokens(q: str) -> List[str]:
    q = _norm(q)
    return [t for t in q.split() if t]

def _search_match(name: str, stats: str, query: str) -> bool:
    ts = _tokens(query or "")
    if not ts:
        return True
    hay = f"{_norm(name)} {_norm(stats)}"
    return all(t in hay for t in ts)

def _stats_to_rich_with_yellow_prefix(stats: str) -> str:
    """
    Делает RichText: в каждой строке, если есть 'xxx: ...',
    красит 'xxx:' в желтый, остальное оставляет обычным.
    """
    import html

    BUFF_NAME_COLOR = "#00d183"  # берюзовый

    s = (stats or "").replace("\r", "")
    if not s.strip():
        return ""

    out_lines = []
    for ln in s.split("\n"):
        ln = ln.rstrip()
        if not ln.strip():
            continue

        # ищем первый ":" и красим префикс
        colon = ln.find(":")
        if colon > 0 and colon < 60:  # небольшой хардлимит, чтобы не красить странные случаи
            head = ln[:colon]          # без ":"
            tail = ln[colon + 1:]      # после ":"
            head_e = html.escape(head)
            tail_e = html.escape(tail)
            out_lines.append(
                f'<span style="color:{BUFF_NAME_COLOR}; font-weight:600;">{head_e}:</span>{tail_e}'
            )
        else:
            out_lines.append(html.escape(ln))

    return "<br/>".join(out_lines)



@dataclass(frozen=True)
class _Zone:
    x: int
    y: int
    w: int
    h: int

    def rect(self) -> QRect:
        return QRect(self.x, self.y, self.w, self.h)

class _CardRowWidget(QWidget):
    def __init__(self, *, icon: Optional[QPixmap], name: str, stats: str, selected: bool):
        super().__init__()
        self._hovered = False
        self._selected = bool(selected)

        self.setMinimumHeight(66)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(10)

        # icon 50x50
        self._icon = QLabel()
        self._icon.setFixedSize(50, 50)
        self._icon.setStyleSheet("background: rgba(255,255,255,0.06); border-radius: 8px;")
        if icon and not icon.isNull():
            pm = icon.scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._icon.setPixmap(pm)
            self._icon.setAlignment(Qt.AlignCenter)
        root.addWidget(self._icon, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)

        self._root = root
        self._col = col

        self._name = QLabel(name)
        self._name.setStyleSheet("color:#f1f1f1; font-size: 13px; font-weight: 600;")
        self._name.setTextInteractionFlags(Qt.NoTextInteraction)
        self._name.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        col.addWidget(self._name, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self._stats_plain = stats or ""

        self._stats = QLabel()
        self._stats.setStyleSheet("color:#b9b9b9; font-size: 11px;")
        self._stats.setTextInteractionFlags(Qt.NoTextInteraction)
        self._stats.setWordWrap(True)
        self._stats.setTextFormat(Qt.RichText)
        self._stats.setText(_stats_to_rich_with_yellow_prefix(self._stats_plain))
        self._stats.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._stats.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        col.addWidget(self._stats, 1, Qt.AlignLeft | Qt.AlignVCenter)

        root.addLayout(col, 1)

        self._check = QLabel("✓" if self._selected else "")
        self._check.setFixedWidth(18)
        self._check.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._check.setStyleSheet("color:#7CFF9A; font-size: 14px; font-weight: 700;")
        root.addWidget(self._check, 0, Qt.AlignVCenter)

    def enterEvent(self, e):
        self._hovered = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect().adjusted(1, 1, -1, -1)
        radius = 12.0

        if self._selected:
            bg = QColor(255, 255, 255, 26)
            bd = QColor(255, 255, 255, 110)
        elif self._hovered:
            bg = QColor(255, 255, 255, 18)
            bd = QColor(255, 255, 255, 95)
        else:
            bg = QColor(255, 255, 255, 10)
            bd = QColor(255, 255, 255, 65)

        path = QPainterPath()
        path.addRoundedRect(float(r.x()), float(r.y()), float(r.width()), float(r.height()), radius, radius)

        p.setClipPath(path)
        p.fillPath(path, bg)
        p.setClipping(False)

        p.setPen(QPen(bd, 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        super().paintEvent(e)

    def recompute_height(self, total_w: int) -> int:
        m = self._root.contentsMargins()
        left, top, right, bottom = m.left(), m.top(), m.right(), m.bottom()
        spacing = self._root.spacing()

        icon_w = self._icon.width()
        check_w = self._check.width()
        # icon + gap + text + gap + check
        text_w = max(10, total_w - (left + right + icon_w + check_w + spacing * 2))

        # чтобы wordwrap считался от правильной ширины
        self._name.setMaximumWidth(text_w)
        self._stats.setMaximumWidth(text_w)

        name_h = QFontMetrics(self._name.font()).height()

        stats_text = (getattr(self, "_stats_plain", "") or "").strip()

        if stats_text:
            fm = QFontMetrics(self._stats.font())
            br = fm.boundingRect(QRect(0, 0, text_w, 10000), Qt.TextWordWrap, stats_text)
            stats_h = br.height()
            gap = self._col.spacing()
        else:
            stats_h = 0
            gap = 0

        inner_h = max(self._icon.height(), name_h + gap + stats_h)
        total_h = max(66, inner_h + top + bottom)

        self.setFixedHeight(total_h)
        self.updateGeometry()
        return total_h


class _CardPickerPopup(QFrame):
    picked = Signal(dict)
    cleared = Signal()
    dismissed = Signal()

    def __init__(self, *, parent: QWidget, rows_visible: int = 5):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("CardPickerPopup")
        self._rows_visible = max(1, int(rows_visible))

        self._search_text: str = ""
        self._all_cards: List[Dict] = []
        self._icon_getter = None
        self._stats_builder = None
        self._selected_card_id: int = 0
        self._allow_clear: bool = True
        self._stats_cache_local: Dict[int, str] = {}

        self.setStyleSheet("""
            QFrame#CardPickerPopup {
                background: #171717;
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 12px;
            }
            QLineEdit {
                background: rgba(255,255,255,0.07);
                border: 1px solid rgba(255,255,255,0.14);
                color: #eaeaea;
                padding: 8px 10px;
                border-radius: 10px;
            }
            QLineEdit:focus { border-color: rgba(255,255,255,0.28); }
            QPushButton {
                background: rgba(255,255,255,0.08);
                border: 1px solid rgba(255,255,255,0.14);
                color: #e6e6e6;
                padding: 8px 10px;
                border-radius: 10px;
                text-align: left;
            }
            QPushButton:hover { background: rgba(255,255,255,0.12); }

            QListWidget {
                background: transparent;
                border: none;
                outline: none;
            }
            QListWidget::item {
                margin: 0px;
                padding: 0px;
                border: none;
                background: transparent;
            }
            QListWidget::item:selected { background: transparent; }
            QListWidget::item:hover    { background: transparent; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        self._row_right_gutter_px = 12

        # --- TOP BAR: search only ---
        top = QWidget(self)
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.setSpacing(0)

        self.search_edit = QLineEdit(top)
        self.search_edit.setPlaceholderText("Поиск карты (название / бонусы)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_changed)
        top_lay.addWidget(self.search_edit, 1)

        root.addWidget(top)

        # --- LIST ---
        self.list = QListWidget()
        self.list.setSpacing(2)
        self.list.setMouseTracking(True)
        self.list.viewport().setMouseTracking(True)

        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.currentItemChanged.connect(lambda *_: self._sync_selection_widgets())

        root.addWidget(self.list)

        self._empty = QLabel("")
        self._empty.setStyleSheet("color:#bdbdbd; padding: 10px;")
        self._empty.setVisible(False)
        root.addWidget(self._empty)

        vb = self.list.verticalScrollBar()
        vb.setSingleStep(24)
        vb.setPageStep(120)

        self._sv_custom = ImageVScrollBar(vb, _find_scroll_dir(), parent=self)
        self._sv_custom.hide()

        reserve = self._sv_custom.width() + 8
        try:
            self.list.setViewportMargins(0, 0, reserve, 0)
        except Exception:
            pass

        vb.rangeChanged.connect(lambda _a, _b: self._sv_custom.setVisible(vb.maximum() > 0))
        QTimer.singleShot(0, self._place_vscroll)

    def _sync_row_widths(self) -> None:
        vw = self.list.viewport().width()
        if vw <= 0:
            return

        target_w = max(1, vw - getattr(self, "_row_right_gutter_px", 12))

        for i in range(self.list.count()):
            it = self.list.item(i)
            if not it:
                continue

            w = self.list.itemWidget(it)
            if isinstance(w, _CardRowWidget):
                w.setMinimumWidth(target_w)
                w.setMaximumWidth(target_w)
                h = w.recompute_height(target_w)
                it.setSizeHint(QSize(target_w, h))
            else:
                h = it.sizeHint().height() or 80
                it.setSizeHint(QSize(target_w, h))

        self.list.doItemsLayout()

    def _on_search_changed(self, txt: str) -> None:
        self._search_text = txt or ""
        self._rebuild_list()

    def _get_stats_cached(self, card: Dict) -> str:
        cid = _safe_int((card or {}).get("Id"), 0)
        if cid > 0 and cid in self._stats_cache_local:
            return self._stats_cache_local[cid]
        s = (self._stats_builder(card) if self._stats_builder else "") or ""
        if cid > 0:
            self._stats_cache_local[cid] = s
        return s

    def _rebuild_list(self) -> None:
        self.list.clear()
        self._empty.setVisible(False)

        if not self._all_cards:
            self.list.setVisible(False)
            self._sv_custom.hide()
            self._empty.setText("Нет доступных карт для этого типа слота")
            self._empty.setVisible(True)
            return

        q = self._search_text or ""
        filtered: List[Dict] = []
        for c in self._all_cards:
            name = str(c.get("Name") or f"ID {_safe_int(c.get('Id'), 0)}")
            stats = self._get_stats_cached(c)
            if _search_match(name, stats, q):
                filtered.append(c)

        if not filtered:
            self.list.setVisible(False)
            self._sv_custom.hide()
            self._empty.setText("Ничего не найдено")
            self._empty.setVisible(True)
            return

        self.list.setVisible(True)

        row_h = 60
        visible_rows = min(self._rows_visible, 4)
        self.list.setFixedHeight(row_h * visible_rows + 6)

        for card in filtered:
            cid = _safe_int(card.get("Id"), 0)
            name = str(card.get("Name") or f"ID {cid}")
            stats = self._get_stats_cached(card)
            pm = self._icon_getter(card) if self._icon_getter else None

            item = QListWidgetItem()
            item.setData(Qt.UserRole, dict(card))
            item.setSizeHint(QSize(0, row_h))
            self.list.addItem(item)

            w = _CardRowWidget(icon=pm, name=name, stats=stats, selected=(cid and cid == self._selected_card_id))
            self.list.setItemWidget(item, w)

            if cid and cid == self._selected_card_id:
                self.list.setCurrentItem(item)

        QTimer.singleShot(0, self._place_vscroll)
        QTimer.singleShot(0, self._sync_row_widths)


    def _place_vscroll(self) -> None:
        if not getattr(self, "_sv_custom", None):
            return
        if not self.list.isVisible():
            self._sv_custom.hide()
            return

        r = self.list.geometry()
        if r.isEmpty():
            return

        margin = 6
        w = self._sv_custom.width()
        x = r.right() - w - margin + 1
        y = r.top() + margin
        h = max(1, r.height() - margin * 2)

        self._sv_custom.setGeometry(x, y, w, h)

        vb = self.list.verticalScrollBar()
        self._sv_custom.setVisible(vb.maximum() > 0)
        self._sync_row_widths()

    def populate(
            self,
            *,
            cards: List[Dict],
            icon_getter: Callable[[Dict], Optional[QPixmap]],
            stats_builder: Callable[[Dict], str],
            selected_card_id: int,
            allow_clear: bool = True,
    ) -> None:
        self._all_cards = list(cards or [])
        self._icon_getter = icon_getter
        self._stats_builder = stats_builder
        self._selected_card_id = _safe_int(selected_card_id, 0)
        self._allow_clear = bool(allow_clear)

        self.search_edit.blockSignals(True)
        self.search_edit.setText(self._search_text)
        self.search_edit.blockSignals(False)

        self._stats_cache_local.clear()
        self._rebuild_list()

        self.setFixedWidth(420)

        # после наполнения — корректно разложить ползунок
        QTimer.singleShot(0, self._place_vscroll)
        QTimer.singleShot(0, self._sync_row_widths)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        card = item.data(Qt.UserRole) or {}
        self.picked.emit(dict(card))

    def _sync_selection_widgets(self) -> None:
        """Обновляет галочки ✓ у строк при смене текущего элемента."""
        cur = self.list.currentItem()
        cur_card = cur.data(Qt.UserRole) if cur else {}
        cur_id = _safe_int((cur_card or {}).get("Id"), 0)

        for i in range(self.list.count()):
            it = self.list.item(i)
            if not it:
                continue
            w = self.list.itemWidget(it)
            if not isinstance(w, _CardRowWidget):
                continue

            card = it.data(Qt.UserRole) or {}
            cid = _safe_int(card.get("Id"), 0)
            is_sel = (cur_id > 0 and cid == cur_id)

            # обновляем только если изменилось
            if getattr(w, "_selected", False) != is_sel:
                w._selected = is_sel
                w._check.setText("✓" if is_sel else "")
                w.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_vscroll()
        QTimer.singleShot(0, self._sync_row_widths)

    def hideEvent(self, e):
        super().hideEvent(e)
        self.dismissed.emit()


class CardsWindow(QWidget):
    """
    Меню выбора карт (экип / оружие).

    • Рисуем фон, «крестик», и справа информацию о предмете.
    • По клику в зоны слотов открываем меню с картами.

    Снаружи подписываться на сигналы:
      card_picked(int slot_index, dict card)
      card_cleared(int slot_index)

    Также можно поднимать сохранённые карты:
      set_selected_cards({1: card_dict, 2: card_dict, ...})
    """

    closed = Signal()
    card_picked = Signal(int, dict)   # slot_index (1..3), card dict (строки из Card)
    card_cleared = Signal(int)        # slot_index (1..3)

    # Любое подтверждённое изменение кэша карт предмета.
    # key = ключ предмета в _per_item_cards
    # cards = текущий dict {slot_index: card_dict}
    item_cache_changed = Signal(object, object)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent;")
        self.installEventFilter(self)

        # режим окна
        self._kind: str = "equipment"  # "equipment" | "weapon"
        self._bg_pm: Optional[QPixmap] = None
        self._pm_close_hover: Optional[QPixmap] = _load_file_image(CLOSE_ICON_HOVER)

        # hover/press
        self._hover_in_close: bool = False
        self._pressed_in_close: bool = False
        self._press_pos: Optional[QPoint] = None
        self._press_gpos: Optional[QPoint] = None

        # press flags for apply/clear zones
        self._pressed_in_apply: bool = False
        self._pressed_in_clear: bool = False

        # золотой hover на зонах
        self._hover_gold_key: Optional[str] = None
        self._hover_gold_rect: Optional[QRect] = None
        self._hover_gold_radius: float = 0.0

        # стиль обводки (3 слоя: glow + core + highlight)
        self._gold_pen_glow = QPen(QColor(255, 200, 70, 110), 3)
        self._gold_pen_glow.setCosmetic(True)
        self._gold_pen_glow.setCapStyle(Qt.RoundCap)
        self._gold_pen_glow.setJoinStyle(Qt.RoundJoin)

        self._gold_pen_core = QPen(QColor(255, 215, 100, 235), 1)
        self._gold_pen_core.setCosmetic(True)
        self._gold_pen_core.setCapStyle(Qt.RoundCap)
        self._gold_pen_core.setJoinStyle(Qt.RoundJoin)

        self._gold_pen_hi = QPen(QColor(255, 245, 200, 255), 1)
        self._gold_pen_hi.setCosmetic(True)
        self._gold_pen_hi.setCapStyle(Qt.RoundCap)
        self._gold_pen_hi.setJoinStyle(Qt.RoundJoin)

        # dragging
        self._dragging: bool = False
        self._drag_offset: QPoint = QPoint(0, 0)

        # overrides
        self._session_override_close_rect: Optional[QRect] = None

        # контекст предмета
        self._item_ctx: Optional[dict] = None
        # уникальный идентификатор КОНКРЕТНОГО экземпляра предмета (как для печатей)
        self._item_instance_guid: Optional[str] = None
        self._image_loader: Optional[Callable[[int], Optional[bytes]]] = None
        self._item_icon_pm: Optional[QPixmap] = None
        # Id класса экипировки (EquipmentClass.Id) для текущего предмета
        self._item_class_id: Optional[int] = None

        self._type_name_lookup = None  # Callable[[int], str] | None

        # выбранные карты для текущего предмета (слот -> card dict / pixmap)
        self._selected_cards: Dict[int, Dict] = {}
        self._selected_card_pms: Dict[int, Optional[QPixmap]] = {}

        # сохранённые (применённые) карты по предметам:
        # ключ = InstanceGuid (строка), а если его нет — старый ключ (kind, Equip_Id/..., slot_key)
        self._per_item_cards: Dict[Union[str, Tuple[str, int, str]], Dict[int, Dict]] = {}
        self._per_item_pms: Dict[Union[str, Tuple[str, int, str]], Dict[int, Optional[QPixmap]]] = {}
        self._current_item_key: Optional[Union[str, Tuple[str, int, str]]] = None

        # какой слот в экипировке открыл это окно (ring1 / ring2 / helmet и т.п.)
        self._item_slot_key: Optional[str] = None

        # шрифты (предмет)
        self._font_title = QFont("Segoe UI", 12, QFont.Bold)
        self._font_text = QFont("Segoe UI", 10)

        # шрифты (карты напротив слотов)
        self._font_card_name = QFont("Segoe UI", 10, QFont.Bold)
        self._font_card_stats = QFont("Segoe UI", 9)

        # визуальные мелочи
        self._slot_border_pen = QPen(QColor(255, 255, 255, 40), 1)
        self._slot_border_pen.setCosmetic(True)

        self._picker_popup: Optional[_CardPickerPopup] = None
        self._card_stats_builder: Optional[Callable[[Dict], str]] = None
        self._card_icon_cache: Dict[int, QPixmap] = {}
        self._card_stats_cache: Dict[int, str] = {}
        self._upg_cond_cache: Dict[tuple, str] = {}

        # --- session (apply/cancel) ---
        self._session_backup_cards: Dict[int, Dict] = {}
        self._session_backup_pms: Dict[int, Optional[QPixmap]] = {}
        self._session_applied: bool = False

        # где-то в __init__
        self._character_stats: dict[int, float] = {}

        # --- NEW: подписка на обновления статов + дебаунс ---
        self._pending_stats: Optional[Dict[int, float]] = None
        self._stats_recalc_timer = QTimer(self)
        self._stats_recalc_timer.setSingleShot(True)
        self._stats_recalc_timer.timeout.connect(self._recalc_cards_from_current_stats)

        # подключаемся к глобальному bus (если он есть)
        try:
            if get_current_stats_bus is not None:
                get_current_stats_bus().statsChanged.connect(self._on_current_stats_changed)
        except Exception:
            pass

        # первичная синхронизация (сработает, когда окно покажется)
        try:
            self._on_current_stats_changed(get_global_current_stats())
        except Exception:
            pass

        self._debug_cards = True

    def _dbg(self, msg: str, *, card_id: int | None = None) -> None:
        if not getattr(self, "_debug_cards", False):
            return
        flt = getattr(self, "_debug_card_id", None)
        if flt is not None and card_id is not None and int(flt) != int(card_id):
            return
        print(msg)

    # ---------------- public API ----------------
    def set_card_stats_builder(self, fn: Optional[Callable[[Dict], str]]) -> None:
        """Колбэк: card_dict -> str (характеристики). Пока можешь не задавать."""
        self._card_stats_builder = fn

    def set_image_loader(self, loader: Optional[Callable[[int], Optional[bytes]]]) -> None:
        """Передайте data.get_image_bytes (иконки предметов и карточных карт, если Image_Id в той же таблице Images)."""
        self._image_loader = loader

    def set_type_name_lookup(self, fn) -> None:
        """Колбэк: tid:int -> str (название типа из БД)."""
        self._type_name_lookup = fn

    def set_context_item(self, item: Optional[dict]) -> None:
        """Передайте сюда предмет, по которому открыли окно."""
        self._item_ctx = dict(item) if item else None

        # InstanceGuid текущего экземпляра (если есть в словаре предмета)
        if self._item_ctx:
            guid = str(self._item_ctx.get("InstanceGuid") or "").strip()
            self._item_instance_guid = guid or None
        else:
            self._item_instance_guid = None

        self._item_icon_pm = self._try_load_item_icon(self._item_ctx)
        # определить класс предмета (EquipmentClass.Id) для фильтрации доступных карт
        if self._item_ctx:
            il = self._get_internal_level_for_item(self._item_ctx)
            self._item_class_id = self._class_id_from_internal(il)
        else:
            self._item_class_id = None


        # подтягиваем сохранённые карты для ЭТОГО экземпляра (или предмета)
        self._current_item_key = self._current_item_key_value()
        key = self._current_item_key

        if key is not None and key in self._per_item_cards:
            saved_cards = self._per_item_cards.get(key, {}) or {}
            saved_pms = self._per_item_pms.get(key, {}) or {}

            self._selected_cards = {i: dict(c) for i, c in saved_cards.items()}
            self._selected_card_pms = {}

            for idx, card in self._selected_cards.items():
                pm = saved_pms.get(idx)
                if pm is None or pm.isNull():
                    pm = self._try_load_card_icon(card)
                self._selected_card_pms[idx] = pm
        else:
            # для нового предмета/экземпляра слоты пустые
            self._selected_cards.clear()
            self._selected_card_pms.clear()

        self.update()

    def set_selected_cards(self, by_slot: Dict[int, Optional[dict]]) -> None:
        """Поднять выбранные карты, например из БД, и отрисовать превью в слотах."""
        self._selected_cards.clear()
        self._selected_card_pms.clear()

        for idx, card in (by_slot or {}).items():
            i = _safe_int(idx, 0)
            if i <= 0 or not card:
                continue

            c = dict(card)

            if "StatsText" not in c:
                stats_text = self._card_stats_text_for_paint(c)
                if stats_text:
                    c["StatsText"] = stats_text

            self._selected_cards[i] = c
            self._selected_card_pms[i] = self._try_load_card_icon(c)

        key = self._current_item_key_value()
        self._current_item_key = key

        if key is not None:
            self._set_item_cards_cache(
                key,
                {k: dict(v) for k, v in self._selected_cards.items()},
                dict(self._selected_card_pms),
                reason="set_selected_cards",
            )

        self._session_backup_cards = {k: dict(v) for k, v in self._selected_cards.items()}
        self._session_backup_pms = dict(self._selected_card_pms)

        self.update()

    def _set_item_cards_cache(
            self,
            key,
            cards_map: Optional[Dict[int, Dict]],
            pms_map: Optional[Dict[int, Optional[QPixmap]]] = None,
            *,
            reason: str = "",
    ) -> None:
        """
        Единая точка изменения _per_item_cards.

        Важно:
        любое подтверждённое изменение кэша карт должно проходить через этот метод,
        чтобы MainWindow мог сразу пересчитать характеристики и DPS.
        """
        if key is None:
            return

        clean_cards: Dict[int, Dict] = {}
        for idx, card in (cards_map or {}).items():
            i = _safe_int(idx, 0)
            if i <= 0 or not isinstance(card, dict):
                continue

            cid = _safe_int(
                card.get("Id")
                or card.get("Card_Id")
                or card.get("CardId")
                or card.get("card_id"),
                0,
            )
            if cid <= 0:
                continue

            clean_cards[int(i)] = dict(card)

        clean_pms: Dict[int, Optional[QPixmap]] = {}
        if isinstance(pms_map, dict):
            for idx, pm in pms_map.items():
                i = _safe_int(idx, 0)
                if i <= 0:
                    continue
                clean_pms[int(i)] = pm

        self._per_item_cards[key] = {int(k): dict(v) for k, v in clean_cards.items()}
        self._per_item_pms[key] = dict(clean_pms)

        try:
            self.item_cache_changed.emit(key, {int(k): dict(v) for k, v in clean_cards.items()})
        except Exception:
            pass

    def set_close_zone(self, rect: RectLike, *, kind: Optional[str] = None) -> None:
        qrect = QRect(*rect) if not isinstance(rect, QRect) else QRect(rect)
        if kind is None:
            self._session_override_close_rect = QRect(qrect)
        else:
            k = "weapon" if str(kind).lower().strip() == "weapon" else "equipment"
            if k == "weapon":
                global CLOSE_ZONE_WEAPON
                CLOSE_ZONE_WEAPON = (qrect.x(), qrect.y(), qrect.width(), qrect.height())
            else:
                global CLOSE_ZONE_EQUIPMENT
                CLOSE_ZONE_EQUIPMENT = (qrect.x(), qrect.y(), qrect.width(), qrect.height())

    def open_centered(
            self,
            owner: QWidget,
            kind: str = "equipment",
            close_zone: Optional[RectLike] = None,
            item: Optional[dict] = None,
            type_name_lookup=None,
            slot_key: Optional[str] = None,  # NEW
    ) -> None:
        # --- NEW: определяем kind по EquipmentType (IsMeleeWeapon/IsSingleHandWeapon != NULL) ---
        req_kind = "weapon" if str(kind).lower().strip() == "weapon" else "equipment"
        eff_kind = req_kind

        # slot_key (на всякий случай — fallback если Type_Id не удастся определить)
        _slot_key = None
        if slot_key is not None:
            _slot_key = str(slot_key).strip() or None
        elif item:
            try:
                sk = (item.get("slot_key") or item.get("SlotKey") or "").strip()
            except Exception:
                sk = ""
            if sk:
                _slot_key = sk

        # 1) Пытаемся определить по EquipmentType
        try:
            conn = self._db_conn()
        except Exception:
            conn = None

        tid = 0
        if item:
            tid = _safe_int(item.get("Type_Id") or item.get("TypeId") or 0, 0)

        if conn and tid > 0:
            row = None
            try:
                row = conn.execute(
                    "SELECT IsMeleeWeapon, IsSingleHandWeapon FROM EquipmentType WHERE Id=? LIMIT 1",
                    (int(tid),),
                ).fetchone()
            except Exception:
                row = None

            if row is not None:
                try:
                    if hasattr(row, "keys"):
                        is_melee = row["IsMeleeWeapon"]
                        is_single = row["IsSingleHandWeapon"]
                    else:
                        is_melee = row[0] if len(row) > 0 else None
                        is_single = row[1] if len(row) > 1 else None
                except Exception:
                    is_melee = None
                    is_single = None

                # РОВНО по твоему правилу: != NULL
                if (is_melee is not None) or (is_single is not None):
                    eff_kind = "weapon"
                else:
                    eff_kind = "equipment"
            # если типа нет в БД — оставляем req_kind
        else:
            # 2) fallback по slot_key (если Type_Id/БД недоступны)
            sk_l = (_slot_key or "").strip().lower().replace("ё", "е")
            if any(x in sk_l for x in ("weapon", "оруж", "spear", "копь", "копье", "копьё")):
                eff_kind = "weapon"
            elif any(x in sk_l for x in ("offhand", "off_hand", "off-hand", "shield", "щит", "orb", "сфера", "sphere")):
                eff_kind = "equipment"

        self._kind = "weapon" if eff_kind == "weapon" else "equipment"

        # --- дальше НИЧЕГО не меняю (твоя текущая логика) ---
        self._bg_pm = _load_file_image(CM_WEAPON_PATH if self._kind == "weapon" else CM_EQUIPMENT_PATH) or QPixmap(640,
                                                                                                                   400)
        if self._bg_pm.isNull():
            self._bg_pm = QPixmap(640, 400)
            self._bg_pm.fill(Qt.black)

        self.setFixedSize(self._bg_pm.size())
        self._session_override_close_rect = QRect(*close_zone) if (
                close_zone is not None and not isinstance(close_zone, QRect)
        ) else close_zone

        # NEW: запоминаем slot_key (например "ring1" / "ring2")
        self._item_slot_key = None
        if slot_key is not None:
            self._item_slot_key = str(slot_key)
        elif item:
            # если вызывающий уже положил slot_key в словарь предмета –
            # подхватим и его
            sk = (item.get("slot_key") or item.get("SlotKey") or "").strip()
            if sk:
                self._item_slot_key = sk

        self.set_type_name_lookup(type_name_lookup)
        self.set_context_item(item)

        gp = owner.mapToGlobal(owner.rect().center())
        self.move(gp.x() - self.width() // 2, gp.y() - self.height() // 2)

        self._hover_in_close = self._pressed_in_close = False
        self._pressed_in_apply = False
        self._pressed_in_clear = False

        self._hover_gold_key = None
        self._hover_gold_rect = None
        self._hover_gold_radius = 0.0

        self._press_pos = self._press_gpos = None
        self._dragging = False

        self._card_stats_cache.clear()
        self._upg_cond_cache.clear()

        # --- NEW: snapshot состояния на момент открытия (для Cancel/закрытия без Apply) ---
        self._session_applied = False
        self._session_backup_cards = {k: dict(v) for k, v in (self._selected_cards or {}).items()}
        self._session_backup_pms = dict(self._selected_card_pms or {})

        self.show()
        self.raise_()
        self.activateWindow()
        self.update()

    def _normalize_stats_dict(self, stats_obj: object) -> Dict[int, float]:
        """
        Приводит любые входные статы к виду Dict[int,float].
        Принимает dict с int/str ключами и числовыми/строковыми значениями.
        """
        out: Dict[int, float] = {}
        if not isinstance(stats_obj, dict):
            return out

        for k, v in (stats_obj or {}).items():
            try:
                ik = int(k)
            except Exception:
                continue

            try:
                fv = float(v)
            except Exception:
                try:
                    s = str(v).strip().replace(",", ".")
                    fv = float(s) if s else 0.0
                except Exception:
                    fv = 0.0

            out[ik] = fv

        return out

    def _pull_character_stats_from_owner(self, *, force: bool = False) -> Dict[int, float]:
        """
        Фоллбек: если по каким-то причинам set_character_stats не вызвали,
        попробуем достать статы из:
          1) self._current_stats_dict (если кто-то присвоил снаружи)
          2) parent.character_stats / parent._current_stats_dict
        """
        # если уже есть и не просим форс — просто вернём
        if not force and isinstance(getattr(self, "_character_stats", None), dict) and self._character_stats:
            return self._character_stats

        src = None

        # 1) то, что могли положить напрямую (ты это делал в MainWindow)
        try:
            src = getattr(self, "_current_stats_dict", None)
        except Exception:
            src = None

        # 2) из parent (обычно это MainWindow)
        if not isinstance(src, dict) or not src:
            owner = self.parent()
            if owner is not None:
                try:
                    src = getattr(owner, "character_stats", None)
                except Exception:
                    src = None
                if not isinstance(src, dict) or not src:
                    try:
                        src = getattr(owner, "_current_stats_dict", None)
                    except Exception:
                        src = None

        norm = self._normalize_stats_dict(src)

        # если нашли что-то — применяем как будто через set_character_stats (с очисткой кэшей)
        if norm:
            old = dict(getattr(self, "_character_stats", {}) or {})
            if old != norm:
                self._character_stats = dict(norm)
                # совместимость: если кто-то читает это поле
                try:
                    self._current_stats_dict = dict(norm)
                except Exception:
                    pass

                # ВАЖНО: статы влияют на Type=1 (атака), значит сбрасываем кэш
                self._card_stats_cache.clear()
                if self._picker_popup is not None:
                    try:
                        self._picker_popup._stats_cache_local.clear()
                        self._picker_popup._rebuild_list()
                    except Exception:
                        pass
                self.update()

        return dict(getattr(self, "_character_stats", {}) or {})

    def on_current_stats_changed(self, stats: dict[int, float] | None) -> None:
        """
        Совместимость: MainWindow может вызывать cw.on_current_stats_changed(...)
        Теперь тоже используем общий дебаунс-путь.
        """
        self._on_current_stats_changed(stats or {})

    def showEvent(self, e):
        super().showEvent(e)
        # если пока окно было скрыто статы успели измениться — применим при показе
        if getattr(self, "_pending_stats", None) is not None:
            try:
                self._stats_recalc_timer.start(0)
            except Exception:
                self._recalc_cards_from_current_stats()

    def _on_current_stats_changed(self, stats: dict) -> None:
        # кладём как есть (нормализация будет в set_character_stats)
        self._pending_stats = dict(stats) if isinstance(stats, dict) else {}

        # ✅ ВАЖНО: даже если окно скрыто — кэш статов карт нужно сбросить,
        # иначе тултипы/анкета будут показывать старые значения Type=1 (от атаки).
        self._card_stats_cache.clear()

        # если попап есть — тоже сбросим локальный кэш (дёшево)
        if self._picker_popup is not None:
            try:
                self._picker_popup._stats_cache_local.clear()
            except Exception:
                pass

        # если окно не видно — не дёргаем пересчёт выбранных карт и rebuild списка,
        # но тултип сможет посчитать актуально (кэш уже сброшен)
        if not self.isVisible():
            return

        try:
            self._stats_recalc_timer.start(0)
        except Exception:
            self._recalc_cards_from_current_stats()

    def _recalc_cards_from_current_stats(self) -> None:
        stats = self._pending_stats or {}
        self._pending_stats = None

        # ВАЖНО: это сбросит кэши и перерисует (и попап тоже, если открыт)
        self.set_character_stats(stats)

    def set_character_stats(self, stats: dict[int, float] | None) -> None:
        """Передай сюда итоговые статы персонажа (после calc_for_character)."""
        norm = self._normalize_stats_dict(stats)
        self._character_stats = dict(norm)

        # совместимость со старым путём (ты это поле мог трогать снаружи)
        try:
            self._current_stats_dict = dict(self._character_stats)
        except Exception:
            pass

        # ВАЖНО: значения Type=1 зависят от атаки, а статы карт у нас кэшируются по card.Id
        self._card_stats_cache.clear()

        # если попап открыт — у него тоже локальный кэш строк статов
        if self._picker_popup is not None:
            try:
                self._picker_popup._stats_cache_local.clear()
                self._picker_popup._rebuild_list()
            except Exception:
                pass

        # NEW: обновим StatsText у уже выбранных карт,
        # чтобы Apply/tooltip наружу отдавали актуальный текст (с учётом новой атаки)
        if self._selected_cards:
            for idx, card in list(self._selected_cards.items()):
                if not card:
                    continue
                c = dict(card)
                txt = (self._card_stats_text_for_paint(c) or "").strip()
                if txt:
                    c["StatsText"] = txt
                else:
                    c.pop("StatsText", None)
                self._selected_cards[idx] = c

        self.update()

    # ---------------- helpers / db ----------------
    def _current_attack_value_for_buff(self) -> float:
        """
        'Текущая Атака' для BuffDescriptionVariable.Type=1.

        ВАЖНО: даже если get_global_current_stats() возвращает dict,
        ключи могут быть строками -> тогда stats.get(10) == 0.
        Поэтому ВСЕ источники нормализуем через _normalize_stats_dict().

        + Добавлен print (не спамит: печатает 1 раз при первом вызове и дальше
          только если atk==0, но не чаще 1 раза в ~1.2 сек).
        """
        import time

        def _to_float(v) -> float:
            if v is None:
                return 0.0
            try:
                return float(v)
            except Exception:
                try:
                    s = str(v).strip().replace(",", ".")
                    return float(s) if s else 0.0
                except Exception:
                    return 0.0

        # 1) локальный источник (то, что пришло через set_character_stats / owner)
        if not (getattr(self, "_character_stats", None) or {}):
            try:
                self._pull_character_stats_from_owner(force=False)
            except Exception:
                pass

        local_raw = getattr(self, "_character_stats", None)
        local = self._normalize_stats_dict(local_raw) if isinstance(local_raw, dict) else {}

        # 2) глобальный источник (внутри characteristics_math он может вернуть dict без нормализации ключей)
        try:
            global_raw = get_global_current_stats()
        except Exception:
            global_raw = {}
        global_stats = self._normalize_stats_dict(global_raw) if isinstance(global_raw, dict) else {}

        # 3) QApplication property (самый "общий" источник между окнами)
        app_raw = {}
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                v = app.property("current_character_stats")
                if isinstance(v, dict):
                    app_raw = v
        except Exception:
            app_raw = {}
        app_stats = self._normalize_stats_dict(app_raw) if isinstance(app_raw, dict) else {}

        # выбираем лучший источник по приоритету
        # (если локальный пустой/без 10 — берём app, потом global)
        src_name = "local"
        stats = local

        if (not stats) or (10 not in stats):
            if app_stats and (10 in app_stats):
                src_name = "app"
                stats = app_stats
            elif global_stats:
                src_name = "global"
                stats = global_stats
            else:
                # хоть что-то
                if app_stats:
                    src_name = "app"
                    stats = app_stats
                elif global_stats:
                    src_name = "global"
                    stats = global_stats

        atk = _to_float((stats or {}).get(10, 0.0))

        # ---------------- debug print ----------------
        now = time.monotonic()
        last_ts = float(getattr(self, "_dbg_atk_last_print_ts", 0.0) or 0.0)
        printed_once = bool(getattr(self, "_dbg_atk_printed_once", False))

        need_print = False
        if not printed_once:
            need_print = True
        elif abs(atk) <= 1e-12 and (now - last_ts) > 1.2:
            need_print = True

        if need_print:
            try:
                def _head_keys(d: dict) -> list[int]:
                    try:
                        return sorted(int(k) for k in d.keys())[:20]
                    except Exception:
                        return []

                def _raw_key_types(d: dict) -> list[str]:
                    out = []
                    try:
                        for k in list(d.keys())[:10]:
                            out.append(type(k).__name__)
                    except Exception:
                        pass
                    return out

                #print(
                #    "[CARDS][ATK] "
                #    f"src={src_name} atk10={atk} | "
                #    f"local_len={len(local)} has10={10 in local} keys_head={_head_keys(local)} | "
                #    f"app_len={len(app_stats)} has10={10 in app_stats} keys_head={_head_keys(app_stats)} | "
                #    f"global_len={len(global_stats)} has10={10 in global_stats} keys_head={_head_keys(global_stats)} | "
                #    f"global_raw_key_types={_raw_key_types(global_raw) if isinstance(global_raw, dict) else []}",
                #    flush=True
                #)
            except Exception:
                pass

            try:
                self._dbg_atk_last_print_ts = float(now)
                self._dbg_atk_printed_once = True
            except Exception:
                pass

        return float(atk)

    def _format_plain_template(self, template: str, values_by_index: Dict[int, str]) -> str:
        """
        Подстановка {0},{1}... БЕЗ авто-плюсов и прочей "статовой" логики.
        """
        tpl = str(template or "").strip()
        if not tpl:
            return ""

        # собираем индексы, которые реально есть в шаблоне
        idxs = [int(m.group(1)) for m in re.finditer(r"\{(\d+)\}", tpl)]
        mx = max(idxs) if idxs else (-1)

        # формируем список значений под .format
        values: List[str] = []
        for i in range(mx + 1):
            values.append(str(values_by_index.get(i, "0")))

        try:
            return tpl.format(*values)
        except Exception:
            # fallback: regex replace
            def repl(m):
                idx = int(m.group(1))
                return str(values_by_index.get(idx, "0"))

            try:
                return re.sub(r"\{(\d+)\}", repl, tpl)
            except Exception:
                return tpl

    def _build_card_buff_description_lines(self, card_id: int) -> List[str]:
        """
        CardBuffDescription -> BuffDescription.Template + BuffDescriptionVariable(Index, Value, Type)

        Правила:
          - порядок строк = CardBuffDescription.OrderIndex (потом Id)
          - базовое значение CardBuffDescription.Value кладём в {0} (если не None)
          - BuffDescriptionVariable:
              Type=0 -> подставляем Value
              Type=1 -> подставляем (Value * текущая_атака)
            Index определяет, в какой {Index} подставлять
          - если переменная с тем же Index есть — она ПЕРЕЗАТИРАЕТ базовое {0}
        """

        cid = _safe_int(card_id, 0)
        if cid <= 0:
            return []

        debug = bool(getattr(self, "_debug_cards", False))
        flt = getattr(self, "_debug_card_id", None)
        if flt is not None and int(flt) != int(cid):
            debug = False

        conn = self._db_conn()
        if not conn:
            return []

        # 1) строки описаний бафов для карты
        try:
            rows = conn.execute(
                """
                SELECT
                    cbd.Id             AS CBDId,
                    cbd.Description_Id AS DescId,
                    cbd.Value          AS BaseVal,
                    cbd.OrderIndex     AS OIdx,
                    bd.Name            AS DescName,     -- <<< ДОБАВИЛИ
                    bd.Template        AS Template,
                    bd.IsStack         AS IsStack
                FROM CardBuffDescription cbd
                JOIN BuffDescription bd ON bd.Id = cbd.Description_Id
                WHERE cbd.Card_Id = ?
                ORDER BY cbd.OrderIndex ASC, cbd.Id ASC
                """,
                (int(cid),)
            ).fetchall()
        except Exception:
            rows = []

        if not rows:
            return []

        desc_ids: List[int] = []
        # было: (cbd_id, desc_id, base_val, template)
        ordered: List[tuple[int, int, object, str, str]] = []  # (cbd_id, desc_id, base_val, desc_name, template)

        for r in rows or []:
            if hasattr(r, "keys"):
                cbd_id = _safe_int(r["CBDId"], 0)
                desc_id = _safe_int(r["DescId"], 0)
                base_val = r["BaseVal"]
                desc_name = str(r["DescName"] or "")
                tpl = str(r["Template"] or "")
            else:
                cbd_id = _safe_int(r[0], 0)
                desc_id = _safe_int(r[1], 0)
                base_val = r[2]
                desc_name = str(r[4] or "")  # <<< ИНДЕКСЫ СДВИНУЛИСЬ
                tpl = str(r[5] or "")  # <<< ТУТ ТЕПЕРЬ Template

            if cbd_id > 0 and desc_id > 0 and tpl.strip():
                ordered.append((cbd_id, desc_id, base_val, desc_name, tpl))
                desc_ids.append(desc_id)

        if not ordered or not desc_ids:
            return []

        # 2) переменные для всех BuffDescription_Id одним запросом
        vars_by_desc: Dict[int, List[tuple[int, float, int]]] = {int(d): [] for d in set(desc_ids)}
        # --- определяем реальные названия колонок (у тебя раньше было жёстко 'Index', из-за этого часто 0-0) ---
        fk_col = self._pick_col("BuffDescriptionVariable",
                                ["BuffDescription_Id", "BuffDescriptionId", "Description_Id", "DescriptionId"])
        idx_col = self._pick_col("BuffDescriptionVariable", ["Index", "Idx", "OrderIndex", "OrderIdex"])
        val_col = self._pick_col("BuffDescriptionVariable", ["Value", "Val"])
        type_col = self._pick_col("BuffDescriptionVariable", ["Type", "VarType", "ValueType"])

        q = ",".join(["?"] * len(set(desc_ids)))
        try:
            vrows = conn.execute(
                f"""
                SELECT
                    BuffDescription_Id AS DescId,
                    "Index"            AS VIdx,
                    Value              AS VVal,
                    Type               AS VType
                FROM BuffDescriptionVariable
                WHERE BuffDescription_Id IN ({q})
                ORDER BY BuffDescription_Id ASC, "Index" ASC, Id ASC
                """,
                tuple(int(x) for x in sorted(set(desc_ids)))
            ).fetchall()
        except Exception:
            vrows = []

        def _to_float(v) -> float:
            if v is None:
                return 0.0
            try:
                return float(v)
            except Exception:
                try:
                    s = str(v).strip().replace(",", ".")
                    return float(s) if s else 0.0
                except Exception:
                    return 0.0

        for vr in vrows or []:
            if hasattr(vr, "keys"):
                did = _safe_int(vr["DescId"], 0)
                vidx = _safe_int(vr["VIdx"], 0)
                vval = _to_float(vr["VVal"])
                vtype = _safe_int(vr["VType"], 0)
            else:
                did = _safe_int(vr[0], 0)
                vidx = _safe_int(vr[1], 0)
                vval = _to_float(vr[2])
                vtype = _safe_int(vr[3], 0)

            if did > 0:
                vars_by_desc.setdefault(did, []).append((int(vidx), float(vval), int(vtype)))

        # 3) формирование строк
        cur_atk = float(self._current_attack_value_for_buff() or 0.0)
        out_lines: List[str] = []

        for _cbd_id, desc_id, base_val, desc_name, tpl in ordered:
            values_by_index: Dict[int, str] = {}

            if base_val is not None:
                values_by_index[0] = self._fmt_num(base_val)

            for vidx, vval, vtype in vars_by_desc.get(int(desc_id), []) or []:
                if int(vtype) == 1:
                    computed = float(vval) * cur_atk
                    values_by_index[int(vidx)] = str(self._round_half_up_int(computed))
                else:
                    values_by_index[int(vidx)] = self._fmt_num(vval)

            line = self._format_plain_template(tpl, values_by_index).strip()
            if not line:
                continue

            # <<< ВОТ ЭТО: добавляем "Name: " перед отформатированным Template
            dn = (desc_name or "").strip()
            if dn:
                low_line = line.strip().lower()
                low_dn = dn.lower()
                # если шаблон уже сам начинается с имени — не дублируем
                if not low_line.startswith(low_dn):
                    line = f"{dn}: {line}"

            out_lines.append(line)

        return out_lines

    def _card_stats_text_for_paint(self, card: Dict) -> str:
        """Быстрый текст статов для отрисовки: с кэшем по card.Id."""
        c = card or {}
        cid = _safe_int(c.get("Id"), 0)
        if cid > 0 and cid in self._card_stats_cache:
            return self._card_stats_cache[cid] or ""

        fn = self._card_stats_builder or self._build_card_stats_text
        try:
            s = (fn(c) if fn else "") or ""
        except Exception:
            s = ""

        if cid > 0:
            self._card_stats_cache[cid] = s
        return s

    def _card_text_rect_for_slot(self, rslot: QRect) -> QRect:
        """
        Прямоугольник, где рисуем текст карты "напротив слота".
        Настраивается тут:
          - +14: отступ от слота вправо
          - -6: подъем текста вверх
          - h=66: высота блока текста
          - right_pad=16: отступ от правого края окна
        """
        right_pad = 50
        x = rslot.right() + 12
        y = rslot.top() - 12
        w = max(10, self.width() - x - right_pad)
        h = rslot.height() + 20 #66
        #return QRect(x, y, w, h)

        return QRect(x, y, w, h).adjusted(0, 2, 0, -2)

    def _buff_prefix_part(self, line: str) -> str:
        s = (line or "").lstrip()
        c = s.find(":")
        if c > 0 and c < 60:
            return s[:c + 1]  # включая ":"
        return ""

    def _wrap_lines(self, text: str, fm: QFontMetrics, max_w: int, max_lines: int) -> List[str]:
        """Word-wrap на max_lines строк + многоточие в последней."""
        t = (text or "").strip()
        if not t or max_w <= 8 or max_lines <= 0:
            return []

        words = t.split()
        lines: List[str] = []
        cur = ""

        for w in words:
            test = (cur + " " + w).strip()
            if fm.horizontalAdvance(test) <= max_w:
                cur = test
                continue

            if cur:
                lines.append(cur)
                cur = w
            else:
                # очень длинное слово
                lines.append(fm.elidedText(w, Qt.ElideRight, max_w))
                cur = ""

            if len(lines) >= max_lines:
                break

        if len(lines) < max_lines and cur:
            lines.append(cur)

        if len(lines) > max_lines:
            lines = lines[:max_lines]

        # если обрезали и ещё есть хвост — элидим последнюю строку
        if len(lines) == max_lines:
            joined = " ".join(lines)
            if joined != t:
                lines[-1] = fm.elidedText(lines[-1] + " …", Qt.ElideRight, max_w)

        return lines

    def _draw_card_text_for_slot(self, p: QPainter, slot_idx: int, rslot: QRect) -> None:
        """Рисует название + статы выбранной карты рядом со слотом."""
        card = self._selected_cards.get(slot_idx)
        if not card:
            return

        rr = self._card_text_rect_for_slot(rslot)
        if rr.isEmpty():
            return

        name = str(card.get("Name") or f"ID {_safe_int(card.get('Id'), 0)}").strip()
        stats_raw = (self._card_stats_text_for_paint(card) or "").replace("\r", "").strip()

        # компактнее для отображения рядом со слотами
        stats_compact = " • \n".join([ln.strip() for ln in stats_raw.split("\n") if ln.strip()])

        p.save()
        p.setClipRect(rr)

        # --- name (1 строка) ---
        p.setFont(self._font_card_name)
        fm_name = QFontMetrics(self._font_card_name)
        name_line = fm_name.elidedText(name, Qt.ElideRight, rr.width())
        name_h = fm_name.height()

        # --- stats (2 строки) ---
        p.setFont(self._font_card_stats)
        fm_stats = QFontMetrics(self._font_card_stats)
        stats_lines = self._wrap_lines(stats_compact, fm_stats, rr.width(), 2)
        stats_h = fm_stats.height() * len(stats_lines)

        gap = 2 if stats_lines else 0
        total_h = name_h + gap + stats_h
        y = rr.y() + max(0, (rr.height() - total_h) // 2)

        p.setPen(QColor("#f1f1f1"))
        p.setFont(self._font_card_name)
        p.drawText(QRect(rr.x(), y, rr.width(), name_h), Qt.AlignLeft | Qt.AlignVCenter, name_line)
        y += name_h + gap

        if stats_lines:
            p.setFont(self._font_card_stats)
            h = fm_stats.height()
            for ln in stats_lines:
                rect = QRect(rr.x(), y, rr.width(), h)

                # 1) вся строка серым
                p.setPen(QColor("#bdbdbd"))
                p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, ln)

                # 2) поверх — префикс "Name:" желтым
                pref = self._buff_prefix_part(ln)
                if pref:
                    p.setPen(QColor("#f2d27a"))
                    p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, pref)

                y += h

        p.restore()

    def _item_rect(self) -> Optional[QRect]:
        return self._rect_from_tuple(WEAPON_ZONE_ITEM if self._kind == "weapon" else EQUIP_ZONE_ITEM)

    def _hoverable_zones(self) -> List[Tuple[str, QRect, float]]:
        """
        Список зон, которые подсвечиваем золотом при hover.
        (key, rect, radius)
        """
        out: List[Tuple[str, QRect, float]] = []
        if self._kind == "weapon":
            for idx, r in self._weapon_slot_rects():
                out.append((f"slot{idx}", r, 3.0))
        else:
            r = self._equipment_slot_rect()
            if r:
                out.append(("slot1", r, 3.0))

        r_apply = self._apply_rect()
        if r_apply:
            out.append(("apply", r_apply, 3.0))

        r_clear = self._clear_rect()
        if r_clear:
            out.append(("clear", r_clear, 3.0))

        return out

    def _hit_test_hover_zone(self, pos: QPoint) -> Tuple[Optional[str], Optional[QRect], float]:
        for key, r, radius in self._hoverable_zones():
            if r.contains(pos):
                return key, QRect(r), float(radius)
        return None, None, 0.0

    def _draw_gold_outline(self, p: QPainter, r: QRect, radius: float) -> None:
        if not r or r.isEmpty():
            return

        rr = r.adjusted(0, 0, 0, 0)  # чтобы не резалось по краям пикселей
        if rr.isEmpty():
            return

        path = QPainterPath()
        path.addRoundedRect(float(rr.x()), float(rr.y()), float(rr.width()), float(rr.height()), float(radius),
                            float(radius))

        p.setBrush(Qt.NoBrush)

        # glow
        p.setPen(self._gold_pen_glow)
        p.drawPath(path)

        # core
        p.setPen(self._gold_pen_core)
        p.drawPath(path)

        # subtle highlight
        p.setPen(self._gold_pen_hi)
        p.drawPath(path)

    def _db_conn(self):
        parent = self.parent()
        return getattr(getattr(parent, "data", None), "conn", None)

    def get_cards_for_item(self, item: Optional[dict],
                           *, kind: Optional[str] = None,
                           slot_key: Optional[str] = None) -> Dict[int, Dict]:
        """
        Вернёт {slot_index: card_dict} для переданного предмета,
        используя те же ключи, что и внутри окна.
        """
        key = self._item_key_for(item, kind=kind, slot_key=slot_key)
        if key is None:
            return {}

        cards = self._per_item_cards.get(key, {}) or {}
        # на всякий случай копию, чтобы снаружи не сломали внутреннее состояние
        return {i: dict(c) for i, c in cards.items()}

    def clone_cards_between_items(
            self,
            src_item: Optional[dict],
            dst_item: Optional[dict],
            *,
            kind: Optional[str] = None,
            src_slot_key: Optional[str] = None,
            dst_slot_key: Optional[str] = None,
    ) -> None:
        """
        Копирует уже применённые карты (после Apply) с одного предмета на другой.

        kind:
          "equipment" / "weapon". Если не указано — берётся self._kind.
        slot_key:
          Нужен только как запасной путь, если у предмета вдруг нет InstanceGuid
          (тогда ключ строится по (kind, Equip_Id, slot_key)).
        """
        if not src_item or not dst_item:
            return

        k = kind or self._kind or "equipment"

        # ключ источника
        src_key = self._item_key_for(src_item, kind=k, slot_key=src_slot_key)
        if src_key is None:
            return

        src_cards = self._per_item_cards.get(src_key)
        if not src_cards:
            # у исходного предмета просто нет карт — копировать нечего
            return

        src_pms = self._per_item_pms.get(src_key) or {}

        # ключ приёмника
        dst_key = self._item_key_for(dst_item, kind=k, slot_key=dst_slot_key or src_slot_key)
        if dst_key is None:
            return

        # делаем копии, чтобы изменение в одном месте не трогало другое
        self._per_item_cards[dst_key] = {idx: dict(card or {}) for idx, card in src_cards.items()}
        self._per_item_pms[dst_key] = dict(src_pms)

    def _etype_name_by_id(self, tid: int) -> str:
        if self._type_name_lookup:
            try:
                return str(self._type_name_lookup(tid) or "—")
            except Exception:
                pass

        conn = self._db_conn()
        if not conn or not tid:
            return "—"
        try:
            row = conn.execute("SELECT Name FROM EquipmentType WHERE Id=? LIMIT 1", (int(tid),)).fetchone()
            return row["Name"] if hasattr(row, "keys") else (row[0] or "—")
        except Exception:
            return "—"

    def _rect_from_tuple(self, t: Optional[Tuple[int, int, int, int]]) -> Optional[QRect]:
        if not t:
            return None
        x, y, w, h = map(int, t)
        if w <= 0 or h <= 0:
            return None
        return QRect(x, y, w, h)

    def _effective_close_rect(self) -> Optional[QRect]:
        if self._session_override_close_rect:
            return QRect(self._session_override_close_rect)
        return self._rect_from_tuple(CLOSE_ZONE_WEAPON if self._kind == "weapon" else CLOSE_ZONE_EQUIPMENT)

    def _drag_region_rect(self) -> Optional[QRect]:
        return self._rect_from_tuple(DRAG_REGION)

    def _equipment_slot_rect(self) -> Optional[QRect]:
        return self._rect_from_tuple(EQUIP_ZONE_SLOT1)

    def _weapon_slot_rects(self) -> List[Tuple[int, QRect]]:
        out: List[Tuple[int, QRect]] = []
        for idx, t in ((1, WEAPON_ZONE_SLOT1), (2, WEAPON_ZONE_SLOT2), (3, WEAPON_ZONE_SLOT3)):
            r = self._rect_from_tuple(t)
            if r:
                out.append((idx, r))
        return out

    def _slot_index_at_pos(self, pos: QPoint) -> Optional[int]:
        """Возвращает индекс слота (equipment: 1; weapon: 1..3) если клик внутри зоны слота."""
        if self._kind == "weapon":
            for idx, r in self._weapon_slot_rects():
                if r.contains(pos):
                    return idx
            return None
        r = self._equipment_slot_rect()
        return 1 if (r and r.contains(pos)) else None

    def _max_slots_for_kind(self) -> int:
        return 3 if self._kind == "weapon" else 1

    def _apply_rect(self) -> Optional[QRect]:
        return self._rect_from_tuple(WEAPON_ZONE_APPLY if self._kind == "weapon" else EQUIP_ZONE_APPLY)

    def _clear_rect(self) -> Optional[QRect]:
        return self._rect_from_tuple(WEAPON_ZONE_CLEAR if self._kind == "weapon" else EQUIP_ZONE_CLEAR)

    def _apply_current_selection(self) -> None:
        # помечаем, что изменения подтверждены
        self._session_applied = True

        # фиксируем состояние как «применённое» для этого предмета
        key = self._current_item_key_value()
        self._current_item_key = key

        if key is not None:
            self._set_item_cards_cache(
                key,
                {k: dict(v) for k, v in (self._selected_cards or {}).items()},
                dict(self._selected_card_pms or {}),
                reason="apply_current_selection",
            )

        # снапшот для последующего Cancel, если потом снова откроем окно
        self._session_backup_cards = {k: dict(v) for k, v in self._selected_cards.items()}
        self._session_backup_pms = dict(self._selected_card_pms)

        # закрыть попап, если открыт
        if self._picker_popup is not None:
            try:
                self._picker_popup.hide()
            except Exception:
                pass

        self._close_and_emit()

        # “сохранить” наружу текущее состояние по всем слотам
        for idx in range(1, self._max_slots_for_kind() + 1):
            card = self._selected_cards.get(idx)
            if card:
                self.card_picked.emit(idx, dict(card))
            else:
                self.card_cleared.emit(idx)

    def _clear_all_slots(self) -> None:
        # закрыть попап, если открыт
        if self._picker_popup is not None:
            try:
                self._picker_popup.hide()
            except Exception:
                pass

        self._selected_cards.clear()
        self._selected_card_pms.clear()
        self.update()
        # наружу ничего не шлём — окончательное состояние уйдёт в _apply_current_selection()

    # ---------------- card bonuses (BonusType.Template + CardBonusVariable) ----
    def _pick_col(self, table: str, candidates: List[str]) -> Optional[str]:
        conn = self._db_conn()
        if not conn:
            return None
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            actual = {}
            for r in rows or []:
                name = r["name"] if hasattr(r, "keys") else r[1]
                if name:
                    actual[str(name).lower()] = str(name)
            for c in candidates:
                hit = actual.get(str(c).lower())
                if hit:
                    return hit
        except Exception:
            pass
        return None

    def _upg_condition_text(self, cond_id: int, prefer_idx: int | None = None) -> str:
        cond_id = _safe_int(cond_id, 0)
        if cond_id <= 0:
            return ""

        # кэш теперь учитывает prefer_idx
        cache_key = (cond_id, int(prefer_idx) if prefer_idx is not None else -1)
        if cache_key in self._upg_cond_cache:
            return self._upg_cond_cache[cache_key]

        conn = self._db_conn()
        if not conn:
            self._upg_cond_cache[cache_key] = ""
            return ""

        fk_col = self._pick_col("UpgConditionVariable",
                                ["UpgCondition_Id", "UpgConditionId", "Condition_Id", "ConditionId"])
        val_col = self._pick_col("UpgConditionVariable", ["Value", "Text", "String", "Str", "Name"])
        idx_col = self._pick_col("UpgConditionVariable", ["Index", "Idx", "OrderIndex", "OrderIdex"])

        if not fk_col or not val_col:
            self._upg_cond_cache[cache_key] = ""
            return ""

        out = ""
        try:
            if idx_col:
                rows = conn.execute(
                    f'''SELECT "{idx_col}" AS VIdx, "{val_col}" AS VVal
                        FROM UpgConditionVariable
                        WHERE "{fk_col}"=?
                        ORDER BY "{idx_col}" ASC, Id ASC''',
                    (int(cond_id),)
                ).fetchall()

                m: Dict[int, str] = {}
                for r in rows or []:
                    i = _safe_int(r["VIdx"] if hasattr(r, "keys") else r[0], 0)
                    v = (r["VVal"] if hasattr(r, "keys") else r[1])
                    m[i] = self._fmt_num(v)

                # ✅ главное: сначала пробуем prefer_idx (например 2), потом 2, потом 0, потом любое
                if prefer_idx is not None and int(prefer_idx) in m:
                    out = m[int(prefer_idx)]
                elif 2 in m:
                    out = m[2]
                elif 0 in m:
                    out = m[0]
                else:
                    out = m[min(m.keys())] if m else ""
            else:
                row = conn.execute(
                    f'''SELECT "{val_col}" FROM UpgConditionVariable
                        WHERE "{fk_col}"=? ORDER BY Id ASC LIMIT 1''',
                    (int(cond_id),)
                ).fetchone()
                out = self._fmt_num(row[0] if row and not hasattr(row, "keys") else (row[val_col] if row else ""))
        except Exception:
            out = ""

        out = (out or "").strip()
        self._upg_cond_cache[cache_key] = out
        return out

    def _has_col(self, table: str, col: str) -> bool:
        conn = self._db_conn()
        if not conn:
            return False
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            for r in rows or []:
                name = r["name"] if hasattr(r, "keys") else r[1]
                if name == col:
                    return True
        except Exception:
            pass
        return False

    def _fmt_num(self, v) -> str:
        """Красиво приводит Value к строке: 10.0 -> '10', 10.5 -> '10.5'."""
        if v is None:
            return "0"
        try:
            if isinstance(v, (int, float)):
                f = float(v)
            else:
                s = str(v).strip().replace(",", ".")
                f = float(s) if s else 0.0
            if abs(f - int(f)) < 1e-9:
                return str(int(f))
            return str(f).rstrip("0").rstrip(".")
        except Exception:
            return str(v)

    def _round_half_up_int(self, x: float) -> int:
        """Округление к ближайшему целому (0.5 вверх): 13.5->14, -13.5->-14."""
        try:
            xf = float(x)
        except Exception:
            return 0
        if xf >= 0:
            return int(math.floor(xf + 0.5))
        return int(math.ceil(xf - 0.5))

    def _maybe_prefix_plus(self, template: str, idx: int, s: str) -> str:
        """
        Плюс добавляем только в одном случае:
            - это именно {0}
            - {0} является первым значимым содержимым шаблона
            - значение положительное
            - перед {0} в шаблоне уже не стоит + или -

        Примеры:
            "{0} к Силе"              -> "+7 к Силе"
            "{0}-{1} урона"           -> "+7-10 урона"
            "Урон увеличен на {0}"    -> "Урон увеличен на 7"
            "{1} при {0}"             -> "10 при 7"
            "+{0} к Силе"             -> "+7 к Силе", без "++7"
        """
        s = (s or "").strip()
        if not s:
            return s

        if s[0] in "+-":
            return s

        try:
            idx = int(idx)
        except Exception:
            return s

        # Плюс нужен только для {0}.
        if idx != 0:
            return s

        tpl = str(template or "")

        try:
            first_ph = re.search(r"\{(\d+)\}", tpl)
            if not first_ph:
                return s

            first_idx = _safe_int(first_ph.group(1), -1)
            if first_idx != 0:
                return s

            prefix = tpl[:first_ph.start()]

            # {0} должен идти первым значимым содержимым строки.
            if prefix.strip() != "":
                return s

            # Если в шаблоне уже явно указан знак перед {0}, второй плюс не добавляем.
            if re.search(r"[+\-]\s*\{0\}", tpl):
                return s
        except Exception:
            return s

        try:
            f = float(s.replace(",", "."))
            if f > 0:
                return "+" + s
        except Exception:
            pass

        return s

    def _format_bonus_template(
            self,
            template: str,
            values_by_index: Dict[int, str],
            *,
            skip_plus_indices: Optional[set[int]] = None
    ) -> str:
        tpl0 = str(template or "").strip()
        if not tpl0:
            if not values_by_index:
                return ""
            return " ".join(str(values_by_index[i]) for i in sorted(values_by_index.keys()))

        skip = set()
        try:
            skip = {int(x) for x in (skip_plus_indices or set())}
        except Exception:
            skip = set()

        # фикс "+ {0}" -> "+{0}" и "- {0}" -> "-{0}"
        tpl = re.sub(r"([+\-])\s+\{(\d+)\}", r"\1{\2}", tpl0)

        tpl_idxs = []
        try:
            tpl_idxs = [int(m.group(1)) for m in re.finditer(r"\{(\d+)\}", tpl)]
        except Exception:
            tpl_idxs = []

        need_mx = max(tpl_idxs) if tpl_idxs else -1
        dict_mx = max(values_by_index.keys()) if values_by_index else -1
        mx = max(need_mx, dict_mx)

        values: List[str] = []
        for i in range(mx + 1):
            raw = str(values_by_index.get(i, "0"))

            # Теперь _maybe_prefix_plus сама решает:
            # плюс только для {0}, только если {0} первый.
            if i not in skip:
                raw = self._maybe_prefix_plus(tpl, i, raw)

            values.append(raw)

        try:
            out = tpl.format(*values)
            out = re.sub(r"([+\-])\s+(?=\d)", r"\1", out)
            return out
        except Exception:
            pass

        def repl(m):
            idx = _safe_int(m.group(1), 0)
            raw = str(values_by_index.get(idx, "0"))

            if idx not in skip:
                raw = self._maybe_prefix_plus(tpl, idx, raw)

            return raw

        try:
            out = re.sub(r"\{(\d+)\}", repl, tpl)
            out = re.sub(r"([+\-])\s+(?=\d)", r"\1", out)
            return out
        except Exception:
            return tpl

    def _build_card_stats_text(self, card: Dict) -> str:
        """
        1) CardBonus -> BonusType.Template + CardBonusVariable(Index, Value)
           (+ логика UpgConditionVariable / UpgLevelStepVariable во 2-й плейсхолдер)

        2) ДОПОЛНИТЕЛЬНО:
           CardBuffDescription -> BuffDescription.Template + BuffDescriptionVariable(Index, Value, Type)
           сортировка по CardBuffDescription.OrderIndex.
        """
        cid = _safe_int((card or {}).get("Id"), 0)
        if cid <= 0:
            return ""

        debug = bool(getattr(self, "_debug_cards", True))
        if (not debug) and cid in self._card_stats_cache:
            return self._card_stats_cache[cid]

        conn = self._db_conn()
        if not conn:
            self._card_stats_cache[cid] = ""
            return ""

        # --------------------- helpers ---------------------
        def _cols(table: str) -> List[str]:
            try:
                rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
                return [(r["name"] if hasattr(r, "keys") else r[1]) for r in (rows or [])]
            except Exception:
                return []

        def _norm_name(s: str) -> str:
            return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())

        def _find_col(table: str, must: Tuple[str, ...], forbid: Tuple[str, ...] = ()) -> Optional[str]:
            cs = _cols(table)
            for c in cs:
                n = _norm_name(c)
                if all(t in n for t in must) and not any(t in n for t in forbid):
                    return c
            return None

        def _is_nonzero(x) -> bool:
            if x is None:
                return False
            s = str(x).strip()
            return s not in ("", "0", "0.0", "0,0")

        # --------------------- 1) CardBonus part ---------------------
        bonus_lines: List[str] = []

        try:
            cb_order_col = _find_col("CardBonus", ("order", "index"))
            cb_order_expr = f'cb."{cb_order_col}"' if cb_order_col else "cb.rowid"

            cb_cond_col = _find_col("CardBonus", ("upgcondition",))
            cb_step_col = _find_col("CardBonus", ("upglevelstep",))

            bt_tpl_col = _find_col("BonusType", ("template",)) or _find_col("BonusType", ("text",), ("id",))

            cbv_fk_col = _find_col("CardBonusVariable", ("cardbonus", "id"))
            cbv_idx_col = _find_col("CardBonusVariable", ("index",), ("id",)) or _find_col("CardBonusVariable",
                                                                                           ("idx",), ("id",))
            cbv_val_col = _find_col("CardBonusVariable", ("value",), ("id",)) or _find_col("CardBonusVariable",
                                                                                           ("val",),
                                                                                           ("id", "idx", "index"))

            can_build_bonus = bool(bt_tpl_col and cbv_fk_col and cbv_idx_col and cbv_val_col)

            if can_build_bonus:
                tpl_select = f'bt."{bt_tpl_col}" AS Template'
                cond_expr = f'cb."{cb_cond_col}"' if cb_cond_col else "NULL"
                step_expr = f'cb."{cb_step_col}"' if cb_step_col else "NULL"

                bonus_rows = conn.execute(
                    f"""
                    SELECT
                        cb.Id AS CBId,
                        {cb_order_expr} AS OIdx,
                        {tpl_select},
                        {cond_expr} AS CondRaw,
                        {step_expr} AS StepRaw
                    FROM CardBonus cb
                    LEFT JOIN BonusType bt ON bt.Id = cb.Type_Id
                    WHERE cb.Card_Id = ?
                    ORDER BY OIdx ASC, cb.Id ASC
                    """,
                    (int(cid),)
                ).fetchall()

                ordered: List[tuple[int, str, object, object]] = []
                cb_ids: List[int] = []

                for r in bonus_rows or []:
                    cbid = _safe_int(r["CBId"] if hasattr(r, "keys") else r[0], 0)
                    tpl = (r["Template"] if hasattr(r, "keys") else r[2]) or ""
                    cond_raw = (r["CondRaw"] if hasattr(r, "keys") else r[3])
                    step_raw = (r["StepRaw"] if hasattr(r, "keys") else r[4])
                    if cbid > 0:
                        cb_ids.append(cbid)
                        ordered.append((cbid, str(tpl), cond_raw, step_raw))

                if cb_ids:
                    vars_map: Dict[int, Dict[int, str]] = {cbid: {} for cbid in cb_ids}
                    q = ",".join(["?"] * len(cb_ids))

                    vrows = conn.execute(
                        f"""
                        SELECT
                            "{cbv_fk_col}"  AS CBId,
                            "{cbv_idx_col}" AS VIdx,
                            "{cbv_val_col}" AS VVal
                        FROM CardBonusVariable
                        WHERE "{cbv_fk_col}" IN ({q})
                        ORDER BY "{cbv_fk_col}" ASC, "{cbv_idx_col}" ASC, Id ASC
                        """,
                        tuple(int(x) for x in cb_ids)
                    ).fetchall()

                    for vr in vrows or []:
                        cbid = _safe_int(vr["CBId"] if hasattr(vr, "keys") else vr[0], 0)
                        vidx = _safe_int(vr["VIdx"] if hasattr(vr, "keys") else vr[1], 0)
                        vval = (vr["VVal"] if hasattr(vr, "keys") else vr[2])
                        if cbid in vars_map:
                            vars_map[cbid][vidx] = self._fmt_num(vval)

                    for cbid, tpl, cond_raw, step_raw in ordered:
                        vals = dict(vars_map.get(cbid, {}) or {})
                        skip: set[int] = set()

                        placeholders = [int(m.group(1)) for m in re.finditer(r"\{(\d+)\}", tpl or "")]
                        second_idx = placeholders[1] if len(placeholders) >= 2 else None

                        cond_txt = ""
                        if _is_nonzero(cond_raw):
                            sraw = str(cond_raw).strip()
                            if re.fullmatch(r"[+-]?\d+", sraw):
                                cond_id = _safe_int(sraw, 0)
                                if cond_id > 0:
                                    cond_txt = (self._upg_condition_text(cond_id, prefer_idx=second_idx) or "").strip()
                            if not cond_txt:
                                cond_txt = self._fmt_num(cond_raw).strip()
                        elif _is_nonzero(step_raw):
                            cond_txt = self._fmt_num(step_raw).strip()

                        if cond_txt and second_idx is not None:
                            vals[second_idx] = cond_txt
                            skip.add(second_idx)

                        line = self._format_bonus_template(tpl, vals, skip_plus_indices=skip).strip()
                        if line:
                            bonus_lines.append(line)

        except Exception:
            # если часть с CardBonus упала — всё равно покажем CardBuffDescription
            bonus_lines = []

        # --------------------- 2) CardBuffDescription part ---------------------
        buff_lines = self._build_card_buff_description_lines(cid)

        # --------------------- result ---------------------
        lines = []
        lines.extend(bonus_lines)
        lines.extend(buff_lines)

        text = "\n".join([ln for ln in lines if (ln or "").strip()])
        self._card_stats_cache[cid] = text
        return text

    # ---------------- icons ----------------
    def _try_load_item_icon(self, item: Optional[dict]) -> Optional[QPixmap]:
        if not item:
            return None
        img_id = item.get("Icon_Image_Id") or item.get("Image_Id") or item.get("CostumeImage_Id")
        if not img_id or not self._image_loader:
            return None
        try:
            raw = self._image_loader(int(img_id))
        except Exception:
            raw = None
        if not raw:
            return None
        pm = QPixmap()
        return pm if pm.loadFromData(raw) else None

    def _try_load_card_icon(self, card: Optional[dict]) -> Optional[QPixmap]:
        if not card or not self._image_loader:
            return None
        img_id = card.get("Image_Id") or card.get("ImageId") or card.get("ImageID")
        img_id = _safe_int(img_id, 0)
        if not img_id:
            return None

        if img_id in self._card_icon_cache:
            return self._card_icon_cache[img_id]

        try:
            raw = self._image_loader(int(img_id))
        except Exception:
            raw = None
        if not raw:
            return None

        pm = QPixmap()
        if pm.loadFromData(raw):
            self._card_icon_cache[img_id] = pm
            return pm
        return None

    # ---------------- slot resolving / cards query ----------------
    def _item_key_for(
            self,
            item: Optional[dict],
            *,
            kind: Optional[str] = None,
            slot_key: Optional[str] = None,
    ):
        """
        Строит тот же ключ, что и раньше в _current_item_key_value:
        1) Если есть InstanceGuid → он и есть ключ
        2) Иначе (kind, Equip_Id/Equipment_Id/Id, slot_key)
        """
        it = item or {}
        if not it:
            return None

        # --- основной путь: InstanceGuid ---
        inst = str(it.get("InstanceGuid") or "").strip()
        if inst:
            return inst

        # --- fallback: старый ключ по id + slot_key ---
        eid = _safe_int(
            it.get("Equip_Id")
            or it.get("Equipment_Id")
            or it.get("Id"),
            0,
        )
        if eid <= 0:
            return None

        k = kind or self._kind or "equipment"
        k = "weapon" if str(k).lower().strip() == "weapon" else "equipment"

        tag = (slot_key or it.get("slot_key") or it.get("SlotKey") or "").strip()

        return (k, eid, tag)

    def _current_item_key_value(self):
        """
        Уникальный ключ предмета для хранения выбранных карт.
        Просто обёртка вокруг _item_key_for для текущего self._item_ctx.
        """
        it = self._item_ctx or {}
        key = self._item_key_for(it, kind=self._kind, slot_key=self._item_slot_key)

        # Если ключ строковый — это InstanceGuid, кэшируем его
        if isinstance(key, str):
            self._item_instance_guid = key

        return key

    def build_tooltip_cards_payload_for_item(
            self,
            item: Optional[dict],
            *,
            kind: Optional[str] = None,
            slot_key: Optional[str] = None,
    ) -> List[Tuple[Optional[int], str, str]]:
        """
        Готовый список для тултипа:
            [(icon_id, name, desc), ...]

        icon_id:
          - для оружия, если карта – стихия и у её типа задан ToolTipImage_Id,
            сюда кладётся именно ToolTipImage_Id (Id из Image);
          - иначе None, чтобы тултип использовал стандартную картинку слота.

        desc — текст бонусов карты (ВСЕГДА пересчитываем актуально).
        """

        def _safe_int(v, default=0):
            try:
                return int(v)
            except Exception:
                return default

        key = self._item_key_for(item, kind=kind, slot_key=slot_key)
        if key is None:
            return []

        by_slot: Dict[int, Dict] = self._per_item_cards.get(key, {}) or {}
        out: List[Tuple[Optional[int], str, str]] = []

        is_weapon_kind = (str(kind or "").lower() == "weapon")

        for idx in sorted(by_slot.keys()):
            card_src = by_slot[idx] or {}

            # работаем с копией, чтобы не ломать хранилище ссылками
            card = dict(card_src)

            # по умолчанию – без спец. иконки
            icon_val: Optional[int] = None

            # для оружия смотрим, является ли карта «элементом»
            # и есть ли у типа ToolTipImage_Id / Image_Id
            if is_weapon_kind:
                elem_id = _safe_int(card.get("Element_Id"), 0)
                tip_id = _safe_int(card.get("ToolTipImage_Id") or card.get("Element_Id"), 0)
                if elem_id > 0 and tip_id > 0:
                    icon_val = tip_id

            name = str(card.get("Name") or f"ID {_safe_int(card.get('Id'), 0)}")

            # ✅ ВАЖНО: НЕ доверяем сохранённому StatsText,
            # потому что он мог быть посчитан при другой атаке.
            desc = (self._card_stats_text_for_paint(card) or "").replace("\r", "").strip()

            # (опционально) можно обновить и кэшированное поле в самой карте,
            # чтобы другие места, которые читают StatsText, тоже видели актуально:
            card_src["StatsText"] = desc

            out.append((icon_val, name, desc))

        return out

    def _resolve_slot_id_from_equipment_type(self, tid: int) -> Optional[int]:
        conn = self._db_conn()
        if not conn or tid <= 0:
            return None
        try:
            row = conn.execute("SELECT Slot_Id FROM EquipmentType WHERE Id=? LIMIT 1", (int(tid),)).fetchone()
            if not row:
                return None
            return _safe_int(row["Slot_Id"] if hasattr(row, "keys") else row[0], 0) or None
        except Exception:
            return None

    def _resolve_slot_id_from_equipment_instance(self, equip_id: int) -> Optional[int]:
        """
        Fallback: если у тебя связи заведены на Equipment.Slot_Id (а не EquipmentType.Slot_Id),
        этот метод может выручить. Если колонки нет — безопасно вернёт None.
        """
        conn = self._db_conn()
        if not conn or equip_id <= 0:
            return None
        try:
            row = conn.execute("SELECT Slot_Id FROM Equipment WHERE Id=? LIMIT 1", (int(equip_id),)).fetchone()
            if not row:
                return None
            return _safe_int(row["Slot_Id"] if hasattr(row, "keys") else row[0], 0) or None
        except Exception:
            return None

    def _slot_id_for_current_item(self) -> Optional[int]:
        """
        Основной путь: EquipmentType.Slot_Id по Type_Id.
        Fallback: Equipment.Slot_Id по Id/Equip_Id, если у тебя так заведено.
        """
        it = self._item_ctx or {}

        tid = _safe_int(it.get("Type_Id") or it.get("TypeId"), 0)
        slot_id = self._resolve_slot_id_from_equipment_type(tid) if tid > 0 else None
        if slot_id:
            return slot_id

        eid = _safe_int(it.get("Equip_Id") or it.get("Equipment_Id") or it.get("Id"), 0)
        if eid > 0:
            return self._resolve_slot_id_from_equipment_instance(eid)

        return None

    def _query_cards_for_slot(self, slot_id: int, *, slot_index: Optional[int] = None) -> List[Dict]:
        """
        Возвращает список карт, которые вообще подходят для slot_id.

        • Для оружия: в слоте 1 разрешены все карты, в слотах 2–3
          карты стихий (CardType.Element_Id > 0) отфильтровываются.
        • По классу предмета (C/B/A): показываем только карты, у которых
          CardType.MaxEquipmentClass_Id IS NULL (0) или равен классу предмета
          (EquipmentClass.Id: 1 – C, 2 – B, 3 – A).
        • По флагу Card.IsLegacy: показываем только те, у которых IsLegacy = 0.

        • Доп. фильтр: CardEquipmentType
            - если для карты ВООБЩЕ есть строки в CardEquipmentType, то карта
              показывается только если есть строка (Card_Id, Type_Id) под текущий EquipmentType.Id.
            - если для карты НЕТ строк в CardEquipmentType, карта остаётся доступной (как раньше).

        • Доп. фильтр: CardBonusVariableCondition (IsSingleHandWeapon)
            - если у карты есть релевантные условия по IsSingleHandWeapon (0/1) под текущий тип (или NULL тип),
              то:
                * если есть и 0 и 1 -> карта показывается всегда
                * если только 0 -> карта только для 2H (IsSingleHandWeapon=0)
                * если только 1 -> карта только для 1H (IsSingleHandWeapon=1)
            - если релевантных условий нет -> карта как раньше.

        • Доп. фильтр по BonusType.Id в CardBonus:
            - если карта содержит BonusType=314 -> показывать только если Equipment.InternalLevel >= EquipmentClass(Level) для Id=3
            - если карта содержит BonusType=320 -> показывать только если EquipmentType.IsMeleeWeapon = 1
        """
        conn = self._db_conn()
        if not conn or not slot_id:
            return []

        def _has_table(name: str) -> bool:
            try:
                return bool(conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
                    (name,),
                ).fetchone())
            except Exception:
                return False

        # текущий EquipmentType.Id предмета
        it = self._item_ctx or {}
        etype_id = _safe_int(it.get("Type_Id") or it.get("TypeId") or 0, 0)

        # внутренний уровень предмета (для правила 314)
        try:
            item_ilvl = int(self._get_internal_level_for_item(it)) if it else 0
        except Exception:
            item_ilvl = 0

        # IsSingleHandWeapon / IsMeleeWeapon предмета: сначала из item, иначе из EquipmentType
        item_is_1h = it.get("IsSingleHandWeapon", None)
        item_is_1h = _safe_int(item_is_1h, -1) if item_is_1h is not None else -1

        item_is_melee = it.get("IsMeleeWeapon", None)
        item_is_melee = _safe_int(item_is_melee, -1) if item_is_melee is not None else -1

        if etype_id > 0 and _has_table("EquipmentType"):
            try:
                row = conn.execute(
                    "SELECT IsMeleeWeapon, IsSingleHandWeapon FROM EquipmentType WHERE Id=? LIMIT 1",
                    (int(etype_id),),
                ).fetchone()
            except Exception:
                row = None
            if row is not None:
                try:
                    if hasattr(row, "keys"):
                        db_is_melee = row["IsMeleeWeapon"]
                        db_is_1h = row["IsSingleHandWeapon"]
                    else:
                        db_is_melee = row[0] if len(row) > 0 else None
                        db_is_1h = row[1] if len(row) > 1 else None
                except Exception:
                    db_is_melee = None
                    db_is_1h = None

                if item_is_melee not in (0, 1):
                    item_is_melee = _safe_int(db_is_melee, -1)
                if item_is_1h not in (0, 1):
                    item_is_1h = _safe_int(db_is_1h, -1)

        # ---------- условия 314 / 320 ----------
        has_cardbonus = _has_table("CardBonus")

        allow_314 = True
        if has_cardbonus and _has_table("EquipmentClass"):
            lvl_a = None
            try:
                row = conn.execute("SELECT Level FROM EquipmentClass WHERE Id=3 LIMIT 1").fetchone()
                if row is not None:
                    lvl_a = _safe_int(row["Level"] if hasattr(row, "keys") else row[0], None)
            except Exception:
                lvl_a = None

            if isinstance(lvl_a, int) and lvl_a > 0:
                # если не смогли определить internal level — считаем, что не проходит
                allow_314 = bool(item_ilvl >= lvl_a)

        allow_320 = bool(item_is_melee == 1)

        # ---------- включаем фильтры по таблицам ----------
        use_cet_filter = (etype_id > 0) and _has_table("CardEquipmentType")

        use_cbvc_filter = (
                self._kind == "weapon"
                and item_is_1h in (0, 1)
                and _has_table("CardBonusVariableCondition")
                and _has_table("CardBonusVariable")
                and _has_table("CardBonus")
        )

        extra_sql = ""
        params: list = [int(slot_id)]

        # ---------- CardEquipmentType (доп. фильтр) ----------
        if use_cet_filter:
            extra_sql += """
              AND (
                  NOT EXISTS (SELECT 1 FROM CardEquipmentType cet0 WHERE cet0.Card_Id = c.Id)
                  OR EXISTS (
                      SELECT 1
                      FROM CardEquipmentType cet
                      WHERE cet.Card_Id = c.Id
                        AND cet.Type_Id = ?
                  )
              )
            """
            params.append(int(etype_id))

        # ---------- BonusType 314 (доп. фильтр) ----------
        # если предмет НЕ проходит условие, то скрываем все карты, у которых есть CardBonus.Type_Id=314
        if has_cardbonus and (not allow_314):
            extra_sql += """
              AND NOT EXISTS (
                  SELECT 1 FROM CardBonus cb314
                  WHERE cb314.Card_Id = c.Id AND cb314.Type_Id = 314
              )
            """

        # ---------- BonusType 320 (доп. фильтр) ----------
        # если предмет НЕ melee, скрываем все карты с CardBonus.Type_Id=320
        if has_cardbonus and (not allow_320):
            extra_sql += """
              AND NOT EXISTS (
                  SELECT 1 FROM CardBonus cb320
                  WHERE cb320.Card_Id = c.Id AND cb320.Type_Id = 320
              )
            """

        # ---------- CardBonusVariableCondition (IsSingleHandWeapon) (доп. фильтр) ----------
        if use_cbvc_filter:
            if etype_id > 0:
                et_clause = "(cbc.EquipmentType_Id IS NULL OR cbc.EquipmentType_Id = ?)"
                et_params = [int(etype_id)]
            else:
                et_clause = "cbc.EquipmentType_Id IS NULL"
                et_params = []

            extra_sql += f"""
              AND (
                  NOT EXISTS (
                      SELECT 1
                      FROM CardBonusVariableCondition cbc
                      JOIN CardBonusVariable cbv ON cbv.Id = cbc.CardBonusVariable_Id
                      JOIN CardBonus cb ON cb.Id = cbv.CardBonus_Id
                      WHERE cb.Card_Id = c.Id
                        AND {et_clause}
                        AND cbc.IsSingleHandWeapon IN (0, 1)
                  )
                  OR (
                      EXISTS (
                          SELECT 1
                          FROM CardBonusVariableCondition cbc
                          JOIN CardBonusVariable cbv ON cbv.Id = cbc.CardBonusVariable_Id
                          JOIN CardBonus cb ON cb.Id = cbv.CardBonus_Id
                          WHERE cb.Card_Id = c.Id
                            AND {et_clause}
                            AND cbc.IsSingleHandWeapon = 0
                      )
                      AND
                      EXISTS (
                          SELECT 1
                          FROM CardBonusVariableCondition cbc
                          JOIN CardBonusVariable cbv ON cbv.Id = cbc.CardBonusVariable_Id
                          JOIN CardBonus cb ON cb.Id = cbv.CardBonus_Id
                          WHERE cb.Card_Id = c.Id
                            AND {et_clause}
                            AND cbc.IsSingleHandWeapon = 1
                      )
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM CardBonusVariableCondition cbc
                      JOIN CardBonusVariable cbv ON cbv.Id = cbc.CardBonusVariable_Id
                      JOIN CardBonus cb ON cb.Id = cbv.CardBonus_Id
                      WHERE cb.Card_Id = c.Id
                        AND {et_clause}
                        AND cbc.IsSingleHandWeapon = ?
                  )
              )
            """

            # et_clause повторяется 4 раза
            params.extend(et_params)  # NOT EXISTS
            params.extend(et_params)  # EXISTS 0
            params.extend(et_params)  # EXISTS 1
            params.extend(et_params)  # EXISTS match
            params.append(int(item_is_1h))

        # ---------- основной запрос ----------
        try:
            rows = conn.execute(f"""
                SELECT
                    c.Id        AS Id,
                    c.Name      AS Name,
                    c.Type_Id   AS Type_Id,
                    ct.Name     AS TypeName,
                    ct.Image_Id AS Image_Id,
                    ct.ToolTipImage_Id      AS ToolTipImage_Id,
                    ct.Element_Id           AS Element_Id,
                    ct.MaxEquipmentClass_Id AS MaxEquipmentClass_Id,
                    COALESCE(c.IsLegacy, 0) AS IsLegacy
                FROM CardEquipmentSlot ces
                JOIN Card c      ON c.Id = ces.Card_Id
                LEFT JOIN CardType ct ON ct.Id = c.Type_Id
                WHERE ces.Slot_Id = ?
                  AND COALESCE(c.IsLegacy, 0) = 0
                  {extra_sql}
                ORDER BY c.Name COLLATE NOCASE ASC, c.Id ASC
            """, tuple(params)).fetchall()
        except Exception:
            return []

        out: List[Dict] = []
        item_cls_id = self._item_class_id  # 1 – C, 2 – B, 3 – A (по таблице EquipmentClass)

        for r in rows or []:
            d = {k: r[k] for k in r.keys()} if hasattr(r, "keys") else {}
            d["Id"] = _safe_int(d.get("Id"), 0)
            d["Type_Id"] = _safe_int(d.get("Type_Id"), 0)
            d["Image_Id"] = _safe_int(d.get("Image_Id"), 0)  # CardType.Image_Id
            d["ToolTipImage_Id"] = _safe_int(d.get("ToolTipImage_Id"), 0)
            d["Element_Id"] = _safe_int(d.get("Element_Id"), 0)  # для фильтра по стихиям
            d["MaxEquipmentClass_Id"] = _safe_int(d.get("MaxEquipmentClass_Id"), 0)
            d["IsLegacy"] = _safe_int(d.get("IsLegacy"), 0)

            # --- фильтр карт стихий ---
            if (
                    self._kind == "weapon"
                    and (slot_index or 0) > 1
                    and d["Element_Id"] > 0
            ):
                continue

            # --- фильтр по классу предмета ---
            if item_cls_id is not None:
                max_cls_id = d["MaxEquipmentClass_Id"]
                if max_cls_id > 0 and max_cls_id != item_cls_id:
                    continue

            # --- фильтр по IsLegacy (на всякий случай ещё раз на уровне python) ---
            if d["IsLegacy"] != 0:
                continue

            out.append(d)

        return out

    # ---------------- selection state ----------------
    def _select_card_for_slot(self, slot_index: int, card: dict) -> None:
        # делаем копию словаря карты
        c = dict(card)

        stats_text = self._card_stats_text_for_paint(c)  # готовая строка с бонусами
        if stats_text:
            c["StatsText"] = stats_text

        self._selected_cards[slot_index] = c
        self._selected_card_pms[slot_index] = self._try_load_card_icon(c)
        self.update()


    def _clear_slot(self, slot_index: int) -> None:
        self._selected_cards.pop(slot_index, None)
        self._selected_card_pms.pop(slot_index, None)
        self.update()
        #self.card_cleared.emit(slot_index)

    def _open_card_picker(self, slot_index: int, anchor_rect_local: QRect) -> None:
        slot_id = self._slot_id_for_current_item()

        # закрыть старый попап (если остался)
        if getattr(self, "_picker_popup", None) is not None:
            try:
                self._picker_popup.hide()
                self._picker_popup.deleteLater()
            except Exception:
                pass
            self._picker_popup = None

        # лениво создаём меню
        try:
            from .choose_menu_all import ChooseCardMenu, CardChooseConfig  # type: ignore
        except Exception:
            # если вдруг не импортнулось — просто ничего не открываем
            return

        menu = getattr(self, "_choose_card_menu", None)
        if menu is None:
            menu = ChooseCardMenu(self, config=CardChooseConfig())
            setattr(self, "_choose_card_menu", menu)
        else:
            try:
                menu.hide()
            except Exception:
                pass

        # наполнение
        if not slot_id:
            cards: List[Dict] = []
        else:
            cards = self._query_cards_for_slot(slot_id, slot_index=slot_index)

        stats_fn = self._card_stats_builder or self._build_card_stats_text

        entries: List[Dict[str, Any]] = []
        for c in (cards or []):
            card = dict(c or {})
            if not card:
                continue

            pm = self._try_load_card_icon(card)

            # текст бонусов (может быть длинным) — именно он пойдёт в область 77px + мини-скролл
            try:
                bonus_text = (self._card_stats_text_for_paint(card) or "").replace("\r", "").strip()
            except Exception:
                try:
                    # fallback
                    bonus_text = (stats_fn(card) or "").replace("\r", "").strip()
                except Exception:
                    bonus_text = ""

            entries.append({
                "card": card,
                "icon_pm": pm,
                "bonus_text": bonus_text,
            })

        def _on_pick(card: dict) -> None:
            self._select_card_for_slot(slot_index, card)
            try:
                menu.hide()
            except Exception:
                pass

        # позиционирование рядом со слотом
        gp = self.mapToGlobal(anchor_rect_local.bottomLeft()) + QPoint(0, 6)

        menu.open_for(
            anchor_global=gp,
            entries=entries,
            on_pick=_on_pick,
            initial_search="",
            focus_search=True,  # сразу активный ввод
        )

    # ---------------- painting ----------------
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform, True)

        # фон
        if self._bg_pm and not self._bg_pm.isNull():
            p.drawPixmap(self.rect(), self._bg_pm)

        # превью выбранных карт в слотах (рисуем всегда)
        p.setPen(self._slot_border_pen)
        if self._kind == "weapon":
            for idx, rslot in self._weapon_slot_rects():
                # лёгкая рамка, чтобы визуально понимать зону
                p.drawRoundedRect(rslot.adjusted(0, 0, -1, -1), 6, 6)

                pm = self._selected_card_pms.get(idx)
                if pm and not pm.isNull():
                    scaled = pm.scaled(rslot.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    dst = QRect(0, 0, scaled.width(), scaled.height())
                    dst.moveCenter(rslot.center())
                    p.drawPixmap(dst, scaled)

                # NEW: текст карты напротив слота
                self._draw_card_text_for_slot(p, idx, rslot)
        else:
            rslot = self._equipment_slot_rect()
            if rslot:
                p.drawRoundedRect(rslot.adjusted(0, 0, -1, -1), 6, 6)
                pm = self._selected_card_pms.get(1)
                if pm and not pm.isNull():
                    scaled = pm.scaled(rslot.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    dst = QRect(0, 0, scaled.width(), scaled.height())
                    dst.moveCenter(rslot.center())
                    p.drawPixmap(dst, scaled)

                # NEW: текст карты напротив слота
                self._draw_card_text_for_slot(p, 1, rslot)

        # отрисовка иконки и блока инфо
        if self._item_ctx:
            item_rect = self._rect_from_tuple(WEAPON_ZONE_ITEM if self._kind == "weapon" else EQUIP_ZONE_ITEM)
            if item_rect:
                # иконка предмета
                if self._item_icon_pm and not self._item_icon_pm.isNull():
                    scaled = self._item_icon_pm.scaled(item_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    dst = QRect(0, 0, scaled.width(), scaled.height())
                    dst.moveCenter(item_rect.center())
                    p.drawPixmap(dst, scaled)

                # текстовая колонка справа от иконки
                right_pad = 16
                left = item_rect.right() + 20
                top = item_rect.top() - 20
                w = max(10, self.width() - left - right_pad)

                # заголовок (2 строки)
                p.setFont(self._font_title)
                p.setPen(QColor("#ffffff"))
                fm = QFontMetrics(self._font_title)
                title_lines = self._wrap_two_lines(self._title_text(), fm, w)
                line_h = fm.height()
                y = top
                for ln in title_lines:
                    p.drawText(QRect(left, y, w, line_h), Qt.AlignLeft | Qt.AlignVCenter, ln)
                    y += line_h

                # Защита/Атака
                label, base, bonus = self._extract_base_plus()
                p.setFont(self._font_text)
                fm2 = QFontMetrics(self._font_text)
                y += max(4, line_h // 4)

                p.setPen(QColor("#dddddd"))
                base_txt = f"{label}: {base}"
                p.drawText(QRect(left, y, w, fm2.height()), Qt.AlignLeft | Qt.AlignVCenter, base_txt)
                if bonus > 0:
                    base_w = fm2.horizontalAdvance(base_txt + " ")
                    p.setPen(QColor(72, 200, 96))
                    p.drawText(QRect(left + base_w, y, w - base_w, fm2.height()),
                               Qt.AlignLeft | Qt.AlignVCenter, f"+ {bonus}")
                y += fm2.height() + 2

                # Тип • Класс
                t = self._type_text()
                c = self._class_text()
                p.setPen(QColor("#bbbbbb"))
                p.drawText(QRect(left, y, w, fm2.height()), Qt.AlignLeft | Qt.AlignVCenter, f"{t}   •   Класс: {c}")

        # GOLD HOVER: поверх всего (кроме крестика-ховера)
        if self._hover_gold_rect is not None and not self._hover_gold_rect.isEmpty() and not self._hover_in_close:
            self._draw_gold_outline(p, self._hover_gold_rect, self._hover_gold_radius)

        # hover-оверлей крестика
        r = self._effective_close_rect()
        if r and self._hover_in_close and self._pm_close_hover and not self._pm_close_hover.isNull():
            p.drawPixmap(r, self._pm_close_hover.scaled(r.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # ---- текст/мета для правой панели -----------------------------------------
    def _title_text(self) -> str:
        it = self._item_ctx or {}
        name = (it.get("Name") or it.get("Title") or "").strip() or "Предмет"
        up = (it.get("ForgeLevel") or it.get("UpgradeLevel") or it.get("Plus")
              or it.get("Refine") or it.get("EnhanceLevel"))
        n = _safe_int(up, 0)
        return f"+{n} {name}" if n > 0 else name

    def _type_text(self) -> str:
        it = self._item_ctx or {}
        tid = _safe_int(it.get("Type_Id") or it.get("TypeId"), 0)
        if tid:
            t = self._etype_name_by_id(tid)
            if t and t != "—":
                return t
        t = (it.get("TypeName") or it.get("EquipmentType") or it.get("ItemType") or "").strip()
        return t or "—"

    def _get_internal_level_for_item(self, item: dict) -> int:
        conn = self._db_conn()

        def _toi(v, d=0):
            try:
                return int(v)
            except Exception:
                return d

        equip_id = _toi(item.get("Equip_Id") or item.get("Equipment_Id") or item.get("Id"), 0)
        if conn and equip_id:
            try:
                row = conn.execute("SELECT InternalLevel FROM Equipment WHERE Id=? LIMIT 1", (equip_id,)).fetchone()
                if row is not None:
                    val = row["InternalLevel"] if hasattr(row, "keys") else row[0]
                    return _toi(val, 1)
            except Exception:
                pass
        return _toi(item.get("InternalLevel") or item.get("Level") or item.get("RequiredLevel") or 1, 1)

    def _class_id_from_internal(self, internal_level: int) -> Optional[int]:
        """
        Возвращает Id записи из EquipmentClass по внутреннему уровню предмета.
        Используется для сравнения с CardType.MaxEquipmentClass_Id.
        """
        conn = self._db_conn()
        if not conn:
            return None
        try:
            rows = conn.execute("SELECT Id, Level FROM EquipmentClass ORDER BY Level").fetchall()
        except Exception:
            return None

        il = int(internal_level) if internal_level else 0
        cls_id: Optional[int] = None
        for r in rows or []:
            rid = _safe_int(r["Id"] if hasattr(r, "keys") else r[0], 0)
            lvl = _safe_int(r["Level"] if hasattr(r, "keys") else r[1], 0)
            if il >= lvl:
                cls_id = rid
        return cls_id

    def _class_from_internal(self, internal_level: int) -> str:
        conn = self._db_conn()
        if not conn:
            return "—"
        try:
            rows = conn.execute("SELECT Name, Level FROM EquipmentClass ORDER BY Level").fetchall()
        except Exception:
            return "—"
        il = int(internal_level) if internal_level else 0
        klass = "—"
        for r in rows or []:
            name = (r["Name"] if hasattr(r, "keys") else r[0]) or ""
            lvl = (r["Level"] if hasattr(r, "keys") else r[1]) or 0
            try:
                lvl = int(lvl)
            except Exception:
                lvl = 0
            if name and il >= lvl:
                klass = name
        return klass or "—"

    def _class_text(self) -> str:
        it = self._item_ctx or {}
        il = self._get_internal_level_for_item(it)
        klass = self._class_from_internal(il)
        if klass and klass != "—":
            return klass
        return (it.get("ItemClass") or it.get("Class") or it.get("ClassName") or "—")

    def _extract_base_plus(self) -> tuple[str, int, int]:
        it = self._item_ctx or {}

        def gi(*keys, default=0):
            for k in keys:
                if it.get(k) is not None:
                    try:
                        return int(it.get(k))
                    except Exception:
                        return default
            return default

        atk = gi("Attack", "Atk", "Damage", "Dmg", default=0)
        df = gi("Defense", "Defence", "Armor", "Def", default=0)

        show_attack = (atk > 0 and atk >= df)
        label = "Атака" if show_attack else "Защита"
        base = atk if show_attack else df

        forge_level = gi("__forge_level", "ForgeLevel", "UpgradeLevel", default=0)
        forge_bonus = gi("__forge_bonus", "ForgeBonus", "UpgradeMainBonus", default=0)
        plus = forge_bonus if forge_level > 0 else 0

        if show_attack:
            plus_fields = ("AttackPlus", "Attack_Bonus", "AttackBonus", "BonusAttack", "DamagePlus", "DmgPlus")
            total_fields = ("TotalAttack", "TotalAtk")
        else:
            plus_fields = ("DefensePlus", "Defense_Bonus", "DefenseBonus", "BonusDefense", "ArmorPlus", "DefPlus")
            total_fields = ("TotalDefense", "TotalDefence", "TotalArmor")

        for k in plus_fields:
            v = gi(k, default=0)
            if v > 0:
                plus = max(plus, v)
                break

        for k in total_fields:
            tot = gi(k, default=0)
            if tot and tot > base:
                plus = max(plus, tot - base)
                break

        return label, base, max(0, plus)

    def _wrap_two_lines(self, text: str, fm: QFontMetrics, max_w: int) -> List[str]:
        words = str(text or "").split()
        if not words:
            return [""]

        lines: List[str] = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if fm.horizontalAdvance(test) <= max_w:
                cur = test
                continue

            if cur:
                lines.append(cur)
            else:
                piece = ""
                for ch in w:
                    if fm.horizontalAdvance(piece + ch) <= max_w:
                        piece += ch
                    else:
                        break
                lines.append(piece or w)
            cur = w

            if len(lines) >= 2:
                break

        if len(lines) < 2 and cur:
            lines.append(cur)

        if len(lines) == 2 and (" ".join(lines) != " ".join(words)):
            ell = "…"
            s = lines[1]
            while s and fm.horizontalAdvance(s + ell) > max_w:
                s = s[:-1]
            lines[1] = (s + ell) if s else ell

        return lines[:2]

    # ---------------- events (drag/close + клики по слотам) ---------------------
    def eventFilter(self, obj, ev):
        if obj is self:
            et = ev.type()

            if et == QEvent.MouseMove:
                pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()

                # hover крестика
                r_close = self._effective_close_rect()
                in_close = bool(r_close and r_close.contains(pos))
                changed = False

                if in_close != self._hover_in_close:
                    self._hover_in_close = in_close
                    changed = True

                # hover золотых зон (если не на крестике)
                if self._hover_in_close:
                    if self._hover_gold_key is not None or self._hover_gold_rect is not None:
                        self._hover_gold_key = None
                        self._hover_gold_rect = None
                        self._hover_gold_radius = 0.0
                        changed = True
                else:
                    key, rect, rad = self._hit_test_hover_zone(pos)
                    if key != self._hover_gold_key:
                        self._hover_gold_key = key
                        self._hover_gold_rect = rect
                        self._hover_gold_radius = rad
                        changed = True

                if changed:
                    self.update()

                # drag
                if self._dragging:
                    gp = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()
                    self.move(gp - self._drag_offset)
                    return True

                # автозапуск drag
                if (ev.buttons() & Qt.LeftButton) and self._press_pos is not None and not (
                        self._pressed_in_close or self._pressed_in_apply or self._pressed_in_clear
                ):
                    if (pos - self._press_pos).manhattanLength() >= DRAG_THRESHOLD_PX:
                        drag_rect = self._drag_region_rect()
                        if (drag_rect is None) or drag_rect.contains(self._press_pos):
                            gp0 = self._press_gpos or (
                                ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos())
                            self._dragging = True
                            self._drag_offset = gp0 - self.frameGeometry().topLeft()
                            return True
                return False

            if et == QEvent.Leave:
                changed = False
                if self._hover_in_close:
                    self._hover_in_close = False
                    changed = True
                if self._hover_gold_key is not None or self._hover_gold_rect is not None:
                    self._hover_gold_key = None
                    self._hover_gold_rect = None
                    self._hover_gold_radius = 0.0
                    changed = True
                if changed:
                    self.update()
                return False

            if et == QEvent.MouseButtonPress:
                if ev.button() == Qt.LeftButton:
                    pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                    gp = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()
                    self._press_pos = QPoint(pos)
                    self._press_gpos = QPoint(gp)

                    r_close = self._effective_close_rect()
                    self._pressed_in_close = bool(r_close and r_close.contains(pos))

                    r_apply = self._apply_rect()
                    r_clear = self._clear_rect()
                    self._pressed_in_apply = bool(r_apply and r_apply.contains(pos))
                    self._pressed_in_clear = bool(r_clear and r_clear.contains(pos))
                    return True
                return False

            if et == QEvent.MouseButtonRelease:
                if ev.button() == Qt.LeftButton:
                    pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()

                    # клик по Apply
                    r_apply = self._apply_rect()
                    if self._pressed_in_apply and r_apply and r_apply.contains(pos):
                        if self._press_pos is None or (pos - self._press_pos).manhattanLength() < DRAG_THRESHOLD_PX:
                            self._apply_current_selection()
                        self._pressed_in_apply = False
                        self._pressed_in_clear = False
                        self._pressed_in_close = False
                        self._press_pos = None
                        self._press_gpos = None
                        return True

                    # клик по Clear
                    r_clear = self._clear_rect()
                    if self._pressed_in_clear and r_clear and r_clear.contains(pos):
                        if self._press_pos is None or (pos - self._press_pos).manhattanLength() < DRAG_THRESHOLD_PX:
                            self._clear_all_slots()
                        self._pressed_in_apply = False
                        self._pressed_in_clear = False
                        self._pressed_in_close = False
                        self._press_pos = None
                        self._press_gpos = None
                        return True

                    # завершение drag
                    if self._dragging:
                        self._dragging = False
                        self._press_pos = None
                        self._press_gpos = None
                        self._pressed_in_close = False
                        self._pressed_in_apply = False
                        self._pressed_in_clear = False
                        return True

                    # клик по кресту (закрыть)
                    r_close = self._effective_close_rect()
                    if self._pressed_in_close and r_close and r_close.contains(pos):
                        if self._press_pos is None or (pos - self._press_pos).manhattanLength() < DRAG_THRESHOLD_PX:
                            self._close_and_emit()
                            return True

                    # клик по слотам карт
                    slot_idx = self._slot_index_at_pos(pos)
                    if slot_idx is not None:
                        if self._kind == "weapon":
                            anchor = next((r for i, r in self._weapon_slot_rects() if i == slot_idx), None)
                        else:
                            anchor = self._equipment_slot_rect()
                        if anchor:
                            self._open_card_picker(slot_idx, anchor)

                        self._press_pos = None
                        self._press_gpos = None
                        self._pressed_in_close = False
                        self._pressed_in_apply = False
                        self._pressed_in_clear = False
                        return True

                    self._press_pos = None
                    self._press_gpos = None
                    self._pressed_in_close = False
                    self._pressed_in_apply = False
                    self._pressed_in_clear = False
                    return True
                return False

            if et == QEvent.KeyPress:
                if ev.key() == Qt.Key_Escape:
                    self._close_and_emit()
                    return True

        return super().eventFilter(obj, ev)

    # ---------------- internals ----------------
    def _close_and_emit(self):
        # если закрыли БЕЗ Apply — откатить изменения к снимку
        if not getattr(self, "_session_applied", False):
            self._selected_cards = {k: dict(v) for k, v in (self._session_backup_cards or {}).items()}
            self._selected_card_pms = dict(self._session_backup_pms or {})
            self.update()

        self.hide()
        self.closed.emit()

