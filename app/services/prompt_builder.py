def build_prompt(shot: dict) -> str:
    assets = shot.get("assets", [])
    characters = [a for a in assets if a["asset_type"] == "דמות"]
    locations = [a for a in assets if a["asset_type"] == "לוקיישן"]
    props = [a for a in assets if a["asset_type"] == "אביזר"]
    wardrobe = [a for a in assets if a["asset_type"] == "לבוש"]

    def block(title, items):
        if not items:
            return f"{title}: not specified."
        return title + ": " + " | ".join(
            f"{i['name']} — {i['description']} Rules: {i['visual_rules']}"
            + (" Identity reference image is attached." if i.get("reference_url") else "")
            for i in items
        )

    return f"""CINEMATIC AI PRODUCTION PROMPT

SHOT
Title: {shot['title']}
Mood: {shot.get('mood') or 'restrained cinematic tension'}
Camera: {shot.get('camera') or 'cinematic composition'}
Lens: {shot.get('lens') or 'natural perspective'}
Movement: {shot.get('movement') or 'one controlled camera movement'}
Lighting: {shot.get('lighting') or 'motivated realistic lighting'}

{block('CHARACTERS', characters)}
{block('LOCATION', locations)}
{block('PROPS', props)}
{block('WARDROBE', wardrobe)}

ACTION
{shot.get('action') or shot.get('notes') or 'Single clear action matching the shot title.'}

FRAMING
Shot type: {shot.get('shot_type') or 'cinematic'}
Camera angle: {shot.get('camera_angle') or 'eye level'}
Composition: {shot.get('composition') or 'clear cinematic composition'}
Color palette: {shot.get('color_palette') or 'coherent with the project look'}

CONTINUITY
Preserve exact identity, wardrobe, props, architecture, lighting direction and color palette.
No face drift, no duplicate people, no malformed hands, no unreadable text, no cyberpunk neon overload.
"""
