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


def accept_offered_skill(skill_id: int) -> bool:
    return get_skill_accept_widget().accept_offered_skill(skill_id)


def accept_offered_skill_replace(skill_id: int, slot_index: int, copy_id: Optional[int] = None) -> bool:
    return get_skill_accept_widget().accept_offered_skill_replace(skill_id, slot_index, copy_id)


def apply_pending_skill_replace(
    skill_id: int,
    slot_index: int,
    copy_id: Optional[int] = None,
    agent_id: int = 0,
) -> bool:
    return get_skill_accept_widget().apply_pending_skill_replace(skill_id, slot_index, copy_id, agent_id)
