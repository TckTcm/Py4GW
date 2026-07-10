"""Compare manual and Py4GW locked-chest targeting in the live client."""

from __future__ import annotations

from collections import deque
import time

import PyImGui

from Py4GWCoreLib import Agent, Player
from Py4GWCoreLib.PacketSniffer import SNIFFER as PACKET_SNIFFER


MODULE_NAME = "Locked Chest Target Probe"
MODULE_BUILD = "manual-vs-py4gw-v5"

_capture_active = False
_status = "Press Arm manual, then click the locked chest once."
_manual_target_id = 0
_manual_sample: dict[str, int | bool] | None = None
_py4gw_sample: dict[str, int | bool] | None = None
_manual_baseline_revision = 0
_manual_armed = False
_replay_stage = ""
_replay_baseline_revision = 0
_replay_started_at = 0.0
_remote_open_stage = ""
_remote_open_target_id = 0
_remote_open_started_at = 0.0
_last_seen_change_revision = -1
_events: deque[str] = deque(maxlen=20)
_packets: deque[str] = deque(maxlen=30)


def _state() -> dict[str, int | bool]:
    try:
        return Player.GetTargetSelectionState()
    except Exception:
        return {}


def _revision(state: dict[str, int | bool]) -> int:
    return int(state.get("change_revision", 0))


def _format_state(label: str, state: dict[str, int | bool]) -> str:
    return (
        f"{label}: req=({int(state.get('requested_manual_target_id', 0))},"
        f"{int(state.get('requested_auto_target_id', 0))}) "
        f"eval={int(state.get('evaluated_target_id', 0))} "
        f"auto={int(state.get('auto_target_id', 0))} "
        f"manual={int(state.get('manual_target_id', 0))} "
        f"changed=({int(bool(state.get('evaluated_target_changed', False)))},"
        f"{int(bool(state.get('auto_target_changed', False)))},"
        f"{int(bool(state.get('manual_target_changed', False)))}) "
        f"rev={_revision(state)}"
    )


def _capture_manual_target(
    target_id: int,
    state: dict[str, int | bool],
    source: str,
) -> bool:
    global _manual_armed, _manual_target_id, _manual_sample, _status
    if target_id == 0 or target_id == Player.GetAgentID():
        return False
    try:
        if not Agent.IsGadget(target_id):
            return False
    except Exception:
        return False
    _manual_target_id = target_id
    _manual_sample = dict(state) if state else None
    _manual_armed = False
    _status = (
        f"Manual sample captured for gadget agent {target_id} via {source}. "
        "Press Replay Py4GW."
    )
    return True


def _start_capture() -> bool:
    global _capture_active
    if _capture_active:
        return True
    PACKET_SNIFFER.clear_logs("CToS")
    _capture_active = bool(PACKET_SNIFFER.initialize("CToS"))
    return _capture_active


def _stop_capture() -> None:
    global _capture_active
    if not _capture_active:
        return
    _drain_packets()
    PACKET_SNIFFER.terminate("CToS")
    _capture_active = False


def _drain_packets() -> None:
    global _remote_open_stage, _status
    if not _capture_active:
        return
    logs = PACKET_SNIFFER.get_logs("CToS")
    for entry in logs:
        raw = bytes(entry.data)
        header = int(entry.header)
        decoded = PACKET_SNIFFER.decode_packet("CToS", header, int(entry.size), raw)
        _packets.append(f"{decoded} raw={raw[:24].hex(' ')}")
        if _manual_armed and header == 0x51 and len(raw) >= 8:
            target_id = int.from_bytes(raw[4:8], "little")
            if target_id == Player.GetTargetID():
                _capture_manual_target(target_id, _state(), "INTERACT_GADGET")
        if _remote_open_stage == "wait_open_packet" and header == 0x53 and len(raw) >= 8:
            open_flag = int.from_bytes(raw[4:8], "little")
            _remote_open_stage = ""
            _status = f"Remote OPEN_CHEST captured with flag {open_flag}; no movement issued."
    if logs:
        PACKET_SNIFFER.clear_logs("CToS")


def _arm_manual() -> None:
    global _manual_armed, _manual_baseline_revision, _status
    global _manual_target_id, _manual_sample, _py4gw_sample, _replay_stage
    _events.clear()
    _packets.clear()
    _manual_target_id = 0
    _manual_sample = None
    _py4gw_sample = None
    _replay_stage = ""
    if not _start_capture():
        _status = "Native CToS capture failed. Reinject the matching Py4GW.dll."
        return
    state = _state()
    _manual_baseline_revision = _revision(state)
    _manual_armed = True
    _status = "Armed. Manually click the locked chest once."


def _start_py4gw_replay() -> None:
    global _replay_stage, _replay_baseline_revision, _replay_started_at, _status
    if _manual_target_id == 0:
        _status = "Capture a manual chest target first."
        return
    if not _start_capture():
        _status = "Native CToS capture failed."
        return

    state = _state()
    _replay_baseline_revision = _revision(state)
    _replay_started_at = time.monotonic()
    if int(state.get("manual_target_id", 0)) == _manual_target_id:
        Player.ChangeTargetManual(Player.GetAgentID())
        _replay_stage = "clear"
        _status = "Switching away before replaying the Py4GW target."
    else:
        Player.ChangeTargetManual(_manual_target_id)
        _replay_stage = "target"
        _status = f"Py4GW target request sent for chest agent {_manual_target_id}."


