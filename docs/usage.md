# Usage

Commandes principales

```bash
# Analyse (dry-run)
python orphan_manager.py

# Exécution (suppression interactive)
python orphan_manager.py --execute

# Exécution non-interactive (cron)
python orphan_manager.py --execute --yes

# Traiter une seule instance
python orphan_manager.py --instance Alldebrid_radarr
```

Options courantes
- `--execute` : autorise la suppression (sinon le script se contente de lister)
- `--yes` : répondre automatiquement oui aux confirmations (utile pour cron)
- `--instance NAME` : ne traiter qu'une instance précise
- `--log-level DEBUG` : augmenter le niveau de log pour debug
- `--test-match PATH` : tester si un chemin correspond à une instance (si implémenté)

Exemple Cron (exécuter toutes les heures)

```cron
0 * * * * cd /home/kesurof/scripts/orphan-manager && /usr/bin/python3 orphan_manager.py --execute --yes >> logs/cron.log 2>&1
```

Logs
- Les logs sont écrits dans le dossier configuré (`log_dir` dans `config.yaml`).
- Les logs JSONL peuvent être consommés par des outils d'analyse ou Kibana.

Bonnes pratiques
- Tester d'abord en `dry-run` avant d'activer `--execute`.
- Sauvegarder ou archiver les logs importants avant de modifier la configuration.
- S'assurer que `config.yaml` contient des chemins exacts pour `mount_path`.
