from __future__ import annotations
from dataclasses import dataclass

@dataclass
class EquipmentType:
    id: int
    name: str
    slot_id: int

@dataclass
class EquipmentSlot:
    id: int
    name: str
