import importlib.util
import json
import pathlib
import struct
import sys
import types
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "Py4GWCoreLib" / "CrystalDesertTeleporter.py"
MAPPING_FILE_PATH = pathlib.Path(__file__).resolve().parents[1] / "Widgets" / "Guild Wars" / "CrystalDesertTeleporterMappings.json"


def load_module():
    spec = importlib.util.spec_from_file_location("Py4GWCoreLib.CrystalDesertTeleporter", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["Py4GWCoreLib.CrystalDesertTeleporter"] = module
    spec.loader.exec_module(module)
    return module


class CrystalDesertTeleporterTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def packet(self, tick, header, agent_id, state):
        return self.module.RawPacket(
            direction="StoC",
            tick=tick,
            header=header,
            size=12,
            data=struct.pack("<III", header, agent_id, state),
        )

    def map_object_packet(self, tick, object_id, state):
        return self.module.RawPacket(
            direction="StoC",
            tick=tick,
            header=0x0111,
            size=16,
            data=struct.pack("<IIII", 0x0111, object_id, 0, state),
        )

    def map_object_animation_packet(self, tick, object_id, animation_type, animation_stage):
        return self.module.RawPacket(
            direction="StoC",
            tick=tick,
            header=0x010E,
            size=16,
            data=struct.pack("<IIII", 0x010E, object_id, animation_type, animation_stage),
        )

    def test_decodes_gadget_state_packets_for_nearby_agents(self):
        event = self.module.decode_gadget_state_packet(
            self.packet(1000, 0x0111, 42, 1),
            candidate_agent_ids={41, 42, 43, 44},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.agent_id, 42)
        self.assertEqual(event.state, 1)
        self.assertTrue(event.active)

    def test_decodes_direct_gadget_state_packets_from_server(self):
        event = self.module.decode_gadget_state_packet(
            self.packet(1000, 0x0115, 13, 1),
            candidate_agent_ids={13, 14, 15, 16},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.agent_id, 13)
        self.assertEqual(event.state, 1)
        self.assertTrue(event.active)

    def test_ignores_packets_for_agents_outside_the_nearby_switch_cluster(self):
        event = self.module.decode_gadget_state_packet(
            self.packet(1000, 0x0111, 99, 1),
            candidate_agent_ids={41, 42, 43, 44},
        )

        self.assertIsNone(event)

    def test_decodes_map_object_state_packets_by_gadget_id(self):
        event = self.module.decode_gadget_state_packet(
            self.map_object_packet(1000, object_id=705, state=1),
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_id_to_agent_id={705: 13, 706: 14, 707: 15, 708: 16},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.agent_id, 13)
        self.assertEqual(event.state, 1)
        self.assertTrue(event.active)

    def test_decodes_agent_property_int_state_packets_for_nearby_agents(self):
        packet = self.module.RawPacket(
            direction="StoC",
            tick=1000,
            header=0x009F,
            size=16,
            data=struct.pack("<IIII", 0x009F, 0x22, 14, 1),
        )

        event = self.module.decode_gadget_state_packet(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.agent_id, 14)
        self.assertEqual(event.state, 1)
        self.assertTrue(event.active)

    def test_decodes_map_object_animation_packets_by_gadget_id(self):
        event = self.module.decode_gadget_state_packet(
            self.map_object_animation_packet(1000, object_id=706, animation_type=9, animation_stage=2),
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_id_to_agent_id={705: 13, 706: 14, 707: 15, 708: 16},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.agent_id, 14)
        self.assertEqual(event.state, 1)
        self.assertTrue(event.active)

    def test_decodes_agent_property_float_packets_for_nearby_agents(self):
        packet = self.module.RawPacket(
            direction="StoC",
            tick=1000,
            header=0x00A2,
            size=16,
            data=struct.pack("<IIIf", 0x00A2, 0x22, 15, 0.75),
        )

        event = self.module.decode_gadget_state_packet(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.agent_id, 15)
        self.assertEqual(event.state, 1)
        self.assertTrue(event.active)

    def test_probe_summary_ignores_short_candidate_packets_without_payload(self):
        packet = self.module.RawPacket(
            direction="StoC",
            tick=1000,
            header=0x00A2,
            size=4,
            data=struct.pack("<I", 0x00A2),
        )

        summary = self.module.packet_probe_summary(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_ids={705, 706, 707, 708},
        )

        self.assertIsNone(summary)

    def test_probe_summary_reports_candidate_packets_with_payload(self):
        packet = self.module.RawPacket(
            direction="StoC",
            tick=1000,
            header=0x0111,
            size=16,
            data=struct.pack("<IIII", 0x0111, 705, 0, 1),
        )

        summary = self.module.packet_probe_summary(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_ids={705, 706, 707, 708},
        )

        self.assertEqual(summary, "0x0111 size=16 words=705 0 1")

    def test_runtime_signature_formats_unknown_gadget_fields_for_live_capture(self):
        snapshot = self.module.GadgetRuntimeSnapshot(
            agent_id=14,
            visual_effects=3,
            h00c4=1126198885,
            h00c8=1970499183,
            h00d4=(1, 2, 3, 4),
        )

        summary = self.module.runtime_signature(snapshot)

        self.assertIn("ve=0x3", summary)
        self.assertIn("c4=0x43206E65/en C", summary)
        self.assertIn("c8=0x75736E6F/onsu", summary)
        self.assertIn("d4=0x00000001,0x00000002,0x00000003,0x00000004", summary)

    def test_probe_summary_decodes_world_create_agent_packets_for_switch_gadgets(self):
        packet = self.module.RawPacket(
            direction="StoC",
            tick=1000,
            header=0x0020,
            size=24,
            data=struct.pack("<IIIIII", 0x0020, 14, 706, 2, 1, 3307065344),
        )

        summary = self.module.packet_probe_summary(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_ids={705, 706, 707, 708},
        )
        event = self.module.decode_gadget_state_packet(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_id_to_agent_id={705: 13, 706: 14, 707: 15, 708: 16},
        )

        self.assertEqual(
            summary,
            "0x0020 create agent=14 gadget=706 kind=2 flag=1 x=-2525 raw=14 706 2 1 3307065344",
        )
        self.assertIsNone(event)

    def test_probe_summary_reports_unmatched_world_create_packets_for_diagnostics(self):
        packet = self.module.RawPacket(
            direction="StoC",
            tick=1000,
            header=0x0020,
            size=24,
            data=struct.pack("<IIIIII", 0x0020, 30, 720, 2, 1, 3307065344),
        )

        summary = self.module.packet_probe_summary(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_ids={705, 706, 707, 708},
        )

        self.assertEqual(
            summary,
            "0x0020 create unmatched agent=30 gadget=720 kind=2 flag=1 x=-2525 raw=30 720 2 1 3307065344",
        )

    def test_decodes_world_create_switch_packets_by_agent_and_gadget_id(self):
        packet = self.module.RawPacket(
            direction="StoC",
            tick=1000,
            header=0x0020,
            size=24,
            data=struct.pack("<IIIIII", 0x0020, 16, 708, 2, 1, 3305684992),
        )

        event = self.module.decode_world_create_switch_packet(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_id_to_agent_id={705: 13, 706: 14, 707: 15, 708: 16},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.agent_id, 16)
        self.assertEqual(event.header, 0x0020)
        self.assertTrue(event.active)

    def test_decodes_unmatched_world_create_packets_for_platform_bursts(self):
        packet = self.module.RawPacket(
            direction="StoC",
            tick=1000,
            header=0x0020,
            size=24,
            data=struct.pack("<IIIIII", 0x0020, 21, 716, 2, 1, 1160802304),
        )

        event = self.module.decode_world_create_agent_packet(packet)

        self.assertIsNotNone(event)
        self.assertEqual(event.agent_id, 21)
        self.assertEqual(event.header, 0x0020)
        self.assertTrue(event.active)

    def test_ignores_world_create_packets_that_do_not_look_like_platform_bursts(self):
        packet = self.module.RawPacket(
            direction="StoC",
            tick=1000,
            header=0x0020,
            size=24,
            data=struct.pack("<IIIIII", 0x0020, 21, 716, 1, 0, 1160802304),
        )

        event = self.module.decode_world_create_agent_packet(packet)

        self.assertIsNone(event)

    def test_world_create_burst_recorder_captures_platform_sequence(self):
        recorder = self.module.WorldCreateBurstRecorder(expected_switch_count=4, burst_window_ms=1500)
        events = [
            self.module.GadgetStateEvent(tick=1000, header=0x0020, agent_id=16, state=1),
            self.module.GadgetStateEvent(tick=1030, header=0x0020, agent_id=15, state=1),
            self.module.GadgetStateEvent(tick=1060, header=0x0020, agent_id=14, state=1),
            self.module.GadgetStateEvent(tick=1090, header=0x0020, agent_id=13, state=1),
        ]

        sequence = None
        for event in events:
            sequence = recorder.record(event)

        self.assertEqual(sequence, [16, 15, 14, 13])

    def test_world_create_burst_recorder_resets_after_timeout(self):
        recorder = self.module.WorldCreateBurstRecorder(expected_switch_count=4, burst_window_ms=1500)

        self.assertIsNone(recorder.record(self.module.GadgetStateEvent(tick=1000, header=0x0020, agent_id=16, state=1)))
        self.assertIsNone(recorder.record(self.module.GadgetStateEvent(tick=3000, header=0x0020, agent_id=15, state=1)))

        self.assertEqual(recorder.pending_sequence, [15])

    def test_sequence_recorder_can_be_seeded_from_platform_burst(self):
        recorder = self.module.SequenceRecorder(expected_switch_count=4)

        recorder.set_sequence([16, 15, 14, 13])

        self.assertEqual(recorder.sequence, [16, 15, 14, 13])
        self.assertTrue(recorder.complete)

    def test_probe_summary_reports_ctos_switch_click_packets(self):
        packet = self.module.RawPacket(
            direction="CToS",
            tick=1000,
            header=0x0026,
            size=12,
            data=struct.pack("<III", 0x0026, 13, 0),
        )

        summary = self.module.packet_probe_summary(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_ids={705, 706, 707, 708},
        )

        self.assertEqual(summary, "CToS 0x0026 size=12 words=13 0")

    def test_sequence_decoder_ignores_ctos_switch_click_packets(self):
        packet = self.module.RawPacket(
            direction="CToS",
            tick=1000,
            header=0x0026,
            size=12,
            data=struct.pack("<III", 0x0026, 13, 0),
        )

        event = self.module.decode_gadget_state_packet(packet, candidate_agent_ids={13, 14, 15, 16})

        self.assertIsNone(event)

    def test_normalizes_packet_log_entry_direction(self):
        entry = types.SimpleNamespace(direction="CToS")

        direction = self.module.packet_direction_from_entry(entry)

        self.assertEqual(direction, "CToS")

    def test_interact_gadget_packet_is_targeting_noise_not_a_probe_or_state_event(self):
        packet = self.module.RawPacket(
            direction="CToS",
            tick=1000,
            header=0x0051,
            size=12,
            data=struct.pack("<III", 0x0051, 15, 0),
        )

        summary = self.module.packet_probe_summary(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_ids={705, 706, 707, 708},
        )
        event = self.module.decode_gadget_state_packet(packet, candidate_agent_ids={13, 14, 15, 16})

        self.assertIsNone(summary)
        self.assertIsNone(event)

    def test_travel_init_packet_with_switch_id_is_targeting_noise_not_a_probe(self):
        packet = self.module.RawPacket(
            direction="CToS",
            tick=1000,
            header=0x00C1,
            size=12,
            data=struct.pack("<III", 0x00C1, 16, 0),
        )

        summary = self.module.packet_probe_summary(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_ids={705, 706, 707, 708},
        )
        event = self.module.decode_gadget_state_packet(packet, candidate_agent_ids={13, 14, 15, 16})

        self.assertIsNone(summary)
        self.assertIsNone(event)

    def test_client_action_summary_reports_nonzero_ctos_candidate_pairs(self):
        packet = self.module.RawPacket(
            direction="CToS",
            tick=1000,
            header=0x00C1,
            size=12,
            data=struct.pack("<III", 0x00C1, 15, 16),
        )

        summary = self.module.client_action_summary(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_ids={705, 706, 707, 708},
        )

        self.assertEqual(summary, "CToS action 0x00C1 size=12 words=15 16")

    def test_decode_client_switch_click_ignores_agent_selection_packets(self):
        packet = self.module.RawPacket(
            direction="CToS",
            tick=1000,
            header=0x00C1,
            size=12,
            data=struct.pack("<III", 0x00C1, 16, 14),
        )

        event = self.module.decode_client_switch_click_packet(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
        )

        self.assertIsNone(event)

    def test_decode_client_switch_click_ignores_zero_second_word_targeting_noise(self):
        packet = self.module.RawPacket(
            direction="CToS",
            tick=1000,
            header=0x00C1,
            size=12,
            data=struct.pack("<III", 0x00C1, 16, 0),
        )

        event = self.module.decode_client_switch_click_packet(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
        )

        self.assertIsNone(event)

    def test_decode_client_interact_packet_from_ctos_order_interact(self):
        packet = self.module.RawPacket(
            direction="CToS",
            tick=1000,
            header=0x0039,
            size=12,
            data=struct.pack("<III", 0x0039, 18, 0),
        )

        event = self.module.decode_client_interact_packet(
            packet,
            candidate_agent_ids={18, 19, 20, 21},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.agent_id, 18)
        self.assertEqual(event.header, 0x0039)
        self.assertTrue(event.active)

    def test_decode_client_interact_packet_ignores_non_candidate_agents(self):
        packet = self.module.RawPacket(
            direction="CToS",
            tick=1000,
            header=0x0039,
            size=12,
            data=struct.pack("<III", 0x0039, 30, 0),
        )

        event = self.module.decode_client_interact_packet(
            packet,
            candidate_agent_ids={18, 19, 20, 21},
        )

        self.assertIsNone(event)

    def test_decode_client_sequence_reset_packet_from_ctos_words_48_target(self):
        packet = self.module.RawPacket(
            direction="CToS",
            tick=1000,
            header=0x00C1,
            size=12,
            data=struct.pack("<III", 0x00C1, 48, 18),
        )

        event = self.module.decode_client_sequence_reset_packet(
            packet,
            candidate_agent_ids={18, 19, 20, 21},
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.agent_id, 18)
        self.assertEqual(event.header, 0x00C1)
        self.assertTrue(event.active)

    def test_decode_client_sequence_reset_packet_ignores_non_reset_pairs(self):
        packet = self.module.RawPacket(
            direction="CToS",
            tick=1000,
            header=0x00C1,
            size=12,
            data=struct.pack("<III", 0x00C1, 16, 18),
        )

        event = self.module.decode_client_sequence_reset_packet(
            packet,
            candidate_agent_ids={18, 19, 20, 21},
        )

        self.assertIsNone(event)

    def test_client_click_sequence_recorder_preserves_manual_click_order(self):
        recorder = self.module.ClientClickSequenceRecorder(expected_switch_count=4)
        events = [
            self.module.GadgetStateEvent(tick=1000, header=0x00C1, agent_id=14, state=1),
            self.module.GadgetStateEvent(tick=1010, header=0x00C1, agent_id=16, state=1),
            self.module.GadgetStateEvent(tick=1020, header=0x00C1, agent_id=15, state=1),
            self.module.GadgetStateEvent(tick=1030, header=0x00C1, agent_id=13, state=1),
        ]

        sequence = None
        for event in events:
            sequence = recorder.record(event)

        self.assertEqual(sequence, [14, 16, 15, 13])
        self.assertEqual(recorder.sequence, [14, 16, 15, 13])

    def test_client_action_summary_ignores_zero_targeting_noise(self):
        packet = self.module.RawPacket(
            direction="CToS",
            tick=1000,
            header=0x00C1,
            size=12,
            data=struct.pack("<III", 0x00C1, 16, 0),
        )

        summary = self.module.client_action_summary(
            packet,
            candidate_agent_ids={13, 14, 15, 16},
            candidate_gadget_ids={705, 706, 707, 708},
        )

        self.assertIsNone(summary)

    def test_recorder_ignores_initial_all_switch_flash_and_keeps_the_random_sequence(self):
        recorder = self.module.SequenceRecorder(expected_switch_count=4)
        candidate_ids = {101, 102, 103, 104}
        packets = [
            self.packet(1000, 0x0111, 101, 1),
            self.packet(1010, 0x0111, 102, 1),
            self.packet(1020, 0x0111, 103, 1),
            self.packet(1030, 0x0111, 104, 1),
            self.packet(1700, 0x0111, 103, 1),
            self.packet(2300, 0x0111, 101, 1),
            self.packet(2900, 0x0111, 104, 1),
            self.packet(3500, 0x0111, 102, 1),
        ]

        for packet in packets:
            event = self.module.decode_gadget_state_packet(packet, candidate_ids)
            if event is not None:
                recorder.record(event)

        self.assertEqual(recorder.sequence, [103, 101, 104, 102])
        self.assertTrue(recorder.complete)

    def test_recorder_builds_clickable_sequence_from_map_object_gadget_ids(self):
        recorder = self.module.SequenceRecorder(expected_switch_count=4)
        candidate_agent_ids = {13, 14, 15, 16}
        gadget_id_to_agent_id = {705: 13, 706: 14, 707: 15, 708: 16}
        packets = [
            self.map_object_packet(1000, 705, 1),
            self.map_object_packet(1010, 706, 1),
            self.map_object_packet(1020, 707, 1),
            self.map_object_packet(1030, 708, 1),
            self.map_object_packet(1700, 707, 1),
            self.map_object_packet(2300, 705, 1),
            self.map_object_packet(2900, 708, 1),
            self.map_object_packet(3500, 706, 1),
        ]

        for packet in packets:
            event = self.module.decode_gadget_state_packet(
                packet,
                candidate_agent_ids,
                candidate_gadget_id_to_agent_id=gadget_id_to_agent_id,
            )
            if event is not None:
                recorder.record(event)

        self.assertEqual(recorder.sequence, [15, 13, 16, 14])
        self.assertTrue(recorder.complete)

    def test_click_plan_advances_through_recorded_sequence(self):
        plan = self.module.ClickPlan([103, 101, 104, 102])

        self.assertEqual(plan.next_agent_id(), 103)
        plan.mark_clicked(103)
        self.assertEqual(plan.next_agent_id(), 101)
        plan.mark_clicked(101)
        plan.mark_clicked(104)
        plan.mark_clicked(102)

        self.assertIsNone(plan.next_agent_id())
        self.assertTrue(plan.complete)

    def test_manual_click_event_advances_click_plan_when_it_matches_next_switch(self):
        plan = self.module.ClickPlan([14, 16, 15, 13])
        event = self.module.GadgetStateEvent(tick=1000, header=0x00C1, agent_id=14, state=1)

        advanced = self.module.advance_click_plan_from_event(plan, event)

        self.assertTrue(advanced)
        self.assertEqual(plan.next_agent_id(), 16)

    def test_manual_click_event_does_not_advance_click_plan_out_of_order(self):
        plan = self.module.ClickPlan([14, 16, 15, 13])
        event = self.module.GadgetStateEvent(tick=1000, header=0x00C1, agent_id=13, state=1)

        advanced = self.module.advance_click_plan_from_event(plan, event)

        self.assertFalse(advanced)
        self.assertEqual(plan.next_agent_id(), 14)

    def test_plans_movement_before_switch_interaction_when_out_of_range(self):
        switch = self.module.GadgetSnapshot(agent_id=13, x=250.0, y=0.0)

        decision = self.module.plan_switch_interaction(
            13,
            [switch],
            player_xy=(0.0, 0.0),
            interact_distance=120.0,
        )

        self.assertIsNotNone(decision)
        self.assertEqual(decision.agent_id, 13)
        self.assertFalse(decision.in_range)
        self.assertEqual(decision.x, 250.0)
        self.assertEqual(decision.y, 0.0)

    def test_plans_direct_switch_interaction_when_in_range(self):
        switch = self.module.GadgetSnapshot(agent_id=13, x=100.0, y=0.0)

        decision = self.module.plan_switch_interaction(
            13,
            [switch],
            player_xy=(0.0, 0.0),
            interact_distance=120.0,
        )

        self.assertIsNotNone(decision)
        self.assertTrue(decision.in_range)

    def test_runtime_delta_creates_state_event_when_gadget_fields_change(self):
        before = self.module.GadgetRuntimeSnapshot(
            agent_id=13,
            visual_effects=0,
            h00c4=1,
            h00c8=2,
            h00d4=(3, 4, 5, 6),
        )
        after = self.module.GadgetRuntimeSnapshot(
            agent_id=13,
            visual_effects=0x20,
            h00c4=1,
            h00c8=2,
            h00d4=(3, 4, 5, 6),
        )

        event = self.module.runtime_delta_to_event(before, after, tick=1234)

        self.assertIsNotNone(event)
        self.assertEqual(event.agent_id, 13)
        self.assertEqual(event.header, 0)
        self.assertTrue(event.active)

    def test_runtime_delta_ignores_unchanged_gadget_fields(self):
        before = self.module.GadgetRuntimeSnapshot(
            agent_id=13,
            visual_effects=0,
            h00c4=1,
            h00c8=2,
            h00d4=(3, 4, 5, 6),
        )

        event = self.module.runtime_delta_to_event(before, before, tick=1234)

        self.assertIsNone(event)

    def test_capture_status_makes_start_state_explicit(self):
        status = self.module.CaptureStatus()

        self.assertIn("Capture: off", status.summary(capturing=False, now=10.0))
        self.assertIn("attempts=0", status.summary(capturing=False, now=10.0))

        status.mark_starting()
        self.assertIn("last=starting", status.summary(capturing=False, now=10.0))

        status.mark_started(10.0)
        status.add_packets(stoc=4, ctos=3, matches=2)
        summary = status.summary(capturing=True, now=12.5)

        self.assertIn("Capture: on", summary)
        self.assertIn("age=2.5s", summary)
        self.assertIn("StoC=4", summary)
        self.assertIn("CToS=3", summary)
        self.assertIn("matches=2", summary)

        status.mark_stopped("user")
        self.assertIn("Capture: off", status.summary(capturing=False, now=13.0))
        self.assertIn("last=stopped: user", status.summary(capturing=False, now=13.0))

    def test_capture_status_can_reset_recording_window_without_stopping_capture(self):
        status = self.module.CaptureStatus()
        status.mark_starting()
        status.mark_started(10.0)
        status.add_packets(stoc=7, ctos=3, matches=2)

        status.reset_recording_window(15.0)
        summary = status.summary(capturing=True, now=15.0)

        self.assertIn("Capture: on", summary)
        self.assertIn("attempts=1", summary)
        self.assertIn("last=started", summary)
        self.assertIn("age=0.0s", summary)
        self.assertIn("StoC=0", summary)
        self.assertIn("CToS=0", summary)
        self.assertIn("matches=0", summary)

    def test_selects_nearby_switch_candidates_around_platform(self):
        gadgets = [
            self.module.GadgetSnapshot(agent_id=1, x=0.0, y=0.0, name="platform"),
            self.module.GadgetSnapshot(agent_id=2, x=120.0, y=0.0, name="switch north"),
            self.module.GadgetSnapshot(agent_id=3, x=0.0, y=120.0, name="switch west"),
            self.module.GadgetSnapshot(agent_id=4, x=-120.0, y=0.0, name="switch south"),
            self.module.GadgetSnapshot(agent_id=5, x=0.0, y=-120.0, name="switch east"),
            self.module.GadgetSnapshot(agent_id=99, x=2000.0, y=2000.0, name="chest"),
        ]

        candidates = self.module.select_switch_candidates(gadgets, center=(0.0, 0.0), max_distance=300.0, limit=4)

        self.assertEqual([candidate.agent_id for candidate in candidates], [2, 3, 4, 5])

    def test_selects_named_teleporter_switches_before_nearer_non_switch_gadgets(self):
        gadgets = [
            self.module.GadgetSnapshot(agent_id=1, x=90.0, y=0.0, name="Buried Artifact"),
            self.module.GadgetSnapshot(agent_id=2, x=0.0, y=95.0, name="Ancient Console"),
            self.module.GadgetSnapshot(agent_id=18, x=300.0, y=0.0, name="Teleporter Switch"),
            self.module.GadgetSnapshot(agent_id=19, x=0.0, y=300.0, name="Teleporter Switch"),
            self.module.GadgetSnapshot(agent_id=20, x=-300.0, y=0.0, name="Teleporter Switch"),
            self.module.GadgetSnapshot(agent_id=21, x=0.0, y=-300.0, name="Teleporter Switch"),
        ]

        candidates = self.module.select_switch_candidates(gadgets, center=(0.0, 0.0), max_distance=500.0, limit=4)

        self.assertEqual([candidate.agent_id for candidate in candidates], [18, 19, 20, 21])

    def test_select_switch_candidates_falls_back_to_nearest_when_names_are_unavailable(self):
        gadgets = [
            self.module.GadgetSnapshot(agent_id=10, x=90.0, y=0.0, name=""),
            self.module.GadgetSnapshot(agent_id=11, x=0.0, y=95.0, name=""),
            self.module.GadgetSnapshot(agent_id=12, x=120.0, y=0.0, name=""),
            self.module.GadgetSnapshot(agent_id=13, x=0.0, y=125.0, name=""),
            self.module.GadgetSnapshot(agent_id=14, x=500.0, y=0.0, name=""),
        ]

        candidates = self.module.select_switch_candidates(gadgets, center=(0.0, 0.0), max_distance=600.0, limit=4)

        self.assertEqual([candidate.agent_id for candidate in candidates], [10, 11, 12, 13])

    def test_selects_live_gadgets_in_platform_burst_order(self):
        gadgets = [
            self.module.GadgetSnapshot(agent_id=20, x=3040.0, y=-9044.0, gadget_id=715),
            self.module.GadgetSnapshot(agent_id=18, x=3034.0, y=-9498.0, gadget_id=713),
            self.module.GadgetSnapshot(agent_id=21, x=2823.0, y=-8883.0, gadget_id=716),
            self.module.GadgetSnapshot(agent_id=19, x=2951.0, y=-9737.0, gadget_id=714),
        ]

        selected = self.module.select_gadgets_by_agent_sequence(gadgets, [21, 19, 18, 20])

        self.assertEqual([candidate.agent_id for candidate in selected], [21, 19, 18, 20])
        self.assertEqual([candidate.gadget_id for candidate in selected], [716, 714, 713, 715])

    def test_select_gadgets_by_agent_sequence_returns_empty_when_live_agent_is_missing(self):
        gadgets = [
            self.module.GadgetSnapshot(agent_id=21, x=2823.0, y=-8883.0, gadget_id=716),
            self.module.GadgetSnapshot(agent_id=19, x=2951.0, y=-9737.0, gadget_id=714),
        ]

        selected = self.module.select_gadgets_by_agent_sequence(gadgets, [21, 19, 18, 20])

        self.assertEqual(selected, [])

    def test_maps_platform_burst_agents_to_switches_with_crossed_middle_ranks(self):
        platform_markers = [
            self.module.GadgetSnapshot(agent_id=20, x=3040.0, y=-9044.0, gadget_id=715),
            self.module.GadgetSnapshot(agent_id=18, x=3034.0, y=-9498.0, gadget_id=713),
            self.module.GadgetSnapshot(agent_id=21, x=2823.0, y=-8883.0, gadget_id=716),
            self.module.GadgetSnapshot(agent_id=19, x=2951.0, y=-9737.0, gadget_id=714),
        ]
        switches = [
            self.module.GadgetSnapshot(agent_id=13, x=-2528.0, y=-10037.0, gadget_id=705),
            self.module.GadgetSnapshot(agent_id=14, x=-2525.0, y=-9760.0, gadget_id=706),
            self.module.GadgetSnapshot(agent_id=15, x=-2384.0, y=-10418.0, gadget_id=707),
            self.module.GadgetSnapshot(agent_id=16, x=-2188.0, y=-10514.0, gadget_id=708),
        ]

        sequence = self.module.map_platform_burst_to_switch_sequence(
            platform_markers,
            switches,
            [21, 19, 18, 20],
        )

        self.assertEqual(sequence, [14, 16, 13, 15])

    def test_platform_burst_mapping_returns_empty_when_marker_is_missing(self):
        sequence = self.module.map_platform_burst_to_switch_sequence(
            [self.module.GadgetSnapshot(agent_id=21, x=2823.0, y=-8883.0, gadget_id=716)],
            [self.module.GadgetSnapshot(agent_id=14, x=-2525.0, y=-9760.0, gadget_id=706)],
            [21, 19],
        )

        self.assertEqual(sequence, [])

    def test_learns_platform_mapping_from_manual_switch_sequence(self):
        platform_markers = [
            self.module.GadgetSnapshot(agent_id=21, x=2823.0, y=-8883.0, gadget_id=716),
            self.module.GadgetSnapshot(agent_id=19, x=2951.0, y=-9737.0, gadget_id=714),
            self.module.GadgetSnapshot(agent_id=18, x=3034.0, y=-9498.0, gadget_id=713),
            self.module.GadgetSnapshot(agent_id=20, x=3040.0, y=-9044.0, gadget_id=715),
        ]
        switches = [
            self.module.GadgetSnapshot(agent_id=13, x=-2528.0, y=-10037.0, gadget_id=705),
            self.module.GadgetSnapshot(agent_id=14, x=-2525.0, y=-9760.0, gadget_id=706),
            self.module.GadgetSnapshot(agent_id=15, x=-2384.0, y=-10418.0, gadget_id=707),
            self.module.GadgetSnapshot(agent_id=16, x=-2188.0, y=-10514.0, gadget_id=708),
        ]

        mapping = self.module.learn_platform_mapping(
            platform_markers,
            switches,
            [21, 19, 18, 20],
            [14, 16, 13, 15],
        )

        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.signature, "markers=713,714,715,716|switches=705,706,707,708")
        self.assertEqual(
            dict(mapping.marker_to_switch_gadget_ids),
            {716: 706, 714: 708, 713: 705, 715: 707},
        )

    def test_applies_learned_platform_mapping_to_new_live_agent_ids(self):
        mapping = self.module.PlatformMapping(
            signature="markers=713,714,715,716|switches=705,706,707,708",
            marker_to_switch_gadget_ids=((716, 706), (714, 708), (713, 705), (715, 707)),
        )
        platform_markers = [
            self.module.GadgetSnapshot(agent_id=121, x=2823.0, y=-8883.0, gadget_id=716),
            self.module.GadgetSnapshot(agent_id=119, x=2951.0, y=-9737.0, gadget_id=714),
            self.module.GadgetSnapshot(agent_id=118, x=3034.0, y=-9498.0, gadget_id=713),
            self.module.GadgetSnapshot(agent_id=120, x=3040.0, y=-9044.0, gadget_id=715),
        ]
        switches = [
            self.module.GadgetSnapshot(agent_id=113, x=-2528.0, y=-10037.0, gadget_id=705),
            self.module.GadgetSnapshot(agent_id=114, x=-2525.0, y=-9760.0, gadget_id=706),
            self.module.GadgetSnapshot(agent_id=115, x=-2384.0, y=-10418.0, gadget_id=707),
            self.module.GadgetSnapshot(agent_id=116, x=-2188.0, y=-10514.0, gadget_id=708),
        ]

        sequence = self.module.apply_platform_mapping(
            mapping,
            platform_markers,
            switches,
            [121, 119, 118, 120],
        )

        self.assertEqual(sequence, [114, 116, 113, 115])

    def test_does_not_apply_learned_platform_mapping_in_opposite_direction(self):
        mapping = self.module.PlatformMapping(
            signature="markers=713,714,715,716|switches=705,706,707,708",
            marker_to_switch_gadget_ids=((716, 706), (714, 708), (713, 705), (715, 707)),
        )
        platform_markers = [
            self.module.GadgetSnapshot(agent_id=16, x=-2188.0, y=-10514.0, gadget_id=708),
            self.module.GadgetSnapshot(agent_id=15, x=-2384.0, y=-10418.0, gadget_id=707),
            self.module.GadgetSnapshot(agent_id=14, x=-2525.0, y=-9760.0, gadget_id=706),
            self.module.GadgetSnapshot(agent_id=13, x=-2528.0, y=-10037.0, gadget_id=705),
        ]
        switches = [
            self.module.GadgetSnapshot(agent_id=18, x=3034.0, y=-9498.0, gadget_id=713),
            self.module.GadgetSnapshot(agent_id=20, x=3040.0, y=-9044.0, gadget_id=715),
            self.module.GadgetSnapshot(agent_id=21, x=2823.0, y=-8883.0, gadget_id=716),
            self.module.GadgetSnapshot(agent_id=19, x=2951.0, y=-9737.0, gadget_id=714),
        ]

        sequence = self.module.apply_platform_mapping(
            mapping,
            platform_markers,
            switches,
            [16, 15, 14, 13],
        )

        self.assertEqual(sequence, [])

    def test_applies_distinct_learned_platform_mapping_for_return_platform(self):
        mapping = self.module.PlatformMapping(
            signature="markers=705,706,707,708|switches=713,714,715,716",
            marker_to_switch_gadget_ids=((708, 713), (707, 714), (706, 715), (705, 716)),
        )
        platform_markers = [
            self.module.GadgetSnapshot(agent_id=16, x=-2188.0, y=-10514.0, gadget_id=708),
            self.module.GadgetSnapshot(agent_id=15, x=-2384.0, y=-10418.0, gadget_id=707),
            self.module.GadgetSnapshot(agent_id=14, x=-2525.0, y=-9760.0, gadget_id=706),
            self.module.GadgetSnapshot(agent_id=13, x=-2528.0, y=-10037.0, gadget_id=705),
        ]
        switches = [
            self.module.GadgetSnapshot(agent_id=18, x=3034.0, y=-9498.0, gadget_id=713),
            self.module.GadgetSnapshot(agent_id=20, x=3040.0, y=-9044.0, gadget_id=715),
            self.module.GadgetSnapshot(agent_id=21, x=2823.0, y=-8883.0, gadget_id=716),
            self.module.GadgetSnapshot(agent_id=19, x=2951.0, y=-9737.0, gadget_id=714),
        ]

        sequence = self.module.apply_platform_mapping(
            mapping,
            platform_markers,
            switches,
            [16, 15, 14, 13],
        )

        self.assertEqual(sequence, [18, 19, 20, 21])

    def test_known_mappings_do_not_use_inverse_when_exact_return_mapping_is_absent(self):
        mappings = [
            self.module.PlatformMapping(
                signature="markers=713,714,715,716|switches=705,706,707,708",
                marker_to_switch_gadget_ids=((716, 706), (714, 708), (713, 705), (715, 707)),
            )
        ]
        platform_markers = [
            self.module.GadgetSnapshot(agent_id=16, x=-2188.0, y=-10514.0, gadget_id=708),
            self.module.GadgetSnapshot(agent_id=15, x=-2384.0, y=-10418.0, gadget_id=707),
            self.module.GadgetSnapshot(agent_id=14, x=-2525.0, y=-9760.0, gadget_id=706),
            self.module.GadgetSnapshot(agent_id=13, x=-2528.0, y=-10037.0, gadget_id=705),
        ]
        switches = [
            self.module.GadgetSnapshot(agent_id=18, x=3034.0, y=-9498.0, gadget_id=713),
            self.module.GadgetSnapshot(agent_id=20, x=3040.0, y=-9044.0, gadget_id=715),
            self.module.GadgetSnapshot(agent_id=21, x=2823.0, y=-8883.0, gadget_id=716),
            self.module.GadgetSnapshot(agent_id=19, x=2951.0, y=-9737.0, gadget_id=714),
        ]

        sequence = self.module.map_platform_burst_with_known_mappings(
            mappings,
            platform_markers,
            switches,
            [16, 15, 14, 13],
            expected_switch_count=4,
        )

        self.assertEqual(sequence, [])

    def test_known_mappings_apply_return_platform_when_exact_mapping_exists(self):
        mappings = [
            self.module.PlatformMapping(
                signature="markers=713,714,715,716|switches=705,706,707,708",
                marker_to_switch_gadget_ids=((716, 706), (714, 708), (713, 705), (715, 707)),
            ),
            self.module.PlatformMapping(
                signature="markers=705,706,707,708|switches=713,714,715,716",
                marker_to_switch_gadget_ids=((708, 713), (707, 714), (706, 715), (705, 716)),
            ),
        ]
        platform_markers = [
            self.module.GadgetSnapshot(agent_id=16, x=-2188.0, y=-10514.0, gadget_id=708),
            self.module.GadgetSnapshot(agent_id=15, x=-2384.0, y=-10418.0, gadget_id=707),
            self.module.GadgetSnapshot(agent_id=14, x=-2525.0, y=-9760.0, gadget_id=706),
            self.module.GadgetSnapshot(agent_id=13, x=-2528.0, y=-10037.0, gadget_id=705),
        ]
        switches = [
            self.module.GadgetSnapshot(agent_id=18, x=3034.0, y=-9498.0, gadget_id=713),
            self.module.GadgetSnapshot(agent_id=20, x=3040.0, y=-9044.0, gadget_id=715),
            self.module.GadgetSnapshot(agent_id=21, x=2823.0, y=-8883.0, gadget_id=716),
            self.module.GadgetSnapshot(agent_id=19, x=2951.0, y=-9737.0, gadget_id=714),
        ]

        sequence = self.module.map_platform_burst_with_known_mappings(
            mappings,
            platform_markers,
            switches,
            [16, 15, 14, 13],
            expected_switch_count=4,
        )

        self.assertEqual(sequence, [18, 19, 20, 21])

    def test_mapping_file_contains_only_trusted_manual_entries(self):
        payload = json.loads(MAPPING_FILE_PATH.read_text(encoding="utf-8"))

        self.assertEqual(payload["version"], 1)
        for item in payload["mappings"]:
            self.assertEqual(item.get("source"), "manual")
            self.assertTrue(item.get("signature"))
            self.assertTrue(item.get("marker_to_switch_gadget_ids"))


if __name__ == "__main__":
    unittest.main()
