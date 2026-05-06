import sys
import os
import time
import eel
import asyncio
import threading
import traceback
from core import database

# 1. SETUP ERROR LOGGING IMMEDIATELY (Before any imports)
def get_log_path():
    base_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "launcher_error.log")

def show_error_popup(title, message):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except:
        pass

# Add project root and EXE directory to sys.path
if getattr(sys, 'frozen', False):
    exe_dir = os.path.dirname(sys.executable)
    sys.path.insert(0, exe_dir)
    if hasattr(sys, '_MEIPASS'):
        sys.path.append(sys._MEIPASS)
else:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Background Event Loop Logic
_loop = asyncio.new_event_loop()

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

_thread = threading.Thread(target=start_background_loop, args=(_loop,), daemon=True)
_thread.start()

# GUI Singleton Lock
GUI_LOCK_FILE = "gui.lock"

def release_gui_lock():
    if os.path.exists(GUI_LOCK_FILE):
        try:
            with open(GUI_LOCK_FILE, "r") as f:
                content = f.read().strip()
                if content and int(content) == os.getpid():
                    os.remove(GUI_LOCK_FILE)
        except:
            pass

def acquire_gui_lock():
    if os.path.exists(GUI_LOCK_FILE):
        try:
            with open(GUI_LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            try:
                os.kill(old_pid, 0)
                sys.exit(0)
            except OSError:
                release_gui_lock()
        except:
            release_gui_lock()
    with open(GUI_LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    import atexit
    atexit.register(release_gui_lock)

acquire_gui_lock()

def run_async(coro):
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result()

# --- EXPOSED FUNCTIONS ---

@eel.expose
def get_league_standings():
    return run_async(database.get_all_teams(league='Super Lig'))

@eel.expose
def get_league_top_scorers():
    return run_async(database.get_top_scorers(limit=10, competition='League'))

@eel.expose
def get_league_top_assists():
    return run_async(database.get_top_assists(limit=10, competition='League'))

@eel.expose
def get_league_suspensions():
    return run_async(database.get_league_suspensions())

@eel.expose
def get_team_details(team_name):
    team = run_async(database.get_team(team_name))
    players = run_async(database.get_team_players(team_name))
    if team:
        try:
            import json
            teams_path = os.path.join(os.path.dirname(__file__), "data", "teams.json")
            if os.path.exists(teams_path):
                with open(teams_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for t in data.get("teams", []):
                        if t.get("name", "").lower() == team_name.lower():
                            team["city"] = t.get("city", "Belirtilmemiş")
                            team["stadium"] = t.get("stadium", "Belirtilmemiş")
                            break
        except Exception as e:
            print(f"Error: {e}")
    return {"team": team, "players": players}

@eel.expose
def get_europe_data():
    async def _get_all():
        data = {}
        for key, name in [("UCL", "Champions League"), ("UEL", "Europa League"), ("UECL", "Conference League")]:
            tid = await database.get_tournament_by_name(name)
            if tid:
                standings = await database.get_tournament_league_standings(tid)
                fixtures = await database.get_tournament_fixtures(tid)
                data[key] = {"standings": standings, "fixtures": fixtures}
            else:
                data[key] = {"standings": [], "fixtures": []}
        return data
    return run_async(_get_all())

@eel.expose
def get_league_fixtures(round_no=None):
    return run_async(database.get_fixtures(round_no))

@eel.expose
def get_recent_transfers(limit=50):
    return run_async(database.get_recent_transfers(limit))

@eel.expose
def cancel_transfer(transfer_id):
    run_async(database.cancel_transfer(transfer_id))
    return True

@eel.expose
def get_bot_logs():
    try:
        if os.path.exists("bot.log"):
            with open("bot.log", "r", encoding="utf-8", errors="replace") as f:
                return "".join(f.readlines()[-200:])
        return "Log dosyası bulunamadı."
    except Exception as e:
        return str(e)

@eel.expose
def get_all_teams_gui():
    return run_async(database.get_all_teams())

@eel.expose
def refresh_team_stats(team_name):
    run_async(database.calculate_team_overall(team_name))
    return True

@eel.expose
def add_player_gui(name, team, position, overall, market_value, age):
    run_async(database.add_player(name, team, position, overall, market_value, age))
    return True

@eel.expose
def edit_player_gui(player_id, name, position, overall, market_value, age):
    run_async(database.edit_player(player_id, name, position, overall, market_value, age))
    return True

@eel.expose
def delete_player_gui(player_id):
    run_async(database.delete_player(player_id))
    return True

@eel.expose
def sim_match(match_id, match_type='League'):
    prefix = "L" if match_type == 'League' else "E"
    cmd = f"!sim {prefix}-{match_id}"
    channel = "beinsports-1" if match_type == 'League' else "exxen-1"
    run_async(database.add_gui_command(cmd, channel))
    return True

@eel.expose
def trigger_live_sim(home, away, match_type='League', is_live=True):
    mode = "live" if is_live else "hızlı"
    cmd = f"!livesim {home} - {away} {mode}"
    channel = "beinsports-1" if match_type == 'League' else "exxen-1"
    run_async(database.add_gui_command(cmd, channel))
    return True

@eel.expose
def sim_all_europe(tournament_type, round_name):
    t_name = {"UCL": "Champions League", "UEL": "Europa League", "UECL": "Conference League"}.get(tournament_type, tournament_type)
    run_async(database.add_gui_command(f"!kupasim {t_name} {round_name}", "exxen-1"))
    return True

@eel.expose
def sim_all_league(round_no):
    run_async(database.add_gui_command(f"!haftayi_oynat {round_no}", "beinsports-1"))
    return True

@eel.expose
def reset_league_standings_gui():
    run_async(database.reset_league_standings())
    return True

@eel.expose
def reset_europe_tournaments_gui():
    run_async(database.reset_europe_tournaments())
    return True

@eel.expose
def setup_europe_gui(tournament_name, round_name, team_names, legs=2):
    run_async(database.setup_europe_from_gui(tournament_name, round_name, team_names, legs))
    return True

@eel.expose
def handle_promotion_relegation_gui(relegated_names, promoted_names):
    run_async(database.handle_promotion_relegation(relegated_names, promoted_names))
    return True

@eel.expose
def generate_league_fixtures_gui():
    run_async(database.generate_league_fixtures())
    return True

@eel.expose
def get_bot_status():
    return "Online" if os.path.exists("bot.lock") else "Offline"

# --- HELPERS & BOOT ---

def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.join(os.path.dirname(sys.executable), "_internal")
        if not os.path.exists(base_path): base_path = os.path.dirname(sys.executable)
        return os.path.join(base_path, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def start_bot():
    try:
        if "--gui-mode" not in sys.argv: sys.argv.append("--gui-mode")
        from main import bot
        import config
        threading.Thread(target=lambda: bot.run(config.BOT_TOKEN), daemon=True).start()
    except Exception as e:
        print(f"Bot error: {e}")

def start_eel():
    start_bot()
    eel.init(get_resource_path('web_ui'))
    try:
        eel.start('index.html', size=(1280, 800), mode='edge', port=0)
    except:
        eel.start('index.html', size=(1280, 800), port=0)

if __name__ == "__main__":
    try:
        run_async(database.init_db())
        start_eel()
    except Exception as e:
        show_error_popup("Hata", str(e))
        sys.exit(1)
