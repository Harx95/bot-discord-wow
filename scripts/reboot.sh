#!/usr/bin/env bash
# Redemarre le bot sur le VPS, et montre assez du journal pour savoir s'il est revenu.
#
# A lancer SUR LE VPS, depuis n'importe quel repertoire :
#
#   ./scripts/reboot.sh             # redemarre seulement
#   ./scripts/reboot.sh --update    # git pull, puis redemarre
#
# Le nom du service se surcharge : BOT_SERVICE=autre.service ./scripts/reboot.sh
#
# Le service tourne avec Restart=always : un bot qui refuse de demarrer est donc
# relance sans fin, et "systemctl restart" rend la main sans erreur. Ce script
# compte les relances pour le dire, au lieu de laisser croire que tout va bien.

set -euo pipefail

SERVICE="${BOT_SERVICE:-bot-wow.service}"
LOG_LINES="${BOT_LOG_LINES:-30}"
SETTLE_SECONDS="${BOT_SETTLE_SECONDS:-6}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Les reglages sans valeur par defaut : le bot refuse de demarrer s'il en manque un.
REQUIRED_SETTINGS=(
    DISCORD_TOKEN
    GUILD_ID
    GM_ROLE_ID
    OFFICER_ROLE_ID
    BLIZZARD_CLIENT_ID
    BLIZZARD_CLIENT_SECRET
)

die() {
    echo "ERREUR : $*" >&2
    exit 1
}

update=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        -u | --update) update=true ;;
        -h | --help)
            # Les lignes de commentaire de l'en-tete, sans leur diese.
            sed -n '2,20p' "${BASH_SOURCE[0]}" | grep '^#' | sed 's/^#[[:space:]]\{0,1\}//'
            exit 0
            ;;
        *) die "option inconnue : $1 (voir --help)" ;;
    esac
    shift
done

command -v systemctl >/dev/null 2>&1 ||
    die "systemctl est introuvable. Ce script s'execute sur le VPS, pas en local."
systemctl cat "$SERVICE" >/dev/null 2>&1 ||
    die "service $SERVICE inconnu. Donne le bon nom : BOT_SERVICE=... $0"

# Le service tourne sous l'utilisateur du depot, mais le redemarrer reste une
# action systeme : sudo seulement quand on n'est pas deja root.
sudo=""
[[ $EUID -eq 0 ]] || sudo="sudo"

if $update; then
    echo "== Mise a jour du depot ($REPO)"
    before="$(git -C "$REPO" rev-parse --short HEAD)"
    # --ff-only : une divergence locale doit etre vue, pas fusionnee en silence.
    git -C "$REPO" pull --ff-only
    after="$(git -C "$REPO" rev-parse --short HEAD)"
    if [[ "$before" == "$after" ]]; then
        echo "Deja a jour ($after)."
    else
        echo "$before -> $after"
        git -C "$REPO" --no-pager log --oneline "$before..$after"
    fi
    echo
fi

if [[ -f "$REPO/.env" ]]; then
    missing=()
    for name in "${REQUIRED_SETTINGS[@]}"; do
        grep -qE "^[[:space:]]*${name}=[^[:space:]]" "$REPO/.env" || missing+=("$name")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        die "il manque dans $REPO/.env : ${missing[*]}"
    fi
else
    die "aucun .env dans $REPO : le bot ne peut pas demarrer."
fi

restarts_before="$(systemctl show -p NRestarts --value "$SERVICE" 2>/dev/null || echo 0)"

echo "== Redemarrage de $SERVICE"
$sudo systemctl restart "$SERVICE"

echo "== Attente de ${SETTLE_SECONDS}s pour voir s'il tient"
sleep "$SETTLE_SECONDS"

restarts_after="$(systemctl show -p NRestarts --value "$SERVICE" 2>/dev/null || echo 0)"
echo
journalctl -u "$SERVICE" -n "$LOG_LINES" --no-pager
echo

if ! systemctl is-active --quiet "$SERVICE"; then
    die "$SERVICE n'est pas actif. Le journal ci-dessus dit pourquoi."
fi

if [[ "$restarts_after" -gt "$restarts_before" ]]; then
    die "$SERVICE redemarre en boucle ($restarts_before -> $restarts_after relances).
Le bot plante au demarrage ; le journal ci-dessus porte la vraie erreur."
fi

echo "OK : $SERVICE tourne. Verifie dans le journal les lignes"
echo "  'Connected as', 'Daily profession sync scheduled' et 'Synced N command(s)'."
