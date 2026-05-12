from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any

from PySide6.QtCore import Qt, QRect, QSize, QEvent, Signal, QPoint
from PySide6.QtGui import QPixmap, QPainter, QColor, QBitmap, QFontMetrics, QImage, QFont, QPen, QPainterPath, QGuiApplication
from PySide6.QtWidgets import QWidget, QApplication, QLabel, QFrame


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


class _TalentTooltip(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)

        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setObjectName("talentTooltip")
        self.setStyleSheet("background: transparent; border: none;")

        self._lab = QLabel(self)
        self._lab.setWordWrap(True)
        self._lab.setTextFormat(Qt.RichText)
        self._lab.setStyleSheet(
            "background: transparent;"
            "color: #f2f2f2;"
            "border: none;"
        )

        self.hide()

    def set_html(self, html_text: str, max_w: int = 340) -> None:
        self._lab.setText(html_text or "")
        self._lab.setFixedWidth(int(max_w))
        self._lab.adjustSize()

        pad_x = 10
        pad_y = 8

        self._lab.move(pad_x, pad_y)
        self.resize(
            self._lab.width() + pad_x * 2,
            self._lab.height() + pad_y * 2,
        )

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect().adjusted(1, 1, -2, -2)

        # Чёрный фон с прозрачностью около 90%.
        p.setBrush(QColor(0, 0, 0, 230))

        # Металлическая обводка 2 px.
        p.setPen(QPen(QColor(145, 140, 128, 235), 2))

        p.drawRoundedRect(r, 6, 6)

        p.end()
        super().paintEvent(ev)

