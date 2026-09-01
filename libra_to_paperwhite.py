#!/usr/bin/env python3
"""
libra_to_paperwhite.py — Reconvertit un CBZ déjà découpé case par case
(ex : généré pour la Kobo Libra Colour) vers le format d'une autre liseuse,
par défaut la Kindle Paperwhite 2 (758x1024, niveaux de gris).

Pas de redétection des cases ici : chaque image du CBZ d'entrée est déjà
une case (ou une page de manga déjà au bon découpage) — ce script se
contente de la redimensionner (sans déformation, même logique que
bd_to_kobo.py) et de la recompresser pour la nouvelle liseuse.

Installation :
    pip install pillow --break-system-packages

Utilisation :
    python3 libra_to_paperwhite.py entree.cbz sortie.cbz
    python3 libra_to_paperwhite.py entree.cbz sortie.cbz --width 758 --height 1024 --quality 80 --grayscale
    python3 libra_to_paperwhite.py entree.cbz sortie.cbz --no-grayscale     # garder la couleur mais changer la taille
"""

import argparse
import io
import os
import re
import sys
import zipfile

from PIL import Image

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")


def natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def fit_no_stretch(im, target_w, target_h, bg):
    pw, ph = im.size
    scale = min(target_w / pw, target_h / ph)
    new_w, new_h = max(1, round(pw * scale)), max(1, round(ph * scale))
    resized = im.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new(im.mode, (target_w, target_h), bg)
    canvas.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2))
    return canvas


def convert(input_cbz, output_cbz, width, height, quality, grayscale):
    with zipfile.ZipFile(input_cbz) as zin:
        names = sorted(
            (n for n in zin.namelist() if n.lower().endswith(IMG_EXT)),
            key=natkey,
        )
        if not names:
            sys.exit("Aucune image trouvée dans le CBZ d'entrée.")

        with zipfile.ZipFile(output_cbz, "w", zipfile.ZIP_STORED) as zout:
            for i, name in enumerate(names, start=1):
                data = zin.read(name)
                im = Image.open(io.BytesIO(data)).convert("RGB")
                if grayscale:
                    im = im.convert("L")
                    bg = 255
                else:
                    bg = (255, 255, 255)
                im2 = fit_no_stretch(im, width, height, bg)
                buf = io.BytesIO()
                im2.save(buf, format="JPEG", quality=quality)
                zout.writestr(f"{i:04d}.jpg", buf.getvalue())
                if i % 25 == 0 or i == len(names):
                    print(f"  {i}/{len(names)} pages converties")

    print(f"\nCBZ généré : {output_cbz} ({len(names)} pages)")


def main():
    p = argparse.ArgumentParser(description="Reconvertit un CBZ déjà découpé vers une autre résolution/format de liseuse.")
    p.add_argument("input", help="CBZ source (déjà découpé case par case)")
    p.add_argument("output", help="CBZ de sortie")
    p.add_argument("--width", type=int, default=758, help="Largeur cible (Paperwhite 2 : 758)")
    p.add_argument("--height", type=int, default=1024, help="Hauteur cible (Paperwhite 2 : 1024)")
    p.add_argument("--quality", type=int, default=80, help="Qualité JPEG 1-100 (défaut 80)")
    p.add_argument("--grayscale", dest="grayscale", action="store_true", default=True,
                    help="Niveaux de gris (activé par défaut, pour Paperwhite)")
    p.add_argument("--no-grayscale", dest="grayscale", action="store_false",
                    help="Garder la couleur (juste redimensionner)")
    args = p.parse_args()

    convert(args.input, args.output, args.width, args.height, args.quality, args.grayscale)


if __name__ == "__main__":
    main()
