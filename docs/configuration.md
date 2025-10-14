# Configuration

Le fichier de configuration principal est `config.yaml` (voir `config.example.yaml` pour un exemple complet). Il est divisé en plusieurs sections : `global`, `instances`, `display`, `logging`.

## global
- `medias_base` : chemin racine où sont présents vos dossiers médias (ex : `/home/user/Medias` ou `/mnt/Bibliothèque`).
- `log_dir` : dossier pour écrire les logs.
- `log_retention_days` : nombre de jours à conserver les logs.
- `cycle_count` : nombre de cycles à exécuter (0 = infini).
- `cycle_interval` : minutes entre cycles.
- `exclude_dirs` / `include_dirs` : filtres pour limiter les dossiers scannés.

### Remarque sur `medias_base` et Unicode
Le script accepte des chemins contenant des caractères accentués (ex. `/mnt/Bibliothèque`). Sur Linux (ext4) l'UTF-8 est géré et Python `pathlib` fonctionne correctement. Sur macOS (HFS+) les noms peuvent être normalisés différemment (NFD): si vous observez des problèmes de matching entre symlinks et chemins montés, normalisez (NFC/NFD) ou utilisez le même encodage pour les chemins.

## instances
Chaque entrée de `instances` décrit une instance AllDebrid (Radarr, Sonarr...). Les champs principaux sont décrits dans `docs/instances.md`.

## display
Contrôle le comportement d'affichage (progress bars, couleurs, détails).

## logging
- `console_level` : niveau pour les logs console (INFO, DEBUG...).
- `file_level` : niveau pour les fichiers.
- `json_logging` : écriture de logs au format JSONL.
- `syslog_logging` : envoi vers journald/syslog.

## Extrait (exemple)

```yaml
instances:
  - name: Alldebrid_radarr
    enabled: true
    api_key: YOUR_API_KEY
    mount_path: /mnt/decypharr/alldebrid/torrents
    rate_limit: 0.2
    retry_attempts: 3
    retry_backoff: 2.0
```

Note : `mount_path` doit être le chemin exact sur lequel l'instance dépose les fichiers (ex: le point de montage rclone/AllDebrid). Si vous avez plusieurs montages distincts, créez plusieurs instances.
