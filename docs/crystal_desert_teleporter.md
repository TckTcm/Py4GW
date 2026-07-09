# Crystal Desert Teleporter Widget

The Crystal Desert teleporter widget helps solve the random four-switch teleporter sequences used by the Crystal Desert teleporter platforms.

The sequence is not a fixed mapping. The game generates a new live sequence, and the widget learns it from server packets during the current attempt.

## Requirements

- Py4GW must be injected with a `Py4GW.dll` that includes the StoC packet sniffer payload-size fix.
- The widget must be loaded from `Widgets/Guild Wars/Crystal Desert Teleporter.py`.
- The character must be near the four visible `Teleporter Switch` gadgets for the current platform.

## Basic Usage

1. Stand near the four teleporter switches for the platform you want to use.
2. Click `Scan switches`.
3. Click `Scan + Record`.
4. Trigger the platform sequence in game.
5. Wait for the widget to display a `Sequence:` such as `19 -> 20 -> 18 -> 21`.
6. Use `Click next` to click one switch at a time, or enable `Auto click`.
7. After the last switch is clicked, wait a few seconds for server confirmation packets.
8. Step onto the teleporter platform when the widget shows `Server confirmed sequence. Step onto the platform.`

The final wait is important. The client click is not the proof that the switch sequence was accepted. The server sends delayed `0x0115` gadget-state packets after the interactions, and those packets confirm the actual order.

## Controls

- `Scan switches`: selects the nearest four `Teleporter Switch` gadgets.
- `Scan + Record`: scans switches and starts packet capture.
- `Record` / `Stop`: starts or stops packet capture without rescanning.
- `Reset`: clears the current capture state.
- `Click next`: clicks the next switch in the learned sequence.
- `Auto click`: repeatedly clicks the next expected switch when the character is in range.
- `Learn clicks`: records a manual click order for the current platform burst.
- `Add selected`, `Add`, `Set #1` through `Set #4`: manual calibration helpers when the live packet stream does not produce enough data.
- `Forget learned`: clears trusted manual mappings for the current widget session.

## Packet Signals

The widget uses several packet families:

- `StoC 0x0020 WORLD_CREATE_AGENT`: captures the random platform marker burst. This identifies the platform-side visual sequence, not always the switch order by itself.
- `StoC 0x0115 GADGET_STATE`: carries `agent_id` and `state`. This is the important delayed server confirmation used to learn the real switch order.
- `CToS 0x0039`: confirms that the client attempted to interact with a switch when available.
- `CToS 0x00C1` with first word `48`: means the sequence reset and the widget should restart at the first switch.
- Plain `CToS 0x00C1` targeting packets are not treated as sequence proof because they can be emitted by selection only.

## Expected Widget State

A successful run usually looks like this:

```text
Sequence: 19 -> 20 -> 18 -> 21
Next: <done>
Status: Server confirmed sequence. Step onto the platform.
Recent sequence events:
0x0115 agent=19 state=0x3 ...
0x0115 agent=20 state=0x3 ...
0x0115 agent=18 state=0x3 ...
0x0115 agent=21 state=0x3 ...
```

When `Next: <done>` is visible and the server-confirmed status is shown, the sequence has been completed correctly. `Next: <done>` alone only means the widget has queued or clicked the full plan; it can still be waiting for delayed server confirmation.

## Troubleshooting

If the widget does not learn a sequence:

- Make sure `Build:` shows the latest widget build.
- Use `Scan + Record` before triggering the platform.
- Wait a few seconds after the last switch interaction; server confirmations are delayed.
- Check `Recent sequence events` for `0x0115 agent=... state=...` lines.
- If `First raw StoC after burst` shows truncated packets or missing words, reinject the updated `Py4GW.dll`.
- If only `CToS 0x00C1` appears, that may be selection noise and is not enough to prove a switch activation.

## Implementation Notes

The native StoC sniffer must copy full packet payloads. Guild Wars' StoC handler metadata stores a packet field template and field count, not a raw byte size. The C++ sniffer measures packet size from that template before copying payload bytes. Without that fix, packets such as `0x0115` can appear truncated and the widget cannot read `agent_id` and `state`.
