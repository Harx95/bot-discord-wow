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
| `/resultats <clé>` | GM, Officier | Résultats classés, visibles par la seule personne qui demande |

Un vote par personne, modifiable à tout moment. Les compteurs sont mis à jour
dans le message à chaque vote ; les noms des votants ne sont jamais affichés.

Changer la clé d'un sondage déjà ouvert le détache de ses votes : la clé est
l'identifiant stocké en base et inscrit dans les boutons.

Ajouter une option à un sondage **déjà ouvert** ne l'ajoute pas en base : les
options sont copiées à la création. Il faut supprimer le sondage et le rouvrir.

## Classes et rôles

Les classes, leurs couleurs et les rôles qu'elles peuvent tenir sont dans
`classes.toml`, validé au démarrage.

| Commande | Qui | Effet |
|---|---|---|
| `/roles-classes` | GM, Officier | Crée les rôles Discord de classe manquants |
| `/classes` | GM, Officier | Poste le message de sélection dans le salon courant |
| `/composition` | GM, Officier | Répartition tank / soigneur / DPS |

Lancer `/roles-classes` **avant** `/classes`, sinon les membres déclarent leur
classe sans recevoir la couleur correspondante.

Seule la classe principale donne un rôle Discord : deux rôles de classe
rendraient la couleur du pseudo dépendante de leur ordre dans la hiérarchie.
Les rerolls sont enregistrés en base et comptés dans `/composition`.

Le bot ne peut attribuer que des rôles situés **sous** le sien dans la
hiérarchie. Les rôles de classe sont créés tout en bas, donc c'est acquis ;
en revanche il ne peut pas attribuer Membre, Officier ni Maître de guilde.
