"""Phase-16 acceptance coverage: each realistic fixture in
tests/fixtures/screenplays.py is run through the parser (and, for the
re-import fixtures, the full service-layer create -> diff -> approve
flow) and checked against the specific reliability invariant its scenario
name promises. This is deliberately at a coarser grain than
tests/test_screenplay_parser.py's per-behavior unit tests — the point
here is proving those behaviors hold together over full, natural-reading
screenplay excerpts, not re-deriving them from scratch.
"""

import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import projects, scenes as scene_repo
from app.services import screenplay_import_service as import_service
from app.services.screenplay_parser import parse_screenplay

from tests.fixtures import screenplays as fx


class HebrewScreenplayTests(unittest.TestCase):
    def test_scenes_characters_and_locations_are_correctly_structured(self):
        result = parse_screenplay(fx.HEBREW_SCREENPLAY)
        self.assertEqual([s.scene_number for s in result.scenes], [1, 2, 3])
        self.assertEqual(result.scenes[0].int_ext, "פנים")
        self.assertEqual(result.scenes[0].location, "דירה של נועה")
        self.assertEqual(result.scenes[0].time_of_day, "יום")
        self.assertEqual(result.scenes[1].int_ext, "חוץ")
        character_names = sorted(c.canonical_name for c in result.characters)
        self.assertEqual(character_names, ["אורי", "השוטרת", "נועה"])
        # נועה speaks in all three scenes — one character, not three.
        noa = next(c for c in result.characters if c.canonical_name == "נועה")
        self.assertEqual(noa.first_appearance_scene_number, 1)


class EnglishScreenplayTests(unittest.TestCase):
    def test_scenes_characters_and_locations_are_correctly_structured(self):
        result = parse_screenplay(fx.ENGLISH_SCREENPLAY)
        self.assertEqual([s.scene_number for s in result.scenes], [1, 2, 3])
        self.assertEqual(result.scenes[0].normalized_heading, "INT. COFFEE SHOP - MORNING")
        self.assertEqual(result.scenes[2].location, "RACHEL'S OFFICE")
        character_names = sorted(c.canonical_name for c in result.characters)
        self.assertEqual(character_names, ["DANIEL", "MARK", "RACHEL"])
        rachel = next(c for c in result.characters if c.canonical_name == "RACHEL")
        self.assertEqual(rachel.first_appearance_scene_number, 1)


class MixedLanguageScreenplayTests(unittest.TestCase):
    def test_scene_order_is_preserved_across_the_language_boundary(self):
        result = parse_screenplay(fx.MIXED_LANGUAGE_SCREENPLAY)
        self.assertEqual(len(result.scenes), 2)
        self.assertEqual(result.scenes[0].int_ext, "פנים")
        self.assertEqual(result.scenes[1].int_ext, "INT")

    def test_hebrew_and_english_spellings_of_the_same_person_are_not_guessed_to_be_the_same_entity(self):
        # מאיה (scene 1) and MAYA (scene 2) are, to a human reader, the same
        # character — but they are different strings in different scripts,
        # and the parser never guesses across that gap. Getting this
        # "wrong" here is the point: it proves nothing is silently merged
        # without an exact normalized match.
        result = parse_screenplay(fx.MIXED_LANGUAGE_SCREENPLAY)
        names = {c.canonical_name for c in result.characters}
        self.assertIn("מאיה", names)
        self.assertIn("MAYA", names)


class NumberedScenesScreenplayTests(unittest.TestCase):
    def test_source_numbering_is_preserved_verbatim_while_internal_numbering_is_sequential(self):
        result = parse_screenplay(fx.NUMBERED_SCENES_SCREENPLAY)
        self.assertEqual([s.scene_number for s in result.scenes], [1, 2, 3])
        self.assertTrue(result.scenes[0].original_heading.startswith("14."))
        self.assertTrue(result.scenes[1].original_heading.startswith("15."))
        self.assertTrue(result.scenes[2].original_heading.startswith("16."))


