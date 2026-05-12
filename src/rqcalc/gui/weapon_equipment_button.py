# weapon_equipment_button.py (clean/db-driven)
from __future__ import annotations

from pathlib import Path
from typing import Optional, Callable, List, Dict, Any

from PySide6.QtCore import Qt, QPoint, QRect, QSize, Signal, QTimer
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QMenu, QWidget, QWidgetAction, QLabel, QGridLayout, QVBoxLayout,
    QScrollArea, QFrame, QHBoxLayout, QLineEdit,
    QAbstractSlider, QApplication,
)

from src.rqcalc.db import DataAccess

# ---------- UI ----------
_MENU_WIDTH_PX = 600
_VISIBLE_ROWS = 5
_CARD_H_MIN = 32
_CARD_H_MAX = 50

# ---------- логика ----------
DONOR_MAP = {1: {2, 3}, 4: {5, 6}, 7: {8, 9}, 10: {11, 12}}

# ---------- misc ----------
def _find_scroll_dir() -> Path:
    for p in (
        Path.cwd() / "resources" / "helper_buttons",
        Path(__file__).resolve().parents[2] / "resources" / "helper_buttons",
        Path(__file__).resolve().parents[3] / "resources" / "helper_buttons",
    ):
        if p.exists():
            return p
    return Path.cwd() / "resources" / "helper_buttons"


class ImageVScrollBar(QWidget):
    """
    Лёгкий скин-скроллбар с синхронизацией.

    ВАЖНО:
    PNG-картинки НЕ растягиваются.
    scroll_button_up/down и scroller рисуются в своём оригинальном размере.
    Увеличение высоты скролла увеличивает только путь движения бегунка,
    а не размер самого бегунка.
    """

    def __init__(self, target_bar, assets_dir: Path, parent=None):
        super().__init__(parent)
        self.bar = target_bar

        pm = lambda n: QPixmap(str(assets_dir / n))

        self.up = pm("scroll_button_up.png")
        self.up_h = pm("scroll_button_up_active.png")
        self.up_end = pm("scroll_button_up_end.png")

        self.dn = pm("scroll_button_down.png")
        self.dn_h = pm("scroll_button_down_active.png")
        self.dn_end = pm("scroll_button_down_end.png")

        self.handle = pm("scroller.png")
        self.handle_h = pm("scroller_active.png")

        self.btn_h = max(
            18,
            self.up.height() if not self.up.isNull() else 0,
            self.up_h.height() if not self.up_h.isNull() else 0,
            self.up_end.height() if not self.up_end.isNull() else 0,
            self.dn.height() if not self.dn.isNull() else 0,
            self.dn_h.height() if not self.dn_h.isNull() else 0,
            self.dn_end.height() if not self.dn_end.isNull() else 0,
        )

        self._handle_w = max(
            10,
            self.handle.width() if not self.handle.isNull() else 0,
            self.handle_h.width() if not self.handle_h.isNull() else 0,
        )
        self._handle_h = max(
            10,
            self.handle.height() if not self.handle.isNull() else 0,
            self.handle_h.height() if not self.handle_h.isNull() else 0,
        )

        self._w = max(
            20,
            self.up.width() if not self.up.isNull() else 0,
            self.up_h.width() if not self.up_h.isNull() else 0,
            self.up_end.width() if not self.up_end.isNull() else 0,
            self.dn.width() if not self.dn.isNull() else 0,
            self.dn_h.width() if not self.dn_h.isNull() else 0,
            self.dn_end.width() if not self.dn_end.isNull() else 0,
            self._handle_w,
        )

        self.setFixedWidth(int(self._w))
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")

        self._hover = QPoint(-1, -1)
        self._dragging = False
        self._drag_off = 0

        try:
            self.bar.valueChanged.connect(lambda *_: self.update())
        except Exception:
            pass

        try:
            self.bar.rangeChanged.connect(lambda *_: self.update())
        except Exception:
            pass

    def _track_rect(self) -> QRect:
        r = self.rect()
        return QRect(
            0,
            int(self.btn_h),
            int(r.width()),
            max(0, int(r.height() - 2 * self.btn_h)),
        )

    def _handle_len(self, track_h: int) -> int:
        """
        Оставлено для совместимости со старым кодом.
        Теперь длина бегунка = размеру PNG, а не зависит от pageStep.
        """
        return min(max(1, int(track_h)), int(self._handle_h))

    def _handle_rect(self) -> QRect:
        tr = self._track_rect()
        if tr.height() <= 0:
            return QRect()

        h = min(int(self._handle_h), max(1, int(tr.height())))
        w = min(int(self._handle_w), max(1, int(tr.width())))

        usable = max(1, int(tr.height() - h))
        rng = max(1, int(self.bar.maximum() - self.bar.minimum()))

        if rng <= 0:
            frac = 0.0
        else:
            frac = float(int(self.bar.value()) - int(self.bar.minimum())) / float(rng)

        y = int(tr.top() + usable * frac)
        x = int(tr.left() + (tr.width() - w) / 2)

        return QRect(x, y, w, h)

    def sizeHint(self) -> QSize:
        return QSize(int(self._w), 160)

    def _draw_pixmap_centered(self, p: QPainter, target: QRect, pm: QPixmap) -> None:
        """
        Рисует PNG в оригинальном размере по центру target.
        Ничего не масштабирует.
        """
        if pm is None or pm.isNull() or target.isEmpty():
            return

        x = int(target.left() + (target.width() - pm.width()) / 2)
        y = int(target.top() + (target.height() - pm.height()) / 2)

        p.drawPixmap(x, y, pm)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)

        r = self.rect()

        up_r = QRect(0, 0, r.width(), self.btn_h)
        dn_r = QRect(0, r.height() - self.btn_h, r.width(), self.btn_h)
        hr = self._handle_rect()

        # Верхняя кнопка
        if self.bar.value() <= self.bar.minimum() and not self.up_end.isNull():
            up_pm = self.up_end
        elif up_r.contains(self._hover) and not self.up_h.isNull():
            up_pm = self.up_h
        else:
            up_pm = self.up

        self._draw_pixmap_centered(p, up_r, up_pm)

        # Нижняя кнопка
        if self.bar.value() >= self.bar.maximum() and not self.dn_end.isNull():
            dn_pm = self.dn_end
        elif dn_r.contains(self._hover) and not self.dn_h.isNull():
            dn_pm = self.dn_h
        else:
            dn_pm = self.dn

        self._draw_pixmap_centered(p, dn_r, dn_pm)

        # Бегунок
        if not hr.isEmpty():
            handle_pm = self.handle_h if (hr.contains(self._hover) and not self.handle_h.isNull()) else self.handle
            self._draw_pixmap_centered(p, hr, handle_pm)

        p.end()

    def mouseMoveEvent(self, ev):
        self._hover = ev.pos()

        if self._dragging:
            tr = self._track_rect()
            hr = self._handle_rect()
            hr_h = max(1, int(hr.height()))

            usable = max(1, int(tr.height() - hr_h))
            y = int(ev.pos().y() - self._drag_off)
            y = max(int(tr.top()), min(int(tr.top() + usable), y))

            rng = max(1, int(self.bar.maximum() - self.bar.minimum()))
            value = int(self.bar.minimum() + rng * ((y - tr.top()) / float(usable)))

            self.bar.setValue(value)

        self.update()

    def leaveEvent(self, _):
        self._hover = QPoint(-1, -1)
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return

        up_r = QRect(0, 0, self.width(), self.btn_h)
        dn_r = QRect(0, self.height() - self.btn_h, self.width(), self.btn_h)
        hr = self._handle_rect()
        tr = self._track_rect()

        if up_r.contains(ev.pos()):
            if self.bar.value() > self.bar.minimum():
                self.bar.triggerAction(QAbstractSlider.SliderSingleStepSub)

        elif dn_r.contains(ev.pos()):
            if self.bar.value() < self.bar.maximum():
                self.bar.triggerAction(QAbstractSlider.SliderSingleStepAdd)

        elif hr.contains(ev.pos()):
            self._dragging = True
            self._drag_off = int(ev.pos().y() - hr.top())

        elif tr.contains(ev.pos()):
            if ev.pos().y() < hr.top():
                self.bar.triggerAction(QAbstractSlider.SliderPageStepSub)
            else:
                self.bar.triggerAction(QAbstractSlider.SliderPageStepAdd)

        self.update()
        ev.accept()

    def wheelEvent(self, ev):
        if ev.angleDelta().y() > 0:
            self.bar.triggerAction(QAbstractSlider.SliderSingleStepSub)
        else:
            self.bar.triggerAction(QAbstractSlider.SliderSingleStepAdd)

        ev.accept()
        self.update()

    def mouseReleaseEvent(self, ev):
        self._dragging = False
        self.update()
        ev.accept()


