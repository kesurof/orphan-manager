# Documentation — Orphan Manager

Ce dossier contient la documentation détaillée du projet. Commencez par ce fichier pour comprendre l'architecture, la configuration et les modes d'exécution.

Plan de la documentation

1. Introduction
   - Objectif et cas d'usage
2. Installation
   - Python, virtualenv, dépendances (`requirements.txt`)
3. Configuration
   - Explication des champs de `config.example.yaml` et `config.yaml`
   - Exemple multi-instance
4. Fonctionnement interne
   - Détection des symlinks (`OrphanDetector.scan_symlinks`)
   - Matching symlink ↔ mount (précautions sur `startswith` vs tests sémantiques)
   - Extraction du nom de torrent (`OrphanCleaner.extract_torrent_name`)
   - Interaction avec l'API AllDebrid
5. Modes d'exécution
   - Dry-run, execute, auto-yes, debug, filtrage d'instances
6. Logs et monitoring
   - Format JSONL, rotation, niveau de logs
7. FAQ & troubleshooting
8. Contribution
   - Style de code, tests, PR

Propositions de pages à ajouter (fichiers Markdown individuels)
- `installation.md`
- `configuration.md`
- `internals.md`
- `usage.md`
- `faq.md`

Contribuez : créez une branche, ajoutez votre page dans `docs/` et ouvrez une PR.
