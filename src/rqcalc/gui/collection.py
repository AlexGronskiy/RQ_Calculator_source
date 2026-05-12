# есть проблема когда я нажимаю
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, List, Tuple, Any

from PySide6.QtCore import Qt, QRect, QEvent, Signal, QPoint
from PySide6.QtGui import QPixmap, QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QWidget,
    QSizePolicy,
    QVBoxLayout, QApplication,
)

def _resolve_resource(rel_path: str) -> str:
    """
    Пытаемся найти ресурс:
      1) как есть (от cwd)
      2) относительно родителей текущего файла (на случай src/rqcalc/gui)
    """
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


class CollectionMenu(QFrame):
    """
    Меню коллекций:
      - 4 вкладки (costum/pets/mounts/trophy) -> меняют фоновую картинку
      - 4 кликабельные зоны переключения
      - 2 зоны закрытия
      - внутри каждой вкладки есть свой QScrollArea
      - плитки из БД (пока только Equipment_Id)
    """

    closed = Signal()
    tab_changed = Signal(str)

    TAB_COSTUM = "costum"
    TAB_PETS = "pets"
    TAB_MOUNTS = "mounts"
    TAB_TROPHY = "trophy"

    TABS: List[str] = [TAB_COSTUM, TAB_PETS, TAB_MOUNTS, TAB_TROPHY]
    TAB_TO_GROUP_ID: Dict[str, int] = {
        TAB_COSTUM: 1,  # CollectedGroup.Id = 1
        TAB_PETS: 2,    # CollectedGroup.Id = 2
        TAB_MOUNTS: 3,  # CollectedGroup.Id = 3
        TAB_TROPHY: 4,  # CollectedGroup.Id = 4
    }

    # целевой размер окна коллекций
    DEFAULT_SIZE: Tuple[int, int] = (691, 570)

    MENU_IMAGES = {
        TAB_COSTUM: r"resources/collection/collection_menu_costum.png",
        TAB_PETS: r"resources/collection/collection_menu_pets.png",
        TAB_MOUNTS: r"resources/collection/collection_menu_mounts.png",
        TAB_TROPHY: r"resources/collection/collection_menu_trophy.png",
    }

    CLOSE_ACTIVE_IMAGE = r"resources/helper_buttons/close_button_active.png"
    CLOSE2_IMAGE = r"resources/collection/close.png"

    PLATE_IMAGE = r"resources/collection/collection_plate.png"
    TROPHY_PLATE_IMAGE = r"resources/collection/trophy_plate.png"
    PLATE_ACTIVE_IMAGE = r"resources/collection/collection_plate_active.png"
    BONUS_PLATE_IMAGE = r"resources/collection/collection_plate_bonus.png"

    IN_COL_IMAGE = r"resources/collection/in_col.png"
    ALL_IN_COL_ACTIVE_IMAGE = r"resources/collection/all_in_col_active.png"

    @dataclass
    class LayoutConfig:
        menu_size: Tuple[int, int]
        tab_rects: Dict[str, QRect]
        close1_rect: QRect
        close2_rect: QRect
        scroll_rect: QRect

        # --- настройки “плитки” ---
        tile_icon_rect: QRect  # default 48x48 (только группы 1-3)
        tile_name_rect: QRect  # имя для equipment/pet
        tile_name_rect_trophy: QRect  # имя для trophy (отдельная разметка)
        tile_bonus_rect: QRect  # область бонусов (строки из CollectedItemBonus)
        tile_toggle_rect: QRect  # 19x26 (группы 1-3)
        tile_toggle_rect_trophy: QRect  # 19x26 (только трофеи)

        # --- предпросмотр костюма (только TAB_COSTUM) ---
        costume_preview_rect: QRect  # 210x284

        # --- кнопка "добавить всё" ---
        add_all_rect: QRect

    @staticmethod
    def default_layout() -> "CollectionMenu.LayoutConfig":
        w, h = CollectionMenu.DEFAULT_SIZE

        tab_rects = {
            CollectionMenu.TAB_COSTUM: QRect(92, 40, 95, 28),
            CollectionMenu.TAB_PETS: QRect(188, 40, 93, 28),
            CollectionMenu.TAB_MOUNTS: QRect(282, 40, 104, 28),
            CollectionMenu.TAB_TROPHY: QRect(388, 40, 85, 28),
        }

        close1 = QRect(654, 3, 24, 24)
        close2 = QRect(526, 520, 140, 32)

        scroll_rect = QRect(42, 118, 316, 367)

        # Настройки плитки (группы 1-3)
        tile_icon_rect = QRect(10, 10, 48, 48)
        tile_name_rect = QRect(68, 6, 192, 38)
        tile_toggle_rect = QRect(243, 29, 19, 26)
        tile_bonus_rect = QRect(10, 10, 240, 14)

        # Настройки для трофеев (группа 4)
        tile_name_rect_trophy = QRect(10, 6, 192, 38)
        tile_toggle_rect_trophy = QRect(248, 5, 19, 26)

        costume_preview_rect = QRect(410, 150, 210, 284)

        # Кнопка "добавить всё" — кликабельная зона (без текста)
        add_all_rect = QRect(485, 518, 35, 35)

        return CollectionMenu.LayoutConfig(
            menu_size=(w, h),
            tab_rects=tab_rects,
            close1_rect=close1,
            close2_rect=close2,
            scroll_rect=scroll_rect,
            tile_icon_rect=tile_icon_rect,
            tile_name_rect=tile_name_rect,
            tile_name_rect_trophy=tile_name_rect_trophy,
            tile_bonus_rect=tile_bonus_rect,
            tile_toggle_rect=tile_toggle_rect,
            tile_toggle_rect_trophy=tile_toggle_rect_trophy,
            costume_preview_rect=costume_preview_rect,
            add_all_rect=add_all_rect,
        )

    def __init__(
            self,
            parent: Optional[QWidget] = None,
            *,
            layout: Optional["CollectionMenu.LayoutConfig"] = None,
            conn=None,
    ):
        super().__init__(parent)
        self.setObjectName("CollectionMenu")

        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")

        self._layout = layout or self.default_layout()
        self._active_tab: str = self.TAB_COSTUM
        self._active_group_id: int = int(self.TAB_TO_GROUP_ID.get(self._active_tab, 0))

        self._conn = conn

        self._pixmaps: Dict[str, QPixmap] = {}
        self._plate_cache: Dict[str, QPixmap] = {}
        self._db_image_cache: Dict[int, QPixmap] = {}
        self._close_active_pix: Optional[QPixmap] = None
        self._close2_pix: Optional[QPixmap] = None
        self._in_col_pix: Optional[QPixmap] = None

        # NEW: картинка активного "добавить всё"
        self._all_in_col_active_pix: Optional[QPixmap] = None

        self._close1_down: bool = False
        self._close2_down: bool = False

        self._add_all_down: bool = False

        # NEW: состояние кнопки "добавить всё"
        self._add_all_active: bool = False
        self._add_all_added_ids: set[int] = set()  # что именно добавила кнопка, чтобы убирать только это

        self._built_groups: set[int] = set()

        self._selected_by_group: Dict[int, int] = {}
        self._in_col_set: set[int] = set()

        # восстановим состояние "добавлено в коллекцию" (CollectedItem.Id)
        try:
            app = QApplication.instance()
            raw = app.property("collection_in_col_ids") if app is not None else None
        except Exception:
            raw = None

        if isinstance(raw, (list, tuple, set)):
            restored = set()
            for x in raw:
                try:
                    v = int(x)
                except Exception:
                    continue
                if v > 0:
                    restored.add(v)
            if restored:
                self._in_col_set = restored

        self._tile_bg_by_group: Dict[int, Dict[int, QLabel]] = {}
        self._tile_toggle_by_id: Dict[int, QLabel] = {}
        self._costume_img_by_id: Dict[int, int] = {}

        self._bg = QLabel(self)
        self._bg.setObjectName("CollectionMenuBg")
        self._bg.setScaledContents(False)
        self._bg.setStyleSheet("background: transparent;")
        self._bg.setAutoFillBackground(False)

        self._costume_preview = QLabel(self)
        self._costume_preview.setObjectName("costume_preview")
        self._costume_preview.setStyleSheet("background: transparent; border: none;")
        self._costume_preview.setScaledContents(False)
        self._costume_preview.hide()
        self._costume_preview_image_id: int = 0

        self._tab_zones: Dict[str, QFrame] = {}
        self._build_tab_zones()

        self._close1 = QLabel(self)
        self._close2 = QLabel(self)
        self._build_close_zones()

        self._add_all = QLabel(self)
        self._add_all.setObjectName("add_all_button")
        self._add_all.setText("")
        self._add_all.setCursor(Qt.PointingHandCursor)
        self._add_all.setScaledContents(False)
        self._add_all.setStyleSheet("background: transparent; border: none;")
        self._add_all.installEventFilter(self)

        self._scrolls: Dict[str, QScrollArea] = {}
        self._build_scroll_areas()

        self.apply_layout()
        self.set_tab(self.TAB_COSTUM)

    # ------------------------- public API -------------------------

    def set_tab(self, tab: str) -> None:
        tab = str(tab or "").strip().lower()
        if tab not in self.TABS:
            return

        self._active_tab = tab
        self._active_group_id = int(self.TAB_TO_GROUP_ID.get(tab, 0))

        self._apply_background_for_tab(tab)
        self._apply_scroll_visibility(tab)

        # предпросмотр костюма только на вкладке костюмов
        if self._active_group_id == 1:
            self._costume_preview.show()
            if int(self._costume_preview_image_id or 0) > 0:
                self._apply_costume_preview(self._costume_preview_image_id)
            else:
                self._costume_preview.clear()
        else:
            self._costume_preview.hide()

        # ДЕБАГ: чтобы кеш built_groups не прятал изменения/ошибки на трофеях
        if bool(getattr(self, "DEBUG_REBUILD_ON_TAB", False)):
            try:
                self._built_groups.discard(self._active_group_id)
            except Exception:
                pass

        self._ensure_group_built(self._active_group_id)
        self.tab_changed.emit(tab)

    def current_tab(self) -> str:
        return self._active_tab

    def current_group_id(self) -> int:
        return int(getattr(self, "_active_group_id", 0))

    @classmethod
    def group_id_for_tab(cls, tab: str) -> int:
        tab = str(tab or "").strip().lower()
        return int(cls.TAB_TO_GROUP_ID.get(tab, 0))

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

        for _tab, sc in self._scrolls.items():
            sc.setGeometry(self._layout.scroll_rect)

        self._costume_preview.setGeometry(self._layout.costume_preview_rect)

        self._add_all.setGeometry(self._layout.add_all_rect)

        # NEW: если кнопка активна — держим картинку под текущий размер
        if bool(getattr(self, "_add_all_active", False)):
            pm = self._all_in_col_active_pixmap()
            if not pm.isNull():
                self._add_all.setPixmap(pm.scaled(self._add_all.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
            else:
                self._add_all.clear()
        else:
            self._add_all.clear()

        self._bg.lower()
        for w in self._tab_zones.values():
            w.raise_()
        self._close1.raise_()
        self._close2.raise_()
        self._add_all.raise_()
        for sc in self._scrolls.values():
            sc.raise_()
        self._costume_preview.raise_()

        self._apply_background_for_tab(self._active_tab)

    # ------------------------- build UI -------------------------

    def _build_tab_zones(self) -> None:
        colors = {
            self.TAB_COSTUM: "rgba(255, 0,   0,   0)",
            self.TAB_PETS:   "rgba(0,   255, 0,   0)",
            self.TAB_MOUNTS: "rgba(0,   0,   255, 0)",
            self.TAB_TROPHY: "rgba(255, 255, 0,   0)",
        }

        for tab in self.TABS:
            z = QFrame(self)
            z.setObjectName(f"tab_zone_{tab}")
            z.setStyleSheet(
                f"background-color: {colors.get(tab, 'rgba(255,255,255,0)')}; "
                f"border: 1px solid rgba(0,0,0,0);"
            )
            z.setCursor(Qt.PointingHandCursor)
            z.installEventFilter(self)
            self._tab_zones[tab] = z

    def _build_close_zones(self) -> None:
        self._close1.setObjectName("close_zone_1")
        self._close2.setObjectName("close_zone_2")

        for w in (self._close1, self._close2):
            w.setStyleSheet("background: transparent; border: none;")
            w.setScaledContents(False)
            w.setCursor(Qt.PointingHandCursor)
            w.installEventFilter(self)

    def _build_scroll_areas(self) -> None:
        for tab in self.TABS:
            sc = QScrollArea(self)
            sc.setObjectName(f"collection_scroll_{tab}")

            # убрать рамку/обводку QScrollArea
            sc.setFrameShape(QFrame.NoFrame)
            sc.setFrameShadow(QFrame.Plain)
            sc.setLineWidth(0)
            sc.setMidLineWidth(0)

            sc.setWidgetResizable(True)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sc.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

            # на всякий случай — без бордера в стиле
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
            cont.setObjectName(f"collection_scroll_container_{tab}")
            cont.setStyleSheet("background: transparent;")
            cont.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

            v = QVBoxLayout(cont)
            v.setContentsMargins(4, 4, 0, 4)
            v.setSpacing(2)
            cont.setLayout(v)

            sc.setWidget(cont)
            self._scrolls[tab] = sc

    # ------------------------- resources -------------------------

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

    def _in_col_pixmap(self) -> QPixmap:
        if self._in_col_pix is not None:
            return self._in_col_pix
        self._in_col_pix = QPixmap(_resolve_resource(self.IN_COL_IMAGE))
        return self._in_col_pix

    def _all_in_col_active_pixmap(self) -> QPixmap:
        pm = getattr(self, "_all_in_col_active_pix", None)
        if pm is not None:
            return pm
        self._all_in_col_active_pix = QPixmap(_resolve_resource(self.ALL_IN_COL_ACTIVE_IMAGE))
        return self._all_in_col_active_pix

    def _plate_pixmap_for_group(self, group_id: int) -> QPixmap:
        gid = int(group_id or 0)
        rel = self.TROPHY_PLATE_IMAGE if gid == 4 else self.PLATE_IMAGE

        if rel in self._plate_cache:
            return self._plate_cache[rel]

        resolved = _resolve_resource(rel)
        pm = QPixmap(resolved)

        self._plate_cache[rel] = pm
        return pm

    def _plate_active_pixmap(self, base_size: QSizePolicy | None = None) -> QPixmap:
        # base_size не используется: активная плитка подгоняется под размер базовой
        rel = self.PLATE_ACTIVE_IMAGE
        if rel in self._plate_cache:
            return self._plate_cache[rel]
        pm = QPixmap(_resolve_resource(rel))
        self._plate_cache[rel] = pm
        return pm

    def _bonus_plate_pixmap(self) -> QPixmap:
        rel = self.BONUS_PLATE_IMAGE
        if rel in self._plate_cache:
            return self._plate_cache[rel]
        pm = QPixmap(_resolve_resource(rel))
        self._plate_cache[rel] = pm
        return pm

    def _apply_background_for_tab(self, tab: str) -> None:
        pm = self._pixmap_for_tab(tab)
        if pm.isNull():
            self._bg.clear()
            return
        self._bg.setPixmap(pm.scaled(self._bg.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

    def _apply_scroll_visibility(self, tab: str) -> None:
        for t, sc in self._scrolls.items():
            sc.setVisible(t == tab)

    # ------------------------- DB helpers -------------------------

    def _get_db_conn(self):
        c = getattr(self, "_conn", None)
        if c is not None:
            return c

        p = self.parentWidget()
        if p is not None:
            c = getattr(p, "_conn", None)
            if c is not None:
                self._conn = c
                return c

            c = getattr(getattr(p, "data", None), "conn", None)
            if c is not None:
                self._conn = c
                return c

            pp = p.parentWidget()
            c = getattr(getattr(pp, "data", None), "conn", None) if pp is not None else None
            if c is not None:
                self._conn = c
                return c

        return None

    def _pixmap_from_db_image_id(self, image_id: int) -> QPixmap:
        iid = int(image_id or 0)
        if iid <= 0:
            return QPixmap()
        if iid in self._db_image_cache:
            return self._db_image_cache[iid]

        conn = self._get_db_conn()
        if conn is None:
            return QPixmap()

        try:
            row = conn.execute("SELECT Data FROM Image WHERE Id=?", (iid,)).fetchone()
        except Exception:
            row = None

        if not row:
            self._db_image_cache[iid] = QPixmap()
            return self._db_image_cache[iid]

        try:
            data = row[0]
            if isinstance(data, memoryview):
                data = data.tobytes()
            elif not isinstance(data, (bytes, bytearray)):
                data = bytes(data)
        except Exception:
            self._db_image_cache[iid] = QPixmap()
            return self._db_image_cache[iid]

        pm = QPixmap()
        try:
            pm.loadFromData(data)
        except Exception:
            pm = QPixmap()

        self._db_image_cache[iid] = pm
        return pm

    def _query_equipment_items_for_group(self, group_id: int) -> List[Dict[str, Any]]:
        """
        Возвращает элементы CollectedItem по OrderIndex.
        Поддерживает Equipment/Pet/Trophy.

        ВАЖНО: для трофеев делаем авто-поиск колонок в Trophy через PRAGMA,
        и НЕ отбрасываем строки, даже если не смогли прочитать Trophy (чтобы плитки появлялись).
        """
        conn = self._get_db_conn()
        if conn is None:
            return []

        gid = int(group_id or 0)
        if gid <= 0:
            return []


        rows = conn.execute(
            "SELECT Id, Equipment_Id, Pet_Id, Trophy_Id FROM CollectedItem WHERE Group_Id=? ORDER BY OrderIndex",
            (gid,),
        ).fetchall()

        # --- подготовим колонки Trophy (имя + картинка), если таблица существует ---
        trophy_table_exists = False
        trophy_cols: List[Tuple[str, str]] = []  # (name, type)
        try:
            trophy_table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='Trophy' LIMIT 1"
            ).fetchone() is not None
        except Exception:
            trophy_table_exists = False

        trophy_name_col = None
        trophy_img_col = None

        if trophy_table_exists:
            try:
                info = conn.execute("PRAGMA table_info('Trophy')").fetchall()
                # info: (cid, name, type, notnull, dflt_value, pk)
                trophy_cols = [(str(r[1]), str(r[2] or "")) for r in info]
            except Exception:
                trophy_cols = []

            # имя: сначала пробуем стандартные
            for cand in ("Name", "Title", "DisplayName"):
                if any(c[0] == cand for c in trophy_cols):
                    trophy_name_col = cand
                    break

            # если не нашли — возьмём первую TEXT/строковую
            if trophy_name_col is None:
                for n, t in trophy_cols:
                    if "CHAR" in t.upper() or "TEXT" in t.upper():
                        trophy_name_col = n
                        break

            # картинка: сначала пробуем стандартные
            for cand in ("Image_Id", "ToolTipImage_Id", "IconImage_Id", "Icon_Id", "ImageId", "ImageID"):
                if any(c[0] == cand for c in trophy_cols):
                    trophy_img_col = cand
                    break

            # если не нашли — возьмём первую колонку, содержащую Image/Icon и заканчивающуюся на _Id
            if trophy_img_col is None:
                for n, _t in trophy_cols:
                    nn = n.lower()
                    if (("image" in nn) or ("icon" in nn)) and nn.endswith("_id"):
                        trophy_img_col = n
                        break

        out: List[Dict[str, Any]] = []

        for r in rows or []:
            try:
                collected_id = int(r[0] or 0)
                eq_id = int(r[1] or 0) if r[1] is not None else 0
                pet_id = int(r[2] or 0) if r[2] is not None else 0
                trophy_id = int(r[3] or 0) if r[3] is not None else 0
            except Exception:
                continue

            if collected_id <= 0:
                continue

            # Equipment
            if eq_id > 0:
                try:
                    eq = conn.execute(
                        "SELECT Name, Image_Id, CostumeImage_Id FROM Equipment WHERE Id=?",
                        (eq_id,),
                    ).fetchone()
                except Exception:
                    eq = None

                if not eq:
                    continue

                try:
                    name = str(eq[0] or "")
                    image_id = int(eq[1] or 0) if eq[1] is not None else 0
                    costume_image_id = int(eq[2] or 0) if eq[2] is not None else 0
                except Exception:
                    continue

                out.append(
                    {"CollectedId": collected_id, "Kind": "equipment", "Name": name, "ImageId": image_id,
                     "CostumeImageId": costume_image_id}
                )
                continue

            # Pet
            if pet_id > 0:
                try:
                    pet = conn.execute("SELECT Name, Image_Id FROM Pet WHERE Id=?", (pet_id,)).fetchone()
                except Exception:
                    pet = None

                if not pet:
                    continue

                try:
                    name = str(pet[0] or "")
                    image_id = int(pet[1] or 0) if pet[1] is not None else 0
                except Exception:
                    continue

                out.append({"CollectedId": collected_id, "Kind": "pet", "Name": name, "ImageId": image_id,
                            "CostumeImageId": 0})
                continue

            # Trophy
            if trophy_id > 0:
                name = f"Трофей #{trophy_id}"
                image_id = 0

                if trophy_table_exists and trophy_name_col:
                    # строим SELECT безопасно: имена колонок взяты из PRAGMA
                    if trophy_img_col:
                        tr = conn.execute(
                            f"SELECT {trophy_name_col}, {trophy_img_col} FROM Trophy WHERE Id=?",
                            (trophy_id,),
                        ).fetchone()
                    else:
                        tr = conn.execute(
                            f"SELECT {trophy_name_col} FROM Trophy WHERE Id=?",
                            (trophy_id,),
                        ).fetchone()

                    if tr:
                        try:
                            name = str(tr[0] or name)
                            if trophy_img_col and len(tr) > 1:
                                image_id = int(tr[1] or 0) if tr[1] is not None else 0
                        except Exception:
                            pass

                out.append({"CollectedId": collected_id, "Kind": "trophy", "Name": name, "ImageId": image_id,
                            "CostumeImageId": 0})
                continue

        return out

    # ------------------------- build items -------------------------

    def _ensure_group_built(self, group_id: int) -> None:
        gid = int(group_id or 0)
        if gid <= 0:
            return
        if gid in self._built_groups:
            return
        self._rebuild_group_items(gid)
        self._built_groups.add(gid)

    def _tab_for_group_id(self, group_id: int) -> Optional[str]:
        gid = int(group_id or 0)
        for t, g in (self.TAB_TO_GROUP_ID or {}).items():
            if int(g) == gid:
                return t
        return None

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

    def _tile_is_active(self, group_id: int, collected_id: int) -> bool:
        gid = int(group_id or 0)
        cid = int(collected_id or 0)
        if cid <= 0:
            return False
        if cid in self._in_col_set:
            return True
        sel = int(self._selected_by_group.get(gid, 0))
        return sel == cid

    def _apply_tile_bg(self, group_id: int, collected_id: int) -> None:
        gid = int(group_id or 0)
        cid = int(collected_id or 0)
        bg = (self._tile_bg_by_group.get(gid) or {}).get(cid)
        if bg is None:
            return

        base = self._plate_pixmap_for_group(gid)
        if base.isNull():
            bg.clear()
            return

        if gid == 4:
            # пока для трофеев активной плитки нет ассета — оставляем базу
            pm = base
        else:
            if self._tile_is_active(gid, cid):
                act = self._plate_active_pixmap()
                pm = act.scaled(base.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation) if not act.isNull() else base
            else:
                pm = base

        bg.setPixmap(pm)

    def _refresh_group_bgs(self, group_id: int) -> None:
        gid = int(group_id or 0)
        for cid in (self._tile_bg_by_group.get(gid) or {}).keys():
            self._apply_tile_bg(gid, cid)

    def _apply_toggle_icon(self, collected_id: int) -> None:
        cid = int(collected_id or 0)
        w = self._tile_toggle_by_id.get(cid)
        if w is None:
            return

        if cid in self._in_col_set:
            pm = self._in_col_pixmap()
            if pm.isNull():
                w.clear()
                return
            w.setPixmap(pm.scaled(w.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        else:
            w.clear()

    def _apply_costume_preview(self, costume_image_id: int) -> None:
        iid = int(costume_image_id or 0)
        if iid <= 0:
            self._costume_preview.clear()
            return

        pm = self._pixmap_from_db_image_id(iid)
        if pm.isNull():
            self._costume_preview.clear()
            return

        r = self._layout.costume_preview_rect
        # обычно лучше сохранять пропорции
        scaled = pm.scaled(r.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._costume_preview.setPixmap(scaled)

    def _rebuild_group_items(self, group_id: int) -> None:
        gid = int(group_id or 0)
        tab = self._tab_for_group_id(gid)
        if not tab:
            return

        sc = self._scrolls.get(tab)
        if sc is None:
            return

        cont = sc.widget()
        if cont is None:
            return

        lay = cont.layout()
        if lay is None:
            return

        # очистка UI
        self._clear_layout(lay)
        self._tile_bg_by_group[gid] = {}

        items = self._query_equipment_items_for_group(gid)
        base_plate = self._plate_pixmap_for_group(gid)

        if not items or base_plate.isNull():
            lay.addStretch(1)
            return

        # -------------------- БОНУСЫ: массовая загрузка для группы --------------------
        bonus_lines_by_cid: Dict[int, List[str]] = {}

        conn = self._get_db_conn()
        collected_ids: List[int] = []
        for it in items:
            try:
                cid0 = int(it.get("CollectedId", 0))
            except Exception:
                cid0 = 0
            if cid0 > 0:
                collected_ids.append(cid0)

        if conn is not None and collected_ids:
            try:
                ph = ",".join(["?"] * len(collected_ids))
                rows = conn.execute(
                    f"""
                    SELECT CollectedItem_Id, Type_Id, Value
                    FROM CollectedItemBonus
                    WHERE CollectedItem_Id IN ({ph})
                    ORDER BY CollectedItem_Id, OrderIndex
                    """,
                    tuple(collected_ids),
                ).fetchall()
            except Exception:
                rows = []

            type_ids: List[int] = []
            bonus_raw: List[Tuple[int, int, int]] = []
            for r in rows or []:
                try:
                    if hasattr(r, "keys"):
                        c_id = int(r["CollectedItem_Id"])
                        t_id = int(r["Type_Id"])
                        val = int(r["Value"])
                    else:
                        c_id = int(r[0])
                        t_id = int(r[1])
                        val = int(r[2])
                except Exception:
                    continue
                bonus_raw.append((c_id, t_id, val))
                type_ids.append(t_id)

            templates: Dict[int, str] = {}
            uniq_types = sorted({int(x) for x in type_ids if int(x) > 0})
            if uniq_types:
                try:
                    ph2 = ",".join(["?"] * len(uniq_types))
                    trows = conn.execute(
                        f"SELECT Id, Template FROM BonusType WHERE Id IN ({ph2})",
                        tuple(uniq_types),
                    ).fetchall()
                except Exception:
                    trows = []

                for r in trows or []:
                    try:
                        if hasattr(r, "keys"):
                            tid = int(r["Id"])
                            tpl = str(r["Template"] or "")
                        else:
                            tid = int(r[0])
                            tpl = str(r[1] or "")
                    except Exception:
                        continue
                    templates[tid] = tpl

            for c_id, t_id, val in bonus_raw:
                tpl = templates.get(int(t_id), "")
                txt = tpl.replace("{0}", "+"+str(val)) if tpl else str(val)
                bonus_lines_by_cid.setdefault(int(c_id), []).append(txt)
        # ---------------------------------------------------------------------------

        bonus_plate_pm = self._bonus_plate_pixmap()

        name_rect = self._layout.tile_name_rect_trophy if gid == 4 else self._layout.tile_name_rect
        bonus_rect_cfg = QRect(self._layout.tile_bonus_rect)
        toggle_src = self._layout.tile_toggle_rect_trophy if gid == 4 else self._layout.tile_toggle_rect

        # toggle clamp оставляю (если хочешь полностью ручной — скажи, уберём)
        base_w0, base_h0 = int(base_plate.width()), int(base_plate.height())
        tr = QRect(toggle_src)
        if tr.right() >= base_w0:
            tr.moveLeft(max(0, base_w0 - tr.width()))
        if tr.bottom() >= base_h0:
            tr.moveTop(max(0, base_h0 - tr.height()))
        if tr.left() < 0:
            tr.moveLeft(0)
        if tr.top() < 0:
            tr.moveTop(0)

        # имя
        line_spacing_px = 0
        # бонусы
        bonus_line_spacing_px = 0

        for it in items:
            cid = int(it.get("CollectedId", 0))
            kind = str(it.get("Kind", ""))
            name = str(it.get("Name", ""))
            image_id = int(it.get("ImageId", 0))
            costume_image_id = int(it.get("CostumeImageId", 0))

            bonus_texts = bonus_lines_by_cid.get(cid) or []
            has_bonus_plate = bool(bonus_texts) and (not bonus_plate_pm.isNull())

            base_w, base_h = int(base_plate.width()), int(base_plate.height())
            bonus_w, bonus_h = (int(bonus_plate_pm.width()), int(bonus_plate_pm.height())) if has_bonus_plate else (
            0, 0)

            # ✅ бонус-плитка теперь СНИЗУ
            tile_w = max(base_w, bonus_w)
            tile_h = base_h + (bonus_h if has_bonus_plate else 0)

            tile = QFrame(cont)
            tile.setObjectName(f"collected_tile_{gid}_{cid}")
            tile.setStyleSheet("background: transparent; border: none;")
            tile.setFixedSize(tile_w, tile_h)
            tile.setCursor(Qt.PointingHandCursor)

            tile.setProperty("tile_kind", "plate")
            tile.setProperty("group_id", gid)
            tile.setProperty("collected_id", cid)
            tile.setProperty("costume_image_id", costume_image_id if (gid == 1 and kind == "equipment") else 0)
            tile.installEventFilter(self)

            # base plate bg (сверху)
            bg = QLabel(tile)
            bg.setObjectName(f"tile_bg_{gid}_{cid}")
            bg.setStyleSheet("background: transparent; border: none;")
            bg.setScaledContents(False)
            bg.setGeometry(0, 0, base_w, base_h)
            bg.setPixmap(base_plate)
            bg.setAttribute(Qt.WA_TransparentForMouseEvents, True)

            # bonus plate bg (впритык снизу)
            bonus_bg = None
            if has_bonus_plate:
                bonus_bg = QLabel(tile)
                bonus_bg.setObjectName(f"tile_bonus_plate_{gid}_{cid}")
                bonus_bg.setStyleSheet("background: transparent; border: none;")
                bonus_bg.setScaledContents(False)
                overlap_px = 2  # 1..3 обычно достаточно
                tile_h = base_h + (bonus_h if has_bonus_plate else 0) - (overlap_px if has_bonus_plate else 0)
                # bonus-плитка чуть заходит на base
                bonus_bg.setGeometry(0, base_h - overlap_px, bonus_w, bonus_h)
                bonus_bg.setPixmap(bonus_plate_pm)
                bonus_bg.setAttribute(Qt.WA_TransparentForMouseEvents, True)

            # ИКОНКА: НЕ создаём её для трофеев (gid==4)
            if gid != 4:
                icon = QLabel(tile)
                icon.setObjectName(f"tile_icon_{gid}_{cid}")
                icon.setStyleSheet("background: transparent; border: none;")
                icon.setScaledContents(False)
                icon.setGeometry(self._layout.tile_icon_rect)
                icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

                pm = self._pixmap_from_db_image_id(image_id)
                if not pm.isNull():
                    icon.setPixmap(
                        pm.scaled(self._layout.tile_icon_rect.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

            # ---------- ИМЯ: ручной перенос (как у тебя) ----------
            base_name_lbl = QLabel(tile)
            base_name_lbl.setObjectName(f"tile_name_{gid}_{cid}_l0")
            base_name_lbl.setStyleSheet(
                "background: transparent; border: none;"
                "color: rgb(0, 0, 0);"
                "font-size: 14px;"
            )
            base_name_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            base_name_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            base_name_lbl.ensurePolished()

            fm = QFontMetrics(base_name_lbl.font())
            line_h = int(fm.height())
            w = int(name_rect.width())
            h = int(name_rect.height())

            denom = max(1, line_h + int(line_spacing_px))
            max_lines = max(1, (h + int(line_spacing_px)) // denom)

            text = " ".join((name or "").split())
            words = text.split(" ") if text else []
            lines: List[str] = []
            cur = ""

            def _fits(s: str) -> bool:
                try:
                    return fm.horizontalAdvance(s) <= w
                except Exception:
                    return True

            for word in words:
                test = word if not cur else (cur + " " + word)
                if _fits(test):
                    cur = test
                    continue

                if cur:
                    lines.append(cur)
                    cur = word
                else:
                    chunk = ""
                    for ch in word:
                        t2 = chunk + ch
                        if _fits(t2):
                            chunk = t2
                        else:
                            if chunk:
                                lines.append(chunk)
                            chunk = ch
                            if len(lines) >= max_lines:
                                break
                    cur = chunk
                if len(lines) >= max_lines:
                    break

            if cur and len(lines) < max_lines:
                lines.append(cur)

            if lines:
                if len(lines) > max_lines:
                    lines = lines[:max_lines]
                if len(lines) == max_lines and words:
                    lines[-1] = fm.elidedText(lines[-1], Qt.ElideRight, w)

            for i in range(max_lines):
                if i == 0:
                    lbl = base_name_lbl
                else:
                    lbl = QLabel(tile)
                    lbl.setObjectName(f"tile_name_{gid}_{cid}_l{i}")
                    lbl.setStyleSheet(base_name_lbl.styleSheet())
                    lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                    lbl.ensurePolished()

                y = int(name_rect.y()) + i * (line_h + int(line_spacing_px))
                lbl.setGeometry(int(name_rect.x()), y, w, line_h)
                lbl.setText(lines[i] if i < len(lines) else "")
            # ------------------------------------------------------

            # -------------------------- БОНУСЫ (в нижней bonus plate) --------------------------
            if has_bonus_plate and bonus_bg is not None:
                br = QRect(bonus_rect_cfg)

                base_bonus_lbl = QLabel(bonus_bg)
                base_bonus_lbl.setObjectName(f"tile_bonus_{gid}_{cid}_l0")
                base_bonus_lbl.setStyleSheet(
                    "background: transparent; border: none;"
                    "color: rgb(0, 0, 0);"
                    "font-size: 14px;"
                )
                base_bonus_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                base_bonus_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                base_bonus_lbl.ensurePolished()

                bfm = QFontMetrics(base_bonus_lbl.font())
                b_line_h = int(bfm.height())
                bw = int(br.width())
                bh = int(br.height())

                denom_b = max(1, b_line_h + int(bonus_line_spacing_px))
                max_b_lines = max(1, (bh + int(bonus_line_spacing_px)) // denom_b)

                rendered: List[str] = []

                def _wrap_one(s: str) -> List[str]:
                    s = " ".join((s or "").split())
                    if not s:
                        return [""]
                    wds = s.split(" ")
                    outl: List[str] = []
                    cur2 = ""
                    for wd in wds:
                        test2 = wd if not cur2 else (cur2 + " " + wd)
                        if bfm.horizontalAdvance(test2) <= bw:
                            cur2 = test2
                            continue
                        if cur2:
                            outl.append(cur2)
                            cur2 = wd
                        else:
                            chunk2 = ""
                            for ch in wd:
                                t3 = chunk2 + ch
                                if bfm.horizontalAdvance(t3) <= bw:
                                    chunk2 = t3
                                else:
                                    if chunk2:
                                        outl.append(chunk2)
                                    chunk2 = ch
                            cur2 = chunk2
                    if cur2:
                        outl.append(cur2)
                    return outl

                for bt in bonus_texts:
                    for ln in _wrap_one(bt):
                        rendered.append(ln)
                        if len(rendered) >= max_b_lines:
                            break
                    if len(rendered) >= max_b_lines:
                        break

                if rendered and len(rendered) >= max_b_lines:
                    rendered[-1] = bfm.elidedText(rendered[-1], Qt.ElideRight, bw)

                for i in range(max_b_lines):
                    if i == 0:
                        bl = base_bonus_lbl
                    else:
                        bl = QLabel(bonus_bg)
                        bl.setObjectName(f"tile_bonus_{gid}_{cid}_l{i}")
                        bl.setStyleSheet(base_bonus_lbl.styleSheet())
                        bl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                        bl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                        bl.ensurePolished()

                    yb = int(br.y()) + i * (b_line_h + int(bonus_line_spacing_px))
                    bl.setGeometry(int(br.x()), yb, bw, b_line_h)
                    bl.setText(rendered[i] if i < len(rendered) else "")
            # ---------------------------------------------------------------------------------

            # toggle (в пределах основной плитки)
            toggle = QLabel(tile)
            toggle.setObjectName(f"tile_toggle_{gid}_{cid}")
            toggle.setScaledContents(False)
            toggle.setGeometry(tr)
            toggle.setCursor(Qt.PointingHandCursor)

            toggle.setProperty("tile_kind", "toggle")
            toggle.setProperty("group_id", gid)
            toggle.setProperty("collected_id", cid)
            toggle.installEventFilter(self)
            toggle.raise_()

            self._tile_bg_by_group[gid][cid] = bg
            self._tile_toggle_by_id[cid] = toggle
            if gid == 1 and kind == "equipment":
                self._costume_img_by_id[cid] = costume_image_id

            self._apply_toggle_icon(cid)
            self._apply_tile_bg(gid, cid)

            lay.addWidget(tile, alignment=Qt.AlignTop | Qt.AlignLeft)

        lay.addStretch(1)

    # ------------------------- events -------------------------

    def eventFilter(self, watched, event) -> bool:
        et = event.type()

        try:
            kind = watched.property("tile_kind") if hasattr(watched, "property") else None
        except Exception:
            kind = None

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

        if kind == "toggle":
            if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                watched.setProperty("_pressed_down", True)
                return True

            if et == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                was_down = bool(watched.property("_pressed_down"))
                watched.setProperty("_pressed_down", False)

                if not (was_down and _is_over_widget(watched)):
                    return True

                try:
                    gid = int(watched.property("group_id") or 0)
                    cid = int(watched.property("collected_id") or 0)
                except Exception:
                    gid, cid = 0, 0

                if gid > 0 and cid > 0:
                    if cid in self._in_col_set:
                        self._in_col_set.remove(cid)
                        try:
                            app = QApplication.instance()
                            if app is not None:
                                app.setProperty(
                                    "collection_in_col_ids",
                                    sorted({int(x) for x in (self._in_col_set or set()) if int(x) > 0}),
                                )
                        except Exception:
                            pass
                        try:
                            mw = self.window().parent() if self.window() is not None else None
                            if mw is not None and hasattr(mw, "refresh_stats_panel"):
                                mw.refresh_stats_panel()
                        except Exception:
                            pass
                    else:
                        self._in_col_set.add(cid)
                        try:
                            app = QApplication.instance()
                            if app is not None:
                                app.setProperty(
                                    "collection_in_col_ids",
                                    sorted({int(x) for x in (self._in_col_set or set()) if int(x) > 0}),
                                )
                        except Exception:
                            pass
                        try:
                            mw = self.window().parent() if self.window() is not None else None
                            if mw is not None and hasattr(mw, "refresh_stats_panel"):
                                mw.refresh_stats_panel()
                        except Exception:
                            pass

                    self._apply_toggle_icon(cid)
                    self._apply_tile_bg(gid, cid)
                return True

            return False

        if kind == "plate":
            if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                watched.setProperty("_pressed_down", True)
                return True

            if et == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                was_down = bool(watched.property("_pressed_down"))
                watched.setProperty("_pressed_down", False)

                if not (was_down and _is_over_widget(watched)):
                    return True

                try:
                    gid = int(watched.property("group_id") or 0)
                    cid = int(watched.property("collected_id") or 0)
                    costume_image_id = int(watched.property("costume_image_id") or 0)
                except Exception:
                    gid, cid, costume_image_id = 0, 0, 0

                if gid > 0 and cid > 0:
                    self._selected_by_group[gid] = cid
                    self._refresh_group_bgs(gid)

                    if gid == 1:
                        self._costume_preview_image_id = int(costume_image_id or 0)
                        if self._active_group_id == 1:
                            if self._costume_preview_image_id > 0:
                                self._apply_costume_preview(self._costume_preview_image_id)
                            else:
                                self._costume_preview.clear()

                return True

            return False

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

            return False

        if watched is self._add_all:
            if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._add_all_down = True
                return True

            if et == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                was_down = self._add_all_down
                self._add_all_down = False
                over = _is_over_widget(watched)

                if not (was_down and over):
                    return True

                conn = self._get_db_conn()

                if not self._add_all_active:
                    self._add_all_active = True

                    all_ids: List[int] = []
                    if conn is not None:
                        try:
                            rows = conn.execute("SELECT Id FROM CollectedItem").fetchall()
                        except Exception:
                            rows = []

                        for r in rows or []:
                            try:
                                cid = int(r[0]) if not hasattr(r, "keys") else int(r["Id"])
                            except Exception:
                                continue
                            if cid > 0:
                                all_ids.append(cid)

                    before = set(self._in_col_set)
                    self._add_all_added_ids = set(all_ids) - before

                    self._in_col_set.update(all_ids)
                    try:
                        app = QApplication.instance()
                        if app is not None:
                            app.setProperty(
                                "collection_in_col_ids",
                                sorted({int(x) for x in (self._in_col_set or set()) if int(x) > 0}),
                            )
                    except Exception:
                        pass

                    try:
                        mw = self.window().parent() if self.window() is not None else None
                        if mw is not None and hasattr(mw, "refresh_stats_panel"):
                            mw.refresh_stats_panel()
                    except Exception:
                        pass

                    pm = self._all_in_col_active_pixmap()
                    if not pm.isNull():
                        self._add_all.setPixmap(
                            pm.scaled(self._add_all.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                        )
                    else:
                        self._add_all.clear()

                else:
                    self._add_all_active = False

                    for cid in list(self._add_all_added_ids):
                        self._in_col_set.discard(int(cid))
                    try:
                        app = QApplication.instance()
                        if app is not None:
                            app.setProperty(
                                "collection_in_col_ids",
                                sorted({int(x) for x in (self._in_col_set or set()) if int(x) > 0}),
                            )
                    except Exception:
                        pass
                    try:
                        mw = self.window().parent() if self.window() is not None else None
                        if mw is not None and hasattr(mw, "refresh_stats_panel"):
                            mw.refresh_stats_panel()
                    except Exception:
                        pass
                    self._add_all_added_ids.clear()
                    self._add_all.clear()

                for gg, cmap in (self._tile_bg_by_group or {}).items():
                    ggid = int(gg or 0)
                    for cc in (cmap or {}).keys():
                        cid2 = int(cc or 0)
                        if cid2 <= 0:
                            continue
                        self._apply_toggle_icon(cid2)
                        self._apply_tile_bg(ggid, cid2)

                return True

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
                    self.closed.emit()
                return True

            return False

        return super().eventFilter(watched, event)

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


class CollectionWindow(QFrame):
    """
    Обёртка-окно для CollectionMenu.
    """
    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None, *, layout: Optional["CollectionMenu.LayoutConfig"] = None):
        super().__init__(parent)
        self.setObjectName("CollectionWindow")

        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")

        self._drag_pos: Optional[QPoint] = None
        self._last_pos: Optional[QPoint] = None

        self._conn = getattr(getattr(parent, "data", None), "conn", None)

        self.menu = CollectionMenu(self, layout=layout, conn=self._conn)
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
        try:
            if hasattr(self, "menu") and self.menu is not None:
                self.menu._reset_close_visuals()
        except Exception:
            pass

        if isinstance(self._last_pos, QPoint):
            try:
                self.move(self._last_pos)
            except Exception:
                pass
        else:
            host = parent if isinstance(parent, QWidget) else self.parentWidget()
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
                y_limit = int(lay.scroll_rect.y())
            except Exception:
                y_limit = 0

            if p.y() >= y_limit:
                return False

            try:
                if lay.close1_rect.contains(p) or lay.close2_rect.contains(p):
                    return False
            except Exception:
                pass

            try:
                for r in (lay.tab_rects or {}).values():
                    if r.contains(p):
                        return False
            except Exception:
                pass

            return True

        if et == QEvent.MouseButtonPress:
            try:
                if event.button() == Qt.LeftButton:
                    p = _pos_in_menu()
                    if p is not None and _can_start_drag(p):
                        try:
                            gp = event.globalPosition().toPoint()
                        except Exception:
                            gp = event.globalPos()
                        self._drag_pos = gp - self.frameGeometry().topLeft()
                        event.accept()
                        return True
            except Exception:
                pass

        if et == QEvent.MouseMove:
            try:
                if self._drag_pos is not None and (event.buttons() & Qt.LeftButton):
                    try:
                        gp = event.globalPosition().toPoint()
                    except Exception:
                        gp = event.globalPos()
                    self.move(gp - self._drag_pos)
                    event.accept()
                    return True
            except Exception:
                pass

        if et == QEvent.MouseButtonRelease:
            try:
                if event.button() == Qt.LeftButton:
                    self._drag_pos = None
            except Exception:
                self._drag_pos = None

        return super().eventFilter(watched, event)

    def closeEvent(self, ev) -> None:  # noqa: N802
        try:
            self._last_pos = QPoint(self.pos())
        except Exception:
            self._last_pos = None

        try:
            self.closed.emit()
        except Exception:
            pass
        super().closeEvent(ev)