# ---------- helpers по БД ----------
def _armor_bl_for_level(level: Optional[int]) -> float:
    """
    armorBL = 10040 * e^(0.05 * lvl) / e^(0.05 * 60)
    """
    import math

    try:
        lvl = int(level) if level is not None else None
    except Exception:
        lvl = None

    if lvl is None:
        return 1.0

    return 10040.0 * math.exp(0.05 * float(lvl)) / math.exp(0.05 * 60.0)


def _row_get(row, key: str, idx: int = 0):
    """sqlite.Row-safe getter"""
    if row is None:
        return None
    try:
        return row[key]
    except Exception:
        try:
            return row[idx]
        except Exception:
            return None


def _class_lineage_ids(conn, class_id: int) -> list[int]:
    """
    Возвращает [class_id, base_id, base_of_base, ...] пока Base_Id не NULL.
    Защита от циклов.
    """
    out: list[int] = []
    seen: set[int] = set()
    cur = int(class_id)

    while cur and cur not in seen:
        out.append(cur)
        seen.add(cur)
        row = conn.execute("SELECT Base_Id FROM Class WHERE Id = ?", (cur,)).fetchone()
        base = _row_get(row, "Base_Id", 0)
        if base is None:
            break
        cur = int(base)

    return out


def _class_allow_extra_weapon(conn, class_id: Optional[int]) -> bool:
    """
    AllowExtraWeapon с учётом наследования:
    если у класса NULL -> берём у Base_Id и т.д.
    """
    if class_id is None:
        return False

    for cid in _class_lineage_ids(conn, int(class_id)):
        row = conn.execute("SELECT AllowExtraWeapon FROM Class WHERE Id = ?", (cid,)).fetchone()
        v = _row_get(row, "AllowExtraWeapon", 0)
        if v is not None:
            return int(v) == 1

    return False


def _allowed_class_ids(conn, class_id: Optional[int]) -> Optional[set[int]]:
    """
    Для фильтрации по EquipmentCondition / EquipmentTypeCondition:
    - включаем текущий класс + всех родителей по Base_Id
    - плюс добавляем donor по DONOR_MAP (если текущий/родитель является receiver)
    """
    if class_id is None:
        return None

    base_chain = set(_class_lineage_ids(conn, int(class_id)))

    # donor map: если наш класс (или его база) в receivers -> добавляем donor
    for donor, receivers in DONOR_MAP.items():
        if any(cid in receivers for cid in base_chain):
            base_chain.add(int(donor))

    return base_chain

def _has_col(conn, table: str, col: str) -> bool:
    return any(r[1] == col for r in conn.execute(f"PRAGMA table_info({table})"))

def _first_col(conn, table: str, candidates: list[str]) -> str | None:
    for c in candidates:
        if _has_col(conn, table, c):
            return c
    return None

def _image_col(conn) -> str:
    return "Image_Id" if _has_col(conn, "Equipment", "Image_Id") else "Image_ID"

def _icon_col(conn) -> str | None:
    return "Icon_Image_Id" if _has_col(conn, "Equipment", "Icon_Image_Id") else None

def _bonus_template_col(conn) -> str:
    return _first_col(
        conn, "BonusType",
        ["Template", "TextTemplate", "Text", "Text1", "Text2", "Text3", "DisplayText", "Description", "Desc", "Name"]
    ) or "Name"

