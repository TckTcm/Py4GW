from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Iterable, Literal, Mapping


PacketDirection = Literal["StoC", "CToS"]

# WASM RE notes:
# - OnMsgState(packet, ...):      agent_id = *(u32*)(packet + 4), state = *(u32*)(packet + 8)
# - GadgetCliOnState(...):       state bit 0 calls AvGadgetActivate, otherwise deactivate
# - MANIPULATE_MAP_OBJECT uses object_id/gadget_id at +4, animation at +8, stage at +12.
# - MANIPULATE_MAP_OBJECT2 uses object_id/gadget_id at +4 and state at +12.
# - AGENT_PROPERTY_UPDATE_INT uses prop_id at +4, agent_id at +8, value at +12.
# - AGENT_PROPERTY_UPDATE_FLOAT uses prop_id at +4, agent_id at +8, value at +12.
DIRECT_GADGET_STATE_HEADERS = frozenset({0x0115})
MAP_OBJECT_ANIMATION_HEADERS = frozenset({0x010E})
MAP_OBJECT_STATE_HEADERS = frozenset({0x0111})
AGENT_PROPERTY_INT_STATE_HEADERS = frozenset({0x009F})
AGENT_PROPERTY_FLOAT_STATE_HEADERS = frozenset({0x00A2})
TARGETING_NOISE_HEADERS = frozenset({0x0051, 0x00C1})
CLIENT_SWITCH_CLICK_HEADERS = frozenset({0x00C1})
CLIENT_INTERACT_HEADERS = frozenset({0x0039})
WORLD_CREATE_AGENT_HEADERS = frozenset({0x0020})
GADGET_STATE_HEADER_CANDIDATES = (
    MAP_OBJECT_ANIMATION_HEADERS
    | MAP_OBJECT_STATE_HEADERS
    | AGENT_PROPERTY_INT_STATE_HEADERS
    | AGENT_PROPERTY_FLOAT_STATE_HEADERS
    | DIRECT_GADGET_STATE_HEADERS
)


@dataclass(frozen=True, slots=True)
class RawPacket:
    direction: PacketDirection
    tick: int
    header: int
    size: int
    data: bytes


@dataclass(frozen=True, slots=True)
class GadgetStateEvent:
    tick: int
    header: int
    agent_id: int
    state: int

    @property
    def active(self) -> bool:
        return (self.state & 1) != 0


@dataclass(frozen=True, slots=True)
class GadgetSnapshot:
    agent_id: int
    x: float
    y: float
    name: str = ""
    gadget_id: int = 0
    extra_type: int = 0

    def distance_to(self, center: tuple[float, float]) -> float:
        return math.hypot(self.x - center[0], self.y - center[1])


@dataclass(frozen=True, slots=True)
class SwitchInteractionDecision:
    agent_id: int
    x: float
    y: float
    distance: float
    in_range: bool


@dataclass(frozen=True, slots=True)
class GadgetRuntimeSnapshot:
    agent_id: int
    visual_effects: int
    h00c4: int
    h00c8: int
    h00d4: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PlatformMapping:
    signature: str
    marker_to_switch_gadget_ids: tuple[tuple[int, int], ...]


@dataclass(slots=True)
class CaptureStatus:
    start_attempts: int = 0
    started_at: float | None = None
    last_result: str = "never"
    stoc_scanned: int = 0
    ctos_scanned: int = 0
    state_matches: int = 0

    def reset_packets(self) -> None:
        self.stoc_scanned = 0
        self.ctos_scanned = 0
        self.state_matches = 0

    def reset_all(self) -> None:
        self.start_attempts = 0
        self.started_at = None
        self.last_result = "never"
        self.reset_packets()

    def reset_recording_window(self, now: float) -> None:
        if self.start_attempts <= 0:
            self.start_attempts = 1
        self.started_at = float(now)
        self.last_result = "started"
        self.reset_packets()

    def mark_starting(self) -> None:
        self.start_attempts += 1
        self.started_at = None
        self.last_result = "starting"
        self.reset_packets()

    def mark_started(self, now: float) -> None:
        self.started_at = float(now)
        self.last_result = "started"

    def mark_failed(self, reason: str) -> None:
        self.started_at = None
        self.last_result = f"failed: {reason}"

    def mark_stopped(self, reason: str) -> None:
        self.started_at = None
        self.last_result = f"stopped: {reason}"

    def add_packets(self, *, stoc: int = 0, ctos: int = 0, matches: int = 0) -> None:
        self.stoc_scanned += max(0, int(stoc))
        self.ctos_scanned += max(0, int(ctos))
        self.state_matches += max(0, int(matches))

    def summary(self, *, capturing: bool, now: float) -> str:
        age = 0.0 if self.started_at is None else max(0.0, float(now) - self.started_at)
        state = "on" if capturing else "off"
        return (
            f"Capture: {state}  attempts={self.start_attempts}  last={self.last_result}  "
            f"age={age:.1f}s  StoC={self.stoc_scanned}  CToS={self.ctos_scanned}  "
            f"matches={self.state_matches}"
        )


