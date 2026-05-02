import eel
import asyncio
import os
import sys
import threading
from core import database

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Background Event Loop Logic
_loop = asyncio.new_event_loop()

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

# Start the loop in a background thread
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
            
            # Check if process is alive
            try:
                os.kill(old_pid, 0)
                print(f"[!] GUI zaten çalışıyor! (PID: {old_pid})")
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
    """Run a coroutine in our background thread's event loop and wait for result"""
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result()

# Expose Python functions to Eel
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
    
    # teams.json'dan şehir ve stadyum bilgilerini ekle
    if team:
        try:
            import json
            import os
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
            print(f"Error loading city/stadium: {e}")
        
    return {"team": team, "players": players}

@eel.expose
def refresh_team_stats(team_name):
    """Refreshes OVRs and total power for a specific team"""
    new_ovr = run_async(database.calculate_team_overall(team_name))
    return new_ovr


@eel.expose
def add_player_gui(name, team, position, overall, market_value, age):
    return run_async(database.add_player(name, team, position, int(overall), int(market_value), int(age)))

@eel.expose
def delete_player_gui(player_id):
    return run_async(database.delete_player(int(player_id)))

@eel.expose
def edit_player_gui(player_id, name, position, overall, market_value, age):
    return run_async(database.edit_player(int(player_id), name, position, int(overall), int(market_value), int(age)))

@eel.expose
def get_europe_data():
    try:
        # These can also be run in parallel for even more speed
        ucl_id = run_async(database.get_tournament_by_name("UCL"))
        uel_id = run_async(database.get_tournament_by_name("UEL"))
        uecl_id = run_async(database.get_tournament_by_name("UECL"))
        
        data = {
            "UCL": {
                "fixtures": run_async(database.get_tournament_fixtures(ucl_id)) if ucl_id else [],
                "standings": run_async(database.get_tournament_league_standings(ucl_id)) if ucl_id else []
            },
            "UEL": {
                "fixtures": run_async(database.get_tournament_fixtures(uel_id)) if uel_id else [],
                "standings": run_async(database.get_tournament_league_standings(uel_id)) if uel_id else []
            },
            "UECL": {
                "fixtures": run_async(database.get_tournament_fixtures(uecl_id)) if uecl_id else [],
                "standings": run_async(database.get_tournament_league_standings(uecl_id)) if uecl_id else []
            }
        }
        return data
    except Exception as e:
        print(f"Error in get_europe_data: {e}")
        return {"UCL": {"fixtures": [], "standings": []}, "UEL": {"fixtures": [], "standings": []}, "UECL": {"fixtures": [], "standings": []}}

@eel.expose
def get_recent_transfers():
    return run_async(database.get_recent_transfers(limit=20))

@eel.expose
def cancel_transfer(transfer_id):
    return run_async(database.cancel_transfer(transfer_id))

@eel.expose
def get_bot_logs():
    """Reads the last 100 lines from bot.log"""
    try:
        log_path = os.path.join(os.path.dirname(__file__), "bot.log")
        if not os.path.exists(log_path):
            return "Log dosyası henüz oluşturulmadı."
        
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            return "".join(lines[-100:]) # Return last 100 lines
    except Exception as e:
        return f"Log okuma hatası: {e}"

@eel.expose
def get_league_fixtures(round_no=None):
    if round_no is None:
        round_no = run_async(database.get_latest_played_round()) + 1
    return run_async(database.get_fixtures(round_no=round_no))

@eel.expose
def sim_match(match_id, competition_type="League"):
    """Simulate a single match (League or Tournament)"""
    return run_async(_sim_single_match(match_id, competition_type))

@eel.expose
def sim_all_europe(tournament_name, round_name):
    """Simulate all pending matches in a tournament round"""
    return run_async(_sim_all_europe_logic(tournament_name, round_name))

@eel.expose
def sim_all_league(round_no):
    """Simulate all pending matches in a league round"""
    return run_async(_sim_all_league_logic(round_no))

async def _sim_all_league_logic(round_no):
    try:
        async with database.get_db() as db:
            db.row_factory = aiosqlite_row_factory
            async with db.execute(
                "SELECT id FROM matches WHERE round_no = ? AND status = 'Pending'",
                (round_no,)
            ) as cursor:
                pending = await cursor.fetchall()
        
        for p in pending:
            await _sim_single_match(p['id'], "League")
        return True
    except Exception as e:
        print(f"Error in _sim_all_league_logic: {e}")
        return False

@eel.expose
def trigger_live_sim(home_team, away_team, competition_type="Europe", is_live=True):
    """Queue a match command for the bot (Live or Fast)"""
    comp_str = competition_type
    if competition_type == "League":
        comp_str = "Lig"
    elif competition_type == "Europe":
        # Fallback if specific type isn't passed
        comp_str = "UCL"
    
    command = f"!mac {home_team} vs {away_team} {comp_str}"
    if is_live:
        command += " Live"
        
    channel = 'beinsports-1' if competition_type == 'League' else 'exxen-1'
    return run_async(database.add_gui_command(command, channel=channel))

