# Phase 0 : base de référence

Première phase de la feuille de route du nouvel agent
([`WASF_IMPLEMENTATION_SPECIFICATION.md`](WASF_IMPLEMENTATION_SPECIFICATION.md)), faite le
15 novembre 2026. Son but : savoir ce que coûte et ce que produit une préparation, avant de
changer la façon dont l'agent décrit.

**En bref.** Les instruments sont en place et testés. Aucune mesure sur un vrai modèle n'existe
encore : l'équipe n'a pas encore de modèle disponible, et elle a décidé de ne rien filmer. Rien de
ce document ne dit donc quoi que ce soit de la qualité des descriptions.

## Ce qui a changé dans le code

Rien dans la façon dont l'agent décrit : mêmes consignes, mêmes contrôles, même éditeur, même
export. Trois changements, approuvés par l'équipe :

| Changement | Fichiers | Ce qu'il apporte |
| --- | --- | --- |
| Garde de version | `wasf/project.py` | Wasf ignore à la lecture les champs qu'il ne connaît pas, et ne les réécrit pas. Un `projet.json` d'un format plus récent est donc refusé, à l'ouverture comme à l'enregistrement, avec un message clair : une version ancienne ne peut plus effacer ce qu'elle ne connaît pas. Nécessaire avant d'ajouter des champs en phase 1 |
| Journal des appels | `wasf/calllog.py` (nouveau), `wasf/providers.py`, `wasf/pipeline.py`, `wasf/agent.py` | Une ligne par appel au modèle dans `appels.jsonl`, à côté de `projet.json` : étape, passage, fournisseur, modèle demandé et modèle qui a répondu, nombre d'images, empreinte de la requête, jetons envoyés et reçus, raison de fin, durée, résultat. Les jetons ne sont notés que si l'API les donne, sinon `null` : jamais estimés. Ni clé (masquée même dans un message d'erreur), ni consigne, ni image. À la fin, `wasf preparer` affiche le total. Avec `--remplacer`, le journal suit l'ancien projet dans son dossier de sauvegarde |
| Limite de réponse de Claude | `wasf/providers.py`, `wasf/cli.py` | 1 024 jetons par défaut au lieu de 400, qui pouvaient couper une réponse JSON complète ; réglable avec `--jetons-max`. Une réponse coupée est annoncée pendant la préparation et notée au journal (`fin` : `max_tokens`) |

Ce que chaque API renvoie, et que le journal lit :

| Fournisseur | Jetons envoyés | Jetons reçus | Raison de fin | Nouveaux essais |
| --- | --- | --- | --- | --- |
| Gemini | `prompt_token_count` | `candidates_token_count` | `finish_reason` | Comptés : Wasf réessaie lui-même |
| Claude | `input_tokens` | `output_tokens` | `stop_reason` | `null` : le SDK réessaie de lui-même, sans que Wasf le voie |
| OpenAI | `prompt_tokens` | `completion_tokens` | `finish_reason` | `null`, pour la même raison |
| Ollama | `prompt_eval_count` | `eval_count` | `done_reason` | Un seul essai |
| Simulation | `null` | `null` | `simulation` | Un seul essai |

## Ce qui a été vérifié

- **La suite de tests** : 356 tests le 15 novembre 2026, 355 passés et 1 sauté, celui qui ne
  tourne que là où CodeCarbon est installé.
- **25 tests nouveaux** : `tests/test_version_guard.py` (projet relu à l'identique, format plus
  récent refusé et laissé intact, version mal formée expliquée, éditeur et export qui le disent)
  et `tests/test_call_log.py` (une ligne par appel, numérotation continue, aucune clé ni consigne,
  une reprise après Ctrl+C qui ne redemande aucun passage déjà écrit, journal gardé avec l'ancien
  projet, jetons et raison de fin lus pour chacun des quatre fournisseurs contre un faux serveur
  local, limite de Claude par défaut et réglable, option `--jetons-max` transmise).
- **Le clip de démonstration, avec la simulation** (30 s, 5 passages) : 10 appels, 5 brouillons
  avec images et 5 révisions en texte seul, aucun échec. Le journal compte exactement les appels
  que le rapport de transparence compte dans les traces. La simulation ne donne pas de jetons : le
  journal écrit `null`, comme prévu. Cela prouve que l'instrument fonctionne, pas que l'agent
  décrit bien.

## Ce qui n'a pas pu être mesuré, et pourquoi

| Mesure prévue | État | Raison |
| --- | --- | --- |
| Jetons, temps, coût et échecs d'un vrai modèle | Non mesurés | Aucun modèle disponible pour l'instant : l'équipe attend encore son accès à une API, et Ollama n'a pas encore été essayé |
| Qualité des descriptions | Non mesurée | Pas de vrai modèle, et pas de scènes réelles |
| Scènes tournées par l'équipe | Abandonnées | Décision de l'équipe : rien ne sera filmé |

**Le banc d'essai sans tournage.** Il reposera sur :

- des clips synthétiques fabriqués par FFmpeg (formes, couleurs, coupes et textes à des instants
  connus, personne à l'écran), qui vérifient la mécanique du temps : coupes, fenêtres, ordre des
  faits ;
- le clip de démonstration de Wasf ;
- si l'équipe le décide, des extraits de films publiés sous une licence qui autorise l'adaptation,
  comme Creative Commons BY. La licence sert alors de référence à l'accord du producteur, que Wasf
  exige.

Sur des clips synthétiques, on ne peut juger que la mécanique, jamais la qualité d'une description.

## Le premier essai réel, dès qu'un modèle est disponible

Sans clé ni compte, avec Ollama (les images ne quittent pas l'ordinateur) :

```bash
ollama pull gemma3
wasf preparer clip.mp4 --intention intention.yaml --sous-titres clip.srt --fournisseur ollama
```

Avec une clé, placée dans une variable d'environnement et jamais dans un fichier (PowerShell) :

```powershell
$env:GEMINI_API_KEY = "..."
wasf preparer clip.mp4 --intention intention.yaml --sous-titres clip.srt --fournisseur gemini
```

Pour un film réel, choisir une offre qui n'utilise pas les données envoyées (voir le README, « Choisir
le modèle d'IA »). Faire trois essais par clip avec les mêmes entrées, et reporter le total que
`wasf preparer` affiche à la fin :

| Date | Clip | Fournisseur et modèle | Appels | Jetons envoyés / reçus | Attente totale | Échecs | Réponses coupées |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | Aucun essai réel pour l'instant | | | | | | |

Le coût en argent se calcule ensuite à partir des jetons et du prix publié par le fournisseur le
jour de l'essai, en notant ce prix et sa source à côté du résultat.

## Ce que la phase 0 permet déjà

- Savoir combien d'appels et de jetons coûte une préparation, dès le premier essai réel.
- Comparer deux fournisseurs sur les mêmes entrées.
- Vérifier, ligne par ligne, qu'une reprise ne paie rien deux fois.
- Faire évoluer `projet.json` en phase 1 sans risque pour les projets existants.
