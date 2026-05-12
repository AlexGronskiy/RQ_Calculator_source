#characteristics_math.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pydoc import html
from typing import Dict, Mapping, Optional, Iterable, Any, List, Tuple

from PySide6.QtCore import Qt, QSize, Signal, QRect, QPoint, QObject, QTimer, QEvent
from PySide6.QtGui import QPixmap, QIcon, QFontMetrics, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
    QSizePolicy, QSpacerItem, QPushButton, QApplication
)

import math
from functools import lru_cache
import re

_VAR_COL_RE = re.compile(r"^(Var|Value)(\d+)$", re.IGNORECASE)
_BT_COL_RE = re.compile(r"^BonusType(?:_?Id)?(\d+)$", re.IGNORECASE)
# --- NEW: Card.Set_Id cache (нужно для RequiredSetSize/RequiredSet_Id) ---
_CARD_SET_ID_CACHE: dict[tuple[int, int], int] = {}  # (id(conn), card_id) -> set_id (0 if none)

_EQUIPTYPE_COLS_CACHE: dict[int, set[str]] = {}
_EQUIPTYPE_WEAPON_CACHE: dict[tuple[int, int], Optional[bool]] = {}

_ACTIVE_EVENT_ID: int = 0
_ACTIVE_STATE_ID: int = 0
_ACTIVE_LOST_CONTROL_ID: int = 0
# Active equipment context for BonusTypeStatCondition (EquipmentType_Id / PairEquipment)
_ACTIVE_EQUIP_TYPE_IDS_SET: set[int] = set()
_ACTIVE_WEAPON_EQUIP_TYPE_ID: int = 0
_ACTIVE_OFFHAND_EQUIP_TYPE_ID: int = 0

def _equiptype_cols(conn) -> set[str]:
    key = id(conn)
    if key in _EQUIPTYPE_COLS_CACHE:
        return _EQUIPTYPE_COLS_CACHE[key]
    cols = _table_columns(conn, "EquipmentType") if conn else []
    s = {str(c).lower() for c in (cols or [])}
    _EQUIPTYPE_COLS_CACHE[key] = s
    return s

def _is_weapon_type_by_equipmenttype(conn, type_id: int) -> Optional[bool]:
    """
    True/False/None:
      - True  -> (IsMeleeWeapon != NULL) OR (IsSingleHandWeapon != NULL)
      - False -> обе NULL
      - None  -> нет conn/Type_Id или нет нужных колонок/таблицы
    """
    if not conn or int(type_id or 0) <= 0:
        return None

    k = (id(conn), int(type_id))
    if k in _EQUIPTYPE_WEAPON_CACHE:
        return _EQUIPTYPE_WEAPON_CACHE[k]

    cols = _equiptype_cols(conn)
    want = []
    if "ismeleeweapon" in cols:
        want.append("IsMeleeWeapon")
    if "issinglehandweapon" in cols:
        want.append("IsSingleHandWeapon")

    if not want:
        _EQUIPTYPE_WEAPON_CACHE[k] = None
        return None

    sql = f'SELECT {", ".join(_qident(c) for c in want)} FROM "EquipmentType" WHERE "Id"=? LIMIT 1'
    try:
        row = conn.execute(sql, (int(type_id),)).fetchone()
    except Exception:
        row = None

    if not row:
        _EQUIPTYPE_WEAPON_CACHE[k] = None
        return None

    # логика ровно как ты хочешь: != NULL
    def _get(cname: str):
        return row[cname] if hasattr(row, "keys") else row[want.index(cname)]

    is_weapon = False
    for c in want:
        if _get(c) is not None:
            is_weapon = True
            break

    _EQUIPTYPE_WEAPON_CACHE[k] = bool(is_weapon)
    return bool(is_weapon)

# ---------------------------------------------------------------------------
# ACTIVE CONTEXT: Event / State (set from main window)
# ---------------------------------------------------------------------------

def set_active_event_state(
        event_id: int = 0,
        state_id: int = 0,
        lost_control_id: int | None = None,
) -> None:
    global _ACTIVE_EVENT_ID, _ACTIVE_STATE_ID, _ACTIVE_LOST_CONTROL_ID

    try:
        _ACTIVE_EVENT_ID = int(event_id or 0)
    except Exception:
        _ACTIVE_EVENT_ID = 0

    try:
        _ACTIVE_STATE_ID = int(state_id or 0)
    except Exception:
        _ACTIVE_STATE_ID = 0

    # ВАЖНО:
    # lost_control_id намеренно optional.
    # Старые вызовы set_active_event_state(event_id, state_id)
    # не должны случайно сбрасывать выбранный контроль.
    if lost_control_id is not None:
        try:
            _ACTIVE_LOST_CONTROL_ID = int(lost_control_id or 0)
        except Exception:
            _ACTIVE_LOST_CONTROL_ID = 0

def get_active_event_id() -> int:
    try:
        return int(_ACTIVE_EVENT_ID or 0)
    except Exception:
        return 0

def get_active_state_id() -> int:
    try:
        return int(_ACTIVE_STATE_ID or 0)
    except Exception:
        return 0

def get_active_lost_control_id() -> int:
    """
    Возвращает текущий выбранный статус контроля.

    Основной источник — QApplication.property("player_lost_control_id"),
    потому что MainWindow уже выставляет это свойство при выборе контроля.
    Глобальная переменная нужна только как fallback.
    """
    try:
        app = QApplication.instance()
        if app is not None:
            v = app.property("player_lost_control_id")
            if v is not None:
                return int(v or 0)
    except Exception:
        pass

    try:
        return int(_ACTIVE_LOST_CONTROL_ID or 0)
    except Exception:
        return 0

# ---------------------------------------------------------------------------
# BonusTypeStatCondition helpers
# ---------------------------------------------------------------------------

_BTS_COND_META_CACHE: dict[
    int,
    tuple[
        str | None,
        str | None,
        str | None,
        str | None,
        str | None,
        str | None,
        str | None,
    ],
] = {}

def _get_bts_condition_meta(conn) -> tuple[
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
]:
    """
    returns:
      (
        table,
        bts_id_col,
        event_col,
        state_col,
        equiptype_col,
        pair_col,
        lost_control_col,
      )

    cached per-connection.
    """
    if not conn:
        return (None, None, None, None, None, None, None)

    k = id(conn)
    if k in _BTS_COND_META_CACHE:
        return _BTS_COND_META_CACHE[k]

    table = _first_existing_table(conn, [
        "BonusTypeStatCondition",
        "BonusTypeCondition",
    ])
    if not table:
        _BTS_COND_META_CACHE[k] = (None, None, None, None, None, None, None)
        return (None, None, None, None, None, None, None)

    cols = _table_columns(conn, table) or []

    bts_id_col = _pick_id_col(cols, ["BonusTypeStat_Id", "BonusTypeStatId", "BonusTypeStat"])
    event_col = _pick_id_col(cols, ["Event_Id", "EventId", "Event"])
    state_col = _pick_id_col(cols, ["State_Id", "StateId", "State"])
    equip_col = _pick_id_col(cols, ["EquipmentType_Id", "EquipmentTypeId", "EquipmentType"])

    low = {str(c).lower(): str(c) for c in cols}

    pair_col = None
    for cand in ("PairEquipment", "Pair_Equipment", "Pair", "IsPairEquipment"):
        if cand.lower() in low:
            pair_col = low[cand.lower()]
            break

    lost_control_col = None
    for cand in ("LostControl", "Lost_Control", "IsLostControl", "LostControl_Id", "LostControlId"):
        if cand.lower() in low:
            lost_control_col = low[cand.lower()]
            break

    if not bts_id_col:
        _BTS_COND_META_CACHE[k] = (None, None, None, None, None, None, None)
        return (None, None, None, None, None, None, None)

    _BTS_COND_META_CACHE[k] = (
        table,
        bts_id_col,
        event_col,
        state_col,
        equip_col,
        pair_col,
        lost_control_col,
    )
    return (
        table,
        bts_id_col,
        event_col,
        state_col,
        equip_col,
        pair_col,
        lost_control_col,
    )

def _load_bts_conditions_map(
        conn,
        bts_ids: list[int],
) -> dict[int, list[tuple[int | None, int | None, int | None, int, int | None]]]:
    """
    returns:
      {
        BonusTypeStat_Id: [
          (
            Event_Id | None,
            State_Id | None,
            EquipmentType_Id | None,
            PairEquipment,
            LostControl | None,
          ),
          ...
        ]
      }

    OR-логика по строкам:
      - каждая строка = набор ограничений;
      - внутри строки условия работают через AND;
      - строки между собой работают через OR.
    """
    if not conn or not bts_ids:
        return {}

    (
        table,
        bts_id_col,
        event_col,
        state_col,
        equip_col,
        pair_col,
        lost_control_col,
    ) = _get_bts_condition_meta(conn)

    if not table or not bts_id_col:
        return {}

    # Если в таблице нет ни одной колонки условий — не фильтруем.
    if not event_col and not state_col and not equip_col and not pair_col and not lost_control_col:
        return {}

    ids = [int(x) for x in bts_ids if int(x or 0) > 0]
    if not ids:
        return {}

    q = ",".join("?" for _ in ids)

    sel = [_qident(bts_id_col)]

    if event_col:
        sel.append(_qident(event_col))
    else:
        sel.append("NULL")

    if state_col:
        sel.append(_qident(state_col))
    else:
        sel.append("NULL")

    if equip_col:
        sel.append(_qident(equip_col))
    else:
        sel.append("NULL")

    if pair_col:
        sel.append(_qident(pair_col))
    else:
        sel.append("0")

    if lost_control_col:
        sel.append(_qident(lost_control_col))
    else:
        sel.append("NULL")

    sql = (
        f"SELECT {', '.join(sel)} "
        f"FROM {_qident(table)} "
        f"WHERE {_qident(bts_id_col)} IN ({q}) "
        f"ORDER BY Id ASC"
    )

    try:
        rows = conn.execute(sql, tuple(ids)).fetchall()
    except Exception:
        return {}

    out: dict[int, list[tuple[int | None, int | None, int | None, int, int | None]]] = {}

    for r in rows or []:
        if hasattr(r, "keys"):
            bts_id = r[bts_id_col]
            ev = r[event_col] if event_col else None
            st = r[state_col] if state_col else None
            et = r[equip_col] if equip_col else None
            pe = r[pair_col] if pair_col else 0
            lc = r[lost_control_col] if lost_control_col else None
        else:
            # порядок select: bts_id, ev, st, et, pe, lc
            bts_id = r[0] if len(r) > 0 else None
            ev = r[1] if len(r) > 1 else None
            st = r[2] if len(r) > 2 else None
            et = r[3] if len(r) > 3 else None
            pe = r[4] if len(r) > 4 else 0
            lc = r[5] if len(r) > 5 else None

        try:
            bts_id_i = int(bts_id or 0)
        except Exception:
            continue

        if bts_id_i <= 0:
            continue

        ev_i = None
        st_i = None
        et_i = None
        pe_i = 0
        lc_i = None

        if ev is not None:
            try:
                ev_i = int(ev)
            except Exception:
                ev_i = None

        if st is not None:
            try:
                st_i = int(st)
            except Exception:
                st_i = None

        if et is not None:
            try:
                et_i = int(et)
                if et_i <= 0:
                    et_i = None
            except Exception:
                et_i = None

        try:
            pe_i = int(pe or 0)
        except Exception:
            pe_i = 0

        if lc is not None:
            try:
                lc_i = int(lc or 0)
            except Exception:
                lc_i = None

        out.setdefault(int(bts_id_i), []).append((ev_i, st_i, et_i, pe_i, lc_i))

    return out

def _bts_conditions_allow(
        conds: list[
            tuple[int | None, int | None]
            | tuple[int | None, int | None, int | None, int]
            | tuple[int | None, int | None, int | None, int, int | None]
        ] | None
) -> bool:
    """
    OR-логика по строкам условий:
      - если условий нет -> True;
      - если есть хоть одна строка, где все ограничения совпали -> True;
      - иначе False.

    LostControl:
      - LostControl NULL или 0 -> не ограничивает бонус;
      - LostControl = 1 -> бонус работает только если выбран любой статус контроля,
        то есть player_lost_control_id > 0.
    """
    if not conds:
        return True

    cur_ev = get_active_event_id()
    cur_st = get_active_state_id()
    cur_lost_control = get_active_lost_control_id()

    equip_types = _ACTIVE_EQUIP_TYPE_IDS_SET if isinstance(_ACTIVE_EQUIP_TYPE_IDS_SET, set) else set()

    try:
        w_tid = int(_ACTIVE_WEAPON_EQUIP_TYPE_ID or 0)
    except Exception:
        w_tid = 0

    try:
        o_tid = int(_ACTIVE_OFFHAND_EQUIP_TYPE_ID or 0)
    except Exception:
        o_tid = 0

    for row in (conds or []):
        if not isinstance(row, (tuple, list)) or len(row) < 2:
            continue

        ev = row[0]
        st = row[1]
        et = row[2] if len(row) >= 3 else None
        pe = row[3] if len(row) >= 4 else 0
        lc = row[4] if len(row) >= 5 else None

        # Event
        if ev is not None and int(ev) != int(cur_ev):
            continue

        # State
        if st is not None and int(st) != int(cur_st):
            continue

        # LostControl
        try:
            lost_control_required = int(lc or 0) == 1
        except Exception:
            lost_control_required = False

        if lost_control_required and int(cur_lost_control or 0) <= 0:
            continue

        # EquipmentType
        try:
            etid = int(et) if et is not None else None
        except Exception:
            etid = None

        if etid is not None and etid > 0:
            try:
                pair = int(pe or 0) == 1
            except Exception:
                pair = False

            if pair:
                if int(w_tid) != int(etid) or int(o_tid) != int(etid):
                    continue
            else:
                if int(etid) not in equip_types:
                    continue

        return True

    return False

# ---------------------------------------------------------------------------
# BUFF DESCRIPTION VARIABLES
# Type=1 -> считается от текущего значения Stat.Id=10 (Атака)
# ---------------------------------------------------------------------------

def _load_buff_description_variable_rows(conn, buff_desc_id: int) -> list[dict]:
    """
    Пытается прочитать BuffDescriptionVariable:
      Index / Type / Value
    и возвращает список dict: {"Index": int, "Type": int, "Value": float}

    Делает это максимально "живуче" к разным схемам колонок.
    """
    if not conn or int(buff_desc_id or 0) <= 0:
        return []

    table = _first_existing_table(conn, [
        "BuffDescriptionVariable",
        "BuffDescriptionVariables",
        "BuffDescVariable",
        "BuffDescVariables",
    ])
    if not table:
        return []

    cols = _table_columns(conn, table)
    if not cols:
        return []

    idx_col = _pick_id_col(cols, ["Index", "`Index`", "VarIndex", "OrderIndex"])
    type_col = _pick_id_col(cols, ["Type", "Type_Id", "VarType", "VariableType"])
    val_col = _pick_id_col(cols, ["Value", "Amount", "Coef", "Multiplier"])

    # чем в таблице связываются строки с конкретным описанием
    owner_col = _pick_id_col(cols, [
        "BuffDescription_Id", "BuffDescriptionId",
        "Description_Id", "BuffDesc_Id",
        "Buff_Id", "BuffId",
    ])

    if not idx_col or not type_col:
        return []

    # Value может отсутствовать — тогда считаем его 0
    sel_cols = [_qident(idx_col), _qident(type_col)]
    if val_col:
        sel_cols.append(_qident(val_col))

    if not owner_col:
        # без owner_col мы не сможем отфильтровать конкретный buff_desc_id
        return []

    sql = (
        f"SELECT {', '.join(sel_cols)} "
        f"FROM {_qident(table)} "
        f"WHERE {_qident(owner_col)}=? "
        f"ORDER BY {_qident(idx_col)} ASC, rowid ASC"
    )

    try:
        rows = conn.execute(sql, (int(buff_desc_id),)).fetchall()
    except Exception:
        return []

    out: list[dict] = []
    for r in rows or []:
        if hasattr(r, "keys"):
            idx = _to_int(r[idx_col], 0)
            tp = _to_int(r[type_col], 0)
            vv = _to_float(r[val_col], 0.0) if val_col else 0.0
        else:
            idx = _to_int(r[0], 0)
            tp = _to_int(r[1], 0)
            vv = _to_float(r[2], 0.0) if val_col else 0.0

        out.append({"Index": int(idx), "Type": int(tp), "Value": float(vv)})

    return out

def compute_buff_description_variables(
    conn,
    buff_desc_id: int,
    *,
    current_stats: Mapping[int, float] | None = None,
) -> dict[int, float]:
    rows = _load_buff_description_variable_rows(conn, int(buff_desc_id or 0))
    if not rows:
        return {}

    # если current_stats не передали ИЛИ передали пустое — берём глобальный кэш
    if not current_stats:
        cur = get_global_current_stats()
    else:
        cur = _normalize_stats_mapping(current_stats)

    atk = float(cur.get(10, 0.0) or 0.0)

    out: dict[int, float] = {}
    for rr in rows:
        idx = int(rr.get("Index", 0))
        tp = int(rr.get("Type", 0))
        val = float(rr.get("Value", 0.0) or 0.0)

        if idx < 0:
            continue

        if tp == 1:
            # Новое правило:
            # Type=1 -> текущая Атака * Value
            out[idx] = float(atk) * float(val)
        else:
            # Type=0 -> просто Value
            out[idx] = float(val)

    return out

def _get_card_set_id(conn, card_id: int) -> int:
    if not conn or int(card_id or 0) <= 0:
        return 0

    key = (id(conn), int(card_id))
    if key in _CARD_SET_ID_CACHE:
        return int(_CARD_SET_ID_CACHE[key] or 0)

    set_id = 0
    try:
        row = conn.execute("SELECT Set_Id FROM Card WHERE Id=? LIMIT 1", (int(card_id),)).fetchone()
        if row:
            raw = row["Set_Id"] if hasattr(row, "keys") else row[0]
            set_id = _to_int(raw, 0)
    except Exception:
        set_id = 0

    _CARD_SET_ID_CACHE[key] = int(set_id or 0)
    return int(set_id or 0)

def _list_tables(conn) -> list[str]:
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        name = r[0] if not hasattr(r, "keys") else r["name"]
        if not name or str(name).startswith("sqlite_"):
            continue
        out.append(str(name))
    return out

def _guess_bonustype_stat_table(conn) -> str | None:
    # Ищем любую таблицу, где есть и BonusType и Stat и Multiply
    for t in _list_tables(conn):
        cols = _table_columns(conn, t)
        low = [c.lower() for c in cols]
        if any("bonustype" in c for c in low) and any("stat" in c for c in low) and any("multiply" in c for c in low):
            return t
    # Если без multiply — тоже ок, но хуже
    for t in _list_tables(conn):
        cols = _table_columns(conn, t)
        low = [c.lower() for c in cols]
        if any("bonustype" in c for c in low) and any("stat" in c for c in low):
            return t
    return None

def _collect_possible_ids(item: dict) -> list[int]:
    ids: list[int] = []
    for k, v in (item or {}).items():
        if not isinstance(k, str):
            continue
        lk = k.lower()
        if "id" not in lk and "template" not in lk and "proto" not in lk:
            continue
        try:
            iv = int(v)
        except Exception:
            continue
        if iv:
            ids.append(iv)
    # уникальные, сохраняя порядок
    seen = set()
    out = []
    for x in ids:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out

def _extract_inline_bonus_rows(item: dict) -> list[dict]:
    """
    Вытаскивает бонусы прямо из dict предмета:
      BonusType1 + Var1/Value1
      BonusType_Id2 + Var2/Value2
    """
    bt_by_i: dict[int, int] = {}
    v_by_i: dict[int, float] = {}

    for k, v in (item or {}).items():
        if not isinstance(k, str):
            continue

        m = _BT_COL_RE.match(k)
        if m:
            i = int(m.group(1))
            try:
                bt_by_i[i] = int(v or 0)
            except Exception:
                bt_by_i[i] = 0
            continue

        m2 = _VAR_COL_RE.match(k)
        if m2:
            i = int(m2.group(2))
            try:
                v_by_i[i] = float(v) if v not in (None, "") else 0.0
            except Exception:
                v_by_i[i] = 0.0

    out = []
    for i, bt in bt_by_i.items():
        if not bt:
            continue
        out.append({"BonusType_Id": int(bt), "vars": [float(v_by_i.get(i, 0.0))]})
    return out

# ---------------------------------------------------------------------------
# GLOBAL CURRENT CHARACTER STATS (shared between windows)
# ---------------------------------------------------------------------------

_GLOBAL_CURRENT_STATS: dict[int, float] = {}

class CurrentStatsBus(QObject):
    statsChanged = Signal(dict)  # emits: dict[int, float]

_GLOBAL_STATS_BUS = CurrentStatsBus()

def get_current_stats_bus() -> CurrentStatsBus:
    return _GLOBAL_STATS_BUS

def _normalize_stats_mapping(m) -> dict[int, float]:
    out: dict[int, float] = {}
    if not isinstance(m, dict):
        try:
            m = dict(m)  # Mapping -> dict
        except Exception:
            return out

    for k, v in (m or {}).items():
        try:
            ik = int(k)
        except Exception:
            continue
        try:
            fv = float(v)
        except Exception:
            try:
                s = str(v).strip().replace(",", ".")
                fv = float(s) if s else 0.0
            except Exception:
                fv = 0.0
        out[ik] = fv
    return out

def set_global_current_stats(stats, *, src: str = "") -> None:
    global _GLOBAL_CURRENT_STATS
    _GLOBAL_CURRENT_STATS = _normalize_stats_mapping(stats)

    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.setProperty("current_character_stats", dict(_GLOBAL_CURRENT_STATS))
            if src:
                app.setProperty("current_character_stats_src", str(src))
    except Exception:
        pass

    # NEW: notify all listeners (CardsWindow etc.)
    try:
        from PySide6.QtCore import QTimer
        payload = dict(_GLOBAL_CURRENT_STATS)
        QTimer.singleShot(0, lambda p=payload: get_current_stats_bus().statsChanged.emit(p))
    except Exception:
        try:
            get_current_stats_bus().statsChanged.emit(dict(_GLOBAL_CURRENT_STATS))
        except Exception:
            pass

def get_global_current_stats() -> dict[int, float]:
    try:
        if _GLOBAL_CURRENT_STATS:
            return dict(_GLOBAL_CURRENT_STATS)
    except Exception:
        pass

    # fallback: попытка забрать из QApplication property
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            v = app.property("current_character_stats")
            if isinstance(v, dict) and v:
                return _normalize_stats_mapping(v)
    except Exception:
        pass

    return {}

def get_global_stat(stat_id: int, default: float = 0.0) -> float:
    st = get_global_current_stats()
    try:
        return float(st.get(int(stat_id), default) or default)
    except Exception:
        return float(default)


# если IsMultiply=1 означает +X%: 5 -> 1.05
# если у тебя в БД проценты хранятся иначе (например 500 = 5.00%), поменяй делитель на 10000
MULTIPLY_DIV = 100.0

def _table_exists(conn, name: str) -> bool:
    try:
        r = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)
        ).fetchone()
        return bool(r)
    except Exception:
        return False

def _first_existing_table(conn, candidates: list[str]) -> str | None:
    for t in candidates:
        if _table_exists(conn, t):
            return t
    return None

def _table_columns(conn, table: str) -> list[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except Exception:
        return []
    cols = []
    for r in rows:
        # sqlite: (cid, name, type, notnull, dflt_value, pk)
        cols.append(r[1] if isinstance(r, (tuple, list)) else r["name"])
    return cols

def _pick_id_col(cols: list[str], candidates: list[str]) -> str | None:
    low = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in low:
            return low[cand.lower()]
    return None

def _extract_var_cols(cols: list[str]) -> list[str]:
    found = []
    for c in cols:
        m = _VAR_COL_RE.match(c)
        if m:
            found.append((int(m.group(2)), c))
    found.sort(key=lambda x: x[0])
    return [c for _, c in found]

def _fetch_bonus_rows(conn, table: str, id_col: str, id_val: int) -> list[dict]:
    """
    Возвращает список dict:
      { 'BonusType_Id': int, 'vars': [v1, v2, ...] }
    """
    cols = _table_columns(conn, table)
    if not cols:
        return []

    # BonusType_Id колонка может называться по-разному, пробуем варианты
    bt_col = _pick_id_col(cols, ["BonusType_Id", "BonusTypeId", "BonusType"])
    if not bt_col:
        return []

    var_cols = _extract_var_cols(cols)
    if not var_cols:
        # иногда бывает просто "Value"
        vcol = _pick_id_col(cols, ["Value", "Amount"])
        var_cols = [vcol] if vcol else []

    sel_cols = [bt_col] + [c for c in var_cols if c]
    sql = f"SELECT {', '.join(sel_cols)} FROM {table} WHERE {id_col}=?"
    try:
        rows = conn.execute(sql, (int(id_val),)).fetchall()
    except Exception:
        return []

    out = []
    for r in rows:
        # r может быть tuple или sqlite Row
        def _get(ix, name):
            if hasattr(r, "keys"):
                return r[name]
            return r[ix]

        bt = _get(0, bt_col)
        if bt is None:
            continue

        vars_ = []
        for i, c in enumerate(var_cols, start=1):
            v = _get(i, c) if c else 0
            try:
                v = float(v) if v is not None else 0.0
            except Exception:
                v = 0.0
            vars_.append(v)

        out.append({"BonusType_Id": int(bt), "vars": vars_})
    return out

class BonusTypeStatResolver:
    def __init__(self, conn):
        self.conn = conn
        self._bts_cache: dict[int, list[tuple[int, int]]] = {}  # bt -> [(Stat_Id, IsMultiply)]

        self.table = _first_existing_table(conn, ["BonusTypeStat", "BonusTypeStats", "BonusType_Stat"])
        if not self.table:
            self.table = _guess_bonustype_stat_table(conn)

        self.cols = _table_columns(conn, self.table) if self.table else []
        self.bt_col = _pick_id_col(self.cols, ["BonusType_Id", "BonusTypeId", "BonusType"])
        self.stat_col = _pick_id_col(self.cols, ["Stat_Id", "StatId", "Stat"])
        self.mul_col = _pick_id_col(self.cols, ["IsMultiply", "Multiply", "IsMul"])

    def map_bonus_type(self, bonus_type_id: int) -> list[tuple[int, int]]:
        if bonus_type_id in self._bts_cache:
            return self._bts_cache[bonus_type_id]

        if not self.conn or not self.table or not self.bt_col or not self.stat_col:
            self._bts_cache[bonus_type_id] = []
            return []

        mul_col = self.mul_col or "0"

        sql = f"SELECT {self.stat_col}, {mul_col} FROM {self.table} WHERE {self.bt_col}=?"
        try:
            rows = self.conn.execute(sql, (int(bonus_type_id),)).fetchall()
        except Exception:
            rows = []

        mapped: list[tuple[int, int]] = []
        for r in rows:
            if hasattr(r, "keys"):
                sid = r[0]
                mul = r[1] if self.mul_col else 0
            else:
                sid = r[0]
                mul = r[1] if self.mul_col else 0
            try:
                mapped.append((int(sid or 0), int(mul or 0)))
            except Exception:
                continue

        self._bts_cache[bonus_type_id] = mapped
        return mapped

_INLINE_BONUS_TABLE_CACHE: dict[int, tuple[str, str, list[str]]] = {}

def _qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'

def _get_inline_bonus_table(conn) -> tuple[str, str, list[str]] | None:
    """
    Находит таблицу, где в одной строке предмета лежат BonusType1..N и Var/Value1..N
    и кэширует результат.
    """
    if not conn:
        return None

    key = id(conn)
    if key in _INLINE_BONUS_TABLE_CACHE:
        return _INLINE_BONUS_TABLE_CACHE[key]

    best = None
    best_score = 0

    for t in _list_tables(conn):
        cols = _table_columns(conn, t)
        if not cols:
            continue

        # нужен какой-то Id
        id_col = _pick_id_col(cols, ["Id", "Equip_Id", "Equipment_Id", "Item_Id", "TemplateId", "Template_Id"])
        if not id_col:
            continue

        bt_cnt = sum(1 for c in cols if _BT_COL_RE.match(c))
        var_cnt = sum(1 for c in cols if _VAR_COL_RE.match(c))

        # если нет пар BonusType/Var(Value) — не наша таблица
        if bt_cnt <= 0 or var_cnt <= 0:
            continue

        low = [c.lower() for c in cols]
        score = bt_cnt * 3 + var_cnt * 2
        if "name" in low:
            score += 2
        if any("def" in c for c in low) or any("armor" in c for c in low):
            score += 1

        if score > best_score:
            best_score = score
            best = (t, id_col, cols)

    if best:
        _INLINE_BONUS_TABLE_CACHE[key] = best
    return best

def _fetch_row_dict(conn, table: str, id_col: str, id_val: int, cols: list[str]) -> dict | None:
    """
    SELECT *-подобная загрузка строки в dict.
    """
    if not conn or not table or not id_col:
        return None
    try:
        sel = ", ".join(_qident(c) for c in cols)
        sql = f"SELECT {sel} FROM {_qident(table)} WHERE {_qident(id_col)}=? LIMIT 1"
        row = conn.execute(sql, (int(id_val),)).fetchone()
        if not row:
            return None

        out = {}
        if hasattr(row, "keys"):
            for c in cols:
                out[c] = row[c]
        else:
            for i, c in enumerate(cols):
                out[c] = row[i]
        return out
    except Exception:
        return None

def _resolve_card_id_from_entry(c) -> int:
    if c is None:
        return 0

    # int / str
    if isinstance(c, (int, str)):
        return _to_int(c, 0)

    # tuple/list (берём первый элемент)
    if isinstance(c, (tuple, list)):
        return _to_int(c[0], 0) if c else 0

    # dict-like
    if isinstance(c, dict):
        for k in ("Id", "id", "Card_Id", "CardId", "card_id"):
            if k in c and c[k] not in (None, ""):
                return _to_int(c[k], 0)
        return 0

    # sqlite Row / Mapping-подобное
    if hasattr(c, "keys"):
        for k in ("Id", "id", "Card_Id", "CardId", "card_id"):
            try:
                return _to_int(c[k], 0)
            except Exception:
                pass
        try:
            return _to_int(c[0], 0)
        except Exception:
            return 0

    return 0

def _to_int(x, default=0) -> int:
    try:
        return int(x)
    except Exception:
        return default

def _to_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

_FORMULA_OP_CACHE: dict[tuple[int, int], str] = {}  # (id(conn), formula_id) -> op
_BONUSTYPE_IS_SINGLE_CACHE: dict[tuple[int, int], bool] = {}


def _bonus_type_is_single(conn, bonus_type_id: int) -> bool:
    try:
        bt_id = int(bonus_type_id or 0)
    except Exception:
        bt_id = 0

    if not conn or bt_id <= 0:
        return False

    key = (id(conn), int(bt_id))
    if key in _BONUSTYPE_IS_SINGLE_CACHE:
        return bool(_BONUSTYPE_IS_SINGLE_CACHE[key])

    is_single = False
    try:
        row = conn.execute(
            'SELECT IsSingle FROM "BonusType" WHERE Id=? LIMIT 1',
            (int(bt_id),),
        ).fetchone()
        if row:
            raw = row["IsSingle"] if hasattr(row, "keys") else row[0]
            is_single = bool(int(raw or 0))
    except Exception:
        is_single = False

    _BONUSTYPE_IS_SINGLE_CACHE[key] = bool(is_single)
    return bool(is_single)


def _take_bonus_type_once(conn, seen: Optional[set[int]], bonus_type_id: int) -> bool:
    """
    True  -> этот BonusType можно применять
    False -> его уже применяли раньше в текущем расчёте
    """
    try:
        bt_id = int(bonus_type_id or 0)
    except Exception:
        bt_id = 0

    if bt_id <= 0:
        return False

    if seen is None:
        return True

    if not _bonus_type_is_single(conn, int(bt_id)):
        return True

    if int(bt_id) in seen:
        return False

    seen.add(int(bt_id))
    return True


def _formula_op(conn, formula_id: int) -> str:
    """
    Пытаемся понять оператор из Formula (если таблица есть),
    иначе возвращаем ">".
    """
    if not conn or int(formula_id or 0) <= 0:
        return ">"

    key = (id(conn), int(formula_id))
    if key in _FORMULA_OP_CACHE:
        return _FORMULA_OP_CACHE[key]

    op = ">"
    try:
        if not _table_exists(conn, "Formula"):
            _FORMULA_OP_CACHE[key] = op
            return op

        cols = _table_columns(conn, "Formula")
        if not cols:
            _FORMULA_OP_CACHE[key] = op
            return op

        # берём любые текстовые поля, где потенциально хранится выражение
        pref = ["Expression", "Expr", "Text", "Formula", "Value", "Code", "Name", "Description"]
        pick = None
        low = {c.lower(): c for c in cols}
        for p in pref:
            if p.lower() in low:
                pick = low[p.lower()]
                break
        if pick is None:
            pick = cols[0]

        row = conn.execute(f'SELECT "{pick}" FROM "Formula" WHERE Id=? LIMIT 1', (int(formula_id),)).fetchone()
        s = ""
        if row:
            raw = row[0] if not hasattr(row, "keys") else row[pick]
            s = str(raw or "").strip()

        # ищем оператор (важно: >= раньше > и т.п.)
        if ">=" in s:
            op = ">="
        elif "<=" in s:
            op = "<="
        elif "!=" in s:
            op = "!="
        elif "==" in s:
            op = "=="
        elif ">" in s:
            op = ">"
        elif "<" in s:
            op = "<"
        elif "=" in s:
            op = "=="
    except Exception:
        op = ">"

    _FORMULA_OP_CACHE[key] = op
    return op

def _cmp_by_op(op: str, left: float, right: float) -> bool:
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    if op == "<":
        return left < right
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    # default
    return left > right

def _resolve_upgrade_level(item: Dict[str, Any]) -> int:
    # у тебя уже используются похожие поля в других местах
    for k in ("__forge_level", "ForgeLevel", "UpgradeLevel", "Plus", "Refine", "EnhanceLevel"):
        if k in item and item[k] is not None:
            return _to_int(item[k], 0)
    return 0

def _resolve_type_id(item: Dict[str, Any]) -> int:
    return _to_int(item.get("Type_Id") or item.get("TypeId"), 0)

def _get_is_single_hand_weapon(conn, type_id: int) -> Optional[bool]:
    """
    True  -> одноручное
    False -> двуручное
    None  -> неизвестно/не оружие/нет данных
    """
    if not conn or int(type_id or 0) <= 0:
        return None

    try:
        row = conn.execute(
            "SELECT IsSingleHandWeapon FROM EquipmentType WHERE Id=? LIMIT 1",
            (int(type_id),)
        ).fetchone()
    except Exception:
        row = None

    if not row:
        return None

    val = row["IsSingleHandWeapon"] if hasattr(row, "keys") else row[0]

    # В твоей схеме часто бывает: у двуручек IsSingleHandWeapon = NULL.
    # Если тип вообще "оружейный" — считаем NULL как двуручное (False).
    if val is None:
        try:
            is_weapon = _is_weapon_type_by_equipmenttype(conn, int(type_id))
        except Exception:
            is_weapon = None

        if is_weapon is True:
            return False
        return None

    try:
        return bool(_to_int(val, 0))
    except Exception:
        return None

def _load_bonustype_stat_map(conn, bonus_type_id: int) -> List[Tuple[int, int, int]]:
    """
    returns list of (VarIndex, Stat_Id, IsMultiply)
    с учётом BonusTypeStatCondition (Event_Id / State_Id) по BonusTypeStat.Id
    """
    if not conn or bonus_type_id <= 0:
        return []

    try:
        rows = conn.execute(
            "SELECT Id, VarIndex, Stat_Id, IsMultiply FROM BonusTypeStat WHERE BonusType_Id=?",
            (int(bonus_type_id),)
        ).fetchall()
    except Exception:
        return []

    if not rows:
        return []

    # соберём условия пачкой
    bts_ids: list[int] = []
    for r in rows:
        try:
            bts_id = _to_int(r["Id"] if hasattr(r, "keys") else r[0], 0)
        except Exception:
            bts_id = 0
        if bts_id > 0:
            bts_ids.append(int(bts_id))

    cond_map = _load_bts_conditions_map(conn, bts_ids)

    out: List[Tuple[int, int, int]] = []
    for r in rows or []:
        if hasattr(r, "keys"):
            bts_id = _to_int(r["Id"], 0)
            vi = _to_int(r["VarIndex"], 0)
            sid = _to_int(r["Stat_Id"], 0)
            im = _to_int(r["IsMultiply"], 0)
        else:
            bts_id = _to_int(r[0], 0)
            vi = _to_int(r[1], 0)
            sid = _to_int(r[2], 0)
            im = _to_int(r[3], 0)

        if sid <= 0:
            continue

        if not _bts_conditions_allow(cond_map.get(int(bts_id), None)):
            continue

        out.append((int(vi), int(sid), int(im)))

    return out

def _load_bonustype_variables(conn, bonus_type_id: int) -> Dict[int, Dict[str, Any]]:
    """
    BonusTypeVariable:
      - MultiplicityStat_Id: какой стат проверяем
      - MultiplicityValue: во сколько раз умножаем base (Value[Index=0])
      - MulFormula_Id: какой оператор сравнения (если есть)
    returns {Index: {"MultiplicityStat_Id": int|None, "MultiplicityValue": float|None, "MulFormula_Id": int|None}}
    """
    if not conn or bonus_type_id <= 0:
        return {}
    try:
        rows = conn.execute(
            """SELECT "Index", MultiplicityStat_Id, MultiplicityValue, MulFormula_Id
               FROM BonusTypeVariable
               WHERE BonusType_Id=?
               ORDER BY "Index" ASC, Id ASC""",
            (int(bonus_type_id),),
        ).fetchall()
        out: Dict[int, Dict[str, Any]] = {}
        for r in rows or []:
            idx = _to_int(r["Index"] if hasattr(r, "keys") else r[0], 0)
            msid = r["MultiplicityStat_Id"] if hasattr(r, "keys") else r[1]
            mval = r["MultiplicityValue"] if hasattr(r, "keys") else r[2]
            fid  = r["MulFormula_Id"] if hasattr(r, "keys") else r[3]
            out[idx] = {
                "MultiplicityStat_Id": _to_int(msid, 0) or None,
                "MultiplicityValue": _to_float(mval, 0.0) or None,
                "MulFormula_Id": _to_int(fid, 0) or None,
            }
        return out
    except Exception:
        return {}

def _load_card_bonus_rows(conn, card_id: int) -> List[Dict[str, Any]]:
    if not conn or card_id <= 0:
        return []
    try:
        rows = conn.execute(
            """SELECT Id, Type_Id, OrderIndex,
                      UpgConditionVariable, UpgLevelStepVariable,
                      RequiredCard_Id, NegateCard_Id,
                      MultiplyEffectCard_Id, RequiredSet_Id, RequiredSetSize
               FROM CardBonus
               WHERE Card_Id=?
               ORDER BY OrderIndex ASC, Id ASC""",
            (int(card_id),)
        ).fetchall()
        out = []
        for r in rows or []:
            out.append({
                "CBId": _to_int(r["Id"] if hasattr(r, "keys") else r[0], 0),
                "Type_Id": _to_int(r["Type_Id"] if hasattr(r, "keys") else r[1], 0),
                "OrderIndex": _to_int(r["OrderIndex"] if hasattr(r, "keys") else r[2], 0),
                "UpgConditionVariable": (r["UpgConditionVariable"] if hasattr(r, "keys") else r[3]),
                "UpgLevelStepVariable": (r["UpgLevelStepVariable"] if hasattr(r, "keys") else r[4]),
                "RequiredCard_Id": _to_int(r["RequiredCard_Id"] if hasattr(r, "keys") else r[5], 0),
                "NegateCard_Id": _to_int(r["NegateCard_Id"] if hasattr(r, "keys") else r[6], 0),
                "MultiplyEffectCard_Id": _to_int(r["MultiplyEffectCard_Id"] if hasattr(r, "keys") else r[7], 0),
                "RequiredSet_Id": _to_int(r["RequiredSet_Id"] if hasattr(r, "keys") else r[8], 0),
                "RequiredSetSize": _to_int(r["RequiredSetSize"] if hasattr(r, "keys") else r[9], 0),
            })
        return out
    except Exception:
        return []

def _load_card_bonus_vars_with_conditions(
    conn,
    cbid: int,
    *,
    item_type_id: int,
    is_single_hand: Optional[bool],
) -> Dict[int, float]:
    """
    Собирает var_map {Index: Value} для CardBonus_Id,
    учитывая CardBonusVariableCondition (EquipmentType_Id / IsSingleHandWeapon).

    Фикс:
      - НЕ суммируем альтернативы для одного Index.
      - Выбираем одну "лучшую" переменную по специфичности условий.
        spec = (есть EquipmentType_Id?) + (есть IsSingleHandWeapon?)
      - Если несколько кандидатов с одинаковым spec:
          * если Value одинаковые -> берём одно
          * иначе -> берём значение кандидата с меньшим Id (стабильно, без удвоений)
    """
    if not conn or int(cbid or 0) <= 0:
        return {}

    try:
        vrows = conn.execute(
            """SELECT Id, "Index", Value
               FROM CardBonusVariable
               WHERE CardBonus_Id=?
               ORDER BY "Index" ASC, Id ASC""",
            (int(cbid),)
        ).fetchall()
    except Exception:
        return {}

    if not vrows:
        return {}

    var_ids = [_to_int(r["Id"] if hasattr(r, "keys") else r[0], 0) for r in (vrows or [])]
    var_ids = [int(x) for x in var_ids if int(x or 0) > 0]

    # vid -> [(EquipmentType_Id|None, IsSingleHandWeapon|None), ...]
    cond_map: Dict[int, List[Tuple[Optional[int], Optional[int]]]] = {}

    if var_ids:
        q = ",".join("?" for _ in var_ids)
        try:
            crows = conn.execute(
                f"""SELECT CardBonusVariable_Id, EquipmentType_Id, IsSingleHandWeapon
                    FROM CardBonusVariableCondition
                    WHERE CardBonusVariable_Id IN ({q})
                    ORDER BY Id ASC""",
                tuple(int(x) for x in var_ids)
            ).fetchall()

            for cr in crows or []:
                vid = _to_int(cr["CardBonusVariable_Id"] if hasattr(cr, "keys") else cr[0], 0)
                et = cr["EquipmentType_Id"] if hasattr(cr, "keys") else cr[1]
                sh = cr["IsSingleHandWeapon"] if hasattr(cr, "keys") else cr[2]

                et_i = _to_int(et, 0) or None
                sh_i = _to_int(sh, -1)
                sh_i = None if sh_i < 0 else sh_i

                if vid > 0:
                    cond_map.setdefault(int(vid), []).append((et_i, sh_i))
        except Exception:
            pass

    def _row_matches(et_i: Optional[int], sh_i: Optional[int]) -> bool:
        # EquipmentType_Id задан -> должен быть известен item_type_id и совпасть
        if et_i is not None:
            if int(item_type_id or 0) <= 0:
                return False
            if int(et_i) != int(item_type_id):
                return False

        # IsSingleHandWeapon задан -> is_single_hand обязан быть известен и совпасть
        if sh_i is not None:
            if is_single_hand is None:
                return False
            if int(bool(is_single_hand)) != int(sh_i):
                return False

        return True

    def _best_spec_for_var(conds: List[Tuple[Optional[int], Optional[int]]]) -> Optional[int]:
        """
        Возвращает spec лучшей совпавшей строки условия для переменной.
        0  -> условий нет (общая переменная)
        None -> ни одна строка условий не совпала
        """
        if not conds:
            return 0

        best = None
        for et_i, sh_i in conds:
            if not _row_matches(et_i, sh_i):
                continue
            spec = (1 if et_i is not None else 0) + (1 if sh_i is not None else 0)
            if best is None or spec > best:
                best = spec
        return best

    # idx -> список кандидатов (spec, vid, val)
    by_idx: Dict[int, List[Tuple[int, int, float]]] = {}

    for vr in vrows or []:
        vid = _to_int(vr["Id"] if hasattr(vr, "keys") else vr[0], 0)
        idx = _to_int(vr["Index"] if hasattr(vr, "keys") else vr[1], 0)
        val = _to_float(vr["Value"] if hasattr(vr, "keys") else vr[2], 0.0)

        if vid <= 0:
            continue

        spec = _best_spec_for_var(cond_map.get(int(vid), []))
        if spec is None:
            continue

        by_idx.setdefault(int(idx), []).append((int(spec), int(vid), float(val)))

    if not by_idx:
        return {}

    out: Dict[int, float] = {}

    for idx, cands in by_idx.items():
        if not cands:
            continue

        max_spec = max(s for (s, _vid, _v) in cands)
        best = [t for t in cands if t[0] == max_spec]

        if len(best) == 1:
            out[int(idx)] = float(best[0][2])
            continue

        # несколько кандидатов одинаковой специфичности
        vals = [float(t[2]) for t in best]
        v0 = vals[0]
        all_same = all(abs(v - v0) <= 1e-9 for v in vals)

        if all_same:
            out[int(idx)] = float(v0)
        else:
            # стабильно берём по меньшему vid (чтобы не было "12+12")
            best.sort(key=lambda t: int(t[1]))
            out[int(idx)] = float(best[0][2])

    return out

def compute_cards_bonus_stats_for_item(
    conn,
    item: Dict[str, Any],
    *,
    current_stats: Optional[Dict[int, float]] = None,
    equipped_card_ids: Optional[Iterable[int]] = None,
    debug: bool = False,
    single_bonus_seen: Optional[set[int]] = None,
) -> tuple[Dict[int, float], Dict[int, float]]:
    """
    Возвращает (add_dict, mul_percent_dict) от карт, вставленных в item["_cards"].

    Условия CardBonus:
      - RequiredCard_Id: бонус применяется только если указанная карта тоже экипирована
      - RequiredSetSize + RequiredSet_Id:
            бонус применяется только если на персонаже есть >= RequiredSetSize карт,
            у которых Card.Set_Id == RequiredSet_Id
      - NegateCard_Id:
            если карт NegateCard_Id надето 1 -> бонус = 0 (пропускаем)
            если карт NegateCard_Id надето 2+ -> берём модуль всех значений бонуса
      - MultiplyEffectCard_Id:
            если карт MultiplyEffectCard_Id надето 2+ -> множитель = 2, иначе 1

    ВАЖНО:
    - VarIndex=0: обычная прибавка (берём var_map[0], если нет — fallback на first_val)
    - VarIndex=2: “за каждые X статов” — считается ТОЛЬКО если передан current_stats
    - VarIndex=3: “за каждый уровень улучшения” — считается ТОЛЬКО если в CardBonus есть thr/step
    """
    if not conn or not item:
        return {}, {}

    def _norm_equipped(raw: Optional[Iterable[int]]) -> tuple[list[int], set[int], dict[int, int]]:
        if raw is None:
            raw = item.get("_equipped_card_ids", None)

        ids_list: list[int] = []
        if isinstance(raw, (list, tuple)):
            for x in raw:
                iv = _to_int(x, 0)
                if iv > 0:
                    ids_list.append(iv)
        elif isinstance(raw, (set, frozenset)):
            for x in raw:
                iv = _to_int(x, 0)
                if iv > 0:
                    ids_list.append(iv)
        else:
            ids_list = []

        ids_set = set(ids_list)
        counts: dict[int, int] = {}
        for cid in ids_list:
            counts[int(cid)] = int(counts.get(int(cid), 0)) + 1
        return ids_list, ids_set, counts

    equipped_list, equipped_set, equipped_counts = _norm_equipped(equipped_card_ids)

    # --- RequiredSetSize: считаем по Set_Id с учётом дублей ---
    set_counts: Dict[int, int] | None = None

    def _ensure_set_counts() -> Dict[int, int]:
        nonlocal set_counts
        if set_counts is not None:
            return set_counts
        sc: Dict[int, int] = {}
        for cid in equipped_list:
            sid = _get_card_set_id(conn, int(cid))
            if sid > 0:
                sc[int(sid)] = int(sc.get(int(sid), 0)) + 1
        set_counts = sc
        return set_counts

    cards = item.get("_cards") or item.get("Cards") or item.get("cards") or []
    if isinstance(cards, dict):
        cards = list(cards.values())
    if not isinstance(cards, list) or not cards:
        try:
            item.pop("_card_mul_groups_by_stat", None)
        except Exception:
            pass
        return {}, {}

    item_type_id = _resolve_type_id(item)
    is_single_hand = _get_is_single_hand_weapon(conn, item_type_id)
    upg_level = _resolve_upgrade_level(item)

    add_out: Dict[int, float] = {}
    mul_out: Dict[int, float] = {}
    accepted_bonus_type_ids: set[int] = set()

    # {Stat_Id: {group_key: percent_sum}}
    # Для stat_id=10 group_key = Card_Id (суммируем одинаковые карты, разные — потом перемножим)
    mul_groups: Dict[int, Dict[int, float]] = {}

    slot_s = str(
        item.get("_slot")
        or item.get("Slot")
        or item.get("slot")
        or item.get("SlotKey")
        or item.get("slot_key")
        or ""
    ).strip().lower()

    # ---- КОСТЫЛЬ: определяем "двуручку в weapon" максимально надёжно ----
    is_weapon_slot = ("weapon" in slot_s) and ("weapon2" not in slot_s) and ("hand2" not in slot_s)
    is_twohand_weapon = False
    if is_weapon_slot:
        raw_1h = item.get("IsSingleHandWeapon", None)
        if raw_1h is not None:
            try:
                is_twohand_weapon = (int(raw_1h) == 0)
            except Exception:
                is_twohand_weapon = False
        else:
            if is_single_hand is False:
                is_twohand_weapon = True
            elif is_single_hand is None:
                try:
                    if item_type_id > 0 and _is_weapon_type_by_equipmenttype(conn, int(item_type_id)):
                        is_twohand_weapon = True
                except Exception:
                    is_twohand_weapon = False

    def _eval_conditions(br: Dict[str, Any]) -> tuple[bool, bool, int]:
        """
        returns (ok, apply_abs, effect_mult)
        """
        req = _to_int(br.get("RequiredCard_Id"), 0)
        neg = _to_int(br.get("NegateCard_Id"), 0)
        mul_card = _to_int(br.get("MultiplyEffectCard_Id"), 0)
        req_set_id = _to_int(br.get("RequiredSet_Id"), 0)
        req_set_size = _to_int(br.get("RequiredSetSize"), 0)

        # RequiredCard
        if req > 0 and req not in equipped_set:
            return (False, False, 1)

        # RequiredSet
        if req_set_size > 0:
            if req_set_id <= 0:
                return (False, False, 1)

            have = int(_ensure_set_counts().get(int(req_set_id), 0))
            if have < int(req_set_size):
                return (False, False, 1)

        # MultiplyEffectCard_Id (Воко)
        effect_mult = 1
        if mul_card > 0:
            cnt_mul = int(equipped_counts.get(int(mul_card), 0))
            effect_mult = 2 if cnt_mul >= 2 else 1

        # NegateCard_Id (П'атага)
        apply_abs = False
        if neg > 0:
            cnt_neg = int(equipped_counts.get(int(neg), 0))
            if cnt_neg == 1:
                return (False, False, 1)
            if cnt_neg >= 2:
                apply_abs = True

        return (True, apply_abs, int(effect_mult))

    for c in cards:
        card_id = _resolve_card_id_from_entry(c)
        if card_id <= 0:
            continue

        bonus_rows = _load_card_bonus_rows(conn, card_id)
        if not bonus_rows:
            continue

        for br in bonus_rows:
            cbid = br["CBId"]
            btid = br["Type_Id"]
            if cbid <= 0 or btid <= 0:
                continue

            if not _take_bonus_type_once(conn, single_bonus_seen, int(btid)):
                continue

            ok, apply_abs, effect_mult = _eval_conditions(br)
            if not ok:
                continue

            accepted_bonus_type_ids.add(int(btid))

            bts = _load_bonustype_stat_map(conn, btid)  # (VarIndex, Stat_Id, IsMultiply)
            if not bts:
                continue

            var_map = _load_card_bonus_vars_with_conditions(
                conn,
                cbid,
                item_type_id=item_type_id,
                is_single_hand=is_single_hand,
            )

            # first_val: первое ненулевое значение (fallback только для VarIndex=0)
            first_val = 0.0
            for _k in sorted(var_map.keys()):
                try:
                    vv = float(var_map[_k])
                except Exception:
                    vv = 0.0
                if abs(vv) > 1e-12:
                    first_val = vv
                    break

            # --- VarIndex=3: “за каждый уровень улучшения предмета”
            thr_raw = br.get("UpgConditionVariable")
            step_raw = br.get("UpgLevelStepVariable")

            if thr_raw is not None or step_raw is not None:
                thr = _to_int(thr_raw, 0)
                step = max(1, _to_int(step_raw, 1))

                base_per = var_map.get(0, None)
                if base_per is None and var_map:
                    base_per = first_val

                if base_per is not None:
                    n = max(0, int(upg_level) - int(thr))
                    n = n // int(step) if step > 1 else n
                    var_map[3] = float(base_per) * float(n)

            # --- VarIndex=2 (если current_stats передали)
            if current_stats is not None:
                btv = _load_bonustype_variables(conn, btid)
                if btv:
                    base = float(var_map.get(0, 0.0))
                    thr = var_map.get(1, None)  # CardBonusVariable.Index=1 (порог/делитель)

                    has_var0_any = any(int(vi) == 0 for (vi, _sid, _im) in bts)

                    for vidx, meta in btv.items():
                        msid = meta.get("MultiplicityStat_Id")
                        if not msid:
                            continue

                        src_val = float(current_stats.get(int(msid), 0.0) or 0.0)

                        mval = meta.get("MultiplicityValue")
                        fid = meta.get("MulFormula_Id")

                        # РЕЖИМ A: условный множитель
                        if mval is not None and thr is not None:
                            op = _formula_op(conn, int(fid or 0))
                            ok2 = _cmp_by_op(op, src_val, float(thr))

                            if not ok2:
                                var_map[int(vidx)] = 0.0
                                continue

                            mult = float(mval)
                            if abs(mult) <= 1e-12:
                                var_map[int(vidx)] = 0.0
                                continue

                            if has_var0_any:
                                delta = base * (mult - 1.0)
                                var_map[int(vidx)] = float(delta) if abs(delta) > 1e-12 else 0.0
                            else:
                                var_map[int(vidx)] = float(base * mult)
                            continue

                        # РЕЖИМ B: "за каждые X"
                        if thr is None:
                            continue
                        div_eff = float(thr)
                        if abs(div_eff) <= 1e-12:
                            continue

                        cnt = int(math.floor(src_val / div_eff))
                        var_map[int(vidx)] = float(base) * float(cnt) if cnt > 0 else 0.0

            # --- применение BonusTypeStat ---
            for var_idx, stat_id, is_mul in bts:
                var_idx = int(var_idx)
                stat_id = int(stat_id)

                if var_idx in var_map:
                    v = float(var_map.get(var_idx, 0.0))
                else:
                    if var_idx == 0:
                        v = float(first_val)
                    else:
                        continue

                if abs(v) <= 1e-12:
                    continue

                if apply_abs:
                    v = abs(float(v))

                if effect_mult != 1:
                    v = float(v) * float(effect_mult)

                # ---- КОСТЫЛЬ: одноручка -> 61..66 режем пополам ----
                if bool(is_single_hand) and int(is_mul) != 1 and int(stat_id) in (61, 62, 63, 64, 65, 66, 68, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47):
                    v = float(v) * 0.5

                # ---- КОСТЫЛЬ: двуручка -> элементные карты режем пополам ----
                if is_twohand_weapon and int(is_mul) != 1 and int(stat_id) in (25, 26, 27, 28, 29, 30):
                    v = float(v) * 0.5

                if int(is_mul) == 1:
                    if int(stat_id) == 10:
                        gg = mul_groups.setdefault(stat_id, {})
                        gg[int(card_id)] = float(gg.get(int(card_id), 0.0)) + float(v)
                    else:
                        mul_out[stat_id] = mul_out.get(stat_id, 0.0) + float(v)
                        gg = mul_groups.setdefault(stat_id, {})
                        gg[int(card_id)] = float(gg.get(int(card_id), 0.0)) + float(v)
                else:
                    add_out[stat_id] = add_out.get(stat_id, 0.0) + float(v)

        try:
            clean = {}
            for sid, by_card in (mul_groups or {}).items():
                by_card2 = {int(cid): float(p) for cid, p in (by_card or {}).items() if abs(float(p)) > 1e-12}
                if by_card2:
                    clean[int(sid)] = by_card2
            if clean:
                item["_card_mul_groups_by_stat"] = clean
            else:
                item.pop("_card_mul_groups_by_stat", None)
        except Exception:
            pass

    try:
        atk_groups = mul_groups.get(10) if isinstance(mul_groups, dict) else None
        if isinstance(atk_groups, dict) and atk_groups:
            factor = 1.0
            for _pct in (atk_groups or {}).values():
                try:
                    pp = float(_pct)
                except Exception:
                    pp = 0.0
                if abs(pp) <= 1e-12:
                    continue
                factor *= (1.0 + (pp / float(MULTIPLY_DIV)))
            equiv = (factor - 1.0) * float(MULTIPLY_DIV)
            if abs(equiv) > 1e-12:
                mul_out[10] = float(equiv)
            else:
                try:
                    mul_out.pop(10, None)
                except Exception:
                    pass
        else:
            try:
                mul_out.pop(10, None)
            except Exception:
                pass
    except Exception:
        pass

    try:
        if accepted_bonus_type_ids:
            item["_accepted_card_bonus_type_ids"] = set(int(x) for x in accepted_bonus_type_ids)
        else:
            item.pop("_accepted_card_bonus_type_ids", None)
    except Exception:
        pass

    return add_out, mul_out

def compute_cards_bonus_stats_varindex2_for_item(
    conn,
    item: Dict[str, Any],
    *,
    current_stats: Dict[int, float],
    equipped_card_ids: Optional[Iterable[int]] = None,
    debug: bool = False,
    allowed_bonus_type_ids: Optional[Iterable[int]] = None,
) -> tuple[Dict[int, float], Dict[int, float]]:
    """
    Корректирующий проход для бонусов карт, зависящих от текущих статов через BonusTypeVariable.

    ФИКС:
      - раньше бралась только первая строка BonusTypeVariable с MultiplicityStat_Id -> Index=3 игнорировался.
      - теперь обрабатываем все подходящие индексы (VarIndex), которые реально используются в BonusTypeStat.
      - если таких индексов несколько и они являются альтернативами (дают один и тот же набор целевых статов),
        выбираем один активный по максимальному current_stats[MultiplicityStat_Id] (чтобы не суммировать режимы).
    """
    if not conn or not item or not current_stats:
        return {}, {}

    def _norm_equipped(raw: Optional[Iterable[int]]) -> tuple[list[int], set[int], dict[int, int]]:
        if raw is None:
            raw = item.get("_equipped_card_ids", None)

        ids_list: list[int] = []
        if isinstance(raw, (list, tuple)):
            for x in raw:
                iv = _to_int(x, 0)
                if iv > 0:
                    ids_list.append(iv)
        elif isinstance(raw, (set, frozenset)):
            for x in raw:
                iv = _to_int(x, 0)
                if iv > 0:
                    ids_list.append(iv)

        ids_set = set(ids_list)
        counts: dict[int, int] = {}
        for cid in ids_list:
            counts[int(cid)] = int(counts.get(int(cid), 0)) + 1
        return ids_list, ids_set, counts

    equipped_list, equipped_set, equipped_counts = _norm_equipped(equipped_card_ids)

    # --- RequiredSetSize: считаем по Set_Id с учётом дублей ---
    set_counts: Dict[int, int] | None = None

    def _ensure_set_counts() -> Dict[int, int]:
        nonlocal set_counts
        if set_counts is not None:
            return set_counts
        sc: Dict[int, int] = {}
        for cid in equipped_list:
            sid = _get_card_set_id(conn, int(cid))
            if sid > 0:
                sc[int(sid)] = int(sc.get(int(sid), 0)) + 1
        set_counts = sc
        return set_counts

    cards = item.get("_cards") or item.get("Cards") or item.get("cards") or []
    if isinstance(cards, dict):
        cards = list(cards.values())
        item["_cards"] = cards
    if not isinstance(cards, list) or not cards:
        return {}, {}

    item_type_id = _resolve_type_id(item)
    is_single_hand = _get_is_single_hand_weapon(conn, item_type_id)

    add_out: Dict[int, float] = {}
    mul_out: Dict[int, float] = {}

    allowed_bt_ids: Optional[set[int]] = None
    if allowed_bonus_type_ids is not None:
        tmp: set[int] = set()
        for x in (allowed_bonus_type_ids or ()):
            try:
                iv = int(x)
            except Exception:
                continue
            if iv > 0:
                tmp.add(int(iv))
        allowed_bt_ids = tmp

    def _merge(dst: Dict[int, float], src: Dict[int, float]) -> None:
        for k, v in (src or {}).items():
            dst[int(k)] = float(dst.get(int(k), 0.0)) + float(v)

    def _eval_conditions(br: Dict[str, Any]) -> tuple[bool, bool, int]:
        """
        returns (ok, apply_abs, effect_mult)
        """
        req = _to_int(br.get("RequiredCard_Id"), 0)
        neg = _to_int(br.get("NegateCard_Id"), 0)
        mul_card = _to_int(br.get("MultiplyEffectCard_Id"), 0)
        req_set_id = _to_int(br.get("RequiredSet_Id"), 0)
        req_set_size = _to_int(br.get("RequiredSetSize"), 0)

        # RequiredCard
        if req > 0 and req not in equipped_set:
            return (False, False, 1)

        # RequiredSet
        if req_set_size > 0:
            if req_set_id <= 0:
                return (False, False, 1)
            have = int(_ensure_set_counts().get(int(req_set_id), 0))
            if have < int(req_set_size):
                return (False, False, 1)

        # MultiplyEffectCard_Id
        effect_mult = 1
        if mul_card > 0:
            cnt_mul = int(equipped_counts.get(int(mul_card), 0))
            effect_mult = 2 if cnt_mul >= 2 else 1

        # NegateCard_Id
        apply_abs = False
        if neg > 0:
            cnt_neg = int(equipped_counts.get(int(neg), 0))
            if cnt_neg == 1:
                return (False, False, 1)
            if cnt_neg >= 2:
                apply_abs = True

        return (True, apply_abs, int(effect_mult))

    def _safe_stat_value(sid: int) -> float:
        try:
            return float(current_stats.get(int(sid), 0.0) or 0.0)
        except Exception:
            return 0.0

    for c in cards:
        card_id = _resolve_card_id_from_entry(c)
        if card_id <= 0:
            continue

        bonus_rows = _load_card_bonus_rows(conn, card_id)
        if not bonus_rows:
            continue

        for br in bonus_rows:
            cbid = br["CBId"]
            btid = br["Type_Id"]
            if cbid <= 0 or btid <= 0:
                continue

            if allowed_bt_ids is not None and int(btid) not in allowed_bt_ids:
                continue

            ok, apply_abs, effect_mult = _eval_conditions(br)
            if not ok:
                continue

            bts = _load_bonustype_stat_map(conn, btid)  # (VarIndex, Stat_Id, IsMultiply)
            if not bts:
                continue

            # группируем маппинг по VarIndex
            bts_by_vi: Dict[int, List[Tuple[int, int]]] = {}
            for vi, sid, im in (bts or []):
                vi_i = int(vi)
                sid_i = int(sid)
                im_i = int(im)
                if sid_i <= 0:
                    continue
                bts_by_vi.setdefault(vi_i, []).append((sid_i, im_i))

            if not bts_by_vi:
                continue

            btv = _load_bonustype_variables(conn, btid)  # {Index: meta}
            if not btv:
                continue

            # кандидаты: такие BonusTypeVariable.Index, которые (а) имеют MultiplicityStat_Id, (б) реально используются в bts
            cand_vars: list[tuple[int, dict]] = []
            for vidx, meta in (btv or {}).items():
                try:
                    vi_i = int(vidx)
                except Exception:
                    continue
                if not isinstance(meta, dict):
                    continue
                msid = meta.get("MultiplicityStat_Id")
                if not msid:
                    continue
                if vi_i not in bts_by_vi:
                    continue
                cand_vars.append((vi_i, meta))

            if not cand_vars:
                continue

            # если несколько кандидатов и они мапятся в один и тот же набор выходных статов -> считаем их альтернативами
            # и выбираем 1 активный по максимальному значению текущего исходного стата.
            process_vars = list(cand_vars)

            if len(cand_vars) > 1:
                target_sets = []
                for vi_i, _meta in cand_vars:
                    s = frozenset((int(sid), int(im)) for (sid, im) in (bts_by_vi.get(int(vi_i)) or []))
                    target_sets.append(s)

                if len(set(target_sets)) == 1:
                    # альтернативы
                    def _score(t: tuple[int, dict]) -> tuple[float, int]:
                        vi_i, meta = t
                        msid = int(meta.get("MultiplicityStat_Id") or 0)
                        # tie-break: меньший vi предпочтительнее
                        return (_safe_stat_value(msid), -int(vi_i))

                    best = max(cand_vars, key=_score)
                    process_vars = [best]

            # один раз грузим var_map для cbid
            var_map = _load_card_bonus_vars_with_conditions(
                conn,
                cbid,
                item_type_id=item_type_id,
                is_single_hand=is_single_hand,
            )
            if not var_map:
                continue

            # base = Index=0 (fallback: первый ненулевой)
            base_val = _to_float(var_map.get(0, 0.0), 0.0)
            if abs(base_val) <= 1e-12:
                for _k in sorted(var_map.keys()):
                    vv = _to_float(var_map.get(_k, 0.0), 0.0)
                    if abs(vv) > 1e-12:
                        base_val = vv
                        break
            if abs(base_val) <= 1e-12:
                continue

            # first_val (для совместимости с тем, как основной проход мог бы взять fallback для VarIndex=0)
            first_val = 0.0
            for _k in sorted(var_map.keys()):
                vv = _to_float(var_map.get(_k, 0.0), 0.0)
                if abs(vv) > 1e-12:
                    first_val = vv
                    break

            # считаем дельты по каждому выбранному VarIndex
            for vidx, meta in (process_vars or []):
                vi_i = int(vidx)

                msid = int(meta.get("MultiplicityStat_Id") or 0)
                if msid <= 0:
                    continue

                # step/threshold:
                # сначала пробуем CardBonusVariable.Index == BonusTypeVariable.Index,
                # если нет — fallback на Index=1
                step_val = None
                if vi_i in var_map:
                    step_val = _to_float(var_map.get(vi_i, 0.0), 0.0)
                elif 1 in var_map:
                    step_val = _to_float(var_map.get(1, 0.0), 0.0)

                if step_val is None:
                    continue

                src_val = _safe_stat_value(msid)

                # что было применено в первом проходе (current_stats=None)
                if vi_i in var_map:
                    already = _to_float(var_map.get(vi_i, 0.0), 0.0)
                else:
                    already = float(first_val) if vi_i == 0 else 0.0

                computed = 0.0
                mval = meta.get("MultiplicityValue", None)

                # РЕЖИМ 1: "за каждые X" (MultiplicityValue отсутствует)
                if mval is None:
                    div_eff = float(step_val)
                    if abs(div_eff) <= 1e-12:
                        computed = 0.0
                    else:
                        cnt = int(math.floor(float(src_val) / float(div_eff)))
                        computed = float(base_val) * float(cnt) if cnt > 0 else 0.0
                else:
                    # РЕЖИМ 2: условный множитель
                    try:
                        mult = float(mval)
                    except Exception:
                        mult = 0.0

                    fid = meta.get("MulFormula_Id", None)
                    op = _formula_op(conn, int(fid or 0))
                    ok2 = _cmp_by_op(op, float(src_val), float(step_val))
                    computed = float(base_val) * float(mult) if (ok2 and abs(mult) > 1e-12) else 0.0

                if apply_abs:
                    computed = abs(float(computed))
                    already = abs(float(already))

                if effect_mult != 1:
                    computed = float(computed) * float(effect_mult)
                    already = float(already) * float(effect_mult)

                delta = float(computed) - float(already)
                if abs(delta) <= 1e-12:
                    continue

                loc_add: Dict[int, float] = {}
                loc_mul: Dict[int, float] = {}

                for sid, im in (bts_by_vi.get(vi_i) or []):
                    if int(im) == 1:
                        loc_mul[int(sid)] = float(loc_mul.get(int(sid), 0.0)) + float(delta)
                    else:
                        loc_add[int(sid)] = float(loc_add.get(int(sid), 0.0)) + float(delta)

                _merge(add_out, loc_add)
                _merge(mul_out, loc_mul)

    return add_out, mul_out

def _get_equipment_internal_level(conn, equip_id: int, fallback: int = 1) -> int:
    """
    ВАЖНО: internal_level берём ТОЛЬКО из Equipment.InternalLevel (как в StampWindow),
    иначе при fallback на 60 получаются 48 вместо 8.
    """
    try:
        row = conn.execute(
            "SELECT InternalLevel, Level FROM Equipment WHERE Id=? LIMIT 1",
            (int(equip_id),),
        ).fetchone()
        if not row:
            return int(fallback)

        ilvl = row[0]
        if ilvl is None:
            ilvl = row[1]

        ilvl = _to_int(ilvl, fallback)
        return ilvl if ilvl > 0 else int(fallback)
    except Exception:
        return int(fallback)

def _get_bonus_type_coefs(conn, bonus_type_id: int) -> Tuple[float, float]:
    """BonusType.StampQualityMinCoef/StampQualityMaxCoef, иначе (1,1)."""
    try:
        row = conn.execute(
            "SELECT StampQualityMinCoef, StampQualityMaxCoef FROM BonusType WHERE Id=? LIMIT 1",
            (int(bonus_type_id),),
        ).fetchone()
        if not row:
            return (1.0, 1.0)
        return (_to_float(row[0], 1.0), _to_float(row[1], 1.0))
    except Exception:
        return (1.0, 1.0)

def _calc_stamp_scaled_value(
    *,
    base_value: float,
    min_coef: float,
    max_coef: float,
    internal_level: int,
    max_level: float = 60.0,
) -> int:
    """
    1:1 логика из StampWindow._get_stamp_value():
      lvl_min = 10
      coef = mn + d*(internal_level - lvl_min)
      num = coef * base
      округление: ceil если (ceil-num)<0.98, иначе trunc
    """
    base = float(base_value)
    mn = float(min_coef)
    mx = float(max_coef)

    lvl_min = 10.0
    lvl_max = float(max_level)

    if lvl_max <= lvl_min:
        coef = mn
    else:
        d = (mx - mn) / (lvl_max - lvl_min)
        value = max(0.0, float(internal_level) - lvl_min)
        coef = mn + d * value

    num = coef * base
    num2 = math.ceil(num)
    out = num2 if (num2 - num) < 0.98 else math.trunc(num)
    return int(out)

def calc_stamp_bonus_stats_for_equipment(
    conn,
    *,
    equip_id: int,
    stamp_id: int,
    color_id: int,
    debug: bool = False,
) -> Dict[int, float]:
    """
    Возвращает dict Stat_Id -> value (ADD)
    Считает печать строго как StampWindow (по internal_level предмета).
    """
    equip_id = _to_int(equip_id, 0)
    stamp_id = _to_int(stamp_id, 0)
    color_id = _to_int(color_id, 0)
    if equip_id <= 0 or stamp_id <= 0:
        return {}

    # 1) variant
    row = conn.execute(
        "SELECT Id FROM StampVariant WHERE Stamp_Id=? AND Color_Id=? LIMIT 1",
        (stamp_id, color_id),
    ).fetchone()
    if row:
        variant_id = _to_int(row[0], 0)
    else:
        row = conn.execute(
            "SELECT Id FROM StampVariant WHERE Stamp_Id=? ORDER BY Color_Id DESC LIMIT 1",
            (stamp_id,),
        ).fetchone()
        variant_id = _to_int(row[0], 0) if row else 0

    if variant_id <= 0:
        return {}

    # 2) internal level предмета (КРИТИЧНО)
    ilvl = _get_equipment_internal_level(conn, equip_id, fallback=1)

    # 3) бонусы печати (Type_Id + QualityValue)
    rows = conn.execute(
        "SELECT Type_Id, QualityValue FROM StampVariantBonus "
        "WHERE StampVariant_Id=? ORDER BY OrderIndex, rowid",
        (variant_id,),
    ).fetchall()

    out: Dict[int, float] = {}

    for r in rows or []:
        type_id = _to_int(r[0], 0)
        base_q = _to_float(r[1], 0.0)
        if type_id <= 0 or base_q == 0:
            continue

        mn, mx = _get_bonus_type_coefs(conn, type_id)
        scaled = _calc_stamp_scaled_value(
            base_value=base_q,
            min_coef=mn,
            max_coef=mx,
            internal_level=ilvl,
            max_level=60.0,  # как у тебя в StampWindow (min(60, cap))
        )

        # 4) маппинг Type_Id -> Stat_Id через BonusTypeStat
        mrows = conn.execute(
            "SELECT Stat_Id, IsMultiply FROM BonusTypeStat WHERE BonusType_Id=?",
            (type_id,),
        ).fetchall()

        for mr in mrows or []:
            stat_id = _to_int(mr[0], 0)
            is_mul = _to_int(mr[1], 0)

            # Пока возвращаем только ADD-часть.
            # (Если захочешь правильно учесть IsMultiply=1 — скажи, сделаем отдельно мультипликаторы.)
            if stat_id > 0 and is_mul == 0:
                out[stat_id] = out.get(stat_id, 0.0) + float(scaled)

    return out

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

def compute_equipment_bonus_stats_via_bonustype(
    conn,
    equipment_rows: list[dict],
    *,
    return_parts: bool = False,
    debug: bool = True,
    MULTIPLY_DIV: int = 100,
    player_level: Optional[int] = None,
    menu_bonus_enabled: Optional[Mapping[str, bool]] = None,
    single_bonus_seen: Optional[set[int]] = None,
):
    """
    Суммарные статы от экипировки:
      - базовые Attack/Defense из Equipment
      - форж: добавка к atk/def по EquipmentForge (округление ВСЕГДА ВВЕРХ),
              HP по EquipmentLevelForge (по Equipment.InternalLevel),
              allstat по EquipmentForge.AllStatBonus
      - бонусы предмета: EquipmentBonus + EquipmentBonusVariable -> BonusTypeStat
      - печать: StampVariantBonus(QualityValue scaled) -> BonusTypeStat
      - карты: compute_cards_bonus_stats_for_item()
        учитывает RequiredCard_Id / NegateCard_Id / MultiplyEffectCard_Id через общий контекст экипированных карт
      - EquipmentTypeBonus:
            Equipment.Type_Id -> EquipmentTypeBonus (Type_Id, Value) -> BonusTypeStat

    ВАЖНО (обновлено):
      - все проценты (BonusTypeStat.IsMultiply=1) стакаем как произведение:
            Π(1 + p/100)
        а наружу отдаём эквивалентным процентом:
            (prod - 1) * 100
      - если return_parts=True -> возвращает (add_dict, mul_percent_equiv_dict) и НЕ применяет проценты.
      - если return_parts=False -> применяет проценты внутри и возвращает итоговый dict.
    """
    from collections import defaultdict
    import math
    import re

    armor_bl = _armor_bl_for_level(player_level)

    _menu_defaults = {
        "talents": True,
        "guild": True,
        "elixir": True,
        "consumble": True,
        "aura": True,
        "buffs": True,
        "collect": True,
        "stamp": True,
        "reforge": True,
    }
    _menu_flags = dict(_menu_defaults)
    if isinstance(menu_bonus_enabled, Mapping):
        for _k, _v in menu_bonus_enabled.items():
            _kk = str(_k or "").strip().lower()
            if _kk:
                _menu_flags[_kk] = bool(_v)

    def _menu_on(key: str) -> bool:
        return bool(_menu_flags.get(str(key or "").strip().lower(), True))

    # ------------------------- utils -------------------------
    def _toi(v, d=0) -> int:
        try:
            return int(v)
        except Exception:
            try:
                return int(float(str(v).strip()))
            except Exception:
                return d

    def _tof(v, d=0.0) -> float:
        try:
            return float(v)
        except Exception:
            try:
                return float(str(v).replace(",", ".").strip())
            except Exception:
                return d

    def _table_exists(_conn, name: str) -> bool:
        try:
            row = _conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
                (name,),
            ).fetchone()
            return bool(row)
        except Exception:
            return False

    _PLUS_RE = re.compile(r"^\s*\+\s*(\d+)\b")
    _CEIL_EPS = 1e-9

    def _ceil_mul(base: int, coef: float) -> int:
        if base <= 0 or coef <= 0:
            return 0
        x = float(base) * float(coef)
        return int(math.ceil(x - _CEIL_EPS))

    # ------------------------- early exit -------------------------
    if not conn or not equipment_rows:
        return ({}, {}) if return_parts else {}

    if single_bonus_seen is None:
        single_bonus_seen = set()

    # ------------------------- Stat.IsPercent map -------------------------
    stat_is_percent: dict[int, bool] = {}
    try:
        rows = conn.execute("SELECT Id, IsPercent FROM Stat").fetchall()
        for r in rows or []:
            if hasattr(r, "keys"):
                sid = _toi(r["Id"], 0)
                ip = _toi(r["IsPercent"], 0)
            else:
                sid = _toi(r[0], 0)
                ip = _toi(r[1], 0)
            if sid > 0:
                stat_is_percent[int(sid)] = bool(ip)
    except Exception:
        pass

    # ------------------------- collect equipped cards context -------------------------
    def _iter_card_ids_from_item(it: dict) -> list[int]:
        cards_raw = it.get("_cards") or it.get("cards") or it.get("Cards")
        if not cards_raw:
            return []
        if isinstance(cards_raw, dict):
            cards_list = list(cards_raw.values())
        elif isinstance(cards_raw, (list, tuple)):
            cards_list = list(cards_raw)
        else:
            return []

        out: list[int] = []
        for cc in cards_list:
            cid = 0
            if isinstance(cc, dict):
                cid = _toi(cc.get("Id") or cc.get("Card_Id") or cc.get("card_id"), 0)
            elif isinstance(cc, (tuple, list)) and cc:
                cid = _toi(cc[0], 0)
            else:
                cid = _toi(cc, 0)

            if cid > 0:
                out.append(int(cid))
        return out

    equipped_card_ids: list[int] = []
    for it0 in equipment_rows:
        if isinstance(it0, dict):
            equipped_card_ids.extend(_iter_card_ids_from_item(it0))
    equipped_ctx = tuple(equipped_card_ids)

    # ------------------------- caches -------------------------
    equip_cache: dict[int, tuple[int, int, int, int, int]] = {}
    forge_cache: dict[int, tuple[float, float, int]] = {}
    hp_forge_cache: dict[tuple[int, int], int] = {}
    bt_map_cache: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
    stamp_variant_cache: dict[tuple[int, int], tuple[dict[int, float], dict[int, float]]] = {}
    type_bonus_cache: dict[int, list[tuple[int, float]]] = {}
    equiptype_dbg_cache: dict[int, tuple[str, int, int, int] | None] = {}

    mul_idx_cache: dict[int, set[int]] = {}

    def _mul_indices_for_bonus_type(bonus_type_id: int) -> set[int]:
        bt_id = int(bonus_type_id or 0)
        if bt_id <= 0:
            return set()

        if bt_id in mul_idx_cache:
            return mul_idx_cache[bt_id]

        try:
            if not _table_exists(conn, "BonusTypeVariable"):
                mul_idx_cache[bt_id] = set()
                return mul_idx_cache[bt_id]
        except Exception:
            mul_idx_cache[bt_id] = set()
            return mul_idx_cache[bt_id]

        try:
            info_rows = conn.execute('PRAGMA table_info("BonusTypeVariable")').fetchall()
        except Exception:
            info_rows = []

        low_to_real: dict[str, str] = {}
        for r in info_rows or []:
            try:
                nm = r["name"] if hasattr(r, "keys") else r[1]
            except Exception:
                nm = None
            if nm:
                low_to_real[str(nm).lower()] = str(nm)

        def _pick(cands: list[str]) -> Optional[str]:
            for c in cands:
                cc = str(c).lower()
                if cc in low_to_real:
                    return low_to_real[cc]
            return None

        bt_col = _pick(["BonusType_Id", "BonusTypeId", "BonusType"])
        mf_col = _pick(["MulFormula_Id", "MulFormulaId", "MulFormula"])
        idx_col = _pick(["Index", "Idx"])

        if not bt_col or not mf_col or not idx_col:
            mul_idx_cache[bt_id] = set()
            return mul_idx_cache[bt_id]

        try:
            rows = conn.execute(
                f"""
                SELECT {_qident(idx_col)} AS idx
                FROM "BonusTypeVariable"
                WHERE {_qident(bt_col)} = ? AND {_qident(mf_col)} = 16
                """,
                (bt_id,),
            ).fetchall()
            s = {
                int((rr["idx"] if hasattr(rr, "keys") else rr[0]))
                for rr in (rows or [])
                if (rr["idx"] if hasattr(rr, "keys") else rr[0]) is not None
            }
        except Exception:
            s = set()

        mul_idx_cache[bt_id] = s
        return s

    # ------------------------- db getters -------------------------
    def _equip_row(eid: int) -> tuple[int, int, int, int, int] | None:
        eid = int(eid)
        if eid in equip_cache:
            return equip_cache[eid]
        row = conn.execute(
            "SELECT Attack, Defense, Level, InternalLevel, Type_Id FROM Equipment WHERE Id=? LIMIT 1",
            (eid,),
        ).fetchone()
        if not row:
            return None
        if hasattr(row, "keys"):
            atk = _toi(row["Attack"], 0)
            df = _toi(row["Defense"], 0)
            lvl = _toi(row["Level"], 0)
            ilv = _toi(row["InternalLevel"], 0)
            tid = _toi(row["Type_Id"], 0)
        else:
            atk = _toi(row[0], 0)
            df = _toi(row[1], 0)
            lvl = _toi(row[2], 0)
            ilv = _toi(row[3], 0)
            tid = _toi(row[4], 0)
        equip_cache[eid] = (atk, df, lvl, ilv, tid)
        return equip_cache[eid]

    def _resolve_equipment_id(it: dict) -> int:
        keys_order = ("Equipment_Id", "Equip_Id", "TemplateId", "Template_Id", "Item_Id", "Id")
        for k in keys_order:
            if k in it and it[k] not in (None, ""):
                eid = _toi(it[k], 0)
                if eid > 0 and _equip_row(eid) is not None:
                    return int(eid)

        for k, v in (it or {}).items():
            if not isinstance(k, str):
                continue
            lk = k.lower()
            if "id" not in lk:
                continue
            eid = _toi(v, 0)
            if eid > 0 and _equip_row(eid) is not None:
                return int(eid)

        return 0

    def _forge_level_from_item(it: dict) -> int:
        for k in ("__forge_level", "ForgeLevel", "UpgradeLevel", "Plus", "EnhanceLevel"):
            v = _toi(it.get(k), 0)
            if v > 0:
                return v
        name = str(it.get("Name") or it.get("DisplayName") or "")
        m = _PLUS_RE.match(name)
        if m:
            return _toi(m.group(1), 0)
        return 0

    def _forge_coefs(level: int) -> tuple[float, float, int]:
        level = int(level)
        if level in forge_cache:
            return forge_cache[level]
        row = conn.execute(
            "SELECT Attack, Defense, AllStatBonus FROM EquipmentForge WHERE Level=? LIMIT 1",
            (level,),
        ).fetchone()
        if not row:
            forge_cache[level] = (0.0, 0.0, 0)
            return forge_cache[level]
        if hasattr(row, "keys"):
            atk_c = _tof(row["Attack"], 0.0)
            def_c = _tof(row["Defense"], 0.0)
            all_s = _toi(row["AllStatBonus"], 0)
        else:
            atk_c = _tof(row[0], 0.0)
            def_c = _tof(row[1], 0.0)
            all_s = _toi(row[2], 0)
        forge_cache[level] = (atk_c, def_c, all_s)
        return forge_cache[level]

    def _forge_hp(forge_level: int, internal_level: int) -> int:
        key = (int(forge_level), int(internal_level))
        if key in hp_forge_cache:
            return hp_forge_cache[key]
        row = conn.execute(
            "SELECT Hp FROM EquipmentLevelForge WHERE Level=? AND EquipmentLevel=? LIMIT 1",
            (int(forge_level), int(internal_level)),
        ).fetchone()
        hp = 0 if not row else (_toi(row["Hp"], 0) if hasattr(row, "keys") else _toi(row[0], 0))
        hp_forge_cache[key] = hp
        return hp

    def _bt_map(bt: int) -> list[tuple[int, int, int]]:
        bt = int(bt)
        ev = get_active_event_id()
        st = get_active_state_id()
        key = (bt, ev, st)

        if key in bt_map_cache:
            return bt_map_cache[key]

        try:
            rows = conn.execute(
                "SELECT Id, VarIndex, Stat_Id, IsMultiply FROM BonusTypeStat WHERE BonusType_Id=?",
                (bt,),
            ).fetchall()
        except Exception:
            rows = []

        if not rows:
            bt_map_cache[key] = []
            return []

        bts_ids = []
        for r in rows:
            if hasattr(r, "keys"):
                bts_ids.append(_toi(r["Id"], 0))
            else:
                bts_ids.append(_toi(r[0], 0))

        cond_map = _load_bts_conditions_map(conn, [int(x) for x in bts_ids if int(x or 0) > 0])

        out: list[tuple[int, int, int]] = []
        for r in rows or []:
            if hasattr(r, "keys"):
                bts_id = _toi(r["Id"], 0)
                vi = _toi(r["VarIndex"], 0)
                sid = _toi(r["Stat_Id"], 0)
                mul = _toi(r["IsMultiply"], 0)
            else:
                bts_id = _toi(r[0], 0)
                vi = _toi(r[1], 0)
                sid = _toi(r[2], 0)
                mul = _toi(r[3], 0)

            if sid <= 0:
                continue

            if not _bts_conditions_allow(cond_map.get(int(bts_id), None)):
                continue

            out.append((int(vi), int(sid), int(mul)))

        bt_map_cache[key] = out
        return out

    _mounted_cache: Optional[bool] = None

    def _is_mounted_state() -> bool:
        nonlocal _mounted_cache
        if _mounted_cache is not None:
            return bool(_mounted_cache)
        try:
            _mounted_cache = bool(_bt_map(262) or _bt_map(265))
        except Exception:
            _mounted_cache = False
        return bool(_mounted_cache)

    _mv241_stat_ids: set[int] = set()
    try:
        for _vi, _sid, _im in (_bt_map(241) or []):
            if int(_sid) > 0:
                _mv241_stat_ids.add(int(_sid))
    except Exception:
        _mv241_stat_ids = set()

    if not _mv241_stat_ids:
        try:
            rows = conn.execute(
                "SELECT DISTINCT Stat_Id FROM BonusTypeStat WHERE BonusType_Id=?",
                (241,),
            ).fetchall()
            for r in rows or []:
                sid = _toi(r["Stat_Id"], 0) if hasattr(r, "keys") else _toi(r[0], 0)
                if sid > 0:
                    _mv241_stat_ids.add(int(sid))
        except Exception:
            pass

    def _pick_fallback_value(var_map: dict[int, float]) -> float:
        if 0 in var_map and abs(float(var_map[0])) > 1e-12:
            return float(var_map[0])
        if len(var_map) == 1:
            return float(next(iter(var_map.values())))
        return 0.0

    res_add = defaultdict(float)
    res_mul_prod: dict[int, float] = {}

    def _dbg_slot_label(_it: dict, _eid: int = 0, _type_id: int = 0) -> str:
        slot = str(
            _it.get("_slot")
            or _it.get("Slot")
            or _it.get("slot")
            or _it.get("SlotKey")
            or _it.get("slot_key")
            or ""
        ).strip().lower()
        tok = str(
            _it.get("_uuid")
            or _it.get("InstanceGuid")
            or _it.get("Guid")
            or _it.get("Id")
            or id(_it)
        )
        nm = str(_it.get("Name") or _it.get("DisplayName") or "").strip()
        parts = []
        if slot:
            parts.append(slot)
        if _eid:
            parts.append(f"eid={int(_eid)}")
        if _type_id:
            parts.append(f"type={int(_type_id)}")
        if tok:
            parts.append(f"tok={tok}")
        if nm:
            parts.append(f"name={nm}")
        return " | ".join(parts) if parts else tok

    def _dbg_fmt_map(d: dict[int, float], *, is_mul: bool = False) -> str:
        if not d:
            return "{}"
        items = []
        for k in sorted(d.keys()):
            try:
                sid = int(k)
                v = float(d[k])
            except Exception:
                continue
            if abs(v) <= 1e-12:
                continue
            if is_mul:
                pv = (float(v) - 1.0) * float(MULTIPLY_DIV)
                items.append(f"{sid}:{pv:+.6g}%")
            else:
                items.append(f"{sid}:{v:+.6g}")
        return "{" + ", ".join(items) + "}"

    def _mul_prod_into(prod_map: dict[int, float], stat_id: int, pct: float) -> None:
        try:
            sid = int(stat_id)
            p = float(pct)
        except Exception:
            return
        if sid <= 0:
            return
        if abs(p) <= 1e-12:
            return
        f = 1.0 + p / float(MULTIPLY_DIV)
        prod_map[sid] = float(prod_map.get(sid, 1.0)) * float(f)

    def _apply_bonus_type(
            bt: int,
            var_map: dict[int, float],
            out_add: defaultdict[int, float],
            out_mul_prod: dict[int, float],
    ) -> None:
        bt_i = int(bt or 0)
        mounted = _is_mounted_state()

        if bt_i == 241 and mounted:
            return
        if bt_i in (262, 265) and (not mounted):
            return

        mapped = _bt_map(bt)
        if not mapped:
            return

        if not _take_bonus_type_once(conn, single_bonus_seen, int(bt_i)):
            return

        if var_map and armor_bl != 1.0:
            mul_idxs = _mul_indices_for_bonus_type(int(bt))
            if mul_idxs and armor_bl != 1.0:
                vm = dict(var_map)

                for idx in mul_idxs:
                    try:
                        i = int(idx)
                    except Exception:
                        continue

                    if i in vm:
                        try:
                            fv = float(vm[i]) * float(armor_bl)
                            if fv >= 0:
                                fv = math.floor(fv + 0.5)
                            else:
                                fv = math.ceil(fv - 0.5)
                            vm[i] = int(fv)
                        except Exception:
                            pass
                        continue

                    j = i - 1
                    if j in vm:
                        try:
                            fv = float(vm[j]) * float(armor_bl)
                            if fv >= 0:
                                fv = math.floor(fv + 0.5)
                            else:
                                fv = math.ceil(fv - 0.5)
                            vm[j] = int(fv)
                        except Exception:
                            pass

                var_map = vm

        fb = _pick_fallback_value(var_map)

        for var_index, stat_id, is_mul in mapped:
            v = float(var_map.get(int(var_index), fb))
            if abs(v) <= 1e-12:
                continue

            sid = int(stat_id)
            im = int(is_mul)

            if _mv241_stat_ids and sid in _mv241_stat_ids:
                if mounted:
                    if bt_i not in (262, 265):
                        continue
                    if im == 1:
                        _mul_prod_into(out_mul_prod, sid, v)
                    else:
                        out_add[sid] += v
                    continue

                if bt_i in (262, 265):
                    continue

                if im == 1:
                    _mul_prod_into(out_mul_prod, sid, v)
                    continue

                out_add[sid] += v
                continue

            if im == 1:
                _mul_prod_into(out_mul_prod, sid, v)
            else:
                out_add[sid] += v

    def _resolve_stamp_variant_id(it: dict) -> int:
        def _valid_variant(vid: int) -> bool:
            if vid <= 0:
                return False
            try:
                row = conn.execute("SELECT 1 FROM StampVariant WHERE Id=? LIMIT 1", (int(vid),)).fetchone()
                return bool(row)
            except Exception:
                return False

        def _pick_int(d: dict, keys: tuple[str, ...]) -> int:
            for k in keys:
                if k in d and d[k] not in (None, ""):
                    try:
                        v = int(float(str(d[k]).strip()))
                        if v:
                            return v
                    except Exception:
                        pass
            return 0

        for k in ("StampVariant_Id", "StampVariantId", "_stamp_variant_id"):
            vid = _toi(it.get(k), 0)
            if _valid_variant(vid):
                return int(vid)

        stamp = it.get("_stamp") or it.get("stamp") or it.get("Stamp")
        if isinstance(stamp, dict):
            for k in ("StampVariant_Id", "StampVariantId", "Variant_Id", "VariantId", "_stamp_variant_id"):
                vid = _toi(stamp.get(k), 0)
                if _valid_variant(vid):
                    return int(vid)

        stamp_id = _pick_int(it, ("StampId", "Stamp_Id", "StampID", "stamp_id"))
        color_id = _pick_int(it, ("ColorId", "Color_Id", "StampColorId", "StampColor_Id", "stamp_color_id"))

        if isinstance(stamp, dict):
            if stamp_id <= 0:
                stamp_id = _pick_int(stamp, ("StampId", "Stamp_Id", "Id", "stamp_id"))
            if color_id <= 0:
                color_id = _pick_int(stamp, ("ColorId", "Color_Id", "StampColorId", "StampColor_Id", "stamp_color_id"))

        if stamp_id <= 0:
            return 0

        try:
            if color_id > 0:
                row = conn.execute(
                    "SELECT Id FROM StampVariant WHERE Stamp_Id=? AND Color_Id=? LIMIT 1",
                    (int(stamp_id), int(color_id)),
                ).fetchone()
                if row:
                    return int(row["Id"] if hasattr(row, "keys") else row[0])

            row = conn.execute(
                "SELECT Id FROM StampVariant WHERE Stamp_Id=? ORDER BY Color_Id DESC LIMIT 1",
                (int(stamp_id),),
            ).fetchone()
            if row:
                return int(row["Id"] if hasattr(row, "keys") else row[0])
        except Exception:
            pass

        return 0

    def _get_bonus_type_coefs(bt: int) -> tuple[float, float]:
        row = conn.execute(
            "SELECT StampQualityMinCoef, StampQualityMaxCoef FROM BonusType WHERE Id=? LIMIT 1",
            (int(bt),),
        ).fetchone()
        if not row:
            return (1.0, 1.0)
        if hasattr(row, "keys"):
            return (_tof(row["StampQualityMinCoef"], 1.0), _tof(row["StampQualityMaxCoef"], 1.0))
        return (_tof(row[0], 1.0), _tof(row[1], 1.0))

    def _calc_stamp_scaled_value(base_value: float, mn: float, mx: float, internal_level: int) -> int:
        lvl_min = 10.0
        lvl_max = 60.0
        ilvl = float(max(0, int(internal_level)))

        if lvl_max <= lvl_min:
            coef = float(mn)
        else:
            d = (float(mx) - float(mn)) / (lvl_max - lvl_min)
            value = max(0.0, ilvl - lvl_min)
            coef = float(mn) + d * value

        num = coef * float(base_value)
        num2 = math.ceil(num)
        out = num2 if (num2 - num) < 0.98 else math.trunc(num)
        return int(out)

    def _stamp_variant_scaled_parts(stamp_variant_id: int, internal_level: int) -> tuple[dict[int, float], dict[int, float]]:
        key = (int(stamp_variant_id), int(internal_level))
        if key in stamp_variant_cache:
            return stamp_variant_cache[key]

        out_add = defaultdict(float)
        out_mul_prod_local: dict[int, float] = {}

        rows = conn.execute(
            "SELECT Type_Id, QualityValue FROM StampVariantBonus "
            "WHERE StampVariant_Id=? ORDER BY OrderIndex, rowid",
            (int(stamp_variant_id),),
        ).fetchall()

        for r in rows or []:
            if hasattr(r, "keys"):
                bt = _toi(r["Type_Id"], 0)
                qv = _tof(r["QualityValue"], 0.0)
            else:
                bt = _toi(r[0], 0)
                qv = _tof(r[1], 0.0)

            if bt <= 0 or abs(qv) <= 1e-12:
                continue

            mn, mx = _get_bonus_type_coefs(bt)
            scaled = _calc_stamp_scaled_value(qv, mn, mx, internal_level)

            _apply_bonus_type(bt, {0: float(scaled)}, out_add, out_mul_prod_local)

        add_res = {int(k): float(v) for k, v in out_add.items() if abs(float(v)) > 1e-12}
        mul_res_pct_equiv: dict[int, float] = {}
        for sid, f in (out_mul_prod_local or {}).items():
            try:
                ff = float(f)
            except Exception:
                continue
            if abs(ff - 1.0) <= 1e-12:
                continue
            mul_res_pct_equiv[int(sid)] = (ff - 1.0) * float(MULTIPLY_DIV)

        stamp_variant_cache[key] = (add_res, mul_res_pct_equiv)
        return add_res, mul_res_pct_equiv

    has_type_bonus = _table_exists(conn, "EquipmentTypeBonus")

    def _load_equipment_type_bonuses(equip_type_id: int) -> list[tuple[int, float]]:
        etid = int(equip_type_id or 0)
        if etid <= 0 or not has_type_bonus:
            return []
        if etid in type_bonus_cache:
            return type_bonus_cache[etid]
        try:
            rows = conn.execute(
                "SELECT Type_Id, Value FROM EquipmentTypeBonus WHERE EquipmentType_Id=? ORDER BY Id",
                (etid,),
            ).fetchall()
        except Exception:
            rows = []

        out: list[tuple[int, float]] = []
        for r in rows or []:
            if hasattr(r, "keys"):
                bt = _toi(r["Type_Id"], 0)
                val = _tof(r["Value"], 0.0)
            else:
                bt = _toi(r[0], 0)
                val = _tof(r[1], 0.0)
            if bt > 0 and abs(val) > 1e-12:
                out.append((int(bt), float(val)))

        type_bonus_cache[etid] = out
        return out

    def _equiptype_dbg(tid: int) -> tuple[str, int, int, int] | None:
        tid = int(tid or 0)
        if tid <= 0:
            return None
        if tid in equiptype_dbg_cache:
            return equiptype_dbg_cache[tid]
        try:
            row = conn.execute(
                "SELECT Name, Slot_Id, IsMeleeWeapon, IsSingleHandWeapon FROM EquipmentType WHERE Id=? LIMIT 1",
                (tid,),
            ).fetchone()
        except Exception:
            row = None
        if not row:
            equiptype_dbg_cache[tid] = None
            return None
        if hasattr(row, "keys"):
            nm = str(row["Name"] or "")
            slot_id = _toi(row["Slot_Id"], 0)
            is_melee = _toi(row["IsMeleeWeapon"], 0)
            is_1h = _toi(row["IsSingleHandWeapon"], 0)
        else:
            nm = str(row[0] or "")
            slot_id = _toi(row[1], 0)
            is_melee = _toi(row[2], 0)
            is_1h = _toi(row[3], 0)
        equiptype_dbg_cache[tid] = (nm, int(slot_id), int(is_melee), int(is_1h))
        return equiptype_dbg_cache[tid]

    _dual_main_atk: int | None = None
    _dual_off_atk: int | None = None

    _weapon_markers = (
        "weapon", "mainhand", "main_hand", "weapon1", "hand1", "primary",
        "right", "rhand", "right_hand",
        "оруж", "пра", "прав", "осн",
    )
    _offhand_markers = (
        "offhand", "off_hand", "secondhand", "second_hand", "weapon2", "hand2", "secondary",
        "shield", "left", "lhand", "left_hand",
        "лева", "лев", "втор", "щит",
    )
    _spear_markers = (
        "spear", "lance", "pike", "polearm", "halberd",
        "weapon3", "hand3", "thirdhand", "third_hand",
        "копь", "копье", "копьё", "пика", "алебард",
    )

    for it in equipment_rows:
        if not isinstance(it, dict):
            continue

        _dbg_before_add = None
        _dbg_before_mul = None
        if bool(debug):
            try:
                _dbg_before_add = dict(res_add)
            except Exception:
                _dbg_before_add = None
            try:
                _dbg_before_mul = dict(res_mul_prod)
            except Exception:
                _dbg_before_mul = None

        it["_equipped_card_ids"] = equipped_ctx

        eid = _resolve_equipment_id(it)
        if eid <= 0:
            continue

        eq = _equip_row(eid)
        if eq is None:
            continue

        base_atk, base_def, _lvl, internal_lvl, type_id = eq

        if type_id > 0 and (not it.get("Type_Id")):
            it["Type_Id"] = int(type_id)

        forge_level = _forge_level_from_item(it)

        atk_total = int(base_atk or 0)
        def_total = int(base_def or 0)

        if forge_level > 0:
            atk_coef, def_coef, allstat = _forge_coefs(forge_level)

            atk_total += _ceil_mul(atk_total, atk_coef)
            def_total += _ceil_mul(def_total, def_coef)

            if internal_lvl > 0 and (not _is_weapon_type_by_equipmenttype(conn, int(type_id or 0))):
                hp = _forge_hp(forge_level, internal_lvl)
                if hp > 0:
                    res_add[1] += float(hp)

            if allstat and allstat > 0:
                for sid in (4, 5, 6, 7, 8, 9):
                    res_add[sid] += float(allstat)

        if atk_total > 0:
            slot_s = str(
                it.get("_slot")
                or it.get("Slot")
                or it.get("slot")
                or it.get("SlotKey")
                or it.get("slot_key")
                or ""
            ).strip().lower()

            slot_kind = "other"
            if slot_s:
                if any(m in slot_s for m in _spear_markers):
                    slot_kind = "spear"
                elif any(m in slot_s for m in _weapon_markers):
                    slot_kind = "weapon"
                elif any(m in slot_s for m in _offhand_markers):
                    slot_kind = "offhand"

            if slot_kind in ("weapon", "offhand"):
                try:
                    is_weapon_type = bool(_is_weapon_type_by_equipmenttype(conn, int(type_id or 0)))
                except Exception:
                    is_weapon_type = False

                if is_weapon_type:
                    raw_1h = it.get("IsSingleHandWeapon")
                    if raw_1h is None:
                        et_dbg2 = _equiptype_dbg(int(type_id or 0))
                        is_1h = int(et_dbg2[3]) if et_dbg2 else 0
                    else:
                        is_1h = _toi(raw_1h, 0)

                    if int(is_1h) == 1:
                        if slot_kind == "weapon":
                            _dual_main_atk = int(atk_total)
                        else:
                            _dual_off_atk = int(atk_total)

        if def_total > 0:
            res_add[12] += float(def_total)
        if atk_total > 0:
            res_add[10] += float(atk_total)

        if has_type_bonus and int(type_id or 0) > 0:
            tb_list = _load_equipment_type_bonuses(int(type_id))
            for bt, val in tb_list:
                _apply_bonus_type(int(bt), {0: float(val)}, res_add, res_mul_prod)

        if not hasattr(compute_equipment_bonus_stats_via_bonustype, "_equipbonus_meta"):
            try:
                info_rows = conn.execute('PRAGMA table_info("EquipmentBonus")').fetchall()
                cols = set()
                for rr in info_rows or []:
                    try:
                        nm = rr["name"] if hasattr(rr, "keys") else rr[1]
                    except Exception:
                        nm = None
                    if nm:
                        cols.add(str(nm).lower())

                setattr(
                    compute_equipment_bonus_stats_via_bonustype,
                    "_equipbonus_meta",
                    {
                        "has_activate": bool("activate" in cols),
                        "has_buff_condition": bool("buffcondition_id" in cols),
                    },
                )
            except Exception:
                setattr(
                    compute_equipment_bonus_stats_via_bonustype,
                    "_equipbonus_meta",
                    {
                        "has_activate": False,
                        "has_buff_condition": False,
                    },
                )

        equipbonus_meta = getattr(
            compute_equipment_bonus_stats_via_bonustype,
            "_equipbonus_meta",
            {},
        ) or {}

        equipbonus_has_activate = bool(equipbonus_meta.get("has_activate", False))
        equipbonus_has_buff_condition = bool(equipbonus_meta.get("has_buff_condition", False))

        active_buff_ids: set[int] = set()
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                raw = app.property("player_buff_ids")
                if isinstance(raw, (list, tuple, set)):
                    for x in raw:
                        bid = _toi(x, 0)
                        if bid > 0:
                            active_buff_ids.add(int(bid))
        except Exception:
            pass

        try:
            if equipbonus_has_activate and equipbonus_has_buff_condition:
                bonus_rows = conn.execute(
                    """
                    SELECT Id, Type_Id, Activate, BuffCondition_Id
                    FROM EquipmentBonus
                    WHERE Equipment_Id=?
                    ORDER BY OrderIndex
                    """,
                    (int(eid),),
                ).fetchall()
            elif equipbonus_has_activate:
                bonus_rows = conn.execute(
                    """
                    SELECT Id, Type_Id, Activate
                    FROM EquipmentBonus
                    WHERE Equipment_Id=?
                    ORDER BY OrderIndex
                    """,
                    (int(eid),),
                ).fetchall()
            elif equipbonus_has_buff_condition:
                bonus_rows = conn.execute(
                    """
                    SELECT Id, Type_Id, BuffCondition_Id
                    FROM EquipmentBonus
                    WHERE Equipment_Id=?
                    ORDER BY OrderIndex
                    """,
                    (int(eid),),
                ).fetchall()
            else:
                bonus_rows = conn.execute(
                    """
                    SELECT Id, Type_Id
                    FROM EquipmentBonus
                    WHERE Equipment_Id=?
                    ORDER BY OrderIndex
                    """,
                    (int(eid),),
                ).fetchall()
        except Exception:
            bonus_rows = []

        for br in bonus_rows or []:
            if hasattr(br, "keys"):
                bonus_id = _toi(br["Id"], 0)
                bt = _toi(br["Type_Id"], 0)
                act = br["Activate"] if equipbonus_has_activate else None
                buff_cond_id = _toi(br["BuffCondition_Id"], 0) if equipbonus_has_buff_condition else 0
            else:
                bonus_id = _toi(br[0], 0)
                bt = _toi(br[1], 0)

                pos = 2
                act = None
                buff_cond_id = 0

                if equipbonus_has_activate:
                    act = br[pos] if len(br) > pos else None
                    pos += 1

                if equipbonus_has_buff_condition:
                    buff_cond_id = _toi(br[pos], 0) if len(br) > pos else 0

            if bonus_id <= 0 or bt <= 0:
                continue

            # если активен связанный баф — этот бонус предмета не работает
            if buff_cond_id > 0 and buff_cond_id in active_buff_ids:
                continue

            if equipbonus_has_activate and act is not None:
                if not bool(it.get("_activate_checked", False)):
                    continue
                if _toi(act, 0) != 1:
                    continue

            try:
                var_rows = conn.execute(
                    "SELECT `Index`, Value FROM EquipmentBonusVariable "
                    "WHERE EquipmentBonus_Id=? ORDER BY `Index`",
                    (int(bonus_id),),
                ).fetchall()
            except Exception:
                var_rows = []

            var_map: dict[int, float] = {}
            for vr in var_rows or []:
                if hasattr(vr, "keys"):
                    idx = _toi(vr["Index"], 0)
                    val = _tof(vr["Value"], 0.0)
                else:
                    idx = _toi(vr[0], 0)
                    val = _tof(vr[1], 0.0)
                var_map[int(idx)] = float(val)

            _apply_bonus_type(int(bt), var_map, res_add, res_mul_prod)

        # ---- EquipmentElixir (временные улучшения) ----
        if _menu_on("elixir"):
            elx = it.get("Elixir") or it.get("_elixir") or it.get("elixir")
            if isinstance(elx, dict):
                blist = elx.get("Bonuses") or elx.get("bonuses") or []
                for b in (blist or []):
                    if not isinstance(b, dict):
                        continue

                    bt_elx = _toi(b.get("Type_Id") or b.get("TypeId") or b.get("Type"), 0)
                    val_elx = _tof(b.get("Value") or b.get("Val") or 0, 0.0)

                    if bt_elx > 0 and abs(val_elx) > 1e-12:
                        _apply_bonus_type(int(bt_elx), {0: float(val_elx)}, res_add, res_mul_prod)

        stamp_variant_id = _resolve_stamp_variant_id(it)
        if stamp_variant_id > 0:
            st_add, st_mul = _stamp_variant_scaled_parts(stamp_variant_id, internal_lvl)
            for sid, v in st_add.items():
                res_add[int(sid)] += float(v)
            for sid, v in st_mul.items():
                _mul_prod_into(res_mul_prod, int(sid), float(v))

        cards_raw = it.get("_cards") or it.get("cards") or it.get("Cards")
        if cards_raw:
            if isinstance(cards_raw, dict):
                it["_cards"] = list(cards_raw.values())

            c_add, c_mul = compute_cards_bonus_stats_for_item(
                conn,
                it,
                current_stats=None,
                equipped_card_ids=equipped_ctx,
                debug=bool(debug),
                single_bonus_seen=single_bonus_seen,
            )

            for sid, v in (c_add or {}).items():
                res_add[int(sid)] += float(v)

            for sid, v in (c_mul or {}).items():
                sid_i = int(sid)
                vv = float(v)
                _mul_prod_into(res_mul_prod, sid_i, vv)

        if bool(debug) and (_dbg_before_add is not None or _dbg_before_mul is not None):
            try:
                cur_add = dict(res_add)
                before_add = dict(_dbg_before_add or {})
                delta_add: dict[int, float] = {}
                for sid in set(cur_add.keys()) | set(before_add.keys()):
                    dv = float(cur_add.get(int(sid), 0.0)) - float(before_add.get(int(sid), 0.0))
                    if abs(dv) > 1e-12:
                        delta_add[int(sid)] = dv

                cur_mul = dict(res_mul_prod)
                before_mul = dict(_dbg_before_mul or {})
                delta_mul_factor: dict[int, float] = {}
                for sid in set(cur_mul.keys()) | set(before_mul.keys()):
                    bf = float(before_mul.get(int(sid), 1.0))
                    af = float(cur_mul.get(int(sid), 1.0))
                    if abs(bf) <= 1e-18:
                        bf = 1.0
                    ratio = af / bf
                    if abs(ratio - 1.0) > 1e-12:
                        delta_mul_factor[int(sid)] = float(ratio)

                delta_add2 = {k: v for k, v in delta_add.items() if int(k) not in (10, 12)}
                if delta_add2 or delta_mul_factor:
                    label = _dbg_slot_label(it, _eid=eid, _type_id=type_id)
                    try:
                        _cids = _iter_card_ids_from_item(it)
                    except Exception:
                        _cids = []
            except Exception:
                pass

    if _dual_main_atk is not None and _dual_off_atk is not None:
        a1 = float(_dual_main_atk)
        a2 = float(_dual_off_atk)
        if (a1 + a2) > 0.0:
            before = float(res_add.get(10, 0.0))
            res_add[10] = before - a1 - a2 + (a1 + a2) * 0.5

    add_dict = {int(k): float(v) for k, v in res_add.items() if abs(float(v)) > 1e-12}

    mul_dict_equiv: dict[int, float] = {}
    for sid, f in (res_mul_prod or {}).items():
        try:
            ff = float(f)
        except Exception:
            continue
        if abs(ff - 1.0) <= 1e-12:
            continue
        mul_dict_equiv[int(sid)] = (ff - 1.0) * float(MULTIPLY_DIV)

    if return_parts:
        return add_dict, mul_dict_equiv

    out: dict[int, float] = {}
    all_sids = set(add_dict.keys()) | set(mul_dict_equiv.keys())

    for sid in all_sids:
        fixed = float(add_dict.get(int(sid), 0.0))
        pct_equiv = float(mul_dict_equiv.get(int(sid), 0.0))

        val = fixed
        if abs(pct_equiv) > 1e-12:
            val = fixed * (1.0 + pct_equiv / float(MULTIPLY_DIV))

        if not stat_is_percent.get(int(sid), False):
            if val >= 0:
                val = float(int(math.ceil(val - _CEIL_EPS)))
            else:
                val = float(int(math.floor(val + _CEIL_EPS)))

        if abs(val) > 1e-12:
            out[int(sid)] = float(val)

    return out

# ---------------------------------------------------------------------------
# 1) Описание стата из таблицы Stat
# ---------------------------------------------------------------------------

@dataclass
class StatDef:
    id: int
    name: str
    code: Optional[str] = None
    is_percent: bool = False
    order: int = 0
    progress_name: Optional[str] = None
    image_id: Optional[int] = None
    default_value: float = 0.00

def _load_stat_defs(conn) -> List["StatDef"]:
    stat_defs: List[StatDef] = []
    if conn is None:
        return stat_defs

    # ------------------------------------------------------------
    # 1) Узнаём колонки таблицы Stat (для совместимости со старыми БД)
    # ------------------------------------------------------------
    stat_cols: set[str] = set()
    try:
        for r in conn.execute("PRAGMA table_info('Stat')").fetchall():
            try:
                stat_cols.add(str(r[1]))
            except Exception:
                pass
    except Exception:
        stat_cols = set()

    # У некоторых БД встречается опечатка IsPersent
    percent_col = None
    if "IsPercent" in stat_cols:
        percent_col = "IsPercent"
    elif "IsPersent" in stat_cols:
        percent_col = "IsPersent"

    # Какие колонки мы хотим (если они существуют)
    base_cols = ["Id", "Name"]
    opt_cols: List[str] = []

    if percent_col:
        opt_cols.append(percent_col)
    if "DefaultValue" in stat_cols:
        opt_cols.append("DefaultValue")
    if "ProgressName" in stat_cols:
        opt_cols.append("ProgressName")
    if "Image_Id" in stat_cols:
        opt_cols.append("Image_Id")
    if "OrderIndex" in stat_cols:
        opt_cols.append("OrderIndex")
    if "Element_Id" in stat_cols:
        opt_cols.append("Element_Id")
    if "Race_Id" in stat_cols:
        opt_cols.append("Race_Id")

    select_cols = base_cols + opt_cols

    # ------------------------------------------------------------
    # 2) Достаём строки (если PRAGMA не сработал — fallback варианты)
    # ------------------------------------------------------------
    rows = None
    used_cols: List[str] = []

    def _try_fetch(sql_cols: List[str]) -> Optional[list]:
        sql = "SELECT " + ", ".join(sql_cols) + " FROM Stat"
        if "OrderIndex" in sql_cols:
            sql += " ORDER BY OrderIndex ASC, Id ASC"
        else:
            sql += " ORDER BY Id ASC"
        try:
            return conn.execute(sql).fetchall()
        except Exception:
            return None

    rows = _try_fetch(select_cols)
    used_cols = list(select_cols)

    if rows is None:
        # fallback под разные схемы / опечатки
        variants = [
            ["Id", "Name", "IsPercent", "DefaultValue", "ProgressName", "Image_Id", "OrderIndex", "Element_Id", "Race_Id"],
            ["Id", "Name", "IsPersent", "DefaultValue", "ProgressName", "Image_Id", "OrderIndex", "Element_Id", "Race_Id"],

            ["Id", "Name", "IsPercent", "DefaultValue", "ProgressName", "Image_Id", "OrderIndex"],
            ["Id", "Name", "IsPersent", "DefaultValue", "ProgressName", "Image_Id", "OrderIndex"],

            ["Id", "Name", "IsPercent", "DefaultValue", "ProgressName", "Image_Id"],
            ["Id", "Name", "IsPersent", "DefaultValue", "ProgressName", "Image_Id"],

            ["Id", "Name", "IsPercent", "DefaultValue", "ProgressName"],
            ["Id", "Name", "IsPersent", "DefaultValue", "ProgressName"],

            ["Id", "Name", "IsPercent", "DefaultValue"],
            ["Id", "Name", "IsPersent", "DefaultValue"],

            ["Id", "Name", "DefaultValue", "ProgressName", "Image_Id"],
            ["Id", "Name", "DefaultValue"],
            ["Id", "Name", "ProgressName", "Image_Id"],
            ["Id", "Name"],
        ]
        for cols in variants:
            rows = _try_fetch(cols)
            if rows is not None:
                used_cols = list(cols)
                break

    if rows is None:
        return stat_defs

    col_pos = {c: i for i, c in enumerate(used_cols)}

    def _row_get(row, col: str):
        idx = col_pos.get(col, None)
        if idx is None:
            return None
        try:
            if hasattr(row, "keys") and col in row.keys():
                return row[col]
        except Exception:
            pass
        try:
            return row[idx]
        except Exception:
            return None

    # Какие колонки реально присутствуют в результирующих строках
    used_set = set(used_cols)
    has_order = "OrderIndex" in used_set
    has_element = "Element_Id" in used_set
    has_race = "Race_Id" in used_set
    has_default = "DefaultValue" in used_set
    has_progress = "ProgressName" in used_set
    has_image = "Image_Id" in used_set
    has_percent = ("IsPercent" in used_set) or ("IsPersent" in used_set)
    used_percent_col = "IsPercent" if "IsPercent" in used_set else ("IsPersent" if "IsPersent" in used_set else None)

    # ------------------------------------------------------------
    # 3) Собираем element_id / race_id и подтягиваем имена
    # ------------------------------------------------------------
    element_ids: set[int] = set()
    race_ids: set[int] = set()

    if has_element or has_race:
        for row in rows:
            if has_element:
                v_el = _row_get(row, "Element_Id")
                try:
                    if v_el is not None:
                        element_ids.add(int(v_el))
                except Exception:
                    pass
            if has_race:
                v_rc = _row_get(row, "Race_Id")
                try:
                    if v_rc is not None:
                        race_ids.add(int(v_rc))
                except Exception:
                    pass

    elem_name_by_id: Dict[int, str] = {}
    if element_ids:
        try:
            placeholders = ",".join(["?"] * len(element_ids))
            q = f"SELECT Id, Name FROM Element WHERE Id IN ({placeholders})"
            for r in conn.execute(q, tuple(sorted(element_ids))).fetchall():
                try:
                    eid = int(r[0] if not (hasattr(r, "keys") and "Id" in r.keys()) else r["Id"])
                except Exception:
                    continue
                try:
                    nm = str(r[1] if not (hasattr(r, "keys") and "Name" in r.keys()) else r["Name"])
                except Exception:
                    nm = ""
                if nm:
                    elem_name_by_id[eid] = nm
        except Exception:
            pass

    # Race map: стараемся прочитать IsPvP, если не получается — считаем IsPvP=0
    race_info_by_id: Dict[int, tuple[str, int]] = {}
    if race_ids:
        try:
            placeholders = ",".join(["?"] * len(race_ids))
            q = f"SELECT Id, Name, IsPvP FROM Race WHERE Id IN ({placeholders})"
            for r in conn.execute(q, tuple(sorted(race_ids))).fetchall():
                try:
                    rid = int(r[0] if not (hasattr(r, "keys") and "Id" in r.keys()) else r["Id"])
                except Exception:
                    continue
                try:
                    nm = str(r[1] if not (hasattr(r, "keys") and "Name" in r.keys()) else r["Name"])
                except Exception:
                    nm = ""
                try:
                    ispvp = int(r[2] if not (hasattr(r, "keys") and "IsPvP" in r.keys()) else r["IsPvP"])
                except Exception:
                    ispvp = 0
                race_info_by_id[rid] = (nm, ispvp)
        except Exception:
            # fallback без IsPvP
            try:
                placeholders = ",".join(["?"] * len(race_ids))
                q = f"SELECT Id, Name FROM Race WHERE Id IN ({placeholders})"
                for r in conn.execute(q, tuple(sorted(race_ids))).fetchall():
                    try:
                        rid = int(r[0] if not (hasattr(r, "keys") and "Id" in r.keys()) else r["Id"])
                    except Exception:
                        continue
                    try:
                        nm = str(r[1] if not (hasattr(r, "keys") and "Name" in r.keys()) else r["Name"])
                    except Exception:
                        nm = ""
                    race_info_by_id[rid] = (nm, 0)
            except Exception:
                pass

    # ------------------------------------------------------------
    # 4) Сначала собираем “сырые” данные, чтобы вычислить min order для групп
    # ------------------------------------------------------------
    prepared: List[dict] = []
    element_min_order: Optional[int] = None
    race_min_order: Optional[int] = None

    for row in rows:
        sid = _row_get(row, "Id")
        try:
            sid_int = int(sid)
        except Exception:
            continue

        base_order_db = sid_int
        if has_order:
            v = _row_get(row, "OrderIndex")
            try:
                if v is not None:
                    base_order_db = int(v)
            except Exception:
                base_order_db = sid_int

        name = _row_get(row, "Name")
        name = str(name) if name is not None else ""

        is_percent = False
        if has_percent and used_percent_col:
            v = _row_get(row, used_percent_col)
            if v is not None:
                try:
                    is_percent = bool(int(v))
                except Exception:
                    is_percent = bool(v)

        default_value = 0.0
        if has_default:
            v = _row_get(row, "DefaultValue")
            try:
                if v is not None:
                    default_value = float(v)
            except Exception:
                default_value = 0.0

        progress_name = None
        if has_progress:
            v = _row_get(row, "ProgressName")
            try:
                progress_name = str(v) if v is not None else None
            except Exception:
                progress_name = None

        image_id = None
        if has_image:
            v = _row_get(row, "Image_Id")
            try:
                image_id = int(v) if v is not None else None
            except Exception:
                image_id = None

        el_id_int: Optional[int] = None
        rc_id_int: Optional[int] = None

        if has_element:
            v = _row_get(row, "Element_Id")
            try:
                el_id_int = int(v) if v is not None else None
            except Exception:
                el_id_int = None

        if has_race:
            v = _row_get(row, "Race_Id")
            try:
                rc_id_int = int(v) if v is not None else None
            except Exception:
                rc_id_int = None

        # определяем IsPvP для race (если нет в мапе — считаем 0)
        ispvp = 0
        if rc_id_int is not None:
            ispvp = int(race_info_by_id.get(rc_id_int, ("", 0))[1] or 0)

        # обновляем min order для групп (только если правило применимо)
        if el_id_int is not None:
            element_min_order = base_order_db if element_min_order is None else min(element_min_order, base_order_db)

        if rc_id_int is not None and ispvp == 0:
            race_min_order = base_order_db if race_min_order is None else min(race_min_order, base_order_db)

        prepared.append(
            dict(
                sid=sid_int,
                name=name,
                is_percent=is_percent,
                default_value=default_value,
                progress_name=progress_name,
                image_id=image_id,
                base_order_db=base_order_db,
                element_id=el_id_int,
                race_id=rc_id_int,
                ispvp=ispvp,
            )
        )

    # если групп нет — просто чтобы не было None в сортировке
    if element_min_order is None:
        element_min_order = 10**9
    if race_min_order is None:
        race_min_order = 10**9

    # ------------------------------------------------------------
    # 5) Создаём StatDef + ключ сортировки
    # ------------------------------------------------------------
    tmp: List[tuple[tuple[int, int, int, int], StatDef]] = []

    for it in prepared:
        sid_int = int(it["sid"])
        name = str(it["name"])
        is_percent = bool(it["is_percent"])
        default_value = float(it["default_value"])
        progress_name = it["progress_name"]
        image_id = it["image_id"]
        base_order_db = int(it["base_order_db"])
        el_id_int = it["element_id"]
        rc_id_int = it["race_id"]
        ispvp = int(it["ispvp"])

        # Подмена имени
        special_sort = sid_int
        kind = 2  # обычный

        if el_id_int is not None:
            nm = elem_name_by_id.get(int(el_id_int), "")
            if nm:
                name = nm
            special_sort = int(el_id_int)
            kind = 0  # элементы

        elif rc_id_int is not None and ispvp == 0:
            nm = race_info_by_id.get(int(rc_id_int), ("", 0))[0]
            if nm:
                name = nm
            special_sort = int(rc_id_int)
            kind = 1  # расы

        # Формируем StatDef (без round_digits и прочего лишнего)
        sd = StatDef(
            id=sid_int,
            name=name,
            is_percent=is_percent,
            code=None,
            progress_name=progress_name,
            image_id=image_id,
            default_value=default_value,
        )

        # order: используем OrderIndex (если был), иначе Id
        try:
            sd.order = int(base_order_db)
        except Exception:
            pass

        # Сортировка:
        # - элементы/расы группируем в непрерывные блоки (по min OrderIndex среди них),
        #   а внутри блока сортируем по Element.Id / Race.Id
        if kind == 0:
            sort_base = int(element_min_order)
        elif kind == 1:
            sort_base = int(race_min_order)
        else:
            sort_base = int(base_order_db)

        tmp.append(((sort_base, kind, int(special_sort), sid_int), sd))

    tmp.sort(key=lambda t: t[0])
    stat_defs = [sd for _, sd in tmp]
    return stat_defs

def _res_path(rel_path: str) -> str:
    """
    Ищет ресурс по относительному пути (например 'resources/main_menu/char_plus.png')
    Пробует рядом с файлом, уровнем выше и текущую рабочую папку.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, rel_path),
        os.path.join(here, "..", rel_path),
        os.path.join(os.getcwd(), rel_path),
    ]
    for p in candidates:
        if os.path.exists(p):
            return os.path.abspath(p)
    return candidates[0]  # fallback

# ---------------------------------------------------------------------------
# 2.5) Очки параметров (StatsPerLevel из таблицы Setting) + draggable UI
# ---------------------------------------------------------------------------

# дефолтное положение плашки в "дизайн-координатах" PNG (как STATS_RECT в main_window.py)
UNSPENT_PARAM_POINTS_RECT = (606, 477, 50, 16)  # (x, y, w, h)

def _read_setting_value(conn, key: str) -> str | None:
    """
    Читает Setting.Value по Setting.Key (или близким именам колонок).
    Возвращает raw-строку или None.
    """
    if not conn or not key:
        return None

    # пробуем разные имена колонок, потому что у разных сборок БД бывает по-разному
    key_cols = ["Key", "`Key`", "\"Key\"", "[Key]", "key", "`key`", "\"key\"", "[key]", "Name", "Code"]
    sql_tpl = "SELECT Value FROM Setting WHERE {col} = ? LIMIT 1"

    for col in key_cols:
        try:
            row = conn.execute(sql_tpl.format(col=col), (str(key),)).fetchone()
            if not row:
                continue
            raw = row[0] if not hasattr(row, "keys") else row["Value"]
            if raw in (None, ""):
                return None
            return str(raw)
        except Exception:
            continue
    return None

def load_setting_int(conn, key: str, default: int = 0) -> int:
    raw = _read_setting_value(conn, key)
    if raw is None:
        return int(default)
    try:
        # на случай "3.0" или " 3 "
        return int(float(str(raw).strip()))
    except Exception:
        return int(default)

class ParamAllocationState(QObject):
    """
    Держит распределение очков параметров в памяти:
      total = (level-1) * StatsPerLevel
      unspent = total - spent
    """
    unspentChanged = Signal(int)

    def __init__(
        self,
        conn,
        *,
        base_points: int = 0,
        base_by_stat: Mapping[int, int] | None = None,
        limited_stats: Iterable[int] = (4, 5, 6, 7, 8, 9),
    ):
        super().__init__()
        self.conn = conn
        self.stats_per_level: int = load_setting_int(conn, "StatsPerLevel", default=0)
        self.base_points: int = int(base_points)

        self.limited_stats = tuple(int(x) for x in limited_stats)

        # общий MaxStatCount (как в Setting), не "минус 1"
        _msc = load_setting_int(conn, "MaxStatCount", default=0)
        self.max_stat_total: int | None = int(_msc) if int(_msc) > 0 else None

        # база по статам (именно она "входит в лимит")
        self.base_by_stat: dict[int, int] = {int(k): int(v) for k, v in (base_by_stat or {}).items()}

        # если не передали — попробуем взять DefaultValue из Stat (и clamp до min=1)
        if not self.base_by_stat and self.conn:
            try:
                for sd in _load_stat_defs(self.conn):
                    if sd.id in self.limited_stats:
                        try:
                            self.base_by_stat[int(sd.id)] = int(float(sd.default_value))
                        except Exception:
                            self.base_by_stat[int(sd.id)] = 0
            except Exception:
                pass

        # clamp: на 1 уровне у параметров минимум 1, и это должно считаться в лимите
        for sid in self.limited_stats:
            self.base_by_stat[sid] = max(1, int(self.base_by_stat.get(sid, 0)))

        self.level: int = 1
        self.total_points: int = 0

        self.allocated: dict[int, int] = {}
        self._stack: list[int] = []

    def reset_all(self) -> None:
        """Сбросить ВСЕ распределённые очки параметров (не трогая уровень/total)."""
        if not self.allocated and not self._stack:
            return
        self.allocated.clear()
        self._stack.clear()
        self.unspentChanged.emit(self.unspent_points())

    def remaining_capacity_for_stat(self, stat_id: int) -> int:
        """
        Сколько уровневых очков ещё можно вложить в этот stat_id,
        чтобы (base + allocated) <= MaxStatCount.
        """
        sid = int(stat_id)

        # лимит нужен только для параметров 4..9
        if sid not in self.limited_stats:
            return 10 ** 9

        # если MaxStatCount не задан — считаем безлимит
        if self.max_stat_total is None:
            return 10 ** 9

        base = int(self.base_by_stat.get(sid, 0))
        cap_alloc = max(0, int(self.max_stat_total - base))  # максимум, сколько можно вложить уровнем
        cur = int(self.allocated.get(sid, 0))
        return max(0, cap_alloc - cur)

    def set_level(self, level: int) -> None:
        try:
            self.level = max(1, int(level))
        except Exception:
            self.level = 1

        # если надо, легко поменять формулу (например, давать очки и на 1 уровне)
        self.total_points = int(self.base_points + max(0, (self.level - 1)) * int(self.stats_per_level))

        # если уровень понизили, а потрачено больше чем total — откатываем по стеку
        self._reconcile_after_total_change()
        self.unspentChanged.emit(self.unspent_points())

    def unspent_points(self) -> int:
        spent = sum(int(v) for v in (self.allocated or {}).values())
        return max(0, int(self.total_points - spent))

    def as_base_stats(self) -> dict[int, float]:
        """Что добавить как base_stats в calc_for_character()."""
        return {int(k): float(v) for k, v in (self.allocated or {}).items() if int(v) != 0}

    def spend(self, stat_id: int, amount: int = 1) -> bool:
        sid = int(stat_id)
        amt = max(1, int(amount))

        # NEW: ограничение по MaxStatCount (только для уровневых очков)
        cap = self.remaining_capacity_for_stat(sid)
        if cap <= 0:
            return False
        amt = min(amt, cap)

        if self.unspent_points() < amt:
            return False

        self.allocated[sid] = int(self.allocated.get(sid, 0) + amt)
        for _ in range(amt):
            self._stack.append(sid)

        self.unspentChanged.emit(self.unspent_points())
        return True

    def refund_all_for_stat(self, stat_id: int) -> int:
        sid = int(stat_id)
        cur = int(self.allocated.get(sid, 0))
        if cur <= 0:
            return 0
        # refund сам эмитит unspentChanged
        self.refund(sid, cur)
        return cur


    def refund(self, stat_id: int, amount: int = 1) -> bool:
        sid = int(stat_id)
        amt = max(1, int(amount))
        cur = int(self.allocated.get(sid, 0))
        if cur <= 0:
            return False

        dec = min(cur, amt)
        self.allocated[sid] = cur - dec
        if self.allocated[sid] <= 0:
            self.allocated.pop(sid, None)

        # убираем последние вхождения sid из стека
        left = dec
        if left > 0 and self._stack:
            i = len(self._stack) - 1
            while i >= 0 and left > 0:
                if self._stack[i] == sid:
                    self._stack.pop(i)
                    left -= 1
                i -= 1

        self.unspentChanged.emit(self.unspent_points())
        return True

    def spend_all(self, stat_id: int) -> bool:
        u = self.unspent_points()
        if u <= 0:
            return False

        cap = self.remaining_capacity_for_stat(int(stat_id))
        if cap <= 0:
            return False

        return self.spend(int(stat_id), min(u, cap))

    def _reconcile_after_total_change(self) -> None:
        """Если total уменьшился, откатываем траты по стеку, пока не влезем в total."""
        def _spent() -> int:
            return sum(int(v) for v in (self.allocated or {}).values())

        while _spent() > int(self.total_points) and self._stack:
            sid = self._stack.pop()
            cur = int(self.allocated.get(sid, 0))
            if cur > 0:
                cur -= 1
                if cur <= 0:
                    self.allocated.pop(sid, None)
                else:
                    self.allocated[sid] = cur

class UnspentParamPointsWidget(QFrame):
    """
    Маленькая плашка:
      "Свободно: <зелёное число>"
    Перетаскивается по MainWindow мышью.
    """
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("unspent_param_points")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("""
            QFrame#unspent_param_points {
                background: transparent;
                border: none;
            }
            QLabel { background: transparent; color: #3b290c; }
        """)

        self.lbl = QLabel(self)
        f = self.lbl.font()
        f.setPointSizeF(9)
        f.setBold(True)
        self.lbl.setFont(f)
        self.lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.lbl.setTextFormat(Qt.RichText)

        self.set_points(0)

    def resizeEvent(self, e):
        self.lbl.setGeometry(10, 0, max(1, self.width() - 20), self.height())
        super().resizeEvent(e)

    def set_points(self, n: int) -> None:
        try:
            n = int(n)
        except Exception:
            n = 0
        # число зелёным, выравнивание слева — задано
        self.lbl.setText(f"<span style='color:#2fa85a'>{n}</span>")

def layout_unspent_param_points_widget(
    widget: QWidget,
    *,
    img_rect: QRect,
    scale: float,
    design_rect: tuple[int, int, int, int] | None = None,
) -> None:
    """
    Позиционирование (по умолчанию 1 раз).
    Если пользователь уже двигал — не трогаем.
    """
    if getattr(widget, "user_moved", False):
        return

    x0, y0, w0, h0 = design_rect or UNSPENT_PARAM_POINTS_RECT
    X = int(img_rect.x() + x0 * scale)
    Y = int(img_rect.y() + y0 * scale)
    W = max(1, int(w0 * scale))
    H = max(1, int(h0 * scale))
    widget.setGeometry(X, Y, W, H)

# ---------------------------------------------------------------------------
# 2) Математика: аккумулирование статов
# ---------------------------------------------------------------------------
class CharacteristicsMath:
    """
    Вся математика по подсчёту финальных статов персонажа.
    """

    def __init__(self, conn):
        self.conn = conn
        self.stat_defs: List[StatDef] = _load_stat_defs(conn)

        self.by_id: Dict[int, StatDef] = {s.id: s for s in self.stat_defs}
        self.by_code: Dict[str, StatDef] = {s.code: s for s in self.stat_defs if s.code}

        # <-- кэшируем очки за уровень
        self._stats_per_level: int = self._load_stats_per_level()

        # --- NEW: быстрый поиск Stat.Id по имени (из БД), и кэш инфы по классам ---
        self._class_info_cache: dict[int, dict[str, Any]] = {}
        self._stat_name_to_id: dict[str, int] = {}

        def _norm(s: str) -> str:
            s = str(s or "").strip().lower()
            return re.sub(r"[^0-9a-zа-яё]+", "", s, flags=re.IGNORECASE)

        self._norm_stat_name = _norm

        for sd in self.stat_defs:
            self._stat_name_to_id[_norm(sd.name)] = int(sd.id)
            if sd.progress_name:
                self._stat_name_to_id[_norm(sd.progress_name)] = int(sd.id)

    def _calc_formula15_avg_stacks(
            self,
            *,
            dot_apply_rate: float,
            seconds: float,
            max_stack: int,
    ) -> Dict[str, float]:
        """
        Отдельный спорный блок усреднения стаков DoT.
        Его потом можно будет заменить отдельно, не ломая остальной DPS.
        """
        try:
            rate = max(0.0, float(dot_apply_rate or 0.0))
        except Exception:
            rate = 0.0

        try:
            secs = max(0.0, float(seconds or 0.0))
        except Exception:
            secs = 0.0

        try:
            mstack = max(0, int(max_stack or 0))
        except Exception:
            mstack = 0

        if rate <= 0.0 or secs <= 0.0 or mstack <= 0:
            return {
                "h": 0.0,
                "AvgStacks": 0.0,
            }

        h = 1.0 - math.exp(-(rate * secs))

        avg_stacks = 0.0
        cur = float(h)
        for _ in range(mstack):
            avg_stacks += cur
            cur *= h

        return {
            "h": float(h),
            "AvgStacks": float(avg_stacks),
        }

    def _calc_formula15_payload(
            self,
            *,
            values_by_id: Mapping[int, float],
            equipment_rows: Iterable[Mapping[int, float] | Mapping[str, float]] = (),
            target_race_row: Mapping[str, Any] | None = None,
            target_element_row: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Считает DPS только для Stat.Id = 75.
        Здесь же сразу учитывается верхняя цель:
          - множитель по расе через Race.DefStat_Id
          - Monster_damage_modifier по выбранной приверженности существа
          - общий множитель по элементу цели через Stat.Id 61..66
        """
        conn = self.conn

        payload: Dict[str, Any] = {
            "Attack": 0.0,
            "CritRating": 0.0,
            "CritChancePercent": 0.0,
            "CritChance": 0.0,
            "CritPowerPercent": 0.0,
            "CritPower": 0.0,
            "CritAvg": 1.0,
            "AttackSpeedStat": 0.0,
            "AttackSpeedWeaponBase": 1.0,
            "AttacksPerSecond": 0.0,
            "DotTickSpeedPercent": 0.0,
            "DotTicksPerSecond": 1.0,
            "WeaponMode": "single_hit",
            "HitParts": [1.0],
            "ProcCapableHitsPerAttack": 1,
            "HitEventsPerSecond": 0.0,
            "HitMultiplier": 1.0,
            "HitMultipliers": [1.0],
            "HitElementIds": [None],
            "ExpectedHitDamage": [],
            "ExpectedHitDamageWithMultiplier": [],
            "ExpectedAttackDamage": 0.0,
            "ExpectedAttackDamageWithMultiplier": 0.0,
            "GlobalMultiplierRaw": 0.0,
            "GlobalMultiplier": 1.0,
            "DPS_hit": 0.0,
            "DoTs": [],
            "DPS_total": 0.0,
            "DebugItems": [],
            "DebugCards": [],
            "DebugDotEvents": [],
            "DebugDotSourcesById": {},
            "DebugDotSummary": {},
            "TargetRaceStatId": None,
            "TargetRaceRaw": 0.0,
            "TargetRaceMultiplier": 1.0,
            "TargetMonsterElementLevelId": None,
            "TargetMonsterElementId": None,
            "TargetWholeElementStatId": None,
            "TargetWholeElementRaw": 0.0,
            "TargetWholeElementMultiplier": 1.0,
            "TargetCommonMultiplier": 1.0,
            "TargetHitElementIds": [],
            "TargetHitMultiplierStatIds": [],
            "TargetHitDamageModifiers": [],
            "TargetDotDamageModifiers": [],
            "TargetMonsterDamageModifierMap": {},
            "BaseDPS_hit": 0.0,
            "BaseDPS_total": 0.0,
            "DPS_hit_before_common": 0.0,
            "DPS_total_before_common": 0.0,
        }

        if conn is None:
            return payload

        def _toi(v, d=0) -> int:
            try:
                return int(v)
            except Exception:
                try:
                    return int(float(str(v).strip()))
                except Exception:
                    return d

        def _tof(v, d=0.0) -> float:
            try:
                return float(v)
            except Exception:
                try:
                    return float(str(v).replace(",", ".").strip())
                except Exception:
                    return d

        raw_vals = _normalize_stats_mapping(values_by_id or {})
        raw_items = list(equipment_rows or ())

        def _normalize_equip_row(x) -> dict | None:
            if isinstance(x, dict):
                return x

            if isinstance(x, (tuple, list)):
                d: dict = {}
                if len(x) > 0:
                    d["_slot"] = x[0]
                if len(x) > 1:
                    d["Id"] = x[1]
                    d["Equipment_Id"] = x[1]
                if len(x) > 2:
                    d["__forge_level"] = x[2]
                if len(x) > 3:
                    d["TemplateId"] = x[3]
                if len(x) > 4:
                    d["ProtoId"] = x[4]
                if len(x) > 5:
                    d["_uuid"] = x[5]
                    d["InstanceGuid"] = x[5]
                if len(x) > 6:
                    d["_cards"] = x[6]
                return d

            return None

        norm_items: List[dict] = []
        for row in raw_items:
            d = _normalize_equip_row(row)
            if isinstance(d, dict):
                norm_items.append(d)

        _weapon_markers = (
            "weapon", "mainhand", "main_hand", "weapon1", "hand1", "primary",
            "right", "rhand", "right_hand",
            "оруж", "пра", "прав", "осн",
        )
        _offhand_markers = (
            "offhand", "off_hand", "secondhand", "second_hand", "weapon2", "hand2", "secondary",
            "shield", "left", "lhand", "left_hand",
            "лева", "лев", "втор", "щит",
        )
        _spear_markers = (
            "spear", "lance", "pike", "polearm", "halberd",
            "weapon3", "hand3", "thirdhand", "third_hand",
            "копь", "копье", "копьё", "пика", "алебард",
        )

        def _slot_kind(it: dict) -> str:
            slot_s = str(
                it.get("_slot")
                or it.get("Slot")
                or it.get("slot")
                or it.get("SlotKey")
                or it.get("slot_key")
                or ""
            ).strip().lower()

            if not slot_s:
                return ""

            if any(m in slot_s for m in _spear_markers):
                return "spear"
            if any(m in slot_s for m in _offhand_markers):
                return "offhand"
            if any(m in slot_s for m in _weapon_markers):
                return "weapon"
            return ""

        def _slot_debug_name(it: dict) -> str:
            return str(
                _slot_kind(it)
                or it.get("_slot")
                or it.get("Slot")
                or it.get("slot")
                or it.get("SlotKey")
                or it.get("slot_key")
                or ""
            ).strip().lower()

        def _equip_id(it: dict) -> int:
            for k in ("Equipment_Id", "Equip_Id", "TemplateId", "Template_Id", "Item_Id", "Id"):
                if k in it and it[k] not in (None, ""):
                    eid = _toi(it[k], 0)
                    if eid > 0:
                        return int(eid)
            return 0

        def _resolve_item_type_id(it: dict) -> int:
            tid = _resolve_type_id(it)
            if tid > 0:
                return int(tid)

            eid = _equip_id(it)
            if eid <= 0:
                return 0

            try:
                row = conn.execute(
                    "SELECT Type_Id FROM Equipment WHERE Id=? LIMIT 1",
                    (int(eid),),
                ).fetchone()
            except Exception:
                row = None

            if not row:
                return 0

            try:
                return _toi(row["Type_Id"] if hasattr(row, "keys") else row[0], 0)
            except Exception:
                return 0

        def _resolve_weapon_attack_speed(it: dict | None) -> float:
            if not isinstance(it, dict):
                return 1.0

            for k in ("AttackSpeed",):
                if k in it and it[k] not in (None, ""):
                    v = _tof(it[k], 1.0)
                    return v if abs(v) > 1e-12 else 1.0

            eid = _equip_id(it)
            if eid <= 0:
                return 1.0

            try:
                row = conn.execute(
                    "SELECT AttackSpeed FROM Equipment WHERE Id=? LIMIT 1",
                    (int(eid),),
                ).fetchone()
            except Exception:
                row = None

            if not row:
                return 1.0

            try:
                val = row["AttackSpeed"] if hasattr(row, "keys") else row[0]
                v = _tof(val, 1.0)
                return v if abs(v) > 1e-12 else 1.0
            except Exception:
                return 1.0

        equiptype_cols = {str(c).lower() for c in (_table_columns(conn, "EquipmentType") or [])}
        has_isdoublehit = "isdoublehit" in equiptype_cols
        equip_type_cache: Dict[int, Dict[str, Any]] = {}

        def _get_equip_type_info(type_id: int) -> Dict[str, Any]:
            tid = _toi(type_id, 0)
            if tid <= 0:
                return {
                    "IsSingleHandWeapon": None,
                    "IsDoubleHit": 0,
                }

            if tid in equip_type_cache:
                return dict(equip_type_cache[tid])

            info = {
                "IsSingleHandWeapon": None,
                "IsDoubleHit": 0,
            }

            try:
                if has_isdoublehit:
                    row = conn.execute(
                        """
                        SELECT IsSingleHandWeapon, IsDoubleHit
                        FROM EquipmentType
                        WHERE Id=?
                        LIMIT 1
                        """,
                        (int(tid),),
                    ).fetchone()
                else:
                    row = conn.execute(
                        """
                        SELECT IsSingleHandWeapon
                        FROM EquipmentType
                        WHERE Id=?
                        LIMIT 1
                        """,
                        (int(tid),),
                    ).fetchone()
            except Exception:
                row = None

            if row:
                try:
                    raw_1h = row["IsSingleHandWeapon"] if hasattr(row, "keys") else row[0]
                    if raw_1h is None:
                        info["IsSingleHandWeapon"] = False if _is_weapon_type_by_equipmenttype(conn, tid) else None
                    else:
                        info["IsSingleHandWeapon"] = bool(_toi(raw_1h, 0))
                except Exception:
                    info["IsSingleHandWeapon"] = None

                if has_isdoublehit:
                    try:
                        raw_dh = row["IsDoubleHit"] if hasattr(row, "keys") else row[1]
                        info["IsDoubleHit"] = _toi(raw_dh, 0)
                    except Exception:
                        info["IsDoubleHit"] = 0

            equip_type_cache[tid] = dict(info)
            return dict(info)

        state_id = _toi(get_active_state_id(), 0)

        filtered_items: List[dict] = []
        for it in norm_items:
            kind = _slot_kind(it)
            if state_id == 1 and kind == "spear":
                continue
            if state_id == 2 and kind in ("weapon", "offhand"):
                continue
            filtered_items.append(it)

        main_weapon: dict | None = None
        offhand_weapon: dict | None = None
        spear_weapon: dict | None = None

        for it in filtered_items:
            kind = _slot_kind(it)
            type_id = _resolve_item_type_id(it)
            is_weapon_type = bool(_is_weapon_type_by_equipmenttype(conn, int(type_id or 0)))

            if kind == "weapon" and is_weapon_type:
                main_weapon = it
            elif kind == "offhand" and is_weapon_type:
                offhand_weapon = it
            elif kind == "spear" and is_weapon_type:
                spear_weapon = it

        if state_id == 2 and spear_weapon is not None:
            main_weapon = spear_weapon
            offhand_weapon = None

        if main_weapon is None and spear_weapon is not None:
            main_weapon = spear_weapon

        if main_weapon is None and offhand_weapon is not None:
            main_weapon = offhand_weapon
            offhand_weapon = None

        main_type_id = _resolve_item_type_id(main_weapon or {})
        off_type_id = _resolve_item_type_id(offhand_weapon or {})

        main_info = _get_equip_type_info(main_type_id)
        off_info = _get_equip_type_info(off_type_id)

        dual_wield = bool(
            main_weapon is not None
            and offhand_weapon is not None
            and main_info.get("IsSingleHandWeapon") is True
            and off_info.get("IsSingleHandWeapon") is True
        )

        if dual_wield:
            weapon_mode = "dual_wield_1h"
            hit_parts = [1.0, 0.5]
            proc_hits_per_attack = 2
        else:
            if _toi(main_info.get("IsDoubleHit"), 0) == 1:
                weapon_mode = "two_handed_double_hit"
                hit_parts = [0.5, 0.5]
                proc_hits_per_attack = 2
            else:
                weapon_mode = "single_hit"
                hit_parts = [1.0]
                proc_hits_per_attack = 1

        payload["WeaponMode"] = weapon_mode
        payload["HitParts"] = list(hit_parts)
        payload["ProcCapableHitsPerAttack"] = int(proc_hits_per_attack)

        attack = _tof(raw_vals.get(10, 0.0), 0.0)
        attack_speed_stat = _tof(raw_vals.get(11, 0.0), 0.0)
        crit_rating = _tof(raw_vals.get(15, 0.0), 0.0)
        crit_power_percent = _tof(raw_vals.get(16, 0.0), 0.0)

        lvl = 1
        try:
            lvl = int(getattr(self, "_current_level", 1) or 1)
        except Exception:
            lvl = 1
        if lvl <= 0:
            lvl = 1

        crit_power_formula = float(crit_rating) * ((-0.6491 * float(lvl)) + 60.1007)
        if crit_power_formula > 0.0:
            crit_chance_percent = (1.0 - math.pow(0.999, crit_power_formula)) * 60.0
        else:
            crit_chance_percent = 0.0

        crit_chance_percent = max(0.0, min(60.0, float(crit_chance_percent)))
        crit_chance = crit_chance_percent / 100.0
        crit_power = float(crit_power_percent) / 100.0
        crit_avg = (crit_chance * crit_power) + (1.0 - crit_chance)

        attack_sec = _resolve_weapon_attack_speed(main_weapon)
        attacks_per_second = (float(attack_speed_stat) * float(attack_sec)) / 100.0
        dot_tick_speed_percent = float(attack_speed_stat) / 10.0
        dot_ticks_per_second = 1.0 + (float(dot_tick_speed_percent) / 100.0)
        hit_events_per_second = float(attacks_per_second) * float(proc_hits_per_attack)

        global_multiplier_raw = _tof(raw_vals.get(80, 0.0), 0.0)
        global_multiplier = (float(global_multiplier_raw) / 100.0) if float(global_multiplier_raw) > 0.0 else 1.0

        payload["Attack"] = float(attack)
        payload["CritRating"] = float(crit_rating)
        payload["CritChancePercent"] = float(crit_chance_percent)
        payload["CritChance"] = float(crit_chance)
        payload["CritPowerPercent"] = float(crit_power_percent)
        payload["CritPower"] = float(crit_power)
        payload["CritAvg"] = float(crit_avg)
        payload["AttackSpeedStat"] = float(attack_speed_stat)
        payload["AttackSpeedWeaponBase"] = float(attack_sec)
        payload["AttacksPerSecond"] = float(attacks_per_second)
        payload["DotTickSpeedPercent"] = float(dot_tick_speed_percent)
        payload["DotTicksPerSecond"] = float(dot_ticks_per_second)
        payload["HitEventsPerSecond"] = float(hit_events_per_second)
        payload["GlobalMultiplierRaw"] = float(global_multiplier_raw)
        payload["GlobalMultiplier"] = float(global_multiplier)

        element_damage_stat_by_element: Dict[int, int] = {}
        whole_target_stat_by_element: Dict[int, int] = {}

        try:
            rows = conn.execute(
                """
                SELECT Id, Element_Id
                FROM Stat
                WHERE Id IN (25, 26, 27, 28, 29, 30, 61, 62, 63, 64, 65, 66)
                """
            ).fetchall()
        except Exception:
            rows = []

        for r in rows or []:
            try:
                sid = _toi(r["Id"] if hasattr(r, "keys") else r[0], 0)
                eid = _toi(r["Element_Id"] if hasattr(r, "keys") else r[1], 0)
            except Exception:
                continue
            if sid > 0 and eid > 0:
                if 25 <= sid <= 30:
                    element_damage_stat_by_element[int(eid)] = int(sid)
                elif 61 <= sid <= 66:
                    whole_target_stat_by_element[int(eid)] = int(sid)

        def _element_multiplier(element_id: int | None) -> float:
            eid = _toi(element_id, 0)
            if eid <= 0:
                return 1.0
            sid = element_damage_stat_by_element.get(int(eid))
            if not sid:
                return 1.0
            raw = _tof(raw_vals.get(int(sid), 0.0), 0.0)
            return (float(raw) / 100.0) if float(raw) > 0.0 else 1.0

        def _iter_card_entries(it: dict) -> List[Any]:
            cards_raw = it.get("_cards") or it.get("cards") or it.get("Cards")
            if isinstance(cards_raw, dict):
                return list(cards_raw.values())
            if isinstance(cards_raw, (list, tuple)):
                return list(cards_raw)
            return []

        equipped_card_ids: List[int] = []
        for it in filtered_items:
            for c in _iter_card_entries(it):
                cid = _resolve_card_id_from_entry(c)
                if cid > 0:
                    equipped_card_ids.append(int(cid))

        equipped_card_set = set(equipped_card_ids)

        equipped_card_counts: Dict[int, int] = {}
        for cid in equipped_card_ids:
            equipped_card_counts[int(cid)] = int(equipped_card_counts.get(int(cid), 0)) + 1

        equipped_set_counts: Dict[int, int] = {}
        for cid in equipped_card_ids:
            sid = _get_card_set_id(conn, int(cid))
            if sid > 0:
                equipped_set_counts[int(sid)] = int(equipped_set_counts.get(int(sid), 0)) + 1

        bt_cols = {str(c).lower() for c in (_table_columns(conn, "BonusType") or [])}
        has_bt_dot_id = "dot_id" in bt_cols
        has_bt_card_dot_chance = "carddotchance" in bt_cols

        bonus_type_dot_meta_cache: Dict[int, Dict[str, Any]] = {}
        dot_row_cache: Dict[int, Dict[str, Any]] = {}
        equip_type_bonus_cache: Dict[int, List[Tuple[int, float]]] = {}
        stamp_variant_resolve_cache: Dict[Tuple[int, int], int] = {}

        def _load_bonus_type_dot_meta(bt_id: int) -> Dict[str, Any]:
            ibt = _toi(bt_id, 0)
            if ibt <= 0:
                return {"Dot_Id": 0, "CardDotChance": None}

            if ibt in bonus_type_dot_meta_cache:
                return dict(bonus_type_dot_meta_cache[ibt])

            meta = {"Dot_Id": 0, "CardDotChance": None}

            cols_to_select: List[str] = []
            if has_bt_dot_id:
                cols_to_select.append("Dot_Id")
            if has_bt_card_dot_chance:
                cols_to_select.append("CardDotChance")

            if not cols_to_select:
                bonus_type_dot_meta_cache[ibt] = dict(meta)
                return dict(meta)

            try:
                sql = f'SELECT {", ".join(cols_to_select)} FROM "BonusType" WHERE Id=? LIMIT 1'
                row = conn.execute(sql, (int(ibt),)).fetchone()
            except Exception:
                row = None

            if row:
                try:
                    if has_bt_dot_id:
                        meta["Dot_Id"] = _toi(
                            row["Dot_Id"] if hasattr(row, "keys") else row[cols_to_select.index("Dot_Id")], 0)

                    if has_bt_card_dot_chance:
                        raw_cdc = row["CardDotChance"] if hasattr(row, "keys") else row[
                            cols_to_select.index("CardDotChance")]
                        meta["CardDotChance"] = None if raw_cdc is None else float(raw_cdc)
                except Exception:
                    meta["Dot_Id"] = 0
                    meta["CardDotChance"] = None

            bonus_type_dot_meta_cache[ibt] = dict(meta)
            return dict(meta)

        def _load_dot_row(dot_id: int) -> Dict[str, Any] | None:
            did = _toi(dot_id, 0)
            if did <= 0:
                return None

            if did in dot_row_cache:
                return dict(dot_row_cache[did])

            try:
                row = conn.execute(
                    """
                    SELECT Id, Name, Stat_Id, MinValue, MaxValue, Seconds, MaxStack, Element_Id
                    FROM Dot
                    WHERE Id=?
                    LIMIT 1
                    """,
                    (int(did),),
                ).fetchone()
            except Exception:
                row = None

            if not row:
                return None

            out = {
                "Id": _toi(row["Id"] if hasattr(row, "keys") else row[0], 0),
                "Name": str((row["Name"] if hasattr(row, "keys") else row[1]) or ""),
                "Stat_Id": _toi(row["Stat_Id"] if hasattr(row, "keys") else row[2], 0),
                "MinValue": _tof(row["MinValue"] if hasattr(row, "keys") else row[3], 0.0),
                "MaxValue": _tof(row["MaxValue"] if hasattr(row, "keys") else row[4], 0.0),
                "Seconds": _tof(row["Seconds"] if hasattr(row, "keys") else row[5], 0.0),
                "MaxStack": _toi(row["MaxStack"] if hasattr(row, "keys") else row[6], 0),
                "Element_Id": _toi(row["Element_Id"] if hasattr(row, "keys") else row[7], 0),
            }

            dot_row_cache[did] = dict(out)
            return dict(out)

        def _eval_card_bonus_conditions(br: Dict[str, Any]) -> Tuple[bool, bool, int]:
            req = _toi(br.get("RequiredCard_Id"), 0)
            neg = _toi(br.get("NegateCard_Id"), 0)
            mul_card = _toi(br.get("MultiplyEffectCard_Id"), 0)
            req_set_id = _toi(br.get("RequiredSet_Id"), 0)
            req_set_size = _toi(br.get("RequiredSetSize"), 0)

            if req > 0 and req not in equipped_card_set:
                return (False, False, 1)

            if req_set_size > 0:
                if req_set_id <= 0:
                    return (False, False, 1)
                have = int(equipped_set_counts.get(int(req_set_id), 0))
                if have < int(req_set_size):
                    return (False, False, 1)

            effect_mult = 1
            if mul_card > 0:
                cnt_mul = int(equipped_card_counts.get(int(mul_card), 0))
                effect_mult = 2 if cnt_mul >= 2 else 1

            apply_abs = False
            if neg > 0:
                cnt_neg = int(equipped_card_counts.get(int(neg), 0))
                if cnt_neg == 1:
                    return (False, False, 1)
                if cnt_neg >= 2:
                    apply_abs = True

            return (True, apply_abs, int(effect_mult))

        def _first_non_zero(var_map: Mapping[int, float] | None) -> float:
            if not isinstance(var_map, Mapping):
                return 0.0
            for k in sorted(var_map.keys()):
                vv = _tof(var_map.get(k), 0.0)
                if abs(vv) > 1e-12:
                    return float(vv)
            return 0.0

        def _resolve_stamp_variant_id_local(it: dict) -> int:
            def _valid_variant(vid: int) -> bool:
                if vid <= 0:
                    return False
                try:
                    row = conn.execute("SELECT 1 FROM StampVariant WHERE Id=? LIMIT 1", (int(vid),)).fetchone()
                    return bool(row)
                except Exception:
                    return False

            def _pick_int(d: dict, keys: Tuple[str, ...]) -> int:
                for k in keys:
                    if k in d and d[k] not in (None, ""):
                        try:
                            v = int(float(str(d[k]).strip()))
                            if v:
                                return v
                        except Exception:
                            pass
                return 0

            for k in ("StampVariant_Id", "StampVariantId", "_stamp_variant_id"):
                vid = _toi(it.get(k), 0)
                if _valid_variant(vid):
                    return int(vid)

            stamp = it.get("_stamp") or it.get("stamp") or it.get("Stamp")
            if isinstance(stamp, dict):
                for k in ("StampVariant_Id", "StampVariantId", "Variant_Id", "VariantId", "_stamp_variant_id"):
                    vid = _toi(stamp.get(k), 0)
                    if _valid_variant(vid):
                        return int(vid)

            stamp_id = _pick_int(it, ("StampId", "Stamp_Id", "StampID", "stamp_id"))
            color_id = _pick_int(it, ("ColorId", "Color_Id", "StampColorId", "StampColor_Id", "stamp_color_id"))

            if isinstance(stamp, dict):
                if stamp_id <= 0:
                    stamp_id = _pick_int(stamp, ("StampId", "Stamp_Id", "Id", "stamp_id"))
                if color_id <= 0:
                    color_id = _pick_int(stamp,
                                         ("ColorId", "Color_Id", "StampColorId", "StampColor_Id", "stamp_color_id"))

            cache_key = (int(stamp_id), int(color_id))
            if cache_key in stamp_variant_resolve_cache:
                return int(stamp_variant_resolve_cache[cache_key])

            if stamp_id <= 0:
                stamp_variant_resolve_cache[cache_key] = 0
                return 0

            try:
                if color_id > 0:
                    row = conn.execute(
                        "SELECT Id FROM StampVariant WHERE Stamp_Id=? AND Color_Id=? LIMIT 1",
                        (int(stamp_id), int(color_id)),
                    ).fetchone()
                    if row:
                        vid = _toi(row["Id"] if hasattr(row, "keys") else row[0], 0)
                        stamp_variant_resolve_cache[cache_key] = int(vid)
                        return int(vid)

                row = conn.execute(
                    "SELECT Id FROM StampVariant WHERE Stamp_Id=? ORDER BY Color_Id DESC LIMIT 1",
                    (int(stamp_id),),
                ).fetchone()
                if row:
                    vid = _toi(row["Id"] if hasattr(row, "keys") else row[0], 0)
                    stamp_variant_resolve_cache[cache_key] = int(vid)
                    return int(vid)
            except Exception:
                pass

            stamp_variant_resolve_cache[cache_key] = 0
            return 0

        def _load_equipment_type_bonuses_local(equip_type_id: int) -> List[Tuple[int, float]]:
            etid = _toi(equip_type_id, 0)
            if etid <= 0:
                return []
            if etid in equip_type_bonus_cache:
                return list(equip_type_bonus_cache[etid])

            if not _table_exists(conn, "EquipmentTypeBonus"):
                equip_type_bonus_cache[etid] = []
                return []

            try:
                rows = conn.execute(
                    "SELECT Type_Id, Value FROM EquipmentTypeBonus WHERE EquipmentType_Id=? ORDER BY Id",
                    (int(etid),),
                ).fetchall()
            except Exception:
                rows = []

            out: List[Tuple[int, float]] = []
            for r in rows or []:
                try:
                    if hasattr(r, "keys"):
                        bt = _toi(r["Type_Id"], 0)
                        val = _tof(r["Value"], 0.0)
                    else:
                        bt = _toi(r[0], 0)
                        val = _tof(r[1], 0.0)
                except Exception:
                    continue

                if bt > 0 and abs(val) > 1e-12:
                    out.append((int(bt), float(val)))

            equip_type_bonus_cache[etid] = list(out)
            return list(out)

        dot_sources_by_id: Dict[int, List[Dict[str, Any]]] = {}
        main_hit_element_id: int | None = None
        off_hit_element_id: int | None = None
        single_dot_bonus_seen: set[int] = set()
        debug_dot_events: List[Dict[str, Any]] = []

        try:
            from PySide6.QtWidgets import QApplication
            _app = QApplication.instance()
        except Exception:
            _app = None

        active_buff_ids: set[int] = set()
        try:
            raw_buff_ids = _app.property("player_buff_ids") if _app is not None else None
            if isinstance(raw_buff_ids, (list, tuple, set)):
                for x in raw_buff_ids:
                    bid = _toi(x, 0)
                    if bid > 0:
                        active_buff_ids.add(int(bid))
        except Exception:
            active_buff_ids = set()

        def _push_debug(ev: Dict[str, Any]) -> None:
            debug_dot_events.append(dict(ev))

        def _accept_source(
                *,
                source_kind: str,
                slot_kind: str,
                bt_id: int,
                dot_row: Dict[str, Any],
                chance_percent: float,
                chance_source: str,
                extra: Optional[Dict[str, Any]] = None,
        ) -> None:
            nonlocal main_hit_element_id, off_hit_element_id

            src = {
                "SourceKind": str(source_kind),
                "SlotKind": str(slot_kind),
                "BonusTypeId": int(bt_id),
                "DotId": int(_toi(dot_row.get("Id"), 0)),
                "DotName": str(dot_row.get("Name") or ""),
                "ElementId": _toi(dot_row.get("Element_Id"), 0),
                "ChancePercent": float(chance_percent),
                "ChanceFraction": float(chance_percent) / 100.0,
                "ChanceSource": str(chance_source),
            }
            if isinstance(extra, dict):
                src.update(dict(extra))

            dot_sources_by_id.setdefault(int(src["DotId"]), []).append(src)

            src_element_id = _toi(src.get("ElementId"), 0)
            if str(source_kind) == "card" and src_element_id > 0:
                if slot_kind in ("weapon", "spear") and main_hit_element_id is None:
                    main_hit_element_id = int(src_element_id)
                elif slot_kind == "offhand" and off_hit_element_id is None:
                    off_hit_element_id = int(src_element_id)

        for _it in filtered_items:
            try:
                payload["DebugItems"].append({
                    "slot": _slot_debug_name(_it),
                    "equip_id": _equip_id(_it),
                    "type_id": _resolve_item_type_id(_it),
                    "is_single_hand": _get_is_single_hand_weapon(conn, _resolve_item_type_id(_it)),
                })
            except Exception:
                pass

        try:
            payload["DebugCards"] = [int(x) for x in equipped_card_ids]
        except Exception:
            payload["DebugCards"] = []

        # ------------------------- CARD DOT SOURCES -------------------------
        for it in filtered_items:
            item_type_id = _resolve_item_type_id(it)
            is_single_hand = _get_is_single_hand_weapon(conn, item_type_id)
            slot_kind = _slot_kind(it)

            for c in _iter_card_entries(it):
                card_id = _resolve_card_id_from_entry(c)
                if card_id <= 0:
                    _push_debug({
                        "stage": "card_entry",
                        "source_kind": "card",
                        "slot": _slot_debug_name(it),
                        "reason": "card_id<=0",
                        "raw": repr(c),
                    })
                    continue

                bonus_rows = _load_card_bonus_rows(conn, int(card_id))
                if not bonus_rows:
                    _push_debug({
                        "stage": "card_bonus_rows",
                        "source_kind": "card",
                        "slot": _slot_debug_name(it),
                        "card_id": int(card_id),
                        "reason": "no_bonus_rows",
                    })
                    continue

                for br in bonus_rows:
                    cbid = _toi(br.get("CBId"), 0)
                    bt_id = _toi(br.get("Type_Id"), 0)

                    dbg_row: Dict[str, Any] = {
                        "stage": "bonus_row",
                        "source_kind": "card",
                        "slot": _slot_debug_name(it),
                        "card_id": int(card_id),
                        "cbid": int(cbid),
                        "bt_id": int(bt_id),
                        "item_type_id": int(item_type_id or 0),
                        "is_single_hand": None if is_single_hand is None else bool(is_single_hand),
                    }

                    if cbid <= 0 or bt_id <= 0:
                        dbg_row["reason"] = "bad_cbid_or_bt"
                        _push_debug(dbg_row)
                        continue

                    ok, apply_abs, effect_mult = _eval_card_bonus_conditions(br)
                    dbg_row["conditions_ok"] = bool(ok)
                    dbg_row["apply_abs"] = bool(apply_abs)
                    dbg_row["effect_mult"] = int(effect_mult)

                    if not ok:
                        dbg_row["reason"] = "card_bonus_conditions_failed"
                        _push_debug(dbg_row)
                        continue

                    dot_meta = _load_bonus_type_dot_meta(int(bt_id))
                    dot_id = _toi(dot_meta.get("Dot_Id"), 0)
                    dbg_row["dot_id"] = int(dot_id)
                    dbg_row["card_dot_chance"] = dot_meta.get("CardDotChance", None)

                    if dot_id <= 0:
                        dbg_row["reason"] = "bonus_type_has_no_dot"
                        _push_debug(dbg_row)
                        continue

                    var_map = _load_card_bonus_vars_with_conditions(
                        conn,
                        int(cbid),
                        item_type_id=int(item_type_id or 0),
                        is_single_hand=is_single_hand,
                    )
                    dbg_row["var_map"] = dict(var_map or {})

                    first_non_zero = _first_non_zero(var_map)
                    dbg_row["first_non_zero"] = float(first_non_zero)

                    if dot_meta.get("CardDotChance") is not None:
                        chance_percent = _tof(dot_meta.get("CardDotChance"), 0.0)
                        dbg_row["chance_source"] = "CardDotChance"
                    else:
                        chance_percent = float(first_non_zero)
                        dbg_row["chance_source"] = "var_map"

                    dbg_row["chance_percent_before_mods"] = float(chance_percent)

                    if apply_abs:
                        chance_percent = abs(float(chance_percent))
                    if effect_mult != 1:
                        chance_percent = float(chance_percent) * float(effect_mult)

                    dbg_row["chance_percent_after_mods"] = float(chance_percent)

                    if chance_percent <= 0.0:
                        dbg_row["reason"] = "chance_percent<=0"
                        _push_debug(dbg_row)
                        continue

                    if not _take_bonus_type_once(conn, single_dot_bonus_seen, int(bt_id)):
                        dbg_row["reason"] = "take_bonus_type_once_blocked"
                        _push_debug(dbg_row)
                        continue

                    dot_row = _load_dot_row(int(dot_id))
                    if not dot_row:
                        dbg_row["reason"] = "dot_row_not_found"
                        _push_debug(dbg_row)
                        continue

                    dbg_row["reason"] = "accepted"
                    dbg_row["dot_name"] = str(dot_row.get("Name") or "")
                    dbg_row["dot_element_id"] = _toi(dot_row.get("Element_Id"), 0)

                    _accept_source(
                        source_kind="card",
                        slot_kind=str(slot_kind),
                        bt_id=int(bt_id),
                        dot_row=dot_row,
                        chance_percent=float(chance_percent),
                        chance_source=str(dbg_row["chance_source"]),
                        extra={
                            "CardId": int(card_id),
                            "CardBonusId": int(cbid),
                        },
                    )
                    _push_debug(dbg_row)

        # ------------------------- STAMP DOT SOURCES -------------------------
        for it in filtered_items:
            slot_kind = _slot_kind(it)
            eid = _equip_id(it)
            if eid <= 0:
                continue

            stamp_variant_id = _resolve_stamp_variant_id_local(it)
            if stamp_variant_id <= 0:
                continue

            internal_lvl = _get_equipment_internal_level(conn, int(eid), fallback=1)

            try:
                rows = conn.execute(
                    """
                    SELECT Type_Id, QualityValue
                    FROM StampVariantBonus
                    WHERE StampVariant_Id=?
                    ORDER BY OrderIndex, rowid
                    """,
                    (int(stamp_variant_id),),
                ).fetchall()
            except Exception:
                rows = []

            for r in rows or []:
                if hasattr(r, "keys"):
                    bt_id = _toi(r["Type_Id"], 0)
                    base_q = _tof(r["QualityValue"], 0.0)
                else:
                    bt_id = _toi(r[0], 0)
                    base_q = _tof(r[1], 0.0)

                dbg_row: Dict[str, Any] = {
                    "stage": "stamp_bonus_row",
                    "source_kind": "stamp",
                    "slot": _slot_debug_name(it),
                    "equip_id": int(eid),
                    "stamp_variant_id": int(stamp_variant_id),
                    "bt_id": int(bt_id),
                    "base_quality": float(base_q),
                    "internal_level": int(internal_lvl),
                }

                if bt_id <= 0 or abs(base_q) <= 1e-12:
                    dbg_row["reason"] = "bad_bt_or_quality"
                    _push_debug(dbg_row)
                    continue

                dot_meta = _load_bonus_type_dot_meta(int(bt_id))
                dot_id = _toi(dot_meta.get("Dot_Id"), 0)
                dbg_row["dot_id"] = int(dot_id)

                if dot_id <= 0:
                    dbg_row["reason"] = "bonus_type_has_no_dot"
                    _push_debug(dbg_row)
                    continue

                mn, mx = _get_bonus_type_coefs(conn, int(bt_id))
                scaled = _calc_stamp_scaled_value(
                    base_value=float(base_q),
                    min_coef=float(mn),
                    max_coef=float(mx),
                    internal_level=int(internal_lvl),
                    max_level=60.0,
                )
                chance_percent = float(scaled)

                dbg_row["chance_source"] = "stamp_scaled_quality"
                dbg_row["chance_percent_before_mods"] = float(chance_percent)
                dbg_row["chance_percent_after_mods"] = float(chance_percent)

                if chance_percent <= 0.0:
                    dbg_row["reason"] = "chance_percent<=0"
                    _push_debug(dbg_row)
                    continue

                if not _take_bonus_type_once(conn, single_dot_bonus_seen, int(bt_id)):
                    dbg_row["reason"] = "take_bonus_type_once_blocked"
                    _push_debug(dbg_row)
                    continue

                dot_row = _load_dot_row(int(dot_id))
                if not dot_row:
                    dbg_row["reason"] = "dot_row_not_found"
                    _push_debug(dbg_row)
                    continue

                dbg_row["reason"] = "accepted"
                dbg_row["dot_name"] = str(dot_row.get("Name") or "")
                dbg_row["dot_element_id"] = _toi(dot_row.get("Element_Id"), 0)

                _accept_source(
                    source_kind="stamp",
                    slot_kind=str(slot_kind),
                    bt_id=int(bt_id),
                    dot_row=dot_row,
                    chance_percent=float(chance_percent),
                    chance_source="stamp_scaled_quality",
                    extra={
                        "EquipId": int(eid),
                        "StampVariantId": int(stamp_variant_id),
                    },
                )
                _push_debug(dbg_row)

        # ------------------------- EQUIPMENT BONUS DOT SOURCES -------------------------
        equipbonus_cols = {str(c).lower() for c in (_table_columns(conn, "EquipmentBonus") or [])}
        equipbonus_has_activate = "activate" in equipbonus_cols
        equipbonus_has_buff_condition = "buffcondition_id" in equipbonus_cols

        for it in filtered_items:
            eid = _equip_id(it)
            if eid <= 0:
                continue

            slot_kind = _slot_kind(it)

            try:
                if equipbonus_has_activate and equipbonus_has_buff_condition:
                    bonus_rows = conn.execute(
                        """
                        SELECT Id, Type_Id, Activate, BuffCondition_Id
                        FROM EquipmentBonus
                        WHERE Equipment_Id=?
                        ORDER BY OrderIndex
                        """,
                        (int(eid),),
                    ).fetchall()
                elif equipbonus_has_activate:
                    bonus_rows = conn.execute(
                        """
                        SELECT Id, Type_Id, Activate
                        FROM EquipmentBonus
                        WHERE Equipment_Id=?
                        ORDER BY OrderIndex
                        """,
                        (int(eid),),
                    ).fetchall()
                elif equipbonus_has_buff_condition:
                    bonus_rows = conn.execute(
                        """
                        SELECT Id, Type_Id, BuffCondition_Id
                        FROM EquipmentBonus
                        WHERE Equipment_Id=?
                        ORDER BY OrderIndex
                        """,
                        (int(eid),),
                    ).fetchall()
                else:
                    bonus_rows = conn.execute(
                        """
                        SELECT Id, Type_Id
                        FROM EquipmentBonus
                        WHERE Equipment_Id=?
                        ORDER BY OrderIndex
                        """,
                        (int(eid),),
                    ).fetchall()
            except Exception:
                bonus_rows = []

            for br in bonus_rows or []:
                if hasattr(br, "keys"):
                    bonus_id = _toi(br["Id"], 0)
                    bt_id = _toi(br["Type_Id"], 0)
                    act = br["Activate"] if equipbonus_has_activate else None
                    buff_cond_id = _toi(br["BuffCondition_Id"], 0) if equipbonus_has_buff_condition else 0
                else:
                    bonus_id = _toi(br[0], 0)
                    bt_id = _toi(br[1], 0)
                    pos = 2
                    act = None
                    buff_cond_id = 0
                    if equipbonus_has_activate:
                        act = br[pos] if len(br) > pos else None
                        pos += 1
                    if equipbonus_has_buff_condition:
                        buff_cond_id = _toi(br[pos], 0) if len(br) > pos else 0

                dbg_row: Dict[str, Any] = {
                    "stage": "equip_bonus_row",
                    "source_kind": "equip_bonus",
                    "slot": _slot_debug_name(it),
                    "equip_id": int(eid),
                    "bonus_id": int(bonus_id),
                    "bt_id": int(bt_id),
                }

                if bonus_id <= 0 or bt_id <= 0:
                    dbg_row["reason"] = "bad_bonus_id_or_bt"
                    _push_debug(dbg_row)
                    continue

                if buff_cond_id > 0 and buff_cond_id in active_buff_ids:
                    dbg_row["reason"] = "blocked_by_active_buff_condition"
                    dbg_row["buff_condition_id"] = int(buff_cond_id)
                    _push_debug(dbg_row)
                    continue

                if equipbonus_has_activate and act is not None:
                    if not bool(it.get("_activate_checked", False)):
                        dbg_row["reason"] = "activate_checkbox_off"
                        _push_debug(dbg_row)
                        continue
                    if _toi(act, 0) != 1:
                        dbg_row["reason"] = "activate_flag_not_one"
                        _push_debug(dbg_row)
                        continue

                dot_meta = _load_bonus_type_dot_meta(int(bt_id))
                dot_id = _toi(dot_meta.get("Dot_Id"), 0)
                dbg_row["dot_id"] = int(dot_id)

                if dot_id <= 0:
                    dbg_row["reason"] = "bonus_type_has_no_dot"
                    _push_debug(dbg_row)
                    continue

                try:
                    var_rows = conn.execute(
                        """
                        SELECT "Index", Value
                        FROM EquipmentBonusVariable
                        WHERE EquipmentBonus_Id=?
                        ORDER BY "Index"
                        """,
                        (int(bonus_id),),
                    ).fetchall()
                except Exception:
                    var_rows = []

                var_map: Dict[int, float] = {}
                for vr in var_rows or []:
                    if hasattr(vr, "keys"):
                        idx = _toi(vr["Index"], 0)
                        val = _tof(vr["Value"], 0.0)
                    else:
                        idx = _toi(vr[0], 0)
                        val = _tof(vr[1], 0.0)
                    var_map[int(idx)] = float(val)

                dbg_row["var_map"] = dict(var_map or {})

                chance_percent = float(_first_non_zero(var_map))
                dbg_row["chance_source"] = "var_map"
                dbg_row["chance_percent_before_mods"] = float(chance_percent)
                dbg_row["chance_percent_after_mods"] = float(chance_percent)

                if chance_percent <= 0.0:
                    dbg_row["reason"] = "chance_percent<=0"
                    _push_debug(dbg_row)
                    continue

                if not _take_bonus_type_once(conn, single_dot_bonus_seen, int(bt_id)):
                    dbg_row["reason"] = "take_bonus_type_once_blocked"
                    _push_debug(dbg_row)
                    continue

                dot_row = _load_dot_row(int(dot_id))
                if not dot_row:
                    dbg_row["reason"] = "dot_row_not_found"
                    _push_debug(dbg_row)
                    continue

                dbg_row["reason"] = "accepted"
                dbg_row["dot_name"] = str(dot_row.get("Name") or "")
                dbg_row["dot_element_id"] = _toi(dot_row.get("Element_Id"), 0)

                _accept_source(
                    source_kind="equip_bonus",
                    slot_kind=str(slot_kind),
                    bt_id=int(bt_id),
                    dot_row=dot_row,
                    chance_percent=float(chance_percent),
                    chance_source="var_map",
                    extra={
                        "EquipId": int(eid),
                        "EquipmentBonusId": int(bonus_id),
                    },
                )
                _push_debug(dbg_row)

        # ------------------------- EQUIPMENT TYPE BONUS DOT SOURCES -------------------------
        for it in filtered_items:
            slot_kind = _slot_kind(it)
            type_id = _resolve_item_type_id(it)
            if type_id <= 0:
                continue

            for bt_id, val in _load_equipment_type_bonuses_local(int(type_id)):
                dbg_row: Dict[str, Any] = {
                    "stage": "equip_type_bonus_row",
                    "source_kind": "equip_type_bonus",
                    "slot": _slot_debug_name(it),
                    "type_id": int(type_id),
                    "bt_id": int(bt_id),
                    "value": float(val),
                }

                if bt_id <= 0 or abs(val) <= 1e-12:
                    dbg_row["reason"] = "bad_bt_or_value"
                    _push_debug(dbg_row)
                    continue

                dot_meta = _load_bonus_type_dot_meta(int(bt_id))
                dot_id = _toi(dot_meta.get("Dot_Id"), 0)
                dbg_row["dot_id"] = int(dot_id)

                if dot_id <= 0:
                    dbg_row["reason"] = "bonus_type_has_no_dot"
                    _push_debug(dbg_row)
                    continue

                chance_percent = float(val)
                dbg_row["chance_source"] = "EquipmentTypeBonus.Value"
                dbg_row["chance_percent_before_mods"] = float(chance_percent)
                dbg_row["chance_percent_after_mods"] = float(chance_percent)

                if chance_percent <= 0.0:
                    dbg_row["reason"] = "chance_percent<=0"
                    _push_debug(dbg_row)
                    continue

                if not _take_bonus_type_once(conn, single_dot_bonus_seen, int(bt_id)):
                    dbg_row["reason"] = "take_bonus_type_once_blocked"
                    _push_debug(dbg_row)
                    continue

                dot_row = _load_dot_row(int(dot_id))
                if not dot_row:
                    dbg_row["reason"] = "dot_row_not_found"
                    _push_debug(dbg_row)
                    continue

                dbg_row["reason"] = "accepted"
                dbg_row["dot_name"] = str(dot_row.get("Name") or "")
                dbg_row["dot_element_id"] = _toi(dot_row.get("Element_Id"), 0)

                _accept_source(
                    source_kind="equip_type_bonus",
                    slot_kind=str(slot_kind),
                    bt_id=int(bt_id),
                    dot_row=dot_row,
                    chance_percent=float(chance_percent),
                    chance_source="EquipmentTypeBonus.Value",
                    extra={
                        "EquipmentTypeId": int(type_id),
                    },
                )
                _push_debug(dbg_row)

        if dual_wield:
            hit_element_ids = [
                int(main_hit_element_id) if main_hit_element_id else None,
                int(off_hit_element_id) if off_hit_element_id else None,
            ]
        else:
            hit_element_ids = [int(main_hit_element_id) if main_hit_element_id else None for _ in hit_parts]

        # страховка: если элемент обычных hit-атак не нашёлся через dot-source,
        # пробуем добрать напрямую из экипировки
        resolved_hit_element_ids = self._resolve_formula15_hit_element_ids_from_equipment(
            payload={"HitElementIds": hit_element_ids},
            equipment_rows=equipment_rows,
        )
        if resolved_hit_element_ids and any(x is not None for x in resolved_hit_element_ids):
            hit_element_ids = list(resolved_hit_element_ids)

        hit_multipliers: List[float] = [_element_multiplier(eid) for eid in hit_element_ids]

        expected_hit_damage: List[float] = []
        expected_hit_damage_with_multiplier: List[float] = []

        for idx, hit_part in enumerate(hit_parts):
            raw_hit = float(attack) * float(hit_part) * float(crit_avg)
            expected_hit_damage.append(float(raw_hit))

            mul = hit_multipliers[idx] if idx < len(hit_multipliers) else 1.0
            expected_hit_damage_with_multiplier.append(float(raw_hit) * float(mul))

        expected_attack_damage = sum(expected_hit_damage)
        expected_attack_damage_with_multiplier = sum(expected_hit_damage_with_multiplier)

        payload["HitElementIds"] = list(hit_element_ids)
        payload["HitMultiplier"] = float(hit_multipliers[0]) if len(hit_multipliers) == 1 else None
        payload["HitMultipliers"] = list(hit_multipliers)
        payload["ExpectedHitDamage"] = list(expected_hit_damage)
        payload["ExpectedHitDamageWithMultiplier"] = list(expected_hit_damage_with_multiplier)
        payload["ExpectedAttackDamage"] = float(expected_attack_damage)
        payload["ExpectedAttackDamageWithMultiplier"] = float(expected_attack_damage_with_multiplier)

        # ---------------- TARGET ----------------
        race_row = dict(target_race_row or {}) if isinstance(target_race_row, Mapping) else {}
        elem_row = dict(target_element_row or {}) if isinstance(target_element_row, Mapping) else {}

        race_stat_id = _toi(race_row.get("DefStat_Id"), 0)
        race_raw = 0.0
        race_multiplier = 1.0
        if race_stat_id > 0:
            race_raw = _tof(raw_vals.get(int(race_stat_id), 0.0), 0.0)
            if race_raw > 0.0:
                race_multiplier = float(race_raw) / 100.0

        monster_def_level_id = _toi(elem_row.get("Id"), 0)
        monster_element_id = _toi(elem_row.get("Element_Id"), 0)

        whole_target_stat_id = whole_target_stat_by_element.get(int(monster_element_id),
                                                                0) if monster_element_id > 0 else 0
        whole_target_raw = 0.0
        whole_target_multiplier = 1.0
        if whole_target_stat_id > 0:
            whole_target_raw = _tof(raw_vals.get(int(whole_target_stat_id), 0.0), 0.0)
            if whole_target_raw > 0.0:
                whole_target_multiplier = float(whole_target_raw) / 100.0

        common_multiplier = float(race_multiplier) * float(whole_target_multiplier)

        mdm_factor_by_stat: Dict[int | None, float] = {}
        if monster_def_level_id > 0 and _table_exists(conn, "Monster_damage_modifier"):
            try:
                rows = conn.execute(
                    """
                    SELECT Stat_Id, DamagePercent
                    FROM Monster_damage_modifier
                    WHERE DefElement_Id=?
                    ORDER BY rowid ASC
                    """,
                    (int(monster_def_level_id),),
                ).fetchall()
            except Exception:
                rows = []

            for r in rows or []:
                if hasattr(r, "keys"):
                    raw_sid = r["Stat_Id"]
                    raw_pct = r["DamagePercent"]
                else:
                    raw_sid = r[0]
                    raw_pct = r[1]

                key = None
                if raw_sid is not None:
                    sid = _toi(raw_sid, 0)
                    key = int(sid) if sid > 0 else None

                if raw_pct is None:
                    factor = 1.0
                else:
                    factor = _tof(raw_pct, 100.0) / 100.0

                mdm_factor_by_stat[key] = float(factor)

        def _mdm_factor_for_multiplier_stat(multiplier_stat_id: int | None) -> float:
            key = None
            try:
                sid = int(multiplier_stat_id) if multiplier_stat_id is not None else 0
                key = int(sid) if sid > 0 else None
            except Exception:
                key = None

            if key in mdm_factor_by_stat:
                return float(mdm_factor_by_stat[key])
            if None in mdm_factor_by_stat:
                return float(mdm_factor_by_stat[None])
            return 1.0

        hit_multiplier_stat_ids: List[int | None] = []
        hit_target_damage_modifiers: List[float] = []
        hit_parts_before_common: List[float] = []
        hit_parts_after_common: List[float] = []

        for idx, dmg_with_mul in enumerate(expected_hit_damage_with_multiplier):
            eid = _toi(hit_element_ids[idx], 0) if idx < len(hit_element_ids) else 0
            mult_stat_id = element_damage_stat_by_element.get(int(eid)) if eid > 0 else None
            mdm_factor = _mdm_factor_for_multiplier_stat(mult_stat_id)

            part_before_common = (
                    float(_tof(dmg_with_mul, 0.0))
                    * float(attacks_per_second)
                    * float(global_multiplier)
                    * float(mdm_factor)
            )
            part_after_common = float(part_before_common) * float(common_multiplier)

            hit_multiplier_stat_ids.append(int(mult_stat_id) if mult_stat_id else None)
            hit_target_damage_modifiers.append(float(mdm_factor))
            hit_parts_before_common.append(float(part_before_common))
            hit_parts_after_common.append(float(part_after_common))

        dps_hit_before_common = sum(hit_parts_before_common)
        dps_hit = sum(hit_parts_after_common)

        dot_payloads: List[Dict[str, Any]] = []
        dots_total_before_common = 0.0
        dots_total = 0.0

        for dot_id in sorted(dot_sources_by_id.keys()):
            dot_row = _load_dot_row(int(dot_id))
            if not dot_row:
                continue

            dot_stat_id = _toi(dot_row.get("Stat_Id"), 0)
            dot_base_stat_value = _tof(raw_vals.get(int(dot_stat_id), 0.0), 0.0) if dot_stat_id > 0 else 0.0
            dot_min = _tof(dot_row.get("MinValue"), 0.0)
            dot_max = _tof(dot_row.get("MaxValue"), 0.0)
            dot_seconds = _tof(dot_row.get("Seconds"), 0.0)
            dot_max_stack = _toi(dot_row.get("MaxStack"), 0)
            dot_element_id = _toi(dot_row.get("Element_Id"), 0)

            dot_tick_damage = float(dot_base_stat_value) * ((float(dot_min) + float(dot_max)) / 2.0)

            proc_chance_sum = 0.0
            srcs = dot_sources_by_id.get(int(dot_id), []) or []
            for src in srcs:
                proc_chance_sum += _tof(src.get("ChanceFraction"), 0.0)

            dot_apply_rate = float(hit_events_per_second) * float(proc_chance_sum)
            avg_stack_meta = self._calc_formula15_avg_stacks(
                dot_apply_rate=float(dot_apply_rate),
                seconds=float(dot_seconds),
                max_stack=int(dot_max_stack),
            )
            h = _tof(avg_stack_meta.get("h"), 0.0)
            avg_stacks = _tof(avg_stack_meta.get("AvgStacks"), 0.0)

            dot_multiplier = _element_multiplier(int(dot_element_id))
            base_dps_dot = (
                    float(dot_tick_damage)
                    * float(dot_ticks_per_second)
                    * float(avg_stacks)
                    * float(dot_multiplier)
                    * float(global_multiplier)
            )

            dot_multiplier_stat_id = element_damage_stat_by_element.get(
                int(dot_element_id)) if dot_element_id > 0 else None
            dot_target_damage_modifier = _mdm_factor_for_multiplier_stat(dot_multiplier_stat_id)

            dps_dot_before_common = float(base_dps_dot) * float(dot_target_damage_modifier)
            dps_dot = float(dps_dot_before_common) * float(common_multiplier)

            dot_dbg = {
                "DotId": int(dot_id),
                "DotName": str(dot_row.get("Name") or ""),
                "DotStatId": int(dot_stat_id),
                "DotBaseStatValue": float(dot_base_stat_value),
                "DotMinValue": float(dot_min),
                "DotMaxValue": float(dot_max),
                "DotSeconds": float(dot_seconds),
                "DotMaxStack": int(dot_max_stack),
                "DotElementId": int(dot_element_id) if dot_element_id > 0 else None,
                "DotTickDamage": float(dot_tick_damage),
                "DotTicksPerSecond": float(dot_ticks_per_second),
                "ProcChanceSum": float(proc_chance_sum),
                "ProcChanceSumPercent": float(proc_chance_sum) * 100.0,
                "DotApplyRate": float(dot_apply_rate),
                "h": float(h),
                "AvgStacks": float(avg_stacks),
                "DotMultiplier": float(dot_multiplier),
                "BaseDPS_dot": float(base_dps_dot),
                "TargetMultiplierStatId": int(dot_multiplier_stat_id) if dot_multiplier_stat_id else None,
                "TargetDamageModifier": float(dot_target_damage_modifier),
                "DPS_dot_before_common": float(dps_dot_before_common),
                "DPS_dot": float(dps_dot),
                "Sources": list(srcs),
            }

            dot_payloads.append(dot_dbg)
            dots_total_before_common += float(dps_dot_before_common)
            dots_total += float(dps_dot)

        payload["TargetRaceStatId"] = int(race_stat_id) if race_stat_id > 0 else None
        payload["TargetRaceRaw"] = float(race_raw)
        payload["TargetRaceMultiplier"] = float(race_multiplier)
        payload["TargetMonsterElementLevelId"] = int(monster_def_level_id) if monster_def_level_id > 0 else None
        payload["TargetMonsterElementId"] = int(monster_element_id) if monster_element_id > 0 else None
        payload["TargetWholeElementStatId"] = int(whole_target_stat_id) if whole_target_stat_id > 0 else None
        payload["TargetWholeElementRaw"] = float(whole_target_raw)
        payload["TargetWholeElementMultiplier"] = float(whole_target_multiplier)
        payload["TargetCommonMultiplier"] = float(common_multiplier)
        payload["TargetHitElementIds"] = list(hit_element_ids)
        payload["TargetHitMultiplierStatIds"] = list(hit_multiplier_stat_ids)
        payload["TargetHitDamageModifiers"] = list(hit_target_damage_modifiers)
        payload["TargetDotDamageModifiers"] = [float(x.get("TargetDamageModifier", 1.0)) for x in dot_payloads]
        payload["TargetMonsterDamageModifierMap"] = {
            ("NULL" if k is None else str(int(k))): float(v)
            for k, v in mdm_factor_by_stat.items()
        }

        payload["BaseDPS_hit"] = float(sum(
            float(_tof(v, 0.0)) * float(attacks_per_second) * float(global_multiplier)
            for v in expected_hit_damage_with_multiplier
        ))
        payload["DPS_hit_before_common"] = float(dps_hit_before_common)
        payload["DPS_hit"] = float(dps_hit)

        payload["DoTs"] = list(dot_payloads)
        payload["BaseDPS_total"] = float(payload["BaseDPS_hit"]) + float(
            sum(float(x.get("BaseDPS_dot", 0.0)) for x in dot_payloads))
        payload["DPS_total_before_common"] = float(dps_hit_before_common + dots_total_before_common)
        payload["DPS_total"] = float(dps_hit) + float(dots_total)

        try:
            payload["DebugDotEvents"] = list(debug_dot_events)
        except Exception:
            payload["DebugDotEvents"] = []

        try:
            payload["DebugDotSourcesById"] = {
                int(dot_id): list(srcs or [])
                for dot_id, srcs in (dot_sources_by_id or {}).items()
            }
        except Exception:
            payload["DebugDotSourcesById"] = {}

        try:
            payload["DebugDotSummary"] = {
                "accepted_dot_ids": sorted(int(x) for x in dot_sources_by_id.keys()),
                "accepted_sources_count": sum(len(v or []) for v in dot_sources_by_id.values()),
                "events_count": len(debug_dot_events),
            }
        except Exception:
            payload["DebugDotSummary"] = {}

        return payload

    def _resolve_formula15_hit_element_ids_from_equipment(
            self,
            *,
            payload: Mapping[str, Any],
            equipment_rows: Iterable[Mapping[int, float] | Mapping[str, float]] = (),
    ) -> List[int | None]:
        """
        Вытаскивает элементы обычных hit-атак напрямую из экипировки по вставленным картам,
        не завязываясь на DoT-источники.

        Нужен потому, что текущий _calc_formula15_payload() выставляет HitElementIds
        только через card DoT source, и элемент обычной автоатаки может потеряться.
        """
        conn = self.conn
        if conn is None:
            return list(payload.get("HitElementIds") or [])

        def _toi(v, d=0) -> int:
            try:
                return int(v)
            except Exception:
                try:
                    return int(float(str(v).strip()))
                except Exception:
                    return d

        raw_items = list(equipment_rows or ())

        def _normalize_equip_row(x) -> dict | None:
            if isinstance(x, dict):
                return x

            if isinstance(x, (tuple, list)):
                d: dict = {}
                if len(x) > 0:
                    d["_slot"] = x[0]
                if len(x) > 1:
                    d["Id"] = x[1]
                    d["Equipment_Id"] = x[1]
                if len(x) > 2:
                    d["__forge_level"] = x[2]
                if len(x) > 3:
                    d["TemplateId"] = x[3]
                if len(x) > 4:
                    d["ProtoId"] = x[4]
                if len(x) > 5:
                    d["_uuid"] = x[5]
                    d["InstanceGuid"] = x[5]
                if len(x) > 6:
                    d["_cards"] = x[6]
                return d

            return None

        norm_items: List[dict] = []
        for row in raw_items:
            d = _normalize_equip_row(row)
            if isinstance(d, dict):
                norm_items.append(d)

        _weapon_markers = (
            "weapon", "mainhand", "main_hand", "weapon1", "hand1", "primary",
            "right", "rhand", "right_hand",
            "оруж", "пра", "прав", "осн",
        )
        _offhand_markers = (
            "offhand", "off_hand", "secondhand", "second_hand", "weapon2", "hand2", "secondary",
            "shield", "left", "lhand", "left_hand",
            "лева", "лев", "втор", "щит",
        )
        _spear_markers = (
            "spear", "lance", "pike", "polearm", "halberd",
            "weapon3", "hand3", "thirdhand", "third_hand",
            "копь", "копье", "копьё", "пика", "алебард",
        )

        def _slot_kind(it: dict) -> str:
            slot_s = str(
                it.get("_slot")
                or it.get("Slot")
                or it.get("slot")
                or it.get("SlotKey")
                or it.get("slot_key")
                or ""
            ).strip().lower()

            if not slot_s:
                return ""

            if any(m in slot_s for m in _spear_markers):
                return "spear"
            if any(m in slot_s for m in _offhand_markers):
                return "offhand"
            if any(m in slot_s for m in _weapon_markers):
                return "weapon"
            return ""

        def _equip_id(it: dict) -> int:
            for k in ("Equipment_Id", "Equip_Id", "TemplateId", "Template_Id", "Item_Id", "Id"):
                if k in it and it[k] not in (None, ""):
                    eid = _toi(it[k], 0)
                    if eid > 0:
                        return int(eid)
            return 0

        def _resolve_item_type_id(it: dict) -> int:
            tid = _resolve_type_id(it)
            if tid > 0:
                return int(tid)

            eid = _equip_id(it)
            if eid <= 0:
                return 0

            try:
                row = conn.execute(
                    "SELECT Type_Id FROM Equipment WHERE Id=? LIMIT 1",
                    (int(eid),),
                ).fetchone()
            except Exception:
                row = None

            if not row:
                return 0

            try:
                return _toi(row["Type_Id"] if hasattr(row, "keys") else row[0], 0)
            except Exception:
                return 0

        def _iter_card_entries(it: dict) -> List[Any]:
            cards_raw = it.get("_cards") or it.get("cards") or it.get("Cards")
            if isinstance(cards_raw, dict):
                return list(cards_raw.values())
            if isinstance(cards_raw, (list, tuple)):
                return list(cards_raw)
            return []

        card_element_cache: Dict[int, int] = {}

        def _card_element_id(card_id: int) -> int:
            cid = _toi(card_id, 0)
            if cid <= 0:
                return 0

            if cid in card_element_cache:
                return int(card_element_cache[cid])

            try:
                row = conn.execute(
                    """
                    SELECT ct.Element_Id
                    FROM Card c
                    LEFT JOIN CardType ct ON ct.Id = c.Type_Id
                    WHERE c.Id=?
                    LIMIT 1
                    """,
                    (int(cid),),
                ).fetchone()
            except Exception:
                row = None

            eid = 0
            if row:
                try:
                    eid = _toi(row["Element_Id"] if hasattr(row, "keys") else row[0], 0)
                except Exception:
                    eid = 0

            card_element_cache[cid] = int(eid)
            return int(eid)

        state_id = _toi(get_active_state_id(), 0)

        filtered_items: List[dict] = []
        for it in norm_items:
            kind = _slot_kind(it)
            if state_id == 1 and kind == "spear":
                continue
            if state_id == 2 and kind in ("weapon", "offhand"):
                continue
            filtered_items.append(it)

        main_element_id: int | None = None
        off_element_id: int | None = None

        for it in filtered_items:
            kind = _slot_kind(it)
            if kind not in ("weapon", "offhand", "spear"):
                continue

            type_id = _resolve_item_type_id(it)
            if not _is_weapon_type_by_equipmenttype(conn, int(type_id or 0)):
                continue

            for c in _iter_card_entries(it):
                cid = _resolve_card_id_from_entry(c)
                if cid <= 0:
                    continue

                eid = _card_element_id(int(cid))
                if eid <= 0:
                    continue

                if kind in ("weapon", "spear"):
                    if main_element_id is None:
                        main_element_id = int(eid)
                elif kind == "offhand":
                    if off_element_id is None:
                        off_element_id = int(eid)

                break

        hit_parts = list(payload.get("HitParts") or [1.0])
        weapon_mode = str(payload.get("WeaponMode") or "").strip().lower()

        if weapon_mode == "dual_wield_1h":
            return [
                int(main_element_id) if main_element_id else None,
                int(off_element_id) if off_element_id else None,
            ]

        return [int(main_element_id) if main_element_id else None for _ in hit_parts]

    def _apply_formula15_target_modifiers(
            self,
            *,
            payload: Mapping[str, Any],
            values_by_id: Mapping[int, float],
            target_race_row: Mapping[str, Any] | None = None,
            target_element_row: Mapping[str, Any] | None = None,
            equipment_rows: Iterable[Mapping[int, float] | Mapping[str, float]] = (),
    ) -> Dict[str, Any]:
        """
        Накладывает на уже посчитанный payload формулы DPS (Stat.Id = 75)
        модификаторы цели из верхнего блока "конструктора существа".

        Правила:
          - множитель по расе берём приоритетно из Race.DefStat_Id,
            но если он не попадает в боевые race-статы или не найден,
            ищем стат по Stat.Race_Id среди [68, 38..47];
          - Monster_damage_modifier.DefElement_Id + Stat_Id -> покомпонентный множитель;
          - Monster_damage_modifier.Stat_Id IS NULL -> множитель для компонента без элемента;
          - Stat.Id [61..66] -> общий множитель по элементу выбранного существа.
        """
        try:
            base_payload = dict(payload or {})
        except Exception:
            base_payload = {}

        if not base_payload:
            return {
                "DPS_total": 0.0,
                "DPS_hit": 0.0,
                "DoTs": [],
            }

        conn = self.conn
        raw_vals = _normalize_stats_mapping(values_by_id or {})

        def _toi(v, d=0) -> int:
            try:
                return int(v)
            except Exception:
                try:
                    return int(float(str(v).strip()))
                except Exception:
                    return d

        def _tof(v, d=0.0) -> float:
            try:
                return float(v)
            except Exception:
                try:
                    return float(str(v).replace(",", ".").strip())
                except Exception:
                    return d

        out: Dict[str, Any] = dict(base_payload)
        out["DoTs"] = [dict(x) for x in (base_payload.get("DoTs") or []) if isinstance(x, dict)]

        race_row = dict(target_race_row or {}) if isinstance(target_race_row, Mapping) else {}
        elem_row = dict(target_element_row or {}) if isinstance(target_element_row, Mapping) else {}

        app_target_race = {}
        app_target_element = {}

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                raw_race = app.property("rq_target_creature_top_race_row")
                raw_elem = app.property("rq_target_creature_top_element_row")
                if isinstance(raw_race, dict):
                    app_target_race = dict(raw_race)
                if isinstance(raw_elem, dict):
                    app_target_element = dict(raw_elem)
        except Exception:
            app_target_race = {}
            app_target_element = {}

        shared_target_race = {}
        shared_target_element = {}

        try:
            raw = getattr(self, "_shared_target_race_row", None)
            if isinstance(raw, dict):
                shared_target_race = dict(raw)
        except Exception:
            shared_target_race = {}

        try:
            raw = getattr(self, "_shared_target_element_row", None)
            if isinstance(raw, dict):
                shared_target_element = dict(raw)
        except Exception:
            shared_target_element = {}

        effective_race_row = dict(race_row)
        effective_elem_row = dict(elem_row)

        if not effective_race_row and app_target_race:
            effective_race_row = dict(app_target_race)
        if not effective_race_row and shared_target_race:
            effective_race_row = dict(shared_target_race)

        if not effective_elem_row and app_target_element:
            effective_elem_row = dict(app_target_element)
        if not effective_elem_row and shared_target_element:
            effective_elem_row = dict(shared_target_element)

        race_row = dict(effective_race_row or {})
        elem_row = dict(effective_elem_row or {})

        # ---------- element -> stat maps ----------
        element_damage_stat_by_element: Dict[int, int] = {}
        whole_target_stat_by_element: Dict[int, int] = {}

        if conn is not None:
            try:
                rows = conn.execute(
                    """
                    SELECT Id, Element_Id
                    FROM Stat
                    WHERE Id IN (25, 26, 27, 28, 29, 30, 61, 62, 63, 64, 65, 66)
                    """
                ).fetchall()
            except Exception:
                rows = []

            for r in rows or []:
                try:
                    sid = _toi(r["Id"] if hasattr(r, "keys") else r[0], 0)
                    eid = _toi(r["Element_Id"] if hasattr(r, "keys") else r[1], 0)
                except Exception:
                    continue

                if sid <= 0 or eid <= 0:
                    continue

                if 25 <= sid <= 30:
                    element_damage_stat_by_element[int(eid)] = int(sid)
                elif 61 <= sid <= 66:
                    whole_target_stat_by_element[int(eid)] = int(sid)

        # ---------- race stat resolve ----------
        race_damage_stat_ids = [68, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47]
        race_id = _toi(race_row.get("Id"), 0)
        race_stat_id = _toi(race_row.get("DefStat_Id"), 0)

        def _resolve_race_stat_id() -> int:
            # 1) если в Race.DefStat_Id уже лежит нужный combat-stat
            if race_stat_id in race_damage_stat_ids:
                return int(race_stat_id)

            if conn is None or race_id <= 0:
                return int(race_stat_id if race_stat_id > 0 else 0)

            # 2) ищем по Stat.Race_Id среди боевых race-статов из панели
            try:
                q = ",".join("?" for _ in race_damage_stat_ids)
                rows = conn.execute(
                    f"""
                    SELECT Id
                    FROM Stat
                    WHERE Race_Id = ?
                      AND Id IN ({q})
                    ORDER BY Id ASC
                    """,
                    (int(race_id), *[int(x) for x in race_damage_stat_ids]),
                ).fetchall()
            except Exception:
                rows = []

            if rows:
                for wanted_sid in race_damage_stat_ids:
                    for r in rows:
                        sid = _toi(r["Id"] if hasattr(r, "keys") else r[0], 0)
                        if sid == int(wanted_sid):
                            return int(sid)

            # 3) fallback обратно на DefStat_Id, если он вообще есть
            if race_stat_id > 0:
                return int(race_stat_id)

            return 0

        resolved_race_stat_id = _resolve_race_stat_id()

        race_raw = 0.0
        race_multiplier = 1.0
        if resolved_race_stat_id > 0:
            race_raw = _tof(raw_vals.get(int(resolved_race_stat_id), 0.0), 0.0)
            if race_raw > 0.0:
                race_multiplier = float(race_raw) / 100.0

        # ---------- общий множитель по элементу существа (61..66) ----------
        monster_def_level_id = _toi(elem_row.get("Id"), 0)
        monster_element_id = _toi(elem_row.get("Element_Id"), 0)

        whole_target_stat_id = whole_target_stat_by_element.get(int(monster_element_id),
                                                                0) if monster_element_id > 0 else 0
        whole_target_raw = 0.0
        whole_target_multiplier = 1.0
        if whole_target_stat_id > 0:
            whole_target_raw = _tof(raw_vals.get(int(whole_target_stat_id), 0.0), 0.0)
            if whole_target_raw > 0.0:
                whole_target_multiplier = float(whole_target_raw) / 100.0

        common_multiplier = float(race_multiplier) * float(whole_target_multiplier)

        # ---------- Monster_damage_modifier ----------
        mdm_factor_by_stat: Dict[int | None, float] = {}
        if conn is not None and monster_def_level_id > 0 and _table_exists(conn, "Monster_damage_modifier"):
            try:
                rows = conn.execute(
                    """
                    SELECT Stat_Id, DamagePercent
                    FROM Monster_damage_modifier
                    WHERE DefElement_Id=?
                    ORDER BY rowid ASC
                    """,
                    (int(monster_def_level_id),),
                ).fetchall()
            except Exception:
                rows = []

            for r in rows or []:
                try:
                    raw_sid = r["Stat_Id"] if hasattr(r, "keys") else r[0]
                    raw_pct = r["DamagePercent"] if hasattr(r, "keys") else r[1]
                except Exception:
                    continue

                key = None
                if raw_sid is not None:
                    sid = _toi(raw_sid, 0)
                    key = int(sid) if sid > 0 else None

                if raw_pct is None:
                    factor = 1.0
                else:
                    factor = _tof(raw_pct, 100.0) / 100.0

                mdm_factor_by_stat[key] = float(factor)

        def _mdm_factor_for_multiplier_stat(multiplier_stat_id: int | None) -> float:
            key = None
            try:
                sid = int(multiplier_stat_id) if multiplier_stat_id is not None else 0
                key = int(sid) if sid > 0 else None
            except Exception:
                key = None

            if key in mdm_factor_by_stat:
                return float(mdm_factor_by_stat[key])
            if None in mdm_factor_by_stat:
                return float(mdm_factor_by_stat[None])
            return 1.0

        # ---------- hit ----------
        hit_element_ids = list(base_payload.get("HitElementIds") or [])
        hit_damage_with_mul = list(base_payload.get("ExpectedHitDamageWithMultiplier") or [])
        attacks_per_second = _tof(base_payload.get("AttacksPerSecond"), 0.0)
        global_multiplier = _tof(base_payload.get("GlobalMultiplier"), 1.0)

        hit_multiplier_stat_ids: List[int | None] = []
        hit_target_damage_modifiers: List[float] = []
        hit_dps_parts_before_common: List[float] = []
        hit_dps_parts_after_common: List[float] = []

        for idx, dmg_with_mul in enumerate(hit_damage_with_mul):
            eid = _toi(hit_element_ids[idx], 0) if idx < len(hit_element_ids) else 0
            mult_stat_id = element_damage_stat_by_element.get(int(eid)) if eid > 0 else None
            mdm_factor = _mdm_factor_for_multiplier_stat(mult_stat_id)

            part_before_common = (
                    float(_tof(dmg_with_mul, 0.0))
                    * float(attacks_per_second)
                    * float(global_multiplier)
                    * float(mdm_factor)
            )
            part_after_common = float(part_before_common) * float(common_multiplier)

            hit_multiplier_stat_ids.append(int(mult_stat_id) if mult_stat_id else None)
            hit_target_damage_modifiers.append(float(mdm_factor))
            hit_dps_parts_before_common.append(float(part_before_common))
            hit_dps_parts_after_common.append(float(part_after_common))

        dps_hit_before_common = sum(hit_dps_parts_before_common)
        dps_hit_final = sum(hit_dps_parts_after_common)

        # ---------- DoT ----------
        dot_target_damage_modifiers: List[float] = []
        dots_total_before_common = 0.0
        dots_total_final = 0.0
        new_dots: List[Dict[str, Any]] = []

        for dot in (out.get("DoTs") or []):
            if not isinstance(dot, dict):
                continue

            dot_copy = dict(dot)
            base_dps_dot = _tof(dot_copy.get("DPS_dot"), 0.0)

            dot_element_id = _toi(dot_copy.get("DotElementId"), 0)
            dot_multiplier_stat_id = element_damage_stat_by_element.get(
                int(dot_element_id)) if dot_element_id > 0 else None
            mdm_factor = _mdm_factor_for_multiplier_stat(dot_multiplier_stat_id)

            dps_dot_before_common = float(base_dps_dot) * float(mdm_factor)
            dps_dot_final = float(dps_dot_before_common) * float(common_multiplier)

            dot_copy["TargetMultiplierStatId"] = int(dot_multiplier_stat_id) if dot_multiplier_stat_id else None
            dot_copy["TargetDamageModifier"] = float(mdm_factor)
            dot_copy["BaseDPS_dot"] = float(base_dps_dot)
            dot_copy["DPS_dot_before_common"] = float(dps_dot_before_common)
            dot_copy["DPS_dot"] = float(dps_dot_final)

            new_dots.append(dot_copy)
            dot_target_damage_modifiers.append(float(mdm_factor))
            dots_total_before_common += float(dps_dot_before_common)
            dots_total_final += float(dps_dot_final)

        out["DoTs"] = list(new_dots)
        out["BaseDPS_hit"] = float(_tof(base_payload.get("DPS_hit"), 0.0))
        out["DPS_hit_before_common"] = float(dps_hit_before_common)
        out["DPS_hit"] = float(dps_hit_final)
        out["BaseDPS_total"] = float(_tof(base_payload.get("DPS_total"), 0.0))
        out["DPS_total_before_common"] = float(dps_hit_before_common + dots_total_before_common)
        out["DPS_total"] = float(dps_hit_final + dots_total_final)

        out["TargetRaceStatId"] = int(resolved_race_stat_id) if resolved_race_stat_id > 0 else None
        out["TargetRaceRaw"] = float(race_raw)
        out["TargetRaceMultiplier"] = float(race_multiplier)
        out["TargetMonsterElementLevelId"] = int(monster_def_level_id) if monster_def_level_id > 0 else None
        out["TargetMonsterElementId"] = int(monster_element_id) if monster_element_id > 0 else None
        out["TargetWholeElementStatId"] = int(whole_target_stat_id) if whole_target_stat_id > 0 else None
        out["TargetWholeElementRaw"] = float(whole_target_raw)
        out["TargetWholeElementMultiplier"] = float(whole_target_multiplier)
        out["TargetCommonMultiplier"] = float(common_multiplier)
        out["TargetHitElementIds"] = list(hit_element_ids)
        out["TargetHitMultiplierStatIds"] = list(hit_multiplier_stat_ids)
        out["TargetHitDamageModifiers"] = list(hit_target_damage_modifiers)
        out["TargetDotDamageModifiers"] = list(dot_target_damage_modifiers)
        out["TargetMonsterDamageModifierMap"] = {
            ("NULL" if k is None else str(int(k))): float(v)
            for k, v in mdm_factor_by_stat.items()
        }

        return out

    def _normalize_menu_bonus_enabled(self, flags: Optional[Mapping[str, bool]] = None) -> Dict[str, bool]:
        defaults = {
            "talents": True,
            "guild": True,
            "elixir": True,
            "consum": True,
            "consumble": True,
            "aura": True,
            "buffs": True,
            "collect": True,
            "stamp": True,
            "reforge": True,
        }

        norm = dict(defaults)

        stored = getattr(self, "menu_bonus_enabled", None)
        if isinstance(stored, Mapping):
            for k, v in stored.items():
                kk = str(k or "").strip().lower()
                if kk:
                    norm[kk] = bool(v)

        if isinstance(flags, Mapping):
            for k, v in flags.items():
                kk = str(k or "").strip().lower()
                if kk:
                    norm[kk] = bool(v)

        # ВАЖНО:
        # consum и consumble — это один и тот же флаг.
        # Нельзя оставлять ситуацию, когда один False, а второй True,
        # иначе блок расходников продолжит считаться из-за OR в calc_for_character().
        consum_value = None

        if isinstance(flags, Mapping):
            if "consumble" in flags:
                consum_value = bool(flags.get("consumble"))
            elif "consum" in flags:
                consum_value = bool(flags.get("consum"))

        if consum_value is None and isinstance(stored, Mapping):
            if "consumble" in stored:
                consum_value = bool(stored.get("consumble"))
            elif "consum" in stored:
                consum_value = bool(stored.get("consum"))

        if consum_value is None:
            consum_value = bool(norm.get("consumble", norm.get("consum", True)))

        norm["consum"] = bool(consum_value)
        norm["consumble"] = bool(consum_value)

        return norm

    def _is_menu_bonus_enabled(self, flags: Optional[Mapping[str, bool]], key: str) -> bool:
        kk = str(key or "").strip().lower()
        if not kk:
            return True
        norm = self._normalize_menu_bonus_enabled(flags)
        return bool(norm.get(kk, True))

    def _get_player_elixir_payload(self) -> Optional[dict]:
        """
        Эликсир персонажа из main_window.py.
        main_window кладёт его в QApplication.property("player_elixir_payload").
        """
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return None

            raw = app.property("player_elixir_payload")
            if isinstance(raw, dict):
                return dict(raw)
        except Exception:
            pass

        return None

    def _get_player_consumables_payloads(self) -> List[dict]:
        """
        Активные расходники персонажа из main_window.py.

        Читаем максимально живуче:
          1) QApplication.property("player_consumables_payloads")
          2) если там не получилось — QApplication.property("player_consumable_ids")
             и восстанавливаем payload'ы из БД.

        Поддерживаем не только list, но и tuple/set/прочие iterable-значения.
        """

        def _load_payload_from_db(consumable_id: int) -> Optional[dict]:
            cid = _to_int(consumable_id, 0)
            if self.conn is None or cid <= 0:
                return None

            try:
                row = self.conn.execute(
                    """
                    SELECT Id, Name, Image_Id, Exeption
                    FROM Consumable
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
                    real_id = _to_int(row["Id"], 0)
                    name = str(row["Name"] or "")
                    image_id = row["Image_Id"]
                    ex_raw = row["Exeption"]
                else:
                    real_id = _to_int(row[0], 0)
                    name = str(row[1] or "")
                    image_id = row[2]
                    ex_raw = row[3]
            except Exception:
                return None

            if real_id <= 0:
                return None

            ex = None
            try:
                if ex_raw is not None and str(ex_raw).strip() != "":
                    ex = int(ex_raw)
            except Exception:
                ex = None

            try:
                bonus_rows = self.conn.execute(
                    """
                    SELECT Type_Id, Value, OrderIndex
                    FROM ConsumableBonus
                    WHERE Consumable_Id=?
                    ORDER BY OrderIndex, rowid
                    """,
                    (int(real_id),),
                ).fetchall()
            except Exception:
                bonus_rows = []

            bonuses: List[dict] = []
            for r in (bonus_rows or []):
                try:
                    if hasattr(r, "keys"):
                        bt = _to_int(r["Type_Id"], 0)
                        val = _to_float(r["Value"], 0.0)
                        order_idx = _to_int(r["OrderIndex"], 0)
                    else:
                        bt = _to_int(r[0], 0)
                        val = _to_float(r[1], 0.0)
                        order_idx = _to_int(r[2], 0)
                except Exception:
                    continue

                if bt <= 0 or abs(float(val)) <= 1e-12:
                    continue

                bonuses.append(
                    {
                        "Type_Id": int(bt),
                        "Value": float(val),
                        "OrderIndex": int(order_idx),
                    }
                )

            return {
                "Id": int(real_id),
                "Name": str(name),
                "Image_Id": image_id,
                "Exeption": ex,
                "Bonuses": list(bonuses),
            }

        def _normalize_payload_dict(raw_payload: Mapping[str, Any]) -> Optional[dict]:
            try:
                cid = _to_int(raw_payload.get("Id") or raw_payload.get("id"), 0)
            except Exception:
                cid = 0

            if cid <= 0:
                return None

            name = str(raw_payload.get("Name") or raw_payload.get("name") or "")
            image_id = raw_payload.get("Image_Id", raw_payload.get("image_id"))
            ex_raw = raw_payload.get("Exeption", raw_payload.get("exeption"))

            ex = None
            try:
                if ex_raw is not None and str(ex_raw).strip() != "":
                    ex = int(ex_raw)
            except Exception:
                ex = None

            raw_bonuses = raw_payload.get("Bonuses") or raw_payload.get("bonuses") or []
            bonuses: List[dict] = []

            if isinstance(raw_bonuses, (list, tuple, set)):
                for b in raw_bonuses:
                    if not isinstance(b, Mapping):
                        continue

                    try:
                        bt = _to_int(b.get("Type_Id") or b.get("TypeId") or b.get("Type"), 0)
                    except Exception:
                        bt = 0

                    try:
                        val = _to_float(b.get("Value") or b.get("Val") or 0.0, 0.0)
                    except Exception:
                        val = 0.0

                    try:
                        order_idx = _to_int(b.get("OrderIndex"), 0)
                    except Exception:
                        order_idx = 0

                    if bt <= 0 or abs(float(val)) <= 1e-12:
                        continue

                    bonuses.append(
                        {
                            "Type_Id": int(bt),
                            "Value": float(val),
                            "OrderIndex": int(order_idx),
                        }
                    )

            return {
                "Id": int(cid),
                "Name": str(name),
                "Image_Id": image_id,
                "Exeption": ex,
                "Bonuses": list(bonuses),
            }

        def _iter_any(raw) -> List[Any]:
            if raw is None:
                return []
            if isinstance(raw, (list, tuple, set)):
                return list(raw)
            try:
                if isinstance(raw, (str, bytes, bytearray, dict)):
                    return [raw]
                return list(raw)
            except Exception:
                return [raw]

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return []

            out: List[dict] = []
            seen_ids: set[int] = set()

            raw_payloads = app.property("player_consumables_payloads")
            for x in _iter_any(raw_payloads):
                payload = None

                if isinstance(x, Mapping):
                    payload = _normalize_payload_dict(x)
                else:
                    cid = _to_int(x, 0)
                    if cid > 0:
                        payload = _load_payload_from_db(int(cid))

                if not isinstance(payload, dict):
                    continue

                cid = _to_int(payload.get("Id"), 0)
                if cid <= 0 or cid in seen_ids:
                    continue

                seen_ids.add(int(cid))
                out.append(dict(payload))

            if out:
                return out

            raw_ids = app.property("player_consumable_ids")
            for x in _iter_any(raw_ids):
                cid = _to_int(x, 0)
                if cid <= 0 or cid in seen_ids:
                    continue

                payload = _load_payload_from_db(int(cid))
                if not isinstance(payload, dict):
                    continue

                seen_ids.add(int(cid))
                out.append(dict(payload))

            return out
        except Exception:
            return []

    def _get_player_guild_talents(self) -> List[dict]:
        """
        Активные гильдейские таланты персонажа из guild_menu.py.
        Ожидаем QApplication.property("player_guild_talents") в формате:
        [
            {"Branch_Id": int, "Talent_Id": int, "Points": int},
            ...
        ]
        """
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return []

            raw = app.property("player_guild_talents")
            if isinstance(raw, list):
                out: List[dict] = []
                for x in raw:
                    if not isinstance(x, dict):
                        continue

                    bid = _to_int(x.get("Branch_Id") or x.get("branch_id"), 0)
                    tid = _to_int(x.get("Talent_Id") or x.get("talent_id"), 0)
                    pts = _to_int(x.get("Points") or x.get("points"), 0)

                    if bid <= 0 or tid <= 0 or pts <= 0:
                        continue

                    out.append(
                        {
                            "Branch_Id": int(bid),
                            "Talent_Id": int(tid),
                            "Points": int(pts),
                        }
                    )
                return out
        except Exception:
            pass

        return []

    def _get_player_talents(self) -> List[dict]:
        """
        Активные таланты персонажа из talents_menu.py.
        Ожидаем QApplication.property("player_talents") в формате:
        [
            {"Branch_Id": int, "Talent_Id": int, "HIndex": int},
            ...
        ]
        """
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return []

            raw = app.property("player_talents")
            if isinstance(raw, list):
                out: List[dict] = []
                for x in raw:
                    if not isinstance(x, dict):
                        continue

                    bid = _to_int(x.get("Branch_Id") or x.get("branch_id"), 0)
                    tid = _to_int(x.get("Talent_Id") or x.get("talent_id"), 0)
                    hidx = _to_int(x.get("HIndex") or x.get("hindex"), -1)

                    if bid <= 0 or tid <= 0 or hidx < 0:
                        continue

                    out.append(
                        {
                            "Branch_Id": int(bid),
                            "Talent_Id": int(tid),
                            "HIndex": int(hidx),
                        }
                    )
                return out
        except Exception:
            pass

        return []

    def _get_player_personal_aura_id(self) -> int:
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return 0
            return _to_int(app.property("player_personal_aura_id"), 0)
        except Exception:
            return 0

    def _get_player_buff_ids(self) -> List[int]:
        ids: List[int] = []

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return []

            raw = app.property("player_buff_ids")
            if isinstance(raw, (list, tuple, set)):
                for x in raw:
                    bid = _to_int(x, 0)
                    if bid > 0:
                        ids.append(int(bid))
        except Exception:
            return []

        out: List[int] = []
        seen: set[int] = set()
        for bid in ids:
            if bid > 0 and bid not in seen:
                seen.add(bid)
                out.append(int(bid))
        return out

    def _get_player_buff_stack_map(self) -> Dict[int, int]:
        out: Dict[int, int] = {}

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return {}

            raw = app.property("player_buff_stack_map")
            if isinstance(raw, dict):
                for k, v in raw.items():
                    bid = _to_int(k, 0)
                    stack = _to_int(v, 0)
                    if bid > 0 and stack > 0:
                        out[int(bid)] = int(stack)
        except Exception:
            return {}

        return out

    def _compute_player_buffs_bonus(
            self,
            *,
            selected_buff_ids: Iterable[int] = (),
            buff_stack_map: Optional[Mapping[int, int]] = None,
            selected_talents: Iterable[Mapping[str, Any]] = (),
            single_bonus_seen: Optional[set[int]] = None,
    ) -> Tuple[Dict[int, float], Dict[int, float], Dict[int, List[float]]]:
        """
        returns:
          add_out               -> обычные additive бонусы
          mul_out               -> обычные multiplicative % бонусы
          special_mul_out       -> специальные % бонусы, которые надо применять
                                   после остальных множителей:
                                   stat_id -> [pct1, pct2, ...]

        Спец-правило:
          - если BuffBonus.MulyiplyBonus = 1
          - и BonusType даёт множитель на атаку (в твоей БД это BonusType.Id = 6,
            а по маппингу BonusTypeStat -> Stat_Id=10, IsMultiply=1),
          то этот бонус НЕ идёт в обычный mul_out.
          Он переносится в special_mul_out[10].
        """
        add_out: Dict[int, float] = {}
        mul_out: Dict[int, float] = {}
        special_mul_out: Dict[int, List[float]] = {}

        if self.conn is None:
            return add_out, mul_out, special_mul_out

        buff_ids: List[int] = []
        for x in (selected_buff_ids or ()):
            bid = _to_int(x, 0)
            if bid > 0:
                buff_ids.append(int(bid))

        if not buff_ids:
            return add_out, mul_out, special_mul_out

        norm_stack_map: Dict[int, int] = {}
        if isinstance(buff_stack_map, Mapping):
            for k, v in buff_stack_map.items():
                bid = _to_int(k, 0)
                stack = _to_int(v, 0)
                if bid > 0 and stack > 0:
                    norm_stack_map[int(bid)] = int(stack)

        selected_talent_ids: List[int] = []
        for row in (selected_talents or ()):
            if not isinstance(row, Mapping):
                continue
            tid = _to_int(row.get("Talent_Id") or row.get("talent_id"), 0)
            if tid > 0:
                selected_talent_ids.append(int(tid))
        selected_talent_ids = sorted(set(selected_talent_ids))

        has_buffbonus_multiply = False
        try:
            cols = _table_columns(self.conn, "BuffBonus") or []
            has_buffbonus_multiply = any(str(c).lower() == "mulyiplybonus".lower() for c in cols)
        except Exception:
            has_buffbonus_multiply = False

        def _load_bonus_rows_for_buff(buff_id: int) -> List[Tuple[int, float, int]]:
            if int(buff_id) <= 0:
                return []

            # 1) если есть TalentBonus для этого бафа и активных талантов — берём ИХ
            if selected_talent_ids:
                ph = ",".join(["?"] * len(selected_talent_ids))
                try:
                    rows = self.conn.execute(
                        f"""
                        SELECT Type_Id, Value
                        FROM TalentBonus
                        WHERE BuffCondition_Id=?
                          AND Talent_Id IN ({ph})
                        ORDER BY Id
                        """,
                        (int(buff_id), *tuple(int(x) for x in selected_talent_ids)),
                    ).fetchall()
                except Exception:
                    rows = []

                out_rows: List[Tuple[int, float, int]] = []
                for r in rows or []:
                    try:
                        if hasattr(r, "keys"):
                            bt_id = _to_int(r["Type_Id"], 0)
                            val = _to_float(r["Value"], 0.0)
                        else:
                            bt_id = _to_int(r[0], 0)
                            val = _to_float(r[1], 0.0)
                    except Exception:
                        continue

                    if not _take_bonus_type_once(self.conn, single_bonus_seen, int(bt_id)):
                        continue

                    if bt_id > 0 and abs(float(val)) > 1e-12:
                        out_rows.append((int(bt_id), float(val), 0))

                if out_rows:
                    return out_rows

            # 2) иначе обычный BuffBonus
            try:
                if has_buffbonus_multiply:
                    rows = self.conn.execute(
                        """
                        SELECT Type_Id, Value, MulyiplyBonus
                        FROM BuffBonus
                        WHERE Buff_Id=?
                        ORDER BY OrderIndex, Type_Id
                        """,
                        (int(buff_id),),
                    ).fetchall()
                else:
                    rows = self.conn.execute(
                        """
                        SELECT Type_Id, Value
                        FROM BuffBonus
                        WHERE Buff_Id=?
                        ORDER BY OrderIndex, Type_Id
                        """,
                        (int(buff_id),),
                    ).fetchall()
            except Exception:
                rows = []

            out_rows: List[Tuple[int, float, int]] = []
            for r in rows or []:
                try:
                    if hasattr(r, "keys"):
                        bt_id = _to_int(r["Type_Id"], 0)
                        val = _to_float(r["Value"], 0.0)
                        multiply_bonus = _to_int(r["MulyiplyBonus"], 0) if has_buffbonus_multiply else 0
                    else:
                        bt_id = _to_int(r[0], 0)
                        val = _to_float(r[1], 0.0)
                        multiply_bonus = _to_int(r[2], 0) if has_buffbonus_multiply and len(r) > 2 else 0
                except Exception:
                    continue

                if bt_id > 0 and abs(float(val)) > 1e-12:
                    out_rows.append((int(bt_id), float(val), int(multiply_bonus)))

            return out_rows

        for buff_id in buff_ids:
            stack = max(1, int(norm_stack_map.get(int(buff_id), 1)))
            bonus_rows = _load_bonus_rows_for_buff(int(buff_id))
            if not bonus_rows:
                continue

            for bt_id, base_val, multiply_bonus in bonus_rows:
                eff_val = float(base_val) * float(stack)

                try:
                    mapped = _load_bonustype_stat_map(self.conn, int(bt_id))
                except Exception:
                    mapped = []

                if not mapped:
                    continue

                for var_idx, sid, is_mul in mapped:
                    try:
                        vi = int(var_idx)
                        stat_id = int(sid)
                        im = int(is_mul)
                    except Exception:
                        continue

                    if stat_id <= 0 or vi != 0:
                        continue

                    # Спец-правило для "Отваги"-подобных бафов:
                    # BuffBonus.MulyiplyBonus=1 + множитель атаки
                    if im == 1 and stat_id == 10 and int(bt_id) == 6 and int(multiply_bonus) == 1:
                        special_mul_out.setdefault(10, []).append(float(eff_val))
                        continue

                    if im == 1:
                        mul_out[stat_id] = float(mul_out.get(stat_id, 0.0)) + float(eff_val)
                    else:
                        add_out[stat_id] = float(add_out.get(stat_id, 0.0)) + float(eff_val)

        return add_out, mul_out, special_mul_out

    def _get_player_general_aura_ids(self) -> List[int]:
        ids: List[int] = []

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return []

            raw = app.property("player_general_aura_ids")
            if isinstance(raw, (list, tuple, set)):
                for x in raw:
                    aid = _to_int(x, 0)
                    if aid > 0:
                        ids.append(int(aid))

            if not ids:
                old_id = _to_int(app.property("player_general_aura_id"), 0)
                if old_id > 0:
                    ids.append(int(old_id))
        except Exception:
            return []

        out: List[int] = []
        seen: set[int] = set()
        for aid in ids:
            if aid > 0 and aid not in seen:
                seen.add(aid)
                out.append(int(aid))
        return out

    def _get_player_general_aura_use_talents_map(self) -> Dict[int, bool]:
        out: Dict[int, bool] = {}

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return {}

            raw = app.property("player_general_aura_use_talents_map")
            if isinstance(raw, dict):
                for k, v in raw.items():
                    aid = _to_int(k, 0)
                    if aid > 0:
                        out[int(aid)] = bool(v)

            if not out:
                old_flag = bool(app.property("player_general_aura_use_talents"))
                for aid in self._get_player_general_aura_ids():
                    out[int(aid)] = bool(old_flag)
        except Exception:
            return {}

        return out

    def _compute_player_auras_bonus(
            self,
            *,
            personal_aura_id: int = 0,
            general_aura_ids: Iterable[int] = (),
            general_use_talents_map: Optional[Mapping[int, bool]] = None,
            selected_talents: Iterable[Mapping[str, Any]] = (),
            single_bonus_seen: Optional[set[int]] = None,
    ) -> Tuple[Dict[int, float], Dict[int, float]]:
        """
        Возвращает:
          (add_dict, mul_percent_dict)

        Логика:
          - personal aura:
              AuraBonus.Value
              если есть TalentBonus с AuraCondition_Id == aura_id и тем же Type_Id,
              берём TalentBonus.Value вместо AuraBonus.Value
              если в TalentBonus есть новый Type_Id, которого нет в AuraBonus,
              тоже добавляем его
          - general aura:
              base = AuraBonus.SharedValue, если SharedValue IS NULL -> AuraBonus.Value
              если у конкретной ауры включена галочка use talents,
              то override берём ИЗ ВСЕХ TalentBonus этой ауры, даже если сами таланты не выбраны.
              При этом:
                - совпадающий Type_Id заменяет AuraBonus.SharedValue
                - новый Type_Id тоже добавляется

        Важно:
          - если одна и та же аура выбрана и в personal, и в general,
            то совпадающие Type_Id из general НЕ добавляются второй раз
          - только VarIndex == 0
          - BuffCondition_Id у talent override здесь игнорируем, т.е. берём только
            строки без BuffCondition_Id
        """
        add_out: Dict[int, float] = {}
        mul_out: Dict[int, float] = {}

        if self.conn is None:
            return add_out, mul_out

        personal_aura_id = _to_int(personal_aura_id, 0)
        norm_general_ids: List[int] = []
        for x in (general_aura_ids or ()):
            aid = _to_int(x, 0)
            if aid > 0:
                norm_general_ids.append(int(aid))

        if personal_aura_id <= 0 and not norm_general_ids:
            return add_out, mul_out

        selected_talent_ids: List[int] = []
        for row in (selected_talents or ()):
            if not isinstance(row, Mapping):
                continue
            tid = _to_int(row.get("Talent_Id") or row.get("talent_id"), 0)
            if tid > 0:
                selected_talent_ids.append(int(tid))
        selected_talent_ids = sorted(set(selected_talent_ids))

        def _load_override_map(aura_id: int, *, shared: bool, selected_only: bool) -> Dict[int, float]:
            if aura_id <= 0:
                return {}

            sql = """
                SELECT Type_Id, Value, SharedValue
                FROM TalentBonus
                WHERE AuraCondition_Id=?
                  AND (BuffCondition_Id IS NULL OR BuffCondition_Id=0)
            """
            params: List[Any] = [int(aura_id)]

            if selected_only:
                if not selected_talent_ids:
                    return {}
                ph = ",".join(["?"] * len(selected_talent_ids))
                sql += f" AND Talent_Id IN ({ph})"
                params.extend(int(x) for x in selected_talent_ids)

            sql += " ORDER BY Id"

            try:
                rows = self.conn.execute(sql, tuple(params)).fetchall()
            except Exception:
                rows = []

            out: Dict[int, float] = {}
            for r in rows or []:
                try:
                    if hasattr(r, "keys"):
                        type_id = _to_int(r["Type_Id"], 0)
                        raw_value = r["Value"]
                        raw_shared = r["SharedValue"]
                    else:
                        type_id = _to_int(r[0], 0)
                        raw_value = r[1]
                        raw_shared = r[2]
                except Exception:
                    continue

                if type_id <= 0:
                    continue

                if shared:
                    if raw_shared is None:
                        eff = _to_float(raw_value, 0.0)
                    else:
                        eff = _to_float(raw_shared, 0.0)
                else:
                    eff = _to_float(raw_value, 0.0)

                if abs(float(eff)) <= 1e-12:
                    continue

                out[int(type_id)] = float(out.get(int(type_id), 0.0)) + float(eff)

            return out

        def _load_resolved_bt_values(aura_id: int, *, shared: bool, use_talent_overrides: bool, selected_only: bool) -> \
        Dict[int, float]:
            if aura_id <= 0:
                return {}

            try:
                rows = self.conn.execute(
                    """
                    SELECT Type_Id, Value, SharedValue
                    FROM AuraBonus
                    WHERE Aura_Id=?
                    ORDER BY OrderIndex, Type_Id
                    """,
                    (int(aura_id),),
                ).fetchall()
            except Exception:
                rows = []

            base_map: Dict[int, float] = {}
            for r in rows or []:
                try:
                    if hasattr(r, "keys"):
                        bt_id = _to_int(r["Type_Id"], 0)
                        raw_value = r["Value"]
                        raw_shared = r["SharedValue"]
                    else:
                        bt_id = _to_int(r[0], 0)
                        raw_value = r[1]
                        raw_shared = r[2]
                except Exception:
                    continue

                if bt_id <= 0:
                    continue

                if shared:
                    if raw_shared is None:
                        eff_value = _to_float(raw_value, 0.0)
                    else:
                        eff_value = _to_float(raw_shared, 0.0)
                else:
                    eff_value = _to_float(raw_value, 0.0)

                if abs(float(eff_value)) <= 1e-12:
                    continue

                base_map[int(bt_id)] = float(eff_value)

            if not use_talent_overrides:
                return dict(base_map)

            override_map = _load_override_map(int(aura_id), shared=shared, selected_only=selected_only)
            if not override_map:
                return dict(base_map)

            resolved = dict(base_map)
            for bt_id, val in override_map.items():
                resolved[int(bt_id)] = float(val)

            return resolved

        def _apply_bt_values(bt_values: Mapping[int, float]) -> None:
            for bt_id, eff_value in (bt_values or {}).items():
                ibt = _to_int(bt_id, 0)
                fval = _to_float(eff_value, 0.0)
                if ibt <= 0 or abs(fval) <= 1e-12:
                    continue

                if not _take_bonus_type_once(self.conn, single_bonus_seen, int(ibt)):
                    continue

                try:
                    mapped = _load_bonustype_stat_map(self.conn, int(ibt))
                except Exception:
                    mapped = []

                if not mapped:
                    continue

                for var_idx, sid, is_mul in mapped:
                    vi = _to_int(var_idx, -1)
                    stat_id = _to_int(sid, 0)
                    im = _to_int(is_mul, 0)
                    if stat_id <= 0 or vi != 0:
                        continue

                    if im == 1:
                        mul_out[stat_id] = float(mul_out.get(stat_id, 0.0)) + float(fval)
                    else:
                        add_out[stat_id] = float(add_out.get(stat_id, 0.0)) + float(fval)

        personal_bt_values: Dict[int, float] = {}
        if personal_aura_id > 0:
            personal_bt_values = _load_resolved_bt_values(
                int(personal_aura_id),
                shared=False,
                use_talent_overrides=bool(selected_talent_ids),
                selected_only=True,
            )
            _apply_bt_values(personal_bt_values)

        norm_use_talents_map: Dict[int, bool] = {}
        if isinstance(general_use_talents_map, Mapping):
            for k, v in general_use_talents_map.items():
                aid = _to_int(k, 0)
                if aid > 0:
                    norm_use_talents_map[int(aid)] = bool(v)

        seen_general: set[int] = set()
        for aid in norm_general_ids:
            if aid <= 0 or aid in seen_general:
                continue
            seen_general.add(int(aid))

            use_overrides = bool(norm_use_talents_map.get(int(aid), False))
            general_bt_values = _load_resolved_bt_values(
                int(aid),
                shared=True,
                use_talent_overrides=use_overrides,
                selected_only=False,
            )

            if personal_aura_id > 0 and int(aid) == int(personal_aura_id):
                for bt_id in list(general_bt_values.keys()):
                    if int(bt_id) in personal_bt_values:
                        general_bt_values.pop(int(bt_id), None)

            _apply_bt_values(general_bt_values)

        return add_out, mul_out

    def _pick_guild_talent_value(self, by_points: Optional[Mapping[int, float]], points: int) -> Optional[float]:
        if not isinstance(by_points, Mapping) or not by_points:
            return None

        try:
            p = int(points or 0)
        except Exception:
            p = 0

        norm: Dict[int, float] = {}
        for k, v in by_points.items():
            try:
                kk = int(k)
                vv = float(v)
            except Exception:
                continue
            norm[int(kk)] = float(vv)

        if not norm:
            return None

        if p in norm:
            return float(norm[p])

        keys = sorted(norm.keys())
        lower = [k for k in keys if k <= p]
        if lower:
            return float(norm[max(lower)])

        return float(norm[keys[0]])

    def _compute_player_guild_talents_bonus(
            self,
            selected_talents: Iterable[Mapping[str, Any]],
            single_bonus_seen: Optional[set[int]] = None,
    ) -> Tuple[Dict[int, float], Dict[int, float]]:
        """
        Возвращает:
          (add_dict, mul_percent_dict)

        Логика:
          GuildTalentBonus.Type_Id -> BonusTypeStat
          GuildTalentVariable(Index, Points, Value) -> значения переменных
          выбранный уровень таланта = Points из player_guild_talents
        """
        add_out: Dict[int, float] = {}
        mul_out: Dict[int, float] = {}

        if self.conn is None:
            return add_out, mul_out

        bonus_type_ids_cache: Dict[int, List[int]] = {}
        vars_cache: Dict[int, Dict[int, Dict[int, float]]] = {}

        for row in (selected_talents or []):
            if not isinstance(row, Mapping):
                continue

            talent_id = _to_int(row.get("Talent_Id") or row.get("talent_id"), 0)
            points = _to_int(row.get("Points") or row.get("points"), 0)

            if talent_id <= 0 or points <= 0:
                continue

            if talent_id not in bonus_type_ids_cache:
                try:
                    b_rows = self.conn.execute(
                        """
                        SELECT Type_Id
                        FROM GuildTalentBonus
                        WHERE Talent_Id=?
                        ORDER BY Id
                        """,
                        (int(talent_id),),
                    ).fetchall()
                except Exception:
                    b_rows = []

                bt_ids: List[int] = []
                for r in b_rows or []:
                    try:
                        if hasattr(r, "keys"):
                            bt_id = _to_int(r["Type_Id"], 0)
                        else:
                            bt_id = _to_int(r[0], 0)
                    except Exception:
                        bt_id = 0
                    if bt_id > 0:
                        bt_ids.append(int(bt_id))

                bonus_type_ids_cache[int(talent_id)] = list(bt_ids)

            if talent_id not in vars_cache:
                try:
                    v_rows = self.conn.execute(
                        """
                        SELECT "Index", Points, Value
                        FROM GuildTalentVariable
                        WHERE Talent_Id=?
                        ORDER BY "Index", Points, Id
                        """,
                        (int(talent_id),),
                    ).fetchall()
                except Exception:
                    v_rows = []

                vars_by_index: Dict[int, Dict[int, float]] = {}
                for r in v_rows or []:
                    try:
                        if hasattr(r, "keys"):
                            idx = _to_int(r["Index"], 0)
                            pts = _to_int(r["Points"], 0)
                            val = float(r["Value"])
                        else:
                            idx = _to_int(r[0], 0)
                            pts = _to_int(r[1], 0)
                            val = float(r[2])
                    except Exception:
                        continue

                    vars_by_index.setdefault(int(idx), {})[int(pts)] = float(val)

                vars_cache[int(talent_id)] = dict(vars_by_index)

            bt_ids = bonus_type_ids_cache.get(int(talent_id), []) or []
            vars_by_index = vars_cache.get(int(talent_id), {}) or {}

            for bt_id in bt_ids:
                if not _take_bonus_type_once(self.conn, single_bonus_seen, int(bt_id)):
                    continue
                bts = _load_bonustype_stat_map(self.conn, int(bt_id))
                if not bts:
                    continue

                for var_idx, stat_id, is_mul in bts:
                    vi = int(var_idx)
                    sid = int(stat_id)
                    if sid <= 0:
                        continue

                    by_points = vars_by_index.get(int(vi))
                    if not by_points and int(vi) == 0:
                        by_points = vars_by_index.get(0)
                        if not by_points and len(vars_by_index) == 1:
                            try:
                                by_points = next(iter(vars_by_index.values()))
                            except Exception:
                                by_points = None

                    val = self._pick_guild_talent_value(by_points, int(points))
                    if val is None:
                        continue

                    fv = float(val)
                    if abs(fv) <= 1e-12:
                        continue

                    if int(is_mul) == 1:
                        mul_out[sid] = float(mul_out.get(sid, 0.0)) + float(fv)
                    else:
                        add_out[sid] = float(add_out.get(sid, 0.0)) + float(fv)

        return add_out, mul_out

    def _compute_player_talents_bonus(
            self,
            selected_talents: Iterable[Mapping[str, Any]],
            single_bonus_seen: Optional[set[int]] = None,
    ) -> Tuple[Dict[int, float], Dict[int, float]]:
        """
        Возвращает:
          (add_dict, mul_percent_dict)

        Логика:
          TalentBonus.Type_Id -> BonusTypeStat
          TalentBonus.Value   -> значение для VarIndex=0

        Важно:
          - TalentBonus с AuraCondition_Id / BuffCondition_Id здесь НЕ считаем,
            потому что это не пассивные бонусы таланта
          - такие строки должны обрабатываться через ауры/баффы
        """
        add_out: Dict[int, float] = {}
        mul_out: Dict[int, float] = {}

        if self.conn is None:
            return add_out, mul_out

        bonus_rows_cache: Dict[int, List[Tuple[int, float]]] = {}

        for row in (selected_talents or []):

            if not isinstance(row, Mapping):
                continue

            talent_id = _to_int(row.get("Talent_Id") or row.get("talent_id"), 0)
            if talent_id <= 0:
                continue

            if talent_id not in bonus_rows_cache:
                try:
                    b_rows = self.conn.execute(
                        """
                        SELECT Type_Id, Value
                        FROM TalentBonus
                        WHERE Talent_Id=?
                          AND (AuraCondition_Id IS NULL OR AuraCondition_Id=0)
                          AND (BuffCondition_Id IS NULL OR BuffCondition_Id=0)
                        ORDER BY Id
                        """,
                        (int(talent_id),),
                    ).fetchall()
                except Exception:
                    b_rows = []

                prepared: List[Tuple[int, float]] = []
                for r in b_rows or []:
                    try:
                        if hasattr(r, "keys"):
                            bt_id = _to_int(r["Type_Id"], 0)
                            val = float(r["Value"] or 0.0)
                        else:
                            bt_id = _to_int(r[0], 0)
                            val = float(r[1] or 0.0)
                    except Exception:
                        continue

                    if not _take_bonus_type_once(self.conn, single_bonus_seen, int(bt_id)):
                        continue

                    if bt_id > 0 and abs(val) > 1e-12:
                        prepared.append((int(bt_id), float(val)))

                bonus_rows_cache[int(talent_id)] = prepared

            for bt_id, val in (bonus_rows_cache.get(int(talent_id)) or []):
                try:
                    mapped = _load_bonustype_stat_map(self.conn, int(bt_id))
                except Exception:
                    mapped = []

                if not mapped:
                    continue

                for var_idx, sid, is_mul in mapped:
                    try:
                        stat_id = int(sid)
                        vi = int(var_idx)
                        im = int(is_mul)
                    except Exception:
                        continue

                    if stat_id <= 0 or vi != 0:
                        continue

                    if im == 1:
                        mul_out[stat_id] = float(mul_out.get(stat_id, 0.0)) + float(val)
                    else:
                        add_out[stat_id] = float(add_out.get(stat_id, 0.0)) + float(val)

        return add_out, mul_out

    # --- NEW: stat id by name from Stat table ---
    def _sid(self, name: str) -> int | None:
        try:
            return int(self._stat_name_to_id.get(self._norm_stat_name(name)))
        except Exception:
            return None

    # --- NEW: class info (with Base_Id fallback for HpPerVitality) ---
    def _load_class_info(self, class_id: int | None, class_name: str | None) -> dict[str, Any]:
        """
        Возвращает:
          {
            "class_id": int|None,
            "base_id": int|None,
            "primary_stat_id": int|None,
            "energy_stat_id": int|None,   # 2 (Энергия) или 3 (Мана)
            "hp_per_vit": float
          }

        Правило: если Base_Id != NULL -> HpPerVitality берём у Base_Id (как ты описал).
        """
        if not self.conn:
            return {"class_id": None, "base_id": None, "primary_stat_id": None, "energy_stat_id": None, "hp_per_vit": 0.0}

        cid: int | None = None
        try:
            cid = int(class_id) if class_id is not None else None
        except Exception:
            cid = None

        if cid is None and class_name:
            try:
                row = self.conn.execute(
                    "SELECT Id FROM Class WHERE lower(Name)=? LIMIT 1",
                    (str(class_name).strip().lower(),)
                ).fetchone()
                if row:
                    cid = int(row[0] if not hasattr(row, "keys") else row["Id"])
            except Exception:
                cid = None

        if cid is None or cid <= 0:
            return {"class_id": None, "base_id": None, "primary_stat_id": None, "energy_stat_id": None, "hp_per_vit": 0.0}

        if cid in self._class_info_cache:
            return self._class_info_cache[cid]

        def _toi(x, d=0):
            try: return int(x)
            except Exception:
                try: return int(float(str(x).strip()))
                except Exception: return d

        def _tof(x, d=0.0):
            try: return float(x)
            except Exception:
                try: return float(str(x).replace(",", "."))
                except Exception: return d

        def _get_row(xid: int):
            try:
                return self.conn.execute(
                    "SELECT Id, Base_Id, PrimaryStat_Id, EnergyStat_Id, HpPerVitality FROM Class WHERE Id=? LIMIT 1",
                    (int(xid),)
                ).fetchone()
            except Exception:
                return None

        row = _get_row(cid)
        if not row:
            info = {"class_id": cid, "base_id": None, "primary_stat_id": None, "energy_stat_id": None, "hp_per_vit": 0.0}
            self._class_info_cache[cid] = info
            return info

        if hasattr(row, "keys"):
            base_id = _toi(row["Base_Id"], 0) or None
            primary_id = _toi(row["PrimaryStat_Id"], 0) or None
            energy_id = _toi(row["EnergyStat_Id"], 0) or None
            hp_per_vit = _tof(row["HpPerVitality"], 0.0)
        else:
            base_id = _toi(row[1], 0) or None
            primary_id = _toi(row[2], 0) or None
            energy_id = _toi(row[3], 0) or None
            hp_per_vit = _tof(row[4], 0.0)

        # Base_Id: HpPerVitality берём у базы (и, если надо, подтягиваем Primary/Energy)
        if base_id and int(base_id) != int(cid):
            brow = _get_row(int(base_id))
            if brow:
                if hasattr(brow, "keys"):
                    hp_per_vit = _tof(brow["HpPerVitality"], hp_per_vit)
                    if not primary_id:
                        primary_id = _toi(brow["PrimaryStat_Id"], 0) or primary_id
                    if not energy_id:
                        energy_id = _toi(brow["EnergyStat_Id"], 0) or energy_id
                else:
                    hp_per_vit = _tof(brow[4], hp_per_vit)
                    if not primary_id:
                        primary_id = _toi(brow[2], 0) or primary_id
                    if not energy_id:
                        energy_id = _toi(brow[3], 0) or energy_id

        info = {
            "class_id": cid,
            "base_id": base_id,
            "primary_stat_id": primary_id,
            "energy_stat_id": energy_id,
            "hp_per_vit": float(hp_per_vit or 0.0),
        }
        self._class_info_cache[cid] = info
        return info

    def set_applied_stamps_by_instance(self, applied: Optional[dict]) -> None:
        """
        applied: dict[instance_guid -> payload]
        payload как в StampWindow: {"id": int, "color_id": int, ...}
        """
        self._applied_stamps_by_inst = dict(applied or {})

    # ---------- STAMP: helpers ----------
    @lru_cache(maxsize=1)
    def _get_max_player_level(self) -> int:
        """Кап уровня. В stamp_window было 100, но пробуем брать из Setting/Settings."""
        conn = getattr(self, "conn", None)
        if conn is None:
            return 100
        # 1) Setting (твоя БД)
        try:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='Setting'").fetchone():
                row = conn.execute("SELECT Value FROM Setting WHERE Key='MaxPlayerLevel' LIMIT 1").fetchone()
                if row and row[0]:
                    v = int(row[0])
                    if v > 0:
                        return v
        except Exception:
            pass
        # 2) Settings (на всякий случай)
        try:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='Settings'").fetchone():
                row = conn.execute(
                    "SELECT QualityValue FROM Settings WHERE Key='MaxPlayerLevel' LIMIT 1").fetchone()
                if row and row[0]:
                    v = int(row[0])
                    if v > 0:
                        return v
        except Exception:
            pass
        return 100
    @lru_cache(maxsize=512)
    def _get_bonus_type_coefs(self, bonus_type_id: int) -> Tuple[float, float]:
        """BonusType.StampQualityMinCoef/MaxCoef или (1.0, 1.0)."""
        conn = getattr(self, "conn", None)
        if conn is None:
            return (1.0, 1.0)
        try:
            row = conn.execute(
                "SELECT StampQualityMinCoef, StampQualityMaxCoef FROM BonusType WHERE Id=? LIMIT 1",
                (int(bonus_type_id),),
            ).fetchone()
            if row:
                mn = float(row[0] if row[0] is not None else 1.0)
                mx = float(row[1] if row[1] is not None else 1.0)
                return (mn, mx)
        except Exception:
            pass
        return (1.0, 1.0)
    def _get_internal_level_for_item(self, equip_id: int, item: Optional[dict] = None) -> int:
        """
        internal_level:
          1) item["InternalLevel"]
          2) SELECT Equipment.InternalLevel
          3) fallback: item["Level"] / item["RequiredLevel"] / 1
        """
        # 1) из item dict
        try:
            if isinstance(item, dict) and item.get("InternalLevel") is not None:
                v = int(item.get("InternalLevel") or 1)
                return v if v > 0 else 1
        except Exception:
            pass
        conn = getattr(self, "conn", None)
        # 2) из БД
        try:
            if conn is not None and int(equip_id or 0) > 0:
                row = conn.execute(
                    "SELECT InternalLevel FROM Equipment WHERE Id=? LIMIT 1",
                    (int(equip_id),),
                ).fetchone()
                if row and row[0] is not None:
                    v = int(row[0])
                    return v if v > 0 else 1
        except Exception:
            pass
        # 3) fallback
        try:
            if isinstance(item, dict):
                v = int(item.get("Level") or item.get("RequiredLevel") or 1)
                return v if v > 0 else 1
        except Exception:
            pass
        return 1
    def _get_stamp_value(
            self,
            base_value: float | int,
            *,
            min_coef: float,
            max_coef: float,
            internal_level: float,
            min_level: float,
            max_level: Optional[float] = None,
    ) -> int:
        """
        1:1 как в stamp_window.py.
        Округление: ceil, если (ceil(num)-num) < 0.98, иначе trunc.
        """
        try:
            base = float(base_value)
            mn = float(min_coef)
            mx = float(max_coef)
            if max_level is None:
                max_level = float(min(60, self._get_max_player_level()))
            lvl_min = 10.0
            lvl_max = float(max_level)
            d = float((mx - mn) / (lvl_max - lvl_min))
            ilvl = float(internal_level)
            value = max(0.0, ilvl - lvl_min)
            num = (mn + d * value) * base
            num2 = math.ceil(num)
            out = num2 if (num2 - num) < 0.98 else math.trunc(num)
            return int(out)
        except Exception:
            try:
                return int(round(float(base_value)))
            except Exception:
                return 0

    def _stamp_bonus_stats_for_item(
            self, *, stamp_id: int, color_id: int, internal_level: int
    ) -> Tuple[Dict[int, float], Dict[int, float]]:
        """
        Возвращает:
          flat: {Stat_Id: +value}
          mul : {Stat_Id: +percent}   (IsMultiply=1 => проценты)
        Учитывает BonusTypeStatCondition (Event_Id / State_Id) по BonusTypeStat.Id
        """
        conn = getattr(self, "conn", None)
        if conn is None or int(stamp_id) <= 0:
            return ({}, {})

        # выбрать вариант (цвет) -> StampVariant.Id
        variant_id = None
        try:
            row = conn.execute(
                "SELECT Id FROM StampVariant WHERE Stamp_Id=? AND Color_Id=? LIMIT 1",
                (int(stamp_id), int(color_id)),
            ).fetchone()
            if row:
                variant_id = int(row[0])
            else:
                row = conn.execute(
                    "SELECT Id FROM StampVariant WHERE Stamp_Id=? ORDER BY Color_Id DESC LIMIT 1",
                    (int(stamp_id),),
                ).fetchone()
                if row:
                    variant_id = int(row[0])
        except Exception:
            variant_id = None

        if not variant_id:
            return ({}, {})

        # читаем бонус-линии варианта
        try:
            rows = conn.execute(
                """
                SELECT Type_Id, QualityValue
                FROM StampVariantBonus
                WHERE StampVariant_Id=?
                ORDER BY OrderIndex
                """,
                (int(variant_id),),
            ).fetchall()
        except Exception:
            rows = []

        if not rows:
            return ({}, {})

        flat: Dict[int, float] = {}
        mul: Dict[int, float] = {}
        max_level = float(min(60, self._get_max_player_level()))
        ilvl = int(internal_level or 1)

        for r in rows:
            try:
                type_id = int(r[0])
                qv = float(r[1])
            except Exception:
                continue

            mn, mx = self._get_bonus_type_coefs(type_id)
            scaled = self._get_stamp_value(
                base_value=qv,
                internal_level=float(ilvl),
                min_coef=mn,
                max_coef=mx,
                min_level=1,
                max_level=max_level,
            )

            # маппинг BonusType -> Stat через BonusTypeStat + фильтр по условиям
            try:
                map_rows = conn.execute(
                    "SELECT Id, Stat_Id, IsMultiply FROM BonusTypeStat WHERE BonusType_Id=?",
                    (int(type_id),),
                ).fetchall()
            except Exception:
                map_rows = []

            if not map_rows:
                continue

            bts_ids = []
            for mr in map_rows:
                try:
                    bts_ids.append(int(mr["Id"] if hasattr(mr, "keys") else mr[0]))
                except Exception:
                    pass

            cond_map = _load_bts_conditions_map(conn, bts_ids)

            for mr in map_rows:
                try:
                    if hasattr(mr, "keys"):
                        bts_id = int(mr["Id"])
                        stat_id = int(mr["Stat_Id"])
                        is_mul = int(mr["IsMultiply"] or 0)
                    else:
                        bts_id = int(mr[0])
                        stat_id = int(mr[1])
                        is_mul = int(mr[2] or 0)
                except Exception:
                    continue

                if stat_id <= 0:
                    continue

                if not _bts_conditions_allow(cond_map.get(int(bts_id), None)):
                    continue

                if is_mul == 1:
                    mul[stat_id] = float(mul.get(stat_id, 0.0) or 0.0) + float(scaled)
                else:
                    flat[stat_id] = float(flat.get(stat_id, 0.0) or 0.0) + float(scaled)

        return (flat, mul)

    def collect_stamp_stats_from_selected_items(
            self, selected_items: Iterable[Any]
    ) -> Tuple[Dict[int, float], Dict[int, float]]:
        """
        selected_items: что ты уже логируешь как [('armor', 127, ..., 'guid'), ...]
        Берём stamp из self._applied_stamps_by_inst[InstanceGuid] (как у StampWindow).
        """
        applied = getattr(self, "_applied_stamps_by_inst", {}) or {}
        conn = getattr(self, "conn", None)
        if conn is None:
            return ({}, {})
        total_flat: Dict[int, float] = {}
        total_mul: Dict[int, float] = {}
        for it in selected_items or []:
            # вытащим equip_id + instance_guid
            equip_id = 0
            inst = ""
            item_dict = None
            if isinstance(it, dict):
                item_dict = it
                try:
                    equip_id = int(it.get("Id") or 0)
                except Exception:
                    equip_id = 0
                inst = str(it.get("InstanceGuid") or "")
            else:
                # ожидаем кортеж как в твоих логах: (slot, equip_id, ..., instance_guid)
                try:
                    equip_id = int(it[1] or 0)
                except Exception:
                    equip_id = 0
                try:
                    inst = str(it[5] or "")
                except Exception:
                    inst = ""
            if not inst:
                continue
            payload = applied.get(inst)
            if not isinstance(payload, dict):
                continue
            try:
                stamp_id = int(payload.get("id") or payload.get("Id") or 0)
            except Exception:
                stamp_id = 0
            try:
                color_id = int(payload.get("color_id") or payload.get("ColorId") or payload.get("Color_Id") or 0)
            except Exception:
                color_id = 0
            if stamp_id <= 0:
                continue
            if color_id <= 0:
                # в UI у тебя 0 = "снять", реальные цвета 1..4; если пусто — пусть будет 4 (оранж) как дефолт списка
                color_id = 4
            internal_level = self._get_internal_level_for_item(equip_id, item=item_dict)
            flat, mul = self._stamp_bonus_stats_for_item(
                stamp_id=stamp_id,
                color_id=color_id,
                internal_level=internal_level,
            )
            for sid, v in flat.items():
                total_flat[sid] = float(total_flat.get(sid, 0.0) or 0.0) + float(v)
            for sid, p in mul.items():
                total_mul[sid] = float(total_mul.get(sid, 0.0) or 0.0) + float(p)
        return (total_flat, total_mul)

    # --- NEW: apply parameter rules to derived stats ---
    def _apply_param_rules_inplace(
            self,
            vals: Dict[int, float],
            *,
            class_id: int | None,
            class_name: str | None
    ) -> None:
        """
        Правила параметров (с поддержкой значений < 1 и отрицательных):

          - PrimaryStat (Class.PrimaryStat_Id) -> Атака: +2 за 1 и +15 за каждые 10
            (для отрицательных тоже работает: каждый “минус-поинт” уменьшает)

          - Ловкость -> скорость атаки: +0.25% за 1 и +2.5% за каждые 10;
                        уворот +4 за каждые 10
            (всё симметрично для отрицательных)

          - Выносливость -> HP +HpPerVitality*(VIT-1)
                            (базовый 1 даёт 0; если VIT < 1 — уходит в минус)
                            per 10:
                              если класс с Энергией: +15 Энергии и +0.03 к восстановлению энергии
                              если класс с Маной:    +30 Маны   и +0.09 к восстановлению маны
            (per10 тоже учитывается в минус при VIT <= -10, -20, ...)

          - Удача -> рейтинг крита: шаг 0.33/0.67/1.00 (каждые 3 очка = ровно +1)
                     (для отрицательных: -0.33/-0.67/-1.00 и т.д.)
                     per 10: +1 к рейтингу крита и +4 попадания (и в минус при -10, -20, ...)
        """

        sid_hp = self._sid("Здоровье") or 1
        sid_energy = self._sid("Энергия") or 2
        sid_mana = self._sid("Мана") or 3

        sid_atk = self._sid("Атака") or 10
        sid_atk_speed = self._sid("Скорость атаки") or 11
        sid_dodge = self._sid("Уворот") or 14
        sid_hit = self._sid("Попадание") or 13

        sid_crit_rating = self._sid("Рейтинг крита") or self._sid("Рейтинг шанса крита") or 15

        sid_energy_regen = self._sid("Восстановление энергии") or 23
        sid_mana_regen = self._sid("Восстановление маны") or 24

        sid_agi = self._sid("Ловкость") or 7
        sid_vit = self._sid("Выносливость") or 8
        sid_luck = self._sid("Удача") or 9

        def _int_param(sid: int) -> int:
            """Параметры могут быть отрицательные (карты). Берём целое без clamp к 0."""
            try:
                v = float(vals.get(int(sid), 0.0) or 0.0)
            except Exception:
                v = 0.0
            # устойчиво к -2.0000000001
            if v >= 0:
                return int(math.floor(v + 1e-9))
            else:
                return int(math.ceil(v - 1e-9))

        def _blocks(x: int, step: int) -> int:
            """
            Кол-во полных блоков, симметрично для отрицательных:
              19 -> 1,  10 -> 1,  9 -> 0
             -19 -> -1, -10 -> -1, -9 -> 0
            """
            if step <= 0:
                return 0
            return int(x / step)  # trunc toward 0

        def _luck_thirds(luck_val: int) -> float:
            """
            Рейтинг крита по удаче:
              1 -> 0.33, 2 -> 0.67, 3 -> 1.00
             -1 -> -0.33, -2 -> -0.67, -3 -> -1.00
            """
            if luck_val == 0:
                return 0.0
            sign = 1.0 if luck_val > 0 else -1.0
            a = abs(int(luck_val))
            blocks3 = a // 3
            rem = a % 3
            rem_add = {0: 0.00, 1: 0.33, 2: 0.67}[rem]
            return sign * (float(blocks3) + float(rem_add))

        info = self._load_class_info(class_id, class_name)

        # --- primary stat -> attack ---
        primary_sid = info.get("primary_stat_id")
        try:
            primary_sid = int(primary_sid) if primary_sid is not None else None
        except Exception:
            primary_sid = None

        if primary_sid is not None and primary_sid > 0:
            p = _int_param(primary_sid)
            blocks10_p = _blocks(p, 10)
            atk_add = (p * 2) + (blocks10_p * 15)
            if atk_add:
                vals[int(sid_atk)] = float(vals.get(int(sid_atk), 0.0) or 0.0) + float(atk_add)

        # --- agility ---
        agi = _int_param(int(sid_agi))
        if agi:
            blocks10_agi = _blocks(agi, 10)

            atk_speed_add = (agi * 0.25) + (blocks10_agi * 2.5)
            if abs(atk_speed_add) > 1e-12:
                vals[int(sid_atk_speed)] = float(vals.get(int(sid_atk_speed), 0.0) or 0.0) + float(atk_speed_add)

            dodge_add = blocks10_agi * 4
            if dodge_add:
                vals[int(sid_dodge)] = float(vals.get(int(sid_dodge), 0.0) or 0.0) + float(dodge_add)

        # --- vitality ---
        vit_total = _int_param(int(sid_vit))

        hp_per_vit = 0.0
        try:
            hp_per_vit = float(info.get("hp_per_vit", 0.0) or 0.0)
        except Exception:
            hp_per_vit = 0.0

        # КЛЮЧЕВОЕ:
        # 1 даёт 0, но если VIT < 1 — бонус становится отрицательным и должен отнимать ХП.
        vit_for_hp = int(vit_total) - 1

        if vit_for_hp and hp_per_vit:
            vals[int(sid_hp)] = float(vals.get(int(sid_hp), 0.0) or 0.0) + float(vit_for_hp) * float(hp_per_vit)

        # per 10 по выносливости — тоже симметрично для отрицательных
        blocks10_vit = _blocks(vit_total, 10)
        if blocks10_vit:
            energy_stat_id = info.get("energy_stat_id")
            try:
                energy_stat_id = int(energy_stat_id) if energy_stat_id is not None else None
            except Exception:
                energy_stat_id = None

            uses_mana = (energy_stat_id == int(sid_mana))
            if uses_mana:
                vals[int(sid_mana)] = float(vals.get(int(sid_mana), 0.0) or 0.0) + float(blocks10_vit * 30)
                vals[int(sid_mana_regen)] = float(vals.get(int(sid_mana_regen), 0.0) or 0.0) + float(
                    blocks10_vit * 0.09)
            else:
                vals[int(sid_energy)] = float(vals.get(int(sid_energy), 0.0) or 0.0) + float(blocks10_vit * 15)
                vals[int(sid_energy_regen)] = float(vals.get(int(sid_energy_regen), 0.0) or 0.0) + float(
                    blocks10_vit * 0.03)

        # --- luck ---
        luck = _int_param(int(sid_luck))

        crit_rating_add = _luck_thirds(luck)
        if abs(crit_rating_add) > 1e-12:
            vals[int(sid_crit_rating)] = float(vals.get(int(sid_crit_rating), 0.0) or 0.0) + float(crit_rating_add)

        # per 10 по удаче — симметрично для отрицательных
        blocks10_luck = _blocks(luck, 10)
        if blocks10_luck:
            vals[int(sid_crit_rating)] = float(vals.get(int(sid_crit_rating), 0.0) or 0.0) + float(blocks10_luck * 1.0)
            vals[int(sid_hit)] = float(vals.get(int(sid_hit), 0.0) or 0.0) + float(blocks10_luck * 4)

    # --- вспомогалки ---
    def _load_stats_per_level(self) -> int:
        """
        Берёт из Setting: Key='StatsPerLevel', Value=<число>
        """
        if not self.conn:
            return 0
        row = self.conn.execute(
            'SELECT "Value" FROM "Setting" WHERE "Key" = ? LIMIT 1',
            ("StatsPerLevel",),
        ).fetchone()
        if not row:
            return 0
        raw = row[0] if not hasattr(row, "keys") else row["Value"]
        return int(float(raw))

    def stats_per_level(self) -> int:
        """Сколько очков параметров даётся за 1 уровень."""
        return int(self._stats_per_level or 0)

    Editable_Stat = (4, 5, 6, 7, 8, 9)

    def _has_weapon_equipped(self, equip_items: list[dict]) -> bool:
        for it in equip_items or []:
            tid = _resolve_type_id(it)
            if self.conn and tid > 0:
                w = _is_weapon_type_by_equipmenttype(self.conn, tid)
                if w:
                    return True
            # дальше твой старый fallback по имени типа можно оставить как совсем последний
        return False

    def _empty_values_by_id(self, *, ignore_base_attack: bool = False) -> Dict[int, float]:
        # база по умолчанию из Stat.DefaultValue
        acc = {s.id: float(getattr(s, "default_value", 0.00) or 0.00) for s in self.stat_defs}

        # --- базовая атака персонажа = минимум 2 (без учета параметров) ---
        sid_atk = self._sid("Атака") or 10
        try:
            cur_atk = float(acc.get(int(sid_atk), 0.0) or 0.0)
        except Exception:
            cur_atk = 0.0

        # NEW: если есть оружие — базовую атаку (2) НЕ навязываем
        if not ignore_base_attack:
            acc[int(sid_atk)] = max(cur_atk, 2.0)

        # на 1 уровне у каждого параметра минимум 1
        for sid in self.Editable_Stat:
            acc[sid] = max(float(acc.get(sid, 0.0)), 1.0)

        # --- базовые регены (всегда, поверх Stat.DefaultValue; до параметров/экипировки/бафов) ---
        sid_energy_regen = self._sid("Восстановление энергии") or 23
        sid_mana_regen = self._sid("Восстановление маны") or 24

        try:
            acc[int(sid_energy_regen)] = float(acc.get(int(sid_energy_regen), 0.0) or 0.0) + 0.2
        except Exception:
            pass

        try:
            acc[int(sid_mana_regen)] = float(acc.get(int(sid_mana_regen), 0.0) or 0.0) + 0.6
        except Exception:
            pass

        return acc

    def _add_dict_into(
        self,
        acc: Dict[int, float],
        src: Mapping[int, float] | Mapping[str, float],
    ) -> None:
        if not src:
            return

        some_key = next(iter(src.keys()), None)
        if some_key is None:
            return

        if isinstance(some_key, int):
            for k, v in src.items():
                try:
                    val = float(v)
                except Exception:
                    continue
                acc[k] = acc.get(k, 0.0) + val
        else:
            for code, v in src.items():
                if not isinstance(code, str):
                    continue
                stat_def = self.by_code.get(code)
                if not stat_def:
                    continue
                try:
                    val = float(v)
                except Exception:
                    continue
                acc[stat_def.id] = acc.get(stat_def.id, 0.0) + val

    def calc_from_sources(
        self,
        *,
        base_stats: Mapping[int, float] | Mapping[str, float] = None,
        equip_stats: Iterable[Mapping[int, float] | Mapping[str, float]] = (),
        buff_stats: Iterable[Mapping[int, float] | Mapping[str, float]] = (),
        ignore_base_attack: bool = False,
    ) -> Dict[int, float]:
        acc = self._empty_values_by_id(ignore_base_attack=ignore_base_attack)

        if base_stats:
            self._add_dict_into(acc, base_stats)

        for d in equip_stats or ():
            self._add_dict_into(acc, d)

        for d in buff_stats or ():
            self._add_dict_into(acc, d)

        return acc

    def calc_for_character_model(self, char_model: Any) -> Dict[int, float]:
        base_by_code: Dict[str, float] = {}
        equip_dicts: List[Dict[str, float]] = []
        buff_dicts: List[Dict[str, float]] = []

        return self.calc_from_sources(
            base_stats=base_by_code,
            equip_stats=equip_dicts,
            buff_stats=buff_dicts,
        )

    def _hp_group_class_id(self, class_id: int | None, class_name: str | None) -> int | None:
        """
        В ClassLevelHpBonus Class_Id = это "группа" классов:
          1  - мечник/крестоносец/темный рыцарь
          4  - стрелок/снайпер/охотник
          7  - маг/волшебник/чернокнижник
          10 - вор/разбойник/ассасин
        """
        # если снаружи уже передают правильный group id — используем его
        if class_id in (1, 4, 7, 10):
            return int(class_id)
        n = (class_name or "").strip().lower()
        if any(k in n for k in ("мечник", "крестоносец", "темный рыцарь")):
            return 1
        if any(k in n for k in ("стрелок", "снайпер", "охотник")):
            return 4
        if any(k in n for k in ("маг", "волшебник", "чернокнижник")):
            return 7
        if any(k in n for k in ("вор", "разбойник", "ассасин")):
            return 10
        return None

    def _load_hp_from_db(self, hp_group_class_id: int, level: int) -> float | None:
        if not self.conn:
            return None
        try:
            row = self.conn.execute(
                "SELECT Value FROM ClassLevelHpBonus WHERE Class_Id = ? AND Level = ?",
                (int(hp_group_class_id), int(level)),
            ).fetchone()
            if not row:
                return None
            raw = row[0] if not hasattr(row, "keys") else row["Value"]
            if raw in (None, ""):
                return None
            return float(raw)
        except Exception:
            return None

    def _get_hp_for_class_level(self, class_id: int | None, level: int) -> float | None:
        """
        Возвращает точное ХП из ClassLevelHpBonus.Value для (class_id, level).
        Если таблицы/строки нет — вернёт None.
        """
        if not self.conn or not class_id:
            return None

        try:
            row = self.conn.execute(
                "SELECT Value FROM ClassLevelHpBonus WHERE Class_Id = ? AND Level = ?",
                (int(class_id), int(level)),
            ).fetchone()
            if not row:
                return None

            val = row[0] if not hasattr(row, "keys") else row["Value"]
            if val is None or val == "":
                return None
            return float(val)
        except Exception:
            return None

    def _class_id_from_name(self, class_name: str | None) -> int | None:
        """
        Маппинг имени класса -> Class_Id для таблицы ClassLevelHpBonus.
        1 - мечник/крестоносец/темный рыцарь
        4 - стрелок/снайпер/охотник
        7 - маг/волшебник/чернокнижник
        10 - вор/разбойник/ассасин
        """
        n = (class_name or "").strip().lower()

        if any(k in n for k in ("мечник", "крестоносец", "темный рыцарь")):
            return 1
        if any(k in n for k in ("стрелок", "снайпер", "охотник")):
            return 4
        if any(k in n for k in ("маг", "волшебник", "чернокнижник")):
            return 7
        if any(k in n for k in ("вор", "разбойник", "ассасин")):
            return 10

        return None

    def calc_for_character(
            self,
            *,
            class_id: int | None = None,
            class_name: str | None = None,
            level: int = 1,
            equipment_rows: Iterable[Mapping[int, float] | Mapping[str, float]] = (),
            buff_stats: Iterable[Mapping[int, float] | Mapping[str, float]] = (),
            base_stats: Mapping[int, float] | Mapping[str, float] = None,
            menu_bonus_enabled: Optional[Mapping[str, bool]] = None,
    ) -> Dict[int, float]:

        try:
            self._current_class_id = int(class_id) if class_id is not None else None
        except Exception:
            self._current_class_id = None

        try:
            self._current_level = int(level)
        except Exception:
            self._current_level = 1

        menu_flags = self._normalize_menu_bonus_enabled(menu_bonus_enabled)
        self.menu_bonus_enabled = dict(menu_flags)

        raw_equip = list(equipment_rows or ())

        equip_stat_dicts: list[Mapping[int, float] | Mapping[str, float]] = []
        equip_items: list[dict] = []
        selected_talents: List[dict] = []
        single_bonus_seen: set[int] = set()

        # МУЛЬТИПЛИКАТИВНЫЕ проценты: stat_id -> factor (Π(1+p/100))
        mul_prod: dict[int, float] = {}

        # Специальные бафовые множители, которые должны усиливаться
        # всеми остальными обычными множителями этого же стата.
        # stat_id -> [pct1, pct2, ...]
        special_mul_percent: Dict[int, List[float]] = {}

        def _mul_into(stat_id: int, pct: float) -> None:
            try:
                sid = int(stat_id)
                p = float(pct)
            except Exception:
                return
            if sid <= 0:
                return
            if abs(p) <= 1e-12:
                return
            f = 1.0 + p / 100.0
            mul_prod[sid] = float(mul_prod.get(sid, 1.0)) * float(f)

        def _normalize_equip_row(x) -> dict | None:
            if isinstance(x, dict):
                return x

            if isinstance(x, (tuple, list)):
                d: dict = {}

                if len(x) > 0:
                    d["_slot"] = x[0]
                if len(x) > 1 and x[1] not in (None, ""):
                    d["Id"] = x[1]
                if len(x) > 2 and x[2] not in (None, ""):
                    d["ForgeLevel"] = x[2]
                if len(x) > 3 and x[3] not in (None, ""):
                    d["TemplateId"] = x[3]
                if len(x) > 4 and x[4] not in (None, ""):
                    d["ProtoId"] = x[4]
                if len(x) > 5 and x[5] not in (None, ""):
                    d["_uuid"] = x[5]
                if len(x) > 6 and x[6] not in (None, ""):
                    d["_cards"] = x[6]

                return d

            return None

        for e in raw_equip:
            e = _normalize_equip_row(e)
            if not isinstance(e, dict):
                continue

            some_key = next(iter(e.keys()), None)

            if isinstance(some_key, int):
                equip_stat_dicts.append(e)
                continue

            if any(k in e for k in (
                    "Id", "Equip_Id", "Equipment_Id", "Item_Id", "TemplateId", "Template_Id", "ProtoId",
                    "StampId", "Stamp_Id", "_cards"
            )):
                equip_items.append(e)

        # --- state filtering weapon/offhand/spear ---
        cur_state = get_active_state_id()

        def _slot_text(it: dict) -> str:
            return str(
                it.get("_slot")
                or it.get("Slot")
                or it.get("slot")
                or it.get("SlotKey")
                or it.get("slot_key")
                or ""
            ).strip().lower()

        weapon_markers = (
            "weapon", "mainhand", "main_hand", "weapon1", "hand1", "primary",
            "right", "rhand", "right_hand",
            "оруж", "пра", "прав", "осн",
        )
        offhand_markers = (
            "offhand", "off_hand", "secondhand", "second_hand", "weapon2", "hand2", "secondary",
            "shield", "left", "lhand", "left_hand",
            "лева", "лев", "втор", "щит",
        )
        spear_markers = (
            "spear", "lance", "pike", "polearm", "halberd",
            "weapon3", "hand3", "thirdhand", "third_hand",
            "копь", "копье", "копьё", "пика", "алебард",
        )

        def _slot_kind(it: dict) -> str:
            s = _slot_text(it)
            if not s:
                return "other"
            if any(m in s for m in spear_markers):
                return "spear"
            if any(m in s for m in weapon_markers):
                return "weapon"
            if any(m in s for m in offhand_markers):
                return "offhand"
            return "other"

        if int(cur_state) == 1:
            equip_items = [it for it in (equip_items or []) if _slot_kind(it) != "spear"]
        elif int(cur_state) == 2:
            equip_items = [it for it in (equip_items or []) if _slot_kind(it) not in ("weapon", "offhand")]

        # --- context for BonusTypeStatCondition ---
        global _ACTIVE_EQUIP_TYPE_IDS_SET, _ACTIVE_WEAPON_EQUIP_TYPE_ID, _ACTIVE_OFFHAND_EQUIP_TYPE_ID

        _et_set: set[int] = set()
        _w_tid: int = 0
        _o_tid: int = 0
        weapon_like: list[tuple[str, int]] = []

        for _it in (equip_items or []):
            if not isinstance(_it, dict):
                continue

            _tid = _resolve_type_id(_it)

            if _tid <= 0 and self.conn is not None:
                for k in ("Id", "Equipment_Id", "Equip_Id", "Item_Id", "TemplateId", "Template_Id"):
                    if k not in _it or _it[k] in (None, ""):
                        continue
                    try:
                        cand = int(_it[k])
                    except Exception:
                        cand = 0
                    if cand <= 0:
                        continue
                    try:
                        row = self.conn.execute(
                            "SELECT Type_Id FROM Equipment WHERE Id=? LIMIT 1",
                            (int(cand),)
                        ).fetchone()
                        if row:
                            raw_tid = row["Type_Id"] if hasattr(row, "keys") else row[0]
                            _tid = int(raw_tid or 0)
                            if _tid > 0:
                                _it["Type_Id"] = int(_tid)
                                break
                    except Exception:
                        pass

            if _tid > 0:
                _et_set.add(int(_tid))

            _slot = str(_it.get("_slot") or _it.get("Slot") or _it.get("slot") or _it.get("SlotKey") or _it.get(
                "slot_key") or "")
            _s = _slot.strip().lower()
            tok = str(_it.get("_uuid") or _it.get("InstanceGuid") or _it.get("Id") or id(_it))

            if _s:
                if any(m in _s for m in weapon_markers):
                    if _tid > 0:
                        _w_tid = int(_tid)
                        weapon_like.append((tok, int(_tid)))
                    continue
                if any(m in _s for m in offhand_markers):
                    if _tid > 0:
                        _o_tid = int(_tid)
                        weapon_like.append((tok, int(_tid)))
                    continue

            if self.conn is not None and _tid > 0:
                try:
                    w = _is_weapon_type_by_equipmenttype(self.conn, int(_tid))
                except Exception:
                    w = None
                if w:
                    weapon_like.append((tok, int(_tid)))

        if _w_tid <= 0 and weapon_like:
            _w_tid = int(weapon_like[0][1])

        if _o_tid <= 0 and len(weapon_like) >= 2:
            first_tok = weapon_like[0][0]
            for tok, tid in weapon_like[1:]:
                if tok != first_tok:
                    _o_tid = int(tid)
                    break

        _ACTIVE_EQUIP_TYPE_IDS_SET = _et_set
        _ACTIVE_WEAPON_EQUIP_TYPE_ID = int(_w_tid)
        _ACTIVE_OFFHAND_EQUIP_TYPE_ID = int(_o_tid)

        has_weapon = self._has_weapon_equipped(equip_items)

        def _apply_hp_base_inplace(vals: Dict[int, float]) -> None:
            hp_group_id = self._hp_group_class_id(class_id=self._current_class_id, class_name=class_name)
            if hp_group_id is None:
                return
            hp_base = self._load_hp_from_db(hp_group_id, self._current_level)
            if hp_base is None:
                return

            default_hp = 0.0
            sd_hp = self.by_id.get(1)
            if sd_hp is not None:
                try:
                    default_hp = float(sd_hp.default_value or 0.0)
                except Exception:
                    default_hp = 0.0

            cur_hp = float(vals.get(1, 0.0) or 0.0)
            bonus_hp = cur_hp - default_hp
            vals[1] = float(hp_base) + float(bonus_hp)

        def _apply_mul_inplace(
                vals: Dict[int, float],
                mul_prod_map: Dict[int, float],
                *,
                grouped_mul: Dict[int, Dict[int, float]] | None = None,
        ) -> None:
            """
            mul_prod_map: stat_id -> factor (Π(1+p/100))
            grouped_mul: stat_id -> {group_key: pct_equiv} (если нужно отдельно перемножать группы)
            """

            def _apply_factor(stat_id: int, factor: float) -> None:
                try:
                    f = float(factor)
                except Exception:
                    return
                if abs(f - 1.0) <= 1e-12:
                    return
                base_v = float(vals.get(int(stat_id), 0.0) or 0.0)
                vals[int(stat_id)] = base_v * f

            for sid, factor in (mul_prod_map or {}).items():
                _apply_factor(int(sid), factor)

            if grouped_mul:
                for sid, groups in grouped_mul.items():
                    if not groups:
                        continue
                    base_v = float(vals.get(int(sid), 0.0) or 0.0)
                    mul_total = 1.0
                    for _gk, pct_equiv in groups.items():
                        try:
                            p = float(pct_equiv or 0.0)
                        except Exception:
                            p = 0.0
                        if abs(p) <= 1e-12:
                            continue
                        mul_total *= (1.0 + p / 100.0)
                    if abs(mul_total - 1.0) > 1e-12:
                        vals[int(sid)] = base_v * mul_total

        # ------------------------------------------------------------------
        # 1) Считаем статы от equip_items
        # ------------------------------------------------------------------
        grouped_mul_percent: Dict[int, Dict[int, float]] = {}

        equip_add_from_items: dict[int, float] = {}
        equip_mul_from_items: dict[int, float] = {}

        if self.conn is not None and equip_items:
            try:
                equip_add_from_items, equip_mul_from_items = compute_equipment_bonus_stats_via_bonustype(
                    self.conn,
                    list(equip_items),
                    return_parts=True,
                    debug=True,
                    MULTIPLY_DIV=100,
                    player_level=self._current_level,
                    single_bonus_seen=single_bonus_seen,
                )
            except Exception:
                equip_add_from_items, equip_mul_from_items = {}, {}

            for k, v in (equip_mul_from_items or {}).items():
                try:
                    ik = int(k)
                    fv = float(v)
                except Exception:
                    continue
                if abs(fv) <= 1e-12:
                    continue
                _mul_into(ik, fv)

        # ------------------------------------------------------------------
        # 1.5) Бонусы коллекций
        # ------------------------------------------------------------------
        if self.conn is not None and self._is_menu_bonus_enabled(menu_flags, "collect"):
            try:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
                raw_ids = app.property("collection_in_col_ids") if app is not None else None
            except Exception:
                raw_ids = None

            col_ids: list[int] = []
            if isinstance(raw_ids, (list, tuple, set)):
                for x in raw_ids:
                    try:
                        v = int(x)
                    except Exception:
                        continue
                    if v > 0:
                        col_ids.append(int(v))

            if col_ids:
                col_ids = sorted(set(col_ids))

                try:
                    has_tbl = self.conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='CollectedItemBonus' LIMIT 1"
                    ).fetchone()
                except Exception:
                    has_tbl = None

                if has_tbl:
                    CHUNK = 900
                    for i0 in range(0, len(col_ids), CHUNK):
                        chunk = col_ids[i0:i0 + CHUNK]
                        if not chunk:
                            continue
                        ph = ",".join(["?"] * len(chunk))
                        try:
                            rows = self.conn.execute(
                                f"""
                                SELECT CollectedItem_Id, Type_Id, Value
                                FROM CollectedItemBonus
                                WHERE CollectedItem_Id IN ({ph})
                                ORDER BY CollectedItem_Id, OrderIndex
                                """,
                                tuple(int(x) for x in chunk),
                            ).fetchall()
                        except Exception:
                            rows = []

                        for r in rows or []:
                            try:
                                if hasattr(r, "keys"):
                                    bt_id = int(r["Type_Id"] or 0)
                                    val = float(r["Value"] or 0)
                                else:
                                    bt_id = int(r[1] or 0)
                                    val = float(r[2] or 0)
                            except Exception:
                                continue

                            if bt_id <= 0 or abs(float(val)) <= 1e-12:
                                continue

                            if not _take_bonus_type_once(self.conn, single_bonus_seen, int(bt_id)):
                                continue

                            bts = _load_bonustype_stat_map(self.conn, int(bt_id))
                            if not bts:
                                continue

                            fb = float(val)
                            for _vi, sid, is_mul in bts:
                                if abs(fb) <= 1e-12:
                                    continue
                                stat_id = int(sid)
                                if stat_id <= 0:
                                    continue
                                if int(is_mul) == 1:
                                    _mul_into(stat_id, fb)
                                else:
                                    equip_add_from_items[stat_id] = float(equip_add_from_items.get(stat_id, 0.0)) + fb

        # ------------------------------------------------------------------
        # 1.745) Таланты персонажа из меню талантов
        # ------------------------------------------------------------------
        if self.conn is not None:
            selected_talents = self._get_player_talents()
        else:
            selected_talents = []

        if self.conn is not None and self._is_menu_bonus_enabled(menu_flags, "talents"):
            if selected_talents:
                talents_add, talents_mul = self._compute_player_talents_bonus(
                    selected_talents,
                    single_bonus_seen=single_bonus_seen,
                )

                for sid, val in (talents_add or {}).items():
                    try:
                        stat_id = int(sid)
                        fv = float(val)
                    except Exception:
                        continue
                    if stat_id <= 0 or abs(fv) <= 1e-12:
                        continue
                    equip_add_from_items[stat_id] = float(equip_add_from_items.get(stat_id, 0.0)) + fv

                for sid, val in (talents_mul or {}).items():
                    try:
                        stat_id = int(sid)
                        fv = float(val)
                    except Exception:
                        continue
                    if stat_id <= 0 or abs(fv) <= 1e-12:
                        continue
                    _mul_into(stat_id, fv)

        # ------------------------------------------------------------------
        # 1.75) Эликсир персонажа из нижнего меню
        # ------------------------------------------------------------------
        if self.conn is not None and self._is_menu_bonus_enabled(menu_flags, "elixir"):
            payload = self._get_player_elixir_payload()
            if isinstance(payload, dict):
                blist = payload.get("Bonuses") or payload.get("bonuses") or []
                for b in (blist or []):
                    if not isinstance(b, dict):
                        continue

                    try:
                        bt_id = int(b.get("Type_Id") or b.get("TypeId") or b.get("Type") or 0)
                    except Exception:
                        bt_id = 0

                    try:
                        val = float(b.get("Value") or b.get("Val") or 0.0)
                    except Exception:
                        val = 0.0

                    if bt_id <= 0 or abs(val) <= 1e-12:
                        continue

                    if not _take_bonus_type_once(self.conn, single_bonus_seen, int(bt_id)):
                        continue

                    bts = _load_bonustype_stat_map(self.conn, int(bt_id))
                    if not bts:
                        continue

                    for _vi, sid, is_mul in bts:
                        stat_id = int(sid)
                        if stat_id <= 0:
                            continue

                        if int(is_mul) == 1:
                            _mul_into(stat_id, float(val))
                        else:
                            equip_add_from_items[stat_id] = float(equip_add_from_items.get(stat_id, 0.0)) + float(val)

        # ------------------------------------------------------------------
        # 1.755) Гильдейские таланты из нижнего меню
        # ------------------------------------------------------------------
        if self.conn is not None and self._is_menu_bonus_enabled(menu_flags, "guild"):
            guild_selected = self._get_player_guild_talents()
            if guild_selected:
                guild_add, guild_mul = self._compute_player_guild_talents_bonus(
                    guild_selected,
                    single_bonus_seen=single_bonus_seen,
                )

                for sid, val in (guild_add or {}).items():
                    try:
                        stat_id = int(sid)
                        fv = float(val)
                    except Exception:
                        continue
                    if stat_id <= 0 or abs(fv) <= 1e-12:
                        continue
                    equip_add_from_items[stat_id] = float(equip_add_from_items.get(stat_id, 0.0)) + fv

                for sid, val in (guild_mul or {}).items():
                    try:
                        stat_id = int(sid)
                        fv = float(val)
                    except Exception:
                        continue
                    if stat_id <= 0 or abs(fv) <= 1e-12:
                        continue
                    _mul_into(stat_id, fv)

        # ------------------------------------------------------------------
        # 1.76) Расходники персонажа из нижнего меню
        # ------------------------------------------------------------------
        if self.conn is not None and (
                self._is_menu_bonus_enabled(menu_flags, "consum")
                or self._is_menu_bonus_enabled(menu_flags, "consumble")
        ):
            payloads = self._get_player_consumables_payloads()
            for payload in (payloads or []):
                if not isinstance(payload, dict):
                    continue

                blist = payload.get("Bonuses") or payload.get("bonuses") or []
                for b in (blist or []):
                    if not isinstance(b, dict):
                        continue

                    try:
                        bt_id = int(b.get("Type_Id") or b.get("TypeId") or b.get("Type") or 0)
                    except Exception:
                        bt_id = 0

                    try:
                        val = float(b.get("Value") or b.get("Val") or 0.0)
                    except Exception:
                        val = 0.0

                    if bt_id <= 0 or abs(val) <= 1e-12:
                        continue

                    if not _take_bonus_type_once(self.conn, single_bonus_seen, int(bt_id)):
                        continue

                    bts = _load_bonustype_stat_map(self.conn, int(bt_id))
                    if not bts:
                        continue

                    for _vi, sid, is_mul in bts:
                        stat_id = int(sid)
                        if stat_id <= 0:
                            continue

                        if int(is_mul) == 1:
                            _mul_into(stat_id, float(val))
                        else:
                            equip_add_from_items[stat_id] = float(equip_add_from_items.get(stat_id, 0.0)) + float(val)

        # ------------------------------------------------------------------
        # 1.77) Ауры персонажа из меню аур
        # ------------------------------------------------------------------
        if self.conn is not None and self._is_menu_bonus_enabled(menu_flags, "aura"):
            personal_aura_id = self._get_player_personal_aura_id()
            general_aura_ids = self._get_player_general_aura_ids()
            general_use_talents_map = self._get_player_general_aura_use_talents_map()

            aura_selected_talents = (
                selected_talents
                if self._is_menu_bonus_enabled(menu_flags, "talents")
                else []
            )

            aura_add, aura_mul = self._compute_player_auras_bonus(
                personal_aura_id=personal_aura_id,
                general_aura_ids=general_aura_ids,
                general_use_talents_map=general_use_talents_map,
                selected_talents=aura_selected_talents,
                single_bonus_seen=single_bonus_seen,
            )

            for sid, val in (aura_add or {}).items():
                try:
                    stat_id = int(sid)
                    fv = float(val)
                except Exception:
                    continue
                if stat_id <= 0 or abs(fv) <= 1e-12:
                    continue
                equip_add_from_items[stat_id] = float(equip_add_from_items.get(stat_id, 0.0)) + fv

            for sid, val in (aura_mul or {}).items():
                try:
                    stat_id = int(sid)
                    fv = float(val)
                except Exception:
                    continue
                if stat_id <= 0 or abs(fv) <= 1e-12:
                    continue
                _mul_into(stat_id, fv)

        # ------------------------------------------------------------------
        # 1.78) Бафы / дебафы из меню бафов
        # ------------------------------------------------------------------
        if self.conn is not None and self._is_menu_bonus_enabled(menu_flags, "buffs"):
            buff_ids = self._get_player_buff_ids()
            buff_stack_map = self._get_player_buff_stack_map()

            buff_selected_talents = (
                selected_talents
                if self._is_menu_bonus_enabled(menu_flags, "talents")
                else []
            )

            buff_add, buff_mul, buff_special_mul = self._compute_player_buffs_bonus(
                selected_buff_ids=buff_ids,
                buff_stack_map=buff_stack_map,
                selected_talents=buff_selected_talents,
                single_bonus_seen=single_bonus_seen,
            )

            for sid, val in (buff_add or {}).items():
                try:
                    stat_id = int(sid)
                    fv = float(val)
                except Exception:
                    continue
                if stat_id <= 0 or abs(fv) <= 1e-12:
                    continue
                equip_add_from_items[stat_id] = float(equip_add_from_items.get(stat_id, 0.0)) + fv

            for sid, val in (buff_mul or {}).items():
                try:
                    stat_id = int(sid)
                    fv = float(val)
                except Exception:
                    continue
                if stat_id <= 0 or abs(fv) <= 1e-12:
                    continue
                _mul_into(stat_id, fv)

            for sid, vals_list in (buff_special_mul or {}).items():
                try:
                    stat_id = int(sid)
                except Exception:
                    continue
                if stat_id <= 0:
                    continue

                dst = special_mul_percent.setdefault(stat_id, [])
                for raw_v in (vals_list or []):
                    try:
                        fv = float(raw_v)
                    except Exception:
                        continue
                    if abs(fv) <= 1e-12:
                        continue
                    dst.append(float(fv))

        # ------------------------------------------------------------------
        # 2) База
        # ------------------------------------------------------------------
        vals = self._empty_values_by_id(ignore_base_attack=has_weapon)

        if base_stats:
            self._add_dict_into(vals, base_stats)

        for d in equip_stat_dicts or ():
            self._add_dict_into(vals, d)

        if equip_add_from_items:
            self._add_dict_into(vals, equip_add_from_items)

        # Внешние бонусы/бафы:
        # 1) если в dict есть _menu_bonus_key / menu_bonus_key / MenuBonusKey -> фильтруем по нему
        # 2) если ключа нет -> это общий поток "buffs"
        for d in buff_stats or ():
            try:
                src_key = ""
                if isinstance(d, Mapping):
                    src_key = str(
                        d.get("_menu_bonus_key")
                        or d.get("menu_bonus_key")
                        or d.get("MenuBonusKey")
                        or ""
                    ).strip().lower()
            except Exception:
                src_key = ""

            if src_key:
                if not self._is_menu_bonus_enabled(menu_flags, src_key):
                    continue
            else:
                if not self._is_menu_bonus_enabled(menu_flags, "buffs"):
                    continue

            self._add_dict_into(vals, d)

        # ------------------------------------------------------------------
        # 2.5) VarIndex=2 динамика (добавки/проценты)
        # ------------------------------------------------------------------
        if self.conn is not None and equip_items:
            try:
                equipped_card_ids: list[int] = []
                for it in (equip_items or []):
                    cards = it.get("_cards") or []
                    if isinstance(cards, dict):
                        cards = list(cards.values())
                    if isinstance(cards, (list, tuple)):
                        for c in cards:
                            cid = _resolve_card_id_from_entry(c)
                            if cid > 0:
                                equipped_card_ids.append(int(cid))
                equipped_ctx = tuple(equipped_card_ids)
            except Exception:
                equipped_ctx = tuple()

            dyn_add: dict[int, float] = {}
            dyn_mul: dict[int, float] = {}

            for it in (equip_items or []):
                if not isinstance(it, dict):
                    continue
                try:
                    da, dm = compute_cards_bonus_stats_varindex2_for_item(
                        self.conn,
                        it,
                        current_stats=vals,
                        equipped_card_ids=equipped_ctx,
                        debug=False,
                        allowed_bonus_type_ids=it.get("_accepted_card_bonus_type_ids"),
                    )
                except Exception:
                    continue

                for sid, v in (da or {}).items():
                    try:
                        isid = int(sid)
                        fv = float(v)
                    except Exception:
                        continue
                    if abs(fv) <= 1e-12:
                        continue
                    dyn_add[isid] = float(dyn_add.get(isid, 0.0)) + fv

                for sid, v in (dm or {}).items():
                    try:
                        isid = int(sid)
                        fv = float(v)
                    except Exception:
                        continue
                    if abs(fv) <= 1e-12:
                        continue
                    dyn_mul[isid] = float(dyn_mul.get(isid, 0.0)) + float(fv)

            if dyn_add:
                self._add_dict_into(vals, dyn_add)

            if dyn_mul:
                for sid, v in dyn_mul.items():
                    _mul_into(int(sid), float(v))

        # ------------------------------------------------------------------
        # 3) Производные
        # ------------------------------------------------------------------
        self._apply_param_rules_inplace(vals, class_id=self._current_class_id, class_name=class_name)

        # ------------------------------------------------------------------
        # 4) HP base
        # ------------------------------------------------------------------
        _apply_hp_base_inplace(vals)

        # ------------------------------------------------------------------
        # 5) Применяем обычные множители %
        # ------------------------------------------------------------------
        _apply_mul_inplace(vals, mul_prod, grouped_mul=grouped_mul_percent)

        # ------------------------------------------------------------------
        # 5.1) Применяем специальные бафовые множители
        #      вида "процент, усиленный всеми остальными множителями"
        # ------------------------------------------------------------------
        if special_mul_percent:
            for sid, vals_list in (special_mul_percent or {}).items():
                try:
                    stat_id = int(sid)
                except Exception:
                    continue

                if stat_id <= 0 or not vals_list:
                    continue

                # Базовый общий множитель стата без самих спец-бафов.
                total_other_factor = float(mul_prod.get(stat_id, 1.0) or 1.0)

                # если по этому стату есть grouped_mul — тоже включаем в общий множитель
                try:
                    groups = (grouped_mul_percent or {}).get(stat_id, {}) or {}
                    for _gk, pct_equiv in groups.items():
                        p = float(pct_equiv or 0.0)
                        if abs(p) <= 1e-12:
                            continue
                        total_other_factor *= (1.0 + p / 100.0)
                except Exception:
                    pass

                cur_val = float(vals.get(stat_id, 0.0) or 0.0)
                if abs(cur_val) <= 1e-12:
                    continue

                special_factor = 1.0
                for raw_pct in (vals_list or []):
                    try:
                        pct = float(raw_pct or 0.0)
                    except Exception:
                        continue
                    if abs(pct) <= 1e-12:
                        continue

                    special_factor *= (1.0 + (pct * total_other_factor) / 100.0)

                if abs(special_factor - 1.0) > 1e-12:
                    vals[stat_id] = cur_val * special_factor

        return vals


class _StatInfoTooltip(QFrame):
    def __init__(self):
        super().__init__(
            None,
            Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setObjectName("statInfoTooltip")
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

    def set_content(self, title: str, body_html: str, max_w: int = 250) -> None:
        title = html.escape(str(title or "").strip() or "—")

        body = str(body_html or "").strip()
        if not body:
            body = "—"

        body = body.replace("\r\n", "\n").replace("\r", "\n")
        if "\n" in body:
            body = body.replace("\n", "<br>")

        color_title = "#f2c45d"
        color_text = "#f2f2f2"

        html_text = (
            "<div>"
            f"<div style='color:{color_title}; font-weight:700; font-size:14px;'>"
            f"{title}"
            f"</div>"
            f"<div style='color:{color_text}; font-size:12px; margin-top:6px;'>"
            f"{body}"
            f"</div>"
            "</div>"
        )

        self._lab.setText(html_text)
        self._lab.setFixedWidth(int(max_w))
        self._lab.adjustSize()

        pad_x = 11
        pad_y = 9

        self._lab.move(pad_x, pad_y)
        self.resize(
            self._lab.width() + pad_x * 2,
            self._lab.height() + pad_y * 2,
        )

    def show_at(self, global_pos: QPoint) -> None:
        pos = QPoint(global_pos)

        try:
            scr_obj = QApplication.screenAt(pos) or QApplication.primaryScreen()
            scr = scr_obj.availableGeometry() if scr_obj is not None else QRect(0, 0, 1920, 1080)

            margin = 6

            x = int(pos.x())
            y = int(pos.y())

            if x + self.width() > scr.right() - margin:
                x = int(scr.right() - self.width() - margin)

            if y + self.height() > scr.bottom() - margin:
                y = int(pos.y() - self.height() - 12)

            x = max(int(scr.left() + margin), int(x))
            y = max(int(scr.top() + margin), int(y))

            pos = QPoint(x, y)
        except Exception:
            pass

        self.move(pos)
        self.show()
        self.raise_()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect().adjusted(1, 1, -2, -2)

        # Чёрный фон с прозрачностью около 90%.
        p.setBrush(QColor(0, 0, 0, 230))

        # Металлическая обводка 2 px.
        p.setPen(QPen(QColor(145, 140, 128, 235), 2))

        # Для статов делаем окно более округлым.
        p.drawRoundedRect(r, 11, 11)

        p.end()
        super().paintEvent(ev)
# ---------------------------------------------------------------------------
# 3) UI: панель статов справа от персонажа
# ---------------------------------------------------------------------------
class StatRowWidget(QWidget):
    """
    Одна строка вида:

        Атака                53

    Для строк "Параметры" добавляются кнопки:
      [minus]  VALUE  [plus] [plus_all]

    Дополнительно:
      - при наведении (удержать курсор 2 секунды) показывает подробное описание стата
        из Stat.DescriptionTemplate с подстановкой {0}.
      - если у стата задан Stat.DescriptionFormula_Id — значение для {0} вычисляется по формуле.
    """

    # сигналы клика (пока только наружу отдаём stat_id)
    minusClicked = Signal(int)
    plusClicked = Signal(int)
    plusAllClicked = Signal(int)

    # X-координаты внутри строки
    NAME_X = 4
    VALUE_X = 170
    RIGHT_PADDING = 60

    BTN_W = 22
    BTN_H = 20

    MINUS_OFFSET_X = -2
    RIGHT_BTNS_OFFSET_X = 0

    BTN_GAP = 2

    RIGHT_PADDING_WITH_BTNS = 60  # когда есть кнопки справа
    RIGHT_PADDING_NO_BTNS = 4  # когда кнопок нет (обычные статы)

    TOOLTIP_DELAY_MS = 2000

    # (id(conn), stat_id) -> (template, formula_id, round_digits)
    _TOOLTIP_META_CACHE: dict[tuple[int, int], tuple[Optional[str], Optional[int], Optional[int]]] = {}

    MARQUEE_ENABLED = False
    MARQUEE_INTERVAL_MS = 35
    MARQUEE_STEP = 1
    MARQUEE_EDGE_PAUSE_TICKS = 20

    def __init__(
            self,
            name: str,
            is_percent: bool = False,
            parent: QWidget | None = None,
            *,
            stat_id: int | None = None,
            adjustable: bool = False,  # только для "Параметры"
    ):
        super().__init__(parent)
        self._is_percent = is_percent
        self.stat_id = int(stat_id) if stat_id is not None else -1
        self._adjustable = bool(adjustable)

        # viewport для имени — чтобы можно было крутить текст внутри обрезаемой области
        self.name_viewport = QWidget(self)
        self.name_viewport.setStyleSheet("background: transparent;")
        try:
            self.name_viewport.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception:
            pass

        # viewport для значения — нужен для бегущей строки,
        # если значение упирается в область скроллбара / не помещается по ширине
        self.value_viewport = QWidget(self)
        self.value_viewport.setStyleSheet("background: transparent;")
        try:
            self.value_viewport.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception:
            pass

        self.lbl_name = QLabel(name, self.name_viewport)
        self.lbl_value = QLabel("—", self.value_viewport)

        f = self.lbl_name.font()
        f.setPointSizeF(11)
        self.lbl_name.setFont(f)
        self.lbl_value.setFont(f)

        self.lbl_name.setStyleSheet("color: #3b290c; background: transparent;")
        self.lbl_value.setStyleSheet("color: #000000; background: transparent;")

        self.lbl_name.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.lbl_value.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        try:
            self.lbl_name.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.lbl_value.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception:
            pass

        # кнопки (только если adjustable=True)
        self.btn_minus = None
        self.btn_plus = None
        self.btn_plus_all = None

        if self._adjustable:
            self.btn_minus = self._make_icon_btn("resources/main_menu/char_minus.png", fallback_text="-")
            self.btn_plus = self._make_icon_btn("resources/main_menu/char_plus.png", fallback_text="+")
            self.btn_plus_all = self._make_icon_btn("resources/main_menu/char_plus_all.png", fallback_text="++")

            self.btn_minus.clicked.connect(lambda: self.minusClicked.emit(self.stat_id))
            self.btn_plus.clicked.connect(lambda: self.plusClicked.emit(self.stat_id))
            self.btn_plus_all.clicked.connect(lambda: self.plusAllClicked.emit(self.stat_id))

            try:
                self.btn_minus.installEventFilter(self)
                self.btn_plus.installEventFilter(self)
                self.btn_plus_all.installEventFilter(self)
            except Exception:
                pass

        # --- tooltip state ---
        self._last_numeric_value: Optional[float] = None
        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.setInterval(int(self.TOOLTIP_DELAY_MS))
        self._tooltip_timer.timeout.connect(self._on_tooltip_timeout)

        # --- marquee имени ---
        self._base_name_text = str(name or "")
        self._marquee_offset = 0
        self._marquee_dir = 1
        self._marquee_pause_ticks = int(getattr(self, "MARQUEE_EDGE_PAUSE_TICKS", 20))
        self._marquee_overflow = 0

        self._marquee_timer = QTimer(self)
        self._marquee_timer.setInterval(int(getattr(self, "MARQUEE_INTERVAL_MS", 35)))
        self._marquee_timer.timeout.connect(self._tick_name_marquee)

        # --- marquee значения ---
        self._base_value_text = "—"
        self._value_marquee_offset = 0
        self._value_marquee_overflow = 0
        self._value_marquee_text_width = 0
        self._value_marquee_gap = 0
        self._value_marquee_cycle_width = 0

        self._value_marquee_timer = QTimer(self)
        self._value_marquee_timer.setInterval(int(getattr(self, "VALUE_MARQUEE_INTERVAL_MS", self.MARQUEE_INTERVAL_MS)))
        self._value_marquee_timer.timeout.connect(self._tick_value_marquee)

        self._update_geometry()

    def _refresh_name_marquee(self, reset: bool = False) -> None:
        base_text = str(getattr(self, "_base_name_text", self.lbl_name.text() or ""))
        self._base_name_text = base_text

        viewport_w = max(0, int(self.name_viewport.width()))
        viewport_h = max(0, int(self.name_viewport.height() or self.height() or 18))

        fm = QFontMetrics(self.lbl_name.font())

        # Ширина одной копии текста.
        # Запас нужен, чтобы крайний символ не подрезался.
        one_text_w = max(1, int(fm.horizontalAdvance(base_text)) + 8)

        # Реальный зазор между двумя отдельными QLabel.
        gap = max(24, int(getattr(self, "MARQUEE_GAP", 32) or 32))
        cycle_w = int(one_text_w + gap)

        self._marquee_text_width = int(one_text_w)
        self._marquee_gap = int(gap)
        self._marquee_cycle_width = int(cycle_w)

        enabled = bool(getattr(self, "MARQUEE_ENABLED", False))
        overflow = max(0, int(one_text_w - viewport_w))
        self._marquee_overflow = int(overflow)

        is_visible_now = bool(self.isVisible() and self.name_viewport.isVisible())
        try:
            wnd = self.window()
            if wnd is not None and not wnd.isVisible():
                is_visible_now = False
        except Exception:
            pass

        # Вторая копия текста создаётся лениво.
        lbl2 = getattr(self, "_marquee_lbl_2", None)
        if lbl2 is None:
            lbl2 = QLabel(self.name_viewport)
            lbl2.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lbl2.setStyleSheet(self.lbl_name.styleSheet())
            lbl2.setAlignment(self.lbl_name.alignment())
            lbl2.setFont(self.lbl_name.font())
            self._marquee_lbl_2 = lbl2

        if reset:
            self._marquee_offset = 0

        if enabled and overflow > 0 and is_visible_now:
            # ВАЖНО:
            # Больше не делаем одну строку "текст + пробелы + текст".
            # Две отдельные копии дают бесшовный цикл без рывка на стыке.
            if self.lbl_name.text() != base_text:
                self.lbl_name.setText(base_text)

            if lbl2.text() != base_text:
                lbl2.setText(base_text)

            try:
                lbl2.setFont(self.lbl_name.font())
                lbl2.setStyleSheet(self.lbl_name.styleSheet())
                lbl2.setAlignment(self.lbl_name.alignment())
            except Exception:
                pass

            try:
                self._marquee_offset = int(self._marquee_offset) % max(1, int(cycle_w))
            except Exception:
                self._marquee_offset = 0

            x1 = -int(self._marquee_offset)
            x2 = int(x1 + cycle_w)

            self.lbl_name.setGeometry(int(x1), 0, int(one_text_w), int(viewport_h))
            lbl2.setGeometry(int(x2), 0, int(one_text_w), int(viewport_h))

            self.lbl_name.show()
            lbl2.show()

            if not self._marquee_timer.isActive():
                self._marquee_timer.start()
        else:
            self._marquee_timer.stop()
            self._marquee_offset = 0

            if self.lbl_name.text() != base_text:
                self.lbl_name.setText(base_text)

            self.lbl_name.setGeometry(0, 0, int(one_text_w), int(viewport_h))
            self.lbl_name.show()

            try:
                lbl2.hide()
            except Exception:
                pass

    def _tick_name_marquee(self) -> None:
        if not bool(getattr(self, "MARQUEE_ENABLED", False)):
            self._marquee_timer.stop()
            self._marquee_offset = 0
            self.lbl_name.move(0, 0)

            try:
                lbl2 = getattr(self, "_marquee_lbl_2", None)
                if lbl2 is not None:
                    lbl2.hide()
            except Exception:
                pass

            return

        is_visible_now = bool(self.isVisible() and self.name_viewport.isVisible())
        try:
            wnd = self.window()
            if wnd is not None and not wnd.isVisible():
                is_visible_now = False
        except Exception:
            pass

        if not is_visible_now:
            self._marquee_timer.stop()
            self._marquee_offset = 0
            self.lbl_name.move(0, 0)

            try:
                lbl2 = getattr(self, "_marquee_lbl_2", None)
                if lbl2 is not None:
                    lbl2.hide()
            except Exception:
                pass

            return

        overflow = int(getattr(self, "_marquee_overflow", 0) or 0)
        cycle_w = int(getattr(self, "_marquee_cycle_width", 0) or 0)
        one_text_w = int(getattr(self, "_marquee_text_width", 0) or 0)

        if overflow <= 0 or cycle_w <= 0 or one_text_w <= 0:
            self._marquee_timer.stop()
            self._marquee_offset = 0
            self.lbl_name.move(0, 0)

            try:
                lbl2 = getattr(self, "_marquee_lbl_2", None)
                if lbl2 is not None:
                    lbl2.hide()
            except Exception:
                pass

            return

        lbl2 = getattr(self, "_marquee_lbl_2", None)
        if lbl2 is None:
            self._refresh_name_marquee(reset=False)
            return

        step = max(1, int(getattr(self, "MARQUEE_STEP", 1)))

        # Сохраняем перелёт через границу цикла.
        # Визуально это бесшовно, потому что рядом едет вторая копия QLabel.
        self._marquee_offset = (int(self._marquee_offset) + int(step)) % int(cycle_w)

        x1 = -int(self._marquee_offset)
        x2 = int(x1 + cycle_w)

        self.lbl_name.move(int(x1), 0)
        lbl2.move(int(x2), 0)

        if not lbl2.isVisible():
            lbl2.show()

    def _refresh_value_marquee(self, reset: bool = False) -> None:
        """
        Бегущая строка для значения справа.
        Используется в меню "Прочее", когда значение не помещается в доступную область
        и иначе залезает под скроллбар.
        """
        base_text = str(getattr(self, "_base_value_text", self.lbl_value.text() or ""))
        self._base_value_text = base_text

        viewport_w = max(0, int(self.value_viewport.width()))
        viewport_h = max(0, int(self.value_viewport.height() or self.height() or 18))

        fm = QFontMetrics(self.lbl_value.font())

        one_text_w = max(1, int(fm.horizontalAdvance(base_text)) + 8)
        gap = max(24, int(getattr(self, "VALUE_MARQUEE_GAP", getattr(self, "MARQUEE_GAP", 32)) or 32))
        cycle_w = int(one_text_w + gap)

        self._value_marquee_text_width = int(one_text_w)
        self._value_marquee_gap = int(gap)
        self._value_marquee_cycle_width = int(cycle_w)

        enabled = bool(getattr(self, "VALUE_MARQUEE_ENABLED", False))
        overflow = max(0, int(one_text_w - viewport_w))
        self._value_marquee_overflow = int(overflow)

        is_visible_now = bool(self.isVisible() and self.value_viewport.isVisible())
        try:
            wnd = self.window()
            if wnd is not None and not wnd.isVisible():
                is_visible_now = False
        except Exception:
            pass

        lbl2 = getattr(self, "_value_marquee_lbl_2", None)
        if lbl2 is None:
            lbl2 = QLabel(self.value_viewport)
            lbl2.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lbl2.setStyleSheet(self.lbl_value.styleSheet())
            lbl2.setAlignment(self.lbl_value.alignment())
            lbl2.setFont(self.lbl_value.font())
            self._value_marquee_lbl_2 = lbl2

        if reset:
            self._value_marquee_offset = 0

        if enabled and overflow > 0 and is_visible_now:
            if self.lbl_value.text() != base_text:
                self.lbl_value.setText(base_text)

            if lbl2.text() != base_text:
                lbl2.setText(base_text)

            try:
                lbl2.setFont(self.lbl_value.font())
                lbl2.setStyleSheet(self.lbl_value.styleSheet())
                lbl2.setAlignment(self.lbl_value.alignment())
            except Exception:
                pass

            try:
                self._value_marquee_offset = int(self._value_marquee_offset) % max(1, int(cycle_w))
            except Exception:
                self._value_marquee_offset = 0

            x1 = -int(self._value_marquee_offset)
            x2 = int(x1 + cycle_w)

            self.lbl_value.setGeometry(int(x1), 0, int(one_text_w), int(viewport_h))
            lbl2.setGeometry(int(x2), 0, int(one_text_w), int(viewport_h))

            self.lbl_value.show()
            lbl2.show()

            if not self._value_marquee_timer.isActive():
                self._value_marquee_timer.start()
        else:
            self._value_marquee_timer.stop()
            self._value_marquee_offset = 0

            if self.lbl_value.text() != base_text:
                self.lbl_value.setText(base_text)

            self.lbl_value.setGeometry(0, 0, int(one_text_w), int(viewport_h))
            self.lbl_value.show()

            try:
                lbl2.hide()
            except Exception:
                pass

    def _tick_value_marquee(self) -> None:
        if not bool(getattr(self, "VALUE_MARQUEE_ENABLED", False)):
            self._value_marquee_timer.stop()
            self._value_marquee_offset = 0
            self.lbl_value.move(0, 0)

            try:
                lbl2 = getattr(self, "_value_marquee_lbl_2", None)
                if lbl2 is not None:
                    lbl2.hide()
            except Exception:
                pass

            return

        is_visible_now = bool(self.isVisible() and self.value_viewport.isVisible())
        try:
            wnd = self.window()
            if wnd is not None and not wnd.isVisible():
                is_visible_now = False
        except Exception:
            pass

        if not is_visible_now:
            self._value_marquee_timer.stop()
            self._value_marquee_offset = 0
            self.lbl_value.move(0, 0)

            try:
                lbl2 = getattr(self, "_value_marquee_lbl_2", None)
                if lbl2 is not None:
                    lbl2.hide()
            except Exception:
                pass

            return

        overflow = int(getattr(self, "_value_marquee_overflow", 0) or 0)
        cycle_w = int(getattr(self, "_value_marquee_cycle_width", 0) or 0)
        one_text_w = int(getattr(self, "_value_marquee_text_width", 0) or 0)

        if overflow <= 0 or cycle_w <= 0 or one_text_w <= 0:
            self._value_marquee_timer.stop()
            self._value_marquee_offset = 0
            self.lbl_value.move(0, 0)

            try:
                lbl2 = getattr(self, "_value_marquee_lbl_2", None)
                if lbl2 is not None:
                    lbl2.hide()
            except Exception:
                pass

            return

        lbl2 = getattr(self, "_value_marquee_lbl_2", None)
        if lbl2 is None:
            self._refresh_value_marquee(reset=False)
            return

        step = max(1, int(getattr(self, "VALUE_MARQUEE_STEP", getattr(self, "MARQUEE_STEP", 1))))

        self._value_marquee_offset = (int(self._value_marquee_offset) + int(step)) % int(cycle_w)

        x1 = -int(self._value_marquee_offset)
        x2 = int(x1 + cycle_w)

        self.lbl_value.move(int(x1), 0)
        lbl2.move(int(x2), 0)

        if not lbl2.isVisible():
            lbl2.show()

    def _make_icon_btn(self, rel_path: str, fallback_text: str = "") -> QPushButton:
        b = QPushButton(self)
        b.setFixedSize(self.BTN_W, self.BTN_H)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)

        # Сдвиг "вдавливания" (можешь менять)
        press_shift = 1

        b.setStyleSheet(f"""
            QPushButton {{
                border: 1px solid rgba(0,0,0,0);
                border-radius: 3px;
                background: transparent;
                padding: 0px;
            }}
            QPushButton:hover {{
                background: rgba(0, 0, 0, 0);
                border: 1px solid rgba(0, 0, 0, 0);
            }}
            QPushButton:pressed {{
                background: rgba(0, 0, 0, 0);
                border: 1px solid rgba(0, 0, 0, 0);
                padding-left: {press_shift}px;
                padding-top: {press_shift}px;
            }}
        """)

        pm = QPixmap(_res_path(rel_path))
        if not pm.isNull():
            b.setIcon(QIcon(pm))
            # чтобы при :pressed (padding) иконка не обрезалась
            b.setIconSize(QSize(self.BTN_W, self.BTN_H))
        else:
            b.setText(fallback_text)

        return b

    def _update_geometry(self) -> None:
        w = int(self.width() or 0)
        h = int(self.height() or 18)

        right_padding = self.RIGHT_PADDING_WITH_BTNS if self._adjustable else self.RIGHT_PADDING_NO_BTNS

        try:
            value_x = int(getattr(self, "VALUE_X", self.VALUE_X))
        except Exception:
            value_x = int(self.VALUE_X)

        try:
            min_value_w = int(getattr(self, "VALUE_MIN_W_NO_BTNS", 0) or 0)
        except Exception:
            min_value_w = 52

        if (not self._adjustable) and min_value_w > 0:
            max_value_x = w - right_padding - min_value_w
            min_value_x = self.NAME_X + 10
            value_x = max(min_value_x, min(value_x, max_value_x))

        value_width = max(0, w - value_x - right_padding)
        right_area_x = value_x + value_width + self.RIGHT_BTNS_OFFSET_X - 5

        minus_x = value_x - self.BTN_W - self.BTN_GAP + self.MINUS_OFFSET_X
        if self._adjustable:
            name_width = max(0, minus_x - self.NAME_X)
        else:
            name_width = max(0, value_x - self.NAME_X)

        self.name_viewport.setGeometry(self.NAME_X, 0, name_width, h)
        self.value_viewport.setGeometry(value_x, 0, value_width, h)

        self._refresh_name_marquee(reset=False)
        self._refresh_value_marquee(reset=False)

        if self._adjustable and self.btn_minus and self.btn_plus and self.btn_plus_all:
            y_btn = max(0, (h - self.BTN_H) // 2)
            self.btn_minus.setGeometry(minus_x, y_btn, self.BTN_W, self.BTN_H)
            self.btn_plus.setGeometry(right_area_x, y_btn, self.BTN_W, self.BTN_H)
            self.btn_plus_all.setGeometry(
                right_area_x + self.BTN_W + self.BTN_GAP, y_btn, self.BTN_W, self.BTN_H
            )

    def resizeEvent(self, event):
        self._update_geometry()
        super().resizeEvent(event)

    def set_name(self, name: str) -> None:
        self._base_name_text = str(name or "")
        self.lbl_name.setText(self._base_name_text)
        self._refresh_name_marquee(reset=True)

    def _format_value(self, value: Optional[float]) -> str:
        if value is None:
            return "—"

        try:
            v = float(value)
        except Exception:
            return str(value)

        # Для этих статов всегда показываем 2 знака после запятой
        # (15 — рейтинг крита; можно добавить сюда 11/23/24 если тоже хочешь всегда 2 знака)
        FORCE_2_DECIMALS = {15}

        if int(self.stat_id) in FORCE_2_DECIMALS:
            text = f"{v:.2f}"
        else:
            # если по факту целое (с допуском на float-погрешности)
            if abs(v - round(v)) < 1e-9:
                text = str(int(round(v)))
            else:
                # до 2 знаков, но убираем лишние нули
                text = f"{v:.2f}".rstrip("0").rstrip(".")

        if self._is_percent:
            text += "%"

        return text

    def set_value(self, value: Optional[float]) -> None:
        # сохраняем исходное числовое значение для формул тултипа
        try:
            self._last_numeric_value = None if value is None else float(value)
        except Exception:
            self._last_numeric_value = None

        text = self._format_value(value)

        old_text = str(getattr(self, "_base_value_text", "") or "")
        changed = old_text != str(text)

        self._base_value_text = str(text)

        if changed:
            if self.lbl_value.text() != text:
                self.lbl_value.setText(text)

            lbl2 = getattr(self, "_value_marquee_lbl_2", None)
            if lbl2 is not None and lbl2.text() != text:
                lbl2.setText(text)

            self._refresh_value_marquee(reset=True)
        else:
            # Значение не изменилось — не сбрасываем бегущую строку,
            # просто убеждаемся, что геометрия актуальна.
            self._refresh_value_marquee(reset=False)

    # ----------------------------- tooltip logic -----------------------------

    def _cursor_inside_self(self) -> bool:
        try:
            from PySide6.QtGui import QCursor
            gp = QCursor.pos()
            lp = self.mapFromGlobal(gp)
            return bool(self.rect().contains(lp))
        except Exception:
            return False

    def enterEvent(self, event):  # noqa: N802
        try:
            tip = getattr(self, "_custom_stat_tooltip", None)
            if tip is not None:
                tip.hide()
        except Exception:
            pass

        try:
            if self.stat_id > 0:
                self._tooltip_timer.stop()
                self._tooltip_timer.start()
        except Exception:
            pass

        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        # если ушли на дочерний виджет, например кнопки параметров,
        # курсор всё ещё внутри строки -> hover не сбрасываем
        if self._cursor_inside_self():
            try:
                event.ignore()
            except Exception:
                pass
            return

        try:
            self._tooltip_timer.stop()
        except Exception:
            pass

        try:
            tip = getattr(self, "_custom_stat_tooltip", None)
            if tip is not None:
                tip.hide()
        except Exception:
            pass

        try:
            from PySide6.QtWidgets import QToolTip
            QToolTip.hideText()
        except Exception:
            pass

        super().leaveEvent(event)

    def eventFilter(self, obj: QObject, event) -> bool:  # noqa: N802
        # если заходим на кнопки, но остаёмся в пределах строки —
        # считаем это продолжением hover
        try:
            et = event.type()

            if et == QEvent.Enter:
                if self.stat_id > 0:
                    try:
                        tip = getattr(self, "_custom_stat_tooltip", None)
                        if tip is not None:
                            tip.hide()
                    except Exception:
                        pass

                    self._tooltip_timer.stop()
                    self._tooltip_timer.start()

            elif et == QEvent.Leave:
                if not self._cursor_inside_self():
                    self._tooltip_timer.stop()

                    try:
                        tip = getattr(self, "_custom_stat_tooltip", None)
                        if tip is not None:
                            tip.hide()
                    except Exception:
                        pass

                    try:
                        from PySide6.QtWidgets import QToolTip
                        QToolTip.hideText()
                    except Exception:
                        pass

        except Exception:
            pass

        return super().eventFilter(obj, event)

    def _find_panel_like_parent(self):
        w = self.parent()
        # поднимаемся наверх пока не найдём объект с conn
        while w is not None:
            if hasattr(w, "conn"):
                return w
            try:
                w = w.parent()
            except Exception:
                break
        return None

    def _tooltip_meta(self, conn) -> tuple[Optional[str], Optional[int], Optional[int]]:
        if conn is None or self.stat_id <= 0:
            return (None, None, None)

        key = (id(conn), int(self.stat_id))
        cached = self._TOOLTIP_META_CACHE.get(key)
        if cached is not None:
            return cached

        tpl: Optional[str] = None
        fid: Optional[int] = None
        rd: Optional[int] = None

        row = None
        try:
            row = conn.execute(
                "SELECT DescriptionTemplate, DescriptionFormula_Id, RoundDigits "
                "FROM Stat WHERE Id=? LIMIT 1",
                (int(self.stat_id),),
            ).fetchone()
        except Exception:
            row = None

        if row is None:
            try:
                row = conn.execute(
                    "SELECT DescriptionTemplate, DescriptionFormula_Id "
                    "FROM Stat WHERE Id=? LIMIT 1",
                    (int(self.stat_id),),
                ).fetchone()
            except Exception:
                row = None

        if row is not None:
            try:
                tpl = str(row[0]) if row[0] is not None else None
            except Exception:
                tpl = None
            try:
                fid = int(row[1]) if row[1] is not None else None
            except Exception:
                fid = None
            try:
                if len(row) >= 3 and row[2] is not None:
                    rd = int(row[2])
            except Exception:
                rd = None

        if tpl is not None:
            tpl = tpl.strip()
            if not tpl:
                tpl = None

        if fid is not None and int(fid) <= 0:
            fid = None

        self._TOOLTIP_META_CACHE[key] = (tpl, fid, rd)
        return self._TOOLTIP_META_CACHE[key]

    def _format_tooltip_number(self, value: float, round_digits: Optional[int]) -> str:
        try:
            v = float(value)
        except Exception:
            return str(value)

        if round_digits is None:
            if abs(v - round(v)) < 1e-9:
                return str(int(round(v)))
            return f"{v:.2f}".rstrip("0").rstrip(".")

        try:
            d = int(round_digits)
        except Exception:
            d = 0

        if d <= 0:
            return str(int(round(v)))

        return f"{v:.{d}f}".rstrip("0").rstrip(".")

    def _calc_formula_value(self, formula_id: int, v: float, *, level: int) -> float:
        fid = int(formula_id or 0)
        vv = float(v)

        def _apply_formula_local(fid_local: int | None, raw_value: float) -> float:
            try:
                ffid = int(fid_local or 0)
            except Exception:
                ffid = 0

            rv = float(raw_value or 0.0)

            if ffid == 11:
                denom = (rv / 100.0) + 1.0
                return 0.0 if abs(denom) <= 1e-12 else (rv / denom)

            if ffid == 12:
                return rv - 100.0

            if ffid == 13:
                armor_bl = float(_armor_bl_for_level(int(level or 1)))
                if armor_bl <= 1e-12:
                    return 0.0
                return 100.0 * (1.0 - 1.0 / (1.0 + rv / armor_bl))

            if ffid == 20:
                lvl = float(int(level or 1))
                power = rv * (-0.6491 * lvl + 60.1007)
                return (1.0 - math.pow(0.999, power)) * 60.0

            return rv

        if fid == 18:
            panel = self._find_panel_like_parent()
            raw_vals = getattr(panel, "_last_values_by_id", {}) if panel is not None else {}

            try:
                hp = float(raw_vals.get(1, 0.0) or 0.0)
            except Exception:
                hp = 0.0

            try:
                armor_raw = float(raw_vals.get(12, 0.0) or 0.0)
            except Exception:
                armor_raw = 0.0

            def_resist = _apply_formula_local(13, armor_raw)
            denom = 1.0 - (float(def_resist) / 100.0)
            return 0.0 if hp <= 0.0 else (float(hp) / max(1e-12, denom))

        if fid == 19:
            panel = self._find_panel_like_parent()
            conn = getattr(panel, "conn", None) if panel is not None else None
            raw_vals = getattr(panel, "_last_values_by_id", {}) if panel is not None else {}

            try:
                hp = float(raw_vals.get(1, 0.0) or 0.0)
            except Exception:
                hp = 0.0

            try:
                pvp_raw = float(raw_vals.get(48, 0.0) or 0.0)
            except Exception:
                pvp_raw = 0.0

            pvp_fid = None
            if conn is not None:
                cache = getattr(self, "_FORMULA_BY_STAT_CACHE", None)
                if not isinstance(cache, dict):
                    self._FORMULA_BY_STAT_CACHE = {}
                    cache = self._FORMULA_BY_STAT_CACHE

                key = (id(conn), 48)
                if key not in cache:
                    try:
                        row = conn.execute(
                            "SELECT DescriptionFormula_Id FROM Stat WHERE Id=? LIMIT 1",
                            (48,),
                        ).fetchone()
                        if row is not None:
                            val = row[0] if not hasattr(row, "keys") else row["DescriptionFormula_Id"]
                            cache[key] = int(val) if val is not None else None
                        else:
                            cache[key] = None
                    except Exception:
                        cache[key] = None

                pvp_fid = cache.get(key)

            pvp_resist = _apply_formula_local(pvp_fid, pvp_raw)
            denom = 1.0 - (float(pvp_resist) / 100.0)
            return 0.0 if hp <= 0.0 else (float(hp) / max(1e-12, denom))

        if fid == 11:
            denom = (vv / 100.0) + 1.0
            return 0.0 if abs(denom) <= 1e-12 else (vv / denom)

        if fid == 12:
            return vv - 100.0

        if fid == 13:
            armor_bl = float(_armor_bl_for_level(int(level or 1)))
            if armor_bl <= 1e-12:
                return 0.0
            return 100.0 * (1.0 - 1.0 / (1.0 + vv / armor_bl))

        if fid == 15 and int(getattr(self, "stat_id", 0) or 0) == 75:
            try:
                panel = self._find_panel_like_parent()
            except Exception:
                panel = None

            try:
                math_obj = getattr(panel, "math", None) if panel is not None else None
                dbg_map = getattr(math_obj, "_formula15_debug_by_stat", None) if math_obj is not None else None
                if isinstance(dbg_map, dict):
                    dbg = dbg_map.get(75)
                    if isinstance(dbg, dict):
                        return float(dbg.get("DPS_total", vv) or vv)
            except Exception:
                pass

        if fid == 20:
            lvl = float(int(level or 1))
            power = vv * (-0.6491 * lvl + 60.1007)
            return (1.0 - math.pow(0.999, power)) * 60.0

        return vv

    def _build_tooltip_text(self) -> Optional[str]:
        panel = self._find_panel_like_parent()
        conn = getattr(panel, "conn", None) if panel is not None else None
        if conn is None or self.stat_id <= 0:
            return None

        tpl, fid, rd = self._tooltip_meta(conn)

        level = 1
        try:
            level = int(getattr(panel, "_last_level_seen", None) or 0) or 0
        except Exception:
            level = 0

        if level <= 0:
            try:
                math_obj = getattr(panel, "math", None)
                level = int(getattr(math_obj, "_current_level", 0) or 0)
            except Exception:
                level = 0

        if level <= 0:
            level = 1

        if int(fid or 0) == 15 and int(self.stat_id) == 75:
            try:
                math_obj = getattr(panel, "math", None)
                dbg_map = getattr(math_obj, "_formula15_debug_by_stat", None) if math_obj is not None else None
                dbg = dbg_map.get(75) if isinstance(dbg_map, dict) else None
            except Exception:
                dbg = None

            if isinstance(dbg, dict):
                def _fmt_num(x: Any, digits: int = 4) -> str:
                    try:
                        xf = float(x)
                    except Exception:
                        return str(x)

                    if abs(xf - round(xf)) < 1e-12:
                        return str(int(round(xf)))

                    return f"{xf:.{int(digits)}f}".rstrip("0").rstrip(".")

                def _fmt_pct_direct(x: Any, digits: int = 2) -> str:
                    try:
                        xf = float(x)
                    except Exception:
                        return "0%"
                    return f"{xf:.{int(digits)}f}".rstrip("0").rstrip(".") + "%"

                def _fmt_mul(x: Any, digits: int = 3) -> str:
                    try:
                        xf = float(x)
                    except Exception:
                        return "1"
                    return f"{xf:.{int(digits)}f}".rstrip("0").rstrip(".")

                lines: List[str] = []
                title = (self.lbl_name.text() or "").strip() or "DPS"

                dps_total = float(dbg.get("DPS_total", 0.0) or 0.0)
                dps_hit = float(dbg.get("DPS_hit", 0.0) or 0.0)
                dots = list(dbg.get("DoTs", []) or [])
                dps_dot_sum = 0.0
                for dot in dots:
                    try:
                        dps_dot_sum += float(dot.get("DPS_dot", 0.0) or 0.0)
                    except Exception:
                        pass

                lines.append(f"<b>{title}</b>")
                lines.append(f"Итог: <b>{_fmt_num(dps_total)}</b>")
                lines.append(
                    f"Тычки: {_fmt_num(dps_hit)}"
                    + (f" | DoT: {_fmt_num(dps_dot_sum)}" if abs(dps_dot_sum) > 1e-12 else "")
                )

                lines.append("")
                lines.append("<b>База</b>")
                lines.append(
                    f"Атака: {_fmt_num(dbg.get('Attack', 0.0))}"
                    f" | Крит: {_fmt_pct_direct(dbg.get('CritChancePercent', 0.0))}"
                    f" | Сила крита: {_fmt_pct_direct(dbg.get('CritPowerPercent', 0.0))}"
                )
                lines.append(
                    f"Скорость атаки: {_fmt_num(dbg.get('AttackSpeedStat', 0.0))}"
                    f" | атак/сек: {_fmt_num(dbg.get('AttacksPerSecond', 0.0))}"
                )

                weapon_mode = str(dbg.get("WeaponMode") or "")
                if weapon_mode:
                    mode_name = {
                        "single_hit": "Обычное оружие",
                        "two_handed_double_hit": "Двуручка (2 удара)",
                        "dual_wield_1h": "Два одноручных",
                    }.get(weapon_mode, weapon_mode)

                    hit_parts = list(dbg.get("HitParts", []) or [])
                    if hit_parts:
                        parts_txt = " / ".join(_fmt_num(float(x) * 100.0, 2) + "%" for x in hit_parts)
                        lines.append(f"Режим: {mode_name} [{parts_txt}]")
                    else:
                        lines.append(f"Режим: {mode_name}")

                global_mul_raw = float(dbg.get("GlobalMultiplierRaw", 0.0) or 0.0)
                if global_mul_raw > 0.0:
                    lines.append(f"Общий множитель: {_fmt_mul(dbg.get('GlobalMultiplier', 1.0))}x")

                hit_muls = list(dbg.get("HitMultipliers", []) or [])
                hit_elems = list(dbg.get("HitElementIds", []) or [])
                if hit_muls:
                    hit_parts_txt: List[str] = []
                    for i, hm in enumerate(hit_muls):
                        elem_id = None
                        try:
                            if i < len(hit_elems):
                                elem_id = hit_elems[i]
                        except Exception:
                            elem_id = None

                        if elem_id in (None, 0, "0"):
                            hit_parts_txt.append(f"{_fmt_mul(hm)}x")
                        else:
                            hit_parts_txt.append(f"E{elem_id}: {_fmt_mul(hm)}x")

                    if hit_parts_txt:
                        lines.append("Множители ударов: " + ", ".join(hit_parts_txt))

                target_common_mul = float(dbg.get("TargetCommonMultiplier", 1.0) or 1.0)
                target_hit_mods = list(dbg.get("TargetHitDamageModifiers", []) or [])
                target_dot_mods = list(dbg.get("TargetDotDamageModifiers", []) or [])

                has_target_info = (
                        abs(target_common_mul - 1.0) > 1e-12
                        or any(abs(float(x) - 1.0) > 1e-12 for x in target_hit_mods if x is not None)
                        or any(abs(float(x) - 1.0) > 1e-12 for x in target_dot_mods if x is not None)
                )

                if has_target_info:
                    lines.append("")
                    lines.append("<b>Цель</b>")

                    race_mul = float(dbg.get("TargetRaceMultiplier", 1.0) or 1.0)
                    elem_mul = float(dbg.get("TargetWholeElementMultiplier", 1.0) or 1.0)

                    if abs(race_mul - 1.0) > 1e-12:
                        lines.append(f"Множитель по расе: {_fmt_mul(race_mul)}x")

                    if abs(elem_mul - 1.0) > 1e-12:
                        lines.append(f"Множитель по элементу цели: {_fmt_mul(elem_mul)}x")

                    if target_hit_mods:
                        hit_mod_txt = ", ".join(_fmt_mul(x) + "x" for x in target_hit_mods)
                        lines.append(f"Защита от ударов: {hit_mod_txt}")

                    if target_dot_mods:
                        dot_mod_txt = ", ".join(_fmt_mul(x) + "x" for x in target_dot_mods)
                        lines.append(f"Защита от DoT: {dot_mod_txt}")

                if dots:
                    lines.append("")
                    lines.append("<b>DoT</b>")

                    for dot in dots:
                        dot_name = str(dot.get("DotName") or f"Dot #{dot.get('DotId')}")
                        dot_dps = _fmt_num(dot.get("DPS_dot", 0.0))
                        dot_chance = _fmt_pct_direct(dot.get("ProcChanceSumPercent", 0.0))
                        dot_stacks = _fmt_num(dot.get("AvgStacks", 0.0), 3)
                        dot_mul = _fmt_mul(dot.get("DotMultiplier", 1.0))

                        row = f"{dot_name}: {dot_dps}"
                        extra: List[str] = []

                        if dot_chance != "0%":
                            extra.append(f"шанс {dot_chance}")
                        if dot_stacks not in ("0", "0.0"):
                            extra.append(f"стаки {dot_stacks}")
                        if dot_mul != "1":
                            extra.append(f"множ. {dot_mul}x")

                        if extra:
                            row += " (" + ", ".join(extra) + ")"

                        lines.append(row)

                while lines and lines[-1] == "":
                    lines.pop()

                return "<br/>".join(lines)

        if tpl is None:
            return None

        if self._last_numeric_value is None:
            rep = "—"
        else:
            vv = float(self._last_numeric_value)
            if fid is not None:
                try:
                    out_v = self._calc_formula_value(int(fid), vv, level=level)
                except Exception:
                    out_v = vv
            else:
                out_v = vv
            rep = self._format_tooltip_number(out_v, rd)

        desc = str(tpl).replace("{0}", rep)

        def _fmt_inline_number(x: float) -> str:
            try:
                xf = float(x)
            except Exception:
                return str(x)

            try:
                if rd is not None and int(rd) > 0:
                    return f"{xf:.{int(rd)}f}".rstrip("0").rstrip(".")
            except Exception:
                pass

            if abs(xf - round(xf)) < 1e-9:
                return str(int(round(xf)))
            return f"{xf:.4f}".rstrip("0").rstrip(".")

        def _resolve_weapon_attack_speed() -> float:
            try:
                math_obj = getattr(panel, "math", None)
                dbg_map = getattr(math_obj, "_formula15_debug_by_stat", None) if math_obj is not None else None
                dbg = dbg_map.get(75) if isinstance(dbg_map, dict) else None
                if isinstance(dbg, dict):
                    v = float(dbg.get("AttackSpeedWeaponBase", 0.0) or 0.0)
                    if abs(v) > 1e-12:
                        return v
            except Exception:
                pass

            rows = []
            try:
                rows = list(getattr(panel, "_last_equipment_rows", []) or [])
            except Exception:
                rows = []

            def _item_equip_id(it: dict) -> int:
                for k in ("Id", "Equipment_Id", "Equip_Id", "Item_Id"):
                    try:
                        v = int(it.get(k) or 0)
                        if v > 0:
                            return v
                    except Exception:
                        pass
                return 0

            def _item_type_id(it: dict) -> int:
                for k in ("Type_Id", "EquipmentType_Id", "TypeId"):
                    try:
                        v = int(it.get(k) or 0)
                        if v > 0:
                            return v
                    except Exception:
                        pass

                eid = _item_equip_id(it)
                if eid <= 0:
                    return 0

                try:
                    row = conn.execute(
                        'SELECT Type_Id FROM "Equipment" WHERE Id=? LIMIT 1',
                        (int(eid),),
                    ).fetchone()
                except Exception:
                    row = None

                if not row:
                    return 0

                try:
                    return int((row["Type_Id"] if hasattr(row, "keys") else row[0]) or 0)
                except Exception:
                    return 0

            def _item_attack_speed(it: dict) -> float:
                for k in ("AttackSpeed",):
                    try:
                        if k in it and it[k] not in (None, ""):
                            v = float(str(it[k]).replace(",", "."))
                            return v if abs(v) > 1e-12 else 1.0
                    except Exception:
                        pass

                eid = _item_equip_id(it)
                if eid <= 0:
                    return 1.0

                try:
                    row = conn.execute(
                        'SELECT AttackSpeed FROM "Equipment" WHERE Id=? LIMIT 1',
                        (int(eid),),
                    ).fetchone()
                except Exception:
                    row = None

                if not row:
                    return 1.0

                try:
                    raw = row["AttackSpeed"] if hasattr(row, "keys") else row[0]
                    v = float(str(raw).replace(",", "."))
                    return v if abs(v) > 1e-12 else 1.0
                except Exception:
                    return 1.0

            for it in rows:
                if not isinstance(it, dict):
                    continue
                try:
                    tid = _item_type_id(it)
                    if tid > 0 and _is_weapon_type_by_equipmenttype(conn, int(tid)):
                        return _item_attack_speed(it)
                except Exception:
                    pass

            return 1.0

        def _safe_eval_expr(expr: str) -> Optional[float]:
            import ast
            import operator as _op

            try:
                expr = str(expr)
            except Exception:
                return None

            expr = expr.strip()
            if not expr:
                return None

            expr = (
                expr
                .replace(",", ".")
                .replace("\xa0", " ")
                .replace("\u202f", " ")
                .replace("\t", " ")
                .replace("\r", " ")
                .replace("\n", " ")
                .replace("–", "-")
                .replace("—", "-")
                .replace("−", "-")
            )
            expr = re.sub(r"\s+", "", expr)

            if not expr:
                return None

            for ch in expr:
                if ch.isdigit() or ch in ".()+-*/":
                    continue
                return None

            try:
                node = ast.parse(expr, mode="eval")
            except Exception:
                return None

            bin_ops = {
                ast.Add: _op.add,
                ast.Sub: _op.sub,
                ast.Mult: _op.mul,
                ast.Div: _op.truediv,
            }
            un_ops = {
                ast.UAdd: _op.pos,
                ast.USub: _op.neg,
            }

            def _eval(n):
                if isinstance(n, ast.Expression):
                    return _eval(n.body)

                if isinstance(n, ast.Constant):
                    if isinstance(n.value, (int, float)):
                        return float(n.value)
                    return None

                if hasattr(ast, "Num") and isinstance(n, ast.Num):
                    return float(n.n)

                if isinstance(n, ast.BinOp) and type(n.op) in bin_ops:
                    a = _eval(n.left)
                    b = _eval(n.right)
                    if a is None or b is None:
                        return None
                    try:
                        return float(bin_ops[type(n.op)](a, b))
                    except Exception:
                        return None

                if isinstance(n, ast.UnaryOp) and type(n.op) in un_ops:
                    a = _eval(n.operand)
                    if a is None:
                        return None
                    try:
                        return float(un_ops[type(n.op)](a))
                    except Exception:
                        return None

                return None

            return _eval(node)

        if "\\n" in desc and "\n" not in desc:
            desc = desc.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")

        atk_sec = _resolve_weapon_attack_speed()
        _BR_RE = re.compile(r"\[([^\[\]]+)\]")

        def _repl(m):
            inner = m.group(1) or ""
            expr = str(inner)

            expr = re.sub(
                r"attack\|sec",
                str(float(atk_sec)),
                expr,
                flags=re.IGNORECASE,
            )

            val = _safe_eval_expr(expr)
            if val is None:
                return m.group(0)
            return _fmt_inline_number(val)

        for _ in range(5):
            new_desc = _BR_RE.sub(_repl, desc)
            if new_desc == desc:
                break
            desc = new_desc

        desc = desc.replace("\r\n", "\n").replace("\r", "\n")
        if "\n" in desc:
            desc = "<br/>".join(desc.split("\n"))

        return desc

    def _on_tooltip_timeout(self) -> None:
        if not self._cursor_inside_self():
            return

        txt = None
        try:
            txt = self._build_tooltip_text()
        except Exception:
            txt = None

        if not txt:
            return

        try:
            tip = getattr(self, "_custom_stat_tooltip", None)
            if tip is None:
                tip = _StatInfoTooltip()
                self._custom_stat_tooltip = tip

            title = ""
            try:
                title = str(getattr(self, "_base_name_text", "") or self.lbl_name.text() or "").strip()
            except Exception:
                title = ""

            if not title:
                title = "—"

            tip.set_content(title, txt, max_w=250)

            pos = self.mapToGlobal(QPoint(10, int(self.height()) + 8))
            tip.show_at(pos)

        except Exception:
            pass

class VisualStatWidget(QWidget):
    """
    Иконка 26x26 слева.
    Справа: сверху текст, снизу шкала из 10 делений.
    Ширина шкалы зависит от общей ширины виджета и
    автоматически делится на 10 сегментов.
    """

    ICON_SIZE = 26

    # --- координаты внутри виджета ---
    ICON_X = 4
    ICON_Y = 2

    TEXT_X = ICON_X + ICON_SIZE + 4   # старт текста по X
    TEXT_Y = 0                        # текст по Y
    TEXT_HEIGHT = 15

    BAR_X = TEXT_X                    # шкала по X
    BAR_Y = TEXT_Y + TEXT_HEIGHT + 4  # шкала по Y
    BAR_HEIGHT = 8

    RIGHT_PADDING = 4                 # отступ справа

    SEGMENT_COUNT = 10
    SEGMENT_SPACING = 1               # расстояние между сегментами

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)

        # --- иконка ---
        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(self.ICON_SIZE, self.ICON_SIZE)
        self.icon_label.setScaledContents(True)

        # === БЕЙДЖ (кратность) поверх иконки ===
        self.mult_label = QLabel("", self)  # child of icon -> всегда поверх.icon_label
        self.mult_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.mult_label.setAlignment(Qt.AlignCenter)

        fmul = self.mult_label.font()
        fmul.setPointSizeF(8)
        fmul.setBold(True)
        self.mult_label.setFont(fmul)

        self.mult_label.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #6eea78, stop:1 #2fa85a);
                color: #ffffff;
                border: 1px solid #5a452e;
                border-radius: 2px;
                padding: 0px 2px;
            }
        """)

        self.mult_label.hide()
        # === /БЕЙДЖ ===

        # --- текст ---
        self.text_label = QLabel(text, self)
        f = self.text_label.font()
        f.setPointSizeF(10)
        self.text_label.setFont(f)
        self.text_label.setStyleSheet("color: #3b290c;")
        self.text_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        # --- контейнер для шкалы (без layout-а) ---
        self.bar_container = QWidget(self)

        self._segments: List[QFrame] = []
        for _ in range(self.SEGMENT_COUNT):
            seg = QFrame(self.bar_container)
            seg.setStyleSheet(
                "background-color: rgba(0, 0, 0, 0);"
                "border-radius: 0px;"
                "border: 1px solid rgba(0, 0, 0, 60);"
            )
            self._segments.append(seg)

        # высота по умолчанию, чтобы всё влезло
        self.setMinimumHeight(
            max(self.ICON_Y + self.ICON_SIZE, self.BAR_Y + self.BAR_HEIGHT) + 2
        )

        self.set_filled_segments(0)
        self._update_geometry()

    # --- ручная раскладка по X/Y ---

    def _update_geometry(self) -> None:
        w = self.width() or 130

        # иконка
        self.icon_label.setGeometry(
            self.ICON_X, self.ICON_Y, self.ICON_SIZE, self.ICON_SIZE
        )

        # обновим позицию бейджа (после того как выставили icon_label)
        self._update_multiplier_geometry()

        # текст
        text_width = max(0, w - self.TEXT_X - self.RIGHT_PADDING)
        self.text_label.setGeometry(
            self.TEXT_X, self.TEXT_Y, text_width, self.TEXT_HEIGHT
        )

        # контейнер шкалы
        bar_width = max(0, w - self.BAR_X - self.RIGHT_PADDING)
        self.bar_container.setGeometry(
            self.BAR_X, self.BAR_Y, bar_width, self.BAR_HEIGHT
        )

        # сами сегменты внутри контейнера
        self._update_segments_geometry()

    def _update_multiplier_geometry(self) -> None:
        txt = (self.mult_label.text() or "").strip()
        if not txt:
            self.mult_label.hide()
            return

        badge_w, badge_h = 20, 14

        r = self.icon_label.geometry()  # <-- реальная позиция иконки внутри виджета
        x = r.x() + r.width() - badge_w
        y = r.y() + r.height() - badge_h

        self.mult_label.setGeometry(x, y, badge_w, badge_h)
        self.mult_label.raise_()  # <-- гарантируем что поверх
        self.mult_label.show()

    def set_multiplier(self, mult: int) -> None:
        try:
            mult = int(mult)
        except Exception:
            mult = 0

        if mult <= 0:
            self.mult_label.setText("")
            self.mult_label.hide()
            return

        self.mult_label.setText(str(mult))
        self._update_multiplier_geometry()

    def set_value_progress(self, value: float | int | None, step: int = 10) -> None:
        """
        value=значение стата.
        step=10 => каждые 10 очков дают +1 к 'кратности', а шкала показывает остаток 0..9.
        Пример: 20 => rem=0, mult=2.
        """
        if step <= 0:
            step = 10

        try:
            v = float(value) if value is not None else 0.0
        except Exception:
            v = 0.0

        iv = int(round(v))
        if iv < 0:
            iv = 0

        mult = iv // step
        rem = iv % step

        # rem у нас 0..9 (если step=10), как раз под 10 сегментов
        rem = max(0, min(self.SEGMENT_COUNT, rem))

        self.set_filled_segments(rem)
        self.set_multiplier(mult)

    def _update_segments_geometry(self) -> None:
        bw = self.bar_container.width()
        bh = self.BAR_HEIGHT

        if self.SEGMENT_COUNT <= 0 or bw <= 0:
            return

        total_spacing = self.SEGMENT_SPACING * (self.SEGMENT_COUNT - 1)
        usable_width = max(1, bw - total_spacing)

        # базовая ширина сегмента и "лишние" пиксели
        base_w = usable_width // self.SEGMENT_COUNT
        extra = usable_width % self.SEGMENT_COUNT

        x = 0
        for i, seg in enumerate(self._segments):
            # первым `extra` сегментам даём +1 пиксель
            seg_w = base_w + (1 if i < extra else 0)
            seg.setGeometry(x, 0, seg_w, bh)
            x += seg_w
            if i < self.SEGMENT_COUNT - 1:
                x += self.SEGMENT_SPACING

    def resizeEvent(self, event):
        self._update_geometry()
        super().resizeEvent(event)

    # --- API ---

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)

    def set_icon(self, pixmap: QPixmap) -> None:
        self.icon_label.setPixmap(pixmap)

    def set_filled_segments(self, count: int) -> None:
        count = max(0, min(self.SEGMENT_COUNT, count))
        for i, seg in enumerate(self._segments):
            if i < count:
                seg.setStyleSheet(
                    "background-color: #3cb64b;"
                    "border-radius: 0px;"
                    "border: 1px solid #2c7f35;"
                )
            else:
                seg.setStyleSheet(
                    "background-color: #d7b57a;"  # светло-бежевый фон
                    "border-radius: 0px;"
                    "border: 1px solid #b48a4a;"  # тонкая коричневая рамка
                )

class CharacteristicsPanel(QFrame):
    """
    Правая панель статов.
    Всё внутри _rows_frame раскладывается вручную по Y-координатам,
    никаких layout-ов там нет. Меняешь числа в константах — двигается
    только то, что привязано к этим числам.
    """

    ROOT_MARGINS = (16, 0, 16, 10)   # (left, top, right, bottom)
    ROOT_SPACING = 0

    # --- базовые размеры ---
    ROW_WIDTH = 269      # ширина строк статов
    ROW_HEIGHT = 18      # высота одной строки
    TITLE_HEIGHT = 18    # высота заголовков
    VISUAL_BLOCK_HEIGHT = 69

    # --- вкладки (hitbox-ы вместо кнопок; можно вручную подстроить) ---
    # Прямоугольник-хедер вкладок
    TAB_BG_SIZE = (270, 36)  # (w, h)
    TAB_BG_POS = (0, 0)
    TAB_BG_IMG = r"resources/main_menu/button_char.png"  # показываем только когда активна "Дополнительно"

    # Кликабельные зоны внутри TAB_BG_SIZE (x, y, w, h)
    TAB_MAIN_RECT = (0, 0, ROW_WIDTH // 2, TAB_BG_SIZE[1])
    TAB_EXTRA_RECT = (ROW_WIDTH // 2, 0, ROW_WIDTH - (ROW_WIDTH // 2), TAB_BG_SIZE[1])

    # Временная подсветка hitbox-ов (2 разных цвета)
    TAB_MAIN_COLOR = "rgba(0, 200, 0, 70)"
    TAB_EXTRA_COLOR = "rgba(0, 120, 255, 70)"

    # --- "Дополнительно": прокручиваемая область под TAB_BG ---
    # Размер видимой области (viewport) и путь к длинной картинке.
    EXTRA_VIEW_SIZE = (267, 385)  # (w, h) — область сразу под TAB_BG
    EXTRA_IMG_PATH = r"resources/main_menu/dop_char_bottom.png"  # 269x877 (длинная)
    EXTRA_SCROLL_WHEEL_STEP = 30  # шаг прокрутки колёсиком (px)

    # --- "Доп.ые": отступ между названием и значением (колонка значения внутри StatRowWidget) ---
    # Чем БОЛЬШЕ число — тем правее начинается значение и тем больше “пустого места” между именем и значением.
    EXTRA_ROW_VALUE_X = 203  # поставь 185/190/200 как тебе надо


    # --- кастомные иконки скролла ---
    SB_UP_DEFAULT = r"resources/helper_buttons/scroll_button_up.png"
    SB_UP_ACTIVE  = r"resources/helper_buttons/scroll_button_up_active.png"
    SB_UP_END     = r"resources/helper_buttons/scroll_button_up_end.png"

    SB_DOWN_DEFAULT = r"resources/helper_buttons/scroll_button_down.png"
    SB_DOWN_ACTIVE  = r"resources/helper_buttons/scroll_button_down_active.png"
    SB_DOWN_END     = r"resources/helper_buttons/scroll_button_down_end.png"

    SB_SCROLLER_DEFAULT = r"resources/helper_buttons/scroller.png"
    SB_SCROLLER_ACTIVE  = r"resources/helper_buttons/scroller_active.png"

    # --- "Доп.ые": размещение статов поверх длинной картинки ---
    # --- фиксированные заголовки поверх EXTRA_IMG_PATH (координаты в системе картинки) ---
    EXTRA_FIXED_TITLES = [
        ("general", "Общее"),
        ("survival", "Выживание"),
        ("pvp", "PvP (Игрок против игрока)"),
        ("elem_dmg", "Элементальный урон"),
        ("elem_res", "Устойчивость к элементам"),
        ("race_res", "Устойчивость к урону от рас"),
    ]


    # --- "Доп.ые": Y первой строки статов для каждой секции (координаты НА КАРТИНКЕ) ---
    # ЭТО и есть “двигать каждую группу отдельно”.
    EXTRA_SECTION_STATS_TOP_Y = {
        "general": 20,
        "survival": 144,
        "pvp": 208,
        "elem_dmg": 292,
        "elem_res": 436,
        "race_res": 580,
    }

    # x, y — координаты на САМОЙ длинной картинке (EXTRA_IMG_PATH)
    # ПОДГОНИ ПОД СВОЙ МАКЕТ dop_char_bottom2.png
    EXTRA_FIXED_TITLE_POS = {
        "general":  (12, -2),
        "survival": (12, 122),
        "pvp": (12, 186),
        "elem_dmg": (12, 270),
        "elem_res": (12, 415),
        "race_res": (12, 558),
    }

    EXTRA_FIXED_TITLE_FONT_PT = 12
    EXTRA_FIXED_TITLE_HEIGHT = 22
    EXTRA_FIXED_TITLE_COLOR = "#3b290c"

    # --- "Доп.ые": состав секций (ID статов) ---
    # Правь списки тут — и это автоматически повлияет и на группировку, и на отображение.
    EXTRA_SECTION_STAT_IDS = {
        "general": [17, 18, 19, 20, 21],
        "survival": [22, 23, 24],  # реально показываем один из 23/24 по классу
        "elem_dmg": [25, 26, 27, 28, 29, 30],
        "elem_res": [31, 32, 33, 34, 35, 36],
        "pvp": [37, 48, 59],  # <-- ДОБАВЬ сюда те 2 недостающих ID
        "race_res": [67, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58],
    }


    # (опционально) показывать строку с id-шниками под заголовком на картинке
    EXTRA_FIXED_SHOW_IDS = False
    EXTRA_FIXED_IDS_FONT_PT = 9
    EXTRA_FIXED_IDS_HEIGHT = 14
    EXTRA_FIXED_IDS_COLOR = "#6a4b17"
    EXTRA_FIXED_IDS_GAP_Y = 0
    # Это *только* координаты; правь руками под макет dop_char_bottom.png.
    EXTRA_STATS_LEFT_X = 8          # X начала текста
    EXTRA_STATS_TOP_Y = 16           # Y первой строки на картинке
    EXTRA_STATS_ROW_STEP = 20        # шаг между строками (px)
    EXTRA_STATS_PRELOAD = 120        # предзагрузка сверху/снизу при скролле (px)
    EXTRA_STATS_RIGHT_PAD = 4        # отступ справа до скроллбара (px)
    # --- Абсолютные Y-координаты для вкладки "Осн.ые" (пиксели от верха _rows_frame) ---
    HEALTH_ROWS_Y = (7, 25)                 # Здоровье, Энергия
    PARAM_TITLE_Y = 44                      # "Параметры"
    PARAM_ROWS_Y = (71, 91, 111, 131)       # Сила, Ловкость, Выносливость, Удача

    VISUAL_BLOCK_Y = 156                    # прямоугольник
    VISUAL_AREAS_GEOMETRY = [
        (11, 2, 125, 28),  # левый верх
        (136, 2, 125, 28),  # правый верх
        (11, 35, 125, 28),  # левый низ
        (136, 35, 125, 28),  # правый низ
    ]

    CHARS_TITLE_Y = 231                     # "Характеристики"
    CHAR_ROWS_Y = (251, 269, 287, 305, 323, 341, 359)  # боевые статы

    paramMinusClicked = Signal(int)
    paramPlusClicked = Signal(int)
    paramPlusAllClicked = Signal(int)
    mainParamChanged = Signal(int)  # new_main_param_id (4/5/6)
    paramResetClicked = Signal()

    def __init__(self, parent: QWidget | None = None, conn=None, param_state=None):
        super().__init__(parent)
        self.setMinimumHeight(410)
        # фиксируем ширину панели под ROW_WIDTH и отступы
        total_width = self.ROW_WIDTH + self.ROOT_MARGINS[0] + self.ROOT_MARGINS[2]
        self.setFixedWidth(total_width)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self.setObjectName("char_stats_panel")
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.setStyleSheet("""
            QFrame{
                background-color: rgba(255, 0, 0, 0);
                border-radius: 0px;
            }
        """)

        if conn is None and parent is not None:
            data = getattr(parent, "data", None)
            conn = getattr(data, "conn", None)

        self.conn = conn
        self.math = CharacteristicsMath(conn) if conn is not None else None
        self.stat_defs: List[StatDef] = self.math.stat_defs if self.math else []
        self.unspent_param_points: int = 0
        self._last_level_seen: int | None = None

        self._current_group: str = "main"

        self.rows_by_id: Dict[int, StatRowWidget] = {}
        self.rows_by_code: Dict[str, StatRowWidget] = {}
        self._last_values_by_id: Dict[int, float] = {}

        self.visual_block: Optional[QFrame] = None
        self.visual_widgets: List[VisualStatWidget] = []

        # --- корневой лейаут ---
        root = QVBoxLayout(self)
        root.setContentsMargins(*self.ROOT_MARGINS)
        root.setSpacing(self.ROOT_SPACING)

        # ===== 1. Кнопки вкладок =====
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)

        self.param_state: ParamAllocationState | None = None
        self._current_main_param_id: int | None = None

        def _make_group_button(text: str, base_color: str, checked_color: str) -> QPushButton:
            btn = QPushButton(text, self)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(24)
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    padding: 2px 10px;
                    border-radius: 8px;
                    border: 1px solid #b48a4a;
                    background: {base_color};
                    color: #3b290c;
                }}
                QPushButton:checked {{
                    background: {checked_color};
                    color: #ffffff;
                }}
                """
            )
            return btn

        self.btn_group_main = _make_group_button("Осн.ые", "#e5d4aa", "#2fa85a")
        self.btn_group_extra = _make_group_button("Доп.ые", "#e5d4aa", "#e0b02a")
        self.btn_group_other = _make_group_button("Прочие", "#e5d4aa", "#a067cc")

        self.btn_group_main.clicked.connect(lambda: self._on_group_button_clicked("main"))
        self.btn_group_extra.clicked.connect(lambda: self._on_group_button_clicked("extra"))
        self.btn_group_other.clicked.connect(lambda: self._on_group_button_clicked("other"))

        # Реальные кнопки прячем (оставляем только ради сигналов/checked-state)
        for _b in (self.btn_group_main, self.btn_group_extra, self.btn_group_other):
            _b.hide()

        # Прямоугольник вкладок: фон + кликабельные hitbox-ы
        self.tabs_rect = QFrame(self)
        self.tabs_rect.setObjectName("CharTabsRect")
        tw, th = self.TAB_BG_SIZE
        self.tabs_rect.setFixedSize(int(tw), int(th))
        self.tabs_rect.setStyleSheet("QFrame#CharTabsRect { background: transparent; border: none; }")
        root.addWidget(self.tabs_rect, 0, Qt.AlignLeft)

        # фон (появляется только на вкладке "Дополнительно")
        self._tabs_bg = QLabel(self.tabs_rect)
        self._tabs_bg.setGeometry(0, 0, int(tw), int(th))
        self._tabs_bg.setScaledContents(True)
        self._tabs_bg.hide()

        # hitbox: "Основные"
        self.tab_hit_main = QFrame(self.tabs_rect)
        x, y, w, h = self.TAB_MAIN_RECT
        self.tab_hit_main.setGeometry(int(x), int(y), int(w), int(h))
        self.tab_hit_main.setCursor(Qt.PointingHandCursor)
        self.tab_hit_main.setStyleSheet("background: transparent; border: none;")
        self.tab_hit_main._pressed_inside = False  # type: ignore[attr-defined]

        def _tab_main_mouse_press(ev):
            if ev.button() == Qt.LeftButton:
                self.tab_hit_main._pressed_inside = True  # type: ignore[attr-defined]
                ev.accept()
                return
            QWidget.mousePressEvent(self.tab_hit_main, ev)

        def _tab_main_mouse_release(ev):
            if ev.button() == Qt.LeftButton:
                armed = bool(getattr(self.tab_hit_main, "_pressed_inside", False))
                self.tab_hit_main._pressed_inside = False  # type: ignore[attr-defined]

                try:
                    inside = self.tab_hit_main.rect().contains(ev.position().toPoint())
                except Exception:
                    try:
                        inside = self.tab_hit_main.rect().contains(ev.pos())
                    except Exception:
                        inside = False

                if armed and inside:
                    self.btn_group_main.click()

                ev.accept()
                return
            QWidget.mouseReleaseEvent(self.tab_hit_main, ev)

        self.tab_hit_main.mousePressEvent = _tab_main_mouse_press  # type: ignore[assignment]
        self.tab_hit_main.mouseReleaseEvent = _tab_main_mouse_release  # type: ignore[assignment]

        # hitbox: "Дополнительно"
        self.tab_hit_extra = QFrame(self.tabs_rect)
        x, y, w, h = self.TAB_EXTRA_RECT
        self.tab_hit_extra.setGeometry(int(x), int(y), int(w), int(h))
        self.tab_hit_extra.setCursor(Qt.PointingHandCursor)
        self.tab_hit_extra.setStyleSheet("background: transparent; border: none;")
        self.tab_hit_extra._pressed_inside = False  # type: ignore[attr-defined]

        def _tab_extra_mouse_press(ev):
            if ev.button() == Qt.LeftButton:
                self.tab_hit_extra._pressed_inside = True  # type: ignore[attr-defined]
                ev.accept()
                return
            QWidget.mousePressEvent(self.tab_hit_extra, ev)

        def _tab_extra_mouse_release(ev):
            if ev.button() == Qt.LeftButton:
                armed = bool(getattr(self.tab_hit_extra, "_pressed_inside", False))
                self.tab_hit_extra._pressed_inside = False  # type: ignore[attr-defined]

                try:
                    inside = self.tab_hit_extra.rect().contains(ev.position().toPoint())
                except Exception:
                    try:
                        inside = self.tab_hit_extra.rect().contains(ev.pos())
                    except Exception:
                        inside = False

                if armed and inside:
                    self.btn_group_extra.click()

                ev.accept()
                return
            QWidget.mouseReleaseEvent(self.tab_hit_extra, ev)

        self.tab_hit_extra.mousePressEvent = _tab_extra_mouse_press  # type: ignore[assignment]
        self.tab_hit_extra.mouseReleaseEvent = _tab_extra_mouse_release  # type: ignore[assignment]

        # "Прочие" пока уводим в сторону (кнопка остаётся, но не показывается)
        self.btn_group_other.move(self.ROW_WIDTH + 20, 0)

        # ===== 1.5) "Дополнительно": прокручиваемая область под TAB_BG =====
        self.dop_scroll_wrap = QFrame(self)
        self.dop_scroll_wrap.setObjectName("CharExtraScrollWrap")
        vw, vh = self.EXTRA_VIEW_SIZE
        self.dop_scroll_wrap.setFixedSize(int(vw), int(vh))
        self.dop_scroll_wrap.setStyleSheet("QFrame#CharExtraScrollWrap { background: transparent; border: none; }")
        root.addWidget(self.dop_scroll_wrap, 0, Qt.AlignLeft)

        # viewport (клипует содержимое)
        self.dop_viewport = QFrame(self.dop_scroll_wrap)
        self.dop_viewport.setObjectName("CharExtraViewport")
        self.dop_viewport.setGeometry(0, 0, int(vw), int(vh))
        self.dop_viewport.setStyleSheet("QFrame#CharExtraViewport { background: transparent; border: none; }")

        # длинная картинка (двигаем по Y)
        self._dop_img_pm = QPixmap(_res_path(self.EXTRA_IMG_PATH))
        self.dop_img_label = QLabel(self.dop_viewport)
        self.dop_img_label.setObjectName("CharExtraImage")
        self.dop_img_label.setScaledContents(False)
        if not self._dop_img_pm.isNull():
            self.dop_img_label.setPixmap(self._dop_img_pm)
            self.dop_img_label.setGeometry(0, 0, self._dop_img_pm.width(), self._dop_img_pm.height())
        else:
            self.dop_img_label.setGeometry(0, 0, int(vw), int(vh))

        self._dop_scroll_y = 0
        self._dop_max_scroll = max(0, (0 if self._dop_img_pm.isNull() else self._dop_img_pm.height()) - int(vh))

        # ---- кастомный скроллбар (картинки) ----
        self._dop_sb_up_hover = False
        self._dop_sb_down_hover = False
        self._dop_sb_handle_hover = False
        self._dop_sb_up_pressed = False
        self._dop_sb_down_pressed = False
        self._dop_sb_up_armed = False
        self._dop_sb_down_armed = False
        self._dop_sb_dragging = False
        self._dop_sb_drag_off_y = 0

        self._dop_sb_pm_up_def = QPixmap(_res_path(self.SB_UP_DEFAULT))
        self._dop_sb_pm_up_act = QPixmap(_res_path(self.SB_UP_ACTIVE))
        self._dop_sb_pm_up_end = QPixmap(_res_path(self.SB_UP_END))

        self._dop_sb_pm_down_def = QPixmap(_res_path(self.SB_DOWN_DEFAULT))
        self._dop_sb_pm_down_act = QPixmap(_res_path(self.SB_DOWN_ACTIVE))
        self._dop_sb_pm_down_end = QPixmap(_res_path(self.SB_DOWN_END))

        self._dop_sb_pm_handle_def = QPixmap(_res_path(self.SB_SCROLLER_DEFAULT))
        self._dop_sb_pm_handle_act = QPixmap(_res_path(self.SB_SCROLLER_ACTIVE))

        _w_candidates = []
        for _pm in (
                self._dop_sb_pm_up_def, self._dop_sb_pm_up_act, self._dop_sb_pm_up_end,
                self._dop_sb_pm_down_def, self._dop_sb_pm_down_act, self._dop_sb_pm_down_end,
                self._dop_sb_pm_handle_def, self._dop_sb_pm_handle_act,
        ):
            if not _pm.isNull():
                _w_candidates.append(int(_pm.width()))
        self._dop_sb_w = max(_w_candidates) if _w_candidates else 16

        self._dop_sb_up_h = int(self._dop_sb_pm_up_def.height()) if not self._dop_sb_pm_up_def.isNull() else 16
        self._dop_sb_down_h = int(self._dop_sb_pm_down_def.height()) if not self._dop_sb_pm_down_def.isNull() else 16
        self._dop_sb_handle_h = int(
            self._dop_sb_pm_handle_def.height()) if not self._dop_sb_pm_handle_def.isNull() else 24
        self._dop_sb_handle_w = int(
            self._dop_sb_pm_handle_def.width()) if not self._dop_sb_pm_handle_def.isNull() else int(self._dop_sb_w)

        # контейнер скроллбара (поверх viewport)
        self.dop_sb = QFrame(self.dop_viewport)
        self.dop_sb.setObjectName("CharExtraScrollBar")
        self.dop_sb.setStyleSheet("QFrame#CharExtraScrollBar { background: transparent; border: none; }")
        self.dop_sb.setGeometry(int(vw) - int(self._dop_sb_w), 0, int(self._dop_sb_w), int(vh))

        # дорожка под ползунком
        self.dop_sb_track = QFrame(self.dop_sb)
        self.dop_sb_track.setObjectName("CharExtraScrollTrack")
        self.dop_sb_track.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        track_top = int(self._dop_sb_up_h)
        track_h = int(vh) - int(self._dop_sb_up_h) - int(self._dop_sb_down_h)
        if track_h < 1:
            track_h = 1

        track_pad_x = 1
        self.dop_sb_track.setGeometry(
            int(track_pad_x),
            int(track_top),
            int(self._dop_sb_w) - int(track_pad_x) * 2,
            int(track_h),
        )

        self.dop_sb_track.setStyleSheet("""
        QFrame#CharExtraScrollTrack {
            background: rgba(0, 0, 0, 35);
            border: 1px solid rgba(0, 0, 0, 55);
        }
        """)
        self.dop_sb_track.lower()

        def _cx(pm: QPixmap) -> int:
            if pm.isNull():
                return 0
            return max(0, (int(self._dop_sb_w) - int(pm.width())) // 2)

        # стрелка вверх
        self.dop_sb_up = QLabel(self.dop_sb)
        self.dop_sb_up.setObjectName("CharExtraScrollUp")
        self.dop_sb_up.setCursor(Qt.PointingHandCursor)
        self.dop_sb_up.setGeometry(
            _cx(self._dop_sb_pm_up_def),
            0,
            int(self._dop_sb_pm_up_def.width()) if not self._dop_sb_pm_up_def.isNull() else int(self._dop_sb_w),
            int(self._dop_sb_up_h),
        )
        self.dop_sb_up.setScaledContents(True)

        # стрелка вниз
        self.dop_sb_down = QLabel(self.dop_sb)
        self.dop_sb_down.setObjectName("CharExtraScrollDown")
        self.dop_sb_down.setCursor(Qt.PointingHandCursor)
        self.dop_sb_down.setGeometry(
            _cx(self._dop_sb_pm_down_def),
            int(vh) - int(self._dop_sb_down_h),
            int(self._dop_sb_pm_down_def.width()) if not self._dop_sb_pm_down_def.isNull() else int(self._dop_sb_w),
            int(self._dop_sb_down_h),
        )
        self.dop_sb_down.setScaledContents(True)

        # ползунок
        self.dop_sb_handle = QLabel(self.dop_sb)
        self.dop_sb_handle.setObjectName("CharExtraScrollerHandle")
        self.dop_sb_handle.setCursor(Qt.OpenHandCursor)
        self.dop_sb_handle.setGeometry(
            _cx(self._dop_sb_pm_handle_def),
            int(self._dop_sb_up_h),
            int(self._dop_sb_handle_w),
            int(self._dop_sb_handle_h),
        )
        self.dop_sb_handle.setScaledContents(True)

        def _label_contains_pos(lbl: QLabel, ev) -> bool:
            try:
                return lbl.rect().contains(ev.position().toPoint())
            except Exception:
                try:
                    return lbl.rect().contains(ev.pos())
                except Exception:
                    return False

        def _sb_up_enter(_e):
            self._dop_sb_up_hover = True
            self._extra_scroll_update_bar()

        def _sb_up_leave(_e):
            self._dop_sb_up_hover = False
            self._dop_sb_up_pressed = False
            self._dop_sb_up_armed = False
            self._extra_scroll_update_bar()

        def _sb_up_press(ev):
            if ev.button() != Qt.LeftButton:
                return
            self._dop_sb_up_pressed = True
            self._dop_sb_up_armed = True
            self._extra_scroll_update_bar()
            ev.accept()

        def _sb_up_release(ev):
            was_pressed = bool(self._dop_sb_up_pressed)
            armed = bool(self._dop_sb_up_armed)
            self._dop_sb_up_pressed = False
            self._dop_sb_up_armed = False

            if was_pressed and armed and _label_contains_pos(self.dop_sb_up, ev):
                if self._dop_scroll_y > 0:
                    self._extra_scroll_scroll_by(-int(self.EXTRA_SCROLL_WHEEL_STEP))

            self._extra_scroll_update_bar()
            ev.accept()

        self.dop_sb_up.enterEvent = _sb_up_enter  # type: ignore[assignment]
        self.dop_sb_up.leaveEvent = _sb_up_leave  # type: ignore[assignment]
        self.dop_sb_up.mousePressEvent = _sb_up_press  # type: ignore[assignment]
        self.dop_sb_up.mouseReleaseEvent = _sb_up_release  # type: ignore[assignment]

        def _sb_down_enter(_e):
            self._dop_sb_down_hover = True
            self._extra_scroll_update_bar()

        def _sb_down_leave(_e):
            self._dop_sb_down_hover = False
            self._dop_sb_down_pressed = False
            self._dop_sb_down_armed = False
            self._extra_scroll_update_bar()

        def _sb_down_press(ev):
            if ev.button() != Qt.LeftButton:
                return
            self._dop_sb_down_pressed = True
            self._dop_sb_down_armed = True
            self._extra_scroll_update_bar()
            ev.accept()

        def _sb_down_release(ev):
            was_pressed = bool(self._dop_sb_down_pressed)
            armed = bool(self._dop_sb_down_armed)
            self._dop_sb_down_pressed = False
            self._dop_sb_down_armed = False

            if was_pressed and armed and _label_contains_pos(self.dop_sb_down, ev):
                if self._dop_scroll_y < self._dop_max_scroll:
                    self._extra_scroll_scroll_by(int(self.EXTRA_SCROLL_WHEEL_STEP))

            self._extra_scroll_update_bar()
            ev.accept()

        self.dop_sb_down.enterEvent = _sb_down_enter  # type: ignore[assignment]
        self.dop_sb_down.leaveEvent = _sb_down_leave  # type: ignore[assignment]
        self.dop_sb_down.mousePressEvent = _sb_down_press  # type: ignore[assignment]
        self.dop_sb_down.mouseReleaseEvent = _sb_down_release  # type: ignore[assignment]

        def _handle_enter(_e):
            self._dop_sb_handle_hover = True
            if not self._dop_sb_dragging:
                self.dop_sb_handle.setCursor(Qt.OpenHandCursor)
            self._extra_scroll_update_bar()

        def _handle_leave(_e):
            self._dop_sb_handle_hover = False
            if not self._dop_sb_dragging:
                self.dop_sb_handle.setCursor(Qt.OpenHandCursor)
            self._extra_scroll_update_bar()

        def _handle_press(ev):
            if ev.button() != Qt.LeftButton:
                return
            self._dop_sb_dragging = True
            self.dop_sb_handle.setCursor(Qt.ClosedHandCursor)
            self._dop_sb_drag_off_y = int(getattr(ev, "position", lambda: QPoint(0, 0))().y()) if hasattr(ev,
                                                                                                          "position") else int(
                ev.pos().y())
            self._dop_sb_drag_off_y = max(0, min(self._dop_sb_handle_h - 1, self._dop_sb_drag_off_y))
            self._extra_scroll_update_bar()

        def _handle_move(ev):
            if not self._dop_sb_dragging:
                return
            my = int(getattr(ev, "position", lambda: QPoint(0, 0))().y()) if hasattr(ev, "position") else int(
                ev.pos().y())
            bar_my = int(self.dop_sb_handle.y()) + my
            track_top2 = int(self._dop_sb_up_h)
            track_bottom2 = int(vh) - int(self._dop_sb_down_h)
            track_h2 = max(1, track_bottom2 - track_top2)
            handle_h2 = int(self._dop_sb_handle_h)

            new_handle_top = bar_my - int(self._dop_sb_drag_off_y)
            new_handle_top = max(track_top2, min(track_top2 + track_h2 - handle_h2, new_handle_top))

            if self._dop_max_scroll <= 0:
                self._extra_scroll_set_offset(0)
                return

            denom = float(max(1, track_h2 - handle_h2))
            ratio = float(new_handle_top - track_top2) / denom
            self._extra_scroll_set_offset(int(round(ratio * float(self._dop_max_scroll))))

        def _handle_release(_e):
            self._dop_sb_dragging = False
            self.dop_sb_handle.setCursor(Qt.OpenHandCursor)
            self._extra_scroll_update_bar()

        self.dop_sb_handle.enterEvent = _handle_enter  # type: ignore[assignment]
        self.dop_sb_handle.leaveEvent = _handle_leave  # type: ignore[assignment]
        self.dop_sb_handle.mousePressEvent = _handle_press  # type: ignore[assignment]
        self.dop_sb_handle.mouseMoveEvent = _handle_move  # type: ignore[assignment]
        self.dop_sb_handle.mouseReleaseEvent = _handle_release  # type: ignore[assignment]

        # прокрутка колёсиком
        def _extra_wheel(ev):
            if self._dop_max_scroll <= 0:
                ev.ignore()
                return
            dy = ev.angleDelta().y()
            if dy == 0:
                ev.ignore()
                return
            if dy < 0:
                self._extra_scroll_scroll_by(int(self.EXTRA_SCROLL_WHEEL_STEP))
            else:
                self._extra_scroll_scroll_by(-int(self.EXTRA_SCROLL_WHEEL_STEP))
            ev.accept()

        self.dop_viewport.wheelEvent = _extra_wheel  # type: ignore[assignment]
        self.dop_img_label.wheelEvent = _extra_wheel  # type: ignore[assignment]

        # начальная позиция + иконки
        self._extra_scroll_refresh_max()
        self._extra_scroll_set_offset(0)

        # по умолчанию область скрыта
        self.dop_scroll_wrap.hide()

        # ===== 2. Контейнер под строки =====
        self._rows_frame = QFrame(self)
        self._rows_frame.setObjectName("stats_body")
        self._rows_frame.setMinimumWidth(self.ROW_WIDTH)
        self._rows_frame.setMaximumWidth(self.ROW_WIDTH)
        root.addWidget(self._rows_frame, 1)

        root.addItem(QSpacerItem(1, 1, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self._rebuild_rows_for_group(self._current_group)
        self.btn_group_main.setChecked(True)

        if param_state is not None:
            self.set_param_state(param_state)

    #def set_menu_bonus_enabled(self, flags: Optional[Mapping[str, bool]] = None) -> None:
    #    norm = self._normalize_menu_bonus_enabled(flags)
    #    self.menu_bonus_enabled = dict(norm)
#
    #    try:
    #        if self.math is not None:
    #            self.math.menu_bonus_enabled = dict(norm)
    #    except Exception:
    #        pass

    # --- группировка для "Доп.ые" / "Прочие" --- #
    def set_param_state(self, state: ParamAllocationState | None) -> None:
        self.param_state = state

    def _group_for_stat(self, sd: StatDef) -> str:
        try:
            sid = int(getattr(sd, "id", 0) or 0)
        except Exception:
            sid = 0

        if sid <= 16:
            return "main"

        extra_ids = set()
        ids_map = getattr(self, "EXTRA_SECTION_STAT_IDS", None)
        if isinstance(ids_map, dict):
            for lst in ids_map.values():
                if isinstance(lst, (list, tuple, set)):
                    for x in lst:
                        try:
                            extra_ids.add(int(x))
                        except Exception:
                            pass

        return "extra" if sid in extra_ids else "other"

    def set_group(self, group: str) -> None:
        if group not in ("main", "extra", "other"):
            return
        if self._current_group == group:
            return

        self._current_group = group

        self.btn_group_main.setChecked(group == "main")
        self.btn_group_extra.setChecked(group == "extra")
        self.btn_group_other.setChecked(group == "other")

        # строки (вкладка "Осн.ые" и "Прочие")
        self._rebuild_rows_for_group(group)

        # фон вкладок: показываем картинку только когда активна "Дополнительно"
        bg = getattr(self, "_tabs_bg", None)
        if isinstance(bg, QLabel):
            if group == "extra":
                pm = QPixmap(_res_path(self.TAB_BG_IMG))
                if not pm.isNull():
                    bg.setPixmap(pm)
                    bg.show()
                else:
                    bg.clear()
                    bg.hide()
            else:
                bg.clear()
                bg.hide()

        # область с прокруткой (только для "Доп.ые")
        extra_wrap = getattr(self, "dop_scroll_wrap", None)
        rows_frame = getattr(self, "_rows_frame", None)

        if group == "extra":
            if isinstance(extra_wrap, QWidget):
                extra_wrap.show()
            if isinstance(rows_frame, QWidget):
                rows_frame.hide()

            # на случай если картинка/размеры поменялись
            if hasattr(self, "_extra_scroll_refresh_max"):
                self._extra_scroll_refresh_max()

            # КЛЮЧЕВОЕ: сразу синхронизируем позицию картинки + оверлеи (статы/заголовки),
            # чтобы они появились без первого "скролла колесом"
            cur_y = int(getattr(self, "_dop_scroll_y", 0) or 0)
            if hasattr(self, "_extra_scroll_set_offset"):
                self._extra_scroll_set_offset(cur_y)
            elif hasattr(self, "_extra_overlay_sync_visible"):
                self._extra_overlay_sync_visible()

            if hasattr(self, "_extra_scroll_update_bar"):
                self._extra_scroll_update_bar()
        else:
            if isinstance(extra_wrap, QWidget):
                extra_wrap.hide()
            if isinstance(rows_frame, QWidget):
                rows_frame.show()

    # ------------------------------------------------------------------
    # "Дополнительно": прокрутка длинной картинки (dop_char_bottom.png)
    # ------------------------------------------------------------------

    def _extra_scroll_refresh_max(self) -> None:
        try:
            _, vh = self.EXTRA_VIEW_SIZE
        except Exception:
            vh = 0

        pm = getattr(self, "_dop_img_pm", QPixmap())
        img_h = 0 if pm is None or pm.isNull() else int(pm.height())
        self._dop_max_scroll = max(0, int(img_h) - int(vh))

        try:
            self._dop_scroll_y = int(self._dop_scroll_y)
        except Exception:
            self._dop_scroll_y = 0
        self._dop_scroll_y = max(0, min(int(self._dop_scroll_y), int(self._dop_max_scroll)))

    def _extra_scroll_scroll_by(self, dy: int) -> None:
        try:
            delta = int(dy)
        except Exception:
            delta = 0
        self._extra_scroll_set_offset(int(self._dop_scroll_y) + int(delta))

    def _extra_scroll_set_offset(self, y: int) -> None:
        try:
            ny = int(y)
        except Exception:
            ny = 0

        ny = max(0, min(int(ny), int(getattr(self, "_dop_max_scroll", 0) or 0)))
        self._dop_scroll_y = int(ny)

        lbl = getattr(self, "dop_img_label", None)
        if isinstance(lbl, QLabel):
            lbl.move(0, -int(self._dop_scroll_y))

        # важно: при скролле подгружаем/прячем оверлейные строки
        if hasattr(self, "_extra_overlay_sync_visible"):
            self._extra_overlay_sync_visible()

        self._extra_scroll_update_bar()

    def _extra_scroll_update_bar(self) -> None:
        # Обновляет стрелки/ползунок + позицию ползунка под текущий scroll_y.
        try:
            vw, vh = self.EXTRA_VIEW_SIZE
        except Exception:
            vw, vh = (269, 392)

        self._extra_scroll_refresh_max()

        sb = getattr(self, "dop_sb", None)
        up = getattr(self, "dop_sb_up", None)
        down = getattr(self, "dop_sb_down", None)
        handle = getattr(self, "dop_sb_handle", None)

        max_scroll = int(getattr(self, "_dop_max_scroll", 0) or 0)
        cur = int(getattr(self, "_dop_scroll_y", 0) or 0)
        at_top = cur <= 0
        at_bottom = cur >= max_scroll if max_scroll > 0 else True

        # 1) иконки стрелок
        if isinstance(up, QLabel):
            if at_top:
                pm = getattr(self, "_dop_sb_pm_up_end", QPixmap())
            else:
                if getattr(self, "_dop_sb_up_hover", False) or getattr(self, "_dop_sb_up_pressed", False):
                    pm = getattr(self, "_dop_sb_pm_up_act", QPixmap())
                else:
                    pm = getattr(self, "_dop_sb_pm_up_def", QPixmap())
            if pm is not None and not pm.isNull():
                up.setPixmap(pm)

        if isinstance(down, QLabel):
            if at_bottom:
                pm = getattr(self, "_dop_sb_pm_down_end", QPixmap())
            else:
                if getattr(self, "_dop_sb_down_hover", False) or getattr(self, "_dop_sb_down_pressed", False):
                    pm = getattr(self, "_dop_sb_pm_down_act", QPixmap())
                else:
                    pm = getattr(self, "_dop_sb_pm_down_def", QPixmap())
            if pm is not None and not pm.isNull():
                down.setPixmap(pm)

        # 2) ползунок
        if isinstance(handle, QLabel):
            if max_scroll <= 0:
                handle.hide()
                return

            handle.show()

            track_top = int(getattr(self, "_dop_sb_up_h", 16) or 16)
            track_bottom = int(vh) - int(getattr(self, "_dop_sb_down_h", 16) or 16)
            track_h = max(1, int(track_bottom) - int(track_top))

            handle_h = int(getattr(self, "_dop_sb_handle_h", 24) or 24)
            handle_w = int(getattr(self, "_dop_sb_handle_w", int(getattr(self, "_dop_sb_w", 16) or 16)) or 16)
            bar_w = int(getattr(self, "_dop_sb_w", 16) or 16)

            denom = float(max(1, track_h - handle_h))
            ratio = float(cur) / float(max_scroll) if max_scroll > 0 else 0.0
            new_y = int(track_top + round(ratio * denom))
            new_y = max(track_top, min(track_top + track_h - handle_h, new_y))

            new_x = max(0, (bar_w - handle_w) // 2)
            handle.setGeometry(int(new_x), int(new_y), int(handle_w), int(handle_h))

            if getattr(self, "_dop_sb_handle_hover", False) or getattr(self, "_dop_sb_dragging", False):
                pm = getattr(self, "_dop_sb_pm_handle_act", QPixmap())
            else:
                pm = getattr(self, "_dop_sb_pm_handle_def", QPixmap())
            if pm is not None and not pm.isNull():
                handle.setPixmap(pm)

    def _extra_overlay_sync_visible(self) -> None:
        """Подгружает/прячет строки статов для вкладки 'Доп.ые' / 'Прочее'
        + держит фиксированные заголовки на координатах картинки EXTRA_IMG_PATH.
        """
        if getattr(self, "_current_group", "") != "extra":
            return

        layout = getattr(self, "_extra_overlay_layout", None)
        if not isinstance(layout, list):
            layout = []

        parent = getattr(self, "dop_img_label", None)
        if not isinstance(parent, QWidget):
            return

        # чтобы hover/tooltip ловились на оверлей-строках
        try:
            parent.setMouseTracking(True)
        except Exception:
            pass

        is_other_panel = self.__class__.__name__ == "OtherCharacteristicsPanel"

        try:
            vis_top = int(getattr(self, "_dop_scroll_y", 0))
        except Exception:
            vis_top = 0

        vw, vh = getattr(self, "EXTRA_VIEW_SIZE", (0, 0))
        try:
            vh = int(vh)
        except Exception:
            vh = 0
        vis_bot = vis_top + vh

        widgets = getattr(self, "_extra_overlay_widgets", None)
        if not isinstance(widgets, dict):
            widgets = {}
            setattr(self, "_extra_overlay_widgets", widgets)

        try:
            extra_value_x = int(getattr(self, "EXTRA_ROW_VALUE_X", 0) or 0)
        except Exception:
            extra_value_x = None

        # базовые гео-параметры
        try:
            x = int(getattr(self, "STATS_ROW_X", 10) or 0)
        except Exception:
            x = 0

        # место под кастомный скроллбар
        try:
            sb_w = int(getattr(self, "SCROLLBAR_W", 18) or 0)
        except Exception:
            sb_w = 0
        try:
            right_pad = int(getattr(self, "SCROLLBAR_RIGHT_PAD", 0) or 0)
        except Exception:
            right_pad = 0

        try:
            row_h = int(getattr(self, "ROW_HEIGHT", 18) or 18)
        except Exception:
            row_h = 18

        try:
            w = int(getattr(self, "ROW_WIDTH", 269) or 269) - x - sb_w - right_pad
        except Exception:
            w = 269 - x - sb_w - right_pad
        if w < 60:
            w = 60

        layout_ids = set()

        # Берём уже посчитанные отображаемые значения.
        # Это важно: если тут брать _last_values_by_id, то можно перезаписать строку raw-значением
        # после формул из update_by_id().
        display_vals = getattr(self, "_last_display_values_by_id", None)
        if not isinstance(display_vals, dict):
            display_vals = getattr(self, "_last_values_by_id", None)
        if not isinstance(display_vals, dict):
            display_vals = {}

        for sd, y_on_img in layout:
            try:
                sid_int = int(sd.id)
                layout_ids.add(sid_int)
            except Exception:
                sid_int = None

            y0 = int(y_on_img)
            y1 = y0 + row_h
            need = (y1 >= vis_top) and (y0 <= vis_bot)

            row = widgets.get(sd.id)

            if need:
                if row is None or row.parent() is None:
                    row = StatRowWidget(
                        sd.name,
                        is_percent=getattr(sd, "is_percent", False),
                        parent=parent,
                        stat_id=int(getattr(sd, "id", 0) or 0),
                    )

                    # ВАЖНО: должно быть False, иначе hover не работает
                    row.setAttribute(Qt.WA_TransparentForMouseEvents, False)
                    row.setAttribute(Qt.WA_TranslucentBackground, True)
                    row.setStyleSheet("background: transparent;")
                    try:
                        row.setMouseTracking(True)
                    except Exception:
                        pass

                    widgets[sd.id] = row

                # гарантируем регистрацию
                if sid_int is not None:
                    try:
                        self.rows_by_id[sid_int] = row
                    except Exception:
                        pass

                if getattr(sd, "code", None):
                    try:
                        self.rows_by_code[sd.code] = row
                    except Exception:
                        pass

                # применяем другой VALUE_X только для extra
                if extra_value_x is not None:
                    try:
                        row.VALUE_X = int(extra_value_x)
                    except Exception:
                        pass

                # Имя можно прокручивать как раньше.
                try:
                    row.MARQUEE_ENABLED = True
                except Exception:
                    pass

                # В меню "Прочее" значение тоже становится бегущей строкой,
                # если не помещается в доступную ширину.
                try:
                    row.VALUE_MARQUEE_ENABLED = bool(is_other_panel)
                except Exception:
                    pass

                # Для "Прочее" НЕ возвращаем +20 к ширине строки:
                # эти +20 как раз позволяют значению залезать под зону скролла.
                row_w = int(w) if is_other_panel else int(w) + 20

                row.setGeometry(int(x), int(y0), int(row_w), int(row_h))

                try:
                    row._update_geometry()
                except Exception:
                    pass

                # Меняем только значение уже существующей строки.
                if sid_int is not None:
                    try:
                        row.set_value(display_vals.get(sid_int))
                    except Exception:
                        pass

                row.show()
            else:
                if row is not None:
                    row.hide()

        # скрываем “старые” виджеты, которых уже нет в текущем layout
        for sid, row in list(widgets.items()):
            try:
                sid_int = int(sid)
            except Exception:
                sid_int = None

            if sid_int is None or sid_int not in layout_ids:
                try:
                    row.hide()
                except Exception:
                    pass
                try:
                    if sid_int is not None and self.rows_by_id.get(sid_int) is row:
                        del self.rows_by_id[sid_int]
                except Exception:
                    pass

        # --- фиксированные заголовки (координаты на картинке) ---
        titles = getattr(self, "EXTRA_FIXED_TITLES", None)
        if isinstance(titles, (list, tuple)) and titles:
            labels = getattr(self, "_extra_fixed_title_labels", None)
            if not isinstance(labels, dict):
                labels = {}
                setattr(self, "_extra_fixed_title_labels", labels)

            ids_labels = getattr(self, "_extra_fixed_ids_labels", None)
            if not isinstance(ids_labels, dict):
                ids_labels = {}
                setattr(self, "_extra_fixed_ids_labels", ids_labels)

            pos_map = getattr(self, "EXTRA_FIXED_TITLE_POS", None)
            if not isinstance(pos_map, dict):
                pos_map = {}

            try:
                font_pt = float(getattr(self, "EXTRA_FIXED_TITLE_FONT_PT", 11) or 11)
            except Exception:
                font_pt = 11.0

            title_h = int(getattr(self, "EXTRA_FIXED_TITLE_HEIGHT", getattr(self, "TITLE_HEIGHT", 18)) or 18)
            color = getattr(self, "EXTRA_FIXED_TITLE_COLOR", "#3b290c") or "#3b290c"

            used_keys = set()

            for key, title in titles:
                used_keys.add(key)
                x0, y0 = pos_map.get(key, (10, 0))
                try:
                    x0 = int(x0)
                except Exception:
                    x0 = 10
                try:
                    y0 = int(y0)
                except Exception:
                    y0 = 0

                lbl = labels.get(key)
                if lbl is None or lbl.parent() is None:
                    lbl = QLabel(str(title), parent)
                    lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                    lbl.setStyleSheet(f"color: {color}; background: transparent;")
                    f = lbl.font()
                    f.setPointSizeF(font_pt)
                    f.setBold(True)
                    lbl.setFont(f)
                    labels[key] = lbl

                lbl.setGeometry(int(x0), int(y0), int(vw) - 20, int(title_h))
                lbl.show()

                if isinstance(ids_labels, dict):
                    il = ids_labels.get(key)
                    if il is not None:
                        try:
                            il.show()
                        except Exception:
                            pass

            for k, lbl in list(labels.items()):
                if k not in used_keys:
                    try:
                        lbl.hide()
                    except Exception:
                        pass
            for k, lbl in list(ids_labels.items()):
                if k not in used_keys:
                    try:
                        lbl.hide()
                    except Exception:
                        pass

    def _on_group_button_clicked(self, group_key: str) -> None:
        self.set_group(group_key)

    # --- очистка контейнера --- #
    def _clear_rows(self) -> None:
        dbg = bool(getattr(self, "DEBUG_EXTRA_HEADERS", False))

        rf = getattr(self, "_rows_frame", None)
        if rf is None:
            return

        # сбросить реестры (не переопределяем, чтобы не ломать внешние ссылки)
        try:
            self.rows_by_id.clear()
        except Exception:
            self.rows_by_id = {}

        try:
            self.rows_by_code.clear()
        except Exception:
            self.rows_by_code = {}

        # сбросить вспомогательные поля
        try:
            self.visual_widgets = []
        except Exception:
            pass
        try:
            self.visual_block = None
        except Exception:
            pass

        try:
            setattr(self, "_extra_section_labels", [])
        except Exception:
            pass
        try:
            setattr(self, "_extra_overlay_layout", [])
        except Exception:
            pass

        # удалить все прямые дочерние виджеты у rows_frame
        try:
            direct_children = rf.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
        except Exception:
            direct_children = [ch for ch in rf.children() if isinstance(ch, QWidget)]

        #if dbg:
        #    try:
        #        lbl_all = rf.findChildren(QLabel)
        #        lbl_direct = rf.findChildren(QLabel, options=Qt.FindDirectChildrenOnly)
        #        rows_direct = rf.findChildren(StatRowWidget, options=Qt.FindDirectChildrenOnly)
        #        print(
        #            f"[STATPANEL] _clear_rows pre: StatRowWidget={len(rows_direct)} QLabel(all)={len(lbl_all)} QLabel(direct)={len(lbl_direct)}")
        #    except Exception:
        #        pass

        for w in list(direct_children):
            if w is None:
                continue
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

        # важно: сбросить minHeight, иначе QScrollArea может сохранять “старый” диапазон скролла
        try:
            rf.setMinimumHeight(0)
        except Exception:
            pass

        #if dbg:
        #    try:
        #        lbl_all = rf.findChildren(QLabel)
        #        rows_direct = rf.findChildren(StatRowWidget, options=Qt.FindDirectChildrenOnly)
        #        print(
        #            f"[STATPANEL] _clear_rows post: children={len(rf.children())} QLabel(all)={len(lbl_all)} StatRowWidget={len(rows_direct)}")
        #    except Exception:
        #        pass

    def reset_params(self) -> None:
        # 1) сброс распределения
        if self.param_state is not None:
            self.param_state.reset_all()

        # 2) наружу сигнал, чтобы main_window пересчитал статы
        self.paramResetClicked.emit()

    # --- построение строк по правилам --- #
    def _load_image_pixmap(self, image_id: int) -> Optional[QPixmap]:
        """
        Загружает QPixmap по image_id из таблицы Image.
        Подгони SQL под свою схему (Path / Data и т.п.).
        """
        if self.conn is None:
            return None

        try:
            # ВАРИАНТ 1: если в Image хранится BLOB с картинкой
            row = self.conn.execute(
                "SELECT Data FROM Image WHERE Id = ?",
                (image_id,)
            ).fetchone()
            if not row:
                return None

            blob = row[0] if not hasattr(row, "keys") else row["Data"]
            if not blob:
                return None

            pm = QPixmap()
            if pm.loadFromData(blob):
                return pm
            return None

        except Exception:
            return None

    def _class_uses_mana(self, class_name: str | None = None) -> bool:
        """
        True, если для этого класса вместо Энергии нужно показывать Манy.
        """
        n = (class_name or getattr(self, "_current_class_name", "") or "").strip().lower()
        return any(k in n for k in ("маг", "волшебник", "чернокнижник"))

    def _main_stat_id_for_class_name(self, class_name: str | None) -> int:
        """
        Возвращает Id основного стата по имени класса.

        Маппинг:
          "мечник", "крестоносец", "темный рыцарь", "вор", "разбойник", "ассасин" -> Сила (4)
          "стрелок", "снайпер", "охотник"                                       -> Точность (5)
          "маг", "волшебник", "чернокнижник"                                    -> Интеллект (6)
        По умолчанию — Сила (4).
        """
        n = (class_name or "").strip().lower()

        if any(k in n for k in ("мечник", "крестоносец", "темный рыцарь", "вор", "разбойник", "ассасин")):
            return 4  # Сила

        if any(k in n for k in ("стрелок", "снайпер", "охотник")):
            return 5  # Точность

        if any(k in n for k in ("маг", "волшебник", "чернокнижник")):
            return 6  # Интеллект

        # дефолт — Сила
        return 4

    def set_class_name(self, class_name: str | None) -> None:
        """
        Сохраняет текущее имя класса и перестраивает строки
        ТОЛЬКО если реально поменялся состав строк для текущей вкладки.
        """
        new_name = (class_name or "").strip().lower()
        old_name = (getattr(self, "_current_class_name", "") or "").strip().lower()

        try:
            uses_mana = bool(self._class_uses_mana(new_name))
        except Exception:
            uses_mana = False

        new_parent_class_id = 7 if uses_mana else 1
        old_parent_class_id = getattr(self, "_current_parent_class_id", None)

        self._current_class_name = new_name
        self._current_parent_class_id = new_parent_class_id

        cur_group = str(getattr(self, "_current_group", "") or "").strip().lower()

        # Для "Осн.ые" состав строк зависит от:
        # - main_param_id (4/5/6)
        # - resource_id (2/3)
        if cur_group == "main":
            try:
                main_param_id = int(self._main_stat_id_for_class_name(new_name))
            except Exception:
                main_param_id = 4

            resource_id = 3 if uses_mana else 2
            new_layout_key = (int(main_param_id), int(resource_id))
            old_layout_key = getattr(self, "_main_layout_key", None)

            self._main_layout_key = new_layout_key

            # если состав строк реально изменился — rebuild
            if old_layout_key is not None and tuple(old_layout_key) != tuple(new_layout_key):
                self._rebuild_rows_for_group("main")
            return

        # Для "Доп.ые" состав строк зависит только от survival-строки 23/24
        if cur_group == "extra":
            if new_parent_class_id in (1, 4, 10):
                survival_resource_id = 23
            elif new_parent_class_id == 7:
                survival_resource_id = 24
            else:
                survival_resource_id = 0

            new_layout_key = (int(survival_resource_id),)
            old_layout_key = getattr(self, "_extra_layout_key", None)

            self._extra_layout_key = new_layout_key

            if old_layout_key is not None and tuple(old_layout_key) != tuple(new_layout_key):
                self._rebuild_rows_for_group("extra")
            return

        # Для остальных вкладок имя класса сохраняем, но rebuild не нужен
        return

    def _rebuild_rows_for_group(self, group: str) -> None:
        self.DEBUG_EXTRA_HEADERS = True
        dbg = bool(getattr(self, "DEBUG_EXTRA_HEADERS", False))

        # трекаем смену вкладки (первый rebuild тоже считаем переключением, чтобы сбросить скролл)
        prev_group = getattr(self, "_last_rebuild_group", None)
        group_switched = (prev_group != group)
        setattr(self, "_last_rebuild_group", group)

        # чистим строки и старые секционные лейблы (они часто не удаляются _clear_rows)
        self._clear_rows()
        try:
            for ch in self._rows_frame.findChildren(QLabel):
                n = ch.objectName() or ""
                if (
                        n.startswith("extra_section_title__")
                        or n.startswith("extra_section_ids__")
                        or n.startswith("main_section_label__")
                ):
                    ch.deleteLater()
        except Exception:
            pass

        y_shift = int(getattr(self, "CONTENT_Y_SHIFT", -4) or 0)
        self._extra_y_shift = int(y_shift)

        stat_by_id: Dict[int, StatDef] = {}
        for sd in self.stat_defs:
            try:
                stat_by_id[int(sd.id)] = sd
            except Exception:
                pass

        def _force_sizes(content_h: int) -> None:
            try:
                content_h = int(max(0, content_h))
            except Exception:
                content_h = 0

            try:
                self._rows_frame.setMinimumHeight(content_h)
            except Exception:
                pass

            try:
                w = int(self._rows_frame.width())
                if w <= 0:
                    w = int(getattr(self, "ROW_WIDTH", 1) or 1)
                self._rows_frame.resize(max(1, w), max(1, content_h))
            except Exception:
                pass

            try:
                self._rows_frame.updateGeometry()
                self._rows_frame.update()
            except Exception:
                pass

        def _call_sync_visible() -> None:
            for name in (
                    "_extra_overlay_sync_visible",
                    "_overlay_sync_visible",
                    "_sync_visible",
                    "_sync_rows_visibility",
                    "_update_visible_rows",
                    "_update_visible",
            ):
                try:
                    fn = getattr(self, name, None)
                    if callable(fn):
                        fn()
                        return
                except Exception:
                    pass

        def _get_scroll_ctx():
            for start in (self._rows_frame, self):
                p = start
                while p is not None:
                    if hasattr(p, "verticalScrollBar"):
                        try:
                            vb = p.verticalScrollBar()
                        except Exception:
                            vb = None
                        if vb is not None:
                            try:
                                hb = p.horizontalScrollBar() if hasattr(p, "horizontalScrollBar") else None
                            except Exception:
                                hb = None
                            return p, vb, hb
                    try:
                        p = p.parentWidget()
                    except Exception:
                        break
            return None, None, None

        def _apply_scroll(force_top: bool, content_h: int) -> None:
            sa, vb, hb = _get_scroll_ctx()
            if vb is None:
                return

            vh = 0
            try:
                if sa is not None and hasattr(sa, "viewport") and sa.viewport() is not None:
                    vh = int(sa.viewport().height())
            except Exception:
                vh = 0
            if vh <= 0:
                try:
                    pw = self._rows_frame.parentWidget()
                    vh = int(pw.height()) if pw is not None else int(self.height())
                except Exception:
                    vh = 0

            try:
                ch = int(max(0, content_h))
            except Exception:
                ch = 0

            maxv = max(0, ch - max(0, vh))

            try:
                mn = int(vb.minimum())
            except Exception:
                mn = 0

            try:
                vb.setRange(mn, mn + int(maxv))
            except Exception:
                try:
                    vb.setRange(0, int(maxv))
                    mn = 0
                except Exception:
                    pass

            try:
                if hasattr(vb, "setPageStep"):
                    vb.setPageStep(max(1, int(vh)))
            except Exception:
                pass
            try:
                if hasattr(vb, "setSingleStep"):
                    vb.setSingleStep(20)
            except Exception:
                pass

            try:
                cur = int(vb.value())
            except Exception:
                cur = mn
            try:
                mx = int(vb.maximum())
            except Exception:
                mx = mn + int(maxv)

            target = mn if force_top else max(mn, min(cur, mx))
            try:
                if int(vb.value()) != int(target):
                    vb.setValue(int(target))
                elif force_top and mx > mn:
                    vb.setValue(min(mn + 1, mx))
                    vb.setValue(mn)
            except Exception:
                pass

            if hb is not None and force_top:
                try:
                    hb.setValue(int(hb.minimum()))
                except Exception:
                    pass

            _call_sync_visible()

            try:
                if sa is not None and hasattr(sa, "viewport") and sa.viewport() is not None:
                    sa.viewport().update()
            except Exception:
                pass

        def _schedule_after_rebuild(tag: str, force_top: bool, content_h: int) -> None:
            max_tries = 4

            def _try(attempt: int) -> None:
                sa, vb, hb = _get_scroll_ctx()
                if vb is None and attempt < max_tries:
                    try:
                        QTimer.singleShot(40 if attempt < 2 else 120, lambda: _try(attempt + 1))
                        return
                    except Exception:
                        pass

                _apply_scroll(force_top=force_top, content_h=content_h)

                try:
                    self._rows_frame.repaint()
                except Exception:
                    pass

            try:
                QTimer.singleShot(0, lambda: _try(1))
            except Exception:
                _try(1)

        # ======================
        # Вкладка "Доп.ые"
        # ======================
        if group == "extra":
            # parent_class_id (нужно для survival)
            parent_class_id = None
            for a in (
                    "_current_parent_class_id",
                    "current_parent_class_id",
                    "parent_class_id",
                    "_parent_class_id",
                    "_current_class_id",
                    "current_class_id",
            ):
                v = getattr(self, a, None)
                if v is None:
                    continue
                try:
                    parent_class_id = int(getattr(v, "id", v))
                    break
                except Exception:
                    continue

            # секции из единого источника
            ids_map = getattr(self, "EXTRA_SECTION_STAT_IDS", None)
            if not isinstance(ids_map, dict):
                ids_map = {}

            general_ids = list(ids_map.get("general", [17, 18, 19, 20, 21]) or [])
            elem_dmg_ids = list(ids_map.get("elem_dmg", [25, 26, 27, 28, 29, 30]) or [])
            elem_res_ids = list(ids_map.get("elem_res", [31, 32, 33, 34, 35, 36]) or [])
            pvp_ids = list(ids_map.get("pvp", [37, 48, 59]) or [])
            race_res_ids = list(ids_map.get("race_res", [49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 67]) or [])

            survival_ids = [22]
            if parent_class_id in (1, 4, 10):
                survival_ids.append(23)
            elif parent_class_id == 7:
                survival_ids.append(24)

            section_defs: List[tuple[str, str, List[int]]] = [
                ("general", "Общее", [int(x) for x in general_ids if str(x).isdigit() or isinstance(x, int)]),
                ("survival", "Выживание", [int(x) for x in survival_ids]),
                ("elem_dmg", "Элементальный урон",
                 [int(x) for x in elem_dmg_ids if str(x).isdigit() or isinstance(x, int)]),
                ("elem_res", "Устойчивость к элементам",
                 [int(x) for x in elem_res_ids if str(x).isdigit() or isinstance(x, int)]),
                ("pvp", "PvP (Игрок против игрока)",
                 [int(x) for x in pvp_ids if str(x).isdigit() or isinstance(x, int)]),
                ("race_res", "Устойчивость к урону от рас",
                 [int(x) for x in race_res_ids if str(x).isdigit() or isinstance(x, int)]),
            ]

            top_map = getattr(self, "EXTRA_SECTION_STATS_TOP_Y", None)
            if not isinstance(top_map, dict):
                top_map = {}

            step_map = getattr(self, "EXTRA_SECTION_ROW_STEP", None)
            if not isinstance(step_map, dict):
                step_map = {}

            default_step = int(getattr(self, "EXTRA_STATS_ROW_STEP", 22) or 22)
            row_h = int(getattr(self, "ROW_HEIGHT", 18) or 18)

            # собираем layout строго по секциям + возможность двигать каждую секцию отдельно
            layout: List[tuple[StatDef, int]] = []
            present_ids_map: Dict[str, List[int]] = {}
            used_ids: set[int] = set()

            title_pos = getattr(self, "EXTRA_FIXED_TITLE_POS", None)
            if not isinstance(title_pos, dict):
                title_pos = {}

            title_h = int(getattr(self, "EXTRA_FIXED_TITLE_HEIGHT", getattr(self, "TITLE_HEIGHT", 18)) or 18)

            for sec_key, sec_title, ids in section_defs:
                want_ids: List[int] = []
                for x in ids:
                    try:
                        want_ids.append(int(x))
                    except Exception:
                        pass

                start_y = top_map.get(sec_key, None)
                if start_y is None:
                    # если не задано — берём от заголовка секции
                    try:
                        start_y = int(title_pos.get(sec_key, (0, 0))[1]) + int(title_h) + 2
                    except Exception:
                        start_y = int(title_h) + 2

                try:
                    start_y = int(start_y)
                except Exception:
                    start_y = 0

                sec_step = step_map.get(sec_key, default_step)
                try:
                    sec_step = int(sec_step)
                except Exception:
                    sec_step = int(default_step)

                present: List[int] = []
                idx = 0
                for sid in want_ids:
                    sd = stat_by_id.get(int(sid))
                    if not sd:
                        continue
                    y = int(start_y + idx * sec_step)
                    layout.append((sd, y))
                    present.append(int(sid))
                    used_ids.add(int(sid))
                    idx += 1

                present_ids_map[sec_key] = present

                #if dbg:
                #    missed = [sid for sid in want_ids if sid not in present]
                #    if missed:
                #        print(f"[STATPANEL] EXTRA: section '{sec_key}' missed ids (нет в stat_defs): {missed}")

            setattr(self, "_extra_section_present_ids", present_ids_map)
            setattr(self, "_extra_overlay_layout", layout)

            #if dbg:
            #    print("[STATPANEL] EXTRA: sections present_ids:",
            #          {k: v for k, v in present_ids_map.items()})
            #    # подсказка: кандидаты “пвп”-статов по имени/коду
            #    pvp_candidates = []
            #    for sd in self.stat_defs:
            #        try:
            #            sid = int(sd.id)
            #        except Exception:
            #            continue
            #        nm = (getattr(sd, "name", "") or "").lower()
            #        cd = (getattr(sd, "code", "") or "").lower()
            #        if "pvp" in nm or "pvp" in cd or "игрок" in nm:
            #            pvp_candidates.append((sid, getattr(sd, "name", ""), getattr(sd, "code", "")))
            #    if pvp_candidates:
            #        pvp_candidates.sort(key=lambda t: t[0])
            #        print("[STATPANEL] EXTRA: pvp candidates (id, name, code):")
            #        for t in pvp_candidates:
            #            print("   ", t)

            # обновим оверлей сразу (чтобы появилось без первого скролла)
            try:
                if hasattr(self, "_extra_overlay_sync_visible"):
                    self._extra_overlay_sync_visible()
            except Exception:
                pass

            # значения (если уже есть)
            if self._last_values_by_id:
                self.update_by_id(self._last_values_by_id)

            # rows_frame в extra не используется, но пусть будет валидный размер
            if layout:
                bottom = max(int(y) for _, y in layout) + row_h + 8
            else:
                bottom = 0
            _force_sizes(bottom)

            return

        # ======================
        # Вкладка "Осн.ые"
        # ======================
        if group == "main":
            main_param_id = self._main_stat_id_for_class_name(getattr(self, "_current_class_name", None))
            uses_mana = self._class_uses_mana(getattr(self, "_current_class_name", None))
            resource_id = 3 if uses_mana else 2
            health_ids = (1, resource_id)

            if self._current_main_param_id is None:
                self._current_main_param_id = int(main_param_id)
            elif int(main_param_id) != int(self._current_main_param_id):
                self._current_main_param_id = int(main_param_id)
                if self.param_state is not None:
                    for sid in (4, 5, 6):
                        if sid != self._current_main_param_id:
                            self.param_state.refund_all_for_stat(sid)
                self.mainParamChanged.emit(self._current_main_param_id)

            row_x = int(getattr(self, "STATS_ROW_X", 10) or 0)

            for sid, y in zip(health_ids, self.HEALTH_ROWS_Y):
                sd = stat_by_id.get(int(sid))
                if not sd:
                    continue
                row = StatRowWidget(sd.name, is_percent=sd.is_percent, parent=self._rows_frame, stat_id=int(sd.id))
                row.setGeometry(int(row_x), int(y + y_shift), self.ROW_WIDTH, self.ROW_HEIGHT)
                row.show()
                self.rows_by_id[sd.id] = row
                if sd.code:
                    self.rows_by_code[sd.code] = row

            main_title_x = int(getattr(self, "MAIN_SECTION_X", 13) or 0)
            main_title_font_pt = getattr(self, "MAIN_SECTION_TITLE_FONT_PT", 11)
            try:
                main_title_font_pt = float(main_title_font_pt)
            except Exception:
                main_title_font_pt = 11.0
            main_title_h = int(getattr(self, "MAIN_SECTION_TITLE_HEIGHT", self.TITLE_HEIGHT) or self.TITLE_HEIGHT)
            main_title_color = getattr(self, "MAIN_SECTION_TITLE_COLOR", "#3b290c") or "#3b290c"

            lbl_params = QLabel("Параметры", self._rows_frame)
            lbl_params.setObjectName("main_section_label__params")
            lbl_params.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            f = lbl_params.font()
            f.setPointSizeF(float(main_title_font_pt))
            f.setBold(True)
            lbl_params.setFont(f)
            lbl_params.setStyleSheet(f"color: {main_title_color};")
            lbl_params.setGeometry(int(main_title_x), int(self.PARAM_TITLE_Y + y_shift), self.ROW_WIDTH,
                                   int(main_title_h))
            lbl_params.show()

            param_ids = (main_param_id, 7, 8, 9)
            for sid, y in zip(param_ids, self.PARAM_ROWS_Y):
                sd = stat_by_id.get(int(sid))
                if not sd:
                    continue
                row = StatRowWidget(sd.name, is_percent=sd.is_percent, parent=self._rows_frame, stat_id=int(sd.id),
                                    adjustable=True)
                row.setGeometry(int(row_x), int(y + y_shift), self.ROW_WIDTH, 20)
                row.show()
                row.minusClicked.connect(self.paramMinusClicked.emit)
                row.plusClicked.connect(self.paramPlusClicked.emit)
                row.plusAllClicked.connect(self.paramPlusAllClicked.emit)
                self.rows_by_id[sd.id] = row
                if sd.code:
                    self.rows_by_code[sd.code] = row

            vb_y = int(self.VISUAL_BLOCK_Y + y_shift)
            vb_h = self.VISUAL_BLOCK_HEIGHT
            vb_w = self.ROW_WIDTH

            self.visual_block = QFrame(self._rows_frame)
            self.visual_block.setGeometry(0, vb_y, vb_w, vb_h)
            self.visual_block.setStyleSheet(
                "QFrame {"
                "background-color: rgba(0, 0, 0, 0);"
                "border-radius: 6px;"
                "}"
            )
            self.visual_block.show()

            self.visual_widgets = []
            for x, y, w, h in self.VISUAL_AREAS_GEOMETRY:
                vw = VisualStatWidget(parent=self.visual_block)
                vw.setGeometry(x, y, w, h)
                vw.show()
                self.visual_widgets.append(vw)

            visual_stat_ids = (main_param_id, 7, 8, 9)
            for vw, sid in zip(self.visual_widgets, visual_stat_ids):
                sd = stat_by_id.get(int(sid))
                if not sd:
                    continue
                vw._stat_id = int(sid)
                text = (sd.progress_name or "").strip() or sd.name
                vw.set_text(text)
                if sd.image_id is not None:
                    pm = self._load_image_pixmap(sd.image_id)
                    if pm is not None and not pm.isNull():
                        vw.set_icon(pm)
                vw.set_value_progress(0)

            lbl_stats = QLabel("Характеристики", self._rows_frame)
            lbl_stats.setObjectName("main_section_label__chars")
            lbl_stats.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            f2 = lbl_stats.font()
            f2.setPointSizeF(float(main_title_font_pt))
            f2.setBold(True)
            lbl_stats.setFont(f2)
            lbl_stats.setStyleSheet(f"color: {main_title_color};")
            lbl_stats.setGeometry(int(main_title_x), int(self.CHARS_TITLE_Y + y_shift), self.ROW_WIDTH,
                                  int(main_title_h))
            lbl_stats.show()

            char_ids = list(range(10, 17))
            for sid, y in zip(char_ids, self.CHAR_ROWS_Y):
                sd = stat_by_id.get(int(sid))
                if not sd:
                    continue
                row = StatRowWidget(sd.name, is_percent=sd.is_percent, parent=self._rows_frame, stat_id=int(sd.id))
                row.setGeometry(int(row_x), int(y + y_shift), self.ROW_WIDTH, self.ROW_HEIGHT)
                row.show()
                self.rows_by_id[sd.id] = row
                if sd.code:
                    self.rows_by_code[sd.code] = row

            bottom_candidates = []
            try:
                bottom_candidates.append(int(self.CHAR_ROWS_Y[-1] + y_shift + self.ROW_HEIGHT + 8))
            except Exception:
                pass
            try:
                bottom_candidates.append(int(self.VISUAL_BLOCK_Y + y_shift + self.VISUAL_BLOCK_HEIGHT + 8))
            except Exception:
                pass
            bottom = max(bottom_candidates) if bottom_candidates else 0

            _force_sizes(bottom)
            _schedule_after_rebuild("MAIN", force_top=bool(group_switched), content_h=bottom)
            setattr(self, "_extra_section_labels", [])

        else:
            y = int(0 + y_shift)
            row_x = int(getattr(self, "STATS_ROW_X", 10) or 0)

            for sd in self.stat_defs:
                if self._group_for_stat(sd) != group:
                    continue
                row = StatRowWidget(sd.name, is_percent=sd.is_percent, parent=self._rows_frame, stat_id=int(sd.id))
                row.setGeometry(int(row_x), int(y), self.ROW_WIDTH, self.ROW_HEIGHT)
                row.show()
                self.rows_by_id[sd.id] = row
                if sd.code:
                    self.rows_by_code[sd.code] = row
                y += self.ROW_HEIGHT + 2

            content_h = int(y + 8)
            _force_sizes(content_h)
            _schedule_after_rebuild(str(group), force_top=bool(group_switched), content_h=content_h)
            setattr(self, "_extra_section_labels", [])

        if self._last_values_by_id:
            self.update_by_id(self._last_values_by_id)
    # --- обновление значений --- #

    def update_by_id(self, values_by_id: Mapping[int, float]) -> None:
        """
        Обновляет значения строк статов.

        ВАЖНО:
        В строки панели отдаём СЫРЫЕ значения статов, без применения DescriptionFormula_Id.

        DescriptionFormula_Id нужен для текста подсказки при наведении.
        Если применять его прямо тут, то устойчивости начинают показывать не свои реальные
        значения, а проценты из hover-подсказки.
        """
        try:
            raw_vals = dict(values_by_id) if values_by_id is not None else {}
        except Exception:
            raw_vals = {}

        # сохраняем полный raw-набор
        self._last_values_by_id = dict(raw_vals)

        display_vals = dict(raw_vals)

        stat_ids_to_fill: set[int] = set()

        try:
            stat_ids_to_fill.update(int(x) for x in getattr(self, "rows_by_id", {}).keys())
        except Exception:
            pass

        try:
            widgets = getattr(self, "_extra_overlay_widgets", None)
            if isinstance(widgets, dict):
                stat_ids_to_fill.update(int(x) for x in widgets.keys())
        except Exception:
            pass

        try:
            for sd in getattr(self, "stat_defs", []) or []:
                stat_ids_to_fill.add(int(sd.id))
        except Exception:
            pass

        # Заполняем отсутствующие значения нулями, но НЕ применяем DescriptionFormula_Id.
        for sid in stat_ids_to_fill:
            try:
                sid_int = int(sid)
            except Exception:
                continue

            try:
                display_vals[sid_int] = float(raw_vals.get(sid_int, 0.0) or 0.0)
            except Exception:
                display_vals[sid_int] = 0.0

        self._last_display_values_by_id = dict(display_vals)

        for sid, row in list(getattr(self, "rows_by_id", {}).items()):
            try:
                sid_int = int(sid)
            except Exception:
                continue

            if row is None:
                continue

            try:
                row.set_value(display_vals.get(sid_int))
            except Exception:
                pass

        widgets = getattr(self, "_extra_overlay_widgets", None)
        if isinstance(widgets, dict):
            for sid, row in list(widgets.items()):
                try:
                    sid_int = int(sid)
                except Exception:
                    continue

                if row is None:
                    continue

                try:
                    if hasattr(row, "parent") and row.parent() is None:
                        continue
                except Exception:
                    pass

                try:
                    row.set_value(display_vals.get(sid_int))
                except Exception:
                    pass

        for vw in (self.visual_widgets or []):
            sid = getattr(vw, "_stat_id", None)
            if sid is None:
                continue

            try:
                val = display_vals.get(int(sid), 0)
            except Exception:
                val = 0

            try:
                vw.set_value_progress(val, step=10)
            except Exception:
                pass

        try:
            if getattr(self, "_current_group", "") == "extra":
                self._extra_overlay_sync_visible()
        except Exception:
            pass

        try:
            prev_pub = getattr(self, "_last_published_values_by_id", None)
            if not isinstance(prev_pub, dict) or prev_pub != display_vals:
                self._last_published_values_by_id = dict(display_vals)
                set_global_current_stats(self._last_published_values_by_id, src="stats_panel.update_by_id")
        except Exception:
            pass

    def update_by_code(self, values_by_code: Mapping[str, float]) -> None:
        for code, val in values_by_code.items():
            row = self.rows_by_code.get(code)
            if row is not None:
                row.set_value(val)

    def clear_values(self) -> None:
        self._last_values_by_id = {}
        for row in self.rows_by_id.values():
            row.set_value(None)

    def set_menu_bonus_enabled(self, flags: Optional[Mapping[str, bool]] = None) -> None:
        defaults = {
            "talents": True,
            "guild": True,
            "elixir": True,
            "consum": True,
            "aura": True,
            "buffs": True,
            "collect": True,
            "stamp": True,
            "reforge": True,
        }

        norm = dict(defaults)
        if isinstance(flags, Mapping):
            for k, v in flags.items():
                kk = str(k or "").strip().lower()
                if kk:
                    norm[kk] = bool(v)

        self.menu_bonus_enabled = dict(norm)

        try:
            if self.math is not None:
                self.math.menu_bonus_enabled = dict(norm)
        except Exception:
            pass

    def _start_external_equipment_recalc_watch(self) -> None:
        """
        Лёгкий watcher:
        если кто-то снаружи поменял содержимое уже известных equipment_rows
        (например применил карту к предмету, но не вызвал recalc_and_update),
        мы это замечаем и делаем полный перерасчёт по последним kwargs.
        """

        def _row_slot(it: dict) -> str:
            return str(
                it.get("_slot")
                or it.get("Slot")
                or it.get("slot")
                or it.get("SlotKey")
                or it.get("slot_key")
                or ""
            ).strip().lower()

        def _row_equip_id(it: dict) -> int:
            for k in ("Equipment_Id", "Equip_Id", "TemplateId", "Template_Id", "Item_Id", "Id"):
                try:
                    if k in it and it[k] not in (None, ""):
                        return int(it[k])
                except Exception:
                    pass
            return 0

        def _row_forge_level(it: dict) -> int:
            for k in ("__forge_level", "ForgeLevel", "UpgradeLevel", "Plus", "Refine", "EnhanceLevel"):
                try:
                    if k in it and it[k] not in (None, ""):
                        return int(it[k])
                except Exception:
                    pass
            return 0

        def _row_stamp_signature(it: dict) -> tuple:
            stamp = it.get("_stamp") or it.get("stamp") or it.get("Stamp")
            if isinstance(stamp, dict):
                return (
                    int(stamp.get("StampVariant_Id") or stamp.get("StampVariantId") or stamp.get("Variant_Id") or 0),
                    int(stamp.get("StampId") or stamp.get("Stamp_Id") or stamp.get("Id") or 0),
                    int(stamp.get("ColorId") or stamp.get("Color_Id") or stamp.get("StampColorId") or 0),
                )

            return (
                int(it.get("StampVariant_Id") or it.get("StampVariantId") or 0),
                int(it.get("StampId") or it.get("Stamp_Id") or 0),
                int(it.get("ColorId") or it.get("Color_Id") or it.get("StampColorId") or 0),
            )

        def _row_elixir_signature(it: dict) -> tuple:
            elx = it.get("Elixir") or it.get("_elixir") or it.get("elixir")
            if not isinstance(elx, dict):
                return ()
            bonuses = elx.get("Bonuses") or elx.get("bonuses") or []
            sig = []
            for b in (bonuses or []):
                if not isinstance(b, dict):
                    continue
                try:
                    sig.append((
                        int(b.get("Type_Id") or b.get("TypeId") or b.get("Type") or 0),
                        float(b.get("Value") or b.get("Val") or 0.0),
                    ))
                except Exception:
                    pass
            return (
                str(elx.get("Name") or ""),
                tuple(sig),
            )

        def _row_cards_signature(it: dict) -> tuple:
            cards_raw = it.get("_cards") or it.get("cards") or it.get("Cards")
            if isinstance(cards_raw, dict):
                cards = list(cards_raw.values())
            elif isinstance(cards_raw, (list, tuple)):
                cards = list(cards_raw)
            else:
                cards = []

            out = []
            for c in cards:
                cid = _resolve_card_id_from_entry(c)
                if cid > 0:
                    out.append(int(cid))
                    continue

                if isinstance(c, dict):
                    try:
                        out.append((
                            int(c.get("Id") or c.get("Card_Id") or 0),
                            str(c.get("Name") or ""),
                        ))
                    except Exception:
                        pass

            return tuple(out)

        def _rows_signature(rows) -> tuple:
            sig = []
            for raw in list(rows or []):
                if isinstance(raw, dict):
                    it = raw
                else:
                    try:
                        it = dict(raw)
                    except Exception:
                        sig.append(("raw", repr(raw)))
                        continue

                try:
                    sig.append((
                        _row_slot(it),
                        _row_equip_id(it),
                        int(_resolve_type_id(it) or 0),
                        _row_forge_level(it),
                        bool(it.get("_activate_checked", False)),
                        _row_stamp_signature(it),
                        _row_elixir_signature(it),
                        _row_cards_signature(it),
                    ))
                except Exception:
                    sig.append(("broken", repr(it)))

            return tuple(sig)

        try:
            rows_now = list(getattr(self, "_last_equipment_rows", []) or [])
        except Exception:
            rows_now = []

        try:
            self._last_equipment_watch_signature = _rows_signature(rows_now)
        except Exception:
            self._last_equipment_watch_signature = ()

        try:
            token = int(getattr(self, "_equipment_watch_token", 0) or 0) + 1
        except Exception:
            token = 1
        self._equipment_watch_token = int(token)

        def _tick():
            try:
                if int(getattr(self, "_equipment_watch_token", 0) or 0) != int(token):
                    return

                try:
                    rows_live = list(getattr(self, "_last_equipment_rows", []) or [])
                except Exception:
                    rows_live = []

                cur_sig = _rows_signature(rows_live)
                prev_sig = getattr(self, "_last_equipment_watch_signature", None)

                if prev_sig is None:
                    self._last_equipment_watch_signature = cur_sig
                elif cur_sig != prev_sig:
                    self._last_equipment_watch_signature = cur_sig

                    kwargs = getattr(self, "_last_recalc_kwargs", None)
                    if isinstance(kwargs, dict) and kwargs:
                        try:
                            self.recalc_and_update(**dict(kwargs))
                        except Exception:
                            import traceback
                            traceback.print_exc()
                        return

                QTimer.singleShot(150, _tick)
            except Exception:
                try:
                    QTimer.singleShot(300, _tick)
                except Exception:
                    pass

        try:
            QTimer.singleShot(150, _tick)
        except Exception:
            pass

    def recalc_and_update(
            self,
            *,
            class_id: int | None = None,
            class_name: str | None = None,
            level: int = 1,
            equipment_rows: Iterable[Mapping[int, float] | Mapping[str, float]] = (),
            base_stats: Mapping[int, float] | Mapping[str, float] = None,
            event_id: int = 0,
            state_id: int = 0,
            menu_bonus_enabled: Optional[Mapping[str, bool]] = None,
    ) -> Dict[int, float]:
        self.current_event_id = int(event_id or 0)
        self.current_state_id = int(state_id or 0)

        set_active_event_state(self.current_event_id, self.current_state_id)

        if menu_bonus_enabled is not None:
            try:
                self.set_menu_bonus_enabled(menu_bonus_enabled)
            except Exception:
                self.menu_bonus_enabled = dict(menu_bonus_enabled)

        if class_name is not None:
            new_name = (class_name or "").strip().lower()
            old_name = (getattr(self, "_current_class_name", "") or "").strip().lower()
            if new_name != old_name:
                self.set_class_name(class_name)

        if not self.math:
            return {}

        try:
            lvl = int(level)
        except Exception:
            lvl = 1

        if self._last_level_seen is None:
            self._last_level_seen = lvl
        else:
            if lvl > self._last_level_seen:
                gained = (lvl - self._last_level_seen) * self.math.stats_per_level()
                self.unspent_param_points += gained
            self._last_level_seen = lvl

        try:
            self._last_equipment_rows = list(equipment_rows or ())
        except Exception:
            self._last_equipment_rows = []

        try:
            self._last_recalc_kwargs = {
                "class_id": class_id,
                "class_name": class_name,
                "level": int(lvl),
                "equipment_rows": list(self._last_equipment_rows),
                "base_stats": dict(base_stats or {}) if isinstance(base_stats, Mapping) else base_stats,
                "event_id": int(event_id or 0),
                "state_id": int(state_id or 0),
                "menu_bonus_enabled": dict(menu_bonus_enabled or {}) if isinstance(menu_bonus_enabled,
                                                                                   Mapping) else menu_bonus_enabled,
            }
        except Exception:
            self._last_recalc_kwargs = {
                "class_id": class_id,
                "class_name": class_name,
                "level": int(lvl),
                "equipment_rows": list(self._last_equipment_rows),
                "base_stats": base_stats,
                "event_id": int(event_id or 0),
                "state_id": int(state_id or 0),
                "menu_bonus_enabled": menu_bonus_enabled,
            }

        try:
            if self.math is not None:
                self.math._shared_last_recalc_kwargs = dict(self._last_recalc_kwargs or {})
        except Exception:
            pass

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.setProperty("rq_last_recalc_kwargs", dict(self._last_recalc_kwargs or {}))
        except Exception:
            pass

        try:
            vals = self.math.calc_for_character(
                class_id=class_id,
                class_name=class_name,
                level=lvl,
                equipment_rows=self._last_equipment_rows,
                base_stats=base_stats,
                menu_bonus_enabled=getattr(self, "menu_bonus_enabled", None),
            )
        except Exception:
            import traceback
            traceback.print_exc()
            return {}

        try:
            vals = dict(vals or {})
        except Exception:
            vals = {}

        # ---------------- DPS (75) ----------------
        target_race_row = None
        target_element_row = None

        try:
            raw = getattr(self, "_creature_selected_race", None)
            if isinstance(raw, dict):
                target_race_row = dict(raw)
        except Exception:
            target_race_row = None

        try:
            raw = getattr(self, "_creature_selected_element", None)
            if isinstance(raw, dict):
                target_element_row = dict(raw)
        except Exception:
            target_element_row = None

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                if not isinstance(target_race_row, dict):
                    raw = app.property("rq_target_creature_top_race_row")
                    if isinstance(raw, dict):
                        target_race_row = dict(raw)

                if not isinstance(target_element_row, dict):
                    raw = app.property("rq_target_creature_top_element_row")
                    if isinstance(raw, dict):
                        target_element_row = dict(raw)
        except Exception:
            pass

        try:
            base_dbg = self.math._calc_formula15_payload(
                values_by_id=vals,
                equipment_rows=self._last_equipment_rows,
            )
        except Exception:
            import traceback
            traceback.print_exc()
            base_dbg = {
                "DPS_total": 0.0,
                "DPS_hit": 0.0,
                "DoTs": [],
            }

        try:
            dbg = self.math._apply_formula15_target_modifiers(
                payload=base_dbg,
                values_by_id=vals,
                target_race_row=target_race_row,
                target_element_row=target_element_row,
                equipment_rows=self._last_equipment_rows,
            )
        except Exception:
            import traceback
            traceback.print_exc()
            dbg = dict(base_dbg or {})

        try:
            self.math._formula15_debug_by_stat = {75: dict(dbg)}
        except Exception:
            pass

        try:
            vals[75] = float(dbg.get("DPS_total", 0.0) or 0.0)
        except Exception:
            vals[75] = 0.0

        # ---------------- EHP (76) / EHP(PvP) (77) ----------------
        conn = getattr(self, "conn", None)

        def _tof(v, d=0.0) -> float:
            try:
                return float(v)
            except Exception:
                try:
                    return float(str(v).replace(",", ".").strip())
                except Exception:
                    return d

        def _formula_id_for_stat(stat_id: int) -> int | None:
            try:
                sid = int(stat_id)
            except Exception:
                return None

            if conn is None or sid <= 0:
                return None

            cache = getattr(self, "_stat_formula_id_cache", None)
            if not isinstance(cache, dict):
                self._stat_formula_id_cache = {}
                cache = self._stat_formula_id_cache

            key = (id(conn), sid)
            if key not in cache:
                fid = None
                try:
                    row = conn.execute(
                        "SELECT DescriptionFormula_Id FROM Stat WHERE Id=? LIMIT 1",
                        (sid,),
                    ).fetchone()
                    if row is not None:
                        val = row[0] if not hasattr(row, "keys") else row["DescriptionFormula_Id"]
                        fid = int(val) if val is not None else None
                except Exception:
                    fid = None
                cache[key] = fid

            return cache.get(key)

        def _apply_formula_local(fid: int | None, raw_value: float) -> float:
            try:
                ffid = int(fid or 0)
            except Exception:
                ffid = 0

            vv = float(raw_value or 0.0)

            if ffid == 11:
                denom = (vv / 100.0) + 1.0
                return 0.0 if abs(denom) <= 1e-12 else (vv / denom)

            if ffid == 12:
                return vv - 100.0

            if ffid == 13:
                armor_bl = float(_armor_bl_for_level(int(lvl or 1)))
                if armor_bl <= 1e-12:
                    return 0.0
                return 100.0 * (1.0 - 1.0 / (1.0 + vv / armor_bl))

            if ffid == 20:
                lvl_f = float(int(lvl or 1))
                power = vv * (-0.6491 * lvl_f + 60.1007)
                return (1.0 - math.pow(0.999, power)) * 60.0

            return vv

        try:
            hp = _tof(vals.get(1, 0.0), 0.0)
        except Exception:
            hp = 0.0

        try:
            armor_raw = _tof(vals.get(12, 0.0), 0.0)
        except Exception:
            armor_raw = 0.0

        armor_fid = _formula_id_for_stat(12)
        def_resist = _apply_formula_local(armor_fid, armor_raw)

        # базовый EHP, который уже был правильным
        if hp > 0.0:
            denom = 1.0 - (float(def_resist) / 100.0)
            base_ehp = float(hp) / max(1e-12, denom)
        else:
            base_ehp = 0.0

        # нижняя цель для EHP
        ehp_target_race_row = None
        ehp_target_element_row = None

        try:
            raw = getattr(self, "_creature_selected_race2", None)
            if isinstance(raw, dict):
                ehp_target_race_row = dict(raw)
        except Exception:
            ehp_target_race_row = None

        try:
            raw = getattr(self, "_creature_selected_element2", None)
            if isinstance(raw, dict):
                ehp_target_element_row = dict(raw)
        except Exception:
            ehp_target_element_row = None

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                if not isinstance(ehp_target_race_row, dict):
                    raw = app.property("rq_target_creature_bottom_race_row")
                    if isinstance(raw, dict):
                        ehp_target_race_row = dict(raw)

                if not isinstance(ehp_target_element_row, dict):
                    raw = app.property("rq_target_creature_bottom_element_row")
                    if isinstance(raw, dict):
                        ehp_target_element_row = dict(raw)
        except Exception:
            pass

        race_per_def = 0.0
        try:
            race_stat_id = int((ehp_target_race_row or {}).get("DefStat_Id") or 0)
        except Exception:
            race_stat_id = 0

        if race_stat_id > 0:
            try:
                race_raw = _tof(vals.get(race_stat_id, 0.0), 0.0)
                race_fid = _formula_id_for_stat(race_stat_id)
                race_per_def = float(_apply_formula_local(race_fid, race_raw))
            except Exception:
                race_per_def = 0.0

        element_per_def = 0.0
        try:
            element_stat_id = int((ehp_target_element_row or {}).get("DefStat_Id") or 0)
        except Exception:
            element_stat_id = 0

        if element_stat_id > 0:
            try:
                element_raw = _tof(vals.get(element_stat_id, 0.0), 0.0)
                element_fid = _formula_id_for_stat(element_stat_id)
                element_per_def = float(_apply_formula_local(element_fid, element_raw))
            except Exception:
                element_per_def = 0.0

        final_ehp = float(base_ehp)

        if final_ehp > 0.0:
            denom = 1.0 - (float(race_per_def) / 100.0)
            final_ehp = float(final_ehp) / max(1e-12, denom)

        if final_ehp > 0.0:
            denom = 1.0 - (float(element_per_def) / 100.0)
            final_ehp = float(final_ehp) / max(1e-12, denom)

        vals[76] = float(final_ehp)

        # EHP(PvP) пока не трогаем по нижней цели.
        # Оставляем его на базе старого EHP-блока, чтобы не сломать текущую формулу 19.
        try:
            pvp_raw = _tof(vals.get(48, 0.0), 0.0)
        except Exception:
            pvp_raw = 0.0

        pvp_fid = _formula_id_for_stat(48)
        pvp_resist = _apply_formula_local(pvp_fid, pvp_raw)

        if float(base_ehp or 0.0) > 0.0:
            denom = 1.0 - (float(pvp_resist) / 100.0)
            vals[77] = float(base_ehp) / max(1e-12, denom)
        else:
            vals[77] = 0.0

        self.update_by_id(vals)

        try:
            self._start_external_equipment_recalc_watch()
        except Exception:
            pass

        return dict(vals or {})

class OtherCharacteristicsPanel(CharacteristicsPanel):
    """
    Правая панель для борда "Прочее".
    Использует тот же scroll/image-механизм, что и "Дополнительно",
    но со своим набором секций и без survival/pvp/elem_res.
    """
    ROOT_MARGINS = (8, 0, 8, 10)

    TAB_MAIN_RECT = (0, 0, 0, 0)
    TAB_EXTRA_RECT = (0, 0, 0, 0)
    TAB_BG_IMG = r"resources/__missing_other_tabs_bg__.png"

    EXTRA_VIEW_SIZE = (267, 385)
    EXTRA_IMG_PATH = r"resources/main_menu/other_char_bottom.png"
    EXTRA_SCROLL_WHEEL_STEP = 30
    EXTRA_ROW_VALUE_X = 193

    EXTRA_FIXED_TITLES = [
        ("general", "Основные показатели"),
        ("elem_dmg", "Урон по существам элемента"),
        ("race_res", "Урон по расам"),
    ]

    EXTRA_SECTION_STAT_IDS = {
        "general": [75, 60, 79, 78, 76, 77],
        "elem_dmg": [61, 62, 63, 64, 65, 66],
        "race_res": [68, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47],
    }

    # Верхний блок отдан под "конструктор существа", поэтому остальные секции сдвинуты ниже.
    EXTRA_SECTION_STATS_TOP_Y = {
        "general": 64,
        "elem_dmg": 210,
        "race_res": 354,
    }

    EXTRA_FIXED_TITLE_POS = {
        "general": (12, -2),
        "elem_dmg": (12, 185),
        "race_res": (12, 329),
    }

    EXTRA_FIXED_TITLE_FONT_PT = 12
    EXTRA_FIXED_TITLE_HEIGHT = 22
    EXTRA_FIXED_TITLE_COLOR = "#3b290c"

    EXTRA_FIXED_SHOW_IDS = False
    EXTRA_FIXED_IDS_FONT_PT = 9
    EXTRA_FIXED_IDS_HEIGHT = 14
    EXTRA_FIXED_IDS_COLOR = "#6a4b17"
    EXTRA_FIXED_IDS_GAP_Y = 0

    EXTRA_STATS_LEFT_X = 8
    EXTRA_STATS_TOP_Y = 72
    EXTRA_STATS_ROW_STEP = 20
    EXTRA_STATS_PRELOAD = 120
    EXTRA_STATS_RIGHT_PAD = 4

    CREATURE_BUTTON_SIZE = (21, 20)

    # ---------------- верхний блок ----------------
    CREATURE_RACE_BUTTON_POS = (3, 42)
    CREATURE_ELEMENT_BUTTON_POS = (157, 42)

    CREATURE_RACE_ICON_RECT = (28, 44, 17, 17)
    CREATURE_RACE_NAME_RECT = (47, 44, 108, 15)

    CREATURE_ELEMENT_ICON_RECTS = [
        (182, 47, 11, 11),
        (196, 47, 11, 11),
        (211, 47, 11, 11),
    ]

    # ---------------- нижний блок (+103 по Y) ----------------
    CREATURE_SECOND_BLOCK_Y_OFFSET = 103

    CREATURE_RACE2_BUTTON_POS = (3, 145)
    CREATURE_ELEMENT2_BUTTON_POS = (157, 145)

    CREATURE_RACE2_ICON_RECT = (28, 147, 17, 17)
    CREATURE_RACE2_NAME_RECT = (47, 147, 108, 15)

    CREATURE_ELEMENT2_ICON_RECT = (182, 150, 11, 11)

    CREATURE_POPUP_WIDTH = 152
    CREATURE_POPUP_ROW_H = 20
    CREATURE_POPUP_OFFSET_Y = 20

    CREATURE_RACE_ROW_ICON_RECT = (2, 1, 17, 17)
    CREATURE_RACE_ROW_TEXT_RECT = (22, 0, 126, 20)

    CREATURE_ELEMENT_ROW_ICON_SIZE = 11
    CREATURE_ELEMENT_ROW_ICON_GAP = 1

    def __init__(self, parent: QWidget | None = None, conn=None, param_state=None):
        super().__init__(parent=parent, conn=conn, param_state=param_state)

        self._creature_button_turn_pm = QPixmap(_res_path(r"resources/main_menu/menu_button_turn.png"))

        self._creature_race_rows: List[dict] = []
        self._creature_element_rows: List[dict] = []
        self._creature_element2_rows: List[dict] = []

        self._creature_selected_race: Optional[dict] = None
        self._creature_selected_element: Optional[dict] = None

        self._creature_selected_race2: Optional[dict] = None
        self._creature_selected_element2: Optional[dict] = None

        self._creature_open_popup: Optional[str] = None

        self._load_creature_constructor_data()
        self._init_creature_constructor_ui()
        self._apply_creature_constructor_defaults()

        try:
            parent_img = getattr(self, "dop_img_label", None)
            if isinstance(parent_img, QWidget):
                parent_img.installEventFilter(self)
        except Exception:
            pass

        try:
            self.set_group("extra")
        except Exception:
            pass

        self._refresh_creature_constructor_ui()
        self._creature_ui_raise()

    def _load_creature_constructor_data(self) -> None:
        self._creature_race_rows = []
        self._creature_element_rows = []
        self._creature_element2_rows = []

        conn = getattr(self, "conn", None)
        if conn is None:
            return

        # ---------- Race ----------
        try:
            rows = conn.execute(
                """
                SELECT Id, Name, Image_Id, DefStat_Id
                FROM Race
                WHERE IsPvP = 0
                ORDER BY Id ASC
                """
            ).fetchall()
        except Exception:
            rows = []

        for row in rows or []:
            try:
                race_id = _to_int(row["Id"] if hasattr(row, "keys") else row[0], 0)
                name = str((row["Name"] if hasattr(row, "keys") else row[1]) or "")
                image_id = _to_int(row["Image_Id"] if hasattr(row, "keys") else row[2], 0)
                def_stat_id = _to_int(row["DefStat_Id"] if hasattr(row, "keys") else row[3], 0)
            except Exception:
                continue

            if race_id <= 0:
                continue

            self._creature_race_rows.append(
                {
                    "Id": int(race_id),
                    "Name": str(name),
                    "Image_Id": int(image_id) if image_id > 0 else None,
                    "DefStat_Id": int(def_stat_id) if def_stat_id > 0 else None,
                }
            )

        # ---------- Верхний элемент: Monster_element_level ----------
        try:
            rows = conn.execute(
                """
                SELECT Id, Element_Id, Level, Image_Id
                FROM Monster_element_level
                ORDER BY Id ASC
                """
            ).fetchall()
        except Exception:
            rows = []

        for row in rows or []:
            try:
                elem_id = _to_int(row["Id"] if hasattr(row, "keys") else row[0], 0)
                element_id = _to_int(row["Element_Id"] if hasattr(row, "keys") else row[1], 0)
                level = _to_int(row["Level"] if hasattr(row, "keys") else row[2], 0)
                image_id = _to_int(row["Image_Id"] if hasattr(row, "keys") else row[3], 0)
            except Exception:
                continue

            if elem_id <= 0:
                continue

            self._creature_element_rows.append(
                {
                    "Id": int(elem_id),
                    "Element_Id": int(element_id),
                    "Level": max(0, int(level)),
                    "Image_Id": int(image_id) if image_id > 0 else None,
                }
            )

        # ---------- Нижний элемент: Element ----------
        try:
            rows = conn.execute(
                """
                SELECT Id, Name, IconImage_Id, DefStat_Id
                FROM Element
                ORDER BY Id ASC
                """
            ).fetchall()
        except Exception:
            rows = []

        for row in rows or []:
            try:
                elem_id = _to_int(row["Id"] if hasattr(row, "keys") else row[0], 0)
                name = str((row["Name"] if hasattr(row, "keys") else row[1]) or "")
                icon_image_id = _to_int(row["IconImage_Id"] if hasattr(row, "keys") else row[2], 0)
                def_stat_id = _to_int(row["DefStat_Id"] if hasattr(row, "keys") else row[3], 0)
            except Exception:
                continue

            if elem_id <= 0:
                continue

            self._creature_element2_rows.append(
                {
                    "Id": int(elem_id),
                    "Name": str(name),
                    "IconImage_Id": int(icon_image_id) if icon_image_id > 0 else None,
                    "DefStat_Id": int(def_stat_id) if def_stat_id > 0 else None,
                }
            )

    def _init_creature_constructor_ui(self) -> None:
        parent = getattr(self, "dop_img_label", None)
        if not isinstance(parent, QWidget):
            return

        try:
            parent.setMouseTracking(True)
        except Exception:
            pass

        popup_style = (
            "QFrame {"
            " background: rgba(238, 220, 181, 245);"
            " border: 1px solid rgba(59, 41, 12, 180);"
            " }"
        )

        row_style = (
            "QFrame { background: transparent; border: none; }"
            "QLabel { background: transparent; color: #3b290c; border: none; }"
        )

        hover_style = (
            "QFrame { background: rgba(174, 126, 54, 70); border: none; }"
            "QLabel { background: transparent; color: #3b290c; border: none; }"
        )

        POPUP_MAX_VISIBLE_ROWS = 11
        POPUP_SIDE_PAD = 4
        POPUP_TEXT_GAP = 4
        POPUP_MIN_WIDTH = 24

        def _contains_local(widget: QWidget, ev) -> bool:
            try:
                return widget.rect().contains(ev.position().toPoint())
            except Exception:
                try:
                    return widget.rect().contains(ev.pos())
                except Exception:
                    return False

        def _set_button_active(btn: QLabel, active: bool) -> None:
            if not isinstance(btn, QLabel):
                return
            if active and self._creature_button_turn_pm is not None and not self._creature_button_turn_pm.isNull():
                btn.setPixmap(self._creature_button_turn_pm)
            else:
                btn.clear()

        def _popup_blocked_for_button(popup_key: str) -> bool:
            opened = str(getattr(self, "_creature_open_popup", "") or "").strip().lower()
            if not opened:
                return False
            return opened != str(popup_key or "").strip().lower()

        def _bind_button(btn: QLabel, popup_key: str) -> None:
            btn._creature_hover = False  # type: ignore[attr-defined]
            btn._creature_pressed = False  # type: ignore[attr-defined]
            btn._creature_armed = False  # type: ignore[attr-defined]

            def _is_this_popup_open() -> bool:
                opened = str(getattr(self, "_creature_open_popup", "") or "").strip().lower()
                return opened == str(popup_key or "").strip().lower()

            def _enter(_e):
                btn._creature_hover = True  # type: ignore[attr-defined]
                if _popup_blocked_for_button(popup_key):
                    _set_button_active(btn, False)
                    return
                _set_button_active(btn, True)

            def _leave(_e):
                btn._creature_hover = False  # type: ignore[attr-defined]
                btn._creature_pressed = False  # type: ignore[attr-defined]
                btn._creature_armed = False  # type: ignore[attr-defined]

                # Если именно эта менюшка сейчас открыта — кнопка должна оставаться
                # в "активном" состоянии, как на hover/press.
                if _is_this_popup_open():
                    _set_button_active(btn, True)
                else:
                    _set_button_active(btn, False)

            def _press(ev):
                if ev.button() != Qt.LeftButton:
                    return QLabel.mousePressEvent(btn, ev)

                if _popup_blocked_for_button(popup_key):
                    btn._creature_pressed = False  # type: ignore[attr-defined]
                    btn._creature_armed = False  # type: ignore[attr-defined]
                    _set_button_active(btn, False)
                    ev.accept()
                    return

                btn._creature_pressed = True  # type: ignore[attr-defined]
                btn._creature_armed = True  # type: ignore[attr-defined]
                _set_button_active(btn, True)
                ev.accept()

            def _release(ev):
                if ev.button() != Qt.LeftButton:
                    return QLabel.mouseReleaseEvent(btn, ev)

                was_pressed = bool(getattr(btn, "_creature_pressed", False))
                armed = bool(getattr(btn, "_creature_armed", False))
                btn._creature_pressed = False  # type: ignore[attr-defined]
                btn._creature_armed = False  # type: ignore[attr-defined]

                if _popup_blocked_for_button(popup_key):
                    _set_button_active(btn, False)
                    ev.accept()
                    return

                inside = _contains_local(btn, ev)
                if was_pressed and armed and inside:
                    self._open_creature_popup(popup_key)

                # Если popup этой кнопки открыт — держим кнопку активной всегда.
                if _is_this_popup_open():
                    _set_button_active(btn, True)
                else:
                    _set_button_active(btn, bool(getattr(btn, "_creature_hover", False) and inside))

                ev.accept()

            btn.enterEvent = _enter  # type: ignore[assignment]
            btn.leaveEvent = _leave  # type: ignore[assignment]
            btn.mousePressEvent = _press  # type: ignore[assignment]
            btn.mouseReleaseEvent = _release  # type: ignore[assignment]

        def _popup_visible_height(row_count: int) -> int:
            rc = max(0, int(row_count))
            return max(1, min(POPUP_MAX_VISIBLE_ROWS, rc) * int(self.CREATURE_POPUP_ROW_H))

        def _popup_max_scroll(row_count: int) -> int:
            rc = max(0, int(row_count))
            return max(0, rc - POPUP_MAX_VISIBLE_ROWS)

        def _attach_popup_scroll(menu: QFrame, row_widgets: List[QFrame]) -> None:
            menu._popup_row_widgets = list(row_widgets)  # type: ignore[attr-defined]
            menu._popup_row_count = len(row_widgets)  # type: ignore[attr-defined]
            menu._popup_scroll_index = 0  # type: ignore[attr-defined]

            def _reposition_rows() -> None:
                scroll_index = max(0, int(getattr(menu, "_popup_scroll_index", 0)))
                row_h = int(self.CREATURE_POPUP_ROW_H)
                visible_rows = int(min(POPUP_MAX_VISIBLE_ROWS, max(0, len(row_widgets))))
                menu_w = int(menu.width())

                for idx, row in enumerate(row_widgets):
                    local_y = int((idx - scroll_index) * row_h)
                    row.setGeometry(0, local_y, menu_w, row_h)
                    row.setVisible(scroll_index <= idx < (scroll_index + visible_rows))

            def _wheel_event(ev):
                total = max(0, int(getattr(menu, "_popup_row_count", 0)))
                max_scroll = _popup_max_scroll(total)
                if max_scroll <= 0:
                    ev.accept()
                    return

                try:
                    delta_y = int(ev.angleDelta().y())
                except Exception:
                    delta_y = 0

                if delta_y == 0:
                    ev.accept()
                    return

                cur = max(0, int(getattr(menu, "_popup_scroll_index", 0)))
                steps = max(1, abs(delta_y) // 120)

                if delta_y < 0:
                    cur += steps
                else:
                    cur -= steps

                cur = max(0, min(max_scroll, cur))
                menu._popup_scroll_index = int(cur)  # type: ignore[attr-defined]
                _reposition_rows()
                ev.accept()

            menu._popup_reposition_rows = _reposition_rows  # type: ignore[attr-defined]
            menu.wheelEvent = _wheel_event  # type: ignore[assignment]
            _reposition_rows()

        def _make_row_item(menu: QFrame, *, y: int, on_release, render_content) -> QFrame:
            row = QFrame(menu)
            row.setGeometry(0, int(y), int(menu.width()), int(self.CREATURE_POPUP_ROW_H))
            row.setCursor(Qt.PointingHandCursor)
            row.setStyleSheet(row_style)
            row._pressed_inside = False  # type: ignore[attr-defined]
            row._hovered = False  # type: ignore[attr-defined]

            render_content(row)

            def _enter(_e):
                row._hovered = True  # type: ignore[attr-defined]
                row.setStyleSheet(hover_style)

            def _leave(_e):
                row._hovered = False  # type: ignore[attr-defined]
                row._pressed_inside = False  # type: ignore[attr-defined]
                row.setStyleSheet(row_style)

            def _press(ev):
                if ev.button() != Qt.LeftButton:
                    return QFrame.mousePressEvent(row, ev)
                row._pressed_inside = True  # type: ignore[attr-defined]
                row.setStyleSheet(hover_style)
                ev.accept()

            def _release(ev):
                if ev.button() != Qt.LeftButton:
                    return QFrame.mouseReleaseEvent(row, ev)

                was_pressed = bool(getattr(row, "_pressed_inside", False))
                row._pressed_inside = False  # type: ignore[attr-defined]
                inside = _contains_local(row, ev)

                if was_pressed and inside:
                    try:
                        on_release()
                    except Exception:
                        pass

                if inside and bool(getattr(row, "_hovered", False)):
                    row.setStyleSheet(hover_style)
                else:
                    row.setStyleSheet(row_style)
                ev.accept()

            row.enterEvent = _enter  # type: ignore[assignment]
            row.leaveEvent = _leave  # type: ignore[assignment]
            row.mousePressEvent = _press  # type: ignore[assignment]
            row.mouseReleaseEvent = _release  # type: ignore[assignment]
            return row

        def _metrics():
            try:
                return parent.fontMetrics()
            except Exception:
                try:
                    return self.fontMetrics()
                except Exception:
                    return None

        def _calc_race_popup_width() -> int:
            m = _metrics()
            icon_w = int(self.CREATURE_RACE_ROW_ICON_RECT[2])
            if m is None:
                text_w = 90
            else:
                text_w = 0
                for row in self._creature_race_rows:
                    try:
                        text_w = max(text_w, int(m.horizontalAdvance(str(row.get("Name") or ""))))
                    except Exception:
                        pass

            w = POPUP_SIDE_PAD + icon_w + POPUP_TEXT_GAP + text_w + POPUP_SIDE_PAD
            return max(POPUP_MIN_WIDTH, int(w))

        def _calc_top_element_popup_width() -> int:
            size = int(self.CREATURE_ELEMENT_ROW_ICON_SIZE)
            gap = int(self.CREATURE_ELEMENT_ROW_ICON_GAP)
            max_icons_w = 0

            for row in self._creature_element_rows:
                lvl = max(0, _to_int(row.get("Level"), 0))
                if lvl <= 0:
                    cur_w = size
                else:
                    cur_w = lvl * size + max(0, lvl - 1) * gap
                max_icons_w = max(max_icons_w, int(cur_w))

            w = POPUP_SIDE_PAD + max_icons_w + POPUP_SIDE_PAD
            return max(POPUP_MIN_WIDTH, int(w))

        def _calc_bottom_element_popup_width() -> int:
            m = _metrics()
            icon_w = 11
            if m is None:
                text_w = 70
            else:
                text_w = 0
                for row in self._creature_element2_rows:
                    try:
                        text_w = max(text_w, int(m.horizontalAdvance(str(row.get("Name") or ""))))
                    except Exception:
                        pass

            w = POPUP_SIDE_PAD + icon_w + POPUP_TEXT_GAP + text_w + POPUP_SIDE_PAD
            return max(POPUP_MIN_WIDTH, int(w))

        # ---------------- верхние кнопки ----------------
        bw, bh = self.CREATURE_BUTTON_SIZE
        rbx, rby = self.CREATURE_RACE_BUTTON_POS
        ebx, eby = self.CREATURE_ELEMENT_BUTTON_POS

        self.creature_race_button = QLabel(parent)
        self.creature_race_button.setGeometry(int(rbx), int(rby), int(bw), int(bh))
        self.creature_race_button.setScaledContents(True)
        self.creature_race_button.setStyleSheet("background: transparent; border: none;")
        self.creature_race_button.setCursor(Qt.PointingHandCursor)

        self.creature_element_button = QLabel(parent)
        self.creature_element_button.setGeometry(int(ebx), int(eby), int(bw), int(bh))
        self.creature_element_button.setScaledContents(True)
        self.creature_element_button.setStyleSheet("background: transparent; border: none;")
        self.creature_element_button.setCursor(Qt.PointingHandCursor)

        _bind_button(self.creature_race_button, "race_top")
        _bind_button(self.creature_element_button, "element_top")

        rx, ry, rw, rh = self.CREATURE_RACE_ICON_RECT
        self.creature_race_icon = QLabel(parent)
        self.creature_race_icon.setGeometry(int(rx), int(ry), int(rw), int(rh))
        self.creature_race_icon.setScaledContents(True)
        self.creature_race_icon.setStyleSheet("background: transparent; border: none;")
        self.creature_race_icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        nx, ny, nw, nh = self.CREATURE_RACE_NAME_RECT
        self.creature_race_name = QLabel(parent)
        self.creature_race_name.setGeometry(int(nx), int(ny), int(nw), int(nh))
        self.creature_race_name.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.creature_race_name.setStyleSheet("background: transparent; border: none; color: #ffffff;")
        self.creature_race_name.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.creature_element_icons: List[QLabel] = []
        for idx, rect in enumerate(self.CREATURE_ELEMENT_ICON_RECTS):
            x, y, w, h = rect
            lbl = QLabel(parent)
            lbl.setObjectName(f"OtherCreatureElementIcon{idx}")
            lbl.setGeometry(int(x), int(y), int(w), int(h))
            lbl.setScaledContents(True)
            lbl.setStyleSheet("background: transparent; border: none;")
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.creature_element_icons.append(lbl)

        # ---------------- нижние кнопки ----------------
        rbx2, rby2 = self.CREATURE_RACE2_BUTTON_POS
        ebx2, eby2 = self.CREATURE_ELEMENT2_BUTTON_POS

        self.creature_race2_button = QLabel(parent)
        self.creature_race2_button.setGeometry(int(rbx2), int(rby2), int(bw), int(bh))
        self.creature_race2_button.setScaledContents(True)
        self.creature_race2_button.setStyleSheet("background: transparent; border: none;")
        self.creature_race2_button.setCursor(Qt.PointingHandCursor)

        self.creature_element2_button = QLabel(parent)
        self.creature_element2_button.setGeometry(int(ebx2), int(eby2), int(bw), int(bh))
        self.creature_element2_button.setScaledContents(True)
        self.creature_element2_button.setStyleSheet("background: transparent; border: none;")
        self.creature_element2_button.setCursor(Qt.PointingHandCursor)

        _bind_button(self.creature_race2_button, "race_bottom")
        _bind_button(self.creature_element2_button, "element_bottom")

        rx2, ry2, rw2, rh2 = self.CREATURE_RACE2_ICON_RECT
        self.creature_race2_icon = QLabel(parent)
        self.creature_race2_icon.setGeometry(int(rx2), int(ry2), int(rw2), int(rh2))
        self.creature_race2_icon.setScaledContents(True)
        self.creature_race2_icon.setStyleSheet("background: transparent; border: none;")
        self.creature_race2_icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        nx2, ny2, nw2, nh2 = self.CREATURE_RACE2_NAME_RECT
        self.creature_race2_name = QLabel(parent)
        self.creature_race2_name.setGeometry(int(nx2), int(ny2), int(nw2), int(nh2))
        self.creature_race2_name.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.creature_race2_name.setStyleSheet("background: transparent; border: none; color: #ffffff;")
        self.creature_race2_name.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        ex2, ey2, ew2, eh2 = self.CREATURE_ELEMENT2_ICON_RECT
        self.creature_element2_icon = QLabel(parent)
        self.creature_element2_icon.setGeometry(int(ex2), int(ey2), int(ew2), int(eh2))
        self.creature_element2_icon.setScaledContents(True)
        self.creature_element2_icon.setStyleSheet("background: transparent; border: none;")
        self.creature_element2_icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        try:
            img_w = int(parent.width())
        except Exception:
            img_w = 267

        race_popup_w = _calc_race_popup_width()
        top_element_popup_w = _calc_top_element_popup_width()
        bottom_element_popup_w = _calc_bottom_element_popup_width()

        # ---------------- popup: race top ----------------
        self.creature_race_popup = QFrame(parent)
        self.creature_race_popup.setStyleSheet(popup_style)
        self.creature_race_popup.hide()
        self.creature_race_popup.setGeometry(
            int(rbx),
            int(rby + self.CREATURE_POPUP_OFFSET_Y),
            int(race_popup_w),
            int(_popup_visible_height(len(self._creature_race_rows))),
        )

        race_top_rows: List[QFrame] = []

        for idx, race in enumerate(self._creature_race_rows):
            def _render_race_row(row_parent: QFrame, race_row=dict(race)) -> None:
                ix, iy, iw, ih = self.CREATURE_RACE_ROW_ICON_RECT
                icon = QLabel(row_parent)
                icon.setGeometry(int(ix), int(iy), int(iw), int(ih))
                icon.setScaledContents(True)
                icon.setStyleSheet("background: transparent; border: none;")
                icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

                image_id = race_row.get("Image_Id")
                if image_id:
                    pm = self._load_image_pixmap(int(image_id))
                    if pm is not None and not pm.isNull():
                        icon.setPixmap(pm)

                menu_w = int(row_parent.parentWidget().width()) if row_parent.parentWidget() else int(race_popup_w)
                text = QLabel(str(race_row.get("Name") or ""), row_parent)
                text.setGeometry(22, 0, max(1, menu_w - 22 - POPUP_SIDE_PAD), int(self.CREATURE_POPUP_ROW_H))
                text.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                text.setStyleSheet("background: transparent; border: none; color: #3b290c;")
                text.setAttribute(Qt.WA_TransparentForMouseEvents, True)

            row = _make_row_item(
                self.creature_race_popup,
                y=idx * int(self.CREATURE_POPUP_ROW_H),
                on_release=lambda race_row=dict(race): self._select_creature_race("top", race_row),
                render_content=_render_race_row,
            )
            race_top_rows.append(row)

        _attach_popup_scroll(self.creature_race_popup, race_top_rows)

        # ---------------- popup: element top ----------------
        self.creature_element_popup = QFrame(parent)
        self.creature_element_popup.setStyleSheet(popup_style)
        self.creature_element_popup.hide()

        elem_popup_x = min(int(ebx), max(0, int(img_w) - int(top_element_popup_w)))
        self.creature_element_popup.setGeometry(
            int(elem_popup_x),
            int(eby + self.CREATURE_POPUP_OFFSET_Y),
            int(top_element_popup_w),
            int(_popup_visible_height(len(self._creature_element_rows))),
        )

        elem_top_rows: List[QFrame] = []

        for idx, elem in enumerate(self._creature_element_rows):
            def _render_element_row(row_parent: QFrame, elem_row=dict(elem)) -> None:
                size = int(self.CREATURE_ELEMENT_ROW_ICON_SIZE)
                gap = int(self.CREATURE_ELEMENT_ROW_ICON_GAP)
                level = max(0, _to_int(elem_row.get("Level"), 0))
                image_id = elem_row.get("Image_Id")
                pm = self._load_image_pixmap(int(image_id)) if image_id else None

                x = 2
                for _ in range(level):
                    icon = QLabel(row_parent)
                    icon.setGeometry(int(x), 4, int(size), int(size))
                    icon.setScaledContents(True)
                    icon.setStyleSheet("background: transparent; border: none;")
                    icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                    if pm is not None and not pm.isNull():
                        icon.setPixmap(pm)
                    x += int(size) + int(gap)

            row = _make_row_item(
                self.creature_element_popup,
                y=idx * int(self.CREATURE_POPUP_ROW_H),
                on_release=lambda elem_row=dict(elem): self._select_creature_element("top", elem_row),
                render_content=_render_element_row,
            )
            elem_top_rows.append(row)

        _attach_popup_scroll(self.creature_element_popup, elem_top_rows)

        # ---------------- popup: race bottom ----------------
        self.creature_race2_popup = QFrame(parent)
        self.creature_race2_popup.setStyleSheet(popup_style)
        self.creature_race2_popup.hide()
        self.creature_race2_popup.setGeometry(
            int(rbx2),
            int(rby2 + self.CREATURE_POPUP_OFFSET_Y),
            int(race_popup_w),
            int(_popup_visible_height(len(self._creature_race_rows))),
        )

        race_bottom_rows: List[QFrame] = []

        for idx, race in enumerate(self._creature_race_rows):
            def _render_race2_row(row_parent: QFrame, race_row=dict(race)) -> None:
                ix, iy, iw, ih = self.CREATURE_RACE_ROW_ICON_RECT
                icon = QLabel(row_parent)
                icon.setGeometry(int(ix), int(iy), int(iw), int(ih))
                icon.setScaledContents(True)
                icon.setStyleSheet("background: transparent; border: none;")
                icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

                image_id = race_row.get("Image_Id")
                if image_id:
                    pm = self._load_image_pixmap(int(image_id))
                    if pm is not None and not pm.isNull():
                        icon.setPixmap(pm)

                menu_w = int(row_parent.parentWidget().width()) if row_parent.parentWidget() else int(race_popup_w)
                text = QLabel(str(race_row.get("Name") or ""), row_parent)
                text.setGeometry(22, 0, max(1, menu_w - 22 - POPUP_SIDE_PAD), int(self.CREATURE_POPUP_ROW_H))
                text.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                text.setStyleSheet("background: transparent; border: none; color: #3b290c;")
                text.setAttribute(Qt.WA_TransparentForMouseEvents, True)

            row = _make_row_item(
                self.creature_race2_popup,
                y=idx * int(self.CREATURE_POPUP_ROW_H),
                on_release=lambda race_row=dict(race): self._select_creature_race("bottom", race_row),
                render_content=_render_race2_row,
            )
            race_bottom_rows.append(row)

        _attach_popup_scroll(self.creature_race2_popup, race_bottom_rows)

        # ---------------- popup: element bottom ----------------
        self.creature_element2_popup = QFrame(parent)
        self.creature_element2_popup.setStyleSheet(popup_style)
        self.creature_element2_popup.hide()

        elem2_popup_x = min(int(ebx2), max(0, int(img_w) - int(bottom_element_popup_w)))
        self.creature_element2_popup.setGeometry(
            int(elem2_popup_x),
            int(eby2 + self.CREATURE_POPUP_OFFSET_Y),
            int(bottom_element_popup_w),
            int(_popup_visible_height(len(self._creature_element2_rows))),
        )

        elem_bottom_rows: List[QFrame] = []

        for idx, elem2 in enumerate(self._creature_element2_rows):
            def _render_element2_row(row_parent: QFrame, elem_row=dict(elem2)) -> None:
                icon = QLabel(row_parent)
                icon.setGeometry(2, 4, 11, 11)
                icon.setScaledContents(True)
                icon.setStyleSheet("background: transparent; border: none;")
                icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

                image_id = _to_int(elem_row.get("IconImage_Id"), 0)
                if image_id > 0:
                    pm = self._load_image_pixmap(int(image_id))
                    if pm is not None and not pm.isNull():
                        icon.setPixmap(pm)

                menu_w = int(row_parent.parentWidget().width()) if row_parent.parentWidget() else int(
                    bottom_element_popup_w)
                text = QLabel(str(elem_row.get("Name") or ""), row_parent)
                text.setGeometry(17, 0, max(1, menu_w - 17 - POPUP_SIDE_PAD), int(self.CREATURE_POPUP_ROW_H))
                text.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                text.setStyleSheet("background: transparent; border: none; color: #3b290c;")
                text.setAttribute(Qt.WA_TransparentForMouseEvents, True)

            row = _make_row_item(
                self.creature_element2_popup,
                y=idx * int(self.CREATURE_POPUP_ROW_H),
                on_release=lambda elem_row=dict(elem2): self._select_creature_element("bottom", elem_row),
                render_content=_render_element2_row,
            )
            elem_bottom_rows.append(row)

        _attach_popup_scroll(self.creature_element2_popup, elem_bottom_rows)

    def _apply_creature_constructor_defaults(self) -> None:
        race_default = None
        for row in self._creature_race_rows:
            if _to_int(row.get("Id"), 0) == 1:
                race_default = row
                break
        if race_default is None and self._creature_race_rows:
            race_default = self._creature_race_rows[0]

        elem_default_top = self._creature_element_rows[-1] if self._creature_element_rows else None
        elem_default_bottom = self._creature_element2_rows[-1] if self._creature_element2_rows else None

        saved_top_race = None
        saved_top_element = None
        saved_bottom_race = None
        saved_bottom_element = None

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                raw = app.property("rq_target_creature_top_race_row")
                if isinstance(raw, dict) and raw:
                    saved_top_race = dict(raw)

                raw = app.property("rq_target_creature_top_element_row")
                if isinstance(raw, dict) and raw:
                    saved_top_element = dict(raw)

                raw = app.property("rq_target_creature_bottom_race_row")
                if isinstance(raw, dict) and raw:
                    saved_bottom_race = dict(raw)

                raw = app.property("rq_target_creature_bottom_element_row")
                if isinstance(raw, dict) and raw:
                    saved_bottom_element = dict(raw)
        except Exception:
            pass

        self._creature_selected_race = (
            dict(saved_top_race)
            if isinstance(saved_top_race, dict) and saved_top_race
            else (dict(race_default) if isinstance(race_default, dict) else None)
        )

        self._creature_selected_element = (
            dict(saved_top_element)
            if isinstance(saved_top_element, dict) and saved_top_element
            else (dict(elem_default_top) if isinstance(elem_default_top, dict) else None)
        )

        self._creature_selected_race2 = (
            dict(saved_bottom_race)
            if isinstance(saved_bottom_race, dict) and saved_bottom_race
            else (dict(race_default) if isinstance(race_default, dict) else None)
        )

        self._creature_selected_element2 = (
            dict(saved_bottom_element)
            if isinstance(saved_bottom_element, dict) and saved_bottom_element
            else (dict(elem_default_bottom) if isinstance(elem_default_bottom, dict) else None)
        )

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.setProperty(
                    "rq_target_creature_top_race_row",
                    dict(self._creature_selected_race or {}) if isinstance(self._creature_selected_race, dict) else {},
                )
                app.setProperty(
                    "rq_target_creature_top_element_row",
                    dict(self._creature_selected_element or {}) if isinstance(self._creature_selected_element,
                                                                              dict) else {},
                )
                app.setProperty(
                    "rq_target_creature_bottom_race_row",
                    dict(self._creature_selected_race2 or {}) if isinstance(self._creature_selected_race2,
                                                                            dict) else {},
                )
                app.setProperty(
                    "rq_target_creature_bottom_element_row",
                    dict(self._creature_selected_element2 or {}) if isinstance(self._creature_selected_element2,
                                                                               dict) else {},
                )
        except Exception:
            pass

        try:
            if self.math is not None:
                self.math._shared_target_race_row = (
                    dict(self._creature_selected_race or {})
                    if isinstance(self._creature_selected_race, dict)
                    else {}
                )
                self.math._shared_target_element_row = (
                    dict(self._creature_selected_element or {})
                    if isinstance(self._creature_selected_element, dict)
                    else {}
                )
        except Exception:
            pass

    def _close_creature_popups(self, refresh: bool = True) -> None:
        self._creature_open_popup = None

        for name in (
                "creature_race_popup",
                "creature_element_popup",
                "creature_race2_popup",
                "creature_element2_popup",
        ):
            popup = getattr(self, name, None)
            if isinstance(popup, QWidget):
                popup.hide()

        if refresh:
            self._refresh_creature_constructor_ui()

    def _open_creature_popup(self, kind: str) -> None:
        want = str(kind or "").strip().lower()
        if want not in ("race_top", "element_top", "race_bottom", "element_bottom"):
            return

        if self._creature_open_popup == want:
            self._close_creature_popups(refresh=True)
            return

        self._close_creature_popups(refresh=False)
        self._creature_open_popup = want

        popup_name = {
            "race_top": "creature_race_popup",
            "element_top": "creature_element_popup",
            "race_bottom": "creature_race2_popup",
            "element_bottom": "creature_element2_popup",
        }.get(want, "")

        popup = getattr(self, popup_name, None)
        if isinstance(popup, QWidget):
            popup.show()
            popup.raise_()

        self._creature_ui_raise()
        self._refresh_creature_constructor_ui()

        # ВАЖНО:
        # после открытия popup кнопка может получить leaveEvent и очистить turn-иконку.
        # Возвращаем активное состояние уже после завершения текущей очереди событий.
        try:
            QTimer.singleShot(0, self._refresh_creature_constructor_ui)
        except Exception:
            pass

    def _select_creature_race(self, target: str, race_row: dict) -> None:
        tgt = str(target or "").strip().lower()
        picked = dict(race_row or {}) if isinstance(race_row, dict) else None

        if tgt == "top":
            self._creature_selected_race = picked
        elif tgt == "bottom":
            self._creature_selected_race2 = picked
        else:
            return

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                if tgt == "top":
                    app.setProperty(
                        "rq_target_creature_top_race_row",
                        dict(picked or {}) if isinstance(picked, dict) else {},
                    )
                else:
                    app.setProperty(
                        "rq_target_creature_bottom_race_row",
                        dict(picked or {}) if isinstance(picked, dict) else {},
                    )
        except Exception:
            pass

        try:
            if self.math is not None:
                if tgt == "top":
                    self.math._shared_target_race_row = dict(picked or {}) if isinstance(picked, dict) else {}
        except Exception:
            pass

        self._close_creature_popups(refresh=False)
        self._refresh_creature_constructor_ui()

        refreshed = False

        try:
            owner = self.window()
        except Exception:
            owner = None

        cur = owner if owner is not None else self
        seen = set()

        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))

            fn = getattr(cur, "refresh_stats_panel", None)
            if callable(fn):
                try:
                    fn()
                    try:
                        QTimer.singleShot(0, fn)
                    except Exception:
                        pass
                    refreshed = True
                    break
                except Exception:
                    import traceback
                    traceback.print_exc()
                    break

            try:
                cur = cur.parentWidget()
            except Exception:
                cur = None

        if not refreshed:
            local_kwargs = getattr(self, "_last_recalc_kwargs", None)

            try:
                shared_kwargs = getattr(self.math, "_shared_last_recalc_kwargs",
                                        None) if self.math is not None else None
            except Exception:
                shared_kwargs = None

            try:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
                app_kwargs = app.property("rq_last_recalc_kwargs") if app is not None else None
            except Exception:
                app_kwargs = None

            kwargs = local_kwargs if isinstance(local_kwargs, dict) and local_kwargs else (
                shared_kwargs if isinstance(shared_kwargs, dict) and shared_kwargs else app_kwargs
            )

            if isinstance(kwargs, dict) and kwargs:
                try:
                    self.recalc_and_update(**dict(kwargs))
                except Exception:
                    import traceback
                    traceback.print_exc()

        self._refresh_creature_constructor_ui()

    def _select_creature_element(self, target: str, elem_row: dict) -> None:
        tgt = str(target or "").strip().lower()
        picked = dict(elem_row or {}) if isinstance(elem_row, dict) else None

        if tgt == "top":
            self._creature_selected_element = picked
        elif tgt == "bottom":
            self._creature_selected_element2 = picked
        else:
            return

        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                if tgt == "top":
                    app.setProperty(
                        "rq_target_creature_top_element_row",
                        dict(picked or {}) if isinstance(picked, dict) else {},
                    )
                else:
                    app.setProperty(
                        "rq_target_creature_bottom_element_row",
                        dict(picked or {}) if isinstance(picked, dict) else {},
                    )
        except Exception:
            pass

        try:
            if self.math is not None:
                if tgt == "top":
                    self.math._shared_target_element_row = dict(picked or {}) if isinstance(picked, dict) else {}
        except Exception:
            pass

        self._close_creature_popups(refresh=False)
        self._refresh_creature_constructor_ui()

        refreshed = False

        try:
            owner = self.window()
        except Exception:
            owner = None

        cur = owner if owner is not None else self
        seen = set()

        while cur is not None and id(cur) not in seen:
            seen.add(id(cur))

            fn = getattr(cur, "refresh_stats_panel", None)
            if callable(fn):
                try:
                    fn()
                    try:
                        QTimer.singleShot(0, fn)
                    except Exception:
                        pass
                    refreshed = True
                    break
                except Exception:
                    import traceback
                    traceback.print_exc()
                    break

            try:
                cur = cur.parentWidget()
            except Exception:
                cur = None

        if not refreshed:
            local_kwargs = getattr(self, "_last_recalc_kwargs", None)

            try:
                shared_kwargs = getattr(self.math, "_shared_last_recalc_kwargs",
                                        None) if self.math is not None else None
            except Exception:
                shared_kwargs = None

            try:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
                app_kwargs = app.property("rq_last_recalc_kwargs") if app is not None else None
            except Exception:
                app_kwargs = None

            kwargs = local_kwargs if isinstance(local_kwargs, dict) and local_kwargs else (
                shared_kwargs if isinstance(shared_kwargs, dict) and shared_kwargs else app_kwargs
            )

            if isinstance(kwargs, dict) and kwargs:
                try:
                    self.recalc_and_update(**dict(kwargs))
                except Exception:
                    import traceback
                    traceback.print_exc()

        self._refresh_creature_constructor_ui()

    def _refresh_creature_constructor_ui(self) -> None:
        # ---------- верхний блок ----------
        race_row = self._creature_selected_race if isinstance(self._creature_selected_race, dict) else {}
        elem_row = self._creature_selected_element if isinstance(self._creature_selected_element, dict) else {}

        race_icon = getattr(self, "creature_race_icon", None)
        if isinstance(race_icon, QLabel):
            race_icon.clear()
            image_id = _to_int(race_row.get("Image_Id"), 0)
            if image_id > 0:
                pm = self._load_image_pixmap(int(image_id))
                if pm is not None and not pm.isNull():
                    race_icon.setPixmap(pm)

        race_name = getattr(self, "creature_race_name", None)
        if isinstance(race_name, QLabel):
            race_name.setText(str(race_row.get("Name") or ""))

        elem_image_id = _to_int(elem_row.get("Image_Id"), 0)
        elem_level = max(0, min(3, _to_int(elem_row.get("Level"), 0)))
        elem_pm = self._load_image_pixmap(int(elem_image_id)) if elem_image_id > 0 else None

        for idx, lbl in enumerate(getattr(self, "creature_element_icons", []) or []):
            if not isinstance(lbl, QLabel):
                continue
            lbl.clear()
            if idx < int(elem_level) and elem_pm is not None and not elem_pm.isNull():
                lbl.setPixmap(elem_pm)

        # ---------- нижний блок ----------
        race_row2 = self._creature_selected_race2 if isinstance(self._creature_selected_race2, dict) else {}
        elem_row2 = self._creature_selected_element2 if isinstance(self._creature_selected_element2, dict) else {}

        race_icon2 = getattr(self, "creature_race2_icon", None)
        if isinstance(race_icon2, QLabel):
            race_icon2.clear()
            image_id = _to_int(race_row2.get("Image_Id"), 0)
            if image_id > 0:
                pm = self._load_image_pixmap(int(image_id))
                if pm is not None and not pm.isNull():
                    race_icon2.setPixmap(pm)

        race_name2 = getattr(self, "creature_race2_name", None)
        if isinstance(race_name2, QLabel):
            race_name2.setText(str(race_row2.get("Name") or ""))

        elem_icon2 = getattr(self, "creature_element2_icon", None)
        if isinstance(elem_icon2, QLabel):
            elem_icon2.clear()
            image_id = _to_int(elem_row2.get("IconImage_Id"), 0)
            if image_id > 0:
                pm = self._load_image_pixmap(int(image_id))
                if pm is not None and not pm.isNull():
                    elem_icon2.setPixmap(pm)

        # ---------- активные кнопки при открытом popup ----------
        open_popup = str(getattr(self, "_creature_open_popup", "") or "").strip().lower()

        btn_map = {
            "race_top": getattr(self, "creature_race_button", None),
            "element_top": getattr(self, "creature_element_button", None),
            "race_bottom": getattr(self, "creature_race2_button", None),
            "element_bottom": getattr(self, "creature_element2_button", None),
        }

        for key, btn in btn_map.items():
            if not isinstance(btn, QLabel):
                continue

            is_active = (open_popup == key)
            if is_active and self._creature_button_turn_pm is not None and not self._creature_button_turn_pm.isNull():
                btn.setPixmap(self._creature_button_turn_pm)
            else:
                btn.clear()

        self._creature_ui_raise()

    def _creature_ui_raise(self) -> None:
        # сначала обычные элементы панели
        for name in (
                "creature_race_button",
                "creature_element_button",
                "creature_race_icon",
                "creature_race_name",
                "creature_race2_button",
                "creature_element2_button",
                "creature_race2_icon",
                "creature_race2_name",
                "creature_element2_icon",
        ):
            w = getattr(self, name, None)
            if isinstance(w, QWidget):
                try:
                    w.raise_()
                except Exception:
                    pass

        for lbl in getattr(self, "creature_element_icons", []) or []:
            if isinstance(lbl, QWidget):
                try:
                    lbl.raise_()
                except Exception:
                    pass

        # popup-ы всегда последними, чтобы ничего не рисовалось поверх них
        for name in (
                "creature_race_popup",
                "creature_element_popup",
                "creature_race2_popup",
                "creature_element2_popup",
        ):
            w = getattr(self, name, None)
            if isinstance(w, QWidget):
                try:
                    w.raise_()
                except Exception:
                    pass

    def _extra_overlay_sync_visible(self) -> None:
        super()._extra_overlay_sync_visible()
        self._creature_ui_raise()

    def _rebuild_rows_for_group(self, group: str) -> None:
        if group != "extra":
            return super()._rebuild_rows_for_group(group)

        self.DEBUG_EXTRA_HEADERS = True

        prev_group = getattr(self, "_last_rebuild_group", None)
        group_switched = (prev_group != group)
        setattr(self, "_last_rebuild_group", group)

        self._clear_rows()
        try:
            for ch in self._rows_frame.findChildren(QLabel):
                n = ch.objectName() or ""
                if (
                        n.startswith("extra_section_title__")
                        or n.startswith("extra_section_ids__")
                        or n.startswith("main_section_label__")
                ):
                    ch.deleteLater()
        except Exception:
            pass

        y_shift = int(getattr(self, "CONTENT_Y_SHIFT", -4) or 0)
        self._extra_y_shift = int(y_shift)

        stat_by_id: Dict[int, StatDef] = {}
        for sd in self.stat_defs:
            try:
                stat_by_id[int(sd.id)] = sd
            except Exception:
                pass

        def _force_sizes(content_h: int) -> None:
            try:
                content_h = int(max(0, content_h))
            except Exception:
                content_h = 0

            try:
                self._rows_frame.setMinimumHeight(content_h)
            except Exception:
                pass

            try:
                w = int(self._rows_frame.width())
                if w <= 0:
                    w = int(getattr(self, "ROW_WIDTH", 1) or 1)
                self._rows_frame.resize(max(1, w), max(1, content_h))
            except Exception:
                pass

            try:
                self._rows_frame.updateGeometry()
                self._rows_frame.update()
            except Exception:
                pass

        ids_map = getattr(self, "EXTRA_SECTION_STAT_IDS", None)
        if not isinstance(ids_map, dict):
            ids_map = {}

        title_pos = getattr(self, "EXTRA_FIXED_TITLE_POS", None)
        if not isinstance(title_pos, dict):
            title_pos = {}

        title_h = int(getattr(self, "EXTRA_FIXED_TITLE_HEIGHT", getattr(self, "TITLE_HEIGHT", 18)) or 18)
        row_h = int(getattr(self, "ROW_HEIGHT", 18) or 18)
        default_step = int(getattr(self, "EXTRA_STATS_ROW_STEP", 20) or 20)

        layout: List[tuple[StatDef, int]] = []
        present_ids_map: Dict[str, List[int]] = {}

        # ---------------------------------------------------------
        # GENERAL:
        #   75                     -> над первой менюшкой
        #   60,79,78,76           -> между менюшками
        #   77                    -> почти сразу под нижней менюшкой
        # ---------------------------------------------------------
        general_ids_all = [int(x) for x in (ids_map.get("general", []) or [])]

        general_top_ids = [75]
        general_middle_ids = [60, 79, 78, 76]
        general_bottom_ids = [77]

        # если вдруг каких-то id нет в таблице stat_defs, просто пропустятся
        general_top_start_y = 20

        # пространство между первой и второй менюшкой
        general_middle_start_y = 66
        general_middle_step = 20

        # сразу под нижней менюшкой
        general_bottom_start_y = 168

        present_general: List[int] = []

        idx = 0
        for sid in general_top_ids:
            if sid not in general_ids_all:
                continue
            sd = stat_by_id.get(int(sid))
            if not sd:
                continue
            y = int(general_top_start_y + idx * default_step)
            layout.append((sd, y))
            present_general.append(int(sid))
            idx += 1

        idx = 0
        for sid in general_middle_ids:
            if sid not in general_ids_all:
                continue
            sd = stat_by_id.get(int(sid))
            if not sd:
                continue
            y = int(general_middle_start_y + idx * general_middle_step)
            layout.append((sd, y))
            present_general.append(int(sid))
            idx += 1

        idx = 0
        for sid in general_bottom_ids:
            if sid not in general_ids_all:
                continue
            sd = stat_by_id.get(int(sid))
            if not sd:
                continue
            y = int(general_bottom_start_y + idx * default_step)
            layout.append((sd, y))
            present_general.append(int(sid))
            idx += 1

        present_ids_map["general"] = present_general

        # ---------------------------------------------------------
        # остальные секции
        # ---------------------------------------------------------
        section_defs: List[tuple[str, str, List[int]]] = [
            ("elem_dmg", "Урон по элементам", [int(x) for x in (ids_map.get("elem_dmg", []) or [])]),
            ("race_res", "Урон по расам", [int(x) for x in (ids_map.get("race_res", []) or [])]),
        ]

        top_map = getattr(self, "EXTRA_SECTION_STATS_TOP_Y", None)
        if not isinstance(top_map, dict):
            top_map = {}

        step_map = getattr(self, "EXTRA_SECTION_ROW_STEP", None)
        if not isinstance(step_map, dict):
            step_map = {}

        for sec_key, _sec_title, ids in section_defs:
            want_ids: List[int] = []
            for x in ids:
                try:
                    want_ids.append(int(x))
                except Exception:
                    pass

            start_y = top_map.get(sec_key, None)
            if start_y is None:
                try:
                    start_y = int(title_pos.get(sec_key, (0, 0))[1]) + int(title_h) + 2
                except Exception:
                    start_y = int(title_h) + 2

            try:
                start_y = int(start_y)
            except Exception:
                start_y = 0

            sec_step = step_map.get(sec_key, default_step)
            try:
                sec_step = int(sec_step)
            except Exception:
                sec_step = int(default_step)

            present: List[int] = []
            idx = 0
            for sid in want_ids:
                sd = stat_by_id.get(int(sid))
                if not sd:
                    continue
                y = int(start_y + idx * sec_step)
                layout.append((sd, y))
                present.append(int(sid))
                idx += 1

            present_ids_map[sec_key] = present

        setattr(self, "_extra_section_present_ids", present_ids_map)
        setattr(self, "_extra_overlay_layout", layout)

        try:
            if hasattr(self, "_extra_overlay_sync_visible"):
                self._extra_overlay_sync_visible()
        except Exception:
            pass

        if self._last_values_by_id:
            self.update_by_id(self._last_values_by_id)

        if layout:
            bottom = max(int(y) for _, y in layout) + row_h + 8
        else:
            bottom = 0
        _force_sizes(bottom)

        try:
            if group_switched and hasattr(self, "_extra_scroll_set_offset"):
                self._extra_scroll_set_offset(0)
            elif hasattr(self, "_extra_scroll_update_bar"):
                self._extra_scroll_update_bar()
        except Exception:
            pass

    def eventFilter(self, obj, event):
        try:
            ev_type = event.type()
        except Exception:
            ev_type = None

        try:
            parent_img = getattr(self, "dop_img_label", None)
        except Exception:
            parent_img = None

        if obj is parent_img and ev_type is not None:
            try:
                mouse_press_type = event.Type.MouseButtonPress
            except Exception:
                try:
                    from PySide6.QtCore import QEvent
                    mouse_press_type = QEvent.MouseButtonPress
                except Exception:
                    mouse_press_type = None

            if ev_type == mouse_press_type:
                if str(getattr(self, "_creature_open_popup", "") or "").strip():
                    try:
                        btn = event.button()
                    except Exception:
                        btn = None

                    if btn == Qt.LeftButton:
                        self._close_creature_popups()

        return super().eventFilter(obj, event)