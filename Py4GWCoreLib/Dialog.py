"""
Core Dialog wrapper for the native PyDialog C++ module.
This module provides dialog access helpers for use by widgets or scripts.

Layering in this module:
1. Live/native state via `PyDialog` (`get_active_dialog`, buttons, callback journal).
2. Static dialog metadata and decoded text via `DialogCatalog` when available.
3. Optional SQLite-backed history via `dialog_step_pipeline`.
4. Thin module-level wrapper functions at the bottom for ergonomic imports.

When changing behavior, keep those responsibilities separate. Most regressions here come
from mixing live UI state, static catalog lookups, and persisted history in the same path.
"""

from __future__ import annotations

import importlib
import re
from typing import Any, Callable, Dict, List, Optional, Tuple


def _import_optional_attr(relative_module: str, absolute_module: str, attr_name: str) -> Any:
    if __package__:
        try:
            module = importlib.import_module(relative_module, __package__)
            return getattr(module, attr_name)
        except Exception:
            pass
    try:
        module = importlib.import_module(absolute_module)
        return getattr(module, attr_name)
    except Exception:
        return None


def _safe_call(default: Any, callback: Callable[[], Any]) -> Any:
    try:
        return callback()
    except Exception:
        return default


def _call_native_dialog_method(method_name: str, default: Any, *args: Any, **kwargs: Any) -> Any:
    if PyDialog is None:
        return default
    method = getattr(PyDialog.PyDialog, method_name, None)
    if not callable(method):
        return default
    return _safe_call(default, lambda: method(*args, **kwargs))


_get_dialog_step_pipeline = _import_optional_attr(
    ".dialog_step_pipeline",
    "dialog_step_pipeline",
    "get_dialog_step_pipeline",
)

try:
    import PyDialog
except Exception:  # pragma: no cover - runtime environment specific
    PyDialog = None


# Text sanitation helpers.
def _get_dialog_catalog_widget():
    factory = _import_optional_attr(
        ".DialogCatalog",
        "DialogCatalog",
        "get_dialog_catalog_widget",
    )
    if not callable(factory):
        return None
    return _safe_call(None, factory)


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_COLOR_TAG_RE = re.compile(r"</?c(?:=[^>]*)?>", re.IGNORECASE)
_GENERIC_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9:_-]*(?:\s+[^>]*)?>")
_LBRACKET_TOKEN_RE = re.compile(r"\[lbracket\]", re.IGNORECASE)
_RBRACKET_TOKEN_RE = re.compile(r"\[rbracket\]", re.IGNORECASE)
_ORPHAN_BREAK_TOKEN_RE = re.compile(r"(?<!\w)(?:brx|br)(?!\w)", re.IGNORECASE)
_ORPHAN_PARAGRAPH_TOKEN_RE = re.compile(r"(?<!\w)p(?!\w)")
_MISSING_SPACE_AFTER_PUNCT_RE = re.compile(r"([!?:;\)\]])([A-Za-z0-9])")
_MISSING_SPACE_ALPHA_NUM_RE = re.compile(r"([A-Za-z])(\d{2,})")
_MISSING_SPACE_NUM_ALPHA_RE = re.compile(r"(\d{2,})([A-Za-z])")
_MISSING_SPACE_CAMEL_RE = re.compile(r"([a-z])([A-Z])")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_INLINE_CHOICE_RE = re.compile(r"<a\s*=\s*([^>]+)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_SENTINEL_CANONICAL = {
    "<empty>": "<empty>",
    "<no label>": "<no label>",
    "<decoding...>": "<decoding...>",
    "<decoding label...>": "<decoding label...>",
}
_SENTINEL_RE = re.compile(
    "|".join(re.escape(token) for token in _SENTINEL_CANONICAL.keys()),
    re.IGNORECASE,
)


