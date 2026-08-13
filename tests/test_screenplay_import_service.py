"""Coverage for the two-stage screenplay import orchestration service:
parse/preview (no production writes), diffing against existing scenes, and
the atomic approve/commit step — including the safety invariants a naive
re-import easily gets wrong (duplicate billing has no analog here, but
duplicate/destroyed production data is the equivalent risk).
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import settings
from app.database.connection import init_db
from app.repositories import assets as assets_repo
from app.repositories import projects, scenes as scene_repo, screenplay_structure, shots as shot_repo
from app.repositories import import_runs as import_runs_repo
from app.services import screenplay_import_service as svc

_SIMPLE_V1 = "1. INT. HOUSE - DAY\n\nJOHN\nHi there.\n"
_TWO_SCENES = (
    "1. INT. HOUSE - DAY\n\nJOHN\nHi there.\n\n"
    "2. EXT. YARD - NIGHT\n\nMARY\nHello John.\n"
)
_SCENE_WITH_PROP = (
    "1. INT. HOUSE - DAY\n\nHe picks up the \"letter\" and reads it.\n\nJOHN\nHi there.\n"
)


class ScreenplayImportServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = settings.database_path
        settings.database_path = Path(self.tempdir.name) / "test.db"
        init_db()
        self.project = projects.create_project(
            {"name": "Import", "description": "", "visual_style": "", "rules": ""}
        )

    def tearDown(self):
        settings.database_path = self.original_db
        self.tempdir.cleanup()


class CreateImportRunTests(ScreenplayImportServiceTestCase):
    def test_create_parses_and_returns_review_required_run(self):
        run = svc.create_import_run(self.project["id"], _TWO_SCENES)
        self.assertEqual(run["status"], "review_required")
        self.assertEqual(run["scene_count"], 2)
        self.assertEqual(run["character_count"], 2)
        # No production writes happened yet.
        self.assertEqual(scene_repo.list_scenes(self.project["id"]), [])

    def test_empty_screenplay_raises_stable_category(self):
        with self.assertRaises(svc.ScreenplayImportError) as ctx:
            svc.create_import_run(self.project["id"], "   ")
        self.assertEqual(ctx.exception.category, "empty_script")

    def test_identical_approved_screenplay_is_idempotent(self):
        first = svc.create_import_run(self.project["id"], _SIMPLE_V1)
        svc.approve_import_run(first["id"])

        second = svc.create_import_run(self.project["id"], _SIMPLE_V1)

        self.assertEqual(second["duplicate_of_import_run_id"], first["id"])
        self.assertEqual(len(import_runs_repo.list_import_runs(self.project["id"])), 1)

    def test_identical_but_not_yet_approved_screenplay_creates_a_fresh_preview(self):
        # Idempotency is scoped to *approved* imports only — a still-pending
        # review shouldn't block re-submitting the same text for review.
        first = svc.create_import_run(self.project["id"], _SIMPLE_V1)
        second = svc.create_import_run(self.project["id"], _SIMPLE_V1)
        self.assertNotIn("duplicate_of_import_run_id", second)
        self.assertNotEqual(first["id"], second["id"])

    def test_force_bypasses_the_duplicate_shortcut_for_already_approved_text(self):
        # The escape hatch for re-checking already-approved text against a
        # newer parser version: without force, identical text to an
        # approved run always short-circuits (previous test); force skips
        # that and produces a real fresh preview instead.
        first = svc.create_import_run(self.project["id"], _SIMPLE_V1)
        svc.approve_import_run(first["id"])

        forced = svc.create_import_run(self.project["id"], _SIMPLE_V1, force=True)

        self.assertNotIn("duplicate_of_import_run_id", forced)
        self.assertNotEqual(forced["id"], first["id"])
        self.assertEqual(forced["status"], "review_required")
        self.assertEqual(len(import_runs_repo.list_import_runs(self.project["id"])), 2)


class ReparseTests(ScreenplayImportServiceTestCase):
    def test_reparse_updates_the_same_run_in_place(self):
        run = svc.create_import_run(self.project["id"], _SIMPLE_V1)
        updated = svc.reparse_import_run(run["id"], _TWO_SCENES)
        self.assertEqual(updated["id"], run["id"])
        self.assertEqual(updated["scene_count"], 2)
        self.assertEqual(updated["status"], "review_required")

    def test_reparse_after_approval_is_rejected(self):
        run = svc.create_import_run(self.project["id"], _SIMPLE_V1)
        svc.approve_import_run(run["id"])
        with self.assertRaises(svc.ImportRunNotEditable):
            svc.reparse_import_run(run["id"], _TWO_SCENES)


class ApproveFirstImportTests(ScreenplayImportServiceTestCase):
    def test_approve_persists_scenes_characters_locations_and_blocks(self):
        run = svc.create_import_run(self.project["id"], _TWO_SCENES)
        result = svc.approve_import_run(run["id"])

        self.assertEqual(result["scenes_added"], 2)
        scenes = scene_repo.list_scenes(self.project["id"])
        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[0]["normalized_heading"], "INT. HOUSE - DAY")
        self.assertEqual(scenes[0]["raw_scene_text"][:1], "1")  # original heading preserved verbatim

        characters = screenplay_structure.list_screenplay_characters(self.project["id"])
        self.assertEqual(sorted(c["canonical_name"] for c in characters), ["JOHN", "MARY"])

        blocks = screenplay_structure.list_scene_content_blocks(scenes[0]["id"])
        self.assertEqual(blocks[0]["block_type"], "dialogue")
        self.assertEqual(blocks[0]["character_name"], "JOHN")

    def test_approve_marks_run_approved(self):
        run = svc.create_import_run(self.project["id"], _SIMPLE_V1)
        svc.approve_import_run(run["id"])
        refreshed = import_runs_repo.get_import_run(run["id"])
        self.assertEqual(refreshed["status"], "approved")
        self.assertIsNotNone(refreshed["approved_at"])

    def test_double_approve_is_rejected(self):
        run = svc.create_import_run(self.project["id"], _SIMPLE_V1)
        svc.approve_import_run(run["id"])
        with self.assertRaises(svc.ImportRunNotEditable):
            svc.approve_import_run(run["id"])

    def test_first_import_never_requires_confirmation(self):
        run = svc.create_import_run(self.project["id"], _TWO_SCENES)
        # Must not raise ImportRunConflict.
        svc.approve_import_run(run["id"], confirm=False)


class StoryBibleSyncTests(ScreenplayImportServiceTestCase):
    """Approving an import must create Story Bible cards for every
    character, location, and prop the breakdown reports — this is the
    fix for the reported bug where locations/accessories never appeared
    in the Story Bible after a script (re-)import even though the
    underlying screenplay-parse tables were populated correctly.
    """

    def test_approve_creates_story_bible_cards_for_all_entity_types(self):
        run = svc.create_import_run(self.project["id"], _SCENE_WITH_PROP)
        svc.approve_import_run(run["id"])

        by_type = {}
        for asset in assets_repo.list_assets(self.project["id"]):
            by_type.setdefault(asset["asset_type"], []).append(asset["name"])

        self.assertEqual(by_type.get("דמות"), ["JOHN"])
        self.assertEqual(by_type.get("לוקיישן"), ["HOUSE"])
        self.assertEqual(by_type.get("אביזר"), ["letter"])

    def test_reimport_does_not_touch_an_already_curated_asset_card(self):
        run = svc.create_import_run(self.project["id"], _SCENE_WITH_PROP)
        svc.approve_import_run(run["id"])

        location_asset = next(
            a for a in assets_repo.list_assets(self.project["id"]) if a["asset_type"] == "לוקיישן"
        )
        assets_repo.update_asset(location_asset["id"], {"description": "תיאור ידני שנכתב על ידי המשתמש"})

        # Re-approving the exact same text (forced re-parse) must not touch
        # the manually-curated card.
        second_run = svc.create_import_run(self.project["id"], _SCENE_WITH_PROP, force=True)
        svc.approve_import_run(second_run["id"])

        refreshed = assets_repo.get_asset(location_asset["id"])
        self.assertEqual(refreshed["description"], "תיאור ידני שנכתב על ידי המשתמש")
        locations = [a for a in assets_repo.list_assets(self.project["id"]) if a["asset_type"] == "לוקיישן"]
        self.assertEqual(len(locations), 1)


class RenameEntityTests(ScreenplayImportServiceTestCase):
    """Manual correction of the parsed character/location/prop list before
    approval — the fix for the reported gap where a mis-parsed entity name
    could only be fixed by editing the raw screenplay text and re-parsing.
    """

    def test_rename_location_updates_breakdown_and_count(self):
        run = svc.create_import_run(self.project["id"], _TWO_SCENES)
        updated = svc.rename_entity(run["id"], "locations", "HOUSE", "MAIN HOUSE")

        names = sorted(loc["canonical_name"] for loc in updated["breakdown"]["locations"])
        self.assertEqual(names, ["MAIN HOUSE", "YARD"])
        self.assertEqual(updated["location_count"], 2)

    def test_rename_character_keeps_old_name_as_alias(self):
        run = svc.create_import_run(self.project["id"], _TWO_SCENES)
        updated = svc.rename_entity(run["id"], "characters", "JOHN", "JOHNATHAN")

        renamed = next(c for c in updated["breakdown"]["characters"] if c["canonical_name"] == "JOHNATHAN")
        self.assertIn("JOHN", renamed["aliases"])

    def test_renamed_character_scene_link_still_resolves_at_approval(self):
        run = svc.create_import_run(self.project["id"], _TWO_SCENES)
        svc.rename_entity(run["id"], "characters", "JOHN", "JOHNATHAN")
        svc.approve_import_run(run["id"])

        characters = screenplay_structure.list_screenplay_characters(self.project["id"])
        self.assertEqual(sorted(c["canonical_name"] for c in characters), ["JOHNATHAN", "MARY"])
        scenes = scene_repo.list_scenes(self.project["id"])
        house_scene = next(s for s in scenes if s["normalized_heading"] == "INT. HOUSE - DAY")
        blocks = screenplay_structure.list_scene_content_blocks(house_scene["id"])
        self.assertEqual(blocks[0]["character_name"], "JOHN")  # raw cue text untouched

    def test_rename_onto_an_existing_name_merges_the_two_entities(self):
        text = (
            "1. INT. HOUSE - DAY\n\nJOHN\nHi.\n\n"
            "2. INT. MANSION - DAY\n\nMARY\nHello.\n"
        )
        run = svc.create_import_run(self.project["id"], text)
        updated = svc.rename_entity(run["id"], "locations", "MANSION", "HOUSE")

        locations = updated["breakdown"]["locations"]
        self.assertEqual([loc["canonical_name"] for loc in locations], ["HOUSE"])
        self.assertIn("MANSION", locations[0]["aliases"])
        self.assertEqual(updated["location_count"], 1)

    def test_rename_unknown_entity_raises(self):
        run = svc.create_import_run(self.project["id"], _TWO_SCENES)
        with self.assertRaises(svc.EntityNotFound):
            svc.rename_entity(run["id"], "locations", "NOWHERE", "SOMEWHERE")

    def test_rename_after_approval_is_rejected(self):
        run = svc.create_import_run(self.project["id"], _TWO_SCENES)
        svc.approve_import_run(run["id"])
        with self.assertRaises(svc.ImportRunNotEditable):
            svc.rename_entity(run["id"], "locations", "HOUSE", "MAIN HOUSE")


class DeleteEntityTests(ScreenplayImportServiceTestCase):
    def test_delete_prop_removes_it_from_breakdown(self):
        run = svc.create_import_run(self.project["id"], _SCENE_WITH_PROP)
        updated = svc.delete_entity(run["id"], "props", "letter")

        self.assertEqual(updated["breakdown"]["props"], [])
        self.assertEqual(updated["prop_count"], 0)

    def test_deleted_character_does_not_block_approval(self):
        run = svc.create_import_run(self.project["id"], _TWO_SCENES)
        svc.delete_entity(run["id"], "characters", "JOHN")
        result = svc.approve_import_run(run["id"])

        self.assertEqual(result["characters_created"], 1)
        characters = screenplay_structure.list_screenplay_characters(self.project["id"])
        self.assertEqual([c["canonical_name"] for c in characters], ["MARY"])

    def test_delete_unknown_entity_raises(self):
        run = svc.create_import_run(self.project["id"], _TWO_SCENES)
        with self.assertRaises(svc.EntityNotFound):
            svc.delete_entity(run["id"], "locations", "NOWHERE")


class ReimportSafetyTests(ScreenplayImportServiceTestCase):
    def _approve(self, text):
        run = svc.create_import_run(self.project["id"], text)
        return svc.approve_import_run(run["id"])

    def test_pure_addition_does_not_require_confirmation(self):
        self._approve(_SIMPLE_V1)
        run2 = svc.create_import_run(self.project["id"], _TWO_SCENES)
        result = svc.approve_import_run(run2["id"])  # no confirm
        self.assertEqual(result["scenes_added"], 1)
        self.assertEqual(result["scenes_unchanged"], 1)

    def test_changing_an_existing_scene_requires_confirmation(self):
        self._approve(_SIMPLE_V1)
        changed_text = "1. INT. HOUSE - DAY\n\nJOHN\nA totally different line.\n"
        run2 = svc.create_import_run(self.project["id"], changed_text)
        with self.assertRaises(svc.ImportRunConflict) as ctx:
            svc.approve_import_run(run2["id"])
        self.assertEqual(ctx.exception.reason, "confirmation_required")
        # Nothing was written.
        scenes = scene_repo.list_scenes(self.project["id"])
        self.assertEqual(scenes[0]["raw_scene_text"], "1. INT. HOUSE - DAY\n\nJOHN\nHi there.")

    def test_confirmed_change_updates_in_place_preserving_scene_id(self):
        self._approve(_SIMPLE_V1)
        scene_id_before = scene_repo.list_scenes(self.project["id"])[0]["id"]
        changed_text = "1. INT. HOUSE - DAY\n\nJOHN\nA totally different line.\n"
        run2 = svc.create_import_run(self.project["id"], changed_text)
        svc.approve_import_run(run2["id"], confirm=True)

        scenes = scene_repo.list_scenes(self.project["id"])
        self.assertEqual(len(scenes), 1)
        self.assertEqual(scenes[0]["id"], scene_id_before)
        self.assertIn("A totally different line", scenes[0]["raw_scene_text"])

    def test_removing_a_scene_without_downstream_data_requires_confirm_then_succeeds(self):
        self._approve(_TWO_SCENES)
        run2 = svc.create_import_run(self.project["id"], _SIMPLE_V1)  # drops scene 2

        with self.assertRaises(svc.ImportRunConflict):
            svc.approve_import_run(run2["id"])

        svc.approve_import_run(run2["id"], confirm=True)
        scenes = scene_repo.list_scenes(self.project["id"])
        self.assertEqual(len(scenes), 1)

    def test_removing_a_scene_with_downstream_shots_is_blocked_even_with_confirm(self):
        self._approve(_TWO_SCENES)
        scene2 = next(s for s in scene_repo.list_scenes(self.project["id"]) if s["scene_number"] == 2)
        shot_repo.create_shot({
            "project_id": self.project["id"], "scene_id": scene2["id"], "shot_number": 1,
            "title": "Shot", "prompt": "x", "duration_seconds": 5,
        })

        run2 = svc.create_import_run(self.project["id"], _SIMPLE_V1)  # would drop scene 2
        with self.assertRaises(svc.ImportRunConflict) as ctx:
            svc.approve_import_run(run2["id"], confirm=True)
        self.assertEqual(ctx.exception.reason, "downstream_data_protected")
        self.assertEqual(ctx.exception.protected_scene_ids, [scene2["id"]])

        # The scene, and its shot, must still exist untouched.
        scenes_after = scene_repo.list_scenes(self.project["id"])
        self.assertEqual(len(scenes_after), 2)
        self.assertEqual(len(scene_repo.get_scene(scene2["id"])["shots"]), 1)

    def test_approving_a_new_run_supersedes_the_previous_approved_run(self):
        run1 = svc.create_import_run(self.project["id"], _SIMPLE_V1)
        svc.approve_import_run(run1["id"])
        run2 = svc.create_import_run(self.project["id"], _TWO_SCENES)
        svc.approve_import_run(run2["id"])

        self.assertEqual(import_runs_repo.get_import_run(run1["id"])["status"], "superseded")
        self.assertEqual(import_runs_repo.get_import_run(run2["id"])["status"], "approved")

    def test_heading_based_matching_survives_scene_renumbering(self):
        # Insert a new scene 1, shifting the old scene 1 to scene 2 and the
        # old scene 2 to scene 3 — pure positional (scene_number) matching
        # would misread this as "scene 1 removed, a different scene 1 added"
        # for both original scenes, losing their ids (and any downstream
        # shots). Heading-based matching must instead recognize both as the
        # *same* scenes, just renumbered/"changed", not removed+re-added.
        self._approve(_TWO_SCENES)
        original_scene_ids = {s["normalized_heading"]: s["id"] for s in scene_repo.list_scenes(self.project["id"])}

        renumbered = (
            "1. INT. GARAGE - DAY\n\nA new opening scene.\n\n"
            "2. INT. HOUSE - DAY\n\nJOHN\nHi there.\n\n"
            "3. EXT. YARD - NIGHT\n\nMARY\nHello John.\n"
        )
        run2 = svc.create_import_run(self.project["id"], renumbered)
        diff = svc.preview_diff(run2["id"])
        self.assertEqual(len(diff["added"]), 1)
        self.assertEqual(len(diff["removed"]), 0)
        # Renumbering is real, reported information (scene_number changed),
        # so these are "changed", not silently "unchanged" — but critically
        # they were MATCHED (not removed+added), which is what the next
        # assertion after approval proves actually matters: id preservation.
        self.assertEqual(len(diff["changed"]), 2)
        self.assertEqual(len(diff["unchanged"]), 0)

        svc.approve_import_run(run2["id"], confirm=True)
        scenes_after = scene_repo.list_scenes(self.project["id"])
        self.assertEqual(len(scenes_after), 3)
        for scene in scenes_after:
            if scene["normalized_heading"] in original_scene_ids:
                self.assertEqual(scene["id"], original_scene_ids[scene["normalized_heading"]])


class TransactionAtomicityTests(ScreenplayImportServiceTestCase):
    def test_failure_partway_through_commit_leaves_no_partial_scenes(self):
        # _replace_blocks runs immediately after each scene's own INSERT,
        # inside the same still-open transaction — failing here for the
        # first scene proves that even an already-INSERTed scene row (not
        # just later ones) gets rolled back, because commit() is never
        # reached for the whole approve_import_run() call.
        run = svc.create_import_run(self.project["id"], _TWO_SCENES)

        with patch(
            "app.repositories.screenplay_structure._replace_blocks",
            side_effect=RuntimeError("simulated failure mid-commit"),
        ):
            with self.assertRaises(RuntimeError):
                svc.approve_import_run(run["id"])

        # Nothing was partially written: zero scenes, run still review_required.
        self.assertEqual(scene_repo.list_scenes(self.project["id"]), [])
        self.assertEqual(import_runs_repo.get_import_run(run["id"])["status"], "review_required")


class ComputeDiffUnitTests(ScreenplayImportServiceTestCase):
    def test_empty_project_treats_all_scenes_as_added(self):
        parsed_scenes = [
            {"scene_number": 1, "normalized_heading": "INT. A - DAY", "int_ext": "INT",
             "location": "A", "time_of_day": "DAY", "raw_scene_text": "1. INT. A - DAY"},
        ]
        diff = svc.compute_diff(self.project["id"], parsed_scenes)
        self.assertEqual(len(diff["added"]), 1)
        self.assertFalse(diff["requires_confirmation"])


if __name__ == "__main__":
    unittest.main()
