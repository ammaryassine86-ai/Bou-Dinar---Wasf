# Lot 2 : six correctifs de fiabilité (14 novembre 2026)

Le lot 2 proposé au départ allait plus loin (rapport de qualité séparé, mémoire mesurée à chaque
export, analyse du film mixé, cache des voix…). Après relecture du code, six points seulement ont
été retenus : ceux qui protègent le travail approuvé de la réalisation ou qui aident tout de
suite l'équipe à enregistrer la derja. Ce document dit, pour chacun, ce qui n'allait pas, ce qui a
changé, les fichiers touchés, les tests qui le prouvent et ce qui reste à faire. La fin du
document liste ce qui a été écarté, et pourquoi.

## En bref

| N° | Problème | Avant | Après | Tests ajoutés |
| --- | --- | --- | --- | --- |
| 1 | Modification faite pendant un export | perdue : l'export réécrit à la fin la copie du projet lue au début | gardée ; l'export prévient que ce film ne la contient pas | 4 |
| 2 | Enregistrements manquants (voix « humain ») | l'export s'arrête au premier fichier manquant, un par un ; une annonce illisible fait échouer l'export à la toute fin | tout le dossier est vérifié avant de commencer, tout ce qui manque est listé d'un coup ; annonce absente ou illisible : carton muet et phrase à enregistrer | 6 |
| 3 | Qualité des voix | aucune mesure : une voix muette passe dans l'export final | voix muette : export final refusé ; saturation, écart de volume, voix trop courte, silences : alertes chiffrées ; `--couper-silences` sur demande | 11 |
| 4 | Vidéo changée depuis la préparation | export final terminé sans les passages d'après la fin, avec une ligne dans le journal | export final refusé ; en version de travail, chaque passage perdu est nommé | 6 |
| 5 | Qui lit les descriptions | ni le rapport ni les crédits ne le disent | voix utilisée et résultat du contrôle des voix dans `rapport_transparence.json` et `credits.txt` | 7 |
| 6 | `projet.json` abîmé | erreur Python brute (traceback) | message clair, sauvegardes nommées, fichier laissé tel quel | 9 |

Suite de tests : 212 tests avant le lot, 255 après, tous réussis. Le son exporté reste identique
à l'octet près quand aucune option nouvelle n'est utilisée.

## Méthode

Avant toute modification, le code a été copié hors du dépôt. Cette copie sert de référence
« avant » dans tout ce document : les mêmes scripts ont tourné sur les deux versions.

Un correctif à la fois : le code, ses tests, puis la suite complète.

| Étape | Tests | Résultat | Durée |
| --- | --- | --- | --- |
| Avant le lot | 212 | 212 réussis | 5 min 44 |
| Après le correctif 1 | 216 | 216 réussis | 6 min 09 |
| Après le correctif 2 | 222 | 222 réussis | 6 min 49 |
| Après le correctif 3 | 233 | 233 réussis | 7 min 58 |
| Après le correctif 4 | 239 | 239 réussis | 8 min 56 |
| Après le correctif 5 | 246 | 246 réussis | 9 min 32 |
| Après le correctif 6 | 255 | 255 réussis | 10 min 32 |
| Version finale (lecture directe des voix, libellé de la voix, lint) | 255 | 255 réussis | 9 min 55 |

La suite est plus longue surtout parce que les nouveaux tests font de vrais exports avec FFmpeg.
Ruff relève 26 remarques avant comme après le lot : les mêmes, aucune nouvelle.

## 1. Une modification faite pendant un export est gardée

**Avant.** `wasf exporter` lisait `projet.json` au début, travaillait plusieurs minutes sur un
long film, puis réécrivait à la fin la copie lue au début, avec ses mesures. Tout ce que la
réalisation avait fait entre-temps dans l'éditeur disparaissait : texte corrigé, passage validé
ou ignoré, approbation retirée. Sur le code d'avant, les deux tests de ce correctif échouent : le
texte corrigé redevient « Un carré jaune. », le passage ignoré redevient « brouillon ».

**Ce qui a changé.** Juste avant d'enregistrer, l'export relit le projet et n'y ajoute que ce qui
lui revient : la mesure de chaque voix, l'énergie et une ligne de journal. Il compare aussi le
projet relu à celui du début. Si un texte, un statut, l'approbation ou les signatures ont changé,
il le note dans le journal (`modifie_pendant_export`) et l'affiche :

