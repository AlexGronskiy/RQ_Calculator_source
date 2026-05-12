from __future__ import annotations
from PySide6.QtCore import Qt, QRect, QTimer, QPoint, QEvent
from PySide6.QtGui import QPixmap, QPainter, QIntValidator, QColor, QPen, QCursor
from PySide6.QtWidgets import QWidget, QSpinBox, QLineEdit, QVBoxLayout, QApplication

# --- параметры спрайта ---
COLS = 5
ROWS = 2
# порядок кадров в PNG слева-направо, сверху-вниз:
# 1 2 3 4 5
# 6 7 8 9 0
ORDER = [1, 2, 3, 4, 5, 6, 7, 8, 9, 0]

# --- геометрия цифр ---
FIXED_DIGITS = 2       # рисуем всегда 2 цифры
SCALE        = 0.3     # масштаб тайла относительно его «нативного» размера
DIGIT_GAP    = 0       # зазор между цифрами (px в целевом виджете)
OFFSET_X     = -42     # сдвиг всего блока относительно центра spin
OFFSET_Y     = 24

# --- зона, которая реально ловит колесо мыши вокруг цифр ---
# Визуально цифры остаются такими же, но область прокрутки становится больше.
HITBOX_PAD_X = 30
HITBOX_PAD_Y = 14

# --- debug подсветка зоны прокрутки ---
SHOW_SCROLL_HITBOX = False
HITBOX_COLOR  = QColor(255, 80, 0, 90)
HITBOX_BORDER = QColor(255, 120, 0, 180)


class _InlineEditorPopup(QWidget):
    """Маленькое поле ввода уровня (Qt.Popup), закрывается по клику вне."""
    def __init__(self, wheel: "LevelWheel"):
        # !!! Важно: flags задаём как второй позиционный аргумент
        super().__init__(wheel, Qt.Popup | Qt.FramelessWindowHint)
        self.wheel = wheel

        # полностью прозрачный контейнер
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

        # поле ввода
        self.edit = QLineEdit(self)
        self.edit.setAlignment(Qt.AlignCenter)
        self.edit.setFixedWidth(72)
        self.edit.setStyleSheet("""
            QLineEdit {
                background: rgba(25,25,25,230);
                color: #eaeaea;
                border: 1px solid #666;
                border-radius: 6px;
                padding: 6px 8px;
                selection-background-color: #444;
            }
        """)

        # нулевые отступы, чтобы размер попапа = размеру поля
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit)

        self.edit.returnPressed.connect(self._commit)
        self.edit.editingFinished.connect(self._commit)

    def open_at(self, global_pos):
        sp = self.wheel.spin
        if not sp:
            return
        vmin, vmax = sp.minimum(), sp.maximum()
        self.edit.setValidator(QIntValidator(vmin, vmax, self))
        self.edit.setText(str(sp.value()))
        self.adjustSize()  # размер попапа ровно под QLineEdit

        x = global_pos.x() - self.width() // 2
        y = global_pos.y() - self.height() // 2
        self.move(x, y)
        self.show()
        self.edit.setFocus(Qt.OtherFocusReason)
        self.edit.selectAll()

    def _commit(self):
        sp = self.wheel.spin
        if not sp:
            self.close()
            return
        text = self.edit.text().strip()
        if text:
            try:
                val = int(text)
                val = max(sp.minimum(), min(sp.maximum(), val))  # автоподстановка max/min
                sp.setValue(val)
            except ValueError:
                pass
        self.close()

    def keyPressEvent(self, ev):
        # учитываем оба варианта Enter: обычный и на Numpad
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._commit()
            ev.accept()
            return
        if ev.key() == Qt.Key_Escape:
            self.close()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def _maybe_commit_on_focus_out(self):
        # Если ушли фокусом не через Esc — попробуем применить
        if self.isVisible():
            self._commit()


