"""Phase-17 acceptance test: one realistic full screenplay driven through
the entire Script Import flow exactly as a production user would use it —
parse -> preview -> edit-before-commit -> approve -> persist -> survive a
restart -> safely re-import a later draft without destroying downstream
production work.

This is deliberately one long ordered story rather than N independent
unit tests: the point of Phase 17 is proving these properties hold
*together*, on one screenplay, not in isolation. Each step is a numbered
test method on a shared TestCase so failures point at exactly which
promise broke; unittest runs a class's methods in alphabetical order, so
step numbers are zero-padded into the method names to keep that order
meaningful without depending on unittest internals.

Uses the service layer directly (app.services.screenplay_import_service),
the same entry points app/api/screenplay_imports.py calls — API-layer
request/response wiring is covered separately in
tests/test_screenplay_imports_api.py, and the interactive UI was verified
against a live server with Playwright during development (parse -> diff
-> approve, edit-and-reparse, confirmed re-import with id preservation,
and the protected-removal block all reproduced in a real browser).
"""

import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.database.connection import get_connection, init_db
from app.repositories import projects, scenes as scene_repo, shots as shot_repo
from app.services import screenplay_import_service as import_service

# --- The screenplay, in three drafts -----------------------------------------
#
# DRAFT_1: what the user first pastes in.
# DRAFT_2: DRAFT_1 with scene 6's closing line edited *before* approval —
#          proves the edit-before-commit step actually changes what gets
#          persisted, not just the in-memory preview.
# DRAFT_3: DRAFT_2 approved, then re-imported later with scene 2's dialogue
#          rewritten (a real change) and scene 4 dropped entirely (an
#          attempted removal of a scene that, by then, has a shot on it).

DRAFT_1 = """1. INT. NEWSROOM - DAY

LIANA sits at her desk, scanning headlines. Her editor, TOM, appears at
her side.

TOM
You're not seriously running with this.

LIANA
I have three sources.

TOM
(skeptical)
Three anonymous sources.

2. EXT. CITY HALL STEPS - DAY

Reporters gather as the MAYOR steps up to a bank of microphones.

MAYOR
The allegations are baseless.

Liana watches from the back of the crowd, recording on her phone.

3. INT. NEWSROOM - NIGHT

Liana sits alone, typing furiously.

TOM (O.S.)
Liana, legal wants to see the draft.

LIANA
Tell them it's coming.

4. EXT. PARKING GARAGE - NIGHT

Liana walks quickly to her car. A SOURCE steps out of the shadows.

SOURCE
You didn't hear this from me.

LIANA
I never do.

5. INT. NEWSROOM - MORNING

Tom reads the final draft, tension in his shoulders.

TOM
Run it.

6. INT. NEWSROOM - EVENING

The newsroom buzzes with activity. Liana watches the story go live on
every screen.

LIANA
(quietly)
We did it.
"""

DRAFT_2 = DRAFT_1.replace("We did it.", "We did it. Together.")

DRAFT_3 = DRAFT_2.replace(
    "MAYOR\nThe allegations are baseless.",
    "MAYOR\nThe allegations are completely baseless.",
).replace(
    """4. EXT. PARKING GARAGE - NIGHT

Liana walks quickly to her car. A SOURCE steps out of the shadows.

SOURCE
You didn't hear this from me.

LIANA
I never do.

5. INT. NEWSROOM - MORNING""",
    "4. INT. NEWSROOM - MORNING",
)


