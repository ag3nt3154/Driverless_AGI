import os
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\alexr\anaconda3\envs\dagi\Lib\site-packages")

from docling.datamodel.pipeline_options import LayoutOptions
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.models.stages.layout.layout_model import LayoutModel

art = Path(r"C:\Users\alexr\Driverless_AGI\docling-models")
spec = LayoutOptions().model_spec
repo_folder = spec.model_repo_folder  # docling-project--docling-layout-heron
expected = art / repo_folder

lines = []
lines.append("HF_HUB_OFFLINE=" + str(os.environ.get("HF_HUB_OFFLINE")))
lines.append("artifacts_path exists: " + str(art.exists()))
lines.append("expected repo dir exists: " + str(expected.exists()))
lines.append("expected repo dir: " + str(expected))

# Replicate loader resolver (lines 66-83 of layout_model.py), model_path==""
ap = art
if (ap / repo_folder).exists():
    ap = ap / repo_folder / spec.model_path  # model_path is ""
elif (ap / spec.model_path).exists():
    ap = ap / spec.model_path
lines.append("RESOLVED layout artifact_path: " + str(ap))
lines.append("config.json present: " + str((ap / "config.json").exists()))
lines.append("model.safetensors present: " + str((ap / "model.safetensors").exists()))

# Real instantiation OFFLINE (download_models only called if artifacts_path is None)
try:
    opts = LayoutOptions()
    lm = LayoutModel(
        options=opts,
        artifacts_path=art,
        accelerator_options=AcceleratorOptions(),
    )
    lines.append("LayoutModel instantiated OFFLINE: True")
    lines.append("layout_predictor type: " + type(lm.layout_predictor).__name__)
except Exception as e:
    lines.append("LayoutModel instantiation FAILED: " + repr(e))

out = "\n".join(lines) + "\n"
sys.stdout.write(out)
with open(r"C:\Users\alexr\Driverless_AGI\.dagi\hash_cache\verify_layout_model.txt", "w") as f:
    f.write(out)
