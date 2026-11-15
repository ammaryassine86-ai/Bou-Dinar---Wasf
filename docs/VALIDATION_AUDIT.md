# Audit de l'agent Wasf : contrôles automatiques et contrôle qualité

Ce rapport passe en revue chaque mécanisme de contrôle, puis les réécritures, la seconde lecture et
l'échantillon. Pour chaque contrôle, il répond à six questions :

1. Que mesure-t-il ?
2. Est-ce une règle fixe ou un jugement de l'IA ?
3. Quelles erreurs détecte-t-il ?
4. Lesquelles laisse-t-il passer ?
5. Quelles fausses alertes peut-il donner ?
6. Peut-il donner une fausse impression de fiabilité ?

Les exemples marqués « exécuté » ont été reproduits avec le code actuel, sans le modifier et sans
appeler aucun service d'IA.

## 1. Le principe

- Un contrôle rend un niveau.
  - `erreur` **bloque** : l'agent réécrit, et la personne qui relit ne peut pas valider tant qu'il
    reste une erreur.
  - `attention` **signale** : le passage sort de la validation en un clic, mais il peut être
    validé.
- Presque tous les contrôles sont des règles fixes, écrites à la main : listes de mots, seuils,
  comparaisons de textes. **Un seul jugement vient d'une IA** : la seconde lecture, facultative.
  Les contrôles dits « de preuve » comparent le texte du modèle à ce que **le même modèle** dit
  avoir vu. Ils mesurent sa cohérence avec lui-même, pas la vérité de l'image.
- Le texte de l'IA et le texte d'une personne ne sont pas traités pareil.
  - Une certitude ou une étiquette psychologique bloque le texte de l'IA, mais seulement signale
    celui d'une personne.
  - Les contrôles de preuve ne s'appliquent qu'au texte de l'IA (`ai_text` dans
    `agent.run_checks`).

## 2. Les contrôles du texte (`agent.run_checks`)

| Code | Ce qui est mesuré | Niveau | Détecte | Laisse passer, ou alerte à tort |
| --- | --- | --- | --- | --- |
| `vide` | Texte vide | info | Un passage sans description | Rien |
| `refus` | 24 formules de refus en français, anglais, arabe et derja (`textnorm.looks_like_refusal`) | erreur, sans réécriture | « Je ne peux pas », « I'm sorry », « لا أستطيع »… | Laisse passer un refus dit autrement : « Je préfère ne pas décrire cette image. » (exécuté). Alerte à tort sur un texte à l'écran : « Un panneau indique : je suis désolé, fermé. » est bloqué (exécuté) |
| `ecriture` | Part des lettres arabes et latines ; quelques mots anglais en piste française | erreur | Une piste dans la mauvaise écriture ; une réponse en anglais | Une langue fausse dans la bonne écriture (arabe standard dans une piste en arabe dialectal et inversement, voir [MULTILINGUAL_AUDIT.md](MULTILINGUAL_AUDIT.md)) |
| `trop_long` | Nombre de mots face au budget de la pause | erreur | Un texte trop long pour sa pause | La vraie durée de la voix, mesurée seulement à l'export |
| `a_eviter` | Les mots que la réalisation interdit, malgré l'article, le pluriel, le féminin ou les accents (`textnorm.mentions`) | erreur | Les variantes d'écriture d'un secret | Les synonymes et les périphrases. Alerte à tort en arabe sur un mot court contenu dans un autre (« دار » dans « المدارس », exécuté) |
| `repetition_dialogue` | Part des mots de plus de deux lettres que l'on retrouve dans la réplique d'avant ou d'après (60 % ou plus, à partir de 4 mots) | erreur | Une description qui recopie la réplique | Une reprise dans une autre langue ou en d'autres mots ; tout ce que l'on entend sans sous-titre. Alerte à tort sur la description d'une action que la réplique demande : « Amel ouvre lentement la lettre de sa mère. » après « Ouvre la lettre de ta mère. » est bloqué (exécuté) |
| `arabe_standard` | Mots repères d'arabe standard sans aucun mot repère de derja | attention, derja seulement | Une piste en derja qui dérive | Une phrase en arabe standard qui contient un seul mot repère de derja ; une orthographe de derja non listée (exécuté) |
| `repetition` | Ressemblance des textes avec le passage précédent, 80 % ou plus (`textnorm.too_similar`) | attention | Le même texte deux fois de suite | La même idée en d'autres mots ; une répétition à deux passages d'écart |

