# Inventory Hero Selection And Item Upgrade RE

This note documents the reverse-engineered inventory flows used by the Py4GW widgets for:

- selecting a hero in the native inventory window
- applying an inventory rune or upgrade to an equipped armor piece

The important implementation split is:

- C++ exposes only native helpers that cannot be implemented safely from Python.
- Python owns widget state, item discovery, validation, labels, and user workflow.

## Hero Inventory Selection

The inventory equipment window keeps the selected inventory target in its frame context. The hero selector widget should not synthesize mouse clicks. It should send the native frame message that the inventory window already uses to switch the selected agent.

The working path is:

1. Python finds the desired party hero and resolves its agent id.
2. Python opens or reuses the native inventory window.
3. Python calls the exposed UI manager helper that sends the inventory set-agent frame message to the `Inventory-Equipment` frame.
4. C++ validates the target frame and inventory id before forwarding the message.

The important guard is that hero inventory ids can become stale when the party changes. When a hero is removed and a new hero is added, the inventory frame may still hold the previous selection. `ItemMgr.cpp` blocks stale `Inventory-Equipment` refreshes and stale item updates so the client does not dereference an invalid inventory.

## Rune And Upgrade Application

The actual item upgrade is a native item-order sequence, not a click:

```text
ITEM_UPGRADE_BEGIN  header 0x0080: target_inventory_id, target_item_id
ITEM_UPGRADE_ADD    header 0x007f: upgrade_slot, upgrade_item_id
ITEM_UPGRADE_END    header 0x0082
```

Observed rune captures confirmed that armor runes use `upgrade_slot=1`.

The exposed Python call is:

```python
Inventory.ApplyUpgrade(
    inventory_id,
    target_item_id,
    upgrade_item_id,
    upgrade_slot,
    target_agent_id,
)
```

Python is responsible for selecting the rune item, selecting the armor slot, resolving the selected hero/player inventory id, and refusing obvious bad requests before calling C++. C++ then validates the inventory id, item ids, interaction flags, and native `ValidateUpgrade` before sending the order sequence.

## Native Function Map

The C++ layer scans these Guild Wars functions from assertion anchors in `ItCliApi.cpp`:

| Helper | Purpose |
|---|---|
| `ValidateUpgrade_Func` | Native compatibility check for target item and upgrade item |
| `OrderUpgradeBegin_Func` | Sends the begin order for target inventory and target item |
| `OrderUpgradeAdd_Func` | Sends the upgrade slot and upgrade item |
| `OrderUpgradeEnd_Func` | Completes the upgrade order |
| `GetInventoryIDFromAgent_Func` | Resolves the native inventory id for a player or hero agent |
| `GetEquippedItemID_Func` | Resolves equipped item id for an inventory/equipment slot |
| `InventoryTableFind_Func` | Validates that an inventory id still exists in the item context |

## Post-Upgrade UI Continuation Guard

The client also emits internal UI continuation messages after the native upgrade path. These messages are safe in the normal UI-driven flow because client globals are initialized by the inventory UI. They are unsafe after Py4GW's direct native order sequence because those UI globals are not part of the packet path.

Two crash signatures identified this:

| UI message | Crash | Cause |
|---|---|---|
| `0x10000108` | `Assertion: upgradeItemId` at `ItCliApi.cpp(1659)` | Client UI continuation called `OrderUpgradeAdd(0, 0)` from stale globals |
| `0x10000109` | `Assertion: ptr` at `ItCliApi.cpp(1004)` | Client UI continuation rebuilt an upgrade UI payload using item id `0` |

The fix in `ItemMgr.cpp` arms a short post-upgrade guard before `OrderUpgradeBegin/Add/End`. During that window, it blocks a small number of stale `0x10000108` and `0x10000109` messages, then automatically disables itself. This preserves the successful native CToS order sequence while preventing the follow-up UI path from dereferencing uninitialized upgrade state.

## Implementation Files

Python:

- `Py4GWCoreLib/Inventory.py`
- `Widgets/Automation/Enhancements/Hero Inventory Selector.py`
- `Widgets/Automation/Enhancements/Inventory Rune Applier.py`
- `tests/test_hero_inventory_selector.py`
- `tests/test_inventory_rune_applier_widget.py`
- `tests/test_inventory_upgrade_api.py`
- `tests/test_packet_sniffer_upgrade_decode.py`

C++:

- `include/py_Inventory.h`
- `src/py_Inventory.cpp`
- `vendor/gwca/Include/GWCA/Managers/ItemMgr.h`
- `vendor/gwca/Source/ItemMgr.cpp`
- `vendor/gwca/Source/UIMgr.cpp`
- `tests/test_inventory_upgrade_bindings.py`
- `tests/test_inventory_equipment_probe_guards.py`
- `tests/test_move_item_guards.py`
- `tests/test_ui_payload_logging.py`

## Operational Notes

After rebuilding `Py4GW_cpp_files`, copy the rebuilt DLL to `Py4GW/Py4GW.dll` before injecting into `Gw.exe`.

If a future crash happens immediately after a successful upgrade, inspect the crash stack for the UI message id near the Py4GW hook frame. The previously fixed continuation messages are `0x10000108` and `0x10000109`.
