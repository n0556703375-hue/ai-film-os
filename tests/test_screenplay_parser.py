"""Coverage for the deterministic screenplay structural parser.

All screenplay text here is original synthetic material written for this
test suite — no copyrighted screenplay content is used anywhere.
"""

import unittest

from app.services.screenplay_parser import (
    ScreenplayParseError,
    parse_screenplay,
    validate_scene_order,
)


class EmptyAndErrorTests(unittest.TestCase):
    def test_empty_screenplay_raises(self):
        with self.assertRaises(ScreenplayParseError):
            parse_screenplay("")

    def test_whitespace_only_screenplay_raises(self):
        with self.assertRaises(ScreenplayParseError):
            parse_screenplay("   \n\n   ")


class SceneDetectionTests(unittest.TestCase):
    def test_numbered_english_scenes_detected_in_order(self):
        text = (
            "1. INT. KITCHEN - DAY\n\nA kettle boils.\n\n"
            "2. EXT. GARDEN - DAY\n\nLeaves fall.\n\n"
            "3. INT. KITCHEN - NIGHT\n\nThe kettle is cold now.\n"
        )
        result = parse_screenplay(text)
        self.assertEqual([s.scene_number for s in result.scenes], [1, 2, 3])
        self.assertEqual(result.scenes[0].location, "KITCHEN")
        self.assertEqual(result.scenes[0].time_of_day, "DAY")
        self.assertEqual(result.scenes[2].time_of_day, "NIGHT")

    def test_unnumbered_english_scenes_detected(self):
        text = "INT. OFFICE - DAY\n\nPapers everywhere.\n\nEXT. PARKING LOT - NIGHT\n\nA lone car.\n"
        result = parse_screenplay(text)
        self.assertEqual(len(result.scenes), 2)
        self.assertEqual(result.scenes[0].location, "OFFICE")
        self.assertEqual(result.scenes[1].location, "PARKING LOT")

    def test_int_ext_combined_heading(self):
        for token in ("INT./EXT.", "INT/EXT", "EXT./INT.", "I/E."):
            with self.subTest(token=token):
                text = f"{token} CAR - DAY\n\nDriving through the city.\n"
                result = parse_screenplay(text)
                self.assertEqual(result.scenes[0].int_ext, "INT/EXT")

    def test_hebrew_scene_headings_detected(self):
        text = (
            "1. פנים. משרד - יום\n\nהשולחן מלא ניירת.\n\n"
            "2. חוץ. חניה - לילה\n\nמכונית בודדת.\n"
        )
        result = parse_screenplay(text)
        self.assertEqual(len(result.scenes), 2)
        self.assertEqual(result.scenes[0].int_ext, "פנים")
        self.assertEqual(result.scenes[0].location, "משרד")
        self.assertEqual(result.scenes[1].int_ext, "חוץ")

    def test_hebrew_combined_int_ext_heading(self):
        text = "פנים/חוץ. מרפסת - ערב\n\nהיא מביטה בעיר.\n"
        result = parse_screenplay(text)
        self.assertEqual(result.scenes[0].int_ext, "פנים/חוץ")

    def test_mixed_hebrew_and_english_screenplay(self):
        text = (
            "1. INT. APARTMENT - DAY\n\nA suitcase lies open.\n\n"
            "2. פנים. דירה - יום\n\nמזוודה פתוחה על הרצפה.\n"
        )
        result = parse_screenplay(text)
        self.assertEqual(len(result.scenes), 2)
        self.assertEqual(result.scenes[0].location, "APARTMENT")
        self.assertEqual(result.scenes[1].location, "דירה")

    def test_extra_whitespace_and_page_breaks_do_not_break_detection(self):
        text = (
            "1.    INT.   HOUSE   -   DAY\n\n\n"
            "   John enters the room slowly.   \n\n"
            "-- 2 --\n\n"
            "2. EXT. YARD - NIGHT\n\nA dog barks.\n"
        )
        result = parse_screenplay(text)
        self.assertEqual(len(result.scenes), 2)
        self.assertEqual(result.scenes[0].location, "HOUSE")
        self.assertIn("John enters the room slowly.", result.scenes[0].raw_scene_text)

    def test_no_scene_headings_falls_back_to_single_scene_with_warning(self):
        text = "Just some free-form text with no screenplay structure at all.\nMore text here.\n"
        result = parse_screenplay(text)
        self.assertEqual(len(result.scenes), 1)
        self.assertEqual(result.scenes[0].scene_number, 1)
        self.assertIn("Just some free-form text", result.scenes[0].raw_scene_text)
        categories = [w.category for w in result.warnings]
        self.assertIn("no_scene_headings_detected", categories)

    def test_scene_order_invariant_holds_for_many_scenes(self):
        parts = [f"{i}. INT. ROOM {i} - DAY\n\nSomething happens in room {i}.\n" for i in range(1, 21)]
        result = parse_screenplay("\n".join(parts))
        self.assertEqual([s.scene_number for s in result.scenes], list(range(1, 21)))
        validate_scene_order(result.scenes)  # must not raise

    def test_no_scene_is_dropped_duplicated_or_reordered(self):
        text = (
            "1. INT. A - DAY\n\nFirst.\n\n"
            "2. INT. B - DAY\n\nSecond.\n\n"
            "3. INT. C - DAY\n\nThird.\n\n"
            "4. INT. D - DAY\n\nFourth.\n"
        )
        result = parse_screenplay(text)
        headings = [s.location for s in result.scenes]
        self.assertEqual(headings, ["A", "B", "C", "D"])
        self.assertEqual(len(set(s.scene_number for s in result.scenes)), 4)

    def test_original_heading_text_is_preserved_verbatim_content(self):
        text = "7. INT.   WAREHOUSE - CONTINUOUS\n\nBoxes stacked to the ceiling.\n"
        result = parse_screenplay(text)
        self.assertIn("WAREHOUSE", result.scenes[0].original_heading)
        self.assertEqual(result.scenes[0].time_of_day, "CONTINUOUS")


