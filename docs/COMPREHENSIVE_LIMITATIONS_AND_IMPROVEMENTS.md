# Limites connues et améliorations : état complet après le lot 3

Ce document reprend les quinze limites examinées lors de l'audit du 15 novembre 2026 (phase 0,
code relu avant toute modification). Pour chacune : son classement, ce que fait le code, ce que
le lot 3 a changé, les tests, et ce qui reste. Il ne promet aucun gain de justesse visuelle :
aucune évaluation sur de vrais films n'a encore été faite.

Classements : **corrigible** (une correction de code suffit), **améliorable** (un progrès
mesurable), **calibrage** (il faut de vrais enregistrements ou des films annotés),
**validation humaine** (le logiciel seul ne peut pas trancher), **hors champ pour l'instant**
(reste une limite documentée).

## En bref

| # | Limite | Classement | État après le lot 3 | Tests |
| --- | --- | --- | --- | --- |
| A | La simulation hors ligne ne voit pas les images | Déjà corrigé | Annoncée partout comme simulation ; le rapport dit aussi qu'aucun appel réel n'a eu lieu | `test_trust.py`, `test_energy_scope.py` |
| B | La liste « à éviter » ne voit que les variantes d'écriture | Validation humaine | Inchangé | aucun |
| C | Les contrôles de langue sont des règles simples | Calibrage | Inchangé | aucun |
| D | Sans sous-titres, les pauses viennent des silences | Calibrage | Inchangé | aucun |
| E | Sous-titres en français, description en derja | Hors champ pour l'instant | Inchangé | aucun |
| F | Voix de synthèse faibles en derja | Validation humaine | Inchangé ; la voix humaine reste recommandée | aucun |
| G | La confiance de l'IA n'est pas une garantie | Corrigible | **Corrigé** : affichée comme la note que l'IA se donne | `test_energy_scope.py` |
| H | Visages, gestes, continuité | Calibrage | Inchangé ; le choix des images était déjà adaptatif | aucun |
| I | La mesure d'énergie est incomplète | Améliorable | **Amélioré** : le rapport dit ce qui est mesuré et compte les appels au modèle | `test_energy_scope.py` |
| J | Erreurs des fournisseurs et nouvelles tentatives | Corrigible | **Corrigé** pour les erreurs fatales ; politique unique de nouvelles tentatives à faire | `test_fatal_errors.py` |
| K | La durée affichée à la relecture est une estimation | Déjà corrigé | Inchangé | tests de l'éditeur |
| L | Une modification faite pendant un export peut se perdre | Déjà corrigé (lot 2) | Inchangé | `test_export_edits.py` |
| M | Le contrôle des voix mesure le son, pas la prononciation | Calibrage | Inchangé | `test_voice_checks.py` |
| N | Origine des enregistrements | Corrigible | **Corrigé** : déclaration de l'équipe, marquée non vérifiée | `test_voice_source.py` |
| O | Un film remplacé, de même durée, passait inaperçu | Corrigible | **Corrigé** : empreinte du fichier, avertissement | `test_film_fingerprint.py` |

## Résultats

| | Avant le lot 3 | Après le lot 3 |
| --- | --- | --- |
| Tests sous Linux | 255 réussis | 292 réussis, en 8 min 31 |
| Nouveaux tests | | 37, dans 4 fichiers |
| Tests existants modifiés | | 2 assertions de libellé (point G, voir plus bas) |
| Avertissements du linter (ruff) | 26 | 25, aucun nouveau |
| Windows | 253 réussis, 2 ignorés (lot 2) | à relancer sur le PC de l'équipe |

## Ce que le lot 3 a changé

### J. Une erreur qui reviendrait à chaque passage arrête la préparation

- **Avant** : chaque erreur du fournisseur était attrapée passage par passage
  (`DescriberAgent.describe`). Une clé refusée, un modèle inconnu ou un quota du jour épuisé
  faisaient donc échouer tous les passages restants, l'un après l'autre, et la préparation
  « finissait » avec une piste vide.
- **Cause** : rien ne distinguait une erreur passagère d'une erreur qui reviendra à coup sûr.
- **Correction** : `providers.is_fatal` reconnaît les erreurs fatales par leur statut HTTP (401,
  403, 404) et par les codes des fournisseurs (`PerDay` et `API key not valid` chez Gemini,
  `insufficient_quota` chez OpenAI, `credit balance` chez Claude), plus un serveur Ollama qui ne
  répond pas du tout. `ProviderError` porte alors `fatal=True`. `pipeline._stop_on_fatal` garde
  chaque passage fini, inscrit `arret_fournisseur` dans l'historique (passage et raison), et
  s'arrête avec la marche à suivre : `--reprendre --refaire-echecs` une fois le problème réglé.
