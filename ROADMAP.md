# Feuille de route — Bot de guilde

Une étape à la fois. Ne pas anticiper les suivantes.
Chaque étape se termine par : test manuel réussi, puis commit, puis rendu d'explication technique court et concis.

## Où on en est — 1er octobre 2026

Étapes 1 à 4bis terminées, testées sur le serveur et commitées.

Deux étapes sont écrites mais **pas encore testées sur le serveur** :
l'**étape 4ter**, qui fait passer le vote des boutons aux réactions, et
l'**étape 5**, le sondage du nom de guilde. Leurs deux scénarios de recette sont
en bas de ce fichier, à dérouler avant de commiter.

Côté échéances, le code ne bloque plus rien : les trois sondages peuvent être
clos dès que tu as tranché. L'étape 5 a aussi amené les modales, sur lesquelles
se greffera la commande de création de sondage à la volée.

L'étape 4 a été remaniée le 30 septembre, après un premier jet : deux messages
au lieu d'un, chacun avec son tableau en colonnes Tank / Soigneur / DPS, des
boutons à bascule en gris, et plus de bouton « Recommencer ». Le scénario de
recette est conservé en bas de ce fichier : il sert de non-régression.

### Mise en route sur une nouvelle machine

```sh
python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
```

Puis remplir `.env`. Trois valeurs sont déjà connues, seul le token est à
récupérer sur le portail développeur Discord :

```
DISCORD_TOKEN=   <- à récupérer, jamais commité
GUILD_ID=1551290844685017161
GM_ROLE_ID=1551972951769747456        (rôle « Maître de guilde »)
OFFICER_ROLE_ID=1551968511562227833   (rôle « Officier »)
```

Vérifier que tout passe : `.venv/bin/pytest`, `.venv/bin/ruff check src tests`,
`.venv/bin/pyright`.

### Ce qui n'est pas dans le dépôt

- **`data/bot.db`** — recréée au démarrage par les migrations. Elle ne contenait
  que des données de test, rien à transférer.

Les 12 icônes sont en place dans `assets/` et versionnées. Tant qu'une icône
manque, le bot utilise l'emoji unicode de repli de `classes.toml` : rien ne
casse, mais `/emojis` doit être lancée pour que les vraies icônes s'affichent.

### Couleur du pseudo

Discord affiche la couleur du rôle **le plus haut** qui en a une. Le rôle du bot
est sous Membre, Officier et Maître de guilde, donc les rôles de classe sont créés
sous eux : un officier garde la couleur d'officier, sa classe ne se voit pas.

Deux façons de régler ça, toutes deux à faire à la main dans les paramètres du
serveur, le bot ne peut pas s'en charger :

- retirer la couleur des rôles Membre, Officier et Maître de guilde — la couleur
  de classe remonte alors d'elle-même, et le rang reste lisible au classement ;
- ou remonter le rôle du bot au-dessus d'Officier, puis les rôles de classe
  au-dessus aussi. Plus intrusif, et ça met les classes au-dessus des grades.

### État du serveur Discord

- Les 9 rôles de classe **existent déjà**, créés lors d'un test. `/roles-classes`
  les récupérera par leur nom au lieu d'en créer des doublons.
- Le rôle du bot est au-dessus des rôles de classe, donc il peut les attribuer.
  Il reste **sous** Membre, Officier et Maître de guilde, qu'il ne peut donc pas
  attribuer. Sans conséquence aujourd'hui.
- Les 14 icônes sont des **emojis du serveur**, posées à la main : les 9 classes,
  les 3 rôles, plus `alliance` et `horde`. Aucun emoji d'application n'est envoyé,
  et `/emojis` n'a donc plus rien à faire — le bot lit le serveur en premier.
- Le bot a besoin de « Gérer les messages » dans le salon des sondages pour
  retirer les réactions hors menu. `/sondage` refuse de poster sans elle.

### Manques connus, dans aucune étape

- **Ajouter une option à un sondage déjà ouvert** ne l'ajoute pas en base : les
  options sont copiées à la création. Il faut supprimer le sondage et le rouvrir.
