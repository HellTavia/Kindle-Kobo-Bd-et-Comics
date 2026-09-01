#!/usr/bin/env python3
"""
bd_to_kobo.py — Découpe une BD (case par case) et exporte un CBZ prêt
pour liseuse (par défaut calé sur la Kobo Libra Colour, 1264x1680).

Fonctionne sur :
  - un fichier .cbz / .zip (images à l'intérieur)
  - un fichier .pdf (nécessite PyMuPDF : pip install pymupdf)
  - un dossier contenant déjà les images de la BD

Installation des dépendances :
    pip install pillow numpy scipy img2pdf --break-system-packages
    pip install pymupdf --break-system-packages   # optionnel, pour lire les PDF

Utilisation :
    python3 bd_to_kobo.py entree.cbz sortie.cbz
    python3 bd_to_kobo.py mon_dossier_images/ sortie.cbz
    python3 bd_to_kobo.py entree.pdf sortie.cbz --width 1264 --height 1680

Réglages utiles :
    --width / --height   résolution cible (par défaut Kobo Libra Colour)
    --upscale-limit      agrandissement max d'une case (défaut x4, évite le flou)
    --margin             marge en pixels gardée autour de chaque case (défaut 4)
    --keep-temp          ne pas supprimer le dossier temporaire de travail
"""

import argparse
import io
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile

import numpy as np
from PIL import Image
from scipy import ndimage

# ---------------------------------------------------------------------------
# 1. Détection des cases (flood-fill sur le fond clair, robuste aux scans
#    réels : éclairage non uniforme, art en pleine page, couleurs sombres)
# ---------------------------------------------------------------------------

def load_gray(path):
    im = Image.open(path).convert("RGB")
    gray = np.array(im.convert("L"))
    return im, gray


def estimate_background_level(gray):
    hist = np.bincount(gray.ravel(), minlength=256)
    bright_hist = hist[150:]
    return 150 + int(np.argmax(bright_hist))


def background_mask(gray, margin_below_bg=45):
    bg = estimate_background_level(gray)
    thresh = max(150, bg - margin_below_bg)
    return gray >= thresh


def merge_overlapping(panels):
    def overlaps(a, b):
        ax0, ay0, ax1, ay1 = a
        bx0, by0, bx1, by1 = b
        ix0, iy0 = max(ax0, bx0), max(ay0, by0)
        ix1, iy1 = min(ax1, bx1), min(ay1, by1)
        return ix1 > ix0 and iy1 > iy0

    boxes = list(panels)
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if overlaps(boxes[i], boxes[j]):
                    a, b = boxes[i], boxes[j]
                    boxes[i] = (min(a[0], b[0]), min(a[1], b[1]),
                                max(a[2], b[2]), max(a[3], b[3]))
                    del boxes[j]
                    changed = True
                    break
            if changed:
                break
    return boxes


def reading_order(panels, y_tol_frac=0.35):
    if not panels:
        return panels
    avg_h = sum(p[3] - p[1] for p in panels) / len(panels)
    tol = avg_h * y_tol_frac
    panels_sorted = sorted(panels, key=lambda p: p[1])
    rows = []
    for p in panels_sorted:
        for row in rows:
            if abs(row[0][1] - p[1]) <= tol:
                row.append(p)
                break
        else:
            rows.append([p])
    result = []
    for row in rows:
        row.sort(key=lambda p: p[0])
        result.extend(row)
    return result


