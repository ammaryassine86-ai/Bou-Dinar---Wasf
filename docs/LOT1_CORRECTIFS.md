# Lot 1 : cinq correctifs (14 novembre 2026)

L'audit du code avait relevé cinq problèmes à corriger en premier. Ce document dit, pour
chacun, ce qui n'allait pas, ce qui a changé, quels fichiers ont été touchés, quels tests le
prouvent et ce qui reste à faire. Les sous-titres dynamiques et la formulation des émotions sur
la diapositive d'éthique ne font pas partie de ce lot : ce sont deux chantiers à part.

## En bref

| Code | Problème | Avant | Après | Tests ajoutés |
| --- | --- | --- | --- | --- |
| E03 | Mémoire du mixage | 2 023 Mo pour un film de 20 min, environ 93 Mo de plus par minute de film | environ 121 Mo, que le film dure 5 ou 120 min ; son identique à l'échantillon près | 6 |
| T24 | Voix plus longue que sa pause | export terminé, 5 voix sur 5 débordent sur la réplique suivante (jusqu'à 6,8 s) | export final refusé avec la liste des dépassements ; version de travail toujours possible ; durée estimée visible dans l'éditeur | 7 |
| S01 / S02 | Éditeur attaquable depuis une autre page | une page étrangère valide 2 passages au nom de la réalisatrice ; un faux nom d'hôte lit tout le projet | tout est refusé (403) et le projet reste intact | 26 |
| T14 | Sous-titres arabes en Windows-1256 | 5 répliques derja sur 5 changées en « � », sans un mot ; l'UTF-16 donne 0 réplique, sans un mot | lues à l'identique, encodage affiché ; un fichier illisible arrête tout avec la marche à suivre | 22 |
| T27 | Préparation interrompue | rien n'est enregistré : les brouillons déjà payés sont perdus | le projet est enregistré après chaque passage ; `--reprendre` et `--refaire-echecs` | 10 |

Suite de tests : 141 tests avant le lot, 212 après, tous réussis.

## Méthode

Avant toute modification, le code a été copié dans un dossier daté, hors du dépôt, avec
l'empreinte SHA-256 de chaque fichier. C'est cette copie qui sert de référence « avant » dans
tout ce document.

Un correctif à la fois : le code, ses tests, puis la suite complète. Le nombre de tests a suivi :

| Étape | Tests | Résultat | Durée |
| --- | --- | --- | --- |
| Avant le lot | 141 | 141 réussis | 2 min 59 |
| Après E03 | 147 | 147 réussis | 3 min 32 |
| Après T24 | 154 | 154 réussis | 3 min 54 |
| Après S01 / S02 | 180 | 180 réussis | 3 min 57 |
| Après T14 | 191 | 191 réussis | 4 min 17 |
| Après T27 | 201 | 201 réussis | 5 min 24 |
| Complément T14 (voir plus bas) | 212 | 212 réussis | 5 min 31 |

Le banc d'essai de l'audit (une cinquantaine de cas, hors dépôt) a été rejoué avant et après.
Le banc lui-même a changé à trois endroits, pour tester le nouveau code honnêtement : ses appels
légitimes à l'éditeur portent maintenant le jeton, sans quoi ils seraient refusés comme ceux d'un
attaquant ; le cas S10 lance la vraie commande `wasf relire --hote 0.0.0.0` au lieu de lire le
code ; un nouveau cas, T27b, vérifie que `--refaire-echecs` ne refait que les passages en échec.

## E03 : mixer un long film sans saturer la mémoire

**Avant.** Pour mixer la piste, Wasf décodait tout le son du film en mémoire (nombres à virgule
de 32 bits, 48 kHz, stéréo) et en faisait plusieurs copies : enveloppe de baisse du son, piste
des voix, mélange, conversion finale. Mesuré : 638 Mo pour 5 min, 1 031 Mo pour 10 min,
2 023 Mo pour 20 min. Par extrapolation, environ 8,3 Go pour un long métrage de 90 min : sur un
portable de 8 Go, l'export échoue ou fait ramer la machine.

**Ce qui a changé** (`wasf/mix.py`, `wasf/media.py`) :

- le son du film est décodé une fois dans un fichier brut temporaire (PCM 16 bits), dans un
  dossier `.mixage-…` du dossier d'export, supprimé à la fin, même en cas d'erreur ;
- le mixage se fait par tranches de 30 s lues dans ce fichier, et chaque échantillon subit
  exactement les mêmes calculs qu'avant : le résultat est le même ;
- quand le mélange dépasse 0,98, l'ancien code baissait tout le mélange d'un même facteur. Pour
  garder ce comportement sans tenir le film en mémoire, un premier passage écrit les fichiers et
  trouve le pic, et un second passage réécrit le mélange baissé, seulement s'il le faut ;
- les WAV s'écrivent au fur et à mesure (`media.WavWriter`), octet pour octet comme
  `media.write_wav`.

**Tests** (`tests/test_mix_chunks.py`, 6 tests) :

- cinq cas comparent octet par octet les deux WAV à une copie de l'ancien algorithme, gardée
  dans le test : tranches qui coupent une voix ou un fondu (1,7 s), tranches minuscules (0,05 s),
  tranche par défaut, film fort dont tout le mélange est baissé, film sans piste son. Vérifié une
  fois à la main : décaler le mélange d'un seul échantillon fait échouer les cinq cas ;
- un test mesure la mémoire, dans un processus séparé, sur des films de 2 et 8 min : moins de
  40 Mo d'écart (l'ancien code en prenait environ 560 de plus).

