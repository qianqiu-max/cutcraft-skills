import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build
from new_skill import scaffold


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "skills").mkdir()
        (self.root / "site").mkdir()
        self.patch = patch.object(build, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def publish_fixture(self, slug):
        skill = scaffold(self.root, slug, "测试效果", "转场", "FFmpeg")
        meta_path = skill / "showcase.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.update(draft=False, summary="两段素材叠化", inputs=["两段素材"], prompt="使用附件生成转场。")
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        for name in ("demo.mp4", "poster.webp"):
            (skill / "previews" / name).write_bytes(b"fixture")
        (skill / "scripts").mkdir()
        (skill / "scripts" / "effect.py").write_text("print('test')", encoding="utf-8")
        return skill

    def test_new_effect_enters_catalog_prompt_and_installable_packages(self):
        scaffold(self.root, "draft", "待验证", "合成", "Blender")
        self.publish_fixture("cut-test")
        stage = self.root / "result"
        build.generate(stage)
        items = json.loads((stage / "catalog.json").read_text(encoding="utf-8"))["skills"]
        self.assertEqual([s["id"] for s in items], ["cut-test"])
        self.assertIn("/downloads/cut-test.zip", items[0]["prompt"])
        self.assertIn("main/skills/cut-test/SKILL.md", items[0]["prompt"])
        self.assertIn("使用附件生成转场。", items[0]["prompt"])
        for archive in ("cut-test.zip", "cutcraft-skills.zip"):
            with ZipFile(stage / "downloads" / archive) as z:
                self.assertIn("cut-test/scripts/effect.py", z.namelist())
                self.assertIn("cut-test/SKILL.md", z.namelist())
                self.assertFalse(any("previews" in s or "draft/" in s for s in z.namelist()))
        self.assertTrue((stage / items[0]["video"]).is_file())

    def test_published_skill_requires_preview_and_matching_name(self):
        skill = self.publish_fixture("cut-test")
        (skill / "previews" / "demo.mp4").unlink()
        with self.assertRaisesRegex(ValueError, "missing public preview"):
            build.read_skill(skill)
        (skill / "SKILL.md").write_text("---\nname: other\ndescription: Test\n---\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "folder name"):
            build.read_skill(skill)

    def test_scaffold_refuses_overwrite_and_invalid_name(self):
        scaffold(self.root, "my-effect", "测试", "转场", "本机")
        with self.assertRaises(FileExistsError):
            scaffold(self.root, "my-effect", "另一个", "转场", "本机")
        with self.assertRaises(ValueError):
            scaffold(self.root, "../elsewhere", "测试", "转场", "本机")
