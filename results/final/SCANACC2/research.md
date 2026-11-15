# SCANACC2 research notes

Sources actually read (full text):

- CubiCasa5K, Kalervo et al., arXiv 1904.01920. States that training used 90-degree rotations, colour jitter and crop/scale, and that test-time augmentation (the image rotated four ways, predictions averaged) helps. Implemented as an offline experiment (4- and 8-view rotate/flip average of icon probabilities). Measured on 62 dev drawings: doors up about 2 points, windows down 1 to 4 points at the 0.7 cut, within noise. The full dev run could not finish under memory pressure; not adopted.
- Raster-to-Vector: Revisiting Floorplan Transformation, Liu, Wu, Kohli, Furukawa, ICCV 2017 (the file at the jiajunwu.com im2cad URL). Treats doors and windows as openings on walls. Tried the segmenter's wall openings as a second signal to gate detector components. Measured on 115 dev drawings: no gain.

Measured, not from literature: per-class confidence cuts 0.4 to 0.8 with and without the duplicate gap merge, collinear fragment merging at larger gaps, and 768 input size. The existing 0.7 cut and 1024 input stay. See constants.json.

Finding: raw component totals match gold (windows 770 vs 750, doors 966 vs 855) but per-document counts are wrong because real openings fragment into several pieces at confidence 0.54 to 0.7, and false blobs sit in the same range. Confidence does not separate them. A stronger detector or a trained opening-merge model is needed, not a threshold.

Gold convention check (dev only): gold counts in data/cubicasa5k/calib/gt.json come from the CubiCasa5K SVG annotations, where the Door and Window classes cover every door and window element (swing, sliding, entrance; the dataset has no separate class for closet or hatch openings), and the official icon heads use the same merged Door and Window classes. Our detector classes therefore already cover the gold scope. Raw dev totals agree with gold (windows 770 vs 750, doors 966 vs 855), which also argues against a scope gap. A per-document split of under-counts into scope vs detection needs positional gold, and the SVG-to-PNG registration was unreliable (component precision 0.12 to 0.3), so that split was not measured. The class definitions were not re-read from the repo in this session; this paragraph rests on the paper's description and the totals above.
