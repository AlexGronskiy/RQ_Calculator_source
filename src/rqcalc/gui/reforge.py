#reforge.py
from __future__ import annotations

import math
from typing import Callable, Optional, Dict, Any, List, Tuple
from PySide6.QtCore import Qt, QPoint, QSize, QEvent, QRect, Signal, QTimer, QDir, QFileInfo
from PySide6.QtGui import QPixmap, QIcon, QKeyEvent, QPainter, QImage, QColor
from PySide6.QtWidgets import QWidget, QLabel, QToolButton, QFrame, QGridLayout, QApplication, QHBoxLayout, QButtonGroup

# цвет/иконка печати – подтягиваем из stamp_window (как в тултипах)
from .stamp_window import STAMP_COLOR_META as _STAMP_COLOR_META
from .choose_menu_all import ChooseMenuAll, ChooseMenuConfig

# бонусные строки – тот же хелпер, что и в MainWindow
try:
    from .weapon_equipment_button import _render_bonus_lines as _render_bonus_lines_helper  # type: ignore
except Exception:
    _render_bonus_lines_helper = None



def _get_instance_guid(item: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(item, dict):
        return None
    return (
        item.get("InstanceGuid")
        or item.get("InstanceGUID")
        or item.get("Instance_Id")
    )

class UpgradeWindow(QWidget):
    """
    Окно улучшения предмета (рефорджа).

    — Прозрачное, без рамки; фон — PNG resources/upgrade_bg/upgrade_menu.png
    — Фиксированный размер 426×612
    — open_centered(owner): ApplicationModal + центрирование
    — Перетаскивание ЛКМ за «пустые» зоны
    — Esc/Enter — закрывают окно
    """

    on_reforge_request = Signal(dict)  # {"item": dict|None, "mat1": dict|None, "mat2": dict|None}

    WIN_W, WIN_H = 426, 612
    CLOSE_SIZE = QSize(24, 24)

    HELP_SIZE = QSize(24, 24)
    HELP_ICON_ACTIVE = "resources/helper_buttons/help_button_active.png"

    # Геометрия зон (x, y, w, h)
    GEO_ITEM   = (46,  68, 53, 53)
    GEO_MAT1   = (128, 140, 54, 54)
    GEO_MAT2   = (128, 216, 54, 54)
    GEO_RESULT = (46, 389, 53, 53)

    # Слоты, которые не имеет смысла показывать в «выборе надетых»
    EXCLUDE_SLOTS = {"costume", "ornament", "mount"}

    # Попап выбора надетых
    PICK_COLS = 4
    PICK_ICON_PX = 56

    # Иконки материалов
    PHILO_STONE_PATH = "resources/upgrade_bg/Purple_Philosopher_Stone.png"
    RUNE_SAVES_PATH  = "resources/upgrade_bg/Rune_Saves.png"
    RUNE_COLD_PATH   = "resources/upgrade_bg/Rune_Coldness.png"
    LEVEL_THRESHOLD  = 60

    # DEBUG-подсветка областей
    #SHOW_DEBUG_AREAS = False
    #DEBUG_FORCE_VISIBLE = False
    DEBUG_COLORS = {
        "item":   "rgba(46,204,113,110)",   # зелёный
        "mat1":   "rgba(155,89,182,110)",   # фиолетовый
        "mat2":   "rgba(52,152,219,110)",   # синий
        "result": "rgba(243,156,18,110)",   # оранжевый
    }

    # дефолтная картинка фоллбэк
    HELP_DEFAULT_IMG = "resources/upgrade_bg/help_upgrades/одежда_С_класс.png"

    # единый конфиг: пути картинок + геометрия кнопок
    HELP_UI_CONFIG_DEFAULT = {
        "base_size": [426, 612],  # координаты кнопок заданы под это «каноническое» окно

        "images": {
            # категории → классы → путь к PNG
            "armor": {  # Одежда
                "C": "resources/upgrade_bg/help_upgrades/одежда_С_класс.png",
                "B": "resources/upgrade_bg/help_upgrades/одежда_В_класс.png",
                "A": "resources/upgrade_bg/help_upgrades/одежда_А_класс.png",
            },
            "onehand": {  # Одноручка
                "C": "resources/upgrade_bg/help_upgrades/одноручка_С_класс.png",
                "B": "resources/upgrade_bg/help_upgrades/одноручка_В_класс.png",
                "A": "resources/upgrade_bg/help_upgrades/одноручка_А_класс.png",
            },
            "twohand": {  # Двуручка
                "C": "resources/upgrade_bg/help_upgrades/двуручка_С_класс.png",
                "B": "resources/upgrade_bg/help_upgrades/двуручка_В_класс.png",
                "A": "resources/upgrade_bg/help_upgrades/двуручка_А_класс.png",
            },
        },
        # 6 прямоугольных зон под кнопки (лево-право, верх-низ)
        # координаты под ваш макет 426×612; легко поменять в файле.
        "buttons": [
            {"id": "cat_armor", "rect": [18, 23, 124, 17], "set": {"kind": "armor"}},
            {"id": "cat_onehand", "rect": [148, 23, 126, 17], "set": {"kind": "onehand"}},
            {"id": "cat_twohand", "rect": [280, 23, 126, 17], "set": {"kind": "twohand"}},

            {"id": "gr_C", "rect": [18, 42, 124, 17], "set": {"grade": "C"}},
            {"id": "gr_B", "rect": [148, 42, 126, 17], "set": {"grade": "B"}},
            {"id": "gr_A", "rect": [280, 42, 126, 17], "set": {"grade": "A"}},
        ],

        # опционально — геометрия крестика в help-окне (если нужно двигать)
        "close": {"rect": [390, -2, 24, 24]},
    }
    # ---------- help_menu ----------
    DEBUG_REFORGE = True

    # === ДОБАВЬ ВНУТРЬ class UpgradeWindow(QWidget): ===

    def _is_descendant_obj(self, obj: object, root: Optional[object]) -> bool:
        """
        True если obj является root или находится внутри него по цепочке parent().
        Работает и для QWidget, и для QObject.
        """
        if obj is None or root is None:
            return False
        try:
            cur = obj
            while cur is not None:
                if cur is root:
                    return True
                # QObject.parent()
                cur = cur.parent() if hasattr(cur, "parent") else None
        except Exception:
            return False
        return False

    def _arm_global_mouse_swallow(self, *, count: int = 2, timeout_ms: int = 220) -> None:
        """
        Ставит временный глобальный фильтр на QApplication, чтобы поймать "replay" клика
        после закрытия popup и не дать ему улететь в MainWindow.
        """
        try:
            token = int(getattr(self, "_swallow_token", 0)) + 1
        except Exception:
            token = 1
        setattr(self, "_swallow_token", token)

        try:
            cur_left = int(getattr(self, "_swallow_global_left", 0))
        except Exception:
            cur_left = 0

        setattr(self, "_swallow_global_left", max(cur_left, int(count or 1)))

        app = QApplication.instance()
        if app is not None and not bool(getattr(self, "_app_evt_filter_installed", False)):
            try:
                app.installEventFilter(self)
                setattr(self, "_app_evt_filter_installed", True)
            except Exception:
                setattr(self, "_app_evt_filter_installed", False)

        # авто-сброс на случай, если replay не случится
        QTimer.singleShot(int(timeout_ms), lambda tok=token: self._disarm_global_mouse_swallow(token=tok))

    def _disarm_global_mouse_swallow(self, *, token: Optional[int] = None) -> None:
        """
        Снимает глобальный фильтр (если это актуальный token).
        """
        if token is not None:
            try:
                cur_tok = int(getattr(self, "_swallow_token", 0))
            except Exception:
                cur_tok = 0
            if token != cur_tok:
                return

        setattr(self, "_swallow_global_left", 0)

        app = QApplication.instance()
        if app is not None and bool(getattr(self, "_app_evt_filter_installed", False)):
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
        setattr(self, "_app_evt_filter_installed", False)

    def _dbg_alpha_stats_pm(self, pm: QPixmap, *, alpha_thr: int = 6) -> tuple[float, bool]:
        """
        Возвращает:
          - долю пикселей с alpha > alpha_thr (0..1)
          - есть ли вообще альфа-канал
        Это нужно чтобы понять "иконка прозрачная" или "её клипает/не рисует UI".
        """
        if not pm or pm.isNull():
            return 0.0, False

        try:
            img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
            w, h = img.width(), img.height()
            if w <= 0 or h <= 0:
                return 0.0, False

            has_alpha = img.hasAlphaChannel()
            total = w * h
            nonzero = 0

            # 64x64 = 4096, это очень дёшево
            for y in range(h):
                for x in range(w):
                    if img.pixelColor(x, y).alpha() > alpha_thr:
                        nonzero += 1

            return (nonzero / float(total)), has_alpha
        except Exception:
            return 0.0, False

    def _short_item(self, item: object) -> str:
        """
        Короткое представление предмета для лога (без простыней).
        """
        try:
            d = item if isinstance(item, dict) else dict(item)  # type: ignore
        except Exception:
            return f"type={type(item).__name__} repr={repr(item)[:200]}"

        def g(*keys):
            for k in keys:
                if k in d and d[k] is not None:
                    return d.get(k)
            return None

        keys_present = []
        for k in (
        "Id", "Equip_Id", "Equipment_Id", "Type_Id", "Icon_Image_Id", "Image_Id", "ToolTipImage_Id", "Slot_Id",
        "InstanceGuid"):
            if k in d:
                keys_present.append(k)

        return (
            f"type=dict keys={keys_present} "
            f"Id={g('Id')} Equip_Id={g('Equip_Id', 'Equipment_Id')} Type_Id={g('Type_Id')} "
            f"Icon_Image_Id={g('Icon_Image_Id')} Image_Id={g('Image_Id')} ToolTipImage_Id={g('ToolTipImage_Id', 'TooltipImage_Id')} "
            f"Slot_Id={g('Slot_Id', 'SlotId')} InstanceGuid={g('InstanceGuid', 'InstanceGUID', 'Instance_Id')}"
        )

    def _pick_selected_items_dict(self, parent: QWidget) -> tuple[str, Optional[dict]]:
        """
        Пытаемся найти правильный dict надетых предметов у parent.
        Выбираем лучший по количеству truthy-значений.
        Логируем все кандидаты.
        """
        candidates = [
            "_selected_items",
            "selected_items",
            "_equipped_items",
            "equipped_items",
            "_equipment_items",
            "equipment_items",
            "_wear_items",
            "wear_items",
            "_gear_items",
            "gear_items",
            "items_equipped",
            "_items_equipped",
            "equipped",
            "_equipped",
        ]

        method_candidates = [
            "get_equipped_items",
            "get_equipment_items",
            "get_wear_items",
            "get_selected_items",
        ]

        found: List[Tuple[str, dict, int, int]] = []  # (name, dict, len, truthy_count)

        def _as_dict(v) -> Optional[dict]:
            if v is None:
                return None
            if isinstance(v, dict):
                return v
            try:
                dv = dict(v)  # type: ignore
                return dv if isinstance(dv, dict) else None
            except Exception:
                return None

        def _truthy_count(d: dict) -> int:
            try:
                return sum(1 for _, it in d.items() if bool(it))
            except Exception:
                return 0

        # 1) атрибуты-словарики
        for name in candidates:
            try:
                v = getattr(parent, name, None)
            except Exception:
                v = None
            d = _as_dict(v)
            if d is None:
                continue
            found.append((name, d, len(d), _truthy_count(d)))

        # 2) методы, которые возвращают dict
        for mname in method_candidates:
            try:
                fn = getattr(parent, mname, None)
            except Exception:
                fn = None
            if not callable(fn):
                continue
            try:
                d = _as_dict(fn())
            except Exception:
                d = None
            if d is None:
                continue
            found.append((mname + "()", d, len(d), _truthy_count(d)))

        if not found:
            return "<none>", None

        # выбираем лучший: сначала truthy_count, потом len
        best = max(found, key=lambda t: (t[3], t[2]))
        return best[0], best[1]

    def _get_character_level(self) -> Optional[int]:
        """
        Пытаемся достать текущий уровень персонажа из parent (main_window),
        чтобы передавать его в _render_bonus_lines_helper(..., char_level=...).
        Если не нашли — вернём None (тогда armorBL=1.0 и формулы не искажаются).
        """
        p = self.parent()
        if p is None:
            return None

        def _to_int_or_none(v) -> Optional[int]:
            try:
                iv = int(v)
                return iv if iv > 0 else None
            except Exception:
                return None

        # 1) методы/поля
        for name in (
                "get_level", "get_character_level", "get_char_level",
                "character_level", "char_level", "level", "_level",
                "current_level", "_current_level",
        ):
            try:
                attr = getattr(p, name, None)
            except Exception:
                attr = None

            if callable(attr):
                try:
                    got = _to_int_or_none(attr())
                    if got is not None:
                        return got
                except Exception:
                    pass
            else:
                got = _to_int_or_none(attr)
                if got is not None:
                    return got

        # 2) spinbox-подобные виджеты (value())
        def _try_value(obj) -> Optional[int]:
            if obj is None:
                return None
            try:
                if hasattr(obj, "value") and callable(obj.value):
                    return _to_int_or_none(obj.value())
            except Exception:
                return None
            return None

        for name in (
                "level_spin", "levelSpin", "spin_level", "level_spinbox",
                "spinbox_level", "sb_level", "_level_spin", "_spin_level",
                "level_sb", "levelSB",
        ):
            try:
                got = _try_value(getattr(p, name, None))
                if got is not None:
                    return got
            except Exception:
                pass

        # 3) часто уровень лежит в p.ui.*
        ui = getattr(p, "ui", None)
        if ui is not None:
            for name in (
                    "level_spin", "levelSpin", "spin_level", "level_spinbox",
                    "spinbox_level", "sb_level",
            ):
                try:
                    got = _try_value(getattr(ui, name, None))
                    if got is not None:
                        return got
                except Exception:
                    pass

        return None

    # ---------- lifecycle ----------
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # ===== хелперы =====
        def uconnect(signal, slot):
            from PySide6.QtCore import Qt as _Qt
            try:
                signal.connect(slot, _Qt.ConnectionType.UniqueConnection)
            except Exception:
                signal.connect(slot)

        def mk_slot(parent: QWidget, name: str) -> QLabel:
            lab = QLabel(parent)
            lab.setObjectName(name)
            lab.setScaledContents(True)
            lab.setStyleSheet("background: transparent;")
            lab.setContextMenuPolicy(Qt.NoContextMenu)
            lab.setAttribute(Qt.WA_Hover, True)
            lab.installEventFilter(self)
            return lab

        # сохраним чтобы юзать в других местах класса (eventFilter и т.п.)
        #self._sys_beep = _sys_beep

        # ===== окно =====
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.CustomizeWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(self.WIN_W, self.WIN_H)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setStyleSheet("background: transparent;")

        # Фон
        self.bg_label = QLabel(self)
        self.bg_label.setGeometry(0, 0, self.WIN_W, self.WIN_H)
        self.bg_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._bg_pm = QPixmap("resources/upgrade_bg/upgrade_menu.png")
        if not self._bg_pm.isNull():
            self.bg_label.setPixmap(
                self._bg_pm.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            )

        # Кнопка закрытия (иконка только по hover)
        self.btn_close = QToolButton(self)
        self.btn_close.setObjectName("close_button")
        self.btn_close.setFixedSize(self.CLOSE_SIZE)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setStyleSheet(
            "QToolButton#close_button{background:transparent;border:none}"
            "QToolButton#close_button:hover{background:transparent}"
            "QToolButton#close_button:pressed{background:rgba(255,255,255,0.2);border-radius:4px}"
        )
        self.btn_close.installEventFilter(self)
        uconnect(self.btn_close.clicked, self.close)

        # Кнопка подсказки (слева от крестика)
        self.btn_help = QToolButton(self)
        self.btn_help.setObjectName("help_button")
        self.btn_help.setFixedSize(self.CLOSE_SIZE)
        self.btn_help.setCursor(Qt.PointingHandCursor)
        self.btn_help.setAutoRaise(True)
        self.btn_help.setFocusPolicy(Qt.NoFocus)
        self.btn_help.setStyleSheet(
            "QToolButton#help_button{background:transparent;border:none}"
            "QToolButton#help_button:hover{background:transparent}"
            "QToolButton#help_button:pressed{background:transparent}"
        )
        self.btn_help.installEventFilter(self)
        self.btn_help.move(393, 2)

        # Зоны-слоты
        self.slot_item = mk_slot(self, "slot_item")
        self.slot_mat1 = mk_slot(self, "slot_mat1")
        self.slot_mat2 = mk_slot(self, "slot_mat2")
        self.slot_result = mk_slot(self, "slot_result")

        # Статусная строка
        self.status_label = QLabel(self)
        self.status_label.setStyleSheet("color:rgba(255,255,255,0.92);font-size:12px;background:transparent")
        self.status_label.setAlignment(Qt.AlignCenter)

        # Попап выбора надетых
        self._pick_popup: Optional[QFrame] = None
        self._pick_grid: Optional[QGridLayout] = None
        self._make_pick_item_popup()
        # Универсальное меню выбора экипировки (24 слота)
        self._choose_menu_all: Optional[ChooseMenuAll] = ChooseMenuAll(self, config=ChooseMenuConfig())

        # Попап выбора уровня точки
        self._lvl_popup: Optional[QFrame] = None
        self._lvl_grid: Optional[QGridLayout] = None
        self._selected_forge_level: Optional[int] = None
        self._selected_forge_bonus: int = 0  # главный стат (как раньше)
        self._selected_forge_bonus_atk: int = 0  # отдельный бонус к атаке
        self._selected_forge_bonus_def: int = 0  # отдельный бонус к защите
        self._selected_forge_allstat: int = 0
        self._selected_forge_hp: int = 0
        self._make_level_popup()

        # Данные/стейт
        self._image_loader: Optional[Callable[[int], Optional[bytes]]] = None
        self._item: Optional[Dict[str, Any]] = None
        self._mat1: Optional[Dict[str, Any]] = None
        self._mat2: Optional[Dict[str, Any]] = None
        self._result_payload: Optional[Dict[str, Any]] = None
        self._item_source_slot: Optional[str] = None  # из какого слота взяли предмет
        # к какому именно экземпляру предмета сейчас привязано окно
        self._item_instance_guid: str | None = None

        # --- element badge cache ---
        self._element_badge_cache: Dict[int, QPixmap] = {}

        # Перетаскивание окна
        self._dragging = False
        self._drag_offset = QPoint()
        self._drag_blockers: set[QWidget] = set()
        self._rebuild_drag_blockers()

        # Размещение
        self._place_slots()

        # Материалы по умолчанию скрыты
        self.slot_mat1.hide()
        self.slot_mat2.hide()

        # Кэши БД
        self._db_cols_cache: Dict[str, set[str]] = {}
        self._forge_tbl_cache: Optional[str] = None

        # Разрешение выбора предмета только из попапа
        self._require_pick_from_popup = True

        # Единоразовый «блым» при открытии окна (как системное уведомление)
        #QTimer.singleShot(0, lambda: self._sys_beep("asterisk"))

    # ---------- Публичный API ----------
    def _element_id_for_item(self, item: Optional[Dict[str, Any]]) -> Optional[int]:
        """
        Возвращает Element_Id предмета.

        Источники (по приоритету):
          1) прямое поле предмета Element_Id / ElementId (если > 0)
          2) если стихия задана КАРТОЙ (item["_cards"]/cards/Cards):
                - пытаемся взять Element_Id из CardType (через Card.Type_Id или напрямую по CardType_Id)
          3) если ничего не нашли -> None
        """
        if not isinstance(item, dict):
            return None

        def _toi(v) -> int:
            try:
                return int(v)
            except Exception:
                try:
                    return int(float(str(v).strip()))
                except Exception:
                    return 0

        # 1) прямое поле элемента на предмете
        for k in ("Element_Id", "ElementId", "Element_ID"):
            v = item.get(k)
            iv = _toi(v)
            if iv > 0:
                return iv

        # 2) попытка вывести элемент из вставленных карт
        cards_raw = item.get("_cards") or item.get("cards") or item.get("Cards")
        if not cards_raw:
            return None

        # нормализуем в список
        if isinstance(cards_raw, dict):
            entries = list(cards_raw.values())
        elif isinstance(cards_raw, (list, tuple, set, frozenset)):
            entries = list(cards_raw)
        else:
            entries = [cards_raw]

        conn = None
        try:
            conn = self._db_conn()
        except Exception:
            conn = None
        if conn is None:
            return None

        def _extract_card_id_and_type_id(ent) -> tuple[int, int]:
            """
            Возвращает (card_id, card_type_id).
            card_type_id может прийти напрямую (если в ent уже есть Type_Id/ CardType_Id),
            иначе будем пробовать через Card.Id.
            """
            card_id = 0
            card_type_id = 0

            if ent is None:
                return 0, 0

            # tuple/list: берём первый элемент (как часто делают в проекте)
            if isinstance(ent, (tuple, list)):
                ent = ent[0] if ent else None
                if ent is None:
                    return 0, 0

            if isinstance(ent, dict):
                card_id = _toi(
                    ent.get("Id")
                    or ent.get("Card_Id")
                    or ent.get("CardId")
                    or ent.get("card_id")
                )
                card_type_id = _toi(
                    ent.get("CardType_Id")
                    or ent.get("CardTypeId")
                    or ent.get("Type_Id")
                    or ent.get("TypeId")
                )
                return card_id, card_type_id

            # просто int/str
            card_id = _toi(ent)
            return card_id, 0

        # пробуем по каждой карте; находим первый валидный Element_Id
        for ent in entries:
            card_id, card_type_id = _extract_card_id_and_type_id(ent)

            # 2a) если знаем CardType_Id -> CardType.Element_Id
            if card_type_id > 0:
                row = None
                try:
                    row = conn.execute(
                        "SELECT Element_Id FROM CardType WHERE Id=? LIMIT 1",
                        (int(card_type_id),),
                    ).fetchone()
                except Exception:
                    row = None

                if row:
                    try:
                        eid = _toi(row["Element_Id"] if hasattr(row, "keys") else row[0])
                    except Exception:
                        eid = 0
                    if eid > 0:
                        return eid

            # 2b) если знаем Card.Id -> Card.Type_Id -> CardType.Element_Id
            if card_id > 0:
                row = None
                try:
                    row = conn.execute(
                        "SELECT ct.Element_Id "
                        "FROM Card c "
                        "JOIN CardType ct ON ct.Id=c.Type_Id "
                        "WHERE c.Id=? LIMIT 1",
                        (int(card_id),),
                    ).fetchone()
                except Exception:
                    row = None

                if row:
                    try:
                        eid = _toi(row["Element_Id"] if hasattr(row, "keys") else row[0])
                    except Exception:
                        eid = 0
                    if eid > 0:
                        return eid

        return None

    def _element_badge_image_id_for_item(self, item: Optional[Dict[str, Any]]) -> Optional[int]:
        """
        Достаёт Image.Id для бейджа элемента.

        Логика:
          1) если в item явно лежит ToolTipImage_Id -> берём его
          2) иначе пытаемся получить Element_Id (включая вывод из карт через _element_id_for_item)
             и по нему берём картинку из CardType (ToolTipImage_Id, иначе Image_Id)
          3) фоллбэк: если в item лежит CardType_Id/CardTypeId -> пробуем по нему
        """
        if not isinstance(item, dict):
            return None

        def _toi(v) -> int:
            try:
                return int(v)
            except Exception:
                try:
                    return int(float(str(v).strip()))
                except Exception:
                    return 0

        direct = _toi(
            item.get("ToolTipImage_Id")
        )
        if direct > 0:
            return direct

        # ключевое: берём Element_Id НЕ только из поля предмета, но и из карт
        eid = None
        try:
            eid = self._element_id_for_item(item)
        except Exception:
            eid = None

        if eid is not None and int(eid or 0) > 0:
            return self._db_element_badge_image_id(int(eid))

        ct_id = _toi(item.get("CardType_Id") or item.get("CardTypeId") or 0)
        if ct_id > 0:
            return self._db_element_badge_image_id(int(ct_id))

        return None

    def _db_element_badge_image_id(self, cardtype_or_element_id: int) -> Optional[int]:
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
                    left = min(left, x);
                    right = max(right, x)
                    top = min(top, y);
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
        Минимально: если есть альфа — кроп по альфе (убираем лишние поля).
        Если альфы нет — оставляем как есть (чтобы не сделать хуже).
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

    def _load_element_badge_pixmap(self, element_id: int, item: Optional[Dict[str, Any]] = None) -> Optional[QPixmap]:
        if not element_id:
            return None

        cached = self._element_badge_cache.get(int(element_id))
        if isinstance(cached, QPixmap) and not cached.isNull():
            return cached

        if not self._image_loader:
            return None

        img_id = None
        if item:
            img_id = self._element_badge_image_id_for_item(item)
        if img_id is None:
            img_id = self._db_element_badge_image_id(int(element_id))

        if not img_id:
            return None

        try:
            raw = self._image_loader(int(img_id))
        except Exception:
            raw = None
        if not raw:
            return None

        pm = QPixmap()
        if not pm.loadFromData(raw) or pm.isNull():
            return None

        pm = self._sanitize_badge_pixmap(pm)
        # кешируем только успех
        if not pm.isNull():
            self._element_badge_cache[int(element_id)] = pm
        return pm if not pm.isNull() else None

    def _compose_with_element_badge(self, base_pm: QPixmap, canvas_size: QSize, element_id: int,
                                    item: Dict[str, Any]) -> QPixmap:
        """
        Базовая иконка + бейдж элемента снизу-слева.
        Бейдж рисуем как 12x16 относительно "клетки" 54.
        """
        canvas = QPixmap(canvas_size)
        canvas.fill(Qt.transparent)

        p = QPainter(canvas)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # base icon (центр)
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
                m = max(1, int(base * (4.0 / 54.0)))
                badge_scaled = badge.scaled(bw, bh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

                dy = int(base * (2.0 / 54.0))  # сдвиг вниз на ~2px в дизайне 54
                by = canvas.height() - badge_scaled.height() - m + dy

                # чтобы не вылез за низ (иначе обрежется):
                by = min(by, canvas.height() - badge_scaled.height())
                bx = m
                p.drawPixmap(bx, by, badge_scaled)

        p.end()
        return canvas

    def _ei_call(self, fn, **kwargs) -> bool:
        """
        Вызывает метод equip_info, передавая только те kwargs, которые он реально принимает.
        Возвращает True если вызов успешно прошёл.
        """
        if not callable(fn):
            return False

        import inspect
        try:
            sig = inspect.signature(fn)
        except Exception:
            # если сигнатура недоступна — пробуем как есть
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

    def _build_bonus_lines_for_tip(self, payload: dict) -> Optional[list[str]]:
        """
        Бонусные строки как в main:
        - берём equip_id в т.ч. из payload["Id"] (контракт weapon_equipment_button)
        - вызываем _render_bonus_lines_helper(conn, equip_id, char_level=уровень_перса)
        - чистим дубли/служебные строки
        """
        p = self.parent()
        if not p:
            return None

        if not _render_bonus_lines_helper:
            return None

        data = getattr(p, "data", None)
        conn = getattr(data, "conn", None)
        if conn is None:
            return None

        # equip_id: важный фикс — учитываем "Id"
        equip_id = (
                payload.get("Equip_Id")
                or payload.get("Equipment_Id")
                or payload.get("EquipId")
                or payload.get("EquipmentId")
                or payload.get("Id")
        )
        try:
            equip_id_i = int(equip_id) if equip_id is not None else 0
        except Exception:
            equip_id_i = 0

        if equip_id_i <= 0:
            return None

        # char_level: уровень персонажа (для armorBL / MulFormula_Id=16)
        char_lvl = self._get_character_level()

        try:
            bonus_lines = _render_bonus_lines_helper(conn, int(equip_id_i), char_level=char_lvl)
        except Exception:
            bonus_lines = None

        if not bonus_lines:
            return None

        import re

        # вычищаем “встроенные” строки статов (которые часто рисуются ещё и самим equip_info)
        STAT_RE = re.compile(r"^\s*(атака|защита)\s*:\s*\d+\s*(?:\+\s*\d+)?\s*$", re.I)
        AS_RE = re.compile(r"^\s*(?:as|attack\s*speed|скорость\s*атаки)\s*:\s*[\d.,]+\s*(?:\+\s*[\d.,]+)?\s*$", re.I)
        DPS_RE = re.compile(r"^\s*(?:dps|урон\s*(?:в\s*)?секунду)\s*:\s*[\d.,]+\s*(?:\+\s*[\d.,]+)?\s*$", re.I)

        def norm(s: str) -> str:
            s = str(s or "").replace("\u00a0", " ").strip()
            s = re.sub(r"\s+", " ", s)
            return s.lower()

        cleaned: list[str] = []
        seen = set()

        for s in bonus_lines:
            s = str(s or "").strip()
            if not s:
                continue

            if STAT_RE.match(s) or AS_RE.match(s) or DPS_RE.match(s):
                continue

            k = norm(s)
            if k in seen:
                continue
            seen.add(k)
            cleaned.append(s)

        return cleaned or None

    def open_centered(self, owner: Optional[QWidget] = None) -> None:
        """Открыть окно рефоржа без Qt-модальности. Блокировку делает shield из MainWindow."""

        # 1) закрыть попапы/ховеры, чтобы не было мусора при переоткрытии
        self._hide_pick_item_popup()
        self._hide_level_popup()
        self._end_all_hovers()

        # 2) owner может быть дочерним виджетом — нам нужен верхний window()
        host = None
        if owner is not None:
            try:
                host = owner.window()
            except Exception:
                host = owner

        # 3) если есть host — делаем его родителем
        if host is not None and host is not self.parent():
            self.setParent(host, self.windowFlags())

        # 4) окно всегда стартует пустым
        self._clear_reforge_ui()

        # ВАЖНО:
        # Не используем WindowModal/ApplicationModal.
        # Блокировку кликов делает shield в MainWindow.
        # Qt-модальность даёт системный звук Windows при клике вне окна.
        try:
            self.setWindowModality(Qt.NonModal)
        except Exception:
            pass

        try:
            if hasattr(self, "setModal"):
                self.setModal(False)
        except Exception:
            pass

        try:
            self.setEnabled(True)
        except Exception:
            pass

        try:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        except Exception:
            pass

        try:
            self.setWindowOpacity(1.0)
        except Exception:
            pass

        # 5) центрирование
        if host is not None:
            og = host.frameGeometry()
            x = og.x() + (og.width() - self.width()) // 2
            y = og.y() + (og.height() - self.height()) // 2
        else:
            scr_obj = self.screen() or QApplication.primaryScreen()
            scr = scr_obj.availableGeometry() if scr_obj else QRect(0, 0, 1920, 1080)
            x = scr.x() + (scr.width() - self.width()) // 2
            y = scr.y() + (scr.height() - self.height()) // 2

        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

        try:
            QApplication.setActiveWindow(self)
        except Exception:
            pass

    def _as_plain_dict(self, v) -> Optional[Dict[str, Any]]:
        """Надёжно приводит QVariantMap/sqlite3.Row/Mapping к обычному dict."""
        if v is None:
            return None
        if isinstance(v, dict):
            return dict(v)
        try:
            return dict(v)
        except Exception:
            return None

    def set_image_loader(self, loader: Callable[[int], Optional[bytes]]) -> None:
        self._image_loader = loader

    def set_item(
            self,
            item: Optional[Dict[str, Any]],
            slot_key: Optional[str] = None,
            *,
            _user_pick: bool = False
    ) -> None:
        """
        Устанавливает предмет для рефоржа.

        Требование:
        - если self._require_pick_from_popup = True:
            * предмет можно установить ТОЛЬКО после выбора в попапе (_user_pick=True)
            * внешние set_item(item!=None) игнорируются
            * set_item(None) разрешён (очистка)
        """

        # Жёсткий запрет на автоподстановку: только пользовательский выбор из попапа
        if self._require_pick_from_popup and (not _user_pick) and (item is not None):
            return

        self._item_source_slot = str(slot_key) if slot_key else None
        self._selected_forge_level = None
        self._selected_forge_bonus = 0
        self._selected_forge_bonus_atk = 0
        self._selected_forge_bonus_def = 0
        self._selected_forge_allstat = 0
        self._selected_forge_hp = 0
        self._result_payload = None

        # делаем локальную копию
        self._item = dict(item) if isinstance(item, dict) else None

        # иконка исходного предмета (или очистка, если None)
        self._set_label_icon_from_item(self.slot_item, self._item)

        # результат пока пустой
        self.slot_result.clear()

        # материалы прячем
        self.slot_mat1.hide()
        self.slot_mat2.hide()
        self._mat1 = None
        self._mat2 = None

        self._update_reforge_enabled()

    def set_materials(self, mat1: Optional[Dict[str, Any]], mat2: Optional[Dict[str, Any]]) -> None:
        self._mat1 = mat1
        self._mat2 = mat2
        self._set_label_icon_from_item(self.slot_mat1, mat1)
        self._set_label_icon_from_item(self.slot_mat2, mat2)
        self._update_reforge_enabled()

    def set_result_icon(self, pm: Optional[QPixmap]) -> None:
        if not pm or pm.isNull():
            self.slot_result.clear()
        else:
            self._set_pixmap_to_label(self.slot_result, pm)

    def set_result_data(self, result: Optional[Dict[str, Any]]) -> None:
        self._result_payload = result

    def set_status(self, text: str) -> None:
        self.status_label.setText(text or "")

    # ---------- layout / debug ----------

    def _place_slots(self) -> None:
        # крестик
        self.btn_close.move(390, 2)

        # help слева от крестика с зазором 4px
        self.btn_help.move(353, 2)

        # зоны
        self.slot_item.setGeometry(*self.GEO_ITEM)
        self.slot_mat1.setGeometry(*self.GEO_MAT1)
        self.slot_mat2.setGeometry(*self.GEO_MAT2)
        self.slot_result.setGeometry(*self.GEO_RESULT)

        # статус
        self.status_label.setGeometry(12, self.height() - 26, self.width() - 24, 18)

    # ---------- Попап выбора надетых ----------

    def _make_pick_item_popup(self) -> None:
        self._pick_popup = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        self._pick_popup.setObjectName("pickPopup")

        # ВАЖНО: чтобы после закрытия попапа Qt не "перекидывал" клик в окно под ним
        self._pick_popup.setAttribute(Qt.WA_NoMouseReplay, True)

        # ВАЖНО: убираем padding у QToolButton — он реально может убивать отрисовку иконки,
        # когда высота/ширина кнопки получаются на грани.
        self._pick_popup.setStyleSheet(
            """
            QFrame#pickPopup {
                background: rgba(15,15,18,0.94);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 10px;
            }
            QToolButton {
                background: rgba(255,255,255,0.05);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 8px;
                padding: 0px; /* КРИТИЧНО */
            }
            QToolButton:hover {
                border-color: rgba(255,255,255,0.35);
                background: rgba(255,255,255,0.08);
            }
            QToolButton::menu-indicator { image: none; }
            """
        )
        self._pick_popup.installEventFilter(self)
        self._pick_popup.hide()

        self._pick_grid = QGridLayout(self._pick_popup)
        self._pick_grid.setContentsMargins(10, 10, 10, 10)
        self._pick_grid.setHorizontalSpacing(8)
        self._pick_grid.setVerticalSpacing(8)

    @staticmethod
    def _clear_layout(layout: QGridLayout) -> None:
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _rebuild_pick_item_popup(self) -> None:
        if not (self._pick_popup and self._pick_grid):
            return

        self._clear_layout(self._pick_grid)

        parent = self.parent()
        # выбрать лучший dict экипировки
        source_name, selected = self._pick_selected_items_dict(parent)

        items: List[Tuple[str, dict]] = []
        for slot_key, it in selected.items():
            excluded = slot_key in self.EXCLUDE_SLOTS
            truthy = bool(it)
            raw_type = type(it).__name__
            if excluded or not it:
                continue
            d = self._as_plain_dict(it)
            if not d:
                continue
            try:
                keys = list(d.keys())
            except Exception:
                keys = []

            items.append((str(slot_key), d))

        items.sort(key=lambda t: str(t[0]))

        cols = max(1, int(self.PICK_COLS))
        icon_px = int(self.PICK_ICON_PX)

        # фикс размер кнопки под иконку + рамка
        btn_w = icon_px + 10
        btn_h = icon_px + 10
        margin = max(0, (btn_w - icon_px) // 2)

        for idx, (slot_key, item) in enumerate(items):
            r, c = divmod(idx, cols)
            #self._dbg("PICK", f"[{idx}] build btn slot={slot_key} item_keys={list(item.keys())}")

            btn = QToolButton(self._pick_popup)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setAutoRaise(True)
            btn.setFocusPolicy(Qt.NoFocus)

            # ВАЖНО: НЕ используем btn.setIcon(...) как основной способ отображения
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            btn.setFixedSize(QSize(btn_w, btn_h))
            btn.setIcon(QIcon())  # специально пусто

            # Лейбл-иконка поверх кнопки (клик сквозь него)
            icon_lab = QLabel(btn)
            icon_lab.setObjectName("pick_icon_label")
            icon_lab.setGeometry(margin, margin, icon_px, icon_px)
            icon_lab.setScaledContents(True)
            icon_lab.setAlignment(Qt.AlignCenter)
            icon_lab.setStyleSheet("background: transparent; border: none;")
            icon_lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)

            # 1) id картинки
            img_id = self._resolve_image_id(item)

            pm = None
            if img_id:
                try:
                    pm = self._load_pm_by_id(int(img_id))
                except Exception:
                    pm = None

            if pm and not pm.isNull():
                ratio, has_alpha = self._dbg_alpha_stats_pm(pm)

                eid = self._element_id_for_item(item) or 0
                if eid:
                    final_pm = self._compose_with_element_badge(pm, QSize(icon_px, icon_px), int(eid), item)
                else:
                    final_pm = pm.scaled(icon_px, icon_px, Qt.KeepAspectRatio, Qt.SmoothTransformation)

                icon_lab.setPixmap(final_pm)

                # дебаг: проверяем, что QLabel реально держит pixmap
                try:
                    lp = icon_lab.pixmap()
                except Exception:
                    pass

            # мета для клика/тултипа (события ловим на кнопке)
            btn.setProperty("slot_key", slot_key)
            btn.setProperty("item_dict", dict(item))
            btn.setProperty("_armed_pick", False)

            btn.installEventFilter(self)
            self._pick_grid.addWidget(btn, r, c)

        self._pick_popup.adjustSize()
        #self._dbg("PICK", f"rebuild done. widgets={len(items)} popup_sizeHint={self._pick_popup.sizeHint()}")
        self._rebuild_drag_blockers()

    def _show_pick_item_popup(self) -> None:
        """
        Новый формат: вместо старого QFrame-попапа используем ChooseMenuAll (equip_choose.png, 24 слота).
        """
        anchor = self.slot_item
        if not anchor:
            return

        # инстанс меню
        cm = getattr(self, "_choose_menu_all", None)
        if cm is None:
            try:
                self._choose_menu_all = ChooseMenuAll(self, config=ChooseMenuConfig())
                cm = self._choose_menu_all
            except Exception:
                cm = None

        # fallback: старый попап
        if cm is None:
            self._rebuild_pick_item_popup()

            hint = self._pick_popup.sizeHint()
            tl = anchor.mapToGlobal(anchor.rect().bottomLeft())
            x, y = tl.x(), tl.y() + 6

            scr = (
                self.window().screen().availableGeometry()
                if self.window()
                else QApplication.primaryScreen().availableGeometry()
            )

            if x + hint.width() > scr.right() - 6:
                x = max(scr.left() + 6, scr.right() - hint.width() - 6)
            if y + hint.height() > scr.bottom() - 6:
                y = anchor.mapToGlobal(anchor.rect().topLeft()).y() - hint.height() - 6

            self._pick_popup.move(x, y)
            self._pick_popup.show()
            self._pick_popup.raise_()
            self._pick_popup.activateWindow()
            return

        # собрать предметы (как в _rebuild_pick_item_popup, только без создания кнопок)
        parent = self.parent()
        _source_name, selected = self._pick_selected_items_dict(parent)

        items: List[Tuple[str, dict]] = []
        for slot_key, it in (selected or {}).items():
            if slot_key in self.EXCLUDE_SLOTS:
                continue
            if not it:
                continue
            d = self._as_plain_dict(it)
            if not d:
                continue
            items.append((str(slot_key), d))

        items.sort(key=lambda t: str(t[0]))

        def _icon_provider(it: dict) -> Optional[QPixmap]:
            img_id = None
            try:
                img_id = self._resolve_image_id(it)
            except Exception:
                img_id = None

            pm = None
            if img_id:
                try:
                    pm = self._load_pm_by_id(int(img_id))
                except Exception:
                    pm = None

            if not pm or pm.isNull():
                return None

            canvas = QSize(50, 50)
            try:
                eid = int(self._element_id_for_item(it) or 0)
            except Exception:
                eid = 0

            if eid:
                try:
                    return self._compose_with_element_badge(pm, canvas, int(eid), it)
                except Exception:
                    pass

            return pm.scaled(canvas, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        def _on_pick(sk: str, it: dict) -> None:
            # применяем выбор
            self.set_item(it, slot_key=sk, _user_pick=True)
            self._refresh_mats_for_item()

            # гасим возможный replay release/доп. клики
            self._arm_global_mouse_swallow(count=3, timeout_ms=260)

            # закрываем меню (и тултип)
            self._hide_pick_item_popup()

        def _on_hover_enter(cell: QWidget, sk: str, it: dict) -> None:
            tip_item = dict(it or {})
            tip_item["slot_key"] = str(sk)
            self._show_item_tip(cell, tip_item)

        def _on_hover_leave(cell: QWidget) -> None:
            self._tip_leave_for(cell)  # type: ignore[arg-type]

        cm.open_for(
            anchor_widget=anchor,
            items=items,
            icon_provider=_icon_provider,
            on_pick=_on_pick,
            on_hover_enter=_on_hover_enter,
            on_hover_leave=_on_hover_leave,
        )

    # === ЗАМЕНИ ЦЕЛИКОМ функцию _hide_pick_item_popup ===

    def _hide_pick_item_popup(self) -> None:
        # старый попап
        pp = getattr(self, "_pick_popup", None)
        if pp and pp.isVisible():
            pp.hide()

        # новое меню
        cm = getattr(self, "_choose_menu_all", None)
        if cm is not None and cm.isVisible():
            try:
                cm.hide()
            except Exception:
                pass

        # закрываем тултип
        p = self.parent()
        ei = getattr(p, "equip_info", None) if p else None
        if ei:
            try:
                last = getattr(self, "_last_tip_anchor", None)
                if last is not None:
                    ei.end_hover(last)
            except Exception:
                pass

        self._last_tip_anchor = None

    # ---------- Попап уровней точки ----------
    def _make_level_popup(self) -> None:
        self._lvl_popup = QFrame(self, Qt.Popup | Qt.FramelessWindowHint)
        self._lvl_popup.setObjectName("forgeLevelPopup")

        # тоже самое: не пробрасывать клик "сквозь" попап
        self._lvl_popup.setAttribute(Qt.WA_NoMouseReplay, True)

        self._lvl_popup.setStyleSheet(
            """
            QFrame#forgeLevelPopup {
                background: rgba(15,15,18,0.96);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 8px;
            }
            QLabel[levelCol] {
                color:#e6d27a;
            }
            QLabel[valueCol] {
                color:#f0f0f0;
            }
        """
        )
        self._lvl_popup.installEventFilter(self)
        self._lvl_popup.hide()

        self._lvl_grid = QGridLayout(self._lvl_popup)
        self._lvl_grid.setContentsMargins(8, 8, 8, 8)
        self._lvl_grid.setHorizontalSpacing(16)
        self._lvl_grid.setVerticalSpacing(2)

    def _rebuild_level_popup(self) -> None:
        if not (self._lvl_popup and self._lvl_grid and self._item):
            return

        self._clear_layout(self._lvl_grid)

        # ===== базовые атака/защита из Equipment =====
        base_atk = 0.0
        base_def = 0.0

        conn = self._db_conn()
        if conn:
            equip_id = (
                    self._item.get("Equip_Id")
                    or self._item.get("Equipment_Id")
                    or self._item.get("Id")
            )
            try:
                equip_id = int(equip_id)
            except Exception:
                equip_id = 0

            if equip_id:
                has_atk = self._db_has_col("Equipment", "Attack")
                has_def = self._db_has_col("Equipment", "Defense")

                cols = []
                if has_atk:
                    cols.append("Attack")
                if has_def:
                    cols.append("Defense")

                if cols:
                    sql = f"SELECT {', '.join(cols)} FROM Equipment WHERE Id=? LIMIT 1"
                    try:
                        row = conn.execute(sql, (equip_id,)).fetchone()
                    except Exception:
                        row = None

                    if row:
                        if hasattr(row, "keys"):
                            if has_atk:
                                try:
                                    base_atk = float(row["Attack"] or 0)
                                except Exception:
                                    base_atk = 0.0
                            if has_def:
                                try:
                                    base_def = float(row["Defense"] or 0)
                                except Exception:
                                    base_def = 0.0
                        else:
                            idx = 0
                            if has_atk:
                                try:
                                    base_atk = float(row[idx] or 0)
                                except Exception:
                                    base_atk = 0.0
                                idx += 1
                            if has_def and idx < len(row):
                                try:
                                    base_def = float(row[idx] or 0)
                                except Exception:
                                    base_def = 0.0

        rows = self._load_forge_rows()
        if not rows:
            lbl = QLabel("Нет уровней точки", self._lvl_popup)
            lbl.setStyleSheet("color:#cfe6a5; padding:4px 8px;")
            self._lvl_grid.addWidget(lbl, 0, 0)
            self._lvl_popup.adjustSize()
            return

        # Ограничение для предметов класса C: максимум +10
        grade = self._determine_item_grade(self._item or {})
        if str(grade).upper() == "C":
            rows = [r for r in rows if int(r.get("level") or 0) <= 10]

        if not rows:
            lbl = QLabel("Нет уровней точки для этого предмета", self._lvl_popup)
            lbl.setStyleSheet("color:#cfe6a5; padding:4px 8px;")
            self._lvl_grid.addWidget(lbl, 0, 0)
            self._lvl_popup.adjustSize()
            return

        is_weapon = self._is_weapon_item(self._item)

        # Какой стат считаем "главным" для ForgeBonus.
        # ВАЖНО:
        # - предмет экипировки с Defense = 0 всё равно можно улучшать;
        # - бонус к защите у него будет 0;
        # - HP-бонус всё равно должен отображаться и применяться.
        if is_weapon and base_atk > 0:
            primary_kind = "attack"
        elif base_atk > 0:
            primary_kind = "attack"
        elif base_def > 0:
            primary_kind = "defense"
        elif not is_weapon:
            primary_kind = "defense"
        else:
            primary_kind = ""

        BASE_ROW_STYLE = (
            "background: rgba(0,0,0,0.35);"
            "border-radius:4px;"
            "border:1px solid rgba(0,0,0,0);"
        )
        HOVER_ROW_STYLE = (
            "background: rgba(0,0,0,0.45);"
            "border-radius:4px;"
            "border:1px solid rgba(255,255,255,0.22);"
        )

        for idx, row in enumerate(rows):
            lvl = int(row.get("level") or 0)

            atk_coef = float(row.get("attack") or 0.0)
            def_coef = float(row.get("defense") or 0.0)
            all_stat = int(row.get("all") or 0)

            # Бонусы по каждому стату.
            # Если база 0 — бонус остаётся 0, но строку уровня НЕ скрываем.
            bonus_atk = int(math.ceil(base_atk * atk_coef)) if (base_atk > 0 and atk_coef) else 0
            bonus_def = int(math.ceil(base_def * def_coef)) if (base_def > 0 and def_coef) else 0

            # Главный бонус для ForgeBonus.
            if primary_kind == "attack":
                main_bonus = bonus_atk
            elif primary_kind == "defense":
                main_bonus = bonus_def
            else:
                main_bonus = bonus_atk or bonus_def

            # HP бонус — только НЕ для оружия.
            hp_bonus = 0
            if not is_weapon:
                hp_bonus = self._hp_bonus_for_item_and_level(self._item, lvl)

            roww = QWidget(self._lvl_popup)
            roww.setCursor(Qt.PointingHandCursor)
            roww.setProperty("forge_level", lvl)
            roww.setProperty("forge_bonus", int(main_bonus or 0))
            roww.setProperty("forge_allstat", int(all_stat or 0))

            # Реальные отдельные бонусы по каждому стату.
            roww.setProperty("forge_bonus_atk", int(bonus_atk or 0))
            roww.setProperty("forge_bonus_def", int(bonus_def or 0))

            roww.setProperty("_base_style", BASE_ROW_STYLE)
            roww.setProperty("_hover_style", HOVER_ROW_STYLE)

            roww.setStyleSheet(BASE_ROW_STYLE)
            roww.installEventFilter(self)

            hl = QHBoxLayout(roww)
            hl.setContentsMargins(4, 2, 4, 2)
            hl.setSpacing(10)

            lbl_lvl = QLabel(f"+{lvl}", roww)
            lbl_lvl.setProperty("levelCol", True)
            lbl_lvl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

            lines: List[str] = []

            if bonus_atk > 0:
                lines.append(f"+{bonus_atk} к атаке")
            if bonus_def > 0:
                lines.append(f"+{bonus_def} к защите")

            if (not is_weapon) and hp_bonus > 0:
                lines.append(f"+{hp_bonus} к здоровью")

            if all_stat > 0:
                lines.append(
                    f"+{all_stat} ко всем параметрам" if is_weapon else f"+{all_stat} ко всем атрибутам"
                )

            if not lines:
                lines.append("Без бонусов")

            lbl_val = QLabel("\n".join(lines), roww)
            lbl_val.setProperty("valueCol", True)
            lbl_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            hl.addWidget(lbl_lvl, 0)
            hl.addWidget(lbl_val, 1)

            self._lvl_grid.addWidget(roww, idx, 0)

        self._lvl_popup.adjustSize()

    def _show_level_popup(self) -> None:
        if not self._item or not self._lvl_popup:
            return
        self._rebuild_level_popup()

        anchor = self.slot_mat1
        if not anchor or not anchor.isVisible():
            return

        hint = self._lvl_popup.sizeHint()
        tl = anchor.mapToGlobal(anchor.rect().bottomRight())
        x = tl.x() + 6
        y = tl.y()

        scr = (
            self.window().screen().availableGeometry()
            if self.window()
            else QApplication.primaryScreen().availableGeometry()
        )
        if x + hint.width() > scr.right() - 6:
            x = max(scr.left() + 6, scr.right() - hint.width() - 6)
        if y + hint.height() > scr.bottom() - 6:
            y = anchor.mapToGlobal(anchor.rect().topRight()).y() - hint.height() - 6

        self._lvl_popup.move(x, y)
        self._lvl_popup.show()
        self._lvl_popup.raise_()
        self._lvl_popup.activateWindow()

    def _hide_level_popup(self) -> None:
        if self._lvl_popup and self._lvl_popup.isVisible():
            self._lvl_popup.hide()

    # ---------- Печати ----------

    @staticmethod
    def _to_int(v, default: int = 0) -> int:
        try:
            return int(v)
        except Exception:
            return default

    def _saved_stamp_raw_for_item(self, item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Находим печать для предмета:
        0) сначала inline в самом item ("Stamp"/"stamp"),
        1) потом по InstanceGuid в кэше родителя (_applied_stamps),
        2) потом через parent.data.get_item_stamp_by_instance(inst).
        """
        if not isinstance(item, dict) or not item:
            return None

        # 0) inline-штамп
        try:
            raw_inline = item.get("Stamp")
            if isinstance(raw_inline, dict) and raw_inline:
                return dict(raw_inline)
        except Exception:
            pass

        try:
            raw_inline = item.get("stamp")
            if isinstance(raw_inline, dict) and raw_inline:
                return dict(raw_inline)
        except Exception:
            pass

        inst = _get_instance_guid(item)
        if not inst:
            return None

        parent = self.parent()
        if not parent:
            return None

        # 1) локальный кэш хозяина
        try:
            cache = getattr(parent, "_applied_stamps", None)
            if isinstance(cache, dict) and inst in cache:
                raw = cache[inst]
                return dict(raw) if isinstance(raw, dict) else raw
        except Exception:
            pass

        # 2) DAO по инстансу
        try:
            data = getattr(parent, "data", None)
            getter = getattr(data, "get_item_stamp_by_instance", None)
            if callable(getter):
                raw = getter(inst)
                if isinstance(raw, dict) and raw:
                    return dict(raw)
                return raw
        except Exception:
            pass

        return None

    def _stamp_tip_payload_for_item(self, item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Превращает сохранённую печать в payload для equip_info.show_for_item(stamp=...),
        как делает StampWindow._to_tip_stamp_payload.
        """
        raw = self._saved_stamp_raw_for_item(item)
        if not raw:
            return None

        # уже tip-payload
        if any(k in raw for k in ("HeaderColorHex", "HeaderIconImageId", "icon_id")):
            try:
                return dict(raw)
            except Exception:
                return raw

        try:
            cid = int(
                raw.get("color_id")
                or raw.get("ColorId")
                or raw.get("Color_Id")
                or 0
            )
        except Exception:
            cid = 0

        parent = self.parent()
        meta = {}
        if parent and hasattr(parent, "_stamp_color_meta"):
            try:
                meta = parent._stamp_color_meta(cid) or {}
            except Exception:
                meta = {}
        if not meta:
            meta = _STAMP_COLOR_META.get(cid, {}) or {}

        name = (raw.get("name") or raw.get("Name") or "").strip()
        bonuses = list(
            raw.get("bonuses")
            or raw.get("Bonuses")
            or raw.get("BonusLines")
            or []
        )

        return {
            "Id": raw.get("id") or raw.get("Id"),
            "Name": name,
            "name": name,
            "ColorId": cid,
            "Bonuses": bonuses,
            "BonusLines": bonuses,
            "Effects": bonuses,
            "HeaderColorHex": meta.get("hex"),
            "HeaderIconImageId": meta.get("icon_img_id"),
            "icon_id": meta.get("icon_img_id"),
        }

    # ---------- Работа с БД / фордж ----------

    def _db_conn(self):
        parent = self.parent()
        data = getattr(parent, "data", None) if parent else None
        return getattr(data, "conn", None)

    def _db_has_col(self, table: str, col: str) -> bool:
        conn = self._db_conn()
        if not conn:
            return False

        table_l = str(table).lower()
        col_l = str(col).lower()

        cache = self._db_cols_cache
        if table_l not in cache:
            cols = set()
            try:
                for r in conn.execute(f"PRAGMA table_info({table})").fetchall():
                    name = r[1]
                    cols.add(str(name).lower())
            except Exception:
                cols = set()
            cache[table_l] = cols

        return col_l in cache.get(table_l, set())

    def _forge_table_name(self) -> Optional[str]:
        if self._forge_tbl_cache is not None:
            return self._forge_tbl_cache

        conn = self._db_conn()
        name = None
        if conn:
            for cand in ("EqipmentForge", "EquipmentForge", "Equipment_Forge"):
                try:
                    row = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
                        (cand,),
                    ).fetchone()
                except Exception:
                    row = None
                if row:
                    name = cand
                    break
        self._forge_tbl_cache = name
        return name

    def _load_forge_rows(self) -> List[Dict[str, Any]]:
        """
        Загружает строки форджа из EqipmentForge/EquipmentForge/Equipment_Forge:
        Level, Attack, Defense, AllStatBonus.
        """
        conn = self._db_conn()
        table = self._forge_table_name()
        if not conn or not table:
            return []

        has_attack = self._db_has_col(table, "Attack")
        has_defense = self._db_has_col(table, "Defense")
        has_all = self._db_has_col(table, "AllStatBonus")

        cols = ["Level"]
        if has_attack:
            cols.append("Attack")
        if has_defense:
            cols.append("Defense")
        if has_all:
            cols.append("AllStatBonus")

        sql = f"SELECT {', '.join(cols)} FROM {table} ORDER BY Level"
        try:
            rows = conn.execute(sql).fetchall()
        except Exception:
            return []

        out: List[Dict[str, Any]] = []
        for r in rows or []:
            lvl = 0
            atk_coef = 0.0
            def_coef = 0.0
            all_stat = 0

            if hasattr(r, "keys"):
                try:
                    lvl = self._to_int(r["Level"], 0)
                except Exception:
                    lvl = 0
                if has_attack:
                    try:
                        atk_coef = float(r["Attack"] or 0)
                    except Exception:
                        atk_coef = 0.0
                if has_defense:
                    try:
                        def_coef = float(r["Defense"] or 0)
                    except Exception:
                        def_coef = 0.0
                if has_all and "AllStatBonus" in r.keys():
                    try:
                        all_stat = self._to_int(r["AllStatBonus"], 0)
                    except Exception:
                        all_stat = 0
            else:
                idx = 0
                try:
                    lvl = self._to_int(r[idx], 0)
                except Exception:
                    lvl = 0
                idx += 1
                if has_attack:
                    try:
                        atk_coef = float(r[idx] or 0)
                    except Exception:
                        atk_coef = 0.0
                    idx += 1
                if has_defense:
                    try:
                        def_coef = float(r[idx] or 0)
                    except Exception:
                        def_coef = 0.0
                    idx += 1
                if has_all and idx < len(r):
                    try:
                        all_stat = self._to_int(r[idx], 0)
                    except Exception:
                        all_stat = 0

            out.append(
                {"level": lvl, "attack": atk_coef, "defense": def_coef, "all": all_stat}
            )
        return out

    def _hp_bonus_for_item_and_level(self, item: Optional[Dict[str, Any]], forge_level: int) -> int:
        """
        Возвращает бонус HP из таблицы EquipmentLevelForge для данного уровня точки.
        Учитывает класс предмета:
          C: с +5
          B: с +6
          A: с +7

        IMPORTANT:
        Для оружия HP бонус НЕ применяется вообще → всегда 0.
        """
        if not item or forge_level <= 0:
            return 0

        # >>> ВАЖНО: оружию HP не добавляем никогда
        if self._is_weapon_item(item):
            return 0

        # Порог по классу
        grade = self._determine_item_grade(item)
        grade = str(grade or "").upper()
        min_lvl_by_grade = {"C": 5, "B": 6, "A": 7}
        min_lvl = min_lvl_by_grade.get(grade, 7)
        if forge_level < min_lvl:
            return 0

        conn = self._db_conn()
        if not conn:
            return 0

        # Проверим, что таблица/колонки вообще есть
        if not (
                self._db_has_col("EquipmentLevelForge", "Level")
                and self._db_has_col("EquipmentLevelForge", "EquipmentLevel")
                and self._db_has_col("EquipmentLevelForge", "Hp")
        ):
            return 0

        # InternalLevel предмета
        parent = self.parent()
        equip_info = getattr(parent, "equip_info", None) if parent else None
        internal_level = None
        if equip_info and hasattr(equip_info, "_get_internal_level_for_item"):
            try:
                internal_level = int(equip_info._get_internal_level_for_item(item))
            except Exception:
                internal_level = None

        if not internal_level:
            internal_level = self._to_int(
                item.get("InternalLevel")
                or item.get("IternalLevel")
                or item.get("Level")
                or item.get("RequiredLevel")
                or 1,
                1,
            )

        # Берём запись с нужным Level и максимальным EquipmentLevel <= internal_level
        try:
            row = conn.execute(
                """
                SELECT Hp
                FROM EquipmentLevelForge
                WHERE Level = ? AND EquipmentLevel <= ?
                ORDER BY EquipmentLevel DESC
                LIMIT 1
                """,
                (int(forge_level), int(internal_level)),
            ).fetchone()
        except Exception:
            row = None

        if not row:
            return 0

        try:
            if hasattr(row, "keys"):
                return self._to_int(row["Hp"], 0)
            return self._to_int(row[0], 0)
        except Exception:
            return 0

    def _refresh_mats_for_item(self) -> None:
        it = self._item
        if not it:
            self.slot_mat1.hide()
            self.slot_mat2.hide()
            self.slot_mat1.clear()
            self.slot_mat2.clear()
            self._mat1 = None
            self._mat2 = None
            self._update_reforge_enabled()
            return

        # MAT1 — философский камень (кликабелен)
        pm1 = self._load_icon_pm(self.PHILO_STONE_PATH)
        if pm1:
            self._set_pixmap_to_label(self.slot_mat1, pm1)
            self.slot_mat1.setCursor(Qt.PointingHandCursor)
            self.slot_mat1.show()

        # MAT2 — руна (декоративная), зависит от уровня предмета
        lvl = self._to_int(it.get("Level"))
        path2 = self.RUNE_SAVES_PATH if lvl <= self.LEVEL_THRESHOLD else self.RUNE_COLD_PATH
        pm2 = self._load_icon_pm(path2)
        if pm2:
            self._set_pixmap_to_label(self.slot_mat2, pm2)
            self.slot_mat2.setCursor(Qt.ArrowCursor)
            self.slot_mat2.show()

        self._mat1 = None
        self._mat2 = None
        self._update_reforge_enabled()
        #self._apply_debug_areas()

    def _update_result_preview(self) -> None:
        """
        Перестроить предпросмотр улучшенного предмета в слоте GEO_RESULT.
        В result кладём всю мету точки (уровень, бонус к главному стату, allstat, HP)
        и базовые значения атаки/защиты.
        """
        if not self._item or self._selected_forge_level is None:
            self._result_payload = None
            self.slot_result.clear()
            return

        res = dict(self._item)

        # ===== базовые атака/защита из Equipment =====
        base_atk = 0.0
        base_def = 0.0

        conn = self._db_conn()
        if conn:
            equip_id = (
                    self._item.get("Equip_Id")
                    or self._item.get("Equipment_Id")
                    or self._item.get("Id")
            )
            try:
                equip_id = int(equip_id)
            except Exception:
                equip_id = 0

            if equip_id:
                has_atk = self._db_has_col("Equipment", "Attack")
                has_def = self._db_has_col("Equipment", "Defense")

                cols = []
                if has_atk:
                    cols.append("Attack")
                if has_def:
                    cols.append("Defense")

                if cols:
                    sql = f"SELECT {', '.join(cols)} FROM Equipment WHERE Id=? LIMIT 1"
                    try:
                        row = conn.execute(sql, (equip_id,)).fetchone()
                    except Exception:
                        row = None

                    if row:
                        if hasattr(row, "keys"):
                            if has_atk:
                                try:
                                    base_atk = float(row["Attack"] or 0)
                                except Exception:
                                    base_atk = 0.0
                            if has_def:
                                try:
                                    base_def = float(row["Defense"] or 0)
                                except Exception:
                                    base_def = 0.0
                        else:
                            idx = 0
                            if has_atk:
                                try:
                                    base_atk = float(row[idx] or 0)
                                except Exception:
                                    base_atk = 0.0
                                idx += 1
                            if has_def and idx < len(row):
                                try:
                                    base_def = float(row[idx] or 0)
                                except Exception:
                                    base_def = 0.0

        base_atk_i = int(round(base_atk)) if base_atk > 0 else 0
        base_def_i = int(round(base_def)) if base_def > 0 else 0

        is_weapon = self._is_weapon_item(self._item)

        # бонус HP из EquipmentLevelForge (только НЕ для оружия)
        if is_weapon:
            hp_bonus = 0
        else:
            hp_bonus = self._hp_bonus_for_item_and_level(
                self._item,
                int(self._selected_forge_level),
            )

        self._selected_forge_hp = int(hp_bonus)

        atk_bonus = int(self._selected_forge_bonus_atk or 0)
        def_bonus = int(self._selected_forge_bonus_def or 0)

        res["ForgeLevel"] = int(self._selected_forge_level)
        res["ForgeBonus"] = int(self._selected_forge_bonus or 0)  # главный стат (атака/защита)
        res["ForgeAllStatBonus"] = int(self._selected_forge_allstat or 0)
        res["ForgeHpBonus"] = int(self._selected_forge_hp or 0)

        # НОВОЕ: отдельные бонусы
        res["ForgeAttackBonus"] = atk_bonus
        res["ForgeDefenseBonus"] = def_bonus

        # базовые значения (для тултипа и прочей меты)
        res["BaseAttack"] = base_atk_i
        res["BaseDefense"] = base_def_i

        if self._item_source_slot:
            res["slot_key"] = self._item_source_slot

        self._result_payload = res
        self._set_label_icon_from_item(self.slot_result, res)

    # ---------- Иконки ----------
    def _db_equipment_image_id(self, equip_id: int) -> Optional[int]:
        """
        Пытаемся получить ImageId для предмета из таблицы Equipment по Id.
        Приоритет: Icon_Image_Id -> Image_Id -> Tooltip.
        """
        try:
            equip_id = int(equip_id)
        except Exception:
            return None
        if equip_id <= 0:
            return None

        conn = self._db_conn()
        if not conn:
            return None

        wanted = [
            "Icon_Image_Id", "IconImage_Id", "IconImageId",
            "Image_Id", "ImageId",
            "ToolTipImage_Id", "TooltipImage_Id", "ToolTipImageId", "TooltipImageId",
        ]
        cols = [c for c in wanted if self._db_has_col("Equipment", c)]
        if not cols:
            return None

        sql = f"SELECT {', '.join(cols)} FROM Equipment WHERE Id=? LIMIT 1"
        try:
            row = conn.execute(sql, (equip_id,)).fetchone()
        except Exception:
            row = None

        if not row:
            return None

        for i, col in enumerate(cols):
            try:
                v = row[col] if hasattr(row, "keys") else row[i]
                iv = int(v)
                if iv > 0:
                    return iv
            except Exception:
                continue

        return None

    def _db_equipment_type_image_id(self, type_id: int) -> Optional[int]:
        """
        Фоллбек: если у конкретного предмета нет картинки — попробуем взять из EquipmentType.
        Приоритет: Icon_Image_Id -> Image_Id -> Tooltip.
        """
        try:
            type_id = int(type_id)
        except Exception:
            return None
        if type_id <= 0:
            return None

        conn = self._db_conn()
        if not conn:
            return None

        wanted = [
            "Icon_Image_Id", "IconImage_Id", "IconImageId",
            "Image_Id", "ImageId",
            "ToolTipImage_Id", "TooltipImage_Id", "ToolTipImageId", "TooltipImageId",
        ]
        cols = [c for c in wanted if self._db_has_col("EquipmentType", c)]
        if not cols:
            return None

        sql = f"SELECT {', '.join(cols)} FROM EquipmentType WHERE Id=? LIMIT 1"
        try:
            row = conn.execute(sql, (type_id,)).fetchone()
        except Exception:
            row = None

        if not row:
            return None

        for i, col in enumerate(cols):
            try:
                v = row[col] if hasattr(row, "keys") else row[i]
                iv = int(v)
                if iv > 0:
                    return iv
            except Exception:
                continue

        return None

    def _resolve_image_id(self, item: Dict[str, Any]) -> Optional[int]:
        """
        Находит ImageId для иконки максимально надёжно:
        1) берём из самого item (учитывая Icon_Image_Id)
        2) если нет — идём в Equipment по Id/Equip_Id
        3) если нет — идём в EquipmentType по Type_Id
        При успехе кешируем в item (не перетирая существующие ключи).
        """
        if not isinstance(item, dict):
            item = dict(item)  # type: ignore

        # 1) прямые поля в item
        img_id = self._extract_image_id(item)
        if img_id:
            item.setdefault("Icon_Image_Id", img_id)
            item.setdefault("Image_Id", img_id)
            return img_id

        # 2) Equipment.Id
        equip_id = (
                item.get("Equip_Id") or item.get("Equipment_Id")
                or item.get("EquipId") or item.get("EquipmentId")
                or item.get("Id")
        )
        try:
            equip_id_i = int(equip_id) if equip_id is not None else 0
        except Exception:
            equip_id_i = 0

        if equip_id_i > 0:
            img_id = self._db_equipment_image_id(equip_id_i)
            if img_id:
                item.setdefault("Icon_Image_Id", img_id)
                item.setdefault("Image_Id", img_id)
                return img_id

        # 3) EquipmentType.Id
        type_id = (
                item.get("Type_Id") or item.get("TypeId")
                or item.get("EquipmentType_Id") or item.get("EquipmentTypeId")
        )
        try:
            type_id_i = int(type_id) if type_id is not None else 0
        except Exception:
            type_id_i = 0

        if type_id_i > 0:
            img_id = self._db_equipment_type_image_id(type_id_i)
            if img_id:
                item.setdefault("Icon_Image_Id", img_id)
                item.setdefault("Image_Id", img_id)
                return img_id
        return None

    def _load_icon_pm(self, path: str) -> Optional[QPixmap]:
        pm = QPixmap(path)
        return pm if not pm.isNull() else None

    def _extract_image_id(self, item: Dict[str, Any]) -> Optional[int]:
        if not isinstance(item, dict):
            try:
                item = dict(item)  # type: ignore
            except Exception:
                return None

        # ВАЖНО: сначала Icon_Image_Id (контракт weapon_equipment_button),
        # потом Image_Id, потом прочие алиасы/tooltip.
        for k in (
                "Icon_Image_Id", "Icon_ImageId", "IconImage_Id", "IconImageId",
                "Image_Id", "ImageId",
                "ItemImage_Id", "ItemImageId",
                "ToolTipImage_Id", "TooltipImage_Id", "ToolTipImageId", "TooltipImageId",
        ):
            v = item.get(k)
            if v is None:
                continue
            try:
                iv = int(v)
                if iv > 0:
                    return iv
            except Exception:
                pass

        return None

    def _load_pm_by_id(self, image_id: int) -> Optional[QPixmap]:
        """
        Грузим иконку предмета.
        1) Если задан self._image_loader – пробуем его.
        2) Если нет – parent.data.get_image_bytes.

        ВАЖНО: ничего не сохраняем на диск (никаких PNG).
        """
        raw = None
        used = "none"

        if self._image_loader:
            try:
                raw = self._image_loader(int(image_id))
                used = "self._image_loader"
            except Exception as e:
                raw = None
                used = f"self._image_loader EXC {type(e).__name__}"

        if not raw:
            parent = self.parent()
            getter = None
            if parent is not None and hasattr(parent, "data"):
                try:
                    getter = getattr(parent.data, "get_image_bytes", None)
                except Exception:
                    getter = None

            if callable(getter):
                try:
                    raw = getter(int(image_id))
                    used = "parent.data.get_image_bytes"
                except Exception as e:
                    raw = None
                    used = f"parent.data.get_image_bytes EXC {type(e).__name__}"

        raw_type = type(raw).__name__
        try:
            raw_len = len(raw)  # type: ignore
        except Exception:
            raw_len = None

        try:
            if isinstance(raw, memoryview):
                raw = raw.tobytes()
            elif isinstance(raw, bytearray):
                raw = bytes(raw)
        except Exception:
            pass

        pm = QPixmap()
        try:
            ok = pm.loadFromData(raw)  # type: ignore[arg-type]
        except Exception as e:
            ok = False

        return pm

    def _set_label_icon_from_item(self, label: QLabel, item: Optional[Dict[str, Any]]) -> None:
        if not item:
            label.clear()
            return

        img_id = self._resolve_image_id(item)
        if not img_id:
            label.clear()
            return

        pm = self._load_pm_by_id(int(img_id))
        if not pm or pm.isNull():
            label.clear()
            return

        # fallback size, если label ещё не разложен
        target = label.size()
        if target.width() <= 1 or target.height() <= 1:
            # берём “дизайнерский” размер слотов (53/54)
            target = QSize(54, 54)

        eid = self._element_id_for_item(item) or 0
        if eid:
            final_pm = self._compose_with_element_badge(pm, target, int(eid), item)
            label.setPixmap(final_pm)
        else:
            label.setPixmap(pm.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    @staticmethod
    def _set_pixmap_to_label(label: QLabel, pm: QPixmap) -> None:
        label.setPixmap(pm.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # ---------- Тултипы ----------
    def _show_item_tip(self, anchor_widget: QWidget, payload: dict) -> None:
        p = self.parent()
        if not p:
            return

        ei = getattr(p, "equip_info", None)
        if ei is None:
            return

        tip_item = dict(payload or {})

        slot_key = str(
            tip_item.get("slot_key")
            or tip_item.get("SlotKey")
            or getattr(self, "_picked_slot_key", "")
            or ""
        ).strip()

        if slot_key:
            tip_item["slot_key"] = slot_key

        # --- подтягиваем живой предмет из MainWindow._selected_items ---
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
                elif int(live_item.get("Id") or 0) > 0 and int(live_item.get("Id") or 0) == int(
                        tip_item.get("Id") or 0):
                    same_item = True

            if same_item and isinstance(live_item, dict):
                important_keys = (
                    "InstanceGuid",
                    "Stamp", "stamp", "_stamp",
                    "StampId", "StampColorId", "StampName", "StampBonuses",
                    "StampHeaderColorHex", "StampHeaderIconImageId", "StampHeaderIconId",
                    "__forge_level", "ForgeLevel", "UpgradeLevel", "Forge_Level",
                    "__forge_bonus", "ForgeBonus", "Forge_Bonus", "UpgradeBonus", "UpgradeBonusValue",
                    "__forge_hp_bonus", "ForgeHpBonus", "Forge_HP_Bonus", "ForgeHp", "HpBonusFromForge",
                    "__forge_allstat", "ForgeAllStatBonus", "ForgeAllBonus", "AllStatBonus", "Forge_AllStatBonus",
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

        def _pick_int(d: dict, keys: tuple[str, ...]) -> int | None:
            for k in keys:
                if k in d and d[k] is not None:
                    try:
                        return int(d[k])
                    except Exception:
                        pass
            return None

        # 1) собрать значения из любых алиасов
        forge_level = _pick_int(tip_item, ("ForgeLevel", "__forge_level", "UpgradeLevel", "Forge_Level"))
        forge_bonus = _pick_int(
            tip_item,
            ("ForgeBonus", "__forge_bonus", "Forge_Bonus", "UpgradeBonus", "UpgradeBonusValue"),
        )
        forge_hp = _pick_int(
            tip_item,
            ("ForgeHpBonus", "__forge_hp_bonus", "Forge_HP_Bonus", "ForgeHp", "HpBonusFromForge"),
        )
        forge_all = _pick_int(
            tip_item,
            ("ForgeAllStatBonus", "__forge_allstat", "ForgeAllBonus", "AllStatBonus", "Forge_AllStatBonus"),
        )
        forge_atk = _pick_int(tip_item, ("ForgeAttackBonus", "__forge_atk_bonus", "ForgeAtkBonus"))
        forge_def = _pick_int(tip_item, ("ForgeDefenseBonus", "__forge_def_bonus", "ForgeDefBonus"))

        # 2) удалить алиасы, чтобы не плодить дубли
        for k in (
                "__forge_level", "__forge_bonus", "__forge_hp_bonus", "__forge_allstat",
                "__forge_atk_bonus", "__forge_def_bonus",
                "Forge_Level", "Forge_Bonus", "Forge_HP_Bonus", "Forge_AllStatBonus",
                "ForgeAllBonus", "ForgeAllStat", "AllStatBonus",
                "UpgradeLevel", "UpgradeBonus", "UpgradeBonusValue",
                "ForgeAtkBonus", "ForgeDefBonus",
        ):
            tip_item.pop(k, None)

        # 3) оставить каноничные ключи
        if forge_level is not None:
            tip_item["ForgeLevel"] = forge_level
            tip_item["UpgradeLevel"] = forge_level
        if forge_bonus is not None:
            tip_item["ForgeBonus"] = forge_bonus
        if forge_hp is not None:
            tip_item["ForgeHpBonus"] = forge_hp
        if forge_all is not None:
            tip_item["ForgeAllStatBonus"] = forge_all
        if forge_atk is not None:
            tip_item["ForgeAttackBonus"] = forge_atk
        if forge_def is not None:
            tip_item["ForgeDefenseBonus"] = forge_def

        bonus_lines = None
        try:
            bonus_lines = self._build_bonus_lines_for_tip(tip_item)
        except Exception:
            bonus_lines = None

        stamp_payload = None
        try:
            stamp_payload = self._stamp_tip_payload_for_item(tip_item)
        except Exception:
            stamp_payload = None

        def _etype_name_by_id(tid: int) -> str:
            try:
                data = getattr(p, "data", None)
                conn = getattr(data, "conn", None)
                if conn is None:
                    return "—"

                row = conn.execute(
                    "SELECT Name FROM EquipmentType WHERE Id=? LIMIT 1",
                    (int(tid),),
                ).fetchone()

                if not row:
                    return "—"

                try:
                    return row["Name"]
                except Exception:
                    return row[0]
            except Exception:
                return "—"

        # Карты — как в InventoryWindow._show_item_tooltip:
        # даём equip_info полноценный payload карт, если cards_window умеет его собрать.
        cards_payload = None
        try:
            cw = getattr(p, "cards_window", None)
            if cw is not None and hasattr(cw, "build_tooltip_cards_payload_for_item"):
                try:
                    kind = "weapon" if slot_key in ("weapon", "offhand", "spear") or self._is_weapon_item(
                        tip_item) else "equipment"
                except Exception:
                    kind = "equipment"

                cards_payload = cw.build_tooltip_cards_payload_for_item(
                    tip_item,
                    kind=kind,
                    slot_key=slot_key or None,
                )
        except Exception:
            cards_payload = None

        rect_global = QRect(
            anchor_widget.mapToGlobal(anchor_widget.rect().topLeft()),
            anchor_widget.rect().size(),
        )

        safe_rect = QRect(rect_global)
        safe_rect.setWidth(max(60, safe_rect.width()))

        gp = safe_rect.center()
        gp.setY(safe_rect.top())

        image_loader = getattr(getattr(p, "data", None), "get_image_bytes", None) or self._image_loader

        kwargs = dict(
            item=tip_item,
            image_loader=image_loader,
            global_pos=gp,
            slot_key=slot_key or None,
            type_name=None,
            type_name_lookup=_etype_name_by_id,
            item_class=tip_item.get("ItemClass"),
            cards=cards_payload,
            bonus_lines=bonus_lines,
            stamp=stamp_payload,
            anchor_rect_global=safe_rect,
        )

        # Закрыть старую анкету от другого anchor.
        try:
            last = getattr(self, "_last_tip_anchor", None)
            if last is not None and last is not anchor_widget:
                ei.end_hover(last)
        except Exception:
            pass

        self._last_tip_anchor = anchor_widget

        # Linux/Wayland:
        # show_for_item вызывается напрямую, без begin_hover(),
        # поэтому transientParent надо ставить здесь.
        # Иначе анкета может провалиться под UpgradeWindow/попап выбора.
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

        # ВАЖНО: в reforge этого раньше не хватало.
        # В stamp_window это уже сделано, поэтому там анкета стабильнее.
        try:
            ei.show()
            ei.raise_()
            ei.update()
        except Exception:
            pass

    def _tip_enter_for(self, w: QLabel) -> None:
        payload = None
        if w is self.slot_item:
            payload = self._item
        elif w is self.slot_mat1:
            payload = self._mat1
        elif w is self.slot_mat2:
            payload = self._mat2
        elif w is self.slot_result:
            payload = self._result_payload

        if not payload:
            return

        self._show_item_tip(w, payload)

    def _tip_leave_for(self, w: QLabel) -> None:
        p = self.parent()
        if p and hasattr(p, "equip_info"):
            try:
                p.equip_info.end_hover(w)
            except Exception:
                pass
        if getattr(self, "_last_tip_anchor", None) is w:
            self._last_tip_anchor = None

    def _end_all_hovers(self) -> None:
        for w in (self.slot_item, self.slot_mat1, self.slot_mat2, self.slot_result):
            self._tip_leave_for(w)

    # ---------- События ----------
    # === ЗАМЕНИ ЦЕЛИКОМ функцию eventFilter ===

    def eventFilter(self, obj, ev) -> bool:
        # ---- Глобальное поглощение "replay" клика после закрытия popup ----
        try:
            swallow_left = int(getattr(self, "_swallow_global_left", 0))
        except Exception:
            swallow_left = 0

        if swallow_left > 0:
            t0 = ev.type()

            btn0 = Qt.NoButton
            try:
                if hasattr(ev, "button"):
                    btn0 = ev.button()
            except Exception:
                btn0 = Qt.NoButton

            if t0 in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
                is_left = (btn0 == Qt.LeftButton)
            elif t0 == QEvent.MouseButtonRelease:
                is_left = (btn0 in (Qt.LeftButton, Qt.NoButton))
            else:
                is_left = False

            if is_left:
                pp = getattr(self, "_pick_popup", None)
                lp = getattr(self, "_lvl_popup", None)
                if not self._is_descendant_obj(obj, pp) and not self._is_descendant_obj(obj, lp):
                    try:
                        ev.accept()
                    except Exception:
                        pass

                    swallow_left -= 1
                    setattr(self, "_swallow_global_left", swallow_left)

                    if swallow_left <= 0:
                        self._disarm_global_mouse_swallow()

                    return True

        if not hasattr(self, "_close_armed"):
            self._close_armed = False
        if not hasattr(self, "_help_armed"):
            self._help_armed = False
        if not hasattr(self, "_pick_item_armed_obj"):
            self._pick_item_armed_obj = None
        if not hasattr(self, "_forge_level_armed_obj"):
            self._forge_level_armed_obj = None

        t = ev.type()
        btn = getattr(ev, "button", lambda: None)()
        pos = ev.position().toPoint() if hasattr(ev, "position") else (ev.pos() if hasattr(ev, "pos") else None)

        # =======================
        #   К Н О П К А  К Р Е С Т И К
        # =======================
        if obj is self.btn_close:
            if t == QEvent.Enter:
                self.btn_close.setIcon(QIcon("resources/helper_buttons/close_button_active.png"))
                self.btn_close.setIconSize(self.CLOSE_SIZE)
                return True

            elif t in (QEvent.Leave, QEvent.HoverLeave):
                self.btn_close.setIcon(QIcon())
                self._close_armed = False
                return True

            elif t == QEvent.MouseButtonPress and btn == Qt.LeftButton:
                self._close_armed = True
                return True

            elif t == QEvent.MouseButtonRelease and btn == Qt.LeftButton:
                inside = self.btn_close.rect().contains(pos) if pos is not None else False
                armed = self._close_armed
                self._close_armed = False
                if inside and armed:
                    self.close()
                return True

            elif t == QEvent.MouseButtonDblClick:
                return True

            return False

        # =======================
        #   К Н О П К А  H E L P
        # =======================
        if obj is self.btn_help:
            if t == QEvent.Enter:
                self.btn_help.setIcon(QIcon("resources/helper_buttons/help_button_active.png"))
                self.btn_help.setIconSize(self.CLOSE_SIZE)
                return True

            elif t in (QEvent.Leave, QEvent.HoverLeave):
                self.btn_help.setIcon(QIcon())
                self._help_armed = False
                return True

            elif t == QEvent.MouseButtonPress and btn == Qt.LeftButton:
                self._help_armed = True
                return True

            elif t == QEvent.MouseButtonRelease and btn == Qt.LeftButton:
                inside = self.btn_help.rect().contains(pos) if pos is not None else False
                armed = self._help_armed
                self._help_armed = False
                if inside and armed:
                    self._on_help_clicked()
                return True

            elif t == QEvent.MouseButtonDblClick:
                return True

            return False

        # =======================
        #   Т У Л Т И П Ы  П О  З О Н А М
        # =======================
        if obj in (self.slot_item, self.slot_mat1, self.slot_mat2, self.slot_result):
            if t == QEvent.Enter:
                self._tip_enter_for(obj)
                return False
            if t in (QEvent.Leave, QEvent.HoverLeave):
                self._tip_leave_for(obj)
                return False

        # ПКМ по GEO_RESULT → сохранить улучшенный предмет
        if obj is self.slot_result and t == QEvent.MouseButtonRelease and btn == Qt.RightButton:
            self._on_result_right_click()
            return True

        # клик по GEO_ITEM → попап выбора надетых
        if obj is self.slot_item and t == QEvent.MouseButtonRelease and btn == Qt.LeftButton:
            self._show_pick_item_popup()
            return True

        # клик по MAT1 → меню уровней точки
        if obj is self.slot_mat1 and self.slot_mat1.isVisible():
            if t == QEvent.MouseButtonRelease and btn == Qt.LeftButton:
                if self._item:
                    self._show_level_popup()
                return True

        # =======================
        #   П О П П А П  В Ы Б О Р А  Н А Д Е Т Ы Х
        # =======================
        if (
                isinstance(obj, QToolButton)
                and obj.parent() is getattr(self, "_pick_popup", None)
                and obj.property("item_dict") is not None
        ):
            p = self.parent()

            if t == QEvent.Enter and p and hasattr(p, "equip_info"):
                self._show_item_tip(obj, obj.property("item_dict"))
                return True

            if t in (QEvent.Leave, QEvent.HoverLeave) and p and hasattr(p, "equip_info"):
                try:
                    p.equip_info.end_hover(obj)
                except Exception:
                    pass
                return True

            if t == QEvent.MouseButtonPress and btn == Qt.LeftButton:
                self._pick_item_armed_obj = obj
                try:
                    ev.accept()
                except Exception:
                    pass
                return True

            if t == QEvent.MouseButtonRelease and btn == Qt.LeftButton:
                armed_obj = getattr(self, "_pick_item_armed_obj", None)
                self._pick_item_armed_obj = None
                inside = obj.rect().contains(pos) if pos is not None else False

                if armed_obj is obj and inside:
                    slot_key = obj.property("slot_key")
                    slot_key = str(slot_key) if slot_key else None

                    raw_item = obj.property("item_dict")
                    item = self._as_plain_dict(raw_item) or {}

                    self.set_item(item, slot_key=slot_key, _user_pick=True)
                    self._refresh_mats_for_item()

                    self._arm_global_mouse_swallow(count=3, timeout_ms=260)
                    self._hide_pick_item_popup()

                try:
                    ev.accept()
                except Exception:
                    pass
                return True

            if t == QEvent.MouseButtonDblClick:
                try:
                    ev.accept()
                except Exception:
                    pass
                return True

            return True

        # закрытие попапа выбора надетых
        if obj is getattr(self, "_pick_popup", None):
            if t in (QEvent.Hide, QEvent.Close):
                self._pick_item_armed_obj = None
                self._hide_pick_item_popup()
                return True
            return False

        # =======================
        #   П О П П А П  У Р О В Н Е Й  Т О Ч К И
        # =======================
        if obj is getattr(self, "_lvl_popup", None):
            if t in (QEvent.Hide, QEvent.Close):
                self._forge_level_armed_obj = None
                self._hide_level_popup()
                return True
            return False

        # строки в меню уровней точки
        if (
                isinstance(obj, QWidget)
                and obj.parent() is getattr(self, "_lvl_popup", None)
                and obj.property("forge_level") is not None
        ):
            base_style = obj.property("_base_style") or (
                "background: rgba(0,0,0,0.35);"
                "border-radius:4px;"
                "border:1px solid rgba(0,0,0,0);"
            )
            hover_style = obj.property("_hover_style") or (
                "background: rgba(0,0,0,0.45);"
                "border-radius:4px;"
                "border:1px solid rgba(255,255,255,0.22);"
            )

            if t == QEvent.Enter:
                obj.setStyleSheet(hover_style)
                return True

            if t in (QEvent.Leave, QEvent.HoverLeave):
                obj.setStyleSheet(base_style)
                return True

            if t == QEvent.MouseButtonPress and btn == Qt.LeftButton:
                self._forge_level_armed_obj = obj
                return True

            if t == QEvent.MouseButtonRelease and btn == Qt.LeftButton:
                armed_obj = getattr(self, "_forge_level_armed_obj", None)
                self._forge_level_armed_obj = None
                inside = obj.rect().contains(pos) if pos is not None else False

                if armed_obj is obj and inside:
                    lvl = self._to_int(obj.property("forge_level"), 0)
                    bonus_main = self._to_int(obj.property("forge_bonus"), 0)
                    all_bonus = self._to_int(obj.property("forge_allstat"), 0)
                    bonus_atk = self._to_int(obj.property("forge_bonus_atk"), 0)
                    bonus_def = self._to_int(obj.property("forge_bonus_def"), 0)

                    self._selected_forge_level = lvl
                    self._selected_forge_bonus = bonus_main
                    self._selected_forge_bonus_atk = bonus_atk
                    self._selected_forge_bonus_def = bonus_def
                    self._selected_forge_allstat = all_bonus
                    self._selected_forge_hp = 0

                    self._hide_level_popup()

                    if self._item is not None:
                        self._update_result_preview()
                return True

            if t == QEvent.MouseButtonDblClick:
                return True

            return False

        return super().eventFilter(obj, ev)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
            self.close()
            return
        super().keyPressEvent(e)

    def _reset_help_button_visual(self) -> None:
        if hasattr(self, "btn_help") and self.btn_help:
            self.btn_help.setDown(False)
            self.btn_help.setChecked(False)
            self.btn_help.setIcon(QIcon())  # убрать активную иконку
            self.btn_help.setAttribute(Qt.WA_UnderMouse, False)
            # реполиш стиля на всякий случай
            self.btn_help.setStyleSheet(self.btn_help.styleSheet())
            self.btn_help.update()

    def _on_result_right_click(self) -> None:
        """
        ПКМ по слоту результата — отправляем наружу запрос на сохранение
        улучшенного предмета через сигнал on_reforge_request.
        Формат payload совместим со старым (_emit_save_result),
        чтобы MainWindow продолжал всё понимать.
        После сохранения — очищаем все слоты рефоржа.
        """
        # если предмета/уровня нет – просто ничего не делаем
        if not self._item or self._selected_forge_level is None:
            return

        # убеждаемся, что предпросмотр актуален
        if not self._result_payload:
            self._update_result_preview()
        if not self._result_payload:
            # всё ещё нечего сохранять
            return

        # ГЛАВНОЕ: "item" = улучшенный предмет, как раньше в _emit_save_result
        payload = {
            "item": dict(self._result_payload),  # уже улучшенный предмет
            "slot_key": self._item_source_slot,
            "forge_level": int(self._selected_forge_level),

            # дополнительные поля — если MainWindow их не использует, они просто игнорируются
            "forge_bonus": int(self._selected_forge_bonus or 0),
            "forge_all_bonus": int(self._selected_forge_allstat or 0),
            "forge_hp_bonus": int(self._selected_forge_hp or 0),
        }

        self.on_reforge_request.emit(payload)

        # после успешной отправки — чистим UI рефоржа
        self._clear_reforge_ui()

    # ---------- Перетаскивание окна ----------

    def _rebuild_drag_blockers(self) -> None:
        """Какие виджеты (и их потомки) блокируют старт перетаскивания окна."""
        self._drag_blockers = {
            w
            for w in (
                getattr(self, "btn_close", None),
                getattr(self, "slot_item", None),
                getattr(self, "slot_mat1", None),
                getattr(self, "slot_mat2", None),
                getattr(self, "slot_result", None),
                getattr(self, "_pick_popup", None),
                getattr(self, "_lvl_popup", None),
            )
            if w is not None
        }

    def _is_drag_blocked(self, w: Optional[QWidget]) -> bool:
        blockers = getattr(self, "_drag_blockers", set())
        cur = w
        while cur is not None:
            if cur in blockers:
                return True
            cur = cur.parentWidget()
        return False

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            w = self.childAt(e.position().toPoint())
            if not self._is_drag_blocked(w):
                self._dragging = True
                self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self.setCursor(Qt.SizeAllCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        if self._dragging and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(e)

    # ---------- hide/close ----------

    def hideEvent(self, ev) -> None:
        self._hide_pick_item_popup()
        self._hide_level_popup()
        self._end_all_hovers()
        if hasattr(self, "btn_close"):
            self.btn_close.setIcon(QIcon())  # убираем картинку
            self.btn_close.setIconSize(self.CLOSE_SIZE)  # на всякий случай
        if hasattr(self, "btn_help"):
            self.btn_help.setIcon(QIcon())
            self.btn_help.setIconSize(self.HELP_SIZE)

        self._reset_help_button_visual()  # <- добавь это
        super().hideEvent(ev)

    def close(self) -> bool:  # type: ignore[override]
        self._hide_pick_item_popup()
        self._hide_level_popup()
        self._end_all_hovers()
        return super().close()

    # ---------- Служебные ----------

    def _update_reforge_enabled(self) -> None:
        """
        Пока отдельной кнопки «Reforge» нет – метод оставлен для совместимости.
        Через него удобно будет управлять доступностью кнопки в будущем.
        """
        return

    def _clear_reforge_ui(self) -> None:
        """
        Полный сброс состояния окна рефоржа:
        очищаем выбранный предмет, материалы, результат и иконки.
        """
        # стейт
        self._item = None
        self._mat1 = None
        self._mat2 = None
        self._result_payload = None
        self._item_source_slot = None

        self._selected_forge_level = None
        self._selected_forge_bonus = 0
        self._selected_forge_bonus_atk = 0
        self._selected_forge_bonus_def = 0
        self._selected_forge_allstat = 0
        self._selected_forge_hp = 0

        # иконки слотов
        self.slot_item.clear()
        self.slot_mat1.clear()
        self.slot_mat2.clear()
        self.slot_result.clear()

        # материалы скрываем
        self.slot_mat1.hide()
        self.slot_mat2.hide()

        # снимаем ховеры, чистим статус
        self._end_all_hovers()
        self.set_status("")

    def _is_weapon_item(self, item: Optional[dict]) -> bool:
        """
        Оружие ли это – по Slot_Id (21/22) + фоллбэки.
        ДОПОЛНИТЕЛЬНО: если в EquipmentType для Type_Id оба поля
        IsMeleeWeapon и IsSingleHandWeapon НЕ NULL → это оружие.
        """
        if not isinstance(item, dict):
            return False

        # 1) прямые поля в item (Slot_Id)
        slot_id = 0
        for k in ("Slot_Id", "SlotId", "EquipmentSlot_Id", "EquipmentSlotId"):
            if item.get(k) is not None:
                try:
                    slot_id = int(item.get(k) or 0)
                except Exception:
                    slot_id = 0
                break
        if slot_id in (21, 22):
            return True

        # 2) по имени слота (если прокидываешь slot_key)
        try:
            sk = str(item.get("slot_key") or item.get("slotKey") or item.get("SlotKey") or "").lower()
        except Exception:
            sk = ""
        if sk:
            if ("weapon" in sk) or ("spear" in sk) or ("коп" in sk) or ("оруж" in sk):
                return True

        conn = self._db_conn()
        if not conn:
            return False

        # equip_id (для фоллбэков)
        equip_id = item.get("Equip_Id") or item.get("Equipment_Id") or item.get("Id")
        try:
            equip_id = int(equip_id)
        except Exception:
            equip_id = 0

        # 3) фоллбэк в БД по Equipment.Id -> Equipment.Slot_Id
        if equip_id and self._db_has_col("Equipment", "Slot_Id"):
            try:
                row = conn.execute("SELECT Slot_Id FROM Equipment WHERE Id=? LIMIT 1", (int(equip_id),)).fetchone()
            except Exception:
                row = None
            if row:
                try:
                    db_slot = int(row["Slot_Id"] if hasattr(row, "keys") else row[0])
                except Exception:
                    db_slot = 0
                if db_slot in (21, 22):
                    return True

        # 4) определим Type_Id (из item или из Equipment)
        tid = item.get("Type_Id") or item.get("TypeId") or item.get("EquipmentType_Id") or item.get("EquipmentTypeId")
        try:
            tid = int(tid)
        except Exception:
            tid = 0

        if not tid and equip_id:
            # попробуем вытащить тип из Equipment, если там он есть
            for col in ("Type_Id", "EquipmentType_Id"):
                if self._db_has_col("Equipment", col):
                    try:
                        row = conn.execute(f"SELECT {col} FROM Equipment WHERE Id=? LIMIT 1",
                                           (int(equip_id),)).fetchone()
                    except Exception:
                        row = None
                    if row:
                        try:
                            tid = int(row[col] if hasattr(row, "keys") else row[0])
                        except Exception:
                            tid = 0
                    if tid:
                        break

        # 5) ДОП проверка через EquipmentType: IsMeleeWeapon != NULL AND IsSingleHandWeapon != NULL
        if tid and self._db_has_col("EquipmentType", "IsMeleeWeapon") and self._db_has_col("EquipmentType",
                                                                                           "IsSingleHandWeapon"):
            try:
                row = conn.execute(
                    "SELECT IsMeleeWeapon, IsSingleHandWeapon FROM EquipmentType WHERE Id=? LIMIT 1",
                    (int(tid),),
                ).fetchone()
            except Exception:
                row = None

            if row:
                try:
                    melee = row["IsMeleeWeapon"] if hasattr(row, "keys") else row[0]
                except Exception:
                    melee = None
                try:
                    onehand = row["IsSingleHandWeapon"] if hasattr(row, "keys") else row[1]
                except Exception:
                    onehand = None

                # ВАЖНО: проверяем именно на NULL (0 тоже считается "не NULL")
                if melee is not None and onehand is not None:
                    return True

        # 6) старый фоллбэк по EquipmentType.Slot_Id (оставим)
        if tid and self._db_has_col("EquipmentType", "Slot_Id"):
            try:
                row = conn.execute("SELECT Slot_Id FROM EquipmentType WHERE Id=? LIMIT 1", (int(tid),)).fetchone()
            except Exception:
                row = None
            if row:
                try:
                    db_slot = int(row["Slot_Id"] if hasattr(row, "keys") else row[0])
                except Exception:
                    db_slot = 0
                if db_slot in (21, 22):
                    return True

        return False

    def _determine_item_grade(self, item: Optional[dict]) -> str:
        """
        Определяем класс предмета (C / B / A).

        Приоритет:
        1) спрашиваем у родительского equip_info тот же алгоритм, что в тултипе;
        2) fallback – старые пороги _CLASS_THRESHOLDS из stamp_window;
        3) ещё один fallback – «до ~50 уровня = B, дальше = A» (как раньше).
        """
        if not isinstance(item, dict):
            return "A"

        parent = self.parent()
        equip_info = getattr(parent, "equip_info", None) if parent else None

        # 1) главный источник истины – логика из EquipmentInfoWindow
        if equip_info and hasattr(equip_info, "_get_internal_level_for_item") and hasattr(
            equip_info, "_class_letter_from_internal"
        ):
            try:
                internal_lvl = equip_info._get_internal_level_for_item(item)
                grade = equip_info._class_letter_from_internal(internal_lvl)
                if isinstance(grade, str) and grade.strip():
                    grade = grade.strip().upper()
                    if grade in ("A", "B", "C"):
                        return grade
            except Exception:
                pass

        # 2) fallback – старые пороги из stamp_window (если вдруг они ещё заданы)
        try:
            t_id = self._to_int(item.get("Type_Id") or item.get("TypeId") or 0, 0)
            lvl = self._to_int(
                item.get("InternalLevel")
                or item.get("Level")
                or item.get("RequiredLevel")
                or 1,
                1,
            )
        except Exception:
            t_id, lvl = 0, 1

        # 3) простой эвристический fallback
        return "B" if lvl <= 50 else "A"

    def _on_help_clicked(self) -> None:
        """
        Переключиться из окна рефоржа в окно подсказок.

        Рефордж не скрываем через self.hide(), потому что MainWindow может воспринять
        Hide как закрытие рефоржа и снять/сломать shield.

        Вместо этого временно паркуем рефордж за экраном, открываем help,
        а при закрытии help напрямую возвращаем рефордж обратно.
        """
        try:
            self._hide_pick_item_popup()
        except Exception:
            pass

        try:
            self._hide_level_popup()
        except Exception:
            pass

        try:
            self._end_all_hovers()
        except Exception:
            pass

        main_owner = self.parent()

        try:
            reforge_pos = self.frameGeometry().topLeft()
        except Exception:
            reforge_pos = QPoint(0, 0)

        try:
            self._last_reforge_pos_before_help = QPoint(reforge_pos)
        except Exception:
            pass

        # лениво создаём help-окно
        if not hasattr(self, "_help_win") or self._help_win is None:
            self._help_win = UpgradeHelpWindow(parent=main_owner)
            self._help_win.set_help_config(self.HELP_UI_CONFIG_DEFAULT)
            self._help_win.select(kind="armor", grade="C")

        help_win = self._help_win

        def _restore_reforge_from_help(help_pos: Optional[QPoint] = None) -> None:
            """
            Прямой возврат из help в reforge.
            Делается идемпотентно, чтобы повторный on_exit не ломал состояние.
            """
            try:
                active = bool(getattr(self, "_help_switch_active", False))
            except Exception:
                active = False

            if not active:
                return

            try:
                self._help_switch_active = False
            except Exception:
                pass

            pos = help_pos

            if not isinstance(pos, QPoint):
                try:
                    if help_win is not None:
                        saved = getattr(help_win, "_last_global_pos", None)
                        if isinstance(saved, QPoint):
                            pos = QPoint(saved)
                except Exception:
                    pos = None

            if not isinstance(pos, QPoint):
                try:
                    saved = getattr(self, "_last_reforge_pos_before_help", None)
                    if isinstance(saved, QPoint):
                        pos = QPoint(saved)
                except Exception:
                    pos = None

            if not isinstance(pos, QPoint):
                pos = QPoint(0, 0)

            # Возвращаем рефордж на место help-окна.
            try:
                self.move(pos)
            except Exception:
                pass

            try:
                self.setWindowOpacity(1.0)
            except Exception:
                pass

            try:
                self.setEnabled(True)
            except Exception:
                pass

            try:
                self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            except Exception:
                pass

            try:
                self.setWindowModality(Qt.NonModal)
            except Exception:
                pass

            try:
                if hasattr(self, "setModal"):
                    self.setModal(False)
            except Exception:
                pass

            # Shield должен остаться активным, но разрешённым окном снова становится reforge.
            try:
                if main_owner is not None and hasattr(main_owner, "_ensure_reforge_shield"):
                    main_owner._ensure_reforge_shield()
            except Exception:
                pass

            try:
                if main_owner is not None:
                    main_owner._block_main_input = True
                    main_owner._block_allow_root = self
            except Exception:
                pass

            try:
                self.show()
                self.raise_()
                self.activateWindow()
                QApplication.setActiveWindow(self)
            except Exception:
                pass

            def _stack_shield_under_reforge() -> None:
                try:
                    shield = getattr(main_owner, "_reforge_shield", None) if main_owner is not None else None
                    if shield is not None and self.isVisible():
                        shield.show()
                        shield.raise_()
                        try:
                            shield.stackUnder(self)
                        except Exception:
                            pass
                        self.raise_()
                        self.activateWindow()
                        try:
                            QApplication.setActiveWindow(self)
                        except Exception:
                            pass
                except Exception:
                    pass

            _stack_shield_under_reforge()
            QTimer.singleShot(0, _stack_shield_under_reforge)
            QTimer.singleShot(30, _stack_shield_under_reforge)
            QTimer.singleShot(100, _stack_shield_under_reforge)

            try:
                self._reset_help_button_visual()
            except Exception:
                pass

        # Прямой callback в help-окно.
        # Это надёжнее, чем надеяться только на сигнал on_exit.
        try:
            help_win._return_to_reforge_callback = _restore_reforge_from_help
        except Exception:
            pass

        # Фолбэк через сигнал: если help закроется не через _close_clicked.
        try:
            help_win.on_exit.connect(lambda: _restore_reforge_from_help(None), Qt.ConnectionType.UniqueConnection)
        except Exception:
            try:
                help_win.on_exit.connect(lambda: _restore_reforge_from_help(None))
            except Exception:
                pass

        # Первое открытие help — на позиции текущего окна рефоржа.
        try:
            if not isinstance(getattr(help_win, "_last_global_pos", None), QPoint):
                help_win._last_global_pos = QPoint(reforge_pos)
        except Exception:
            pass

        # Включаем режим переключения.
        try:
            self._help_switch_active = True
        except Exception:
            pass

        # Не self.hide().
        # Паркуем рефордж далеко за экраном, чтобы MainWindow не снял reforge-shield.
        try:
            self.move(QPoint(-100000, -100000))
        except Exception:
            pass

        try:
            self.setWindowOpacity(0.01)
        except Exception:
            pass

        try:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception:
            pass

        # Shield должен остаться активным.
        try:
            if main_owner is not None and hasattr(main_owner, "_ensure_reforge_shield"):
                main_owner._ensure_reforge_shield()
        except Exception:
            pass

        # Открываем help.
        try:
            help_win.open_centered(owner=self)
        except Exception:
            try:
                help_win.show()
                help_win.raise_()
                help_win.activateWindow()
            except Exception:
                pass

        # Пока открыт help, именно он разрешён поверх shield.
        try:
            if main_owner is not None:
                main_owner._block_main_input = True
                main_owner._block_allow_root = help_win
        except Exception:
            pass

        def _stack_shield_under_help() -> None:
            try:
                shield = getattr(main_owner, "_reforge_shield", None) if main_owner is not None else None
                if shield is not None and help_win is not None and help_win.isVisible():
                    shield.show()
                    shield.raise_()
                    try:
                        shield.stackUnder(help_win)
                    except Exception:
                        pass
                    help_win.raise_()
                    help_win.activateWindow()
                    try:
                        QApplication.setActiveWindow(help_win)
                    except Exception:
                        pass
            except Exception:
                pass

        _stack_shield_under_help()
        QTimer.singleShot(0, _stack_shield_under_help)
        QTimer.singleShot(30, _stack_shield_under_help)
        QTimer.singleShot(100, _stack_shield_under_help)

        QTimer.singleShot(0, self._reset_help_button_visual)


class UpgradeHelpWindow(QWidget):
    on_exit = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.CustomizeWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setFixedSize(426, 612)

        # фон-картинка
        self.bg = QLabel(self)
        self.bg.setGeometry(0, 0, 426, 612)
        self.bg.setScaledContents(True)

        self._base_w = 426
        self._base_h = 612
        self._btn_specs: List[Dict[str, Any]] = []

        # крестик (геом. зададим из конфига)
        self.btn_close = QToolButton(self)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setAutoRaise(True)
        self.btn_close.setIconSize(QSize(24, 24))
        self.btn_close.setStyleSheet(
            "QToolButton{background:transparent;border:none}"
            "QToolButton:hover{background:transparent}"
            "QToolButton:pressed{background:transparent}"
        )
        self.btn_close.installEventFilter(self)

        # состояние/конфиг
        self._cfg: Dict[str, Any] = {}
        self._btns: Dict[str, QToolButton] = {}
        self._image_map_flat: Dict[str, str] = {}
        self._current_kind = "armor"
        self._current_grade = "C"

        # аккуратный стиль кнопок (без скачков размеров)
        self._BTN_STYLE = (
            "QToolButton{background: rgba(255,255,255,0.00);"
            "border:1px solid rgba(255,255,255,0.00);"
            "border-radius:4px; padding:2px 6px; color:#ddd;}"
            "QToolButton:hover{background: rgba(255,255,255,0.08);"
            "border:1px solid rgba(255,255,255,0.22);}"
            "QToolButton:checked{background: rgba(255,255,255,0.12);"
            "border:1px solid rgba(255,255,255,0.35); color:#fff;}"
        )

    # ---------- Публичный API ----------
    def set_help_config(self, cfg: Dict[str, Any]) -> None:
        self._cfg = dict(cfg or {})
        self._image_map_flat = self._normalize_image_map(self._cfg.get("images") or {})

        base = self._cfg.get("base_size") or [426, 612]
        self._base_w, self._base_h = int(base[0]), int(base[1])

        self._rebuild_close_button()  # создаём/обновляем кнопку закрытия (положение позже)
        self._rebuild_buttons_from_cfg()  # создаём кнопки (положение позже)
        self._apply_current_image()  # загрузит картинку и расставит всё по месту

    def select(self, *, kind: Optional[str] = None, grade: Optional[str] = None) -> None:
        if kind:
            self._current_kind = str(kind)
        if grade:
            self._current_grade = str(grade)
        self._apply_current_image()
        self._update_button_states()

    def open_centered(self, owner: Optional[QWidget] = None) -> None:
        """
        Открыть help-окно без Qt-модальности.

        Shield уже делает MainWindow, поэтому Qt.WindowModal/ApplicationModal
        здесь использовать нельзя — из-за них появляется системный звук Windows.
        """
        host = None
        if owner is not None:
            try:
                host = owner.window()
            except Exception:
                host = owner

        if self.parent() is None and host is not None:
            try:
                self.setParent(host, self.windowFlags())
            except Exception:
                pass

        try:
            self.setWindowModality(Qt.NonModal)
        except Exception:
            pass

        try:
            if hasattr(self, "setModal"):
                self.setModal(False)
        except Exception:
            pass

        try:
            self.setEnabled(True)
        except Exception:
            pass

        self._apply_current_image()

        pos = None

        # 1) если окно уже двигали/открывали — используем сохранённую позицию
        try:
            saved = getattr(self, "_last_global_pos", None)
            if isinstance(saved, QPoint):
                pos = QPoint(saved)
        except Exception:
            pos = None

        # 2) первое открытие из окна рефоржа — позиция старого рефоржа
        if pos is None and owner is not None:
            try:
                if isinstance(owner, UpgradeWindow):
                    saved = getattr(owner, "_last_reforge_pos_before_help", None)
                    if isinstance(saved, QPoint):
                        pos = QPoint(saved)
                    else:
                        pos = owner.frameGeometry().topLeft()
            except Exception:
                pos = None

        # 3) fallback — центр относительно owner
        if pos is None and owner is not None:
            try:
                og = owner.frameGeometry()
                pos = QPoint(
                    int(og.x() + (og.width() - self.width()) // 2),
                    int(og.y() + (og.height() - self.height()) // 2),
                )
            except Exception:
                pos = None

        # 4) fallback — центр экрана
        if pos is None:
            scr_obj = self.screen() or QApplication.primaryScreen()
            scr = scr_obj.availableGeometry() if scr_obj else QRect(0, 0, 1920, 1080)
            pos = QPoint(
                int(scr.x() + (scr.width() - self.width()) // 2),
                int(scr.y() + (scr.height() - self.height()) // 2),
            )

        # Не даём окну полностью уехать за экран
        try:
            scr_obj = QApplication.screenAt(pos) or self.screen() or QApplication.primaryScreen()
            scr = scr_obj.availableGeometry() if scr_obj else QRect(0, 0, 1920, 1080)

            x = min(max(pos.x(), scr.left()), max(scr.left(), scr.right() - self.width() + 1))
            y = min(max(pos.y(), scr.top()), max(scr.top(), scr.bottom() - self.height() + 1))
            pos = QPoint(int(x), int(y))
        except Exception:
            pass

        self.move(pos)
        self._last_global_pos = QPoint(pos)

        self.show()
        self.raise_()
        self.activateWindow()

    # ---------- Внутреннее ----------
    def _apply_current_image(self) -> None:
        default_img = getattr(
            UpgradeWindow,
            "HELP_DEFAULT_IMG",
            "resources/upgrade_bg/help_upgrades/одежда_С_класс.png",
        )

        key = f"{self._current_kind}|{self._current_grade}"
        raw_path = self._image_map_flat.get(key)

        path = self._resolve_help_path(raw_path) if raw_path else default_img
        pm = QPixmap(path)
        if pm.isNull():
            pm = QPixmap(default_img)

        # Сохраняем текущую позицию перед сменой картинки/размера,
        # чтобы переключение вкладок не двигало окно.
        old_pos = None
        try:
            if self.isVisible():
                old_pos = self.frameGeometry().topLeft()
        except Exception:
            old_pos = None

        img_w, img_h = pm.width(), pm.height()

        try:
            scr_obj = QApplication.screenAt(old_pos) if isinstance(old_pos, QPoint) else None
            scr_obj = scr_obj or self.screen() or QApplication.primaryScreen()
            scr = scr_obj.availableGeometry() if scr_obj else QRect(0, 0, 1920, 1080)
        except Exception:
            scr = QRect(0, 0, 1920, 1080)

        margin = 24
        max_w = max(200, scr.width() - margin * 2)
        max_h = max(200, scr.height() - margin * 2)

        scale = 1.0
        if img_w > max_w or img_h > max_h:
            scale = min(max_w / img_w, max_h / img_h)

        if scale < 1.0:
            disp_w = int(round(img_w * scale))
            disp_h = int(round(img_h * scale))
            disp_pm = pm.scaled(disp_w, disp_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            disp_w, disp_h = img_w, img_h
            disp_pm = pm

        self.setFixedSize(disp_w, disp_h)

        self.bg.setGeometry(0, 0, disp_w, disp_h)
        self.bg.setPixmap(disp_pm)
        self.bg.lower()

        self._relayout_controls(disp_w, disp_h)

        try:
            self.btn_close.raise_()
        except Exception:
            pass

        try:
            for b in self._btns.values():
                b.raise_()
        except Exception:
            pass

        # После смены картинки/размера оставляем окно там, где оно было.
        if isinstance(old_pos, QPoint):
            try:
                x = min(max(old_pos.x(), scr.left()), max(scr.left(), scr.right() - self.width() + 1))
                y = min(max(old_pos.y(), scr.top()), max(scr.top(), scr.bottom() - self.height() + 1))
                new_pos = QPoint(int(x), int(y))
                self.move(new_pos)
                self._last_global_pos = QPoint(new_pos)
            except Exception:
                pass

    def _resolve_help_path(self, path: str) -> str:
        if not path:
            return path
        if QFileInfo(path).exists():
            return path
        # пробуем вариант с заменой латинских A/B/C на кириллические А/В/С и наоборот
        swap = str.maketrans({
            "A": "А", "B": "В", "C": "С",
            "a": "а", "b": "в", "c": "с",
            "А": "A", "В": "B", "С": "C",
            "а": "a", "в": "b", "с": "c",
        })
        alt = path.translate(swap)
        if QFileInfo(alt).exists():
            return alt
        return path  # вернём оригинал — дальше сработает фоллбэк

    @staticmethod
    def _normalize_image_map(image_map: Dict[str, Any]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for k, v in (image_map or {}).items():
            if isinstance(v, dict):
                for subk, path in v.items():
                    out[f"{k}|{subk}"] = str(path)
            else:
                out[str(k)] = str(v)
        return out

    def _rebuild_close_button(self) -> None:
        # саму кнопку уже создали в __init__, здесь ничего кроме проверки не нужно
        if not isinstance(self.btn_close, QToolButton):
            self.btn_close = QToolButton(self)
            self.btn_close.setCursor(Qt.PointingHandCursor)
            self.btn_close.setAutoRaise(True)
            self.btn_close.setIconSize(QSize(24, 24))
            #self.btn_close.clicked.connect(self._close_clicked)
            try:
                self.btn_close.setIcon(QIcon("resources/helper_buttons/close_button_active.png"))
            except Exception:
                pass

    def _rebuild_close_from_cfg(self) -> None:
        rect = (self._cfg.get("close") or {}).get("rect") or [353, 2, 24, 24]
        self.btn_close.setGeometry(QRect(*[int(x) for x in rect]))

    def _relayout_controls(self, win_w: int, win_h: int) -> None:
        sx = win_w / float(self._base_w or 1)
        sy = win_h / float(self._base_h or 1)

        # close
        close_rect = (self._cfg.get("close") or {}).get("rect") or [353, 2, 24, 24]
        cx, cy, cw, ch = [int(v) for v in close_rect]
        gx, gy = int(round(cx * sx)), int(round(cy * sy))
        gw, gh = max(1, int(round(cw * sx))), max(1, int(round(ch * sy)))
        self.btn_close.setGeometry(gx, gy, gw, gh)
        self.btn_close.setIconSize(QSize(gw, gh))  # чтобы иконка не «торчала» за границы

        # buttons (категории/классы)
        for spec in self._btn_specs:
            btn = self._btns.get(spec["id"])
            if not btn:
                continue
            x, y, w, h = [int(v) for v in (spec.get("rect") or [0, 0, 0, 0])]
            btn.setGeometry(int(round(x * sx)), int(round(y * sy)),
                            max(1, int(round(w * sx))), max(1, int(round(h * sy))))

    def eventFilter(self, obj, ev):
        if not hasattr(self, "_close_armed"):
            self._close_armed = False

        if obj is self.btn_close:
            if ev.type() == QEvent.Enter:
                self.btn_close.setIcon(QIcon("resources/helper_buttons/close_button_active.png"))
                return True

            elif ev.type() in (QEvent.Leave, QEvent.Hide):
                self.btn_close.setIcon(QIcon())
                self._close_armed = False
                return True

            elif ev.type() == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
                self._close_armed = True
                return True

            elif ev.type() == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
                try:
                    inside = self.btn_close.rect().contains(ev.position().toPoint())
                except Exception:
                    try:
                        inside = self.btn_close.rect().contains(ev.pos())
                    except Exception:
                        inside = False

                armed = self._close_armed
                self._close_armed = False

                if armed and inside:
                    self._close_clicked()
                return True

            elif ev.type() == QEvent.MouseButtonDblClick:
                return True

        return super().eventFilter(obj, ev)

    def hideEvent(self, e):
        try:
            self._last_global_pos = self.frameGeometry().topLeft()
        except Exception:
            pass

        try:
            self._help_dragging = False
            self.setCursor(Qt.ArrowCursor)
        except Exception:
            pass

        try:
            self.btn_close.setIcon(QIcon())
        except Exception:
            pass

        super().hideEvent(e)

    def _rebuild_buttons_from_cfg(self) -> None:
        # удалить старые
        for b in self._btns.values():
            b.setParent(None); b.deleteLater()
        self._btns.clear(); self._btn_specs.clear()

        self._grp_kind = QButtonGroup(self);  self._grp_kind.setExclusive(True)
        self._grp_grade = QButtonGroup(self); self._grp_grade.setExclusive(True)

        for spec in (self._cfg.get("buttons") or []):
            bid = str(spec.get("id") or "")
            if not bid: continue
            self._btn_specs.append(spec)

            set_dict = dict(spec.get("set") or {})

            btn = QToolButton(self)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._BTN_STYLE)
            btn.setCheckable(True)

            # привяжем к нужной группе
            if "kind" in set_dict:
                self._grp_kind.addButton(btn)
            if "grade" in set_dict:
                self._grp_grade.addButton(btn)

            # безопасно ловим переключение
            btn.toggled.connect(lambda checked, s=set_dict: checked and self._on_btn_clicked(s))
            self._btns[bid] = btn

        self._update_button_states()

    def _on_btn_clicked(self, set_dict: Dict[str, Any]) -> None:
        kind = self._current_kind
        grade = self._current_grade
        if "kind" in set_dict:  kind = str(set_dict["kind"])
        if "grade" in set_dict: grade = str(set_dict["grade"])
        self.select(kind=kind, grade=grade)

    def _update_button_states(self) -> None:
        # выставляем checked у кнопок с текущими kind/grade
        btn_specs = self._cfg.get("buttons") or []
        for i, spec in enumerate(btn_specs):
            b = list(self._btns.values())[i]
            set_dict = spec.get("set") or {}
            checked = False
            if "kind" in set_dict and str(set_dict["kind"]) == self._current_kind:
                checked = True
            if "grade" in set_dict and str(set_dict["grade"]) == self._current_grade:
                checked = True
            b.setChecked(checked)

    def _close_clicked(self) -> None:
        try:
            pos = self.frameGeometry().topLeft()
            self._last_global_pos = QPoint(pos)
        except Exception:
            pos = None

        try:
            self._help_dragging = False
            self.setCursor(Qt.ArrowCursor)
        except Exception:
            pass

        # Сначала напрямую возвращаем reforge.
        # Это важно: если сначала сделать self.hide(), Qt может активировать MainWindow,
        # и пользователь увидит "залипший" shield без окна рефоржа.
        cb = None
        try:
            cb = getattr(self, "_return_to_reforge_callback", None)
        except Exception:
            cb = None

        if callable(cb):
            try:
                cb(QPoint(pos) if isinstance(pos, QPoint) else None)
            except Exception:
                pass

        self.hide()

        try:
            self.on_exit.emit()
        except Exception:
            pass

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            try:
                pos = e.position().toPoint()
            except Exception:
                try:
                    pos = e.pos()
                except Exception:
                    pos = QPoint()

            child = self.childAt(pos)

            # Не начинаем перетаскивание, если кликнули по крестику
            # или по кнопкам выбора категории/класса.
            blocked = False
            cur = child
            while cur is not None:
                if cur is self.btn_close:
                    blocked = True
                    break

                try:
                    if cur in set(self._btns.values()):
                        blocked = True
                        break
                except Exception:
                    pass

                try:
                    cur = cur.parentWidget()
                except Exception:
                    cur = None

            if not blocked:
                try:
                    self._help_dragging = True
                    self._help_drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    self.setCursor(Qt.SizeAllCursor)
                    e.accept()
                    return
                except Exception:
                    self._help_dragging = False

        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        try:
            dragging = bool(getattr(self, "_help_dragging", False))
        except Exception:
            dragging = False

        if dragging and (e.buttons() & Qt.LeftButton):
            try:
                new_pos = e.globalPosition().toPoint() - getattr(self, "_help_drag_offset", QPoint())
                self.move(new_pos)
                self._last_global_pos = QPoint(new_pos)
                e.accept()
                return
            except Exception:
                pass

        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            try:
                self._help_dragging = False
                self._last_global_pos = self.frameGeometry().topLeft()
                self.setCursor(Qt.ArrowCursor)
                e.accept()
                return
            except Exception:
                pass

        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
            try:
                e.accept()
            except Exception:
                pass
            self._close_clicked()
            return

        super().keyPressEvent(e)