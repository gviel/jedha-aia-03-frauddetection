#!/usr/bin/env bash
set -euo pipefail

# Pause/relance/statut des DAGs de la stack Airflow en cours (docker-compose.yml).
# Ne démarre/arrête pas la stack elle-même (cf. start.sh/stop.sh) : juste un toggle
# sur l'état "is_paused".
#
# "all" = tous les DAGs que le scheduler a actuellement chargés, sans filtrer par nom :
# cette stack (LocalExecutor, un seul docker-compose) ne sert que les DAGs de ce projet
# (dags/dag_*.py), donc pas besoin de reconnaître des dag_id précis — et ça reste valide
# même si un dag_id est renommé (cf. refactor "renommer les DAGs Airflow selon specs.md").

usage() {
    cat <<EOF
Usage: $(basename "$0") <pause|unpause|status> [dag_id|all]

  pause   <dag_id|all>   Met en pause un DAG (ou tous les DAGs chargés si "all"/omis)
  unpause <dag_id|all>   Réactive un DAG (ou tous les DAGs chargés si "all"/omis)
  status  [dag_id|all]   Affiche l'état pause/actif (tous par défaut)
EOF
    exit 1
}

[ $# -ge 1 ] || usage
ACTION="$1"
TARGET="${2:-all}"

case "$ACTION" in
    pause|unpause|status) ;;
    *) usage ;;
esac

# Nom du conteneur scheduler variable selon docker-compose v1 (project_service_1)
# ou v2 (project-service-1) — on le retrouve dynamiquement plutôt que de le figer.
SCHEDULER_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E 'airflow.*scheduler' | head -1)"
if [ -z "$SCHEDULER_CONTAINER" ]; then
    echo "ERREUR : conteneur airflow-scheduler introuvable (stack Airflow arrêtée ? cf. ./start.sh)" >&2
    exit 1
fi

run_airflow() {
    docker exec "$SCHEDULER_CONTAINER" airflow "$@"
}

raw_list() {
    run_airflow dags list 2>/dev/null | grep -v '^\[info\|^==='
}

list_raw() {
    raw_list | grep -v '^dag_id '
}

project_dags() {
    list_raw | awk -F'|' '{gsub(/^ +| +$/,"",$1); print $1}' | sort -u
}

# Affiche l'en-tête de colonnes puis les lignes correspondant aux DAGs demandés —
# l'en-tête n'est imprimée que s'il y a au moins un résultat, pour ne pas l'afficher
# devant une sortie vide (dag_id inconnu, filtre qui ne matche rien).
print_statuses() {
    local -a targets=("$@")
    local joined regex all rows
    joined="$(IFS='|'; echo "${targets[*]}")"
    regex="^(${joined})[[:space:]]"
    all="$(raw_list)"
    rows="$(echo "$all" | grep -E "$regex" || true)"
    if [ -n "$rows" ]; then
        local header
        header="$(echo "$all" | grep -E '^dag_id ')"
        echo "$header"
        echo "$header" | sed -E 's/[^|]/-/g; s/\|/+/g'
        echo "$rows"
    fi
}

if [ "$TARGET" = "all" ]; then
    mapfile -t TARGETS < <(project_dags)
    if [ ${#TARGETS[@]} -eq 0 ]; then
        echo "ERREUR : aucun DAG trouvé (stack pas encore prête ? dags-folder pas encore scanné ?)" >&2
        exit 1
    fi
else
    if ! project_dags | grep -qx "$TARGET"; then
        echo "AVERTISSEMENT : \"$TARGET\" n'apparaît pas dans les DAGs actuellement chargés — tentative quand même." >&2
    fi
    TARGETS=("$TARGET")
fi

case "$ACTION" in
    pause|unpause)
        for dag in "${TARGETS[@]}"; do
            run_airflow dags "$ACTION" "$dag"
        done
        echo "--- État après \"$ACTION\" ---"
        print_statuses "${TARGETS[@]}"
        ;;
    status)
        print_statuses "${TARGETS[@]}"
        ;;
esac