> Attention : la piste a été modifiée pendant l'export (p001 : texte modifié ; approbation de la
> réalisation retirée). Ces changements sont bien enregistrés, mais ce film ne les contient pas :
> relancez « wasf exporter » pour les y mettre.

Le film et le rapport décrivent toujours l'état lu au début, celui qui a servi à les fabriquer.
La mesure de chaque voix garde le texte pour lequel elle a été prise : l'éditeur sait donc qu'elle
ne vaut plus pour le nouveau texte.

**Fichiers.** `wasf/pipeline.py` (fin de `render`, `changed_during_export`).

**Tests.** `tests/test_export_edits.py` : une vraie modification envoyée à l'éditeur pendant
l'export (texte, puis approbation retirée), une validation faite pendant une version de travail,
un export sans modification (aucun message), et ce qui compte comme changement.

**Limite.** Une sauvegarde de l'éditeur faite dans la fraction de seconde entre la relecture et
l'écriture du projet par l'export pourrait encore être perdue. Un verrou partagé entre l'éditeur
et l'export fermerait ce créneau ; il n'a pas semblé utile à ce stade.

## 2. Les enregistrements sont tous vérifiés avant de commencer

**Avant.** Avec la voix « humain », l'export s'arrêtait au premier fichier manquant :

> Enregistrement manquant : p002.wav (ou .mp3, .m4a…) dans …/voix

On l'ajoutait, on relançait, et l'export s'arrêtait au suivant (p003 abîmé, puis p004). Un
`annonce.wav` illisible faisait échouer tout l'export à la toute fin, après le mixage, avec une
erreur de FFmpeg.

**Ce qui a changé.** Avant tout travail, Wasf regarde le dossier entier et liste d'un coup ce qui
manque et ce qui est inutilisable, puis les fichiers qui ne servent à aucun passage, souvent une
erreur de nom :

> Enregistrements à compléter avant l'export, dans …/voix :
> - manquants (2) : p002, p004
> - inutilisables (1) : p003.wav (illisible)
>
> Chaque passage attend un fichier à son nom, par exemple p002.wav, ou .mp3, .m4a, .ogg, .flac, .opus.
> Fichiers du dossier qui ne servent à aucun passage (nom ou format) : p2.m4a

Les noms en majuscules d'un téléphone (`P003.M4A`) sont reconnus. Un fichier au bon nom mais dans
un format non pris en charge (`p002.amr`) est signalé. L'annonce reste facultative : absente ou
illisible, le carton reste muet comme avant, mais Wasf affiche la phrase exacte à enregistrer.
Rien n'est créé dans le dossier d'export tant que la liste n'est pas complète.

**Fichiers.** `wasf/tts.py` (`find_recording`), `wasf/media.py` (`audio_problem`),
`wasf/pipeline.py` (`check_recordings`, annonce illisible).

**Tests.** `tests/test_recordings.py` : six formats et des majuscules ; manquant, illisible, vide,
mal nommé, format non pris en charge et `desktop.ini` ignoré, dans un seul message ; version de
travail ; dossier absent ; annonce absente, puis illisible, puis présente.

## 3. Chaque voix est mesurée avant l'export final

**Avant.** Aucune mesure du son des voix. Un fichier muet (micro coupé) passait dans l'export
final : le passage était approuvé, mais le spectateur n'entendait rien.

**Ce qui a changé.** Chaque voix est mesurée telle qu'elle sort du moteur ou de l'enregistrement,
avant toute accélération. Le son du film n'est jamais analysé : ses silences et sa musique sont
voulus et donneraient de fausses alertes.

| Problème | Mesure | Seuil | Effet |
| --- | --- | --- | --- |
| Voix muette ou presque | crête de la voix | sous −40 dBFS | **bloque l'export final** |
| Son saturé | crêtes écrêtées (3 échantillons ou plus à 99 % du maximum) | 3 crêtes ou plus | alerte |
| Écart de volume | niveau de la parole (trames de 20 ms au-dessus de −45 dBFS) | à plus de 6 dB de la médiane des voix | alerte |
| Voix trop courte | durée de parole | moins de 40 % de la durée que demande le texte (textes de 1 s ou plus) | alerte |
| Silence au début ou à la fin | silence avant ou après la parole | plus de 1 s | alerte |