**Résultats.** Sur le clip de démonstration, export final avec la voix `bip` puis `espeak`, ancien
code contre nouveau : `piste_audiodecrite.wav`, `voix_seule.wav` et le son décodé de
`film_audiodecrit.mp4` ont la même empreinte SHA-256 (par exemple `93bc5f66…` pour la piste
mixée avec `bip`, `2df65bd8…` avec `espeak`).

Pic de mémoire, mesuré sur des films de test (son de 48 kHz stéréo, trois descriptions) avec
le code final (`lot1/verif_e03.py`). Le chiffre comprend Python et NumPy, soit une centaine de Mo
à eux seuls. Les temps varient d'une ou deux secondes d'un passage à l'autre, pas la mémoire.

| Film | Avant | Après | Temps du mixage, avant → après |
| --- | --- | --- | --- |
| 5 min | 638,6 Mo | 120,8 Mo | 2,2 s → 2,3 s |
| 10 min | 1 030,7 Mo | 121,4 Mo | 4,6 s → 3,6 s |
| 20 min | 2 023,3 Mo | 121,5 Mo | 8,7 s → 6,8 s |
| 60 min | non mesuré (environ 5,6 Go par extrapolation) | 121,2 Mo | 20,4 s |
| 120 min | non mesuré (environ 11,1 Go par extrapolation) | 121,4 Mo | 37,6 s |

Banc d'essai : le cas E03 passe de « Fail » à « Pass ». Dans le passage complet du banc, il mesure 283 Mo à 5, 10 et 20 min ; lancé seul, 121 Mo. Dans les deux cas, la mémoire ne dépend plus de la durée du film.

**Limites.** Le fichier temporaire occupe sur le disque le son décodé du film, environ 11,5 Mo
par minute (1,4 Go pour 2 h), le temps de l'export. Quand le mélange doit être baissé, le second
passage rallonge un peu l'export.

## T24 : une voix plus longue que sa pause

**Avant.** L'éditeur comptait les mots (pause × débit fixe) mais n'affichait aucune durée. À
l'export, une voix trop longue était accélérée jusqu'à ×1,3, puis placée quand même, sur la
réplique suivante. Cas T24 du banc (moteur de voix trois fois plus lent que prévu) : export
terminé, 5 voix sur 5 sur le dialogue suivant (6,8 s au pire), 5 lignes dans le journal pour
tout avertissement.

**Ce qui a changé :**

- sous chaque texte, l'éditeur affiche la durée estimée, mise à jour pendant la frappe :
  « 3 / 3 mots · environ 1,2 s à dire pour 1,4 s de pause » (mots ÷ débit de la piste) ;
- à l'export, chaque voix est synthétisée puis mesurée. La mesure (durée, accélération, temps
  disponible, dépassement, texte mesuré) est gardée dans le projet (`voix_mesuree`) et affichée
  dans l'éditeur. Tant que le texte n'a pas changé, un passage qui déborde porte le signalement
  « voix trop longue » ; dès qu'on le raccourcit, la mesure est marquée périmée ;
