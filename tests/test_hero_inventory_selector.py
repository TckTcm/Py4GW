import importlib.util
import pathlib
import sys
import types
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "Widgets" / "Automation" / "Enhancements" / "Hero Inventory Selector.py"


class FakeUIManager:
    visible = False
    set_visible_error = None
    set_visible_calls = []
    keydown_calls = []
    frame_click_calls = []
    test_mouse_click_calls = []
    label_frame_id = 0
    send_frame_ui_message_calls = []
    direct_message_selects = False

    @classmethod
    def reset(cls):
        cls.visible = False
        cls.set_visible_error = None
        cls.set_visible_calls = []
        cls.keydown_calls = []
        cls.frame_click_calls = []
        cls.test_mouse_click_calls = []
        cls.label_frame_id = 0
        cls.send_frame_ui_message_calls = []
        cls.direct_message_selects = False

    @classmethod
    def IsWindowVisible(cls, window_id):
        return cls.visible

    @classmethod
    def SetWindowVisible(cls, window_id, visible):
        if cls.set_visible_error:
            raise cls.set_visible_error
        cls.set_visible_calls.append((window_id, visible))
        cls.visible = visible

    @classmethod
    def Keydown(cls, key, frame_id):
        cls.keydown_calls.append((key, frame_id))

    @classmethod
    def FrameClick(cls, frame_id):
        cls.frame_click_calls.append(frame_id)

    @classmethod
    def TestMouseClickAction(cls, frame_id, current_state, wparam_value, lparam_value=0):
        cls.test_mouse_click_calls.append((frame_id, current_state, wparam_value, lparam_value))

    @classmethod
    def GetFrameIDByLabel(cls, label):
        return cls.label_frame_id if label == "Inventory-Equipment" else 0

    @classmethod
    def SendFrameUIMessage(cls, frame_id, message_id, wparam, lparam=0):
        cls.send_frame_ui_message_calls.append((frame_id, message_id, wparam, lparam))
        valid_frame = frame_id and frame_id in {cls.label_frame_id, FakeHeroes.inventory_equipment_frame_id}
        if cls.direct_message_selects and valid_frame and message_id == 0x56:
            FakeHeroes.selected_agent_id = wparam
        return bool(valid_frame)


class FakeWindowID:
    WindowID_Inventory = 0x42


class FakeHeroes:
    hero_agent_id = 42
    selected_agent_id = 0
    inventory_equipment_frame_id = 0

    @classmethod
    def reset(cls):
        cls.hero_agent_id = 42
        cls.selected_agent_id = 0
        cls.inventory_equipment_frame_id = 0

    @classmethod
    def GetHeroAgentIDByPartyPosition(cls, hero_position):
        return cls.hero_agent_id if hero_position == 1 else 0

    @classmethod
    def GetNameByAgentID(cls, agent_id):
        return "Test Hero" if agent_id == cls.hero_agent_id else ""

    @classmethod
    def GetInventorySelectedAgentID(cls):
        return cls.selected_agent_id

    @classmethod
    def GetInventoryEquipmentFrameID(cls):
        return cls.inventory_equipment_frame_id


