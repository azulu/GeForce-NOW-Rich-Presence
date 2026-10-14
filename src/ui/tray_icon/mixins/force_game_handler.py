import os
import logging
import time
import threading
from typing import TYPE_CHECKING

from PyQt5.QtWidgets import QDialog, QSystemTrayIcon, QApplication
from src.core.utils import get_lang_from_registry, load_locale
from ..dialogs import QuestListDialog, AskGameDialog, MatchSelectionDialog

try:
    LANG = get_lang_from_registry()
    TEXTS = load_locale(LANG)
except Exception:
    LANG = os.getenv('GEFORCE_LANG', 'en')
    TEXTS = load_locale(LANG)

logger = logging.getLogger('geforce_presence')

if TYPE_CHECKING:
    from ..tray_icon import SystemTrayIcon
    Base = SystemTrayIcon
else:
    Base = object

class ForceGameHandlerMixin(Base):
    def toggle_force_game(self):
        # 0. Check for running quests
        if getattr(self.pm, "active_quests", None):
            dlg = QuestListDialog(self.pm)
            dlg.set_add_game_callback(self.process_quest_input)
            dlg.exec_()
            return

        if self.pm.forced_game:
            self.pm.stop_force_game()
            self.showMessage("OK", TEXTS.get("force_game_stopped", "Game forcing stopped."), QSystemTrayIcon.Information, 3000)
            self.update_menu()
            return

        dialog = AskGameDialog(title=TEXTS.get("force_game", "Force Game"), message=TEXTS.get("game_name", "Game Name:"))
        
        def on_quest_opened():
            dialog.reject()
            dlg = QuestListDialog(self.pm)
            dlg.set_add_game_callback(self.process_quest_input)
            dlg.exec_()
            
        def on_update_list_opened():
            dialog.set_updating(True)
            self.showMessage("Info", TEXTS.get("downloading", "Downloading..."), QSystemTrayIcon.Information, 4000)
            QApplication.processEvents()

            def on_progress(cur, tot):
                dialog.update_download_progress(cur, tot)
                QApplication.processEvents()

            self.pm.download_progress.connect(on_progress)
            try:
                apps = self.pm._fetch_discord_apps_cached(force_download=True)
            finally:
                try:
                    self.pm.download_progress.disconnect(on_progress)
                except Exception:
                    pass

            if apps:
                dialog.set_update_result(True, len(apps))
                self.showMessage("Info", TEXTS.get("force_list_updated", "Game list updated successfully ({count} apps).").replace("{count}", str(len(apps))), QSystemTrayIcon.Information, 3000)
            else:
                dialog.set_update_result(False)
                self.showMessage("Error", TEXTS.get("force_list_update_error", "Could not update the Discord game list."), QSystemTrayIcon.Warning, 4000)

        dialog.quest_mode_requested.connect(on_quest_opened)
        dialog.update_list_requested.connect(on_update_list_opened)

        if dialog.exec_() == QDialog.Accepted:
            game_name = dialog.get_game_name()
            if not game_name:
                return
            
            # Normal force game
            self.process_force_game(game_name)

    def process_quest_input(self, game_name):
        """
        Similar to process_force_game but for quests.
        Returns True if a game was successfully queued/started.
        """
        # Reuse search logic
        gm = self.pm.games_map or {}
        local_candidates = [k for k in gm if game_name.lower() in k.lower()]
        
        options = []
        if local_candidates:
            for k in local_candidates:
                score = 1.0 if k.lower() == game_name.lower() else 0.8
                options.append({"name": k, "id": gm[k].get("client_id"), "exe": gm[k].get("executable_path"), "score": score})
        
        discord_options = self.pm._find_discord_matches(game_name, max_candidates=50)
        for d_opt in discord_options:
            if not any(o["name"].lower() == d_opt["name"].lower() for o in options):
                options.append(d_opt)

        options.sort(key=lambda x: x.get("score", 0), reverse=True)
        options = options[:50]

        if not options:
            status = self.pm.check_discord_cache_status()
            if status["status"] == "MISSING" or status["hours"] > 168:
                self.showMessage(TEXTS.get("force_searching", "Searching..."), TEXTS.get("force_cache_miss", "Not found in cache (old/missing). Downloading recent data for '{game}'...").replace("{game}", game_name), QSystemTrayIcon.Information, 4000)
                QApplication.processEvents() 
                apps = self.pm._fetch_discord_apps_cached(force_download=True)
                
                if apps:
                    discord_options2 = self.pm._find_discord_matches(game_name, max_candidates=50)
                    for d_opt in discord_options2:
                        if not any(o["name"].lower() == d_opt["name"].lower() for o in options):
                            options.append(d_opt)
                
                options.sort(key=lambda x: x.get("score", 0), reverse=True)
                options = options[:50]
        
        if not options:
            self.showMessage("Info", TEXTS.get("force_no_matches", "No matches found."), QSystemTrayIcon.Information, 3000)
            return False

        # Show selection dialog
        sel_dialog = MatchSelectionDialog(TEXTS.get("quest_select_game", "Select Game (Quest)"), options)
        if sel_dialog.exec_() == QDialog.Accepted and sel_dialog.selected_match:
            match = sel_dialog.selected_match
            self.apply_quest_game(match)
            return True
        return False

    def apply_quest_game(self, match):
        name = match["name"]
        
        # Resolve exe: Discord match -> Local database config -> Generic fallback
        exe = match.get("exe")
        if not exe:
            local_entry = (self.pm.games_map or {}).get(name) or {}
            exe = local_entry.get("executable_path")
        if not exe:
            exe = f"{name}.exe"
        
        # Save cache
        self.pm._apply_discord_match(name, match)
        
        # Launch using PM
        self.pm.launch_quest_game(name, exe)

    def process_force_game(self, game_name):
        gm = self.pm.games_map or {}
        local_candidates = [k for k in gm if game_name.lower() in k.lower()]
        
        options = []
        if local_candidates:
            for k in local_candidates:
                score = 1.0 if k.lower() == game_name.lower() else 0.8
                options.append({"name": k, "id": gm[k].get("client_id"), "exe": gm[k].get("executable_path"), "score": score})
        
        # 1. Search in Discord (Local Cache First)
        discord_options = self.pm._find_discord_matches(game_name, max_candidates=50)
        for d_opt in discord_options:
            if not any(o["name"].lower() == d_opt["name"].lower() for o in options):
                options.append(d_opt)

        options.sort(key=lambda x: x.get("score", 0), reverse=True)
        options = options[:50]

        # 2. If no matches, force download and search again
        if not options:
            status = self.pm.check_discord_cache_status()
            if status["status"] == "MISSING" or status["hours"] > 168:
                self.showMessage(TEXTS.get("force_searching", "Searching..."), TEXTS.get("force_cache_miss_discord", "Not found in cache (old/missing). Downloading recent Discord data for '{game}'...").replace("{game}", game_name), QSystemTrayIcon.Information, 4000)
                QApplication.processEvents() # Keep UI responsive (mostly)
                
                # Update cache
                apps = self.pm._fetch_discord_apps_cached(force_download=True)
                
                # Search again
                if apps:
                    discord_options2 = self.pm._find_discord_matches(game_name, max_candidates=50)
                    for d_opt in discord_options2:
                        if not any(o["name"].lower() == d_opt["name"].lower() for o in options):
                            options.append(d_opt)
                
                options.sort(key=lambda x: x.get("score", 0), reverse=True)
                options = options[:50]

        if not options:
            self.showMessage("Info", TEXTS.get("force_no_matches_anywhere", "No matches in JSON or Discord (even after updating)."), QSystemTrayIcon.Information, 3000)
            return

        # Show selection dialog
        sel_dialog = MatchSelectionDialog(TEXTS.get("force_select_game", "Select game"), options)
        if sel_dialog.exec_() == QDialog.Accepted and sel_dialog.selected_match:
            match = sel_dialog.selected_match
            self.apply_force_game(match)

    def apply_force_game(self, match):
        name = match["name"]
        cid = match.get("id")
        
        # Resolve exe: Discord match -> Local database config -> Generic fallback
        exe = match.get("exe")
        if not exe:
            local_entry = (self.pm.games_map or {}).get(name) or {}
            exe = local_entry.get("executable_path")
        if not exe:
            exe = f"{name}.exe"
        
        # PERSISTENCE: Save the match to games_config_merged.json
        self.pm._apply_discord_match(name, match)
        
        self.pm.forced_game = {
            "name": name,
            "client_id": cid,
            "executable_path": exe
        }
        self.pm.last_game = dict(self.pm.forced_game)
        self.pm.current_game_start_time = int(time.time())
        logger.info(f"🎮 Juego forzado activado: {name} (id={cid})")

        if cid:
            try:
                def reconnect_after_delay():
                    time.sleep(11)
                
                self.pm._disconnect_rpc_temporarily()
                
                self.pm.client_id = cid
                self.pm._connect_rpc(cid)
                logger.info(f"🔁 RPC reON con client_id forzado: {cid}")
            except Exception as e:
                logger.error(f"❌ Error reconectando RPC tras forzar juego: {e}")
                threading.Thread(target=reconnect_after_delay, daemon=True).start()

        if exe:
            try:
                self.pm.close_fake_executable()
            except Exception as e:
                logger.debug(f"No se pudo cerrar ejecutable previo: {e}")
            self.pm.launch_fake_executable(exe, name)
        
        self.showMessage("OK", f"{TEXTS.get('tray_forced_game', 'Forced game')}: {name}", QSystemTrayIcon.Information, 3000)
        self.update_menu()
