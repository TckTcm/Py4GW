import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "Py4GW_python" / "Widgets" / "Automation" / "Helpers" / "Dialogs" / "Dialog Telemetry Monitor.py"


def _load_dialog_monitor_module():
    module_name = "dialog_active_monitor_under_test"
    for name in (module_name, "Py4GW", "Py4GWCoreLib"):
        sys.modules.pop(name, None)

    py4gw_module = types.ModuleType("Py4GW")
    py4gw_module.Console = types.SimpleNamespace(get_projects_path=lambda: str(REPO_ROOT))
    sys.modules["Py4GW"] = py4gw_module

    pyimgui_stub = types.SimpleNamespace(
        button=lambda *args, **kwargs: False,
        small_button=lambda *args, **kwargs: False,
        same_line=lambda *args, **kwargs: None,
        text=lambda *args, **kwargs: None,
        text_wrapped=lambda *args, **kwargs: None,
        separator=lambda *args, **kwargs: None,
        begin_child=lambda *args, **kwargs: False,
        end_child=lambda *args, **kwargs: None,
        input_text=lambda label, value, size: value,
        combo=lambda label, current, items: current,
        input_float=lambda label, value: value,
        input_int=lambda label, value: value,
        begin=lambda *args, **kwargs: False,
        end=lambda *args, **kwargs: None,
        begin_table=lambda *args, **kwargs: False,
        end_table=lambda *args, **kwargs: None,
        table_setup_column=lambda *args, **kwargs: None,
        table_next_row=lambda *args, **kwargs: None,
        table_set_column_index=lambda *args, **kwargs: None,
        set_clipboard_text=lambda *args, **kwargs: None,
        WindowFlags=types.SimpleNamespace(NoFlag=0, AlwaysAutoResize=0),
        TableFlags=types.SimpleNamespace(Resizable=0),
        TableColumnFlags=types.SimpleNamespace(WidthFixed=0, WidthStretch=0),
    )
    routines_stub = types.SimpleNamespace(Checks=types.SimpleNamespace(Map=types.SimpleNamespace(MapValid=lambda: True)))
    map_stub = types.SimpleNamespace(GetMapID=lambda: 857)
    agent_stub = types.SimpleNamespace(GetModelID=lambda agent_id: 2188, GetNameByID=lambda agent_id: "Test NPC")
    player_stub = types.SimpleNamespace(GetName=lambda: "Test Character")
    dialog_stub = types.SimpleNamespace(
        sanitize_dialog_text=lambda value: str(value or "").strip(),
        extract_inline_dialog_choices_from_active=None,
        sync_dialog_storage=lambda include_raw=True, include_callback_journal=True: {
            "raw_inserted": 1,
            "journal_inserted": 2,
            "turns_finalized": 3,
        },
    )

    core_module = types.ModuleType("Py4GWCoreLib")
    core_module.Routines = routines_stub
    core_module.PyImGui = pyimgui_stub
    core_module.Map = map_stub
    core_module.Agent = agent_stub
    core_module.Player = player_stub
    core_module.Dialog = dialog_stub
    sys.modules["Py4GWCoreLib"] = core_module

    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class DialogActiveMonitorTests(unittest.TestCase):
    def setUp(self):
        self.module = _load_dialog_monitor_module()

    def test_module_name_identifies_new_widget(self):
        self.assertEqual("Dialog Telemetry Monitor", self.module.MODULE_NAME)

    def test_default_tab_is_live(self):
        state = self.module.DialogMonitorState()

        self.assertEqual(self.module._TAB_LIVE, state.selected_tab)

    def test_select_tab_accepts_known_values_and_rejects_unknown(self):
        state = self.module.DialogMonitorState()

        state.select_tab(self.module._TAB_LOGS)
        state.select_tab("Unknown")

        self.assertEqual(self.module._TAB_LOGS, state.selected_tab)

    def test_select_npc_uid_clears_selected_turn_when_selection_changes(self):
        state = self.module.DialogMonitorState()
        state.selected_npc_uid = "857:2188:14"
        state.selected_turn_id = 42

        state.select_npc_uid("857:2188:99")

        self.assertEqual("857:2188:99", state.selected_npc_uid)
        self.assertEqual(0, state.selected_turn_id)

    def test_inline_choice_certainty_is_marked_inline(self):
        inline_choice = self.module._InlineDialogChoice(0x84, "Accept quest")
        native_choice = types.SimpleNamespace(dialog_id=0x85)

        self.assertEqual("[inline]", self.module._choice_certainty_label(inline_choice))
        self.assertEqual("[authoritative]", self.module._choice_certainty_label(native_choice))

    def test_player_name_text_is_obfuscated_case_insensitively(self):
        masked = self.module._obfuscate_player_name_text("Greetings, test character.")

        self.assertEqual("Greetings, <character name>.", masked)

    def test_player_name_text_is_hidden_when_redaction_is_unavailable(self):
        self.module.Player.GetName = lambda: ""

        masked = self.module._obfuscate_player_name_text("Greetings, Test Character.")

        self.assertEqual(self.module._REDACTION_BLOCKED_PLACEHOLDER, masked)

    def test_recursive_payload_obfuscation_masks_only_player_name(self):
        payload = {
            "body_text_raw": "Hello Test Character",
            "choices": [
                {"choice_text_raw": "Speak to TEST CHARACTER now."},
                {"choice_text_raw": "Speak to Master Togo now."},
            ],
            "nested": {"text": "Test Character and Mhenlo"},
        }

        masked = self.module._obfuscate_player_name_value(payload)

        self.assertEqual("Hello <character name>", masked["body_text_raw"])
        self.assertEqual("Speak to <character name> now.", masked["choices"][0]["choice_text_raw"])
        self.assertEqual("Speak to Master Togo now.", masked["choices"][1]["choice_text_raw"])
        self.assertEqual("<character name> and Mhenlo", masked["nested"]["text"])

    def test_fail_closed_payload_obfuscation_raises_when_redaction_is_unavailable(self):
        self.module.Player.GetName = lambda: ""

        with self.assertRaises(self.module._PlayerNameRedactionUnavailable):
            self.module._obfuscate_player_name_value({"body_text_raw": "Hello Test Character"}, fail_closed=True)

    def test_sync_core_storage_records_last_error(self):
        state = self.module.DialogMonitorState()

        def boom(**kwargs):
            raise RuntimeError("sqlite unavailable")

        self.module.Dialog.sync_dialog_storage = boom

        state.sync_core_storage(now=10.0)

        self.assertEqual("sqlite unavailable", state.last_sync_error)
        self.assertEqual(
            {"raw_inserted": 0, "journal_inserted": 0, "turns_finalized": 0},
            state.last_storage_sync_result,
        )

    def test_timed_cache_only_refreshes_after_ttl(self):
        cache = self.module._TimedValueCache()
        calls = []

        def fetcher():
            calls.append("fetch")
            return len(calls)

        first = cache.get_or_refresh("turns", ttl_seconds=1.0, fetcher=fetcher, now=100.0)
        second = cache.get_or_refresh("turns", ttl_seconds=1.0, fetcher=fetcher, now=100.5)
        third = cache.get_or_refresh("turns", ttl_seconds=1.0, fetcher=fetcher, now=101.5)

        self.assertEqual(1, first)
        self.assertEqual(1, second)
        self.assertEqual(2, third)
        self.assertEqual(["fetch", "fetch"], calls)

    def test_copy_choice_label_button_copies_visible_choice_text(self):
        clipboard: list[str] = []
        self.module.PyImGui.button = lambda *args, **kwargs: True
        self.module.PyImGui.set_clipboard_text = lambda value: clipboard.append(str(value))
        choice = types.SimpleNamespace(
            dialog_id=0x84,
            message="Raw Choice",
            message_decoded="Accept quest",
            message_decode_pending=False,
        )

        self.module._copy_choice_label_button(choice, "choice_text_0")

        self.assertEqual(["Accept quest"], clipboard)

    def test_copy_text_to_clipboard_is_blocked_when_redaction_is_unavailable(self):
        clipboard: list[str] = []
        self.module.Player.GetName = lambda: ""
        self.module.PyImGui.set_clipboard_text = lambda value: clipboard.append(str(value))
        self.module._state.last_file_action_error = ""

        self.module._copy_text_to_clipboard("Hello Test Character")

        self.assertEqual([], clipboard)
        self.assertIn("redaction unavailable", self.module._state.last_file_action_error.lower())

    def test_write_obfuscated_json_does_not_create_file_when_redaction_is_unavailable(self):
        self.module.Player.GetName = lambda: ""

        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "blocked.json"

            with self.assertRaises(self.module._PlayerNameRedactionUnavailable):
                self.module._write_obfuscated_json(
                    str(export_path),
                    {"body_text_raw": "Hello Test Character"},
                )

            self.assertFalse(export_path.exists())


if __name__ == "__main__":
    unittest.main()
