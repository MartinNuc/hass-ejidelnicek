"""Horizontal wordmark: the bowl icon beside the product name."""
from PIL import Image, ImageDraw, ImageFont

SS = 4
H = 256 * SS                      # brands logo.png: max 256 tall
icon = Image.open("icon_512.png").convert("RGBA")

FONT = "/System/Library/Fonts/Avenir Next.ttc"   # Demi Bold; full Czech coverage
TEXT = "E-jídelníček"
INK = (0x3A, 0x2A, 0x1E, 255)

mark = icon.resize((H, H), Image.LANCZOS)
size = int(H * 0.40)
font = ImageFont.truetype(FONT, size, index=2)

# Guard: Arial Rounded silently rendered tofu boxes for the Czech carons.
# Probe at a small size so the glyph fits the sample box.
_probe = ImageFont.truetype(FONT, 60, index=2)
def _renders(ch):
    def bmp(c):
        im = Image.new("L", (90, 90), 0)
        ImageDraw.Draw(im).text((5, 5), c, font=_probe, fill=255)
        return im.tobytes()
    return bmp(ch) != bmp("\uffff") and any(bmp(ch))
missing = [c for c in sorted(set(TEXT)) if not c.isspace() and not _renders(c)]
assert not missing, f"font lacks glyphs for {missing}"

pad = int(H * 0.10)
gap = int(H * 0.12)
probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
box = probe.textbbox((0, 0), TEXT, font=font)
tw, th = box[2] - box[0], box[3] - box[1]

W = H + gap + tw + pad
out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
out.alpha_composite(mark, (0, 0))
d = ImageDraw.Draw(out)
d.text((H + gap - box[0], (H - th) / 2 - box[1]), TEXT, font=font, fill=INK)

for tall, name in ((256, "logo.png"), (512, "logo@2x.png")):
    w = round(out.width * tall / out.height)
    out.resize((w, tall), Image.LANCZOS).save(name)
    print(name, f"{w}x{tall}")
