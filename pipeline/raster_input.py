"""Bounded, orientation-correct raster decoding shared by upload and page readers."""
import os
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

# A compressed image can expand far beyond the upload byte limit. 10000 x 10000
# scans fit; larger images require an explicit server memory budget increase.
MAX_PIXELS = 120_000_000
# Leave room for the API, decoder copies and the resized image on a small host.
# JPEG draft decoding reduces its working dimensions before this byte check.
MAX_DECODE_BYTES = int(float(os.environ.get("RASTER_MAX_DECODE_MB", "128")) * 1024 ** 2)


def cap_image(img: Image.Image, side: int) -> Image.Image:
    if img.width * img.height > MAX_PIXELS:
        raise ValueError("This image is too large to decode safely. Export it at a lower resolution (up to 120 megapixels).")
    if img.format == "JPEG":
        ratio = min(1.0, side / max(img.size))
        img.draft("RGB", (max(1, round(img.width * ratio)), max(1, round(img.height * ratio))))
    bytes_per_pixel = 4 if img.mode in ("RGBA", "CMYK", "I", "F") else (
        2 if img.mode in ("LA", "I;16", "I;16B", "I;16L") else 3 if img.mode == "RGB" else 1)
    if img.mode == "P":
        bytes_per_pixel = 4 if "transparency" in img.info else 3  # full-size conversion before filtering
    if img.width * img.height * bytes_per_pixel > MAX_DECODE_BYTES:
        raise ValueError("This image needs more decoding memory than this server allows. Export it at a lower resolution or as JPEG and upload it again.")
    if max(img.size) > side:
        # Preserve palette colours and transparency, including transparent index 0.
        if img.mode == "P":
            img = img.convert("RGBA" if "transparency" in img.info else "RGB")
        if img.mode.startswith("I;16"):
            # Pillow cannot filter I;16 directly. Sample before tone conversion,
            # avoiding a second full-size integer buffer for large 16-bit scans.
            img.thumbnail((side, side), Image.Resampling.NEAREST, reducing_gap=None)
        else:
            img.thumbnail((side, side), Image.Resampling.BILINEAR, reducing_gap=2.0)
    if img.mode in ("I", "I;16", "I;16B", "I;16L"):
        # PNG samples are unsigned 16-bit: retain their full tonal range.
        img = img.point(lambda v: v * (255 / 65535)).convert("L")
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
