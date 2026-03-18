# Py4GW

**Py4GW** is a Python library designed to enhance the Guild Wars experience by providing tools for automation, scripting, and in-game interactions.

---

## Directory Structure

```text
Py4GW_python/
|-- Addons/                     # Add-on extensions (e.g., GWBlackBOX.dll)
|-- DEMO/                       # Example scripts demonstrating library usage
|-- HeroAI/                     # Hero AI automation and logic
|-- Py4GWCoreLib/               # Core library for Guild Wars automation
|-- Widgets/                    # Widgets for in-game interactions
|-- resources/                  # Fonts, configs, and other resources
|-- stubs/                      # Type hint files for Python development
|-- build/                      # Build directory
|-- dist/                       # Distribution directory
|-- Legacy code and tests/      # Archived code and test scripts
|-- Working Miscelaneous code/  # Experimental or temporary scripts
|-- Py4GW.dll                   # Main DLL for the project
|-- Py4GW.ini                   # Configuration file
|-- Py4GW_Launcher.py           # Launcher script
|-- Barebones_Example_module.py # Minimal example script
`-- requirements.txt            # Dependencies
```

---

## How to Download

1. Go to the [Releases Page](https://github.com/apoguita/Py4GW/releases/tag/Official).
2. Download the files under "Assets."
3. Extract them to your preferred directory.

---

## Contributing

We welcome contributions from the community! Here's how you can get involved:

1. Fork the repository.
2. Create a new branch for your feature or bugfix.
3. Commit your changes and push the branch.
4. Submit a pull request for review.

### Stop Tracking Log/Configuration Files

If you want to stop tracking local changes to the log and configuration files used by Py4GW, you can use the following commands to temporarily remove them from the worktree.

```bash
git update-index --skip-worktree Py4GW_injection_log.txt
git update-index --skip-worktree Py4GW.ini
git update-index --skip-worktree Py4GW_Launcher.ini
```

You can then verify that the files are correctly skipped by running this command, which should output the list of skipped files:

```bash
git ls-files -v | grep "^S"
S Py4GW.ini
S Py4GW_Launcher.ini
S Py4GW_injection_log.txt
```

To re-enable local tracking of the files, run the following commands:

```bash
git update-index --no-skip-worktree Py4GW_injection_log.txt
git update-index --no-skip-worktree Py4GW.ini
git update-index --no-skip-worktree Py4GW_Launcher.ini
```
