# bot-discord-wow

Bot Discord de guilde pour WoW Forever.

## Installation

```sh
python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # puis renseigner DISCORD_TOKEN et GUILD_ID
```

## Lancement

```sh
.venv/bin/python -m bot
```

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