def _u32(data: bytes, offset: int) -> int | None:
    if len(data) < offset + 4:
        return None
    return struct.unpack_from("<I", data, offset)[0]


def _f32(data: bytes, offset: int) -> float | None:
    if len(data) < offset + 4:
        return None
    return struct.unpack_from("<f", data, offset)[0]


def _u32_words(data: bytes, *, start: int = 4, limit: int = 12) -> list[int]:
    words: list[int] = []
    for offset in range(start, min(len(data), start + (limit * 4)), 4):
        if offset + 4 > len(data):
            break
        words.append(struct.unpack_from("<I", data, offset)[0])
    return words


def _u32_ascii(value: int) -> str:
    raw = struct.pack("<I", int(value) & 0xFFFFFFFF)
    return "".join(chr(byte) if 32 <= byte < 127 else "." for byte in raw)


def runtime_signature(snapshot: GadgetRuntimeSnapshot) -> str:
    d4_text = ",".join(f"0x{value & 0xFFFFFFFF:08X}" for value in snapshot.h00d4[:4])
    return (
        f"ve=0x{snapshot.visual_effects:X} "
        f"c4=0x{snapshot.h00c4 & 0xFFFFFFFF:08X}/{_u32_ascii(snapshot.h00c4)} "
        f"c8=0x{snapshot.h00c8 & 0xFFFFFFFF:08X}/{_u32_ascii(snapshot.h00c8)} "
        f"d4={d4_text}"
    )


def packet_direction_from_entry(entry, default: PacketDirection = "StoC") -> PacketDirection:
    direction = getattr(entry, "direction", default)
    if direction in ("StoC", "CToS"):
        return direction

    name = getattr(direction, "name", None)
    if name in ("StoC", "CToS"):
        return name

    value = getattr(direction, "value", None)
    if value in ("StoC", "CToS"):
        return value

    text = str(direction).lower()
    if "ctos" in text:
        return "CToS"
    if "stoc" in text:
        return "StoC"
    return default


def _minimum_probe_size(header: int) -> int:
    if header in (
        MAP_OBJECT_ANIMATION_HEADERS
        | MAP_OBJECT_STATE_HEADERS
        | AGENT_PROPERTY_INT_STATE_HEADERS
        | AGENT_PROPERTY_FLOAT_STATE_HEADERS
    ):
        return 16
    return 8


def _is_targeting_noise_packet(
    packet: RawPacket,
    *,
    candidate_agent_ids: set[int],
    candidate_gadget_ids: set[int],
    words: list[int],
) -> bool:
    if packet.header not in TARGETING_NOISE_HEADERS:
        return False
    if packet.size != 12 or len(packet.data) != 12 or len(words) < 2:
        return False
    return words[0] in candidate_agent_ids | candidate_gadget_ids and words[1] == 0


def _world_create_agent_summary(words: list[int], candidate_agent_ids: set[int], candidate_gadget_ids: set[int]) -> str | None:
    if len(words) < 4:
        return None
    matches_candidate = words[0] in candidate_agent_ids or words[1] in candidate_gadget_ids
    looks_like_switch_create = words[2] == 2 and words[3] == 1
    if not matches_candidate and not looks_like_switch_create:
        return None

    word_text = " ".join(str(word) for word in words) if words else "<none>"
    x_value = _f32(struct.pack("<I", words[4]), 0) if len(words) >= 5 else None
    x_text = f" x={x_value:.0f}" if x_value is not None else ""
    label = "0x0020 create" if matches_candidate else "0x0020 create unmatched"
    return (
        f"{label} agent={words[0]} gadget={words[1]} "
        f"kind={words[2]} flag={words[3]}{x_text} raw={word_text}"
    )


