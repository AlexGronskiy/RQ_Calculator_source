#inventory.py
from __future__ import annotations
from pathlib import Path
from typing import Optional, Tuple, Callable, Dict, Set
import copy
import uuid
import time
import traceback


from PySide6.QtCore import Qt, QRect, QPoint, QEvent, QTimer
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QFont, QImage
from PySide6.QtWidgets import QWidget, QLabel, QApplication, QMenu

from .weapon_equipment_button import _render_bonus_lines

# ----------------------- базовые ресурсы / геометрия ----------------------------
INV_BG_PATH      = "resources/inventory/inventory.png"
CLOSE_HOVER_PATH = "resources/helper_buttons/close_button_active.png"

CLOSE_POS_DESIGN = (345, 4)
CLOSE_SIZE_PX    = 24
CLOSE_PAD_PX     = 0

ROWS, COLS = 13, 6
CELL, GAP  = 54, 2
GRID_ORIGIN_DESIGN = (22, 81)
ICON_SCALE = 0.92

# --- фразы по заполненности -----------------------------------------------------
CAPACITY_MESSAGES: dict[int, str] = {
    0:  "Пустовато, лута как после четвёрок.",
    6:  "Пара безделушек, под разогрев.",
    12: "Карманы пока не трещат от хлама.",
    18: "У карманов глаз дёргается.",
    24: "Может, хватит столько хлама?",
    30: "Тащишься как ходячая барахолка.",
    36: "Верблюд уважительно молчит.",
    42: "Спина просит отпуск... и ортопеда.",
    48: "Ради шмота дом закладываем?",
    54: "Кредит под залог совести одобрен.",
    60: "Торговцы уже занесли тебя в избранное.",
    66: "Продам печень. Дорого. Беру Эдика!",
    72: "Коллекторы в двери не стучат?",
    78: "Заполнено! Ни пикселя не отрисую!",
}

# --- отладка (в консоль) --------------------------------------------------------
DEBUG_INV = True

POPUP_MENU_STYLE = """
QMenu {
    background: transparent;
    border: none;
    padding: 6px;
}

QMenu::separator {
    height: 1px;
    background: rgba(145, 140, 128, 190);
    margin: 6px 8px;
}

QMenu::item {
    color: #f2c45d;
    background: transparent;
    padding: 6px 14px;
    margin: 1px 2px;
    border-radius: 5px;
    font-weight: 700;
}

QMenu::item:selected {
    color: #fff0b0;
    background-color: rgba(80, 80, 80, 145);
    border-radius: 5px;
}

QMenu::item:pressed {
    color: #ffffff;
    background-color: rgba(110, 100, 80, 170);
}

QMenu::item:disabled {
    color: rgba(180, 180, 180, 120);
}

QMenu::indicator {
    width: 14px;
    height: 14px;
}
"""


def _apply_popup_menu_style(menu: QMenu) -> None:
    if menu is None:
        return

    try:
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
    except Exception:
        pass

    try:
        menu.setWindowFlag(Qt.NoDropShadowWindowHint, True)
    except Exception:
        pass

    menu.setStyleSheet(POPUP_MENU_STYLE)


_INV_LOG_SEQ = 0
def _next_seq() -> int:
    global _INV_LOG_SEQ
    _INV_LOG_SEQ += 1
    return _INV_LOG_SEQ

def _stack_tail(limit: int = 8) -> str:
    try:
        st = traceback.extract_stack()
        # выкидываем последние 2 кадра (эта функция + её caller)
        st = st[:-2]
        tail = st[-limit:]
        # только имена файлов (без путей), чтобы читалось
        return " > ".join([f"{Path(fr.filename).name}:{fr.lineno}:{fr.name}" for fr in tail])
    except Exception:
        return "stack:n/a"

#def _d(*a):
#    if DEBUG_INV:
#        print("[INV]", *a)


# наследование классов (донор → реципиенты)
DONOR_MAP: dict[int, set[int]] = {1:{2,3}, 4:{5,6}, 7:{8,9}, 10:{11,12}}

# --- конфиг счётчика ------------------------------------------------------------
COUNTER_CFG = {
    "x":  230,   # дизайн-координаты, пойдут в self._project(...)
    "y":  43,
    "w":  120,
    "h":  24,
    "font_px": 16,        # базовый размер шрифта (масштабируется по _scale())
    "align": "right",     # "left" | "center" | "right"
    "color": "#e6d27a",   # цвет текста счётчика
}

DRAG_THRESHOLD_PX = 6  # сколько пикселей нужно сдвинуть, чтобы начался перетаскивание

_INV_LAST_POS: Optional[QPoint] = None

# ------------------------------ утилиты -----------------------------------------
def _equip_slot_keys_lower_from_parent(parent) -> set[str]:
    """
    Возвращает множество допустимых ключей экип-слотов (lowercase),
    берём из parent._selected_items (это самый правильный источник).
    """
    keys: set[str] = set()
    try:
        if parent and hasattr(parent, "_selected_items") and isinstance(parent._selected_items, dict):
            keys |= {str(k).strip().lower() for k in parent._selected_items.keys()}
    except Exception:
        pass

    # алиасы, которые у нас могут прилетать из _hit_zone
    keys |= {"ring", "weapon", "offhand"}
    return keys

def _resolve_resource(rel_path: str) -> str:
    p = Path(rel_path)
    for c in (Path.cwd() / p,
              Path(__file__).resolve().parents[2] / p,
              Path(__file__).resolve().parents[3] / p):
        if c.exists():
            return str(c)
    return str(p)

def _load_file_image(rel_path: str) -> Optional[QPixmap]:
    pm = QPixmap(_resolve_resource(rel_path))
    return pm if not pm.isNull() else None

def deep_clone(item: dict | None) -> dict | None:
    return copy.deepcopy(item) if item is not None else None

def get_instance_guid(item: dict | None) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    return item.get("InstanceGuid") or item.get("InstanceGUID") or item.get("Instance_Id")

def ensure_local_guid(item: dict) -> dict:
    if not isinstance(item, dict):
        return item
    if not get_instance_guid(item):
        item = dict(item)
        item["InstanceGuid"] = str(uuid.uuid4())
    return item

# ------------------------------ клетки ------------------------------------------
class CellWidget(QLabel):
    def __init__(self, row: int, col: int, parent=None):
        super().__init__(parent)
        self.row, self.col = row, col
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setScaledContents(False)
        self._hover = False
        self.setStyleSheet("""
            QLabel { background: rgba(0,0,0,0); border: 0px solid rgba(255,255,255,60); border-radius: 2px; }
        """)

    def enterEvent(self, _):  self._hover = True;  self.update()
    def leaveEvent(self, _):  self._hover = False; self.update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self._hover:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(QColor(230,210,122,220), 2))
            r = self.rect().adjusted(2,2,-2,-2)
            p.drawRoundedRect(r, 3, 3)

