"""
Core wrapper for the native PySkillAccept C++ module.
This module owns pending skill acceptance hooks and debug state.
"""

from __future__ import annotations

from typing import List, Optional

try:
    import PySkillAccept
except Exception as exc:  # pragma: no cover - runtime environment specific
    PySkillAccept = None
    _PYSKILLACCEPT_IMPORT_ERROR = exc
else:
    _PYSKILLACCEPT_IMPORT_ERROR = None


class PendingSkillInfo:
    """Python wrapper for native PendingSkillInfo struct."""

    def __init__(self, native_info):
        self.native = native_info
        self.skill_id = native_info.skill_id
        self.copy_id = native_info.copy_id
        self.ref_count = native_info.ref_count


class PendingSkillDebugEvent:
    """Python wrapper for pending skill hook debug event."""

    def __init__(self, native_info):
        self.native = native_info
        self.owner_id = native_info.owner_id
        self.skill_id = native_info.skill_id
        self.copy_id = native_info.copy_id
        self.added = native_info.added


class PendingSkillFrameEvent:
    """Python wrapper for pending skill frame UI debug event."""

    def __init__(self, native_info):
        self.native = native_info
        self.source = native_info.source
        self.message_id = native_info.message_id
        self.wparam_ptr = native_info.wparam_ptr
        self.lparam_ptr = native_info.lparam_ptr
        self.w0 = native_info.w0
        self.w1 = native_info.w1
        self.w2 = native_info.w2
        self.w3 = native_info.w3
        self.w4 = native_info.w4
        self.frame_id = native_info.frame_id
        self.frame_hash = native_info.frame_hash
        self.parent_frame_id = native_info.parent_frame_id
        self.child_offset_id = native_info.child_offset_id
        self.frame_context_ptr = native_info.frame_context_ptr
        self.callback_index = native_info.callback_index
        self.callback_ptr = native_info.callback_ptr
        self.callback_context_ptr = native_info.callback_context_ptr
        self.callback_context_deref_ptr = native_info.callback_context_deref_ptr
        self.state_ptr = native_info.state_ptr
        self.root_frame_id = native_info.root_frame_id
        self.root_frame_hash = native_info.root_frame_hash
        self.equip_button_frame_id = native_info.equip_button_frame_id
        self.slot_index = native_info.slot_index
        self.owner_id = native_info.owner_id
        self.skill_id = native_info.skill_id
        self.copy_id = native_info.copy_id
        self.accepted = native_info.accepted
        self.reason = native_info.reason


class VisibleRewardSkillInfo:
    """Python wrapper for visible reward skill resolution state."""

    def __init__(self, native_info):
        self.native = native_info
        self.skill_id = native_info.skill_id
        self.owner_id = native_info.owner_id
        self.source_frame_id = native_info.source_frame_id


class PendingSkillResolutionTraceEntry:
    """Python wrapper for pending skill resolution trace state."""

    def __init__(self, native_info):
        self.native = native_info
        self.queried_frame_id = native_info.queried_frame_id
        self.inspected_frame_id = native_info.inspected_frame_id
        self.inspected_frame_hash = native_info.inspected_frame_hash
        self.ancestry_depth = native_info.ancestry_depth
        self.stage = native_info.stage
        self.callback_ptr = native_info.callback_ptr
        self.context_ptr = native_info.context_ptr
        self.state_ptr = native_info.state_ptr
        self.root_frame_id = native_info.root_frame_id
        self.root_frame_hash = native_info.root_frame_hash
        self.equip_button_frame_id = native_info.equip_button_frame_id
        self.slot_index = native_info.slot_index
        self.owner_id = native_info.owner_id
        self.skill_id = native_info.skill_id
        self.accepted = native_info.accepted
        self.reason = native_info.reason


