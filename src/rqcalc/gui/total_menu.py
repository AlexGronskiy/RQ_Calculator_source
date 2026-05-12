from __future__ import annotations

from pathlib import Path
from typing import Optional

import os
import sys
import subprocess
import webbrowser

from PySide6.QtCore import Qt, QRect, QSize, QEvent, Signal, QPoint, QTimer
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QLabel, QFrame


MENU_BG_PATH = "resources/total_menu/menu.png"

CLOSE_BTN_ACTIVE_PATH = "resources/helper_buttons/close_button_active.png"

ABOUT_PROJECT_ACTIVE_PATH = "resources/total_menu/about_project.png"
REPORT_BUG_ACTIVE_PATH = "resources/total_menu/report_bug.png"
CHECKING_UPDATES_ACTIVE_PATH = "resources/total_menu/checking_updates.png"
SAVE_CHARACTER_ACTIVE_PATH = "resources/total_menu/save_character.png"
LOAD_CHARACTER_ACTIVE_PATH = "resources/total_menu/load_character.png"
ROOT_FOLDER_ACTIVE_PATH = "resources/total_menu/root_folder.png"
SUPPORT_PROJECT_ACTIVE_PATH = "resources/total_menu/support_project.png"

PROJECT_DEVBLOG_WEB_URL = "https://t.me/rq_calc_devblog/1"
PROJECT_DEVBLOG_TG_URL = "tg://resolve?domain=rq_calc_devblog&post=1"

PROJECT_ABOUT_URL = "https://t.me/rq_calc_devblog/15/655"
PROJECT_ABOUT_TG_URL = "tg://resolve?domain=rq_calc_devblog&post=15&comment=655"

PROJECT_SITE_URL = "https://alexgronskiy.github.io/rq-calculator-site/"

TELEGRAM_WARNING_TEXT = "Внимание! Эта кнопка перекинет Вас на Телеграмм канал разработчика!"
CHECKING_UPDATES_TOOLTIP_TEXT = "Проверяет наличие новой версии калькулятора."
SAVE_CHARACTER_TOOLTIP_TEXT = "Примечание! Можно вызывать через главное меню сочетанием Ctrl + S."
LOAD_CHARACTER_TOOLTIP_TEXT = "Примечание! Можно вызывать через главное меню сочетанием Ctrl + D."
ROOT_FOLDER_TOOLTIP_TEXT = "Открыть проводник с файлами программы."
SUPPORT_PROJECT_TOOLTIP_TEXT = "Внимание! При нажатии откроется сайт с информацией."
TOTAL_MENU_TOOLTIP_MAX_W = 180

MENU_W = 234
MENU_H = 326

CLOSE_BTN_RECT = (197, 3, 24, 24)

MENU_ITEM_X = 18
MENU_ITEM_Y = 40
MENU_ITEM_W = 199
MENU_ITEM_H = 35
MENU_ITEM_GAP_Y = 3

MENU_ITEM_ACTIVE_W = 205
MENU_ITEM_ACTIVE_H = 41


def _resolve_resource(rel_path: str) -> str:
    p = Path(rel_path)
    for base in (Path.cwd(), Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[3]):
        candidate = base / p
        if candidate.exists():
            return str(candidate)
    return str(p)


def _project_root_dir() -> Path:
    candidates = []

    try:
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass

    try:
        candidates.append(Path.cwd())
    except Exception:
        pass

    try:
        here = Path(__file__).resolve()
        candidates.append(here.parents[2])
    except Exception:
        pass

    try:
        here = Path(__file__).resolve()
        candidates.append(here.parents[3])
    except Exception:
        pass

    for c in candidates:
        try:
            if (c / "resources").exists():
                return c
        except Exception:
            pass

    return Path.cwd()


class _InputShield(QWidget):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("TotalMenuShield")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self.setGeometry(parent.rect())
        self._target_window: Optional[QWidget] = None
        self.hide()

    def set_target_window(self, window: Optional[QWidget]) -> None:
        self._target_window = window

    def sync_geometry(self) -> None:
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(p.rect())

    def _raise_target_window(self) -> None:
        w = self._target_window
        if w is None:
            return

        try:
            if not w.isVisible():
                return
        except Exception:
            return

        try:
            w.raise_()
        except Exception:
            pass

        try:
            w.activateWindow()
        except Exception:
            pass

    def event(self, e: QEvent) -> bool:
        et = e.type()

        if et in (
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseButtonDblClick,
            QEvent.MouseMove,
            QEvent.Wheel,
            QEvent.ContextMenu,
            QEvent.KeyPress,
            QEvent.KeyRelease,
            QEvent.FocusIn,
            QEvent.WindowActivate,
        ):
            self._raise_target_window()

        try:
            e.accept()
        except Exception:
            pass

        return True


