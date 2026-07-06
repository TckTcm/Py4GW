import importlib.util
import pathlib
import sys
import types
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "Py4GWCoreLib" / "Inventory.py"


class FakePyInventoryInstance:
    apply_upgrade_calls = []
    validate_calls = []
    equipped_items = {}
    inventory_ids = {}
    validate_result = True

    @classmethod
    def reset(cls):
        cls.apply_upgrade_calls = []
        cls.validate_calls = []
        cls.equipped_items = {}
        cls.inventory_ids = {}
        cls.validate_result = True

    def GetInventoryIDFromAgent(self, agent_id):
        return self.inventory_ids.get(agent_id, 0)

    def IsInventoryIDValid(self, inventory_id):
        return bool(inventory_id and inventory_id in set(self.inventory_ids.values()))

    def GetEquippedItemID(self, inventory_id, equip_slot):
        return self.equipped_items.get((inventory_id, equip_slot), 0)

    def GetUpgradeSlot(self, upgrade_item_id):
        if upgrade_item_id == 101:
            return 1
        if upgrade_item_id == 202:
            return 7
        return 0

    def ValidateUpgrade(self, target_item_id, upgrade_item_id):
        self.validate_calls.append((target_item_id, upgrade_item_id))
        return self.validate_result

    def ApplyUpgrade(self, inventory_id, target_item_id, upgrade_item_id, upgrade_slot=0, target_agent_id=0):
        self.apply_upgrade_calls.append((
            inventory_id,
            target_item_id,
            upgrade_item_id,
            upgrade_slot,
            target_agent_id,
        ))
        return True


class FakePyInventoryModule(types.ModuleType):
    def __init__(self):
        super().__init__("PyInventory")
        self.Bag = None

    def PyInventory(self):
        return FakePyInventoryInstance()


class FakeUIManager:
    send_calls = []
    send_result = True

    @classmethod
    def reset(cls):
        cls.send_calls = []
        cls.send_result = True

    @classmethod
    def SendUIMessage(cls, msgid, values, skip_hooks=False):
        cls.send_calls.append((msgid, list(values), skip_hooks))
        return cls.send_result