## 3. Les contrôles des émotions (`emotions.check_emotions`)

| Code | Ce qui est mesuré | Niveau | Détecte | Laisse passer |
| --- | --- | --- | --- | --- |
| `diagnostic` | Étiquettes psychologiques ou médicales d'une liste (25 en français, 7 en arabe, 10 en derja) | erreur pour l'IA, attention pour une personne | « déprimée », « hystérique »… | Toute étiquette absente de la liste |
| `certitude` | Mot de certitude dans une phrase qui nomme une émotion, sauf après une négation | erreur pour l'IA, attention pour une personne | « clairement furieuse » | Une émotion dite comme un fait, sans mot de certitude : « Il baisse les yeux, triste. » passe sans alerte quand le modèle se dit sûr à 0,9 (exécuté) |
| `interpretation` | Émotion nommée sans signe visible dans la même phrase ; en mode `signes`, tout mot d'émotion ou de jugement de la liste | attention | « Il est triste. » | Les mots absents des listes |
| `emotion_incertaine` | Émotion nommée sans nuance alors que le modèle s'en dit sûr à moins de 0,5 | attention | Une affirmation que le modèle lui-même ne tient pas | La même affirmation dès que le modèle se note 0,5 ou plus |
| `emotion_dialogue` | Émotion déjà nommée dans la réplique | attention | Une redite | Une redite en d'autres mots ou dans une autre langue |
| `geste_repete` | Gestes déjà décrits au passage précédent | attention | La même posture redite | Une redite plus ancienne |

**Ce que les crédits en disaient.** `export.write_credits` écrivait, en mode `nuancees` :
« Émotions : nommées seulement avec leurs signes visibles, jamais avec certitude ». Or :

- une émotion sans signe n'est qu'une alerte, qu'on peut valider ;
- une certitude écrite par une personne n'est aussi qu'une alerte : « Elle est clairement
  furieuse. » se valide une fois modifiée à la main (exécuté).

La phrase décrivait la consigne, pas ce que le code garantit. **Corrigé après l'audit** : les
crédits disent maintenant que l'IA « avait pour consigne » de nommer une émotion seulement avec
ses signes visibles, sans certitude. Ils précisent aussi qu'un mot de certitude bloque son texte
et qu'une émotion sans signe visible est signalée à la relecture. En mode `signes`, ils disent
combien de passages nomment quand même une émotion.

## 4. Les contrôles de preuve (`emotions.check_evidence`)

Ils comparent le texte de l'IA à ce que l'IA dit avoir vu. Aucun ne bloque.

| Code | Ce qui est comparé | Ce que cela attrape | Ce qui passe |
| --- | --- | --- | --- |
| `emotion_ambigue` | Plusieurs lectures pour une personne, aucune notée 0,6 ou plus, et un texte qui tranche | Une conclusion que le modèle lui-même ne soutient pas | Tout, si le modèle ne donne qu'une lecture |
| `sans_preuve` | Émotion nommée sans indices | Une supposition sans appui déclaré | Des indices inventés |
| `indice_non_observe` | Indices d'une émotion absents des observations (mots en commun) | Une incohérence interne | Un indice reformulé qui partage un mot avec une observation |
| `signe_non_observe` | Deux gestes ou plus dans le texte, aucun dans les observations, synonymes compris | Un geste qui n'apparaît que dans le texte | **Un geste inventé et aussi inscrit dans les observations** : aucune alerte, validation en un clic possible (exécuté) |
| `reponse_incomplete` | Gestes ou émotions dans le texte, aucune observation | Une réponse incomplète | Rien de plus |
| `phrase_sans_appui` | Une phrase qui ne s'appuie, selon le modèle, sur aucune observation | Un aveu du modèle | Des appuis donnés au hasard |
| `signe_non_confirme` | Une phrase dont tous les appuis ont été rejetés à la seconde lecture | Une observation que le vérificateur dit ne pas voir | Voir la section 6 |
| `surcharge` | 6 gestes ou plus | Un passage trop chargé | La pertinence des gestes gardés |

Ces contrôles sont utiles parce qu'ils rendent visibles les contradictions du modèle. Mais un
modèle qui se trompe de façon cohérente les passe tous.

## 5. Les réécritures

- **Quand** : seulement sur une `erreur`, jamais sur une `attention`. Pas après un refus, car une
  réécriture sans les images inventerait la scène.
