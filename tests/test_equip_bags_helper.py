import importlib.util
import sys
import types
import unittest
from enum import IntEnum
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_CACHE_PATH = REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "GlobalCache" / "InventoryCache.py"
ITEMS_HELPER_PATH = REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "botting_src" / "helpers_src" / "Items.py"
UI_HELPER_PATH = REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "botting_src" / "helpers_src" / "UI.py"
DECORATORS_PATH = REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "botting_src" / "helpers_src" / "decorators.py"


def _clear_modules(*prefixes: str) -> None:
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes):
            sys.modules.pop(name, None)


def _make_package(name: str, path: Path | None = None) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = [str(path)] if path is not None else []
    sys.modules[name] = module
    return module


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _drain(generator):
    while True:
        try:
            next(generator)
        except StopIteration as stop:
            return stop.value


class _FakeBag:
    states: dict[int, dict] = {}

    @classmethod
    def configure(cls, mapping: dict[int, dict]) -> None:
        cls.states = {bag_id: dict(state) for bag_id, state in mapping.items()}

    def __init__(self, bag_id: int, _bag_name: str):
        state = self.states.setdefault(
            bag_id,
            {"container_item": 0, "size": 0, "context_calls": 0, "items": [], "item_count": 0},
        )
        self._state = state
        self.id = bag_id
        self.name = str(bag_id)
        self.container_item = state["container_item"]

    def GetContext(self) -> None:
        self._state["context_calls"] += 1
        self.container_item = self._state["container_item"]

    def GetItems(self):
        return list(self._state["items"])

    def GetItemCount(self) -> int:
        return int(self._state["item_count"])

    def GetSize(self) -> int:
        return int(self._state["size"])

    def FindItemById(self, _item_id: int):
        return None


class _FakeInventoryNative:
    def __init__(self) -> None:
        self.equip_calls = []

    def EquipItem(self, item_id: int, agent_id: int) -> bool:
        self.equip_calls.append((item_id, agent_id))
        return True

    def OpenXunlaiWindow(self) -> None:
        return None

    def GetIsStorageOpen(self) -> bool:
        return False


class _FakeBagsEnum(IntEnum):
    Backpack = 1
    BeltPouch = 2
    Bag1 = 3
    Bag2 = 4


class _FakeMessageType:
    Error = "error"
    Warning = "warning"
    Info = "info"


class _FakePy4GW(types.ModuleType):
    def __init__(self):
        super().__init__("Py4GW")
        self.Console = types.SimpleNamespace(MessageType=_FakeMessageType)


class InventoryCacheBagStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _clear_modules("PyInventory", "Py4GWCoreLib")
        pyinventory = types.ModuleType("PyInventory")
        pyinventory.Bag = _FakeBag
        pyinventory.PyInventory = _FakeInventoryNative
        sys.modules["PyInventory"] = pyinventory

        core_pkg = _make_package("Py4GWCoreLib", REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib")
        core_pkg.ConsoleLog = lambda *_args, **_kwargs: None
        core_pkg.Bags = _FakeBagsEnum
        core_pkg.ModelID = types.SimpleNamespace(Vial_Of_Dye=types.SimpleNamespace(value=146))
        core_pkg.Item = types.SimpleNamespace(
            Customization=types.SimpleNamespace(
                GetDyeInfo=lambda _item_id: types.SimpleNamespace(dye1=types.SimpleNamespace(ToInt=lambda: 0))
            )
        )
        core_pkg.WindowID = types.SimpleNamespace(WindowID_InventoryBags=0)

        sys.modules["Py4GWCoreLib.Py4GWcorelib"] = types.SimpleNamespace(ActionQueueManager=object)
        sys.modules["Py4GWCoreLib.UIManager"] = types.SimpleNamespace(
            UIManager=types.SimpleNamespace(IsWindowVisible=lambda _window_id: False)
        )
        sys.modules["Py4GWCoreLib.GWUI"] = types.SimpleNamespace(GWUI=object)

        global_cache_pkg = _make_package("Py4GWCoreLib.GlobalCache", REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "GlobalCache")
        item_cache_module = types.ModuleType("Py4GWCoreLib.GlobalCache.ItemCache")
        item_cache_module.RawItemCache = object
        item_cache_module.ItemCache = object
        item_cache_module.Bag_enum = _FakeBagsEnum
        sys.modules["Py4GWCoreLib.GlobalCache.ItemCache"] = item_cache_module
        setattr(global_cache_pkg, "ItemCache", item_cache_module)

        cls.inventory_cache_module = _load_module("Py4GWCoreLib.GlobalCache.InventoryCache", INVENTORY_CACHE_PATH)

    def test_get_bag_container_item_refreshes_context_before_read(self):
        _FakeBag.configure({2: {"container_item": 1234, "size": 5, "context_calls": 0, "items": [], "item_count": 0}})
        cache = self.inventory_cache_module.InventoryCache(object(), object(), object())

        self.assertEqual(1234, cache.GetBagContainerItem(2))
        self.assertEqual(1, _FakeBag.states[2]["context_calls"])

    def test_get_bag_size_refreshes_context_before_read(self):
        _FakeBag.configure({3: {"container_item": 4321, "size": 10, "context_calls": 0, "items": [], "item_count": 0}})
        cache = self.inventory_cache_module.InventoryCache(object(), object(), object())

        self.assertEqual(10, cache.GetBagSize(3))
        self.assertEqual(1, _FakeBag.states[3]["context_calls"])


class _SequencedInventory:
    def __init__(self, item_id: int, container_values: list[int], size_values: list[int]):
        self.item_id = item_id
        self.container_values = list(container_values)
        self.size_values = list(size_values)
        self.equip_calls = []
        self.use_calls = []

    def GetBagContainerItem(self, _bag_id: int) -> int:
        if len(self.container_values) > 1:
            return self.container_values.pop(0)
        return self.container_values[0]

    def GetBagSize(self, _bag_id: int) -> int:
        if len(self.size_values) > 1:
            return self.size_values.pop(0)
        return self.size_values[0]

    def GetFirstModelID(self, _model_id: int) -> int:
        return self.item_id

    def EquipItem(self, item_id: int, agent_id: int) -> None:
        self.equip_calls.append((item_id, agent_id))

    def UseItem(self, item_id: int) -> None:
        self.use_calls.append(item_id)


class _UseTriggeredInventory:
    def __init__(self, item_id: int):
        self.item_id = item_id
        self.equip_calls = []
        self.use_calls = []
        self._equipped = False

    def GetBagContainerItem(self, _bag_id: int) -> int:
        return 9001 if self._equipped else 0

    def GetBagSize(self, _bag_id: int) -> int:
        return 10 if self._equipped else 0

    def GetFirstModelID(self, _model_id: int) -> int:
        return self.item_id

    def EquipItem(self, item_id: int, agent_id: int) -> None:
        self.equip_calls.append((item_id, agent_id))

    def UseItem(self, item_id: int) -> None:
        self.use_calls.append(item_id)
        self._equipped = True


class _FallbackTriggeredInventory:
    def __init__(self, item_id: int):
        self.item_id = item_id
        self.use_calls = []
        self.move_calls = []
        self._equipped = False

    def GetBagContainerItem(self, _bag_id: int) -> int:
        return 9001 if self._equipped else 0

    def GetBagSize(self, _bag_id: int) -> int:
        return 10 if self._equipped else 0

    def GetFirstModelID(self, _model_id: int) -> int:
        return self.item_id

    def UseItem(self, item_id: int) -> None:
        self.use_calls.append(item_id)

    def MoveModelToBagSlot(self, model_id: int, bag_id: int, slot: int) -> bool:
        self.move_calls.append((model_id, bag_id, slot))
        return True


class _FakeYield:
    wait_calls = []

    @staticmethod
    def wait(duration_ms: int):
        _FakeYield.wait_calls.append(duration_ms)
        yield None


class _FakeEvents:
    def __init__(self):
        self.unmanaged_failures = 0

    def on_unmanaged_fail(self):
        self.unmanaged_failures += 1


class _FakeUIHelper:
    def __init__(self, on_double_click=None):
        self.open_all_bags_calls = 0
        self.bag_item_double_click_calls = []
        self._on_double_click = on_double_click or (lambda _bag_id, _slot: None)

    def iter_open_all_bags(self):
        self.open_all_bags_calls += 1
        yield None

    def open_all_bags(self):
        return None

    def iter_bag_item_double_click(self, bag_id: int, slot: int):
        self.bag_item_double_click_calls.append((bag_id, slot))
        self._on_double_click(bag_id, slot)
        yield None

    def bag_item_double_click(self, bag_id: int, slot: int):
        return None


class _DecoratedStyleUIHelper(_FakeUIHelper):
    def open_all_bags(self):
        return None

    def iter_open_all_bags(self):
        self.open_all_bags_calls += 1
        yield None

    def bag_item_double_click(self, _bag_id: int, _slot: int):
        return None

    def iter_bag_item_double_click(self, bag_id: int, slot: int):
        self.bag_item_double_click_calls.append((bag_id, slot))
        self._on_double_click(bag_id, slot)
        yield None


class _FakeBotRoot:
    def __init__(self, ui_helper: _FakeUIHelper | None = None):
        self.helpers = types.SimpleNamespace(UI=ui_helper or _FakeUIHelper())


class _FakeBottingParent:
    def __init__(self, events: _FakeEvents, root: _FakeBotRoot | None = None):
        self.parent = root or _FakeBotRoot()
        self._config = types.SimpleNamespace()
        self.Events = events


class _FakeUIManagerAPI:
    child_frame_id = 4242
    test_mouse_action_calls = []
    test_mouse_click_action_calls = []
    button_double_click_calls = []

    @classmethod
    def reset(cls):
        cls.test_mouse_action_calls = []
        cls.test_mouse_click_action_calls = []
        cls.button_double_click_calls = []

    @staticmethod
    def GetChildFrameID(_parent_hash: int, _offsets):
        return _FakeUIManagerAPI.child_frame_id

    @staticmethod
    def FrameExists(frame_id: int) -> bool:
        return frame_id == _FakeUIManagerAPI.child_frame_id

    @staticmethod
    def TestMouseAction(frame_id: int, current_state: int, wparam_value: int, lparam_value: int = 0):
        _FakeUIManagerAPI.test_mouse_action_calls.append((frame_id, current_state, wparam_value, lparam_value))

    @staticmethod
    def TestMouseClickAction(frame_id: int, current_state: int, wparam_value: int, lparam_value: int = 0):
        _FakeUIManagerAPI.test_mouse_click_action_calls.append((frame_id, current_state, wparam_value, lparam_value))

    @staticmethod
    def ButtonDoubleClick(frame_id: int):
        _FakeUIManagerAPI.button_double_click_calls.append(frame_id)


class ItemsBagEquipHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _clear_modules("Py4GW", "Py4GWCoreLib")
        sys.modules["Py4GW"] = _FakePy4GW()

        core_pkg = _make_package("Py4GWCoreLib", REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib")
        core_pkg.ConsoleLog = lambda *_args, **_kwargs: None
        core_pkg.Console = types.SimpleNamespace(MessageType=_FakeMessageType)
        sys.modules["Py4GWCoreLib.Py4GWcorelib"] = types.SimpleNamespace(
            ConsoleLog=lambda *_args, **_kwargs: None,
            Console=types.SimpleNamespace(MessageType=_FakeMessageType),
        )

        player_module = types.ModuleType("Py4GWCoreLib.Player")
        player_module.Player = types.SimpleNamespace(GetAgentID=lambda: 77)
        sys.modules["Py4GWCoreLib.Player"] = player_module

        model_enum = types.SimpleNamespace(
            Igneous_Summoning_Stone=types.SimpleNamespace(value=1),
            Bonus_Nevermore_Flatbow=types.SimpleNamespace(value=2),
            Bonus_Luminescent_Scepter=types.SimpleNamespace(value=3),
            Bonus_Rhinos_Charge=types.SimpleNamespace(value=4),
            Bonus_Serrated_Shield=types.SimpleNamespace(value=5),
            Bonus_Soul_Shrieker=types.SimpleNamespace(value=6),
            Bonus_Tigers_Roar=types.SimpleNamespace(value=7),
            Bonus_Wolfs_Favor=types.SimpleNamespace(value=8),
        )
        _make_package("Py4GWCoreLib.enums_src", REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "enums_src")
        sys.modules["Py4GWCoreLib.enums_src.Model_enums"] = types.SimpleNamespace(ModelID=model_enum)
        sys.modules["Py4GWCoreLib.enums"] = types.SimpleNamespace(Bags=_FakeBagsEnum)

        routines_module = types.ModuleType("Py4GWCoreLib.Routines")
        routines_module.Routines = types.SimpleNamespace(Yield=_FakeYield)
        sys.modules["Py4GWCoreLib.Routines"] = routines_module

        _make_package("Py4GWCoreLib.botting_src", REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "botting_src")
        _make_package(
            "Py4GWCoreLib.botting_src.helpers_src",
            REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "botting_src" / "helpers_src",
        )
        _load_module("Py4GWCoreLib.botting_src.helpers_src.decorators", DECORATORS_PATH)
        cls.items_module = _load_module("Py4GWCoreLib.botting_src.helpers_src.Items", ITEMS_HELPER_PATH)

    def setUp(self):
        _FakeYield.wait_calls = []
        self.events = _FakeEvents()
        self.items_helper = self.items_module._Items(_FakeBottingParent(self.events))

    def test_equip_inventory_bag_returns_true_when_target_bag_is_already_equipped(self):
        inventory = _SequencedInventory(item_id=5001, container_values=[1234], size_values=[5])
        global_cache_module = types.ModuleType("Py4GWCoreLib.GlobalCache")
        global_cache_module.GLOBAL_CACHE = types.SimpleNamespace(Inventory=inventory)
        sys.modules["Py4GWCoreLib.GlobalCache"] = global_cache_module

        result = _drain(self.items_helper._equip_inventory_bag(35, 3))

        self.assertTrue(result)
        self.assertEqual([], inventory.equip_calls)
        self.assertEqual(0, self.events.unmanaged_failures)

    def test_equip_inventory_bag_uses_item_and_waits_for_target_bag(self):
        inventory = _SequencedInventory(item_id=5002, container_values=[0, 0, 9001], size_values=[0, 0, 10])
        global_cache_module = types.ModuleType("Py4GWCoreLib.GlobalCache")
        global_cache_module.GLOBAL_CACHE = types.SimpleNamespace(Inventory=inventory)
        sys.modules["Py4GWCoreLib.GlobalCache"] = global_cache_module

        result = _drain(self.items_helper._equip_inventory_bag(35, 4, timeout_ms=600))

        self.assertTrue(result)
        self.assertEqual([5002], inventory.use_calls)
        self.assertEqual([], inventory.equip_calls)
        self.assertGreaterEqual(len(_FakeYield.wait_calls), 1)
        self.assertEqual(0, self.events.unmanaged_failures)

    def test_equip_inventory_bag_uses_item_path_for_bag_container_activation(self):
        inventory = _UseTriggeredInventory(item_id=5003)
        global_cache_module = types.ModuleType("Py4GWCoreLib.GlobalCache")
        global_cache_module.GLOBAL_CACHE = types.SimpleNamespace(Inventory=inventory)
        sys.modules["Py4GWCoreLib.GlobalCache"] = global_cache_module

        result = _drain(self.items_helper._equip_inventory_bag(34, 2, timeout_ms=600))

        self.assertTrue(result)
        self.assertEqual([5003], inventory.use_calls)
        self.assertEqual([], inventory.equip_calls)
        self.assertEqual(0, self.events.unmanaged_failures)

    def test_equip_inventory_bag_falls_back_to_move_and_ui_double_click(self):
        inventory = _FallbackTriggeredInventory(item_id=5004)
        ui_helper = _FakeUIHelper(on_double_click=lambda _bag_id, _slot: setattr(inventory, "_equipped", True))
        self.items_helper = self.items_module._Items(_FakeBottingParent(self.events, _FakeBotRoot(ui_helper)))
        global_cache_module = types.ModuleType("Py4GWCoreLib.GlobalCache")
        global_cache_module.GLOBAL_CACHE = types.SimpleNamespace(Inventory=inventory)
        sys.modules["Py4GWCoreLib.GlobalCache"] = global_cache_module

        result = _drain(self.items_helper._equip_inventory_bag(35, 3, timeout_ms=600))

        self.assertTrue(result)
        self.assertEqual([5004], inventory.use_calls)
        self.assertEqual([(35, _FakeBagsEnum.Backpack, 0)], inventory.move_calls)
        self.assertEqual(1, ui_helper.open_all_bags_calls)
        self.assertEqual([(_FakeBagsEnum.Backpack, 0)], ui_helper.bag_item_double_click_calls)
        self.assertEqual(0, self.events.unmanaged_failures)

    def test_equip_inventory_bag_fallback_uses_explicit_ui_generator_api_when_public_wrappers_return_none(self):
        inventory = _FallbackTriggeredInventory(item_id=5005)
        ui_helper = _DecoratedStyleUIHelper(on_double_click=lambda _bag_id, _slot: setattr(inventory, "_equipped", True))
        self.items_helper = self.items_module._Items(_FakeBottingParent(self.events, _FakeBotRoot(ui_helper)))
        global_cache_module = types.ModuleType("Py4GWCoreLib.GlobalCache")
        global_cache_module.GLOBAL_CACHE = types.SimpleNamespace(Inventory=inventory)
        sys.modules["Py4GWCoreLib.GlobalCache"] = global_cache_module

        result = _drain(self.items_helper._equip_inventory_bag(35, 3, timeout_ms=600))

        self.assertTrue(result)
        self.assertEqual(1, ui_helper.open_all_bags_calls)
        self.assertEqual([(_FakeBagsEnum.Backpack, 0)], ui_helper.bag_item_double_click_calls)
        self.assertEqual(0, self.events.unmanaged_failures)

class UIBagDoubleClickHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _clear_modules("Py4GWCoreLib")
        _make_package("Py4GWCoreLib", REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib")
        sys.modules["Py4GWCoreLib.Py4GWcorelib"] = types.SimpleNamespace(
            ConsoleLog=lambda *_args, **_kwargs: None,
            Console=types.SimpleNamespace(MessageType=_FakeMessageType),
        )
        routines_module = types.ModuleType("Py4GWCoreLib.Routines")
        routines_module.Routines = types.SimpleNamespace(Yield=_FakeYield)
        sys.modules["Py4GWCoreLib.Routines"] = routines_module
        sys.modules["Py4GWCoreLib.GWUI"] = types.SimpleNamespace(GWUI=object)
        sys.modules["Py4GWCoreLib.UIManager"] = types.SimpleNamespace(UIManager=_FakeUIManagerAPI)

        _make_package("Py4GWCoreLib.botting_src", REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "botting_src")
        _make_package(
            "Py4GWCoreLib.botting_src.helpers_src",
            REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "botting_src" / "helpers_src",
        )
        _load_module("Py4GWCoreLib.botting_src.helpers_src.decorators", DECORATORS_PATH)
        cls.ui_module = _load_module("Py4GWCoreLib.botting_src.helpers_src.UI", UI_HELPER_PATH)

    def setUp(self):
        _FakeYield.wait_calls = []
        _FakeUIManagerAPI.reset()
        self.ui_helper = self.ui_module._UI(_FakeBottingParent(_FakeEvents()))

    def test_iter_bag_item_double_click_uses_frame_mouse_double_click_path(self):
        _drain(self.ui_helper.iter_bag_item_double_click(1, 0))

        self.assertEqual(
            [(_FakeUIManagerAPI.child_frame_id, 9, 0, 0)],
            _FakeUIManagerAPI.test_mouse_action_calls,
        )
        self.assertEqual(
            [(_FakeUIManagerAPI.child_frame_id, 9, 0, 0)],
            _FakeUIManagerAPI.test_mouse_click_action_calls,
        )
        self.assertEqual([], _FakeUIManagerAPI.button_double_click_calls)


if __name__ == "__main__":
    unittest.main()
