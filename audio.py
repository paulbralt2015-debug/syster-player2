"""Lecture audio en temps réel avec décodage de l'inversion de spectre.

Le son est extrait par ffmpeg (fourni par le paquet imageio-ffmpeg, ou ffmpeg installé
sur le système), traité par blocs, puis envoyé à la carte son via sounddevice.
"""
import os
import queue
import shutil
import subprocess
import threading

import numpy as np

try:
    from scipy.signal import butter, sosfilt
except Exception:
    butter = sosfilt = None

try:
    import sounddevice as sd
except Exception:
    sd = None

FS = 44100
BLOC = 4096


def trouver_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


class InverseurSpectre:
    """Inversion de spectre : f -> fc - f (se défait en la réappliquant)."""

    def __init__(self):
        self.fc = 6000.0
        self._fc_filtre = None
        self.reset()

    def reset(self):
        self._n = 0
        self._sos = None
        self._zi = None
        self._fc_filtre = None

    def traiter(self, x):
        fc = float(self.fc)
        if self._sos is None or fc != self._fc_filtre:
            coupure = min(fc, 0.95 * FS / 2) / (FS / 2)
            self._sos = butter(8, coupure, btype="low", output="sos")
            self._zi = np.zeros((self._sos.shape[0], 2))
            self._fc_filtre = fc
        n = self._n + np.arange(len(x))
        phase = (fc * n / FS) % 1.0
        y = x * (2.0 * np.cos(2 * np.pi * phase))
        y, self._zi = sosfilt(self._sos, y, zi=self._zi)
        self._n += len(x)
        return np.clip(y, -1.0, 1.0).astype(np.float32)


class Audio:
    """mode : 'brut', 'decode' (inversion de spectre) ou 'muet'."""

    def __init__(self):
        self.mode = "brut"
        self.inv = InverseurSpectre()
        self.volume = 1.0
        self.ffmpeg = trouver_ffmpeg()
        self.q = queue.Queue(maxsize=8)
        self.reste = np.zeros(0, np.float32)
        self.verrou = threading.Lock()
        self.proc = None
        self.gen = 0
        self.pret = threading.Event()
        self.stream = None
        if sd is not None and self.ffmpeg and butter is not None:
            try:
                self.stream = sd.OutputStream(samplerate=FS, channels=1, dtype="float32",
                                              blocksize=1024, callback=self._callback)
                self.stream.start()
            except Exception:
                self.stream = None

    @property
    def disponible(self):
        return self.stream is not None

    @property
    def fc(self):
        return self.inv.fc

    @fc.setter
    def fc(self, v):
        self.inv.fc = float(v)

    def _callback(self, outdata, frames, temps, statut):
        out = np.zeros(frames, np.float32)
        pos = 0
        with self.verrou:
            while pos < frames:
                if self.reste.size == 0:
                    try:
                        self.reste = self.q.get_nowait()
                    except queue.Empty:
                        break
                n = min(frames - pos, self.reste.size)
                out[pos:pos + n] = self.reste[:n]
                self.reste = self.reste[n:]
                pos += n
        outdata[:, 0] = out * self.volume

    def _traiter(self, x):
        if self.mode == "muet":
            return np.zeros_like(x)
        if self.mode == "decode":
            return self.inv.traiter(x)
        return x

    def _lire(self, proc, g):
        premier = True
        while g == self.gen:
            data = proc.stdout.read(BLOC * 4)
            if not data:
                break
            data = data[: len(data) // 4 * 4]
            x = np.frombuffer(data, dtype="<f4").astype(np.float32)
            y = self._traiter(x)
            while g == self.gen:
                try:
                    self.q.put(y, timeout=0.1)
                    break
                except queue.Full:
                    continue
            if premier:
                premier = False
                self.pret.set()
        self.pret.set()

    def start(self, chemin, t):
        self.stop()
        if not self.disponible:
            return
        self.pret.clear()
        self.inv.reset()
        cmd = [self.ffmpeg, "-v", "quiet", "-ss", f"{max(t, 0):.3f}", "-i", chemin,
               "-vn", "-ac", "1", "-ar", str(FS), "-f", "f32le", "-"]
        flags = 0x08000000 if os.name == "nt" else 0   # pas de fenêtre console
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, creationflags=flags)
        except Exception:
            self.proc = None
            self.pret.set()
            return
        self.gen += 1
        threading.Thread(target=self._lire, args=(self.proc, self.gen), daemon=True).start()

    def attendre(self, delai=1.5):
        self.pret.wait(delai)

    def stop(self):
        self.gen += 1
        p, self.proc = self.proc, None
        if p is not None:
            try:
                p.kill()
            except Exception:
                pass
        with self.verrou:
            self.reste = np.zeros(0, np.float32)
            while True:
                try:
                    self.q.get_nowait()
                except queue.Empty:
                    break

    def fermer(self):
        self.stop()
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
