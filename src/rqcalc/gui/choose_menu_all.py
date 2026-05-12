# choose_menu_all.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, List, Tuple, Any, Dict

from PySide6.QtCore import Qt, QRect, QSize, QPoint, Signal, QEvent, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QFontMetrics, QCursor
from PySide6.QtWidgets import (
    QWidget, QLabel, QApplication, QLineEdit, QScrollArea, QVBoxLayout, QFrame
)

# Картинковый скроллбар как в weapon_equipment_button.py
try:
    from .weapon_equipment_button import ImageVScrollBar, _find_scroll_dir  # type: ignore
except Exception:
    ImageVScrollBar = None  # type: ignore
    _find_scroll_dir = None  # type: ignore


def _resolve_resource(rel: str) -> str:
    """
    Ищем ресурс как:
      - CWD/rel
      - .../src/.. (как в остальных окнах проекта)
    """
    p = Path(rel)
    for c in (
        Path.cwd() / p,
        Path(__file__).resolve().parents[2] / p,
        Path(__file__).resolve().parents[3] / p,
    ):
        if c.exists():
            return str(c)
    return str(p)


# =============================================================================
#  EQUIPMENT CHOOSE MENU (24 slots)
# =============================================================================
@dataclass
class ChooseMenuConfig:
    bg_path: str = "resources/choose_menu/equip_choose.png"
    # размер фона (если картинка не нашлась — используем это как fallback)
    fallback_size: Tuple[int, int] = (371, 278)

    # сетка слотов ВНУТРИ картинки
    grid_origin: Tuple[int, int] = (18, 41)
    cols: int = 6
    rows: int = 4
    slot_px: int = 50
    gap_px: int = 6