class HeroInventorySelectorTests(unittest.TestCase):
    def setUp(self):
        FakeUIManager.reset()
        FakeHeroes.reset()

        core = types.ModuleType("Py4GWCoreLib")
        core.UIManager = FakeUIManager
        core.WindowID = FakeWindowID
        core.Party = types.SimpleNamespace(Heroes=FakeHeroes)
        core.PyImGui = types.SimpleNamespace()

        enums_pkg = types.ModuleType("Py4GWCoreLib.enums_src")
        ui_enums = types.ModuleType("Py4GWCoreLib.enums_src.UI_enums")
        ui_enums.WindowID = FakeWindowID

        py4gw = types.ModuleType("Py4GW")
        py4gw.Console = types.SimpleNamespace(
            Log=lambda *args, **kwargs: None,
            MessageType=types.SimpleNamespace(Info=1, Warning=2, Error=3),
        )
        py4gw.Game = types.SimpleNamespace(enqueue=lambda callback: callback())

        sys.modules["Py4GWCoreLib"] = core
        sys.modules["Py4GWCoreLib.enums_src"] = enums_pkg
        sys.modules["Py4GWCoreLib.enums_src.UI_enums"] = ui_enums
        sys.modules["Py4GW"] = py4gw

        spec = importlib.util.spec_from_file_location("hero_inventory_selector_under_test", MODULE_PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_ensure_inventory_open_uses_idempotent_visibility_not_toggle(self):
        self.module._ensure_inventory_window_open()

        self.assertEqual(FakeUIManager.set_visible_calls, [(FakeWindowID.WindowID_Inventory, True)])
        self.assertEqual(FakeUIManager.keydown_calls, [])

    def test_select_hero_one_starts_native_retry_flow(self):
        self.module._select_hero_one()

        self.assertEqual(self.module._selection_state, "retry_native")
        self.assertEqual(FakeUIManager.set_visible_calls, [(FakeWindowID.WindowID_Inventory, True)])
        self.assertIn("Demande", self.module._last_status)

    def test_retry_flow_prefers_direct_inventory_equipment_frame_message(self):
        FakeUIManager.label_frame_id = 77
        FakeHeroes.inventory_equipment_frame_id = 77
        FakeUIManager.direct_message_selects = True

        self.module._select_hero_one()
        self.module._selection_next_action = 0.0
        self.module._tick_native_selection()
        self.module._selection_next_action = 0.0
        self.module._tick_native_selection()

        self.assertEqual(FakeUIManager.send_frame_ui_message_calls, [(77, 0x56, FakeHeroes.hero_agent_id, 0)])
        self.assertEqual(self.module._selection_state, "idle")
        self.assertIn("sélectionné", self.module._last_status)

    def test_direct_message_sent_without_confirmed_selection_retries_direct_message(self):
        FakeUIManager.label_frame_id = 77
        FakeHeroes.inventory_equipment_frame_id = 77

        self.module._select_hero_one()
        self.module._selection_next_action = 0.0
        self.module._tick_native_selection()
        self.module._selection_next_action = 0.0
        self.module._tick_native_selection()

        self.assertEqual(
            FakeUIManager.send_frame_ui_message_calls,
            [
                (77, 0x56, FakeHeroes.hero_agent_id, 0),
                (77, 0x56, FakeHeroes.hero_agent_id, 0),
            ],
        )
        self.assertEqual(self.module._selection_state, "retry_native")

    def test_retries_when_inventory_equipment_frame_appears_after_first_tick(self):
        FakeUIManager.direct_message_selects = True

        self.module._select_hero_one()
        self.module._selection_next_action = 0.0
        self.module._tick_native_selection()
        FakeHeroes.inventory_equipment_frame_id = 77
        self.module._selection_next_action = 0.0
        self.module._tick_native_selection()
        self.module._selection_next_action = 0.0
        self.module._tick_native_selection()

        self.assertEqual(FakeUIManager.send_frame_ui_message_calls, [(77, 0x56, FakeHeroes.hero_agent_id, 0)])
        self.assertEqual(self.module._selection_state, "idle")
        self.assertIn("sélectionné", self.module._last_status)

    def test_direct_message_uses_native_frame_resolver_when_label_lookup_fails(self):
        FakeHeroes.inventory_equipment_frame_id = 88
        FakeUIManager.direct_message_selects = True

        self.module._select_hero_one()
        self.module._selection_next_action = 0.0
        self.module._tick_native_selection()
        self.module._selection_next_action = 0.0
        self.module._tick_native_selection()

        self.assertEqual(FakeUIManager.send_frame_ui_message_calls, [(88, 0x56, FakeHeroes.hero_agent_id, 0)])
        self.assertEqual(self.module._selection_state, "idle")
        self.assertIn("sélectionné", self.module._last_status)

    def test_direct_message_does_not_bypass_guarded_native_zero_with_label_lookup(self):
        FakeUIManager.label_frame_id = 77

        self.module._select_hero_one()
        self.module._selection_next_action = 0.0
        self.module._tick_native_selection()

        self.assertEqual(FakeUIManager.send_frame_ui_message_calls, [])
        self.assertEqual(self.module._selection_direct_frame_id, 0)
        self.assertEqual(self.module._selection_state, "retry_native")

    def test_debug_details_include_python_direct_state_and_inventory_visibility(self):
        FakeUIManager.visible = True
        FakeHeroes.selected_agent_id = 17
        self.module._selection_direct_completed = True
        self.module._selection_direct_sent = True
        self.module._selection_direct_frame_id = 123

        details = self.module._selection_debug_details()

        self.assertIn("selected_agent_id=17", details)
        self.assertIn("direct_frame=123", details)
        self.assertIn("direct_sent=1", details)
        self.assertIn("inventory_visible=True", details)

    def test_safe_select_reports_runtime_errors_in_status(self):
        FakeUIManager.set_visible_error = RuntimeError("dll wrapper mismatch")

        self.module._safe_select_hero_one()

        self.assertEqual(self.module._selection_state, "idle")
        self.assertIn("Erreur sélection", self.module._last_status)
        self.assertIn("dll wrapper mismatch", self.module._last_status)

    def test_native_failure_does_not_fall_back_to_ui_clicks(self):
        self.module._select_hero_one()
        self.module._selection_native_attempts = self.module.NATIVE_RETRY_LIMIT
        self.module._selection_next_action = 0.0

        self.module._tick_native_selection()

        self.assertEqual(self.module._selection_state, "idle")
        self.assertIn("native impossible", self.module._last_status)
        self.assertEqual(FakeUIManager.frame_click_calls, [])
        self.assertEqual(FakeUIManager.test_mouse_click_calls, [])


if __name__ == "__main__":
    unittest.main()
