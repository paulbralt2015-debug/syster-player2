# Syster / VideoCrypt Player

Lecteur vidéo expérimental qui décode **en temps réel**, sans clé ni carte, des
enregistrements d'anciens brouillages analogiques :

| Système | Brouillage de l'image | Méthode de décodage |
|---|---|---|
| Nagravision Syster | lignes mélangées | recherche de l'ordre des lignes par continuité de l'image |
| VideoCrypt | chaque ligne coupée puis rotation | recherche du décalage circulaire de chaque ligne |

Le son peut être traité par **inversion de spectre** (f → fc − f), avec une fréquence
porteuse réglable à l'oreille.

## Lancer
    pip install -r requirements.txt
    python player.py [fichier.mp4]

## Commandes
- Espace : lecture / pause · ← / → : -5 s / +5 s · barre de progression
- D : décodage activé / désactivé
- F : image inversée haut/bas
- [ et ] (ou boutons ◀ ▶) : décalage horizontal (VideoCrypt) ; A : réglage automatique
- Qualité : Rapide / Normal / Précis (largeur de traitement VideoCrypt, finesse Syster)
- Son : brut / décodé (inversion de spectre) / muet, avec réglage de la fréquence porteuse

## Limites (à lire)
- **Vidéos recompressées ou désentrelacées** (ex. YouTube) : le résultat est souvent
  partiel. Le VideoCrypt est surtout sensible au désentrelacement, qui mélange des
  lignes ayant des coupes différentes. Une capture entrelacée, propre, donne de bien
  meilleurs résultats.
- **VideoCrypt** : le décalage horizontal global de l'image est inconnu ; il est suivi
  d'une image à l'autre mais il faut parfois le régler à la main au début (touches
  [ ] ou A). Un changement de plan peut faire sauter ce réglage.
- **Son** : la fréquence porteuse réelle de chaque système n'est pas connue du projet ;
  on la règle à l'oreille. Sur du son compressé, le résultat est limité. Le son du
  VideoCrypt est en général non brouillé : laissez « Son brut ».
- Scènes très sombres ou unies : l'ordre ou le décalage des lignes y est incertain.
- Si l'ordinateur est trop lent, des images sont sautées pour rester en temps réel.

## Version ligne de commande (image seule)
    python descramble.py entree.mp4 sortie.mp4 [--mode syster|videocrypt] [--flip]

## Avertissement
À utiliser uniquement sur des enregistrements dont vous détenez les droits
(archives personnelles, restauration de services analogiques éteints). Ne publiez
aucune vidéo dans ce dépôt.
