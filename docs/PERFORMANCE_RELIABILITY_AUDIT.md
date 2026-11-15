# Audit de l'agent Wasf : performance et fiabilité

Ce rapport donne des mesures faites pendant l'audit, puis examine la tenue de Wasf face aux pannes,
aux interruptions et aux gros films. **Le temps de réponse d'un vrai modèle n'a pas été mesuré** :
toutes les mesures utilisent la simulation `mock`, qui répond instantanément. Elles montrent donc
le coût du travail fait sur l'ordinateur, pas la durée réelle d'une préparation.

## 1. Les conditions de mesure

- **Machine** : un conteneur Linux dans le nuage, 2 processeurs virtuels, 7 Go de mémoire,
  Python 3.13, FFmpeg 6.1.1, sans CodeCarbon. Un ordinateur portable donnera d'autres chiffres.
- **Film** : 10 minutes fabriquées par FFmpeg (mire animée `testsrc2`), en 1920 × 1080, 24 images
  par seconde. Encodage H.264 avec une image clé toutes les 2 s, environ 13 Mbit/s (990 Mo), et un
  son continu. Une image synthétique se compresse autrement qu'un vrai film.
- **Sous-titres** : 75 répliques de 4 s séparées par des pauses de 4 s. Cela donne 75 passages
  d'un budget de 8 mots.
- **Réglages** : ceux par défaut, 2 images avant chaque pause et 2 pendant. Fournisseur `mock`,
  voix espeak-ng.
- **Script de mesure** : hors du dépôt. Il appelle `pipeline.prepare` et `pipeline.render`, et
  relève le temps et la mémoire maximale avec `resource.getrusage`.

## 2. Les mesures

| Étape | Durée | Par passage | Mémoire max de Python | Mémoire max de FFmpeg et espeak |
| --- | --- | --- | --- | --- |
| Préparation, images régulièrement espacées (`--choix-images fixe`) | 38,0 s | 0,51 s | 46 Mo | 86 Mo |
| Préparation, images choisies (`auto`, par défaut) | 84,7 s | 1,13 s | 48 Mo | 86 Mo |
| Export sans carton (`--sans-annonce`) | 63,9 s | 0,85 s | 131 Mo | 130 Mo |
| Export avec carton (par défaut) | 239,0 s | 3,19 s | 136 Mo | 370 Mo |

Ce que ces chiffres montrent :

- **Le choix des images coûte 0,62 s par pause** sur cette machine : (84,7 − 38,0) / 75. Le README
  annonce « environ une demi-seconde ». C'est le bon ordre de grandeur, un peu au-dessus ici. Ce
  coût vient du décodage complet de chaque fenêtre en pleine résolution avant réduction. Il croît
  avec la résolution du film et avec la longueur des pauses.
- **Le carton d'annonce multiplie par 3,7 la durée de l'export** : 175 s de plus pour 10 minutes,
  soit environ 17 s par minute de film sur cette machine.
  - Sans carton, l'image est copiée telle quelle (`media.mux`, `-c:v copy`).
  - Avec le carton, `media.prepend_card` assemble le carton et le film, et réencode toute l'image
    en H.264 (`libx264`, `-crf 20`).
  - Le film perd donc un peu de qualité à chaque export, et un long métrage demandera des dizaines
    de minutes de plus. Mettre le carton dans un petit fichier encodé à part, puis assembler sans
    réencoder, l'éviterait quand les formats le permettent.
  - Le carton décale aussi tout le film : dans l'essai, `film_audiodecrit.mp4` dure 606,9 s au
    lieu de 600 s. Les sous-titres WebVTT et SRT gardent, eux, les instants du film d'origine.
    Chargés avec `film_audiodecrit.mp4`, ils arrivent 6,9 s trop tôt. Ce point a été trouvé
    pendant les corrections faites après l'audit ; il n'est pas corrigé.
- **La mémoire reste faible et ne dépend pas de la durée du film** : le son est mixé par tranches
  de 30 s (`mix.MIX_CHUNK_SECONDS`), et les tests vérifient que le résultat est identique au
  mélange en un bloc. Seul un film de 10 minutes a été mesuré.
- **La sauvegarde de `projet.json` prend 20 à 30 ms**, mesurée sur des projets de 75, 300 et 600
  passages remplis par la simulation. Le temps vient surtout de l'écriture forcée sur le disque
  (`fsync`), pas de la taille. Sauvegarder après chaque passage ne ralentit donc pas la
  préparation.

