from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Dict, Optional, Iterable, List, Tuple, Set
from .models import EquipmentType, EquipmentSlot


class DataAccess:
    """
    Минимальный доступ к БД под текущие нужды UI:
      - список классов (Id, Name, Image_Id)
      - получение байтов изображения по Id
      - кап уровня персонажа
      - список предметов для слота с учётом ограничений по классам (для валидации уже выбранных предметов)
    """
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._img_cache: Dict[int, bytes] = {}

        # кэш классов: Id -> Name
        self._classes_cache: Dict[int, str] = self._load_classes()

    # ---------- Классы ----------
    def list_classes(self) -> list[tuple[int, str, int]]:
        rows = self.conn.execute(
            "SELECT Id, Name, Image_Id FROM Class ORDER BY Id"
        ).fetchall()
        return [(int(r["Id"]), r["Name"], int(r["Image_Id"])) for r in rows]

    def _load_classes(self) -> Dict[int, str]:
        rows = self.conn.execute("SELECT Id, Name FROM Class").fetchall()
        return {int(r["Id"]): r["Name"] for r in rows}

    # ---------- Картинки ----------
    def get_image_bytes(self, image_id: int) -> Optional[bytes]:
        if image_id in self._img_cache:
            return self._img_cache[image_id]

        # принудительно приводим к BLOB, чтобы драйвер не пытался декодировать в str
        row = self.conn.execute(
            "SELECT CAST(Data AS BLOB) AS Data FROM Image WHERE Id=?",
            (image_id,)
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT CAST(Data AS BLOB) AS Data FROM StaticImage WHERE Id=?",
                (image_id,)
            ).fetchone()
        if row is None:
            return None

        blob = row["Data"]
        # в разных версиях sqlite3 для BLOB это может быть bytes или memoryview
        if isinstance(blob, memoryview):
            data = blob.tobytes()
        else:
            data = bytes(blob)

        self._img_cache[image_id] = data
        return data

    # ---------- Кап уровня ----------
    def get_max_character_level(self) -> int:
        row = self.conn.execute(
            "SELECT MaxLevel FROM Version ORDER BY ROWID DESC LIMIT 1"
        ).fetchone()
        if not row or row[0] is None:
            raise RuntimeError("Version.MaxLevel not found")
        return int(row[0])

    # ---------- Простая проверка предметов по слоту/классу ----------
    def list_equipment_for_slot(self, slot_id: int, class_id: int) -> list[dict]:
        """
        Вернёт предметы для указанного слота, учитывая ограничения:
          - Если у предмета есть EquipmentCondition -> разрешён, если class_id есть в списке предмета
          - Если у предмета НЕТ EquipmentCondition -> считаем универсальным
        Слот берётся из EquipmentType.Slot_Id.
        Поля: Id, Name, Image_Id (CostumeImage_Id приоритетнее).
        """
        q = """
        SELECT
            e.Id,
            e.Name,
            COALESCE(e.CostumeImage_Id, e.Image_Id) AS ImgId
        FROM Equipment AS e
        JOIN EquipmentType AS t ON t.Id = e.Type_Id
        WHERE t.Slot_Id = ?
          AND (
                -- у предмета есть свои ограничения -> проверяем только их
                (EXISTS (SELECT 1 FROM EquipmentCondition ec WHERE ec.Equipment_Id = e.Id)
                 AND EXISTS (SELECT 1 FROM EquipmentCondition ec
                             WHERE ec.Equipment_Id = e.Id AND ec.Class_Id = ?))
                OR
                -- у предмета нет ограничений -> универсален
                NOT EXISTS (SELECT 1 FROM EquipmentCondition ec WHERE ec.Equipment_Id = e.Id)
              )
        ORDER BY e.Name COLLATE NOCASE ASC
        """
        rows = self.conn.execute(q, (int(slot_id), int(class_id))).fetchall()
        return [
            {
                "Id": int(r["Id"]),
                "Name": r["Name"],
                "Image_Id": (int(r["ImgId"]) if r["ImgId"] is not None else None),
            }
            for r in rows
        ]
