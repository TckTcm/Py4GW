import importlib.util
import pathlib
import struct
import sys
import types
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "Py4GWCoreLib" / "PacketSniffer.py"


class FakeNativePacketSniffer:
    @staticmethod
    def instance():
        return FakeNativePacketSniffer()

    def initialize(self):
        return True

    def initialize_ctos(self):
        return True

    def initialize_stoc(self):
        return True

    def terminate(self):
        return None

    def terminate_ctos(self):
        return None

    def terminate_stoc(self):
        return None

    def get_logs(self):
        return []

    def get_logs_by_direction(self, direction):
        return []

    def clear_logs(self):
        return None

    def clear_logs_by_direction(self, direction):
        return None


class PacketSnifferUpgradeDecodeTests(unittest.TestCase):
    def setUp(self):
        sys.modules["PyPacketSniffer"] = types.SimpleNamespace(
            PacketSniffer=FakeNativePacketSniffer,
            PacketDirection=types.SimpleNamespace(StoC=0, CToS=1),
        )

        core = types.ModuleType("Py4GWCoreLib")
        core.__path__ = [str(MODULE_PATH.parent)]
        enums_pkg = types.ModuleType("Py4GWCoreLib.enums_src")
        enums_pkg.__path__ = [str(MODULE_PATH.parent / "enums_src")]
        sys.modules["Py4GWCoreLib"] = core
        sys.modules["Py4GWCoreLib.enums_src"] = enums_pkg

        spec = importlib.util.spec_from_file_location("Py4GWCoreLib.PacketSniffer", MODULE_PATH)
        self.packet_sniffer_module = importlib.util.module_from_spec(spec)
        sys.modules["Py4GWCoreLib.PacketSniffer"] = self.packet_sniffer_module
        spec.loader.exec_module(self.packet_sniffer_module)

    def tearDown(self):
        sys.modules.pop("PyPacketSniffer", None)
        sys.modules.pop("Py4GWCoreLib.PacketSniffer", None)
        sys.modules.pop("Py4GWCoreLib.enums_src", None)

    def test_names_native_item_upgrade_order_packets(self):
        sniffer = self.packet_sniffer_module.PacketSniffer()

        self.assertEqual(sniffer.get_packet_name("CToS", 0x0080), "ITEM_UPGRADE_BEGIN")
        self.assertEqual(sniffer.get_packet_name("CToS", 0x007F), "ITEM_UPGRADE_ADD")
        self.assertEqual(sniffer.get_packet_name("CToS", 0x0082), "ITEM_UPGRADE_END")

    def test_decodes_native_item_upgrade_order_fields(self):
        sniffer = self.packet_sniffer_module.PacketSniffer()

        begin = sniffer.decode_packet("CToS", 0x0080, 12, struct.pack("<III", 0x0080, 185, 3021))
        add = sniffer.decode_packet("CToS", 0x007F, 12, struct.pack("<III", 0x007F, 1, 19506))
        end = sniffer.decode_packet("CToS", 0x0082, 4, struct.pack("<I", 0x0082))

        self.assertIn("ITEM_UPGRADE_BEGIN", begin)
        self.assertIn("target_inventory_id=185", begin)
        self.assertIn("target_item_id=3021", begin)
        self.assertIn("ITEM_UPGRADE_ADD", add)
        self.assertIn("upgrade_slot=1", add)
        self.assertIn("upgrade_item_id=19506", add)
        self.assertIn("ITEM_UPGRADE_END", end)


if __name__ == "__main__":
    unittest.main()
