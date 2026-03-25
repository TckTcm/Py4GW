import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "Py4GW_python" / "Widgets" / "Automation" / "Helpers" / "Dialogs" / "Venta Cemetery - Rojis Disarm Trap.py"


class _FakeTimer:
    def Start(self):
        return None

    def Reset(self):
        return None

    def HasElapsed(self, _ms):
        return False


class _FakeActionQueueManager:
    queued_actions = []

    def ProcessQueue(self, _name):
        return None

    def ResetQueue(self, _name):
        self.__class__.queued_actions.append(("reset", _name))
        return None

    def AddAction(self, *args, **kwargs):
        self.__class__.queued_actions.append(("action", args, kwargs))
        return None

    def AddActionWithDelay(self, *args, **kwargs):
        self.__class__.queued_actions.append(("delay", args, kwargs))
        return None

    def GetAllActionNames(self, _name):
        return [str(entry[1]) for entry in self.__class__.queued_actions]

    def GetHistoryNames(self, _name):
        return [str(entry[1]) for entry in self.__class__.queued_actions]


class _FakeColor:
    def __init__(self, *_args, **_kwargs):
        pass

    def to_tuple_normalized(self):
        return (1.0, 1.0, 1.0, 1.0)


class _FakeMap:
    @staticmethod
    def IsMapLoading():
        return False

    @staticmethod
    def IsMapReady():
        return True


class _FakePlayer:
    @staticmethod
    def GetAgentID():
        return 58


class _FakeSkill:
    @staticmethod
    def GetName(skill_id):
        if int(skill_id) == 1418:
            return "Disarm Trap"
        if int(skill_id) == 2358:
            return "You_Move_Like_a_Dwarf"
        return f"Skill {skill_id}"


class _FakeSkillBar:
    @staticmethod
    def GetSkillIDBySlot(_slot):
        return 2358


class _FakeUIManager:
    frame_hash_map = {
        1725534410: 1001,
        792099697: 2002,
    }
    parent_map = {}
    ui_message_logs = []

    @classmethod
    def GetFrameIDByHash(cls, frame_hash):
        return cls.frame_hash_map.get(int(frame_hash), 0)

    @staticmethod
    def FrameExists(frame_id):
        return int(frame_id) > 0

    @staticmethod
    def GetChildFrameID(*_args, **_kwargs):
        return 0

    @staticmethod
    def GetChildFrameByFrameId(*_args, **_kwargs):
        return 0

    @classmethod
    def GetParentFrameID(cls, frame_id):
        return cls.parent_map.get(int(frame_id), 0)

    @staticmethod
    def GetFrameArray():
        return []

    @staticmethod
    def TestMouseAction(*_args, **_kwargs):
        return None

    @staticmethod
    def TestMouseClickAction(*_args, **_kwargs):
        return None

    @staticmethod
    def FrameClick(*_args, **_kwargs):
        return None

    @classmethod
    def GetUIMessageLogs(cls):
        return list(cls.ui_message_logs)

    @classmethod
    def ClearUIMessageLogs(cls):
        cls.ui_message_logs = []


class _FakeDialogModule(types.ModuleType):
    def __init__(self):
        super().__init__("Py4GWCoreLib.Dialog")
        self.calls = []
        self.frame_events = []
        self.visible_reward_by_frame = {}
        self.open_root_result = True

    def clear_pending_skill_resolution_trace(self):
        return None

    def get_pending_skill_resolution_trace(self):
        return []

    def get_pending_skill_frame_events(self):
        return list(self.frame_events)

    def clear_pending_skill_frame_events(self):
        self.frame_events = []

    def get_pending_skills(self, _agent_id=0):
        return []

    def get_visible_reward_skill_from_frame(self, frame_id):
        info = self.visible_reward_by_frame.get(int(frame_id), {})
        return types.SimpleNamespace(
            skill_id=int(info.get("skill_id", 0)),
            owner_id=int(info.get("owner_id", 0)),
            source_frame_id=int(info.get("source_frame_id", 0)),
        )

    def apply_pending_skill_replace(self, *_args, **_kwargs):
        self.calls.append(("pending_apply", _args, _kwargs))
        return False

    def accept_offered_skill_and_apply_pending(self, *_args, **_kwargs):
        self.calls.append(("accept_then_pending", _args, _kwargs))
        return False

    def apply_open_reward_skill_replace_from_root(self, skill_id, slot_index, root_frame_id, agent_id=0, target_frame_id=0):
        self.calls.append(
            ("open_root", int(skill_id), int(slot_index), int(root_frame_id), int(agent_id), int(target_frame_id))
        )
        return bool(self.open_root_result)


