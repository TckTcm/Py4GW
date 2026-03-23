from __future__ import annotations

from typing import List

import Py4GWCoreLib.SkillAccept as SkillAccept
from Py4GWCoreLib import (
    ActionQueueManager,
    Color,
    ImGui,
    Map,
    Player,
    PyImGui,
    Skill,
    SkillBar,
    Timer,
    UIManager,
)

MODULE_NAME = "Rojis Disarm Trap"
MISSION_NAME = "Venta Cemetery"
NPC_NAME = "Rojis"
DISARM_TRAP_SKILL_ID = 1418
FLOW_TIMEOUT_MS = 1500
VERIFY_DELAY_MS = 1200
TRACE_PREVIEW_COUNT = 6
MAX_UI_RETRIES = 3
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
UI_MOUSE_CLICK_STATE = 8
SOURCE_CLICK_SETTLE_DELAY_MS = 120
SLOT_CLICK_SETTLE_DELAY_MS = 45
POST_SLOT_SELECTION_DELAY_MS = 180


def _noop_action() -> None:
    return None


class RojisDisarmTrapWidget:
    def __init__(self) -> None:
        self.selected_slot = 8
        self.status_message = "Idle."
        self.pending_flow_request = False
        self.verifying_apply = False
        self.verify_slot = 0
        self.verify_pre_slot_skill_id = 0
        self.verify_source_frame_id = 0
        self.verify_slot_frame_ids: tuple[int, ...] = ()
        self.verify_retries_left = 0
        self.verify_timer = Timer()
        self.verify_timer.Start()
        self.last_trace: List[object] = []
        self.last_frame_events: List[object] = []
        self.last_queue_plan: List[str] = []
        self.last_queue_history: List[str] = []
        self.last_queue_debug: List[str] = []
        self.last_retry_debug: List[str] = []
        self.last_ui_debug: List[str] = []
        self.last_visible_candidate_debug: List[str] = []
        self.last_ui_payload_debug: List[str] = []

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

    def current_slot_skill_id(self, slot: int) -> int:
        try:
            return int(SkillBar.GetSkillIDBySlot(slot) or 0)
        except Exception:
            return 0

    def reward_window_is_visible(self) -> bool:
        equip_frame = int(UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH) or 0)
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

    def get_ancestry_depth(self, frame_id: int, ancestor_frame_id: int, max_depth: int = 64) -> int | None:
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

    def get_open_reward_ui_slot_frames(self, slot: int) -> List[int]:
        slot_frames = self.get_reward_window_slot_frame_candidates(slot)
        if slot_frames:
            return list(slot_frames)

        target_frames = self.get_reward_window_slot_target_frames(slot)
        if target_frames:
            return list(target_frames)

        return self.get_slot_frame_candidates(slot)

    def refresh_queue_debug(self) -> None:
        try:
            queue = ActionQueueManager()
            self.last_queue_plan = list(queue.GetAllActionNames("FAST"))
            self.last_queue_history = list(queue.GetHistoryNames("FAST"))
        except Exception:
            self.last_queue_plan = []
            self.last_queue_history = []

    def _decode_payload_u32(self, payload: object, index: int) -> int:
        try:
            raw = list(payload or [])
        except Exception:
            return 0
        start = index * 4
        if len(raw) < start + 4:
            return 0
        try:
            return int.from_bytes(bytes(int(value) & 0xFF for value in raw[start:start + 4]), "little")
        except Exception:
            return 0

    def refresh_ui_payload_debug(self) -> None:
        slot = int(self.verify_slot or self.selected_slot or 0)
        reward_root = int(UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH) or 0)
        equip_frame = int(UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH) or 0)
        slot_frames = [int(frame_id or 0) for frame_id in self.get_open_reward_ui_slot_frames(slot)]
        verified_slot_frames = [int(frame_id or 0) for frame_id in self.verify_slot_frame_ids if int(frame_id or 0) > 0]
        target_frames = {
            frame_id
            for frame_id in [reward_root, equip_frame, self.verify_source_frame_id, *slot_frames, *verified_slot_frames]
            if frame_id > 0
        }

        lines: List[str] = []
        try:
            logs = list(UIManager.GetUIMessageLogs())
        except Exception:
            self.last_ui_payload_debug = []
            return

        for tick, message_id, incoming, is_frame_message, frame_id, w_bytes, l_bytes in reversed(logs):
            frame_id = int(frame_id or 0)
            w0 = self._decode_payload_u32(w_bytes, 0)
            w1 = self._decode_payload_u32(w_bytes, 1)
            if target_frames and frame_id not in target_frames and w0 not in target_frames and w1 not in target_frames:
                continue
            lines.append(
                f"tick={int(tick)} msg=0x{int(message_id):08X} "
                f"incoming={bool(incoming)} frame_msg={bool(is_frame_message)} "
                f"frame={frame_id} w0={w0} w1={w1} "
                f"w={list(w_bytes[:8])} l={list(l_bytes[:8])}"
            )
            if len(lines) >= TRACE_PREVIEW_COUNT:
                break
        self.last_ui_payload_debug = lines

    def refresh_ui_debug(self, slot: int, source_frame_id: int = 0, slot_frames: List[int] | None = None) -> None:
        reward_root = int(UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH) or 0)
        equip_frame = int(UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH) or 0)
        slot_frames = list(slot_frames or [])
        try:
            target_frames = list(self.get_reward_window_slot_target_frames(slot))
        except Exception:
            target_frames = []
        try:
            frame_candidates = list(self.get_reward_window_slot_frame_candidates(slot))
        except Exception:
            frame_candidates = []
        lines = [
            f"source={int(source_frame_id or 0)} exists={bool(source_frame_id and UIManager.FrameExists(source_frame_id))}",
            f"reward_root={reward_root} exists={bool(reward_root and UIManager.FrameExists(reward_root))}",
            f"equip_frame={equip_frame} exists={bool(equip_frame and UIManager.FrameExists(equip_frame))}",
            f"slot_frames={slot_frames}",
            f"slot_target_frames={target_frames}",
            f"slot_frame_candidates={frame_candidates}",
        ]
        for frame_id in [int(source_frame_id or 0), *slot_frames, equip_frame]:
            if frame_id <= 0:
                continue
            try:
                parent = int(UIManager.GetParentFrameID(frame_id) or 0)
            except Exception:
                parent = 0
            lines.append(
                f"frame {frame_id}: exists={bool(UIManager.FrameExists(frame_id))} parent={parent} "
                f"in_reward={self.is_descendant_frame(frame_id, reward_root) if reward_root > 0 else False}"
            )
        self.last_ui_debug = lines
        self.refresh_visible_candidate_debug(slot)

    def refresh_visible_candidate_debug(self, slot: int) -> None:
        reward_root = int(UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH) or 0)
        lines: List[str] = []
        candidates = self.get_visible_reward_candidate_frames(slot)
        if reward_root > 0:
            lines.append(f"reward_root={reward_root} candidate_count={len(candidates)}")
        else:
            lines.append(f"reward_root=0 candidate_count={len(candidates)}")

        for frame_id in candidates:
            frame_id = int(frame_id or 0)
            if frame_id <= 0:
                continue
            try:
                info = SkillAccept.get_visible_reward_skill_from_frame(frame_id)
            except Exception as exc:
                lines.append(f"frame {frame_id}: resolver_error={exc}")
                continue
            skill_id = int(getattr(info, "skill_id", 0) or 0)
            owner_id = int(getattr(info, "owner_id", 0) or 0)
            source_frame_id = int(getattr(info, "source_frame_id", 0) or 0)
            if skill_id <= 0 and source_frame_id <= 0 and frame_id != reward_root:
                continue
            depth = self.get_ancestry_depth(frame_id, reward_root, max_depth=8) if reward_root > 0 else None
            lines.append(
                f"frame {frame_id}: depth={depth} skill={skill_id} owner={owner_id} source={source_frame_id}"
            )
            if len(lines) >= 16:
                break
        self.last_visible_candidate_debug = lines

    def get_visible_reward_candidate_frames(self, slot: int) -> List[int]:
        frames: List[int] = []
        reward_root = int(UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH) or 0)
        equip_frame = int(UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH) or 0)
        prioritized = [
            reward_root,
            equip_frame,
            *self.get_reward_window_slot_target_frames(slot),
            *self.get_reward_window_slot_frame_candidates(slot),
            *self.get_open_reward_ui_slot_frames(slot),
        ]
        for frame_id in prioritized:
            frame_id = int(frame_id or 0)
            if frame_id > 0 and UIManager.FrameExists(frame_id) and frame_id not in frames:
                frames.append(frame_id)

        if reward_root > 0 and UIManager.FrameExists(reward_root):
            for frame_id in self.get_frame_descendants(reward_root, max_depth=5):
                if frame_id > 0 and UIManager.FrameExists(frame_id) and frame_id not in frames:
                    frames.append(frame_id)
        return frames

    def resolve_open_reward_anchor_frame(self, slot: int) -> int:
        reward_root = int(UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH) or 0)
        for frame_id in self.get_visible_reward_candidate_frames(slot):
            try:
                native_info = SkillAccept.get_visible_reward_skill_from_frame(frame_id)
            except Exception:
                continue
            skill_id = int(getattr(native_info, "skill_id", 0) or 0)
            if skill_id != DISARM_TRAP_SKILL_ID:
                continue
            source_frame_id = int(getattr(native_info, "source_frame_id", 0) or 0)
            if (
                frame_id > 0
                and frame_id != source_frame_id
                and source_frame_id > 0
                and self.is_descendant_frame(frame_id, source_frame_id)
            ):
                return frame_id
            if (
                frame_id > 0
                and frame_id != reward_root
                and source_frame_id == reward_root
                and reward_root > 0
            ):
                return frame_id
            if source_frame_id > 0 and UIManager.FrameExists(source_frame_id):
                return source_frame_id
            return frame_id
        return 0

    def get_fallback_open_reward_anchor_frame(self) -> int:
        reward_root = int(UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH) or 0)
        if reward_root > 0 and UIManager.FrameExists(reward_root):
            return reward_root

        equip_frame = int(UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH) or 0)
        if equip_frame > 0 and UIManager.FrameExists(equip_frame):
            return equip_frame

        return 0

    def get_native_open_reward_target_frame(self, slot: int) -> int:
        for frame_id in reversed(self.get_open_reward_ui_slot_frames(slot)):
            frame_id = int(frame_id or 0)
            if frame_id > 0 and UIManager.FrameExists(frame_id):
                return frame_id
        return 0

    def queue_open_reward_ui_apply(
        self,
        slot: int,
        source_frame_id: int = 0,
        retries_left: int = MAX_UI_RETRIES,
    ) -> bool:
        slot_frames = self.get_open_reward_ui_slot_frames(slot)
        equip_frame = int(UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH) or 0)
        if not slot_frames:
            self.status_message = f"Open reward UI apply aborted: slot {slot} frame is missing."
            return False
        if equip_frame <= 0 or not UIManager.FrameExists(equip_frame):
            self.status_message = "Open reward UI apply aborted: Equip button is not visible."
            return False

        try:
            SkillAccept.clear_pending_skill_frame_events()
        except Exception:
            pass
        try:
            SkillAccept.clear_pending_skill_resolution_trace()
        except Exception:
            pass
        try:
            UIManager.ClearUIMessageLogs()
        except Exception:
            pass
        self.last_trace = []
        self.last_frame_events = []
        self.last_ui_payload_debug = []

        queue = ActionQueueManager()
        queue.ResetQueue("FAST")
        effective_source_frame_id = int(source_frame_id or 0)
        reward_root = int(UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH) or 0)
        if effective_source_frame_id == reward_root:
            effective_source_frame_id = 0

        queue_steps: List[str] = []
        if effective_source_frame_id > 0 and UIManager.FrameExists(effective_source_frame_id):
            queue_steps.append(f"source_click={effective_source_frame_id}")
            queue.AddAction("FAST", UIManager.TestMouseAction, effective_source_frame_id, UI_MOUSE_CLICK_STATE, 0, 0)
            queue.AddAction("FAST", UIManager.TestMouseClickAction, effective_source_frame_id, UI_MOUSE_CLICK_STATE, 0, 0)
            queue.AddAction("FAST", UIManager.FrameClick, effective_source_frame_id)
            queue.AddActionWithDelay("FAST", SOURCE_CLICK_SETTLE_DELAY_MS, _noop_action)
        for slot_frame in slot_frames:
            queue_steps.append(f"slot_click={slot_frame}")
            queue.AddAction("FAST", UIManager.TestMouseAction, slot_frame, UI_MOUSE_CLICK_STATE, 0, 0)
            queue.AddAction("FAST", UIManager.TestMouseClickAction, slot_frame, UI_MOUSE_CLICK_STATE, 0, 0)
            queue.AddAction("FAST", UIManager.FrameClick, slot_frame)
            queue.AddActionWithDelay("FAST", SLOT_CLICK_SETTLE_DELAY_MS, _noop_action)
        queue_steps.append(f"equip_click={equip_frame}")
        queue.AddActionWithDelay("FAST", POST_SLOT_SELECTION_DELAY_MS, _noop_action)
        queue.AddAction("FAST", UIManager.TestMouseAction, equip_frame, UI_MOUSE_CLICK_STATE, 0, 0)
        queue.AddAction("FAST", UIManager.TestMouseClickAction, equip_frame, UI_MOUSE_CLICK_STATE, 0, 0)
        queue.AddAction("FAST", UIManager.FrameClick, equip_frame)
        queue.AddAction("FAST", UIManager.TestMouseAction, equip_frame, UI_MOUSE_CLICK_STATE, 0, 0)
        self.begin_verify(
            slot,
            pre_slot_skill_id=self.current_slot_skill_id(slot),
            source_frame_id=effective_source_frame_id,
            slot_frame_ids=tuple(int(frame_id) for frame_id in slot_frames),
            retries_left=retries_left,
        )
        self.refresh_queue_debug()
        self.last_queue_debug = [
            f"slot={slot} retries_left={retries_left}",
            f"source_frame={effective_source_frame_id}",
            f"slot_frames={slot_frames}",
            f"queue_steps={queue_steps}",
            f"queue_plan={self.last_queue_plan[:10]}",
            f"queue_history={self.last_queue_history[-10:]}",
        ]
        self.refresh_ui_debug(slot, effective_source_frame_id, slot_frames)
        self.status_message = (
            f"Queued source-first open Equip Skill UI apply for slot {slot} "
            f"via source frame {effective_source_frame_id} and frames {slot_frames}."
        )
        return True

    def refresh_retry_debug(self, slot: int, current_slot_frames: List[int], retries_left: int) -> None:
        reward_root = int(UIManager.GetFrameIDByHash(REWARD_WINDOW_HASH) or 0)
        previous_slot_frames = [int(frame_id or 0) for frame_id in self.verify_slot_frame_ids if int(frame_id or 0) > 0]
        current_slot_frames = [int(frame_id or 0) for frame_id in current_slot_frames if int(frame_id or 0) > 0]
        added_slot_frames = [frame_id for frame_id in current_slot_frames if frame_id not in previous_slot_frames]
        removed_slot_frames = [frame_id for frame_id in previous_slot_frames if frame_id not in current_slot_frames]
        lines = [
            f"slot={slot} retries_left={retries_left}",
            f"source_frame={self.verify_source_frame_id}",
            f"previous_slot_frames={previous_slot_frames}",
            f"current_slot_frames={current_slot_frames}",
            f"added_slot_frames={added_slot_frames}",
            f"removed_slot_frames={removed_slot_frames}",
            f"stale_candidate_list={previous_slot_frames != current_slot_frames}",
            f"reward_root={reward_root} exists={bool(reward_root and UIManager.FrameExists(reward_root))}",
        ]
        for frame_id in current_slot_frames[:6]:
            try:
                parent = int(UIManager.GetParentFrameID(frame_id) or 0)
            except Exception:
                parent = 0
            depth = self.get_ancestry_depth(frame_id, reward_root) if reward_root > 0 else None
            lines.append(
                f"frame {frame_id}: parent={parent} depth={depth} "
                f"in_reward={self.is_descendant_frame(frame_id, reward_root) if reward_root > 0 else False}"
            )
        self.last_retry_debug = lines
        self.refresh_ui_debug(slot, self.verify_source_frame_id, current_slot_frames)

    def refresh_trace(self) -> None:
        try:
            self.last_trace = list(SkillAccept.get_pending_skill_resolution_trace())
        except Exception:
            self.last_trace = []
        try:
            self.last_frame_events = list(SkillAccept.get_pending_skill_frame_events())
        except Exception:
            self.last_frame_events = []
        self.refresh_ui_payload_debug()
        self.refresh_queue_debug()

    def describe_last_trace(self) -> str:
        if not self.last_trace:
            return "No native trace captured."
        entry = self.last_trace[-1]
        return (
            f"{getattr(entry, 'stage', '')}/{getattr(entry, 'reason', '')} "
            f"owner={getattr(entry, 'owner_id', 0)} "
            f"skill={getattr(entry, 'skill_id', 0)} "
            f"slot={getattr(entry, 'slot_index', 0)}"
        )

    def has_pending_disarm_trap(self, agent_id: int) -> bool:
        try:
            pending = SkillAccept.get_pending_skills(agent_id)
        except Exception:
            return False
        return any(int(item.skill_id) == DISARM_TRAP_SKILL_ID for item in pending)

    def queue_flow(self) -> None:
        self.pending_flow_request = True
        self.status_message = "Queued exact Rojis flow."

    def begin_verify(
        self,
        slot: int,
        pre_slot_skill_id: int | None = None,
        source_frame_id: int = 0,
        slot_frame_ids: tuple[int, ...] = (),
        retries_left: int = 0,
    ) -> None:
        self.verifying_apply = True
        self.verify_slot = slot
        self.verify_pre_slot_skill_id = int(self.current_slot_skill_id(slot) if pre_slot_skill_id is None else pre_slot_skill_id)
        self.verify_source_frame_id = int(source_frame_id or 0)
        self.verify_slot_frame_ids = tuple(int(frame_id) for frame_id in slot_frame_ids)
        self.verify_retries_left = max(0, int(retries_left))
        self.verify_timer.Reset()

    def execute_flow(self) -> None:
        self.pending_flow_request = False
        if Map.IsMapLoading():
            self.status_message = "Map is loading; try again once Guild Wars is stable."
            return
        if not Map.IsMapReady():
            self.status_message = "Map is not ready yet."
            return

        slot = self.selected_slot
        slot_skill_id = self.current_slot_skill_id(slot)
        if slot_skill_id == DISARM_TRAP_SKILL_ID:
            self.status_message = f"Slot {slot} already contains {self.resolve_skill_name(DISARM_TRAP_SKILL_ID)}."
            return

        agent_id = self.get_player_agent_id()
        if agent_id <= 0:
            self.status_message = "Controlled player agent id is unavailable."
            return

        queued = False
        self.last_trace = []
        if self.reward_window_is_visible():
            anchor_frame = self.resolve_open_reward_anchor_frame(slot)
            if anchor_frame <= 0:
                anchor_frame = self.get_fallback_open_reward_anchor_frame()
            if anchor_frame <= 0:
                self.status_message = "Open reward exact apply failed: reward window anchor unavailable."
                return
            if self.queue_open_reward_ui_apply(slot, anchor_frame, MAX_UI_RETRIES):
                self.status_message = (
                    f"Queued exact source-first open-window Disarm Trap flow for slot {slot}."
                )
                return
            self.status_message = "Open reward exact apply failed: UI queue unavailable."
            return

        if self.has_pending_disarm_trap(agent_id):
            try:
                queued = bool(
                    SkillAccept.apply_pending_skill_replace(
                        DISARM_TRAP_SKILL_ID,
                        slot - 1,
                        None,
                        agent_id,
                    )
                )
            except Exception as exc:
                self.status_message = f"Pending apply raised before queue: {exc}"
                return
            self.refresh_trace()
            if not queued:
                self.status_message = f"Pending apply failed: {self.describe_last_trace()}"
                return
            self.status_message = f"Queued pending Disarm Trap apply for slot {slot}."
            self.begin_verify(slot)
            return

        try:
            queued = bool(
                SkillAccept.accept_offered_skill_and_apply_pending(
                    DISARM_TRAP_SKILL_ID,
                    slot - 1,
                    agent_id,
                    FLOW_TIMEOUT_MS,
                )
            )
        except Exception as exc:
            self.status_message = f"Rojis accept/apply raised before queue: {exc}"
            return

        self.refresh_trace()
        if not queued:
            self.status_message = f"Rojis accept/apply failed: {self.describe_last_trace()}"
            return

        self.status_message = f"Queued exact Rojis -> Disarm Trap flow for slot {slot}."
        self.begin_verify(slot)

    def update(self) -> None:
        ActionQueueManager().ProcessQueue("FAST")
        if self.pending_flow_request:
            self.execute_flow()

        if not self.verifying_apply or not self.verify_timer.HasElapsed(VERIFY_DELAY_MS):
            return

        slot_skill_id = self.current_slot_skill_id(self.verify_slot)
        if slot_skill_id == DISARM_TRAP_SKILL_ID:
            self.status_message = f"Applied {self.resolve_skill_name(DISARM_TRAP_SKILL_ID)} to slot {self.verify_slot}."
            self.verifying_apply = False
            self.verify_slot = 0
            self.verify_retries_left = 0
            return

        if (
            self.reward_window_is_visible()
            and slot_skill_id == self.verify_pre_slot_skill_id
            and self.verify_retries_left > 0
        ):
            current_slot_frames = self.get_open_reward_ui_slot_frames(self.verify_slot)
            next_retries = self.verify_retries_left - 1
            self.refresh_retry_debug(self.verify_slot, current_slot_frames, next_retries)
            if self.queue_open_reward_ui_apply(self.verify_slot, self.verify_source_frame_id, next_retries):
                self.status_message = (
                    f"Retrying source-first open-window apply for slot {self.verify_slot}. "
                    f"Source frame {self.verify_source_frame_id}, slot frames {list(self.verify_slot_frame_ids) if self.verify_slot_frame_ids else 'none'}."
                )
                return

        self.refresh_trace()
        self.status_message = (
            f"Queued flow did not verify for slot {self.verify_slot}. "
            f"Source frame {self.verify_source_frame_id}, slot frames "
            f"{list(self.verify_slot_frame_ids) if self.verify_slot_frame_ids else 'none'}. "
            f"{self.describe_last_trace()}"
        )
        self.verifying_apply = False
        self.verify_slot = 0
        self.verify_retries_left = 0

    def draw_trace(self) -> None:
        if not PyImGui.collapsing_header("Diagnostics"):
            return

        if not self.last_trace:
            PyImGui.text("No native trace entries captured yet.")

        for entry in self.last_trace[-TRACE_PREVIEW_COUNT:]:
            PyImGui.text_wrapped(
                f"{'OK' if getattr(entry, 'accepted', False) else 'NO'} "
                f"{getattr(entry, 'stage', '')}/{getattr(entry, 'reason', '')} "
                f"owner={getattr(entry, 'owner_id', 0)} "
                f"skill={getattr(entry, 'skill_id', 0)} "
                f"slot={getattr(entry, 'slot_index', 0)}"
            )
        if self.last_frame_events:
            PyImGui.separator()
            PyImGui.text("Pending skill frame events:")
            for event in self.last_frame_events[-TRACE_PREVIEW_COUNT:]:
                PyImGui.text_wrapped(
                    f"{'OK' if getattr(event, 'accepted', False) else 'NO'} "
                    f"src={getattr(event, 'source', 0)} "
                    f"msg=0x{int(getattr(event, 'message_id', 0)):08X} "
                    f"frame={getattr(event, 'frame_id', 0)} "
                    f"parent={getattr(event, 'parent_frame_id', 0)} "
                    f"child={getattr(event, 'child_offset_id', 0)} "
                    f"cb[{getattr(event, 'callback_index', 0)}]=0x{int(getattr(event, 'callback_ptr', 0)):08X} "
                    f"ctx=0x{int(getattr(event, 'callback_context_ptr', 0)):08X} "
                    f"state=0x{int(getattr(event, 'state_ptr', 0)):08X} "
                    f"slot={getattr(event, 'slot_index', 0)} "
                    f"skill={getattr(event, 'skill_id', 0)} "
                    f"reason={getattr(event, 'reason', '')}"
                )
        if self.last_ui_debug:
            PyImGui.separator()
            PyImGui.text("UI frame debug:")
            for line in self.last_ui_debug[-10:]:
                PyImGui.text_wrapped(line)
        if self.last_visible_candidate_debug:
            PyImGui.separator()
            PyImGui.text("Visible reward resolver:")
            for line in self.last_visible_candidate_debug[-15:]:
                PyImGui.text_wrapped(line)
        if self.last_ui_payload_debug:
            PyImGui.separator()
            PyImGui.text("Filtered UI payloads:")
            for line in self.last_ui_payload_debug[-TRACE_PREVIEW_COUNT:]:
                PyImGui.text_wrapped(line)
        if self.last_queue_plan:
            PyImGui.separator()
            PyImGui.text("FAST queue plan:")
            for line in self.last_queue_plan[:10]:
                PyImGui.text_wrapped(line)
        if self.last_queue_history:
            PyImGui.separator()
            PyImGui.text("FAST queue history:")
            for line in self.last_queue_history[-10:]:
                PyImGui.text_wrapped(line)

    def draw(self) -> None:
        if PyImGui.begin(MODULE_NAME):
            PyImGui.text_wrapped(
                "Exact helper for Venta Cemetery -> Rojis -> Disarm Trap. "
                "It uses an exact native open-window reward path when the Equip Skill window is visible, "
                "otherwise it falls back to the known offer-then-pending path."
            )
            PyImGui.separator()
            PyImGui.text(f"Mission: {MISSION_NAME}")
            PyImGui.text(f"NPC: {NPC_NAME}")
            PyImGui.text(f"Reward: {self.resolve_skill_name(DISARM_TRAP_SKILL_ID)} [{DISARM_TRAP_SKILL_ID}]")

            slots = [str(index) for index in range(1, 9)]
            self.selected_slot = PyImGui.combo("Target Slot", self.selected_slot - 1, slots) + 1

            current_skill_id = self.current_slot_skill_id(self.selected_slot)
            PyImGui.text(
                f"Current slot {self.selected_slot}: {self.resolve_skill_name(current_skill_id)} [{current_skill_id}]"
            )
            if PyImGui.button("Take Disarm Trap"):
                self.queue_flow()

            PyImGui.separator()
            PyImGui.text_wrapped(self.status_message)
            self.draw_trace()
        PyImGui.end()


def tooltip() -> None:
    PyImGui.begin_tooltip()
    title_color = Color(255, 200, 100, 255)
    ImGui.push_font("Regular", 20)
    PyImGui.text_colored(MODULE_NAME, title_color.to_tuple_normalized())
    ImGui.pop_font()
    PyImGui.separator()
    PyImGui.text("Exact helper for the Venta Cemetery mission reward from Rojis.")
    PyImGui.text("Uses the exact native open-window reward flow when visible, then falls back to pending apply.")
    PyImGui.end_tooltip()


_widget = RojisDisarmTrapWidget()


def main() -> None:
    _widget.update()
    _widget.draw()


if __name__ == "__main__":
    main()
