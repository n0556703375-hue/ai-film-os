import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SceneAssemblyUiTests(unittest.TestCase):
    def test_scene_assembly_script_loads_after_workspace_overrides(self):
        html = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")

        self.assertIn('/static/scene-assembly-ui.js', html)
        self.assertLess(html.index('/static/continuity-ui.js'), html.index('/static/scene-assembly-ui.js'))

    def test_scene_assembly_uses_read_only_preview_manifest(self):
        script = (ROOT / "app" / "static" / "scene-assembly-ui.js").read_text(encoding="utf-8")

        self.assertIn('/api/scenes/${sceneId}/preview-manifest', script)
        self.assertIn('data-scene-assembly-timeline', script)
        self.assertIn('ready_for_preview', script)
        self.assertIn('missing_video_shot_ids', script)
        self.assertNotIn('method: "POST"', script)
        self.assertNotIn('method: "PATCH"', script)
        self.assertNotIn('method: "DELETE"', script)

    def test_scene_assembly_surfaces_media_audio_and_dialogue(self):
        script = (ROOT / "app" / "static" / "scene-assembly-ui.js").read_text(encoding="utf-8")

        self.assertIn('<video', script)
        self.assertIn('image_url', script)
        self.assertIn('has_dialogue', script)
        self.assertIn('has_audio_notes', script)
        self.assertIn('openShot(', script)


if __name__ == "__main__":
    unittest.main()
