from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import Py4GW
import Py4GWCoreLib.Dialog as Dialog
import Py4GWCoreLib.SkillAccept as SkillAccept
from Py4GWCoreLib import (
    ActionQueueManager,
    Color,
    Console,
    ConsoleLog,
    ImGui,
    Map,
    Party,
    Player,
    PyImGui,
    Skill,
    SkillBar,
    Timer,
    UIManager,
)

MODULE_NAME = "Mission Skill Reward"
MODULE_ICON = "Textures/Module_Icons/Skill Learner.png"

SKILL_SLOT_HASHES = {
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
UI_RETRY_DELAY_MS = 180
UI_SETTLE_DELAY_MS = 700
MAX_UI_RETRIES = 3


@dataclass
class PendingSkillRow:
    skill_id: int
    copy_id: int
    ref_count: int
    name: str


@dataclass
class RequestedApply:
    skill_id: int
    slot: int
    mode: str
    retries_left: int


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
        self.last_auto_signature: Optional[tuple[int, int]] = None
        self.last_auto_attempt_signature: Optional[tuple[int, int]] = None

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
        self.last_auto_signature = None
        self.last_auto_attempt_signature = None
        self.status_message = reason

    def is_runtime_ready(self) -> bool:
        if Map.IsMapLoading():
            self.reset_runtime_state("Waiting for map load to finish.")
            return False
        if not Map.IsMapReady():
            self.reset_runtime_state("Waiting for map readiness.")
            return False
        if not Party.IsPartyLoaded():
            self.reset_runtime_state("Waiting for party data.")
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
            pending = Dialog.get_pending_skills(agent_id)
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
        rows.sort(key=lambda item: (item.skill_id, item.copy_id))
        self.pending_rows = rows
        if rows:
            self.selected_pending_index = min(self.selected_pending_index, len(rows) - 1)
        else:
            self.selected_pending_index = 0

    def reward_window_is_visible(self) -> bool:
        equip_frame = UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH)
        return bool(equip_frame and UIManager.FrameExists(equip_frame))

    def get_slot_frame_id(self, slot: int) -> int:
        return UIManager.GetFrameIDByHash(SKILL_SLOT_HASHES[slot])

    def get_selected_row(self) -> Optional[PendingSkillRow]:
        if not self.pending_rows:
            return None
        index = min(max(self.selected_pending_index, 0), len(self.pending_rows) - 1)
        return self.pending_rows[index]

    def queue_ui_fallback(self, skill_id: int, slot: int) -> bool:
        slot_frame = self.get_slot_frame_id(slot)
        equip_frame = UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH)
        if not slot_frame or not UIManager.FrameExists(slot_frame):
            self.status_message = f"UI fallback aborted: slot {slot} frame is missing."
            return False
        if not equip_frame or not UIManager.FrameExists(equip_frame):
            self.status_message = "UI fallback aborted: Equip button is not visible."
            return False

        queue = ActionQueueManager()
        queue.AddAction("FAST", UIManager.TestMouseClickAction, slot_frame, 0, 0)
        queue.AddActionWithDelay("FAST", UI_RETRY_DELAY_MS, UIManager.FrameClick, equip_frame)
        self.active_request = RequestedApply(
            skill_id=skill_id,
            slot=slot,
            mode="ui",
            retries_left=MAX_UI_RETRIES - 1,
        )
        self.apply_timer.Reset()
        self.status_message = f"UI fallback queued for {self.resolve_skill_name(skill_id)} in slot {slot}."
        return True

    def try_native_apply(self, skill_id: int, slot: int, copy_id: Optional[int]) -> bool:
        agent_id = self.get_player_agent_id()
        try:
            applied = bool(Dialog.apply_pending_skill_replace(skill_id, slot - 1, copy_id, agent_id))
        except Exception as exc:
            self.status_message = f"Native apply failed: {exc}"
            return False

        if not applied:
            return False

        self.active_request = RequestedApply(
            skill_id=skill_id,
            slot=slot,
            mode="native",
            retries_left=0,
        )
        self.apply_timer.Reset()
        self.status_message = f"Native apply queued for {self.resolve_skill_name(skill_id)} in slot {slot}."
        return True

    def request_apply(self, row: PendingSkillRow, source: str) -> None:
        current_slot_skill_id = int(SkillBar.GetSkillIDBySlot(self.selected_slot) or 0)
        if current_slot_skill_id == row.skill_id:
            self.status_message = f"Slot {self.selected_slot} already contains {row.name}."
            return

        if self.try_native_apply(row.skill_id, self.selected_slot, row.copy_id):
            ConsoleLog(MODULE_NAME, f"Queued native apply for skill_id={row.skill_id} slot={self.selected_slot} source={source}", Console.MessageType.Info)
            return

        if self.queue_ui_fallback(row.skill_id, self.selected_slot):
            ConsoleLog(MODULE_NAME, f"Queued UI fallback for skill_id={row.skill_id} slot={self.selected_slot} source={source}", Console.MessageType.Info)

    def request_manual_apply(self) -> None:
        skill_id = int(self.manual_skill_id or 0)
        if skill_id <= 0:
            self.status_message = "Enter a valid manual skill ID."
            return

        row = PendingSkillRow(
            skill_id=skill_id,
            copy_id=0,
            ref_count=0,
            name=self.resolve_skill_name(skill_id),
        )
        self.request_apply(row, "manual")

    def has_pending_skill(self, skill_id: int) -> bool:
        return any(row.skill_id == skill_id for row in self.pending_rows)

    def update_active_request(self) -> None:
        request = self.active_request
        if request is None:
            return
        if not self.apply_timer.HasElapsed(UI_SETTLE_DELAY_MS):
            return

        slot_skill_id = int(SkillBar.GetSkillIDBySlot(request.slot) or 0)
        if slot_skill_id == request.skill_id:
            self.status_message = f"Applied {self.resolve_skill_name(request.skill_id)} to slot {request.slot} via {request.mode}."
            self.last_auto_signature = (request.skill_id, request.slot)
            self.active_request = None
            return

        pending_still_present = self.has_pending_skill(request.skill_id)
        if request.mode == "ui" and pending_still_present and self.reward_window_is_visible() and request.retries_left > 0:
            if self.queue_ui_fallback(request.skill_id, request.slot):
                self.active_request.retries_left = request.retries_left - 1
            else:
                self.active_request = None
            return

        if not pending_still_present and not self.reward_window_is_visible():
            self.status_message = f"Reward window closed for skill {request.skill_id}, but slot {request.slot} could not be verified."
        else:
            self.status_message = f"Apply did not verify for {self.resolve_skill_name(request.skill_id)} in slot {request.slot}."
        self.active_request = None

    def maybe_auto_apply(self) -> None:
        if not self.auto_apply_single_pending or self.active_request is not None:
            return
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
        self.request_apply(row, "auto")

    def update(self) -> None:
        if not self.is_runtime_ready():
            return
        ActionQueueManager().ProcessQueue("FAST")
        if self.pending_refresh_timer.HasElapsed(200):
            self.refresh_pending_rows()
            self.pending_refresh_timer.Reset()
        self.update_active_request()
        self.maybe_auto_apply()

    def draw_pending_rows(self) -> None:
        if not self.pending_rows:
            PyImGui.text("No pending mission reward skill detected.")
            return

        labels = [
            f"{row.name} [id={row.skill_id}, copy={row.copy_id}, refs={row.ref_count}]"
            for row in self.pending_rows
        ]
        self.selected_pending_index = PyImGui.combo("Pending Skill", self.selected_pending_index, labels)
        row = self.get_selected_row()
        if row is None:
            return

        PyImGui.text(f"Selected: {row.name}")
        PyImGui.text(f"Skill ID: {row.skill_id}")
        PyImGui.text(f"Copy ID: {row.copy_id}")
        PyImGui.text(f"Current slot {self.selected_slot}: {self.resolve_skill_name(int(SkillBar.GetSkillIDBySlot(self.selected_slot) or 0))}")
        if PyImGui.button("Apply Pending Reward"):
            self.request_apply(row, "manual-pending")

    def draw_debug(self) -> None:
        if not PyImGui.collapsing_header("Diagnostics"):
            return

        PyImGui.text(f"Native ready: {self.native_ready}")
        if self.native_error:
            PyImGui.text_wrapped(f"Native error: {self.native_error}")
        PyImGui.text(f"Reward window visible: {self.reward_window_is_visible()}")
        slot_frame = self.get_slot_frame_id(self.selected_slot)
        PyImGui.text(f"Selected slot frame: {slot_frame}")
        equip_frame = UIManager.GetFrameIDByHash(EQUIP_BUTTON_HASH)
        PyImGui.text(f"Equip button frame: {equip_frame}")

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
    PyImGui.text("Native pending-skill apply is preferred.")
    PyImGui.text("UI click fallback uses one slot click plus Equip.")
    PyImGui.end_tooltip()


_widget = MissionSkillRewardWidget()


def main() -> None:
    _widget.update()
    _widget.draw()


if __name__ == "__main__":
    main()