- **Combien** : `--revisions`, 2 par défaut. Après la dernière, les contrôles sont refaits une
  fois. S'il reste une erreur, le passage est bloqué jusqu'à ce qu'une personne le corrige.
- **Avec quoi** : le brouillon, les erreurs, les observations du brouillon, le budget, le lexique
  et la langue (`prompts.build_revision_prompt`). **Pas les images.**
- **Ce qui change** : le texte, les appuis, et **la confiance**.

**Constat de l'audit : la confiance donnée sans les images remplaçait celle donnée avec.** Un
brouillon trop long noté 0,3 par le modèle, réécrit en texte seul avec une note de 0,95, gardait
0,95 (exécuté). L'alerte « IA peu sûre » disparaissait, et le passage devenait validable en un
clic s'il n'avait pas d'autre alerte. Or une note donnée en relisant son propre texte ne dit rien
de ce que le modèle a vu.

**Corrigé après l'audit** (`agent.confidence_after_rewrite`) :
- Une réécriture peut baisser la note du brouillon, quand elle a dû couper quelque chose, mais
  jamais la remonter.
- Une note inconnue au brouillon reste inconnue, donc signalée.
- Une réécriture sans note garde celle du brouillon.
- Le journal de l'agent garde la note que la réécriture s'est donnée.

`tests/test_confidence_rewrite.py` vérifie ces cas, dont celui du 0,3 qui reste signalé.

## 6. La seconde lecture

- **Activation** : `--seconde-lecture` (même modèle) ou `--seconde-lecture gemini|anthropic|openai|ollama`
  (un autre fournisseur). Désactivée par défaut.
- **Ce que reçoit le vérificateur** : les **mêmes images** et une liste d'au plus **8
  affirmations** du premier modèle (observations, changements, interactions)
  (`DescriberAgent._second_look`). Il ne reçoit pas la description.
- **Quand** : seulement si le passage parle de personnes (gestes, visages, émotions, changements
  ou interactions).
- **Ce qu'il rend** : « oui », « non » ou « incertain » pour chaque affirmation.

Le vérificateur évalue-t-il vraiment l'image, de façon indépendante ? Il regarde bien l'image : ce
n'est pas une relecture du texte seul. Mais il ne décrit pas la scène lui-même. On lui demande si
une affirmation précise est visible, ce qui l'oriente vers le « oui ».

Deux modèles peuvent-ils être d'accord sur une erreur ? Oui, pour plusieurs raisons :

- Par défaut, c'est le **même modèle** qui vérifie.
- Deux modèles différents peuvent partager les mêmes biais.
- La question est posée affirmation par affirmation, ce qui favorise la confirmation.
- Au-delà de 8 affirmations, les suivantes ne sont pas vérifiées.

Ce qui en sort :

- Seul un « non » déclenche une alerte (`signe_non_confirme`). Un « incertain » n'en déclenche
  aucune : le passage reste validable en un clic (exécuté). L'éditeur affiche bien le nombre
  d'affirmations incertaines, mais ne les compte pas comme une alerte.
- Une erreur du vérificateur est notée dans le journal, puis oubliée : le passage n'est pas
  signalé.
- Le gain de la seconde lecture n'a jamais été mesuré. Le README le dit.

## 7. La confiance et les alertes de relecture (`agent.review_flags`)

- La confiance est **une note que le modèle se donne**. Rien ne l'étalonne : on ne sait pas si un
  passage noté 0,8 est plus souvent juste qu'un passage noté 0,6.
- Sous 0,5, le passage est signalé : « IA peu sûre (elle se note 0,3 sur 1) ». Une confiance
  inconnue est signalée aussi.
- **L'éditeur affiche encore cette note en pourcentage**, au-dessus du texte de l'IA (« Texte écrit
  par l'IA · confiance 30 % », dans `editor.js`), et la certitude des émotions aussi (« certitude
  30 % »). Le README dit que l'éditeur la montre comme une note et non comme une probabilité :
  c'est vrai pour l'alerte, pas pour cet en-tête.

## 8. L'échantillon et la validation en un clic

- À la fin de la préparation, `agent.draw_sample` tire au hasard 10 % des passages sans alerte,
  arrondis au-dessus. Il en tire au moins 3 dès qu'il y a 10 passages sans alerte.
- La validation en un clic (`/api/valider-sans-alerte`) est refusée tant que ces passages n'ont
  pas été validés ou ignorés un par un.