def detect_panels(gray, min_panel_frac=0.012):
    h, w = gray.shape
    bg_mask = background_mask(gray)
    structure = np.ones((3, 3), dtype=int)
    labels, _ = ndimage.label(bg_mask, structure=structure)

    border_ids = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    border_ids.discard(0)
    gutter_network = np.isin(labels, list(border_ids)) if border_ids else np.zeros_like(bg_mask)

    panel_mask = ~gutter_network
    plabels, pn = ndimage.label(panel_mask, structure=structure)
    if pn == 0:
        return [(0, 0, w, h)]

    min_area = min_panel_frac * h * w
    panels = []
    for i, sl in enumerate(ndimage.find_objects(plabels), start=1):
        if sl is None:
            continue
        ys, xs = sl
        area = (plabels[sl] == i).sum()
        if area < min_area:
            continue
        x0, x1, y0, y1 = xs.start, xs.stop, ys.start, ys.stop
        if (x1 - x0) < w * 0.04 or (y1 - y0) < h * 0.03:
            continue
        panels.append((x0, y0, x1, y1))

    panels = merge_overlapping(panels)
    if not panels:
        panels = [(0, 0, w, h)]

    # Stage 2: refine each flood-fill blob with a local whitespace cut.
    # Flood-fill can under-split when two panels are bridged by a single
    # thin dark path somewhere else on the page (a shared border, a
    # caption box touching both) even though a clean gutter exists at
    # most x/y positions. A local, region-scaled whitespace scan (not
    # affected by page-wide vignetting since it only looks at this one
    # blob) catches what the global flood-fill missed.
    refined = []
    for (x0, y0, x1, y1) in panels:
        sub = gray[y0:y1, x0:x1]
        pieces = _whitespace_refine(sub, x0, y0, page_h=h, page_w=w)
        if len(pieces) > 6:
            # runaway refinement (usually a near-blank text page or a
            # heavily textured panel) - trust the flood-fill blob instead
            pieces = [(x0, y0, x1, y1)]
        refined.extend(pieces)

    refined = reading_order(refined)
    return refined


def _looks_like_real_gutter(region, axis, b0, b1, check_margin=20, black_thresh=90, min_black_frac=0.22):
    """A genuine panel gutter is flanked by the panels' drawn black frame
    line. A speech-bubble's white interior can also look like a 'gutter'
    locally (spans most of the panel width) but has no such frame right
    next to it - use that to tell the two apart."""
    h, w = region.shape
    total = h if axis == 'row' else w

    def black_frac_at(pos):
        if pos < 0 or pos >= total:
            return 0.0
        if axis == 'row':
            band = region[max(0, pos-1):pos+2, :]
        else:
            band = region[:, max(0, pos-1):pos+2]
        return (band < black_thresh).mean()

    before = max(black_frac_at(b0 - k) for k in range(1, check_margin))
    after = max(black_frac_at(b1 + k) for k in range(1, check_margin))
    return before >= min_black_frac or after >= min_black_frac


def _whitespace_refine(region, ox, oy, page_h, page_w, axis='row', depth=0, max_depth=6):
    h, w = region.shape
    if h < 40 or w < 40 or depth > max_depth:
        return [(ox, oy, ox + w, oy + h)]

    local_bg = estimate_background_level(region)
    bg_thresh = max(150, local_bg - 15)
    is_bg = region >= bg_thresh

    if axis == 'row':
        frac = is_bg.mean(axis=1)
        total = h
        page_total = page_h
    else:
        frac = is_bg.mean(axis=0)
        total = w
        page_total = page_w

    is_gutter = frac >= 0.80
    bands = []
    i, n = 0, len(is_gutter)
    while i < n:
        if is_gutter[i]:
            j = i
            while j < n and is_gutter[j]:
                j += 1
            bands.append((i, j))
            i = j
        else:
            i += 1

    # Real panel gutters are thin dividing gaps (a few px). A text bubble's
    # white interior can also read as "background" across a wide span, but
    # it's much thicker than a gutter - use that to exclude it here, before
    # even checking for a flanking border line.
    max_gutter_px = max(15, int(page_total * 0.025))
    bands = [(b0, b1) for (b0, b1) in bands if (b1 - b0) <= max_gutter_px]

    min_seg = max(30, int(page_total * 0.045))
    segs = []
    prev = 0
    for (b0, b1) in bands:
        mid = (b0 + b1) // 2
        if mid - prev >= min_seg and _looks_like_real_gutter(region, axis, b0, b1):
            segs.append((prev, mid))
            prev = mid
    if total - prev >= min_seg:
        segs.append((prev, total))
    if not segs:
        segs = [(0, total)]
    if len(segs) > 6:
        segs = [(0, total)]

    other = 'col' if axis == 'row' else 'row'
    if len(segs) <= 1:
        return _whitespace_refine(region, ox, oy, page_h, page_w, axis=other, depth=depth + 1, max_depth=max_depth)

    out = []
    for (s0, s1) in segs:
        if axis == 'row':
            sub = region[s0:s1, :]
            nox, noy = ox, oy + s0
        else:
            sub = region[:, s0:s1]
            nox, noy = ox + s0, oy
        out.extend(_whitespace_refine(sub, nox, noy, page_h, page_w, axis=other, depth=depth + 1, max_depth=max_depth))
    return out


