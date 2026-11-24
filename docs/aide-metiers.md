# 🛠️ Les métiers de la guilde

Les messages au-dessus listent, métier par métier, qui sait quoi et à quelle compétence. Tout vient directement du jeu : personne n'a rien à déclarer. **Mis à jour automatiquement chaque jour à 5 h.**

Le salon est en lecture seule, mais **deux commandes y sont à toi**. Tape `/` dans la barre de message pour les voir.

## `/qui-métier` — qui peut fabriquer cet objet

```
/qui-métier objet: Cape élégante en cuir
/qui-métier objet: Fine Leather Cloak
```

- **Français ou anglais**, même réponse.
- Les accents et les majuscules ne comptent pas.
- Un morceau de nom suffit : `cuir estampé` marche, `potion` aussi — mais répond large.
- La recherche porte sur le nom de la recette **et** sur celui de l'objet fabriqué.

## `/recettes` — tout ce qu'un artisan sait faire

```
/recettes personnage: Ezrym-Avelorn métier: Travail du cuir
```

Les deux champs se complètent tout seuls : commence à taper, puis choisis dans la liste. Le second ne propose que **les métiers de ce personnage-là**.

## À savoir

- **Les réponses n'arrivent qu'à toi**, personne d'autre ne les voit jamais. Elles ne restent pas dans le salon : elles disparaissent dès que tu recharges Discord, et tout de suite si tu cliques sur **Supprimer le message**.
- **Cuisine, Secourisme et Pêche ne sont pas suivis** : presque tout le monde les a, et ils noyaient les vraies réponses.
- Un personnage **sous le niveau 10** est invisible pour l'API de Blizzard. Un métier monté depuis ta dernière déconnexion n'apparaît qu'à la synchro suivante.
- Un trou, une bizarrerie ? Préviens un officier : `/synchro-métiers` relit tout immédiatement.
