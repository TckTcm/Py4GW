import Py4GW

def EscapeFakeChatLiteralBrackets(text) -> str:
    escaped = []
    for char in str(text):
        if char == "[":
            escaped.append("[lbracket]")
        elif char == "]":
            escaped.append("[rbracket]")
        else:
            escaped.append(char)
    return "".join(escaped)

def _sanitize_console_args(sender, message):
    return (
        EscapeFakeChatLiteralBrackets(sender),
        EscapeFakeChatLiteralBrackets(message),
    )

def install_console_log_escape():
    current_log = Py4GW.Console.Log
    if getattr(current_log, "_py4gw_python_bracket_escape", False):
        return current_log

    native_log = getattr(Py4GW.Console, "_py4gw_python_native_log", current_log)

    def wrapped_log(sender, message, message_type=Py4GW.Console.MessageType.Info):
        safe_sender, safe_message = _sanitize_console_args(sender, message)
        return native_log(safe_sender, safe_message, message_type)

    wrapped_log._py4gw_python_bracket_escape = True
    Py4GW.Console._py4gw_python_native_log = native_log
    Py4GW.Console.Log = wrapped_log
    return wrapped_log

@staticmethod
def ConsoleLog(sender, message, message_type:int=0 , log: bool = True):
    """Logs a message with an optional message type."""
    if log:
        if message_type == 0:
            Py4GW.Console.Log(sender, message, Py4GW.Console.MessageType.Info)
        elif message_type == 1:
            Py4GW.Console.Log(sender, message, Py4GW.Console.MessageType.Warning)
        elif message_type == 2:
            Py4GW.Console.Log(sender, message, Py4GW.Console.MessageType.Error)
        elif message_type == 3:
            Py4GW.Console.Log(sender, message, Py4GW.Console.MessageType.Debug)
        elif message_type == 4:
            Py4GW.Console.Log(sender, message, Py4GW.Console.MessageType.Success)
        elif message_type == 5:
            Py4GW.Console.Log(sender, message, Py4GW.Console.MessageType.Performance)
        elif message_type == 6:
            Py4GW.Console.Log(sender, message, Py4GW.Console.MessageType.Notice)
        else:
            Py4GW.Console.Log(sender, message, Py4GW.Console.MessageType.Info)

install_console_log_escape()
Console = Py4GW.Console
