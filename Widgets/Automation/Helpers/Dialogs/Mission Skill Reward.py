from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import Py4GW
import Py4GWCoreLib.SkillAccept as SkillAccept
from Py4GWCoreLib import (
    ActionQueueManager,
    Color,
    Console,
    ConsoleLog,
    ImGui,
    Map,
    Player,
    PyImGui,
    Skill,
    SkillBar,
    Timer,
    UIManager,
)

MODULE_NAME = "Mission Skill Reward"
MODULE_ICON = "Textures/Module_Icons/Skill Learner.png"

SKILLBAR_WINDOW_HASH = 641635682
SKILL_SLOT_OFFSETS = [2]
LEGACY_SKILL_SLOT_HASHES = {
    1: 2327501170,
    2: 1118947873,
    3: 3729459048,
    4: 505013902,
    5: 1764163401,
    6: 4191425816,
    7: 1566692728,
    8: 4117371686,
}
EQUIP_BUTTON_HASH = 1725534410
REWARD_WINDOW_HASH = 792099697
WIDGET_BUILD_ID = "2026-03-20 22:14"
UI_RETRY_DELAY_MS = 180
UI_SETTLE_DELAY_MS = 1100
MAX_UI_RETRIES = 3
SOURCE_CLICK_SETTLE_DELAY_MS = 120
SLOT_CLICK_SETTLE_DELAY_MS = 45
POST_SLOT_SELECTION_DELAY_MS = 180
UI_MOUSE_CLICK_STATE = 8
TRACE_HOLD_MS = 5000


def _noop_action() -> None:
    return None


@dataclass
class PendingSkillRow:
    skill_id: int
    copy_id: int
    ref_count: int
    name: str


@dataclass
class RequestedApply:
    slot: int
    mode: str
    retries_left: int
    expected_skill_id: Optional[int]
    pre_slot_skill_id: int
    source_frame_id: int = 0
    slot_frame_ids: tuple[int, ...] = ()
    attempted_target_index: int = 0
    target_frame_ids: tuple[int, ...] = ()
    owner_id: int = 0


@dataclass
class VisibleRewardInfo:
    skill_id: int
    owner_id: int
    source_frame_id: int
    name: str


