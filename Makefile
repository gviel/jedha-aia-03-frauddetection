PYTHON  := python3
VENV    := .venv
PIP     := $(VENV)/bin/pip
PYEXEC  := $(VENV)/bin/python

# ── Setup ──────────────────────────────────────────────────────────────────────

$(VENV): src/requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip --quiet
	$(PIP) install -r src/requirements.txt
	@touch $(VENV)

venv: $(VENV)

# ── Scripts ML ─────────────────────────────────────────────────────────────────

prepare: $(VENV)
	$(PYEXEC) src/prepare_dataset.py $(ARGS)

train: $(VENV)
	$(PYEXEC) src/train.py $(ARGS)

test: $(VENV)
	$(PYEXEC) -m pytest tests/ -v

# ── API ────────────────────────────────────────────────────────────────────────

api-venv: api/requirements.txt
	$(PYTHON) -m venv $(VENV)-api
	$(VENV)-api/bin/pip install --upgrade pip --quiet
	$(VENV)-api/bin/pip install -r api/requirements.txt

api: api-venv
	$(VENV)-api/bin/uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload

# ── Airflow (pause/relance des DAGs sur la stack en cours) ─────────────────────

dag-status:
	airflow/dag_toggle.sh status $(DAG)

dag-pause:
	airflow/dag_toggle.sh pause $(DAG)

dag-unpause:
	airflow/dag_toggle.sh unpause $(DAG)

# ── Utilitaires ────────────────────────────────────────────────────────────────

clean:
	rm -rf $(VENV) $(VENV)-api work/logs work/fraudTest_prepared.csv work/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]

# Tous les logs (prepare_dataset_*.log, train_*.log) de work/logs.
clean-logs:
	rm -rf work/logs

# Logs de work/logs sauf ceux du dernier jour disponible (dernière date YYYYMMDD trouvée
# dans les noms de fichiers *_YYYYMMDD_HHMMSS.log).
clean-logs-keep-last:
	@last="$$(ls work/logs 2>/dev/null | grep -oE '[0-9]{8}' | sort -u | tail -1)"; \
	if [ -z "$$last" ]; then \
		echo "Aucun log dans work/logs."; \
	else \
		echo "Conservation des logs du $$last, suppression du reste."; \
		find work/logs -type f ! -name "*_$${last}_*" -delete; \
	fi

# Tous les répertoires de transactions work/YYYYMMDD (générés par le DAG 3.1).
clean-trx:
	rm -rf work/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]

# Répertoires work/YYYYMMDD sauf celui du dernier jour disponible (tri lexicographique =
# tri chronologique sur un nom YYYYMMDD).
clean-trx-keep-last:
	@last="$$(ls -d work/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9] 2>/dev/null | xargs -n1 basename | sort | tail -1)"; \
	if [ -z "$$last" ]; then \
		echo "Aucun répertoire work/YYYYMMDD."; \
	else \
		echo "Conservation de work/$$last, suppression des autres jours."; \
		for d in work/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]; do \
			[ -d "$$d" ] || continue; \
			[ "$$(basename $$d)" = "$$last" ] || rm -rf "$$d"; \
		done; \
	fi

# Fichiers CSV intermédiaires (work/fraudTest_prepared.csv, work/client_trx_analysis.csv),
# régénérés par prepare_dataset.py/train.py — work/fraudTest.csv (source, alimentée par le
# DAG 3.1) n'est volontairement jamais supprimé par cette cible.
clean-work-csv:
	rm -f work/fraudTest_prepared.csv work/client_trx_analysis.csv

# Tous les logs de tâches Airflow (airflow/logs/dag_id=*/run_id=*/task_id=*/attempt=*.log)
# + les logs du dag-processor (airflow/logs/dag_processor/YYYY-MM-DD/) — Airflow ne fait aucune
# rotation automatique de ces fichiers, cf. docs/travail/troubleshooting.md. Le dossier
# airflow/logs lui-même n'est jamais supprimé (bind-mount actif si la stack tourne).
clean-airflow-logs:
	rm -rf airflow/logs/dag_id=* airflow/logs/dag_processor

# Logs Airflow sauf ceux du dernier jour disponible (date déduite des run_id
# "run_id=scheduled__YYYY-MM-DDTHH:MM:SS+00:00" ou "run_id=manual__...", et des sous-dossiers
# déjà nommés YYYY-MM-DD sous dag_processor).
clean-airflow-logs-keep-last:
	@last="$$(find airflow/logs -maxdepth 2 -type d -name 'run_id=*' 2>/dev/null | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | sort -u | tail -1)"; \
	if [ -z "$$last" ]; then \
		echo "Aucun run_id dans airflow/logs."; \
	else \
		echo "Conservation des runs du $$last, suppression du reste."; \
		find airflow/logs -maxdepth 2 -type d -name 'run_id=*' | while read -r d; do \
			case "$$d" in \
				*"$$last"*) ;; \
				*) rm -rf "$$d" ;; \
			esac; \
		done; \
		if [ -d airflow/logs/dag_processor ]; then \
			for d in airflow/logs/dag_processor/*/; do \
				[ -d "$$d" ] || continue; \
				[ "$$(basename "$$d")" = "$$last" ] || rm -rf "$$d"; \
			done; \
		fi; \
	fi

.PHONY: venv prepare train test api-venv api clean clean-logs clean-logs-keep-last \
        clean-trx clean-trx-keep-last clean-work-csv clean-airflow-logs \
        clean-airflow-logs-keep-last dag-status dag-pause dag-unpause
