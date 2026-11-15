# Audit de l'agent Wasf : français, arabe standard et derja

Ce rapport examine chaque langue à part : consignes, contraintes, contrôles, voix. Il ne juge pas
la qualité linguistique des descriptions. Pour la juger, il faudrait des descriptions écrites par
de vrais modèles et relues par des locuteur·rices natif·ves, et le dépôt n'en contient aucune.
**Aucune affirmation de justesse linguistique ne peut donc être faite à ce stade.**

Les comportements marqués « vérifié à l'exécution » ont été reproduits avec le code actuel, sans
le modifier.

## 1. Ce qui est commun aux trois langues

- **La consigne système est en français** (`prompts.SYSTEM_PROMPT`), quelle que soit la langue de
  la piste. Seule la consigne de langue (`LANG_SPECS`) change, à la fin de la consigne du passage.
- **Le choix de la langue** se fait dans cet ordre :
  1. l'option `--langue` ;
  2. la `langue` du fichier d'intention ;
  3. la langue des sous-titres (`textnorm.dialogue_language`) ;
  4. le français par défaut.

  `dialogue_language` donne le français dès que les lettres latines dominent. Puis, en écriture
  arabe, il compte des mots repères d'arabe standard et de derja.
- **Le budget de mots** se compte en mots séparés par des espaces, au débit de 2,5 mots par
  seconde en français, 2,0 en arabe et 2,2 en derja (`tts.WORDS_PER_SECOND`). Ces valeurs n'ont
  pas de source citée dans le dépôt. La réalisation peut les changer (`mots_par_seconde`). En
  arabe, les prépositions et pronoms collés au mot font qu'un « mot » porte plus de sens qu'en
  français. Personne n'a mesuré si les débits choisis compensent cette différence.
- **La liste « à éviter »** est reconnue malgré l'article, le pluriel, le féminin, les accents et
  les variantes d'écriture arabe (`textnorm.mentions`). Mais en arabe, une deuxième règle cherche
  aussi les lettres du mot à l'intérieur des autres mots. Un mot court à éviter peut donc bloquer
  un passage qui n'en parle pas :
  - avec « دار » (maison) à éviter, le texte « المدارس مغلقة » (les écoles sont fermées) est
    bloqué, ce qui a été vérifié à l'exécution ;
  - le texte « يدور حول الطاولة » est bloqué pour « دور ».
- **Le lexique du film** n'a pas de langue. Il est donné « à reprendre tel quel » à chaque piste.
  Une même intention utilisée pour une piste en derja et une en français fera entrer des mots en
  caractères arabes dans le texte français.
- **La répétition du dialogue** se compare mot à mot, donc seulement dans la même langue.

## 2. Français

| Aspect | Ce que fait le code |
| --- | --- |
| Consigne de langue | « Écris en français, au présent, en phrases courtes et simples. » (61 caractères) |
| Écriture | Bloque un texte en caractères arabes ; bloque un texte qui semble en anglais : au moins deux mots d'une liste de 18 mots anglais courants, plus nombreux que ceux d'une liste de 22 mots français |
| Émotions et gestes | Les listes les plus complètes : 115 mots d'émotion, 126 signes visibles, 15 nuances, 11 mots de certitude, 25 étiquettes psychologiques, 14 groupes de gestes synonymes |
| Voix | espeak-ng (`fr`), Azure `fr-FR-DeniseNeural` (voix de France), Piper, ou voix humaine |

**Limites** :
- Rien ne vérifie la grammaire, les accords ni le naturel.
- Les mots de jugement se limitent à trois : « magnifique », « beau », « belle ».
- Un film tunisien sous-titré en français reçoit une piste en français, sauf si la réalisation
  choisit une autre langue. Le code l'annonce dans le journal.

**À faire relire par des personnes** : le style d'audiodescription, la longueur des phrases à
l'oreille, le vocabulaire des gestes.

## 3. Arabe standard

| Aspect | Ce que fait le code |
| --- | --- |
| Consigne de langue | En arabe : arabe standard simplifié, au présent, phrases courtes et claires (64 caractères) |
| Écriture | Bloque un texte où les lettres arabes sont moins de la moitié |
| Registre | **Aucun contrôle** : une piste en arabe standard qui glisse vers le dialecte n'est pas signalée. Le contrôle inverse n'existe que pour la derja |
| Émotions et gestes | Listes plus courtes qu'en français : 37 émotions, 68 signes, 12 nuances, 8 mots de certitude, 7 étiquettes, 6 groupes de gestes. Un mot absent ne bloque jamais : il laisse passer sans alerte |
| Voix | espeak-ng (`ar`) ; Azure prend par défaut `ar-TN-ReemNeural`, une voix tunisienne, même pour l'arabe standard |

**Limites** :
- Les voyelles brèves ne sont pas écrites, et rien ne les demande. Un moteur de voix doit les
  deviner. Sa prononciation n'a pas été mesurée.
- Une voix tunisienne pour de l'arabe standard est un choix à faire écouter à des personnes
  concernées.

**À faire relire par des personnes** : la correction de la langue, le niveau de langue (simplifié
ou soutenu), les listes de `wasf/emotions.py`.

## 4. Derja tunisienne

### 4.1 Ce que fait le code