class _ChooseCell(QWidget):
    """
    Одна ячейка (slot_px x slot_px). Рисуем иконку и «свечение» как в inventory.
    """
    hovered = Signal(object)   # self
    unhovered = Signal(object) # self
    clicked = Signal(object)   # self

    def __init__(self, parent: QWidget, idx: int, *, size_px: int):
        super().__init__(parent)
        self._idx = int(idx)
        self._hover = False
        self._pm: Optional[QPixmap] = None
        self.slot_key: Optional[str] = None
        self.item: Optional[dict] = None

        self.setFixedSize(int(size_px), int(size_px))
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)

        # чтобы не было «replay» клика сквозь popup
        self.setAttribute(Qt.WA_NoMouseReplay, True)

    def set_payload(self, slot_key: Optional[str], item: Optional[dict], pm: Optional[QPixmap]) -> None:
        # При переоткрытии меню ячейка может физически остаться под курсором,
        # но Qt не всегда пришлёт новый Enter. Поэтому hover сбрасываем,
        # а ChooseMenuAll после show() сам пересчитает ячейку под курсором.
        self._hover = False
        self._armed_click = False

        self.slot_key = str(slot_key) if slot_key else None
        self.item = dict(item) if isinstance(item, dict) else None
        self._pm = pm if (pm and not pm.isNull()) else None
        self.update()

    def _set_hover(self, on: bool) -> None:
        on = bool(on)
        if self._hover == on:
            return
        self._hover = on
        self.update()
        if on:
            self.hovered.emit(self)
        else:
            self.unhovered.emit(self)

    def enterEvent(self, _ev) -> None:
        self._set_hover(True)
        super().enterEvent(_ev)

    def mouseMoveEvent(self, ev) -> None:
        # Доп. страховка: если Enter потерялся, но курсор двигается внутри ячейки,
        # всё равно включаем hover и вызываем анкету.
        if self.item and self.slot_key:
            self._set_hover(True)
        super().mouseMoveEvent(ev)

    def leaveEvent(self, _ev) -> None:
        self._set_hover(False)
        super().leaveEvent(_ev)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._armed_click = bool(self.item)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            armed = bool(getattr(self, "_armed_click", False))
            self._armed_click = False

            inside = False
            try:
                inside = self.rect().contains(ev.position().toPoint())
            except Exception:
                try:
                    inside = self.rect().contains(ev.pos())
                except Exception:
                    inside = False

            if armed and inside and self.item:
                self.clicked.emit(self)

            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        r = self.rect()

        # иконка — заполняем весь 50x50
        if self._pm and not self._pm.isNull():
            scaled = self._pm.scaled(r.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            sx = max(0, (scaled.width() - r.width()) // 2)
            sy = max(0, (scaled.height() - r.height()) // 2)
            src = QRect(sx, sy, r.width(), r.height())
            p.drawPixmap(r, scaled, src)

        if self._hover:
            # <-- было r.adjusted(2,2,-2,-2), делаем по краю (свечение больше)
            rr = r.adjusted(0, 0, -0, -0)

            p.setPen(Qt.NoPen)
            p.setBrush(QColor(240, 220, 140, 45))
            p.drawRoundedRect(rr, 3, 3)

            pen = QPen(QColor(240, 220, 140, 210))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rr, 5, 5)

        p.end()


class ChooseMenuAll(QWidget):
    """
    Универсальное меню выбора экипировки (24 слота) для stamp_window и reforge.
    Внешний код:
      - собирает список (slot_key, item_dict)
      - даёт icon_provider(item)->QPixmap
      - даёт callbacks hover_enter/hover_leave/pick
    """
    def __init__(self, parent: QWidget, *, config: Optional[ChooseMenuConfig] = None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoMouseReplay, True)

        self.cfg = config or ChooseMenuConfig()

        # фон
        bg_path = _resolve_resource(self.cfg.bg_path)
        self._bg_pm = QPixmap(bg_path)
        if self._bg_pm.isNull():
            w, h = self.cfg.fallback_size
            self._bg_pm = QPixmap(int(w), int(h))
            self._bg_pm.fill(QColor(0, 0, 0, 0))

        self.setFixedSize(self._bg_pm.size())

        self._bg = QLabel(self)
        self._bg.setPixmap(self._bg_pm)
        self._bg.setScaledContents(True)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        self._bg.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # callbacks
        self._icon_provider: Optional[Callable[[dict], Optional[QPixmap]]] = None
        self._on_pick: Optional[Callable[[str, dict], None]] = None
        self._on_hover_enter: Optional[Callable[[QWidget, str, dict], None]] = None
        self._on_hover_leave: Optional[Callable[[QWidget], None]] = None

        self._last_hover_cell: Optional[_ChooseCell] = None

        # слоты
        self._cells: List[_ChooseCell] = []
        self._build_cells()

        self.hide()

    # ---------- public ----------
    def open_for(
            self,
            *,
            anchor_widget: QWidget,
            items: List[Tuple[str, dict]],
            icon_provider: Callable[[dict], Optional[QPixmap]],
            on_pick: Callable[[str, dict], None],
            on_hover_enter: Optional[Callable[[QWidget, str, dict], None]] = None,
            on_hover_leave: Optional[Callable[[QWidget], None]] = None,
    ) -> None:
        """
        Показываем меню рядом с anchor_widget.
        Данные записываем в 24 ячейки слева-направо, сверху-вниз.

        ВАЖНО:
        после show() принудительно пересчитываем ячейку под курсором.
        Иначе если popup открылся прямо под мышкой, Qt может не прислать Enter,
        и анкета предмета не появится.
        """
        self._icon_provider = icon_provider
        self._on_pick = on_pick
        self._on_hover_enter = on_hover_enter
        self._on_hover_leave = on_hover_leave

        self._fill(items)

        hint = self.sizeHint()
        tl = anchor_widget.mapToGlobal(anchor_widget.rect().bottomLeft())
        x, y = tl.x(), tl.y() + 6

        scr = (
            anchor_widget.window().screen().availableGeometry()
            if anchor_widget.window()
            else QApplication.primaryScreen().availableGeometry()
        )

        if x + hint.width() > scr.right() - 6:
            x = max(scr.left() + 6, scr.right() - hint.width() - 6)
        if y + hint.height() > scr.bottom() - 6:
            y = anchor_widget.mapToGlobal(anchor_widget.rect().topLeft()).y() - hint.height() - 6

        self.move(int(x), int(y))
        self.show()
        self.raise_()
        self.activateWindow()

        # Критично для стабильного появления анкет.
        QTimer.singleShot(0, self._refresh_hover_from_cursor)
        QTimer.singleShot(30, self._refresh_hover_from_cursor)

    # ---------- internal ----------
    def _build_cells(self) -> None:
        gx, gy = self.cfg.grid_origin
        cols = int(self.cfg.cols)
        rows = int(self.cfg.rows)
        slot = int(self.cfg.slot_px)
        gap = int(self.cfg.gap_px)

        total = cols * rows
        for i in range(total):
            r, c = divmod(i, cols)
            x = int(gx + c * (slot + gap))
            y = int(gy + r * (slot + gap))

            cell = _ChooseCell(self, i, size_px=slot)
            cell.move(x, y)
            cell.hovered.connect(self._on_cell_hovered)
            cell.unhovered.connect(self._on_cell_unhovered)
            cell.clicked.connect(self._on_cell_clicked)
            self._cells.append(cell)

        # фон не ловит мышь
        self._bg.lower()
        for c in self._cells:
            c.raise_()

    def _fill(self, items: List[Tuple[str, dict]]) -> None:
        # Закрываем старую анкету от прошлой hovered-ячейки.
        old_hover = getattr(self, "_last_hover_cell", None)
        if old_hover is not None:
            cb_leave = self._on_hover_leave
            if callable(cb_leave):
                try:
                    cb_leave(old_hover)
                except Exception:
                    pass

        self._last_hover_cell = None

        # нормализуем
        norm: List[Tuple[str, dict]] = []
        for sk, it in (items or []):
            if not sk or not isinstance(it, dict) or not it:
                continue
            norm.append((str(sk), dict(it)))

        for i, cell in enumerate(self._cells):
            if i < len(norm):
                sk, it = norm[i]
                pm = None
                try:
                    if callable(self._icon_provider):
                        pm = self._icon_provider(it)
                except Exception:
                    pm = None

                cell.set_payload(sk, it, pm)
                cell.show()
            else:
                cell.set_payload(None, None, None)
                cell.show()

        self._bg.lower()
        for c in self._cells:
            c.raise_()

    def _cell_at_global_pos(self, global_pos: QPoint) -> Optional[_ChooseCell]:
        """
        Надёжно ищет ячейку под курсором.
        Нужно потому что Qt.Popup иногда открывается уже под мышкой,
        и обычный enterEvent у _ChooseCell не приходит.
        """
        try:
            w = QApplication.widgetAt(global_pos)
        except Exception:
            w = None

        cur = w
        while cur is not None:
            if isinstance(cur, _ChooseCell) and cur in self._cells:
                return cur
            try:
                if cur is self:
                    break
                cur = cur.parentWidget()
            except Exception:
                cur = None

        try:
            local = self.mapFromGlobal(global_pos)
            child = self.childAt(local)
        except Exception:
            child = None

        cur = child
        while cur is not None:
            if isinstance(cur, _ChooseCell) and cur in self._cells:
                return cur
            try:
                if cur is self:
                    break
                cur = cur.parentWidget()
            except Exception:
                cur = None

        return None

    def _refresh_hover_from_cursor(self) -> None:
        """
        Принудительно синхронизирует hover по текущей позиции курсора.
        Благодаря этому анкета появляется даже если popup открылся прямо под мышкой.
        """
        if not self.isVisible():
            return

        cell = self._cell_at_global_pos(QCursor.pos())

        for c in self._cells:
            should_hover = bool(c is cell and c.item and c.slot_key)
            try:
                c._set_hover(should_hover)
            except Exception:
                pass

    def _on_cell_hovered(self, cell: _ChooseCell) -> None:
        self._last_hover_cell = cell
        if not (cell and cell.item and cell.slot_key):
            return
        cb = self._on_hover_enter
        if callable(cb):
            try:
                cb(cell, str(cell.slot_key), dict(cell.item))
            except Exception:
                pass

    def _on_cell_unhovered(self, cell: _ChooseCell) -> None:
        if self._last_hover_cell is cell:
            self._last_hover_cell = None
        cb = self._on_hover_leave
        if callable(cb):
            try:
                cb(cell)
            except Exception:
                pass

    def _on_cell_clicked(self, cell: _ChooseCell) -> None:
        if not (cell and cell.item and cell.slot_key):
            return

        cb = self._on_pick
        if callable(cb):
            try:
                cb(str(cell.slot_key), dict(cell.item))
            except Exception:
                pass

        self.hide()

    def hideEvent(self, ev) -> None:
        # Закрываем тултип на последней наведённой ячейке
        # и сбрасываем hover у всех ячеек.
        for cell in list(getattr(self, "_cells", []) or []):
            try:
                cell._set_hover(False)
            except Exception:
                pass

        self._last_hover_cell = None
        super().hideEvent(ev)


# =============================================================================
#  STAMP CHOOSE MENU (scroll + search + blocks)
# =============================================================================
@dataclass
class StampChooseConfig:
    bg_path: str = "resources/choose_menu/stamp_choose.png"
    fallback_size: Tuple[int, int] = (503, 372)

    # поиск (позиция/размер можно менять)
    search_rect: Tuple[int, int, int, int] = (18, 55, 500, 28)

    # область контента, привязанная к скроллу
    content_rect: Tuple[int, int, int, int] = (17, 114, 499, 241)

    # блок печати
    block_bg_path: str = "resources/choose_menu/stamp_block.png"
    block_size: Tuple[int, int] = (499, 89)
    block_gap_y: int = 1

    # кастомный скроллер: если задано — ставим строго так,
    # иначе автоматически справа внутри content_rect.
    vscroll_rect: Optional[Tuple[int, int, int, int]] = (519, 115, 18, 239)
    vscroll_margin: int = 6


class _StampBlock(QWidget):
    hovered = Signal(object)   # self
    unhovered = Signal(object) # self
    clicked = Signal(object)   # self

    def __init__(self, parent: QWidget, *, bg_pm: Optional[QPixmap], size: Tuple[int, int]):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_NoMouseReplay, True)

        self._bg_pm = bg_pm if (bg_pm and not bg_pm.isNull()) else None
        w, h = int(size[0]), int(size[1])
        self.setFixedSize(w, h)

        self._hover = False
        self.stamp_id: int = 0
        self.name: str = ""
        self.bonuses: List[str] = []

    def set_payload(self, stamp_id: int, name: str, bonuses: List[str]) -> None:
        self.stamp_id = int(stamp_id or 0)
        self.name = str(name or "")
        self.bonuses = list(bonuses or [])
        self.update()

    def _set_hover(self, on: bool) -> None:
        on = bool(on)
        if self._hover == on:
            return
        self._hover = on
        self.update()
        if on:
            self.hovered.emit(self)
        else:
            self.unhovered.emit(self)

    def enterEvent(self, _ev) -> None:
        self._set_hover(True)
        super().enterEvent(_ev)

    def leaveEvent(self, _ev) -> None:
        self._set_hover(False)
        super().leaveEvent(_ev)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._armed_click = (int(self.stamp_id or 0) > 0)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            armed = bool(getattr(self, "_armed_click", False))
            self._armed_click = False

            inside = False
            try:
                inside = self.rect().contains(ev.position().toPoint())
            except Exception:
                try:
                    inside = self.rect().contains(ev.pos())
                except Exception:
                    inside = False

            if armed and inside and int(self.stamp_id or 0) > 0:
                self.clicked.emit(self)

            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        r = self.rect()

        # фон блока
        if self._bg_pm and not self._bg_pm.isNull():
            p.drawPixmap(r, self._bg_pm)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 20, 24, 235))
            p.drawRoundedRect(r.adjusted(0, 0, -1, -1), 8, 8)

        # свечение при наведении
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(240, 220, 140, 35))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 6, 6)

            pen = QPen(QColor(240, 220, 140, 200))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 6, 6)

        # текст
        name = self.name or ""
        bons = self.bonuses or []

        # область имени
        name_rect = QRect(14, 10, 170, r.height() - 20)
        f = QFont()
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(235, 235, 235, 235))
        p.drawText(name_rect, Qt.TextWordWrap | Qt.AlignVCenter | Qt.AlignLeft, name)

        # область бонусов
        b_rect = QRect(230, 4, r.width() - 240, r.height() - 10)
        f2 = QFont()
        f2.setBold(False)
        p.setFont(f2)
        p.setPen(QColor(207, 230, 165, 235))

        if bons:
            # ограничим по высоте блока (обычно 2-3 строки)
            text = "\n".join([str(x) for x in bons[:3]])
        else:
            text = "—"
        p.drawText(b_rect, Qt.TextWordWrap | Qt.AlignVCenter | Qt.AlignLeft, text)

        p.end()


