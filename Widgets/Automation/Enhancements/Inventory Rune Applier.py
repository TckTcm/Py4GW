import time

import Py4GW
from Py4GWCoreLib import Inventory, Item, ItemArray, Party, Player, PyImGui, UIManager, UpgradeWindow

try:
    from Py4GWCoreLib.enums_src.Item_enums import INVENTORY_BAGS
except Exception:
    INVENTORY_BAGS = [1, 2, 3, 4]

try:
    from Py4GWCoreLib.PacketSniffer import SNIFFER as PACKET_SNIFFER
except Exception:
    PACKET_SNIFFER = None


MODULE_NAME = "Inventory Armor Upgrader"
MODULE_ICON = "Textures/Module_Icons/Inventory.png"
INTERNAL_GWCA_UI_MESSAGE_MASK = 0x30000000
UPGRADE_CTO_HEADERS = {0x007F, 0x0080, 0x0082}
ARMOR_RUNE_UPGRADE_SLOT = 1
ARMOR_INSIGNIA_UPGRADE_SLOT = 7
ARMOR_UPGRADE_SLOTS = {ARMOR_RUNE_UPGRADE_SLOT, ARMOR_INSIGNIA_UPGRADE_SLOT}

ARMOR_SLOTS = [
    ("Chest", 2),
    ("Leggings", 3),
    ("Head", 4),
    ("Boots", 5),
    ("Gloves", 6),
]

_selected_rune_index = 0
_selected_armor_slot_index = 0
_selected_target_agent_index = 0
_target_agent_options = []
_last_status = "Ready."
_rune_name_cache = {}
_rune_name_requested = set()
_pending_upgrade = None
PENDING_UPGRADE_TIMEOUT_SECONDS = 5.0
UI_CAPTURE_MAX_LINES = 120
CTOS_CAPTURE_MAX_LINES = 80
_ui_payload_capture_active = False
_ui_payload_capture_lines = []
_ctos_packet_capture_active = False
_ctos_packet_capture_lines = []


def _log_status(message, message_type):
    global _last_status
    _last_status = message
    Py4GW.Console.Log(MODULE_NAME, message, message_type)


def _inventory_bag_ids():
    return [int(getattr(bag, "value", bag)) for bag in INVENTORY_BAGS]


def _safe_item_name(item_id):
    if item_id in _rune_name_cache:
        return _rune_name_cache[item_id]

    try:
        if Item.IsNameReady(item_id):
            name = Item.GetName(item_id)
            if name and name not in ("Unknown", "Timeout"):
                _rune_name_cache[item_id] = name
                _rune_name_requested.discard(item_id)
                return name
    except Exception:
        pass

    if item_id not in _rune_name_requested:
        try:
            Item.RequestName(item_id)
            _rune_name_requested.add(item_id)
        except Exception:
            pass
    return f"item {item_id}"


def _get_inventory_rune_items():
    runes = []
    bags = ItemArray.CreateBagList(*_inventory_bag_ids())
    for item_id in ItemArray.GetItemArray(bags):
        try:
            if int(Inventory.GetUpgradeSlot(item_id)) != ARMOR_RUNE_UPGRADE_SLOT:
                continue
        except Exception:
            continue
        runes.append((int(item_id), _safe_item_name(int(item_id))))
    return runes


def _get_inventory_upgrade_items():
    upgrades = []
    bags = ItemArray.CreateBagList(*_inventory_bag_ids())
    for item_id in ItemArray.GetItemArray(bags):
        try:
            if int(Inventory.GetUpgradeSlot(item_id)) not in ARMOR_UPGRADE_SLOTS:
                continue
        except Exception:
            continue
        upgrades.append((int(item_id), _safe_item_name(int(item_id))))
    return upgrades


def _get_target_agent_id(options=None):
    if options is None:
        options = _target_agent_options or _get_target_agent_options()
    if not options:
        return 0

    index = max(0, min(_selected_target_agent_index, len(options) - 1))
    return int(options[index][0] or 0)