def packet_probe_summary(
    packet: RawPacket,
    *,
    candidate_agent_ids: Iterable[int],
    candidate_gadget_ids: Iterable[int],
) -> str | None:
    if packet.direction not in ("StoC", "CToS"):
        return None
    if packet.size < _minimum_probe_size(packet.header) or len(packet.data) < _minimum_probe_size(packet.header):
        return None

    candidate_agent_ids = {int(agent_id) for agent_id in candidate_agent_ids}
    candidate_gadget_ids = {int(gadget_id) for gadget_id in candidate_gadget_ids}
    words = _u32_words(packet.data)
    if _is_targeting_noise_packet(
        packet,
        candidate_agent_ids=candidate_agent_ids,
        candidate_gadget_ids=candidate_gadget_ids,
        words=words,
    ):
        return None

    references_candidate = any(word in candidate_agent_ids or word in candidate_gadget_ids for word in words)
    if packet.direction == "CToS":
        if not references_candidate:
            return None
        word_text = " ".join(str(word) for word in words) if words else "<none>"
        return f"CToS 0x{packet.header:04X} size={packet.size} words={word_text}"

    if packet.header in WORLD_CREATE_AGENT_HEADERS:
        return _world_create_agent_summary(words, candidate_agent_ids, candidate_gadget_ids)

    if packet.header not in GADGET_STATE_HEADER_CANDIDATES and not references_candidate:
        return None

    word_text = " ".join(str(word) for word in words) if words else "<none>"
    return f"0x{packet.header:04X} size={packet.size} words={word_text}"


def client_action_summary(
    packet: RawPacket,
    *,
    candidate_agent_ids: Iterable[int],
    candidate_gadget_ids: Iterable[int],
) -> str | None:
    if packet.direction != "CToS":
        return None
    if packet.size < 8 or len(packet.data) < 8:
        return None

    candidate_agent_ids = {int(agent_id) for agent_id in candidate_agent_ids}
    candidate_gadget_ids = {int(gadget_id) for gadget_id in candidate_gadget_ids}
    words = _u32_words(packet.data)
    if _is_targeting_noise_packet(
        packet,
        candidate_agent_ids=candidate_agent_ids,
        candidate_gadget_ids=candidate_gadget_ids,
        words=words,
    ):
        return None
    if not any(word in candidate_agent_ids or word in candidate_gadget_ids for word in words):
        return None

    word_text = " ".join(str(word) for word in words) if words else "<none>"
    return f"CToS action 0x{packet.header:04X} size={packet.size} words={word_text}"


def decode_client_switch_click_packet(
    packet: RawPacket,
    *,
    candidate_agent_ids: Iterable[int],
) -> GadgetStateEvent | None:
    # RE check: CToS 0x00C1 is CharMsgSendAgentSelection(a, b), called from
    # IAgentView::SetSelections. It can appear when merely targeting a switch,
    # so it is not a reliable proof that a teleporter switch was activated.
    return None


def decode_client_interact_packet(
    packet: RawPacket,
    *,
    candidate_agent_ids: Iterable[int],
) -> GadgetStateEvent | None:
    if packet.direction != "CToS":
        return None
    if packet.header not in CLIENT_INTERACT_HEADERS:
        return None
    if packet.size < 12 or len(packet.data) < 12:
        return None

    candidate_agent_ids = {int(agent_id) for agent_id in candidate_agent_ids}
    words = _u32_words(packet.data, limit=2)
    if len(words) < 2:
        return None

    agent_id = int(words[0])
    if agent_id not in candidate_agent_ids:
        return None
    return GadgetStateEvent(tick=int(packet.tick), header=int(packet.header), agent_id=agent_id, state=1)