def _render_bonus_lines(conn, equip_id: int, char_level: Optional[int] = None) -> list[str]:
    import re

    tmpl_col = _bonus_template_col(conn)

    var_table = "EquipmentBonusVariable"
    var_cols = {r[1] for r in conn.execute(f'PRAGMA table_info({var_table})')}

    raw_idx = "VarIndex" if "VarIndex" in var_cols else ("Index" if "Index" in var_cols else None)
    idx_sql = raw_idx if (raw_idx and raw_idx != "Index") else ('"Index"' if raw_idx else None)
    val_col = "Value" if "Value" in var_cols else next(
        (c for c in var_cols if c not in {"EquipmentBonus_Id", "VarIndex", "Index"}), None
    )
    if not val_col:
        return []

    armor_bl = _armor_bl_for_level(char_level)

    mul_idx_cache: dict[int, set[int]] = {}

    def _mul_indices_for_bonus_type(bonus_type_id: int) -> set[int]:
        if bonus_type_id in mul_idx_cache:
            return mul_idx_cache[bonus_type_id]

        try:
            cols = {r[1] for r in conn.execute('PRAGMA table_info("BonusTypeVariable")')}
        except Exception:
            mul_idx_cache[bonus_type_id] = set()
            return mul_idx_cache[bonus_type_id]

        if "BonusType_Id" not in cols or "MulFormula_Id" not in cols or "Index" not in cols:
            mul_idx_cache[bonus_type_id] = set()
            return mul_idx_cache[bonus_type_id]

        try:
            rows = conn.execute(
                """
                SELECT "Index" AS idx
                FROM BonusTypeVariable
                WHERE BonusType_Id = ? AND MulFormula_Id = 16
                """,
                (int(bonus_type_id),)
            ).fetchall()
            s = {int(r["idx"]) for r in rows if r["idx"] is not None}
        except Exception:
            s = set()

        mul_idx_cache[bonus_type_id] = s
        return s

    def _round_half_up_to_int(x: float) -> int:
        import math
        return int(math.floor(x + 0.5)) if x >= 0 else int(math.ceil(x - 0.5))

    def _try_mul(v: str, mul: float) -> str:
        s = (v or "").strip()
        if not s:
            return v

        try:
            num = float(s.replace(",", "."))
        except Exception:
            return v

        out = num * float(mul)
        return str(_round_half_up_to_int(out))

    def _ensure_leading_plus(line: str) -> str:
        s = str(line or "").strip()
        if not s:
            return s

        # Уже со знаком — не трогаем
        if s.startswith("+") or s.startswith("-"):
            return s

        # Если строка начинается с числа/процента — добавляем "+"
        # Примеры:
        #   "1 к Выносливости"   -> "+1 к Выносливости"
        #   "5% к Атаке"         -> "+5% к Атаке"
        #   "12.5 к атаке"       -> "+12.5 к атаке"
        #   "0.5% ..."           -> "+0.5% ..."
        if re.match(r"^\d+(?:[.,]\d+)?%?(?:\s|$)", s):
            return "+" + s

        return s

    active_buff_ids: set[int] = set()
    try:
        app = QApplication.instance()
        raw = app.property("player_buff_ids") if app is not None else None
        if isinstance(raw, (list, tuple, set)):
            for x in raw:
                bid = _safe_int(x, 0)
                if bid > 0:
                    active_buff_ids.add(int(bid))
    except Exception:
        pass

    eb_cols = {r[1] for r in conn.execute('PRAGMA table_info("EquipmentBonus")')}
    has_buff_cond = ("BuffCondition_Id" in eb_cols)

    extra_select = ", eb.BuffCondition_Id AS BuffConditionId" if has_buff_cond else ", NULL AS BuffConditionId"

    rows = conn.execute(
        f"""
        SELECT eb.Id AS EBId,
               eb.OrderIndex,
               eb.Type_Id AS TypeId
               {extra_select},
               bt.{tmpl_col} AS Tmpl
        FROM EquipmentBonus eb
        JOIN BonusType bt ON bt.Id = eb.Type_Id
        WHERE eb.Equipment_Id = ?
        ORDER BY eb.OrderIndex
        """,
        (int(equip_id),)
    ).fetchall()

    out: list[str] = []
    for r in rows:
        try:
            buff_cond_id = _safe_int(r["BuffConditionId"], 0)
        except Exception:
            try:
                buff_cond_id = _safe_int(r[3], 0)
            except Exception:
                buff_cond_id = 0

        if buff_cond_id > 0 and buff_cond_id in active_buff_ids:
            continue

        tmpl = (r["Tmpl"] or "").strip()
        if not tmpl:
            continue

        eb_id = int(r["EBId"])
        bt_id = int(r["TypeId"]) if r["TypeId"] is not None else 0

        if idx_sql:
            vrows = conn.execute(
                f"""
                SELECT {idx_sql} AS idx, {val_col} AS val
                FROM {var_table}
                WHERE EquipmentBonus_Id=?
                ORDER BY {idx_sql}
                """,
                (eb_id,)
            ).fetchall()

            vals: list[str] = []
            for vr in vrows:
                i = int(vr["idx"])
                if i >= len(vals):
                    vals.extend([""] * (i - len(vals) + 1))
                vals[i] = str(vr["val"])
        else:
            vals = [str(vr["val"]) for vr in conn.execute(
                f"SELECT {val_col} AS val FROM {var_table} WHERE EquipmentBonus_Id=? ORDER BY rowid",
                (eb_id,)
            ).fetchall()]

        mul_idxs = _mul_indices_for_bonus_type(bt_id)
        if mul_idxs and armor_bl != 1.0 and vals:
            for idx in mul_idxs:
                i = int(idx)

                if 0 <= i < len(vals):
                    vals[i] = _try_mul(vals[i], armor_bl)
                    continue

                if 1 <= i <= len(vals):
                    vals[i - 1] = _try_mul(vals[i - 1], armor_bl)

        try:
            line = tmpl.format(*vals)
        except Exception:
            line = tmpl

        line = _ensure_leading_plus(line)
        out.append(line)

    return out

class _PixCache(dict):
    def getpm(self, loader: Callable[[int], Optional[bytes]], image_id: Optional[int]):
        if not image_id:
            return None
        pm = self.get(image_id)
        if pm is None:
            data = loader(image_id)
            if data:
                pm = QPixmap()
                pm = pm if pm.loadFromData(data) else None
                if pm:
                    self[image_id] = pm
        return pm

# ---------- element badge (weapon) ----------
def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def weapon_element_badge_image_id(cards_window, weapon_item: Optional[dict], *, slot_key: Optional[str] = None) -> Optional[int]:
    """
    Возвращает Image_Id бейджа стихии (ToolTipImage_Id) для оружия, если в картах есть стихия.

    Берём самым надёжным путём: через CardsWindow.build_tooltip_cards_payload_for_item(),
    потому что там уже есть логика:
      - "это стихия" => Element_Id > 0
      - иконка => ToolTipImage_Id

    Возвращает:
      int Image_Id или None
    """
    if not weapon_item or cards_window is None:
        return None

    fn = getattr(cards_window, "build_tooltip_cards_payload_for_item", None)
    if not callable(fn):
        return None

    try:
        payload = fn(weapon_item, kind="weapon", slot_key=slot_key)
    except TypeError:
        # на случай если сигнатура без slot_key
        try:
            payload = fn(weapon_item, kind="weapon")
        except Exception:
            return None
    except Exception:
        return None

    # payload: List[Tuple[Optional[int], str, str]]
    # icon_id != None кладётся только для "элементных" карт
    for icon_id, _name, _desc in (payload or []):
        iid = _safe_int(icon_id, 0)
        if iid > 0:
            return iid

    return None


