"""확정한 images.png를 Windows ICO로 변환합니다. 필요: pip install pillow."""

from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent
ICON_SIZES = [(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)]


if __name__ == "__main__":
    with Image.open(ROOT / "images.png") as source:
        icon = source.convert("RGBA").resize((256, 256), Image.Resampling.LANCZOS)
    # Tk 창 아이콘 호환성을 위해 PNG 압축 대신 BMP 항목을 저장합니다.
    icon.save(ROOT / "fishing.ico", sizes=ICON_SIZES, bitmap_format="bmp")
    print("fishing.ico 생성 완료 (확정된 images.png 사용)")
