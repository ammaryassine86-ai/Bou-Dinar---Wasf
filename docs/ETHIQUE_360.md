# Wasf et l'éthique « 360 »

Le hackathon IA Éthique 360 juge une IA sous six angles, pas seulement sur sa performance.
Voici, pour chacun, la question posée, ce que Wasf fait déjà dans le code, et ce qui reste à faire.

## 1. Les créateurs : qui garde la main sur l'œuvre et les décisions ?

- **Dans le code** : la réalisation écrit le fichier d'intention (ce qu'il faut faire remarquer,
  ce qu'il ne faut jamais révéler) ; l'agent le suit. Wasf signale les passages où l'IA doute ;
  la réalisation les vérifie, valide un par un un échantillon tiré au hasard parmi les autres,
  valide le reste en un clic, signe et approuve la piste. Toute modification ultérieure, et tout
  changement de nom, retire cette approbation.
- **L'IA écrit, la réalisation décide.** Le texte de l'IA est conservé à part, sans être modifié,
  pour que chacun voie ce qui vient de l'humain. Un·e audiodescripteur·rice peut relire et signer
  à la place de la réalisation, si la production le souhaite.
- **Les émotions, au choix de la réalisation** : `emotions: nuancees` laisse l'IA nommer une
  émotion probable, avec ses signes visibles et une nuance ; `emotions: signes` l'interdit (voir
  « Visages et émotions » plus bas).
- **À faire** : faire écouter la piste à des spectateurs aveugles (avec IBSAR) et publier leur note.

## 2. Les droits : consentement, droits d'auteur, rémunération

- **Dans le code** : `wasf preparer` refuse de traiter un film sans `accord_producteur: true` et
  sans référence de l'accord. Les crédits et le rapport disent ce que l'IA a écrit et qui l'a
  validé.
- **Notre choix** : l'IA écrit la piste pour que beaucoup plus de films soient décrits, à un coût
  que les productions tunisiennes peuvent payer. Quand une production fait appel à un·e
  audiodescripteur·rice, il ou elle est crédité·e et payé·e.
- **Ce que Wasf ne fera jamais** : cloner la voix de quelqu'un sans son accord écrit.
- **À faire** : modèle de contrat type (producteur, réalisation, Wasf).

## 3. Les données : d'où viennent-elles, sont-elles utilisées légalement ?

- **Dans le code** : seules des images réduites (768 px) et le texte nécessaire sont envoyés au
  modèle ; jamais le film entier. Avec Ollama, rien ne quitte l'ordinateur.