def compose_icon_with_badge(
    base_pm: Optional[QPixmap],
    badge_pm: Optional[QPixmap],
    out_size: QSize,
    *,
    badge_ratio: float = 0.42,   # доля от out_size (по меньшей стороне)
    pad_px: int = 1,             # отступ от края
    corner: str = "bl",          # "bl" | "br" | "tl" | "tr"
) -> Optional[QPixmap]:
    """
    Собирает итоговую иконку: base_pm + маленький badge_pm в углу.

    - out_size: размер итоговой иконки (например размер QLabel слота)
    - badge_ratio: 0.42 => бейдж ~42% от меньшей стороны
    - corner: где рисовать бейдж (по умолчанию bottom-left)
    """
    if out_size is None or out_size.isEmpty():
        return base_pm

    out = QPixmap(out_size)
    out.fill(Qt.transparent)

    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    # base
    if base_pm and not base_pm.isNull():
        scaled = base_pm.scaled(out_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        dst = QRect(0, 0, scaled.width(), scaled.height())
        dst.moveCenter(QRect(QPoint(0, 0), out_size).center())
        p.drawPixmap(dst, scaled)

    # badge
    if badge_pm and not badge_pm.isNull():
        side = max(8, int(min(out_size.width(), out_size.height()) * float(badge_ratio)))
        b = badge_pm.scaled(QSize(side, side), Qt.KeepAspectRatio, Qt.SmoothTransformation)

        x = pad_px
        y = pad_px

        if corner == "br":
            x = out_size.width() - b.width() - pad_px
            y = out_size.height() - b.height() - pad_px
        elif corner == "bl":
            x = pad_px
            y = out_size.height() - b.height() - pad_px
        elif corner == "tr":
            x = out_size.width() - b.width() - pad_px
            y = pad_px
        else:  # "tl"
            x = pad_px
            y = pad_px

        p.drawPixmap(QRect(x, y, b.width(), b.height()), b)

    p.end()
    return out

class _ActivateBonusToggle(QWidget):
    """
    Маленький квадратик с галочкой в правом верхнем углу слота.

    Появляется только если у экипированного предмета есть EquipmentBonus с Activate != NULL.
    Галочка управляет применением только тех EquipmentBonus, у которых Activate = 1 (см. characteristics_math.py).
    """

    BOX = 14
    PAD = 1

    def __init__(self, parent_widget: QWidget, slot_key: str, data, get_selected_item):
        super().__init__(parent_widget)
        self._slot_key = str(slot_key or "")
        self._data = data
        self._get_selected_item = get_selected_item

        self.setFixedSize(self.BOX, self.BOX)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Особенность предмета (вкл/выкл)")

        self._checked = False
        self._visible = False

        self.hide()
        try:
            parent_widget.installEventFilter(self)
        except Exception:
            pass

    def sync(self) -> None:
        """Синхронизировать видимость/галочку/позицию с текущим предметом в слоте."""
        owner = self.parentWidget()
        if owner is None:
            return

        try:
            it = self._get_selected_item(self._slot_key)
        except Exception:
            it = None

        if not isinstance(it, dict) or not it:
            self._visible = False
            self.hide()
            return

        eid = _safe_int(it.get("Id"), 0)

        # кэшируем флаг "есть ли бонусы с Activate != NULL" в самом item dict
        has_key = "_has_activatable_bonus"
        has = it.get(has_key, None)
        if has is None:
            has = False
            try:
                conn = getattr(self._data, "conn", None)
                if conn is not None and eid > 0:
                    row = conn.execute(
                        "SELECT 1 FROM EquipmentBonus WHERE Equipment_Id=? AND Activate IS NOT NULL LIMIT 1",
                        (int(eid),),
                    ).fetchone()
                    has = bool(row)
            except Exception:
                has = False
            try:
                it[has_key] = bool(has)
            except Exception:
                pass

        self._visible = bool(has)
        if not self._visible:
            self.hide()
            return

        self._checked = bool(it.get("_activate_checked", False))
        self._reposition()
        self.show()
        self.raise_()
        self.update()

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent

        if obj is self.parentWidget():
            et = ev.type()
            # на перерисовках/ресайзах подгоняем позицию и актуальность
            if et in (QEvent.Paint, QEvent.Resize, QEvent.Move, QEvent.Show):
                try:
                    self.sync()
                except Exception:
                    pass
        return False

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)

        self._pressed_inside = True
        ev.accept()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(ev)

        owner = self.parentWidget()
        armed = bool(getattr(self, "_pressed_inside", False))
        self._pressed_inside = False

        try:
            inside = self.rect().contains(ev.position().toPoint())
        except Exception:
            try:
                inside = self.rect().contains(ev.pos())
            except Exception:
                inside = False

        if not armed or not inside or owner is None:
            ev.accept()
            return

        try:
            it = self._get_selected_item(self._slot_key)
        except Exception:
            it = None

        if not isinstance(it, dict) or not it:
            ev.accept()
            return

        new_checked = not bool(it.get("_activate_checked", False))
        it["_activate_checked"] = bool(new_checked)
        self._checked = bool(new_checked)

        try:
            fn = getattr(owner, "refresh_stats_panel", None)
            if callable(fn):
                fn()
        except Exception:
            pass

        try:
            fn = getattr(owner, "_update_board_pixmap", None)
            if callable(fn):
                fn()
        except Exception:
            pass

        self.update()
        ev.accept()

    def paintEvent(self, ev):
        if not self._visible:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # фон квадратика
        r = self.rect().adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
        p.setPen(QPen(QColor(220, 220, 220, 230), 1))
        p.setBrush(QColor(0, 0, 0, 255))
        p.drawRoundedRect(r, 2, 2)

        # галочка
        if self._checked:
            p.setPen(QPen(QColor(245, 245, 245, 240), 2))
            x1 = r.left() + 3
            y1 = r.center().y()
            x2 = r.left() + 6
            y2 = r.bottom() - 3
            x3 = r.right() - 3
            y3 = r.top() + 3
            p.drawLine(x1, y1, x2, y2)
            p.drawLine(x2, y2, x3, y3)

        p.end()

    def _reposition(self) -> None:
        owner = self.parentWidget()
        if owner is None:
            return

        rect = None

        # 1) пробуем через зоны (DB-driven) — наиболее точно к слоту
        try:
            zr = getattr(owner, "_zone_rect", None)
            if callable(zr):
                rect = zr(self._slot_key)
        except Exception:
            rect = None

        # 2) fallback: через slot_icons (если есть)
        if rect is None:
            try:
                slot_icons = getattr(owner, "_slot_icons", None) or {}
                lbl = slot_icons.get(self._slot_key)
                if lbl is not None and hasattr(lbl, "size") and hasattr(lbl, "mapTo"):
                    tl = lbl.mapTo(owner, QPoint(0, 0))
                    rect = QRect(tl, lbl.size())
            except Exception:
                rect = None

        if rect is None:
            rect = owner.rect()

        x = int(rect.right() - self.width() - 7)
        y = int(rect.top() + 7)
        self.move(x, y)