class DialogueVsActionTests(unittest.TestCase):
    def test_action_paragraph_is_never_classified_as_dialogue(self):
        text = (
            "1. INT. ROOM - DAY\n\n"
            "The room is quiet. Dust floats in the light. Nothing moves for a long moment.\n"
        )
        result = parse_screenplay(text)
        blocks = result.scenes[0].blocks
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].block_type, "action")
        self.assertEqual(blocks[0].character_name, "")

    def test_dialogue_heavy_scene_alternates_correctly(self):
        text = (
            "1. INT. CAFE - DAY\n\n"
            "ANNA\n"
            "Did you get my message?\n\n"
            "DAVID\n"
            "Yeah, I saw it.\n\n"
            "ANNA\n"
            "And?\n\n"
            "DAVID\n"
            "I'm still thinking.\n"
        )
        result = parse_screenplay(text)
        blocks = result.scenes[0].blocks
        self.assertEqual([b.block_type for b in blocks], ["dialogue"] * 4)
        self.assertEqual([b.character_name for b in blocks], ["ANNA", "DAVID", "ANNA", "DAVID"])
        self.assertEqual(blocks[0].raw_text, "Did you get my message?")

    def test_action_heavy_scene_has_no_dialogue_blocks(self):
        text = (
            "1. EXT. FIELD - DAY\n\n"
            "Wind moves through tall grass.\n\n"
            "A hawk circles overhead.\n\n"
            "Clouds gather on the horizon.\n"
        )
        result = parse_screenplay(text)
        blocks = result.scenes[0].blocks
        self.assertTrue(all(b.block_type == "action" for b in blocks))
        self.assertEqual(len(blocks), 3)

    def test_dialogue_is_never_assigned_to_the_wrong_character(self):
        text = (
            "1. INT. ROOM - DAY\n\n"
            "PETER\n"
            "This is mine.\n\n"
            "SUSAN\n"
            "No, it's mine.\n"
        )
        result = parse_screenplay(text)
        blocks = result.scenes[0].blocks
        self.assertEqual(blocks[0].character_name, "PETER")
        self.assertEqual(blocks[0].raw_text, "This is mine.")
        self.assertEqual(blocks[1].character_name, "SUSAN")
        self.assertEqual(blocks[1].raw_text, "No, it's mine.")

    def test_parenthetical_before_dialogue_is_captured_separately(self):
        text = "1. INT. ROOM - DAY\n\nJANE\n(whispering)\nDon't move.\n"
        result = parse_screenplay(text)
        block = result.scenes[0].blocks[0]
        self.assertEqual(block.block_type, "dialogue")
        self.assertEqual(block.parenthetical, "(whispering)")
        self.assertEqual(block.raw_text, "Don't move.")

    def test_transition_is_classified_as_transition_not_action(self):
        text = "1. INT. ROOM - DAY\n\nShe leaves.\n\nFADE OUT.\n\n2. EXT. STREET - DAY\n\nRain falls.\n"
        result = parse_screenplay(text)
        blocks = result.scenes[0].blocks
        self.assertEqual(blocks[-1].block_type, "transition")
        self.assertEqual(blocks[-1].raw_text, "FADE OUT.")

    def test_cue_with_vo_annotation_still_classified_as_dialogue(self):
        text = "1. INT. ROOM - DAY\n\nTOM (V.O.)\nI never told anyone.\n"
        result = parse_screenplay(text)
        block = result.scenes[0].blocks[0]
        self.assertEqual(block.block_type, "dialogue")
        self.assertEqual(block.character_name, "TOM")

    def test_low_confidence_hebrew_cue_without_colon_is_flagged(self):
        # Hebrew has no case distinction, so a short line with no colon is a
        # guess, not a confirmed cue — must be flagged, not silently trusted.
        text = "1. פנים. חדר - יום\n\nדני\nבוא הנה כבר.\n"
        result = parse_screenplay(text)
        block = result.scenes[0].blocks[0]
        self.assertEqual(block.confidence, "low")
        categories = [w.category for w in result.warnings]
        self.assertIn("low_confidence_classification", categories)

    def test_hebrew_action_lead_in_ending_in_colon_is_not_a_fabricated_cue(self):
        # "על המסך:" ("on the screen:") introduces a displayed message —
        # a common Hebrew screenwriting convention — not a speaker. Found
        # via a real production screenplay where this pattern inflated the
        # character count from ~13 real speakers to 56 entities.
        text = (
            "1. INT. ROOM - DAY\n\n"
            "היא בודקת את המסך.\n"
            "על המסך:\n"
            "אזעקה פעילה.\n\n"
            "דבורה:\n"
            "מה קורה?\n"
        )
        result = parse_screenplay(text)
        names = [c.canonical_name for c in result.characters]
        self.assertEqual(names, ["דבורה"])
        action_text = " ".join(
            b.raw_text for b in result.scenes[0].blocks if b.block_type == "action"
        )
        self.assertIn("אזעקה פעילה", action_text)

    def test_long_hebrew_sentence_ending_in_colon_is_not_a_cue(self):
        text = (
            "1. INT. ROOM - DAY\n\n"
            "היא פותחת שלוש שכבות:\n"
            "האחת ריקה.\n\n"
            "דני:\n"
            "בוא הנה.\n"
        )
        result = parse_screenplay(text)
        names = [c.canonical_name for c in result.characters]
        self.assertEqual(names, ["דני"])

    def test_digit_containing_colon_line_is_not_a_cue(self):
        # A page number or timestamp fused onto adjacent text by a PDF
        # export ("00:09דבורה:") is never a real character name.
        text = (
            "1. INT. ROOM - DAY\n\n"
            "00:09תוצאה:\n"
            "בדיקה הושלמה.\n\n"
            "רותם:\n"
            "טוב.\n"
        )
        result = parse_screenplay(text)
        names = [c.canonical_name for c in result.characters]
        self.assertEqual(names, ["רותם"])

    def test_short_two_word_hebrew_role_cue_still_recognized(self):
        # "קול האטלס:" ("Voice of the Atlas:") is a legitimate short
        # descriptive speaker role, not a narration lead-in — the fix for
        # the above cases must not start rejecting real short cues.
        text = "1. INT. ROOM - DAY\n\nקול האטלס:\nהודעה לכולם.\n"
        result = parse_screenplay(text)
        names = [c.canonical_name for c in result.characters]
        self.assertEqual(names, ["קול האטלס"])
        self.assertEqual(result.scenes[0].blocks[0].confidence, "high")

    def test_multi_word_action_sentence_without_colon_is_not_guessed_as_a_cue(self):
        # The no-colon "low confidence" guess previously had no word-count
        # cap (only a character-length cap), so a short action sentence
        # with no trailing punctuation — e.g. "Samdar leads them inside" —
        # could be mistaken for a cue. A real cue is a name, at most a
        # couple of words, never a full sentence.
        text = (
            "1. INT. ROOM - DAY\n\n"
            "סמדר מובילה אותן אותן פנימה\n"
            "הן נכנסות בשקט.\n\n"
            "דני:\n"
            "היי.\n"
        )
        result = parse_screenplay(text)
        names = [c.canonical_name for c in result.characters]
        self.assertEqual(names, ["דני"])

    def test_negation_and_door_lead_word_lines_are_not_guessed_as_cues(self):
        # "לא ירוק" ("not green") and "הדלת נפתחת" ("the door opens") are
        # two-word action fragments that pass the word-count cap but are
        # never real character names — negation words and physical objects
        # never open a speaker cue.
        for line in ["לא ירוק", "הדלת נפתחת"]:
            with self.subTest(line=line):
                text = f"1. INT. ROOM - DAY\n\n{line}\nעוד פעולה כאן.\n\nדני:\nהיי.\n"
                result = parse_screenplay(text)
                names = [c.canonical_name for c in result.characters]
                self.assertEqual(names, ["דני"])

    def test_colon_wrapped_onto_start_of_next_line_is_reattached(self):
        # Same RTL copy-paste artifact as the period case above, but with a
        # colon: a narration lead-in's trailing colon lands on the *next*
        # visual line instead of the end of the line it belongs to. Found
        # in a real production screenplay ("...הודעה\n:תשע שעות...").
        # Left unhandled, the announcement text is left carrying a stray
        # leading colon.
        text = (
            "1. פנים. רחוב - יום\n\n"
            "על מסך עירוני קטן מעל הרובע מופיעה אותה הודעה\n"
            ":תשע שעות להפעלת הציר הלבן.\n\n"
            "דבורה:\n"
            "מה קורה?\n"
        )
        result = parse_screenplay(text)
        names = [c.canonical_name for c in result.characters]
        self.assertEqual(names, ["דבורה"])
        action_lines = [b.raw_text for b in result.scenes[0].blocks if b.block_type == "action"]
        self.assertTrue(all(not line.startswith(":") for line in action_lines))
        self.assertTrue(any(line.endswith("הודעה:\nתשע שעות להפעלת הציר הלבן.") for line in action_lines))

    def test_digit_fused_short_line_without_colon_is_not_guessed_as_a_cue(self):
        # A page-number/timestamp fused directly onto text by a PDF export
        # ("5תמר") is never a real character name, whether or not the line
        # ends in a colon.
        text = "1. INT. ROOM - DAY\n\n5תמר\nהיא נכנסת.\n\nדני:\nהיי.\n"
        result = parse_screenplay(text)
        names = [c.canonical_name for c in result.characters]
        self.assertEqual(names, ["דני"])

    def test_generic_system_and_location_label_colon_lines_are_not_guessed_as_cues(self):
        # Generic labels that lead in to displayed/read text ("Result:",
        # "Options:", "List of names:", "Typing:", "In the transit
        # center:") — never a speaking character's name.
        for label in ["תוצאה", "אפשרויות", "רשימת שמות", "מקלידה", "במרכז התחבורה"]:
            with self.subTest(label=label):
                text = (
                    "1. INT. ROOM - DAY\n\n"
                    f"{label}:\n"
                    "פרטים מוצגים כאן.\n\n"
                    "דני:\n"
                    "טוב.\n"
                )
                result = parse_screenplay(text)
                names = [c.canonical_name for c in result.characters]
                self.assertEqual(names, ["דני"])

    def test_scene_and_screen_heading_fragments_are_not_guessed_as_cues(self):
        # A scene/act heading or "the screen" fragmented across a mid-word
        # PDF line-wrap must never be guessed as a character's name.
        for fragment in ["סצנה", "חלק", "מסך"]:
            with self.subTest(fragment=fragment):
                text = f"1. INT. ROOM - DAY\n\n{fragment}\nהמשך הפעולה.\n\nדני:\nהיי.\n"
                result = parse_screenplay(text)
                names = [c.canonical_name for c in result.characters]
                self.assertEqual(names, ["דני"])

    def test_new_speaker_cue_ends_previous_dialogue_block_even_without_a_blank_line(self):
        # Real-world pasted screenplays often lack a blank line between
        # consecutive speaker exchanges. Without a boundary check, the
        # dialogue-collection loop swallowed the next speaker's cue and
        # lines as literal text into the first speaker's block, badly
        # misattributing dialogue across the whole document.
        text = "1. פנים. חדר - יום\n\nיוכבד:\nבואי הנה.\nליאורה:\nאני באה.\n"
        result = parse_screenplay(text)
        blocks = result.scenes[0].blocks
        self.assertEqual([b.block_type for b in blocks], ["dialogue", "dialogue"])
        self.assertEqual([b.character_name for b in blocks], ["יוכבד", "ליאורה"])
        self.assertEqual(blocks[0].raw_text, "בואי הנה.")
        self.assertEqual(blocks[1].raw_text, "אני באה.")

    def test_block_order_is_preserved_within_a_scene(self):
        text = (
            "1. INT. ROOM - DAY\n\n"
            "He walks in.\n\n"
            "MIA\n"
            "Finally.\n\n"
            "He sits.\n\n"
            "CUT TO:\n"
        )
        result = parse_screenplay(text)
        types = [b.block_type for b in result.scenes[0].blocks]
        self.assertEqual(types, ["action", "dialogue", "action", "transition"])
        orders = [b.order for b in result.scenes[0].blocks]
        self.assertEqual(orders, sorted(orders))


