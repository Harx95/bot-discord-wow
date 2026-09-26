# Bot de guilde — WoW Forever

Bot Discord pour une guilde WoW Forever (sortie du jeu le 4 novembre 2026).
Gère les sondages de pré-lancement, l'attribution des classe, des métiers, des rôles
et un annuaire des métiers.

Feuille de route : ROADMAP.md — ne traite QUE l'étape demandée.

## Stack

- Python 3.12, discord.py 2.x
- aiosqlite (SQL brut, pas d'ORM)
- pydantic : configuration et définitions de sondages UNIQUEMENT
- pyright (mode standard), ruff (lint + format)
- Pas de nouvelle dépendance sans me demander.

## Architecture

- `src/bot/` — cogs et vues discord.py
- `src/db/` — repositories, un par agrégat
- `src/domain/` — dataclasses frozen, aucune dépendance à discord.py
- `migrations/` — SQL versionné, seul endroit où du DDL est autorisé

Règles :
- Les entités du domaine sont des `@dataclass(frozen=True, slots=True)`,
  jamais des modèles pydantic.
- Le SQL vit dans les repositories. Aucune requête ailleurs.
- Les cogs ne parlent jamais à la base directement, ils passent par un repository.

## Contraintes discord.py

- Toute interaction dépassant 2 s doit être `defer()` en premier.
- Les vues sont persistantes : `timeout=None`, `custom_id` stable et préfixé,
  aucun état conservé en mémoire. Elles doivent survivre à un redémarrage.
- Narrowing explicite avant d'accéder aux attributs de `Member` :
  `interaction.user` est `User | Member`.
- Vérifier `interaction.guild is not None` avant usage.
- Réponses d'erreur toujours en `ephemeral=True`.

Limites de l'API à respecter, elles sont souvent frôlées ici :
- menu déroulant : 25 options maximum
- libellé d'option : 100 caractères
- description de commande : 100 caractères
- embed : 6000 caractères au total, 25 champs

## Contexte Discord

Serveur de la guilde, développement direct dessus (pas encore de membres).
`GUILD_ID` sert à synchroniser les commandes instantanément.

Rôles, du plus haut au plus bas :
1. rôle du bot
2. GM
3. Officier
4. Membre

Personne n'a deux rôles à la fois : un officier n'a PAS le rôle Membre.
Une vérification de permission teste donc l'appartenance à GM ou Officier,
jamais l'absence de Membre.

Le rôle du bot doit rester au-dessus des rôles qu'il attribue
(classes, métiers). Toujours vérifier la hiérarchie avant un `add_roles`.

Salons : annonces, sondages, calendrier-raid, stratégies-raid,
rôles, métiers, général. Seuls GM et Officier y écrivent, sauf général.

## Contexte du jeu

WoW Forever, niveau maximum 60, base Vanilla.
Les 9 classes sont disponibles dans les DEUX factions.
Race payante : Skyborne (pas de Paladin).
Types de royaume : Normal, JcJ, Roleplay.

Ne jamais coder en dur une liste de classes, races ou métiers :
tout passe par la configuration, le jeu n'est pas encore sorti.

## Conventions

- Tout ce que voit l'utilisateur est en français : commandes, libellés, erreurs.
- Code, noms de variables, commentaires et commits en anglais.
- Annotations de types partout, y compris les retours `-> None`.
- Jamais de secret en dur : tout passe par `.env` et l'objet `Settings`.

## Méthode de travail

- Une étape de ROADMAP.md à la fois. Ne pas anticiper les suivantes.
- Proposer un plan avant toute modification touchant plus de 3 fichiers.
- Vérifier la documentation officielle de discord.py avant d'utiliser
  un composant : l'API Discord évolue vite.
- Commit à la fin de chaque étape validée, message en anglais.
