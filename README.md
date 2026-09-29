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