- **Aucune commande d'officier n'efface les choix de quelqu'un d'autre.** Chacun
  défait les siens en recliquant. `ClassRepo.clear_choices()` est écrite et
  testée : il ne manque que la commande qui l'appelle, si le besoin se présente.
- **Un vote par réaction est silencieux.** Une réaction ne passe pas par une
  interaction, donc rien ne peut être répondu au votant, pas même un éphémère.
  Le compteur du message est le seul accusé de réception. Accepté en l'état.
- **Pas d'anti-rebond sur la réécriture du message.** Chaque réaction déclenche
  une édition, et Discord en limite environ 5 par 5 secondes par salon. À trente
  votants dans la même minute l'affichage prendra du retard, sans rien perdre en
  base. À traiter si ça se produit vraiment, pas avant.

## Contrainte de calendrier

- Bêta WoW Forever : jusqu'au 21 octobre 2026
- Réservation des noms : 27 octobre – 3 novembre
- Création des personnages : à partir du 27 octobre
- Sortie : 4 novembre

Les sondages Faction, Type de royaume et Nom de guilde doivent être
clos avant le 25 octobre. La faction ne conditionne pas la réservation du
nom mais la création des personnages, qui ouvre le 27 octobre : tout le
monde doit créer du même côté.
Les étapes 1 à 5 sont donc prioritaires. L'étape 6 peut attendre la sortie.

## Questions ouvertes

