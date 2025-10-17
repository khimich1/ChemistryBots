import os
from pathlib import Path

try:
    from PIL import Image
except Exception as e:
    print("Install pillow first: pip install Pillow")
    raise


def convert_dir_to_webp(source_dir: Path, quality: int = 82) -> None:
    source_dir = Path(source_dir)
    assert source_dir.exists(), f"Directory not found: {source_dir}"

    exts = {".jpg", ".jpeg", ".png"}
    out_count = 0
    for img_path in source_dir.iterdir():
        if img_path.suffix.lower() not in exts:
            continue
        out_path = img_path.with_suffix(".webp")
        try:
            with Image.open(img_path) as im:
                im.save(out_path, "WEBP", quality=quality, method=6)
            out_count += 1
            print(f"Converted: {img_path.name} -> {out_path.name}")
        except Exception as e:
            print(f"Failed: {img_path} — {e}")

    print(f"Done. Generated {out_count} webp files in {source_dir}")


if __name__ == "__main__":
    here = Path(__file__).resolve().parents[1] / "assets"
    convert_dir_to_webp(here)


