import importlib.util
import json
import pathlib
import struct
import sys
import tempfile
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WIDGET_PATH = ROOT / "Widgets" / "Guild Wars" / "Crystal Desert Teleporter.py"


class WidgetHarness:
    STUB_MODULES = (
        "Py4GW",
        "PyAgent",
        "PyImGui",
        "Py4GWCoreLib",
        "Py4GWCoreLib.Agent",
        "Py4GWCoreLib.AgentArray",
        "Py4GWCoreLib.CrystalDesertTeleporter",
        "Py4GWCoreLib.PacketSniffer",
        "Py4GWCoreLib.Player",
        "Py4GWCoreLib.Routines",
    )

    def __init__(self, temp_dir: pathlib.Path):
        self.temp_dir = temp_dir
        self.agents = {}
        self.packet_logs = []
        self.console_logs = []
        self.player_xy = (0.0, 0.0)
        self.target_id = 0
        self.moves = []
        self.interactions = []
        self.text_lines = []
        self.initialize_results = {"both": True, "StoC": True, "CToS": True}
        self.initialize_calls = []
        self.buttons = set()
        self._saved_modules = {}
        self.module = None

    def install(self):
        sentinel = object()
        self._sentinel = sentinel
        for name in self.STUB_MODULES:
            self._saved_modules[name] = sys.modules.get(name, sentinel)

        harness = self

        py4gw = types.ModuleType("Py4GW")

        class ConsoleMessageType:
            Info = "Info"
            Warning = "Warning"
            Error = "Error"

        class Console:
            MessageType = ConsoleMessageType

            @staticmethod
            def Log(module_name, message, message_type=ConsoleMessageType.Info):
                harness.console_logs.append((module_name, message, message_type))

        py4gw.Console = Console
        sys.modules["Py4GW"] = py4gw

        pyagent = types.ModuleType("PyAgent")

        class PyAgentObject:
            def __init__(self, agent_id):
                self.agent_id = int(agent_id)
                self.visual_effects = int(harness.agents.get(int(agent_id), {}).get("visual_effects", 0))

            def GetContext(self):
                return True

        class PyGadgetAgentObject:
            def __init__(self, agent_id):
                self.agent_id = int(agent_id)
                agent = harness.agents.get(int(agent_id), {})
                self.h00C4 = int(agent.get("h00C4", 0))
                self.h00C8 = int(agent.get("h00C8", 0))
                self.h00D4 = list(agent.get("h00D4", []))

            def GetContext(self):
                return True

        pyagent.PyAgent = PyAgentObject
        pyagent.PyGadgetAgent = PyGadgetAgentObject
        sys.modules["PyAgent"] = pyagent

        pyimgui = types.ModuleType("PyImGui")
        pyimgui.ImGuiCond = types.SimpleNamespace(FirstUseEver=1)
        pyimgui.WindowFlags = types.SimpleNamespace(AlwaysAutoResize=1)
        pyimgui.begin_tooltip = lambda: True
        pyimgui.end_tooltip = lambda: None
        pyimgui.text = lambda value, *_args, **_kwargs: harness.text_lines.append(str(value))
        pyimgui.separator = lambda: None
        pyimgui.same_line = lambda *_args, **_kwargs: None
        pyimgui.checkbox = lambda _label, value: bool(value)
        pyimgui.set_next_window_size = lambda *_args, **_kwargs: None
        pyimgui.begin = lambda *_args, **_kwargs: True
        pyimgui.end = lambda: None

        def button(label):
            return label in harness.buttons

        pyimgui.button = button
        sys.modules["PyImGui"] = pyimgui

        core_package = types.ModuleType("Py4GWCoreLib")
        core_package.__path__ = [str(ROOT / "Py4GWCoreLib")]
        sys.modules["Py4GWCoreLib"] = core_package

        core_name = "Py4GWCoreLib.CrystalDesertTeleporter"
        core_path = ROOT / "Py4GWCoreLib" / "CrystalDesertTeleporter.py"
        core_spec = importlib.util.spec_from_file_location(core_name, core_path)
        core_module = importlib.util.module_from_spec(core_spec)
        sys.modules[core_name] = core_module
        core_spec.loader.exec_module(core_module)

        agent_module = types.ModuleType("Py4GWCoreLib.Agent")

        class Agent:
            @staticmethod
            def IsGadget(agent_id):
                return int(agent_id) in harness.agents

            @staticmethod
            def GetXY(agent_id):
                agent = harness.agents[int(agent_id)]
                return agent["x"], agent["y"]

            @staticmethod
            def GetNameByID(agent_id):
                return harness.agents[int(agent_id)].get("name", "")

            @staticmethod
            def GetGadgetID(agent_id):
                return harness.agents[int(agent_id)]["gadget_id"]

            @staticmethod
            def GetGadgetAgentExtraType(agent_id):
                return harness.agents[int(agent_id)].get("extra_type", 0)

        agent_module.Agent = Agent
        sys.modules["Py4GWCoreLib.Agent"] = agent_module

        agent_array_module = types.ModuleType("Py4GWCoreLib.AgentArray")

        class AgentArray:
            @staticmethod
            def GetGadgetArray():
                return list(harness.agents)

        agent_array_module.AgentArray = AgentArray
        sys.modules["Py4GWCoreLib.AgentArray"] = agent_array_module

        packet_sniffer_module = types.ModuleType("Py4GWCoreLib.PacketSniffer")

        class PacketSniffer:
            def initialize(self, direction="both", *_args, **_kwargs):
                harness.initialize_calls.append(direction)
                return harness.initialize_results.get(direction, True)

            def get_logs(self, *_args, **_kwargs):
                return list(harness.packet_logs)

            def clear_logs(self, *_args, **_kwargs):
                harness.packet_logs.clear()

            def terminate(self, *_args, **_kwargs):
                return None

        packet_sniffer_module.SNIFFER = PacketSniffer()
        sys.modules["Py4GWCoreLib.PacketSniffer"] = packet_sniffer_module

        player_module = types.ModuleType("Py4GWCoreLib.Player")

        class Player:
            @staticmethod
            def GetXY():
                return harness.player_xy

            @staticmethod
            def Move(x, y):
                harness.moves.append((float(x), float(y)))

            @staticmethod
            def Interact(agent_id, call_target):
                harness.interactions.append((int(agent_id), bool(call_target)))

            @staticmethod
            def GetTargetID():
                return int(harness.target_id)

        player_module.Player = Player
        sys.modules["Py4GWCoreLib.Player"] = player_module

        routines_module = types.ModuleType("Py4GWCoreLib.Routines")

        class Checks:
            class Map:
                @staticmethod
                def MapValid():
                    return True

        routines_module.Checks = Checks
        sys.modules["Py4GWCoreLib.Routines"] = routines_module

        module_name = "crystal_desert_teleporter_widget_under_test"
        spec = importlib.util.spec_from_file_location(module_name, WIDGET_PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        module.MAPPING_FILE = str(self.temp_dir / "CrystalDesertTeleporterMappings.json")
        module._platform_mappings_loaded = False
        module._platform_mappings.clear()
        self.module = module
        return module

    def restore(self):
        for name, previous in self._saved_modules.items():
            if previous is self._sentinel:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
        sys.modules.pop("crystal_desert_teleporter_widget_under_test", None)

    def add_gadget(self, agent_id, gadget_id, x, y, name="Teleporter Switch"):
        self.agents[int(agent_id)] = {
            "gadget_id": int(gadget_id),
            "x": float(x),
            "y": float(y),
            "name": name,
            "extra_type": 0,
            "visual_effects": 0,
            "h00C4": 0,
            "h00C8": 0,
            "h00D4": [],
        }

    def set_runtime(self, agent_id, *, visual_effects=None, h00C4=None, h00C8=None, h00D4=None):
        agent = self.agents[int(agent_id)]
        if visual_effects is not None:
            agent["visual_effects"] = int(visual_effects)
        if h00C4 is not None:
            agent["h00C4"] = int(h00C4)
        if h00C8 is not None:
            agent["h00C8"] = int(h00C8)
        if h00D4 is not None:
            agent["h00D4"] = [int(value) for value in h00D4]

    def add_packet(self, direction, tick, header, data):
        self.packet_logs.append(
            types.SimpleNamespace(
                direction=direction,
                tick=int(tick),
                header=int(header),
                size=len(data),
                data=data,
            )
        )

    def add_world_create_packet(self, tick, agent_id, gadget_id):
        self.add_packet(
            "StoC",
            tick,
            0x0020,
            struct.pack("<IIIIII", 0x0020, int(agent_id), int(gadget_id), 2, 1, tick),
        )

    def add_client_click_packet(self, tick, paired_agent_id, clicked_agent_id):
        self.add_packet(
            "CToS",
            tick,
            0x00C1,
            struct.pack("<III", 0x00C1, int(paired_agent_id), int(clicked_agent_id)),
        )

    def add_client_reset_packet(self, tick, target_agent_id):
        self.add_packet(
            "CToS",
            tick,
            0x00C1,
            struct.pack("<III", 0x00C1, 48, int(target_agent_id)),
        )

    def add_client_interact_packet(self, tick, agent_id, flag=0):
        self.add_packet(
            "CToS",
            tick,
            0x0039,
            struct.pack("<III", 0x0039, int(agent_id), int(flag)),
        )


class CrystalDesertTeleporterWidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.harness = WidgetHarness(pathlib.Path(self.temp.name))
        self.widget = self.harness.install()

    def tearDown(self):
        self.harness.restore()
        self.temp.cleanup()

    def set_known_return_platform(self):
        for agent_id, gadget_id, x, y in (
            (13, 705, -2528.0, -10037.0),
            (14, 706, -2525.0, -9760.0),
            (15, 707, -2384.0, -10418.0),
            (16, 708, -2188.0, -10514.0),
            (18, 713, 3034.0, -9498.0),
            (20, 715, 3040.0, -9044.0),
            (21, 716, 2823.0, -8883.0),
            (19, 714, 2951.0, -9737.0),
        ):
            self.harness.add_gadget(agent_id, gadget_id, x, y)
        self.widget._candidate_switches = [
            self.widget.GadgetSnapshot(agent_id=18, x=3034.0, y=-9498.0, gadget_id=713),
            self.widget.GadgetSnapshot(agent_id=20, x=3040.0, y=-9044.0, gadget_id=715),
            self.widget.GadgetSnapshot(agent_id=21, x=2823.0, y=-8883.0, gadget_id=716),
            self.widget.GadgetSnapshot(agent_id=19, x=2951.0, y=-9737.0, gadget_id=714),
        ]

    def set_known_forward_platform(self):
        for agent_id, gadget_id, x, y in (
            (118, 713, 3034.0, -9498.0),
            (120, 715, 3040.0, -9044.0),
            (121, 716, 2823.0, -8883.0),
            (119, 714, 2951.0, -9737.0),
            (113, 705, -2528.0, -10037.0),
            (114, 706, -2525.0, -9760.0),
            (115, 707, -2384.0, -10418.0),
            (116, 708, -2188.0, -10514.0),
        ):
            self.harness.add_gadget(agent_id, gadget_id, x, y)
        self.widget._candidate_switches = [
            self.widget.GadgetSnapshot(agent_id=113, x=-2528.0, y=-10037.0, gadget_id=705),
            self.widget.GadgetSnapshot(agent_id=114, x=-2525.0, y=-9760.0, gadget_id=706),
            self.widget.GadgetSnapshot(agent_id=115, x=-2384.0, y=-10418.0, gadget_id=707),
            self.widget.GadgetSnapshot(agent_id=116, x=-2188.0, y=-10514.0, gadget_id=708),
        ]

    def set_live_forward_platform(self):
        for agent_id, gadget_id, x, y in (
            (21, 716, 2823.0, -8883.0),
            (19, 714, 2951.0, -9737.0),
            (18, 713, 3034.0, -9498.0),
            (20, 715, 3040.0, -9044.0),
            (13, 705, -2528.0, -10037.0),
            (14, 706, -2525.0, -9760.0),
            (15, 707, -2384.0, -10418.0),
            (16, 708, -2188.0, -10514.0),
        ):
            self.harness.add_gadget(agent_id, gadget_id, x, y)
        self.widget._candidate_switches = [
            self.widget.GadgetSnapshot(agent_id=13, x=-2528.0, y=-10037.0, name="Teleporter Switch", gadget_id=705),
            self.widget.GadgetSnapshot(agent_id=14, x=-2525.0, y=-9760.0, name="Teleporter Switch", gadget_id=706),
            self.widget.GadgetSnapshot(agent_id=15, x=-2384.0, y=-10418.0, name="Teleporter Switch", gadget_id=707),
            self.widget.GadgetSnapshot(agent_id=16, x=-2188.0, y=-10514.0, name="Teleporter Switch", gadget_id=708),
        ]

    def set_unknown_platform(self):
        for agent_id, gadget_id, x, y in (
            (201, 801, -100.0, -400.0),
            (202, 802, -120.0, -300.0),
            (203, 803, -110.0, -200.0),
            (204, 804, -90.0, -100.0),
            (301, 901, 100.0, 100.0),
            (302, 902, 120.0, 200.0),
            (303, 903, 110.0, 300.0),
            (304, 904, 90.0, 400.0),
        ):
            self.harness.add_gadget(agent_id, gadget_id, x, y)
        self.widget._candidate_switches = [
            self.widget.GadgetSnapshot(agent_id=301, x=100.0, y=100.0, gadget_id=901),
            self.widget.GadgetSnapshot(agent_id=302, x=120.0, y=200.0, gadget_id=902),
            self.widget.GadgetSnapshot(agent_id=303, x=110.0, y=300.0, gadget_id=903),
            self.widget.GadgetSnapshot(agent_id=304, x=90.0, y=400.0, gadget_id=904),
        ]

    def add_other_unknown_platform_markers(self):
        for agent_id, gadget_id, x, y in (
            (211, 811, -500.0, -400.0),
            (212, 812, -520.0, -300.0),
            (213, 813, -510.0, -200.0),
            (214, 814, -490.0, -100.0),
        ):
            self.harness.add_gadget(agent_id, gadget_id, x, y)

    def process_known_return_burst(self):
        for tick, agent_id, gadget_id in (
            (1000, 16, 708),
            (1010, 15, 707),
            (1020, 14, 706),
            (1030, 13, 705),
        ):
            self.harness.add_world_create_packet(tick, agent_id, gadget_id)
        self.widget._capturing = True
        self.widget._process_capture()

    def process_known_forward_burst(self):
        for tick, agent_id, gadget_id in (
            (3000, 121, 716),
            (3010, 119, 714),
            (3020, 118, 713),
            (3030, 120, 715),
        ):
            self.harness.add_world_create_packet(tick, agent_id, gadget_id)
        self.widget._capturing = True
        self.widget._process_capture()

    def process_live_forward_burst(self):
        for tick, agent_id, gadget_id in (
            (5000, 21, 716),
            (5010, 19, 714),
            (5020, 18, 713),
            (5030, 20, 715),
        ):
            self.harness.add_world_create_packet(tick, agent_id, gadget_id)
        self.widget._capturing = True
        self.widget._process_capture()

    def process_unknown_burst(self):
        for tick, agent_id, gadget_id in (
            (2000, 204, 804),
            (2010, 203, 803),
            (2020, 202, 802),
            (2030, 201, 801),
        ):
            self.harness.add_world_create_packet(tick, agent_id, gadget_id)
        self.widget._capturing = True
        self.widget._process_capture()

    def process_other_unknown_burst(self):
        for tick, agent_id, gadget_id in (
            (3000, 214, 814),
            (3010, 213, 813),
            (3020, 212, 812),
            (3030, 211, 811),
        ):
            self.harness.add_world_create_packet(tick, agent_id, gadget_id)
        self.widget._capturing = True
        self.widget._process_capture()

    def write_mapping_file(self, signature, pairs):
        self.widget._PERSISTENT_MAPPINGS_ENABLED = True
        payload = {
            "version": 1,
            "mappings": [
                {
                    "signature": signature,
                    "source": "manual",
                    "marker_to_switch_gadget_ids": [list(pair) for pair in pairs],
                }
            ],
        }
        pathlib.Path(self.widget.MAPPING_FILE).write_text(json.dumps(payload), encoding="utf-8")
        self.widget._platform_mappings_loaded = False
        self.widget._platform_mappings.clear()

    def write_legacy_untrusted_mapping_file(self, signature, pairs):
        payload = {
            "version": 1,
            "mappings": [
                {
                    "signature": signature,
                    "marker_to_switch_gadget_ids": [list(pair) for pair in pairs],
                }
            ],
        }
        pathlib.Path(self.widget.MAPPING_FILE).write_text(json.dumps(payload), encoding="utf-8")
        self.widget._platform_mappings_loaded = False
        self.widget._platform_mappings.clear()

    def install_known_return_mapping(self):
        self.write_mapping_file(
            "markers=705,706,707,708|switches=713,714,715,716",
            ((708, 713), (707, 714), (706, 715), (705, 716)),
        )

    def install_known_forward_mapping(self):
        self.write_mapping_file(
            "markers=713,714,715,716|switches=705,706,707,708",
            ((716, 706), (714, 708), (713, 705), (715, 707)),
        )

    def test_selected_target_summary_identifies_switch_candidate_row(self):
        self.set_known_return_platform()
        self.harness.target_id = 20

        summary = self.widget._selected_target_summary()

        self.assertEqual(
            summary,
            "Selected target: agent=20 switch-row=2 gadget=715 name=Teleporter Switch xy=(3040, -9044)",
        )

    def test_selected_target_summary_handles_non_switch_target(self):
        self.set_known_return_platform()
        self.harness.target_id = 999

        summary = self.widget._selected_target_summary()

        self.assertEqual(summary, "Selected target: agent=999 not in switch candidates")

    def test_switch_table_marks_selected_switch(self):
        self.set_known_return_platform()
        self.harness.target_id = 20

        self.widget._draw_switch_table()

        self.assertTrue(
            any("[selected]" in line and "agent=20" in line for line in self.harness.text_lines),
            self.harness.text_lines,
        )

    def test_add_selected_records_current_target_for_manual_calibration(self):
        self.set_known_return_platform()
        self.process_known_return_burst()
        self.harness.target_id = 18
        self.harness.buttons.add("Forget learned")
        self.widget._draw_controls()
        self.harness.buttons.clear()
        self.harness.buttons.add("Add selected")

        self.widget._draw_controls()

        self.assertEqual(self.widget._manual_calibration_sequence, [18])
        self.assertIn("Manual calibration: 1/4", self.widget._status)

    def test_add_selected_warns_when_target_is_not_a_switch_candidate(self):
        self.set_known_return_platform()
        self.process_known_return_burst()
        self.harness.target_id = 999
        self.harness.buttons.add("Forget learned")
        self.widget._draw_controls()
        self.harness.buttons.clear()
        self.harness.buttons.add("Add selected")

        self.widget._draw_controls()

        self.assertEqual(self.widget._manual_calibration_sequence, [])
        self.assertEqual(self.widget._status, "Selected target 999 is not one of the selected switches.")

    def test_set_selected_position_calibrates_last_switch_from_live_forward_platform(self):
        self.widget._PERSISTENT_MAPPINGS_ENABLED = True
        self.set_live_forward_platform()
        self.process_live_forward_burst()
        self.assertEqual(self.widget._pending_platform_sequence, [21, 19, 18, 20])
        self.assertIsNone(self.widget._click_plan)

        for target_id, button in (
            (13, "Set #4"),
            (14, "Set #1"),
            (16, "Set #2"),
            (15, "Set #3"),
        ):
            self.harness.target_id = target_id
            self.harness.buttons = {button}
            self.widget._draw_controls()

        self.assertEqual(self.widget._recorder.sequence, [14, 16, 15, 13])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 14)
        self.assertEqual(self.widget._manual_calibration_slots, [0, 0, 0, 0])
        payload = json.loads(pathlib.Path(self.widget.MAPPING_FILE).read_text(encoding="utf-8"))
        mappings = {
            item["signature"]: tuple(tuple(pair) for pair in item["marker_to_switch_gadget_ids"])
            for item in payload["mappings"]
        }
        self.assertEqual(
            mappings["markers=713,714,715,716|switches=705,706,707,708"],
            ((716, 706), (714, 708), (713, 707), (715, 705)),
        )

    def test_switch_table_add_buttons_enter_current_sequence_without_saving_by_default(self):
        self.set_live_forward_platform()
        self.process_live_forward_burst()
        self.assertEqual(self.widget._pending_platform_sequence, [21, 19, 18, 20])
        self.assertIsNone(self.widget._click_plan)

        for agent_id in (15, 14, 16, 13):
            self.harness.buttons = {f"Add##cdt_manual_{agent_id}"}
            self.widget._draw_switch_table()

        self.assertEqual(self.widget._recorder.sequence, [15, 14, 16, 13])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 15)
        self.assertIn("current attempt", self.widget._status)
        self.assertFalse(pathlib.Path(self.widget.MAPPING_FILE).exists())

    def test_platform_burst_markers_are_tracked_for_follow_up_server_probes(self):
        self.set_live_forward_platform()
        self.process_live_forward_burst()

        self.assertEqual(
            [(marker.agent_id, marker.gadget_id) for marker in self.widget._platform_markers],
            [(21, 716), (19, 714), (18, 713), (20, 715)],
        )

        self.harness.add_packet(
            "StoC",
            6000,
            0x0108,
            struct.pack("<III", 0x0108, 716, 123),
        )
        self.widget._process_capture()

        self.assertIn("0x0108 size=12 words=716 123", self.widget._last_probe_packets)

    def test_direct_marker_state_packets_are_logged_without_faking_switch_sequence(self):
        self.set_live_forward_platform()
        self.process_live_forward_burst()
        self.harness.add_packet(
            "StoC",
            6000,
            0x0115,
            struct.pack("<III", 0x0115, 21, 1),
        )

        self.widget._process_capture()

        self.assertIn("0x0115 marker agent=21 state=0x1 tick=6000", self.widget._last_events)
        self.assertEqual(self.widget._recorder.sequence, [])
        self.assertIsNone(self.widget._click_plan)

    def test_direct_switch_state_packets_still_record_switch_sequence(self):
        self.set_live_forward_platform()
        self.widget._capturing = True
        self.harness.add_packet(
            "StoC",
            6000,
            0x0115,
            struct.pack("<III", 0x0115, 14, 1),
        )

        self.widget._process_capture()

        self.assertEqual(self.widget._recorder.sequence, [14])
        self.assertIn("0x0115 agent=14 state=0x1 tick=6000", self.widget._last_events)

    def test_runtime_match_maps_random_burst_to_switch_sequence_when_keys_are_unique(self):
        self.set_unknown_platform()
        runtime_pairs = (
            (204, 301, 9001),
            (203, 304, 9004),
            (202, 302, 9002),
            (201, 303, 9003),
        )
        for marker_agent, switch_agent, key in runtime_pairs:
            self.harness.set_runtime(marker_agent, h00C8=key, h00D4=(2, 16, key + 10, key + 20))
            self.harness.set_runtime(switch_agent, h00C8=key, h00D4=(2, 16, key + 10, key + 20))

        self.process_unknown_burst()

        self.assertEqual(self.widget._recorder.sequence, [301, 304, 302, 303])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 301)
        self.assertIn("Sequence matched from live runtime fields", self.widget._status)

    def test_records_first_raw_server_packets_after_platform_burst(self):
        self.set_unknown_platform()
        self.process_unknown_burst()
        self.harness.add_packet(
            "StoC",
            2500,
            0x00A1,
            struct.pack("<IIII", 0x00A1, 777, 888, 999),
        )

        self.widget._process_capture()

        self.assertIn("StoC 0x00A1 AGENT_PROPERTY_PLAY_EFFECT size=16 words=777 888 999 bytes=16", self.widget._last_raw_server_packets)
        self.assertEqual(self.widget._raw_server_header_counts[0x00A1], 1)

    def test_raw_server_packet_summary_marks_truncated_stoc_payload(self):
        packet = self.widget.RawPacket(
            direction="StoC",
            tick=2500,
            header=0x0029,
            size=5,
            data=struct.pack("<IB", 0x0029, 18),
        )

        summary = self.widget._raw_server_packet_summary(packet)

        self.assertIn("bytes=5", summary)
        self.assertIn("truncated", summary)

    def test_raw_server_packet_summary_decodes_agent_move_to_point(self):
        packet = self.widget.RawPacket(
            direction="StoC",
            tick=2500,
            header=0x0029,
            size=16,
            data=struct.pack("<IIff", 0x0029, 18, 3034.0, -9498.0),
        )

        summary = self.widget._raw_server_packet_summary(packet)

        self.assertIn("agent=18", summary)
        self.assertIn("x=3034", summary)
        self.assertIn("y=-9498", summary)

    def test_process_capture_warns_when_native_sniffer_returns_truncated_stoc_after_burst(self):
        self.set_unknown_platform()
        self.process_unknown_burst()
        self.harness.add_packet("StoC", 2500, 0x0115, b"\x15\x01\x00")

        self.widget._process_capture()

        self.assertIn("native PacketSniffer is still truncating StoC payloads", self.widget._status)

    def test_widget_does_not_reuse_live_forward_mapping_in_opposite_direction(self):
        self.set_live_forward_platform()
        self.process_live_forward_burst()
        for agent_id in (15, 14, 16, 13):
            self.harness.buttons = {f"Add##cdt_manual_{agent_id}"}
            self.widget._draw_switch_table()

        self.widget._recorder.clear()
        self.widget._world_create_recorder.clear()
        self.widget._pending_platform_sequence.clear()
        self.widget._click_plan = None
        self.set_known_return_platform()

        self.process_known_return_burst()

        self.assertEqual(self.widget._recorder.sequence, [])
        self.assertIsNone(self.widget._click_plan)
        self.assertIn("Random platform burst captured", self.widget._status)

    def test_widget_ignores_legacy_untrusted_platform_mapping_file(self):
        self.write_legacy_untrusted_mapping_file(
            "markers=713,714,715,716|switches=705,706,707,708",
            ((716, 706), (714, 708), (713, 705), (715, 707)),
        )
        self.set_known_forward_platform()

        self.process_known_forward_burst()

        self.assertEqual(self.widget._recorder.sequence, [])
        self.assertIsNone(self.widget._click_plan)
        self.assertEqual(self.widget._pending_platform_sequence, [121, 119, 118, 120])
        self.assertIn("Random platform burst captured", self.widget._status)

    def test_widget_maps_known_return_platform_burst_to_click_plan_after_learning(self):
        self.install_known_return_mapping()
        self.set_known_return_platform()

        self.process_known_return_burst()

        self.assertEqual(self.widget._recorder.sequence, [18, 19, 20, 21])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 18)
        self.assertEqual(self.widget._status, "Sequence mapped from platform burst.")

    def test_widget_maps_new_platform_burst_after_previous_plan_is_complete(self):
        self.install_known_return_mapping()
        self.set_known_return_platform()
        self.process_known_return_burst()
        for agent_id in (18, 19, 20, 21):
            self.widget._click_plan.mark_clicked(agent_id)
        self.assertTrue(self.widget._click_plan.complete)
        self.install_known_forward_mapping()
        self.set_known_forward_platform()

        self.process_known_forward_burst()

        self.assertEqual(self.widget._recorder.sequence, [114, 116, 113, 115])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 114)
        self.assertEqual(self.widget._status, "Sequence mapped from platform burst.")

    def test_widget_uses_manual_mapping_file_override(self):
        self.write_mapping_file(
            "markers=705,706,707,708|switches=713,714,715,716",
            ((708, 715), (707, 713), (706, 716), (705, 714)),
        )
        self.set_known_return_platform()

        self.process_known_return_burst()

        self.assertEqual(self.widget._recorder.sequence, [20, 18, 21, 19])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 20)

    def test_widget_agent_selection_packets_do_not_recalibrate_when_known_plan_already_exists(self):
        self.install_known_return_mapping()
        self.set_known_return_platform()
        self.process_known_return_burst()
        for tick, paired, clicked in (
            (1100, 18, 19),
            (1110, 19, 20),
            (1120, 20, 21),
            (1130, 21, 18),
        ):
            self.harness.add_client_click_packet(tick, paired, clicked)

        self.widget._process_capture()

        self.assertEqual(self.widget._recorder.sequence, [18, 19, 20, 21])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 18)
        payload = json.loads(pathlib.Path(self.widget.MAPPING_FILE).read_text(encoding="utf-8"))
        mappings = {
            item["signature"]: tuple(tuple(pair) for pair in item["marker_to_switch_gadget_ids"])
            for item in payload["mappings"]
        }
        self.assertEqual(
            mappings["markers=705,706,707,708|switches=713,714,715,716"],
            ((708, 713), (707, 714), (706, 715), (705, 716)),
        )

    def test_manual_calibration_overrides_existing_mapped_plan(self):
        self.install_known_forward_mapping()
        self.set_known_forward_platform()
        self.process_known_forward_burst()
        self.assertEqual(self.widget._recorder.sequence, [114, 116, 113, 115])

        for agent_id in (113, 114, 115, 116):
            self.widget._record_manual_calibration_switch(agent_id)

        self.assertEqual(self.widget._recorder.sequence, [113, 114, 115, 116])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 113)
        payload = json.loads(pathlib.Path(self.widget.MAPPING_FILE).read_text(encoding="utf-8"))
        mappings = {
            item["signature"]: tuple(tuple(pair) for pair in item["marker_to_switch_gadget_ids"])
            for item in payload["mappings"]
        }
        self.assertEqual(
            mappings["markers=713,714,715,716|switches=705,706,707,708"],
            ((716, 705), (714, 706), (713, 707), (715, 708)),
        )

        self.widget._recorder.clear()
        self.widget._world_create_recorder.clear()
        self.widget._pending_platform_sequence.clear()
        self.widget._click_plan = None
        self.widget._platform_mappings_loaded = False
        self.widget._platform_mappings.clear()
        self.process_known_forward_burst()

        self.assertEqual(self.widget._recorder.sequence, [113, 114, 115, 116])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 113)

    def test_forget_learned_mappings_clears_saved_plan_but_keeps_pending_burst(self):
        self.install_known_forward_mapping()
        self.set_known_forward_platform()
        self.process_known_forward_burst()
        self.assertEqual(self.widget._recorder.sequence, [114, 116, 113, 115])
        self.harness.buttons.add("Forget learned")

        self.widget._draw_controls()

        self.assertEqual(self.widget._recorder.sequence, [])
        self.assertIsNone(self.widget._click_plan)
        self.assertEqual(self.widget._pending_platform_sequence, [121, 119, 118, 120])
        self.assertEqual(self.widget._platform_mappings, {})
        payload = json.loads(pathlib.Path(self.widget.MAPPING_FILE).read_text(encoding="utf-8"))
        self.assertEqual(payload["mappings"], [])
        self.assertIn("Learned mappings cleared", self.widget._status)

        for agent_id in (113, 114, 115, 116):
            self.widget._record_manual_calibration_switch(agent_id)

        self.assertEqual(self.widget._recorder.sequence, [113, 114, 115, 116])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 113)

    def test_learn_clicks_mode_relearns_sequence_when_wrong_plan_shares_prefix(self):
        self.install_known_forward_mapping()
        self.set_known_forward_platform()
        self.process_known_forward_burst()
        self.assertEqual(self.widget._recorder.sequence, [114, 116, 113, 115])
        self.harness.buttons.add("Learn clicks")

        self.widget._draw_controls()
        for tick, agent_id in (
            (4100, 114),
            (4110, 116),
            (4120, 115),
            (4130, 113),
        ):
            self.harness.add_client_interact_packet(tick, agent_id)
        self.widget._process_capture()

        self.assertEqual(self.widget._recorder.sequence, [114, 116, 115, 113])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 114)
        payload = json.loads(pathlib.Path(self.widget.MAPPING_FILE).read_text(encoding="utf-8"))
        mappings = {
            item["signature"]: tuple(tuple(pair) for pair in item["marker_to_switch_gadget_ids"])
            for item in payload["mappings"]
        }
        self.assertEqual(
            mappings["markers=713,714,715,716|switches=705,706,707,708"],
            ((716, 706), (714, 708), (713, 707), (715, 705)),
        )

    def test_widget_does_not_guess_unknown_platform_burst(self):
        self.set_unknown_platform()
        self.widget._auto_click = True

        self.process_unknown_burst()

        self.assertEqual(self.widget._recorder.sequence, [])
        self.assertIsNone(self.widget._click_plan)
        self.assertFalse(self.widget._auto_click)
        self.assertEqual(self.widget._pending_platform_sequence, [204, 203, 202, 201])
        self.assertIn("Random platform burst captured", self.widget._status)

    def test_widget_manual_calibration_saves_and_reuses_unknown_platform_mapping(self):
        self.widget._PERSISTENT_MAPPINGS_ENABLED = True
        self.set_unknown_platform()
        self.process_unknown_burst()

        for agent_id in (302, 304, 301, 303):
            self.widget._record_manual_calibration_switch(agent_id)

        self.assertEqual(self.widget._recorder.sequence, [302, 304, 301, 303])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 302)
        payload = json.loads(pathlib.Path(self.widget.MAPPING_FILE).read_text(encoding="utf-8"))
        mappings = {
            item["signature"]: tuple(tuple(pair) for pair in item["marker_to_switch_gadget_ids"])
            for item in payload["mappings"]
        }
        self.assertEqual(
            mappings["markers=801,802,803,804|switches=901,902,903,904"],
            ((804, 902), (803, 904), (802, 901), (801, 903)),
        )

        self.widget._recorder.clear()
        self.widget._world_create_recorder.clear()
        self.widget._pending_platform_sequence.clear()
        self.widget._click_plan = None
        self.widget._platform_mappings_loaded = False
        self.widget._platform_mappings.clear()
        self.process_unknown_burst()

        self.assertEqual(self.widget._recorder.sequence, [302, 304, 301, 303])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 302)

    def test_new_platform_burst_clears_partial_manual_calibration(self):
        self.set_unknown_platform()
        self.add_other_unknown_platform_markers()
        self.process_unknown_burst()
        self.widget._record_manual_calibration_switch(302)

        self.process_other_unknown_burst()

        self.assertEqual(self.widget._pending_platform_sequence, [214, 213, 212, 211])
        self.assertEqual(self.widget._manual_calibration_sequence, [])
        self.assertIsNone(self.widget._click_plan)
        self.assertIn("Platform burst changed; manual calibration cleared", self.widget._status)

    def test_repeated_same_platform_burst_keeps_partial_manual_calibration(self):
        self.set_unknown_platform()
        self.process_unknown_burst()
        self.widget._record_manual_calibration_switch(302)

        self.process_unknown_burst()

        self.assertEqual(self.widget._pending_platform_sequence, [204, 203, 202, 201])
        self.assertEqual(self.widget._manual_calibration_sequence, [302])
        self.assertIsNone(self.widget._click_plan)

    def test_widget_agent_selection_packets_do_not_learn_unknown_platform_mapping(self):
        self.set_unknown_platform()
        self.process_unknown_burst()
        for tick, paired, clicked in (
            (2100, 301, 302),
            (2110, 301, 304),
            (2120, 302, 301),
            (2130, 301, 303),
        ):
            self.harness.add_client_click_packet(tick, paired, clicked)

        self.widget._process_capture()

        self.assertEqual(self.widget._recorder.sequence, [])
        self.assertIsNone(self.widget._click_plan)
        self.assertFalse(pathlib.Path(self.widget.MAPPING_FILE).exists())

    def test_widget_ctos_interact_packets_can_learn_unknown_platform_mapping(self):
        self.widget._PERSISTENT_MAPPINGS_ENABLED = True
        self.set_unknown_platform()
        self.process_unknown_burst()
        for tick, agent_id in (
            (2100, 302),
            (2110, 304),
            (2120, 301),
            (2130, 303),
        ):
            self.harness.add_client_interact_packet(tick, agent_id)

        self.widget._process_capture()

        self.assertEqual(self.widget._recorder.sequence, [302, 304, 301, 303])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 302)
        payload = json.loads(pathlib.Path(self.widget.MAPPING_FILE).read_text(encoding="utf-8"))
        mappings = {
            item["signature"]: tuple(tuple(pair) for pair in item["marker_to_switch_gadget_ids"])
            for item in payload["mappings"]
        }
        self.assertEqual(
            mappings["markers=801,802,803,804|switches=901,902,903,904"],
            ((804, 902), (803, 904), (802, 901), (801, 903)),
        )

    def test_start_capture_falls_back_to_stoc_when_ctos_hook_is_unavailable(self):
        self.set_known_return_platform()
        self.harness.player_xy = (2950.0, -9400.0)
        self.harness.initialize_results["both"] = False
        self.harness.initialize_results["StoC"] = True

        self.widget._start_capture()

        self.assertTrue(self.widget._capturing)
        self.assertEqual(self.harness.initialize_calls, ["both", "StoC"])
        self.assertIn("StoC only", self.widget._status)

    def test_widget_ctos_reset_restarts_click_plan_from_first_switch(self):
        self.install_known_return_mapping()
        self.set_known_return_platform()
        self.process_known_return_burst()
        self.widget._click_plan.mark_clicked(18)
        self.widget._manual_calibration_sequence[:] = [18]
        self.harness.add_client_reset_packet(1200, 18)

        self.widget._process_capture()

        self.assertEqual(self.widget._click_plan.next_agent_id(), 18)
        self.assertEqual(self.widget._manual_calibration_sequence, [])
        self.assertEqual(self.widget._status, "Sequence reset by client packet. Restart at 18.")

    def test_widget_ctos_reset_without_sequence_waits_for_platform_burst(self):
        self.set_known_return_platform()
        self.widget._capturing = True
        self.widget._manual_calibration_sequence[:] = [18]
        self.harness.add_client_reset_packet(1200, 18)

        self.widget._process_capture()

        self.assertIsNone(self.widget._click_plan)
        self.assertEqual(self.widget._manual_calibration_sequence, [])
        self.assertEqual(self.widget._status, "Sequence reset by client packet; waiting for platform burst.")

    def test_widget_reset_button_clears_partial_manual_calibration(self):
        self.set_unknown_platform()
        self.process_unknown_burst()
        self.widget._record_manual_calibration_switch(302)
        self.harness.buttons.add("Reset")

        self.widget._draw_controls()

        self.assertEqual(self.widget._manual_calibration_sequence, [])
        self.assertEqual(self.widget._pending_platform_sequence, [])

    def test_scan_switches_clears_pending_burst_and_partial_manual_calibration(self):
        self.set_unknown_platform()
        self.process_unknown_burst()
        self.widget._record_manual_calibration_switch(302)
        self.harness.buttons.add("Scan switches")

        self.widget._draw_controls()

        self.assertEqual(self.widget._manual_calibration_sequence, [])
        self.assertEqual(self.widget._pending_platform_sequence, [])
        self.assertIsNone(self.widget._click_plan)
        self.assertEqual(self.widget._recorder.sequence, [])
        self.assertIn("switch candidate(s) selected", self.widget._status)

    def test_scan_switches_clears_stale_packet_logs(self):
        self.set_unknown_platform()
        self.widget._capturing = True
        for tick, agent_id, gadget_id in (
            (2000, 204, 804),
            (2010, 203, 803),
            (2020, 202, 802),
            (2030, 201, 801),
        ):
            self.harness.add_world_create_packet(tick, agent_id, gadget_id)
        self.harness.buttons.add("Scan switches")

        self.widget._draw_controls()
        self.widget._process_capture()

        self.assertEqual(self.harness.packet_logs, [])
        self.assertEqual(self.widget._pending_platform_sequence, [])
        self.assertIsNone(self.widget._click_plan)

    def test_runtime_changes_are_disabled_by_default_and_do_not_create_click_plan(self):
        self.set_known_return_platform()
        self.widget._capturing = True
        self.widget._prime_runtime_snapshots()
        current_time = [100.0]
        self.widget.time.monotonic = lambda: current_time[0]

        for offset, agent_id in enumerate((18, 20, 21, 19), start=1):
            current_time[0] += 0.5
            self.harness.set_runtime(agent_id, visual_effects=offset)
            self.widget._process_runtime_changes()

        self.assertEqual(self.widget._recorder.sequence, [])
        self.assertIsNone(self.widget._click_plan)
        self.assertEqual(self.widget._last_runtime_changes, [])
        self.assertEqual(self.widget._capture_status.state_matches, 0)

    def test_reset_button_clears_pending_platform_sequence(self):
        self.widget._pending_platform_sequence[:] = [204, 203, 202, 201]
        self.harness.buttons.add("Reset")

        self.widget._draw_controls()

        self.assertEqual(self.widget._pending_platform_sequence, [])

    def test_reset_button_disables_stale_auto_click_state(self):
        self.widget._auto_click = True
        self.widget._click_plan = self.widget.ClickPlan([18, 19])
        self.widget._pending_click_agent_id = 18
        self.widget._last_click_time = 123.0
        self.widget._last_move_agent_id = 18
        self.widget._last_move_time = 123.0
        self.harness.buttons.add("Reset")

        self.widget._draw_controls()

        self.assertFalse(self.widget._auto_click)
        self.assertIsNone(self.widget._click_plan)
        self.assertEqual(self.widget._pending_click_agent_id, 0)
        self.assertEqual(self.widget._last_click_time, 0.0)
        self.assertEqual(self.widget._last_move_agent_id, 0)
        self.assertEqual(self.widget._last_move_time, 0.0)

    def test_start_capture_disables_stale_auto_click_state(self):
        self.set_known_return_platform()
        self.harness.player_xy = (2950.0, -9400.0)
        self.widget._auto_click = True
        self.widget._click_plan = self.widget.ClickPlan([18, 19])
        self.widget._pending_click_agent_id = 18
        self.widget._last_click_time = 123.0
        self.widget._last_move_agent_id = 18
        self.widget._last_move_time = 123.0

        self.widget._start_capture()

        self.assertTrue(self.widget._capturing)
        self.assertFalse(self.widget._auto_click)
        self.assertIsNone(self.widget._click_plan)
        self.assertEqual(self.widget._pending_click_agent_id, 0)
        self.assertEqual(self.widget._last_click_time, 0.0)
        self.assertEqual(self.widget._last_move_agent_id, 0)
        self.assertEqual(self.widget._last_move_time, 0.0)

    def test_stop_button_clears_auto_click_and_pending_click_state(self):
        self.set_known_return_platform()
        self.widget._capturing = True
        self.widget._ctos_capture_available = True
        self.widget._auto_click = True
        self.widget._click_plan = self.widget.ClickPlan([18, 19])
        self.widget._pending_click_agent_id = 18
        self.widget._pending_click_started_at = 123.0
        self.widget._last_click_time = 123.0
        self.widget._last_move_agent_id = 18
        self.widget._last_move_time = 123.0
        self.harness.buttons.add("Stop")

        self.widget._draw_controls()

        self.assertFalse(self.widget._capturing)
        self.assertFalse(self.widget._ctos_capture_available)
        self.assertFalse(self.widget._auto_click)
        self.assertEqual(self.widget._pending_click_agent_id, 0)
        self.assertEqual(self.widget._pending_click_started_at, 0.0)
        self.assertEqual(self.widget._last_click_time, 0.0)
        self.assertEqual(self.widget._last_move_agent_id, 0)
        self.assertEqual(self.widget._last_move_time, 0.0)
        self.assertEqual(self.widget._click_plan.next_agent_id(), 18)
        self.assertEqual(self.widget._status, "Recording stopped.")

    def test_click_next_interacts_and_waits_for_ctos_interact_when_available(self):
        self.set_known_return_platform()
        self.harness.player_xy = (3034.0, -9498.0)
        self.widget._capturing = True
        self.widget._ctos_capture_available = True
        self.widget._click_plan = self.widget.ClickPlan([18, 19])

        self.widget._click_next_switch()

        self.assertEqual(self.harness.interactions, [(18, False)])
        self.assertEqual(self.harness.moves, [])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 18)
        self.assertEqual(self.widget._pending_click_agent_id, 18)
        self.assertEqual(self.widget._status, "Interacted with switch agent 18; waiting for CToS 0x39 confirmation.")

    def test_ctos_interact_confirmation_advances_pending_click_plan(self):
        self.set_known_return_platform()
        self.harness.player_xy = (3034.0, -9498.0)
        self.widget._capturing = True
        self.widget._ctos_capture_available = True
        self.widget._click_plan = self.widget.ClickPlan([18, 19])

        self.widget._click_next_switch()
        self.harness.add_client_interact_packet(1200, 18)
        self.widget._process_capture()

        self.assertEqual(self.widget._click_plan.next_agent_id(), 19)
        self.assertEqual(self.widget._pending_click_agent_id, 0)
        self.assertEqual(self.widget._status, "CToS interact confirmed for switch agent 18. Next switch: 19.")

    def test_click_next_advances_immediately_when_ctos_capture_is_unavailable(self):
        self.set_known_return_platform()
        self.harness.player_xy = (3034.0, -9498.0)
        self.widget._capturing = True
        self.widget._ctos_capture_available = False
        self.widget._click_plan = self.widget.ClickPlan([18, 19])

        self.widget._click_next_switch()

        self.assertEqual(self.harness.interactions, [(18, False)])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 19)
        self.assertEqual(self.widget._pending_click_agent_id, 0)
        self.assertEqual(self.widget._status, "Interacted with switch agent 18. Next switch: 19.")

    def test_pending_click_times_out_to_keep_auto_click_moving(self):
        self.set_known_return_platform()
        self.harness.player_xy = (3034.0, -9498.0)
        self.widget._capturing = True
        self.widget._ctos_capture_available = True
        self.widget._click_plan = self.widget.ClickPlan([18, 19])
        current_time = [100.0]
        self.widget.time.monotonic = lambda: current_time[0]

        self.widget._click_next_switch()
        current_time[0] += self.widget._INTERACT_CONFIRM_TIMEOUT + 0.1
        self.widget._process_pending_click_timeout()

        self.assertEqual(self.widget._click_plan.next_agent_id(), 19)
        self.assertEqual(self.widget._pending_click_agent_id, 0)
        self.assertIn("No CToS interact confirmation", self.widget._status)

    def test_final_pending_click_timeout_tells_user_to_wait_for_server_confirmation(self):
        self.set_known_return_platform()
        self.harness.player_xy = (3034.0, -9498.0)
        self.widget._capturing = True
        self.widget._ctos_capture_available = True
        self.widget._click_plan = self.widget.ClickPlan([18])
        current_time = [100.0]
        self.widget.time.monotonic = lambda: current_time[0]

        self.widget._click_next_switch()
        current_time[0] += self.widget._INTERACT_CONFIRM_TIMEOUT + 0.1
        self.widget._process_pending_click_timeout()

        self.assertTrue(self.widget._click_plan.complete)
        self.assertIn("Wait a few seconds for server sequence confirmation", self.widget._status)

    def test_final_ctos_confirmation_tells_user_to_wait_for_server_confirmation(self):
        self.set_known_return_platform()
        self.harness.player_xy = (3034.0, -9498.0)
        self.widget._capturing = True
        self.widget._ctos_capture_available = True
        self.widget._click_plan = self.widget.ClickPlan([18])

        self.widget._click_next_switch()
        self.harness.add_client_interact_packet(1200, 18)
        self.widget._process_capture()

        self.assertTrue(self.widget._click_plan.complete)
        self.assertIn("Wait a few seconds for server sequence confirmation", self.widget._status)

    def test_partial_server_confirmation_keeps_wait_status_after_final_click(self):
        self.set_live_forward_platform()
        self.widget._capturing = True
        self.widget._recorder.set_sequence([13, 14, 16, 15])
        self.widget._click_plan = self.widget.ClickPlan([13, 14, 16, 15])
        for agent_id in (13, 14, 16, 15):
            self.widget._click_plan.mark_clicked(agent_id)
        self.widget._status = "Final click queued. Wait a few seconds for server sequence confirmation, then step onto the platform."

        for tick, agent_id in ((6000, 13), (6100, 14), (6200, 16)):
            self.harness.add_packet(
                "StoC",
                tick,
                0x0115,
                struct.pack("<III", 0x0115, agent_id, 3),
            )
        self.widget._process_capture()

        self.assertIn("Wait a few seconds for server sequence confirmation", self.widget._status)

    def test_full_server_confirmation_updates_status_after_final_click(self):
        self.set_live_forward_platform()
        self.widget._capturing = True
        self.widget._recorder.set_sequence([13, 14, 16, 15])
        self.widget._click_plan = self.widget.ClickPlan([13, 14, 16, 15])
        for agent_id in (13, 14, 16, 15):
            self.widget._click_plan.mark_clicked(agent_id)
        self.widget._status = "Final click queued. Wait a few seconds for server sequence confirmation, then step onto the platform."

        for tick, agent_id in ((6000, 13), (6100, 14), (6200, 16), (6300, 15)):
            self.harness.add_packet(
                "StoC",
                tick,
                0x0115,
                struct.pack("<III", 0x0115, agent_id, 3),
            )
        self.widget._process_capture()

        self.assertEqual(self.widget._status, "Server confirmed sequence. Step onto the platform.")

    def test_click_next_requires_capture_for_client_confirmation(self):
        self.set_known_return_platform()
        self.harness.player_xy = (3034.0, -9498.0)
        self.widget._capturing = False
        self.widget._click_plan = self.widget.ClickPlan([18, 19])

        self.widget._click_next_switch()

        self.assertEqual(self.harness.interactions, [])
        self.assertEqual(self.widget._click_plan.next_agent_id(), 18)
        self.assertEqual(self.widget._status, "Start recording before clicking switches.")

    def test_agent_selection_packet_does_not_advance_click_plan(self):
        self.set_known_return_platform()
        self.widget._capturing = True
        self.widget._click_plan = self.widget.ClickPlan([18, 19])
        self.widget._pending_click_agent_id = 18

        self.harness.add_client_click_packet(1200, 19, 18)
        self.widget._process_capture()

        self.assertEqual(self.widget._click_plan.next_agent_id(), 18)
        self.assertEqual(self.widget._pending_click_agent_id, 18)

    def test_click_next_moves_toward_next_switch_when_out_of_range(self):
        self.set_known_return_platform()
        self.harness.player_xy = (0.0, 0.0)
        self.widget._capturing = True
        self.widget._click_plan = self.widget.ClickPlan([18])

        self.widget._click_next_switch()

        self.assertEqual(self.harness.interactions, [])
        self.assertEqual(len(self.harness.moves), 1)
        move_x, move_y = self.harness.moves[0]
        distance_to_switch = ((move_x - 3034.0) ** 2 + (move_y - -9498.0) ** 2) ** 0.5
        self.assertLess(distance_to_switch, self.widget._INTERACT_DISTANCE)
        self.assertNotEqual(self.harness.moves[0], (3034.0, -9498.0))
        self.assertEqual(self.widget._click_plan.next_agent_id(), 18)
        self.assertEqual(self.widget._status, "Moving to switch agent 18.")

    def test_click_next_moves_to_approach_point_instead_of_switch_center(self):
        self.set_known_return_platform()
        self.harness.player_xy = (3034.0, -9300.0)
        self.widget._capturing = True
        self.widget._click_plan = self.widget.ClickPlan([18])

        self.widget._click_next_switch()

        self.assertEqual(len(self.harness.moves), 1)
        move_x, move_y = self.harness.moves[0]
        self.assertAlmostEqual(move_x, 3034.0, places=3)
        self.assertGreater(move_y, -9498.0)
        self.assertLess(abs(move_y - -9498.0), self.widget._INTERACT_DISTANCE)
        self.assertNotEqual(self.harness.moves[0], (3034.0, -9498.0))


if __name__ == "__main__":
    unittest.main()