- **Une consigne détaillée**, en français, de 791 caractères. Elle demande :
  - d'écrire la derja telle qu'on la parle, en caractères arabes, en phrases courtes ;
  - jamais d'arabe standard ;
  - de reprendre le sens des notes de la réalisation, jamais leurs mots, et d'écrire aussi les
    observations en derja ;
  - de garder les mots français du quotidien, écrits comme en derja (« البورتابل », « أورانج »).

  Elle donne aussi 13 remplacements précis (« يغزر » et non « ينظر », « توا » et non « الآن »…)
  et une phrase dans le bon ton.
- **Les exemples et le lexique de la réalisation**, ajoutés à la consigne, qui donnent le ton du
  film.
- **Un contrôle « arabe standard »** (`textnorm.looks_like_standard_arabic`). Il signale (sans
  bloquer) un texte qui a au moins deux mots d'une liste de 25 mots d'arabe standard, et aucun mot
  d'une liste de 25 mots de derja.
- **Des listes d'émotions et de gestes en derja** : 44 émotions, 81 signes, 22 nuances, 11 mots
  de certitude, 10 étiquettes. Une partie vient des notes de l'équipe du 13/11/2026 : 20
  émotions, 48 signes, 9 nuances, 4 certitudes et 4 étiquettes. Le code et
  `docs/DERJA_A_RELIRE.md` disent qu'elles n'ont pas encore été vérifiées par un·e locuteur·rice
  natif·ve.

### 4.2 La derja est-elle vraiment prise en charge ?

Non, pas au sens d'un modèle qui connaît la derja. Wasf demande à un modèle multilingue d'écrire en
derja. Il le guide avec une consigne, des remplacements, le lexique et les exemples du film, puis
surveille le résultat avec des listes de mots. Il n'y a :

- ni modèle propre à la derja,
- ni données en derja,
- ni évaluation en derja.

La qualité dépend donc du modèle choisi et du soin mis dans les exemples. Elle n'a été mesurée
pour aucun modèle.

### 4.3 Ce que les contrôles laissent passer ou signalent à tort

Tous ces cas ont été vérifiés à l'exécution.

- **Un seul mot repère suffit à faire taire l'alerte.** « أمل تجلس أمام الباب وتنظر إلى الشارع »
  est signalé comme arabe standard. Avec « برشا » ajouté à la fin, il ne l'est plus, alors que le
  reste de la phrase est inchangé.
- **L'orthographe de la derja n'est pas fixée.** Écrit « برشة » au lieu de « برشا », le même mot
  n'est plus reconnu comme repère de derja.
- **Une phrase en derja sans mot repère** ne déclenche rien. Ce comportement est juste, mais le
  contrôle ne dit rien non plus de sa qualité.
- **L'arabizi** (la derja écrite en lettres latines, « barcha », « 3aychek ») n'est pas reconnu.
  Des sous-titres en arabizi font choisir le français comme langue de la piste. Un texte en derja
  où les lettres latines dominent est bloqué.
- **Les mots français écrits en lettres latines** dans une piste en derja bloquent le passage dès
  que les lettres latines font la moitié du texte. C'est le cas de « أمل تحط le portable على la
  table ». La règle suit la consigne (écrire ces mots en lettres arabes, pour la voix). Mais elle
  bloque aussi le texte d'une personne qui corrige, puisque c'est une erreur et non une alerte.

### 4.4 La voix

- **espeak-ng** lit la derja avec sa voix arabe (`ar`), faite pour l'arabe standard.
- **Azure** a deux voix tunisiennes (`ar-TN-ReemNeural`, `ar-TN-HediNeural`) ; leur rendu sur un
  texte en derja n'a pas été mesuré.
- Le README recommande la voix humaine pour la derja. Le contrôle des voix mesure le son, pas la
  prononciation.

## 5. Ce qui demande des locuteur·rices natif·ves

| Question | Langue | Pourquoi aucun code ne peut y répondre |
| --- | --- | --- |
| Les descriptions sont-elles correctes et naturelles ? | Les trois | Il faut juger le sens, la grammaire et le ton |
| La derja reste-t-elle de la derja, et de quelle région ? | Derja | Pas d'orthographe fixée, des variantes selon les régions |
| Les mots des listes `DERJA_A_RELIRE` sont-ils justes ? | Derja | Le code les marque « à relire » |
| Comment écrire les mots français du quotidien en lettres arabes ? | Derja | Plusieurs graphies coexistent |
| Le débit de 2,0 ou 2,2 mots par seconde convient-il ? | Arabe, derja | À mesurer sur des lectures réelles |
| La voix tunisienne d'Azure convient-elle à l'arabe standard, et à la derja ? | Arabe, derja | À écouter |
| Les gestes sont-ils lus avec le sens qu'ils ont en Tunisie ? | Les trois | `ETHIQUE_360.md` cite le « non » fait en relevant la tête ; aucun lexique des gestes n'existe dans le code |

## 6. En résumé

- **Français** : le mieux outillé, avec les listes les plus longues, mais rien ne juge la qualité
  de la langue.
- **Arabe standard** : seule l'écriture est contrôlée, pas le registre.
- **Derja** : le plus de soin dans la consigne, mais pas plus que des consignes et des listes de
  mots. Une partie de ces listes attend une relecture native.

Dans les trois cas, les contrôles signalent ; la réalisation décide. Une mesure de la qualité
linguistique demande le protocole de [BENCHMARK_PROTOCOL.md](BENCHMARK_PROTOCOL.md), avec des
correcteur·rices natif·ves.
