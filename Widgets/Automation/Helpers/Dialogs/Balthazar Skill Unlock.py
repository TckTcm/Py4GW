from __future__ import annotations

import time
from typing import List, Optional

from Py4GWCoreLib import Color, Dialog, ImGui, Map, Party, PyImGui, Skill
from Py4GWCoreLib.BalthazarSkillUnlock import (
    BALTHAZAR_UNLOCK_DIALOG_MASK,
    DEFAULT_SEARCH_RESULT_LIMIT,
    GREAT_TEMPLE_OF_BALTHAZAR_MAP_ID,
    PRIEST_OF_BALTHAZAR_MODEL_ID,
    BalthazarSkillUnlockAttempt,
    SkillOption,
    get_balthazar_skill_unlock_helper,
)

MODULE_NAME = "Balthazar Skill Unlock"
MODULE_ICON = "Textures/Module_Icons/Skill Learner.png"

SEARCH_RESULT_LIMIT = DEFAULT_SEARCH_RESULT_LIMIT
SEND_THROTTLE_SECONDS = 0.4
VERIFY_DELAY_SECONDS = 1.2
VERIFY_TIMEOUT_SECONDS = 5.0


class BalthazarSkillUnlockWidget:
    def __init__(self) -> None:
        self.api = get_balthazar_skill_unlock_helper()
        self.search_text = ""
        self.manual_skill_id = 0
        self.selected_skill_id = 0
        self.selected_match_index = 0
        self.status_message = "Ready."
        self.use_pvp_remap = True
        self.allow_without_priest_target = False
        self.allow_already_unlocked = False
        self.matches: List[SkillOption] = []
        self.pending_unlock: Optional[BalthazarSkillUnlockAttempt] = None
        self.last_send_time = 0.0
        self.last_search_signature = ""

    def _refresh_matches(self) -> None:
        signature = self.search_text
        if signature == self.last_search_signature:
            return
        self.last_search_signature = signature
        self.matches = self.api.search_skills(self.search_text, limit=SEARCH_RESULT_LIMIT)
        if self.matches:
            self.selected_match_index = min(max(self.selected_match_index, 0), len(self.matches) - 1)
        else:
            self.selected_match_index = 0

    def _skill_name(self, skill_id: int) -> str:
        return self.api.get_skill_name(skill_id)

    def _current_balthazar_points(self) -> int:
        return self.api.get_current_balthazar_points()

    def _skill_is_unlocked(self, skill_id: int) -> bool:
        return self.api.is_skill_unlocked(skill_id)

    def _normalize_send_skill_id(self, skill_id: int) -> int:
        return self.api.normalize_send_skill_id(skill_id, use_pvp_remap=self.use_pvp_remap)

    def _estimated_unlock_cost(self, skill_id: int) -> int:
        return self.api.estimated_unlock_cost(skill_id)

    def _target_summary(self) -> tuple[int, str, int]:
        target = self.api.get_target_summary()
        return target.target_id, target.target_name, target.model_id

    def _select_match(self, option: SkillOption) -> None:
        self.selected_skill_id = int(option.skill_id)
        self.manual_skill_id = int(option.skill_id)
        self.status_message = f"Selected {option.name} [{option.skill_id}]."

    def _send_unlock_request(self) -> None:
        selected_skill_id = int(self.selected_skill_id or 0)
        if selected_skill_id <= 0:
            self.status_message = "Select a skill from search results or enter a manual skill ID."
            return

        now = time.monotonic()
        if (now - self.last_send_time) < SEND_THROTTLE_SECONDS:
            self.status_message = "Send throttled. Wait a moment before sending another unlock request."
            return

        result = self.api.queue_unlock_skill(
            selected_skill_id,
            use_pvp_remap=self.use_pvp_remap,
            require_priest_target=not self.allow_without_priest_target,
            allow_already_unlocked=self.allow_already_unlocked,
        )
        self.status_message = result.message
        if result.ok and result.attempt is not None:
            self.last_send_time = now
            self.pending_unlock = result.attempt

    def _update_pending_unlock(self) -> None:
        pending = self.pending_unlock
        if pending is None:
            return

        verification = self.api.verify_unlock_attempt(
            pending,
            verify_delay_seconds=VERIFY_DELAY_SECONDS,
            verify_timeout_seconds=VERIFY_TIMEOUT_SECONDS,
        )
        if verification.complete:
            self.status_message = verification.message
            self.pending_unlock = None

    def update(self) -> None:
        self._refresh_matches()
        self._update_pending_unlock()

    def _draw_status_panel(self) -> None:
        current_map_id = int(Map.GetMapID() or 0)
        current_map_name = str(Map.GetMapName(current_map_id) or "Unknown")
        current_balth = self._current_balthazar_points()
        target_id, target_name, model_id = self._target_summary()
        priest_ok = model_id == PRIEST_OF_BALTHAZAR_MODEL_ID
        map_ok = current_map_id == GREAT_TEMPLE_OF_BALTHAZAR_MAP_ID

        PyImGui.text(f"Map: {current_map_name} ({current_map_id})")
        PyImGui.text_colored(
            f"Target: {target_name} [{target_id}] | model {model_id}",
            (0.6, 1.0, 0.6, 1.0) if priest_ok else (1.0, 0.8, 0.4, 1.0),
        )
        PyImGui.text(f"Current Balthazar faction: {current_balth}")
        if not map_ok:
            PyImGui.text_colored(
                f"Warning: expected map {GREAT_TEMPLE_OF_BALTHAZAR_MAP_ID} for Great Temple of Balthazar.",
                (1.0, 0.8, 0.4, 1.0),
            )
        if PyImGui.button("Travel to GToB"):
            Map.Travel(GREAT_TEMPLE_OF_BALTHAZAR_MAP_ID)

    def _draw_search_panel(self) -> None:
        new_search = str(PyImGui.input_text("Search Skill", self.search_text, 128))
        if new_search != self.search_text:
            self.search_text = new_search
            self.last_search_signature = ""

        self.manual_skill_id = int(PyImGui.input_int("Manual Skill ID", int(self.manual_skill_id or 0)))
        if PyImGui.button("Use Manual ID"):
            self.selected_skill_id = int(self.manual_skill_id or 0)
            self.status_message = f"Selected manual skill ID {self.selected_skill_id}."
        PyImGui.same_line(0.0, -1.0)
        if PyImGui.button("Clear Selection"):
            self.selected_skill_id = 0
            self.manual_skill_id = 0
            self.status_message = "Cleared selected skill."

        PyImGui.separator()
        if not self.matches:
            PyImGui.text("Type at least 2 characters to search, or enter a skill ID.")
            return

        if PyImGui.begin_child("BalthazarSkillMatches", (0, 220), True, PyImGui.WindowFlags.NoFlag):
            for index, option in enumerate(self.matches):
                label = f"{option.name} [{option.skill_id}]"
                is_selected = int(option.skill_id) == int(self.selected_skill_id or 0)
                if PyImGui.selectable(f"{label}##balth_skill_{index}", is_selected, PyImGui.SelectableFlags.NoFlag, (0, 0)):
                    self._select_match(option)
            PyImGui.end_child()

    def _draw_selected_skill_panel(self) -> None:
        selected_skill_id = int(self.selected_skill_id or 0)
        if selected_skill_id <= 0:
            PyImGui.text("No skill selected.")
            return

        selected_name = self._skill_name(selected_skill_id)
        send_skill_id = self._normalize_send_skill_id(selected_skill_id)
        raw_dialog_id = BALTHAZAR_UNLOCK_DIALOG_MASK | (send_skill_id & 0xFFFF)
        requested_unlocked = self._skill_is_unlocked(selected_skill_id)
        send_unlocked = self._skill_is_unlocked(send_skill_id)
        estimated_cost = self._estimated_unlock_cost(selected_skill_id)

        try:
            _, profession_name = Skill.GetProfession(selected_skill_id)
        except Exception:
            profession_name = "Unknown"
        try:
            _, campaign_name = Skill.GetCampaign(selected_skill_id)
        except Exception:
            campaign_name = "Unknown"
        try:
            _, type_name = Skill.GetType(selected_skill_id)
        except Exception:
            type_name = "Unknown"
        try:
            concise = str(Skill.GetConciseDescription(selected_skill_id) or "")
        except Exception:
            concise = ""

        try:
            is_pvp = bool(Skill.Flags.IsPvP(selected_skill_id))
        except Exception:
            is_pvp = False
        try:
            is_playable = bool(Skill.Flags.IsPlayable(selected_skill_id))
        except Exception:
            is_playable = False
        try:
            is_elite = bool(Skill.Flags.IsElite(selected_skill_id))
        except Exception:
            is_elite = False

        PyImGui.text(f"Selected: {selected_name}")
        PyImGui.text(f"Skill ID: {selected_skill_id}")
        PyImGui.text(f"Profession: {profession_name} | Campaign: {campaign_name} | Type: {type_name}")
        PyImGui.text(f"Playable: {is_playable} | PvP skill: {is_pvp} | Elite: {is_elite}")
        PyImGui.text(f"Estimated unlock cost: {estimated_cost if estimated_cost > 0 else 'Unknown'}")
        PyImGui.text(f"Send skill ID: {send_skill_id} | Raw dialog: 0x{raw_dialog_id:08X}")
        PyImGui.text(f"Unlocked bitmask: requested={requested_unlocked} | send-id={send_unlocked}")
        if concise:
            PyImGui.separator()
            PyImGui.text_wrapped(concise)
            PyImGui.separator()

        self.use_pvp_remap = bool(
            PyImGui.checkbox("Use PvP remap when Skill.ExtraData.GetIDPvP(...) differs", self.use_pvp_remap)
        )
        self.allow_without_priest_target = bool(
            PyImGui.checkbox("Allow send without Priest of Balthazar target", self.allow_without_priest_target)
        )
        self.allow_already_unlocked = bool(
            PyImGui.checkbox("Allow send even if the skill already looks unlocked", self.allow_already_unlocked)
        )

        if PyImGui.button("Unlock Selected Skill"):
            self._send_unlock_request()

    def _draw_diagnostics(self) -> None:
        if not PyImGui.collapsing_header("Diagnostics"):
            return

        if self.api.catalog_error:
            PyImGui.text_wrapped(f"Catalog error: {self.api.catalog_error}")

        pending = self.pending_unlock
        if pending is None:
            PyImGui.text("Pending unlock: none")
        else:
            elapsed = time.monotonic() - pending.sent_at
            PyImGui.text(
                f"Pending unlock: {pending.requested_skill_name} "
                f"| raw=0x{pending.raw_dialog_id:08X} | elapsed={elapsed:.2f}s"
            )

        try:
            sent_entries = Dialog.get_dialog_callback_journal_sent()[-5:]
        except Exception:
            sent_entries = []

        if sent_entries:
            PyImGui.separator()
            PyImGui.text("Recent sent dialog journal entries:")
            for entry in reversed(sent_entries):
                event_type = str(getattr(entry, "event_type", "") or "?")
                dialog_id = int(getattr(entry, "dialog_id", 0) or 0)
                agent_id = int(getattr(entry, "agent_id", 0) or 0)
                PyImGui.text(f"{event_type} | dialog=0x{dialog_id:08X} | agent={agent_id}")

    def draw(self) -> None:
        if PyImGui.begin(MODULE_NAME):
            PyImGui.text_wrapped(
                "Thin UI over the reusable Py4GWCoreLib.BalthazarSkillUnlock helper. "
                "Select a skill, confirm the current target, and queue the Balthazar unlock dialog family."
            )
            PyImGui.separator()

            if not Map.IsMapReady() or not Party.IsPartyLoaded():
                PyImGui.text("Waiting for map and party readiness.")
            else:
                self._draw_status_panel()
                PyImGui.separator()
                self._draw_search_panel()
                PyImGui.separator()
                self._draw_selected_skill_panel()

            PyImGui.separator()
            PyImGui.text_wrapped(self.status_message)
            self._draw_diagnostics()
        PyImGui.end()


def tooltip() -> None:
    PyImGui.begin_tooltip()
    title_color = Color(255, 200, 100, 255)
    ImGui.push_font("Regular", 20)
    PyImGui.text_colored(MODULE_NAME, title_color.to_tuple_normalized())
    ImGui.pop_font()
    PyImGui.separator()
    PyImGui.text("Search or enter a skill ID, then send the Balthazar unlock dialog.")
    PyImGui.text("The helper verifies result by watching unlocked-skill bits and Balthazar faction.")
    PyImGui.text("Reusable API: Py4GWCoreLib.BalthazarSkillUnlock.queue_unlock_skill(...).")
    PyImGui.end_tooltip()


_widget = BalthazarSkillUnlockWidget()


def main() -> None:
    _widget.update()
    _widget.draw()


if __name__ == "__main__":
    main()