class LevelWheel(QWidget):
    """
    Накладной виджет поверх QSpinBox.

    Рисует 2 цифры уровня из спрайта, но имеет увеличенную невидимую
    область вокруг цифр, чтобы колесо мыши стабильно ловилось на разных
    DPI/мониторах/мышках.

    Дополнительно ставит eventFilter на QApplication:
    если Qt отправил Wheel-событие не самому LevelWheel, а нижнему QLabel/окну,
    мы всё равно перехватим событие, если курсор находится в зоне уровня.
    """

    def __init__(self, spin: QSpinBox, sprite_path: str, parent=None):
        super().__init__(parent)

        self.spin = spin
        self.sprite = QPixmap(sprite_path)
        self._editor_popup: _InlineEditorPopup | None = None
        self._app_filter_installed = False

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)

        # Таймер пока не используем, оставляем как было.
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.update)

        if self.spin:
            try:
                self.spin.valueChanged.connect(self._on_spin_changed)
            except Exception:
                pass

            # На случай если Wheel-событие прилетит именно в скрытый spin.
            try:
                self.spin.installEventFilter(self)
            except Exception:
                pass

        # Самый важный фолбэк:
        # на некоторых системах колесо уходит в board_label/родителя,
        # а не в маленький LevelWheel.
        app = QApplication.instance()
        if app is not None:
            try:
                app.installEventFilter(self)
                self._app_filter_installed = True
            except Exception:
                self._app_filter_installed = False

        self.show()

    # ====== утилиты по спрайту ======
    def _digit_tile_size(self) -> tuple[int, int]:
        if not self.sprite.isNull():
            return self.sprite.width() // COLS, self.sprite.height() // ROWS
        return 32, 32

    def _src_rect_for_digit(self, d: int) -> QRect:
        d = d % 10

        try:
            idx = ORDER.index(d)
        except ValueError:
            idx = 0

        col = idx % COLS
        row = idx // COLS
        tw, th = self._digit_tile_size()

        return QRect(col * tw, row * th, tw, th)

    def _digits_size(self) -> tuple[int, int]:
        tw, th = self._digit_tile_size()

        w_digit = max(1, int(tw * SCALE))
        h_digit = max(1, int(th * SCALE))

        total_w = w_digit * FIXED_DIGITS + max(0, FIXED_DIGITS - 1) * DIGIT_GAP

        return total_w, h_digit

    # ====== геометрия виджета ======
    def _current_size(self) -> tuple[int, int]:
        digits_w, digits_h = self._digits_size()

        # ВАЖНО:
        # размеры самого QWidget теперь больше, чем визуальные цифры.
        # Так колесо ловится не только пиксель-в-пиксель по цифрам.
        total_w = digits_w + HITBOX_PAD_X * 2
        total_h = digits_h + HITBOX_PAD_Y * 2

        return total_w, total_h

    def relocate_over_spin(self):
        """
        Центрируем видимые цифры над spin-боксом,
        но сам QWidget делаем шире/выше из-за hitbox padding.
        """
        if not self.spin:
            return

        g = self.spin.geometry()

        digits_w, digits_h = self._digits_size()
        widget_w, widget_h = self._current_size()

        digits_x = g.center().x() - digits_w // 2 + OFFSET_X
        digits_y = g.top() - digits_h + OFFSET_Y

        x = digits_x - HITBOX_PAD_X
        y = digits_y - HITBOX_PAD_Y

        self.setGeometry(int(x), int(y), int(widget_w), int(widget_h))
        self.raise_()

    def _global_hit_rect(self) -> QRect:
        if not self.isVisible():
            return QRect()

        try:
            top_left = self.mapToGlobal(QPoint(0, 0))
            return QRect(top_left, self.size())
        except Exception:
            return QRect()

    def _event_global_pos(self, ev) -> QPoint:
        try:
            return ev.globalPosition().toPoint()
        except Exception:
            pass

        try:
            return ev.globalPos()
        except Exception:
            pass

        return QCursor.pos()

    # ====== прокрутка ======
    def _wheel_delta_y(self, ev) -> int:
        dy = 0

        try:
            dy = int(ev.angleDelta().y())
        except Exception:
            dy = 0

        # Для некоторых тачпадов/драйверов.
        if dy == 0:
            try:
                dy = int(ev.pixelDelta().y())
            except Exception:
                dy = 0

        return dy

    def _apply_wheel_event(self, ev) -> bool:
        if not self.spin:
            return False

        dy = self._wheel_delta_y(ev)
        if dy == 0:
            return False

        # Обычная мышь обычно даёт 120 за один щелчок.
        # Если прилетело 240/360 — учитываем как 2/3 шага.
        steps = 1
        if abs(dy) >= 120:
            steps = max(1, abs(dy) // 120)

        if dy > 0:
            self.spin.stepBy(int(steps))
        else:
            self.spin.stepBy(-int(steps))

        self.update()

        try:
            ev.accept()
        except Exception:
            pass

        return True

    # ====== события ======
    def _on_spin_changed(self, _v: int):
        self.relocate_over_spin()
        self.update()

    def eventFilter(self, obj, ev) -> bool:
        if ev is not None and ev.type() == QEvent.Wheel:
            if not self.isVisible() or not self.isEnabled():
                return False

            # Если открыт ввод уровня — не перехватываем колесо.
            try:
                if self._editor_popup is not None and self._editor_popup.isVisible():
                    return False
            except Exception:
                pass

            gp = self._event_global_pos(ev)
            if self._global_hit_rect().contains(gp):
                return self._apply_wheel_event(ev)

        return super().eventFilter(obj, ev)

    def paintEvent(self, _ev):
        if self.sprite.isNull() or not self.spin:
            return

        if SHOW_SCROLL_HITBOX:
            p_dbg = QPainter(self)
            p_dbg.setRenderHint(QPainter.Antialiasing, True)

            r = self.rect()
            p_dbg.fillRect(r, HITBOX_COLOR)

            pen = QPen(HITBOX_BORDER)
            pen.setWidth(2)
            p_dbg.setPen(pen)
            p_dbg.drawRect(r.adjusted(1, 1, -1, -1))

            p_dbg.end()

        val = int(self.spin.value())
        tens, ones = (val // 10) % 10, val % 10

        tw, th = self._digit_tile_size()
        w_digit = max(1, int(tw * SCALE))
        h_digit = max(1, int(th * SCALE))

        digits_w = w_digit * FIXED_DIGITS + DIGIT_GAP * (FIXED_DIGITS - 1)
        digits_h = h_digit

        left = (self.width() - digits_w) // 2
        top = (self.height() - digits_h) // 2

        dst_t = QRect(left, top, w_digit, h_digit)
        dst_o = QRect(left + w_digit + DIGIT_GAP, top, w_digit, h_digit)

        src_t = self._src_rect_for_digit(tens)
        src_o = self._src_rect_for_digit(ones)

        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        p.drawPixmap(dst_t, self.sprite, src_t)
        p.drawPixmap(dst_o, self.sprite, src_o)

        p.end()

    def wheelEvent(self, ev):
        if self._apply_wheel_event(ev):
            return

        super().wheelEvent(ev)

    def mousePressEvent(self, ev):
        """
        ЛКМ по зоне — открыть инлайн-ввод уровня.
        Колесо при этом работает отдельно через wheelEvent/eventFilter.
        """
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)

        gp = self.mapToGlobal(ev.pos())

        if self._editor_popup is None:
            self._editor_popup = _InlineEditorPopup(self)

        self._editor_popup.open_at(gp)
        ev.accept()

    def show(self):
        super().show()
        try:
            self.raise_()
        except Exception:
            pass

    def hide(self):
        super().hide()

    def closeEvent(self, ev):
        if self._app_filter_installed:
            app = QApplication.instance()
            if app is not None:
                try:
                    app.removeEventFilter(self)
                except Exception:
                    pass

            self._app_filter_installed = False

        super().closeEvent(ev)
