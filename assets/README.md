# Icônes

Images utilisées pour les emojis du bot. Elles ne sont pas fournies : ce sont des
icônes de jeu, à récupérer toi-même.

## Où les déposer

```
assets/classes/<clé>.png   guerrier, paladin, chasseur, voleur, pretre,
                           chaman, mage, demoniste, druide
assets/roles/<clé>.png     tank, heal, dps
```

Les clés doivent correspondre exactement à celles de `classes.toml`.

## Contraintes Discord

- PNG, JPEG ou GIF
- **256 Ko maximum** par fichier
- 128×128 suffit largement, Discord affiche en 22×22

## Envoi

`/emojis` les envoie comme emojis d'application. Ils n'occupent aucun des
emplacements d'emoji du serveur et fonctionnent partout où le bot est invité.
La commande est idempotente : relancée, elle n'envoie que ce qui manque.

Tant qu'une icône est absente, le bot utilise l'emoji unicode de repli défini
dans `classes.toml`.