- export final : si une voix ne tient pas dans sa pause, même accélérée (×1,3 au plus, 0,05 s de
  tolérance), ou si elle chevauche la suivante, rien n'est mixé. L'export est refusé avec, pour
  chaque passage, le dépassement et la réplique qu'il couvrirait, et le conseil de raccourcir le
  texte ou d'utiliser `--brouillon`. Le refus est noté dans l'historique (`export_refuse`) ;
- version de travail (`--brouillon`) : toujours produite, elle liste ces voix dans le journal et
  dans le rapport (`voix_hors_pause`).

**Fichiers :** `wasf/mix.py` (`timing_problems`, `VoiceTimingError`, mode strict),
`wasf/tts.py` (`speaking_rate`, `estimated_seconds`), `wasf/agent.py` (`voice_checks`, signalement
« voix trop longue »), `wasf/pipeline.py` (`render`, `_record_voices`), `wasf/export.py`
(`voix_hors_pause`), `wasf/project.py` (`voix_mesuree`, `mots_par_seconde`),
`wasf/editor/app.py`, `editor.js`, `editor.css`.

**Tests** (`tests/test_voice_timing.py`, 7 tests) :

- export final refusé pour une voix trois fois trop lente : ni film ni piste écrits, mesure
  gardée, signalement affiché ;
- version de travail produite malgré tout, avec la liste dans le rapport ;
- export final du clip de démonstration : chaque voix reste dans sa propre pause, ne couvre
  aucune réplique des sous-titres et ne touche aucune autre voix ;
- deux pauses qui se chevauchent (projet modifié à la main) : refus « chevauche » ;
- règles de calcul : dépassement, marge, chevauchement ;
- 300 jeux de sous-titres tirés au hasard (dans le désordre, qui se chevauchent) : les pauses
  prévues ne recouvrent jamais le dialogue ni les unes les autres ;
- l'éditeur montre l'estimation et la voix mesurée ; un texte raccourci rend la mesure périmée et
  le signalement disparaît.

Vérifié aussi dans Chrome : l'éditeur affiche « 3 / 3 mots · environ 1,2 s à dire pour 1,4 s de
pause », puis, après un export refusé, « Voix mesurée à l'export (bip) : 2,8 s, accélérée ×1,3
pour 1,4 s disponibles : elle déborde de 1,4 s ». Après une modification : « Texte modifié depuis
la dernière mesure (bip) : la voix sera mesurée au prochain export ».

Banc d'essai : le cas T24 passe de « Fail » à « Pass » (export final refusé, avec la liste des dépassements).

**Limites.** La durée affichée pendant la relecture reste une estimation : seule la vraie voix,
mesurée à l'export, fait foi, et elle dépend du moteur choisi. L'export final synthétise toutes
les voix avant de refuser : avec un moteur payant (Azure), cette synthèse est facturée. Dans
l'éditeur, « voix trop longue » est un signalement « à vérifier » et non un blocage : c'est
l'export qui bloque. Un export refusé laisse en place les fichiers d'un export précédent réussi.
Les projets créés avant ce lot utilisent le débit par défaut de leur langue.

## S01 / S02 : l'éditeur et les autres pages du navigateur

**Avant.**

- S01 : une page web ouverte dans le même navigateur envoyait un simple formulaire à
  `http://127.0.0.1:8765/api/valider-sans-alerte`. Réponse 200 : 2 passages validés et signés
  « Réalisatrice A » par cette page.
- S02 : une requête avec `Host: attacker.example:8765` recevait tout le projet. Une page de
  « DNS rebinding » pouvait donc lire les textes et les images d'un film inédit.
- S10 : `wasf relire --hote 0.0.0.0` était accepté sans un mot : n'importe qui sur le même Wi-Fi
  pouvait lire et valider.

**Ce qui a changé.** Le jeton n'est pas la seule protection. Chaque requête passe ces contrôles,
dans cet ordre :

1. le nom d'hôte doit être une adresse locale (127.0.0.0/8, `localhost`, `::1`), sinon 403. Une
   page de DNS rebinding arrive sous son propre nom : elle est refusée ici ;
