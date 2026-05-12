from __future__ import annotations

import json
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Qt, QRect, QSize, QEvent, Signal, QPoint
from PySide6.QtGui import QPixmap, QPainter, QColor, QPen, QPalette
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QFrame,
    QApplication,
)


# =========================
# CONFIG
# =========================
@dataclass(frozen=True)
class SaveLoadManagerConfig:
    save_bg_path: str = "resources/save_manager/save_schem.png"
    load_bg_path: str = "resources/save_manager/load_schem.png"
    fallback_size: tuple[int, int] = (562, 372)

    close_rect: tuple[int, int, int, int] = (525, 3, 24, 24)
    close_active_path: str = "resources/helper_buttons/close_button_active.png"

    filename_rect: tuple[int, int, int, int] = (17, 325, 295, 28)

    list_rect: tuple[int, int, int, int] = (14, 78, 528, 245)
    vscroll_rect: tuple[int, int, int, int] = (519, 78, 22, 242)

    action_rect: tuple[int, int, int, int] = (315, 324, 112, 35)
    action_visual_size: tuple[int, int] = (118, 41)

    cancel_rect: tuple[int, int, int, int] = (430, 324, 112, 35)
    cancel_visual_size: tuple[int, int] = (118, 41)

    save_active_path: str = "resources/save_manager/save.png"
    load_active_path: str = "resources/save_manager/load.png"
    cancel_active_path: str = "resources/save_manager/cancel.png"


CFG = SaveLoadManagerConfig()


# =========================
# HELPERS
# =========================
def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        try:
            return int(float(str(v).strip()))
        except Exception:
            return int(default)


def _resolve_resource(rel_path: str) -> str:
    p = Path(rel_path)

    candidates = []

    try:
        if getattr(sys, "frozen", False):
            candidates.append(Path(sys.executable).resolve().parent / p)
    except Exception:
        pass

    try:
        candidates.append(Path.cwd() / p)
    except Exception:
        pass

    try:
        here = Path(__file__).resolve()
        candidates.append(here.parents[2] / p)
    except Exception:
        pass

    try:
        here = Path(__file__).resolve()
        candidates.append(here.parents[3] / p)
    except Exception:
        pass

    for c in candidates:
        try:
            if c.exists():
                return str(c)
        except Exception:
            pass

    return str(p)


def _app_root_dir() -> Path:
    candidates: list[Path] = []

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


def _saves_dir() -> Path:
    p = _app_root_dir() / "saves"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _normalize_filename(name: str) -> str:
    s = str(name or "").strip()
    s = re.sub(r"\.rqschem$", "", s, flags=re.IGNORECASE)
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", s)
    s = s.strip().strip(".")
    return s[:120].strip()


def _scheme_path_from_name(name: str) -> Path:
    clean = _normalize_filename(name)
    return _saves_dir() / f"{clean}.rqschem"


def _list_scheme_files() -> list[Path]:
    base = _saves_dir()
    files = []
    try:
        files = [p for p in base.glob("*.rqschem") if p.is_file()]
    except Exception:
        files = []

    def _sort_key(p: Path):
        try:
            return p.stat().st_mtime
        except Exception:
            return 0.0

    files.sort(key=_sort_key, reverse=True)
    return files


def _json_safe_clone(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            try:
                kk = str(k)
            except Exception:
                kk = "key"
            out[kk] = _json_safe_clone(v)
        return out

    if isinstance(value, (list, tuple, set)):
        return [_json_safe_clone(x) for x in value]

    if isinstance(value, bytes):
        return None

    try:
        return str(value)
    except Exception:
        return None


def _current_player_elixir_payload(main_window) -> Optional[dict]:
    fn = getattr(main_window, "_current_player_elixir_payload", None)
    if callable(fn):
        try:
            payload = fn()
            if isinstance(payload, dict):
                return deepcopy(payload)
        except Exception:
            pass

    payload = getattr(main_window, "_player_elixir_payload", None)
    if isinstance(payload, dict):
        return deepcopy(payload)

    return None


def _current_player_consumables_payloads(main_window) -> list[dict]:
    payloads = getattr(main_window, "_player_consumables_payloads", None)
    if isinstance(payloads, list):
        out: list[dict] = []
        for x in payloads:
            if isinstance(x, dict):
                out.append(deepcopy(x))
        return out
    return []


def _current_creature_constructor_state(main_window) -> dict:
    out = {
        "top_race_row": {},
        "top_element_row": {},
        "bottom_race_row": {},
        "bottom_element_row": {},
    }

    panel = getattr(main_window, "other_stats_panel", None)

    try:
        if panel is not None:
            if isinstance(getattr(panel, "_creature_selected_race", None), dict):
                out["top_race_row"] = deepcopy(panel._creature_selected_race)
            if isinstance(getattr(panel, "_creature_selected_element", None), dict):
                out["top_element_row"] = deepcopy(panel._creature_selected_element)
            if isinstance(getattr(panel, "_creature_selected_race2", None), dict):
                out["bottom_race_row"] = deepcopy(panel._creature_selected_race2)
            if isinstance(getattr(panel, "_creature_selected_element2", None), dict):
                out["bottom_element_row"] = deepcopy(panel._creature_selected_element2)
    except Exception:
        pass

    try:
        app = QApplication.instance()
        if app is not None:
            if not out["top_race_row"]:
                raw = app.property("rq_target_creature_top_race_row")
                if isinstance(raw, dict):
                    out["top_race_row"] = deepcopy(raw)

            if not out["top_element_row"]:
                raw = app.property("rq_target_creature_top_element_row")
                if isinstance(raw, dict):
                    out["top_element_row"] = deepcopy(raw)

            if not out["bottom_race_row"]:
                raw = app.property("rq_target_creature_bottom_race_row")
                if isinstance(raw, dict):
                    out["bottom_race_row"] = deepcopy(raw)

            if not out["bottom_element_row"]:
                raw = app.property("rq_target_creature_bottom_element_row")
                if isinstance(raw, dict):
                    out["bottom_element_row"] = deepcopy(raw)
    except Exception:
        pass

    return out


def _slot_kind_for_saved_item(slot_key: Optional[str]) -> str:
    sk = str(slot_key or "").strip().lower()
    return "weapon" if sk in {"weapon", "offhand", "spear"} else "equipment"


def _normalize_cards_payload(raw: Any) -> dict[int, dict]:
    out: dict[int, dict] = {}

    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, (list, tuple)):
        items = [(i + 1, raw[i]) for i in range(len(raw))]
    else:
        items = []

    for k, v in items:
        idx = _safe_int(k, 0)
        if idx <= 0 or not isinstance(v, dict):
            continue
        out[int(idx)] = deepcopy(v)

    return out


def _embed_cards_into_item_snapshot(main_window, item: dict, *, slot_key: Optional[str] = None) -> dict:
    snap = deepcopy(item) if isinstance(item, dict) else {}
    if not isinstance(snap, dict) or not snap:
        return {}

    cards_payload = _normalize_cards_payload(
        snap.get("_cards") or snap.get("cards") or snap.get("Cards")
    )

    cw = getattr(main_window, "cards_window", None)
    if not cards_payload and cw is not None and hasattr(cw, "get_cards_for_item"):
        try:
            real_slot_key = str(
                slot_key
                or snap.get("slot_key")
                or snap.get("SlotKey")
                or ""
            ).strip() or None

            cards_payload = _normalize_cards_payload(
                cw.get_cards_for_item(
                    snap,
                    kind=_slot_kind_for_saved_item(real_slot_key),
                    slot_key=real_slot_key,
                )
            )
        except Exception:
            cards_payload = {}

    if cards_payload:
        snap["_cards"] = deepcopy(cards_payload)
        snap["cards"] = deepcopy(cards_payload)
        snap["Cards"] = deepcopy(cards_payload)

    return snap