- Hébergement final : VPS, Raspberry Pi ou plateforme ? (avant l'étape 5)

## Décisions prises

- **Création de sondages depuis Discord** : approche mixte retenue. `polls.toml`
  reste la source des sondages structurants d'avant-lancement (faction, royaume), dont les clés sont inscrites en base et dans les boutons. Une
  commande de création à la volée, pour les sondages ponctuels d'après-sortie,
  sera greffée sur l'étape 5 qui amène déjà les modales. Ne rien figer d'ici là
  qui empêcherait un sondage défini en base plutôt qu'en fichier.

---

## Étape 1 — Squelette

Le bot démarre, se connecte, répond à une commande.

- [x] Arborescence du projet, `pyproject.toml`, dépendances
- [x] Chargement de la configuration via pydantic-settings et `.env`
- [x] Connexion du bot, intents minimaux (members activé)
- [x] Synchronisation des commandes sur `GUILD_ID` au démarrage
- [x] Commande `/ping` qui répond « Pong »
- [x] Journalisation lisible dans la console
- [x] ruff et pyright configurés, aucune erreur

Fini quand : `python -m bot` démarre et `/ping` répond sur le serveur.

## Étape 2 — Base de données

Le schéma et la couche d'accès, sans aucune commande Discord.

- [x] Module de migrations : lit `migrations/*.sql`, applique celles qui manquent
- [x] Migration 001 : tables members, polls, poll_options, poll_votes
- [x] Dataclasses du domaine correspondantes
- [x] `MemberRepo` et `PollRepo` avec leurs méthodes de base
- [x] Tests unitaires des repositories sur une base temporaire

Fini quand : les tests passent, et relancer le bot ne rejoue pas les migrations.

## Étape 3 — Sondages simples

Les trois sondages à choix limité, sans propositions ni combos.

- [x] Définition des sondages en configuration, validée par pydantic
- [x] Commande `/sondage <clé>`, réservée à GM et Officier
- [x] Vue persistante à boutons, `custom_id` stables
- [x] Un vote par personne, modifiable, stocké en base
- [x] Le message affiche les compteurs en direct
- [x] Commande `/resultats <clé>`, réservée à GM et Officier
- [x] Sondages : faction, type de royaume, pack Skyborne

Fini quand : le bot redémarre en plein sondage et les boutons fonctionnent encore.

**Remanié par l'étape 4ter** : les boutons de vote ont disparu au profit des
réactions, et « un vote par personne » est devenu configurable. Les deux lignes
ci-dessus décrivent l'état livré à l'époque, pas le code actuel.

**Révisé le 1er octobre** : le sondage Skyborne est retiré, et le type de
royaume est refait sur le modèle de Faction — deux choix, JcE et JcJ, portés par
les emojis `:murloc:` et `:pvp:` du serveur, et répondre les deux est permis.
Il ne reste donc que deux sondages, tous deux multi-réponses.

## Étape 4 — Déclaration de classe et de rôle

Le plus délicat : deux tableaux vivants, des boutons à bascule, attribution de rôle.

Énoncé révisé plusieurs fois en cours d'étape. Les menus déroulants sont devenus
des boutons. Puis le classement par préférence a été séparé en deux messages :
le personnage principal d'un côté, les classes encore en réflexion pour ce même
personnage de l'autre — ce ne sont pas des personnages secondaires, mais une
liste courte de candidats non tranchés. Chacun a son tableau en colonnes
Tank / Soigneur / DPS.

Les boutons **restent gris**, pour tout le monde. Le style d'un bouton appartient
au message, et un message de salon est le même pour tous : une couleur y
montrerait le dernier qui a cliqué, pas celui qui regarde. Le retour visuel est
le tableau juste au-dessus, où le pseudo entre et sort d'une colonne en direct.

Un clic ne produit **qu'un seul message éphémère** : la question du rôle, une
erreur, ou une confirmation. La question du rôle devient sa propre confirmation
au lieu d'en empiler une seconde, et tout message terminal s'efface au bout de
30 secondes.

- [x] Deux messages suivis : « Composition au lancement » et « Autres classes
      envisagées au lancement »
- [x] Chaque encart répartit les pseudos en colonnes Tank / Soigneur / DPS, avec
      l'icône de classe devant chaque nom
- [x] Un bouton par classe sous chaque message, icône **et** nom, gris
- [x] Encart 1 : cliquer déclare la principale, recliquer la retire avec sa
      couleur, cliquer une autre la remplace
- [x] Encart 2 : cliquer ajoute, recliquer retire, refus si la classe est déjà la
      principale, refus si les deux places sont prises
- [x] Refus vérifiés **avant** la question du rôle, pour ne pas la poser pour rien
- [x] Étape du rôle sautée quand la classe n'en a qu'un seul
- [x] Un seul éphémère par clic, effacé au bout de 30 secondes
- [x] Icônes de classe et de rôle en emojis d'application, via `/emojis`
- [x] Création des rôles Discord de classe, colorés, non séparés
- [x] Récupération d'un rôle existant de même nom, sans doublon
- [x] Vérification de la hiérarchie avant `add_roles`, message clair si échec
- [x] `/composition` : répartition tanks / heals / dps

Fini quand : Mage cliqué sous le premier message donne le rôle Mage, colore le
pseudo en bleu clair et fait apparaître le nom dans la colonne DPS ; recliquer
Mage défait tout.

### Scénario de recette — passé le 30 septembre 2026

Déroulé en entier sur le serveur, tout est passé. Conservé comme non-régression :
à rejouer si les boutons ou les tableaux sont retouchés.

**Préalable** : retirer la couleur des rôles Membre, Officier et Maître de guilde,
sinon les étapes 4 et 6 à 8 échouent à tort — voir « Couleur du pseudo » plus haut.

| #  | Action | Attendu |
|----|--------|---------|
| 1  | `/emojis` | « Envoyées (12) », ou la liste de ce qui manque |
| 2  | `/roles-classes` | **« Récupérés (9) »**, pas « Créés » : les rôles existent déjà |
| 3  | `/classes` | **Deux** messages, 9 boutons gris chacun sur 2 rangées, icône + nom, colonnes à « — » |
| 4  | Msg 1 → Mage | Aucune question de rôle. Confirmation seule, pseudo bleu clair, nom en colonne DPS |
| 5  | Attendre 30 s | La confirmation disparaît toute seule |
| 6  | Msg 1 → Mage | « retirée », pseudo redevient blanc, la colonne DPS se vide |
| 7  | Msg 1 → Druide | « Druide — quel rôle ? ». Tank → **le même message** devient la confirmation, pseudo orange |
| 8  | Msg 1 → Paladin → Soigneur | « Elle remplace **Druide** », une seule ligne dans le tableau |
| 9  | Msg 2 → Prêtre → Soigneur | « ajoutée », colonne Soigneur du msg 2. **Le msg 1 ne bouge pas** |
| 10 | Msg 2 → Voleur | Ajouté sans question de rôle |
| 11 | Msg 2 → Chaman | « Tu as déjà 2 classes envisagées », **sans** question de rôle |
| 12 | Msg 2 → Paladin | « est déjà ta classe principale », **sans** question de rôle |
| 13 | Msg 2 → Voleur | « retirée », la colonne DPS du msg 2 se vide |
| 14 | Msg 1 → Prêtre → Soigneur | Promu : quitte le msg 2, arrive dans le msg 1, **les deux** se mettent à jour |
| 15 | `/composition` | Répartition, classes envisagées comptées à part |
| 16 | `Ctrl-C`, relancer, recliquer sur les deux messages | Tout répond encore |

L'étape 16 est le test décisif : rien n'est gardé en mémoire, chaque bouton est
reconstruit depuis le `custom_id` inscrit dans le message.

Les étapes 11 et 12 vérifient que les refus arrivent avant la question du rôle.
Les étapes 9 et 14 vérifient que seul le tableau qui a changé est réécrit, sauf
en cas de promotion où les deux le sont.

Reste ouvert, hors étape : `/classes` relancée poste deux nouveaux messages et
fige les anciens, qui gardent des boutons actifs. À supprimer à la main.

## Étape 4bis — Clôture des sondages

Hors feuille de route initiale, ajoutée le 30 septembre : `PollRepo.close()`
existait et était testée, mais rien ne l'appelait, et les sondages Faction,
Type de royaume et Nom de guilde doivent être clos avant le 25 octobre.

Une commande plutôt qu'un bouton sous le sondage : un composant fait partie du
message, donc un bouton « Clore » serait visible et cliquable par tous les
membres, avec un refus à la clé. Discord ne sait pas masquer un bouton selon le
rôle. La commande, elle, suit `/sondage` et `/resultats` et reste invisible.

Pas de réouverture : `/clore` montre les résultats et demande confirmation
avant d'agir. Une fois confirmée, la clôture est définitive.

- [x] `/clore <clé>`, réservée à GM et Officier, même autocomplétion que `/sondage`
- [x] Confirmation éphémère portant les résultats classés, avec « Clore
      définitivement » et « Annuler »
- [x] Boutons de confirmation persistants comme les autres : `timeout=None`,
      clé dans le `custom_id`, rien en mémoire
- [x] À la confirmation : message du sondage réécrit en gris, pied « Sondage
      clos. », boutons de vote retirés
- [x] Clôture valable même si le message public est irrécupérable, avec un
      avertissement dans la réponse
- [x] Clore un sondage déjà clos est dit, pas rejoué

Fini quand : `/clore` sur un sondage voté fige son message, et un clic sur un
bouton de vote d'un ancien message répond « Ce sondage est clos ».

### Scénario de recette — passé le 30 septembre 2026

Déroulé sur le serveur, tout est passé. Conservé comme non-régression.

| # | Action | Attendu |
|---|--------|---------|
| 1 | `/clore` sur un sondage jamais ouvert | « Ce sondage n'a pas encore été ouvert » |
| 2 | `/sondage clé:faction`, voter à 2 comptes si possible | Compteurs à jour |
| 3 | `/clore clé:faction` | Éphémère : résultats classés + les deux boutons |
| 4 | « Annuler » | « Annulé. Le sondage reste ouvert. » Le message public n'a pas bougé, on peut encore voter |
| 5 | `/clore clé:faction` → « Clore définitivement » | Message public en gris, « Sondage clos. », **plus aucun bouton** |
| 6 | `/resultats clé:faction` | Résultats toujours lisibles, « Sondage clos » |
| 7 | `/clore clé:faction` | « Ce sondage est clos » — pas de confirmation proposée |
| 8 | `/sondage clé:faction` | Refusé : un sondage clos ne se réaffiche pas |
| 9 | Réafficher un sondage avant clôture, le clore, cliquer un vote sur **l'ancien** message | « Ce sondage est clos, les votes ne sont plus pris en compte » |
| 10 | `Ctrl-C` pendant qu'une confirmation est ouverte, relancer, cliquer « Clore définitivement » | Le bouton répond encore |

L'étape 9 vérifie que la clôture est étanche en base et pas seulement à
l'écran : seul le dernier message est réécrit, les anciens gardent leurs
boutons, et c'est `handle_vote` qui les rend inoffensifs.

L'étape 10 vérifie la persistance des boutons de confirmation.

Reste ouvert : un sondage clos par erreur ne se rouvre qu'en base. C'était le
choix retenu, la confirmation servant de garde-fou.

**Ce scénario date des boutons de vote.** Les étapes 2, 5 et 9 ne se déroulent
plus tout à fait pareil depuis l'étape 4ter : on vote en réagissant, la clôture
retire les réactions au lieu des boutons, et `handle_vote` n'existe plus — c'est
le gestionnaire de réactions qui écarte un vote sur un sondage clos. Les étapes
1, 3, 4, 6, 7, 8 et 10 restent valables telles quelles ; le scénario de l'étape
4ter couvre le reste.

## Étape 4ter — Vote par réaction

Hors feuille de route initiale, ajoutée le 30 septembre. Les icônes Alliance et
Horde ayant été posées en emojis du serveur, elles deviennent les bulletins
eux-mêmes : on ne clique plus un bouton, on réagit sous le message. Les trois
sondages basculent, et « Peu importe » disparaît de Faction — réagir avec les
deux emojis dit exactement la même chose, en mieux.

Ce que ça change, au-delà de l'apparence :

- **Un vote par personne n'est plus une garantie de schéma.** La clé primaire
  `(poll_id, member_id)` ne pouvait pas représenter deux réactions du même
  membre. Migration 003, reconstruction en `(poll_id, member_id, option_id)`,
  et le choix unique se fait désormais dans le repository, par sondage.
- **Discord ne rejoue jamais un événement de réaction.** Un clic sur un bouton
  échouait visiblement quand le bot était éteint ; une réaction, elle, s'ajoute
  très bien sans lui et reste invisible pour toujours. D'où la réconciliation au
  démarrage, qui relit les réactions et réaligne la base. Le message fait foi.
- **Rien ne peut être répondu au votant.** Pas d'interaction, donc pas
  d'éphémère : le compteur est le seul retour.
- **Un message plafonne à 20 réactions distinctes**, contre 25 boutons.

- [x] `emoji` obligatoire par option, `icon` facultatif nommant un emoji du serveur
- [x] Deux options d'un même sondage ne peuvent pas partager un emoji
- [x] `multiple` par sondage ; activé sur Faction, puis sur Type de royaume
- [x] Migration 003 : plusieurs votes par membre, anciens votes conservés
- [x] `EmojiStore` lit le serveur, puis l'application, puis l'unicode
- [x] Intent `guild_reactions`, non privilégié
- [x] `/sondage` pose les bulletins et vérifie les cinq permissions nécessaires
- [x] Réaction hors menu ou sur sondage clos : retirée
- [x] Choix unique : réagir ailleurs déplace le vote et retire l'ancienne réaction
- [x] Réconciliation au démarrage sur les réactions réellement présentes
- [x] `/clore` retire les réactions au lieu des boutons
- [x] `/sondage` refuse de réafficher un sondage déjà voté et encore affiché
- [ ] **Recette sur le serveur** — voir le scénario ci-dessous

Fini quand : réagir 🔵 sous Faction incrémente Alliance, réagir 🔴 en plus
incrémente Horde sans retirer Alliance, et un redémarrage retrouve les deux.

### Scénario de recette — à dérouler

Le bot a besoin de « Gérer les messages » dans le salon avant de commencer.

| #  | Action | Attendu |
|----|--------|---------|
| 1  | `/sondage clé:faction` | Message posté, **deux** réactions déjà en place : les icônes Alliance et Horde, pas les pastilles |
| 2  | Réagir 🔵 | Alliance passe à 1. **Aucun message** ne répond, c'est normal |
| 3  | Réagir 🔴 en plus | Horde passe à 1 **et Alliance reste à 1** : le multi-vote marche |
| 4  | Retirer 🔵 | Alliance retombe à 0, Horde reste à 1 |
| 5  | Réagir 🍕 | La réaction est retirée par le bot, les compteurs ne bougent pas |
| 6  | `/sondage clé:royaume`, réagir :murloc: | JcE à 1 |
| 7  | Réagir :pvp: en plus | JcJ à 1 **et JcE reste à 1** : ce sondage accepte aussi les deux |
| 8  | `Ctrl-C`, retirer :murloc: pendant l'arrêt, relancer | Au démarrage, JcE est à 0 et JcJ à 1 : la réconciliation a vu la réaction retirée hors ligne |
| 9  | `/sondage clé:faction` | **Refusé** : déjà affiché et déjà voté |
| 10 | `/resultats clé:faction` | Compteurs cohérents avec les réactions du message |
| 11 | `/clore clé:faction` → confirmer | Message en gris, « Sondage clos. », **plus aucune réaction** |
| 12 | Réagir 🔵 sur le sondage clos | La réaction est retirée, le compteur ne bouge pas |
| 13 | Supprimer le message de royaume, `/sondage clé:royaume` | Accepté : il n'y a plus rien à perdre |

L'étape 8 est la décisive : c'est elle qui vérifie la réconciliation, et elle
n'a pas d'équivalent du temps des boutons.

Plus aucun sondage n'est à choix unique : le repository sait encore le faire,
mais seul un sondage à venir le rejouera. L'étape 9 vérifie le garde-fou du
réaffichage, l'étape 13 qu'il ne bloque pas une reprise légitime.

## Étape 5 — Sondage nom de guilde

Vote ouvert avec propositions des membres.

**Le vote par réaction ne convient pas à cette étape** : un message plafonne à
20 réactions distinctes, et un nom proposé par un membre n'a pas d'emoji à lui.
Le vote se fait donc dans un menu déroulant sous le message, à côté des réactions
que gardent les deux autres sondages.

La prévision « la couche base et `/clore` ne bougent pas » était fausse. Ce que
l'étape a réellement changé :

- **Un sondage a désormais deux bulletins possibles.** Un bloc
  `[polls.proposals]` dans `polls.toml` remplace les options configurées et fait
  basculer le sondage sur le menu. `votes_by_reaction` pilote le reste : les
  permissions demandées, le gel à la clôture, et surtout la réconciliation.
- **La réconciliation devait être bornée.** Elle reconstruit les votes depuis les
  réactions du message ; lancée sur un sondage à menu, elle n'aurait trouvé
  aucune réaction et aurait effacé toutes les voix. Elle saute ces sondages.
- **Trois voix par personne, plafonnées par Discord lui-même** : `max_values = 3`
  sur le menu, donc la limite est tenue côté client. `set_votes` remplace d'un
  bloc les voix d'un membre, ce qui est exactement la forme de ce qu'un menu
  soumet — une sélection complète, pas un delta.
- **Les voix ne disent plus la participation**, d'où « 13 voix de 5
  participants » en pied et un `COUNT(DISTINCT member_id)` pour l'obtenir.
- **Dépassement des 25 options : la 26ᵉ proposition est refusée.** Paginer
  cacherait une proposition neuve à ceux qui doivent voter dessus, et trier par
  popularité la rendrait invisible, une proposition neuve étant à zéro voix. Un
  officier retire un nom pour faire de la place.
- **La modale n'est pas persistante** et ne peut pas l'être : elle n'appartient à
  aucun message, donc rien ne peut la reconstruire. C'est le bouton qui l'ouvre
  qui survit au redémarrage ; une modale laissée ouverte pendant un redémarrage
  échoue à l'envoi et coûte un second clic.
- **`TextInput(label=...)` est déprécié depuis discord.py 2.6** au profit de
  `ui.Label`, qui enveloppe le champ et affiche les règles juste en dessous.

- [x] Bouton « Proposer un nom » ouvrant une modale
- [x] Validation : longueur, caractères autorisés, doublons insensibles à la
      casse et aux accents — « Les Loups » et « les loups » ont la même clé
- [x] Limite de propositions par personne : 2, configurable
- [x] Vote sur toutes les options, y compris ajoutées
- [x] Vote par menu propre à ce sondage, 3 voix par personne
- [x] Dépassement de 25 options : proposition refusée, menu plafonné de toute façon
- [x] `/retirer-proposition`, réservée à GM et Officier, l'auteur en autocomplétion
- [ ] **Recette sur le serveur** — voir le scénario ci-dessous

Fini quand : un membre propose un nom, il apparaît, les autres peuvent voter.

### Scénario de recette — à dérouler

Ce sondage ne demande que « Envoyer des messages », « Intégrer des liens » et
« Voir les anciens messages » : rien ne pose de réaction dessus, donc rien n'a
à en retirer.

| #  | Action | Attendu |
|----|--------|---------|
| 1  | `/sondage clé:nom_guilde` | Message posté avec le bouton « Proposer un nom » seul : **pas de menu**, il n'y a rien à voter |
| 2  | « Proposer un nom », écrire « Les Loups de Pierre » | Confirmation en éphémère, le nom apparaît à 0 voix **et le menu apparaît** |
| 3  | Proposer « les loups de pierre » | Refusé : déjà en lice. La casse et les accents ne font pas un nom différent |
| 4  | Proposer « Ab » | Refusé par Discord **avant l'envoi** : le champ exige 3 caractères |
| 5  | Proposer « Nom 2 » | Refusé : pas de chiffre dans un nom de guilde |
| 6  | Proposer un 2ᵉ nom valide, puis tenter un 3ᵉ | Le 3ᵉ est refusé : limite de 2 propositions, les deux déjà proposés sont rappelés |
| 7  | Choisir un nom dans le menu | « Tes voix vont à … », compteur à 1, pied « 1 voix de 1 participant(s) » |
| 8  | Rouvrir le menu, choisir **deux** noms | Les voix sont **remplacées**, pas ajoutées : 2 voix au total pour ce membre |
| 9  | Tenter d'en sélectionner 4 | Impossible : Discord bloque la 4ᵉ sélection, le bot n'est pas sollicité |
| 10 | « Retirer mes voix » | « Tes voix sont retirées », les compteurs retombent |
| 11 | « Retirer mes voix » encore | « Tu n'avais pas encore voté », rien ne bouge |
| 12 | `Ctrl-C`, relancer, voter dans le menu | Le vote marche : le menu est reconstruit depuis son `custom_id`, et la sélection arrive bien dans la charge utile |
| 13 | Comparer les compteurs avant / après ce redémarrage | **Identiques.** C'est le point décisif : la réconciliation ne doit pas avoir touché ce sondage |
| 14 | Réagir avec n'importe quel emoji sous le message | La réaction **reste** : ce sondage ne vote pas par réaction, donc le bot l'ignore au lieu de la retirer |
| 15 | `/retirer-proposition`, choisir un nom qui a des voix | Il disparaît de l'embed et du menu, ses voix avec, et le nombre de voix perdues est annoncé |
| 16 | `/resultats clé:nom_guilde` | Classement cohérent, « N voix de M participant(s) » |
| 17 | `/clore clé:nom_guilde` → confirmer | Message en gris, « Sondage clos. », **plus aucun composant** |
| 18 | Cliquer le menu sur le message clos | Rien n'est enregistré ; si le gel a échoué, « Ce sondage est clos » |
| 19 | `/sondage clé:nom_guilde` | Refusé : un sondage clos ne se réaffiche pas |

Les étapes 12 et 13 sont les décisives, et elles sont indissociables : la
première vérifie que la persistance des composants fonctionne, la seconde qu'elle
ne s'accompagne pas d'un effacement silencieux des voix au démarrage.

L'étape 9 vérifie une limite tenue par Discord, pas par le bot — c'est pour ça
qu'elle vaut d'être vue au moins une fois.

## Étape 6 — Métiers et annuaire

À faire après la sortie du jeu : la liste des métiers n'est pas fiable avant.

- [ ] Migration 002 : table professions
- [ ] Sélection des métiers dans #rôles, avec niveau et notes
- [ ] Attribution des rôles Discord de métier
- [ ] Message d'annuaire dans #métiers, mis à jour automatiquement
- [ ] Gestion du message supprimé et de la limite de caractères d'un embed
- [ ] `/artisan <métier>` pour une recherche rapide

Fini quand : ajouter un métier met l'annuaire à jour sans intervention.

## Avant d'inviter les membres

- [x] Créer un serveur de test et y reproduire la structure
- [ ] Passer les vérifications de permissions avec un second compte
- [ ] Choisir et configurer l'hébergement
- [ ] Sauvegarde automatique de la base