C'est un bon garde-fou contre la validation à l'aveugle. Ce n'est pas une garantie : un petit
échantillon voit rarement un défaut peu fréquent. Chances de voir au moins un passage faux dans
l'échantillon, selon la part de passages faux parmi ceux sans alerte :

| Passages relus dans l'échantillon | 5 % de faux | 10 % de faux | 20 % de faux |
| --- | --- | --- | --- |
| 3 (de 10 à 30 passages sans alerte) | 14 % | 27 % | 49 % |
| 10 (100 passages sans alerte) | 40 % | 65 % | 89 % |
| 30 (300 passages sans alerte) | 79 % | 96 % | 99,9 % |

Calcul : 1 − (1 − p)ⁿ, en tirant avec remise. Le tirage réel est sans remise, ce qui donne des
chances un peu plus hautes pour de petits films.

Trois limites en découlent :

- **Une erreur trouvée dans l'échantillon ne change rien.** Une fois les passages de
  l'échantillon corrigés et validés, le clic est permis. Le code n'élargit pas l'échantillon.
- **Ignorer un passage de l'échantillon compte comme l'avoir relu.** Le clic se débloque, et le
  rapport compte ce passage dans `echantillon_relu`. Les crédits écrivent alors « après relecture
  d'un échantillon de N passages ».
- **L'éditeur ne montre que les images fixes.** Relire, c'est comparer le texte aux mêmes images
  que le modèle, sauf si l'on regarde le film à côté.

## 9. Les contrôles des voix, à l'export (`mix.py`)

| Contrôle | Seuil | Niveau |
| --- | --- | --- |
| Voix qui déborde de sa pause, ou qui chevauche la suivante | 0,05 s, après accélération de 1,3 fois au plus | Bloquant pour l'export final |
| Voix muette | Pic sous −40 dBFS | Bloquant |
| Passage après la fin du film, ou voix coupée par la fin | Au-delà de la durée du film | Bloquant |
| Son saturé | 3 pics plats ou plus | Alerte |
| Écart de volume | 6 dB autour de la voix médiane | Alerte |
| Voix trop courte pour son texte | Moins de 40 % du temps attendu, pour un texte d'au moins 1 s | Alerte |
| Silence au début ou à la fin | Plus d'1 s | Alerte |

Ces contrôles mesurent le son, pas ce qui est dit : une voix bien audible peut mal prononcer un
mot. Le README le dit. Ils sont tous des règles fixes. Leurs seuils sont des choix de départ, pas
encore réglés sur de vrais enregistrements.

## 10. Ce qui peut donner une fausse impression de fiabilité

| Ce que l'on voit | Ce que cela veut dire en réalité |
| --- | --- |
| « ok · 7/9 mots » dans l'éditeur | Aucune règle ne s'est déclenchée. Rien n'a été comparé à l'image |
| « Validés en un clic, sans alerte » | Sans alerte des règles, après relecture d'un échantillon qui peut être de 3 passages |
| « confiance 95 % » | Une note que le modèle se donne en voyant les images. Depuis la correction, une réécriture sans les images peut la baisser, plus la remonter |
| « Seconde lecture : 3 confirmés » | Le même modèle, ou un autre, a répondu « oui » à une question qui orientait vers le oui |
| « 331 tests réussis » | Les tests vérifient la logique de Wasf avec des réponses de modèle simulées, pas ce qu'un modèle voit. Le README le dit |
| Crédits : « jamais avec certitude » (avant la correction) | La consigne et le contrôle du texte de l'IA, pas une garantie sur le texte final. Les crédits disent maintenant « avait pour consigne » |

## 11. En résumé

- **Ce qui marche** : les contrôles sont nombreux, rapides et lisibles. Ils bloquent bien ce qui ne
  doit jamais sortir sous la plume de l'IA : refus, mauvaise écriture, texte trop long, secret,
  certitude, diagnostic. Ils rendent visibles les contradictions du modèle.
- **Ce qui manque** : aucun contrôle ne compare le texte à l'image. La seule exception est la
  seconde lecture, facultative, qui ne signale que les « non ».
- **Trois corrections simples réduisent la fausse confiance**, sans rien changer d'autre :
  - garder la confiance du brouillon après une réécriture : **fait après l'audit** ;
  - compter « incertain » comme une alerte : à décider ;
  - afficher la note dans l'éditeur comme dans l'alerte : à décider.

  Les deux dernières demandent une modification du code, donc l'accord de l'équipe.
