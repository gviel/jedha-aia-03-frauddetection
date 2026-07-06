
# Méthode avec virtualenv + direnv

0) vérifier que direnv est installé
apt install virtualenv direnv
et l'ajouter au ~/.bashrc ou à ~/.local/bin/env
echo 'eval "$(direnv hook bash)"' >> ~/.bashrc

1) dans le répertoire projet
virtualenv .venv --python=python3.12

2) créer la config de l'env
echo "layout python .venv" > .envrc

3) autoriser direnv a s'éxecuter dans ce rép
direnv allow

4) installer les déps
pip install -r requirements.txt

NB: on peut générer un requirements.txt depuis le fichier YAML conda avec conda env export --from-history > requirements.txt ou en convertissant manuellement les dépendances.

# Méthode avec env conda3
conda env create -f env_ml.yaml
conda activate ml
python -m ipykernel install --user --name ml --display-name "ML"


