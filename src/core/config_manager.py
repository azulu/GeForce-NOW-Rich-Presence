import logging
from pathlib import Path
from typing import Dict, Optional
from src.core.utils import safe_json_load, save_json, CONFIG_DIR, USER_DATA_DIR
from src.core.utils import get_lang_from_registry, load_locale

try:
    LANG = get_lang_from_registry()
    TEXTS = load_locale(LANG)
except Exception:
    import os
    LANG = os.getenv('GEFORCE_LANG', 'en')
    TEXTS = load_locale(LANG)


logger = logging.getLogger('geforce_presence')

class ConfigManager:
    def __init__(self, config_path_file: Path):
        self.config_path_file = Path(config_path_file)
        self.games_config: Dict = {}
        self.games_config_path: Optional[Path] = None
        self.app_settings: Dict = {
            "start_with_windows": False,
            "start_gfn_on_launch": True,
            "start_discord_on_launch": False,
            "get_cookie_on_launch": False,
            "show_lobby_status": True
        }
        self.app_settings_path = USER_DATA_DIR / "app_settings.json"
        self._load()
    def _load(self):
        # Ruta fija al archivo que siempre queremos cargar
        fixed_path = CONFIG_DIR / "games_config_merged.json"
        backup_path = CONFIG_DIR / "games_config_merged_backup.json"
        
        # Migrate app_settings.json from legacy CONFIG_DIR if not present in USER_DATA_DIR
        if not self.app_settings_path.exists():
            legacy_path = CONFIG_DIR / "app_settings.json"
            if legacy_path.exists():
                try:
                    import shutil
                    shutil.copy2(str(legacy_path), str(self.app_settings_path))
                    logger.info("Migrated app_settings.json from legacy CONFIG_DIR to USER_DATA_DIR.")
                except Exception as e:
                    logger.error(f"Failed to migrate legacy app_settings.json: {e}")

        # Cargar app_settings.json
        if self.app_settings_path.exists():
            data_settings = safe_json_load(self.app_settings_path)
            if isinstance(data_settings, dict):
                # Update defaults with loaded settings
                self.app_settings.update(data_settings)
        else:
            save_json(self.app_settings, self.app_settings_path)

        from src.core.utils import validate_games_config, download_from_github
        data = None

        # 1. Intentar cargar el archivo principal
        if fixed_path.exists():
            data = safe_json_load(fixed_path)
            if not validate_games_config(data):
                logger.warning("⚠️ games_config_merged.json is corrupt or invalid.")
                data = None

        # 2. Intentar cargar copia de respaldo local (backup)
        if data is None and backup_path.exists():
            data = safe_json_load(backup_path)
            if validate_games_config(data):
                logger.info("ℹ️ Loading local backup copy of games_config_merged.json")
                save_json(data, fixed_path)  # Restaurar el archivo principal
            else:
                logger.warning("⚠️ Local backup copy games_config_merged_backup.json is also corrupt.")
                data = None

        # 3. Intentar descargar respaldo desde GitHub
        if data is None:
            data = download_from_github("games_config_merged.json")
            if validate_games_config(data):
                logger.info("✅ Successfully downloaded games_config_merged.json from GitHub.")
                save_json(data, fixed_path)  # Guardar como archivo principal
            else:
                logger.warning("⚠️ Could not get a valid games_config_merged.json from GitHub.")
                data = None

        # Aplicar los datos cargados o iniciar con un diccionario vacío
        if data is not None:
            self.games_config = data
            self.games_config_path = fixed_path
            logger.info(TEXTS.get("games_config_merged", "✅ games_config_merged.json cargado automáticamente: {fixed_path}").format(fixed_path=fixed_path))
            self._log_games_summary()
            
            # Crear copia de respaldo local si no existe
            if not backup_path.exists():
                try:
                    save_json(data, backup_path)
                    logger.info("💾 Local backup created at games_config_merged_backup.json")
                except Exception as e:
                    logger.error(f"Could not save the backup: {e}")
        else:
            logger.error("❌ All methods of loading games_config_merged.json failed. Loading an empty JSON.")
            self.games_config = {}
            self.games_config_path = fixed_path

    def _log_games_summary(self, verbose=False):
        count = len(self.games_config)
        if count == 0:
            logger.warning(TEXTS.get("no_games_found", "⚠️ No se encontraron juegos en la configuración."))
            return
        
        logger.info(TEXTS.get("games_loaded", "📦 Juegos cargados: {count}").format(count=count))

    def get_game_mapping(self):
        return self.games_config

    def get_setting(self, key: str, default=None):
        return self.app_settings.get(key, default)

    def set_setting(self, key: str, value):
        self.app_settings[key] = value
        save_json(self.app_settings, self.app_settings_path)
