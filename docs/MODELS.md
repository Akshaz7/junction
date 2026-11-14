# MODELS

Every third-party model and dataset: name, source URL, licence, training data, and (for API models) the exact model ID with the docs page it came from.

| Name | Kind | Source URL | Licence | Trained on | Used for |
|---|---|---|---|---|---|
| Yytsi ResNet34-UNet (floorplan-to-3d-walls) | segmentation: floor/wall/door/window | https://huggingface.co/Yytsi/floorplan-to-3d-walls (code https://github.com/Yytsi/floorplan-to-3d) | MIT code + MIT weights | CubiCasa5K high-quality splits, exact split unclear: treat CubiCasa5K test drawings as possibly seen | V-01 baseline segmenter; fine-tune target (V-06) |
| CubiCasa5K official multi-task (hg_furukawa_original) | segmentation + icons (window, door, toilet, sink, bathtub, …) + rooms | https://github.com/CubiCasa/CubiCasa5k | CC BY-NC 4.0 (code and weights) | CubiCasa5K train split | V-02 internal baseline for fixtures only (non-commercial; not shipped as the final detector) |
| RF-DETR-medium "2dplan2strct" | boxes: wall/room/door/window | https://huggingface.co/OsamaMo/2dplan2strct | rfdetr Apache-2.0; checkpoint non-commercial research only | undisclosed | Evaluated, not used |
| SegFormer-B0 floorplan (Patnev71) | room/background | https://huggingface.co/Patnev71/segformer-b0-finetuned-floorplan | "other" | unknown | Rejected (card reports mIoU 0.0) |
| CubiCasa5K dataset | training data | https://github.com/CubiCasa/CubiCasa5k (Zenodo) | CC BY-NC-SA 4.0 | — | Fine-tuning data (V-05), held-out ids removed |

## API models (via engine/models; IDs confirmed in provider docs 2026-11-14; prices in engine/models/models.yaml `prices:`)
| Task | Provider | Model ID | Docs | Fallbacks |
|---|---|---|---|---|
| route | NVIDIA | nvidia/nemotron-3.5-lightning-30b-a3b | build.nvidia.com/nvidia/nemotron-3.5-lightning-30b-a3b | Runware google:gemini@3.1-flash-lite |
| read_drawing | Gemini | gemini-3.8-flash | ai.google.dev/gemini-api/docs/models | Featherless Qwen/Qwen3-VL-30B-A3B-Instruct; Runware google:gemini@3.5-flash |
| verify_item | Gemini | gemini-3.5-flash-lite | ai.google.dev/gemini-api/docs/models | NVIDIA nvidia/nemotron-3.5-super-vl-120b-a12b; Runware google:gemini@3.1-flash-lite |
| speech_intent | Gemini | gemini-3.5-flash-lite | ai.google.dev/gemini-api/docs/models | NVIDIA nemotron-3.5-lightning-30b-a3b; Runware google:gemini@3.1-flash-lite |
| write_answer | Anthropic | claude-sonnet-5-5 | platform.claude.com/docs/en/about-claude/models | Gemini gemini-3.8-flash; Runware anthropic:claude@sonnet-4.6 |
| judge_text | Anthropic | claude-haiku-5-5 | platform.claude.com/docs/en/about-claude/models | NVIDIA nemotron-3.5-lightning-30b-a3b; Runware anthropic:claude@haiku-4.5 |
| advise | NVIDIA | nvidia/nemotron-3-super-120b-a12b | build.nvidia.com/nvidia/nemotron-3-super-120b-a12b | Anthropic claude-sonnet-5-5; Runware anthropic:claude@sonnet-4.6 |
| tts | Runware | fishaudio:s2.1@pro | runware.ai/docs/models/fishaudio-s2-1-pro | — (ElevenLabs to be wired in S-08) |
| OCR | local | RapidOCR (rapidocr-onnxruntime) | https://github.com/RapidAI/RapidOCR | Apache-2.0 |
| tts | ElevenLabs | eleven_flash_v2_5 (voice SAz9YHcvj6GT2YYXdXww) | https://elevenlabs.io/docs | Runware fishaudio:s2.1@pro |
