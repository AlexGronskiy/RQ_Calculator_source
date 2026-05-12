# main_window
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Iterable
from pathlib import Path
from uuid import uuid4
import threading

from PySide6.QtGui import QCursor, QPixmap, QIcon, QPainter, QColor, QPen, QBrush, QMouseEvent, QFontMetrics, QImage, QBitmap
from PySide6.QtCore import Qt, QSize, QRect, QPoint, QTimer, QEvent, Signal, QObject
from PySide6.QtWidgets import (
    QApplication,
    QSpinBox,
    QGraphicsOpacityEffect,
    QWidget,
    QLabel,
    QMenu,
    QWidgetAction,
    QGridLayout,
    QToolButton,
    QFrame, QVBoxLayout, QPushButton, QScrollArea,
    QAbstractScrollArea, QScrollBar, QComboBox,
)

from ..db import DataAccess
from .level_wheel import LevelWheel
from .сostum_mount_button import CostumeController, MountController
from .weapon_equipment_button import (
    make_equipment_controllers,
    make_weapon_offhand_controllers,
    _render_bonus_lines,
)
try:
    from .weapon_equipment_button import ImageVScrollBar, _find_scroll_dir  # type: ignore
except Exception:
    ImageVScrollBar = None  # type: ignore
    _find_scroll_dir = None  # type: ignore
from .equipment_info_window import EquipmentInfoWindow
from .stamp_window import StampWindow
from .inventory import InventoryWindow
from .reforge import UpgradeWindow  # путь подправь, если reforge.py в другом пакете
from .cards import CardsWindow
from .characteristics_math import (
    CharacteristicsPanel,
    OtherCharacteristicsPanel,
    ParamAllocationState,
    UnspentParamPointsWidget,
    layout_unspent_param_points_widget,
)
from collections import defaultdict
from .collection import CollectionWindow
from .elixir_menu import ChooseElixirMenu, ElixirChooseConfig
from .consumble_menu import ChooseConsumbleMenu, ConsumbleChooseConfig
from .guild_menu import GuildMenu
from .talents_menu import TalentsMenu
from .aura_menu import AuraMenuWindow
from .buff_debuff_menu import BuffDebuffMenuWindow
from .total_menu import TotalMenuWindow
from .save_and_load_manager import SaveLoadManagerWindow
from .update_manager import UpdateManager, UpdateCheckResult

# =========================
# "КОНФИГ"
# =========================
# --- spear rules ---
SPEAR_TYPE_ID = 22
SPEAR_HIDE_FOR_CLASS_IDS = {1}   # базовый мечник: НЕ показываем слот/фон

# --- фон ---
MAIN_BG_PATH_DEFAULT = "resources/main_menu/main_window.png"
MAIN_BG_PATH_SPEAR = "resources/main_menu/main_window_spear.png"

# --- окна (hover-иконки) ---
MINIMIZE_HOVER_PATH = "resources/helper_buttons/minimize_button_active.png"
CLOSE_HOVER_PATH = "resources/helper_buttons/close_button_active.png"

EXTRA_ZONES = {
    "close": {"pos": (623, 4), "size": 24, "glow_px": 1.00, "glow_scale": 25},
    "minimize": {"pos": (579, 4), "size": 24, "glow_px": 1.00, "glow_scale": 25},
}

OTHER_MENU_OPEN_BTN_RECT = (652, 203, 18, 98)
OTHER_MENU_OPEN_HOVER_PATH = "resources/main_menu/other/buttonRight_mouseover.png"
OTHER_MENU_OPEN_PRESS_PATH = "resources/main_menu/other/buttonRight_press.png"

OTHER_MENU_BG_PATH = "resources/main_menu/main_window_other.png"
OTHER_MENU_OVERLAP_PX = 26

OTHER_MENU_CLOSE_BTN_RECT = (288, 203, 18, 98)
OTHER_MENU_CLOSE_HOVER_PATH = "resources/main_menu/other/buttonClose_mouseover.png"
OTHER_MENU_CLOSE_PRESS_PATH = "resources/main_menu/other/buttonClose_press.png"

# --- нижнее меню ---
MENU_GLOW_PATH = "resources/main_menu/glow_button.png"
MENU_BUTTONS = [
    {"key": "talents", "rect": (55, 460, 42, 46)},
    {"key": "guild", "rect": (100, 460, 42, 46)},
    {"key": "elixir", "rect": (142, 460, 42, 46)},
    {"key": "consumble", "rect": (187, 460, 42, 46)},
    {"key": "aura", "rect": (232, 460, 42, 46)},
    {"key": "buffs", "rect": (277, 460, 42, 46)},
    {"key": "collect", "rect": (322, 460, 42, 46)},
    {"key": "stamp", "rect": (371, 460, 42, 46)},
    {"key": "reforge", "rect": (415, 460, 42, 46)},
    {"key": "inventory", "rect": (460, 460, 42, 46)},
]
MENU_KEYS = {b["key"] for b in MENU_BUTTONS}

MENU_BONUS_TOGGLE_KEYS = (
    "talents",
    "guild",
    "elixir",
    "consumble",
    "aura",
    "buffs",
    "collect",
)

# --- выбор класса ---
CLASS_ICON_OFFSET = (-145, -66)  # смещение иконки класса (dx, dy) в пикселях экрана
CLASS_FRAME_PX = 38
CLASS_ICON_PX = 36
CLASS_BORDER_W = 2

# --- силуэт ---
SIL_OFFSET = (-145, 45)  # смещение силуэта (dx, dy)
SIL_SCALE = 0.70

# --- glow / slots ---
SLOT_PX = 64
SLOT_VISUAL_PX = 60
GLOW_PATH = "resources/main_menu/glow.png"
GLOW_SCALE = 1.00
GLOW_SHIFT_X = 0
GLOW_SHIFT_Y = 0
GLOW_CLIP_TO_IMG = True

# --- пол ---
GENDER_ICON_PX = 20
GENDER_BTN_PAD = 8
GENDER_BORDER_W = 2
GENDER_POS_MANUAL = True
GENDER_M_POS = (140, 417)  # координаты в системе PNG
GENDER_F_POS = (211, 417)
GENDER_M_OFFSET = (0, 0)
GENDER_F_OFFSET = (0, 0)

# --- цвета ---
GOLD = "#e6d27a"
BORDER_NORMAL = "#444"
MENU_THUMB_BORDER_W = 1

# --- иконки пола ---
GENDER_BEFORE20_M = "resources/main_menu/gender/man_befor_20.png"
GENDER_BEFORE20_F = "resources/main_menu/gender/woman_befor_20.png"
GENDER_AFTER20_M = "resources/main_menu/gender/man_after_20.png"
GENDER_AFTER20_F = "resources/main_menu/gender/woman_after_20.png"

# --- координаты слотов (система исходного PNG) ---
SLOT_POS: Dict[str, Tuple[int, int]] = {
    "head": (21, 48),
    "mask": (21, 106),
    "armor": (21, 162),
    "gloves": (21, 219),
    "legs": (21, 277),
    "boots": (21, 334),
    "weapon": (21, 391),
    "costume": (239, 48),
    "spear": (78, 390),
    "mount": (239, 390),
    "ornament": (296, 48),
    "amulet": (296, 106),
    "ring1": (296, 162),
    "ring2": (296, 219),
    "totem": (296, 277),
    "artifact": (296, 334),
    "offhand": (296, 391),
}

NON_INVENTORY_COPY_SLOTS = {"costume", "ornament", "mount"}

# --- изображения силуэта в БД ---
IMG = {"silhouette_m": 888, "silhouette_f": 889}

# насколько заполнить иконкой прямоугольник слота (1.0 = полностью)
SLOT_ICON_SCALE = 0.78

# где-нибудь рядом с константами
ELEM_BADGE_SCALE = 0.35
ELEM_BADGE_DX = -3   # >0 вправо
ELEM_BADGE_DY = 0   # >0 вверх

# --- 2 доп. кнопки в MainWindow ---
SMALL_MENU_BTN_OFF_PATH = "resources/main_menu/menu_button_off.png"
SMALL_MENU_BTN_DOWN_PATH = "resources/main_menu/menu_button_turn.png"

# размер в пикселях исходного PNG
SMALL_MENU_BTN_W = 21
SMALL_MENU_BTN_H = 20

# позиции в системе исходного PNG (x, y)
# поменяй эти координаты как хочешь
SMALL_MENU_BTNS = [
    {"key": "extra_btn1", "pos": (16, 10)},
    {"key": "extra_btn2", "pos": (172, 10)},
    {"key": "extra_btn3", "pos": (371, 10)},  # LostControl
]

# --- кнопки быстрого просмотра активных бафов/дебафов ---
ACTIVE_BUFF_PREVIEW_BTN_ACTIVE_PATH = "resources/main_menu/menu_button_turn_left.png"

ACTIVE_BUFF_PREVIEW_BTN_W = 20
ACTIVE_BUFF_PREVIEW_BTN_H = 21
ACTIVE_BUFF_PREVIEW_BTN_FIRST_POS = (279, 109)
ACTIVE_BUFF_PREVIEW_BTN_GAP_Y = 1

ACTIVE_BUFF_PREVIEW_BTNS = [
    {
        "key": "buff_preview_other",
        "mode": "other",
        "title": "Активные бафы",
        "empty": "Нет активных бафов",
        "index": 0,
    },
    {
        "key": "buff_preview_personal",
        "mode": "personal",
        "title": "Личные бафы",
        "empty": "Нет активных личных бафов",
        "index": 1,
    },
    {
        "key": "buff_preview_debuff",
        "mode": "debuff",
        "title": "Дебафы",
        "empty": "Нет активных дебафов",
        "index": 2,
    },
]

TOTAL_MENU_BTN_RECT = (491, 4, 24, 24)
TOTAL_MENU_BTN_ACTIVE_PATH = "resources/helper_buttons/menu_button_active.png"

HELP_MENU_BTN_RECT = (535, 4, 24, 24)
HELP_MENU_BTN_ACTIVE_PATH = "resources/helper_buttons/help_button_active.png"

HELP_CONTROL_BG_PATH = "resources/main_menu/helper_control.png"
HELP_CONTROL_FALLBACK_SIZE = (562, 372)

HELP_CONTROL_CLOSE_RECT = (525, 3, 24, 24)
HELP_CONTROL_CLOSE_ACTIVE_PATH = "resources/helper_buttons/close_button_active.png"

HELP_CONTROL_TEXT_RECT = (20, 58, 498, 299)
HELP_CONTROL_SCROLL_RECT = (519, 55, 22, 300)

HELP_CONTROL_TEXT = """
Этот калькулятор создан игроком SilverDeath на языке Python.
В основе лежит модифицированная БД старого калькулятора.
Все несостыковки что вы можете обнаружить сделаны не специально(честное слово)!
Сообщить об ошибке можно в Меню(иконка шестерни на главном экране).
Отдельная благодарность Royal Creator-ам кто согласился участвовать в
обзорном Бэта-тесте, а так же всем кто помогал на этапе разработки
советами и выявлением багов.

Внимание! В новом калькуляторе нельзя вставить "устаревшие карты" и наложить 
"устаревшие печати", скорее всего этой возможности добавлено не будет!

Краткий экскурс по управлению и интерфейсу:
1) Уровень персонажа, выбор класса, выбор пола:
Наводясь курсором на цифры над головой силуэта персонажа и покрутив
колёсико мыши, можно прибавить/отнять уровень персонажа. Так же, если необходимо
ввести конкретный уровень, нажмите по цифрам и введите число. 
Внимание! 
Если уровень персонажа случайно сбросится, то надетые предметы не доступные ему 
по уровню переместятся в Инвентарь.

Выбор класса осуществляется нажатием на иконку класса, всего в игре 4 класса:
Мечник, Стрелок, Маг, Вор.
Каждый из классов имеет 2 специализации что можно выбрать достигнув 20-го уровня:
Мечника может выбрать развитие или в Крестоносца, или в Тёмного рыцаря.
Стрелок может выбрать развитие или в Охотника, или в Снайпера.
Маг может выбрать развитие или в Волшебника, или в Чернокнижника.
Вор может выбрать развитие или в Разбойника, или в Ассасина.
Внимание! 
Если вы поменяете класс персонажа на другой, то все экипированные предметы и 
предметы лежащие в инвентаре неподходящие этому классу будут удалены.

Так же, в калькуляторе как и в игре есть на выбор 2 пола - мужской и женский.
Технически пол персонажа не влияет на основной геймплей, разница только во внешнем 
виде экипировки и доступности к надеванию некоторых элементов экипировки.
Внимание! 
Если вы поменяете пол персонажа на другой, то все экипированные предметы и 
предметы лежащие в инвентаре неподходящие этому полу будут удалены.

2) Выбор экипировки:
- Слоты "Головной убор", "Аксессуар для Лица", "Доспех", "Перчатки", "Поножи",
"Обувь", "Оружие", "Левая рука/Щит/Орб", "Копьё", "Амулет", "Кольцо(верхний слот)",
"Кольцо(нижний слот)", "Тотем","Артефакт" вызывают стандартное меню выбора
предмета, список предметов зависит на прямую от выбранного вами класса и 
текущего уровня персонажа.
- Слоты "Костюм" и "Ездовое животное" вызывают меню выбора предмета на прямую 
зависящее от меню "Коллекции", так что перед выбором этих предметов убедитесь
что они добавлены в вашу коллекцию.
- Слот "Украшение" вызывает меню со списком всех доступных в игре 
украшений(некоторые из них больше нельзя получить в игре)
 
3) Вставка карт в предмет:
Для вставки карты в предмет необходимо навестись на необходимый нам предмет
и с зажатым Shift нажать ПКМ(правая кнопка мыши), после чего откроется
меню вставки карты. Нажав на слот карты откроется меню выбора карт, в
нём можно искать необходимую карту по названию и по характеристикам.
После выбора карты необходимо нажать "Привенить", в противном случае
карте просто не учтётся.
Что бы из предмета убрать карту необход так же с зажатым Shift нажать 
ПКМ(правая кнопка мыши) после чего нажать "Очистить"(в случае с оружием 
увы пока все 3 карты будут очищаться, в дальнейших обновлениях эта 
недоработка будет устранена)

4) Наложение печати:
Для наложения печати необходимо открыть меню с рисунком сургуча Ахи.
Что бы поместить предмет в слот для наложения печати необходимо нажать
на то же место куда и в игре помещается предмет, откроется окно с выбором
предмета, список формируется из предметов надетых на персонажа.
Чтобы наложить на предмет необходимую печать, необходимо нажать на слот
с изображением Изумруда/Сапфира/Мориона - откроется меню со списком
всех возможных печатей для выбранного предмета в том числе и с печатями
доступными для переноса от других классов(так же присутствует поиск по
названию и по параметрам печати). После выбора печати она автоматически
будет выбранна самой редкой по цвету(рыжая печать). Для изменения цвета
необходимо выбрать кружок с соответствующим цветом печати на нижней панели.

5) Улучшение предмета: 
Для улучшение предмета необходимо открыть меню с рисунком Пурпурного 
филосовского камня. Что бы поместить предмет в слот для улучшения предмета 
необходимо нажать на то же место куда и в игре помещается предмет, 
откроется окно с выбором предмета(список формируется из предметов 
надетых на персонажа). Чтобы улучшить предмет до необходимого уровня, 
надо нажать на слот с Пурпурным философским камнем - откроется меню со списком
уровнея улучшения доступного для выбранного предмета.

6) Инветарь:
Инвентарь создан что бы проще было сравнивать характеристики экипировки и найти
самую подходящую для Вас схему персонажа, так же в инвентаре доступно 78 слотов
под "свап" экипировку.
Что бы перенести предмет в инвентарь необходимо просто нажать по предмету
ПКМ(правая кнопка мыши), после чего предмет переместится в первый свободный слот
инвентаря. Если в инвентаре нажать ПКМ по предмету он поместится в подходящий слот,
если слот занят предметом аналогичного типа предметы просто поменяются местами.


7) Взаимодействие с экипировкой:
Если в основном меню(меню персонажа) с зажатым Ctrl нажать ПКМ то у нас откроется
окно взаимодействия с предметом, у Колец и Оружия есть дополнительные параметры 
для взаимодействия. Также это окно можно вызвать и в инвентаре.

8) Менеджер сохранения/загрузки:
В калькуляторе можно сохранить или загрузить существующую схему персонажа,
это необходимо что бы каждый раз не пересобирать с нуля, или по памяти свою
сборку. Чтобы сохранить/загрущить персонажа необходимо нажать на "Меню"(иконка 
шестерни на главном экране). Или же это можно сделать сочетанием клавиш:
Ctrl + S - открыть менеджер сохранения
Ctrl + D - открыть менеджер загрузки

9) Показатель Урон в секунду:
Этот пораметр из меню "Прочее" отображает усреднённый урон на продолжительной 
дистанции. В урон в секунду входит урон от простых ударов персонажа, усиление
от карты элемента, учитывается дот урон(высчитывается невидимый параметр 
"удержание дот-урона" на основе всез источников дот и учитывается усиление
% от разгона дот), так же учитывается существо что мы бьём и урон по существам
определённой расы и стихии, а так же все усилители на %урон. К сожалению в настройке
крона по существу нет параметра "защиты существа", этот параметр не получилось 
высчитать самостоятельно(при разхработке была найдена информация но форуме, но 
небыло никакого подтверждения ей). Исходя из информации что была найдена на форуме
итоговый множитель для урона по существу с защитой следующий:
Защита: Нет - 1
Защита: Низкая - 0.7
Защита: Средняя - 0.6
Защита: Высокая - 0.5
Соре, но так как я не смог подтвердить эту инфу я её решил пока не добавлять,
позднее если получится подтвердить, то в последующих версиях я намерен добавить 
эту функцию.

10) Показатель EHP:
Этот параметр из меню "Прочее" не является прямым показателем выживаемости персонажа, это параметр 
эффективности здоровья персонажа(то сколько фактически персонаж может впитать урона).
Он зависит от вашего максимального здоровья, от показателя снижения урона защиты(при 
наведении на параметр Защита можно увидеть на сколько % снижен урон по вам) и от 
устойчивостей к расам и элементам. В конструкторе существа ниже параметра EHP вы 
можете посмотреть на сколько разные устойчивости в действительности эффетивны, особенно
для игроков не имеющих хорошую экипировку.

Что бы я мог добавить параметр именно выживаемости, необходимо знать как именно уворот
работает относительно попадания, по сколько у каждого существа в игре есть свой показатель 
попадания, точной формулы считающей шанс уворота от попадания увы нет возможности узнать.
""".strip()

HOVER_NAME_TEXT_BY_KEY = {
    # Слоты экипировки
    "head":     "Головной убор",
    "mask":     "Аксессуар для Лица",
    "armor":    "Доспех",
    "gloves":   "Перчатки",
    "legs":     "Поножи",
    "boots":    "Обувь",
    "weapon":   "Оружие",
    "offhand":  "Левая рука/Щит/Орб",
    "spear":    "Копьё",
    "costume":  "Костюм",
    "mount":    "Ездовое животное",
    "ornament": "Украшение",
    "amulet":   "Амулет",
    "ring1":    "Кольцо(верхний слот)",
    "ring2":    "Кольцо(нижний слот)",
    "totem":    "Тотем",
    "artifact": "Артефакт",

    # Нижнее меню
    "talents": "Таланты",
    "guild": "Гильдия",
    "elixir": "Эликсиры",
    "consumble": "Расходники",
    "aura": "Ауры",
    "buffs": "Бафы/Дебафы",
    "collect": "Коллекции",
    "stamp": "Наложение печати",
    "reforge": "Улучшение предмета",
    "inventory": "Инвентарь",

    # Верхние кнопки / служебное
    "close": "Закрыть",
    "minimize": "Свернуть",
    "helper_menu": "Подсказки",
    "total_menu": "Меню",

    # Маленькие выборы сверху
    "extra_btn1": "Состояние",
    "extra_btn2": "Текущий ивент",
    "extra_btn3": "Состояние контроля",

    # Прочее меню
    "other_menu_open": "Прочее",
    "other_menu_close": "Скрыть прочее",

    # Класс / пол
    "class": "Класс",
    "gender_m": "Мужской",
    "gender_f": "Женский",
}

HOVER_NAME_LABEL_MAX_W = 190

POPUP_MENU_STYLE = """
QMenu {
    background: transparent;
    border: none;
    padding: 6px;
}

QMenu::separator {
    height: 1px;
    background: rgba(145, 140, 128, 190);
    margin: 6px 8px;
}

QMenu::item {
    color: #f2c45d;
    background: transparent;
    padding: 6px 14px;
    margin: 1px 2px;
    border-radius: 5px;
    font-weight: 700;
}

QMenu::item:selected {
    color: #fff0b0;
    background-color: rgba(80, 80, 80, 145);
    border-radius: 5px;
}

QMenu::item:pressed {
    color: #ffffff;
    background-color: rgba(110, 100, 80, 170);
}

QMenu::item:disabled {
    color: rgba(180, 180, 180, 120);
}

QMenu::indicator {
    width: 14px;
    height: 14px;
}
"""

POPUP_PANEL_STYLE = """
QWidget {
    background: transparent;
    border: none;
}
"""

CLASS_THUMB_STYLE = """
QToolButton {
    background-color: rgba(30, 30, 30, 125);
    border: 2px solid rgba(145, 140, 128, 235);
    border-radius: 7px;
    padding: 3px;
}

QToolButton:hover {
    background-color: rgba(120, 120, 120, 150);
    border: 2px solid #f2c45d;
}

QToolButton:pressed {
    background-color: rgba(145, 135, 105, 165);
    border: 2px solid #fff0b0;
}
"""


def _apply_popup_menu_style(menu: QMenu) -> None:
    if menu is None:
        return

    try:
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
        menu.setAttribute(Qt.WA_NoSystemBackground, True)
        menu.setAttribute(Qt.WA_StyledBackground, False)
        menu.setAutoFillBackground(False)
    except Exception:
        pass

    try:
        menu.setWindowFlag(Qt.FramelessWindowHint, True)
        menu.setWindowFlag(Qt.NoDropShadowWindowHint, True)
    except Exception:
        pass

    menu.setStyleSheet(POPUP_MENU_STYLE)

# =========================
# HELPERS
# =========================
def _pm_from_bytes(data: Optional[bytes]) -> Optional[QPixmap]:
    if not data:
        return None
    pm = QPixmap()
    return pm if pm.loadFromData(data) else None


def _load_db_image(db: DataAccess, image_id: int) -> Optional[QPixmap]:
    try:
        return _pm_from_bytes(db.get_image_bytes(int(image_id)))
    except Exception:
        return None


def _resolve_resource(rel_path: str) -> Optional[str]:
    p = Path(rel_path)
    for base in (Path.cwd(), Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[3]):
        candidate = base / p
        if candidate.exists():
            return str(candidate)
    return None

def db_allowed_equipment_ids(conn, slot_id: int, class_ids: list[int]) -> set[int]:
    # ВНИМАНИЕ: e.Type_Id возможно у тебя называется иначе (EquipmentType_Id и т.п.)
    # Подправь JOIN под свою таблицу Equipment.
    ph = ",".join(["?"] * len(class_ids)) if class_ids else "NULL"
    sql = f"""
    SELECT e.Id
    FROM Equipment e
    JOIN EquipmentType et ON et.Id = e.Type_Id
    WHERE et.Slot_Id = ?
      AND (
        NOT EXISTS (SELECT 1 FROM EquipmentCondition c WHERE c.Equipment_Id = e.Id)
        OR EXISTS (SELECT 1 FROM EquipmentCondition c
                   WHERE c.Equipment_Id = e.Id AND c.Class_Id IN ({ph}))
      )
    """
    args = [slot_id] + class_ids
    return {row[0] for row in conn.execute(sql, args).fetchall()}

_FILE_IMAGE_CACHE: Dict[str, QPixmap] = {}

def _load_file_image(rel_path: str) -> Optional[QPixmap]:
    """
    Ленивая загрузка картинки с диска с кешированием по абсолютному пути.
    """
    rp = _resolve_resource(rel_path) or rel_path
    if rp in _FILE_IMAGE_CACHE:
        return _FILE_IMAGE_CACHE[rp]

    pm = QPixmap(rp)
    if pm.isNull():
        return None

    _FILE_IMAGE_CACHE[rp] = pm
    return pm

def _safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default

STATS_RECT = (356, 34, 300, 428)


class _MenuBonusToggle(QWidget):
    """
    Маленький квадратик с галочкой в правом верхнем углу кнопки нижнего меню.

    Полностью независим от EquipmentBonus.Activate.
    Управляет только включением/выключением учёта бонусов соответствующего меню в математике.
    """

    BOX = 14
    PAD = 1

    def __init__(self, parent_widget: QWidget, menu_key: str):
        super().__init__(parent_widget)
        self._menu_key = str(menu_key or "").strip().lower()

        self.setFixedSize(self.BOX, self.BOX)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Бонусы этого меню (вкл/выкл)")

        self._checked = True
        self._visible = True

        self.hide()
        try:
            parent_widget.installEventFilter(self)
        except Exception:
            pass

    def sync(self) -> None:
        owner = self.parentWidget()
        if owner is None:
            return

        btn = None
        try:
            btn = (getattr(owner, "menu_btns", {}) or {}).get(self._menu_key)
        except Exception:
            btn = None

        if btn is None:
            self._visible = False
            self.hide()
            return

        state = {}
        try:
            state = getattr(owner, "_get_menu_bonus_enabled_map")()
        except Exception:
            state = getattr(owner, "_menu_bonus_enabled", {}) or {}

        self._checked = bool(state.get(self._menu_key, True))
        self._visible = True

        self._reposition()
        self.show()
        self.raise_()
        self.update()

    def eventFilter(self, obj, ev):
        if obj is self.parentWidget():
            et = ev.type()
            if et in (QEvent.Paint, QEvent.Resize, QEvent.Move, QEvent.Show):
                try:
                    self.sync()
                except Exception:
                    pass
        return False

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)

        owner = self.parentWidget()
        if owner is None:
            return super().mousePressEvent(ev)

        try:
            fn = getattr(owner, "_on_menu_bonus_toggle_clicked", None)
            if callable(fn):
                fn(self._menu_key)
        except Exception:
            pass

        ev.accept()

    def paintEvent(self, ev):
        if not self._visible:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect().adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
        p.setPen(QPen(QColor(220, 220, 220, 230), 1))
        p.setBrush(QColor(0, 0, 0, 255))
        p.drawRoundedRect(r, 2, 2)

        if self._checked:
            p.setPen(QPen(QColor(245, 245, 245, 240), 2))
            x1 = r.left() + 3
            y1 = r.center().y()
            x2 = r.left() + 6
            y2 = r.bottom() - 3
            x3 = r.right() - 3
            y3 = r.top() + 3
            p.drawLine(x1, y1, x2, y2)
            p.drawLine(x2, y2, x3, y3)

        p.end()

    def _reposition(self) -> None:
        owner = self.parentWidget()
        if owner is None:
            return

        rect = None

        try:
            zr = getattr(owner, "_zone_rect", None)
            if callable(zr):
                rect = zr(self._menu_key)
        except Exception:
            rect = None

        if rect is None:
            try:
                btn = (getattr(owner, "menu_btns", {}) or {}).get(self._menu_key)
                if btn is not None:
                    rect = btn.geometry()
            except Exception:
                rect = None

        if rect is None or rect.isNull():
            self.hide()
            return

        x = rect.right() - self.width() + 1
        y = rect.top() + 1
        self.move(int(x), int(y))


class _ControlStatusWidget(QWidget):
    """
    Маленькая строка статуса контроля:
    текст + иконка справа.
    Если всё не помещается — бегущая строка.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._text: str = ""
        self._icon_pm: Optional[QPixmap] = None
        self._offset: int = 0

        # ВАЖНО:
        # timer создаём ДО self.hide(), потому что hide() может сразу вызвать hideEvent().
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._tick)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")

        self.hide()

    def set_payload(self, text: str, icon_pm: Optional[QPixmap]) -> None:
        self._text = str(text or "")
        self._icon_pm = QPixmap(icon_pm) if isinstance(icon_pm, QPixmap) and not icon_pm.isNull() else None
        self._offset = 0
        self.setToolTip(self._text)
        self._update_timer_state()
        self.update()

    def _icon_side(self) -> int:
        return max(1, min(20, int(self.height())))

    def _content_width(self) -> int:
        if not self._text:
            return 0

        fm = QFontMetrics(self.font())
        text_w = int(fm.horizontalAdvance(self._text))

        if self._icon_pm is not None and not self._icon_pm.isNull():
            return text_w + 5 + self._icon_side()

        return text_w

    def _update_timer_state(self) -> None:
        timer = getattr(self, "_timer", None)
        if timer is None:
            return

        need_scroll = self._content_width() > max(1, self.width())

        if need_scroll and self.isVisible():
            if not timer.isActive():
                timer.start()
        else:
            if timer.isActive():
                timer.stop()
            self._offset = 0

    def _tick(self) -> None:
        cw = self._content_width()

        if cw <= self.width():
            self._offset = 0
            self._update_timer_state()
            self.update()
            return

        gap = 28
        self._offset += 1

        if self._offset > cw + gap:
            self._offset = 0

        self.update()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._update_timer_state()

    def hideEvent(self, ev) -> None:
        super().hideEvent(ev)

        timer = getattr(self, "_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._update_timer_state()

    def paintEvent(self, ev) -> None:
        if not self._text:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setClipRect(self.rect())

        fm = QFontMetrics(self.font())
        text_w = int(fm.horizontalAdvance(self._text))
        icon_side = self._icon_side()

        has_icon = self._icon_pm is not None and not self._icon_pm.isNull()
        content_w = self._content_width()
        scroll_gap = 28

        p.setPen(QColor(GOLD))

        def _draw_content(x: int) -> None:
            baseline = int((self.height() + fm.ascent() - fm.descent()) / 2)
            p.drawText(int(x), int(baseline), self._text)

            if has_icon:
                icon_x = int(x + text_w + 5)
                icon_y = int((self.height() - icon_side) / 2)

                pm = self._icon_pm.scaled(
                    icon_side,
                    icon_side,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                p.drawPixmap(icon_x, icon_y, pm)

        if content_w <= self.width():
            _draw_content(0)
        else:
            x1 = -int(self._offset)
            _draw_content(x1)
            _draw_content(x1 + content_w + scroll_gap)

        p.end()


class _LostControlMenuRow(QWidget):
    """
    Строка QMenu для LostControl:
    Name + справа через небольшой пробел Image_Id.
    """

    def __init__(
            self,
            action: QWidgetAction,
            *,
            name: str,
            icon_pm: Optional[QPixmap],
            checked: bool,
            width: int,
            parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self._action = action
        self._name = str(name or "")
        self._icon_pm = QPixmap(icon_pm) if isinstance(icon_pm, QPixmap) and not icon_pm.isNull() else None
        self._checked = bool(checked)
        self._hovered = False

        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(max(120, int(width)), 26)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")

    def enterEvent(self, ev) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.pos()):
            try:
                self._action.trigger()
            except Exception:
                pass
            ev.accept()
            return

        super().mouseReleaseEvent(ev)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        r = self.rect()

        if self._hovered:
            p.setBrush(QColor(80, 80, 80, 145))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r.adjusted(2, 1, -2, -1), 5, 5)

        color = QColor(GOLD) if self._checked else QColor("#dddddd")
        p.setPen(color)

        fm = QFontMetrics(self.font())
        text_x = 10
        baseline = int((self.height() + fm.ascent() - fm.descent()) / 2)
        p.drawText(text_x, baseline, self._name)

        if self._icon_pm is not None and not self._icon_pm.isNull():
            text_w = int(fm.horizontalAdvance(self._name))
            side = 20
            icon_x = int(text_x + text_w + 6)
            icon_y = int((self.height() - side) / 2)

            pm = self._icon_pm.scaled(
                side,
                side,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            p.drawPixmap(icon_x, icon_y, pm)

        p.end()


class _HoverNameInfoBoard(QFrame):
    """
    Маленький инфо-борд для названия зоны наведения.
    Стиль: чёрный полупрозрачный фон, металлическая обводка 2px,
    скругление, золотистый текст.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")

        self._lab = QLabel(self)
        self._lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._lab.setAttribute(Qt.WA_TranslucentBackground, True)
        self._lab.setAutoFillBackground(False)
        self._lab.setAlignment(Qt.AlignCenter)
        self._lab.setWordWrap(True)
        self._lab.setTextFormat(Qt.RichText)
        self._lab.setStyleSheet(
            "background: transparent;"
            "border: none;"
            "color: #f2c45d;"
            "font-weight: 700;"
        )

        self.hide()

    def set_point_size(self, pt: int) -> None:
        try:
            f = self._lab.font()
            f.setPointSize(int(pt))
            self._lab.setFont(f)
        except Exception:
            pass

    def setText(self, text: str) -> None:
        self.set_text(text, max_w=HOVER_NAME_LABEL_MAX_W)

    def text(self) -> str:
        try:
            return str(self._plain_text or "")
        except Exception:
            return ""

    def set_text(self, text: str, max_w: int = 190) -> None:
        self._plain_text = str(text or "").strip()

        safe = (
            self._plain_text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        self._lab.setText(
            "<div style='line-height:125%;'>"
            f"<span style='color:#f2c45d; font-weight:700;'>{safe}</span>"
            "</div>"
        )

        pad_x = 10
        pad_y = 6

        try:
            fm = QFontMetrics(self._lab.font())
            text_w = int(fm.horizontalAdvance(self._plain_text))
        except Exception:
            text_w = int(max_w)

        label_max_w = max(80, int(max_w) - pad_x * 2)
        label_w = min(label_max_w, max(40, text_w + 6))

        self._lab.setFixedWidth(int(label_w))
        self._lab.adjustSize()
        self._lab.move(int(pad_x), int(pad_y))

        self.resize(
            int(self._lab.width() + pad_x * 2),
            int(self._lab.height() + pad_y * 2),
        )

    def adjustSize(self) -> None:
        try:
            self.set_text(self.text(), max_w=HOVER_NAME_LABEL_MAX_W)
        except Exception:
            super().adjustSize()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect().adjusted(1, 1, -2, -2)

        # Чёрный фон примерно 90% непрозрачности.
        p.setBrush(QColor(0, 0, 0, 230))

        # Металлическая обводка 2px.
        p.setPen(QPen(QColor(145, 140, 128, 235), 2))

        p.drawRoundedRect(r, 7, 7)
        p.end()

        super().paintEvent(ev)


class _ActiveBuffPreviewTooltip(QFrame):
    """
    Tooltip для иконки активного бафа:
    название сверху, ниже описание бонуса.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(
            parent,
            Qt.ToolTip |
            Qt.FramelessWindowHint |
            Qt.NoDropShadowWindowHint,
        )

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")

        self._lab = QLabel(self)
        self._lab.setWordWrap(True)
        self._lab.setTextFormat(Qt.RichText)
        self._lab.setStyleSheet(
            "background: transparent;"
            "border: none;"
            "color: #f2f2f2;"
            "font-weight: 700;"
        )

        self.hide()

    def _esc(self, text: str) -> str:
        return (
            str(text or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )

    def set_payload(self, name: str, bonus_text: str) -> None:
        name = str(name or "").strip() or "Баф"
        bonus_text = str(bonus_text or "").strip() or "Бонус не указан"

        html = (
            "<div style='line-height:130%;'>"
            f"<span style='color:#f2c45d; font-weight:800;'>{self._esc(name)}</span>"
            "<br>"
            f"<span style='color:#f2f2f2; font-weight:650;'>{self._esc(bonus_text)}</span>"
            "</div>"
        )

        self._lab.setText(html)

        pad_x = 10
        pad_y = 8
        max_w = 270

        self._lab.setFixedWidth(max_w - pad_x * 2)
        self._lab.adjustSize()
        self._lab.move(pad_x, pad_y)

        self.resize(
            int(self._lab.width() + pad_x * 2),
            int(self._lab.height() + pad_y * 2),
        )

    def show_near_widget(self, w: QWidget) -> None:
        if w is None:
            return

        try:
            gap = 8
            gp = w.mapToGlobal(QPoint(w.width() + gap, 0))

            screen = w.screen()
            available = screen.availableGeometry() if screen is not None else QRect()

            if not available.isEmpty():
                if gp.x() + self.width() > available.right():
                    gp = w.mapToGlobal(QPoint(-self.width() - gap, 0))

                if gp.y() + self.height() > available.bottom():
                    gp.setY(max(available.top() + 4, available.bottom() - self.height() - 4))

                if gp.y() < available.top():
                    gp.setY(available.top() + 4)

            self.move(gp)
            self.show()
            self.raise_()
        except Exception:
            pass

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect().adjusted(1, 1, -2, -2)
        p.setBrush(QColor(0, 0, 0, 230))
        p.setPen(QPen(QColor(145, 140, 128, 235), 2))
        p.drawRoundedRect(r, 7, 7)

        p.end()
        super().paintEvent(ev)


class _ActiveBuffPreviewIcon(QFrame):
    def __init__(self, parent: "_ActiveBuffPreviewPanel", payload: dict, side: int):
        super().__init__(parent)

        self._panel = parent
        self._payload = dict(payload or {})
        self._hover = False
        self._side = max(1, int(side))

        pm = self._payload.get("IconPixmap")
        self._pm = QPixmap(pm) if isinstance(pm, QPixmap) and not pm.isNull() else QPixmap()

        self.setFixedSize(self._side, self._side)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")

    def enterEvent(self, ev) -> None:
        self._hover = True
        self.update()

        try:
            self._panel.show_item_tooltip(self, self._payload)
        except Exception:
            pass

        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:
        self._hover = False
        self.update()

        try:
            self._panel.hide_item_tooltip()
        except Exception:
            pass

        super().leaveEvent(ev)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        r = self.rect()

        if not self._pm.isNull():
            scaled = self._pm.scaled(
                r.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            draw_rect = QRect(0, 0, scaled.width(), scaled.height())
            draw_rect.moveCenter(r.center())
            p.drawPixmap(draw_rect.topLeft(), scaled)
        else:
            p.setBrush(QColor(0, 0, 0, 130))
            p.setPen(QPen(QColor(145, 140, 128, 180), 1))
            p.drawRoundedRect(r.adjusted(1, 1, -2, -2), 3, 3)

        if self._hover:
            p.setPen(QPen(QColor("#f2c45d"), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0, 0, -1, -1), 3, 3)

        p.end()


class _ActiveBuffPreviewPanel(QFrame):
    """
    Ряд иконок активных бафов/дебафов слева от кнопки MainWindow.
    Без фона: только иконки 21x21.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._owner: Optional[QWidget] = None
        self._items: list[dict] = []
        self._open_key: str = ""
        self._app_filter_installed = False

        self._icon_side = 21
        self._gap = 1
        self._pad = 0

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setStyleSheet("background: transparent; border: none;")

        self._tip = _ActiveBuffPreviewTooltip(None)

        self.hide()

    def set_owner(self, owner: QWidget) -> None:
        self._owner = owner

    def set_open_key(self, key: str) -> None:
        self._open_key = str(key or "")

    def set_items(self, items: list[dict], *, empty_text: str, max_width: int) -> None:
        self._items = [dict(x or {}) for x in (items or [])]

        for child in list(self.findChildren(_ActiveBuffPreviewIcon)):
            try:
                child.hide()
                child.setParent(None)
                child.deleteLater()
            except Exception:
                pass

        icon_side = int(self._icon_side)
        gap = int(self._gap)
        pad = int(self._pad)

        if not self._items:
            self.resize(1, 1)
            self.update()
            return

        max_width = max(icon_side, int(max_width or icon_side))

        max_cols = max(1, int((max_width - pad * 2 + gap) / (icon_side + gap)))
        cols = max(1, min(max_cols, len(self._items)))
        rows = max(1, int((len(self._items) + cols - 1) / cols))

        w = pad * 2 + cols * icon_side + max(0, cols - 1) * gap
        h = pad * 2 + rows * icon_side + max(0, rows - 1) * gap

        self.resize(int(w), int(h))

        for i, payload in enumerate(self._items):
            row = i // cols
            col = i % cols

            icon = _ActiveBuffPreviewIcon(self, payload, icon_side)
            x = pad + col * (icon_side + gap)
            y = pad + row * (icon_side + gap)

            icon.move(int(x), int(y))
            icon.show()
            icon.raise_()

        self.update()

    def show_item_tooltip(self, icon: QWidget, payload: dict) -> None:
        try:
            self._tip.set_payload(
                str((payload or {}).get("Name") or ""),
                str((payload or {}).get("BonusText") or ""),
            )
            self._tip.show_near_widget(icon)
        except Exception:
            pass

    def hide_item_tooltip(self) -> None:
        try:
            self._tip.hide()
        except Exception:
            pass

    def _install_app_filter(self) -> None:
        if self._app_filter_installed:
            return

        app = QApplication.instance()
        if app is None:
            return

        try:
            app.installEventFilter(self)
            self._app_filter_installed = True
        except Exception:
            self._app_filter_installed = False

    def _remove_app_filter(self) -> None:
        if not self._app_filter_installed:
            return

        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass

        self._app_filter_installed = False

    def _global_pos_from_event(self, ev) -> QPoint:
        try:
            return ev.globalPosition().toPoint()
        except Exception:
            pass

        try:
            return ev.globalPos()
        except Exception:
            pass

        return QCursor.pos()

    def _global_rect_for(self, w: QWidget) -> QRect:
        try:
            return QRect(w.mapToGlobal(QPoint(0, 0)), w.size())
        except Exception:
            return QRect()

    def _is_inside_preview_area(self, gp: QPoint) -> bool:
        if self._global_rect_for(self).contains(gp):
            return True

        owner = self._owner
        if owner is None:
            return False

        try:
            btns = getattr(owner, "_active_buff_preview_btns", {}) or {}
            for btn in btns.values():
                if isinstance(btn, QWidget) and btn.isVisible():
                    if self._global_rect_for(btn).contains(gp):
                        return True
        except Exception:
            pass

        return False

    def eventFilter(self, obj, ev) -> bool:
        if not self.isVisible():
            return False

        if ev.type() != QEvent.MouseButtonRelease:
            return False

        try:
            if ev.button() != Qt.LeftButton:
                return False
        except Exception:
            return False

        gp = self._global_pos_from_event(ev)
        if self._is_inside_preview_area(gp):
            return False

        owner = self._owner
        try:
            if owner is not None:
                fn = getattr(owner, "_close_active_buff_preview", None)
                if callable(fn):
                    fn()
                    ev.accept()
                    return True
        except Exception:
            pass

        self.hide()
        ev.accept()
        return True

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._install_app_filter()

    def hideEvent(self, ev) -> None:
        self.hide_item_tooltip()
        self._remove_app_filter()
        super().hideEvent(ev)

    def paintEvent(self, ev) -> None:
        # Фон специально не рисуем.
        super().paintEvent(ev)


class _InfoBoardMenu(QMenu):
    """
    QMenu в стиле инфо-борда:
    настоящий полупрозрачный чёрный фон, металлическая обводка,
    скругление и обычная логика QMenu.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)

        try:
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self.setWindowFlag(Qt.NoDropShadowWindowHint, True)
        except Exception:
            pass

        self.setStyleSheet(POPUP_MENU_STYLE)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect().adjusted(1, 1, -2, -2)

        # Реальная прозрачность, как у инфо-борда.
        p.setBrush(QColor(0, 0, 0, 230))
        p.setPen(QPen(QColor(145, 140, 128, 235), 2))
        p.drawRoundedRect(r, 7, 7)

        p.end()

        super().paintEvent(ev)


class _HelperControlWindow(QWidget):
    closed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(
            parent,
            Qt.Tool |
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint,
        )

        self.setObjectName("HelperControlWindow")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")

        self._drag_pos: Optional[QPoint] = None
        self._last_pos: Optional[QPoint] = None
        self._close_down: bool = False
        self._closed_emitted: bool = False

        bg_path = _resolve_resource(HELP_CONTROL_BG_PATH) or HELP_CONTROL_BG_PATH
        self._bg_pm = QPixmap(bg_path)

        if self._bg_pm.isNull():
            fw, fh = HELP_CONTROL_FALLBACK_SIZE
            self._bg_pm = QPixmap(int(fw), int(fh))
            self._bg_pm.fill(Qt.GlobalColor.transparent)

        self.setFixedSize(self._bg_pm.size())
        self._apply_window_mask_from_bg()

        self._bg = QLabel(self)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        self._bg.setPixmap(self._bg_pm)
        self._bg.setScaledContents(True)
        self._bg.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._bg.setStyleSheet("background: transparent;")
        self._bg.show()

        self._close_active_pm = QPixmap(
            _resolve_resource(HELP_CONTROL_CLOSE_ACTIVE_PATH) or HELP_CONTROL_CLOSE_ACTIVE_PATH
        )

        cx, cy, cw, ch = HELP_CONTROL_CLOSE_RECT
        self._close = QLabel(self)
        self._close.setGeometry(int(cx), int(cy), int(cw), int(ch))
        self._close.setAttribute(Qt.WA_TranslucentBackground, True)
        self._close.setAutoFillBackground(False)
        self._close.setStyleSheet("background: transparent; border: none;")
        self._close.setScaledContents(False)
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.installEventFilter(self)
        self._close.show()

        tx, ty, tw, th = HELP_CONTROL_TEXT_RECT
        self._area = QScrollArea(self)
        self._area.setGeometry(int(tx), int(ty), int(tw), int(th))
        self._area.setFrameShape(QFrame.NoFrame)
        self._area.setWidgetResizable(True)
        self._area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._area.setAttribute(Qt.WA_TranslucentBackground, True)
        self._area.setAutoFillBackground(False)

        try:
            self._area.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
            self._area.viewport().setAutoFillBackground(False)
            self._area.viewport().setStyleSheet("background: transparent;")
        except Exception:
            pass

        self._text_label = QLabel()
        self._text_label.setObjectName("helperControlText")
        self._text_label.setWordWrap(True)
        self._text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._text_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._text_label.setStyleSheet(f"""
            QLabel#helperControlText {{
                background: transparent;
                color: #f2f2f2;
                border: none;
                padding: 0px;
                font-weight: 600;
            }}
        """)
        self._area.setWidget(self._text_label)

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

        self.set_help_text(HELP_CONTROL_TEXT)

        self.installEventFilter(self)
        QTimer.singleShot(0, self._place_vscroll)

    def _apply_window_mask_from_bg(self) -> None:
        pm = getattr(self, "_bg_pm", None)
        if pm is None or pm.isNull():
            return

        try:
            img = pm.toImage()
            if not img.hasAlphaChannel():
                return

            mask_img = img.createAlphaMask()
            mask_bm = QBitmap.fromImage(mask_img, Qt.AutoColor)

            if mask_bm is not None and not mask_bm.isNull():
                self.setMask(mask_bm)
        except Exception:
            pass

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

    def set_help_text(self, text: str) -> None:
        text = str(text or "").strip()

        if not text:
            text = "Инструкция пока не заполнена."

        self._text_label.setText(text)

        try:
            view_w = max(1, int(self._area.viewport().width()) - 4)
            self._text_label.setFixedWidth(view_w)
            self._text_label.adjustSize()
        except Exception:
            pass

        QTimer.singleShot(0, self._place_vscroll)

    def open_centered(self, parent: Optional[QWidget] = None) -> None:
        host = parent if isinstance(parent, QWidget) else self.parentWidget()

        if self._last_pos is not None:
            self.move(self._last_pos)
        else:
            try:
                if host is not None:
                    hg = host.frameGeometry()
                    x = hg.x() + (hg.width() - self.width()) // 2
                    y = hg.y() + (hg.height() - self.height()) // 2
                else:
                    scr = QApplication.primaryScreen().availableGeometry()
                    x = scr.x() + (scr.width() - self.width()) // 2
                    y = scr.y() + (scr.height() - self.height()) // 2

                self.move(int(x), int(y))
            except Exception:
                pass

        self.show()
        self.raise_()
        self.activateWindow()

        QTimer.singleShot(0, self._place_vscroll)
        QTimer.singleShot(0, self._sync_scrollbar_visible)

    def _place_vscroll(self) -> None:
        if self._sv_custom is None:
            return

        try:
            x, y, w, h = HELP_CONTROL_SCROLL_RECT
            self._sv_custom.setGeometry(int(x), int(y), int(w), int(h))
            self._sync_scrollbar_visible()
        except Exception:
            pass

    def _sync_scrollbar_visible(self) -> None:
        if self._sv_custom is None:
            return

        try:
            vb = self._area.verticalScrollBar()
            self._sv_custom.setVisible(vb.maximum() > 0)
            if vb.maximum() > 0:
                self._sv_custom.raise_()
        except Exception:
            pass

    def _is_over_widget(self, w: QWidget, ev) -> bool:
        try:
            gp = ev.globalPosition().toPoint()
        except Exception:
            try:
                gp = ev.globalPos()
            except Exception:
                return False

        try:
            lp = w.mapFromGlobal(gp)
        except Exception:
            return False

        return w.rect().contains(lp)

    def eventFilter(self, obj, ev) -> bool:
        if obj is self._close:
            et = ev.type()

            if et == QEvent.Enter:
                if not self._close_active_pm.isNull():
                    self._set_close_pixmap(self._close_active_pm)
                return False

            if et == QEvent.Leave:
                if not self._close_down:
                    self._set_close_pixmap(None)
                return False

            if et == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
                self._close_down = True
                if not self._close_active_pm.isNull():
                    self._set_close_pixmap(self._close_active_pm)
                ev.accept()
                return True

            if et == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
                was_down = bool(self._close_down)
                self._close_down = False

                over = self._is_over_widget(self._close, ev)

                if not over:
                    self._set_close_pixmap(None)

                if was_down and over:
                    self.close()

                ev.accept()
                return True

            return False

        return super().eventFilter(obj, ev)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            try:
                gp = ev.globalPosition().toPoint()
            except Exception:
                try:
                    gp = ev.globalPos()
                except Exception:
                    gp = QCursor.pos()

            self._drag_pos = gp - self.frameGeometry().topLeft()
            ev.accept()
            return

        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        if self._drag_pos and (ev.buttons() & Qt.LeftButton):
            try:
                gp = ev.globalPosition().toPoint()
            except Exception:
                try:
                    gp = ev.globalPos()
                except Exception:
                    gp = QCursor.pos()

            self.move(gp - self._drag_pos)
            ev.accept()
            return

        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._drag_pos = None

            try:
                self._last_pos = QPoint(self.frameGeometry().topLeft())
            except Exception:
                try:
                    self._last_pos = QPoint(self.pos())
                except Exception:
                    pass

            ev.accept()
            return

        super().mouseReleaseEvent(ev)

    def closeEvent(self, ev) -> None:
        try:
            self._last_pos = QPoint(self.frameGeometry().topLeft())
        except Exception:
            try:
                self._last_pos = QPoint(self.pos())
            except Exception:
                pass

        try:
            self._set_close_pixmap(None)
        except Exception:
            pass

        self._close_down = False

        super().closeEvent(ev)

        if not self._closed_emitted:
            self._closed_emitted = True
            try:
                self.closed.emit()
            except Exception:
                pass

        QTimer.singleShot(0, self._reset_closed_flag)

    def _reset_closed_flag(self) -> None:
        self._closed_emitted = False


class ClassThumb(QToolButton):
    """Мини-кнопка класса для меню выбора класса."""

    def __init__(
            self,
            class_id: int,
            name: str,
            icon_pm: Optional[QPixmap],
            size_px: int = 48,
            parent=None,
    ):
        super().__init__(parent)

        self._id = int(class_id)
        self.setToolTip(str(name or ""))
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

        self.setIconSize(QSize(int(size_px), int(size_px)))
        self.setFixedSize(int(size_px) + 8, int(size_px) + 8)

        if icon_pm is not None and not icon_pm.isNull():
            self.setIcon(QIcon(icon_pm))

        self.setStyleSheet(CLASS_THUMB_STYLE)

class InvisibleSpin(QSpinBox):
    """Невидимый спинбокс — только держатель значения уровня (без любого пользовательского ввода)."""

    def textFromValue(self, _: int) -> str:
        return ""

    def focusInEvent(self, e):
        # не даём получать фокус (чтобы не было ввода/каретки)
        try:
            self.clearFocus()
        except Exception:
            pass
        e.accept()

    def mousePressEvent(self, e):
        # полностью глотаем клики
        e.accept()

    def mouseReleaseEvent(self, e):
        e.accept()

    def mouseDoubleClickEvent(self, e):
        e.accept()

    def wheelEvent(self, e):
        # запрещаем менять уровень колесом на самом spin (крутить можно только через LevelWheel)
        e.accept()

    def keyPressEvent(self, e):
        # запрещаем любые клавиши (стрелки, цифры и т.п.)
        e.accept()

    def contextMenuEvent(self, e):
        e.accept()


class _InputShield(QWidget):
    """Прозрачная накладка, которая глотает ВСЕ вводные события,
    включая Wheel и Drag&Drop, чтобы события не проваливались в нижние виджеты.
    """
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("InputShield")

        # Щит должен получать мышь, включая wheel.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        # Чтобы ловить Drag&Drop.
        self.setAcceptDrops(True)

        # Ничего не рисуем и не даём фону вмешиваться.
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)

        self.setGeometry(parent.rect())
        self.show()
        self.raise_()

    def sync_geometry(self) -> None:
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(p.rect())

    def _eat(self, e) -> bool:
        try:
            e.accept()
        except Exception:
            pass
        return True

    # ---- Wheel: обязательно блокируем отдельно ----
    def wheelEvent(self, e) -> None:
        self._eat(e)

    # ---- Mouse ----
    def mousePressEvent(self, e) -> None:
        self._eat(e)

    def mouseReleaseEvent(self, e) -> None:
        self._eat(e)

    def mouseDoubleClickEvent(self, e) -> None:
        self._eat(e)

    def mouseMoveEvent(self, e) -> None:
        self._eat(e)

    def contextMenuEvent(self, e) -> None:
        self._eat(e)

    # ---- Drag & Drop: блокируем, но не даём провалиться вниз ----
    def dragEnterEvent(self, e) -> None:
        try:
            e.setDropAction(Qt.IgnoreAction)
        except Exception:
            pass
        self._eat(e)

    def dragMoveEvent(self, e) -> None:
        try:
            e.setDropAction(Qt.IgnoreAction)
        except Exception:
            pass
        self._eat(e)

    def dragLeaveEvent(self, e) -> None:
        self._eat(e)

    def dropEvent(self, e) -> None:
        try:
            e.setDropAction(Qt.IgnoreAction)
        except Exception:
            pass
        self._eat(e)

    # ---- Остальные события тоже глотаем ----
    def event(self, e: QEvent) -> bool:
        et = e.type()

        if et in (
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseButtonDblClick,
            QEvent.MouseMove,
            QEvent.Wheel,
            QEvent.ContextMenu,
            QEvent.DragEnter,
            QEvent.DragMove,
            QEvent.DragLeave,
            QEvent.Drop,
            QEvent.KeyPress,
            QEvent.KeyRelease,
        ):
            return self._eat(e)

        return super().event(e)


class _MainModalInputBlocker(QObject):
    """
    Глобальный фильтр ввода для всех модальных/полумодальных меню.

    Исправляет проблему прозрачных top-level окон:
    если меню имеет прозрачные области или setMask(), Qt может отправить событие
    в MainWindow под ним. Этот фильтр ловит такие события на уровне QApplication.
    """
    INPUT_EVENT_TYPES = {
        QEvent.MouseButtonPress,
        QEvent.MouseButtonRelease,
        QEvent.MouseButtonDblClick,
        QEvent.MouseMove,
        QEvent.Wheel,
        QEvent.ContextMenu,
        QEvent.DragEnter,
        QEvent.DragMove,
        QEvent.DragLeave,
        QEvent.Drop,
        QEvent.KeyPress,
        QEvent.KeyRelease,
    }

    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self._owner = owner

    def _eat(self, ev, reason: str = "") -> bool:
        try:
            ev.accept()
        except Exception:
            pass
        return True

    def _global_pos(self, ev) -> QPoint:
        try:
            return ev.globalPosition().toPoint()
        except Exception:
            pass

        try:
            return ev.globalPos()
        except Exception:
            pass

        try:
            return QCursor.pos()
        except Exception:
            return QPoint(0, 0)

    def _is_descendant_obj(self, obj: object, root: Optional[object]) -> bool:
        if obj is None or root is None:
            return False

        try:
            cur = obj
            seen: set[int] = set()

            while cur is not None and id(cur) not in seen:
                seen.add(id(cur))

                if cur is root:
                    return True

                if isinstance(cur, QWidget):
                    try:
                        pw = cur.parentWidget()
                    except Exception:
                        pw = None

                    if pw is not None:
                        cur = pw
                        continue

                try:
                    cur = cur.parent() if hasattr(cur, "parent") else None
                except Exception:
                    cur = None
        except Exception:
            return False

        return False

    def _widget_global_rect(self, w: QWidget) -> QRect:
        if not isinstance(w, QWidget):
            return QRect()

        try:
            if w.isWindow():
                return QRect(w.frameGeometry())
        except Exception:
            pass

        try:
            return QRect(w.mapToGlobal(QPoint(0, 0)), w.size())
        except Exception:
            return QRect()

    def _is_visible_widget(self, w: object) -> bool:
        if not isinstance(w, QWidget):
            return False

        owner = self._owner

        if w is owner:
            return False

        try:
            if not w.isVisible():
                return False
        except Exception:
            return False

        try:
            if w.width() <= 0 or w.height() <= 0:
                return False
        except Exception:
            return False

        try:
            if w.windowType() == Qt.ToolTip:
                return False
        except Exception:
            pass

        return True

    def _append_root(self, out: list[QWidget], seen: set[int], w: object) -> None:
        if not isinstance(w, QWidget):
            return

        if not self._is_visible_widget(w):
            return

        if id(w) not in seen:
            seen.add(id(w))
            out.append(w)

        # Для wrapper-окон вроде AuraMenuWindow / BuffDebuffMenuWindow,
        # где реальное меню может лежать в .menu.
        try:
            inner = getattr(w, "menu", None)
        except Exception:
            inner = None

        if isinstance(inner, QWidget) and self._is_visible_widget(inner):
            if id(inner) not in seen:
                seen.add(id(inner))
                out.append(inner)

        # Если это дочерний widget, но его window() — отдельное top-level окно,
        # добавим и window().
        try:
            ww = w.window()
        except Exception:
            ww = None

        if isinstance(ww, QWidget) and ww is not w and self._is_visible_widget(ww):
            if id(ww) not in seen:
                seen.add(id(ww))
                out.append(ww)

    def _allowed_roots(self) -> list[QWidget]:
        """
        Окна, внутри которых ввод должен работать.
        Все остальные события под ними/рядом с ними должны блокировать MainWindow.
        """
        owner = self._owner
        out: list[QWidget] = []
        seen: set[int] = set()

        try:
            self._append_root(out, seen, getattr(owner, "_block_allow_root", None))
        except Exception:
            pass

        names = (
            # окна, которые реально должны перекрывать MainWindow
            "stamp_window",
            "cards_window",
            "upgrade_win",

            "_talents_menu_window",
            "_guild_menu_window",
            "_aura_menu_window",
            "_buff_debuff_menu_window",
            "_collection_window",

            "_total_menu_window",
            "_save_load_manager_window",
            "_update_info_window",
            "_update_check_window",
            "_update_result_window",

            # выборы эликсиров/расходников
            "_elixir_menu",
            "_consumble_menu",
            "_player_elixir_menu",
            "_player_consumble_menu",
        )

        for name in names:
            try:
                self._append_root(out, seen, getattr(owner, name, None))
            except Exception:
                pass

        return out

    def _active_shields(self) -> list[QWidget]:
        owner = self._owner
        out: list[QWidget] = []

        for name in ("_stamp_shield", "_reforge_shield", "_inv_shield"):
            try:
                sh = getattr(owner, name, None)
            except Exception:
                sh = None

            if isinstance(sh, QWidget):
                try:
                    if sh.isVisible():
                        out.append(sh)
                except Exception:
                    pass

        return out

    def _target_widget(self, obj, gp: QPoint) -> Optional[QWidget]:
        if isinstance(obj, QWidget):
            return obj

        try:
            w = QApplication.widgetAt(gp)
            if isinstance(w, QWidget):
                return w
        except Exception:
            pass

        return None

    def _scroll_area_can_scroll(self, area: QAbstractScrollArea, ev) -> bool:
        try:
            ad = ev.angleDelta()
            dx = int(ad.x())
            dy = int(ad.y())
        except Exception:
            dx = 0
            dy = 0

        try:
            pd = ev.pixelDelta()
            if dx == 0:
                dx = int(pd.x())
            if dy == 0:
                dy = int(pd.y())
        except Exception:
            pass

        try:
            vb = area.verticalScrollBar()
            hb = area.horizontalScrollBar()
        except Exception:
            return False

        if dy != 0:
            try:
                return bool(vb is not None and vb.maximum() > vb.minimum())
            except Exception:
                return False

        if dx != 0:
            try:
                return bool(hb is not None and hb.maximum() > hb.minimum())
            except Exception:
                return False

        try:
            return bool(
                (vb is not None and vb.maximum() > vb.minimum())
                or (hb is not None and hb.maximum() > hb.minimum())
            )
        except Exception:
            return False

    def _is_real_wheel_receiver(self, target: Optional[QWidget], root: QWidget, ev) -> bool:
        """
        True только если колесо реально должно остаться внутри меню:
        QScrollArea/QListWidget/QScrollBar/QComboBox или кастомный Python-widget
        с собственным wheelEvent.
        """
        if target is None:
            return False

        try:
            cur = target
            seen: set[int] = set()

            while cur is not None and id(cur) not in seen:
                seen.add(id(cur))

                if isinstance(cur, QScrollBar):
                    return True

                if isinstance(cur, QAbstractScrollArea):
                    return self._scroll_area_can_scroll(cur, ev)

                if isinstance(cur, QComboBox):
                    return True

                # Кастомные виджеты проекта, где wheelEvent написан вручную
                # например элементы аур/расходников с прокруткой текста.
                try:
                    if "wheelEvent" in getattr(type(cur), "__dict__", {}):
                        return True
                except Exception:
                    pass

                if cur is root:
                    break

                try:
                    nxt = cur.parentWidget()
                except Exception:
                    nxt = None

                if nxt is not None:
                    cur = nxt
                    continue

                try:
                    cur = cur.parent() if hasattr(cur, "parent") else None
                except Exception:
                    cur = None
        except Exception:
            return False

        return False

    def _is_blocking_active(self, roots: list[QWidget]) -> bool:
        owner = self._owner

        try:
            if bool(getattr(owner, "_block_main_input", False)):
                return True
        except Exception:
            pass

        try:
            if bool(getattr(owner, "_stamp_shield", None)) and owner._stamp_shield.isVisible():
                return True
        except Exception:
            pass

        try:
            if bool(getattr(owner, "_reforge_shield", None)) and owner._reforge_shield.isVisible():
                return True
        except Exception:
            pass

        try:
            if bool(getattr(owner, "_inv_shield", None)) and owner._inv_shield.isVisible():
                return True
        except Exception:
            pass

        return bool(roots)

    def eventFilter(self, obj, ev) -> bool:
        et = ev.type()

        if et not in self.INPUT_EVENT_TYPES:
            return False

        owner = self._owner
        roots = self._allowed_roots()

        if not self._is_blocking_active(roots):
            return False

        gp = self._global_pos(ev)
        target = self._target_widget(obj, gp)

        # 1) Внутри разрешённого окна клики/клавиши проходят.
        # Колесо — только если оно реально обрабатывается меню.
        for root in roots:
            if target is not None and self._is_descendant_obj(target, root):
                if et == QEvent.Wheel:
                    if self._is_real_wheel_receiver(target, root, ev):
                        return False
                    return self._eat(ev, "wheel_inside_non_scroll_menu")

                return False

        # 2) Если курсор геометрически над окном меню,
        # но событие прилетело НЕ в это меню — значит это прозрачная область/mask.
        # Съедаем, чтобы не провалилось в MainWindow.
        for root in roots:
            try:
                gr = self._widget_global_rect(root)
                if not gr.isEmpty() and gr.contains(gp):
                    return self._eat(ev, f"over_allowed_root:{type(root).__name__}")
            except Exception:
                pass

        # 3) Событие в сам shield — съедаем.
        for sh in self._active_shields():
            if target is not None and self._is_descendant_obj(target, sh):
                return self._eat(ev, "target_is_shield")

            try:
                gr = self._widget_global_rect(sh)
                if not gr.isEmpty() and gr.contains(gp):
                    return self._eat(ev, "over_shield")
            except Exception:
                pass

        # 4) Если событие попало в MainWindow или его детей — съедаем.
        if target is not None and self._is_descendant_obj(target, owner):
            return self._eat(ev, f"target_in_main:{type(target).__name__}")

        try:
            owner_rect = self._widget_global_rect(owner)
            if not owner_rect.isEmpty() and owner_rect.contains(gp):
                return self._eat(ev, "over_main_rect")
        except Exception:
            pass

        # 5) Если открыт shield инвентаря — блокируем и InventoryWindow.
        inv = getattr(owner, "inventory_window", None)
        inv_sh = getattr(owner, "_inv_shield", None)

        try:
            inv_blocked = bool(inv is not None and inv_sh is not None and inv_sh.isVisible())
        except Exception:
            inv_blocked = False

        if inv_blocked and isinstance(inv, QWidget):
            if target is not None and self._is_descendant_obj(target, inv):
                return self._eat(ev, f"target_in_inventory:{type(target).__name__}")

            try:
                inv_rect = self._widget_global_rect(inv)
                if not inv_rect.isEmpty() and inv_rect.contains(gp):
                    return self._eat(ev, "over_inventory_rect")
            except Exception:
                pass

        return False

@dataclass(frozen=True)
class EquipSlotMeta:
    id: int
    name: str
    state_id: int | None
    extra_slot_id: int | None
    count: int
    is_weapon: bool

class _UpdateInfoBoardWindow(QFrame):
    cancelled = Signal()
    updateRequested = Signal(object)
    statusChanged = Signal(str)
    checkFinished = Signal(object)
    downloadFinished = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._result: Optional[UpdateCheckResult] = None
        self._closing_silent = False

        self.setObjectName("UpdateInfoBoardWindow")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")
        self.setFixedSize(430, 210)
        self.hide()

        self._title = QLabel(self)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setWordWrap(True)
        self._title.setStyleSheet(
            "background: transparent;"
            "color: #f2c45d;"
            "font-size: 15px;"
            "font-weight: 800;"
            "border: none;"
        )

        self._body = QLabel(self)
        self._body.setAlignment(Qt.AlignCenter)
        self._body.setWordWrap(True)
        self._body.setStyleSheet(
            "background: transparent;"
            "color: #f2f2f2;"
            "font-size: 12px;"
            "font-weight: 600;"
            "border: none;"
        )

        self.btn_update = QPushButton("Обновить", self)
        self.btn_cancel = QPushButton("Отмена", self)

        for btn in (self.btn_update, self.btn_cancel):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(20, 20, 20, 230);
                    color: #f2c45d;
                    border: 2px solid rgba(145, 140, 128, 235);
                    border-radius: 7px;
                    padding: 6px 14px;
                    font-weight: 800;
                }
                QPushButton:hover {
                    color: #fff0b0;
                    border-color: #f2c45d;
                    background-color: rgba(55, 55, 55, 235);
                }
                QPushButton:pressed {
                    color: #ffffff;
                    background-color: rgba(85, 75, 55, 240);
                }
                QPushButton:disabled {
                    color: rgba(190, 190, 190, 120);
                    border-color: rgba(120, 120, 120, 120);
                    background-color: rgba(20, 20, 20, 150);
                }
            """)

        self.btn_update.clicked.connect(self._on_update_clicked)
        self.btn_cancel.clicked.connect(self.close)

        self.statusChanged.connect(self.set_status_text)
        self.checkFinished.connect(self.set_check_result)
        self.downloadFinished.connect(self.set_download_result)

        self._apply_layout()

    def _apply_layout(self) -> None:
        margin_x = 24

        self._title.setGeometry(margin_x, 20, self.width() - margin_x * 2, 36)
        self._body.setGeometry(margin_x, 62, self.width() - margin_x * 2, 82)

        btn_w = 122
        btn_h = 34
        gap = 16
        y = self.height() - 52

        total_w = btn_w * 2 + gap
        x0 = (self.width() - total_w) // 2

        self.btn_update.setGeometry(x0, y, btn_w, btn_h)
        self.btn_cancel.setGeometry(x0 + btn_w + gap, y, btn_w, btn_h)

    def set_checking(self) -> None:
        self._result = None
        self._title.setText("Проверка обновлений")
        self._body.setText("Получаю информацию о доступных обновлениях...")

        self.btn_update.hide()
        self.btn_cancel.show()
        self.btn_cancel.setText("Отмена")
        self.btn_cancel.setEnabled(True)

        btn_w = 122
        btn_h = 34
        y = self.height() - 52
        x = (self.width() - btn_w) // 2

        self.btn_cancel.setGeometry(int(x), int(y), int(btn_w), int(btn_h))
        self.btn_cancel.raise_()

    def set_status_text(self, text: str) -> None:
        self._body.setText(str(text or ""))

    def set_check_result(self, result: object) -> None:
        if not isinstance(result, UpdateCheckResult):
            self._title.setText("Ошибка проверки")
            self._body.setText("Не удалось обработать результат проверки обновлений.")
            self._show_cancel_only()
            return

        self._result = result

        if not result.ok:
            self._title.setText("Ошибка проверки")
            self._body.setText(result.error or "Не удалось проверить обновления.")
            self._show_cancel_only()
            return

        if not result.update_available:
            self._title.setText("Обновлений не найдено")
            self._body.setText("У Вас уже установлена актуальная версия калькулятора.")
            self._show_cancel_only()
            return

        comps = []
        for comp in result.components_to_update:
            if comp.name == "app":
                comps.append("программа")
            elif comp.name == "resources":
                comps.append("ресурсы")
            elif comp.name == "database":
                comps.append("база данных")
            else:
                comps.append(comp.name)

        comps_text = ", ".join(comps) if comps else "компоненты"

        self._title.setText("Найдено обновление")
        self._body.setText(
            f"Доступна версия: {result.remote_version}\n"
            f"Будет обновлено: {comps_text}\n\n"
            f"{result.notes or ''}"
        )

        self.btn_update.show()
        self.btn_update.setEnabled(True)
        self.btn_cancel.setText("Отмена")
        self.btn_cancel.setEnabled(True)

        self._apply_layout()

    def set_downloading(self) -> None:
        self._title.setText("Обновление")
        self._body.setText("Подготовка загрузки...")
        self.btn_update.setEnabled(False)
        self.btn_cancel.setEnabled(False)

    def set_download_result(self, payload: object) -> None:
        if isinstance(payload, dict) and payload.get("ok"):
            self._title.setText("Обновление загружено")
            self._body.setText("Калькулятор будет перезапущен для установки обновления.")
            self.btn_update.hide()
            self.btn_cancel.hide()
            return

        err = ""
        if isinstance(payload, dict):
            err = str(payload.get("error") or "")

        self._title.setText("Ошибка обновления")
        self._body.setText(err or "Не удалось скачать или установить обновление.")
        self._show_cancel_only()

    def _show_cancel_only(self) -> None:
        self.btn_update.hide()
        self.btn_cancel.show()
        self.btn_cancel.setText("Отмена")
        self.btn_cancel.setEnabled(True)

        btn_w = 122
        btn_h = 34
        y = self.height() - 52
        x = (self.width() - btn_w) // 2

        self.btn_cancel.setGeometry(int(x), int(y), int(btn_w), int(btn_h))
        self.btn_cancel.raise_()

    def _on_update_clicked(self) -> None:
        if self._result is None:
            return

        self.updateRequested.emit(self._result)

    def open_centered(self, owner: QWidget) -> None:
        """
        Открывает окно проверки обновлений по центру MainWindow.

        ВАЖНО:
        _UpdateInfoBoardWindow является ДОЧЕРНИМ виджетом MainWindow,
        поэтому move() должен получать локальные координаты родителя,
        а не глобальные координаты экрана.

        Старая версия брала owner.mapToGlobal(...), из-за чего окно уезжало
        вниз/вправо, обрезалось границами MainWindow, и кнопки становились
        недоступны.
        """
        if owner is None:
            return

        # На всякий случай гарантируем, что окно остаётся дочерним для MainWindow.
        try:
            if self.parentWidget() is not owner:
                self.setParent(owner)
        except Exception:
            pass

        # Берём область картинки внутри MainWindow в ЛОКАЛЬНЫХ координатах.
        try:
            anchor = owner._img_rect() if hasattr(owner, "_img_rect") else owner.rect()
        except Exception:
            anchor = owner.rect()

        if not isinstance(anchor, QRect) or anchor.isEmpty():
            try:
                anchor = owner.rect()
            except Exception:
                anchor = QRect(0, 0, 851, 657)

        # Центрируем внутри anchor, но всё ещё в координатах owner.
        x = int(anchor.x() + (anchor.width() - self.width()) / 2)
        y = int(anchor.y() + (anchor.height() - self.height()) / 2)

        # Не даём окну вылезти за видимую область MainWindow.
        try:
            bounds = owner.rect()
            pad = 8

            x = max(bounds.left() + pad, min(x, bounds.right() - self.width() - pad))
            y = max(bounds.top() + pad, min(y, bounds.bottom() - self.height() - pad))
        except Exception:
            pass

        self.move(int(x), int(y))
        self.show()
        self.raise_()

        try:
            self.activateWindow()
        except Exception:
            pass

    def close_silent(self) -> None:
        self._closing_silent = True
        self.close()

    def closeEvent(self, ev) -> None:
        super().closeEvent(ev)

        if not self._closing_silent:
            try:
                self.cancelled.emit()
            except Exception:
                pass

        self._closing_silent = False

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        r = self.rect().adjusted(1, 1, -2, -2)

        p.setBrush(QColor(0, 0, 0, 232))
        p.setPen(QPen(QColor(145, 140, 128, 235), 2))
        p.drawRoundedRect(r, 9, 9)

        p.end()

        super().paintEvent(ev)

# =========================
# MAIN WINDOW
# =========================
class MainWindow(QWidget):
    def __init__(self, data: DataAccess):
        super().__init__()
        self._hover_tip_connected = None
        self.data = data

        # =====================================================================
        # ВАЖНО: поля состояния должны существовать ДО installEventFilter()
        #        и ДО создания дочерних окон (UpgradeWindow и т.п.),
        #        потому что eventFilter может вызваться во время __init__.
        # =====================================================================
        self._zones_screen: List[Tuple[str, QRect]] = []
        self._selected_items: Dict[str, Dict] = {}
        self._suppress_stamp_equipped: set[int] = set()
        self._equip_via_menu: bool = False
        self._equip_from_inventory: bool = False
        self._mask_stamp_slots: set[str] = set()
        self._applied_stamps: Dict[str, Dict] = {}

        self._slot_icons: Dict[str, QLabel] = {}

        # щиты/блокировки (чтобы eventFilter тоже не падал)
        self._stamp_shield = None
        self._inv_shield = None  # type: Optional[_InputShield]
        self._reforge_shield = None  # type: Optional[_InputShield]
        self._block_main_input = False
        self._block_allow_root: QWidget | None = None
        self._pending_inventory_prune = False

        # ===== DB-driven equipment slots registry =====
        self._slot_meta_by_id: Dict[int, EquipSlotMeta] = {}
        self._slot_meta_by_name: Dict[str, EquipSlotMeta] = {}
        self._ui_slot_to_db_slot_id: Dict[str, int] = {}
        self._db_slot_to_ui_keys: Dict[int, List[str]] = {}
        self._etype_meta_cache: Dict[int, dict] = {}
        self._weapon_slot_with_extra = None  # <-- добавить
        self._init_equipment_slot_registry()

        # ===== кеши классов (Class) =====
        self._class_row_cache: Dict[int, dict] = {}
        self._class_effective_cache: Dict[int, dict] = {}
        self._class_lineage_cache: Dict[int, List[int]] = {}
        self._slot_allowed_ids_cache: Dict[Tuple[int, int], set[int]] = {}  # (slot_id, class_id) -> {equip_ids}

        # --- кеши ---
        self._image_cache: Dict[int, QPixmap] = {}
        self._etype_name_cache: Dict[int, str] = {}
        self._stamp_color_cache: Dict[int, Dict] = {}

        self.setWindowTitle("IsItCalc — Main UI")

        # ===== локальные хелперы =====
        def uconnect(signal, slot):
            """Подключить сигнал с попыткой UniqueConnection, с безопасным фолбэком."""
            try:
                signal.connect(slot, Qt.ConnectionType.UniqueConnection)
            except Exception:
                signal.connect(slot)

        def mk_tbtn(parent, name: str | None = None, cursor=Qt.PointingHandCursor,
                    autoraise=True, stylesheet: str | None = None) -> QToolButton:
            btn = QToolButton(parent)
            if name:
                btn.setObjectName(name)

            btn.setCursor(cursor)
            btn.setAutoRaise(autoraise)

            # ВАЖНО:
            # кнопки в этом UI не должны получать клавиатурный фокус.
            # Иначе Tab выбирает случайную кнопку, а Space/Enter активируют её.
            btn.setFocusPolicy(Qt.NoFocus)

            if stylesheet:
                btn.setStyleSheet(stylesheet)

            return btn

        # ===== базовые поля =====
        self._base_w = 851
        self._base_h = 657
        self._drag_pos: Optional[QPoint] = None

        # ===== системные кнопки =====
        _WINDOW_BTN_STYLE = """
            QToolButton { background: transparent; border: none; padding: 0; }
            QToolButton:hover { background: transparent; }
        """
        self.close_btn = mk_tbtn(self, "closeBtn", stylesheet=_WINDOW_BTN_STYLE)
        uconnect(self.close_btn.clicked, self.close)

        self.minimize_btn = mk_tbtn(self, "minimizeBtn", stylesheet=_WINDOW_BTN_STYLE)
        uconnect(self.minimize_btn.clicked, self.showMinimized)

        # ===== окно/фон =====
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.CustomizeWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)  # прозрачный бэк
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)  # как в твоём коде
        self.setStyleSheet("background: transparent;")

        # ===== уровень персонажа =====
        self._max_level_cap = _safe_int(self.data.get_max_character_level(), 1)
        self.level_spin = InvisibleSpin(self)
        self.level_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.level_spin.setAlignment(Qt.AlignCenter)
        self.level_spin.setRange(1, self._max_level_cap)
        self.level_spin.setValue(1)
        self.level_spin.setStyleSheet(
            """
            QAbstractSpinBox, QSpinBox {
                background: rgba(0,0,0,0);
                color: rgba(0,0,0,0);
                border: none;
                selection-background-color: rgba(0,0,0,0);
                selection-color: rgba(0,0,0,0);
            }
            """
        )
        self.level_spin.setFixedSize(81, 25)  # width можно любой, важнее height
        uconnect(self.level_spin.valueChanged, self._on_level_changed)

        sprite_path = _resolve_resource("resources/main_menu/counter_numbers0-9.png") or \
                      "resources/main_menu/counter_numbers0-9.png"
        self.level_wheel = LevelWheel(self.level_spin, sprite_path, parent=self)
        self.level_wheel.raise_()
        self.level_wheel.show()

        # ===== очки параметров (StatsPerLevel) =====
        self.param_points = ParamAllocationState(self.data.conn)
        self.unspent_points_widget = UnspentParamPointsWidget(self)
        self.unspent_points_widget.hide()

        try:
            self.param_points.unspentChanged.connect(self._on_unspent_changed, Qt.ConnectionType.UniqueConnection)
        except Exception:
            self.param_points.unspentChanged.connect(self._on_unspent_changed)

        self.param_points.set_level(int(self.level_spin.value()))

        # ===== борда / фон =====
        self.board_label = QLabel(self)
        self.board_label.setAlignment(Qt.AlignCenter)
        self.board_label.setScaledContents(False)
        self.board_label.setStyleSheet("background: transparent;")
        self.board_label.setAttribute(Qt.WA_TranslucentBackground, True)
        self.board_label.setAutoFillBackground(False)
        self.board_label.setMouseTracking(True)

        def _board_label_mouse_press(ev):
            if ev.button() != Qt.LeftButton:
                return QLabel.mousePressEvent(self.board_label, ev)

            try:
                gp = ev.globalPosition().toPoint()
            except Exception:
                try:
                    gp = ev.globalPos()
                except Exception:
                    gp = QCursor.pos()

            self._drag_pos = gp - self.frameGeometry().topLeft()
            ev.accept()

        def _board_label_mouse_move(ev):
            if self._drag_pos and (ev.buttons() & Qt.LeftButton):
                try:
                    gp = ev.globalPosition().toPoint()
                except Exception:
                    try:
                        gp = ev.globalPos()
                    except Exception:
                        gp = QCursor.pos()

                self.move(gp - self._drag_pos)
                ev.accept()
                return

            QLabel.mouseMoveEvent(self.board_label, ev)

        def _board_label_mouse_release(ev):
            if ev.button() == Qt.LeftButton:
                self._drag_pos = None
                ev.accept()
                return

            QLabel.mouseReleaseEvent(self.board_label, ev)

        self.board_label.mousePressEvent = _board_label_mouse_press  # type: ignore[assignment]
        self.board_label.mouseMoveEvent = _board_label_mouse_move  # type: ignore[assignment]
        self.board_label.mouseReleaseEvent = _board_label_mouse_release  # type: ignore[assignment]

        # ВАЖНО:
        # EquipmentInfoWindow должен быть настоящим top-level tooltip-окном.
        # Если оставить parent=self, на Linux move(global_pos) может трактоваться
        # как позиция относительно MainWindow, из-за чего анкета уезжает вправо/вниз.
        self.equip_info = EquipmentInfoWindow(None)

        # Но контекст главного окна всё равно сохраняем,
        # чтобы анкета могла брать data.conn, уровень персонажа и прочие данные.
        self.equip_info.main_window = self
        self.equip_info._ctx_root = self

        # Так как parent=None, вручную удаляем анкету при уничтожении MainWindow.
        try:
            self.destroyed.connect(self.equip_info.deleteLater)
        except Exception:
            pass

        self._bg_default = _load_file_image(MAIN_BG_PATH_DEFAULT)
        self._bg_spear = _load_file_image(MAIN_BG_PATH_SPEAR)
        self._bg_current: Optional[QPixmap] = self._bg_default or self._bg_spear
        self._update_design_base_from_original()

        # ===== классы =====
        self._classes: List[Tuple[int, str, Optional[QPixmap]]] = [
            (cid, cname, _load_db_image(data, img_id)) for cid, cname, img_id in data.list_classes()
        ]

        self.class_combo = QComboBox(self)  # <-- создаём ОДИН раз, сразу с parent
        for cid, cname, _ in self._classes:
            self.class_combo.addItem(cname, cid)

        if self.class_combo.count() > 0:
            self.class_combo.setCurrentIndex(0)

        uconnect(self.class_combo.currentIndexChanged, self._on_class_combo_changed)
        self.class_combo.hide()

        # ===== силуэт =====
        self.silhouette_label = QLabel(self)
        self.silhouette_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.silhouette_label.setAttribute(Qt.WA_TranslucentBackground, True)
        self.silhouette_label.setAutoFillBackground(False)
        self.silhouette_label.setStyleSheet("background: transparent;")
        self._sil_pm_m = _load_db_image(self.data, IMG["silhouette_m"])
        self._sil_pm_f = _load_db_image(self.data, IMG["silhouette_f"])
        self._gender = 1
        self._sil_original = self._sil_pm_m

        # ===== контроллеры экипировки =====
        get_gender_id = lambda: (1 if self._gender == 1 else 2)
        get_level = lambda: int(self.level_spin.value())

        self.eq_ctrls = make_equipment_controllers(
            parent=self,
            data=self.data,
            on_pick=self._on_pick_equipment,
            on_clear=self._on_clear_equipment,
            get_class_id=lambda: self._current_class_id(),
            get_gender_id=get_gender_id,
            get_level=get_level,
            get_selected_item=lambda k: (self._selected_items or {}).get(k),
        )
        self.weapon_ctrl, self.offhand_ctrl, self.spear_ctrl = make_weapon_offhand_controllers(
            parent=self,
            data=self.data,
            on_pick=self._on_pick_equipment,
            on_clear=self._on_clear_equipment,
            get_class_id=lambda: self._current_class_id(),
            get_gender_id=get_gender_id,
            get_level=get_level,
            get_selected_item=lambda k: (self._selected_items or {}).get(k),
        )

        self.costume_ctrl = CostumeController(
            parent_widget=self,
            data=self.data,
            get_gender_id=get_gender_id,
            on_pick=self._on_pick_equipment,
            on_clear=self._on_clear_equipment,
        )

        self.mount_ctrl = MountController(
            parent_widget=self,
            data=self.data,
            get_gender_id=get_gender_id,
            on_pick=self._on_pick_equipment,
            on_clear=self._on_clear_equipment,
        )
        self.costume_ctrl.on_gender_changed(get_gender_id())

        # ===== иконка класса =====
        self.class_btn = mk_tbtn(self, "classBtn")
        self.class_btn.setFixedSize(CLASS_FRAME_PX, CLASS_FRAME_PX)
        self.class_btn.setIconSize(QSize(CLASS_ICON_PX, CLASS_ICON_PX))
        self.class_btn.setAttribute(Qt.WA_TranslucentBackground, True)
        self.class_btn.setAutoFillBackground(False)
        uconnect(self.class_btn.clicked, self._on_class_icon_click)

        pad = max(0, (CLASS_FRAME_PX - CLASS_ICON_PX) // 2 - CLASS_BORDER_W)
        self._CLASS_ICON_STYLE_NORMAL = f"""
            QToolButton#classBtn {{
              background-color: transparent;
              border: {CLASS_BORDER_W}px solid #8c8c8c;
              border-top-color: #cfcfcf;
              border-left-color: #cfcfcf;
              border-right-color: #5a5a5a;
              border-bottom-color: #5a5a5a;
              border-radius: 6px;
              padding: {pad}px;
            }}
            QToolButton#classBtn:hover {{
              border-top-color: #e0e0e0;
              border-left-color: #e0e0e0;
              border-right-color: #6a6a6a;
              border-bottom-color: #6a6a6a;
            }}
        """
        self._CLASS_ICON_STYLE_ACTIVE = f"""
            QToolButton#classBtn {{
              background-color: transparent;
              border: {CLASS_BORDER_W}px solid {GOLD};
              border-top-color: #f6e8b2;
              border-left-color: #f6e8b2;
              border-right-color: #7b5c12;
              border-bottom-color: #7b5c12;
              border-radius: 6px;
              padding: {pad}px;
            }}
        """
        self.class_btn.setStyleSheet(self._CLASS_ICON_STYLE_NORMAL)

        # ===== двуручность / offhand ghost =====
        self._two_handed_equipped = False
        self._block_weapon_clear_for_offhand_menu = False

        self._offhand_ghost = QLabel(self)
        self._offhand_ghost.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._offhand_ghost.setStyleSheet("background: transparent;")
        self._offhand_ghost.setScaledContents(True)
        self._offhand_ghost.hide()
        self._offhand_ghost_fx = QGraphicsOpacityEffect(self._offhand_ghost)
        self._offhand_ghost_fx.setOpacity(0.55)
        self._offhand_ghost.setGraphicsEffect(self._offhand_ghost_fx)

        # ===== кнопки пола =====
        self.gender_m_btn = self._mk_gender_btn(None, "Мужчина")
        self.gender_f_btn = self._mk_gender_btn(None, "Женщина")
        self.gender_m_btn.setObjectName("genderBtnM")
        self.gender_f_btn.setObjectName("genderBtnF")
        self.gender_m_btn.setAutoRaise(True)
        self.gender_f_btn.setAutoRaise(True)
        self.gender_m_btn.setAttribute(Qt.WA_TranslucentBackground, True)
        self.gender_f_btn.setAttribute(Qt.WA_TranslucentBackground, True)
        self.gender_m_btn.setAutoFillBackground(False)
        self.gender_f_btn.setAutoFillBackground(False)
        uconnect(self.gender_m_btn.clicked, lambda _=False: self._set_gender(1))
        uconnect(self.gender_f_btn.clicked, lambda _=False: self._set_gender(2))

        self._apply_current_gender_icons()
        self._update_gender_styles()

        # ===== glow/hover оверлеи =====
        self._glow_pm = _load_file_image(GLOW_PATH)

        self.hover_glow = QLabel(self)
        self.hover_glow.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hover_glow.setAttribute(Qt.WA_TranslucentBackground, True)
        self.hover_glow.setAutoFillBackground(False)
        self.hover_glow.setStyleSheet("background: transparent;")
        self.hover_glow.setScaledContents(True)
        self.hover_glow.hide()

        self._glow_locked_key: Optional[str] = None
        self._glow_locked_rect: Optional[QRect] = None

        self._menu_glow_pm = _load_file_image(MENU_GLOW_PATH)
        self.menu_glow = QLabel(self)
        self.menu_glow.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.menu_glow.setAttribute(Qt.WA_TranslucentBackground, True)
        self.menu_glow.setAutoFillBackground(False)
        self.menu_glow.setStyleSheet("background: transparent;")
        self.menu_glow.setScaledContents(True)
        self.menu_glow.hide()

        self._min_hover_pm = _load_file_image(MINIMIZE_HOVER_PATH)
        self._close_hover_pm = _load_file_image(CLOSE_HOVER_PATH)
        self.winbtn_hover = QLabel(self)
        self.winbtn_hover.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.winbtn_hover.setAttribute(Qt.WA_TranslucentBackground, True)
        self.winbtn_hover.setAutoFillBackground(False)
        self.winbtn_hover.setStyleSheet("background: transparent;")
        self.winbtn_hover.setScaledContents(True)
        self.winbtn_hover.hide()

        self.hover_name_label = _HoverNameInfoBoard(self)
        self.hover_name_label.setObjectName("hoverNameLabel")
        self.hover_name_label.hide()

        # ===== нижнее меню =====
        self.menu_btns: Dict[str, QToolButton] = {}
        for b in MENU_BUTTONS:
            key = b["key"]
            btn = mk_tbtn(self)
            btn.setStyleSheet(
                """
                QToolButton {
                    background: transparent;
                    color: #ddd;
                    border: none;
                    padding: 0;
                    font-weight: 600;
                }
                QToolButton:hover { color: white; }
                """
            )
            if key == "inventory":
                uconnect(btn.clicked, self._on_menu_bag_clicked)
            elif key == "guild":
                uconnect(btn.clicked, self._on_menu_guild_clicked)
            elif key == "elixir":
                uconnect(btn.clicked, self._on_menu_elixir_clicked)
            elif key == "consumble":
                uconnect(btn.clicked, self._on_menu_consumble_clicked)
            elif key == "aura":
                uconnect(btn.clicked, self._on_menu_aura_clicked)
            elif key == "collect":
                uconnect(btn.clicked, self._on_menu_collect_clicked)
            elif key == "stamp":
                uconnect(btn.clicked, self._on_menu_stamp_clicked)
            elif key == "reforge":
                uconnect(btn.clicked, self._on_menu_reforge_clicked)
            elif key == "talents":
                uconnect(btn.clicked, self._on_menu_talents_clicked)
            elif key == "buffs":
                uconnect(btn.clicked, self._on_menu_buffs_clicked)
            btn.raise_()
            self.menu_btns[key] = btn

        # ===== таймер ховера =====
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(25)
        uconnect(self._hover_timer.timeout, self._update_glow_from_global)

        # ===== меню классов =====
        self._build_class_menu()

        # ===== глобальные фильтры событий =====
        self._stamp_shield = None
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)

            self._main_modal_input_blocker = _MainModalInputBlocker(self)
            app.installEventFilter(self._main_modal_input_blocker)

        self.board_label.installEventFilter(self)
        self.board_label.setMouseTracking(True)

        # ===== окно рефоржа =====
        self.upgrade_win = UpgradeWindow(self)
        if hasattr(self.data, "get_image_bytes"):
            self.upgrade_win.set_image_loader(self.data.get_image_bytes)
        uconnect(self.upgrade_win.on_reforge_request, self._on_reforge_requested)

        # ===== состояние/слоты =====
        # (уже инициализировано в начале, здесь оставляем только то, что реально надо после upgrade_win)
        self._zones_screen = []
        self._selected_items = self._selected_items or {}
        self._suppress_stamp_equipped = self._suppress_stamp_equipped or set()
        self._equip_via_menu = bool(self._equip_via_menu)
        self._equip_from_inventory = bool(self._equip_from_inventory)
        self._mask_stamp_slots = self._mask_stamp_slots or set()
        self._applied_stamps = self._applied_stamps or {}

        self._slot_icons = {}
        for key in SLOT_POS.keys():
            lbl = QLabel(self)
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            lbl.setMouseTracking(True)
            lbl.installEventFilter(self)
            lbl.setStyleSheet("background: transparent;")
            lbl.setScaledContents(True)
            lbl.hide()
            self._slot_icons[key] = lbl

        # ===== первичная отрисовка =====
        self.resize(self._base_w, self._base_h)
        self.setFixedSize(self.size())
        self._apply_current_class_icon()
        self._apply_class_border_for_current()
        self._select_background_by_class()
        self._update_board_pixmap()
        self._apply_level_rules_for_current_class()

        # ===== offhand overlay =====
        self._offhand_overlay = QLabel(self)
        self._offhand_overlay.setStyleSheet("background: rgba(20,20,20,120); border-radius: 4px;")
        self._offhand_overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._offhand_overlay.hide()

        QTimer.singleShot(0, self._layout_overlays)

        # ===== окно печатей =====
        self.stamp_window = StampWindow(self)
        uconnect(self.stamp_window.closed, self._remove_stamp_shield)
        cid = self._current_class_id()
        self.stamp_window.set_player_class(cid if cid is not None else self.class_combo.currentText())
        self._last_class_bucket = self._class_bucket_from_name(self.class_combo.currentText())
        self.stamp_window.hide()

        # ===== инвентарь =====
        self.inventory_window: Optional[InventoryWindow] = None

        # ===== окно карт =====
        self.cards_window = CardsWindow(self)
        try:
            self.cards_window.installEventFilter(self)
        except Exception:
            pass
        try:
            uconnect(self.cards_window.closed, self._on_cards_closed)
        except Exception:
            uconnect(self.cards_window.closed, lambda: None)
        if hasattr(self.data, "get_image_bytes"):
            self.cards_window.set_image_loader(self.data.get_image_bytes)

        # ===== щиты под модалки =====
        self._inv_shield = None  # type: Optional[_InputShield]
        self._reforge_shield = None  # type: Optional[_InputShield]
        self._block_main_input = False
        self._block_allow_root: QWidget | None = None

        # после создания всех кнопок:
        self.gender_m_btn.installEventFilter(self)
        self.gender_f_btn.installEventFilter(self)
        for b in self.menu_btns.values():
            b.installEventFilter(self)

        self.cards_window.card_picked.connect(self._on_card_picked)
        self.cards_window.card_cleared.connect(self._on_card_cleared)

        try:
            self.cards_window.item_cache_changed.connect(
                self._on_item_cache_changed,
                Qt.ConnectionType.UniqueConnection,
            )
        except Exception:
            try:
                self.cards_window.item_cache_changed.connect(self._on_item_cache_changed)
            except Exception:
                pass

        self.character_stats: Dict[int, float] = {}

        self._elixir_menu: Optional[ChooseElixirMenu] = None
        self._player_elixir_payload: Optional[dict] = None
        self._consumble_menu: Optional[ChooseConsumbleMenu] = None
        self._player_consumables_payloads: List[dict] = []
        self._talents_menu_window: Optional[TalentsMenu] = None
        self._aura_menu_window: Optional[AuraMenuWindow] = None
        self._buff_debuff_menu_window: Optional[BuffDebuffMenuWindow] = None

        # ===== 2 доп. кнопки (маленькие) =====
        self._init_small_menu_buttons()
        self._init_active_buff_preview_buttons()

        self._init_event_selector_ui()

        self._disable_keyboard_focus_for_main_ui()
        QTimer.singleShot(0, self._disable_keyboard_focus_for_main_ui)

    def focusNextPrevChild(self, next: bool) -> bool:
        """
        Полностью запрещаем Tab/Shift+Tab навигацию по виджетам MainWindow.
        """
        return False

    def _disable_keyboard_focus_for_main_ui(self) -> None:
        """
        Отключает клавиатурный фокус у кнопок/виджетов главного окна.

        Нужно, чтобы Tab не выбирал случайные кнопки,
        а Space/Enter не активировали сфокусированную кнопку.
        """
        widgets: list[QWidget] = []

        for w in (
                getattr(self, "close_btn", None),
                getattr(self, "minimize_btn", None),
                getattr(self, "class_btn", None),
                getattr(self, "gender_m_btn", None),
                getattr(self, "gender_f_btn", None),
                getattr(self, "total_menu_btn", None),
                getattr(self, "helper_menu_btn", None),
                getattr(self, "other_menu_open_btn", None),
                getattr(self, "other_menu_close_btn", None),
                getattr(self, "btn_reset_params", None),
        ):
            if isinstance(w, QWidget):
                widgets.append(w)

        try:
            widgets.extend([w for w in (getattr(self, "menu_btns", {}) or {}).values() if isinstance(w, QWidget)])
        except Exception:
            pass

        try:
            widgets.extend([w for w in (getattr(self, "small_menu_btns", {}) or {}).values() if isinstance(w, QWidget)])
        except Exception:
            pass

        try:
            widgets.extend([w for w in (getattr(self, "_slot_icons", {}) or {}).values() if isinstance(w, QWidget)])
        except Exception:
            pass

        seen: set[int] = set()
        for w in widgets:
            oid = id(w)
            if oid in seen:
                continue
            seen.add(oid)

            try:
                w.setFocusPolicy(Qt.NoFocus)
            except Exception:
                pass

            try:
                w.clearFocus()
            except Exception:
                pass

        try:
            self.setFocusPolicy(Qt.NoFocus)
        except Exception:
            pass

        try:
            self.clearFocus()
        except Exception:
            pass

    def _get_menu_bonus_enabled_map(self) -> Dict[str, bool]:
        state = getattr(self, "_menu_bonus_enabled", None)
        if not isinstance(state, dict):
            state = {}

        normalized: Dict[str, bool] = {}
        for key in MENU_BONUS_TOGGLE_KEYS:
            normalized[str(key)] = bool(state.get(key, True))

        self._menu_bonus_enabled = dict(normalized)
        return dict(normalized)

    def _ensure_menu_bonus_toggles(self) -> None:
        self._get_menu_bonus_enabled_map()

        toggles = getattr(self, "_menu_bonus_toggles", None)
        if not isinstance(toggles, dict):
            toggles = {}

        for key in list(toggles.keys()):
            if key not in MENU_BONUS_TOGGLE_KEYS:
                try:
                    toggles[key].hide()
                    toggles[key].deleteLater()
                except Exception:
                    pass
                toggles.pop(key, None)

        for key in MENU_BONUS_TOGGLE_KEYS:
            w = toggles.get(key)
            if not isinstance(w, _MenuBonusToggle):
                toggles[key] = _MenuBonusToggle(self, key)

        self._menu_bonus_toggles = toggles

    def _place_menu_bonus_toggles(self) -> None:
        self._ensure_menu_bonus_toggles()

        pm = self.board_label.pixmap()
        toggles = getattr(self, "_menu_bonus_toggles", {}) or {}

        if not pm:
            for w in toggles.values():
                try:
                    w._visible = False
                    w.hide()
                except Exception:
                    pass
            return

        for key in MENU_BONUS_TOGGLE_KEYS:
            w = toggles.get(key)
            if w is None:
                continue

            try:
                w.sync()
            except Exception:
                try:
                    w._visible = False
                    w.hide()
                except Exception:
                    pass

    def _on_menu_bonus_toggle_clicked(self, menu_key: str) -> None:
        key = str(menu_key or "").strip().lower()
        if key not in MENU_BONUS_TOGGLE_KEYS:
            return

        state = self._get_menu_bonus_enabled_map()
        state[key] = not bool(state.get(key, True))
        self._menu_bonus_enabled = dict(state)

        try:
            tog = (getattr(self, "_menu_bonus_toggles", {}) or {}).get(key)
            if tog is not None:
                tog.sync()
        except Exception:
            pass

        try:
            self.refresh_stats_panel()
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self.refresh_stats_panel)
        except Exception:
            pass

        try:
            self.update()
        except Exception:
            pass

    def _class_allows_equipment_type(self, type_id: int, *, class_id: Optional[int] = None) -> bool:
        cid = _safe_int(class_id if class_id is not None else self._current_class_id(), 0)
        if cid <= 0:
            return False

        lineage = self._class_lineage_ids(cid)
        if not lineage:
            return False

        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None:
            return False

        tid = _safe_int(type_id, 0)
        if tid <= 0:
            return True  # нет типа — не режем

        # ✅ если по этому Type_Id нет ни одной записи — значит тип не ограничен
        try:
            any_row = conn.execute(
                "SELECT 1 FROM EquipmentTypeCondition WHERE Type_Id=? LIMIT 1",
                (tid,)
            ).fetchone()
        except Exception:
            any_row = None

        if not any_row:
            return True

        ph = ",".join(["?"] * len(lineage))
        sql = f"""
            SELECT 1
            FROM EquipmentTypeCondition
            WHERE Type_Id = ?
              AND Class_Id IN ({ph})
            LIMIT 1
        """
        try:
            row = conn.execute(sql, [tid] + [int(x) for x in lineage]).fetchone()
        except Exception:
            row = None

        return bool(row)

    def _spear_slot_visible(self) -> bool:
        """
        Копьё (slot 'spear') показываем только если:
          - текущий класс НЕ в списке исключений (Class_Id=1 скрываем),
          - и EquipmentTypeCondition разрешает Type_Id=22 для текущего класса/его предков.
        """
        cid = _safe_int(self._current_class_id(), 0)
        if cid <= 0:
            return False

        if cid in SPEAR_HIDE_FOR_CLASS_IDS:
            return False

        return self._class_allows_equipment_type(SPEAR_TYPE_ID, class_id=cid)

    # =========================
    # EQUIPMENT SLOTS (DB-driven)
    # =========================
    _EQUIP_SLOT_SELECT = """
        SELECT Id, Name, State_Id, ExtraSlot_Id, Count, IsWeapon
        FROM EquipmentSlot
        ORDER BY Id
    """

    def _norm_slot_name(self, s: str) -> str:
        return (s or "").strip().casefold()

    def _init_equipment_slot_registry(self) -> None:
        """
        Строит маппинг UI slot_key -> EquipmentSlot.Id из БД.
        Ожидается, что EquipmentSlot.Name в БД соответствует ключам UI (head/mask/armor/...).
        Для слотов с Count>1 (например ring) — поддерживает ring1/ring2.
        """
        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None:
            return

        try:
            rows = conn.execute(self._EQUIP_SLOT_SELECT).fetchall()
        except Exception:
            rows = []

        meta_by_id: Dict[int, EquipSlotMeta] = {}
        meta_by_name: Dict[str, EquipSlotMeta] = {}

        for r in rows or []:
            try:
                if hasattr(r, "keys"):
                    sid = int(r["Id"])
                    name = str(r["Name"])
                    st = r["State_Id"]
                    ex = r["ExtraSlot_Id"]
                    cnt = int(r["Count"])
                    iw = int(r["IsWeapon"] or 0)
                else:
                    sid = int(r[0]); name = str(r[1]); st = r[2]; ex = r[3]; cnt = int(r[4]); iw = int(r[5] or 0)
            except Exception:
                continue

            meta = EquipSlotMeta(
                id=sid,
                name=name,
                state_id=(int(st) if st is not None else None),
                extra_slot_id=(int(ex) if ex is not None else None),
                count=max(1, int(cnt)),
                is_weapon=(iw == 1),
            )
            meta_by_id[sid] = meta
            meta_by_name[self._norm_slot_name(name)] = meta

        self._slot_meta_by_id = meta_by_id
        self._slot_meta_by_name = meta_by_name

        # --- UI key -> db slot id ---
        ui_to_db: Dict[str, int] = {}
        db_to_ui: Dict[int, List[str]] = {}

        for ui_key in (SLOT_POS or {}).keys():
            k = (ui_key or "").strip().casefold()
            base = re.sub(r"\d+$", "", k)  # ring1 -> ring

            meta = meta_by_name.get(k) or meta_by_name.get(base)
            if not meta:
                continue

            ui_to_db[ui_key] = meta.id
            db_to_ui.setdefault(meta.id, []).append(ui_key)

        # если в БД слот "ring" (Count>=2), а UI ключи ring1/ring2 — они уже попадут через base.
        self._ui_slot_to_db_slot_id = ui_to_db
        self._db_slot_to_ui_keys = db_to_ui

        # сбрасываем кеши допустимых предметов (они зависят от slot_id)
        try:
            self._slot_allowed_ids_cache.clear()
        except Exception:
            self._slot_allowed_ids_cache = {}
        # --- spear fallback ---
        # Если в EquipmentSlot.Name нет "spear", то обычно spear = weapon.ExtraSlot_Id
        if "spear" in (SLOT_POS or {}) and "spear" not in ui_to_db:
            weapon_meta = meta_by_name.get("weapon")
            if weapon_meta and weapon_meta.extra_slot_id:
                extra_id = int(weapon_meta.extra_slot_id)
                ui_to_db["spear"] = extra_id
                db_to_ui.setdefault(extra_id, []).append("spear")

    def _slot_meta(self, slot_key: str) -> Optional[EquipSlotMeta]:
        sid = self._slot_db_id(slot_key)
        if sid:
            return self._slot_meta_by_id.get(int(sid))
        # фолбэк по имени
        return self._slot_meta_by_name.get(self._norm_slot_name(slot_key))

    def _slot_db_id(self, slot_key: str) -> Optional[int]:
        if not slot_key:
            return None
        sid = self._ui_slot_to_db_slot_id.get(str(slot_key))
        return int(sid) if sid else None

    def slot_key_by_id(self, slot_id: int) -> Optional[str]:
        """
        DB Slot_Id -> UI slot_key.
        Если слоту соответствует несколько UI-ключей (Count>1), вернём первый свободный.
        """
        sid = _safe_int(slot_id, 0)
        if sid <= 0:
            return None

        keys = (self._db_slot_to_ui_keys or {}).get(sid) or []
        if not keys:
            # пробуем через имя слота
            meta = (self._slot_meta_by_id or {}).get(sid)
            if meta:
                name_key = self._norm_slot_name(meta.name)
                if name_key in (SLOT_POS or {}):
                    return name_key
            return None

        if len(keys) == 1:
            return keys[0]

        # несколько ключей (ring1/ring2): выбираем свободный, иначе первый
        for k in keys:
            if not (self._selected_items or {}).get(k):
                return k
        return keys[0]

    def _slot_key_for_item(self, item: dict) -> Optional[str]:
        """
        Определить UI-слот для предмета через EquipmentType.Slot_Id.
        Полезно для auto-экипа/перетаскивания.
        """
        tid = _safe_int(item.get("Type_Id") or item.get("TypeId"), 0)
        if tid <= 0:
            return None

        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None:
            return None

        try:
            row = conn.execute("SELECT Slot_Id FROM EquipmentType WHERE Id=? LIMIT 1", (tid,)).fetchone()
        except Exception:
            row = None

        if not row:
            return None

        slot_id = row[0] if not hasattr(row, "keys") else row["Slot_Id"]
        return self.slot_key_by_id(_safe_int(slot_id, 0))

    # =========================
    # SLOT → kind (weapon/equipment) (DB-driven)
    # =========================
    def _slot_kind(self, slot_key: str) -> str:
        """
        Возвращает "weapon" или "equipment" на основании EquipmentSlot.IsWeapon.
        """
        meta = self._slot_meta(slot_key)
        return "weapon" if (meta and meta.is_weapon) else "equipment"

    def _slot_is_active_in_current_state(self, slot_key: str) -> bool:
        """
        Slot активен, если EquipmentSlot.State_Id is NULL или равен текущему state_id.
        """
        meta = self._slot_meta(slot_key)
        if not meta:
            return True
        if meta.state_id is None:
            return True
        cur_state = int(getattr(self, "_current_state_id", 0) or 0)
        return int(meta.state_id) == cur_state

    def _slot_key_from_obj(self, obj) -> Optional[str]:
        """
        Надёжно определяет UI slot_key по объекту, на который пришёл event.
        Поддерживает:
          - obj.property("slot_key")
          - objectName() с префиксами slot_/equip_/icon_ и т.п.
        """
        if obj is None:
            return None

        # 1) property("slot_key") — лучший вариант
        try:
            v = obj.property("slot_key")
            if v:
                k = str(v).strip()
                if k in (SLOT_POS or {}):
                    return k
        except Exception:
            pass

        # 2) разбор objectName()
        name = ""
        try:
            name = str(obj.objectName() or "")
        except Exception:
            name = ""

        if not name:
            return None

        # примеры: slot_weapon_icon, weapon_icon, equip_ring1, ring2_btn...
        n = name.strip().casefold()
        n = re.sub(r"^(slot_|equip_|icon_|btn_|lbl_)", "", n)
        n = re.sub(r"(_icon|_btn|_label|_lbl)$", "", n)

        # иногда objectName может быть типа "slot_ring_1" → "ring1"
        n = n.replace("_", "")
        # ring1 / ring2 и т.п. оставляем как есть

        # ищем прямое совпадение
        for candidate in (n,):
            if candidate in (SLOT_POS or {}):
                # вернуть оригинальный ключ из SLOT_POS (с учётом регистра/формата)
                # но у тебя SLOT_POS ключи в lower, так что ок
                return candidate

        return None

    # =========================
    # EquipmentType meta (for icon badges, optional)
    # =========================
    def _etype_meta(self, type_id: int) -> dict:
        """
        Кеширует строку EquipmentType по Id как dict.
        Работает даже если row не sqlite3.Row (через cursor.description).
        """
        tid = _safe_int(type_id, 0)
        if tid <= 0:
            return {}

        if tid in getattr(self, "_etype_meta_cache", {}):
            return self._etype_meta_cache[tid] or {}

        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None:
            self._etype_meta_cache[tid] = {}
            return {}

        try:
            cur = conn.execute("SELECT * FROM EquipmentType WHERE Id=? LIMIT 1", (tid,))
            row = cur.fetchone()
        except Exception:
            row = None
            cur = None

        out = {}
        if row:
            try:
                if hasattr(row, "keys"):
                    out = {k: row[k] for k in row.keys()}
                elif cur and getattr(cur, "description", None):
                    cols = [d[0] for d in cur.description]
                    out = {cols[i]: row[i] for i in range(min(len(cols), len(row)))}
            except Exception:
                out = {}

        self._etype_meta_cache[tid] = out
        return out

    def _item_is_weapon_like(self, item: dict) -> bool:
        """
        Пытается понять "оружейность" по полям item или EquipmentType.
        Нужен только для бейджей/иконок, не для логики допуска.
        """
        if not isinstance(item, dict):
            return False

        # быстрый фолбэк по item
        for k in ("IsWeapon", "IsMeleeWeapon", "IsRangedWeapon"):
            if _safe_int(item.get(k), 0) == 1:
                return True

        tid = _safe_int(item.get("Type_Id") or item.get("TypeId"), 0)
        if tid <= 0:
            return False

        meta = self._etype_meta(tid)
        for k in ("IsWeapon", "IsMeleeWeapon", "IsRangedWeapon"):
            if _safe_int(meta.get(k), 0) == 1:
                return True

        return False

    def _should_draw_element_badge(self, slot_key: str, item: dict) -> bool:
        """
        Рисовать ли бейдж элемента на иконке.

        ВАЖНО (регрессия, из-за которой "пистолеты без элемента"):
        - даже если БД-слоты не замаппились (meta=None) или EquipmentSlot.IsWeapon=0,
          для UI-слотов weapon/offhand/spear бейдж ВСЕГДА разрешаем (как было раньше).
        - иначе пытаемся определить "оружейность" по метаданным слота/типа.
        """
        sk = str(slot_key or "").strip().lower()
        if sk in ("weapon", "offhand", "spear"):
            return True

        meta = self._slot_meta(slot_key)
        if meta and meta.is_weapon:
            return True
        return self._item_is_weapon_like(item)

    def _update_slot_icon(self, slot_key: str) -> None:
        lbl = self._slot_icons.get(slot_key)
        if not lbl:
            return

        item = (self._selected_items or {}).get(slot_key)
        if not item:
            lbl.hide()
            if slot_key == "weapon":
                self._update_offhand_overlay(refresh_icon=True)
            elif slot_key == "offhand":
                self._update_offhand_overlay(refresh_icon=False)
            return

        rect = next((r for k, r in self._zones_screen if k == slot_key), None)
        if rect is None or rect.isEmpty():
            lbl.hide()
            if slot_key == "weapon":
                self._update_offhand_overlay(refresh_icon=True)
            elif slot_key == "offhand":
                self._update_offhand_overlay(refresh_icon=False)
            return

        img_id = item.get("CostumeImage_Id") if slot_key == "costume" else (
                item.get("Image_Id") or item.get("Icon_Image_Id")
        )
        base_pm = self._get_image_pm(img_id)
        if not base_pm:
            lbl.hide()
            if slot_key == "weapon":
                self._update_offhand_overlay(refresh_icon=True)
            elif slot_key == "offhand":
                self._update_offhand_overlay(refresh_icon=False)
            return

        tw = int(rect.width() * SLOT_ICON_SCALE)
        th = int(rect.height() * SLOT_ICON_SCALE)
        target = QRect(0, 0, max(1, tw), max(1, th))
        target.moveCenter(rect.center())
        icon_size = target.size()

        scaled_base = base_pm.scaled(icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        canvas = QPixmap(icon_size)
        canvas.fill(Qt.transparent)

        p = QPainter(canvas)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.drawPixmap(0, 0, scaled_base)

        should_badge = False
        try:
            should_badge = bool(self._should_draw_element_badge(slot_key, item))
        except Exception:
            should_badge = False

        if should_badge:
            self._paint_element_badge(p, icon_size, item, slot_key=slot_key)

        p.end()

        if slot_key == "offhand" and self._is_offhand_disabled():
            canvas = self._disabled_pixmap(canvas, overlay_alpha=110, desaturate=True)

        lbl.setGeometry(target)
        lbl.setPixmap(canvas)
        lbl.show()
        lbl.raise_()

        if slot_key == "weapon":
            self._update_offhand_overlay(refresh_icon=True)
        elif slot_key == "offhand":
            self._update_offhand_overlay(refresh_icon=False)

    def _paint_element_badge(self, p: QPainter, icon_size: QSize, item: dict, *, slot_key: str | None = None) -> None:
        """
        Рисует маленький бейдж элемента на иконке оружия/оружейного слота.

        ВАЖНО:
        _element_pm_for_item() может вернуть None, если у предмета нет элементной карты
        или если элементный значок невозможно получить из БД. Это нормальная ситуация,
        а не ошибка. В таком случае просто не рисуем бейдж.
        """
        elem_pm = self._element_pm_for_item(item, slot_key=slot_key)

        if not isinstance(elem_pm, QPixmap) or elem_pm.isNull():
            return

        try:
            w = _safe_int(icon_size.width(), 0)
            h = _safe_int(icon_size.height(), 0)
        except Exception:
            return

        if w <= 0 or h <= 0:
            return

        side = max(1, int(w * ELEM_BADGE_SCALE))

        try:
            elem_scaled = elem_pm.scaled(
                side,
                side,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        except Exception:
            return

        if elem_scaled.isNull():
            return

        # старое поведение: bottom-left
        x = max(0, int(ELEM_BADGE_DX))
        y = max(0, int(h - elem_scaled.height() - ELEM_BADGE_DY))

        try:
            p.drawPixmap(x, y, elem_scaled)
        except Exception:
            pass

    def _element_pm_for_item(self, item: dict | None, *, slot_key: str | None = None) -> Optional[QPixmap]:
        """
        Возвращает QPixmap значка элемента для оружия/оружейных слотов.

        Приоритет:
        1) Элементная карта внутри предмета:
           - item["_cards"] / item["cards"] / item["Cards"]
           - поддерживаем как dict(slot_index -> card), так и list/tuple (по порядку слотов)
           - если у карты есть Element_Id/ToolTipImage_Id -> используем их
           - если Element_Id отсутствует в dict -> пробуем добрать через БД по Type_Id или Card.Id
        2) fallback: через CardsWindow.build_tooltip_cards_payload_for_item()
           (это то, чем пользуется рюкзак/инвентарь для отрисовки бейджа)
        3) fallback: item["Element_Id"] (если где-то устанавливается старой логикой)
           -> ищем ToolTipImage_Id по Element_Id в CardType.
        """
        if not item or not isinstance(item, dict):
            return None

        conn = getattr(getattr(self, "data", None), "conn", None)

        # ------------------------------------------------------------
        # 1) пробуем из вставленных карт, которые лежат прямо в item
        # ------------------------------------------------------------
        cards_raw = None
        for ck in ("_cards", "cards", "Cards"):
            v = item.get(ck)
            if v is not None:
                cards_raw = v
                break

        cards_map: dict = {}
        if isinstance(cards_raw, dict):
            cards_map = cards_raw
        elif isinstance(cards_raw, (list, tuple)):
            # нормализуем list/tuple -> dict(slot_index -> entry)
            # slot_index у нас в проекте обычно 1..N, поэтому start=1.
            try:
                cards_map = {i: cards_raw[i - 1] for i in range(1, len(cards_raw) + 1)}
            except Exception:
                cards_map = {}
        else:
            cards_map = {}

        if isinstance(cards_map, dict) and cards_map:
            # сначала пробуем слот 1 (обычно элементная карта на оружии), потом остальные
            try:
                keys = list(cards_map.keys())
                # сортируем ключи так, чтобы 1 был первым (если есть),
                # но не ломаем типы (str/int)
                if 1 in keys:
                    keys.remove(1)
                    keys = [1] + keys
                elif "1" in keys:
                    keys.remove("1")
                    keys = ["1"] + keys
            except Exception:
                keys = list(cards_map.keys())

            # кеши для фолбэков через БД
            ct_cache = getattr(self, "_cardtype_elem_tooltip_cache", None)
            if not isinstance(ct_cache, dict):
                ct_cache = {}
                self._cardtype_elem_tooltip_cache = ct_cache

            c_cache = getattr(self, "_card_elem_tooltip_cache", None)
            if not isinstance(c_cache, dict):
                c_cache = {}
                self._card_elem_tooltip_cache = c_cache

            for k in keys:
                c = cards_map.get(k)
                if not c:
                    continue

                # -----------------------------
                # card как dict
                # -----------------------------
                if isinstance(c, dict):
                    # поддерживаем оба нейминга
                    elem_id = _safe_int(c.get("Element_Id") or c.get("ElementId"), 0)
                    tip_img_id = _safe_int(c.get("ToolTipImage_Id") or c.get("ToolTipImageId"), 0)
                    type_id = _safe_int(c.get("Type_Id") or c.get("TypeId"), 0)
                    card_id = _safe_int(c.get("Id") or c.get("Card_Id") or c.get("CardId"), 0)

                    # 1) если уже есть и Element и ToolTipImage — сразу отдаём
                    if elem_id > 0 and tip_img_id > 0:
                        return self._get_image_pm(tip_img_id)

                    # 2) если Element_Id нет/0 — пробуем добыть через БД по Type_Id или Card.Id
                    if conn is not None:
                        # --- по CardType.Id ---
                        if type_id > 0:
                            cached = ct_cache.get(type_id)
                            if isinstance(cached, tuple) and len(cached) == 2:
                                e2, t2 = cached
                            else:
                                e2, t2 = 0, int(cached or 0) if isinstance(cached, (int, float)) else 0

                            if (e2 <= 0 or t2 <= 0) and (cached is None or not isinstance(cached, tuple)):
                                try:
                                    row = conn.execute(
                                        "SELECT Element_Id, ToolTipImage_Id FROM CardType WHERE Id=? LIMIT 1",
                                        (int(type_id),),
                                    ).fetchone()
                                except Exception:
                                    row = None

                                if row:
                                    if hasattr(row, "keys"):
                                        e2 = _safe_int(row["Element_Id"], 0)
                                        t2 = _safe_int(row["ToolTipImage_Id"], 0)
                                    else:
                                        e2 = _safe_int(row[0], 0)
                                        t2 = _safe_int(row[1], 0)
                                else:
                                    e2, t2 = 0, 0

                                ct_cache[type_id] = (int(e2), int(t2))

                            if elem_id <= 0:
                                elem_id = _safe_int(e2, 0)
                            if tip_img_id <= 0:
                                tip_img_id = _safe_int(t2, 0)

                            if elem_id > 0 and tip_img_id > 0:
                                return self._get_image_pm(tip_img_id)

                        # --- по Card.Id ---
                        if card_id > 0:
                            cached = c_cache.get(card_id)
                            if isinstance(cached, tuple) and len(cached) == 2:
                                e2, t2 = cached
                            else:
                                e2, t2 = 0, int(cached or 0) if isinstance(cached, (int, float)) else 0

                            if cached is None or not isinstance(cached, tuple):
                                try:
                                    row = conn.execute(
                                        """
                                        SELECT ct.Element_Id, ct.ToolTipImage_Id
                                        FROM Card c
                                        JOIN CardType ct ON ct.Id = c.Type_Id
                                        WHERE c.Id=?
                                        LIMIT 1
                                        """,
                                        (int(card_id),),
                                    ).fetchone()
                                except Exception:
                                    row = None

                                if row:
                                    if hasattr(row, "keys"):
                                        e2 = _safe_int(row["Element_Id"], 0)
                                        t2 = _safe_int(row["ToolTipImage_Id"], 0)
                                    else:
                                        e2 = _safe_int(row[0], 0)
                                        t2 = _safe_int(row[1], 0)
                                else:
                                    e2, t2 = 0, 0

                                c_cache[card_id] = (int(e2), int(t2))

                            if elem_id <= 0:
                                elem_id = _safe_int(e2, 0)
                            if tip_img_id <= 0:
                                tip_img_id = _safe_int(t2, 0)

                            if elem_id > 0 and tip_img_id > 0:
                                return self._get_image_pm(tip_img_id)

                    continue

                # -----------------------------
                # card как tuple/list -> попробуем извлечь Card.Id
                # -----------------------------
                if isinstance(c, (tuple, list)) and c:
                    try:
                        c0 = c[0]
                    except Exception:
                        c0 = None
                    if isinstance(c0, dict):
                        card_id = _safe_int(c0.get("Id") or c0.get("Card_Id") or c0.get("CardId"), 0)
                    else:
                        card_id = _safe_int(c0, 0)
                else:
                    # -----------------------------
                    # card как число (Card.Id)
                    # -----------------------------
                    card_id = _safe_int(c, 0)

                if card_id > 0 and conn is not None:
                    cached = c_cache.get(card_id)
                    if isinstance(cached, tuple) and len(cached) == 2:
                        e2, t2 = cached
                    else:
                        e2, t2 = 0, int(cached or 0) if isinstance(cached, (int, float)) else 0

                    if cached is None or not isinstance(cached, tuple):
                        try:
                            row = conn.execute(
                                """
                                SELECT ct.Element_Id, ct.ToolTipImage_Id
                                FROM Card c
                                JOIN CardType ct ON ct.Id = c.Type_Id
                                WHERE c.Id=?
                                LIMIT 1
                                """,
                                (int(card_id),),
                            ).fetchone()
                        except Exception:
                            row = None

                        if row:
                            if hasattr(row, "keys"):
                                e2 = _safe_int(row["Element_Id"], 0)
                                t2 = _safe_int(row["ToolTipImage_Id"], 0)
                            else:
                                e2 = _safe_int(row[0], 0)
                                t2 = _safe_int(row[1], 0)
                        else:
                            e2, t2 = 0, 0

                        c_cache[card_id] = (int(e2), int(t2))

                    if _safe_int(e2, 0) > 0 and _safe_int(t2, 0) > 0:
                        return self._get_image_pm(int(t2))

        # ------------------------------------------------------------
        # 2) fallback: пробуем через CardsWindow (как в рюкзаке)
        # ------------------------------------------------------------
        cw = getattr(self, "cards_window", None)
        fn = getattr(cw, "build_tooltip_cards_payload_for_item", None) if cw is not None else None
        if callable(fn):
            kind = None
            try:
                if slot_key:
                    kind = self._slot_kind(str(slot_key))
            except Exception:
                kind = None

            # CardsWindow обычно ждёт "weapon"/"equipment"
            kind = "weapon" if kind == "weapon" else "equipment"

            try:
                payload = fn(item, kind=kind, slot_key=slot_key)
            except TypeError:
                try:
                    payload = fn(item, kind=kind)
                except Exception:
                    payload = None
            except Exception:
                payload = None

            for icon_id, _name, _desc in (payload or []):
                iid = _safe_int(icon_id, 0)
                if iid > 0:
                    return self._get_image_pm(int(iid))

        # ------------------------------------------------------------
        # 3) fallback: старая логика через item["Element_Id"]
        # ------------------------------------------------------------
        elem_id = _safe_int(item.get("Element_Id"), 0)
        if elem_id <= 0:
            return None
        if conn is None:
            return None

        cache = getattr(self, "_element_icon_id_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._element_icon_id_cache = cache

        img_id = cache.get(elem_id)
        if img_id is None:
            try:
                row = conn.execute(
                    "SELECT ToolTipImage_Id FROM CardType WHERE Element_Id=? AND ToolTipImage_Id IS NOT NULL LIMIT 1",
                    (int(elem_id),),
                ).fetchone()
            except Exception:
                row = None

            if not row:
                cache[elem_id] = 0
                return None

            img_id = row["ToolTipImage_Id"] if hasattr(row, "keys") else row[0]
            img_id = _safe_int(img_id, 0)
            cache[elem_id] = img_id

        return self._get_image_pm(img_id) if img_id > 0 else None

    # =========================
    # Open picker (weapon/equipment) — one entry point
    # =========================
    def _open_picker_for_slot(self, slot_key: str) -> None:
        """
        Открывает окно выбора предметов для слота. Режим определяется DB-driven.
        Пытается вызвать существующие методы, чтобы не ломать проект.
        """
        if not slot_key:
            return

        kind = self._slot_kind(slot_key)
        is_weapon = (kind == "weapon")

        # Если слот не активен в текущем состоянии — не открываем выбор
        if not self._slot_is_active_in_current_state(slot_key):
            return

        # 1) если есть weapon_equipment_button — пробуем через него
        btn = getattr(self, "weapon_equipment_button", None)
        if btn is not None:
            # универсальные варианты
            for mname in ("open_for_slot", "open_slot", "open"):
                m = getattr(btn, mname, None)
                if callable(m):
                    try:
                        m(slot_key=slot_key, is_weapon=is_weapon, class_id=self._current_class_id())
                        return
                    except TypeError:
                        try:
                            m(slot_key, is_weapon)
                            return
                        except TypeError:
                            try:
                                m(slot_key)
                                return
                            except Exception:
                                pass

            # частные варианты
            if is_weapon:
                for mname in ("open_weapon", "open_weapon_cards", "open_weapon_picker"):
                    m = getattr(btn, mname, None)
                    if callable(m):
                        try:
                            m(slot_key)
                        except Exception:
                            pass
                        return
            else:
                for mname in ("open_equipment", "open_equipment_cards", "open_equipment_picker"):
                    m = getattr(btn, mname, None)
                    if callable(m):
                        try:
                            m(slot_key)
                        except Exception:
                            pass
                        return

        # 2) иначе пробуем через cards_window (если он умеет открывать пикер)
        cw = getattr(self, "cards_window", None)
        if cw is not None:
            for mname in ("open_for_slot", "open_slot", "open_picker", "open"):
                m = getattr(cw, mname, None)
                if callable(m):
                    try:
                        m(slot_key=slot_key, is_weapon=is_weapon, class_id=self._current_class_id())
                        return
                    except TypeError:
                        try:
                            m(slot_key, is_weapon)
                            return
                        except TypeError:
                            try:
                                m(slot_key)
                                return
                            except Exception:
                                pass

    # DB-логика ExtraSlot_Id (только если AllowExtraWeapon=1)
    def _class_can_use_extra_weapon(self) -> bool:
        """
        AllowExtraWeapon (с учётом наследования Base_Id).
        """
        cid = _safe_int(self._current_class_id(), 0)
        if cid <= 0:
            return False
        eff = self._class_effective(cid) or {}
        return _safe_int(eff.get("AllowExtraWeapon"), 0) == 1

    # оставим старое имя, чтобы не ломать вызовы
    def _class_can_use_spear_flag(self) -> bool:
        return self._class_can_use_extra_weapon()

    def resolve_slot_ids_for_ui_key(self, slot_key: str, *, class_id: Optional[int] = None) -> List[int]:
        """
        Возвращает список Slot_Id, которые допустимы для UI-слота.

        База: всегда собственный Slot_Id слота.
        ExtraWeapon: если AllowExtraWeapon=1, то в СЛОТ, указанный weapon.ExtraSlot_Id,
        дополнительно разрешаем предметы из weapon-slot (то есть Slot_Id оружия).
        """
        meta = self._slot_meta(slot_key)
        if not meta:
            return []

        if class_id is None:
            class_id = self._current_class_id()

        ids = [int(meta.id)]

        # ---- ExtraWeapon (НЕ про копьё) ----
        if self._class_can_use_extra_weapon():
            weapon_meta = self._slot_meta("weapon")
            if weapon_meta and weapon_meta.extra_slot_id:
                target_slot_id = int(weapon_meta.extra_slot_id)
                # если текущий UI-слот = целевой слот под "доп. оружие"
                if int(meta.id) == target_slot_id:
                    ids.append(int(weapon_meta.id))  # разрешаем и weapon-slot предметы

        # unique
        out = []
        seen = set()
        for x in ids:
            xi = _safe_int(x, 0)
            if xi and xi not in seen:
                seen.add(xi)
                out.append(xi)
        return out

    # =========================
    # CLASS (DB-driven)
    # =========================
    _CLASS_SELECT = """
        SELECT
            Id, Name, Base_Id,
            PrimaryStat_Id, EnergyStat_Id,
            IsMelee, AllowExtraWeapon,
            Specialization_Id, HpPerVitality,
            Image_Id
        FROM "Class"
        WHERE Id = ?
        LIMIT 1
    """

    def _row_to_dict(self, row, cols: List[str]) -> Optional[dict]:
        if not row:
            return None
        if hasattr(row, "keys"):
            return {c: row[c] for c in cols if c in row.keys()}
        try:
            return {cols[i]: row[i] for i in range(min(len(cols), len(row)))}
        except Exception:
            return None

    def _get_class_row(self, class_id: int) -> Optional[dict]:
        cid = _safe_int(class_id, 0)
        if cid <= 0:
            return None
        if cid in self._class_row_cache:
            return self._class_row_cache[cid]

        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None:
            return None

        cols = [
            "Id", "Name", "Base_Id",
            "PrimaryStat_Id", "EnergyStat_Id",
            "IsMelee", "AllowExtraWeapon",
            "Specialization_Id", "HpPerVitality",
            "Image_Id",
        ]
        try:
            row = conn.execute(self._CLASS_SELECT, (cid,)).fetchone()
        except Exception:
            row = None

        d = self._row_to_dict(row, cols)
        if d is not None:
            # нормализуем Base_Id (NULL/0 -> None)
            b = d.get("Base_Id")
            bi = _safe_int(b, 0)
            d["Base_Id"] = (bi if bi > 0 else None)
            self._class_row_cache[cid] = d
        return d

    def _class_lineage_ids(self, class_id: int) -> List[int]:
        """
        Возвращает линейку наследования: [self, base, base_of_base, ...] пока Base_Id не NULL.
        """
        cid = _safe_int(class_id, 0)
        if cid <= 0:
            return []
        if cid in self._class_lineage_cache:
            return list(self._class_lineage_cache[cid])

        out: List[int] = []
        seen: set[int] = set()
        cur = cid
        while cur and cur not in seen:
            seen.add(cur)
            out.append(cur)
            row = self._get_class_row(cur)
            cur = _safe_int((row or {}).get("Base_Id"), 0)

        self._class_lineage_cache[cid] = list(out)
        return out

    def _class_effective(self, class_id: int) -> dict:
        """
        Возвращает effective-поля класса с учётом наследования по Base_Id:
        наследуются PrimaryStat_Id, EnergyStat_Id, IsMelee, AllowExtraWeapon, HpPerVitality.
        """
        cid = _safe_int(class_id, 0)
        if cid <= 0:
            return {}

        if cid in self._class_effective_cache:
            return dict(self._class_effective_cache[cid])

        row = self._get_class_row(cid) or {}
        base_id = _safe_int(row.get("Base_Id"), 0)

        eff = dict(row)
        if base_id > 0:
            base_eff = self._class_effective(base_id)

            inheritable = ("PrimaryStat_Id", "EnergyStat_Id", "IsMelee", "AllowExtraWeapon", "HpPerVitality")
            for k in inheritable:
                if eff.get(k) is None:
                    eff[k] = base_eff.get(k)

        self._class_effective_cache[cid] = dict(eff)
        return eff

    def _allowed_equipment_ids_for(self, slot_id: int, class_id: int) -> set[int]:
        """
        Кешируем ids из data.list_equipment_for_slot(slot_id, class_id).
        """
        sid = _safe_int(slot_id, 0)
        cid = _safe_int(class_id, 0)
        if sid <= 0 or cid <= 0:
            return set()

        key = (sid, cid)
        if key in self._slot_allowed_ids_cache:
            return set(self._slot_allowed_ids_cache[key])

        ids: set[int] = set()
        try:
            rows = self.data.list_equipment_for_slot(sid, cid) or []
        except Exception:
            rows = []

        for r in rows:
            rid = 0
            try:
                if isinstance(r, dict):
                    rid = _safe_int(r.get("Id"), 0)
                else:
                    rid = _safe_int(r[0], 0)
            except Exception:
                rid = 0
            if rid:
                ids.add(rid)

        self._slot_allowed_ids_cache[key] = set(ids)
        return ids

    def _allowed_ids_for_slot_and_lineage(self, slot_key: str, lineage_ids: List[int]) -> set[int]:
        """
        Возвращает Id предметов, которые можно надеть в данный UI-слот для линейки классов.
        Slot_Id берём из БД. ExtraSlot_Id учитываем только если AllowExtraWeapon=1.
        """
        lineage = [_safe_int(x, 0) for x in (lineage_ids or []) if _safe_int(x, 0) > 0]
        if not lineage:
            return set()

        slot_ids = self.resolve_slot_ids_for_ui_key(slot_key, class_id=self._current_class_id())
        if not slot_ids:
            return set()

        out: set[int] = set()
        for sid in slot_ids:
            for cid in lineage:
                out |= self._allowed_equipment_ids_for(sid, cid)
        return out

    # =========================
    # EVENT / STATE / LOST CONTROL SELECTORS
    # =========================
    EVENT_NONE_MENU_TEXT = "Нет ивента"
    LOST_CONTROL_NONE_MENU_TEXT = "Не в контроле"

    def _init_event_selector_ui(self) -> None:
        # -----------------------
        # EVENT (extra_btn2)
        # -----------------------
        self._current_event_id: int = 0
        self._current_event_name: str = ""

        self.event_name_label = QLabel(self)
        self.event_name_label.setObjectName("currentEventLabel")
        self.event_name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.event_name_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.event_name_label.setStyleSheet(f"""
            QLabel#currentEventLabel {{
                background: transparent;
                color: {GOLD};
                font-weight: 700;
            }}
        """)
        self.event_name_label.hide()
        self.event_name_label.raise_()

        self._event_menu = _InfoBoardMenu(self)
        self._event_menu.setStyleSheet(f"""
            QMenu {{
                background:#1b1b1b;
                border:1px solid #666;
                border-radius:8px;
                padding:6px;
            }}
            QMenu::separator {{
                height:1px;
                background:#444;
                margin:6px 8px;
            }}
            QMenu::item {{
                color:#ddd;
                padding:6px 34px 6px 12px;
                background:transparent;
            }}
            QMenu::item:selected {{
                background:#2b2b2b;
                color:#fff;
                border-radius:4px;
            }}
            QMenu::item:checked {{
                color:{GOLD};
            }}
            QMenu::indicator {{
                subcontrol-origin: padding;
                subcontrol-position: right center;
                left: auto;
                right: 10px;
                width: 14px;
                height: 14px;
            }}
        """)

        # -----------------------
        # STATE (extra_btn1)
        # -----------------------
        self._current_state_id: int = 0
        self._current_state_name: str = ""

        self.state_name_label = QLabel(self)
        self.state_name_label.setObjectName("currentStateLabel")
        self.state_name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.state_name_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.state_name_label.setStyleSheet(f"""
            QLabel#currentStateLabel {{
                background: transparent;
                color: {GOLD};
                font-weight: 700;
            }}
        """)
        self.state_name_label.hide()
        self.state_name_label.raise_()
        self._state_menu = _InfoBoardMenu(self)
        _apply_popup_menu_style(self._state_menu)

        # -----------------------
        # LOST CONTROL (extra_btn3)
        # -----------------------
        self._current_lost_control_id: int = 0
        self._current_lost_control_name: str = self.LOST_CONTROL_NONE_MENU_TEXT
        self._current_lost_control_image_id: int = 0

        self.lost_control_status_label = _ControlStatusWidget(self)
        self.lost_control_status_label.setObjectName("currentLostControlLabel")
        self.lost_control_status_label.setStyleSheet("background: transparent;")
        self.lost_control_status_label.hide()
        self.lost_control_status_label.raise_()

        self._control_menu = _InfoBoardMenu(self)
        _apply_popup_menu_style(self._control_menu)

        # общий обработчик закрытия меню
        try:
            self._event_menu.aboutToHide.connect(self._on_event_menu_about_to_hide, Qt.ConnectionType.UniqueConnection)
        except Exception:
            self._event_menu.aboutToHide.connect(self._on_event_menu_about_to_hide)

        try:
            self._state_menu.aboutToHide.connect(self._on_event_menu_about_to_hide, Qt.ConnectionType.UniqueConnection)
        except Exception:
            self._state_menu.aboutToHide.connect(self._on_event_menu_about_to_hide)

        try:
            self._control_menu.aboutToHide.connect(self._on_event_menu_about_to_hide,
                                                   Qt.ConnectionType.UniqueConnection)
        except Exception:
            self._control_menu.aboutToHide.connect(self._on_event_menu_about_to_hide)

        # STATE: по умолчанию первое состояние из State
        rows_state = self._fetch_events_from_db("State")
        if rows_state:
            sid, sname = rows_state[0]
            self._set_current_event(int(sid), str(sname), kind="state")
        else:
            self._set_current_event(0, "", kind="state")

        # EVENT: по умолчанию "Нет ивента"
        self._set_current_event(0, "", kind="event")

        # CONTROL: по умолчанию "Не в контроле"
        self._set_current_event(0, self.LOST_CONTROL_NONE_MENU_TEXT, kind="control", image_id=0)

    def _fetch_events_from_db(self, table: str = "Event") -> List[Tuple[int, str]]:
        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None:
            return []

        table_norm = (table or "").strip().lower()
        if table_norm not in ("event", "state"):
            return []

        real_table = "Event" if table_norm == "event" else "State"

        try:
            rows = conn.execute(f'SELECT Id, Name FROM "{real_table}" ORDER BY Id').fetchall()
        except Exception:
            return []

        out: List[Tuple[int, str]] = []
        for r in rows or []:
            try:
                if hasattr(r, "keys"):
                    out.append((int(r["Id"]), str(r["Name"])))
                else:
                    out.append((int(r[0]), str(r[1])))
            except Exception:
                continue
        return out

    def _fetch_lost_controls_from_db(self) -> List[Tuple[int, str, int]]:
        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None:
            return []

        out: List[Tuple[int, str, int]] = []

        # Основное имя таблицы по твоему CREATE TABLE — LostControl.
        # Второе оставил как страховку под возможную опечатку LostContol.
        for table_name in ("LostControl", "LostContol"):
            try:
                rows = conn.execute(
                    f'SELECT Id, Name, Image_Id FROM "{table_name}" ORDER BY Id ASC'
                ).fetchall()
            except Exception:
                rows = None

            if rows is None:
                continue

            for r in rows or []:
                try:
                    if hasattr(r, "keys"):
                        rid = _safe_int(r["Id"], 0)
                        name = str(r["Name"] or "")
                        img_id = _safe_int(r["Image_Id"], 0)
                    else:
                        rid = _safe_int(r[0], 0)
                        name = str(r[1] or "")
                        img_id = _safe_int(r[2], 0)
                except Exception:
                    continue

                if rid > 0:
                    out.append((int(rid), name, int(img_id)))

            break

        return out

    def _rebuild_event_menu(self, kind: str = "event") -> None:
        kind = (kind or "event").strip().lower()
        is_state = (kind == "state")
        is_control = kind in ("control", "lostcontrol", "lost_control")

        if is_control:
            m = getattr(self, "_control_menu", None)
        else:
            m = getattr(self, "_state_menu" if is_state else "_event_menu", None)

        if m is None:
            return

        m.clear()

        # -----------------------
        # LOST CONTROL:
        # первым всегда "Не в контроле",
        # после него такой же separator, как у "Нет ивента",
        # дальше LostControl ORDER BY Id ASC.
        # -----------------------
        if is_control:
            current_id = int(getattr(self, "_current_lost_control_id", 0) or 0)

            db_rows = self._fetch_lost_controls_from_db()
            rows_for_width: List[Tuple[int, str, int]] = [
                (0, self.LOST_CONTROL_NONE_MENU_TEXT, 0)
            ]
            rows_for_width.extend(db_rows)

            try:
                fm = QFontMetrics(self.font())
                max_w = 0

                for _rid, name, img_id in rows_for_width:
                    text_w = int(fm.horizontalAdvance(str(name or "")))
                    icon_w = 26 if _safe_int(img_id, 0) > 0 else 0
                    max_w = max(max_w, text_w + icon_w + 34)

                menu_w = max(170, max_w)
            except Exception:
                menu_w = 190

            try:
                m.setMinimumWidth(int(menu_w))
            except Exception:
                pass

            def _add_control_row(rid: int, name: str, img_id: int) -> None:
                act = QWidgetAction(m)
                act.setData({
                    "id": int(rid),
                    "name": str(name or ""),
                    "image_id": int(img_id or 0),
                })

                try:
                    act.triggered.connect(
                        lambda _checked=False, a=act, k="control": self._on_event_action_triggered(a, k)
                    )
                except Exception:
                    pass

                pm = None
                if _safe_int(img_id, 0) > 0:
                    try:
                        pm = self._get_image_pm(int(img_id))
                    except Exception:
                        pm = None

                row = _LostControlMenuRow(
                    act,
                    name=str(name or ""),
                    icon_pm=pm,
                    checked=(int(rid) == int(current_id)),
                    width=int(menu_w),
                    parent=m,
                )

                act.setDefaultWidget(row)
                m.addAction(act)

            # Первый пункт: "Не в контроле"
            _add_control_row(0, self.LOST_CONTROL_NONE_MENU_TEXT, 0)

            # Разделитель как у "Нет ивента"
            if db_rows:
                m.addSeparator()

            # Остальные пункты из LostControl
            for rid, name, img_id in db_rows:
                _add_control_row(int(rid), str(name or ""), int(img_id or 0))

            return

        # -----------------------
        # STATE: только значения из State
        # -----------------------
        if is_state:
            rows = self._fetch_events_from_db("State")

            if not rows:
                a = m.addAction("State: пусто")
                a.setEnabled(False)
                return

            current_id = int(getattr(self, "_current_state_id", 0) or 0)
            ids = {int(rid) for rid, _ in rows}

            if current_id not in ids:
                sid, sname = rows[0]
                self._set_current_event(int(sid), str(sname), kind="state")
                current_id = int(sid)

            for rid, name in rows:
                act = m.addAction(name)
                act.setCheckable(True)
                act.setData(int(rid))
                act.setChecked(int(rid) == int(current_id))
                act.triggered.connect(
                    lambda _=False, a=act, k=kind: self._on_event_action_triggered(a, k)
                )

            return

        # -----------------------
        # EVENT: "Нет ивента" + список Event
        # -----------------------
        none_text = self.EVENT_NONE_MENU_TEXT
        current_id = int(getattr(self, "_current_event_id", 0) or 0)

        a0 = m.addAction(none_text)
        a0.setCheckable(True)
        a0.setData(0)
        a0.setChecked(current_id == 0)
        a0.triggered.connect(
            lambda _=False, act=a0, k=kind: self._on_event_action_triggered(act, k)
        )

        m.addSeparator()

        for rid, name in self._fetch_events_from_db("Event"):
            act = m.addAction(name)
            act.setCheckable(True)
            act.setData(int(rid))
            act.setChecked(int(rid) == int(current_id))
            act.triggered.connect(
                lambda _=False, a=act, k=kind: self._on_event_action_triggered(a, k)
            )

    def _on_event_button_clicked(self) -> None:
        btns = (getattr(self, "small_menu_btns", {}) or {})

        btn_state = btns.get("extra_btn1")
        btn_event = btns.get("extra_btn2")
        btn_control = btns.get("extra_btn3")

        sender_btn = self.sender()

        if sender_btn is btn_state:
            kind = "state"
        elif sender_btn is btn_event:
            kind = "event"
        elif sender_btn is btn_control:
            kind = "control"
        else:
            kind = "event"

        menu_by_kind = {
            "state": getattr(self, "_state_menu", None),
            "event": getattr(self, "_event_menu", None),
            "control": getattr(self, "_control_menu", None),
        }

        btn_by_kind = {
            "state": btn_state,
            "event": btn_event,
            "control": btn_control,
        }

        m = menu_by_kind.get(kind)
        sender_btn = btn_by_kind.get(kind)

        if m is None or sender_btn is None:
            return

        # закрываем все остальные меню
        for other_kind, other_menu in menu_by_kind.items():
            if other_kind == kind:
                continue

            try:
                if other_menu is not None and other_menu.isVisible():
                    other_menu.hide()
            except Exception:
                pass

            other_btn = btn_by_kind.get(other_kind)
            try:
                if other_btn is not None:
                    other_btn.setChecked(False)
                    other_btn.setDown(False)
                    other_btn.update()
            except Exception:
                pass

        # если это же меню уже открыто — закрываем
        try:
            if m.isVisible():
                m.hide()
                sender_btn.setChecked(False)
                sender_btn.setDown(False)
                sender_btn.update()
                return
        except Exception:
            pass

        # пересобрать пункты перед показом
        try:
            self._rebuild_event_menu(kind)
        except Exception:
            pass

        # держим кнопку нажатой, пока меню открыто
        try:
            sender_btn.setChecked(True)
            sender_btn.setDown(False)
            sender_btn.update()
        except Exception:
            pass

        # popup под кнопкой
        try:
            gp = sender_btn.mapToGlobal(QPoint(0, sender_btn.height() + 2))
            m.popup(gp)
        except Exception:
            try:
                sender_btn.setChecked(False)
                sender_btn.setDown(False)
                sender_btn.update()
            except Exception:
                pass

    def _on_event_menu_about_to_hide(self) -> None:
        btns = (getattr(self, "small_menu_btns", {}) or {})

        btn_state = btns.get("extra_btn1")
        btn_event = btns.get("extra_btn2")
        btn_control = btns.get("extra_btn3")

        s = self.sender()

        try:
            if s is getattr(self, "_state_menu", None) and btn_state:
                btn_state.setChecked(False)
                btn_state.setDown(False)
                btn_state.update()

            elif s is getattr(self, "_event_menu", None) and btn_event:
                btn_event.setChecked(False)
                btn_event.setDown(False)
                btn_event.update()

            elif s is getattr(self, "_control_menu", None) and btn_control:
                btn_control.setChecked(False)
                btn_control.setDown(False)
                btn_control.update()

        except Exception:
            pass

    def _on_event_action_triggered(self, act, kind: str = "event") -> None:
        kind = (kind or "event").strip().lower()
        is_control = kind in ("control", "lostcontrol", "lost_control")

        rid = 0
        name = ""
        image_id = 0

        if is_control:
            data = None
            try:
                data = act.data()
            except Exception:
                data = None

            if isinstance(data, dict):
                rid = _safe_int(data.get("id"), 0)
                name = str(data.get("name") or "")
                image_id = _safe_int(data.get("image_id"), 0)
            else:
                try:
                    rid = int(data or 0)
                except Exception:
                    rid = 0

            if rid == 0:
                name = self.LOST_CONTROL_NONE_MENU_TEXT
                image_id = 0

            self._set_current_event(rid, name, kind="control", image_id=image_id)

            try:
                if getattr(self, "_control_menu", None) is not None:
                    self._control_menu.hide()
            except Exception:
                pass

        else:
            try:
                rid = int(act.data() or 0)
            except Exception:
                rid = 0

            if rid != 0:
                try:
                    name = str(act.text() or "")
                except Exception:
                    name = ""

            self._set_current_event(rid, name, kind=kind)

        try:
            self.refresh_stats_panel()
        except Exception:
            pass

    def _set_current_event(
            self,
            event_id: int,
            event_name: str,
            kind: str = "event",
            *,
            image_id: int = 0,
    ) -> None:
        kind = (kind or "event").strip().lower()

        if kind == "state":
            self._current_state_id = int(event_id or 0)
            self._current_state_name = str(event_name or "")
            self._update_event_label_text(kind="state")
            return

        if kind in ("control", "lostcontrol", "lost_control"):
            cid = int(event_id or 0)

            self._current_lost_control_id = cid
            self._current_lost_control_name = (
                str(event_name or "").strip()
                if cid > 0
                else self.LOST_CONTROL_NONE_MENU_TEXT
            )
            self._current_lost_control_image_id = int(image_id or 0)

            # Пока математику не подключаем, но состояние уже можно читать оттуда.
            try:
                app = QApplication.instance()
                if app is not None:
                    app.setProperty("player_lost_control_id", int(self._current_lost_control_id))
                    app.setProperty("player_lost_control_name", str(self._current_lost_control_name))
                    app.setProperty("player_lost_control_image_id", int(self._current_lost_control_image_id))
            except Exception:
                pass

            self._update_event_label_text(kind="control")
            return

        self._current_event_id = int(event_id or 0)
        self._current_event_name = str(event_name or "")
        self._update_event_label_text(kind="event")

    def _update_event_label_text(self, kind: str = "event") -> None:
        kind = (kind or "event").strip().lower()

        # -------- LOST CONTROL --------
        if kind in ("control", "lostcontrol", "lost_control"):
            lbl = getattr(self, "lost_control_status_label", None)
            if lbl is None:
                return

            cur_id = int(getattr(self, "_current_lost_control_id", 0) or 0)
            cur_name = str(getattr(self, "_current_lost_control_name", "") or "")
            img_id = int(getattr(self, "_current_lost_control_image_id", 0) or 0)

            if cur_id == 0 or not cur_name:
                cur_name = self.LOST_CONTROL_NONE_MENU_TEXT
                img_id = 0

            pm = None
            if img_id > 0:
                try:
                    pm = self._get_image_pm(int(img_id))
                except Exception:
                    pm = None

            try:
                lbl.set_payload(cur_name, pm)
            except Exception:
                pass

            return

        is_state = (kind == "state")
        lbl = getattr(self, "state_name_label" if is_state else "event_name_label", None)

        if lbl is None:
            return

        # -------- STATE --------
        if is_state:
            cur_id = int(getattr(self, "_current_state_id", 0) or 0)
            cur_name = str(getattr(self, "_current_state_name", "") or "")

            if (cur_id == 0) or (not cur_name):
                rows = self._fetch_events_from_db("State")
                if rows:
                    sid, sname = rows[0]
                    self._current_state_id = int(sid)
                    self._current_state_name = str(sname)
                    cur_name = str(sname)

            full = cur_name or ""
            lbl.setToolTip(full)

            w = max(10, lbl.width() - 6)
            fm = QFontMetrics(lbl.font())
            lbl.setText(fm.elidedText(full, Qt.ElideRight, w))
            return

        # -------- EVENT --------
        cur_id = int(getattr(self, "_current_event_id", 0) or 0)
        cur_name = str(getattr(self, "_current_event_name", "") or "")
        none_text = self.EVENT_NONE_MENU_TEXT

        if cur_id == 0:
            full = none_text
            lbl.setToolTip(none_text)
        else:
            full = cur_name or none_text
            lbl.setToolTip(full)

        w = max(10, lbl.width() - 6)
        fm = QFontMetrics(lbl.font())
        lbl.setText(fm.elidedText(full, Qt.ElideRight, w))

    def _layout_event_selector_ui(self) -> None:
        """
        Раскладывает:
          • State label справа от extra_btn1;
          • Event label справа от extra_btn2;
          • LostControl status в области 83x20 от (395,10).
        """
        btns = (getattr(self, "small_menu_btns", {}) or {})

        btn_state = btns.get("extra_btn1")
        btn_event = btns.get("extra_btn2")
        btn_control = btns.get("extra_btn3")

        lbl_state = getattr(self, "state_name_label", None)
        lbl_event = getattr(self, "event_name_label", None)
        lbl_control = getattr(self, "lost_control_status_label", None)

        if (
                not btn_state
                or not btn_event
                or not btn_control
                or lbl_state is None
                or lbl_event is None
                or lbl_control is None
        ):
            return

        pm = self.board_label.pixmap()
        if not pm:
            return

        sx = self._scale()
        ir = self._img_rect()

        # общий шрифт под scale
        try:
            base_pt = 10
            pt = int(max(8, min(14, round(base_pt * sx))))
            for lbl in (lbl_state, lbl_event, lbl_control):
                f = lbl.font()
                f.setPointSize(pt)
                lbl.setFont(f)
        except Exception:
            pass

        gap = max(2, int(6 * sx))

        # -------------------------
        # STATE: справа от btn_state, до btn_event
        # -------------------------
        left_s = btn_state.x() + btn_state.width() + gap
        right_s = btn_event.x() - gap
        avail_s = max(1, right_s - left_s)
        max_w_s = max(60, int(160 * sx))
        w_s = max(1, min(max_w_s, avail_s))

        lbl_state.setGeometry(left_s, btn_state.y(), w_s, btn_state.height())
        lbl_state.show()
        lbl_state.raise_()
        self._update_event_label_text(kind="state")

        # -------------------------
        # EVENT: справа от btn_event, до кнопки контроля
        # -------------------------
        left_e = btn_event.x() + btn_event.width() + gap
        right_e = btn_control.x() - gap
        avail_e = max(1, right_e - left_e)
        max_w_e = max(60, int(180 * sx))
        w_e = max(1, min(max_w_e, avail_e))

        lbl_event.setGeometry(left_e, btn_event.y(), w_e, btn_event.height())
        lbl_event.show()
        lbl_event.raise_()
        self._update_event_label_text(kind="event")

        # -------------------------
        # LOST CONTROL:
        # область 83x20 от координат PNG (395,10)
        # -------------------------
        try:
            control_rect = self._project(395, 10, 83, 20)
        except Exception:
            control_rect = QRect(
                int(ir.x() + 395 * sx),
                int(ir.y() + 10 * sx),
                max(1, int(83 * sx)),
                max(1, int(20 * sx)),
            )

        lbl_control.setGeometry(control_rect)
        lbl_control.show()
        lbl_control.raise_()
        self._update_event_label_text(kind="control")

    def get_current_event_id(self) -> int:
        return int(getattr(self, "_current_event_id", 0) or 0)

    def get_current_event_name(self) -> str:
        return str(getattr(self, "_current_event_name", "") or "")

    def get_current_state_id(self) -> int:
        return int(getattr(self, "_current_state_id", 0) or 0)

    def get_current_state_name(self) -> str:
        return str(getattr(self, "_current_state_name", "") or "")

    def get_current_lost_control_id(self) -> int:
        return int(getattr(self, "_current_lost_control_id", 0) or 0)

    def get_current_lost_control_name(self) -> str:
        return str(getattr(self, "_current_lost_control_name", "") or "")

    def get_current_lost_control_image_id(self) -> int:
        return int(getattr(self, "_current_lost_control_image_id", 0) or 0)

    # ---------- утилиты ----------
    def _ensure_other_stats_panel(self) -> None:
        panel = getattr(self, "other_stats_panel", None)
        if panel is not None:
            return

        panel = OtherCharacteristicsPanel(self, conn=self.data.conn)
        panel.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        panel.setEnabled(True)
        panel.setMouseTracking(True)

        fn = getattr(panel, "set_param_state", None)
        if callable(fn):
            fn(self.param_points)

        try:
            panel.set_group("extra")
        except Exception:
            pass

        # если статы уже были посчитаны до первого открытия правого борда — сразу зальём их
        try:
            cur_stats = getattr(self, "character_stats", None)
            if isinstance(cur_stats, dict) and cur_stats:
                panel.update_by_id(cur_stats)
        except Exception:
            pass

        panel.hide()
        self.other_stats_panel = panel

    def _ensure_other_menu_ui(self) -> None:
        if getattr(self, "_other_menu_ui_ready", False):
            return

        self._other_menu_ui_ready = True
        self._other_menu_open = False

        self._other_menu_pm = _load_file_image(OTHER_MENU_BG_PATH)

        open_hover = (_resolve_resource(OTHER_MENU_OPEN_HOVER_PATH) or OTHER_MENU_OPEN_HOVER_PATH).replace("\\", "/")
        open_press = (_resolve_resource(OTHER_MENU_OPEN_PRESS_PATH) or OTHER_MENU_OPEN_PRESS_PATH).replace("\\", "/")
        close_hover = (_resolve_resource(OTHER_MENU_CLOSE_HOVER_PATH) or OTHER_MENU_CLOSE_HOVER_PATH).replace("\\", "/")
        close_press = (_resolve_resource(OTHER_MENU_CLOSE_PRESS_PATH) or OTHER_MENU_CLOSE_PRESS_PATH).replace("\\", "/")

        self.other_menu_bg = QLabel(self)
        self.other_menu_bg.setObjectName("otherMenuBg")
        self.other_menu_bg.setStyleSheet("background: transparent;")
        self.other_menu_bg.setAttribute(Qt.WA_TranslucentBackground, True)

        # ВАЖНО:
        # фон правой менюшки должен получать мышь,
        # чтобы с него можно было таскать весь MainWindow
        self.other_menu_bg.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.other_menu_bg.setScaledContents(True)
        self.other_menu_bg.setMouseTracking(True)
        self.other_menu_bg.hide()

        def _other_menu_bg_mouse_press(ev):
            if ev.button() != Qt.LeftButton:
                return QLabel.mousePressEvent(self.other_menu_bg, ev)

            try:
                gp = ev.globalPosition().toPoint()
            except Exception:
                try:
                    gp = ev.globalPos()
                except Exception:
                    gp = QCursor.pos()

            self._drag_pos = gp - self.frameGeometry().topLeft()
            ev.accept()

        def _other_menu_bg_mouse_move(ev):
            if self._drag_pos and (ev.buttons() & Qt.LeftButton):
                try:
                    gp = ev.globalPosition().toPoint()
                except Exception:
                    try:
                        gp = ev.globalPos()
                    except Exception:
                        gp = QCursor.pos()

                self.move(gp - self._drag_pos)
                ev.accept()
                return

            QLabel.mouseMoveEvent(self.other_menu_bg, ev)

        def _other_menu_bg_mouse_release(ev):
            if ev.button() == Qt.LeftButton:
                self._drag_pos = None
                ev.accept()
                return

            QLabel.mouseReleaseEvent(self.other_menu_bg, ev)

        self.other_menu_bg.mousePressEvent = _other_menu_bg_mouse_press  # type: ignore[assignment]
        self.other_menu_bg.mouseMoveEvent = _other_menu_bg_mouse_move  # type: ignore[assignment]
        self.other_menu_bg.mouseReleaseEvent = _other_menu_bg_mouse_release  # type: ignore[assignment]

        self.other_menu_open_btn = QToolButton(self)
        self.other_menu_open_btn.setObjectName("otherMenuOpenBtn")
        self.other_menu_open_btn.setCursor(Qt.PointingHandCursor)
        self.other_menu_open_btn.setAutoRaise(True)
        self.other_menu_open_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.other_menu_open_btn.setFocusPolicy(Qt.NoFocus)
        self.other_menu_open_btn.setAttribute(Qt.WA_TranslucentBackground, True)
        self.other_menu_open_btn.setAutoFillBackground(False)
        self.other_menu_open_btn.setStyleSheet(f"""
            QToolButton#otherMenuOpenBtn {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
            QToolButton#otherMenuOpenBtn:hover {{
                border-image: url("{open_hover}");
            }}
            QToolButton#otherMenuOpenBtn:pressed {{
                border-image: url("{open_press}");
            }}
            QToolButton#otherMenuOpenBtn:disabled {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
        """)
        try:
            self.other_menu_open_btn.clicked.connect(
                self._on_other_menu_open_clicked,
                Qt.ConnectionType.UniqueConnection,
            )
        except Exception:
            self.other_menu_open_btn.clicked.connect(self._on_other_menu_open_clicked)
        self.other_menu_open_btn.hide()

        self.other_menu_close_btn = QToolButton(self)
        self.other_menu_close_btn.setObjectName("otherMenuCloseBtn")
        self.other_menu_close_btn.setCursor(Qt.PointingHandCursor)
        self.other_menu_close_btn.setAutoRaise(True)
        self.other_menu_close_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.other_menu_close_btn.setFocusPolicy(Qt.NoFocus)
        self.other_menu_close_btn.setAttribute(Qt.WA_TranslucentBackground, True)
        self.other_menu_close_btn.setAutoFillBackground(False)
        self.other_menu_close_btn.setStyleSheet(f"""
            QToolButton#otherMenuCloseBtn {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
            QToolButton#otherMenuCloseBtn:hover {{
                border-image: url("{close_hover}");
            }}
            QToolButton#otherMenuCloseBtn:pressed {{
                border-image: url("{close_press}");
            }}
        """)
        try:
            self.other_menu_close_btn.clicked.connect(
                self._on_other_menu_close_clicked,
                Qt.ConnectionType.UniqueConnection,
            )
        except Exception:
            self.other_menu_close_btn.clicked.connect(self._on_other_menu_close_clicked)
        self.other_menu_close_btn.hide()

    def _on_other_menu_open_clicked(self) -> None:
        self._set_other_menu_open(True)

    def _on_other_menu_close_clicked(self) -> None:
        self._set_other_menu_open(False)

    def _set_other_menu_open(self, opened: bool) -> None:
        self._ensure_other_menu_ui()

        opened = bool(opened)
        self._other_menu_open = opened

        # При переключении меню сразу убираем старые hover-слои,
        # чтобы текст "Прочее" не зависал на старой области.
        try:
            self._hide_hover_name_label()
        except Exception:
            pass

        for nm in ("menu_glow", "hover_glow", "winbtn_hover"):
            try:
                w = getattr(self, nm, None)
                if w is not None:
                    w.hide()
            except Exception:
                pass

        # ВАЖНО:
        # кнопку открытия НЕ прячем.
        # Иначе при первом запуске зона может не попасть в _zones_screen.
        # Пока меню открыто — просто отключаем клики по ней,
        # а hover-зону отсекаем в _hit_zone().
        try:
            self.other_menu_open_btn.setEnabled(not opened)
            self.other_menu_open_btn.setVisible(True)
        except Exception:
            pass

        # Сначала меняем физический размер main window,
        # потом раскладываем оверлеи и пересобираем зоны.
        self._update_board_pixmap()
        self._layout_overlays()

        try:
            self._recalc_zones()
        except Exception:
            pass

        try:
            if getattr(self, "_hover_timer", None) is not None and not self._hover_timer.isActive():
                self._hover_timer.start()
        except Exception:
            pass

        QTimer.singleShot(0, self._update_glow_from_global)

    def _layout_other_menu(self) -> None:
        self._ensure_other_menu_ui()
        self._ensure_other_stats_panel()

        ir = self._img_rect()
        if ir.isEmpty():
            try:
                self.other_menu_bg.hide()
                self.other_menu_close_btn.hide()
                self.other_menu_open_btn.hide()
            except Exception:
                pass

            try:
                panel = getattr(self, "other_stats_panel", None)
                if panel is not None:
                    panel.hide()
            except Exception:
                pass

            return

        sx = self._scale()
        opened = bool(getattr(self, "_other_menu_open", False))

        # --- кнопка открытия на основной борде ---
        bx, by, bw, bh = OTHER_MENU_OPEN_BTN_RECT
        open_rect = self._project(int(bx), int(by), int(bw), int(bh))

        # ВАЖНО:
        # кнопку открытия всегда держим разложенной и видимой.
        # Когда Прочее открыто — она отключена, но не исчезает из layout.
        try:
            self.other_menu_open_btn.setGeometry(open_rect)
            self.other_menu_open_btn.setVisible(True)
            self.other_menu_open_btn.setEnabled(not opened)
            if not opened:
                self.other_menu_open_btn.raise_()
        except Exception:
            pass

        pm = getattr(self, "_other_menu_pm", None)
        if pm is None or pm.isNull():
            try:
                self.other_menu_bg.hide()
                self.other_menu_close_btn.hide()
            except Exception:
                pass

            try:
                panel = getattr(self, "other_stats_panel", None)
                if panel is not None:
                    panel.hide()
            except Exception:
                pass

            try:
                self.other_menu_open_btn.show()
                self.other_menu_open_btn.raise_()
            except Exception:
                pass

            return

        if not opened:
            try:
                self.other_menu_bg.hide()
                self.other_menu_close_btn.hide()
            except Exception:
                pass

            try:
                panel = getattr(self, "other_stats_panel", None)
                if panel is not None:
                    panel.hide()
            except Exception:
                pass

            try:
                self.other_menu_open_btn.show()
                self.other_menu_open_btn.raise_()
            except Exception:
                pass

            return

        # Меню открыто — старую подсказку/hover от кнопки открытия убрать.
        try:
            self._hide_hover_name_label()
        except Exception:
            pass

        menu_w = max(1, int(pm.width() * sx))
        menu_h = max(1, int(pm.height() * sx))
        overlap = int(OTHER_MENU_OVERLAP_PX * sx)

        # меню начинается от правого края основной борды
        menu_x = int(ir.right() - overlap + 1)
        menu_y = int(ir.top())

        scaled_pm = pm.scaled(menu_w, menu_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.other_menu_bg.setPixmap(scaled_pm)
        self.other_menu_bg.setGeometry(menu_x, menu_y, menu_w, menu_h)
        self.other_menu_bg.show()

        # --- кнопка закрытия ---
        cx, cy, cw, ch = OTHER_MENU_CLOSE_BTN_RECT
        close_rect = QRect(
            int(menu_x + cx * sx),
            int(menu_y + cy * sx),
            max(1, int(cw * sx)),
            max(1, int(ch * sx)),
        )
        self.other_menu_close_btn.setGeometry(close_rect)
        self.other_menu_close_btn.show()

        # --- панель статов поверх правого борда ---
        panel = getattr(self, "other_stats_panel", None)
        if panel is not None:
            panel_x = int(menu_x)
            panel_y = int(menu_y + 36)
            panel_w = int(menu_w)
            panel_h = max(1, int(menu_h - 36))

            panel.setGeometry(panel_x, panel_y, panel_w, panel_h)
            panel.show()

            try:
                cur_stats = getattr(self, "character_stats", None)
                if isinstance(cur_stats, dict) and cur_stats:
                    panel.update_by_id(cur_stats)
            except Exception:
                pass

        # порядок слоёв
        self.other_menu_bg.raise_()
        if panel is not None:
            panel.raise_()
        self.other_menu_close_btn.raise_()

        # кнопка открытия остаётся под правым меню,
        # но её зона будет игнорироваться в _hit_zone(), пока меню открыто.
        try:
            self.other_menu_open_btn.stackUnder(self.other_menu_bg)
        except Exception:
            pass

        # main close/minimize должны быть поверх правой менюшки
        self.close_btn.raise_()
        self.minimize_btn.raise_()
        self.winbtn_hover.raise_()

        try:
            self.hover_name_label.raise_()
        except Exception:
            pass

    def _init_small_menu_buttons(self) -> None:
        """
        Создаёт маленькие кнопки:
          extra_btn1: State selector
          extra_btn2: Event selector
          extra_btn3: LostControl selector

        Все держат "нажатую" картинку пока меню открыто.
        """
        off_path = (_resolve_resource(SMALL_MENU_BTN_OFF_PATH) or SMALL_MENU_BTN_OFF_PATH).replace("\\", "/")
        down_path = (_resolve_resource(SMALL_MENU_BTN_DOWN_PATH) or SMALL_MENU_BTN_DOWN_PATH).replace("\\", "/")

        self.small_menu_btns: Dict[str, QToolButton] = {}

        for b in SMALL_MENU_BTNS:
            key = b["key"]

            btn = QToolButton(self)
            btn.setObjectName(f"smallMenuBtn_{key}")
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            btn.setAutoRaise(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setAttribute(Qt.WA_TranslucentBackground, True)
            btn.setAutoFillBackground(False)
            btn.setFocusPolicy(Qt.NoFocus)

            btn.setStyleSheet(f"""
                QToolButton#{btn.objectName()} {{
                    background: transparent;
                    border: none;
                    padding: 0px;
                    border-image: url("{off_path}");
                }}
                QToolButton#{btn.objectName()}:pressed {{
                    border-image: url("{down_path}");
                }}
                QToolButton#{btn.objectName()}:checked {{
                    border-image: url("{down_path}");
                }}
            """)

            if key in ("extra_btn1", "extra_btn2", "extra_btn3"):
                btn.setCheckable(True)
                btn.setChecked(False)
                try:
                    btn.clicked.connect(self._on_event_button_clicked, Qt.ConnectionType.UniqueConnection)
                except Exception:
                    btn.clicked.connect(self._on_event_button_clicked)
            else:
                try:
                    btn.clicked.connect(lambda _=False: None, Qt.ConnectionType.UniqueConnection)
                except Exception:
                    btn.clicked.connect(lambda _=False: None)

            btn.hide()
            btn.raise_()
            self.small_menu_btns[key] = btn

    def _on_event_button_pressed(self) -> None:
        btn = (getattr(self, "small_menu_btns", {}) or {}).get("extra_btn2")
        m = getattr(self, "_event_menu", None)
        if not btn or m is None:
            return

        # обновляем пункты
        try:
            self._rebuild_event_menu()
        except Exception:
            pass

        # позиция "чуть ниже кнопки"
        gp = btn.mapToGlobal(QPoint(0, btn.height() + 2))

        # важно: показать на следующем тике, чтобы не схлопнулось/не проглотилось
        QTimer.singleShot(0, lambda _gp=gp: m.popup(_gp))

    def _place_small_menu_buttons(self) -> None:
        """
        Позиционирует маленькие кнопки State/Event/LostControl,
        кнопку общего меню, кнопку окна подсказок,
        а также 3 кнопки быстрого просмотра активных бафов/дебафов.
        """
        pm = self.board_label.pixmap()
        if not pm:
            try:
                btn = getattr(self, "total_menu_btn", None)
                if btn is not None:
                    btn.hide()
            except Exception:
                pass

            try:
                btn = getattr(self, "helper_menu_btn", None)
                if btn is not None:
                    btn.hide()
            except Exception:
                pass

            try:
                for btn in (getattr(self, "_active_buff_preview_btns", {}) or {}).values():
                    if btn is not None:
                        btn.hide()
            except Exception:
                pass

            try:
                self._close_active_buff_preview()
            except Exception:
                pass

            return

        sx = self._scale()
        ir = self._img_rect()

        w0, h0 = SMALL_MENU_BTN_W, SMALL_MENU_BTN_H

        for b in SMALL_MENU_BTNS:
            key = b["key"]
            btn = (getattr(self, "small_menu_btns", {}) or {}).get(key)
            if not btn:
                continue

            x0, y0 = b["pos"]
            X = int(ir.x() + x0 * sx)
            Y = int(ir.y() + y0 * sx)
            W = max(1, int(w0 * sx))
            H = max(1, int(h0 * sx))

            btn.setGeometry(X, Y, W, H)
            btn.show()
            btn.raise_()

        self._place_active_buff_preview_buttons()

        self._layout_total_menu_button()
        self._layout_helper_menu_button()

    def _active_buff_preview_spec(self, key: str) -> Optional[dict]:
        key = str(key or "").strip()

        for spec in ACTIVE_BUFF_PREVIEW_BTNS:
            if str(spec.get("key") or "") == key:
                return dict(spec)

        return None

    def _init_active_buff_preview_buttons(self) -> None:
        """
        Создаёт 3 кнопки быстрого просмотра активных эффектов:
          верхняя  — все бафы кроме личных и дебафов;
          средняя — личные бафы;
          нижняя  — дебафы.

        Нажатие обрабатывается вручную через press/release, чтобы QToolButton
        не залипал в checked-состоянии при пустом списке.
        """
        active_path = (
                _resolve_resource(ACTIVE_BUFF_PREVIEW_BTN_ACTIVE_PATH)
                or ACTIVE_BUFF_PREVIEW_BTN_ACTIVE_PATH
        ).replace("\\", "/")

        self._active_buff_preview_btns: Dict[str, QToolButton] = {}
        self._active_buff_preview_open_key: str = ""

        panel = getattr(self, "_active_buff_preview_panel", None)
        if not isinstance(panel, _ActiveBuffPreviewPanel):
            panel = _ActiveBuffPreviewPanel(self)
            panel.set_owner(self)
            panel.hide()
            self._active_buff_preview_panel = panel

        def _event_pos(ev) -> QPoint:
            try:
                return ev.position().toPoint()
            except Exception:
                pass

            try:
                return ev.pos()
            except Exception:
                return QPoint(-9999, -9999)

        for spec in ACTIVE_BUFF_PREVIEW_BTNS:
            key = str(spec.get("key") or "").strip()
            if not key:
                continue

            btn = QToolButton(self)
            btn.setObjectName(f"activeBuffPreviewBtn_{key}")
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            btn.setAutoRaise(True)
            btn.setCheckable(True)
            btn.setChecked(False)

            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setAttribute(Qt.WA_TranslucentBackground, True)
            btn.setAutoFillBackground(False)
            btn.setMouseTracking(True)
            btn.setProperty("_buff_preview_pressed", False)

            btn.setStyleSheet(f"""
                QToolButton#{btn.objectName()} {{
                    background: transparent;
                    border: none;
                    padding: 0px;
                }}
                QToolButton#{btn.objectName()}:hover {{
                    border-image: url("{active_path}");
                }}
                QToolButton#{btn.objectName()}:pressed {{
                    border-image: url("{active_path}");
                }}
                QToolButton#{btn.objectName()}:checked {{
                    border-image: url("{active_path}");
                }}
            """)

            def _make_mouse_press(_btn: QToolButton, _key: str):
                def _mouse_press(ev) -> None:
                    if ev.button() != Qt.LeftButton:
                        QToolButton.mousePressEvent(_btn, ev)
                        return

                    _btn.setProperty("_buff_preview_pressed", True)
                    _btn.setDown(True)
                    ev.accept()

                return _mouse_press

            def _make_mouse_release(_btn: QToolButton, _key: str):
                def _mouse_release(ev) -> None:
                    if ev.button() != Qt.LeftButton:
                        QToolButton.mouseReleaseEvent(_btn, ev)
                        return

                    pos = _event_pos(ev)
                    over = _btn.rect().contains(pos)
                    was_pressed = bool(_btn.property("_buff_preview_pressed"))

                    _btn.setProperty("_buff_preview_pressed", False)
                    _btn.setDown(False)

                    if was_pressed and over:
                        try:
                            self._toggle_active_buff_preview(_key)
                        except Exception:
                            try:
                                self._close_active_buff_preview()
                            except Exception:
                                pass

                        ev.accept()
                        return

                    try:
                        self._set_active_buff_preview_button_state(
                            str(getattr(self, "_active_buff_preview_open_key", "") or "")
                        )
                    except Exception:
                        pass

                    ev.accept()

                return _mouse_release

            btn.mousePressEvent = _make_mouse_press(btn, key)  # type: ignore[assignment]
            btn.mouseReleaseEvent = _make_mouse_release(btn, key)  # type: ignore[assignment]

            btn.hide()
            btn.raise_()

            self._active_buff_preview_btns[key] = btn

    def _place_active_buff_preview_buttons(self) -> None:
        pm = self.board_label.pixmap()
        btns = getattr(self, "_active_buff_preview_btns", None)

        if not pm or not isinstance(btns, dict):
            try:
                for btn in (btns or {}).values():
                    if btn is not None:
                        btn.hide()
            except Exception:
                pass

            try:
                self._close_active_buff_preview()
            except Exception:
                pass

            return

        sx = self._scale()
        ir = self._img_rect()

        x0, y0 = ACTIVE_BUFF_PREVIEW_BTN_FIRST_POS
        w0 = ACTIVE_BUFF_PREVIEW_BTN_W
        h0 = ACTIVE_BUFF_PREVIEW_BTN_H
        gap0 = ACTIVE_BUFF_PREVIEW_BTN_GAP_Y

        for spec in ACTIVE_BUFF_PREVIEW_BTNS:
            key = str(spec.get("key") or "").strip()
            idx = _safe_int(spec.get("index"), 0)

            btn = btns.get(key)
            if btn is None:
                continue

            x = int(ir.x() + x0 * sx)
            y = int(ir.y() + (y0 + idx * (h0 + gap0)) * sx)
            w = max(1, int(w0 * sx))
            h = max(1, int(h0 * sx))

            btn.setGeometry(int(x), int(y), int(w), int(h))
            btn.show()
            btn.raise_()

        try:
            panel = getattr(self, "_active_buff_preview_panel", None)
            if isinstance(panel, _ActiveBuffPreviewPanel) and panel.isVisible():
                self._position_active_buff_preview_panel()
                panel.raise_()
        except Exception:
            pass

    def _set_active_buff_preview_button_state(self, active_key: str) -> None:
        active_key = str(active_key or "").strip()

        states_before = {}
        try:
            states_before = {
                str(key): bool(btn.isChecked())
                for key, btn in (getattr(self, "_active_buff_preview_btns", {}) or {}).items()
                if btn is not None
            }
        except Exception:
            states_before = {}

        for key, btn in (getattr(self, "_active_buff_preview_btns", {}) or {}).items():
            btn.setChecked(str(key) == active_key)
            btn.setDown(False)
            btn.update()

        states_after = {}
        try:
            states_after = {
                str(key): bool(btn.isChecked())
                for key, btn in (getattr(self, "_active_buff_preview_btns", {}) or {}).items()
                if btn is not None
            }
        except Exception:
            states_after = {}

    def _active_buff_preview_items_for_mode(self, mode: str) -> list[dict]:
        """
        Возвращает активные эффекты для ряда иконок слева от кнопки.
        """
        mode = str(mode or "").strip().lower()

        if mode in ("debuff", "debuffs", "negative", "negate"):
            allowed_tabs = {"tab6"}
        elif mode in ("personal", "self", "личные"):
            allowed_tabs = {"tab1"}
        else:
            allowed_tabs = {"tab2", "tab3", "tab4", "tab5"}

        out: list[dict] = []

        try:
            app = QApplication.instance()
            raw = app.property("player_buff_preview_items") if app is not None else None
        except Exception:
            raw = None

        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue

                tab = str(item.get("Tab") or item.get("tab") or "").strip().lower()
                bonus_text = str(item.get("BonusText") or "").strip()

                if tab not in allowed_tabs:
                    continue

                if not bonus_text or bonus_text.casefold() == "нет":
                    continue

                payload = dict(item)

                image_id = _safe_int(
                    payload.get("Image_Id") or payload.get("ImageId") or payload.get("image_id"),
                    0,
                )

                pm = payload.get("IconPixmap")
                if not isinstance(pm, QPixmap) or pm.isNull():
                    try:
                        pm = self._get_image_pm(int(image_id)) if image_id > 0 else QPixmap()
                    except Exception:
                        pm = QPixmap()

                payload["Image_Id"] = int(image_id)
                payload["IconPixmap"] = pm if isinstance(pm, QPixmap) else QPixmap()
                out.append(payload)

        if out:
            return out

        w = getattr(self, "_buff_debuff_menu_window", None)
        if not isinstance(w, BuffDebuffMenuWindow):
            return []

        try:
            w.set_class_id(_safe_int(self._current_class_id(), 0))
        except Exception:
            pass

        try:
            w.set_level(_safe_int(self.level_spin.value(), 0))
        except Exception:
            pass

        try:
            fn = getattr(w, "get_active_preview_items", None)
            items = list(fn(str(mode or "")) or []) if callable(fn) else []
        except Exception:
            items = []

        for payload in items:
            if not isinstance(payload, dict):
                continue

            bonus_text = str(payload.get("BonusText") or "").strip()
            if not bonus_text or bonus_text.casefold() == "нет":
                continue

            image_id = _safe_int(payload.get("Image_Id"), 0)
            pm = payload.get("IconPixmap")

            if not isinstance(pm, QPixmap) or pm.isNull():
                try:
                    pm = self._get_image_pm(int(image_id)) if image_id > 0 else QPixmap()
                except Exception:
                    pm = QPixmap()

            payload = dict(payload)
            payload["IconPixmap"] = pm if isinstance(pm, QPixmap) else QPixmap()
            out.append(payload)

        return out

    def _toggle_active_buff_preview(self, key: str) -> None:
        key = str(key or "").strip()

        try:
            spec = self._active_buff_preview_spec(key)

            if not spec:
                self._close_active_buff_preview()
                QTimer.singleShot(0, lambda: self._set_active_buff_preview_button_state(""))
                return

            panel = getattr(self, "_active_buff_preview_panel", None)

            same_open = (
                    isinstance(panel, _ActiveBuffPreviewPanel)
                    and panel.isVisible()
                    and str(getattr(self, "_active_buff_preview_open_key", "") or "") == key
            )

            if same_open:
                self._close_active_buff_preview()
                QTimer.singleShot(0, lambda: self._set_active_buff_preview_button_state(""))
                return

            self._set_active_buff_preview_button_state("")

            mode = str(spec.get("mode") or "")
            items = self._active_buff_preview_items_for_mode(mode)

            if not items:
                self._close_active_buff_preview()
                QTimer.singleShot(0, lambda: self._set_active_buff_preview_button_state(""))
                QTimer.singleShot(30, lambda: self._set_active_buff_preview_button_state(""))
                return

            if not isinstance(panel, _ActiveBuffPreviewPanel):
                panel = _ActiveBuffPreviewPanel(self)
                panel.set_owner(self)
                self._active_buff_preview_panel = panel

            try:
                if panel.parentWidget() is not self:
                    panel.setParent(self)
            except Exception:
                pass

            max_w = self._active_buff_preview_max_panel_width(key)

            panel.set_owner(self)
            panel.set_open_key(key)
            panel.set_items(
                items,
                empty_text=str(spec.get("empty") or "Нет активных эффектов"),
                max_width=max_w,
            )

            self._active_buff_preview_open_key = key
            self._set_active_buff_preview_button_state(key)

            panel.show()
            self._position_active_buff_preview_panel()
            panel.raise_()

            for child in panel.findChildren(QWidget):
                try:
                    child.show()
                    child.raise_()
                except Exception:
                    pass

            for nm in ("hover_name_label", "menu_glow", "hover_glow"):
                try:
                    ww = getattr(self, nm, None)
                    if ww is not None:
                        ww.hide()
                except Exception:
                    pass

            def _raise_again() -> None:
                try:
                    if panel.isVisible():
                        self._position_active_buff_preview_panel()
                        panel.raise_()

                        for child in panel.findChildren(QWidget):
                            try:
                                child.show()
                                child.raise_()
                            except Exception:
                                pass
                except Exception:
                    pass

            QTimer.singleShot(0, _raise_again)
            QTimer.singleShot(30, _raise_again)

        except Exception:
            self._close_active_buff_preview()
            QTimer.singleShot(0, lambda: self._set_active_buff_preview_button_state(""))
            QTimer.singleShot(30, lambda: self._set_active_buff_preview_button_state(""))

    def _active_buff_preview_max_panel_width(self, key: str) -> int:
        btn = (getattr(self, "_active_buff_preview_btns", {}) or {}).get(str(key or ""))
        if btn is None:
            return 180

        try:
            ir = self._img_rect()
            left_limit = ir.left() + 4
            available = max(80, int(btn.x() - left_limit - 4))
            return min(260, available)
        except Exception:
            return 180

    def _position_active_buff_preview_panel(self) -> None:
        panel = getattr(self, "_active_buff_preview_panel", None)
        if not isinstance(panel, _ActiveBuffPreviewPanel):
            return

        key = str(getattr(self, "_active_buff_preview_open_key", "") or "")
        btn = (getattr(self, "_active_buff_preview_btns", {}) or {}).get(key)

        if btn is None:
            panel.hide()
            return

        try:
            ir = self._img_rect()
        except Exception:
            ir = self.rect()

        gap = max(1, int(1 * self._scale()))

        # Ряд должен выходить влево от кнопки.
        x = int(btn.x() - panel.width() - gap)
        y = int(btn.y())

        try:
            x = max(int(ir.left() + 4), x)
            y = max(int(ir.top() + 4), min(y, int(ir.bottom() - panel.height() - 4)))
        except Exception:
            pass

        panel.move(int(x), int(y))
        panel.raise_()

    def _close_active_buff_preview(self) -> None:
        self._active_buff_preview_open_key = ""

        try:
            panel = getattr(self, "_active_buff_preview_panel", None)
            if isinstance(panel, _ActiveBuffPreviewPanel):
                panel.hide()
        except Exception:
            pass

        self._set_active_buff_preview_button_state("")

    def _layout_reset_button(self) -> None:
        btn = getattr(self, "btn_reset_params", None)
        sp = getattr(self, "stats_panel", None)
        if btn is None or sp is None:
            return

        # показываем только на вкладке "main"
        visible = (getattr(sp, "_current_group", "main") == "main")
        btn.setVisible(visible)
        if not visible:
            return

        # якорь как раньше
        src = getattr(sp, "_rows_frame", sp)

        # позиция внутри src (как у тебя было)
        local_x = 194
        local_y = 40

        # размер из макета картинки 66x20 с учётом scale
        sx = self._scale()
        w = max(1, int(66 * sx))
        h = max(1, int(20 * sx))

        p = src.mapTo(self, QPoint(local_x, local_y))
        btn.setGeometry(p.x(), p.y(), w, h)
        btn.setIconSize(QSize(w, h))
        btn.raise_()

    def _on_unspent_changed(self, v: int) -> None:
        try:
            self.unspent_points_widget.set_points(v)
        except Exception:
            return

        # после show/raise внутри set_points() фиксируем слои
        def _fix():
            sp = getattr(self, "stats_panel", None)
            if sp and self.unspent_points_widget:
                # держим плашку НИЖЕ панели, чтобы не перекрывала её кнопки
                self.unspent_points_widget.stackUnder(sp)

        QTimer.singleShot(0, _fix)

    # ---------- щит на время окна рефоржа ----------
    def _ensure_main_modal_input_blocker(self) -> None:
        """
        Устанавливает глобальный фильтр, который не даёт событиям проваливаться
        в MainWindow под прозрачными/frameless/top-level меню.
        """
        app = QApplication.instance()
        if app is None:
            return

        blocker = getattr(self, "_main_modal_input_blocker", None)

        if isinstance(blocker, _MainModalInputBlocker):
            return

        blocker = _MainModalInputBlocker(self)
        self._main_modal_input_blocker = blocker

        try:
            app.installEventFilter(blocker)
        except Exception:
            pass

    def _set_widget_tree_mouse_transparent_for_shield(
            self,
            root: Optional[QWidget],
            shield: Optional[QWidget],
            cache_attr: str,
    ) -> None:
        """
        Делает дочерние интерактивные виджеты root прозрачными для мыши,
        чтобы события гарантированно попадали в shield.

        Это та же идея, из-за которой сейчас нормально работает reforge:
        даже если какой-то QLabel/QToolButton лежит выше щита по стеку,
        он перестаёт принимать мышь и событие уходит в shield.
        """
        if root is None or shield is None:
            return

        if not isinstance(root, QWidget) or not isinstance(shield, QWidget):
            return

        prev = getattr(self, cache_attr, None)
        if not isinstance(prev, dict):
            prev = {}

        widgets: list[QWidget] = []

        try:
            for w in root.findChildren(QWidget):
                if w is None:
                    continue

                if w is shield:
                    continue

                try:
                    if shield.isAncestorOf(w):
                        continue
                except Exception:
                    pass

                # Если root = MainWindow, не трогаем отдельные top-level окна:
                # StampWindow/CardsWindow/UpgradeWindow должны остаться кликабельными.
                if root is self:
                    try:
                        if w.window() is not self:
                            continue
                    except Exception:
                        pass

                # Не трогаем отдельные окна-попапы.
                try:
                    if w.isWindow() and w is not root:
                        continue
                except Exception:
                    pass

                widgets.append(w)
        except Exception:
            widgets = []

        seen: set[int] = set()

        for w in widgets:
            oid = id(w)
            if oid in seen:
                continue

            seen.add(oid)

            try:
                if w not in prev:
                    prev[w] = bool(w.testAttribute(Qt.WA_TransparentForMouseEvents))

                w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            except Exception:
                pass

        setattr(self, cache_attr, prev)

    def _restore_widget_tree_mouse_transparency_for_shield(self, cache_attr: str) -> None:
        """
        Возвращает виджетам прежнее состояние Qt.WA_TransparentForMouseEvents.
        """
        prev = getattr(self, cache_attr, None)

        if isinstance(prev, dict):
            for w, old_value in list(prev.items()):
                try:
                    if isinstance(w, QWidget):
                        w.setAttribute(Qt.WA_TransparentForMouseEvents, bool(old_value))
                        w.update()
                except Exception:
                    pass

        try:
            setattr(self, cache_attr, {})
        except Exception:
            pass

    def _raise_shield_again(self, shield_attr: str, root: Optional[QWidget] = None) -> None:
        """
        Повторно поднимает shield после открытия top-level окна/перелэйаута.
        """
        try:
            shield = getattr(self, shield_attr, None)
        except Exception:
            shield = None

        if not isinstance(shield, QWidget):
            return

        try:
            if root is None:
                root = shield.parentWidget()
        except Exception:
            root = None

        try:
            if root is not None:
                shield.setGeometry(root.rect())
        except Exception:
            pass

        try:
            if shield.isVisible():
                shield.show()
                shield.raise_()
        except Exception:
            pass

    def _ensure_reforge_shield(self) -> None:
        try:
            self._ensure_input_shield_global_blocker()
        except Exception:
            pass

        uw = getattr(self, "upgrade_win", None)

        # 0) на всякий: если уже тянули окно — сбросить
        try:
            self._drag_pos = None
        except Exception:
            pass

        # 1) принудительно убрать модальность у окна улучшения (иначе Windows может пищать)
        if uw is not None:
            try:
                uw.setWindowModality(Qt.NonModal)
            except Exception:
                pass

        if hasattr(uw, "setModal"):
            try:
                uw.setModal(False)
            except Exception:
                pass
            try:
                uw.setEnabled(True)
            except Exception:
                pass

        # 2) гарантируем, что остальные окна приложения не disabled (иначе beep всё равно будет)
        for w in (
                self,
                getattr(self, "inventory_window", None),
                getattr(self, "cards_window", None),
                getattr(self, "stamp_window", None),
        ):
            if w is None:
                continue
            try:
                w.setEnabled(True)
            except Exception:
                pass

        # 3) включаем "жёсткую" блокировку мейна на время рефорджа
        try:
            self._block_main_input = True
        except Exception:
            pass
        try:
            self._block_allow_root = uw if uw is not None else None
        except Exception:
            pass

        # 4) создаём/обновляем щит поверх main window
        shield = getattr(self, "_reforge_shield", None)
        if shield is None:
            self._reforge_shield = _InputShield(self)
            shield = self._reforge_shield
        else:
            try:
                shield.sync_geometry()
            except Exception:
                try:
                    shield.setGeometry(self.rect())
                except Exception:
                    pass
            try:
                shield.show()
            except Exception:
                pass

        # Щит должен быть выше всего в main (чтобы ловить мышь),
        # но если reforge-окно видимо — кладём щит под него (если это работает в твоей иерархии).
        try:
            shield.raise_()
        except Exception:
            pass

        # 5) чтобы не всплывали глоу/анкеты "сквозь" модалку
        try:
            if hasattr(self, "_hover_timer") and self._hover_timer.isActive():
                self._hover_timer.stop()
        except Exception:
            pass

        for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
            try:
                w = getattr(self, nm, None)
                if w is not None:
                    w.hide()
            except Exception:
                pass

        try:
            if hasattr(self, "equip_info") and self.equip_info is not None:
                self.equip_info.hide()
        except Exception:
            pass

        # 6) отдельно блокируем инвентарь (если открыт) — без disabled, только щитом
        try:
            self._ensure_inventory_shield()
        except Exception:
            pass

        # 7) ВАЖНО: на время рефорджа делаем интерактивные виджеты main "прозрачными" для мыши,
        # чтобы даже если они окажутся выше щита по стеку — события всё равно улетали в щит.
        prev = getattr(self, "_reforge_prev_mouse_transparency", None)
        if not isinstance(prev, dict):
            prev = {}

        widgets: list[QWidget] = []

        # базовые интерактивные зоны/контролы
        for w in (
                getattr(self, "board_label", None),
                getattr(self, "class_btn", None),
                getattr(self, "close_btn", None),
                getattr(self, "minimize_btn", None),
                getattr(self, "gender_m_btn", None),
                getattr(self, "gender_f_btn", None),
                getattr(self, "level_wheel", None),
                getattr(self, "level_spin", None),
        ):
            if w is not None:
                widgets.append(w)

        # кнопки нижнего меню
        try:
            widgets.extend(list((getattr(self, "menu_btns", {}) or {}).values()))
        except Exception:
            pass

        # маленькие кнопки (state/event)
        try:
            widgets.extend(list((getattr(self, "small_menu_btns", {}) or {}).values()))
        except Exception:
            pass

        # иконки слотов
        try:
            widgets.extend(list((getattr(self, "_slot_icons", {}) or {}).values()))
        except Exception:
            pass

        # уникализация + исключаем upgrade_win и его детей
        uniq: list[QWidget] = []
        seen: set[int] = set()
        for w in widgets:
            if w is None:
                continue
            if uw is not None:
                try:
                    if w is uw or uw.isAncestorOf(w):
                        continue
                except Exception:
                    pass
            oid = id(w)
            if oid in seen:
                continue
            seen.add(oid)
            uniq.append(w)

        for w in uniq:
            try:
                if w not in prev:
                    prev[w] = bool(w.testAttribute(Qt.WA_TransparentForMouseEvents))
                w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            except Exception:
                pass

        self._reforge_prev_mouse_transparency = prev

        # 8) щит должен быть ПОД окном рефоржа (если это реально sibling в твоём UI)
        if uw is not None and uw.isVisible():
            try:
                shield.stackUnder(uw)
            except Exception:
                pass
            try:
                uw.activateWindow()
            except Exception:
                pass

    def _remove_reforge_shield(self) -> None:
        # 1) восстановить mouse-transparency для виджетов мейна
        prev = getattr(self, "_reforge_prev_mouse_transparency", None)
        if isinstance(prev, dict):
            for w, old in list(prev.items()):
                try:
                    if w is None:
                        continue
                    w.setAttribute(Qt.WA_TransparentForMouseEvents, bool(old))
                except Exception:
                    pass
        try:
            self._reforge_prev_mouse_transparency = {}
        except Exception:
            pass

        # 2) убрать щит
        shield = getattr(self, "_reforge_shield", None)
        if shield is not None:
            try:
                shield.hide()
            except Exception:
                pass
            try:
                shield.deleteLater()
            except Exception:
                pass
            self._reforge_shield = None

        # 3) снять жёсткую блокировку
        try:
            self._block_main_input = False
        except Exception:
            pass
        try:
            self._block_allow_root = None
        except Exception:
            pass

        # 4) включаем hover обратно только если ничего "модального" не висит
        uw = getattr(self, "upgrade_win", None)
        sw = getattr(self, "stamp_window", None)
        cw = getattr(self, "cards_window", None)

        any_modal = (
                (uw is not None and uw.isVisible()) or
                (sw is not None and sw.isVisible()) or
                (cw is not None and cw.isVisible()) or
                self._stamp_shield_active()
        )

        try:
            if not any_modal and hasattr(self, "_hover_timer") and not self._hover_timer.isActive():
                self._hover_timer.start()
        except Exception:
            pass

    def _reforge_shield_active(self) -> bool:
        return bool(getattr(self, "_reforge_shield", None) and self._reforge_shield.isVisible())

    def _inventory_shield_active(self) -> bool:
        sh = getattr(self, "_inv_shield", None)
        try:
            return bool(sh is not None and sh.isVisible())
        except Exception:
            return False

    def _any_input_shield_active(self) -> bool:
        """
        Общая проверка активных щитов MainWindow/Inventory/Reforge.

        Нужна в том числе для Wheel, потому что колесо мыши может прилететь
        не в сам _InputShield, а в LevelWheel/другой виджет под курсором.
        """
        try:
            if bool(getattr(self, "_block_main_input", False)):
                return True
        except Exception:
            pass

        try:
            if self._stamp_shield_active():
                return True
        except Exception:
            pass

        try:
            if self._reforge_shield_active():
                return True
        except Exception:
            pass

        try:
            if self._inventory_shield_active():
                return True
        except Exception:
            pass

        return False

    def _ensure_inventory_shield(self) -> None:
        inv = getattr(self, "inventory_window", None)

        if inv is None or not inv.isVisible():
            return

        if self._inv_shield is None or self._inv_shield.parentWidget() is not inv:
            if self._inv_shield is not None:
                try:
                    self._inv_shield.hide()
                    self._inv_shield.deleteLater()
                except Exception:
                    pass
            self._inv_shield = _InputShield(inv)

        self._inv_shield.setGeometry(inv.rect())
        self._inv_shield.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._inv_shield.show()
        self._inv_shield.raise_()

        try:
            QTimer.singleShot(0, self._inv_shield.raise_)
            QTimer.singleShot(30, self._inv_shield.raise_)
        except Exception:
            pass

    def _remove_inventory_shield(self) -> None:
        sh = getattr(self, "_inv_shield", None)

        if sh is not None:
            try:
                sh.hide()
            except Exception:
                pass

            try:
                sh.deleteLater()
            except Exception:
                pass

            self._inv_shield = None

    # замените существующую версию
    def _open_cards_menu(
            self,
            kind: str,
            *,
            item: Optional[dict] = None,
            slot_key: Optional[str] = None,
    ) -> None:
        """
        Открывает окно карт по Shift+ПКМ.

        ВАЖНО:
        раньше щит ставился до открытия CardsWindow. Если внутри открытия происходило
        исключение, щит оставался поверх MainWindow, и программа выглядела зависшей.
        Теперь при любой ошибке щиты гарантированно снимаются.
        """
        kind = "weapon" if str(kind or "").strip().lower() == "weapon" else "equipment"

        cw = getattr(self, "cards_window", None)
        if cw is None:
            print("[CARDS_OPEN][SKIP] cards_window is None", flush=True)
            return

        # 0) Сначала делаем тяжёлые/потенциально опасные операции БЕЗ щитов.
        # Если тут что-то упадёт, главное окно не будет перекрыто прозрачным shield.
        try:
            self.refresh_stats_panel()
        except Exception:
            import traceback
            print("[CARDS_OPEN][STATS_ERROR] Ошибка refresh_stats_panel перед открытием карт", flush=True)
            traceback.print_exc()

        try:
            stats_dict = dict(getattr(self, "character_stats", {}) or {})

            if hasattr(cw, "set_character_stats"):
                try:
                    cw.set_character_stats(stats_dict)
                except Exception:
                    import traceback
                    print("[CARDS_OPEN][SET_STATS_ERROR] Ошибка cw.set_character_stats", flush=True)
                    traceback.print_exc()

            try:
                cw._current_stats_dict = dict(stats_dict)
            except Exception:
                pass

            if hasattr(cw, "on_current_stats_changed"):
                try:
                    cw.on_current_stats_changed(dict(stats_dict))
                except Exception:
                    import traceback
                    print("[CARDS_OPEN][STATS_CHANGED_ERROR] Ошибка cw.on_current_stats_changed", flush=True)
                    traceback.print_exc()
        except Exception:
            import traceback
            print("[CARDS_OPEN][PREP_ERROR] Ошибка подготовки CardsWindow", flush=True)
            traceback.print_exc()

        shields_created = False

        try:
            # 1) Щиты ставим только непосредственно перед открытием.
            self._ensure_stamp_shield()
            self._ensure_inventory_shield()
            shields_created = True

            try:
                self.menu_glow.hide()
                self.hover_glow.hide()
                self.winbtn_hover.hide()
            except Exception:
                pass

            try:
                if hasattr(self, "equip_info") and self.equip_info is not None:
                    self.equip_info.hide()
            except Exception:
                pass

            # 2) Открываем окно карт.
            cw.open_centered(
                self,
                kind=kind,
                item=item,
                slot_key=slot_key,
            )

            # 3) Контрольный raise через event loop.
            # На некоторых системах Qt окно может показать не сразу.
            try:
                QTimer.singleShot(0, cw.raise_)
                QTimer.singleShot(0, cw.activateWindow)
            except Exception:
                pass

            # Если окно по какой-то причине не стало видимым — снимаем щиты.
            try:
                if not cw.isVisible():
                    raise RuntimeError("CardsWindow.open_centered() finished, but window is not visible")
            except RuntimeError:
                raise
            except Exception:
                pass

        except Exception:
            import traceback
            print(
                "[CARDS_OPEN][ERROR] Не удалось открыть окно карт "
                f"kind={kind!r}, slot_key={slot_key!r}, item_id={(item or {}).get('Id') if isinstance(item, dict) else None}",
                flush=True,
            )
            traceback.print_exc()

            if shields_created:
                try:
                    self._remove_stamp_shield()
                except Exception:
                    pass

                try:
                    self._remove_inventory_shield()
                except Exception:
                    pass

            try:
                if hasattr(self, "_hover_timer") and not self._hover_timer.isActive():
                    self._hover_timer.start()
            except Exception:
                pass

    def _on_cards_closed(self) -> None:
        """
        Закрытие окна карт: снимаем все щиты и возвращаем hover.
        """
        try:
            self._remove_stamp_shield()
        except Exception:
            pass

        try:
            self._remove_inventory_shield()
        except Exception:
            pass

        try:
            if hasattr(self, "_hover_timer") and not self._hover_timer.isActive():
                self._hover_timer.start()
        except Exception:
            pass

        try:
            self._update_glow_from_global()
        except Exception:
            pass

    def _etype_name_by_id(self, tid: int) -> str:
        """
        Возвращает Name из EquipmentType по Id с кешированием.
        """
        tid = _safe_int(tid, 0)
        if tid <= 0:
            return "—"

        cache = self._etype_name_cache
        if tid in cache:
            return cache[tid]

        try:
            row = self.data.conn.execute(
                "SELECT Name FROM EquipmentType WHERE Id=? LIMIT 1",
                (tid,),
            ).fetchone()
        except Exception:
            name = "—"
        else:
            if not row:
                name = "—"
            else:
                # row может быть Row или tuple
                name = row[0] if isinstance(row, (tuple, list)) else row["Name"]

        cache[tid] = name
        return name

    def _item_is_weapon(self, it: dict | None) -> bool:
        if not it:
            return False
        # явный флаг
        if _safe_int(it.get("IsWeapon"), 0) == 1:
            return True
        atk = _safe_int(it.get("Attack"), 0)
        # «offhand/щит» в имени типа — считаем НЕ оружием
        tname = self._etype_name_by_id(_safe_int(it.get("Type_Id") or it.get("TypeId"), 0)).lower()
        looks_shield = ("offhand" in tname)
        return (atk > 0) and (not looks_shield)

    # --- Геттеры пола для инвентаря/контроллеров ---
    def current_gender_id(self) -> int:
        """1 = муж, 2 = жен."""
        return 1 if self._gender == 1 else 2

    def get_current_gender_id(self) -> int:
        return self.current_gender_id()

    def selected_gender_id(self) -> int:
        return self.current_gender_id()

    def _call_many(self, names: Iterable[str], arg: Optional[str] = None) -> None:
        """Безопасно вызвать набор методов-«хуков». Если метод принимает аргумент — передаём, иначе вызываем без."""
        for name in names:
            fn = getattr(self, name, None)
            if not callable(fn):
                continue
            try:
                if arg is not None:
                    try:
                        fn(arg)
                    except TypeError:
                        fn()
                else:
                    fn()
            except Exception:
                # глотаем — эти хуки не должны ломать основной поток
                pass

    # ---------- хелперы штампов ----------
    def _equipment_allowed_for_class(self, equip_id: int, class_ids: list[int]) -> bool:
        """
        True если:
          - для equip_id нет строк в EquipmentCondition (значит подходит всем),
          ИЛИ
          - есть хотя бы одна строка EquipmentCondition(Equipment_Id=equip_id, Class_Id IN class_ids)
        """
        eid = _safe_int(equip_id, 0)
        if eid <= 0:
            return True

        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None:
            return True  # если БД недоступна — лучше не дропать

        cls = [int(_safe_int(x, 0)) for x in (class_ids or []) if _safe_int(x, 0) > 0]
        ph = ",".join(["?"] * len(cls)) if cls else "NULL"

        sql = f"""
        SELECT 1
        WHERE
          NOT EXISTS (SELECT 1 FROM EquipmentCondition c WHERE c.Equipment_Id = ?)
          OR EXISTS (
              SELECT 1
              FROM EquipmentCondition c
              WHERE c.Equipment_Id = ?
                AND c.Class_Id IN ({ph})
          )
        LIMIT 1
        """
        args = [eid, eid] + cls
        try:
            return bool(conn.execute(sql, args).fetchone())
        except Exception:
            return True

    def _poke_hover_synthetic(self) -> None:
        """Послать искусственный MouseMove в board_label, чтобы сразу отрисовать ховер/тултип."""
        if not hasattr(self, "board_label") or not self.board_label:
            return
        gp = QCursor.pos()
        lp = self.board_label.mapFromGlobal(gp)
        ev = QMouseEvent(QEvent.MouseMove, lp, gp, Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        QApplication.postEvent(self.board_label, ev)

    def _normalize_stamp_record(self, rec: Optional[dict]) -> dict:
        """Приводит запись печати к единому виду (всегда возвращает валидный dict)."""
        if not rec:
            return {"Id": 0, "ColorId": 0, "Name": "", "Bonuses": []}

        sid = _safe_int(rec.get("Id") or rec.get("id"), 0)
        col = _safe_int(rec.get("ColorId") or rec.get("color_id"), 0)
        name = (rec.get("Name") or rec.get("name") or "").strip()
        bonuses = list(rec.get("Bonuses") or rec.get("BonusLines") or rec.get("Effects") or rec.get("bonuses") or [])

        meta = self._stamp_color_meta(col) or {}
        out = {"Id": sid, "ColorId": col, "Name": name, "Bonuses": bonuses, "HeaderColorHex": meta.get("hex"),
               "HeaderIconImageId": meta.get("icon_img_id"), "icon_id": meta.get("icon_img_id"),
               "BonusLines": list(bonuses), "Effects": list(bonuses), "name": name}
        # алиасы для совместимости
        return out

    def _embed_stamp_into_item(self, item: Optional[dict], stamp_norm: Optional[dict]) -> None:
        """
        Жёстко вшивает печать во все распространённые поля предмета,
        чтобы любой тултип смог её прочитать.
        """
        if not item:
            return
        st = stamp_norm or {"Id": 0, "ColorId": 0, "Name": "", "Bonuses": []}

        # Каноника
        item["Stamp"] = dict(st)
        item["stamp"] = dict(st)

        # Денорм-поля (верхнего уровня)
        item["StampId"] = _safe_int(st.get("Id"), 0)
        item["StampColorId"] = _safe_int(st.get("ColorId"), 0)
        item["StampName"] = st.get("Name") or ""
        item["StampBonuses"] = list(st.get("Bonuses") or [])

        # Полезные «верхние» меты для заголовков
        if st.get("HeaderColorHex") is not None:
            item["StampHeaderColorHex"] = st["HeaderColorHex"]
        if st.get("HeaderIconImageId") is not None:
            item["StampHeaderIconImageId"] = st["HeaderIconImageId"]
        if st.get("icon_id") is not None:
            item["StampHeaderIconId"] = st["icon_id"]

    def _mask_stamp_for_slot(self, slot_key: str, ttl_ms: int = 800) -> None:
        """Коротко скрыть печать в тултипе для слота (чтобы не мигала старая после выбора)."""
        if not slot_key:
            return
        if not hasattr(self, "_mask_stamp_slots") or not isinstance(self._mask_stamp_slots, set):
            self._mask_stamp_slots = set()
        self._mask_stamp_slots.add(slot_key)
        QTimer.singleShot(ttl_ms, lambda _k=slot_key: self._mask_stamp_slots.discard(_k))

    def _slot_key_of_item_id(self, item_id: int) -> Optional[str]:
        """Найти, в каком слоте сейчас надет предмет с данным item_id."""
        iid = _safe_int(item_id, 0)
        if not iid:
            return None
        for k, it in (self._selected_items or {}).items():
            try:
                if _safe_int(it.get("Id"), 0) == iid:
                    return k
            except Exception:
                continue
        return None

    def _slot_has_item(self, slot_key: str) -> bool:
        """Есть ли предмет в указанном слоте."""
        try:
            return bool((self._selected_items or {}).get(str(slot_key)))
        except Exception:
            return False

    def _suppress_stamp_for(self, item_id: int, ttl_ms: int = 1200) -> None:
        """Временно подавить показ печати для item_id."""
        cur = getattr(self, "_suppress_stamp_equipped", None)
        if not isinstance(cur, set):
            try:
                self._suppress_stamp_equipped = set(cur.keys()) if isinstance(cur, dict) else set(cur or [])
            except Exception:
                self._suppress_stamp_equipped = set()

        iid = _safe_int(item_id, 0)
        if not iid:
            return
        self._suppress_stamp_equipped.add(iid)
        QTimer.singleShot(ttl_ms, lambda _iid=iid: self._suppress_stamp_equipped.discard(_iid))

    # ---------- иконки слотов ----------
    def _ensure_equip_buttons_map(self) -> None:
        """
        Лениво собираем маппинг slot_key -> виджет (QToolButton/QLabel),
        чтобы можно было выставлять иконки.
        Ищем по именам атрибутов вида btn_<slot_key> или <slot_key>_btn.
        """
        if hasattr(self, "_equip_buttons") and isinstance(self._equip_buttons, dict) and self._equip_buttons:
            return

        keys_guess = [
            "weapon",
            "chest",
            "gloves",
            "boots",
            "pants",
            "helmet",
            "shoulders",
            "belt",
            "neck",
            "ring1",
            "ring2",
            "bracelet",
            "earring1",
            "earring2",
            "cloak",
            "offhand",
            "amulet",
        ]
        mapping = {}
        for k in keys_guess:
            for name in (f"btn_{k}", f"{k}_btn", k):
                w = getattr(self, name, None)
                if w is not None:
                    mapping[k] = w
                    break

        if not getattr(self, "_equip_buttons", None):
            self._equip_buttons = mapping
        else:
            self._equip_buttons.update({k: v for k, v in mapping.items() if k not in self._equip_buttons})

    # ---------- кеш картинок из БД ----------
    def _disabled_pixmap(self, pm: QPixmap, *, overlay_alpha: int = 110, desaturate: bool = True) -> QPixmap:
        """
        Делает иконку "задизейбленной":
          - desaturate=True  -> переводит в grayscale
          - overlay_alpha    -> затемняющий серый оверлей сверху
        """
        if pm is None or pm.isNull():
            return QPixmap()

        img = pm.toImage().convertToFormat(QImage.Format_ARGB32)

        if desaturate:
            w, h = img.width(), img.height()
            for y in range(h):
                for x in range(w):
                    c = img.pixelColor(x, y)
                    if c.alpha() == 0:
                        continue
                    g = int(0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue())
                    c.setRed(g);
                    c.setGreen(g);
                    c.setBlue(g)
                    img.setPixelColor(x, y, c)

        out = QPixmap.fromImage(img)

        if overlay_alpha > 0:
            canvas = QPixmap(out.size())
            canvas.fill(Qt.transparent)
            p = QPainter(canvas)
            try:
                p.setRenderHint(QPainter.Antialiasing, True)
                p.drawPixmap(0, 0, out)
                # серый фильтр сверху (подкрути альфу под вкус)
                p.fillRect(canvas.rect(), QColor(60, 60, 60, int(overlay_alpha)))
            finally:
                p.end()
            out = canvas

        return out

    def _get_image_pm(self, image_id: int | None) -> Optional[QPixmap]:
        """
        Возвращает QPixmap по Image_Id с кешированием.
        """
        iid = _safe_int(image_id, 0)
        if iid <= 0:
            return None

        pm = self._image_cache.get(iid)
        if pm is not None:
            return pm

        raw = None
        try:
            raw = self.data.get_image_bytes(iid)
        except Exception:
            return None

        pm = _pm_from_bytes(raw)
        if pm:
            self._image_cache[iid] = pm
        return pm

    def _image_pm_for_item(self, item: dict | None) -> Optional[QPixmap]:
        """Достаёт QPixmap иконки предмета через кеширующий _get_image_pm."""
        if not item:
            return None
        img_id = (
                item.get("Icon_Image_Id")
                or item.get("Image_Id")
                or item.get("CostumeImage_Id")
        )
        return self._get_image_pm(img_id)

    def _set_slot_pixmap(self, slot_key: str, pm: Optional[QPixmap]) -> None:
        """
        Ставит иконку в соответствующий виджет слота.
        Поддерживает QToolButton (setIcon) и QLabel (setPixmap).
        """
        self._ensure_equip_buttons_map()
        w = (self._equip_buttons or {}).get(str(slot_key))
        if w is None:
            return

        try:
            size = w.iconSize() if hasattr(w, "iconSize") else w.size()
        except Exception:
            size = None

        if pm is None:
            try:
                if hasattr(w, "setIcon"):
                    w.setIcon(QIcon())
                if hasattr(w, "setPixmap"):
                    w.setPixmap(QPixmap())
            except Exception:
                pass
            return

        if hasattr(w, "setIcon"):
            ic = QIcon(pm if size is None else pm.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            w.setIcon(ic)
            try:
                if size is None:
                    w.setIconSize(pm.size())
            except Exception:
                pass
        elif hasattr(w, "setPixmap"):
            if size is None:
                w.setPixmap(pm)
            else:
                w.setPixmap(pm.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def refresh_equipment_slot(self, slot_key: str) -> None:
        """Обновляет картинку слота по self._selected_items[slot_key]."""
        try:
            item = (self._selected_items or {}).get(str(slot_key))
            pm = self._image_pm_for_item(item) if item else None
            self._set_slot_pixmap(str(slot_key), pm)
        except Exception:
            pass

    # ---------- штампы/инстансы ----------
    def get_stamp_for_instance(self, inst: str) -> Optional[dict]:
        if not inst:
            return None
        rec = (self._applied_stamps or {}).get(inst)
        if rec:
            return rec
        try:
            if hasattr(self.data, "get_item_stamp_by_instance"):
                return self.data.get_item_stamp_by_instance(inst)
        except Exception:
            pass
        return None

    # ---------- экипировка ----------
    def equip_item_in_slot(self, slot_key: str, item: dict, prev_item: Optional[dict] = None) -> bool:
        """
        Универсальная точка экипировки:
        - НЕ чистим печати (чистка — только в on_inventory_swap_request и там, где это явно нужно);
        - сохраняем предмет;
        - обновляем картинку слота;
        - вызываем пересчёты/обновления UI.
        """
        try:
            if not hasattr(self, "_selected_items") or not isinstance(self._selected_items, dict):
                self._selected_items = {}
            self._selected_items[str(slot_key)] = dict(item) if item else None

            self._update_slot_icon(str(slot_key))

            self._call_many(
                (
                    "recalc_stats",
                    "recalc_all",
                    "update_stats",
                    "refresh_stats_panel",
                    "refresh_equipment",
                    "_refresh_equipment_ui",
                    "repaint_equipment",
                    "rebuild_equipment",
                    "update_equipment_ui",
                    "update_equipment_panel",
                    "on_equipment_changed",
                ),
                arg=str(slot_key),
            )
            return True
        except Exception:
            return False

    # MainWindow
    def _sync_inventory_context(self) -> None:
        inv = getattr(self, "inventory_window", None)
        if not inv:
            return

        gender_id = self.get_current_gender_id()

        cls_ctx = None
        try:
            cls_ctx = self._current_class_id()
        except Exception:
            cls_ctx = None

        if cls_ctx is None:
            try:
                cls_ctx = self.class_combo.currentText()
            except Exception:
                cls_ctx = None

        # ВАЖНО:
        # сначала обновляем пол, потом класс.
        # Иначе при смене пола инвентарь может чиститься по старому gender_id.
        try:
            fn = getattr(inv, "on_player_gender_changed", None)
            if callable(fn):
                fn(gender_id)
        except Exception:
            pass

        try:
            fn = getattr(inv, "on_player_class_changed", None)
            if callable(fn):
                fn(cls_ctx)
        except Exception:
            pass

    # === свап из инвентаря ===
    def _swap_twohanded_weapon_into_inventory_cell(self, dst_cell_ref: dict, inv=None) -> bool:
        """
        Если на персонаже двуручка и из инвентаря пытаются надеть предмет в offhand,
        делаем swap без требования свободной ячейки:

            weapon(двуручка) -> в ТУ ЖЕ ячейку инвентаря (откуда берём offhand)
            offhand-item     -> в offhand

        FIX (критичный):
          - НЕ снимаем weapon со слота, пока не убедились, что он реально записан в инвентарь
          - запись ячейки делаем через _assign_inventory_cell_payload(..., inv=inv), который
            пытается дернуть API InventoryWindow, если dict оказался копией
          - после callback инвентарь может "очистить" исходную ячейку — реассерт на следующем тике
        """
        if not isinstance(dst_cell_ref, dict):
            return False

        if inv is None:
            inv = getattr(self, "inventory_window", None)

        # резолвим реальную ячейку (если возможно)
        real_cell = dst_cell_ref
        try:
            if inv is not None:
                real_cell = self._resolve_inventory_cell_ref(dst_cell_ref, inv)
        except Exception:
            real_cell = dst_cell_ref

        weapon_it = (getattr(self, "_selected_items", None) or {}).get("weapon")
        if not (isinstance(weapon_it, dict) and weapon_it):
            return False

        # убеждаемся, что это двуручка
        try:
            if not bool(self._weapon_is_two_handed(weapon_it)):
                return False
        except Exception:
            return False

        # снап оружия (тот же InstanceGuid, new_instance=False)
        try:
            weapon_snap = self._make_inventory_snapshot(weapon_it, new_instance=False, slot_key="weapon")
        except Exception:
            return False

        # --- 1) пытаемся положить оружие в ячейку
        try:
            self._assign_inventory_cell_payload(real_cell, weapon_snap, inv=inv)
        except Exception:
            return False

        # --- 2) верификация: если это была копия — оружия в реальной ячейке нет => НЕ СНИМАЕМ weapon
        def _cell_has_weapon(cell: dict, snap: dict) -> bool:
            if not isinstance(cell, dict) or not isinstance(snap, dict):
                return False
            g = snap.get("InstanceGuid")
            if g and cell.get("InstanceGuid") == g:
                return True
            eid = _safe_int(snap.get("Id") or snap.get("Equip_Id"), 0)
            if eid and _safe_int(cell.get("Id") or cell.get("Equip_Id"), 0) == eid:
                return True
            return False

        ok_written = False
        try:
            ok_written = _cell_has_weapon(real_cell, weapon_snap)
        except Exception:
            ok_written = False

        # если не видно в этой ссылке — попробуем найти по инстансу через _resolve_inventory_cell_ref
        if not ok_written and inv is not None:
            try:
                probe = {"InstanceGuid": weapon_snap.get("InstanceGuid")}
                found = self._resolve_inventory_cell_ref(probe, inv)
                if isinstance(found, dict) and _cell_has_weapon(found, weapon_snap):
                    ok_written = True
                    real_cell = found
            except Exception:
                pass

        if not ok_written:
            # ❗️КЛЮЧ: не трогаем weapon слот — иначе “удаление”
            return False

        # --- 3) теперь можно безопасно снять оружие со слота
        try:
            (self._selected_items or {}).pop("weapon", None)
        except Exception:
            pass

        try:
            self._two_handed_equipped = False
        except Exception:
            pass

        try:
            (getattr(self, "_mask_stamp_slots", set()) or set()).discard("weapon")
        except Exception:
            pass

        # --- 4) обновим UI weapon/offhand
        try:
            self._update_slot_icon("weapon")
        except Exception:
            pass

        try:
            if hasattr(self, "_update_offhand_overlay"):
                self._update_offhand_overlay(refresh_icon=False)
        except Exception:
            pass

        # --- 5) реассерт: инвентарь может очистить исходную ячейку после callback
        try:
            if inv is not None:
                def _reassert(cell=real_cell, snap=dict(weapon_snap)):
                    try:
                        self._assign_inventory_cell_payload(cell, snap, inv=inv)
                    except Exception:
                        pass
                    for meth in ("refresh", "repaint", "update_grid", "refresh_grid", "update"):
                        fn = getattr(inv, meth, None)
                        if callable(fn):
                            try:
                                fn()
                            except Exception:
                                pass

                QTimer.singleShot(0, _reassert)
                QTimer.singleShot(30, _reassert)
        except Exception:
            pass

        # --- 6) обновим инвентарь сразу
        if inv is not None:
            for meth in ("refresh", "repaint", "update_grid", "refresh_grid", "update"):
                fn = getattr(inv, meth, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass

        return True

    def _resolve_inventory_cell_ref(self, cell_like: dict, inv) -> dict:
        """
        Пытается получить ССЫЛКУ на реальную dict-ячейку инвентаря.

        FIX:
          - не возвращаем первую попавшуюся "похожую" ячейку по слабой сигнатуре
          - учитываем карты / печать / эликсир / forge
          - для одинаковых предметов выбираем лучший матч, а не первый
        """
        if inv is None or not isinstance(cell_like, dict):
            return cell_like

        def _i(v):
            try:
                return int(v)
            except Exception:
                return None

        def _get_any(d: dict, keys: tuple[str, ...]):
            for k in keys:
                if k in d:
                    return d.get(k)
            lk = {str(k).casefold(): k for k in d.keys()}
            for k in keys:
                kk = lk.get(str(k).casefold())
                if kk is not None:
                    return d.get(kk)
            return None

        def _forge_level(d: dict) -> int:
            for k in ("__forge_level", "ForgeLevel", "UpgradeLevel", "Plus", "Refine", "EnhanceLevel"):
                try:
                    if k in d and d[k] not in (None, ""):
                        return int(d[k])
                except Exception:
                    pass
            return 0

        def _stamp_sig(d: dict) -> tuple:
            st = d.get("Stamp") or d.get("stamp")
            if isinstance(st, dict):
                return (
                    _safe_int(st.get("Id"), 0),
                    _safe_int(st.get("ColorId"), 0),
                    str(st.get("Name") or ""),
                    tuple(str(x) for x in (st.get("Bonuses") or [])),
                )
            return ()

        def _elixir_sig(d: dict) -> tuple:
            el = d.get("Elixir") or d.get("_elixir")
            if not isinstance(el, dict):
                return ()
            bons = []
            for b in (el.get("Bonuses") or []):
                if not isinstance(b, dict):
                    continue
                bons.append((
                    _safe_int(b.get("OrderIndex"), 0),
                    _safe_int(b.get("Type_Id") or b.get("TypeId"), 0),
                    float(b.get("Value") or 0.0),
                ))
            return (
                _safe_int(el.get("Id") or el.get("id"), 0),
                str(el.get("Name") or el.get("name") or ""),
                tuple(bons),
            )

        def _cards_sig(d: dict) -> tuple:
            def _norm_cards_map(raw) -> dict[int, dict]:
                out: dict[int, dict] = {}
                if isinstance(raw, dict):
                    items = list(raw.items())
                elif isinstance(raw, (list, tuple)):
                    items = [(i + 1, raw[i]) for i in range(len(raw))]
                else:
                    items = []

                for k, v in items:
                    try:
                        idx = int(k)
                    except Exception:
                        continue
                    if idx <= 0 or not isinstance(v, dict):
                        continue
                    out[int(idx)] = dict(v)
                return out

            cmap = {}
            for ck in ("_cards", "cards", "Cards"):
                cmap = _norm_cards_map(d.get(ck))
                if cmap:
                    break

            if not cmap:
                cw = getattr(self, "cards_window", None)
                if cw is not None and hasattr(cw, "get_cards_for_item"):
                    try:
                        sk = str(d.get("slot_key") or d.get("SlotKey") or "").strip()
                    except Exception:
                        sk = ""

                    try:
                        kind = "weapon" if (sk and self._slot_kind(sk) == "weapon") else "equipment"
                    except Exception:
                        kind = "weapon" if sk in {"weapon", "offhand", "spear"} else "equipment"

                    try:
                        got = cw.get_cards_for_item(d, kind=kind, slot_key=(sk or None))
                        cmap = _norm_cards_map(got)
                    except Exception:
                        cmap = {}

            sig = []
            for idx in sorted(cmap.keys()):
                c = cmap[idx] or {}
                sig.append((
                    int(idx),
                    _safe_int(c.get("Id") or c.get("Card_Id") or c.get("CardId"), 0),
                    _safe_int(c.get("Image_Id") or c.get("ImageId"), 0),
                    str(c.get("Name") or ""),
                ))
            return tuple(sig)

        def _item_sig(d: dict) -> tuple:
            return (
                _safe_int(_get_any(d, ("Id", "Equip_Id", "EquipId")), 0),
                _safe_int(_get_any(d, ("Type_Id", "TypeId")), 0),
                _safe_int(_get_any(d, ("Level", "level")), 0),
                _safe_int(_get_any(d, ("Image_Id", "Icon_Image_Id", "CostumeImage_Id")), 0),
                _forge_level(d),
                _stamp_sig(d),
                _cards_sig(d),
                _elixir_sig(d),
            )

        try:
            cells = list(self._iter_inventory_cells(inv))
        except Exception:
            cells = []

        if not cells:
            return cell_like

        # 0) identity
        try:
            for c in cells:
                if c is cell_like:
                    return c
        except Exception:
            pass

        # 1) row/col
        row = _i(_get_any(cell_like, ("row", "Row", "r")))
        col = _i(_get_any(cell_like, ("col", "Col", "c")))
        if row is not None and col is not None:
            for c in cells:
                if not isinstance(c, dict):
                    continue
                r2 = _i(_get_any(c, ("row", "Row", "r")))
                c2 = _i(_get_any(c, ("col", "Col", "c")))
                if r2 == row and c2 == col:
                    return c

        # 2) exact guid
        inst_like = _get_any(cell_like, ("InstanceGuid", "instance_guid", "instanceGuid"))
        if inst_like:
            for c in cells:
                if not isinstance(c, dict):
                    continue
                if c.get("_emptied") is True:
                    continue
                if _get_any(c, ("InstanceGuid", "instance_guid", "instanceGuid")) == inst_like:
                    return c

        sig_like = _item_sig(cell_like)

        idx_keys = ("idx", "index", "cell", "cell_id", "cell_index", "slot_index", "grid_index", "pos", "x", "y")
        idx_map_like = {}
        for k in idx_keys:
            iv = _i(_get_any(cell_like, (k,)))
            if iv is not None:
                idx_map_like[k] = iv

        best_cell = None
        best_score = -1

        for c in cells:
            if not isinstance(c, dict):
                continue
            if c.get("_emptied") is True:
                continue

            score = 0

            # индексные поля усиливают матч, но сами по себе уже не решают всё
            for k, iv in idx_map_like.items():
                iv2 = _i(_get_any(c, (k,)))
                if iv2 is not None and iv2 == iv:
                    score += 25

            sig_cur = _item_sig(c)

            # Id / Type / Level / Image / forge
            if sig_like[0] and sig_cur[0] and sig_like[0] == sig_cur[0]:
                score += 40
            if sig_like[1] and sig_cur[1] and sig_like[1] == sig_cur[1]:
                score += 20
            if sig_like[2] and sig_cur[2] and sig_like[2] == sig_cur[2]:
                score += 8
            if sig_like[3] and sig_cur[3] and sig_like[3] == sig_cur[3]:
                score += 8
            if sig_like[4] == sig_cur[4]:
                score += 10

            # stamp / cards / elixir — самые важные для одинаковых предметов
            if sig_like[5] and sig_cur[5] and sig_like[5] == sig_cur[5]:
                score += 35
            if sig_like[6] and sig_cur[6] and sig_like[6] == sig_cur[6]:
                score += 70
            if sig_like[7] and sig_cur[7] and sig_like[7] == sig_cur[7]:
                score += 25

            if score > best_score:
                best_score = score
                best_cell = c

        if isinstance(best_cell, dict) and best_score >= 40:
            return best_cell

        return cell_like

    def _assign_inventory_cell_payload(self, cell_ref: dict, payload: dict | None, *, inv=None) -> None:
        """
        Аккуратно переписать содержимое ячейки инвентаря.

        FIX:
          - если InventoryWindow имеет свой API для изменения ячейки — используем его
          - НЕ тащим временные _*-поля старого предмета в новый payload
          - оставляем только служебные координаты/индексы ячейки
          - снимаем частые флаги Empty/IsEmpty/etc
        """
        if inv is None:
            inv = getattr(self, "inventory_window", None)

        if not isinstance(cell_ref, dict):
            return

        def _i(v):
            try:
                return int(v)
            except Exception:
                return None

        def _get_any(d: dict, keys: tuple[str, ...]):
            for k in keys:
                if k in d:
                    return d.get(k)
            lk = {str(k).casefold(): k for k in d.keys()}
            for k in keys:
                kk = lk.get(str(k).casefold())
                if kk is not None:
                    return d.get(kk)
            return None

        def _cell_pos(d: dict):
            r = _i(_get_any(d, ("row", "Row", "rowIndex", "RowIndex", "r")))
            c = _i(_get_any(d, ("col", "Col", "colIndex", "ColIndex", "c")))
            idx = _i(_get_any(d, ("idx", "index", "cell", "cell_id", "cell_index", "slot_index", "grid_index", "pos")))
            return r, c, idx

        def _try_inv_api_set(cell_dict: dict, pay: dict | None) -> bool:
            if inv is None:
                return False

            r, c, idx = _cell_pos(cell_dict)

            for mname in (
                    "set_cell_payload",
                    "apply_cell_payload",
                    "update_cell_payload",
                    "replace_cell_payload",
                    "set_cell",
                    "update_cell",
                    "set_item_in_cell",
                    "inv_set_cell_payload",
            ):
                fn = getattr(inv, mname, None)
                if not callable(fn):
                    continue

                try:
                    fn(cell_dict, pay)
                    return True
                except TypeError:
                    pass
                except Exception:
                    pass

                if r is not None and c is not None:
                    try:
                        fn(r, c, pay)
                        return True
                    except TypeError:
                        pass
                    except Exception:
                        pass

                if idx is not None:
                    try:
                        fn(idx, pay)
                        return True
                    except TypeError:
                        pass
                    except Exception:
                        pass

            return False

        def _clone_payload(src: dict | None) -> dict | None:
            if not isinstance(src, dict):
                return None

            out = dict(src)

            for _k in (
                    "Stamp", "stamp", "StampBonuses", "StampBonusLines", "Bonuses",
                    "_cards", "cards", "Cards",
                    "Elixir", "_elixir",
            ):
                if _k not in out:
                    continue

                v = out.get(_k)
                try:
                    import copy as _copy2
                    out[_k] = _copy2.deepcopy(v)
                except Exception:
                    try:
                        out[_k] = dict(v)
                    except Exception:
                        try:
                            out[_k] = list(v)
                        except Exception:
                            out[_k] = v

            return out

        pay = _clone_payload(payload)

        # ---- если получилось через API инвентаря — выходим
        if _try_inv_api_set(cell_ref, pay):
            return

        # ---- fallback: правим dict напрямую
        preserve_keys_ci = {
            "row", "col", "rowindex", "colindex",
            "idx", "index", "cell", "cell_id", "cell_index",
            "slot", "slot_index", "grid_index", "pos", "x", "y", "page", "tab",
            "_row", "_col", "_rowindex", "_colindex",
            "_idx", "_index", "_cell", "_cell_id", "_cell_index",
            "_slot", "_slot_index", "_grid_index", "_pos", "_x", "_y", "_page", "_tab",
        }

        preserved = {}
        try:
            for k, v in list(cell_ref.items()):
                lk = str(k).casefold()

                # оставляем только служебные координаты/индексы ячейки,
                # а НЕ все подряд _*-поля старого предмета
                if lk not in preserve_keys_ci:
                    continue

                if lk in {
                    "_emptied", "_empty", "_is_empty",
                    "emptied", "empty", "isempty", "is_empty", "isemptied",
                    "isempty", "is_empty_cell"
                }:
                    continue

                preserved[k] = v
        except Exception:
            preserved = {}

        cell_ref.clear()

        if preserved:
            cell_ref.update(preserved)

        if pay:
            cell_ref.update(pay)

            for k in (
                    "_emptied", "_empty", "_is_empty",
                    "emptied", "empty", "is_empty", "isEmpty", "IsEmpty", "Empty", "is_empty_cell"
            ):
                try:
                    cell_ref.pop(k, None)
                except Exception:
                    pass

            try:
                cell_ref["Empty"] = False
            except Exception:
                pass
        else:
            try:
                cell_ref["_emptied"] = True
            except Exception:
                pass

    def on_inventory_swap_request(self, slot_key: str, new_item: dict, prev_item: Optional[dict]) -> bool:
        """
        Свап из инвентаря в слот.

        FIX (критичный):
          InventoryWindow может передавать new_item как копию dict, а не ссылку на реальную ячейку.
          Поэтому ВСЕ изменения ячейки делаем через резолв реальной ячейки по InstanceGuid.

        FIX (двуручка):
          если сейчас на персонаже ДВУРУЧКА и из инвентаря надеваем предмет в offhand:
            weapon(двуручка) -> в эту же ячейку
            предмет -> в offhand

        FIX (дубликат offhand):
          при надевании двуручки в weapon offhand переносится в инвентарь.
          если обработчик дергается повторно — add_item может добавлять тот же InstanceGuid второй раз.
          => перед add_item проверяем, нет ли уже такого InstanceGuid в инвентаре.
        """
        if not isinstance(getattr(self, "_selected_items", None), dict):
            self._selected_items = {}

        slot_key = str(slot_key or "").strip()
        inv = getattr(self, "inventory_window", None)

        # --- референс на РЕАЛЬНУЮ ячейку инвентаря ---
        src_cell_ref = new_item
        try:
            if inv is not None and isinstance(new_item, dict):
                src_cell_ref = self._resolve_inventory_cell_ref(new_item, inv)
        except Exception:
            src_cell_ref = new_item

        # --- входящий предмет (копия), InstanceGuid нужен стабильно ---
        # (если нет InstanceGuid — добавим и в копию, и в ячейку)
        try:
            src_tmp = dict(src_cell_ref) if isinstance(src_cell_ref, dict) else dict(new_item or {})
        except Exception:
            src_tmp = {}

        if not src_tmp.get("InstanceGuid"):
            try:
                guid = str(uuid4())
                src_tmp["InstanceGuid"] = guid
                if isinstance(src_cell_ref, dict):
                    src_cell_ref["InstanceGuid"] = guid
            except Exception:
                pass

        src = dict(src_tmp)
        inst_new = src.get("InstanceGuid")

        # --- блок по уровню персонажа (нельзя надеть предмет выше текущего уровня) ---
        try:
            cur_lvl = _safe_int(self.level_spin.value(), 1)
        except Exception:
            cur_lvl = None

        req_lvl = _safe_int(
            src.get("Level") or src.get("RequiredLevel") or src.get("ReqLevel") or 0,
            0,
        )
        if cur_lvl is not None and req_lvl > 0 and int(req_lvl) > int(cur_lvl):
            return False

        # ------------------------------------------------------------
        # ✅ FIX (обратный кейс): если сейчас на персонаже ДВУРУЧКА и
        # из инвентаря надеваем предмет в offhand — делаем swap:
        # двуручка -> в эту же ячейку, предмет -> в offhand.
        # ------------------------------------------------------------
        cell_replaced_by_weapon = False
        try:
            if slot_key == "offhand" and self._weapon_is_two_handed((self._selected_items or {}).get("weapon")):
                cell_replaced_by_weapon = self._swap_twohanded_weapon_into_inventory_cell(src_cell_ref, inv=inv)
                if cell_replaced_by_weapon:
                    # если swap успешен — src_cell_ref теперь содержит weapon, а в offhand пойдёт src
                    pass
        except Exception:
            cell_replaced_by_weapon = False

        # --- текущий предмет в слоте (куда надеваем) ---
        prev_item = prev_item if isinstance(prev_item, dict) else (self._selected_items or {}).get(slot_key)

        # --- чистим штамп у прошлого предмета в слоте (если был) ---
        if isinstance(prev_item, dict):
            inst_prev = prev_item.get("InstanceGuid")
            if inst_prev:
                try:
                    self._clear_stamp_for_instance(inst_prev)
                except Exception:
                    pass

        # --- НОРМАЛИЗУЕМ/ПОДТЯГИВАЕМ печать для src ---
        st_raw = None
        try:
            if hasattr(self.data, "get_item_stamp_by_instance") and inst_new:
                st_raw = self.data.get_item_stamp_by_instance(inst_new)
        except Exception:
            st_raw = None
        if st_raw is None:
            try:
                st_raw = (getattr(self, "_applied_stamps", {}) or {}).get(inst_new)
            except Exception:
                st_raw = None
        if st_raw is None:
            st_raw = src.get("Stamp") or src.get("stamp")

        st_norm = self._normalize_stamp_record(st_raw)
        if hasattr(self.data, "set_item_stamp_by_instance") and inst_new:
            try:
                self.data.set_item_stamp_by_instance(
                    inst_new,
                    _safe_int(st_norm["Id"]),
                    _safe_int(st_norm["ColorId"]),
                    list(st_norm["Bonuses"]),
                    st_norm["Name"],
                )
            except Exception:
                pass

        # вшить печать в item, который пойдёт в слот
        self._embed_stamp_into_item(src, st_norm)

        # удалить кэш штампа из инвентаря (если есть)
        if inv and hasattr(inv, "inv_clear_stamp_for_instance") and inst_new:
            try:
                inv.inv_clear_stamp_for_instance(inst_new)
            except Exception:
                pass

        # --- снап для возврата в инвентарь старого предмета (из target-слота) ---
        back_snap = None
        if prev_item:
            back_snap = self._ensure_instance_guid(dict(prev_item)) or {}
            back_snap["slot_key"] = str(slot_key)
            inst_prev = back_snap.get("InstanceGuid")

            prev_raw = None
            if hasattr(self.data, "get_item_stamp_by_instance") and inst_prev:
                try:
                    prev_raw = self.data.get_item_stamp_by_instance(inst_prev)
                except Exception:
                    prev_raw = None
            if prev_raw is None:
                prev_raw = (getattr(self, "_applied_stamps", {}) or {}).get(inst_prev)
            if prev_raw is None:
                prev_raw = prev_item.get("Stamp") or prev_item.get("stamp")

            st_prev = self._normalize_stamp_record(prev_raw)

            if hasattr(self.data, "set_item_stamp_by_instance") and inst_prev:
                try:
                    self.data.set_item_stamp_by_instance(
                        inst_prev,
                        _safe_int(st_prev["Id"]),
                        _safe_int(st_prev["ColorId"]),
                        list(st_prev["Bonuses"]),
                        st_prev["Name"],
                    )
                except Exception:
                    pass

            self._embed_stamp_into_item(back_snap, st_prev)

            if inv and hasattr(inv, "inv_set_stamp_for_instance") and inst_prev:
                try:
                    inv.inv_set_stamp_for_instance(
                        inst_prev,
                        _safe_int(st_prev["Id"]),
                        _safe_int(st_prev["ColorId"]),
                        list(st_prev["Bonuses"]),
                        st_prev["Name"],
                        st_prev.get("HeaderColorHex"),
                        st_prev.get("HeaderIconImageId"),
                    )
                except Exception:
                    pass

        # --- экипируем копию входящего экземпляра ---
        self._selected_items[str(slot_key)] = src

        # ✅ ДВУРУЧКА: правильный флаг
        try:
            if slot_key == "weapon":
                self._two_handed_equipped = bool(self._weapon_is_two_handed(src))
                try:
                    self._update_slot_icon("offhand")
                except Exception:
                    pass
        except Exception:
            pass

        # --- кладём обратно в ИМЕННО ЭТУ ячейку инвентаря старый предмет (или чистим её) ---
        # ✅ но если мы уже положили сюда weapon (swap при двуручке) — НЕ трогаем ячейку
        if not cell_replaced_by_weapon:
            if back_snap:
                self._assign_inventory_cell_payload(src_cell_ref, back_snap, inv=inv)
            else:
                self._assign_inventory_cell_payload(src_cell_ref, None, inv=inv)

        # рефреш инвентаря
        for meth in ("refresh", "repaint", "update", "rebuild", "_rebuild", "_rebuild_grid"):
            try:
                if inv and hasattr(inv, meth):
                    getattr(inv, meth)()
            except Exception:
                pass

        # обновить UI слота
        try:
            self._update_slot_icon(str(slot_key))
        except Exception:
            pass

        # оффхенд overlay / ghost
        try:
            self._update_offhand_overlay()
        except Exception:
            pass

        # дернуть "хуки"
        try:
            self._call_many(
                (
                    "refresh_equipment",
                    "_refresh_equipment_ui",
                    "rebuild_equipment",
                    "update_equipment_ui",
                    "recalc_stats",
                    "update_stats",
                    "on_equipment_changed",
                ),
                arg=str(slot_key),
            )
        except Exception:
            pass

        try:
            self.refresh_stats_panel()
        except Exception:
            pass

        return True

    def _stamp_payload_for_instance(self, instance_guid: str) -> Optional[dict]:
        return (getattr(self, "_stamp_cache_by_instance", {}) or {}).get(instance_guid)

    # === инвентарь ===
    def _ensure_inventory_window(self) -> None:
        if getattr(self, "inventory_window", None) is None:
            self.inventory_window = InventoryWindow(self)
            try:
                self.inventory_window.destroyed.connect(lambda: setattr(self, "inventory_window", None))
            except Exception:
                pass
            if hasattr(self.data, "get_image_bytes"):
                self.inventory_window.set_image_loader(self.data.get_image_bytes)

            # в _ensure_inventory_window
            def _allow(item, cls_ctx):
                try:
                    need = (
                            item.get("Class_Id") or item.get("ClassId") or
                            item.get("Required_Class_Id") or item.get("RequiredClassId")
                    )
                    if need is None or str(need).strip() == "":
                        return None  # ⟵ НЕ знаем, пусть решает инвентарь по БД
                    return _safe_int(need) == _safe_int(cls_ctx)
                except Exception:
                    return None

            self.inventory_window.on_player_gender_changed(self.get_current_gender_id())
            self.inventory_window.set_class_filter(_allow, filter_on_add=False)

        # ✅ если класс уже меняли до создания окна — применим отложенную чистку
        if bool(getattr(self, "_pending_inventory_prune", False)):
            self._pending_inventory_prune = False
            try:
                QTimer.singleShot(0, self._drop_invalid_inventory_for_new_class)
            except Exception:
                try:
                    self._drop_invalid_inventory_for_new_class()
                except Exception:
                    pass

    def _slot_id_from_item_type_id(self, type_id: int) -> Optional[int]:
        conn = getattr(getattr(self, "data", None), "conn", None)
        tid = _safe_int(type_id, 0)
        if conn is None or tid <= 0:
            return None
        try:
            row = conn.execute(
                "SELECT Slot_Id FROM EquipmentType WHERE Id=? LIMIT 1",
                (tid,)
            ).fetchone()
        except Exception:
            row = None
        if not row:
            return None
        try:
            return _safe_int(row[0] if isinstance(row, (tuple, list)) else row["Slot_Id"], 0) or None
        except Exception:
            return None

    def _request_inventory_prune_for_current_class(self) -> None:
        """
        Чистим инвентарь под текущий класс.
        Если окно инвентаря ещё не создано — ставим флаг, и почистим при первом создании.
        """
        inv = getattr(self, "inventory_window", None)
        if inv is None:
            self._pending_inventory_prune = True
            return
        self._drop_invalid_inventory_for_new_class()

    def _iter_inventory_cells(self, inv) -> Iterable[dict]:
        """
        Пытается достать ССЫЛКИ на dict-ячейки инвентаря.
        Поддерживает разные реализации InventoryWindow (методы/атрибуты).
        """
        if inv is None:
            return []

        # 1) методы-итераторы (если есть)
        for mname in ("iter_cells", "iter_all_cells", "all_cells", "get_cells", "get_all_cells"):
            fn = getattr(inv, mname, None)
            if callable(fn):
                try:
                    data = fn()
                except Exception:
                    data = None
                if data is None:
                    continue

                # data может быть list[dict] или list[list[dict]]
                stack = [data]
                out = []
                seen = set()
                while stack:
                    cur = stack.pop()
                    if isinstance(cur, dict):
                        oid = id(cur)
                        if oid not in seen:
                            seen.add(oid)
                            out.append(cur)
                    elif isinstance(cur, (list, tuple, set)):
                        stack.extend(list(cur))
                    elif isinstance(cur, (dict,)):
                        stack.extend(list(cur.values()))
                return out

        # 2) атрибуты-контейнеры
        candidates = (
            "cells", "_cells",
            "grid", "_grid",
            "items", "_items",
            "cells_data", "_cells_data",
            "data", "_data",
        )

        def _flatten(x):
            stack = [x]
            seen_obj = set()
            out = []
            while stack:
                cur = stack.pop()
                if cur is None:
                    continue
                oid = id(cur)
                if oid in seen_obj:
                    continue
                seen_obj.add(oid)

                if isinstance(cur, dict):
                    # сам dict может быть ячейкой ИЛИ мапой idx->ячейка
                    if ("Id" in cur) or ("Equip_Id" in cur) or ("InstanceGuid" in cur):
                        out.append(cur)
                    else:
                        stack.extend(list(cur.values()))
                elif isinstance(cur, (list, tuple, set)):
                    stack.extend(list(cur))
            return out

        for name in candidates:
            cont = getattr(inv, name, None)
            if cont is None:
                continue
            cells = _flatten(cont)
            if cells:
                return cells

        return []

    def _inventory_item_allowed_for_current_class(self, item: dict, lineage: List[int]) -> bool:
        """
        True если предмет в инвентаре допустим текущему классу И текущему полу.

        Логика:
          1) Gender_Id / GenderId / gender_id — проверяется всегда;
          2) EquipmentTypeCondition по Type_Id;
          3) list_equipment_for_slot по Slot_Id из EquipmentType + lineage;
          4) EquipmentCondition как финальная страховка.
        """
        if not isinstance(item, dict):
            return True

        eid = _safe_int(
            item.get("Id")
            or item.get("Equip_Id")
            or item.get("Equipment_Id")
            or item.get("EquipmentId"),
            0,
        )

        # ---------- gender check ----------
        current_gender = 1 if int(getattr(self, "_gender", 1) or 1) == 1 else 2

        def _item_gender_id_from_db(equip_id: int) -> Optional[int]:
            conn = getattr(getattr(self, "data", None), "conn", None)
            if conn is None or int(equip_id or 0) <= 0:
                return None

            col = None
            try:
                cols = conn.execute('PRAGMA table_info("Equipment")').fetchall()
                low_to_real = {}
                for r in cols or []:
                    try:
                        nm = r["name"] if hasattr(r, "keys") else r[1]
                    except Exception:
                        nm = None
                    if nm:
                        low_to_real[str(nm).lower()] = str(nm)

                for cand in ("Gender_Id", "Gender_ID", "GenderId", "gender_id"):
                    if cand.lower() in low_to_real:
                        col = low_to_real[cand.lower()]
                        break
            except Exception:
                col = None

            if not col:
                return None

            try:
                row = conn.execute(
                    f'SELECT "{col}" FROM "Equipment" WHERE Id=? LIMIT 1',
                    (int(equip_id),),
                ).fetchone()
            except Exception:
                row = None

            if not row:
                return None

            try:
                raw = row[col] if hasattr(row, "keys") else row[0]
            except Exception:
                raw = None

            if raw in (None, ""):
                return None

            try:
                return int(raw)
            except Exception:
                return None

        # 1) сначала поле прямо в item
        item_gender = None
        for k in ("Gender_Id", "Gender_ID", "GenderId", "gender_id"):
            if item.get(k) not in (None, ""):
                item_gender = _safe_int(item.get(k), 0)
                break

        # 2) если в item пола нет — добираем из БД
        if item_gender is None and eid > 0:
            item_gender = _item_gender_id_from_db(eid)

        # 0 / NULL считаем универсальным предметом
        if item_gender is not None and int(item_gender) > 0 and int(item_gender) != int(current_gender):
            return False

        # ---------- class check ----------
        if eid <= 0:
            return True

        cur_class_id = _safe_int(self._current_class_id(), 0)
        if cur_class_id <= 0:
            return True

        tid = _safe_int(item.get("Type_Id") or item.get("TypeId"), 0)

        # (1) Type-condition
        if tid and not self._class_allows_equipment_type(tid, class_id=cur_class_id):
            return False

        # (2) Slot+class allowed list
        sid = self._slot_id_from_item_type_id(tid)
        if sid:
            allowed_ids: set[int] = set()
            for cid in (lineage or []):
                allowed_ids |= self._allowed_equipment_ids_for(int(sid), int(cid))

            if allowed_ids and eid not in allowed_ids:
                return False

        # (3) EquipmentCondition fallback
        try:
            if not self._equipment_allowed_for_class(eid, list(lineage or [])):
                return False
        except Exception:
            pass

        return True

    def _drop_invalid_inventory_for_new_class(self) -> None:
        """
        Очищает ИНВЕНТАРЬ от предметов, не подходящих текущему классу или текущему полу.
        Работает по месту: чистит dict-ячейку и чистит stamp по InstanceGuid.
        """
        lineage = self._compatible_class_ids_for_current()

        inv = getattr(self, "inventory_window", None)
        if inv is None:
            self._pending_inventory_prune = True
            return

        # Сначала синхронизируем контекст самого InventoryWindow.
        try:
            fn = getattr(inv, "on_player_gender_changed", None)
            if callable(fn):
                fn(self.get_current_gender_id())
        except Exception:
            pass

        try:
            fn = getattr(inv, "on_player_class_changed", None)
            if callable(fn):
                cls_ctx = self._current_class_id()
                if cls_ctx is None:
                    cls_ctx = self.class_combo.currentText()
                fn(cls_ctx)
        except Exception:
            pass

        # Если класс не удалось получить — всё равно пол уже почистился через InventoryWindow.
        if not lineage:
            return

        removed = 0

        cells = list(self._iter_inventory_cells(inv))
        if not cells:
            return

        for cell in cells:
            if not isinstance(cell, dict):
                continue

            if cell.get("_emptied") is True:
                continue

            eid = _safe_int(
                cell.get("Id")
                or cell.get("Equip_Id")
                or cell.get("Equipment_Id")
                or cell.get("EquipmentId"),
                0,
            )
            if eid <= 0:
                continue

            if self._inventory_item_allowed_for_current_class(cell, lineage):
                continue

            inst = cell.get("InstanceGuid")

            if inst:
                try:
                    self._clear_stamp_for_instance(inst)
                except Exception:
                    pass

                if hasattr(inv, "inv_clear_stamp_for_instance"):
                    try:
                        inv.inv_clear_stamp_for_instance(inst)
                    except Exception:
                        pass

            removed_by_api = False
            if inst:
                for mname in (
                        "remove_item_by_instance",
                        "remove_instance",
                        "remove_by_instance",
                        "delete_instance",
                        "inv_remove_item_by_instance",
                ):
                    fn = getattr(inv, mname, None)
                    if callable(fn):
                        try:
                            fn(inst)
                            removed_by_api = True
                            break
                        except Exception:
                            pass

            if not removed_by_api:
                try:
                    cell.clear()
                    cell["_emptied"] = True
                except Exception:
                    pass

            removed += 1

        if removed:
            for meth in ("refresh", "repaint", "update_grid", "refresh_grid", "update"):
                fn = getattr(inv, meth, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass

            try:
                inv._reflow_after_changes()
            except Exception:
                pass

            try:
                inv._update_capacity_indicator()
            except Exception:
                pass

    def _toggle_inventory(self) -> None:
        """Открыть/закрыть инвентарь как тумблер."""
        self._ensure_inventory_window()
        w = self.inventory_window
        if w.isVisible():
            w.hide()
        else:
            w.open_right_of(self)

    def _on_menu_bag_clicked(self) -> None:
        self._toggle_inventory()

    # === печати по item_id / instance ===
    def _clear_stamp_for_item_id(self, item_id: int) -> None:
        """Очистка печати по item_id (и по всем найденным экземплярам в слотах)."""
        if not item_id:
            return

        if hasattr(self.data, "clear_item_stamp"):
            try:
                self.data.clear_item_stamp(int(item_id))
            except Exception:
                pass

        insts_to_clear: List[str] = []
        try:
            for it in (self._selected_items or {}).values():
                if not it:
                    continue
                if _safe_int(it.get("Id"), 0) == _safe_int(item_id, 0):
                    inst = it.get("InstanceGuid")
                    if inst:
                        insts_to_clear.append(inst)
        except Exception:
            insts_to_clear = []

        for inst in insts_to_clear:
            self._clear_stamp_for_instance(inst)
            inv = getattr(self, "inventory_window", None)
            if inv and hasattr(inv, "inv_clear_stamp_for_instance"):
                try:
                    inv.inv_clear_stamp_for_instance(inst)
                except Exception:
                    pass

    def _add_item_to_inventory(self, item: dict | None, slot_key: str | None = None) -> None:
        sk = str(slot_key or "").strip().lower()

        # Костюм / Украшение / Ездовое животное нельзя копировать в инвентарь
        # ни через Ctrl+ПКМ, ни через старые/случайные вызовы этого метода.
        if sk in NON_INVENTORY_COPY_SLOTS:
            return

        if not item:
            return

        snap = self._make_inventory_snapshot(item, new_instance=True, slot_key=slot_key)
        self._try_add_to_inventory(snap)

    def _remove_from_slot_keep_stamp(self, slot_key: str) -> None:
        """Снять предмет со слота, НЕ трогая печать этого инстанса. Обновляет UI и статы."""
        slot_key = str(slot_key)

        # снять предмет
        try:
            (self._selected_items or {}).pop(slot_key, None)
        except Exception:
            pass

        # убрать маску тултипа
        try:
            self._mask_stamp_slots.discard(slot_key)
        except Exception:
            pass

        # спец-логика костюма
        if slot_key == "costume":
            try:
                self._sil_original = self._sil_pm_m if self._gender == 1 else self._sil_pm_f
                self._layout_overlays()
            except Exception:
                pass

        # если сняли оружие — двуручность сбросить
        if slot_key == "weapon":
            self._two_handed_equipped = False

        # обновить иконку слота (сам спрячется если предмета нет)
        try:
            self._update_slot_icon(slot_key)
        except Exception:
            # fallback на прямое скрытие QLabel, если вдруг
            try:
                lbl = (self._slot_icons or {}).get(slot_key)
                if lbl:
                    lbl.hide()
            except Exception:
                pass

        # оффхенд overlay / ghost
        try:
            self._update_offhand_overlay()
        except Exception:
            pass

        # дернуть "хуки" (но без refresh_stats_panel внутри — вызовем напрямую один раз)
        try:
            self._call_many(
                (
                    "refresh_equipment",
                    "_refresh_equipment_ui",
                    "rebuild_equipment",
                    "update_equipment_ui",
                    "recalc_stats",
                    "update_stats",
                    "on_equipment_changed",
                ),
                arg=slot_key,
            )
        except Exception:
            pass

        # КЛЮЧЕВОЕ: пересчитать панель статов
        try:
            self.refresh_stats_panel()
        except Exception:
            pass

    def _move_slot_item_to_inventory(self, slot_key: str) -> bool:
        """
        Переместить предмет из слота в инвентарь.
        FIX: если надета двуручка, ПКМ по offhand работает как ПКМ по weapon.
        """
        slot_key = str(slot_key or "").strip()

        # Костюм / Украшение / Ездовое животное вообще не должны попадать в инвентарь
        # из главного окна.
        if slot_key.lower() in NON_INVENTORY_COPY_SLOTS:
            return False

        # ✅ двуручка: ПКМ по offhand = снять оружие
        try:
            if slot_key == "offhand" and self._is_offhand_disabled():
                if (getattr(self, "_selected_items", None) or {}).get("weapon"):
                    slot_key = "weapon"
        except Exception:
            pass

        item = (self._selected_items or {}).get(slot_key)
        if not item:
            return False

        try:
            snap = self._make_inventory_snapshot(item, new_instance=False, slot_key=slot_key)
        except Exception:
            return False

        try:
            ok = bool(self._try_add_to_inventory(snap))
        except Exception:
            ok = False

        if not ok:
            return False

        # успешно добавили — снимаем со слота и пересчитываем всё
        self._remove_from_slot_keep_stamp(slot_key)
        return True

    def _make_inventory_snapshot(self, item: dict, *, new_instance: bool, slot_key: str | None):
        it = self._ensure_instance_guid(dict(item)) or {}
        snap = self._clone_new_instance(it) if new_instance else dict(it)
        if slot_key:
            snap["slot_key"] = str(slot_key)

        # ---------------- stamp (как было) ----------------
        st = self._stamp_payload_for_item(it)  # DAO → лок. кэш → embedded
        if st:
            self._embed_stamp_into_item(snap, st)
            inst = snap.get("InstanceGuid")
            if new_instance and inst:
                # персист штампа для НОВОГО экземпляра
                if hasattr(self.data, "set_item_stamp_by_instance"):
                    self.data.set_item_stamp_by_instance(
                        inst,
                        int(st.get("Id") or 0),
                        int(st.get("ColorId") or 0),
                        list(st.get("Bonuses") or []),
                        st.get("Name") or "",
                    )
                if not hasattr(self, "_applied_stamps") or not isinstance(self._applied_stamps, dict):
                    self._applied_stamps = {}
                self._applied_stamps[inst] = {
                    "id": int(st.get("Id") or 0),
                    "color_id": int(st.get("ColorId") or 0),
                    "name": st.get("Name") or "",
                    "bonuses": list(st.get("Bonuses") or []),
                }
            elif not new_instance and inst and getattr(self, "inventory_window", None):
                # прогреть кэш инвентаря для СТАРОГО экземпляра
                try:
                    self.inventory_window.inv_set_stamp_for_instance(
                        inst,
                        int(st.get("Id") or 0),
                        int(st.get("ColorId") or 0),
                        list(st.get("Bonuses") or []),
                        st.get("Name") or "",
                        st.get("HeaderColorHex"),
                        st.get("HeaderIconImageId") or st.get("icon_id"),
                    )
                except Exception:
                    pass

        # ---------------- elixir (как было) ----------------
        ELX_BASE = 9000
        ELX_LIM = 9100

        def _clear_elixir_inline(d: dict) -> None:
            if not isinstance(d, dict):
                return
            for kk in list(d.keys()):
                if not isinstance(kk, str):
                    continue
                suf = None
                if kk.startswith("BonusType"):
                    suf = kk[len("BonusType"):]
                elif kk.startswith("Var"):
                    suf = kk[len("Var"):]
                elif kk.startswith("Value"):
                    suf = kk[len("Value"):]
                if suf is None:
                    continue
                try:
                    idx = int(suf)
                except Exception:
                    continue
                if ELX_BASE <= idx < ELX_LIM:
                    d.pop(kk, None)

        src_inst = str(it.get("InstanceGuid") or "").strip()
        el_payload = None

        el = it.get("Elixir") or it.get("_elixir")
        if isinstance(el, dict) and _safe_int(el.get("Id") or el.get("id"), 0) > 0:
            el_payload = dict(el)
            el_payload["Id"] = _safe_int(el_payload.get("Id") or el_payload.get("id"), 0)
            el_payload["Name"] = str(el_payload.get("Name") or el_payload.get("name") or "")
            if "Bonuses" not in el_payload:
                el_payload["Bonuses"] = list(el_payload.get("bonuses") or [])
        else:
            cache = getattr(self, "_applied_elixirs", None)
            if isinstance(cache, dict) and src_inst and isinstance(cache.get(src_inst), dict):
                rec = cache.get(src_inst) or {}
                eid = _safe_int(rec.get("id") or rec.get("Id"), 0)
                if eid > 0:
                    el_payload = {
                        "Id": eid,
                        "Name": str(rec.get("name") or rec.get("Name") or ""),
                        "Image_Id": rec.get("image_id") if rec.get("image_id") is not None else rec.get("Image_Id"),
                        "Bonuses": list(rec.get("bonuses") or rec.get("Bonuses") or []),
                    }

        if isinstance(el_payload, dict) and _safe_int(el_payload.get("Id"), 0) > 0:
            if not isinstance(el_payload.get("Bonuses"), list) or not el_payload.get("Bonuses"):
                conn = getattr(getattr(self, "data", None), "conn", None)
                if conn is not None:
                    try:
                        from .equipment_elixir import get_elixir_bonuses, get_elixir_meta
                        meta = get_elixir_meta(conn, int(el_payload["Id"])) or {}
                        if not el_payload.get("Name"):
                            el_payload["Name"] = str(meta.get("Name") or "")
                        if el_payload.get("Image_Id") is None:
                            el_payload["Image_Id"] = meta.get("Image_Id")
                        el_payload["Bonuses"] = list(get_elixir_bonuses(conn, int(el_payload["Id"])) or [])
                    except Exception:
                        pass

            _clear_elixir_inline(snap)
            snap.pop("_elixir", None)
            snap["Elixir"] = {
                "Id": _safe_int(el_payload.get("Id"), 0),
                "Name": str(el_payload.get("Name") or ""),
                "Image_Id": el_payload.get("Image_Id"),
                "Bonuses": list(el_payload.get("Bonuses") or []),
            }

            try:
                bonuses_sorted = sorted(
                    [b for b in (snap["Elixir"]["Bonuses"] or []) if isinstance(b, dict)],
                    key=lambda b: _safe_int(b.get("OrderIndex"), 0),
                )
            except Exception:
                bonuses_sorted = [b for b in (snap["Elixir"]["Bonuses"] or []) if isinstance(b, dict)]

            i = 0
            for b in bonuses_sorted:
                idx = ELX_BASE + i
                if idx >= ELX_LIM:
                    break
                bt = _safe_int(b.get("Type_Id"), 0)
                val = _safe_int(b.get("Value"), 0)
                if bt > 0 and val != 0:
                    snap[f"BonusType{idx}"] = int(bt)
                    snap[f"Var{idx}"] = int(val)
                i += 1

            if new_instance:
                new_inst = str(snap.get("InstanceGuid") or "").strip()
                if new_inst:
                    cache = getattr(self, "_applied_elixirs", None)
                    if not isinstance(cache, dict):
                        cache = {}
                        self._applied_elixirs = cache
                    cache[new_inst] = {
                        "id": _safe_int(snap["Elixir"]["Id"], 0),
                        "name": snap["Elixir"]["Name"] or "",
                        "image_id": snap["Elixir"].get("Image_Id"),
                        "bonuses": list(snap["Elixir"].get("Bonuses") or []),
                    }

        # ---------------- cards (FIX) ----------------
        def _deepcopy_local(v):
            import copy as _copy
            try:
                return _copy.deepcopy(v)
            except Exception:
                try:
                    return dict(v)
                except Exception:
                    try:
                        return list(v)
                    except Exception:
                        return v

        def _normalize_cards_map(raw) -> dict[int, dict]:
            out: dict[int, dict] = {}

            if isinstance(raw, dict):
                items = list(raw.items())
            elif isinstance(raw, (list, tuple)):
                items = [(i + 1, raw[i]) for i in range(len(raw))]
            else:
                items = []

            for k, v in items:
                try:
                    idx = int(k)
                except Exception:
                    continue
                if idx <= 0 or not isinstance(v, dict):
                    continue
                out[int(idx)] = _deepcopy_local(v)

            return out

        cards_payload: dict[int, dict] = {}

        # 1) сначала пробуем то, что уже лежит прямо в item
        for ck in ("_cards", "cards", "Cards"):
            cards_payload = _normalize_cards_map(it.get(ck))
            if cards_payload:
                break

        # 2) если inline нет — пробуем достать из CardsWindow по кэшу экземпляра
        cw = getattr(self, "cards_window", None)
        try:
            slot_guess = str(slot_key or it.get("slot_key") or it.get("SlotKey") or "").strip()
        except Exception:
            slot_guess = ""

        try:
            kind_guess = "weapon" if (slot_guess and self._slot_kind(slot_guess) == "weapon") else "equipment"
        except Exception:
            kind_guess = "weapon" if slot_guess in {"weapon", "offhand", "spear"} else "equipment"

        if not cards_payload and cw is not None and hasattr(cw, "get_cards_for_item"):
            try:
                cards_payload = _normalize_cards_map(
                    cw.get_cards_for_item(
                        it,
                        kind=kind_guess,
                        slot_key=(slot_guess or None),
                    )
                )
            except Exception:
                cards_payload = {}

        if cards_payload:
            snap["_cards"] = _deepcopy_local(cards_payload)
            snap["cards"] = _deepcopy_local(cards_payload)
            snap["Cards"] = _deepcopy_local(cards_payload)

        # 3) для нового экземпляра обязательно клонируем и карточный кэш CardsWindow
        if new_instance and cw is not None and hasattr(cw, "clone_cards_between_items"):
            try:
                cw.clone_cards_between_items(
                    src_item=it,
                    dst_item=snap,
                    kind=kind_guess,
                    src_slot_key=(slot_guess or None),
                    dst_slot_key=(slot_guess or None),
                )
            except Exception:
                pass

        return snap

    def _try_add_to_inventory(self, snap: dict) -> bool:
        self._ensure_inventory_window()
        ok = self.inventory_window.add_item(snap)
        self.inventory_window.open_right_of(self, margin=12, v_align="center")
        return ok

    def _clear_all_stamps_on_class_change(self) -> None:
        """Забыть все наложенные печати при смене класса (локально + DAO + UI)."""
        if hasattr(self, "_applied_stamps"):
            try:
                self._applied_stamps.clear()
            except Exception:
                self._applied_stamps = {}

        if hasattr(self, "stamp_window") and self.stamp_window is not None:
            self.stamp_window.reset_stamps_cache()

        if hasattr(self, "equip_info"):
            self.equip_info.hide()

    def _class_bucket_from_name(self, name: str) -> str:
        """
        Возвращает "семью" класса без хардкода по подстрокам:
        берём ROOT (класс без Base_Id) и возвращаем его Name в lower().
        Примеры: 'мечник', 'стрелок', 'маг', 'вор' (и любые будущие root-классы).
        """
        n = (name or "").strip().casefold()

        cid = None
        try:
            # если это текущий выбранный — берём id напрямую
            if n and hasattr(self, "class_combo") and n == (self.class_combo.currentText() or "").strip().casefold():
                cid = self._current_class_id()
        except Exception:
            cid = None

        if not cid:
            for _cid, _cname, _ in getattr(self, "_classes", []):
                if (str(_cname or "").strip().casefold() == n) or (n and n == str(_cname or "").strip().casefold()):
                    cid = _cid
                    break

        cid = _safe_int(cid, 0)
        if cid <= 0:
            return "unknown"

        lineage = self._class_lineage_ids(cid)
        root_id = lineage[-1] if lineage else cid
        root_row = self._get_class_row(root_id) or {}
        return (root_row.get("Name") or "unknown").strip().casefold()

    def _compatible_class_ids_for_current(self) -> List[int]:
        """
        Возвращает список Id классов, чьи вещи может носить ТЕКУЩИЙ класс.
        DB-логика: текущий класс + все предки по Base_Id.
        """
        cur_id = _safe_int(self._current_class_id(), 0)
        if cur_id <= 0:
            return []
        return self._class_lineage_ids(cur_id)

    def _is_base_class(self) -> bool:
        cid = _safe_int(self._current_class_id(), 0)
        if cid <= 0:
            return False
        row = self._get_class_row(cid) or {}
        return row.get("Base_Id") is None

    def _is_advanced_class(self) -> bool:
        cid = _safe_int(self._current_class_id(), 0)
        if cid <= 0:
            return False
        row = self._get_class_row(cid) or {}
        return row.get("Base_Id") is not None

    def _is_before20_class(self) -> bool:
        # твоя текущая логика иконок пола “до 20” = базовые классы
        return self._is_base_class()


    # --- экземпляры предметов ----------------------------------------------------
    def _ensure_instance_guid(self, item: Optional[dict]) -> Optional[dict]:
        """Гарантирует, что у предмета есть уникальный InstanceGuid (немутирующий для входного dict)."""
        if not item:
            return None
        if not item.get("InstanceGuid"):
            item = dict(item)
            item["InstanceGuid"] = str(uuid4())
        return item

    def _refresh_hover_after_modal(self) -> None:
        # 1) обновим glow из текущей позиции курсора
        self._update_glow_from_global()
        # 2) если курсор уже над иконкой слота — показать анкету сразу
        gp = QCursor.pos()
        for key, lbl in (self._slot_icons or {}).items():
            if not lbl or not lbl.isVisible():
                continue
            anchor_rect = QRect(lbl.mapToGlobal(lbl.rect().topLeft()), lbl.rect().size())
            if not anchor_rect.contains(gp):
                continue
            it = (self._selected_items or {}).get(key)
            if not it:
                break
            bonus_lines = _render_bonus_lines(self.data.conn, _safe_int(it.get("Id"), 0))
            mask_slots = getattr(self, "_mask_stamp_slots", None) or set()
            stamp_payload = None
            if key not in mask_slots:
                stamp_payload = self._stamp_payload_for_item(it)
            if key == "ornament":
                stamp_payload = False
            # ВАЖНО: якорная точка = центр предмета (без setY(top))
            gp2 = anchor_rect.center()

            try:
                self.equip_info._ctx_root = self
            except Exception:
                pass

            self.equip_info.show_for_item(
                it,
                image_loader=self.data.get_image_bytes,
                global_pos=gp2,
                type_name=None,
                type_name_lookup=self._etype_name_by_id,
                item_class=it.get("ItemClass"),
                cards=None,
                bonus_lines=bonus_lines,
                stamp=stamp_payload,
                anchor_rect_global=anchor_rect,
            )
            # поднять окно тултипа
            self.equip_info.show()
            self.equip_info.raise_()
            self.equip_info.update()
            break

    def _clone_new_instance(self, item: Optional[dict]) -> Optional[dict]:
        """Делает копию предмета как нового экземпляра (новый InstanceGuid) с полным переносом вложенных данных."""
        if not isinstance(item, dict):
            return None

        import copy as _copy

        try:
            out = _copy.deepcopy(item)
        except Exception:
            out = dict(item)

            for k in (
                    "Stamp", "stamp", "StampBonuses", "StampBonusLines", "Bonuses",
                    "_cards", "cards", "Cards",
                    "Elixir", "_elixir",
            ):
                if k not in out:
                    continue
                v = out.get(k)
                try:
                    out[k] = _copy.deepcopy(v)
                except Exception:
                    try:
                        out[k] = dict(v)
                    except Exception:
                        try:
                            out[k] = list(v)
                        except Exception:
                            out[k] = v

        out["InstanceGuid"] = str(uuid4())
        return out

    # --- сохранение/чтение печатей (по InstanceGuid) -----------------------------
    def _clear_stamp_for_instance(self, inst_id: str) -> None:
        """Стереть печать, привязанную к конкретному экземпляру предмета."""
        if not inst_id:
            return
        if hasattr(self.data, "clear_item_stamp_by_instance"):
            self.data.clear_item_stamp_by_instance(inst_id)
            return
        if not hasattr(self, "_applied_stamps") or not isinstance(self._applied_stamps, dict):
            self._applied_stamps = {}
        self._applied_stamps.pop(inst_id, None)

    def _clear_stamp_for_slot(self, slot_key: str) -> None:
        """Очистить печать только у текущего предмета в слоте (по InstanceGuid)."""
        it = (self._selected_items or {}).get(slot_key)
        if not it:
            return
        inst = it.get("InstanceGuid")
        if inst:
            self._clear_stamp_for_instance(inst)

    def _stamp_color_meta(self, color_id: int) -> Optional[dict]:
        """
        Читает цвет/иконку печати из БД StampColor с кешированием.
        """
        cid = _safe_int(color_id, 0)
        if cid <= 0:
            return None

        cache = self._stamp_color_cache
        if cid in cache:
            return cache[cid]

        conn = getattr(getattr(self, "data", None), "conn", None)
        if not conn:
            return None

        row = conn.execute(
            "SELECT Argb, Image_Id FROM StampColor WHERE Id=? LIMIT 1",
            (cid,),
        ).fetchone()

        if not row:
            return None

        # Row может быть Row/tuple
        if hasattr(row, "keys"):
            hexv = row["Argb"]
            icon = row["Image_Id"]
        else:
            hexv, icon = row[0], row[1]

        meta = {"hex": hexv, "icon_img_id": icon}
        cache[cid] = meta
        return meta

    # ---------- штампы: payload / применение ----------
    def _stamp_payload_for_item(self, item_or_id_or_inst) -> Optional[dict]:
        """
        Возвращает payload печати для КОНКРЕТНОГО ЭКЗЕМПЛЯРА.

        Больше НЕ ИЩЕМ по item_id (чтобы печати не «переезжали» между экземплярами).
        Работают два варианта:
          • dict item → берём item['InstanceGuid'] (fallback к item['Stamp'] при необходимости);
          • str inst  → используем как InstanceGuid напрямую.

        Возврат: нормализованный dict или None.
        """
        if not item_or_id_or_inst:
            return None

        # 1) InstanceGuid
        inst: Optional[str] = None
        item_dict: Optional[dict] = None
        if isinstance(item_or_id_or_inst, dict):
            item_dict = item_or_id_or_inst
            inst = item_dict.get("InstanceGuid")
        elif isinstance(item_or_id_or_inst, str):
            inst = item_or_id_or_inst
        else:
            return None  # int item_id и прочее — намеренно не поддерживаем

        # 2) DAO → локальный кэш
        rec = None
        if inst and hasattr(self, "data") and hasattr(self.data, "get_item_stamp_by_instance"):
            rec = self.data.get_item_stamp_by_instance(inst)
        if not rec and inst:
            rec = (getattr(self, "_applied_stamps", {}) or {}).get(inst)

        # 3) Фоллбэк к «вшитому» в item штампу
        if not rec and item_dict:
            rec = item_dict.get("Stamp") or item_dict.get("stamp")

        if not rec:
            return None

        # 4) Нормализация + косметика
        norm = self._normalize_stamp_record(rec) or {}
        color_id = _safe_int(norm.get("ColorId"), 0)
        meta = self._stamp_color_meta(color_id) or {}
        if "HeaderColorHex" not in norm and meta.get("hex"):
            norm["HeaderColorHex"] = meta.get("hex")
        if ("HeaderIconImageId" not in norm and "icon_id" not in norm) and meta.get("icon_img_id"):
            norm["HeaderIconImageId"] = meta.get("icon_img_id")
            norm["icon_id"] = meta.get("icon_img_id")

        # дубликаты для совместимости
        norm["BonusLines"] = list(norm.get("Bonuses") or [])
        norm["Effects"] = list(norm.get("Bonuses") or [])
        norm["name"] = norm.get("Name") or ""
        return norm

    def apply_stamp_to_item(
            self,
            instance_guid: str,
            stamp_id: int,
            color_id: int,
            bonuses: List[str],
            stamp_name: str,
    ) -> None:
        """
        Принять выбор печати из StampWindow и сохранить его за КОНКРЕТНЫМ ЭКЗЕМПЛЯРОМ.

        Ключевое:
          - сохраняем в БД + локальный кэш
          - вшиваем печать прямо в надетый item (если он найден)
          - ДЁРГАЕМ refresh_stats_panel() чтобы статы обновились сразу, без "снять/надеть"
        """
        if not instance_guid:
            return

        # --- нормализация входа ---
        stamp_id = _safe_int(stamp_id, 0)
        color_id = _safe_int(color_id, 0)
        stamp_name = stamp_name or ""
        bonuses = list(bonuses or [])

        # 1) персист
        if hasattr(self, "data") and hasattr(self.data, "set_item_stamp_by_instance"):
            self.data.set_item_stamp_by_instance(
                instance_guid=instance_guid,
                stamp_id=stamp_id,
                color_id=color_id,
                bonuses=bonuses,
                name=stamp_name,
            )

        # 2) локальный кэш
        if not hasattr(self, "_applied_stamps") or not isinstance(self._applied_stamps, dict):
            self._applied_stamps = {}
        self._applied_stamps[instance_guid] = {
            "id": stamp_id,
            "color_id": color_id,
            "name": stamp_name,
            "bonuses": bonuses,
        }

        # 3) найти слот, где надет этот инстанс
        slot_key_of_item = None
        equipped_item = None
        for k, it in (self._selected_items or {}).items():
            if it and it.get("InstanceGuid") == instance_guid:
                slot_key_of_item = k
                equipped_item = it
                break

        # 4) собрать нормализованный stamp payload и вшить в предмет
        st_norm = self._normalize_stamp_record(
            {
                "Id": stamp_id,
                "ColorId": color_id,
                "Name": stamp_name,
                "Bonuses": bonuses,
            }
        )

        item_id = 0
        if slot_key_of_item and isinstance(equipped_item, dict):
            try:
                item_id = _safe_int(equipped_item.get("Id"), 0)
            except Exception:
                item_id = 0

            # вшиваем во все поля, которые используют тултипы/инвентарь/математика
            self._embed_stamp_into_item(equipped_item, st_norm)
            # доп. алиас — на случай если где-то в коде ждёшь именно "_stamp"
            equipped_item["_stamp"] = dict(st_norm)
        # 5) снять подавление (у тебя suppress хранит item_id, а не instance_guid)
        if item_id and isinstance(getattr(self, "_suppress_stamp_equipped", None), set):
            self._suppress_stamp_equipped.discard(int(item_id))
        # 6) рефреш UI слота (иконка/анкета) + пересчёты
        if slot_key_of_item:
            self.refresh_equipment_slot(slot_key_of_item)
            for fn_name in (
                    "refresh_equipment",
                    "_refresh_equipment_ui",
                    "rebuild_equipment",
                    "update_equipment_ui",
                    "recalc_stats",
                    "update_stats",
                    "on_equipment_changed",
            ):
                fn = getattr(self, fn_name, None)
                if callable(fn):
                    fn(slot_key_of_item)
        # 7) ВОТ ЭТОГО НЕ ХВАТАЛО: сразу обновить правую панель статов
        self.refresh_stats_panel()
        # 8) если курсор всё ещё над предметом — можно мгновенно обновить анкету (не обязательно, но приятно)
        QTimer.singleShot(0, self._refresh_hover_after_modal)

    # =========================
    # Equipment Elixir (пер-экземпляр)
    # =========================
    _ELIXIR_INLINE_BASE = 9000
    _ELIXIR_INLINE_LIMIT = 9100

    def _elixir_payload_for_item(self, item: dict) -> Optional[dict]:
        """
        Возвращает payload эликсира для конкретного item.
        Источники (в порядке приоритета):
          1) item["Elixir"] / item["_elixir"] (embedded)
          2) локальный кэш self._applied_elixirs[InstanceGuid]
        """
        if not isinstance(item, dict) or not item:
            return None

        el = item.get("Elixir") or item.get("_elixir")
        if isinstance(el, dict) and int(el.get("Id") or el.get("id") or 0) > 0:
            eid = _safe_int(el.get("Id") or el.get("id"), 0)
            out = dict(el)
            out["Id"] = eid
            out["Name"] = str(out.get("Name") or out.get("name") or "")
            if out.get("Image_Id") is None:
                out["Image_Id"] = out.get("image_id")
            return out

        inst = str(item.get("InstanceGuid") or "").strip()
        if not inst:
            return None

        cache = getattr(self, "_applied_elixirs", None)
        if not isinstance(cache, dict):
            return None

        rec = cache.get(inst)
        if not isinstance(rec, dict):
            return None

        eid = _safe_int(rec.get("id") or rec.get("Id"), 0)
        if eid <= 0:
            return None

        return {
            "Id": eid,
            "Name": str(rec.get("name") or rec.get("Name") or ""),
            "Image_Id": rec.get("image_id") if rec.get("image_id") is not None else rec.get("Image_Id"),
            "Bonuses": list(rec.get("bonuses") or rec.get("Bonuses") or []),
        }

    def _clear_elixir_inline_fields(self, item: dict) -> None:
        if not isinstance(item, dict) or not item:
            return

        base = int(getattr(self, "_ELIXIR_INLINE_BASE", 9000))
        lim = int(getattr(self, "_ELIXIR_INLINE_LIMIT", 9100))

        def _idx_from_key(k: str) -> int | None:
            try:
                if not isinstance(k, str):
                    return None
                if k.startswith("BonusType"):
                    return int(k[len("BonusType"):])
                if k.startswith("Var"):
                    return int(k[len("Var"):])
                if k.startswith("Value"):
                    return int(k[len("Value"):])
            except Exception:
                return None
            return None

        for k in list(item.keys()):
            idx = _idx_from_key(k)
            if idx is None:
                continue
            if base <= idx < lim:
                item.pop(k, None)

    def _embed_elixir_into_item(self, item: dict, payload: Optional[dict]) -> None:
        """
        Вшивает эликсир в item:
          - item["Elixir"] (для UI)
          - BonusTypeXXXX/VarXXXX (для math через inline бонусы)
        """
        if not isinstance(item, dict) or not item:
            return

        self._clear_elixir_inline_fields(item)
        item.pop("Elixir", None)
        item.pop("_elixir", None)

        if not payload:
            return

        eid = _safe_int(payload.get("Id") or payload.get("id"), 0)
        if eid <= 0:
            return

        name = str(payload.get("Name") or payload.get("name") or "")
        img_id = payload.get("Image_Id")
        bonuses = payload.get("Bonuses") or payload.get("bonuses") or []
        if not isinstance(bonuses, list):
            bonuses = list(bonuses) if bonuses else []

        norm_payload = {
            "Id": eid,
            "Name": name,
            "Image_Id": img_id,
            "Bonuses": list(bonuses),
        }
        item["Elixir"] = dict(norm_payload)

        base = int(getattr(self, "_ELIXIR_INLINE_BASE", 9000))
        lim = int(getattr(self, "_ELIXIR_INLINE_LIMIT", 9100))
        i = 0

        def _order_key(r):
            try:
                return int(r.get("OrderIndex") or 0)
            except Exception:
                return 0

        try:
            bonuses_sorted = sorted([b for b in bonuses if isinstance(b, dict)], key=_order_key)
        except Exception:
            bonuses_sorted = [b for b in bonuses if isinstance(b, dict)]

        for b in bonuses_sorted:
            if base + i >= lim:
                break
            bt = _safe_int(b.get("Type_Id") or b.get("TypeId"), 0)
            val = _safe_int(b.get("Value"), 0)
            if bt <= 0 or val == 0:
                i += 1
                continue
            idx = base + i
            item[f"BonusType{idx}"] = bt
            item[f"Var{idx}"] = val
            i += 1

    def apply_elixir_to_item(self, instance_guid: str, elixir_id: int) -> None:
        """
        Применить эликсир к предмету по InstanceGuid.
        Храним в локальном кэше + вшиваем в сам item (и как inline бонусы).
        """
        instance_guid = str(instance_guid or "").strip()
        if not instance_guid:
            return

        elixir_id = _safe_int(elixir_id, 0)
        if elixir_id <= 0:
            return

        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None:
            return

        try:
            from .equipment_elixir import get_elixir_meta, get_elixir_bonuses
        except Exception:
            return

        meta = get_elixir_meta(conn, elixir_id) or {}
        bonuses = get_elixir_bonuses(conn, elixir_id) or []

        payload = {
            "Id": elixir_id,
            "Name": str(meta.get("Name") or ""),
            "Image_Id": meta.get("Image_Id"),
            "Bonuses": list(bonuses),
        }

        cache = getattr(self, "_applied_elixirs", None)
        if not isinstance(cache, dict):
            cache = {}
            self._applied_elixirs = cache
        cache[instance_guid] = {
            "id": elixir_id,
            "name": payload.get("Name") or "",
            "image_id": payload.get("Image_Id"),
            "bonuses": list(payload.get("Bonuses") or []),
        }

        sel = getattr(self, "_selected_items", None)
        if isinstance(sel, dict):
            for k, it in list(sel.items()):
                if not isinstance(it, dict):
                    continue
                if str(it.get("InstanceGuid") or "").strip() == instance_guid:
                    self._embed_elixir_into_item(it, payload)
                    sel[k] = dict(it)
                    try:
                        self._update_slot_icon(str(k))
                    except Exception:
                        pass
                    break

        try:
            self.refresh_stats_panel()
        except Exception:
            pass

    def _clear_elixir_for_instance(self, instance_guid: str) -> None:
        instance_guid = str(instance_guid or "").strip()
        if not instance_guid:
            return

        cache = getattr(self, "_applied_elixirs", None)
        if isinstance(cache, dict):
            cache.pop(instance_guid, None)

        sel = getattr(self, "_selected_items", None)
        if isinstance(sel, dict):
            for k, it in list(sel.items()):
                if not isinstance(it, dict):
                    continue
                if str(it.get("InstanceGuid") or "").strip() == instance_guid:
                    self._embed_elixir_into_item(it, None)
                    sel[k] = dict(it)
                    try:
                        self._update_slot_icon(str(k))
                    except Exception:
                        pass
                    break

        try:
            self.refresh_stats_panel()
        except Exception:
            pass

    # ---------- щит на время окна печатей ----------
    def _ensure_stamp_shield(self) -> None:
        """Создать и показать щит поверх MainWindow."""
        try:
            self._ensure_main_modal_input_blocker()
        except Exception:
            pass

        try:
            self._drag_pos = None
        except Exception:
            pass

        try:
            self._block_main_input = True
        except Exception:
            pass

        # ВАЖНО:
        # При открытом StampWindow MainWindow не должен реагировать даже на hover.
        # Клики уже режутся глобальным фильтром, но hover_glow/tooltip живут от таймера
        # и от Enter/Move-событий, поэтому их нужно принудительно погасить.
        try:
            ht = getattr(self, "_hover_timer", None)
            if ht is not None and ht.isActive():
                ht.stop()
        except Exception:
            pass

        for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
            try:
                w = getattr(self, nm, None)
                if w is not None:
                    w.hide()
            except Exception:
                pass

        try:
            if getattr(self, "_glow_locked_key", None) is not None:
                self._unlock_glow()
        except Exception:
            pass

        try:
            if hasattr(self, "equip_info") and self.equip_info is not None:
                try:
                    self.equip_info.end_hover(self)
                except Exception:
                    self.equip_info.hide()
        except Exception:
            pass

        if getattr(self, "_stamp_shield", None) is None:
            self._stamp_shield = _InputShield(self)

        try:
            self._stamp_shield.setGeometry(self.rect())
            self._stamp_shield.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            self._stamp_shield.show()
            self._stamp_shield.raise_()
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self._stamp_shield.raise_)
            QTimer.singleShot(30, self._stamp_shield.raise_)
        except Exception:
            pass

    def _remove_stamp_shield(self) -> None:
        sh = getattr(self, "_stamp_shield", None)

        if sh is not None:
            try:
                sh.hide()
            except Exception:
                pass

            try:
                sh.deleteLater()
            except Exception:
                pass

            self._stamp_shield = None

        try:
            still_blocked = bool(
                self._reforge_shield_active()
                or (
                        getattr(self, "_inv_shield", None) is not None
                        and getattr(self, "_inv_shield").isVisible()
                )
            )
        except Exception:
            still_blocked = False

        try:
            self._block_main_input = bool(still_blocked)
        except Exception:
            pass

        if not still_blocked:
            try:
                self._block_allow_root = None
            except Exception:
                pass

            # Возвращаем hover только когда действительно больше нет активного щита.
            try:
                ht = getattr(self, "_hover_timer", None)
                if ht is not None and not ht.isActive():
                    ht.start()
            except Exception:
                pass

            try:
                QTimer.singleShot(50, self._refresh_hover_after_modal)
            except Exception:
                try:
                    QTimer.singleShot(50, self._update_glow_from_global)
                except Exception:
                    pass
        else:
            for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
                try:
                    w = getattr(self, nm, None)
                    if w is not None:
                        w.hide()
                except Exception:
                    pass

    def _stamp_shield_active(self) -> bool:
        return bool(getattr(self, "_stamp_shield", None) and self._stamp_shield.isVisible())

    # ---------- меню печатей ----------
    def _on_menu_stamp_clicked(self) -> None:
        self._ensure_stamp_shield()
        try:
            self._block_allow_root = self.stamp_window
        except Exception:
            pass
        self.stamp_window.open_centered(self)
        self.stamp_window.closed.disconnect(self._remove_stamp_shield)
        self.stamp_window.closed.connect(self._remove_stamp_shield)

    def _on_stamp_closed(self) -> None:
        self._input_blocked = False
        if hasattr(self, "_hover_timer"):
            self._hover_timer.start()

    def _open_stamp_menu(self) -> None:
        self._ensure_stamp_shield()
        self.menu_glow.hide()
        self.hover_glow.hide()
        self.winbtn_hover.hide()
        if hasattr(self, "equip_info"):
            try:
                self.equip_info.end_hover(self)  # <-- ВАЖНО: стоп таймера + очистка payload
            except Exception:
                self.equip_info.hide()

        if not hasattr(self, "stamp_window") or self.stamp_window is None:
            self.stamp_window = StampWindow(self)

        try:
            self._block_allow_root = self.stamp_window
        except Exception:
            pass

        self.stamp_window.closed.disconnect(self._remove_stamp_shield)
        self.stamp_window.closed.connect(self._remove_stamp_shield)
        self.stamp_window.open_centered(self)



    # ---------- приведение экипа к классовым правилам ----------
    def _coerce_equipment_to_class(self) -> None:
        lineage = self._compatible_class_ids_for_current()
        if not lineage:
            return

        for slot_key, item in list((self._selected_items or {}).items()):
            if not item:
                continue
            item_id = _safe_int(item.get("Id"), 0)
            if not item_id:
                continue

            allowed_ids = self._allowed_ids_for_slot_and_lineage(slot_key, lineage)
            # если allowed_ids пустой — не трогаем (значит не смогли вычислить)
            if allowed_ids and item_id not in allowed_ids:
                self._on_clear_equipment(slot_key)

    def _slot_id_from_ui(self, slot_key: str) -> int | None:
        return self._slot_db_id(slot_key)

    def _load_slots_cache(self):
        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None:
            self._slot_by_name = {}
            self._weapon_slot_with_extra = None
            return

        rows = conn.execute(
            'SELECT Id, Name, IsWeapon, ExtraSlot_Id, Count FROM EquipmentSlot'
        ).fetchall()

        self._slot_by_name = {(r[1] or "").strip().casefold(): {
            "Id": r[0], "Name": r[1], "IsWeapon": r[2], "ExtraSlot_Id": r[3], "Count": r[4]
        } for r in rows}

        self._weapon_slot_with_extra = None
        for s in self._slot_by_name.values():
            if s.get("IsWeapon") and s.get("ExtraSlot_Id"):
                self._weapon_slot_with_extra = s
                break

    # ---------- glow lock/unlock ----------
    def _lock_glow_on_slot(self, key: str, rect: QRect) -> None:
        self._glow_locked_key = key
        self._glow_locked_rect = QRect(rect)
        if self._glow_pm:
            glow_rect = self._glow_rect_for(key, rect)
            self.hover_glow.setGeometry(glow_rect)
            self.hover_glow.setPixmap(self._glow_pm)
            self.hover_glow.show()
            self.hover_glow.raise_()

    def _unlock_glow(self) -> None:
        self._glow_locked_key = None
        self._glow_locked_rect = None
        if getattr(self, "hover_glow", None) is not None:
            self.hover_glow.hide()

    def _clear_level_focus_if_outside(self, global_pos: QPoint) -> None:
        if not self.level_spin:
            return
        lp = self.level_spin.mapFromGlobal(global_pos)
        if not self.level_spin.rect().contains(lp):
            self.level_spin.clearFocus()

    # ---------- offhand overlay ----------
    def _is_offhand_disabled(self) -> bool:
        weapon = (getattr(self, "_selected_items", None) or {}).get("weapon")
        disabled = bool(self._weapon_is_two_handed(weapon))
        self._two_handed_equipped = disabled
        return disabled

    def _update_offhand_overlay(self, *, refresh_icon: bool = True) -> None:
        r = self._zone_rect("offhand")
        if not r or r.isEmpty():
            self._offhand_overlay.hide()
            self._offhand_ghost.hide()
            return
        if refresh_icon:
            self._update_slot_icon("offhand")
        disabled = bool(self._is_offhand_disabled())
        if not disabled:
            self._offhand_overlay.hide()
            self._offhand_ghost.hide()
            return
        off_lbl = (self._slot_icons or {}).get("offhand")
        if off_lbl:
            off_lbl.hide()
        weapon = (getattr(self, "_selected_items", None) or {}).get("weapon") or None
        if not isinstance(weapon, dict):
            weapon = None
        ghost_pm = None
        if weapon:
            img_id = weapon.get("Image_Id") or weapon.get("Icon_Image_Id")
            base_pm = self._get_image_pm(img_id)
            if base_pm and (not base_pm.isNull()):
                tw = int(r.width() * SLOT_ICON_SCALE)
                th = int(r.height() * SLOT_ICON_SCALE)
                target = QRect(0, 0, max(1, tw), max(1, th))
                target.moveCenter(r.center())
                icon_size = target.size()
                scaled_base = base_pm.scaled(icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                canvas = QPixmap(icon_size)
                canvas.fill(Qt.transparent)
                p = QPainter(canvas)
                p.setRenderHint(QPainter.Antialiasing, True)
                p.drawPixmap(0, 0, scaled_base)
                if self._should_draw_element_badge("offhand", weapon):
                    self._paint_element_badge(p, icon_size, weapon, slot_key="weapon")
                p.end()
                ghost_pm = self._disabled_pixmap(canvas, overlay_alpha=0, desaturate=True)
                self._offhand_ghost.setGeometry(target)
        if ghost_pm and not ghost_pm.isNull():
            self._offhand_ghost_fx.setOpacity(0.85)
            self._offhand_ghost.setPixmap(ghost_pm)
            self._offhand_ghost.show()
            self._offhand_ghost.raise_()
        else:
            self._offhand_ghost.hide()
        pad = max(2, int(r.width() * 0.05))
        self._offhand_overlay.setGeometry(r.adjusted(pad, pad, -pad, -pad))
        self._offhand_overlay.show()
        self._offhand_overlay.raise_()
        if self._offhand_ghost.isVisible() and self._offhand_overlay.isVisible():
            self._offhand_ghost.stackUnder(self._offhand_overlay)

    def _on_level_changed(self, _v: int) -> None:
        # при программном откате уровня (если инвентарь переполнен) — не запускаем логику повторно
        if bool(getattr(self, "_suppress_level_changed", False)):
            return

        prev_level = _safe_int(getattr(self, "_last_level_value", _v), _safe_int(_v, 1))

        ok = self._drop_invalid_equipment_for_level(prev_level=prev_level)

        # держим кэш актуального уровня
        self._last_level_value = _safe_int(self.level_spin.value(), 1)

        if not ok:
            return

        for key in SLOT_POS:
            self._update_slot_icon(key)
        self._update_offhand_overlay()
        self._sync_buff_debuff_menu_context()
        if getattr(self, "param_points", None):
            self.param_points.set_level(int(self.level_spin.value()))
        self.refresh_stats_panel()

    def _drop_invalid_equipment_for_level(self, prev_level: Optional[int] = None) -> bool:
        current_level = _safe_int(self.level_spin.value(), 1)

        to_drop: List[str] = []
        for slot_key, item in list((self._selected_items or {}).items()):
            if not item or not isinstance(item, dict):
                continue
            if _safe_int(item.get("Level"), 0) > current_level:
                to_drop.append(str(slot_key))

        if not to_drop:
            return True

        if prev_level is None:
            prev_level = current_level

        # переносим в инвентарь (вместо удаления)
        for key in to_drop:
            ok = False
            try:
                ok = bool(self._move_slot_item_to_inventory(key))
            except Exception:
                ok = False

            if not ok:
                # если инвентарь не принял предмет — откатываем уровень назад
                try:
                    self._suppress_level_changed = True
                    self.level_spin.setValue(int(prev_level))
                finally:
                    self._suppress_level_changed = False
                return False

        if "weapon" in to_drop:
            self._two_handed_equipped = False

        self._update_offhand_overlay()
        return True

    def _drop_invalid_equipment_for_gender(self) -> None:
        current_gender = 1 if self._gender == 1 else 2

        conn = getattr(getattr(self, "data", None), "conn", None)

        def _gender_id_from_db(equip_id: int) -> Optional[int]:
            if conn is None or int(equip_id or 0) <= 0:
                return None

            col = None
            try:
                rows = conn.execute('PRAGMA table_info("Equipment")').fetchall()
                low_to_real = {}
                for r in rows or []:
                    try:
                        nm = r["name"] if hasattr(r, "keys") else r[1]
                    except Exception:
                        nm = None
                    if nm:
                        low_to_real[str(nm).lower()] = str(nm)

                for cand in ("Gender_Id", "Gender_ID", "GenderId", "gender_id"):
                    if cand.lower() in low_to_real:
                        col = low_to_real[cand.lower()]
                        break
            except Exception:
                col = None

            if not col:
                return None

            try:
                row = conn.execute(
                    f'SELECT "{col}" FROM "Equipment" WHERE Id=? LIMIT 1',
                    (int(equip_id),),
                ).fetchone()
            except Exception:
                row = None

            if not row:
                return None

            try:
                raw = row[col] if hasattr(row, "keys") else row[0]
            except Exception:
                raw = None

            if raw in (None, ""):
                return None

            try:
                return int(raw)
            except Exception:
                return None

        def _item_allowed(item: dict) -> bool:
            if not isinstance(item, dict):
                return True

            gender_id = None
            for k in ("Gender_Id", "Gender_ID", "GenderId", "gender_id"):
                if item.get(k) not in (None, ""):
                    gender_id = _safe_int(item.get(k), 0)
                    break

            if gender_id is None:
                eid = _safe_int(
                    item.get("Id")
                    or item.get("Equip_Id")
                    or item.get("Equipment_Id")
                    or item.get("EquipmentId"),
                    0,
                )
                if eid > 0:
                    gender_id = _gender_id_from_db(eid)

            # 0 / NULL = универсальный предмет.
            if gender_id is None or int(gender_id) <= 0:
                return True

            return int(gender_id) == int(current_gender)

        to_drop: List[str] = []

        for slot_key, item in list((self._selected_items or {}).items()):
            if not isinstance(item, dict) or not item:
                continue

            if not _item_allowed(item):
                to_drop.append(str(slot_key))

        if to_drop:
            try:
                self._bulk_clear_equipment_slots(to_drop)
            except Exception:
                for key in to_drop:
                    try:
                        self._on_clear_equipment(key)
                    except Exception:
                        pass

    def _apply_level_rules_for_current_class(self) -> None:
        if self._is_advanced_class():
            self.level_spin.setRange(20, self._max_level_cap)
            if self.level_spin.value() < 20:
                self.level_spin.setValue(20)
            return
        if self._is_base_class():
            self.level_spin.setRange(1, 20)
            if self.level_spin.value() > 20:
                self.level_spin.setValue(20)
            return
        self.level_spin.setRange(1, self._max_level_cap)
        if self.level_spin.value() < 1:
            self.level_spin.setValue(1)

    def _drop_invalid_equipment_for_new_class(self) -> None:
        lineage = self._compatible_class_ids_for_current()
        if not lineage:
            return
        selected = getattr(self, "_selected_items", None) or {}
        to_drop: list[str] = []
        cur_class_id = _safe_int(self._current_class_id(), 0)
        for slot_key, it in list(selected.items()):
            if not it or not isinstance(it, dict):
                continue
            eid = _safe_int(it.get("Id") or it.get("Equip_Id"), 0)
            if not eid:
                continue
            tid = _safe_int(it.get("Type_Id") or it.get("TypeId"), 0)
            if tid and not self._class_allows_equipment_type(tid, class_id=cur_class_id):
                to_drop.append(str(slot_key))
                continue
            slot_ids = self.resolve_slot_ids_for_ui_key(str(slot_key), class_id=cur_class_id) or []
            if not slot_ids:
                sid_fallback = self._slot_id_from_item_type_id(tid)
                if sid_fallback:
                    slot_ids = [sid_fallback]
            allowed_ids: set[int] = set()
            for sid in slot_ids:
                for cid in lineage:
                    allowed_ids |= self._allowed_equipment_ids_for(int(sid), int(cid))
            if allowed_ids and eid not in allowed_ids:
                to_drop.append(str(slot_key))
        if to_drop:
            self._bulk_clear_equipment_slots(to_drop)
        self._request_inventory_prune_for_current_class()

    # ---------- слот-иконки ----------
    def on_element_card_applied(self, slot_key: str, card_row: dict | None) -> None:
        item = self._selected_items.get(slot_key)
        if not item:
            return
        elem_id = _safe_int(card_row.get("Element_Id"), 0) if card_row else 0
        if elem_id > 0:
            item["Element_Id"] = int(elem_id)
        else:
            item.pop("Element_Id", None)
        self._update_slot_icon(slot_key)
        if slot_key == "weapon":
            self._update_offhand_overlay()


    def _pad_for_icon_button(self, btn: QToolButton, icon_px: int, border_w: int) -> int:
        return max(0, (btn.width() - icon_px) // 2 - border_w)

    def _place_close_btn(self) -> None:
        r = self._zone_rect("close")
        if not r:
            return
        self.close_btn.setFixedSize(r.size())
        self.close_btn.setIconSize(r.size())
        self.close_btn.move(r.topLeft())
        self.close_btn.raise_()

    def _place_minimize_btn(self) -> None:
        r = self._zone_rect("minimize")
        if not r:
            return
        self.minimize_btn.setFixedSize(r.size())
        self.minimize_btn.setIconSize(r.size())
        self.minimize_btn.move(r.topLeft())
        self.minimize_btn.raise_()

    def _place_menu_buttons(self) -> None:
        pm = self.board_label.pixmap()
        if not pm:
            return

        from PySide6.QtCore import Qt

        def _uconnect(sig, slot):
            try:
                sig.connect(slot, Qt.ConnectionType.UniqueConnection)
            except Exception:
                try:
                    sig.connect(slot)
                except Exception:
                    pass

        sx = pm.width() / float(self._base_w)
        ir = self._img_rect()

        for b in MENU_BUTTONS:
            key = b["key"]
            btn = self.menu_btns.get(key)
            if not btn:
                continue

            if key == "inventory":
                _uconnect(btn.clicked, self._on_menu_bag_clicked)
            elif key == "guild":
                _uconnect(btn.clicked, self._on_menu_guild_clicked)
            elif key == "elixir":
                _uconnect(btn.clicked, self._on_menu_elixir_clicked)
            elif key == "consumble":
                _uconnect(btn.clicked, self._on_menu_consumble_clicked)
            elif key == "aura":
                _uconnect(btn.clicked, self._on_menu_aura_clicked)
            elif key == "collect":
                _uconnect(btn.clicked, self._on_menu_collect_clicked)
            elif key == "stamp":
                _uconnect(btn.clicked, self._on_menu_stamp_clicked)
            elif key == "reforge":
                _uconnect(btn.clicked, self._on_menu_reforge_clicked)
            elif key == "talents":
                _uconnect(btn.clicked, self._on_menu_talents_clicked)
            elif key == "buffs":
                _uconnect(btn.clicked, self._on_menu_buffs_clicked)


            x0, y0, w0, h0 = b["rect"]
            X = int(ir.x() + x0 * sx)
            Y = int(ir.y() + y0 * sx)
            W = int(w0 * sx)
            H = int(h0 * sx)
            btn.setGeometry(X, Y, W, H)
            btn.show()

        self._sync_player_elixir_button_icon()
        self._place_menu_bonus_toggles()

    def _load_player_elixir_payload_from_db(self, elixir_id: int) -> Optional[dict]:
        """
        Эликсир персонажа (не оружия).
        Таблицы:
          Elixir
          ElixirBonus
        """
        elixir_id = _safe_int(elixir_id, 0)
        if elixir_id <= 0:
            return None

        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None:
            return None

        try:
            row = conn.execute(
                """
                SELECT Id, Name, Image_Id
                FROM Elixir
                WHERE Id=? AND COALESCE(IsLegacy, 0)=0
                LIMIT 1
                """,
                (int(elixir_id),),
            ).fetchone()
        except Exception:
            row = None

        if not row:
            return None

        try:
            if hasattr(row, "keys"):
                eid = _safe_int(row["Id"], 0)
                name = str(row["Name"] or "")
                image_id = row["Image_Id"]
            else:
                eid = _safe_int(row[0], 0)
                name = str(row[1] or "")
                image_id = row[2]
        except Exception:
            return None

        if eid <= 0:
            return None

        try:
            bonus_rows = conn.execute(
                """
                SELECT Type_Id, Value, OrderIndex
                FROM ElixirBonus
                WHERE Elixir_Id=?
                ORDER BY OrderIndex, rowid
                """,
                (int(eid),),
            ).fetchall()
        except Exception:
            bonus_rows = []

        bonuses: List[dict] = []
        for r in bonus_rows or []:
            try:
                if hasattr(r, "keys"):
                    bt = _safe_int(r["Type_Id"], 0)
                    val = _safe_int(r["Value"], 0)
                    order_idx = _safe_int(r["OrderIndex"], 0)
                else:
                    bt = _safe_int(r[0], 0)
                    val = _safe_int(r[1], 0)
                    order_idx = _safe_int(r[2], 0)
            except Exception:
                continue

            if bt <= 0:
                continue

            bonuses.append(
                {
                    "Type_Id": int(bt),
                    "Value": int(val),
                    "OrderIndex": int(order_idx),
                }
            )

        return {
            "Id": int(eid),
            "Name": str(name),
            "Image_Id": image_id,
            "Bonuses": list(bonuses),
        }

    def _current_player_elixir_id(self) -> int:
        payload = getattr(self, "_player_elixir_payload", None)
        if isinstance(payload, dict):
            eid = _safe_int(payload.get("Id") or payload.get("id"), 0)
            if eid > 0:
                return int(eid)

        try:
            app = QApplication.instance()
            if app is not None:
                raw = app.property("player_elixir_payload")
                if isinstance(raw, dict):
                    eid = _safe_int(raw.get("Id") or raw.get("id"), 0)
                    if eid > 0:
                        return int(eid)
        except Exception:
            pass

        return 0

    def _current_player_elixir_payload(self) -> Optional[dict]:
        payload = getattr(self, "_player_elixir_payload", None)
        if isinstance(payload, dict):
            return dict(payload)

        try:
            app = QApplication.instance()
            if app is not None:
                raw = app.property("player_elixir_payload")
                if isinstance(raw, dict):
                    return dict(raw)
        except Exception:
            pass

        return None

    def _ensure_buff_debuff_menu_window(self) -> BuffDebuffMenuWindow:
        w = getattr(self, "_buff_debuff_menu_window", None)
        if isinstance(w, BuffDebuffMenuWindow):
            try:
                w.set_class_id(_safe_int(self._current_class_id(), 0))
            except Exception:
                pass
            try:
                w.set_level(_safe_int(self.level_spin.value(), 0))
            except Exception:
                pass
            return w

        w = BuffDebuffMenuWindow(self)
        self._buff_debuff_menu_window = w

        try:
            w.set_class_id(_safe_int(self._current_class_id(), 0))
        except Exception:
            pass
        try:
            w.set_level(_safe_int(self.level_spin.value(), 0))
        except Exception:
            pass

        try:
            w.closed.connect(self._on_buff_debuff_menu_closed, Qt.ConnectionType.UniqueConnection)
        except Exception:
            try:
                w.closed.connect(self._on_buff_debuff_menu_closed)
            except Exception:
                pass

        return w

    def _sync_buff_debuff_menu_context(self) -> None:
        w = getattr(self, "_buff_debuff_menu_window", None)
        if not isinstance(w, BuffDebuffMenuWindow):
            return

        try:
            w.set_class_id(_safe_int(self._current_class_id(), 0))
        except Exception:
            pass

        try:
            w.set_level(_safe_int(self.level_spin.value(), 0))
        except Exception:
            pass

        # ВАЖНО:
        # при смене карт/печатей/талантов надо не просто прокинуть class/level,
        # а заставить меню бафов выкинуть бафы, источник которых больше не активен.
        try:
            fn = getattr(w, "refresh_runtime_context", None)
            if callable(fn):
                fn()
        except Exception:
            pass

    def _ensure_talents_menu_window(self) -> TalentsMenu:
        w = getattr(self, "_talents_menu_window", None)
        if isinstance(w, TalentsMenu):
            try:
                w.set_class_id(_safe_int(self._current_class_id(), 0))
            except Exception:
                pass
            return w

        w = TalentsMenu(self)
        self._talents_menu_window = w

        try:
            w.set_class_id(_safe_int(self._current_class_id(), 0))
        except Exception:
            pass

        try:
            w.closed.connect(self._on_talents_menu_closed, Qt.ConnectionType.UniqueConnection)
        except Exception:
            try:
                w.closed.connect(self._on_talents_menu_closed)
            except Exception:
                pass

        return w



    def _sync_talents_menu_class_context(self) -> None:
        w = getattr(self, "_talents_menu_window", None)
        if not isinstance(w, TalentsMenu):
            return

        try:
            cid = _safe_int(self._current_class_id(), 0)
        except Exception:
            cid = 0

        try:
            w.set_class_id(cid)
        except Exception:
            pass

    def _on_menu_talents_clicked(self) -> None:
        w = self._ensure_talents_menu_window()

        try:
            w.set_class_id(_safe_int(self._current_class_id(), 0))
        except Exception:
            pass

        # toggle
        try:
            if w.isVisible():
                w.close()
                return
        except Exception:
            pass

        # блокируем ввод в MainWindow
        try:
            self._block_main_input = True
            self._block_allow_root = w
        except Exception:
            pass

        # прибираем подсветки/tooltip и останавливаем hover
        try:
            if hasattr(self, "_hover_timer") and self._hover_timer is not None and self._hover_timer.isActive():
                self._hover_timer.stop()
        except Exception:
            pass

        for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
            try:
                ww = getattr(self, nm, None)
                if ww is not None:
                    ww.hide()
            except Exception:
                pass

        try:
            if getattr(self, "equip_info", None) is not None:
                try:
                    self.equip_info.end_hover(self)
                except Exception:
                    self.equip_info.hide()
        except Exception:
            pass

        try:
            if getattr(self, "_glow_locked_key", None) is not None:
                self._unlock_glow()
        except Exception:
            pass

        w.open_centered(self)

    def _on_talents_menu_closed(self) -> None:
        # снять блокировку
        try:
            self._block_main_input = False
        except Exception:
            pass
        try:
            self._block_allow_root = None
        except Exception:
            pass

        # вернуть фокус/активность
        try:
            self.raise_()
            self.activateWindow()
            QApplication.setActiveWindow(self)
        except Exception:
            pass

        # hover обратно — но только если сейчас нет других модалок/щитов
        try:
            any_modal = bool(self._stamp_shield_active() or self._reforge_shield_active())
        except Exception:
            any_modal = False

        try:
            if (not any_modal) and hasattr(self, "_hover_timer") and self._hover_timer is not None:
                if not self._hover_timer.isActive():
                    self._hover_timer.start()
        except Exception:
            pass

        try:
            QTimer.singleShot(50, self._refresh_hover_after_modal)
            QTimer.singleShot(60, self._poke_hover_synthetic)
        except Exception:
            pass

        try:
            self._update_glow_from_global()
        except Exception:
            pass

    def _on_menu_aura_clicked(self) -> None:
        w = getattr(self, "_aura_menu_window", None)
        if w is None:
            self._aura_menu_window = AuraMenuWindow(self)
            w = self._aura_menu_window
            try:
                w.closed.connect(self._on_aura_menu_closed)
            except Exception:
                pass

        # toggle
        try:
            if w.isVisible():
                w.close()
                return
        except Exception:
            pass

        # блокируем ввод в MainWindow
        try:
            self._block_main_input = True
            self._block_allow_root = w
        except Exception:
            pass

        # прячем подсветки/tooltip и стопаем hover
        try:
            if hasattr(self, "_hover_timer") and self._hover_timer is not None and self._hover_timer.isActive():
                self._hover_timer.stop()
        except Exception:
            pass

        for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
            try:
                ww = getattr(self, nm, None)
                if ww is not None:
                    ww.hide()
            except Exception:
                pass

        try:
            if getattr(self, "equip_info", None) is not None:
                try:
                    self.equip_info.end_hover(self)
                except Exception:
                    self.equip_info.hide()
        except Exception:
            pass

        try:
            if getattr(self, "_glow_locked_key", None) is not None:
                self._unlock_glow()
        except Exception:
            pass

        w.open_centered(self)

    def _on_aura_menu_closed(self) -> None:
        try:
            self._block_main_input = False
        except Exception:
            pass

        try:
            self._block_allow_root = None
        except Exception:
            pass

        try:
            self.raise_()
            self.activateWindow()
            QApplication.setActiveWindow(self)
        except Exception:
            pass

        try:
            any_modal = bool(self._stamp_shield_active() or self._reforge_shield_active())
        except Exception:
            any_modal = False

        try:
            ht = getattr(self, "_hover_timer", None)
            if (not any_modal) and ht is not None and (not ht.isActive()):
                ht.start()
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self._update_glow_from_global)
            QTimer.singleShot(0, self._poke_hover_synthetic)
        except Exception:
            pass

    def _on_menu_buffs_clicked(self) -> None:
        w = self._ensure_buff_debuff_menu_window()

        try:
            w.set_class_id(_safe_int(self._current_class_id(), 0))
        except Exception:
            pass

        try:
            w.set_level(_safe_int(self.level_spin.value(), 0))
        except Exception:
            pass

        try:
            fn = getattr(w, "refresh_runtime_context", None)
            if callable(fn):
                fn()
        except Exception:
            pass

        # toggle
        try:
            if w.isVisible():
                w.close()
                return
        except Exception:
            pass

        # ВАЖНО:
        # Для меню бафов/дебафов НЕ включаем _block_main_input.
        # Иначе eventFilter MainWindow съедает MouseButtonPress/Release
        # у трёх маленьких кнопок быстрого просмотра активных эффектов.
        try:
            self._block_main_input = False
            self._block_allow_root = None
        except Exception:
            pass

        # Прячем подсветки/tooltip и стопаем hover,
        # но не блокируем клики по кнопкам быстрого списка.
        try:
            if hasattr(self, "_hover_timer") and self._hover_timer is not None and self._hover_timer.isActive():
                self._hover_timer.stop()
        except Exception:
            pass

        for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
            try:
                ww = getattr(self, nm, None)
                if ww is not None:
                    ww.hide()
            except Exception:
                pass

        try:
            if getattr(self, "equip_info", None) is not None:
                try:
                    self.equip_info.end_hover(self)
                except Exception:
                    self.equip_info.hide()
        except Exception:
            pass

        try:
            if getattr(self, "_glow_locked_key", None) is not None:
                self._unlock_glow()
        except Exception:
            pass

        w.open_centered(self)

        # Поднимаем 3 кнопки быстрого списка поверх слоёв MainWindow.
        try:
            self._place_active_buff_preview_buttons()
        except Exception:
            pass

        def _raise_preview_buttons_again() -> None:
            try:
                self._place_active_buff_preview_buttons()
            except Exception:
                pass

            try:
                for btn in (getattr(self, "_active_buff_preview_btns", {}) or {}).values():
                    if btn is not None:
                        btn.show()
                        btn.raise_()
            except Exception:
                pass

            try:
                panel = getattr(self, "_active_buff_preview_panel", None)
                if isinstance(panel, _ActiveBuffPreviewPanel) and panel.isVisible():
                    self._position_active_buff_preview_panel()
                    panel.raise_()
            except Exception:
                pass

        QTimer.singleShot(0, _raise_preview_buttons_again)
        QTimer.singleShot(30, _raise_preview_buttons_again)

    def _on_buff_debuff_menu_closed(self) -> None:
        try:
            self._block_main_input = False
        except Exception:
            pass

        try:
            self._block_allow_root = None
        except Exception:
            pass

        try:
            self.raise_()
            self.activateWindow()
            QApplication.setActiveWindow(self)
        except Exception:
            pass

        try:
            any_modal = bool(self._stamp_shield_active() or self._reforge_shield_active())
        except Exception:
            any_modal = False

        try:
            ht = getattr(self, "_hover_timer", None)
            if (not any_modal) and ht is not None and (not ht.isActive()):
                ht.start()
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self._update_glow_from_global)
            QTimer.singleShot(0, self._poke_hover_synthetic)
        except Exception:
            pass

    def _ensure_player_elixir_icon_label(self) -> Optional[QLabel]:
        btn = (getattr(self, "menu_btns", {}) or {}).get("elixir")
        if btn is None:
            return None

        lbl = getattr(self, "_player_elixir_icon_lbl", None)
        if isinstance(lbl, QLabel) and lbl.parent() is btn:
            return lbl

        lbl = QLabel(btn)
        lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lbl.setAttribute(Qt.WA_TranslucentBackground, True)
        lbl.setAutoFillBackground(False)
        lbl.setStyleSheet("background: transparent; border: none;")
        lbl.setScaledContents(True)
        lbl.hide()

        self._player_elixir_icon_lbl = lbl
        return lbl

    def _sync_player_elixir_button_icon(self) -> None:
        """
        Рисует иконку выбранного эликсира на кнопке нижнего меню 'elixir'
        отдельным QLabel, чтобы можно было точно задавать размер и смещение.
        """
        btn = (getattr(self, "menu_btns", {}) or {}).get("elixir")
        if btn is None:
            return

        payload = self._current_player_elixir_payload()
        if not isinstance(payload, dict):
            try:
                btn.setIcon(QIcon())
            except Exception:
                pass
            lbl = getattr(self, "_player_elixir_icon_lbl", None)
            if isinstance(lbl, QLabel):
                lbl.hide()
            return

        image_id = _safe_int(payload.get("Image_Id"), 0)
        if image_id <= 0:
            try:
                btn.setIcon(QIcon())
            except Exception:
                pass
            lbl = getattr(self, "_player_elixir_icon_lbl", None)
            if isinstance(lbl, QLabel):
                lbl.hide()
            return

        pm = None
        try:
            pm = self._get_image_pm(image_id)
        except Exception:
            pm = None

        if pm is None or pm.isNull():
            try:
                btn.setIcon(QIcon())
            except Exception:
                pass
            lbl = getattr(self, "_player_elixir_icon_lbl", None)
            if isinstance(lbl, QLabel):
                lbl.hide()
            return

        try:
            btn.setIcon(QIcon())
        except Exception:
            pass

        lbl = getattr(self, "_player_elixir_icon_lbl", None)
        if not isinstance(lbl, QLabel) or lbl.parent() is not btn:
            lbl = QLabel(btn)
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            lbl.setStyleSheet("background: transparent; border: none;")
            lbl.setScaledContents(True)
            self._player_elixir_icon_lbl = lbl

        sx = 1.0
        try:
            sx = float(self._scale())
        except Exception:
            sx = 1.0

        icon_px = max(1, int(round(38 * sx)))
        scaled = pm.scaled(icon_px, icon_px, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

        # вот ЭТИМИ числами двигаешь иконку
        x_off = 1  # вправо = положительное, влево = отрицательное
        y_off = 2  # вниз = положительное, вверх = отрицательное

        x = (btn.width() - icon_px) // 2 + x_off
        y = (btn.height() - icon_px) // 2 + y_off

        lbl.setGeometry(int(x), int(y), int(icon_px), int(icon_px))
        lbl.setPixmap(scaled)
        lbl.show()
        lbl.raise_()

        try:
            tog = (getattr(self, "_menu_bonus_toggles", {}) or {}).get("elixir")
            if tog is not None:
                tog.raise_()
        except Exception:
            pass

    def _set_player_elixir(self, elixir_id: int) -> None:
        payload = self._load_player_elixir_payload_from_db(elixir_id)
        if not isinstance(payload, dict):
            return

        self._player_elixir_payload = dict(payload)

        try:
            app = QApplication.instance()
            if app is not None:
                app.setProperty("player_elixir_payload", dict(payload))
                app.setProperty("player_elixir_id", int(payload.get("Id") or 0))
        except Exception:
            pass

        try:
            self._sync_player_elixir_button_icon()
        except Exception:
            pass

        try:
            self.refresh_stats_panel()
        except Exception:
            pass

        try:
            self.update()
        except Exception:
            pass

    def _clear_player_elixir(self) -> None:
        self._player_elixir_payload = None

        try:
            app = QApplication.instance()
            if app is not None:
                app.setProperty("player_elixir_payload", None)
                app.setProperty("player_elixir_id", 0)
        except Exception:
            pass

        try:
            self._sync_player_elixir_button_icon()
        except Exception:
            pass

        try:
            self.refresh_stats_panel()
        except Exception:
            pass

        try:
            self.update()
        except Exception:
            pass

    def _ensure_elixir_menu(self) -> ChooseElixirMenu:
        menu = getattr(self, "_elixir_menu", None)
        if isinstance(menu, ChooseElixirMenu):
            return menu

        menu = ChooseElixirMenu(self, config=ElixirChooseConfig())
        self._elixir_menu = menu

        try:
            menu.closed.connect(self._on_elixir_menu_closed, Qt.ConnectionType.UniqueConnection)
        except Exception:
            try:
                menu.closed.connect(self._on_elixir_menu_closed)
            except Exception:
                pass

        return menu

    def _open_player_elixir_menu(self) -> None:
        anchor_btn = (getattr(self, "menu_btns", {}) or {}).get("elixir")
        if anchor_btn is None:
            return

        menu = self._ensure_elixir_menu()
        current_id = self._current_player_elixir_id()

        try:
            if hasattr(self, "_hover_timer") and self._hover_timer is not None and self._hover_timer.isActive():
                self._hover_timer.stop()
        except Exception:
            pass

        for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
            try:
                ww = getattr(self, nm, None)
                if ww is not None:
                    ww.hide()
            except Exception:
                pass

        try:
            if getattr(self, "equip_info", None) is not None:
                try:
                    self.equip_info.end_hover(self)
                except Exception:
                    self.equip_info.hide()
        except Exception:
            pass

        def _on_pick(elixir: dict, _bonus_lines: List[str]) -> None:
            picked_id = _safe_int((elixir or {}).get("Id"), 0)
            if picked_id <= 0:
                return

            cur_id = self._current_player_elixir_id()

            # повторный клик по тому же эликсиру = снять
            if int(cur_id) == int(picked_id):
                self._clear_player_elixir()
                try:
                    menu.set_selected_elixir_id(0)
                except Exception:
                    pass
            else:
                self._set_player_elixir(int(picked_id))
                try:
                    menu.set_selected_elixir_id(int(picked_id))
                except Exception:
                    pass

        menu.open_for(
            anchor_widget=anchor_btn,
            conn=getattr(getattr(self, "data", None), "conn", None),
            on_pick=_on_pick,
            on_hover_enter=None,
            on_hover_leave=None,
            initial_search="",
            selected_elixir_id=int(current_id),
            focus_search=True,
        )

    def _on_menu_elixir_clicked(self) -> None:
        menu = getattr(self, "_elixir_menu", None)
        if isinstance(menu, ChooseElixirMenu) and menu.isVisible():
            menu.hide()
            return

        self._open_player_elixir_menu()

    def _on_elixir_menu_closed(self) -> None:
        try:
            self.raise_()
            self.activateWindow()
            QApplication.setActiveWindow(self)
        except Exception:
            pass

        try:
            any_modal = bool(self._stamp_shield_active() or self._reforge_shield_active())
        except Exception:
            any_modal = False

        try:
            ht = getattr(self, "_hover_timer", None)
            if (not any_modal) and ht is not None and (not ht.isActive()):
                ht.start()
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self._update_glow_from_global)
            QTimer.singleShot(0, self._poke_hover_synthetic)
        except Exception:
            pass

    def _load_player_consumable_payload_from_db(self, consumable_id: int) -> Optional[dict]:
        """
        Расходник персонажа из таблиц:
          Consumable
          ConsumableBonus
        """
        consumable_id = _safe_int(consumable_id, 0)
        if consumable_id <= 0:
            return None

        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None:
            return None

        try:
            row = conn.execute(
                """
                SELECT Id, Name, Image_Id, Exeption
                FROM Consumable
                WHERE Id=?
                LIMIT 1
                """,
                (int(consumable_id),),
            ).fetchone()
        except Exception:
            row = None

        if not row:
            return None

        try:
            if hasattr(row, "keys"):
                cid = _safe_int(row["Id"], 0)
                name = str(row["Name"] or "")
                image_id = row["Image_Id"]
                ex_raw = row["Exeption"]
            else:
                cid = _safe_int(row[0], 0)
                name = str(row[1] or "")
                image_id = row[2]
                ex_raw = row[3]
        except Exception:
            return None

        if cid <= 0:
            return None

        ex = None
        try:
            if ex_raw is not None and str(ex_raw).strip() != "":
                ex = int(ex_raw)
        except Exception:
            ex = None

        try:
            bonus_rows = conn.execute(
                """
                SELECT Type_Id, Value, OrderIndex
                FROM ConsumableBonus
                WHERE Consumable_Id=?
                ORDER BY OrderIndex, rowid
                """,
                (int(cid),),
            ).fetchall()
        except Exception:
            bonus_rows = []

        bonuses: List[dict] = []
        for r in bonus_rows or []:
            try:
                if hasattr(r, "keys"):
                    bt = _safe_int(r["Type_Id"], 0)
                    val = _safe_int(r["Value"], 0)
                    order_idx = _safe_int(r["OrderIndex"], 0)
                else:
                    bt = _safe_int(r[0], 0)
                    val = _safe_int(r[1], 0)
                    order_idx = _safe_int(r[2], 0)
            except Exception:
                continue

            if bt <= 0:
                continue

            bonuses.append(
                {
                    "Type_Id": int(bt),
                    "Value": int(val),
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

    def _current_player_consumable_ids(self) -> List[int]:
        out: List[int] = []

        payloads = getattr(self, "_player_consumables_payloads", None)
        if isinstance(payloads, list):
            for p in payloads:
                if not isinstance(p, dict):
                    continue
                cid = _safe_int(p.get("Id") or p.get("id"), 0)
                if cid > 0:
                    out.append(int(cid))

        if out:
            return out

        try:
            app = QApplication.instance()
            if app is not None:
                raw = app.property("player_consumable_ids")
                if isinstance(raw, (list, tuple, set)):
                    for x in raw:
                        v = _safe_int(x, 0)
                        if v > 0:
                            out.append(int(v))
        except Exception:
            pass

        # unique с сохранением порядка
        seen = set()
        res: List[int] = []
        for x in out:
            if x not in seen:
                seen.add(x)
                res.append(int(x))
        return res

    def _set_player_consumables(self, consumable_ids: Iterable[int]) -> None:
        """
        Сохраняет активные расходники персонажа.
        Конфликты по Exeption нормализуются по правилу:
          последний расходник из одной группы заменяет предыдущий.

        ВАЖНО:
          конфликтной группой считается любое числовое значение Exeption >= 0
          NULL = нет группы, не конфликтует.
        """
        ordered_ids: List[int] = []
        for x in list(consumable_ids or []):
            v = _safe_int(x, 0)
            if v > 0:
                ordered_ids.append(int(v))

        payloads: List[dict] = []
        group_to_index: Dict[int, int] = {}

        for cid in ordered_ids:
            payload = self._load_player_consumable_payload_from_db(int(cid))
            if not isinstance(payload, dict):
                continue

            grp = payload.get("Exeption", None)

            if grp is not None:
                try:
                    grp = int(grp)
                except Exception:
                    grp = None

            if grp is not None and int(grp) >= 0 and grp in group_to_index:
                prev_idx = group_to_index[int(grp)]
                if 0 <= prev_idx < len(payloads):
                    payloads[prev_idx] = dict(payload)
                    continue

            if grp is not None and int(grp) >= 0:
                group_to_index[int(grp)] = len(payloads)

            payloads.append(dict(payload))

        self._player_consumables_payloads = list(payloads)

        ids = [_safe_int(p.get("Id"), 0) for p in payloads if isinstance(p, dict)]
        ids = [int(x) for x in ids if x > 0]

        try:
            app = QApplication.instance()
            if app is not None:
                app.setProperty("player_consumables_payloads", list(payloads))
                app.setProperty("player_consumable_ids", list(ids))
        except Exception:
            pass

        try:
            self.refresh_stats_panel()
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self.refresh_stats_panel)
        except Exception:
            pass

        try:
            self.update()
        except Exception:
            pass

    def _clear_player_consumables(self) -> None:
        self._player_consumables_payloads = []

        try:
            app = QApplication.instance()
            if app is not None:
                app.setProperty("player_consumables_payloads", [])
                app.setProperty("player_consumable_ids", [])
        except Exception:
            pass

        try:
            self.refresh_stats_panel()
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self.refresh_stats_panel)
        except Exception:
            pass

        try:
            self.update()
        except Exception:
            pass

    def _ensure_consumble_menu(self) -> ChooseConsumbleMenu:
        menu = getattr(self, "_consumble_menu", None)
        if isinstance(menu, ChooseConsumbleMenu):
            return menu

        menu = ChooseConsumbleMenu(self, config=ConsumbleChooseConfig())
        self._consumble_menu = menu

        try:
            menu.closed.connect(self._on_consumble_menu_closed, Qt.ConnectionType.UniqueConnection)
        except Exception:
            try:
                menu.closed.connect(self._on_consumble_menu_closed)
            except Exception:
                pass

        return menu

    def _open_player_consumble_menu(self) -> None:
        anchor_btn = (getattr(self, "menu_btns", {}) or {}).get("consumble")
        if anchor_btn is None:
            return

        menu = self._ensure_consumble_menu()
        current_ids = self._current_player_consumable_ids()

        try:
            if hasattr(self, "_hover_timer") and self._hover_timer is not None and self._hover_timer.isActive():
                self._hover_timer.stop()
        except Exception:
            pass

        for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
            try:
                ww = getattr(self, nm, None)
                if ww is not None:
                    ww.hide()
            except Exception:
                pass

        try:
            if getattr(self, "equip_info", None) is not None:
                try:
                    self.equip_info.end_hover(self)
                except Exception:
                    self.equip_info.hide()
        except Exception:
            pass

        def _on_pick(_consumble: dict, _bonus_lines: List[str]) -> None:
            selected_ids = list(menu.selected_ids() or [])
            if selected_ids:
                self._set_player_consumables(selected_ids)
            else:
                self._clear_player_consumables()

        menu.open_for(
            anchor_widget=anchor_btn,
            conn=getattr(getattr(self, "data", None), "conn", None),
            on_pick=_on_pick,
            on_hover_enter=None,
            on_hover_leave=None,
            initial_search="",
            selected_ids=list(current_ids),
            focus_search=True,
        )

    def _on_menu_consumble_clicked(self) -> None:
        menu = getattr(self, "_consumble_menu", None)
        if isinstance(menu, ChooseConsumbleMenu) and menu.isVisible():
            menu.hide()
            return

        self._open_player_consumble_menu()

    def _on_consumble_menu_closed(self) -> None:
        try:
            self.raise_()
            self.activateWindow()
            QApplication.setActiveWindow(self)
        except Exception:
            pass

        try:
            any_modal = bool(self._stamp_shield_active() or self._reforge_shield_active())
        except Exception:
            any_modal = False

        try:
            ht = getattr(self, "_hover_timer", None)
            if (not any_modal) and ht is not None and (not ht.isActive()):
                ht.start()
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self._update_glow_from_global)
            QTimer.singleShot(0, self._poke_hover_synthetic)
        except Exception:
            pass

    def _on_menu_collect_clicked(self) -> None:
        w = getattr(self, "_collection_window", None)
        if w is None:
            self._collection_window = CollectionWindow(self)
            w = self._collection_window
            try:
                w.closed.connect(self._on_collection_closed)
            except Exception:
                pass

        # toggle
        try:
            if w.isVisible():
                w.close()
                return
        except Exception:
            pass

        # блокируем ввод в MainWindow (штатный механизм eventFilter)
        try:
            self._block_main_input = True
            self._block_allow_root = w
        except Exception:
            pass

        # прибираем подсветки/tooltip и останавливаем hover (как у модалок)
        try:
            if hasattr(self, "_hover_timer") and self._hover_timer is not None and self._hover_timer.isActive():
                self._hover_timer.stop()
        except Exception:
            pass

        for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
            try:
                ww = getattr(self, nm, None)
                if ww is not None:
                    ww.hide()
            except Exception:
                pass

        try:
            if getattr(self, "equip_info", None) is not None:
                try:
                    self.equip_info.end_hover(self)
                except Exception:
                    self.equip_info.hide()
        except Exception:
            pass

        try:
            if getattr(self, "_glow_locked_key", None) is not None:
                self._unlock_glow()
        except Exception:
            pass

        # открыть поверх
        w.open_centered(self)

    def _on_collection_closed(self) -> None:
        # снять блокировку
        try:
            self._block_main_input = False
        except Exception:
            pass
        try:
            self._block_allow_root = None
        except Exception:
            pass

        # вернуть фокус/активность
        try:
            self.raise_()
            self.activateWindow()
            QApplication.setActiveWindow(self)
        except Exception:
            pass

        # hover обратно — но только если сейчас нет других модалок/щитов
        try:
            any_modal = bool(self._stamp_shield_active() or self._reforge_shield_active())
        except Exception:
            any_modal = False

        try:
            if (not any_modal) and hasattr(self, "_hover_timer") and self._hover_timer is not None:
                if not self._hover_timer.isActive():
                    self._hover_timer.start()
        except Exception:
            pass

        # как после закрытия рефоржа: синтетически обновить hover/glow
        try:
            QTimer.singleShot(50, self._refresh_hover_after_modal)
            QTimer.singleShot(60, self._poke_hover_synthetic)
        except Exception:
            pass

        try:
            self._update_glow_from_global()
        except Exception:
            pass

    def _ensure_guild_menu_window(self) -> GuildMenu:
        w = getattr(self, "_guild_menu_window", None)
        if isinstance(w, GuildMenu):
            return w

        w = GuildMenu(self)
        self._guild_menu_window = w

        try:
            w.closed.connect(self._on_guild_menu_closed, Qt.ConnectionType.UniqueConnection)
        except Exception:
            try:
                w.closed.connect(self._on_guild_menu_closed)
            except Exception:
                pass

        return w

    def _on_menu_guild_clicked(self) -> None:
        w = self._ensure_guild_menu_window()

        # toggle
        try:
            if w.isVisible():
                w.close()
                return
        except Exception:
            pass

        # блокируем ввод в MainWindow
        try:
            self._block_main_input = True
            self._block_allow_root = w
        except Exception:
            pass

        # прибираем подсветки/tooltip и останавливаем hover
        try:
            if hasattr(self, "_hover_timer") and self._hover_timer is not None and self._hover_timer.isActive():
                self._hover_timer.stop()
        except Exception:
            pass

        for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
            try:
                ww = getattr(self, nm, None)
                if ww is not None:
                    ww.hide()
            except Exception:
                pass

        try:
            if getattr(self, "equip_info", None) is not None:
                try:
                    self.equip_info.end_hover(self)
                except Exception:
                    self.equip_info.hide()
        except Exception:
            pass

        try:
            if getattr(self, "_glow_locked_key", None) is not None:
                self._unlock_glow()
        except Exception:
            pass

        # открыть поверх main, с запоминанием прошлой позиции
        w.open_centered(self)

    def _on_guild_menu_closed(self) -> None:
        # снять блокировку
        try:
            self._block_main_input = False
        except Exception:
            pass
        try:
            self._block_allow_root = None
        except Exception:
            pass

        # вернуть фокус/активность
        try:
            self.raise_()
            self.activateWindow()
            QApplication.setActiveWindow(self)
        except Exception:
            pass

        # hover обратно — но только если сейчас нет других модалок/щитов
        try:
            any_modal = bool(self._stamp_shield_active() or self._reforge_shield_active())
        except Exception:
            any_modal = False

        try:
            if (not any_modal) and hasattr(self, "_hover_timer") and self._hover_timer is not None:
                if not self._hover_timer.isActive():
                    self._hover_timer.start()
        except Exception:
            pass

        try:
            QTimer.singleShot(50, self._refresh_hover_after_modal)
            QTimer.singleShot(60, self._poke_hover_synthetic)
        except Exception:
            pass

        try:
            self._update_glow_from_global()
        except Exception:
            pass

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._hover_timer.isActive():
            self._hover_timer.start()
        self.refresh_stats_panel()

    def _normalize_item_for_calc(self, slot_key: str, it: dict) -> dict:
        d = dict(it)
        sk = str(slot_key or "")
        d.setdefault("slot_key", sk)
        d.setdefault("SlotKey", sk)
        sid = self._slot_db_id(sk)
        if sid:
            d.setdefault("Slot_Id", sid)
            d.setdefault("SlotId", sid)
        if "Id" in d and "Equip_Id" not in d:
            d["Equip_Id"] = d["Id"]
        if "Equip_Id" in d and "Id" not in d:
            d["Id"] = d["Equip_Id"]
        if "Type_Id" in d and "TypeId" not in d:
            d["TypeId"] = d["Type_Id"]
        if "TypeId" in d and "Type_Id" not in d:
            d["Type_Id"] = d["TypeId"]
        return d

    def _schedule_stats_recalc(self, reason: str = "") -> None:
        """
        Отложенный перерасчёт характеристик.

        Нужен, чтобы несколько сигналов подряд от CardsWindow
        не запускали 3-4 полных пересчёта подряд.
        """
        timer = getattr(self, "_stats_recalc_timer", None)

        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(0)

            try:
                timer.timeout.connect(self.refresh_stats_panel, Qt.ConnectionType.UniqueConnection)
            except Exception:
                timer.timeout.connect(self.refresh_stats_panel)

            self._stats_recalc_timer = timer

        try:
            self._last_stats_recalc_reason = str(reason or "")
        except Exception:
            pass

        timer.start(0)

    def _sync_cards_cache_into_selected_items(self) -> None:
        """
        Синхронизирует CardsWindow._per_item_cards обратно в self._selected_items.

        Главная идея:
        математика читает карты из item["_cards"] / item["cards"] / item["Cards"],
        поэтому перед пересчётом надо гарантировать, что dict предмета содержит
        актуальный кэш карт.
        """
        cw = getattr(self, "cards_window", None)
        selected = getattr(self, "_selected_items", None)

        if cw is None or not isinstance(selected, dict):
            return

        get_key = getattr(cw, "_item_key_for", None)
        if not callable(get_key):
            return

        per_item_cards = getattr(cw, "_per_item_cards", None)
        if not isinstance(per_item_cards, dict):
            return

        def _slot_kind_for_cards(slot_key: str) -> str:
            try:
                return "weapon" if self._slot_kind(slot_key) == "weapon" else "equipment"
            except Exception:
                return "weapon" if str(slot_key).lower() in ("weapon", "offhand", "spear") else "equipment"

        def _write_cards_to_item(item: dict, cards_map: dict[int, dict], slot_key: str) -> None:
            clean: dict[int, dict] = {}

            for idx, card in (cards_map or {}).items():
                i = _safe_int(idx, 0)
                if i <= 0 or not isinstance(card, dict):
                    continue

                cid = _safe_int(
                    card.get("Id")
                    or card.get("Card_Id")
                    or card.get("CardId")
                    or card.get("card_id"),
                    0,
                )
                if cid <= 0:
                    continue

                clean[int(i)] = dict(card)

            if clean:
                item["_cards"] = {int(k): dict(v) for k, v in clean.items()}
                item["cards"] = {int(k): dict(v) for k, v in clean.items()}
                item["Cards"] = {int(k): dict(v) for k, v in clean.items()}
            else:
                item.pop("_cards", None)
                item.pop("cards", None)
                item.pop("Cards", None)

            # Element_Id нужен для старой логики бейджа/хита у weapon.
            if str(slot_key).lower() == "weapon":
                first_card = clean.get(1)
                elem_id = 0

                if isinstance(first_card, dict):
                    elem_id = _safe_int(
                        first_card.get("Element_Id")
                        or first_card.get("ElementId"),
                        0,
                    )

                if elem_id > 0:
                    item["Element_Id"] = int(elem_id)
                else:
                    item.pop("Element_Id", None)

        for slot_key, item in list(selected.items()):
            if not isinstance(item, dict):
                continue

            sk = str(slot_key or "").strip()
            if not sk:
                continue

            try:
                item_key = get_key(
                    item,
                    kind=_slot_kind_for_cards(sk),
                    slot_key=sk,
                )
            except TypeError:
                try:
                    item_key = get_key(item, kind=_slot_kind_for_cards(sk))
                except TypeError:
                    item_key = get_key(item)
            except Exception:
                item_key = None

            if item_key is None:
                continue

            # Важно:
            # если ключа нет в кэше — не трогаем item.
            # если ключ есть, но там {} — значит карты сняты, и aliases надо очистить.
            if item_key not in per_item_cards:
                continue

            cards_map = per_item_cards.get(item_key) or {}
            _write_cards_to_item(item, cards_map, sk)

    def _on_item_cache_changed(self, *_args) -> None:
        """
        Реакция на любое подтверждённое изменение CardsWindow._per_item_cards.
        """
        try:
            self._sync_cards_cache_into_selected_items()
        except Exception:
            pass

        try:
            self._sync_buff_debuff_menu_context()
        except Exception:
            pass

        try:
            self._schedule_stats_recalc("item_cache_changed")
        except Exception:
            try:
                self.refresh_stats_panel()
            except Exception:
                pass

    def refresh_stats_panel(self, *_args, **_kwargs) -> None:
        if not isinstance(getattr(self, "character_stats", None), dict):
            self.character_stats = {}
        try:
            self._sync_cards_cache_into_selected_items()
        except Exception:
            pass

        main_panel = getattr(self, "stats_panel", None)
        other_panel = getattr(self, "other_stats_panel", None)
        cw = getattr(self, "cards_window", None)

        menu_bonus_enabled = self._get_menu_bonus_enabled_map()

        calc_panel = main_panel if main_panel is not None else other_panel

        if calc_panel is None:
            if cw is not None:
                stats_dict = dict(getattr(self, "character_stats", {}) or {})
                if hasattr(cw, "set_character_stats"):
                    cw.set_character_stats(stats_dict)
                cw._current_stats_dict = dict(stats_dict)
                if hasattr(cw, "on_current_stats_changed"):
                    cw.on_current_stats_changed(stats_dict)
            return

        for panel in (main_panel, other_panel):
            if panel is None:
                continue
            try:
                fn = getattr(panel, "set_menu_bonus_enabled", None)
                if callable(fn):
                    fn(dict(menu_bonus_enabled))
                else:
                    panel.menu_bonus_enabled = dict(menu_bonus_enabled)
            except Exception:
                try:
                    panel.menu_bonus_enabled = dict(menu_bonus_enabled)
                except Exception:
                    pass

        base_stats = None
        if getattr(self, "param_points", None):
            base_stats = self.param_points.as_base_stats()

        class_id = 0
        if hasattr(self, "_current_class_id"):
            class_id = _safe_int(self._current_class_id(), 0)

        class_name = None
        if getattr(self, "class_combo", None) is not None:
            class_name = self.class_combo.currentText()

        level = 1
        if getattr(self, "level_spin", None) is not None:
            level = _safe_int(self.level_spin.value(), 1) or 1

        event_id = _safe_int(getattr(self, "_current_event_id", 0), 0)
        state_id = _safe_int(getattr(self, "_current_state_id", 0), 0)

        EQUIP_SLOT_KEYS = set((SLOT_POS or {}).keys())
        selected_map = getattr(self, "_selected_items", {}) or {}
        if not isinstance(selected_map, dict):
            selected_map = dict(selected_map)

        offhand_disabled = bool(self._is_offhand_disabled()) if hasattr(self, "_is_offhand_disabled") else False
        equipment_rows = []

        for slot_key, it in (selected_map or {}).items():
            sk = str(slot_key or "").strip().lower()
            if sk.startswith("inv") or sk.startswith("inventory"):
                continue
            if sk not in EQUIP_SLOT_KEYS:
                continue
            if not it:
                continue
            if sk == "offhand" and offhand_disabled:
                continue
            if not isinstance(it, dict):
                it = dict(it)

            meta = self._slot_meta(sk) if hasattr(self, "_slot_meta") else None
            if meta and meta.state_id is not None and int(meta.state_id) != int(state_id):
                continue

            it = self._normalize_item_for_calc(sk, it)
            equipment_rows.append(it)

        try:
            res = calc_panel.recalc_and_update(
                class_id=class_id,
                class_name=class_name,
                level=level,
                equipment_rows=equipment_rows,
                base_stats=base_stats,
                event_id=event_id,
                state_id=state_id,
                menu_bonus_enabled=dict(menu_bonus_enabled),
            )
        except TypeError:
            try:
                res = calc_panel.recalc_and_update(
                    class_id=class_id,
                    class_name=class_name,
                    level=level,
                    equipment_rows=equipment_rows,
                    base_stats=base_stats,
                    event_id=event_id,
                    state_id=state_id,
                )
            except TypeError:
                try:
                    res = calc_panel.recalc_and_update(
                        class_id=class_id,
                        class_name=class_name,
                        level=level,
                        equipment_rows=equipment_rows,
                        base_stats=base_stats,
                        menu_bonus_enabled=dict(menu_bonus_enabled),
                    )
                except TypeError:
                    res = calc_panel.recalc_and_update(
                        class_id=class_id,
                        class_name=class_name,
                        level=level,
                        equipment_rows=equipment_rows,
                        base_stats=base_stats,
                    )

        stats_dict = dict(res or {})
        self.character_stats = dict(stats_dict)

        # если считали не main_panel — дольём значения в main_panel
        if main_panel is not None and main_panel is not calc_panel:
            try:
                main_panel.update_by_id(stats_dict)
            except Exception:
                pass

        # правый борд всегда обновляем отдельно тем же результатом
        if other_panel is not None and other_panel is not calc_panel:
            try:
                other_panel.update_by_id(stats_dict)
            except Exception:
                pass

        if cw is not None:
            if hasattr(cw, "set_character_stats"):
                cw.set_character_stats(stats_dict)
            cw._current_stats_dict = dict(stats_dict)
            if hasattr(cw, "on_current_stats_changed"):
                cw.on_current_stats_changed(stats_dict)

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return super().mousePressEvent(ev)

        self._pressed_inside = True
        ev.accept()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(ev)

        owner = self.parentWidget()
        armed = bool(getattr(self, "_pressed_inside", False))
        self._pressed_inside = False

        try:
            inside = self.rect().contains(ev.position().toPoint())
        except Exception:
            try:
                inside = self.rect().contains(ev.pos())
            except Exception:
                inside = False

        if armed and inside and owner is not None:
            try:
                fn = getattr(owner, "_on_menu_bonus_toggle_clicked", None)
                if callable(fn):
                    fn(self._menu_key)
            except Exception:
                pass

        ev.accept()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag_pos and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_pos)
            ev.accept()

    def _apply_class_border_for_current(self) -> None:
        self.class_btn.setStyleSheet(
            self._CLASS_ICON_STYLE_NORMAL if self._is_base_class() else self._CLASS_ICON_STYLE_ACTIVE
        )

    # ---------- динамическая база ----------
    def _update_design_base_from_original(self) -> None:
        pm = self._bg_current or self._bg_default or self._bg_spear
        if pm and not pm.isNull():
            self._base_w = pm.width()
            self._base_h = pm.height()

    # ---------- фабрики ----------
    def _mk_gender_btn(self, pm: Optional[QPixmap], tooltip: str) -> QToolButton:
        b = QToolButton(self)
        b.setToolTip(tooltip)
        b.setCursor(Qt.PointingHandCursor)
        b.setAutoRaise(True)
        if pm:
            b.setIcon(QIcon(pm))
        b.setIconSize(QSize(GENDER_ICON_PX, GENDER_ICON_PX))
        b.setFixedSize(GENDER_ICON_PX + GENDER_BTN_PAD, GENDER_ICON_PX + GENDER_BTN_PAD)
        b.setStyleSheet("background: transparent;")
        b.setAttribute(Qt.WA_TranslucentBackground, True)
        b.setAutoFillBackground(False)
        return b

    # ---------- геометрия ----------
    def _scale(self) -> float:
        pm = self.board_label.pixmap()
        return (pm.width() / self._base_w) if (pm and self._base_w) else 1.0

    def _img_rect(self) -> QRect:
        return self.board_label.geometry()

    def _project(self, x: int, y: int, w: int = 0, h: int = 0) -> QRect:
        sx = self._scale()
        ir = self._img_rect()
        return QRect(int(ir.x() + x * sx), int(ir.y() + y * sx), int(w * sx), int(h * sx))

    # ---------- меню классов ----------
    def _build_class_menu(self) -> None:
        self.class_menu = _InfoBoardMenu(self)
        _apply_popup_menu_style(self.class_menu)

        panel = QWidget(self.class_menu)
        panel.setAttribute(Qt.WA_TranslucentBackground, True)
        panel.setAutoFillBackground(False)
        panel.setStyleSheet(POPUP_PANEL_STYLE)

        grid = QGridLayout(panel)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)

        COLS, ICON = 3, 48

        for i, (cid, cname, pm) in enumerate(getattr(self, "_classes", []) or []):
            r, c = divmod(i, COLS)

            btn = ClassThumb(
                int(cid),
                str(cname or ""),
                pm,
                size_px=ICON,
                parent=panel,
            )

            btn.clicked.connect(
                lambda _=False, c_id=cid: self._choose_class_from_menu(c_id)
            )

            grid.addWidget(btn, r, c, alignment=Qt.AlignCenter)

        act = QWidgetAction(self.class_menu)
        act.setDefaultWidget(panel)

        self.class_menu.clear()
        self.class_menu.addAction(act)

        def _on_menu_show():
            self._set_class_icon_active(True)

            if hasattr(self, "_hover_timer") and self._hover_timer.isActive():
                self._hover_timer.stop()

            if getattr(self, "menu_glow", None):
                self.menu_glow.hide()

            if getattr(self, "hover_glow", None):
                self.hover_glow.hide()

            if getattr(self, "winbtn_hover", None):
                self.winbtn_hover.hide()

            if getattr(self, "equip_info", None):
                self.equip_info.hide()

            try:
                self._hide_hover_name_label()
            except Exception:
                pass

        def _on_menu_hide():
            self._set_class_icon_active(False)

            if hasattr(self, "_hover_timer") and not self._hover_timer.isActive():
                self._hover_timer.start()

            if getattr(self, "_glow_locked_key", None) is not None:
                self._unlock_glow()

            QTimer.singleShot(0, self._refresh_hover_after_modal)
            QTimer.singleShot(0, self._poke_hover_synthetic)

        try:
            self.class_menu.aboutToShow.connect(
                _on_menu_show,
                Qt.ConnectionType.UniqueConnection,
            )
        except Exception:
            self.class_menu.aboutToShow.connect(_on_menu_show)

        try:
            self.class_menu.aboutToHide.connect(
                _on_menu_hide,
                Qt.ConnectionType.UniqueConnection,
            )
        except Exception:
            self.class_menu.aboutToHide.connect(_on_menu_hide)

    def _choose_class_from_menu(self, class_id: int) -> None:
        for i in range(self.class_combo.count()):
            if self.class_combo.itemData(i) == class_id:
                self.class_combo.setCurrentIndex(i)
                break
        if hasattr(self, "class_menu") and self.class_menu is not None: self.class_menu.hide()

    def _set_class_icon_active(self, active: bool) -> None:
        self.class_btn.setStyleSheet(self._CLASS_ICON_STYLE_ACTIVE if active else self._CLASS_ICON_STYLE_NORMAL)

    # ---------- фильтр событий ----------
    def _gp_from_ev(self, ev) -> QPoint:
        try:
            return ev.globalPosition().toPoint()
        except Exception:
            try:
                return ev.globalPos()
            except Exception:
                return QCursor.pos()

    def eventFilter(self, obj, ev):
        """Оптимизированная обработка событий главного окна (с DB-driven слотами)."""
        from PySide6.QtWidgets import QWidget

        NON_MOVABLE_SLOTS = set(NON_INVENTORY_COPY_SLOTS)

        # fallback-наборы (на случай если _slot_kind() недоступен/не знает слот)
        CARD_SLOTS_EQUIPMENT = {"head", "mask", "armor", "gloves", "legs", "boots", "artifact", "totem", "ring1",
                                "ring2", "amulet"}
        CARD_SLOTS_WEAPON = {"weapon", "spear"}  # offhand решаем по факту предмета

        et = ev.type()

        # --- пол: всегда меняем на release, но не глотаем release у самой кнопки ---
        if et == QEvent.MouseButtonRelease and obj in (
                getattr(self, "gender_m_btn", None),
                getattr(self, "gender_f_btn", None),
        ):
            if ev.button() == Qt.LeftButton:
                if obj is getattr(self, "gender_m_btn", None):
                    self._set_gender(1)
                elif obj is getattr(self, "gender_f_btn", None):
                    self._set_gender(2)
            return False

        selected = self._selected_items or {}
        slot_icons = getattr(self, "_slot_icons", None) or {}

        def _mods():
            return ev.modifiers() if hasattr(ev, "modifiers") else QApplication.keyboardModifiers()

        def _icon_key(lbl):
            v = lbl.property("slot_key") if hasattr(lbl, "property") else None
            if v:
                return str(v)
            cache = getattr(self, "_slot_icon_to_key", None)
            if cache is None or len(cache) != len(slot_icons):
                cache = {v: k for k, v in slot_icons.items()}
                self._slot_icon_to_key = cache
            return cache.get(lbl)

        def _slot_has_item(slot_key: str) -> bool:
            return bool(selected.get(str(slot_key)))

        def _open_cards_if_shift_rclick(slot_key: str) -> bool:
            """Открыть окно карт по Shift+ПКМ, если в слоте есть предмет."""
            if not slot_key:
                return True

            sk = str(slot_key)

            # NEW: костюм / украшение / ездовой — карты запрещены
            if sk in NON_MOVABLE_SLOTS:
                return True

            # если в слоте нет предмета — как и раньше, ничего не делаем
            it = selected.get(sk)
            if not it:
                return True

            # NEW: фоллбэк-блок по EquipmentType.Slot_Id (EquipmentSlot.Id)
            # (на случай если NON_MOVABLE_SLOTS где-то не совпадёт)
            try:
                conn = getattr(getattr(self, "data", None), "conn", None)
                tid = _safe_int(it.get("Type_Id") or it.get("TypeId") or 0, 0)
                if conn is not None and tid > 0:
                    row = conn.execute(
                        "SELECT Slot_Id FROM EquipmentType WHERE Id=? LIMIT 1",
                        (int(tid),),
                    ).fetchone()
                    slot_db = _safe_int(row["Slot_Id"] if hasattr(row, "keys") else row[0], 0) if row else 0
                    if slot_db in (13, 14, 15):
                        return True
            except Exception:
                pass

            opener = getattr(self, "_open_cards_menu", None)
            if not callable(opener):
                return True

            kind_fn = getattr(self, "_slot_kind", None)
            kind = None
            if callable(kind_fn):
                try:
                    kind = kind_fn(sk)
                except Exception:
                    kind = None

            if sk == "offhand":
                is_weapon_fn = getattr(self, "_item_is_weapon", None)
                is_weapon = False
                if callable(is_weapon_fn):
                    try:
                        is_weapon = bool(is_weapon_fn(it))
                    except Exception:
                        is_weapon = False
                opener("weapon" if is_weapon else "equipment", item=it, slot_key=sk)
                return True

            if kind is None:
                if sk in CARD_SLOTS_WEAPON:
                    kind = "weapon"
                elif sk in CARD_SLOTS_EQUIPMENT:
                    kind = "equipment"

            if kind in ("weapon", "equipment"):
                opener(kind, item=it, slot_key=sk)
            return True

        def _open_slot_primary(slot_key: str, rect: QRect) -> bool:
            if not slot_key:
                return False

            is_active = getattr(self, "_slot_is_active_in_current_state", None)
            if callable(is_active) and not is_active(slot_key):
                return True

            opener = getattr(self, "_open_equip_menu_async", None)
            if callable(opener):
                is_weapon = None
                kind = getattr(self, "_slot_kind", None)
                if callable(kind):
                    try:
                        is_weapon = (kind(slot_key) == "weapon")
                    except Exception:
                        is_weapon = None

                ok = False
                try:
                    ok = bool(opener(slot_key, rect, is_weapon=is_weapon))
                except TypeError:
                    try:
                        ok = bool(opener(slot_key, rect))
                    except Exception:
                        ok = False
                except Exception:
                    ok = False

                if ok:
                    return True

            picker = getattr(self, "_open_picker_for_slot", None)
            if callable(picker):
                picker(slot_key)
                return True

            return False

        # ---- окна, которые нужно ловить на Show/Hide (рефорж и т.п.) ----
        uw = getattr(self, "upgrade_win", None)
        cw = getattr(self, "cards_window", None)

        if obj in (uw, cw):
            if et == QEvent.Show:
                if hasattr(self, "_hover_timer"):
                    self._hover_timer.stop()
                if getattr(self, "equip_info", None):
                    self.equip_info.hide()

                if obj is uw:
                    self._ensure_reforge_shield()
                    self._ensure_inventory_shield()
                    if getattr(self, "menu_glow", None):
                        self.menu_glow.hide()
                    if getattr(self, "hover_glow", None):
                        self.hover_glow.hide()
                    if getattr(self, "winbtn_hover", None):
                        self.winbtn_hover.hide()
                return False

            if et in (QEvent.Hide, QEvent.Close, QEvent.HideToParent):
                if obj is uw:
                    self._remove_reforge_shield()
                    self._remove_inventory_shield()

                self.raise_()
                self.activateWindow()
                QApplication.setActiveWindow(self)

                if hasattr(self, "_hover_timer") and not self._hover_timer.isActive():
                    self._hover_timer.start()

                QTimer.singleShot(50, self._refresh_hover_after_modal)
                QTimer.singleShot(60, self._poke_hover_synthetic)
                return False

        # --- синхронизация геометрии щитов при ресайзе ---
        if et == QEvent.Resize:
            sh = getattr(self, "_stamp_shield", None)
            if sh is not None:
                sh.sync_geometry()
            sh2 = getattr(self, "_reforge_shield", None)
            if sh2 is not None:
                sh2.sync_geometry()
            inv_sh = getattr(self, "_inv_shield", None)
            if inv_sh is not None:
                inv_sh.sync_geometry()
            return False

        # --- глобальная блокировка ввода ---
        block_due_to_modal = self._any_input_shield_active()

        # ------------------------------------------------------------
        # Если открыто окно, которое включает щит,
        # блокируем ТОЛЬКО прокрутку колеса в MainWindow.
        #
        # Колесо внутри самого открытого окна/меню НЕ трогаем.
        # Клики тоже НЕ трогаем этим блоком.
        # ------------------------------------------------------------
        if block_due_to_modal and et == QEvent.Wheel:
            w = obj if isinstance(obj, QWidget) else None
            allow_root = getattr(self, "_block_allow_root", None)

            # Если колесо крутят внутри открытого разрешённого окна
            # cards/stamp/reforge/etc — пропускаем.
            if w and allow_root and (w is allow_root or allow_root.isAncestorOf(w)):
                return False

            # Если колесо прилетело в MainWindow или его дочерние виджеты —
            # глотаем, чтобы не менялся уровень персонажа.
            if w and w.window() is self:
                try:
                    ev.accept()
                except Exception:
                    pass
                return True

            return False

        # ------------------------------------------------------------
        # Старую блокировку мыши оставляем, но БЕЗ QEvent.Wheel.
        # ------------------------------------------------------------
        if block_due_to_modal and et in (
                QEvent.MouseButtonDblClick,
                QEvent.ContextMenu,
                QEvent.DragEnter,
                QEvent.DragMove,
                QEvent.DragLeave,
                QEvent.Drop,
        ):
            w = obj if isinstance(obj, QWidget) else None
            allow_root = getattr(self, "_block_allow_root", None)

            if w and allow_root and (w is allow_root or allow_root.isAncestorOf(w)):
                return False

            if w and w.window() is self:
                try:
                    ev.accept()
                except Exception:
                    pass
                return True

        # --- события НЕ из нашего окна не интерпретируем ---
        if isinstance(obj, QWidget):
            if obj.window() is not self:
                return False
        else:
            return False

        # --- движение мыши: обновление glow ---
        if et == QEvent.MouseMove:
            if block_due_to_modal:
                if getattr(self, "menu_glow", None):
                    self.menu_glow.hide()
                if getattr(self, "hover_glow", None):
                    self.hover_glow.hide()
                if getattr(self, "winbtn_hover", None):
                    self.winbtn_hover.hide()
                return False
            self._update_glow_from_global(ev)
            return False

        # ======================================================================
        #                      И К О Н К И   С Л О Т О В   (QLabel)
        # ======================================================================
        if (slot_icons and obj in slot_icons.values()) or (hasattr(obj, "property") and obj.property("slot_key")):
            slot_key = _icon_key(obj)

            if et == QEvent.Enter and slot_key:
                item = selected.get(slot_key)
                if not item:
                    return False

                bonus_lines = _render_bonus_lines(self.data.conn, _safe_int(item.get("Id"), 0))

                mask_slots = getattr(self, "_mask_stamp_slots", None) or set()
                stamp_payload = None if slot_key in mask_slots else self._stamp_payload_for_item(item)
                if slot_key == "ornament":
                    stamp_payload = False

                anchor_rect = QRect(obj.mapToGlobal(obj.rect().topLeft()), obj.rect().size())
                gp = anchor_rect.center()

                try:
                    self.equip_info._ctx_root = self
                except Exception:
                    pass

                if getattr(self, "equip_info", None):
                    self.equip_info.show_for_item(
                        item,
                        image_loader=self.data.get_image_bytes,
                        global_pos=gp,
                        type_name=None,
                        type_name_lookup=self._etype_name_by_id,
                        item_class=item.get("ItemClass"),
                        cards=None,
                        bonus_lines=bonus_lines,
                        stamp=stamp_payload,
                        anchor_rect_global=anchor_rect,
                    )
                return False

            if et == QEvent.Leave:
                if getattr(self, "equip_info", None):
                    self.equip_info.end_hover(obj)
                return False

            if et == QEvent.MouseButtonRelease and slot_key:
                if getattr(self, "equip_info", None):
                    self.equip_info.hide()

                rect = self._zone_rect(slot_key) or obj.geometry()

                if ev.button() == Qt.LeftButton:
                    return _open_slot_primary(slot_key, rect)

                if ev.button() == Qt.RightButton:
                    m = _mods()
                    if m & Qt.ShiftModifier:
                        return _open_cards_if_shift_rclick(slot_key)
                    if m & Qt.ControlModifier:
                        lp = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
                        gp = obj.mapToGlobal(lp)
                        return self._open_slot_context_menu_async(slot_key, gp)
                    if slot_key in NON_MOVABLE_SLOTS:
                        return True
                    self._move_slot_item_to_inventory(slot_key)
                    return True

                return False

            return False

        # ======================================================================
        #                               Б О Р Д А
        # ======================================================================
        if obj is getattr(self, "board_label", None) and et == QEvent.MouseButtonRelease:
            lp = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
            key, rect = self._hit_zone(obj.mapToParent(lp))
            if not key or not rect:
                return False

            if key == "minimize":
                self.showMinimized()
                return True
            if key == "close":
                self.close()
                return True

            m = _mods()

            if key in MENU_KEYS:
                if ev.button() == Qt.LeftButton:
                    if key == "stamp":
                        self._open_stamp_menu()
                        return True
                    if key == "inventory":
                        self._on_menu_bag_clicked()
                        return True
                    if key == "collect":
                        self._on_menu_collect_clicked()
                        return True
                return True

            if key in SLOT_POS:
                if ev.button() == Qt.LeftButton:
                    return _open_slot_primary(key, rect)

                if ev.button() == Qt.RightButton:
                    if m & Qt.ShiftModifier:
                        return _open_cards_if_shift_rclick(key)
                    if m & Qt.ControlModifier:
                        gp = QCursor.pos()
                        return self._open_slot_context_menu_async(key, gp)
                    if key in NON_MOVABLE_SLOTS:
                        return True
                    self._move_slot_item_to_inventory(key)
                    return True

                return True

        return False

    def _open_equip_menu_async(self, key: str, rect: QRect, *, is_weapon: Optional[bool] = None) -> bool:
        ctrl = {
            "costume": self.costume_ctrl,
            "mount": getattr(self, "mount_ctrl", None),
            "weapon": self.weapon_ctrl,
            "offhand": self.offhand_ctrl,
            "spear": self.spear_ctrl,
        }.get(key, (self.eq_ctrls or {}).get(key))
        if not ctrl:
            return False
        hint = self._items_menu_size_hint(key)
        pos = self.mapToGlobal(QPoint(rect.left() - (hint.height() - 207), rect.top() - (hint.height() + 68)))

        def _finish_unlock() -> None:
            self._equip_via_menu = False
            self._block_weapon_clear_for_offhand_menu = False
            self._unlock_glow()

            ht = getattr(self, "_hover_timer", None)
            if ht is not None and not ht.isActive():
                ht.start()

            QTimer.singleShot(0, self._update_glow_from_global)
            QTimer.singleShot(0, self._poke_hover_synthetic)

        def _open() -> None:
            self._lock_glow_on_slot(key, rect)
            self._equip_via_menu = True
            if key == "offhand":
                weapon = (self._selected_items or {}).get("weapon")
                self._block_weapon_clear_for_offhand_menu = bool(self._weapon_is_two_handed(weapon))
            else:
                self._block_weapon_clear_for_offhand_menu = False

            try:
                menu = ctrl.show_menu(pos)
            except Exception:
                menu = None
            if not menu:
                _finish_unlock()
                return

            menu.aboutToHide.connect(_finish_unlock)
            if hasattr(menu, "triggered"):
                menu.triggered.connect(lambda *_: _finish_unlock())

            def _watchdog() -> None:
                popup = QApplication.activePopupWidget()
                if popup is None or not popup.isVisible():
                    if getattr(self, "_glow_locked_key", None) is not None:
                        _finish_unlock()
                    return
                QTimer.singleShot(60, _watchdog)

            QTimer.singleShot(60, _watchdog)

        QTimer.singleShot(0, _open)
        return True

    def _open_slot_context_menu_async(self, key: str, global_pos) -> bool:
        def _show():
            item = (self._selected_items or {}).get(key)

            m = _InfoBoardMenu(self)
            _apply_popup_menu_style(m)

            if item:
                # --- кольца: дублирование (как было) ---
                if key in ("ring1", "ring2") or str(key).startswith("ring"):
                    act_dup = m.addAction("Дублировать кольцо")
                    target = "ring2" if key == "ring1" else "ring1"

                    def _dup(*_):
                        src_item = self._ensure_instance_guid(dict(item)) or dict(item)

                        try:
                            import copy as _copy
                            dup_item = _copy.deepcopy(src_item)
                        except Exception:
                            dup_item = dict(src_item)
                            for _k in (
                                    "Stamp", "stamp", "StampBonuses", "StampBonusLines", "Bonuses",
                                    "_cards", "cards", "Cards",
                                    "Elixir", "_elixir",
                            ):
                                if _k in dup_item:
                                    v = dup_item.get(_k)
                                    try:
                                        import copy as _copy2
                                        dup_item[_k] = _copy2.deepcopy(v)
                                    except Exception:
                                        try:
                                            dup_item[_k] = dict(v)
                                        except Exception:
                                            try:
                                                dup_item[_k] = list(v)
                                            except Exception:
                                                dup_item[_k] = v

                        dup_item["InstanceGuid"] = str(uuid4())

                        self._on_pick_equipment(target, dup_item)
                        new_it = (self._selected_items or {}).get(target)

                        st = self._stamp_payload_for_item(src_item)
                        if st and new_it and new_it.get("InstanceGuid"):
                            self.apply_stamp_to_item(
                                new_it["InstanceGuid"],
                                _safe_int(st.get("Id"), 0),
                                _safe_int(st.get("ColorId"), 0),
                                list(st.get("Bonuses") or []),
                                st.get("Name") or "",
                            )

                        cw = getattr(self, "cards_window", None)
                        if cw and new_it and hasattr(cw, "clone_cards_between_items"):
                            cw.clone_cards_between_items(
                                src_item=src_item,
                                dst_item=new_it,
                                kind="equipment",
                                src_slot_key=key,
                                dst_slot_key=target,
                            )

                    act_dup.triggered.connect(_dup)
                    m.addSeparator()

                # --- Эликсиры (Ctrl+ПКМ): добавляем пункты "Добавить/Убрать ..." ---
                conn = getattr(getattr(self, "data", None), "conn", None)
                if conn is not None:
                    # пересобрать регистр слотов, если маппинга ещё нет или он пустой
                    try:
                        need_init = (not hasattr(self, "_ui_slot_to_db_slot_id")) or (
                            not isinstance(getattr(self, "_ui_slot_to_db_slot_id", None), dict)
                        ) or (len(getattr(self, "_ui_slot_to_db_slot_id", {}) or {}) == 0)
                        if need_init and hasattr(self, "_init_equipment_slot_registry"):
                            self._init_equipment_slot_registry()
                    except Exception:
                        pass

                    # убедимся, что есть InstanceGuid (и запишем обратно в слот при необходимости)
                    it2 = self._ensure_instance_guid(dict(item)) or dict(item)
                    if it2.get("InstanceGuid") and (
                            not isinstance(item, dict) or item.get("InstanceGuid") != it2.get("InstanceGuid")):
                        try:
                            (self._selected_items or {})[key] = dict(it2)
                            item = (self._selected_items or {}).get(key) or dict(it2)
                        except Exception:
                            item = dict(it2)

                    inst = str((item or {}).get("InstanceGuid") or "").strip()
                    if inst:
                        # текущий Equip_Id (нужен для проверки "можно ли выбрать для родителя")
                        equip_id = _safe_int(
                            (item or {}).get("Id") or (item or {}).get("Equipment_Id") or (item or {}).get("Equip_Id"),
                            0
                        )

                        # линейка классов (для списка допустимых предметов)
                        lineage: list[int] = []
                        try:
                            cid = _safe_int(self._current_class_id(), 0)
                            lineage = list(self._class_lineage_ids(cid) or []) if cid > 0 else []
                        except Exception:
                            lineage = []

                        # можно ли вообще пользоваться логикой extra-weapon
                        try:
                            can_extra = bool(self._class_can_use_extra_weapon())
                        except Exception:
                            can_extra = False

                        # 1) slot_id по UI ключу
                        sid = None
                        try:
                            sid = self._slot_db_id(str(key))
                        except Exception:
                            sid = None

                        # 2) фолбэк: берём slot_id из типа предмета (EquipmentType.Slot_Id)
                        if not sid:
                            try:
                                tid = _safe_int((item or {}).get("Type_Id") or (item or {}).get("TypeId"), 0)
                                if tid > 0:
                                    row = conn.execute(
                                        "SELECT Slot_Id FROM EquipmentType WHERE Id=? LIMIT 1",
                                        (int(tid),)
                                    ).fetchone()
                                    if row:
                                        sid = _safe_int(row["Slot_Id"] if hasattr(row, "keys") else row[0], 0)
                                        if sid <= 0:
                                            sid = None
                            except Exception:
                                sid = None

                        slot_ids: list[int] = []
                        if sid:
                            slot_ids.append(int(sid))

                        # ExtraSlot:
                        #  - дочерний (meta.id == sid -> meta.extra_slot_id) оставляем как было
                        #  - родитель (meta.extra_slot_id == sid) ТЕПЕРЬ добавляем ТОЛЬКО если текущий предмет
                        #    реально допустим для родителя (по list_equipment_for_slot + линейка классов)
                        try:
                            meta_by_id = getattr(self, "_slot_meta_by_id", None)
                            if slot_ids and isinstance(meta_by_id, dict):
                                base = int(slot_ids[0])

                                # --- родительские слоты (исправление) ---
                                for meta in (meta_by_id or {}).values():
                                    try:
                                        if not meta:
                                            continue
                                        if int(getattr(meta, "extra_slot_id", 0) or 0) != base:
                                            continue

                                        parent_sid = int(getattr(meta, "id"))
                                        if parent_sid <= 0:
                                            continue

                                        # ВАЖНО: показываем "родительские" эликсиры на экстра-слоте
                                        # только если:
                                        #  - класс разрешает extra-weapon
                                        #  - и этот предмет можно выбрать для родительского слота
                                        if not can_extra or equip_id <= 0 or not lineage:
                                            continue

                                        allowed: set[int] = set()
                                        for c in lineage:
                                            try:
                                                allowed |= set(
                                                    self._allowed_equipment_ids_for(parent_sid, int(c)) or set())
                                            except Exception:
                                                continue

                                        if allowed and (equip_id in allowed):
                                            slot_ids.append(parent_sid)
                                    except Exception:
                                        continue

                                # --- дочерний слот (как было) ---
                                try:
                                    cur_meta = (meta_by_id or {}).get(base)
                                    ex = int(getattr(cur_meta, "extra_slot_id", 0) or 0) if cur_meta else 0
                                    if ex > 0:
                                        slot_ids.append(ex)
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        # уникальные
                        seen = set()
                        slot_ids = [x for x in slot_ids if (x not in seen and not seen.add(x))]

                        # получить список эликсиров
                        try:
                            from .equipment_elixir import list_elixirs_for_slots, get_elixir_meta, get_elixir_bonuses
                            elixirs = list_elixirs_for_slots(conn, slot_ids)
                        except Exception:
                            elixirs = []

                        if elixirs:
                            # текущий активный эликсир
                            cur_id = 0
                            cur_el = (item or {}).get("Elixir") or (item or {}).get("_elixir")
                            if isinstance(cur_el, dict):
                                cur_id = _safe_int(cur_el.get("Id") or cur_el.get("id"), 0)

                            if cur_id <= 0:
                                cache = getattr(self, "_applied_elixirs", None)
                                if isinstance(cache, dict) and isinstance(cache.get(inst), dict):
                                    cur_id = _safe_int((cache.get(inst) or {}).get("id"), 0)

                            m.addSeparator()

                            for e in elixirs:
                                eid = _safe_int(e.get("Id"), 0)
                                nm = str(e.get("Name") or "")
                                if eid <= 0 or not nm:
                                    continue

                                active = (eid == cur_id)
                                title = ("Убрать " if active else "Добавить ") + nm
                                act = m.addAction(title)

                                def _toggle(_=False, _eid=eid, _active=active, _key=str(key)):
                                    sel = getattr(self, "_selected_items", None)
                                    if not isinstance(sel, dict):
                                        return
                                    cur_item = sel.get(_key)
                                    if not isinstance(cur_item, dict) or not cur_item:
                                        return

                                    cur_item = self._ensure_instance_guid(dict(cur_item)) or dict(cur_item)
                                    inst2 = str(cur_item.get("InstanceGuid") or "").strip()
                                    if not inst2:
                                        return

                                    cache2 = getattr(self, "_applied_elixirs", None)
                                    if not isinstance(cache2, dict):
                                        cache2 = {}
                                        self._applied_elixirs = cache2

                                    ELX_BASE = 9000
                                    ELX_LIM = 9100

                                    # чистим только "наши" inline-поля
                                    for kk in list(cur_item.keys()):
                                        if not isinstance(kk, str):
                                            continue
                                        suf = None
                                        if kk.startswith("BonusType"):
                                            suf = kk[len("BonusType"):]
                                        elif kk.startswith("Var"):
                                            suf = kk[len("Var"):]
                                        elif kk.startswith("Value"):
                                            suf = kk[len("Value"):]
                                        if suf is None:
                                            continue
                                        try:
                                            idx = int(suf)
                                        except Exception:
                                            continue
                                        if ELX_BASE <= idx < ELX_LIM:
                                            cur_item.pop(kk, None)

                                    # снять
                                    if _active:
                                        cache2.pop(inst2, None)
                                        cur_item.pop("Elixir", None)
                                        cur_item.pop("_elixir", None)
                                    else:
                                        # применить/заменить
                                        try:
                                            meta = get_elixir_meta(conn, int(_eid)) or {}
                                        except Exception:
                                            meta = {}

                                        try:
                                            bonuses = list(get_elixir_bonuses(conn, int(_eid)) or [])
                                        except Exception:
                                            bonuses = []

                                        payload = {
                                            "Id": int(_eid),
                                            "Name": str(meta.get("Name") or ""),
                                            "Image_Id": meta.get("Image_Id"),
                                            "Bonuses": list(bonuses),
                                        }
                                        cur_item["Elixir"] = dict(payload)

                                        cache2[inst2] = {
                                            "id": int(_eid),
                                            "name": payload["Name"] or "",
                                            "image_id": payload.get("Image_Id"),
                                            "bonuses": list(payload.get("Bonuses") or []),
                                        }

                                        # inline BonusType/Var
                                        try:
                                            bonuses_sorted = sorted(
                                                [b for b in bonuses if isinstance(b, dict)],
                                                key=lambda b: _safe_int(b.get("OrderIndex"), 0),
                                            )
                                        except Exception:
                                            bonuses_sorted = [b for b in bonuses if isinstance(b, dict)]

                                        i = 0
                                        for b in bonuses_sorted:
                                            idx = ELX_BASE + i
                                            if idx >= ELX_LIM:
                                                break
                                            bt = _safe_int(b.get("Type_Id"), 0)
                                            val = _safe_int(b.get("Value"), 0)
                                            if bt > 0 and val != 0:
                                                cur_item[f"BonusType{idx}"] = int(bt)
                                                cur_item[f"Var{idx}"] = int(val)
                                            i += 1

                                    sel[_key] = dict(cur_item)
                                    try:
                                        self._update_slot_icon(_key)
                                    except Exception:
                                        pass
                                    try:
                                        self.refresh_stats_panel()
                                    except Exception:
                                        pass
                                    ei = getattr(self, "equip_info", None)
                                    if ei and ei.isVisible():
                                        try:
                                            ei.hide()
                                        except Exception:
                                            pass

                                act.triggered.connect(_toggle)

                            m.addSeparator()

                # --- остальное (как было) ---
                slot_key_norm = str(key or "").strip().lower()

                # Для Костюма / Украшения / Ездового животного пункт копирования
                # вообще не добавляем в меню.
                if slot_key_norm not in NON_INVENTORY_COPY_SLOTS:
                    m.addAction("Копировать предмет в инвентарь").triggered.connect(
                        lambda _=False, it=item, k=key: self._add_item_to_inventory(it, slot_key=k)
                    )

                m.addAction("Очистить слот").triggered.connect(lambda *_: self._on_clear_equipment(key))

            m.popup(global_pos)

        QTimer.singleShot(0, _show)
        return True

    def _bulk_clear_equipment_slots(self, slots: list[str]) -> None:
        """Очистить несколько слотов и сделать один refresh в конце."""
        if not slots:
            return
        sel = self._selected_items or {}
        icons = getattr(self, "_slot_icons", None) or {}
        mask = getattr(self, "_mask_stamp_slots", None)
        need_layout = weapon_cleared = False
        for slot_key in map(lambda s: str(s or ""), slots):
            it = sel.get(slot_key)
            if it and it.get("InstanceGuid"):
                self._clear_stamp_for_instance(it["InstanceGuid"])
            sel.pop(slot_key, None)
            if mask is not None:
                mask.discard(slot_key)
            if slot_key == "costume":
                need_layout = True
                self._sil_original = self._sil_pm_m if self._gender == 1 else self._sil_pm_f
            elif slot_key == "weapon":
                weapon_cleared = True
            if hasattr(self, "_update_slot_icon"):
                self._update_slot_icon(slot_key)
            else:
                lbl = icons.get(slot_key)
                if lbl:
                    lbl.hide()
        if weapon_cleared:
            self._two_handed_equipped = False
        if need_layout:
            self._layout_overlays()
        self._update_offhand_overlay()
        self.refresh_stats_panel()

    def _equipment_condition_allows(self, equipment_ids: list[int], allowed_class_ids: list[int]) -> dict[int, bool]:
        """
        {Equipment_Id: allowed_bool} по EquipmentCondition:
          - нет строк по Equipment_Id -> True
          - иначе True если есть строка с Class_Id in allowed_class_ids
        """
        ids = [int(x) for x in (equipment_ids or []) if int(x) > 0]
        cls = {int(x) for x in (allowed_class_ids or []) if int(x) > 0}
        if not ids:
            return {}
        conn = getattr(getattr(self, "data", None), "conn", None)
        if conn is None or not cls:
            return {eid: True for eid in ids}
        ph = ",".join("?" * len(ids))
        rows = conn.execute(
            f'SELECT Equipment_Id, Class_Id FROM "EquipmentCondition" WHERE Equipment_Id IN ({ph})',
            ids
        ).fetchall()
        cond: dict[int, set[int]] = defaultdict(set)
        for r in rows:
            eq, cc = (r["Equipment_Id"], r["Class_Id"]) if hasattr(r, "keys") else (r[0], r[1])
            cond[int(eq)].add(int(cc))
        return {eid: (eid not in cond) or bool(cond[eid] & cls) for eid in ids}

    def _glow_rect_for(self, key: str, rect: QRect) -> QRect:
        if rect.isEmpty():
            return rect
        conf = EXTRA_ZONES.get(key)
        base_px = (conf.get("size") if conf else SLOT_PX)
        visual_px = (conf.get("glow_px", base_px) if conf else SLOT_VISUAL_PX)
        scale = (conf.get("glow_scale", 1.0) if conf else GLOW_SCALE)
        sx = rect.width() / float(base_px)
        target = int(visual_px * scale * sx)
        c = rect.center()
        r = QRect(0, 0, target, target)
        r.moveCenter(QPoint(c.x() + int(GLOW_SHIFT_X * sx), c.y() + int(GLOW_SHIFT_Y * sx)))
        return r.intersected(self._img_rect()) if GLOW_CLIP_TO_IMG else r

    def _select_background_by_class(self) -> None:
        self._bg_current = self._bg_spear if (self._bg_spear and self._spear_slot_visible()) else (
                    self._bg_default or self._bg_spear)
        self._update_design_base_from_original()

    def _update_board_pixmap(self) -> None:
        pm = self._bg_current
        if not pm:
            self.board_label.setPixmap(QPixmap())
            self.board_label.setGeometry(0, 0, self.width(), self.height())
            self._recalc_zones()
            return

        scaled = pm.scaled(self._base_w, self._base_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        board_w = int(scaled.width())
        board_h = int(scaled.height())

        outer_w = board_w
        outer_h = board_h

        other_open = bool(getattr(self, "_other_menu_open", False))
        other_pm = getattr(self, "_other_menu_pm", None)

        if other_open and other_pm is not None and not other_pm.isNull():
            sx = (board_w / float(self._base_w)) if self._base_w else 1.0
            menu_w = max(1, int(other_pm.width() * sx))
            menu_h = max(1, int(other_pm.height() * sx))
            overlap = int(OTHER_MENU_OVERLAP_PX * sx)

            outer_w = max(outer_w, board_w + menu_w - overlap)
            outer_h = max(outer_h, menu_h)

        self.board_label.setPixmap(scaled)
        self.board_label.setGeometry(0, 0, board_w, board_h)

        self.setFixedSize(int(outer_w), int(outer_h))

        self._recalc_zones()
        self.board_label.lower()

        for w in (
                self.silhouette_label,
                self.class_btn,
                self.gender_m_btn,
                self.gender_f_btn,
                self.hover_glow,
        ):
            try:
                w.raise_()
            except Exception:
                pass

    def _update_glow_from_global(self, *_args) -> None:
        # Если открыто окно/щит, MainWindow не должен показывать hover вообще.
        # Это фиксит ситуацию, когда StampWindow открыт, клики уже заблокированы,
        # но подсветка слотов экипировки продолжает появляться под окном.
        try:
            modal_hover_blocked = bool(
                getattr(self, "_block_main_input", False)
                or self._stamp_shield_active()
                or self._reforge_shield_active()
                or (
                        getattr(self, "_inv_shield", None) is not None
                        and getattr(self, "_inv_shield").isVisible()
                )
            )
        except Exception:
            modal_hover_blocked = bool(getattr(self, "_block_main_input", False))

        if modal_hover_blocked:
            for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
                try:
                    w = getattr(self, nm, None)
                    if w is not None:
                        w.hide()
                except Exception:
                    pass

            try:
                if getattr(self, "_glow_locked_key", None) is not None:
                    self._unlock_glow()
            except Exception:
                pass

            try:
                if getattr(self, "equip_info", None) is not None:
                    self.equip_info.hide()
            except Exception:
                pass

            return

        # Зоны могут меняться после layout/resize/open-close.
        # Поэтому перед hit-test держим их актуальными.
        try:
            self._recalc_zones()
        except Exception:
            pass

        try:
            gp = QCursor.pos()
            local_main = self.mapFromGlobal(gp)
        except Exception:
            self._hide_hover_name_label()
            return

        key, rect = self._hit_zone(local_main)

        if not key or not rect or rect.isEmpty():
            if getattr(self, "menu_glow", None) is not None:
                self.menu_glow.hide()
            if getattr(self, "hover_glow", None) is not None:
                self.hover_glow.hide()
            if getattr(self, "winbtn_hover", None) is not None:
                self.winbtn_hover.hide()

            self._hide_hover_name_label()
            return

        # Название наведённой зоны.
        self._show_hover_name_label(str(key), rect)

        if key in ("close", "minimize"):
            pm = self._close_hover_pm if key == "close" else self._min_hover_pm

            if pm and getattr(self, "winbtn_hover", None) is not None:
                self.winbtn_hover.setPixmap(pm)
                self.winbtn_hover.setGeometry(rect)
                self.winbtn_hover.show()
                self.winbtn_hover.raise_()
            elif getattr(self, "winbtn_hover", None) is not None:
                self.winbtn_hover.hide()

            if getattr(self, "menu_glow", None) is not None:
                self.menu_glow.hide()
            if getattr(self, "hover_glow", None) is not None:
                self.hover_glow.hide()

            try:
                self.hover_name_label.raise_()
            except Exception:
                pass

            return

        if key in MENU_KEYS:
            if getattr(self, "_menu_glow_pm", None) and getattr(self, "menu_glow", None) is not None:
                self.menu_glow.setPixmap(self._menu_glow_pm)
                self.menu_glow.setGeometry(rect)
                self.menu_glow.show()
                self.menu_glow.raise_()
            elif getattr(self, "menu_glow", None) is not None:
                self.menu_glow.hide()

            if getattr(self, "hover_glow", None) is not None:
                self.hover_glow.hide()
            if getattr(self, "winbtn_hover", None) is not None:
                self.winbtn_hover.hide()

            try:
                self.hover_name_label.raise_()
            except Exception:
                pass

            return

        if key in SLOT_POS:
            if getattr(self, "_glow_pm", None) and getattr(self, "hover_glow", None) is not None:
                glow_rect = self._glow_rect_for(key, rect)
                self.hover_glow.setPixmap(self._glow_pm)
                self.hover_glow.setGeometry(glow_rect)
                self.hover_glow.show()
                self.hover_glow.raise_()
            elif getattr(self, "hover_glow", None) is not None:
                self.hover_glow.hide()

            if getattr(self, "menu_glow", None) is not None:
                self.menu_glow.hide()
            if getattr(self, "winbtn_hover", None) is not None:
                self.winbtn_hover.hide()

            try:
                self.hover_name_label.raise_()
            except Exception:
                pass

            return

        # Остальные зоны: class/gender/extra_btn/total_menu/other_menu.
        # Для них показываем только инфо-борд с названием.
        if getattr(self, "menu_glow", None) is not None:
            self.menu_glow.hide()
        if getattr(self, "hover_glow", None) is not None:
            self.hover_glow.hide()
        if getattr(self, "winbtn_hover", None) is not None:
            self.winbtn_hover.hide()

        try:
            self.hover_name_label.raise_()
        except Exception:
            pass

    def _recalc_zones(self) -> None:
        pm = self.board_label.pixmap()
        if not pm:
            self._zones_screen = []
            return

        sx = pm.width() / float(self._base_w)
        ir = self._img_rect()
        zones: List[Tuple[str, QRect]] = []

        allow_spear = self._spear_slot_visible()
        other_opened = bool(getattr(self, "_other_menu_open", False))

        def _add_widget_zone(key: str, widget, fallback_rect: Optional[QRect] = None) -> None:
            rect = QRect()

            try:
                if widget is not None:
                    rect = QRect(widget.geometry())
            except Exception:
                rect = QRect()

            if (rect is None or rect.isNull() or rect.isEmpty()) and fallback_rect is not None:
                rect = QRect(fallback_rect)

            if rect is not None and not rect.isNull() and not rect.isEmpty():
                zones.append((str(key), QRect(rect)))

        # Слоты экипировки
        for key, (x, y) in SLOT_POS.items():
            if key == "spear" and not allow_spear:
                continue

            S = int(SLOT_PX * sx)
            zones.append((
                key,
                QRect(
                    int(ir.x() + x * sx),
                    int(ir.y() + y * sx),
                    S,
                    S,
                ),
            ))

        # Нижнее меню
        for b in MENU_BUTTONS:
            x0, y0, w0, h0 = b["rect"]
            zones.append((
                b["key"],
                QRect(
                    int(ir.x() + x0 * sx),
                    int(ir.y() + y0 * sx),
                    int(w0 * sx),
                    int(h0 * sx),
                ),
            ))

        # Свернуть / закрыть
        for key, conf in EXTRA_ZONES.items():
            x0, y0 = conf["pos"]
            S = int(conf["size"] * sx)
            zones.append((
                key,
                QRect(
                    int(ir.x() + x0 * sx),
                    int(ir.y() + y0 * sx),
                    S,
                    S,
                ),
            ))

        # Главное меню
        try:
            x0, y0, w0, h0 = TOTAL_MENU_BTN_RECT
            fallback = self._project(int(x0), int(y0), int(w0), int(h0))
            _add_widget_zone("total_menu", getattr(self, "total_menu_btn", None), fallback)
        except Exception:
            pass

        # Кнопка подсказок
        try:
            x0, y0, w0, h0 = HELP_MENU_BTN_RECT
            fallback = self._project(int(x0), int(y0), int(w0), int(h0))
            _add_widget_zone("helper_menu", getattr(self, "helper_menu_btn", None), fallback)
        except Exception:
            pass

        # Кнопки состояния / ивента / контроля
        try:
            btns = getattr(self, "small_menu_btns", {}) or {}
            for cfg in SMALL_MENU_BTNS:
                key = str(cfg.get("key") or "")
                if not key:
                    continue

                x0, y0 = cfg.get("pos", (0, 0))
                fallback = self._project(
                    int(x0),
                    int(y0),
                    int(SMALL_MENU_BTN_W),
                    int(SMALL_MENU_BTN_H),
                )

                _add_widget_zone(key, btns.get(key), fallback)
        except Exception:
            pass

        # Класс
        try:
            _add_widget_zone("class", getattr(self, "class_btn", None), None)
        except Exception:
            pass

        # Пол
        try:
            _add_widget_zone("gender_m", getattr(self, "gender_m_btn", None), None)
        except Exception:
            pass

        try:
            _add_widget_zone("gender_f", getattr(self, "gender_f_btn", None), None)
        except Exception:
            pass

        # Прочее
        try:
            bx, by, bw, bh = OTHER_MENU_OPEN_BTN_RECT
            fallback = self._project(int(bx), int(by), int(bw), int(bh))
            _add_widget_zone("other_menu_open", getattr(self, "other_menu_open_btn", None), fallback)
        except Exception:
            pass

        try:
            if other_opened:
                _add_widget_zone("other_menu_close", getattr(self, "other_menu_close_btn", None), None)
        except Exception:
            pass

        self._zones_screen = zones

    def _is_global_pos_over_inventory_window(self, gp: QPoint) -> bool:
        """
        True, если глобальная позиция мыши находится поверх открытого окна инвентаря.

        Нужно для Linux/Wayland: из-за прозрачного top-level окна инвентаря
        hover иногда проходит в MainWindow под ним.
        """
        inv = getattr(self, "inventory_window", None)

        if not isinstance(inv, QWidget):
            return False

        try:
            if not inv.isVisible():
                return False
        except Exception:
            return False

        try:
            geo = inv.frameGeometry()
            if geo.isValid() and geo.contains(gp):
                return True
        except Exception:
            pass

        try:
            top_left = inv.mapToGlobal(QPoint(0, 0))
            rect = QRect(top_left, inv.size())
            return rect.contains(gp)
        except Exception:
            return False

    def _hit_zone(self, p_in_window: QPoint):
        # Linux/Wayland:
        # если InventoryWindow открыт поверх MainWindow, hover главного окна
        # не должен срабатывать под ним.
        try:
            gp = self.mapToGlobal(p_in_window)
            if self._is_global_pos_over_inventory_window(gp):
                return None, None
        except Exception:
            pass

        other_opened = bool(getattr(self, "_other_menu_open", False))

        # Если Прочее открыто, область правого меню не должна пробивать
        # hover-зоны главного окна под собой.
        if other_opened:
            try:
                bg = getattr(self, "other_menu_bg", None)
                close_btn = getattr(self, "other_menu_close_btn", None)

                if bg is not None and bg.isVisible() and bg.geometry().contains(p_in_window):
                    if close_btn is not None and close_btn.isVisible() and close_btn.geometry().contains(p_in_window):
                        return "other_menu_close", QRect(close_btn.geometry())

                    return None, None
            except Exception:
                pass

        for key, r in self._zones_screen:
            if key == "other_menu_open" and other_opened:
                continue

            if key == "other_menu_close" and not other_opened:
                continue

            if r.contains(p_in_window):
                return key, r

        return None, None

    def _zone_rect(self, key: str) -> Optional[QRect]:
        for k, r in self._zones_screen:
            if k == key:
                return r
        return None

    def _hover_name_for_key(self, key: str) -> str:
        key = str(key or "").strip()

        if not key:
            return ""

        # Для класса можно показывать выбранный класс, а не просто слово "Класс".
        if key == "class":
            try:
                class_name = str(self.class_combo.currentText() or "").strip()
                if class_name:
                    return f"Класс: {class_name}"
            except Exception:
                pass

        return str(HOVER_NAME_TEXT_BY_KEY.get(key, "") or "")

    def _hide_hover_name_label(self) -> None:
        try:
            lbl = getattr(self, "hover_name_label", None)
            if lbl is not None:
                lbl.hide()
        except Exception:
            pass

    def _show_hover_name_label(self, key: str, anchor_rect: QRect) -> None:
        lbl = getattr(self, "hover_name_label", None)
        if lbl is None:
            return

        key = str(key or "").strip()
        text = self._hover_name_for_key(key)

        if not text:
            self._hide_hover_name_label()
            return

        if anchor_rect is None or anchor_rect.isEmpty():
            self._hide_hover_name_label()
            return

        try:
            sx = self._scale()
        except Exception:
            sx = 1.0

        try:
            pt = max(8, min(12, int(round(9 * sx))))
            if hasattr(lbl, "set_point_size"):
                lbl.set_point_size(pt)
            else:
                f = lbl.font()
                f.setPointSize(pt)
                lbl.setFont(f)
        except Exception:
            pass

        max_w = max(90, int(HOVER_NAME_LABEL_MAX_W * max(0.75, sx)))

        try:
            if hasattr(lbl, "set_text"):
                lbl.set_text(text, max_w=max_w)
            else:
                lbl.setText(text)
                lbl.adjustSize()
        except Exception:
            try:
                lbl.setText(text)
                lbl.adjustSize()
            except Exception:
                self._hide_hover_name_label()
                return

        gap = max(4, int(5 * sx))

        img_r = self._img_rect()
        bounds = self.rect()
        if not img_r.isEmpty():
            bounds = bounds.united(img_r)

        def _clamp_x(v: int) -> int:
            return max(bounds.left() + 2, min(int(v), bounds.right() - lbl.width() - 2))

        def _clamp_y(v: int) -> int:
            return max(bounds.top() + 2, min(int(v), bounds.bottom() - lbl.height() - 2))

        # По умолчанию — над областью.
        x = int(anchor_rect.center().x() - lbl.width() / 2)
        y = int(anchor_rect.top() - lbl.height() - gap)

        # Маленькие верхние кнопки лучше показывать снизу,
        # иначе плашка упирается в верхнюю границу и выглядит криво.
        if key in ("extra_btn1", "extra_btn2", "extra_btn3", "total_menu", "close", "minimize"):
            x = int(anchor_rect.center().x() - lbl.width() / 2)
            y = int(anchor_rect.bottom() + gap)

        # Класс/пол — компактно сверху, если сверху не хватает места, уйдёт вниз.
        elif key in ("class", "gender_m", "gender_f"):
            x = int(anchor_rect.center().x() - lbl.width() / 2)
            y = int(anchor_rect.top() - lbl.height() - gap)
            if y < bounds.top() + 2:
                y = int(anchor_rect.bottom() + gap)

        # Вертикальную кнопку "Прочее" лучше показывать слева от кнопки,
        # а не над ней.
        elif key == "other_menu_open":
            x = int(anchor_rect.left() - lbl.width() - gap)
            y = int(anchor_rect.center().y() - lbl.height() / 2)

            if x < bounds.left() + 2:
                x = int(anchor_rect.right() + gap)

        elif key == "other_menu_close":
            x = int(anchor_rect.right() + gap)
            y = int(anchor_rect.center().y() - lbl.height() / 2)

            if x + lbl.width() > bounds.right() - 2:
                x = int(anchor_rect.left() - lbl.width() - gap)

        else:
            if y < bounds.top() + 2:
                y = int(anchor_rect.bottom() + gap)

        x = _clamp_x(x)
        y = _clamp_y(y)

        lbl.move(int(x), int(y))
        lbl.show()
        lbl.raise_()

    # ---------- оверлеи ----------
    def _layout_overlays(self) -> None:
        self._ensure_other_menu_ui()

        r = self._img_rect()

        # позиция кнопки класса (по центру иконки)
        self._move_class_icon_by_icon_center(
            r.x() + r.width() // 2 + int(CLASS_ICON_OFFSET[0]),
            r.y() + r.height() + int(CLASS_ICON_OFFSET[1]),
        )

        if r.isEmpty():
            return

        # силуэт (влезает до кнопки класса)
        top = r.y()
        bottom_limit = self.class_btn.y() - 8
        max_h = max(0, min(r.height(), bottom_limit - top))

        if self._sil_original and max_h > 0:
            base = self._sil_original.scaled(QSize(r.width(), max_h), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            sil = self._sil_original.scaled(
                QSize(max(1, int(base.width() * SIL_SCALE)), max(1, int(base.height() * SIL_SCALE))),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            x = r.x() + (r.width() - sil.width()) // 2 + int(SIL_OFFSET[0])
            y = top + (max_h - sil.height()) // 2 + int(SIL_OFFSET[1])

            lbl = self.silhouette_label
            lbl.setPixmap(sil)
            lbl.setAttribute(Qt.WA_TranslucentBackground, True)
            lbl.setStyleSheet("background: transparent;")
            lbl.setGeometry(x, y, sil.width(), sil.height())

            sil_r = lbl.geometry()
            if not sil_r.isEmpty():
                self.level_spin.move(
                    sil_r.center().x() - self.level_spin.width() // 2,
                    max(r.y() + 6, sil_r.top() - self.level_spin.height() - 6),
                )
                self.level_spin.show()
                self.level_spin.raise_()
                self.level_wheel.raise_()
                self.level_wheel.relocate_over_spin()
                self.level_wheel.show()

        # кнопки пола
        self._place_gender_buttons()

        # плашка "Свободные очки"
        upw = getattr(self, "unspent_points_widget", None)
        if upw:
            upw.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            if "layout_unspent_param_points_widget" in globals():
                layout_unspent_param_points_widget(upw, img_rect=r, scale=self._scale())
            upw.show()

        # stats_panel (создание)
        if getattr(self, "stats_panel", None) is None:
            try:
                self.stats_panel = CharacteristicsPanel(self, conn=self.data.conn, param_state=self.param_points)
            except TypeError:
                self.stats_panel = CharacteristicsPanel(self, conn=self.data.conn)

        sp = getattr(self, "stats_panel", None)
        if upw and sp:
            upw.stackUnder(sp)

        # reset-обёртки старого варианта прячем
        if hasattr(self, "reset_wrap"):
            self.reset_wrap.hide()

        # reset кнопка
        if not hasattr(self, "btn_reset_params"):
            btn = self.btn_reset_params = QToolButton(self)
            btn.setObjectName("resetParamsBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setAutoRaise(True)
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
            btn.setStyleSheet("""
                QToolButton#resetParamsBtn { background: transparent; border: none; padding: 0px; }
                QToolButton#resetParamsBtn:hover { background: transparent; }
                QToolButton#resetParamsBtn:pressed { padding-right: 1px; padding-down: 1px; }
            """)
            img_path = _resolve_resource(r"resources/main_menu/char_reset.png") or r"resources/main_menu/char_reset.png"
            pm = QPixmap(img_path)
            if not pm.isNull():
                btn.setIcon(QIcon(pm))
            btn.clicked.connect(self._on_param_reset_clicked)
            btn.hide()

        # подписки на смену вкладок панели
        if sp and not getattr(self, "_reset_btn_wired", False):
            def _cu(sig, slot):
                try:
                    sig.connect(slot, Qt.ConnectionType.UniqueConnection)
                except TypeError:
                    sig.connect(slot)
                except RuntimeError:
                    pass

            _cu(sp.btn_group_main.clicked, self._layout_reset_button)
            _cu(sp.btn_group_extra.clicked, self._layout_reset_button)
            _cu(sp.btn_group_other.clicked, self._layout_reset_button)
            self._reset_btn_wired = True

        # позиционирование stats_panel + коннекты параметров
        if sp:
            sp.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            sp.setEnabled(True)
            sp.setMouseTracking(True)

            fn = getattr(sp, "set_param_state", None)
            if callable(fn):
                fn(self.param_points)

            x0, y0, w0, h0 = STATS_RECT
            sx = self._scale()
            sp.setGeometry(int(r.x() + x0 * sx), int(r.y() + y0 * sx), int(w0 * sx), int(h0 * sx))
            sp.show()
            sp.raise_()

            def _cu(sig, slot):
                try:
                    sig.connect(slot, Qt.ConnectionType.UniqueConnection)
                except TypeError:
                    sig.connect(slot)
                except RuntimeError:
                    pass

            if hasattr(sp, "paramPlusClicked"):
                _cu(sp.paramPlusClicked, self._on_param_plus_clicked)
            if hasattr(sp, "paramMinusClicked"):
                _cu(sp.paramMinusClicked, self._on_param_minus_clicked)
            if hasattr(sp, "paramPlusAllClicked"):
                _cu(sp.paramPlusAllClicked, self._on_param_plus_all_clicked)
            if hasattr(sp, "paramResetClicked"):
                _cu(sp.paramResetClicked, self._on_param_reset_clicked)

        # базовый порядок слоёв
        self.board_label.lower()
        self.silhouette_label.raise_()
        self.class_btn.raise_()
        self.gender_m_btn.raise_()
        self.gender_f_btn.raise_()
        self.hover_glow.raise_()

        # кнопки окна / меню
        self.close_btn.move(r.right() - self.close_btn.width() - 8, r.top() + 8)
        self.close_btn.raise_()

        self._place_close_btn()
        self._place_minimize_btn()
        self._place_menu_buttons()
        self._place_small_menu_buttons()

        try:
            btn = getattr(self, "total_menu_btn", None)
            if btn is not None:
                btn.raise_()
        except Exception:
            pass

        for b in (getattr(self, "small_menu_btns", {}) or {}).values():
            b.raise_()

        self._layout_event_selector_ui()

        for btn in self.menu_btns.values():
            btn.raise_()

        self.menu_glow.raise_()
        self.hover_glow.raise_()

        # новая правая менюшка
        self._layout_other_menu()

        # системные кнопки и их hover обязаны быть ПОВЕРХ новой менюшки
        self.close_btn.raise_()
        self.minimize_btn.raise_()
        self.winbtn_hover.raise_()

        # иконки предметов
        for key in SLOT_POS.keys():
            self._update_slot_icon(key)

        # reset-кнопку позиционируем ПОСЛЕ stats_panel.raise_()
        self._layout_reset_button()

        try:
            self._raise_active_modal_layer()
        except Exception:
            pass

    def _on_param_reset_clicked(self) -> None:
        st = getattr(self, "param_points", None)
        if not st:
            return
        for name in ("reset", "reset_allocations", "reset_allocated", "clear_allocations", "clear"):
            fn = getattr(st, name, None)
            if callable(fn):
                fn()
                self.refresh_stats_panel()
                return
        alloc = next(
            (getattr(st, a) for a in ("allocated", "_allocated", "allocations", "spent", "spent_by_stat", "by_stat")
             if isinstance(getattr(st, a, None), dict) and getattr(st, a)),
            None,
        ) or next(
            (getattr(st, m)() for m in ("get_allocations", "get_allocated", "alloc_map", "as_allocations")
             if callable(getattr(st, m, None)) and isinstance(getattr(st, m)(), dict) and getattr(st, m)()),
            None,
        )

        if alloc and callable(getattr(st, "refund", None)):
            for k, v in list(alloc.items()):
                if str(v).isdigit() and str(k).lstrip("-").isdigit():
                    amt = int(v)
                    if amt > 0:
                        st.refund(int(k), amt)

        self.refresh_stats_panel()

    def _on_param_plus_clicked(self, stat_id: int) -> None:
        if getattr(self.param_points, "spend", None) and self.param_points.spend(int(stat_id), 1):
            self.refresh_stats_panel()

    def _on_param_minus_clicked(self, stat_id: int) -> None:
        if getattr(self.param_points, "refund", None) and self.param_points.refund(int(stat_id), 1):
            self.refresh_stats_panel()

    def _on_param_plus_all_clicked(self, stat_id: int) -> None:
        if getattr(self.param_points, "spend_all", None) and self.param_points.spend_all(int(stat_id)):
            self.refresh_stats_panel()

    def _frame_style_for(self, obj_name: str, active: bool, border_w: int, pad: int) -> str:
        top_l, bot_r = ("#f6e8b2", "#7b5c12") if active else ("#cfcfcf", "#5a5a5a")
        hover = "" if active else f"""
    QToolButton#{obj_name}:hover {{
      border-top-color: #e0e0e0;
      border-left-color: #e0e0e0;
      border-right-color: #6a6a6a;
      border-bottom-color: #6a6a6a;
    }}"""
        return f"""
    QToolButton#{obj_name} {{
      background-color: transparent;
      border: {border_w}px solid {GOLD if active else "#8c8c8c"};
      border-top-color: {top_l};
      border-left-color: {top_l};
      border-right-color: {bot_r};
      border-bottom-color: {bot_r};
      border-radius: 6px;
      padding: {pad}px;
    }}{hover}"""

    def _move_class_icon_by_icon_center(self, center_x: int, bottom_y: int) -> None:
        self.class_btn.move(int(center_x - self.class_btn.width() / 2), int(bottom_y - self.class_btn.height()))

    def _place_gender_buttons(self) -> None:
        for btn, pos, off in (
                (self.gender_m_btn, GENDER_M_POS, GENDER_M_OFFSET),
                (self.gender_f_btn, GENDER_F_POS, GENDER_F_OFFSET),
        ):
            self._move_gender_btn(btn, pos, off)
            btn.show()
            btn.raise_()

    def _move_gender_btn(self, btn: QToolButton, design_xy: Tuple[int, int],
                         offset_xy: Tuple[int, int] = (0, 0)) -> None:
        tl = self._project(design_xy[0], design_xy[1], 0, 0).topLeft()
        sx = self._scale()
        dx, dy = offset_xy
        btn.move(tl.x() + int(dx * sx), tl.y() + int(dy * sx))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._update_board_pixmap()
        self._layout_overlays()
        for sh in (getattr(self, "_stamp_shield", None), getattr(self, "_reforge_shield", None)):
            if sh and sh.isVisible():
                sh.setGeometry(self.rect())

    # ---------- класс / фон ----------
    def _apply_current_class_icon(self) -> None:
        idx = self.class_combo.currentIndex()
        if idx < 0:
            self.class_btn.setIcon(QIcon())
            return
        cid = self.class_combo.itemData(idx)
        pm = next((pm for _cid, _name, pm in self._classes if _cid == cid and pm), None)
        if pm:
            pm = pm.scaled(CLASS_ICON_PX, CLASS_ICON_PX, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.class_btn.setIcon(QIcon(pm))

    def _on_class_icon_click(self, _checked: bool = False) -> None:
        self._set_class_icon_active(True)
        menu = getattr(self, "class_menu", None)
        if menu is None:
            self._build_class_menu()
            menu = getattr(self, "class_menu", None)
            if menu is None:
                return
        anchor = self.class_btn
        hint = menu.sizeHint()
        mw, mh = hint.width(), hint.height()
        gp = anchor.mapToGlobal(QPoint((anchor.width() - mw) // 2, -mh - 8))
        scr = self.window().screen().availableGeometry()
        x = max(scr.left() + 8, min(gp.x(), scr.right() - mw - 8))
        y = max(scr.top() + 8, min(gp.y(), scr.bottom() - mh - 8))
        menu.popup(QPoint(x, y))

    def _on_class_combo_changed(self, _i: int) -> None:
        for fn in (
                self._apply_current_class_icon,
                self._select_background_by_class,
                self._update_board_pixmap,
                self._apply_current_gender_icons,
                self._update_gender_styles,
                self._layout_overlays,
                self._apply_class_border_for_current,
        ):
            fn()

        self._drop_invalid_equipment_for_new_class()
        self._last_class_bucket = self._class_bucket_from_name(self.class_combo.currentText())
        self._apply_level_rules_for_current_class()
        self._sync_inventory_context()
        self._coerce_inventory_to_class()
        self._update_offhand_overlay()
        self._sync_buff_debuff_menu_context()
        try:
            self._sync_talents_menu_class_context()
        except Exception:
            pass

        self.refresh_stats_panel()

    def _coerce_inventory_to_class(self) -> None:
        inv = getattr(self, "inventory_window", None)
        class_ids = self._compatible_class_ids_for_current() if inv else None
        if not class_ids:
            return
        def allowed(it: dict) -> bool:
            if not isinstance(it, dict):
                return True
            eid = _safe_int(it.get("Id") or it.get("Equip_Id"), 0)
            return eid <= 0 or self._equipment_allowed_for_class(eid, class_ids)
        touched = False
        for a in ("items", "_items", "_inventory_items", "inventory_items"):
            lst = getattr(inv, a, None)
            if isinstance(lst, list):
                before = len(lst)
                lst[:] = [x for x in lst if (not x) or allowed(x)]
                touched = len(lst) != before
                break
        if not touched:
            for a in ("cells", "_cells", "_grid", "_grid_cells", "grid_cells"):
                d = getattr(inv, a, None)
                if isinstance(d, dict):
                    for k, x in list(d.items()):
                        if x and not allowed(x):
                            d.pop(k, None)
                    touched = True
                    break
        for m in (
        "apply_filters", "rebuild", "rebuild_grid", "refresh_grid", "update_grid", "refresh", "update", "repaint"):
            fn = getattr(inv, m, None)
            if callable(fn):
                fn()

    def _is_two_handed(self, it: dict | None) -> bool:
        return self._weapon_is_two_handed(it)

    def _weapon_is_two_handed(self, it: dict | None) -> bool:
        return bool(it) and ("IsSingleHandWeapon" in it) and (_safe_int(it.get("IsSingleHandWeapon"), 1) == 0)

    def _hide_equip_tip_if_outside(self, icon_obj) -> None:
        ei = getattr(self, "equip_info", None)
        if not ei or not ei.isVisible():
            return
        icon_rect = QRect(icon_obj.mapToGlobal(icon_obj.rect().topLeft()), icon_obj.rect().size()).adjusted(-24, -24,                                                                                                24, 24)
        united = icon_rect.united(ei.frameGeometry().adjusted(-6, -6, 6, 6))
        if not united.contains(QCursor.pos()):
            ei.hide()

    def _slot_title(self, key: str) -> str:
        return {
            "head": "Головной убор",
            "mask": "Аксессуар для лица",
            "armor": "Броня",
            "gloves": "Перчатки",
            "legs": "Поножи",
            "boots": "Обувь",
            "weapon": "Оружие",
            "spear": "Копьё",
            "costume": "Костюм",
            "mount": "Ездовой питомец",
            "offhand": "Щит/Орб/Оружие (левая рука)",
            "ornament": "Украшение",
            "amulet": "Амулет",
            "ring1": "Кольцо 1",
            "ring2": "Кольцо 2",
            "totem": "Тотем",
            "artifact": "Артефакт",
        }.get(key, key)

    def _items_menu_size_hint(self, slot_key: str) -> QSize:
        # ВАЖНО:
        # позиция меню в _open_equip_menu_async завязана на hint.height().
        # Для costume/mount заголовок длиннее -> QMenu.sizeHint() другой -> меню смещается иначе.
        # Поэтому для этих слотов считаем hint как для обычного слота (weapon).

        slot_key = str(slot_key or "").strip()
        if slot_key in ("costume", "mount"):
            slot_key = "weapon"

        m = QMenu(self)
        t = self._slot_title(slot_key)
        m.addSection(t)
        for i in range(1, 6):
            m.addAction(f"{t}: вариант {i}")
        m.addSeparator()
        m.addAction("Очистить слот")
        hint = m.sizeHint()
        m.deleteLater()
        return hint

    # ---------- выбор / очистка ----------
    def _on_pick_equipment(self, slot_key: str, item: dict) -> None:
        slot_key = str(slot_key or "").strip()
        if not slot_key or not item:
            return

        src = dict(self._ensure_instance_guid(item) or item)

        # ✅ weapon выбран и он двуручный при занятом offhand -> offhand переносим в инвентарь (не удаляем)
        if slot_key == "weapon":
            try:
                if self._weapon_is_two_handed(src):
                    off_it = (self._selected_items or {}).get("offhand")
                    if off_it:
                        if not self._move_slot_item_to_inventory("offhand"):
                            return
            except Exception:
                pass

        # offhand выбран при двуручке -> двуручку переносим в инвентарь (не удаляем)
        if slot_key == "offhand":
            weapon = (self._selected_items or {}).get("weapon")
            if weapon and self._weapon_is_two_handed(weapon):
                self._block_weapon_clear_for_offhand_menu = False
                if not self._move_slot_item_to_inventory("weapon"):
                    return

        prev = (self._selected_items or {}).get(slot_key)

        # --- чистим штамп+эликсир у ПРЕДЫДУЩЕГО инстанса (он исчезает при замене из меню) ---
        if isinstance(prev, dict):
            inst_prev = prev.get("InstanceGuid")
            if inst_prev:
                try:
                    self._clear_stamp_for_instance(inst_prev)
                except Exception:
                    pass
                try:
                    cache = getattr(self, "_applied_elixirs", None)
                    if isinstance(cache, dict):
                        cache.pop(str(inst_prev), None)
                except Exception:
                    pass

        # --- эликсир для НОВОГО предмета: вшиваем inline, чтобы math сразу учитывал ---
        ELX_BASE = 9000
        ELX_LIM = 9100

        def _clear_elixir_inline(d: dict) -> None:
            if not isinstance(d, dict):
                return
            for kk in list(d.keys()):
                if not isinstance(kk, str):
                    continue
                suf = None
                if kk.startswith("BonusType"):
                    suf = kk[len("BonusType"):]
                elif kk.startswith("Var"):
                    suf = kk[len("Var"):]
                elif kk.startswith("Value"):
                    suf = kk[len("Value"):]
                if suf is None:
                    continue
                try:
                    idx = int(suf)
                except Exception:
                    continue
                if ELX_BASE <= idx < ELX_LIM:
                    d.pop(kk, None)

        inst_new = str(src.get("InstanceGuid") or "").strip()
        el_payload = None

        el = src.get("Elixir") or src.get("_elixir")
        if isinstance(el, dict) and _safe_int(el.get("Id") or el.get("id"), 0) > 0:
            el_payload = dict(el)
            el_payload["Id"] = _safe_int(el_payload.get("Id") or el_payload.get("id"), 0)
            el_payload["Name"] = str(el_payload.get("Name") or el_payload.get("name") or "")
            if "Bonuses" not in el_payload:
                el_payload["Bonuses"] = list(el_payload.get("bonuses") or [])
        else:
            cache = getattr(self, "_applied_elixirs", None)
            if isinstance(cache, dict) and inst_new and isinstance(cache.get(inst_new), dict):
                rec = cache.get(inst_new) or {}
                eid = _safe_int(rec.get("id") or rec.get("Id"), 0)
                if eid > 0:
                    el_payload = {
                        "Id": eid,
                        "Name": str(rec.get("name") or rec.get("Name") or ""),
                        "Image_Id": rec.get("image_id") if rec.get("image_id") is not None else rec.get("Image_Id"),
                        "Bonuses": list(rec.get("bonuses") or rec.get("Bonuses") or []),
                    }

        if isinstance(el_payload, dict) and _safe_int(el_payload.get("Id"), 0) > 0:
            # если бонусов нет — доберём из БД
            if not isinstance(el_payload.get("Bonuses"), list) or not el_payload.get("Bonuses"):
                conn = getattr(getattr(self, "data", None), "conn", None)
                if conn is not None:
                    try:
                        from .equipment_elixir import get_elixir_bonuses, get_elixir_meta
                        meta = get_elixir_meta(conn, int(el_payload["Id"])) or {}
                        if not el_payload.get("Name"):
                            el_payload["Name"] = str(meta.get("Name") or "")
                        if el_payload.get("Image_Id") is None:
                            el_payload["Image_Id"] = meta.get("Image_Id")
                        el_payload["Bonuses"] = list(get_elixir_bonuses(conn, int(el_payload["Id"])) or [])
                    except Exception:
                        pass

            _clear_elixir_inline(src)
            src.pop("_elixir", None)
            src["Elixir"] = {
                "Id": _safe_int(el_payload.get("Id"), 0),
                "Name": str(el_payload.get("Name") or ""),
                "Image_Id": el_payload.get("Image_Id"),
                "Bonuses": list(el_payload.get("Bonuses") or []),
            }

            # inline
            try:
                bonuses_sorted = sorted(
                    [b for b in (src["Elixir"]["Bonuses"] or []) if isinstance(b, dict)],
                    key=lambda b: _safe_int(b.get("OrderIndex"), 0),
                )
            except Exception:
                bonuses_sorted = [b for b in (src["Elixir"]["Bonuses"] or []) if isinstance(b, dict)]

            i = 0
            for b in bonuses_sorted:
                idx = ELX_BASE + i
                if idx >= ELX_LIM:
                    break
                bt = _safe_int(b.get("Type_Id"), 0)
                val = _safe_int(b.get("Value"), 0)
                if bt > 0 and val != 0:
                    src[f"BonusType{idx}"] = int(bt)
                    src[f"Var{idx}"] = int(val)
                i += 1

            # прогреем кэш, чтобы меню "Убрать/Добавить" знало текущее состояние
            if inst_new:
                cache = getattr(self, "_applied_elixirs", None)
                if not isinstance(cache, dict):
                    cache = {}
                    self._applied_elixirs = cache
                cache[inst_new] = {
                    "id": _safe_int(src["Elixir"]["Id"], 0),
                    "name": src["Elixir"]["Name"] or "",
                    "image_id": src["Elixir"].get("Image_Id"),
                    "bonuses": list(src["Elixir"].get("Bonuses") or []),
                }

        try:
            self.equip_item_in_slot(slot_key, src, prev_item=prev)
        except Exception:
            if not isinstance(getattr(self, "_selected_items", None), dict):
                self._selected_items = {}
            self._selected_items[slot_key] = dict(src)
            self._update_slot_icon(slot_key)

        if slot_key == "weapon":
            self._two_handed_equipped = bool(self._weapon_is_two_handed(src))

        if slot_key in ("weapon", "offhand") and hasattr(self, "_update_offhand_overlay"):
            self._update_offhand_overlay(refresh_icon=(slot_key == "weapon"))

        # --- costume: обновляем силуэт персонажа (не слот), затем делаем layout ---
        if slot_key == "costume" and hasattr(self, "_layout_overlays"):
            try:
                sil_id = 0
                if isinstance(src, dict):
                    if "Icon_Image_Id" in src:
                        sil_id = _safe_int(src.get("Image_Id"), 0)
                    if sil_id <= 0:
                        sil_id = _safe_int(src.get("CostumeImage_Id"), 0)
                    if sil_id <= 0:
                        sil_id = _safe_int(src.get("Image_Id"), 0)

                    if sil_id <= 0:
                        eid = 0
                        for k in ("Equipment_Id", "Equip_Id", "TemplateId", "Template_Id", "Item_Id", "Id"):
                            eid = _safe_int(src.get(k), 0)
                            if eid > 0:
                                break

                        if eid > 0:
                            conn = getattr(getattr(self, "data", None), "conn", None)
                            if conn is not None:
                                try:
                                    row = conn.execute(
                                        "SELECT CostumeImage_Id FROM Equipment WHERE Id=? LIMIT 1",
                                        (int(eid),),
                                    ).fetchone()
                                except Exception:
                                    row = None
                                if row:
                                    try:
                                        sil_id = _safe_int(row["CostumeImage_Id"] if hasattr(row, "keys") else row[0],
                                                           0)
                                    except Exception:
                                        pass

                pm = self._get_image_pm(int(sil_id)) if int(sil_id) > 0 else None
                if pm is not None:
                    self._sil_original = pm
                else:
                    g = int(getattr(self, "_gender", 1) or 1)
                    self._sil_original = self._sil_pm_m if g == 1 else self._sil_pm_f
            except Exception:
                pass

            self._layout_overlays()

        self.refresh_stats_panel()
        ei = getattr(self, "equip_info", None)
        if ei and ei.isVisible():
            ei.hide()

    def _on_clear_equipment(self, slot_key: str) -> None:
        slot_key = str(slot_key or "").strip()
        if not slot_key:
            return
        # offhand-меню при двуручке не должно очищать weapon
        if slot_key == "weapon" and bool(getattr(self, "_block_weapon_clear_for_offhand_menu", False)):
            return

        sel = getattr(self, "_selected_items", None)
        if not isinstance(sel, dict):
            sel = self._selected_items = {}

        it = sel.get(slot_key)
        if isinstance(it, dict):
            inst = it.get("InstanceGuid")
            if inst:
                # stamp
                try:
                    self._clear_stamp_for_instance(inst)
                except Exception:
                    pass
                inv = getattr(self, "inventory_window", None)
                if inv and hasattr(inv, "inv_clear_stamp_for_instance"):
                    try:
                        inv.inv_clear_stamp_for_instance(inst)
                    except Exception:
                        pass

                # elixir
                try:
                    cache = getattr(self, "_applied_elixirs", None)
                    if isinstance(cache, dict):
                        cache.pop(str(inst), None)
                except Exception:
                    pass

        sel.pop(slot_key, None)

        mask = getattr(self, "_mask_stamp_slots", None)
        if mask is not None:
            mask.discard(slot_key)

        if slot_key == "weapon":
            self._two_handed_equipped = False

        if slot_key == "costume":
            self._sil_original = self._sil_pm_m if self._gender == 1 else self._sil_pm_f
            if hasattr(self, "_layout_overlays"):
                self._layout_overlays()

        self._update_slot_icon(slot_key)

        if hasattr(self, "_update_offhand_overlay"):
            self._update_offhand_overlay()

        if hasattr(self, "_call_many"):
            self._call_many(
                (
                    "refresh_equipment",
                    "_refresh_equipment_ui",
                    "rebuild_equipment",
                    "update_equipment_ui",
                    "recalc_stats",
                    "update_stats",
                    "on_equipment_changed",
                ),
                arg=slot_key,
            )

        self.refresh_stats_panel()
        ei = getattr(self, "equip_info", None)
        if ei and ei.isVisible():
            ei.hide()

    def _apply_current_gender_icons(self) -> None:
        man_path, wom_path = (GENDER_BEFORE20_M, GENDER_BEFORE20_F) if self._is_before20_class() else (
        GENDER_AFTER20_M, GENDER_AFTER20_F)
        man_pm, wom_pm = _load_file_image(man_path), _load_file_image(wom_path)
        sz = QSize(GENDER_ICON_PX, GENDER_ICON_PX)
        for btn, pm in ((self.gender_m_btn, man_pm), (self.gender_f_btn, wom_pm)):
            btn.setIcon(QIcon(pm) if pm else QIcon())
            btn.setIconSize(sz)
            btn.update()

    def _update_gender_styles(self) -> None:
        for btn, key, active in (
                (self.gender_m_btn, "genderBtnM", self._gender == 1),
                (self.gender_f_btn, "genderBtnF", self._gender == 2),
        ):
            pad = self._pad_for_icon_button(btn, GENDER_ICON_PX, GENDER_BORDER_W)
            btn.setStyleSheet(self._frame_style_for(key, active, GENDER_BORDER_W, pad))

    def _set_gender(self, g: int) -> None:
        try:
            g = int(g)
        except Exception:
            return

        if g not in (1, 2) or g == self._gender:
            return

        self._gender = g
        self._sil_original = self._sil_pm_m if g == 1 else self._sil_pm_f

        try:
            self.costume_ctrl.on_gender_changed(g)
        except Exception:
            pass

        # Экипировка на персонаже.
        self._drop_invalid_equipment_for_gender()

        self._update_gender_styles()
        self._layout_overlays()
        self._update_offhand_overlay()

        # Инвентарь.
        self._sync_inventory_context()
        self._drop_invalid_inventory_for_new_class()

        try:
            self._update_board_pixmap()
        except Exception:
            pass

        try:
            self.refresh_stats_panel()
        except Exception:
            pass

    def _current_class_id(self) -> Optional[int]:
        idx = self.class_combo.currentIndex()
        return self.class_combo.itemData(idx) if idx >= 0 else None

    ##########################
    ### Улучшение предмета ###
    ##########################
    def _pick_item_for_reforge(self) -> Optional[dict]:
        sel = getattr(self, "_selected_items", None) or {}
        return sel.get("weapon") or next((v for v in sel.values() if v), None)

    def _on_menu_reforge_clicked(self) -> None:
        uw = getattr(self, "upgrade_win", None)
        if uw is None:
            return
        # если уже открыто — закрываем
        if uw.isVisible():
            uw.hide()
            return
        # один раз поставим фильтр на само окно рефоржа, чтобы ловить Hide/Show
        if not getattr(self, "_reforge_evfilter_installed", False):
            uw.installEventFilter(self)
            self._reforge_evfilter_installed = True
        self._ensure_reforge_shield()
        # показать по центру (если есть метод) или просто show()
        if hasattr(uw, "open_centered"):
            uw.open_centered(self)
        else:
            uw.show()
        uw.raise_()
        uw.activateWindow()
        # если рефорж в том же parent, щит держим под ним
        if getattr(self, "_reforge_shield", None) is not None:
            self._reforge_shield.stackUnder(uw)

    def _on_reforge_closed(self) -> None:
        self._remove_reforge_shield()
        # на выходе — обновим ховер (если курсор над слотом)
        if hasattr(self, "_refresh_hover_after_modal"):
            self._refresh_hover_after_modal()

    def _on_reforge_requested(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return

        item = payload.get("item")
        if not isinstance(item, dict):
            return

        def _toi(v, d=0):
            try:
                return int(v)
            except Exception:
                return d

        slot_key = payload.get("slot_key")
        if not slot_key:
            item_id = _toi(item.get("Id") or item.get("Equip_Id") or 0)
            slot_key = self._slot_key_of_item_id(item_id) if item_id else None
        if not slot_key:
            return

        slot_key = str(slot_key)
        prev = (self._selected_items or {}).get(slot_key)

        merged = dict(item)

        # не теряем инстанс и inline-печать/её мету
        if isinstance(prev, dict):
            guid = prev.get("InstanceGuid")
            if guid and not merged.get("InstanceGuid"):
                merged["InstanceGuid"] = guid

            for k in (
                    "Stamp", "stamp", "StampId", "StampColorId", "StampName", "StampBonuses",
                    "StampHeaderColorHex", "StampHeaderIconImageId", "StampHeaderIconId",
            ):
                if k in prev and k not in merged:
                    merged[k] = prev[k]

        fl = _toi(payload.get("forge_level") or merged.get("ForgeLevel") or merged.get("__forge_level") or merged.get(
            "UpgradeLevel"))
        fb = _toi(payload.get("forge_bonus") or merged.get("ForgeBonus") or merged.get("__forge_bonus"))
        fa = _toi(payload.get("forge_allstat") or payload.get("forge_all_bonus") or merged.get(
            "ForgeAllStatBonus") or merged.get("AllStatBonus") or merged.get("__forge_allstat"))
        fhp = _toi(payload.get("forge_hp_bonus") or merged.get("ForgeHpBonus") or merged.get("__forge_hp_bonus"))

        fatk = _toi(payload.get("forge_atk_bonus") or merged.get("ForgeAttackBonus") or merged.get(
            "ForgeAtkBonus") or merged.get("__forge_atk_bonus"))
        fdef = _toi(payload.get("forge_def_bonus") or merged.get("ForgeDefenseBonus") or merged.get(
            "ForgeDefBonus") or merged.get("__forge_def_bonus"))

        if fl > 0:
            merged.update({
                "__forge_level": fl,
                "ForgeLevel": fl,
                "UpgradeLevel": fl,
            })
        else:
            merged.pop("__forge_level", None)
            merged.pop("ForgeLevel", None)
            merged.pop("UpgradeLevel", None)

        if fb:
            merged.update({
                "__forge_bonus": fb,
                "ForgeBonus": fb,
            })
        else:
            merged.pop("__forge_bonus", None)
            merged.pop("ForgeBonus", None)

        if fa:
            merged.update({
                "__forge_allstat": fa,
                "ForgeAllStatBonus": fa,
                "AllStatBonus": fa,
            })
        else:
            merged.pop("__forge_allstat", None)
            merged.pop("ForgeAllStatBonus", None)
            merged.pop("AllStatBonus", None)

        if fhp:
            merged.update({
                "__forge_hp_bonus": fhp,
                "ForgeHpBonus": fhp,
            })
        else:
            merged.pop("__forge_hp_bonus", None)
            merged.pop("ForgeHpBonus", None)

        if fatk:
            merged.update({
                "__forge_atk_bonus": fatk,
                "ForgeAttackBonus": fatk,
                "ForgeAtkBonus": fatk,
            })
        else:
            merged.pop("__forge_atk_bonus", None)
            merged.pop("ForgeAttackBonus", None)
            merged.pop("ForgeAtkBonus", None)

        if fdef:
            merged.update({
                "__forge_def_bonus": fdef,
                "ForgeDefenseBonus": fdef,
                "ForgeDefBonus": fdef,
            })
        else:
            merged.pop("__forge_def_bonus", None)
            merged.pop("ForgeDefenseBonus", None)
            merged.pop("ForgeDefBonus", None)

        self.equip_item_in_slot(slot_key, merged, prev_item=prev)

        upd = getattr(self, "_update_offhand_overlay", None)
        if callable(upd):
            upd()

        QTimer.singleShot(0, self._refresh_hover_after_modal)

    def _on_card_picked(self, slot_index: int, card: dict):
        cw = getattr(self, "cards_window", None)
        if not cw or not getattr(cw, "_item_slot_key", None):
            return

        slot_key = str(cw._item_slot_key)
        item = (self._selected_items or {}).get(slot_key)
        if not item:
            return

        si = _safe_int(slot_index, 0)
        if si <= 0:
            return

        def _slot_kind_for_cards() -> str:
            try:
                return "weapon" if self._slot_kind(slot_key) == "weapon" else "equipment"
            except Exception:
                return "weapon" if slot_key in ("weapon", "offhand", "spear") else "equipment"

        def _normalize_cards_map(raw) -> dict[int, dict]:
            out: dict[int, dict] = {}

            if isinstance(raw, dict):
                iterable = list(raw.items())
            elif isinstance(raw, (list, tuple)):
                iterable = [(i + 1, raw[i]) for i in range(len(raw))]
            else:
                iterable = []

            for k, v in iterable:
                idx = _safe_int(k, 0)
                if idx <= 0 or not isinstance(v, dict):
                    continue

                cid = _safe_int(
                    v.get("Id")
                    or v.get("Card_Id")
                    or v.get("CardId"),
                    0,
                )
                if cid <= 0:
                    continue

                out[int(idx)] = dict(v)

            return out

        def _write_cards_to_item(cards_map: dict[int, dict]) -> None:
            clean: dict[int, dict] = {}
            for idx, c in (cards_map or {}).items():
                i = _safe_int(idx, 0)
                if i <= 0 or not isinstance(c, dict):
                    continue

                cid = _safe_int(
                    c.get("Id")
                    or c.get("Card_Id")
                    or c.get("CardId"),
                    0,
                )
                if cid <= 0:
                    continue

                clean[int(i)] = dict(c)

            if clean:
                # Все алиасы держим строго одинаковыми.
                # Иначе одна часть кода видит новую карту, а другая продолжает читать старую.
                item["_cards"] = {int(k): dict(v) for k, v in clean.items()}
                item["cards"] = {int(k): dict(v) for k, v in clean.items()}
                item["Cards"] = {int(k): dict(v) for k, v in clean.items()}
            else:
                item.pop("_cards", None)
                item.pop("cards", None)
                item.pop("Cards", None)

            # Старый совместимый Element_Id нужен только для первого слота weapon.
            if slot_key == "weapon":
                first_card = clean.get(1)
                elem_id = 0
                if isinstance(first_card, dict):
                    elem_id = _safe_int(first_card.get("Element_Id") or first_card.get("ElementId"), 0)

                if elem_id > 0:
                    item["Element_Id"] = int(elem_id)
                else:
                    item.pop("Element_Id", None)

        # Главный источник истины после Apply — CardsWindow._per_item_cards.
        cards_map: dict[int, dict] = {}
        try:
            get_cards = getattr(cw, "get_cards_for_item", None)
            if callable(get_cards):
                cards_map = _normalize_cards_map(
                    get_cards(
                        item,
                        kind=_slot_kind_for_cards(),
                        slot_key=slot_key,
                    )
                )
        except Exception:
            cards_map = {}

        # Фолбэк: если почему-то live-cache не отдал карту, собираем из item и применяем текущий сигнал.
        if not cards_map:
            for key in ("_cards", "cards", "Cards"):
                cards_map = _normalize_cards_map(item.get(key))
                if cards_map:
                    break

        if isinstance(card, dict) and card:
            cards_map[int(si)] = dict(card)
        else:
            cards_map.pop(int(si), None)

        _write_cards_to_item(cards_map)

        # Держим кэш CardsWindow синхронным с item на всякий случай.
        try:
            key_fn = getattr(cw, "_item_key_for", None)
            if callable(key_fn):
                item_key = key_fn(
                    item,
                    kind=_slot_kind_for_cards(),
                    slot_key=slot_key,
                )
                if item_key is not None:
                    cw._per_item_cards[item_key] = {
                        int(k): dict(v)
                        for k, v in cards_map.items()
                        if isinstance(v, dict)
                    }
        except Exception:
            pass

        try:
            self._dbg_dump_equipped_items(
                reason=f"card_picked slot={slot_key} si={si} card_id={(card or {}).get('Id')}",
                focus_slot=slot_key,
            )
        except Exception:
            pass

        self._update_slot_icon(slot_key)

        if slot_key in ("weapon", "offhand"):
            self._update_offhand_overlay(refresh_icon=False)

        # ВАЖНО:
        # сначала чистим бафы, источник которых пропал после замены карты,
        # потом уже считаем характеристики.
        self._sync_buff_debuff_menu_context()
        self.refresh_stats_panel()

    def _dbg_dump_equipped_items(
            self,
            *,
            reason: str = "",
            focus_slot: str | None = None,
    ) -> None:
        """
        Дебаг: печатает содержимое self._selected_items (всё, что надето на персонаже)
        в компактном виде, плюс отдельно показывает карты внутри предметов.

        Включение:
          - либо self.DBG_EQUIP_DICT = True
          - либо переменная окружения RQ_DBG_EQUIP_DICT=1
          - расширенный дамп (pprint) -> RQ_DBG_EQUIP_DICT_FULL=1
        """
        try:
            import os
            import pprint
        except Exception:
            os = None
            pprint = None

        enabled = bool(getattr(self, "DBG_EQUIP_DICT", False))
        if not enabled and os is not None:
            enabled = (str(os.environ.get("RQ_DBG_EQUIP_DICT", "")).strip() == "1")
        if not enabled:
            return

        full = False
        if os is not None:
            full = (str(os.environ.get("RQ_DBG_EQUIP_DICT_FULL", "")).strip() == "1")

        selected = getattr(self, "_selected_items", None) or {}
        if not isinstance(selected, dict):
            try:
                selected = dict(selected)
            except Exception:
                selected = {}

        def _resolve_card_id(entry) -> int:
            if entry is None:
                return 0
            if isinstance(entry, int):
                return int(entry)
            if isinstance(entry, str):
                try:
                    return int(entry)
                except Exception:
                    return 0
            if isinstance(entry, dict):
                for k in ("Id", "Card_Id", "CardId", "card_id", "id"):
                    if k in entry and entry[k] not in (None, ""):
                        try:
                            return int(entry[k])
                        except Exception:
                            return 0
                return 0
            if isinstance(entry, (list, tuple)):
                if not entry:
                    return 0
                return _resolve_card_id(entry[0])
            return 0

        def _extract_cards_summary(item: dict) -> dict:
            cards_raw = None
            cards_key = None
            for k in ("_cards", "cards", "Cards"):
                if k in item:
                    cards_raw = item.get(k)
                    cards_key = k
                    break

            # нормализуем к списку "энтрис" для card_id-детекта
            entries = []
            if isinstance(cards_raw, dict):
                try:
                    # сорт по slot_index, чтобы видеть дубли в разных слотах
                    for kk in sorted(cards_raw.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
                        entries.append(cards_raw.get(kk))
                except Exception:
                    entries = list(cards_raw.values())
            elif isinstance(cards_raw, (list, tuple)):
                entries = list(cards_raw)
            elif cards_raw is None:
                entries = []
            else:
                entries = [cards_raw]

            card_ids = []
            for e in entries:
                cid = _resolve_card_id(e)
                if cid > 0:
                    card_ids.append(cid)

            dups = sorted({c for c in card_ids if card_ids.count(c) > 1})

            # если _cards = dict, покажем ещё ключи слотов
            slot_keys = None
            if isinstance(cards_raw, dict):
                try:
                    slot_keys = list(cards_raw.keys())
                except Exception:
                    slot_keys = None

            return {
                "cards_key": cards_key,
                "cards_type": (type(cards_raw).__name__ if cards_raw is not None else None),
                "cards_len": (len(cards_raw) if hasattr(cards_raw, "__len__") else (len(entries) if entries else 0)),
                "slot_keys": slot_keys,
                "card_ids": card_ids,
                "dups": dups,
            }

        print("\n[EQDICT] reason=", reason, "focus_slot=", focus_slot)

        # компактный вывод по слотам
        for slot_key in sorted(selected.keys(), key=lambda s: str(s)):
            it = selected.get(slot_key)
            if not it:
                print(f"  - {slot_key}: <empty>")
                continue
            if not isinstance(it, dict):
                try:
                    it = dict(it)
                except Exception:
                    print(f"  - {slot_key}: <non-dict item: {type(it).__name__}>")
                    continue

            inst = it.get("InstanceGuid") or it.get("_uuid")
            eid = it.get("Id") or it.get("Equip_Id")
            tid = it.get("Type_Id") or it.get("TypeId")
            lvl = it.get("Level")
            is1h = it.get("IsSingleHandWeapon")

            cs = _extract_cards_summary(it)
            print(
                f"  - {slot_key}: dict_id={id(it)} inst={inst} eid={eid} type={tid} lvl={lvl} IsSingleHandWeapon={is1h} "
                f"cards[{cs['cards_key']}]: type={cs['cards_type']} len={cs['cards_len']} slot_keys={cs['slot_keys']} "
                f"card_ids={cs['card_ids']} dups={cs['dups']}"
            )

        # расширенный дамп (чтобы увидеть вообще всё, включая реальные card dict-объекты)
        if full and pprint is not None:
            if focus_slot and focus_slot in selected and isinstance(selected.get(focus_slot), dict):
                print("\n[EQDICT][FULL] only focus_slot =", focus_slot)
                pprint.pprint(selected.get(focus_slot), width=160, sort_dicts=False)
            else:
                print("\n[EQDICT][FULL] full _selected_items")
                pprint.pprint(selected, width=160, sort_dicts=False)

    def _on_card_cleared(self, slot_index: int):
        cw = getattr(self, "cards_window", None)
        if not cw or not getattr(cw, "_item_slot_key", None):
            return

        slot_key = str(cw._item_slot_key)
        item = (self._selected_items or {}).get(slot_key)
        if not item:
            return

        si = _safe_int(slot_index, 0)
        if si <= 0:
            return

        def _slot_kind_for_cards() -> str:
            try:
                return "weapon" if self._slot_kind(slot_key) == "weapon" else "equipment"
            except Exception:
                return "weapon" if slot_key in ("weapon", "offhand", "spear") else "equipment"

        def _normalize_cards_map(raw) -> dict[int, dict]:
            out: dict[int, dict] = {}

            if isinstance(raw, dict):
                iterable = list(raw.items())
            elif isinstance(raw, (list, tuple)):
                iterable = [(i + 1, raw[i]) for i in range(len(raw))]
            else:
                iterable = []

            for k, v in iterable:
                idx = _safe_int(k, 0)
                if idx <= 0 or not isinstance(v, dict):
                    continue

                cid = _safe_int(
                    v.get("Id")
                    or v.get("Card_Id")
                    or v.get("CardId"),
                    0,
                )
                if cid <= 0:
                    continue

                out[int(idx)] = dict(v)

            return out

        def _write_cards_to_item(cards_map: dict[int, dict]) -> None:
            clean: dict[int, dict] = {}
            for idx, c in (cards_map or {}).items():
                i = _safe_int(idx, 0)
                if i <= 0 or not isinstance(c, dict):
                    continue

                cid = _safe_int(
                    c.get("Id")
                    or c.get("Card_Id")
                    or c.get("CardId"),
                    0,
                )
                if cid <= 0:
                    continue

                clean[int(i)] = dict(c)

            if clean:
                item["_cards"] = {int(k): dict(v) for k, v in clean.items()}
                item["cards"] = {int(k): dict(v) for k, v in clean.items()}
                item["Cards"] = {int(k): dict(v) for k, v in clean.items()}
            else:
                item.pop("_cards", None)
                item.pop("cards", None)
                item.pop("Cards", None)

            if slot_key == "weapon":
                first_card = clean.get(1)
                elem_id = 0
                if isinstance(first_card, dict):
                    elem_id = _safe_int(first_card.get("Element_Id") or first_card.get("ElementId"), 0)

                if elem_id > 0:
                    item["Element_Id"] = int(elem_id)
                else:
                    item.pop("Element_Id", None)

        cards_map: dict[int, dict] = {}
        try:
            get_cards = getattr(cw, "get_cards_for_item", None)
            if callable(get_cards):
                cards_map = _normalize_cards_map(
                    get_cards(
                        item,
                        kind=_slot_kind_for_cards(),
                        slot_key=slot_key,
                    )
                )
        except Exception:
            cards_map = {}

        if not cards_map:
            for key in ("_cards", "cards", "Cards"):
                cards_map = _normalize_cards_map(item.get(key))
                if cards_map:
                    break

        cards_map.pop(int(si), None)
        _write_cards_to_item(cards_map)

        try:
            key_fn = getattr(cw, "_item_key_for", None)
            if callable(key_fn):
                item_key = key_fn(
                    item,
                    kind=_slot_kind_for_cards(),
                    slot_key=slot_key,
                )
                if item_key is not None:
                    cw._per_item_cards[item_key] = {
                        int(k): dict(v)
                        for k, v in cards_map.items()
                        if isinstance(v, dict)
                    }
        except Exception:
            pass

        try:
            self._dbg_dump_equipped_items(
                reason=f"card_cleared slot={slot_key} si={si}",
                focus_slot=slot_key,
            )
        except Exception:
            pass

        self._update_slot_icon(slot_key)

        if slot_key in ("weapon", "offhand"):
            self._update_offhand_overlay(refresh_icon=False)

        self._sync_buff_debuff_menu_context()
        self.refresh_stats_panel()

    def _ensure_helper_menu_button(self) -> None:
        btn = getattr(self, "helper_menu_btn", None)
        if isinstance(btn, QToolButton):
            return

        active_path = (_resolve_resource(HELP_MENU_BTN_ACTIVE_PATH) or HELP_MENU_BTN_ACTIVE_PATH).replace("\\", "/")

        btn = QToolButton(self)
        btn.setObjectName("helperMenuBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAutoRaise(True)
        btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCheckable(True)
        btn.setChecked(False)
        btn.setAttribute(Qt.WA_TranslucentBackground, True)
        btn.setAutoFillBackground(False)

        btn.setStyleSheet(f"""
            QToolButton#helperMenuBtn {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
            QToolButton#helperMenuBtn:hover {{
                border-image: url("{active_path}");
            }}
            QToolButton#helperMenuBtn:pressed {{
                border-image: url("{active_path}");
            }}
            QToolButton#helperMenuBtn:checked {{
                border-image: url("{active_path}");
            }}
        """)

        try:
            btn.clicked.connect(self._open_helper_control_window, Qt.ConnectionType.UniqueConnection)
        except Exception:
            btn.clicked.connect(self._open_helper_control_window)

        btn.hide()
        self.helper_menu_btn = btn

    def _layout_helper_menu_button(self) -> None:
        self._ensure_helper_menu_button()

        pm = self.board_label.pixmap()
        btn = getattr(self, "helper_menu_btn", None)
        if btn is None:
            return

        if not pm:
            btn.hide()
            return

        x0, y0, w0, h0 = HELP_MENU_BTN_RECT
        rect = self._project(int(x0), int(y0), int(w0), int(h0))

        btn.setGeometry(rect)
        btn.show()
        btn.raise_()

    def _ensure_helper_control_window(self) -> _HelperControlWindow:
        w = getattr(self, "_helper_control_window", None)
        if isinstance(w, _HelperControlWindow):
            return w

        w = _HelperControlWindow(self)
        self._helper_control_window = w

        try:
            w.closed.connect(self._on_helper_control_closed, Qt.ConnectionType.UniqueConnection)
        except Exception:
            w.closed.connect(self._on_helper_control_closed)

        return w

    def _open_helper_control_window(self) -> None:
        btn = getattr(self, "helper_menu_btn", None)
        w = self._ensure_helper_control_window()

        if w.isVisible():
            try:
                w.close()
            except Exception:
                pass
            return

        # Это окно НЕ модальное:
        # не включаем _block_main_input,
        # не создаём shield,
        # не блокируем клики по MainWindow.
        try:
            if getattr(self, "hover_name_label", None) is not None:
                self.hover_name_label.hide()
        except Exception:
            pass

        try:
            if btn is not None:
                btn.setChecked(True)
                btn.setDown(False)
                btn.update()
        except Exception:
            pass

        try:
            w.set_help_text(HELP_CONTROL_TEXT)
        except Exception:
            pass

        try:
            w.open_centered(self)
        except Exception:
            try:
                if btn is not None:
                    btn.setChecked(False)
                    btn.setDown(False)
                    btn.update()
            except Exception:
                pass

    def _on_helper_control_closed(self) -> None:
        btn = getattr(self, "helper_menu_btn", None)

        try:
            if btn is not None:
                btn.setChecked(False)
                btn.setDown(False)
                btn.update()
        except Exception:
            pass

        try:
            if getattr(self, "_hover_timer", None) is not None and not self._hover_timer.isActive():
                self._hover_timer.start()
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self._update_glow_from_global)
            QTimer.singleShot(0, self._poke_hover_synthetic)
        except Exception:
            pass

    def _ensure_total_menu_button(self) -> None:
        btn = getattr(self, "total_menu_btn", None)
        if isinstance(btn, QToolButton):
            return

        active_path = (_resolve_resource(TOTAL_MENU_BTN_ACTIVE_PATH) or TOTAL_MENU_BTN_ACTIVE_PATH).replace("\\", "/")

        btn = QToolButton(self)
        btn.setObjectName("totalMenuBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAutoRaise(True)
        btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCheckable(True)
        btn.setChecked(False)
        btn.setAttribute(Qt.WA_TranslucentBackground, True)
        btn.setAutoFillBackground(False)
        btn.setStyleSheet(f"""
            QToolButton#totalMenuBtn {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
            QToolButton#totalMenuBtn:hover {{
                border-image: url("{active_path}");
            }}
            QToolButton#totalMenuBtn:pressed {{
                border-image: url("{active_path}");
            }}
            QToolButton#totalMenuBtn:checked {{
                border-image: url("{active_path}");
            }}
        """)

        try:
            btn.clicked.connect(self._open_total_menu, Qt.ConnectionType.UniqueConnection)
        except Exception:
            btn.clicked.connect(self._open_total_menu)

        btn.hide()
        self.total_menu_btn = btn

    def _layout_total_menu_button(self) -> None:
        self._ensure_total_menu_button()

        pm = self.board_label.pixmap()
        btn = getattr(self, "total_menu_btn", None)
        if btn is None:
            return

        if not pm:
            btn.hide()
            return

        x0, y0, w0, h0 = TOTAL_MENU_BTN_RECT
        rect = self._project(int(x0), int(y0), int(w0), int(h0))

        btn.setGeometry(rect)
        btn.show()
        btn.raise_()

    def _ensure_total_menu_window(self) -> TotalMenuWindow:
        menu = getattr(self, "_total_menu_window", None)
        if isinstance(menu, TotalMenuWindow):
            return menu

        menu = TotalMenuWindow(self)
        self._total_menu_window = menu

        try:
            menu.closed.connect(self._on_total_menu_closed, Qt.ConnectionType.UniqueConnection)
        except Exception:
            menu.closed.connect(self._on_total_menu_closed)

        try:
            menu.saveCharacterClicked.connect(
                self._open_save_manager_from_total_menu,
                Qt.ConnectionType.UniqueConnection,
            )
        except Exception:
            menu.saveCharacterClicked.connect(self._open_save_manager_from_total_menu)

        try:
            menu.loadCharacterClicked.connect(
                self._open_load_manager_from_total_menu,
                Qt.ConnectionType.UniqueConnection,
            )
        except Exception:
            menu.loadCharacterClicked.connect(self._open_load_manager_from_total_menu)

        try:
            menu.checkingUpdatesClicked.connect(
                self._open_update_check_from_total_menu,
                Qt.ConnectionType.UniqueConnection,
            )
        except Exception:
            menu.checkingUpdatesClicked.connect(self._open_update_check_from_total_menu)

        return menu

    def _open_total_menu(self) -> None:
        btn = getattr(self, "total_menu_btn", None)
        menu = self._ensure_total_menu_window()

        if menu.isVisible():
            try:
                menu.close_menu()
            except Exception:
                pass
            return

        # блокируем ввод в MainWindow, как у остальных модалок/оверлеев
        try:
            self._block_main_input = True
        except Exception:
            pass

        try:
            self._block_allow_root = menu
        except Exception:
            pass

        # убрать чекбоксы нижнего меню, если они есть
        try:
            self._place_menu_bonus_toggles()
        except Exception:
            pass

        # стопаем hover-логику
        try:
            if hasattr(self, "_hover_timer") and self._hover_timer is not None and self._hover_timer.isActive():
                self._hover_timer.stop()
        except Exception:
            pass

        # убрать все текущие подсветки/ховеры
        for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
            try:
                ww = getattr(self, nm, None)
                if ww is not None:
                    ww.hide()
            except Exception:
                pass

        try:
            if getattr(self, "_glow_locked_key", None) is not None:
                self._unlock_glow()
        except Exception:
            pass

        try:
            if getattr(self, "equip_info", None) is not None:
                try:
                    self.equip_info.end_hover(self)
                except Exception:
                    self.equip_info.hide()
        except Exception:
            pass

        # кнопка открытия не должна "висеть" активной, пока меню открыто
        try:
            if btn is not None:
                btn.setChecked(False)
                btn.setDown(False)
                btn.setEnabled(False)
                btn.update()
        except Exception:
            pass

        try:
            menu.open_centered(self)

            # КЛЮЧЕВОЕ:
            # после открытия меню MainWindow может ещё раз поднять stats_panel/иконки,
            # поэтому принудительно возвращаем shield наверх несколько раз.
            self._raise_active_modal_layer()
            QTimer.singleShot(0, self._raise_active_modal_layer)
            QTimer.singleShot(30, self._raise_active_modal_layer)
            QTimer.singleShot(100, self._raise_active_modal_layer)

        except Exception:
            try:
                self._block_main_input = False
            except Exception:
                pass

            try:
                self._block_allow_root = None
            except Exception:
                pass

            try:
                if btn is not None:
                    btn.setEnabled(True)
                    btn.setChecked(False)
                    btn.setDown(False)
                    btn.update()
            except Exception:
                pass

            try:
                self._place_menu_bonus_toggles()
            except Exception:
                pass

    def _on_total_menu_closed(self) -> None:
        btn = getattr(self, "total_menu_btn", None)

        # снять блокировку main window
        try:
            self._block_main_input = False
        except Exception:
            pass

        try:
            self._block_allow_root = None
        except Exception:
            pass

        # вернуть кнопку открытия в обычное состояние
        try:
            if btn is not None:
                btn.setEnabled(True)
                btn.setChecked(False)
                btn.setDown(False)
                btn.update()
        except Exception:
            pass

        # вернуть фокус главному окну
        try:
            self.raise_()
            self.activateWindow()
            QApplication.setActiveWindow(self)
        except Exception:
            pass

        # hover обратно — только если реально нет других модалок/щитов
        try:
            any_modal = bool(self._stamp_shield_active() or self._reforge_shield_active())
        except Exception:
            any_modal = False

        try:
            if (not any_modal) and hasattr(self, "_hover_timer") and self._hover_timer is not None:
                if not self._hover_timer.isActive():
                    self._hover_timer.start()
        except Exception:
            pass

        try:
            if getattr(self, "_glow_locked_key", None) is not None:
                self._unlock_glow()
        except Exception:
            pass

        try:
            self.menu_glow.hide()
        except Exception:
            pass

        try:
            self.hover_glow.hide()
        except Exception:
            pass

        try:
            self.winbtn_hover.hide()
        except Exception:
            pass

        # вернуть чекбоксы включения бонусов нижнего меню
        try:
            self._place_menu_bonus_toggles()
            QTimer.singleShot(0, self._place_menu_bonus_toggles)
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self._update_glow_from_global)
            QTimer.singleShot(0, self._poke_hover_synthetic)
        except Exception:
            pass

    def _ensure_save_load_manager_window(self) -> SaveLoadManagerWindow:
        w = getattr(self, "_save_load_manager_window", None)
        if isinstance(w, SaveLoadManagerWindow):
            return w

        w = SaveLoadManagerWindow(self)
        self._save_load_manager_window = w

        try:
            w.closed.connect(self._on_save_load_manager_closed, Qt.ConnectionType.UniqueConnection)
        except Exception:
            w.closed.connect(self._on_save_load_manager_closed)

        try:
            w.cancelledToTotalMenu.connect(
                self._on_save_load_manager_cancelled_to_total_menu,
                Qt.ConnectionType.UniqueConnection,
            )
        except Exception:
            w.cancelledToTotalMenu.connect(self._on_save_load_manager_cancelled_to_total_menu)

        return w

    def _open_save_load_manager(self, mode: str, *, return_to_total_menu_on_cancel: bool) -> None:
        mode = str(mode or "save").strip().lower()
        if mode not in ("save", "load"):
            mode = "save"

        w = self._ensure_save_load_manager_window()

        # если открыто total_menu — убираем его перед открытием менеджера
        total_menu = getattr(self, "_total_menu_window", None)
        try:
            if total_menu is not None and total_menu.isVisible():
                total_menu.close_menu()
        except Exception:
            pass

        # блокируем ввод в MainWindow
        try:
            self._block_main_input = True
        except Exception:
            pass

        try:
            self._block_allow_root = w
        except Exception:
            pass

        # убрать чекбоксы нижнего меню, если они есть
        try:
            self._place_menu_bonus_toggles()
        except Exception:
            pass

        # стоп hover-логики
        try:
            if hasattr(self, "_hover_timer") and self._hover_timer is not None and self._hover_timer.isActive():
                self._hover_timer.stop()
        except Exception:
            pass

        # убираем все подсветки
        for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
            try:
                ww = getattr(self, nm, None)
                if ww is not None:
                    ww.hide()
            except Exception:
                pass

        try:
            if getattr(self, "_glow_locked_key", None) is not None:
                self._unlock_glow()
        except Exception:
            pass

        try:
            if getattr(self, "equip_info", None) is not None:
                try:
                    self.equip_info.end_hover(self)
                except Exception:
                    self.equip_info.hide()
        except Exception:
            pass

        try:
            w.open_centered(
                self,
                mode=mode,
                cancel_returns_to_total_menu=bool(return_to_total_menu_on_cancel),
            )

            # КЛЮЧЕВОЕ:
            # после открытия save/load MainWindow может ещё раз поднять stats_panel/иконки,
            # поэтому возвращаем shield save/load наверх.
            self._raise_active_modal_layer()
            QTimer.singleShot(0, self._raise_active_modal_layer)
            QTimer.singleShot(30, self._raise_active_modal_layer)
            QTimer.singleShot(100, self._raise_active_modal_layer)

        except Exception:
            try:
                self._block_main_input = False
            except Exception:
                pass

            try:
                self._block_allow_root = None
            except Exception:
                pass

            try:
                self._place_menu_bonus_toggles()
            except Exception:
                pass

    def _open_save_manager_from_total_menu(self) -> None:
        self._open_save_load_manager("save", return_to_total_menu_on_cancel=True)

    def _open_load_manager_from_total_menu(self) -> None:
        self._open_save_load_manager("load", return_to_total_menu_on_cancel=True)

    def _open_save_manager_direct(self) -> None:
        self._open_save_load_manager("save", return_to_total_menu_on_cancel=False)

    def _open_load_manager_direct(self) -> None:
        self._open_save_load_manager("load", return_to_total_menu_on_cancel=False)

    def _ensure_update_info_window(self) -> _UpdateInfoBoardWindow:
        w = getattr(self, "_update_info_window", None)
        if isinstance(w, _UpdateInfoBoardWindow):
            return w

        w = _UpdateInfoBoardWindow(self)
        self._update_info_window = w

        try:
            w.cancelled.connect(self._on_update_info_cancelled, Qt.ConnectionType.UniqueConnection)
        except Exception:
            w.cancelled.connect(self._on_update_info_cancelled)

        try:
            w.updateRequested.connect(self._on_update_requested, Qt.ConnectionType.UniqueConnection)
        except Exception:
            w.updateRequested.connect(self._on_update_requested)

        try:
            w.downloadFinished.connect(self._on_update_window_download_finished, Qt.ConnectionType.UniqueConnection)
        except Exception:
            w.downloadFinished.connect(self._on_update_window_download_finished)

        return w

    def _on_update_window_download_finished(self, payload: object) -> None:
        if not (isinstance(payload, dict) and payload.get("ok")):
            return

        self._updater_is_launching = True

        try:
            self._block_main_input = True
        except Exception:
            pass

        try:
            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(700, app.quit)
        except Exception:
            pass

    def _open_update_check_from_total_menu(self) -> None:
        """
        Открывает окно проверки обновлений из total_menu.

        total_menu закрываем.
        При отмене возвращаемся в MainWindow, а не обратно в total_menu.
        """
        total_menu = getattr(self, "_total_menu_window", None)
        try:
            if total_menu is not None and total_menu.isVisible():
                total_menu.close_menu()
        except Exception:
            pass

        w = self._ensure_update_info_window()
        w.set_checking()

        try:
            self._block_main_input = True
        except Exception:
            pass

        try:
            self._block_allow_root = w
        except Exception:
            pass

        try:
            self._place_menu_bonus_toggles()
        except Exception:
            pass

        try:
            if hasattr(self, "_hover_timer") and self._hover_timer is not None and self._hover_timer.isActive():
                self._hover_timer.stop()
        except Exception:
            pass

        for nm in ("menu_glow", "hover_glow", "winbtn_hover", "hover_name_label"):
            try:
                ww = getattr(self, nm, None)
                if ww is not None:
                    ww.hide()
            except Exception:
                pass

        try:
            if getattr(self, "_glow_locked_key", None) is not None:
                self._unlock_glow()
        except Exception:
            pass

        try:
            if getattr(self, "equip_info", None) is not None:
                try:
                    self.equip_info.end_hover(self)
                except Exception:
                    self.equip_info.hide()
        except Exception:
            pass

        w.open_centered(self)

        try:
            self._raise_active_modal_layer()
            QTimer.singleShot(0, self._raise_active_modal_layer)
            QTimer.singleShot(30, self._raise_active_modal_layer)
            QTimer.singleShot(100, self._raise_active_modal_layer)
        except Exception:
            pass

        self._start_update_check_worker(w)

    def _start_update_check_worker(self, w: _UpdateInfoBoardWindow) -> None:
        def _worker():
            try:
                manager = UpdateManager()

                def _progress(msg: str) -> None:
                    try:
                        w.statusChanged.emit(str(msg or ""))
                    except Exception:
                        pass

                result = manager.check_for_updates(progress=_progress)
            except Exception as e:
                result = UpdateCheckResult(
                    ok=False,
                    update_available=False,
                    current_version="0.0.0",
                    remote_version="0.0.0",
                    notes="",
                    components_to_update=[],
                    manifest={},
                    error=str(e),
                )

            try:
                w.checkFinished.emit(result)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_requested(self, result: object) -> None:
        if not isinstance(result, UpdateCheckResult):
            return

        w = self._ensure_update_info_window()
        w.set_downloading()

        def _worker():
            try:
                manager = UpdateManager()

                def _progress(msg: str) -> None:
                    try:
                        w.statusChanged.emit(str(msg or ""))
                    except Exception:
                        pass

                plan_path = manager.prepare_update(result, progress=_progress)
                manager.launch_updater(plan_path)

                try:
                    w.downloadFinished.emit({"ok": True})
                except Exception:
                    pass

            except Exception as e:
                try:
                    w.downloadFinished.emit({"ok": False, "error": str(e)})
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_info_cancelled(self) -> None:
        if getattr(self, "_updater_is_launching", False):
            return

        try:
            self._block_main_input = False
        except Exception:
            pass

        try:
            self._block_allow_root = None
        except Exception:
            pass

        try:
            self.raise_()
            self.activateWindow()
            QApplication.setActiveWindow(self)
        except Exception:
            pass

        try:
            any_modal = bool(self._stamp_shield_active() or self._reforge_shield_active())
        except Exception:
            any_modal = False

        try:
            if (not any_modal) and hasattr(self, "_hover_timer") and self._hover_timer is not None:
                if not self._hover_timer.isActive():
                    self._hover_timer.start()
        except Exception:
            pass

        try:
            self._place_menu_bonus_toggles()
            QTimer.singleShot(0, self._place_menu_bonus_toggles)
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self._update_glow_from_global)
            QTimer.singleShot(0, self._poke_hover_synthetic)
        except Exception:
            pass

    def _on_update_download_finished(self, payload: object) -> None:
        """
        Этот метод оставлен на будущее, если захочешь отдельно подключать сигнал.
        Сейчас результат загрузки обрабатывает само окно через downloadFinished.
        """
        pass

    def _raise_active_modal_layer(self) -> None:
        """
        Возвращает активный shield модального меню поверх всех виджетов MainWindow.

        Нужно потому что _layout_overlays(), stats_panel, иконки слотов и прочие
        элементы MainWindow могут делать raise_() уже после открытия total/save/load меню.
        """
        try:
            allow_root = getattr(self, "_block_allow_root", None)
        except Exception:
            allow_root = None

        if not isinstance(allow_root, QWidget):
            return

        try:
            if not allow_root.isVisible():
                return
        except Exception:
            return

        try:
            shield = allow_root.parentWidget()
        except Exception:
            shield = None

        # Для total_menu/save_load_manager allow_root лежит внутри shield,
        # а сам shield является ребёнком MainWindow.
        if isinstance(shield, QWidget) and shield is not self:
            try:
                if shield.parentWidget() is self:
                    shield.setGeometry(self.rect())
                    shield.show()
                    shield.raise_()
                    allow_root.raise_()
                    return
            except Exception:
                pass

        # Фолбэк для окон, которые являются прямыми детьми MainWindow.
        try:
            allow_root.raise_()
        except Exception:
            pass

    def _on_save_load_manager_closed(self) -> None:
        try:
            self._block_main_input = False
        except Exception:
            pass

        try:
            self._block_allow_root = None
        except Exception:
            pass

        try:
            self.raise_()
            self.activateWindow()
            QApplication.setActiveWindow(self)
        except Exception:
            pass

        try:
            any_modal = bool(self._stamp_shield_active() or self._reforge_shield_active())
        except Exception:
            any_modal = False

        try:
            if (not any_modal) and hasattr(self, "_hover_timer") and self._hover_timer is not None:
                if not self._hover_timer.isActive():
                    self._hover_timer.start()
        except Exception:
            pass

        try:
            if getattr(self, "_glow_locked_key", None) is not None:
                self._unlock_glow()
        except Exception:
            pass

        try:
            self.menu_glow.hide()
        except Exception:
            pass

        try:
            self.hover_glow.hide()
        except Exception:
            pass

        try:
            self.winbtn_hover.hide()
        except Exception:
            pass

        # вернуть чекбоксы включения бонусов нижнего меню
        try:
            self._place_menu_bonus_toggles()
            QTimer.singleShot(0, self._place_menu_bonus_toggles)
        except Exception:
            pass

        try:
            QTimer.singleShot(0, self._update_glow_from_global)
            QTimer.singleShot(0, self._poke_hover_synthetic)
        except Exception:
            pass

    def _on_save_load_manager_cancelled_to_total_menu(self) -> None:
        self._on_save_load_manager_closed()

        try:
            QTimer.singleShot(0, self._open_total_menu)
        except Exception:
            pass

    def keyPressEvent(self, ev) -> None:
        try:
            key = ev.key()
            mods = ev.modifiers()

            if (mods & Qt.ControlModifier) and key == Qt.Key_S:
                self._open_save_manager_direct()
                ev.accept()
                return

            if (mods & Qt.ControlModifier) and key == Qt.Key_D:
                self._open_load_manager_direct()
                ev.accept()
                return

            # Запрещаем клавиатурную активацию кнопок.
            # Space/Enter могли нажимать сфокусированную кнопку,
            # а Tab/Backtab — выбирать следующую кнопку.
            if key in (
                    Qt.Key_Space,
                    Qt.Key_Return,
                    Qt.Key_Enter,
                    Qt.Key_Tab,
                    Qt.Key_Backtab,
            ):
                try:
                    fw = QApplication.focusWidget()
                    if fw is not None:
                        fw.clearFocus()
                except Exception:
                    pass

                ev.accept()
                return

        except Exception:
            pass

        super().keyPressEvent(ev)