Chaque problème donne le passage, son moment dans le film, la valeur mesurée, le seuil et quoi
faire. Les alertes ne bloquent jamais rien. Une voix trop longue pour sa pause (lot 1, T24) dit
maintenant aussi combien de silence elle contient :

> p001 : 2,5 s de voix, accélérée ×1,30 pour 1,4 s disponibles ; elle déborde de 1,1 s sur le
> dialogue. Elle contient 0,7 s de silence au début et 0,9 s à la fin : « --couper-silences »
> retire ce silence.

Wasf ne corrige rien de lui-même. `wasf exporter … --couper-silences` retire, sur demande, le
silence avant et après chaque voix, en gardant 0,08 s de marge de chaque côté ; une pause au milieu
de la parole n'est jamais touchée, et la parole reste telle quelle (au plus une unité d'écart sur
32 768, due à la réécriture du fichier). Le rapport note combien de silence a été coupé pour
chaque voix.

**Son identique.** Sans `--couper-silences`, le son exporté est identique à l'octet près à celui
d'avant le lot : même empreinte SHA-256 pour la piste mixée et la voix seule, en français, arabe et
derja, avec les voix `bip` et `espeak` (12 fichiers comparés).

**Temps et mémoire.** Mixage d'un film de 20 minutes avec 198 voix, deux passages chacun :

| Version | Temps du mixage | Mémoire maximale |
| --- | --- | --- |
| Avant le lot | 43,0 à 43,9 s | 122,2 à 122,3 Mo |
| Première version du correctif (un décodage FFmpeg de plus par voix) | 56,4 à 56,7 s | 123,9 à 124,1 Mo |
| Version finale (voix lue directement, sans nouveau processus FFmpeg) | 29,7 à 32,1 s | 123,5 à 123,8 Mo |

La première version ralentissait le mixage de 30 %. La version finale lit chaque voix
directement dans son fichier WAV et réutilise ces échantillons quand la voix n'est pas accélérée :
le mixage est plus rapide qu'avant le lot, pour 1,5 Mo de mémoire en plus.

**Fichiers.** `wasf/mix.py` (mesures, `quality_problems`, `trim_silence`, refus),
`wasf/media.py` (`read_pcm16_wav`), `wasf/pipeline.py` (refus selon le problème, option),
`wasf/cli.py` (`--couper-silences`).

**Tests.** `tests/test_voice_checks.py` : voix normale, muette, saturée, trop faible, trop courte,
silence au début ; une pause voulue au milieu d'une voix (aucune alerte, rien de coupé) ; dans un
vrai export : voix muette (export final refusé, version de travail possible), alertes qui ne
bloquent pas, silence coupé sur demande avec la parole gardée à l'identique, et les silences du
film qui ne déclenchent rien.

**Limites.** Les mesures portent sur le son, pas sur la prononciation : une voix bien audible peut
mal dire un mot de derja. Les seuils sont des choix de départ, pas encore réglés sur de vrais
enregistrements de l'équipe. Dans une pièce bruyante (bruit au-dessus de −45 dBFS), le silence
n'est pas repéré et rien n'est coupé.

## 4. Une vidéo changée depuis la préparation

**Avant.** Si la vidéo à côté du projet était remplacée par une version plus courte, l'export
final se terminait sans rien dire d'autre que deux lignes de journal : le film sortait sans les
passages d'après la fin, pourtant approuvés.

| Essai | Avant | Après |
| --- | --- | --- |
| Piste approuvée de 5 passages, vidéo remplacée par ses 20 premières secondes | film produit avec p001 à p003 ; « p004 : hors de la durée du film, ignoré. » | export final refusé : « la vidéo court.mp4 dure 20,0 s, mais la piste a été préparée sur une vidéo de 30,0 s… » |
| Banc d'essai de 20 min dont la dernière pause dépasse la fin du film | 2,5 s de la dernière voix coupées sans un mot | refus : « p199 : la fin du film couperait 2,5 s de cette voix. » |

**Ce qui a changé.** L'export compare la durée de la vidéo à celle mesurée à la préparation. Au-delà
d'une demi-seconde d'écart, l'export final est refusé avec la marche à suivre : remettre la vidéo
d'origine, refaire la préparation, ou faire une version de travail. Le même film réencodé passe.
Dans tous les cas, un passage qui tombe après la fin du film, ou une voix que la fin du film
couperait, est nommé ; l'export final s'arrête dessus.

