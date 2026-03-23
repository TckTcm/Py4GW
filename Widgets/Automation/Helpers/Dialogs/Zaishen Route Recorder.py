from __future__ import annotations

import json
import os
import pprint
from dataclasses import dataclass, field
from typing import Any, Dict, List

import Py4GW  # type: ignore
from Py4GWCoreLib import Agent, Map, Player, PyImGui, Routines

MODULE_NAME = "Zaishen Route Recorder"
MODULE_ICON = "Textures\\Module_Icons\\Quest Auto Runner.png"

_PROJECT_ROOT = str(Py4GW.Console.get_projects_path() or "")
_DATA_DIR = os.path.join(_PROJECT_ROOT, "Widgets", "Data")
_DATA_PATH = os.path.join(_DATA_DIR, "zaishen_route_recorder.json")
os.makedirs(_DATA_DIR, exist_ok=True)


@dataclass
class RecorderState:
    label_input: str = ""
    status_text: str = "Ready."
    records: List[Dict[str, Any]] = field(default_factory=list)


_state = RecorderState()


def _round_coord(value: Any) -> float:
    try:
        return round(float(value), 2)
    except Exception:
        return 0.0


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _map_payload() -> Dict[str, Any]:
    map_id = int(Map.GetMapID() or 0)
    return {
        "map_id": map_id,
        "map_name": _safe_text(Map.GetMapName(map_id) if map_id else Map.GetMapName()),
    }


def _player_payload() -> Dict[str, Any]:
    player_agent_id = int(Player.GetAgentID() or 0)
    x, y, z = Agent.GetXYZ(player_agent_id) if player_agent_id > 0 else (0.0, 0.0, 0.0)
    return {
        "player_agent_id": player_agent_id,
        "player_x": _round_coord(x),
        "player_y": _round_coord(y),
        "player_z": _round_coord(z),
    }