async def _sim_single_match(match_id, comp_type):
    import random
    try:
        # 1. Get match info
        async with database.get_db() as db:
            db.row_factory = aiosqlite_row_factory
            table = "matches" if comp_type == "League" else "tournament_fixtures"
            async with db.execute(f"SELECT * FROM {table} WHERE id = ?", (match_id,)) as cursor:
                match = await cursor.fetchone()
                if not match or match['status'] == 'Played': return False
        
        h_name, a_name = match['home_team'], match['away_team']
        
        # 2. Get ratings
        h_data = await database.get_team(h_name)
        a_data = await database.get_team(a_name)
        h_ovr = h_data['overall'] if h_data else 75
        a_ovr = a_data['overall'] if a_data else 75
        
        # 3. Simple Math Sim (Big Team Bias)
        BIG_TEAMS = ["Real Madrid", "Manchester City", "Bayern Munich", "PSG", "Liverpool", "Barcelona", "Inter", "Juventus", "AC Milan", "Galatasaray", "Fenerbahçe", "Beşiktaş", "Trabzonspor", "Kocaelispor"]
        h_bias = 1.25 if any(bt in h_name for bt in BIG_TEAMS) else 1.0
        a_bias = 1.25 if any(bt in a_name for bt in BIG_TEAMS) else 1.0
        
        h_str = (h_ovr * h_bias * 1.05) / 75.0 # Home advantage 1.05
        a_str = (a_ovr * a_bias) / 75.0
        
        h_goals = random.choices([0,1,2,3,4,5], weights=[max(5, 20/h_str), 35*h_str, 20*h_str, 10, 3, 1])[0]
        a_goals = random.choices([0,1,2,3,4,5], weights=[max(5, 30/a_str), 40*a_str, 15*a_str, 7, 2, 1])[0]
        
        # 4. Record
        comp_name = comp_type
        if comp_type in ["UCL", "UEL", "UECL"]:
            comp_name = comp_type

        
        await database.record_match(h_name, a_name, h_goals, a_goals, comp_name, "Clear", [], leg=match.get('leg', 1), events=[])
        return True
    except Exception as e:
        print(f"Error in _sim_single_match: {e}")
        return False

async def _sim_all_europe_logic(tournament_name, round_name):
    try:
        t_id = await database.get_tournament_by_name(tournament_name)
        if not t_id: return False
        
        async with database.get_db() as db:
            db.row_factory = aiosqlite_row_factory
            async with db.execute(
                "SELECT id FROM tournament_fixtures WHERE tournament_id = ? AND round = ? AND status = 'Pending'",
                (t_id, round_name)
            ) as cursor:
                pending = await cursor.fetchall()
        
        for p in pending:
            await _sim_single_match(p['id'], tournament_name)
        return True
    except Exception as e:
        print(f"Error in _sim_all_europe_logic: {e}")
        return False

def aiosqlite_row_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

@eel.expose
def reset_league_standings_gui():
    return run_async(database.reset_league_standings())

@eel.expose
def reset_europe_tournaments_gui():
    return run_async(database.reset_europe_tournaments())

@eel.expose
def get_all_teams_gui():
    return run_async(database.get_all_teams_simple())

@eel.expose
def setup_europe_gui(tournament_name, round_name, team_names, legs):
    return run_async(database.setup_europe_from_gui(tournament_name, round_name, team_names, int(legs)))

@eel.expose
def handle_promotion_relegation_gui(relegated, promoted):
    return run_async(database.handle_promotion_relegation(relegated, promoted))

@eel.expose
def generate_league_fixtures_gui():
    return run_async(database.generate_league_fixtures())

import subprocess

def start_bot():
    """Starts the Discord bot in a separate background process"""
    try:
        # Use sys.executable to ensure we use the same python environment
        # Birlikte tek CMD penceresinde çalışmalar için CREATE_NEW_CONSOLE kaldırıldı.
        # CREATE_NO_WINDOW eklenerek botun arka planda tamamen sessiz çalışması sağlandı.
        bot_process = subprocess.Popen(
            [sys.executable, "main.py", "--gui-mode", "--parent-pid", str(os.getpid())],
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        print("[Launcher] Discord bot started in background (hidden).")
        return bot_process

    except Exception as e:
        print(f"[Launcher] Failed to start bot: {e}")
        return None

def start_eel():
    # Start the bot automatically
    bot_process = start_bot()
    
    eel.init('web_ui')
    try:
        import time
        time.sleep(1)
        eel.start('index.html', size=(1280, 800), port=0) 
    except (SystemExit, KeyboardInterrupt):
        pass
    except Exception as e:
        print(f"[Launcher] Eel Error: {e}")
        # Do NOT restart eel here - that causes an infinite loop
    finally:
        if bot_process and bot_process.poll() is None:
            print("[Launcher] Shutting down Discord bot...")
            bot_process.terminate()
            try:
                bot_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                bot_process.kill()
        print("UI Closed.")


if __name__ == "__main__":
    # Ensure database is initialized
    run_async(database.init_db())
    start_eel()
