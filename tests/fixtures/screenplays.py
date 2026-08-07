"""Realistic, original (non-copyrighted) synthetic screenplay fixtures for
the Script Import redesign's Phase 16 coverage. Each constant below is a
full, natural-reading multi-scene excerpt (not a two-line regex probe —
those already live as targeted cases in tests/test_screenplay_parser.py)
covering one specific reliability scenario the product spec calls out by
name. tests/test_screenplay_import_fixtures.py runs each of these through
the parser (and, for the two re-import fixtures, the full service-layer
create -> diff -> approve flow) and asserts the scenario's invariant.

Scenario index (12 fixtures):
  1.  HEBREW_SCREENPLAY               - Hebrew headings/cues end to end
  2.  ENGLISH_SCREENPLAY               - standard Hollywood formatting
  3.  MIXED_LANGUAGE_SCREENPLAY        - Hebrew scene followed by an English scene
  4.  NUMBERED_SCENES_SCREENPLAY       - multi-digit numbered headings
  5.  UNNUMBERED_SCENES_SCREENPLAY     - no leading scene numbers at all
  6.  DIALOGUE_HEAVY_SCREENPLAY        - rapid back-and-forth, parentheticals
  7.  ACTION_HEAVY_SCREENPLAY          - long action paragraph, minimal dialogue
  8.  ALIAS_VARIANTS_SCREENPLAY        - one character's annotation variants
                                         merge; a similar-looking different
                                         character never does
  9.  LOCATION_VARIANTS_SCREENPLAY     - whitespace/case formatting variants
                                         merge; a sub-location stays distinct
  10. MALFORMED_BUT_RECOVERABLE_SCREENPLAY - lowercase, stray page numbers,
                                         colon separators, missing dashes
  11. REIMPORT_BASE_SCREENPLAY         - approved, then re-imported unchanged
  12. REIMPORT_CHANGED_SCREENPLAY      - REIMPORT_BASE_SCREENPLAY with one
                                         scene edited and one scene added
"""

HEBREW_SCREENPLAY = """1. פנים. דירה של נועה - יום

נועה עומדת ליד החלון ומביטה החוצה. הטלפון שלה מצלצל.

נועה:
(עונה בהיסוס)
הלו? כן, זו אני.

מהעבר השני של הקו נשמע קול עמום. נועה מחווירה.

נועה:
מה זאת אומרת נעלם?

2. חוץ. רחוב יעקב - לילה

נועה יוצאת מהבניין בריצה, מעיל פתוח ברוח.

אורי:
נועה! חכי!

נועה עוצרת ומסתובבת.

נועה:
אורי? מה אתה עושה פה?

3. פנים. תחנת המשטרה - יום

נועה ואורי יושבים מול שולחן חקירות. שוטרת נכנסת עם תיק בידה.

השוטרת:
מצאנו את הרכב שלו.
"""

ENGLISH_SCREENPLAY = """1. INT. COFFEE SHOP - MORNING

RACHEL sits alone at a corner table, nursing a cold cup of coffee. The
door chimes. DANIEL enters, scanning the room.

DANIEL
Rachel. I didn't think you'd come.

RACHEL
(not looking up)
Neither did I.

Daniel sits across from her, uncertain.

DANIEL
We need to talk about the contract.

2. EXT. PARKING LOT - DAY

Rachel walks briskly toward her car. Daniel follows.

DANIEL
Wait, just give me five minutes.

RACHEL
You had five years.

3. INT. RACHEL'S OFFICE - AFTERNOON

Rachel sits behind her desk, reviewing documents. Her assistant, MARK,
knocks and enters.

MARK
The Henderson file is ready for your signature.

RACHEL
Leave it on the desk.
"""

MIXED_LANGUAGE_SCREENPLAY = """1. פנים. משרד ההפקה - בוקר

מאיה יושבת מול המחשב, קוראת מסמכים. הטלפון מצלצל.

מאיה:
כן, הלו.

היא שומעת קול מהצד השני ומהנהנת לאט.

מאיה:
אני אבדוק את זה ואחזור אליך.

2. INT. LOS ANGELES OFFICE - DAY

JAKE sits at his desk, laptop open, waiting for the call to connect.
MAYA's face appears on the screen.

JAKE
Maya! Good to finally see you.

MAYA
Jake, we need to discuss the schedule.

JAKE
(leaning back)
I figured you'd say that.
"""