def _target_payload() -> Dict[str, Any]:
    target_id = int(Player.GetTargetID() or 0)
    if target_id <= 0:
        return {
            "target_id": 0,
            "target_name": "",
            "target_model_id": 0,
            "target_is_npc": False,
            "target_allegiance": "Unknown",
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


def _record_label(default_prefix: str) -> str:
    custom = _safe_text(_state.label_input)
    if custom:
        return custom
    return f"{default_prefix} {_record_count() + 1}"


def _record_count() -> int:
    return len(_state.records)


def _save_records() -> None:
    try:
        with open(_DATA_PATH, "w", encoding="utf-8") as handle:
            json.dump(_state.records, handle, ensure_ascii=True, indent=2)
    except Exception as exc:
        _state.status_text = f"Save failed: {exc}"
        Py4GW.Console.Log(MODULE_NAME, _state.status_text, Py4GW.Console.MessageType.Error)


def _load_records() -> None:
    if not os.path.exists(_DATA_PATH):
        return

    try:
        with open(_DATA_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, list):
            _state.records = [item for item in payload if isinstance(item, dict)]
            _state.status_text = f"Loaded {_record_count()} recorded entries."
    except Exception as exc:
        _state.records = []
        _state.status_text = f"Load failed: {exc}"
        Py4GW.Console.Log(MODULE_NAME, _state.status_text, Py4GW.Console.MessageType.Error)


def _append_record(record: Dict[str, Any]) -> None:
    _state.records.append(record)
    _save_records()


def _capture_player_step() -> None:
    record = {
        "index": _record_count() + 1,
        "kind": "step",
        "label": _record_label("Step"),
        **_map_payload(),
        **_player_payload(),
    }
    _append_record(record)
    _state.status_text = (
        f"Recorded {record['label']} at "
        f"({record['player_x']}, {record['player_y']}, {record['player_z']})."
    )


def _capture_target_npc() -> None:
    target = _target_payload()
    if int(target["target_id"]) <= 0:
        _state.status_text = "No target selected."
        return
    if not bool(target["target_is_npc"]):
        _state.status_text = "Current target is not an NPC."
        return

    record = {
        "index": _record_count() + 1,
        "kind": "npc",
        "label": _record_label("NPC"),
        **_map_payload(),
        **_player_payload(),
        **target,
    }
    _append_record(record)
    _state.status_text = (
        f"Recorded NPC '{record['target_name'] or '<unnamed>'}' "
        f"(id={record['target_id']}, model={record['target_model_id']})."
    )


def _remove_last_record() -> None:
    if not _state.records:
        _state.status_text = "Nothing to remove."
        return
    removed = _state.records.pop()
    _save_records()
    _state.status_text = f"Removed {removed.get('kind', 'entry')} '{removed.get('label', '')}'."


def _clear_records() -> None:
    if not _state.records:
        _state.status_text = "Recorder is already empty."
        return
    _state.records.clear()
    _save_records()
    _state.status_text = "Cleared all recorded entries."


def _records_as_json() -> str:
    return json.dumps(_state.records, ensure_ascii=True, indent=2)


def _records_as_python() -> str:
    return "RECORDED_ZAISHEN_ROUTE = " + pprint.pformat(_state.records, width=120, sort_dicts=False)


def _copy_json_export() -> None:
    PyImGui.set_clipboard_text(_records_as_json())
    _state.status_text = "Copied JSON export to clipboard."


def _copy_python_export() -> None:
    PyImGui.set_clipboard_text(_records_as_python())
    _state.status_text = "Copied Python export to clipboard."


def _current_player_summary() -> str:
    player = _player_payload()
    return (
        f"Player: ({player['player_x']}, {player['player_y']}, {player['player_z']}) "
        f"| agent_id={player['player_agent_id']}"
    )


def _current_target_summary() -> str:
    target = _target_payload()
    if int(target["target_id"]) <= 0:
        return "Target: <none>"
    return (
        f"Target: {target['target_name'] or '<unnamed>'} "
        f"| id={target['target_id']} | model={target['target_model_id']} "
        f"| npc={target['target_is_npc']} | pos=({target['target_x']}, {target['target_y']}, {target['target_z']})"
    )


def _entry_line(entry: Dict[str, Any]) -> str:
    kind = _safe_text(entry.get("kind", "entry"))
    label = _safe_text(entry.get("label", ""))
    if kind == "npc":
        return (
            f"#{entry.get('index', 0)} [{kind}] {label} | "
            f"{entry.get('target_name', '<unnamed>')} | "
            f"target=({entry.get('target_x', 0.0)}, {entry.get('target_y', 0.0)}, {entry.get('target_z', 0.0)}) | "
            f"player=({entry.get('player_x', 0.0)}, {entry.get('player_y', 0.0)}, {entry.get('player_z', 0.0)})"
        )
    return (
        f"#{entry.get('index', 0)} [{kind}] {label} | "
        f"player=({entry.get('player_x', 0.0)}, {entry.get('player_y', 0.0)}, {entry.get('player_z', 0.0)})"
    )


def _draw_records_panel() -> None:
    PyImGui.separator()
    PyImGui.text(f"Recorded entries: {_record_count()}")
    PyImGui.text_wrapped(f"Data file: {_DATA_PATH}")

    if PyImGui.begin_child("ZaishenRecorderEntries", (0, 260), True, PyImGui.WindowFlags.HorizontalScrollbar):
        if not _state.records:
            PyImGui.text("<no entries yet>")
        else:
            for entry in _state.records[-20:]:
                line = _entry_line(entry)
                PyImGui.text_wrapped(line)
                if PyImGui.small_button(f"CopyJSON##{entry.get('index', 0)}"):
                    PyImGui.set_clipboard_text(json.dumps(entry, ensure_ascii=True, indent=2))
                    _state.status_text = f"Copied entry #{entry.get('index', 0)} to clipboard."
        PyImGui.end_child()


def _draw_help() -> None:
    PyImGui.separator()
    PyImGui.text_wrapped(
        "Use 'Add Current Step' whenever you want to capture a manual movement point. "
        "Use 'Record Target NPC' when you are targeting the Zaishen NPC instance you want me to use later. "
        "The exported JSON/Python includes map, player position, and target metadata so I can turn your captures into quest-taker logic."
    )


def _draw_widget() -> None:
    if not PyImGui.begin(MODULE_NAME):
        PyImGui.end()
        return

    map_info = _map_payload()
    PyImGui.text(f"Map: {map_info['map_name']} ({map_info['map_id']})")
    PyImGui.text(_current_player_summary())
    PyImGui.text_wrapped(_current_target_summary())

    label_input = str(PyImGui.input_text("Label / Note", _state.label_input))
    if label_input != _state.label_input:
        _state.label_input = label_input

    if PyImGui.button("Add Current Step"):
        _capture_player_step()
    if PyImGui.button("Record Target NPC"):
        _capture_target_npc()
    if PyImGui.button("Remove Last Entry"):
        _remove_last_record()
    if PyImGui.button("Clear All Entries"):
        _clear_records()

    PyImGui.separator()
    if PyImGui.button("Copy JSON Export"):
        _copy_json_export()
    if PyImGui.button("Copy Python Export"):
        _copy_python_export()
    if PyImGui.button("Reload Saved Entries"):
        _load_records()

    _draw_records_panel()
    _draw_help()
    PyImGui.separator()
    PyImGui.text_wrapped(f"Status: {_state.status_text}")
    PyImGui.end()


def tooltip() -> None:
    PyImGui.begin_tooltip()
    PyImGui.text(MODULE_NAME)
    PyImGui.separator()
    PyImGui.bullet_text("Record manual route steps as live player x/y/z")
    PyImGui.bullet_text("Record the current targeted NPC name and metadata")
    PyImGui.bullet_text("Copy the capture as JSON or Python for later bot integration")
    PyImGui.end_tooltip()


def main() -> None:
    try:
        if not Routines.Checks.Map.MapValid():
            return
        if Routines.Checks.Map.IsMapReady():
            _draw_widget()
    except Exception as exc:
        _state.status_text = f"Error: {exc}"
        Py4GW.Console.Log(MODULE_NAME, f"Unexpected error: {exc}", Py4GW.Console.MessageType.Error)


_load_records()


if __name__ == "__main__":
    main()
