#!/usr/bin/env python3
"""
bd_to_kobo_gui.py — Interface graphique pour bd_to_kobo.py.

Doit être dans le MÊME dossier que bd_to_kobo.py.

Dépendance : tkinter (fait partie de Python, mais parfois pas installé
par défaut sur Linux). Si le lancement échoue avec une erreur du genre
"No module named tkinter" :
    sudo apt install python3-tk          (Debian/Ubuntu/Mint/MX Linux)

Lancement :
    python3 bd_to_kobo_gui.py
ou, une fois rendu exécutable (chmod +x bd_to_kobo_gui.py) :
    ./bd_to_kobo_gui.py
"""

import os
import sys
import queue
import threading
import traceback
import webbrowser

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext
except ImportError:
    sys.exit(
        "tkinter n'est pas installé. Sur Debian/Ubuntu/Mint/MX Linux :\n"
        "    sudo apt install python3-tk\n"
        "puis relancez ce script."
    )

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import bd_to_kobo as core
except ImportError:
    sys.exit("bd_to_kobo.py introuvable. Placez bd_to_kobo_gui.py dans le même dossier que bd_to_kobo.py.")


PRESETS = {
    "Kobo Libra Colour (1264x1680, couleur)": dict(width=1264, height=1680, quality=90, grayscale=False),
    "Kindle Paperwhite 2 (758x1024, niveaux de gris)": dict(width=758, height=1024, quality=80, grayscale=True),
    "Personnalisé": None,
}
PRESET_NAMES = list(PRESETS.keys())