# ---------- карточка ----------
class _EquipItemCard(QWidget):
    """Карточка: иконка, заголовок, базовый стат, справа — бокс строк бонусов."""
    clicked = Signal(dict)

    def __init__(self, controller, menu, item: dict, preload_lines: list[str] | None = None):
        super().__init__(menu)
        self.setObjectName("equipCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.item = item
        self.ctrl = controller

        self.setStyleSheet("""
            #equipCard { background: transparent; border-radius: 6px; }
            #equipCard:hover { background: rgba(255,255,255,0.08); }
        """)

        lay = QGridLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(2)
        lay.setColumnStretch(0, 0)
        lay.setColumnStretch(1, 1)
        lay.setColumnStretch(2, 0)

        # иконка
        self.icon_lbl = QLabel(self)
        self.icon_lbl.setFixedSize(40, 40)
        self.icon_lbl.setScaledContents(True)
        self.icon_lbl.setStyleSheet("background: transparent;")
        img_id = item.get("Icon_Image_Id") or item.get("Image_Id")
        pm = self.ctrl._pm_cached(img_id)
        if pm:
            self.icon_lbl.setPixmap(pm)
        lay.addWidget(self.icon_lbl, 0, 0, 3, 1)

        # заголовок
        title = f"{item['Name']}  —  ур. {item.get('Level', 0)}"
        if getattr(self.ctrl, "_add_weapon_tags", False):
            tags = []

            # 2H если IsSingleHandWeapon == 0
            is_single = item.get("IsSingleHandWeapon")
            try:
                if is_single is not None and int(is_single) == 0:
                    tags.append("2H")
            except Exception:
                pass

            if tags:
                title += "  [" + " • ".join(tags) + "]"

        name_lbl = QLabel(title, self)
        name_lbl.setStyleSheet("color:#fff; font-weight:600; background: transparent;")
        lay.addWidget(name_lbl, 0, 1, 1, 1)

        # базовый стат
        stat_val = item.get("Attack") or item.get("Defense") or 0
        stat_lbl = QLabel(
            f"Атака: {item['Attack']}" if item.get("Attack") else f"Защита: {stat_val}",
            self
        )
        stat_lbl.setStyleSheet("color:#d8d8d8; background: transparent;")
        lay.addWidget(stat_lbl, 1, 1, 1, 1)

        # правый бокс бонусов
        right_box = QFrame(self)
        right_box.setObjectName("statsBox")
        right_box.setMinimumWidth(260)
        right_box.setMaximumWidth(360)
        right_v = QVBoxLayout(right_box)
        right_v.setContentsMargins(10, 8, 10, 8)
        right_v.setSpacing(6)
        right_v.setAlignment(Qt.AlignTop | Qt.AlignRight)
        right_box.setStyleSheet("""
            QFrame#statsBox {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 10px;
            }
        """)
        lay.addWidget(right_box, 0, 2, 3, 1)

        for line in (preload_lines or []):
            lbl = QLabel(line, right_box)
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setStyleSheet("color:#cfcfc0; padding:0; background: transparent;")
            right_v.addWidget(lbl)
        right_v.addStretch(1)

        # дочерние виджеты не перехватывают мышь
        for w in self.findChildren(QWidget):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)

        self._pressed_inside = True
        ev.accept()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(ev)

        armed = bool(getattr(self, "_pressed_inside", False))
        self._pressed_inside = False

        try:
            inside = self.rect().contains(ev.position().toPoint())
        except Exception:
            try:
                inside = self.rect().contains(ev.pos())
            except Exception:
                inside = False

        if armed and inside:
            try:
                self.clicked.emit(self.item)
            finally:
                ev.accept()
                return

        ev.accept()


# ---------- базовый контроллер ----------
class _BaseController:
    def __init__(
            self,
            parent_widget: QWidget,
            data: DataAccess,
            on_pick,
            on_clear,
            slot_key: str,
            type_name: str,
            get_class_id=None,
            get_gender_id=None,
            get_level=None,
            get_selected_item=None,
    ):
        self.parent = parent_widget
        self.data = data

        self.SLOT_KEY = str(slot_key or "")
        self.SLOT_ID = 0
        self.TYPE_NAME = str(type_name or "")

        self.get_class_id = get_class_id
        self.get_gender_id = get_gender_id
        self.get_level = get_level

        self.get_selected_item = get_selected_item
        self.on_pick = on_pick
        self.on_clear = on_clear

        # общий кэш пиксмапов (разделяем между всеми контроллерами на одном parent)
        pc = getattr(self.parent, "_wob_pix_cache", None)
        if not isinstance(pc, _PixCache):
            pc = _PixCache()
            try:
                setattr(self.parent, "_wob_pix_cache", pc)
            except Exception:
                pass
        self._pix_cache: _PixCache = pc

        self._menu: Optional[QMenu] = None
        self._menu_is_open = False

        # Квадратик "особенности" (Activate != NULL) рисуем прямо на главном окне,
        # чтобы его было видно после экипировки.
        self._activate_toggle: Optional[_ActivateBonusToggle] = None
        try:
            self._activate_toggle = _ActivateBonusToggle(self.parent, self.SLOT_KEY, self.data, self.get_selected_item)
            QTimer.singleShot(0, self._activate_toggle.sync)
        except Exception:
            self._activate_toggle = None

    def _pm_cached(self, image_id: Optional[int]):
        try:
            iid = int(image_id) if image_id is not None else None
        except Exception:
            iid = None
        return self._pix_cache.getpm(self.data.get_image_bytes, iid)

    def show_context_menu(self, global_pos: QPoint):
        m = QMenu(self.parent)
        m.setStyleSheet(
            "QMenu{background:#1b1b1b;border:1px solid #666;border-radius:6px;}"
            "QMenu::item{padding:6px 10px;color:#eee;}"
        )

        a_clear = m.addAction("Снять предмет")

        def _do_clear():
            try:
                self.on_clear(self.SLOT_KEY)
            finally:
                try:
                    if self._activate_toggle is not None:
                        QTimer.singleShot(0, self._activate_toggle.sync)
                except Exception:
                    pass

        a_clear.triggered.connect(_do_clear)
        m.popup(global_pos)
        return m

    def show_menu(self, global_pos: QPoint):
        """
        Меню выбора предмета для main_window через ChooseItemMenu (PNG подложка item_choose.png).
        ВАЖНО:
          - QMenu делаем полностью прозрачным (иначе серые углы от его фона).
          - Не показываем "анкету" по наведению (без hover-callbacks).
        """
        items = self._fetch_items()

        m = QMenu(self.parent)

        # ---- КЛЮЧЕВОЕ: убираем фон/рамки/тени QMenu, чтобы PNG с альфой выглядел нормально ----
        try:
            m.setAttribute(Qt.WA_TranslucentBackground, True)
            m.setAttribute(Qt.WA_NoSystemBackground, True)
            m.setAutoFillBackground(False)
            m.setWindowFlag(Qt.FramelessWindowHint, True)
            m.setWindowFlag(Qt.NoDropShadowWindowHint, True)
        except Exception:
            pass

        m.setStyleSheet(
            "QMenu{background: transparent; border: none; padding:0px; margin:0px;}"
            "QMenu::item{background: transparent; padding:0px; margin:0px;}"
            "QMenu::separator{height:0px; margin:0px; padding:0px;}"
        )

        # импорт внутри, чтобы не ловить циклические импорты
        try:
            from .choose_menu_all import ChooseItemMenu, ItemChooseConfig  # type: ignore
        except Exception:
            # fallback: старое меню (хотя бы не падаем)
            m.setStyleSheet(
                "QMenu{background:#1b1b1b;border:1px solid #666;border-radius:6px;}"
                "QMenu::item{padding:6px 10px;color:#eee;}"
            )
            if not items:
                a = m.addAction("(нет подходящих предметов)")
                a.setEnabled(False)
            else:
                for it in items:
                    name = (it.get("Name") if isinstance(it, dict) else None) or "(без названия)"
                    act = m.addAction(str(name))
                    act.triggered.connect(lambda _=False, _it=it: self._apply_pick(dict(_it)))
            m.popup(global_pos)
            return m

        # --- собираем entries под ChooseItemMenu ---
        entries: List[Dict[str, Any]] = []
        for it in (items or []):
            if not isinstance(it, dict) or not it:
                continue

            try:
                equip_id = int(it.get("Id") or 0)
            except Exception:
                equip_id = 0

            # бонусы как в старом меню (через БД)
            try:
                lines = self._get_bonus_lines(equip_id) if equip_id > 0 else []
            except Exception:
                lines = []

            # иконка
            img_id = it.get("Icon_Image_Id") or it.get("Image_Id")
            pm = self._pm_cached(img_id)

            entries.append({
                "item": dict(it),
                "bonuses": list(lines or []),
                "icon_pm": pm,
            })

        root = ChooseItemMenu(m, config=ItemChooseConfig())

        # на всякий случай делаем прозрачными внутренности (иногда viewport даёт серый фон)
        try:
            root.setAutoFillBackground(False)
            root.setStyleSheet("background: transparent;")
            root._area.setStyleSheet("background: transparent;")  # type: ignore[attr-defined]
            root._area.viewport().setStyleSheet("background: transparent;")  # type: ignore[attr-defined]
            root._cont.setStyleSheet("background: transparent;")  # type: ignore[attr-defined]
        except Exception:
            pass

        def _do_pick(item_dict: Dict[str, Any]) -> None:
            try:
                self._apply_pick(dict(item_dict or {}))
            finally:
                try:
                    m.close()
                except Exception:
                    pass

        # ВАЖНО: hover-callbacks НЕ передаём -> анкета не вызывается по наведению
        root.set_entries(
            entries=entries,
            on_pick=_do_pick,
            on_hover_enter=None,
            on_hover_leave=None,
            focus_search=True,
        )

        wa = QWidgetAction(m)
        wa.setDefaultWidget(root)
        m.addAction(wa)

        m.popup(global_pos)
        return m

    # заглушки
    def _fetch_items(self) -> list[dict]:
        return []

    def _get_bonus_lines(self, equip_id: int) -> list[str]:
        lvl = self.get_level() if callable(self.get_level) else self.get_level
        try:
            lvl_i = int(lvl) if lvl is not None else None
        except Exception:
            lvl_i = None
        return _render_bonus_lines(self.data.conn, int(equip_id), char_level=lvl_i)

    def _apply_pick(self, item: dict):
        raise NotImplementedError