class _HitboxImageButton(QWidget):
    clicked = Signal()

    def __init__(
        self,
        *,
        hit_x: int,
        hit_y: int,
        hit_w: int,
        hit_h: int,
        visual_w: int,
        visual_h: int,
        active_rel_path: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self._hit_x = int(hit_x)
        self._hit_y = int(hit_y)
        self._hit_w = int(hit_w)
        self._hit_h = int(hit_h)
        self._visual_w = int(visual_w)
        self._visual_h = int(visual_h)

        self._hover = False
        self._pressed = False
        self._hit_rect_local = QRect()

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent;")

        self._active_label = QLabel(self)
        self._active_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._active_label.setStyleSheet("background: transparent;")
        self._active_label.setScaledContents(True)
        self._active_label.hide()

        pm = QPixmap(_resolve_resource(active_rel_path))
        self._active_pm = pm if not pm.isNull() else None

    def apply_scale(self, scale: float) -> None:
        s = max(0.1, float(scale or 1.0))

        vis_w = max(1, int(round(self._visual_w * s)))
        vis_h = max(1, int(round(self._visual_h * s)))
        hit_w = max(1, int(round(self._hit_w * s)))
        hit_h = max(1, int(round(self._hit_h * s)))

        dx = (vis_w - hit_w) // 2
        dy = (vis_h - hit_h) // 2

        x = int(round((self._hit_x * s) - dx))
        y = int(round((self._hit_y * s) - dy))

        self.setGeometry(x, y, vis_w, vis_h)
        self._hit_rect_local = QRect(dx, dy, hit_w, hit_h)

        self._active_label.setGeometry(0, 0, vis_w, vis_h)

        if self._active_pm is not None:
            scaled = self._active_pm.scaled(
                QSize(vis_w, vis_h),
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
            self._active_label.setPixmap(scaled)

        self._sync_visual()

    def _inside_hit(self, pos) -> bool:
        try:
            return self._hit_rect_local.contains(pos)
        except Exception:
            return False

    def _sync_visual(self) -> None:
        active = bool(self._pressed or self._hover)
        self._active_label.setVisible(active)

        try:
            if self._inside_hit(self.mapFromGlobal(self.cursor().pos())):
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.unsetCursor()
        except Exception:
            if active:
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.unsetCursor()

        self.update()

    def enterEvent(self, e) -> None:
        self._hover = False
        self._sync_visual()
        e.accept()

    def leaveEvent(self, e) -> None:
        self._hover = False
        self._pressed = False
        self._sync_visual()
        e.accept()

    def mouseMoveEvent(self, e) -> None:
        self._hover = self._inside_hit(e.position().toPoint() if hasattr(e, "position") else e.pos())
        self._sync_visual()
        e.accept()

    def mousePressEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return super().mousePressEvent(e)

        pos = e.position().toPoint() if hasattr(e, "position") else e.pos()
        self._pressed = self._inside_hit(pos)
        self._hover = self._inside_hit(pos)
        self._sync_visual()
        e.accept()

    def mouseReleaseEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(e)

        pos = e.position().toPoint() if hasattr(e, "position") else e.pos()
        inside = self._inside_hit(pos)
        was_pressed = bool(self._pressed)

        self._pressed = False
        self._hover = bool(inside)
        self._sync_visual()

        if was_pressed and inside:
            self.clicked.emit()

        e.accept()


class _TelegramWarningTooltip(QFrame):
    """
    Инфо-борд в стиле tooltip-а талантов:
    чёрный полупрозрачный фон, металлическая обводка, скругление.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.setWindowFlags(
            Qt.ToolTip |
            Qt.FramelessWindowHint |
            Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setObjectName("telegramWarningTooltip")
        self.setStyleSheet("background: transparent; border: none;")

        self._lab = QLabel(self)
        self._lab.setWordWrap(True)
        self._lab.setTextFormat(Qt.RichText)
        self._lab.setStyleSheet(
            "background: transparent;"
            "color: #f2f2f2;"
            "border: none;"
            "font-weight: 700;"
        )

        self.hide()

    def set_text(self, text: str, max_w: int = 310) -> None:
        raw_text = str(text or "").strip()

        title = ""
        body = raw_text

        for prefix in ("Внимание!", "Примечание!", "В разработке!"):
            if raw_text.startswith(prefix):
                title = prefix
                body = raw_text[len(prefix):].strip()
                break

        if title and body:
            html_text = (
                "<div style='line-height:135%;'>"
                f"<span style='color:#f2c45d; font-weight:700;'>{title}</span>"
                "<br>"
                f"<span style='color:#f2f2f2;'>{body}</span>"
                "</div>"
            )
        elif title:
            html_text = (
                "<div style='line-height:135%;'>"
                f"<span style='color:#f2c45d; font-weight:700;'>{title}</span>"
                "</div>"
            )
        else:
            html_text = (
                "<div style='line-height:135%;'>"
                f"<span style='color:#f2f2f2;'>{body}</span>"
                "</div>"
            )

        self._lab.setText(html_text)

        pad_x = 10
        pad_y = 8

        label_w = max(120, int(max_w) - pad_x * 2)
        self._lab.setFixedWidth(label_w)
        self._lab.adjustSize()

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


class TotalMenuWindow(QWidget):
    closed = Signal()

    aboutProjectClicked = Signal()
    reportBugClicked = Signal()
    checkingUpdatesClicked = Signal()
    saveCharacterClicked = Signal()
    loadCharacterClicked = Signal()
    openRootFolderClicked = Signal()
    supportProjectClicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._owner: Optional[QWidget] = None
        self._shield: Optional[_InputShield] = None
        self._scale_factor: float = 1.0
        self._last_global_pos: Optional[QPoint] = None
        self._drag_pos: Optional[QPoint] = None

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)
        self.hide()

        self._bg_label = QLabel(self)
        self._bg_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._bg_label.setStyleSheet("background: transparent;")
        self._bg_label.setScaledContents(True)

        bg = QPixmap(_resolve_resource(MENU_BG_PATH))
        self._bg_pm = bg if not bg.isNull() else None

        self.btn_close = _HitboxImageButton(
            hit_x=CLOSE_BTN_RECT[0],
            hit_y=CLOSE_BTN_RECT[1],
            hit_w=CLOSE_BTN_RECT[2],
            hit_h=CLOSE_BTN_RECT[3],
            visual_w=CLOSE_BTN_RECT[2],
            visual_h=CLOSE_BTN_RECT[3],
            active_rel_path=CLOSE_BTN_ACTIVE_PATH,
            parent=self,
        )
        self.btn_close.clicked.connect(self.close_menu)

        self.btn_about_project = _HitboxImageButton(
            hit_x=MENU_ITEM_X,
            hit_y=MENU_ITEM_Y + (MENU_ITEM_H + MENU_ITEM_GAP_Y) * 0,
            hit_w=MENU_ITEM_W,
            hit_h=MENU_ITEM_H,
            visual_w=MENU_ITEM_ACTIVE_W,
            visual_h=MENU_ITEM_ACTIVE_H,
            active_rel_path=ABOUT_PROJECT_ACTIVE_PATH,
            parent=self,
        )
        self.btn_report_bug = _HitboxImageButton(
            hit_x=MENU_ITEM_X,
            hit_y=MENU_ITEM_Y + (MENU_ITEM_H + MENU_ITEM_GAP_Y) * 1,
            hit_w=MENU_ITEM_W,
            hit_h=MENU_ITEM_H,
            visual_w=MENU_ITEM_ACTIVE_W,
            visual_h=MENU_ITEM_ACTIVE_H,
            active_rel_path=REPORT_BUG_ACTIVE_PATH,
            parent=self,
        )
        self.btn_checking_updates = _HitboxImageButton(
            hit_x=MENU_ITEM_X,
            hit_y=MENU_ITEM_Y + (MENU_ITEM_H + MENU_ITEM_GAP_Y) * 2,
            hit_w=MENU_ITEM_W,
            hit_h=MENU_ITEM_H,
            visual_w=MENU_ITEM_ACTIVE_W,
            visual_h=MENU_ITEM_ACTIVE_H,
            active_rel_path=CHECKING_UPDATES_ACTIVE_PATH,
            parent=self,
        )
        self.btn_save_character = _HitboxImageButton(
            hit_x=MENU_ITEM_X,
            hit_y=MENU_ITEM_Y + (MENU_ITEM_H + MENU_ITEM_GAP_Y) * 3,
            hit_w=MENU_ITEM_W,
            hit_h=MENU_ITEM_H,
            visual_w=MENU_ITEM_ACTIVE_W,
            visual_h=MENU_ITEM_ACTIVE_H,
            active_rel_path=SAVE_CHARACTER_ACTIVE_PATH,
            parent=self,
        )
        self.btn_load_character = _HitboxImageButton(
            hit_x=MENU_ITEM_X,
            hit_y=MENU_ITEM_Y + (MENU_ITEM_H + MENU_ITEM_GAP_Y) * 4,
            hit_w=MENU_ITEM_W,
            hit_h=MENU_ITEM_H,
            visual_w=MENU_ITEM_ACTIVE_W,
            visual_h=MENU_ITEM_ACTIVE_H,
            active_rel_path=LOAD_CHARACTER_ACTIVE_PATH,
            parent=self,
        )
        self.btn_root_folder = _HitboxImageButton(
            hit_x=MENU_ITEM_X,
            hit_y=MENU_ITEM_Y + (MENU_ITEM_H + MENU_ITEM_GAP_Y) * 5,
            hit_w=MENU_ITEM_W,
            hit_h=MENU_ITEM_H,
            visual_w=MENU_ITEM_ACTIVE_W,
            visual_h=MENU_ITEM_ACTIVE_H,
            active_rel_path=ROOT_FOLDER_ACTIVE_PATH,
            parent=self,
        )
        self.btn_support_project = _HitboxImageButton(
            hit_x=MENU_ITEM_X,
            hit_y=MENU_ITEM_Y + (MENU_ITEM_H + MENU_ITEM_GAP_Y) * 6,
            hit_w=MENU_ITEM_W,
            hit_h=MENU_ITEM_H,
            visual_w=MENU_ITEM_ACTIVE_W,
            visual_h=MENU_ITEM_ACTIVE_H,
            active_rel_path=SUPPORT_PROJECT_ACTIVE_PATH,
            parent=self,
        )

        self.btn_about_project.clicked.connect(self._open_about_project)
        self.btn_report_bug.clicked.connect(self._open_project_channel)
        self.btn_checking_updates.clicked.connect(self.checkingUpdatesClicked)
        self.btn_save_character.clicked.connect(self.saveCharacterClicked)
        self.btn_load_character.clicked.connect(self.loadCharacterClicked)
        self.btn_root_folder.clicked.connect(self.openRootFolderClicked)
        self.btn_root_folder.clicked.connect(self._open_root_folder)
        self.btn_support_project.clicked.connect(self._open_support_project)

        self._init_total_menu_tooltips()

    def _init_total_menu_tooltips(self) -> None:
        """
        Кастомные всплывающие подсказки для кнопок total_menu.
        Стиль такой же, как у инфо-борда талантов.
        """
        self._tooltip_target: Optional[QWidget] = None

        self._tooltip_text_by_button = {
            self.btn_about_project: TELEGRAM_WARNING_TEXT,
            self.btn_report_bug: TELEGRAM_WARNING_TEXT,
            self.btn_checking_updates: CHECKING_UPDATES_TOOLTIP_TEXT,
            self.btn_save_character: SAVE_CHARACTER_TOOLTIP_TEXT,
            self.btn_load_character: LOAD_CHARACTER_TOOLTIP_TEXT,
            self.btn_root_folder: ROOT_FOLDER_TOOLTIP_TEXT,
            self.btn_support_project: SUPPORT_PROJECT_TOOLTIP_TEXT,
        }

        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.setInterval(int(TOTAL_MENU_TOOLTIP_MAX_W))
        self._tooltip_timer.timeout.connect(self._show_total_menu_tooltip)

        self._tooltip_popup = _TelegramWarningTooltip(None)
        self._tooltip_popup.set_text("", max_w=TOTAL_MENU_TOOLTIP_MAX_W)
        self._tooltip_popup.hide()

        for btn in self._tooltip_text_by_button.keys():
            try:
                btn.installEventFilter(self)
            except Exception:
                pass

    def _is_total_menu_tooltip_button(self, obj) -> bool:
        m = getattr(self, "_tooltip_text_by_button", None)
        return isinstance(m, dict) and obj in m

    def _tooltip_text_for_button(self, btn: QWidget) -> str:
        try:
            m = getattr(self, "_tooltip_text_by_button", None)
            if isinstance(m, dict):
                return str(m.get(btn, "") or "")
        except Exception:
            pass

        return ""

    def _is_inside_button_hitbox(self, btn: QWidget, event: Optional[QEvent] = None) -> bool:
        if btn is None:
            return False

        try:
            if event is not None and hasattr(event, "position"):
                pos = event.position().toPoint()
            elif event is not None and hasattr(event, "pos"):
                pos = event.pos()
            else:
                pos = btn.mapFromGlobal(btn.cursor().pos())

            fn = getattr(btn, "_inside_hit", None)
            if callable(fn):
                return bool(fn(pos))

            return bool(btn.rect().contains(pos))
        except Exception:
            return False

    def _schedule_total_menu_tooltip(self, btn: QWidget, event: Optional[QEvent] = None) -> None:
        if not self._is_inside_button_hitbox(btn, event):
            self._hide_total_menu_tooltip()
            return

        if not self._tooltip_text_for_button(btn):
            self._hide_total_menu_tooltip()
            return

        self._tooltip_target = btn

        try:
            if self._tooltip_timer.isActive():
                self._tooltip_timer.stop()
            self._tooltip_timer.start()
        except Exception:
            pass

    def _show_total_menu_tooltip(self) -> None:
        btn = getattr(self, "_tooltip_target", None)
        popup = getattr(self, "_tooltip_popup", None)

        if btn is None or popup is None:
            return

        if not self.isVisible() or not btn.isVisible():
            self._hide_total_menu_tooltip()
            return

        if not self._is_inside_button_hitbox(btn):
            self._hide_total_menu_tooltip()
            return

        text = self._tooltip_text_for_button(btn)
        if not text:
            self._hide_total_menu_tooltip()
            return

        try:
            if hasattr(popup, "set_text"):
                # ВАЖНО:
                # сюда передаём text конкретной кнопки,
                # а не TELEGRAM_WARNING_TEXT.
                popup.set_text(text, max_w=TOTAL_MENU_TOOLTIP_MAX_W)

            gap = 8
            gp = btn.mapToGlobal(QPoint(btn.width() + gap, 0))

            try:
                screen = self.screen()
                available = screen.availableGeometry() if screen is not None else QRect()

                if not available.isEmpty() and gp.x() + popup.width() > available.right():
                    gp = btn.mapToGlobal(QPoint(0, btn.height() + gap))

                if not available.isEmpty() and gp.y() + popup.height() > available.bottom():
                    gp = btn.mapToGlobal(QPoint(0, -popup.height() - gap))
            except Exception:
                pass

            popup.move(gp)
            popup.show()
            popup.raise_()
        except Exception:
            pass

    def _hide_total_menu_tooltip(self) -> None:
        try:
            if getattr(self, "_tooltip_timer", None) is not None:
                self._tooltip_timer.stop()
        except Exception:
            pass

        try:
            popup = getattr(self, "_tooltip_popup", None)
            if popup is not None:
                popup.hide()
        except Exception:
            pass

        self._tooltip_target = None

    def eventFilter(self, obj, event) -> bool:
        if self._is_total_menu_tooltip_button(obj):
            et = event.type()

            if et in (QEvent.Enter, QEvent.MouseMove):
                self._schedule_total_menu_tooltip(obj, event)

            elif et in (
                    QEvent.Leave,
                    QEvent.MouseButtonPress,
                    QEvent.MouseButtonRelease,
                    QEvent.MouseButtonDblClick,
            ):
                self._hide_total_menu_tooltip()

        return super().eventFilter(obj, event)

    def _open_about_project(self) -> None:
        """
        Открывает конкретное сообщение 'О проекте' в Telegram.

        Сначала пробуем открыть Telegram-приложение через tg://.
        Если обработчика tg:// нет — открываем обычную web-ссылку.

        По аналогии с кнопкой 'Сообщить об ошибке':
        total_menu после нажатия НЕ закрываем.
        """
        try:
            self.aboutProjectClicked.emit()
        except Exception:
            pass

        opened = False

        # 1) Пытаемся открыть именно приложение Telegram на нужном сообщении.
        try:
            if sys.platform.startswith("win"):
                os.startfile(PROJECT_ABOUT_TG_URL)
                opened = True
            elif sys.platform == "darwin":
                subprocess.Popen(["open", PROJECT_ABOUT_TG_URL])
                opened = True
            else:
                subprocess.Popen(["xdg-open", PROJECT_ABOUT_TG_URL])
                opened = True
        except Exception:
            opened = False

        # 2) Если Telegram-схема не открылась — fallback в браузер.
        if not opened:
            try:
                opened = bool(webbrowser.open_new_tab(PROJECT_ABOUT_URL))
            except Exception:
                opened = False

        # Меню специально НЕ закрываем.
        try:
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def _open_project_channel(self) -> None:
        """
        Открывает Telegram-канал разработки калькулятора.

        Сначала пробуем открыть Telegram-приложение через tg://.
        Если обработчика tg:// нет — открываем обычную web-ссылку.

        ВАЖНО:
        total_menu после нажатия НЕ закрываем.
        """
        try:
            self.reportBugClicked.emit()
        except Exception:
            pass

        opened = False

        # 1) Пытаемся открыть именно приложение Telegram.
        try:
            if sys.platform.startswith("win"):
                os.startfile(PROJECT_DEVBLOG_TG_URL)
                opened = True
            elif sys.platform == "darwin":
                subprocess.Popen(["open", PROJECT_DEVBLOG_TG_URL])
                opened = True
            else:
                subprocess.Popen(["xdg-open", PROJECT_DEVBLOG_TG_URL])
                opened = True
        except Exception:
            opened = False

        # 2) Если Telegram-схема не открылась — fallback в браузер.
        if not opened:
            try:
                opened = bool(webbrowser.open_new_tab(PROJECT_DEVBLOG_WEB_URL))
            except Exception:
                opened = False

        # Меню специально НЕ закрываем.
        try:
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def _open_support_project(self) -> None:
        """
        Открывает страницу поддержки проекта на сайте RQ Calculator.

        При нажатии сначала отправляем внешний сигнал supportProjectClicked,
        затем открываем сайт в браузере.
        total_menu после нажатия НЕ закрываем.
        """
        try:
            self.supportProjectClicked.emit()
        except Exception:
            pass

        opened = False

        try:
            opened = bool(webbrowser.open_new_tab(PROJECT_SITE_URL))
        except Exception:
            opened = False

        if not opened:
            try:
                if sys.platform.startswith("win"):
                    os.startfile(PROJECT_SITE_URL)
                    opened = True
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", PROJECT_SITE_URL])
                    opened = True
                else:
                    subprocess.Popen(["xdg-open", PROJECT_SITE_URL])
                    opened = True
            except Exception:
                opened = False

        try:
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def _owner_scale(self) -> float:
        owner = self._owner
        if owner is None:
            return 1.0

        fn = getattr(owner, "_scale", None)
        if callable(fn):
            try:
                s = float(fn() or 1.0)
                return max(0.1, s)
            except Exception:
                pass
        return 1.0

    def _owner_anchor_rect(self) -> QRect:
        owner = self._owner
        if owner is None:
            return QRect()

        fn = getattr(owner, "_img_rect", None)
        if callable(fn):
            try:
                r = fn()
                if isinstance(r, QRect) and not r.isEmpty():
                    return QRect(r)
            except Exception:
                pass

        return owner.rect()

    def _ensure_shield(self, owner: QWidget) -> _InputShield:
        if self._shield is None or self._shield.parentWidget() is not owner:
            if self._shield is not None:
                try:
                    self._shield.hide()
                    self._shield.deleteLater()
                except Exception:
                    pass

            self._shield = _InputShield(owner)

        self._shield.sync_geometry()
        self._shield.set_target_window(self)
        return self._shield

    def _apply_scaled_layout(self) -> None:
        s = max(0.1, float(self._scale_factor or 1.0))

        w = max(1, int(round(MENU_W * s)))
        h = max(1, int(round(MENU_H * s)))

        self.setFixedSize(w, h)

        # Если раньше была добавлена чёрная подложка — убираем её.
        try:
            backing = getattr(self, "_backing_label", None)
            if isinstance(backing, QLabel):
                backing.hide()
                backing.deleteLater()
                self._backing_label = None
        except Exception:
            pass

        self._bg_label.setGeometry(0, 0, w, h)

        if self._bg_pm is not None:
            self._bg_label.setPixmap(
                self._bg_pm.scaled(QSize(w, h), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self._bg_label.clear()

        self._bg_label.raise_()

        self.btn_close.apply_scale(s)
        self.btn_about_project.apply_scale(s)
        self.btn_report_bug.apply_scale(s)
        self.btn_checking_updates.apply_scale(s)
        self.btn_save_character.apply_scale(s)
        self.btn_load_character.apply_scale(s)
        self.btn_root_folder.apply_scale(s)
        self.btn_support_project.apply_scale(s)

        self.btn_close.raise_()
        self.btn_about_project.raise_()
        self.btn_report_bug.raise_()
        self.btn_checking_updates.raise_()
        self.btn_save_character.raise_()
        self.btn_load_character.raise_()
        self.btn_root_folder.raise_()
        self.btn_support_project.raise_()

    def open_centered(self, owner: QWidget) -> None:
        if owner is None:
            return

        self._owner = owner
        self._scale_factor = self._owner_scale()

        flags = (
            Qt.Tool |
            Qt.FramelessWindowHint |
            Qt.NoDropShadowWindowHint
        )

        try:
            self.setParent(owner, flags)
        except TypeError:
            try:
                self.setParent(owner)
                self.setWindowFlags(flags)
            except Exception:
                self.setWindowFlags(flags)
        except Exception:
            self.setWindowFlags(flags)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

        shield = self._ensure_shield(owner)
        shield.show()
        shield.raise_()

        self._apply_scaled_layout()

        saved_pos = getattr(self, "_last_global_pos", None)

        if isinstance(saved_pos, QPoint):
            x = int(saved_pos.x())
            y = int(saved_pos.y())
        else:
            anchor = self._owner_anchor_rect()
            if anchor.isEmpty():
                anchor = owner.rect()

            try:
                anchor_top_left = owner.mapToGlobal(anchor.topLeft())
                x = int(anchor_top_left.x() + (anchor.width() - self.width()) / 2)
                y = int(anchor_top_left.y() + (anchor.height() - self.height()) / 2)
            except Exception:
                x = int(owner.x() + (owner.width() - self.width()) / 2)
                y = int(owner.y() + (owner.height() - self.height()) / 2)

        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

        try:
            wh = self.windowHandle()
            ow = owner.windowHandle()
            if wh is not None and ow is not None:
                wh.setTransientParent(ow)
        except Exception:
            pass

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            try:
                gp = e.globalPosition().toPoint()
            except Exception:
                gp = e.globalPos()

            self._drag_pos = gp - self.frameGeometry().topLeft()

            try:
                self.raise_()
                self.activateWindow()
            except Exception:
                pass

            e.accept()
            return

        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        drag_pos = getattr(self, "_drag_pos", None)

        if drag_pos is not None and (e.buttons() & Qt.LeftButton):
            try:
                gp = e.globalPosition().toPoint()
            except Exception:
                gp = e.globalPos()

            new_pos = gp - drag_pos
            self.move(new_pos)

            try:
                self._last_global_pos = QPoint(self.frameGeometry().topLeft())
            except Exception:
                self._last_global_pos = QPoint(new_pos)

            try:
                self.raise_()
            except Exception:
                pass

            e.accept()
            return

        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        try:
            self._last_global_pos = QPoint(self.frameGeometry().topLeft())
        except Exception:
            try:
                self._last_global_pos = QPoint(self.pos())
            except Exception:
                pass

        self._drag_pos = None
        e.accept()

    def close_menu(self) -> None:
        try:
            self._hide_total_menu_tooltip()
        except Exception:
            pass

        try:
            self._last_global_pos = QPoint(self.frameGeometry().topLeft())
        except Exception:
            try:
                self._last_global_pos = QPoint(self.pos())
            except Exception:
                pass

        self.hide()

        if self._shield is not None:
            try:
                self._shield.set_target_window(None)
            except Exception:
                pass

            try:
                self._shield.hide()
            except Exception:
                pass

        self.closed.emit()

    def _open_root_folder(self) -> None:
        root = _project_root_dir()

        try:
            if sys.platform.startswith("win"):
                os.startfile(str(root))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(root)])
            else:
                subprocess.Popen(["xdg-open", str(root)])
        except Exception:
            return

        self.close_menu()