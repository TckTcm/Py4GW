import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "Py4GW_python" / "Widgets" / "Automation" / "Helpers" / "Dialogs" / "Target Dialog Sender.py"


class _FakeIniHandler:
    def __init__(self, _path: str) -> None:
        self.store: dict[tuple[str, str], object] = {}

    def write_key(self, section: str, key: str, value) -> None:
        self.store[(section, key)] = value

    def read_int(self, section: str, key: str, default: int = 0) -> int:
        return int(self.store.get((section, key), default))

    def read_key(self, section: str, key: str, default: str = "") -> str:
        return str(self.store.get((section, key), default))

    def read_bool(self, section: str, key: str, default: bool = False) -> bool:
        return bool(self.store.get((section, key), default))


class _FakeTimer:
    def __init__(self) -> None:
        self.running = False

    def Start(self) -> None:
        self.running = True

    def Stop(self) -> None:
        self.running = False

    def Reset(self) -> None:
        self.running = True

    def HasElapsed(self, _duration_ms: int) -> bool:
        return False

    def GetElapsedTime(self) -> int:
        return 0


def _load_target_dialog_sender():
    module_name = "target_dialog_sender_under_test"
    for name in (module_name, "Py4GW", "Py4GWCoreLib"):
        sys.modules.pop(name, None)

    py4gw_module = types.ModuleType("Py4GW")
    py4gw_module.Console = types.SimpleNamespace(
        get_projects_path=lambda: str(REPO_ROOT),
        Log=lambda *_args, **_kwargs: None,
        MessageType=types.SimpleNamespace(Error="error"),
    )
    sys.modules["Py4GW"] = py4gw_module

    player_calls = {
        "change_target": [],
        "send_dialog": [],
    }
    dialog_calls = {
        "live": [],
        "fallback": [],
    }

    class _FakePlayer:
        target_id = 0

        @staticmethod
        def GetTargetID() -> int:
            return int(_FakePlayer.target_id)

        @staticmethod
        def ChangeTarget(target_id: int) -> None:
            player_calls["change_target"].append(int(target_id))

        @staticmethod
        def SendDialog(dialog_id: int) -> None:
            player_calls["send_dialog"].append(int(dialog_id))

        @staticmethod
        def SendRawDialog(dialog_id: int) -> None:
            player_calls["send_dialog"].append(int(dialog_id))

    dialog_module = types.SimpleNamespace(
        get_active_dialog_choice_id_by_text=lambda text: dialog_calls["live"].append(str(text)) or 0,
        get_active_dialog_choice_id_by_text_with_fallback=lambda text, history_limit=25: dialog_calls["fallback"].append((str(text), int(history_limit))) or 0,
    )

    pyimgui_stub = types.SimpleNamespace(
        begin=lambda *_args, **_kwargs: False,
        end=lambda *_args, **_kwargs: None,
        text=lambda *_args, **_kwargs: None,
        text_wrapped=lambda *_args, **_kwargs: None,
        separator=lambda *_args, **_kwargs: None,
        combo=lambda _label, current, _items: current,
        checkbox=lambda _label, value: value,
        input_text=lambda _label, value: value,
        input_int=lambda _label, value: value,
        button=lambda *_args, **_kwargs: False,
        bullet_text=lambda *_args, **_kwargs: None,
        begin_tooltip=lambda: None,
        end_tooltip=lambda: None,
    )

    routines_stub = types.SimpleNamespace(
        Checks=types.SimpleNamespace(
            Map=types.SimpleNamespace(MapValid=lambda: True, IsMapReady=lambda: True)
        )
    )

    core_module = types.ModuleType("Py4GWCoreLib")
    core_module.Agent = types.SimpleNamespace(GetNameByID=lambda _agent_id: "Test Target")
    core_module.Dialog = dialog_module
    core_module.IniHandler = _FakeIniHandler
    core_module.Player = _FakePlayer
    core_module.PyImGui = pyimgui_stub
    core_module.Routines = routines_stub
    core_module.Timer = _FakeTimer
    sys.modules["Py4GWCoreLib"] = core_module

    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module, _FakePlayer, dialog_module, player_calls, dialog_calls


class TargetDialogSenderChoiceTextTests(unittest.TestCase):
    def setUp(self):
        self.module, self.player_cls, self.dialog_module, self.player_calls, self.dialog_calls = _load_target_dialog_sender()

    def test_resolve_choice_text_dialog_id_uses_live_helper_in_live_mode(self):
        self.dialog_module.get_active_dialog_choice_id_by_text = lambda text: self.dialog_calls["live"].append(str(text)) or 0x84

        result = self.module._resolve_choice_text_dialog_id("Accept quest", 0)

        self.assertEqual(0x84, result)
        self.assertEqual(["Accept quest"], self.dialog_calls["live"])
        self.assertEqual([], self.dialog_calls["fallback"])

    def test_resolve_choice_text_dialog_id_uses_fallback_helper_in_fallback_mode(self):
        self.dialog_module.get_active_dialog_choice_id_by_text_with_fallback = (
            lambda text, history_limit=25: self.dialog_calls["fallback"].append((str(text), int(history_limit))) or 0x85
        )

        result = self.module._resolve_choice_text_dialog_id("Accept quest", 1)

        self.assertEqual(0x85, result)
        self.assertEqual([("Accept quest", 25)], self.dialog_calls["fallback"])
        self.assertEqual([], self.dialog_calls["live"])

    def test_queue_choice_text_send_retargets_and_sends_resolved_id(self):
        self.player_cls.target_id = 77
        self.dialog_module.get_active_dialog_choice_id_by_text_with_fallback = (
            lambda text, history_limit=25: self.dialog_calls["fallback"].append((str(text), int(history_limit))) or 0x84
        )
        self.module._state.choice_text_input = "Accept quest"
        self.module._state.choice_text_match_mode_index = 1
        self.module._state.retarget_before_send = True

        self.module._queue_choice_text_send()

        self.assertEqual([77], self.player_calls["change_target"])
        self.assertEqual([0x84], self.player_calls["send_dialog"])
        self.assertIn("0x84", self.module._state.status_text)

    def test_queue_choice_text_send_reports_resolution_failure_without_sending(self):
        self.player_cls.target_id = 77
        self.module._state.choice_text_input = "Accept quest"
        self.module._state.choice_text_match_mode_index = 0
        self.module._state.retarget_before_send = True

        self.module._queue_choice_text_send()

        self.assertEqual([], self.player_calls["send_dialog"])
        self.assertIn("Could not resolve", self.module._state.status_text)


if __name__ == "__main__":
    unittest.main()
