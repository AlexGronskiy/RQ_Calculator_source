# equipment_elixir.py
from __future__ import annotations

from typing import Iterable, Optional


def _table_exists(conn, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (str(name),),
        ).fetchone()
    except Exception:
        row = None
    return bool(row)


def get_elixir_meta(conn, elixir_id: int) -> Optional[dict]:
    """
    EquipmentElixir: Id, Name, Image_Id
    """
    if conn is None:
        return None
    try:
        elixir_id = int(elixir_id or 0)
    except Exception:
        elixir_id = 0
    if elixir_id <= 0:
        return None

    if not _table_exists(conn, "EquipmentElixir"):
        return None

    try:
        row = conn.execute(
            "SELECT Id, Name, Image_Id FROM EquipmentElixir WHERE Id=? LIMIT 1",
            (int(elixir_id),),
        ).fetchone()
    except Exception:
        row = None

    if not row:
        return None

    try:
        if hasattr(row, "keys"):
            return {
                "Id": int(row["Id"] or 0),
                "Name": row["Name"] or "",
                "Image_Id": row["Image_Id"],
            }
        return {"Id": int(row[0] or 0), "Name": row[1] or "", "Image_Id": row[2] if len(row) > 2 else None}
    except Exception:
        return None


def get_elixir_bonuses(conn, elixir_id: int) -> list[dict]:
    """
    EquipmentElixirBonus: EquipmentElixir_Id, Type_Id, Value, OrderIndex
    """
    if conn is None:
        return []
    try:
        elixir_id = int(elixir_id or 0)
    except Exception:
        elixir_id = 0
    if elixir_id <= 0:
        return []

    if not (_table_exists(conn, "EquipmentElixirBonus") and _table_exists(conn, "EquipmentElixir")):
        return []

    try:
        rows = conn.execute(
            """
            SELECT Type_Id, Value, OrderIndex
            FROM EquipmentElixirBonus
            WHERE EquipmentElixir_Id=?
            ORDER BY OrderIndex
            """,
            (int(elixir_id),),
        ).fetchall()
    except Exception:
        rows = []

    out: list[dict] = []
    for r in rows or []:
        try:
            if hasattr(r, "keys"):
                bt = int(r["Type_Id"] or 0)
                val = int(r["Value"] or 0)
                oi = int(r["OrderIndex"] or 0)
            else:
                bt = int(r[0] or 0)
                val = int(r[1] or 0)
                oi = int(r[2] or 0) if len(r) > 2 else 0
        except Exception:
            continue
        out.append({"Type_Id": bt, "Value": val, "OrderIndex": oi})
    return out


def list_elixirs_for_slots(conn, slot_ids: Iterable[int]) -> list[dict]:
    """
    Список доступных эликсиров для одного или нескольких EquipmentSlot.Id
    (используется для контекстного меню по Ctrl+ПКМ).
    """
    if conn is None:
        return []

    try:
        ids = [int(x) for x in (slot_ids or []) if int(x) > 0]
    except Exception:
        ids = []
    if not ids:
        return []

    if not (_table_exists(conn, "EquipmentElixir") and _table_exists(conn, "EquipmentElixirSlot")):
        return []

    ph = ",".join(["?"] * len(ids))
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT ee.Id, ee.Name, ee.Image_Id
            FROM EquipmentElixir ee
            JOIN EquipmentElixirSlot es ON es.EquipmentElixir_Id = ee.Id
            WHERE es.EquipmentSlot_Id IN ({ph})
            ORDER BY ee.Name COLLATE NOCASE
            """,
            tuple(int(x) for x in ids),
        ).fetchall()
    except Exception:
        rows = []

    out: list[dict] = []
    for r in rows or []:
        try:
            if hasattr(r, "keys"):
                out.append(
                    {"Id": int(r["Id"] or 0), "Name": r["Name"] or "", "Image_Id": r["Image_Id"]}
                )
            else:
                out.append(
                    {"Id": int(r[0] or 0), "Name": r[1] or "", "Image_Id": r[2] if len(r) > 2 else None}
                )
        except Exception:
            continue
    return out