- **Inchangé** : une limite par minute, un serveur surchargé ou un délai dépassé restent des
  erreurs passagères : le passage est sauté et pourra être refait.
- **Tests** (`test_fatal_errors.py`, 19 cas) : classement de quatorze erreurs types, Ollama éteint
  ou lent, arrêt au troisième passage sans aucun appel après, reprise qui ne redemande rien de
  déjà écrit, erreur passagère qui ne saute que son passage, message de la ligne de commande.
- **Reste à faire** : une politique de nouvelles tentatives unique et réglable pour tous les
  fournisseurs (aujourd'hui : Gemini attend et réessaie, les bibliothèques de Claude et d'OpenAI
  réessaient d'elles-mêmes, Ollama jamais), et l'historique de chaque tentative.

### N. L'origine des enregistrements, déclarée par l'équipe

- **Avant** : avec le moteur « humain », le rapport disait seulement « enregistrements fournis
  par l'équipe ». Rien ne permettait de dire qu'un fichier était une voix de synthèse faite
  ailleurs, ni qui avait prêté sa voix.
- **Correction** : `wasf exporter --source-voix humaine|synthese|inconnue --voix-de "…"`.
  `tts.declared_source` garde la déclaration telle quelle, avec `verifiee_par_wasf: false`. Le
  rapport la reprend dans `voix_utilisee.declaration`, les crédits disent par exemple « déclarés
  comme voix humaines (Riadh), déclaration non vérifiée par Wasf », et l'historique note
  `source_voix_declaree`. Sans déclaration, les crédits disent « origine non déclarée par
  l'équipe ». Ces options sont refusées avec une voix de synthèse : Wasf la connaît déjà et la
  nomme lui-même. `--voix-de` sans `--source-voix` est refusé aussi.
- **Tests** (`test_voice_source.py`, 8 cas).
- **Ce qui ne peut pas être garanti** : Wasf n'authentifie pas une voix humaine. C'est une
  déclaration, et le texte le dit à chaque fois.

### I. Ce que mesure l'énergie, et ce qu'elle laisse de côté

- **Avant** : chaque mesure portait la remarque « mesure locale uniquement », mais le rapport ne
  disait ni ce qui restait hors mesure ni combien d'appels au modèle avaient été faits.
- **Correction** : le rapport ajoute `energie_portee` (ce qui est mesuré : cet ordinateur ; ce
  qui ne l'est pas : les serveurs du fournisseur en ligne, ou une machine Ollama distante, ou la
  seconde lecture si elle tourne en ligne) et `appels_au_modele` (avec images, texte seul, en
  échec, réels ou simulés), lus dans la trace de chaque passage (`export.model_calls`).
- **Tests** (`test_energy_scope.py`, 4 cas).
- **Ce qui ne peut pas être garanti** : la consommation des serveurs n'est jamais estimée par
  Wasf. Les appels d'une préparation refaite depuis ne sont plus dans les traces : non recomptés.

### G. La confiance de l'IA, présentée comme sa propre note

- **Avant** : un passage sous 0,5 était signalé « IA peu sûre (30 %) », ce qui se lit comme une
  probabilité mesurée d'avoir raison.
- **Correction** : « IA peu sûre (elle se note 0,3 sur 1) » (`agent.review_flags`). Le seuil, le
  signalement et l'obligation de validation humaine ne changent pas. Un passage sans
  signalement n'est jamais présenté comme juste.
- **Tests** : `test_energy_scope.py::test_confidence_is_shown_as_the_models_own_mark`. Deux
  assertions existantes vérifiaient l'ancien libellé mot pour mot (`test_units.py`,
  `test_emotion_scenarios.py`) : elles attendent le nouveau.
- **Ce qui ne peut pas être garanti** : cette note n'est pas calibrée. Elle sert à attirer
  l'attention, pas à mesurer la justesse.

### O. Un film remplacé est signalé, même de même durée

- **Avant** : seule la durée de la vidéo était comparée à celle de la préparation. Un autre
  montage de même durée passait inaperçu.
- **Correction** : `media.fingerprint` (taille du fichier et SHA-256 de trois tranches de 1 Mio :
  début, milieu, fin) est noté à la préparation (`Project.empreinte_film`). À l'export,
  `pipeline._film_check` compare : si le fichier a changé, l'export l'écrit dans son journal, dans
  le rapport (`controle_du_film`) et dans l'historique (`film_modifie_depuis_preparation`).
- **Choix : avertir, pas bloquer.** Une copie réencodée du même montage (plus légère, autre
  format) change aussi l'empreinte, et elle doit pouvoir s'exporter (`test_film_changed.py`). Une
  durée différente, elle, bloque toujours l'export final (lot 2).