def _restore_cards_cache_from_saved_items(main_window, selected_items: dict, inventory_cells: list[dict]) -> None:
    cw = getattr(main_window, "cards_window", None)
    if cw is None:
        return

    try:
        if not isinstance(getattr(cw, "_per_item_cards", None), dict):
            cw._per_item_cards = {}
        if not isinstance(getattr(cw, "_per_item_pms", None), dict):
            cw._per_item_pms = {}

        cw._per_item_cards.clear()
        cw._per_item_pms.clear()
    except Exception:
        pass

    def _push_one(item: dict, slot_key: Optional[str]) -> None:
        if not isinstance(item, dict) or not item:
            return

        cards_payload = _normalize_cards_payload(
            item.get("_cards") or item.get("cards") or item.get("Cards")
        )
        if not cards_payload:
            return

        try:
            key_fn = getattr(cw, "_item_key_for", None)
            if not callable(key_fn):
                return

            real_slot_key = str(
                slot_key
                or item.get("slot_key")
                or item.get("SlotKey")
                or ""
            ).strip() or None

            item_key = key_fn(
                item,
                kind=_slot_kind_for_saved_item(real_slot_key),
                slot_key=real_slot_key,
            )
            if item_key is None:
                return

            cw._per_item_cards[item_key] = {int(i): deepcopy(c) for i, c in cards_payload.items()}

            pm_map: dict[int, QPixmap] = {}
            icon_loader = getattr(cw, "_try_load_card_icon", None)
            for idx, card in cards_payload.items():
                pm = None
                try:
                    if callable(icon_loader):
                        pm = icon_loader(card)
                except Exception:
                    pm = None

                if isinstance(pm, QPixmap) and not pm.isNull():
                    pm_map[int(idx)] = pm

            cw._per_item_pms[item_key] = dict(pm_map)
        except Exception:
            pass

    try:
        for slot_key, item in (selected_items or {}).items():
            _push_one(item, str(slot_key))
    except Exception:
        pass

    try:
        for row in (inventory_cells or []):
            if not isinstance(row, dict):
                continue
            item = row.get("item")
            slot_key = row.get("slot_key") or (item.get("slot_key") if isinstance(item, dict) else None)
            _push_one(item, str(slot_key or "") or None)
    except Exception:
        pass


def build_character_scheme(main_window) -> dict:
    class_id = 0
    try:
        fn = getattr(main_window, "_current_class_id", None)
        if callable(fn):
            class_id = _safe_int(fn(), 0)
    except Exception:
        class_id = 0

    class_name = ""
    try:
        combo = getattr(main_window, "class_combo", None)
        if combo is not None:
            class_name = str(combo.currentText() or "")
    except Exception:
        class_name = ""

    level = 1
    try:
        spin = getattr(main_window, "level_spin", None)
        if spin is not None:
            level = _safe_int(spin.value(), 1) or 1
    except Exception:
        level = 1

    gender = _safe_int(getattr(main_window, "_gender", 1), 1)

    event_id = _safe_int(getattr(main_window, "_current_event_id", 0), 0)
    event_name = str(getattr(main_window, "_current_event_name", "") or "")
    state_id = _safe_int(getattr(main_window, "_current_state_id", 0), 0)
    state_name = str(getattr(main_window, "_current_state_name", "") or "")

    lost_control_id = _safe_int(getattr(main_window, "_current_lost_control_id", 0), 0)
    lost_control_name = str(getattr(main_window, "_current_lost_control_name", "") or "")
    lost_control_image_id = _safe_int(getattr(main_window, "_current_lost_control_image_id", 0), 0)

    try:
        app = QApplication.instance()
        if app is not None:
            if lost_control_id <= 0:
                lost_control_id = _safe_int(app.property("player_lost_control_id"), 0)
            if not lost_control_name:
                lost_control_name = str(app.property("player_lost_control_name") or "")
            if lost_control_image_id <= 0:
                lost_control_image_id = _safe_int(app.property("player_lost_control_image_id"), 0)
    except Exception:
        pass

    menu_bonus_enabled = {}
    try:
        fn = getattr(main_window, "_get_menu_bonus_enabled_map", None)
        if callable(fn):
            menu_bonus_enabled = dict(fn() or {})
        else:
            menu_bonus_enabled = dict(getattr(main_window, "_menu_bonus_enabled", {}) or {})
    except Exception:
        menu_bonus_enabled = {}

    param_allocated = {}
    param_stack = []

    try:
        pp = getattr(main_window, "param_points", None)
        if pp is not None:
            param_allocated = {
                str(int(k)): int(v)
                for k, v in dict(getattr(pp, "allocated", {}) or {}).items()
                if int(v) != 0
            }
            param_stack = [int(x) for x in list(getattr(pp, "_stack", []) or [])]
    except Exception:
        param_allocated = {}
        param_stack = []

    # --- equipped items + embedded cards ---
    selected_items: dict[str, Any] = {}
    try:
        raw_selected = dict(getattr(main_window, "_selected_items", {}) or {})
    except Exception:
        raw_selected = {}

    for slot_key, item in raw_selected.items():
        if not isinstance(item, dict):
            continue
        try:
            snap = _embed_cards_into_item_snapshot(main_window, item, slot_key=str(slot_key))
            selected_items[str(slot_key)] = _json_safe_clone(snap)
        except Exception:
            try:
                selected_items[str(slot_key)] = _json_safe_clone(dict(item))
            except Exception:
                pass

    # --- inventory items with saved cells ---
    inventory_cells: list[dict] = []
    try:
        inv = getattr(main_window, "inventory_window", None)
        inv_items = getattr(inv, "_items", None) if inv is not None else None
        if isinstance(inv_items, dict):
            for (r, c), item in sorted(inv_items.items(), key=lambda kv: (kv[0][0], kv[0][1])):
                if not isinstance(item, dict) or not item:
                    continue

                snap = _embed_cards_into_item_snapshot(
                    main_window,
                    item,
                    slot_key=str(item.get("slot_key") or item.get("SlotKey") or "") or None,
                )

                inventory_cells.append(
                    {
                        "row": int(r),
                        "col": int(c),
                        "slot_key": str(item.get("slot_key") or item.get("SlotKey") or ""),
                        "item": _json_safe_clone(snap),
                    }
                )
    except Exception:
        inventory_cells = []

    # --- app/window states ---
    try:
        app = QApplication.instance()
    except Exception:
        app = None

    player_talents = []
    try:
        w = getattr(main_window, "_talents_menu_window", None)
        if w is not None and hasattr(w, "get_selected_talents"):
            player_talents = list(w.get_selected_talents() or [])
        elif app is not None and isinstance(app.property("player_talents"), list):
            player_talents = list(app.property("player_talents") or [])
    except Exception:
        player_talents = []

    player_guild_talents = []
    try:
        w = getattr(main_window, "_guild_menu_window", None)
        if w is not None and hasattr(w, "get_selected_talents"):
            player_guild_talents = list(w.get_selected_talents() or [])
        elif app is not None and isinstance(app.property("player_guild_talents"), list):
            player_guild_talents = list(app.property("player_guild_talents") or [])
    except Exception:
        player_guild_talents = []

    aura_state = {
        "personal_aura_id": 0,
        "general_aura_ids": [],
        "general_use_talents_map": {},
        "active_tab": "personal",
    }
    try:
        w = getattr(main_window, "_aura_menu_window", None)
        aw = getattr(w, "menu", w)

        if aw is not None and (
            hasattr(aw, "_selected_personal_aura_id")
            or hasattr(aw, "_selected_general_aura_ids")
            or hasattr(aw, "_general_use_talents_by_aura")
        ):
            try:
                current_tab_fn = getattr(aw, "current_tab", None)
                aura_tab = str(current_tab_fn() or "personal") if callable(current_tab_fn) else str(getattr(aw, "_active_tab", "personal") or "personal")
            except Exception:
                aura_tab = "personal"

            sel_ids_fn = getattr(aw, "selected_general_aura_ids", None)
            talents_map_fn = getattr(aw, "general_use_talents_map", None)

            aura_state = {
                "personal_aura_id": _safe_int(getattr(aw, "_selected_personal_aura_id", 0), 0),
                "general_aura_ids": list(sel_ids_fn() or []) if callable(sel_ids_fn) else [],
                "general_use_talents_map": dict(talents_map_fn() or {}) if callable(talents_map_fn) else {},
                "active_tab": str(aura_tab or "personal"),
            }
        elif app is not None:
            aura_state = {
                "personal_aura_id": _safe_int(app.property("player_personal_aura_id"), 0),
                "general_aura_ids": list(app.property("player_general_aura_ids") or []),
                "general_use_talents_map": dict(app.property("player_general_aura_use_talents_map") or {}),
                "active_tab": "personal",
            }
    except Exception:
        pass

    buff_state = {
        "buff_ids": [],
        "buff_stack_map": {},
        "combo_index_by_tab": {},
        "active_tab": "tab1",
    }
    try:
        w = getattr(main_window, "_buff_debuff_menu_window", None)
        bw = getattr(w, "menu", w)

        if bw is not None and hasattr(bw, "_combo_index_by_tab"):
            combo_map = getattr(bw, "_combo_index_by_tab", {}) or {}

            try:
                active_ids_fn = getattr(bw, "_current_active_buff_ids", None)
                active_ids = active_ids_fn() if callable(active_ids_fn) else set()
            except Exception:
                active_ids = set()

            try:
                current_tab_fn = getattr(bw, "current_tab", None)
                buff_tab = str(current_tab_fn() or "tab1") if callable(current_tab_fn) else str(getattr(bw, "_active_tab", "tab1") or "tab1")
            except Exception:
                buff_tab = "tab1"

            buff_state = {
                "buff_ids": sorted(
                    int(x) for x in (active_ids or set())
                    if _safe_int(x, 0) > 0
                ),
                "buff_stack_map": {
                    int(k): int(v)
                    for _tab, mp in combo_map.items()
                    if isinstance(mp, dict)
                    for k, v in mp.items()
                    if _safe_int(k, 0) > 0 and _safe_int(v, 0) > 0
                },
                "combo_index_by_tab": _json_safe_clone(combo_map),
                "active_tab": str(buff_tab or "tab1"),
            }
        elif app is not None:
            buff_state = {
                "buff_ids": list(app.property("player_buff_ids") or []),
                "buff_stack_map": dict(app.property("player_buff_stack_map") or {}),
                "combo_index_by_tab": {},
                "active_tab": "tab1",
            }
    except Exception:
        pass

    collection_state = {
        "in_col_ids": [],
        "selected_by_group": {},
        "active_tab": "costum",
    }
    try:
        w = getattr(main_window, "_collection_window", None)
        cm = getattr(w, "menu", w)

        if cm is not None and (
            hasattr(cm, "_in_col_set")
            or hasattr(cm, "_selected_by_group")
            or hasattr(cm, "_active_tab")
        ):
            try:
                current_tab_fn = getattr(cm, "current_tab", None)
                col_tab = str(current_tab_fn() or "costum") if callable(current_tab_fn) else str(getattr(cm, "_active_tab", "costum") or "costum")
            except Exception:
                col_tab = "costum"

            collection_state = {
                "in_col_ids": sorted(int(x) for x in (getattr(cm, "_in_col_set", set()) or set()) if _safe_int(x, 0) > 0),
                "selected_by_group": {
                    int(k): int(v)
                    for k, v in (getattr(cm, "_selected_by_group", {}) or {}).items()
                    if _safe_int(k, 0) > 0 and _safe_int(v, 0) > 0
                },
                "active_tab": str(col_tab or "costum"),
            }
        elif app is not None:
            collection_state = {
                "in_col_ids": list(app.property("collection_in_col_ids") or []),
                "selected_by_group": {},
                "active_tab": "costum",
            }
    except Exception:
        pass

    creature_constructor_state = _current_creature_constructor_state(main_window)

    payload = {
        "schema": "rqschem",
        "version": 2,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "character": {
            "class_id": int(class_id),
            "class_name": str(class_name),
            "level": int(level),
            "gender": int(gender),

            "event_id": int(event_id),
            "event_name": str(event_name),
            "state_id": int(state_id),
            "state_name": str(state_name),

            "lost_control_id": int(lost_control_id),
            "lost_control_name": str(lost_control_name),
            "lost_control_image_id": int(lost_control_image_id),

            "menu_bonus_enabled": _json_safe_clone(menu_bonus_enabled),

            "param_points": {
                "allocated": _json_safe_clone(param_allocated),
                "stack": _json_safe_clone(param_stack),
            },

            "selected_items": selected_items,
            "inventory_cells": _json_safe_clone(inventory_cells),

            "applied_stamps": _json_safe_clone(getattr(main_window, "_applied_stamps", {}) or {}),
            "applied_elixirs": _json_safe_clone(getattr(main_window, "_applied_elixirs", {}) or {}),

            "mask_stamp_slots": _json_safe_clone(sorted(list(getattr(main_window, "_mask_stamp_slots", set()) or []))),
            "suppress_stamp_equipped": _json_safe_clone(sorted(list(getattr(main_window, "_suppress_stamp_equipped", set()) or []))),

            "player_elixir_payload": _json_safe_clone(_current_player_elixir_payload(main_window)),
            "player_consumables_payloads": _json_safe_clone(_current_player_consumables_payloads(main_window)),

            "player_talents": _json_safe_clone(player_talents),
            "player_guild_talents": _json_safe_clone(player_guild_talents),
            "aura_state": _json_safe_clone(aura_state),
            "buff_state": _json_safe_clone(buff_state),
            "collection_state": _json_safe_clone(collection_state),

            "other_menu_open": bool(getattr(main_window, "_other_menu_open", False)),
            "creature_constructor_state": _json_safe_clone(creature_constructor_state),
        },
    }

    return payload


