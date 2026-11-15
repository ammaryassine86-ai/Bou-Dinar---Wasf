# Audit de l'agent Wasf : éthique et vie privée

Ce rapport confronte chaque promesse éthique du projet à ce que fait le code. Les promesses
viennent du README, de `docs/ETHIQUE_360.md`, du fichier d'intention d'exemple et des textes que
Wasf écrit lui-même dans ses exports.

Pour chaque point, le verdict est l'un de ceux-ci :
- **conforme** : le code fait ce qui est promis ;
- **partiel** : le code le fait en partie, ou sous une condition que la promesse ne dit pas ;
- **écart** : le code ne fait pas ce qui est promis.

Les comportements marqués « exécuté » ont été reproduits avec le code audité, sans le modifier.
Après l'audit, le même jour, l'équipe a fait corriger trois de ces écarts : le consentement, la
mention dans le SRT et deux phrases des crédits. Les passages concernés le disent (« corrigé »).

## 1. Vue d'ensemble

| Promesse | Verdict | En une phrase |
| --- | --- | --- |
| Pas de film sans l'accord du producteur | Conforme depuis la correction (écart à l'audit) | `accord_producteur: non` passait, et la référence n'était pas exigée. Seul `true` est accepté, et la référence est obligatoire |
| Option entièrement locale | Partiel | Vrai avec Ollama sur l'ordinateur, mais rien ne le vérifie ni ne le note |
| Relecture humaine avant toute publication | Conforme | Imposée à l'export, avec des limites sur l'échantillon |
| Approbation de la réalisation | Partiel | Imposée, mais contournable par une option non documentée, et sans authentification |
| Pas de reconnaissance faciale | Conforme | Aucun outil de reconnaissance ; le modèle de vision a seulement pour consigne de ne nommer personne d'après son visage |
| Pas de reconnaissance automatique des émotions | Partiel | Aucun classifieur, mais en mode par défaut le modèle de vision peut nommer une émotion probable. Les crédits le disent maintenant sans promettre plus |
| Le film n'entraîne aucun modèle | Partiel | Vrai pour Wasf ; invérifiable pour le fournisseur. Les crédits ont été corrigés ; le rapport écrit encore `entrainement_sur_le_film: false` |
| Clés d'API protégées | Conforme | Lues dans l'environnement, jamais écrites par Wasf |
| Rapport de transparence | Conforme, avec des manques | Riche, mais muet sur l'adresse du serveur et sur l'offre utilisée |
| Mention de l'IA dans chaque export | Partiel | Le SRT l'affiche depuis la correction ; il n'en avait aucune à l'audit. Elle reste invisible dans le WebVTT, et absente du MP4 avec `--sans-annonce` |

## 2. Le consentement du producteur

**La promesse.** `ETHIQUE_360.md` dit que « `wasf preparer` refuse de traiter un film sans
`accord_producteur: true` et sans référence de l'accord ». Le README dit que l'accord est
obligatoire et que sa référence passe dans le rapport et les crédits.

**Le code audité.** `Intent.check_rights` vérifiait seulement `bool(droits["accord_producteur"])`.
La référence n'était jamais exigée.

**Le défaut.** En Python, tout texte non vide vaut « vrai ». Les essais (exécutés sur le code
audité) donnaient ceci :

| Valeur écrite dans le fichier YAML | Résultat |
| --- | --- |
| `true`, `oui`, `yes` | Accepté |
| **`non`** | **Accepté** |
| **`"non"`**, **`"false"`** (entre guillemets) | **Accepté** |
| `false`, `no`, `0`, `""` | Refusé |

Une équipe qui écrivait `accord_producteur: non`, en français, voyait donc son film traité. Sans
référence, les crédits écrivaient « Accord du producteur : oui ».

**Ce qui reste vrai.** L'accord est une déclaration de la personne qui remplit l'intention. Aucun
logiciel ne peut prouver qu'un producteur a dit oui. La référence (courriel, contrat) sert à le
retrouver ; c'est pourquoi elle devrait être obligatoire.

**Corrigé après l'audit** (`intent._as_consent`, `Intent.check_rights`) :

| Valeur écrite dans le fichier YAML | Résultat |
| --- | --- |
| `true` (ou `yes`, que YAML lit aussi comme vrai), avec une référence | Accepté |
| `true` sans référence, ou avec une référence vide | Refusé : la marche à suivre est donnée |
| `non`, `oui`, `"true"` ou `"false"` entre guillemets, `1`… | Refusé : « écrivez true […] sans guillemets » |
| `false`, `no`, rien | Refusé, comme avant |