class QueueWriter:
    """Redirige print()/stdout vers une file lue par l'interface."""
    def __init__(self, q):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(text)

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("BD → liseuse")
        root.geometry("760x680")
        root.minsize(620, 500)

        self.log_queue = queue.Queue()
        self.busy = False

        self._build_ui()
        self.root.after(100, self._poll_log)

    # ---------------------------------------------------------------- UI

    def _build_ui(self):
        pad = dict(padx=8, pady=4)

        # --- Fichier source ---
        f_src = ttk.LabelFrame(self.root, text="1. Fichier ou dossier source (BD)")
        f_src.pack(fill="x", **pad)
        self.input_var = tk.StringVar()
        ttk.Entry(f_src, textvariable=self.input_var).pack(side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(f_src, text="Parcourir…", command=self._browse_input).pack(side="left", padx=6)

        # --- Réglages liseuse ---
        f_set = ttk.LabelFrame(self.root, text="2. Réglages de sortie")
        f_set.pack(fill="x", **pad)

        row1 = ttk.Frame(f_set); row1.pack(fill="x", padx=6, pady=4)
        ttk.Label(row1, text="Liseuse :").pack(side="left")
        self.preset_var = tk.StringVar(value=PRESET_NAMES[0])
        preset_box = ttk.Combobox(row1, textvariable=self.preset_var, values=PRESET_NAMES,
                                   state="readonly", width=42)
        preset_box.pack(side="left", padx=6)
        preset_box.bind("<<ComboboxSelected>>", self._on_preset_change)

        row2 = ttk.Frame(f_set); row2.pack(fill="x", padx=6, pady=4)
        ttk.Label(row2, text="Largeur (px) :").pack(side="left")
        self.width_var = tk.IntVar(value=1264)
        ttk.Entry(row2, textvariable=self.width_var, width=7).pack(side="left", padx=(4, 16))
        ttk.Label(row2, text="Hauteur (px) :").pack(side="left")
        self.height_var = tk.IntVar(value=1680)
        ttk.Entry(row2, textvariable=self.height_var, width=7).pack(side="left", padx=(4, 16))
        ttk.Label(row2, text="Qualité JPEG :").pack(side="left")
        self.quality_var = tk.IntVar(value=90)
        ttk.Entry(row2, textvariable=self.quality_var, width=5).pack(side="left", padx=4)
        self.grayscale_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="Niveaux de gris", variable=self.grayscale_var).pack(side="left", padx=16)

        row3 = ttk.Frame(f_set); row3.pack(fill="x", padx=6, pady=4)
        ttk.Label(row3, text="Marge (px) :").pack(side="left")
        self.margin_var = tk.IntVar(value=4)
        ttk.Entry(row3, textvariable=self.margin_var, width=5).pack(side="left", padx=(4, 16))
        ttk.Label(row3, text="Agrandissement max :").pack(side="left")
        self.upscale_var = tk.DoubleVar(value=4.0)
        ttk.Entry(row3, textvariable=self.upscale_var, width=5).pack(side="left", padx=4)

        # --- Actions ---
        f_act = ttk.LabelFrame(self.root, text="3. Action")
        f_act.pack(fill="x", **pad)

        direct = ttk.Frame(f_act); direct.pack(fill="x", padx=6, pady=6)
        ttk.Label(direct, text="Conversion directe (pas de relecture manuelle) →").pack(side="left")
        self.btn_direct = ttk.Button(direct, text="Choisir la sortie .cbz et générer",
                                      command=self._run_direct)
        self.btn_direct.pack(side="left", padx=8)

        ttk.Separator(f_act, orient="horizontal").pack(fill="x", padx=6, pady=4)

        step1 = ttk.Frame(f_act); step1.pack(fill="x", padx=6, pady=6)
        ttk.Label(step1, text="Étape 1 — Exporter les pages pour relecture manuelle →").pack(side="left")
        self.btn_review = ttk.Button(step1, text="Choisir un dossier et exporter",
                                      command=self._run_export_review)
        self.btn_review.pack(side="left", padx=8)
        self.btn_open_html = ttk.Button(step1, text="Ouvrir revue.html", state="disabled",
                                         command=self._open_review_html)
        self.btn_open_html.pack(side="left", padx=4)

        step2 = ttk.Frame(f_act); step2.pack(fill="x", padx=6, pady=6)
        ttk.Label(step2, text="Étape 2 — Construire le CBZ depuis un dossier corrigé →").pack(side="left")
        self.btn_build = ttk.Button(step2, text="Choisir le dossier corrigé et générer",
                                     command=self._run_build_from_review)
        self.btn_build.pack(side="left", padx=8)

        # --- Log ---
        f_log = ttk.LabelFrame(self.root, text="Progression")
        f_log.pack(fill="both", expand=True, **pad)
        self.log_widget = scrolledtext.ScrolledText(f_log, state="disabled", height=14, wrap="word")
        self.log_widget.pack(fill="both", expand=True, padx=6, pady=6)

        self._last_review_dir = None
        self._all_buttons = [self.btn_direct, self.btn_review, self.btn_build]

    # ------------------------------------------------------------ helpers

    def _on_preset_change(self, event=None):
        preset = PRESETS[self.preset_var.get()]
        if preset is None:
            return
        self.width_var.set(preset["width"])
        self.height_var.set(preset["height"])
        self.quality_var.set(preset["quality"])
        self.grayscale_var.set(preset["grayscale"])

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Choisir le fichier BD",
            filetypes=[("BD (cbz, cbr, zip, pdf)", "*.cbz *.cbr *.zip *.pdf"), ("Tous les fichiers", "*.*")],
        )
        if path:
            self.input_var.set(path)

    def _log(self, msg):
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", msg)
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                self._log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in self._all_buttons:
            b.configure(state=state)

    def _run_in_thread(self, fn, *args, on_done=None):
        if self.busy:
            messagebox.showinfo("Patientez", "Une opération est déjà en cours.")
            return
        self._set_busy(True)

        def worker():
            old_stdout = sys.stdout
            sys.stdout = QueueWriter(self.log_queue)
            error = None
            try:
                fn(*args)
            except SystemExit as e:
                error = str(e)
            except Exception:
                error = traceback.format_exc()
            finally:
                sys.stdout = old_stdout
            self.root.after(0, lambda: self._finish(error, on_done))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, error, on_done):
        self._set_busy(False)
        if error:
            self._log(f"\n--- ERREUR ---\n{error}\n")
            messagebox.showerror("Erreur", error if len(error) < 500 else error[:500] + "…")
        else:
            self._log("\n--- Terminé ---\n")
            if on_done:
                on_done()

    # ------------------------------------------------------------ actions

    def _current_settings(self):
        try:
            return dict(
                width=self.width_var.get(),
                height=self.height_var.get(),
                upscale_limit=self.upscale_var.get(),
                margin=self.margin_var.get(),
                quality=self.quality_var.get(),
                grayscale=self.grayscale_var.get(),
            )
        except tk.TclError:
            messagebox.showerror("Valeur invalide", "Vérifiez les champs largeur/hauteur/qualité/marge (nombres attendus).")
            return None

    def _run_direct(self):
        inp = self.input_var.get().strip()
        if not inp:
            messagebox.showwarning("Fichier manquant", "Choisissez d'abord le fichier BD source.")
            return
        out = filedialog.asksaveasfilename(title="Enregistrer le CBZ sous…",
                                            defaultextension=".cbz",
                                            filetypes=[("CBZ", "*.cbz")])
        if not out:
            return
        s = self._current_settings()
        if s is None:
            return
        self._log(f"\n>>> Génération directe de {os.path.basename(out)}…\n")
        self._run_in_thread(core.run, inp, out, s["width"], s["height"], s["upscale_limit"],
                             s["margin"], False, s["quality"], s["grayscale"])

    def _run_export_review(self):
        inp = self.input_var.get().strip()
        if not inp:
            messagebox.showwarning("Fichier manquant", "Choisissez d'abord le fichier BD source.")
            return
        folder = filedialog.askdirectory(title="Choisir/créer le dossier de relecture")
        if not folder:
            return
        self._last_review_dir = folder
        self._log(f"\n>>> Export pour relecture dans {folder}…\n")

        def done():
            self.btn_open_html.configure(state="normal")
            messagebox.showinfo(
                "Export terminé",
                "Pages exportées. Cliquez sur 'Ouvrir revue.html' pour corriger les cases, "
                "puis utilisez l'étape 2 une fois terminé.",
            )

        self._run_in_thread(core.export_review, inp, folder, False, on_done=done)

    def _open_review_html(self):
        if not self._last_review_dir:
            return
        html_path = os.path.join(self._last_review_dir, "revue.html")
        if not os.path.exists(html_path):
            messagebox.showerror("Introuvable", f"{html_path} n'existe pas.")
            return
        webbrowser.open("file://" + os.path.abspath(html_path))

    def _run_build_from_review(self):
        folder = filedialog.askdirectory(title="Choisir le dossier de relecture corrigé")
        if not folder:
            return
        if not os.path.exists(os.path.join(folder, "boxes.json")):
            messagebox.showerror("Dossier invalide", "Ce dossier ne contient pas de boxes.json.")
            return
        out = filedialog.asksaveasfilename(title="Enregistrer le CBZ final sous…",
                                            defaultextension=".cbz",
                                            filetypes=[("CBZ", "*.cbz")])
        if not out:
            return
        s = self._current_settings()
        if s is None:
            return
        self._log(f"\n>>> Construction de {os.path.basename(out)} depuis {folder}…\n")
        self._run_in_thread(core.build_from_review, folder, out, s["width"], s["height"],
                             s["upscale_limit"], s["margin"], s["quality"], s["grayscale"])


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
