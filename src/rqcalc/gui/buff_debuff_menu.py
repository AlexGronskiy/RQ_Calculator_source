from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import Qt, QRect, QEvent, Signal, QPoint, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QWidget,
    QScrollArea,
    QVBoxLayout,
    QComboBox,
    QApplication,
    QStyledItemDelegate,
    QListView,
    QStyle,
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
        return int(default)


def _to_str(v) -> str:
    try:
        return str(v or "")
    except Exception:
        return ""


def _has_col(conn, table: str, col: str) -> bool:
    try:
        return any(r[1] == col for r in conn.execute(f'PRAGMA table_info("{table}")'))
    except Exception:
        return False


def _pm_from_bytes(data: Optional[bytes]) -> QPixmap:
    pm = QPixmap()
    try:
        if data:
            pm.loadFromData(data)
    except Exception:
        pass
    return pm


def _format_number(v: Any) -> str:
    try:
        fv = float(v)
        if abs(fv - round(fv)) < 1e-9:
            return str(int(round(fv)))
        return f"{fv:.4f}".rstrip("0").rstrip(".")
    except Exception:
        return str(v)


def _format_bonus_template(template: str, value: Any) -> str:
    tpl = _to_str(template).strip()
    if not tpl:
        return ""

    sval = _format_number(value)

    def _repl(_m):
        return sval

    return re.sub(r"\{(\d+)\}", _repl, tpl).strip()


class _BuffComboDelegate(QStyledItemDelegate):
    def __init__(self, combo: "_BuffComboBox"):
        super().__init__(combo)
        self._combo = combo

    def sizeHint(self, option, index):
        text = _to_str(index.data(Qt.DisplayRole))
        width = max(80, int(self._combo.width()) - 30)

        fm = QFontMetrics(option.font)
        br = fm.boundingRect(
            QRect(0, 0, width, 2000),
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter,
            text,
        )

        h = max(22, int(br.height()) + 8)
        return QSize(int(self._combo.width()), int(h))

    def paint(self, painter, option, index):
        painter.save()

        text = _to_str(index.data(Qt.DisplayRole))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        if selected:
            painter.fillRect(option.rect, QColor("#d9ecff"))
        else:
            painter.fillRect(option.rect, QColor("#f3f3f3"))

        text_rect = option.rect.adjusted(6, 2, -6, -2)
        painter.setPen(QColor("#000000"))
        painter.drawText(
            text_rect,
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter,
            text,
        )

        painter.restore()


class _BuffComboBox(QComboBox):
    def __init__(self, parent: Optional[QWidget], anchor_rect: QRect):
        super().__init__(parent)

        self._anchor_rect = QRect(anchor_rect)
        self._hover = False

        view = QListView(self)
        view.setWordWrap(True)
        view.setUniformItemSizes(False)
        view.setSpacing(0)
        self.setView(view)
        self.setItemDelegate(_BuffComboDelegate(self))

        self.setCursor(Qt.PointingHandCursor)
        self.setEditable(False)
        self.setInsertPolicy(QComboBox.NoInsert)

        try:
            self.currentIndexChanged.connect(self._on_index_changed_internal)
        except Exception:
            pass

    def _line_height_for_text(self, text: str, width: int) -> int:
        fm = QFontMetrics(self.font())
        br = fm.boundingRect(QRect(0, 0, max(10, int(width)), 3000), Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter, _to_str(text))
        return max(22, int(br.height()) + 8)

    def _preferred_height(self) -> int:
        text = _to_str(self.currentText())
        text_w = max(20, int(self.width()) - 30)
        return self._line_height_for_text(text, text_w)

    def recenter_in_block(self, block_height: int) -> None:
        target_h = self._preferred_height()
        cx = int(self._anchor_rect.x())
        cw = int(self._anchor_rect.width())
        cy = int(self._anchor_rect.center().y())

        y = int(round(cy - target_h / 2.0))
        if y < 0:
            y = 0
        if y + target_h > int(block_height):
            y = max(0, int(block_height) - target_h)

        self.setGeometry(cx, y, cw, target_h)

        try:
            self.view().setMinimumWidth(int(cw))
            self.view().setMaximumWidth(int(cw))
        except Exception:
            pass

        self.update()

    def _on_index_changed_internal(self, *_args) -> None:
        try:
            parent = self.parentWidget()
            bh = parent.height() if parent is not None else self.height()
        except Exception:
            bh = self.height()
        self.recenter_in_block(int(bh))

    def enterEvent(self, ev) -> None:
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(ev)

    def showPopup(self) -> None:
        try:
            self.view().setMinimumWidth(int(self.width()))
            self.view().setMaximumWidth(int(self.width()))
        except Exception:
            pass
        super().showPopup()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        r = self.rect().adjusted(0, 0, -1, -1)

        border_col = QColor("#5f5f5f") if self._hover else QColor("#7f7f7f")

        p.setPen(border_col)
        p.setBrush(QColor("#f3f3f3"))
        p.drawRect(r)

        dd_w = 22
        dd_rect = QRect(r.right() - dd_w + 1, r.top(), dd_w, r.height())
        p.fillRect(dd_rect, QColor("#e8e8e8"))

        p.setPen(QColor("#9a9a9a"))
        p.drawLine(dd_rect.left(), dd_rect.top(), dd_rect.left(), dd_rect.bottom())

        # стрелка
        p.setPen(QColor("#333333"))
        cx = dd_rect.center().x()
        cy = dd_rect.center().y()
        p.drawLine(cx - 4, cy - 1, cx, cy + 3)
        p.drawLine(cx, cy + 3, cx + 4, cy - 1)

        text_rect = QRect(r.left() + 6, r.top() + 2, r.width() - dd_w - 10, r.height() - 4)
        p.setPen(QColor("#000000"))
        p.drawText(text_rect, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter, _to_str(self.currentText()))

        p.end()