### Les fichiers

| Fichier | Taille mesurée | Remarque |
| --- | --- | --- |
| Image de 768 px | 20 Ko en moyenne | Sur une mire ; un vrai film donnera d'autres tailles |
| Image de 512 px | 11 Ko en moyenne | Idem |
| `projet.json`, 75 passages | 192 Ko | Avec la simulation, dont les réponses sont plus courtes que celles d'un vrai modèle |
| `piste_audiodecrite.wav` | 115 Mo pour 10 min | 48 kHz, stéréo, 16 bits : 11,5 Mo par minute, quel que soit le film |
| `voix_seule.wav` | 58 Mo pour 10 min | Mono : 5,8 Mo par minute |
| Copie temporaire du son du film, pendant l'export | Autant que la piste mixée | Effacée à la fin (`build_mix`, bloc `finally`) |

Pour un film de 2 heures, les deux WAV font donc environ 2,1 Go. Il faut compter 1,4 Go de plus
pendant l'export. Ce calcul vient du format, pas d'une mesure sur un film de cette durée.

### Ce que dit la mesure d'énergie de Wasf

Le rapport du film d'essai donne 2,65 s pour la « préparation », alors qu'elle a pris 84,7 s.
`EnergyMeter("preparation")` n'entoure que l'écriture des passages (`pipeline._draft`). Trois
étapes restent hors de la mesure :

- la recherche des pauses ;
- le choix des images ;
- leur extraction.

Ici, ces étapes font 97 % du temps de préparation sur l'ordinateur. Avec un vrai modèle, l'attente
des réponses dominera la durée, mais le travail de FFmpeg restera hors de la mesure. Le texte
`energie_portee` du rapport dit pourtant mesurer « cet ordinateur, pendant la préparation et
l'export ».

## 3. Le temps d'une vraie préparation

Il n'a pas été mesuré. Le code permet seulement d'en écrire la forme. Pour N passages :

```
temps ≈ N × (travail local, environ 1,1 s ici)
      + N × (brouillon + réécritures, 0 à 2, + seconde lecture éventuelle) × temps de réponse du modèle
      + attentes des nouvelles tentatives
```

Les passages sont écrits **un par un** : aucun appel ne part en parallèle. C'est simple et sûr
pour la reprise, mais c'est le premier goulot d'étranglement pour un long métrage. Le nombre de
pauses d'un long métrage dépend de ses dialogues ; aucun film réel n'a été mesuré.

## 4. Les pannes du fournisseur

| Situation | Ce que fait Wasf | Vérifié |
| --- | --- | --- |
| Clé refusée, modèle inconnu, quota du jour ou crédit épuisé, Ollama éteint | Arrêt immédiat, passages finis gardés, marche à suivre (`--reprendre --refaire-echecs`) | Tests (`test_fatal_errors.py`) |
| Limite par minute ou serveur saturé, Gemini | 2 nouvelles tentatives avec attente | Tests |
| Erreur passagère, Claude ou OpenAI | Nouvelles tentatives de leur bibliothèque, puis passage vide et signalé | Lu |
| Erreur passagère, Ollama | Aucune nouvelle tentative : passage vide et signalé | Lu |
| Délai dépassé | Passage vide et signalé (120 s chez Gemini, 600 s chez Ollama) | Lu |
| **Erreur fatale pendant une réécriture** | Avalée : le passage garde son brouillon et ses erreurs, et il est marqué « fait ». `--refaire-echecs` ne le reprendra pas ; une personne doit le corriger | Exécuté |
| Erreur pendant la seconde lecture | Avalée : notée dans le journal, sans alerte sur le passage | Lu |

Deux petits défauts de comptage :

- Une seconde lecture qui a échoué est comptée dans le rapport comme un appel avec images
  réussi (`export.model_calls` compte l'étape « seconde lecture », même quand elle contient une
  erreur).
- Une réécriture qui a échoué est comptée « en échec », ce qui est juste.

## 5. Interruption et reprise

- **La sauvegarde est atomique** (`project.save_project`) : fichier temporaire, écriture forcée sur
  le disque, puis remplacement en une fois. Une coupure laisse l'ancien fichier ou le nouveau,
  entier. Sous Windows, le dossier ne peut pas être forcé sur le disque : le remplacement reste
  atomique, mais le tout dernier instant avant une coupure de courant n'est pas garanti. Le code le
  dit.