# ---------- обычные слоты ----------
class EquipmentController(_BaseController):
    def __init__(self, parent_widget, data, on_pick, on_clear, slot_key: str, type_id: int, type_name: str,
                 get_class_id=None, get_gender_id=None, get_level=None, get_selected_item=None):
        super().__init__(parent_widget, data, on_pick, on_clear, slot_key, type_name,
                         get_class_id, get_gender_id, get_level, get_selected_item)
        self.TYPE_ID = int(type_id)

    def _fetch_items(self) -> list[dict]:
        conn = self.data.conn
        image_col, icon_col = _image_col(conn), _icon_col(conn)

        class_id = self.get_class_id() if callable(self.get_class_id) else self.get_class_id
        gender_id = self.get_gender_id() if callable(self.get_gender_id) else self.get_gender_id
        level = self.get_level() if callable(self.get_level) else self.get_level

        allowed_class_ids = None
        if class_id is not None:
            allowed_class_ids = {int(class_id)}
            for donor, rec in DONOR_MAP.items():
                if int(class_id) in rec:
                    allowed_class_ids.add(donor)

        select_cols = (
            f"e.Id, e.Name, e.Level, e.Attack, e.Defense, e.{image_col} AS ImageId, e.Gender_Id"
            + (f", e.{icon_col} AS IconImageId" if icon_col else "")
        )
        join_ec = "LEFT JOIN EquipmentCondition ec ON ec.Equipment_Id = e.Id"

        where, params = [f"e.Type_Id = {int(self.TYPE_ID)}"], []
        if level is not None:
            where.append("e.Level <= ?")
            params.append(int(level))
        if allowed_class_ids is not None:
            ph = ",".join("?" for _ in allowed_class_ids)
            where.append(f"(ec.Class_Id IS NULL OR ec.Class_Id IN ({ph}))")
            params.extend(sorted(int(x) for x in allowed_class_ids))
        if gender_id is not None:
            where.append("(e.Gender_Id IS NULL OR e.Gender_Id = ?)")
            params.append(int(gender_id))

        rows = conn.execute(
            f"""
            SELECT {select_cols}
            FROM Equipment e
            {join_ec}
            WHERE {" AND ".join(where)}
            GROUP BY e.Id
            ORDER BY e.Level DESC, e.Name COLLATE NOCASE
            """,
            tuple(params)
        ).fetchall()

        items: list[dict] = []
        for r in rows:
            items.append({
                "Id": int(r["Id"]),
                "Name": r["Name"],
                "Level": int(r["Level"]) if r["Level"] is not None else 0,
                "Attack": int(r["Attack"]) if r["Attack"] is not None else 0,
                "Defense": int(r["Defense"]) if r["Defense"] is not None else 0,
                "Image_Id": int(r["ImageId"]) if r["ImageId"] is not None else None,
                "Icon_Image_Id": (int(r["IconImageId"]) if (icon_col and r["IconImageId"] is not None) else None),
                "Gender_Id": (int(r["Gender_Id"]) if r["Gender_Id"] is not None else None),
            })
        return items

    def _apply_pick(self, item: dict):
        payload = {
            "Id": int(item["Id"]),
            "Name": item["Name"],
            "Level": int(item.get("Level") or 0),
            "Attack": int(item.get("Attack") or 0),
            "Defense": int(item.get("Defense") or 0),
            "Type_Id": self.TYPE_ID,
            "TypeName": self.TYPE_NAME,
            "Icon_Image_Id": item.get("Icon_Image_Id") or item.get("Image_Id"),
            "Image_Id": item.get("Image_Id"),
            "Gender_Id": item.get("Gender_Id"),
            # флаг "галочки" (по умолчанию выключено)
            "_activate_checked": False,
        }
        self.on_pick(self.SLOT_KEY, payload)

        # обновим квадратик-галочку на главном слоте
        try:
            if self._activate_toggle is not None:
                QTimer.singleShot(0, self._activate_toggle.sync)
        except Exception:
            pass