# ---------------------------------------------------------------------------
# 2. Redimensionnement sans déformation (même échelle en X et Y)
# ---------------------------------------------------------------------------

def fit_no_stretch(panel_im, target_w, target_h, upscale_limit=4.0, bg=255, grayscale=False):
    if grayscale:
        panel_im = panel_im.convert("L")
    pw, ph = panel_im.size
    scale = min(target_w / pw, target_h / ph, upscale_limit)
    new_w, new_h = max(1, round(pw * scale)), max(1, round(ph * scale))
    resized = panel_im.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new(panel_im.mode, (target_w, target_h), bg)
    canvas.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2))
    return canvas


# ---------------------------------------------------------------------------
# 3. Entrée : dossier / cbz / pdf -> dossier d'images ordonné
# ---------------------------------------------------------------------------

IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")


def natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def prepare_pages(input_path, work_dir):
    pages_dir = os.path.join(work_dir, "pages")
    os.makedirs(pages_dir, exist_ok=True)

    if os.path.isdir(input_path):
        files = sorted(
            (f for f in os.listdir(input_path) if f.lower().endswith(IMG_EXT)),
            key=natkey,
        )
        for i, f in enumerate(files, start=1):
            ext = os.path.splitext(f)[1]
            shutil.copy(os.path.join(input_path, f), os.path.join(pages_dir, f"{i:04d}{ext}"))

    elif input_path.lower().endswith((".cbz", ".zip")):
        with zipfile.ZipFile(input_path) as z:
            names = sorted(
                (n for n in z.namelist() if n.lower().endswith(IMG_EXT)), key=natkey
            )
            for i, n in enumerate(names, start=1):
                ext = os.path.splitext(n)[1]
                with z.open(n) as src, open(os.path.join(pages_dir, f"{i:04d}{ext}"), "wb") as dst:
                    dst.write(src.read())

    elif input_path.lower().endswith(".pdf"):
        try:
            import fitz  # PyMuPDF
        except ImportError:
            sys.exit("Pour lire un PDF il faut PyMuPDF : pip install pymupdf --break-system-packages")
        doc = fitz.open(input_path)
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(dpi=300)
            pix.save(os.path.join(pages_dir, f"{i:04d}.png"))

    else:
        sys.exit(f"Format d'entrée non reconnu : {input_path}")

    return sorted(
        (os.path.join(pages_dir, f) for f in os.listdir(pages_dir) if f.lower().endswith(IMG_EXT)),
        key=natkey,
    )


# ---------------------------------------------------------------------------
# 4. Mode relecture : export des pages + boîtes pour ajustement manuel,
#    puis reconstruction du CBZ final à partir des boîtes corrigées.
# ---------------------------------------------------------------------------

REVIEW_TOOL_FILENAME = "revue.html"