- **Tests** (`test_film_fingerprint.py`, 5 cas) : empreinte sensible à un seul octet, notée à la
  préparation, même film reconnu, autre fichier de même durée signalé, ancien projet sans
  empreinte.
- **Ce qui ne peut pas être garanti** : l'empreinte dit que le fichier a changé, pas ce qui a
  changé. Les projets préparés avant ce lot n'ont que la durée, et le rapport le dit.

## Ce qui n'a pas changé, et pourquoi

Ces points demandent des données ou des personnes qu'aucun test automatique ne remplace. Les
changer sans mesure, c'était risquer de faire moins bien sans le savoir.

- **B. Synonymes dans la liste « à éviter »** (`textnorm.py`, `agent.run_checks`) : la
  vérification compare des mots après normalisation de l'écriture. Repérer des synonymes demande
  des listes écrites et relues par des locuteur·rices natif·ves du français, de l'arabe et de la
  derja, chacune à part, pour éviter de signaler du vocabulaire descriptif légitime.
- **C. Contrôles de langue** (`agent.py`, arabe standard dans un passage en derja) : les
  améliorer demande des échantillons de derja annotés. Les contrôles restent des signalements :
  la réalisation décide.
- **D. Pauses sans sous-titres** (`gaps.py`, `silencedetect` de FFmpeg à seuil fixe) : la musique
  masque les pauses. Une détection de la voix ou des seuils adaptatifs demanderaient une nouvelle
  dépendance et des films annotés pour mesurer précision et rappel. La méthode actuelle resterait
  le recours.
- **E. Réplique en français, description en derja** (`agent.run_checks`, comparaison de mots dans
  une même langue) : il faudrait une traduction ou un modèle sémantique multilingue, en simple
  signalement. Sans mesure, le risque de fausses alertes est trop grand.
- **F. Voix de synthèse en derja** (Azure `ar-TN`, espeak-ng, Piper) : leur intelligibilité,
  leur accent et leur prosodie ne peuvent être jugés que par des locuteur·rices natif·ves.
  L'enregistrement humain (moteur « humain ») reste recommandé.
- **H. Images, gestes, continuité** : le choix des images est déjà adaptatif
  (`media.most_distinct` retient les moments où l'image change, en ignorant les mouvements de
  caméra) ; aucun suivi ni aucune reconnaissance de visages ; la continuité vient des noms donnés
  par la réalisation (`continuity.py`). Le gain réel de la seconde lecture, les cas où deux
  modèles se trompent ensemble et la justesse sur de vraies scènes n'ont pas été mesurés.
  Protocole : `docs/TESTS_EMOTIONS.md`. Mots derja à faire relire : `docs/DERJA_A_RELIRE.md`.
- **M. Seuils du contrôle des voix** (`mix.py` : −40 dBFS, 6 dB, 40 %, 1 s) : choix de départ,
  à régler sur de vrais enregistrements de l'équipe (téléphone et voix de synthèse). Un son
  correct ne prouve pas une bonne prononciation : il faut une écoute par des locuteur·rices
  natif·ves.

## Déjà traité avant ce lot

- **A. Simulation** : annonce parlée, carton, WebVTT, crédits et rapport disent « simulation,
  aucune image analysée » ; la préparation le dit aussi (`test_trust.py`).
- **K. Durée estimée** : l'éditeur affiche « environ X s à dire pour Y s de pause » ; l'export
  mesure la vraie voix et refuse une voix qui déborde de sa pause.
- **L. Modification pendant un export** (lot 2) : l'export relit le projet à la fin, n'écrit que
  ses propres champs et signale ce que le film ne contient pas (`test_export_edits.py`). Reste
  une fraction de seconde entre la relecture et l'écriture.
- **Enregistrements vérifiés avant de commencer** et **`projet.json` abîmé** (lot 2) :
  `test_recordings.py`, `test_project_file.py`.

## Ce qui demande de vrais enregistrements, de vrais films ou des personnes

- Régler les seuils du contrôle des voix sur des enregistrements de l'équipe.
- Faire relire les listes de mots derja et écouter les voix de synthèse en derja.
- Mesurer la justesse sur de vraies scènes, avec et sans seconde lecture.
- Mesurer la détection des pauses sans sous-titres sur des films annotés.
- Faire juger les descriptions par des spectateurs aveugles et malvoyants.

Aucun de ces points n'a encore été fait : ce document ne prétend pas le contraire.

## Rejouer les tests

```bash
pip install -e ".[dev]"
pytest tests/test_fatal_errors.py tests/test_voice_source.py tests/test_energy_scope.py tests/test_film_fingerprint.py
pytest
```