# ---------- weapon/offhand/spear ----------
class WeaponOffhandController(_BaseController):
    """
    DB-driven контроллер weapon/offhand/spear:
    - фильтры: уровень, пол, class_id + donor map через EquipmentCondition
    - типы слота: берём по EquipmentType.Slot_Id (никакого хардкода)
    - fallback для offhand: если по БД для Slot_Id=7 ничего нет -> показываем Slot_Id=21 (weapon)
      и при выборе кладём в weapon-слот.
    """
    def __init__(self, parent_widget, data, on_pick, on_clear, slot_key: str, slot_id: int, type_name: str,
                 get_class_id=None, get_gender_id=None, get_level=None, get_selected_item=None):
        super().__init__(parent_widget, data, on_pick, on_clear, slot_key, type_name,
                         get_class_id, get_gender_id, get_level, get_selected_item)
        self.SLOT_ID = int(slot_id)
        self._add_weapon_tags = True

    def _is_two_handed_equipped(self) -> bool:
        w = self.get_selected_item("weapon") if callable(self.get_selected_item) else None
        if not w:
            return False
        is_single = w.get("IsSingleHandWeapon")
        if is_single is None:
            return False
        try:
            return int(is_single) == 0  # 0 => 2H
        except Exception:
            return False

    def enforce_class_rules(self):
        """
        Правило:
        - если weapon двуручное (IsSingleHandWeapon == 0) -> offhand запрещён.
        """
        try:
            w = self.get_selected_item("weapon") if callable(self.get_selected_item) else None
            oh = self.get_selected_item("offhand") if callable(self.get_selected_item) else None
            if not w or not oh:
                return

            is_single = w.get("IsSingleHandWeapon")
            if is_single is None:
                return

            if int(is_single) == 0:
                self.on_clear("offhand")
        except Exception:
            pass

    def show_menu(self, global_pos: QPoint):
        return super().show_menu(global_pos)

    def _apply_pick(self, item: dict):
        target = item.get("_pick_target") or self.SLOT_KEY

        def _sync_toggle_for_slot(slot_key: str) -> None:
            try:
                if slot_key == self.SLOT_KEY:
                    if self._activate_toggle is not None:
                        QTimer.singleShot(0, self._activate_toggle.sync)
                    return

                ctrls = getattr(self.parent, "_equip_ctrls", None)
                if isinstance(ctrls, dict):
                    other = ctrls.get(str(slot_key))
                    tog = getattr(other, "_activate_toggle", None)
                    if tog is not None:
                        QTimer.singleShot(0, tog.sync)
            except Exception:
                pass

        # Если реально выбрали предмет в offhand, а сейчас в weapon стоит 2H —
        # снимаем weapon ТОЛЬКО в момент подтверждённого выбора.
        try:
            if str(target) == "offhand":
                w = self.get_selected_item("weapon") if callable(self.get_selected_item) else None
                if isinstance(w, dict):
                    is_single = w.get("IsSingleHandWeapon")
                    if is_single is not None and int(is_single) == 0:
                        self.on_clear("weapon")
                        _sync_toggle_for_slot("weapon")
        except Exception:
            pass

        # Если ставим двуручное в weapon — offhand очищаем тоже только при подтверждённом выборе.
        try:
            if str(target) == "weapon":
                is_single = item.get("IsSingleHandWeapon")
                if is_single is not None and int(is_single) == 0:
                    self.on_clear("offhand")
                    _sync_toggle_for_slot("offhand")
        except Exception:
            pass

        self.on_pick(target, {
            "Id": int(item["Id"]),
            "Name": item["Name"],
            "Level": int(item.get("Level") or 0),
            "Attack": int(item.get("Attack") or 0),
            "Defense": int(item.get("Defense") or 0),
            "Type_Id": int(item.get("Type_Id") or 0),
            "TypeName": self.TYPE_NAME,
            "Icon_Image_Id": item.get("Icon_Image_Id") or item.get("Image_Id"),
            "Image_Id": item.get("Image_Id"),
            "Gender_Id": item.get("Gender_Id"),
            "IsSingleHandWeapon": item.get("IsSingleHandWeapon"),
            "IsMeleeWeapon": item.get("IsMeleeWeapon"),
            "_activate_checked": False,
        })

        _sync_toggle_for_slot(str(target))

    def _fetch_items(self) -> list[dict]:
        conn = self.data.conn

        image_col = _image_col(conn)
        icon_col = _icon_col(conn)

        has_et_single = _has_col(conn, "EquipmentType", "IsSingleHandWeapon")
        has_et_melee = _has_col(conn, "EquipmentType", "IsMeleeWeapon")

        gender_id = self.get_gender_id() if callable(self.get_gender_id) else self.get_gender_id
        level = self.get_level() if callable(self.get_level) else self.get_level
        class_id = self.get_class_id() if callable(self.get_class_id) else self.get_class_id

        allow_extra = _class_allow_extra_weapon(conn, class_id)
        allowed_ids = _allowed_class_ids(conn, class_id)

        # ---------------- base filters (общие для всех запросов) ----------------
        base_where: list[str] = []
        base_params: list[int] = []

        if level is not None:
            base_where.append("e.Level <= ?")
            base_params.append(int(level))

        if gender_id is not None:
            base_where.append("(e.Gender_Id IS NULL OR e.Gender_Id = ?)")
            base_params.append(int(gender_id))

        # фильтр по классу: EquipmentCondition + EquipmentTypeCondition
        if allowed_ids is not None:
            allowed = sorted(int(x) for x in allowed_ids)
            ph = ",".join("?" for _ in allowed)

            # EquipmentCondition:
            base_where.append(
                f"""(
                    NOT EXISTS (SELECT 1 FROM EquipmentCondition ec2 WHERE ec2.Equipment_Id = e.Id)
                    OR EXISTS (SELECT 1 FROM EquipmentCondition ec2
                               WHERE ec2.Equipment_Id = e.Id AND ec2.Class_Id IN ({ph}))
                )"""
            )
            base_params.extend(allowed)

            # EquipmentTypeCondition:
            base_where.append(
                f"""(
                    NOT EXISTS (SELECT 1 FROM EquipmentTypeCondition tc2 WHERE tc2.Type_Id = e.Type_Id)
                    OR EXISTS (SELECT 1 FROM EquipmentTypeCondition tc2
                               WHERE tc2.Type_Id = e.Type_Id AND tc2.Class_Id IN ({ph}))
                )"""
            )
            base_params.extend(allowed)

        # ---------------- helpers ----------------
        single_expr = "et.IsSingleHandWeapon AS SingleRaw" if has_et_single else "NULL AS SingleRaw"
        melee_expr = "et.IsMeleeWeapon AS MeleeRaw" if has_et_melee else "NULL AS MeleeRaw"

        select_cols = [
            "e.Id", "e.Name", "e.Level", "e.Attack", "e.Defense",
            "e.Type_Id AS TypeId",
            f"e.{image_col} AS ImageId",
            "e.Gender_Id",
            (f"e.{icon_col} AS IconImageId" if icon_col else "NULL AS IconImageId"),
            single_expr,
            melee_expr,
        ]

        def _query_by_slot(slot_id: int, extra_where: list[str] | None = None, extra_params: list[int] | None = None) -> \
        list[dict]:
            w = ["et.Slot_Id = ?"]
            p: list[int] = [int(slot_id)]

            if base_where:
                w.extend(base_where)
                p.extend(base_params)

            if extra_where:
                w.extend(extra_where)
            if extra_params:
                p.extend(extra_params)

            rows = conn.execute(
                f"""
                SELECT {", ".join(select_cols)}
                FROM Equipment e
                JOIN EquipmentType et ON et.Id = e.Type_Id
                WHERE {" AND ".join(w)}
                """,
                tuple(p)
            ).fetchall()

            out: list[dict] = []
            for r in rows:
                out.append({
                    "Id": int(r["Id"]),
                    "Name": r["Name"],
                    "Level": int(r["Level"]) if r["Level"] is not None else 0,
                    "Attack": int(r["Attack"]) if r["Attack"] is not None else 0,
                    "Defense": int(r["Defense"]) if r["Defense"] is not None else 0,

                    "Type_Id": int(r["TypeId"]),
                    "Image_Id": int(r["ImageId"]) if r["ImageId"] is not None else None,
                    "Icon_Image_Id": (int(r["IconImageId"]) if r["IconImageId"] is not None else None),
                    "Gender_Id": (int(r["Gender_Id"]) if r["Gender_Id"] is not None else None),

                    "IsSingleHandWeapon": (int(r["SingleRaw"]) if r["SingleRaw"] is not None else None),
                    "IsMeleeWeapon": (int(r["MeleeRaw"]) if r["MeleeRaw"] is not None else None),
                })
            return out

        def _slot_has_any(slot_id: int) -> bool:
            w = ["et.Slot_Id = ?"]
            p: list[int] = [int(slot_id)]
            if base_where:
                w.extend(base_where)
                p.extend(base_params)

            row = conn.execute(
                f"""
                SELECT 1
                FROM Equipment e
                JOIN EquipmentType et ON et.Id = e.Type_Id
                WHERE {" AND ".join(w)}
                LIMIT 1
                """,
                tuple(p)
            ).fetchone()
            return bool(row)

        # ---------------- main logic ----------------
        # weapon / spear — как обычно
        if self.SLOT_KEY == "weapon":
            items = _query_by_slot(int(self.SLOT_ID))
            for it in items:
                it["_pick_target"] = "weapon"
            # сортировка как раньше
            items.sort(key=lambda x: (-int(x.get("Level") or 0), (x.get("Name") or "").casefold()))
            return items

        if self.SLOT_KEY == "spear":
            if not _slot_has_any(int(self.SLOT_ID)):
                return []
            items = _query_by_slot(int(self.SLOT_ID))
            for it in items:
                it["_pick_target"] = "spear"
            items.sort(key=lambda x: (-int(x.get("Level") or 0), (x.get("Name") or "").casefold()))
            return items

        # ---------------- OFFHAND ----------------
        # Режим "доп оружие": показываем (slot 7 items) + (slot 21 1H weapons), и ВСЁ кладём в offhand
        if self.SLOT_KEY == "offhand" and allow_extra:
            # 1) обычные предметы слота 7
            offhand_items = _query_by_slot(int(self.SLOT_ID))

            # 2) оружие слота 21, но только 1H
            weapon_items: list[dict] = []
            if has_et_single:
                weapon_items = _query_by_slot(
                    21,
                    extra_where=["et.IsSingleHandWeapon = 1"],
                    extra_params=[]
                )

            # merge без дублей
            merged: dict[int, dict] = {}
            for it in offhand_items:
                merged[int(it["Id"])] = it
            for it in weapon_items:
                merged[int(it["Id"])] = it

            items = list(merged.values())
            for it in items:
                it["_pick_target"] = "offhand"

            items.sort(key=lambda x: (-int(x.get("Level") or 0), (x.get("Name") or "").casefold()))
            return items

        # Обычный режим offhand:
        # - если в slot 7 есть предметы -> показываем их и кладём в offhand
        # - если пусто -> fallback на slot 21 и кладём в weapon (как у тебя было)
        if self.SLOT_KEY == "offhand":
            if _slot_has_any(int(self.SLOT_ID)):
                items = _query_by_slot(int(self.SLOT_ID))
                for it in items:
                    it["_pick_target"] = "offhand"
            else:
                items = _query_by_slot(21)
                for it in items:
                    it["_pick_target"] = "weapon"

            items.sort(key=lambda x: (-int(x.get("Level") or 0), (x.get("Name") or "").casefold()))
            return items

        return []