def decode_client_sequence_reset_packet(
    packet: RawPacket,
    *,
    candidate_agent_ids: Iterable[int],
) -> GadgetStateEvent | None:
    if packet.direction != "CToS":
        return None
    if packet.header not in CLIENT_SWITCH_CLICK_HEADERS:
        return None
    if packet.size < 12 or len(packet.data) < 12:
        return None

    candidate_agent_ids = {int(agent_id) for agent_id in candidate_agent_ids}
    words = _u32_words(packet.data, limit=2)
    if len(words) < 2:
        return None

    reset_opcode = int(words[0])
    target_agent_id = int(words[1])
    if reset_opcode != 48:
        return None
    if target_agent_id not in candidate_agent_ids:
        return None
    return GadgetStateEvent(tick=int(packet.tick), header=int(packet.header), agent_id=target_agent_id, state=1)


def decode_world_create_switch_packet(
    packet: RawPacket,
    candidate_agent_ids: Iterable[int],
    *,
    candidate_gadget_id_to_agent_id: Mapping[int, int],
) -> GadgetStateEvent | None:
    if packet.direction != "StoC":
        return None
    if packet.header not in WORLD_CREATE_AGENT_HEADERS:
        return None
    if packet.size < 12 or len(packet.data) < 12:
        return None

    candidate_agent_ids = {int(agent_id) for agent_id in candidate_agent_ids}
    candidate_gadget_id_to_agent_id = {
        int(gadget_id): int(agent_id)
        for gadget_id, agent_id in candidate_gadget_id_to_agent_id.items()
        if int(gadget_id) > 0 and int(agent_id) > 0
    }
    agent_id = _u32(packet.data, 4)
    gadget_id = _u32(packet.data, 8)
    if agent_id is None or gadget_id is None:
        return None

    mapped_agent_id = candidate_gadget_id_to_agent_id.get(int(gadget_id))
    if mapped_agent_id is None and int(agent_id) not in candidate_agent_ids:
        return None
    if mapped_agent_id is not None and int(agent_id) not in candidate_agent_ids:
        agent_id = mapped_agent_id

    return GadgetStateEvent(tick=int(packet.tick), header=int(packet.header), agent_id=int(agent_id), state=1)


def decode_world_create_agent_packet(packet: RawPacket) -> GadgetStateEvent | None:
    if packet.direction != "StoC":
        return None
    if packet.header not in WORLD_CREATE_AGENT_HEADERS:
        return None
    if packet.size < 20 or len(packet.data) < 20:
        return None

    words = _u32_words(packet.data)
    if len(words) < 4:
        return None
    if words[2] != 2 or words[3] != 1:
        return None

    return GadgetStateEvent(tick=int(packet.tick), header=int(packet.header), agent_id=int(words[0]), state=1)


def decode_gadget_state_packet(
    packet: RawPacket,
    candidate_agent_ids: Iterable[int],
    *,
    candidate_gadget_id_to_agent_id: Mapping[int, int] | None = None,
    header_candidates: frozenset[int] = GADGET_STATE_HEADER_CANDIDATES,
) -> GadgetStateEvent | None:
    if packet.direction != "StoC":
        return None
    if packet.header not in header_candidates:
        return None
    if packet.size < 12 or len(packet.data) < 12:
        return None

    candidate_agent_ids = {int(agent_id) for agent_id in candidate_agent_ids}
    candidate_gadget_id_to_agent_id = {
        int(gadget_id): int(agent_id)
        for gadget_id, agent_id in (candidate_gadget_id_to_agent_id or {}).items()
        if int(gadget_id) > 0 and int(agent_id) > 0
    }

    if packet.header in AGENT_PROPERTY_INT_STATE_HEADERS and packet.size >= 16 and len(packet.data) >= 16:
        agent_id = _u32(packet.data, 8)
        state = _u32(packet.data, 12)
        if agent_id in candidate_agent_ids and state is not None:
            return GadgetStateEvent(
                tick=int(packet.tick),
                header=int(packet.header),
                agent_id=int(agent_id),
                state=int(state),
        )
        return None

    if packet.header in AGENT_PROPERTY_FLOAT_STATE_HEADERS and packet.size >= 16 and len(packet.data) >= 16:
        agent_id = _u32(packet.data, 8)
        value = _f32(packet.data, 12)
        if agent_id in candidate_agent_ids and value is not None:
            return GadgetStateEvent(
                tick=int(packet.tick),
                header=int(packet.header),
                agent_id=int(agent_id),
                state=1 if abs(value) > 0.0001 else 0,
            )
        return None

    if packet.header in MAP_OBJECT_ANIMATION_HEADERS and packet.size >= 16 and len(packet.data) >= 16:
        object_id = _u32(packet.data, 4)
        animation_type = _u32(packet.data, 8)
        animation_stage = _u32(packet.data, 12)
        agent_id = candidate_gadget_id_to_agent_id.get(int(object_id or 0))
        if agent_id is not None and (animation_type or animation_stage):
            return GadgetStateEvent(
                tick=int(packet.tick),
                header=int(packet.header),
                agent_id=int(agent_id),
                state=1,
            )

    if packet.header in MAP_OBJECT_STATE_HEADERS and packet.size >= 16 and len(packet.data) >= 16:
        object_id = _u32(packet.data, 4)
        state = _u32(packet.data, 12)
        agent_id = candidate_gadget_id_to_agent_id.get(int(object_id or 0))
        if agent_id is not None and state is not None:
            return GadgetStateEvent(
                tick=int(packet.tick),
                header=int(packet.header),
                agent_id=int(agent_id),
                state=int(state),
            )

    agent_id = _u32(packet.data, 4)
    state = _u32(packet.data, 8)
    if agent_id is None or state is None:
        return None
    if agent_id not in candidate_agent_ids:
        return None
    return GadgetStateEvent(tick=int(packet.tick), header=int(packet.header), agent_id=int(agent_id), state=int(state))