class CharacterNormalizationTests(unittest.TestCase):
    def test_exact_case_and_whitespace_variants_merge_to_one_character(self):
        text = (
            "1. INT. ROOM - DAY\n\nJOHN\nHello.\n\n"
            "2. INT. ROOM - NIGHT\n\nJohn\nHi again.\n\n"
            "3. INT. ROOM - DAY\n\nJOHN  \nOne more time.\n"
        )
        result = parse_screenplay(text)
        self.assertEqual(len(result.characters), 1)
        self.assertEqual(result.characters[0].first_appearance_scene_number, 1)

    def test_annotation_variants_of_same_character_do_not_create_aliases_incorrectly(self):
        text = "1. INT. ROOM - DAY\n\nKATE\nHi.\n\n2. INT. ROOM - DAY\n\nKATE (O.S.)\nWait!\n"
        result = parse_screenplay(text)
        names = [c.canonical_name for c in result.characters]
        self.assertEqual(names, ["KATE"])

    def test_genuinely_different_names_are_never_merged(self):
        # "JOHN" vs "JOHN SMITH" must stay separate — never auto-merge on
        # partial overlap, only on an exact normalized match.
        text = "1. INT. ROOM - DAY\n\nJOHN\nHi.\n\n2. INT. ROOM - DAY\n\nJOHN SMITH\nHello there.\n"
        result = parse_screenplay(text)
        names = sorted(c.canonical_name for c in result.characters)
        self.assertEqual(names, ["JOHN", "JOHN SMITH"])

    def test_hebrew_character_alias_spacing_variant_merges(self):
        text = (
            "1. פנים. חדר - יום\n\nרונית:\nשלום.\n\n"
            "2. פנים. חדר - יום\n\nרונית  :\nמה שלומך.\n"
        )
        result = parse_screenplay(text)
        self.assertEqual(len(result.characters), 1)
        self.assertEqual(result.characters[0].canonical_name.strip(), "רונית")