def _get_target_agent_options():
    options = []
    seen_agent_ids = set()

    try:
        player_agent_id = int(Player.GetAgentID() or 0)
    except Exception:
        player_agent_id = 0
    if player_agent_id:
        options.append((player_agent_id, f"Player ({player_agent_id})"))
        seen_agent_ids.add(player_agent_id)

    try:
        heroes = list(Party.GetHeroes() or [])
    except Exception:
        heroes = []

    for hero_index, hero in enumerate(heroes, start=1):
        try:
            agent_id = int(getattr(hero, "agent_id", 0) or 0)
        except Exception:
            agent_id = 0
        if not agent_id or agent_id in seen_agent_ids:
            continue

        try:
            name = Party.Heroes.GetNameByAgentID(agent_id) or ""
        except Exception:
            name = ""
        if not name:
            name = f"Hero {hero_index}"

        options.append((agent_id, f"{name} ({agent_id})"))
        seen_agent_ids.add(agent_id)

    return options


def _clamp_selected_indexes(runes, target_options=None):
    global _selected_rune_index, _selected_armor_slot_index, _selected_target_agent_index
    if runes:
        _selected_rune_index = max(0, min(_selected_rune_index, len(runes) - 1))
    else:
        _selected_rune_index = 0
    _selected_armor_slot_index = max(0, min(_selected_armor_slot_index, len(ARMOR_SLOTS) - 1))
    if target_options:
        _selected_target_agent_index = max(0, min(_selected_target_agent_index, len(target_options) - 1))
    else:
        _selected_target_agent_index = 0


def _resolve_rune_application(agent_id, equip_slot, rune_item_id):
    return _resolve_upgrade_application(agent_id, equip_slot, rune_item_id)


def _get_upgrade_request_slot(item_upgrade_slot):
    if item_upgrade_slot == ARMOR_INSIGNIA_UPGRADE_SLOT:
        return 0
    return item_upgrade_slot


def _resolve_upgrade_application(agent_id, equip_slot, upgrade_item_id):
    inventory_id = int(Inventory.GetInventoryIDFromAgent(agent_id) or 0)
    if not inventory_id:
        return False, "inventory_id=0", None

    target_item_id = int(Inventory.GetEquippedItemID(inventory_id, equip_slot) or 0)
    if not target_item_id:
        return False, f"inventory_id={inventory_id}, target_item=0", None
    if target_item_id == int(upgrade_item_id):
        return False, f"inventory_id={inventory_id}, target_item={target_item_id}, upgrade_item={int(upgrade_item_id)}", None

    upgrade_slot = int(Inventory.GetUpgradeSlot(upgrade_item_id) or 0)
    if upgrade_slot not in ARMOR_UPGRADE_SLOTS:
        return False, f"inventory_id={inventory_id}, target_item={target_item_id}, upgrade_item={int(upgrade_item_id)}, upgrade_slot={upgrade_slot}", None
    request_upgrade_slot = _get_upgrade_request_slot(upgrade_slot)

    validate_ok = bool(Inventory.ValidateUpgrade(target_item_id, upgrade_item_id))
    if not validate_ok:
        return False, f"inventory_id={inventory_id}, target_item={target_item_id}, upgrade_item={int(upgrade_item_id)}, validate=0", None

    request = {
        "inventory_id": inventory_id,
        "target_item_id": target_item_id,
        "upgrade_slot": request_upgrade_slot,
    }
    diagnostic = f"inventory_id={inventory_id}, target_item={target_item_id}, upgrade_item={int(upgrade_item_id)}, upgrade_slot={request_upgrade_slot}"
    if request_upgrade_slot != upgrade_slot:
        diagnostic = f"{diagnostic}, item_upgrade_slot={upgrade_slot}"
    return True, diagnostic, request


def _describe_rune_application(agent_id, equip_slot, rune_item_id):
    return _describe_upgrade_application(agent_id, equip_slot, rune_item_id)


def _describe_upgrade_application(agent_id, equip_slot, upgrade_item_id):
    ok, diagnostic, _ = _resolve_upgrade_application(agent_id, equip_slot, upgrade_item_id)
    return ok, diagnostic


def _payload_bytes_to_u32_words(raw_bytes):
    data = [int(b) & 0xFF for b in (raw_bytes or [])]
    words = []
    for offset in range(0, len(data), 4):
        chunk = data[offset:offset + 4]
        if not chunk:
            continue
        if len(chunk) < 4:
            chunk = chunk + ([0] * (4 - len(chunk)))
        words.append(int.from_bytes(bytes(chunk), "little", signed=False))
    return words


