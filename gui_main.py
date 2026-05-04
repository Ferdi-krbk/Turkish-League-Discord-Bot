import sys
import os
import time

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

try:
    # 2. LOG ENVIRONMENT INFO
    log_path = get_log_path()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] --- BAŞLATMA DENEMESİ ---\n")
        f.write(f"EXE Yolu: {sys.executable}\n")
        f.write(f"Çalışma Dizini: {os.getcwd()}\n")
        f.write(f"Python Sürümü: {sys.version}\n")

    import eel
    import asyncio
    import threading
    import traceback
    from core import database
except Exception as e:
    import traceback
    error_msg = f"Kritik Yükleme Hatası: {e}\n\n{traceback.format_exc()}"
    with open(get_log_path(), "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] IMPORT ERROR: {error_msg}\n")
    show_error_popup("Başlatma Hatası", f"Kütüphaneler yüklenemedi: {e}")
    sys.exit(1)

# Add project root and EXE directory to sys.path
if getattr(sys, 'frozen', False):
    exe_dir = os.path.dirname(sys.executable)
    sys.path.insert(0, exe_dir)
    # Also add the internal bundle path
    if hasattr(sys, '_MEIPASS'):
        sys.path.append(sys._MEIPASS)
else:
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
def get_match_history(limit=50):
    return run_async(database.get_recent_matches(limit))

@eel.expose
def generate_fixture():
    run_async(database.generate_fixture())
    return "Fikstür oluşturuldu!"

@eel.expose
def reset_database():
    run_async(database.reset_database())
    return "Veritabanı sıfırlandı!"

@eel.expose
def reset_europe_tournaments():
    """Reset button for European tournaments ONLY"""
    run_async(database.reset_europe_tournaments())
    return "Avrupa turnuvaları sıfırlandı!"

@eel.expose
def add_player(team_name, player_name, position, age, ovr, market_value, nationality):
    """Adds a new player to the database via UI"""
    try:
        run_async(database.add_player(team_name, player_name, position, age, ovr, market_value, nationality))
        return {"status": "success", "message": f"{player_name} başarıyla eklendi!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@eel.expose
def delete_player(player_id):
    run_async(database.delete_player(player_id))
    return "Oyuncu silindi!"

@eel.expose
def update_player(player_id, name, position, age, ovr):
    run_async(database.update_player(player_id, name, position, age, ovr))
    return "Oyuncu güncellendi!"

@eel.expose
def run_command(command, channel="exxen-1"):
    """Saves a command to database to be picked up by the Discord bot"""
    run_async(database.add_gui_command(command, channel))
    return f"Komut gönderildi: {command}"

@eel.expose
def get_bot_status():
    """Returns lock status as a proxy for bot status"""
    import os
    if os.path.exists("bot.lock"):
        return "Online"
    return "Offline"

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    if getattr(sys, 'frozen', False):
        # In onefolder build, _internal is where assets are.
        # But if we use --add-data, PyInstaller 6+ often maps it directly or in _internal
        base_path = os.path.join(os.path.dirname(sys.executable), "_internal")
        if not os.path.exists(base_path):
            base_path = os.path.dirname(sys.executable)
        
        # If we have _MEIPASS (onefile), use it
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
            
        res_path = os.path.join(base_path, relative_path)
    else:
        res_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)
    
    return res_path

def start_bot():
    """Starts the Discord bot in a background thread within the same process."""
    try:
        # Force gui-mode so main.py handles logging/watchdog correctly
        if "--gui-mode" not in sys.argv:
            sys.argv.append("--gui-mode")
            
        from main import bot
        import config
        import traceback
        
        def bot_thread_func():
            log_path = get_log_path()
            
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [BotThread] Starting...\n")
            
            try:
                bot.run(config.BOT_TOKEN)
            except Exception as e:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [BotThread] CRITICAL ERROR: {e}\n")
                    f.write(traceback.format_exc())
                    f.write("\n" + "="*50 + "\n")
                
                # Show specific popup for Token error
                if "Improper token" in str(e) or "Unauthorized" in str(e):
                    show_error_popup("Discord Bağlantı Hatası", "Bot Tokenı (config.py/.env) geçersiz veya hatalı.\nLütfen ayarları kontrol edin.")
                else:
                    show_error_popup("Bot Hatası", f"Bot çalışırken bir hata oluştu: {e}")

        bot_thread = threading.Thread(target=bot_thread_func, daemon=True)
        bot_thread.start()
        print("[Launcher] Discord bot started in background thread.")
        return bot_thread

    except Exception as e:
        import traceback
        log_path = get_log_path()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Failed to start bot thread: {e}\n")
            f.write(traceback.format_exc())
        return None

def start_eel():
    """Initializes and starts the Eel web interface."""
    # Start bot in background
    start_bot()

    log_path = get_log_path()
    eel.init(get_resource_path('web_ui'))
    try:
        # Try mode='edge' first, it's very reliable on Windows 10/11
        eel.start('index.html', size=(1280, 800), mode='edge', port=0) 
    except Exception as e1:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Edge start failed, trying default: {e1}\n")
        try:
            # Fallback to default browser (which uses different launch logic)
            eel.start('index.html', size=(1280, 800), port=0)
        except Exception as e2:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Final Eel start failure: {e2}\n")
            show_error_popup("Arayüz Başlatılamadı", f"Tarayıcı hatası: {e2}\nLütfen Chrome veya Edge yüklü olduğundan emin olun.")
    finally:
        print("UI Closed.")

if __name__ == "__main__":
    log_path = get_log_path()
    
    try:
        # 1. Ensure database is initialized
        run_async(database.init_db())
        
        # 2. Start Eel GUI
        start_eel()
    except Exception as e:
        import traceback
        error_msg = f"Kritik Hata: {e}\n\n{traceback.format_exc()}"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] RUNTIME ERROR: {error_msg}\n")
        show_error_popup("Uygulama Hatası", "Uygulama çalışırken bir hata oluştu.\nLütfen launcher_error.log dosyasını kontrol edin.")
        sys.exit(1)