class LocationNormalizationTests(unittest.TestCase):
    def test_exact_formatting_variants_of_same_location_merge(self):
        text = (
            "1. INT. KITCHEN - DAY\n\nCooking.\n\n"
            "2. int.   kitchen - night\n\nStill cooking.\n"
        )
        result = parse_screenplay(text)
        self.assertEqual(len(result.locations), 1)

    def test_different_phrasings_of_a_location_are_not_semantically_merged(self):
        # Documented v1 limitation: only exact-normalized matches merge.
        # "LEORA'S HOUSE" and "LEORA - LIVING ROOM" are conceptually related
        # but textually different, so they stay as two distinct locations
        # rather than risking an incorrect merge.
        text = (
            "1. INT. LEORA'S HOUSE - DAY\n\nShe walks in.\n\n"
            "2. INT. LEORA'S HOUSE - LIVING ROOM - DAY\n\nShe sits.\n"
        )
        result = parse_screenplay(text)
        self.assertEqual(len(result.locations), 2)

    def test_location_first_appearance_scene_number_is_correct(self):
        text = "1. INT. A - DAY\n\nx\n\n2. INT. B - DAY\n\ny\n\n3. INT. A - NIGHT\n\nz\n"
        result = parse_screenplay(text)
        location_a = next(loc for loc in result.locations if loc.canonical_name == "A")
        self.assertEqual(location_a.first_appearance_scene_number, 1)


