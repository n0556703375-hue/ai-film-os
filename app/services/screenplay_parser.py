"""Deterministic screenplay structural parser.

This module performs the structural split of a screenplay — scene
boundaries, block classification (action/dialogue/parenthetical/transition),
and character/location extraction — using plain-text pattern matching only.
No LLM call is involved anywhere in this file.

This is a deliberate architectural choice (see the Script Import redesign):
asking a language model to reconstruct an entire screenplay's structure from
scratch is unreliable — it can reorder, merge, drop, or invent scenes, and
there is no way to verify its output against the source. A regex/heuristic
parser over standard screenplay formatting conventions is slower to extend
but its behavior is enumerable, testable, and — critically — provably
order-preserving and non-inventive: every character of the source screenplay
ends up in exactly one scene's `raw_scene_text`, scenes are emitted in
strict source order, and nothing is classified with unwarranted certainty
(low-confidence classifications are flagged, never silently guessed).

AI enrichment (narrative synopsis, thematic notes) is intentionally NOT
part of this module. It is a separate, optional, best-effort layer that
may run over this parser's output later — it must never be able to alter
scene boundaries, order, or block classification.

Accessory/prop extraction is the one exception: it is deterministic and
quote-driven, mirroring the character/location extraction below — a prop
is only ever recognized because the screenwriter explicitly set it off in
quotation marks inside an action line (a common screenwriting convention
for flagging a significant object), never guessed from ordinary nouns.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


# --- Screenplay formatting vocabulary --------------------------------------

_INT_EXT_ALTERNATION = "|".join([
    r"INT\.?\s*/\s*EXT\.?",
    r"EXT\.?\s*/\s*INT\.?",
    r"I\s*/\s*E\.?",
    r"INT\.?",
    r"EXT\.?",
    r"פנים\s*/\s*חוץ\.?",
    r"חוץ\s*/\s*פנים\.?",
    r"פנים\.?",
    r"חוץ\.?",
])

_HEADING_RE = re.compile(
    r"^\s*(?:(?P<number>\d+)[.\)]\s*)?"
    r"(?P<intext>" + _INT_EXT_ALTERNATION + r")"
    r"[\s.\-–—:]*"
    r"(?P<rest>.*?)\s*$",
    re.IGNORECASE,
)

_INT_EXT_CANONICAL = {
    "int": "INT", "int.": "INT",
    "ext": "EXT", "ext.": "EXT",
    "פנים": "פנים", "פנים.": "פנים",
    "חוץ": "חוץ", "חוץ.": "חוץ",
}


def _canonical_int_ext(raw: str) -> str:
    key = raw.strip().lower()
    if key in _INT_EXT_CANONICAL:
        return _INT_EXT_CANONICAL[key]
    # Combined forms (INT/EXT, EXT/INT, I/E, פנים/חוץ, חוץ/פנים) — normalize
    # to one stable label regardless of slash spacing, per-half periods, or
    # original order (e.g. "INT./EXT." and "EXT/INT" both become "INT/EXT").
    collapsed = re.sub(r"[\s.]*", "", key)
    if collapsed in {"int/ext", "ext/int", "i/e"}:
        return "INT/EXT"
    if collapsed in {"פנים/חוץ", "חוץ/פנים"}:
        return "פנים/חוץ"
    return raw.strip()


_TIME_OF_DAY_KEYWORDS = {
    "day", "night", "morning", "evening", "dawn", "dusk", "afternoon",
    "continuous", "later", "moments later", "same time", "sunset", "sunrise",
    "יום", "לילה", "בוקר", "ערב", "שחר", "דמדומים", "צהריים", "רציף",
    "מאוחר יותר", "באותו זמן", "בו ברגע", "שקיעה", "זריחה",
}

_TRANSITION_PHRASES = {
    "cut to:", "cut to", "fade in:", "fade in", "fade out.", "fade out",
    "fade to black.", "fade to black", "dissolve to:", "dissolve to",
    "smash cut to:", "smash cut to", "match cut to:", "match cut to",
    "jump cut to:", "jump cut to", "time cut to:", "time cut to",
    "עבור ל:", "עבור ל", "נמס ל:", "נמס ל", "חיתוך ל:", "חיתוך ל",
    "קאט ל:", "קאט ל", "דהייה פנימה:", "דהייה פנימה", "דהייה החוצה.",
    "דהייה החוצה", "דהייה לשחור.", "דהייה לשחור",
}

_CUE_ANNOTATION_RE = re.compile(r"\(([^()]*)\)\s*$")
_INLINE_CUE_SPLIT_RE = re.compile(r"^(?P<name>[^\n:]{1,40}?):\s+(?P<rest>\S.*)$")
_HEBREW_LETTER_RE = re.compile(r"[֐-׿]")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")

MAX_CUE_LENGTH = 40

# Matches a quoted span using any of the quote-mark conventions a Hebrew or
# English screenplay might use for flagging a prop: straight double quotes,
# curly double quotes, or the Hebrew gershayim mark (״). Each alternative
# pins its own delimiter on both sides so mismatched quote styles never pair
# up across unrelated text.
_QUOTED_PROP_RE = re.compile(
    r'"([^"\n]{1,40})"|“([^”\n]{1,40})”|״([^״\n]{1,40})״'
)


# --- Data model --------------------------------------------------------------

@dataclass
class ContentBlock:
    order: int
    block_type: str  # action|dialogue|parenthetical|transition|other
    raw_text: str
    character_name: str = ""
    parenthetical: str = ""
    confidence: str = "high"  # high|low

    def to_dict(self) -> dict:
        return {
            "order": self.order,
            "block_type": self.block_type,
            "raw_text": self.raw_text,
            "character_name": self.character_name,
            "parenthetical": self.parenthetical,
            "confidence": self.confidence,
        }


@dataclass
class ParsedScene:
    scene_number: int
    original_heading: str
    normalized_heading: str
    int_ext: str
    location: str
    time_of_day: str
    raw_scene_text: str
    blocks: list[ContentBlock] = field(default_factory=list)
    participants: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scene_number": self.scene_number,
            "original_heading": self.original_heading,
            "normalized_heading": self.normalized_heading,
            "int_ext": self.int_ext,
            "location": self.location,
            "time_of_day": self.time_of_day,
            "raw_scene_text": self.raw_scene_text,
            "blocks": [b.to_dict() for b in self.blocks],
            "participants": list(self.participants),
        }


@dataclass
class ParsedEntity:
    canonical_name: str
    aliases: list[str]
    first_appearance_scene_number: int

    def to_dict(self) -> dict:
        return {
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases),
            "first_appearance_scene_number": self.first_appearance_scene_number,
        }


@dataclass
class ParseWarning:
    category: str
    message: str
    scene_number: int | None = None

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "message": self.message,
            "scene_number": self.scene_number,
        }


@dataclass
class ParsedScreenplay:
    scenes: list[ParsedScene]
    characters: list[ParsedEntity]
    locations: list[ParsedEntity]
    props: list[ParsedEntity]
    warnings: list[ParseWarning]

    def to_dict(self) -> dict:
        return {
            "scenes": [s.to_dict() for s in self.scenes],
            "characters": [c.to_dict() for c in self.characters],
            "locations": [loc.to_dict() for loc in self.locations],
            "props": [p.to_dict() for p in self.props],
            "warnings": [w.to_dict() for w in self.warnings],
        }


class ScreenplayParseError(ValueError):
    """Raised only for input that cannot be parsed at all (e.g. empty text)."""


# --- Line normalization -------------------------------------------------------

def _normalize_line(line: str) -> str:
    """Collapse repeated internal whitespace and strip. Preserves content."""
    return re.sub(r"[ \t]+", " ", line.strip())


def _is_page_break_artifact(line: str) -> bool:
    """Lines that are pagination noise, not screenplay content."""
    stripped = line.strip()
    if not stripped:
        return False
    if re.fullmatch(r"-{2,}\s*(?:page\s*)?\d*\s*-{2,}", stripped, re.IGNORECASE):
        return True
    if re.fullmatch(r"\d{1,4}\.?", stripped):
        # A bare page number. Distinguished from a numbered scene heading
        # because a heading always carries an INT/EXT token on the same line.
        return True
    return False


_WRAPPED_LEADING_MARK_RE = re.compile(r"^([.:])(?=[A-Za-z֐-׿])")


def _reattach_wrapped_leading_punctuation(lines: list[str]) -> list[str]:
    """Undo a common RTL copy-paste artifact: a period or colon that
    belongs at the *end* of one visual line instead lands on the *start*
    of the next — a source page rendering as "...רגע\n.דבורה:\n..."
    instead of "...רגע.\nדבורה:\n...", or "...הודעה\n:תשע שעות...\n..."
    instead of "...הודעה:\nתשע שעות...\n...". Left alone, either breaks
    the previous line's own end-of-sentence/lead-in punctuation check
    *and* glues a stray leading mark onto the next line's cue name —
    fragmenting one real speaker into two entities (period case) or
    turning a long narration line into a fake short cue by stranding its
    colon on the wrong side of the line break (colon case). Only
    triggers when the mark is immediately followed by a letter (no
    space) — a genuine list marker like ". " or ".1" is left untouched —
    and only when the immediately preceding line is non-blank and not
    already terminated.
    """
    fixed = list(lines)
    for index, line in enumerate(fixed):
        match = _WRAPPED_LEADING_MARK_RE.match(line)
        if not match:
            continue
        mark = match.group(1)
        previous_index = index - 1
        if previous_index < 0:
            continue
        previous_line = fixed[previous_index]
        if not previous_line or re.search(r"[.!?:]$", previous_line):
            continue
        fixed[previous_index] = previous_line + mark
        fixed[index] = line[1:]
    return fixed


def _split_lines(screenplay: str) -> list[str]:
    lines = screenplay.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    result = []
    for line in lines:
        if _is_page_break_artifact(line):
            continue
        result.append(_normalize_line(line))
    return _reattach_wrapped_leading_punctuation(result)


def _has_more_content(lines: list[str], from_index: int) -> bool:
    return any(line for line in lines[from_index:])


# --- Heading parsing -----------------------------------------------------------

def _match_heading(line: str) -> re.Match | None:
    if not line:
        return None
    return _HEADING_RE.match(line)


def _split_location_and_time(rest: str) -> tuple[str, str]:
    if not rest:
        return "", ""
    for separator in ("—", "–", "-"):
        if separator in rest:
            head, _, tail = rest.rpartition(separator)
            head = head.strip(" .-–—")
            tail_key = tail.strip(" .-–—").lower()
            if tail_key in _TIME_OF_DAY_KEYWORDS and head:
                return head, tail.strip(" .-–—")
    return rest.strip(" .-–—"), ""


def _parse_heading(line: str) -> dict | None:
    match = _match_heading(line)
    if not match:
        return None
    int_ext = _canonical_int_ext(match.group("intext"))
    rest = match.group("rest") or ""
    location, time_of_day = _split_location_and_time(rest)
    normalized = f"{int_ext}. {location}".strip()
    if time_of_day:
        normalized = f"{normalized} - {time_of_day}"
    return {
        "int_ext": int_ext,
        "location": location,
        "time_of_day": time_of_day,
        "normalized_heading": normalized,
    }


# --- Block-level classification -------------------------------------------------

def _looks_like_transition(text: str) -> bool:
    key = text.strip().lower()
    return key in _TRANSITION_PHRASES


def _looks_like_parenthetical(text: str) -> bool:
    stripped = text.strip()
    return (
        len(stripped) >= 2
        and stripped[0] in "(("
        and stripped[-1] in "))"
    )


def _strip_cue_annotation(text: str) -> tuple[str, str]:
    """Split a character cue line into (name, trailing annotation).

    Also strips stray leading punctuation (a period, comma, or dash) from
    the name. This is not cosmetic: copy-pasting Hebrew (RTL) text out of
    a PDF frequently displaces a sentence-ending period onto the *start*
    of the next visual line — e.g. a source page rendering as
    "...רגע\n.דבורה:\n..." — which would otherwise produce ".דבורה" as a
    distinct character from every clean "דבורה" cue elsewhere, silently
    fragmenting one real speaker into two entities. raw_text is left
    untouched; this only affects the extracted name used for grouping.
    """
    working = text.strip().rstrip(":").strip()
    working = working.lstrip(".,;:־-").strip()
    annotation = ""
    match = _CUE_ANNOTATION_RE.search(working)
    if match:
        annotation = match.group(1).strip()
        working = working[: match.start()].strip()
    return working, annotation


# Hebrew has no case distinction to signal "this line is a name" the way
# English's ALL-CAPS convention does, so a trailing colon is the only
# structural signal available — but plenty of ordinary action lines also
# end with a colon to introduce an on-screen message, a list, or a sign
# ("על המסך:", "היא פותחת שלוש שכבות:"). Real character cues in practice
# are short (a name, or a short descriptive role like "קול האטלס" or
# "רובוט ניקוי" — never more than two words in practice); a colon-
# terminated line that is longer, opens with a preposition or pronoun
# (which a name never does), or contains a digit (a name never does
# either — a bare digit here is a timestamp or page number that a PDF
# export fused onto the adjacent text with no space) is a narration
# lead-in, not a cue.
MAX_HEBREW_CUE_WORDS = 2
_HEBREW_CUE_DISQUALIFYING_FIRST_WORDS = {
    "על", "אל", "מול", "ליד", "אצל", "עם", "בתוך", "מתחת", "מתחתיה", "מעל",
    "אחרי", "לפני", "היא", "הוא", "הם", "הן", "כש", "אם", "כי",
    "אבל", "אז", "גם", "רק", "כל", "בסוף", "אזהרה", "ספירה", "הספירה",
    "מתחתיו",
    # A scene/act heading fragmented across a mid-word PDF line-wrap
    # ("סצנה י״ז — הדרך לארכיו" / "ן..." on the next line, or "חלק ד׳ —
    # ...") leaves the heading fragment unmatched by _match_heading;
    # without this, the leftover text reads as a short standalone line
    # and gets guessed as a cue. A character is never literally named
    # "Scene" or "Part".
    "סצנה", "חלק",
    # "the screen" / "the screen shows" as its own line or short phrase —
    # a display surface is never a speaking character's name.
    "המסך", "מסך",
    # Generic system/output labels that lead in to displayed or read-aloud
    # text ("Result:", "Options:", "List of names:", "Typing:", "In the
    # transit center:") — the same lead-in pattern as "the screen:", just
    # with a different label noun. Never a speaking character's name.
    "תוצאה", "אפשרויות", "רשימת", "מקלידה", "במרכז",
    # "not" / "no" as a sentence-opening negation ("Not final. But it
    # looks...") and "the door" as a physical object — never how a real
    # character's name begins.
    "לא", "הדלת",
}
_DIGIT_RE = re.compile(r"\d")


def _has_digit_or_disqualifying_first_word(name: str) -> bool:
    if _DIGIT_RE.search(name):
        return True
    words = name.split()
    return bool(words) and words[0] in _HEBREW_CUE_DISQUALIFYING_FIRST_WORDS


def _looks_like_hebrew_cue_colon_line(name: str) -> bool:
    words = name.split()
    if not words or len(words) > MAX_HEBREW_CUE_WORDS:
        return False
    return not _has_digit_or_disqualifying_first_word(name)


def _looks_like_character_cue(line: str, has_more_content: bool) -> tuple[bool, str]:
    """Return (is_cue, confidence) for a single candidate line.

    confidence is only meaningful when is_cue is True. A cue can never be
    the last content in a scene — there must be something (dialogue, at
    minimum a parenthetical) for it to introduce.
    """
    if not has_more_content:
        return False, ""
    if not line or len(line) > MAX_CUE_LENGTH:
        return False, ""
    if _match_heading(line) or _looks_like_transition(line):
        return False, ""
    if _looks_like_parenthetical(line):
        return False, ""

    name, _annotation = _strip_cue_annotation(line)
    if not name:
        return False, ""

    has_hebrew = bool(_HEBREW_LETTER_RE.search(name))
    has_latin = bool(_LATIN_LETTER_RE.search(name))
    ends_with_colon = line.rstrip().endswith(":")

    if has_latin and not has_hebrew:
        # Standard screenplay convention: character cues are ALL CAPS.
        letters_only = re.sub(r"[^A-Za-z]", "", name)
        if letters_only and letters_only == letters_only.upper():
            return True, "high"
        return False, ""

    if has_hebrew:
        if ends_with_colon:
            if _looks_like_hebrew_cue_colon_line(name):
                return True, "high"
            # A colon-terminated line that's too long, or opens with a
            # preposition/pronoun, reads as narration introducing an
            # on-screen message or list rather than a speaker's name —
            # never guessed as a cue at all, so it folds into action text
            # instead of fabricating dialogue for a non-existent speaker.
            return False, ""
        # No case distinction in Hebrew and no colon convention used — a
        # short standalone line ahead of more text is a plausible cue, but
        # this is a real guess, not a confirmed structural signal. A real
        # cue is a name (at most a couple of words); anything longer is an
        # action sentence that merely lacks trailing punctuation, not a
        # speaker. Still never guessed at all when it opens with the same
        # disqualifying words as the colon case (e.g. a fragmented "סצנה
        # ..." heading left behind by a mid-word PDF line-wrap).
        words = name.split()
        if (
            words
            and len(words) <= MAX_HEBREW_CUE_WORDS
            and len(name) <= 25
            and not re.search(r"[.!?]$", name)
            and not _has_digit_or_disqualifying_first_word(name)
        ):
            return True, "low"
        return False, ""

    return False, ""


def _split_inline_dialogue_cue(line: str) -> tuple[str, str] | None:
    """Detect a same-line "NAME: dialogue" cue and split it into
    (character_name, dialogue_text).

    This is a distinct convention from the standard screenplay cue (a name
    alone on its own line, dialogue below it): some scripts — notably
    stage-play/transcript-style pastes — put the speaker and their line on
    one line, colon-separated. Without this, every such line falls through
    as plain action text and no character is ever recognized. The name
    portion is validated with the exact same short-name heuristic already
    trusted for the standalone colon-terminated cue (see
    ``_looks_like_hebrew_cue_colon_line``), so an action line that merely
    contains a mid-sentence colon (a time, an on-screen message lead-in,
    a list) is rejected the same way it already would be there.
    """
    match = _INLINE_CUE_SPLIT_RE.match(line)
    if not match:
        return None
    if _match_heading(line) or _looks_like_transition(line):
        return None

    name = match.group("name").strip()
    rest = match.group("rest").strip()
    if not name or not rest:
        return None

    has_hebrew = bool(_HEBREW_LETTER_RE.search(name))
    has_latin = bool(_LATIN_LETTER_RE.search(name))

    if has_latin and not has_hebrew:
        letters_only = re.sub(r"[^A-Za-z]", "", name)
        if letters_only and letters_only == letters_only.upper():
            return name, rest
        return None

    if has_hebrew and _looks_like_hebrew_cue_colon_line(name):
        return name, rest

    return None


def _classify_lines(lines: list[str]) -> list[ContentBlock]:
    """Classify a scene's content lines into ordered blocks.

    Deliberately operates line-by-line rather than on blank-line-separated
    paragraphs: real plain-text screenplay pastes commonly have NO blank
    line between a character cue, its parenthetical, and its dialogue
    (they're visually distinguished by indentation/capitalization in a
    real screenplay layout, which plain text does not preserve) — grouping
    by blank lines first would merge a cue and its dialogue into a single
    action paragraph and silently lose the distinction entirely.
    """
    blocks: list[ContentBlock] = []
    order = 0
    pending_action: list[str] = []
    n = len(lines)
    index = 0

    def flush_action() -> None:
        nonlocal order
        text = "\n".join(pending_action).strip()
        if text:
            blocks.append(ContentBlock(order=order, block_type="action", raw_text=text))
            order += 1
        pending_action.clear()

    while index < n:
        line = lines[index]

        if not line:
            flush_action()
            index += 1
            continue

        if _looks_like_transition(line):
            flush_action()
            blocks.append(ContentBlock(order=order, block_type="transition", raw_text=line))
            order += 1
            index += 1
            continue

        has_more = _has_more_content(lines, index + 1)
        is_cue, confidence = _looks_like_character_cue(line, has_more)
        if is_cue:
            flush_action()
            character_name, _annotation = _strip_cue_annotation(line)
            index += 1
            while index < n and not lines[index]:
                index += 1

            leading_parenthetical = ""
            if index < n and _looks_like_parenthetical(lines[index]):
                leading_parenthetical = lines[index].strip()
                index += 1
                while index < n and not lines[index]:
                    index += 1

            dialogue_lines: list[str] = []
            while index < n and lines[index]:
                candidate = lines[index]
                # Stop collecting as soon as the next line is itself a new
                # structural boundary (cue, transition, heading) — real
                # screenplay text pasted from some PDF exports has no blank
                # line between one speaker's line and the next speaker's
                # cue, and without this check the whole exchange gets
                # silently swallowed into the first speaker's dialogue,
                # misattributing every line after it.
                if _match_heading(candidate) or _looks_like_transition(candidate):
                    break
                candidate_is_cue, _candidate_confidence = _looks_like_character_cue(
                    candidate, _has_more_content(lines, index + 1)
                )
                if candidate_is_cue or _split_inline_dialogue_cue(candidate):
                    break
                dialogue_lines.append(candidate)
                index += 1

            if dialogue_lines:
                blocks.append(ContentBlock(
                    order=order,
                    block_type="dialogue",
                    raw_text="\n".join(dialogue_lines).strip(),
                    character_name=character_name,
                    parenthetical=leading_parenthetical,
                    confidence=confidence,
                ))
                order += 1
            elif leading_parenthetical:
                # Cue + parenthetical with nothing after it (rare, but the
                # parenthetical must not be silently dropped).
                blocks.append(ContentBlock(
                    order=order,
                    block_type="parenthetical",
                    raw_text=leading_parenthetical,
                    character_name=character_name,
                    confidence=confidence,
                ))
                order += 1
            continue

        inline_cue = _split_inline_dialogue_cue(line)
        if inline_cue:
            flush_action()
            character_name, first_dialogue_line = inline_cue
            index += 1
            dialogue_lines = [first_dialogue_line]
            while index < n and lines[index]:
                candidate = lines[index]
                # Same stopping rule as the standalone-cue case above: a new
                # speaker's line (of either cue style) or a new structural
                # boundary ends this speaker's turn rather than being
                # swallowed into it.
                if _match_heading(candidate) or _looks_like_transition(candidate):
                    break
                candidate_is_cue, _candidate_confidence = _looks_like_character_cue(
                    candidate, _has_more_content(lines, index + 1)
                )
                if candidate_is_cue or _split_inline_dialogue_cue(candidate):
                    break
                dialogue_lines.append(candidate)
                index += 1

            blocks.append(ContentBlock(
                order=order,
                block_type="dialogue",
                raw_text="\n".join(dialogue_lines).strip(),
                character_name=character_name,
                confidence="high",
            ))
            order += 1
            continue

        if _looks_like_parenthetical(line):
            flush_action()
            blocks.append(ContentBlock(order=order, block_type="parenthetical", raw_text=line))
            order += 1
            index += 1
            continue

        pending_action.append(line)
        index += 1

    flush_action()
    return blocks


def _extract_quoted_props(text: str) -> list[str]:
    """Return every quoted span in an action line, in source order.

    Only action text is scanned by the caller — dialogue quoting a line of
    speech (also delimited by quote marks in plain-text pastes) is never
    mistaken for a prop callout.
    """
    props = []
    for match in _QUOTED_PROP_RE.finditer(text):
        span = next(group for group in match.groups() if group is not None).strip()
        if span:
            props.append(span)
    return props


# --- Canonicalization -----------------------------------------------------------

def _normalize_key(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", folded).strip()


def _canonicalize_entities(
    occurrences: list[tuple[str, int]],
) -> list[ParsedEntity]:
    """Group raw strings by an exact normalized key — never fuzzy-merges.

    ``occurrences`` is a list of (raw_text, scene_number) in source order.
    Two raw variants are only ever considered the same entity when they are
    identical after case/whitespace normalization; anything else (a first
    name vs. a full name, a genuinely different spelling) is kept separate
    rather than risked being merged incorrectly.
    """
    groups: dict[str, dict] = {}
    order: list[str] = []
    for raw, scene_number in occurrences:
        raw = raw.strip()
        if not raw:
            continue
        key = _normalize_key(raw)
        if not key:
            continue
        if key not in groups:
            groups[key] = {"counts": {}, "first_scene": scene_number}
            order.append(key)
        counts = groups[key]["counts"]
        counts[raw] = counts.get(raw, 0) + 1
        groups[key]["first_scene"] = min(groups[key]["first_scene"], scene_number)

    entities = []
    for key in order:
        counts = groups[key]["counts"]
        canonical = max(counts.items(), key=lambda item: (item[1], -len(item[0])))[0]
        aliases = sorted(name for name in counts if name != canonical)
        entities.append(ParsedEntity(
            canonical_name=canonical,
            aliases=aliases,
            first_appearance_scene_number=groups[key]["first_scene"],
        ))
    return entities


# --- Top-level entry point ------------------------------------------------------

def parse_screenplay(screenplay_text: str) -> ParsedScreenplay:
    if not screenplay_text or not screenplay_text.strip():
        raise ScreenplayParseError("empty_script")

    lines = _split_lines(screenplay_text)
    warnings: list[ParseWarning] = []

    # Locate every heading line's index to split into scenes up front —
    # this is what makes order preservation structural rather than
    # incidental: scenes are literally slices of the original line list in
    # their original order, nothing is ever re-sorted or reconstructed.
    heading_indices: list[tuple[int, dict, str]] = []
    for index, line in enumerate(lines):
        parsed = _parse_heading(line)
        if parsed:
            heading_indices.append((index, parsed, line))

    if not heading_indices:
        warnings.append(ParseWarning(
            category="no_scene_headings_detected",
            message="לא זוהו כותרות סצנה (INT./EXT.) בתסריט. כל הטקסט נשמר כסצנה אחת לבדיקה.",
        ))
        segments = [(0, {"int_ext": "", "location": "", "time_of_day": "", "normalized_heading": ""}, "", lines)]
    else:
        segments = []
        for position, (start, heading, original_line) in enumerate(heading_indices):
            content_start = start + 1
            content_end = heading_indices[position + 1][0] if position + 1 < len(heading_indices) else len(lines)
            segments.append((start, heading, original_line, lines[content_start:content_end]))

    scenes: list[ParsedScene] = []
    character_occurrences: list[tuple[str, int]] = []
    location_occurrences: list[tuple[str, int]] = []
    prop_occurrences: list[tuple[str, int]] = []

    for scene_number, (_start, heading, original_line, content_lines) in enumerate(segments, start=1):
        blocks = _classify_lines(content_lines)

        scene_characters: list[str] = []
        for block in blocks:
            if block.block_type == "dialogue" and block.character_name:
                character_occurrences.append((block.character_name, scene_number))
                if block.character_name not in scene_characters:
                    scene_characters.append(block.character_name)
            if block.block_type == "action":
                for prop_name in _extract_quoted_props(block.raw_text):
                    prop_occurrences.append((prop_name, scene_number))
            if block.confidence == "low":
                warnings.append(ParseWarning(
                    category="low_confidence_classification",
                    message=f"סיווג לא ודאי בסצנה {scene_number}: \"{block.raw_text[:60]}\"",
                    scene_number=scene_number,
                ))

        if heading["location"]:
            location_occurrences.append((heading["location"], scene_number))

        raw_scene_text = "\n".join([original_line, *content_lines]).strip()

        scenes.append(ParsedScene(
            scene_number=scene_number,
            original_heading=original_line,
            normalized_heading=heading["normalized_heading"],
            int_ext=heading["int_ext"],
            location=heading["location"],
            time_of_day=heading["time_of_day"],
            raw_scene_text=raw_scene_text,
            blocks=blocks,
            participants=scene_characters,
        ))

    characters = _canonicalize_entities(character_occurrences)
    locations = _canonicalize_entities(location_occurrences)
    props = _canonicalize_entities(prop_occurrences)

    validate_scene_order(scenes)

    return ParsedScreenplay(
        scenes=scenes,
        characters=characters,
        locations=locations,
        props=props,
        warnings=warnings,
    )


def validate_scene_order(scenes: list[ParsedScene]) -> None:
    """Assert the critical Phase-4 invariant: no missing/duplicated/reordered scenes.

    This is structurally guaranteed by construction (scenes are built by a
    single forward pass over the source lines), but is checked explicitly
    so a future change to the parser cannot silently violate it.
    """
    expected = list(range(1, len(scenes) + 1))
    actual = [scene.scene_number for scene in scenes]
    if actual != expected:
        raise ScreenplayParseError("scene_order_invariant_violated")
