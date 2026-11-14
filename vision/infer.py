"""Model wrappers. One model loaded at a time is the caller's job (call .release()).

SegModel   - Yytsi ResNet34-UNet (MIT): floor/wall/door/window class map at original resolution.
OfficialModel - CubiCasa5K multi-task net (CC BY-NC 4.0, internal baseline): room map + icon map.
"""
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))


def device():
    return torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def _letterbox(img, size, fill):
    w, h = img.size
    s = size / max(w, h)
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    canvas = Image.new("RGB", (size, size), fill)
    ox, oy = (size - nw) // 2, (size - nh) // 2
    canvas.paste(img.resize((nw, nh), Image.BILINEAR), (ox, oy))
    return canvas, (ox, oy, nw, nh)


def _unbox(arr, box, out_size, resample):
    ox, oy, nw, nh = box
    arr = arr[..., oy:oy + nh, ox:ox + nw]
    return arr


class SegModel:
    MEAN, STD = np.array([0.485, 0.456, 0.406]), np.array([0.229, 0.224, 0.225])
    NAME = "yytsi-unet-resnet34"

    def __init__(self, size=512, dev=None):
        from safetensors.torch import load_file
        from unet_resnet34 import UNetResNet34
        self.size, self.dev = size, dev or device()
        m = UNetResNet34(4)
        m.load_state_dict(load_file(str(ROOT / "weights/yytsi_unet/best.safetensors")), strict=True)
        self.m = m.to(self.dev).eval()

    def probs(self, img):
        """Softmax probs (4,H,W) at original resolution, float32."""
        box_img, box = _letterbox(img, self.size, tuple(int(v * 255) for v in self.MEAN))
        x = ((np.asarray(box_img, np.float32) / 255 - self.MEAN) / self.STD).transpose(2, 0, 1)
        with torch.no_grad():
            p = self.m(torch.from_numpy(x).float()[None].to(self.dev)).softmax(1)
            ox, oy, nw, nh = box
            p = p[:, :, oy:oy + nh, ox:ox + nw]
            p = torch.nn.functional.interpolate(p, size=(img.size[1], img.size[0]), mode="bilinear", align_corners=False)
        return p[0].cpu().numpy()

    def classes(self, img):
        return self.probs(img).argmax(0).astype(np.uint8)

    def release(self):
        del self.m
        if self.dev.type == "mps":
            torch.mps.empty_cache()


class OfficialModel:
    NAME = "cubicasa5k-official-hg_furukawa"
    ICONS = ["bg", "Window", "Door", "Closet", "ElectricalAppl", "Toilet", "Sink", "SaunaBench", "FireP", "Bathtub", "Chimney"]
    ROOMS = ["bg", "Outdoor", "Wall", "Kitchen", "Living", "Bed", "Bath", "Entry", "Storage", "Garage", "Undefined", "Railing"]

    def __init__(self, size=512, dev=None):
        sys.path.insert(0, str(ROOT / "weights/_src/CubiCasa5k-master"))
        from floortrans.models.hg_furukawa_original import hg_furukawa_original
        self.size, self.dev = size, dev or device()
        m = hg_furukawa_original(n_classes=51)
        m.conv4_ = torch.nn.Conv2d(256, 44, bias=True, kernel_size=1)
        m.upsample = torch.nn.ConvTranspose2d(44, 44, kernel_size=4, stride=4)
        ck = torch.load(ROOT / "weights/cubicasa_official/model_best_val_loss_var.pkl", map_location="cpu", weights_only=False)
        m.load_state_dict(ck["model_state"])
        self.m = m.to(self.dev).eval()

    def maps(self, img):
        """Return (rooms (H,W) uint8, icons (H,W) uint8) at original resolution (letterboxed in, cropped out)."""
        box_img, box = _letterbox(img, self.size, (255, 255, 255))
        x = 2 * (np.asarray(box_img, np.float32) / 255 - 0.5)
        with torch.no_grad():
            y = self.m(torch.from_numpy(x).permute(2, 0, 1)[None].to(self.dev))[0]
            ox, oy, nw, nh = box
            y = y[:, oy:oy + nh, ox:ox + nw][None]
            y = torch.nn.functional.interpolate(y, size=(img.size[1], img.size[0]), mode="bilinear", align_corners=False)[0]
        y = y.cpu()
        ip = y[33:44].softmax(0)
        self.icon_conf = ip.max(0).values.numpy()
        self.room_conf = y[21:33].softmax(0).max(0).values.numpy()
        return y[21:33].argmax(0).numpy().astype(np.uint8), y[33:44].argmax(0).numpy().astype(np.uint8)

    def release(self):
        del self.m
        if self.dev.type == "mps":
            torch.mps.empty_cache()