class UnnumberedScenesScreenplayTests(unittest.TestCase):
    def test_scenes_detected_without_any_leading_numbers(self):
        result = parse_screenplay(fx.UNNUMBERED_SCENES_SCREENPLAY)
        self.assertEqual([s.scene_number for s in result.scenes], [1, 2])
        self.assertFalse(result.scenes[0].original_heading[0].isdigit())
        self.assertFalse(result.scenes[1].original_heading[0].isdigit())


class DialogueHeavyScreenplayTests(unittest.TestCase):
    def test_every_exchange_is_attributed_to_the_correct_speaker_in_order(self):
        result = parse_screenplay(fx.DIALOGUE_HEAVY_SCREENPLAY)
        dialogue_blocks = [b for b in result.scenes[0].blocks if b.block_type == "dialogue"]
        speakers = [b.character_name for b in dialogue_blocks]
        self.assertEqual(
            speakers,
            ["SAM", "TOVA", "SAM", "TOVA", "SAM", "TOVA", "SAM", "TOVA"],
        )
        self.assertEqual(dialogue_blocks[2].parenthetical, "(raising his voice)")
        self.assertEqual(dialogue_blocks[3].parenthetical, "(calmly)")


class ActionHeavyScreenplayTests(unittest.TestCase):
    def test_long_action_paragraph_stays_one_block_and_is_never_misread_as_dialogue(self):
        result = parse_screenplay(fx.ACTION_HEAVY_SCREENPLAY)
        blocks = result.scenes[0].blocks
        action_blocks = [b for b in blocks if b.block_type == "action"]
        dialogue_blocks = [b for b in blocks if b.block_type == "dialogue"]
        self.assertEqual(len(action_blocks), 1)
        self.assertIn("Mist clings to the rocks", action_blocks[0].raw_text)
        self.assertEqual(len(dialogue_blocks), 1)
        self.assertEqual(dialogue_blocks[0].character_name, "NOA")


class AliasVariantsScreenplayTests(unittest.TestCase):
    def test_annotation_variant_merges_but_similar_different_character_does_not(self):
        result = parse_screenplay(fx.ALIAS_VARIANTS_SCREENPLAY)
        names = sorted(c.canonical_name for c in result.characters)
        self.assertEqual(names, ["DANA", "DAVID"])
        david = next(c for c in result.characters if c.canonical_name == "DAVID")
        self.assertEqual(david.first_appearance_scene_number, 1)
        # DAVID speaks (with the O.S. annotation) in scene 2 too — proving
        # the annotation variant folded into the same entity rather than
        # creating a second "DAVID (O.S.)" character.
        david_scenes = {
            scene.scene_number
            for scene in result.scenes
            if "DAVID" in scene.participants
        }
        self.assertEqual(david_scenes, {1, 2, 3})


class LocationVariantsScreenplayTests(unittest.TestCase):
    def test_whitespace_and_case_variants_merge_but_sub_location_stays_distinct(self):
        result = parse_screenplay(fx.LOCATION_VARIANTS_SCREENPLAY)
        location_names = sorted(loc.canonical_name for loc in result.locations)
        self.assertEqual(location_names, ["CAR", "HOUSE - KITCHEN", "KITCHEN"])
        kitchen = next(loc for loc in result.locations if loc.canonical_name == "KITCHEN")
        self.assertEqual(kitchen.first_appearance_scene_number, 1)

    def test_combined_int_ext_form_is_canonicalized(self):
        result = parse_screenplay(fx.LOCATION_VARIANTS_SCREENPLAY)
        self.assertEqual(result.scenes[3].int_ext, "INT/EXT")


