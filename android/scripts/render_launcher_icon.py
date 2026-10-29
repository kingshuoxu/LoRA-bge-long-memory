#!/usr/bin/env python3
"""Render the launcher mark: a small constellation on near-black.

Adaptive foreground is 108dp with the mark inside the 66dp keyline.
Legacy mipmaps are the same artwork at every density, plus a circle crop.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1] / "apk" / "app" / "src" / "main" / "res"
PREVIEW = Path(__file__).resolve().parents[1] / "icon-preview"
FONT = Path(__file__).resolve().parents[1] / "apk" / "app" / "src" / "main" / "res" / "font" / "noto_sans_sc.otf"
BG = (8, 10, 16, 255)
TEAL = (126, 200, 192)
INK = (247, 251, 252)

# Positions in the 108dp adaptive viewport. Center is 54. Safe radius is ~33.
NODES = (
    (48.0, 54.0, 6.6, True),
    (66.5, 43.5, 3.7, False),
    (62.0, 67.5, 4.2, False),
)
EDGES = ((0, 1), (0, 2), (1, 2))


def scale(value, canvas):
    return value * canvas / 108.0


def blank(canvas):
    return Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))


def draw_mark(canvas, color, glow=True):
    image = blank(canvas)
    if glow:
        haze = blank(canvas)
        hd = ImageDraw.Draw(haze)
        cx, cy = scale(56, canvas), scale(54, canvas)
        radius = scale(22, canvas)
        hd.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(*TEAL, 90))
        image = Image.alpha_composite(image, haze.filter(ImageFilter.GaussianBlur(scale(10, canvas))))
        soft = blank(canvas)
        sd = ImageDraw.Draw(soft)
        for x, y, r, _primary in NODES:
            px, py, pr = scale(x, canvas), scale(y, canvas), scale(r * 2.4, canvas)
            sd.ellipse((px - pr, py - pr, px + pr, py + pr), fill=(*TEAL, 70))
        image = Image.alpha_composite(image, soft.filter(ImageFilter.GaussianBlur(scale(3.2, canvas))))
    lines = blank(canvas)
    ld = ImageDraw.Draw(lines)
    width = max(1, int(round(scale(1.35, canvas))))
    for a, b in EDGES:
        ax, ay = scale(NODES[a][0], canvas), scale(NODES[a][1], canvas)
        bx, by = scale(NODES[b][0], canvas), scale(NODES[b][1], canvas)
        ld.line((ax, ay, bx, by), fill=(*color, 210), width=width)
    image = Image.alpha_composite(image, lines)
    cores = blank(canvas)
    cd = ImageDraw.Draw(cores)
    for x, y, r, primary in NODES:
        px, py, pr = scale(x, canvas), scale(y, canvas), scale(r, canvas)
        if primary:
            draw_spark(cd, px, py, pr * 1.55, color)
        cd.ellipse((px - pr, py - pr, px + pr, py + pr), fill=(*color, 255))
    return Image.alpha_composite(image, cores)


def draw_spark(draw, cx, cy, radius, color):
    # Two solid diamonds. A single star polygon fills with a hole.
    arm = radius
    waist = radius * 0.36
    fill = (*color, 255)
    draw.polygon([(cx, cy - arm), (cx + waist, cy), (cx, cy + arm), (cx - waist, cy)], fill=fill)
    draw.polygon([(cx - arm, cy), (cx, cy - waist), (cx + arm, cy), (cx, cy + waist)], fill=fill)


def full_icon(canvas):
    base = Image.new("RGBA", (canvas, canvas), BG)
    return Image.alpha_composite(base, draw_mark(canvas, INK, glow=True))


def circle_mask(canvas):
    mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, canvas - 1, canvas - 1), fill=255)
    return mask


def squircle_mask(canvas):
    # Superellipse close to the Pixel / vivo squircle. n=4.5 stays inside the safe zone visually.
    mask = Image.new("L", (canvas, canvas), 0)
    pixels = mask.load()
    n = 4.5
    radius = canvas * 0.5
    cx = cy = (canvas - 1) / 2.0
    for y in range(canvas):
        for x in range(canvas):
            nx = abs(x - cx) / radius
            ny = abs(y - cy) / radius
            if nx**n + ny**n <= 1.0:
                pixels[x, y] = 255
    return mask


def apply_mask(image, mask):
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    out.paste(image, (0, 0))
    out.putalpha(mask)
    return out


def save_png(image, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")


def downscale(image, size):
    return image.resize((size, size), Image.Resampling.LANCZOS)


def launcher_grid(icon, wallpaper, label_color):
    # 48dp icon at xxhdpi, four columns, two rows. Ours is the first cell.
    icon_px = 144
    cell = 210
    pad_x = 36
    pad_y = 48
    cols, rows = 4, 2
    width = pad_x * 2 + cell * cols
    height = pad_y * 2 + cell * rows
    canvas = Image.new("RGBA", (width, height), wallpaper)
    masked = apply_mask(downscale(icon, icon_px), squircle_mask(icon_px))
    placeholders = (
        (90, 98, 110),
        (168, 164, 156),
        (120, 132, 148),
        (150, 150, 158),
        (110, 118, 128),
        (176, 170, 160),
        (132, 140, 150),
    )
    font = ImageFont.truetype(str(FONT), 28)
    labels = ["记忆", "对话", "相册", "设置", "时钟", "地图", "音乐", "天气"]
    draw = ImageDraw.Draw(canvas)
    index = 0
    for row in range(rows):
        for col in range(cols):
            left = pad_x + col * cell + (cell - icon_px) // 2
            top = pad_y + row * cell
            if index == 0:
                canvas.alpha_composite(masked, (left, top))
            else:
                blob = Image.new("RGBA", (icon_px, icon_px), placeholders[index - 1] + (255,))
                blob.putalpha(squircle_mask(icon_px))
                canvas.alpha_composite(blob, (left, top))
            text = labels[index]
            box = draw.textbbox((0, 0), text, font=font)
            tw = box[2] - box[0]
            draw.text((left + (icon_px - tw) / 2, top + icon_px + 12), text, fill=label_color, font=font)
            index += 1
    return canvas


def main():
    master = 1024
    icon = full_icon(master)
    foreground = draw_mark(master, INK, glow=True)
    mono = draw_mark(master, (255, 255, 255), glow=False)
    circle = apply_mask(icon, circle_mask(master))
    squircle = apply_mask(icon, squircle_mask(master))

    fg_sizes = {"mdpi": 108, "hdpi": 162, "xhdpi": 216, "xxhdpi": 324, "xxxhdpi": 432}
    legacy = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
    for density, size in fg_sizes.items():
        save_png(downscale(foreground, size), ROOT / f"mipmap-{density}" / "ic_launcher_foreground.png")
    for density, size in legacy.items():
        full = downscale(icon, size)
        save_png(full, ROOT / f"mipmap-{density}" / "ic_launcher.png")
        save_png(apply_mask(full, circle_mask(size)), ROOT / f"mipmap-{density}" / "ic_launcher_round.png")

    PREVIEW.mkdir(parents=True, exist_ok=True)
    save_png(downscale(icon, 512), PREVIEW / "icon-large.png")
    save_png(downscale(circle, 512), PREVIEW / "icon-circle.png")
    save_png(downscale(squircle, 512), PREVIEW / "icon-squircle.png")
    save_png(downscale(mono, 512), PREVIEW / "icon-monochrome.png")
    save_png(launcher_grid(icon, (18, 20, 28, 255), (232, 232, 234, 255)), PREVIEW / "launcher-dark.png")
    save_png(launcher_grid(icon, (236, 232, 224, 255), (28, 28, 32, 255)), PREVIEW / "launcher-light.png")
    print(PREVIEW)


if __name__ == "__main__":
    main()
