"""Build-time: pack the default static model into the package tree.

Run BEFORE building the wheel. The output dir is gitignored and never
committed; it exists only so hatchling can pack it. In a dev checkout where
this has not run, the provider falls back to a one-time download by name.
"""
from pathlib import Path
import urllib.request

from model2vec import StaticModel

NAME = "minishlab/potion-base-8M"
OUT = Path(__file__).resolve().parent.parent / "docmancer" / "_models" / "potion-base-8M"
OUT.mkdir(parents=True, exist_ok=True)
StaticModel.from_pretrained(NAME).save_pretrained(str(OUT))

# Ship the model's license next to the weights (potion models are MIT).
lic = OUT / "LICENSE"
if not lic.exists():
    try:
        urllib.request.urlretrieve(
            f"https://huggingface.co/{NAME}/resolve/main/LICENSE", str(lic)
        )
    except Exception:
        lic.write_text("potion-base-8M is distributed under the MIT License by MinishLab.\n")

size_mb = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
print(f"vendored {NAME} to {OUT} ({size_mb:.1f} MB)")
assert size_mb < 95, f"vendored model {size_mb:.1f} MB exceeds safe PyPI per-file budget"