class SequenceRecorder:
    def __init__(
        self,
        *,
        expected_switch_count: int = 4,
        simultaneous_window_ms: int = 250,
        repeat_window_ms: int = 250,
    ) -> None:
        self.expected_switch_count = max(1, int(expected_switch_count))
        self.simultaneous_window_ms = max(1, int(simultaneous_window_ms))
        self.repeat_window_ms = max(1, int(repeat_window_ms))
        self._sequence: list[int] = []
        self._pending_batch: list[GadgetStateEvent] = []
        self._last_active_tick_by_agent: dict[int, int] = {}

    @property
    def sequence(self) -> list[int]:
        projected = list(self._sequence)
        self._append_batch_to(projected, self._pending_batch)
        return projected[: self.expected_switch_count]

    @property
    def complete(self) -> bool:
        return len(self.sequence) >= self.expected_switch_count

    def clear(self) -> None:
        self._sequence.clear()
        self._pending_batch.clear()
        self._last_active_tick_by_agent.clear()

    def set_sequence(self, sequence: Iterable[int]) -> None:
        self.clear()
        for agent_id in sequence:
            agent_id = int(agent_id)
            if agent_id <= 0 or agent_id in self._sequence:
                continue
            self._sequence.append(agent_id)
            if len(self._sequence) >= self.expected_switch_count:
                return

    def record(self, event: GadgetStateEvent) -> None:
        if not event.active:
            return

        last_tick = self._last_active_tick_by_agent.get(event.agent_id)
        if last_tick is not None and event.tick - last_tick < self.repeat_window_ms:
            return
        self._last_active_tick_by_agent[event.agent_id] = event.tick

        if self._pending_batch and event.tick - self._pending_batch[0].tick > self.simultaneous_window_ms:
            self._finalize_pending_batch()
        self._pending_batch.append(event)

    def _finalize_pending_batch(self) -> None:
        self._append_batch_to(self._sequence, self._pending_batch)
        self._pending_batch.clear()

    def _append_batch_to(self, target: list[int], batch: list[GadgetStateEvent]) -> None:
        if not batch:
            return
        unique_agents = []
        for event in batch:
            if event.agent_id not in unique_agents:
                unique_agents.append(event.agent_id)

        all_switch_flash_threshold = min(self.expected_switch_count, 3)
        if len(unique_agents) >= all_switch_flash_threshold:
            return

        for agent_id in unique_agents:
            if agent_id in target:
                continue
            if len(target) >= self.expected_switch_count:
                return
            target.append(agent_id)


