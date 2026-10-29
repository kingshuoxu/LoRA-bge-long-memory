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

# 108dp viewport. The 72dp safe zone is centered on 54. The mark spans ~46dp,
# about 64% of that zone, and its bounding box is centered on 54,54.
SPARK = (43.0, 52.8)
SPARK_ARM = 12.2
SPARK_INNER = 3.4
NODES = (
    (71.2, 37.3, 5.6),
    (66.4, 70.3, 6.0),
)
LINE = 2.8


def scale(value, canvas):
    return value * canvas / 108.0


def blank(canvas):
    return Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))


def spark_points(cx, cy, arm, inner):
    # Angular order, so the polygon does not cross itself or leave a hole.
    return [
        (cx, cy - arm),
        (cx + inner, cy - inner),
        (cx + arm, cy),
        (cx + inner, cy + inner),
        (cx, cy + arm),
        (cx - inner, cy + inner),
        (cx - arm, cy),
        (cx - inner, cy - inner),
    ]


def draw_mark(canvas, color, glow=True):
    image = blank(canvas)
    sx, sy = SPARK
    if glow:
        haze = blank(canvas)
        hd = ImageDraw.Draw(haze)
        cx, cy = scale(54, canvas), scale(54, canvas)
        radius = scale(32, canvas)
        hd.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(*TEAL, 46))
        image = Image.alpha_composite(image, haze.filter(ImageFilter.GaussianBlur(scale(16, canvas))))
    points = [(sx, sy), NODES[0][:2], NODES[1][:2]]
    lines = blank(canvas)
    ld = ImageDraw.Draw(lines)
    width = max(2, int(round(scale(LINE, canvas))))
    for a, b in ((0, 1), (0, 2), (1, 2)):
        ax, ay = scale(points[a][0], canvas), scale(points[a][1], canvas)
        bx, by = scale(points[b][0], canvas), scale(points[b][1], canvas)
        ld.line((ax, ay, bx, by), fill=(*color, 230), width=width)
    image = Image.alpha_composite(image, lines)
    cores = blank(canvas)
    cd = ImageDraw.Draw(cores)
    px, py = scale(sx, canvas), scale(sy, canvas)
    arm = scale(SPARK_ARM, canvas)
    inner = scale(SPARK_INNER, canvas)
    if glow:
        core = blank(canvas)
        cr = scale(4.2, canvas)
        ImageDraw.Draw(core).ellipse((px - cr, py - cr, px + cr, py + cr), fill=(*color, 200))
        image = Image.alpha_composite(image, core.filter(ImageFilter.GaussianBlur(scale(2.2, canvas))))
    cd.polygon(spark_points(px, py, arm, inner), fill=(*color, 255))
    for x, y, radius in NODES:
        nx, ny, nr = scale(x, canvas), scale(y, canvas), scale(radius, canvas)
        cd.ellipse((nx - nr, ny - nr, nx + nr, ny + nr), fill=(*color, 255))
    return Image.alpha_composite(image, cores)


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


def fmt(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


def circle_path(cx, cy, radius):
    return f"M{fmt(cx)},{fmt(cy - radius)} a{fmt(radius)},{fmt(radius)} 0 1,0 0,{fmt(radius * 2)} a{fmt(radius)},{fmt(radius)} 0 1,0 0,{fmt(-radius * 2)} z"


def write_monochrome_xml():
    sx, sy = SPARK
    pts = spark_points(sx, sy, SPARK_ARM, SPARK_INNER)
    star = "M" + " L".join(f"{fmt(x)},{fmt(y)}" for x, y in pts) + " Z"
    b, c = NODES
    lines = f"M{fmt(sx)},{fmt(sy)} L{fmt(b[0])},{fmt(b[1])} M{fmt(sx)},{fmt(sy)} L{fmt(c[0])},{fmt(c[1])} M{fmt(b[0])},{fmt(b[1])} L{fmt(c[0])},{fmt(c[1])}"
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp"
    android:height="108dp"
    android:viewportWidth="108"
    android:viewportHeight="108">
    <path
        android:fillColor="#FFFFFFFF"
        android:pathData="{star}" />
    <path
        android:fillColor="#FFFFFFFF"
        android:pathData="{circle_path(b[0], b[1], b[2])}" />
    <path
        android:fillColor="#FFFFFFFF"
        android:pathData="{circle_path(c[0], c[1], c[2])}" />
    <path
        android:pathData="{lines}"
        android:strokeColor="#FFFFFFFF"
        android:strokeLineCap="round"
        android:strokeWidth="{fmt(LINE)}" />
</vector>
"""
    path = ROOT / "drawable" / "ic_launcher_monochrome.xml"
    path.write_text(xml, encoding="utf-8")


def themed_monochrome(canvas):
    # Android 13 paints the monochrome alpha as a dark glyph on a light tint.
    glyph = draw_mark(canvas, (255, 255, 255), glow=False)
    plate = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    ImageDraw.Draw(plate).ellipse((0, 0, canvas - 1, canvas - 1), fill=(226, 232, 236, 255))
    ink = Image.new("RGBA", (canvas, canvas), (24, 28, 34, 255))
    ink.putalpha(glyph.getchannel("A"))
    return Image.alpha_composite(plate, ink)


def main():
    master = 1024
    icon = full_icon(master)
    foreground = draw_mark(master, INK, glow=True)
    mono = themed_monochrome(master)
    write_monochrome_xml()
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
