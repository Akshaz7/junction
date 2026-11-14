# MODELS

Every third-party model and dataset: name, source URL, licence, training data, and (for API models) the exact model ID with the docs page it came from.

| Name | Kind | Source URL | Licence | Trained on | Used for |
|---|---|---|---|---|---|
| Yytsi ResNet34-UNet (floorplan-to-3d-walls) | segmentation: floor/wall/door/window | https://huggingface.co/Yytsi/floorplan-to-3d-walls (code https://github.com/Yytsi/floorplan-to-3d) | MIT code + MIT weights | CubiCasa5K high-quality splits, exact split unclear: treat CubiCasa5K test drawings as possibly seen | V-01 baseline segmenter; fine-tune target (V-06) |
| CubiCasa5K official multi-task (hg_furukawa_original) | segmentation + icons (window, door, toilet, sink, bathtub, …) + rooms | https://github.com/CubiCasa/CubiCasa5k | CC BY-NC 4.0 (code and weights) | CubiCasa5K train split | V-02 internal baseline for fixtures only (non-commercial; not shipped as the final detector) |
| RF-DETR-medium "2dplan2strct" | boxes: wall/room/door/window | https://huggingface.co/OsamaMo/2dplan2strct | rfdetr Apache-2.0; checkpoint non-commercial research only | undisclosed | Evaluated, not used |
| SegFormer-B0 floorplan (Patnev71) | room/background | https://huggingface.co/Patnev71/segformer-b0-finetuned-floorplan | "other" | unknown | Rejected (card reports mIoU 0.0) |
| CubiCasa5K dataset | training data | https://github.com/CubiCasa/CubiCasa5k (Zenodo) | CC BY-NC-SA 4.0 | — | Fine-tuning data (V-05), held-out ids removed |