def _format_word_list(words):
    if not words:
        return "[]"
    return "[" + ", ".join(f"0x{word:08x}" for word in words) + "]"


def _format_ui_payload_log(entry):
    tick, msgid, incoming, is_frame_message, frame_id, w_bytes, l_bytes = entry[:7]
    source = "frame" if is_frame_message else ("hook" if incoming else "sent")
    frame = int(frame_id or 0) if is_frame_message else 0
    w_words = _payload_bytes_to_u32_words(w_bytes)
    l_words = _payload_bytes_to_u32_words(l_bytes)
    return (
        f"tick={int(tick)} src={source} msg=0x{int(msgid):08x} frame={frame} "
        f"w={_format_word_list(w_words)} l={_format_word_list(l_words)}"
    )


def _is_relevant_payload_log(entry):
    try:
        msgid = int(entry[1])
        return (msgid & INTERNAL_GWCA_UI_MESSAGE_MASK) != INTERNAL_GWCA_UI_MESSAGE_MASK
    except Exception:
        return False


def _get_ui_payload_logs():
    try:
        get_logs = getattr(UIManager, "GetUIMessageLogs", None)
        if callable(get_logs):
            return list(get_logs())

        import PyUIManager

        return list(PyUIManager.UIManager.get_ui_message_logs())
    except Exception as exception:
        _log_status(f"UI capture failed: {exception}", Py4GW.Console.MessageType.Error)
        return []


def _clear_native_ui_payload_logs():
    try:
        clear_logs = getattr(UIManager, "ClearUIMessageLogs", None)
        if callable(clear_logs):
            clear_logs()
        else:
            import PyUIManager

            PyUIManager.UIManager.clear_ui_message_logs()
    except Exception as exception:
        _log_status(f"Failed to reset payloads: {exception}", Py4GW.Console.MessageType.Error)
        return False
    return True


def _clear_ui_payload_capture():
    global _ui_payload_capture_lines
    if not _clear_native_ui_payload_logs():
        return False

    _ui_payload_capture_lines = []
    _log_status("UI payloads reset.", Py4GW.Console.MessageType.Info)
    return True


def _start_ui_payload_capture():
    global _ui_payload_capture_active
    if not _clear_ui_payload_capture():
        return False

    _ui_payload_capture_active = True
    _log_status("UI capture started.", Py4GW.Console.MessageType.Info)
    return True


def _stop_ui_payload_capture():
    global _ui_payload_capture_active
    _ui_payload_capture_active = False
    _refresh_ui_payload_capture()
    _log_status("UI capture stopped.", Py4GW.Console.MessageType.Info)
    return True


def _refresh_ui_payload_capture(limit=UI_CAPTURE_MAX_LINES):
    global _ui_payload_capture_lines
    lines = []
    for entry in _get_ui_payload_logs():
        if not _is_relevant_payload_log(entry):
            continue
        try:
            lines.append(_format_ui_payload_log(entry))
        except Exception as exception:
            lines.append(f"unreadable payload: {exception}")

    _ui_payload_capture_lines = lines[-int(limit):]
    return list(_ui_payload_capture_lines)


def _dump_ui_payload_capture():
    lines = _refresh_ui_payload_capture()
    if not lines:
        _log_status("UI capture is empty.", Py4GW.Console.MessageType.Warning)
        return False

    for line in lines:
        Py4GW.Console.Log(MODULE_NAME, line, Py4GW.Console.MessageType.Info)
    _log_status(f"{len(lines)} UI payload(s) logged.", Py4GW.Console.MessageType.Info)
    return True


def _copy_ui_payload_capture():
    lines = _ui_payload_capture_lines or _refresh_ui_payload_capture()
    if not lines:
        _log_status("UI capture is empty.", Py4GW.Console.MessageType.Warning)
        return False

    try:
        PyImGui.set_clipboard_text("\n".join(lines))
    except Exception as exception:
        _log_status(f"Failed to copy UI capture: {exception}", Py4GW.Console.MessageType.Error)
        return False

    _log_status(f"{len(lines)} UI payload(s) copied.", Py4GW.Console.MessageType.Info)
    return True


