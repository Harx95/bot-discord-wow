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