def _restore_loaded_costume_visual(main_window) -> None:
    """
    После загрузки схемы восстанавливает внешний вид персонажа от надетого костюма.

    В обычном выборе костюма это делает MainWindow._on_pick_equipment(),
    но apply_character_scheme() кладёт _selected_items напрямую, поэтому
    _sil_original нужно восстановить отдельно.
    """
    try:
        selected = getattr(main_window, "_selected_items", None)
        if not isinstance(selected, dict):
            selected = {}
            main_window._selected_items = selected
    except Exception:
        selected = {}

    item = selected.get("costume")

    # Если костюм не надет — вернуть обычный силуэт по полу.
    if not isinstance(item, dict) or not item:
        try:
            gender = _safe_int(getattr(main_window, "_gender", 1), 1)
            main_window._sil_original = (
                getattr(main_window, "_sil_pm_m", None)
                if gender == 1
                else getattr(main_window, "_sil_pm_f", None)
            )
        except Exception:
            pass
        return

    item = dict(item)

    eid = 0
    for key in ("Id", "Equipment_Id", "Equip_Id", "TemplateId", "Template_Id", "Item_Id"):
        eid = _safe_int(item.get(key), 0)
        if eid > 0:
            break

    db_icon_id = 0
    db_silhouette_id = 0

    # В БД:
    #   Equipment.Image_Id        = иконка слота
    #   Equipment.CostumeImage_Id = внешний вид персонажа
    try:
        conn = getattr(getattr(main_window, "data", None), "conn", None)
        if conn is not None and eid > 0:
            row = conn.execute(
                "SELECT Image_Id, CostumeImage_Id FROM Equipment WHERE Id=? LIMIT 1",
                (int(eid),),
            ).fetchone()

            if row:
                if hasattr(row, "keys"):
                    db_icon_id = _safe_int(row["Image_Id"], 0)
                    db_silhouette_id = _safe_int(row["CostumeImage_Id"], 0)
                else:
                    db_icon_id = _safe_int(row[0], 0)
                    db_silhouette_id = _safe_int(row[1], 0)
    except Exception:
        db_icon_id = 0
        db_silhouette_id = 0

    # Нормализуем сохранённый костюм под формат, который ждёт MainWindow:
    #   Image_Id        = силуэт персонажа
    #   Icon_Image_Id   = иконка слота
    #   CostumeImage_Id = иконка слота, потому что _update_slot_icon("costume")
    #                     сейчас берёт именно CostumeImage_Id.
    if db_silhouette_id > 0:
        item["Image_Id"] = int(db_silhouette_id)

    if db_icon_id > 0:
        item["Icon_Image_Id"] = int(db_icon_id)
        item["CostumeImage_Id"] = int(db_icon_id)

    item["Type_Id"] = _safe_int(item.get("Type_Id"), 14) or 14
    item["TypeName"] = str(item.get("TypeName") or "Костюм")

    selected["costume"] = item
    main_window._selected_items = selected

    try:
        costume_ctrl = getattr(main_window, "costume_ctrl", None)
        if costume_ctrl is not None:
            costume_ctrl._current_costume_id = int(eid) if eid > 0 else _safe_int(item.get("Id"), 0)
    except Exception:
        pass

    sil_id = 0

    # Новый/нормализованный формат: Image_Id = силуэт.
    sil_id = _safe_int(item.get("Image_Id"), 0)

    # Фолбэк из БД.
    if sil_id <= 0:
        sil_id = _safe_int(db_silhouette_id, 0)

    # Фолбэк для старых/кривых сохранений.
    # Если Icon_Image_Id есть, то Image_Id почти наверняка был силуэтом.
    # Если Icon_Image_Id нет, пробуем CostumeImage_Id.
    if sil_id <= 0:
        if item.get("Icon_Image_Id") is None:
            sil_id = _safe_int(item.get("CostumeImage_Id"), 0)

    pm = None
    try:
        get_pm = getattr(main_window, "_get_image_pm", None)
        if callable(get_pm) and sil_id > 0:
            pm = get_pm(int(sil_id))
    except Exception:
        pm = None

    try:
        if pm is not None:
            main_window._sil_original = pm
        else:
            gender = _safe_int(getattr(main_window, "_gender", 1), 1)
            main_window._sil_original = (
                getattr(main_window, "_sil_pm_m", None)
                if gender == 1
                else getattr(main_window, "_sil_pm_f", None)
            )
    except Exception:
        pass


