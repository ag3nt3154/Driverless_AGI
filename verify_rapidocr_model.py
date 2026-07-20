import os
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\alexr\anaconda3\envs\dagi\Lib\site-packages")

from docling.datamodel.pipeline_options import RapidOcrOptions
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel

art = Path(r"C:\Users\alexr\Driverless_AGI\models\rapidocr_models")
opts = RapidOcrOptions(lang=["english"], backend="onnxruntime")
repo_folder = RapidOcrModel._model_repo_folder  # "RapidOcr"

lines = []
lines.append("HF_HUB_OFFLINE=" + str(os.environ.get("HF_HUB_OFFLINE")))
lines.append("artifacts_path exists: " + str(art.exists()))
lines.append("expected repo dir (artifacts_path/RapidOcr): " + str((art / repo_folder).exists()))

# Replicate loader resolver (lines 369-382 of rapid_ocr_model.py)
def resolve_artifact_path(key, path):
    if path is None:
        return None
    return art / repo_folder / path

det = resolve_artifact_path("det_model_path", opts.det_model_path)
cls = resolve_artifact_path("cls_model_path", opts.cls_model_path)
rec = resolve_artifact_path("rec_model_path", opts.rec_model_path)
rec_keys = resolve_artifact_path("rec_keys_path", opts.rec_keys_path)

lines.append("det resolves: " + str(det) + "  exists=" + str(det.exists() if det else "N/A"))
lines.append("cls resolves: " + str(cls) + "  exists=" + str(cls.exists() if cls else "N/A"))
lines.append("rec resolves: " + str(rec) + "  exists=" + str(rec.exists() if rec else "N/A"))
lines.append("rec_keys resolves: " + str(rec_keys) + "  (None => built-in dict, OK)")

# Real instantiation OFFLINE (download_models only if artifacts_path is None)
try:
    rom = RapidOcrModel(
        enabled=True,
        artifacts_path=art,
        options=opts,
        accelerator_options=AcceleratorOptions(),
    )
    lines.append("RapidOcrModel instantiated OFFLINE: True")
    # Confirm the reader was built with local model paths
    p = rom.reader.engine.engine_manager.params if hasattr(rom.reader, "engine") else None
    lines.append("reader built: " + str(rom.reader is not None))
except Exception as e:
    lines.append("RapidOcrModel instantiation FAILED: " + repr(e))

out = "\n".join(lines) + "\n"
sys.stdout.write(out)
with open(r"C:\Users\alexr\Driverless_AGI\.dagi\hash_cache\verify_rapidocr_model.txt", "w") as f:
    f.write(out)