class TalentsMenu(QWidget):
    closed = Signal()
    selectionChanged = Signal()

    BG_PATH = "resources/talents/talent_menu.png"
    CLOSE_ACTIVE_PATH = "resources/helper_buttons/close_button_active.png"
    BIG_CLOSE_PATH = "resources/talents/close.png"
    SLOT_BG_PATH = "resources/talents/talent_slot.png"
    COVER_BG_PATH = "resources/talents/talent_cover.png"
    FRAME_OVER_PATH = "resources/talents/frame_over.png"
    FRAME_OVER_RECT = QRect(628, 29, 85, 85)

    RESET_PATH = "resources/talents/reset.png"
    RESET_RECT = QRect(456, 629, 150, 39)

    # Прямоугольник для числа очков талантов.
    # Поставил заглушку — подставь свои координаты/размер по talent_menu.png.
    TALENT_POINTS_RECT = QRect(206, 627, 20, 16)
    TALENT_POINTS_FONT_PX = 16
    TALENT_POINTS_COLOR_OK = QColor("#3fbf59")
    TALENT_POINTS_COLOR_ZERO = QColor("#7a7a7a")

    FIRST_SLOT_RECT = QRect(18, 42, 730, 144)
    COVER_RECT = QRect(18, 187, 730, 436)

    # Область под иконку класса
    CLASS_INFO_ICON_RECT = QRect(49, 213, 230, 356) #232 330 (356 356)

    # Область под весь текстовый блок
    CLASS_INFO_TEXT_RECT = QRect(297, 270, 350, 230)

    # Размеры шрифтов
    CLASS_TITLE_FONT_PX = 19
    CLASS_BODY_FONT_PX = 16

    # Вертикальные отступы между строками
    CLASS_TITLE_BOTTOM_GAP = 4
    CLASS_DESC_BOTTOM_GAP = 5

    # Оформление подписи ветки таланта внутри talent_slot
    BRANCH_NAME_RECT = QRect(16, 29, 158, 87)
    BRANCH_NAME_FONT_PX = 18
    BRANCH_NAME_COLOR = QColor("#f2e4bb")

    CLOSE_RECT = QRect(730, 3, 24, 24)
    BIG_CLOSE_RECT = QRect(608, 633, 140, 32)
    FALLBACK_SIZE = (768, 679)


    TALENT_GRID_X = 195
    TALENT_GRID_Y = 16
    TALENT_ICON_W = 48
    TALENT_ICON_H = 48
    TALENT_COL_GAP = 16
    TALENT_ROW_GAP = 14

    TALENT_COL_GAPS = (16, 16, 37, 33, 16, 44)  # между 0-1,1-2,...,5-6
    BRANCH_COLOR_BASE_FILL_W = 180
    TALENT_RECT_HINDEX = 6

    TALENT_TOOLTIP_MAX_W = 340

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMouseTracking(True)

        self._bg_pm = QPixmap(_resolve_resource(self.BG_PATH))
        if self._bg_pm.isNull():
            w, h = self.FALLBACK_SIZE
            self._bg_pm = QPixmap(w, h)
            self._bg_pm.fill(QColor(20, 20, 20, 240))

        self._close_active_pm = QPixmap(_resolve_resource(self.CLOSE_ACTIVE_PATH))
        self._big_close_pm = QPixmap(_resolve_resource(self.BIG_CLOSE_PATH))
        self._reset_pm = QPixmap(_resolve_resource(self.RESET_PATH))
        self._slot_bg_pm = QPixmap(_resolve_resource(self.SLOT_BG_PATH))
        self._cover_bg_pm = QPixmap(_resolve_resource(self.COVER_BG_PATH))
        self._frame_over_pm = QPixmap(_resolve_resource(self.FRAME_OVER_PATH))

        self.setFixedSize(self._bg_pm.size())
        self._apply_window_mask_from_bg()

        self._drag_active = False
        self._drag_offset = QPoint()
        self._last_global_pos: Optional[QPoint] = None

        self._hover_part: str = ""
        self._pressed_part: str = ""

        # pending talent action on release
        self._pending_talent_action: str = ""
        self._pending_talent_branch_id: int = 0
        self._pending_talent_id: int = 0

        self._current_class_id: int = 0
        self._current_class_row: Optional[dict] = None

        self._db_image_cache: dict[int, QPixmap] = {}
        self._slot_transparent_mask_cache: dict[tuple[int, int, int], QPixmap] = {}
        self._setting_cache: dict[str, str] = {}

        # TalentBranch
        self._talent_branch_slots: list[Optional[dict]] = [None, None, None, None]
        self._talent_branch_visible_count: int = 1

        # Talent
        self._talents_by_branch: Dict[int, List[dict]] = {}
        self._selected_talents_by_branch: Dict[int, Dict[int, int]] = {}

        self._hover_branch_id: int = 0
        self._hover_talent_id: int = 0
        self._hover_talent_rect: Optional[QRect] = None

        self._tooltip = _TalentTooltip(self)

        self._host_runtime_signals_connected = False
        self._connect_host_runtime_signals()

        self._stats_bus_connected = False
        self._connect_global_stats_bus()

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

    def _screen_rect(self, global_hint: Optional[QPoint] = None) -> QRect:
        try:
            if isinstance(global_hint, QPoint):
                scr = QGuiApplication.screenAt(global_hint)
                if scr is not None:
                    return scr.availableGeometry()
        except Exception:
            pass

        try:
            center_hint = QPoint(
                int(self.x() + self.width() / 2),
                int(self.y() + self.height() / 2),
            )
            scr = QGuiApplication.screenAt(center_hint)
            if scr is not None:
                return scr.availableGeometry()
        except Exception:
            pass

        try:
            if self.window() and self.window().screen():
                return self.window().screen().availableGeometry()
        except Exception:
            pass

        try:
            app = QApplication.instance()
            if app is not None and app.primaryScreen() is not None:
                return app.primaryScreen().availableGeometry()
        except Exception:
            pass

        return QRect(0, 0, 1920, 1080)

    def _clamp_global_pos(self, pos: QPoint, global_hint: Optional[QPoint] = None) -> QPoint:
        hint = global_hint
        if hint is None:
            try:
                hint = QPoint(
                    int(pos.x() + self.width() / 2),
                    int(pos.y() + self.height() / 2),
                )
            except Exception:
                hint = pos

        sr = self._screen_rect(hint)

        x = int(pos.x())
        y = int(pos.y())

        if x + self.width() > sr.right():
            x = sr.right() - self.width()
        if y + self.height() > sr.bottom():
            y = sr.bottom() - self.height()

        x = max(sr.left(), x)
        y = max(sr.top(), y)
        return QPoint(x, y)

    def _conn(self):
        p = self.parentWidget()
        seen = set()
        while p is not None and id(p) not in seen:
            seen.add(id(p))
            try:
                data = getattr(p, "data", None)
                conn = getattr(data, "conn", None)
                if conn is not None:
                    return conn
            except Exception:
                pass
            p = p.parentWidget()
        return None

    def _read_setting_value(self, key: str) -> Optional[str]:
        if not key:
            return None

        cache = getattr(self, "_setting_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._setting_cache = cache

        if key in cache:
            raw = cache.get(key)
            return None if raw in (None, "") else str(raw)

        conn = self._conn()
        if conn is None:
            cache[key] = ""
            return None

        key_cols = ["Key", "`Key`", "\"Key\"", "[Key]", "key", "`key`", "\"key\"", "[key]", "Name", "Code"]
        sql_tpl = "SELECT Value FROM Setting WHERE {col} = ? LIMIT 1"

        for col in key_cols:
            try:
                row = conn.execute(sql_tpl.format(col=col), (str(key),)).fetchone()
                if not row:
                    continue
                raw = row[0] if not hasattr(row, "keys") else row["Value"]
                cache[key] = "" if raw in (None, "") else str(raw)
                return None if raw in (None, "") else str(raw)
            except Exception:
                continue

        cache[key] = ""
        return None

    def _setting_int(self, key: str, default: int = 0) -> int:
        raw = self._read_setting_value(key)
        if raw is None:
            return int(default)
        try:
            return int(float(str(raw).strip()))
        except Exception:
            return int(default)

    def _current_level(self) -> int:
        host = self.parentWidget()
        try:
            if host is not None and hasattr(host, "level_spin") and host.level_spin is not None:
                return max(1, _safe_int(host.level_spin.value(), 1))
        except Exception:
            pass
        return 1

    def _connect_host_runtime_signals(self) -> None:
        if getattr(self, "_host_runtime_signals_connected", False):
            return

        host = self.parentWidget()
        if host is None:
            return

        try:
            if hasattr(host, "level_spin") and host.level_spin is not None:
                try:
                    host.level_spin.valueChanged.connect(self._on_host_level_changed,
                                                         Qt.ConnectionType.UniqueConnection)
                except Exception:
                    try:
                        host.level_spin.valueChanged.connect(self._on_host_level_changed)
                    except Exception:
                        pass
        except Exception:
            pass

        self._host_runtime_signals_connected = True

    def _connect_global_stats_bus(self) -> None:
        if getattr(self, "_stats_bus_connected", False):
            return

        bus = None
        try:
            from .characteristics_math import get_current_stats_bus
            bus = get_current_stats_bus()
        except Exception:
            try:
                from characteristics_math import get_current_stats_bus
                bus = get_current_stats_bus()
            except Exception:
                bus = None

        if bus is None:
            return

        try:
            bus.statsChanged.connect(self._on_global_stats_changed, Qt.ConnectionType.UniqueConnection)
        except Exception:
            try:
                bus.statsChanged.connect(self._on_global_stats_changed)
            except Exception:
                return

        self._stats_bus_connected = True

    def _find_hovered_talent(self) -> tuple[Optional[int], Optional[dict], Optional[QRect]]:
        bid = _safe_int(getattr(self, "_hover_branch_id", 0), 0)
        tid = _safe_int(getattr(self, "_hover_talent_id", 0), 0)
        rect = getattr(self, "_hover_talent_rect", None)

        if bid <= 0 or tid <= 0 or not isinstance(rect, QRect):
            return None, None, None

        for talent in self._branch_talents(bid):
            if not isinstance(talent, dict):
                continue
            if _safe_int(talent.get("Id"), 0) == tid:
                return int(bid), talent, QRect(rect)

        return None, None, None

    def _refresh_hovered_talent_tooltip(self) -> None:
        bid, talent, rect = self._find_hovered_talent()
        if bid is None or not isinstance(talent, dict) or rect is None:
            return

        self._show_talent_tooltip(int(bid), talent, rect)

    def _on_global_stats_changed(self, *_args) -> None:
        """
        Когда stats_panel публикует новые глобальные статы,
        заново собираем tooltip таланта, чтобы {0}/{1} обновились.
        """
        try:
            if not self.isVisible():
                return
        except Exception:
            pass

        try:
            self._refresh_hovered_talent_tooltip()
        except Exception:
            pass

        try:
            self.update()
        except Exception:
            pass

    def _on_host_level_changed(self, *_args) -> None:
        changed = False

        try:
            changed = self._enforce_talent_points_limit()
        except Exception:
            changed = False

        try:
            self._refresh_hovered_talent_tooltip()
        except Exception:
            pass

        if changed:
            try:
                self._hover_talent_rect = None if self._hover_talent_id == 0 else self._hover_talent_rect
            except Exception:
                pass

        try:
            self.update()
        except Exception:
            pass

    def _selection_prune_order(self) -> list[tuple[int, int, int]]:
        """
        Порядок снятия талантов при нехватке очков:
        - сначала более поздние ветки (нижние слоты)
        - внутри ветки сначала больший HIndex
        """
        out: list[tuple[int, int, int]] = []

        visible_slots = int(getattr(self, "_talent_branch_visible_count", 1) or 1)
        branch_slots = list(getattr(self, "_talent_branch_slots", [None, None, None, None]) or [None, None, None, None])

        for slot_idx in range(max(1, visible_slots)):
            if slot_idx >= 4:
                break

            row = branch_slots[slot_idx] if slot_idx < len(branch_slots) else None
            if not isinstance(row, dict):
                continue

            bid = _safe_int(row.get("Id"), 0)
            if bid <= 0:
                continue

            cols = self._branch_selected_cols(bid)
            for hidx in sorted(cols.keys(), reverse=True):
                tid = _safe_int(cols.get(hidx), 0)
                if tid > 0:
                    out.append((int(slot_idx), int(bid), int(hidx)))

        out.sort(key=lambda x: (x[0], x[2]), reverse=True)
        return out

    def _enforce_talent_points_limit(self) -> bool:
        """
        Если из-за понижения уровня доступных очков стало меньше,
        постепенно снимаем активные таланты, пока spent <= total.
        """
        total = int(self._talent_points_total())
        spent = int(self._talent_points_spent())

        if spent <= total:
            return False

        changed = False

        while spent > total:
            removed = False

            for _slot_idx, bid, hidx in self._selection_prune_order():
                cur_tid = self._selected_talent_id_for_hindex(int(bid), int(hidx))
                if cur_tid <= 0:
                    continue

                self._set_selected_talent_at_hindex(int(bid), int(hidx), 0, notify=False)
                changed = True
                removed = True
                break

            if not removed:
                break

            spent = int(self._talent_points_spent())

        if changed:
            self._notify_selection_changed()

        return changed

    def _talent_points_total(self) -> int:
        lvl = max(1, self._current_level())

        mult = max(1, self._setting_int("TalentLevelMultiplicity", 1))
        max_lvl = max(0, self._setting_int("QualityMaxLevel", lvl))

        effective_level = min(int(lvl), int(max_lvl)) if max_lvl > 0 else int(lvl)
        by_level = int(effective_level // mult)

        row = getattr(self, "_current_class_row", None)
        base_bonus = 3 if _safe_int((row or {}).get("Base_Id"), 0) > 0 else 0

        return max(0, int(by_level + base_bonus))

    def _talent_points_spent(self) -> int:
        spent = 0
        for cols in (self._selected_talents_by_branch or {}).values():
            if not isinstance(cols, dict):
                continue
            for _hidx, tid in cols.items():
                if _safe_int(tid, 0) > 0:
                    spent += 1
        return int(spent)

    def _talent_points_left(self) -> int:
        return max(0, int(self._talent_points_total() - self._talent_points_spent()))

    def _branch_has_selected_h6(self, branch_id: int) -> bool:
        tid = self._selected_talent_id_for_hindex(branch_id, 6)
        return _safe_int(tid, 0) > 0

    def set_class_id(self, class_id: Optional[int]) -> None:
        cid = _safe_int(class_id, 0)
        class_changed = (cid != int(getattr(self, "_current_class_id", 0) or 0))

        self._current_class_id = int(cid)
        self._current_class_row = self._load_class_row(cid) if cid > 0 else None

        try:
            slots, visible_count = self._load_talent_branch_slots(cid)
        except Exception:
            slots, visible_count = ([None, None, None, None], 1)

        self._talent_branch_slots = list(slots or [None, None, None, None])
        self._talent_branch_visible_count = int(visible_count or 1)

        try:
            self._talents_by_branch = self._load_talents_for_visible_branches()
        except Exception:
            self._talents_by_branch = {}

        self._prune_selected_talents()
        self._enforce_talent_points_limit()
        self._publish_selected_talents()

        if class_changed:
            self._hover_branch_id = 0
            self._hover_talent_id = 0
            self._hover_talent_rect = None
            self._tooltip.hide()

        self.update()

    def _load_class_row(self, class_id: int) -> Optional[dict]:
        cid = _safe_int(class_id, 0)
        if cid <= 0:
            return None

        conn = self._conn()
        if conn is None:
            return None

        try:
            row = conn.execute(
                """
                SELECT Id, Name, Base_Id, Talent_Description, Class_Variable, Class_Image_Id
                FROM "Class"
                WHERE Id=?
                LIMIT 1
                """,
                (int(cid),),
            ).fetchone()
        except Exception:
            row = None

        if not row:
            return None

        try:
            if hasattr(row, "keys"):
                return {
                    "Id": _safe_int(row["Id"], 0),
                    "Name": _to_str(row["Name"]),
                    "Base_Id": _safe_int(row["Base_Id"], 0),
                    "Talent_Description": _to_str(row["Talent_Description"]),
                    "Class_Variable": _to_str(row["Class_Variable"]),
                    "Class_Image_Id": _safe_int(row["Class_Image_Id"], 0),
                }
            return {
                "Id": _safe_int(row[0], 0),
                "Name": _to_str(row[1]),
                "Base_Id": _safe_int(row[2], 0),
                "Talent_Description": _to_str(row[3]),
                "Class_Variable": _to_str(row[4]),
                "Class_Image_Id": _safe_int(row[5], 0),
            }
        except Exception:
            return None

    def _class_lineage_ids(self, class_id: int) -> list[int]:
        """
        Возвращает цепочку классов:
        [current_class_id, base_id, base_base_id, ...]
        """
        conn = self._conn()
        cid = _safe_int(class_id, 0)
        if conn is None or cid <= 0:
            return []

        out: list[int] = []
        seen: set[int] = set()

        cur = int(cid)
        while cur > 0 and cur not in seen:
            seen.add(cur)
            out.append(int(cur))

            try:
                row = conn.execute(
                    'SELECT Base_Id FROM "Class" WHERE Id=? LIMIT 1',
                    (int(cur),),
                ).fetchone()
            except Exception:
                row = None

            if not row:
                break

            try:
                raw_base = row["Base_Id"] if hasattr(row, "keys") else row[0]
                base_id = _safe_int(raw_base, 0)
            except Exception:
                base_id = 0

            if base_id <= 0:
                break

            cur = int(base_id)

        return out

    def _parse_branch_color(self, raw_color) -> QColor:
        s = _to_str(raw_color).strip()
        if not s:
            return QColor(70, 70, 70, 255)

        # 1) обычный QColor-парсинг (#RRGGBB, названия и т.п.)
        qc = QColor(s)
        if qc.isValid():
            if qc.alpha() <= 0:
                qc.setAlpha(255)
            return qc

        # 2) форматы вида "255;128;0" / "255,128,0" / "255 128 0"
        buf = s.replace(";", " ").replace(",", " ")
        parts = [x for x in buf.split() if x.strip()]
        nums: list[int] = []
        for x in parts:
            try:
                nums.append(int(float(x)))
            except Exception:
                pass

        if len(nums) >= 3:
            r = max(0, min(255, nums[0]))
            g = max(0, min(255, nums[1]))
            b = max(0, min(255, nums[2]))
            a = max(0, min(255, nums[3])) if len(nums) >= 4 else 255
            return QColor(r, g, b, a)

        return QColor(70, 70, 70, 255)

    def _load_talent_branch_slots(self, class_id: int) -> tuple[list[Optional[dict]], int]:
        """
        Собирает TalentBranch для текущего класса с учётом Base_Id.
        Если у класса нет Base_Id -> показываем только 1 slot.
        Если Base_Id есть -> показываем 4 slot.
        """
        row = getattr(self, "_current_class_row", None)
        base_id = _safe_int((row or {}).get("Base_Id"), 0)
        visible_count = 4 if base_id > 0 else 1

        conn = self._conn()
        cid = _safe_int(class_id, 0)
        if conn is None or cid <= 0:
            return [None, None, None, None], visible_count

        lineage = self._class_lineage_ids(cid)
        if not lineage:
            return [None, None, None, None], visible_count

        priority_by_class = {int(cls_id): idx for idx, cls_id in enumerate(lineage)}

        ph = ",".join(["?"] * len(lineage))
        try:
            rows = conn.execute(
                f"""
                SELECT Id, Name, Class_Id, Color, OrderIndex
                FROM TalentBranch
                WHERE Class_Id IN ({ph})
                ORDER BY OrderIndex, Id
                """,
                tuple(int(x) for x in lineage),
            ).fetchall()
        except Exception:
            rows = []

        slots: list[Optional[dict]] = [None, None, None, None]

        # если у разных классов в lineage вдруг один и тот же OrderIndex,
        # приоритет у более "близкого" класса: current -> parent -> parent parent
        candidates: list[dict] = []
        for r in rows or []:
            try:
                if hasattr(r, "keys"):
                    bid = _safe_int(r["Id"], 0)
                    name = _to_str(r["Name"])
                    cls_id = _safe_int(r["Class_Id"], 0)
                    color = _to_str(r["Color"])
                    order_idx = _safe_int(r["OrderIndex"], 0)
                else:
                    bid = _safe_int(r[0], 0)
                    name = _to_str(r[1])
                    cls_id = _safe_int(r[2], 0)
                    color = _to_str(r[3])
                    order_idx = _safe_int(r[4], 0)
            except Exception:
                continue

            if bid <= 0 or cls_id <= 0:
                continue
            if order_idx < 0 or order_idx >= 4:
                continue
            if cls_id not in priority_by_class:
                continue

            candidates.append(
                {
                    "Id": int(bid),
                    "Name": str(name),
                    "Class_Id": int(cls_id),
                    "Color": str(color),
                    "OrderIndex": int(order_idx),
                    "_priority": int(priority_by_class[cls_id]),
                }
            )

        candidates.sort(key=lambda x: (int(x["OrderIndex"]), int(x["_priority"]), int(x["Id"])))

        for item in candidates:
            oi = int(item["OrderIndex"])
            if slots[oi] is None:
                slots[oi] = dict(item)

        return slots, int(visible_count)

    def _image_pm(self, image_id: int) -> QPixmap:
        iid = _safe_int(image_id, 0)
        if iid <= 0:
            return QPixmap()

        cache = getattr(self, "_db_image_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._db_image_cache = cache

        if iid in cache:
            return cache[iid]

        pm = _load_db_image_pixmap(self._conn(), iid)
        cache[iid] = pm
        return pm

    def _load_talents_for_visible_branches(self) -> Dict[int, List[dict]]:
        conn = self._conn()
        if conn is None:
            return {}

        branch_ids: List[int] = []
        for row in (self._talent_branch_slots or []):
            if isinstance(row, dict):
                bid = _safe_int(row.get("Id"), 0)
                if bid > 0:
                    branch_ids.append(int(bid))

        branch_ids = sorted(set(branch_ids))
        if not branch_ids:
            return {}

        ph = ",".join(["?"] * len(branch_ids))

        try:
            rows = conn.execute(
                f"""
                SELECT Id, Branch_Id, Name, Description, HIndex, VIndex, Active,
                       PassiveDescription, EquipmentCondition, Image_Id, GrayImage_Id
                FROM Talent
                WHERE Branch_Id IN ({ph})
                ORDER BY Branch_Id, HIndex, VIndex, Id
                """,
                tuple(int(x) for x in branch_ids),
            ).fetchall()
        except Exception:
            rows = []

        out: Dict[int, List[dict]] = {}
        by_talent_id: Dict[int, dict] = {}

        for r in rows or []:
            try:
                if hasattr(r, "keys"):
                    tid = _safe_int(r["Id"], 0)
                    bid = _safe_int(r["Branch_Id"], 0)
                    name = _to_str(r["Name"])
                    desc = _to_str(r["Description"])
                    hidx = _safe_int(r["HIndex"], 0)
                    vidx = _safe_int(r["VIndex"], 0)
                    active = _safe_int(r["Active"], 0)
                    passive_desc = _to_str(r["PassiveDescription"])
                    equip_cond = _to_str(r["EquipmentCondition"])
                    image_id = _safe_int(r["Image_Id"], 0)
                    gray_id = _safe_int(r["GrayImage_Id"], 0)
                else:
                    tid = _safe_int(r[0], 0)
                    bid = _safe_int(r[1], 0)
                    name = _to_str(r[2])
                    desc = _to_str(r[3])
                    hidx = _safe_int(r[4], 0)
                    vidx = _safe_int(r[5], 0)
                    active = _safe_int(r[6], 0)
                    passive_desc = _to_str(r[7])
                    equip_cond = _to_str(r[8])
                    image_id = _safe_int(r[9], 0)
                    gray_id = _safe_int(r[10], 0)
            except Exception:
                continue

            if tid <= 0 or bid <= 0:
                continue

            talent = {
                "Id": int(tid),
                "Branch_Id": int(bid),
                "Name": str(name),
                "Description": str(desc),
                "HIndex": int(hidx),
                "VIndex": int(vidx),
                "Active": int(active),
                "PassiveDescription": str(passive_desc),
                "EquipmentCondition": str(equip_cond),
                "Image_Id": int(image_id),
                "GrayImage_Id": int(gray_id),
                "TalentVariables": {},
                "ActiveBuffLines": [],
                "PassiveBuffLines": [],
            }

            out.setdefault(int(bid), []).append(talent)
            by_talent_id[int(tid)] = talent

        talent_ids = sorted(by_talent_id.keys())

        # ----------------------------------------------------------
        # TalentVariable -> для подстановки в Talent.Description
        #
        # ЭТОТ БЛОК НЕ СВЯЗАН С BuffDescription.
        # Его не трогаем по смыслу:
        #   TalentVariable.Index = 0 -> Talent.Description {0}
        #   TalentVariable.Index = 1 -> Talent.Description {1}
        #
        # Type=1 -> текущая Атака * Value
        # Type=0 -> просто Value
        # ----------------------------------------------------------
        if talent_ids:
            ph_tv = ",".join(["?"] * len(talent_ids))
            try:
                tv_rows = conn.execute(
                    f"""
                    SELECT Talent_Id, "Index", Value, Type
                    FROM TalentVariable
                    WHERE Talent_Id IN ({ph_tv})
                    ORDER BY Talent_Id, "Index", Id
                    """,
                    tuple(int(x) for x in talent_ids),
                ).fetchall()
            except Exception:
                tv_rows = []

            for r in tv_rows or []:
                try:
                    if hasattr(r, "keys"):
                        tid = _safe_int(r["Talent_Id"], 0)
                        idx = _safe_int(r["Index"], 0)
                        val = r["Value"]
                        typ = _safe_int(r["Type"], 0)
                    else:
                        tid = _safe_int(r[0], 0)
                        idx = _safe_int(r[1], 0)
                        val = r[2]
                        typ = _safe_int(r[3], 0)
                except Exception:
                    continue

                talent = by_talent_id.get(int(tid))
                if not talent:
                    continue

                try:
                    val_f = float(val)
                except Exception:
                    val_f = 0.0

                talent.setdefault("TalentVariables", {})[int(idx)] = {
                    "Value": float(val_f),
                    "Type": int(typ),
                }

        # ----------------------------------------------------------
        # TalentBuffDescription -> BuffDescription.Template
        #
        # Это отдельная логика от Talent.Description.
        #
        # Правила:
        #   TalentBuffDescription.OrderIndex = 0 -> BuffDescription.Template {0}
        #   TalentBuffDescription.OrderIndex = 1 -> BuffDescription.Template {1}
        #   TalentBuffDescription.OrderIndex = 2 -> BuffDescription.Template {2}
        #
        # Но:
        #   - если в Template только один плейсхолдер, например "{0}",
        #     TalentBuffDescription.Value имеет приоритет;
        #
        #   - если в Template несколько плейсхолдеров, например "{0}-{1}",
        #     сначала берём готовые значения из compute_buff_description_variables(),
        #     потому что там уже может быть корректный диапазон;
        #
        #   - TalentBuffDescription.Value используется как fallback для тех индексов,
        #     которых compute_buff_description_variables не дал.
        # ----------------------------------------------------------
        if talent_ids:
            ph2 = ",".join(["?"] * len(talent_ids))
            try:
                b_rows = conn.execute(
                    f"""
                    SELECT
                        tbd.Talent_Id,
                        tbd.Description_Id,
                        tbd.Value,
                        bd.Name,
                        bd.Template,
                        tbd.OrderIndex,
                        tbd.IsPassive
                    FROM TalentBuffDescription AS tbd
                    JOIN BuffDescription AS bd ON bd.Id = tbd.Description_Id
                    WHERE tbd.Talent_Id IN ({ph2})
                    ORDER BY tbd.Talent_Id, tbd.IsPassive, tbd.OrderIndex, tbd.Description_Id, tbd.Id
                    """,
                    tuple(int(x) for x in talent_ids),
                ).fetchall()
            except Exception:
                b_rows = []

            grouped: Dict[tuple[int, int, int], dict] = {}

            for r in b_rows or []:
                try:
                    if hasattr(r, "keys"):
                        tid = _safe_int(r["Talent_Id"], 0)
                        desc_id = _safe_int(r["Description_Id"], 0)
                        raw_value = r["Value"]
                        bd_name = _to_str(r["Name"])
                        bd_tpl = _to_str(r["Template"])
                        order_idx = _safe_int(r["OrderIndex"], 0)
                        is_passive = _safe_int(r["IsPassive"], 0)
                    else:
                        tid = _safe_int(r[0], 0)
                        desc_id = _safe_int(r[1], 0)
                        raw_value = r[2]
                        bd_name = _to_str(r[3])
                        bd_tpl = _to_str(r[4])
                        order_idx = _safe_int(r[5], 0)
                        is_passive = _safe_int(r[6], 0)
                except Exception:
                    continue

                talent = by_talent_id.get(int(tid))
                if not talent:
                    continue

                key = (int(tid), int(desc_id), int(is_passive))
                item = grouped.get(key)

                if item is None:
                    item = {
                        "Talent_Id": int(tid),
                        "Description_Id": int(desc_id),
                        "Name": str(bd_name),
                        "Template": str(bd_tpl),
                        "IsPassive": int(is_passive),
                        "SortOrder": int(order_idx),
                        "RawValuesByOrder": {},
                    }
                    grouped[key] = item
                else:
                    item["SortOrder"] = min(
                        int(item.get("SortOrder", 0)),
                        int(order_idx),
                    )

                # OrderIndex напрямую соответствует номеру плейсхолдера.
                # Даже Value = 0 сохраняем. Не сохраняем только None.
                if raw_value is not None:
                    try:
                        item.setdefault("RawValuesByOrder", {})[int(order_idx)] = raw_value
                    except Exception:
                        pass

            try:
                from .characteristics_math import compute_buff_description_variables
            except Exception:
                try:
                    from characteristics_math import compute_buff_description_variables
                except Exception:
                    compute_buff_description_variables = None

            grouped_items = list(grouped.values())
            grouped_items.sort(key=lambda x: (
                _safe_int(x.get("Talent_Id"), 0),
                _safe_int(x.get("IsPassive"), 0),
                _safe_int(x.get("SortOrder"), 0),
                _safe_int(x.get("Description_Id"), 0),
            ))

            for item in grouped_items:
                tid = _safe_int(item.get("Talent_Id"), 0)
                is_passive = _safe_int(item.get("IsPassive"), 0)
                desc_id = _safe_int(item.get("Description_Id"), 0)
                bd_name = _to_str(item.get("Name")).strip()
                bd_tpl = _to_str(item.get("Template")).strip()
                sort_order = _safe_int(item.get("SortOrder"), 0)

                talent = by_talent_id.get(int(tid))
                if not talent:
                    continue

                raw_values_by_order = dict(item.get("RawValuesByOrder") or {})

                fallback_values = {}
                if compute_buff_description_variables is not None:
                    try:
                        fb = compute_buff_description_variables(conn, int(desc_id))
                        if isinstance(fb, dict):
                            fallback_values = dict(fb)
                    except Exception:
                        fallback_values = {}

                placeholder_indexes: List[int] = []
                try:
                    for m in re.finditer(r"\{(\d+)\}", bd_tpl):
                        idx = _safe_int(m.group(1), -1)
                        if idx >= 0 and idx not in placeholder_indexes:
                            placeholder_indexes.append(int(idx))
                except Exception:
                    placeholder_indexes = []

                values_by_order: Dict[int, Any] = {}

                # Один плейсхолдер:
                #   Value из TalentBuffDescription должен исправлять случаи,
                #   где fallback даёт дефолтную 1.
                #
                # Несколько плейсхолдеров:
                #   fallback имеет приоритет, потому что для диапазонов {0}-{1}
                #   он уже может давать корректные готовые значения.
                raw_has_priority = len(placeholder_indexes) <= 1

                for idx in placeholder_indexes:
                    has_raw = idx in raw_values_by_order and raw_values_by_order.get(idx) is not None
                    has_fb = idx in fallback_values and fallback_values.get(idx) is not None

                    if raw_has_priority:
                        if has_raw:
                            values_by_order[int(idx)] = raw_values_by_order.get(idx)
                        elif has_fb:
                            values_by_order[int(idx)] = fallback_values.get(idx)
                    else:
                        if has_fb:
                            values_by_order[int(idx)] = fallback_values.get(idx)
                        elif has_raw:
                            values_by_order[int(idx)] = raw_values_by_order.get(idx)

                # Дополнительная страховка:
                # если в шаблоне regex почему-то не нашёл индекс,
                # но данные по нему есть — добавляем, не перетирая уже выбранное.
                for k, v in fallback_values.items():
                    ik = _safe_int(k, -1)
                    if ik >= 0:
                        values_by_order.setdefault(int(ik), v)

                for k, v in raw_values_by_order.items():
                    ik = _safe_int(k, -1)
                    if ik >= 0:
                        values_by_order.setdefault(int(ik), v)

                text = self._format_buff_description_line(bd_tpl, values_by_order)

                if not text and not bd_name:
                    continue

                line = {
                    "Name": bd_name,
                    "Text": text,
                    "SortOrder": int(sort_order),
                }

                if int(is_passive) == 1:
                    talent["PassiveBuffLines"].append(line)
                else:
                    talent["ActiveBuffLines"].append(line)

        for talent in by_talent_id.values():
            try:
                talent["ActiveBuffLines"].sort(
                    key=lambda x: _safe_int(x.get("SortOrder"), 0) if isinstance(x, dict) else 0
                )
                talent["PassiveBuffLines"].sort(
                    key=lambda x: _safe_int(x.get("SortOrder"), 0) if isinstance(x, dict) else 0
                )
            except Exception:
                pass

        for bid, lst in list(out.items()):
            lst.sort(key=lambda x: (
                int(x.get("HIndex", 0)),
                int(x.get("VIndex", 0)),
                int(x.get("Id", 0)),
            ))
            out[int(bid)] = lst

        return out

    def _prune_selected_talents(self) -> None:
        valid_branch_ids = {
            _safe_int(row.get("Id"), 0)
            for row in (self._talent_branch_slots or [])
            if isinstance(row, dict)
        }

        new_state: Dict[int, Dict[int, int]] = {}

        for bid, cols in (self._selected_talents_by_branch or {}).items():
            ibid = _safe_int(bid, 0)
            if ibid <= 0 or ibid not in valid_branch_ids:
                continue

            available = self._talents_by_branch.get(int(ibid), []) or []
            valid_ids = {_safe_int(t.get("Id"), 0) for t in available if isinstance(t, dict)}

            tmp: Dict[int, int] = {}
            for hidx, tid in (cols or {}).items():
                ih = _safe_int(hidx, -1)
                itid = _safe_int(tid, 0)
                if ih < 0 or itid <= 0:
                    continue
                if itid not in valid_ids:
                    continue
                tmp[int(ih)] = int(itid)

            if tmp:
                new_state[int(ibid)] = dict(sorted(tmp.items()))

        self._selected_talents_by_branch = dict(new_state)

    def _branch_talents(self, branch_id: int) -> List[dict]:
        return list((self._talents_by_branch or {}).get(int(branch_id), []) or [])

    def _branch_selected_cols(self, branch_id: int) -> Dict[int, int]:
        m = (self._selected_talents_by_branch or {}).get(int(branch_id), {})
        if isinstance(m, dict):
            return dict(m)
        return {}

    def _selected_talent_id_for_hindex(self, branch_id: int, hindex: int) -> int:
        cols = self._branch_selected_cols(branch_id)
        return _safe_int(cols.get(int(hindex)), 0)

    def _max_selected_hindex(self, branch_id: int) -> int:
        cols = self._branch_selected_cols(branch_id)
        if not cols:
            return -1
        try:
            return max(int(x) for x in cols.keys())
        except Exception:
            return -1

    def _talent_is_rectangular(self, hindex: int) -> bool:
        return int(hindex) == int(self.TALENT_RECT_HINDEX)

    def _talent_has_default_outline(self, hindex: int) -> bool:
        return int(hindex) not in (3, 6)

    def _draw_talent_default_outline(self, p: QPainter, rect: QRect, hindex: int) -> None:
        """
        Постоянная тёмно-серая обводка:
        - 1 px внутрь
        - 1 px наружу
        Исключения: HIndex = 3 и 6.
        """
        if rect.isEmpty():
            return

        if not self._talent_has_default_outline(hindex):
            return

        pen = QPen(QColor(58, 58, 58, 230), 2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        if self._talent_is_rectangular(hindex):
            p.drawRect(rect.adjusted(-1, -1, 1, 1))
            return

        ellipse_rect = rect.adjusted(-1, -1, 1, 1)
        p.drawEllipse(ellipse_rect)

    def _talent_col_x_local(self, hindex: int) -> int:
        h = max(0, int(hindex))
        x = int(self.TALENT_GRID_X)

        for i in range(h):
            gap = int(self.TALENT_COL_GAPS[i]) if i < len(self.TALENT_COL_GAPS) else int(self.TALENT_COL_GAPS[-1])
            x += int(self.TALENT_ICON_W) + gap

        return int(x)

    def _branch_color_fill_width(self, branch_id: int, slot_rect: QRect) -> int:
        """
        Ширина цветной заливки внутри slot:
        - если таланты не выбраны — заливка до середины первых талантов, HIndex=0;
        - после выбора таланта — заливка до середины следующего доступного таланта;
        - если следующего доступного таланта нет — до середины последнего выбранного;
        - если выбран финальный HIndex=6 — заливаем всю внутреннюю область.
        """
        color_rect = QRect(0, 0, slot_rect.width(), slot_rect.height()).adjusted(4, 8, -8, -8)
        if color_rect.width() <= 0:
            return 0

        local_slot_rect = QRect(0, 0, slot_rect.width(), slot_rect.height())

        branch_talents = [
            t for t in self._branch_talents(branch_id)
            if isinstance(t, dict)
        ]

        def _fill_width_to_talent_center(talent: dict) -> int:
            icon_rect = self._slot_talent_icon_rect(
                local_slot_rect,
                branch_id,
                talent,
            )

            fill_to = int(icon_rect.center().x()) - int(color_rect.left()) + 1
            return max(0, min(int(color_rect.width()), int(fill_to)))

        def _first_talent_at_hindex(hindex: int) -> Optional[dict]:
            candidates = []

            for t in branch_talents:
                if _safe_int(t.get("HIndex"), -1) != int(hindex):
                    continue

                candidates.append(t)

            candidates.sort(key=lambda x: (
                _safe_int(x.get("VIndex"), 0),
                _safe_int(x.get("Id"), 0),
            ))

            return candidates[0] if candidates else None

        # Фолбэк, если в БД/ветке почему-то нет нужных талантов.
        fallback_w = min(
            int(color_rect.width()),
            max(0, int(self.BRANCH_COLOR_BASE_FILL_W)),
        )

        max_h = self._max_selected_hindex(branch_id)

        # Если в ветке ещё ничего не выбрано —
        # заливка должна доходить до середины первых талантов, HIndex=0.
        if max_h < 0:
            first_talent = _first_talent_at_hindex(0)
            if isinstance(first_talent, dict):
                return _fill_width_to_talent_center(first_talent)

            return int(fallback_w)

        # Если выбран последний прямоугольный талант — заливаем всю ветку.
        if int(max_h) >= int(self.TALENT_RECT_HINDEX):
            return int(color_rect.width())

        # После выбора таланта ищем следующий доступный HIndex.
        next_available_talent = None

        try:
            next_h = int(max_h) + 1

            candidates = []
            for t in branch_talents:
                hidx = _safe_int(t.get("HIndex"), -1)
                if hidx != int(next_h):
                    continue

                try:
                    if not self._can_activate_talent(int(branch_id), int(hidx)):
                        continue
                except Exception:
                    continue

                candidates.append(t)

            candidates.sort(key=lambda x: (
                _safe_int(x.get("VIndex"), 0),
                _safe_int(x.get("Id"), 0),
            ))

            if candidates:
                next_available_talent = candidates[0]
        except Exception:
            next_available_talent = None

        # Главное поведение: тянем заливку до середины следующего доступного таланта.
        if isinstance(next_available_talent, dict):
            return _fill_width_to_talent_center(next_available_talent)

        # Фолбэк: если следующего доступного нет,
        # оставляем заливку до середины последнего выбранного таланта.
        selected_tid = self._selected_talent_id_for_hindex(branch_id, max_h)
        if selected_tid <= 0:
            return int(fallback_w)

        selected_talent = None
        for t in branch_talents:
            if _safe_int(t.get("Id"), 0) == int(selected_tid):
                selected_talent = t
                break

        if isinstance(selected_talent, dict):
            return _fill_width_to_talent_center(selected_talent)

        return int(fallback_w)

    def _draw_talent_pixmap_with_shape(self, p: QPainter, rect: QRect, pm: QPixmap, hindex: int) -> None:
        if pm is None or pm.isNull() or rect.isEmpty():
            return

        try:
            scaled = pm.scaled(rect.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        except Exception:
            return

        if self._talent_is_rectangular(hindex):
            p.drawPixmap(rect, scaled)
            return

        p.save()
        path = QPainterPath()
        path.addEllipse(rect)
        p.setClipPath(path)
        p.drawPixmap(rect, scaled)
        p.restore()

    def _draw_talent_hover_outline(self, p: QPainter, rect: QRect, hindex: int) -> None:
        if rect.isEmpty():
            return

        pen = QPen(QColor(243, 216, 137, 210), 2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        if self._talent_is_rectangular(hindex):
            # внешний размер ~50x50 при иконке 48x48
            p.drawRect(rect.adjusted(-1, -1, 1, 1))
            return

        # Внутренний диаметр 48 px, толщина 2 px:
        # рисуем окружность 50x50 вокруг 48x48 области
        ellipse_rect = rect.adjusted(-1, -1, 1, 1)
        p.drawEllipse(ellipse_rect)

    def _can_activate_talent(self, branch_id: int, hindex: int) -> bool:
        cols = self._branch_selected_cols(branch_id)

        if int(hindex) in cols:
            return True

        if int(hindex) == 0:
            return True

        for need in range(0, int(hindex)):
            if int(need) not in cols:
                return False

        max_h = self._max_selected_hindex(branch_id)
        return int(hindex) <= int(max_h) + 1

    def _set_selected_talent_at_hindex(self, branch_id: int, hindex: int, talent_id: int, *,
                                       notify: bool = True) -> None:
        bid = int(branch_id)
        hh = int(hindex)
        tid = int(talent_id)

        cols = self._branch_selected_cols(bid)

        if tid > 0:
            cols[hh] = tid
        else:
            cols.pop(hh, None)

        if cols:
            self._selected_talents_by_branch[bid] = dict(sorted(cols.items()))
        else:
            self._selected_talents_by_branch.pop(bid, None)

        if notify:
            self._notify_selection_changed()

    def _activate_talent(self, talent: dict) -> None:
        if not isinstance(talent, dict):
            return

        bid = _safe_int(talent.get("Branch_Id"), 0)
        hidx = _safe_int(talent.get("HIndex"), 0)
        tid = _safe_int(talent.get("Id"), 0)

        if bid <= 0 or tid <= 0:
            return

        cur_tid = self._selected_talent_id_for_hindex(bid, hidx)

        # Смена таланта в той же колонке разрешена всегда и не тратит новое очко
        if cur_tid > 0:
            if cur_tid != tid:
                self._set_selected_talent_at_hindex(bid, hidx, tid)
            return

        if not self._can_activate_talent(bid, hidx):
            return

        # Новый выбор в новой колонке требует свободное очко таланта
        if self._talent_points_left() <= 0:
            return

        self._set_selected_talent_at_hindex(bid, hidx, tid)

    def _deactivate_talent(self, talent: dict) -> None:
        if not isinstance(talent, dict):
            return

        bid = _safe_int(talent.get("Branch_Id"), 0)
        hidx = _safe_int(talent.get("HIndex"), 0)
        tid = _safe_int(talent.get("Id"), 0)

        if bid <= 0 or tid <= 0:
            return

        cur_tid = self._selected_talent_id_for_hindex(bid, hidx)
        if cur_tid != tid:
            return

        # Снимать можно только последний по HIndex
        if int(hidx) != int(self._max_selected_hindex(bid)):
            return

        self._set_selected_talent_at_hindex(bid, hidx, 0)

    def _slot_talent_icon_rect(self, slot_rect: QRect, branch_id: int, talent: dict) -> QRect:
        hidx = _safe_int(talent.get("HIndex"), 0)
        vidx = _safe_int(talent.get("VIndex"), 0)

        x = int(slot_rect.left()) + int(self._talent_col_x_local(hidx))

        same_col = [t for t in self._branch_talents(branch_id) if _safe_int(t.get("HIndex"), -1) == hidx]
        has_v0 = any(_safe_int(t.get("VIndex"), -1) == 0 for t in same_col)
        has_v1 = any(_safe_int(t.get("VIndex"), -1) == 1 for t in same_col)

        if has_v0 and has_v1:
            if int(vidx) == 1:
                y_local = int(self.TALENT_GRID_Y) + int(self.TALENT_ICON_H) + int(self.TALENT_ROW_GAP)
            else:
                y_local = int(self.TALENT_GRID_Y)
        else:
            total_h = int(self.TALENT_ICON_H) + int(self.TALENT_ROW_GAP) + int(self.TALENT_ICON_H)
            y_local = int(self.TALENT_GRID_Y) + (total_h - int(self.TALENT_ICON_H)) // 2

        y = int(slot_rect.top()) + int(y_local)

        return QRect(int(x), int(y), int(self.TALENT_ICON_W), int(self.TALENT_ICON_H))

    def _hit_talent_icon(self, local_pos: QPoint) -> Tuple[Optional[int], Optional[dict], Optional[QRect]]:
        # Если курсор над кнопкой интерфейса — таланты тут не ловим вообще
        if self._hit_action_part(local_pos):
            return None, None, None

        visible_slots = int(getattr(self, "_talent_branch_visible_count", 1) or 1)
        branch_slots = list(getattr(self, "_talent_branch_slots", [None, None, None, None]) or [None, None, None, None])

        for i in range(max(1, visible_slots)):
            if i >= 4:
                break
            row = branch_slots[i] if i < len(branch_slots) else None
            if not isinstance(row, dict):
                continue

            bid = _safe_int(row.get("Id"), 0)
            if bid <= 0:
                continue

            slot_rect = self._slot_rect_by_index(i)
            for talent in self._branch_talents(bid):
                if not isinstance(talent, dict):
                    continue
                rect = self._slot_talent_icon_rect(slot_rect, bid, talent)
                if rect.contains(local_pos):
                    return int(bid), talent, rect

        return None, None, None

    def _talent_icon_pm_for_state(self, talent: dict, is_selected: bool) -> QPixmap:
        if not isinstance(talent, dict):
            return QPixmap()

        if is_selected:
            iid = _safe_int(talent.get("Image_Id"), 0)
            if iid <= 0:
                iid = _safe_int(talent.get("GrayImage_Id"), 0)
        else:
            iid = _safe_int(talent.get("GrayImage_Id"), 0)
            if iid <= 0:
                iid = _safe_int(talent.get("Image_Id"), 0)

        return self._image_pm(iid)

    def _format_buff_description_line(self, template: str, values_by_order: Dict[int, Any]) -> str:
        """
        Подставляет в BuffDescription.Template значения из TalentBuffDescription.Value
        по индексу TalentBuffDescription.OrderIndex:

          OrderIndex = 0 -> {0}
          OrderIndex = 1 -> {1}
          ...

        ВАЖНО:
        - никакой автоподстановки '+' перед значением не делаем
        - если значения для плейсхолдера нет, оставляем {n} как есть
        """
        tpl = _to_str(template).strip()
        if not tpl:
            return ""

        norm: Dict[int, str] = {}
        for k, v in (values_by_order or {}).items():
            ik = _safe_int(k, -1)
            if ik < 0:
                continue

            if v in (None, ""):
                norm[int(ik)] = ""
                continue

            try:
                fv = float(str(v).replace(",", "."))
                if abs(fv - round(fv)) < 1e-9:
                    sval = str(int(round(fv)))
                else:
                    sval = f"{fv:.4f}".rstrip("0").rstrip(".")
            except Exception:
                sval = str(v)

            norm[int(ik)] = sval

        def _repl(m):
            idx = _safe_int(m.group(1), -1)
            if idx < 0:
                return m.group(0)
            return norm.get(int(idx), m.group(0))

        return re.sub(r"\{(\d+)\}", _repl, tpl).strip()

    def _current_stat_value_for_talent_variable(self, _unused: int = 10) -> float:
        """
        Теперь TalentVariable.Type = 1 всегда означает:
        берём ТЕКУЩУЮ АТАКУ (Stat.Id = 10).

        Аргумент оставлен только для совместимости вызовов.
        """
        sid = 10

        # 1) Через helpers из characteristics_math
        try:
            from .characteristics_math import get_global_stat
        except Exception:
            try:
                from characteristics_math import get_global_stat
            except Exception:
                get_global_stat = None

        if get_global_stat is not None:
            try:
                val = float(get_global_stat(int(sid), 0.0) or 0.0)
                if abs(val) > 1e-12:
                    return val
            except Exception:
                pass

        # 2) Через QApplication.property("current_character_stats")
        try:
            app = QApplication.instance()
            if app is not None:
                raw = app.property("current_character_stats")
                if isinstance(raw, dict):
                    try:
                        val = float(raw.get(int(sid), 0.0) or 0.0)
                        if abs(val) > 1e-12:
                            return val
                    except Exception:
                        pass
        except Exception:
            pass

        # 3) Через stats_panel._last_values_by_id
        host = self.parentWidget()
        try:
            panel = getattr(host, "stats_panel", None)
            if panel is not None:
                last_vals = getattr(panel, "_last_values_by_id", None)
                if isinstance(last_vals, dict):
                    try:
                        val = float(last_vals.get(int(sid), 0.0) or 0.0)
                        if abs(val) > 1e-12:
                            return val
                    except Exception:
                        pass
        except Exception:
            pass

        # 4) Через character_stats у MainWindow
        try:
            stats_dict = getattr(host, "character_stats", None)
            if isinstance(stats_dict, dict):
                try:
                    return float(stats_dict.get(int(sid), 0.0) or 0.0)
                except Exception:
                    pass
        except Exception:
            pass

        return 0.0

    def _format_talent_variable_number(self, value: float) -> str:
        try:
            fv = float(value)
        except Exception:
            return str(value)

        if abs(fv - round(fv)) < 1e-9:
            return str(int(round(fv)))

        return f"{fv:.4f}".rstrip("0").rstrip(".")

    def _render_talent_description_text(self, talent: dict) -> str:
        """
        Подставляет в Talent.Description значения из TalentVariable:

          Index = 0 -> {0}
          Index = 1 -> {1}
          ...

        Новое правило:
          - если TalentVariable.Type == 1:
                подставляем (текущая Атака * TalentVariable.Value)
          - иначе:
                подставляем просто TalentVariable.Value

        Никаких автоплюсов не добавляем.
        """
        desc = _to_str((talent or {}).get("Description")).strip()
        if not desc:
            return ""

        tv_map = (talent or {}).get("TalentVariables") or {}
        if not isinstance(tv_map, dict) or not tv_map:
            return desc

        atk = float(self._current_stat_value_for_talent_variable(10))
        repl_map: Dict[int, str] = {}

        for idx, meta in tv_map.items():
            ii = _safe_int(idx, -1)
            if ii < 0 or not isinstance(meta, dict):
                continue

            typ = _safe_int(meta.get("Type"), 0)
            raw_val = meta.get("Value", 0.0)

            try:
                coef_f = float(raw_val)
            except Exception:
                coef_f = 0.0

            if int(typ) == 1:
                final_val = float(atk) * float(coef_f)
            else:
                final_val = float(coef_f)

            repl_map[int(ii)] = self._format_talent_variable_number(final_val)

        def _repl(m):
            idx = _safe_int(m.group(1), -1)
            if idx < 0:
                return m.group(0)
            return repl_map.get(int(idx), m.group(0))

        return re.sub(r"\{(\d+)\}", _repl, desc)

    def _talent_tooltip_html(self, talent: dict) -> str:
        title = html.escape(_to_str(talent.get("Name")).strip() or "—")
        is_active_skill = (_safe_int(talent.get("Active"), 0) == 1)

        color_title = "#f2c45d"       # жёлто-золотистый
        color_text = "#f2f2f2"        # основной белый текст
        color_muted = "#d6d6d6"
        color_green = "#00d183"
        color_line = "#8f8878"

        parts: List[str] = []

        parts.append(
            f"<div style='color:{color_title}; font-weight:700; font-size:14px;'>"
            f"{title}"
            f"</div>"
        )

        if is_active_skill:
            parts.append(
                f"<div style='color:{color_green}; font-size:12px; margin-top:4px; font-weight:700;'>"
                f"Активное умение"
                f"</div>"
            )
        else:
            parts.append(
                f"<div style='color:{color_green}; font-size:12px; margin-top:4px; font-weight:700;'>"
                f"Пассивное умение"
                f"</div>"
            )

        desc = self._render_talent_description_text(talent).strip()
        if desc:
            parts.append(
                f"<div style='color:{color_text}; font-size:12px; margin-top:6px;'>"
                f"{html.escape(desc).replace(chr(10), '<br>')}"
                f"</div>"
            )

        for line in (talent.get("ActiveBuffLines") or []):
            if isinstance(line, dict):
                bd_name = _to_str(line.get("Name")).strip()
                bd_text = _to_str(line.get("Text")).strip()
            else:
                bd_name = ""
                bd_text = _to_str(line).strip()

            if not bd_name and not bd_text:
                continue

            if bd_name:
                parts.append(
                    "<div style='font-size:12px; margin-top:4px;'>"
                    f"<span style='color:{color_green}; font-weight:700;'>"
                    f"{html.escape(bd_name)}:"
                    f"</span> "
                    f"<span style='color:{color_text};'>"
                    f"{html.escape(bd_text).replace(chr(10), '<br>')}"
                    f"</span>"
                    "</div>"
                )
            else:
                parts.append(
                    f"<div style='color:{color_text}; font-size:12px; margin-top:4px;'>"
                    f"{html.escape(bd_text).replace(chr(10), '<br>')}"
                    f"</div>"
                )

        # ВАЖНО:
        # TalentBonus.Type_Id визуально больше не выводим в tooltip.
        # Расчёты это не ломает, потому что здесь была только отрисовка текста:
        #
        #   bonus_texts = self._get_talent_bonus_texts(...)
        #
        # Сам выбранный талант всё равно публикуется через _publish_selected_talents()
        # и дальше учитывается математикой.

        equip_cond = _to_str(talent.get("EquipmentCondition")).strip()
        if equip_cond:
            parts.append(
                f"<div style='border-top:2px solid {color_line}; margin-top:6px; margin-bottom:6px;'></div>"
            )
            parts.append(
                f"<div style='color:{color_muted}; font-size:12px;'>"
                f"{html.escape(equip_cond).replace(chr(10), '<br>')}"
                f"</div>"
            )

        passive_desc = _to_str(talent.get("PassiveDescription")).strip()
        passive_lines = talent.get("PassiveBuffLines") or []

        has_passive_lines = False
        for x in passive_lines:
            if isinstance(x, dict):
                if _to_str(x.get("Name")).strip() or _to_str(x.get("Text")).strip():
                    has_passive_lines = True
                    break
            else:
                if _to_str(x).strip():
                    has_passive_lines = True
                    break

        if passive_desc or has_passive_lines:
            parts.append(
                f"<div style='color:{color_green}; font-size:12px; margin-top:6px; font-weight:700;'>"
                f"Пассивное умение"
                f"</div>"
            )

            if passive_desc:
                parts.append(
                    f"<div style='color:{color_text}; font-size:12px; margin-top:4px;'>"
                    f"{html.escape(passive_desc).replace(chr(10), '<br>')}"
                    f"</div>"
                )

            for line in passive_lines:
                if isinstance(line, dict):
                    bd_name = _to_str(line.get("Name")).strip()
                    bd_text = _to_str(line.get("Text")).strip()
                else:
                    bd_name = ""
                    bd_text = _to_str(line).strip()

                if not bd_name and not bd_text:
                    continue

                if bd_name:
                    parts.append(
                        "<div style='font-size:12px; margin-top:4px;'>"
                        f"<span style='color:{color_green}; font-weight:700;'>"
                        f"{html.escape(bd_name)}:"
                        f"</span> "
                        f"<span style='color:{color_text};'>"
                        f"{html.escape(bd_text).replace(chr(10), '<br>')}"
                        f"</span>"
                        "</div>"
                    )
                else:
                    parts.append(
                        f"<div style='color:{color_text}; font-size:12px; margin-top:4px;'>"
                        f"{html.escape(bd_text).replace(chr(10), '<br>')}"
                        f"</div>"
                    )

        return "<div>" + "".join(parts) + "</div>"

    def _show_talent_tooltip(self, branch_id: int, talent: dict, icon_rect: QRect) -> None:
        html_text = self._talent_tooltip_html(talent)
        self._tooltip.set_html(html_text, max_w=int(self.TALENT_TOOLTIP_MAX_W))

        x = icon_rect.right() + 12
        y = icon_rect.top()

        if x + self._tooltip.width() > self.width() - 6:
            x = icon_rect.left() - self._tooltip.width() - 12
        if x < 6:
            x = 6

        if y + self._tooltip.height() > self.height() - 6:
            y = self.height() - self._tooltip.height() - 6
        if y < 6:
            y = 6

        self._tooltip.move(int(x), int(y))
        self._tooltip.show()
        self._tooltip.raise_()

    def _update_talent_hover_from_pos(self, local_pos: QPoint) -> None:
        bid, talent, rect = self._hit_talent_icon(local_pos)

        if bid is None or not isinstance(talent, dict) or rect is None:
            self._hover_branch_id = 0
            self._hover_talent_id = 0
            self._hover_talent_rect = None
            self._tooltip.hide()
            self.update()
            return

        tid = _safe_int(talent.get("Id"), 0)
        if self._hover_branch_id == int(bid) and self._hover_talent_id == int(tid):
            self._show_talent_tooltip(int(bid), talent, rect)
            return

        self._hover_branch_id = int(bid)
        self._hover_talent_id = int(tid)
        self._hover_talent_rect = QRect(rect)
        self._show_talent_tooltip(int(bid), talent, rect)
        self.update()

    def _draw_talents_in_slot(self, p: QPainter, slot_rect: QRect, branch_row: Optional[dict]) -> None:
        if not isinstance(branch_row, dict):
            return

        bid = _safe_int(branch_row.get("Id"), 0)
        if bid <= 0:
            return

        hover_bid = int(getattr(self, "_hover_branch_id", 0) or 0)
        hover_tid = int(getattr(self, "_hover_talent_id", 0) or 0)

        for talent in self._branch_talents(bid):
            if not isinstance(talent, dict):
                continue

            tid = _safe_int(talent.get("Id"), 0)
            hidx = _safe_int(talent.get("HIndex"), 0)

            rect = self._slot_talent_icon_rect(slot_rect, bid, talent)
            is_selected = (_safe_int(self._selected_talent_id_for_hindex(bid, hidx), 0) == tid)

            pm = self._talent_icon_pm_for_state(talent, is_selected)
            if pm and not pm.isNull():
                self._draw_talent_pixmap_with_shape(p, rect, pm, hidx)

            # Постоянная тёмно-серая обводка
            self._draw_talent_default_outline(p, rect, hidx)

            # Hover-обводка поверх постоянной
            if hover_bid == bid and hover_tid == tid:
                self._draw_talent_hover_outline(p, rect, hidx)

    def _slot_rect_by_index(self, idx: int) -> QRect:
        r = QRect(self.FIRST_SLOT_RECT)
        if idx > 0:
            r.translate(0, int(idx) * self.FIRST_SLOT_RECT.height())
        return r

    def _draw_talent_branch_slot(self, p: QPainter, slot_rect: QRect, branch_row: Optional[dict]) -> None:
        if isinstance(branch_row, dict):
            color = self._parse_branch_color(branch_row.get("Color"))
            branch_id = _safe_int(branch_row.get("Id"), 0)
        else:
            color = QColor(70, 70, 70, 255)
            branch_id = 0

        underlay = QPixmap(slot_rect.size())
        underlay.fill(Qt.GlobalColor.transparent)

        up = QPainter(underlay)
        up.setRenderHint(QPainter.Antialiasing, True)
        up.setRenderHint(QPainter.SmoothPixmapTransform, True)

        color_rect = QRect(0, 0, slot_rect.width(), slot_rect.height()).adjusted(4, 8, -8, -8)

        fill_w = self._branch_color_fill_width(branch_id, slot_rect) if branch_id > 0 else max(
            0, min(color_rect.width(), int(self.BRANCH_COLOR_BASE_FILL_W))
        )

        if color_rect.width() > 0 and color_rect.height() > 0 and fill_w > 0:
            fill_rect = QRect(color_rect.left(), color_rect.top(), int(fill_w), color_rect.height())
            up.fillRect(fill_rect, color)

        mask_pm = self._slot_fully_transparent_mask_pm(slot_rect.size(), threshold_alpha=80)
        if mask_pm and not mask_pm.isNull():
            up.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            up.drawPixmap(0, 0, mask_pm)

        up.end()

        p.drawPixmap(slot_rect.topLeft(), underlay)

        if self._slot_bg_pm and not self._slot_bg_pm.isNull():
            self._draw_scaled_pm(p, self._slot_bg_pm, slot_rect)

        if isinstance(branch_row, dict):
            name = _to_str(branch_row.get("Name")).strip()
        else:
            name = ""

        if name:
            text_rect = QRect(self.BRANCH_NAME_RECT)
            text_rect.translate(slot_rect.left(), slot_rect.top())

            f = p.font()
            f.setPixelSize(int(self.BRANCH_NAME_FONT_PX))
            p.setFont(f)
            p.setPen(self.BRANCH_NAME_COLOR)

            text_flags = Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignVCenter
            p.drawText(text_rect, text_flags, name)

        # frame_over только если выбран талант HIndex = 6
        if branch_id > 0 and self._branch_has_selected_h6(branch_id):
            if self._frame_over_pm and not self._frame_over_pm.isNull():
                frame_rect = QRect(self.FRAME_OVER_RECT)
                frame_rect.translate(slot_rect.left(), slot_rect.top())
                self._draw_scaled_pm(p, self._frame_over_pm, frame_rect)

    def _draw_scaled_pm(self, p: QPainter, pm: QPixmap, rect: QRect) -> None:
        if pm is None or pm.isNull() or rect.isEmpty():
            return
        try:
            scaled = pm.scaled(rect.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        except Exception:
            return
        p.drawPixmap(rect, scaled)

    def _slot_fully_transparent_mask_pm(self, size, threshold_alpha: int = 2) -> QPixmap:
        """
        Маска для цветной подложки talent_slot.

        Цвет остаётся только там, где пиксель slot имеет alpha <= threshold_alpha.
        По умолчанию 26 ~= прозрачность 90%+.
        """
        try:
            w = int(size.width())
            h = int(size.height())
        except Exception:
            return QPixmap()

        if w <= 0 or h <= 0:
            return QPixmap()

        threshold_alpha = max(0, min(255, int(threshold_alpha)))

        cache = getattr(self, "_slot_transparent_mask_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._slot_transparent_mask_cache = cache

        key = (w, h, threshold_alpha)
        cached = cache.get(key)
        if isinstance(cached, QPixmap) and not cached.isNull():
            return cached

        if self._slot_bg_pm is None or self._slot_bg_pm.isNull():
            return QPixmap()

        try:
            scaled = self._slot_bg_pm.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
            src = scaled.toImage().convertToFormat(QImage.Format_ARGB32)
        except Exception:
            return QPixmap()

        try:
            mask_img = QImage(w, h, QImage.Format_ARGB32)
            mask_img.fill(Qt.GlobalColor.transparent)
        except Exception:
            return QPixmap()

        white = QColor(255, 255, 255, 255)
        transparent = QColor(0, 0, 0, 0)

        for y in range(h):
            for x in range(w):
                try:
                    a = src.pixelColor(x, y).alpha()
                except Exception:
                    a = 255

                if a <= threshold_alpha:
                    mask_img.setPixelColor(x, y, white)
                else:
                    mask_img.setPixelColor(x, y, transparent)

        pm = QPixmap.fromImage(mask_img)
        cache[key] = pm
        return pm

    def _draw_pm_fit_center(self, p: QPainter, pm: QPixmap, rect: QRect) -> None:
        """
        Рисует картинку с сохранением пропорций,
        масштабируя её ВНУТРИ заданной области и центрируя в ней.
        """
        if pm is None or pm.isNull() or rect.isEmpty():
            return

        try:
            scaled = pm.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:
            return

        draw_rect = QRect(0, 0, scaled.width(), scaled.height())
        draw_rect.moveCenter(rect.center())
        p.drawPixmap(draw_rect, scaled)

    def _class_icon_pm(self, image_id: int) -> QPixmap:
        return self._image_pm(_safe_int(image_id, 0))

    def _draw_class_cover_info(self, p: QPainter, cover_rect: QRect) -> None:
        row = getattr(self, "_current_class_row", None)
        if not isinstance(row, dict):
            return

        icon_rect = QRect(self.CLASS_INFO_ICON_RECT)
        text_rect = QRect(self.CLASS_INFO_TEXT_RECT)

        if icon_rect.isEmpty() or text_rect.isEmpty():
            return

        icon_pm = self._class_icon_pm(_safe_int(row.get("Class_Image_Id"), 0))
        if not icon_pm.isNull():
            self._draw_pm_fit_center(p, icon_pm, icon_rect)

        title = _to_str(row.get("Name")).strip()
        desc = _to_str(row.get("Talent_Description")).strip()
        var_text = _to_str(row.get("Class_Variable")).strip()

        cur_y = text_rect.top()

        title_font = p.font()
        title_font.setBold(True)
        title_font.setPixelSize(int(self.CLASS_TITLE_FONT_PX))

        body_font = p.font()
        body_font.setBold(False)
        body_font.setPixelSize(int(self.CLASS_BODY_FONT_PX))

        # 1 строка — имя класса
        p.setPen(QColor("#f2e4bb"))
        p.setFont(title_font)

        title_h = QFontMetrics(title_font).boundingRect(
            QRect(text_rect.left(), cur_y, text_rect.width(), 1000),
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
            title,
        ).height()
        title_rect = QRect(text_rect.left(), cur_y, text_rect.width(), title_h)
        p.drawText(title_rect, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, title)
        cur_y = title_rect.bottom() + int(self.CLASS_TITLE_BOTTOM_GAP)

        # 2 строка — Talent_Description
        p.setPen(QColor("#d6cdb8"))
        p.setFont(body_font)

        if desc:
            desc_h = QFontMetrics(body_font).boundingRect(
                QRect(text_rect.left(), cur_y, text_rect.width(), 1000),
                Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
                desc,
            ).height()
            desc_rect = QRect(text_rect.left(), cur_y, text_rect.width(), desc_h)
            p.drawText(desc_rect, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, desc)
            cur_y = desc_rect.bottom() + int(self.CLASS_DESC_BOTTOM_GAP)

        # 3 строка — Class_Variable
        if var_text:
            var_h = QFontMetrics(body_font).boundingRect(
                QRect(text_rect.left(), cur_y, text_rect.width(), 1000),
                Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
                var_text,
            ).height()
            var_rect = QRect(text_rect.left(), cur_y, text_rect.width(), var_h)
            p.drawText(var_rect, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, var_text)

    def _hit_action_part(self, local_pos: QPoint) -> str:
        if self.CLOSE_RECT.contains(local_pos):
            return "close"
        if self.BIG_CLOSE_RECT.contains(local_pos):
            return "big_close"
        if self.RESET_RECT.contains(local_pos):
            return "reset"
        return ""

    def _set_hover_part(self, local_pos: QPoint) -> None:
        new_hover = self._hit_action_part(local_pos)
        if new_hover != self._hover_part:
            self._hover_part = new_hover
            self.update()

    def _clear_pending_talent_action(self) -> None:
        self._pending_talent_action = ""
        self._pending_talent_branch_id = 0
        self._pending_talent_id = 0

    def _clear_talent_hover(self) -> None:
        self._hover_branch_id = 0
        self._hover_talent_id = 0
        self._hover_talent_rect = None
        self._tooltip.hide()

    def get_selected_talents(self) -> List[dict]:
        out: List[dict] = []

        visible_slots = int(getattr(self, "_talent_branch_visible_count", 1) or 1)
        branch_slots = list(getattr(self, "_talent_branch_slots", [None, None, None, None]) or [None, None, None, None])

        for i in range(max(1, visible_slots)):
            if i >= 4:
                break

            row = branch_slots[i] if i < len(branch_slots) else None
            if not isinstance(row, dict):
                continue

            bid = _safe_int(row.get("Id"), 0)
            if bid <= 0:
                continue

            cols = self._branch_selected_cols(bid)
            for hidx in sorted(cols.keys()):
                tid = _safe_int(cols.get(hidx), 0)
                if tid <= 0:
                    continue

                out.append(
                    {
                        "Branch_Id": int(bid),
                        "Talent_Id": int(tid),
                        "HIndex": int(hidx),
                    }
                )

        return out

    def _publish_selected_talents(self) -> None:
        selected: List[dict] = []

        for row in (self.get_selected_talents() or []):
            if not isinstance(row, dict):
                continue

            bid = _safe_int(row.get("Branch_Id"), 0)
            tid = _safe_int(row.get("Talent_Id"), 0)
            hidx = _safe_int(row.get("HIndex"), -1)

            if bid <= 0 or tid <= 0 or hidx < 0:
                continue

            selected.append(
                {
                    "Branch_Id": int(bid),
                    "Talent_Id": int(tid),
                    "HIndex": int(hidx),
                }
            )

        try:
            app = QApplication.instance()
            if app is not None:
                app.setProperty("player_talents", list(selected))
        except Exception:
            pass

    def _notify_selection_changed(self) -> None:
        self._publish_selected_talents()

        try:
            self.selectionChanged.emit()
        except Exception:
            pass

        host = self.parentWidget()

        try:
            if host is not None:
                fn = getattr(host, "refresh_stats_panel", None)
                if callable(fn):
                    fn()
        except Exception:
            pass

        # Обновляем меню бафов/дебафов, если оно уже создано
        try:
            if host is not None:
                w = getattr(host, "_buff_debuff_menu_window", None)
                if w is not None:
                    fn = getattr(w, "refresh_runtime_context", None)
                    if callable(fn):
                        fn()
        except Exception:
            pass

    def _format_bonus_type_value(self, v: Any) -> str:
        try:
            fv = float(v)
            if abs(fv - round(fv)) < 1e-9:
                return str(int(round(fv)))
            return f"{fv:.4f}".rstrip("0").rstrip(".")
        except Exception:
            return str(v)

    def _format_bonus_type_template(self, template: str, value: Any) -> str:
        tpl = _to_str(template).strip()
        if not tpl:
            return ""

        sval = self._format_bonus_type_value(value)

        def _repl(m):
            return sval

        return re.sub(r"\{(\d+)\}", _repl, tpl)

    def _get_talent_bonus_texts(self, talent_id: int) -> List[str]:
        conn = self._conn()
        tid = _safe_int(talent_id, 0)
        if conn is None or tid <= 0:
            return []

        try:
            rows = conn.execute(
                """
                SELECT tb.Type_Id, tb.Value, bt.Template
                FROM TalentBonus AS tb
                JOIN BonusType AS bt ON bt.Id = tb.Type_Id
                WHERE tb.Talent_Id=?
                  AND (tb.AuraCondition_Id IS NULL OR tb.AuraCondition_Id=0)
                  AND (tb.BuffCondition_Id IS NULL OR tb.BuffCondition_Id=0)
                ORDER BY tb.Id
                """,
                (int(tid),),
            ).fetchall()
        except Exception:
            rows = []

        out: List[str] = []

        for r in rows or []:
            try:
                if hasattr(r, "keys"):
                    val = r["Value"]
                    tpl = _to_str(r["Template"])
                else:
                    val = r[1]
                    tpl = _to_str(r[2])
            except Exception:
                continue

            text = self._format_bonus_type_template(tpl, val).strip()
            if text:
                out.append(text)

        return out

    def _reset_all_talents(self) -> None:
        self._selected_talents_by_branch = {}
        self._hover_branch_id = 0
        self._hover_talent_id = 0
        self._hover_talent_rect = None
        self._tooltip.hide()
        self.update()

    def open_centered(self, host: QWidget) -> None:
        try:
            refresh_fn = getattr(host, "refresh_stats_panel", None)
            if callable(refresh_fn):
                refresh_fn()
        except Exception:
            pass

        try:
            cid = 0
            if hasattr(host, "_current_class_id"):
                cid = _safe_int(host._current_class_id(), 0)
            self.set_class_id(cid)
        except Exception:
            pass

        try:
            self._enforce_talent_points_limit()
        except Exception:
            pass

        if isinstance(self._last_global_pos, QPoint):
            try:
                self.move(self._last_global_pos)
            except Exception:
                pass
        else:
            try:
                host_geo = host.frameGeometry()
                x = int(host_geo.center().x() - self.width() / 2)
                y = int(host_geo.center().y() - self.height() / 2)
                self.move(x, y)
            except Exception:
                self.move(100, 100)

        self.show()
        self.raise_()
        try:
            self.activateWindow()
        except Exception:
            pass

        try:
            self._refresh_hovered_talent_tooltip()
        except Exception:
            pass

        self.update()

    def mousePressEvent(self, ev) -> None:
        local_pos = ev.position().toPoint()

        if ev.button() == Qt.RightButton:
            hit = self._hit_action_part(local_pos)
            if hit:
                self._pressed_part = ""
                self._clear_pending_talent_action()
                self._clear_talent_hover()
                self.update()
                ev.accept()
                return

            bid, talent, _rect = self._hit_talent_icon(local_pos)
            if bid is not None and isinstance(talent, dict):
                self._pending_talent_action = "deactivate"
                self._pending_talent_branch_id = int(bid)
                self._pending_talent_id = _safe_int(talent.get("Id"), 0)
                self._update_talent_hover_from_pos(local_pos)
                self.update()
                ev.accept()
                return

            self._clear_pending_talent_action()
            return super().mousePressEvent(ev)

        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)

        hit = self._hit_action_part(local_pos)
        if hit:
            self._pressed_part = hit
            self._hover_part = hit
            self._clear_pending_talent_action()
            self._clear_talent_hover()
            self.update()
            ev.accept()
            return

        bid, talent, _rect = self._hit_talent_icon(local_pos)
        if bid is not None and isinstance(talent, dict):
            self._pressed_part = ""
            self._pending_talent_action = "activate"
            self._pending_talent_branch_id = int(bid)
            self._pending_talent_id = _safe_int(talent.get("Id"), 0)
            self._update_talent_hover_from_pos(local_pos)
            self.update()
            ev.accept()
            return

        self._pressed_part = ""
        self._clear_pending_talent_action()
        self._clear_talent_hover()

        try:
            gp = ev.globalPosition().toPoint()
        except Exception:
            gp = ev.globalPos()

        self._drag_active = True
        self._drag_offset = gp - self.frameGeometry().topLeft()
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag_active:
            try:
                gp = ev.globalPosition().toPoint()
            except Exception:
                gp = ev.globalPos()

            new_pos = gp - self._drag_offset
            self.move(new_pos)
            self._last_global_pos = QPoint(new_pos)
            ev.accept()
            return

        local_pos = ev.position().toPoint()
        hit = self._hit_action_part(local_pos)
        self._set_hover_part(local_pos)

        if hit:
            self._clear_talent_hover()
            self.update()
            super().mouseMoveEvent(ev)
            return

        self._update_talent_hover_from_pos(local_pos)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        local_pos = ev.position().toPoint()

        if ev.button() == Qt.LeftButton and self._drag_active:
            self._drag_active = False
            try:
                self._last_global_pos = QPoint(self.pos())
            except Exception:
                pass
            self._clear_pending_talent_action()
            ev.accept()
            return

        # release для кнопок интерфейса
        if ev.button() == Qt.LeftButton:
            hit = self._hit_action_part(local_pos)
            should_trigger = bool(self._pressed_part) and (hit == self._pressed_part)
            pressed_part = self._pressed_part

            self._pressed_part = ""
            self._hover_part = hit

            if should_trigger:
                if pressed_part in ("close", "big_close"):
                    self._clear_pending_talent_action()
                    self.update()
                    self.close()
                    ev.accept()
                    return

                if pressed_part == "reset":
                    self._clear_pending_talent_action()
                    self._clear_talent_hover()
                    self._reset_all_talents()
                    self.update()
                    ev.accept()
                    return

            # release для ЛКМ по таланту
            if self._pending_talent_action == "activate":
                bid, talent, _rect = self._hit_talent_icon(local_pos)
                if (
                        bid is not None
                        and isinstance(talent, dict)
                        and int(bid) == int(self._pending_talent_branch_id)
                        and _safe_int(talent.get("Id"), 0) == int(self._pending_talent_id)
                ):
                    self._activate_talent(talent)
                    self._update_talent_hover_from_pos(local_pos)
                    self.update()

                self._clear_pending_talent_action()
                ev.accept()
                return

            self._clear_pending_talent_action()
            self.update()
            return super().mouseReleaseEvent(ev)

        # release для ПКМ по таланту
        if ev.button() == Qt.RightButton:
            if self._pending_talent_action == "deactivate":
                bid, talent, _rect = self._hit_talent_icon(local_pos)
                if (
                        bid is not None
                        and isinstance(talent, dict)
                        and int(bid) == int(self._pending_talent_branch_id)
                        and _safe_int(talent.get("Id"), 0) == int(self._pending_talent_id)
                ):
                    self._deactivate_talent(talent)
                    self._update_talent_hover_from_pos(local_pos)
                    self.update()

                self._clear_pending_talent_action()
                ev.accept()
                return

            self._clear_pending_talent_action()
            return super().mouseReleaseEvent(ev)

        return super().mouseReleaseEvent(ev)

    def leaveEvent(self, ev) -> None:
        self._hover_part = ""
        self._hover_branch_id = 0
        self._hover_talent_id = 0
        self._hover_talent_rect = None
        self._tooltip.hide()
        self.update()
        super().leaveEvent(ev)

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            self.close()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def closeEvent(self, ev) -> None:
        self._drag_active = False
        self._pressed_part = ""
        self._hover_part = ""
        self._clear_pending_talent_action()
        self._hover_branch_id = 0
        self._hover_talent_id = 0
        self._hover_talent_rect = None
        self._tooltip.hide()

        try:
            self._last_global_pos = QPoint(self.pos())
        except Exception:
            pass

        try:
            self.closed.emit()
        except Exception:
            pass

        super().closeEvent(ev)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        if self._bg_pm and not self._bg_pm.isNull():
            p.drawPixmap(self.rect(), self._bg_pm)
        else:
            p.fillRect(self.rect(), QColor(20, 20, 20, 240))

        row = getattr(self, "_current_class_row", None)
        base_id = _safe_int((row or {}).get("Base_Id"), 0)

        visible_slots = int(getattr(self, "_talent_branch_visible_count", 1) or 1)
        branch_slots = list(getattr(self, "_talent_branch_slots", [None, None, None, None]) or [None, None, None, None])

        for i in range(max(1, visible_slots)):
            if i >= 4:
                break
            slot_rect = self._slot_rect_by_index(i)
            branch_row = branch_slots[i] if i < len(branch_slots) else None
            self._draw_talent_branch_slot(p, slot_rect, branch_row)
            self._draw_talents_in_slot(p, slot_rect, branch_row)

        if base_id <= 0:
            cover_rect = QRect(self.COVER_RECT)
            if self._cover_bg_pm and not self._cover_bg_pm.isNull():
                self._draw_scaled_pm(p, self._cover_bg_pm, cover_rect)
            self._draw_class_cover_info(p, cover_rect)

        # Очки талантов
        points_left = self._talent_points_left()
        pts_rect = QRect(self.TALENT_POINTS_RECT)
        pts_font = QFont("Segoe UI")
        pts_font.setBold(True)
        pts_font.setPixelSize(int(self.TALENT_POINTS_FONT_PX))
        p.setFont(pts_font)
        p.setPen(self.TALENT_POINTS_COLOR_OK if points_left > 0 else self.TALENT_POINTS_COLOR_ZERO)
        p.drawText(pts_rect, Qt.AlignLeft | Qt.AlignVCenter, str(int(points_left)))

        # reset кнопка — рисуем ПОСЛЕ слотов, чтобы она была сверху
        if self._hover_part == "reset" or self._pressed_part == "reset":
            if self._reset_pm and not self._reset_pm.isNull():
                p.drawPixmap(self.RESET_RECT, self._reset_pm)

        # большая кнопка закрытия
        if self._hover_part == "big_close" or self._pressed_part == "big_close":
            if self._big_close_pm and not self._big_close_pm.isNull():
                p.drawPixmap(self.BIG_CLOSE_RECT, self._big_close_pm)

        # крестик
        if self._hover_part == "close" or self._pressed_part == "close":
            if self._close_active_pm and not self._close_active_pm.isNull():
                p.drawPixmap(self.CLOSE_RECT, self._close_active_pm)

        p.end()