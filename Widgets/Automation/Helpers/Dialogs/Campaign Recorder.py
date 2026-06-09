from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import Py4GW
from Py4GWCoreLib import Agent, Dialog, Map, Player, PyImGui, Quest, Routines
from Py4GWCoreLib.enums import explorables, get_quest_name, outposts

MODULE_NAME = "Campaign Recorder"

__widget__ = {
    "name": MODULE_NAME,
    "enabled": False,
    "category": "Dialog",
    "subcategory": "Recorder",
}

_PROJECT_ROOT = ""
_DATA_DIR = ""
_DATA_PATH = ""
_AUTOSAVE_INTERVAL_SECONDS = 1.0
_DEFAULT_MOVEMENT_THRESHOLD = 750.0


def _resolve_data_paths() -> tuple[str, str, str]:
    global _PROJECT_ROOT, _DATA_DIR, _DATA_PATH

    project_root = str(Py4GW.Console.get_projects_path() or "")
    if not project_root:
        _PROJECT_ROOT = ""
        _DATA_DIR = ""
        _DATA_PATH = ""
        return "", "", ""

    data_dir = os.path.join(project_root, "Widgets", "Data")
    data_path = os.path.join(data_dir, "campaign_recorder.json")
    os.makedirs(data_dir, exist_ok=True)
    _PROJECT_ROOT = project_root
    _DATA_DIR = data_dir
    _DATA_PATH = data_path
    return project_root, data_dir, data_path


def _round_coord(value: Any) -> float:
    try:
        return round(float(value), 2)
    except Exception:
        return 0.0


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _sanitize_player_name(value: Any) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    return "<player_name>"


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    dx = float(a[0]) - float(b[0])
    dy = float(a[1]) - float(b[1])
    dz = float(a[2]) - float(b[2])
    return (dx * dx + dy * dy + dz * dz) ** 0.5


def _reset_runtime_baselines() -> None:
    _state.last_auto_position = None
    _state.last_map_id = 0
    _state.last_target_npc_uid = ""
    _state.last_dialog_key = ""
    _state.last_selected_dialog_id = 0
    _state.last_dialog_context = {}
    _state.last_dialog_buttons = {}


def _report_persistence_issue(action: str, detail: str) -> None:
    message = f"{action} failed: {detail}"
    _state.status_text = message
    try:
        Py4GW.Console.Log(MODULE_NAME, message, Py4GW.Console.MessageType.Error)
    except Exception:
        return


def _resolve_map_name_from_enums(map_id: int) -> str:
    if map_id <= 0:
        return ""

    candidate_tables = (outposts, explorables)
    for table in candidate_tables:
        if isinstance(table, dict) and map_id in table:
            return _safe_text(table.get(map_id))

    return ""


def _resolve_quest_name_from_enums(quest_id: int) -> str:
    if quest_id <= 0:
        return ""

    try:
        return _safe_text(get_quest_name(quest_id))
    except Exception:
        return ""


@dataclass
class RecorderSession:
    session_name: str = ""
    session_note: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    movement_threshold: float = _DEFAULT_MOVEMENT_THRESHOLD
    events: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class RecorderState:
    recording_active: bool = False
    manual_note: str = ""
    status_text: str = "Ready."
    session_loaded: bool = False
    session_dirty: bool = False
    last_save_at: float = 0.0
    session: RecorderSession = field(default_factory=RecorderSession)
    last_auto_position: Optional[tuple[float, float, float]] = None
    last_map_id: int = 0
    last_target_npc_uid: str = ""
    last_dialog_key: str = ""
    last_selected_dialog_id: int = 0
    last_dialog_context: Dict[str, Any] = field(default_factory=dict)
    last_dialog_buttons: Dict[int, str] = field(default_factory=dict)


_state = RecorderState()