class MissionSkillRewardWidget:
    def __init__(self) -> None:
        self.selected_slot = 8
        self.selected_pending_index = 0
        self.manual_skill_id = 0
        self.auto_apply_single_pending = False
        self.pending_rows: List[PendingSkillRow] = []
        self.status_message = "Idle."
        self.native_init_attempted = False
        self.native_ready = False
        self.native_error = ""
        self.pending_refresh_timer = Timer()
        self.pending_refresh_timer.Start()
        self.apply_timer = Timer()
        self.auto_attempt_timer = Timer()
        self.auto_attempt_timer.Start()
        self.active_request: Optional[RequestedApply] = None
        self.latest_visible_reward: Optional[VisibleRewardInfo] = None
        self.latest_resolution_trace: List[object] = []
        self.preserved_resolution_trace: List[object] = []
        self.latest_apply_trace: List[object] = []
        self.preserved_apply_trace: List[object] = []
        self.latest_native_drag_trace: List[object] = []
        self.preserved_native_drag_trace: List[object] = []
        self.last_visible_reward_rejection = ""
        self.last_auto_signature: Optional[tuple[int, int]] = None
        self.last_auto_attempt_signature: Optional[tuple[int, int]] = None
        self.trace_hold_timer = Timer()
        self.trace_hold_timer.Start()
        self.trace_hold_active = False

    def ensure_native_ready(self) -> bool:
        if self.native_init_attempted:
            return self.native_ready

        self.native_init_attempted = True
        try:
            self.native_ready = bool(SkillAccept.get_skill_accept_widget().initialize())
        except Exception as exc:
            self.native_ready = False
            self.native_error = str(exc)

        if not self.native_ready and not self.native_error:
            self.native_error = "PySkillAccept.initialize() returned False."
        return self.native_ready

    def reset_runtime_state(self, reason: str) -> None:
        self.pending_rows = []
        self.active_request = None
        self.latest_visible_reward = None
        self.latest_resolution_trace = []
        self.preserved_resolution_trace = []
        self.latest_apply_trace = []
        self.preserved_apply_trace = []
        self.latest_native_drag_trace = []
        self.preserved_native_drag_trace = []
        self.last_visible_reward_rejection = ""
        self.last_auto_signature = None
        self.last_auto_attempt_signature = None
        self.trace_hold_active = False
        self.status_message = reason

    def is_runtime_ready(self) -> bool:
        if self.reward_window_is_visible():
            return True
        if Map.IsMapLoading():
            self.reset_runtime_state("Waiting for map load to finish.")
            return False
        if not Map.IsMapReady():
            self.reset_runtime_state("Waiting for map readiness.")
            return False
        return True

    def get_player_agent_id(self) -> int:
        try:
            return int(Player.GetAgentID() or 0)
        except Exception:
            return 0

    def resolve_skill_name(self, skill_id: int) -> str:
        try:
            return Skill.GetName(skill_id)
        except Exception:
            return f"Skill {skill_id}"

    def refresh_pending_rows(self) -> None:
        if not self.ensure_native_ready():
            self.pending_rows = []
            return

        agent_id = self.get_player_agent_id()
        try:
            pending = SkillAccept.get_pending_skills(agent_id)
        except Exception as exc:
            self.pending_rows = []
            self.status_message = f"Pending skill refresh failed: {exc}"
            return

        rows = [
            PendingSkillRow(
                skill_id=int(item.skill_id),
                copy_id=int(item.copy_id),
                ref_count=int(item.ref_count),
                name=self.resolve_skill_name(int(item.skill_id)),
            )
            for item in pending
            if int(item.skill_id) > 0
        ]
        if self.reward_window_is_visible() and self.latest_visible_reward is not None:
            rows = [row for row in rows if row.skill_id == self.latest_visible_reward.skill_id]
        rows.sort(key=lambda item: (item.skill_id, item.copy_id))
        self.pending_rows = rows
        if rows:
            self.selected_pending_index = min(self.selected_pending_index, len(rows) - 1)
        else:
            self.selected_pending_index = 0

    def reward_window_is_visible(self) -> bool:
        equip_frame = UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH)
        return bool(equip_frame and UIManager.FrameExists(equip_frame))

    def get_slot_frame_candidates(self, slot: int) -> List[int]:
        frames: List[int] = []
        for path in ([slot - 1] + SKILL_SLOT_OFFSETS, [slot - 1]):
            try:
                frame_id = int(UIManager.GetChildFrameID(SKILLBAR_WINDOW_HASH, path) or 0)
            except Exception:
                frame_id = 0
            if frame_id > 0 and UIManager.FrameExists(frame_id) and frame_id not in frames:
                frames.append(frame_id)

        legacy_hash = LEGACY_SKILL_SLOT_HASHES.get(slot)
        if legacy_hash:
            frame_id = int(UIManager.GetFrameIDByHash(legacy_hash) or 0)
            if frame_id > 0 and UIManager.FrameExists(frame_id) and frame_id not in frames:
                frames.append(frame_id)
        return frames

    def get_slot_frame_id(self, slot: int) -> int:
        frames = self.get_apply_slot_frame_candidates(slot)
        return frames[0] if frames else 0

    def get_selected_row(self) -> Optional[PendingSkillRow]:
        if not self.pending_rows:
            return None
        index = min(max(self.selected_pending_index, 0), len(self.pending_rows) - 1)
        return self.pending_rows[index]

    def is_descendant_frame(self, frame_id: int, ancestor_frame_id: int) -> bool:
        current = int(frame_id or 0)
        guard = 0
        while current > 0 and guard < 64:
            if current == ancestor_frame_id:
                return True
            try:
                current = int(UIManager.GetParentFrameID(current) or 0)
            except Exception:
                return False
            guard += 1
        return False

    def get_ancestry_depth(self, frame_id: int, ancestor_frame_id: int, max_depth: int = 64) -> Optional[int]:
        current = int(frame_id or 0)
        depth = 0
        guard = 0
        while current > 0 and guard < max_depth:
            if current == ancestor_frame_id:
                return depth
            try:
                current = int(UIManager.GetParentFrameID(current) or 0)
            except Exception:
                return None
            depth += 1
            guard += 1
        return None

    def get_frame_descendants(self, ancestor_frame_id: int, max_depth: int = 4) -> List[int]:
        if ancestor_frame_id <= 0 or not UIManager.FrameExists(ancestor_frame_id):
            return []
        try:
            frame_array = UIManager.GetFrameArray()
        except Exception:
            return []

        matches: List[tuple[int, int]] = []
        for frame_id in frame_array:
            frame_id = int(frame_id or 0)
            if frame_id <= 0 or frame_id == ancestor_frame_id or not UIManager.FrameExists(frame_id):
                continue
            depth = self.get_ancestry_depth(frame_id, ancestor_frame_id, max_depth=max_depth)
            if depth is None or depth <= 0:
                continue
            matches.append((depth, frame_id))

        matches.sort(key=lambda item: (-item[0], item[1]))
        return [frame_id for _, frame_id in matches]

    def get_reward_window_slot_frame_candidates(self, slot: int) -> List[int]:
        reward_root = int(UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH) or 0)
        if reward_root <= 0 or not UIManager.FrameExists(reward_root):
            return []

        base_frames = [
            frame_id
            for frame_id in self.get_slot_frame_candidates(slot)
            if self.is_descendant_frame(frame_id, reward_root)
        ]
        if not base_frames:
            return []

        frames: List[int] = []
        for frame_id in base_frames:
            for descendant_id in self.get_frame_descendants(frame_id, max_depth=4):
                if descendant_id not in frames:
                    frames.append(descendant_id)
            if frame_id not in frames:
                frames.append(frame_id)
        return frames

    def get_reward_window_slot_target_frames(self, slot: int) -> List[int]:
        reward_root = int(UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH) or 0)
        if reward_root <= 0 or not UIManager.FrameExists(reward_root):
            return []
        frames: List[int] = []
        for frame_id in self.get_slot_frame_candidates(slot):
            if self.is_descendant_frame(frame_id, reward_root) and frame_id not in frames:
                frames.append(frame_id)
        try:
            direct_slot = int(UIManager.GetChildFrameByFrameId(reward_root, slot - 1) or 0)
        except Exception:
            direct_slot = 0
        if direct_slot > 0 and UIManager.FrameExists(direct_slot):
            for descendant_id in self.get_frame_descendants(direct_slot, max_depth=4):
                if descendant_id not in frames:
                    frames.append(descendant_id)
            if direct_slot not in frames:
                frames.append(direct_slot)
        return frames

    def get_apply_slot_frame_candidates(self, slot: int) -> List[int]:
        frames: List[int] = []
        for frame_id in self.get_slot_frame_candidates(slot):
            if frame_id not in frames:
                frames.append(frame_id)
        for frame_id in self.get_reward_window_slot_frame_candidates(slot):
            if frame_id not in frames:
                frames.append(frame_id)
        return frames

    def get_open_reward_ui_slot_frames(self, slot: int) -> List[int]:
        target_frames = self.get_reward_window_slot_target_frames(slot)
        if target_frames:
            return list(target_frames)

        slot_frames = self.get_reward_window_slot_frame_candidates(slot)
        if slot_frames:
            return list(slot_frames)

        return self.get_apply_slot_frame_candidates(slot)

    def get_visible_reward_context_frames(self, slot: int) -> List[int]:
        frames: List[int] = []
        reward_root = int(UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH) or 0)
        equip_frame = int(UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH) or 0)
        current_source_frame = int(self.latest_visible_reward.source_frame_id if self.latest_visible_reward else 0)
        prioritized = [
            reward_root,
            current_source_frame,
            equip_frame,
            *self.get_reward_window_slot_target_frames(slot),
            *self.get_reward_window_slot_frame_candidates(slot),
            *self.get_slot_frame_candidates(slot),
        ]
        for frame_id in prioritized:
            if frame_id > 0 and UIManager.FrameExists(frame_id) and frame_id not in frames:
                frames.append(frame_id)

        if reward_root <= 0 or not UIManager.FrameExists(reward_root):
            return frames

        try:
            frame_array = UIManager.GetFrameArray()
        except Exception:
            return frames

        for frame_id in frame_array:
            frame_id = int(frame_id or 0)
            if frame_id <= 0 or frame_id in frames or not UIManager.FrameExists(frame_id):
                continue
            if self.is_descendant_frame(frame_id, reward_root):
                frames.append(frame_id)
        return frames

    def refresh_visible_reward(self) -> None:
        self.latest_visible_reward = None
        self.latest_resolution_trace = []
        self.last_visible_reward_rejection = ""
        if not self.reward_window_is_visible():
            return
        if not self.ensure_native_ready():
            return
        if self.trace_hold_active and self.trace_hold_timer.HasElapsed(TRACE_HOLD_MS):
            self.trace_hold_active = False
        if self.active_request is None and not self.trace_hold_active:
            try:
                SkillAccept.clear_pending_skill_resolution_trace()
            except Exception:
                pass
        reward_root = int(UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH) or 0)

        for frame_id in self.get_visible_reward_context_frames(self.selected_slot):
            try:
                native_info = SkillAccept.get_visible_reward_skill_from_frame(frame_id)
            except Exception:
                continue

            skill_id = int(getattr(native_info, "skill_id", 0) or 0)
            if skill_id <= 0:
                continue
            source_frame_id = int(getattr(native_info, "source_frame_id", 0) or 0)
            if reward_root > 0 and source_frame_id > 0 and not self.is_descendant_frame(source_frame_id, reward_root):
                self.last_visible_reward_rejection = (
                    f"Rejected non-authoritative visible reward from frame {source_frame_id}; "
                    f"expected a descendant of reward root {reward_root}."
                )
                continue

            self.latest_visible_reward = VisibleRewardInfo(
                skill_id=skill_id,
                owner_id=int(getattr(native_info, "owner_id", 0) or 0),
                source_frame_id=source_frame_id,
                name=self.resolve_skill_name(skill_id),
            )
            break

        try:
            self.latest_resolution_trace = SkillAccept.get_pending_skill_resolution_trace()
        except Exception:
            self.latest_resolution_trace = []
        if self.latest_resolution_trace:
            self.preserved_resolution_trace = list(self.latest_resolution_trace)
        elif self.trace_hold_active and self.preserved_resolution_trace:
            self.latest_resolution_trace = list(self.preserved_resolution_trace)
        self.refresh_derived_traces()

    def clear_resolution_trace(self) -> None:
        self.latest_resolution_trace = []
        self.preserved_resolution_trace = []
        self.latest_apply_trace = []
        self.preserved_apply_trace = []
        self.latest_native_drag_trace = []
        self.preserved_native_drag_trace = []
        self.trace_hold_active = False
        try:
            SkillAccept.clear_pending_skill_resolution_trace()
        except Exception:
            pass

    def refresh_derived_traces(self) -> None:
        resolution_trace = self.latest_resolution_trace or self.preserved_resolution_trace
        apply_entries = [
            entry
            for entry in resolution_trace
            if str(getattr(entry, "stage", "")) in {
                "accept_offered_skill_replace",
                "apply_pending_skill",
                "apply_from_frame",
                "apply_open_reward_from_root",
                "apply_visible_reward_entry",
                "apply_visible_reward_from_frame",
                "target_frame_handler",
                "native_pending_apply",
                "native_drag_drop",
            }
        ]
        native_drag_entries = [
            entry
            for entry in resolution_trace
            if "native_drag_drop" in str(getattr(entry, "stage", "")) or "native_drag_drop" in str(getattr(entry, "reason", ""))
        ]
        if apply_entries:
            self.latest_apply_trace = list(apply_entries)
            self.preserved_apply_trace = list(apply_entries)
        elif not self.trace_hold_active:
            self.latest_apply_trace = []
        if native_drag_entries:
            self.latest_native_drag_trace = list(native_drag_entries)
            self.preserved_native_drag_trace = list(native_drag_entries)
        elif not self.trace_hold_active:
            self.latest_native_drag_trace = []

    def snapshot_resolution_trace(self) -> None:
        try:
            trace = SkillAccept.get_pending_skill_resolution_trace()
        except Exception:
            return
        if trace:
            self.latest_resolution_trace = list(trace)
            self.preserved_resolution_trace = list(trace)
            self.refresh_derived_traces()

    def hold_resolution_trace(self) -> None:
        self.snapshot_resolution_trace()
        self.trace_hold_active = True
        self.trace_hold_timer.Reset()

    def get_apply_trace_entries(self) -> List[object]:
        return self.latest_apply_trace or self.preserved_apply_trace

    def get_native_drag_trace_entries(self) -> List[object]:
        return self.latest_native_drag_trace or self.preserved_native_drag_trace

    def describe_last_apply_failure(self) -> str:
        apply_entries = self.get_apply_trace_entries()
        native_drag_entries = self.get_native_drag_trace_entries()
        if native_drag_entries:
            entry = native_drag_entries[-1]
        elif apply_entries:
            entry = apply_entries[-1]
        else:
            return "Native apply failed before native trace was captured."
        return (
            f"Native apply failed at {getattr(entry, 'stage', '')}/{getattr(entry, 'reason', '')} "
            f"(q={getattr(entry, 'queried_frame_id', 0)}, "
            f"f={getattr(entry, 'inspected_frame_id', 0)}, "
            f"slot={getattr(entry, 'slot_index', 0)})."
        )

    def describe_last_native_drag_result(self) -> str:
        native_drag_entries = self.get_native_drag_trace_entries()
        if not native_drag_entries:
            return "No native drag result was captured."
        entry = native_drag_entries[-1]
        return (
            f"Native drag result: {getattr(entry, 'reason', '')} "
            f"(q={getattr(entry, 'queried_frame_id', 0)}, "
            f"f={getattr(entry, 'inspected_frame_id', 0)}, "
            f"slot={getattr(entry, 'slot_index', 0)})."
        )

    def get_last_native_drag_reason(self) -> str:
        native_drag_entries = self.get_native_drag_trace_entries()
        if not native_drag_entries:
            return ""
        return str(getattr(native_drag_entries[-1], "reason", "") or "")

    def get_last_apply_reason(self) -> str:
        apply_entries = self.get_apply_trace_entries()
        if apply_entries:
            return str(getattr(apply_entries[-1], "reason", "") or "")
        return self.get_last_native_drag_reason()

    def queue_ui_fallback(
        self,
        slot: int,
        expected_skill_id: Optional[int],
        mode: str,
        source_frame_id: int = 0,
    ) -> bool:
        if self.reward_window_is_visible():
            slot_frames = self.get_open_reward_ui_slot_frames(slot)
        else:
            slot_frames = self.get_apply_slot_frame_candidates(slot)
        equip_frame = UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH)
        if not slot_frames:
            self.status_message = f"UI fallback aborted: slot {slot} frame is missing."
            return False
        if not equip_frame or not UIManager.FrameExists(equip_frame):
            self.status_message = "UI fallback aborted: Equip button is not visible."
            return False

        self.clear_resolution_trace()
        queue = ActionQueueManager()
        queue.ResetQueue("FAST")
        if source_frame_id > 0 and UIManager.FrameExists(source_frame_id):
            queue.AddAction("FAST", UIManager.TestMouseClickAction, source_frame_id, UI_MOUSE_CLICK_STATE, 0, 0)
            queue.AddActionWithDelay("FAST", SOURCE_CLICK_SETTLE_DELAY_MS, _noop_action)
        for slot_frame in slot_frames:
            queue.AddAction("FAST", UIManager.TestMouseAction, slot_frame, UI_MOUSE_CLICK_STATE, 0, 0)
            queue.AddAction("FAST", UIManager.TestMouseClickAction, slot_frame, UI_MOUSE_CLICK_STATE, 0, 0)
            queue.AddActionWithDelay("FAST", SLOT_CLICK_SETTLE_DELAY_MS, _noop_action)
        queue.AddActionWithDelay("FAST", POST_SLOT_SELECTION_DELAY_MS, _noop_action)
        queue.AddAction("FAST", UIManager.TestMouseAction, equip_frame, UI_MOUSE_CLICK_STATE, 0, 0)
        queue.AddAction("FAST", UIManager.TestMouseClickAction, equip_frame, UI_MOUSE_CLICK_STATE, 0, 0)
        queue.AddAction("FAST", UIManager.FrameClick, equip_frame)
        queue.AddAction("FAST", UIManager.TestMouseAction, equip_frame, UI_MOUSE_CLICK_STATE, 0, 0)
        self.active_request = RequestedApply(
            slot=slot,
            mode=mode,
            retries_left=MAX_UI_RETRIES - 1,
            expected_skill_id=expected_skill_id,
            pre_slot_skill_id=int(SkillBar.GetSkillIDBySlot(slot) or 0),
            source_frame_id=int(source_frame_id or 0),
            slot_frame_ids=tuple(int(frame_id) for frame_id in slot_frames),
        )
        self.apply_timer.Reset()
        if expected_skill_id is None:
            self.status_message = f"Open reward UI action queued for slot {slot} via frames {slot_frames}."
        else:
            self.status_message = (
                f"UI fallback queued for {self.resolve_skill_name(expected_skill_id)} "
                f"in slot {slot} via source frame {int(source_frame_id or 0)} and slot frames {slot_frames}."
            )
        return True

    def queue_native_visible_reward_apply(self, slot: int, info: VisibleRewardInfo, start_index: int = 0) -> bool:
        if slot < 1 or slot > 8:
            self.status_message = f"Native apply aborted: slot {slot} is out of range."
            return False
        if info.source_frame_id <= 0 or not UIManager.FrameExists(info.source_frame_id):
            self.status_message = "Native apply aborted: visible reward source frame is missing."
            return False

        target_frames = self.get_reward_window_slot_target_frames(slot)
        if not target_frames:
            self.status_message = (
                f"Native apply aborted: no reward-window slot target frame was found for slot {slot}."
            )
            return False
        slot_selection_frames = self.get_reward_window_slot_frame_candidates(slot)
        if not slot_selection_frames:
            slot_selection_frames = list(target_frames)

        owner_id = int(info.owner_id or 0)
        if owner_id <= 0:
            owner_id = int(self.get_player_agent_id() or 0)
        if start_index < 0:
            start_index = 0
        request = RequestedApply(
            slot=slot,
            mode="native-visible-prime",
            retries_left=0,
            expected_skill_id=info.skill_id,
            pre_slot_skill_id=int(SkillBar.GetSkillIDBySlot(slot) or 0),
            source_frame_id=int(info.source_frame_id or 0),
            slot_frame_ids=tuple(int(frame_id) for frame_id in slot_selection_frames),
            attempted_target_index=start_index,
            target_frame_ids=tuple(int(frame_id) for frame_id in target_frames),
            owner_id=owner_id,
        )

        for target_index in range(start_index, len(request.target_frame_ids)):
            if self.try_native_pending_apply_from_target(request, target_index):
                return True

        self.clear_resolution_trace()
        queue = ActionQueueManager()
        queue.ResetQueue("FAST")
        for frame_id in slot_selection_frames:
            if frame_id <= 0 or not UIManager.FrameExists(frame_id):
                continue
            queue.AddAction("FAST", UIManager.TestMouseAction, frame_id, UI_MOUSE_CLICK_STATE, 0, 0)
            queue.AddAction("FAST", UIManager.TestMouseClickAction, frame_id, UI_MOUSE_CLICK_STATE, 0, 0)
            queue.AddActionWithDelay("FAST", SLOT_CLICK_SETTLE_DELAY_MS, _noop_action)
        queue.AddActionWithDelay("FAST", POST_SLOT_SELECTION_DELAY_MS, _noop_action)
        self.active_request = request
        self.apply_timer.Reset()
        self.status_message = (
            f"Priming reward target selection for {info.name} in slot {slot} "
            f"via selection frames {slot_selection_frames} before native pending apply."
        )
        return True

    def try_native_pending_apply_from_target(self, request: RequestedApply, target_index: int) -> bool:
        if request.expected_skill_id is None:
            return False
        if target_index < 0 or target_index >= len(request.target_frame_ids):
            return False

        target_frame_id = int(request.target_frame_ids[target_index] or 0)
        if target_frame_id <= 0 or not UIManager.FrameExists(target_frame_id):
            return False

        self.clear_resolution_trace()
        try:
            queued = bool(
                SkillAccept.apply_pending_skill_replace_from_frame(
                    request.expected_skill_id,
                    request.slot - 1,
                    target_frame_id,
                    request.owner_id,
                )
            )
        except Exception as exc:
            self.snapshot_resolution_trace()
            self.status_message = f"Native pending apply raised before queue: {exc}"
            return False
        self.snapshot_resolution_trace()
        if not queued:
            return False

        request.mode = "native-visible"
        request.attempted_target_index = target_index
        self.active_request = request
        self.apply_timer.Reset()
        self.status_message = (
            f"Native pending apply queued for {self.resolve_skill_name(request.expected_skill_id)} "
            f"in slot {request.slot} via target frame {target_frame_id}."
        )
        return True

    def request_open_window_ui_apply(self, source: str) -> None:
        if self.queue_ui_fallback(self.selected_slot, None, "ui-open"):
            ConsoleLog(
                MODULE_NAME,
                f"Queued open reward UI apply for slot={self.selected_slot} source={source}",
                Console.MessageType.Info,
            )
            return
        self.status_message = "Open reward UI apply failed: slot or Equip frame was unavailable."

    def request_visible_reward_apply(self, source: str) -> None:
        self.refresh_visible_reward()
        info = self.latest_visible_reward
        if info is None:
            self.status_message = "No live reward skill resolved for this open window yet."
            return

        current_slot_skill_id = int(SkillBar.GetSkillIDBySlot(self.selected_slot) or 0)
        if current_slot_skill_id == info.skill_id:
            self.status_message = f"Slot {self.selected_slot} already contains {info.name}."
            return

        if self.queue_native_visible_reward_apply(self.selected_slot, info):
            ConsoleLog(
                MODULE_NAME,
                f"Queued visible reward native apply for skill_id={info.skill_id} slot={self.selected_slot} source={source}",
                Console.MessageType.Info,
            )
            return
        return

    def queue_native_pending_apply(self, slot: int, row: PendingSkillRow) -> bool:
        if slot < 1 or slot > 8:
            self.status_message = f"Native pending apply aborted: slot {slot} is out of range."
            return False

        agent_id = self.get_player_agent_id()
        if agent_id <= 0:
            self.status_message = "Native pending apply aborted: controlled player agent id is unavailable."
            return False

        self.clear_resolution_trace()
        queued = False
        try:
            queued = bool(
                SkillAccept.apply_pending_skill_replace(
                    row.skill_id,
                    slot - 1,
                    row.copy_id,
                    agent_id,
                )
            )
        except Exception as exc:
            self.status_message = f"Native pending apply failed before queue: {exc}"
            return False
        finally:
            self.snapshot_resolution_trace()

        if not queued:
            self.hold_resolution_trace()
            self.status_message = (
                f"{self.describe_last_apply_failure()} Pending reward {row.name} "
                f"[id={row.skill_id}, copy={row.copy_id}] slot={slot} owner={agent_id}."
            )
            return False

        self.active_request = RequestedApply(
            slot=slot,
            mode="native-pending",
            retries_left=0,
            expected_skill_id=row.skill_id,
            pre_slot_skill_id=int(SkillBar.GetSkillIDBySlot(slot) or 0),
        )
        self.apply_timer.Reset()
        self.status_message = (
            f"Native pending apply queued for {row.name} in slot {slot} "
            f"(copy {row.copy_id}, owner {agent_id})."
        )
        return True

    def request_apply(self, row: PendingSkillRow, source: str) -> None:
        current_slot_skill_id = int(SkillBar.GetSkillIDBySlot(self.selected_slot) or 0)
        if current_slot_skill_id == row.skill_id:
            self.status_message = f"Slot {self.selected_slot} already contains {row.name}."
            return

        if self.reward_window_is_visible():
            self.refresh_visible_reward()
            if self.latest_visible_reward is None:
                self.request_open_window_ui_apply(source)
                return
            if self.latest_visible_reward.skill_id != row.skill_id:
                self.status_message = (
                    f"Open reward window is offering {self.latest_visible_reward.name}; "
                    f"cached pending skill {row.name} was ignored."
                )
                return
            self.request_visible_reward_apply(source)
            return

        if self.queue_native_pending_apply(self.selected_slot, row):
            ConsoleLog(
                MODULE_NAME,
                f"Queued closed-window pending apply for skill_id={row.skill_id} slot={self.selected_slot} source={source}",
                Console.MessageType.Info,
            )
            return

    def request_manual_apply(self) -> None:
        skill_id = int(self.manual_skill_id or 0)
        if self.reward_window_is_visible():
            self.refresh_visible_reward()
            if self.latest_visible_reward is not None:
                self.request_visible_reward_apply("manual-visible")
                return
            if skill_id > 0:
                self.status_message = (
                    "Manual native apply is disabled while the live reward source frame is unresolved. "
                    "Use Apply Open Reward (UI) or wait for live reward detection."
                )
                return
            self.request_open_window_ui_apply("manual-open")
            return

        if skill_id <= 0:
            self.status_message = "Select a cached pending reward or enter a manual skill id."
            return

        row = next((item for item in self.pending_rows if item.skill_id == skill_id), None)
        if row is None:
            self.status_message = (
                f"No cached pending reward matches manual skill id {skill_id}. "
                "Use a listed pending reward or re-open the reward window."
            )
            return
        self.request_apply(row, "manual-pending")

    def has_pending_skill(self, skill_id: int) -> bool:
        return any(row.skill_id == skill_id for row in self.pending_rows)

    def update_active_request(self) -> None:
        request = self.active_request
        if request is None:
            return

        if request.mode == "native-visible-prime":
            if not ActionQueueManager().IsEmpty("FAST"):
                return
            for target_index in range(request.attempted_target_index, len(request.target_frame_ids)):
                if self.try_native_pending_apply_from_target(request, target_index):
                    return
            self.hold_resolution_trace()
            self.status_message = (
                f"{self.describe_last_apply_failure()} "
                f"Source frame {request.source_frame_id}, slot {request.slot}, target frames {list(request.target_frame_ids)}."
            )
            self.active_request = None
            return

        if not self.apply_timer.HasElapsed(UI_SETTLE_DELAY_MS):
            return

        slot_skill_id = int(SkillBar.GetSkillIDBySlot(request.slot) or 0)
        if request.expected_skill_id is not None and slot_skill_id == request.expected_skill_id:
            self.status_message = (
                f"Applied {self.resolve_skill_name(request.expected_skill_id)} to slot {request.slot} via {request.mode}."
            )
            self.last_auto_signature = (request.expected_skill_id, request.slot)
            self.hold_resolution_trace()
            self.active_request = None
            return

        reward_window_visible = self.reward_window_is_visible()

        if request.mode == "native-visible":
            apply_reason = self.get_last_apply_reason()
            next_target_index = request.attempted_target_index + 1
            if (
                reward_window_visible
                and apply_reason in {
                    "native_drag_drop_target_rejected_accept_0",
                    "native_drag_drop_gate_rejected",
                    "pending_state_unresolved_from_frame",
                    "pending_state_slot_mismatch",
                    "native_pending_apply_call_failed",
                    "pending_apply_no_verifiable_slot_change",
                    "pre_slot_snapshot_unreadable",
                    "post_slot_snapshot_unreadable",
                }
                and next_target_index < len(request.target_frame_ids)
            ):
                self.refresh_visible_reward()
                if (
                    self.latest_visible_reward is not None
                    and request.expected_skill_id is not None
                    and self.latest_visible_reward.skill_id == request.expected_skill_id
                    and self.queue_native_visible_reward_apply(
                        request.slot,
                        self.latest_visible_reward,
                        start_index=next_target_index,
                    )
                ):
                    return

        if request.mode == "ui-open":
            if slot_skill_id != request.pre_slot_skill_id:
                self.status_message = (
                    f"Open reward UI action changed slot {request.slot} from "
                    f"{self.resolve_skill_name(request.pre_slot_skill_id)} to {self.resolve_skill_name(slot_skill_id)}."
                )
                self.hold_resolution_trace()
                self.active_request = None
                return
            if not reward_window_visible:
                self.status_message = (
                    f"Open reward UI action submitted for slot {request.slot}; "
                    "reward window closed without a verifiable slot change."
                )
                self.hold_resolution_trace()
                self.active_request = None
                return
            if request.retries_left > 0:
                if self.queue_ui_fallback(request.slot, None, "ui-open") and self.active_request is not None:
                    self.active_request.retries_left = request.retries_left - 1
                else:
                    self.active_request = None
                return
            self.status_message = (
                f"Open reward UI action did not verify for slot {request.slot} "
                f"after slot frames {list(request.slot_frame_ids) if request.slot_frame_ids else 'none'}."
            )
            self.hold_resolution_trace()
            self.active_request = None
            return

        if reward_window_visible and request.retries_left > 0 and request.expected_skill_id is not None:
            if self.queue_ui_fallback(
                request.slot,
                request.expected_skill_id,
                request.mode,
                request.source_frame_id,
            ) and self.active_request is not None:
                self.active_request.retries_left = request.retries_left - 1
            else:
                self.active_request = None
            return

        if request.expected_skill_id is not None and not reward_window_visible:
            if request.mode == "native-pending":
                self.status_message = (
                    f"Closed-window pending apply for {self.resolve_skill_name(request.expected_skill_id)} "
                    f"did not change slot {request.slot}."
                )
            else:
                self.status_message = (
                    f"Reward window closed for {self.resolve_skill_name(request.expected_skill_id)}, "
                    f"but slot {request.slot} could not be verified."
                )
        else:
            native_drag_summary = ""
            if request.mode == "native-visible":
                apply_reason = self.get_last_apply_reason()
                if "native_drag_drop" in apply_reason:
                    native_drag_summary = f" {self.describe_last_native_drag_result()}"
            self.status_message = (
                f"Apply did not verify for slot {request.slot} after source frame {request.source_frame_id} "
                f"and slot frames {list(request.target_frame_ids) if request.target_frame_ids else list(request.slot_frame_ids) if request.slot_frame_ids else 'none'}."
                f"{native_drag_summary}"
            )
        self.hold_resolution_trace()
        self.active_request = None

    def maybe_auto_apply(self) -> None:
        if not self.auto_apply_single_pending or self.active_request is not None:
            return
        row: Optional[PendingSkillRow] = None
        if self.reward_window_is_visible():
            if self.latest_visible_reward is None:
                return
            signature = (self.latest_visible_reward.skill_id, self.selected_slot)
        else:
            if len(self.pending_rows) != 1:
                self.last_auto_signature = None
                self.last_auto_attempt_signature = None
                return
            row = self.pending_rows[0]
            signature = (row.skill_id, self.selected_slot)
        if self.last_auto_signature == signature:
            return
        if self.last_auto_attempt_signature == signature and not self.auto_attempt_timer.HasElapsed(1000):
            return
        self.last_auto_attempt_signature = signature
        self.auto_attempt_timer.Reset()
        if self.reward_window_is_visible():
            self.request_visible_reward_apply("auto")
            return
        if row is not None:
            self.request_apply(row, "auto-pending")

    def update(self) -> None:
        if not self.is_runtime_ready():
            return
        ActionQueueManager().ProcessQueue("FAST")
        if self.active_request is None and self.pending_refresh_timer.HasElapsed(200):
            self.refresh_visible_reward()
            self.refresh_pending_rows()
            self.pending_refresh_timer.Reset()
        self.update_active_request()
        self.maybe_auto_apply()

    def draw_pending_rows(self) -> None:
        if self.latest_visible_reward is not None:
            info = self.latest_visible_reward
            PyImGui.text(f"Visible reward: {info.name}")
            PyImGui.text(f"Skill ID: {info.skill_id}")
            PyImGui.text(f"Owner ID: {info.owner_id}")
            PyImGui.text(f"Current slot {self.selected_slot}: {self.resolve_skill_name(int(SkillBar.GetSkillIDBySlot(self.selected_slot) or 0))}")
            if PyImGui.button("Apply Current Reward (Preferred)"):
                self.request_visible_reward_apply("manual-visible")
            if PyImGui.button("Apply Visible Reward (UI)"):
                self.queue_ui_fallback(self.selected_slot, info.skill_id, "ui-visible", info.source_frame_id)
            if self.pending_rows:
                PyImGui.separator()
        elif self.reward_window_is_visible():
            PyImGui.text_wrapped(
                "Live reward is not resolved yet. Pending-skill cache is hidden because it is not authoritative "
                "for this open Equip Skill window."
            )
            if PyImGui.button("Apply Open Reward (UI)"):
                self.request_open_window_ui_apply("manual-open")
            return

        if not self.pending_rows:
            if self.reward_window_is_visible() and self.latest_visible_reward is None:
                PyImGui.text("No live reward skill resolved for this open window yet.")
            else:
                PyImGui.text("No pending mission reward skill detected.")
            return

        labels = [
            f"{row.name} [id={row.skill_id}, copy={row.copy_id}, refs={row.ref_count}]"
            for row in self.pending_rows
        ]
        PyImGui.text_wrapped(
            "Pending-skill cache entries below drive the closed-window native replace path. "
            "Use them after the reward window closes; while the reward window is open, prefer the live visible reward path."
        )
        self.selected_pending_index = PyImGui.combo("Pending Skill", self.selected_pending_index, labels)
        row = self.get_selected_row()
        if row is None:
            return

        PyImGui.text(f"Selected: {row.name}")
        PyImGui.text(f"Skill ID: {row.skill_id}")
        PyImGui.text(f"Copy ID: {row.copy_id}")
        PyImGui.text(f"Current slot {self.selected_slot}: {self.resolve_skill_name(int(SkillBar.GetSkillIDBySlot(self.selected_slot) or 0))}")
        if PyImGui.button("Apply Selected Pending Reward"):
            self.request_apply(row, "manual-pending")

    def draw_debug(self) -> None:
        if not PyImGui.collapsing_header("Diagnostics"):
            return

        PyImGui.text(f"Native ready: {self.native_ready}")
        PyImGui.text(f"Widget build: {WIDGET_BUILD_ID}")
        if self.native_error:
            PyImGui.text_wrapped(f"Native error: {self.native_error}")
        PyImGui.text(f"Reward window visible: {self.reward_window_is_visible()}")
        PyImGui.text(f"Player agent id: {self.get_player_agent_id()}")
        if self.latest_visible_reward is None:
            PyImGui.text("Visible reward resolver: none")
        else:
            PyImGui.text(
                f"Visible reward resolver: {self.latest_visible_reward.name} "
                f"[id={self.latest_visible_reward.skill_id}, owner={self.latest_visible_reward.owner_id}]"
            )
            PyImGui.text(f"Visible reward source frame: {self.latest_visible_reward.source_frame_id}")
        if self.last_visible_reward_rejection:
            PyImGui.text_wrapped(self.last_visible_reward_rejection)
        reward_root = UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH)
        PyImGui.text(f"Reward root frame: {reward_root}")
        slot_frames = self.get_slot_frame_candidates(self.selected_slot)
        PyImGui.text(f"Selected slot frames: {slot_frames if slot_frames else 'none'}")
        reward_slot_frames = self.get_reward_window_slot_frame_candidates(self.selected_slot)
        PyImGui.text(f"Reward-window slot frames: {reward_slot_frames if reward_slot_frames else 'none'}")
        reward_target_frames = self.get_reward_window_slot_target_frames(self.selected_slot)
        PyImGui.text(f"Reward-window target frames: {reward_target_frames if reward_target_frames else 'none'}")
        equip_frame = UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH)
        PyImGui.text(f"Equip button frame: {equip_frame}")
        resolution_trace = self.latest_resolution_trace or self.preserved_resolution_trace
        native_entries = self.get_native_drag_trace_entries()
        apply_entries = self.get_apply_trace_entries()
        if resolution_trace or native_entries or apply_entries:
            PyImGui.separator()
            if resolution_trace:
                PyImGui.text("Resolution trace:")
                for entry in resolution_trace[-6:]:
                    PyImGui.text_wrapped(
                        f"{'OK' if getattr(entry, 'accepted', False) else 'NO'} "
                        f"{getattr(entry, 'stage', '')}/{getattr(entry, 'reason', '')} "
                        f"q={getattr(entry, 'queried_frame_id', 0)} "
                        f"f={getattr(entry, 'inspected_frame_id', 0)}:{getattr(entry, 'inspected_frame_hash', 0)} "
                        f"d={getattr(entry, 'ancestry_depth', 0)} "
                        f"cb=0x{int(getattr(entry, 'callback_ptr', 0)):08X} "
                        f"ctx=0x{int(getattr(entry, 'context_ptr', 0)):08X} "
                        f"st=0x{int(getattr(entry, 'state_ptr', 0)):08X} "
                        f"root={getattr(entry, 'root_frame_id', 0)}:{getattr(entry, 'root_frame_hash', 0)} "
                        f"equip={getattr(entry, 'equip_button_frame_id', 0)} "
                        f"slot={getattr(entry, 'slot_index', 0)} "
                        f"owner={getattr(entry, 'owner_id', 0)} "
                        f"skill={getattr(entry, 'skill_id', 0)}"
                    )
            if native_entries:
                PyImGui.separator()
                PyImGui.text("Native drag trace:")
                for entry in native_entries[-6:]:
                    PyImGui.text_wrapped(
                        f"{'OK' if getattr(entry, 'accepted', False) else 'NO'} "
                        f"{getattr(entry, 'stage', '')}/{getattr(entry, 'reason', '')} "
                        f"q={getattr(entry, 'queried_frame_id', 0)} "
                        f"f={getattr(entry, 'inspected_frame_id', 0)}:{getattr(entry, 'inspected_frame_hash', 0)} "
                        f"root={getattr(entry, 'root_frame_id', 0)}:{getattr(entry, 'root_frame_hash', 0)} "
                        f"slot={getattr(entry, 'slot_index', 0)} "
                        f"owner={getattr(entry, 'owner_id', 0)} "
                        f"skill={getattr(entry, 'skill_id', 0)}"
                    )
            if apply_entries:
                PyImGui.separator()
                PyImGui.text("Apply trace:")
                for entry in apply_entries[-6:]:
                    PyImGui.text_wrapped(
                        f"{'OK' if getattr(entry, 'accepted', False) else 'NO'} "
                        f"{getattr(entry, 'stage', '')}/{getattr(entry, 'reason', '')} "
                        f"q={getattr(entry, 'queried_frame_id', 0)} "
                        f"f={getattr(entry, 'inspected_frame_id', 0)}:{getattr(entry, 'inspected_frame_hash', 0)} "
                        f"root={getattr(entry, 'root_frame_id', 0)}:{getattr(entry, 'root_frame_hash', 0)} "
                        f"slot={getattr(entry, 'slot_index', 0)} "
                        f"owner={getattr(entry, 'owner_id', 0)} "
                        f"skill={getattr(entry, 'skill_id', 0)}"
                    )

    def draw(self) -> None:
        if PyImGui.begin(MODULE_NAME):
            PyImGui.text_wrapped(
                "Stable helper for the post-grant mission skill reward window. "
                "It prefers native pending-skill replacement and falls back to a short UI click path only when needed."
            )
            PyImGui.separator()

            slots = [str(index) for index in range(1, 9)]
            self.selected_slot = PyImGui.combo("Target Slot", self.selected_slot - 1, slots) + 1
            self.auto_apply_single_pending = PyImGui.checkbox(
                "Auto-apply when exactly one pending reward exists",
                self.auto_apply_single_pending,
            )

            PyImGui.separator()
            self.draw_pending_rows()

            PyImGui.separator()
            self.manual_skill_id = PyImGui.input_int("Manual Skill ID", self.manual_skill_id)
            if PyImGui.button("Try Manual Apply"):
                self.request_manual_apply()

            PyImGui.separator()
            PyImGui.text_wrapped(self.status_message)
            self.draw_debug()
        PyImGui.end()


def tooltip() -> None:
    PyImGui.begin_tooltip()
    title_color = Color(255, 200, 100, 255)
    ImGui.push_font("Regular", 20)
    PyImGui.text_colored(MODULE_NAME, title_color.to_tuple_normalized())
    ImGui.pop_font()
    PyImGui.separator()
    PyImGui.text("Handles the mission reward equip window with bounded retries.")
    PyImGui.text("Native pending-skill apply is preferred after the reward window closes.")
    PyImGui.text("UI click fallback uses one slot click plus Equip.")
    PyImGui.end_tooltip()


_widget = MissionSkillRewardWidget()


def main() -> None:
    _widget.update()
    _widget.draw()


if __name__ == "__main__":
    main()