2. `Sec-Fetch-Site`, quand le navigateur l'envoie, doit valoir `same-origin` ou `none`, sinon 403 ;
3. `Origin`, s'il est présent, doit être l'adresse même de l'éditeur, sinon 403 ;
4. tout appel à `/api/` et toute requête qui modifie quelque chose doit porter le jeton de session
   dans l'en-tête `X-Wasf-Jeton`. Le jeton est tiré au hasard à chaque lancement
   (`secrets.token_urlsafe(32)`), écrit seulement dans la page de l'éditeur, et comparé en temps
   constant (`hmac.compare_digest`). Sinon 403 ;
5. une requête qui a un corps doit être du JSON, sinon 415 : un formulaire HTML ne peut pas en
   envoyer.

Les réponses interdisent l'affichage de l'éditeur dans le cadre d'une autre page
(`X-Frame-Options: DENY`, CSP `frame-ancestors 'none'`), limitent la page à ses propres fichiers
(`default-src 'self'`, `form-action 'none'`) et ne sont pas mises en cache (`no-store`). Le
serveur n'écoute que sur une adresse locale : `--hote 0.0.0.0` ou une adresse du réseau est
refusé, avec l'explication (S10).

**Fichiers :** `wasf/editor/app.py`, `wasf/editor/static/editor.js`,
`wasf/editor/templates/index.html`, `wasf/cli.py`. Côté tests, `tests/editeur_client.py` ouvre
l'éditeur comme sa vraie page, avec le jeton ; `test_emotions.py`, `test_pipeline.py`,
`test_second_pass.py` et `test_trust.py` l'utilisent désormais.

**Tests** (`tests/test_editor_security.py`, 26 tests) :

- appels sans jeton ou avec un faux jeton refusés, sur chaque route ; nouveau jeton à chaque
  lancement ;
- requêtes d'un autre site refusées même avec le bon jeton (`Origin` étranger, `Sec-Fetch-Site`
  `cross-site` ou `same-site`) ; corps autre que JSON refusé (415) ;
- noms d'hôte étrangers refusés, adresses locales acceptées ; la page porte le jeton et ne peut
  pas être encadrée ;
- `wasf relire --hote` avec `0.0.0.0`, `::` ou une adresse du réseau : refusé, code de sortie 1 ;
- sur un vrai serveur, scénario de DNS rebinding (`Host` et `Origin` au nom de l'attaquant,
  `Sec-Fetch-Site: same-origin` comme après le rebinding) : page, API et validation refusées ;
- sur un vrai serveur, requêtes non autorisées (autre site, autre port local, aucun en-tête) :
  toutes refusées, projet inchangé ; la page de l'éditeur, elle, récupère le jeton et fonctionne ;
- `wasf relire` lancé comme un vrai processus : joignable sur 127.0.0.1, injoignable depuis
  l'adresse réseau de la machine.

Vérifié aussi dans Chrome, avec une page d'attaque servie sur un autre port local : le
formulaire et la requête `no-cors` arrivent au serveur et sont refusés (403), la lecture du
projet est bloquée, le cadre est refusé (`frame-ancestors 'none'`). Après l'attaque : approbation
de la réalisation toujours à faux, aucun passage validé en un clic, textes inchangés.
L'enregistrement depuis l'éditeur lui-même fonctionne (« Enregistré. »).

Banc d'essai : S01 et S02 passent de « Fail » à « Pass » (403, aucun passage validé, projet non renvoyé), S10 de « Partial » à « Pass » (`--hote 0.0.0.0` refusé, code de sortie 1). S03 (sortir du dossier des images) et S04 (script injecté) restent à « Pass ».

