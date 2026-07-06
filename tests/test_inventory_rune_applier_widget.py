import importlib.util
import pathlib
import sys
import types
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "Widgets" / "Automation" / "Enhancements" / "Inventory Rune Applier.py"


class FakePyImGui:
    WindowFlags = types.SimpleNamespace(AlwaysAutoResize=1)
    clipboard_text = ""

    @classmethod
    def reset(cls):
        cls.clipboard_text = ""

    @classmethod
    def set_clipboard_text(cls, value):
        cls.clipboard_text = value


class FakeInventory:
    upgrade_slots = {}
    apply_calls = []
    validate_calls = []
    inventory_ids = {}
    equipped_items = {}
    validate_result = True

    @classmethod
    def reset(cls):
        cls.upgrade_slots = {}
        cls.apply_calls = []
        cls.validate_calls = []
        cls.inventory_ids = {}
        cls.equipped_items = {}
        cls.validate_result = True

    @classmethod
    def GetUpgradeSlot(cls, item_id):
        return cls.upgrade_slots.get(item_id, 0)

    @classmethod
    def GetInventoryIDFromAgent(cls, agent_id):
        return cls.inventory_ids.get(agent_id, 0)

    @classmethod
    def GetEquippedItemID(cls, inventory_id, equip_slot):
        return cls.equipped_items.get((inventory_id, equip_slot), 0)

    @classmethod
    def ValidateUpgrade(cls, target_item_id, upgrade_item_id):
        cls.validate_calls.append((target_item_id, upgrade_item_id))
        return cls.validate_result

    @classmethod
    def ApplyRuneToEquippedArmor(cls, agent_id, equip_slot, rune_item_id):
        cls.apply_calls.append((agent_id, equip_slot, rune_item_id))
        return True

    @classmethod
    def ApplyUpgrade(cls, inventory_id, target_item_id, upgrade_item_id, upgrade_slot=0, target_agent_id=0):
        cls.apply_calls.append((
            inventory_id,
            target_item_id,
            upgrade_item_id,
            upgrade_slot,
            target_agent_id,
        ))
        return True


class FakeItem:
    names = {}
    ready = {}
    requests = []

    @classmethod
    def reset(cls):
        cls.names = {}
        cls.ready = {}
        cls.requests = []

    @classmethod
    def RequestName(cls, item_id):
        cls.requests.append(item_id)

    @classmethod
    def IsNameReady(cls, item_id):
        return cls.ready.get(item_id, False)

    @classmethod
    def GetName(cls, item_id):
        return cls.names.get(item_id, "")


class FakeItemArray:
    item_ids = []

    @classmethod
    def reset(cls):
        cls.item_ids = []

    @staticmethod
    def CreateBagList(*bag_ids):
        return list(bag_ids)

    @classmethod
    def GetItemArray(cls, bags):
        return list(cls.item_ids)


class FakeHeroes:
    selected_agent_id = 0
    heroes = []
    names = {}

    @classmethod
    def reset(cls):
        cls.selected_agent_id = 0
        cls.heroes = []
        cls.names = {}

    @classmethod
    def GetInventorySelectedAgentID(cls):
        return cls.selected_agent_id

    @classmethod
    def GetNameByAgentID(cls, agent_id):
        return cls.names.get(agent_id, "")


class FakeParty:
    Heroes = FakeHeroes

    @staticmethod
    def GetHeroes():
        return list(FakeHeroes.heroes)


class FakePlayer:
    agent_id = 99

    @classmethod
    def GetAgentID(cls):
        return cls.agent_id


class FakeUIManager:
    send_calls = []
    send_result = True
    payload_logs = []
    clear_payload_calls = 0

    @classmethod
    def reset(cls):
        cls.send_calls = []
        cls.send_result = True
        cls.payload_logs = []
        cls.clear_payload_calls = 0

    @classmethod
    def SendUIMessage(cls, msgid, values, skip_hooks=False):
        cls.send_calls.append((msgid, list(values), skip_hooks))
        return cls.send_result

    @classmethod
    def GetUIMessageLogs(cls):
        return list(cls.payload_logs)

    @classmethod
    def ClearUIMessageLogs(cls):
        cls.clear_payload_calls += 1
        cls.payload_logs = []


class FakeUpgradeWindow:
    open = False
    confirm_calls = 0
    confirm_result = True

    @classmethod
    def reset(cls):
        cls.open = False
        cls.confirm_calls = 0
        cls.confirm_result = True

    @classmethod
    def IsOpen(cls):
        return cls.open

    @classmethod
    def Confirm(cls):
        cls.confirm_calls += 1
        return cls.confirm_result