class InventoryUpgradeApiTests(unittest.TestCase):
    def setUp(self):
        FakePyInventoryInstance.reset()
        FakeUIManager.reset()
        sys.modules["Py4GW"] = types.ModuleType("Py4GW")
        sys.modules["PyInventory"] = FakePyInventoryModule()
        core = types.ModuleType("Py4GWCoreLib")
        core.__path__ = [str(MODULE_PATH.parent)]
        item_module = types.ModuleType("Py4GWCoreLib.Item")
        item_module.Item = types.SimpleNamespace()
        item_array_module = types.ModuleType("Py4GWCoreLib.ItemArray")
        item_array_module.ItemArray = types.SimpleNamespace()
        ui_manager_module = types.ModuleType("Py4GWCoreLib.UIManager")
        ui_manager_module.UIManager = FakeUIManager
        enums_pkg = types.ModuleType("Py4GWCoreLib.enums_src")
        item_enums_module = types.ModuleType("Py4GWCoreLib.enums_src.Item_enums")
        item_enums_module.Bags = types.SimpleNamespace()

        sys.modules["Py4GWCoreLib"] = core
        sys.modules["Py4GWCoreLib.Item"] = item_module
        sys.modules["Py4GWCoreLib.ItemArray"] = item_array_module
        sys.modules["Py4GWCoreLib.UIManager"] = ui_manager_module
        sys.modules["Py4GWCoreLib.enums_src"] = enums_pkg
        sys.modules["Py4GWCoreLib.enums_src.Item_enums"] = item_enums_module

        spec = importlib.util.spec_from_file_location("Py4GWCoreLib.Inventory", MODULE_PATH)
        self.inventory_module = importlib.util.module_from_spec(spec)
        sys.modules["Py4GWCoreLib.Inventory"] = self.inventory_module
        spec.loader.exec_module(self.inventory_module)

    def test_get_upgrade_slot_classifies_native_rune_interaction(self):
        self.assertEqual(self.inventory_module.Inventory.GetUpgradeSlot(101), 1)

    def test_is_inventory_id_valid_wraps_native_inventory_table_lookup(self):
        FakePyInventoryInstance.inventory_ids[42] = 321

        self.assertTrue(self.inventory_module.Inventory.IsInventoryIDValid(321))
        self.assertFalse(self.inventory_module.Inventory.IsInventoryIDValid(150))

    def test_apply_rune_to_equipped_armor_resolves_inventory_and_uses_native_item_order(self):
        FakePyInventoryInstance.inventory_ids[42] = 321
        FakePyInventoryInstance.equipped_items[(321, 2)] = 555

        result = self.inventory_module.Inventory.ApplyRuneToEquippedArmor(42, 2, 101)

        self.assertTrue(result)
        self.assertEqual(FakePyInventoryInstance.apply_upgrade_calls, [(321, 555, 101, 1, 42)])
        self.assertEqual(FakeUIManager.send_calls, [])

    def test_apply_upgrade_uses_native_item_order_without_ui_message(self):
        FakePyInventoryInstance.inventory_ids[42] = 321
        FakePyInventoryInstance.equipped_items[(321, 2)] = 555

        result = self.inventory_module.Inventory.ApplyUpgrade(321, 555, 101, 1, 42)

        self.assertTrue(result)
        self.assertEqual(FakePyInventoryInstance.apply_upgrade_calls, [(321, 555, 101, 1, 42)])
        self.assertEqual(FakeUIManager.send_calls, [])

    def test_apply_upgrade_rejects_same_target_and_upgrade_item_before_native_validation(self):
        FakePyInventoryInstance.inventory_ids[42] = 321

        result = self.inventory_module.Inventory.ApplyUpgrade(321, 101, 101, 1, 42)

        self.assertFalse(result)
        self.assertEqual(FakePyInventoryInstance.validate_calls, [])
        self.assertEqual(FakePyInventoryInstance.apply_upgrade_calls, [])

    def test_apply_rune_to_equipped_armor_rejects_non_rune_upgrade_slot(self):
        FakePyInventoryInstance.inventory_ids[42] = 321
        FakePyInventoryInstance.equipped_items[(321, 2)] = 555

        result = self.inventory_module.Inventory.ApplyRuneToEquippedArmor(42, 2, 202)

        self.assertFalse(result)
        self.assertEqual(FakePyInventoryInstance.apply_upgrade_calls, [])

    def test_apply_rune_to_equipped_armor_rejects_same_target_and_rune_before_native_validation(self):
        FakePyInventoryInstance.inventory_ids[42] = 321
        FakePyInventoryInstance.equipped_items[(321, 2)] = 101

        result = self.inventory_module.Inventory.ApplyRuneToEquippedArmor(42, 2, 101)

        self.assertFalse(result)
        self.assertEqual(FakePyInventoryInstance.validate_calls, [])
        self.assertEqual(FakePyInventoryInstance.apply_upgrade_calls, [])

    def test_apply_rune_to_equipped_armor_requires_native_validation(self):
        FakePyInventoryInstance.inventory_ids[42] = 321
        FakePyInventoryInstance.equipped_items[(321, 2)] = 555
        FakePyInventoryInstance.validate_result = False

        result = self.inventory_module.Inventory.ApplyRuneToEquippedArmor(42, 2, 101)

        self.assertFalse(result)
        self.assertEqual(FakePyInventoryInstance.apply_upgrade_calls, [])

    def test_apply_rune_to_equipped_armor_rejects_stale_hero_agent(self):
        FakePyInventoryInstance.inventory_ids[86] = 321
        FakePyInventoryInstance.equipped_items[(321, 2)] = 555

        party_module = types.ModuleType("Py4GWCoreLib.Party")
        party_module.Party = types.SimpleNamespace(
            GetHeroes=lambda: [types.SimpleNamespace(agent_id=91)],
            Heroes=types.SimpleNamespace(),
        )
        player_module = types.ModuleType("Py4GWCoreLib.Player")
        player_module.Player = types.SimpleNamespace(GetAgentID=lambda: 42)
        sys.modules["Py4GWCoreLib.Party"] = party_module
        sys.modules["Py4GWCoreLib.Player"] = player_module

        result = self.inventory_module.Inventory.ApplyRuneToEquippedArmor(86, 2, 101)

        self.assertFalse(result)
        self.assertEqual(FakePyInventoryInstance.apply_upgrade_calls, [])


if __name__ == "__main__":
    unittest.main()