**Limites.** Il faut ouvrir l'éditeur par l'adresse affichée par `wasf relire` : un lien venu
d'un autre site est refusé, c'est voulu. Le jeton protège des pages web, pas des programmes : un
autre programme lancé sur le même ordinateur, ou un autre compte de cet ordinateur, peut ouvrir
la page et y lire le jeton. Sur un ordinateur partagé, fermez l'éditeur après la relecture. Un
navigateur ancien qui n'envoie pas `Sec-Fetch-Site` laisse une autre page afficher une image
extraite, sans pouvoir la lire ; le projet, lui, reste protégé par le jeton. Le cas S09 (texte
de plusieurs Mo envoyé à l'éditeur) n'est pas traité : il est prévu au lot 3.

## T14 : sous-titres arabes et encodages

**Avant.** Les sous-titres étaient lus en UTF-8 (`errors="replace"`), en remplaçant sans
prévenir tout octet illisible par « � ». Les sous-titres arabes faits sous Windows sont souvent en Windows-1256 :
5 répliques derja sur 5 devenaient illisibles. Un fichier UTF-16 donnait 0 réplique, sans
message, et les pauses venaient alors des silences, parfois sur le dialogue. Aucun encodage
n'était indiqué.

**Ce qui a changé** (`wasf/gaps.py`, `wasf/pipeline.py`, `wasf/project.py`, `wasf/cli.py`).
Wasf essaie, dans cet ordre :

1. l'UTF-16 avec sa marque d'ordre des octets (BOM) ;
2. l'UTF-16 sans BOM, reconnu à ses octets nuls : minutages et chiffres sont en ASCII, donc
   environ un octet sur deux est nul. Quelques octets nuls égarés dans un autre fichier sont une
   avarie et arrêtent la lecture ;
3. l'UTF-8, avec ou sans BOM ;
4. le Windows-1256, gardé seulement si le texte donne des mots arabes entiers ;
5. l'ISO-8859-6, l'autre page de code arabe, plus ancienne, avec le même contrôle ;
6. le Windows-1252, gardé seulement si le texte n'est pas fait de mots en lettres accentuées.

Pourquoi ces contrôles : ces pages de code donnent un caractère à presque chaque octet, si bien
que n'importe quel fichier « se lit ». Le contrôle écarte la mauvaise lecture. Un fichier français
en Windows-1252 lu comme du Windows-1256 met des lettres arabes dans des mots latins
(« École » devient « ةcole »). Un fichier arabe lu comme du Windows-1252 donne des mots comme
« ÕÇÑ ». Un fichier en ISO-8859-6 lu comme du Windows-1256 glisse des lettres latines entre des
lettres arabes (« جيتش » devient « جêتش »). Un mot français collé à l'article, comme « الـwifi »,
reste normal.

Si rien ne convient, la préparation s'arrête avant le moindre appel à l'IA, avec la marche à
suivre (enregistrer le fichier en UTF-8 dans Subtitle Edit ou Aegisub). Aucun caractère n'est
jamais remplacé. L'encodage trouvé est écrit dans le journal (« Sous-titres : 5 réplique(s),
encodage Windows-1256 (arabe). ») et gardé dans le projet (`encodage_sous_titres`). Un fichier
qui contient déjà des « � » est lu, mais signalé.

**Complément, ajouté en rédigeant ce document.** En préparant les exemples, trois trous sont
apparus dans le correctif T14 : l'UTF-16 enregistré sans BOM donnait encore 0 réplique sans
message (en ASCII, c'est même de l'UTF-8 valide) ; l'ISO-8859-6 était lu comme du Windows-1256,
avec de mauvaises lettres ; un fichier de texte sans aucun minutage donnait 0 réplique sans
message. Les trois sont corrigés, avec leurs tests, et la suite complète a été rejouée. Un
changement de comportement en découle : un fichier qui contient du texte mais aucune réplique
minutée arrête maintenant la préparation, au lieu de passer en silence à la détection des
silences. Un fichier vide, lui, garde l'ancien comportement (pauses tirées des silences), avec
un avertissement.

**Tests** (`tests/test_subtitle_encoding.py`, 22 tests). Les échantillons derja ont cinq
répliques, avec chadda, orthographes tunisiennes et un mot français collé à l'article
(« الـwifi ما يخدمش ») :

- lus à l'identique, minutages compris, sans un seul « � », en UTF-8, UTF-8 avec BOM et fins de
  ligne Windows, Windows-1256, UTF-16 avec BOM, UTF-16 sans BOM (petit et grand boutiste) et
  ISO-8859-6 ;
