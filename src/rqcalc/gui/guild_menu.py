from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any

from PySide6.QtCore import Qt, QPoint, QRect, QEvent, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QBitmap, QFont, QPen, QGuiApplication
from PySide6.QtWidgets import QWidget, QLabel, QApplication, QFrame


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

def _to_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        try:
            return int(float(str(v).strip()))
        except Exception:
            return int(default)

def _to_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        try:
            return float(str(v).replace(",", ".").strip())
        except Exception:
            return float(default)

def _to_str(v) -> str:
    try:
        return str(v or "")
    except Exception:
        return ""

def _fmt_num(v: Any) -> str:
    try:
        fv = float(v)
    except Exception:
        return str(v)
    if abs(fv - round(fv)) < 1e-9:
        return str(int(round(fv)))
    s = f"{fv:.4f}".rstrip("0").rstrip(".")
    return s or "0"

def _load_db_image_pixmap(conn, image_id: int) -> QPixmap:
    iid = int(image_id or 0)
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


class _GuildTalentTooltip(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)

        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setObjectName("guildTalentTooltip")
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

    def set_content(self, title: str, active_line: str, body: str) -> None:
        title = html.escape(title or "")
        active_line = html.escape(active_line or "")
        body = html.escape(body or "—").replace("\n", "<br>")

        color_title = "#f2c45d"   # жёлто-золотистый
        color_text = "#f2f2f2"    # основной белый
        color_green = "#00d183"   # активное умение / акценты

        parts: List[str] = []

        parts.append(
            f"<div style='color:{color_title}; font-weight:700; font-size:14px;'>"
            f"{title}"
            f"</div>"
        )

        if active_line:
            parts.append(
                f"<div style='color:{color_green}; font-size:12px; margin-top:4px; font-weight:700;'>"
                f"{active_line}"
                f"</div>"
            )

        parts.append(
            f"<div style='color:{color_text}; font-size:12px; margin-top:6px;'>"
            f"{body}"
            f"</div>"
        )

        html_text = "<div>" + "".join(parts) + "</div>"
        self._lab.setText(html_text)

        max_w = 300
        self._lab.setFixedWidth(max_w)
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


