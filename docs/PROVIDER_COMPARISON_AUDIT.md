# Audit de l'agent Wasf : comparaison des fournisseurs d'IA

Ce rapport compare ce que le code fait avec chaque fournisseur : Gemini, Claude, OpenAI et Ollama.
**Le dépôt ne contient aucune mesure comparable entre fournisseurs** : aucune description produite
par un vrai modèle, aucun temps de réponse, aucun jeton compté, aucun taux d'erreur. Toutes les
lignes de qualité ci-dessous disent donc « non établi », et le rapport finit par le protocole qui
permettrait de les établir.

## 1. Ce que fait chaque adaptateur (`wasf/providers.py`)

| | Gemini | Claude | OpenAI | Ollama |
| --- | --- | --- | --- | --- |
| Bibliothèque | `google-genai` | `anthropic` | `openai` | `requests`, API HTTP d'Ollama |
| Clé | `GEMINI_API_KEY` ou `GOOGLE_API_KEY` | `ANTHROPIC_API_KEY` | `OPENAI_API_KEY`, ou aucune avec `--url` | Aucune |
| Modèle par défaut dans le code | `gemini-3.6-flash` | `claude-haiku-5-5` | `gpt-6-luna` | `gemma3` |
| Ordre envoyé | Images, puis texte | Images, puis texte | Texte, puis images | Texte, images en pièces jointes |
| Consigne système | `system_instruction` | `system` | message `system` | message `system` |
| Réponse JSON imposée | Oui (`response_mime_type`) | Non, seulement demandée | Non, seulement demandée | Oui (`format: json`) |
| Température | Non envoyée (Gemini 3 l'ignore, selon le commentaire du code) | Non envoyée | 0,4 pour un serveur compatible ; non envoyée chez OpenAI | 0,4 |
| Limite de longueur de réponse | Aucune fixée | **400 jetons**, sans vérifier si la réponse a été coupée | Aucune fixée | Aucune fixée |
| Délai d'attente | 120 s, fixé par Wasf | Celui de la bibliothèque | Celui de la bibliothèque | 600 s |
| Nouvelles tentatives | Par Wasf : 2 au plus, sur limite par minute (attente annoncée par Google, 65 s au plus) ou serveur saturé (10 s puis 20 s) | Celles de la bibliothèque (deux, selon le README) | Celles de la bibliothèque (deux, selon le README) | Aucune |
| Erreurs fatales (arrêt de la préparation) | 401, 403, 404, quota du jour, clé invalide | 401, 403, 404, crédit épuisé | 401, 403, 404, quota épuisé | Serveur injoignable, 404 |
| Modèle réellement utilisé, noté | `model_version` | `model` | `model` | `model` |

Remarques sur ce tableau :

- **Les noms de modèles par défaut** sont ceux du code. Les fournisseurs les changent souvent ; le
  README le dit. Le rapport de transparence note le nom que l'API dit avoir utilisé
  (`modeles_utilises`), ce qui est une bonne pratique.
- **Claude et ses 400 jetons.** La réponse demandée est un objet JSON : quatre observations, des
  changements, des interactions, des émotions avec leurs indices, la description, les appuis et
  une remarque. En arabe ou en derja, un même texte coûte souvent plus de jetons qu'en français.
  Une réponse coupée n'est plus du JSON valide. `parse_reply` prend alors tout le texte brut comme
  description, et les contrôles le bloquent ou le signalent. Ce cas n'a pas été mesuré. L'adaptateur
  ne lit pas la raison de fin de réponse (`stop_reason`), qui dirait si la réponse a été coupée.
- **Aucun adaptateur ne fixe de graine aléatoire**, et la température diffère d'un fournisseur à
  l'autre. Deux préparations du même film ne donnent pas forcément le même texte.

## 2. Ce que chaque passage coûte en appels

| Appel | Images | Quand |
| --- | --- | --- |
| Brouillon | 4 par défaut | Toujours, une fois |
| Réécriture | Aucune ; consigne système et brouillon renvoyés | Sur une erreur, 2 fois au plus |
| Seconde lecture | Les 4 mêmes | Si elle est demandée et que le passage parle de personnes |
| Nouvelle tentative | Comme l'appel qu'elle refait | Gemini : limite par minute ou serveur saturé ; Claude et OpenAI : selon leur bibliothèque |

Le rapport de transparence compte les appels qui ont produit les textes actuels
(`appels_au_modele`). **Rien n'enregistre les jetons consommés ni le temps de réponse** : les
adaptateurs jettent les champs d'usage que renvoient les API. Le coût d'un film ne peut donc pas
être calculé à partir d'un projet. Pour le savoir, il faut regarder la facture du fournisseur, ou
ajouter cet enregistrement au code.

## 3. La comparaison demandée

| Critère | Gemini | Claude | OpenAI | Ollama |
| --- | --- | --- | --- | --- |
| Compréhension visuelle | Non établi | Non établi | Non établi | Non établi |
| Raisonnement sur plusieurs images | Non établi | Non établi | Non établi | Non établi |
| Qualité des descriptions | Non établi | Non établi | Non établi | Non établi |
| Français | Non établi | Non établi | Non établi | Non établi |
| Arabe standard | Non établi | Non établi | Non établi | Non établi |
| Derja tunisienne | Non établi | Non établi | Non établi | Non établi |
| Temps de réponse | Non mesuré | Non mesuré | Non mesuré | Non mesuré ; dépend de la machine |
| Jetons consommés | Non enregistré | Non enregistré | Non enregistré | Non enregistré |
| Coût | Non calculable depuis le projet | Non calculable | Non calculable | Électricité locale, mesurable avec CodeCarbon |
| Taux d'erreur | Non mesuré | Non mesuré | Non mesuré | Non mesuré |
| Nouvelles tentatives | Par Wasf | Par la bibliothèque | Par la bibliothèque | Aucune |
| Confidentialité | Images, dialogues et notes envoyés à Google ; l'offre gratuite peut les réutiliser (le code l'annonce) | Envoyés à Anthropic | Envoyés à OpenAI, ou au serveur de `--url` | Restent sur l'ordinateur si Ollama y tourne |
| Hors ligne | Non | Non | Avec un serveur local compatible seulement | Oui |

