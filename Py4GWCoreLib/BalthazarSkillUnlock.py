"""
Reusable helper for the Priest of Balthazar skill-unlock vendor flow.
This module provides search, normalization, send, and verification helpers.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import List, Optional

import Py4GW

from .Agent import Agent
from .Player import Player
from .Py4GWcorelib import Console, ConsoleLog
from .Skill import Skill

MODULE_NAME = "Balthazar Skill Unlock"

GREAT_TEMPLE_OF_BALTHAZAR_MAP_ID = 248
PRIEST_OF_BALTHAZAR_MODEL_ID = 218
BALTHAZAR_UNLOCK_DIALOG_MASK = 0x10000000
PVP_REMAP_SENTINEL = 0x0D6C
DEFAULT_SEARCH_RESULT_LIMIT = 80


@dataclass(frozen=True)
class SkillOption:
    skill_id: int
    name: str


@dataclass(frozen=True)
class BalthazarTargetSummary:
    target_id: int
    target_name: str
    model_id: int


@dataclass
class BalthazarSkillUnlockAttempt:
    requested_skill_id: int
    requested_skill_name: str
    send_skill_id: int
    raw_dialog_id: int
    target_id: int
    target_name: str
    target_model_id: int
    estimated_unlock_cost: int
    balthazar_points_before: int
    unlocked_requested_before: bool
    unlocked_send_before: bool
    sent_at: float = 0.0


@dataclass(frozen=True)
class BalthazarSkillUnlockResult:
    ok: bool
    message: str
    attempt: Optional[BalthazarSkillUnlockAttempt] = None


@dataclass(frozen=True)
class BalthazarSkillUnlockVerification:
    complete: bool
    success: bool
    message: str
    elapsed_seconds: float
    balthazar_points_now: int
    unlocked_requested_now: bool
    unlocked_send_now: bool


class BalthazarSkillUnlockHelper:
    """High-level helper for Balthazar skill unlock search and send flow."""

    def __init__(self) -> None:
        self.catalog_error = ""
        self._skill_catalog: List[SkillOption] = []
        self._skill_catalog_by_id: dict[int, SkillOption] = {}
        self.refresh_skill_catalog()

    def _candidate_skill_json_paths(self) -> List[str]:
        project_root = str(Py4GW.Console.get_projects_path() or "")
        candidates = []
        if project_root:
            candidates.append(os.path.join(project_root, "Py4GWCoreLib", "skill_descriptions.json"))
        candidates.append(
            os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__),
                    "skill_descriptions.json",
                )
            )
        )
        return candidates

    @staticmethod
    def _parse_search_as_skill_id(query: str) -> int:
        value = str(query or "").strip()
        if not value:
            return 0
        try:
            return int(value, 0)
        except Exception:
            return 0

    def _load_skill_catalog(self) -> List[SkillOption]:
        self.catalog_error = ""
        for path in self._candidate_skill_json_paths():
            if not os.path.exists(path):
                continue
            try:
                with open(path, encoding="utf-8") as handle:
                    raw = json.load(handle)
            except Exception as exc:
                self.catalog_error = f"Failed to read skill catalog: {exc}"
                return []

            catalog: List[SkillOption] = []
            for key, payload in raw.items():
                try:
                    skill_id = int(key)
                except Exception:
                    continue
                if skill_id <= 0 or not isinstance(payload, dict):
                    continue
                name = str(payload.get("name", "") or "").strip()
                if not name:
                    continue
                catalog.append(SkillOption(skill_id=skill_id, name=name))

            catalog.sort(key=lambda item: (item.name.lower(), item.skill_id))
            return catalog

        self.catalog_error = "Could not locate Py4GWCoreLib/skill_descriptions.json."
        return []

    def refresh_skill_catalog(self) -> List[SkillOption]:
        self._skill_catalog = self._load_skill_catalog()
        self._skill_catalog_by_id = {item.skill_id: item for item in self._skill_catalog}
        return list(self._skill_catalog)

    def get_skill_catalog(self) -> List[SkillOption]:
        return list(self._skill_catalog)

    def get_skill_option(self, skill_id: int) -> Optional[SkillOption]:
        return self._skill_catalog_by_id.get(int(skill_id or 0))

    def get_skill_name(self, skill_id: int) -> str:
        resolved = int(skill_id or 0)
        if resolved <= 0:
            return "None"
        option = self.get_skill_option(resolved)
        if option is not None:
            return option.name
        try:
            return str(Skill.GetName(resolved) or f"Skill {resolved}")
        except Exception:
            return f"Skill {resolved}"

    def search_skills(self, query: str, limit: int = DEFAULT_SEARCH_RESULT_LIMIT) -> List[SkillOption]:
        query_text = str(query or "").strip()
        if not query_text:
            return []

        numeric_id = self._parse_search_as_skill_id(query_text)
        if numeric_id > 0:
            option = self.get_skill_option(numeric_id)
            if option is not None:
                return [option]
            return [SkillOption(skill_id=numeric_id, name=self.get_skill_name(numeric_id))]

        if len(query_text) < 2:
            return []

        query_lower = query_text.lower()
        exact_matches: List[SkillOption] = []
        prefix_matches: List[SkillOption] = []
        contains_matches: List[SkillOption] = []

        for item in self._skill_catalog:
            lowered = item.name.lower()
            if lowered == query_lower:
                exact_matches.append(item)
            elif lowered.startswith(query_lower):
                prefix_matches.append(item)
            elif query_lower in lowered:
                contains_matches.append(item)

        results = exact_matches + prefix_matches + contains_matches
        return results[: max(0, int(limit or 0))]

    def get_current_balthazar_points(self) -> int:
        try:
            current_balth, _, _ = Player.GetBalthazarData()
            return int(current_balth or 0)
        except Exception:
            return 0

    def is_skill_unlocked(self, skill_id: int) -> bool:
        resolved = int(skill_id or 0)
        if resolved <= 0:
            return False
        try:
            masks = Player.GetUnlockedCharacterSkills() or []
        except Exception:
            return False
        index = resolved // 32
        bit = resolved % 32
        if index < 0 or index >= len(masks):
            return False
        return bool((int(masks[index]) >> bit) & 1)

    def normalize_send_skill_id(self, skill_id: int, use_pvp_remap: bool = True) -> int:
        resolved = int(skill_id or 0)
        if resolved <= 0:
            return 0
        if not use_pvp_remap:
            return resolved
        try:
            pvp_id = int(Skill.ExtraData.GetIDPvP(resolved) or 0)
        except Exception:
            pvp_id = 0
        if pvp_id == PVP_REMAP_SENTINEL:
            return resolved
        if pvp_id > 0 and pvp_id != resolved:
            return pvp_id
        return resolved

    def estimated_unlock_cost(self, skill_id: int) -> int:
        try:
            return 3000 if bool(Skill.Flags.IsElite(skill_id)) else 1000
        except Exception:
            return 0

    def get_target_summary(self, target_id: int = 0) -> BalthazarTargetSummary:
        resolved_target_id = int(target_id or Player.GetTargetID() or 0)
        if resolved_target_id <= 0:
            return BalthazarTargetSummary(target_id=0, target_name="No current target", model_id=0)

        try:
            target_name = str(Agent.GetNameByID(resolved_target_id) or f"Target {resolved_target_id}")
        except Exception:
            target_name = f"Target {resolved_target_id}"
        try:
            model_id = int(Agent.GetModelID(resolved_target_id) or 0)
        except Exception:
            model_id = 0
        return BalthazarTargetSummary(
            target_id=resolved_target_id,
            target_name=target_name,
            model_id=model_id,
        )

    def build_unlock_attempt(
        self,
        skill_id: int,
        *,
        target_id: int = 0,
        use_pvp_remap: bool = True,
        require_priest_target: bool = True,
        allow_already_unlocked: bool = False,
    ) -> BalthazarSkillUnlockResult:
        requested_skill_id = int(skill_id or 0)
        if requested_skill_id <= 0:
            return BalthazarSkillUnlockResult(
                ok=False,
                message="Select a valid skill ID before sending an unlock request.",
            )

        target = self.get_target_summary(target_id)
        if require_priest_target and target.model_id != PRIEST_OF_BALTHAZAR_MODEL_ID:
            return BalthazarSkillUnlockResult(
                ok=False,
                message=(
                    f"Current target is {target.target_name} (model {target.model_id}), not Priest of Balthazar "
                    f"({PRIEST_OF_BALTHAZAR_MODEL_ID})."
                ),
            )

        send_skill_id = self.normalize_send_skill_id(requested_skill_id, use_pvp_remap=use_pvp_remap)
        if send_skill_id <= 0:
            return BalthazarSkillUnlockResult(
                ok=False,
                message="Could not resolve a valid Balthazar send skill ID.",
            )

        unlocked_requested = self.is_skill_unlocked(requested_skill_id)
        unlocked_send = self.is_skill_unlocked(send_skill_id)
        if (unlocked_requested or unlocked_send) and not allow_already_unlocked:
            return BalthazarSkillUnlockResult(
                ok=False,
                message="Selected skill already appears unlocked. Enable override to send anyway.",
            )

        attempt = BalthazarSkillUnlockAttempt(
            requested_skill_id=requested_skill_id,
            requested_skill_name=self.get_skill_name(requested_skill_id),
            send_skill_id=send_skill_id,
            raw_dialog_id=BALTHAZAR_UNLOCK_DIALOG_MASK | (send_skill_id & 0xFFFF),
            target_id=target.target_id,
            target_name=target.target_name,
            target_model_id=target.model_id,
            estimated_unlock_cost=self.estimated_unlock_cost(requested_skill_id),
            balthazar_points_before=self.get_current_balthazar_points(),
            unlocked_requested_before=unlocked_requested,
            unlocked_send_before=unlocked_send,
        )
        return BalthazarSkillUnlockResult(
            ok=True,
            message=(
                f"Prepared Balthazar unlock for {attempt.requested_skill_name} "
                f"using raw dialog 0x{attempt.raw_dialog_id:08X}."
            ),
            attempt=attempt,
        )

    def queue_unlock_skill(
        self,
        skill_id: int,
        *,
        target_id: int = 0,
        use_pvp_remap: bool = True,
        require_priest_target: bool = True,
        allow_already_unlocked: bool = False,
        log_send: bool = True,
    ) -> BalthazarSkillUnlockResult:
        prepared = self.build_unlock_attempt(
            skill_id,
            target_id=target_id,
            use_pvp_remap=use_pvp_remap,
            require_priest_target=require_priest_target,
            allow_already_unlocked=allow_already_unlocked,
        )
        if not prepared.ok or prepared.attempt is None:
            return prepared

        attempt = prepared.attempt
        attempt.sent_at = time.monotonic()
        Player.SendRawDialog(attempt.raw_dialog_id)

        if log_send:
            ConsoleLog(
                MODULE_NAME,
                (
                    f"Queued Balthazar unlock request target_id={attempt.target_id} "
                    f"model_id={attempt.target_model_id} requested_skill_id={attempt.requested_skill_id} "
                    f"send_skill_id={attempt.send_skill_id} raw_dialog=0x{attempt.raw_dialog_id:08X}"
                ),
                Console.MessageType.Info,
            )

        return BalthazarSkillUnlockResult(
            ok=True,
            message=(
                f"Queued unlock request for {attempt.requested_skill_name} "
                f"using raw dialog 0x{attempt.raw_dialog_id:08X}."
            ),
            attempt=attempt,
        )

    def verify_unlock_attempt(
        self,
        attempt: BalthazarSkillUnlockAttempt,
        *,
        verify_delay_seconds: float = 0.0,
        verify_timeout_seconds: Optional[float] = None,
    ) -> BalthazarSkillUnlockVerification:
        elapsed = max(0.0, time.monotonic() - float(attempt.sent_at or 0.0))
        unlocked_requested_now = self.is_skill_unlocked(attempt.requested_skill_id)
        unlocked_send_now = self.is_skill_unlocked(attempt.send_skill_id)
        balthazar_points_now = self.get_current_balthazar_points()

        if elapsed < verify_delay_seconds:
            return BalthazarSkillUnlockVerification(
                complete=False,
                success=False,
                message=(
                    f"Waiting to verify {attempt.requested_skill_name} "
                    f"({elapsed:.2f}s < {verify_delay_seconds:.2f}s)."
                ),
                elapsed_seconds=elapsed,
                balthazar_points_now=balthazar_points_now,
                unlocked_requested_now=unlocked_requested_now,
                unlocked_send_now=unlocked_send_now,
            )

        if (
            (not attempt.unlocked_requested_before and unlocked_requested_now)
            or (not attempt.unlocked_send_before and unlocked_send_now)
        ):
            return BalthazarSkillUnlockVerification(
                complete=True,
                success=True,
                message=(
                    f"Verified unlock for {attempt.requested_skill_name}. "
                    f"Balthazar faction: {attempt.balthazar_points_before} -> {balthazar_points_now}."
                ),
                elapsed_seconds=elapsed,
                balthazar_points_now=balthazar_points_now,
                unlocked_requested_now=unlocked_requested_now,
                unlocked_send_now=unlocked_send_now,
            )

        if balthazar_points_now < attempt.balthazar_points_before:
            return BalthazarSkillUnlockVerification(
                complete=True,
                success=True,
                message=(
                    f"Faction decreased after send ({attempt.balthazar_points_before} -> {balthazar_points_now}) "
                    f"for {attempt.requested_skill_name}. Unlock likely succeeded, but the bitmask has not been observed yet."
                ),
                elapsed_seconds=elapsed,
                balthazar_points_now=balthazar_points_now,
                unlocked_requested_now=unlocked_requested_now,
                unlocked_send_now=unlocked_send_now,
            )

        if verify_timeout_seconds is not None and elapsed >= verify_timeout_seconds:
            return BalthazarSkillUnlockVerification(
                complete=True,
                success=False,
                message=(
                    f"Sent 0x{attempt.raw_dialog_id:08X} for {attempt.requested_skill_name}, "
                    "but no unlock or faction change was verified."
                ),
                elapsed_seconds=elapsed,
                balthazar_points_now=balthazar_points_now,
                unlocked_requested_now=unlocked_requested_now,
                unlocked_send_now=unlocked_send_now,
            )

        return BalthazarSkillUnlockVerification(
            complete=False,
            success=False,
            message=f"Unlock request still pending for {attempt.requested_skill_name}.",
            elapsed_seconds=elapsed,
            balthazar_points_now=balthazar_points_now,
            unlocked_requested_now=unlocked_requested_now,
            unlocked_send_now=unlocked_send_now,
        )


_balthazar_skill_unlock_helper: Optional[BalthazarSkillUnlockHelper] = None


def get_balthazar_skill_unlock_helper() -> BalthazarSkillUnlockHelper:
    global _balthazar_skill_unlock_helper
    if _balthazar_skill_unlock_helper is None:
        _balthazar_skill_unlock_helper = BalthazarSkillUnlockHelper()
    return _balthazar_skill_unlock_helper


def refresh_skill_catalog() -> List[SkillOption]:
    return get_balthazar_skill_unlock_helper().refresh_skill_catalog()


def get_skill_catalog() -> List[SkillOption]:
    return get_balthazar_skill_unlock_helper().get_skill_catalog()


def get_skill_option(skill_id: int) -> Optional[SkillOption]:
    return get_balthazar_skill_unlock_helper().get_skill_option(skill_id)


def get_skill_name(skill_id: int) -> str:
    return get_balthazar_skill_unlock_helper().get_skill_name(skill_id)


def search_skills(query: str, limit: int = DEFAULT_SEARCH_RESULT_LIMIT) -> List[SkillOption]:
    return get_balthazar_skill_unlock_helper().search_skills(query, limit=limit)


def get_current_balthazar_points() -> int:
    return get_balthazar_skill_unlock_helper().get_current_balthazar_points()


def is_skill_unlocked(skill_id: int) -> bool:
    return get_balthazar_skill_unlock_helper().is_skill_unlocked(skill_id)


def normalize_send_skill_id(skill_id: int, use_pvp_remap: bool = True) -> int:
    return get_balthazar_skill_unlock_helper().normalize_send_skill_id(skill_id, use_pvp_remap=use_pvp_remap)


def estimated_unlock_cost(skill_id: int) -> int:
    return get_balthazar_skill_unlock_helper().estimated_unlock_cost(skill_id)


def get_target_summary(target_id: int = 0) -> BalthazarTargetSummary:
    return get_balthazar_skill_unlock_helper().get_target_summary(target_id)


def build_unlock_attempt(
    skill_id: int,
    *,
    target_id: int = 0,
    use_pvp_remap: bool = True,
    require_priest_target: bool = True,
    allow_already_unlocked: bool = False,
) -> BalthazarSkillUnlockResult:
    return get_balthazar_skill_unlock_helper().build_unlock_attempt(
        skill_id,
        target_id=target_id,
        use_pvp_remap=use_pvp_remap,
        require_priest_target=require_priest_target,
        allow_already_unlocked=allow_already_unlocked,
    )


def queue_unlock_skill(
    skill_id: int,
    *,
    target_id: int = 0,
    use_pvp_remap: bool = True,
    require_priest_target: bool = True,
    allow_already_unlocked: bool = False,
    log_send: bool = True,
) -> BalthazarSkillUnlockResult:
    return get_balthazar_skill_unlock_helper().queue_unlock_skill(
        skill_id,
        target_id=target_id,
        use_pvp_remap=use_pvp_remap,
        require_priest_target=require_priest_target,
        allow_already_unlocked=allow_already_unlocked,
        log_send=log_send,
    )


def verify_unlock_attempt(
    attempt: BalthazarSkillUnlockAttempt,
    *,
    verify_delay_seconds: float = 0.0,
    verify_timeout_seconds: Optional[float] = None,
) -> BalthazarSkillUnlockVerification:
    return get_balthazar_skill_unlock_helper().verify_unlock_attempt(
        attempt,
        verify_delay_seconds=verify_delay_seconds,
        verify_timeout_seconds=verify_timeout_seconds,
    )


__all__ = [
    "MODULE_NAME",
    "GREAT_TEMPLE_OF_BALTHAZAR_MAP_ID",
    "PRIEST_OF_BALTHAZAR_MODEL_ID",
    "BALTHAZAR_UNLOCK_DIALOG_MASK",
    "PVP_REMAP_SENTINEL",
    "DEFAULT_SEARCH_RESULT_LIMIT",
    "SkillOption",
    "BalthazarTargetSummary",
    "BalthazarSkillUnlockAttempt",
    "BalthazarSkillUnlockResult",
    "BalthazarSkillUnlockVerification",
    "BalthazarSkillUnlockHelper",
    "get_balthazar_skill_unlock_helper",
    "refresh_skill_catalog",
    "get_skill_catalog",
    "get_skill_option",
    "get_skill_name",
    "search_skills",
    "get_current_balthazar_points",
    "is_skill_unlocked",
    "normalize_send_skill_id",
    "estimated_unlock_cost",
    "get_target_summary",
    "build_unlock_attempt",
    "queue_unlock_skill",
    "verify_unlock_attempt",
]
