# equipment_info_window.py (compact/optimized)
from __future__ import annotations
from typing import Callable, Iterable, Optional, Sequence, Tuple, Dict, List

from PySide6.QtCore import Qt, QPoint, QSize, QRect, QTimer, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QPixmap, QFont, QColor, QPainter, QCursor
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
    QSpacerItem, QSizePolicy, QGraphicsDropShadowEffect, QApplication, QSpinBox, QComboBox, QLineEdit
)

import html
# единый рендер бонусов из БД (один источник истины)
from .weapon_equipment_button import _render_bonus_lines  # noqa

# -------- константы --------
TYPE_CLASS_THRESHOLDS: Dict[int, Tuple[Optional[int], int]] = {
    1:(26,46), 2:(22,46), 3:(27,49), 4:(24,49), 5:(27,49), 6:(24,49),
    7:(25,46), 8:(26,48), 9:(27,43), 10:(25,50), 11:(27,46), 12:(22,48),
    21:(25,48), 22:(26,49), 23:(22,48), 24:(26,48), 25:(24,48), 26:(26,48),
    27:(25,48), 28:(25,48), 29:(26,48), 30:(27,47), 31:(6,47), 32:(None,47),
    33:(25,48), 34:(24,49), 35:(25,48), 36:(24,49),
}
STAMP_COLORS = {"green":"#32CD32","blue":"#4169E1","purple":"#8A2BE2","orange":"#FF9600"}
DEFAULT_STAMP_COLOR = "#ffd98a"
_SEP = "#ffd98a"  # разделитель
CARD_ICON_W = 16
CARD_ICON_H = 16
BUFF_NAME_COLOR = "#00d183"  # чуть более жёлтый для "Name:"


def _bonus_template_col_local(conn) -> str:
    """
    Возвращает SQL-фрагмент колонки с шаблоном BonusType (в кавычках), максимально устойчиво.
    """
    try:
        cols = [r[1] for r in conn.execute('PRAGMA table_info("BonusType")').fetchall()]
    except Exception:
        cols = []

    if not cols:
        return '"Template"'

    # map lower -> original
    m = {str(c).lower(): str(c) for c in cols}

    preferred = [
        "templateru", "template_ru", "template_ru_ru", "template_rus", "template_ru1",
        "template", "tooltiptemplate", "tooltiptmpl",
    ]
    for cand in preferred:
        if cand in m:
            return f'"{m[cand]}"'

    # fallback: любая колонка содержащая "template"
    for c in cols:
        if "template" in str(c).lower():
            return f'"{c}"'

    return f'"{cols[0]}"'


def _armor_bl_for_level(level: Optional[int]) -> float:
    """
    armorBL = 10040 * e^(0.05 * lvl) / e^(0.05 * 60)
    """
    import math

    lvl = int(level) if level is not None else None

    if lvl is None:
        return 1.0

    return 10040 * math.pow(2.718281828459045, 0.05 * level) / math.pow(2.718281828459045, 0.05 * 60)


# кеш для MulFormula=16: (id(conn), bonus_type_id) -> set(indices)
_MUL16_CACHE: dict[tuple[int, int], set[int]] = {}


def _render_bonus_lines_local(conn, equip_id: int, char_level: Optional[int] = None) -> list[str]:
    tmpl_col = _bonus_template_col_local(conn)

    # --- таблица переменных бонуса ---
    var_table = "EquipmentBonusVariable"
    try:
        var_cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{var_table}")').fetchall()]
    except Exception:
        return []

    var_cols_l = {str(c).lower(): str(c) for c in var_cols}
    # index column
    idx_col = None
    for cand in ("varindex", "index"):
        if cand in var_cols_l:
            idx_col = var_cols_l[cand]
            break
    if not idx_col:
        return []

    # value column
    val_col = None
    for cand in ("value",):
        if cand in var_cols_l:
            val_col = var_cols_l[cand]
            break
    if not val_col:
        # fallback: первая “не служебная” колонка
        for c in var_cols:
            cl = str(c).lower()
            if cl not in ("id", "equipmentbonus_id", "varindex", "index"):
                val_col = str(c)
                break
    if not val_col:
        return []

    armor_bl = _armor_bl_for_level(char_level)

    # --- MulFormula=16 индексы для BonusType ---
    def _mul16_indices_for_bonus_type(bonus_type_id: int) -> set[int]:
        key = (id(conn), int(bonus_type_id))
        if key in _MUL16_CACHE:
            return _MUL16_CACHE[key]

        # выясняем колонки BonusTypeVariable
        try:
            cols = [r[1] for r in conn.execute('PRAGMA table_info("BonusTypeVariable")').fetchall()]
        except Exception:
            _MUL16_CACHE[key] = set()
            return _MUL16_CACHE[key]

        cols_l = {str(c).lower(): str(c) for c in cols}
        need = ("bonustype_id", "mulformula_id")
        if not all(n in cols_l for n in need):
            _MUL16_CACHE[key] = set()
            return _MUL16_CACHE[key]

        btv_idx_col = None
        for cand in ("index", "varindex"):
            if cand in cols_l:
                btv_idx_col = cols_l[cand]
                break
        if not btv_idx_col:
            _MUL16_CACHE[key] = set()
            return _MUL16_CACHE[key]

        try:
            rows = conn.execute(
                f'''
                SELECT "{btv_idx_col}" AS idx
                FROM "BonusTypeVariable"
                WHERE "BonusType_Id" = ? AND "MulFormula_Id" = 16
                ''',
                (int(bonus_type_id),)
            ).fetchall()
        except Exception:
            _MUL16_CACHE[key] = set()
            return _MUL16_CACHE[key]

        s: set[int] = set()
        for r in rows or []:
            try:
                v = r["idx"] if hasattr(r, "keys") else r[0]
                if v is not None:
                    s.add(int(v))
            except Exception:
                pass

        _MUL16_CACHE[key] = s
        return s

    def _round_half_up_to_int(x: float) -> int:
        import math
        return int(math.floor(x + 0.5)) if x >= 0 else int(math.ceil(x - 0.5))

    def _try_mul_to_int(v, mul: float):
        # v может быть int/float/str
        s = str(v).strip() if v is not None else ""
        if not s:
            return v
        try:
            num = float(s.replace(",", "."))
        except Exception:
            return v
        return str(_round_half_up_to_int(num * float(mul)))

    # --- бонусы предмета ---
    rows = conn.execute(
        f"""
        SELECT eb.Id AS EBId,
               eb.OrderIndex,
               eb.Type_Id AS TypeId,
               bt.{tmpl_col} AS Tmpl
        FROM EquipmentBonus eb
        JOIN BonusType bt ON bt.Id = eb.Type_Id
        WHERE eb.Equipment_Id = ?
        ORDER BY eb.OrderIndex
        """,
        (int(equip_id),)
    ).fetchall()

    out: list[str] = []
    for r in rows or []:
        tmpl = (r["Tmpl"] if hasattr(r, "keys") else r[3]) or ""
        tmpl = str(tmpl).strip()
        if not tmpl:
            continue

        eb_id = int(r["EBId"] if hasattr(r, "keys") else r[0])
        bt_id = int(r["TypeId"] if hasattr(r, "keys") else r[2]) if (r is not None) else 0

        # читаем переменные как (idx -> val)
        try:
            vrows = conn.execute(
                f'''
                SELECT "{idx_col}" AS idx, "{val_col}" AS val
                FROM "{var_table}"
                WHERE "EquipmentBonus_Id" = ?
                ORDER BY "{idx_col}"
                ''',
                (eb_id,)
            ).fetchall()
        except Exception:
            vrows = []

        if not vrows:
            # без переменных всё равно пытаемся отрендерить
            try:
                out.append(tmpl.format())
            except Exception:
                out.append(tmpl)
            continue

        idx_list: list[int] = []
        vals_by_idx: dict[int, str] = {}

        for vr in vrows:
            try:
                i = int(vr["idx"] if hasattr(vr, "keys") else vr[0])
                vv = (vr["val"] if hasattr(vr, "keys") else vr[1])
            except Exception:
                continue
            idx_list.append(i)
            vals_by_idx[i] = str(vv)

        # --- применяем MulFormula=16 ---
        mul_raw = _mul16_indices_for_bonus_type(bt_id)

        # ключевое: авто-определяем смещение индексов между BonusTypeVariable и EquipmentBonusVariable
        # пробуем shift 0 / -1 / +1 и берём максимальное совпадение
        if mul_raw and armor_bl != 1.0:
            vset = set(idx_list)
            best_shift = 0
            best_score = -1
            for shift in (0, -1, 1):
                shifted = {m + shift for m in mul_raw}
                score = len(shifted & vset)
                if score > best_score:
                    best_score = score
                    best_shift = shift

            mul_effective = {m + best_shift for m in mul_raw}
            for i in mul_effective:
                if i in vals_by_idx:
                    vals_by_idx[i] = _try_mul_to_int(vals_by_idx[i], armor_bl)

        # собираем list для format(*vals) по максимальному индексу из EquipmentBonusVariable
        max_i = max(idx_list) if idx_list else -1
        vals: list[str] = [""] * (max_i + 1)
        for i in idx_list:
            if 0 <= i <= max_i:
                vals[i] = vals_by_idx.get(i, "")

        try:
            out.append(tmpl.format(*vals))
        except Exception:
            out.append(tmpl)

    return out

# -------- мелочь в один проход --------
def _pm_from_bytes(data: Optional[bytes]) -> Optional[QPixmap]:
    if not data:
        return None
    pm = QPixmap()
    return pm if pm.loadFromData(data) else None

def _gender_text(item: dict) -> str:
    try:
        g = int(item.get("Gender_Id"))
    except Exception:
        return "Любой"
    return "Мужской" if g == 1 else ("Женский" if g == 2 else "Любой")

def _stats_to_rich_with_yellow_prefix(stats: str) -> str:
    """
    Каждую строку вида 'XXX: ...' делает RichText,
    окрашивая 'XXX:' в BUFF_NAME_COLOR.
    """
    s = (stats or "").replace("\r", "")
    if not s.strip():
        return ""

    out = []
    for ln in s.split("\n"):
        ln = ln.rstrip()
        if not ln.strip():
            continue

        colon = ln.find(":")
        if 0 < colon < 60:
            head = html.escape(ln[:colon])
            tail = html.escape(ln[colon + 1:])  # вместе с пробелами после ":"
            out.append(
                f"<span style='color:{BUFF_NAME_COLOR}; font-weight:600;'>{head}:</span>{tail}"
            )
        else:
            out.append(html.escape(ln))

    return "<br/>".join(out)