`tests/test_consent.py` vérifie chacun de ces cas.

## 3. L'exécution locale et les données envoyées

**La promesse.** « Avec Ollama, rien ne quitte l'ordinateur. » Le README annonce aussi une
« option 100 % locale ».

**Le code** :

- **Ollama** : il tourne par défaut sur `127.0.0.1:11434`. Mais `OLLAMA_HOST` ou `--url` peuvent
  désigner une autre machine. Wasf ne l'interdit pas, n'affiche alors aucun rappel, et le rapport
  ne note pas l'adresse. Après coup, rien ne permet de dire si les images sont restées sur
  l'ordinateur.
- **Les fournisseurs en ligne** reçoivent les images et tout le texte de la consigne :
  - le titre ;
  - l'intention ;
  - les personnages ;
  - les dialogues voisins et l'histoire jusque-là ;
  - le lexique et les exemples ;
  - **la liste de ce qu'il ne faut jamais révéler**.

  Le rappel affiché par `prepare` parle « des images extraites et du texte ». Il ne précise pas
  que ce texte contient les secrets de l'intrigue.
- **L'éditeur** n'écoute que sur l'ordinateur local. C'est imposé par trois mécanismes, que les
  tests vérifient :
  - le contrôle de l'hôte ;
  - le contrôle de l'origine ;
  - un jeton de session par démarrage.
- **Les voix** : espeak-ng et Piper tournent sur l'ordinateur. Azure reçoit le texte des
  descriptions, et le rapport le dit (`sur_cet_ordinateur: false`).

**Verdict** : partiel. Le mode local existe et fonctionne, mais rien ne garantit qu'il est
utilisé, ni ne le prouve après coup.

## 4. La relecture humaine

**La promesse.** L'IA écrit, la réalisation décide. Rien n'est publié sans validation.

**Le code** (`pipeline.readiness_problems`) refuse l'export final dans trois cas :

- personne n'a signé ;
- un passage n'est ni validé ni ignoré ;
- la réalisation n'a pas approuvé la piste.

L'éditeur impose de relire un par un les passages de l'échantillon avant la validation en un
clic. La version de travail (`--brouillon`) contourne tout, mais elle est annoncée comme telle
partout : carton, annonce, WebVTT, crédits et rapport.

**Les limites** :
- **L'échantillon** est petit pour un film court, et une erreur trouvée ne déclenche rien de plus
  (voir [VALIDATION_AUDIT.md](VALIDATION_AUDIT.md)).
- **Un passage de l'échantillon peut être ignoré au lieu d'être relu.** Il débloque alors le clic
  et compte quand même comme « relu » dans le rapport et les crédits.
- **La relecture se fait sur les images fixes** que le modèle a vues, pas sur la vidéo.

**Verdict** : conforme. La relecture est vraiment imposée ; sa qualité dépend des personnes.

## 5. L'approbation de la réalisation

**Le code** :
- L'approbation demande que tous les passages soient validés ou ignorés, et qu'un nom de
  réalisation soit renseigné.
- Elle est retirée dès qu'un texte change, qu'un passage est rouvert ou qu'un nom change.
- Chaque action est datée dans l'historique.

**Les limites** :
- **Une option la contourne.** `wasf exporter --sans-validation-realisateur` exporte sans
  approbation. Le film l'annonce bien : le carton affiche « Approbation de la réalisation en
  attente » et les crédits « approbation en attente ». Mais l'option n'a pas de texte d'aide et
  n'apparaît pas dans le README. Seul le message d'erreur de l'export la mentionne.
- **Rien n'authentifie la personne qui approuve.** La signature et l'approbation sont un nom tapé
  dans l'éditeur. Toute personne devant l'ordinateur peut approuver au nom de la réalisation.
  Pour un outil local sans comptes, c'est attendu, mais la promesse doit le dire.

**Verdict** : partiel.

## 6. Pas de reconnaissance faciale

**Le code** :
- Aucune bibliothèque de détection ou de reconnaissance des visages : les dépendances sont numpy,
  Flask, PyYAML, requests, Pillow, plus des bibliothèques facultatives (fournisseurs d'IA, Azure,
  CodeCarbon).
- Les seules images analysées par Wasf lui-même sont des vignettes grises de 64 × 36 pixels, pour
  repérer où l'image change.
- La règle 7 de la consigne interdit de nommer un acteur ou une personne réelle d'après son
  visage.