def export_review(input_path, review_dir, keep_temp=False):
    work_dir = tempfile.mkdtemp(prefix="bd_to_kobo_")
    try:
        page_paths = prepare_pages(input_path, work_dir)
        if not page_paths:
            sys.exit("Aucune image trouvée en entrée.")

        pages_out = os.path.join(review_dir, "pages")
        os.makedirs(pages_out, exist_ok=True)

        pages_json = []
        for pidx, page_path in enumerate(page_paths, start=1):
            im, gray = load_gray(page_path)
            panels = detect_panels(gray)
            fname = f"{pidx:04d}.jpg"
            im.convert("RGB").save(os.path.join(pages_out, fname), quality=88)
            pages_json.append({
                "file": fname,
                "width": im.width,
                "height": im.height,
                "panels": [list(map(int, p)) for p in panels],
            })
            print(f"  page {pidx}/{len(page_paths)} : {len(panels)} case(s)")

        with open(os.path.join(review_dir, "boxes.json"), "w", encoding="utf-8") as f:
            json.dump({"pages": pages_json}, f, ensure_ascii=False, indent=1)

        tool_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), REVIEW_TOOL_FILENAME)
        if os.path.exists(tool_src):
            shutil.copy(tool_src, os.path.join(review_dir, REVIEW_TOOL_FILENAME))
        else:
            print(f"ATTENTION : {REVIEW_TOOL_FILENAME} introuvable à côté du script — gardez les deux fichiers ensemble.")

        print(f"\nDossier de relecture prêt : {review_dir}")
        print(f"Ouvrez {os.path.join(review_dir, REVIEW_TOOL_FILENAME)} dans un navigateur pour corriger les cases.")
        print(f"Une fois terminé : python3 {os.path.basename(__file__)} --from-review \"{review_dir}\" sortie.cbz")
    finally:
        if keep_temp:
            print("Dossier temporaire conservé :", work_dir)
        else:
            shutil.rmtree(work_dir, ignore_errors=True)


