# Feuille de route — Bot de guilde

Une étape à la fois. Ne pas anticiper les suivantes.
Chaque étape se termine par : test manuel réussi, puis commit, puis rendu d'explication technique court et concis.

## Où on en est — 29 septembre 2026

Étapes 1 à 3 terminées, testées et commitées.
**Étape 4 écrite et commitée, mais PAS encore testée manuellement** : c'est la
première chose à faire à la reprise. Le scénario est en bas de ce fichier.

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
- **`assets/classes/*.png` et `assets/roles/*.png`** — les icônes de classe, à
  déposer de nouveau. Voir `assets/README.md`. Sans elles le bot utilise les
  emojis unicode de repli de `classes.toml` : rien ne casse.

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

## Étape 4 — Sondage classe et rôle

Le plus délicat : combos, boutons, attribution de rôle.

Énoncé révisé en cours d'étape : les menus déroulants sont devenus des boutons,
et le couple « principal + rerolls » un classement par préférence.

- [ ] Boutons de classe, puis boutons de rôle filtrés selon la classe
- [ ] Trois choix classés par préférence, dans member_choices
- [ ] Le choix ① donne le rôle Discord, les suivants ne changent pas la couleur
- [ ] Bouton « Recommencer » pour tout réinitialiser
- [ ] Icônes de classe et de rôle en emojis d'application, via `/emojis`
- [ ] Création des rôles Discord de classe, colorés, non séparés
- [ ] Récupération d'un rôle existant de même nom, sans doublon
- [ ] Vérification de la hiérarchie avant `add_roles`, message clair si échec
- [ ] `/composition` : répartition tanks / heals / dps
- [ ] `/annuaire` : message public tenu à jour à chaque déclaration

Fini quand : voter mage donne le rôle Mage et le pseudo devient bleu clair.

### Test manuel à faire à la reprise

Déposer d'abord les icônes dans `assets/`, puis lancer le bot.

| # | Action | Attendu |
|---|---|---|
| 1 | `/emojis` | « Envoyées (12) », ou la liste de ce qui manque |
| 2 | `/roles-classes` | **« Récupérés (9) »**, pas « Créés » : les rôles existent déjà |
| 3 | `/classes` dans #rôles | 9 classes en colonnes, 9 boutons + « Recommencer » |
| 4 | `/annuaire` | Annuaire vide posté |
| 5 | Bouton Mage → DPS | « Choix n° ① », pseudo bleu clair, annuaire mis à jour |
| 6 | Bouton Druide → Tank | « Choix n° ② », pseudo **toujours** bleu clair |
| 7 | Bouton Prêtre → Soigneur | « Choix n° ③ » |
| 8 | Un 4ᵉ choix | « Tu as déjà fait tes 3 choix » |
| 9 | « Recommencer » | Choix effacés, couleur retirée, annuaire vidé |
| 10 | `/composition` | Répartition, choix suivants comptés à part |
| 11 | `Ctrl-C`, relancer, recliquer | Les boutons répondent encore |

L'étape 11 est le test décisif : rien n'est gardé en mémoire, chaque bouton est
reconstruit depuis le `custom_id` inscrit dans le message.

Une fois validé : cocher les cases ci-dessus, puis commit.

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
