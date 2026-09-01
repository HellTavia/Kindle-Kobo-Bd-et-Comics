#!/usr/bin/env python3
"""
fix_red_background.py — Corrige a posteriori le bug de fond rouge
(RGB 255,0,0) sur un CBZ déjà généré par bd_to_kobo.py, sans refaire
la détection des cases : ne touche que la couleur, rien d'autre.

Repeint en blanc tout pixel qui correspond exactement (ou presque) au
rouge du bug, en laissant le reste de l'image intact. Sans effet sur
les CBZ en niveaux de gris (le bug n'existe qu'en couleur).

Installation :
    pip install pillow numpy --break-system-packages

Utilisation :
    python3 fix_red_background.py entree.cbz sortie.cbz
    python3 fix_red_background.py *.cbz --in-place     # corrige plusieurs fichiers sur eux-mêmes
"""

import argparse
import glob
import io
import os
import sys
import zipfile

import numpy as np
from PIL import Image

BUG_RED = (255, 0, 0)


def fix_image(im, tolerance=10):
    """Repeint en blanc les pixels proches du rouge du bug (255,0,0).
    Ne touche à rien d'autre (les vrais rouges d'une case, plus foncés
    ou pas purs à ce point, ne sont pas concernés)."""
    if im.mode != "RGB":
        return im, False
    arr = np.array(im)
    r, g, b = arr[..., 0].astype(int), arr[..., 1].astype(int), arr[..., 2].astype(int)
    mask = (r >= 255 - tolerance) & (g <= tolerance) & (b <= tolerance)
    if not mask.any():
        return im, False
    arr[mask] = (255, 255, 255)
    return Image.fromarray(arr, "RGB"), True


def fix_cbz(input_cbz, output_cbz):
    changed_count = 0
    total = 0
    with zipfile.ZipFile(input_cbz) as zin:
        names = zin.namelist()
        tmp_out = output_cbz + ".tmp"
        with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_STORED) as zout:
            for name in names:
                data = zin.read(name)
                if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
                    total += 1
                    im = Image.open(io.BytesIO(data))
                    fixed, changed = fix_image(im)
                    if changed:
                        changed_count += 1
                        buf = io.BytesIO()
                        save_kwargs = {"quality": 92} if name.lower().endswith((".jpg", ".jpeg")) else {}
                        fmt = "JPEG" if name.lower().endswith((".jpg", ".jpeg")) else im.format or "PNG"
                        fixed.save(buf, format=fmt, **save_kwargs)
                        data = buf.getvalue()
                zout.writestr(name, data)

    os.replace(tmp_out, output_cbz)
    print(f"{os.path.basename(input_cbz)} : {changed_count}/{total} image(s) corrigée(s) -> {output_cbz}")


def main():
    p = argparse.ArgumentParser(description="Corrige le fond rouge (bug) en blanc sur un ou plusieurs CBZ déjà générés.")
    p.add_argument("input", nargs="?", help="CBZ à corriger (mode simple, un seul fichier)")
    p.add_argument("output", nargs="?", help="CBZ de sortie (mode simple)")
    p.add_argument("--batch", nargs="+", metavar="CBZ",
                    help="Corrige plusieurs fichiers d'un coup (ex: --batch *.cbz). Ignore input/output.")
    p.add_argument("--in-place", action="store_true", help="Écrase directement chaque fichier (avec --batch), ou le fichier d'entrée en mode simple")
    p.add_argument("--suffix", default="_corrige", help="Suffixe ajouté au nom si ni --in-place ni sortie explicite (défaut : _corrige)")
    args = p.parse_args()

    if args.batch:
        files = []
        for pattern in args.batch:
            matches = glob.glob(pattern)
            files.extend(matches if matches else [pattern])
        for f in files:
            if not os.path.exists(f):
                print(f"Introuvable, ignoré : {f}")
                continue
            if args.in_place:
                fix_cbz(f, f)
            else:
                base, ext = os.path.splitext(f)
                fix_cbz(f, f"{base}{args.suffix}{ext}")
        return

    if not args.input:
        sys.exit("Usage : python3 fix_red_background.py entree.cbz sortie.cbz\n"
                  "    ou : python3 fix_red_background.py --batch *.cbz [--in-place]")

    if args.in_place:
        fix_cbz(args.input, args.input)
    elif args.output:
        fix_cbz(args.input, args.output)
    else:
        base, ext = os.path.splitext(args.input)
        fix_cbz(args.input, f"{base}{args.suffix}{ext}")


if __name__ == "__main__":
    main()
