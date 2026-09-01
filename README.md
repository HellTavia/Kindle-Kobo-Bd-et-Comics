Kindle-Kobo-Bd-et-Comics

Découpe une BD ou un comics case par case pour la rendre lisible en plein écran sur une liseuse, sans avoir à zoomer. Pensé à l'origine pour la BD franco-belge (grilles de cases avec bordures noires), mais fonctionne aussi sur du comics ou du manga déjà en couleur.

Chaque case détectée devient une page à part entière du fichier de sortie, redimensionnée à la taille exacte de l'écran de la liseuse sans être déformée (même échelle en largeur et en hauteur, avec des marges blanches si besoin plutôt qu'un étirement).

Comment ça marche

Le script ouvre chaque page de l'album (CBZ/CBR/PDF/dossier d'images).
Il détecte automatiquement les cases (analyse du fond clair autour de chaque case + des bordures noires qui les séparent).
Chaque case est recadrée, redimensionnée à la résolution de l'écran visé, puis toutes les cases sont réassemblées dans l'ordre de lecture en un nouveau fichier CBZ, prêt à copier sur la liseuse.

La détection est automatique et fonctionne bien sur la majorité des pages, mais reste une heuristique : sur certaines mises en page inhabituelles (cases collées sans espace blanc, grandes illustrations pleine page, bulles qui débordent), le découpage peut être imparfait. D'où l'outil de relecture manuelle (voir plus bas) pour corriger ponctuellement sans tout refaire.

Fichiers du projet:

bd_to_kobo.py	Le cœur du projet : détection des cases + génération du CBZ, en ligne de commande

bd_to_kobo_gui.py	Interface graphique pour bd_to_kobo.py (mêmes fonctions, sans taper de commandes)

revue.html	Outil de relecture visuelle : corriger les cases à la souris avant l'export final

libra_to_paperwhite.py	Convertit un CBZ déjà découpé vers une autre résolution/liseuse, sans redétection (rapide)

fix_red_background.py	Corrige a posteriori un bug d'affichage (fond rouge au lieu de blanc) sur un CBZ déjà généré

bd_to_kobo_gui.py a besoin de bd_to_kobo.py dans le même dossier. bd_to_kobo.py copie automatiquement revue.html dans le dossier de relecture — gardez donc les deux ensemble aussi.

Installation
bash
pip install pillow numpy scipy --break-system-packages

Optionnel selon les besoins :

bash
pip install pymupdf --break-system-packages   # pour lire directement un .pdf
sudo apt install python3-tk                   # pour l'interface graphique (Linux)

Rendre les scripts exécutables (facultatif, permet de lancer ./script.py au lieu de python3 script.py) :

bash
chmod +x bd_to_kobo.py bd_to_kobo_gui.py libra_to_paperwhite.py fix_red_background.py
Formats d'entrée acceptés
.cbz / .zip
.pdf (nécessite PyMuPDF, voir installation)
un dossier contenant déjà les images de l'album

Les .cbr (archives RAR) ne sont pas supportés directement — il faut les reconvertir en .cbz au préalable (7-Zip, WinRAR, etc.).

Utilisation
Option A — Ligne de commande, conversion directe
bash
python3 bd_to_kobo.py album.cbz sortie.cbz --width 1264 --height 1680 --quality 90
Option B — Interface graphique
bash
python3 bd_to_kobo_gui.py

Choisir le fichier source, un profil de liseuse (ou des dimensions personnalisées), puis cliquer sur Générer.

Option C — Avec relecture manuelle (recommandé pour un premier essai)

Pour corriger à la main les cases mal détectées avant de figer le résultat :

1. Export pour relecture

bash
python3 bd_to_kobo.py album.cbz --export-review dossier_revue/

Crée dossier_revue/ avec les pages, les cases détectées (boxes.json) et une copie de revue.html.

2. Correction visuelle

Ouvrir dossier_revue/revue.html dans un navigateur, charger le dossier. Pour chaque page : glisser une case pour la déplacer, tirer un coin pour la redimensionner, "+ Ajouter une case" pour une case oubliée (dessiner au clic-glissé), "Supprimer la case" ou touche Suppr pour en effacer une. Cliquer "Enregistrer boxes.json" régulièrement (télécharge le fichier — remplacer celui du dossier dossier_revue par la version téléchargée).

3. Génération du CBZ final

bash
python3 bd_to_kobo.py --from-review dossier_revue/ sortie.cbz --width 1264 --height 1680

Le dossier de relecture ne dépend pas de la liseuse cible : on peut relire une seule fois puis générer plusieurs sorties (Libra, Paperwhite...) à partir du même dossier_revue/.

Profils de liseuses
Liseuse	Commande
Kobo Libra Colour (couleur, 1264×1680)	--width 1264 --height 1680 --quality 90
Kindle Paperwhite 2 (niveaux de gris, 758×1024)	--width 758 --height 1024 --quality 80 --grayscale
Autre liseuse	Adapter --width/--height à la résolution de l'écran (en portrait), --grayscale si l'écran n'est pas couleur

Résumé des options utiles :

Option	Rôle
--width, --height	Résolution cible en pixels (portrait)
--quality	Qualité JPEG 1-100 — 80-90 est un bon compromis poids/netteté
--grayscale	Sortie en niveaux de gris (écrans non couleur)
--margin	Marge en pixels gardée autour de chaque case détectée (défaut : 4)
--upscale-limit	Agrandissement maximum d'une case (évite le flou sur les toutes petites cases, défaut : x4)
Convertir un CBZ déjà découpé vers une autre liseuse

Si un CBZ est déjà bien découpé (une case = une image) pour une liseuse et qu'il faut juste l'adapter à une autre, libra_to_paperwhite.py est plus rapide que de repasser par la détection complète :

bash
python3 libra_to_paperwhite.py entree.cbz sortie.cbz --width 758 --height 1024 --quality 80 --grayscale

(par défaut déjà réglé sur les valeurs Paperwhite 2 ; --no-grayscale pour garder la couleur)

Corriger un CBZ déjà généré (fond rouge au lieu de blanc)

Un bug d'affichage (corrigé depuis dans bd_to_kobo.py) pouvait donner un fond rouge pur autour des cases sur les exports en couleur. Pour rattraper des fichiers déjà générés sans tout refaire :

bash
python3 fix_red_background.py entree.cbz sortie_corrigee.cbz
# ou plusieurs fichiers d'un coup :
python3 fix_red_background.py --batch *.cbz
Limites connues
La détection des cases est une heuristique : très fiable sur les grilles classiques, moins sur les pages avec beaucoup de cases collées sans gouttière, ou les illustrations pleine page avec incrustations.
Le format CBZ ne porte pas de métadonnées (auteur, titre...) : certaines liseuses afficheront "Auteur inconnu" même si le contenu est correct.
Après un gros transfert USB, certaines liseuses (Kobo) mettent quelques minutes à générer les vignettes de couverture — ce n'est pas un bug du script.
