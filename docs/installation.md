# Installation

Prérequis
- Python 3.9+ recommandé
- pip
- (optionnel) virtualenv ou venv

Installation rapide

```bash
# Créer un environnement virtuel (optionnel mais recommandé)
python3 -m venv .venv
source .venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt
```

Vérifier la version Python

```bash
python --version
```

Remarques
- Si vous êtes sur une distribution basée sur Debian/Ubuntu, installez les dépendances systèmes nécessaires pour Python si besoin (build-essential, libssl-dev, libffi-dev, python3-dev).
- Utiliser un virtualenv aide à isoler les dépendances du système.