def _install_fake_modules():
    dialog_module = _FakeDialogModule()
    package = types.ModuleType("Py4GWCoreLib")
    package.__path__ = []
    package.ActionQueueManager = _FakeActionQueueManager
    package.Color = _FakeColor
    package.ImGui = types.SimpleNamespace(push_font=lambda *_a, **_k: None, pop_font=lambda: None)
    package.Map = _FakeMap
    package.Player = _FakePlayer
    package.PyImGui = types.SimpleNamespace(
        begin=lambda *_a, **_k: False,
        end=lambda: None,
        text=lambda *_a, **_k: None,
        text_wrapped=lambda *_a, **_k: None,
        separator=lambda: None,
        combo=lambda *_a, **_k: 0,
        button=lambda *_a, **_k: False,
        collapsing_header=lambda *_a, **_k: False,
        begin_tooltip=lambda: None,
        end_tooltip=lambda: None,
        text_colored=lambda *_a, **_k: None,
    )
    package.Skill = _FakeSkill
    package.SkillBar = _FakeSkillBar
    package.Timer = _FakeTimer
    package.UIManager = _FakeUIManager

    sys.modules["Py4GWCoreLib"] = package
    sys.modules["Py4GWCoreLib.Dialog"] = dialog_module
    sys.modules["Py4GWCoreLib.SkillAccept"] = dialog_module
    package.SkillAccept = dialog_module
    return dialog_module


class RojisDisarmTrapWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dialog_module = _install_fake_modules()
        spec = importlib.util.spec_from_file_location("rojis_disarm_trap_widget", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        cls.module = module

    def setUp(self):
        self.dialog_module.calls.clear()
        self.dialog_module.frame_events = []
        self.dialog_module.open_root_result = True
        _FakeActionQueueManager.queued_actions = []
        _FakeUIManager.parent_map = {}
        _FakeUIManager.ui_message_logs = []

    def test_open_reward_window_queues_source_first_ui_path(self):
        widget = self.module.RojisDisarmTrapWidget()
        ui_calls = []
        def _queue_ui(slot, source_frame_id=0, retries_left=0):
            ui_calls.append((int(slot), int(source_frame_id)))
            widget.begin_verify(int(slot))
            return True
        widget.queue_open_reward_ui_apply = _queue_ui
        widget.get_visible_reward_candidate_frames = lambda slot: [1001, 3003]
        widget.get_open_reward_ui_slot_frames = lambda slot: [4004, 5005]
        self.dialog_module.visible_reward_by_frame = {
            3003: {"skill_id": 1418, "owner_id": 58, "source_frame_id": 3003},
        }

        widget.execute_flow()

        self.assertEqual([], self.dialog_module.calls)
        self.assertEqual([(8, 3003)], ui_calls)
        self.assertTrue(widget.verifying_apply)
        self.assertEqual(8, widget.verify_slot)

    def test_open_reward_window_uses_reward_root_as_source_fallback(self):
        widget = self.module.RojisDisarmTrapWidget()
        ui_calls = []
        def _queue_ui(slot, source_frame_id=0, retries_left=0):
            ui_calls.append((int(slot), int(source_frame_id)))
            widget.begin_verify(int(slot))
            return True
        widget.queue_open_reward_ui_apply = _queue_ui
        widget.get_visible_reward_candidate_frames = lambda slot: []
        widget.get_open_reward_ui_slot_frames = lambda slot: [4004, 5005]

        widget.execute_flow()

        self.assertEqual([], self.dialog_module.calls)
        self.assertEqual([(8, 2002)], ui_calls)
        self.assertTrue(widget.verifying_apply)
        self.assertEqual(8, widget.verify_slot)

    def test_resolve_open_reward_anchor_prefers_specific_descendant_over_reward_root(self):
        widget = self.module.RojisDisarmTrapWidget()
        widget.get_visible_reward_candidate_frames = lambda slot: [2002, 3003]
        self.dialog_module.visible_reward_by_frame = {
            3003: {"skill_id": 1418, "owner_id": 58, "source_frame_id": 2002},
        }

        self.assertEqual(3003, widget.resolve_open_reward_anchor_frame(8))

    def test_open_reward_window_reports_ui_queue_failure(self):
        widget = self.module.RojisDisarmTrapWidget()
        def _queue_ui(_slot, _source_frame_id=0, _retries_left=0):
            return False

        widget.queue_open_reward_ui_apply = _queue_ui
        widget.get_visible_reward_candidate_frames = lambda slot: [1001, 3003]
        widget.get_open_reward_ui_slot_frames = lambda slot: [4004, 5005]
        self.dialog_module.visible_reward_by_frame = {
            3003: {"skill_id": 1418, "owner_id": 58, "source_frame_id": 3003},
        }

        widget.execute_flow()

        self.assertEqual([], self.dialog_module.calls)
        self.assertFalse(widget.verifying_apply)
        self.assertEqual("Open reward exact apply failed: UI queue unavailable.", widget.status_message)

    def test_open_reward_ui_queue_clicks_source_then_slot_then_equip(self):
        widget = self.module.RojisDisarmTrapWidget()
        widget.get_open_reward_ui_slot_frames = lambda slot: [4004, 5005]

        queued = widget.queue_open_reward_ui_apply(8, 3003)

        self.assertTrue(queued)
        frame_click_targets = [
            args[2]
            for entry in _FakeActionQueueManager.queued_actions
            if len(entry) == 3
            for kind, args, _kwargs in [entry]
            if kind == "action" and len(args) >= 3 and args[1] == self.module.UIManager.FrameClick
        ]
        self.assertEqual([3003, 4004, 5005, 1001], frame_click_targets)
        test_mouse_targets = [
            args[2]
            for entry in _FakeActionQueueManager.queued_actions
            if len(entry) == 3
            for kind, args, _kwargs in [entry]
            if kind == "action" and len(args) >= 3 and args[1] == self.module.UIManager.TestMouseAction
        ]
        self.assertEqual([3003, 4004, 5005, 1001, 1001], test_mouse_targets)
        test_mouse_click_targets = [
            args[2]
            for entry in _FakeActionQueueManager.queued_actions
            if len(entry) == 3
            for kind, args, _kwargs in [entry]
            if kind == "action" and len(args) >= 3 and args[1] == self.module.UIManager.TestMouseClickAction
        ]
        self.assertEqual([3003, 4004, 5005, 1001], test_mouse_click_targets)

    def test_open_reward_ui_queue_skips_reward_root_as_fake_source(self):
        widget = self.module.RojisDisarmTrapWidget()
        widget.get_open_reward_ui_slot_frames = lambda slot: [417]

        queued = widget.queue_open_reward_ui_apply(8, 2002)

        self.assertTrue(queued)
        frame_click_targets = [
            args[2]
            for entry in _FakeActionQueueManager.queued_actions
            if len(entry) == 3
            for kind, args, _kwargs in [entry]
            if kind == "action" and len(args) >= 3 and args[1] == self.module.UIManager.FrameClick
        ]
        self.assertEqual([417, 1001], frame_click_targets)

    def test_open_reward_ui_prefers_slot_frame_candidates_over_target_frames(self):
        widget = self.module.RojisDisarmTrapWidget()
        widget.get_reward_window_slot_frame_candidates = lambda slot: [417]
        widget.get_reward_window_slot_target_frames = lambda slot: [417, 421]
        widget.get_slot_frame_candidates = lambda slot: [8008]

        self.assertEqual([417], widget.get_open_reward_ui_slot_frames(8))

    def test_open_reward_ui_queue_records_queue_step_debug(self):
        widget = self.module.RojisDisarmTrapWidget()
        widget.get_open_reward_ui_slot_frames = lambda slot: [4004, 5005]
        _FakeUIManager.parent_map = {
            3003: 2002,
            4004: 3003,
            5005: 3003,
        }

        queued = widget.queue_open_reward_ui_apply(8, 3003)

        self.assertTrue(queued)
        self.assertTrue(any("source_click=3003" in line for line in widget.last_queue_debug))
        self.assertTrue(any("slot_click=4004" in line for line in widget.last_queue_debug))
        self.assertTrue(any("slot_click=5005" in line for line in widget.last_queue_debug))
        self.assertTrue(any("equip_click=1001" in line for line in widget.last_queue_debug))
        self.assertTrue(any("frame 4004" in line and "parent=3003" in line for line in widget.last_ui_debug))

    def test_retry_debug_reports_changed_candidate_frames(self):
        widget = self.module.RojisDisarmTrapWidget()
        widget.verifying_apply = True
        widget.verify_slot = 8
        widget.verify_pre_slot_skill_id = 2358
        widget.verify_source_frame_id = 3003
        widget.verify_slot_frame_ids = (4004, 5005)
        widget.verify_retries_left = 1
        widget.verify_timer.HasElapsed = lambda _ms: True
        widget.get_open_reward_ui_slot_frames = lambda slot: [6006]
        widget.queue_open_reward_ui_apply = lambda *_args, **_kwargs: True
        _FakeUIManager.parent_map = {
            3003: 2002,
            4004: 3003,
            5005: 3003,
            6006: 2002,
        }

        widget.update()

        self.assertTrue(any("previous_slot_frames=[4004, 5005]" in line for line in widget.last_retry_debug))
        self.assertTrue(any("current_slot_frames=[6006]" in line for line in widget.last_retry_debug))
        self.assertTrue(any("added_slot_frames=[6006]" in line for line in widget.last_retry_debug))
        self.assertTrue(any("removed_slot_frames=[4004, 5005]" in line for line in widget.last_retry_debug))
        self.assertTrue(any("stale_candidate_list=True" in line for line in widget.last_retry_debug))

    def test_refresh_trace_captures_pending_skill_frame_events(self):
        widget = self.module.RojisDisarmTrapWidget()
        self.dialog_module.frame_events = [
            types.SimpleNamespace(
                source=0,
                message_id=0x10000058,
                frame_id=417,
                parent_frame_id=393,
                child_offset_id=7,
                callback_index=0,
                callback_ptr=0x53BE50,
                callback_context_ptr=0x12340000,
                state_ptr=0x56780000,
                slot_index=7,
                skill_id=1418,
                accepted=True,
                reason="authoritative_pending_state",
            )
        ]

        widget.refresh_trace()

        self.assertEqual(1, len(widget.last_frame_events))
        self.assertEqual(417, getattr(widget.last_frame_events[0], "frame_id", 0))
        self.assertEqual(1418, getattr(widget.last_frame_events[0], "skill_id", 0))

    def test_refresh_trace_captures_filtered_reward_ui_payloads(self):
        widget = self.module.RojisDisarmTrapWidget()
        widget.selected_slot = 8
        widget.verify_slot_frame_ids = (417,)
        _FakeUIManager.ui_message_logs = [
            (1, 0x24, True, True, 417, [0] * 8, []),
            (2, 0x28, True, True, 2002, [0] * 8, []),
            (3, 0x24, True, True, 9999, [0] * 8, []),
        ]
        widget.refresh_trace()

        self.assertTrue(any("frame=417" in line for line in widget.last_ui_payload_debug))
        self.assertTrue(any("frame=2002" in line for line in widget.last_ui_payload_debug))
        self.assertFalse(any("frame=9999" in line for line in widget.last_ui_payload_debug))


if __name__ == "__main__":
    unittest.main()
