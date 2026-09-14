"""Overlay a "معلم" gold ribbon on the teacher app's launcher icons so
they are visually distinct from the parent app's icons — required by
App Store Guideline 4.3(a), which rejects identical icons across apps
from the same developer.

RUN THIS after every `flutter pub run flutter_launcher_icons` on the
teacher_app, because the icon generator overwrites all sizes from the
shared `logo-emblem.png` source and wipes the ribbon.

    cd mobile/teacher_app
    flutter pub run flutter_launcher_icons
    python ../../scripts/apply_teacher_icon_ribbon.py

Also runs against the standalone school-teacher-app/ Xcode Cloud repo
if it is checked out next to schoolsudan/ on the same machine.

Dependencies: Pillow, arabic-reshaper, python-bidi (pip install them
in your working virtualenv).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display


BAND_COLOR = (201, 162, 75, 255)   # brand gold — matches manasety_ui token
TEXT_COLOR = (255, 255, 255, 255)
BAND_RATIO = 0.18                  # 18% of image height
TEXT_RATIO_OF_BAND = 0.55          # font size = 55% of band height
FONT_PATH = "/System/Library/Fonts/GeezaPro.ttc"

_shaped = arabic_reshaper.reshape("معلم")
DISPLAY_TEXT = get_display(_shaped)


def add_teacher_ribbon(png_path: Path) -> None:
    img = Image.open(png_path).convert("RGBA")
    w, h = img.size

    band_h = max(int(h * BAND_RATIO), 3)
    band = Image.new("RGBA", (w, band_h), BAND_COLOR)
    img.paste(band, (0, h - band_h), band)

    if band_h >= 16:
        font_size = max(int(band_h * TEXT_RATIO_OF_BAND), 8)
        font = ImageFont.truetype(FONT_PATH, font_size)

        draw = ImageDraw.Draw(img)
        bbox = draw.textbbox((0, 0), DISPLAY_TEXT, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (w - tw) // 2 - bbox[0]
        y = h - band_h + (band_h - th) // 2 - bbox[1]
        draw.text((x, y), DISPLAY_TEXT, font=font, fill=TEXT_COLOR)

    img.save(png_path)


# Roots to scan — the monorepo teacher_app plus the standalone Xcode
# Cloud clone (if present on the same machine). We check a couple of
# common Desktop layouts for the standalone repo.
HERE = Path(__file__).resolve().parent.parent  # → schoolsudan/
STANDALONE_CANDIDATES = [
    HERE.parent / "school-teacher-app",                # sibling of schoolsudan
    Path.home() / "Desktop/school-teacher-app",        # bare on Desktop
]
STANDALONE = next((p for p in STANDALONE_CANDIDATES if p.exists()), None)

ROOTS = [
    HERE / "mobile/teacher_app/ios/Runner/Assets.xcassets/AppIcon.appiconset",
    HERE / "mobile/teacher_app/android/app/src/main/res",
]
if STANDALONE is not None:
    ROOTS.append(STANDALONE / "ios/Runner/Assets.xcassets/AppIcon.appiconset")
    ROOTS.append(STANDALONE / "android/app/src/main/res")

# Corresponding target on the Desktop for the Play Store hero image.
PLAY_STORE_ICON = Path.home() / "Desktop/manasety-teacher-playstore-icon-512.png"


def main() -> None:
    total = 0
    for root in ROOTS:
        if not root.exists():
            print(f"⚠ skip missing: {root}")
            continue
        for p in root.rglob("*.png"):
            name = p.name.lower()
            if (
                name.startswith("icon-app")
                or name.startswith("ic_launcher")
                or "launcher_icon" in name
            ):
                add_teacher_ribbon(p)
                total += 1
                print(f"  ✓ {p.relative_to(root)}")

    if PLAY_STORE_ICON.exists():
        add_teacher_ribbon(PLAY_STORE_ICON)
        print(f"  ✓ {PLAY_STORE_ICON}")
        total += 1

    print(f"\nDone — modified {total} PNG files.")


if __name__ == "__main__":
    main()