class WorldCreateBurstRecorder:
    def __init__(self, *, expected_switch_count: int = 4, burst_window_ms: int = 1500) -> None:
        self.expected_switch_count = max(1, int(expected_switch_count))
        self.burst_window_ms = max(1, int(burst_window_ms))
        self._first_tick: int | None = None
        self._pending_sequence: list[int] = []

    @property
    def pending_sequence(self) -> list[int]:
        return list(self._pending_sequence)

    def clear(self) -> None:
        self._first_tick = None
        self._pending_sequence.clear()

    def record(self, event: GadgetStateEvent) -> list[int] | None:
        if not event.active:
            return None
        if event.header not in WORLD_CREATE_AGENT_HEADERS:
            return None

        if self._first_tick is None or int(event.tick) - self._first_tick > self.burst_window_ms:
            self._first_tick = int(event.tick)
            self._pending_sequence.clear()

        if int(event.agent_id) not in self._pending_sequence:
            self._pending_sequence.append(int(event.agent_id))

        if len(self._pending_sequence) >= self.expected_switch_count:
            sequence = self._pending_sequence[: self.expected_switch_count]
            self.clear()
            return sequence
        return None


class ClientClickSequenceRecorder:
    def __init__(self, *, expected_switch_count: int = 4) -> None:
        self.expected_switch_count = max(1, int(expected_switch_count))
        self._sequence: list[int] = []

    @property
    def sequence(self) -> list[int]:
        return list(self._sequence)

    @property
    def complete(self) -> bool:
        return len(self._sequence) >= self.expected_switch_count

    def clear(self) -> None:
        self._sequence.clear()

    def record(self, event: GadgetStateEvent) -> list[int] | None:
        if not event.active:
            return None
        agent_id = int(event.agent_id)
        if agent_id <= 0 or agent_id in self._sequence or self.complete:
            return None
        self._sequence.append(agent_id)
        if self.complete:
            return self.sequence
        return None


class ClickPlan:
    def __init__(self, sequence: Iterable[int]) -> None:
        self.sequence = [int(agent_id) for agent_id in sequence if int(agent_id) > 0]
        self._index = 0

    @property
    def complete(self) -> bool:
        return self._index >= len(self.sequence)

    def next_agent_id(self) -> int | None:
        if self.complete:
            return None
        return self.sequence[self._index]

    def mark_clicked(self, agent_id: int) -> bool:
        if self.complete:
            return False
        if self.sequence[self._index] != int(agent_id):
            return False
        self._index += 1
        return True


def advance_click_plan_from_event(plan: ClickPlan, event: GadgetStateEvent) -> bool:
    if not event.active:
        return False
    return plan.mark_clicked(int(event.agent_id))


def plan_switch_interaction(
    agent_id: int,
    switches: Iterable[GadgetSnapshot],
    *,
    player_xy: tuple[float, float],
    interact_distance: float,
) -> SwitchInteractionDecision | None:
    target_id = int(agent_id)
    for switch in switches:
        if int(switch.agent_id) != target_id:
            continue
        distance = switch.distance_to((float(player_xy[0]), float(player_xy[1])))
        return SwitchInteractionDecision(
            agent_id=target_id,
            x=float(switch.x),
            y=float(switch.y),
            distance=distance,
            in_range=distance <= float(interact_distance),
        )
    return None


def runtime_delta_fields(before: GadgetRuntimeSnapshot, after: GadgetRuntimeSnapshot) -> list[str]:
    if before.agent_id != after.agent_id:
        return ["agent_id"]

    changed: list[str] = []
    if before.visual_effects != after.visual_effects:
        changed.append("visual_effects")
    if before.h00c4 != after.h00c4:
        changed.append("h00c4")
    if before.h00c8 != after.h00c8:
        changed.append("h00c8")
    if before.h00d4 != after.h00d4:
        changed.append("h00d4")
    return changed


def runtime_delta_to_event(
    before: GadgetRuntimeSnapshot,
    after: GadgetRuntimeSnapshot,
    *,
    tick: int,
) -> GadgetStateEvent | None:
    if before.agent_id != after.agent_id:
        return None
    if not runtime_delta_fields(before, after):
        return None
    return GadgetStateEvent(tick=int(tick), header=0, agent_id=int(after.agent_id), state=1)