class FakePacketLogEntry:
    def __init__(self, tick, direction, header, size, data):
        self.tick = tick
        self.direction = direction
        self.header = header
        self.size = size
        self.data = data


class FakePacketSniffer:
    logs = []
    initialize_calls = []
    clear_calls = []
    terminate_calls = []

    @classmethod
    def reset(cls):
        cls.logs = []
        cls.initialize_calls = []
        cls.clear_calls = []
        cls.terminate_calls = []

    @classmethod
    def initialize(cls, direction="both"):
        cls.initialize_calls.append(direction)
        return True

    @classmethod
    def terminate(cls, direction="both"):
        cls.terminate_calls.append(direction)

    @classmethod
    def get_logs(cls, direction="both"):
        if direction == "both":
            return list(cls.logs)
        return [entry for entry in cls.logs if entry.direction == direction]

    @classmethod
    def clear_logs(cls, direction="both"):
        cls.clear_calls.append(direction)
        if direction == "both":
            cls.logs = []
        else:
            cls.logs = [entry for entry in cls.logs if entry.direction != direction]

    @staticmethod
    def get_packet_name(direction, header):
        names = {
            0x0080: "ITEM_UPGRADE_BEGIN",
            0x007F: "ITEM_UPGRADE_ADD",
            0x0082: "ITEM_UPGRADE_END",
        }
        return names.get(header, f"0x{header:04X}")

    @staticmethod
    def decode_packet(direction, header, size, raw):
        words = []
        for offset in range(0, len(raw), 4):
            words.append(int.from_bytes(raw[offset:offset + 4], "little"))
        if header == 0x0080 and len(words) >= 3:
            return f"ITEM_UPGRADE_BEGIN size={size} | target_inventory_id={words[1]}, target_item_id={words[2]}"
        if header == 0x007F and len(words) >= 3:
            return f"ITEM_UPGRADE_ADD size={size} | upgrade_slot={words[1]}, upgrade_item_id={words[2]}"
        if header == 0x0082:
            return f"ITEM_UPGRADE_END size={size}"
        return f"0x{header:04X} size={size}"


