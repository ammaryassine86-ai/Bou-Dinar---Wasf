# Audit de l'agent Wasf : capacités et limites de l'IA

Ce rapport porte sur la vision (comment l'agent perçoit une scène) et sur la qualité des
descriptions. Il s'appuie sur le code de la branche `main` (commit `34c491a`). Aucun vrai modèle
n'a été appelé : tout ce qui touche à la justesse de ce qu'un modèle voit reste **non mesuré**, et
le rapport le dit à chaque fois.

## 1. Ce que le modèle reçoit, et ce qu'il ne reçoit jamais

Pour chaque passage, un seul appel avec images (`DescriberAgent.describe`) envoie trois choses.

| Élément | Contenu | Taille mesurée |
| --- | --- | --- |
| Consigne système | `SYSTEM_PROMPT` : 11 règles, en français, la même pour les trois langues | 2 449 caractères |
| Consigne du passage | `build_draft_prompt` : titre, intention, style, personnages, lexique, exemples, horaires, notes de la scène, contexte de la scène, histoire jusque-là, dialogue juste avant et juste après, dernier état des personnages, liste des images avec leur instant, règle des émotions, langue, nombre maximal de mots | 2 587 caractères pour un passage du film d'essai |
| Images | 4 JPEG par défaut : 2 dans les 3 s avant la pause (512 px de large), 2 pendant (768 px) | En moyenne 20 Ko (768 px) et 11 Ko (512 px) sur le film d'essai, une image synthétique. Un vrai film donnera d'autres tailles |

Le modèle ne reçoit jamais :

- **la vidéo** : seulement des images fixes ;
- **le son** : ni musique, ni bruits, ni voix. Le dialogue n'arrive que comme texte, et seulement
  s'il y a des sous-titres ;
- **ce qui se passe en dehors de la fenêtre** qui va de 3 s avant la pause à sa fin. Ce qui se
  passe pendant un long dialogue n'est jamais montré ;
- **les images des passages précédents.** Le passé n'arrive que sous forme de texte : dialogues,
  descriptions déjà écrites, dernier état des personnages.

## 2. Vision : comment l'agent perçoit une scène

### 2.1 Extraction

`media.extract_frame` lance FFmpeg une fois par image : recherche à l'instant voulu
(`-ss` avant `-i`), une seule image, mise à l'échelle à 768 ou 512 px de large au plus, JPEG en
qualité `-q:v 4`. Les instants sont gardés au millième de seconde dans le projet (`instants`).

### 2.2 Pourquoi quatre images

C'est un réglage, pas une limite du code :

- `--images`, 2 par défaut, fixe le nombre d'images prises pendant la pause ;
- `--images-contexte`, 2 par défaut, fixe le nombre d'images prises avant, dans les
  `--secondes-contexte` qui précèdent la pause (3 s par défaut).

Le code justifie les images d'avant par les réactions, qui ont souvent lieu pendant la réplique.
Il les justifie aussi par le coût : ces images sont plus petites, donc demandent moins de jetons
et moins d'énergie. Le nombre est le même pour toutes les pauses d'un film : une scène chargée ne
reçoit pas plus d'images qu'un plan fixe.

### 2.3 Images fixes ou choisies

- Avec `--choix-images auto` (par défaut), `pipeline._moments` décode chaque groupe de temps
  (les 3 s d'avant, puis la pause) en vignettes grises de 64 × 36 pixels (`media.thumbnails`).
  Il en garde 6, régulièrement espacées. `media.most_distinct` choisit parmi elles la paire la
  plus différente, puis l'image la plus éloignée de celles déjà choisies.
- La différence (`media.change_score`) se calcule ainsi :
  - un décalage de l'image, comme un panoramique, est d'abord compensé par corrélation de phase,
    jusqu'au tiers de l'image ;
  - on retire à chaque vignette sa luminosité moyenne, ce qui atténue un fondu ou un changement
    de lumière ;
  - seuls les 10 % de pixels qui changent le plus comptent.
- Sous un score de 6 (`STILL`), le plan est jugé fixe et les images restent régulièrement
  espacées.

Le choix porte donc sur **quels** moments montrer, pas sur **combien**. Et il ne se fait que
parmi 6 candidats, espacés de la durée du groupe divisée par 6 : environ 0,5 s pour les 3 s
d'avant, et jusqu'à 1,3 s pour une pause de 8 s. Un geste plus court que cet écart peut tomber
entre deux candidats. Le critère est le changement visuel, pas l'importance pour l'histoire.

### 2.4 Résolution et compression

768 px de large pendant la pause, 512 px avant. Les petits détails peuvent disparaître : un texte à
l'écran, un objet tenu dans la main, une expression dans un plan large. Le code ne détecte pas ces
cas et n'envoie jamais d'image plus grande.

### 2.5 Le temps

Chaque image est annoncée au modèle avec son instant et sa place : « juste avant la pause,
pendant le dialogue » ou « pendant la pause » (`prompts._frames_lines`). La règle 4 demande de
décrire ce qui change d'une image à l'autre. L'ordre est donc gardé, mais le mouvement entre deux
images reste à deviner : le modèle ne voit ni la vitesse ni la trajectoire.

### 2.6 Plusieurs images à la fois

Les images partent ensemble, dans l'ordre, dans un seul appel. Les quatre adaptateurs le font tous
(une liste de parties chez Gemini, de blocs chez Claude et OpenAI, de pièces jointes chez Ollama).
Le modèle peut comparer les images entre elles ; dans quelle mesure il le fait bien n'a pas été
mesuré.

### 2.7 Relations spatiales, objets, actions, gestes

Tout repose sur le modèle de langage visuel. Wasf n'utilise :

- ni détecteur d'objets,
- ni estimation de la pose,
- ni suivi des personnes ou des visages,
- ni mesure de la profondeur.

Les deux derniers manques sont des choix éthiques écrits dans `ETHIQUE_360.md`. Rien dans le code
ne vérifie une relation spatiale (gauche, droite, devant, derrière), ni le nom d'un objet. Les
vignettes de 64 × 36 servent seulement à choisir les instants.

### 2.8 Scènes ambiguës

La consigne demande de décrire les signes sans conclure et de donner toutes les lectures possibles
(règle 5). Elle demande aussi une confiance sous 0,5 quand l'image est ambiguë (règle 10). Deux
mécanismes suivent ces réponses :

- Le contrôle `emotion_ambigue` (`emotions.check_evidence`) signale un texte qui tranche entre
  plusieurs lectures alors qu'aucune n'est notée à 0,6 ou plus.
- Une confiance sous 0,5 signale le passage (`agent.review_flags`).

Les deux reposent sur ce que le modèle dit de lui-même.

### 2.9 Mouvements de caméra rapides

- Un panoramique est compensé dans le choix des images.
- Un décalage de plus d'un tiers de l'image compte comme un changement de plan.
- Le zoom n'est pas compensé.
- Une caméra rapide, une foule ou un zoom peuvent produire plus de changement qu'un petit geste,
  et prendre sa place dans le choix. Le README le reconnaît.
- Une image prise pendant un mouvement rapide peut être floue ; le code ne le détecte pas.

### 2.10 Transitions et événements brefs

- Un changement de plan pendant la pause attire le choix des images. C'est souvent utile, puisque
  le plan change, mais ces images peuvent manquer le geste d'après.
- Un événement de moins d'une demi-seconde peut tomber entre deux candidats.
- Ce qui se passe pendant le dialogue, plus de 3 s avant une pause, n'est jamais vu. C'est la
  limite la plus structurelle : les pauses viennent des sous-titres ou des silences, pas de
  l'image.

### 2.11 Ce qui est vu, ce qui est supposé

La réponse demandée sépare plusieurs champs :

- `observations` : quatre faits visibles au plus ;
- `changements` et `interactions` ;
- `emotions` : ce qui est supposé, avec ses indices et une certitude ;
- `appuis` : pour chaque phrase, les observations qui la fondent.

L'éditeur montre ces champs à part du texte. C'est utile à la relecture, mais **c'est le même
modèle qui écrit les observations et la description**. Une observation fausse fonde une phrase
fausse que les contrôles jugeront « appuyée ». Seule la seconde lecture, facultative, remet les
observations face aux images.

## 3. Les risques visuels, un par un

| Risque | Ce qui le réduit dans le code | Ce qui reste | Amélioration technique possible ? | Validation humaine nécessaire ? |
| --- | --- | --- | --- | --- |
| Geste inventé | Observations et appuis ; `signe_non_observe` ; seconde lecture facultative ; relecture | Un geste inventé et noté comme observé ne déclenche rien (vérifié à l'exécution) | Oui : seconde lecture par défaut, idéalement par un autre fournisseur, ou description indépendante comparée à la première | Oui, toujours |
| Mauvais objet | Lexique du film pour les noms des choses ; seconde lecture | Aucun contrôle sur le nom d'un objet | En partie : plus de résolution sur demande, questions ciblées au vérificateur | Oui |
| Mauvaise relation spatiale | Aucun | Rien ne vérifie gauche, droite, devant, derrière | Faiblement : questions ciblées au vérificateur ; à mesurer d'abord | Oui |
| Confusion entre personnes | Noms et descriptions fournis par la réalisation ; règle 7 (pas de nom sans description qui permette de reconnaître) | Un nom mal attribué passe dans la mémoire des personnages (`character_memory`) et dans les passages suivants | Limitée sans suivi des visages, exclu par choix | Oui |
| Action brève manquée | Choix des images là où ça change ; 2 images avant la pause | 6 candidats seulement ; rien pendant le dialogue | Oui : plus de candidats, détection des plans, images ajoutées quand le score de changement est élevé. Coût et énergie en plus | Oui, sur la vidéo |
| Expression mal lue | Mode `signes` ; règles sur la certitude et les étiquettes ; lectures multiples | Les contrôles jugent la façon d'écrire, pas la justesse de la lecture | Non sans classifieur d'émotions, exclu par choix | Oui |
| Continuité fausse | Histoire en texte ; dernier état des personnages ; contrôles de répétition | Les descriptions passées n'ont pas encore été relues : une erreur peut se propager au passage suivant | Oui : marquer dans la consigne que ces descriptions ne sont pas relues, ou réécrire après relecture | Oui |

Pour chaque ligne, la relecture humaine reste le seul contrôle de la vérité. Or l'éditeur ne
montre que les mêmes images fixes, sans la vidéo. Une réalisation qui connaît son film corrige de
mémoire. Un·e audiodescripteur·rice extérieur·e doit regarder le film à côté.

## 4. Qualité des descriptions

### 4.1 Ce que demandent les consignes

La consigne système (`prompts.SYSTEM_PROMPT`) pose les règles suivantes :

1. L'essentiel d'abord : qui, fait quoi, où.
2. Présent, troisième personne, ton neutre, jamais une liste.
3. Expressions, gestes et regards entre personnages, en priorité ce qui compte pour l'histoire.
4. Décrire ce qui change d'une image à l'autre.
5. Le signe visible d'abord, aucune certitude ni diagnostic sur une émotion.
6. Ne pas répéter le dialogue, ne pas anticiper.
7. Ne nommer un personnage que si sa description permet de le reconnaître, jamais un acteur.
8. Suivre l'intention de la réalisation.
9. Respecter le nombre de mots : sans rien d'important, une description vide.
10. Une confiance sous 0,5 si l'image est ambiguë.
11. Répondre en JSON.

Ce sont de bonnes règles d'audiodescription. Mais ce sont des demandes au modèle : la plupart ne
sont vérifiées par aucun code.

### 4.2 Critère par critère

| Critère | Ce qui le favorise | Ce que le code vérifie | Ce qui n'est pas vérifié |
| --- | --- | --- | --- |
| Ancré dans l'image | Règles 1, 4, 5 ; observations et appuis | Cohérence du texte avec les observations du modèle | La vérité des observations (sauf seconde lecture) |
| Juste | Images choisies là où ça change | Rien | Tout. Non mesuré |
| Concis | Budget de mots calculé sur la pause | Nombre de mots ; 6 gestes ou plus signalés (`surcharge`) | La densité d'information |
| Objectif | Règles 2 et 5 ; mode `signes` | Certitude, étiquettes, 3 mots de jugement en français (« magnifique », « beau », « belle ») | Tout autre jugement ou commentaire |
| Utile aux spectateurs aveugles ou malvoyants | Règles 1, 3, 8 | Rien | Tout. Aucune évaluation par les personnes concernées |
| Adapté à la pause | Budget de mots ; débit par langue | Mots avant l'export ; vraie durée de la voix à l'export, qui refuse un débordement | Le débit réel d'un·e lecteur·rice tant que la piste n'est pas exportée |
| Sans détail inutile | Règle 9 (description vide permise) | `surcharge` | Le choix de ce qui compte |
| Cohérent avec la scène | Histoire, mémoire des personnages | Répétition du passage précédent ; geste déjà décrit | La cohérence de fond |
| Naturel | Exemples écrits pour le film ; consigne de langue | Écriture, anglais, arabe standard dans une piste en derja | La grammaire, le naturel, le registre |

### 4.3 Comment l'agent choisit ce qui compte

Le choix vient de trois sources :

- la consigne générale : actions, personnages, lieux, textes à l'écran, gestes qui comptent pour
  l'histoire ;
- les notes de la réalisation : « à faire remarquer », « à ne jamais mentionner », contexte de la
  scène ;
- le jugement du modèle.

Aucun code ne classe les éléments par importance. Une note de scène est donnée à **chaque**
passage de la scène (`Intent.notes_for`), avec la mention « À faire remarquer dans ce passage ».
Dans l'exemple du dépôt, la scène dure 40 s et la note « Amel regarde la porte du café, sa tasse à
la main » serait demandée à toutes ses pauses. Cela pousse le modèle à la redire, même quand elle
n'est plus visible. Les contrôles de répétition ne la rattrapent que si deux descriptions qui se
suivent se ressemblent à 80 % au moins (`textnorm.too_similar`), ou partagent au moins deux gestes
qui font l'essentiel des gestes du nouveau texte (`geste_repete`).

### 4.4 Audiodescription, ou résumé de l'image ?

La structure est celle d'une audiodescription :

- des passages placés dans les pauses ;
- un budget de mots ;
- le présent ;
- l'interdiction de répéter le dialogue ;
- l'intention de la réalisation ;
- des secrets à garder.

Mais l'agent ne sait de l'histoire que ce que disent les sous-titres et ses propres descriptions,
et il ne voit que quatre images par pause. Il n'a aucun moyen de savoir qu'un détail vu à la
minute 3 sera important à la minute 40. Sans notes de la réalisation, le risque est un bon résumé
de l'image du moment plutôt qu'une description au service du récit. Cela n'a pas été mesuré.

### 4.5 Répéter ce que le spectateur entend déjà

- **Le dialogue** : le contrôle `repetition_dialogue` bloque un texte dont 60 % des mots de plus
  de deux lettres se trouvent dans la réplique d'avant ou d'après (à partir de 4 mots). La
  comparaison se fait mot à mot. Une description en derja ne sera donc jamais rapprochée d'un
  sous-titre en français : c'est vérifié à l'exécution, et le README le dit déjà.
- **Le son** : le modèle n'entend rien. Une sonnerie, une porte qui claque, une musique qui
  change, ou une voix hors champ sans sous-titre peuvent être décrites alors que le spectateur les
  entend. Aucun contrôle ne le voit : « Le téléphone sonne. Elle décroche. » passe sans alerte
  (vérifié à l'exécution).

### 4.6 Ce que contient une consigne, sur un exemple

Voici la consigne qu'écrit `build_draft_prompt` pour un passage fictif, avec le fichier
d'intention d'exemple du dépôt (`examples/intention.exemple.yaml`). Les répliques et les instants
ont été inventés pour l'audit, et la piste mise en français.

```text
Passage : de 0:12,0 à 0:17,0 (pause de 4.4 s dans les dialogues).
À faire remarquer dans ce passage : Amel regarde la porte du café, sa tasse à la main.
À ne jamais mentionner : le visiteur, lettre
Contexte de la scène : Ouverture : on ne doit pas savoir qui va entrer.
Dialogue juste avant : « Tu attends quelqu'un ? »
Dialogue juste après : « Non, personne. »
Dernier état connu des personnages (ne le redis pas s'il n'a pas changé ; décris ce qui change) :
- Amel (0:04,2) : tient une tasse ; regarde la porte
Images jointes, dans l'ordre chronologique : 1 · 0:09,4 (juste avant la pause, pendant le
dialogue) ; 2 · 0:10,9 (juste avant la pause, pendant le dialogue) ; 3 · 0:13,6 (pendant la
pause) ; 4 · 0:15,3 (pendant la pause).
Émotions : la réalisation ne veut aucun mot d'émotion. [...]
Nombre maximal de mots : 9.
```

Trois remarques sur cet exemple :

- La note de scène demande au modèle de « faire remarquer » un geste qu'il ne voit peut-être pas
  sur ces quatre images. Le contrôle des appuis ne l'arrêtera pas si le modèle l'inscrit aussi
  dans ses observations.
- Le lexique du film (`chéchia → الشاشية`, etc.) est donné « à reprendre tel quel » quelle que soit
  la langue de la piste. Si la même intention sert à faire une piste en français, des mots en
  caractères arabes peuvent s'y glisser.
- La réécriture (`build_revision_prompt`) reçoit le brouillon, les problèmes et les observations,
  mais pas les images. Elle peut raccourcir sans rien inventer, ou inventer : seuls les contrôles
  d'appuis relisent le résultat.

## 5. En résumé

- **Ce que l'IA fait réellement** : elle lit quatre images fixes et une consigne détaillée, rend
  une description structurée et dit elle-même ce qu'elle a vu, ce qu'elle suppose et à quel point
  elle est sûre.
- **Ce que le code ajoute** : le choix des instants, le budget de mots, le contexte en texte, des
  contrôles de forme et de cohérence, et la réécriture.
- **Ce que personne ne sait encore** : si ce qu'elle voit est juste, et si ce qu'elle écrit aide
  les spectateurs.

Le protocole pour le mesurer est dans [BENCHMARK_PROTOCOL.md](BENCHMARK_PROTOCOL.md).