class PropExtractionTests(unittest.TestCase):
    def test_quoted_prop_in_action_line_is_extracted(self):
        text = "1. INT. KITCHEN - DAY\n\nHe picks up the \"gun\" and hides it.\n"
        result = parse_screenplay(text)
        names = [p.canonical_name for p in result.props]
        self.assertEqual(names, ["gun"])

    def test_hebrew_gershayim_quoted_prop_is_extracted(self):
        text = "1. INT. MITBAH - DAY\n\nהיא מוציאה ״אקדח״ מהמגירה.\n"
        result = parse_screenplay(text)
        names = [p.canonical_name for p in result.props]
        self.assertEqual(names, ["אקדח"])

    def test_quoted_dialogue_is_never_treated_as_a_prop(self):
        text = "1. INT. ROOM - DAY\n\nJOHN\n\"Get out\", he says nothing else.\n"
        result = parse_screenplay(text)
        self.assertEqual(result.props, [])

    def test_repeated_quoted_prop_merges_and_keeps_first_scene(self):
        text = (
            "1. INT. ROOM - DAY\n\nThe \"knife\" gleams.\n\n"
            "2. INT. ROOM - NIGHT\n\nThe \"knife\" is gone.\n"
        )
        result = parse_screenplay(text)
        self.assertEqual(len(result.props), 1)
        self.assertEqual(result.props[0].first_appearance_scene_number, 1)

    def test_no_quoted_spans_yields_no_props(self):
        text = "1. INT. ROOM - DAY\n\nNothing notable happens here.\n"
        result = parse_screenplay(text)
        self.assertEqual(result.props, [])