# ---------- навешивание обработчиков ----------
def wire_slot_mouse_handlers(widget, controller):
    """ЛКМ/ПКМ срабатывают только на отпускании кнопки внутри того же виджета."""
    from PySide6.QtCore import QObject, QEvent

    class _MouseFilter(QObject):
        def __init__(self, owner_widget, owner_controller):
            super().__init__(owner_widget)
            self._widget = owner_widget
            self._controller = owner_controller
            self._armed_button = Qt.NoButton

        def _local_pos(self, ev):
            try:
                return ev.position().toPoint()
            except Exception:
                try:
                    return ev.pos()
                except Exception:
                    return QPoint(-1, -1)

        def _global_pos(self, ev):
            try:
                return ev.globalPosition().toPoint()
            except Exception:
                try:
                    return ev.globalPos()
                except Exception:
                    return self._widget.mapToGlobal(QPoint(0, 0))

        def _inside(self, ev) -> bool:
            lp = self._local_pos(ev)
            return self._widget.rect().contains(lp)

        def eventFilter(self, obj, ev):
            et = ev.type()

            if et == QEvent.MouseButtonPress:
                btn = ev.button()
                if btn in (Qt.LeftButton, Qt.RightButton) and self._inside(ev):
                    self._armed_button = btn
                    return True
                self._armed_button = Qt.NoButton
                return False

            if et == QEvent.MouseMove:
                if self._armed_button != Qt.NoButton:
                    # если увели курсор за пределы виджета — снимаем arm
                    if not self._inside(ev):
                        self._armed_button = Qt.NoButton
                return False

            if et == QEvent.MouseButtonRelease:
                btn = ev.button()
                armed = self._armed_button
                self._armed_button = Qt.NoButton

                if btn == Qt.LeftButton and armed == Qt.LeftButton and self._inside(ev):
                    self._controller.show_menu(self._global_pos(ev))
                    return True

                if btn == Qt.RightButton and armed == Qt.RightButton and self._inside(ev):
                    self._controller.show_context_menu(self._global_pos(ev))
                    return True

                return False

            if et == QEvent.Leave:
                if self._armed_button != Qt.NoButton:
                    self._armed_button = Qt.NoButton
                return False

            return False

    f = _MouseFilter(widget, controller)
    widget.installEventFilter(f)
    if not hasattr(widget, "_wob_filters"):
        widget._wob_filters = []
    widget._wob_filters.append(f)

def _bind_to(self, widget):
    wire_slot_mouse_handlers(widget, self)

EquipmentController.bind_to = _bind_to
WeaponOffhandController.bind_to = _bind_to


# ---------- фабрики ----------
def make_equipment_controllers(parent, data, on_pick, on_clear,
                               get_class_id=None, get_gender_id=None, get_level=None, get_selected_item=None):
    mk = lambda key, tid, tname: EquipmentController(
        parent, data, on_pick, on_clear, key, tid, tname,
        get_class_id, get_gender_id, get_level, get_selected_item=get_selected_item
    )
    return {
        "head": mk("head", 1, "Головной убор"),
        "mask": mk("mask", 2, "Маска"),
        "armor": mk("armor", 3, "Броня"),
        "gloves": mk("gloves", 4, "Перчатки"),
        "legs": mk("legs", 5, "Штаны"),
        "boots": mk("boots", 6, "Ботинки"),
        "ornament": mk("ornament", 13, "Украшение"),
        "amulet": mk("amulet", 12, "Амулет"),
        "ring1": mk("ring1", 11, "Кольцо (1)"),
        "ring2": mk("ring2", 11, "Кольцо (2)"),
        "totem": mk("totem", 10, "Тотем"),
        "artifact": mk("artifact", 9, "Артефакт"),
    }

def make_weapon_offhand_controllers(parent, data, on_pick, on_clear,
                                    get_class_id=None, get_gender_id=None, get_level=None,
                                    get_selected_item=None):
    mk = lambda key, sid, tname: WeaponOffhandController(
        parent, data, on_pick, on_clear, key, sid, tname,
        get_class_id, get_gender_id, get_level,
        get_selected_item
    )
    return (
        mk("weapon", 21, "Оружие"),
        mk("offhand", 7, "Левая рука"),
        mk("spear", 22, "Копьё"),
    )
