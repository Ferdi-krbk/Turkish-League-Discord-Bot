import sys
import discord
from discord.ext import commands
from discord.app_commands import CommandTree
import config
from core import database

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
    bot.remove_command("help") # Varsayılan help'i kaldır
    await database.init_db()
    await database.load_teams_from_json()
    await database.load_players_from_json()
    await bot.load_extension("cogs.match")
    await bot.load_extension("cogs.transfer")
    await bot.load_extension("cogs.info")
    await bot.load_extension("cogs.interview")
    await bot.load_extension("cogs.tournament")
    await bot.load_extension("cogs.injury")
    await bot.load_extension("cogs.admin")

bot.setup_hook = setup_hook

@bot.event
async def on_ready():
    """Bot startup handler"""
    try:
        await bot.tree.sync()
        print(f"[OK] Logged in as {bot.user}")
        print(f"[OK] Loaded {len(bot.cogs)} cogs")
        print(f"[OK] Invite URL: https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot")
    except Exception as e:
        print(f"[X] Startup error: {e}")

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
    try:
        if isinstance(error, commands.CommandNotFound):
            # Suggesting space if it looks like a URL-command mashup
            cmd_name = ctx.invoked_with
            if any(x in cmd_name.lower() for x in ["ara", "transferbilgi", "scout"]) and "http" in cmd_name.lower():
                await ctx.send("❌ **Hata:** Komut ile link arasına boşluk bırakmayı unuttun! Doğru kullanım: `!ara <link>`")
            else:
                await ctx.send(f"❌ **Hata:** `{cmd_name}` komutu bulunamadı.")
    except Exception as e:
        print(f"DEBUG: Error in global on_command_error: {e}")
    
    print(f"DEBUG: Command error: {error}")

if __name__ == "__main__":
    bot.run(config.BOT_TOKEN)