**La limite.** Un modèle de vision généraliste peut reconnaître une personne célèbre. Seule la
consigne l'en empêche : aucun contrôle ne signale un nom absent de la liste des personnages.

**Verdict** : conforme pour Wasf. Le reste dépend du modèle.

## 7. Pas de reconnaissance automatique des émotions

**Le code** :
- Aucun classifieur d'émotions, aucun point du visage.
- En mode `nuancees`, qui est **le mode par défaut**, la consigne laisse le modèle de vision
  nommer une émotion **probable**. Il doit l'appuyer sur des signes visibles, avec une nuance, et
  rendre ses suppositions à part (`emotions`), avec une certitude.
- En mode `signes`, aucun mot d'émotion n'est permis.

**Ce que cela veut dire.** Wasf ne fait pas de reconnaissance des émotions au sens d'un système
qui classe des visages. Mais en mode par défaut, il demande bien au modèle de supposer ce que
ressent un personnage d'après son jeu à l'écran. `ETHIQUE_360.md` le présente honnêtement : ce
sont les émotions jouées par des acteurs, jamais l'état d'une personne réelle.

**Un point de cohérence, corrigé après l'audit.** Les crédits disaient « Émotions : nommées
seulement avec leurs signes visibles, jamais avec certitude ». Or une émotion sans signe n'est
qu'une alerte, et une certitude écrite par une personne aussi (exécuté, voir
[VALIDATION_AUDIT.md](VALIDATION_AUDIT.md)). Ils disent maintenant ce que l'IA « avait pour
consigne », ce qu'un mot de certitude bloque et ce qui est seulement signalé.

**Verdict** : partiel. L'équipe peut choisir de garder ce mode par défaut et de le décrire
précisément, ou de passer au mode `signes` par défaut.

## 8. Pas d'entraînement sur le film

**Le code** :
- Wasf n'entraîne et n'affine aucun modèle : aucun code d'entraînement dans le dépôt.
- Le rapport écrit `entrainement_sur_le_film: false`, en dur, quel que soit le fournisseur.
- Les crédits écrivaient « Le film n'est jamais utilisé pour entraîner un modèle d'IA. », même
  pour une simulation.
- `prepare` rappelle qu'une offre gratuite, comme celle de Gemini, peut réutiliser les données
  envoyées. `ETHIQUE_360.md` le dit aussi, avec un lien vers les conditions de Google.

**L'écart.** Wasf ne sait pas quelle offre l'équipe utilise. Si c'est une offre gratuite qui
réutilise les données, la phrase des crédits devenait fausse, alors qu'elle était écrite sans
condition.

**Corrigé après l'audit, pour les crédits** (`export._training_lines`). Ils disent maintenant :
« Wasf n'entraîne aucun modèle d'IA sur ce film. » Pour Gemini, Claude et OpenAI, ils ajoutent
que les images et les textes envoyés au fournisseur « relèvent de ses conditions d'utilisation,
que Wasf ne peut pas vérifier ».

**Ce qui reste** :
- le rapport écrit encore `entrainement_sur_le_film: false`, en dur ;
- noter dans le rapport l'offre déclarée par l'équipe, comme pour l'origine des voix, reste à
  décider.

**Verdict** : partiel.

## 9. La protection des clés d'API

**Le code** :
- Les clés sont lues uniquement dans les variables d'environnement : `GEMINI_API_KEY` ou
  `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AZURE_SPEECH_KEY`.
- Aucune option de la ligne de commande ne prend une clé.
- Aucun champ de `projet.json`, du rapport ou des crédits ne contient de clé.
- `.gitignore` exclut `.env`.

**Le point non vérifié.** Les messages d'erreur des fournisseurs sont copiés tels quels dans
`projet.json` : le journal de l'agent, et la raison de l'arrêt sur erreur fatale. Ces messages ne
devraient pas contenir la clé, mais cela n'a pas été vérifié avec les vrais services.

**Verdict** : conforme.

## 10. Le rapport de transparence

**Le code** (`export.transparency_report`). Le rapport donne :

- la mention lue en tête du film ;
- le fournisseur, le modèle demandé et les modèles que l'API dit avoir utilisés ;
- les signataires et l'approbation ;
- l'accord et sa référence ;
- le nombre de passages validés, dont ceux validés en un clic, et l'échantillon relu ;
- la part du texte changée par un humain ;
- le mode des émotions et le nombre de passages qui en nomment une ;
- la seconde lecture ;
- le contrôle du film ;
- la voix et le contrôle audio ;
- l'énergie et sa portée ;
- le nombre d'appels au modèle.