def apply_character_scheme(main_window, raw: dict) -> bool:
    if not isinstance(raw, dict):
        return False

    if str(raw.get("schema") or "") != "rqschem":
        return False

    character = raw.get("character")
    if not isinstance(character, dict):
        return False

    class_id = _safe_int(character.get("class_id"), 0)
    class_name = str(character.get("class_name") or "")
    level = max(1, _safe_int(character.get("level"), 1))
    gender = _safe_int(character.get("gender"), 1)

    event_id = _safe_int(character.get("event_id"), 0)
    event_name = str(character.get("event_name") or "")
    state_id = _safe_int(character.get("state_id"), 0)
    state_name = str(character.get("state_name") or "")

    lost_control_id = _safe_int(character.get("lost_control_id"), 0)
    lost_control_name = str(character.get("lost_control_name") or "")
    lost_control_image_id = _safe_int(character.get("lost_control_image_id"), 0)

    menu_bonus_enabled = character.get("menu_bonus_enabled")
    if not isinstance(menu_bonus_enabled, dict):
        menu_bonus_enabled = {}

    param_points = character.get("param_points")
    if not isinstance(param_points, dict):
        param_points = {}

    selected_items = character.get("selected_items")
    if not isinstance(selected_items, dict):
        selected_items = {}

    inventory_cells = character.get("inventory_cells")
    if not isinstance(inventory_cells, list):
        inventory_cells = []

    applied_stamps = character.get("applied_stamps")
    if not isinstance(applied_stamps, dict):
        applied_stamps = {}

    applied_elixirs = character.get("applied_elixirs")
    if not isinstance(applied_elixirs, dict):
        applied_elixirs = {}

    mask_stamp_slots = character.get("mask_stamp_slots")
    if not isinstance(mask_stamp_slots, list):
        mask_stamp_slots = []

    suppress_stamp_equipped = character.get("suppress_stamp_equipped")
    if not isinstance(suppress_stamp_equipped, list):
        suppress_stamp_equipped = []

    player_elixir_payload = character.get("player_elixir_payload")
    if not isinstance(player_elixir_payload, dict):
        player_elixir_payload = None

    player_consumables_payloads = character.get("player_consumables_payloads")
    if not isinstance(player_consumables_payloads, list):
        player_consumables_payloads = []

    player_talents = character.get("player_talents")
    if not isinstance(player_talents, list):
        player_talents = []

    player_guild_talents = character.get("player_guild_talents")
    if not isinstance(player_guild_talents, list):
        player_guild_talents = []

    aura_state = character.get("aura_state")
    if not isinstance(aura_state, dict):
        aura_state = {}

    buff_state = character.get("buff_state")
    if not isinstance(buff_state, dict):
        buff_state = {}

    collection_state = character.get("collection_state")
    if not isinstance(collection_state, dict):
        collection_state = {}

    creature_constructor_state = character.get("creature_constructor_state")
    if not isinstance(creature_constructor_state, dict):
        creature_constructor_state = {}

    top_race_row = creature_constructor_state.get("top_race_row")
    if not isinstance(top_race_row, dict):
        top_race_row = {}

    top_element_row = creature_constructor_state.get("top_element_row")
    if not isinstance(top_element_row, dict):
        top_element_row = {}

    bottom_race_row = creature_constructor_state.get("bottom_race_row")
    if not isinstance(bottom_race_row, dict):
        bottom_race_row = {}

    bottom_element_row = creature_constructor_state.get("bottom_element_row")
    if not isinstance(bottom_element_row, dict):
        bottom_element_row = {}

    other_menu_open = bool(character.get("other_menu_open", False))

    combo = getattr(main_window, "class_combo", None)
    if combo is not None:
        set_ok = False

        if class_id > 0:
            for i in range(combo.count()):
                try:
                    if _safe_int(combo.itemData(i), 0) == int(class_id):
                        combo.setCurrentIndex(i)
                        set_ok = True
                        break
                except Exception:
                    continue

        if (not set_ok) and class_name:
            for i in range(combo.count()):
                try:
                    if str(combo.itemText(i) or "").strip() == class_name:
                        combo.setCurrentIndex(i)
                        set_ok = True
                        break
                except Exception:
                    continue

    try:
        fn = getattr(main_window, "_set_gender", None)
        if callable(fn):
            fn(int(gender))
        else:
            setattr(main_window, "_gender", int(gender))
    except Exception:
        pass

    try:
        spin = getattr(main_window, "level_spin", None)
        if spin is not None:
            spin.setValue(int(level))
    except Exception:
        pass

    try:
        fn = getattr(main_window, "_set_current_event", None)
        if callable(fn):
            # Восстанавливаем состояние передвижения.
            fn(int(state_id), str(state_name), kind="state")

            # Восстанавливаем ивент.
            fn(int(event_id), str(event_name), kind="event")

            # Восстанавливаем статус контроля.
            # ВАЖНО: это нужно не только для математики, но и для визуального текста/иконки.
            fn(
                int(lost_control_id),
                str(lost_control_name),
                kind="control",
                image_id=int(lost_control_image_id),
            )
        else:
            setattr(main_window, "_current_state_id", int(state_id))
            setattr(main_window, "_current_state_name", str(state_name))

            setattr(main_window, "_current_event_id", int(event_id))
            setattr(main_window, "_current_event_name", str(event_name))

            setattr(main_window, "_current_lost_control_id", int(lost_control_id))
            setattr(main_window, "_current_lost_control_name", str(lost_control_name))
            setattr(main_window, "_current_lost_control_image_id", int(lost_control_image_id))
    except Exception:
        pass

    try:
        setattr(main_window, "_menu_bonus_enabled", dict(menu_bonus_enabled))
    except Exception:
        pass

    try:
        toggles = getattr(main_window, "_menu_bonus_toggles", None)
        if isinstance(toggles, dict):
            for tog in toggles.values():
                try:
                    sync_fn = getattr(tog, "sync", None)
                    if callable(sync_fn):
                        sync_fn()
                except Exception:
                    pass
    except Exception:
        pass

    pp = getattr(main_window, "param_points", None)
    if pp is not None:
        try:
            set_level_fn = getattr(pp, "set_level", None)
            if callable(set_level_fn):
                set_level_fn(int(level))
        except Exception:
            pass

        try:
            reset_fn = getattr(pp, "reset_all", None)
            if callable(reset_fn):
                reset_fn()
        except Exception:
            pass

        allocated_raw = param_points.get("allocated")
        stack_raw = param_points.get("stack")

        allocated: dict[int, int] = {}
        if isinstance(allocated_raw, dict):
            for k, v in allocated_raw.items():
                sid = _safe_int(k, 0)
                val = _safe_int(v, 0)
                if sid > 0 and val > 0:
                    allocated[int(sid)] = int(val)

        stack: list[int] = []
        if isinstance(stack_raw, list):
            for x in stack_raw:
                sid = _safe_int(x, 0)
                if sid > 0:
                    stack.append(int(sid))

        if not stack and allocated:
            for sid, amt in allocated.items():
                stack.extend([int(sid)] * int(amt))

        try:
            pp.allocated = dict(allocated)
            pp._stack = list(stack)
        except Exception:
            pass

        try:
            emit_sig = getattr(pp, "unspentChanged", None)
            unspent_fn = getattr(pp, "unspent_points", None)
            if emit_sig is not None and callable(unspent_fn):
                emit_sig.emit(unspent_fn())
        except Exception:
            pass

    try:
        main_window._selected_items = deepcopy(selected_items)
    except Exception:
        main_window._selected_items = dict(selected_items)

    try:
        _restore_loaded_costume_visual(main_window)
    except Exception:
        pass

    try:
        main_window._applied_stamps = deepcopy(applied_stamps)
    except Exception:
        main_window._applied_stamps = dict(applied_stamps)

    try:
        main_window._applied_elixirs = deepcopy(applied_elixirs)
    except Exception:
        main_window._applied_elixirs = dict(applied_elixirs)

    try:
        main_window._mask_stamp_slots = {str(x) for x in mask_stamp_slots}
    except Exception:
        main_window._mask_stamp_slots = set()

    try:
        main_window._suppress_stamp_equipped = {_safe_int(x, 0) for x in suppress_stamp_equipped if _safe_int(x, 0) > 0}
    except Exception:
        main_window._suppress_stamp_equipped = set()

    try:
        main_window._player_elixir_payload = deepcopy(player_elixir_payload) if isinstance(player_elixir_payload, dict) else None
    except Exception:
        main_window._player_elixir_payload = None

    try:
        payloads = []
        for x in player_consumables_payloads:
            if isinstance(x, dict):
                payloads.append(deepcopy(x))
        main_window._player_consumables_payloads = payloads
    except Exception:
        main_window._player_consumables_payloads = []

    aura_personal_id = _safe_int(aura_state.get("personal_aura_id"), 0)
    aura_general_ids = [
        int(x) for x in list(aura_state.get("general_aura_ids") or [])
        if _safe_int(x, 0) > 0
    ]
    aura_map = {
        int(k): bool(v)
        for k, v in dict(aura_state.get("general_use_talents_map") or {}).items()
        if _safe_int(k, 0) > 0
    }
    aura_active_tab = str(aura_state.get("active_tab") or "personal")

    buff_ids = [
        int(x) for x in list(buff_state.get("buff_ids") or [])
        if _safe_int(x, 0) > 0
    ]
    buff_stack_map = {
        int(k): int(v)
        for k, v in dict(buff_state.get("buff_stack_map") or {}).items()
        if _safe_int(k, 0) > 0 and _safe_int(v, 0) > 0
    }
    buff_combo_index_by_tab = {
        str(tab): {
            int(k): int(v)
            for k, v in dict(mp or {}).items()
            if _safe_int(k, 0) > 0 and _safe_int(v, 0) >= 0
        }
        for tab, mp in dict(buff_state.get("combo_index_by_tab") or {}).items()
        if isinstance(mp, dict)
    }
    buff_active_tab = str(buff_state.get("active_tab") or "tab1")

    collection_in_col_ids = [
        int(x) for x in list(collection_state.get("in_col_ids") or [])
        if _safe_int(x, 0) > 0
    ]
    collection_selected_by_group = {
        int(k): int(v)
        for k, v in dict(collection_state.get("selected_by_group") or {}).items()
        if _safe_int(k, 0) > 0 and _safe_int(v, 0) > 0
    }
    collection_active_tab = str(collection_state.get("active_tab") or "costum")

    try:
        app = QApplication.instance()
        if app is not None:
            if isinstance(main_window._player_elixir_payload, dict):
                app.setProperty("player_elixir_payload", deepcopy(main_window._player_elixir_payload))
                app.setProperty("player_elixir_id", _safe_int(main_window._player_elixir_payload.get("Id"), 0))
            else:
                app.setProperty("player_elixir_payload", None)
                app.setProperty("player_elixir_id", 0)

            cons_payloads = list(getattr(main_window, "_player_consumables_payloads", []) or [])
            cons_ids = [_safe_int(p.get("Id"), 0) for p in cons_payloads if isinstance(p, dict)]
            cons_ids = [int(x) for x in cons_ids if x > 0]

            app.setProperty("player_consumables_payloads", deepcopy(cons_payloads))
            app.setProperty("player_consumable_ids", cons_ids)

            app.setProperty("player_talents", deepcopy(list(player_talents)))
            app.setProperty("player_guild_talents", deepcopy(list(player_guild_talents)))

            app.setProperty("player_personal_aura_id", int(aura_personal_id))
            app.setProperty("player_general_aura_ids", list(aura_general_ids))
            app.setProperty("player_general_aura_use_talents_map", dict(aura_map))
            app.setProperty("player_general_aura_id", aura_general_ids[0] if aura_general_ids else 0)
            app.setProperty("player_general_aura_use_talents", bool(any(bool(aura_map.get(int(aid), False)) for aid in aura_general_ids)))

            app.setProperty("player_buff_ids", list(buff_ids))
            app.setProperty("player_buff_stack_map", dict(buff_stack_map))

            app.setProperty("player_lost_control_id", int(lost_control_id))
            app.setProperty("player_lost_control_name", str(lost_control_name))
            app.setProperty("player_lost_control_image_id", int(lost_control_image_id))

            # На случай если label уже был переложен/переотрисован после первого вызова.
            try:
                fn = getattr(main_window, "_set_current_event", None)
                if callable(fn):
                    fn(
                        int(lost_control_id),
                        str(lost_control_name),
                        kind="control",
                        image_id=int(lost_control_image_id),
                    )
                else:
                    update_lbl = getattr(main_window, "_update_event_label_text", None)
                    if callable(update_lbl):
                        update_lbl(kind="control")
            except Exception:
                pass

            app.setProperty("collection_in_col_ids", list(collection_in_col_ids))

            app.setProperty("rq_target_creature_top_race_row", dict(top_race_row or {}))
            app.setProperty("rq_target_creature_top_element_row", dict(top_element_row or {}))
            app.setProperty("rq_target_creature_bottom_race_row", dict(bottom_race_row or {}))
            app.setProperty("rq_target_creature_bottom_element_row", dict(bottom_element_row or {}))
        else:
            app = None
    except Exception:
        app = None

    try:
        fn = getattr(main_window, "_set_other_menu_open", None)
        if callable(fn):
            fn(bool(other_menu_open))
        else:
            setattr(main_window, "_other_menu_open", bool(other_menu_open))
    except Exception:
        pass

    try:
        other_panel = getattr(main_window, "other_stats_panel", None)
        if other_panel is not None:
            other_panel._creature_selected_race = dict(top_race_row or {}) if isinstance(top_race_row,
                                                                                         dict) and top_race_row else None
            other_panel._creature_selected_element = dict(top_element_row or {}) if isinstance(top_element_row,
                                                                                               dict) and top_element_row else None
            other_panel._creature_selected_race2 = dict(bottom_race_row or {}) if isinstance(bottom_race_row,
                                                                                             dict) and bottom_race_row else None
            other_panel._creature_selected_element2 = dict(bottom_element_row or {}) if isinstance(bottom_element_row,
                                                                                                   dict) and bottom_element_row else None

            try:
                other_panel._close_creature_popups(refresh=False)
            except Exception:
                try:
                    other_panel._close_creature_popups()
                except Exception:
                    pass

            try:
                if getattr(other_panel, "math", None) is not None:
                    other_panel.math._shared_target_race_row = dict(top_race_row or {})
                    other_panel.math._shared_target_element_row = dict(top_element_row or {})
            except Exception:
                pass

            try:
                other_panel._refresh_creature_constructor_ui()
            except Exception:
                pass
    except Exception:
        pass

    try:
        ensure_inv = getattr(main_window, "_ensure_inventory_window", None)
        if callable(ensure_inv):
            ensure_inv()

        inv = getattr(main_window, "inventory_window", None)
        if inv is not None:
            try:
                current_items = dict(getattr(inv, "_items", {}) or {})
            except Exception:
                current_items = {}

            for rc in list(current_items.keys()):
                try:
                    inv._inv_clear_icon_at(rc, "load_scheme")
                except Exception:
                    try:
                        icon = (getattr(inv, "_cell_icons", {}) or {}).get(rc)
                        if icon is not None:
                            icon.clear()
                            icon.hide()
                    except Exception:
                        pass

            try:
                inv._items.clear()
            except Exception:
                inv._items = {}

            for row in sorted(
                [x for x in inventory_cells if isinstance(x, dict)],
                key=lambda d: (_safe_int(d.get("row"), 9999), _safe_int(d.get("col"), 9999))
            ):
                r = _safe_int(row.get("row"), -1)
                c = _safe_int(row.get("col"), -1)
                item = row.get("item")

                if r < 0 or c < 0 or not isinstance(item, dict) or not item:
                    continue

                try:
                    place_fn = getattr(inv, "_place_item_into_cell", None)
                    if callable(place_fn):
                        place_fn((int(r), int(c)), deepcopy(item))
                    else:
                        inv.add_item(deepcopy(item))
                except Exception:
                    try:
                        inv.add_item(deepcopy(item))
                    except Exception:
                        pass

            try:
                inv._update_capacity_message()
            except Exception:
                pass
            try:
                inv._update_capacity_indicator()
            except Exception:
                pass
            try:
                inv.update()
            except Exception:
                pass
    except Exception:
        pass

    try:
        _restore_cards_cache_from_saved_items(main_window, dict(selected_items), list(inventory_cells))
    except Exception:
        pass

    try:
        ensure_tal = getattr(main_window, "_ensure_talents_menu_window", None)
        if callable(ensure_tal):
            tw = ensure_tal()

            state: dict[int, dict[int, int]] = {}
            for row in list(player_talents or []):
                if not isinstance(row, dict):
                    continue
                bid = _safe_int(row.get("Branch_Id"), 0)
                tid = _safe_int(row.get("Talent_Id"), 0)
                hidx = _safe_int(row.get("HIndex"), -1)
                if bid <= 0 or tid <= 0 or hidx < 0:
                    continue
                state.setdefault(int(bid), {})[int(hidx)] = int(tid)

            tw._selected_talents_by_branch = deepcopy(state)

            try:
                tw._prune_selected_talents()
            except Exception:
                pass
            try:
                tw._enforce_talent_points_limit()
            except Exception:
                pass
            try:
                tw._publish_selected_talents()
            except Exception:
                pass
            try:
                tw.update()
            except Exception:
                pass
    except Exception:
        pass

    try:
        ensure_guild = getattr(main_window, "_ensure_guild_menu_window", None)
        if callable(ensure_guild):
            gw = ensure_guild()

            branch_state: dict[int, dict[str, int]] = {}
            for row in list(player_guild_talents or []):
                if not isinstance(row, dict):
                    continue
                bid = _safe_int(row.get("Branch_Id"), 0)
                tid = _safe_int(row.get("Talent_Id"), 0)
                pts = _safe_int(row.get("Points"), 0)
                if bid <= 0 or tid <= 0 or pts <= 0:
                    continue
                branch_state[int(bid)] = {
                    "Talent_Id": int(tid),
                    "Points": int(pts),
                }

            gw._branch_state = deepcopy(branch_state)

            try:
                gw.reload_from_db()
            except Exception:
                pass
            try:
                gw._publish_selected_talents()
            except Exception:
                pass
            try:
                gw.update()
            except Exception:
                pass
    except Exception:
        pass

    # ---------- sync aura window/menu ----------
    try:
        aura_win = getattr(main_window, "_aura_menu_window", None)
        if aura_win is None:
            try:
                from .aura_menu import AuraMenuWindow
            except Exception:
                try:
                    from aura_menu import AuraMenuWindow
                except Exception:
                    AuraMenuWindow = None

            if AuraMenuWindow is not None:
                try:
                    aura_win = AuraMenuWindow(main_window)
                    main_window._aura_menu_window = aura_win
                    try:
                        aura_win.closed.connect(main_window._on_aura_menu_closed, Qt.ConnectionType.UniqueConnection)
                    except Exception:
                        try:
                            aura_win.closed.connect(main_window._on_aura_menu_closed)
                        except Exception:
                            pass
                except Exception:
                    aura_win = None

        aw = getattr(aura_win, "menu", aura_win)
        if aw is not None:
            try:
                set_ctx = getattr(aw, "set_player_context", None)
                if callable(set_ctx):
                    set_ctx(int(class_id), int(level))
            except Exception:
                pass

            aw._selected_personal_aura_id = int(aura_personal_id)
            aw._selected_general_aura_ids = set(int(x) for x in aura_general_ids if _safe_int(x, 0) > 0)
            aw._general_use_talents_by_aura = {
                int(k): bool(v)
                for k, v in aura_map.items()
                if _safe_int(k, 0) > 0
            }

            try:
                set_tab_fn = getattr(aw, "set_tab", None)
                if callable(set_tab_fn):
                    set_tab_fn(str(aura_active_tab or "personal"))
                else:
                    aw._rebuild_visible_tab()
            except Exception:
                try:
                    aw._rebuild_visible_tab()
                except Exception:
                    pass

            try:
                aw._publish_selection_state()
            except Exception:
                pass
            try:
                aw.update()
            except Exception:
                pass
    except Exception:
        pass

    # ---------- sync buff/debuff window/menu ----------
    try:
        ensure_buff = getattr(main_window, "_ensure_buff_debuff_menu_window", None)
        if callable(ensure_buff):
            buff_win = ensure_buff()
        else:
            buff_win = getattr(main_window, "_buff_debuff_menu_window", None)

        bw = getattr(buff_win, "menu", buff_win)
        if bw is not None:
            try:
                set_class_fn = getattr(buff_win, "set_class_id", None)
                if callable(set_class_fn):
                    set_class_fn(int(class_id))
                else:
                    inner_set_class_fn = getattr(bw, "set_class_id", None)
                    if callable(inner_set_class_fn):
                        inner_set_class_fn(int(class_id))
            except Exception:
                pass

            try:
                set_level_fn = getattr(buff_win, "set_level", None)
                if callable(set_level_fn):
                    set_level_fn(int(level))
                else:
                    inner_set_level_fn = getattr(bw, "set_level", None)
                    if callable(inner_set_level_fn):
                        inner_set_level_fn(int(level))
            except Exception:
                pass

            combo_map = deepcopy(buff_combo_index_by_tab)
            if not isinstance(combo_map, dict):
                combo_map = {}
            bw._combo_index_by_tab = combo_map

            try:
                set_tab_fn = getattr(bw, "set_tab", None)
                if callable(set_tab_fn):
                    set_tab_fn(str(buff_active_tab or "tab1"))
                else:
                    bw._rebuild_visible_tab()
            except Exception:
                try:
                    bw._rebuild_visible_tab()
                except Exception:
                    pass

            try:
                bw._publish_selected_buffs(refresh_stats=False)
            except Exception:
                pass
            try:
                bw.update()
            except Exception:
                pass
    except Exception:
        pass

    # ---------- sync collection window/menu ----------
    try:
        collection_win = getattr(main_window, "_collection_window", None)
        if collection_win is None:
            try:
                from .collection import CollectionWindow
            except Exception:
                try:
                    from collection import CollectionWindow
                except Exception:
                    CollectionWindow = None

            if CollectionWindow is not None:
                try:
                    collection_win = CollectionWindow(main_window)
                    main_window._collection_window = collection_win
                    try:
                        collection_win.closed.connect(main_window._on_collection_closed, Qt.ConnectionType.UniqueConnection)
                    except Exception:
                        try:
                            collection_win.closed.connect(main_window._on_collection_closed)
                        except Exception:
                            pass
                except Exception:
                    collection_win = None

        cm = getattr(collection_win, "menu", collection_win)
        if cm is not None:
            cm._in_col_set = set(int(x) for x in collection_in_col_ids if _safe_int(x, 0) > 0)
            cm._selected_by_group = {
                int(k): int(v)
                for k, v in collection_selected_by_group.items()
                if _safe_int(k, 0) > 0 and _safe_int(v, 0) > 0
            }

            try:
                set_tab_fn = getattr(cm, "set_tab", None)
                if callable(set_tab_fn):
                    set_tab_fn(str(collection_active_tab or "costum"))
            except Exception:
                pass

            try:
                for cid in list((getattr(cm, "_tile_toggle_by_id", {}) or {}).keys()):
                    cm._apply_toggle_icon(int(cid))
            except Exception:
                pass

            try:
                group_ids = set(int(g) for g in (getattr(cm, "_tile_bg_by_group", {}) or {}).keys())
                group_ids.update(int(g) for g in (cm._selected_by_group or {}).keys())
                for gid in sorted(group_ids):
                    cm._refresh_group_bgs(int(gid))
            except Exception:
                pass

            try:
                cm.update()
            except Exception:
                pass
    except Exception:
        pass

    try:
        slot_icons = getattr(main_window, "_slot_icons", {}) or {}
        slot_keys = set(slot_icons.keys()) | set((getattr(main_window, "_selected_items", {}) or {}).keys())
        update_slot_icon = getattr(main_window, "_update_slot_icon", None)
        if callable(update_slot_icon):
            for slot_key in slot_keys:
                try:
                    update_slot_icon(str(slot_key))
                except Exception:
                    pass
    except Exception:
        pass

    try:
        fn = getattr(main_window, "_sync_player_elixir_button_icon", None)
        if callable(fn):
            fn()
    except Exception:
        pass

    try:
        fn = getattr(main_window, "_sync_inventory_context", None)
        if callable(fn):
            fn()
    except Exception:
        pass

    try:
        fn = getattr(main_window, "_place_menu_bonus_toggles", None)
        if callable(fn):
            fn()
    except Exception:
        pass

    try:
        fn = getattr(main_window, "_set_current_event", None)
        if callable(fn):
            fn(
                int(lost_control_id),
                str(lost_control_name),
                kind="control",
                image_id=int(lost_control_image_id),
            )

        layout_fn = getattr(main_window, "_layout_event_selector_ui", None)
        if callable(layout_fn):
            layout_fn()

        update_fn = getattr(main_window, "_update_event_label_text", None)
        if callable(update_fn):
            update_fn(kind="control")
    except Exception:
        pass

    try:
        fn = getattr(main_window, "_update_offhand_overlay", None)
        if callable(fn):
            try:
                fn(refresh_icon=False)
            except TypeError:
                fn()
    except Exception:
        pass

    try:
        fn = getattr(main_window, "_sync_buff_debuff_menu_context", None)
        if callable(fn):
            fn()
    except Exception:
        pass

    try:
        fn = getattr(main_window, "_sync_talents_menu_class_context", None)
        if callable(fn):
            fn()
    except Exception:
        pass

    try:
        fn = getattr(main_window, "refresh_stats_panel", None)
        if callable(fn):
            fn()
    except Exception:
        pass

    try:
        main_window.update()
    except Exception:
        pass

    return True