- la lettre ڨ (le /g/ tunisien), absente du Windows-1256, passe en UTF-8 ;
- français en Windows-1252 non pris pour de l'arabe, et l'inverse ; les deux pages de code
  arabes ne sont pas prises l'une pour l'autre ; l'UTF-16 en ASCII n'est pas lu comme de l'UTF-8 ;
- fichier abîmé, octets nuls égarés, texte sans minutage : arrêt avec un message clair ;
  fichiers vides : avertissement seulement ; « � » déjà présents : avertissement ;
- `wasf preparer` écrit l'encodage dans le journal et dans le projet, et le dialogue derja
  arrive intact jusqu'au contexte de l'agent ; la commande refuse un fichier illisible (code 1,
  aucun projet écrit).

**Résultats**, mêmes fichiers lus par l'ancien et le nouveau code :

| Échantillon | Avant | Après |
| --- | --- | --- |
| Derja, UTF-8 | 5 répliques, encodage non indiqué | 5 répliques exactes, UTF-8 |
| Derja, Windows-1256 | 5 répliques, toutes illisibles (« ����� ��ѿ… ») | 5 répliques exactes, Windows-1256 |
| Derja, ISO-8859-6 | 5 répliques, toutes illisibles | 5 répliques exactes, ISO-8859-6 |
| Derja, UTF-16 avec BOM | 0 réplique, aucun message | 5 répliques exactes, UTF-16 |
| Derja, UTF-16 sans BOM | 0 réplique, aucun message | 5 répliques exactes, UTF-16 |
| Français, UTF-16 sans BOM | 0 réplique, aucun message | 3 répliques exactes, UTF-16 |
| Français, Windows-1252 | 3 répliques abîmées (« � Tu viens ? � �a d�pend. ») | 3 répliques exactes, Windows-1252 |
| Fichier abîmé | 1 réplique abîmée, aucun message | arrêt : « Impossible de lire… », marche à suivre |
| Texte sans minutage | 0 réplique, aucun message | arrêt : « Aucune réplique lue… », marche à suivre |
| Fichier vide | 0 réplique, aucun message | 0 réplique, avertissement : pauses tirées des silences |

Banc d'essai : le cas T14 passe de « Fail » à « Pass » (0 réplique sur 4 abîmée, encodage signalé).

**Limites.** Les seuils des contrôles (20 % de mots mêlés, 2 % de lettres latines entre des
lettres arabes) ont été vérifiés sur nos échantillons et sur tout le texte arabe du dépôt
(212 lignes sur 213 reconnues une à une, la dernière étant une ligne de code Python), pas sur un
corpus de vrais fichiers de sous-titres tunisiens : à vérifier avec ceux des productions. Le Mac
arabe et l'UTF-32 ne sont pas lus : ils arrêtent la préparation avec le message. Le DOS 720, page
de code arabe de l'époque MS-DOS, est pris pour du Windows-1256 et donne de mauvaises lettres ;
l'encodage affiché et le dialogue montré dans l'éditeur permettent de le repérer. On ne s'attend
pas à le croiser dans des sous-titres d'aujourd'hui.

## T27 : préparation interrompue

**Avant.** Le projet n'était enregistré qu'une fois, à la toute fin. Cas T27 du banc (Ctrl+C
pendant le 3e appel au modèle) : aucun `projet.json`, 18 images sur le disque, 2 brouillons
payés perdus. Rien ne permettait de reprendre.

**Ce qui a changé** (`wasf/pipeline.py`, `wasf/project.py`, `wasf/cli.py`, `wasf/agent.py`,
`wasf/editor/app.py`, `editor.js`, `index.html`) :

- le projet est enregistré dès que les pauses et leurs images sont prêtes, puis après chaque
  passage écrit ;
- chaque enregistrement est atomique et durable : fichier temporaire dans le même dossier, écrit
  puis forcé sur le disque (`fsync`), puis `os.replace` sur `projet.json`, puis `fsync` du
  dossier. Une coupure à n'importe quel moment laisse l'ancien fichier entier ou le nouveau
  entier, jamais un mélange. Le fichier temporaire est effacé si l'écriture échoue, y compris sur
  Ctrl+C ;
- chaque passage a un état IA (`a_faire`, `fait`, `echec`) et le projet un état de préparation
  (`en_cours`, `terminee`) ;
