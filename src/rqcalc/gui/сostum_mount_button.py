#сostum_mount_button.py
from __future__ import annotations

from typing import Optional
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QRect, QSize, QTimer
from PySide6.QtGui import QAction, QPixmap, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QMenu, QWidget, QWidgetAction, QLabel, QGridLayout,
    QScrollArea, QVBoxLayout, QFrame, QScrollBar, QHBoxLayout
)

# меню выбора предметов (item_choose.png)
from .choose_menu_all import ChooseItemMenu, ItemChooseConfig

# бонусные строки как в main/reforge (если таблицы есть)
try:
    from .weapon_equipment_button import _render_bonus_lines as _render_bonus_lines_helper  # type: ignore
except Exception:
    _render_bonus_lines_helper = None  # type: ignore

# --- пары костюмов (мужской_id, женский_id) ---
_COSTUME_PAIRS = [
    (472, None), (473, None), (474, 475), (None, 476), (981, 477), (None, 478),
    (816, 817), (820, 818), (821, 819), (822, 823), (825, 824), (827, 826),
    (975, 983), (976, 984), (978, 987), (979, 992), (980, 982), (None, 985),
    (977, 986), (994, 988), (995, 989), (996, 990), (997, None), (998, 991),
]
_COUNTERPART: dict[int, int] = {}
for _m, _f in _COSTUME_PAIRS:
    if _m is not None and _f is not None:
        _COUNTERPART[int(_m)] = int(_f)
        _COUNTERPART[int(_f)] = int(_m)


def _pm_from_bytes(data: Optional[bytes]) -> Optional[QPixmap]:
    if not data:
        return None
    pm = QPixmap()
    return pm if pm.loadFromData(data) else None


def _find_scroll_dir() -> Path:
    candidates = [
        Path.cwd() / "resources" / "helper_buttons",
        Path(__file__).resolve().parents[2] / "resources" / "helper_buttons",
        Path(__file__).resolve().parents[1] / "resources" / "helper_buttons",
        Path(__file__).resolve().parents[0] / "resources" / "helper_buttons",
    ]
    for c in candidates:
        if (c / "scroll_up.png").exists() and (c / "scroll_mid.png").exists() and (c / "scroll_down.png").exists():
            return c
    return candidates[0]

def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