class _BuffDebuffItemWidget(QFrame):
    value_changed = Signal(int, int, str)

    def __init__(
        self,
        parent: Optional[QWidget],
        *,
        item_id: int,
        base_pm: QPixmap,
        active_pm: QPixmap,
        combo_rect: QRect,
        name_rect: QRect,
        icon_rect: QRect,
        icon_pm: Optional[QPixmap] = None,
        name_text: str = "",
        options: Optional[list[str]] = None,
        current_index: int = 0,
    ):
        super().__init__(parent)

        self._item_id = int(item_id)
        self._base_pm = QPixmap(base_pm) if not base_pm.isNull() else QPixmap()
        self._active_pm = QPixmap(active_pm) if not active_pm.isNull() else QPixmap()

        self._hover = False
        self._combo_rect = QRect(combo_rect)
        self._name_rect = QRect(name_rect)
        self._icon_rect = QRect(icon_rect)

        self._icon_pm = QPixmap(icon_pm) if isinstance(icon_pm, QPixmap) and not icon_pm.isNull() else QPixmap()
        self._name_text = _to_str(name_text)

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

        self._combo = _BuffComboBox(self, self._combo_rect)
        items = [str(x) for x in options] if options else [""]

        self._combo.addItems(items)

        idx = max(0, min(len(items) - 1, int(current_index))) if items else 0
        self._combo.setCurrentIndex(idx)
        self._combo.recenter_in_block(self.height())

        try:
            self._combo.currentIndexChanged.connect(self._on_combo_index_changed)
        except Exception:
            pass

    def _on_combo_index_changed(self, index: int) -> None:
        try:
            self._combo.recenter_in_block(self.height())
        except Exception:
            pass

        try:
            txt = str(self._combo.currentText() or "")
        except Exception:
            txt = ""
        self.value_changed.emit(int(self._item_id), int(index), txt)

    def current_index(self) -> int:
        try:
            return int(self._combo.currentIndex())
        except Exception:
            return 0

    def current_text(self) -> str:
        try:
            return str(self._combo.currentText() or "")
        except Exception:
            return ""

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        bg_pm = self._active_pm if (self._hover and not self._active_pm.isNull()) else self._base_pm

        if not bg_pm.isNull():
            target_rect = QRect(0, 0, self.width(), self.height())
            if bg_pm.size() != target_rect.size():
                draw_pm = bg_pm.scaled(target_rect.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            else:
                draw_pm = bg_pm
            p.drawPixmap(target_rect.topLeft(), draw_pm)

        if not self._icon_pm.isNull() and not self._icon_rect.isEmpty():
            scaled = self._icon_pm.scaled(
                self._icon_rect.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            draw_rect = QRect(0, 0, scaled.width(), scaled.height())
            draw_rect.moveCenter(self._icon_rect.center())
            p.drawPixmap(draw_rect.topLeft(), scaled)

        if not self._name_rect.isEmpty() and self._name_text.strip():
            p.setPen(Qt.black)
            p.drawText(
                self._name_rect,
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                self._name_text,
            )

        p.end()
        super().paintEvent(ev)

    def enterEvent(self, ev) -> None:
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(ev)


class BuffDebuffMenu(QFrame):
    closed = Signal()
    tab_changed = Signal(str)

    TAB_1 = "tab1"
    TAB_2 = "tab2"
    TAB_3 = "tab3"
    TAB_4 = "tab4"
    TAB_5 = "tab5"
    TAB_6 = "tab6"
    TABS = [TAB_1, TAB_2, TAB_3, TAB_4, TAB_5, TAB_6]

    DEFAULT_SIZE: Tuple[int, int] = (691, 570)

    MENU_IMAGES: Dict[str, str] = {
        TAB_1: r"resources/buff_debuff_menu/buff_debuff_menu_1.png",
        TAB_2: r"resources/buff_debuff_menu/buff_debuff_menu_2.png",
        TAB_3: r"resources/buff_debuff_menu/buff_debuff_menu_3.png",
        TAB_4: r"resources/buff_debuff_menu/buff_debuff_menu_4.png",
        TAB_5: r"resources/buff_debuff_menu/buff_debuff_menu_5.png",
        TAB_6: r"resources/buff_debuff_menu/buff_debuff_menu_6.png",
    }

    CLOSE_ACTIVE_IMAGE = r"resources/helper_buttons/close_button_active.png"
    CLOSE2_IMAGE = r"resources/collection/close.png"

    BLOCK_PATH = r"resources/buff_debuff_menu/buff_debuff_block.png"
    BLOCK_ACTIVE_PATH = r"resources/buff_debuff_menu/buff_debuff_block_active.png"

    @dataclass
    class LayoutConfig:
        menu_size: Tuple[int, int]
        tab_rects: Dict[str, QRect]
        close1_rect: QRect
        close2_rect: QRect
        list_rect: QRect
        icon_rect: QRect
        name_rect: QRect
        combo_rect: QRect

    @staticmethod
    def default_layout() -> "BuffDebuffMenu.LayoutConfig":
        tab_rects = {
            BuffDebuffMenu.TAB_1: QRect(94, 40, 94, 28),
            BuffDebuffMenu.TAB_2: QRect(187, 40, 94, 28),
            BuffDebuffMenu.TAB_3: QRect(281, 40, 94, 28),
            BuffDebuffMenu.TAB_4: QRect(375, 40, 94, 28),
            BuffDebuffMenu.TAB_5: QRect(469, 40, 94, 28),
            BuffDebuffMenu.TAB_6: QRect(563, 40, 94, 28),
        }

        close1 = QRect(654, 3, 24, 24)
        close2 = QRect(526, 520, 140, 32)

        return BuffDebuffMenu.LayoutConfig(
            menu_size=BuffDebuffMenu.DEFAULT_SIZE,
            tab_rects=tab_rects,
            close1_rect=close1,
            close2_rect=close2,
            list_rect=QRect(44, 120, 598, 361),
            icon_rect=QRect(10, 35, 48, 48),
            name_rect=QRect(71, 9, 195, 100),
            combo_rect=QRect(280, 44, 284, 30),
        )

    def __init__(
            self,
            parent: Optional[QWidget] = None,
            *,
            layout: Optional["BuffDebuffMenu.LayoutConfig"] = None,
    ):
        super().__init__(parent)
        self.setObjectName("BuffDebuffMenu")

        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")

        self._layout = layout or self.default_layout()
        self._active_tab: str = self.TAB_1

        self._current_class_id: int = 0
        self._current_level: int = 0

        self._pixmaps: Dict[str, QPixmap] = {}
        self._close_active_pix: Optional[QPixmap] = None
        self._close2_pix: Optional[QPixmap] = None
        self._block_pm: Optional[QPixmap] = None
        self._block_active_pm: Optional[QPixmap] = None

        self._close1_down: bool = False
        self._close2_down: bool = False

        # tab -> { buff_id -> combo_index }
        self._combo_index_by_tab: Dict[str, Dict[int, int]] = {
            self.TAB_1: {},
            self.TAB_2: {},
            self.TAB_3: {},
            self.TAB_4: {},
            self.TAB_5: {},
            self.TAB_6: {},
        }

        self._bg = QLabel(self)
        self._bg.setObjectName("BuffDebuffMenuBg")
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

        self.apply_layout()
        self.set_tab(self.TAB_1)

    def current_tab(self) -> str:
        return self._active_tab

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

    def _build_tab_zones(self) -> None:
        for tab in self.TABS:
            z = QFrame(self)
            z.setObjectName(f"buff_debuff_tab_zone_{tab}")
            z.setStyleSheet(
                "background-color: rgba(255,255,255,0);"
                "border: 1px solid rgba(0,0,0,0);"
            )
            z.setCursor(Qt.PointingHandCursor)
            z.installEventFilter(self)
            self._tab_zones[tab] = z

    def _build_close_zones(self) -> None:
        self._close1.setObjectName("buff_debuff_close_zone_1")
        self._close2.setObjectName("buff_debuff_close_zone_2")

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
            v.setSpacing(3)

            sc.setWidget(cont)
            self._scrolls[tab] = sc
            self._containers[tab] = cont
            self._vboxes[tab] = v

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

    def _block_pixmap(self) -> QPixmap:
        if self._block_pm is not None:
            return self._block_pm
        self._block_pm = QPixmap(_resolve_resource(self.BLOCK_PATH))
        return self._block_pm

    def _block_active_pixmap(self) -> QPixmap:
        if self._block_active_pm is not None:
            return self._block_active_pm
        self._block_active_pm = QPixmap(_resolve_resource(self.BLOCK_ACTIVE_PATH))
        return self._block_active_pm

    def _apply_background_for_tab(self, tab: str) -> None:
        pm = self._pixmap_for_tab(tab)
        if pm.isNull():
            self._bg.clear()
            return
        self._bg.setPixmap(pm.scaled(self._bg.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

    def _apply_scroll_visibility(self, tab: str) -> None:
        for t, sc in self._scrolls.items():
            sc.setVisible(t == tab)

    def refresh_runtime_context(self) -> None:
        """
        Обновление меню при изменении внешнего контекста:
        - заменили/сняли карту;
        - заменили/сняли печать;
        - изменились таланты/гильдийские таланты.

        Чистим сохранённые combo-index по всем вкладкам,
        чтобы баф от снятой карты сразу исчезал из player_buff_ids/player_buff_stack_map.
        """
        removed_active = False

        try:
            for tab in self.TABS:
                rows = self._query_buffs_for_tab(tab)

                visible_ids = {
                    _safe_int(r.get("Id"), 0)
                    for r in rows
                    if isinstance(r, dict) and _safe_int(r.get("Id"), 0) > 0
                }

                state_map = self._combo_index_by_tab.setdefault(tab, {})
                if not isinstance(state_map, dict):
                    self._combo_index_by_tab[tab] = {}
                    continue

                for old_id in list(state_map.keys()):
                    oid = _safe_int(old_id, 0)

                    if oid <= 0:
                        state_map.pop(old_id, None)
                        continue

                    if int(oid) not in visible_ids:
                        old_idx = _safe_int(state_map.get(old_id), 0)

                        if old_idx > 0:
                            removed_active = True

                        state_map.pop(old_id, None)

        except Exception:
            pass

        self._rebuild_visible_tab()

        # Даже если активный баф не удалился, свойства всё равно надо перепубликовать,
        # чтобы player_buff_ids/player_buff_stack_map соответствовали актуальному списку.
        self._publish_selected_buffs(refresh_stats=bool(removed_active))

    def set_class_id(self, class_id: int) -> None:
        cid = _safe_int(class_id, 0)
        if int(self._current_class_id) != int(cid):
            self._current_class_id = int(cid)
            self._rebuild_visible_tab()

    def set_level(self, level: int) -> None:
        lvl = _safe_int(level, 0)
        if int(self._current_level) != int(lvl):
            self._current_level = int(lvl)
            self._rebuild_visible_tab()

    def _current_active_buff_ids(self) -> set[int]:
        out: set[int] = set()

        for _tab, mp in (self._combo_index_by_tab or {}).items():
            if not isinstance(mp, dict):
                continue
            for buff_id, combo_index in mp.items():
                bid = _safe_int(buff_id, 0)
                idx = _safe_int(combo_index, 0)
                if bid > 0 and idx > 0:
                    out.add(int(bid))

        return out

    def _publish_selected_buffs(self, *, refresh_stats: bool = True) -> None:
        stack_map: Dict[int, int] = {}
        preview_items: list[dict] = []

        try:
            for tab, mp in (self._combo_index_by_tab or {}).items():
                if not isinstance(mp, dict):
                    continue

                rows = self._query_buffs_for_tab(tab)
                row_by_id: Dict[int, dict] = {}

                for row in rows or []:
                    if not isinstance(row, dict):
                        continue

                    bid = _safe_int(row.get("Id"), 0)
                    if bid > 0:
                        row_by_id[int(bid)] = dict(row)

                for buff_id, combo_index in list(mp.items()):
                    bid = _safe_int(buff_id, 0)
                    idx = _safe_int(combo_index, 0)

                    if bid <= 0 or idx <= 0:
                        continue

                    row = row_by_id.get(int(bid))
                    if not isinstance(row, dict):
                        continue

                    options = self._combo_options_for_buff(row)
                    if not options:
                        continue

                    safe_idx = max(0, min(len(options) - 1, int(idx)))
                    if safe_idx <= 0:
                        continue

                    bonus_text = _to_str(options[safe_idx]).strip()

                    if not bonus_text or bonus_text.casefold() == "нет":
                        continue

                    stack_map[int(bid)] = int(safe_idx)

                    preview_items.append(
                        {
                            "Id": int(bid),
                            "Name": _to_str(row.get("Name")),
                            "BonusText": bonus_text,
                            "Image_Id": _safe_int(row.get("Image_Id"), 0),
                            "Tab": str(tab),
                            "StackIndex": int(safe_idx),
                        }
                    )

        except Exception:
            stack_map = {}
            preview_items = []

        try:
            app = QApplication.instance()
            if app is not None:
                app.setProperty("player_buff_ids", list(sorted(stack_map.keys())))
                app.setProperty("player_buff_stack_map", dict(stack_map))
                app.setProperty("player_buff_preview_items", list(preview_items))
        except Exception:
            pass

        if not refresh_stats:
            return

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

    def _get_db_conn(self):
        host = self
        seen = set()
        while host is not None and id(host) not in seen:
            seen.add(id(host))

            try:
                data = getattr(host, "data", None)
                conn = getattr(data, "conn", None)
                if conn is not None:
                    return conn
            except Exception:
                pass

            try:
                conn = getattr(host, "conn", None)
                if conn is not None:
                    return conn
            except Exception:
                pass

            host = host.parentWidget()

        return None

    def _get_main_window(self):
        host = self
        seen = set()
        while host is not None and id(host) not in seen:
            seen.add(id(host))
            if hasattr(host, "data") and hasattr(host, "_selected_items"):
                return host
            host = host.parentWidget()
        return None

    def _image_pm(self, image_id: int) -> QPixmap:
        iid = _safe_int(image_id, 0)
        if iid <= 0:
            return QPixmap()

        host = self._get_main_window()
        if host is not None:
            try:
                fn = getattr(host, "_get_image_pm", None)
                if callable(fn):
                    pm = fn(int(iid))
                    if isinstance(pm, QPixmap) and not pm.isNull():
                        return pm
            except Exception:
                pass

            try:
                data = getattr(host, "data", None)
                getter = getattr(data, "get_image_bytes", None)
                if callable(getter):
                    return _pm_from_bytes(getter(int(iid)))
            except Exception:
                pass

        conn = self._get_db_conn()
        if conn is not None:
            try:
                row = conn.execute("SELECT Data FROM Image WHERE Id=? LIMIT 1", (int(iid),)).fetchone()
            except Exception:
                row = None

            if row:
                try:
                    raw = row["Data"] if hasattr(row, "keys") else row[0]
                except Exception:
                    raw = None
                return _pm_from_bytes(raw)

        return QPixmap()

    def _get_active_guild_talent_ids(self) -> set[int]:
        out: set[int] = set()

        try:
            app = QApplication.instance()
            if app is None:
                return out

            raw = app.property("player_guild_talents")
            if isinstance(raw, list):
                for row in raw:
                    if not isinstance(row, dict):
                        continue
                    tid = _safe_int(row.get("Talent_Id") or row.get("talent_id"), 0)
                    if tid > 0:
                        out.add(int(tid))
        except Exception:
            pass

        return out

    def _get_active_talent_ids(self) -> set[int]:
        out: set[int] = set()

        try:
            app = QApplication.instance()
            if app is None:
                return out

            raw = app.property("player_talents")
            if isinstance(raw, list):
                for row in raw:
                    if not isinstance(row, dict):
                        continue
                    tid = _safe_int(row.get("Talent_Id") or row.get("talent_id"), 0)
                    if tid > 0:
                        out.add(int(tid))
        except Exception:
            pass

        return out

    def _class_lineage_ids(self, class_id: int) -> list[int]:
        """
        Полностью по аналогии с talents_menu:
        current class -> Base_Id -> Base_Id родителя -> ...
        """
        conn = self._get_db_conn()
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

    def _get_equipped_card_ids(self) -> set[int]:
        """
        Возвращает Id реально надетых карт.

        Раньше источник был только item["_cards"] / item["cards"] / item["Cards"].
        Из-за этого после замены карты меню бафов могло видеть старую карту,
        если словарь предмета ещё не успел синхронизироваться.

        Теперь приоритет такой:
        1) живой кэш cards_window.get_cards_for_item(...)
        2) только если живого кэша нет/метод недоступен — старые поля предмета
        """
        out: set[int] = set()

        host = self._get_main_window()
        if host is None:
            return out

        items = getattr(host, "_selected_items", {}) or {}
        if not isinstance(items, dict):
            return out

        cards_window = getattr(host, "cards_window", None)

        def _slot_kind(slot_key: Optional[str]) -> str:
            sk = str(slot_key or "").strip().lower()
            return "weapon" if sk in {"weapon", "offhand", "spear"} else "equipment"

        def _push_card_payload(raw_cards: Any) -> None:
            if isinstance(raw_cards, dict):
                iterable = list(raw_cards.values())
            elif isinstance(raw_cards, (list, tuple)):
                iterable = list(raw_cards)
            else:
                iterable = []

            for c in iterable:
                cid = 0

                try:
                    if isinstance(c, dict):
                        cid = _safe_int(
                            c.get("Id")
                            or c.get("Card_Id")
                            or c.get("CardId"),
                            0,
                        )

                    elif isinstance(c, (tuple, list)) and c:
                        first = c[0]

                        if isinstance(first, dict):
                            cid = _safe_int(
                                first.get("Id")
                                or first.get("Card_Id")
                                or first.get("CardId"),
                                0,
                            )
                        else:
                            cid = _safe_int(first, 0)

                    else:
                        cid = _safe_int(c, 0)

                except Exception:
                    cid = 0

                if cid > 0:
                    out.add(int(cid))

        for slot_key, it in list(items.items()):
            if not isinstance(it, dict):
                continue

            real_slot_key = str(
                slot_key
                or it.get("slot_key")
                or it.get("SlotKey")
                or ""
            ).strip() or None

            used_live_cards_source = False

            # ------------------------------------------------------
            # Главный источник: актуальный кэш cards_window.
            # Даже если он вернул пусто, это значит "карт нет",
            # и fallback к старому item["_cards"] делать нельзя,
            # иначе старая снятая карта снова попадёт в список бафов.
            # ------------------------------------------------------
            try:
                get_cards = getattr(cards_window, "get_cards_for_item", None)
                if callable(get_cards):
                    try:
                        live_cards = get_cards(
                            it,
                            kind=_slot_kind(real_slot_key),
                            slot_key=real_slot_key,
                        )
                    except TypeError:
                        try:
                            live_cards = get_cards(
                                it,
                                kind=_slot_kind(real_slot_key),
                            )
                        except TypeError:
                            live_cards = get_cards(it)

                    used_live_cards_source = True
                    _push_card_payload(live_cards)
            except Exception:
                used_live_cards_source = False

            if used_live_cards_source:
                continue

            # Старый fallback только если cards_window недоступен.
            old_cards = it.get("_cards") or it.get("cards") or it.get("Cards") or []
            _push_card_payload(old_cards)

        return out

    def _get_equipped_stamp_ids(self) -> set[int]:
        out: set[int] = set()
        host = self._get_main_window()
        items = getattr(host, "_selected_items", {}) if host is not None else {}

        stamp_reader = getattr(host, "_stamp_payload_for_item", None) if host is not None else None

        for it in (items or {}).values():
            if not isinstance(it, dict):
                continue

            sid = 0

            try:
                if callable(stamp_reader):
                    st = stamp_reader(it)
                    if isinstance(st, dict):
                        sid = _safe_int(st.get("Id") or st.get("id"), 0)
            except Exception:
                sid = 0

            if sid <= 0:
                st = it.get("Stamp") or it.get("stamp")
                if isinstance(st, dict):
                    sid = _safe_int(st.get("Id") or st.get("id"), 0)

            if sid > 0:
                out.add(int(sid))

        return out

    def _query_buff_bonus_rows(self, buff_id: int) -> list[dict]:
        """
        Приоритет источников для значений бафа:
        1) Если у активных талантов есть TalentBonus с BuffCondition_Id = buff_id,
           то берём строки ИЗ TalentBonus.
        2) Иначе берём обычные строки ИЗ BuffBonus.

        Дополнительно:
          - для BuffBonus читаем MulyiplyBonus, если колонка есть;
          - для TalentBonus считаем MulyiplyBonus = 0.
        """
        conn = self._get_db_conn()
        bid = _safe_int(buff_id, 0)
        if conn is None or bid <= 0:
            return []

        active_talent_ids = sorted(self._get_active_talent_ids())

        # --- Сначала пробуем заменить BuffBonus на TalentBonus ---
        if active_talent_ids:
            ph = ",".join(["?"] * len(active_talent_ids))
            try:
                rows = conn.execute(
                    f"""
                    SELECT tb.Type_Id, tb.Value, tb.Id AS OrderIndex, bt.Template
                    FROM TalentBonus AS tb
                    JOIN BonusType AS bt ON bt.Id = tb.Type_Id
                    WHERE tb.BuffCondition_Id=?
                      AND tb.Talent_Id IN ({ph})
                    ORDER BY tb.Id
                    """,
                    (int(bid), *tuple(int(x) for x in active_talent_ids)),
                ).fetchall()
            except Exception:
                rows = []

            out: list[dict] = []
            for r in rows or []:
                try:
                    if hasattr(r, "keys"):
                        out.append(
                            {
                                "Type_Id": _safe_int(r["Type_Id"], 0),
                                "Value": _safe_int(r["Value"], 0),
                                "OrderIndex": _safe_int(r["OrderIndex"], 0),
                                "Template": _to_str(r["Template"]),
                                "MulyiplyBonus": 0,
                            }
                        )
                    else:
                        out.append(
                            {
                                "Type_Id": _safe_int(r[0], 0),
                                "Value": _safe_int(r[1], 0),
                                "OrderIndex": _safe_int(r[2], 0),
                                "Template": _to_str(r[3]),
                                "MulyiplyBonus": 0,
                            }
                        )
                except Exception:
                    continue

            if out:
                return out

        has_multiply_bonus = _has_col(conn, "BuffBonus", "MulyiplyBonus")

        # --- Если TalentBonus для этого бафа нет, используем обычный BuffBonus ---
        try:
            if has_multiply_bonus:
                rows = conn.execute(
                    """
                    SELECT bb.Type_Id, bb.Value, bb.OrderIndex, bt.Template, bb.MulyiplyBonus
                    FROM BuffBonus AS bb
                    JOIN BonusType AS bt ON bt.Id = bb.Type_Id
                    WHERE bb.Buff_Id=?
                    ORDER BY bb.OrderIndex, bb.Type_Id
                    """,
                    (int(bid),),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT bb.Type_Id, bb.Value, bb.OrderIndex, bt.Template
                    FROM BuffBonus AS bb
                    JOIN BonusType AS bt ON bt.Id = bb.Type_Id
                    WHERE bb.Buff_Id=?
                    ORDER BY bb.OrderIndex, bb.Type_Id
                    """,
                    (int(bid),),
                ).fetchall()
        except Exception:
            rows = []

        out: list[dict] = []
        for r in rows or []:
            try:
                if hasattr(r, "keys"):
                    out.append(
                        {
                            "Type_Id": _safe_int(r["Type_Id"], 0),
                            "Value": _safe_int(r["Value"], 0),
                            "OrderIndex": _safe_int(r["OrderIndex"], 0),
                            "Template": _to_str(r["Template"]),
                            "MulyiplyBonus": _safe_int(r["MulyiplyBonus"], 0) if has_multiply_bonus else 0,
                        }
                    )
                else:
                    out.append(
                        {
                            "Type_Id": _safe_int(r[0], 0),
                            "Value": _safe_int(r[1], 0),
                            "OrderIndex": _safe_int(r[2], 0),
                            "Template": _to_str(r[3]),
                            "MulyiplyBonus": _safe_int(r[4], 0) if has_multiply_bonus and len(r) > 4 else 0,
                        }
                    )
            except Exception:
                continue

        return out

    def _combo_options_for_buff(self, row: dict) -> list[str]:
        max_stack = max(0, _safe_int(row.get("MaxStackCount"), 0))
        bonus_rows = self._query_buff_bonus_rows(_safe_int(row.get("Id"), 0))

        options: list[str] = ["Нет"]

        if max_stack <= 0 or not bonus_rows:
            return options

        for stack in range(1, max_stack + 1):
            parts: list[str] = []

            for b in bonus_rows:
                val = _safe_int(b.get("Value"), 0) * int(stack)
                txt = _format_bonus_template(_to_str(b.get("Template")), val).strip()
                if not txt:
                    continue

                if val > 0:
                    stripped = txt.lstrip()
                    if not stripped.startswith(("+", "-", "−", "–", "—")):
                        txt = "+" + txt

                parts.append(txt)

            options.append("\n".join(parts) if parts else f"x{stack}")

        return options

    def get_active_preview_items(self, group: str) -> list[dict]:
        """
        Возвращает активные бафы/дебафы для маленького выдвижного списка в MainWindow.

        Активным считается только тот эффект, у которого текущий текст combo != "Нет".
        """
        group = _to_str(group).strip().lower()

        if group in ("debuff", "debuffs", "negative", "negate"):
            tabs = [self.TAB_6]
        elif group in ("personal", "self", "личные"):
            tabs = [self.TAB_1]
        elif group in ("all", "*", "все"):
            tabs = list(self.TABS)
        else:
            tabs = [self.TAB_2, self.TAB_3, self.TAB_4, self.TAB_5]

        # Сначала синхронизируем состояние прямо с живых combo-box.
        # Это страховка на случай, если signal где-то не успел обновить state_map.
        try:
            for tab in tabs:
                cont = (getattr(self, "_containers", {}) or {}).get(tab)
                if cont is None:
                    continue

                state_map = self._combo_index_by_tab.setdefault(tab, {})
                if not isinstance(state_map, dict):
                    state_map = {}
                    self._combo_index_by_tab[tab] = state_map

                for w in cont.findChildren(_BuffDebuffItemWidget):
                    try:
                        bid = _safe_int(getattr(w, "_item_id", 0), 0)
                        idx = _safe_int(w.current_index(), 0)
                        txt = _to_str(w.current_text()).strip()
                    except Exception:
                        continue

                    if bid <= 0:
                        continue

                    if idx > 0 and txt and txt.casefold() != "нет":
                        state_map[int(bid)] = int(idx)
                    else:
                        state_map[int(bid)] = 0
        except Exception:
            pass

        out: list[dict] = []
        seen_ids: set[int] = set()
        changed_state = False

        for tab in tabs:
            rows = self._query_buffs_for_tab(tab)
            state_map = self._combo_index_by_tab.setdefault(tab, {})

            if not isinstance(state_map, dict):
                state_map = {}
                self._combo_index_by_tab[tab] = state_map

            visible_ids = {
                _safe_int(r.get("Id"), 0)
                for r in rows
                if isinstance(r, dict) and _safe_int(r.get("Id"), 0) > 0
            }

            for old_id in list(state_map.keys()):
                oid = _safe_int(old_id, 0)
                if oid <= 0 or int(oid) not in visible_ids:
                    state_map.pop(old_id, None)
                    changed_state = True

            for row in rows:
                buff_id = _safe_int(row.get("Id"), 0)
                if buff_id <= 0:
                    continue

                options = self._combo_options_for_buff(row)

                if buff_id in state_map:
                    current_index = _safe_int(state_map.get(buff_id), 0)
                else:
                    current_index = self._default_combo_index_for_row(row)
                    state_map[buff_id] = int(current_index)
                    changed_state = True

                current_index = max(0, min(len(options) - 1, int(current_index))) if options else 0
                state_map[buff_id] = int(current_index)

                if current_index <= 0:
                    continue

                bonus_text = ""
                try:
                    bonus_text = _to_str(options[current_index]).strip()
                except Exception:
                    bonus_text = ""

                if not bonus_text or bonus_text.casefold() == "нет":
                    continue

                if buff_id in seen_ids:
                    continue

                seen_ids.add(int(buff_id))

                icon_pm = self._image_pm(_safe_int(row.get("Image_Id"), 0))

                out.append(
                    {
                        "Id": int(buff_id),
                        "Name": _to_str(row.get("Name")),
                        "BonusText": bonus_text,
                        "Image_Id": _safe_int(row.get("Image_Id"), 0),
                        "IconPixmap": icon_pm,
                        "Tab": str(tab),
                        "StackIndex": int(current_index),
                    }
                )

        if changed_state:
            try:
                self._publish_selected_buffs(refresh_stats=False)
            except Exception:
                pass

        return out

    def _default_combo_index_for_row(self, row: dict) -> int:
        auto_enabled = _safe_int(row.get("AutoEnabled"), 0)
        max_stack = max(0, _safe_int(row.get("MaxStackCount"), 0))
        if auto_enabled == 1 and max_stack > 0:
            return 1
        return 0

    def _query_buffs_for_tab(self, tab: str) -> list[dict]:
        conn = self._get_db_conn()
        if conn is None:
            return []

        lvl = _safe_int(self._current_level, 0)
        if lvl <= 0:
            return []

        has_group_col = _has_col(conn, "Buff", "Group")
        group_sql = 'CAST("Group" AS INTEGER) AS GroupValue,' if has_group_col else "NULL AS GroupValue,"

        try:
            rows = conn.execute(
                f"""
                SELECT
                    Id,
                    Name,
                    MaxStackCount,
                    Level,
                    Class_Id,
                    Card_Id,
                    Stamp_Id,
                    TalentCondition_Id,
                    GuildCondition_Id,
                    AutoEnabled,
                    Image_Id,
                    IsNegate,
                    {group_sql}
                    StartVersion_Id,
                    EndVersion_Id
                FROM Buff
                WHERE Level<=?
                ORDER BY Level, Name, Id
                """,
                (int(lvl),),
            ).fetchall()
        except Exception:
            rows = []

        guild_ids = self._get_active_guild_talent_ids()
        card_ids = self._get_equipped_card_ids()
        stamp_ids = self._get_equipped_stamp_ids()
        active_talent_ids = self._get_active_talent_ids()

        current_class_id = _safe_int(self._current_class_id, 0)
        class_lineage = set(self._class_lineage_ids(current_class_id))

        out: list[dict] = []

        for r in rows or []:
            try:
                if hasattr(r, "keys"):
                    row = {
                        "Id": _safe_int(r["Id"], 0),
                        "Name": _to_str(r["Name"]),
                        "MaxStackCount": _safe_int(r["MaxStackCount"], 0),
                        "Level": _safe_int(r["Level"], 0),
                        "Class_Id": _safe_int(r["Class_Id"], 0),
                        "Card_Id": _safe_int(r["Card_Id"], 0),
                        "Stamp_Id": _safe_int(r["Stamp_Id"], 0),
                        "TalentCondition_Id": _safe_int(r["TalentCondition_Id"], 0),
                        "GuildCondition_Id": _safe_int(r["GuildCondition_Id"], 0),
                        "AutoEnabled": _safe_int(r["AutoEnabled"], 0),
                        "Image_Id": _safe_int(r["Image_Id"], 0),
                        "IsNegate": _safe_int(r["IsNegate"], 0),
                        "GroupValue": _safe_int(r["GroupValue"], -1) if r["GroupValue"] is not None else None,
                    }
                else:
                    row = {
                        "Id": _safe_int(r[0], 0),
                        "Name": _to_str(r[1]),
                        "MaxStackCount": _safe_int(r[2], 0),
                        "Level": _safe_int(r[3], 0),
                        "Class_Id": _safe_int(r[4], 0),
                        "Card_Id": _safe_int(r[5], 0),
                        "Stamp_Id": _safe_int(r[6], 0),
                        "TalentCondition_Id": _safe_int(r[7], 0),
                        "GuildCondition_Id": _safe_int(r[8], 0),
                        "AutoEnabled": _safe_int(r[9], 0),
                        "Image_Id": _safe_int(r[10], 0),
                        "IsNegate": _safe_int(r[11], 0),
                        "GroupValue": _safe_int(r[12], -1) if r[12] is not None else None,
                    }
            except Exception:
                continue

            bid = _safe_int(row.get("Id"), 0)
            if bid <= 0:
                continue

            class_id = _safe_int(row.get("Class_Id"), 0)
            card_id = _safe_int(row.get("Card_Id"), 0)
            stamp_id = _safe_int(row.get("Stamp_Id"), 0)
            talent_cond_id = _safe_int(row.get("TalentCondition_Id"), 0)
            guild_cond_id = _safe_int(row.get("GuildCondition_Id"), 0)
            is_negate = _safe_int(row.get("IsNegate"), 0)
            group_val = row.get("GroupValue", None)

            talent_ok = (talent_cond_id <= 0 or talent_cond_id in active_talent_ids)
            class_ok = (class_id > 0 and current_class_id > 0 and class_id in class_lineage)

            is_personal_by_class = bool(class_ok)
            is_personal_by_group = (group_val == 0)
            is_party_by_group = (group_val == 1)
            is_guild_by_condition = (guild_cond_id > 0 and guild_cond_id in guild_ids)

            match = False

            if tab == self.TAB_1:
                match = (
                        is_negate == 0
                        and talent_ok
                        and (is_personal_by_class or is_personal_by_group)
                )

            elif tab == self.TAB_2:
                match = (
                        is_negate == 0
                        and class_id <= 0
                        and card_id <= 0
                        and stamp_id <= 0
                        and talent_cond_id <= 0
                        and guild_cond_id <= 0
                        and group_val not in (0, 1)
                )

            elif tab == self.TAB_3:
                match = (
                        is_negate == 0
                        and talent_ok
                        and (
                                is_party_by_group
                                or is_guild_by_condition
                        )
                )

            elif tab == self.TAB_4:
                match = (is_negate == 0 and card_id > 0 and card_id in card_ids)

            elif tab == self.TAB_5:
                match = (is_negate == 0 and stamp_id > 0 and stamp_id in stamp_ids)

            elif tab == self.TAB_6:
                match = (is_negate == 1)

            if match:
                out.append(row)

        return out

    def _on_item_value_changed(self, tab: str, buff_id: int, index: int, text: str) -> None:
        t = _to_str(tab).strip().lower()
        bid = _safe_int(buff_id, 0)
        idx = max(0, _safe_int(index, 0))

        if t not in self.TABS or bid <= 0:
            return

        if t not in self._combo_index_by_tab:
            self._combo_index_by_tab[t] = {}

        self._combo_index_by_tab[t][int(bid)] = int(idx)
        self._publish_selected_buffs(refresh_stats=True)

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
        tab = self._active_tab
        lay = self._vboxes.get(tab)
        if lay is None:
            return

        self._clear_layout(lay)

        base_pm = self._block_pixmap()
        active_pm = self._block_active_pixmap()

        rows = self._query_buffs_for_tab(tab)
        state_map = self._combo_index_by_tab.setdefault(tab, {})

        if not isinstance(state_map, dict):
            state_map = {}
            self._combo_index_by_tab[tab] = state_map

        removed_active = False

        visible_ids = {
            _safe_int(r.get("Id"), 0)
            for r in rows
            if isinstance(r, dict) and _safe_int(r.get("Id"), 0) > 0
        }

        for old_id in list(state_map.keys()):
            oid = _safe_int(old_id, 0)

            if oid <= 0:
                state_map.pop(old_id, None)
                continue

            if int(oid) not in visible_ids:
                old_idx = _safe_int(state_map.get(old_id), 0)
                if old_idx > 0:
                    removed_active = True
                state_map.pop(old_id, None)

        for row in rows:
            buff_id = _safe_int(row.get("Id"), 0)
            if buff_id <= 0:
                continue

            options = self._combo_options_for_buff(row)

            if buff_id in state_map:
                current_index = max(
                    0,
                    min(len(options) - 1, _safe_int(state_map.get(buff_id), 0)),
                )
            else:
                current_index = self._default_combo_index_for_row(row)
                current_index = max(0, min(len(options) - 1, int(current_index)))
                state_map[buff_id] = int(current_index)

            icon_pm = self._image_pm(_safe_int(row.get("Image_Id"), 0))

            w = _BuffDebuffItemWidget(
                self._containers.get(tab),
                item_id=int(buff_id),
                base_pm=base_pm,
                active_pm=active_pm,
                combo_rect=self._layout.combo_rect,
                name_rect=self._layout.name_rect,
                icon_rect=self._layout.icon_rect,
                icon_pm=icon_pm,
                name_text=_to_str(row.get("Name")),
                options=options,
                current_index=current_index,
            )

            try:
                w.value_changed.connect(
                    lambda item_id, index, text, _tab=tab: self._on_item_value_changed(
                        _tab,
                        item_id,
                        index,
                        text,
                    )
                )
            except Exception:
                pass

            lay.addWidget(w, alignment=Qt.AlignTop | Qt.AlignLeft)

        lay.addStretch(1)

        # Если баф исчез из-за снятой карты/печати/таланта и он был выбран,
        # надо не просто обновить app property, а ещё пересчитать статы.
        self._publish_selected_buffs(refresh_stats=bool(removed_active))

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


class BuffDebuffMenuWindow(QFrame):
    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None, *, layout: Optional["BuffDebuffMenu.LayoutConfig"] = None):
        super().__init__(parent)
        self.setObjectName("BuffDebuffMenuWindow")

        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")

        self._drag_pos: Optional[QPoint] = None
        self._last_pos: Optional[QPoint] = None

        self.menu = BuffDebuffMenu(self, layout=layout)
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

    def set_class_id(self, class_id: int) -> None:
        try:
            self.menu.set_class_id(_safe_int(class_id, 0))
        except Exception:
            pass

    def set_level(self, level: int) -> None:
        try:
            self.menu.set_level(_safe_int(level, 0))
        except Exception:
            pass

    def refresh_runtime_context(self) -> None:
        try:
            if hasattr(self, "menu") and self.menu is not None:
                self.menu.refresh_runtime_context()
        except Exception:
            pass

    def get_active_preview_items(self, group: str) -> list[dict]:
        try:
            if hasattr(self, "menu") and self.menu is not None:
                return list(self.menu.get_active_preview_items(group))
        except Exception:
            pass

        return []

    def open_centered(self, parent: Optional[QWidget] = None) -> None:
        host = parent if isinstance(parent, QWidget) else self.parentWidget()

        try:
            if hasattr(self, "menu") and self.menu is not None:
                self.menu._reset_close_visuals()
                self.menu.refresh_runtime_context()
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