**Fichiers.** `wasf/pipeline.py` (durée comparée, refus), `wasf/mix.py` (`hors_film`, `coupee`).

**Tests.** `tests/test_film_changed.py` : vidéo raccourcie (refus), version de travail (passages
perdus nommés), même film réencodé (accepté), passage après la fin et voix coupée sur un film de
synthèse, conseil adapté dans le message de refus.

**Limite.** Seule la durée est comparée : un autre montage de même durée n'est pas repéré.

## 5. Le rapport dit qui lit les descriptions

**Avant.** Ni `rapport_transparence.json` ni `credits.txt` ne disaient si la voix était un
enregistrement ou une voix de synthèse, ni laquelle.

**Ce qui a changé.** Le rapport gagne trois champs, et les crédits deux lignes :

- `voix_utilisee` : le moteur, la voix et le service. Exemples dans les crédits :
  « Voix : voix de synthèse ar-TN-ReemNeural (Azure AI Speech) », « Voix : voix de synthèse
  espeak-ng (fr), sur cet ordinateur ». Seuls des noms y figurent, jamais un chemin de l'ordinateur.
- `controle_audio` : les contrôles faits, le nombre de problèmes bloquants et d'alertes, leur type
  et le détail de chacun (passage, moment, mesure, seuil, quoi faire). Sans problème, il est écrit
  « aucun problème trouvé par ces contrôles », jamais « aucune erreur ». Une version de travail
  avec un problème bloquant le dit : « version de travail seulement ».
- `duree_film_s` : la durée du film.

Pour le moteur « humain », Wasf ne peut pas savoir qui a fait les fichiers. Les crédits disent donc
seulement ce qu'il sait : « enregistrements fournis par l'équipe (moteur « humain »), sans
synthèse vocale par Wasf ». Si un de ces fichiers vient d'une voix de synthèse, c'est à l'équipe de
le dire. Quand rien n'a été mesuré, les champs restent vides (`null`).

**Fichiers.** `wasf/tts.py` (`describe_voice`), `wasf/export.py` (`audio_summary`, crédits),
`wasf/pipeline.py`.

**Tests.** `tests/test_report_voice.py` : enregistrements fournis (sans chemin local dans le
rapport), voix espeak, signal de test, chaque moteur décrit, une alerte comptée sans jamais
écrire « aucun problème », un problème bloquant dans une version de travail, rien de mesuré.

## 6. Un `projet.json` abîmé

**Avant.**

> json.decoder.JSONDecodeError: Expecting value: line 1 column 28 (char 27)

précédé d'une vingtaine de lignes de traceback Python.

**Après.**

> Erreur : Projet illisible : …/projet.json (JSON invalide à la ligne 1, colonne 28). Il a sans
> doute été modifié à la main ou mal copié ; Wasf l'a laissé tel quel. Aucune sauvegarde
> « sauvegarde-… » dans ce dossier : remettez une copie de projet.json, ou refaites la préparation.

S'il existe des sauvegardes (`--remplacer` en crée), le message les nomme. Le fichier n'est jamais
touché. L'éditeur refuse de démarrer sur un projet abîmé ; s'il est abîmé pendant que l'éditeur
est ouvert, la page affiche le même message au lieu d'une erreur sans explication.

**Fichiers.** `wasf/project.py` (`ProjectFileError`, `load_project`), `wasf/cli.py`,
`wasf/editor/app.py`.

**Tests.** `tests/test_project_file.py` : JSON coupé, fichier vide, texte non UTF-8, liste au lieu
d'un projet, passages mal formés, sauvegardes nommées, éditeur au démarrage et en cours de route.

## Essai avec le projet derja de l'équipe

Le projet `essais/demo3` (5 passages en derja écrits par Gemini) a été exporté avec la voix
« humain ». Les enregistrements sont des **remplaçants** : chaque phrase lue par espeak-ng, avec
0,7 s de silence avant et 0,6 s après, enregistrée en `.m4a`, comme un téléphone qu'on lance un peu
tôt et qu'on arrête un peu tard. Ce n'est pas une voix humaine : l'essai vérifie le chemin des
fichiers, pas la qualité d'une voix.

- `P003.M4A`, en majuscules, est trouvé.
- Sans option, l'export final est refusé : p001, p004 et p005 débordent de leur pause (1,4 s pour
  p001 et p005), et chaque message dit combien de silence la voix contient.
