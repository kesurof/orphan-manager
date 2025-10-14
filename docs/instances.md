# Instances AllDebrid

Chaque entrée dans `instances:` du `config.yaml` représente une instance AllDebrid (ex. Radarr, Sonarr, backups). Exemple :

```yaml
- name: Alldebrid_radarr
  enabled: true
  api_key: YOUR_API_KEY
  mount_path: /mnt/decypharr/alldebrid/torrents
  rate_limit: 0.2
  retry_attempts: 3
  retry_backoff: 2.0
```

Champs
- `name` (string) : identifiant lisible de l'instance. Utilisé pour les logs et le filtrage via l'option `--instance`.
- `enabled` (bool) : activer/désactiver le traitement de l'instance.
- `api_key` (string) : clé API AllDebrid.
- `mount_path` (path) : chemin du point de montage où sont stockés les fichiers téléchargés pour cette instance. IMPORTANT : doit pointer vers le répertoire racine des torrents (le premier composant permet d'identifier le nom du torrent lors de la suppression).
- `rate_limit` (float) : délai (secondes) entre requêtes API pour éviter le throttling.
- `retry_attempts` (int) : nombre de tentatives en cas d'erreur API.
- `retry_backoff` (float) : multiplicateur exponentiel entre tentatives.

Notes
- `mount_path` doit être unique par instance idéalement. Si deux `mount_path` sont des préfixes l'un de l'autre, le matching basé sur texte peut causer des collisions; la version recommandée du script utilise une vérification sémantique de chemin (`is_relative_to`/`relative_to`).
- Pour des raisons de permissions, assurez-vous que l'utilisateur qui exécute le script peut lire les symlinks sous `medias_base` et lister le contenu du `mount_path`.
