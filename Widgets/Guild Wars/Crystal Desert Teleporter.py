from __future__ import annotations

import importlib
import ctypes
import json
import os
import struct
import time
import traceback

import Py4GW
import PyAgent
import PyImGui
try:
    import PyPointers
except Exception:
    PyPointers = None

from Py4GWCoreLib.Agent import Agent
from Py4GWCoreLib.AgentArray import AgentArray
import Py4GWCoreLib.CrystalDesertTeleporter as CrystalDesertTeleporterCore
from Py4GWCoreLib.PacketSniffer import SNIFFER as PACKET_SNIFFER
from Py4GWCoreLib.Player import Player
from Py4GWCoreLib.Routines import Checks

CrystalDesertTeleporterCore = importlib.reload(CrystalDesertTeleporterCore)
ClickPlan = CrystalDesertTeleporterCore.ClickPlan
CaptureStatus = CrystalDesertTeleporterCore.CaptureStatus
GadgetSnapshot = CrystalDesertTeleporterCore.GadgetSnapshot
GadgetRuntimeSnapshot = CrystalDesertTeleporterCore.GadgetRuntimeSnapshot
PlatformMapping = CrystalDesertTeleporterCore.PlatformMapping
RawPacket = CrystalDesertTeleporterCore.RawPacket
SequenceRecorder = CrystalDesertTeleporterCore.SequenceRecorder
WorldCreateBurstRecorder = CrystalDesertTeleporterCore.WorldCreateBurstRecorder
client_action_summary = CrystalDesertTeleporterCore.client_action_summary
decode_client_interact_packet = CrystalDesertTeleporterCore.decode_client_interact_packet
decode_client_sequence_reset_packet = CrystalDesertTeleporterCore.decode_client_sequence_reset_packet
decode_gadget_state_packet = CrystalDesertTeleporterCore.decode_gadget_state_packet
decode_world_create_agent_packet = CrystalDesertTeleporterCore.decode_world_create_agent_packet
decode_world_create_switch_packet = CrystalDesertTeleporterCore.decode_world_create_switch_packet
learn_platform_mapping = CrystalDesertTeleporterCore.learn_platform_mapping
packet_direction_from_entry = CrystalDesertTeleporterCore.packet_direction_from_entry
packet_probe_summary = CrystalDesertTeleporterCore.packet_probe_summary
map_platform_burst_with_known_mappings = CrystalDesertTeleporterCore.map_platform_burst_with_known_mappings
plan_switch_interaction = CrystalDesertTeleporterCore.plan_switch_interaction
runtime_delta_fields = CrystalDesertTeleporterCore.runtime_delta_fields
runtime_delta_to_event = CrystalDesertTeleporterCore.runtime_delta_to_event
runtime_signature = CrystalDesertTeleporterCore.runtime_signature
select_switch_candidates = CrystalDesertTeleporterCore.select_switch_candidates


MODULE_NAME = "Crystal Desert Teleporter"
MODULE_ICON = "Textures/Module_Icons/Travel.png"
MODULE_BUILD = "server-confirmed-v47"
MAPPING_FILE = os.path.join(os.path.dirname(__file__), "CrystalDesertTeleporterMappings.json")
_PERSISTENT_MAPPINGS_ENABLED = False

_MAX_SWITCH_DISTANCE = 650.0
_MIN_SWITCH_DISTANCE = 60.0
_INTERACT_DISTANCE = 140.0
_AUTO_CLICK_DELAY = 0.85
_MOVE_REISSUE_DELAY = 1.25
_INTERACT_CONFIRM_TIMEOUT = 1.25

_capturing = False
_ctos_capture_available = False
_auto_click = False
_status = "Idle"
_candidate_switches: list[GadgetSnapshot] = []
_recorder = SequenceRecorder(expected_switch_count=4)
_world_create_recorder = WorldCreateBurstRecorder(expected_switch_count=4, burst_window_ms=1800)
_capture_status = CaptureStatus()
_click_plan: ClickPlan | None = None
_last_click_time = 0.0
_last_move_agent_id = 0
_last_move_time = 0.0
_pending_click_agent_id = 0
_pending_click_started_at = 0.0
_last_events: list[str] = []
_last_runtime_changes: list[str] = []
_last_probe_packets: list[str] = []
_last_raw_server_packets: list[str] = []
_last_client_actions: list[str] = []
_raw_server_header_counts: dict[int, int] = {}
_runtime_snapshots: dict[int, GadgetRuntimeSnapshot] = {}
_runtime_diagnostics_enabled = False
_pending_platform_sequence: list[int] = []
_platform_markers: list[GadgetSnapshot] = []
_manual_calibration_sequence: list[int] = []
_manual_calibration_slots: list[int] = [0, 0, 0, 0]
_platform_mappings: dict[str, PlatformMapping] = {}
_platform_mappings_loaded = False
_last_runtime_match_status = ""
_last_runtime_match_attempt_at = 0.0
_server_confirmation_plan_id = 0
_server_confirmed_switch_agent_ids: set[int] = set()

_GADGET_CONTEXT_OFFSET = 0x38
_GADGET_INFO_SIZE = 0x10

_TRUSTED_MAPPING_SOURCE = "manual"
_STOC_HEADER_NAMES = getattr(
    importlib.import_module("Py4GWCoreLib.PacketSniffer"),
    "STOC_HEADER_NAMES",
    {
        0x0020: "WORLD_CREATE_AGENT",
        0x009F: "AGENT_PROPERTY_UPDATE_INT",
        0x00A1: "AGENT_PROPERTY_PLAY_EFFECT",
        0x00A2: "AGENT_PROPERTY_UPDATE_FLOAT",
        0x010E: "MANIPULATE_MAP_OBJECT",
        0x0111: "MANIPULATE_MAP_OBJECT2",
        0x0115: "GADGET_STATE",
    },
)


def configure() -> None:
    pass


def on_disable() -> None:
    if _capturing:
        _stop_capture()


def tooltip() -> None:
    PyImGui.begin_tooltip()
    PyImGui.text(MODULE_NAME)
    PyImGui.separator()
    PyImGui.text("Records Crystal Desert teleporter switch flashes and clicks the switches in that order.")
    PyImGui.end_tooltip()


def _log(message: str, message_type=Py4GW.Console.MessageType.Info) -> None:
    Py4GW.Console.Log(MODULE_NAME, message, message_type)


def _set_status(message: str, message_type=Py4GW.Console.MessageType.Info) -> None:
    global _status
    _status = message
    _log(message, message_type)


def _clear_manual_calibration() -> None:
    _manual_calibration_sequence.clear()
    for index in range(len(_manual_calibration_slots)):
        _manual_calibration_slots[index] = 0


def _manual_slot_count() -> int:
    return sum(1 for agent_id in _manual_calibration_slots if int(agent_id) > 0)


def _manual_slots_active() -> bool:
    return _manual_slot_count() > 0


def _manual_slots_complete() -> bool:
    return (
        len(_manual_calibration_slots) >= _recorder.expected_switch_count
        and all(int(agent_id) > 0 for agent_id in _manual_calibration_slots[: _recorder.expected_switch_count])
        and len(set(_manual_calibration_slots[: _recorder.expected_switch_count])) == _recorder.expected_switch_count
    )


def _manual_slots_text() -> str:
    parts = []
    for index, agent_id in enumerate(_manual_calibration_slots[: _recorder.expected_switch_count], start=1):
        parts.append(f"#{index}={agent_id if agent_id else '<empty>'}")
    return " ".join(parts)