class _ActivateBonusToggle(QWidget):
    """
    Маленький квадратик с галочкой в правом верхнем углу слота.

    Появляется только если у экипированного предмета есть EquipmentBonus с Activate != NULL.
    Галочка управляет применением только тех EquipmentBonus, у которых Activate = 1
    (см. characteristics_math.py).
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

        owner = self.parentWidget()
        if owner is None:
            return super().mousePressEvent(ev)

        try:
            it = self._get_selected_item(self._slot_key)
        except Exception:
            it = None

        if not isinstance(it, dict) or not it:
            return super().mousePressEvent(ev)

        # toggle
        new_checked = not bool(it.get("_activate_checked", False))
        it["_activate_checked"] = bool(new_checked)
        self._checked = bool(new_checked)

        # просим пересчитать статы (и обновить UI)
        try:
            fn = getattr(owner, "refresh_stats_panel", None)
            if callable(fn):
                fn()
        except Exception:
            pass

        # иногда UI обновляется через отдельные методы
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

class ImageVScrollBar(QWidget):
    """
    Кастомный вертикальный скроллбар картинками:
      scroll_up.png, scroll_mid.png, scroll_down.png
    Реальный QScrollBar скрыт.
    """
    def __init__(self, bar: QScrollBar, img_dir: Path, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.bar = bar
        self.img_dir = img_dir

        self.up_pm = QPixmap(str(img_dir / "scroll_up.png"))
        self.mid_pm = QPixmap(str(img_dir / "scroll_mid.png"))
        self.dn_pm = QPixmap(str(img_dir / "scroll_down.png"))

        self.btn_h = self.up_pm.height() if not self.up_pm.isNull() else 18
        self.track_w = self.up_pm.width() if not self.up_pm.isNull() else 12

        self.setFixedWidth(self.track_w)
        self.setMouseTracking(True)

        self._dragging = False
        self._drag_off = 0
        self._hover = QPoint(-1, -1)

        self.bar.setVisible(False)

        try:
            self.bar.valueChanged.connect(self.update)
            self.bar.rangeChanged.connect(self.update)
        except Exception:
            pass

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.track_w, 120)

    def _track_rect(self) -> QRect:
        return QRect(0, self.btn_h, self.track_w, max(0, self.height() - 2 * self.btn_h))

    def _handle_rect(self) -> QRect:
        tr = self._track_rect()
        rng = max(1, self.bar.maximum() - self.bar.minimum())
        h = max(22, int(tr.height() * (self.bar.pageStep() / max(1, (rng + self.bar.pageStep())))))
        usable = max(1, tr.height() - h)
        frac = (self.bar.value() - self.bar.minimum()) / rng
        y = int(tr.top() + usable * frac)
        return QRect(0, y, self.track_w, h)

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        up_r = QRect(0, 0, self.track_w, self.btn_h)
        if not self.up_pm.isNull():
            p.drawPixmap(up_r, self.up_pm)

        dn_r = QRect(0, self.height() - self.btn_h, self.track_w, self.btn_h)
        if not self.dn_pm.isNull():
            p.drawPixmap(dn_r, self.dn_pm)

        tr = self._track_rect()
        if not self.mid_pm.isNull() and tr.height() > 0:
            y = tr.top()
            while y < tr.bottom():
                h = min(self.mid_pm.height(), tr.bottom() - y + 1)
                src = QRect(0, 0, self.mid_pm.width(), h)
                dst = QRect(0, y, self.track_w, h)
                p.drawPixmap(dst, self.mid_pm, src)
                y += h

        hr = self._handle_rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 70))
        p.drawRoundedRect(hr.adjusted(2, 2, -2, -2), 4, 4)
        p.end()

    def mouseMoveEvent(self, ev):  # noqa: N802
        self._hover = ev.pos()
        if self._dragging:
            tr = self._track_rect()
            hr = self._handle_rect()
            h = hr.height()
            usable = max(1, tr.height() - h)
            y = min(tr.bottom() - h + 1, max(tr.top(), ev.pos().y() - self._drag_off))
            frac = (y - tr.top()) / usable
            rng = max(1, self.bar.maximum() - self.bar.minimum())
            self.bar.setValue(int(self.bar.minimum() + rng * frac))
        self.update()

    def leaveEvent(self, _):  # noqa: N802
        self._hover = QPoint(-1, -1)
        self.update()

    def mousePressEvent(self, ev):  # noqa: N802
        if ev.button() != Qt.LeftButton:
            return
        up_r = QRect(0, 0, self.width(), self.btn_h)
        dn_r = QRect(0, self.height() - self.btn_h, self.width(), self.btn_h)
        hr = self._handle_rect()
        tr = self._track_rect()

        if up_r.contains(ev.pos()):
            if self.bar.value() > self.bar.minimum():
                self.bar.triggerAction(QScrollBar.SliderSingleStepSub)
        elif dn_r.contains(ev.pos()):
            if self.bar.value() < self.bar.maximum():
                self.bar.triggerAction(QScrollBar.SliderSingleStepAdd)
        elif hr.contains(ev.pos()):
            self._dragging = True
            self._drag_off = ev.pos().y() - hr.top()
        elif tr.contains(ev.pos()):
            if ev.pos().y() < hr.top():
                self.bar.triggerAction(QScrollBar.SliderPageStepSub)
            else:
                self.bar.triggerAction(QScrollBar.SliderPageStepAdd)
        self.update()

    def mouseReleaseEvent(self, _):  # noqa: N802
        self._dragging = False
        self.update()

    def wheelEvent(self, ev):  # noqa: N802
        dy = ev.angleDelta().y()
        if dy > 0:
            self.bar.triggerAction(QScrollBar.SliderSingleStepSub)
        if dy < 0:
            self.bar.triggerAction(QScrollBar.SliderSingleStepAdd)


class CostumeController:
    """
    Type_Id=14 (costume). Показывает ТОЛЬКО то, что добавлено в Коллекции:
      MainWindow._collection_window.menu._in_col_set  (set CollectedItem.Id)
    Переводим CollectedItem.Id -> Equipment_Id через CollectedItem (Group_Id=1).
    """
    SLOT_KEY = "costume"
    TYPE_ID_COSTUME = 14
    COLLECTION_GROUP_ID = 1
    TYPE_NAME = "Костюм"

    def __init__(self, parent_widget, data, get_gender_id, on_pick, on_clear):
        self.parent = parent_widget
        self.data = data
        self.get_gender_id = get_gender_id
        self.on_pick = on_pick
        self.on_clear = on_clear

        self._current_gender = int(self.get_gender_id())
        self._current_costume_id: Optional[int] = None

        cols = {str(r[1]) for r in self.data.conn.execute("PRAGMA table_info(Equipment)").fetchall()}
        self._has_costume_image = ("CostumeImage_Id" in cols)

        def _get_selected_item(k: str):
            try:
                sel = getattr(self.parent, "_selected_items", None) or {}
                return sel.get(str(k))
            except Exception:
                return None

        self._activate_toggle: Optional[_ActivateBonusToggle] = None
        try:
            self._activate_toggle = _ActivateBonusToggle(self.parent, self.SLOT_KEY, self.data, _get_selected_item)
            QTimer.singleShot(0, self._activate_toggle.sync)
        except Exception:
            self._activate_toggle = None

    def show_menu(self, global_pos: QPoint) -> Optional[QMenu]:
        gender_id = int(self.get_gender_id() or 0)
        items = self._fetch_costumes_by_gender(gender_id)

        m = QMenu(self.parent)

        # --- ВАЖНО: делаем QMenu реально прозрачным окном ---
        try:
            m.setAttribute(Qt.WA_TranslucentBackground, True)
            m.setAttribute(Qt.WA_NoSystemBackground, True)
            m.setAutoFillBackground(False)
            m.setWindowFlag(Qt.FramelessWindowHint, True)
            m.setWindowFlag(Qt.NoDropShadowWindowHint, True)
        except Exception:
            pass

        m.setStyleSheet(
            "QMenu{background: transparent; border: 0px; padding:0px; margin:0px;}"
            "QMenu::item{background: transparent; padding:0px; margin:0px;}"
            "QMenu::separator{height:0px; margin:0px; padding:0px;}"
        )

        # -----------------------------
        # ПУСТОЙ СПИСОК: рисуем QLabel
        # -----------------------------
        if not items:
            cfg = ItemChooseConfig()
            #cfg.block_bg_path = "resources/choose_menu/costum_block.png"
            #cfg.block_size = (499, 89)

            # (не обязательно для пустого, но оставляем, чтобы конфиг был тот же)
            #dx = 0
            #dy = -30
            #x, y, w, h = cfg.icon_rect
            #cfg.icon_rect = (x + dx, y + dy, w, h)
            #x, y, w, h = cfg.name_rect
            #cfg.name_rect = (x + dx, y + dy, w, h)
            #x, y, w, h = cfg.base_stat_rect
            #cfg.base_stat_rect = (x + dx, y + dy, w, h)
            #x, y, w, h = cfg.req_level_rect
            #cfg.req_level_rect = (x + dx, y + dy, w, h)
            #x, y, w, h = cfg.bonuses_rect
            #cfg.bonuses_rect = (x + dx, y + dy, w, h)

            menu_widget = ChooseItemMenu(m, config=cfg)

            # --- ВАЖНО: прозрачные внутренности ---
            try:
                menu_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                menu_widget.setAttribute(Qt.WA_NoSystemBackground, True)
                menu_widget.setAutoFillBackground(False)
                menu_widget.setStyleSheet("background: transparent;")

                area = getattr(menu_widget, "_area", None)
                if area is not None:
                    area.setStyleSheet(
                        "QScrollArea{background: transparent; border:0px;}"
                        "QScrollArea>QWidget{background: transparent;}"
                    )
                    try:
                        area.viewport().setAutoFillBackground(False)
                        area.viewport().setStyleSheet("background: transparent;")
                    except Exception:
                        pass

                cont = getattr(menu_widget, "_cont", None)
                if cont is not None:
                    cont.setAutoFillBackground(False)
                    cont.setStyleSheet("background: transparent;")
            except Exception:
                pass

            # обязательно вызвать set_entries (чтобы корректно настроились скролл/фильтр),
            # но pick нам не нужен
            def _noop_pick(_item: dict) -> None:
                return

            menu_widget.set_entries(
                entries=[],
                on_pick=_noop_pick,
                on_hover_enter=None,
                on_hover_leave=None,
                focus_search=False,
            )

            # ⬇⬇⬇ ВОТ ЭТО ТЫ МЕНЯЕШЬ, ЧТОБЫ ДВИГАТЬ НАДПИСЬ ⬇⬇⬇
            EMPTY_MSG_RECT = (17, 210, 499, 30)  # x, y, w, h
            msg = QLabel(menu_widget)
            msg.setGeometry(*EMPTY_MSG_RECT)
            msg.setText("(Добавь костюмы в Коллекцию)")
            msg.setAlignment(Qt.AlignCenter)
            msg.setWordWrap(True)
            msg.setStyleSheet("background: transparent; color:#eaeaea; font-weight:600;")
            msg.raise_()
            msg.show()

            # поиск можно отключить
            try:
                menu_widget.search_edit.setEnabled(False)
                menu_widget.search_edit.setText("")
            except Exception:
                pass

            wa = QWidgetAction(m)
            wa.setDefaultWidget(menu_widget)
            m.addAction(wa)

            m.popup(QPoint(global_pos))
            return m

        # уровень персонажа (нужен для MulFormula_Id=16 / armorBL в бонусах, если есть)
        char_lvl = None
        try:
            spin = getattr(self.parent, "level_spin", None) or getattr(self.parent, "lvl_spin", None)
            if spin is not None and hasattr(spin, "value"):
                char_lvl = int(spin.value())
        except Exception:
            char_lvl = None

        conn = getattr(self.data, "conn", None)

        # добираем Level/Attack/Defense одной пачкой (чтобы в блоке было чем заполнить)
        extra: dict[int, dict] = {}
        try:
            ids = [int(it.get("Id") or 0) for it in items if int(it.get("Id") or 0) > 0]
            if conn is not None and ids:
                qm = ",".join("?" for _ in ids)
                rows = conn.execute(
                    f"SELECT Id, Level, Attack, Defense FROM Equipment WHERE Id IN ({qm})",
                    tuple(ids),
                ).fetchall()
                for r in rows or []:
                    try:
                        eid = int(r["Id"]) if hasattr(r, "keys") else int(r[0])
                        lvl = int((r["Level"] if hasattr(r, "keys") else r[1]) or 0)
                        atk = int((r["Attack"] if hasattr(r, "keys") else r[2]) or 0)
                        deff = int((r["Defense"] if hasattr(r, "keys") else r[3]) or 0)
                    except Exception:
                        continue
                    extra[eid] = {"Level": lvl, "Attack": atk, "Defense": deff}
        except Exception:
            extra = {}

        # костюмный блок
        cfg = ItemChooseConfig()
        cfg.block_bg_path = "resources/choose_menu/item_block.png"
        cfg.block_size = (499, 89)

        # --- твоя подгонка разметки ---
        dx = 0
        dy = 0
        x, y, w, h = cfg.icon_rect
        cfg.icon_rect = (x + dx, y + dy, w, h)
        x, y, w, h = cfg.name_rect
        cfg.name_rect = (x + dx, y + dy, w, h)
        x, y, w, h = cfg.base_stat_rect
        cfg.base_stat_rect = (x + dx, y + dy, w, h)
        x, y, w, h = cfg.req_level_rect
        cfg.req_level_rect = (x + dx, y + dy, w, h)
        x, y, w, h = cfg.bonuses_rect
        cfg.bonuses_rect = (x + dx, y + dy, w, h)

        menu_widget = ChooseItemMenu(m, config=cfg)

        # --- ВАЖНО: делаем прозрачными внутренности (viewport часто красит фон) ---
        try:
            menu_widget.setAttribute(Qt.WA_TranslucentBackground, True)
            menu_widget.setAttribute(Qt.WA_NoSystemBackground, True)
            menu_widget.setAutoFillBackground(False)
            menu_widget.setStyleSheet("background: transparent;")

            area = getattr(menu_widget, "_area", None)
            if area is not None:
                area.setStyleSheet(
                    "QScrollArea{background: transparent; border:0px;}"
                    "QScrollArea>QWidget{background: transparent;}"
                )
                try:
                    area.viewport().setAutoFillBackground(False)
                    area.viewport().setStyleSheet("background: transparent;")
                except Exception:
                    pass

            cont = getattr(menu_widget, "_cont", None)
            if cont is not None:
                cont.setAutoFillBackground(False)
                cont.setStyleSheet("background: transparent;")
        except Exception:
            pass

        entries: list[dict] = []
        for it in items:
            item_full = dict(it)
            eid = int(item_full.get("Id") or 0)

            if eid in extra:
                item_full.update(extra[eid])

            icon_id = item_full.get("Image_Id")
            icon_pm = _pm_from_bytes(self.data.get_image_bytes(icon_id)) if icon_id is not None else None

            bonus_lines: list[str] = []
            if conn is not None and _render_bonus_lines_helper:
                try:
                    bonus_lines = _render_bonus_lines_helper(conn, int(eid), char_level=char_lvl) or []
                except Exception:
                    bonus_lines = []

            entries.append({"item": item_full, "bonuses": bonus_lines, "icon_pm": icon_pm})

        def _pick(item_payload: dict) -> None:
            try:
                self._apply_pick(item_payload)
            finally:
                try:
                    m.close()
                except Exception:
                    pass

        menu_widget.set_entries(
            entries=entries,
            on_pick=_pick,
            on_hover_enter=None,
            on_hover_leave=None,
            focus_search=True,
        )

        wa = QWidgetAction(m)
        wa.setDefaultWidget(menu_widget)
        m.addAction(wa)

        m.popup(QPoint(global_pos))
        return m

    def on_gender_changed(self, gender_id: int):
        self._current_gender = int(gender_id)
        if self._current_costume_id is None:
            return

        mapped = _COUNTERPART.get(int(self._current_costume_id))
        if mapped:
            item = self._fetch_costume_item(int(mapped))
            if item:
                self._apply_pick(item)
                return

        self._clear_selection()

    def _clear_selection(self) -> None:
        self._current_costume_id = None
        self.on_clear(self.SLOT_KEY)

        try:
            if self._activate_toggle is not None:
                QTimer.singleShot(0, self._activate_toggle.sync)
        except Exception:
            pass

    def _build_card_widget(self, menu: QMenu, item: dict) -> QWidget:
        w = QWidget(menu)
        w.setObjectName("costumeCard")
        w.setAttribute(Qt.WA_Hover, True)
        w.setAttribute(Qt.WA_StyledBackground, True)
        w.setMouseTracking(True)

        lay = QGridLayout(w)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(2)

        icon_lbl = QLabel(w)
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setScaledContents(True)
        icon_lbl.setStyleSheet("background: transparent;")

        cid = item.get("Image_Id")
        pm = _pm_from_bytes(self.data.get_image_bytes(cid)) if cid is not None else None
        if pm:
            icon_lbl.setPixmap(pm)
        lay.addWidget(icon_lbl, 0, 0, 2, 1)

        name_lbl = QLabel(item.get("Name", ""), w)
        name_lbl.setStyleSheet("background: transparent; color:#fff; font-weight:600;")
        lay.addWidget(name_lbl, 0, 1, 1, 1)

        def _choose_and_close(_ev, _item=item, _menu=menu):
            self._apply_pick(_item)
            _menu.close()

        w.mouseReleaseEvent = _choose_and_close
        return w

    def _apply_pick(self, item: dict):
        self._current_costume_id = int(item["Id"])
        payload = {
            "Id": int(item["Id"]),
            "Name": item.get("Name", ""),
            "Image_Id": item.get("CostumeImage_Id"),  # силуэт
            "Icon_Image_Id": item.get("Image_Id"),  # иконка слота
            "CostumeImage_Id": item.get("Image_Id"),  # совместимость
            "Type_Id": self.TYPE_ID_COSTUME,
            "TypeName": self.TYPE_NAME,

            # флаг "галочки" (по умолчанию выключено)
            "_activate_checked": False,
        }
        self.on_pick(self.SLOT_KEY, payload)

        try:
            if self._activate_toggle is not None:
                QTimer.singleShot(0, self._activate_toggle.sync)
        except Exception:
            pass

    def _allowed_equipment_ids_from_collection(self) -> set[int]:
        cw = getattr(self.parent, "_collection_window", None)
        menu = getattr(cw, "menu", None) if cw is not None else None
        in_col = getattr(menu, "_in_col_set", None)
        if not isinstance(in_col, set) or not in_col:
            return set()

        conn = getattr(self.data, "conn", None)
        if conn is None:
            return set()

        ids = [int(x) for x in in_col if int(x) > 0]
        if not ids:
            return set()

        out: set[int] = set()
        step = 900
        for i in range(0, len(ids), step):
            chunk = ids[i:i + step]
            qm = ",".join("?" for _ in chunk)
            try:
                rows = conn.execute(
                    f"SELECT Equipment_Id FROM CollectedItem WHERE Group_Id=? AND Id IN ({qm}) AND Equipment_Id IS NOT NULL",
                    (int(self.COLLECTION_GROUP_ID), *chunk),
                ).fetchall()
            except Exception:
                rows = []

            for r in rows or []:
                try:
                    v = r["Equipment_Id"] if hasattr(r, "keys") else r[0]
                    eid = int(v or 0)
                except Exception:
                    eid = 0
                if eid > 0:
                    out.add(eid)

        return out

    def _fetch_costumes_by_gender(self, gender_id: int) -> list[dict]:
        allowed = self._allowed_equipment_ids_from_collection()
        if not allowed:
            return []

        if self._has_costume_image:
            sql = """
                SELECT Id, Name, Image_Id, CostumeImage_Id
                FROM Equipment
                WHERE Type_Id = ? AND Gender_Id = ?
                ORDER BY Name COLLATE NOCASE
            """
        else:
            sql = """
                SELECT Id, Name, Image_Id, NULL as CostumeImage_Id
                FROM Equipment
                WHERE Type_Id = ? AND Gender_Id = ?
                ORDER BY Name COLLATE NOCASE
            """

        rows = self.data.conn.execute(sql, (self.TYPE_ID_COSTUME, int(gender_id))).fetchall()

        items: list[dict] = []
        for r in rows or []:
            try:
                eid = int(r["Id"]) if hasattr(r, "keys") else int(r[0])
            except Exception:
                continue
            if eid not in allowed:
                continue

            try:
                name = r["Name"] if hasattr(r, "keys") else r[1]
                img = r["Image_Id"] if hasattr(r, "keys") else r[2]
                cim = r["CostumeImage_Id"] if hasattr(r, "keys") else r[3]
            except Exception:
                continue

            items.append({
                "Id": int(eid),
                "Name": str(name or ""),
                "Image_Id": int(img) if img is not None else None,
                "CostumeImage_Id": int(cim) if cim is not None else None,
            })

        return items

    def _fetch_costume_item(self, equip_id: int) -> Optional[dict]:
        allowed = self._allowed_equipment_ids_from_collection()
        if allowed and int(equip_id) not in allowed:
            return None

        if self._has_costume_image:
            r = self.data.conn.execute(
                "SELECT Id, Name, Image_Id, CostumeImage_Id FROM Equipment WHERE Id=? AND Type_Id=?",
                (int(equip_id), self.TYPE_ID_COSTUME),
            ).fetchone()
        else:
            r = self.data.conn.execute(
                "SELECT Id, Name, Image_Id, NULL as CostumeImage_Id FROM Equipment WHERE Id=? AND Type_Id=?",
                (int(equip_id), self.TYPE_ID_COSTUME),
            ).fetchone()

        if not r:
            return None

        return {
            "Id": int(r["Id"]) if hasattr(r, "keys") else int(r[0]),
            "Name": (r["Name"] if hasattr(r, "keys") else r[1]),
            "Image_Id": int(r["Image_Id"] if hasattr(r, "keys") else r[2]) if (r["Image_Id"] if hasattr(r, "keys") else r[2]) is not None else None,
            "CostumeImage_Id": int(r["CostumeImage_Id"] if hasattr(r, "keys") else r[3]) if (r["CostumeImage_Id"] if hasattr(r, "keys") else r[3]) is not None else None,
        }


class MountController:
    """
    Type_Id=15 (mount). Показывает ТОЛЬКО то, что добавлено в Коллекции.
    Переводим CollectedItem.Id -> Equipment_Id через CollectedItem (Group_Id=3).
    """
    SLOT_KEY = "mount"
    TYPE_ID_MOUNT = 15
    COLLECTION_GROUP_ID = 3
    TYPE_NAME = "Ездовой питомец"

    def __init__(self, parent_widget, data, get_gender_id, on_pick, on_clear):
        self.parent = parent_widget
        self.data = data
        self.get_gender_id = get_gender_id
        self.on_pick = on_pick
        self.on_clear = on_clear
        self._current_mount_id: Optional[int] = None

        def _get_selected_item(k: str):
            try:
                sel = getattr(self.parent, "_selected_items", None) or {}
                return sel.get(str(k))
            except Exception:
                return None

        self._activate_toggle: Optional[_ActivateBonusToggle] = None
        try:
            self._activate_toggle = _ActivateBonusToggle(self.parent, self.SLOT_KEY, self.data, _get_selected_item)
            QTimer.singleShot(0, self._activate_toggle.sync)
        except Exception:
            self._activate_toggle = None

    def show_menu(self, global_pos: QPoint) -> Optional[QMenu]:
        items = self._fetch_mounts()

        m = QMenu(self.parent)

        # --- ВАЖНО: делаем QMenu реально прозрачным окном ---
        try:
            m.setAttribute(Qt.WA_TranslucentBackground, True)
            m.setAttribute(Qt.WA_NoSystemBackground, True)
            m.setAutoFillBackground(False)
            m.setWindowFlag(Qt.FramelessWindowHint, True)
            m.setWindowFlag(Qt.NoDropShadowWindowHint, True)
        except Exception:
            pass

        m.setStyleSheet(
            "QMenu{background: transparent; border: 0px; padding:0px; margin:0px;}"
            "QMenu::item{background: transparent; padding:0px; margin:0px;}"
            "QMenu::separator{height:0px; margin:0px; padding:0px;}"
        )

        # -----------------------------
        # ПУСТОЙ СПИСОК: рисуем QLabel
        # -----------------------------
        if not items:
            cfg = ItemChooseConfig()
            menu_widget = ChooseItemMenu(m, config=cfg)

            try:
                menu_widget.setAttribute(Qt.WA_TranslucentBackground, True)
                menu_widget.setAttribute(Qt.WA_NoSystemBackground, True)
                menu_widget.setAutoFillBackground(False)
                menu_widget.setStyleSheet("background: transparent;")

                area = getattr(menu_widget, "_area", None)
                if area is not None:
                    area.setStyleSheet(
                        "QScrollArea{background: transparent; border:0px;}"
                        "QScrollArea>QWidget{background: transparent;}"
                    )
                    try:
                        area.viewport().setAutoFillBackground(False)
                        area.viewport().setStyleSheet("background: transparent;")
                    except Exception:
                        pass

                cont = getattr(menu_widget, "_cont", None)
                if cont is not None:
                    cont.setAutoFillBackground(False)
                    cont.setStyleSheet("background: transparent;")
            except Exception:
                pass

            def _noop_pick(_item: dict) -> None:
                return

            menu_widget.set_entries(
                entries=[],
                on_pick=_noop_pick,
                on_hover_enter=None,
                on_hover_leave=None,
                focus_search=False,
            )

            # ⬇⬇⬇ ВОТ ЭТО ТЫ МЕНЯЕШЬ, ЧТОБЫ ДВИГАТЬ НАДПИСЬ ⬇⬇⬇
            EMPTY_MSG_RECT = (17, 210, 499, 30)  # x, y, w, h
            msg = QLabel(menu_widget)
            msg.setGeometry(*EMPTY_MSG_RECT)
            msg.setText("(Добавь маунтов в Коллекцию)")
            msg.setAlignment(Qt.AlignCenter)
            msg.setWordWrap(True)
            msg.setStyleSheet("background: transparent; color:#eaeaea; font-weight:600;")
            msg.raise_()
            msg.show()

            try:
                menu_widget.search_edit.setEnabled(False)
                menu_widget.search_edit.setText("")
            except Exception:
                pass

            wa = QWidgetAction(m)
            wa.setDefaultWidget(menu_widget)
            m.addAction(wa)

            m.popup(QPoint(global_pos))
            return m

        # --- дальше (не пусто) как было ---
        char_lvl = None
        try:
            spin = getattr(self.parent, "level_spin", None) or getattr(self.parent, "lvl_spin", None)
            if spin is not None and hasattr(spin, "value"):
                char_lvl = int(spin.value())
        except Exception:
            char_lvl = None

        conn = getattr(self.data, "conn", None)

        extra: dict[int, dict] = {}
        try:
            ids = [int(it.get("Id") or 0) for it in items if int(it.get("Id") or 0) > 0]
            if conn is not None and ids:
                qm = ",".join("?" for _ in ids)
                rows = conn.execute(
                    f"SELECT Id, Level, Attack, Defense FROM Equipment WHERE Id IN ({qm})",
                    tuple(ids),
                ).fetchall()
                for r in rows or []:
                    try:
                        eid = int(r["Id"]) if hasattr(r, "keys") else int(r[0])
                        lvl = int((r["Level"] if hasattr(r, "keys") else r[1]) or 0)
                        atk = int((r["Attack"] if hasattr(r, "keys") else r[2]) or 0)
                        deff = int((r["Defense"] if hasattr(r, "keys") else r[3]) or 0)
                    except Exception:
                        continue
                    extra[eid] = {"Level": lvl, "Attack": atk, "Defense": deff}
        except Exception:
            extra = {}

        cfg = ItemChooseConfig()
        menu_widget = ChooseItemMenu(m, config=cfg)

        try:
            menu_widget.setAttribute(Qt.WA_TranslucentBackground, True)
            menu_widget.setAttribute(Qt.WA_NoSystemBackground, True)
            menu_widget.setAutoFillBackground(False)
            menu_widget.setStyleSheet("background: transparent;")

            area = getattr(menu_widget, "_area", None)
            if area is not None:
                area.setStyleSheet(
                    "QScrollArea{background: transparent; border:0px;}"
                    "QScrollArea>QWidget{background: transparent;}"
                )
                try:
                    area.viewport().setAutoFillBackground(False)
                    area.viewport().setStyleSheet("background: transparent;")
                except Exception:
                    pass

            cont = getattr(menu_widget, "_cont", None)
            if cont is not None:
                cont.setAutoFillBackground(False)
                cont.setStyleSheet("background: transparent;")
        except Exception:
            pass

        entries: list[dict] = []
        for it in items:
            item_full = dict(it)
            eid = int(item_full.get("Id") or 0)

            if eid in extra:
                item_full.update(extra[eid])

            icon_id = item_full.get("Image_Id")
            icon_pm = _pm_from_bytes(self.data.get_image_bytes(icon_id)) if icon_id is not None else None

            bonus_lines: list[str] = []
            if conn is not None and _render_bonus_lines_helper:
                try:
                    bonus_lines = _render_bonus_lines_helper(conn, int(eid), char_level=char_lvl) or []
                except Exception:
                    bonus_lines = []

            entries.append({"item": item_full, "bonuses": bonus_lines, "icon_pm": icon_pm})

        def _pick(item_payload: dict) -> None:
            try:
                self._apply_pick(item_payload)
            finally:
                try:
                    m.close()
                except Exception:
                    pass

        menu_widget.set_entries(
            entries=entries,
            on_pick=_pick,
            on_hover_enter=None,
            on_hover_leave=None,
            focus_search=True,
        )

        wa = QWidgetAction(m)
        wa.setDefaultWidget(menu_widget)
        m.addAction(wa)

        m.popup(QPoint(global_pos))
        return m

    def _build_card_widget(self, menu: QMenu, item: dict) -> QWidget:
        w = QWidget(menu)
        w.setObjectName("costumeCard")
        w.setAttribute(Qt.WA_Hover, True)
        w.setAttribute(Qt.WA_StyledBackground, True)
        w.setMouseTracking(True)

        lay = QGridLayout(w)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(2)

        icon_lbl = QLabel(w)
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setScaledContents(True)
        icon_lbl.setStyleSheet("background: transparent;")

        cid = item.get("Image_Id")
        pm = _pm_from_bytes(self.data.get_image_bytes(cid)) if cid is not None else None
        if pm:
            icon_lbl.setPixmap(pm)
        lay.addWidget(icon_lbl, 0, 0, 2, 1)

        name_lbl = QLabel(item.get("Name", ""), w)
        name_lbl.setStyleSheet("background: transparent; color:#fff; font-weight:600;")
        lay.addWidget(name_lbl, 0, 1, 1, 1)

        def _choose_and_close(_ev, _item=item, _menu=menu):
            self._apply_pick(_item)
            _menu.close()

        w.mouseReleaseEvent = _choose_and_close
        return w

    def _apply_pick(self, item: dict):
        self._current_mount_id = int(item["Id"])
        payload = {
            "Id": int(item["Id"]),
            "Name": item.get("Name", ""),
            "Image_Id": item.get("Image_Id"),
            "Type_Id": self.TYPE_ID_MOUNT,
            "TypeName": self.TYPE_NAME,

            # флаг "галочки" (по умолчанию выключено)
            "_activate_checked": False,
        }
        self.on_pick(self.SLOT_KEY, payload)

        try:
            if self._activate_toggle is not None:
                QTimer.singleShot(0, self._activate_toggle.sync)
        except Exception:
            pass

    def _allowed_equipment_ids_from_collection(self) -> set[int]:
        cw = getattr(self.parent, "_collection_window", None)
        menu = getattr(cw, "menu", None) if cw is not None else None
        in_col = getattr(menu, "_in_col_set", None)
        if not isinstance(in_col, set) or not in_col:
            return set()

        conn = getattr(self.data, "conn", None)
        if conn is None:
            return set()

        ids = [int(x) for x in in_col if int(x) > 0]
        if not ids:
            return set()

        out: set[int] = set()
        step = 900
        for i in range(0, len(ids), step):
            chunk = ids[i:i + step]
            qm = ",".join("?" for _ in chunk)
            try:
                rows = conn.execute(
                    f"SELECT Equipment_Id FROM CollectedItem WHERE Group_Id=? AND Id IN ({qm}) AND Equipment_Id IS NOT NULL",
                    (int(self.COLLECTION_GROUP_ID), *chunk),
                ).fetchall()
            except Exception:
                rows = []

            for r in rows or []:
                try:
                    v = r["Equipment_Id"] if hasattr(r, "keys") else r[0]
                    eid = int(v or 0)
                except Exception:
                    eid = 0
                if eid > 0:
                    out.add(eid)

        return out

    def _fetch_mounts(self) -> list[dict]:
        allowed = self._allowed_equipment_ids_from_collection()
        if not allowed:
            return []

        rows = self.data.conn.execute(
            """
            SELECT Id, Name, Image_Id
            FROM Equipment
            WHERE Type_Id = ?
            ORDER BY Name COLLATE NOCASE
            """,
            (self.TYPE_ID_MOUNT,),
        ).fetchall()

        items: list[dict] = []
        for r in rows or []:
            try:
                eid = int(r["Id"]) if hasattr(r, "keys") else int(r[0])
            except Exception:
                continue
            if eid not in allowed:
                continue

            try:
                name = r["Name"] if hasattr(r, "keys") else r[1]
                img = r["Image_Id"] if hasattr(r, "keys") else r[2]
            except Exception:
                continue

            items.append({
                "Id": int(eid),
                "Name": str(name or ""),
                "Image_Id": int(img) if img is not None else None,
            })

        return items