"""E-jidelnicek integration icon: a bowl of soup with steam."""
from PIL import Image, ImageDraw
import math

SS = 4
S = 512 * SS
cx = S * 0.5

def lerp(a, b, t): return tuple(round(x + (y - x) * t) for x, y in zip(a, b))

def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m

def stroke(draw, pts, width, fill):
    """Polyline with genuinely round caps and joins (PIL's width= gives square caps)."""
    r = width / 2
    for x, y in pts:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=fill)

def plume(draw, cx0, y0, y1, amp, width, alpha):
    pts = []
    n = 220
    for i in range(n + 1):
        t = i / n
        y = y0 + (y1 - y0) * t
        taper = 1 - 0.30 * t                      # narrows as it rises
        x = cx0 + math.sin(t * math.pi * 1.6) * amp * taper
        pts.append((x, y))
    stroke(draw, pts, width, (255, 255, 255, alpha))

# background -----------------------------------------------------------------
TOP, BOT = (0xF7, 0xB5, 0x50), (0xDD, 0x65, 0x22)
bg = Image.new("RGBA", (S, S))
d = ImageDraw.Draw(bg)
for y in range(S):
    d.line([(0, y), (S, y)], fill=lerp(TOP, BOT, y / S) + (255,))
bg.putalpha(rounded_mask(S, int(S * 0.22)))

layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
dl = ImageDraw.Draw(layer)

WHITE = (255, 255, 255, 255)
CREAM = (255, 240, 214, 255)

RIM = S * 0.525          # y of the soup surface / bowl mouth
BW  = S * 0.66           # bowl width
BH  = S * 0.225          # bowl depth below the rim

# steam ----------------------------------------------------------------------
plume(dl, cx,             RIM - S * 0.115, S * 0.150, S * 0.040, S * 0.036, 240)
plume(dl, cx - S * 0.150, RIM - S * 0.095, S * 0.215, S * 0.032, S * 0.030, 165)
plume(dl, cx + S * 0.150, RIM - S * 0.095, S * 0.215, S * 0.032, S * 0.030, 165)

# soup surface (drawn first; the bowl covers its lower half) -------------------
SW, SHH = BW * 0.94, S * 0.15
dl.ellipse([cx - SW / 2, RIM - SHH / 2, cx + SW / 2, RIM + SHH / 2], fill=CREAM)

# bowl: bottom half of an ellipse centred on the rim line ---------------------
dl.pieslice([cx - BW / 2, RIM - BH, cx + BW / 2, RIM + BH], start=0, end=180, fill=WHITE)

icon = Image.alpha_composite(bg, layer)
for px in (512, 256):
    icon.resize((px, px), Image.LANCZOS).save(f"icon_{px}.png")
# legibility proof at the size HA actually renders an integration icon
icon.resize((48, 48), Image.LANCZOS).resize((192, 192), Image.NEAREST).save("proof_48.png")
print("ok")
