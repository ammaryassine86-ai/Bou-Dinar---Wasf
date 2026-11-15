# Protocole d'évaluation de Wasf sur de vraies scènes

Ce document décrit comment mesurer ce que l'audit n'a pas pu mesurer : la justesse des
descriptions, leur utilité et la valeur des contrôles. **Il ne contient aucun résultat.** Il
complète `docs/TESTS_EMOTIONS.md`, qui portait sur les visages et les gestes.

## 1. Principes

- **Des droits clairs.** On utilise seulement deux sortes de scènes :
  - des scènes tournées par l'équipe, avec l'accord écrit des acteurs ;
  - des extraits de films dont le producteur a donné son accord.

  Jamais un film de tiers sans droits.
- **La référence avant la machine.** Les correcteur·rices écrivent ce qu'il faut décrire en
  regardant la **vidéo**, avant de voir les textes de l'IA.
- **À l'aveugle.** Les correcteur·rices ne savent pas quel réglage ni quel fournisseur a produit
  un texte.
- **Les mêmes entrées pour tous.** Les images et les consignes sont figées une fois, puis
  envoyées telles quelles à chaque configuration (voir
  [PROVIDER_COMPARISON_AUDIT.md](PROVIDER_COMPARISON_AUDIT.md)).
- **Tout publier.** On publie les échecs comme les réussites, avec le nombre de passages et les
  écarts entre essais.

## 2. Le jeu de scènes

Chaque scène dure 15 à 30 s, avec une ou deux répliques et une ou deux pauses à décrire. Il faut
au moins 4 scènes par catégorie, soit 44 scènes et environ 90 passages.

| Catégorie | Ce qu'on filme ou choisit | Ce que cela teste |
| --- | --- | --- |
| Scène simple | Une personne, un geste net, plan fixe | Le minimum attendu |
| Scène complexe | Plusieurs actions en même temps, décor chargé | Le choix de ce qui compte |
| Gestes rapides | Un geste de moins d'une demi-seconde pendant la pause | Le choix des images (`auto` contre `fixe`) |
| Plusieurs personnes | Trois personnages ou plus, qui se répondent par des gestes | La confusion entre personnes, les interactions |
| Mouvement de caméra | Panoramique, zoom, caméra à l'épaule pendant un petit geste | La compensation du mouvement |
| Faible lumière | Intérieur sombre, nuit | Les objets et les expressions mal vus |
| Scène ambiguë | Quelqu'un immobile, expression neutre | La confiance basse, les lectures multiples, l'absence de conclusion |
| Information sonore | Une sonnerie, une porte, une musique qui change, une voix hors champ | La redite de ce qu'on entend |
| Dialogue en français | Sous-titres en français | La langue de la piste, la redite du dialogue |
| Dialogue en arabe standard | Sous-titres en arabe | Le registre de la piste |
| Dialogue en derja | Sous-titres en derja, et une version sous-titrée en français | La dérive vers l'arabe standard ; la redite entre langues |

Il faut ajouter dans chaque catégorie une scène où la réalisation donne une note « à faire
remarquer » et une liste « à éviter ». C'est ce qui permet de tester le suivi de l'intention et le
risque de répéter une note de scène.

## 3. La référence

Pour chaque pause, deux personnes voyantes qui n'ont pas joué la scène regardent la vidéo et
écrivent, chacune de son côté :

1. **les événements visuels essentiels**, avec leur instant : ce qu'un spectateur aveugle doit
   savoir pour suivre ;
2. **les détails secondaires** ;
3. **ce qu'on entend déjà** : répliques, bruits, musique ;
4. **ce qui ne se voit pas** et ne doit pas être affirmé.

Elles comparent ensuite leurs listes. Elles notent leur accord avant discussion, puis s'accordent
sur une liste finale.

## 4. Les métriques

Une description est d'abord découpée en **affirmations** : « Amel pose la tasse et regarde la
porte » en contient deux. Chaque affirmation est jugée sur la vidéo :

- **juste** ;
- **fausse** : elle ne se voit pas, ou se voit autrement ;
- **invérifiable**.

| Métrique | Calcul | Qui la mesure |
| --- | --- | --- |
| Justesse visuelle | Affirmations justes ÷ affirmations jugées | Correcteur·rices voyant·es |
| Taux d'invention, par affirmation | Affirmations fausses ÷ affirmations jugées | Correcteur·rices |
| Taux d'invention, par passage | Passages avec au moins une affirmation fausse ÷ passages | Correcteur·rices |
| Couverture de l'essentiel | Événements essentiels décrits ÷ événements essentiels de la référence | Correcteur·rices |
| Concision | Mots ÷ budget (moyenne et maximum) ; événements essentiels couverts pour 10 mots | Automatique, puis correcteur·rices |
| Redite du dialogue ou du son | Passages qui redisent une réplique ou décrivent ce qu'on entend ÷ passages | Correcteur·rices ; le contrôle de Wasf est comparé à leur jugement |
| Qualité de la langue | Note de 1 à 5 sur la correction, le naturel et le registre, par deux locuteur·rices natif·ves de chaque langue ; accord exact et à un point près | Locuteur·rices natif·ves |
| Adéquation au temps | Voix qui débordent ÷ voix (version de travail) ; accélération moyenne ; part des voix accélérées | Automatique (rapport de transparence) |
| Taux de correction humaine | `modifies_par_un_humain` ÷ passages ; `part_moyenne_du_texte_modifiee` ; temps de relecture par passage, chronométré | Automatique, plus un chronomètre |

