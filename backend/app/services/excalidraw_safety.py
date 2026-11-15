"""Validate an Excalidraw drawing saved on a diagram node.

Only plain drawing elements are kept: no embedded images, iframes or links,
and no app state beyond what the editor needs. The drawing is bounded so board
revisions stay small.
"""
import json

MAX_ELEMENTS = 1500
MAX_BYTES = 400_000

ALLOWED_TYPES = {"rectangle", "ellipse", "diamond", "arrow", "line", "freedraw", "text", "frame"}
# Element keys Excalidraw needs to restore a drawing. Anything else is dropped.
ALLOWED_KEYS = {
    "id", "type", "x", "y", "width", "height", "angle", "strokeColor", "backgroundColor",
    "fillStyle", "strokeWidth", "strokeStyle", "roughness", "opacity", "groupIds", "frameId",
    "roundness", "seed", "version", "versionNonce", "isDeleted", "boundElements", "updated",
    "locked", "points", "lastCommittedPoint", "startBinding", "endBinding", "startArrowhead",
    "endArrowhead", "elbowed", "fixedSegments", "startIsSpecial", "endIsSpecial", "pressures",
    "simulatePressure", "text", "originalText", "fontSize", "fontFamily", "textAlign",
    "verticalAlign", "containerId", "autoResize", "lineHeight", "baseline", "name", "index",
}


def clean_scene(scene) -> dict:
    """Return {"elements": [...]} with only safe drawing data, or raise ValueError."""
    if not isinstance(scene, dict) or not isinstance(scene.get("elements"), list):
        raise ValueError("The drawing must contain a list of elements")
    elements = []
    for element in scene["elements"]:
        if not isinstance(element, dict):
            raise ValueError("The drawing has an invalid element")
        if element.get("isDeleted"):
            continue
        if element.get("type") not in ALLOWED_TYPES:
            raise ValueError("Drawings can't contain images, embeds or links")
        clean = {key: value for key, value in element.items() if key in ALLOWED_KEYS}
        clean["link"] = None
        elements.append(clean)
    if len(elements) > MAX_ELEMENTS:
        raise ValueError("The drawing is too large; split it into smaller diagrams")
    result = {"elements": elements}
    if len(json.dumps(result, separators=(",", ":"))) > MAX_BYTES:
        raise ValueError("The drawing is too large; split it into smaller diagrams")
    return result