class ChooseStampMenu(QWidget):
    """
    Меню выбора печати:
      - фон stamp_choose.png (503x372)
      - поисковая строка (позиция/размер настраиваемы)
      - scroll-area (позиция/размер настраиваемы)
      - элементы списка — блоки на stamp_block.png (499x65), шаг 1px
      - кастомный ImageVScrollBar как в stamp_window.py
    """
    def __init__(self, parent: QWidget, *, config: Optional[StampChooseConfig] = None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoMouseReplay, True)

        self.cfg = config or StampChooseConfig()

        # фон меню
        bg_path = _resolve_resource(self.cfg.bg_path)
        self._bg_pm = QPixmap(bg_path)
        if self._bg_pm.isNull():
            w, h = self.cfg.fallback_size
            self._bg_pm = QPixmap(int(w), int(h))
            self._bg_pm.fill(QColor(0, 0, 0, 0))

        self.setFixedSize(self._bg_pm.size())

        self._bg = QLabel(self)
        self._bg.setPixmap(self._bg_pm)
        self._bg.setScaledContents(True)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        self._bg.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # фон блока
        block_path = _resolve_resource(self.cfg.block_bg_path)
        self._block_pm = QPixmap(block_path)
        if self._block_pm.isNull():
            self._block_pm = None

        # callbacks
        self._on_pick: Optional[Callable[[int, str, List[str]], None]] = None
        self._on_search_changed: Optional[Callable[[str], None]] = None

        # search
        sx, sy, sw, sh = self.cfg.search_rect
        self.search_edit = QLineEdit(self)
        self.search_edit.setGeometry(int(sx), int(sy), int(sw), int(sh))
        self.search_edit.setPlaceholderText("Поиск (название / бонусы)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setStyleSheet(
            "QLineEdit{background: rgba(0,0,0,0); border: 0px; color:#eaeaea; padding-left:6px;}"
            "QLineEdit:focus{outline:none;}"
        )
        self.search_edit.textChanged.connect(self._on_search_text_changed)

        # content + scroll
        cx, cy, cw, ch = self.cfg.content_rect

        self._area = QScrollArea(self)
        self._area.setGeometry(int(cx), int(cy), int(cw), int(ch))
        self._area.setFrameShape(QFrame.NoFrame)
        self._area.setWidgetResizable(True)
        self._area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._cont = QWidget()
        self._area.setWidget(self._cont)

        self._vbox = QVBoxLayout(self._cont)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(int(self.cfg.block_gap_y))

        # custom scrollbar
        self._sv_custom = None
        if ImageVScrollBar is not None and callable(_find_scroll_dir):
            try:
                self._sv_custom = ImageVScrollBar(
                    self._area.verticalScrollBar(),
                    _find_scroll_dir(),
                    parent=self,
                )
                self._sv_custom.hide()
            except Exception:
                self._sv_custom = None

        vb = self._area.verticalScrollBar()
        vb.setSingleStep(24)
        vb.setPageStep(120)
        vb.rangeChanged.connect(lambda _a, _b: self._sync_scrollbar_visible())

        self.installEventFilter(self)

        QTimer.singleShot(0, self._place_vscroll)
        self.hide()

    # ---------- public ----------
    def open_for(
        self,
        *,
        anchor_widget: QWidget,
        entries: List[Dict[str, Any]],
        on_pick: Callable[[int, str, List[str]], None],
        on_search_changed: Optional[Callable[[str], None]] = None,
        initial_search: str = "",
        focus_search: bool = True,
    ) -> None:
        """
        entries: [{"id": int, "name": str, "bonuses": list[str]}, ...]
        """
        self._on_pick = on_pick
        self._on_search_changed = on_search_changed

        try:
            self.search_edit.blockSignals(True)
            self.search_edit.setText(str(initial_search or ""))
        finally:
            self.search_edit.blockSignals(False)

        self.set_entries(entries)

        # позиционирование как у popup'ов
        hint = self.sizeHint()
        tl = anchor_widget.mapToGlobal(anchor_widget.rect().bottomLeft())
        x, y = tl.x(), tl.y() + 6

        scr = (
            anchor_widget.window().screen().availableGeometry()
            if anchor_widget.window()
            else QApplication.primaryScreen().availableGeometry()
        )

        if x + hint.width() > scr.right() - 6:
            x = max(scr.left() + 6, scr.right() - hint.width() - 6)
        if y + hint.height() > scr.bottom() - 6:
            y = anchor_widget.mapToGlobal(anchor_widget.rect().topLeft()).y() - hint.height() - 6

        self.move(int(x), int(y))
        self.show()
        self.raise_()
        self.activateWindow()

        QTimer.singleShot(0, self._place_vscroll)

        if focus_search:
            QTimer.singleShot(0, self._focus_search)

    def set_entries(self, entries: List[Dict[str, Any]]) -> None:
        self._clear_blocks()

        bsz = self.cfg.block_size
        for e in (entries or []):
            try:
                sid = int(e.get("id") or 0)
            except Exception:
                sid = 0
            name = str(e.get("name") or "")
            bonuses = list(e.get("bonuses") or [])

            block = _StampBlock(self._cont, bg_pm=self._block_pm, size=bsz)
            block.set_payload(sid, name, bonuses)
            block.clicked.connect(self._on_block_clicked)
            self._vbox.addWidget(block)

        self._vbox.addStretch(1)
        QTimer.singleShot(0, self._sync_scrollbar_visible)

    # ---------- internal ----------
    def _clear_blocks(self) -> None:
        while self._vbox.count():
            it = self._vbox.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _on_block_clicked(self, blk: _StampBlock) -> None:
        sid = int(getattr(blk, "stamp_id", 0) or 0)
        if sid <= 0:
            return
        cb = self._on_pick
        if callable(cb):
            try:
                cb(sid, str(getattr(blk, "name", "") or ""), list(getattr(blk, "bonuses", []) or []))
            except Exception:
                pass
        self.hide()

    def _on_search_text_changed(self, txt: str) -> None:
        cb = self._on_search_changed
        if callable(cb):
            try:
                cb(str(txt or ""))
            except Exception:
                pass

    def _focus_search(self) -> None:
        try:
            self.search_edit.setFocus(Qt.ActiveWindowFocusReason)
            self.search_edit.selectAll()
        except Exception:
            pass

    def _sync_scrollbar_visible(self) -> None:
        if self._sv_custom is None:
            return
        try:
            vb = self._area.verticalScrollBar()
            self._sv_custom.setVisible(vb.maximum() > 0)
        except Exception:
            pass

    def _place_vscroll(self) -> None:
        if self._sv_custom is None:
            return

        try:
            if self.cfg.vscroll_rect:
                x, y, w, h = self.cfg.vscroll_rect
                self._sv_custom.setGeometry(int(x), int(y), int(w), int(h))
                self._sync_scrollbar_visible()
                return

            cx, cy, cw, ch = self.cfg.content_rect
            margin = int(self.cfg.vscroll_margin)
            ar = QRect(int(cx), int(cy), int(cw), int(ch))
            x = ar.right() - self._sv_custom.width() - margin
            y = ar.top() + margin
            h = max(1, ar.height() - margin * 2)
            self._sv_custom.setGeometry(int(x), int(y), int(self._sv_custom.width()), int(h))
            self._sync_scrollbar_visible()
        except Exception:
            pass

    def eventFilter(self, obj, ev) -> bool:
        if obj is self and ev.type() == QEvent.Resize:
            QTimer.singleShot(0, self._place_vscroll)
            return False
        return super().eventFilter(obj, ev)

    def hideEvent(self, ev) -> None:
        # при закрытии — не оставляем фокус в поиске
        try:
            self.search_edit.clearFocus()
        except Exception:
            pass
        super().hideEvent(ev)