- Avec `--couper-silences`, l'export final passe : 1,45 à 1,51 s de silence coupé par voix, toutes
  les voix dans leur pause, aucune alerte, niveaux entre −21,2 et −20,7 dBFS.
- L'annonce absente est signalée avec la phrase à enregistrer. Elle contient le nom tel que la
  réalisation l'a signé : signé « Équipe Bou Dinar », la phrase en arabe se termine par ce nom en
  français.

## Écarté, et pourquoi

| Proposition | Pourquoi elle n'est pas dans le lot |
| --- | --- |
| Un second rapport « qualité » | il répéterait `rapport_transparence.json`, qui a été complété à la place |
| La mémoire maximale dans chaque rapport | elle ne compterait que Python, pas FFmpeg, et ne dit rien à une réalisatrice ; le banc d'essai la mesure |
| Chercher silences et sauts de volume dans le film mixé | les silences et la musique du film donneraient de fausses alertes ; on mesure les voix |
| Garder les chemins des voix ou un cache de voix | chaque export refait toutes les voix ; un cache pourrait faire entendre une voix périmée |
| Une mention « qualité : OK » | elle se lirait « aucune erreur » ; le rapport dit ce qui a été contrôlé et ce qui a été trouvé |
| Refaire un seul passage par l'IA à la demande | une fonction nouvelle, pas un correctif ; l'éditeur permet déjà de réécrire un passage |
| Plus de nettoyage des fichiers temporaires | le dossier de mixage est déjà supprimé, même en cas d'échec ; le reste est dans le dossier d'export et remplacé au prochain export |

## Reste à faire ou à décider

- Régler les seuils du contrôle des voix sur de vrais enregistrements de l'équipe.
- L'annonce parlée ne dit pas si la voix est de synthèse : à décider par l'équipe (le rapport et
  les crédits, eux, le disent).
- Tests du lot 2 lancés sous Linux seulement ; sous Windows, non encore vérifiés.
- Les utilisateurs aveugles et malvoyants n'ont pas encore testé Wasf.

## Fichiers modifiés

| Fichier | État | Lignes (+ / −) | Pour |
| --- | --- | --- | --- |
| `wasf/cli.py` | modifié | +8 / −2 | 3 `--couper-silences` ; 6 message clair |
| `wasf/editor/app.py` | modifié | +6 / −1 | 6 projet abîmé au démarrage et en cours de route |
| `wasf/export.py` | modifié | +63 / −2 | 5 voix utilisée, contrôle des voix, crédits |
| `wasf/media.py` | modifié | +30 / −0 | 2 fichier son utilisable ; 3 lecture directe des voix |
| `wasf/mix.py` | modifié | +235 / −24 | 3 mesures et alertes, silence coupé ; 4 passage hors du film |
| `wasf/pipeline.py` | modifié | +158 / −15 | 1 modifications gardées ; 2 vérification des enregistrements ; 3 et 4 refus ; 5 rapport |
| `wasf/project.py` | modifié | +32 / −3 | 6 `ProjectFileError` |
| `wasf/tts.py` | modifié | +48 / −5 | 2 `find_recording` ; 5 `describe_voice` |
| `tests/test_export_edits.py` | nouveau | +134 / −0 | 1 |
| `tests/test_recordings.py` | nouveau | +139 / −0 | 2 |
| `tests/test_voice_checks.py` | nouveau | +256 / −0 | 3 |
| `tests/test_film_changed.py` | nouveau | +142 / −0 | 4 |
| `tests/test_report_voice.py` | nouveau | +138 / −0 | 5 |
| `tests/test_project_file.py` | nouveau | +82 / −0 | 6 |
| `README.md` | modifié | +42 / −11 | voix, éditeur, rapport, tests, limites |
| `docs/LOT2_CORRECTIFS.md` | nouveau | | ce document |

Aucune commande n'a changé de nom ; la seule option nouvelle est `--couper-silences`, sur
`wasf exporter`.

## Rejouer les vérifications

```bash
pip install -e ".[dev,gemini,anthropic,openai]"
pytest                                   # toute la suite
pytest tests/test_export_edits.py tests/test_recordings.py tests/test_voice_checks.py \
       tests/test_film_changed.py tests/test_report_voice.py tests/test_project_file.py   # le lot 2
```

Le test de la voix espeak est sauté si espeak-ng n'est pas installé.
