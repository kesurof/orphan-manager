# FAQ & Troubleshooting

Q: Le script gère-t-il les chemins avec accents (ex: `/mnt/Bibliothèque`) ?
A: Oui, sur Linux (ext4) Python gère l'UTF-8 et `pathlib` fonctionne. Sur macOS HFS+ la normalisation peut être différente (NFD). Si vous rencontrez des problèmes, normalisez les chemins (NFC) ou utilisez des chemins sans caractères spéciaux.

Q: Quels permissions sont nécessaires ?
A: L'utilisateur exécutant le script doit pouvoir :
- Lire les symlinks et parcourir `medias_base`.
- Lister et lire le contenu du `mount_path` configuré pour chaque instance.

Q: Comment tester sans supprimer ?
A: Exécutez sans `--execute` pour un dry-run. Le script listera les orphelins sans toucher au montage.

Q: Le matching symlink ↔ mount donne des faux positifs
A: Si `mount_path` A est préfixe de `mount_path` B, une vérification par chaîne (`startswith`) peut mal matcher. Utilisez la version du script qui vérifie sémantiquement l'appartenance (`is_relative_to` / `relative_to`).

Q: Où sont les logs ?
A: Dans le dossier `log_dir` (défini dans `config.yaml`). Les logs JSONL sont utiles pour ingestion par outils de monitoring.

Q: Comment contribuer ?
A: Ouvrir une PR, documenter le changement et ajouter des tests quand possible.

Si tu veux, je peux :
- ajouter des tests unitaires basiques pour le matching de chemin,
- appliquer le patch pour remplacer `startswith` par `is_relative_to`/`relative_to` dans `orphan_manager.py`.