- **Le film n'entraîne aucun modèle.** C'est écrit dans le rapport de transparence
  (`entrainement_sur_le_film: false`). Cette promesse suppose une offre qui n'exploite pas les
  contenus envoyés : l'offre gratuite de Gemini, par exemple, les utilise pour améliorer les
  produits de Google ([conditions](https://ai.google.dev/terms)). Pour un film réel : offre payante
  qui l'exclut, ou Ollama.
- **Aucun film ni aucune audiodescription d'autrui, aucun jeu de données collecté sur le web** :
  Wasf utilise des modèles déjà entraînés, sans les réentraîner. Le style vient d'exemples écrits
  par l'équipe, ou par un·e audiodescripteur·rice avec son accord écrit ; le clip de démonstration
  est fabriqué par FFmpeg.
- **Pas de reconnaissance faciale ni de modèle biométrique** : Wasf ne reconnaît personne. Il
  décrit des expressions et des gestes visibles, comme un·e audiodescripteur·rice, avec le modèle
  de langage visuel déjà utilisé, sans points du visage ni empreinte biométrique. Les noms des
  personnages viennent de la réalisation, et le modèle a pour consigne de ne jamais nommer un
  acteur d'après son visage.
- **Licences** : chaque voix et chaque jeu de données a sa licence ; beaucoup de voix Piper sont
  réservées à un usage non commercial.

## 4. Cultures et langues : quelles cultures le modèle met-il en avant, ou efface-t-il ?

- **Dans le code** : descriptions en derja tunisienne telle qu'on la parle (avec les mots
  français du quotidien, jamais en arabe standard), en arabe standard ou en français. Le lexique
  du film et les noms des personnages viennent de la réalisation : l'IA ne les devine pas.
- **Pourquoi le lexique** : un modèle a vu bien plus d'arabe standard que de derja. Laissé seul,
  il dérive vers l'arabe standard et efface la langue du film ; les mots fixés par la réalisation
  et les exemples écrits pour le film le ramènent à la derja.
- **Pourquoi c'est important** : les grandes plateformes décrivent surtout des titres dans de
  grandes langues ; les films tunisiens en derja restent de côté.
- **À faire** : un guide de style de l'audiodescription en derja, co-écrit avec des spectateurs
  aveugles et des audiodescripteur·rices tunisien·nes.

## 5. La transparence : le public sait-il ce qui a été généré par l'IA ?

- **Dans le code** : chaque film exporté commence par un carton et une annonce parlée :
  « Audiodescription écrite par intelligence artificielle, validée par … » (ou « assistée par
  intelligence artificielle, écrite et validée par … » quand un·e audiodescripteur·rice relit).
  La même mention figure dans le WebVTT, le SRT, les crédits et le rapport. Elle nomme les
  personnes qui ont réellement signé les passages, jamais un nom tapé après coup.
- **Une simulation est annoncée comme telle** : avec le fournisseur `mock`, qui ne regarde pas
  les images, l'annonce dit « Simulation : aucune image n'a été analysée ».
- **Le rapport chiffre la part humaine** : nombre de passages modifiés, part moyenne du texte
  changée par rapport au texte de l'IA, passages validés en un clic et échantillon relu un par un
  avant ce clic. Il nomme aussi le modèle que l'API dit avoir utilisé.
- **Une version de travail est toujours annoncée comme telle** (`--brouillon`).
- **Vu ou supposé** : l'éditeur montre ce que l'IA dit avoir vu, à part des émotions qu'elle
  suppose, avec leurs signes et sa certitude ; le rapport compte les passages qui nomment une
  émotion.

## 6. La planète : quel coût énergétique pour quel bénéfice ?

- **Dans le code** : images réduites, quatre images par pause (deux pendant, deux juste avant
  en 512 px, désactivables avec `--images-contexte 0`), révisions en texte seul (sans renvoyer
  les images), une seule génération par film, option de modèle local, aucun modèle ajouté pour
  les visages ou les gestes.
- **Mesure** : avec `pip install -e ".[energie]"`, CodeCarbon mesure l'énergie et le CO₂ des étapes
  « préparer » et « exporter » ; le résultat figure dans le rapport. La consommation des serveurs
  d'un fournisseur en ligne n'est pas incluse : nous le disons.
- **Le bénéfice** : une audiodescription produite une fois sert à tous les spectateurs, à chaque
  diffusion.

## Visages et émotions : décrire, pas diagnostiquer

Décrire ce que les personnages expriment sans parler aide à suivre un film. C'est aussi là
qu'une IA se trompe le plus facilement.

- **Les risques** : lire une émotion qui n'y est pas ; l'affirmer comme un fait ; coller une
  étiquette psychologique (« déprimée ») ; lire un geste avec des yeux d'ailleurs (un même geste
  ne dit pas la même chose partout : dans plusieurs pays de la Méditerranée et du monde arabe,
  relever la tête et les sourcils en claquant la langue veut dire « non », pas « surprise ») ;
  redire à chaque passage le même geste.
- **Dans le code** : le signe visible d'abord ; une émotion seulement avec ses signes et une
  nuance ; quand l'image ne suffit pas, plusieurs lectures possibles, aucune imposée ; le texte
  est comparé à ce que le modèle dit avoir vu, chaque phrase dit sur quelles observations elle
  repose ; si la réalisation le demande, les images sont revues pour confirmer chaque
  affirmation (seconde lecture), au besoin par un autre modèle ; un personnage qu'il ne
  reconnaît pas est décrit sans nom, jamais nommé au hasard ; certitude et étiquettes bloquées dans le texte de l'IA ; une émotion sans signe, une
  émotion dont le modèle se dit peu sûr, une émotion que le dialogue dit déjà ou un geste déjà
  décrit sont signalés ; la réalisation peut interdire tout mot d'émotion ; l'éditeur montre sur
  quels signes repose chaque supposition.
- **Ce qui reste** : un modèle peut mal lire un visage ; les règles jugent la façon d'écrire
  et la cohérence avec ce que le modèle déclare, pas la justesse de ce qui est vu ; on ne sait
  pas encore si ces descriptions aident les spectateurs (test prévu avec eux) ; la justesse n'a pas encore été mesurée sur de vraies scènes
  (protocole : [`TESTS_EMOTIONS.md`](TESTS_EMOTIONS.md)). Les émotions décrites sont celles que
  les acteurs jouent à l'écran : Wasf ne juge jamais l'état d'une personne réelle.
- **À faire** : un lexique des gestes tunisiens avec des spectateurs et des audiodescripteur·rices,
  pour que la réalisation puisse les donner à l'agent.

## En cohérence avec la Francophonie

| Valeur (deck) | Wasf |
| --- | --- |
| Diversité culturelle et linguistique | Derja telle qu'on la parle, arabe, français ; films tunisiens et francophones |
| Jeunesse et entrepreneuriat | Un service viable pour les producteurs et les festivals |
| Inclusion et égalité | Spectateurs aveugles et malvoyants, petites structures de production |
| Un numérique au service de l'humain | L'IA écrit, la réalisation décide et signe |

Repères cités par le deck : Convention de l'UNESCO sur la diversité des expressions culturelles
(2005) et Recommandation de l'UNESCO sur l'éthique de l'IA (2021).
