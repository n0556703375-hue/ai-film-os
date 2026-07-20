from app.repositories import projects
from app.services.scene_reference_propagation import apply_scene_asset_variants


def _production_bible(shot: dict) -> tuple[str, str]:
    project_id = shot.get("project_id")
    if not project_id:
        return "", ""
    project = projects.get_project(int(project_id)) or {}
    return (
        str(project.get("visual_style") or "").strip(),
        str(project.get("rules") or "").strip(),
    )


def build_prompt(shot: dict) -> str:
    shot = apply_scene_asset_variants(shot)
    visual_style, global_rules = _production_bible(shot)
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

PRODUCTION BIBLE — MANDATORY FOR THIS SHOT
Visual style: {visual_style or 'Use the established project visual language consistently.'}
Global rules: {global_rules or 'No additional project-wide restrictions were specified.'}
These project-wide rules override generic model defaults and must remain visible in foreground, background, reflections, crowds, costumes, dialogue and incidental details.

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
