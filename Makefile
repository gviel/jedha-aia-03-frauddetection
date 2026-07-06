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

# ── Utilitaires ────────────────────────────────────────────────────────────────

clean:
	rm -rf $(VENV) $(VENV)-api work/logs work/fraudTest_prepared.csv work/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]

.PHONY: venv prepare train test api-venv api clean