- **Le plan est sauvegardé avant le premier appel**, puis le projet après chaque passage.
  `--reprendre` ne renvoie au modèle que les passages encore « à faire ». Les images manquantes
  sont extraites à nouveau, sans appel au modèle.
- **Appels en double** : un passage interrompu entre la réponse du modèle et la sauvegarde est
  redemandé à la reprise. Il y a donc au plus un passage en double par interruption.
  Une nouvelle tentative après un délai dépassé peut aussi être facturée deux fois si le
  fournisseur avait traité la première ; Wasf ne peut pas le savoir.
- **Ce qui est vérifié** : `test_checkpoints.py` et `test_project_file.py` couvrent la reprise, un
  fichier abîmé et les sauvegardes.

## 6. Modifications simultanées

| Situation | Ce qui se passe |
| --- | --- |
| Deux actions dans le même éditeur | Un verrou les met l'une après l'autre ; chaque action relit le fichier avant de l'écrire |
| Deux éditeurs ouverts sur le même projet | Pas de verrou entre eux. Comme chaque action relit puis écrit en quelques millisecondes, une perte demande deux actions presque au même instant |
| Une relecture pendant un export | L'export relit le projet avant d'écrire, n'ajoute que ses mesures, et signale ce qui a changé pendant l'export (`changed_during_export`) |
| Une relecture pendant la préparation | L'éditeur passe en lecture seule tant que la préparation n'est pas terminée |
| **Deux préparations sur le même dossier** | **Rien ne l'empêche.** Avec `--reprendre` lancé deux fois, les deux processus écrivent les mêmes passages : le coût est double, et chacun écrase les sauvegardes de l'autre |

Un fichier verrou dans le dossier du projet suffirait pour le dernier cas.

## 7. Les gros films

- **Le temps** grandit avec le nombre de pauses, sans traitement parallèle. Le travail local est
  d'environ 1,1 s par passage ici. Le temps des modèles s'y ajoute.
- **L'extraction des images** lance un processus FFmpeg par image, et décode toute la fenêtre
  pour le choix des instants. Un film en 4K ou encodé avec des images clés espacées sera plus
  lent. Ces deux cas n'ont pas été mesurés.
- **La mémoire** reste bornée : le son est traité par tranches, et les images d'un passage sont
  lues une à une.
- **Le disque** : environ 17 Mo de WAV par minute de film, plus une copie temporaire pendant
  l'export, et le film réencodé si le carton est gardé.
- **`projet.json`** grossit avec les passages et leurs journaux, mais sa sauvegarde reste rapide
  aux tailles mesurées.

## 8. Les messages d'erreur

- Les erreurs connues sont rendues en une ligne de français qui dit quoi faire
  (`cli.KNOWN_ERRORS`).
- Les erreurs du fournisseur sont gardées dans le journal de l'agent, et l'arrêt sur erreur
  fatale dans l'historique.
- Les refus d'export disent quels passages posent problème et comment les corriger.

C'est un point fort du projet. Le seul message manquant est celui d'une préparation déjà en cours
dans le même dossier.

## 9. Les goulots d'étranglement et les points de rupture

| Point | Effet | Gravité |
| --- | --- | --- |
| Appels au modèle un par un | Un long métrage prend autant d'attentes que de passages | Moyenne (non mesuré) |
| Réencodage de tout le film pour le carton | Environ 17 s par minute de film ici, et une perte de qualité | Moyenne (mesuré) |
| Sous-titres calés sur le film d'origine | En avance de la durée du carton sur `film_audiodecrit.mp4` (6,9 s dans l'essai) | Moyenne (mesuré) |
| Choix des images en pleine résolution | 0,62 s par pause ici, plus en 4K | Faible |
| Claude limité à 400 jetons de réponse | Réponses coupées possibles, surtout en arabe (non mesuré) | Moyenne |
| Quota du jour d'une offre gratuite | Arrêt propre, reprise le lendemain | Faible (bien géré) |
| Deux préparations sur un même dossier | Coût double, sauvegardes écrasées | Faible (erreur d'usage) |
| Erreur fatale pendant une réécriture | Un passage marqué « fait » avec ses erreurs | Faible |