class _InfoBoardMenu(QMenu):
    """
    QMenu в стиле инфо-борда:
    настоящий полупрозрачный чёрный фон, металлическая обводка,
    скругление и обычная логика QMenu.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)

        try:
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self.setWindowFlag(Qt.NoDropShadowWindowHint, True)
        except Exception:
            pass

        self.setStyleSheet(POPUP_MENU_STYLE)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect().adjusted(1, 1, -2, -2)

        # Реальная прозрачность, как у инфо-борда.
        p.setBrush(QColor(0, 0, 0, 230))
        p.setPen(QPen(QColor(145, 140, 128, 235), 2))
        p.drawRoundedRect(r, 7, 7)

        p.end()

        super().paintEvent(ev)
# --------------------------- главное окно инвентаря ------------------------------
class InventoryWindow(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        # ---------------- БАЗОВОЕ СОСТОЯНИЕ (безопасные дефолты) ----------------
        self._drag_pos: Optional[QPoint] = None

        self._cells: list[CellWidget] = []
        self._cell_icons: Dict[Tuple[int, int], QLabel] = {}
        self._items: Dict[Tuple[int, int], dict] = {}  # (r,c) -> item(dict)
        self._image_loader: Optional[Callable[[int], Optional[bytes]]] = None

        # контекст класса/пола
        self._current_class = None
        self._prev_class_id: Optional[int] = None
        self._current_gender: Optional[int] = None
        self._has_gender_col_cache: Optional[bool] = None
        self._gender_col_name: Optional[str] = None

        # кэш печатей по InstanceGuid
        self._inv_stamp_by_instance: dict[str, dict] = {}
        # кэш иконок элементов
        self._element_badge_cache: dict[int, QPixmap] = {}


        # фильтр по классу: дефолты, чтобы не ловить AttributeError
        self._class_filter_fn = None
        self._filter_on_add = False

        # --- drag&drop поля (ДОЛЖНЫ быть инициализированы ДО первых событий) ---
        self._drag_active: bool = False
        self._drag_candidate: dict | None = None  # кандидат до старта drag (ЛКМ down)
        self._drag_press_pos: QPoint | None = None  # глобальная точка нажатия
        self._drag_from_rc: tuple[int, int] | None = None
        self._drag_source_label: QLabel | None = None
        self._drag_target_key: str | None = None
        self._drag_floater: QLabel | None = None  # плавающая иконка

        # ---------------- ОКНО / ФОН ----------------
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.CustomizeWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

        self._bg_pm = _load_file_image(INV_BG_PATH)
        self._base_w, self._base_h = (
            (self._bg_pm.width(), self._bg_pm.height()) if self._bg_pm else (600, 400)
        )

        self.board = QLabel(self)
        self.board.setAttribute(Qt.WA_TranslucentBackground, True)
        self.board.setStyleSheet("background: transparent;")
        self.board.setScaledContents(False)
        self._apply_background()

        # hover-крестик
        self._close_overlay = QLabel(self)
        self._close_overlay.setStyleSheet("background: transparent;")
        self._close_overlay.setScaledContents(True)
        self._close_overlay.hide()
        self._close_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._close_hover_pm = _load_file_image(CLOSE_HOVER_PATH) or QPixmap()

        # ---------------- СЛОЙ СЕТКИ ----------------
        self.grid_layer = QWidget(self)
        self.grid_layer.setAttribute(Qt.WA_TranslucentBackground, True)
        self.grid_layer.setStyleSheet("background: transparent;")
        self.grid_layer.setMouseTracking(True)

        # построить и разложить сетку
        self._build_grid()
        self._layout_grid()

        # ---------------- ТЕКСТОВЫЕ ЭЛЕМЕНТЫ ----------------
        # сообщение о заполненности
        self._ensure_capacity_label()
        self._update_capacity_message()

        # счётчик предметов
        self._ensure_counter_label()
        self._layout_counter_label()
        self._update_counter_label()

        # ---------------- ФИЛЬТРЫ СОБЫТИЙ ----------------
        self.board.installEventFilter(self)
        self.installEventFilter(self)
        self.board.setMouseTracking(True)
        self.setMouseTracking(True)

        # хотим получать MouseMove/Release глобально (для DnD)
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)

        self._drag_target_cell: tuple[int, int] | None = None

        # ---------------- СТАРТОВЫЙ КОНТЕКСТ ОТ РОДИТЕЛЯ ----------------
        try:
            p = self.parent()
            # класс
            cur_cls = None
            for name in ("current_class_id", "get_current_class_id", "get_current_class",
                         "player_class", "selected_class_id", "selected_class"):
                v = getattr(p, name, None)
                if callable(v):
                    cur_cls = v()
                elif v is not None:
                    cur_cls = v
                if cur_cls is not None:
                    break
            if cur_cls is None and getattr(p, "class_combo", None):
                data = p.class_combo.currentData()
                cur_cls = data if data is not None else p.class_combo.currentText()
            if cur_cls is not None:
                self.on_player_class_changed(cur_cls)
        except Exception:
            pass

        try:
            # пол
            cur_gender = None
            for name in ("current_gender_id", "get_current_gender_id", "gender_id",
                         "selected_gender_id", "selected_gender"):
                v = getattr(p, name, None)
                if callable(v):
                    cur_gender = v()
                elif v is not None:
                    cur_gender = v
                if cur_gender is not None:
                    break
            if cur_gender is not None:
                self.on_player_gender_changed(cur_gender)
        except Exception:
            pass

    # -------------------- DEBUG LOG HELPERS --------------------
    def _inv_brief(self, item: dict | None) -> str:
        if not isinstance(item, dict):
            return "None"
        gid = get_instance_guid(item) or ""
        eid = item.get("Id") or item.get("Equipment_Id") or item.get("EquipmentId") or ""
        tid = item.get("Type_Id") or item.get("TypeId") or ""
        sid = item.get("Slot_Id") or item.get("SlotId") or ""
        sk = item.get("slot_key") or item.get("SlotKey") or ""
        nm = item.get("Name") or item.get("name") or ""
        try:
            nm = str(nm)
        except Exception:
            nm = ""
        nm = nm.replace("\n", " ").strip()
        if len(nm) > 28:
            nm = nm[:28] + "…"
        return f"id={eid} gid={gid} type={tid} slot_id={sid} sk={sk} name='{nm}'"

    def _inv_log(self, action: str, **fields) -> None:
        seq = _next_seq()
        t = f"{time.perf_counter():.3f}"
        parts = []
        for k, v in fields.items():
            try:
                if isinstance(v, dict):
                    parts.append(f"{k}={{...}}")
                else:
                    parts.append(f"{k}={v}")
            except Exception:
                parts.append(f"{k}=<?>")
        msg = f"{t} #{seq} {action}"
        if parts:
            msg += " | " + " ".join(parts)
        #if DEBUG_INV_STACK:
        #    msg += " | " + _stack_tail()
        #_d(msg)

    def _inv_remove_at(self, rc: tuple[int, int], reason: str) -> dict | None:
        it = (self._items or {}).get(rc)
        self._inv_log("INV_REMOVE", rc=rc, reason=reason, item=self._inv_brief(it), had=bool(it))
        return self._items.pop(rc, None)

    def _inv_clear_icon_at(self, rc: tuple[int, int], reason: str) -> None:
        ico = self._cell_icons.get(rc)
        if ico:
            ico.clear()
            ico.hide()
            self._inv_log("ICON_CLEAR", rc=rc, reason=reason)

    #====================
    #===Подсчёт слотов===
    #====================
    # ===== СЧЁТЧИК ПРЕДМЕТОВ =====
    def _get_counter_cfg(self) -> dict:
        cfg = dict(COUNTER_CFG)
        p = self.parent()
        # поддержка внешнего конфига родителя: inventory_ui_cfg = {"counter": {...}}
        try:
            ext = getattr(p, "inventory_ui_cfg", None)
            if isinstance(ext, dict) and isinstance(ext.get("counter"), dict):
                for k, v in ext["counter"].items():
                    cfg[k] = v
        except Exception:
            pass
        return cfg

    def _ensure_counter_label(self):
        if getattr(self, "counter_label", None) is None:
            self.counter_label = QLabel(self)
            self.counter_label.setAttribute(Qt.WA_TranslucentBackground, True)
            self.counter_label.setWordWrap(False)
            self.counter_label.setIndent(0)
            self.counter_label.setMargin(0)
            self.counter_label.setContentsMargins(0, 0, 0, 0)
            self.counter_label.setStyleSheet("background:transparent;")

    def _layout_counter_label(self):
        self._ensure_counter_label()
        gr = self._grid_rect()
        cfg = self._get_counter_cfg()
        p = self._project(cfg["x"], cfg["y"], cfg["w"] or gr.width(), cfg["h"] or 24)
        self.counter_label.setGeometry(p.x(), p.y(), p.width(), p.height())

        # выравнивание из конфига
        align = str(cfg.get("align", "right")).lower()
        if align == "left":
            self.counter_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        elif align == "center":
            self.counter_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        else:
            self.counter_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._apply_counter_label_style()
        self.counter_label.raise_()

    def _apply_counter_label_style(self):
        cfg = self._get_counter_cfg()
        sx = self._scale() or 1.0
        font_px = max(1, int((cfg.get("font_px") or 16) * sx))

        f = self.counter_label.font()
        f.setPixelSize(font_px)
        self.counter_label.setFont(f)

        # цвет из конфига; НЕ задаём font-size в QSS, чтобы не перебить QFont
        color = cfg.get("color") or "#e6d27a"
        self.counter_label.setStyleSheet(f"color:{color}; background:transparent;")

    def _max_capacity(self) -> int:
        # максимум равен количеству ячеек (устойчиво к смене ROWS/COLS)
        return len(self._cells) if self._cells else ROWS * COLS

    def _update_counter_label(self):
        self._ensure_counter_label()
        used = self._capacity_used()
        total = self._max_capacity()
        self.counter_label.setText(f"{used} / {total}")

    def _capacity_used(self) -> int:
        return sum(1 for it in (self._items or {}).values() if self._is_real_item(it))

    def _update_capacity_indicator(self):
        self._ensure_capacity_label()
        used = self._capacity_used()

        # округляем вниз к шагу 6 (0, 6, 12, ..., 78)
        milestone = (used // 6) * 6
        msg = CAPACITY_MESSAGES.get(milestone)

        if msg is not None:
            self.capacity_label.setText(msg)  # ← здесь «пишется» фраза
        else:
            self.capacity_label.clear()
        self._update_capacity_message()
        self._update_counter_label()

    def _ensure_capacity_label(self):
        if getattr(self, "capacity_label", None) is None:
            self.capacity_label = QLabel(self)
            self.capacity_label.setAttribute(Qt.WA_TranslucentBackground, True)
            self.capacity_label.setWordWrap(True)
            self.capacity_label.setAlignment(Qt.AlignCenter)
            self.capacity_label.setStyleSheet(
                "color:#e6d27a; font-weight:600; background:transparent; padding:2px;")

    def _capacity_message_for(self, filled: int) -> str:
        keys = sorted(CAPACITY_MESSAGES.keys())
        k = 0
        for t in keys:
            if filled >= t:
                k = t
            else:
                break
        return CAPACITY_MESSAGES.get(k, "")

    def _update_capacity_message(self) -> None:
        self._ensure_capacity_label()
        msg = self._capacity_message_for(self._capacity_used())
        self.capacity_label.setText(msg)

    # -------------------- sticky position (save/restore) --------------------
    def _remember_window_pos(self) -> None:
        """Запоминаем текущую позицию окна (в RAM: родитель + модульная переменная)."""
        global _INV_LAST_POS
        pt = QPoint(self.pos())

        _INV_LAST_POS = QPoint(pt)

        p = self.parent()
        if p is not None:
            try:
                setattr(p, "_inventory_last_pos", QPoint(pt))
            except Exception:
                pass

    def _load_window_pos(self) -> Optional[QPoint]:
        """Берём сохранённую позицию (сначала у родителя, потом из глобалки)."""
        p = self.parent()
        v = getattr(p, "_inventory_last_pos", None) if p else None
        if isinstance(v, QPoint):
            return QPoint(v)

        global _INV_LAST_POS
        if isinstance(_INV_LAST_POS, QPoint):
            return QPoint(_INV_LAST_POS)

        return None

    def _clamp_window_pos_to_screen(self, pt: QPoint) -> QPoint:
        """Не даём окну улететь за пределы экрана (берём availableGeometry)."""
        pad = 6

        sc = None
        try:
            sc = QApplication.screenAt(pt)
        except Exception:
            sc = None

        if sc is None:
            sc = self.screen() or QApplication.primaryScreen()

        geo = sc.availableGeometry() if sc else QRect(0, 0, 1920, 1080)

        min_x = geo.left() + pad
        min_y = geo.top() + pad
        max_x = geo.right() - self.width() - pad
        max_y = geo.bottom() - self.height() - pad

        if max_x < min_x:
            max_x = min_x
        if max_y < min_y:
            max_y = min_y

        x = max(min_x, min(int(pt.x()), max_x))
        y = max(min_y, min(int(pt.y()), max_y))
        return QPoint(x, y)

    def _restore_window_pos_if_any(self) -> bool:
        """Пытаемся восстановить позицию; True если применили."""
        pt = self._load_window_pos()
        if not pt:
            return False
        self.move(self._clamp_window_pos_to_screen(pt))
        return True

    # ---------------------------- API / внешние вызовы ---------------------------
    def set_image_loader(self, loader: Callable[[int], Optional[bytes]]):
        self._image_loader = loader

    def add_item(self, item: dict) -> bool:
        self._inv_log(
            "ADD_REQ",
            item=self._inv_brief(item),
            used=self._capacity_used(),
            total=self._max_capacity(),
            filter_on_add=self._filter_on_add,
            cls=self._current_class_value(),
            gender=self._current_gender,
        )

        if self._filter_on_add:
            ok_pred = True
            ok_rules = True

            if callable(getattr(self, "_class_filter_fn", None)):
                try:
                    ok_pred = bool(self._class_filter_fn(item, self._current_class_value()))
                except TypeError:
                    ok_pred = bool(self._class_filter_fn(item))
                except Exception:
                    ok_pred = True  # не валим добавление из-за ошибки предиката

            try:
                ok_rules = bool(self._is_item_allowed_for_class(item, self._current_class_value()))
            except Exception:
                ok_rules = True

            ok = bool(ok_pred and ok_rules)
            if not ok:
                self._inv_log(
                    "ADD_BLOCKED",
                    item=self._inv_brief(item),
                    ok_pred=ok_pred,
                    ok_rules=ok_rules,
                    cls=self._current_class_value(),
                    gender=self._current_gender,
                )
                return False

        pos = self._find_first_empty()
        if pos is None:
            self._inv_log("ADD_FAIL_NO_SPACE", item=self._inv_brief(item), used=self._capacity_used())
            return False

        self._place_item_into_cell(pos, item)
        self._update_capacity_message()
        self._update_capacity_indicator()

        self._inv_log("ADD_OK", pos=pos, item=self._inv_brief(item), used=self._capacity_used())
        self._remember_window_pos()
        return True

    # ---- совместимость со старым кодом: фильтр по классу ------------------------
    def set_class_filter(self, predicate, *, filter_on_add: bool = False) -> None:
        """
        predicate(item, cls_ctx) -> bool|None
        filter_on_add=True — отбрасывать неподходящее сразу при add_item().
        """
        self._class_filter_fn = predicate
        self._class_filter = predicate
        self._filter_on_add = bool(filter_on_add)

    def remove_instance(self, inst_guid: str) -> bool:
        self._inv_log("REMOVE_INSTANCE_REQ", inst=inst_guid, used=self._capacity_used())

        if not inst_guid:
            return False

        removed = False
        removed_rc = None
        removed_item = None

        for pos, it in list(self._items.items()):
            if get_instance_guid(it) == inst_guid:
                removed_item = it
                removed_rc = pos
                self._items.pop(pos, None)
                icon = self._cell_icons.get(pos)
                if icon:
                    icon.clear()
                    icon.hide()
                removed = True
                break

        self._inv_stamp_by_instance.pop(inst_guid, None)

        self._inv_log(
            "REMOVE_INSTANCE_DONE",
            inst=inst_guid,
            removed=removed,
            rc=removed_rc,
            item=self._inv_brief(removed_item),
            used=self._capacity_used(),
        )

        if removed:
            self._reflow_after_changes()
        self._update_capacity_indicator()
        return removed

    def open_right_of(self, owner: QWidget | None, *, margin: int = 12, v_align: str = "center"):
        self._apply_background()

        # ✅ если уже есть сохранённая позиция — открываем там и НЕ прыгаем
        if self._restore_window_pos_if_any():
            self.show()
            self.raise_()
            self._update_capacity_message()
            return

        # --- старое поведение (фолбэк, если позиция ещё не сохранена) ---
        if owner and owner.isVisible():
            og = owner.frameGeometry()
            screen_geo = owner.window().screen().availableGeometry()
        else:
            og = self.frameGeometry()
            screen_geo = (self.screen().availableGeometry()
                          if self.screen() else QApplication.primaryScreen().availableGeometry())

        x = og.right() + margin
        right_bound = screen_geo.right() - 6
        if x + self.width() > right_bound:
            x = right_bound - self.width()

        if v_align == "top":
            y = og.top()
        elif v_align == "bottom":
            y = og.bottom() - self.height()
        else:
            y = og.center().y() - self.height() // 2

        y = max(screen_geo.top() + 6, min(y, screen_geo.bottom() - self.height() - 6))
        self.move(x, y)

        # ✅ запомнили вычисленную позицию, чтобы дальше окно липло
        self._remember_window_pos()

        self.show()
        self.raise_()
        self._update_capacity_message()

    # --------- печати (локальный кэш по InstanceGuid) ---------------------------
    def inv_set_stamp_for_instance(self, inst: str, stamp_id: int, color_id: int,
                                   bonuses: list[str], name: str,
                                   header_hex: str | None = None,
                                   header_icon_id: int | None = None) -> None:
        if not inst: return
        self._inv_stamp_by_instance[inst] = {
            "Id": int(stamp_id or 0),
            "ColorId": int(color_id or 0),
            "Name": name or "",
            "Bonuses": list(bonuses or []),
            "HeaderColorHex": header_hex,
            "HeaderIconImageId": header_icon_id,
            "icon_id": header_icon_id,
            "BonusLines": list(bonuses or []),
            "Effects": list(bonuses or []),
            "name": name or "",
        }

    def inv_clear_stamp_for_instance(self, inst: str) -> None:
        if not inst: return
        self._inv_stamp_by_instance.pop(inst, None)

    def inv_get_stamp_for_instance(self, inst: str) -> Optional[dict]:
        if not inst:
            return None
        if inst in self._inv_stamp_by_instance:
            return deep_clone(self._inv_stamp_by_instance[inst])
        p = self.parent()
        if p and hasattr(p, "_stamp_payload_for_instance"):
            try:
                sp = p._stamp_payload_for_instance(inst)
                if sp:
                    self._inv_stamp_by_instance[inst] = deep_clone(sp)
                    return deep_clone(sp)
            except Exception:
                pass
        return None

    # ---------------------- смена класса / пола (ВАЖНО) --------------------------
    def on_player_class_changed(self, new_class: object) -> list[dict]:
        prev_id, _ = self._resolve_class_ctx(getattr(self, "_current_class", None))
        self._prev_class_id = prev_id
        self._current_class = new_class
        removed = self._purge_items_not_for_class(new_class)
        self._reflow_after_changes()
        return removed

    def on_player_gender_changed(self, new_gender: object) -> list[dict]:
        """
        Смена пола — фильтрация.
        ОЖИДАЕТСЯ: 1 = муж, 2 = жен.
        """
        val = new_gender
        try:
            if hasattr(val, "value"):
                val = val.value()
        except Exception:
            pass
        try:
            if hasattr(val, "toInt"):
                v = val.toInt()
                val = v[0] if isinstance(v, (tuple, list)) and v else v
        except Exception:
            pass

        try:
            self._current_gender = int(val) if val is not None else None
        except Exception:
            self._current_gender = None

        removed = self._purge_items_not_for_class(self._current_class_value())
        self._reflow_after_changes()
        return removed

    # ---------------------- фильтрация и правила ---------------------------------
    def _current_class_value(self):
        return getattr(self, "_current_class", None)

    def _effective_class_ids(self, cls_id: int) -> Set[int]:
        base_chain = set(self._class_lineage_ids(int(cls_id)))

        # donor map: если наш класс ИЛИ его база в receivers -> добавляем donor
        for donor, receivers in DONOR_MAP.items():
            if any(cid in receivers for cid in base_chain):
                base_chain.add(int(donor))

        return base_chain

    def _db_conn(self):
        p = self.parent()
        try:
            return p.data.conn if (p and hasattr(p, "data") and p.data and getattr(p.data, "conn", None)) else None
        except Exception:
            return None

    def _class_lineage_ids(self, class_id: int) -> Set[int]:
        """
        {class_id, base_id, base_of_base, ...} пока Base_Id не NULL.
        """
        conn = self._db_conn()
        if not conn:
            return {int(class_id)}

        out: set[int] = set()
        seen: set[int] = set()
        cur = int(class_id)

        while cur and cur not in seen:
            out.add(cur)
            seen.add(cur)
            row = conn.execute("SELECT Base_Id FROM Class WHERE Id=?", (cur,)).fetchone()
            base = None
            try:
                base = row["Base_Id"] if (row and hasattr(row, "keys") and "Base_Id" in row.keys()) else (
                    row[0] if row else None)
            except Exception:
                base = None
            if base is None:
                break
            try:
                cur = int(base)
            except Exception:
                break

        return out

    def _class_allow_extra_weapon_ctx(self, cls_ctx: object) -> bool:
        """
        AllowExtraWeapon с учётом наследования Base_Id:
        если у класса NULL -> берём у Base_Id и т.д.
        """
        cls_id, _ = self._resolve_class_ctx(cls_ctx)
        if cls_id is None:
            return False

        conn = self._db_conn()
        if not conn:
            return False

        seen: set[int] = set()
        cur = int(cls_id)
        while cur and cur not in seen:
            seen.add(cur)
            row = conn.execute("SELECT AllowExtraWeapon, Base_Id FROM Class WHERE Id=?", (cur,)).fetchone()
            if not row:
                return False

            try:
                allow = row["AllowExtraWeapon"] if hasattr(row, "keys") else row[0]
                base = row["Base_Id"] if hasattr(row, "keys") else row[1]
            except Exception:
                try:
                    allow, base = row[0], row[1]
                except Exception:
                    return False

            if allow is not None:
                try:
                    return int(allow) == 1
                except Exception:
                    return False

            if base is None:
                break
            try:
                cur = int(base)
            except Exception:
                break

        return False

    def _resolve_class_ctx(self, new_class: object) -> tuple[Optional[int], Optional[str]]:
        cls_id: Optional[int] = None
        cls_name: Optional[str] = None
        p = self.parent()
        classes = getattr(p, "_classes", []) if p else []
        if isinstance(new_class, int):
            cls_id = int(new_class)
            try:
                cls_name = next((name for cid, name, _ in classes if int(cid) == cls_id), None)
                if cls_name: cls_name = str(cls_name).strip().lower()
            except Exception:
                pass
        else:
            try:
                cls_name = str(new_class).strip().lower()
            except Exception:
                cls_name = None
            if classes and cls_name:
                try:
                    cls_id = next((int(cid) for cid, name, _ in classes if str(name).strip().lower() == cls_name), None)
                except Exception:
                    pass
        return cls_id, cls_name

    def _class_name_for_ctx(self, cls_ctx) -> Optional[str]:
        if isinstance(cls_ctx, str):
            return cls_ctx
        p = self.parent()
        if p:
            try:
                if getattr(p, "class_combo", None):
                    for cid, cname, _ in getattr(p, "_classes", []):
                        if int(cid) == int(cls_ctx):
                            return cname
                    return p.class_combo.currentText() or None
            except Exception:
                pass
            try:
                for cid, cname, _ in getattr(p, "_classes", []):
                    if int(cid) == int(cls_ctx):
                        return cname
            except Exception:
                pass
        return None

    def _db_has_col(self, table: str, col: str) -> bool:
        try:
            p = self.parent()
            conn = p.data.conn if p and hasattr(p, "data") and p.data and p.data.conn else None
            if not conn:
                return False
            target = str(col).lower()
            for r in conn.execute(f"PRAGMA table_info({table})"):
                try:
                    if str(r[1]).lower() == target:
                        return True
                except Exception:
                    pass
            return False
        except Exception:
            return False

    def _db_gender_id_for_equip(self, equip_id: int) -> Optional[int]:
        try:
            p = self.parent()
            conn = p.data.conn if p and hasattr(p, "data") and p.data and p.data.conn else None
            if conn is None:
                return None
            if self._gender_col_name is None:
                for cname in ("Gender_Id", "Gender_ID", "GenderId", "gender_id"):
                    if self._db_has_col("Equipment", cname):
                        self._gender_col_name = cname
                        break
                self._has_gender_col_cache = bool(self._gender_col_name)
            if not self._has_gender_col_cache:
                return None
            col = self._gender_col_name
            row = conn.execute(f"SELECT {col} FROM Equipment WHERE Id=? LIMIT 1", (int(equip_id),)).fetchone()
            if not row:
                return None
            gid = None
            try:
                if hasattr(row, "keys") and col in row.keys():
                    gid = row[col]
                else:
                    gid = row[0]
            except Exception:
                gid = None
            return int(gid) if gid is not None else None
        except Exception:
            return None

    def _allowed_ids_for_slot_class(self, slot_id: int, cls_id: int) -> Optional[Set[int]]:
        if not hasattr(self, "_allow_cache_by_slot_class"):
            self._allow_cache_by_slot_class: dict[tuple[int, int], Optional[set[int]]] = {}
        key = (int(slot_id), int(cls_id))
        if key in self._allow_cache_by_slot_class:
            return self._allow_cache_by_slot_class[key]
        ids: Optional[set[int]] = None
        p = self.parent()
        try:
            if p and hasattr(p, "data") and hasattr(p.data, "list_equipment_for_slot"):
                rows = p.data.list_equipment_for_slot(int(slot_id), int(cls_id))
                if rows is None:
                    ids = None
                else:
                    tmp: set[int] = set()
                    for r in rows:
                        rid = (r.get("Id") if isinstance(r, dict) else None) or getattr(r, "Id", None)
                        if rid is not None:
                            tmp.add(int(rid))
                    ids = tmp
        except Exception:
            ids = None
        self._allow_cache_by_slot_class[key] = ids
        return ids

    def _allowed_ids_for_slot_with_inheritance(self, slot_id: int, class_ids: Set[int]) -> Optional[Set[int]]:
        union: Set[int] = set()
        have_data = False
        for cid in class_ids:
            s = self._allowed_ids_for_slot_class(int(slot_id), int(cid))
            if s is not None:
                have_data = True
                union |= set(s)
        return union if have_data else None

    def _db_allows_item_for_class_ids(self, equip_id: int, class_ids: Set[int]) -> Optional[bool]:
        p = self.parent()
        conn = p.data.conn if p and hasattr(p, "data") and p.data and p.data.conn else None
        if not conn:
            return None
        total = conn.execute("SELECT COUNT(1) FROM EquipmentCondition WHERE Equipment_Id=?", (int(equip_id),)).fetchone()[0]
        if int(total) == 0:
            return True
        if class_ids:
            ph = ",".join("?" * len(class_ids))
            row = conn.execute(
                f"SELECT 1 FROM EquipmentCondition WHERE Equipment_Id=? AND (Class_Id IS NULL OR Class_Id IN ({ph})) LIMIT 1",
                (int(equip_id), *sorted(int(x) for x in class_ids))
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM EquipmentCondition WHERE Equipment_Id=? AND Class_Id IS NULL LIMIT 1",
                (int(equip_id),)
            ).fetchone()
        return bool(row)

    def _is_item_allowed_for_class(self, item: dict, new_class: object) -> bool:
        """
        Проверяет предмет на допустимость по текущему полу и классу.

        ВАЖНО:
        gender проверяется всегда, даже если класс не удалось распознать.
        Раньше при cls_id is None функция возвращала True раньше проверки пола.
        """
        if not isinstance(item, dict):
            return True

        equip_id = None
        slot_id = None

        try:
            for k in ("Id", "Equipment_Id", "EquipmentId", "Equip_Id"):
                if item.get(k) not in (None, ""):
                    equip_id = int(item.get(k))
                    break
        except Exception:
            equip_id = None

        # ---------- gender check ----------
        gen_id = self._current_gender

        if gen_id is not None:
            item_gender = None

            for k in ("Gender_Id", "Gender_ID", "GenderId", "gender_id"):
                if item.get(k) not in (None, ""):
                    try:
                        item_gender = int(item.get(k))
                    except Exception:
                        item_gender = None
                    break

            if item_gender is None and equip_id is not None:
                db_gid = self._db_gender_id_for_equip(int(equip_id))
                if db_gid is not None:
                    try:
                        item_gender = int(db_gid)
                    except Exception:
                        item_gender = None

            # 0 / NULL = универсальный предмет.
            if item_gender is not None and int(item_gender) > 0 and int(item_gender) != int(gen_id):
                return False

        # ---------- class check ----------
        cls_id, _ = self._resolve_class_ctx(new_class)
        if cls_id is None:
            return True

        eff_ids = self._effective_class_ids(int(cls_id))

        try:
            slot_id = self._slot_id_for_item(item)
        except Exception:
            slot_id = None

        if slot_id is not None and equip_id is not None:
            allowed = self._allowed_ids_for_slot_with_inheritance(int(slot_id), eff_ids)
            if allowed is not None and int(equip_id) not in allowed:
                return False

        try:
            if equip_id is not None:
                ec = self._db_allows_item_for_class_ids(int(equip_id), eff_ids)
                if ec is False:
                    return False
        except Exception:
            pass

        return True

    def _purge_items_not_for_class(self, new_class: object) -> list[dict]:
        self._inv_log(
            "PURGE_BEGIN",
            new_class=new_class,
            gender=self._current_gender,
            used=self._capacity_used(),
        )

        removed: list[dict] = []
        removed_count = 0

        for pos, it in list(self._items.items()):
            if not it:
                continue
            allowed = True
            try:
                allowed = self._is_item_allowed_for_class(it, new_class)
            except Exception:
                allowed = True

            if not allowed:
                removed.append(deep_clone(it))
                removed_count += 1

                self._inv_log(
                    "PURGE_REMOVE",
                    rc=pos,
                    item=self._inv_brief(it),
                    new_class=new_class,
                    gender=self._current_gender,
                )

                self._items.pop(pos, None)
                ico = self._cell_icons.get(pos)
                if ico:
                    ico.clear()
                    ico.hide()

                try:
                    inst = get_instance_guid(it)
                    if inst:
                        self._inv_stamp_by_instance.pop(inst, None)
                except Exception:
                    pass

        self._update_capacity_indicator()

        self._inv_log(
            "PURGE_END",
            removed=removed_count,
            used=self._capacity_used(),
        )
        return removed

    # --------------------------- геометрия/вёрстка --------------------------------
    def _apply_background(self):
        if not self._bg_pm:
            self.resize(self._base_w, self._base_h)
            self.board.setGeometry(self.rect())
            self.board.setPixmap(QPixmap())
            return
        self.resize(self._bg_pm.width(), self._bg_pm.height())
        self.setFixedSize(self.size())
        self.board.setGeometry(0, 0, self.width(), self.height())
        self.board.setPixmap(self._bg_pm)

    def _img_rect(self) -> QRect: return self.board.geometry()
    def _scale(self) -> float:
        pm = self.board.pixmap()
        return (pm.width() / self._base_w) if (pm and self._base_w) else 1.0
    def _project(self, x:int,y:int,w:int=0,h:int=0) -> QRect:
        sx = self._scale()
        ir = self._img_rect()
        return QRect(int(ir.x()+x*sx), int(ir.y()+y*sx), int(w*sx), int(h*sx))
    def _close_rect(self) -> QRect:
        x,y = CLOSE_POS_DESIGN; s = CLOSE_SIZE_PX
        return self._project(x + CLOSE_PAD_PX, y + CLOSE_PAD_PX, s, s)
    def _grid_rect(self) -> QRect:
        gx, gy = GRID_ORIGIN_DESIGN
        total_w = COLS*CELL + (COLS-1)*GAP
        total_h = ROWS*CELL + (ROWS-1)*GAP
        return self._project(gx, gy, total_w, total_h)

    def _build_grid(self):
        for r in range(ROWS):
            for c in range(COLS):
                cell = CellWidget(r, c, parent=self.grid_layer)
                cell.show()
                self._cells.append(cell)

    def _layout_grid(self):
        grid_rect = self._grid_rect()
        self.grid_layer.setGeometry(grid_rect)
        sx = self._scale()
        cw = int(CELL * sx)
        ch = int(CELL * sx)
        gap = int(GAP * sx)
        for i, cell in enumerate(self._cells):
            r = i // COLS; c = i % COLS
            x = c * (cw + gap)
            y = r * (ch + gap)
            cell.setGeometry(x, y, cw, ch)

        for (r, c), icon in list(self._cell_icons.items()):
            rect = self._icon_rect_for_cell(self._cell_at(r, c))
            icon.setGeometry(rect)

        self._layout_status_label()
        self._layout_counter_label()

    def _layout_status_label(self):
        self._ensure_capacity_label()
        gr = self._grid_rect()
        p = self._project(48, 822, gr.width(), 24)
        self.capacity_label.setGeometry(p.x(), p.y(), p.width(), p.height())
        self._layout_counter_label()

        # фиксируем левую кромку
        self.capacity_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.capacity_label.setIndent(0)  # убираем indent
        self.capacity_label.setMargin(0)  # убираем margin
        self.capacity_label.setContentsMargins(0, 0, 0, 0)  # убираем content-margins

        # если в стилях есть padding, уберём его слева
        st = self.capacity_label.styleSheet()
        self.capacity_label.setStyleSheet(st + "; padding-left:0px;")

        self._apply_capacity_label_style()
        self.capacity_label.raise_()

    def _apply_capacity_label_style(self):
        sx = self._scale() or 1.0
        font_px = max(1, int(16 * sx))  # меняй 16 на базовый размер

        # ← ключ: задаём размер напрямую через QFont (в пикселях)
        f = self.capacity_label.font()
        f.setPixelSize(font_px)
        f.setWeight(QFont.Weight.DemiBold)  # DemiBold ≈ 600; можно убрать, если не нужно
        self.capacity_label.setFont(f)

        # цвет/фон оставим через QSS, БЕЗ font-size, чтобы не перебивать QFont
        self.capacity_label.setStyleSheet(
            "color:#e6d27a; background:transparent; padding:2px;"
        )

    def _cell_at(self, r:int, c:int) -> CellWidget:
        return self._cells[r * COLS + c]

    def _icon_rect_for_cell(self, cell: QLabel) -> QRect:
        r = cell.geometry()
        w = int(r.width() * ICON_SCALE)
        h = int(r.height() * ICON_SCALE)
        x = r.x() + (r.width() - w)//2; y = r.y() + (r.height() - h)//2
        return QRect(x, y, w, h)

    def _find_first_empty(self) -> Optional[Tuple[int, int]]:
        for r in range(ROWS):
            for c in range(COLS):
                rc = (r, c)
                it = (self._items or {}).get(rc)

                if it is None:
                    return rc

                # если в клетке лежит заглушка — вычищаем и считаем клетку свободной
                if self._is_stub_item(it):
                    self._purge_stub_at(rc, "find_first_empty")
                    return rc
        return None

    # --------------------- slot / item helpers -----------------------------------
    def _slot_id_for_item(self, item: dict) -> Optional[int]:
        for k in ("Slot_Id", "SlotId", "EquipmentSlot_Id", "Equipment_Slot_Id"):
            try:
                if item.get(k) is not None:
                    return int(item.get(k))
            except Exception:
                pass
        equip_id = None
        for k in ("Id", "Equipment_Id", "EquipmentId"):
            try:
                if item.get(k) is not None:
                    equip_id = int(item.get(k))
                    break
            except Exception:
                pass
        try:
            p = self.parent()
            if equip_id and p and hasattr(p, "data") and p.data and p.data.conn:
                row = p.data.conn.execute(
                    "SELECT Slot_Id FROM Equipment WHERE Id=? LIMIT 1", (equip_id,)
                ).fetchone()
                if row and row[0] is not None:
                    return int(row[0])
        except Exception:
            pass
        return None

    def _get_item_slot_key(self, item: dict) -> Optional[str]:
        if not isinstance(item, dict):
            return None

        sk = item.get("slot_key") or item.get("SlotKey")
        if sk:
            sk = str(sk).strip()
            # ring оставляем ring (а ring1/ring2 решаем при экипировке)
            if sk.lower() == "ring":
                return "ring"
            return sk

        # если очень хочешь — можно 1 раз спросить у родителя,
        # но лучше сделать обязательным slot_key в item и тут вернуть None
        p = self.parent()
        fn = getattr(p, "get_slot_key_for_item", None) if p else None
        if callable(fn):
            try:
                sk = fn(item)
                return str(sk).strip() if sk else None
            except Exception:
                return None

        return None

    def _type_id_for_item(self, item: dict) -> Optional[int]:
        try:
            for k in ("Type_Id", "TypeId"):
                if item.get(k) is not None:
                    return int(item.get(k))
        except Exception:
            pass
        try:
            equip_id = None
            for k in ("Id", "Equipment_Id", "EquipmentId"):
                if item.get(k) is not None:
                    equip_id = int(item.get(k))
                    break
            p = self.parent()
            if equip_id and p and getattr(getattr(p, "data", None), "conn", None):
                row = p.data.conn.execute("SELECT Type_Id FROM Equipment WHERE Id=? LIMIT 1", (equip_id,)).fetchone()
                if row and row[0] is not None:
                    return int(row[0])
        except Exception:
            pass
        return None

    def _is_single_hand_weapon(self, item: dict) -> bool:
        # 1) если уже лежит в item
        v = item.get("IsSingleHandWeapon")
        if v is not None:
            try:
                return int(v) == 1
            except Exception:
                return False

        # 2) иначе берём из EquipmentType по Type_Id
        conn = self._db_conn()
        if not conn:
            return False

        tid = self._type_id_for_item(item)
        if tid is None:
            return False

        try:
            row = conn.execute("SELECT IsSingleHandWeapon FROM EquipmentType WHERE Id=? LIMIT 1",
                               (int(tid),)).fetchone()
            if not row:
                return False
            val = row["IsSingleHandWeapon"] if hasattr(row, "keys") else row[0]
            if val is None:
                return False
            return int(val) == 1
        except Exception:
            return False

    # ---------------------- тултип предмета --------------------------------------
    def _stamp_for_item(self, item: dict) -> dict | None:
        if not isinstance(item, dict):
            return None
        if item.get("Stamp") is not None:
            return deep_clone(item["Stamp"])
        inst = get_instance_guid(item)
        if not inst:
            return None
        if inst in self._inv_stamp_by_instance:
            return deep_clone(self._inv_stamp_by_instance[inst])
        p = self.parent()
        if p and hasattr(p, "_stamp_payload_for_instance"):
            try:
                sp = p._stamp_payload_for_instance(inst)
                if sp:
                    self._inv_stamp_by_instance[inst] = deep_clone(sp)
                    return deep_clone(sp)
            except Exception:
                pass
        return None

    def _show_item_tooltip(self, icon: QLabel, item: dict):
        p = self.parent()
        if not p or not hasattr(p, "equip_info"):
            return

        ei = getattr(p, "equip_info", None)
        if ei is None:
            return

        try:
            equip_id = int(item.get("Id") or 0)
        except Exception:
            equip_id = 0

        bonus_lines = []
        try:
            if equip_id and hasattr(p, "data") and p.data and p.data.conn:
                bonus_lines = _render_bonus_lines(p.data.conn, equip_id) or []
        except Exception:
            pass

        stamp_payload = self._stamp_for_item(item)

        # ВАЖНО:
        # Якоримся не к маленькой иконке, а к полной ячейке инвентаря.
        # Иначе на Linux/при масштабировании анкета может попасть поверх предмета.
        anchor_widget = icon

        try:
            r = icon.property("inv_row")
            c = icon.property("inv_col")
            if isinstance(r, int) and isinstance(c, int):
                cell = self._cell_at(int(r), int(c))
                if cell is not None:
                    anchor_widget = cell
        except Exception:
            anchor_widget = icon

        try:
            anchor_rect = QRect(
                anchor_widget.mapToGlobal(anchor_widget.rect().topLeft()),
                anchor_widget.rect().size(),
            )
        except Exception:
            anchor_rect = QRect(
                icon.mapToGlobal(icon.rect().topLeft()),
                icon.rect().size(),
            )

        # Чуть расширяем безопасную область вокруг предмета,
        # чтобы алгоритм позиционирования точно не считал пересечение допустимым.
        safe_rect = QRect(anchor_rect)
        try:
            center = safe_rect.center()
            safe_rect.setWidth(max(60, int(safe_rect.width())))
            safe_rect.setHeight(max(60, int(safe_rect.height())))
            safe_rect.moveCenter(center)
        except Exception:
            pass

        gp = safe_rect.center()

        def _etype_name_by_id(tid: int) -> str:
            try:
                row = p.data.conn.execute(
                    "SELECT Name FROM EquipmentType WHERE Id=? LIMIT 1",
                    (int(tid),),
                ).fetchone()
                return row["Name"] if row and row["Name"] else "—"
            except Exception:
                return "—"

        # Пробуем явно собрать payload карт для тултипа.
        cards_payload = None
        slot_key = None

        try:
            slot_key = (item.get("slot_key") or item.get("SlotKey") or "").strip() or None
        except Exception:
            slot_key = None

        try:
            fam = self._item_slot_family(item) or ""
        except Exception:
            fam = ""

        try:
            kind = "weapon" if (
                    fam == "weapon"
                    or (fam == "offhand" and self._is_single_hand_weapon(item))
            ) else "equipment"
        except Exception:
            kind = "equipment"

        try:
            cw = getattr(p, "cards_window", None)
            if cw is not None and hasattr(cw, "build_tooltip_cards_payload_for_item"):
                cards_payload = cw.build_tooltip_cards_payload_for_item(
                    item,
                    kind=kind,
                    slot_key=slot_key,
                )
        except Exception:
            cards_payload = None

        # Если до этого анкета была показана от другого anchor — закрываем старую.
        try:
            last = getattr(self, "_last_tip_anchor", None)
            if last is not None and last is not icon:
                try:
                    ei.end_hover(last)
                except Exception:
                    pass
        except Exception:
            pass

        self._last_tip_anchor = icon

        # Контекст оставляем InventoryWindow, чтобы tooltip брал правильные данные.
        # Но transientParent на Linux не ставим: из-за него tooltip может центрироваться
        # относительно окна инвентаря вместо привязки к ячейке предмета.
        try:
            ei._ctx_root = self

            platform_name = str(QApplication.platformName()).lower()

            if "windows" in platform_name:
                host_handle = self.windowHandle()
                if host_handle is None:
                    self.winId()
                    host_handle = self.windowHandle()

                ei.winId()
                tip_handle = ei.windowHandle()

                if tip_handle is not None and host_handle is not None:
                    tip_handle.setTransientParent(host_handle)
            else:
                ei.winId()
                tip_handle = ei.windowHandle()
                if tip_handle is not None:
                    tip_handle.setTransientParent(None)
        except Exception:
            pass

        ei.show_for_item(
            item=item,
            image_loader=(p.data.get_image_bytes if hasattr(p, "data") else None),
            global_pos=gp,
            slot_key=slot_key,
            type_name=None,
            type_name_lookup=_etype_name_by_id,
            item_class=item.get("ItemClass") if isinstance(item, dict) else None,
            cards=cards_payload,
            bonus_lines=bonus_lines,
            stamp=stamp_payload,
            anchor_rect_global=safe_rect,
        )

        # Дополнительное поднятие именно для top-level inventory window.
        try:
            ei.show()
            ei.raise_()
            ei.update()
        except Exception:
            pass

    # --------------------- размещение / отрисовка --------------------------------
    def _activate_inv_icon(self, obj: QLabel, r: int, c: int) -> None:
        cell = None
        try:
            cell = self._cell_at(r, c)
        except Exception:
            cell = None

        cur_item = obj.property("inv_item_dict")
        if not isinstance(cur_item, dict):
            self._inv_log("EQUIP_LMB_ABORT", rc=(r, c), reason="no_item_dict")
            return

        self._inv_log("EQUIP_LMB_REQ", rc=(r, c), item=self._inv_brief(cur_item))

        # подходит ли по классу/полу
        if not self._is_item_allowed_for_class(cur_item, self._current_class_value()):
            self._inv_log(
                "EQUIP_LMB_BLOCKED",
                rc=(r, c),
                item=self._inv_brief(cur_item),
                cls=self._current_class_value(),
                gender=self._current_gender,
            )
            if cell:
                old = cell.styleSheet()
                cell.setStyleSheet(old + "\nborder:2px solid rgba(255,80,80,220); border-radius:3px;")
                QTimer.singleShot(220, lambda: cell.setStyleSheet(old))
            return

        raw_slot_key = self._get_item_slot_key(cur_item)
        if not raw_slot_key:
            self._inv_log("EQUIP_LMB_ABORT", rc=(r, c), reason="no_slot_key", item=self._inv_brief(cur_item))
            return

        slot_key = self._normalize_key_for_parent(raw_slot_key)

        parent = self.parent()
        equipped_before = None
        try:
            if parent and hasattr(parent, "_selected_items") and isinstance(parent._selected_items, dict):
                equipped_before = parent._selected_items.get(slot_key)
                equipped_before = self._as_real_or_none(equipped_before)

        except Exception:
            equipped_before = None

        self._inv_log(
            "EQUIP_LMB_BEFORE_PARENT",
            rc=(r, c),
            slot=slot_key,
            new=self._inv_brief(cur_item),
            prev=self._inv_brief(equipped_before),
        )

        ok = self._equip_via_parent(slot_key, cur_item, equipped_before, prefer_rc=(int(r), int(c)))
        self._inv_log("EQUIP_LMB_PARENT_RET", rc=(r, c), slot=slot_key, ok=ok)

        if not ok:
            return

        rc = (int(r), int(c))
        removed_by_rc = self._inv_remove_source_cell_safely(rc, cur_item, "equip_lmb_to_parent")

        if equipped_before:
            back = deep_clone(equipped_before)

            if removed_by_rc:
                self._place_item_into_cell(rc, back)
            else:
                # parent уже мог положить prev в src-клетку (swap). Не возвращаем второй раз.
                now_in_rc = (self._items or {}).get(rc)
                same = False
                try:
                    if isinstance(now_in_rc, dict) and isinstance(back, dict):
                        same = self._item_identity_key(now_in_rc) == self._item_identity_key(back)
                except Exception:
                    same = False

                if not same:
                    self._return_items_to_inventory([back], prefer_rc=None)
                else:
                    self._inv_log("EQUIP_SKIP_RETURN_PREV_ALREADY_IN_SRC", rc=rc, prev=self._inv_brief(back))

        else:
            if removed_by_rc:
                obj.clear()
                obj.hide()
                self._inv_log("EQUIP_LMB_SRC_ICON_HIDE", rc=(r, c))

        if parent and hasattr(parent, "equip_info"):
            try:
                parent.equip_info.end_hover(obj)
            except Exception:
                pass

        self._update_capacity_message()
        self._update_capacity_indicator()

        self._inv_log("EQUIP_LMB_DONE", rc=(r, c), slot=slot_key, used=self._capacity_used())

    # ------------------- Element badge helpers -------------------
    def _element_id_for_item(self, item: dict) -> Optional[int]:
        if not isinstance(item, dict):
            return None
        v = item.get("Element_Id")
        if v is not None:
            try:
                return int(v)
            except Exception:
                pass
        return None

    def _element_badge_image_id_for_item(self, item: dict | None) -> Optional[int]:
        """
        Достаёт id картинки бейджа элемента (12x16, с прозрачностью).

        Логика:
          - если у item уже есть ToolTipImage_Id -> используем его
          - иначе берём Element_Id и через CardType находим ToolTipImage_Id (как в main)
          - если Element_Id нет, пробуем CardType_Id / TypeId / Id как fallback
        """
        if not isinstance(item, dict):
            return None

        def _toi(v, d=0):
            try:
                return int(v)
            except Exception:
                return d

        # 0) если item уже содержит ToolTipImage_Id — сразу берём
        direct = _toi(
            item.get("ToolTipImage_Id"),
            0,
        )
        if direct > 0:
            return direct

        # 1) основной путь: Element_Id -> CardType.ToolTipImage_Id
        elem_id = _toi(item.get("Element_Id"), 0)
        if elem_id > 0:
            img_id = self._db_element_badge_image_id(elem_id)
            if img_id:
                return img_id

        # 2) fallback: если вдруг у тебя хранится CardType.Id
        ct_id = _toi(
            item.get("Id"),
            0,
        )
        if ct_id > 0:
            img_id = self._db_element_badge_image_id(ct_id)
            if img_id:
                return img_id

        return None

    def _db_element_badge_image_id(self, cardtype_or_element_id: int) -> Optional[int]:
        """
        Возвращает Image.Id для иконки элемента:
        предпочитаем CardType.ToolTipImage_Id, иначе CardType.Image_Id.

        Вход:
          - CardType.Id  ИЛИ
          - CardType.Element_Id
        """
        try:
            x = int(cardtype_or_element_id)
        except Exception:
            return None
        if x <= 0:
            return None

        # ✅ правильный conn: у родителя
        p = self.parent()
        conn = None
        try:
            conn = p.data.conn if (p and hasattr(p, "data") and p.data and getattr(p.data, "conn", None)) else None
        except Exception:
            conn = None
        if conn is None:
            return None

        def _pick(row):
            if not row:
                return None
            # row может быть sqlite Row или tuple
            try:
                tti = row["ToolTipImage_Id"] if hasattr(row, "keys") else row[0]
                imi = row["ToolTipImage_Id"] if hasattr(row, "keys") else row[1]
            except Exception:
                try:
                    tti, imi = row[0], row[1]
                except Exception:
                    return None
            val = tti if tti is not None else imi
            try:
                return int(val) if val else None
            except Exception:
                return None

        # 1) считаем, что x = CardType.Id
        try:
            row = conn.execute(
                """
                SELECT ToolTipImage_Id, Image_Id
                FROM CardType
                WHERE Id = ?
                LIMIT 1
                """,
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
                """
                SELECT  ToolTipImage_Id,Image_Id
                FROM CardType
                WHERE Element_Id = ?
                LIMIT 1
                """,
                (x,),
            ).fetchone()
            got = _pick(row)
            if got:
                return got
        except Exception:
            pass

        return None

    def _load_element_badge_pixmap(self, element_id: int, item: dict | None = None) -> Optional[QPixmap]:
        if not element_id:
            return None

        # кэш
        if element_id in self._element_badge_cache:
            pm = self._element_badge_cache[element_id]
            return pm if (pm and not pm.isNull()) else None

        pm: Optional[QPixmap] = None

        # 1) Если родитель умеет давать pixmap напрямую — используем
        p = self.parent()
        for name in ("get_element_badge_pixmap", "element_badge_pixmap", "_element_badge_pixmap"):
            fn = getattr(p, name, None) if p else None
            if callable(fn):
                try:
                    got = fn(int(element_id))
                    if isinstance(got, QPixmap) and not got.isNull():
                        pm = got
                        break
                except Exception:
                    pass

        # 2) Через ImageId (item/DB) + loader
        if pm is None and self._image_loader:
            img_id = None
            if item:
                img_id = self._element_badge_image_id_for_item(item)
            if img_id is None:
                img_id = self._db_element_badge_image_id(int(element_id))
            if img_id:
                try:
                    data = self._image_loader(int(img_id))
                    if data:
                        tmp = QPixmap()
                        tmp.loadFromData(data)
                        if not tmp.isNull():
                            pm = tmp
                except Exception:
                    pass

        # 3) Фолбэк по файлам
        if pm is None:
            dir_candidates = [
                "resources/elements",
                "resources/element",
                "resources/ui/elements",
                "resources/icons/elements",
            ]
            for d in dir_candidates:
                base = Path(_resolve_resource(d))
                if base.exists() and base.is_dir():
                    for ext in ("png", "webp", "jpg", "jpeg"):
                        for pat in (f"{element_id}.{ext}", f"element_{element_id}.{ext}", f"elem_{element_id}.{ext}"):
                            fp = base / pat
                            if fp.exists():
                                tmp = QPixmap(str(fp))
                                if not tmp.isNull():
                                    pm = tmp
                                    break
                        if pm is not None:
                            break
                if pm is not None:
                    break

        # ВАЖНО: нормализуем (прозрачность/кроп), чтобы не было квадратов
        if pm is not None and not pm.isNull():
            try:
                pm = self._sanitize_badge_pixmap(pm)
            except Exception:
                pass

        self._element_badge_cache[element_id] = pm or QPixmap()
        return pm if (pm and not pm.isNull()) else None

    def _compose_with_element_badge(self, base_pm: QPixmap, canvas_size, element_id: int, item: dict) -> QPixmap:
        """
        Базовая иконка + бейдж элемента снизу-слева.
        Бейдж РИСУЕМ как 12x16 (в масштабе клетки), и НЕ сохраняем исходное соотношение сторон,
        иначе квадрат никогда не станет прямоугольником.
        """
        canvas = QPixmap(canvas_size)
        canvas.fill(Qt.transparent)

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # base icon (центрируем)
        base_scaled = base_pm.scaled(canvas.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (canvas.width() - base_scaled.width()) // 2
        y = (canvas.height() - base_scaled.height()) // 2
        painter.drawPixmap(x, y, base_scaled)

        if not element_id:
            painter.end()
            return canvas

        badge = self._load_element_badge_pixmap(int(element_id), item=item)
        if badge and not badge.isNull():
            base = int(min(canvas.width(), canvas.height()))

            # 12x16 относительно дизайн-клетки 54
            bw = max(1, int(base * (12.0 / 54.0)))
            bh = max(1, int(base * (16.0 / 54.0)))
            m = max(1, int(base * (4.0 / 54.0)))
            badge_scaled = badge.scaled(bw, bh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

            dy = int(base * (2.0 / 54.0))  # сдвиг вниз на ~2px в дизайне 54
            by = canvas.height() - badge_scaled.height() - m + dy

            # чтобы не вылез за низ (иначе обрежется):
            by = min(by, canvas.height() - badge_scaled.height())
            bx = m
            painter.drawPixmap(bx, by, badge_scaled)

        painter.end()
        return canvas

    def _sanitize_badge_pixmap(self, pm: QPixmap) -> QPixmap:
        """
        Делает бейдж нормальным:
        - если есть альфа -> просто автокроп по альфе
        - если альфы нет -> ищем "фон" по рамкам (несколько inset-рамок), делаем его прозрачным,
          потом кропаем по альфе.
        """
        if not pm or pm.isNull():
            return pm

        from PySide6.QtGui import QImage

        img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
        w, h = img.width(), img.height()
        if w <= 1 or h <= 1:
            return pm

        # --- 1) Проверка: есть ли реальная альфа ---
        has_alpha = False
        for y in range(h):
            for x in range(w):
                if img.pixelColor(x, y).alpha() != 255:
                    has_alpha = True
                    break
            if has_alpha:
                break

        # --- helper: автокроп по альфе ---
        def crop_by_alpha(qimg: QImage) -> QImage:
            ww, hh = qimg.width(), qimg.height()
            minx, miny = ww, hh
            maxx, maxy = -1, -1
            for yy in range(hh):
                for xx in range(ww):
                    if qimg.pixelColor(xx, yy).alpha() > 0:
                        if xx < minx: minx = xx
                        if yy < miny: miny = yy
                        if xx > maxx: maxx = xx
                        if yy > maxy: maxy = yy
            if maxx >= minx and maxy >= miny:
                return qimg.copy(minx, miny, (maxx - minx + 1), (maxy - miny + 1))
            return qimg

        # Если альфа есть — просто кропаем и выходим
        if has_alpha:
            cropped = crop_by_alpha(img)
            out = QPixmap.fromImage(cropped)
            return out if not out.isNull() else pm

        # --- 2) Альфы нет: делаем "прозрачность по фону" ---
        # Берём цвет фона не только по углам (там может быть рамка),
        # а по нескольким inset-рамкам: 0,1,2 пикселя внутрь.
        from collections import Counter

        def sample_inset_border(inset: int) -> list[tuple[int, int, int]]:
            if inset < 0:
                inset = 0
            if inset >= w or inset >= h:
                return []
            xs0, xs1 = inset, w - 1 - inset
            ys0, ys1 = inset, h - 1 - inset
            if xs0 > xs1 or ys0 > ys1:
                return []

            pts: list[tuple[int, int, int]] = []

            # верх/низ
            for x in range(xs0, xs1 + 1):
                c1 = img.pixelColor(x, ys0)
                c2 = img.pixelColor(x, ys1)
                pts.append((c1.red(), c1.green(), c1.blue()))
                pts.append((c2.red(), c2.green(), c2.blue()))

            # лево/право
            for y in range(ys0, ys1 + 1):
                c1 = img.pixelColor(xs0, y)
                c2 = img.pixelColor(xs1, y)
                pts.append((c1.red(), c1.green(), c1.blue()))
                pts.append((c2.red(), c2.green(), c2.blue()))

            return pts

        samples = []
        for inset in (0, 1, 2):
            samples.extend(sample_inset_border(inset))

        if not samples:
            return pm

        # Квантование, чтобы устойчивее найти доминирующий цвет
        def q(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
            r, g, b = rgb
            return (r // 8, g // 8, b // 8)

        cnt = Counter(q(s) for s in samples)
        bg_q, _ = cnt.most_common(1)[0]
        bg = (bg_q[0] * 8, bg_q[1] * 8, bg_q[2] * 8)

        tol = 18  # допуск, можно 12..28
        br, bgc, bb = bg

        # Убираем фон (делаем прозрачным)
        for y in range(h):
            for x in range(w):
                c = img.pixelColor(x, y)
                if (abs(c.red() - br) <= tol and
                        abs(c.green() - bgc) <= tol and
                        abs(c.blue() - bb) <= tol):
                    c.setAlpha(0)
                    img.setPixelColor(x, y, c)
                else:
                    # раз альфы не было — ставим 255 явно
                    if c.alpha() != 255:
                        c.setAlpha(255)
                        img.setPixelColor(x, y, c)

        # Кроп по получившейся альфе
        cropped = crop_by_alpha(img)

        out = QPixmap.fromImage(cropped)
        return out if not out.isNull() else pm

    #-----------------------------------------

    def _place_item_into_cell(self, pos: Tuple[int, int], src_item: dict) -> None:
        r, c = pos

        # если сюда прилетела заглушка — считаем это очисткой клетки
        if self._is_stub_item(src_item):
            self._inv_log("PLACE_STUB_SKIP", rc=(r, c), reason="stub_item")
            self._items.pop((r, c), None)
            ico = self._cell_icons.get((r, c))
            if ico:
                ico.clear()
                ico.hide()
            self._update_capacity_indicator()
            return

        # DETECT OVERWRITE (это частая причина "пропал предмет")
        old = (self._items or {}).get((r, c))
        try:
            old_key = self._item_identity_key(old) if isinstance(old, dict) else None
            new_key = self._item_identity_key(src_item) if isinstance(src_item, dict) else None
        except Exception:
            old_key, new_key = None, None

        if isinstance(old, dict) and old_key is not None and new_key is not None and old_key != new_key:
            self._inv_log(
                "CELL_OVERWRITE",
                rc=(r, c),
                old=self._inv_brief(old),
                new=self._inv_brief(src_item),
            )

        cell = self._cell_at(r, c)

        icon = self._cell_icons.get((r, c))
        if icon is None:
            icon = QLabel(self.grid_layer)
            icon.setAttribute(Qt.WA_TranslucentBackground, True)
            icon.setStyleSheet("background: transparent;")
            icon.setMouseTracking(True)
            icon.installEventFilter(self)
            icon.setContextMenuPolicy(Qt.PreventContextMenu)
            icon.setScaledContents(False)
            icon.setAlignment(Qt.AlignCenter)
            self._cell_icons[(r, c)] = icon

        stored = ensure_local_guid(deep_clone(src_item))
        inst = get_instance_guid(stored)

        st = stored.get("Stamp") or self._stamp_for_item(stored)
        if st is not None:
            stored["Stamp"] = deep_clone(st)
            if inst:
                self._inv_stamp_by_instance[inst] = deep_clone(st)

        self._items[(r, c)] = stored

        img_id = (stored.get("Icon_Image_Id") or stored.get("Image_Id") or stored.get("CostumeImage_Id"))
        pm = None
        if img_id and self._image_loader:
            try:
                data = self._image_loader(int(img_id))
                if data:
                    pm = QPixmap()
                    pm.loadFromData(data)
            except Exception:
                pm = None

        rect = self._icon_rect_for_cell(cell)
        icon.setGeometry(rect)

        if pm and not pm.isNull():
            eid = self._element_id_for_item(stored) or 0
            final_pm = self._compose_with_element_badge(pm, rect.size(), eid, stored)
            icon.setPixmap(final_pm)
            icon.show()
            icon.raise_()
        else:
            # ВАЖНО: предмет в _items есть, но иконка может не рисоваться — это тоже "как будто удалился"
            icon.clear()
            icon.hide()
            self._inv_log(
                "PLACE_NO_PIXMAP",
                rc=(r, c),
                item=self._inv_brief(stored),
                img_id=img_id,
                has_loader=bool(self._image_loader),
            )

        self._update_capacity_indicator()

        icon.setProperty("inv_row", r)
        icon.setProperty("inv_col", c)
        icon.setProperty("inv_item_dict", stored)

        #if DEBUG_INV_VERBOSE_PLACE:
        #    self._inv_log("PLACE_OK", rc=(r, c), item=self._inv_brief(stored), used=self._capacity_used())

    # --------------------------- свап через родителя -----------------------------
    def _source_cell_replaced(self, rc: tuple[int, int], orig_guid: str | None) -> tuple[bool, dict | None]:
        """
        True если родитель заменил содержимое исходной клетки (swap в ту же ячейку).
        """
        try:
            now = (self._items or {}).get(rc)
            if not isinstance(now, dict):
                return (False, None)
            now_guid = get_instance_guid(now)
            if orig_guid and now_guid and now_guid != orig_guid:
                return (True, now)
        except Exception:
            pass
        return (False, None)

    def _equip_via_parent(self, slot_key: str, new_item: dict, prev_item: dict | None,
                          *, prefer_rc: tuple[int, int] | None = None) -> bool:
        parent = self.parent()
        if not parent or not isinstance(new_item, dict):
            self._inv_log("EQUIP_PARENT_ABORT", slot=slot_key, reason="no_parent_or_bad_item")
            return False

        self._inv_log(
            "EQUIP_PARENT_REQ",
            slot=slot_key,
            prefer_rc=prefer_rc,
            new=self._inv_brief(new_item),
            prev=self._inv_brief(prev_item),
        )

        # --- helpers ---
        def _equip_id(it: dict | None) -> int:
            if not isinstance(it, dict):
                return 0
            for k in ("Id", "Equipment_Id", "EquipmentId"):
                v = it.get(k)
                if v is not None:
                    try:
                        return int(v)
                    except Exception:
                        pass
            return 0

        def _same_item(a: dict | None, b: dict | None) -> bool:
            if not isinstance(a, dict) or not isinstance(b, dict):
                return False
            ga = get_instance_guid(a)
            gb = get_instance_guid(b)
            if ga and gb:
                return str(ga) == str(gb)
            ea = _equip_id(a)
            eb = _equip_id(b)
            if ea > 0 and eb > 0:
                return ea == eb
            try:
                return self._item_identity_key(a) == self._item_identity_key(b)
            except Exception:
                return False

        # --- СНАПШОТ ДО ---
        # before_sel
        before_sel = {}
        if hasattr(parent, "_selected_items") and isinstance(parent._selected_items, dict):
            for k, v in parent._selected_items.items():
                if isinstance(v, dict) and self._is_real_item(v):
                    before_sel[str(k).strip().lower()] = deep_clone(v)

        # after_sel
        after_sel = {}
        if hasattr(parent, "_selected_items") and isinstance(parent._selected_items, dict):
            for k, v in parent._selected_items.items():
                if isinstance(v, dict) and self._is_real_item(v):
                    after_sel[str(k).strip().lower()] = deep_clone(v)

        new_item_for_parent = ensure_local_guid(deep_clone(new_item))
        prev_item_for_parent = deep_clone(prev_item) if isinstance(prev_item, dict) else None
        if isinstance(prev_item_for_parent, dict):
            prev_item_for_parent = ensure_local_guid(prev_item_for_parent)

        try:
            new_item_for_parent["slot_key"] = slot_key
        except Exception:
            pass

        res = None
        called = False
        called_name = None

        for name in ("on_inventory_swap_request", "equip_item_in_slot", "equip_item",
                     "set_equipped_item", "apply_item_to_slot"):
            fn = getattr(parent, name, None)
            if not callable(fn):
                continue
            called = True
            called_name = name
            try:
                res = fn(slot_key, new_item_for_parent, prev_item_for_parent)
            except TypeError:
                try:
                    res = fn(slot_key, new_item_for_parent)
                except TypeError:
                    res = fn(new_item_for_parent)
            break

        if not called:
            self._inv_log("EQUIP_PARENT_NO_HANDLER", slot=slot_key)
            return False

        # --- СНАПШОТ ПОСЛЕ ---
        after_sel: dict[str, dict] = {}
        try:
            if hasattr(parent, "_selected_items") and isinstance(parent._selected_items, dict):
                for k, v in parent._selected_items.items():
                    if isinstance(v, dict):
                        after_sel[str(k).strip().lower()] = deep_clone(v)
        except Exception:
            after_sel = {}

        ok: bool | None = None
        extras_from_parent: list[dict] = []

        if isinstance(res, bool):
            ok = res
        elif isinstance(res, dict):
            ok = bool(res.get("ok", res.get("success", True)))
            extra = res.get("extra") or res.get("extras") or res.get("unequipped") or res.get("removed")
            if isinstance(extra, dict):
                extras_from_parent = [extra]
            elif isinstance(extra, (list, tuple)):
                extras_from_parent = [x for x in extra if isinstance(x, dict)]
        elif isinstance(res, (list, tuple)):
            if len(res) >= 1 and isinstance(res[0], bool):
                ok = res[0]
            if len(res) >= 2:
                extra = res[1]
                if isinstance(extra, dict):
                    extras_from_parent = [extra]
                elif isinstance(extra, (list, tuple)):
                    extras_from_parent = [x for x in extra if isinstance(x, dict)]
        else:
            ok = None

        inferred = False
        if ok is not True:
            sk = str(slot_key).strip().lower()
            now = after_sel.get(sk)
            if isinstance(now, dict) and _same_item(now, new_item_for_parent):
                ok = True
                inferred = True
            else:
                ok = False

        self._inv_log(
            "EQUIP_PARENT_RES",
            handler=called_name,
            slot=slot_key,
            ok=ok,
            inferred=inferred,
            res_type=type(res).__name__,
            extras=len(extras_from_parent or []),
        )

        if not ok:
            # полезно: показать что реально лежит в слоте после неуспеха
            try:
                sk = str(slot_key).strip().lower()
                now = after_sel.get(sk)
                self._inv_log("EQUIP_PARENT_FAIL_SLOT_NOW", slot=slot_key, now=self._inv_brief(now))
            except Exception:
                pass
            return False

        # --- implicit extras: что исчезло/заменилось ---
        implicit: list[dict] = []
        exclude: set[tuple] = set()

        if isinstance(prev_item_for_parent, dict):
            exclude.add(self._item_identity_key(prev_item_for_parent))
        exclude.add(self._item_identity_key(new_item_for_parent))

        try:
            for k, was in before_sel.items():
                if not isinstance(was, dict):
                    continue
                kwas = self._item_identity_key(was)
                if kwas in exclude:
                    continue

                now = after_sel.get(k)
                if not isinstance(now, dict):
                    back = deep_clone(was)
                    if isinstance(back, dict) and not back.get("slot_key"):
                        back["slot_key"] = k
                    implicit.append(back)
                    continue

                if self._item_identity_key(now) != kwas:
                    back = deep_clone(was)
                    if isinstance(back, dict) and not back.get("slot_key"):
                        back["slot_key"] = k
                    implicit.append(back)
        except Exception:
            pass

        all_extras: list[dict] = []
        for x in (extras_from_parent or []):
            if isinstance(x, dict):
                all_extras.append(x)
        for x in (implicit or []):
            if isinstance(x, dict):
                all_extras.append(x)

        if not all_extras:
            return True

        # дедуп + не добавляем если уже есть в инвентаре
        def _inv_has_item(it: dict) -> bool:
            try:
                key = self._item_identity_key(it)
            except Exception:
                return False
            try:
                for cur in (self._items or {}).values():
                    if isinstance(cur, dict) and self._item_identity_key(cur) == key:
                        return True
            except Exception:
                pass
            return False

        merged: list[dict] = []
        seen: set[tuple] = set()
        for it in all_extras:
            if not isinstance(it, dict):
                continue
            key = self._item_identity_key(it)
            if key in seen:
                continue
            hit = self._inv_find_existing_rc(it)
            if hit:
                rc0, cur0 = hit
                self._inv_log(
                    "EQUIP_PARENT_EXTRA_DUP_HIT",
                    extra=self._inv_brief(it),
                    in_rc=rc0,
                    in_item=self._inv_brief(cur0),
                )
                continue

            seen.add(key)
            merged.append(ensure_local_guid(deep_clone(it)))

        self._inv_log(
            "EQUIP_PARENT_EXTRAS_MERGED",
            count=len(merged),
            items=[self._inv_brief(x) for x in merged[:6]],
            prefer_rc=prefer_rc,
        )

        if not merged:
            return True

        def _return_later(items=merged, pr=prefer_rc):
            try:
                if not self or not hasattr(self, "_items"):
                    return
            except Exception:
                return
            self._return_items_to_inventory(items, prefer_rc=pr)

        QTimer.singleShot(0, _return_later)
        return True

    def _inv_remove_source_cell_safely(self, rc: tuple[int, int], src_item: dict | None, reason: str) -> bool:
        """
        Удаляет предмет из source-ячейки ТОЛЬКО если в ней всё ещё лежит тот же предмет (по InstanceGuid).
        Если ячейка уже заменена родителем (в ней другой item) — НЕ трогаем её,
        перерисовываем текущий item в ячейке и пытаемся удалить src_item по GUID где бы он ни лежал.
        Возвращает True если реально удалили по rc, False если ячейка была заменена.
        """
        if not isinstance(rc, tuple) or len(rc) != 2:
            return False

        want_gid = get_instance_guid(src_item) if isinstance(src_item, dict) else None
        now = (self._items or {}).get(rc)

        if want_gid and isinstance(now, dict):
            now_gid = get_instance_guid(now)
            if str(now_gid or "") != str(want_gid):
                # ячейка уже не источник — в ней теперь другой item
                self._inv_log(
                    "SRC_CELL_REPLACED_SKIP_POP",
                    rc=rc,
                    reason=reason,
                    want=self._inv_brief(src_item),
                    now=self._inv_brief(now),
                )

                # чтобы не осталось "пусто" / hidden — перерисуем то, что реально лежит в rc
                try:
                    self._place_item_into_cell(rc, now)
                except Exception as e:
                    self._inv_log("SRC_CELL_REPLACED_REDRAW_FAIL", rc=rc, err=repr(e))

                # если исходный предмет всё ещё где-то лежит в инвентаре — уберём его по GUID
                try:
                    self.remove_instance(str(want_gid))
                except Exception:
                    pass

                return False

        # обычный случай: в rc всё ещё источник
        self._inv_remove_at(rc, reason)
        return True

    # ------------------------------ события --------------------------------------
    def eventFilter(self, obj, ev):
        """
        Единый фильтр событий:
        1) Секция board (фон окна, крестик, таскание окна).
        2) Секция иконок предметов в сетке.
        3) Глобальная секция DnD (через qApp.installEventFilter) — в самом конце!
        """

        # ---------------------- 1) BOARD (фон/крест/перемещение окна) ----------------------
        if obj is self.board:
            if ev.type() == QEvent.MouseMove:
                lp = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                if self._close_rect().contains(lp):
                    if not self._close_hover_pm.isNull():
                        rect = self._close_rect()
                        self._close_overlay.setGeometry(rect)
                        self._close_overlay.setPixmap(self._close_hover_pm)
                        self._close_overlay.show()
                        self._close_overlay.raise_()
                else:
                    self._close_overlay.hide()

                if self._drag_pos and (ev.buttons() & Qt.LeftButton):
                    gp = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()
                    self.move(gp - self._drag_pos)

                    # ✅ во время таскания обновляем последнюю позицию
                    self._remember_window_pos()
                    return True
                return False

            if ev.type() == QEvent.MouseButtonPress:
                btn = getattr(ev, "button", lambda: None)()
                if btn == Qt.LeftButton:
                    lp = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                    if self._close_rect().contains(lp):
                        return False
                    gp = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else ev.globalPos()
                    self._drag_pos = gp - self.frameGeometry().topLeft()
                    return True

            if ev.type() == QEvent.MouseButtonRelease:
                self._drag_pos = None

                # ✅ на отпускании ЛКМ фиксируем позицию (после перетаскивания)
                self._remember_window_pos()

                lp = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                if getattr(ev, "button", lambda: None)() == Qt.LeftButton and self._close_rect().contains(lp):
                    # ✅ перед закрытием тоже запомним
                    self._remember_window_pos()
                    self.close()
                    return True
                return False

        # ---------------------- 2) ИКОНКИ ПРЕДМЕТОВ В СЕТКЕ ----------------------
        if isinstance(obj, QLabel) and obj in self._cell_icons.values():
            r = obj.property("inv_row")
            c = obj.property("inv_col")

            cell = None
            if isinstance(r, int) and isinstance(c, int):
                try:
                    cell = self._cell_at(r, c)
                except Exception:
                    cell = None

            # hover: рамка + тултип
            if ev.type() == QEvent.Enter:
                if cell:
                    cell._hover = True
                    cell.update()
                item = obj.property("inv_item_dict") or None
                if isinstance(item, dict):
                    self._show_item_tooltip(obj, item)
                return False

            if ev.type() == QEvent.Leave:
                if cell:
                    cell._hover = False
                    cell.update()

                # Не даём старой ячейке закрыть новую анкету,
                # если мышь быстро перешла на другой предмет.
                if getattr(self, "_last_tip_anchor", None) is obj:
                    p = self.parent()
                    if p and hasattr(p, "equip_info"):
                        try:
                            p.equip_info.end_hover(obj)
                        except Exception:
                            pass
                    self._last_tip_anchor = None

                return False

            # ЛКМ PRESS: помечаем кандидата на drag
            if ev.type() == QEvent.MouseButtonPress and getattr(ev, "button", lambda: None)() == Qt.LeftButton:
                item = obj.property("inv_item_dict") or None
                if isinstance(item, dict):
                    gp = getattr(ev, "globalPosition", None)
                    gp = gp().toPoint() if callable(gp) else getattr(ev, "globalPos", lambda: QPoint(-1, -1))()
                    self._drag_candidate = {"item": item, "label": obj, "r": int(r), "c": int(c)}
                    self._drag_press_pos = gp
                return False

            # CTRL + ПКМ: контекстное меню
            if ev.type() == QEvent.MouseButtonRelease and getattr(ev, "button", lambda: None)() == Qt.RightButton:
                mods = getattr(ev, "modifiers", lambda: QApplication.keyboardModifiers())()
                if mods & Qt.ControlModifier:
                    gpos = getattr(ev, "globalPosition", None)
                    gpos = gpos().toPoint() if callable(gpos) else getattr(ev, "globalPos", lambda: QPoint(-1, -1))()
                    item = obj.property("inv_item_dict") or None
                    if isinstance(item, dict):
                        self._open_inv_item_context_menu_async(obj, int(r), int(c), item, gpos)
                        return True  # Поглощаем
                # если без Ctrl — идём дальше (возможен обычный ПКМ swap ниже)

            # DEBUG: ContextMenu
            if ev.type() == QEvent.ContextMenu:
                lpos = getattr(ev, "pos", lambda: QPoint(-1, -1))()
                gpos = getattr(ev, "globalPos", lambda: QPoint(-1, -1))()
                self._blink_cell(cell, "rgba(170,100,255,220)", 220)
                return False

            # ПКМ RELEASE: свап в слот
            if ev.type() == QEvent.MouseButtonRelease and getattr(ev, "button", lambda: None)() == Qt.RightButton:
                lpos = getattr(ev, "pos", lambda: QPoint(-1, -1))()
                gpos = getattr(ev, "globalPosition", None)
                gpos = gpos().toPoint() if callable(gpos) else getattr(ev, "globalPos", lambda: QPoint(-1, -1))()

                self._blink_cell(cell, "rgba(60,220,220,220)", 180)

                cur_item = obj.property("inv_item_dict")
                if not isinstance(cur_item, dict):
                    return True  # поглотим, чтобы не всплыло системное меню

                # проверка на допустимость по классу/полу
                if not self._is_item_allowed_for_class(cur_item, self._current_class_value()):
                    if cell:
                        old = cell.styleSheet()
                        cell.setStyleSheet(old + "\nborder:2px solid rgba(255,80,80,220); border-radius:3px;")
                        QTimer.singleShot(220, lambda: cell.setStyleSheet(old))
                    return True

                slot_key = self._get_item_slot_key(cur_item)
                if not slot_key:
                    return True

                raw = self._get_item_slot_key(cur_item)
                if not raw:
                    return True

                slot_key = self._normalize_key_for_parent(raw)

                parent = self.parent()
                equipped_before = None
                try:
                    if parent and hasattr(parent, "_selected_items") and isinstance(parent._selected_items, dict):
                        equipped_before = parent._selected_items.get(slot_key)
                        equipped_before = self._as_real_or_none(equipped_before)

                except Exception:
                    equipped_before = None

                ok = self._equip_via_parent(slot_key, cur_item, equipped_before, prefer_rc=(int(r), int(c)))
                if not ok:
                    return True

                # убрать предмет из инвентаря БЕЗОПАСНО (ячейку мог заменить родитель)
                if isinstance(r, int) and isinstance(c, int):
                    rc = (int(r), int(c))
                    removed_by_rc = self._inv_remove_source_cell_safely(rc, cur_item, "equip_rmb_to_parent")

                    if equipped_before:
                        safe_back = dict(equipped_before)
                        if slot_key and not safe_back.get("slot_key"):
                            safe_back["slot_key"] = str(slot_key)

                        if removed_by_rc:
                            self._place_item_into_cell(rc, safe_back)
                        else:
                            # parent уже мог положить prev в src-клетку (swap). Не возвращаем второй раз.
                            now_in_rc = (self._items or {}).get(rc)
                            same = False
                            try:
                                if isinstance(now_in_rc, dict) and isinstance(safe_back, dict):
                                    same = self._item_identity_key(now_in_rc) == self._item_identity_key(safe_back)
                            except Exception:
                                same = False

                            if not same:
                                self._return_items_to_inventory([safe_back], prefer_rc=None)
                            else:
                                self._inv_log("EQUIP_SKIP_RETURN_PREV_ALREADY_IN_SRC", rc=rc,
                                              prev=self._inv_brief(safe_back))

                    else:
                        # чистим/прячем ИКОНКУ только если реально удалили источник из этой клетки
                        if removed_by_rc:
                            obj.clear()
                            obj.hide()

                if parent and hasattr(parent, "equip_info"):
                    try:
                        parent.equip_info.end_hover(obj)
                    except Exception:
                        pass

                self._update_capacity_message()
                self._update_capacity_indicator()
                return True

            # другие события иконок — пропускаем дальше
            return False

        # ---------------------- 3) ГЛОБАЛЬНАЯ DnD-СЕКЦИЯ (через qApp) ----------------------
        # NB: сюда попадают события от любого obj, в т.ч. вне нашего окна
        if ev.type() == QEvent.MouseMove:
            gp = getattr(ev, "globalPosition", None)
            gp = gp().toPoint() if callable(gp) else getattr(ev, "globalPos", lambda: QPoint(-1, -1))()

            drag_active = bool(getattr(self, "_drag_active", False))
            candidate = getattr(self, "_drag_candidate", None)
            press_pos = getattr(self, "_drag_press_pos", None)

            # запуск DnD при достаточном смещении
            if (not drag_active) and candidate and press_pos:
                if (gp - press_pos).manhattanLength() >= DRAG_THRESHOLD_PX:
                    dc = candidate
                    self._drag_begin(dc["label"], dc["r"], dc["c"], dc["item"], press_pos)
                    self._drag_candidate = None
                    self._drag_move(gp)
                    return False

            # перемещение активного DnD
            if drag_active:
                self._drag_move(gp)
                return False

        if ev.type() == QEvent.MouseButtonRelease and getattr(ev, "button", lambda: None)() == Qt.LeftButton:
            gp = getattr(ev, "globalPosition", None)
            gp = gp().toPoint() if callable(gp) else getattr(ev, "globalPos", lambda: QPoint(-1, -1))()

            if bool(getattr(self, "_drag_active", False)):
                self._drag_commit_or_cancel(gp)
                return True

            # если drag не стартовал — сброс кандидата
            self._drag_candidate = None
            self._drag_press_pos = None

        # всё остальное — стандартная обработка
        return super().eventFilter(obj, ev)

    def enterEvent(self, _):  self.board.setMouseTracking(True)

    def resizeEvent(self, _):
        self._apply_background()
        self._close_overlay.hide()
        self._layout_grid()
        self._layout_status_label()
        self._layout_counter_label()


    def _reflow_after_changes(self) -> None:
        # переуложить и обновить фразу
        self._layout_grid()
        self._update_capacity_message()

    def _blink_cell(self, cell: QLabel | None, rgba: str, ms: int = 180):
        if not cell:
            return
        old = cell.styleSheet()
        cell.setStyleSheet(old + f"\nborder:2px solid {rgba}; border-radius:3px;")
        QTimer.singleShot(ms, lambda: cell.setStyleSheet(old))

    def _choose_ring_slot_key(self) -> str:
        parent = self.parent()
        sel = getattr(parent, "_selected_items", None)
        if isinstance(sel, dict) and ("ring1" in sel or "ring2" in sel):
            if not sel.get("ring1"):
                return "ring1"
            if not sel.get("ring2"):
                return "ring2"
            return "ring1"  # оба заняты — заменим ring1
        return "ring"  # если у родителя нет раздельных ключей — оставляем общий

    def _open_inv_item_context_menu_async(self, icon_obj: QLabel, r: int, c: int, item: dict, global_pos) -> None:
        """Контекстное меню по Ctrl+ПКМ для предмета в инвентаре."""

        def _show():
            m = _InfoBoardMenu(self)
            _apply_popup_menu_style(m)

            # --- действие: Удалить предмет из инвентаря ---
            act_del = m.addAction("Удалить предмет")

            def _do_delete():
                # подчистим локальные структуры и UI
                self._items.pop((r, c), None)
                ico = self._cell_icons.get((r, c))
                if ico:
                    ico.clear()
                    ico.hide()
                # если есть кэш печати по InstanceGuid — уберём
                try:
                    inst = (item or {}).get("InstanceGuid")
                    if inst:
                        self._inv_stamp_by_instance.pop(inst, None)
                except Exception:
                    pass
                self._update_capacity_indicator()

            act_del.triggered.connect(_do_delete)

            # --- если это кольцо — добавить пункт "Поместить кольцо во второй слот" ---
            slot_key = self._get_item_slot_key(item)
            is_ring = str(slot_key or "").startswith("ring")
            if is_ring:
                m.addSeparator()
                act_to_ring2 = m.addAction("Поместить кольцо во второй слот")

                def _place_to_ring2():
                    parent = self.parent()
                    if not parent:
                        return
                    # что сейчас в ring2?
                    equipped_before = None
                    try:
                        if hasattr(parent, "_selected_items") and isinstance(parent._selected_items, dict):
                            equipped_before = parent._selected_items.get("ring2")
                    except Exception:
                        equipped_before = None

                    # попытка экипировать в ring2
                    ok = self._equip_via_parent("ring2", item, equipped_before)
                    if not ok:
                        # лёгкая визуальная подсказка
                        cell = None
                        try:
                            cell = self._cell_at(r, c)
                        except Exception:
                            pass
                        self._blink_cell(cell, "rgba(255,80,80,220)", 220)
                        return

                    # успешный своп: текущий предмет уходит в слот, а прежний из ring2 кладём обратно в клетку
                    self._items.pop((r, c), None)
                    if equipped_before:
                        safe_back = dict(equipped_before)
                        if not safe_back.get("slot_key"):
                            safe_back["slot_key"] = "ring2"
                        self._place_item_into_cell((r, c), safe_back)
                    else:
                        ico = self._cell_icons.get((r, c))
                        if ico:
                            ico.clear()
                            ico.hide()

                    # закрыть тултип, если висит
                    p = self.parent()
                    if p and hasattr(p, "equip_info"):
                        try:
                            p.equip_info.end_hover(icon_obj)
                        except Exception:
                            pass

                    self._update_capacity_indicator()

                act_to_ring2.triggered.connect(_place_to_ring2)

            # показать меню
            m.popup(global_pos)

        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, _show)

    # ---------- DRAG&DROP helpers ----------
    def _ensure_drag_floater(self):
        if self._drag_floater is None:
            # создаём топ-левел лейбл (без родителя), а флаги ставим методом
            w = QLabel(None)
            # делаем "плавающим" поверх всех окон и без фрейма
            w.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.Tool
                | Qt.WindowStaysOnTopHint
                | Qt.BypassWindowManagerHint  # безопасно; можно убрать, если не нужно
            )
            # прозрачный фон и не перехватывает мышь
            w.setAttribute(Qt.WA_TranslucentBackground, True)
            w.setAttribute(Qt.WA_NoSystemBackground, True)
            w.setAttribute(Qt.WA_ShowWithoutActivating, True)
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            w.setFocusPolicy(Qt.NoFocus)
            w.setStyleSheet("background: transparent;")
            w.setScaledContents(True)

            self._drag_floater = w

    def _family_for_key(self, key: str) -> str:
        k = (key or "").strip().lower()
        if not k:
            return k
        # нормализация распространённых алиасов
        if "ring" in k:
            return "ring"
        if "shield" in k or "off" in k or k in {"lhand", "left-hand", "secondary"}:
            return "offhand"
        if "weapon" in k or k in {"rhand", "right-hand", "mainhand", "primary", "main"}:
            return "weapon"
        return k

    def _item_slot_family(self, item: dict) -> Optional[str]:
        sk = self._get_item_slot_key(item)
        return self._family_for_key(sk) if sk else None

    def _can_drop_item_to_key(self, item: dict, target_key: str) -> bool:
        fam_item = self._item_slot_family(item)
        fam_target = self._family_for_key(target_key)

        if not fam_item or not fam_target:
            return False

        # обычное правило (семейство совпало)
        if fam_item == fam_target:
            return True

        # спец-правило: weapon -> offhand если класс умеет extra weapon и оружие 1H
        if fam_item == "weapon" and fam_target == "offhand":
            if self._class_allow_extra_weapon_ctx(self._current_class_value()) and self._is_single_hand_weapon(item):
                return True

        return False

    def _normalize_key_for_parent(self, key: str) -> str:
        """Подгоняем ключ под реальные ключи родителя (регистр, алиасы, ring→ring1/2)."""
        k = (key or "").strip()
        if not k:
            return k

        # ring → конкретный слот
        if k.lower() == "ring":
            return self._choose_ring_slot_key()

        # попытка подобрать реальный ключ по регистронезависимому совпадению
        p = self.parent()
        try:
            if p and hasattr(p, "_selected_items") and isinstance(p._selected_items, dict):
                for real in p._selected_items.keys():
                    if str(real).lower() == k.lower():
                        return str(real)
        except Exception:
            pass

        # финальный фолбэк — вернуть как есть
        return k

    def _drag_begin(self, source_label: QLabel, r: int, c: int, item: dict, start_gp: QPoint):
        self._drag_active = True
        self._drag_source_label = source_label
        self._drag_from_rc = (r, c)
        self._drag_target_key = None

        pm = source_label.pixmap()
        if not pm or pm.isNull():
            # запасной путь — загрузить иконку
            img_id = (item.get("Icon_Image_Id") or item.get("Image_Id") or item.get("CostumeImage_Id"))
            if img_id and self._image_loader:
                try:
                    data = self._image_loader(int(img_id))
                    if data:
                        tmp = QPixmap()
                        tmp.loadFromData(data)
                        pm = tmp
                except Exception:
                    pm = None

        self._ensure_drag_floater()
        if pm and not pm.isNull():
            size = source_label.size()
            self._drag_floater.setPixmap(pm.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self._drag_floater.resize(size)
        else:
            self._drag_floater.resize(1, 1)

        self._drag_floater.show()
        self._drag_move(start_gp)  # первоначальная позиция

        # на всякий случай закрыть тултип
        p = self.parent()
        if p and hasattr(p, "equip_info"):
            try: p.equip_info.end_hover(source_label)
            except Exception: pass

    def _drag_move(self, global_pos: QPoint):
        # позиция плавающей иконки
        if self._drag_floater and self._drag_floater.isVisible():
            tl = QPoint(global_pos.x() - self._drag_floater.width() // 2,
                        global_pos.y() - self._drag_floater.height() // 2)
            self._drag_floater.move(tl)

        # определяем слот под курсором и подсвечиваем
        p = self.parent()
        if not p:
            return
        try:
            win_pt = p.mapFromGlobal(global_pos)
            key_raw, rect = p._hit_zone(win_pt)  # что вернул родитель
        except Exception:
            key_raw, rect = (None, None)

        # берём предмет из исходной клетки
        item = None
        if self._drag_from_rc:
            item = self._items.get(self._drag_from_rc)

        good = False
        key_norm = (key_raw or "").strip().lower()  # ← нормализуем ключ слота

        equip_keys_lower = _equip_slot_keys_lower_from_parent(p)
        if key_norm in equip_keys_lower and rect and isinstance(item, dict):
            # семейством разрешаем drop (ring == ring1/ring2)
            good = self._can_drop_item_to_key(item, key_norm) and \
                   self._is_item_allowed_for_class(item, self._current_class_value())

        # сохраняем ТОЛЬКО нормализованный ключ — им будем экипировать
        self._drag_target_key = (key_norm if good else None)

        # визуальная подсветка слота у родителя — ему безопаснее отдать «как есть»
        try:
            if good:
                p._lock_glow_on_slot(key_raw, rect)
            else:
                p._unlock_glow()
        except Exception:
            pass

            # 2) цель внутри сетки инвентаря (для перемещения по клеткам)
        self._drag_target_cell = None
        try:
            lp = self.grid_layer.mapFromGlobal(global_pos)
            for i, cell in enumerate(self._cells):
                if cell.geometry().contains(lp):
                    r = i // COLS
                    c = i % COLS
                    self._drag_target_cell = (r, c)
                    break
        except Exception:
            self._drag_target_cell = None

    def _drag_commit_or_cancel(self, global_pos: QPoint):
        p = self.parent()
        target_key = self._drag_target_key
        target_cell = self._drag_target_cell
        from_rc = self._drag_from_rc

        self._inv_log(
            "DRAG_RELEASE",
            from_rc=from_rc,
            target_key=target_key,
            target_cell=target_cell,
        )

        try:
            if p:
                p._unlock_glow()
        except Exception:
            pass
        if self._drag_floater:
            self._drag_floater.hide()

        self._drag_active = False
        self._drag_candidate = None
        self._drag_press_pos = None
        self._drag_target_key = None
        self._drag_target_cell = None

        if (not p) or (not from_rc):
            self._inv_log("DRAG_ABORT", reason="no_parent_or_from_rc")
            return

        item = self._items.get(from_rc)
        if not isinstance(item, dict):
            self._inv_log("DRAG_ABORT", reason="no_item_in_from_rc", from_rc=from_rc)
            return

        # 1) цель — экип-слот
        if target_key:
            resolved_key = self._normalize_key_for_parent(target_key)

            equipped_before = None
            try:
                if hasattr(p, "_selected_items") and isinstance(p._selected_items, dict):
                    equipped_before = p._selected_items.get(resolved_key)
            except Exception:
                equipped_before = None

            self._inv_log(
                "DRAG_TO_EQUIP_REQ",
                from_rc=from_rc,
                slot=resolved_key,
                new=self._inv_brief(item),
                prev=self._inv_brief(equipped_before),
            )

            ok = self._equip_via_parent(resolved_key, item, equipped_before, prefer_rc=from_rc)
            self._inv_log("DRAG_TO_EQUIP_RET", ok=ok, from_rc=from_rc, slot=resolved_key)

            if not ok:
                return

            rc = (int(from_rc[0]), int(from_rc[1]))
            removed_by_rc = self._inv_remove_source_cell_safely(rc, item, "drag_to_parent")

            if equipped_before:
                back = dict(equipped_before)
                if not back.get("slot_key"):
                    back["slot_key"] = str(resolved_key)

                if removed_by_rc:
                    self._place_item_into_cell(rc, back)
                else:
                    now_in_rc = (self._items or {}).get(rc)
                    same = False
                    try:
                        if isinstance(now_in_rc, dict) and isinstance(back, dict):
                            same = self._item_identity_key(now_in_rc) == self._item_identity_key(back)
                    except Exception:
                        same = False

                    if not same:
                        self._return_items_to_inventory([back], prefer_rc=None)
                    else:
                        self._inv_log("EQUIP_SKIP_RETURN_PREV_ALREADY_IN_SRC", rc=rc, prev=self._inv_brief(back))

            else:
                if removed_by_rc:
                    self._inv_clear_icon_at(rc, "drag_to_parent_no_prev")

            self._update_capacity_message()
            self._update_capacity_indicator()
            return

        # 2) перенос/свап по сетке
        if target_cell and target_cell != from_rc:
            self._inv_log("DRAG_TO_CELL", src=from_rc, dst=target_cell, item=self._inv_brief(item))
            self._move_item_or_swap(from_rc, target_cell)
            self._update_capacity_message()
            self._update_capacity_indicator()

    def _is_real_item(self, it: dict | None) -> bool:
        """True только для реальных предметов, а не для пустых dict-заглушек."""
        if not isinstance(it, dict):
            return False

        # если есть любой из ключевых идентификаторов — это предмет
        for k in ("Id", "Equipment_Id", "EquipmentId", "Type_Id", "TypeId", "Slot_Id", "SlotId"):
            v = it.get(k)
            if v not in (None, "", 0):
                return True

        # если есть картинка — тоже считаем предметом
        for k in ("Icon_Image_Id", "Image_Id", "CostumeImage_Id"):
            v = it.get(k)
            if v not in (None, "", 0):
                return True

        # если есть имя/slot_key — тоже (на всякий)
        nm = (it.get("Name") or it.get("name") or "")
        sk = (it.get("slot_key") or it.get("SlotKey") or "")
        return bool(str(nm).strip() or str(sk).strip())

    def _is_stub_item(self, it: dict | None) -> bool:
        return isinstance(it, dict) and (not self._is_real_item(it))

    def _purge_stub_at(self, rc: tuple[int, int], reason: str) -> bool:
        it = (self._items or {}).get(rc)
        if not self._is_stub_item(it):
            return False
        self._items.pop(rc, None)
        self._inv_clear_icon_at(rc, f"purge_stub:{reason}")
        self._inv_log("PURGE_STUB", rc=rc, reason=reason, item=self._inv_brief(it))
        return True

    def _as_real_or_none(self, it: dict | None) -> dict | None:
        """Нормализатор для того, что приходит из parent._selected_items."""
        return it if self._is_real_item(it) else None

    def _item_identity_key(self, it: dict) -> tuple:
        """
        Устойчивый ключ для сравнения/дедупа предметов.

        Приоритет:
          1) InstanceGuid
          2) расширенная сигнатура предмета:
             Id / Type / Slot / forge / stamp / cards / elixir
        """
        if not isinstance(it, dict):
            return ("_none_",)

        gid = get_instance_guid(it)
        if gid:
            return ("guid", str(gid))

        def _safe_i(v, d=0):
            try:
                return int(v)
            except Exception:
                return d

        def _forge_level(d: dict) -> int:
            for k in ("__forge_level", "ForgeLevel", "UpgradeLevel", "Plus", "Refine", "EnhanceLevel"):
                try:
                    if k in d and d[k] not in (None, ""):
                        return int(d[k])
                except Exception:
                    pass
            return 0

        def _stamp_sig(d: dict) -> tuple:
            st = d.get("Stamp") or d.get("stamp")
            if not isinstance(st, dict):
                return ()
            return (
                _safe_i(st.get("Id"), 0),
                _safe_i(st.get("ColorId"), 0),
                str(st.get("Name") or ""),
                tuple(str(x) for x in (st.get("Bonuses") or [])),
            )

        def _elixir_sig(d: dict) -> tuple:
            el = d.get("Elixir") or d.get("_elixir")
            if not isinstance(el, dict):
                return ()
            bons = []
            for b in (el.get("Bonuses") or []):
                if not isinstance(b, dict):
                    continue
                bons.append((
                    _safe_i(b.get("OrderIndex"), 0),
                    _safe_i(b.get("Type_Id") or b.get("TypeId"), 0),
                    float(b.get("Value") or 0.0),
                ))
            return (
                _safe_i(el.get("Id") or el.get("id"), 0),
                str(el.get("Name") or el.get("name") or ""),
                tuple(bons),
            )

        def _cards_sig(d: dict) -> tuple:
            raw = d.get("_cards") or d.get("cards") or d.get("Cards")
            if isinstance(raw, dict):
                items = list(raw.items())
            elif isinstance(raw, (list, tuple)):
                items = [(i + 1, raw[i]) for i in range(len(raw))]
            else:
                items = []

            out = []
            for k, v in items:
                try:
                    idx = int(k)
                except Exception:
                    continue
                if not isinstance(v, dict):
                    continue
                out.append((
                    int(idx),
                    _safe_i(v.get("Id") or v.get("Card_Id") or v.get("CardId"), 0),
                    _safe_i(v.get("Image_Id") or v.get("ImageId"), 0),
                    str(v.get("Name") or ""),
                ))
            return tuple(sorted(out))

        try:
            eid = it.get("Id") or it.get("Equipment_Id") or it.get("EquipmentId") or 0
            tid = it.get("Type_Id") or it.get("TypeId") or 0
            sid = it.get("Slot_Id") or it.get("SlotId") or 0
            return (
                "meta",
                int(eid),
                int(tid),
                int(sid),
                int(_forge_level(it)),
                _stamp_sig(it),
                _cards_sig(it),
                _elixir_sig(it),
            )
        except Exception:
            return ("repr", repr(it)[:120])

    def _return_items_to_inventory(self, items: list[dict], *, prefer_rc: tuple[int, int] | None = None) -> None:
        if not items:
            return

        self._inv_log(
            "RETURN_BEGIN",
            count=len(items),
            prefer_rc=prefer_rc,
            items=[self._inv_brief(x) for x in items[:6]],
        )

        uniq: list[dict] = []
        seen: set[tuple] = set()
        for it in items:
            if not isinstance(it, dict):
                continue
            k = self._item_identity_key(it)
            if k in seen:
                self._inv_log("RETURN_DEDUP_SKIP", item=self._inv_brief(it))
                continue
            seen.add(k)
            uniq.append(ensure_local_guid(deep_clone(it)))

        # ⚠️ если такой предмет уже есть в инвентаре (по GUID/identity) — не кладём второй раз
        filtered: list[dict] = []
        for it in uniq:
            hit = self._inv_find_existing_rc(it)
            if hit:
                rc0, cur0 = hit
                self._inv_log("RETURN_SKIP_ALREADY_HAVE", rc=rc0, item=self._inv_brief(it), in_item=self._inv_brief(cur0))
                continue
            filtered.append(it)
        uniq = filtered

        if not uniq:
            self._inv_log("RETURN_END", placed=0, reason="all_deduped")
            return

        def _prio(it: dict) -> int:
            fam = self._item_slot_family(it) or ""
            if fam == "weapon":
                return 0
            if fam == "offhand":
                return 1
            if fam == "ring":
                return 2
            return 9

        uniq.sort(key=_prio)

        def _can_use_cell(rc: tuple[int, int]) -> bool:
            try:
                r, c = int(rc[0]), int(rc[1])
            except Exception:
                return False
            if r < 0 or c < 0 or r >= ROWS or c >= COLS:
                return False
            return (r, c) not in (self._items or {})

        placed = 0

        if prefer_rc and uniq and _can_use_cell(prefer_rc):
            it0 = uniq.pop(0)
            try:
                self._place_item_into_cell(prefer_rc, it0)
                placed += 1
                self._inv_log("RETURN_PLACE_PREFER", rc=prefer_rc, item=self._inv_brief(it0))
            except Exception as e:
                self._inv_log("RETURN_PLACE_PREFER_FAIL", rc=prefer_rc, err=repr(e), item=self._inv_brief(it0))

        for it in uniq:
            pos = self._find_first_empty()
            if pos is None:
                self._inv_log("RETURN_NO_SPACE", item=self._inv_brief(it))
                continue
            try:
                self._place_item_into_cell(pos, it)
                placed += 1
                self._inv_log("RETURN_PLACE", rc=pos, item=self._inv_brief(it))
            except Exception as e:
                self._inv_log("RETURN_PLACE_FAIL", rc=pos, err=repr(e), item=self._inv_brief(it))

        try:
            self._update_capacity_message()
            self._update_capacity_indicator()
        except Exception:
            pass

        self._inv_log("RETURN_END", placed=placed, used=self._capacity_used())

    def _inv_find_existing_rc(self, it: dict):
        """Возвращает (rc, existing_item) если в инвентаре уже есть такой предмет."""
        if not isinstance(it, dict):
            return None
        gid = get_instance_guid(it)
        if gid:
            for rc, cur in (self._items or {}).items():
                if isinstance(cur, dict) and str(get_instance_guid(cur) or "") == str(gid):
                    return rc, cur
            return None

        # fallback только если GUID нет
        try:
            key = self._item_identity_key(it)
        except Exception:
            return None
        for rc, cur in (self._items or {}).items():
            if isinstance(cur, dict):
                try:
                    if self._item_identity_key(cur) == key:
                        return rc, cur
                except Exception:
                    pass
        return None

    def _move_item_or_swap(self, src: tuple[int, int], dst: tuple[int, int]) -> None:
        a = self._items.get(src)
        b = self._items.get(dst)

        self._inv_log(
            "MOVE_OR_SWAP_REQ",
            src=src,
            dst=dst,
            a=self._inv_brief(a),
            b=self._inv_brief(b),
        )

        a = self._items.pop(src, None)
        if a is None:
            self._inv_log("MOVE_OR_SWAP_ABORT", reason="src_empty", src=src, dst=dst)
            return
        b = self._items.pop(dst, None)

        self._place_item_into_cell(dst, a)

        if b is not None:
            self._place_item_into_cell(src, b)
            self._inv_log("MOVE_OR_SWAP_DONE", kind="swap", src=src, dst=dst)
        else:
            ico = self._cell_icons.get(src)
            if ico:
                ico.clear()
                ico.hide()
            self._inv_log("MOVE_OR_SWAP_DONE", kind="move", src=src, dst=dst)