class ScriptImportAcceptanceTest(unittest.TestCase):
    """One realistic screenplay, the full flow, in order."""

    # setUpClass/tearDownClass, not setUp/tearDown: this is one continuous
    # story told across ordered test_NN methods sharing a single project
    # and database, exactly like a real user session — a fresh database
    # per method would defeat the point of an *acceptance* test.
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.original_db = settings.database_path
        settings.database_path = Path(cls.tempdir.name) / "acceptance.db"
        init_db()
        cls.project = projects.create_project({
            "name": "Acceptance: Breaking News", "description": "",
            "visual_style": "", "rules": "",
        })

    @classmethod
    def tearDownClass(cls):
        settings.database_path = cls.original_db
        cls.tempdir.cleanup()

    def test_01_stage_a_parse_never_writes_to_production_tables(self):
        run = import_service.create_import_run(self.project["id"], DRAFT_1)
        self.assertEqual(run["status"], "review_required")
        self.assertEqual(scene_repo.list_scenes(self.project["id"]), [])
        self.__class__.first_run_id = run["id"]

    def test_02_scene_count_order_and_no_dup_or_missing(self):
        run = import_service.reparse_import_run(self.first_run_id)
        scenes = run["breakdown"]["scenes"]
        self.assertEqual(len(scenes), 6)
        self.assertEqual([s["scene_number"] for s in scenes], [1, 2, 3, 4, 5, 6])
        headings = [s["original_heading"] for s in scenes]
        self.assertEqual(len(headings), len(set(headings)))  # no duplicate scenes

    def test_03_headings_preserved_verbatim(self):
        run = import_service.reparse_import_run(self.first_run_id)
        scenes = run["breakdown"]["scenes"]
        self.assertEqual(scenes[3]["original_heading"], "4. EXT. PARKING GARAGE - NIGHT")
        self.assertEqual(scenes[3]["normalized_heading"], "EXT. PARKING GARAGE - NIGHT")
        self.assertEqual(scenes[0]["original_heading"], "1. INT. NEWSROOM - DAY")

    def test_04_dialogue_is_correctly_attributed(self):
        run = import_service.reparse_import_run(self.first_run_id)
        scenes = run["breakdown"]["scenes"]

        def dialogue(scene_number, text_snippet):
            scene = scenes[scene_number - 1]
            return next(
                b for b in scene["blocks"]
                if b["block_type"] == "dialogue" and text_snippet in b["raw_text"]
            )

        self.assertEqual(dialogue(1, "not seriously running")["character_name"], "TOM")
        self.assertEqual(dialogue(1, "three sources")["character_name"], "LIANA")
        self.assertEqual(dialogue(2, "baseless")["character_name"], "MAYOR")
        self.assertEqual(dialogue(4, "hear this from me")["character_name"], "SOURCE")
        self.assertEqual(dialogue(3, "legal wants")["character_name"], "TOM")

    def test_05_locations_are_normalized_and_deduplicated(self):
        run = import_service.reparse_import_run(self.first_run_id)
        breakdown = run["breakdown"]
        location_names = sorted(loc["canonical_name"] for loc in breakdown["locations"])
        self.assertEqual(location_names, ["CITY HALL STEPS", "NEWSROOM", "PARKING GARAGE"])
        newsroom = next(loc for loc in breakdown["locations"] if loc["canonical_name"] == "NEWSROOM")
        self.assertEqual(newsroom["first_appearance_scene_number"], 1)

    def test_06_characters_are_deduplicated_across_annotation_variants(self):
        run = import_service.reparse_import_run(self.first_run_id)
        breakdown = run["breakdown"]
        character_names = sorted(c["canonical_name"] for c in breakdown["characters"])
        self.assertEqual(character_names, ["LIANA", "MAYOR", "SOURCE", "TOM"])
        tom = next(c for c in breakdown["characters"] if c["canonical_name"] == "TOM")
        # TOM speaks plainly in scenes 1 and 5, and as "TOM (O.S.)" in scene
        # 3 — one character, not two, and first appearance is still scene 1.
        self.assertEqual(tom["first_appearance_scene_number"], 1)

    def test_07_preview_is_available_and_still_has_made_no_production_writes(self):
        # preview_diff being queryable pre-approval *is* the preview step.
        diff = import_service.preview_diff(self.first_run_id)
        self.assertEqual(len(diff["added"]), 6)
        self.assertFalse(diff["requires_confirmation"])
        self.assertEqual(scene_repo.list_scenes(self.project["id"]), [])

    def test_08_edit_before_commit_changes_what_will_be_persisted(self):
        run = import_service.reparse_import_run(self.first_run_id, DRAFT_2)
        self.assertEqual(run["id"], self.first_run_id)  # same run, edited in place
        self.assertEqual(run["status"], "review_required")
        last_scene = run["breakdown"]["scenes"][-1]
        dialogue_texts = " ".join(
            b["raw_text"] for b in last_scene["blocks"] if b["block_type"] == "dialogue"
        )
        self.assertIn("Together.", dialogue_texts)

    def test_09_approved_import_persists(self):
        summary = import_service.approve_import_run(self.first_run_id)
        self.assertEqual(summary["scenes_added"], 6)
        scenes = scene_repo.list_scenes(self.project["id"])
        self.assertEqual(len(scenes), 6)
        scene_6 = next(s for s in scenes if s["scene_number"] == 6)
        self.assertIn("Together", scene_6["raw_scene_text"])
        self.__class__.original_scene_ids = {s["scene_number"]: s["id"] for s in scenes}

    def test_10_data_survives_a_fresh_connection_and_a_rerun_migration(self):
        # Best available proxy for "refresh the page / redeploy the app" in
        # a file-backed SQLite test: drop every cached connection, re-run
        # the (additive, idempotent) startup migration exactly as the
        # FastAPI lifespan hook does on every boot, then read the data back
        # through brand new connections only.
        get_connection().close()
        init_db()

        scenes = scene_repo.list_scenes(self.project["id"])
        self.assertEqual(len(scenes), 6)
        self.assertEqual(
            {s["scene_number"]: s["id"] for s in scenes},
            self.original_scene_ids,
        )
        scene_6 = next(s for s in scenes if s["scene_number"] == 6)
        self.assertIn("Together", scene_6["raw_scene_text"])

    def test_11_reimport_that_would_remove_a_scene_with_shots_is_blocked_unconditionally(self):
        protected_scene_id = self.original_scene_ids[4]  # PARKING GARAGE
        shot_repo.create_shot({
            "project_id": self.project["id"], "scene_id": protected_scene_id,
            "shot_number": 1, "title": "שוט 1",
        })

        second_run = import_service.create_import_run(self.project["id"], DRAFT_3)
        diff = import_service.preview_diff(second_run["id"])
        removed_ids = {row["id"] for row in diff["removed"]}
        self.assertIn(protected_scene_id, removed_ids)

        with self.assertRaises(import_service.ImportRunConflict) as ctx:
            import_service.approve_import_run(second_run["id"], confirm=True)
        self.assertEqual(ctx.exception.reason, "downstream_data_protected")
        self.assertIn(protected_scene_id, ctx.exception.protected_scene_ids)

        # Nothing was destroyed: still 6 scenes, same ids, shot still there.
        scenes_after = scene_repo.list_scenes(self.project["id"])
        self.assertEqual(len(scenes_after), 6)
        self.assertEqual(
            {s["scene_number"]: s["id"] for s in scenes_after}, self.original_scene_ids,
        )
        remaining_shots = shot_repo.list_shots(self.project["id"])
        self.assertEqual(len(remaining_shots), 1)
        self.assertEqual(remaining_shots[0]["scene_id"], protected_scene_id)

    def test_12_reimport_that_keeps_the_protected_scene_applies_the_real_change_safely(self):
        protected_scene_id = self.original_scene_ids[4]
        safe_new_text = DRAFT_2.replace(
            "MAYOR\nThe allegations are baseless.",
            "MAYOR\nThe allegations are completely baseless.",
        )
        run = import_service.create_import_run(self.project["id"], safe_new_text)
        diff = import_service.preview_diff(run["id"])
        self.assertEqual(len(diff["removed"]), 0)
        self.assertTrue(diff["requires_confirmation"])  # scene 2 changed

        summary = import_service.approve_import_run(run["id"], confirm=True)
        self.assertEqual(summary["scenes_changed"], 1)
        self.assertEqual(summary["scenes_removed"], 0)

        scenes_after = scene_repo.list_scenes(self.project["id"])
        self.assertEqual(len(scenes_after), 6)
        after_ids = {s["scene_number"]: s["id"] for s in scenes_after}
        self.assertEqual(after_ids, self.original_scene_ids)
        # The scene with the shot on it is untouched, id-for-id.
        self.assertEqual(after_ids[4], protected_scene_id)
        scene_2 = next(s for s in scenes_after if s["scene_number"] == 2)
        self.assertIn("completely baseless", scene_2["raw_scene_text"])


if __name__ == "__main__":
    unittest.main()
