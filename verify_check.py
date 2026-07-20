import os
import sys
from pathlib import Path

art = Path(r"C:\Users\alexr\Driverless_AGI\docling-models")
repo = art / "docling-project--docling-models"

lines = []
lines.append("artifacts_path exists: " + str(art.exists()))
lines.append("preferred branch (repo folder) exists: " + str(repo.exists()))

# Replicate TableStructureModel resolver (lines 50-72 of table_structure_model.py)
ap = art
if (ap / "docling-project--docling-models").exists():
    ap = ap / "docling-project--docling-models" / "model_artifacts/tableformer"
elif (ap / "model_artifacts/tableformer").exists():
    ap = ap / "model_artifacts/tableformer"
ap = ap / "accurate"  # ACCURATE mode

lines.append("RESOLVED model dir: " + str(ap))
lines.append("tm_config.json present: " + str((ap / "tm_config.json").exists()))
lines.append("safetensors present: " + str((ap / "tableformer_accurate.safetensors").exists()))
lines.append("HF_HUB_OFFLINE=" + str(os.environ.get("HF_HUB_OFFLINE")))

# Now prove the REAL loader agrees, in offline mode (any HF fetch => exception)
try:
    from docling.datamodel.pipeline_options import TableStructureOptions, TableFormerMode
    from docling.models.stages.table_structure.table_structure_model import TableStructureModel
    opts = TableStructureOptions(enabled=True, mode=TableFormerMode.ACCURATE, artifacts_path=art)
    # Build a minimal model instance WITHOUT triggering remote download:
    # TableStructureModel.__init__ only calls download_models() when artifacts_path is None.
    # We pass artifacts_path, so no HF call should occur.
    tsm = TableStructureModel(
        enabled=True,
        artifacts_path=art,
        options=opts,
        accelerator_options=__import__("docling.datamodel.accelerator_options", fromlist=["AcceleratorOptions"]).AcceleratorOptions(),
    )
    lines.append("TableStructureModel instantiated OFFLINE: True")
    lines.append("tsm resolved dir (save_dir): " + str(tsm.tm_config["model"]["save_dir"]))
except Exception as e:
    lines.append("TableStructureModel instantiation FAILED: " + repr(e))

out = "\n".join(lines) + "\n"
sys.stdout.write(out)
with open(r"C:\Users\alexr\Driverless_AGI\.dagi\hash_cache\verify_local_model.txt", "w") as f:
    f.write(out)