def _get_ctos_packet_logs():
    if PACKET_SNIFFER is None:
        _log_status("PacketSniffer unavailable.", Py4GW.Console.MessageType.Error)
        return []

    try:
        return list(PACKET_SNIFFER.get_logs("CToS"))
    except TypeError:
        try:
            return [entry for entry in PACKET_SNIFFER.get_logs() if getattr(entry, "direction", "") == "CToS"]
        except Exception as exception:
            _log_status(f"CToS capture failed: {exception}", Py4GW.Console.MessageType.Error)
            return []
    except Exception as exception:
        _log_status(f"CToS capture failed: {exception}", Py4GW.Console.MessageType.Error)
        return []


def _clear_native_ctos_packet_logs():
    if PACKET_SNIFFER is None:
        _log_status("PacketSniffer unavailable.", Py4GW.Console.MessageType.Error)
        return False

    try:
        PACKET_SNIFFER.clear_logs("CToS")
    except TypeError:
        PACKET_SNIFFER.clear_logs()
    except Exception as exception:
        _log_status(f"Failed to reset CToS: {exception}", Py4GW.Console.MessageType.Error)
        return False
    return True


def _clear_ctos_packet_capture():
    global _ctos_packet_capture_lines
    if not _clear_native_ctos_packet_logs():
        return False

    _ctos_packet_capture_lines = []
    _log_status("CToS capture reset.", Py4GW.Console.MessageType.Info)
    return True


def _start_ctos_packet_capture():
    global _ctos_packet_capture_active
    if PACKET_SNIFFER is None:
        _log_status("PacketSniffer unavailable.", Py4GW.Console.MessageType.Error)
        return False
    if not _clear_ctos_packet_capture():
        return False

    try:
        started = PACKET_SNIFFER.initialize("CToS")
    except TypeError:
        started = PACKET_SNIFFER.initialize()
    except Exception as exception:
        _log_status(f"Failed to initialize CToS capture: {exception}", Py4GW.Console.MessageType.Error)
        return False

    if not started:
        _log_status("CToS capture initialization refused.", Py4GW.Console.MessageType.Error)
        return False

    _ctos_packet_capture_active = True
    _log_status("CToS capture started.", Py4GW.Console.MessageType.Info)
    return True


def _stop_ctos_packet_capture():
    global _ctos_packet_capture_active
    _ctos_packet_capture_active = False
    _refresh_ctos_packet_capture()
    if PACKET_SNIFFER is not None:
        try:
            PACKET_SNIFFER.terminate("CToS")
        except TypeError:
            PACKET_SNIFFER.terminate()
        except Exception:
            pass
    _log_status("CToS capture stopped.", Py4GW.Console.MessageType.Info)
    return True


def _format_ctos_packet_log(entry):
    tick = int(getattr(entry, "tick", 0) or 0)
    direction = str(getattr(entry, "direction", "CToS") or "CToS")
    header = int(getattr(entry, "header", 0) or 0)
    size = int(getattr(entry, "size", 0) or 0)
    raw = bytes(getattr(entry, "data", b"") or b"")
    words = _payload_bytes_to_u32_words(raw)
    decoded = ""
    if PACKET_SNIFFER is not None:
        try:
            decoded = str(PACKET_SNIFFER.decode_packet(direction, header, size, raw))
        except Exception:
            decoded = ""
    if not decoded:
        name = PACKET_SNIFFER.get_packet_name(direction, header) if PACKET_SNIFFER is not None else f"0x{header:04X}"
        decoded = f"{name} size={size}"
    return (
        f"tick={tick} dir={direction} header=0x{header:04x} {decoded} "
        f"words={_format_word_list(words)} raw={raw.hex(' ')}"
    )


def _is_relevant_ctos_packet(entry):
    try:
        return getattr(entry, "direction", "") == "CToS" and int(getattr(entry, "header", 0)) in UPGRADE_CTO_HEADERS
    except Exception:
        return False


