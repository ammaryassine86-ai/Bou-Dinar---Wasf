# Tester la lecture des visages et des gestes sur de vraies scènes

Les tests automatiques (`tests/test_emotion_scenarios.py`) rejouent huit scènes avec des
**réponses de modèle simulées**. Ils vérifient ce que Wasf fait d'une réponse (signalements,
blocages, réécriture), pas ce qu'un modèle voit. Ce protocole mesure ce que voit un vrai modèle,
sur des scènes jouées par l'équipe : pas de droits de tiers, et des images que l'équipe connaît.

## 1. Filmer les huit scènes

Deux ou trois membres de l'équipe, un téléphone posé, 15 à 30 secondes par scène. Une réplique
au début et une à la fin : la pause entre les deux est le passage décrit.

| Scène | Ce que les acteurs jouent |
| --- | --- |
| 1. Conversation | L'un sourit en parlant, l'autre l'écoute en fronçant les sourcils |
| 2. Pleurs | Un personnage pleure et s'essuie les yeux |
| 3. Colère | Sourcils froncés, poings serrés, un pas vers l'autre |
| 4. Sourire et malaise | Un sourire, des mains qui tremblent autour d'une tasse |
| 5. Montrer, saluer | L'un montre une porte du doigt, l'autre fait signe de la main |
| 6. Dispute sans mots | L'un se penche et gesticule, l'autre recule et croise les bras |
| 7. De la joie à la tristesse | Un rire pendant la dernière réplique, puis le visage qui tombe dans la pause |
| 8. Scène ambiguë | Quelqu'un regarde par la fenêtre, immobile |

Pour chaque scène : un fichier SRT avec les deux répliques, et un fichier d'intention avec les
prénoms et une description des personnages, `emotions: nuancees`, et
`droits: accord_producteur: true` avec une référence (« Scènes jouées par l'équipe ; accord écrit
des acteurs du JJ/MM »). Les acteurs donnent leur accord écrit pour le test et la démonstration.

## 2. Lancer Wasf avec un vrai modèle

```bash
export GEMINI_API_KEY="…"
wasf preparer scene3.mp4 --intention scene3.yaml --sous-titres scene3.srt \
     --fournisseur gemini --sortie essais/scene3
# la même scène sans les images d'avant la pause, pour comparer :
wasf preparer scene3.mp4 --intention scene3.yaml --sous-titres scene3.srt \
     --fournisseur gemini --images-contexte 0 --sortie essais/scene3_sans_contexte
```

Pour mesurer les deux réglages ajoutés, refaire aussi la scène 7 avec `--choix-images fixe` (le
changement est-il moins bien vu ?) et une scène avec `--seconde-lecture`, puis avec
`--seconde-lecture openai` si vous avez une deuxième clé (combien d'affirmations rejetées, et à
raison ? un autre modèle en rattrape-t-il davantage ?). Filmer aussi une scène avec un
panoramique lent pendant un petit geste, pour voir si le geste est gardé.

`projet.json` garde pour chaque passage ce que le modèle dit avoir vu (`observations_ia`), ce
qu'il suppose (`emotions_ia`), son texte (`brouillon_ia`) et les vérifications ; `wasf relire`
les montre dans l'éditeur.

## 3. Noter chaque passage

Une ligne par passage, remplie par deux personnes qui n'ont pas joué la scène :

| Scène | Ce qui est joué | Observations de l'IA | Description | Signes justes (0 à 2) | Invention (quoi) | Émotion : juste et nuancée / trop sûre / fausse / absente | Utile pour un spectateur aveugle (0 à 2) |
| --- | --- | --- | --- | --- | --- | --- | --- |

Quand c'est possible, la dernière colonne est remplie par une personne aveugle ou malvoyante qui
écoute la description sans voir l'image (avec IBSAR).

## 4. Ce qu'on attend

- Scènes 1 à 7 : les signes principaux sont décrits (sourire, larmes, poings, doigt pointé,
  bras croisés) ; dans la scène 7, le changement est décrit, et l'on compare avec la version
  sans images d'avant la pause.
- Scène 4 : les deux signes, sans conclure.
- Scène 8 : des signes seulement, une confiance sous 0,5, aucune émotion affirmée.
- Aucun texte final avec une certitude ou une étiquette psychologique.

## 5. Rendre compte

Reporter le tableau tel quel, échecs compris, dans l'évaluation et sur la slide de démonstration :
« huit scènes jouées par l'équipe, deux correcteurs, modèle X ». Un résultat mesuré sur huit
scènes est un premier indice, pas une preuve.

## 6. Est-ce que ça aide ? Test avec des spectateurs aveugles et malvoyants

Les étapes 1 à 5 mesurent si le modèle voit juste. Celle-ci mesure si les descriptions des
visages et des gestes aident vraiment. Elle ne peut se faire qu'avec des personnes concernées
(avec IBSAR, par exemple), et prend environ une heure par personne.

**Trois versions du même extrait** (3 à 5 minutes, un film dont on a l'accord, ou les scènes
de l'équipe montées ensemble) :

| Version | Comment l'obtenir |
| --- | --- |
| A. Sans audiodescription | La bande son du film seule |
| B. Signes seulement | `emotions: signes` dans le fichier d'intention, `wasf preparer`, relecture, `wasf exporter` |
| C. Signes et émotions nuancées | `emotions: nuancees`, même chemin, dans un autre dossier de sortie |

Chaque piste est relue et validée par la réalisation avant le test, comme pour une diffusion.
Chaque personne écoute deux versions sur trois, dans un ordre qui change d'une personne à
l'autre (A puis C, C puis B, B puis A…), pour que l'ordre ne fausse pas le résultat.

**Après chaque version** :

1. **Compréhension** : cinq questions préparées à l'avance sur ce que vivent les personnages
   (« Que fait Leïla quand Karim lui tend la main ? », « Comment réagit-elle à la nouvelle ? »).
   Réponse libre, notée juste, partielle ou fausse par quelqu'un qui ne sait pas quelle version a
   été écoutée.
2. **Ressenti** : de 1 à 5, « j'ai compris ce que ressentaient les personnages », « la
   description m'a gêné·e pour entendre le film », « la voix en disait trop ».
3. **À la fin** : quelle version la personne préfère, et pourquoi ; un moment où la description
   l'a aidée ; un moment où elle l'a gênée ou a interprété à sa place.

**Accord et respect** : accord écrit (lu à voix haute ou en braille, selon la préférence) ;
la personne peut arrêter à tout moment ; pas de nom dans les résultats ; pas d'enregistrement
sans accord. Le questionnaire est donné à l'oral ou dans un format lisible par un lecteur
d'écran.

**Ce qu'on rapporte** : le nombre de personnes, les scores par version, les citations (avec
accord), et ce qui n'a pas marché. Avec moins de dix personnes, c'est un retour qualitatif, pas
une preuve statistique : on le dit comme ça. Si la version C n'aide pas mieux que la B, ou gêne,
la réalisation choisit `signes` par défaut.