Rien n'y est estimé : un champ non mesuré reste vide.

**Les manques** :
- l'adresse du serveur, et l'offre du fournisseur ;
- la version des consignes ;
- l'énergie de la préparation, qui ne couvre pas l'extraction des images (voir
  [PERFORMANCE_RELIABILITY_AUDIT.md](PERFORMANCE_RELIABILITY_AUDIT.md)) ;
- `echantillon_relu`, qui compte aussi les passages ignorés ;
- `entrainement_sur_le_film`, écrit en dur.

**Verdict** : conforme, avec ces manques.

## 11. La mention de l'IA

**La promesse.** `ETHIQUE_360.md` dit que la mention « figure dans le WebVTT, le SRT, les crédits
et le rapport ». Le tableau des sorties du README dit que `audiodescription.vtt / .srt` contient
« les descriptions en texte, avec la mention IA ».

**Ce que produit l'export** (exécuté sur un film d'essai) :

| Sortie | Mention de l'IA |
| --- | --- |
| Carton et annonce parlée en tête du film | Oui, par défaut. Elle dit qui a validé, d'après les signatures |
| `film_audiodecrit.mp4` avec `--sans-annonce` | **Aucune** : ni carton, ni annonce, ni métadonnée. La piste s'appelle seulement « Audiodescription » |
| `audiodescription.vtt` | Oui, dans un bloc `NOTE`. Un bloc `NOTE` est un commentaire : les lecteurs ne l'affichent pas |
| `audiodescription.srt` | **Aucune à l'audit.** Le format SRT n'a pas de commentaire. **Corrigé** : la mention est le premier sous-titre, dès le début du film, le temps de la dire au débit de la piste (4 s au moins) |
| `credits.txt`, `rapport_transparence.json` | Oui |

Une simulation est toujours annoncée comme telle, et une version de travail aussi. Les tests le
vérifient, et l'export du film d'essai l'a confirmé pour la simulation.

**Verdict** : conforme pour le SRT depuis la correction, ce que vérifie
`tests/test_export_mentions.py`. Partiel pour le WebVTT, où la note reste invisible. Écart pour
le MP4 sans annonce.

**Un point trouvé pendant la correction.** Les sous-titres WebVTT et SRT gardent les instants du
film d'origine. Or, avec le carton (par défaut), `film_audiodecrit.mp4` commence par lui : dans
l'essai, le film y dure 606,9 s au lieu de 600 s. Chargés avec ce fichier, les sous-titres
arrivent donc 6,9 s trop tôt. Il faut soit les décaler de la durée du carton, soit dire dans la
documentation qu'ils vont avec le film d'origine.

## 12. Ce que promettent les documents, au-delà du code

Plusieurs documents annoncent des étapes avec des personnes concernées :

- `ETHIQUE_360.md` : « faire écouter la piste à des spectateurs aveugles (avec IBSAR) », et un
  « test prévu avec eux » ;
- `TESTS_EMOTIONS.md`, section 6 : un protocole de test avec des spectateurs aveugles et
  malvoyants, « avec IBSAR, par exemple » ;
- le README : « Pilote avec IBSAR et le festival HandyFilms », et « tester chaque piste avec des
  spectateurs aveugles et sourds avant de la vendre ».

Le dépôt ne contient aucune trace de prise de contact ni de résultat. Si l'équipe ne compte pas
faire ces étapes, ces phrases promettent plus que ce qui sera fait. Il faut alors les retirer, ou
les présenter comme ce qu'il faudrait faire avant un usage réel, sans dire qu'elles sont prévues.

## 13. Ce qu'il faudrait corriger, par ordre

Les trois premières corrections ont été faites après l'audit, à la demande de l'équipe. Les
autres restent à décider.

1. **Le consentement** : n'accepter que `true`, exiger la référence. **Fait.**
2. **La mention dans le SRT.** **Fait.**
3. **Les deux phrases sans condition des crédits** : l'entraînement, et la certitude des émotions.
   **Fait.**
4. **Le rapport** :
   - noter l'adresse du serveur, et afficher un rappel dès que les images partent ailleurs que
     sur l'ordinateur ;
   - dire dans le rappel que les secrets de l'intrigue partent aussi.
5. **L'option `--sans-validation-realisateur`** : la documenter.
6. **Les promesses de tests avec des personnes concernées**, à aligner sur ce que l'équipe fera
   vraiment.
7. **Le décalage des sous-titres avec le carton** : les caler sur `film_audiodecrit.mp4`, ou dire
   à quel film ils vont.