- `--reprendre` ne traite que les passages `a_faire` : aucun appel à l'IA pour ceux qui sont
  faits. Les images manquantes sont réextraites, sans appel à l'IA ;
- `--refaire-echecs` ne refait que les passages en échec, et seulement ceux qu'une personne n'a
  pas réécrits à la main entre-temps ;
- un Ctrl+C arrête proprement (code 130) et rappelle la commande `--reprendre` ; relancer sans
  `--reprendre` sur un projet inachevé renvoie vers `--reprendre` au lieu d'écraser ;
- tant que la préparation est en cours ou interrompue, l'éditeur est en lecture seule (bandeau
  « Préparation inachevée », réponses 409) et l'export est refusé : aucune modification ne peut
  se perdre.

**Tests** (`tests/test_checkpoints.py`, 10 tests) :

- une préparation coupée au 3e passage garde les 2 premiers, sans fichier temporaire oublié ;
- `--reprendre` : un faux fournisseur compte les appels. Seuls p003, p004 et p005 sont demandés,
  aucun appel pour p001 et p002, qui restent identiques champ pour champ. Les textes finaux sont
  ceux d'une préparation jamais interrompue ;
- `--refaire-echecs` : p002 et p004 échouent ; p004 est réécrit à la main dans l'éditeur ; seul
  p002 est redemandé, p004 garde le texte écrit à la main, les autres ne bougent pas. Relancé
  une seconde fois : aucun appel ;
- le projet est relu sur le disque à chaque enregistrement : JSON entier à chaque fois, avec
  0, 1, 2, 3, 4, 5 passages faits ;
- enregistrement atomique : `fsync` appelé ; si `os.replace` échoue (disque plein, Ctrl+C),
  l'ancien fichier reste intact, octet pour octet, et aucun fichier temporaire ne traîne ;
- éditeur et export attendent la fin de la préparation ;
- images supprimées réextraites sans appel à l'IA ; projets d'avant ce lot reconnus ; ligne de
  commande (code 130 sur Ctrl+C, puis reprise jusqu'au bout).

Vérifié aussi dans Chrome sur un projet interrompu : bandeau « Préparation inachevée » affiché,
et le bouton « Valider et signer » répond « La préparation de ce projet est en cours ou a été
interrompue : la relecture est en lecture seule… ».

Banc d'essai : T27 passe de « Fail » à « Pass » (`projet.json` présent, 2 brouillons gardés) ; le nouveau cas T27b passe aussi (seuls les 2 passages en échec sont redemandés, les autres ne changent pas).

**Limites.** La reprise utilise l'intention copiée dans le projet au premier lancement : il faut
redonner `--sous-titres` en reprenant. Wasf ne retente pas lui-même une erreur passagère du
fournisseur (quota de la minute, réseau), sauf avec Gemini ; les bibliothèques de Claude et
d'OpenAI réessaient deux fois de leur côté, Ollama jamais. Un passage qui échoue quand même reste
vide et signalé, et `--refaire-echecs` le refait ensuite (cas T26, toujours en échec au banc). Sous
Windows, le dossier n'est pas forcé sur le disque après le remplacement (Windows ne le permet
pas) ; le fichier, lui, l'est.

## Banc d'essai de l'audit, avant et après

Avant : 32 « Pass », 8 « Partial », 10 « Fail » sur 50 cas. Après : 40, 7 et 4 sur 51 (T27b
ajouté). Aucun cas n'a régressé. Les cas qui ont changé :

| Cas | Avant | Après |
| --- | --- | --- |
| E03 Mémoire du mixage | Fail | Pass |
| S01 Requête venue d'un autre site | Fail | Pass |
| S02 Faux nom d'hôte (DNS rebinding) | Fail | Pass |
| S10 Éditeur ouvert sur le réseau | Partial | Pass |
| T14 Sous-titres arabes en Windows-1256 | Fail | Pass |
| T24 Voix plus longue que sa pause | Fail | Pass |
| T27 Préparation interrompue | Fail | Pass |
| T27b Refaire seulement les passages en échec | (nouveau) | Pass |