class SkillAcceptWidget:
    """High-level wrapper around the native PySkillAccept module."""

    def __init__(self) -> None:
        self._initialized = False

    def initialize(self) -> bool:
        if PySkillAccept is None:
            return False
        try:
            PySkillAccept.PySkillAccept.initialize()
            self._initialized = True
            return True
        except Exception:
            self._initialized = False
            return False

    def terminate(self) -> None:
        if PySkillAccept is None:
            return
        try:
            PySkillAccept.PySkillAccept.terminate()
        finally:
            self._initialized = False

    def clear_cache(self) -> None:
        if PySkillAccept is None:
            return
        PySkillAccept.PySkillAccept.clear_cache()

    def get_pending_skills(self, agent_id: int = 0) -> List[PendingSkillInfo]:
        if PySkillAccept is None:
            return []
        native_list = PySkillAccept.PySkillAccept.get_pending_skills(agent_id)
        return [PendingSkillInfo(item) for item in native_list]

    def get_pending_skill_debug_event(self) -> Optional[PendingSkillDebugEvent]:
        if PySkillAccept is None:
            return None
        native_info = PySkillAccept.PySkillAccept.get_pending_skill_debug_event()
        return PendingSkillDebugEvent(native_info)

    def get_pending_skill_frame_events(self) -> List[PendingSkillFrameEvent]:
        if PySkillAccept is None:
            return []
        native_list = PySkillAccept.PySkillAccept.get_pending_skill_frame_events()
        return [PendingSkillFrameEvent(item) for item in native_list]

    def clear_pending_skill_frame_events(self) -> None:
        if PySkillAccept is None:
            return
        PySkillAccept.PySkillAccept.clear_pending_skill_frame_events()

    def get_pending_skill_resolution_trace(self) -> List[PendingSkillResolutionTraceEntry]:
        if PySkillAccept is None:
            return []
        native_list = PySkillAccept.PySkillAccept.get_pending_skill_resolution_trace()
        return [PendingSkillResolutionTraceEntry(item) for item in native_list]

    def clear_pending_skill_resolution_trace(self) -> None:
        if PySkillAccept is None:
            return
        PySkillAccept.PySkillAccept.clear_pending_skill_resolution_trace()

    def get_visible_reward_skill_from_frame(self, frame_id: int) -> VisibleRewardSkillInfo:
        if PySkillAccept is None:
            return VisibleRewardSkillInfo(type("VisibleRewardFallback", (), {
                "skill_id": 0,
                "owner_id": 0,
                "source_frame_id": 0,
            })())
        native_info = PySkillAccept.PySkillAccept.get_visible_reward_skill_from_frame(frame_id)
        return VisibleRewardSkillInfo(native_info)

    def accept_offered_skill(self, skill_id: int) -> bool:
        if PySkillAccept is None:
            return False
        return bool(PySkillAccept.PySkillAccept.accept_offered_skill(skill_id))

    def accept_offered_skill_replace(
        self, skill_id: int, slot_index: int, copy_id: Optional[int] = None
    ) -> bool:
        if PySkillAccept is None:
            return False
        return bool(
            PySkillAccept.PySkillAccept.accept_offered_skill_replace(
                skill_id, slot_index, copy_id
            )
        )

    def accept_offered_skill_and_apply_pending(
        self,
        skill_id: int,
        slot_index: int,
        agent_id: int = 0,
        timeout_ms: int = 1500,
    ) -> bool:
        if PySkillAccept is None:
            return False
        return bool(
            PySkillAccept.PySkillAccept.accept_offered_skill_and_apply_pending(
                skill_id, slot_index, agent_id, timeout_ms
            )
        )

    def apply_pending_skill_replace(
        self,
        skill_id: int,
        slot_index: int,
        copy_id: Optional[int] = None,
        agent_id: int = 0,
    ) -> bool:
        if PySkillAccept is None:
            return False
        return bool(
            PySkillAccept.PySkillAccept.apply_pending_skill_replace(
                skill_id, slot_index, copy_id, agent_id
            )
        )

    def apply_pending_skill_replace_from_frame(
        self,
        skill_id: int,
        slot_index: int,
        frame_id: int,
        agent_id: int = 0,
    ) -> bool:
        if PySkillAccept is None:
            return False
        return bool(
            PySkillAccept.PySkillAccept.apply_pending_skill_replace_from_frame(
                skill_id, slot_index, frame_id, agent_id
            )
        )

    def apply_visible_reward_skill_replace_from_frame(
        self,
        slot_index: int,
        frame_id: int,
        agent_id: int = 0,
        target_frame_id: int = 0,
    ) -> bool:
        if PySkillAccept is None:
            return False
        return bool(
            PySkillAccept.PySkillAccept.apply_visible_reward_skill_replace_from_frame(
                slot_index, frame_id, agent_id, target_frame_id
            )
        )

    def apply_open_reward_skill_replace_from_root(
        self,
        skill_id: int,
        slot_index: int,
        root_frame_id: int,
        agent_id: int = 0,
        target_frame_id: int = 0,
    ) -> bool:
        if PySkillAccept is None:
            return False
        return bool(
            PySkillAccept.PySkillAccept.apply_open_reward_skill_replace_from_root(
                skill_id, slot_index, root_frame_id, agent_id, target_frame_id
            )
        )


