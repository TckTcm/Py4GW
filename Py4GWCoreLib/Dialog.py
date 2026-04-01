"""
Core Dialog wrapper for the native PyDialog C++ module.
This module provides dialog access helpers for use by widgets or scripts.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from .dialog_turn_pipeline import get_dialog_turn_pipeline as _get_dialog_turn_pipeline
except Exception:
    try:
        from dialog_turn_pipeline import get_dialog_turn_pipeline as _get_dialog_turn_pipeline  # type: ignore
    except Exception:
        _get_dialog_turn_pipeline = None

MAX_DIALOG_ID = 0x39

try:
    import PyDialog
except Exception as exc:  # pragma: no cover - runtime environment specific
    PyDialog = None
    _PYDIALOG_IMPORT_ERROR = exc
else:
    _PYDIALOG_IMPORT_ERROR = None


def _get_dialog_catalog_widget():
    try:
        from .DialogCatalog import get_dialog_catalog_widget as _factory
    except Exception:
        try:
            from DialogCatalog import get_dialog_catalog_widget as _factory  # type: ignore
        except Exception:
            return None
    try:
        return _factory()
    except Exception:
        return None


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
    if not value:
        return ""
    text = str(value)
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
    turn_id: int = 0,
    dialog_id: int = 0,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "severity": severity,
        "rule": rule,
        "message": message,
        "npc_uid": npc_uid,
        "turn_id": int(turn_id),
        "dialog_id": int(dialog_id),
        "details": details or {},
    }


def _analyze_dialog_turns(
    turns: List[Dict[str, Any]],
    *,
    max_issues: int = 250,
) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []

    for turn in turns:
        turn_id = _as_int(turn.get("id", 0), 0)
        npc_uid = _as_text(turn.get("npc_uid_instance", "")).strip()
        body_dialog_id = _as_int(turn.get("body_dialog_id", 0), 0)
        selected_dialog_id = _as_int(turn.get("selected_dialog_id", 0), 0)
        finalized_reason = _as_text(turn.get("finalized_reason", "")).strip().lower()
        body_text = _as_text(turn.get("body_text_raw", ""))
        choices = list(turn.get("choices", []) or [])

        if body_dialog_id == 0 and choices:
            issues.append(
                _build_diag_issue(
                    severity="warning",
                    rule="orphan_choices_without_body",
                    message="Turn has choices but no body dialog id.",
                    npc_uid=npc_uid,
                    turn_id=turn_id,
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
                    turn_id=turn_id,
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
                    turn_id=turn_id,
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
                    message="Selected dialog id is not present in the offered choices for this turn.",
                    npc_uid=npc_uid,
                    turn_id=turn_id,
                    dialog_id=selected_dialog_id,
                    details={"offered_choice_ids": choice_ids},
                )
            )

    issues.sort(
        key=lambda issue: (
            _DIAG_SEVERITY_ORDER.get(_as_text(issue.get("severity", "info")).lower(), 99),
            -_as_int(issue.get("turn_id", 0), 0),
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
        "analyzed_turns": len(turns),
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


def _parse_inline_choice_dialog_id(raw_value: Any) -> int:
    value = str(raw_value or "").strip()
    if not value:
        return 0
    try:
        return int(value, 0)
    except Exception:
        return 0


def _extract_inline_dialog_choices_from_text(body_text: Optional[str]) -> List[DialogButtonInfo]:
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
    """High-level wrapper around the native PyDialog module."""

    def __init__(self) -> None:
        self._initialized = False

    def initialize(self) -> bool:
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
        if PyDialog is None:
            return
        try:
            PyDialog.PyDialog.terminate()
        finally:
            self._initialized = False

    def get_active_dialog(self) -> Optional[ActiveDialogInfo]:
        if PyDialog is None:
            return None
        native_info = PyDialog.PyDialog.get_active_dialog()
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
        if PyDialog is None:
            return []
        native_list = PyDialog.PyDialog.get_active_dialog_buttons()
        buttons = [DialogButtonInfo(item) for item in native_list]
        if buttons:
            return buttons
        native_active = PyDialog.PyDialog.get_active_dialog()
        return extract_inline_dialog_choices_from_active(native_active)

    def get_last_selected_dialog_id(self) -> int:
        if PyDialog is None:
            return 0
        return PyDialog.PyDialog.get_last_selected_dialog_id()

    def get_dialog_text_decoded(self, dialog_id: int) -> str:
        catalog = _get_dialog_catalog_widget()
        if catalog is not None:
            return catalog.get_dialog_text_decoded(dialog_id)
        if PyDialog is None:
            return ""
        return _sanitize_dialog_text(PyDialog.PyDialog.get_dialog_text_decoded(dialog_id))

    def is_dialog_text_decode_pending(self, dialog_id: int) -> bool:
        catalog = _get_dialog_catalog_widget()
        if catalog is not None:
            return catalog.is_dialog_text_decode_pending(dialog_id)
        if PyDialog is None:
            return False
        return PyDialog.PyDialog.is_dialog_text_decode_pending(dialog_id)

    def is_dialog_active(self) -> bool:
        if PyDialog is None:
            return False
        return bool(PyDialog.PyDialog.is_dialog_active())

    def is_dialog_displayed(self, dialog_id: int) -> bool:
        if PyDialog is None:
            return False
        return PyDialog.PyDialog.is_dialog_displayed(dialog_id)

    def get_dialog_text_decode_status(self) -> List[DialogTextDecodedInfo]:
        catalog = _get_dialog_catalog_widget()
        if catalog is not None:
            return catalog.get_dialog_text_decode_status()
        if PyDialog is None:
            return []
        native_list = PyDialog.PyDialog.get_dialog_text_decode_status()
        return [DialogTextDecodedInfo(item) for item in native_list]

    def is_dialog_available(self, dialog_id: int) -> bool:
        catalog = _get_dialog_catalog_widget()
        if catalog is not None:
            return catalog.is_dialog_available(dialog_id)
        if PyDialog is None:
            return False
        return PyDialog.PyDialog.is_dialog_available(dialog_id)

    def get_dialog_info(self, dialog_id: int) -> Optional[DialogInfo]:
        catalog = _get_dialog_catalog_widget()
        if catalog is not None:
            return catalog.get_dialog_info(dialog_id)
        if PyDialog is None:
            return None
        native_info = PyDialog.PyDialog.get_dialog_info(dialog_id)
        return DialogInfo(native_info)

    def enumerate_available_dialogs(self) -> List[DialogInfo]:
        catalog = _get_dialog_catalog_widget()
        if catalog is not None:
            return catalog.enumerate_available_dialogs()
        if PyDialog is None:
            return []
        native_list = PyDialog.PyDialog.enumerate_available_dialogs()
        return [DialogInfo(item) for item in native_list]

    def get_dialog_event_logs(self) -> List:
        if PyDialog is None:
            return []
        return PyDialog.PyDialog.get_dialog_event_logs()

    def get_dialog_event_logs_received(self) -> List:
        if PyDialog is None:
            return []
        return PyDialog.PyDialog.get_dialog_event_logs_received()

    def get_dialog_event_logs_sent(self) -> List:
        if PyDialog is None:
            return []
        return PyDialog.PyDialog.get_dialog_event_logs_sent()

    def clear_dialog_event_logs(self) -> None:
        if PyDialog is None:
            return
        PyDialog.PyDialog.clear_dialog_event_logs()

    def clear_dialog_event_logs_received(self) -> None:
        if PyDialog is None:
            return
        PyDialog.PyDialog.clear_dialog_event_logs_received()

    def clear_dialog_event_logs_sent(self) -> None:
        if PyDialog is None:
            return
        PyDialog.PyDialog.clear_dialog_event_logs_sent()

    def get_dialog_callback_journal(self) -> List[DialogCallbackJournalEntry]:
        if PyDialog is None:
            return []
        getter = getattr(PyDialog.PyDialog, "get_dialog_callback_journal", None)
        if not callable(getter):
            return []
        native_list = getter()
        return [DialogCallbackJournalEntry(item) for item in native_list]

    def get_dialog_callback_journal_received(self) -> List[DialogCallbackJournalEntry]:
        if PyDialog is None:
            return []
        getter = getattr(PyDialog.PyDialog, "get_dialog_callback_journal_received", None)
        if not callable(getter):
            return []
        native_list = getter()
        return [DialogCallbackJournalEntry(item) for item in native_list]

    def get_dialog_callback_journal_sent(self) -> List[DialogCallbackJournalEntry]:
        if PyDialog is None:
            return []
        getter = getattr(PyDialog.PyDialog, "get_dialog_callback_journal_sent", None)
        if not callable(getter):
            return []
        native_list = getter()
        return [DialogCallbackJournalEntry(item) for item in native_list]

    def clear_dialog_callback_journal(self) -> None:
        if PyDialog is None:
            return
        clearer = getattr(PyDialog.PyDialog, "clear_dialog_callback_journal", None)
        if callable(clearer):
            clearer()

    def clear_dialog_callback_journal_received(self) -> None:
        if PyDialog is None:
            return
        clearer = getattr(PyDialog.PyDialog, "clear_dialog_callback_journal_received", None)
        if callable(clearer):
            clearer()

    def clear_dialog_callback_journal_sent(self) -> None:
        if PyDialog is None:
            return
        clearer = getattr(PyDialog.PyDialog, "clear_dialog_callback_journal_sent", None)
        if callable(clearer):
            clearer()

    def get_callback_journal(
        self,
        npc_uid: Optional[str] = None,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
    ) -> List[DialogCallbackJournalEntry]:
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

    def _get_turn_pipeline(self):
        if _get_dialog_turn_pipeline is None:
            return None
        try:
            return _get_dialog_turn_pipeline()
        except Exception:
            return None

    def configure_dialog_storage(
        self,
        *,
        db_path: Optional[str] = None,
        turn_timeout_ms: Optional[int] = None,
    ) -> str:
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return ""
        try:
            return pipeline.configure(db_path=db_path, turn_timeout_ms=turn_timeout_ms)
        except Exception:
            return ""

    def get_dialog_storage_path(self) -> str:
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return ""
        try:
            return pipeline.get_db_path()
        except Exception:
            return ""

    def sync_dialog_storage(
        self,
        *,
        include_raw: bool = True,
        include_callback_journal: bool = True,
    ) -> Dict[str, int]:
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return {"raw_inserted": 0, "journal_inserted": 0, "turns_finalized": 0}
        raw_events = self.get_dialog_event_logs() if include_raw else None
        callback_journal = self.get_dialog_callback_journal() if include_callback_journal else None
        try:
            return pipeline.sync(raw_events=raw_events, callback_journal=callback_journal)
        except Exception:
            return {"raw_inserted": 0, "journal_inserted": 0, "turns_finalized": 0}

    def flush_dialog_storage(self) -> int:
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return 0
        try:
            return int(pipeline.flush_pending())
        except Exception:
            return 0

    def get_persisted_raw_callbacks(
        self,
        *,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
        limit: int = 200,
        offset: int = 0,
        sync: bool = True,
    ) -> List[Dict[str, Any]]:
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return []
        if sync:
            self.sync_dialog_storage()
        try:
            return pipeline.get_raw_callbacks(
                direction=direction,
                message_type=message_type,
                limit=limit,
                offset=offset,
            )
        except Exception:
            return []

    def clear_persisted_raw_callbacks(
        self,
        *,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
    ) -> int:
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return 0
        try:
            return int(
                pipeline.clear_raw_callbacks(
                    direction=direction,
                    message_type=message_type,
                )
            )
        except Exception:
            return 0

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
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return []
        if sync:
            self.sync_dialog_storage()
        try:
            return pipeline.get_callback_journal(
                npc_uid=npc_uid,
                direction=direction,
                message_type=message_type,
                limit=limit,
                offset=offset,
            )
        except Exception:
            return []

    def clear_persisted_callback_journal(
        self,
        *,
        npc_uid: Optional[str] = None,
        direction: Optional[str] = "all",
        message_type: Optional[Any] = None,
    ) -> int:
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return 0
        try:
            return int(
                pipeline.clear_callback_journal(
                    npc_uid=npc_uid,
                    direction=direction,
                    message_type=message_type,
                )
            )
        except Exception:
            return 0

    def get_dialog_turns(
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
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return []
        if sync:
            self.sync_dialog_storage()
        try:
            return pipeline.get_dialog_turns(
                map_id=map_id,
                npc_uid_instance=npc_uid_instance,
                npc_uid_archetype=npc_uid_archetype,
                body_dialog_id=body_dialog_id,
                choice_dialog_id=choice_dialog_id,
                limit=limit,
                offset=offset,
                include_choices=include_choices,
            )
        except Exception:
            return []

    def get_dialog_turn(
        self, turn_id: int, *, include_choices: bool = True, sync: bool = True
    ) -> Optional[Dict[str, Any]]:
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return None
        if sync:
            self.sync_dialog_storage()
        try:
            return pipeline.get_dialog_turn(turn_id=int(turn_id), include_choices=include_choices)
        except Exception:
            return None

    def get_dialog_turns_by_map(
        self,
        map_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
        include_choices: bool = True,
        sync: bool = True,
    ) -> List[Dict[str, Any]]:
        return self.get_dialog_turns(
            map_id=int(map_id),
            limit=limit,
            offset=offset,
            include_choices=include_choices,
            sync=sync,
        )

    def get_dialog_turns_by_npc_archetype(
        self,
        npc_uid_archetype: str,
        *,
        limit: int = 200,
        offset: int = 0,
        include_choices: bool = True,
        sync: bool = True,
    ) -> List[Dict[str, Any]]:
        return self.get_dialog_turns(
            npc_uid_archetype=npc_uid_archetype,
            limit=limit,
            offset=offset,
            include_choices=include_choices,
            sync=sync,
        )

    def get_dialog_turns_by_body_dialog_id(
        self,
        body_dialog_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
        include_choices: bool = True,
        sync: bool = True,
    ) -> List[Dict[str, Any]]:
        return self.get_dialog_turns(
            body_dialog_id=int(body_dialog_id),
            limit=limit,
            offset=offset,
            include_choices=include_choices,
            sync=sync,
        )

    def get_dialog_turns_by_choice_dialog_id(
        self,
        choice_dialog_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
        include_choices: bool = True,
        sync: bool = True,
    ) -> List[Dict[str, Any]]:
        return self.get_dialog_turns(
            choice_dialog_id=int(choice_dialog_id),
            limit=limit,
            offset=offset,
            include_choices=include_choices,
            sync=sync,
        )

    def get_dialog_choices(self, turn_id: int, *, sync: bool = True) -> List[Dict[str, Any]]:
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return []
        if sync:
            self.sync_dialog_storage()
        try:
            return pipeline.get_dialog_choices(turn_id=int(turn_id))
        except Exception:
            return []

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
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return 0
        if sync:
            self.sync_dialog_storage()
        try:
            return int(
                pipeline.export_raw_callbacks_json(
                    path=path,
                    direction=direction,
                    message_type=message_type,
                    limit=limit,
                    offset=offset,
                )
            )
        except Exception:
            return 0

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
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return 0
        if sync:
            self.sync_dialog_storage()
        try:
            return int(
                pipeline.export_callback_journal_json(
                    path=path,
                    npc_uid=npc_uid,
                    direction=direction,
                    message_type=message_type,
                    limit=limit,
                    offset=offset,
                )
            )
        except Exception:
            return 0

    def export_dialog_turns_json(
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
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return 0
        if sync:
            self.sync_dialog_storage()
        try:
            return int(
                pipeline.export_dialog_turns_json(
                    path=path,
                    map_id=map_id,
                    npc_uid_instance=npc_uid_instance,
                    npc_uid_archetype=npc_uid_archetype,
                    body_dialog_id=body_dialog_id,
                    choice_dialog_id=choice_dialog_id,
                    limit=limit,
                    offset=offset,
                )
            )
        except Exception:
            return 0

    def prune_dialog_logs(
        self,
        *,
        max_raw_rows: Optional[int] = None,
        max_journal_rows: Optional[int] = None,
        max_turn_rows: Optional[int] = None,
        older_than_days: Optional[float] = None,
    ) -> Dict[str, int]:
        pipeline = self._get_turn_pipeline()
        if pipeline is None:
            return {
                "removed_raw_callbacks": 0,
                "removed_callback_journal": 0,
                "removed_dialog_turns": 0,
                "removed_dialog_choices": 0,
            }
        try:
            return pipeline.prune_dialog_logs(
                max_raw_rows=max_raw_rows,
                max_journal_rows=max_journal_rows,
                max_turn_rows=max_turn_rows,
                older_than_days=older_than_days,
            )
        except Exception:
            return {
                "removed_raw_callbacks": 0,
                "removed_callback_journal": 0,
                "removed_dialog_turns": 0,
                "removed_dialog_choices": 0,
            }

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
        turns = self.get_dialog_turns(
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
        return _analyze_dialog_turns(turns, max_issues=max_issues)

_dialog_widget_instance: Optional[DialogWidget] = None


def get_dialog_widget() -> DialogWidget:
    global _dialog_widget_instance
    if _dialog_widget_instance is None:
        _dialog_widget_instance = DialogWidget()
    return _dialog_widget_instance


def get_active_dialog() -> Optional[ActiveDialogInfo]:
    return get_dialog_widget().get_active_dialog()


def get_active_dialog_buttons() -> List[DialogButtonInfo]:
    return get_dialog_widget().get_active_dialog_buttons()


def get_last_selected_dialog_id() -> int:
    return get_dialog_widget().get_last_selected_dialog_id()


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
    turn_timeout_ms: Optional[int] = None,
) -> str:
    return get_dialog_widget().configure_dialog_storage(
        db_path=db_path,
        turn_timeout_ms=turn_timeout_ms,
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


def get_dialog_turns(
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
    return get_dialog_widget().get_dialog_turns(
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


def get_dialog_turn(turn_id: int, *, include_choices: bool = True, sync: bool = True) -> Optional[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_turn(
        turn_id=turn_id,
        include_choices=include_choices,
        sync=sync,
    )


def get_dialog_turns_by_map(
    map_id: int,
    *,
    limit: int = 200,
    offset: int = 0,
    include_choices: bool = True,
    sync: bool = True,
) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_turns_by_map(
        map_id=map_id,
        limit=limit,
        offset=offset,
        include_choices=include_choices,
        sync=sync,
    )


def get_dialog_turns_by_npc_archetype(
    npc_uid_archetype: str,
    *,
    limit: int = 200,
    offset: int = 0,
    include_choices: bool = True,
    sync: bool = True,
) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_turns_by_npc_archetype(
        npc_uid_archetype=npc_uid_archetype,
        limit=limit,
        offset=offset,
        include_choices=include_choices,
        sync=sync,
    )


def get_dialog_turns_by_body_dialog_id(
    body_dialog_id: int,
    *,
    limit: int = 200,
    offset: int = 0,
    include_choices: bool = True,
    sync: bool = True,
) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_turns_by_body_dialog_id(
        body_dialog_id=body_dialog_id,
        limit=limit,
        offset=offset,
        include_choices=include_choices,
        sync=sync,
    )


def get_dialog_turns_by_choice_dialog_id(
    choice_dialog_id: int,
    *,
    limit: int = 200,
    offset: int = 0,
    include_choices: bool = True,
    sync: bool = True,
) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_turns_by_choice_dialog_id(
        choice_dialog_id=choice_dialog_id,
        limit=limit,
        offset=offset,
        include_choices=include_choices,
        sync=sync,
    )


def get_dialog_choices(turn_id: int, *, sync: bool = True) -> List[Dict[str, Any]]:
    return get_dialog_widget().get_dialog_choices(turn_id=turn_id, sync=sync)


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


def export_dialog_turns_json(
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
    return get_dialog_widget().export_dialog_turns_json(
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
    max_turn_rows: Optional[int] = None,
    older_than_days: Optional[float] = None,
) -> Dict[str, int]:
    return get_dialog_widget().prune_dialog_logs(
        max_raw_rows=max_raw_rows,
        max_journal_rows=max_journal_rows,
        max_turn_rows=max_turn_rows,
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
<<<<<<< HEAD
=======

>>>>>>> 59bc33e4 (Create dialog-only branch without SkillAccept bridge)