Restent en échec, hors de ce lot : T08 (mauvais types de valeurs dans le fichier d'intention),
T15 (sous-titres d'un autre montage), T26 (pas de nouvelle tentative automatique) et T35
(modification pendant un export).

Vérification statique : `ruff` signale 26 remarques sur le code final contre 27 avant, et aucune
n'est nouvelle.

## Ce qui n'est pas dans ce lot

- Les sous-titres dynamiques pour sourds et malentendants : chantier séparé.
- La phrase sur les émotions de la diapositive d'éthique, qui ne correspond pas au réglage par
  défaut du code (émotions « nuancées ») : à trancher à part.
- T26 : nouvelle tentative automatique, avec attente croissante, après une erreur passagère.
- T35 : une modification faite dans l'éditeur pendant un export peut être écrasée à la fin de
  l'export (lot 2).
- S09 : pas de limite de taille pour un texte envoyé à l'éditeur (lot 3).

## Fichiers modifiés

| Fichier | État | Lignes (+ / −) | Pour |
| --- | --- | --- | --- |
| `wasf/agent.py` | modifié | +40 / −4 | T24 signalement « voix trop longue » ; T27 échec signalé |
| `wasf/cli.py` | modifié | +34 / −7 | S10 refus de --hote ; T27 --reprendre, --refaire-echecs, Ctrl+C |
| `wasf/editor/app.py` | modifié | +113 / −5 | S01/S02 contrôles et en-têtes ; T24 durées ; T27 lecture seule |
| `wasf/editor/static/editor.css` | modifié | +4 / −0 | T24 styles des durées |
| `wasf/editor/static/editor.js` | modifié | +42 / −5 | S01/S02 jeton ; T24 durées ; T27 bandeau |
| `wasf/editor/templates/index.html` | modifié | +7 / −0 | S01/S02 jeton ; T27 bandeau |
| `wasf/export.py` | modifié | +3 / −0 | T24 `voix_hors_pause` dans le rapport |
| `wasf/gaps.py` | modifié | +128 / −2 | T14 lecture des encodages |
| `wasf/media.py` | modifié | +59 / −12 | E03 décodage vers un fichier, écriture WAV au fil de l'eau |
| `wasf/mix.py` | modifié | +176 / −55 | E03 mixage par tranches ; T24 mesure des voix, refus strict |
| `wasf/pipeline.py` | modifié | +252 / −37 | T24 refus d'export ; T14 encodage ; T27 points de reprise, reprise |
| `wasf/project.py` | modifié | +50 / −4 | T24 voix mesurée ; T14 encodage ; T27 états et sauvegarde atomique |
| `wasf/tts.py` | modifié | +11 / −0 | T24 débit et durée estimée |
| `tests/editeur_client.py` | nouveau | +11 / −0 | client de test avec le jeton |
| `tests/test_checkpoints.py` | nouveau | +235 / −0 | T27 |
| `tests/test_editor_security.py` | nouveau | +237 / −0 | S01/S02/S10 |
| `tests/test_emotions.py` | modifié | +3 / −3 | éditeur ouvert avec le jeton |
| `tests/test_mix_chunks.py` | nouveau | +145 / −0 | E03 |
| `tests/test_pipeline.py` | modifié | +3 / −3 | éditeur ouvert avec le jeton |
| `tests/test_second_pass.py` | modifié | +2 / −2 | éditeur ouvert avec le jeton |
| `tests/test_subtitle_encoding.py` | nouveau | +161 / −0 | T14 |
| `tests/test_trust.py` | modifié | +8 / −8 | éditeur ouvert avec le jeton |
| `tests/test_voice_timing.py` | nouveau | +178 / −0 | T24 |
| `README.md` | modifié | +58 / −5 | nouvelles options, sécurité, encodages, limites |
| `docs/LOT1_CORRECTIFS.md` | nouveau | ce document | |

Les empreintes SHA-256 de chaque fichier, avant et après, sont gardées avec les preuves du lot.

## Rejouer les vérifications

```bash
pip install -e ".[dev,gemini,anthropic,openai]"
pytest                                   # toute la suite
pytest tests/test_mix_chunks.py tests/test_voice_timing.py tests/test_editor_security.py \
       tests/test_subtitle_encoding.py tests/test_checkpoints.py      # les tests du lot 1
```

Le test de mémoire utilise le module `resource` : il est sauté sous Windows.
