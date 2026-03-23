# AGENTS.md - Py4GW_python

## Scope
These instructions apply to everything under `Py4GW_python/`.

## Mission
Build Py4GW widgets and bots that are stable, Pythonic, and aligned with current Py4GW 2.0 conventions.

## Companion Reference (Required)
- Before implementing or refactoring any bot script, read `BOT_REFERENCE.md`.
- Treat `BOT_REFERENCE.md` as practical implementation guidance and examples.
- Treat this `AGENTS.md` as policy and final authority.
- If `BOT_REFERENCE.md` conflicts with `AGENTS.md`, follow `AGENTS.md`.

## Reference Priority (Mandatory)
When creating or refactoring a bot/widget, use references in this exact order:

1. `Widgets/Automation/Bots/Farmers/Events/YAVB 2.0.py`  
   Primary canonical template for Botting + FSM/coroutine architecture.
2. `Widgets/Automation/Bots/Levelers/Factions/Factions Character Leveler.py`  
   Secondary template for large multi-step pipelines and advanced UI overrides.
3. `Widgets/Automation/Bots/Farmers/Weapons/Green_Unique/Axe/Totem Axe.py`  
   `Widgets/Automation/Bots/Vanquish/Factions/Echovald Forest/Ferndale.py`  
   `Widgets/Automation/Bots/Vanquish/Factions/Echovald Forest/Morostav Trail.py`  
   Route-farm and recovery references.
4. `Widgets/Automation/Multiboxing/HeroAI.py`  
   Specialized behavior-tree/multibox architecture reference only; not a base template for normal bots.
5. `Py4GWCoreLib/UIManager.py`  
   Library/API reference only; do not use as structural template for bot scripts.

If references conflict, follow the higher-priority file.

## Required Architecture
- Use `Botting(...)` as the controller.
- Define a main routine and register with `bot.SetMainRoutine(...)`.
- Build flow through states and coroutines (`bot.States.*`, `yield from Routines.Yield.*`).
- Keep widget entrypoint as:
  - `bot.Update()`
  - `bot.UI.draw_window(...)`
- Use optional `configure()`/`tooltip()` as needed.

## Required Coding Style
- Prefer explicit imports; avoid wildcard imports in production scripts.
- Put constants at module top.
- Keep functions focused and deterministic.
- Use Py4GW wrappers (`Routines.Yield.*`, `Player`, `Agent`, `Map`, `Inventory`) rather than ad-hoc low-level logic.
- Prefer `Player.SendChatCommand(...)` (or `Routines.Yield.Player.SendChatCommand(...)`) for slash commands.
- Add timeout/deadlock guards for polling loops.

## Forbidden Patterns
- No AutoIt constructs (`MsgBox`, `Exit`, AutoIt-style API names).
- No disable/enable rendering semantics.
- No memory limiter semantics.
- No hide/show client semantics.
- No direct packet-injection logic in widget scripts.

## Migration Rules (AutoIt -> Py4GW)
- Preserve game logic and timing windows exactly unless explicitly instructed otherwise.
- Preserve decision logic exactly (e.g., animation-to-command mappings).
- Replace sleeps/actions with Py4GW coroutine equivalents.
- Add guard checks for map readiness, target validity, item availability, and timeout exit paths.

## Validation Checklist
For every edited Python file:
1. Syntax check:
   - `python -m py_compile <file.py>`
2. Sanity grep for forbidden terms:
   - `rg -n "MsgBox|DisableRendering|EnableRendering|hide client|memory limit" Widgets`
3. Confirm main loop uses `bot.Update()` and `bot.UI.draw_window(...)`.

## Placement Rules
- Event bots: keep in the established event folder that matches the script category, typically `Widgets/Automation/Bots/Events/` or `Widgets/Automation/Bots/Farmers/Events/`
- Farmers/Levelers/Vanquish: keep in their existing category folders.
- Multibox tools: `Widgets/Automation/Multiboxing/`
- Config outputs: `Widgets/Config/`
- Persistent data: `Widgets/Data/`
- Do not place production bots under `Examples/`.

## Collaboration Constraints
- Never revert unrelated user changes.
- Keep edits minimal and scoped to the request.
- Prefer consistency with the reference priority over personal style choices.
- Before asserting that a revert, restore, removal, or rename succeeded, verify the current file state directly from disk and/or git state in the same turn.
- If a file is untracked or not present in git history, verify against the live file on disk rather than assuming git can confirm it.
- Do not rely on memory for revert status; re-check the actual file contents or `git status`/`git diff` output before reporting completion.
