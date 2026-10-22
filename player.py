"""Lecteur vidéo qui décode en temps réel Syster et VideoCrypt, image et son."""
import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

import cv2
from PIL import Image, ImageTk

from audio import Audio
from core import SysterDescrambler, VideoCryptDescrambler

MODES_VIDEO = ["Brut (aucun décodage)", "Syster (lignes mélangées)",
               "VideoCrypt (coupe et rotation)"]
MODES_SON = ["Son brut", "Son décodé (inversion de spectre)", "Muet"]
QUALITES = {"Rapide": 360, "Normal": 720, "Précis": 1440}   # largeur de traitement VideoCrypt
QUALITES_SYSTER = {"Rapide": 16, "Normal": 8, "Précis": 2}


class Lecteur:
    def __init__(self, root, chemin=None):
        self.root = root
        root.title("Syster / VideoCrypt Player")
        root.geometry("1000x680")
        root.minsize(640, 400)

        self.cap = None
        self.path = None
        self.fps = 25.0
        self.total = 0
        self.pos = 0
        self.playing = False
        self.pending_open = None
        self.pending_seek = None
        self.latest = None
        self.proc_fps = 0.0
        self.running = True
        self.dragging = False

        self.mode_video = tk.StringVar(value=MODES_VIDEO[1])
        self.mode_son = tk.StringVar(value=MODES_SON[0])
        self.qualite = tk.StringVar(value="Normal")
        self.flip = tk.BooleanVar(value=False)
        self.fc_var = tk.DoubleVar(value=6000)
        self.dernier_mode = MODES_VIDEO[1]

        self.audio = Audio()
        self._creer_decodeurs()
        self._build_ui()
        threading.Thread(target=self._worker, daemon=True).start()
        self.root.after(15, self._refresh)
        root.protocol("WM_DELETE_WINDOW", self._close)
        if chemin:
            self.pending_open = chemin

    # ---------------- interface ----------------
    def _creer_decodeurs(self):
        q = self.qualite.get()
        self.syster = SysterDescrambler(QUALITES_SYSTER[q])
        off = getattr(getattr(self, "vc", None), "offset", 0)
        self.vc = VideoCryptDescrambler(QUALITES[q])
        self.vc.offset = off

    def _build_ui(self):
        self.video = tk.Label(self.root, bg="black")
        self.video.pack(fill="both", expand=True)

        self.slider = ttk.Scale(self.root, from_=0, to=1000)
        self.slider.pack(fill="x", padx=8, pady=(4, 0))
        self.slider.bind("<ButtonPress-1>", lambda e: setattr(self, "dragging", True))
        self.slider.bind("<ButtonRelease-1>", self._slider_release)

        l1 = ttk.Frame(self.root)
        l1.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Button(l1, text="Ouvrir…", command=self.ouvrir).pack(side="left")
        self.btn = ttk.Button(l1, text="▶ Lecture", command=self.toggle)
        self.btn.pack(side="left", padx=6)
        ttk.Label(l1, text="Vidéo :").pack(side="left", padx=(10, 2))
        cb = ttk.Combobox(l1, textvariable=self.mode_video, values=MODES_VIDEO,
                          width=30, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._reset_decodeurs())
        ttk.Label(l1, text="Qualité :").pack(side="left", padx=(10, 2))
        cq = ttk.Combobox(l1, textvariable=self.qualite, values=list(QUALITES),
                          width=8, state="readonly")
        cq.pack(side="left")
        cq.bind("<<ComboboxSelected>>", lambda e: (self._creer_decodeurs(), self._reset_decodeurs()))
        ttk.Checkbutton(l1, text="Haut/bas inversé (F)", variable=self.flip).pack(side="left", padx=10)

        l2 = ttk.Frame(self.root)
        l2.pack(fill="x", padx=8, pady=(2, 2))
        ttk.Label(l2, text="Décalage horizontal (VideoCrypt) :").pack(side="left")
        ttk.Button(l2, text="◀", width=3, command=lambda: self._decaler(-8)).pack(side="left", padx=2)
        ttk.Button(l2, text="▶", width=3, command=lambda: self._decaler(8)).pack(side="left", padx=2)
        ttk.Button(l2, text="Auto (A)", command=self._auto_offset).pack(side="left", padx=2)

        l3 = ttk.Frame(self.root)
        l3.pack(fill="x", padx=8, pady=(2, 6))
        ttk.Label(l3, text="Son :").pack(side="left")
        cs = ttk.Combobox(l3, textvariable=self.mode_son, values=MODES_SON,
                          width=34, state="readonly")
        cs.pack(side="left", padx=4)
        cs.bind("<<ComboboxSelected>>", self._change_son)
        ttk.Label(l3, text="Fréquence porteuse :").pack(side="left", padx=(10, 2))
        self.sc = ttk.Scale(l3, from_=1000, to=20000, variable=self.fc_var,
                            length=180, command=self._change_fc)
        self.sc.pack(side="left")
        self.lbl_fc = ttk.Label(l3, text="6000 Hz", width=9)
        self.lbl_fc.pack(side="left")
        self.status = ttk.Label(l3, text="Aucun fichier")
        self.status.pack(side="right")

        self.root.bind("<space>", lambda e: self.toggle())
        self.root.bind("d", lambda e: self._basculer_decodage())
        self.root.bind("f", lambda e: self.flip.set(not self.flip.get()))
        self.root.bind("a", lambda e: self._auto_offset())
        self.root.bind("[", lambda e: self._decaler(-8))
        self.root.bind("]", lambda e: self._decaler(8))
        self.root.bind("<Left>", lambda e: self._seek_rel(-5))
        self.root.bind("<Right>", lambda e: self._seek_rel(5))

    def _reset_decodeurs(self):
        self.syster.reset()
        self.vc.reset()

    def _basculer_decodage(self):
        if self.mode_video.get() == MODES_VIDEO[0]:
            self.mode_video.set(self.dernier_mode)
        else:
            self.dernier_mode = self.mode_video.get()
            self.mode_video.set(MODES_VIDEO[0])
        self._reset_decodeurs()

    def _decaler(self, d):
        self.vc.offset += d

    def _auto_offset(self):
        self.vc.auto_offset()

    def _change_son(self, _=None):
        m = self.mode_son.get()
        self.audio.mode = {MODES_SON[0]: "brut", MODES_SON[1]: "decode",
                           MODES_SON[2]: "muet"}[m]

    def _change_fc(self, _=None):
        fc = int(self.fc_var.get() // 50 * 50)
        self.audio.fc = fc
        self.lbl_fc.config(text=f"{fc} Hz")

    def ouvrir(self):
        p = filedialog.askopenfilename(
            filetypes=[("Vidéos", "*.mp4 *.mkv *.avi *.mov *.webm *.ts"), ("Tous", "*.*")])
        if p:
            self.pending_open = p

    def toggle(self):
        if self.cap is not None:
            self.playing = not self.playing

    def _seek_rel(self, s):
        if self.cap is not None:
            self.pending_seek = max(0, int(self.pos + s * self.fps))

    def _slider_release(self, _):
        self.dragging = False
        if self.total:
            self.pending_seek = int(self.slider.get() / 1000 * self.total)

    def _refresh(self):
        img = self.latest
        if img is not None:
            w = max(self.video.winfo_width(), 2)
            h = max(self.video.winfo_height(), 2)
            ih, iw = img.shape[:2]
            s = min(w / iw, h / ih)
            pil = Image.fromarray(img).resize((max(1, int(iw * s)), max(1, int(ih * s))))
            self.photo = ImageTk.PhotoImage(pil)
            self.video.config(image=self.photo)
        if self.total and not self.dragging:
            self.slider.set(self.pos / self.total * 1000)
        if self.cap is not None:
            t = self.pos / self.fps if self.fps else 0
            son = "" if self.audio.disponible else "  |  son indisponible"
            self.status.config(text=f"{int(t // 60):02d}:{int(t % 60):02d}  |  "
                                    f"{self.proc_fps:.1f} img/s{son}")
            self.btn.config(text="⏸ Pause" if self.playing else "▶ Lecture")
        if self.running:
            self.root.after(15, self._refresh)

    def _close(self):
        self.running = False
        self.audio.fermer()
        self.root.destroy()

    # ---------------- thread de lecture ----------------
    def _traiter(self, frame):
        m = self.mode_video.get()
        if m == MODES_VIDEO[1]:
            frame = self.syster.process(frame)
        elif m == MODES_VIDEO[2]:
            frame = self.vc.process(frame)
        if self.flip.get():
            frame = frame[::-1]
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def _worker(self):
        t0, base = time.time(), 0
        reset_clock = True
        derniere = time.time()
        while self.running:
            if self.pending_open:
                p, self.pending_open = self.pending_open, None
                self.audio.stop()
                if self.cap is not None:
                    self.cap.release()
                cap = cv2.VideoCapture(p)
                if cap.isOpened():
                    self.cap, self.path = cap, p
                    self.fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                    self.total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    self.pos = 0
                    self._reset_decodeurs()
                    self.pending_seek = 0
                    self.playing = True
                    self.root.title("Syster / VideoCrypt Player — " + os.path.basename(p))
                else:
                    self.cap = None

            if self.cap is None:
                time.sleep(0.05)
                continue

            if self.pending_seek is not None:
                n, self.pending_seek = self.pending_seek, None
                self.audio.stop()
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, n)
                self.pos = n
                self._reset_decodeurs()
                reset_clock = True
                if not self.playing:
                    ok, f = self.cap.read()
                    if ok:
                        self.latest = self._traiter(f)
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, n)
                continue

            if not self.playing:
                self.audio.stop()
                reset_clock = True
                time.sleep(0.03)
                continue

            if reset_clock:
                self.audio.start(self.path, self.pos / self.fps)
                self.audio.attendre(1.5)          # démarre l'image avec le son
                t0, base, reset_clock = time.time(), self.pos, False

            # temps réel : on saute des images si le calcul est en retard
            cible = base + int((time.time() - t0) * self.fps)
            while self.pos < cible - 1:
                if not self.cap.grab():
                    break
                self.pos += 1

            ok, frame = self.cap.read()
            if not ok:
                self.playing = False
                self.audio.stop()
                self.pending_seek = 0
                continue
            self.pos += 1
            self.latest = self._traiter(frame)

            now = time.time()
            self.proc_fps = 0.8 * self.proc_fps + 0.2 / max(now - derniere, 1e-6)
            derniere = now

            delai = t0 + (self.pos - base) / self.fps - time.time()
            if delai > 0:
                time.sleep(delai)
        self.audio.stop()


def main():
    import sys
    root = tk.Tk()
    Lecteur(root, sys.argv[1] if len(sys.argv) > 1 else None)
    root.mainloop()


if __name__ == "__main__":
    main()
