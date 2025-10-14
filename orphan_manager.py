#!/usr/bin/env python3
"""
Multi-Instance AllDebrid Orphan Manager v2.0

Détecte et supprime les fichiers orphelins (sans symlinks correspondants)
sur plusieurs instances AllDebrid avec gestion multi-comptes.

Usage:
    python orphan_manager.py                          # Dry-run
    python orphan_manager.py --execute                # Suppression avec confirmation
    python orphan_manager.py --execute --yes          # Suppression auto (cron)
    python orphan_manager.py --instance radarr        # Une seule instance
    python orphan_manager.py --test-match /path/file  # Debug matching
    python orphan_manager.py --debug-list             # Liste torrents

Exit codes:
    0 = Aucun orphelin
    1 = Erreur technique
    2 = Orphelins détectés mais non supprimés
    3 = Suppression réussie
"""

import asyncio
import argparse
import json
import logging
import logging.handlers
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Set, Dict, Optional, Tuple
import yaml

try:
    import aiohttp
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.panel import Panel
    from rich.table import Table
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("[WARNING] Rich/aiohttp not available, using plain output", file=sys.stderr)


# ============================================================================
# DATACLASSES
# ============================================================================

@dataclass
class AllDebridInstance:
    """Configuration d'une instance AllDebrid"""
    name: str
    api_key: str
    mount_path: Path
    rate_limit: float
    retry_attempts: int
    retry_backoff: float
    enabled: bool

    def __post_init__(self):
        self.mount_path = Path(self.mount_path)


@dataclass
class OrphanScanResult:
    """Résultat du scan d'orphelins pour une instance"""
    instance_name: str
    total_sources: int
    total_symlinks: int
    orphaned_files: List[Path]
    scan_duration: float

    @property
    def orphan_count(self) -> int:
        return len(self.orphaned_files)


@dataclass
class GlobalConfig:
    """Configuration globale"""
    medias_base: Path
    log_dir: Path
    log_retention_days: int
    cycle_count: int
    cycle_interval: int
    exclude_dirs: List[str]
    include_dirs: List[str]

    def __post_init__(self):
        self.medias_base = Path(self.medias_base)
        self.log_dir = Path(self.log_dir)


# ============================================================================
# LOGGING
# ============================================================================