def _resolve_chest_target() -> int:
    target_id = _manual_target_id or Player.GetTargetID()
    if target_id == 0:
        return 0
    try:
        return target_id if Agent.IsGadget(target_id) else 0
    except Exception:
        return 0


def _start_remote_open() -> None:
    global _manual_target_id, _remote_open_stage, _remote_open_target_id
    global _remote_open_started_at, _status
    target_id = _resolve_chest_target()
    if target_id == 0:
        _status = "Capture or select a locked chest first."
        return

    _manual_target_id = target_id
    _remote_open_target_id = target_id
    _remote_open_started_at = time.monotonic()
    if not _start_capture():
        _status = "Native CToS capture failed. Reinject the matching Py4GW.dll."
        return

    state = _state()
    if (
        int(state.get("manual_target_id", 0)) == target_id
        and Player.GetTargetID() == target_id
    ):
        if not Player.OpenLockedChest(False):
            _remote_open_stage = ""
            _status = "Native remote-open request was rejected."
            return
        _remote_open_stage = "wait_open_packet"
        _status = f"Remote lockpick request queued once for chest agent {target_id}."
        return

    Player.ChangeTargetManual(target_id)
    _remote_open_stage = "wait_target"
    _status = f"Establishing native manual target for chest agent {target_id}."


def _poll_remote_open() -> None:
    global _remote_open_stage, _status
    if not _remote_open_stage:
        return
    if time.monotonic() - _remote_open_started_at > 10.0:
        _status = f"Timed out during remote chest stage {_remote_open_stage}."
        _remote_open_stage = ""
        return

    if _remote_open_stage == "wait_target":
        state = _state()
        if (
            int(state.get("manual_target_id", 0)) == _remote_open_target_id
            and Player.GetTargetID() == _remote_open_target_id
        ):
            if not Player.OpenLockedChest(False):
                _remote_open_stage = ""
                _status = "Native remote-open request was rejected."
                return
            _remote_open_stage = "wait_open_packet"
            _status = f"Remote lockpick request queued once for chest agent {_remote_open_target_id}."
        return


def _poll_target_state() -> None:
    global _last_seen_change_revision, _manual_armed, _manual_target_id
    global _manual_sample, _py4gw_sample, _replay_stage
    global _replay_baseline_revision, _replay_started_at, _status

    state = _state()
    if not state:
        return
    revision = _revision(state)
    if revision != _last_seen_change_revision:
        _last_seen_change_revision = revision
        _events.append(_format_state("event", state))

    if _manual_armed and revision > _manual_baseline_revision:
        target_id = int(state.get("manual_target_id", 0))
        _capture_manual_target(target_id, state, "target transition")

    if not _replay_stage:
        return

    if time.monotonic() - _replay_started_at > 3.0:
        _status = f"Timed out during Py4GW replay stage {_replay_stage}."
        _replay_stage = ""
        return

    if revision <= _replay_baseline_revision:
        return

    if _replay_stage == "clear":
        _replay_baseline_revision = revision
        _replay_started_at = time.monotonic()
        Player.ChangeTargetManual(_manual_target_id)
        _replay_stage = "target"
        _status = f"Py4GW target request sent for chest agent {_manual_target_id}."
        return

    if _replay_stage == "target":
        _py4gw_sample = dict(state)
        _replay_stage = ""
        if int(state.get("manual_target_id", 0)) == _manual_target_id:
            _status = "Py4GW reproduced the native manual target state."
        else:
            _status = "Py4GW target state differs from the manual sample."


def _draw_sample(label: str, sample: dict[str, int | bool] | None) -> None:
    if sample is None:
        PyImGui.text(f"{label}: <not captured>")
    else:
        PyImGui.text_wrapped(_format_state(label, sample))


def draw_window() -> None:
    PyImGui.set_next_window_size((760, 480), PyImGui.ImGuiCond.FirstUseEver)
    if PyImGui.begin(MODULE_NAME, PyImGui.WindowFlags.AlwaysAutoResize):
        if PyImGui.button("Arm manual"):
            _arm_manual()
        PyImGui.same_line(0.0, 6.0)
        if PyImGui.button("Replay Py4GW"):
            _start_py4gw_replay()
        PyImGui.same_line(0.0, 6.0)
        if PyImGui.button("Open sampled chest"):
            _start_remote_open()
        PyImGui.same_line(0.0, 6.0)
        if PyImGui.button("Stop capture"):
            _stop_capture()

        PyImGui.separator()
        PyImGui.text(f"Build: {MODULE_BUILD}")
        PyImGui.text_wrapped(f"Status: {_status}")
        PyImGui.text(f"Player target: {Player.GetTargetID()}  sampled chest: {_manual_target_id}")
        if _manual_target_id:
            PyImGui.text(
                f"Chest gadget={Agent.GetGadgetID(_manual_target_id)} "
                f"extra={Agent.GetGadgetAgentExtraType(_manual_target_id)}"
            )
        _draw_sample("manual", _manual_sample)
        _draw_sample("py4gw", _py4gw_sample)

        PyImGui.separator()
        PyImGui.text("Target transitions")
        for event in reversed(_events):
            PyImGui.text_wrapped(event)

        PyImGui.separator()
        PyImGui.text("CToS packets")
        if not _packets:
            PyImGui.text("<none: target selection itself is local client state>")
        for packet in reversed(_packets):
            PyImGui.text_wrapped(packet)
    PyImGui.end()


def main() -> None:
    _drain_packets()
    _poll_target_state()
    _poll_remote_open()
    draw_window()