# =========================
# UI
# =========================
class _InputShield(QWidget):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("SaveLoadManagerShield")
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

        self._active_pm = QPixmap(_resolve_resource(active_rel_path))

    def apply_scale(self, scale: float) -> None:
        s = max(0.1, float(scale or 1.0))

        hit_x = float(self._hit_x) * s
        hit_y = float(self._hit_y) * s
        hit_w = max(1, int(round(float(self._hit_w) * s)))
        hit_h = max(1, int(round(float(self._hit_h) * s)))

        vis_w = max(1, int(round(float(self._visual_w) * s)))
        vis_h = max(1, int(round(float(self._visual_h) * s)))

        hit_cx = hit_x + (hit_w / 2.0)
        hit_cy = hit_y + (hit_h / 2.0)

        x = int(round(hit_cx - (vis_w / 2.0)))
        y = int(round(hit_cy - (vis_h / 2.0)))

        local_hit_x = int(round((vis_w - hit_w) / 2.0))
        local_hit_y = int(round((vis_h - hit_h) / 2.0))

        self.setGeometry(x, y, vis_w, vis_h)
        self._hit_rect_local = QRect(local_hit_x, local_hit_y, hit_w, hit_h)

        self._active_label.setGeometry(0, 0, vis_w, vis_h)

        if not self._active_pm.isNull():
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


