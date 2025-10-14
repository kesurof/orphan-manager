# Internals — comment ça fonctionne

Ce document explique le flux interne principal du script.

1. Construction des dossiers à scanner
- Le script parcourt `medias_base` (ou `include_dirs`) pour construire la liste des dossiers où chercher des symlinks. Voir `OrphanDetector.build_symlink_dirs`.

2. Lecture et filtrage des symlinks
- `OrphanDetector.scan_symlinks` parcourt récursivement les dossiers et lit la cible de chaque symlink (via `readlink()` pour des raisons de performance). La cible est normalisée et comparée au `mount_path` de l'instance courante.
- Éviter `startswith` sur des chaînes : préférer `Path.is_relative_to()` (Py3.9+) ou `relative_to()` pour éviter les faux positifs quand un mount est préfixe d'un autre.

3. Scan du montage (webdav/rclone)
- `OrphanDetector.scan_webdav` liste tous les fichiers présents sous `mount_path`.

4. Détection des orphelins
- Le script calcule la différence entre les fichiers présents sur le montage et les cibles de symlinks détectées pour l'instance (`webdav_sources - symlink_targets`).

5. Regroupement par torrent
- Lors de la suppression, le script extrait le nom du torrent en faisant `relative = path.relative_to(mount_path)` et en prenant `relative.parts[0]`. Tous les fichiers du même torrent sont regroupés.

6. Suppression et API
- Les suppressions passent par l'API AllDebrid (méthodes `AllDebridAPI.delete_magnet` ou équivalentes), avec retry et backoff configurés par instance.

Recommandations
- Normaliser les chemins (NFC/NFD) si vous utilisez macOS ou des systèmes qui ont des différences de normalisation d'Unicode.
- Remplacer les vérifications textuelles `startswith` par un test sémantique de chemin (patch proposé dans `docs/configuration.md`).
- Vérifier les permissions de lecture sur `medias_base` et `mount_path`.