def select_switch_candidates(
    gadgets: Iterable[GadgetSnapshot],
    *,
    center: tuple[float, float],
    max_distance: float = 500.0,
    min_distance: float = 50.0,
    limit: int = 4,
) -> list[GadgetSnapshot]:
    nearby: list[tuple[float, GadgetSnapshot]] = []
    for gadget in gadgets:
        if gadget.agent_id <= 0:
            continue
        distance = gadget.distance_to(center)
        if min_distance <= distance <= max_distance:
            nearby.append((distance, gadget))
    nearby.sort(key=lambda item: (item[0], item[1].agent_id))

    requested = max(0, int(limit))
    if requested <= 0:
        return []

    named_switches = [
        (distance, gadget)
        for distance, gadget in nearby
        if "teleporter" in gadget.name.lower() and "switch" in gadget.name.lower()
    ]
    if len(named_switches) >= requested:
        return [gadget for _, gadget in named_switches[:requested]]

    return [gadget for _, gadget in nearby[:requested]]


def select_gadgets_by_agent_sequence(
    gadgets: Iterable[GadgetSnapshot],
    sequence: Iterable[int],
) -> list[GadgetSnapshot]:
    by_agent_id = {
        int(gadget.agent_id): gadget
        for gadget in gadgets
        if int(gadget.agent_id) > 0
    }
    selected: list[GadgetSnapshot] = []
    seen: set[int] = set()
    for raw_agent_id in sequence:
        agent_id = int(raw_agent_id)
        if agent_id <= 0 or agent_id in seen:
            return []
        gadget = by_agent_id.get(agent_id)
        if gadget is None:
            return []
        selected.append(gadget)
        seen.add(agent_id)
    return selected


def platform_mapping_signature(marker_gadget_ids: Iterable[int], switch_gadget_ids: Iterable[int]) -> str:
    markers = sorted({int(gadget_id) for gadget_id in marker_gadget_ids if int(gadget_id) > 0})
    switches = sorted({int(gadget_id) for gadget_id in switch_gadget_ids if int(gadget_id) > 0})
    if not markers or not switches:
        return ""
    marker_text = ",".join(str(gadget_id) for gadget_id in markers)
    switch_text = ",".join(str(gadget_id) for gadget_id in switches)
    return f"markers={marker_text}|switches={switch_text}"


def learn_platform_mapping(
    platform_markers: Iterable[GadgetSnapshot],
    switches: Iterable[GadgetSnapshot],
    burst_sequence: Iterable[int],
    switch_sequence: Iterable[int],
) -> PlatformMapping | None:
    marker_sequence = select_gadgets_by_agent_sequence(platform_markers, burst_sequence)
    switch_sequence_snapshots = select_gadgets_by_agent_sequence(switches, switch_sequence)
    if not marker_sequence or len(marker_sequence) != len(switch_sequence_snapshots):
        return None

    marker_gadget_ids = [int(marker.gadget_id) for marker in marker_sequence]
    switch_gadget_ids = [int(switch.gadget_id) for switch in switch_sequence_snapshots]
    if any(gadget_id <= 0 for gadget_id in marker_gadget_ids + switch_gadget_ids):
        return None
    if len(set(marker_gadget_ids)) != len(marker_gadget_ids):
        return None
    if len(set(switch_gadget_ids)) != len(switch_gadget_ids):
        return None

    signature = platform_mapping_signature(marker_gadget_ids, switch_gadget_ids)
    if not signature:
        return None
    pairs = tuple((marker_gadget_id, switch_gadget_id) for marker_gadget_id, switch_gadget_id in zip(marker_gadget_ids, switch_gadget_ids))
    return PlatformMapping(signature=signature, marker_to_switch_gadget_ids=pairs)


def _switch_agents_for_gadget_sequence(
    switch_gadget_ids: Iterable[int],
    switches: Iterable[GadgetSnapshot],
) -> list[int]:
    switch_agent_by_gadget_id = {
        int(switch.gadget_id): int(switch.agent_id)
        for switch in switches
        if int(switch.gadget_id) > 0 and int(switch.agent_id) > 0
    }

    sequence: list[int] = []
    for switch_gadget_id in switch_gadget_ids:
        switch_agent_id = switch_agent_by_gadget_id.get(int(switch_gadget_id))
        if switch_agent_id is None or switch_agent_id in sequence:
            return []
        sequence.append(switch_agent_id)
    return sequence


