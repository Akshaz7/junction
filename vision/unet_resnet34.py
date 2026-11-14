"""Minimal ResNet34-UNet, key-compatible with segmentation_models_pytorch.Unet('resnet34').

Written so we need no `segmentation-models-pytorch` dependency (pure torch + torchvision, ONNX friendly).
Loads Yytsi/floorplan-to-3d-walls weights (MIT). Classes: floor, wall, door, window.
"""
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision.models import resnet34

CLASS_NAMES = ("floor", "wall", "door", "window")


def _cbr(i, o):
    return nn.Sequential(nn.Conv2d(i, o, 3, padding=1, bias=False), nn.BatchNorm2d(o), nn.ReLU(inplace=True))


class _Block(nn.Module):
    def __init__(self, i, skip, o):
        super().__init__()
        self.conv1 = _cbr(i + skip, o)
        self.conv2 = _cbr(o, o)

    def forward(self, x, skip=None):
        x = F.interpolate(x, scale_factor=2, mode="nearest")
        if skip is not None:
            x = torch.cat([x, skip], 1)
        return self.conv2(self.conv1(x))


class _Decoder(nn.Module):
    def __init__(self):
        super().__init__()
        ins, skips, outs = [512, 256, 128, 64, 32], [256, 128, 64, 64, 0], [256, 128, 64, 32, 16]
        self.blocks = nn.ModuleList(_Block(i, s, o) for i, s, o in zip(ins, skips, outs))

    def forward(self, feats):
        f = feats[::-1]  # deepest first
        x, skips = f[0], f[1:]
        for i, b in enumerate(self.blocks):
            x = b(x, skips[i] if i < len(skips) else None)
        return x


class UNetResNet34(nn.Module):
    def __init__(self, num_classes=4):
        super().__init__()
        self.encoder = resnet34(weights=None)
        del self.encoder.fc
        self.decoder = _Decoder()
        self.segmentation_head = nn.Sequential(nn.Conv2d(16, num_classes, 3, padding=1))

    def forward(self, x):
        e = self.encoder
        f0 = e.relu(e.bn1(e.conv1(x)))
        f1 = e.layer1(e.maxpool(f0))
        f2 = e.layer2(f1)
        f3 = e.layer3(f2)
        f4 = e.layer4(f3)
        return self.segmentation_head(self.decoder([f0, f1, f2, f3, f4]))
