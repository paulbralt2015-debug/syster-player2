"""Ligne de commande :
    python descramble.py entree.mp4 sortie.mp4 [--mode syster|videocrypt] [--flip]
"""
import sys
import cv2
from core import SysterDescrambler, VideoCryptDescrambler


def main(src, dst, mode="syster", flip=False):
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = cv2.VideoWriter(dst, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
    d = VideoCryptDescrambler(largeur_max=w) if mode == "videocrypt" else SysterDescrambler(step=4)
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        res = d.process(frame)
        out.write(res[::-1] if flip else res)
        n += 1
        if n % 25 == 0:
            print(f"{n} images traitées")
    cap.release()
    out.release()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    mode = "videocrypt" if "videocrypt" in sys.argv else "syster"
    main(sys.argv[1], sys.argv[2], mode=mode, flip=("--flip" in sys.argv))