def _apply_platform_mapping_direct(
    mapping: PlatformMapping,
    platform_markers: Iterable[GadgetSnapshot],
    switches: Iterable[GadgetSnapshot],
    burst_sequence: Iterable[int],
) -> list[int]:
    marker_sequence = select_gadgets_by_agent_sequence(platform_markers, burst_sequence)
    if not marker_sequence:
        return []

    marker_gadget_ids = [int(marker.gadget_id) for marker in marker_sequence]
    switch_gadget_ids = [int(switch.gadget_id) for switch in switches if int(switch.gadget_id) > 0]
    current_signature = platform_mapping_signature(marker_gadget_ids, switch_gadget_ids)
    if current_signature != mapping.signature:
        return []

    marker_to_switch_gadget_id = {
        int(marker_gadget_id): int(switch_gadget_id)
        for marker_gadget_id, switch_gadget_id in mapping.marker_to_switch_gadget_ids
    }
    switch_gadget_sequence: list[int] = []
    for marker_gadget_id in marker_gadget_ids:
        switch_gadget_id = marker_to_switch_gadget_id.get(marker_gadget_id)
        if switch_gadget_id is None:
            return []
        switch_gadget_sequence.append(switch_gadget_id)
    return _switch_agents_for_gadget_sequence(switch_gadget_sequence, switches)


def apply_platform_mapping(
    mapping: PlatformMapping,
    platform_markers: Iterable[GadgetSnapshot],
    switches: Iterable[GadgetSnapshot],
    burst_sequence: Iterable[int],
) -> list[int]:
    return _apply_platform_mapping_direct(mapping, platform_markers, switches, burst_sequence)


def map_platform_burst_with_known_mappings(
    mappings: Iterable[PlatformMapping],
    platform_markers: Iterable[GadgetSnapshot],
    switches: Iterable[GadgetSnapshot],
    burst_sequence: Iterable[int],
    *,
    expected_switch_count: int = 4,
) -> list[int]:
    marker_list = tuple(platform_markers)
    switch_list = tuple(switches)
    burst = [int(agent_id) for agent_id in burst_sequence]
    if len(burst) < expected_switch_count:
        return []

    mapping_list = tuple(mappings)

    for mapping in mapping_list:
        sequence = _apply_platform_mapping_direct(
            mapping,
            marker_list,
            switch_list,
            burst[:expected_switch_count],
        )
        if len(sequence) >= expected_switch_count:
            return sequence[:expected_switch_count]
    return []


def map_platform_burst_to_switch_sequence(
    platform_markers: Iterable[GadgetSnapshot],
    switches: Iterable[GadgetSnapshot],
    burst_sequence: Iterable[int],
) -> list[int]:
    marker_list = [marker for marker in platform_markers if int(marker.agent_id) > 0]
    switch_list = [switch for switch in switches if int(switch.agent_id) > 0]
    if not marker_list or len(marker_list) < len(switch_list):
        return []
    if len(switch_list) <= 0:
        return []

    marker_by_agent_id = {int(marker.agent_id): marker for marker in marker_list}
    markers_north_to_south = sorted(marker_list, key=lambda marker: (-float(marker.y), float(marker.x), int(marker.agent_id)))
    switches_north_to_south = sorted(switch_list, key=lambda switch: (-float(switch.y), float(switch.x), int(switch.agent_id)))

    marker_rank_by_agent_id = {
        int(marker.agent_id): rank
        for rank, marker in enumerate(markers_north_to_south)
    }
    switch_rank_by_marker_rank = list(range(len(switches_north_to_south)))
    if len(switch_rank_by_marker_rank) == 4:
        switch_rank_by_marker_rank = [0, 2, 1, 3]

    mapped_sequence: list[int] = []
    seen_markers: set[int] = set()
    for raw_agent_id in burst_sequence:
        marker_agent_id = int(raw_agent_id)
        if marker_agent_id in seen_markers:
            return []
        if marker_agent_id not in marker_by_agent_id:
            return []
        rank = marker_rank_by_agent_id.get(marker_agent_id)
        if rank is None or rank >= len(switch_rank_by_marker_rank):
            return []
        switch_rank = switch_rank_by_marker_rank[rank]
        if switch_rank >= len(switches_north_to_south):
            return []
        mapped_agent_id = int(switches_north_to_south[switch_rank].agent_id)
        if mapped_agent_id in mapped_sequence:
            return []
        mapped_sequence.append(mapped_agent_id)
        seen_markers.add(marker_agent_id)

    return mapped_sequence