def tooltip() -> None:
    PyImGui.begin_tooltip()
    PyImGui.text(MODULE_NAME)
    PyImGui.text("Records dialog, movement, and target snapshots.")
    PyImGui.text("Use the controls to manage the current session.")
    PyImGui.text("Raw timeline is the source of truth; export is derived.")
    PyImGui.text("Manual route markers are preferred over passive movement points.")
    PyImGui.end_tooltip()


def _map_payload() -> Dict[str, Any]:
    map_id = int(Map.GetMapID() or 0)
    map_name = _resolve_map_name_from_enums(map_id)
    if not map_name:
        try:
            map_name = _safe_text(Map.GetMapName(map_id) if map_id else Map.GetMapName())
        except Exception:
            map_name = ""

    return {
        "map_id": map_id,
        "map_name": map_name,
    }


def _active_quest_payload() -> Dict[str, Any]:
    active_quest_id = 0
    active_quest_name = ""

    try:
        active_quest_id = int(Quest.GetActiveQuest() or 0)
    except Exception:
        active_quest_id = 0

    if active_quest_id > 0:
        try:
            active_quest_name = _safe_text(Quest.GetQuestName(active_quest_id))
        except Exception:
            active_quest_name = ""

        if not active_quest_name:
            active_quest_name = _resolve_quest_name_from_enums(active_quest_id)

    return {
        "active_quest_id": active_quest_id,
        "active_quest_name": active_quest_name,
    }


def _player_payload() -> Dict[str, Any]:
    player_agent_id = 0
    player_name_raw = ""
    x, y, z = 0.0, 0.0, 0.0

    try:
        player_agent_id = int(Player.GetAgentID() or 0)
    except Exception:
        player_agent_id = 0

    if player_agent_id > 0:
        try:
            player_name_raw = _safe_text(Player.GetName())
        except Exception:
            player_name_raw = ""
        if not player_name_raw:
            try:
                player_name_raw = _safe_text(Agent.GetNameByID(player_agent_id))
            except Exception:
                player_name_raw = ""
        try:
            x, y, z = Agent.GetXYZ(player_agent_id)
        except Exception:
            x, y, z = 0.0, 0.0, 0.0

    return {
        "player_agent_id": player_agent_id,
        "player_name_raw": player_name_raw,
        "player_name_sanitized": _sanitize_player_name(player_name_raw),
        "player_x": _round_coord(x),
        "player_y": _round_coord(y),
        "player_z": _round_coord(z),
    }


def _current_player_position() -> Optional[tuple[int, tuple[float, float, float]]]:
    try:
        player_agent_id = int(Player.GetAgentID() or 0)
    except Exception:
        player_agent_id = 0

    if player_agent_id <= 0:
        return None

    try:
        x, y, z = Agent.GetXYZ(player_agent_id)
    except Exception:
        return None

    current_pos = (float(x), float(y), float(z))
    if current_pos == (0.0, 0.0, 0.0):
        return None
    return player_agent_id, current_pos


def _target_payload() -> Dict[str, Any]:
    target_id = 0
    try:
        target_id = int(Player.GetTargetID() or 0)
    except Exception:
        target_id = 0

    if target_id <= 0:
        return {
            "target_id": 0,
            "target_name": "",
            "target_model_id": 0,
            "target_is_npc": False,
            "target_allegiance": "",
            "target_x": 0.0,
            "target_y": 0.0,
            "target_z": 0.0,
        }

    target_name = ""
    target_model_id = 0
    target_is_npc = False
    target_allegiance = "Unknown"
    x, y, z = 0.0, 0.0, 0.0

    try:
        target_name = _safe_text(Agent.GetNameByID(target_id))
    except Exception:
        target_name = ""

    try:
        target_model_id = int(Agent.GetModelID(target_id) or 0)
    except Exception:
        target_model_id = 0

    try:
        target_is_npc = bool(Agent.IsNPC(target_id))
    except Exception:
        target_is_npc = False

    try:
        _, target_allegiance = Agent.GetAllegiance(target_id)
    except Exception:
        target_allegiance = "Unknown"

    try:
        x, y, z = Agent.GetXYZ(target_id)
    except Exception:
        x, y, z = 0.0, 0.0, 0.0

    return {
        "target_id": target_id,
        "target_name": target_name,
        "target_model_id": target_model_id,
        "target_is_npc": target_is_npc,
        "target_allegiance": _safe_text(target_allegiance),
        "target_x": _round_coord(x),
        "target_y": _round_coord(y),
        "target_z": _round_coord(z),
    }