def build_from_review(review_dir, output_cbz, width, height, upscale_limit, margin, quality=90, grayscale=False):
    boxes_path = os.path.join(review_dir, "boxes.json")
    if not os.path.exists(boxes_path):
        sys.exit(f"boxes.json introuvable dans {review_dir} (avez-vous bien exporté avec --export-review ?)")
    with open(boxes_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pages_dir = os.path.join(review_dir, "pages")
    work_dir = tempfile.mkdtemp(prefix="bd_to_kobo_build_")
    try:
        export_dir = os.path.join(work_dir, "export")
        os.makedirs(export_dir, exist_ok=True)

        panel_paths = []
        for pidx, page in enumerate(data["pages"], start=1):
            page_path = os.path.join(pages_dir, page["file"])
            im = Image.open(page_path).convert("RGB")
            panels = page["panels"]
            for cidx, (x0, y0, x1, y1) in enumerate(panels, start=1):
                x0m, y0m = max(0, x0 - margin), max(0, y0 - margin)
                x1m, y1m = min(im.width, x1 + margin), min(im.height, y1 + margin)
                crop = im.crop((x0m, y0m, x1m, y1m))
                canvas = fit_no_stretch(crop, width, height, upscale_limit, grayscale=grayscale)
                out_path = os.path.join(export_dir, f"p{pidx:04d}_c{cidx:02d}.jpg")
                canvas.save(out_path, quality=quality)
                panel_paths.append(out_path)
            print(f"  page {pidx}/{len(data['pages'])} : {len(panels)} case(s)")

        with zipfile.ZipFile(output_cbz, "w", zipfile.ZIP_STORED) as z:
            for i, p in enumerate(sorted(panel_paths, key=natkey), start=1):
                z.write(p, arcname=f"{i:04d}.jpg")

        print(f"\nCBZ généré : {output_cbz} ({len(panel_paths)} pages)")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5. Pipeline complet (mode simple, sans relecture)
# ---------------------------------------------------------------------------

def run(input_path, output_cbz, width, height, upscale_limit, margin, keep_temp=False, quality=90, grayscale=False):
    work_dir = tempfile.mkdtemp(prefix="bd_to_kobo_")
    try:
        page_paths = prepare_pages(input_path, work_dir)
        if not page_paths:
            sys.exit("Aucune image trouvée en entrée.")

        export_dir = os.path.join(work_dir, "export")
        os.makedirs(export_dir, exist_ok=True)

        panel_paths = []
        for pidx, page_path in enumerate(page_paths, start=1):
            im, gray = load_gray(page_path)
            panels = detect_panels(gray)
            for cidx, (x0, y0, x1, y1) in enumerate(panels, start=1):
                x0m, y0m = max(0, x0 - margin), max(0, y0 - margin)
                x1m, y1m = min(im.width, x1 + margin), min(im.height, y1 + margin)
                crop = im.crop((x0m, y0m, x1m, y1m))
                canvas = fit_no_stretch(crop, width, height, upscale_limit, grayscale=grayscale)
                out_path = os.path.join(export_dir, f"p{pidx:04d}_c{cidx:02d}.jpg")
                canvas.save(out_path, quality=quality)
                panel_paths.append(out_path)
            print(f"  page {pidx}/{len(page_paths)} : {len(panels)} case(s)")

        with zipfile.ZipFile(output_cbz, "w", zipfile.ZIP_STORED) as z:
            for i, p in enumerate(sorted(panel_paths, key=natkey), start=1):
                z.write(p, arcname=f"{i:04d}.jpg")

        print(f"\nCBZ généré : {output_cbz} ({len(panel_paths)} pages)")
    finally:
        if keep_temp:
            print("Dossier temporaire conservé :", work_dir)
        else:
            shutil.rmtree(work_dir, ignore_errors=True)


def main():
    p = argparse.ArgumentParser(description="Découpe une BD case par case pour liseuse.")
    p.add_argument("input", nargs="?", help="Fichier .cbz/.zip/.pdf ou dossier d'images")
    p.add_argument("output", nargs="?", help="Fichier .cbz de sortie")
    p.add_argument("--width", type=int, default=1264, help="Largeur écran cible (Kobo Libra Colour : 1264)")
    p.add_argument("--height", type=int, default=1680, help="Hauteur écran cible (Kobo Libra Colour : 1680)")
    p.add_argument("--upscale-limit", type=float, default=4.0, help="Agrandissement max d'une case")
    p.add_argument("--margin", type=int, default=4, help="Marge en pixels gardée autour de chaque case")
    p.add_argument("--quality", type=int, default=90, help="Qualité JPEG (1-100). Baisser à 70-80 réduit bien le poids sans perte visible")
    p.add_argument("--grayscale", action="store_true", help="Sortie en niveaux de gris (liseuses non couleur : Kindle, Kobo non-Colour...)")
    p.add_argument("--keep-temp", action="store_true")
    p.add_argument("--export-review", metavar="DOSSIER",
                    help="Au lieu de générer le CBZ, exporte les pages + un outil de relecture visuelle (revue.html) dans DOSSIER")
    p.add_argument("--from-review", metavar="DOSSIER",
                    help="Construit le CBZ final à partir d'un dossier de relecture déjà corrigé (voir --export-review)")
    args = p.parse_args()

    if args.export_review:
        if not args.input:
            sys.exit("Précisez le fichier/dossier d'entrée : python3 bd_to_kobo.py entree.cbz --export-review dossier/")
        export_review(args.input, args.export_review, args.keep_temp)
        return

    if args.from_review:
        out = args.output or args.input
        if not out:
            sys.exit("Précisez le CBZ de sortie : python3 bd_to_kobo.py --from-review dossier/ sortie.cbz")
        build_from_review(args.from_review, out, args.width, args.height,
                           args.upscale_limit, args.margin, args.quality, args.grayscale)
        return

    if not args.input or not args.output:
        sys.exit("Usage : python3 bd_to_kobo.py entree.cbz sortie.cbz")

    run(args.input, args.output, args.width, args.height, args.upscale_limit, args.margin,
        args.keep_temp, args.quality, args.grayscale)


if __name__ == "__main__":
    main()
