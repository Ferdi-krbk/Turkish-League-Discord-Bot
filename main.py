import sys
import discord
from discord.ext import commands
from discord.app_commands import CommandTree
import config
from core import database
import os
import sys
import atexit

# Logging Redirection
LOG_FILE = "bot.log"

# Ensure UTF-8 for everything
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

if "--gui-mode" in sys.argv:
    # Clear log file on startup if in GUI mode
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("--- Bot Started via GUI ---\n")
    
    class Logger(object):
        def __init__(self):
            self.log = open(LOG_FILE, "a", encoding="utf-8", errors="replace")

        def write(self, message):
            # In GUI mode, we ONLY write to file to avoid Windows terminal encoding errors
            self.log.write(message)
            self.log.flush()

        def flush(self):
            self.log.flush()

    sys.stdout = Logger()
    sys.stderr = sys.stdout

# Singleton Lock Mechanism
LOCK_FILE = "bot.lock"

def release_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                content = f.read().strip()
                if content and int(content) == os.getpid():
                    os.remove(LOCK_FILE)
        except:
            pass

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            
            # Fast check: os.kill(pid, 0) raises OSError if the process is dead
            try:
                os.kill(old_pid, 0)
                # Process is alive → another instance is running, exit
                print(f"\n[!] HATA: Bot zaten çalışıyor! (PID: {old_pid})")
                print("[!] İkinci kopya kapatılıyor.\n")
                os._exit(1)
            except OSError:
                # Process is dead → stale lock, take it over
                print(f"[LOCK] Eski kilit dosyası bulundu (PID: {old_pid} - ölü). Temizleniyor...")
                release_lock()
        except Exception:
            # If reading/checking fails, just remove it
            release_lock()
            
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(release_lock)

acquire_lock()

# Windows terminal codepages can crash on emoji output; force UTF-8-safe printing.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Bot setup with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=commands.when_mentioned_or(config.COMMAND_PREFIX),
                intents=intents)

async def setup_hook():
    """Bot baslangic - cog ve db yukleme (online olmadan once)"""
    print("[DEBUG] setup_hook started")
    bot.remove_command("help") # Varsayılan help'i kaldır
    print("[DEBUG] Initializing database...")
    await database.init_db()
    # print("[DEBUG] Loading teams from JSON...")
    # await database.load_teams_from_json()
    # print("[DEBUG] Loading players from JSON...")
    # await database.load_players_from_json()
    
    extensions = [
        "cogs.match", "cogs.transfer", "cogs.info", 
        "cogs.interview", "cogs.tournament", "cogs.injury", "cogs.admin"
    ]
    
    for ext in extensions:
        print(f"[DEBUG] Loading extension: {ext}")
        await bot.load_extension(ext)
        
    print("[DEBUG] setup_hook completed")

bot.setup_hook = setup_hook

from discord.ext import tasks

@bot.event
async def on_ready():
    """Bot startup handler"""
    try:
        print("[DEBUG] on_ready started, syncing tree...")
        await bot.tree.sync()
        print("[DEBUG] tree.sync completed")
        print(f"[OK] Logged in as {bot.user}")
        print(f"[OK] Loaded {len(bot.cogs)} cogs")
        
        # Start GUI command listener
        if not gui_command_listener.is_running():
            gui_command_listener.start()
            
        # Start Parent Watchdog (if started via GUI)
        if "--gui-mode" in sys.argv:
            parent_watchdog.start()
            
    except Exception as e:
        print(f"[X] Startup error: {e}")

# Watchdog state
watchdog_retries = 0

@tasks.loop(seconds=5.0)
async def parent_watchdog():
    """Checks if the parent process (GUI) is still alive"""
    global watchdog_retries
    
    parent_pid = None
    if "--parent-pid" in sys.argv:
        try:
            idx = sys.argv.index("--parent-pid")
            parent_pid = int(sys.argv[idx + 1])
            # print(f"[WATCHDOG] Explicit parent PID received: {parent_pid}")
        except Exception as e:
            print(f"[WATCHDOG] Argument error: {e}")
    
    if parent_pid is None:
        parent_pid = os.getppid()
        # print(f"[WATCHDOG] Falling back to os.getppid(): {parent_pid}")

    # Use a more stable check for Windows
    is_alive = True
    try:
        os.kill(parent_pid, 0)
    except OSError:
        # Double check with tasklist before killing
        try:
            import subprocess
            # Use CREATE_NO_WINDOW to prevent the black CMD window flash on Windows
            check = subprocess.run(
                ["tasklist", "/fi", f"PID eq {parent_pid}", "/nh"], 
                capture_output=True, 
                text=True, 
                timeout=2,
                creationflags=0x08000000 # CREATE_NO_WINDOW
            )
            if str(parent_pid) not in check.stdout:
                is_alive = False
        except:
            is_alive = False # If tasklist fails, assume dead for safety

    if not is_alive:
        watchdog_retries += 1
        if watchdog_retries >= 3: # Only kill after 3 consecutive failures (15 seconds)
            print(f"[WATCHDOG] Parent process ({parent_pid}) definitely closed. Killing bot...")
            os._exit(0)
    else:
        watchdog_retries = 0 # Reset on success