def _refresh_ctos_packet_capture(limit=CTOS_CAPTURE_MAX_LINES):
    global _ctos_packet_capture_lines
    lines = []
    for entry in _get_ctos_packet_logs():
        if not _is_relevant_ctos_packet(entry):
            continue
        try:
            lines.append(_format_ctos_packet_log(entry))
        except Exception as exception:
            lines.append(f"unreadable CToS packet: {exception}")

    _ctos_packet_capture_lines = lines[-int(limit):]
    return list(_ctos_packet_capture_lines)


def _dump_ctos_packet_capture():
    lines = _refresh_ctos_packet_capture()
    if not lines:
        _log_status("CToS capture is empty.", Py4GW.Console.MessageType.Warning)
        return False

    for line in lines:
        Py4GW.Console.Log(MODULE_NAME, line, Py4GW.Console.MessageType.Info)
    _log_status(f"{len(lines)} CToS upgrade packet(s) logged.", Py4GW.Console.MessageType.Info)
    return True


def _copy_ctos_packet_capture():
    lines = _ctos_packet_capture_lines or _refresh_ctos_packet_capture()
    if not lines:
        _log_status("CToS capture is empty.", Py4GW.Console.MessageType.Warning)
        return False

    try:
        PyImGui.set_clipboard_text("\n".join(lines))
    except Exception as exception:
        _log_status(f"Failed to copy CToS capture: {exception}", Py4GW.Console.MessageType.Error)
        return False

    _log_status(f"{len(lines)} CToS packet(s) copied.", Py4GW.Console.MessageType.Info)
    return True


def _set_pending_upgrade(rune_name, armor_label, agent_id):
    global _pending_upgrade
    _pending_upgrade = {
        "rune_name": rune_name,
        "armor_label": armor_label,
        "agent_id": agent_id,
        "started_at": time.monotonic(),
    }


def _advance_pending_upgrade(now=None):
    global _pending_upgrade
    if not _pending_upgrade:
        return False

    if now is None:
        now = time.monotonic()

    rune_name = _pending_upgrade["rune_name"]
    armor_label = _pending_upgrade["armor_label"]
    agent_id = _pending_upgrade["agent_id"]

    try:
        if UpgradeWindow.IsOpen():
            if UpgradeWindow.Confirm():
                _pending_upgrade = None
                _log_status(
                    f"Confirmation sent for {rune_name} on {armor_label} (agent {agent_id}).",
                    Py4GW.Console.MessageType.Info,
                )
                return True
            _log_status(
                f"Upgrade window is open but confirmation failed for {rune_name}.",
                Py4GW.Console.MessageType.Warning,
            )
            return False
    except Exception as exception:
        _pending_upgrade = None
        _log_status(f"Upgrade confirmation error: {exception}", Py4GW.Console.MessageType.Error)
        return False

    if now - _pending_upgrade["started_at"] > PENDING_UPGRADE_TIMEOUT_SECONDS:
        _pending_upgrade = None
        _log_status(
            f"Upgrade confirmation timed out for {rune_name} on {armor_label} (agent {agent_id}).",
            Py4GW.Console.MessageType.Warning,
        )
        return False

    return False


def _apply_selected_rune():
    return _apply_selected_upgrade()


def _apply_selected_upgrade():
    if _pending_upgrade:
        _log_status("Upgrade request already pending.", Py4GW.Console.MessageType.Warning)
        return False

    upgrades = _get_inventory_upgrade_items()
    target_options = _get_target_agent_options()
    _clamp_selected_indexes(upgrades, target_options)
    if not upgrades:
        _log_status("No applicable armor upgrade found in inventory.", Py4GW.Console.MessageType.Warning)
        return False

    agent_id = _get_target_agent_id(target_options)
    if not agent_id:
        _log_status("No target agent available.", Py4GW.Console.MessageType.Warning)
        return False

    upgrade_item_id, upgrade_name = upgrades[_selected_rune_index]
    armor_label, equip_slot = ARMOR_SLOTS[_selected_armor_slot_index]
    try:
        request_ok, diagnostic, request = _resolve_upgrade_application(agent_id, equip_slot, upgrade_item_id)
        applied = bool(request_ok and request and Inventory.ApplyUpgrade(
            request["inventory_id"],
            request["target_item_id"],
            upgrade_item_id,
            request["upgrade_slot"],
            agent_id,
        ))
    except Exception as exception:
        _log_status(f"Upgrade application error: {exception}", Py4GW.Console.MessageType.Error)
        return False

    if applied:
        _log_status(
            f"Application request sent for {upgrade_name} on {armor_label} (agent {agent_id}; {diagnostic}).",
            Py4GW.Console.MessageType.Info,
        )
        return True

    _log_status(
        f"Native application refused for {upgrade_name} on {armor_label} (agent {agent_id}; {diagnostic}).",
        Py4GW.Console.MessageType.Warning,
    )
    return False


