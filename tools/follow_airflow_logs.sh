#!/usr/bin/env bash
# Suit en direct les logs de la stack Airflow. Deux modes, car les tâches (LocalExecutor)
# s'exécutent dans le conteneur airflow-scheduler mais journalisent chacune dans un fichier
# séparé (airflow/logs/dag_id=.../run_id=.../task_id=.../attempt=N.log), PAS sur la sortie
# standard du conteneur — `docker compose logs` seul ne montre donc que l'activité du
# scheduler/apiserver (parsing, heartbeats, ordonnancement), pas le détail d'exécution des DAGs.
#
# Usage :
#   ./tools/follow_airflow_logs.sh                    # logs de la stack (conteneurs Airflow)
#   ./tools/follow_airflow_logs.sh stack               # idem, explicite
#   ./tools/follow_airflow_logs.sh dag <dag_id>        # logs de tâches du DAG, tous runs, en live
#
# Exemples de dag_id (cf. CLAUDE.md) : dag_etl_fraud_detection, dag_train_model, dag_report
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIRFLOW_DIR="$SCRIPT_DIR/../airflow"

MODE="${1:-stack}"

if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
else
    DOCKER_COMPOSE=(docker-compose)
fi

case "$MODE" in
    stack)
        echo "=== Logs de la stack Airflow (Ctrl+C pour arrêter) ==="
        cd "$AIRFLOW_DIR"
        export COMPOSE_PROJECT_NAME=fraud-detection
        exec "${DOCKER_COMPOSE[@]}" logs -f --tail=100 \
            airflow-scheduler airflow-apiserver airflow-dag-processor airflow-triggerer
        ;;
    dag)
        DAG_ID="${2:?Usage: $0 dag <dag_id> — ex: dag_etl_fraud_detection, dag_train_model, dag_report}"
        LOG_DIR="$AIRFLOW_DIR/logs/dag_id=$DAG_ID"
        if [ ! -d "$LOG_DIR" ]; then
            echo "Aucun log pour dag_id=$DAG_ID (pas encore exécuté ? DAG en pause ?) : $LOG_DIR introuvable" >&2
            exit 1
        fi

        echo "=== Logs de tâches du DAG '$DAG_ID' (Ctrl+C pour arrêter) ==="
        echo "Nouveaux fichiers attempt=*.log (nouveaux runs/tâches) suivis automatiquement."
        echo

        # Chaque fichier attempt=*.log découvert est suivi par un `tail -f` en tâche de fond,
        # préfixé par son run_id/task_id pour s'y retrouver quand plusieurs tâches tournent en
        # parallèle. Rescan périodique (les nouveaux run_id n'existent pas encore au lancement,
        # ex. dag_etl_fraud_detection tourne toutes les minutes).
        declare -A TAILED
        # Trap séparé du nettoyage (EXIT) et de l'arrêt (INT/TERM) : un trap INT/TERM qui se
        # contente de tuer les `tail` enfants ne fait PAS sortir la boucle `while true` — sans
        # `exit` explicite ici, Ctrl+C était silencieusement avalé et le script continuait de
        # tourner (bug constaté en usage réel le 2026-07-13).
        cleanup() { jobs -p | xargs -r kill 2>/dev/null; }
        trap cleanup EXIT
        trap 'exit 130' INT TERM

        while true; do
            while IFS= read -r f; do
                [ -n "$f" ] || continue
                if [ -z "${TAILED[$f]:-}" ]; then
                    TAILED["$f"]=1
                    label="$(echo "$f" | sed -E "s|.*dag_id=$DAG_ID/||; s|/attempt=| attempt=|")"
                    tail -n 5 -f "$f" 2>/dev/null | sed "s|^|[$label] |" &
                fi
            done < <(find "$LOG_DIR" -name 'attempt=*.log' 2>/dev/null | sort)
            sleep 2
        done
        ;;
    *)
        echo "Usage: $0 [stack|dag <dag_id>]" >&2
        exit 1
        ;;
esac
