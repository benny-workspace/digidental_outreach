"""Build the app icon and web logo from assets\\logo.png.

Drop a new square PNG at assets\\logo.png and run this to refresh every
branded asset:

    python scripts\\make_icon.py

Produces:
    assets\\outreach_studio.ico   Windows shortcut and taskbar icon
    assets\\logo_transparent.png  white background knocked out, for the app
"""

import sys
from pathlib import Path

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
ASSETS = BASE_DIR / "assets"
SOURCE = ASSETS / "logo.png"
ICO_OUT = ASSETS / "outreach_studio.ico"
PNG_OUT = ASSETS / "logo_transparent.png"

ICO_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
WHITE_CUTOFF = 235  # pixels brighter than this become transparent


def knock_out_white(image):
    """Make the near-white background transparent, keep the dark artwork."""
    image = image.convert("RGBA")
    pixels = image.getdata()
    cleaned = []
    for r, g, b, a in pixels:
        if r >= WHITE_CUTOFF and g >= WHITE_CUTOFF and b >= WHITE_CUTOFF:
            cleaned.append((r, g, b, 0))
        else:
            cleaned.append((r, g, b, a))
    image.putdata(cleaned)
    return image


def main():
    if not SOURCE.exists():
        print(f"Missing {SOURCE}. Put a square PNG there and run this again.")
        sys.exit(1)
    image = Image.open(SOURCE)
    transparent = knock_out_white(image)
    transparent.save(PNG_OUT, format="PNG")
    print(f"Wrote {PNG_OUT}")
    transparent.save(ICO_OUT, format="ICO", sizes=ICO_SIZES)
    print(f"Wrote {ICO_OUT}")


if __name__ == "__main__":
    main()