class InventoryRuneApplierWidgetTests(unittest.TestCase):
    def setUp(self):
        FakePyImGui.reset()
        FakeInventory.reset()
        FakeItem.reset()
        FakeItemArray.reset()
        FakeHeroes.reset()
        FakeUIManager.reset()
        FakeUpgradeWindow.reset()
        FakePacketSniffer.reset()

        core = types.ModuleType("Py4GWCoreLib")
        core.PyImGui = FakePyImGui
        core.Inventory = FakeInventory
        core.Item = FakeItem
        core.ItemArray = FakeItemArray
        core.Party = FakeParty
        core.Player = FakePlayer
        core.PyImGui = FakePyImGui
        core.UIManager = FakeUIManager
        core.UpgradeWindow = FakeUpgradeWindow

        item_enums = types.ModuleType("Py4GWCoreLib.enums_src.Item_enums")
        item_enums.INVENTORY_BAGS = [types.SimpleNamespace(value=1), types.SimpleNamespace(value=2)]

        py4gw = types.ModuleType("Py4GW")
        py4gw.Console = types.SimpleNamespace(
            Log=lambda *args, **kwargs: None,
            MessageType=types.SimpleNamespace(Info=1, Warning=2, Error=3),
        )

        sys.modules["Py4GW"] = py4gw
        sys.modules["Py4GWCoreLib"] = core
        sys.modules["Py4GWCoreLib.enums_src.Item_enums"] = item_enums
        sys.modules["Py4GWCoreLib.PacketSniffer"] = types.SimpleNamespace(SNIFFER=FakePacketSniffer)

        spec = importlib.util.spec_from_file_location("inventory_rune_applier_under_test", MODULE_PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_rune_list_filters_native_rune_upgrade_slot(self):
        FakeItemArray.item_ids = [101, 202, 303]
        FakeInventory.upgrade_slots = {101: 1, 202: 7, 303: 0}
        FakeItem.names = {101: "Rune A", 202: "Insignia B"}
        FakeItem.ready = {101: True, 202: True}

        runes = self.module._get_inventory_rune_items()

        self.assertEqual(runes, [(101, "Rune A")])

    def test_safe_item_name_requests_name_and_uses_it_when_ready(self):
        self.assertEqual(self.module._safe_item_name(101), "item 101")
        self.assertEqual(FakeItem.requests, [101])

        FakeItem.ready = {101: True}
        FakeItem.names = {101: "Rune of Minor Vigor"}

        self.assertEqual(self.module._safe_item_name(101), "Rune of Minor Vigor")

    def test_apply_selected_rune_uses_native_item_upgrade_order_without_ui_confirmation(self):
        FakeItemArray.item_ids = [101]
        FakeInventory.upgrade_slots = {101: 1}
        FakeInventory.inventory_ids = {42: 321}
        FakeInventory.equipped_items = {(321, 3): 555}
        FakePlayer.agent_id = 42
        self.module._selected_target_agent_index = 0
        FakeUpgradeWindow.open = True
        self.module._selected_rune_index = 0
        self.module._selected_armor_slot_index = 1

        self.module._apply_selected_rune()

        self.assertEqual(FakeInventory.apply_calls, [(321, 555, 101, 1, 42)])
        self.assertEqual(FakeUIManager.send_calls, [])
        self.assertEqual(FakeUpgradeWindow.confirm_calls, 0)
        self.assertIsNone(self.module._pending_upgrade)
        self.assertIn("sent", self.module._last_status)

    def test_target_agent_options_include_player_and_present_heroes_by_name(self):
        FakePlayer.agent_id = 99
        FakeHeroes.heroes = [
            types.SimpleNamespace(agent_id=42),
            types.SimpleNamespace(agent_id=77),
            types.SimpleNamespace(agent_id=0),
        ]
        FakeHeroes.names = {42: "Ogden Stonehealer", 77: "Vekk"}

        options = self.module._get_target_agent_options()

        self.assertEqual(options, [
            (99, "Player (99)"),
            (42, "Ogden Stonehealer (42)"),
            (77, "Vekk (77)"),
        ])

    def test_target_agent_options_fallback_to_hero_position_when_name_missing(self):
        FakeHeroes.heroes = [
            types.SimpleNamespace(agent_id=42),
            types.SimpleNamespace(agent_id=77),
        ]
        FakeHeroes.names = {77: "Vekk"}

        options = self.module._get_target_agent_options()

        self.assertEqual(options[1], (42, "Hero 1 (42)"))
        self.assertEqual(options[2], (77, "Vekk (77)"))

    def test_selected_target_agent_uses_combo_choice_instead_of_inventory_selection(self):
        FakePlayer.agent_id = 99
        FakeHeroes.selected_agent_id = 42
        self.module._target_agent_options = [(99, "Player"), (77, "Vekk")]
        self.module._selected_target_agent_index = 1

        self.assertEqual(self.module._get_target_agent_id(), 77)

    def test_clamp_selected_indexes_clamps_target_when_hero_leaves_party(self):
        self.module._selected_target_agent_index = 4

        self.module._clamp_selected_indexes([(101, "Rune")], [(99, "Player")])

        self.assertEqual(self.module._selected_target_agent_index, 0)

    def test_apply_selected_rune_targets_selected_hero_option(self):
        FakeItemArray.item_ids = [101]
        FakeInventory.upgrade_slots = {101: 1}
        FakeInventory.inventory_ids = {77: 654}
        FakeInventory.equipped_items = {(654, 2): 888}
        FakePlayer.agent_id = 99
        FakeHeroes.heroes = [types.SimpleNamespace(agent_id=77)]
        FakeHeroes.names = {77: "Vekk"}
        self.module._selected_target_agent_index = 1
        self.module._selected_rune_index = 0
        self.module._selected_armor_slot_index = 0

        self.module._apply_selected_rune()

        self.assertEqual(FakeInventory.apply_calls, [(654, 888, 101, 1, 77)])
        self.assertIn("agent 77", self.module._last_status)

    def test_apply_selected_rune_rejects_second_order_while_upgrade_pending(self):
        self.module._pending_upgrade = {
            "rune_name": "Rune A",
            "armor_label": "Chest",
            "agent_id": 42,
            "started_at": 10.0,
        }

        result = self.module._apply_selected_rune()

        self.assertFalse(result)
        self.assertEqual(FakeUIManager.send_calls, [])
        self.assertIn("already pending", self.module._last_status)

    def test_describe_rune_application_reports_native_inputs(self):
        FakeInventory.inventory_ids = {42: 321}
        FakeInventory.equipped_items = {(321, 2): 555}
        FakeInventory.upgrade_slots = {101: 1}

        ok, diagnostic = self.module._describe_rune_application(42, 2, 101)

        self.assertTrue(ok)
        self.assertEqual(diagnostic, "inventory_id=321, target_item=555, upgrade_item=101, upgrade_slot=1")

    def test_describe_rune_application_rejects_same_target_and_rune_before_native_validation(self):
        FakeInventory.inventory_ids = {42: 321}
        FakeInventory.equipped_items = {(321, 2): 101}
        FakeInventory.upgrade_slots = {101: 1}

        ok, diagnostic = self.module._describe_rune_application(42, 2, 101)

        self.assertFalse(ok)
        self.assertEqual(diagnostic, "inventory_id=321, target_item=101, upgrade_item=101")
        self.assertEqual(FakeInventory.validate_calls, [])

    def test_describe_rune_application_reports_missing_target_item(self):
        FakeInventory.inventory_ids = {42: 321}

        ok, diagnostic = self.module._describe_rune_application(42, 2, 101)

        self.assertFalse(ok)
        self.assertEqual(diagnostic, "inventory_id=321, target_item=0")

    def test_advance_pending_upgrade_confirms_when_upgrade_window_opens(self):
        self.module._pending_upgrade = {
            "rune_name": "Rune A",
            "armor_label": "Chest",
            "agent_id": 42,
            "started_at": 10.0,
        }
        FakeUpgradeWindow.open = True

        self.assertTrue(self.module._advance_pending_upgrade(now=11.0))

        self.assertEqual(FakeUpgradeWindow.confirm_calls, 1)
        self.assertIsNone(self.module._pending_upgrade)
        self.assertIn("Confirmation", self.module._last_status)

    def test_advance_pending_upgrade_times_out_without_confirmation_window(self):
        self.module._pending_upgrade = {
            "rune_name": "Rune A",
            "armor_label": "Chest",
            "agent_id": 42,
            "started_at": 10.0,
        }

        self.assertFalse(self.module._advance_pending_upgrade(now=16.0))

        self.assertIsNone(self.module._pending_upgrade)
        self.assertIn("timed out", self.module._last_status)

    def test_payload_log_formatter_decodes_little_endian_words(self):
        line = self.module._format_ui_payload_log((
            1000,
            0x100001B4,
            True,
            False,
            0,
            [0x9A, 0x02, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00],
            [0x1F, 0x1B, 0x00, 0x00, 0x11, 0x4A, 0x00, 0x00],
        ))

        self.assertIn("msg=0x100001b4", line)
        self.assertIn("src=hook", line)
        self.assertIn("w=[0x0000029a, 0x00000008]", line)
        self.assertIn("l=[0x00001b1f, 0x00004a11]", line)

    def test_payload_capture_refreshes_recent_non_frame_logs_without_sending(self):
        self.module._start_ui_payload_capture()
        self.assertEqual(FakeUIManager.clear_payload_calls, 1)

        FakeUIManager.payload_logs = [
            (1000, 0x56, True, True, 77, [1, 0, 0, 0], []),
            (1001, 0x3000001D, False, False, 0, [2, 0, 0, 0], []),
            (1001, 0x100001B4, True, False, 0, [0x2A, 0, 0, 0], []),
        ]

        lines = self.module._refresh_ui_payload_capture(limit=5)

        self.assertEqual(len(lines), 2)
        self.assertIn("src=frame", lines[0])
        self.assertIn("msg=0x00000056", lines[0])
        self.assertIn("frame=77", lines[0])
        self.assertIn("msg=0x100001b4", lines[1])
        self.assertIn("w=[0x0000002a]", lines[1])
        self.assertEqual(FakeUIManager.send_calls, [])

    def test_payload_capture_uses_low_level_binding_when_core_facade_is_stale(self):
        get_method = FakeUIManager.GetUIMessageLogs
        clear_method = FakeUIManager.ClearUIMessageLogs
        delattr(FakeUIManager, "GetUIMessageLogs")
        delattr(FakeUIManager, "ClearUIMessageLogs")

        low_level_calls = {"clear": 0}

        class LowLevelUIManager:
            @staticmethod
            def clear_ui_message_logs():
                low_level_calls["clear"] += 1

            @staticmethod
            def get_ui_message_logs():
                return [(1001, 0x100001B4, True, False, 0, [0x2A, 0, 0, 0], [])]

        sys.modules["PyUIManager"] = types.SimpleNamespace(UIManager=LowLevelUIManager)
        try:
            self.assertTrue(self.module._start_ui_payload_capture())
            lines = self.module._refresh_ui_payload_capture(limit=5)
        finally:
            FakeUIManager.GetUIMessageLogs = get_method
            FakeUIManager.ClearUIMessageLogs = clear_method
            sys.modules.pop("PyUIManager", None)

        self.assertEqual(low_level_calls["clear"], 1)
        self.assertEqual(len(lines), 1)
        self.assertIn("msg=0x100001b4", lines[0])

    def test_payload_capture_can_copy_lines_to_clipboard(self):
        self.module._ui_payload_capture_lines = [
            "tick=1 src=hook msg=0x10000109 frame=0 w=[0x0000002a] l=[]",
            "tick=2 src=hook msg=0x100001b4 frame=0 w=[0x00000008] l=[]",
        ]

        self.assertTrue(self.module._copy_ui_payload_capture())

        self.assertIn("msg=0x10000109", FakePyImGui.clipboard_text)
        self.assertIn("msg=0x100001b4", FakePyImGui.clipboard_text)
        self.assertIn("copie", self.module._last_status)

    def test_clear_payload_capture_resets_native_buffer_and_displayed_lines(self):
        self.module._ui_payload_capture_active = True
        self.module._ui_payload_capture_lines = [
            "tick=1 src=hook msg=0x10000109 frame=0 w=[0x0000002a] l=[]",
        ]
        FakeUIManager.payload_logs = [
            (1001, 0x100001B4, True, False, 0, [0x2A, 0, 0, 0], []),
        ]

        self.assertTrue(self.module._clear_ui_payload_capture())

        self.assertEqual(FakeUIManager.clear_payload_calls, 1)
        self.assertEqual(FakeUIManager.payload_logs, [])
        self.assertEqual(self.module._ui_payload_capture_lines, [])
        self.assertTrue(self.module._ui_payload_capture_active)
        self.assertIn("reset", self.module._last_status)

    def test_ctos_packet_capture_formats_only_native_upgrade_order_packets(self):
        self.assertTrue(self.module._start_ctos_packet_capture())

        FakePacketSniffer.logs = [
            FakePacketLogEntry(100, "CToS", 0x0080, 12, (0x0080).to_bytes(4, "little") + (185).to_bytes(4, "little") + (3021).to_bytes(4, "little")),
            FakePacketLogEntry(101, "CToS", 0x007F, 12, (0x007F).to_bytes(4, "little") + (1).to_bytes(4, "little") + (19506).to_bytes(4, "little")),
            FakePacketLogEntry(102, "StoC", 0x0080, 12, (0x0080).to_bytes(4, "little") + (1).to_bytes(4, "little") + (2).to_bytes(4, "little")),
            FakePacketLogEntry(103, "CToS", 0x0082, 4, (0x0082).to_bytes(4, "little")),
        ]

        lines = self.module._refresh_ctos_packet_capture(limit=10)

        self.assertEqual(FakePacketSniffer.initialize_calls, ["CToS"])
        self.assertEqual(FakePacketSniffer.clear_calls, ["CToS"])
        self.assertEqual(len(lines), 3)
        self.assertIn("ITEM_UPGRADE_BEGIN", lines[0])
        self.assertIn("target_inventory_id=185", lines[0])
        self.assertIn("target_item_id=3021", lines[0])
        self.assertIn("ITEM_UPGRADE_ADD", lines[1])
        self.assertIn("upgrade_slot=1", lines[1])
        self.assertIn("upgrade_item_id=19506", lines[1])
        self.assertIn("ITEM_UPGRADE_END", lines[2])

    def test_clear_ctos_packet_capture_resets_packet_buffer_and_displayed_lines(self):
        self.module._ctos_packet_capture_active = True
        self.module._ctos_packet_capture_lines = ["tick=1 dir=CToS header=0x0080 ITEM_UPGRADE_BEGIN"]
        FakePacketSniffer.logs = [
            FakePacketLogEntry(100, "CToS", 0x0080, 12, b"\x80\x00\x00\x00"),
        ]

        self.assertTrue(self.module._clear_ctos_packet_capture())

        self.assertEqual(FakePacketSniffer.clear_calls, ["CToS"])
        self.assertEqual(FakePacketSniffer.logs, [])
        self.assertEqual(self.module._ctos_packet_capture_lines, [])
        self.assertTrue(self.module._ctos_packet_capture_active)
        self.assertIn("CToS", self.module._last_status)


if __name__ == "__main__":
    unittest.main()