class MalformedButRecoverableScreenplayTests(unittest.TestCase):
    def test_pagination_noise_and_irregular_separators_do_not_break_scene_detection(self):
        result = parse_screenplay(fx.MALFORMED_BUT_RECOVERABLE_SCREENPLAY)
        self.assertEqual(len(result.scenes), 3)
        self.assertEqual([s.scene_number for s in result.scenes], [1, 2, 3])
        self.assertEqual(result.scenes[0].location, "office")
        self.assertEqual(result.scenes[0].time_of_day, "day")
        # Scene 3 has no dash separating location from time — recovered as
        # a single scene boundary with the whole remainder folded into
        # location rather than dropped or merged into scene 2.
        self.assertIn("HALLWAY", result.scenes[2].location.upper())

    def test_no_scene_content_from_the_source_is_lost(self):
        result = parse_screenplay(fx.MALFORMED_BUT_RECOVERABLE_SCREENPLAY)
        all_text = " ".join(
            block.raw_text for scene in result.scenes for block in scene.blocks
        )
        self.assertIn("Almost done.", all_text)
        self.assertIn("Rain streaks the windshield.", all_text)
        self.assertIn("checking her watch.", all_text)


class ReimportFixturesServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        self.project = projects.create_project(
            {"name": "Fixture Reimport", "description": "", "visual_style": "", "rules": ""}
        )

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()


class ReimportSameFixtureTests(ReimportFixturesServiceTestCase):
    def test_reimporting_the_exact_same_realistic_screenplay_is_idempotent(self):
        first = import_service.create_import_run(self.project["id"], fx.REIMPORT_BASE_SCREENPLAY)
        import_service.approve_import_run(first["id"])
        before = scene_repo.list_scenes(self.project["id"])

        second = import_service.create_import_run(self.project["id"], fx.REIMPORT_BASE_SCREENPLAY)

        self.assertEqual(second["duplicate_of_import_run_id"], first["id"])
        after = scene_repo.list_scenes(self.project["id"])
        self.assertEqual([s["id"] for s in before], [s["id"] for s in after])
        self.assertEqual(len(after), 3)


class ReimportChangedFixtureTests(ReimportFixturesServiceTestCase):
    def test_reimporting_a_changed_realistic_screenplay_requires_confirmation_then_applies_atomically(self):
        first = import_service.create_import_run(self.project["id"], fx.REIMPORT_BASE_SCREENPLAY)
        import_service.approve_import_run(first["id"])
        original_scene_ids = {s["scene_number"]: s["id"] for s in scene_repo.list_scenes(self.project["id"])}

        second = import_service.create_import_run(self.project["id"], fx.REIMPORT_CHANGED_SCREENPLAY)
        diff = import_service.preview_diff(second["id"])
        self.assertEqual(len(diff["added"]), 1)
        self.assertEqual(len(diff["changed"]), 1)
        self.assertEqual(len(diff["unchanged"]), 2)
        self.assertEqual(len(diff["removed"]), 0)
        self.assertTrue(diff["requires_confirmation"])

        with self.assertRaises(import_service.ImportRunConflict):
            import_service.approve_import_run(second["id"], confirm=False)

        summary = import_service.approve_import_run(second["id"], confirm=True)
        self.assertEqual(summary["scenes_added"], 1)
        self.assertEqual(summary["scenes_changed"], 1)
        self.assertEqual(summary["scenes_unchanged"], 2)

        after_scenes = scene_repo.list_scenes(self.project["id"])
        self.assertEqual(len(after_scenes), 4)
        after_ids = {s["scene_number"]: s["id"] for s in after_scenes}
        # Scenes 1-3 keep their original database ids — any downstream shot
        # work on them would have survived this re-import untouched.
        for scene_number in (1, 2, 3):
            self.assertEqual(after_ids[scene_number], original_scene_ids[scene_number])
        # Scene 1's content genuinely changed on disk (verified via its
        # updated action text), even though its id was preserved.
        scene_1 = next(s for s in after_scenes if s["scene_number"] == 1)
        self.assertIn("visibly worried", scene_1["raw_scene_text"])


if __name__ == "__main__":
    unittest.main()