@tasks.loop(seconds=2.0)
async def gui_command_listener():
    """Listens for commands triggered from the GUI dashboard"""
    try:
        async with database.get_db() as db:
            db.row_factory = aiosqlite_row_factory
            async with db.execute("SELECT * FROM gui_commands WHERE status = 'Pending' LIMIT 1") as cursor:
                cmd_data = await cursor.fetchone()
                
                if cmd_data:
                    cmd_id = cmd_data['id']
                    command_text = cmd_data['command']
                    channel_name = cmd_data.get('channel', 'exxen-1')
                    
                    print(f"[GUI] Executing command: {command_text} in {channel_name}")
                    
                    # Mark as processing
                    await db.execute("UPDATE gui_commands SET status = 'Processing' WHERE id = ?", (cmd_id,))
                    await db.commit()
                    
                    # Find channel
                    channel = None
                    for guild in bot.guilds:
                        channel = discord.utils.get(guild.text_channels, name=channel_name)
                        if channel: break
                    
                    if channel:
                        # Create a fake context to invoke the command
                        # Or just send a message that triggers the bot's on_message
                        # The safest way is to send a message as the bot and have it handle it, 
                        # but bots don't usually trigger themselves.
                        # Better: Use bot.process_commands with a fake message.
                        
                        class FakeMessage:
                            def __init__(self, content, channel):
                                self.content = content
                                self.channel = channel
                                self.author = channel.guild.me # This is a Member object with permissions
                                self.guild = channel.guild
                                self.id = 0
                                self.attachments = []
                                self.embeds = []
                                self.mentions = []
                                self.role_mentions = []
                                self.channel_mentions = []
                                self._state = channel._state
                                self.created_at = discord.utils.utcnow()
                        
                        fake_msg = FakeMessage(command_text, channel)
                        ctx = await bot.get_context(fake_msg)
                        
                        # If ctx.command is None, try manual lookup
                        if ctx.command is None:
                            cmd_name = command_text.split()[0].lstrip('!')
                            ctx.command = bot.get_command(cmd_name)
                        
                        if ctx.command:
                            print(f"[GUI] Invoking command: {ctx.command.name} as {fake_msg.author}")
                            await bot.invoke(ctx)
                            await db.execute("UPDATE gui_commands SET status = 'Completed' WHERE id = ?", (cmd_id,))
                        else:
                            print(f"[GUI] Error: Command not found for '{command_text}'")
                            await db.execute("UPDATE gui_commands SET status = 'Error', error = 'Command not found' WHERE id = ?", (cmd_id,))
                    else:
                        print(f"[GUI] Error: Channel {channel_name} not found.")
                        await db.execute("UPDATE gui_commands SET status = 'Error', error = 'Channel not found' WHERE id = ?", (cmd_id,))
                    
                    await db.commit()
    except Exception as e:
        print(f"[GUI] Error in listener: {e}")

def aiosqlite_row_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

@bot.command(name="load_cog")
@commands.is_owner()
async def load_cog(ctx, extension: str):
    """Reload a cog (owner only)"""
    try:
        await bot.load_extension(f"cogs.{extension}")
        await ctx.send(f"[OK] Loaded {extension}")
    except Exception as e:
        await ctx.send(f"[X] Error: {e}")

@bot.command(name="reload_cog")
@commands.is_owner()
async def reload_cog(ctx, extension: str):
    """Reload a cog (owner only)"""
    try:
        await bot.reload_extension(f"cogs.{extension}")
        await ctx.send(f"[OK] Reloaded {extension}")
    except Exception as e:
        await ctx.send(f"[X] Error: {e}")

@bot.command(name="unload_cog")
@commands.is_owner()
async def unload_cog(ctx, extension: str):
    """Unload a cog (owner only)"""
    try:
        await bot.unload_extension(f"cogs.{extension}")
        await ctx.send(f"[OK] Unloaded {extension}")
    except Exception as e:
        await ctx.send(f"[X] Error: {e}")

@bot.event
async def on_command_error(ctx, error):
    import traceback
    
    # Always log full traceback to file so we can find the exact crash line
    full_tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    print(f"DEBUG: Command error: {error}")
    print(f"DEBUG: Full traceback:\n{full_tb}")
    
    try:
        if isinstance(error, commands.CommandNotFound):
            cmd_name = ctx.invoked_with
            if any(x in cmd_name.lower() for x in ["ara", "transferbilgi", "scout"]) and "http" in cmd_name.lower():
                await ctx.send("❌ **Hata:** Komut ile link arasına boşluk bırakmayı unuttun! Doğru kullanım: `!ara <link>`")
            else:
                await ctx.send(f"❌ **Hata:** `{cmd_name}` komutu bulunamadı.")
    except Exception as e:
        print(f"DEBUG: Error in global on_command_error: {e}")

if __name__ == "__main__":
    bot.run(config.BOT_TOKEN)