def _is_recordable_target_npc(target: Dict[str, Any]) -> bool:
    if not bool(target.get("target_is_npc")):
        return False

    allegiance = _safe_text(target.get("target_allegiance")).lower()
    if allegiance in ("enemy", "minion", "spirit/pet"):
        return False

    return allegiance in ("npc/minipet", "neutral")


def _npc_uid(map_id: int, model_id: int, agent_id: int) -> str:
    if map_id <= 0 or model_id <= 0 or agent_id <= 0:
        return ""
    return f"{map_id}:{model_id}:{agent_id}"


def _active_dialog_context() -> Dict[str, Any]:
    active_dialog = Dialog.get_active_dialog()
    if active_dialog is None:
        return {}

    try:
        agent_id = int(getattr(active_dialog, "agent_id", 0) or 0)
    except Exception:
        agent_id = 0

    try:
        body_dialog_id = int(getattr(active_dialog, "dialog_id", 0) or getattr(active_dialog, "context_dialog_id", 0) or 0)
    except Exception:
        body_dialog_id = 0

    body_text = _safe_text(
        getattr(active_dialog, "message", "")
        or getattr(active_dialog, "raw_message", "")
        or ""
    )

    model_id = 0
    agent_name = ""
    npc_x, npc_y, npc_z = 0.0, 0.0, 0.0
    if agent_id > 0:
        try:
            model_id = int(Agent.GetModelID(agent_id) or 0)
        except Exception:
            model_id = 0
        try:
            agent_name = _safe_text(Agent.GetNameByID(agent_id))
        except Exception:
            agent_name = ""
        try:
            npc_x, npc_y, npc_z = Agent.GetXYZ(agent_id)
        except Exception:
            npc_x, npc_y, npc_z = 0.0, 0.0, 0.0

    map_id = int(Map.GetMapID() or 0)
    npc_uid = _npc_uid(map_id, model_id, agent_id)

    return {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "model_id": model_id,
        "npc_uid": npc_uid,
        "body_dialog_id": body_dialog_id,
        "body_text": body_text,
        "npc_x": _round_coord(npc_x),
        "npc_y": _round_coord(npc_y),
        "npc_z": _round_coord(npc_z),
    }


def _next_label(prefix: str) -> str:
    base = _safe_text(prefix) or "Event"
    return f"{base} {len(_state.session.events) + 1}"


def _append_event(event_type: str, label: str, note: str = "", **extra: Any) -> Dict[str, Any]:
    timestamp = time.time()
    session = _state.session
    event = {
        "index": len(session.events) + 1,
        "timestamp": timestamp,
        "event_type": _safe_text(event_type),
        "label": _safe_text(label),
        "note": _safe_text(note),
        **_active_quest_payload(),
        **_map_payload(),
        **_player_payload(),
        **extra,
    }

    if session.created_at <= 0.0:
        session.created_at = timestamp
    session.updated_at = timestamp
    session.events.append(event)
    _state.session_dirty = True
    _save_session(force=False)
    return event


def _poll_movement() -> None:
    player_state = _current_player_position()
    if player_state is None:
        return

    _, current_pos = player_state

    if _state.last_auto_position is None:
        _append_event(
            "movement_auto",
            _next_label("Auto Route Point"),
            source="auto",
            trigger_distance=0.0,
        )
        _state.last_auto_position = current_pos
        return

    moved = _distance(current_pos, _state.last_auto_position)
    if moved < float(_state.session.movement_threshold):
        return

    _append_event(
        "movement_auto",
        _next_label("Auto Route Point"),
        source="auto",
        trigger_distance=_round_coord(moved),
    )
    _state.last_auto_position = current_pos


