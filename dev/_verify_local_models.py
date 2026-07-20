"""Verify docling loads TableFormer/heron weights from the local models/ dir,
not from Hugging Face -- HF_HUB_OFFLINE=1 makes any network fetch attempt
raise instead of silently succeeding.
"""
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from pathlib import Path
from tools._pdf_convert import _DOCLING_ARTIFACTS_PATH, convert_pdf

root = Path(r"C:\Users\alexr\Driverless_AGI")
print("artifacts path:", _DOCLING_ARTIFACTS_PATH, "exists:", _DOCLING_ARTIFACTS_PATH.is_dir())

pdf = root / "tests" / "fixtures" / "pdf" / "sample_digital.pdf"
md, cache_path = convert_pdf(pdf, root)
print("\nConversion succeeded fully offline (HF_HUB_OFFLINE=1) -- proves local artifacts_path was used.")
print(md[:300])