class JSONLogger:
    """Logger JSON structuré (JSONL format)"""

    def __init__(self, log_file: Path, enabled: bool = True):
        self.enabled = enabled
        self.log_file = log_file

        if enabled and log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, level: str = "INFO", **kwargs):
        """Écrit un événement JSON"""
        if not self.enabled or not self.log_file:
            return

        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "event": event,
            **kwargs
        }

        with open(self.log_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')


def setup_logging(config: GlobalConfig, instance_name: Optional[str] = None) -> Tuple[logging.Logger, JSONLogger]:
    """Configure le système de logging"""

    log_name = f'orphan-{instance_name.lower().replace(" ", "-")}' if instance_name else 'orphan-manager'
    logger = logging.getLogger(log_name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('[%(levelname)s] %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler
    if instance_name:
        safe_name = instance_name.lower().replace(' ', '_').replace('-', '_')
        log_file = config.log_dir / f"{safe_name}_{datetime.now().strftime('%Y%m%d')}.log"
        json_file = config.log_dir / f"{safe_name}_{datetime.now().strftime('%Y%m%d')}.jsonl"
    else:
        log_file = config.log_dir / f"manager_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        json_file = None

    config.log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Syslog handler
    try:
        syslog_handler = logging.handlers.SysLogHandler(
            address='/dev/log',
            facility=logging.handlers.SysLogHandler.LOG_USER
        )
        syslog_formatter = logging.Formatter(f'{log_name}: %(message)s')
        syslog_handler.setFormatter(syslog_formatter)
        logger.addHandler(syslog_handler)
    except Exception:
        pass

    # JSON logger
    json_logger = JSONLogger(json_file, enabled=json_file is not None)

    return logger, json_logger


# ============================================================================
# ALLDEBRID API CLIENT
# ============================================================================

class AllDebridAPI:
    """Client API AllDebrid avec retry automatique"""

    BASE_URL = "https://api.alldebrid.com/v4.1"
    # Suivi des sessions ouvertes pour permettre un nettoyage global en cas d'interruption
    _open_sessions: Set = set()

    def __init__(self, api_key: str, rate_limit: float, retry_attempts: int, retry_backoff: float):
        self.api_key = api_key
        self.rate_limit = rate_limit
        self.retry_attempts = retry_attempts
        self.retry_backoff = retry_backoff
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"Authorization": f"Bearer {self.api_key}"}
        )
        # Enregistrer la session pour nettoyage éventuel
        try:
            AllDebridAPI._open_sessions.add(self.session)
        except Exception:
            pass
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            try:
                await self.session.close()
            finally:
                try:
                    AllDebridAPI._open_sessions.discard(self.session)
                except Exception:
                    pass

    async def _request_with_retry(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Effectue une requête avec retry exponentiel"""
        url = f"{self.BASE_URL}{endpoint}"

        for attempt in range(1, self.retry_attempts + 1):
            try:
                async with self.session.request(method, url, **kwargs) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:  # Rate limit
                        wait = self.retry_backoff ** attempt
                        await asyncio.sleep(wait)
                        continue
                    else:
                        raise Exception(f"HTTP {resp.status}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == self.retry_attempts:
                    raise Exception(f"API error after {self.retry_attempts} attempts: {e}")
                wait = self.retry_backoff ** attempt
                await asyncio.sleep(wait)

        raise Exception("Max retries exceeded")

    async def get_magnets(self) -> List[Dict]:
        """Récupère la liste des torrents"""
        response = await self._request_with_retry("GET", "/magnet/status")

        if response.get('status') != 'success':
            raise Exception(f"API error: {response.get('error', {}).get('message', 'Unknown')}")

        return response.get('data', {}).get('magnets', [])

    def find_magnet_id(self, torrent_name: str, magnets: List[Dict]) -> Optional[str]:
        """Trouve l'ID d'un magnet par son nom (exact ou startswith)"""
        # Essayer exact match
        for magnet in magnets:
            if magnet.get('filename') == torrent_name or magnet.get('name') == torrent_name:
                return magnet.get('id')

        # Essayer startswith (pour films avec extension)
        for magnet in magnets:
            filename = magnet.get('filename', '')
            if filename.startswith(torrent_name):
                return magnet.get('id')

        return None

    async def delete_magnet(self, magnet_id: str) -> bool:
        """Supprime un magnet"""
        try:
            data = aiohttp.FormData()
            data.add_field('id', str(magnet_id))

            response = await self._request_with_retry("POST", "/magnet/delete", data=data)

            return response.get('status') == 'success'
        except Exception:
            return False

    @classmethod
    async def close_all_sessions(cls):
        """Ferme toutes les sessions aiohttp ouvertes (utilisé pour nettoyage sur CTRL-C)."""
        # Copier la liste pour itérer en toute sécurité
        sessions = list(cls._open_sessions)
        for s in sessions:
            try:
                # await close; ignore errors
                await s.close()
            except Exception:
                pass
            try:
                cls._open_sessions.discard(s)
            except Exception:
                pass


# ============================================================================
# ORPHAN DETECTOR
# ============================================================================

class OrphanDetector:
    """Détecteur de fichiers orphelins"""

    def __init__(self, config: GlobalConfig, instance: AllDebridInstance, logger: logging.Logger, json_logger: JSONLogger):
        self.config = config
        self.instance = instance
        self.logger = logger
        self.json_logger = json_logger

    def build_symlink_dirs(self) -> List[Path]:
        """Construit la liste des dossiers à scanner"""
        if self.config.include_dirs:
            # Mode whitelist
            dirs = []
            for dir_name in self.config.include_dirs:
                path = self.config.medias_base / dir_name
                if path.exists() and path.is_dir():
                    dirs.append(path)
            return dirs
        else:
            # Mode blacklist
            dirs = []
            for path in self.config.medias_base.iterdir():
                if not path.is_dir():
                    continue
                if path.name in self.config.exclude_dirs:
                    continue
                dirs.append(path)
            return dirs
        
    def scan_symlinks(self, dirs: List[Path]) -> Set[Path]:
        """Scan tous les symlinks pointant vers le montage (optimisé)"""
        targets = set()
        mount_str = str(self.instance.mount_path)

        for dir_path in dirs:
            self.logger.debug(f"  Scan: {dir_path.name}")
            for item in dir_path.rglob('*'):
                if item.is_symlink():
                    try:
                        # Utiliser readlink() au lieu de resolve() (beaucoup plus rapide)
                        target_str = str(item.readlink())

                        # Si relatif, construire le chemin absolu manuellement
                        if not target_str.startswith('/'):
                            target_path = (item.parent / target_str).resolve()
                        else:
                            target_path = Path(target_str)

                        # Filtrer uniquement ceux qui commencent par mount_path
                        if str(target_path).startswith(mount_str):
                            targets.add(target_path)
                    except (OSError, RuntimeError, ValueError):
                        # Ignorer les symlinks cassés ou inaccessibles
                        continue

        return targets

    def scan_webdav(self, mount: Path) -> Set[Path]:
        """Scan tous les fichiers dans le montage WebDAV"""
        sources = set()

        for item in mount.rglob('*'):
            if item.is_file():
                sources.add(item)

        return sources

    def find_orphans(self) -> OrphanScanResult:
        """Détecte les orphelins"""
        start_time = time.time()

        self.json_logger.log("scan_started", instance=self.instance.name)

        # Vérifier montage
        if not self.instance.mount_path.exists():
            raise Exception(f"Mount inaccessible: {self.instance.mount_path}")

        # Build dirs
        dirs = self.build_symlink_dirs()
        self.logger.info(f"Dossiers à scanner: {len(dirs)}")

        # Scan symlinks
        self.logger.info("Scan symlinks...")
        symlink_targets = self.scan_symlinks(dirs)
        self.logger.info(f"✓ {len(symlink_targets)} symlinks uniques")

        # Scan WebDAV
        self.logger.info("Scan WebDAV sources...")
        webdav_sources = self.scan_webdav(self.instance.mount_path)
        self.logger.info(f"✓ {len(webdav_sources)} fichiers sources")

        # Comparer
        self.logger.info("Comparaison...")
        orphaned = list(webdav_sources - symlink_targets)

        duration = time.time() - start_time

        result = OrphanScanResult(
            instance_name=self.instance.name,
            total_sources=len(webdav_sources),
            total_symlinks=len(symlink_targets),
            orphaned_files=orphaned,
            scan_duration=duration
        )

        self.json_logger.log(
            "scan_completed",
            instance=self.instance.name,
            total_sources=result.total_sources,
            total_symlinks=result.total_symlinks,
            orphan_count=result.orphan_count,
            duration=round(duration, 2)
        )

        return result


# ============================================================================
# ORPHAN CLEANER
# ============================================================================

class OrphanCleaner:
    """Gestionnaire de suppression d'orphelins"""

    def __init__(self, api: AllDebridAPI, instance: AllDebridInstance, logger: logging.Logger, json_logger: JSONLogger, use_rich: bool):
        self.api = api
        self.instance = instance
        self.logger = logger
        self.json_logger = json_logger
        self.use_rich = use_rich

        if use_rich:
            self.console = Console(stderr=True)

    def extract_torrent_name(self, path: Path, mount: Path) -> str:
        """Extrait le nom du torrent depuis le chemin"""
        try:
            relative = path.relative_to(mount)
            return relative.parts[0]
        except (ValueError, IndexError):
            return ""

    def confirm_deletion(self, count: int, auto_yes: bool) -> bool:
        """Demande confirmation pour suppression"""
        if auto_yes:
            self.logger.info("Mode automatique (--yes), suppression sans confirmation")
            return True

        if self.use_rich:
            self.console.print(f"\n[bold yellow]⚠️  Confirmer la suppression de {count} torrents?[/bold yellow] [dim][y/N][/dim]: ", end="")
        else:
            print(f"\n⚠️  Confirmer la suppression de {count} torrents? [y/N]: ", end="", file=sys.stderr)

        response = input().strip().lower()
        return response in ['y', 'yes', 'o', 'oui']

    async def delete_orphans(self, orphans: List[Path], mount: Path) -> Dict[str, int]:
        """Supprime les orphelins via API AllDebrid"""
        # Extraire noms torrents uniques
        torrent_names = set()
        for orphan in orphans:
            name = self.extract_torrent_name(orphan, mount)
            if name:
                torrent_names.add(name)

        torrents = sorted(torrent_names)
        total = len(torrents)

        self.logger.info(f"Torrents uniques à supprimer: {total}")

        # Récupérer liste magnets
        try:
            magnets = await self.api.get_magnets()
        except Exception as e:
            self.logger.error(f"Erreur récupération magnets: {e}")
            return {"success": 0, "not_found": 0, "errors": total}

        # Supprimer
        stats = {"success": 0, "not_found": 0, "errors": 0}
        deleted_torrents: List[str] = []
        not_found_torrents: List[str] = []
        error_torrents: List[str] = []

        for idx, torrent_name in enumerate(torrents, 1):
            display_name = torrent_name[:60]

            if self.use_rich:
                self.console.print(f"[{idx}/{total}] {display_name}")
            else:
                self.logger.info(f"[{idx}/{total}] {display_name}")

            # Trouver ID
            magnet_id = self.api.find_magnet_id(torrent_name, magnets)

            if not magnet_id:
                if self.use_rich:
                    self.console.print("  [yellow]⚠️  Absent[/yellow]")
                else:
                    self.logger.warning("  ⚠️  Absent")
                stats["not_found"] += 1
                not_found_torrents.append(torrent_name)
            else:
                if self.use_rich:
                    self.console.print(f"  [dim]🔍 ID: {magnet_id}[/dim]")
                else:
                    self.logger.info(f"  🔍 ID: {magnet_id}")

                # Supprimer
                success = await self.api.delete_magnet(magnet_id)

                if success:
                    if self.use_rich:
                        self.console.print("  [green]✅ Supprimé[/green]")
                    else:
                        self.logger.info("  ✅ Supprimé")
                    stats["success"] += 1

                    self.json_logger.log(
                        "magnet_deleted",
                        instance=self.instance.name,
                        torrent=torrent_name,
                        magnet_id=magnet_id
                    )
                    deleted_torrents.append(torrent_name)
                else:
                    if self.use_rich:
                        self.console.print("  [red]✗ Échec[/red]")
                    else:
                        self.logger.error("  ✗ Échec")
                    stats["errors"] += 1
                    error_torrents.append(torrent_name)

            # Rate limiting
            await asyncio.sleep(self.instance.rate_limit)

            # Progression
            if idx % 10 == 0:
                msg = f"  📊 Progression: ✅{stats['success']} | ⚠️{stats['not_found']} | ✗{stats['errors']}"
                if self.use_rich:
                    self.console.print(f"[dim]{msg}[/dim]")
                else:
                    self.logger.info(msg)

        self.json_logger.log(
            "deletion_completed",
            instance=self.instance.name,
            **stats,
            deleted_torrents=deleted_torrents,
            not_found_torrents=not_found_torrents,
            error_torrents=error_torrents
        )

        # Retourner aussi les listes pour post-traitement
        stats.update({
            "deleted_torrents": deleted_torrents,
            "not_found_torrents": not_found_torrents,
            "error_torrents": error_torrents
        })

        return stats


# ============================================================================
# ORPHAN MANAGER
# ============================================================================

class OrphanManager:
    """Orchestrateur principal"""

    def __init__(self, config_path: Path):
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f)

        self.global_config = GlobalConfig(
            medias_base=data['global']['medias_base'],
            log_dir=data['global']['log_dir'],
            log_retention_days=data['global'].get('log_retention_days', 3),
            cycle_count=data['global'].get('cycle_count', 1),
            cycle_interval=data['global'].get('cycle_interval', 60),
            exclude_dirs=data['global'].get('exclude_dirs', []),
            include_dirs=data['global'].get('include_dirs', [])
        )

        self.instances = [
            AllDebridInstance(
                name=inst['name'],
                api_key=inst['api_key'],
                mount_path=inst['mount_path'],
                rate_limit=inst.get('rate_limit', 0.2),
                retry_attempts=inst.get('retry_attempts', 3),
                retry_backoff=inst.get('retry_backoff', 2.0),
                enabled=inst.get('enabled', True)
            )
            for inst in data['instances']
        ]

        self.display_config = data.get('display', {})
        self.use_rich = RICH_AVAILABLE and sys.stderr.isatty() and self.display_config.get('show_progress', True)

        if self.use_rich:
            self.console = Console(stderr=True)

        self.logger, _ = setup_logging(self.global_config)

        self.cleanup_old_logs()

    def cleanup_old_logs(self):
        """Supprime les logs anciens"""
        cutoff = datetime.now() - timedelta(days=self.global_config.log_retention_days)

        for log_file in self.global_config.log_dir.glob('*.log'):
            if log_file.stat().st_mtime < cutoff.timestamp():
                log_file.unlink()

        for log_file in self.global_config.log_dir.glob('*.jsonl'):
            if log_file.stat().st_mtime < cutoff.timestamp():
                log_file.unlink()

    async def process_instance(self, instance: AllDebridInstance, execute_mode: bool, auto_yes: bool) -> OrphanScanResult:
        """Traite une instance"""
        instance_logger, json_logger = setup_logging(self.global_config, instance.name)

        if self.use_rich:
            self.console.print(f"\n[bold cyan]{'═'*60}[/bold cyan]")
            self.console.print(f"[bold cyan]📦 {instance.name}[/bold cyan]")
            self.console.print(f"[bold cyan]{'═'*60}[/bold cyan]\n")
        else:
            self.logger.info(f"\n{'═'*60}")
            self.logger.info(f"📦 {instance.name}")
            self.logger.info(f"{'═'*60}\n")

        # Détection
        detector = OrphanDetector(self.global_config, instance, instance_logger, json_logger)
        result = detector.find_orphans()

        instance_logger.info(f"✓ {result.orphan_count} orphelins détectés")

        # Suppression si execute mode
        if execute_mode and result.orphan_count > 0:
            async with AllDebridAPI(
                instance.api_key,
                instance.rate_limit,
                instance.retry_attempts,
                instance.retry_backoff
            ) as api:
                cleaner = OrphanCleaner(api, instance, instance_logger, json_logger, self.use_rich)

                if cleaner.confirm_deletion(result.orphan_count, auto_yes):
                    stats = await cleaner.delete_orphans(result.orphaned_files, instance.mount_path)
                    instance_logger.info(f"\nRÉSUMÉ: ✅{stats['success']} | ⚠️{stats['not_found']} | ✗{stats['errors']}")
                else:
                    instance_logger.info("Suppression annulée")

        return result

    async def run_cycle(self, cycle_num: int, execute_mode: bool, auto_yes: bool, target_instance: Optional[str] = None) -> Dict[str, Tuple[AllDebridInstance, OrphanScanResult]]:
        """Exécute un cycle"""
        if self.use_rich:
            self.console.print(Panel.fit(
                f"[bold cyan]🔄 CYCLE {cycle_num}[/bold cyan]",
                box=box.DOUBLE
            ))
        else:
            self.logger.info(f"\n{'═'*60}")
            self.logger.info(f"🔄 CYCLE {cycle_num}")
            self.logger.info(f"{'═'*60}")

        # Filtrer instances
        enabled_instances = [i for i in self.instances if i.enabled]

        if target_instance:
            enabled_instances = [i for i in enabled_instances if i.name.lower() == target_instance.lower()]

        if not enabled_instances:
            self.logger.error("Aucune instance active")
            return

        self.logger.info(f"Instances actives: {len(enabled_instances)}")

        # Traiter chaque instance
        results: Dict[str, Tuple[AllDebridInstance, OrphanScanResult]] = {}

        for instance in enabled_instances:
            res = await self.process_instance(instance, execute_mode, auto_yes)
            results[instance.name] = (instance, res)

        if self.use_rich:
            self.console.print(f"\n[bold green]✅ CYCLE {cycle_num} terminé[/bold green]\n")
        else:
            self.logger.info(f"\n✅ CYCLE {cycle_num} terminé\n")

        return results

    async def run(self, execute_mode: bool = False, auto_yes: bool = False, target_instance: Optional[str] = None):
        """Point d'entrée principal"""
        if self.use_rich:
            self.console.print(Panel.fit(
                "[bold cyan]🧹 Multi-Instance AllDebrid Orphan Manager v2.0[/bold cyan]",
                box=box.DOUBLE
            ))
        else:
            self.logger.info("🧹 Multi-Instance AllDebrid Orphan Manager v2.0")

        mode = "SUPPRESSION" if execute_mode else "VÉRIFICATION (dry-run)"
        self.logger.info(f"Mode: {mode}\n")

        cycle_num = 0

        while True:
            cycle_num += 1

            results = await self.run_cycle(cycle_num, execute_mode, auto_yes, target_instance)

            # Interactive menu (only if stdin is a TTY)
            if sys.stdin.isatty():
                menu_quit = False
                while True:
                    # Afficher menu d'actions
                    if self.use_rich:
                        self.console.print("═══ ACTIONS ═══\n", style="bold")
                        self.console.print("[1] 📋 Afficher les détails des orphelins")
                        self.console.print("[2] 🗑️  Supprimer les orphelins")
                        self.console.print("[3] ❌ Quitter")
                        self.console.print("[Entrée] ➜ Continuer (prochain cycle)\n")
                        choice = input("Choisir une action [1-3] ou Entrée pour continuer: ").strip()
                    else:
                        print("═══ ACTIONS ═══\n")
                        print("[1] 📋 Afficher les détails des orphelins")
                        print("[2] 🗑️  Supprimer les orphelins")
                        print("[3] ❌ Quitter")
                        print("[Entrée] ➜ Continuer (prochain cycle)\n")
                        choice = input("Choisir une action [1-3] ou Entrée pour continuer: ").strip()

                    if choice == '1':
                        # Afficher détails
                        for inst_name, (inst, scan_res) in results.items():
                            header = f"Instance: {inst_name} — Orphelins: {scan_res.orphan_count}"
                            if self.use_rich:
                                self.console.print(f"\n[bold]{header}[/bold]")
                            else:
                                print(f"\n{header}")

                            if scan_res.orphan_count == 0:
                                if self.use_rich:
                                    self.console.print("  (Aucun)")
                                else:
                                    print("  (Aucun)")
                                continue

                            # Lister quelques éléments (limités)
                            max_show = 200
                            count = 0
                            for p in scan_res.orphaned_files:
                                if count >= max_show:
                                    break
                                line = f"  - {p}"
                                if self.use_rich:
                                    self.console.print(line)
                                else:
                                    print(line)
                                count += 1

                            if count < scan_res.orphan_count:
                                more = scan_res.orphan_count - count
                                msg = f"  ... et {more} autres"
                                if self.use_rich:
                                    self.console.print(msg)
                                else:
                                    print(msg)

                        # Après l'affichage, revenir au menu
                        continue

                    elif choice == '2':
                        # Supprimer : demander confirmation globale si besoin
                        total_orphans = sum(r.orphan_count for (_, r) in results.values())
                        confirm = False
                        if auto_yes:
                            confirm = True
                        else:
                            q = input(f"Confirmer la suppression des {total_orphans} orphelins? [y/N]: ").strip().lower()
                            confirm = q in ('y', 'yes', 'o', 'oui')

                        if confirm:
                            # Utiliser les résultats déjà scannés (ne pas relancer de scan)
                            for inst_name, (inst, scan_res) in results.items():
                                if scan_res.orphan_count == 0:
                                    continue

                                instance_logger, json_logger = setup_logging(self.global_config, inst.name)

                                # Utiliser l'API pour supprimer les orphelins listés
                                async with AllDebridAPI(
                                    inst.api_key,
                                    inst.rate_limit,
                                    inst.retry_attempts,
                                    inst.retry_backoff
                                ) as api:
                                    cleaner = OrphanCleaner(api, inst, instance_logger, json_logger, self.use_rich)

                                    # Confirmation par instance : si l'utilisateur a déjà confirmé globalement
                                    # ou si --yes est actif, on ne redemande pas.
                                    if auto_yes or confirm:
                                        per_confirm = True
                                    else:
                                        per_confirm = cleaner.confirm_deletion(scan_res.orphan_count, auto_yes)

                                    if not per_confirm:
                                        instance_logger.info("Suppression annulée pour cette instance")
                                        continue

                                    stats = await cleaner.delete_orphans(scan_res.orphaned_files, inst.mount_path)
                                    instance_logger.info(f"\nRÉSUMÉ ({inst.name}): ✅{stats['success']} | ⚠️{stats['not_found']} | ✗{stats['errors']}")

                                    # Retirer des résultats scannés les fichiers correspondant aux torrents supprimés
                                    deleted = set(stats.get('deleted_torrents', []))
                                    if deleted:
                                        remaining = []
                                        for p in scan_res.orphaned_files:
                                            try:
                                                rel = p.relative_to(inst.mount_path)
                                                tname = rel.parts[0] if len(rel.parts) > 0 else ''
                                            except Exception:
                                                tname = ''

                                            if tname not in deleted:
                                                remaining.append(p)

                                        scan_res.orphaned_files = remaining

                            # Après suppression, revenir au menu
                            continue
                        else:
                            if self.use_rich:
                                self.console.print("Suppression annulée")
                            else:
                                print("Suppression annulée")

                            # Revenir au menu
                            continue

                    elif choice == '3':
                        # Quitter proprement
                        if self.use_rich:
                            self.console.print("Au revoir 👋")
                        else:
                            print("Au revoir 👋")
                        menu_quit = True
                        break

                    elif choice == '':
                        # Continuer vers le prochain cycle
                        break

                    else:
                        # Choix invalide, réafficher le menu
                        if self.use_rich:
                            self.console.print("Choix invalide, veuillez réessayer.")
                        else:
                            print("Choix invalide, veuillez réessayer.")
                        continue

                if menu_quit:
                    break

            # Sortir si limite atteinte
            if self.global_config.cycle_count > 0 and cycle_num >= self.global_config.cycle_count:
                break

            # Pause entre cycles
            if self.global_config.cycle_count == 0 or cycle_num < self.global_config.cycle_count:
                wait_minutes = self.global_config.cycle_interval
                self.logger.info(f"⏸️  Pause {wait_minutes}min avant cycle {cycle_num + 1}\n")
                await asyncio.sleep(wait_minutes * 60)


# ============================================================================
# MODES DEBUG
# ============================================================================

async def debug_test_match(config_path: Path, test_file: str, instance_name: str):
    """Mode debug : tester matching d'un fichier"""
    with open(config_path, 'r') as f:
        data = yaml.safe_load(f)

    # Trouver instance
    instance_data = next((i for i in data['instances'] if i['name'].lower() == instance_name.lower()), None)
    if not instance_data:
        print(f"Instance '{instance_name}' introuvable")
        return

    instance = AllDebridInstance(
        name=instance_data['name'],
        api_key=instance_data['api_key'],
        mount_path=instance_data['mount_path'],
        rate_limit=instance_data.get('rate_limit', 0.2),
        retry_attempts=instance_data.get('retry_attempts', 3),
        retry_backoff=instance_data.get('retry_backoff', 2.0),
        enabled=True
    )

    print(f"{'═'*60}")
    print(f"🐛 DEBUG: Test matching")
    print(f"{'═'*60}")
    print(f"Fichier: {test_file}")

    # Extraire nom torrent
    path = Path(test_file)
    mount = Path(instance.mount_path)

    try:
        relative = path.relative_to(mount)
        torrent_name = relative.parts[0]
        print(f"Torrent extrait: [{torrent_name}]\n")
    except ValueError:
        print("Erreur: fichier pas dans le mount")
        return

    # Chercher dans API
    async with AllDebridAPI(instance.api_key, instance.rate_limit, instance.retry_attempts, instance.retry_backoff) as api:
        try:
            magnets = await api.get_magnets()
            print(f"✓ {len(magnets)} torrents AllDebrid\n")

            magnet_id = api.find_magnet_id(torrent_name, magnets)

            if magnet_id:
                print(f"✅ TROUVÉ: ID={magnet_id}")
                matching = next((m for m in magnets if m['id'] == magnet_id), None)
                if matching:
                    print(f"   Filename: {matching.get('filename')}")
            else:
                print("❌ Aucune correspondance")
        except Exception as e:
            print(f"✗ Erreur API: {e}")


async def debug_list_torrents(config_path: Path, instance_name: str):
    """Mode debug : lister torrents AllDebrid"""
    with open(config_path, 'r') as f:
        data = yaml.safe_load(f)

    instance_data = next((i for i in data['instances'] if i['name'].lower() == instance_name.lower()), None)
    if not instance_data:
        print(f"Instance '{instance_name}' introuvable")
        return

    instance = AllDebridInstance(
        name=instance_data['name'],
        api_key=instance_data['api_key'],
        mount_path=instance_data['mount_path'],
        rate_limit=instance_data.get('rate_limit', 0.2),
        retry_attempts=instance_data.get('retry_attempts', 3),
        retry_backoff=instance_data.get('retry_backoff', 2.0),
        enabled=True
    )

    print(f"📋 Liste torrents AllDebrid ({instance.name}):\n")

    async with AllDebridAPI(instance.api_key, instance.rate_limit, instance.retry_attempts, instance.retry_backoff) as api:
        try:
            magnets = await api.get_magnets()
            for magnet in magnets:
                print(f"ID: {magnet['id']} | {magnet.get('filename', 'N/A')}")
        except Exception as e:
            print(f"Erreur: {e}")


# ============================================================================
# MAIN
# ============================================================================

async def main():
    """Point d'entrée principal"""
    parser = argparse.ArgumentParser(
        description="Multi-Instance AllDebrid Orphan Manager"
    )
    parser.add_argument('--execute', action='store_true', help="Mode suppression")
    parser.add_argument('--yes', '-y', action='store_true', help="Suppression auto sans confirmation")
    parser.add_argument('--instance', type=str, help="Traiter une seule instance")
    parser.add_argument('--test-match', type=str, help="Tester matching d'un fichier")
    parser.add_argument('--debug-list', action='store_true', help="Lister torrents AllDebrid")
    parser.add_argument('--config', type=Path, default=Path(__file__).parent / 'config.yaml', help="Fichier config")

    args = parser.parse_args()

    # Modes debug
    if args.test_match:
        instance = args.instance or 'alldebrid_radarr'
        await debug_test_match(args.config, args.test_match, instance)
        return 0

    if args.debug_list:
        instance = args.instance or 'alldebrid_radarr'
        await debug_list_torrents(args.config, instance)
        return 0

    # Mode normal
    try:
        manager = OrphanManager(args.config)
        await manager.run(
            execute_mode=args.execute,
            auto_yes=args.yes,
            target_instance=args.instance
        )
        return 0
    except KeyboardInterrupt:
        # Nettoyage des sessions aiohttp ouvertes
        try:
            await AllDebridAPI.close_all_sessions()
        except Exception:
            pass
        print("\nInterrompu par l'utilisateur (CTRL-C).", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Erreur: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        # Protection supplémentaire si l'interruption survient en-dehors de main
        # Tentative de nettoyage des sessions aiohttp
        try:
            asyncio.run(AllDebridAPI.close_all_sessions())
        except Exception:
            pass
        print("\nInterrompu par l'utilisateur (CTRL-C). Arrêt.", file=sys.stderr)
        sys.exit(130)