class _Separator(QWidget):
    """
    Раньше рисовал линию-разделитель.
    Теперь отключён: ничего не рисует и не занимает место.
    """
    def __init__(self, color=_SEP, height=2, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(0)
        self.setMaximumHeight(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setVisible(False)

    def paintEvent(self, _):
        return

# -------- окно --------
class EquipmentInfoWindow(QFrame):
    """Компактный tooltip предмета: базовые поля, бонусы, печать. Никаких эвристик."""

    def __init__(self, parent: Optional[QWidget] = None):
        try:
            _platform_name = str(QApplication.platformName()).lower()
        except Exception:
            _platform_name = ""

        if "windows" in _platform_name:
            _flags = (
                    Qt.Tool |
                    Qt.FramelessWindowHint |
                    Qt.NoDropShadowWindowHint |
                    Qt.WindowDoesNotAcceptFocus |
                    Qt.WindowStaysOnTopHint
            )
        else:
            # На Linux Qt.Tool часто позиционируется оконным менеджером,
            # из-за чего move() может игнорироваться и окно улетает в центр экрана.
            # Qt.ToolTip/Popup-поведение стабильнее для hover-анкеты.
            _flags = (
                    Qt.ToolTip |
                    Qt.FramelessWindowHint |
                    Qt.NoDropShadowWindowHint |
                    Qt.WindowDoesNotAcceptFocus |
                    Qt.WindowStaysOnTopHint
            )

            # Для X11/XCB дополнительно просим обойти WM.
            # На Wayland этот флаг обычно игнорируется, но не ломает поведение.
            if "xcb" in _platform_name:
                _flags |= Qt.BypassWindowManagerHint

        super().__init__(parent, _flags)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)

        # состояние
        self._offset_map: Dict[str, Tuple[int, int]] = {}
        self._static_pm_cache: Dict[str, QPixmap] = {}
        self._pm_slot_empty: Optional[QPixmap] = None
        self._pm_slot_equipped: Optional[QPixmap] = None
        self._ctx_root = None  # QWidget верхнего окна: MainWindow / InventoryWindow / Reforge / Stamp

        # ---------- контейнер ----------
        self._panel = QFrame(self)
        self._panel.setObjectName("panel")
        self._panel.setStyleSheet("""
            QFrame#panel {
                background: rgba(15,15,18,0.70);
                border: 1px solid rgba(255,255,255,0.0);
                border-radius: 10px;
            }
            QLabel { color:#ddd; background:transparent; }
        """)
        sh = QGraphicsDropShadowEffect(self._panel)
        sh.setBlurRadius(24)
        sh.setOffset(0, 6)
        sh.setColor(Qt.black)
        self._panel.setGraphicsEffect(sh)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._panel)

        v = QVBoxLayout(self._panel)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(2)
        self._panel_layout = v

        # ---------- шрифты ----------
        f_title = QFont()
        f_title.setPointSizeF(11)
        f_title.setBold(True)

        f_sub = QFont()
        f_sub.setPointSizeF(10)

        # --- заголовок ---
        self.title_row = QHBoxLayout()
        self.title_row.setContentsMargins(0, 0, 0, 0)
        self.title_row.setSpacing(6)

        self.title_prefix = QLabel("")
        self.title_prefix.setFont(f_title)
        self.title_prefix.setStyleSheet("color:#ffd98a; font-weight:700;")
        self.title_prefix.setVisible(False)

        self.title_slot = QLabel("")
        self.title_slot.setFont(f_title)
        self.title_slot.setTextFormat(Qt.RichText)
        self.title_slot.setContentsMargins(0, 0, 0, 0)
        self.title_slot.setVisible(False)

        self.title_name = QLabel("")
        self.title_name.setWordWrap(True)
        self.title_name.setFont(f_title)
        self.title_name.setStyleSheet("font-weight:700;")
        self.title_name.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.title_name.setTextFormat(Qt.RichText)
        self.title_name.setTextInteractionFlags(Qt.NoTextInteraction)

        self.title_row.addWidget(self.title_prefix, 0, Qt.AlignBaseline)
        self.title_row.addWidget(self.title_slot, 0, Qt.AlignBaseline)
        self.title_row.addWidget(self.title_name, 1, Qt.AlignBaseline)
        v.addLayout(self.title_row)

        # ---------- подзаголовок ----------
        self.sub = QLabel("")
        self.sub.setFont(f_sub)
        self.sub.setStyleSheet("color:#bfbfbf;")
        self.sub.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.sub)

        # ---------- основной стат и оружейные строки ----------
        self.stat = QLabel("")
        self.stat.setFont(f_sub)

        self.spd = QLabel("")
        self.spd.setFont(f_sub)

        self.dps = QLabel("")
        self.dps.setFont(f_sub)

        v.addWidget(self.stat)
        v.addWidget(self.spd)
        v.addWidget(self.dps)

        # ---------- forge-блок ----------
        self.forge_box = QVBoxLayout()
        self.forge_box.setSpacing(2)
        v.addLayout(self.forge_box)

        self._last_render_sig = None
        self._last_render_ts = 0.0

        # ---------- бонусы предмета ----------
        self.bon_box = QVBoxLayout()
        self.bon_box.setSpacing(2)
        v.addLayout(self.bon_box)

        # ---------- карты ----------
        self.cards_box = QVBoxLayout()
        self.cards_box.setSpacing(4)
        v.addLayout(self.cards_box)

        # ---------- печать ----------
        self.stamp_row_container = QWidget(self._panel)
        self.stamp_row_container.setObjectName("stamp_row_container")
        self.stamp_row_container.setStyleSheet("background: transparent;")

        self.stamp_row = QHBoxLayout(self.stamp_row_container)
        self.stamp_row.setContentsMargins(0, 0, 0, 0)
        self.stamp_row.setSpacing(6)

        self.stamp_icon = QLabel()
        self.stamp_icon.setFixedSize(16, 16)
        self.stamp_icon.setScaledContents(True)

        self.stamp_name = QLabel("")
        self.stamp_name.setFont(f_title)

        self.stamp_row.addWidget(self.stamp_icon, 0, Qt.AlignVCenter)
        self.stamp_row.addWidget(self.stamp_name, 0, Qt.AlignVCenter)
        self.stamp_row.addItem(QSpacerItem(1, 1, QSizePolicy.Expanding, QSizePolicy.Minimum))

        v.addWidget(self.stamp_row_container)

        self.stamp_desc = QLabel("")
        self.stamp_desc.setWordWrap(True)
        v.addWidget(self.stamp_desc)

        # ---------- требования ----------
        self.req = QLabel("")
        self.req.setWordWrap(True)
        v.addWidget(self.req)

        # ---------- размеры ----------
        self.setMinimumWidth(345)

        # ---------- hover debounce ----------
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(120)
        self._hover_timer.timeout.connect(self._show_hover_now)

        self._hover_payload = None
        self._last_key = None
        self._last_item_id = None

        # ---- авто-обновление при смене уровня ----
        self._lvl_watch_timer = QTimer(self)
        self._lvl_watch_timer.setInterval(150)
        self._lvl_watch_timer.timeout.connect(self._on_level_watch)
        self._lvl_watch_last = None


    # ----- публичное API -----
    def _on_level_watch(self):
        if not self.isVisible() or not self._hover_payload:
            try:
                self._lvl_watch_timer.stop()
            except Exception:
                pass
            return

        lvl = self._get_char_level_safe()
        if lvl != self._lvl_watch_last:
            self._lvl_watch_last = lvl
            # заставляем пересчитать бонусы (sig включает lvl_sig)
            self._show_hover_now()

    def set_offset_map(self, mapping: Dict[str, Tuple[int, int]]) -> None:
        self._offset_map.update(mapping or {})

    def begin_hover(
            self,
            anchor_widget: QWidget,
            slot_key: Optional[str],
            item: dict,
            image_loader: Callable[[int], Optional[bytes]],
            type_name_lookup: Optional[Callable[[int], str]] = None,
            item_class: Optional[str] = None,
            bonus_lines: Optional[Iterable[str]] = None,
            stamp: Optional[dict] = None,
            cards: Optional[Sequence[Tuple[Optional[int], str]]] = None,
    ) -> None:
        self._hover_payload = (
            anchor_widget,
            slot_key,
            item,
            image_loader,
            type_name_lookup,
            item_class,
            bonus_lines,
            stamp,
            cards,
        )

        try:
            self._ctx_root = anchor_widget.window() if anchor_widget else None
        except Exception:
            self._ctx_root = None

        # На Linux/Wayland/XCB transientParent может заставить Qt.Tool
        # позиционироваться относительно родительского окна, а не глобальных координат.
        # Поэтому transientParent оставляем только на Windows.
        try:
            platform_name = str(QApplication.platformName()).lower()
        except Exception:
            platform_name = ""

        if "windows" in platform_name:
            try:
                host = self._ctx_root or getattr(self, "main_window", None) or self.parent()

                if isinstance(host, QWidget):
                    host = host.window()

                    host_handle = host.windowHandle()
                    if host_handle is None:
                        host.winId()
                        host_handle = host.windowHandle()

                    self.winId()
                    tip_handle = self.windowHandle()

                    if tip_handle is not None and host_handle is not None:
                        tip_handle.setTransientParent(host_handle)
            except Exception:
                pass
        else:
            try:
                self.winId()
                tip_handle = self.windowHandle()
                if tip_handle is not None:
                    tip_handle.setTransientParent(None)
            except Exception:
                pass

        self._hover_timer.start()

    def end_hover(self, _anchor_widget: QWidget) -> None:
        self._hover_timer.stop()
        self._hover_payload = None
        self._last_key = None
        self._last_item_id = None
        self._last_render_sig = None

        # На Wayland не трогаем setWindowOpacity:
        # часть плагинов его не поддерживает и начинает сыпать warning.
        self.hide()

        try:
            self._lvl_watch_timer.stop()
        except Exception:
            pass


    # ----- показ после антидребезга -----
    def _show_hover_now(self):
        if not self._hover_payload:
            return

        (anchor, slot_key, item, image_loader,
         type_name_lookup, item_class, bonus_lines, stamp, cards) = self._hover_payload

        if anchor is None or not isinstance(item, dict):
            return

        item_id = int(item.get("Id") or item.get("Equip_Id") or item.get("Equipment_Id") or 0)

        # аккуратно нормализуем cards в подпись
        cards_sig: tuple = ()
        try:
            if cards:
                cards_sig = tuple(
                    (
                        int(c[0]) if isinstance(c, (tuple, list)) and len(c) > 0 and c[0] is not None else 0,
                        str(c[1]) if isinstance(c, (tuple, list)) and len(c) > 1 else "",
                        str(c[2]) if isinstance(c, (tuple, list)) and len(c) > 2 else "",
                    )
                    for c in cards
                )
        except Exception:
            cards_sig = ()

        # подпись печати — какая-то стабильная штука
        stamp_sig = None
        if isinstance(stamp, dict):
            for k in ("Id", "Stamp_Id", "InstanceGuid", "Guid", "Name"):
                if k in stamp and stamp[k] is not None:
                    stamp_sig = (k, str(stamp[k]))
                    break
            if stamp_sig is None:
                try:
                    stamp_sig = tuple(sorted((str(k), str(v)) for k, v in stamp.items()))
                except Exception:
                    stamp_sig = str(stamp)
        else:
            stamp_sig = None if stamp is None else str(stamp)

        # подпись временного улучшения/эликсира
        elixir_sig = None
        try:
            el = (item or {}).get("Elixir") or (item or {}).get("_elixir")
            if isinstance(el, dict):
                eid = int(el.get("Id") or el.get("id") or 0)
                nm = str(el.get("Name") or el.get("name") or "")
                bons = el.get("Bonuses") or el.get("bonuses") or []
                bt: list[tuple[int, int, int]] = []
                if isinstance(bons, (list, tuple)):
                    for b in bons:
                        if not isinstance(b, dict):
                            continue
                        oi = int(b.get("OrderIndex") or 0)
                        tid = int(b.get("Type_Id") or b.get("TypeId") or 0)
                        val = int(b.get("Value") or 0)
                        bt.append((oi, tid, val))
                elixir_sig = (eid, nm, tuple(bt))
            elif isinstance(el, (list, tuple)):
                pack: list[tuple[int, str]] = []
                for e in el:
                    if not isinstance(e, dict):
                        continue
                    eid = int(e.get("Id") or e.get("id") or 0)
                    nm = str(e.get("Name") or e.get("name") or "")
                    if eid > 0 or nm:
                        pack.append((eid, nm))
                elixir_sig = tuple(pack) if pack else None
        except Exception:
            elixir_sig = None

        lvl_sig = self._get_char_level_safe()
        sig = (slot_key, item_id, cards_sig, stamp_sig, elixir_sig, lvl_sig)

        # Если та же анкета уже видна — не перерисовываем.
        # Если она скрылась/улетела — продолжаем и показываем заново.
        if sig == self._last_render_sig:
            try:
                if self.isVisible():
                    return
            except Exception:
                pass

        self._last_render_sig = sig
        self._last_key, self._last_item_id = slot_key, item_id

        # ВАЖНО:
        # Якорь берём строго от anchor, который передало меню.
        # На Linux QApplication.widgetAt(cursor_pos) может вернуть не тот слой.
        try:
            anchor_rect_global = QRect(
                anchor.mapToGlobal(anchor.rect().topLeft()),
                anchor.rect().size(),
            )
        except Exception:
            anchor_rect_global = None

        if anchor_rect_global is not None and anchor_rect_global.isValid():
            center = anchor_rect_global.center()
        else:
            center = QCursor.pos()

        dx, dy = self._offset_map.get(slot_key, (0, 0))

        self.show_for_item(
            item=item,
            image_loader=image_loader,
            global_pos=center,
            slot_key=slot_key,
            type_name=None,
            type_name_lookup=type_name_lookup,
            item_class=item_class,
            cards=cards,
            bonus_lines=bonus_lines,
            stamp=stamp,
            anchor_rect_global=anchor_rect_global,
            offset_dx=dx,
            offset_dy=dy,
        )

    # ----- основной показ -----
    def show_for_item(
            self,
            item: dict,
            image_loader,
            global_pos: QPoint,
            *,
            slot_key: Optional[str] = None,
            type_name: Optional[str] = None,
            type_name_lookup: Optional[Callable[[int], str]] = None,
            item_class: Optional[str] = None,
            cards: Optional[Sequence[Tuple[Optional[int], str]]] = None,
            bonus_lines: Optional[Iterable[str]] = None,
            stamp: Optional[dict] = None,
            anchor_rect_global: Optional[QRect] = None,
            offset_dx: Optional[int] = None,
            offset_dy: Optional[int] = None,
    ):
        # ------------------------------------------------------------------
        # 1) Нормальный глобальный якорь.
        #    Вся логика расположения должна идти только отсюда.
        # ------------------------------------------------------------------
        if anchor_rect_global is not None and anchor_rect_global.isValid():
            anchor_rect = QRect(anchor_rect_global)
        else:
            anchor_rect = QRect(global_pos, QSize(1, 1))

        anchor_center = anchor_rect.center()

        # ------------------------------------------------------------------
        # 2) Linux/Windows flags + transientParent.
        # ------------------------------------------------------------------
        try:
            platform_name = str(QApplication.platformName()).lower()
        except Exception:
            platform_name = ""

        try:
            if "windows" in platform_name:
                desired_flags = (
                        Qt.Tool |
                        Qt.FramelessWindowHint |
                        Qt.NoDropShadowWindowHint |
                        Qt.WindowDoesNotAcceptFocus |
                        Qt.WindowStaysOnTopHint
                )
            else:
                desired_flags = (
                        Qt.ToolTip |
                        Qt.FramelessWindowHint |
                        Qt.NoDropShadowWindowHint |
                        Qt.WindowDoesNotAcceptFocus |
                        Qt.WindowStaysOnTopHint
                )
                if "xcb" in platform_name:
                    desired_flags |= Qt.BypassWindowManagerHint

            if self.windowFlags() != desired_flags:
                was_visible = self.isVisible()
                if was_visible:
                    self.hide()

                self.setWindowFlags(desired_flags)

                self.setAttribute(Qt.WA_TranslucentBackground, True)
                self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                self.setAttribute(Qt.WA_ShowWithoutActivating, True)
                self.setAttribute(Qt.WA_NoSystemBackground, True)
                self.setAttribute(Qt.WA_StyledBackground, False)
                self.setAutoFillBackground(False)
        except Exception:
            pass

        try:
            host = getattr(self, "_ctx_root", None) or getattr(self, "main_window", None) or self.parent()

            if isinstance(host, QWidget):
                host = host.window()

                host_handle = host.windowHandle()
                if host_handle is None:
                    host.winId()
                    host_handle = host.windowHandle()

                self.winId()
                tip_handle = self.windowHandle()

                if tip_handle is not None and host_handle is not None:
                    tip_handle.setTransientParent(host_handle)
        except Exception:
            pass

        # ------------------------------------------------------------------
        # 3) Экран.
        # ------------------------------------------------------------------
        scr = None
        try:
            sc = QApplication.screenAt(anchor_center)
            scr = sc.availableGeometry() if sc else None
        except Exception:
            scr = None

        if scr is None:
            try:
                sc2 = self.screen() or QApplication.primaryScreen()
                scr = sc2.availableGeometry()
            except Exception:
                scr = QRect(0, 0, 1920, 1080)

        pad = 6
        gap = 5

        extra_dx = 0 if offset_dx is None else int(offset_dx)
        extra_dy = 0 if offset_dy is None else int(offset_dy)

        # ------------------------------------------------------------------
        # 4) Стабильная ширина.
        #    Не подгоняем ширину под маленький слот.
        # ------------------------------------------------------------------
        try:
            target_w = max(345, int(self.minimumWidth()))
        except Exception:
            target_w = 345

        self.setFixedWidth(target_w)
        self._panel.setFixedWidth(target_w)
        self.title_name.setMaximumWidth(max(1, target_w - 32))

        # ------------------------------------------------------------------
        # 5) Полная пересборка содержимого.
        # ------------------------------------------------------------------
        self.setUpdatesEnabled(False)
        try:
            self._reset()
        finally:
            self.setUpdatesEnabled(True)

        raw_item = item if isinstance(item, dict) else None
        eff_item = dict(item) if isinstance(item, dict) else ({} if item else {})

        def _to_int(v, default=0) -> int:
            try:
                return int(v)
            except Exception:
                return default

        forge_level = _to_int(
            eff_item.get("__forge_level")
            or eff_item.get("ForgeLevel")
            or eff_item.get("UpgradeLevel")
            or 0,
            0,
        )

        forge_bonus = _to_int(
            eff_item.get("__forge_bonus")
            or eff_item.get("ForgeBonus")
            or eff_item.get("UpgradeMainBonus")
            or 0,
            0,
        )

        forge_all = _to_int(
            eff_item.get("__forge_allstat")
            or eff_item.get("ForgeAllStatBonus")
            or eff_item.get("ForgeAllStat")
            or eff_item.get("AllStatBonus")
            or 0,
            0,
        )

        forge_hp = _to_int(
            eff_item.get("__forge_hp_bonus")
            or eff_item.get("ForgeHpBonus")
            or eff_item.get("HpBonusFromForge")
            or 0,
            0,
        )

        if forge_level > 0:
            eff_item["__forge_level"] = forge_level
            eff_item["__forge_bonus"] = forge_bonus
            eff_item["__forge_allstat"] = forge_all
            eff_item["__forge_hp_bonus"] = forge_hp
        else:
            eff_item.pop("__forge_level", None)
            eff_item.pop("__forge_bonus", None)
            eff_item.pop("__forge_allstat", None)
            eff_item.pop("__forge_hp_bonus", None)

        self.setUpdatesEnabled(False)
        try:
            self._fill(
                eff_item,
                image_loader,
                slot_key,
                type_name,
                type_name_lookup,
                item_class,
                cards,
                bonus_lines,
                stamp,
                orig_item=raw_item,
            )
        finally:
            self.setUpdatesEnabled(True)

        # Первый честный расчёт размера до позиционирования.
        # Запоминаем минимальную высоту текущего показа, чтобы поздний QTimer
        # на Linux не смог схлопнуть уже нормально рассчитанную анкету.
        try:
            self._tip_min_height_this_show = 0
        except Exception:
            pass

        self._commit_size()

        try:
            self._tip_min_height_this_show = max(
                int(getattr(self, "_tip_min_height_this_show", 0) or 0),
                int(self.height()),
            )
        except Exception:
            pass

        def _position_now():
            tip_w = int(self.width())
            tip_h = int(self.height())

            ax_left = int(anchor_rect.left())
            ax_right = int(anchor_rect.right())
            ax_top = int(anchor_rect.top())
            ax_bottom = int(anchor_rect.bottom())
            ax_center_x = int(anchor_rect.center().x())
            ax_center_y = int(anchor_rect.center().y())

            screen_left = int(scr.left()) + pad
            screen_top = int(scr.top()) + pad
            screen_right = int(scr.right()) - pad
            screen_bottom = int(scr.bottom()) - pad

            def _clamp_x(x: int) -> int:
                return max(screen_left, min(int(x), screen_right - tip_w))

            def _clamp_y(y: int) -> int:
                return max(screen_top, min(int(y), screen_bottom - tip_h))

            def _rect_for(x: int, y: int) -> QRect:
                return QRect(int(x), int(y), int(tip_w), int(tip_h))

            avoid = QRect(anchor_rect).adjusted(-2, -2, 2, 2)

            space_right = screen_right - ax_right
            space_left = ax_left - screen_left
            need_w = tip_w + gap

            if space_right < need_w and space_left >= need_w:
                first_side = "left"
            elif space_right < need_w and space_left < need_w:
                first_side = "right" if space_right >= space_left else "left"
            else:
                first_side = "right"

            right_x = ax_right + gap + extra_dx
            left_x = ax_left - gap - tip_w - extra_dx
            side_y = ax_center_y - tip_h // 2 + extra_dy

            below_x = ax_center_x - tip_w // 2 + extra_dx
            below_y = ax_bottom + gap + extra_dy

            above_x = ax_center_x - tip_w // 2 + extra_dx
            above_y = ax_top - gap - tip_h - extra_dy

            candidates: list[tuple[str, int, int]] = []

            if first_side == "right":
                candidates.append(("right", right_x, side_y))
                candidates.append(("left", left_x, side_y))
            else:
                candidates.append(("left", left_x, side_y))
                candidates.append(("right", right_x, side_y))

            candidates.append(("below", below_x, below_y))
            candidates.append(("above", above_x, above_y))
            candidates.append(("right_top", right_x, ax_top + extra_dy))
            candidates.append(("left_top", left_x, ax_top + extra_dy))
            candidates.append(("right_bottom", right_x, ax_bottom - tip_h + extra_dy))
            candidates.append(("left_bottom", left_x, ax_bottom - tip_h + extra_dy))

            best_rect = None
            best_score = None

            for _name, cx, cy in candidates:
                x = _clamp_x(cx)
                y = _clamp_y(cy)
                r = _rect_for(x, y)

                if not r.intersects(avoid):
                    best_rect = r
                    break

                inter = r.intersected(avoid)
                score = 100000
                score += max(0, inter.width()) * max(0, inter.height())
                score += abs(r.center().x() - ax_center_x)
                score += abs(r.center().y() - ax_center_y)

                if best_score is None or score < best_score:
                    best_score = score
                    best_rect = r

            if best_rect is None:
                best_rect = _rect_for(
                    _clamp_x(ax_right + gap + extra_dx),
                    _clamp_y(ax_center_y - tip_h // 2 + extra_dy),
                )

            target_pos = QPoint(int(best_rect.x()), int(best_rect.y()))

            try:
                self.move(target_pos)
            except Exception:
                pass

            # На Linux/X11 иногда QWidget.move() и QWindow.setPosition()
            # ведут себя по-разному, поэтому дублируем позицию в windowHandle.
            try:
                wh = self.windowHandle()
                if wh is not None:
                    wh.setPosition(target_pos)
            except Exception:
                pass

        # ------------------------------------------------------------------
        # 6) Позиционируем ДО show(), но финальный resize/move делаем невидимо.
        #    Это убирает визуальное подёргивание и не даёт анкете сжаться.
        # ------------------------------------------------------------------
        _position_now()

        platform_name = ""
        try:
            platform_name = str(QApplication.platformName()).lower()
        except Exception:
            platform_name = ""

        # На Windows можно безопасно прятать окно через opacity,
        # чтобы пользователь не видел промежуточный кривой размер.
        use_invisible_first_show = "windows" in platform_name

        if use_invisible_first_show:
            try:
                self.setWindowOpacity(0.0)
            except Exception:
                pass

        self.show()
        self.raise_()

        def _after_show_fix():
            if not self.isVisible():
                return

            self._commit_size()

            try:
                self._tip_min_height_this_show = max(
                    int(getattr(self, "_tip_min_height_this_show", 0) or 0),
                    int(self.height()),
                )
            except Exception:
                pass

            _position_now()
            self.raise_()

            try:
                self._lvl_watch_last = self._get_char_level_safe()
                self._lvl_watch_timer.start()
            except Exception:
                pass

            try:
                self.setWindowOpacity(1.0)
            except Exception:
                pass

        def _after_late_layout_fix():
            if not self.isVisible():
                return

            self._commit_size()

            try:
                self._tip_min_height_this_show = max(
                    int(getattr(self, "_tip_min_height_this_show", 0) or 0),
                    int(self.height()),
                )
            except Exception:
                pass

            _position_now()
            self.raise_()

            try:
                self.setWindowOpacity(1.0)
            except Exception:
                pass

        QTimer.singleShot(0, _after_show_fix)

        # На Windows обычно хватает одного тика, но для RichText/wordWrap
        # оставляем второй контрольный проход уже без видимого дёргания.
        QTimer.singleShot(35, _after_late_layout_fix)

    # ----- наполнение -----
    def _cards_from_cards_window(
            self,
            item: dict | None,
            slot_key: Optional[str],
    ) -> Optional[Sequence[Tuple[Optional[int], str]]]:
        """
        Пытаемся взять список карт у CardsWindow.

        Раньше работало через self.parent(), но после перевода EquipmentInfoWindow
        в top-level окно parent=None. Поэтому теперь сначала ищем main_window,
        который был вручную записан как self.main_window / self._ctx_root.
        """
        if not item:
            return None

        host = None

        # 1) новый основной путь после EquipmentInfoWindow(None)
        try:
            host = getattr(self, "main_window", None)
        except Exception:
            host = None

        # 2) запасной путь, если где-то был сохранён контекст
        if host is None:
            try:
                host = getattr(self, "_ctx_root", None)
            except Exception:
                host = None

        # 3) старый путь, если окно снова когда-нибудь будет с parent
        if host is None:
            try:
                host = self.parent()
            except Exception:
                host = None

        if host is None:
            return None

        cw = getattr(host, "cards_window", None)
        if cw is None:
            return None

        try:
            kind = "weapon" if self._is_weapon_or_spear(item, slot_key or "") else "equipment"
        except Exception:
            kind = "equipment"

        # Основной метод, который уже используется в inventory/reforge.
        fn = getattr(cw, "build_tooltip_cards_payload_for_item", None)
        if callable(fn):
            try:
                payload = fn(
                    item=item,
                    kind=kind,
                    slot_key=(slot_key or ""),
                )
            except TypeError:
                try:
                    payload = fn(
                        item,
                        kind=kind,
                        slot_key=(slot_key or ""),
                    )
                except TypeError:
                    try:
                        payload = fn(item, kind=kind)
                    except Exception:
                        payload = None
                except Exception:
                    payload = None
            except Exception:
                payload = None

            if payload:
                return payload

        return None

    def _fill(
            self, item: dict, image_loader, slot_key, type_name, type_name_lookup,
            item_class, cards, bonus_lines, stamp,
            orig_item: Optional[dict] = None,
    ):
        from typing import Optional
        from html import escape as _esc
        import re as _re

        # если список карт нам явно не передали – пробуем спросить у CardsWindow
        if cards is None:
            cards = self._cards_from_cards_window(item, slot_key)

        FORGE_GREEN = "#32CD32"

        def _to_int(v, d=0) -> int:
            try:
                return int(v)
            except Exception:
                return d

        def _pm(icon_id: Optional[int]):
            if not icon_id:
                return None
            try:
                return _pm_from_bytes(image_loader(icon_id))
            except Exception:
                return None

        # ---------- базовая нормализация item ----------
        if not isinstance(item, dict):
            item = {} if not item else dict(item)

        # исходный dict из MainWindow, в который можно что-то дописать
        orig_item_ref = orig_item if isinstance(orig_item, dict) else None

        # ---------- 1) тип / slot_key / флаги ----------
        raw_tid = item.get("Type_Id") if item.get("Type_Id") is not None else item.get("TypeId")
        if type_name_lookup and raw_tid is not None:
            try:
                typ = type_name_lookup(int(raw_tid)) or "—"
            except Exception:
                typ = "—"
        elif type_name:
            typ = type_name
        else:
            typ = str(item.get("TypeName") or "—")

        slot_key_eff = str(slot_key or item.get("slot_key") or item.get("SlotKey") or "").strip().lower()
        typ_l = typ.lower()

        is_costume = (slot_key_eff == "costume") or ("костюм" in typ_l)
        is_ornament = (slot_key_eff == "ornament") or ("украшение" in typ_l)
        is_mount = (slot_key_eff == "mount") or ("ездов" in typ_l) or ("mount" in typ_l) or (_to_int(raw_tid, 0) == 15)

        hide_card_slots = is_costume or is_ornament or is_mount
        suppress_stamp_section = hide_card_slots or (stamp is False)

        # ---------- 2) forge meta ----------
        raw_up_level = _to_int(item.get("UpgradeLevel"), 0)

        forge_level = _to_int(
            item.get("__forge_level") or item.get("ForgeLevel") or item.get("forge_level") or 0, 0
        )
        forge_bonus = _to_int(
            item.get("__forge_bonus") or item.get("ForgeBonus") or item.get("forge_bonus")
            or item.get("UpgradeMainBonus") or 0,
            0,
        )
        forge_hp_bonus = _to_int(
            item.get("__forge_hp_bonus") or item.get("ForgeHpBonus") or item.get("HpBonusFromForge") or 0, 0
        )
        forge_allstat = _to_int(
            item.get("__forge_allstat") or item.get("ForgeAllStatBonus") or item.get("ForgeAllStat")
            or item.get("AllStatBonus") or 0,
            0,
        )

        # НОВОЕ: отдельные бонусы атаки / защиты (их как раз даёт рефорджа)
        forge_bonus_atk = _to_int(
            item.get("__forge_atk_bonus") or item.get("ForgeAttackBonus") or item.get("ForgeAtkBonus") or 0,
            0,
        )
        forge_bonus_def = _to_int(
            item.get("__forge_def_bonus") or item.get("ForgeDefenseBonus") or item.get("ForgeDefBonus") or 0,
            0,
        )

        level_for_calc = forge_level or raw_up_level
        allstat_effective = forge_allstat if forge_allstat > 0 else (1 if level_for_calc >= 11 else 0)

        # ---------- 3) заголовок ----------
        orig_name = str(item.get("Name") or "Безымянный предмет")
        # если внезапно в Name лежит имя карты, а мы на оружии – пробуем взять базовое имя
        if self._is_weapon_or_spear(item, slot_key_eff):
            low = orig_name.casefold()
            if low.startswith("карта ") or low.startswith("card "):
                alt = (
                        item.get("EquipName")
                        or item.get("EquipmentName")
                        or item.get("BaseItemName")
                        or item.get("BaseName")
                )
                if alt:
                    orig_name = str(alt)

        name = _re.sub(r"^\s*\+\d+\s+", "", orig_name)

        title_lvl = 0
        for kf in ("__forge_level", "ForgeLevel", "forge_level", "UpgradeLevel"):
            vv = _to_int(item.get(kf) or 0, 0)
            if vv > 0:
                title_lvl = vv
                break
        if title_lvl <= 0:
            m = _re.match(r"^\s*\+(\d+)\s+", orig_name)
            if m:
                title_lvl = _to_int(m.group(1), 0)

        color = (
                (stamp or {}).get("HeaderColorHex")
                or STAMP_COLORS.get((stamp or {}).get("color", ""), DEFAULT_STAMP_COLOR)
        )

        # слот-иконки в заголовке (НЕ для костюма/украшения/ездового)
        slot_html = ""
        if not hide_card_slots:
            is_weapon_slots = self._is_weapon_or_spear(item, slot_key_eff)
            slot_count = 3 if is_weapon_slots else 1

            # cards_seq: [(icon_id, name, desc), ...]
            cards_seq: List[Tuple[Optional[int], str, str]] = []
            try:
                for c in (cards or []):
                    if isinstance(c, (tuple, list)):
                        icon_id = c[0] if len(c) > 0 else None
                        name_c = str(c[1]) if len(c) > 1 else ""
                        desc_c = str(c[2]) if len(c) > 2 else ""
                    else:
                        icon_id = None
                        name_c = str(c)
                        desc_c = ""
                    cards_seq.append((icon_id, name_c, desc_c))
            except Exception:
                cards_seq = []

            cards_len = len(cards_seq)
            imgs: List[str] = []

            for idx in range(slot_count):
                has = idx < cards_len
                custom_pm = None
                if has and is_weapon_slots:
                    icon_id = cards_seq[idx][0]
                    if icon_id:
                        custom_pm = _pm(_to_int(icon_id, 0))

                shift = 2 if is_weapon_slots else -2  # как ты хотел

                img = self._slot_img_html(
                    has_card=has,
                    w=CARD_ICON_W,
                    h=CARD_ICON_H,
                    custom_pm=custom_pm,
                    shift_y=shift,
                )
                if img:
                    imgs.append(img)

            slot_html = " ".join(imgs)

        # --- РАЗДЕЛЬНЫЕ ЛЕЙБЛЫ В ЗАГОЛОВКЕ ---

        # +уровень
        if title_lvl > 0:
            self.title_prefix.setText(f"+{title_lvl}")
            self.title_prefix.setStyleSheet(f"color:{color}; font-weight:700;")
            self.title_prefix.show()
        else:
            self.title_prefix.clear()
            self.title_prefix.hide()

        # иконки слотов
        if slot_html:
            self.title_slot.setText(slot_html)
            self.title_slot.setTextFormat(Qt.RichText)
            self.title_slot.show()
        else:
            self.title_slot.clear()
            self.title_slot.hide()

        # название
        self.title_name.setText(_esc(name))
        self.title_name.setTextFormat(Qt.RichText)
        self.title_name.setStyleSheet(f"color:{color}; font-weight:700;")

        # ---------- 4) подзаголовок ----------
        if is_costume or is_ornament:
            self.sub.setText(typ)
        else:
            internal_lvl = self._get_internal_level_for_item(item)
            klass = self._class_letter_from_internal(internal_lvl)
            if not klass or klass == "—":
                klass = str(item_class or item.get("ItemClass") or "—")
            self.sub.setText(f"{typ}   •   Класс: {klass}")

        # общий req_lvl (для обоих путей)
        req_lvl = _to_int(item.get("Level") or item.get("RequiredLevel") or 1, 1) or 1

        # =====================================================================
        # ОСОБЫЙ ПУТЬ: КОСТЮМ / УКРАШЕНИЕ
        # =====================================================================
        if is_costume or is_ornament:
            self._fill_costume_ornament(
                item=item,
                typ=typ,
                slot_key=slot_key,
                bonus_lines=bonus_lines,
                req_lvl=req_lvl,
            )
            return

        # =====================================================================
        # ДАЛЬШЕ — ФИЛЛ ДЛЯ ВСЕХ ОСТАЛЬНЫХ ПРЕДМЕТОВ (включая mount)
        # =====================================================================
        self._fill_regular_item(
            item=item,
            image_loader=image_loader,
            slot_key_eff=slot_key_eff,
            type_name=type_name,
            cards=cards,
            bonus_lines=bonus_lines,
            stamp=stamp,
            suppress_stamp_section=suppress_stamp_section,
            hide_card_slots=hide_card_slots,
            color=color,
            level_for_calc=level_for_calc,
            forge_bonus=forge_bonus,
            forge_hp_bonus=forge_hp_bonus,
            allstat_effective=allstat_effective,
            orig_item=orig_item_ref,
            forge_bonus_atk=forge_bonus_atk,
            forge_bonus_def=forge_bonus_def,
        )

        # требования (обычный предмет)
        self.req.setText(f"Требуется уровень: {req_lvl}    Пол: {_gender_text(item)}")

    def _get_char_level_safe(self) -> Optional[int]:
        """
        Достаём уровень персонажа максимально надёжно.

        Приоритет:
        1) _ctx_root.get_level()
        2) self.main_window.get_level()
        3) parent-chain.get_level()
        4) obj.data.level / obj.data.char_level
        5) obj.level / obj.char_level (атрибуты)
        6) поиск в UI: QSpinBox/QComboBox/QLineEdit с objectName содержащим level/lvl
        """

        def _to_int(v) -> Optional[int]:
            if v is None:
                return None
            try:
                # если это метод/лямбда
                if callable(v):
                    v = v()
            except Exception:
                pass
            try:
                s = str(v).strip()
                if not s:
                    return None
                return int(float(s.replace(",", ".")))
            except Exception:
                return None

        def _try_get_level_method(obj) -> Optional[int]:
            if obj is None:
                return None
            fn = getattr(obj, "get_level", None)
            if callable(fn):
                try:
                    return _to_int(fn())
                except Exception:
                    return None
            return None

        def _try_data_level(obj) -> Optional[int]:
            if obj is None:
                return None
            data = getattr(obj, "data", None)
            if data is None:
                return None
            for k in ("level", "char_level", "player_level", "lvl", "Level", "CharLevel"):
                if hasattr(data, k):
                    v = getattr(data, k)
                    got = _to_int(v)
                    if got is not None:
                        return got
            return None

        def _try_attr_level(obj) -> Optional[int]:
            if obj is None:
                return None
            for k in ("level", "char_level", "player_level", "lvl", "Level", "CharLevel"):
                if hasattr(obj, k):
                    v = getattr(obj, k)
                    got = _to_int(v)
                    if got is not None:
                        return got
            # иногда лежит в obj.ui.*
            ui = getattr(obj, "ui", None)
            if ui is not None:
                for k in ("level", "char_level", "player_level", "lvl", "Level", "CharLevel"):
                    if hasattr(ui, k):
                        v = getattr(ui, k)
                        got = _to_int(v)
                        if got is not None:
                            return got
            return None

        def _try_find_level_widget(root) -> Optional[int]:
            if root is None:
                return None
            # 1) SpinBox по objectName
            try:
                spins = root.findChildren(QSpinBox)
            except Exception:
                spins = []
            best = None

            def _score_spin(sp: QSpinBox) -> int:
                n = (sp.objectName() or "").lower()
                score = 0
                if "level" in n or "lvl" in n:
                    score += 100
                # типичные диапазоны уровня
                try:
                    mn = int(sp.minimum());
                    mx = int(sp.maximum())
                    if 1 <= mn <= 10:
                        score += 5
                    if 50 <= mx <= 300:
                        score += 10
                    if mx >= 60:
                        score += 3
                except Exception:
                    pass
                return score

            best_score = -1
            for sp in spins:
                sc = _score_spin(sp)
                if sc > best_score:
                    best_score = sc
                    best = sp

            if best is not None:
                try:
                    return int(best.value())
                except Exception:
                    pass

            # 2) ComboBox
            try:
                combos = root.findChildren(QComboBox)
            except Exception:
                combos = []
            for cb in combos:
                n = (cb.objectName() or "").lower()
                if "level" in n or "lvl" in n:
                    got = _to_int(cb.currentText())
                    if got is not None:
                        return got

            # 3) LineEdit
            try:
                edits = root.findChildren(QLineEdit)
            except Exception:
                edits = []
            for le in edits:
                n = (le.objectName() or "").lower()
                if "level" in n or "lvl" in n:
                    got = _to_int(le.text())
                    if got is not None:
                        return got

            return None

        # 0) ctx_root
        root = getattr(self, "_ctx_root", None)
        lvl = _try_get_level_method(root)
        if lvl is not None:
            return lvl
        lvl = _try_data_level(root)
        if lvl is not None:
            return lvl
        lvl = _try_attr_level(root)
        if lvl is not None:
            return lvl
        lvl = _try_find_level_widget(root)
        if lvl is not None:
            return lvl

        # 1) self.main_window
        mw = getattr(self, "main_window", None)
        lvl = _try_get_level_method(mw)
        if lvl is not None:
            return lvl
        lvl = _try_data_level(mw)
        if lvl is not None:
            return lvl
        lvl = _try_attr_level(mw)
        if lvl is not None:
            return lvl
        lvl = _try_find_level_widget(mw)
        if lvl is not None:
            return lvl

        # 2) parent-chain
        w = self
        for _ in range(12):
            try:
                w = w.parent()
            except Exception:
                w = None
            if w is None:
                break

            lvl = _try_get_level_method(w)
            if lvl is not None:
                return lvl
            lvl = _try_data_level(w)
            if lvl is not None:
                return lvl
            lvl = _try_attr_level(w)
            if lvl is not None:
                return lvl
            lvl = _try_find_level_widget(w)
            if lvl is not None:
                return lvl

            mw2 = getattr(w, "main_window", None)
            lvl = _try_get_level_method(mw2)
            if lvl is not None:
                return lvl
            lvl = _try_data_level(mw2)
            if lvl is not None:
                return lvl
            lvl = _try_attr_level(mw2)
            if lvl is not None:
                return lvl
            lvl = _try_find_level_widget(mw2)
            if lvl is not None:
                return lvl

        return None

    def _get_bonus_list(self, item: dict, bonus_lines: Optional[Iterable[str]]) -> list[str]:
        """Единый способ достать текстовые бонусы предмета + проставить '+' перед числовыми строками."""
        import re

        def _add_plus_prefix(s: str) -> str:
            s = (s or "").strip()
            if not s:
                return s
            if s[0] in "+-":
                return s
            m = re.match(r"(\d+)(.*)", s)
            if m:
                return f"+{m.group(1)}{m.group(2)}"
            return s

        def _norm_list(ls):
            out: list[str] = []
            for x in ls or []:
                s = str(x).strip()
                if not s:
                    continue
                out.append(_add_plus_prefix(s))
            return out

        # 1) Пытаемся получить бонусы из БД (с учётом уровня) — это приоритет
        try:
            conn = self._db_conn()
            equip_id = (
                    (item or {}).get("Equip_Id") or (item or {}).get("Equipment_Id")
                    or (item or {}).get("EquipId") or (item or {}).get("EquipmentId")
                    or (item or {}).get("Id")
            )
            if conn and equip_id:
                lvl = self._get_char_level_safe()
                ls = _render_bonus_lines_local(conn, int(equip_id), char_level=lvl) or []
                if ls:
                    return _norm_list(ls)
        except Exception as e:
            self._last_bonus_db_error = repr(e)

        # 2) Fallback: то, что передали извне (если БД недоступна)
        if bonus_lines is not None:
            try:
                return _norm_list(list(bonus_lines))
            except Exception:
                return _norm_list([str(bonus_lines)])

        return []

    def _fill_costume_ornament(
            self,
            item: dict,
            typ: str,
            slot_key: Optional[str],
            bonus_lines: Optional[Iterable[str]],
            req_lvl: int,
    ) -> None:
        # карт нет
        self._clear(self.cards_box)

        # статы / оружейные строки не нужны
        for lbl in (self.stat, self.spd, self.dps):
            lbl.clear()
            lbl.hide()

        # forge-блок чистим полностью
        if hasattr(self, "forge_box"):
            self._clear(self.forge_box)

        # бонусы
        base_bonus = self._get_bonus_list(item, bonus_lines)
        cleaned: list[str] = []
        for s in base_bonus:
            cleaned.append(s)

        self._clear(self.bon_box)
        for s in cleaned:
            lbl = QLabel(s)
            lbl.setWordWrap(True)
            self.bon_box.addWidget(lbl)

        # секция печати для костюма/украшения вообще не используется
        self.stamp_row_container.hide()
        self.stamp_icon.clear()
        self.stamp_name.clear()
        self.stamp_desc.clear()

        # ✅ и временные улучшения тоже прячем
        self._hide_elixir_section()

        # требования
        self.req.setText(f"Требуется уровень: {req_lvl}    Пол: {_gender_text(item)}")

    def _bonus_text_css(self) -> str:
        """
        Возвращает цвет/стиль как у бонусных строк.
        Берём палитру с уже существующего QLabel из bon_box, если есть.
        """
        try:
            # найдём первый QLabel в bon_box
            for i in range(self.bon_box.count()):
                it = self.bon_box.itemAt(i)
                w = it.widget() if it else None
                if isinstance(w, QLabel):
                    # если у лейбла явно задан stylesheet — используем его
                    ss = (w.styleSheet() or "").strip()
                    if ss:
                        return ss
                    # иначе — берем цвет из палитры
                    c = w.palette().color(w.foregroundRole())
                    return f"color: rgba({c.red()},{c.green()},{c.blue()},{c.alpha()});"
        except Exception:
            pass
        # fallback — просто белый (если вдруг нет ни одного бонусного лейбла)
        return "color:#eaeaea;"

    def _fill_regular_item(
            self,
            item: dict,
            image_loader,
            slot_key_eff: str,
            type_name: Optional[str],
            cards: Optional[Sequence[Tuple[Optional[int], str]]],
            bonus_lines: Optional[Iterable[str]],
            stamp: Optional[dict],
            suppress_stamp_section: bool,
            hide_card_slots: bool,
            color: str,
            level_for_calc: int,
            forge_bonus: int,
            forge_hp_bonus: int,
            allstat_effective: int,
            orig_item: Optional[dict] = None,
            forge_bonus_atk: Optional[int] = None,
            forge_bonus_def: Optional[int] = None,
    ) -> None:

        from typing import Optional as _Opt

        FORGE_GREEN = "#32CD32"

        def _to_int(v, d=0) -> int:
            try:
                return int(v)
            except Exception:
                return d

        def _pm(icon_id: _Opt[int]):
            if not icon_id:
                return None
            try:
                return _pm_from_bytes(image_loader(icon_id))
            except Exception:
                return None

        def _to_float_or_none(v) -> Optional[float]:
            if v is None:
                return None
            try:
                s = str(v).strip()
                if not s or s == "—":
                    return None
                return float(s.replace(",", "."))
            except Exception:
                return None

        def _fmt_float(x: float) -> str:
            try:
                xf = float(x)
            except Exception:
                return str(x)
            if abs(xf - round(xf)) < 1e-9:
                return str(int(round(xf)))
            return f"{xf:.2f}".rstrip("0").rstrip(".")

        # исходный dict из MainWindow (может быть None, например в reforge.py)
        orig_item_ref = orig_item if isinstance(orig_item, dict) else None

        # ---------- 5) блок карт ----------
        self._clear(self.cards_box)
        if not hide_card_slots:
            # лениво подгружаем статику слотов
            if self._pm_slot_empty is None:
                self._pm_slot_empty = self._static_image_pm("EquipmentToolTipCardEmpty")
            if self._pm_slot_equipped is None:
                self._pm_slot_equipped = self._static_image_pm("EquipmentToolTipCard")

            # сколько слотов у предмета (обычно 1 у экипа, 3 у оружия/копья)
            is_weapon_slots = self._is_weapon_or_spear(item, slot_key_eff)
            slot_count2 = 3 if is_weapon_slots else 1

            # нормализуем cards в список, чтобы можно было по индексу брать
            cards_seq: List[Tuple[Optional[int], str, str]] = []
            try:
                for c in (cards or []):
                    if isinstance(c, (tuple, list)):
                        icon_id = c[0] if len(c) > 0 else None
                        name = str(c[1]) if len(c) > 1 else ""
                        desc = str(c[2]) if len(c) > 2 else ""
                    else:
                        icon_id = None
                        name = str(c)
                        desc = ""
                    cards_seq.append((icon_id, name, desc))
            except Exception:
                cards_seq = []

            # Найти элементную карту и сохранить её иконку в исходный item
            if is_weapon_slots and cards_seq and orig_item_ref is not None:
                element_icon_id: Optional[int] = None
                for icon_id, name, desc in cards_seq:
                    if icon_id:
                        element_icon_id = _to_int(icon_id, 0)
                    break
                if element_icon_id:
                    try:
                        orig_item_ref["ElementIcon_Id"] = element_icon_id
                    except Exception:
                        pass

            cards_len = len(cards_seq)

            for idx in range(slot_count2):
                row = QHBoxLayout()
                row.setSpacing(6)

                icon_lbl = QLabel()
                icon_lbl.setScaledContents(False)

                card_tuple = cards_seq[idx] if idx < cards_len else None
                is_empty = (card_tuple is None)

                if card_tuple:
                    icon_id, card_name, card_desc = card_tuple

                    custom_pm = None
                    if is_weapon_slots and icon_id:
                        custom_pm = _pm(_to_int(icon_id, 0))

                    pm_slot = self._build_slot_pixmap(
                        has_card=True,
                        custom_pm=custom_pm,
                        w=CARD_ICON_W,
                        h=CARD_ICON_H,
                    )
                    if pm_slot:
                        icon_lbl.setPixmap(pm_slot)
                        icon_lbl.setFixedSize(pm_slot.size())

                    text_col = QVBoxLayout()
                    text_col.setContentsMargins(0, 0, 0, 0)
                    text_col.setSpacing(1)

                    name_lbl = QLabel(str(card_name))
                    name_lbl.setFont(self.stat.font())
                    name_lbl.setStyleSheet("color:#00d183;")
                    text_col.addWidget(name_lbl)

                    card_desc = (card_desc or "").replace("\r", "").strip()
                    if card_desc:
                        desc_lbl = QLabel()
                        desc_lbl.setWordWrap(True)
                        desc_lbl.setFont(self.stat.font())
                        desc_lbl.setTextFormat(Qt.RichText)
                        desc_lbl.setText(_stats_to_rich_with_yellow_prefix(card_desc))
                        text_col.addWidget(desc_lbl)

                else:
                    pm_slot = self._build_slot_pixmap(
                        has_card=False,
                        custom_pm=None,
                        w=CARD_ICON_W,
                        h=CARD_ICON_H,
                    )
                    if pm_slot:
                        icon_lbl.setPixmap(pm_slot)
                        icon_lbl.setFixedSize(pm_slot.size())

                    text_col = QVBoxLayout()
                    text_col.setContentsMargins(0, 0, 0, 0)
                    text_col.setSpacing(0)

                    name_lbl = QLabel("Слот для карты")
                    name_lbl.setFont(self.stat.font())
                    name_lbl.setStyleSheet("color:#bfbfbf;")
                    text_col.addWidget(name_lbl)

                row.addWidget(icon_lbl, 0, Qt.AlignVCenter if is_empty else Qt.AlignTop)
                row.addLayout(text_col, 1)
                self.cards_box.addLayout(row)

        # ---------- 6) основная стата / оружейные строки ----------
        atk_raw = _to_int(item.get("Attack"), 0)
        df_raw = _to_int(item.get("Defense"), 0)

        atk_base = _to_int(item.get("BaseAttack") or item.get("base_attack"), 0)
        df_base = _to_int(item.get("BaseDefense") or item.get("base_defense"), 0)

        show_atk = atk_base if atk_base > 0 else atk_raw
        show_df = df_base if df_base > 0 else df_raw

        eff_atk = atk_raw if atk_raw > 0 else show_atk
        eff_df = df_raw if df_raw > 0 else show_df

        is_weapon = self._is_weapon_or_spear(item, slot_key_eff)

        b_atk_explicit = _to_int(forge_bonus_atk or 0, 0)
        b_def_explicit = _to_int(forge_bonus_def or 0, 0)

        bonus_atk = max(0, b_atk_explicit)
        bonus_def = max(0, b_def_explicit)

        if level_for_calc > 0:
            if bonus_atk == 0 and bonus_def == 0:
                explicit = max(0, forge_bonus)
                if explicit > 0:
                    if is_weapon:
                        bonus_atk = explicit
                    elif df_raw > 0 and atk_raw <= 0:
                        bonus_def = explicit
                    else:
                        if df_raw >= atk_raw:
                            bonus_def = explicit
                        else:
                            bonus_atk = explicit
                else:
                    if atk_base > 0 and eff_atk > atk_base:
                        bonus_atk = eff_atk - atk_base
                    if df_base > 0 and eff_df > df_base:
                        bonus_def = eff_df - df_base
        else:
            if atk_base > 0 and eff_atk > atk_base:
                bonus_atk = eff_atk - atk_base
            if df_base > 0 and eff_df > df_base:
                bonus_def = eff_df - df_base

        lines: list[str] = []

        def _add_stat_line(kind: str, base: int, bonus: int) -> None:
            if base <= 0 and bonus <= 0:
                return
            head = "Атака: " if kind == "atk" else "Защита: "
            if bonus > 0:
                lines.append(f"{head}{base} <span style='color:{FORGE_GREEN};'>+ {bonus}</span>")
            else:
                lines.append(f"{head}{base}")

        if is_weapon:
            _add_stat_line("atk", show_atk, bonus_atk)
            _add_stat_line("def", show_df, bonus_def)
        else:
            _add_stat_line("def", show_df, bonus_def)
            _add_stat_line("atk", show_atk, bonus_atk)

        if lines:
            if any("<span" in ln for ln in lines):
                self.stat.setTextFormat(Qt.RichText)
                self.stat.setText("<br>".join(lines))
            else:
                self.stat.setTextFormat(Qt.PlainText)
                self.stat.setText("\n".join(lines))
            self.stat.show()
        else:
            self.stat.hide()

        # === скорость атаки и DPS для оружия ===
        if is_weapon:
            spd_str = self._get_attack_speed_for_item(item)
            self.spd.setTextFormat(Qt.PlainText)
            self.spd.setText(f"Скорость атаки: {spd_str}")
            self.spd.show()

            spd_val = _to_float_or_none(spd_str)
            formed_atk = float(max(0, int(show_atk or 0) + int(bonus_atk or 0)))

            if spd_val is None or formed_atk <= 0:
                self.dps.setTextFormat(Qt.PlainText)
                self.dps.setText("Урон в секунду: —")
            else:
                dps_val = formed_atk * float(spd_val)
                self.dps.setTextFormat(Qt.PlainText)
                self.dps.setText(f"Урон в секунду: {_fmt_float(dps_val)}")
            self.dps.show()
        else:
            self.spd.clear()
            self.spd.hide()
            self.dps.clear()
            self.dps.hide()

        # ---------- 7) forge-блок ----------
        self._clear(self.forge_box)
        if forge_hp_bonus > 0:
            lbl = QLabel(f"+{forge_hp_bonus} к Здоровью")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color:{FORGE_GREEN};")
            self.forge_box.addWidget(lbl)

        if allstat_effective > 0:
            lbl = QLabel(f"+{allstat_effective} ко всем параметрам")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color:{FORGE_GREEN};")
            self.forge_box.addWidget(lbl)

        # ---------- 8) бонусы предмета ----------
        base_bonus = self._get_bonus_list(item, bonus_lines)
        cleaned: list[str] = []
        for s in base_bonus:
            cleaned.append(s)

        self._clear(self.bon_box)
        if cleaned:
            for s in cleaned:
                lbl = QLabel(s)
                lbl.setWordWrap(True)
                self.bon_box.addWidget(lbl)

        # ---------- 9) печать ----------
        st = stamp if isinstance(stamp, dict) else {}

        # собираем данные печати
        stamp_name = (st.get("name") or st.get("Name") or "").strip()
        icon_id = st.get("icon_id") or st.get("HeaderIconImageId")

        bon_lines2 = (
                st.get("Bonuses")
                or st.get("BonusLines")
                or st.get("Effects")
                or []
        )

        import re

        def _add_plus_prefix(s: str) -> str:
            s = (s or "").strip()
            if not s:
                return s
            if s[0] in "+-":
                return s
            m = re.match(r"(\d+)(.*)", s)
            if m:
                return f"+{m.group(1)}{m.group(2)}"
            return s

        if isinstance(bon_lines2, (list, tuple)):
            lines2 = [str(x).strip() for x in bon_lines2 if str(x).strip()]
        elif bon_lines2:
            lines2 = [str(bon_lines2).strip()]
        else:
            lines2 = []

        lines2 = [_add_plus_prefix(s) for s in lines2]
        bon_text = "\n".join(lines2).strip()

        has_stamp_data = bool(stamp_name or icon_id or bon_text)

        if suppress_stamp_section or (not has_stamp_data):
            # печати нет -> просто скрываем секцию, ничего не пишем
            self.stamp_row_container.hide()
            self.stamp_icon.clear()
            self.stamp_icon.hide()
            self.stamp_name.clear()
            self.stamp_name.hide()
            self.stamp_desc.clear()
            self.stamp_desc.hide()
            # <<< FIX: НЕ выходим из функции, потому что ниже должен отрисоваться EquipmentElixir
        else:
            # печать есть -> показываем
            self.stamp_row_container.show()

            # имя: если нет имени, но есть иконка/бонусы — пишем просто "Печать"
            if stamp_name:
                self.stamp_name.setText(f"Печать {stamp_name}")
            else:
                self.stamp_name.setText("Печать")

            self.stamp_name.setStyleSheet(
                f"color:{color}; font-weight:700; background: transparent;"
            )
            self.stamp_name.show()

            pm2 = _pm(icon_id) if icon_id else None
            if pm2 and not pm2.isNull():
                pm2 = pm2.scaled(18, 18, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.stamp_icon.setPixmap(pm2)
                self.stamp_icon.show()
            else:
                self.stamp_icon.clear()
                self.stamp_icon.hide()

            if bon_text:
                self.stamp_desc.setStyleSheet(
                    f"color:{color}; background: transparent;"
                )
                self.stamp_desc.setText(bon_text)
                self.stamp_desc.show()
            else:
                self.stamp_desc.clear()
                self.stamp_desc.hide()

        # ---------- 10) временные улучшения (EquipmentElixir) ----------
        # <<< FIX: берём orig_item_ref если есть, потому что именно туда main_window вшивает Elixir
        self._render_elixir_section(orig_item_ref if orig_item_ref is not None else item)

    def _class_table_name(self) -> Optional[str]:
        """Определяем реальное имя таблицы классов (EquipmentClass / EqipmentClass / Equipment_Class)."""
        if hasattr(self, "_cls_tbl_cache"):
            return self._cls_tbl_cache

        conn = self._db_conn()
        name = None
        if conn:
            for cand in ("EquipmentClass", "EqipmentClass", "Equipment_Class"):
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

        self._cls_tbl_cache = name
        return name

    def _is_weapon_or_spear(self, item: dict | None, slot_key: str | None) -> bool:
        """Пытаемся надёжно понять, что предмет — оружие/копьё."""

        def _toi(v, d=0):
            try:
                return int(v)
            except Exception:
                return d

        it = item or {}
        # 1) по Id слота, если есть (твоя схема: 21 — weapon, 22 — spear)
        sid = _toi(it.get("Slot_Id") or it.get("SlotId") or it.get("EquipmentSlot_Id"))
        if sid in (21, 22):
            return True

        # 2) по ключу слота, если его передали
        if isinstance(slot_key, str) and slot_key.lower() in ("weapon", "spear"):
            return True

        # 3) эвристика: есть атака и это не щит/offhand
        atk = _toi(it.get("Attack"), 0)
        tname = str(it.get("TypeName") or "").lower()
        looks_shield = ("щит" in tname) or ("shield" in tname) or ("offhand" in tname)
        return atk > 0 and not looks_shield

    # ----- internal level / class from DB -----
    def _db_conn(self):
        """Удобный доступ к conn. Ищем и в _ctx_root, и по parent-цепочке."""

        def _try(obj):
            return getattr(getattr(obj, "data", None), "conn", None) if obj is not None else None

        # 1) сначала ctx_root (window() того виджета, по которому hover)
        conn = _try(getattr(self, "_ctx_root", None))
        if conn:
            return conn

        # 2) если кто-то присвоил self.main_window
        conn = _try(getattr(self, "main_window", None))
        if conn:
            return conn

        # 3) parent-цепочка
        w = self
        for _ in range(12):
            try:
                w = w.parent()
            except Exception:
                w = None
            if w is None:
                break
            conn = _try(w)
            if conn:
                return conn
            conn = _try(getattr(w, "main_window", None))
            if conn:
                return conn

        return None

    def _db_has_col(self, table: str, col: str) -> bool:
        """Проверяем, есть ли колонка `col` в таблице `table` (через PRAGMA table_info)."""
        conn = self._db_conn()
        if not conn:
            return False

        target = str(col).lower()
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        except Exception:
            return False

        for r in rows or []:
            # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
            try:
                name = str(r[1]).lower()
            except Exception:
                continue
            if name == target:
                return True
        return False

    def _get_attack_speed_for_item(self, item: dict | None) -> str:
        """
        Возвращает строку скорости атаки предмета.

        Приоритет:
        1) Equipment.AttackSpeed по Id из словаря предмета;
        2) поля AttackSpeed / AttackSpeedStr в самом item;
        3) '—', если ничего не нашли.
        """
        it = item or {}
        conn = self._db_conn()

        def _norm(v):
            if v is None:
                return None
            s = str(v).strip()
            return s or None

        # Пытаемся максимально надёжно вытащить Id экипировки
        equip_id = int(it.get("Id"))

        # 1) Пробуем взять AttackSpeed из таблицы Equipment
        if conn and equip_id:
            try:
                row = conn.execute(
                    "SELECT AttackSpeed FROM Equipment WHERE Id=? LIMIT 1",
                    (equip_id,),
                ).fetchone()
            except Exception:
                row = None

            if row is not None:
                if hasattr(row, "keys"):
                    val = _norm(row["AttackSpeed"])
                else:
                    val = _norm(row[0])
                if val is not None:
                    return val

        # 2) fallback — то, что уже есть в словаре предмета
        val = _norm(it.get("AttackSpeed"))
        if val is not None:
            return val

        # 3) ничего не нашли
        return "—"

    def _get_internal_level_for_item(self, item: dict | None) -> int:
        """
        Возвращает InternalLevel предмета.

        Приоритет:
        1) SELECT Equipment.InternalLevel FROM Equipment WHERE Id = (Equip_Id / Equipment_Id / Id ...)
        2) fallback: item["InternalLevel"], если есть
        3) fallback: Level / RequiredLevel / 1
        """

        def _to_int(v, d=0):
            try:
                return int(v)
            except Exception:
                return d

        it = item or {}
        conn = self._db_conn()

        # Пытаемся максимально надёжно вытащить Id экипировки
        equip_id = _to_int(
            it.get("Equip_Id")
            or it.get("EquipId")
            or it.get("Equipment_Id")
            or it.get("EquipmentId")
            or it.get("Id")
            or 0,
            0,
        )

        # 1) Пробуем вытащить InternalLevel из таблицы Equipment
        if conn and equip_id:
            try:
                row = conn.execute(
                    "SELECT InternalLevel FROM Equipment WHERE Id=? LIMIT 1",
                    (equip_id,),
                ).fetchone()
                if row is not None:
                    if hasattr(row, "keys"):
                        return _to_int(row["InternalLevel"], 1)
                    else:
                        return _to_int(row[0], 1)
            except Exception:
                # Если что-то пошло не так – просто пробуем fallback
                pass

        # 2) fallback – InternalLevel прямо в словаре предмета
        if isinstance(it, dict) and it.get("InternalLevel") is not None:
            return _to_int(it.get("InternalLevel"), 1)

        # 3) запасной вариант – обычный Level / RequiredLevel
        return _to_int(it.get("Level") or it.get("RequiredLevel") or 1, 1)

    def _class_letter_from_internal(self, internal_level: int) -> str:
        """
        Определяет класс (C/B/A) по таблице EquipmentClass:
        берём все записи, сортируем по Level и выбираем последнюю,
        у которой internal_level >= Level.
        """
        conn = self._db_conn()
        if not conn:
            return "—"

        try:
            ilvl = int(internal_level)
        except Exception:
            ilvl = 0
        if ilvl <= 0:
            ilvl = 1

        try:
            rows = conn.execute(
                "SELECT Name, Level FROM EquipmentClass ORDER BY Level"
            ).fetchall()
        except Exception:
            return "—"

        klass = "—"
        for r in rows or []:
            try:
                # поддержим и обычный tuple, и sqlite3.Row
                if hasattr(r, "keys"):
                    name = (r["Name"] or "").strip()
                    lvl_thr = int(r["Level"] or 0)
                else:
                    name = (r[0] or "").strip()
                    lvl_thr = int(r[1] or 0)
            except Exception:
                continue

            if not name:
                continue

            if ilvl >= lvl_thr:
                # запоминаем последний подходящий порог (A перекроет B и C)
                klass = name

        return klass or "—"

    def _forge_meta_from_item(self, item: dict | None) -> tuple[int, int, int, int, int]:
        """
        Достаём данные точки из item.
        Возвращаем (lvl, bonus, all_bonus, base_atk, base_def).
        """
        if not isinstance(item, dict):
            return 0, 0, 0, 0, 0

        def _toi(v, d=0):
            try:
                return int(v)
            except Exception:
                return d

        lvl = _toi(item.get("ForgeLevel") or item.get("forge_level"), 0)
        bonus = _toi(item.get("ForgeBonus") or item.get("forge_bonus"), 0)
        all_bonus = _toi(item.get("ForgeAllStatBonus") or item.get("forge_all_bonus"), 0)

        base_atk = _toi(item.get("BaseAttack") or item.get("base_attack") or item.get("Attack"), 0)
        base_def = _toi(item.get("BaseDefense") or item.get("base_defense") or item.get("Defense"), 0)

        return lvl, bonus, all_bonus, base_atk, base_def

    # ----- служебное -----
    def _build_slot_pixmap(
            self,
            has_card: bool,
            custom_pm: Optional[QPixmap],
            w: int,
            h: int,
    ) -> Optional[QPixmap]:
        """
        Общая логика построения пиксмапа слота карты.
        Используется и в шапке, и в списке карт.
        has_card=True  -> заполненный слот (элементная картинка или EquipmentToolTipCard)
        has_card=False -> пустой слот (EquipmentToolTipCardEmpty)
        """
        if has_card:
            pm = custom_pm
            if pm is None:
                if self._pm_slot_equipped is None:
                    self._pm_slot_equipped = self._static_image_pm("EquipmentToolTipCard")
                pm = self._pm_slot_equipped
        else:
            if self._pm_slot_empty is None:
                self._pm_slot_empty = self._static_image_pm("EquipmentToolTipCardEmpty")
            pm = self._pm_slot_empty

        if not pm or pm.isNull():
            return None

        pm_s = pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # на всякий случай гасим devicePixelRatio, чтобы не было сюрпризов на HiDPI
        try:
            pm_s.setDevicePixelRatio(1.0)
        except Exception:
            pass
        return pm_s

    def _slot_img_html(
            self,
            has_card: bool = False,
            w: int = CARD_ICON_W,
            h: int = CARD_ICON_H,
            custom_pm: Optional[QPixmap] = None,
            shift_y: int = 0,  # NEW: + вниз, - вверх
    ) -> str:
        """
        Маленькая иконка слота карты в заголовке, которая вставляется в QLabel через <img>.

        shift_y:
          +N -> опустить иконку (добавляем прозрачные пиксели сверху)
          -N -> поднять иконку (добавляем прозрачные пиксели снизу)
        """
        pm_s = self._build_slot_pixmap(has_card, custom_pm, w, h)
        if not pm_s:
            return ""

        try:
            sy = int(shift_y or 0)
        except Exception:
            sy = 0

        # ограничим, чтобы не улетело
        sy = max(-12, min(12, sy))

        top_pad = sy if sy > 0 else 0
        bot_pad = (-sy) if sy < 0 else 0
        h_total = pm_s.height() + top_pad + bot_pad

        pm_box = QPixmap(pm_s.width(), h_total)
        pm_box.fill(Qt.transparent)

        p = QPainter(pm_box)
        x = (pm_box.width() - pm_s.width()) // 2
        y = top_pad
        p.drawPixmap(x, y, pm_s)
        p.end()

        ba = QByteArray()
        buf = QBuffer(ba)
        if not buf.open(QBuffer.WriteOnly):
            return ""
        pm_box.save(buf, "PNG")
        buf.close()

        try:
            b64 = bytes(ba.toBase64()).decode("ascii")
        except Exception:
            return ""

        return f"<img width='{pm_box.width()}' height='{h_total}' src='data:image/png;base64,{b64}'>"

    def _static_image_pm(self, name: str) -> Optional[QPixmap]:
        """Берёт BLOB из StaticImage.Data по имени и возвращает QPixmap."""
        conn = self._db_conn()
        if not conn:
            return None
        try:
            row = conn.execute(
                "SELECT Data FROM StaticImage WHERE Name=? LIMIT 1",
                (name,),
            ).fetchone()
        except Exception:
            row = None
        if not row:
            return None

        blob = row["Data"] if hasattr(row, "keys") else row[0]
        if blob is None:
            return None
        # sqlite может вернуть memoryview
        if isinstance(blob, memoryview):
            blob = blob.tobytes()
        elif not isinstance(blob, (bytes, bytearray)):
            try:
                blob = bytes(blob)
            except Exception:
                return None

        pm = QPixmap()
        return pm if pm.loadFromData(blob) else None

    # =========================
    # Equipment Elixir (tooltip)
    # =========================
    def _static_image_pm_by_id(self, image_id: int) -> Optional[QPixmap]:
        """Берёт BLOB из StaticImage.Data по Id и возвращает QPixmap."""
        try:
            iid = int(image_id or 0)
        except Exception:
            iid = 0
        if iid <= 0:
            return None

        conn = self._db_conn()
        if not conn:
            return None

        try:
            row = conn.execute(
                "SELECT Data FROM StaticImage WHERE Id=? LIMIT 1",
                (int(iid),),
            ).fetchone()
        except Exception:
            row = None
        if not row:
            return None

        blob = row["Data"] if hasattr(row, "keys") else row[0]
        if blob is None:
            return None
        if isinstance(blob, memoryview):
            blob = blob.tobytes()
        elif not isinstance(blob, (bytes, bytearray)):
            try:
                blob = bytes(blob)
            except Exception:
                return None

        pm = QPixmap()
        return pm if pm.loadFromData(blob) else None

    def _ensure_elixir_ui(self) -> None:
        if getattr(self, "_elixir_container", None) is not None:
            return

        self._elixir_container = QWidget(self._panel)
        self._elixir_container.setObjectName("elixir_container")
        self._elixir_container.setStyleSheet("background: transparent;")

        root = QVBoxLayout(self._elixir_container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        # header row
        header = QWidget(self._elixir_container)
        h = QHBoxLayout(header)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        self._elixir_header_icon = QLabel()
        self._elixir_header_icon.setFixedSize(19, 21)
        self._elixir_header_icon.setScaledContents(True)

        self._elixir_header_text = QLabel("Временные улучшения:")
        try:
            f = QFont(self.title_name.font())
        except Exception:
            f = QFont()
        f.setPointSizeF(10)
        f.setBold(True)
        self._elixir_header_text.setFont(f)
        self._elixir_header_text.setStyleSheet("color:#ffd98a; font-weight:700;")

        h.addWidget(self._elixir_header_icon, 0, Qt.AlignVCenter)
        h.addWidget(self._elixir_header_text, 0, Qt.AlignVCenter)
        h.addItem(QSpacerItem(1, 1, QSizePolicy.Expanding, QSizePolicy.Minimum))
        root.addWidget(header)

        # lines
        self._elixir_lines_box = QVBoxLayout()
        self._elixir_lines_box.setContentsMargins(0, 0, 0, 0)
        self._elixir_lines_box.setSpacing(2)
        root.addLayout(self._elixir_lines_box)

        # вставляем перед req
        lay = self._panel_layout or (self._panel.layout() if self._panel else None)
        if lay is not None:
            try:
                idx = lay.indexOf(self.req)
            except Exception:
                idx = -1
            if idx >= 0:
                lay.insertWidget(idx, self._elixir_container)
            else:
                lay.addWidget(self._elixir_container)

        self._elixir_container.hide()

    def _hide_elixir_section(self) -> None:
        if getattr(self, "_elixir_container", None) is None:
            return
        try:
            self._clear(self._elixir_lines_box)
        except Exception:
            pass
        try:
            self._elixir_container.hide()
        except Exception:
            pass

    def _elixir_payloads_from_item(self, item: dict) -> list[dict]:
        """
        Поддержка:
          item["Elixir"] = dict
          item["_elixir"] = dict
          (если вдруг станет списком — тоже ок)
        """
        it = item or {}
        el = it.get("Elixir") or it.get("_elixir")

        src_list: list = []
        if isinstance(el, dict):
            src_list = [el]
        elif isinstance(el, (list, tuple)):
            src_list = list(el)
        else:
            return []

        out: list[dict] = []
        for e in src_list:
            if not isinstance(e, dict):
                continue
            try:
                eid = int(e.get("Id") or e.get("id") or 0)
            except Exception:
                eid = 0
            if eid <= 0:
                continue

            name = str(e.get("Name") or e.get("name") or "").strip()
            bonuses = e.get("Bonuses") or e.get("bonuses") or []
            if not isinstance(bonuses, list):
                try:
                    bonuses = list(bonuses)
                except Exception:
                    bonuses = []

            out.append({"Id": int(eid), "Name": name, "Bonuses": list(bonuses)})
        return out

    def _render_elixir_bonus_lines(self, el_payload: dict) -> list[str]:
        """
        Рендер бонусов EquipmentElixir через BonusType.Template:
          - {0} заменяем на Value
          - если до {0} нет текста -> подставляем +Value
        """
        conn = self._db_conn()
        if not conn:
            return []

        bonuses = el_payload.get("Bonuses") or []
        if not isinstance(bonuses, list) or not bonuses:
            return []

        # сортировка по OrderIndex
        try:
            bonuses_sorted = sorted(
                [b for b in bonuses if isinstance(b, dict)],
                key=lambda b: int(b.get("OrderIndex") or 0),
            )
        except Exception:
            bonuses_sorted = [b for b in bonuses if isinstance(b, dict)]

        type_ids: list[int] = []
        seen = set()
        for b in bonuses_sorted:
            try:
                tid = int(b.get("Type_Id") or b.get("TypeId") or 0)
            except Exception:
                tid = 0
            if tid > 0 and tid not in seen:
                seen.add(tid)
                type_ids.append(tid)

        if not type_ids:
            return []

        tmpl_col = _bonus_template_col_local(conn)
        ph = ",".join("?" for _ in type_ids)

        try:
            rows = conn.execute(
                f'SELECT Id, {tmpl_col} AS Tmpl FROM BonusType WHERE Id IN ({ph})',
                tuple(int(x) for x in type_ids),
            ).fetchall()
        except Exception:
            rows = []

        tmpl_map: dict[int, str] = {}
        for r in rows or []:
            try:
                if hasattr(r, "keys"):
                    tid = int(r["Id"] or 0)
                    tmpl = str(r["Tmpl"] or "")
                else:
                    tid = int(r[0] or 0)
                    tmpl = str(r[1] or "")
            except Exception:
                continue
            if tid > 0:
                tmpl_map[tid] = tmpl

        out: list[str] = []
        for b in bonuses_sorted:
            try:
                tid = int(b.get("Type_Id") or b.get("TypeId") or 0)
                val = int(b.get("Value") or 0)
            except Exception:
                continue
            if tid <= 0:
                continue

            tmpl = (tmpl_map.get(tid) or "").strip()
            if not tmpl:
                continue

            if "{0}" in tmpl:
                before = tmpl.split("{0}", 1)[0]
                val_s = str(val)
                if before.strip() == "":
                    if not val_s.startswith(("+", "-")):
                        val_s = f"+{val_s}"
                try:
                    line = tmpl.format(val_s)
                except Exception:
                    line = tmpl.replace("{0}", val_s)
            else:
                line = tmpl

            line = str(line).strip()
            if line:
                out.append(line)

        return out

    def _render_elixir_section(self, item: dict) -> None:
        payloads = self._elixir_payloads_from_item(item)
        if not payloads:
            self._hide_elixir_section()
            return

        self._ensure_elixir_ui()

        # чистим старые строки
        try:
            self._clear(self._elixir_lines_box)
        except Exception:
            pass

        # базовый цвет (как в QFrame#panel: QLabel { color:#ddd; ... })
        base_css = "color:#ddd; background:transparent;"

        # если у реальных бонусов есть явный color в stylesheet — используем его
        try:
            sample_lbl = None
            for i in range(self.bon_box.count()):
                it_l = self.bon_box.itemAt(i)
                w = it_l.widget() if it_l else None
                if isinstance(w, QLabel):
                    sample_lbl = w
                    break

            if sample_lbl is not None:
                ss = (sample_lbl.styleSheet() or "").strip()
                ss_l = ss.lower()
                if "color" in ss_l:
                    # гарантируем прозрачный фон
                    if "background" not in ss_l:
                        if ss and not ss.rstrip().endswith(";"):
                            ss += ";"
                        ss += " background:transparent;"
                    base_css = ss
        except Exception:
            pass

        # оранжевый как у оранжевой печати
        orange = STAMP_COLORS.get("orange", "#FF9600")
        orange_css = f"color:{orange}; background:transparent;"

        # header icon: StaticImage.Id = 13 (19x21)
        pm = self._static_image_pm_by_id(13)
        if pm and not pm.isNull():
            pm_s = pm.scaled(19, 21, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._elixir_header_icon.setPixmap(pm_s)
            self._elixir_header_icon.show()
        else:
            self._elixir_header_icon.clear()
            self._elixir_header_icon.hide()

        # Заголовок (белый как бонусы)
        self._elixir_header_text.setText("Временные улучшения:")
        self._elixir_header_text.setStyleSheet(base_css + " font-weight:700;")
        self._elixir_header_text.show()

        for el in payloads:
            nm = str(el.get("Name") or "").strip()
            if nm:
                name_lbl = QLabel(f"{nm} :")
                name_lbl.setWordWrap(True)
                name_lbl.setStyleSheet(base_css + " font-weight:600;")
                self._elixir_lines_box.addWidget(name_lbl)

            # бонусы эликсира — оранжевые
            for ln in (self._render_elixir_bonus_lines(el) or []):
                lbl = QLabel(str(ln))
                lbl.setWordWrap(True)
                lbl.setStyleSheet(orange_css)
                self._elixir_lines_box.addWidget(lbl)

        self._elixir_container.show()

    def _reset(self) -> None:
        # убираем все ранее вставленные _Separator
        self._clear_separators()

        # заголовок
        self.title_prefix.clear()
        self.title_prefix.hide()
        self.title_prefix.setStyleSheet("color:#ddd; font-weight:700;")

        self.title_name.clear()
        self.title_name.setStyleSheet("color:#ddd; font-weight:700;")

        if hasattr(self, "title_slot") and self.title_slot is not None:
            self.title_slot.clear()
            self.title_slot.hide()

        # подзаголовок
        self.sub.clear()

        # содержимое блоков
        self._clear(self.cards_box)
        if hasattr(self, "forge_box"):
            self._clear(self.forge_box)
        self._clear(self.bon_box)

        for lbl in (self.stat, self.spd, self.dps):
            lbl.clear()
            lbl.hide()

        # секция печати полностью в ноль
        self.stamp_icon.clear()
        self.stamp_icon.hide()
        self.stamp_name.clear()
        self.stamp_name.hide()
        self.stamp_desc.clear()
        self.stamp_desc.hide()
        self.stamp_name.setStyleSheet("")
        self.stamp_desc.setStyleSheet("")
        self.stamp_row_container.hide()

        # временные улучшения (эликсир)
        self._hide_elixir_section()

        # требования
        self.req.clear()

        self.setMinimumSize(345, 0)
        self.setMaximumSize(16777215, 16777215)

    # ----- работа с динамическими разделителями -----
    def _clear_separators(self) -> None:
        """Удаляет все _Separator из основного лейаута панели."""
        lay = self._panel_layout or self._panel.layout()
        if not lay:
            return

        for i in reversed(range(lay.count())):
            item = lay.itemAt(i)
            w = item.widget()
            if w is not None and isinstance(w, _Separator):
                lay.takeAt(i)
                try:
                    w.hide()
                except Exception:
                    pass
                try:
                    w.setParent(None)
                except Exception:
                    pass
                try:
                    w.deleteLater()
                except Exception:
                    pass

    def _commit_size(self):
        """
        Финально пересчитывает размер анкеты.

        Важно:
        - ширину не трогаем динамически;
        - высоту считаем по фактическому sizeHint;
        - не берём max из разных sizeHint, потому что это раздувает окно
          и Qt начинает растягивать промежутки между блоками.
        """
        try:
            if self._panel_layout is not None:
                self._panel_layout.setContentsMargins(16, 12, 16, 12)
                self._panel_layout.setSpacing(2)
        except Exception:
            pass

        try:
            if self.forge_box is not None:
                self.forge_box.setSpacing(1)
        except Exception:
            pass

        try:
            if self.bon_box is not None:
                self.bon_box.setSpacing(1)
        except Exception:
            pass

        try:
            if self.cards_box is not None:
                self.cards_box.setSpacing(2)
        except Exception:
            pass

        try:
            if self.stamp_row is not None:
                self.stamp_row.setSpacing(4)
        except Exception:
            pass

        try:
            if getattr(self, "_elixir_lines_box", None) is not None:
                self._elixir_lines_box.setSpacing(1)
        except Exception:
            pass

        try:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
        except Exception:
            pass

        try:
            if self._panel is not None:
                self._panel.setMinimumHeight(0)
                self._panel.setMaximumHeight(16777215)
        except Exception:
            pass

        target_w = 345
        content_w = max(1, target_w - 32)

        try:
            self.setFixedWidth(target_w)
        except Exception:
            pass

        try:
            if self._panel is not None:
                self._panel.setFixedWidth(target_w)
        except Exception:
            pass

        try:
            self.title_name.setMaximumWidth(content_w)
        except Exception:
            pass

        try:
            for lab in self.findChildren(QLabel):
                lab.setMinimumHeight(0)
                lab.setMaximumHeight(16777215)
                lab.setContentsMargins(0, 0, 0, 0)
                lab.setMargin(0)
                lab.setIndent(0)

                if lab.wordWrap():
                    lab.setMaximumWidth(content_w)

                lab.updateGeometry()
        except Exception:
            pass

        lay = self.layout()
        if lay:
            try:
                lay.invalidate()
                lay.activate()
            except Exception:
                pass

        if self._panel and self._panel.layout():
            try:
                self._panel.layout().invalidate()
                self._panel.layout().activate()
            except Exception:
                pass

        try:
            self.updateGeometry()
            if self._panel is not None:
                self._panel.updateGeometry()
        except Exception:
            pass

        #h = self.sizeHint().height() + 4
        #h = min(h, 800)
        #self.setFixedHeight(h)

        try:
            platform_name = str(QApplication.platformName()).lower()
        except Exception:
            platform_name = ""

        if "windows" in platform_name:
            h = self.sizeHint().height() + 4
        else:
            h_candidates = []

            try:
                h_candidates.append(int(self.sizeHint().height()))
            except Exception:
                pass

            try:
                if self._panel is not None:
                    h_candidates.append(int(self._panel.sizeHint().height()))
            except Exception:
                pass

            try:
                if self._panel is not None and self._panel.layout() is not None:
                    h_candidates.append(int(self._panel.layout().sizeHint().height()))
            except Exception:
                pass

            h = max(h_candidates) + 4 if h_candidates else 40

        #h = max(40, min(int(h), 800))
        #self.setFixedHeight(h)

        # Не даём позднему пересчёту на Linux схлопнуть анкету,
        # если первый расчёт уже дал нормальную высоту.
        try:
            min_h = int(getattr(self, "_tip_min_height_this_show", 0) or 0)
        except Exception:
            min_h = 0

        h = max(40, int(h))

        if min_h > 0:
            h = max(h, min_h)

        h = min(h, 900)
        self.setFixedHeight(h)

    #def _commit_size(self):
    #    lay = self.layout()
    #    if lay:
    #        lay.activate()
    #    if self._panel and self._panel.layout():
    #        self._panel.layout().activate()
    #    h = self.sizeHint().height() + 10
    #    # без жёсткого минимального порога, только верхний:
    #    h = min(h, 800)
    #    self.setFixedHeight(h)

    def paintEvent(self, event):
        # Для WA_TranslucentBackground: обязательно чистим альфа-буфер,
        # иначе остаются "фантомные" пиксели при частых repaint/relayout.
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.end()
        # super().paintEvent(event) намеренно не зовём:
        # фон рисует _panel, а верхний виджет должен быть полностью прозрачным.

    @staticmethod
    def _clear(layout: QVBoxLayout):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w:
                try:
                    w.hide()
                except Exception:
                    pass
                # КЛЮЧЕВО: отцепляем сразу, чтобы не было фантомных “строк”
                try:
                    w.setParent(None)
                except Exception:
                    pass
                try:
                    w.deleteLater()
                except Exception:
                    pass
            else:
                ch = it.layout()
                if ch:
                    EquipmentInfoWindow._clear(ch)
                    # и сам layout тоже просим удалить
                    try:
                        ch.deleteLater()
                    except Exception:
                        pass