class _MiniVScroll(QWidget):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent;")
        self._bar = None
        self._dragging = False
        self._drag_offset = 0

    def bind_bar(self, bar) -> None:
        self._bar = bar

        if self._bar is None:
            self.hide()
            return

        try:
            self._bar.valueChanged.connect(self._sync_from_bar, Qt.ConnectionType.UniqueConnection)
        except Exception:
            try:
                self._bar.valueChanged.connect(self._sync_from_bar)
            except Exception:
                pass

        try:
            self._bar.rangeChanged.connect(self._sync_from_bar, Qt.ConnectionType.UniqueConnection)
        except Exception:
            try:
                self._bar.rangeChanged.connect(self._sync_from_bar)
            except Exception:
                pass

        self._sync_from_bar()

    def _sync_from_bar(self, *_args) -> None:
        bar = self._bar
        if bar is None:
            self.hide()
            return

        try:
            visible = bar.maximum() > 0
        except Exception:
            visible = False

        self.setVisible(bool(visible))
        self.update()

    def _thumb_rect(self) -> QRect:
        bar = self._bar
        if bar is None:
            return QRect()

        w = self.width()
        h = self.height()

        try:
            maximum = max(0, int(bar.maximum()))
            page = max(1, int(bar.pageStep()))
            value = max(0, int(bar.value()))
        except Exception:
            return QRect()

        total = maximum + page
        if total <= 0 or maximum <= 0 or h <= 0:
            return QRect(3, 0, max(8, w - 6), h)

        thumb_h = max(28, int(round(h * (page / total))))
        track_h = max(1, h - thumb_h)
        y = int(round((value / maximum) * track_h)) if maximum > 0 else 0

        return QRect(3, y, max(8, w - 6), thumb_h)

    def _set_value_from_y(self, y: int) -> None:
        bar = self._bar
        if bar is None:
            return

        thumb = self._thumb_rect()
        track_h = max(1, self.height() - thumb.height())

        ny = max(0, min(int(y), track_h))

        try:
            maximum = max(0, int(bar.maximum()))
        except Exception:
            maximum = 0

        if maximum <= 0:
            bar.setValue(0)
            return

        value = int(round((ny / track_h) * maximum)) if track_h > 0 else 0
        bar.setValue(value)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        track = self.rect().adjusted(6, 0, -6, 0)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 20, 20, 160))
        p.drawRoundedRect(track, 4, 4)

        thumb = self._thumb_rect()
        if not thumb.isNull():
            p.setBrush(QColor(210, 180, 95, 230))
            p.drawRoundedRect(thumb, 4, 4)
            p.setPen(QPen(QColor(80, 50, 20, 220), 1))
            p.drawRoundedRect(thumb, 4, 4)

        p.end()

    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)

        thumb = self._thumb_rect()
        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()

        if thumb.contains(pos):
            self._dragging = True
            self._drag_offset = pos.y() - thumb.y()
        else:
            self._set_value_from_y(pos.y() - thumb.height() // 2)

        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        if not self._dragging:
            return super().mouseMoveEvent(ev)

        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
        self._set_value_from_y(pos.y() - self._drag_offset)
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._dragging = False
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev) -> None:
        bar = self._bar
        if bar is None:
            return super().wheelEvent(ev)

        delta = 0
        try:
            delta = ev.angleDelta().y()
        except Exception:
            delta = 0

        step = max(20, int(bar.singleStep() or 20))
        if delta < 0:
            bar.setValue(bar.value() + step)
        elif delta > 0:
            bar.setValue(bar.value() - step)

        ev.accept()