NUMBERED_SCENES_SCREENPLAY = """14. INT. WAREHOUSE - NIGHT

Boxes stacked to the ceiling. A flashlight beam cuts through the dark.

15. EXT. LOADING DOCK - NIGHT

TWO GUARDS stand near a truck, smoking.

GUARD
(quietly)
You hear that?

16. INT. WAREHOUSE - CONTINUOUS

Someone moves between the shelves.
"""

UNNUMBERED_SCENES_SCREENPLAY = """INT. STORAGE ROOM - DAY

ELLA searches through old boxes, coughing from the dust.

EXT. BACKYARD - DAY

Ella sits on the porch steps, a photograph in her hand.

ELLA
(to herself)
There you are.
"""

DIALOGUE_HEAVY_SCREENPLAY = """1. INT. DINER BOOTH - NIGHT

SAM and TOVA sit across from each other, coffee going cold.

SAM
You lied to me.

TOVA
I never lied.

SAM
(raising his voice)
You said you were done with him.

TOVA
(calmly)
I was. Until he called.

SAM
So what now?

TOVA
Now I figure it out. Alone.

SAM
Tova—

TOVA
Don't.
"""

ACTION_HEAVY_SCREENPLAY = """1. EXT. MOUNTAIN TRAIL - DAWN

Mist clings to the rocks. A lone figure, NOA, climbs steadily along the
narrow path, breath visible in the cold air. Below, the valley stretches
out, silent and vast. She stops, checks a torn map against the horizon,
then keeps moving. Loose stones skitter down the slope behind her. She
doesn't look back. The wind picks up, snapping at her jacket. She reaches
a ridge, plants a marker flag in the ground, and looks out over the
valley one last time.

NOA
(to herself)
Almost there.
"""

ALIAS_VARIANTS_SCREENPLAY = """1. INT. CONFERENCE ROOM - DAY

DAVID stands at the head of the table, presenting slides.

DAVID
Our Q3 numbers are up twelve percent.

DANA sits near the door, arms crossed.

DANA
That's not what the board wants to hear.

2. INT. HALLWAY - DAY

DAVID (O.S.)
Tell them I'll have the revised numbers by Friday.

3. EXT. PARKING GARAGE - NIGHT

DAVID waits by his car. DANA approaches from behind.

DAVID
We need to talk.

DANA
I know.
"""

LOCATION_VARIANTS_SCREENPLAY = """1. INT. KITCHEN - DAY

RON chops vegetables at the counter.

RON
Dinner's almost ready.

2. int. kitchen - night

Ron washes dishes, exhausted.

3. INT. HOUSE - KITCHEN - MORNING

Ron sits at the table, reading a letter.

4. INT./EXT. CAR - NIGHT

Ron drives through the rain, headlights cutting through the dark.
"""

MALFORMED_BUT_RECOVERABLE_SCREENPLAY = """--- 1 ---

1. int: office - day

TAMAR sits at her desk, typing quickly.

TAMAR
Almost done.

2

ext.street-night

A car passes slowly. Rain streaks the windshield.

3. INT HALLWAY DAY

TAMAR walks quickly, checking her watch.
"""

REIMPORT_BASE_SCREENPLAY = """1. INT. LAW OFFICE - DAY

ARI reviews a stack of papers at his desk.

ARI
This contract has a problem.

2. EXT. CITY STREET - DAY

ARI walks quickly, phone pressed to his ear.

ARI
Call me back the second you get this.

3. INT. COURTROOM - AFTERNOON

ARI stands before the judge, papers in hand.

ARI
Your honor, we have new evidence.
"""

REIMPORT_CHANGED_SCREENPLAY = """1. INT. LAW OFFICE - DAY

ARI reviews a stack of papers at his desk, visibly worried.

ARI
This contract has a serious problem.

2. EXT. CITY STREET - DAY

ARI walks quickly, phone pressed to his ear.

ARI
Call me back the second you get this.

3. INT. COURTROOM - AFTERNOON

ARI stands before the judge, papers in hand.

ARI
Your honor, we have new evidence.

4. INT. LAW OFFICE - NIGHT

ARI sits alone, staring at the papers.

ARI
(quietly)
We might actually win this.
"""