def _poll_target_npc() -> None:
    target = _target_payload()
    if not target.get("target_id") or not _is_recordable_target_npc(target):
        _state.last_target_npc_uid = ""
        return

    current_map_id = int(Map.GetMapID() or 0)
    target_model_id = int(target.get("target_model_id") or 0)
    target_id = int(target.get("target_id") or 0)
    npc_uid = _npc_uid(current_map_id, target_model_id, target_id)
    if not npc_uid or npc_uid == _state.last_target_npc_uid:
        return

    target_name = _safe_text(target.get("target_name"))
    label_suffix = target_name if target_name else str(target_model_id)
    _append_event(
        "npc_target",
        f"Target NPC {label_suffix}",
        npc_uid=npc_uid,
        **target,
    )
    _state.last_target_npc_uid = npc_uid


def _record_dialog_npc(context: Dict[str, Any]) -> None:
    npc_uid = _safe_text(context.get("npc_uid"))
    agent_id = _coerce_int(context.get("agent_id", 0), 0)
    model_id = _coerce_int(context.get("model_id", 0), 0)
    if not npc_uid or agent_id <= 0 or model_id <= 0:
        return
    if npc_uid == _state.last_target_npc_uid:
        return

    agent_name = _safe_text(context.get("agent_name"))
    label_suffix = agent_name if agent_name else str(model_id)
    _append_event(
        "npc_target",
        f"Dialog NPC {label_suffix}",
        npc_uid=npc_uid,
        source="dialog_auto",
        target_id=agent_id,
        target_name=agent_name,
        target_model_id=model_id,
        target_is_npc=True,
        target_allegiance="NPC/Minipet",
        target_x=_round_coord(context.get("npc_x", 0.0)),
        target_y=_round_coord(context.get("npc_y", 0.0)),
        target_z=_round_coord(context.get("npc_z", 0.0)),
    )
    _state.last_target_npc_uid = npc_uid


def _poll_dialog_body() -> None:
    context = _active_dialog_context()
    if not context:
        _state.last_dialog_key = ""
        return

    body_dialog_id = int(context.get("body_dialog_id", 0) or 0)
    if body_dialog_id <= 0:
        _state.last_dialog_key = ""
        return

    sanitize = getattr(Dialog, "sanitize_dialog_text", None)
    if callable(sanitize):
        try:
            body_text = _safe_text(sanitize(context.get("body_text", "")))
        except Exception:
            body_text = _safe_text(context.get("body_text", ""))
    else:
        body_text = _safe_text(context.get("body_text", ""))

    key = f"{_safe_text(context.get('npc_uid', ''))}|{body_dialog_id}|{body_text}"
    if not key or key == _state.last_dialog_key:
        return

    _state.last_selected_dialog_id = 0

    try:
        buttons = Dialog.get_active_dialog_buttons()
    except Exception:
        buttons = []

    _record_dialog_npc(context)

    _state.last_dialog_context = dict(context)
    _state.last_dialog_buttons = {}
    for button in buttons:
        button_dialog_id = _coerce_int(getattr(button, "dialog_id", 0), 0)
        if button_dialog_id <= 0:
            continue
        _state.last_dialog_buttons[button_dialog_id] = _safe_text(
            getattr(button, "message_decoded", "")
            or getattr(button, "message", "")
            or ""
        )

    choice_count = len(buttons)

    _append_event(
        "dialog_body",
        f"Dialog Body {body_dialog_id}",
        choice_count=choice_count,
        **context,
    )
    _state.last_dialog_key = key