class _SchemeRow(QFrame):
    clicked = Signal(str)

    def __init__(
            self,
            filename_stem: str,
            display_name: str,
            modified_text: str,
            type_text: str,
            size_text: str,
            parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._stem = str(filename_stem or "")
        self._display_name = str(display_name or "")
        self._modified_text = str(modified_text or "")
        self._type_text = str(type_text or "")
        self._size_text = str(size_text or "")

        self._hover = False
        self._pressed = False
        self._selected = False

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background: transparent;")

        row_text_style = "background: transparent; color: #f0df9a; font-weight: 600;"

        self._name_label = QLabel(self)
        self._name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._name_label.setStyleSheet(row_text_style)
        self._name_label.setText(self._display_name)
        self._name_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self._date_label = QLabel(self)
        self._date_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._date_label.setStyleSheet(row_text_style)
        self._date_label.setText(self._modified_text)
        self._date_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self._type_label = QLabel(self)
        self._type_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._type_label.setStyleSheet(row_text_style)
        self._type_label.setText(self._type_text)
        self._type_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self._size_label = QLabel(self)
        self._size_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._size_label.setStyleSheet(row_text_style)
        self._size_label.setText(self._size_text)
        self._size_label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.update()

    def resizeEvent(self, _ev) -> None:
        w = max(1, self.width())
        h = max(1, self.height())

        left = 8
        gap = 8

        name_w = 175
        date_w = 145
        type_w = 90
        size_w = max(40, w - left - name_w - gap - date_w - gap - type_w - gap - 8)

        x1 = 8
        x2 = 180
        x3 = 314
        x4 = 384

        self._name_label.setGeometry(x1, 0, name_w, h)
        self._date_label.setGeometry(x2, 0, date_w, h)
        self._type_label.setGeometry(x3, 0, type_w, h)
        self._size_label.setGeometry(x4, 0, size_w, h)

    def enterEvent(self, ev) -> None:
        self._hover = True
        self.update()
        ev.accept()

    def leaveEvent(self, ev) -> None:
        self._hover = False
        self._pressed = False
        self.update()
        ev.accept()

    def mousePressEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)
        self._pressed = True
        self.update()
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(ev)

        inside = self.rect().contains(ev.position().toPoint() if hasattr(ev, "position") else ev.pos())
        was_pressed = self._pressed
        self._pressed = False
        self.update()

        if was_pressed and inside:
            self.clicked.emit(self._stem)

        ev.accept()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect().adjusted(2, 1, -2, -1)

        if self._selected:
            p.setPen(QPen(QColor(230, 195, 102, 220), 1))
            p.setBrush(QColor(120, 85, 20, 70))
            p.drawRoundedRect(r, 4, 4)
        elif self._pressed:
            p.setPen(QPen(QColor(210, 180, 95, 200), 1))
            p.setBrush(QColor(120, 85, 20, 50))
            p.drawRoundedRect(r, 4, 4)
        elif self._hover:
            p.setPen(QPen(QColor(210, 180, 95, 130), 1))
            p.setBrush(QColor(255, 255, 255, 12))
            p.drawRoundedRect(r, 4, 4)

        p.end()


