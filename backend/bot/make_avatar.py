"""Render the Meet camera cards from the approved Wilco mascot.

Uses the bot's existing Playwright dependency. Run from any directory:
    python backend/bot/make_avatar.py
For a local installed Chrome instead of bundled Chromium:
    python backend/bot/make_avatar.py --channel chrome

The source PNG is preserved; the browser lays out the camera card. The checked-in
frames ship in the bot image, so generation is not needed at runtime.
"""
import argparse
import base64
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "assets"
SOURCE = OUT / "wilco-mascot-v1.png"


def markup(speaking: bool) -> str:
    mascot = base64.b64encode(SOURCE.read_bytes()).decode("ascii")
    # Same composition in both frames; the existing camera switches frames at
    # 5 fps. Only the small voice bars change, keeping the character steady.
    bars = (9, 20, 27, 17, 10) if speaking else (5, 9, 13, 9, 5)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; width: 640px; height: 360px; overflow: hidden;
        background: #fcfaf8; color: #24262c; font-family: Arial, sans-serif; }}
      .wash {{ position: absolute; inset: 0; background: radial-gradient(ellipse at 50% 42%, #e6d9ef 0%, #eff1f5 35%, #fcfaf8 67%); }}
      img {{ position: absolute; height: 255px; width: 220px; object-fit: contain; left: 210px; top: 23px; }}
      .name {{ position: absolute; top: 290px; left: 0; width: 640px; text-align: center; font-size: 20px; font-weight: 600; }}
      .name span {{ color: #65616c; font-size: 14px; font-weight: 400; }}
      .voice {{ position: absolute; left: 443px; top: 133px; display: flex; align-items: center; gap: 4px; height: 32px; }}
      .voice i {{ display: block; width: 4px; border-radius: 3px; background: #126b75; }}
    </style></head><body><div class="wash"></div>
      <img src="data:image/png;base64,{mascot}" alt="Wilco mascot">
      <div class="voice" aria-hidden="true">{''.join(f'<i style="height:{h}px"></i>' for h in bars)}</div>
      <div class="name">Wilco <span>· Meeting assistant</span></div>
    </body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", help="Optional installed browser channel, e.g. chrome")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(**({"channel": args.channel} if args.channel else {}))
        page = browser.new_page(viewport={"width": 640, "height": 360}, device_scale_factor=2)
        for speaking in (False, True):
            page.set_content(markup(speaking))
            page.evaluate("async () => { await document.fonts.ready; await document.images[0].decode(); }")
            target = OUT / ("avatar_speaking.png" if speaking else "avatar_idle.png")
            page.screenshot(path=str(target))
            print("wrote", target)
        browser.close()


if __name__ == "__main__":
    main()
