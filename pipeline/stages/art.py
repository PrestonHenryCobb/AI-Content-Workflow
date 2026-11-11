"""Stage 5: one source image per "still" shot.

Flux Schnell via fal.ai when FAL_KEY is set and the image budget allows; otherwise a
procedural low-poly frame from the closest scene template. Either way the PS2 pass in
the compositor gives the final look, so both sources match the channel style.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from pipeline.budget import BudgetExceeded, Governor
from pipeline.scenes import render_frame, template_for_prompt
from pipeline.schemas import Script, Shot

FAL_URL = "https://fal.run/fal-ai/flux/schnell"
UA = "cold-save-pipeline/0.1 (+python-urllib)"


def style_prompt(shot: Shot, style: dict[str, object]) -> str:
    return f"{style.get('image_prompt_prefix', '')}, {shot.prompt}"


def flux(prompt: str, negative: str, seed: int, key: str, out: Path) -> None:  # pragma: no cover
    body = json.dumps({
        "prompt": f"{prompt}. Avoid: {negative}", "image_size": "portrait_16_9",
        "num_inference_steps": 4, "num_images": 1, "enable_safety_checker": True, "seed": seed,
    }).encode()
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json",
               "Accept": "application/json", "User-Agent": UA}
    req = urllib.request.Request(FAL_URL, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            url = json.loads(r.read())["images"][0]["url"]
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode("utf-8", "replace")
        raise RuntimeError(f"fal HTTP {e.code}: {detail}") from e
    img = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(img, timeout=120) as r:
        out.write_bytes(r.read())


def procedural_still(shot: Shot, seed: int, out: Path) -> None:
    template = shot.template if shot.template != "none" else template_for_prompt(shot.prompt)
    render_frame(template, "push_in", 0.3, 0, 576, 1024, seed).save(out)


def make_stills(script: Script, out_dir: Path, gov: Governor, style: dict[str, object],
                usd_per_image: float, offline: bool = False, seed: int = 1) -> dict[str, str]:
    """Returns {shot_id: source} where source is 'flux' or 'procedural'."""
    out_dir.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("FAL_KEY", "")
    sources: dict[str, str] = {}
    for k, shot in enumerate(script.shots):
        if shot.kind != "still":
            continue
        path = out_dir / f"{shot.id}.png"
        if path.exists():
            sources[shot.id] = "cached"
            continue
        if key and not offline:
            try:
                gov.authorize("images", usd_per_image)
                flux(style_prompt(shot, style), str(style.get("negative_prompt", "")),
                     seed * 1000 + k, key, path)
                gov.charge("images", "art", usd_per_image, meta={"shot": shot.id})
                with Image.open(path) as im:
                    im.verify()
                sources[shot.id] = "flux"
                continue
            except BudgetExceeded:
                pass
            except Exception as e:  # noqa: BLE001 - provider down: fall back, never stall
                sources[f"{shot.id}_error"] = str(e)[:200]
        procedural_still(shot, seed * 1000 + k, path)
        sources[shot.id] = "procedural"
    return sources