class MalformedButRecoverableTests(unittest.TestCase):
    def test_missing_time_of_day_does_not_break_heading_parse(self):
        text = "1. INT. LIBRARY\n\nBooks everywhere.\n"
        result = parse_screenplay(text)
        self.assertEqual(result.scenes[0].location, "LIBRARY")
        self.assertEqual(result.scenes[0].time_of_day, "")

    def test_lowercase_int_ext_still_detected(self):
        text = "int. shed - day\n\nTools on the wall.\n"
        result = parse_screenplay(text)
        self.assertEqual(len(result.scenes), 1)
        self.assertEqual(result.scenes[0].int_ext, "INT")

    def test_heading_with_trailing_colon_separator(self):
        text = "INT: GARAGE - NIGHT\n\nA motorcycle under a tarp.\n"
        result = parse_screenplay(text)
        self.assertEqual(result.scenes[0].location, "GARAGE")

    def test_period_wrapped_onto_start_of_next_line_does_not_split_a_cue(self):
        # A common RTL copy-paste-from-PDF artifact: a sentence-ending
        # period lands on the *next* visual line instead of the end of
        # the one it belongs to — "...רגע\n.דבורה:\n..." instead of
        # "...רגע.\nדבורה:\n...". Left unhandled this both breaks the
        # previous action line's own punctuation and creates ".דבורה" as
        # a second, spurious character distinct from every clean "דבורה"
        # cue elsewhere in the document.
        text = (
            "1. INT. ROOM - DAY\n\n"
            "דבורה שותקת רגע\n"
            ".דבורה:\n"
            "תסמני לבדיקה.\n\n"
            "2. INT. ROOM - NIGHT\n\n"
            "דבורה:\n"
            "עוד פעם.\n"
        )
        result = parse_screenplay(text)
        names = [c.canonical_name for c in result.characters]
        self.assertEqual(names, ["דבורה"])
        self.assertEqual(result.characters[0].first_appearance_scene_number, 1)


class ReimportSameScreenplayTests(unittest.TestCase):
    def test_parsing_the_same_screenplay_twice_is_deterministic(self):
        text = (
            "1. INT. HOUSE - DAY\n\nJOHN\nHi.\n\n"
            "2. EXT. YARD - NIGHT\n\nMARY\nHello.\n"
        )
        first = parse_screenplay(text)
        second = parse_screenplay(text)
        self.assertEqual(first.to_dict(), second.to_dict())


if __name__ == "__main__":
    unittest.main()