def _safe_packet_logs():
    try:
        return list(PACKET_SNIFFER.get_logs("both"))
    except TypeError:
        return list(PACKET_SNIFFER.get_logs())


def _clear_packet_logs() -> None:
    try:
        PACKET_SNIFFER.clear_logs("both")
    except TypeError:
        PACKET_SNIFFER.clear_logs()


def _load_platform_mappings() -> None:
    global _platform_mappings_loaded
    if _platform_mappings_loaded:
        return
    _platform_mappings_loaded = True
    _platform_mappings.clear()
    try:
        with open(MAPPING_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return
    except Exception as exception:
        _log(f"Failed to load platform mappings: {exception}", Py4GW.Console.MessageType.Warning)
        return

    if not isinstance(payload, dict):
        return
    for item in payload.get("mappings", []):
        try:
            if str(item.get("source") or "") != _TRUSTED_MAPPING_SOURCE:
                continue
            signature = str(item.get("signature") or "")
            pairs = tuple(
                (int(pair[0]), int(pair[1]))
                for pair in item.get("marker_to_switch_gadget_ids", [])
            )
            if not signature or not pairs:
                continue
            _platform_mappings[signature] = PlatformMapping(
                signature=signature,
                marker_to_switch_gadget_ids=pairs,
            )
        except Exception:
            continue


def _save_platform_mappings() -> None:
    try:
        payload = {
            "version": 1,
            "mappings": [
                {
                    "signature": mapping.signature,
                    "source": _TRUSTED_MAPPING_SOURCE,
                    "marker_to_switch_gadget_ids": [
                        [marker_gadget_id, switch_gadget_id]
                        for marker_gadget_id, switch_gadget_id in mapping.marker_to_switch_gadget_ids
                    ],
                }
                for mapping in sorted(_platform_mappings.values(), key=lambda item: item.signature)
            ],
        }
        os.makedirs(os.path.dirname(MAPPING_FILE), exist_ok=True)
        with open(MAPPING_FILE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception as exception:
        _log(f"Failed to save platform mappings: {exception}", Py4GW.Console.MessageType.Warning)


def _forget_learned_mappings() -> None:
    global _auto_click, _click_plan, _last_click_time, _last_move_agent_id, _last_move_time
    global _pending_click_agent_id, _pending_click_started_at
    _load_platform_mappings()
    _platform_mappings.clear()
    _save_platform_mappings()
    _recorder.clear()
    _clear_manual_calibration()
    _click_plan = None
    _auto_click = False
    _last_click_time = 0.0
    _last_move_agent_id = 0
    _last_move_time = 0.0
    _pending_click_agent_id = 0
    _pending_click_started_at = 0.0
    if _pending_platform_sequence:
        _set_status("Learned mappings cleared. Use Add buttons for the current platform burst.")
    else:
        _set_status("Learned mappings cleared. Step onto a platform to record a new burst.")


def _begin_manual_click_learning() -> None:
    global _auto_click, _click_plan, _last_click_time, _last_move_agent_id, _last_move_time
    global _pending_click_agent_id, _pending_click_started_at
    if not _pending_platform_sequence:
        _set_status("No platform burst is pending for manual click learning.", Py4GW.Console.MessageType.Warning)
        return
    _recorder.clear()
    _clear_manual_calibration()
    _click_plan = None
    _auto_click = False
    _last_click_time = 0.0
    _last_move_agent_id = 0
    _last_move_time = 0.0
    _pending_click_agent_id = 0
    _pending_click_started_at = 0.0
    _set_status("Learning manual switch clicks. Click the switches in the correct order.")


def _snapshot_gadgets() -> list[GadgetSnapshot]:
    snapshots: list[GadgetSnapshot] = []
    for agent_id in AgentArray.GetGadgetArray():
        if not Agent.IsGadget(agent_id):
            continue
        x, y = Agent.GetXY(agent_id)
        try:
            name = Agent.GetNameByID(agent_id)
        except Exception:
            name = ""
        snapshots.append(
            GadgetSnapshot(
                agent_id=int(agent_id),
                x=float(x),
                y=float(y),
                name=name,
                gadget_id=int(Agent.GetGadgetID(agent_id)),
                extra_type=int(Agent.GetGadgetAgentExtraType(agent_id)),
            )
        )
    return snapshots


def _refresh_candidates() -> None:
    global _candidate_switches
    center = Player.GetXY()
    _candidate_switches = select_switch_candidates(
        _snapshot_gadgets(),
        center=(float(center[0]), float(center[1])),
        max_distance=_MAX_SWITCH_DISTANCE,
        min_distance=_MIN_SWITCH_DISTANCE,
        limit=4,
    )


def _snapshot_gadget_by_agent_id(agent_id: int) -> GadgetSnapshot | None:
    try:
        agent_id = int(agent_id)
        if agent_id <= 0 or not Agent.IsGadget(agent_id):
            return None
        x, y = Agent.GetXY(agent_id)
        try:
            name = Agent.GetNameByID(agent_id)
        except Exception:
            name = ""
        return GadgetSnapshot(
            agent_id=agent_id,
            x=float(x),
            y=float(y),
            name=name,
            gadget_id=int(Agent.GetGadgetID(agent_id)),
            extra_type=int(Agent.GetGadgetAgentExtraType(agent_id)),
        )
    except Exception:
        return None


def _refresh_platform_markers(agent_ids: list[int]) -> None:
    _platform_markers.clear()
    seen: set[int] = set()
    for agent_id in agent_ids:
        agent_id = int(agent_id)
        if agent_id in seen:
            continue
        seen.add(agent_id)
        marker = _snapshot_gadget_by_agent_id(agent_id)
        if marker is not None:
            _platform_markers.append(marker)


def _safe_selected_target_id() -> int:
    try:
        return int(Player.GetTargetID() or 0)
    except Exception:
        return 0


def _selected_target_summary() -> str:
    target_id = _safe_selected_target_id()
    if target_id <= 0:
        return "Selected target: <none>"

    selected_switch: GadgetSnapshot | None = None
    selected_row = 0
    for index, switch in enumerate(_candidate_switches, start=1):
        if int(switch.agent_id) == target_id:
            selected_switch = switch
            selected_row = index
            break
    if selected_switch is None:
        return f"Selected target: agent={target_id} not in switch candidates"

    name = selected_switch.name
    if not name:
        try:
            name = Agent.GetNameByID(target_id)
        except Exception:
            name = ""
    gadget_id = int(selected_switch.gadget_id)
    if gadget_id <= 0:
        try:
            gadget_id = int(Agent.GetGadgetID(target_id))
        except Exception:
            gadget_id = 0
    return (
        f"Selected target: agent={target_id} switch-row={selected_row} "
        f"gadget={gadget_id} name={name or '<unknown>'} "
        f"xy=({selected_switch.x:.0f}, {selected_switch.y:.0f})"
    )


def _record_selected_target_switch() -> None:
    target_id = _safe_selected_target_id()
    if target_id <= 0:
        _set_status("No selected target to add.", Py4GW.Console.MessageType.Warning)
        return
    if target_id not in {switch.agent_id for switch in _candidate_switches}:
        _set_status(
            f"Selected target {target_id} is not one of the selected switches.",
            Py4GW.Console.MessageType.Warning,
        )
        return
    _record_manual_calibration_switch(target_id)


def _record_selected_target_switch_at_position(position: int) -> None:
    target_id = _safe_selected_target_id()
    if target_id <= 0:
        _set_status("No selected target to assign.", Py4GW.Console.MessageType.Warning)
        return
    if target_id not in {switch.agent_id for switch in _candidate_switches}:
        _set_status(
            f"Selected target {target_id} is not one of the selected switches.",
            Py4GW.Console.MessageType.Warning,
        )
        return
    _record_manual_calibration_switch_at_position(target_id, position)


def _accept_platform_burst_sequence(platform_sequence: list[int]) -> tuple[bool, bool]:
    global _last_runtime_match_status, _last_runtime_match_attempt_at
    burst = [int(agent_id) for agent_id in platform_sequence[: _recorder.expected_switch_count]]
    if len(burst) < _recorder.expected_switch_count:
        return False, False

    changed = bool(_pending_platform_sequence) and _pending_platform_sequence != burst
    _pending_platform_sequence[:] = burst
    _refresh_platform_markers(burst)
    _last_raw_server_packets.clear()
    _raw_server_header_counts.clear()
    _last_runtime_match_status = ""
    _last_runtime_match_attempt_at = 0.0
    if changed and (_manual_calibration_sequence or _manual_slots_active()):
        _clear_manual_calibration()
        return True, True
    return True, False


def _runtime_snapshot(agent_id: int) -> GadgetRuntimeSnapshot:
    agent = PyAgent.PyAgent(int(agent_id))
    agent.GetContext()
    gadget = PyAgent.PyGadgetAgent(int(agent_id))
    gadget.GetContext()
    return GadgetRuntimeSnapshot(
        agent_id=int(agent_id),
        visual_effects=int(getattr(agent, "visual_effects", 0)),
        h00c4=int(getattr(gadget, "h00C4", 0)),
        h00c8=int(getattr(gadget, "h00C8", 0)),
        h00d4=tuple(int(value) for value in getattr(gadget, "h00D4", [])),
    )


def _read_u32(address: int) -> int | None:
    try:
        if int(address) <= 0:
            return None
        return int(ctypes.c_uint32.from_address(int(address)).value)
    except Exception:
        return None


def _gadget_info_signature(gadget_id: int) -> tuple[int, int, int] | None:
    if PyPointers is None:
        return None
    try:
        gadget_id = int(gadget_id)
        if gadget_id <= 0:
            return None
        game_context = int(PyPointers.PyPointers.GetGameContextPtr() or 0)
        if game_context <= 0:
            return None
        gadget_context = _read_u32(game_context + _GADGET_CONTEXT_OFFSET)
        if not gadget_context:
            return None
        buffer = _read_u32(gadget_context)
        capacity = _read_u32(gadget_context + 4)
        size = _read_u32(gadget_context + 8)
        if not buffer or size is None or gadget_id >= int(size):
            return None
        if capacity is not None and gadget_id >= int(capacity):
            return None
        info_addr = int(buffer) + (gadget_id * _GADGET_INFO_SIZE)
        h0000 = _read_u32(info_addr)
        h0004 = _read_u32(info_addr + 4)
        h0008 = _read_u32(info_addr + 8)
        if h0000 is None or h0004 is None or h0008 is None:
            return None
        return int(h0000), int(h0004), int(h0008)
    except Exception:
        return None


def _gadget_info_text(gadget_id: int) -> str:
    signature = _gadget_info_signature(gadget_id)
    if signature is None:
        return "ginfo=<unavailable>"
    return "ginfo=" + ",".join(f"0x{value & 0xFFFFFFFF:08X}" for value in signature)


def _runtime_match_keys(snapshot: GadgetRuntimeSnapshot) -> list[tuple[str, tuple[int, ...]]]:
    h00d4 = tuple(int(value) & 0xFFFFFFFF for value in snapshot.h00d4[:4])
    keys: list[tuple[str, tuple[int, ...]]] = []
    if snapshot.h00c8 or h00d4:
        keys.append(
            (
                "full",
                (
                    int(snapshot.visual_effects) & 0xFFFFFFFF,
                    int(snapshot.h00c4) & 0xFFFFFFFF,
                    int(snapshot.h00c8) & 0xFFFFFFFF,
                    *h00d4,
                ),
            )
        )
    if snapshot.h00c8:
        keys.append(("c8", (int(snapshot.h00c8) & 0xFFFFFFFF,)))
    if len(h00d4) >= 4 and (h00d4[2] or h00d4[3]):
        keys.append(("d4_tail", (h00d4[2], h00d4[3])))
    if len(h00d4) >= 3 and h00d4[2]:
        keys.append(("d4_2", (h00d4[2],)))
    if len(h00d4) >= 4 and h00d4[3]:
        keys.append(("d4_3", (h00d4[3],)))
    return keys


def _try_map_pending_burst_from_runtime(*, force: bool = False) -> bool:
    global _click_plan, _last_runtime_match_status, _last_runtime_match_attempt_at
    if _click_plan is not None or len(_pending_platform_sequence) < _recorder.expected_switch_count:
        return False
    if len(_candidate_switches) < _recorder.expected_switch_count:
        return False

    now = time.monotonic()
    if not force and now - _last_runtime_match_attempt_at < 0.75:
        return False
    _last_runtime_match_attempt_at = now

    if len(_platform_markers) < _recorder.expected_switch_count:
        _refresh_platform_markers(_pending_platform_sequence)
    marker_sequence = [
        marker
        for marker in _platform_markers
        if int(marker.agent_id) in set(_pending_platform_sequence)
    ][: _recorder.expected_switch_count]
    if len(marker_sequence) < _recorder.expected_switch_count:
        _last_runtime_match_status = "runtime match: missing live platform marker snapshots"
        return False

    marker_info = {
        marker.agent_id: _gadget_info_signature(marker.gadget_id)
        for marker in marker_sequence
    }
    switch_info = {
        switch.agent_id: _gadget_info_signature(switch.gadget_id)
        for switch in _candidate_switches
    }
    if any(value is not None for value in marker_info.values()) and any(value is not None for value in switch_info.values()):
        switch_by_info: dict[tuple[int, int, int], int] = {}
        duplicate_info: set[tuple[int, int, int]] = set()
        for switch in _candidate_switches:
            signature = switch_info.get(switch.agent_id)
            if signature is None:
                continue
            if signature in switch_by_info:
                duplicate_info.add(signature)
            else:
                switch_by_info[signature] = switch.agent_id
        for signature in duplicate_info:
            switch_by_info.pop(signature, None)

        sequence: list[int] = []
        for marker in marker_sequence:
            signature = marker_info.get(marker.agent_id)
            switch_agent_id = switch_by_info.get(signature) if signature is not None else None
            if switch_agent_id is None or switch_agent_id in sequence:
                sequence.clear()
                break
            sequence.append(int(switch_agent_id))
        if len(sequence) == _recorder.expected_switch_count:
            _recorder.set_sequence(sequence)
            _click_plan = ClickPlan(_recorder.sequence)
            matched = " -> ".join(str(agent_id) for agent_id in sequence)
            _last_runtime_match_status = f"gadget info match => {matched}"
            _last_events.append(_last_runtime_match_status)
            del _last_events[:-8]
            _set_status("Sequence matched from GadgetInfo signatures.")
            return True

    try:
        marker_runtime = {marker.agent_id: _runtime_snapshot(marker.agent_id) for marker in marker_sequence}
        switch_runtime = {switch.agent_id: _runtime_snapshot(switch.agent_id) for switch in _candidate_switches}
    except Exception as exception:
        _last_runtime_match_status = f"runtime match: snapshot failed ({exception})"
        return False

    key_names = ("full", "c8", "d4_tail", "d4_2", "d4_3")
    for key_name in key_names:
        switch_by_key: dict[tuple[int, ...], int] = {}
        duplicate_keys: set[tuple[int, ...]] = set()
        for switch in _candidate_switches:
            keys = {name: key for name, key in _runtime_match_keys(switch_runtime[switch.agent_id])}
            key = keys.get(key_name)
            if key is None:
                continue
            if key in switch_by_key:
                duplicate_keys.add(key)
            else:
                switch_by_key[key] = switch.agent_id
        for key in duplicate_keys:
            switch_by_key.pop(key, None)
        if len(switch_by_key) < _recorder.expected_switch_count:
            continue

        sequence: list[int] = []
        for marker in marker_sequence:
            keys = {name: key for name, key in _runtime_match_keys(marker_runtime[marker.agent_id])}
            key = keys.get(key_name)
            switch_agent_id = switch_by_key.get(key or ())
            if switch_agent_id is None or switch_agent_id in sequence:
                sequence.clear()
                break
            sequence.append(int(switch_agent_id))
        if len(sequence) != _recorder.expected_switch_count:
            continue

        _recorder.set_sequence(sequence)
        _click_plan = ClickPlan(_recorder.sequence)
        matched = " -> ".join(str(agent_id) for agent_id in sequence)
        _last_runtime_match_status = f"runtime match: {key_name} => {matched}"
        _last_events.append(_last_runtime_match_status)
        del _last_events[:-8]
        _set_status(f"Sequence matched from live runtime fields ({key_name}).")
        return True

    marker_keys = []
    for marker in marker_sequence:
        try:
            marker_keys.append(f"{marker.agent_id}:{runtime_signature(marker_runtime[marker.agent_id])}")
        except Exception:
            marker_keys.append(f"{marker.agent_id}:<runtime failed>")
    _last_runtime_match_status = "runtime match: no unique marker->switch key"
    _last_events.append(_last_runtime_match_status)
    _last_events.extend(marker_keys[:2])
    del _last_events[:-8]
    return False


def _is_truncated_stoc_payload(packet: RawPacket) -> bool:
    if packet.direction != "StoC":
        return False
    if packet.header in {0x000C, 0x000D, 0x001E}:
        return False
    return len(bytes(packet.data or b"")) < 8


def _raw_server_decoded_fields(packet: RawPacket, data: bytes) -> str:
    if len(data) < 8:
        return ""

    try:
        if packet.header == 0x0021:
            agent_id = struct.unpack_from("<I", data, 4)[0]
            return f" agent={agent_id}"
        if packet.header in {0x0029, 0x002B, 0x002E} and len(data) >= 16:
            agent_id = struct.unpack_from("<I", data, 4)[0]
            x = struct.unpack_from("<f", data, 8)[0]
            y = struct.unpack_from("<f", data, 12)[0]
            return f" agent={agent_id} x={x:.0f} y={y:.0f}"
        if packet.header == 0x0025 and len(data) >= 12:
            agent_id = struct.unpack_from("<I", data, 4)[0]
            value = struct.unpack_from("<I", data, 8)[0]
            return f" agent={agent_id} value={value}"
        if packet.header == 0x0044 and len(data) >= 12:
            first = struct.unpack_from("<I", data, 4)[0]
            second = struct.unpack_from("<I", data, 8)[0]
            return f" w1={first} w2={second}"
    except Exception:
        return ""
    return ""


def _raw_server_packet_summary(packet: RawPacket) -> str:
    data = bytes(packet.data or b"")
    start_offset = 4
    if len(data) >= 4:
        first_word = struct.unpack_from("<I", data, 0)[0]
        if (first_word & 0xFFFF) != int(packet.header):
            start_offset = 0
    else:
        start_offset = 0

    words: list[int] = []
    for offset in range(start_offset, min(len(data), start_offset + (6 * 4)), 4):
        if offset + 4 > len(data):
            break
        words.append(struct.unpack_from("<I", data, offset)[0])
    word_text = " ".join(str(word) for word in words) if words else "<none>"
    name = _STOC_HEADER_NAMES.get(int(packet.header), "")
    name_text = f" {name}" if name else ""
    flags: list[str] = []
    if _is_truncated_stoc_payload(packet):
        flags.append("truncated")
    flag_text = f" {' '.join(flags)}" if flags else ""
    decoded_text = _raw_server_decoded_fields(packet, data)
    return f"StoC 0x{packet.header:04X}{name_text} size={packet.size} words={word_text}{decoded_text} bytes={len(data)}{flag_text}"


def _record_raw_server_packet_after_burst(packet: RawPacket) -> None:
    if packet.direction != "StoC" or not _pending_platform_sequence:
        return
    if packet.header in {0x000C, 0x000D, 0x001E}:
        return
    _raw_server_header_counts[packet.header] = _raw_server_header_counts.get(packet.header, 0) + 1
    if len(_last_raw_server_packets) >= 12:
        return
    summary = _raw_server_packet_summary(packet)
    if summary in _last_raw_server_packets:
        return
    _last_raw_server_packets.append(summary)
    if _is_truncated_stoc_payload(packet):
        _set_status("native PacketSniffer is still truncating StoC payloads; restart/reinject Py4GW.dll.")
        _last_events.append("truncated StoC payload; native DLL restart needed")
        del _last_events[:-8]


def _prime_runtime_snapshots() -> None:
    _runtime_snapshots.clear()
    for switch in _candidate_switches:
        try:
            _runtime_snapshots[switch.agent_id] = _runtime_snapshot(switch.agent_id)
        except Exception:
            continue


def _clear_recording_state() -> None:
    global _last_runtime_match_status, _last_runtime_match_attempt_at
    global _auto_click, _click_plan, _last_click_time, _last_move_agent_id, _last_move_time
    global _pending_click_agent_id, _pending_click_started_at
    _recorder.clear()
    _world_create_recorder.clear()
    _pending_platform_sequence.clear()
    _platform_markers.clear()
    _clear_manual_calibration()
    _click_plan = None
    _auto_click = False
    _last_events.clear()
    _last_runtime_changes.clear()
    _last_probe_packets.clear()
    _last_raw_server_packets.clear()
    _last_client_actions.clear()
    _raw_server_header_counts.clear()
    _reset_server_confirmation_tracking()
    _last_runtime_match_status = ""
    _last_runtime_match_attempt_at = 0.0
    _last_click_time = 0.0
    _last_move_agent_id = 0
    _last_move_time = 0.0
    _pending_click_agent_id = 0
    _pending_click_started_at = 0.0
    _prime_runtime_snapshots()
    _clear_packet_logs()


def _reset_active_capture_with_fresh_scan() -> None:
    _refresh_candidates()
    _clear_recording_state()
    _capture_status.reset_recording_window(time.monotonic())
    if len(_candidate_switches) < 4:
        _set_status(
            f"Recording reset, but only {len(_candidate_switches)} nearby switch candidate(s).",
            Py4GW.Console.MessageType.Warning,
        )
        return
    _set_status("Recording reset with fresh switch scan.")


def _start_capture() -> None:
    global _capturing, _ctos_capture_available
    if _capturing:
        _reset_active_capture_with_fresh_scan()
        return

    _capture_status.mark_starting()
    _set_status("Starting packet capture.")
    _refresh_candidates()
    if len(_candidate_switches) < 4:
        _capture_status.mark_failed(f"only {len(_candidate_switches)} switch candidates")
        _set_status(
            f"Only {len(_candidate_switches)} nearby switch candidate(s). Stand on the teleporter platform.",
            Py4GW.Console.MessageType.Warning,
        )
        return

    _clear_recording_state()

    stoc_only = False
    _ctos_capture_available = False
    try:
        started = PACKET_SNIFFER.initialize("both")
    except Exception as exception:
        _capture_status.mark_failed(str(exception))
        _set_status(f"Packet capture failed: {exception}", Py4GW.Console.MessageType.Error)
        return
    if not started:
        try:
            started = PACKET_SNIFFER.initialize("StoC")
        except Exception as exception:
            _capture_status.mark_failed(str(exception))
            _set_status(f"StoC packet capture failed: {exception}", Py4GW.Console.MessageType.Error)
            return
        if not started:
            _capture_status.mark_failed("PacketSniffer refused capture")
            _set_status("Packet capture was refused by PacketSniffer.", Py4GW.Console.MessageType.Error)
            return
        stoc_only = True
    else:
        _ctos_capture_available = True

    _capturing = True
    _capture_status.mark_started(time.monotonic())
    if stoc_only:
        _set_status("Recording switch flashes (StoC only; CToS reset unavailable).")
    else:
        _set_status("Recording switch flashes.")


def _stop_capture(reason: str = "user") -> None:
    global _capturing, _ctos_capture_available
    global _auto_click, _last_click_time, _last_move_agent_id, _last_move_time
    global _pending_click_agent_id, _pending_click_started_at
    _capturing = False
    _ctos_capture_available = False
    _auto_click = False
    _last_click_time = 0.0
    _last_move_agent_id = 0
    _last_move_time = 0.0
    _pending_click_agent_id = 0
    _pending_click_started_at = 0.0
    try:
        PACKET_SNIFFER.terminate("both")
    except TypeError:
        PACKET_SNIFFER.terminate()
    except Exception:
        pass
    _capture_status.mark_stopped(reason)
    _set_status("Recording stopped.")


def _raw_packet_from_entry(entry) -> RawPacket:
    return RawPacket(
        direction=packet_direction_from_entry(entry),
        tick=int(getattr(entry, "tick", 0)),
        header=int(getattr(entry, "header", 0)),
        size=int(getattr(entry, "size", 0)),
        data=bytes(getattr(entry, "data", b"")),
    )


def _map_platform_burst_sequence(platform_sequence: list[int]) -> list[int]:
    if len(platform_sequence) < _recorder.expected_switch_count:
        return []
    if not _PERSISTENT_MAPPINGS_ENABLED:
        return []
    _load_platform_mappings()
    snapshots = _snapshot_gadgets()
    burst_sequence = platform_sequence[: _recorder.expected_switch_count]
    return map_platform_burst_with_known_mappings(
        _platform_mappings.values(),
        snapshots,
        _candidate_switches,
        burst_sequence,
        expected_switch_count=_recorder.expected_switch_count,
    )


def _learn_platform_mapping_from_switch_sequence(switch_sequence: list[int]) -> bool:
    if not _PERSISTENT_MAPPINGS_ENABLED:
        _last_events.append("persistent mapping skipped; sequence is random")
        del _last_events[:-8]
        return False
    if len(_pending_platform_sequence) < _recorder.expected_switch_count:
        return False
    mapping = learn_platform_mapping(
        _snapshot_gadgets(),
        _candidate_switches,
        _pending_platform_sequence[: _recorder.expected_switch_count],
        switch_sequence[: _recorder.expected_switch_count],
    )
    if mapping is None:
        return False

    _load_platform_mappings()
    _platform_mappings[mapping.signature] = mapping
    _save_platform_mappings()
    _last_events.append(f"saved platform mapping {mapping.signature}")
    del _last_events[:-8]
    return True


def _set_manual_sequence(sequence: list[int]) -> None:
    global _click_plan
    _recorder.set_sequence(sequence)
    _click_plan = ClickPlan(_recorder.sequence)


def _complete_manual_calibration(sequence: list[int]) -> None:
    global _auto_click, _click_plan
    mapping_saved = _learn_platform_mapping_from_switch_sequence(sequence)
    _set_manual_sequence(sequence)
    _clear_manual_calibration()
    _auto_click = False
    if mapping_saved:
        _set_status("Manual sequence entered and platform mapping saved.")
    else:
        _set_status("Manual sequence entered for current attempt.")


def _prepare_manual_override_if_needed() -> None:
    global _auto_click, _click_plan
    if not _manual_calibration_sequence and not _manual_slots_active() and _click_plan is not None:
        _recorder.clear()
        _click_plan = None
        _clear_pending_click()
        _auto_click = False


def _valid_manual_switch_agent(agent_id: int) -> bool:
    if not _pending_platform_sequence:
        _set_status("No platform burst is pending for manual calibration.", Py4GW.Console.MessageType.Warning)
        return False

    candidate_ids = {switch.agent_id for switch in _candidate_switches}
    agent_id = int(agent_id)
    if agent_id not in candidate_ids:
        _set_status(f"Agent {agent_id} is not one of the selected switches.", Py4GW.Console.MessageType.Warning)
        return False
    return True


def _record_manual_calibration_switch(agent_id: int) -> None:
    if not _valid_manual_switch_agent(agent_id):
        return

    agent_id = int(agent_id)
    if agent_id in _manual_calibration_sequence or agent_id in _manual_calibration_slots:
        _set_status(f"Agent {agent_id} is already in the manual sequence.", Py4GW.Console.MessageType.Warning)
        return

    _prepare_manual_override_if_needed()

    if _manual_slots_active():
        try:
            slot_index = _manual_calibration_slots.index(0)
        except ValueError:
            _set_status("All manual calibration positions are already set.", Py4GW.Console.MessageType.Warning)
            return
        _manual_calibration_slots[slot_index] = agent_id
        if _manual_slots_complete():
            _complete_manual_calibration(_manual_calibration_slots[: _recorder.expected_switch_count])
            return
        _set_status(
            f"Manual calibration: {_manual_slot_count()}/{_recorder.expected_switch_count} positions set. "
            f"{_manual_slots_text()}"
        )
        return

    _manual_calibration_sequence.append(agent_id)
    if len(_manual_calibration_sequence) < _recorder.expected_switch_count:
        _set_status(
            f"Manual calibration: {len(_manual_calibration_sequence)}/{_recorder.expected_switch_count} switches selected."
        )
        return

    sequence = _manual_calibration_sequence[: _recorder.expected_switch_count]
    _complete_manual_calibration(sequence)


def _migrate_manual_sequence_to_slots() -> None:
    if _manual_slots_active():
        return
    for index, agent_id in enumerate(_manual_calibration_sequence[: _recorder.expected_switch_count]):
        _manual_calibration_slots[index] = int(agent_id)
    _manual_calibration_sequence.clear()


def _record_manual_calibration_switch_at_position(agent_id: int, position: int) -> None:
    if not _valid_manual_switch_agent(agent_id):
        return

    agent_id = int(agent_id)
    position = int(position)
    if position < 1 or position > _recorder.expected_switch_count:
        _set_status(f"Manual position {position} is out of range.", Py4GW.Console.MessageType.Warning)
        return

    _prepare_manual_override_if_needed()
    _migrate_manual_sequence_to_slots()

    slot_index = position - 1
    for index, existing_agent_id in enumerate(_manual_calibration_slots[: _recorder.expected_switch_count]):
        if index != slot_index and int(existing_agent_id) == agent_id:
            _set_status(
                f"Agent {agent_id} is already assigned to position {index + 1}.",
                Py4GW.Console.MessageType.Warning,
            )
            return

    _manual_calibration_slots[slot_index] = agent_id
    if _manual_slots_complete():
        _complete_manual_calibration(_manual_calibration_slots[: _recorder.expected_switch_count])
        return
    _set_status(
        f"Manual calibration: position {position} set to agent {agent_id}. "
        f"{_manual_slots_text()}"
    )


def _reset_click_plan_to_sequence_start() -> bool:
    global _click_plan, _last_click_time, _last_move_agent_id, _last_move_time
    global _pending_click_agent_id, _pending_click_started_at
    sequence = _recorder.sequence
    if len(sequence) < _recorder.expected_switch_count:
        return False
    _click_plan = ClickPlan(sequence)
    _clear_manual_calibration()
    _last_click_time = 0.0
    _last_move_agent_id = 0
    _last_move_time = 0.0
    _pending_click_agent_id = 0
    _pending_click_started_at = 0.0
    _reset_server_confirmation_tracking()
    return True


def _clear_pending_click() -> None:
    global _pending_click_agent_id, _pending_click_started_at
    _pending_click_agent_id = 0
    _pending_click_started_at = 0.0


def _reset_server_confirmation_tracking() -> None:
    global _server_confirmation_plan_id
    _server_confirmation_plan_id = 0
    _server_confirmed_switch_agent_ids.clear()


def _track_server_switch_confirmation(event) -> None:
    global _server_confirmation_plan_id
    if _click_plan is None:
        _reset_server_confirmation_tracking()
        return

    plan_id = id(_click_plan)
    if _server_confirmation_plan_id != plan_id:
        _server_confirmation_plan_id = plan_id
        _server_confirmed_switch_agent_ids.clear()

    if int(event.header) != 0x0115:
        return
    if (int(event.state) & 0x3) == 0:
        return

    sequence = [int(agent_id) for agent_id in _click_plan.sequence if int(agent_id) > 0]
    if int(event.agent_id) not in sequence:
        return

    _server_confirmed_switch_agent_ids.add(int(event.agent_id))
    if _click_plan.complete and set(sequence).issubset(_server_confirmed_switch_agent_ids):
        _set_status("Server confirmed sequence. Step onto the platform.")


def _set_click_progress_status(prefix: str) -> None:
    if _click_plan is None or _click_plan.complete:
        _set_status(f"{prefix}. Wait a few seconds for server sequence confirmation, then step onto the platform.")
        return
    _set_status(f"{prefix}. Next switch: {_click_plan.next_agent_id()}.")


def _advance_click_plan_for_agent(agent_id: int, prefix: str) -> bool:
    if _click_plan is None or _click_plan.complete:
        return False
    expected_agent = _click_plan.next_agent_id()
    agent_id = int(agent_id)
    if expected_agent != agent_id:
        if expected_agent is not None:
            _set_status(
                f"Switch interaction agent {agent_id} ignored; expected {expected_agent}.",
                Py4GW.Console.MessageType.Warning,
            )
        return False

    if not _click_plan.mark_clicked(agent_id):
        return False
    if _pending_click_agent_id == agent_id:
        _clear_pending_click()
    _set_click_progress_status(prefix)
    return True


def _process_pending_click_timeout() -> None:
    if not _pending_click_agent_id:
        return
    if time.monotonic() - _pending_click_started_at < _INTERACT_CONFIRM_TIMEOUT:
        return

    agent_id = _pending_click_agent_id
    _clear_pending_click()
    _advance_click_plan_for_agent(
        agent_id,
        f"No CToS interact confirmation for switch agent {agent_id}; assuming interaction was queued",
    )


def _process_capture() -> None:
    global _auto_click, _click_plan
    if not _capturing:
        return

    candidate_ids = {switch.agent_id for switch in _candidate_switches}
    candidate_gadget_id_to_agent_id = {
        switch.gadget_id: switch.agent_id
        for switch in _candidate_switches
        if switch.gadget_id > 0
    }
    candidate_gadget_ids = set(candidate_gadget_id_to_agent_id.keys())
    marker_agent_ids = {marker.agent_id for marker in _platform_markers} | set(_pending_platform_sequence)
    marker_gadget_ids = {marker.gadget_id for marker in _platform_markers if marker.gadget_id > 0}
    tracked_agent_ids = candidate_ids | marker_agent_ids
    tracked_gadget_ids = candidate_gadget_ids | marker_gadget_ids
    tracked_gadget_id_to_agent_id = dict(candidate_gadget_id_to_agent_id)
    for marker in _platform_markers:
        if marker.gadget_id > 0 and marker.gadget_id not in tracked_gadget_id_to_agent_id:
            tracked_gadget_id_to_agent_id[marker.gadget_id] = marker.agent_id
    logs = _safe_packet_logs()
    stoc_count = 0
    ctos_count = 0
    matched_this_tick = 0
    for entry in logs:
        packet = _raw_packet_from_entry(entry)
        if packet.direction == "StoC":
            stoc_count += 1
        elif packet.direction == "CToS":
            ctos_count += 1

        if packet.direction == "CToS":
            client_action = client_action_summary(
                packet,
                candidate_agent_ids=candidate_ids,
                candidate_gadget_ids=candidate_gadget_ids,
            )
            if client_action is not None:
                _last_client_actions.append(client_action)
                del _last_client_actions[:-8]
            reset_event = decode_client_sequence_reset_packet(
                packet,
                candidate_agent_ids=candidate_ids,
            )
            if reset_event is not None:
                _last_events.append(
                    f"CToS reset target={reset_event.agent_id} tick={reset_event.tick}"
                )
                del _last_events[:-8]
                if _reset_click_plan_to_sequence_start():
                    matched_this_tick += 1
                    _set_status(f"Sequence reset by client packet. Restart at {_click_plan.next_agent_id()}.")
                else:
                    _clear_manual_calibration()
                    _set_status("Sequence reset by client packet; waiting for platform burst.")
                continue

            interact_event = decode_client_interact_packet(
                packet,
                candidate_agent_ids=candidate_ids,
            )
            if interact_event is not None:
                _last_events.append(
                    f"CToS interact agent={interact_event.agent_id} tick={interact_event.tick}"
                )
                del _last_events[:-8]
                matched_this_tick += 1
                if _click_plan is not None and not _click_plan.complete:
                    advanced = _advance_click_plan_for_agent(
                        interact_event.agent_id,
                        f"CToS interact confirmed for switch agent {interact_event.agent_id}",
                    )
                    if not advanced and _pending_platform_sequence and not _pending_click_agent_id:
                        _record_manual_calibration_switch(interact_event.agent_id)
                    continue
                if _click_plan is None and _pending_platform_sequence:
                    _record_manual_calibration_switch(interact_event.agent_id)
                    continue
        else:
            _record_raw_server_packet_after_burst(packet)
            probe = packet_probe_summary(
                packet,
                candidate_agent_ids=tracked_agent_ids,
                candidate_gadget_ids=tracked_gadget_ids,
            )
            if probe is not None:
                _last_probe_packets.append(probe)
                del _last_probe_packets[:-8]
            world_create_event = decode_world_create_switch_packet(
                packet,
                candidate_ids,
                candidate_gadget_id_to_agent_id=candidate_gadget_id_to_agent_id,
            )
            matched_world_create = world_create_event is not None
            if world_create_event is None:
                world_create_event = decode_world_create_agent_packet(packet)
            if world_create_event is not None:
                event_label = "platform" if matched_world_create else "platform unmatched"
                _last_events.append(
                    f"0x0020 {event_label} agent={world_create_event.agent_id} tick={world_create_event.tick}"
                )
                del _last_events[:-8]
                platform_sequence = _world_create_recorder.record(world_create_event)
                if platform_sequence is not None and (_click_plan is None or _click_plan.complete):
                    _, manual_cleared = _accept_platform_burst_sequence(platform_sequence)
                    agents = " -> ".join(str(agent_id) for agent_id in platform_sequence)
                    if _try_map_pending_burst_from_runtime(force=True):
                        matched_this_tick += _recorder.expected_switch_count
                        continue
                    mapped_sequence = _map_platform_burst_sequence(platform_sequence)
                    if len(mapped_sequence) >= _recorder.expected_switch_count:
                        _recorder.set_sequence(mapped_sequence)
                        _click_plan = ClickPlan(_recorder.sequence)
                        matched_this_tick += len(mapped_sequence)
                        mapped_agents = " -> ".join(str(agent_id) for agent_id in mapped_sequence)
                        _last_events.append(f"mapped platform burst {agents} as {mapped_agents}")
                        del _last_events[:-8]
                        _set_status("Sequence mapped from platform burst.")
                    else:
                        _auto_click = False
                        if manual_cleared:
                            _set_status(
                                f"Platform burst changed; manual calibration cleared. New random burst: {agents}.",
                                Py4GW.Console.MessageType.Warning,
                            )
                        else:
                            _set_status(
                                f"Random platform burst captured ({agents}); waiting for live switch flashes or Add buttons.",
                                Py4GW.Console.MessageType.Warning,
                            )

        event = decode_gadget_state_packet(
            packet,
            tracked_agent_ids,
            candidate_gadget_id_to_agent_id=tracked_gadget_id_to_agent_id,
        )
        if event is None:
            continue
        matched_this_tick += 1
        if event.agent_id in marker_agent_ids and event.agent_id not in candidate_ids:
            _last_events.append(
                f"0x{event.header:04X} marker agent={event.agent_id} state=0x{event.state:X} tick={event.tick}"
            )
            del _last_events[:-8]
            continue
        _recorder.record(event)
        _last_events.append(
            f"0x{event.header:04X} agent={event.agent_id} state=0x{event.state:X} tick={event.tick}"
        )
        del _last_events[:-8]
        _track_server_switch_confirmation(event)

    _capture_status.add_packets(stoc=stoc_count, ctos=ctos_count, matches=matched_this_tick)
    _clear_packet_logs()
    _try_map_pending_burst_from_runtime()

    if _recorder.complete and _click_plan is None:
        _click_plan = ClickPlan(_recorder.sequence)
        _set_status("Sequence captured.")


def _process_runtime_changes() -> None:
    if not _runtime_diagnostics_enabled:
        return
    if not _capturing or not _candidate_switches:
        return
    if not _runtime_snapshots:
        _prime_runtime_snapshots()
        return

    now_tick = int(time.monotonic() * 1000)
    runtime_matches = 0
    for switch in _candidate_switches:
        try:
            current = _runtime_snapshot(switch.agent_id)
        except Exception:
            continue

        previous = _runtime_snapshots.get(switch.agent_id)
        _runtime_snapshots[switch.agent_id] = current
        if previous is None:
            continue

        changed_fields = runtime_delta_fields(previous, current)
        if not changed_fields:
            continue

        runtime_matches += 1
        _last_runtime_changes.append(
            f"agent={current.agent_id} fields={','.join(changed_fields)} "
            f"ve=0x{current.visual_effects:X} c4={current.h00c4} c8={current.h00c8}"
        )
        del _last_runtime_changes[:-8]

    if runtime_matches:
        _capture_status.add_packets(matches=runtime_matches)


def _click_next_switch() -> None:
    global _last_click_time, _last_move_agent_id, _last_move_time
    global _pending_click_agent_id, _pending_click_started_at
    if _click_plan is None:
        return
    if not _capturing:
        _set_status("Start recording before clicking switches.", Py4GW.Console.MessageType.Warning)
        return
    if _pending_click_agent_id:
        _set_status(f"Waiting for CToS 0x39 confirmation for switch agent {_pending_click_agent_id}.")
        return
    agent_id = _click_plan.next_agent_id()
    if agent_id is None:
        _set_status("Sequence already complete.")
        return

    now = time.monotonic()
    decision = plan_switch_interaction(
        agent_id,
        _candidate_switches,
        player_xy=Player.GetXY(),
        interact_distance=_INTERACT_DISTANCE,
    )
    if decision is not None and not decision.in_range:
        if _last_move_agent_id != agent_id or now - _last_move_time >= _MOVE_REISSUE_DELAY:
            Player.Move(decision.x, decision.y)
            _last_move_agent_id = agent_id
            _last_move_time = now
            _set_status(f"Moving to switch agent {agent_id}.")
        _last_click_time = now
        return

    Player.Interact(agent_id, False)
    _last_click_time = now
    _last_move_agent_id = 0
    _last_move_time = 0.0
    if _ctos_capture_available:
        _pending_click_agent_id = agent_id
        _pending_click_started_at = now
        _set_status(f"Interacted with switch agent {agent_id}; waiting for CToS 0x39 confirmation.")
    else:
        _advance_click_plan_for_agent(agent_id, f"Interacted with switch agent {agent_id}")


def _auto_click_tick() -> None:
    _process_pending_click_timeout()
    if not _auto_click or _click_plan is None or _click_plan.complete:
        return
    if _pending_click_agent_id:
        return
    if time.monotonic() - _last_click_time >= _AUTO_CLICK_DELAY:
        _click_next_switch()


def _draw_switch_table() -> None:
    selected_target_id = _safe_selected_target_id()
    PyImGui.text(f"Switch candidates: {len(_candidate_switches)}")
    for index, switch in enumerate(_candidate_switches, start=1):
        label = switch.name or f"agent {switch.agent_id}"
        selected_marker = " [selected]" if int(switch.agent_id) == selected_target_id else ""
        runtime_text = ""
        try:
            runtime = _runtime_snapshot(switch.agent_id)
            runtime_text = f"  rt={runtime_signature(runtime)}"
        except Exception:
            runtime_text = ""
        PyImGui.text(
            f"{index}. {label}{selected_marker}  agent={switch.agent_id}  gadget={switch.gadget_id}  "
            f"xy=({switch.x:.0f}, {switch.y:.0f}) {_gadget_info_text(switch.gadget_id)}{runtime_text}"
        )
        if _pending_platform_sequence:
            PyImGui.same_line(0, 6)
            if PyImGui.button(f"Add##cdt_manual_{switch.agent_id}"):
                _record_manual_calibration_switch(switch.agent_id)


def _draw_sequence() -> None:
    _load_platform_mappings()
    sequence = _recorder.sequence
    text = " -> ".join(str(agent_id) for agent_id in sequence) if sequence else "<empty>"
    PyImGui.text(f"Build: {MODULE_BUILD}")
    PyImGui.text(f"Sequence: {text}")
    PyImGui.text(_selected_target_summary())
    pending = " -> ".join(str(agent_id) for agent_id in _pending_platform_sequence) if _pending_platform_sequence else "<none>"
    mapping_state = "on" if _PERSISTENT_MAPPINGS_ENABLED else "off"
    PyImGui.text(f"Persistent mappings: {mapping_state} ({len(_platform_mappings)})  Pending burst: {pending}")
    if _platform_markers:
        markers = " ".join(f"{marker.agent_id}/{marker.gadget_id}" for marker in _platform_markers)
        PyImGui.text(f"Tracked markers: {markers}")
        for marker in _platform_markers[: _recorder.expected_switch_count]:
            try:
                PyImGui.text(
                    f"Marker {marker.agent_id}/{marker.gadget_id}: "
                    f"{_gadget_info_text(marker.gadget_id)} {runtime_signature(_runtime_snapshot(marker.agent_id))}"
                )
            except Exception:
                PyImGui.text(f"Marker {marker.agent_id}/{marker.gadget_id}: {_gadget_info_text(marker.gadget_id)} <runtime unavailable>")
    if _last_runtime_match_status:
        PyImGui.text(_last_runtime_match_status)
    if _manual_calibration_sequence:
        manual = " -> ".join(str(agent_id) for agent_id in _manual_calibration_sequence)
        PyImGui.text(f"Manual: {manual}")
    if _manual_slots_active():
        PyImGui.text(f"Manual positions: {_manual_slots_text()}")
    PyImGui.text(_capture_status.summary(capturing=_capturing, now=time.monotonic()))
    if _click_plan is not None:
        next_agent = _click_plan.next_agent_id()
        PyImGui.text(f"Next: {next_agent if next_agent is not None else '<done>'}")


def _draw_controls() -> None:
    global _last_runtime_match_status, _last_runtime_match_attempt_at
    global _auto_click, _click_plan, _last_click_time, _last_move_agent_id, _last_move_time
    global _pending_click_agent_id, _pending_click_started_at
    if PyImGui.button("Scan switches"):
        _refresh_candidates()
        _recorder.clear()
        _world_create_recorder.clear()
        _pending_platform_sequence.clear()
        _platform_markers.clear()
        _clear_manual_calibration()
        _click_plan = None
        _auto_click = False
        _last_click_time = 0.0
        _last_move_agent_id = 0
        _last_move_time = 0.0
        _pending_click_agent_id = 0
        _pending_click_started_at = 0.0
        _last_raw_server_packets.clear()
        _raw_server_header_counts.clear()
        _reset_server_confirmation_tracking()
        _last_runtime_match_status = ""
        _last_runtime_match_attempt_at = 0.0
        _prime_runtime_snapshots()
        _clear_packet_logs()
        _set_status(f"{len(_candidate_switches)} switch candidate(s) selected. Press Record to start capture.")

    PyImGui.same_line(0, 6)
    if PyImGui.button("Scan + Record"):
        _start_capture()

    PyImGui.same_line(0, 6)
    if not _capturing:
        if PyImGui.button("Record"):
            _start_capture()
    else:
        if PyImGui.button("Stop"):
            _stop_capture("user")

    PyImGui.same_line(0, 6)
    if PyImGui.button("Reset"):
        _recorder.clear()
        _world_create_recorder.clear()
        _last_events.clear()
        _last_runtime_changes.clear()
        _last_probe_packets.clear()
        _last_raw_server_packets.clear()
        _last_client_actions.clear()
        _raw_server_header_counts.clear()
        _reset_server_confirmation_tracking()
        _last_runtime_match_status = ""
        _last_runtime_match_attempt_at = 0.0
        _pending_platform_sequence.clear()
        _platform_markers.clear()
        _clear_manual_calibration()
        _click_plan = None
        _auto_click = False
        _last_click_time = 0.0
        _last_move_agent_id = 0
        _last_move_time = 0.0
        _pending_click_agent_id = 0
        _pending_click_started_at = 0.0
        _clear_packet_logs()
        _prime_runtime_snapshots()
        if _capturing:
            _capture_status.reset_recording_window(time.monotonic())
            _set_status("Recording reset.")
        else:
            _capture_status.reset_all()
            _set_status("Reset.")

    PyImGui.same_line(0, 6)
    if PyImGui.button("Forget learned"):
        _forget_learned_mappings()

    PyImGui.same_line(0, 6)
    if PyImGui.button("Learn clicks"):
        _begin_manual_click_learning()

    PyImGui.same_line(0, 6)
    if PyImGui.button("Add selected"):
        _record_selected_target_switch()

    if _pending_platform_sequence:
        for position in range(1, _recorder.expected_switch_count + 1):
            PyImGui.same_line(0, 6)
            if PyImGui.button(f"Set #{position}"):
                _record_selected_target_switch_at_position(position)

    if _click_plan is not None:
        if PyImGui.button("Click next"):
            _click_next_switch()
        PyImGui.same_line(0, 6)
        _auto_click = PyImGui.checkbox("Auto click", _auto_click)


def main() -> None:
    global _capturing
    try:
        if not Checks.Map.MapValid():
            if _capturing:
                _stop_capture("map invalid")
            return

        _process_capture()
        _process_runtime_changes()
        _auto_click_tick()

        PyImGui.set_next_window_size((560, 260), PyImGui.ImGuiCond.FirstUseEver)
        if PyImGui.begin(MODULE_NAME, PyImGui.WindowFlags.AlwaysAutoResize):
            _draw_controls()
            PyImGui.separator()
            PyImGui.text(f"Status: {_status}")
            _draw_sequence()
            PyImGui.separator()
            _draw_switch_table()
            if _last_events:
                PyImGui.separator()
                PyImGui.text("Recent sequence events:")
                for line in _last_events[-5:]:
                    PyImGui.text(line)
            if _last_runtime_changes:
                PyImGui.separator()
                PyImGui.text("Recent runtime changes:")
                for line in _last_runtime_changes[-5:]:
                    PyImGui.text(line)
            if _last_probe_packets:
                PyImGui.separator()
                PyImGui.text("Recent server probes:")
                for line in _last_probe_packets[-5:]:
                    PyImGui.text(line)
            if _last_raw_server_packets:
                PyImGui.separator()
                PyImGui.text("First raw StoC after burst:")
                for line in _last_raw_server_packets[:6]:
                    PyImGui.text(line)
                if _raw_server_header_counts:
                    counts = " ".join(
                        f"0x{header:04X}:{count}"
                        for header, count in sorted(
                            _raw_server_header_counts.items(),
                            key=lambda item: (-item[1], item[0]),
                        )[:8]
                    )
                    PyImGui.text(f"Raw StoC header counts: {counts}")
            if _last_client_actions:
                PyImGui.separator()
                PyImGui.text("Recent client packets (not sequence):")
                for line in _last_client_actions[-5:]:
                    PyImGui.text(line)
        PyImGui.end()
    except Exception as exception:
        _capturing = False
        Py4GW.Console.Log(MODULE_NAME, f"Error: {exception}", Py4GW.Console.MessageType.Error)
        Py4GW.Console.Log(MODULE_NAME, traceback.format_exc(), Py4GW.Console.MessageType.Error)


if __name__ == "__main__":
    main()