class SaveLoadManagerWindow(QWidget):
    closed = Signal()
    cancelledToTotalMenu = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._owner: Optional[QWidget] = None
        self._shield: Optional[_InputShield] = None
        self._scale_factor: float = 1.0
        self._mode: str = "save"
        self._cancel_returns_to_total_menu: bool = False
        self._selected_stem: str = ""
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

        self._bg_save_pm = QPixmap(_resolve_resource(CFG.save_bg_path))
        self._bg_load_pm = QPixmap(_resolve_resource(CFG.load_bg_path))

        self.btn_close = _HitboxImageButton(
            hit_x=CFG.close_rect[0],
            hit_y=CFG.close_rect[1],
            hit_w=CFG.close_rect[2],
            hit_h=CFG.close_rect[3],
            visual_w=CFG.close_rect[2],
            visual_h=CFG.close_rect[3],
            active_rel_path=CFG.close_active_path,
            parent=self,
        )
        self.btn_close.clicked.connect(self.close_manager)

        self.btn_save = _HitboxImageButton(
            hit_x=CFG.action_rect[0],
            hit_y=CFG.action_rect[1],
            hit_w=CFG.action_rect[2],
            hit_h=CFG.action_rect[3],
            visual_w=CFG.action_visual_size[0],
            visual_h=CFG.action_visual_size[1],
            active_rel_path=CFG.save_active_path,
            parent=self,
        )
        self.btn_save.clicked.connect(self._perform_action)

        self.btn_load = _HitboxImageButton(
            hit_x=CFG.action_rect[0],
            hit_y=CFG.action_rect[1],
            hit_w=CFG.action_rect[2],
            hit_h=CFG.action_rect[3],
            visual_w=CFG.action_visual_size[0],
            visual_h=CFG.action_visual_size[1],
            active_rel_path=CFG.load_active_path,
            parent=self,
        )
        self.btn_load.clicked.connect(self._perform_action)

        self.btn_cancel = _HitboxImageButton(
            hit_x=CFG.cancel_rect[0],
            hit_y=CFG.cancel_rect[1],
            hit_w=CFG.cancel_rect[2],
            hit_h=CFG.cancel_rect[3],
            visual_w=CFG.cancel_visual_size[0],
            visual_h=CFG.cancel_visual_size[1],
            active_rel_path=CFG.cancel_active_path,
            parent=self,
        )
        self.btn_cancel.clicked.connect(self.cancel_action)

        self.filename_edit = QLineEdit(self)
        self.filename_edit.setStyleSheet(
            """
            QLineEdit {
                background: transparent;
                border: none;
                color: #f0df9a;
                selection-background-color: rgba(120,85,20,120);
                selection-color: #fff6cf;
                font-weight: 700;
                padding-left: 6px;
                padding-right: 6px;
            }
            """
        )
        self.filename_edit.setPlaceholderText("Название схемы")

        pal = self.filename_edit.palette()
        gold_text = QColor("#f0df9a")
        gold_placeholder = QColor("#f0df9a")

        pal.setColor(QPalette.Active, QPalette.Text, gold_text)
        pal.setColor(QPalette.Inactive, QPalette.Text, gold_text)
        pal.setColor(QPalette.Disabled, QPalette.Text, gold_text)

        pal.setColor(QPalette.Active, QPalette.PlaceholderText, gold_placeholder)
        pal.setColor(QPalette.Inactive, QPalette.PlaceholderText, gold_placeholder)
        pal.setColor(QPalette.Disabled, QPalette.PlaceholderText, gold_placeholder)

        self.filename_edit.setPalette(pal)

        self.filename_edit.returnPressed.connect(self._perform_action)

        self._list_area = QScrollArea(self)
        self._list_area.setFrameShape(QFrame.NoFrame)
        self._list_area.setWidgetResizable(True)
        self._list_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_area.setStyleSheet("background: transparent; border: none;")

        self._list_cont = QWidget()
        self._list_cont.setStyleSheet("background: transparent;")
        self._list_vbox = QVBoxLayout(self._list_cont)
        self._list_vbox.setContentsMargins(0, 0, 24, 0)
        self._list_vbox.setSpacing(1)
        self._list_vbox.addStretch(1)
        self._list_area.setWidget(self._list_cont)

        self._vscroll = _MiniVScroll(self)
        self._vscroll.bind_bar(self._list_area.verticalScrollBar())

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

    def _scaled_rect(self, rect: tuple[int, int, int, int]) -> QRect:
        s = max(0.1, float(self._scale_factor or 1.0))
        x, y, w, h = rect
        return QRect(
            int(round(x * s)),
            int(round(y * s)),
            max(1, int(round(w * s))),
            max(1, int(round(h * s))),
        )

    def _apply_scaled_layout(self) -> None:
        s = max(0.1, float(self._scale_factor or 1.0))

        w = max(1, int(round(CFG.fallback_size[0] * s)))
        h = max(1, int(round(CFG.fallback_size[1] * s)))

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

        bg_pm = self._bg_load_pm if str(self._mode).strip().lower() == "load" else self._bg_save_pm
        if isinstance(bg_pm, QPixmap) and not bg_pm.isNull():
            self._bg_label.setPixmap(
                bg_pm.scaled(QSize(w, h), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self._bg_label.clear()

        self._bg_label.raise_()

        self.btn_close.apply_scale(s)
        self.btn_save.apply_scale(s)
        self.btn_load.apply_scale(s)
        self.btn_cancel.apply_scale(s)

        self.filename_edit.setGeometry(self._scaled_rect(CFG.filename_rect))
        self._list_area.setGeometry(self._scaled_rect(CFG.list_rect))
        self._vscroll.setGeometry(self._scaled_rect(CFG.vscroll_rect))

        font = self.filename_edit.font()
        font.setPointSizeF(max(8.0, 10.0 * s))
        self.filename_edit.setFont(font)

        self.btn_close.raise_()
        self.btn_save.raise_()
        self.btn_load.raise_()
        self.btn_cancel.raise_()
        self.filename_edit.raise_()
        self._list_area.raise_()
        self._vscroll.raise_()

        self._rebuild_file_rows()

    def _set_mode(self, mode: str) -> None:
        self._mode = "load" if str(mode).strip().lower() == "load" else "save"

        self.btn_save.setVisible(self._mode == "save")
        self.btn_load.setVisible(self._mode == "load")

        bg_pm = self._bg_load_pm if self._mode == "load" else self._bg_save_pm
        if isinstance(bg_pm, QPixmap) and not bg_pm.isNull() and self.width() > 0 and self.height() > 0:
            self._bg_label.setPixmap(
                bg_pm.scaled(QSize(self.width(), self.height()), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self._bg_label.clear()

        try:
            self._bg_label.raise_()
            self.btn_close.raise_()
            self.btn_save.raise_()
            self.btn_load.raise_()
            self.btn_cancel.raise_()
            self.filename_edit.raise_()
            self._list_area.raise_()
            self._vscroll.raise_()
        except Exception:
            pass

    def open_centered(
            self,
            owner: QWidget,
            *,
            mode: str = "save",
            cancel_returns_to_total_menu: bool = False,
    ) -> None:
        if owner is None:
            return

        self._owner = owner
        self._scale_factor = self._owner_scale()
        self._cancel_returns_to_total_menu = bool(cancel_returns_to_total_menu)

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

        self._set_mode(mode)
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
        self.refresh_file_list()
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

        try:
            self.filename_edit.setFocus()
            self.filename_edit.selectAll()
        except Exception:
            pass

    def refresh_file_list(self) -> None:
        self._rebuild_file_rows()

    def _clear_file_rows(self) -> None:
        while self._list_vbox.count():
            item = self._list_vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _rebuild_file_rows(self) -> None:
        self._clear_file_rows()

        def _fmt_dt(ts: float) -> str:
            try:
                dt = datetime.fromtimestamp(float(ts))
                return dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                return "—"

        def _fmt_size(sz: int) -> str:
            try:
                size = int(sz)
            except Exception:
                return "—"

            if size < 1024:
                return f"{size} Б"
            if size < 1024 * 1024:
                val = size / 1024.0
                txt = f"{val:.1f}".rstrip("0").rstrip(".")
                return f"{txt} КБ"

            val = size / (1024.0 * 1024.0)
            txt = f"{val:.1f}".rstrip("0").rstrip(".")
            return f"{txt} МБ"

        s = max(0.1, float(self._scale_factor or 1.0))
        row_h = max(22, int(round(24 * s)))

        current_stem = _normalize_filename(self.filename_edit.text())

        files = _list_scheme_files()
        for p in files:
            stem = p.stem

            try:
                st = p.stat()
                modified_text = _fmt_dt(st.st_mtime)
                size_text = _fmt_size(st.st_size)
            except Exception:
                modified_text = "—"
                size_text = "—"

            type_text = "RQSCHEM"

            row = _SchemeRow(
                stem,
                stem,
                modified_text,
                type_text,
                size_text,
                self._list_cont,
            )
            row.setFixedHeight(row_h)
            row.clicked.connect(self._on_row_clicked)
            row.set_selected(stem == current_stem)
            self._list_vbox.addWidget(row)

        self._list_vbox.addStretch(1)

        try:
            self._vscroll._sync_from_bar()
        except Exception:
            pass

    def _on_row_clicked(self, stem: str) -> None:
        stem = str(stem or "")
        self._selected_stem = stem
        try:
            self.filename_edit.setText(stem)
            self.filename_edit.setFocus()
            self.filename_edit.selectAll()
        except Exception:
            pass
        self._rebuild_file_rows()

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

    def close_manager(self) -> None:
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

    def cancel_action(self) -> None:
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

        if self._cancel_returns_to_total_menu:
            self.cancelledToTotalMenu.emit()
        else:
            self.closed.emit()

    def _perform_action(self) -> None:
        if self._owner is None:
            return

        raw_name = str(self.filename_edit.text() or "").strip()
        clean_name = _normalize_filename(raw_name)

        if not clean_name:
            try:
                self.filename_edit.setFocus()
            except Exception:
                pass
            return

        path = _scheme_path_from_name(clean_name)

        if self._mode == "save":
            try:
                payload = build_character_scheme(self._owner)
                with path.open("w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            except Exception:
                return

            self.refresh_file_list()
            self.close_manager()
            return

        # load
        if not path.exists():
            return

        try:
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return

        ok = False
        try:
            ok = apply_character_scheme(self._owner, raw)
        except Exception:
            ok = False

        if ok:
            self.close_manager()

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Escape:
            self.close_manager()
            ev.accept()
            return
        super().keyPressEvent(ev)

