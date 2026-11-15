# Audit de l'agent Wasf : autonomie et « intelligence » de l'agent

La question de ce rapport : Wasf est-il un agent intelligent d'audiodescription, ou une
orchestration de consignes et d'appels à une API ? Pour y répondre, chaque décision prise pendant
une préparation est rangée selon qui la prend :

- le **modèle** d'IA ;
- une **règle fixe** du code ;
- une **consigne** donnée au modèle ;
- la **chaîne de traitement** elle-même, c'est-à-dire l'ordre des étapes ;
- un **humain**.

## 1. Qui décide quoi

| Décision | Qui la prend | Où |
| --- | --- | --- |
| Accepter de traiter le film | Humain (case dans l'intention), vérifiée par une règle | `Intent.check_rights` |
| Où parler (les pauses) | Règle : écarts entre sous-titres, ou silences | `gaps.plan_windows` |
| Combien de mots | Règle : durée × débit, 30 au plus | `pipeline.prepare` |
| Combien d'images | Humain, par une option ; la même pour tout le film | `--images`, `--images-contexte` |
| Quelles images | Règle : là où l'image change le plus, parmi 6 vignettes | `pipeline._moments`, `media.most_distinct` |
| Que mettre en avant, que taire | Humain (intention, notes de scène), transmis par consigne | `intent.py`, `prompts.build_draft_prompt` |
| Que décrire, et comment | **Modèle**, guidé par la consigne | `SYSTEM_PROMPT` |
| Ce qu'il a vu, ce qu'il suppose, sa confiance | **Modèle**, sans contrôle extérieur | `prompts.parse_reply` |
| Si le texte est acceptable | Règles | `agent.run_checks` |
| S'il faut réécrire, et combien de fois | Règle : sur erreur, 2 fois au plus, jamais après un refus | `DescriberAgent.describe` |
| Le nouveau texte | **Modèle**, sans les images | `prompts.build_revision_prompt` |
| Si une affirmation se voit | **Modèle vérificateur**, si un humain l'a demandé | `DescriberAgent._second_look` |
| Ce que le passage suivant sait du passé | Chaîne : textes passés, dernier état des personnages | `story.py`, `continuity.py` |
| Arrêter la préparation | Règle : erreur fatale du fournisseur | `providers.is_fatal`, `pipeline._stop_on_fatal` |
| Quels passages relire un par un | Règle : alertes, puis tirage au hasard | `agent.review_flags`, `agent.draw_sample` |
| Le texte final, la signature, l'approbation | **Humain** | Éditeur de relecture |
| Publier | **Humain**, sous conditions vérifiées par des règles | `pipeline.readiness_problems` |

Le modèle ne prend que trois sortes de décisions :

- ce qu'il écrit ;
- ce qu'il dit avoir vu ;
- la note qu'il se donne.

Tout le reste revient à des règles ou à des humains.

## 2. Les capacités demandées, une par une

| Capacité | Présente ? | Comment, ou pourquoi non |
| --- | --- | --- |
| Comprendre le contexte d'une scène | En partie | Le modèle reçoit en texte l'histoire jusque-là (1 500 caractères), le contexte de scène écrit par la réalisation et les répliques voisines. Il ne revoit jamais les images passées |
| Se servir des passages précédents | Oui, en texte | `story_so_far` (dialogues et descriptions déjà écrites), la description précédente pour les répétitions, `character_memory` |
| Garder la continuité | En partie | Par les noms donnés par la réalisation, pas par les visages. Une erreur passée, pas encore relue, est reprise comme vraie |
| S'adapter au temps disponible | Oui, par une règle | Budget de mots, réécriture si le texte est trop long, puis refus à l'export si la vraie voix déborde |
| Repérer son incertitude | Il la déclare | Confiance, certitude des émotions, lectures multiples. Rien ne vérifie que ces notes sont justes. Depuis la correction faite après l'audit, une réécriture faite sans les images peut baisser la note du brouillon, plus la remonter |
| Demander plus d'images | **Non** | Les images sont choisies avant le premier appel. Ni une confiance basse ni une scène ambiguë ne déclenchent un nouveau regard |
| Décider de régénérer | **Non** | La réécriture suit une règle fixe : sur erreur, en texte seul, 2 fois au plus. Le modèle ne décide pas de recommencer, et aucune réécriture ne revoit l'image |
| Tenir compte des remarques de la réalisation | Avant, pas pendant | L'intention guide la préparation. Les corrections faites dans l'éditeur ne reviennent jamais à l'agent. La note d'un passage est pour l'équipe, pas pour l'IA |
| Apprendre des corrections dans le projet | **Non** | Aucune correction ne sert d'exemple aux passages suivants. Les passages sont tous écrits avant la relecture. Aucun entraînement sur le film, par choix |

## 3. Ce qui revient à chaque couche

- **Le modèle** : lire quatre images, écrire une description dans le budget, séparer ce qu'il voit
  de ce qu'il suppose, se noter. Sur demande : confirmer ou non des affirmations.
- **Les règles fixes** : les pauses, les budgets, le choix des images, une vingtaine de contrôles
  de texte, les alertes, l'échantillon, les contrôles des voix, les conditions de l'export.
- **Les consignes** : les règles d'audiodescription, la langue, les émotions, le lexique, les
  exemples, ce qu'il faut faire remarquer et taire.
- **La chaîne de traitement** : l'ordre du film, le contexte passé, la sauvegarde après chaque
  passage, la reprise, l'arrêt sur erreur fatale.
- **Les humains** : l'accord du producteur, l'intention, la relecture, les corrections, la
  signature, l'approbation, et la décision de publier.

## 4. Le niveau d'autonomie

Pour situer Wasf, cet audit utilise sa propre échelle, simple. Ce n'est pas une norme
reconnue.

| Niveau | Ce que fait le système |
| --- | --- |
| 0 | Aucune IA |
| 1 | Un appel au modèle, rien de plus |
| 2 | Une chaîne fixe qui appelle un modèle et reprend sa réponse selon des règles |
| 3 | Le modèle choisit ses actions : revoir la scène, demander d'autres images, appeler un outil |
| 4 | Le système poursuit un objectif sur tout le film, rassemble lui-même ses preuves et corrige sa méthode |
| 5 | Le système publie sans humain |

**Wasf est au niveau 2.** C'est une chaîne fixe, bien outillée : contexte passé, contrôles
nombreux, réécriture automatique, seconde lecture facultative, reprise. Le modèle n'y choisit
aucune action.

**Ce n'est pas un défaut en soi.** Le projet veut que la réalisation décide : rien n'est publié
sans elle, et le code l'impose. Monter au niveau 3, par exemple en laissant le modèle demander
d'autres images quand il se dit peu sûr, pourrait améliorer la justesse sans toucher au contrôle
humain. Il ne faudrait pas monter au niveau 5 : le projet l'exclut.

## 5. Comment le présenter honnêtement

- **Formulations justes** :
  - « un agent qui rédige un premier jet de chaque description, le contrôle avec des règles et le
    remet à la réalisation » ;
  - « une chaîne d'IA encadrée, où l'humain décide ».
- **À éviter** : « agent autonome », « l'IA comprend le film », « l'IA vérifie ses descriptions ».
  Elle vérifie leur forme et leur cohérence avec ce qu'elle dit avoir vu, pas l'image.

## 6. Ce qui rendrait l'agent plus capable, sans enlever la main à l'humain

Ce sont des pistes. Aucune n'a été codée ni mesurée.

| Piste | Ce que cela changerait | Coût |
| --- | --- | --- |
| Revoir l'image quand le modèle se note sous 0,5 : plus d'images, ou plus grandes | Un vrai second regard là où il doute | Un appel avec images de plus, seulement sur ces passages |
| Réécrire avec les images quand l'erreur touche ce qui est vu | Une réécriture qui ne devine plus | Des images renvoyées sur ces passages |
| Signaler dans la consigne que les descriptions passées ne sont pas relues | Moins d'erreurs qui se propagent | Aucun |
| Reprendre les passages corrigés comme exemples, si l'on relance des passages | Le style et le lexique de la réalisation repris | Une relance de préparation |
| Ajouter des images quand le score de changement est élevé | Moins de gestes brefs manqués | Plus d'images, donc plus de jetons et d'énergie |

Chaque piste demande une mesure avant et après ([BENCHMARK_PROTOCOL.md](BENCHMARK_PROTOCOL.md)).
Sans elle, on ne saura pas si elle aide.