class GuildMenu(QWidget):
    closed = Signal()
    selectionChanged = Signal()

    BG_PATH = "resources/guild/guild_menu.png"
    CLOSE_ACTIVE_PATH = "resources/helper_buttons/close_button_active.png"
    ACTIVE_OVERLAY_PATH = "resources/guild/buff_active.png"
    RESET_ACTIVE_PATH = "resources/guild/reset_active.png"
    RESET_PRESSED_PATH = "resources/guild/reset_pressed.png"

    CLOSE_RECT = QRect(733, 3, 24, 24)
    RESET_RECT = QRect(591, 322, 120, 70)
    FALLBACK_SIZE = (769, 528)

    GRID_START_X = 109
    GRID_START_Y = 101
    CELL_SIZE = 52
    CELL_GAP_X = 28
    CELL_GAP_Y = 28
    COLS = 4

    OVERLAY_SIZE = 70
    COUNTER_FONT_PX = 13

    POINTS_RECT = QRect(627, 268, 55, 38)
    POINTS_FONT_PX = 46
    POINTS_COLOR = QColor("#b87e01")

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

        self._active_overlay_pm = QPixmap(_resolve_resource(self.ACTIVE_OVERLAY_PATH))
        self._reset_active_pm = QPixmap(_resolve_resource(self.RESET_ACTIVE_PATH))
        self._reset_pressed_pm = QPixmap(_resolve_resource(self.RESET_PRESSED_PATH))

        self.setFixedSize(self._bg_pm.size())
        self._apply_window_mask_from_bg()

        self._drag_active = False
        self._drag_offset = QPoint()
        self._last_global_pos: Optional[QPoint] = None

        self._close_down = False
        self._close_active_pm = QPixmap(_resolve_resource(self.CLOSE_ACTIVE_PATH))

        self._reset_hover = False
        self._reset_down = False

        self._pending_click_kind: str = ""
        self._pending_branch_id: int = 0
        self._pending_talent_id: int = 0

        self._close = QLabel(self)
        self._close.setGeometry(self.CLOSE_RECT)
        self._close.setAttribute(Qt.WA_TranslucentBackground, True)
        self._close.setAutoFillBackground(False)
        self._close.setStyleSheet("background-color: rgba(0,0,0,0); border: none;")
        self._close.setScaledContents(False)
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.installEventFilter(self)

        self._tooltip = _GuildTalentTooltip(self)

        self._loaded = False
        self._branches: List[dict] = []
        self._branch_by_id: Dict[int, dict] = {}
        self._branch_state: Dict[int, Dict[str, int]] = {}
        self._hover_branch_id: Optional[int] = None
        self._hover_talent_id: Optional[int] = None
        self._bonus_text_col: Optional[str] = None

        self.hide()

    # ---------------- DB / data ----------------

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

    def _bonus_type_text_column(self, conn) -> Optional[str]:
        if self._bonus_text_col is not None:
            return self._bonus_text_col

        try:
            rows = conn.execute('PRAGMA table_info("BonusType")').fetchall()
        except Exception:
            rows = []

        cols = set()
        for r in rows or []:
            try:
                nm = r["name"] if hasattr(r, "keys") else r[1]
            except Exception:
                nm = None
            if nm:
                cols.add(str(nm).lower())

        if "template" in cols:
            self._bonus_text_col = "Template"
        elif "name" in cols:
            self._bonus_text_col = "Name"
        else:
            self._bonus_text_col = None

        return self._bonus_text_col

    def reload_from_db(self) -> None:
        conn = self._conn()
        self._branches = []
        self._branch_by_id = {}
        self._loaded = True

        if conn is None:
            self.update()
            return

        try:
            branch_rows = conn.execute(
                """
                SELECT Id, Name, MaxPoints
                FROM GuildTalentBranch
                ORDER BY Id
                """
            ).fetchall()
        except Exception:
            branch_rows = []

        branches: List[dict] = []
        for r in branch_rows or []:
            try:
                if hasattr(r, "keys"):
                    bid = _to_int(r["Id"], 0)
                    name = _to_str(r["Name"])
                    maxp = _to_int(r["MaxPoints"], 0)
                else:
                    bid = _to_int(r[0], 0)
                    name = _to_str(r[1])
                    maxp = _to_int(r[2], 0)
            except Exception:
                continue

            if bid <= 0:
                continue

            row = {
                "Id": int(bid),
                "Name": str(name),
                "MaxPoints": max(0, int(maxp)),
                "Talents": [None, None, None, None],
            }
            branches.append(row)

        self._branches = list(branches)
        self._branch_by_id = {int(b["Id"]): b for b in self._branches}

        if not self._branches:
            self.update()
            return

        branch_ids = [int(b["Id"]) for b in self._branches]
        ph = ",".join(["?"] * len(branch_ids))

        try:
            talent_rows = conn.execute(
                f"""
                SELECT Id, Branch_Id, Name, Description, OrderIndex, Active, Image_Id, GrayImage_Id
                FROM GuildTalent
                WHERE Branch_Id IN ({ph})
                ORDER BY Branch_Id, OrderIndex, Id
                """,
                tuple(branch_ids),
            ).fetchall()
        except Exception:
            talent_rows = []

        talents_by_id: Dict[int, dict] = {}

        for r in talent_rows or []:
            try:
                if hasattr(r, "keys"):
                    tid = _to_int(r["Id"], 0)
                    bid = _to_int(r["Branch_Id"], 0)
                    name = _to_str(r["Name"])
                    desc = _to_str(r["Description"])
                    order_idx = _to_int(r["OrderIndex"], 0)
                    active = _to_int(r["Active"], 0)
                    image_id = _to_int(r["Image_Id"], 0)
                    gray_id = _to_int(r["GrayImage_Id"], 0)
                else:
                    tid = _to_int(r[0], 0)
                    bid = _to_int(r[1], 0)
                    name = _to_str(r[2])
                    desc = _to_str(r[3])
                    order_idx = _to_int(r[4], 0)
                    active = _to_int(r[5], 0)
                    image_id = _to_int(r[6], 0)
                    gray_id = _to_int(r[7], 0)
            except Exception:
                continue

            if tid <= 0 or bid <= 0:
                continue
            if bid not in self._branch_by_id:
                continue
            if order_idx < 0 or order_idx >= self.COLS:
                continue

            talent = {
                "Id": int(tid),
                "Branch_Id": int(bid),
                "Name": str(name),
                "Description": str(desc),
                "OrderIndex": int(order_idx),
                "Active": int(active),
                "Image_Id": int(image_id),
                "GrayImage_Id": int(gray_id),
                "VarsByIndex": {},
                "BonusTexts": [],
            }

            self._branch_by_id[bid]["Talents"][order_idx] = talent
            talents_by_id[int(tid)] = talent

        talent_ids = [int(x) for x in talents_by_id.keys()]
        if talent_ids:
            ph2 = ",".join(["?"] * len(talent_ids))

            try:
                var_rows = conn.execute(
                    f"""
                    SELECT Talent_Id, "Index", Points, Value
                    FROM GuildTalentVariable
                    WHERE Talent_Id IN ({ph2})
                    ORDER BY Talent_Id, "Index", Points, Id
                    """,
                    tuple(talent_ids),
                ).fetchall()
            except Exception:
                var_rows = []

            for r in var_rows or []:
                try:
                    if hasattr(r, "keys"):
                        tid = _to_int(r["Talent_Id"], 0)
                        idx = _to_int(r["Index"], 0)
                        pts = _to_int(r["Points"], 0)
                        val = _to_float(r["Value"], 0.0)
                    else:
                        tid = _to_int(r[0], 0)
                        idx = _to_int(r[1], 0)
                        pts = _to_int(r[2], 0)
                        val = _to_float(r[3], 0.0)
                except Exception:
                    continue

                talent = talents_by_id.get(int(tid))
                if not talent:
                    continue

                by_idx = talent.setdefault("VarsByIndex", {})
                by_pts = by_idx.setdefault(int(idx), {})
                by_pts[int(pts)] = float(val)

            bonus_text_col = self._bonus_type_text_column(conn)

            try:
                if bonus_text_col:
                    bonus_rows = conn.execute(
                        f"""
                        SELECT gtb.Talent_Id, gtb.Type_Id, bt.{bonus_text_col} AS BonusText
                        FROM GuildTalentBonus AS gtb
                        JOIN BonusType AS bt ON bt.Id = gtb.Type_Id
                        WHERE gtb.Talent_Id IN ({ph2})
                        ORDER BY gtb.Talent_Id, gtb.Id
                        """,
                        tuple(talent_ids),
                    ).fetchall()
                else:
                    bonus_rows = conn.execute(
                        f"""
                        SELECT Talent_Id, Type_Id
                        FROM GuildTalentBonus
                        WHERE Talent_Id IN ({ph2})
                        ORDER BY Talent_Id, Id
                        """,
                        tuple(talent_ids),
                    ).fetchall()
            except Exception:
                bonus_rows = []

            for r in bonus_rows or []:
                try:
                    if hasattr(r, "keys"):
                        tid = _to_int(r["Talent_Id"], 0)
                        text = _to_str(r["BonusText"]) if bonus_text_col else ""
                    else:
                        tid = _to_int(r[0], 0)
                        text = _to_str(r[2]) if bonus_text_col else ""
                except Exception:
                    continue

                talent = talents_by_id.get(int(tid))
                if not talent:
                    continue

                if text:
                    talent.setdefault("BonusTexts", []).append(str(text))

        valid_branch_ids = {int(b["Id"]) for b in self._branches}
        new_state: Dict[int, Dict[str, int]] = {}
        for bid, st in (self._branch_state or {}).items():
            if int(bid) not in valid_branch_ids:
                continue
            row = self._branch_by_id.get(int(bid))
            if not row:
                continue
            tid = _to_int((st or {}).get("Talent_Id"), 0)
            pts = _to_int((st or {}).get("Points"), 0)
            if tid <= 0 or pts <= 0:
                continue

            exists = False
            for t in (row.get("Talents") or []):
                if isinstance(t, dict) and _to_int(t.get("Id"), 0) == tid:
                    exists = True
                    break
            if exists:
                new_state[int(bid)] = {"Talent_Id": int(tid), "Points": int(pts)}

        self._branch_state = dict(new_state)
        self.update()

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.reload_from_db()

    # ---------------- helpers ----------------

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

    def _set_close_pixmap(self, pm: Optional[QPixmap]) -> None:
        try:
            self._close.clear()
        except Exception:
            pass

        if pm is None or pm.isNull():
            return

        try:
            scaled = pm.scaled(
                self._close.size(),
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
        except Exception:
            return

        canvas = QPixmap(self._close.size())
        canvas.fill(Qt.GlobalColor.transparent)

        p = QPainter(canvas)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(0, 0, scaled)
        p.end()

        self._close.setPixmap(canvas)

    def _clear_pending_click(self) -> None:
        self._pending_click_kind = ""
        self._pending_branch_id = 0
        self._pending_talent_id = 0

    def _reset_all_selections(self) -> None:
        had_any = bool(self._branch_state)

        self._branch_state = {}
        self._hover_branch_id = None
        self._hover_talent_id = None
        self._tooltip.hide()

        if had_any:
            self._notify_selection_changed()

        self.update()

    def _update_reset_hover(self, local_pos: QPoint) -> None:
        new_hover = bool(self.RESET_RECT.contains(local_pos))
        if self._reset_hover != new_hover:
            self._reset_hover = new_hover
            self.update()

    def _branch_row_rect(self, row_idx: int) -> QRect:
        y = self.GRID_START_Y + row_idx * (self.CELL_SIZE + self.CELL_GAP_Y)
        x = self.GRID_START_X
        w = self.COLS * self.CELL_SIZE + (self.COLS - 1) * self.CELL_GAP_X
        h = self.CELL_SIZE
        return QRect(int(x), int(y), int(w), int(h))

    def _cell_rect(self, row_idx: int, col_idx: int) -> QRect:
        x = self.GRID_START_X + col_idx * (self.CELL_SIZE + self.CELL_GAP_X)
        y = self.GRID_START_Y + row_idx * (self.CELL_SIZE + self.CELL_GAP_Y)
        return QRect(int(x), int(y), int(self.CELL_SIZE), int(self.CELL_SIZE))

    def _hit_talent(self, local_pos: QPoint) -> Tuple[Optional[int], Optional[dict], Optional[QRect]]:
        self._ensure_loaded()

        for row_idx, branch in enumerate(self._branches):
            talents = branch.get("Talents") or []
            for col_idx in range(self.COLS):
                if col_idx >= len(talents):
                    continue
                talent = talents[col_idx]
                if not isinstance(talent, dict):
                    continue

                rect = self._cell_rect(row_idx, col_idx)
                if rect.contains(local_pos):
                    return int(branch["Id"]), talent, rect

        return None, None, None

    def _branch_max_points(self, branch_id: int) -> int:
        row = self._branch_by_id.get(int(branch_id))
        if not row:
            return 0
        return max(0, _to_int(row.get("MaxPoints"), 0))

    def _branch_index(self, branch_id: int) -> int:
        bid = int(branch_id or 0)
        for i, row in enumerate(self._branches or []):
            if _to_int(row.get("Id"), 0) == bid:
                return int(i)
        return -1

    def _branch_points(self, branch_id: int) -> int:
        st = self._branch_state_for(branch_id)
        return max(0, _to_int(st.get("Points"), 0))

    def _branch_is_fully_selected(self, branch_id: int) -> bool:
        maxp = self._branch_max_points(branch_id)
        if maxp <= 0:
            return False

        st = self._branch_state_for(branch_id)
        tid = _to_int(st.get("Talent_Id"), 0)
        pts = _to_int(st.get("Points"), 0)
        return tid > 0 and pts >= maxp

    def _can_select_branch(self, branch_id: int) -> bool:
        """
        Следующая ветка доступна только если все предыдущие ветки
        выбраны на максимум MaxPoints.
        """
        idx = self._branch_index(branch_id)
        if idx <= 0:
            return True

        for i in range(idx):
            row = (self._branches or [])[i]
            prev_id = _to_int(row.get("Id"), 0)
            if prev_id <= 0:
                continue
            if not self._branch_is_fully_selected(prev_id):
                return False

        return True

    def _has_selected_higher_branch(self, branch_id: int) -> bool:
        """
        Есть ли любая более поздняя ветка с ненулевым выбором.
        Пока такие есть — менять количество очков в более ранней ветке нельзя.
        """
        idx = self._branch_index(branch_id)
        if idx < 0:
            return False

        branches = self._branches or []
        for i in range(idx + 1, len(branches)):
            other_id = _to_int(branches[i].get("Id"), 0)
            if other_id <= 0:
                continue
            if self._branch_points(other_id) > 0:
                return True

        return False

    def _branch_state_for(self, branch_id: int) -> Dict[str, int]:
        st = self._branch_state.get(int(branch_id))
        if isinstance(st, dict):
            return dict(st)
        return {"Talent_Id": 0, "Points": 0}

    def _set_branch_state(self, branch_id: int, talent_id: int, points: int) -> None:
        branch_id = int(branch_id or 0)
        talent_id = int(talent_id or 0)
        points = int(points or 0)

        if branch_id <= 0:
            return

        old = self._branch_state.get(int(branch_id), None)
        old_tid = _to_int((old or {}).get("Talent_Id"), 0)
        old_pts = _to_int((old or {}).get("Points"), 0)

        maxp = self._branch_max_points(branch_id)
        if maxp <= 0 or talent_id <= 0 or points <= 0:
            if int(branch_id) in self._branch_state:
                self._branch_state.pop(int(branch_id), None)
                self._notify_selection_changed()
            return

        points = min(int(points), int(maxp))

        if old_tid == int(talent_id) and old_pts == int(points):
            return

        self._branch_state[int(branch_id)] = {
            "Talent_Id": int(talent_id),
            "Points": int(points),
        }
        self._notify_selection_changed()

    def _left_click_talent(self, branch_id: int, talent_id: int) -> None:
        maxp = self._branch_max_points(branch_id)
        if maxp <= 0:
            return

        # Пока предыдущая ветка не вкачана на максимум — следующую не трогаем
        if not self._can_select_branch(branch_id):
            return

        st = self._branch_state_for(branch_id)
        cur_tid = _to_int(st.get("Talent_Id"), 0)
        cur_pts = _to_int(st.get("Points"), 0)

        # Если уже выбраны более поздние ветки —
        # менять количество очков в этой ветке нельзя.
        # Разрешаем только переключить сам талант, сохранив текущее число очков.
        if self._has_selected_higher_branch(branch_id):
            if cur_tid > 0 and cur_pts > 0 and cur_tid != int(talent_id):
                self._set_branch_state(branch_id, talent_id, cur_pts)
            return

        if cur_tid == int(talent_id) and cur_pts > 0:
            if cur_pts >= maxp:
                self._set_branch_state(branch_id, 0, 0)
            else:
                self._set_branch_state(branch_id, talent_id, cur_pts + 1)
            return

        # Выбор другого таланта в той же ветке:
        # старая ячейка сбрасывается, новая начинает с 1
        self._set_branch_state(branch_id, talent_id, 1)

    def _right_click_talent(self, branch_id: int, talent_id: int) -> None:
        maxp = self._branch_max_points(branch_id)
        if maxp <= 0:
            return

        # Пока предыдущая ветка не вкачана на максимум — следующую не трогаем
        if not self._can_select_branch(branch_id):
            return

        st = self._branch_state_for(branch_id)
        cur_tid = _to_int(st.get("Talent_Id"), 0)
        cur_pts = _to_int(st.get("Points"), 0)

        # Если уже выбраны более поздние ветки —
        # менять количество очков в этой ветке нельзя.
        # Разрешаем только переключить сам талант, сохранив текущее число очков.
        if self._has_selected_higher_branch(branch_id):
            if cur_tid > 0 and cur_pts > 0 and cur_tid != int(talent_id):
                self._set_branch_state(branch_id, talent_id, cur_pts)
            return

        if cur_tid == int(talent_id) and cur_pts > 0:
            new_pts = cur_pts - 1
            if new_pts <= 0:
                self._set_branch_state(branch_id, 0, 0)
            else:
                self._set_branch_state(branch_id, talent_id, new_pts)
            return

        # ПКМ по невыбранному таланту = выбрать его сразу на максимум ветки
        self._set_branch_state(branch_id, talent_id, maxp)

    def _selected_points_for_talent(self, branch_id: int, talent_id: int) -> int:
        st = self._branch_state_for(branch_id)
        if _to_int(st.get("Talent_Id"), 0) == int(talent_id):
            return max(0, _to_int(st.get("Points"), 0))
        return 0

    def get_selected_talents(self) -> List[dict]:
        out: List[dict] = []
        for branch in self._branches:
            bid = _to_int(branch.get("Id"), 0)
            st = self._branch_state_for(bid)
            tid = _to_int(st.get("Talent_Id"), 0)
            pts = _to_int(st.get("Points"), 0)
            if bid > 0 and tid > 0 and pts > 0:
                out.append(
                    {
                        "Branch_Id": int(bid),
                        "Talent_Id": int(tid),
                        "Points": int(pts),
                    }
                )
        return out

    def _publish_selected_talents(self) -> None:
        selected: List[dict] = []

        for row in (self.get_selected_talents() or []):
            if not isinstance(row, dict):
                continue

            bid = _to_int(row.get("Branch_Id"), 0)
            tid = _to_int(row.get("Talent_Id"), 0)
            pts = _to_int(row.get("Points"), 0)

            if bid <= 0 or tid <= 0 or pts <= 0:
                continue

            selected.append(
                {
                    "Branch_Id": int(bid),
                    "Talent_Id": int(tid),
                    "Points": int(pts),
                }
            )

        try:
            app = QApplication.instance()
            if app is not None:
                app.setProperty("player_guild_talents", list(selected))
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

    def _total_branch_points_limit(self) -> int:
        total = 0
        for branch in (self._branches or []):
            total += max(0, _to_int(branch.get("MaxPoints"), 0))
        return int(total)

    def _allocated_branch_points(self) -> int:
        total = 0
        for st in (self._branch_state or {}).values():
            if not isinstance(st, dict):
                continue
            total += max(0, _to_int(st.get("Points"), 0))
        return int(total)

    def _remaining_branch_points(self) -> int:
        total_limit = self._total_branch_points_limit()
        allocated = self._allocated_branch_points()
        return max(0, int(total_limit - allocated))

    def _total_branch_points_limit(self) -> int:
        total = 0
        for branch in (self._branches or []):
            total += max(0, _to_int(branch.get("MaxPoints"), 0))
        return int(total)

    def _allocated_branch_points(self) -> int:
        total = 0
        for st in (self._branch_state or {}).values():
            if not isinstance(st, dict):
                continue
            total += max(0, _to_int(st.get("Points"), 0))
        return int(total)

    def _remaining_branch_points(self) -> int:
        total_limit = self._total_branch_points_limit()
        allocated = self._allocated_branch_points()
        return max(0, int(total_limit - allocated))

    def _pick_var_value_for_points(self, by_points: Dict[int, float], points: int) -> Optional[float]:
        if not isinstance(by_points, dict) or not by_points:
            return None

        p = int(points or 0)
        if p in by_points:
            return float(by_points[p])

        keys = sorted(int(x) for x in by_points.keys())
        if not keys:
            return None

        lower = [k for k in keys if k <= p]
        if lower:
            return float(by_points[max(lower)])

        return float(by_points[keys[0]])

    def _resolve_placeholders(
            self,
            text: str,
            vars_by_index: Dict[int, Dict[int, float]],
            points: int,
            *,
            plus_for_positive: bool = False,
    ) -> str:
        s = str(text or "")
        if not s:
            return ""

        def _format_value_for_placeholder(val: Any, match) -> str:
            sval = _fmt_num(val)

            if not plus_for_positive:
                return sval

            try:
                fv = float(val)
            except Exception:
                return sval

            # Минус не трогаем.
            if fv <= 0:
                return sval

            # Если в шаблоне уже руками стоит + или - перед {0},
            # не делаем "++2" или "+-2".
            try:
                start = int(match.start())
                before = s[:start].rstrip()
                if before.endswith("+") or before.endswith("-"):
                    return sval
            except Exception:
                pass

            return f"+{sval}"

        def _repl(m):
            idx = _to_int(m.group(1), 0)
            by_points = vars_by_index.get(idx) or vars_by_index.get(0) or {}
            val = self._pick_var_value_for_points(by_points, points)
            if val is None:
                return m.group(0)
            return _format_value_for_placeholder(val, m)

        return re.sub(r"\{(\d+)\}", _repl, s)

    def _tooltip_body_for_talent(self, branch_id: int, talent: dict) -> str:
        pts = self._selected_points_for_talent(branch_id, _to_int(talent.get("Id"), 0))
        preview_points = pts if pts > 0 else 1

        desc = _to_str(talent.get("Description")).strip()
        vars_by_index = talent.get("VarsByIndex") or {}

        # Описание самого GuildTalent не трогаем:
        # там плюс перед значениями автоматически не добавляем.
        if desc:
            body = self._resolve_placeholders(
                desc,
                vars_by_index,
                preview_points,
                plus_for_positive=False,
            ).strip()
            return body or "—"

        lines: List[str] = []

        # А вот строки GuildTalentBonus должны показывать + перед положительным Value.
        for bt in (talent.get("BonusTexts") or []):
            line = self._resolve_placeholders(
                _to_str(bt),
                vars_by_index,
                preview_points,
                plus_for_positive=True,
            ).strip()

            if line:
                lines.append(line)

        return "\n".join(lines).strip() or "—"

    def _show_tooltip_for_talent(self, branch_id: int, talent: dict, cell_rect: QRect) -> None:
        title = _to_str(talent.get("Name")).strip()
        active_line = "Активное умение" if _to_int(talent.get("Active"), 0) == 1 else ""
        body = self._tooltip_body_for_talent(branch_id, talent)

        self._tooltip.set_content(title, active_line, body)

        x = cell_rect.right() + 12
        y = cell_rect.top()

        if x + self._tooltip.width() > self.width() - 6:
            x = cell_rect.left() - self._tooltip.width() - 12
        if x < 6:
            x = 6

        if y + self._tooltip.height() > self.height() - 6:
            y = self.height() - self._tooltip.height() - 6
        if y < 6:
            y = 6

        self._tooltip.move(int(x), int(y))
        self._tooltip.show()
        self._tooltip.raise_()

    def _update_hover_from_pos(self, local_pos: QPoint) -> None:
        bid, talent, rect = self._hit_talent(local_pos)

        if bid is None or not isinstance(talent, dict) or rect is None:
            self._hover_branch_id = None
            self._hover_talent_id = None
            self._tooltip.hide()
            self.update()
            return

        tid = _to_int(talent.get("Id"), 0)
        if self._hover_branch_id == int(bid) and self._hover_talent_id == int(tid):
            self._show_tooltip_for_talent(int(bid), talent, rect)
            return

        self._hover_branch_id = int(bid)
        self._hover_talent_id = int(tid)
        self._show_tooltip_for_talent(int(bid), talent, rect)
        self.update()

    def _talent_pixmap_for_state(self, talent: dict, selected_points: int) -> QPixmap:
        conn = self._conn()
        if conn is None:
            return QPixmap()

        if selected_points > 0:
            iid = _to_int(talent.get("Image_Id"), 0)
            if iid <= 0:
                iid = _to_int(talent.get("GrayImage_Id"), 0)
        else:
            iid = _to_int(talent.get("GrayImage_Id"), 0)
            if iid <= 0:
                iid = _to_int(talent.get("Image_Id"), 0)

        return _load_db_image_pixmap(conn, iid)

    # ---------------- life cycle ----------------

    def open_centered(self, host: QWidget) -> None:
        self._ensure_loaded()

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

        self.update()

    # ---------------- events ----------------

    def eventFilter(self, obj, ev) -> bool:
        if obj is self._close:
            if ev.type() == QEvent.Enter:
                if not self._close_active_pm.isNull():
                    self._set_close_pixmap(self._close_active_pm)
                return False

            if ev.type() == QEvent.Leave:
                if not self._close_down:
                    self._set_close_pixmap(None)
                return False

            if ev.type() == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
                self._close_down = True
                if not self._close_active_pm.isNull():
                    self._set_close_pixmap(self._close_active_pm)
                return True

            if ev.type() == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
                was_down = self._close_down
                self._close_down = False

                try:
                    gp = ev.globalPosition().toPoint()
                except Exception:
                    gp = ev.globalPos()

                lp = self._close.mapFromGlobal(gp)
                over = self._close.rect().contains(lp)

                if not over:
                    self._set_close_pixmap(None)

                if was_down and over:
                    self.close()
                return True

            return False

        return super().eventFilter(obj, ev)

    def mousePressEvent(self, ev) -> None:
        local_pos = ev.position().toPoint()

        if ev.button() == Qt.LeftButton:
            if self.CLOSE_RECT.contains(local_pos):
                ev.accept()
                return

            self._update_reset_hover(local_pos)

            if self.RESET_RECT.contains(local_pos):
                self._reset_down = True
                self._clear_pending_click()
                self.update()
                ev.accept()
                return

            bid, talent, _rect = self._hit_talent(local_pos)
            if bid is not None and isinstance(talent, dict):
                self._reset_down = False
                self._pending_click_kind = "talent_left"
                self._pending_branch_id = int(bid)
                self._pending_talent_id = _to_int(talent.get("Id"), 0)
                self._update_hover_from_pos(local_pos)
                self.update()
                ev.accept()
                return

            self._reset_down = False
            self._clear_pending_click()

            try:
                gp = ev.globalPosition().toPoint()
            except Exception:
                gp = ev.globalPos()

            self._drag_active = True
            self._drag_offset = gp - self.frameGeometry().topLeft()
            ev.accept()
            return

        if ev.button() == Qt.RightButton:
            self._update_reset_hover(local_pos)

            bid, talent, _rect = self._hit_talent(local_pos)
            if bid is not None and isinstance(talent, dict):
                self._reset_down = False
                self._pending_click_kind = "talent_right"
                self._pending_branch_id = int(bid)
                self._pending_talent_id = _to_int(talent.get("Id"), 0)
                self._update_hover_from_pos(local_pos)
                self.update()
                ev.accept()
                return

            self._clear_pending_click()

        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        local_pos = ev.position().toPoint()

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

        self._update_reset_hover(local_pos)
        self._update_hover_from_pos(local_pos)
        self.update()

        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        local_pos = ev.position().toPoint()

        if ev.button() == Qt.LeftButton and self._drag_active:
            self._drag_active = False
            try:
                self._last_global_pos = QPoint(self.pos())
            except Exception:
                pass
            ev.accept()
            return

        if ev.button() == Qt.LeftButton:
            over_reset = bool(self.RESET_RECT.contains(local_pos))
            was_reset_down = bool(self._reset_down)
            self._reset_down = False

            if was_reset_down:
                if over_reset:
                    self._reset_all_selections()
                self.update()
                ev.accept()
                return

            if self._pending_click_kind == "talent_left":
                bid, talent, _rect = self._hit_talent(local_pos)
                if (
                        bid is not None
                        and isinstance(talent, dict)
                        and int(bid) == int(self._pending_branch_id)
                        and _to_int(talent.get("Id"), 0) == int(self._pending_talent_id)
                ):
                    self._left_click_talent(int(bid), _to_int(talent.get("Id"), 0))
                    self._update_hover_from_pos(local_pos)
                    self.update()

                self._clear_pending_click()
                ev.accept()
                return

        if ev.button() == Qt.RightButton:
            if self._pending_click_kind == "talent_right":
                bid, talent, _rect = self._hit_talent(local_pos)
                if (
                        bid is not None
                        and isinstance(talent, dict)
                        and int(bid) == int(self._pending_branch_id)
                        and _to_int(talent.get("Id"), 0) == int(self._pending_talent_id)
                ):
                    self._right_click_talent(int(bid), _to_int(talent.get("Id"), 0))
                    self._update_hover_from_pos(local_pos)
                    self.update()

                self._clear_pending_click()
                ev.accept()
                return

        super().mouseReleaseEvent(ev)

    def leaveEvent(self, ev) -> None:
        self._hover_branch_id = None
        self._hover_talent_id = None
        self._reset_hover = False
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
        self._close_down = False
        self._reset_down = False
        self._reset_hover = False
        self._clear_pending_click()

        try:
            self._last_global_pos = QPoint(self.pos())
        except Exception:
            pass

        self._tooltip.hide()

        try:
            self._set_close_pixmap(None)
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

        # фон
        if self._bg_pm and not self._bg_pm.isNull():
            p.drawPixmap(self.rect(), self._bg_pm)
        else:
            p.fillRect(self.rect(), QColor(20, 20, 20, 240))

        # reset-кнопка
        if self._reset_down and self._reset_hover and self._reset_pressed_pm and not self._reset_pressed_pm.isNull():
            p.drawPixmap(self.RESET_RECT, self._reset_pressed_pm)
        elif self._reset_hover and self._reset_active_pm and not self._reset_active_pm.isNull():
            p.drawPixmap(self.RESET_RECT, self._reset_active_pm)

        self._ensure_loaded()

        # Очки для распределения
        remaining_points = self._remaining_branch_points()
        points_rect = QRect(self.POINTS_RECT)

        f_points = QFont("Segoe UI")
        f_points.setBold(True)
        f_points.setPixelSize(int(self.POINTS_FONT_PX))
        p.setFont(f_points)
        p.setPen(self.POINTS_COLOR)
        p.drawText(points_rect, Qt.AlignCenter, str(int(remaining_points)))

        hover_bid = int(self._hover_branch_id or 0)
        hover_tid = int(self._hover_talent_id or 0)

        for row_idx, branch in enumerate(self._branches):
            bid = _to_int(branch.get("Id"), 0)
            talents = branch.get("Talents") or []

            for col_idx in range(self.COLS):
                if col_idx >= len(talents):
                    continue

                talent = talents[col_idx]
                if not isinstance(talent, dict):
                    continue

                rect = self._cell_rect(row_idx, col_idx)
                tid = _to_int(talent.get("Id"), 0)
                pts = self._selected_points_for_talent(bid, tid)

                pm = self._talent_pixmap_for_state(talent, pts)
                if pm and not pm.isNull():
                    scaled = pm.scaled(rect.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                    p.drawPixmap(rect, scaled)

                if pts > 0 and self._active_overlay_pm and not self._active_overlay_pm.isNull():
                    ov = self._active_overlay_pm.scaled(
                        self.OVERLAY_SIZE,
                        self.OVERLAY_SIZE,
                        Qt.IgnoreAspectRatio,
                        Qt.SmoothTransformation,
                    )
                    ov_rect = QRect(0, 0, self.OVERLAY_SIZE, self.OVERLAY_SIZE)
                    ov_rect.moveCenter(rect.center())
                    p.drawPixmap(ov_rect, ov)

                if hover_bid == bid and hover_tid == tid:
                    pen = QPen(QColor(243, 216, 137, 210), 2)
                    p.setPen(pen)
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 4, 4)

                if pts > 0:
                    badge_w = 16
                    badge_h = 16
                    badge = QRect(rect.right() - badge_w + 1, rect.bottom() - badge_h + 1, badge_w, badge_h)

                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(10, 10, 10, 220))
                    p.drawRoundedRect(badge, 4, 4)

                    pen = QPen(QColor(214, 171, 83, 230), 1)
                    p.setPen(pen)
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(badge, 4, 4)

                    f = QFont("Segoe UI", self.COUNTER_FONT_PX)
                    f.setBold(True)
                    p.setFont(f)
                    p.setPen(QColor(245, 235, 180, 245))
                    p.drawText(badge, Qt.AlignCenter, str(int(pts)))

        p.end()