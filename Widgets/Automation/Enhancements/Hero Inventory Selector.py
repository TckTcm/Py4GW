from Py4GWCoreLib import *
from Py4GWCoreLib.enums_src.UI_enums import WindowID
import Py4GW
import time

MODULE_NAME = "Sélecteur héros inventaire"
MODULE_ICON = "Textures/Module_Icons/Hero Helper.png"

NATIVE_RETRY_DELAY_SECONDS = 0.08
NATIVE_RETRY_LIMIT = 8
NATIVE_TIMEOUT_SECONDS = 2.5
INVENTORY_EQUIPMENT_FRAME_LABEL = "Inventory-Equipment"
INVENTORY_SET_AGENT_FRAME_MESSAGE = 0x56

_last_status = "Prêt."
_selection_state = "idle"
_selection_hero_agent_id = 0
_selection_deadline = 0.0
_selection_next_action = 0.0
_selection_native_attempts = 0
_selection_direct_pending = False
_selection_direct_completed = False
_selection_direct_sent = False
_selection_direct_frame_id = 0
_selection_direct_error = ""


def _log_status(message, message_type):
    global _last_status
    _last_status = message
    Py4GW.Console.Log(MODULE_NAME, message, message_type)


def _ensure_inventory_window_open():
    if not UIManager.IsWindowVisible(WindowID.WindowID_Inventory):
        UIManager.SetWindowVisible(WindowID.WindowID_Inventory, True)


def _hero_name():
    return Party.Heroes.GetNameByAgentID(_selection_hero_agent_id) or f"agent {_selection_hero_agent_id}"


def _current_hero_one_agent_id():
    try:
        return int(Party.Heroes.GetHeroAgentIDByPartyPosition(1) or 0)
    except Exception:
        return 0


def _is_selection_target_current():
    current_agent_id = _current_hero_one_agent_id()
    if current_agent_id == _selection_hero_agent_id:
        return True

    if current_agent_id:
        _log_status(
            f"Selection annulee: hero 1 a change (ancien agent {_selection_hero_agent_id}, nouvel agent {current_agent_id}).",
            Py4GW.Console.MessageType.Warning,
        )
    else:
        _log_status("Selection annulee: hero 1 n'est plus dans le groupe.", Py4GW.Console.MessageType.Warning)
    return False


def _get_valid_inventory_id_for_agent(agent_id):
    global _selection_direct_error

    try:
        inventory_id = int(Inventory.GetInventoryIDFromAgent(agent_id) or 0)
    except Exception as exception:
        _selection_direct_error = f"inventaire indisponible: {exception}"
        return 0

    if not inventory_id:
        _selection_direct_error = "inventaire non pret"
        return 0

    if inventory_id == int(agent_id):
        _selection_direct_error = f"inventaire {inventory_id} identique a l'agent"
        return 0

    validator = getattr(Inventory, "IsInventoryIDValid", None)
    if not callable(validator):
        _selection_direct_error = "validateur inventaire indisponible"
        return 0

    try:
        if not bool(validator(inventory_id)):
            _selection_direct_error = f"inventaire {inventory_id} invalide"
            return 0
    except Exception as exception:
        _selection_direct_error = f"validation inventaire impossible: {exception}"
        return 0

    return inventory_id


def _selection_debug_details():
    try:
        selected_agent_id = Party.Heroes.GetInventorySelectedAgentID()
        visible = UIManager.IsWindowVisible(WindowID.WindowID_Inventory)
        direct_error = _selection_direct_error or "none"
        return (
            f"selected_agent_id={selected_agent_id}, "
            f"direct_frame={_selection_direct_frame_id}, "
            f"direct_sent={1 if _selection_direct_sent else 0}, "
            f"direct_done={1 if _selection_direct_completed else 0}, "
            f"direct_error={direct_error}, "
            f"inventory_visible={visible}"
        )
    except Exception as exception:
        return f"diagnostic indisponible: {exception}"


def _get_inventory_equipment_frame_id():
    native_resolver = getattr(Party.Heroes, "GetInventoryEquipmentFrameID", None)
    if native_resolver:
        return int(native_resolver() or 0)

    return int(UIManager.GetFrameIDByLabel(INVENTORY_EQUIPMENT_FRAME_LABEL) or 0)


def _queue_direct_inventory_label_select():
    global _selection_direct_pending, _selection_direct_completed, _selection_direct_sent, _selection_direct_frame_id, _selection_direct_error
    agent_id = _selection_hero_agent_id
    _selection_direct_pending = True
    _selection_direct_completed = False
    _selection_direct_sent = False
    _selection_direct_frame_id = 0
    _selection_direct_error = ""

    def _send_on_game_thread():
        global _selection_direct_pending, _selection_direct_completed, _selection_direct_sent, _selection_direct_frame_id, _selection_direct_error
        try:
            current_agent_id = _current_hero_one_agent_id()
            if current_agent_id != agent_id:
                _selection_direct_error = f"hero 1 change avant envoi (ancien agent {agent_id}, nouvel agent {current_agent_id})"
                _selection_direct_sent = False
                return

            inventory_id = _get_valid_inventory_id_for_agent(agent_id)
            if not inventory_id:
                _selection_direct_sent = False
                return

            frame_id = _get_inventory_equipment_frame_id()
            _selection_direct_frame_id = frame_id
            _selection_direct_sent = bool(
                frame_id and UIManager.SendFrameUIMessage(
                    frame_id,
                    INVENTORY_SET_AGENT_FRAME_MESSAGE,
                    agent_id,
                    0,
                )
            )
        except Exception as exception:
            _selection_direct_error = str(exception)
            _selection_direct_sent = False
        finally:
            _selection_direct_completed = True
            _selection_direct_pending = False

    Py4GW.Game.enqueue(_send_on_game_thread)


