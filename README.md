# junction — IFC → GLB + element index spike

Proves that the Junction construction dataset's BIM models (IFC) convert into clean 3D
models (GLB) plus a searchable per-element index (`elements.json`). No UI.

## Results

| model | IFC | GLB | convert (1 / 8 threads) | index | elements | GLB nodes ↔ IFC GUID |
|---|---|---|---|---|---|---|
| aalseth_stairs | 0.35 MB | 0.18 MB | 0.26 s / 0.18 s | 0.2 s | 46 | 46/46 |
| duplex_arc | 1.6 MB | 0.94 MB | 1.06 s / 0.46 s | 0.7 s | 289 | 215/215 |
| digital_hub_arc | 9 MB | 6 MB | – / ~3 s | 10 s | 1,021 | 705/705 |
| clinic-plumbing | 56 MB | 31 MB | – / ~10 s | 99 s | 6,587 | 6,587/6,587 |

- **Geometry:** every geometric element is in the GLB except `IfcSpace`/`IfcOpeningElement`, which
  IfcConvert skips by default. The model bbox matches the IFC exactly, and per-element bboxes match within 0.1 mm.
- **Metadata:** GLB nodes are named by IFC GlobalId (`--use-element-guids`) and keep surface-style
  colours. Names, classes, storeys and psets are not written to GLB, so `elements.json` holds them
  and joins on `guid`.
- **Known issues:** digital_hub logs 403 `Failed to convert: IfcMaterial` errors, but the elements are still
  exported with their styles, so the errors are harmless. Aggregates (`IfcRoof`, `IfcStair`) get bboxes rolled up from their parts
  (`bbox_source: "parts"`). IFC2X3 MEP uses generic `IfcFlowSegment`/`IfcFlowFitting` classes, so the category comes from the
  type object (pipe / pipe_fitting / valve …).

## elements.json

```json
{"guid": "…", "name": "…", "ifc_class": "IfcWallStandardCase", "category": "wall",
 "predefined_type": "…", "type_name": "…", "storey": "Level 1", "storey_elevation_m": 0.0,
 "bbox_min": [x, y, z], "bbox_max": [x, y, z], "has_geometry": true, "bbox_source": "own"}
```

Units are metres in IFC world coordinates (Z-up). The GLB is exported Y-up, so `glb = (x, z, -y)`.

## Run it

```sh
# deps (ifcopenshell has no wheels for very new Pythons, so use 3.12)
uv venv -p 3.12 .venv && uv pip install --python .venv -r requirements.txt
# IfcConvert binary (pip ifcopenshell does not ship it)
mkdir -p tools && gh release download ifcconvert-0.8.4 -R IfcOpenShell/IfcOpenShell \
  -p 'ifcconvert-0.8.4-macosm164.zip' -D tools && (cd tools && unzip -o *.zip)
# dataset
curl -L -o ds.zip https://fwjydgxpttajiqpfmqtj.supabase.co/storage/v1/object/public/stoa-junction-2026/junction-dataset-preview.zip
mkdir -p data && unzip -q ds.zip -d data

# convert + index + validate
./tools/IfcConvert -j 8 --use-element-guids --y-up model.ifc model.glb
.venv/bin/python scripts/extract_elements.py model.ifc model.elements.json
.venv/bin/python scripts/validate_glb.py model.glb model.elements.json
```

To view a GLB, drag it onto https://gltf-viewer.donmccurdy.com or import it into Blender.

## Licences

- Code (`scripts/`): MIT, see `LICENSE`.
- `samples/aalseth_stairs.*`: derived from `stairs.blend.ifc` by OpeningDesign, Aalseth_Residence
  (https://github.com/OpeningDesign/Aalseth_Residence). Attribution goes to the entire project team. Licensed
  **CC BY-SA 4.0** (https://creativecommons.org/licenses/by-sa/4.0/).
- `samples/digital_hub_arc.*`: derived from DigitalHub (RWTH Aachen), copyright (c) 2020 RWTH Aachen
  University, E3D Institute of Energy Efficiency and Sustainable Building. **MIT License**.
- Duplex and clinic outputs are not included. The duplex is CC BY-ND 3.0, which allows no derivatives.
  Regenerate them locally from the dataset.
- The dataset itself is not redistributed here. It is for non-commercial use in the Junction challenge.