def _safe_apply_selected_rune():
    return _safe_apply_selected_upgrade()


def _safe_apply_selected_upgrade():
    try:
        return _apply_selected_upgrade()
    except Exception as exception:
        _log_status(f"Upgrade widget error: {exception}", Py4GW.Console.MessageType.Error)
        return False


def main():
    global _selected_rune_index, _selected_armor_slot_index, _selected_target_agent_index, _target_agent_options

    _advance_pending_upgrade()
    if _ui_payload_capture_active:
        _refresh_ui_payload_capture()
    if _ctos_packet_capture_active:
        _refresh_ctos_packet_capture()

    if PyImGui.begin(MODULE_NAME, PyImGui.WindowFlags.AlwaysAutoResize):
        upgrades = _get_inventory_upgrade_items()
        _target_agent_options = _get_target_agent_options()
        _clamp_selected_indexes(upgrades, _target_agent_options)

        if _target_agent_options:
            target_labels = [label for _, label in _target_agent_options]
            _selected_target_agent_index = PyImGui.combo("Target", _selected_target_agent_index, target_labels)
        else:
            PyImGui.text("No player or hero available.")

        if upgrades:
            upgrade_labels = [f"{name} ({item_id})" for item_id, name in upgrades]
            _selected_rune_index = PyImGui.combo("Upgrade", _selected_rune_index, upgrade_labels)
        else:
            PyImGui.text("No applicable armor upgrade in bags.")

        armor_labels = [label for label, _ in ARMOR_SLOTS]
        _selected_armor_slot_index = PyImGui.combo("Armor piece", _selected_armor_slot_index, armor_labels)

        target_agent_id = _get_target_agent_id()
        PyImGui.text(f"Target agent: {target_agent_id or 'none'}")

        if PyImGui.button("Apply upgrade", width=180, height=28):
            _safe_apply_selected_upgrade()

        PyImGui.text(_last_status)

        PyImGui.separator()
        if PyImGui.button("Start UI capture", width=160, height=24):
            _start_ui_payload_capture()
        PyImGui.same_line(0.0, 6.0)
        if PyImGui.button("Stop UI capture", width=150, height=24):
            _stop_ui_payload_capture()

        if PyImGui.button("Refresh capture", width=160, height=24):
            _refresh_ui_payload_capture()
        PyImGui.same_line(0.0, 6.0)
        if PyImGui.button("Log capture", width=150, height=24):
            _dump_ui_payload_capture()

        if PyImGui.button("Copy capture", width=160, height=24):
            _copy_ui_payload_capture()
        PyImGui.same_line(0.0, 6.0)
        if PyImGui.button("Clear payloads", width=150, height=24):
            _clear_ui_payload_capture()

        for line in _ui_payload_capture_lines[-10:]:
            PyImGui.text_wrapped(line)

        PyImGui.separator()
        if PyImGui.button("Start CToS capture", width=160, height=24):
            _start_ctos_packet_capture()
        PyImGui.same_line(0.0, 6.0)
        if PyImGui.button("Stop CToS capture", width=150, height=24):
            _stop_ctos_packet_capture()

        if PyImGui.button("Log CToS", width=160, height=24):
            _dump_ctos_packet_capture()
        PyImGui.same_line(0.0, 6.0)
        if PyImGui.button("Copy CToS", width=150, height=24):
            _copy_ctos_packet_capture()

        if PyImGui.button("Clear CToS", width=160, height=24):
            _clear_ctos_packet_capture()

        for line in _ctos_packet_capture_lines[-10:]:
            PyImGui.text_wrapped(line)

    PyImGui.end()
