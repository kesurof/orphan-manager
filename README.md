
# Orphan Manager

> Outil léger pour détecter et (optionnellement) supprimer les fichiers "orphelins" présents sur des montages AllDebrid lorsque aucun symlink local ne pointe vers eux.

Principes rapides
- Multi-instance (Radarr, Sonarr, backups...) avec priorités, retry et rate-limiting.
- Association symlink ↔ instance basée sur la cible du symlink comparée au `mount_path` configuré pour chaque instance.

Fichiers importants
- `orphan_manager.py` — script principal
- `config.example.yaml` / `config.yaml` — configuration multi-instance
- `requirements.txt` — dépendances Python
- `logs/` — logs JSONL / texte

Installation
```bash
pip install -r requirements.txt
```

Usage rapide
```bash
# Dry-run (détection seulement)
python orphan_manager.py

# Mode suppression (interactive)
python orphan_manager.py --execute

# Mode suppression non-interactive (cron)
python orphan_manager.py --execute --yes

# Traiter une seule instance
python orphan_manager.py --instance Alldebrid_radarr
```

Voir aussi
- Configuration : `config.yaml`
- Logs : dossier configuré dans `config.yaml` (par défaut `logs/`)
- Documentation complète : dossier `docs/`

Licence
Ajoutez un fichier `LICENSE` selon la licence choisie.

Contributions
PRs bienvenues — merci d'ajouter des tests et de documenter les changements.