def _poll_dialog_selection() -> None:
    try:
        selected_dialog_id = int(Dialog.get_last_selected_dialog_id() or 0)
    except Exception:
        selected_dialog_id = 0

    if selected_dialog_id <= 0 or selected_dialog_id == _state.last_selected_dialog_id:
        return

    context = _active_dialog_context()
    if not context:
        context = dict(_state.last_dialog_context)
    if not context:
        _state.last_selected_dialog_id = 0
        return

    _record_dialog_npc(context)

    choice_text = ""
    try:
        buttons = Dialog.get_active_dialog_buttons()
    except Exception:
        buttons = []

    for button in buttons:
        try:
            button_dialog_id = int(getattr(button, "dialog_id", 0) or 0)
        except Exception:
            button_dialog_id = 0
        if button_dialog_id != selected_dialog_id:
            continue
        choice_text = _safe_text(
            getattr(button, "message_decoded", "")
            or getattr(button, "message", "")
            or ""
        )
        break

    if not choice_text:
        choice_text = _safe_text(_state.last_dialog_buttons.get(selected_dialog_id, ""))

    _append_event(
        "dialog_choice_selected",
        f"Selected Dialog {selected_dialog_id}",
        choice_dialog_id=selected_dialog_id,
        choice_text=choice_text,
        selection_source="last_selected_dialog_id",
        **context,
    )
    _state.last_selected_dialog_id = selected_dialog_id


def _poll_map_change() -> None:
    current_map_id = int(Map.GetMapID() or 0)
    previous_map_id = int(_state.last_map_id or 0)

    if previous_map_id <= 0:
        _state.last_map_id = current_map_id
        return

    if current_map_id == previous_map_id:
        return

    previous_map_name = _resolve_map_name_from_enums(previous_map_id)
    if not previous_map_name:
        try:
            previous_map_name = _safe_text(Map.GetMapName(previous_map_id))
        except Exception:
            previous_map_name = ""

    _append_event(
        "map_changed",
        _next_label("Map Change"),
        previous_map_id=previous_map_id,
        previous_map_name=previous_map_name,
    )
    _state.last_map_id = current_map_id
    _state.last_auto_position = None


def _add_manual_route_marker() -> None:
    if not _state.recording_active:
        return
    _append_event(
        "movement_manual",
        _next_label("Manual Route Marker"),
        note=_safe_text(_state.manual_note),
        source="manual",
    )


def _record_current_target_npc() -> None:
    if not _state.recording_active:
        return
    target = _target_payload()
    if not target.get("target_id") or not _is_recordable_target_npc(target):
        return

    current_map_id = int(Map.GetMapID() or 0)
    target_model_id = int(target.get("target_model_id") or 0)
    target_id = int(target.get("target_id") or 0)
    npc_uid = _npc_uid(current_map_id, target_model_id, target_id)
    if not npc_uid:
        return

    target_name = _safe_text(target.get("target_name"))
    label_suffix = target_name if target_name else str(target_model_id)
    _append_event(
        "npc_target",
        f"Record Current Target NPC {label_suffix}",
        npc_uid=npc_uid,
        source="manual",
        **target,
    )
    _state.last_target_npc_uid = npc_uid