**La comparaison ne peut pas encore être établie.** Toute phrase du type « Gemini décrit mieux la
derja » ou « Claude voit mieux les gestes » serait aujourd'hui une supposition.

## 4. Confidentialité, en détail

- **Ce qui part chez un fournisseur en ligne**, à chaque brouillon :
  - les images ;
  - le titre ;
  - l'intention de la réalisation ;
  - les noms et descriptions des personnages ;
  - le lexique et les exemples ;
  - les dialogues voisins et l'histoire jusque-là ;
  - **la liste de ce qu'il ne faut jamais révéler**, c'est-à-dire les secrets de l'intrigue.
- **Le rappel affiché** : `prepare` affiche un rappel pour Gemini, Claude et OpenAI, mais seulement
  sans `--url`. Avec `--url` (un serveur compatible, peut-être distant) ou avec Ollama sur une
  autre machine (`OLLAMA_HOST`), aucun rappel n'est affiché.
- **Le rapport de transparence** note le fournisseur et le modèle, pas l'adresse du serveur. On ne
  peut donc pas savoir, après coup, si les images ont quitté l'ordinateur.

## 5. Protocole pour une comparaison reproductible

Le détail des scènes et des métriques est dans [BENCHMARK_PROTOCOL.md](BENCHMARK_PROTOCOL.md).
Voici ce qui est propre à la comparaison des fournisseurs.

1. **Mêmes entrées pour tous.** Lancer une seule fois `wasf preparer --fournisseur mock` pour
   figer les pauses, les images et les budgets. Puis envoyer à chaque fournisseur exactement les
   mêmes images et la même consigne.
2. **Même contexte pour tous.** Dans Wasf, la consigne d'un passage contient les descriptions
   déjà écrites par le modèle (`story_so_far`) : chaque fournisseur verrait donc une histoire
   différente, la sienne. Pour comparer, il faut un contexte figé : les dialogues seuls, ou des
   descriptions de référence écrites par l'équipe. Cela demande un petit script hors de Wasf, qui
   n'existe pas encore.
3. **Mêmes réglages.** Noter pour chaque fournisseur :
   - le modèle demandé et le modèle rendu ;
   - la date ;
   - la température quand on peut la fixer.

   Faire 3 passages par scène pour mesurer la variation d'un essai à l'autre.
4. **Tout noter.** Par appel, noter :
   - les jetons d'entrée et de sortie (champs d'usage des API) ;
   - le temps de réponse ;
   - la validité du JSON ;
   - les erreurs et les nouvelles tentatives ;
   - les contrôles de Wasf déclenchés.

   Calculer le coût aux tarifs publiés le jour de l'essai, en citant la page.
5. **Juger à l'aveugle.** Les correcteur·rices ne savent pas quel fournisseur a écrit quelle
   description : on mélange l'ordre et on retire les noms.
6. **Dire la taille de l'essai.** Quelques dizaines de passages donnent une première indication,
   pas un classement. Le rapport final doit donner le nombre de passages, les écarts entre essais,
   et les cas où un fournisseur a échoué.