def _try_native_select_hero_one():
    global _selection_native_attempts

    selected_agent_id = Party.Heroes.GetInventorySelectedAgentID()
    if selected_agent_id == _selection_hero_agent_id:
        _log_status(f"{_hero_name()} sélectionné dans l'inventaire.", Py4GW.Console.MessageType.Info)
        return True

    if _selection_direct_pending and not _selection_direct_completed:
        _log_status(
            f"Message natif direct en attente pour {_hero_name()}; label={INVENTORY_EQUIPMENT_FRAME_LABEL}.",
            Py4GW.Console.MessageType.Info,
        )
        return False

    if _selection_native_attempts >= NATIVE_RETRY_LIMIT:
        return False

    _selection_native_attempts += 1
    _queue_direct_inventory_label_select()
    if _selection_direct_completed and not _selection_direct_sent and _selection_direct_error:
        _log_status(
            f"Selection native differee pour {_hero_name()}: {_selection_direct_error} "
            f"(tentative {_selection_native_attempts}/{NATIVE_RETRY_LIMIT}; agent inventaire actuel: {selected_agent_id}).",
            Py4GW.Console.MessageType.Warning,
        )
    else:
        _log_status(
            f"Envoi natif Python 0x56 pour {_hero_name()} via {INVENTORY_EQUIPMENT_FRAME_LABEL} "
            f"(tentative {_selection_native_attempts}/{NATIVE_RETRY_LIMIT}; agent inventaire actuel: {selected_agent_id}).",
            Py4GW.Console.MessageType.Info,
        )
    return False


def _start_native_selection(hero_agent_id):
    global _selection_state, _selection_hero_agent_id, _selection_deadline, _selection_next_action, _selection_native_attempts, _selection_direct_pending, _selection_direct_completed, _selection_direct_sent, _selection_direct_frame_id, _selection_direct_error
    _selection_hero_agent_id = hero_agent_id
    _selection_native_attempts = 0
    _selection_direct_pending = False
    _selection_direct_completed = False
    _selection_direct_sent = False
    _selection_direct_frame_id = 0
    _selection_direct_error = ""
    now = time.perf_counter()
    _selection_deadline = now + NATIVE_TIMEOUT_SECONDS

    _ensure_inventory_window_open()
    _selection_state = "retry_native"
    _selection_next_action = now
    _log_status(f"Demande sélection héro 1 reçue ({_hero_name()}); appel natif en attente.", Py4GW.Console.MessageType.Info)


def _tick_native_selection():
    global _selection_state, _selection_next_action, _selection_native_attempts
    if _selection_state == "idle":
        return

    now = time.perf_counter()
    if now > _selection_deadline:
        _selection_state = "idle"
        _log_status(
            f"Sélection native impossible pour {_hero_name()} ({_selection_debug_details()}).",
            Py4GW.Console.MessageType.Warning,
        )
        return

    if now < _selection_next_action:
        return

    if not _is_selection_target_current():
        _selection_state = "idle"
        return

    if _selection_state == "retry_native":
        _ensure_inventory_window_open()
        if _try_native_select_hero_one():
            _selection_state = "idle"
            return

        if _selection_direct_pending or _selection_native_attempts < NATIVE_RETRY_LIMIT:
            _selection_next_action = now + NATIVE_RETRY_DELAY_SECONDS
            return

        _selection_state = "idle"
        _log_status(
            f"Sélection native impossible pour {_hero_name()} ({_selection_debug_details()}).",
            Py4GW.Console.MessageType.Warning,
        )
        return


def _select_hero_one():
    hero_agent_id = Party.Heroes.GetHeroAgentIDByPartyPosition(1)
    if not hero_agent_id:
        _log_status("Héro 1 introuvable dans le groupe.", Py4GW.Console.MessageType.Warning)
        return

    _start_native_selection(hero_agent_id)


def _log_runtime_error(context, exception):
    global _selection_state
    _selection_state = "idle"
    _log_status(f"Erreur {context}: {exception}", Py4GW.Console.MessageType.Error)


def _safe_select_hero_one():
    try:
        _select_hero_one()
    except Exception as exception:
        _log_runtime_error("sélection héros", exception)


def _safe_tick_native_selection():
    try:
        _tick_native_selection()
    except Exception as exception:
        _log_runtime_error("suivi sélection héros", exception)


def main():
    _safe_tick_native_selection()

    if PyImGui.begin(MODULE_NAME, PyImGui.WindowFlags.AlwaysAutoResize):
        if PyImGui.button("Sélectionner héro 1", width=180, height=28):
            _safe_select_hero_one()

        PyImGui.text(_last_status)

    PyImGui.end()
