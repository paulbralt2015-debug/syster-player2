"""Moteurs de reconstitution d'image pour deux types de brouillage analogique :

- Syster  : lignes mélangées (permutation) -> on retrouve l'ordre des lignes ;
- VideoCrypt : chaque ligne est coupée en un point puis les deux morceaux sont
  échangés ("coupe et rotation") -> on retrouve le décalage circulaire de chaque ligne.

Aucune clé n'est utilisée : tout repose sur la continuité de l'image.
"""
import cv2
import numpy as np
from scipy.spatial.distance import cdist


# ----------------------------------------------------------------------------
# Syster : permutation de lignes
# ----------------------------------------------------------------------------
def order_lines(gray, k=8, step=8):
    H = gray.shape[0]
    g = gray[:, ::step].astype(np.float32)
    D = cdist(g, g, 'cityblock') / g.shape[1]
    np.fill_diagonal(D, np.inf)

    nn = np.argsort(D, axis=1)[:, :k]
    edges = {(min(i, j), max(i, j)) for i in range(H) for j in nn[i]}
    edges = sorted(edges, key=lambda e: D[e])

    parent = list(range(H))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    deg = np.zeros(H, int)
    adj = [[] for _ in range(H)]

    def link(a, b):
        adj[a].append(b)
        adj[b].append(a)
        deg[a] += 1
        deg[b] += 1
        parent[find(a)] = find(b)

    for a, b in edges:
        if deg[a] < 2 and deg[b] < 2 and find(a) != find(b):
            link(a, b)

    while True:
        ends = np.array([n for n in range(H) if deg[n] < 2])
        comp = np.array([find(n) for n in ends])
        if len(set(comp)) == 1:
            break
        sub = D[np.ix_(ends, ends)].copy()
        sub[comp[:, None] == comp[None, :]] = np.inf
        a, b = np.unravel_index(np.argmin(sub), sub.shape)
        link(int(ends[a]), int(ends[b]))

    start = next(n for n in range(H) if deg[n] < 2)
    order, prev, cur = [start], -1, start
    while len(order) < H:
        nxt = [n for n in adj[cur] if n != prev]
        if not nxt:
            break
        prev, cur = cur, nxt[0]
        order.append(cur)
    return np.array(order)


class SysterDescrambler:
    """Remet les lignes dans l'ordre, en gardant le sens haut/bas cohérent."""

    def __init__(self, step=8):
        self.step = step
        self.prev = None

    def reset(self):
        self.prev = None

    def process(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        order = order_lines(gray, step=self.step)
        small = gray[:, ::self.step].astype(np.int16)
        if self.prev is not None and self.prev.shape == small.shape:
            a = np.abs(small[order] - self.prev).mean()
            b = np.abs(small[order[::-1]] - self.prev).mean()
            if b < a:
                order = order[::-1]
        self.prev = small[order]
        return frame[order]


Descrambler = SysterDescrambler  # compatibilité


# ----------------------------------------------------------------------------
# VideoCrypt : coupe et rotation de chaque ligne
# ----------------------------------------------------------------------------
class VideoCryptDescrambler:
    """Retrouve, ligne par ligne, le décalage circulaire qui rend l'image continue.

    Chaque ligne est recalée (corrélation circulaire par FFT, au pixel près) sur une
    référence construite à partir des lignes déjà corrigées. Il reste un décalage
    horizontal global inconnu : il est suivi d'une image à l'autre, et réglable à la
    main (`offset`, en pixels) pour placer le bord gauche de l'image au bon endroit.

    largeur_max : les images plus larges sont réduites avant traitement (plus rapide).
    """

    def __init__(self, largeur_max=720):
        self.largeur_max = largeur_max
        self.offset = 0
        self.prev_spec = None
        self.last_gray = None

    def reset(self):
        self.prev_spec = None
        self.last_gray = None

    def process(self, frame):
        H, W0 = frame.shape[:2]
        W = W0
        if W0 > self.largeur_max:
            # on ne réduit que la largeur : réduire la hauteur mélangerait des lignes brouillées
            W = self.largeur_max
            frame = cv2.resize(frame, (W, H), interpolation=cv2.INTER_AREA)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        g = gray.astype(np.float32)
        g -= g.mean(axis=1, keepdims=True)
        F = np.fft.rfft(g, axis=1).astype(np.complex64)
        k = np.arange(F.shape[1])
        phase = 2j * np.pi * k / W

        shifts = np.zeros(H, dtype=np.int64)
        aligned = np.empty_like(F)
        ref = F[0].copy()
        aligned[0] = F[0]
        for i in range(1, H):
            c = np.fft.irfft(np.conj(ref) * F[i], n=W)
            s = int(np.argmax(c))
            shifts[i] = s
            aligned[i] = F[i] * np.exp(phase * s)
            conf = c[s] * W / (2 * np.sqrt((np.abs(ref) ** 2).sum() * (np.abs(F[i]) ** 2).sum()) + 1e-6)
            if conf > 0.3:
                ref = 0.5 * ref + 0.5 * aligned[i]

        # décalage global : recalage sur l'image précédente
        glob = 0
        if self.prev_spec is not None and self.prev_spec.shape == aligned.shape:
            cc = np.fft.irfft((np.conj(self.prev_spec) * aligned).sum(axis=0), n=W)
            n1 = np.sqrt((np.abs(self.prev_spec) ** 2).sum())
            n2 = np.sqrt((np.abs(aligned) ** 2).sum())
            g_s = int(np.argmax(cc))
            if cc[g_s] * W / (2 * n1 * n2 + 1e-6) > 0.15:
                glob = g_s
        self.prev_spec = aligned * np.exp(phase * glob)

        px = (shifts + glob) % W
        cols = (np.arange(W)[None, :] + px[:, None]) % W
        out = frame[np.arange(H)[:, None], cols]
        self.last_gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY).astype(np.float32)

        if self.offset:
            out = np.roll(out, -int(self.offset), axis=1)
        if W != W0:
            out = cv2.resize(out, (W0, H), interpolation=cv2.INTER_LINEAR)
        return out

    def auto_offset(self):
        """Place le bord gauche là où la discontinuité horizontale est la plus forte."""
        if self.last_gray is None:
            return
        g = self.last_gray
        d = np.abs(np.roll(g, -1, axis=1) - g).mean(axis=0)
        self.offset = (int(np.argmax(d)) + 1) % g.shape[1]