def _build_modular_bot_export() -> Dict[str, Any]:
    player = _player_payload()
    payload: Dict[str, Any] = {
        "name": _safe_text(_state.session.session_name) or "campaign_recording",
        "player_name_raw": _safe_text(player.get("player_name_raw")),
        "player_name_sanitized": _sanitize_player_name(player.get("player_name_sanitized")),
        "steps": [],
    }
    steps: List[Dict[str, Any]] = payload["steps"]
    npc_selectors_by_uid: Dict[str, Dict[str, Any]] = {}
    for event in _state.session.events:
        event_type = _safe_text(event.get("event_type"))
        npc_uid = _safe_text(event.get("npc_uid"))

        if event_type == "npc_target" and npc_uid:
            selector: Dict[str, Any] = {}
            target_x = _coerce_int(event.get("target_x", 0), 0)
            target_y = _coerce_int(event.get("target_y", 0), 0)
            target_name = _safe_text(event.get("target_name"))
            model_id = _coerce_int(event.get("target_model_id", 0), 0)
            if target_x or target_y:
                selector["x"] = target_x
                selector["y"] = target_y
            if model_id > 0:
                selector["model_id"] = model_id
            if target_name:
                selector["target"] = target_name
            if selector:
                npc_selectors_by_uid[npc_uid] = selector
            continue

        if event_type == "dialog_body" and npc_uid:
            selector = dict(npc_selectors_by_uid.get(npc_uid, {}))
            npc_x = _coerce_int(event.get("npc_x", 0), 0)
            npc_y = _coerce_int(event.get("npc_y", 0), 0)
            model_id = _coerce_int(event.get("model_id", 0), 0)
            agent_name = _safe_text(event.get("agent_name"))
            if npc_x or npc_y:
                selector["x"] = npc_x
                selector["y"] = npc_y
            if model_id > 0:
                selector["model_id"] = model_id
            if agent_name and "target" not in selector:
                selector["target"] = agent_name
            if selector:
                npc_selectors_by_uid[npc_uid] = selector
            continue

        if event_type == "movement_manual":
            player_x = _coerce_int(event.get("player_x", 0), 0)
            player_y = _coerce_int(event.get("player_y", 0), 0)
            steps.append(
                {
                    "type": "auto_path",
                    "name": _safe_text(event.get("label")) or "Manual Route Marker",
                    "points": [
                        [
                            player_x,
                            player_y,
                        ]
                    ],
                    "meta": {
                        "active_quest_id": _coerce_int(event.get("active_quest_id", 0), 0),
                        "active_quest_name": _safe_text(event.get("active_quest_name")),
                        "player_name_raw": _safe_text(event.get("player_name_raw")),
                        "player_name_sanitized": _sanitize_player_name(event.get("player_name_sanitized")),
                    },
                }
            )
            continue

        if event_type == "dialog_choice_selected":
            choice_dialog_id = _coerce_int(event.get("choice_dialog_id", 0), 0)
            choice_text = _safe_text(event.get("choice_text")) or _safe_text(event.get("label")) or "Dialog"
            selector = dict(npc_selectors_by_uid.get(npc_uid, {}))
            npc_x = _coerce_int(event.get("npc_x", 0), 0)
            npc_y = _coerce_int(event.get("npc_y", 0), 0)
            model_id = _coerce_int(event.get("model_id", 0), 0)
            agent_name = _safe_text(event.get("agent_name"))
            if npc_x or npc_y:
                selector["x"] = npc_x
                selector["y"] = npc_y
            if model_id > 0:
                selector["model_id"] = model_id
            if agent_name and "target" not in selector:
                selector["target"] = agent_name

            step = {
                "type": "dialog",
                "id": choice_dialog_id,
                "name": choice_text,
                "meta": {
                    "active_quest_id": _coerce_int(event.get("active_quest_id", 0), 0),
                    "active_quest_name": _safe_text(event.get("active_quest_name")),
                    "player_name_raw": _safe_text(event.get("player_name_raw")),
                    "player_name_sanitized": _sanitize_player_name(event.get("player_name_sanitized")),
                },
            }
            step.update(selector)
            steps.append(step)

    return payload


def _copy_modular_bot_export() -> None:
    payload = _build_modular_bot_export()
    PyImGui.set_clipboard_text(json.dumps(payload, ensure_ascii=True, indent=2))


def _current_player_summary() -> str:
    player_state = _current_player_position()
    player = _player_payload()
    player_name = _sanitize_player_name(player.get("player_name_sanitized"))
    if player_state is None:
        if player_name:
            return f"Player: name={player_name} | <unavailable>"
        return "<unavailable>"

    agent_id, current_pos = player_state
    return (
        f"Player: name={player_name or '<unnamed>'} | agent={agent_id} | "
        f"xyz=({_round_coord(current_pos[0])}, {_round_coord(current_pos[1])}, {_round_coord(current_pos[2])})"
    )


def _current_target_summary() -> str:
    target = _target_payload()
    target_id = int(target.get("target_id") or 0)
    if target_id <= 0:
        return "<none>"

    target_name = _safe_text(target.get("target_name")) or "<unnamed>"
    target_model_id = int(target.get("target_model_id") or 0)
    target_is_npc = bool(target.get("target_is_npc"))
    return (
        f"Target: id={target_id} | name={target_name} | "
        f"model={target_model_id} | npc={str(target_is_npc).lower()}"
    )