class _MiniVScroll(QWidget):
    valueChanged = Signal(int)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_NoMouseReplay, True)
        self._content_h = 0
        self._view_h = 0
        self._max_value = 0
        self._value = 0

        self._dragging = False
        self._drag_off = 0

        self.setFixedWidth(10)

    def set_range(self, content_h: int, view_h: int) -> None:
        self._content_h = max(0, int(content_h))
        self._view_h = max(0, int(view_h))
        self._max_value = max(0, self._content_h - self._view_h)
        if self._value > self._max_value:
            self._value = self._max_value
            self.valueChanged.emit(int(self._value))
        self.setVisible(self._max_value > 0)
        self.update()

    def set_value(self, v: int) -> None:
        v = max(0, min(int(v), int(self._max_value)))
        if v == self._value:
            return
        self._value = v
        self.valueChanged.emit(int(self._value))
        self.update()

    def value(self) -> int:
        return int(self._value)

    def maximum(self) -> int:
        return int(self._max_value)

    def _track_rect(self) -> QRect:
        return self.rect().adjusted(2, 2, -2, -2)

    def _thumb_h(self) -> int:
        tr = self._track_rect()
        if tr.height() <= 0 or self._content_h <= 0:
            return 10
        if self._max_value <= 0:
            return tr.height()
        ratio = float(self._view_h) / float(self._content_h) if self._content_h else 1.0
        h = int(tr.height() * ratio)
        return max(12, min(tr.height(), h))

    def _thumb_rect(self) -> QRect:
        tr = self._track_rect()
        th = self._thumb_h()
        if self._max_value <= 0:
            return QRect(tr.x(), tr.y(), tr.width(), tr.height())

        span = max(1, tr.height() - th)
        y = tr.y() + int(span * (float(self._value) / float(self._max_value)))
        return QRect(tr.x(), y, tr.width(), th)

    def _value_from_thumb_top(self, y_top: int) -> int:
        tr = self._track_rect()
        th = self._thumb_h()
        span = max(1, tr.height() - th)
        rel = max(0, min(y_top - tr.y(), span))
        return int(round(float(rel) * float(self._max_value) / float(span))) if self._max_value > 0 else 0

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        tr = self._track_rect()

        # track
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 35))
        p.drawRoundedRect(tr, 4, 4)

        # thumb
        th = self._thumb_rect()
        p.setBrush(QColor(255, 255, 255, 120))
        p.drawRoundedRect(th, 4, 4)
        p.end()

    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)

        th = self._thumb_rect()
        if th.contains(ev.pos()):
            self._dragging = True
            self._drag_off = int(ev.pos().y() - th.y())
            ev.accept()
            return

        # клик по треку = прыгнуть
        tr = self._track_rect()
        y_top = int(ev.pos().y() - self._thumb_h() // 2)
        y_top = max(tr.y(), min(y_top, tr.bottom() - self._thumb_h() + 1))
        self.set_value(self._value_from_thumb_top(y_top))
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        if not self._dragging:
            return super().mouseMoveEvent(ev)

        tr = self._track_rect()
        y_top = int(ev.pos().y() - self._drag_off)
        y_top = max(tr.y(), min(y_top, tr.bottom() - self._thumb_h() + 1))
        self.set_value(self._value_from_thumb_top(y_top))
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            ev.accept()
            return
        super().mouseReleaseEvent(ev)


# =============================================================================
#  ITEM CHOOSE MENU (scroll + search + blocks)
# =============================================================================
from typing import Any  # если у тебя нет Any в импортах — добавь вверху (или оставь тут)

@dataclass
class ItemChooseConfig:
    """UI-конфиг для меню выбора предметов."""

    bg_path: str = "resources/choose_menu/item_choose.png"
    fallback_size: Tuple[int, int] = (503, 372)

    # поиск
    search_rect: Tuple[int, int, int, int] = (18, 55, 500, 28)

    # область контента
    content_rect: Tuple[int, int, int, int] = (17, 114, 499, 241)

    # ✅ ОДИН БЛОК ДЛЯ ВСЕХ
    block_bg_path: str = "resources/choose_menu/item_block.png"
    block_size: Tuple[int, int] = (499, 89)
    block_gap_y: int = 1

    # скролл списка
    vscroll_rect: Optional[Tuple[int, int, int, int]] = (519, 115, 18, 239)
    vscroll_margin: int = 6

    # --- разметка внутри блока (координаты относительно item_block.png) ---
    # (можешь дальше подкручивать как обычно)
    icon_rect: Tuple[int, int, int, int] = (9, 20, 50, 50)

    name_rect: Tuple[int, int, int, int] = (66, 8, 160, 34)
    base_stat_rect: Tuple[int, int, int, int] = (66, 46, 160, 20)

    req_level_rect: Tuple[int, int, int, int] = (240, 8, 32, 77)

    # ✅ область бонусов — как ты сказал
    bonuses_rect: Tuple[int, int, int, int] = (290, 4, 205, 77)

    # мини-скролл бонусов (внутри блока)
    bonus_scrollbar_w: int = 10
    bonus_scrollbar_gap: int = 4
    bonus_wheel_step_px: int = 24


class _ItemBlock(QWidget):
    hovered = Signal(object)   # self
    unhovered = Signal(object) # self
    clicked = Signal(object)   # self

    def __init__(
        self,
        parent: QWidget,
        *,
        cfg: ItemChooseConfig,
        bg_pm: Optional[QPixmap],
        size: Tuple[int, int],
    ):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_NoMouseReplay, True)

        self.cfg = cfg
        self._bg_pm = bg_pm if (bg_pm and not bg_pm.isNull()) else None

        w, h = int(size[0]), int(size[1])
        self.setFixedSize(w, h)

        self._hover = False
        self.item: Optional[Dict[str, Any]] = None
        self.bonus_lines: List[str] = []
        self._icon_pm: Optional[QPixmap] = None

        # для бонусов
        self._bonus_text: str = ""
        self._bonus_scroll = 0
        self._bonus_total_h = 0
        self._font_bonus = QFont("Segoe UI", 9)

        # ✅ мини-скролл рядом с бонусами (как у card_block)
        self._mini = _MiniVScroll(self)
        self._mini.valueChanged.connect(self._on_mini_scroll)
        self._mini.hide()

    def set_payload(self, item: Dict[str, Any], bonus_lines: List[str], icon_pm: Optional[QPixmap]) -> None:
        self.item = dict(item) if isinstance(item, dict) else None
        self.bonus_lines = list(bonus_lines or [])
        self._icon_pm = icon_pm if (icon_pm and not icon_pm.isNull()) else None

        # бонусы одним текстом
        lines = [str(x) for x in (self.bonus_lines or []) if str(x).strip()]
        self._bonus_text = "\n".join(lines).replace("\r", "").strip()
        self._bonus_scroll = 0

        # посчитать высоту бонусов и показать/скрыть мини-скролл
        bx, by, bw, bh = self.cfg.bonuses_rect
        view_h = int(bh)

        sb_w = int(self.cfg.bonus_scrollbar_w)
        gap = int(self.cfg.bonus_scrollbar_gap)

        fm = QFontMetrics(self._font_bonus)

        total_h = 0
        if self._bonus_text:
            br = fm.boundingRect(QRect(0, 0, int(bw), 10000), Qt.TextWordWrap, self._bonus_text)
            total_h = int(br.height())

        use_sb = (total_h > view_h)

        if use_sb and self._bonus_text:
            text_w = max(10, int(bw) - (sb_w + gap))
            br2 = fm.boundingRect(QRect(0, 0, text_w, 10000), Qt.TextWordWrap, self._bonus_text)
            total_h = int(br2.height())

        self._bonus_total_h = int(total_h)
        max_scroll = max(0, self._bonus_total_h - view_h)

        if use_sb and max_scroll > 0:
            sb_x = int(bx + bw - sb_w)
            sb_y = int(by)
            sb_h = int(bh)

            self._mini.setFixedWidth(sb_w)
            self._mini.setGeometry(sb_x, sb_y, sb_w, sb_h)
            self._mini.set_range(self._bonus_total_h, view_h)
            self._mini.set_value(0)
            self._mini.show()
            self._mini.raise_()
        else:
            self._mini.hide()

        self.update()

    def _on_mini_scroll(self, v: int) -> None:
        self._bonus_scroll = int(v)
        self.update()

    def _set_hover(self, on: bool) -> None:
        on = bool(on)
        if self._hover == on:
            return
        self._hover = on
        self.update()
        if on:
            self.hovered.emit(self)
        else:
            self.unhovered.emit(self)

    def enterEvent(self, _ev) -> None:
        self._set_hover(True)
        super().enterEvent(_ev)

    def leaveEvent(self, _ev) -> None:
        self._set_hover(False)
        super().leaveEvent(_ev)

    def wheelEvent(self, ev) -> None:
        # ✅ крутим ТОЛЬКО бонусы, если курсор над bonuses_rect и есть overflow
        bx, by, bw, bh = self.cfg.bonuses_rect
        br = QRect(int(bx), int(by), int(bw), int(bh))
        if br.contains(ev.position().toPoint()) and self._mini.isVisible() and self._mini.maximum() > 0:
            step = int(self.cfg.bonus_wheel_step_px)
            dy = ev.angleDelta().y()
            if dy > 0:
                self._mini.set_value(self._mini.value() - step)
            elif dy < 0:
                self._mini.set_value(self._mini.value() + step)
            ev.accept()
            return
        super().wheelEvent(ev)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._armed_click = bool(isinstance(self.item, dict) and self.item)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            armed = bool(getattr(self, "_armed_click", False))
            self._armed_click = False

            inside = False
            try:
                inside = self.rect().contains(ev.position().toPoint())
            except Exception:
                try:
                    inside = self.rect().contains(ev.pos())
                except Exception:
                    inside = False

            if armed and inside and isinstance(self.item, dict) and self.item:
                self.clicked.emit(self)

            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        r = self.rect()

        # фон блока
        if self._bg_pm and not self._bg_pm.isNull():
            p.drawPixmap(r, self._bg_pm)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 20, 24, 235))
            p.drawRoundedRect(r.adjusted(0, 0, -1, -1), 8, 8)

        # свечение
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(240, 220, 140, 35))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 6, 6)

            pen = QPen(QColor(240, 220, 140, 200))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 6, 6)

        it = self.item or {}

        # иконка
        ix, iy, iw, ih = self.cfg.icon_rect
        icon_r = QRect(int(ix), int(iy), int(iw), int(ih))
        if self._icon_pm and not self._icon_pm.isNull():
            scaled = self._icon_pm.scaled(icon_r.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            dst = QRect(0, 0, scaled.width(), scaled.height())
            dst.moveCenter(icon_r.center())
            p.drawPixmap(dst, scaled)

        # имя
        nx, ny, nw, nh = self.cfg.name_rect
        name_r = QRect(int(nx), int(ny), int(nw), int(nh))
        f = QFont()
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(235, 235, 235, 235))
        p.drawText(name_r, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter, str(it.get("Name") or ""))

        # атака/защита
        bx, by, bw, bh = self.cfg.base_stat_rect
        base_r = QRect(int(bx), int(by), int(bw), int(bh))
        f2 = QFont()
        f2.setBold(False)
        p.setFont(f2)
        p.setPen(QColor(216, 216, 216, 235))

        atk = it.get("Attack") or 0
        deff = it.get("Defense") or 0
        try:
            atk_i = int(atk or 0)
        except Exception:
            atk_i = 0
        try:
            def_i = int(deff or 0)
        except Exception:
            def_i = 0

        base_txt = f"Атака: {atk_i}" if atk_i > 0 else f"Защита: {def_i}"
        p.drawText(base_r, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter, base_txt)

        # уровень
        lx, ly, lw, lh = self.cfg.req_level_rect
        lvl_r = QRect(int(lx), int(ly), int(lw), int(lh))
        p.setPen(QColor(230, 210, 122, 235))
        try:
            lvl_i = int(it.get("Level") or 0)
        except Exception:
            lvl_i = 0
        p.drawText(lvl_r, Qt.AlignCenter, str(lvl_i))

        # бонусы (центрируем, если помещается; иначе — scroll как раньше)
        px, py, pw, ph = self.cfg.bonuses_rect
        sb_w = int(self.cfg.bonus_scrollbar_w)
        gap = int(self.cfg.bonus_scrollbar_gap)

        text_w = int(pw)
        scroll_mode = bool(self._mini.isVisible() and self._mini.maximum() > 0)
        if scroll_mode:
            text_w = max(10, text_w - (sb_w + gap))

        bon_r = QRect(int(px), int(py), int(text_w), int(ph))
        p.setFont(self._font_bonus)
        p.setPen(QColor(207, 230, 165, 235))

        if not self._bonus_text:
            p.drawText(bon_r, Qt.AlignLeft | Qt.AlignVCenter, "—")
            p.end()
            return

        if scroll_mode:
            # overflow → рисуем сверху и скроллим translate'ом
            p.save()
            p.setClipRect(bon_r)
            p.translate(0, -int(self._bonus_scroll))
            big = QRect(
                bon_r.x(),
                bon_r.y(),
                bon_r.width(),
                max(10000, bon_r.height() + int(self._bonus_total_h) + 100),
            )
            p.drawText(big, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, self._bonus_text)
            p.restore()
        else:
            # помещается → вертикально центрируем вручную по высоте текста
            fm = QFontMetrics(self._font_bonus)
            br = fm.boundingRect(QRect(0, 0, bon_r.width(), 10000), Qt.TextWordWrap, self._bonus_text)
            text_h = max(1, int(br.height()))
            y0 = bon_r.y() + max(0, (bon_r.height() - text_h) // 2)
            centered = QRect(bon_r.x(), y0, bon_r.width(), text_h)
            p.drawText(centered, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, self._bonus_text)

        p.end()


class ChooseItemMenu(QWidget):
    """Меню выбора предметов для main_window: фон item_choose.png + список блоков item_block.png."""

    def __init__(self, parent: QWidget, *, config: Optional[ItemChooseConfig] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoMouseReplay, True)

        self.cfg = config or ItemChooseConfig()

        bg_path = _resolve_resource(self.cfg.bg_path)
        self._bg_pm = QPixmap(bg_path)
        if self._bg_pm.isNull():
            w, h = self.cfg.fallback_size
            self._bg_pm = QPixmap(int(w), int(h))
            self._bg_pm.fill(QColor(0, 0, 0, 0))

        self.setFixedSize(self._bg_pm.size())

        self._bg = QLabel(self)
        self._bg.setPixmap(self._bg_pm)
        self._bg.setScaledContents(True)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        self._bg.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        block_path = _resolve_resource(self.cfg.block_bg_path)
        self._block_pm = QPixmap(block_path)
        if self._block_pm.isNull():
            self._block_pm = None

        self._on_pick: Optional[Callable[[Dict[str, Any]], None]] = None
        self._on_hover_enter: Optional[Callable[[QWidget, Dict[str, Any], List[str]], None]] = None
        self._on_hover_leave: Optional[Callable[[QWidget], None]] = None

        self._blocks: List[_ItemBlock] = []
        self._index_text: Dict[_ItemBlock, str] = {}
        self._last_hover: Optional[_ItemBlock] = None

        sx, sy, sw, sh = self.cfg.search_rect
        self.search_edit = QLineEdit(self)
        self.search_edit.setGeometry(int(sx), int(sy), int(sw), int(sh))
        self.search_edit.setPlaceholderText("Поиск предмета (название / бонусы / уровень / атк/защ)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setStyleSheet(
            "QLineEdit{background: rgba(0,0,0,0); border: 0px; color:#eaeaea; padding-left:6px;}"
            "QLineEdit:focus{outline:none;}"
        )
        self.search_edit.textChanged.connect(self._apply_filter)

        cx, cy, cw, ch = self.cfg.content_rect
        self._area = QScrollArea(self)
        self._area.setGeometry(int(cx), int(cy), int(cw), int(ch))
        self._area.setFrameShape(QFrame.NoFrame)
        self._area.setWidgetResizable(True)
        self._area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._cont = QWidget()
        self._area.setWidget(self._cont)

        self._vbox = QVBoxLayout(self._cont)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(int(self.cfg.block_gap_y))

        self._sv_custom = None
        if ImageVScrollBar is not None and callable(_find_scroll_dir):
            try:
                self._sv_custom = ImageVScrollBar(
                    self._area.verticalScrollBar(),
                    _find_scroll_dir(),
                    parent=self,
                )
                self._sv_custom.hide()
            except Exception:
                self._sv_custom = None

        vb = self._area.verticalScrollBar()
        vb.setSingleStep(24)
        vb.setPageStep(120)
        vb.rangeChanged.connect(lambda _a, _b: self._sync_scrollbar_visible())

        self.installEventFilter(self)
        QTimer.singleShot(0, self._place_vscroll)

    def set_entries(
        self,
        *,
        entries: List[Dict[str, Any]],
        on_pick: Callable[[Dict[str, Any]], None],
        on_hover_enter: Optional[Callable[[QWidget, Dict[str, Any], List[str]], None]] = None,
        on_hover_leave: Optional[Callable[[QWidget], None]] = None,
        focus_search: bool = True,
    ) -> None:
        self._on_pick = on_pick
        self._on_hover_enter = on_hover_enter
        self._on_hover_leave = on_hover_leave
        self._build_blocks(entries or [])
        self._apply_filter(self.search_edit.text())
        QTimer.singleShot(0, self._place_vscroll)
        if focus_search:
            QTimer.singleShot(0, self._focus_search)

    def _norm(self, s: str) -> str:
        return (s or "").casefold().replace("ё", "е").strip()

    def _make_index_text(self, item: Dict[str, Any], bonus_lines: List[str]) -> str:
        name = str(item.get("Name") or "")
        try:
            lvl = int(item.get("Level") or 0)
        except Exception:
            lvl = 0
        try:
            atk = int(item.get("Attack") or 0)
        except Exception:
            atk = 0
        try:
            deff = int(item.get("Defense") or 0)
        except Exception:
            deff = 0
        body = "  ".join([str(x) for x in (bonus_lines or [])])
        base = f"{name} ур {lvl} уровень {lvl} атк {atk} атака {atk} защ {deff} защита {deff} {body}"
        return self._norm(base)

    def _clear_blocks(self) -> None:
        self._blocks = []
        self._index_text = {}
        self._last_hover = None
        while self._vbox.count():
            it = self._vbox.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _build_blocks(self, entries: List[Dict[str, Any]]) -> None:
        self._clear_blocks()
        bsz = self.cfg.block_size

        for e in entries or []:
            item = dict(e.get("item") or {})
            if not item:
                continue
            lines = list(e.get("bonuses") or [])
            icon_pm = e.get("icon_pm")
            if not isinstance(icon_pm, QPixmap) or icon_pm.isNull():
                icon_pm = None

            blk = _ItemBlock(self._cont, cfg=self.cfg, bg_pm=self._block_pm, size=bsz)
            blk.set_payload(item, lines, icon_pm)
            blk.clicked.connect(self._on_block_clicked)
            blk.hovered.connect(self._on_block_hover)
            blk.unhovered.connect(self._on_block_unhover)

            self._vbox.addWidget(blk)
            self._blocks.append(blk)
            self._index_text[blk] = self._make_index_text(item, lines)

        self._vbox.addStretch(1)
        QTimer.singleShot(0, self._sync_scrollbar_visible)

    def _on_block_clicked(self, blk: _ItemBlock) -> None:
        if not isinstance(getattr(blk, "item", None), dict) or not blk.item:
            return
        cb = self._on_pick
        if callable(cb):
            try:
                cb(dict(blk.item))
            except Exception:
                pass

    def _on_block_hover(self, blk: _ItemBlock) -> None:
        self._last_hover = blk
        cb = self._on_hover_enter
        if callable(cb) and isinstance(getattr(blk, "item", None), dict) and blk.item:
            try:
                cb(blk, dict(blk.item), list(getattr(blk, "bonus_lines", []) or []))
            except Exception:
                pass

    def _on_block_unhover(self, blk: _ItemBlock) -> None:
        if self._last_hover is blk:
            self._last_hover = None
        cb = self._on_hover_leave
        if callable(cb):
            try:
                cb(blk)
            except Exception:
                pass

    def _apply_filter(self, txt: str) -> None:
        qn = self._norm(str(txt or ""))
        if not qn:
            for b in self._blocks:
                b.setVisible(True)
            return

        toks = [t for t in qn.split() if t]
        for b in self._blocks:
            blob = self._index_text.get(b, "")
            ok = all(t in blob for t in toks)
            b.setVisible(ok)

    def _focus_search(self) -> None:
        try:
            self.search_edit.setFocus(Qt.ActiveWindowFocusReason)
            self.search_edit.selectAll()
        except Exception:
            pass

    def _sync_scrollbar_visible(self) -> None:
        if self._sv_custom is None:
            return
        try:
            vb = self._area.verticalScrollBar()
            self._sv_custom.setVisible(vb.maximum() > 0)
        except Exception:
            pass

    def _place_vscroll(self) -> None:
        if self._sv_custom is None:
            return
        try:
            if self.cfg.vscroll_rect:
                x, y, w, h = self.cfg.vscroll_rect
                self._sv_custom.setGeometry(int(x), int(y), int(w), int(h))
                self._sync_scrollbar_visible()
                return

            cx, cy, cw, ch = self.cfg.content_rect
            margin = int(self.cfg.vscroll_margin)
            ar = QRect(int(cx), int(cy), int(cw), int(ch))
            x = ar.right() - self._sv_custom.width() - margin
            y = ar.top() + margin
            h = max(1, ar.height() - margin * 2)
            self._sv_custom.setGeometry(int(x), int(y), int(self._sv_custom.width()), int(h))
            self._sync_scrollbar_visible()
        except Exception:
            pass

    def eventFilter(self, obj, ev) -> bool:
        if obj is self and ev.type() == QEvent.Resize:
            QTimer.singleShot(0, self._place_vscroll)
            return False
        return super().eventFilter(obj, ev)

    def hideEvent(self, ev) -> None:
        blk = self._last_hover
        self._last_hover = None
        cb = self._on_hover_leave
        if blk is not None and callable(cb):
            try:
                cb(blk)
            except Exception:
                pass

        try:
            self.search_edit.clearFocus()
        except Exception:
            pass

        super().hideEvent(ev)

# =============================================================================
#  CARD CHOOSE MENU (scroll + search + blocks + inner text mini-scroll)
# =============================================================================

@dataclass
class CardChooseConfig:
    bg_path: str = "resources/choose_menu/card_choose.png"
    fallback_size: Tuple[int, int] = (528, 272)

    # поиск (можешь двигать/менять ширину)
    search_rect: Tuple[int, int, int, int] = (18, 55, 500, 28)

    # область списка (scroll)
    content_rect: Tuple[int, int, int, int] = (17, 114, 499, 241)

    # блок карты
    block_bg_path: str = "resources/choose_menu/card_block.png"
    block_size: Tuple[int, int] = (499, 89)
    block_gap_y: int = 1

    # кастомный скроллер списка (как в других меню)
    vscroll_rect: Optional[Tuple[int, int, int, int]] = (519, 115, 18, 239)
    vscroll_margin: int = 6

    # ---- разметка внутри блока (координаты относительно card_block.png) ----
    icon_rect: Tuple[int, int, int, int] = (9, 20, 50, 50)
    name_rect: Tuple[int, int, int, int] = (64, 15, 150, 50)

    # область текста бонусов; ВАЖНО: высота 77px как ты просил
    bonus_rect: Tuple[int, int, int, int] = (240, 4, 255, 77)

    # мини-скролл для текста бонусов (внутри блока)
    bonus_scrollbar_w: int = 10
    bonus_scrollbar_gap: int = 4
    bonus_wheel_step_px: int = 24


class _CardBlock(QWidget):
    hovered = Signal(object)
    unhovered = Signal(object)
    clicked = Signal(object)

    def __init__(self, parent: QWidget, *, cfg: CardChooseConfig, bg_pm: Optional[QPixmap]):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_NoMouseReplay, True)

        self.cfg = cfg
        self._bg_pm = bg_pm if (bg_pm and not bg_pm.isNull()) else None
        self.setFixedSize(int(cfg.block_size[0]), int(cfg.block_size[1]))

        self._hover = False
        self.card: Dict[str, Any] | None = None
        self._icon_pm: Optional[QPixmap] = None
        self._name: str = ""
        self._bonus_text: str = ""

        self._font_name = QFont("Segoe UI", 10, QFont.Bold)
        self._font_bonus = QFont("Segoe UI", 9)

        self._bonus_scroll = 0
        self._bonus_total_h = 0

        self._mini = _MiniVScroll(self)
        self._mini.valueChanged.connect(self._on_mini_scroll)

    def set_payload(self, card: Dict[str, Any], icon_pm: Optional[QPixmap], bonus_text: str) -> None:
        self.card = dict(card) if isinstance(card, dict) else None
        self._icon_pm = icon_pm if (icon_pm and not icon_pm.isNull()) else None
        self._name = str((card or {}).get("Name") or "").strip()
        self._bonus_text = (bonus_text or "").replace("\r", "").strip()

        # посчитаем высоту текста бонусов (word-wrap)
        bx, by, bw, bh = self.cfg.bonus_rect
        view_h = int(bh)

        # если скролл нужен — уменьшаем ширину под мини-скролл
        usable_w = int(bw)
        usable_w_for_measure = max(10, usable_w - (self.cfg.bonus_scrollbar_w + self.cfg.bonus_scrollbar_gap))
        fm = QFontMetrics(self._font_bonus)

        if self._bonus_text:
            br = fm.boundingRect(QRect(0, 0, usable_w_for_measure, 10000), Qt.TextWordWrap, self._bonus_text)
            self._bonus_total_h = int(br.height())
        else:
            self._bonus_total_h = 0

        max_scroll = max(0, self._bonus_total_h - view_h)
        if self._bonus_scroll > max_scroll:
            self._bonus_scroll = max_scroll

        # мини-скроллбар рядом с текстом
        sb_w = int(self.cfg.bonus_scrollbar_w)
        gap = int(self.cfg.bonus_scrollbar_gap)

        sb_x = int(bx + bw - sb_w)
        sb_y = int(by)
        sb_h = int(bh)

        self._mini.setFixedWidth(sb_w)
        self._mini.setGeometry(sb_x, sb_y, sb_w, sb_h)
        self._mini.set_range(self._bonus_total_h, view_h)
        self._mini.set_value(self._bonus_scroll)
        self._mini.raise_()

        self.update()

    def _on_mini_scroll(self, v: int) -> None:
        self._bonus_scroll = int(v)
        self.update()

    def _set_hover(self, on: bool) -> None:
        on = bool(on)
        if self._hover == on:
            return
        self._hover = on
        self.update()
        if on:
            self.hovered.emit(self)
        else:
            self.unhovered.emit(self)

    def enterEvent(self, _ev) -> None:
        self._set_hover(True)
        super().enterEvent(_ev)

    def leaveEvent(self, _ev) -> None:
        self._set_hover(False)
        super().leaveEvent(_ev)

    def wheelEvent(self, ev) -> None:
        # крутим ТОЛЬКО текст бонусов, если курсор над bonus_rect и есть overflow
        bx, by, bw, bh = self.cfg.bonus_rect
        br = QRect(int(bx), int(by), int(bw), int(bh))
        if br.contains(ev.position().toPoint()) and self._mini.isVisible() and self._mini.maximum() > 0:
            step = int(self.cfg.bonus_wheel_step_px)
            dy = ev.angleDelta().y()
            if dy > 0:
                self._mini.set_value(self._mini.value() - step)
            elif dy < 0:
                self._mini.set_value(self._mini.value() + step)
            ev.accept()
            return
        super().wheelEvent(ev)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._armed_click = bool(isinstance(self.card, dict) and self.card)
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            armed = bool(getattr(self, "_armed_click", False))
            self._armed_click = False

            inside = False
            try:
                inside = self.rect().contains(ev.position().toPoint())
            except Exception:
                try:
                    inside = self.rect().contains(ev.pos())
                except Exception:
                    inside = False

            if armed and inside and isinstance(self.card, dict) and self.card:
                self.clicked.emit(self)

            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        r = self.rect()

        # фон блока
        if self._bg_pm and not self._bg_pm.isNull():
            p.drawPixmap(r, self._bg_pm)

        # свечение при наведении
        if self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(240, 220, 140, 35))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 6, 6)

            pen = QPen(QColor(240, 220, 140, 200))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 6, 6)

        # иконка
        ix, iy, iw, ih = self.cfg.icon_rect
        icon_r = QRect(int(ix), int(iy), int(iw), int(ih))
        if self._icon_pm and not self._icon_pm.isNull():
            scaled = self._icon_pm.scaled(icon_r.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            dst = QRect(0, 0, scaled.width(), scaled.height())
            dst.moveCenter(icon_r.center())
            p.drawPixmap(dst, scaled)

        # имя
        nx, ny, nw, nh = self.cfg.name_rect
        name_r = QRect(int(nx), int(ny), int(nw), int(nh))
        p.setFont(self._font_name)
        p.setPen(QColor(235, 235, 235, 235))
        p.drawText(name_r, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter, self._name)

        # бонусы (скроллим внутри 77px)
        bx, by, bw, bh = self.cfg.bonus_rect
        sb_w = int(self.cfg.bonus_scrollbar_w)
        gap = int(self.cfg.bonus_scrollbar_gap)

        text_w = int(bw)
        if self._mini.isVisible():
            text_w = max(10, text_w - (sb_w + gap))

        bonus_r = QRect(int(bx), int(by), int(text_w), int(bh))
        p.setFont(self._font_bonus)
        p.setPen(QColor(207, 230, 165, 235))

        if self._bonus_text:
            p.save()
            p.setClipRect(bonus_r)

            # Если текст помещается в область бонусов целиком —
            # рисуем его по центру по вертикали.
            if int(self._bonus_total_h or 0) <= bonus_r.height():
                draw_y = bonus_r.y() + max(0, (bonus_r.height() - int(self._bonus_total_h or 0)) // 2)
                draw_rect = QRect(bonus_r.x(), draw_y, bonus_r.width(),
                                  max(1, int(self._bonus_total_h or bonus_r.height())))
                p.drawText(draw_rect, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, self._bonus_text)
            else:
                # Если текст длинный и есть внутренний скролл —
                # оставляем старую логику со скроллом.
                p.translate(0, -int(self._bonus_scroll))
                big = QRect(
                    bonus_r.x(),
                    bonus_r.y(),
                    bonus_r.width(),
                    max(10000, bonus_r.height() + int(self._bonus_total_h or 0) + 100),
                )
                p.drawText(big, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, self._bonus_text)

            p.restore()
        else:
            p.drawText(bonus_r, Qt.AlignLeft | Qt.AlignVCenter, "—")

        p.end()


class ChooseCardMenu(QWidget):
    def __init__(self, parent: QWidget, *, config: Optional[CardChooseConfig] = None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoMouseReplay, True)

        self.cfg = config or CardChooseConfig()

        # фон меню
        bg_path = _resolve_resource(self.cfg.bg_path)
        self._bg_pm = QPixmap(bg_path)
        if self._bg_pm.isNull():
            w, h = self.cfg.fallback_size
            self._bg_pm = QPixmap(int(w), int(h))
            self._bg_pm.fill(QColor(0, 0, 0, 0))

        self.setFixedSize(self._bg_pm.size())

        self._bg = QLabel(self)
        self._bg.setPixmap(self._bg_pm)
        self._bg.setScaledContents(True)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        self._bg.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # фон блока
        block_path = _resolve_resource(self.cfg.block_bg_path)
        self._block_pm = QPixmap(block_path)
        if self._block_pm.isNull():
            self._block_pm = None

        self._on_pick: Optional[Callable[[Dict[str, Any]], None]] = None

        # search
        sx, sy, sw, sh = self.cfg.search_rect
        self.search_edit = QLineEdit(self)
        self.search_edit.setGeometry(int(sx), int(sy), int(sw), int(sh))
        self.search_edit.setPlaceholderText("Поиск карты (название / бонусы)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setStyleSheet(
            "QLineEdit{background: rgba(0,0,0,0); border: 0px; color:#eaeaea; padding-left:6px;}"
            "QLineEdit:focus{outline:none;}"
        )
        self.search_edit.textChanged.connect(self._apply_filter)

        # content list
        cx, cy, cw, ch = self.cfg.content_rect
        self._area = QScrollArea(self)
        self._area.setGeometry(int(cx), int(cy), int(cw), int(ch))
        self._area.setFrameShape(QFrame.NoFrame)
        self._area.setWidgetResizable(True)
        self._area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._cont = QWidget()
        self._area.setWidget(self._cont)

        self._vbox = QVBoxLayout(self._cont)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(int(self.cfg.block_gap_y))

        self._blocks: List[_CardBlock] = []
        self._index_text: Dict[_CardBlock, str] = {}

        # custom scrollbar for list
        self._sv_custom = None
        if ImageVScrollBar is not None and callable(_find_scroll_dir):
            try:
                self._sv_custom = ImageVScrollBar(self._area.verticalScrollBar(), _find_scroll_dir(), parent=self)
                self._sv_custom.hide()
            except Exception:
                self._sv_custom = None

        vb = self._area.verticalScrollBar()
        vb.setSingleStep(24)
        vb.setPageStep(120)
        vb.rangeChanged.connect(lambda _a, _b: self._sync_scrollbar_visible())

        self.installEventFilter(self)
        QTimer.singleShot(0, self._place_vscroll)
        self.hide()

    def open_for(
        self,
        *,
        anchor_global: QPoint,
        entries: List[Dict[str, Any]],
        on_pick: Callable[[Dict[str, Any]], None],
        initial_search: str = "",
        focus_search: bool = True,
    ) -> None:
        self._on_pick = on_pick

        try:
            self.search_edit.blockSignals(True)
            self.search_edit.setText(str(initial_search or ""))
        finally:
            self.search_edit.blockSignals(False)

        self.set_entries(entries)

        # позиция (как popup)
        x, y = int(anchor_global.x()), int(anchor_global.y())

        scr = (
            self.parent().window().screen().availableGeometry()
            if self.parent() and self.parent().window()
            else QApplication.primaryScreen().availableGeometry()
        )

        if x + self.width() > scr.right() - 6:
            x = max(scr.left() + 6, scr.right() - self.width() - 6)
        if y + self.height() > scr.bottom() - 6:
            y = max(scr.top() + 6, scr.bottom() - self.height() - 6)

        self.move(int(x), int(y))
        self.show()
        self.raise_()
        self.activateWindow()

        QTimer.singleShot(0, self._place_vscroll)
        if focus_search:
            QTimer.singleShot(0, self._focus_search)

    def set_entries(self, entries: List[Dict[str, Any]]) -> None:
        self._clear_blocks()

        for e in (entries or []):
            card = dict(e.get("card") or {})
            if not card:
                continue
            icon_pm = e.get("icon_pm")
            if not isinstance(icon_pm, QPixmap) or icon_pm.isNull():
                icon_pm = None
            bonus_text = str(e.get("bonus_text") or "").replace("\r", "").strip()

            blk = _CardBlock(self._cont, cfg=self.cfg, bg_pm=self._block_pm)
            blk.set_payload(card, icon_pm, bonus_text)
            blk.clicked.connect(self._on_block_clicked)

            self._vbox.addWidget(blk)
            self._blocks.append(blk)

            name = str(card.get("Name") or "")
            blob = f"{name} {bonus_text}".casefold().replace("ё", "е")
            self._index_text[blk] = blob

        self._vbox.addStretch(1)
        QTimer.singleShot(0, self._sync_scrollbar_visible)
        self._apply_filter(self.search_edit.text())

    def _clear_blocks(self) -> None:
        self._blocks = []
        self._index_text = {}
        while self._vbox.count():
            it = self._vbox.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _on_block_clicked(self, blk: _CardBlock) -> None:
        if not isinstance(getattr(blk, "card", None), dict) or not blk.card:
            return
        cb = self._on_pick
        if callable(cb):
            try:
                cb(dict(blk.card))
            except Exception:
                pass
        self.hide()

    def _apply_filter(self, txt: str) -> None:
        q = (txt or "").casefold().replace("ё", "е").strip()
        if not q:
            for b in self._blocks:
                b.setVisible(True)
            return
        toks = [t for t in q.split() if t]
        for b in self._blocks:
            blob = self._index_text.get(b, "")
            b.setVisible(all(t in blob for t in toks))

    def _focus_search(self) -> None:
        try:
            self.search_edit.setFocus(Qt.ActiveWindowFocusReason)
            self.search_edit.selectAll()
        except Exception:
            pass

    def _sync_scrollbar_visible(self) -> None:
        if self._sv_custom is None:
            return
        try:
            vb = self._area.verticalScrollBar()
            self._sv_custom.setVisible(vb.maximum() > 0)
        except Exception:
            pass

    def _place_vscroll(self) -> None:
        if self._sv_custom is None:
            return
        try:
            if self.cfg.vscroll_rect:
                x, y, w, h = self.cfg.vscroll_rect
                self._sv_custom.setGeometry(int(x), int(y), int(w), int(h))
                self._sync_scrollbar_visible()
                return

            cx, cy, cw, ch = self.cfg.content_rect
            margin = int(self.cfg.vscroll_margin)
            ar = QRect(int(cx), int(cy), int(cw), int(ch))
            x = ar.right() - self._sv_custom.width() - margin
            y = ar.top() + margin
            h = max(1, ar.height() - margin * 2)
            self._sv_custom.setGeometry(int(x), int(y), int(self._sv_custom.width()), int(h))
            self._sync_scrollbar_visible()
        except Exception:
            pass

    def eventFilter(self, obj, ev) -> bool:
        if obj is self and ev.type() == QEvent.Resize:
            QTimer.singleShot(0, self._place_vscroll)
            return False
        return super().eventFilter(obj, ev)

    def hideEvent(self, ev) -> None:
        try:
            self.search_edit.clearFocus()
        except Exception:
            pass
        super().hideEvent(ev)