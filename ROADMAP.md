# Feuille de route — Bot de guilde

Une étape à la fois. Ne pas anticiper les suivantes.
Chaque étape se termine par : test manuel réussi, puis commit, puis rendu d'explication technique court et concis.

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

---

## Étape 1 — Squelette

Le bot démarre, se connecte, répond à une commande.

- [ ] Arborescence du projet, `pyproject.toml`, dépendances
- [ ] Chargement de la configuration via pydantic-settings et `.env`
- [ ] Connexion du bot, intents minimaux (members activé)
- [ ] Synchronisation des commandes sur `GUILD_ID` au démarrage
- [ ] Commande `/ping` qui répond « Pong »
- [ ] Journalisation lisible dans la console
- [ ] ruff et pyright configurés, aucune erreur

Fini quand : `python -m bot` démarre et `/ping` répond sur le serveur.

## Étape 2 — Base de données

Le schéma et la couche d'accès, sans aucune commande Discord.

- [ ] Module de migrations : lit `migrations/*.sql`, applique celles qui manquent
- [ ] Migration 001 : tables members, polls, poll_options, poll_votes
- [ ] Dataclasses du domaine correspondantes
- [ ] `MemberRepo` et `PollRepo` avec leurs méthodes de base
- [ ] Tests unitaires des repositories sur une base temporaire

Fini quand : les tests passent, et relancer le bot ne rejoue pas les migrations.

## Étape 3 — Sondages simples

Les trois sondages à choix limité, sans propositions ni combos.

- [ ] Définition des sondages en configuration, validée par pydantic
- [ ] Commande `/sondage <clé>`, réservée à GM et Officier
- [ ] Vue persistante à boutons, `custom_id` stables
- [ ] Un vote par personne, modifiable, stocké en base
- [ ] Le message affiche les compteurs en direct
- [ ] Commande `/resultats <clé>`, réservée à GM et Officier
- [ ] Sondages : faction, type de royaume, pack Skyborne

Fini quand : le bot redémarre en plein sondage et les boutons fonctionnent encore.

## Étape 4 — Sondage classe et rôle

Le plus délicat : combos, menus déroulants, attribution de rôle.

- [ ] Menu déroulant classe, puis menu rôle filtré selon la classe
- [ ] Choix principal unique, enregistré dans members
- [ ] Choix secondaires multiples, dans member_classes
- [ ] Création des rôles Discord de classe, colorés, non séparés
- [ ] Attribution automatique du rôle de classe au vote
- [ ] Vérification de la hiérarchie avant `add_roles`, message clair si échec
- [ ] `/composition` : répartition tanks / heals / dps

Fini quand : voter mage donne le rôle Mage et le pseudo devient bleu clair.

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