def _current_dialog_summary() -> str:
    active_dialog = Dialog.get_active_dialog()
    if active_dialog is None:
        return "Dialog: <none>"

    try:
        dialog_id = int(getattr(active_dialog, "dialog_id", 0) or 0)
    except Exception:
        dialog_id = 0

    try:
        agent_id = int(getattr(active_dialog, "agent_id", 0) or 0)
    except Exception:
        agent_id = 0

    return f"Dialog: id={dialog_id} | agent={agent_id}"


def _current_quest_summary() -> str:
    quest_id = 0
    quest_name = ""

    try:
        quest_id = int(Quest.GetActiveQuest() or 0)
    except Exception:
        quest_id = 0

    if quest_id <= 0:
        return "Quest: <none>"

    try:
        quest_name = _safe_text(Quest.GetQuestName(quest_id))
    except Exception:
        quest_name = ""

    if not quest_name:
        quest_name = _resolve_quest_name_from_enums(quest_id)

    return f"Quest: {quest_name or '<unnamed>'} ({quest_id})"


def _poll_recording() -> None:
    if not _state.recording_active:
        return
    if not Routines.Checks.Map.MapValid():
        return
    _poll_map_change()
    _poll_movement()
    _poll_dialog_selection()
    _poll_dialog_body()


def _session_payload() -> Dict[str, Any]:
    session = _state.session
    return {
        "session_name": session.session_name,
        "session_note": session.session_note,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "movement_threshold": session.movement_threshold,
        "events": session.events,
    }


def _save_session(force: bool = True) -> None:
    now = time.time()
    if not force:
        if not _state.session_dirty:
            return
        if now - float(_state.last_save_at or 0.0) < _AUTOSAVE_INTERVAL_SECONDS:
            return

    try:
        _, _, data_path = _resolve_data_paths()
    except Exception:
        _report_persistence_issue("Session save", "resolve data path")
        return

    if not data_path:
        _report_persistence_issue("Session save", "no data path")
        return

    try:
        data_dir = os.path.dirname(data_path) or "."
        temp_path = os.path.join(data_dir, f".{os.path.basename(data_path)}.tmp")
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(_session_payload(), handle, ensure_ascii=True, indent=2)
            handle.flush()
            if force:
                os.fsync(handle.fileno())
        os.replace(temp_path, data_path)
        _state.session_dirty = False
        _state.last_save_at = now
    except Exception as exc:
        try:
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        _report_persistence_issue("Session save", str(exc))
        return