_skill_accept_widget_instance: Optional[SkillAcceptWidget] = None


def get_skill_accept_widget() -> SkillAcceptWidget:
    global _skill_accept_widget_instance
    if _skill_accept_widget_instance is None:
        _skill_accept_widget_instance = SkillAcceptWidget()
    return _skill_accept_widget_instance


def get_pending_skills(agent_id: int = 0) -> List[PendingSkillInfo]:
    return get_skill_accept_widget().get_pending_skills(agent_id)


def get_pending_skill_debug_event() -> Optional[PendingSkillDebugEvent]:
    return get_skill_accept_widget().get_pending_skill_debug_event()


def get_pending_skill_frame_events() -> List[PendingSkillFrameEvent]:
    return get_skill_accept_widget().get_pending_skill_frame_events()


def clear_pending_skill_frame_events() -> None:
    get_skill_accept_widget().clear_pending_skill_frame_events()


def get_pending_skill_resolution_trace() -> List[PendingSkillResolutionTraceEntry]:
    return get_skill_accept_widget().get_pending_skill_resolution_trace()


def clear_pending_skill_resolution_trace() -> None:
    get_skill_accept_widget().clear_pending_skill_resolution_trace()


def get_visible_reward_skill_from_frame(frame_id: int) -> VisibleRewardSkillInfo:
    return get_skill_accept_widget().get_visible_reward_skill_from_frame(frame_id)


def accept_offered_skill(skill_id: int) -> bool:
    return get_skill_accept_widget().accept_offered_skill(skill_id)


def accept_offered_skill_replace(skill_id: int, slot_index: int, copy_id: Optional[int] = None) -> bool:
    return get_skill_accept_widget().accept_offered_skill_replace(skill_id, slot_index, copy_id)


def accept_offered_skill_and_apply_pending(
    skill_id: int,
    slot_index: int,
    agent_id: int = 0,
    timeout_ms: int = 1500,
) -> bool:
    return get_skill_accept_widget().accept_offered_skill_and_apply_pending(
        skill_id,
        slot_index,
        agent_id,
        timeout_ms,
    )


def apply_pending_skill_replace(
    skill_id: int,
    slot_index: int,
    copy_id: Optional[int] = None,
    agent_id: int = 0,
) -> bool:
    return get_skill_accept_widget().apply_pending_skill_replace(skill_id, slot_index, copy_id, agent_id)


def apply_pending_skill_replace_from_frame(
    skill_id: int,
    slot_index: int,
    frame_id: int,
    agent_id: int = 0,
) -> bool:
    return get_skill_accept_widget().apply_pending_skill_replace_from_frame(skill_id, slot_index, frame_id, agent_id)


def apply_visible_reward_skill_replace_from_frame(
    slot_index: int,
    frame_id: int,
    agent_id: int = 0,
    target_frame_id: int = 0,
) -> bool:
    return get_skill_accept_widget().apply_visible_reward_skill_replace_from_frame(
        slot_index,
        frame_id,
        agent_id,
        target_frame_id,
    )


def apply_open_reward_skill_replace_from_root(
    skill_id: int,
    slot_index: int,
    root_frame_id: int,
    agent_id: int = 0,
    target_frame_id: int = 0,
) -> bool:
    return get_skill_accept_widget().apply_open_reward_skill_replace_from_root(
        skill_id,
        slot_index,
        root_frame_id,
        agent_id,
        target_frame_id,
    )
