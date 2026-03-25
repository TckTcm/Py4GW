import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLBAR_MODULE_PATH = REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "Skillbar.py"
SKILLBAR_CACHE_MODULE_PATH = REPO_ROOT / "Py4GW_python" / "Py4GWCoreLib" / "GlobalCache" / "SkillbarCache.py"


class _FakeActionQueueManager:
    def AddAction(self, *_args, **_kwargs):
        return None

    def AddActionWithDelay(self, *_args, **_kwargs):
        return None


class _FailingSkillbarInstance:
    def GetSkill(self, _slot):
        raise RuntimeError("skillbar unavailable")


class _FakePySkillbar(types.ModuleType):
    def __init__(self):
        super().__init__("PySkillbar")
        self.Skillbar = _FailingSkillbarInstance


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SkillbarSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules["PyAgent"] = types.SimpleNamespace(AttributeClass=object)
        sys.modules["PySkillbar"] = _FakePySkillbar()
        sys.modules["Py4GWCoreLib.py4gwcorelib_src.Utils"] = types.SimpleNamespace(Utils=object)
        sys.modules["Py4GWCoreLib.Py4GWcorelib"] = types.SimpleNamespace(ActionQueueManager=_FakeActionQueueManager)
        cls.skillbar_module = _load_module("skillbar_under_test", SKILLBAR_MODULE_PATH)
        cls.skillbar_cache_module = _load_module("skillbar_cache_under_test", SKILLBAR_CACHE_MODULE_PATH)

    def test_skillbar_get_skill_id_by_slot_returns_zero_when_native_skill_read_fails(self):
        self.assertEqual(0, self.skillbar_module.SkillBar.GetSkillIDBySlot(8))

    def test_skillbar_cache_get_skill_id_by_slot_returns_zero_when_native_skill_read_fails(self):
        cache = self.skillbar_cache_module.SkillbarCache(_FakeActionQueueManager())
        self.assertEqual(0, cache.GetSkillIDBySlot(8))


if __name__ == "__main__":
    unittest.main()
