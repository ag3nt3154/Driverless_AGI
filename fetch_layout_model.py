import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\alexr\anaconda3\envs\dagi\Lib\site-packages")

from docling.models.stages.layout.layout_model import LayoutModel
from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_HERON

dest = Path(r"C:\Users\alexr\Driverless_AGI\docling-models")
dest.mkdir(parents=True, exist_ok=True)

print("Fetching layout model:", DOCLING_LAYOUT_HERON.repo_id, "rev", DOCLING_LAYOUT_HERON.revision)
out = LayoutModel.download_models(local_dir=dest, force=False, progress=True)
print("DOWNLOADED TO:", out)
print("repo_folder name:", DOCLING_LAYOUT_HERON.model_repo_folder)

repo_dir = dest / DOCLING_LAYOUT_HERON.model_repo_folder
print("repo_dir exists:", repo_dir.exists())
if repo_dir.exists():
    print("repo_dir contents:", sorted(p.name for p in repo_dir.iterdir()))
