from __future__ import annotations

import os
import sys
from pathlib import Path

# ВАЖНО: эти переменные должны быть выставлены ДО импортов PySide6
# (иначе Qt уже инициализируется с другими настройками масштабирования)
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QIcon, QPixmap, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.rqcalc.db import DataAccess  # noqa: E402
from src.rqcalc.gui.main_window import MainWindow  # noqa: E402


def app_dir() -> Path:
    """
    Базовая папка приложения:
    - в exe (PyInstaller): папка, где лежит RQ_Calc.exe
    - в исходниках: папка, где лежит этот файл
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_db(base: Path) -> Path:
    """
    Ищем rqdata.sqlite.
    ВАЖНО: в PyInstaller __file__ может указывать в _internal, поэтому ищем:
      1) рядом с exe (base/rqdata.sqlite)
      2) в base/_internal/rqdata.sqlite (на всякий)
      3) твои старые пути (Calc_src*, если вдруг ещё используется)
    """
    candidates = (
        base / "rqdata.sqlite",
        base / "_internal" / "rqdata.sqlite",
        base / "Calc_src2" / "Calc" / "rqdata.sqlite",
        base / "Calc_src" / "Calc" / "rqdata.sqlite",
    )

    for p in candidates:
        if p.exists():
            return p

    # В dev можно поискать глубже, но в exe лучше не делать rglob по dist
    if not getattr(sys, "frozen", False):
        found = next(base.rglob("rqdata.sqlite"), None)
        if found:
            return Path(found)

    raise FileNotFoundError("rqdata.sqlite not found")


def _load_app_icon(base: Path) -> QIcon:
    """
    Загружаем иконку приложения/окна.
    Приоритет: .ico -> .png (на случай если ico нет).
    """
    ico_path = base / "resources" / "RQCalc_logo.ico"
    if ico_path.exists():
        icon = QIcon(str(ico_path))
        if not icon.isNull():
            return icon

    png_path = base / "resources" / "RQCalc_logo.png"
    if png_path.exists():
        pm = QPixmap(str(png_path))
        if not pm.isNull():
            # аккуратно обрежем пустую прозрачную рамку (если есть)
            img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
            w, h = img.width(), img.height()

            def row_has_alpha(y: int, thr: int = 0) -> bool:
                for x in range(w):
                    if ((img.pixel(x, y) >> 24) & 0xFF) > thr:
                        return True
                return False

            def col_has_alpha(x: int, y0: int, y1: int, thr: int = 0) -> bool:
                for y in range(y0, y1 + 1):
                    if ((img.pixel(x, y) >> 24) & 0xFF) > thr:
                        return True
                return False

            top = 0
            while top < h and not row_has_alpha(top):
                top += 1

            if top < h:
                bottom = h - 1
                while bottom >= top and not row_has_alpha(bottom):
                    bottom -= 1

                left = 0
                while left < w and not col_has_alpha(left, top, bottom):
                    left += 1

                right = w - 1
                while right >= left and not col_has_alpha(right, top, bottom):
                    right -= 1

                if right >= left and bottom >= top:
                    pm = pm.copy(left, top, right - left + 1, bottom - top + 1)

            icon = QIcon()
            # Windows сам выберет нужный размер из набора
            sz = 256
            icon.addPixmap(pm.scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            if not icon.isNull():
                return icon

    return QIcon()


def main() -> None:
    base = app_dir()
    db_path = find_db(base)

    # Чтобы на панели задач Windows это было "нормальное приложение", а не "неизвестное"
    # и чтобы не группировалось под python.exe
    if sys.platform.startswith("win"):
        try:
            import ctypes  # noqa: S402

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RQCalc.RQ_Calc")  # type: ignore[attr-defined]
        except Exception:
            pass

    app = QApplication(sys.argv)

    icon = _load_app_icon(base)
    if not icon.isNull():
        app.setWindowIcon(icon)

    data = DataAccess(db_path)
    w = MainWindow(data)

    # Важно: продублировать на окно — именно это часто решает иконку/опознавание в taskbar
    if not icon.isNull():
        w.setWindowIcon(icon)

    # Тёмная тема (если файл доступен)
    style_candidates = (
        base / "src" / "rqcalc" / "gui" / "style.qss",
        base / "_internal" / "src" / "rqcalc" / "gui" / "style.qss",
    )
    for sp in style_candidates:
        if sp.exists():
            try:
                w.setStyleSheet(sp.read_text(encoding="utf-8"))
            except Exception:
                pass
            break

    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()