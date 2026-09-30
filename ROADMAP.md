# Feuille de route — Bot de guilde

Une étape à la fois. Ne pas anticiper les suivantes.
Chaque étape se termine par : test manuel réussi, puis commit, puis rendu d'explication technique court et concis.

## Où on en est — 30 septembre 2026

Étapes 1 à 4 terminées, testées sur le serveur et commitées.
**Prochaine étape : la 5**, le sondage du nom de guilde. Elle amène les modales,
sur lesquelles se greffera la commande de création de sondage à la volée.

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
- Aucun emoji d'application n'est encore envoyé.

### Manques connus, dans aucune étape

- **Rien ne clôture un sondage.** `PollRepo.close()` existe et est testée, mais
  aucune commande ne l'appelle. La contrainte de calendrier ci-dessous impose une
  clôture avant le 25 octobre : il faut une commande quelque part avant.
- **Ajouter une option à un sondage déjà ouvert** ne l'ajoute pas en base : les
  options sont copiées à la création. Il faut supprimer le sondage et le rouvrir.
- **Aucune commande d'officier n'efface les choix de quelqu'un d'autre.** Chacun
  défait les siens en recliquant. `ClassRepo.clear_choices()` est écrite et
  testée : il ne manque que la commande qui l'appelle, si le besoin se présente.

## Contrainte de calendrier

- Bêta WoW Forever : jusqu'au 21 octobre 2026
- Réservation des noms : 27 octobre – 3 novembre
- Sortie : 4 novembre

Les sondages Faction, Type de royaume et Nom de guilde doivent être
clos avant le 25 octobre : on ne peut pas réserver un nom sans avoir
tranché la faction et le royaume.
Les étapes 1 à 5 sont donc prioritaires. L'étape 6 peut attendre la sortie.

## Questions ouvertes

- Hébergement final : VPS, Raspberry Pi ou plateforme ? (avant l'étape 5)

## Décisions prises

- **Création de sondages depuis Discord** : approche mixte retenue. `polls.toml`
  reste la source des sondages structurants d'avant-lancement (faction, royaume,
  Skyborne), dont les clés sont inscrites en base et dans les boutons. Une
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

## Étape 5 — Sondage nom de guilde

Vote ouvert avec propositions des membres.

- [ ] Bouton « Proposer un nom » ouvrant une modale
- [ ] Validation : longueur, doublons, caractères autorisés
- [ ] Limite de propositions par personne
- [ ] Vote sur toutes les options, y compris ajoutées
- [ ] Gestion du dépassement de 25 options (pagination ou tri)
- [ ] Un officier peut supprimer une proposition

Fini quand : un membre propose un nom, il apparaît, les autres peuvent voter.

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

- [ ] Créer un serveur de test et y reproduire la structure
- [ ] Passer les vérifications de permissions avec un second compte
- [ ] Choisir et configurer l'hébergement
- [ ] Sauvegarde automatique de la base
