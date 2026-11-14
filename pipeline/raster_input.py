"""Bounded, orientation-correct raster decoding shared by upload and page readers."""
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

# A compressed image can expand far beyond the upload byte limit. 10000 x 10000
# scans fit; larger images require an explicit server memory budget increase.
MAX_PIXELS = 120_000_000


def cap_image(img: Image.Image, side: int) -> Image.Image:
    if img.width * img.height > MAX_PIXELS:
        raise ValueError("This image is too large to decode safely. Export it at a lower resolution (up to 120 megapixels).")
    if img.format == "JPEG":
        img.draft("RGB", (side, side))
    if img.mode in ("I", "I;16", "I;16B", "I;16L"):
        # PNG samples are unsigned 16-bit: preserve their full tonal range rather
        # than clipping every sample above 255 to white.
        img = img.point(lambda v: v * (255 / 65535)).convert("L")
    if max(img.size) > side:
        # Preserve palette colours and transparency, including transparent index 0.
        if img.mode == "P":
            img = img.convert("RGBA" if "transparency" in img.info else "RGB")
        img.thumbnail((side, side), Image.Resampling.BILINEAR, reducing_gap=2.0)
    # Transpose after shrinking: the image and all downstream boxes use the same
    # displayed orientation, without a full-resolution rotation buffer.
    ImageOps.exif_transpose(img, in_place=True)
    return img


def read_raster(path: Path, side: int) -> Image.Image:
    """Return an independent RGB image; close the source even on malformed input."""
    try:
        with Image.open(path) as source:
            img = cap_image(source, side)
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
                return rgb
            return img.convert("RGB")
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("This image could not be read. It may be corrupt or incomplete. Export it again as PNG or JPEG.") from exc