def _load_session() -> None:
    if _state.session_dirty:
        _save_session(force=True)

    try:
        _, _, data_path = _resolve_data_paths()
    except Exception:
        _reset_runtime_baselines()
        _report_persistence_issue("Session load", "resolve data path")
        return

    if not data_path or not os.path.exists(data_path):
        _reset_runtime_baselines()
        return

    try:
        with open(data_path, "r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except Exception as exc:
        _reset_runtime_baselines()
        _report_persistence_issue("Session load", str(exc))
        return

    if not isinstance(payload, dict):
        _reset_runtime_baselines()
        _report_persistence_issue("Session load", "invalid payload")
        return

    events = payload.get("events")
    if not isinstance(events, list):
        events = []

    _state.session = RecorderSession(
        session_name=_safe_text(payload.get("session_name")),
        session_note=_safe_text(payload.get("session_note")),
        created_at=_coerce_float(payload.get("created_at"), 0.0),
        updated_at=_coerce_float(payload.get("updated_at"), 0.0),
        movement_threshold=max(0.0, _coerce_float(payload.get("movement_threshold"), _DEFAULT_MOVEMENT_THRESHOLD)),
        events=[event for event in events if isinstance(event, dict)],
    )
    if abs(_state.session.movement_threshold - 100.0) < 0.001 or abs(_state.session.movement_threshold - 300.0) < 0.001:
        _state.session.movement_threshold = _DEFAULT_MOVEMENT_THRESHOLD
    _state.session_dirty = False
    _reset_runtime_baselines()


def _clear_session() -> None:
    _state.recording_active = False
    _state.manual_note = ""
    _state.session = RecorderSession(movement_threshold=_DEFAULT_MOVEMENT_THRESHOLD)
    _reset_runtime_baselines()
    _save_session()


def _start_recording() -> None:
    now = time.time()
    session = _state.session
    if session.created_at <= 0.0:
        session.created_at = now
    if session.updated_at <= 0.0:
        session.updated_at = now
    _state.recording_active = True
    _state.last_auto_position = None
    _state.last_map_id = int(Map.GetMapID() or 0)
    _state.last_target_npc_uid = ""
    _state.last_dialog_key = ""
    _state.last_selected_dialog_id = int(Dialog.get_last_selected_dialog_id() or 0)
    _state.last_dialog_context = {}
    _state.last_dialog_buttons = {}


def _stop_recording() -> None:
    _state.recording_active = False
    _save_session()


def _draw_controls() -> None:
    _state.session.session_name = _safe_text(PyImGui.input_text("Session Name", _state.session.session_name))
    _state.session.session_note = _safe_text(PyImGui.input_text("Session Note", _state.session.session_note))
    _state.manual_note = _safe_text(PyImGui.input_text("Manual Note", _state.manual_note))

    if PyImGui.button("Start Recording"):
        _start_recording()
    PyImGui.same_line(0, -1)
    if PyImGui.button("Stop Recording"):
        _stop_recording()

    if PyImGui.button("Add Manual Route Marker"):
        _add_manual_route_marker()
    PyImGui.same_line(0, -1)
    if PyImGui.button("Record Current Target NPC"):
        _record_current_target_npc()

    if PyImGui.button("Copy Modular Bot Export"):
        _copy_modular_bot_export()

    if PyImGui.button("Save"):
        _save_session()
    PyImGui.same_line(0, -1)
    if PyImGui.button("Reload"):
        _load_session()
    PyImGui.same_line(0, -1)
    if PyImGui.button("Clear Session"):
        _clear_session()


def _draw_timeline() -> None:
    if PyImGui.begin_child("CampaignRecorderTimeline", (0, 260), True, PyImGui.WindowFlags.NoFlag):
        events = _state.session.events[-50:]
        if not events:
            PyImGui.text("<no events yet>")
        else:
            for event in events:
                event_index = int(event.get("index", 0) or 0)
                event_type = _safe_text(event.get("event_type"))
                label = _safe_text(event.get("label"))
                line = f"#{event_index} [{event_type}] {label}"
                PyImGui.text(line)
                note = _safe_text(event.get("note"))
                if note:
                    PyImGui.text(note)
                if PyImGui.small_button(f"CopyJSON##{event_index}"):
                    PyImGui.set_clipboard_text(json.dumps(event, ensure_ascii=True, indent=2))
                PyImGui.separator()
        PyImGui.end_child()


def _draw_widget() -> None:
    PyImGui.text(f"Status: {_state.status_text}")
    PyImGui.text(f"Recording: {'Active' if _state.recording_active else 'Stopped'}")
    PyImGui.separator()
    PyImGui.text(_current_player_summary())
    PyImGui.text(_current_target_summary())
    PyImGui.text(_current_dialog_summary())
    PyImGui.text(_current_quest_summary())
    PyImGui.separator()
    _draw_controls()
    PyImGui.separator()
    _draw_timeline()


def main() -> None:
    if not _state.session_loaded:
        _load_session()
        _state.session_loaded = True

    if Routines.Checks.Map.MapValid():
        _poll_recording()

    if not PyImGui.begin(f"{MODULE_NAME}##CampaignRecorder"):
        PyImGui.end()
        return

    _draw_widget()
    PyImGui.end()


if __name__ == "__main__":
    main()