Trois mesures servent à juger les contrôles eux-mêmes :

| Métrique | Calcul | Ce qu'elle dit |
| --- | --- | --- |
| Rappel des alertes | Passages avec une affirmation fausse **et** une alerte ÷ passages avec une affirmation fausse | Combien d'erreurs les alertes attrapent |
| Précision des alertes | Passages signalés **et** faux ÷ passages signalés | Combien d'alertes sont utiles |
| Étalonnage de la confiance | Justesse par tranche de confiance (sous 0,5 ; 0,5 à 0,8 ; au-dessus) | Si la note que se donne le modèle veut dire quelque chose |

Pour la seconde lecture, deux mesures de plus :

- la part des « non » qui visaient une affirmation vraiment fausse ;
- la part des affirmations fausses qui ont reçu un « oui ».

## 5. Évaluation automatique et évaluation par les personnes concernées

| Type | Ce qu'elle mesure | Ce qu'elle ne peut pas dire |
| --- | --- | --- |
| Automatique | Longueur, durée des voix, redite mot à mot, alertes, validité du JSON, jetons, temps de réponse, coût, part du texte corrigée | Si le texte est vrai |
| Correcteur·rices voyant·es avec la vidéo | Justesse, inventions, couverture, redite du son, langue | Si le texte aide à suivre le film sans le voir |
| Spectateurs aveugles ou malvoyants | Compréhension de l'histoire, gêne pour écouter le film, préférence entre versions | Rien sur la justesse visuelle |

Les deux premières peuvent se faire en équipe. La troisième demande des participant·es, leur
accord éclairé et un questionnaire accessible. Elle n'a pas été faite, et elle n'est pas remplacée
par les deux autres. **Tant qu'elle n'existe pas, aucune affirmation d'utilité pour ces publics ne
peut être faite**, seulement des affirmations de justesse mesurée.

## 6. Le déroulé

1. Tourner ou réunir les scènes, avec les accords écrits.
2. Écrire pour chaque scène un fichier SRT et un fichier d'intention.
3. Figer les entrées : lancer `wasf preparer … --fournisseur mock` une fois par scène, et garder
   le dossier `images/` et les consignes.
4. Écrire les références (section 3).
5. Lancer chaque configuration trois fois.
6. Rassembler les textes, mélanger leur ordre, retirer les noms des configurations.
7. Faire juger à l'aveugle, puis calculer les métriques.
8. Publier le tableau complet, avec le nombre de passages, la date et les noms exacts des modèles.

## 7. Les comparaisons qui répondent à des questions précises

| Comparaison | Question | Métrique principale |
| --- | --- | --- |
| `--choix-images auto` contre `fixe` | Le choix des images rattrape-t-il les gestes brefs ? | Couverture, catégorie « gestes rapides » |
| `--images-contexte 2` contre `0` | Les images d'avant la pause aident-elles à décrire les réactions ? | Couverture, justesse |
| Sans seconde lecture, avec le même modèle, avec un autre fournisseur | La seconde lecture attrape-t-elle les inventions ? | Rappel des alertes, part des « non » justifiés |
| `emotions: nuancees` contre `signes` | Les émotions nommées sont-elles justes ? | Justesse des affirmations d'émotion |
| Gemini, Claude, OpenAI, Ollama | Lequel décrit le plus juste, dans chaque langue, à quel coût ? | Justesse, invention, qualité de langue, coût |

## 8. La taille de l'essai et ses limites

- Avec environ 90 passages par configuration, une proportion mesurée autour de 20 % a une marge
  d'environ ± 8 points (intervalle à 95 %, calcul : 1,96 × √(0,2 × 0,8 / 90)). C'est assez pour
  voir une grosse différence entre deux réglages, pas une petite.
- Des scènes tournées au téléphone par l'équipe ne ressemblent pas à un film professionnel :
  lumière, cadrage, jeu. Il faut le dire avec les résultats.
- Deux correcteur·rices par langue, c'est un minimum. Il faut publier leur accord.
- Les modèles changent souvent : un résultat vaut pour les noms exacts de modèles et la date de
  l'essai.

## 9. Le tableau à publier

À remplir avec les résultats réels. Aucune case ne doit être estimée.

| Configuration | Passages | Justesse | Invention (affirmations) | Invention (passages) | Couverture | Redite | Langue (1 à 5) | Débordements | Correction humaine | Rappel des alertes | Coût |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| … | | | | | | | | | | | |
