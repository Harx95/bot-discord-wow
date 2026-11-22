# bot-discord-wow

Bot Discord de la guilde **Ah sheep here wego again** (ASHWGA) sur WoW Forever,
ruleset JcJ, region Europe.

## Installation

```sh
python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
```

Puis remplir `.env`. Trois valeurs n'ont pas de défaut et sont à récupérer sur
leurs portails — `DISCORD_TOKEN`, `BLIZZARD_CLIENT_ID` et
`BLIZZARD_CLIENT_SECRET` : le bot refuse de démarrer s'il en manque une, avec
une erreur de validation qui les nomme. Les identifiants du serveur
(`GUILD_ID`, `GM_ROLE_ID`, `OFFICER_ROLE_ID`) sont dans `ROADMAP.md`.

Les deux identifiants Battle.net se créent sur
[develop.battle.net](https://develop.battle.net) : un client de type
`client_credentials`, sans URL de redirection.

## Lancement

```sh
.venv/bin/python -m bot
```

## Déploiement

Le bot tourne sur un VPS Debian, en service systemd `bot-wow.service`. Tout le
déploiement tient en une commande, **à lancer sur le VPS** :

```sh
./scripts/reboot.sh --update   # git pull, vérifie le .env, redémarre, montre le journal
./scripts/reboot.sh            # redémarre seulement
```

Le service porte `Restart=always` : un bot qui refuse de démarrer est relancé
sans fin, et `systemctl restart` rend la main sans erreur. Le script compte donc
les relances pendant quelques secondes et le dit, au lieu d'annoncer un succès.
Il vérifie aussi que les réglages obligatoires sont présents dans le `.env` de la
machine — qui n'est pas dans le dépôt — avant de toucher au service.

Le nom du service se surcharge : `BOT_SERVICE=autre.service ./scripts/reboot.sh`.

## Vérifications

```sh
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/pyright
.venv/bin/pytest
```

## Base de données

SQLite, chemin dans `DATABASE_PATH` (`data/bot.db` par défaut). Le schéma est
versionné dans `migrations/` : chaque fichier `.sql` est appliqué une seule fois,
par ordre de nom, et enregistré dans `schema_migrations`. Les migrations sont
jouées au démarrage du bot.

Pour modifier le schéma, ajouter un fichier `migrations/00X_description.sql` —
ne jamais éditer une migration déjà appliquée.

## Sondages

Les sondages sont définis dans `polls.toml`, validé au démarrage : une erreur de
configuration empêche le bot de se lancer plutôt que de casser une commande.

| Commande | Qui | Effet |
|---|---|---|
| `/sondage <clé>` | GM, Officier | Ouvre le sondage dans le salon courant, ou le réaffiche s'il existe déjà |
| `/clore <clé>` | GM, Officier | Clôt le sondage, après confirmation |
| `/resultats <clé>` | GM, Officier | Résultats classés, visibles par la seule personne qui demande |

### Voter

**On vote en réagissant.** Le bot pose lui-même une réaction par option sous le
message : ce sont les bulletins, il suffit de cliquer dessus. Recliquer retire
son vote. Les compteurs se mettent à jour dans le message ; les noms des votants
ne sont jamais affichés.

Un sondage accepte un seul choix par personne, sauf s'il porte `multiple = true`
dans `polls.toml` — c'est le cas de Faction, où réagir avec les deux emojis dit
que les deux conviennent. Sur un sondage à choix unique, réagir ailleurs déplace
le vote et le bot retire l'ancienne réaction.

Une réaction qui n'est pas au menu est retirée, de même qu'une réaction sur un
sondage clos. Il faut donc « Gérer les messages » au bot, en plus de « Ajouter
des réactions » et « Voir les anciens messages » ; `/sondage` vérifie tout ça
avant d'écrire quoi que ce soit et dit précisément ce qui manque.

Une réaction ne passe pas par une interaction : le bot ne peut donc **rien
répondre** au votant, pas même un message éphémère. Le compteur du message est
le seul accusé de réception.

Discord ne rejoue jamais un événement de réaction. Une réaction posée pendant
que le bot est éteint serait donc invisible pour toujours : au démarrage, le bot
relit les réactions de chaque sondage ouvert et réaligne la base dessus. Le
message fait foi, pas la base.

### Limites à connaître

Un message plafonne à **20 réactions distinctes**, ce qui plafonne un sondage à
20 options — et non 25 comme les boutons le permettaient.

`/sondage` sur un sondage déjà affiché et déjà voté est **refusé** : les votes
vivent sous forme de réactions sur le message en cours, un second message
repartirait d'une urne vide et la réconciliation suivante effacerait les
compteurs. Le réaffichage reste possible tant que personne n'a voté, ou si le
message a disparu.

`/clore <clé>` ferme un sondage après confirmation : les résultats s'affichent
avant d'agir, puis le message passe en gris et ses réactions sont retirées.
C'est définitif, il n'y a pas de réouverture. La clôture vaut en base, donc une
réaction reposée sur un ancien message est retirée elle aussi.

Changer la clé d'un sondage déjà ouvert le détache de ses votes : la clé est
l'identifiant stocké en base.

Ajouter une option à un sondage **déjà ouvert** ne l'ajoute pas en base : les
options sont copiées à la création. Il faut supprimer le sondage et le rouvrir.

### Emojis d'un sondage

Chaque option porte un `emoji` unicode obligatoire — c'est le bulletin, donc
deux options d'un même sondage ne peuvent pas partager le même. Un champ `icon`
facultatif nomme un emoji du serveur à utiliser à la place ; tant qu'il n'existe
pas, l'unicode sert de repli et le sondage reste votable.

Les emojis personnalisés sont appariés **par leur nom**, pas par leur
identifiant : réenvoyer une icône sur le serveur ne détache donc aucun vote.

## Classes et rôles

Les classes, leurs couleurs et les rôles qu'elles peuvent tenir sont dans
`classes.toml`, validé au démarrage.

| Commande | Qui | Effet |
|---|---|---|
| `/emojis` | GM, Officier | Envoie les icônes de `assets/` comme emojis du bot |
| `/roles-classes` | GM, Officier | Crée les rôles Discord de classe manquants |
| `/classes` | GM, Officier | Poste les deux messages de déclaration dans le salon courant |
| `/composition` | GM, Officier | Répartition tank / soigneur / DPS |

Lancer `/roles-classes` **avant** `/classes`, sinon les membres déclarent leur
classe sans recevoir la couleur correspondante.

Le bot cherche une icône d'abord parmi les emojis **du serveur**, puis parmi les
emojis **de son application**, et retombe sur l'unicode de la configuration s'il
ne trouve rien. Une icône ajoutée à la main sur le serveur suffit donc, et
`/emojis` devient facultative : elle sert à envoyer les icônes de `assets/` à
l'application quand on préfère ne pas consommer les 50 emplacements du serveur.

`/classes` poste **deux** messages, tenus à jour à chaque clic :

- **Ta classe au lancement** — le personnage principal, un seul par personne.
- **Autres classes envisagées au lancement** — les autres classes auxquelles la
  personne réfléchit pour son personnage principal, sans avoir tranché : jusqu'à
  `max_choices - 1`, sans ordre entre elles.

Chacun range les pseudos en trois colonnes tank / soigneur / DPS, l'icône de la
classe devant le nom, et porte un bouton par classe avec son icône et son nom.

Les boutons restent gris pour tout le monde. Le style d'un bouton fait partie du
message, et un message de salon est identique pour tous : un bouton bleu y
montrerait le dernier qui a cliqué, pas la personne qui regarde. Le retour
visuel, ce sont les colonnes juste au-dessus, où un pseudo entre et sort en
direct.

Cliquer une classe la déclare, recliquer dessus la retire. Sur le premier
message, cliquer une autre classe remplace la principale. Sur le second, une
classe déjà déclarée comme principale est refusée, de même qu'une troisième
quand les deux places sont prises — et ces refus tombent **avant** la question du
rôle, pour ne pas la poser pour rien. Quand une classe ne peut tenir qu'un seul
rôle, elle n'est pas posée non plus.

Un clic n'envoie qu'un seul message éphémère : la question du rôle, une erreur ou
une confirmation. La question du rôle se transforme en confirmation plutôt que
d'en empiler une seconde, et tout message terminal s'efface après 30 secondes.

Le créneau dont vient le clic est inscrit dans le `custom_id`, donc la même
classe ne veut pas dire la même chose selon le message.

Seule la classe principale donne un rôle Discord : deux rôles de classe
rendraient la couleur du pseudo dépendante de leur ordre dans la hiérarchie.
Les classes envisagées sont enregistrées en base et comptées à part dans
`/composition`.

Le bot ne peut attribuer que des rôles situés **sous** le sien dans la
hiérarchie. Les rôles de classe sont créés tout en bas, donc c'est acquis ;
en revanche il ne peut pas attribuer Membre, Officier ni Maître de guilde.

## Métiers

Les métiers viennent de l'**API Battle.net**, pas d'une déclaration : personne ne
saisit quoi que ce soit. Une synchro quotidienne lit le roster de la guilde, les
métiers de chaque personnage et les recettes qu'il connaît, puis écrit tout en
base. Les commandes ne lisent que la base et n'appellent jamais Blizzard.

Les métiers suivis, leur nom français, leur emoji et leur ordre d'affichage sont
dans `professions.toml`, validé au démarrage.

| Commande | Qui | Effet |
|---|---|---|
| `/synchro-métiers` | GM, Officier | Force une synchro immédiate et rend un compte-rendu |
| `/annuaire-métiers` | GM, Officier | Poste ou met à jour l'annuaire dans le salon des métiers |
| `/qui-métier <objet>` | Tout le monde | Qui peut fabriquer cet objet, en français ou en anglais |
| `/recettes <personnage> <métier>` | Tout le monde | Toutes les recettes apprises par ce personnage dans ce métier |

### L'annuaire

`PROFESSIONS_CHANNEL_ID` désigne le salon. L'annuaire y tient **un message par
métier suivi**, posté une fois puis édité — jamais reposté, pour que l'ordre des
messages ne change pas d'un jour à l'autre. Un métier que personne n'exerce reste
affiché, vide, pour la même raison.

La réécriture espace les éditions d'environ une seconde : Discord plafonne vers 5
éditions par 5 secondes et par salon. Un message supprimé à la main est oublié en
base, et `/annuaire-métiers` le repose.

La synchro automatique part tous les jours à l'heure de `PROFESSION_SYNC_HOUR`
(5 h par défaut), **heure de Paris**, changement d'heure compris.

### Les deux commandes de membre

Elles ne répondent que dans le salon des métiers, et toujours en **éphémère** :
c'est ce qui permet de laisser les membres les lancer là sans pouvoir y écrire,
sans qu'ils voient les recherches des autres. Il faut donc, dans ce salon :
refuser « Envoyer des messages » à `@everyone` et lui autoriser « Utiliser les
commandes d'application ».

`/qui-métier` cherche sur le nom de la recette **et** sur celui de l'objet
fabriqué, dans les deux langues, sans tenir compte des accents ni de la casse, et
sur un morceau de nom suffit. Les réponses sont groupées par recette, car une
recherche vague en touche souvent plusieurs. Deux recettes qui portent le même nom
sont fusionnées : les métiers de récolte ont une pseudo-recette par palier, toutes
nommées pareil.

Quand personne ne peut fabriquer l'objet, la réponse distingue deux cas : un nom
qu'aucune recette ne porte, et une recette que la guilde connaissait mais que plus
personne ne sait faire — la personne est partie, ou son métier n'est pas suivi.

`/recettes` propose les personnages en autocomplétion, puis **les métiers de ce
personnage-là**. Une liste trop longue se poursuit sur plusieurs embeds du même
message ; les 6000 caractères d'un message sont partagés par tous ses embeds, pas
accordés à chacun, donc la liste est budgétée une fois et le pied annonce ce qui
manque.

### Les noms de recettes

Le profil d'un personnage répond **toujours en anglais**, même en demandant
`locale=fr_FR`. Le français vient d'un second appel, aux données statiques, qui
rend le nom en douze langues.

Un nom de recette ne changeant jamais, la table `recipes` est un dictionnaire
permanent : la synchro ne demande que les identifiants jamais vus. Le premier
jour coûte donc quelques centaines de requêtes, les suivants une vingtaine. Une
recette non encore traduite reste affichée et trouvable sous son nom anglais.

### Métiers non suivis

Cuisine, Secourisme et Pêche portent `ignored = true` dans `professions.toml` :
rien à leur sujet n'entre en base, l'annuaire ne les montre pas et la recherche ne
les voit pas. Presque tout le monde les a, et elles noyaient les vraies réponses —
« bandage en lin » répondait 18 des 25 personnages.

C'est une liste d'exclusion, pas une liste d'inclusion : un métier que Blizzard
ajouterait remonterait quand même, sous son nom anglais et avec un avertissement
au journal pour qu'on complète le fichier.

### Limites de l'API

L'API ne publie un personnage qu'**à partir du niveau 10**, et seulement après une
déconnexion : un personnage frais apparaît au roster sans métier, et le
compte-rendu de synchro le compte comme ignoré. Le namespace `forever` n'est pas
documenté : les contrats ont été mesurés sur la guilde et peuvent changer sans
préavis. Une synchro ratée laisse la base dans l'état de la veille plutôt que de
la vider.
