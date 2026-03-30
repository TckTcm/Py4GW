import importlib.util
import pathlib
import sys
import types
import unittest
from unittest import mock


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DIALOG_DIR = REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib"
DIALOG_PATH = DIALOG_DIR / "Dialog.py"


def _load_dialog_module(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, DIALOG_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load Dialog.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _make_dialog_turn_pipeline_stub():
    module = types.ModuleType("dialog_turn_pipeline")
    module.get_dialog_turn_pipeline = lambda: None
    return module


def _make_map_stub(map_id: int):
    module = types.ModuleType("Map")

    class Map:
        @staticmethod
        def GetMapID() -> int:
            return map_id

    module.Map = Map
    return module


def _make_agent_stub(model_id: int):
    module = types.ModuleType("Agent")

    class Agent:
        @staticmethod
        def GetModelID(agent_id: int) -> int:
            return model_id

    module.Agent = Agent
    return module


def _make_pydialog_stub(*, get_dialog_info_result=None):
    module = types.ModuleType("PyDialog")

    class PyDialogStub:
        @staticmethod
        def get_dialog_info(dialog_id: int):
            return get_dialog_info_result

    module.PyDialog = PyDialogStub
    return module


class DialogModuleRegressionTests(unittest.TestCase):
    def test_module_exports_static_catalog_helpers(self):
        stubs = {
            "dialog_turn_pipeline": _make_dialog_turn_pipeline_stub(),
        }
        with mock.patch.dict(sys.modules, stubs, clear=False):
            dialog = _load_dialog_module("dialog_module_export_test")

            self.assertTrue(hasattr(dialog, "is_dialog_available"))
            self.assertTrue(hasattr(dialog, "get_dialog_info"))
            self.assertTrue(hasattr(dialog, "enumerate_available_dialogs"))

    def test_get_dialog_info_returns_none_when_native_returns_none(self):
        stubs = {
            "dialog_turn_pipeline": _make_dialog_turn_pipeline_stub(),
            "PyDialog": _make_pydialog_stub(get_dialog_info_result=None),
        }
        with mock.patch.dict(sys.modules, stubs, clear=False):
            dialog = _load_dialog_module("dialog_module_none_contract_test")
            dialog._get_dialog_catalog_widget = lambda: None

            widget = dialog.DialogWidget()

            self.assertIsNone(widget.get_dialog_info(0x0084))

    def test_fallback_choice_resolution_ignores_history_from_other_npc(self):
        stubs = {
            "dialog_turn_pipeline": _make_dialog_turn_pipeline_stub(),
            "Map": _make_map_stub(map_id=857),
            "Agent": _make_agent_stub(model_id=2188),
        }
        with mock.patch.dict(sys.modules, stubs, clear=False):
            dialog = _load_dialog_module("dialog_module_choice_fallback_test")

            class FakeDialogWidget(dialog.DialogWidget):
                def is_dialog_active(self) -> bool:
                    return True

                def get_active_dialog_buttons(self):
                    return [
                        dialog.DialogButtonInfo(dialog_id=101, message="", message_decoded=""),
                        dialog.DialogButtonInfo(dialog_id=102, message="", message_decoded=""),
                    ]

                def _get_dialog_choice_catalog_text(self, dialog_id: int) -> str:
                    return ""

                def get_active_dialog(self):
                    return dialog.ActiveDialogInfo(
                        dialog_id=0x0084,
                        context_dialog_id=0x0084,
                        agent_id=77,
                    )

                def sync_dialog_storage(self, include_raw=False, include_callback_journal=True):
                    return {}

                def get_dialog_turns(self, **kwargs):
                    if "npc_uid_instance" not in kwargs and "npc_uid_archetype" not in kwargs:
                        if kwargs.get("choice_dialog_id") == 101:
                            return [
                                {
                                    "choices": [
                                        {
                                            "choice_dialog_id": 101,
                                            "choice_text_decoded": "Accept quest",
                                            "choice_text_raw": "",
                                        }
                                    ]
                                }
                            ]
                    return []

            widget = FakeDialogWidget()

            self.assertEqual(
                widget.get_active_dialog_choice_id_by_text_with_fallback("Accept quest"),
                0,
            )


if __name__ == "__main__":
    unittest.main()
