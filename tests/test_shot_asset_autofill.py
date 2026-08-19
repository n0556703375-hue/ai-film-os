"""Coverage for app.services.shot_asset_autofill.suggest_shot_asset_ids —
pure name-matching between a shot's free-text fields and project assets."""

import unittest

from app.services.shot_asset_autofill import suggest_shot_asset_ids

_ASSETS = [
    {"id": 1, "name": "יעל", "asset_type": "דמות"},
    {"id": 2, "name": "מטבח הבית", "asset_type": "לוקיישן"},
    {"id": 3, "name": "סכין", "asset_type": "אביזר"},
    {"id": 4, "name": "אור", "asset_type": "אביזר"},  # short, common word
]


class SuggestShotAssetIdsTests(unittest.TestCase):
    def test_matches_name_in_action_field(self):
        shot = {"action": "יעל נכנסת למטבח הבית ומרימה סכין."}
        self.assertEqual(sorted(suggest_shot_asset_ids(shot, _ASSETS)), [1, 2, 3])

    def test_no_matches_returns_empty(self):
        shot = {"action": "רחוב ריק בלילה."}
        self.assertEqual(suggest_shot_asset_ids(shot, _ASSETS), [])

    def test_empty_shot_text_returns_empty(self):
        shot = {"action": "", "dialogue": None}
        self.assertEqual(suggest_shot_asset_ids(shot, _ASSETS), [])

    def test_matches_across_multiple_fields(self):
        shot = {"action": "יעל עומדת בשקט.", "dialogue": "", "notes": "יש להשתמש בסכין."}
        self.assertEqual(sorted(suggest_shot_asset_ids(shot, _ASSETS)), [1, 3])

    def test_word_boundary_avoids_partial_match(self):
        assets = [{"id": 5, "name": "אור", "asset_type": "אביזר"}]
        shot = {"action": "אורית נכנסת לחדר."}
        self.assertEqual(suggest_shot_asset_ids(shot, assets), [])

    def test_exact_short_word_still_matches_with_boundaries(self):
        assets = [{"id": 5, "name": "אור", "asset_type": "אביזר"}]
        shot = {"action": "יש להדליק את האור בחדר."}
        self.assertEqual(suggest_shot_asset_ids(shot, assets), [5])


if __name__ == "__main__":
    unittest.main()
