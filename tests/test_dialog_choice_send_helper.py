import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DIALOG_MODULE_PATH = REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "Dialog.py"


def _clear_modules(*prefixes: str) -> None:
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes):
            sys.modules.pop(name, None)


def _make_package(name: str, path: Path | None = None) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = [str(path)] if path is not None else []
    sys.modules[name] = module
    return module


def _load_dialog_module():
    module_name = "Py4GWCoreLib.Dialog"
    _clear_modules("Py4GWCoreLib", "PyDialog", "PyDialogCatalog", "dialog_turn_pipeline")

    _make_package("Py4GWCoreLib", REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib")

    sent_dialogs: list[int] = []

    class _FakePlayer:
        @staticmethod
        def SendDialog(dialog_id: int) -> None:
            sent_dialogs.append(int(dialog_id))

    player_module = types.ModuleType("Py4GWCoreLib.Player")
    player_module.Player = _FakePlayer
    sys.modules["Py4GWCoreLib.Player"] = player_module

    spec = importlib.util.spec_from_file_location(module_name, DIALOG_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, sent_dialogs


class DialogChoiceSendHelperTests(unittest.TestCase):
    def setUp(self):
        self.module, self.sent_dialogs = _load_dialog_module()
        self.widget = self.module.DialogWidget()

    def _make_button(self, dialog_id: int, *, message: str = "", message_decoded: str = ""):
        return self.module.DialogButtonInfo(
            dialog_id=dialog_id,
            message=message,
            message_decoded=message_decoded,
            message_decode_pending=False,
        )

    def test_get_active_dialog_choice_id_by_text_matches_normalized_visible_choice_text(self):
        self.widget.is_dialog_active = lambda: True
        self.widget.get_active_dialog_buttons = lambda: [
            self._make_button(0x84, message_decoded="Accept quest"),
            self._make_button(0x85, message_decoded="No thanks"),
        ]

        result = self.widget.get_active_dialog_choice_id_by_text("  accept   QUEST ")

        self.assertEqual(0x84, result)

    def test_get_active_dialog_choice_id_by_text_returns_zero_when_dialog_is_not_active(self):
        self.widget.is_dialog_active = lambda: False
        self.widget.get_active_dialog_buttons = lambda: [
            self._make_button(0x84, message_decoded="Accept quest"),
        ]

        result = self.widget.get_active_dialog_choice_id_by_text("Accept quest")

        self.assertEqual(0, result)

    def test_send_active_dialog_choice_by_text_sends_matching_visible_choice_id(self):
        self.widget.is_dialog_active = lambda: True
        self.widget.get_active_dialog_buttons = lambda: [
            self._make_button(0x84, message="Accept quest"),
        ]

        result = self.widget.send_active_dialog_choice_by_text("Accept quest")

        self.assertTrue(result)
        self.assertEqual([0x84], self.sent_dialogs)

    def test_send_active_dialog_choice_by_text_returns_false_when_no_live_match_exists(self):
        self.widget.is_dialog_active = lambda: True
        self.widget.get_active_dialog_buttons = lambda: [
            self._make_button(0x85, message_decoded="No thanks"),
        ]

        result = self.widget.send_active_dialog_choice_by_text("Accept quest")

        self.assertFalse(result)
        self.assertEqual([], self.sent_dialogs)

    def test_get_active_dialog_choice_id_by_text_with_fallback_matches_catalog_text_for_visible_choice(self):
        self.widget.is_dialog_active = lambda: True
        self.widget.get_active_dialog_buttons = lambda: [
            self._make_button(0x84, message_decoded=""),
        ]
        self.widget.get_dialog_info = lambda dialog_id: types.SimpleNamespace(content="Accept quest")
        self.widget.get_dialog_text_decoded = lambda dialog_id: ""
        self.widget.sync_dialog_storage = lambda include_raw=True, include_callback_journal=True: {
            "raw_inserted": 0,
            "journal_inserted": 0,
            "turns_finalized": 0,
        }
        self.widget.get_active_dialog = lambda: None
        self.widget.get_dialog_turns = lambda **kwargs: []

        result = self.widget.get_active_dialog_choice_id_by_text_with_fallback("accept quest")

        self.assertEqual(0x84, result)

    def test_get_active_dialog_choice_id_by_text_with_fallback_matches_history_text_for_visible_choice(self):
        self.widget.is_dialog_active = lambda: True
        self.widget.get_active_dialog_buttons = lambda: [
            self._make_button(0x84, message_decoded=""),
        ]
        self.widget.get_dialog_info = lambda dialog_id: None
        self.widget.get_dialog_text_decoded = lambda dialog_id: ""
        self.widget.sync_dialog_storage = lambda include_raw=True, include_callback_journal=True: {
            "raw_inserted": 0,
            "journal_inserted": 0,
            "turns_finalized": 0,
        }
        self.widget.get_active_dialog = lambda: types.SimpleNamespace(dialog_id=0, context_dialog_id=0x200, agent_id=1)
        self.widget.get_dialog_turns = lambda **kwargs: [
            {
                "choices": [
                    {
                        "choice_dialog_id": 0x84,
                        "choice_text_raw": "Accept quest",
                        "choice_text_decoded": "",
                    }
                ]
            }
        ]

        result = self.widget.get_active_dialog_choice_id_by_text_with_fallback("accept quest")

        self.assertEqual(0x84, result)

    def test_get_active_dialog_choice_id_by_text_with_fallback_does_not_return_non_visible_history_choice(self):
        self.widget.is_dialog_active = lambda: True
        self.widget.get_active_dialog_buttons = lambda: [
            self._make_button(0x85, message_decoded=""),
        ]
        self.widget.get_dialog_info = lambda dialog_id: None
        self.widget.get_dialog_text_decoded = lambda dialog_id: ""
        self.widget.sync_dialog_storage = lambda include_raw=True, include_callback_journal=True: {
            "raw_inserted": 0,
            "journal_inserted": 0,
            "turns_finalized": 0,
        }
        self.widget.get_active_dialog = lambda: types.SimpleNamespace(dialog_id=0, context_dialog_id=0x200, agent_id=1)
        self.widget.get_dialog_turns = lambda **kwargs: [
            {
                "choices": [
                    {
                        "choice_dialog_id": 0x84,
                        "choice_text_raw": "Accept quest",
                        "choice_text_decoded": "",
                    }
                ]
            }
        ]

        result = self.widget.get_active_dialog_choice_id_by_text_with_fallback("accept quest")

        self.assertEqual(0, result)

    def test_send_active_dialog_choice_by_text_with_fallback_sends_catalog_matched_visible_choice(self):
        self.widget.is_dialog_active = lambda: True
        self.widget.get_active_dialog_buttons = lambda: [
            self._make_button(0x84, message_decoded=""),
        ]
        self.widget.get_dialog_info = lambda dialog_id: types.SimpleNamespace(content="Accept quest")
        self.widget.get_dialog_text_decoded = lambda dialog_id: ""
        self.widget.sync_dialog_storage = lambda include_raw=True, include_callback_journal=True: {
            "raw_inserted": 0,
            "journal_inserted": 0,
            "turns_finalized": 0,
        }
        self.widget.get_active_dialog = lambda: None
        self.widget.get_dialog_turns = lambda **kwargs: []

        result = self.widget.send_active_dialog_choice_by_text_with_fallback("Accept quest")

        self.assertTrue(result)
        self.assertEqual([0x84], self.sent_dialogs)


if __name__ == "__main__":
    unittest.main()