def _protect_sentinel_placeholders(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def _replace(match: re.Match[str]) -> str:
        placeholder = f"__PY4GW_SENTINEL_{len(protected)}__"
        canonical = _SENTINEL_CANONICAL.get(match.group(0).lower(), match.group(0))
        protected[placeholder] = canonical
        return placeholder

    return _SENTINEL_RE.sub(_replace, text), protected


def _sanitize_dialog_text(value: Optional[str]) -> str:
    """
    Normalize Guild Wars dialog text into a stable display/query form.

    This removes control characters and markup noise while preserving the
    project-specific sentinel placeholders used by the dialog monitor.
    """
    if not value:
        return ""
    text = str(value)
    # Preserve project-specific sentinel placeholders before stripping generic markup so callers
    # can still distinguish "empty" / "decoding" states after sanitation.
    text, protected_sentinels = _protect_sentinel_placeholders(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _LBRACKET_TOKEN_RE.sub("[", text)
    text = _RBRACKET_TOKEN_RE.sub("]", text)
    text = _COLOR_TAG_RE.sub("", text)
    text = _GENERIC_TAG_RE.sub("", text)
    # Some decoded GW strings leak markup tokens as plain words (e.g. "p", "brx").
    text = _ORPHAN_BREAK_TOKEN_RE.sub(" ", text)
    text = _ORPHAN_PARAGRAPH_TOKEN_RE.sub(" ", text)
    for placeholder, canonical in protected_sentinels.items():
        text = text.replace(placeholder, canonical)
    # Repair collapsed separators caused by removed formatting tags.
    text = _MISSING_SPACE_AFTER_PUNCT_RE.sub(r"\1 \2", text)
    text = _MISSING_SPACE_ALPHA_NUM_RE.sub(r"\1 \2", text)
    text = _MISSING_SPACE_NUM_ALPHA_RE.sub(r"\1 \2", text)
    text = _MISSING_SPACE_CAMEL_RE.sub(r"\1 \2", text)
    text = _CONTROL_CHARS_RE.sub("", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def sanitize_dialog_text(value: Optional[str]) -> str:
    """Public sanitizer for any GW dialog-related text."""
    return _sanitize_dialog_text(value)


def _normalize_dialog_choice_text(value: Optional[str]) -> str:
    return " ".join(_sanitize_dialog_text(value).strip().lower().split())


def _get_dialog_button_label(button: Any) -> str:
    if button is None:
        return ""
    decoded = getattr(button, "message_decoded", "")
    if decoded:
        return _sanitize_dialog_text(decoded)
    return _sanitize_dialog_text(getattr(button, "message", ""))


def _append_unique_dialog_choice_text(values: List[str], value: Optional[str]) -> None:
    text = _sanitize_dialog_text(value)
    if text and text not in values:
        values.append(text)


def _coerce_native_list(value: Any) -> List[Any]:
    """
    Normalize pybind/native list-like return values into a concrete Python list.

    This keeps runtime behavior defensive and gives static type checkers a stable
    iterable type for dynamic `getattr`-based native access paths.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return list(value)
    except TypeError:
        return []


def _build_active_dialog_npc_filters(active_dialog: Optional["ActiveDialogInfo"]) -> Dict[str, Any]:
    """
    Build the current NPC instance/archetype filters for persisted history queries.

    These filters keep history-based dialog matching scoped to the live NPC so
    reused dialog ids from other actors do not bleed into the current screen.
    """
    if active_dialog is None:
        return {}

    agent_id = int(getattr(active_dialog, "agent_id", 0) or 0)
    if agent_id <= 0:
        return {}

    map_id = 0
    model_id = 0

    try:
        from .Map import Map
    except Exception:
        try:
            from Map import Map  # type: ignore
        except Exception:
            Map = None  # type: ignore

    try:
        from .Agent import Agent
    except Exception:
        try:
            from Agent import Agent  # type: ignore
        except Exception:
            Agent = None  # type: ignore

    if Map is not None:
        try:
            map_id = int(Map.GetMapID() or 0)
        except Exception:
            map_id = 0

    if Agent is not None:
        try:
            model_id = int(Agent.GetModelID(agent_id) or 0)
        except Exception:
            model_id = 0

    if map_id <= 0 or model_id <= 0:
        return {}

    # History lookups must stay scoped to the live NPC instance/archetype. Dialog ids are reused
    # broadly enough that cross-NPC history can otherwise relabel the current visible buttons.
    npc_uid_archetype = f"{map_id}:{model_id}"
    return {
        "npc_uid_instance": f"{npc_uid_archetype}:{agent_id}",
        "npc_uid_archetype": npc_uid_archetype,
    }


def _normalize_direction_filter(direction: Optional[str]) -> Optional[bool]:
    if direction is None:
        return None
    value = str(direction).strip().lower()
    if not value or value in {"all", "both", "*"}:
        return None
    if value in {"recv", "received", "incoming", "in"}:
        return True
    if value in {"sent", "outgoing", "out"}:
        return False
    raise ValueError(f"Unsupported direction filter: {direction}")


def _parse_message_type_filter(message_type: Optional[Any]) -> Tuple[Optional[int], Optional[str]]:
    if message_type is None:
        return None, None
    if isinstance(message_type, bool):
        raise TypeError("message_type must be int or str, not bool")
    if isinstance(message_type, int):
        return int(message_type), None
    value = str(message_type).strip()
    if not value:
        return None, None
    try:
        return int(value, 0), None
    except ValueError:
        return None, value.lower()


def _normalize_npc_uid_filter(npc_uid: Optional[str]) -> Optional[str]:
    if npc_uid is None:
        return None
    value = str(npc_uid).strip()
    return value if value else None


_DIAG_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


# Diagnostics helpers for persisted dialog history.
def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _build_diag_issue(
    *,
    severity: str,
    rule: str,
    message: str,
    npc_uid: str = "",
    step_id: int = 0,
    dialog_id: int = 0,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "severity": severity,
        "rule": rule,
        "message": message,
        "npc_uid": npc_uid,
        "step_id": int(step_id),
        "dialog_id": int(dialog_id),
        "details": details or {},
    }


def _analyze_dialog_steps(
    steps: List[Dict[str, Any]],
    *,
    max_issues: int = 250,
) -> Dict[str, Any]:
    """
    Run lightweight consistency checks over persisted dialog history rows.

    The diagnostics are intentionally conservative and meant for monitor/debug
    surfaces, not for blocking runtime behavior.
    """
    issues: List[Dict[str, Any]] = []

    for step in steps:
        step_id = _as_int(step.get("id", 0), 0)
        npc_uid = _as_text(step.get("npc_uid_instance", "")).strip()
        body_dialog_id = _as_int(step.get("body_dialog_id", 0), 0)
        selected_dialog_id = _as_int(step.get("selected_dialog_id", 0), 0)
        finalized_reason = _as_text(step.get("finalized_reason", "")).strip().lower()
        body_text = _as_text(step.get("body_text_raw", ""))
        choices = list(step.get("choices", []) or [])

        if body_dialog_id == 0 and choices:
            issues.append(
                _build_diag_issue(
                    severity="warning",
                    rule="orphan_choices_without_body",
                    message="Turn has choices but no body dialog id.",
                    npc_uid=npc_uid,
                    step_id=step_id,
                    dialog_id=0,
                    details={"choice_count": len(choices)},
                )
            )

        if body_dialog_id != 0 and not body_text.strip():
            issues.append(
                _build_diag_issue(
                    severity="warning",
                    rule="missing_body_text",
                    message="Turn body dialog id is set but body text is empty.",
                    npc_uid=npc_uid,
                    step_id=step_id,
                    dialog_id=body_dialog_id,
                )
            )

        if finalized_reason == "timeout":
            issues.append(
                _build_diag_issue(
                    severity="info",
                    rule="timeout_finalization",
                    message="Turn was finalized by timeout.",
                    npc_uid=npc_uid,
                    step_id=step_id,
                    dialog_id=body_dialog_id,
                )
            )

        choice_ids: List[int] = [
            _as_int(choice.get("choice_dialog_id", 0), 0)
            for choice in choices
            if _as_int(choice.get("choice_dialog_id", 0), 0) != 0
        ]

        if selected_dialog_id != 0 and selected_dialog_id not in set(choice_ids):
            issues.append(
                _build_diag_issue(
                    severity="error",
                    rule="selected_choice_not_offered",
                    message="Selected dialog id is not present in the offered choices for this step.",
                    npc_uid=npc_uid,
                    step_id=step_id,
                    dialog_id=selected_dialog_id,
                    details={"offered_choice_ids": choice_ids},
                )
            )

    issues.sort(
        key=lambda issue: (
            _DIAG_SEVERITY_ORDER.get(_as_text(issue.get("severity", "info")).lower(), 99),
            -_as_int(issue.get("step_id", 0), 0),
        )
    )

    if max_issues > 0:
        issues = issues[: int(max_issues)]

    summary = {"error": 0, "warning": 0, "info": 0, "total": len(issues)}
    for issue in issues:
        severity = _as_text(issue.get("severity", "info")).lower()
        if severity not in summary:
            summary[severity] = 0
        summary[severity] += 1

    return {
        "summary": summary,
        "issues": issues,
        "analyzed_steps": len(steps),
    }


class DialogInfo:
    """Python wrapper for native DialogInfo struct."""

    def __init__(self, native_dialog_info):
        self.native = native_dialog_info
        self.dialog_id = native_dialog_info.dialog_id
        self.flags = native_dialog_info.flags
        self.frame_type = native_dialog_info.frame_type
        self.event_handler = native_dialog_info.event_handler
        self.content_id = native_dialog_info.content_id
        self.property_id = native_dialog_info.property_id
        self.content = _sanitize_dialog_text(native_dialog_info.content)
        self.agent_id = native_dialog_info.agent_id

    def is_available(self) -> bool:
        return (self.flags & 0x1) != 0

    def __repr__(self) -> str:
        return f"DialogInfo(id=0x{self.dialog_id:04x}, available={self.is_available()})"


class ActiveDialogInfo:
    """Python wrapper for native ActiveDialogInfo struct."""

    def __init__(
        self,
        native_active_dialog=None,
        *,
        dialog_id: int = 0,
        context_dialog_id: int = 0,
        agent_id: int = 0,
        dialog_id_authoritative: bool = False,
        message: str = "",
        raw_message: str = "",
    ):
        if native_active_dialog is not None:
            self.native = native_active_dialog
            self.dialog_id = int(getattr(native_active_dialog, "dialog_id", 0))
            self.context_dialog_id = int(getattr(native_active_dialog, "context_dialog_id", 0))
            self.agent_id = int(getattr(native_active_dialog, "agent_id", 0))
            self.dialog_id_authoritative = bool(getattr(native_active_dialog, "dialog_id_authoritative", False))
            self.raw_message = str(getattr(native_active_dialog, "message", "") or "")
            self.message = _sanitize_dialog_text(self.raw_message)
        else:
            self.native = None
            self.dialog_id = dialog_id
            self.context_dialog_id = context_dialog_id
            self.agent_id = agent_id
            self.dialog_id_authoritative = dialog_id_authoritative
            self.raw_message = str(raw_message or message or "")
            self.message = _sanitize_dialog_text(message)

    def __repr__(self) -> str:
        return (
            "ActiveDialogInfo("
            f"dialog_id=0x{self.dialog_id:04x}, "
            f"context_dialog_id=0x{self.context_dialog_id:04x}, "
            f"authoritative={self.dialog_id_authoritative}, "
            f"agent_id={self.agent_id})"
        )


class DialogButtonInfo:
    """Python wrapper for native DialogButtonInfo struct."""

    def __init__(
        self,
        native_button_info=None,
        *,
        dialog_id: int = 0,
        button_icon: int = 0,
        message: str = "",
        message_decoded: str = "",
        message_decode_pending: bool = False,
    ):
        if native_button_info is not None:
            self.native = native_button_info
            self.dialog_id = native_button_info.dialog_id
            self.button_icon = native_button_info.button_icon
            self.message = _sanitize_dialog_text(native_button_info.message)
            self.message_decoded = _sanitize_dialog_text(native_button_info.message_decoded)
            self.message_decode_pending = native_button_info.message_decode_pending
        else:
            self.native = None
            self.dialog_id = dialog_id
            self.button_icon = button_icon
            self.message = _sanitize_dialog_text(message)
            self.message_decoded = _sanitize_dialog_text(message_decoded)
            self.message_decode_pending = message_decode_pending

    def __repr__(self) -> str:
        return f"DialogButtonInfo(dialog_id=0x{self.dialog_id:04x})"


# Inline choice extraction helpers.
def _parse_inline_choice_dialog_id(raw_value: Any) -> int:
    value = str(raw_value or "").strip()
    if not value:
        return 0
    try:
        return int(value, 0)
    except Exception:
        return 0


def _extract_inline_dialog_choices_from_text(body_text: Optional[str]) -> List[DialogButtonInfo]:
    """
    Extract `<a=...>...</a>` style inline choices from raw dialog body text.

    Some GW dialogs expose choices inline instead of through the native active
    button list, so this parser acts as the fallback source for those screens.
    """
    text = str(body_text or "")
    if not text or "<a=" not in text.lower():
        return []

    choices: List[DialogButtonInfo] = []
    seen: set[tuple[int, str]] = set()
    for match in _INLINE_CHOICE_RE.finditer(text):
        dialog_id = _parse_inline_choice_dialog_id(match.group(1))
        if dialog_id == 0:
            continue
        label = _sanitize_dialog_text(match.group(2))
        if not label:
            label = "<empty>"
        dedupe_key = (dialog_id, label)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        choices.append(
            DialogButtonInfo(
                dialog_id=dialog_id,
                message=label,
                message_decoded=label,
                message_decode_pending=False,
            )
        )
    return choices


def extract_inline_dialog_choices_from_text(body_text: Optional[str]) -> List[DialogButtonInfo]:
    """Parse inline GW dialog anchors like `<a=1>...</a>` from raw body text."""
    return _extract_inline_dialog_choices_from_text(body_text)


def _extract_raw_active_dialog_message(active_dialog: Any) -> str:
    if active_dialog is None:
        return ""

    raw_message = getattr(active_dialog, "raw_message", None)
    if raw_message is not None:
        return str(raw_message or "")

    native_dialog = getattr(active_dialog, "native", None)
    if native_dialog is not None:
        native_message = getattr(native_dialog, "message", None)
        if native_message is not None:
            return str(native_message or "")

    message = getattr(active_dialog, "message", None)
    if message is not None:
        return str(message or "")
    return ""


def extract_inline_dialog_choices_from_active(active_dialog: Any) -> List[DialogButtonInfo]:
    """Parse inline choices from either a wrapped ActiveDialogInfo or raw native active dialog object."""
    return _extract_inline_dialog_choices_from_text(_extract_raw_active_dialog_message(active_dialog))


class DialogTextDecodedInfo:
    """Python wrapper for decoded dialog text status."""

    def __init__(self, native_info):
        self.native = native_info
        self.dialog_id = native_info.dialog_id
        self.text = _sanitize_dialog_text(native_info.text)
        self.pending = native_info.pending


class DialogCallbackJournalEntry:
    """Python wrapper for native structured dialog callback journal entries."""

    def __init__(self, native_info):
        self.native = native_info
        self.tick = int(getattr(native_info, "tick", 0))
        self.message_id = int(getattr(native_info, "message_id", 0))
        self.incoming = bool(getattr(native_info, "incoming", False))
        self.dialog_id = int(getattr(native_info, "dialog_id", 0))
        self.context_dialog_id = int(getattr(native_info, "context_dialog_id", 0))
        self.agent_id = int(getattr(native_info, "agent_id", 0))
        self.map_id = int(getattr(native_info, "map_id", 0))
        self.model_id = int(getattr(native_info, "model_id", 0))
        self.dialog_id_authoritative = bool(getattr(native_info, "dialog_id_authoritative", False))
        self.context_dialog_id_inferred = bool(getattr(native_info, "context_dialog_id_inferred", False))
        self.npc_uid = str(getattr(native_info, "npc_uid", "") or "")
        self.event_type = str(getattr(native_info, "event_type", "") or "")
        # Keep callback journal text raw; callers decide whether/how to sanitize.
        self.text = str(getattr(native_info, "text", "") or "")


class DialogWidget:
    """
    High-level wrapper around the native PyDialog module.

    Use this class when you want one object that exposes live dialog state,
    static dialog metadata, callback journals, and optional persisted history.
    """

    def __init__(self) -> None:
        self._initialized = False

    def initialize(self) -> bool:
        """Initialize the native dialog module if it is available."""
        if PyDialog is None:
            return False
        try:
            PyDialog.PyDialog.initialize()
            self._initialized = True
            return True
        except Exception:
            self._initialized = False
            return False

    def terminate(self) -> None:
        """Terminate the native dialog module and clear local initialized state."""
        if PyDialog is None:
            return
        try:
            PyDialog.PyDialog.terminate()
        finally:
            self._initialized = False

    def get_active_dialog(self) -> Optional[ActiveDialogInfo]:
        """
        Return the current live dialog body, or `None` when no dialog is active.

        This is the main entry point for live dialog automation.
        """
        native_info = _call_native_dialog_method("get_active_dialog", None)
        if native_info is None:
            return None
        if (
            getattr(native_info, "dialog_id", 0) == 0
            and getattr(native_info, "context_dialog_id", 0) == 0
            and getattr(native_info, "agent_id", 0) == 0
        ):
            return None
        return ActiveDialogInfo(native_info)

    def get_active_dialog_buttons(self) -> List[DialogButtonInfo]:
        """
        Return the currently visible dialog buttons for the active screen.

        Falls back to parsing inline body markup when the native button list is
        empty for dialogs that encode choices directly in the message text.
        """
        native_list = _coerce_native_list(_call_native_dialog_method("get_active_dialog_buttons", []))
        buttons = [DialogButtonInfo(item) for item in native_list]
        if buttons:
            return buttons
        # Some dialogs expose choices inline in the body markup instead of through the native
        # button list. Falling back here keeps the public API stable for those screens.
        native_active = _call_native_dialog_method("get_active_dialog", None)
        return extract_inline_dialog_choices_from_active(native_active)

    def get_last_selected_dialog_id(self) -> int:
        """Return the most recent dialog id sent through the native dialog API."""
        return int(_call_native_dialog_method("get_last_selected_dialog_id", 0) or 0)

    def _get_dialog_choice_catalog_text(self, dialog_id: int) -> str:
        if int(dialog_id) == 0:
            return ""
        try:
            dialog_info = self.get_dialog_info(int(dialog_id))
        except Exception:
            dialog_info = None
        if dialog_info is not None:
            content = _sanitize_dialog_text(getattr(dialog_info, "content", ""))
            if content:
                return content
        try:
            return _sanitize_dialog_text(self.get_dialog_text_decoded(int(dialog_id)))
        except Exception:
            return ""

    def _get_dialog_choice_history_texts(
        self,
        dialog_id: int,
        *,
        active_dialog: Optional[ActiveDialogInfo] = None,
        history_limit: int = 25,
    ) -> List[str]:
        """
        Collect historical labels for a choice dialog id from persisted dialog steps.

        This is a recovery helper for live screens whose visible button text is
        missing or undecoded.
        """
        if int(dialog_id) == 0:
            return []

        query_kwargs: Dict[str, Any] = {
            "choice_dialog_id": int(dialog_id),
            "limit": max(1, int(history_limit)),
            "offset": 0,
            "include_choices": True,
            "sync": False,
        }
        if active_dialog is not None:
            body_dialog_id = int(
                getattr(active_dialog, "context_dialog_id", 0)
                or getattr(active_dialog, "dialog_id", 0)
                or 0
            )
            if body_dialog_id != 0:
                query_kwargs["body_dialog_id"] = body_dialog_id
            # The active NPC/body filters are what make fallback matching safe enough to use for
            # automation. Without them, reused dialog ids from another NPC can match incorrectly.
            query_kwargs.update(_build_active_dialog_npc_filters(active_dialog))

        steps = self.get_dialog_steps(**query_kwargs)

        texts: List[str] = []
        for step in steps:
            for choice in list(step.get("choices", []) or []):
                if int(choice.get("choice_dialog_id", 0) or 0) != int(dialog_id):
                    continue
                _append_unique_dialog_choice_text(texts, choice.get("choice_text_decoded", ""))
                _append_unique_dialog_choice_text(texts, choice.get("choice_text_raw", ""))
        return texts

    def get_active_dialog_choice_id_by_text(self, text: Optional[str]) -> int:
        """Resolve a visible choice by its current on-screen label only."""
        needle = _normalize_dialog_choice_text(text)
        if not needle or not self.is_dialog_active():
            return 0

        for button in self.get_active_dialog_buttons():
            dialog_id = int(getattr(button, "dialog_id", 0) or 0)
            if dialog_id == 0:
                continue
            if _normalize_dialog_choice_text(_get_dialog_button_label(button)) == needle:
                return dialog_id
        return 0

    def get_active_dialog_choice_id_by_text_with_fallback(
        self,
        text: Optional[str],
        *,
        history_limit: int = 25,
    ) -> int:
        """
        Resolve a choice by text using live labels first, then catalog/history fallbacks.

        This is the safer automation helper when some labels are blank, inline,
        or still waiting for decode status to catch up.
        """
        needle = _normalize_dialog_choice_text(text)
        if not needle or not self.is_dialog_active():
            return 0

        buttons = list(self.get_active_dialog_buttons())
        if not buttons:
            return 0

        for button in buttons:
            dialog_id = int(getattr(button, "dialog_id", 0) or 0)
            if dialog_id == 0:
                continue
            if _normalize_dialog_choice_text(_get_dialog_button_label(button)) == needle:
                return dialog_id

        # Resolution order matters:
        # 1. live visible labels,
        # 2. static catalog / decoded dialog text,
        # 3. persisted history scoped to the current NPC/body.
        #
        # The earlier tiers are cheaper and less ambiguous. History is a recovery path only.
        for button in buttons:
            dialog_id = int(getattr(button, "dialog_id", 0) or 0)
            if dialog_id == 0:
                continue
            if _normalize_dialog_choice_text(self._get_dialog_choice_catalog_text(dialog_id)) == needle:
                return dialog_id

        active_dialog = self.get_active_dialog()
        try:
            self.sync_dialog_storage(include_raw=False, include_callback_journal=True)
        except Exception:
            pass

        for button in buttons:
            dialog_id = int(getattr(button, "dialog_id", 0) or 0)
            if dialog_id == 0:
                continue
            history_texts = self._get_dialog_choice_history_texts(
                dialog_id,
                active_dialog=active_dialog,
                history_limit=history_limit,
            )
            for candidate in history_texts:
                if _normalize_dialog_choice_text(candidate) == needle:
                    return dialog_id
        return 0

    def send_active_dialog_choice_by_text(self, text: Optional[str]) -> bool:
        """Send the live visible choice whose label matches `text`."""
        dialog_id = self.get_active_dialog_choice_id_by_text(text)
        if dialog_id == 0:
            return False

        try:
            from .Player import Player
        except Exception:
            try:
                from Player import Player  # type: ignore
            except Exception:
                return False

        try:
            Player.SendDialog(dialog_id)
            return True
        except Exception:
            return False

    def send_active_dialog_choice_by_text_with_fallback(
        self,
        text: Optional[str],
        *,
        history_limit: int = 25,
    ) -> bool:
        """Send a choice by text using the fallback resolution path when needed."""
        dialog_id = self.get_active_dialog_choice_id_by_text_with_fallback(
            text,
            history_limit=history_limit,
        )
        if dialog_id == 0:
            return False

        try:
            from .Player import Player
        except Exception:
            try:
                from Player import Player  # type: ignore
            except Exception:
                return False

        try:
            Player.SendDialog(dialog_id)
            return True
        except Exception:
            return False

    def get_dialog_text_decoded(self, dialog_id: int) -> str:
        """Return decoded text for a dialog id using the catalog when available."""
        catalog = _get_dialog_catalog_widget()
        if catalog is not None:
            return catalog.get_dialog_text_decoded(dialog_id)
        return _sanitize_dialog_text(_call_native_dialog_method("get_dialog_text_decoded", "", dialog_id))

    def is_dialog_text_decode_pending(self, dialog_id: int) -> bool:
        """Return whether a dialog id is still waiting for decoded text."""
        catalog = _get_dialog_catalog_widget()
        if catalog is not None:
            return catalog.is_dialog_text_decode_pending(dialog_id)
        return bool(_call_native_dialog_method("is_dialog_text_decode_pending", False, dialog_id))

    def is_dialog_active(self) -> bool:
        """Return whether the game currently reports an active dialog screen."""
        return bool(_call_native_dialog_method("is_dialog_active", False))

    def is_dialog_displayed(self, dialog_id: int) -> bool:
        return bool(_call_native_dialog_method("is_dialog_displayed", False, dialog_id))

    def get_dialog_text_decode_status(self) -> List[DialogTextDecodedInfo]:
        """Return decode status rows for dialog ids currently known to the runtime/catalog."""
        catalog = _get_dialog_catalog_widget()
        if catalog is not None:
            return catalog.get_dialog_text_decode_status()
        native_list = _coerce_native_list(_call_native_dialog_method("get_dialog_text_decode_status", []))
        return [DialogTextDecodedInfo(item) for item in native_list]

    def is_dialog_available(self, dialog_id: int) -> bool:
        catalog = _get_dialog_catalog_widget()
        if catalog is not None:
            return catalog.is_dialog_available(dialog_id)
        return bool(_call_native_dialog_method("is_dialog_available", False, dialog_id))

    def get_dialog_info(self, dialog_id: int) -> Optional[DialogInfo]:
        """Return static metadata for a dialog id, not the live active dialog screen."""
        catalog = _get_dialog_catalog_widget()
        if catalog is not None:
            return catalog.get_dialog_info(dialog_id)
        native_info = _call_native_dialog_method("get_dialog_info", None, dialog_id)
        if native_info is None:
            return None
        return DialogInfo(native_info)

    def enumerate_available_dialogs(self) -> List[DialogInfo]:
        """Enumerate the currently available static dialog catalog entries."""
        catalog = _get_dialog_catalog_widget()
        if catalog is not None:
            return catalog.enumerate_available_dialogs()
        native_list = _coerce_native_list(_call_native_dialog_method("enumerate_available_dialogs", []))
        return [DialogInfo(item) for item in native_list]

    def get_dialog_event_logs(self) -> List:
        return _call_native_dialog_method("get_dialog_event_logs", [])

    def get_dialog_event_logs_received(self) -> List:
        return _call_native_dialog_method("get_dialog_event_logs_received", [])

    def get_dialog_event_logs_sent(self) -> List:
        return _call_native_dialog_method("get_dialog_event_logs_sent", [])

    def clear_dialog_event_logs(self) -> None:
        _call_native_dialog_method("clear_dialog_event_logs", None)

    def clear_dialog_event_logs_received(self) -> None:
        _call_native_dialog_method("clear_dialog_event_logs_received", None)

    def clear_dialog_event_logs_sent(self) -> None:
        _call_native_dialog_method("clear_dialog_event_logs_sent", None)

    def get_dialog_callback_journal(self) -> List[DialogCallbackJournalEntry]:
        """Return the full structured callback journal exposed by the native layer."""
        native_list = _coerce_native_list(_call_native_dialog_method("get_dialog_callback_journal", []))
        return [DialogCallbackJournalEntry(item) for item in native_list]

    def get_dialog_callback_journal_received(self) -> List[DialogCallbackJournalEntry]:
        native_list = _coerce_native_list(_call_native_dialog_method("get_dialog_callback_journal_received", []))
        return [DialogCallbackJournalEntry(item) for item in native_list]

    def get_dialog_callback_journal_sent(self) -> List[DialogCallbackJournalEntry]:
        native_list = _coerce_native_list(_call_native_dialog_method("get_dialog_callback_journal_sent", []))
        return [DialogCallbackJournalEntry(item) for item in native_list]

    def clear_dialog_callback_journal(self) -> None:
        _call_native_dialog_method("clear_dialog_callback_journal", None)

    def clear_dialog_callback_journal_received(self) -> None:
        _call_native_dialog_method("clear_dialog_callback_journal_received", None)

    def clear_dialog_callback_journal_sent(self) -> None:
        _call_native_dialog_method("clear_dialog_callback_journal_sent", None)

    def get_callback_journal(
        self,
        npc_uid: Optional[str] = None,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
    ) -> List[DialogCallbackJournalEntry]:
        """
        Return filtered callback journal entries from the live native journal buffer.

        Use this when you need recent structured callback events without touching
        the SQLite-backed persisted history.
        """
        incoming_filter = _normalize_direction_filter(direction)
        message_id_filter, event_type_filter = _parse_message_type_filter(message_type)
        npc_uid_filter = _normalize_npc_uid_filter(npc_uid)

        if incoming_filter is True:
            entries = self.get_dialog_callback_journal_received()
        elif incoming_filter is False:
            entries = self.get_dialog_callback_journal_sent()
        else:
            entries = self.get_dialog_callback_journal()

        out: List[DialogCallbackJournalEntry] = []
        for entry in entries:
            if npc_uid_filter and entry.npc_uid != npc_uid_filter:
                continue
            if message_id_filter is not None and entry.message_id != message_id_filter:
                continue
            if event_type_filter and entry.event_type.lower() != event_type_filter:
                continue
            out.append(entry)
        return out

    def clear_callback_journal(
        self,
        npc_uid: Optional[str] = None,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
    ) -> None:
        """
        Clear live callback journal entries using the best available native API.

        When filtered clear is unavailable natively, this method falls back to
        the older coarse clear behavior.
        """
        incoming_filter = _normalize_direction_filter(direction)
        message_id_filter, event_type_filter = _parse_message_type_filter(message_type)
        npc_uid_filter = _normalize_npc_uid_filter(npc_uid)

        # Fast path keeps backward-compatible clear behavior.
        if npc_uid_filter is None and message_id_filter is None and event_type_filter is None:
            if incoming_filter is True:
                self.clear_dialog_callback_journal_received()
                return
            if incoming_filter is False:
                self.clear_dialog_callback_journal_sent()
                return
            self.clear_dialog_callback_journal()
            return

        if PyDialog is None:
            return

        clearer = getattr(PyDialog.PyDialog, "clear_dialog_callback_journal_filtered", None)
        if callable(clearer):
            clearer(
                npc_uid_filter,
                incoming_filter,
                message_id_filter,
                event_type_filter,
            )
            return

        # Legacy fallback: if filtered clear is unavailable, keep behavior conservative.
        if incoming_filter is True:
            self.clear_dialog_callback_journal_received()
        elif incoming_filter is False:
            self.clear_dialog_callback_journal_sent()
        else:
            self.clear_dialog_callback_journal()

    def _get_step_pipeline(self):
        """Return the optional SQLite history pipeline instance if it is available."""
        if not callable(_get_dialog_step_pipeline):
            return None
        return _safe_call(None, _get_dialog_step_pipeline)

    def _call_step_pipeline_method(
        self,
        method_name: str,
        *,
        default: Any,
        sync: bool = False,
        sync_include_raw: bool = True,
        sync_include_callback_journal: bool = True,
        **kwargs: Any,
    ) -> Any:
        pipeline = self._get_step_pipeline()
        if pipeline is None:
            return default
        if sync:
            self.sync_dialog_storage(
                include_raw=sync_include_raw,
                include_callback_journal=sync_include_callback_journal,
            )
        method = getattr(pipeline, method_name, None)
        if not callable(method):
            return default
        return _safe_call(default, lambda: method(**kwargs))

    def configure_dialog_storage(
        self,
        *,
        db_path: Optional[str] = None,
        step_timeout_ms: Optional[int] = None,
    ) -> str:
        """Configure the SQLite-backed dialog step pipeline and return its DB path."""
        return str(
            self._call_step_pipeline_method(
                "configure",
                default="",
                db_path=db_path,
                step_timeout_ms=step_timeout_ms,
            )
        )

    def get_dialog_storage_path(self) -> str:
        """Return the configured SQLite database path for persisted dialog history."""
        return str(self._call_step_pipeline_method("get_db_path", default=""))

    def sync_dialog_storage(
        self,
        *,
        include_raw: bool = True,
        include_callback_journal: bool = True,
    ) -> Dict[str, int]:
        """
        Snapshot the live native logs into the SQLite-backed persisted dialog store.

        The returned counters are useful for monitors and maintenance scripts that
        want to know how many rows were inserted/finalized during the sync.
        """
        pipeline = self._get_step_pipeline()
        if pipeline is None:
            return {"raw_inserted": 0, "journal_inserted": 0, "steps_finalized": 0}
        # Sync is snapshot-based: pull the current native in-memory logs, let the pipeline
        # deduplicate/finalize them, then query persisted state separately.
        raw_events = self.get_dialog_event_logs() if include_raw else None
        callback_journal = self.get_dialog_callback_journal() if include_callback_journal else None
        return _safe_call(
            {"raw_inserted": 0, "journal_inserted": 0, "steps_finalized": 0},
            lambda: pipeline.sync(raw_events=raw_events, callback_journal=callback_journal),
        )

    def flush_dialog_storage(self) -> int:
        """Force any pending in-memory dialog steps to be finalized into SQLite."""
        return int(self._call_step_pipeline_method("flush_pending", default=0) or 0)

    def get_persisted_raw_callbacks(
        self,
        *,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
        limit: int = 200,
        offset: int = 0,
        sync: bool = True,
    ) -> List[Dict[str, Any]]:
        """Query persisted raw callback rows from the SQLite dialog store."""
        return list(
            self._call_step_pipeline_method(
                "get_raw_callbacks",
                default=[],
                sync=sync,
                direction=direction,
                message_type=message_type,
                limit=limit,
                offset=offset,
            )
        )

    def clear_persisted_raw_callbacks(
        self,
        *,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
    ) -> int:
        return int(
            self._call_step_pipeline_method(
                "clear_raw_callbacks",
                default=0,
                direction=direction,
                message_type=message_type,
            )
            or 0
        )

    def get_persisted_callback_journal(
        self,
        *,
        npc_uid: Optional[str] = None,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
        limit: int = 200,
        offset: int = 0,
        sync: bool = True,
    ) -> List[Dict[str, Any]]:
        """Query persisted structured callback journal rows from SQLite."""
        return list(
            self._call_step_pipeline_method(
                "get_callback_journal",
                default=[],
                sync=sync,
                npc_uid=npc_uid,
                direction=direction,
                message_type=message_type,
                limit=limit,
                offset=offset,
            )
        )

    def clear_persisted_callback_journal(
        self,
        *,
        npc_uid: Optional[str] = None,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
    ) -> int:
        return int(
            self._call_step_pipeline_method(
                "clear_callback_journal",
                default=0,
                npc_uid=npc_uid,
                direction=direction,
                message_type=message_type,
            )
            or 0
        )

    def get_dialog_steps(
        self,
        *,
        map_id: Optional[int] = None,
        npc_uid_instance: Optional[str] = None,
        npc_uid_archetype: Optional[str] = None,
        body_dialog_id: Optional[int] = None,
        choice_dialog_id: Optional[int] = None,
        limit: int = 200,
        offset: int = 0,
        include_choices: bool = True,
        sync: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Query persisted dialog steps from SQLite with optional filtering.

        A dialog step is one body screen plus the offered choices and any choice
        selected before the next body, timeout, or map change.
        """
        # Most callers want fresh persisted history by default. Hot UI paths can pass sync=False
        # when they already called `sync_dialog_storage()` for the current frame/tick.
        return list(
            self._call_step_pipeline_method(
                "get_dialog_steps",
                default=[],
                sync=sync,
                map_id=map_id,
                npc_uid_instance=npc_uid_instance,
                npc_uid_archetype=npc_uid_archetype,
                body_dialog_id=body_dialog_id,
                choice_dialog_id=choice_dialog_id,
                limit=limit,
                offset=offset,
                include_choices=include_choices,
            )
        )

    def get_dialog_step(
        self, step_id: int, *, include_choices: bool = True, sync: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Return one persisted dialog step by id."""
        result = self._call_step_pipeline_method(
            "get_dialog_step",
            default=None,
            sync=sync,
            step_id=int(step_id),
            include_choices=include_choices,
        )
        return result if isinstance(result, dict) else None

    def get_dialog_steps_by_map(
        self,
        map_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
        include_choices: bool = True,
        sync: bool = True,
    ) -> List[Dict[str, Any]]:
        return self.get_dialog_steps(
            map_id=int(map_id),
            limit=limit,
            offset=offset,
            include_choices=include_choices,
            sync=sync,
        )

    def get_dialog_steps_by_npc_archetype(
        self,
        npc_uid_archetype: str,
        *,
        limit: int = 200,
        offset: int = 0,
        include_choices: bool = True,
        sync: bool = True,
    ) -> List[Dict[str, Any]]:
        return self.get_dialog_steps(
            npc_uid_archetype=npc_uid_archetype,
            limit=limit,
            offset=offset,
            include_choices=include_choices,
            sync=sync,
        )

    def get_dialog_steps_by_body_dialog_id(
        self,
        body_dialog_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
        include_choices: bool = True,
        sync: bool = True,
    ) -> List[Dict[str, Any]]:
        return self.get_dialog_steps(
            body_dialog_id=int(body_dialog_id),
            limit=limit,
            offset=offset,
            include_choices=include_choices,
            sync=sync,
        )

    def get_dialog_steps_by_choice_dialog_id(
        self,
        choice_dialog_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
        include_choices: bool = True,
        sync: bool = True,
    ) -> List[Dict[str, Any]]:
        return self.get_dialog_steps(
            choice_dialog_id=int(choice_dialog_id),
            limit=limit,
            offset=offset,
            include_choices=include_choices,
            sync=sync,
        )

    def get_dialog_choices(self, step_id: int, *, sync: bool = True) -> List[Dict[str, Any]]:
        """Return the persisted choice rows that belong to a dialog step."""
        return list(
            self._call_step_pipeline_method(
                "get_dialog_choices",
                default=[],
                sync=sync,
                step_id=int(step_id),
            )
        )

    def export_raw_callbacks_json(
        self,
        path: str,
        *,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
        limit: int = 10000,
        offset: int = 0,
        sync: bool = True,
    ) -> int:
        return int(
            self._call_step_pipeline_method(
                "export_raw_callbacks_json",
                default=0,
                sync=sync,
                path=path,
                direction=direction,
                message_type=message_type,
                limit=limit,
                offset=offset,
            )
            or 0
        )

    def export_callback_journal_json(
        self,
        path: str,
        *,
        npc_uid: Optional[str] = None,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
        limit: int = 10000,
        offset: int = 0,
        sync: bool = True,
    ) -> int:
        return int(
            self._call_step_pipeline_method(
                "export_callback_journal_json",
                default=0,
                sync=sync,
                path=path,
                npc_uid=npc_uid,
                direction=direction,
                message_type=message_type,
                limit=limit,
                offset=offset,
            )
            or 0
        )

    def export_dialog_steps_json(
        self,
        path: str,
        *,
        map_id: Optional[int] = None,
        npc_uid_instance: Optional[str] = None,
        npc_uid_archetype: Optional[str] = None,
        body_dialog_id: Optional[int] = None,
        choice_dialog_id: Optional[int] = None,
        limit: int = 5000,
        offset: int = 0,
        sync: bool = True,
    ) -> int:
        """Export persisted dialog steps to JSON and return the exported row count."""
        return int(
            self._call_step_pipeline_method(
                "export_dialog_steps_json",
                default=0,
                sync=sync,
                path=path,
                map_id=map_id,
                npc_uid_instance=npc_uid_instance,
                npc_uid_archetype=npc_uid_archetype,
                body_dialog_id=body_dialog_id,
                choice_dialog_id=choice_dialog_id,
                limit=limit,
                offset=offset,
            )
            or 0
        )

    def prune_dialog_logs(
        self,
        *,
        max_raw_rows: Optional[int] = None,
        max_journal_rows: Optional[int] = None,
        max_step_rows: Optional[int] = None,
        older_than_days: Optional[float] = None,
    ) -> Dict[str, int]:
        """Prune persisted raw, journal, and step rows from the SQLite store."""
        return dict(
            self._call_step_pipeline_method(
                "prune_dialog_logs",
                default={
                    "removed_raw_callbacks": 0,
                    "removed_callback_journal": 0,
                    "removed_dialog_steps": 0,
                    "removed_dialog_choices": 0,
                },
                max_raw_rows=max_raw_rows,
                max_journal_rows=max_journal_rows,
                max_step_rows=max_step_rows,
                older_than_days=older_than_days,
            )
        )

    def get_dialog_diagnostics(
        self,
        *,
        map_id: Optional[int] = None,
        npc_uid_instance: Optional[str] = None,
        npc_uid_archetype: Optional[str] = None,
        body_dialog_id: Optional[int] = None,
        choice_dialog_id: Optional[int] = None,
        limit: int = 200,
        offset: int = 0,
        sync: bool = True,
        max_issues: int = 250,
    ) -> Dict[str, Any]:
        """Run lightweight diagnostics over persisted dialog history rows."""
        steps = self.get_dialog_steps(
            map_id=map_id,
            npc_uid_instance=npc_uid_instance,
            npc_uid_archetype=npc_uid_archetype,
            body_dialog_id=body_dialog_id,
            choice_dialog_id=choice_dialog_id,
            limit=limit,
            offset=offset,
            include_choices=True,
            sync=sync,
        )
        return _analyze_dialog_steps(steps, max_issues=max_issues)

_dialog_widget_instance: Optional[DialogWidget] = None


# Module-level convenience wrappers.
def get_dialog_widget() -> DialogWidget:
    global _dialog_widget_instance
    if _dialog_widget_instance is None:
        # Keep a single widget wrapper so module-level helpers share the same lazy-initialized
        # native/catalog/pipeline access path instead of each call re-building state.
        _dialog_widget_instance = DialogWidget()
    return _dialog_widget_instance


def get_active_dialog() -> Optional[ActiveDialogInfo]:
    return get_dialog_widget().get_active_dialog()


def get_active_dialog_buttons() -> List[DialogButtonInfo]:
    return get_dialog_widget().get_active_dialog_buttons()


def get_last_selected_dialog_id() -> int:
    return get_dialog_widget().get_last_selected_dialog_id()


def get_active_dialog_choice_id_by_text(text: Optional[str]) -> int:
    return get_dialog_widget().get_active_dialog_choice_id_by_text(text)


def send_active_dialog_choice_by_text(text: Optional[str]) -> bool:
    return get_dialog_widget().send_active_dialog_choice_by_text(text)


def get_active_dialog_choice_id_by_text_with_fallback(
    text: Optional[str],
    *,
    history_limit: int = 25,
) -> int:
    return get_dialog_widget().get_active_dialog_choice_id_by_text_with_fallback(
        text,
        history_limit=history_limit,
    )


def send_active_dialog_choice_by_text_with_fallback(
    text: Optional[str],
    *,
    history_limit: int = 25,
) -> bool:
    return get_dialog_widget().send_active_dialog_choice_by_text_with_fallback(
        text,
        history_limit=history_limit,
    )


def get_dialog_text_decoded(dialog_id: int) -> str:
    return get_dialog_widget().get_dialog_text_decoded(dialog_id)


def is_dialog_text_decode_pending(dialog_id: int) -> bool:
    return get_dialog_widget().is_dialog_text_decode_pending(dialog_id)


def is_dialog_active() -> bool:
    return get_dialog_widget().is_dialog_active()


def is_dialog_displayed(dialog_id: int) -> bool:
    return get_dialog_widget().is_dialog_displayed(dialog_id)


def get_dialog_text_decode_status() -> List[DialogTextDecodedInfo]:
    return get_dialog_widget().get_dialog_text_decode_status()


def is_dialog_available(dialog_id: int) -> bool:
    return get_dialog_widget().is_dialog_available(dialog_id)


def get_dialog_info(dialog_id: int) -> Optional[DialogInfo]:
    return get_dialog_widget().get_dialog_info(dialog_id)


def enumerate_available_dialogs() -> List[DialogInfo]:
    return get_dialog_widget().enumerate_available_dialogs()


def get_dialog_event_logs() -> List:
    return get_dialog_widget().get_dialog_event_logs()


def get_dialog_event_logs_received() -> List:
    return get_dialog_widget().get_dialog_event_logs_received()


def get_dialog_event_logs_sent() -> List:
    return get_dialog_widget().get_dialog_event_logs_sent()


def clear_dialog_event_logs() -> None:
    get_dialog_widget().clear_dialog_event_logs()


def clear_dialog_event_logs_received() -> None:
    get_dialog_widget().clear_dialog_event_logs_received()


def clear_dialog_event_logs_sent() -> None:
    get_dialog_widget().clear_dialog_event_logs_sent()


def get_dialog_callback_journal() -> List[DialogCallbackJournalEntry]:
    return get_dialog_widget().get_dialog_callback_journal()


def get_dialog_callback_journal_received() -> List[DialogCallbackJournalEntry]:
    return get_dialog_widget().get_dialog_callback_journal_received()


def get_dialog_callback_journal_sent() -> List[DialogCallbackJournalEntry]:
    return get_dialog_widget().get_dialog_callback_journal_sent()


def clear_dialog_callback_journal() -> None:
    get_dialog_widget().clear_dialog_callback_journal()


def clear_dialog_callback_journal_received() -> None:
    get_dialog_widget().clear_dialog_callback_journal_received()


def clear_dialog_callback_journal_sent() -> None:
    get_dialog_widget().clear_dialog_callback_journal_sent()


def get_callback_journal(
    npc_uid: Optional[str] = None,
    direction: Optional[str] = "all",
    message_type: Optional[Any] = None,
) -> List[DialogCallbackJournalEntry]:
    return get_dialog_widget().get_callback_journal(
        npc_uid=npc_uid,
        direction=direction,
        message_type=message_type,
    )


def clear_callback_journal(
    npc_uid: Optional[str] = None,
    direction: Optional[str] = "all",
    message_type: Optional[Any] = None,
) -> None:
    get_dialog_widget().clear_callback_journal(
        npc_uid=npc_uid,
        direction=direction,
        message_type=message_type,
    )


def configure_dialog_storage(
    *,
    db_path: Optional[str] = None,
    step_timeout_ms: Optional[int] = None,
) -> str:
    return get_dialog_widget().configure_dialog_storage(
        db_path=db_path,
        step_timeout_ms=step_timeout_ms,
    )


def get_dialog_storage_path() -> str:
    return get_dialog_widget().get_dialog_storage_path()


def sync_dialog_storage(
    *,
    include_raw: bool = True,
    include_callback_journal: bool = True,
) -> Dict[str, int]:
    return get_dialog_widget().sync_dialog_storage(
        include_raw=include_raw,
        include_callback_journal=include_callback_journal,
    )


def flush_dialog_storage() -> int:
    return get_dialog_widget().flush_dialog_storage()


def get_persisted_raw_callbacks(
    *,
    direction: Optional[str] = "all",
    message_type: Optional[Any] = None,
    limit: int = 200,
    offset: int = 0,
    sync: bool = True,
) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_persisted_raw_callbacks(
        direction=direction,
        message_type=message_type,
        limit=limit,
        offset=offset,
        sync=sync,
    )


def clear_persisted_raw_callbacks(
    *,
    direction: Optional[str] = "all",
    message_type: Optional[Any] = None,
) -> int:
    return get_dialog_widget().clear_persisted_raw_callbacks(
        direction=direction,
        message_type=message_type,
    )


def get_persisted_callback_journal(
    *,
    npc_uid: Optional[str] = None,
    direction: Optional[str] = "all",
    message_type: Optional[Any] = None,
    limit: int = 200,
    offset: int = 0,
    sync: bool = True,
) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_persisted_callback_journal(
        npc_uid=npc_uid,
        direction=direction,
        message_type=message_type,
        limit=limit,
        offset=offset,
        sync=sync,
    )


def clear_persisted_callback_journal(
    *,
    npc_uid: Optional[str] = None,
    direction: Optional[str] = "all",
    message_type: Optional[Any] = None,
) -> int:
    return get_dialog_widget().clear_persisted_callback_journal(
        npc_uid=npc_uid,
        direction=direction,
        message_type=message_type,
    )


def get_dialog_steps(
    *,
    map_id: Optional[int] = None,
    npc_uid_instance: Optional[str] = None,
    npc_uid_archetype: Optional[str] = None,
    body_dialog_id: Optional[int] = None,
    choice_dialog_id: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
    include_choices: bool = True,
    sync: bool = True,
) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_steps(
        map_id=map_id,
        npc_uid_instance=npc_uid_instance,
        npc_uid_archetype=npc_uid_archetype,
        body_dialog_id=body_dialog_id,
        choice_dialog_id=choice_dialog_id,
        limit=limit,
        offset=offset,
        include_choices=include_choices,
        sync=sync,
    )


def get_dialog_step(step_id: int, *, include_choices: bool = True, sync: bool = True) -> Optional[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_step(
        step_id=step_id,
        include_choices=include_choices,
        sync=sync,
    )


def get_dialog_steps_by_map(
    map_id: int,
    *,
    limit: int = 200,
    offset: int = 0,
    include_choices: bool = True,
    sync: bool = True,
) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_steps_by_map(
        map_id=map_id,
        limit=limit,
        offset=offset,
        include_choices=include_choices,
        sync=sync,
    )


def get_dialog_steps_by_npc_archetype(
    npc_uid_archetype: str,
    *,
    limit: int = 200,
    offset: int = 0,
    include_choices: bool = True,
    sync: bool = True,
) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_steps_by_npc_archetype(
        npc_uid_archetype=npc_uid_archetype,
        limit=limit,
        offset=offset,
        include_choices=include_choices,
        sync=sync,
    )


def get_dialog_steps_by_body_dialog_id(
    body_dialog_id: int,
    *,
    limit: int = 200,
    offset: int = 0,
    include_choices: bool = True,
    sync: bool = True,
) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_steps_by_body_dialog_id(
        body_dialog_id=body_dialog_id,
        limit=limit,
        offset=offset,
        include_choices=include_choices,
        sync=sync,
    )


def get_dialog_steps_by_choice_dialog_id(
    choice_dialog_id: int,
    *,
    limit: int = 200,
    offset: int = 0,
    include_choices: bool = True,
    sync: bool = True,
) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_steps_by_choice_dialog_id(
        choice_dialog_id=choice_dialog_id,
        limit=limit,
        offset=offset,
        include_choices=include_choices,
        sync=sync,
    )


def get_dialog_choices(step_id: int, *, sync: bool = True) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_choices(step_id=step_id, sync=sync)


def export_raw_callbacks_json(
    path: str,
    *,
    direction: Optional[str] = "all",
    message_type: Optional[Any] = None,
    limit: int = 10000,
    offset: int = 0,
    sync: bool = True,
) -> int:
    return get_dialog_widget().export_raw_callbacks_json(
        path=path,
        direction=direction,
        message_type=message_type,
        limit=limit,
        offset=offset,
        sync=sync,
    )


def export_callback_journal_json(
    path: str,
    *,
    npc_uid: Optional[str] = None,
    direction: Optional[str] = "all",
    message_type: Optional[Any] = None,
    limit: int = 10000,
    offset: int = 0,
    sync: bool = True,
) -> int:
    return get_dialog_widget().export_callback_journal_json(
        path=path,
        npc_uid=npc_uid,
        direction=direction,
        message_type=message_type,
        limit=limit,
        offset=offset,
        sync=sync,
    )


def export_dialog_steps_json(
    path: str,
    *,
    map_id: Optional[int] = None,
    npc_uid_instance: Optional[str] = None,
    npc_uid_archetype: Optional[str] = None,
    body_dialog_id: Optional[int] = None,
    choice_dialog_id: Optional[int] = None,
    limit: int = 5000,
    offset: int = 0,
    sync: bool = True,
) -> int:
    return get_dialog_widget().export_dialog_steps_json(
        path=path,
        map_id=map_id,
        npc_uid_instance=npc_uid_instance,
        npc_uid_archetype=npc_uid_archetype,
        body_dialog_id=body_dialog_id,
        choice_dialog_id=choice_dialog_id,
        limit=limit,
        offset=offset,
        sync=sync,
    )


def prune_dialog_logs(
    *,
    max_raw_rows: Optional[int] = None,
    max_journal_rows: Optional[int] = None,
    max_step_rows: Optional[int] = None,
    older_than_days: Optional[float] = None,
) -> Dict[str, int]:
    return get_dialog_widget().prune_dialog_logs(
        max_raw_rows=max_raw_rows,
        max_journal_rows=max_journal_rows,
        max_step_rows=max_step_rows,
        older_than_days=older_than_days,
    )


def get_dialog_diagnostics(
    *,
    map_id: Optional[int] = None,
    npc_uid_instance: Optional[str] = None,
    npc_uid_archetype: Optional[str] = None,
    body_dialog_id: Optional[int] = None,
    choice_dialog_id: Optional[int] = None,
    limit: int = 200,
    offset: int = 0,
    sync: bool = True,
    max_issues: int = 250,
) -> Dict[str, Any]:
    return get_dialog_widget().get_dialog_diagnostics(
        map_id=map_id,
        npc_uid_instance=npc_uid_instance,
        npc_uid_archetype=npc_uid_archetype,
        body_dialog_id=body_dialog_id,
        choice_dialog_id=choice_dialog_id,
        limit=limit,
        offset=offset,
        sync=sync,
        max_issues=max_issues,
    )
