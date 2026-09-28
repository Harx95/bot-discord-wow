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
.venv/bin/ruff check src
.venv/bin/ruff format --check src
.venv/bin/pyright
```
