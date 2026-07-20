import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\alexr\anaconda3\envs\dagi\Lib\site-packages")

from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel

dest = Path(r"C:\Users\alexr\Driverless_AGI\models\rapidocr_models")
dest.mkdir(parents=True, exist_ok=True)

print("Downloading RapidOCR (english, onnxruntime) into:", dest)
out = RapidOcrModel.download_models(
    local_dir=dest,
    force=False,
    progress=True,
    lang="english",
    backend="onnxruntime",
)
print("DOWNLOADED TO:", out)
print("repo_folder name:", RapidOcrModel._model_repo_folder)

repo_dir = out  # download_models already returns the resolved local_dir
print("repo_dir exists:", repo_dir.exists())
if repo_dir.exists():
    print("repo_dir tree:")
    for p in sorted(repo_dir.rglob("*")):
        if p.is_file():
            print("  ", str(p.relative_to(repo_dir)))
