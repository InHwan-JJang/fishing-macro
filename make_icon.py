"""낚시 매크로 아이콘을 직접 그려 images.png(512x512)와 fishing.ico를 만듭니다.

물 위에 뜬 찌와 물고기를 도형만으로 그린 원본 그림입니다. (외부 이미지를 쓰지 않음)
필요: pip install pillow    실행: python make_icon.py
"""

import math

from PIL import Image, ImageDraw

SIZE = 512
SS = 4                       # 4배로 그린 뒤 줄여서 가장자리를 부드럽게
W = SIZE * SS
WATER_Y = 300                # 수면 높이


def s(v):
    return int(round(v * SS))


def gradient(top, bottom):
    img = Image.new("RGBA", (W, W))
    draw = ImageDraw.Draw(img)
    for y in range(W):
        t = y / (W - 1)
        draw.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    return img


def wave_points(base, amp, period, phase=0.0):
    return [(s(x), s(base + amp * math.sin((x / period) * 2 * math.pi + phase))) for x in range(-8, SIZE + 9, 4)]


def draw_icon():
    img = gradient((104, 204, 244), (30, 120, 200))

    # 찌: 위쪽 빨강, 아래쪽 흰색, 윗부분 막대와 낚싯줄
    bobber = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(bobber)
    bx, by, r = 190, WATER_Y, 66
    d.line([(s(bx), s(-10)), (s(bx), s(by - r - 30))], fill=(255, 255, 255, 255), width=s(5))
    d.rounded_rectangle([s(bx - 9), s(by - r - 48), s(bx + 9), s(by - r + 6)], radius=s(6), fill=(255, 214, 64, 255))
    d.ellipse([s(bx - r), s(by - r), s(bx + r), s(by + r)], fill=(255, 255, 255, 255))
    d.pieslice([s(bx - r), s(by - r), s(bx + r), s(by + r)], 180, 360, fill=(232, 72, 60, 255))
    d.line([(s(bx - r + 2), s(by)), (s(bx + r - 2), s(by))], fill=(18, 54, 94, 255), width=s(6))
    d.ellipse([s(bx - r), s(by - r), s(bx + r), s(by + r)], outline=(18, 54, 94, 255), width=s(8))
    d.ellipse([s(bx - 38), s(by - 48), s(bx - 14), s(by - 28)], fill=(255, 255, 255, 150))
    img = Image.alpha_composite(img, bobber)

    # 물: 반투명이라 찌의 아랫부분과 물고기가 물속에 비쳐 보임
    water = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(water)
    d.polygon(wave_points(WATER_Y, 9, 128) + [(s(SIZE + 8), s(SIZE + 8)), (s(-8), s(SIZE + 8))], fill=(16, 84, 160, 150))
    d.line(wave_points(WATER_Y, 9, 128), fill=(255, 255, 255, 235), width=s(9), joint="curve")
    d.line(wave_points(WATER_Y + 46, 7, 96, 1.6), fill=(255, 255, 255, 90), width=s(6), joint="curve")
    for x, y, rad in ((290, 330, 9), (316, 300 + 56, 6), (150, 386, 7)):
        d.ellipse([s(x - rad), s(y - rad), s(x + rad), s(y + rad)], outline=(255, 255, 255, 170), width=s(3))
    img = Image.alpha_composite(img, water)

    # 물고기 (오른쪽 아래, 오른쪽을 보고 있음)
    fish = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(fish)
    cx, cy = 352, 410
    d.polygon([(s(cx - 62), s(cy)), (s(cx - 112), s(cy - 38)), (s(cx - 112), s(cy + 38))], fill=(255, 140, 36, 255))
    d.ellipse([s(cx - 70), s(cy - 40), s(cx + 70), s(cy + 40)], fill=(255, 178, 60, 255))
    d.polygon([(s(cx - 10), s(cy - 38)), (s(cx + 12), s(cy - 66)), (s(cx + 30), s(cy - 36))], fill=(255, 140, 36, 255))
    d.ellipse([s(cx + 28), s(cy - 16), s(cx + 50), s(cy + 6)], fill=(255, 255, 255, 255))
    d.ellipse([s(cx + 36), s(cy - 10), s(cx + 48), s(cy + 2)], fill=(20, 40, 70, 255))
    d.arc([s(cx - 40), s(cy - 26), s(cx + 6), s(cy + 30)], 280, 80, fill=(224, 108, 24, 255), width=s(5))
    img = Image.alpha_composite(img, fish)

    # 둥근 사각형으로 자르기
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, W - 1], radius=s(104), fill=255)
    img.putalpha(mask)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


if __name__ == "__main__":
    icon = draw_icon()
    icon.save("images.png")
    # BMP 방식으로 저장: Tk의 창 아이콘 읽기가 PNG 압축 항목을 처리하지 못함
    icon.resize((256, 256), Image.LANCZOS).save(
        "fishing.ico", sizes=[(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 128, 256)], bitmap_format="bmp")
    print("images.png, fishing.ico 생성 완료")
