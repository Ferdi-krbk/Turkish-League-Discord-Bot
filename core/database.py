"""
Database module for Turkish Super League Bot
Handles SQLite operations for teams, players, matches, transfers, injuries
"""

import aiosqlite
import json
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

import sys
import re
import contextlib
import unicodedata

def slugify(text: str) -> str:
    """ASCII-safe version of names for reliable searching"""
    if not text: return ""
    text = text.lower()
    chars = {'ç': 'c', 'ş': 's', 'ğ': 'g', 'ü': 'u', 'ö': 'o', 'ı': 'i', 'İ': 'i'}
    for k, v in chars.items():
        text = text.replace(k, v)
    text = re.sub(r'[^a-z0-9]', '', text)
    return text


def parse_market_value(mv_str: str) -> int:
    """Robust parser for market value strings like '75.0 M. €', '800 Bin €', '15,000,000'"""
    if not mv_str: return 0
    # Clean up common non-numeric chars but keep decimal point and comma
    mv_str = mv_str.upper().replace('€', '').replace('$', '').replace(' ', '').strip()
    
    # Handle multipliers
    multiplier = 1
    if 'M' in mv_str:
        multiplier = 1_000_000
        mv_str = mv_str.replace('M', '')
    elif 'K' in mv_str:
        multiplier = 1_000
        mv_str = mv_str.replace('K', '')
    elif 'BİN' in mv_str:
        multiplier = 1_000
        mv_str = mv_str.replace('BİN', '')
    elif 'B' in mv_str:
        # B usually means billion or bin (thousand) in Turkish. In this context, 
        # if it's a small number it might be billion, but usually 'B' is 'Bin'.
        # However, let's stick to 'B' = 'Bin' as per common project usage.
        multiplier = 1_000
        mv_str = mv_str.replace('B', '')
    
    # Remove thousands separators (comma or dot)
    # If there's both , and ., usually the last one is the decimal.
    if ',' in mv_str and '.' in mv_str:
        # 15,000.00 -> remove comma
        mv_str = mv_str.replace(',', '')
    elif ',' in mv_str:
        # 15,000,000 -> remove comma OR 15,5 -> replace with dot
        if re.search(r',\d{3}', mv_str):
            mv_str = mv_str.replace(',', '')
        else:
            mv_str = mv_str.replace(',', '.')
            
    # Remove any trailing non-numeric characters (like trailing dots)
    mv_str = mv_str.strip('.,')
    
    try:
        return int(float(mv_str) * multiplier)
    except:
        return 0


def get_base_path():
    """Get the correct base path whether running as a script or a frozen exe"""
    if getattr(sys, 'frozen', False):
        # Running as a bundled exe. Data is in _internal or same folder.
        # Check _internal first (PyInstaller 6+ default)
        internal_path = os.path.join(os.path.dirname(sys.executable), "_internal")
        if os.path.exists(internal_path):
            return internal_path
        
        # Check _MEIPASS (onefile mode)
        if hasattr(sys, '_MEIPASS'):
            return sys._MEIPASS
            
        return os.path.dirname(sys.executable)
    # Running as a script
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_PATH = get_base_path()
# DB should always be external in the same folder as the exe to allow persistence
DB_EXTERNAL_ROOT = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else BASE_PATH
DB_DIR = os.path.join(DB_EXTERNAL_ROOT, "database")

# Ensure the external database directory exists
try:
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR, exist_ok=True)
except Exception as e:
    print(f"CRITICAL: Could not create database directory {DB_DIR}: {e}")

DB_PATH = os.path.join(DB_DIR, "league.db")

# --- FIRST RUN DATA MIGRATION ---
# If the external database is missing or empty, copy the initial data from the internal bundle
if getattr(sys, 'frozen', False):
    # PyInstaller internal path
    internal_db_path = os.path.join(BASE_PATH, "database", "league.db")
    
    # If external DB doesn't exist OR is very small (empty schema), and internal one does, copy it
    is_empty = not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) < 50000 
    
    if is_empty and os.path.exists(internal_db_path):
        try:
            import shutil
            shutil.copy2(internal_db_path, DB_PATH)
            print(f"✅ Initial database copied to: {DB_PATH}")
        except Exception as e:
            print(f"❌ Error copying initial database: {e}")


@contextlib.asynccontextmanager
async def get_db():
    """Async context manager for database connections with smart encoding transliteration"""
    db = await aiosqlite.connect(DB_PATH)
    
    def smart_decode(b):
        if b is None: return None
        try:
            # 1. Try standard UTF-8
            text = b.decode('utf-8')
        except UnicodeDecodeError:
            # 2. Fallback to Western European (for names like Vitria)
            try:
                text = b.decode('cp1252')
            except UnicodeDecodeError:
                # 3. Final fallback: ignore errors
                text = b.decode('utf-8', errors='ignore')
        
        # 4. Standard return of decoded text (No transliteration)
        return text

    try:
        db.text_factory = smart_decode
        yield db
    finally:
        await db.close()


async def init_db():
    """Initialize database tables"""
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                overall INTEGER,
                played INTEGER DEFAULT 0,
                won INTEGER DEFAULT 0,
                drawn INTEGER DEFAULT 0,
                lost INTEGER DEFAULT 0,
                gf INTEGER DEFAULT 0,
                ga INTEGER DEFAULT 0,
                points INTEGER DEFAULT 0,
                budget INTEGER DEFAULT 50000000,
                form_streak TEXT DEFAULT '',
                league TEXT DEFAULT 'Super Lig',
                is_external INTEGER DEFAULT 0
            )
        """)
        
        # Migration: Ensure league column exists
        try:
            await db.execute("ALTER TABLE teams ADD COLUMN league TEXT DEFAULT 'Super Lig'")
        except:
            pass

        # Players table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                team TEXT,
                position TEXT,
                overall INTEGER,
                age INTEGER,
                pace INTEGER,
                shooting INTEGER,
                passing INTEGER,
                defending INTEGER,
                goals INTEGER DEFAULT 0,
                assists INTEGER DEFAULT 0,
                yellow_cards INTEGER DEFAULT 0,
                red_cards INTEGER DEFAULT 0,
                suspension_matches INTEGER DEFAULT 0,
                form_rating INTEGER DEFAULT 0,
                market_value INTEGER DEFAULT 0,
                slug TEXT,
                nationality TEXT DEFAULT 'Türkiye'
            )
        """)
        
        # Migration: Ensure card and suspension columns exist
        for col in ["yellow_cards", "red_cards", "suspension_matches"]:
            try:
                await db.execute(f"ALTER TABLE players ADD COLUMN {col} INTEGER DEFAULT 0")
            except:
                pass

        # Match history table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                home_team TEXT,
                away_team TEXT,
                home_score INTEGER,
                away_score INTEGER,
                importance TEXT DEFAULT 'Normal',
                weather TEXT DEFAULT 'Clear',
                competition TEXT DEFAULT 'League'
            )
        """)

        # Transfers table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transfers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                player_name TEXT,
                from_team TEXT,
                to_team TEXT,
                fee INTEGER,
                contract_years INTEGER
            )
        """)
        
        # --- NEW MIGRATIONS ---
        try:
            await db.execute("ALTER TABLE teams ADD COLUMN is_external INTEGER DEFAULT 0")
        except: pass
        
        try:
            await db.execute("ALTER TABLE players ADD COLUMN market_value INTEGER DEFAULT 0")
            await db.execute("ALTER TABLE players ADD COLUMN slug TEXT")
            await db.execute("ALTER TABLE players ADD COLUMN nationality TEXT DEFAULT 'Türkiye'")
        except: pass

        # Injuries table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS injuries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_name TEXT,
                team TEXT,
                injury_type TEXT,
                weeks_left INTEGER,
                return_date TEXT,
                duration_weeks INTEGER,
                date TEXT
            )
        """)

        # Referees table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                strictness INTEGER DEFAULT 5, -- 0-10 (Card frequency)
                var_freq INTEGER DEFAULT 5,    -- 0-10 (VAR review frequency)
                personality TEXT DEFAULT 'Standard'
            )
        """)
        await db.commit()
        
        # Seed referees if empty
        async with db.execute("SELECT COUNT(*) FROM referees") as cursor:
            row = await cursor.fetchone()
            if row[0] == 0:
                refs = [
                    ("Cüneyt Çakır", 7, 9, "Efsanevi, otoriter ve VAR'a güvenen bir tarz."),
                    ("Fırat Aydınus", 9, 6, "Karizmatik, kart göstermekten çekinmeyen, oyunun akışına bırakan."),
                    ("Mete Kalkavan", 5, 8, "Sakin, teknik detaylara önem veren, VAR odaklı."),
                    ("Halil Umut Meler", 7, 8, "Modern, kuralcı, fiziksel temaslara karşı hassas."),
                    ("Ali Palabıyık", 9, 5, "Sert, tavizsiz ve otoritesini hissettiren."),
                    ("Hüseyin Göçek", 4, 7, "Tecrübeli, oyunun hızını seven, avantaj kuralını sık uygulayan."),
                    ("Atilla Karaoğlan", 6, 8, "Genç, dinamik ve kuralları disiplinle uygulayan."),
                    ("Abdulkadir Bitigen", 5, 9, "VAR odasıyla uyumlu, teknik faullere odaklı."),
                    ("Arda Kardeşler", 6, 4, "Modern, kuralcı, fiziksel temaslara karşı hassas."),
                    ("Volkan Bayarslan", 6, 72, "Modern, kuralcı, fiziksel temaslara karşı hassas."),
                    ("Zorbay Küçük", 6, 3, "Modern, çok az faul çalar, fiziksel temaslı oyunu sever."),
                    ("Tugay Kaan Numanoğlu", 6, 1, "Modern, çok az faul çalar, fiziksel temaslı oyunu sever.")
                ]
                await db.executemany("INSERT INTO referees (name, strictness, var_freq, personality) VALUES (?,?,?,?)", refs)
                await db.commit()

        # GUI Commands table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gui_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT,
                channel TEXT DEFAULT 'exxen-1',
                status TEXT DEFAULT 'Pending',
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

        # Goal scorers table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS goal_scorers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER,
                player_name TEXT,
                team TEXT,
                minute INTEGER,
                goal_type TEXT DEFAULT 'regular',
                competition TEXT DEFAULT 'League',
                FOREIGN KEY (match_id) REFERENCES matches(id)
            )
        """)
        # Migration: Ensure assist_player_name column exists in goal_scorers
        try:
            await db.execute("ALTER TABLE goal_scorers ADD COLUMN assist_player_name TEXT")
        except:
            pass

        # Tournament management tables
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE, -- 'UCL', 'UEL', 'UECL'
                status TEXT DEFAULT 'Active'
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tournament_fixtures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER,
                round TEXT, -- 'Son 16', 'Çeyrek Final', 'Yarı Final', 'Final'
                home_team TEXT,
                away_team TEXT,
                leg INTEGER DEFAULT 1, -- 1 or 2
                home_score INTEGER DEFAULT 0,
                away_score INTEGER DEFAULT 0,
                agg_home_score INTEGER DEFAULT 0,
                agg_away_score INTEGER DEFAULT 0,
                status TEXT DEFAULT 'Pending' -- 'Pending', 'Played'
            )
        """)

        await db.commit()
        
        # Fixtures table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS fixtures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_no INTEGER,
                home_team TEXT,
                away_team TEXT,
                home_score INTEGER DEFAULT 0,
                away_score INTEGER DEFAULT 0,
                status TEXT DEFAULT 'Pending'
            )
        """)

        await db.commit()
        
        # Scout cache table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS scout_cache (
                query TEXT PRIMARY KEY,
                response_json TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()
        
        # Add new columns to existing schema safely
        try:
            await db.execute("ALTER TABLE teams ADD COLUMN budget INTEGER DEFAULT 50000000")
        except Exception:
            pass
            
        try:
            await db.execute("ALTER TABLE teams ADD COLUMN form_streak TEXT DEFAULT ''")
        except Exception:
            pass
            
        try:
            await db.execute("ALTER TABLE teams ADD COLUMN owner_id INTEGER DEFAULT NULL")
        except Exception:
            pass
            
        try:
            await db.execute("ALTER TABLE teams ADD COLUMN coach_id INTEGER DEFAULT NULL")
        except Exception:
            pass

        try:
            await db.execute("ALTER TABLE teams ADD COLUMN tier TEXT DEFAULT 'Others'")
        except Exception:
            pass

        # Migration: Add scores to fixtures table if they don't exist
        try:
            await db.execute("ALTER TABLE fixtures ADD COLUMN home_score INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE fixtures ADD COLUMN away_score INTEGER DEFAULT 0")
        except Exception:
            pass

        try:
            await db.execute("ALTER TABLE players ADD COLUMN form_rating INTEGER DEFAULT 0")
        except Exception:
            pass
            
        await db.commit()

async def clear_players_table():
    """Clears all existing player records to allow a fresh AI-evaluated start"""
    async with get_db() as db:
        await db.execute("DELETE FROM players")
        await db.commit()
        print("DEBUG: All player records cleared from database.")


async def load_teams_from_json():
    """Load teams from JSON file into database"""
    json_path = os.path.join(BASE_PATH, "data", "teams.json")
    if not os.path.exists(json_path):
        return

    async with get_db() as db:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for team in data["teams"]:
            # Sadece yoksa ekle (İstatistikleri sıfırlamamak için)
            await db.execute("""
                INSERT OR IGNORE INTO teams (name, overall)
                VALUES (?, ?)
            """, (team["name"], team["overall"]))
            
            # Eğer varsa sadece reytingi güncelle (Puanları ellemeyecek)
            await db.execute("""
                UPDATE teams SET overall = ? WHERE name = ?
            """, (team["overall"], team["name"]))

        await db.commit()


async def load_players_from_json():
    """Load players from JSON file into database"""
    json_path = os.path.join(BASE_PATH, "data", "players.json")
    if not os.path.exists(json_path):
        return

    async with get_db() as db:
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            print(f"Uyarı: {json_path} bozuk veya boş, atlanıyor.")
            return

        for player in data.get("players", []):
            p_name = player["name"]
            p_team = player["team"]
            
            # Önce bu isimde ve takımda oyuncu var mı bak (Artık takım kontrolü de var)
            async with db.execute("SELECT id FROM players WHERE LOWER(name) = LOWER(?) AND LOWER(team) = LOWER(?)", (p_name, p_team)) as cursor:
                row = await cursor.fetchone()
                
                if not row:
                    # Yoksa ekle
                    await db.execute("""
                        INSERT INTO players (name, team, position, overall, age, pace, shooting, passing, defending)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (p_name, p_team, player["position"], player["overall"], player["age"], 
                          player["pace"], player["shooting"], player["passing"], player["defending"]))
                else:
                    # Varsa sadece özellikleri güncelle
                    await db.execute("""
                        UPDATE players SET 
                            position = ?, overall = ?, age = ?, pace = ?, shooting = ?, passing = ?, defending = ?
                        WHERE id = ?
                    """, (player["position"], player["overall"], player.get("age", 25), 
                          player["pace"], player["shooting"], player["passing"], player["defending"],
                          row[0]))

        await db.commit()

async def get_team(name: str) -> Optional[Dict[str, Any]]:
    """Get team by name (case-insensitive)"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM teams WHERE LOWER(name) = LOWER(?)", (name,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def search_team(query: str) -> Optional[Dict[str, Any]]:
    """Search team by name or slug (immune to character issues)"""
    if not query: return None
    q = query.strip()
    slug = slugify(q)
    
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        # 1. First search by SLUG (Reliable & character-safe)
        async with db.execute("SELECT * FROM teams WHERE slug = ?", (slug,)) as cursor:
            row = await cursor.fetchone()
            if row: return dict(row)
            
        # 2. Fallback to exact lower name
        async with db.execute("SELECT * FROM teams WHERE LOWER(name) = LOWER(?)", (q,)) as cursor:
            row = await cursor.fetchone()
            if row: return dict(row)

        # 3. Fallback to start match on name
        async with db.execute("SELECT * FROM teams WHERE LOWER(name) LIKE ?", (f"{q.lower()}%",)) as cursor:
            row = await cursor.fetchone()
            if row: return dict(row)
            
        # 4. Fallback to start match on slug (e.g. 'fener' finds 'fenerbahce')
        async with db.execute("SELECT * FROM teams WHERE slug LIKE ?", (f"{slug}%",)) as cursor:
            row = await cursor.fetchone()
            if row: return dict(row)

        # 5. Fallback to fuzzy match (contains)
            async with db.execute("SELECT * FROM teams WHERE slug LIKE ? OR LOWER(name) LIKE ?", (f"%{slug}%", f"%{q.lower()}%")) as cursor:
                row = await cursor.fetchone()
                if row: return dict(row)
                
        return None


async def resolve_canonical_team(q_name: str) -> str:
    """Resolves a team name to its canonical version in the database.
    Checks 'teams' table first, then 'tournament_fixtures' for international teams."""
    if not q_name: return q_name
    
    # Clean redundant prefixes often found in GUI/Bot interactions
    clean_name = re.sub(r'^!(mac|maclar)\s+', '', q_name, flags=re.IGNORECASE).strip()
    q_slug = slugify(clean_name)
    
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        
        # 1. Check 'teams' table (League Teams)
        for table in ["teams", "tournament_fixtures"]:
            name_col = "name" if table == "teams" else "home_team"
            
            # Exact Slug/Name
            query = f"SELECT {name_col} as name FROM {table} WHERE LOWER({name_col}) = LOWER(?) "
            params = [clean_name]
            if table == "teams": 
                query += "OR slug = ?"
                params.append(q_slug)
            
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                if row: return row["name"]

            # Fuzzy (Contains)
            async with db.execute(f"SELECT {name_col} as name FROM {table} WHERE LOWER({name_col}) LIKE ?", (f"%{clean_name.lower()}%",)) as cursor:
                row = await cursor.fetchone()
                if row: return row["name"]
            
            # Slug Inclusion (e.g. 'Besiktas JK' contains 'besiktas' slug)
            if table == "teams":
                async with db.execute(f"SELECT name FROM teams WHERE ? LIKE '%' || slug || '%'", (q_slug,)) as cursor:
                    row = await cursor.fetchone()
                    if row: return row["name"]

        # 2. Word-based matching (Last resort)
        q_words = [w for w in re.split(r'[^a-z0-9]', clean_name.lower()) if len(w) > 3]
        for word in q_words:
            if word in ["spor", "city", "united", "real", "club", "town", "lig", "ligi"]: continue
            for table in ["teams", "tournament_fixtures"]:
                name_col = "name" if table == "teams" else "home_team"
                async with db.execute(f"SELECT {name_col} as name FROM {table} WHERE LOWER({name_col}) LIKE ?", (f"%{word}%",)) as cursor:
                    row = await cursor.fetchone()
                    if row: return row["name"]
                
    return clean_name


def estimate_player_ovr(value_eur: Optional[int]) -> int:
    """Calculates a realistic OVR based on the 2025/26 market value (MV) scale."""
    if value_eur is None or value_eur <= 0: return 65
    value_m = value_eur / 1_000_000.0
    
    # ELITE 2026 SCALE
    if value_m >= 200.0: res = 96 + min(3, int((value_m - 200) / 20)) # 200M -> 96, 220M -> 97
    elif value_m >= 150.0: res = 92 + int((value_m - 150) / 50 * 4)   # 150M -> 92, 200M -> 96
    elif value_m >= 100.0: res = 89 + int((value_m - 100) / 50 * 3)   # 100M -> 89, 150M -> 92
    elif value_m >= 75.0: res = 86 + int((value_m - 75) / 25 * 3)    # 75M -> 86, 100M -> 89
    elif value_m >= 50.0: res = 83 + int((value_m - 50) / 25 * 3)    # 50M -> 83, 75M -> 86
    elif value_m >= 30.0: res = 79 + int((value_m - 30) / 20 * 4)    # 30M -> 79, 50M -> 83
    elif value_m >= 15.0: res = 75 + int((value_m - 15) / 15 * 4)    # 15M -> 75, 30M -> 79
    elif value_m >= 5.0: res = 70 + int((value_m - 5) / 10 * 5)      # 5M -> 70, 15M -> 75
    elif value_m >= 1.0: res = 66 + int((value_m - 1) / 4 * 4)       # 1M -> 66, 5M -> 70
    else: res = 64
    
    return min(99, res)

async def update_team_overall(name: str, new_overall: float):
    """Update team overall rating in both DB and teams.json"""
    # 1. DB Update
    async with get_db() as db:
        await db.execute("UPDATE teams SET overall = ? WHERE name = ?", (new_overall, name))
        await db.commit()

    # 2. JSON Update (Kalıcı olması için)
    teams_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "teams.json")
    if os.path.exists(teams_path):
        try:
            with open(teams_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            updated = False
            for team in data["teams"]:
                if team["name"].lower() == name.lower():
                    team["overall"] = new_overall
                    updated = True
                    break
            
            if updated:
                with open(teams_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Error updating teams.json: {e}")
async def add_team(name: str, league: str = 'Super Lig', overall: float = 75.0, budget: int = 50000000, is_external: int = 0):
    """Add a new team to the database."""
    async with get_db() as db:
        try:
            slug = slugify(name)
            await db.execute("""
                INSERT INTO teams (name, league, overall, budget, slug, is_external)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, league, overall, budget, slug, is_external))
            await db.commit()
            return True
        except Exception as e:
            print(f"Error adding team {name}: {e}")
            return False

async def calculate_external_team_gpr_ai(team_name: str) -> float:
    """Uses Gemini knowledge to calculate GPR based on Top 18 Transfermarkt rule for European teams."""
    from core.ai import generate_content
    
    prompt = f"""
Lütfen '{team_name}' takımının BUGÜNKÜ (Mayıs 2026) Transfermarkt verilerine göre en değerli 18 oyuncusunu belirle.
DİKKAT: Tarih Mayıs 2026'dır. 2024-2025-2026 transferlerini (Örn: Ederson, De Bruyne, Gündoğan gibi isimlerin ayrılışını) hesaba kat.
1. Mayıs 2026 itibarıyla en yüksek piyasa değerine sahip 18 oyuncuyu seç.
2. Bu oyuncular için şu bareme göre OVR (Reyting) ata:
   -200M+ €: 94-100 OVR
    -100M+ €: 90-94 OVR
   - 60M-100M €: 86-89 OVR
   - 30M-60M €: 82-85 OVR
   - 15M-30M €: 78-81 OVR
   - 5M-15M €: 73-77 OVR
   - 1M-5M €: 68-72 OVR
   - <1M €: 60-67 OVR

3. Kesin Hibrit GPR Hesabı Yap:
   - (İlk 11 oyuncunun OVR ortalaması * 0.85) + (Kalan en iyi 7 yedeğin OVR ortalaması * 0.15)

SADECE şu JSON formatında cevap ver:
{{
  "team": "{team_name}",
  "gpr": 84.5,
  "top_18": [
    {{"name": "Oyuncu A", "value_m": 180, "ovr": 94}},
    {{"name": "Oyuncu B", "value_m": 100, "ovr": 90}}
  ]
}}
"""
    try:
        res = await generate_content(prompt, "Sen uzman bir futbol veri analistisin.", temp=0.1, label="EXT_GPR", provider="gemini", attempts=10)
        if res and "gpr" in res:
            print(f"DEBUG: AI GPR Result for {team_name}: {res}")
            return float(res["gpr"])
    except Exception as e:
        print(f"AI GPR Error for {team_name}: {e}")
        
    return 75.0 # Fallback

async def calculate_team_overall(team_name: str) -> float:
    """Calculates team overall based on Top 18 players. 
    AUTOMATICALLY refreshes player OVRs based on their current Market Value before calculation."""
    
    # 1. HER OYUNCUNUN REYTINGINI PIYASA DEGERINE GORE GUNCELLE (Senkronizasyon)
    players = await get_team_players(team_name)
    if not players:
        # Eğer oyuncu yoksa ve TXT'si de yoksa External'dır
        tactic_path = os.path.join("data", "tactics", f"{team_name}.txt")
        if not os.path.exists(tactic_path):
             new_gpr = await calculate_external_team_gpr_ai(team_name)
             await update_team_overall(team_name, new_gpr)
             return new_gpr
        return 0.0
        
    async with get_db() as db:
        for p in players:
            mv = p.get('market_value')
            if mv is not None and mv > 0:
                new_ovr = estimate_player_ovr(mv)
                if new_ovr != p.get('overall', 0):
                    await db.execute("UPDATE players SET overall = ? WHERE id = ?", (new_ovr, p['id']))
        await db.commit()

        # TXT Kontrolü (Dış takım mı yoksa yerel mi?)
        tactic_path = os.path.join("data", "tactics", f"{team_name}.txt")
        is_external = not os.path.exists(tactic_path)

    # 1.5. EXTERNAL AI HESAPLAMA (Eğer TXT yoksa Gemini devreye girer)
    if is_external:
        new_gpr = await calculate_external_team_gpr_ai(team_name)
        await update_team_overall(team_name, new_gpr)
        return new_gpr
    
    # 2. YEREL TAKIM (TXT VAR): Tüm kadronun basit ortalaması
    weighted_avg = sum(p.get('overall', 0) or 0 for p in players) / len(players) if players else 0.0
    weighted_avg = round(weighted_avg, 1)
    
    # 3. TEAM TABLOSUNU VE JSON'I GUNCELLE
    await update_team_overall(team_name, weighted_avg)
    
    return weighted_avg


async def get_all_teams(league: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get all teams sorted by points, optionally filtered by league (e.g., 'Super Lig')"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM teams"
        params = []
        if league:
            query += " WHERE league = ?"
            params.append(league)
        
        query += " ORDER BY points DESC, gf - ga DESC"
        
        async with db.execute(query, params) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def get_user_team(user_id: int) -> Optional[Dict[str, Any]]:
    """Get team managed by a Discord user (either as President or Coach)"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        # Check both owner_id (President) and coach_id (TD)
        async with db.execute("SELECT * FROM teams WHERE owner_id = ? OR coach_id = ?", (user_id, user_id)) as cursor:
            row = await cursor.fetchone()
            if row:
                res = dict(row)
                # Add role info to the result
                res["user_role"] = "başkan" if res["owner_id"] == user_id else "td"
                return res
            return None


async def set_team_role(team_name: str, user_id: int, role: str = "başkan") -> bool:
    """Set a Discord user as 'başkan' (President) or 'td' (Coach) of a team"""
    role = role.lower()
    if role not in ["ba\u015fkan", "td"]:
        role = "ba\u015fkan" # Default

    async with get_db() as db:
        # 1. Önce bu kullanıcıyı diğer takımlardaki TÜM rollerinden sil (Tek takım/Tek rol sınırı)
        await db.execute("UPDATE teams SET owner_id = NULL WHERE owner_id = ?", (user_id,))
        await db.execute("UPDATE teams SET coach_id = NULL WHERE coach_id = ?", (user_id,))
        
        # 2. Şimdi yeni takımı ve rolü ata
        column = "owner_id" if role == "ba\u015fkan" else "coach_id"
        
        # Eğer bu rolde başkası varsa onu çıkaralım mı? 
        # Evet, bir rolde sadece bir kişi olabilir.
        await db.execute(f"UPDATE teams SET {column} = ? WHERE LOWER(name) = LOWER(?)", (user_id, team_name))
        
        await db.commit()
        return True


async def set_team_owner(team_name: str, user_id: int) -> bool:
    """Legacy wrapper for set_team_role (defaults to President)"""
    return await set_team_role(team_name, user_id, "ba\u015fkan")


async def get_team_budget(team_name: str) -> int:
    """Get the current budget for a team"""
    async with get_db() as db:
        async with db.execute("SELECT budget FROM teams WHERE name = ?", (team_name,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def update_team_budget(team_name: str, amount_change: int):
    """Add or subtract from a team's budget"""
    async with get_db() as db:
        await db.execute("UPDATE teams SET budget = budget + ? WHERE name = ?", (amount_change, team_name))
        await db.commit()

async def set_team_budget(team_name: str, amount: int):
    """Directly set a team's budget to a specific amount"""
    async with get_db() as db:
        await db.execute("UPDATE teams SET budget = ? WHERE name = ?", (amount, team_name))
        await db.commit()

async def transfer_team_budget(from_team: str, to_team: str, amount: int) -> tuple[bool, str]:
    """Transfer budget from one team to another atomically"""
    async with get_db() as db:
        # Check sender budget
        async with db.execute("SELECT budget FROM teams WHERE name = ?", (from_team,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return False, f"Gönderen takım ({from_team}) bulunamadı."
            if row[0] < amount:
                return False, f"Yetersiz bakiye! {from_team} kasası: {row[0]:,}"
        
        # Check receiver exists
        async with db.execute("SELECT name FROM teams WHERE name = ?", (to_team,)) as cursor:
            if not await cursor.fetchone():
                return False, f"Alıcı takım ({to_team}) bulunamadı."

        try:
            await db.execute("BEGIN TRANSACTION")
            await db.execute("UPDATE teams SET budget = budget - ? WHERE name = ?", (amount, from_team))
            await db.execute("UPDATE teams SET budget = budget + ? WHERE name = ?", (amount, to_team))
            await db.commit()
            return True, "Başarılı"
        except Exception as e:
            await db.rollback()
            return False, f"Hata: {str(e)}"

async def get_team_form_streak(team_name: str) -> str:
    """Get the recent form string (e.g. 'WWLD') for a team"""
    async with get_db() as db:
        async with db.execute("SELECT form_streak FROM teams WHERE name = ?", (team_name,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] else ""


async def update_team_stats(team_name: str, won: bool, drawn: bool, lost: bool,
                            gf: int, ga: int):
    """Update team statistics after a match"""
    async with get_db() as db:
        points = 3 if won else (1 if drawn else 0)
        await db.execute("""
            UPDATE teams SET
                played = played + 1,
                won = won + ?,
                drawn = drawn + ?,
                lost = lost + ?,
                gf = gf + ?,
                ga = ga + ?,
                points = points + ?
            WHERE LOWER(name) = LOWER(?)
        """, (1 if won else 0, 1 if drawn else 0, 1 if lost else 0, gf, ga, points, team_name))
        await db.commit()


async def update_team_full_stats(team_name: str, played: int, won: int, drawn: int, lost: int,
                               gf: int, ga: int, points: int):
    """Set all statistics for a team at once (Manual Override/Init)"""
    async with get_db() as db:
        # Check if team exists, if not create it
        async with db.execute("SELECT name FROM teams WHERE name = ?", (team_name,)) as cursor:
            if not await cursor.fetchone():
                await db.execute("INSERT INTO teams (name, overall, league) VALUES (?, ?, 'Super Lig')", (team_name, 0))

        await db.execute("""
            UPDATE teams SET
                played = ?,
                won = ?,
                drawn = ?,
                lost = ?,
                gf = ?,
                ga = ?,
                points = ?
            WHERE name = ?
        """, (played, won, drawn, lost, gf, ga, points, team_name))
        await db.commit()


async def update_player_full_stats(player_name: str, team_name: str, goals: int, assists: int = 0):
    """Set goal/assist statistics for a player at once (Manual Override/Init)"""
    async with get_db() as db:
        # Önce oyuncu var mı diye bak (Kendi takımında yoksa başka takımda var mı bak - DUPLICATE ÖNLEYİCİ)
        async with db.execute("SELECT id FROM players WHERE LOWER(name) = LOWER(?) AND LOWER(team) = LOWER(?)", (player_name, team_name)) as cursor:
            row = await cursor.fetchone()
            if not row:
                # Kendi takımında yok, peki başka herhangi bir takımda var mı? (Transfer olmuş olabilir)
                async with db.execute("SELECT id FROM players WHERE LOWER(name) = LOWER(?) LIMIT 1", (player_name,)) as cursor2:
                    row2 = await cursor2.fetchone()
                    if row2:
                        # Var olan oyuncuyu bu takıma çek
                        await db.execute("UPDATE players SET team = ? WHERE id = ?", (team_name, row2[0]))
                    else:
                        # Hiç yoksa ekle
                        await db.execute("""
                            INSERT INTO players (name, team, position, overall, age, pace, shooting, passing, defending)
                            VALUES (?, ?, 'Unknown', 0, 25, 70, 70, 70, 70)
                        """, (player_name, team_name))

        # Şimdi sayıları güncelle
        await db.execute("""
            UPDATE players SET goals = ?, assists = ? WHERE name = ? AND team = ?
        """, (goals, assists, player_name, team_name))
        
        # goal_scorers tablosunu GÜNCELLE:
        # Bu oyuncunun TÜM eski gol kayıtlarını siliyoruz (Case-insensitive)
        # ki verdiğin rakam direkt gerçeği yansıtsın.
        await db.execute("""
            DELETE FROM goal_scorers WHERE LOWER(player_name) = LOWER(?) AND LOWER(team) = LOWER(?)
        """, (player_name, team_name))
        
        # Sonra yeni sayı kadar manuel kayıt ekliyoruz. (ID = -1 Manuel demektir)
        for _ in range(goals):
            await db.execute("""
                INSERT INTO goal_scorers (match_id, player_name, team, minute, goal_type)
                VALUES (-1, ?, ?, 0, 'manual')
            """, (player_name, team_name))
            
        await db.commit()


async def get_player(name: str, team: str = None) -> Optional[Dict[str, Any]]:
    """Get player by name or slug, optionally filtered by team"""
    slug = slugify(name)
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        if team:
            async with db.execute(
                "SELECT * FROM players WHERE (slug = ? OR LOWER(name) = ?) AND team = ?", 
                (slug, name.lower(), team)
            ) as cursor:
                row = await cursor.fetchone()
        else:
            async with db.execute(
                "SELECT * FROM players WHERE slug = ? OR LOWER(name) = ?", 
                (slug, name.lower())
            ) as cursor:
                row = await cursor.fetchone()
        return dict(row) if row else None


async def search_player(name: str, team_str: str = None) -> Optional[Dict[str, Any]]:
    """Search player by partial name match (case-insensitive) with priority"""
    if not name: return None
    q = name.lower().strip()
    
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        
        # 1. Exact Name match (Priority)
        if team_str:
            query = "SELECT * FROM players WHERE LOWER(name) = ? AND LOWER(team) = ?"
            params = (q, team_str.lower().strip())
        else:
            query = "SELECT * FROM players WHERE LOWER(name) = ?"
            params = (q,)
            
        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if row: return dict(row)
            
        # 2. LIKE query for fuzzy name matching (Start of name)
        if team_str:
            query = "SELECT * FROM players WHERE LOWER(name) LIKE ? AND LOWER(team) = ?"
            params = (f"{q}%", team_str.lower().strip())
        else:
            query = "SELECT * FROM players WHERE LOWER(name) LIKE ?"
            params = (f"{q}%",)
            
        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if row: return dict(row)
            
        # 3. LIKE query for names containing the query (Only for longer queries)
        if len(q) >= 4:
            if team_str:
                query = "SELECT * FROM players WHERE LOWER(name) LIKE ? AND LOWER(team) = ?"
                params = (f"%{q}%", team_str.lower().strip())
            else:
                query = "SELECT * FROM players WHERE LOWER(name) LIKE ?"
                params = (f"%{q}%",)
                
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                if row: return dict(row)
                
        return None


async def get_players_by_team(team: str) -> List[Dict[str, Any]]:
    """Get all players from a team"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM players WHERE LOWER(team) = LOWER(?) ORDER BY overall DESC", (team,)
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def add_player(name: str, team: str, position: str, overall: int, market_value: int, age: int = 25) -> bool:
    """Add a new player to a team's squad"""
    async with get_db() as db:
        try:
            # Generate slug for search/matching
            p_slug = slugify(name)
            
            # Use overall as base for physical stats if not provided
            stat = int(overall)
            
            await db.execute(
                """INSERT INTO players (name, team, position, overall, market_value, age, pace, shooting, passing, defending, slug, nationality) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, team, position, overall, market_value, age, stat, stat, stat, stat, p_slug, "Bilinmeyen")
            )
            await db.commit()
            return True
        except Exception as e:
            print(f"Error adding player: {e}")
            return False

async def delete_player(player_id: int) -> bool:
    """Delete a player from the database by ID"""
    async with get_db() as db:
        try:
            await db.execute("DELETE FROM players WHERE id = ?", (player_id,))
            await db.commit()
            return True
        except Exception as e:
            print(f"Error deleting player: {e}")
            return False

async def edit_player(player_id: int, name: str, position: str, overall: int, market_value: int, age: int) -> bool:
    """Edit an existing player's details in the database"""
    async with get_db() as db:
        try:
            # Refresh slug in case name changed
            p_slug = slugify(name)
            await db.execute(
                """UPDATE players 
                   SET name = ?, position = ?, overall = ?, market_value = ?, age = ?, slug = ?
                   WHERE id = ?""",
                (name, position, overall, market_value, age, p_slug, player_id)
            )
            await db.commit()
            return True
        except Exception as e:
            print(f"Error editing player: {e}")
            return False



async def record_match(home_team: str, away_team: str, home_score: int,
                       away_score: int, importance: str = "Normal",
                       weather: str = "Clear", goals: List[Dict] = None, 
                       leg: int = None, events: List[Dict] = None):
    """Record a match result. Detects if it is a League or Europe/Friendly match."""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row

        # --- 0. CANONICAL NAME RESOLUTION (BUG FIX: Resolve names BEFORE anything else) ---
        resolved_home = await resolve_canonical_team(home_team)
        resolved_away = await resolve_canonical_team(away_team)
        
        # 1. KATEGORİ TESPİTİ (Kesin Keyword Şartı + Türkçe Normalizasyon)
        imp_lower = (importance or "Normal").lower().replace("İ", "i").replace("I", "ı")
        
        # Keyword'leri belirle
        is_ucl = any(k in imp_lower for k in ["ucl", "champions", "şampiyonlar"])
        is_uel = any(k in imp_lower for k in ["uel", "europa", "avrupa ligi"])
        is_uecl = any(k in imp_lower for k in ["uecl", "conference", "konferans"])
        is_europe = is_ucl or is_uel or is_uecl or "avrupa" in imp_lower
        
        # Lig tespiti için anahtar kelimeler
        is_explicit_league = any(k in imp_lower for k in ["lig", " l ", "league"]) or (imp_lower.strip() == "l")
        is_domestic_common = any(k in imp_lower for k in ["normal", "derby", "derbi", "kritik", "final", "klasik"])

        # NORMALIZE COMPETITION NAME FOR TOURNAMENT
        def normalize_comp(imp: str) -> str:
            if not imp: return "Friendly"
            il = imp.lower()
            if any(k in il for k in ["ucl", "champions", "şampiyonlar", "sampiyonlar"]): return "UCL"
            if any(k in il for k in ["uel", "europa", "avrupa ligi", "avrupa"]): return "UEL"
            if any(k in il for k in ["uecl", "conference", "konferans"]): return "UECL"
            return "Friendly"

        norm_comp = normalize_comp(imp_lower)

        # REVISED PRIORITY LOGIC (Strict Keyword Based)
        # 1. Avrupa Kupaları
        if is_ucl:
            is_league = False
            competition = "UCL"
        elif is_uel:
            is_league = False
            competition = "UEL"
        elif is_uecl:
            is_league = False
            competition = "UECL"
        # 2. Lig (SADECE açıkça 'lig' veya 'league' geçiyorsa)
        elif is_explicit_league:
            is_league = True
            competition = "League"
        # 3. Diğer her şey (Avrupa kelimesi geçse bile lig değildir)
        elif is_europe:
            is_league = False
            competition = "Europe"
        # 4. Varsayılan: Friendly/Hazırlık
        else:
            is_league = False
            competition = "Friendly"

        # Insert match (Using RESOLVED NAMES for consistent history)
        cursor = await db.execute("""
            INSERT INTO matches (date, home_team, away_team, home_score, away_score, importance, weather, competition)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (datetime.now().strftime("%Y-%m-%d"), resolved_home, resolved_away,
              home_score, away_score, importance, weather, competition))
        match_id = cursor.lastrowid

        # Insert goal scorers if provided
        if goals:
            for goal in goals:
                p_name = goal.get("player", "")
                p_team = goal.get("team", "")
                
                # İSİM NORMALİZASYONU (AKILLI BİRLEŞTİRME)
                canonical_name = p_name
                # Önce tam eşleşme, sonra kısmi eşleşme (Icardi -> Mauro Icardi)
                # OYUNCUYU BUL (ID ve Name alalım)
                player_id = None
                async with db.execute("""
                    SELECT id, name FROM players 
                    WHERE (LOWER(name) = LOWER(?) OR name LIKE ? OR ? LIKE '%' || name || '%')
                    AND LOWER(team) = LOWER(?)
                    ORDER BY LENGTH(name) DESC LIMIT 1
                """, (p_name, f"%{p_name}%", p_name, p_team)) as cursor_p:
                    row_p = await cursor_p.fetchone()
                    if row_p:
                        player_id = row_p["id"]
                        canonical_name = row_p["name"]
                    else:
                        # Noktalı kısaltma kontrolü (C. Ndiaye -> Cherif Ndiaye)
                        search_q = p_name.split(".")[-1].strip() if "." in p_name else p_name
                        async with db.execute("SELECT id, name FROM players WHERE LOWER(name) LIKE ? AND LOWER(team) = LOWER(?)", (f"%{search_q}%", p_team)) as cursor_p2:
                            row_p2 = await cursor_p2.fetchone()
                            if row_p2: 
                                player_id = row_p2["id"]
                                canonical_name = row_p2["name"]
                
                # KAYDET
                await db.execute("""
                    INSERT INTO goal_scorers (match_id, player_name, team, minute, goal_type, competition, assist_player_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (match_id, canonical_name, p_team, goal.get("minute", 0), goal.get("type", "regular"), competition, None))
                
                # --- ASİST KAYDI ---
                assist_name = goal.get("assist")
                canonical_assist = None
                if assist_name and assist_name.lower() != "none" and assist_name.lower() != p_name.lower():
                    canonical_assist = assist_name
                    # Asist yapanı normalize et
                    assist_id = None
                    async with db.execute("""
                        SELECT id, name FROM players 
                        WHERE (LOWER(name) = LOWER(?) OR name LIKE ? OR ? LIKE '%' || name || '%')
                        AND LOWER(team) = LOWER(?)
                        ORDER BY LENGTH(name) DESC LIMIT 1
                    """, (assist_name, f"%{assist_name}%", assist_name, p_team)) as cursor_a:
                        row_a = await cursor_a.fetchone()
                        if row_a:
                            assist_id = row_a["id"]
                            canonical_assist = row_a["name"]
                    
                    # Tabelada asisti güncelle
                    await db.execute("UPDATE goal_scorers SET assist_player_name = ? WHERE id = (SELECT last_insert_rowid())", (canonical_assist,))

                # SADECE LIG MACI VE GERÇEK BİR OYUNCUYSA (Takım ismi değilse) GÜNCELLE
                is_team_goal = (p_name.lower() == p_team.lower())
                if is_league and not is_team_goal and player_id:
                    await db.execute("""
                        UPDATE players SET goals = goals + 1 WHERE id = ?
                    """, (player_id,))
                    
                    # Asist istatistiğini oyuncuya işle
                    if assist_id:
                         await db.execute("""
                            UPDATE players SET assists = assists + 1 WHERE id = ?
                         """, (assist_id,))

        # --- KART VE CEZA TAKİBİ (Sadece Lig Maçları İçin) ---
        if is_league:
            # Önce mevcut cezaları 1 maç düşür (Maçı oynamış/geçirmiş sayılırlar)
            await db.execute("""
                UPDATE players SET suspension_matches = MAX(0, suspension_matches - 1)
                WHERE (LOWER(team) = LOWER(?) OR LOWER(team) = LOWER(?)) AND suspension_matches > 0
            """, (home_team, away_team))

            if events:
                for event in events:
                    etype = event.get("type")
                    if etype in ["yellow_card", "red_card"]:
                        p_name = event.get("player")
                        p_team = event.get("team")
                        if not p_name or not p_team:
                            continue
                        
                        # Oyuncuyu bul
                        async with db.execute("""
                            SELECT name, yellow_cards FROM players 
                            WHERE (LOWER(name) = LOWER(?) OR name LIKE ? OR ? LIKE '%' || name || '%')
                            AND LOWER(team) = LOWER(?)
                            ORDER BY LENGTH(name) DESC LIMIT 1
                        """, (p_name, f"%{p_name}%", p_name, p_team)) as cursor_p:
                            player = await cursor_p.fetchone()
                            if player:
                                canonical_p = player[0]
                                old_yellows = player[1]
                                
                                if etype == "yellow_card":
                                    new_yellows = old_yellows + 1
                                    await db.execute("""
                                        UPDATE players SET yellow_cards = ? WHERE name = ? AND LOWER(team) = LOWER(?)
                                    """, (new_yellows, canonical_p, p_team))
                                    
                                    # 4. Sarı Kart Cezası
                                    if new_yellows % 4 == 0:
                                        await db.execute("""
                                            UPDATE players SET suspension_matches = 1 WHERE name = ? AND LOWER(team) = LOWER(?)
                                        """, (canonical_p, p_team))
                                        print(f"DEBUG: [CEZA] {canonical_p} 4. sarı karttan cezalı duruma düştü.")
                                
                                elif etype == "red_card":
                                    await db.execute("""
                                        UPDATE players SET red_cards = red_cards + 1, suspension_matches = 2 
                                        WHERE name = ? AND LOWER(team) = LOWER(?)
                                    """, (canonical_p, p_team))
                                    print(f"DEBUG: [CEZA] {canonical_p} kırmızı karttan 2 MAÇ cezalı duruma düştü.")

        # 3. BÜTÇE GÜNCELLEME (Tüm maçlar için)
        home_won = home_score > away_score
        away_won = away_score > home_score
        drawn = home_score == away_score

        # Fiyat Ayarları (Detaylı Avrupa Primi)
        if competition == "League":
            win_reward, draw_reward = 300000, 150000
        elif competition == "UCL":
            win_reward, draw_reward = 7000000, 3000000
        elif competition == "UEL":
            win_reward, draw_reward = 3000000, 1000000
        elif competition == "UECL":
            win_reward, draw_reward = 2000000, 500000
        elif competition == "Europe": 
            win_reward, draw_reward = 2000000, 500000
        else: # Friendly/Hazırlık
            win_reward, draw_reward = 0, 0

        home_income = win_reward if home_won else (draw_reward if drawn else 0)
        away_income = win_reward if away_won else (draw_reward if drawn else 0)
        
        for t_name, income in [(resolved_home, home_income), (resolved_away, away_income)]:
            if income > 0:
                await db.execute("UPDATE teams SET budget = budget + ? WHERE name = ?", (income, t_name))

        # 4. Puan Durumu ve Form (Sadece Lig maçıysa)
        if is_league:

            home_form_streak = await get_team_form_streak(resolved_home)
            away_form_streak = await get_team_form_streak(resolved_away)
            
            home_char = "W" if home_won else ("D" if drawn else "L")
            away_char = "W" if away_won else ("D" if drawn else "L")
            
            home_form_streak = (home_form_streak + home_char)[-5:] if home_form_streak else home_char
            away_form_streak = (away_form_streak + away_char)[-5:] if away_form_streak else away_char

            for t_name, is_h, won_match, lost_match, g_f, g_a in [
                (resolved_home, True, home_won, away_won, home_score, away_score),
                (resolved_away, False, away_won, home_won, away_score, home_score)
            ]:
                match_points = 3 if won_match else (1 if drawn else 0)
                update_cursor = await db.execute("""
                    UPDATE teams SET
                        played = played + 1,
                        won = won + ?,
                        drawn = drawn + ?,
                        lost = lost + ?,
                        gf = gf + ?,
                        ga = ga + ?,
                        points = points + ?,
                        form_streak = ?
                    WHERE LOWER(name) = LOWER(?)
                """, (1 if won_match else 0, 1 if drawn else 0, 1 if lost_match else 0,
                      g_f, g_a, match_points, 
                      home_form_streak if is_h else away_form_streak,
                      t_name))
                
                if update_cursor.rowcount == 0:
                    print(f"[WARNING] Standing update failed for team: '{t_name}' (No match in teams table)")
                else:
                    print(f"[SUCCESS] Standing updated for team: '{t_name}' (+{match_points} pts)")

        # 3. Oyuncu Form Güncelleme (SADECE LİG MAÇLARINDA - Avrupa'da manuel kontrol için kapatıldı)
        if goals and is_league:
            # Maçın Adamı (MOTM) bul (En çok gol atan, yoksa ilk golü atan)
            # Not: Tam MOTM verisi cogs/match.py'den gelebilir ama record_match 
            # şu an sadece golleri alıyor. Golcülere ve galip takıma göre form verelim.
            for goal in goals:
                p_name = goal.get("player", "")
                p_team = goal.get("team", "")
                # Gol atan/Asist yapan +1 Form
                await db.execute("""
                    UPDATE players SET form_rating = MIN(3, form_rating + 1) 
                    WHERE LOWER(name) = LOWER(?) AND LOWER(team) = LOWER(?)
                """, (p_name, p_team))
                
                if goal.get("assist"):
                    await db.execute("""
                        UPDATE players SET form_rating = MIN(3, form_rating + 1) 
                        WHERE LOWER(name) = LOWER(?) AND LOWER(team) = LOWER(?)
                    """, (goal["assist"].lower(), p_team.lower()))

            # Yenilen takımın formunu düşür (-1)
            loser = None
            if home_won: loser = away_team
            elif away_won: loser = home_team
            
            if loser:
                await db.execute("""
                    UPDATE players SET form_rating = MAX(-3, form_rating - 1) 
                    WHERE LOWER(team) = LOWER(?)
                """, (loser.lower(),))
            
            # Galip takımın (gol atmayanlar dahil) formunu artır (+1)
            winner = None
            if home_won: winner = home_team
            elif away_won: winner = away_team
            
            if winner:
                await db.execute("""
                    UPDATE players SET form_rating = MIN(3, form_rating + 1) 
                    WHERE LOWER(team) = LOWER(?)
                """, (winner.lower(),))

        await db.commit()
        
        # Fikstür durumunu güncelle (SADECE LİG MAÇI ise)
        if is_league:
            await update_fixture_status(home_team, away_team, "Played", home_score, away_score)
        
        # Turnuva eşleşmesini otomatik güncelle (UCL, UEL, UECL ise)
        if competition in ["UCL", "UEL", "UECL"] or norm_comp in ["UCL", "UEL", "UECL"]:
            sync_name = norm_comp if norm_comp != "Friendly" else competition
            await sync_tournament_fixture(resolved_home, resolved_away, home_score, away_score, sync_name, leg=leg)
        
        return match_id, competition

async def sync_tournament_fixture(home_team: str, away_team: str, h_score: int, a_score: int, t_name: str, leg: int = None):
    """Find a pending tournament fixture and update it automatically. Uses 'leg' if provided for precision."""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        # Turnuvayı bul
        t_id = await get_tournament_by_name(t_name)
        if not t_id: return

        # Ayak (Leg) filtresi ekle
        leg_filter = "AND leg = ?" if leg else ""
        query = f"""
            UPDATE tournament_fixtures 
            SET home_score = ?, away_score = ?, status = 'Played'
            WHERE id IN (
                SELECT id FROM tournament_fixtures 
                WHERE tournament_id = ? 
                AND (LOWER(home_team) = LOWER(?) OR home_team = ?) 
                AND (LOWER(away_team) = LOWER(?) OR away_team = ?)
                AND status = 'Pending'
                {leg_filter}
                ORDER BY leg ASC LIMIT 1
            )
        """
        params = [h_score, a_score, t_id, home_team.lower(), home_team, away_team.lower(), away_team]
        if leg: params.append(leg)

        cursor = await db.execute(query, params)
        if cursor.rowcount == 0:
            # TRY SLUG MATCHING IF DIRECT MATCH FAILED
            h_slug = slugify(home_team)
            a_slug = slugify(away_team)
            
            # Fetch pending fixtures to match in Python (reliable for SQLite)
            async with db.execute("SELECT id, home_team, away_team FROM tournament_fixtures WHERE tournament_id = ? AND status = 'Pending' " + leg_filter, [t_id] + ([leg] if leg else [])) as cursor_f:
                rows = await cursor_f.fetchall()
                for row in rows:
                    fh_slug = slugify(row["home_team"])
                    fa_slug = slugify(row["away_team"])
                    
                    # Robust matching: Exact slug OR one contains the other
                    h_match = (fh_slug == h_slug or h_slug in fh_slug or fh_slug in h_slug)
                    a_match = (fa_slug == a_slug or a_slug in fa_slug or fa_slug in a_slug)
                    
                    if h_match and a_match:
                        await db.execute("UPDATE tournament_fixtures SET home_score = ?, away_score = ?, status = 'Played' WHERE id = ?", (h_score, a_score, row["id"]))
                        print(f"DEBUG: [SYNC] Tournament fixture resolved via slug: {row['home_team']} vs {row['away_team']}")
                        break
        
        await db.commit()


async def record_transfer(player_name: str, from_team: str, to_team: str,
                          fee: int, contract_years: int, player_details: Optional[Dict] = None) -> bool:
    """Record a transfer and ensure player is in the players table. Returns True if successful."""
    async with get_db() as db:
        # 0. DOĞRULAMA: Oyuncu gerçekten bu takımdan mı gidiyor?
        # (Bu kontrol mükerrer satışları engeller)
        async with db.execute("SELECT team FROM players WHERE LOWER(name) = LOWER(?)", (player_name,)) as cursor:
            row_p = await cursor.fetchone()
            # Eğer oyuncu DB'de varsa ve şu anki takımı from_team değilse transferi engelle
            # (Sadece satılan oyuncu için kontrol ediyoruz, 'to_team' Samsunspor ise yani alış ise from_team genellikle 'Diğer Takım' olur, 
            #  bu yüzden eğer DB'de hiç yoksa veya team NULL ise izin veriyoruz)
            if row_p and row_p[0]:
                curr_team = row_p[0]
                if curr_team.lower() != from_team.lower():
                    print(f"DEBUG: Transfer blocked. {player_name} is in {curr_team}, not {from_team}.")
                    return False

        await db.execute("""
            INSERT INTO transfers (date, player_name, from_team, to_team, fee, contract_years)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().strftime("%Y-%m-%d"), player_name, from_team, to_team, fee, contract_years))

        # Transfer bütçelerini düş ve ekle
        await db.execute("UPDATE teams SET budget = budget - ? WHERE name = ?", (fee, to_team))
        await db.execute("UPDATE teams SET budget = budget + ? WHERE name = ?", (fee, from_team))

        # 1. Önce oyuncunun bu takımdaki kaydına bak
        async with db.execute("SELECT id FROM players WHERE LOWER(name) = LOWER(?) AND LOWER(team) = LOWER(?)", (player_name, from_team)) as cursor:
            row = await cursor.fetchone()
            if row:
                # Varsa sadece takımını güncelle
                await db.execute("UPDATE players SET team = ? WHERE id = ?", (to_team, row[0]))
            else:
                # 2. Takımda yoksa, veritabanında HERHANGİ bir yerde var mı bak (Transfer / Hata düzeltme)
                async with db.execute("SELECT id FROM players WHERE LOWER(name) = LOWER(?) LIMIT 1", (player_name,)) as cursor2:
                    row2 = await cursor2.fetchone()
                    if row2:
                        # Varsa sadece takımını güncelle
                        await db.execute("UPDATE players SET team = ? WHERE id = ?", (to_team, row2[0]))
                    elif player_details:
                        # 3. Hiç yoksa ve bilgi gelmişse YENİ EKLE
                        ovr = player_details.get('overall', 0)
                        pos = (player_details.get('position') or player_details.get('pos', 'ST')).upper()
                        age = player_details.get('age', 25)
                        st = ovr # Stats based on OVR for initial insert
                        await db.execute("""
                            INSERT INTO players (name, team, position, overall, age, pace, shooting, passing, defending, form_rating)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                        """, (player_name, to_team, pos, ovr, age, st, st, st, st))

        await db.commit()
        return True



async def record_injury(player_name: str, team: str, injury_type: str,
                        duration_weeks: int):
    """Record an injury"""
    async with get_db() as db:
        return_date = (datetime.now() + timedelta(weeks=duration_weeks)).strftime("%Y-%m-%d")
        await db.execute("""
            INSERT INTO injuries (date, player_name, team, injury_type, duration_weeks, return_date)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (datetime.now().strftime("%Y-%m-%d"), player_name, team,
              injury_type, duration_weeks, return_date))
        await db.commit()
        return return_date



async def get_recent_matches(limit: int = 5) -> List[Dict[str, Any]]:
    """Get recent matches"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM matches ORDER BY date DESC, id DESC LIMIT ?
        """, (limit,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def get_recent_transfers(limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent transfers"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM transfers ORDER BY date DESC, id DESC LIMIT ?
        """, (limit,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def cancel_transfer(transfer_id: int):
    """Undo a transfer: revert player team and refund budget"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM transfers WHERE id = ?", (transfer_id,)) as cursor:
            t = await cursor.fetchone()
            if not t:
                return False
        
        player_name = t['player_name']
        from_team = t['from_team']
        to_team = t['to_team']
        fee = t['fee']
        
        await db.execute("UPDATE players SET team = ? WHERE name = ?", (from_team, player_name))
        await db.execute("UPDATE teams SET budget = budget - ? WHERE name = ?", (fee, from_team))
        await db.execute("UPDATE teams SET budget = budget + ? WHERE name = ?", (fee, to_team))
        await db.execute("DELETE FROM transfers WHERE id = ?", (transfer_id,))
        await db.commit()
        return True

async def add_gui_command(command: str, channel: str = 'exxen-1'):
    """Add a command to the GUI command queue for the bot to execute"""
    async with get_db() as db:
        await db.execute("INSERT INTO gui_commands (command, channel) VALUES (?, ?)", (command, channel))
        await db.commit()
        return True


async def get_active_injuries() -> List[Dict[str, Any]]:
    """Get currently active injuries (return date hasn't passed yet)"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        today = datetime.now().strftime("%Y-%m-%d")
        async with db.execute("""
            SELECT * FROM injuries WHERE return_date >= ? ORDER BY return_date ASC
        """, (today,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def get_league_suspensions() -> List[Dict[str, Any]]:
    """Get only players who are currently suspended"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT name, team, yellow_cards, red_cards, suspension_matches 
            FROM players 
            WHERE suspension_matches > 0
            ORDER BY suspension_matches DESC
        """) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


async def get_team_tactics(team_name: str) -> Optional[Dict[str, str]]:
    """Get team tactics from tactics.txt file"""
    tactics_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tactics.txt")
    if not os.path.exists(tactics_path):
        return None

    with open(tactics_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                name = parts[0]
                if name.lower() == team_name.lower():
                    return {
                        "formation": parts[1],
                        "tactic": parts[2],
                        "style": parts[3] if len(parts) > 3 else "Balanced"
                    }
    return None


async def get_all_tactics() -> Dict[str, Dict[str, str]]:
    """Get all team tactics from tactics.txt file"""
    tactics_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tactics.txt")
    tactics = {}

    if not os.path.exists(tactics_path):
        return tactics

    with open(tactics_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                name = parts[0]
                tactics[name] = {
                    "formation": parts[1],
                    "tactic": parts[2],
                    "style": parts[3] if len(parts) > 3 else "Balanced"
                }

    return tactics


async def save_fixtures(fixtures_list: List[Dict[str, Any]]):
    """Save a list of fixtures to the database"""
    async with get_db() as db:
        for fixture in fixtures_list:
            await db.execute("""
                INSERT INTO fixtures (round_no, home_team, away_team, status)
                VALUES (?, ?, ?, ?)
            """, (fixture["round_no"], fixture["home_team"], fixture["away_team"], fixture.get("status", "Pending")))
        await db.commit()


async def get_fixtures(round_no: int = None) -> List[Dict[str, Any]]:
    """Get fixtures, optionally filtered by round number"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        if round_no:
            async with db.execute(
                "SELECT * FROM fixtures WHERE round_no = ? ORDER BY id ASC", (round_no,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
        else:
            async with db.execute(
                "SELECT * FROM fixtures ORDER BY round_no ASC, id ASC"
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]



async def get_round_results(round_no: int) -> List[Dict[str, Any]]:
    """Oynanan bir haftanın tüm maç sonuçlarını ve golcülerini getirir."""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        
        # 1. O haftanın oynanmış fikstürlerini bul
        async with db.execute("""
            SELECT * FROM fixtures WHERE round_no = ? AND status = 'Played'
        """, (round_no,)) as cursor:
            fixtures = [dict(row) for row in await cursor.fetchall()]
            
        results = []
        for f in fixtures:
            # 2. Her fikstür için en güncel lig maçını bul (Aynı takımların maçı)
            async with db.execute("""
                SELECT * FROM matches 
                WHERE (LOWER(home_team) = LOWER(?) AND LOWER(away_team) = LOWER(?))
                OR (LOWER(home_team) = LOWER(?) AND LOWER(away_team) = LOWER(?))
                AND competition = 'League'
                ORDER BY id DESC LIMIT 1
            """, (f["home_team"], f["away_team"], f["away_team"], f["home_team"])) as cursor_m:
                match = await cursor_m.fetchone()
                if match:
                    match_dict = dict(match)
                    # 3. Maçın gollerini getir
                    async with db.execute("""
                        SELECT * FROM goal_scorers WHERE match_id = ?
                    """, (match_dict["id"],)) as cursor_g:
                        match_dict["goals"] = [dict(row) for row in await cursor_g.fetchall()]
                    results.append(match_dict)
        
        return results


async def get_latest_played_round() -> int:
    """En son hangi haftanın maçlarının oynandığını bulur."""
    async with get_db() as db:
        async with db.execute("SELECT MAX(round_no) FROM fixtures WHERE status = 'Played'") as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] is not None else 0


async def update_fixture_status(home_team: str, away_team: str, status: str = "Played", h_score: int = 0, a_score: int = 0):
    """Update fixture status and recorded scores after a match is played"""
    async with get_db() as db:
        # Karakter duyarsız eşleşme için slugify kullanıyoruz
        h_slug = slugify(home_team)
        a_slug = slugify(away_team)
        
        # Tüm bekleyen fikstürleri çekip Python tarafında slug ile eşleştirelim (En garanti yol)
        # Çünkü SQLite'da unaccent/slugify fonksiyonu gömülü değil.
        async with db.execute("SELECT id, home_team, away_team FROM fixtures WHERE status = 'Pending'") as cursor:
            rows = await cursor.fetchall()
            target_id = None
            for r in rows:
                fh_slug = slugify(r[1])
                fa_slug = slugify(r[2])
                
                if (fh_slug == h_slug and fa_slug == a_slug) or (fh_slug == a_slug and fa_slug == h_slug):
                    target_id = r[0]
                    break
        
        if target_id:
            await db.execute("""
                UPDATE fixtures SET status = ?, home_score = ?, away_score = ?
                WHERE id = ?
            """, (status, h_score, a_score, target_id))
        else:
            print(f"[DEBUG] update_fixture_status fixture not found for: {home_team} - {away_team}")
        
        await db.commit()


async def get_top_scorers(limit: int = 10, competition: str = 'League') -> List[Dict[str, Any]]:
    """
    Gol krallığı listesini getirir. 
    ÖNEMLİ: 'Sadece Süper Lig' isteği üzerine golleri artık 'goal_scorers' tablosundan 
    yarışma tipine (competition) göre sayarak getirir.
    """
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        # Count goals from goal_scorers table filtered by competition
        query = """
            SELECT player_name, team, COUNT(*) as goals
            FROM goal_scorers
            WHERE competition = ?
            GROUP BY player_name, team
            ORDER BY goals DESC
            LIMIT ?
        """
        async with db.execute(query, (competition, limit)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def get_suspended_players(team_name: str) -> List[Dict[str, Any]]:
    """Get currently suspended players and those on the threshold (3 yellow cards)"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT name, yellow_cards, red_cards, suspension_matches 
            FROM players 
            WHERE LOWER(team) = LOWER(?) 
            AND (suspension_matches > 0 OR yellow_cards % 4 == 3)
            ORDER BY suspension_matches DESC, yellow_cards DESC
        """, (team_name,)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def reset_all_cards():
    """Reset all cards and suspensions (useful for season end)"""
    async with get_db() as db:
        await db.execute("UPDATE players SET yellow_cards = 0, red_cards = 0, suspension_matches = 0")
        await db.commit()

async def get_top_assists(limit: int = 10, competition: str = 'League') -> List[Dict[str, Any]]:
    """Get top assist makers across the league or specific tournament"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        # Count assists from goal_scorers table filtered by competition
        query = """
            SELECT assist_player_name as player_name, team, COUNT(*) as assists
            FROM goal_scorers
            WHERE competition = ? AND assist_player_name IS NOT NULL
            GROUP BY assist_player_name, team
            ORDER BY assists DESC
            LIMIT ?
        """
        async with db.execute(query, (competition, limit)) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

async def get_scout_cache(query: str) -> Optional[Dict[str, Any]]:
    """Get cached AI response for a player/URL if it exists and is not too old (48h)"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT response_json FROM scout_cache WHERE query = ? AND timestamp > DATETIME('now', '-2 days')", 
            (query,)
        ) as cursor:
            row = await cursor.fetchone()
            return json.loads(row["response_json"]) if row else None

async def save_scout_cache(query: str, response_json: Dict[str, Any]):
    """Save AI response to scout_cache"""
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO scout_cache (query, response_json, timestamp) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (query, json.dumps(response_json, ensure_ascii=False))
        )
        await db.commit()

async def reset_morale_boost(team_name: str):
    """Resets the morale boost of a team to 0 (after it has been applied to a match)"""
    async with get_db() as db:
        await db.execute("UPDATE teams SET morale_boost = 0 WHERE LOWER(name) = LOWER(?)", (team_name,))
        await db.commit()

async def update_morale_boost(team_name: str, boost: int):
    """Updates the morale boost of a team by the given amount"""
    async with get_db() as db:
        await db.execute("UPDATE teams SET morale_boost = morale_boost + ? WHERE LOWER(name) = LOWER(?)", (boost, team_name))
        await db.commit()

async def get_next_fixture(team_name: str) -> Optional[Dict[str, Any]]:
    """Get the next pending fixture for a specific team"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM fixtures 
            WHERE (LOWER(home_team) = LOWER(?) OR LOWER(away_team) = LOWER(?)) 
            AND status = 'Pending' 
            ORDER BY round_no ASC LIMIT 1
        """, (team_name, team_name)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_team_players(team_name: str) -> List[Dict[str, Any]]:
    """Get all players for a specific team"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM players WHERE LOWER(team) = LOWER(?)", (team_name,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_match_scorers(match_id: int) -> List[Dict[str, Any]]:
    """Get all goal scorers for a specific match"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM goal_scorers WHERE match_id = ?", (match_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

# --- TOURNAMENT HELPERS ---

async def create_tournament(name: str):
    """Create or get a tournament from the database"""
    async with get_db() as db:
        await db.execute("INSERT OR IGNORE INTO tournaments (name) VALUES (?)", (name,))
        await db.commit()
        async with db.execute("SELECT id FROM tournaments WHERE name = ?", (name,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def get_tournament_by_name(name: str) -> Optional[int]:
    """Get tournament ID by name"""
    async with get_db() as db:
        async with db.execute("SELECT id FROM tournaments WHERE name = ?", (name,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def create_tournament_fixtures(tournament_id: int, round_name: str, teams: List[str], legs: int = 2):
    """Generatefixtures from a list of teams. legs=2 for home-away, legs=1 for single match."""
    import random
    temp_teams = teams.copy()
    random.shuffle(temp_teams)
    
    async with get_db() as db:
        while len(temp_teams) >= 2:
            t1 = temp_teams.pop()
            t2 = temp_teams.pop()
            
            # Leg 1: t1 vs t2
            await db.execute("""
                INSERT INTO tournament_fixtures (tournament_id, round, home_team, away_team, leg)
                VALUES (?, ?, ?, ?, 1)
            """, (tournament_id, round_name, t1, t2))
            
            if legs == 2:
                # Leg 2: t2 vs t1
                await db.execute("""
                    INSERT INTO tournament_fixtures (tournament_id, round, home_team, away_team, leg)
                    VALUES (?, ?, ?, ?, 2)
                """, (tournament_id, round_name, t2, t1))
            
        await db.commit()

async def create_group_stage_fixtures(tournament_id: int, group_round: str, teams: List[str]):
    """
    Create a single round-robin fixture list for a group, split into 3 matchdays.
    For 4 teams => 6 matches => 2 matches per matchday (MD1..MD3). Single-leg.
    """
    import random
    if not teams or len(teams) < 4:
        return
    uniq = []
    seen = set()
    for t in teams:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            uniq.append(t)
    teams = uniq
    if len(teams) != 4:
        # For now, World Cup groups are fixed at 4 teams.
        return

    # Circle method schedule for 4 teams (3 matchdays)
    t1, t2, t3, t4 = teams
    matchdays = [
        [(t1, t4), (t2, t3)],  # MD1
        [(t1, t3), (t4, t2)],  # MD2
        [(t1, t2), (t3, t4)],  # MD3
    ]

    async with get_db() as db:
        for md_idx, matches in enumerate(matchdays, start=1):
            round_name = f"{group_round} - MD{md_idx}"
            for a, b in matches:
                # Randomize home/away for flavor
                if random.random() < 0.5:
                    home, away = a, b
                else:
                    home, away = b, a
                await db.execute(
                    """
                    INSERT INTO tournament_fixtures (tournament_id, round, home_team, away_team, leg)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (tournament_id, round_name, home, away),
                )
        await db.commit()

async def get_group_standings(tournament_id: int, group_round: str) -> List[Dict[str, Any]]:
    """
    Compute standings for one group round (e.g. World Cup 4-team groups).
    Aggregates MD1..MD3 for fixtures starting with group_round prefix.
    """
    all_fx = await get_tournament_fixtures(tournament_id)
    fixtures = [f for f in all_fx if str(f.get("round", "")).startswith(group_round)]
    table: Dict[str, Dict[str, Any]] = {}

    def ensure(team: str):
        if team not in table:
            table[team] = {"team": team, "mp": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "gd": 0, "pts": 0}

    for f in fixtures:
        h, a = f["home_team"], f["away_team"]
        ensure(h)
        ensure(a)
        if f.get("status") != "Played":
            continue
        hs, aw = int(f.get("home_score", 0)), int(f.get("away_score", 0))

        table[h]["mp"] += 1
        table[a]["mp"] += 1
        table[h]["gf"] += hs
        table[h]["ga"] += aw
        table[a]["gf"] += aw
        table[a]["ga"] += hs

        if hs > aw:
            table[h]["w"] += 1
            table[a]["l"] += 1
            table[h]["pts"] += 3
        elif aw > hs:
            table[a]["w"] += 1
            table[h]["l"] += 1
            table[a]["pts"] += 3
        else:
            table[h]["d"] += 1
            table[a]["d"] += 1
            table[h]["pts"] += 1
            table[a]["pts"] += 1

    for t in table.values():
        t["gd"] = t["gf"] - t["ga"]
    return sorted(table.values(), key=lambda x: (-x["pts"], -x["gd"], -x["gf"], x["team"].lower()))

async def get_tournament_league_standings(tournament_id: int, round_prefix: str = "Lig Aşaması") -> List[Dict[str, Any]]:
    """
    Computes standings for the new UEFA 36-team League Stage (Swiss Model).
    Aggregates all matches where round starts with round_prefix.
    """
    all_fx = await get_tournament_fixtures(tournament_id)
    # Filter for League Stage rounds (e.g., "Lig Aşaması - MD1")
    fixtures = [f for f in all_fx if str(f.get("round", "")).startswith(round_prefix)]
    
    table: Dict[str, Dict[str, Any]] = {}

    def ensure(team: str):
        if team not in table:
            table[team] = {"team": team, "mp": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "gd": 0, "pts": 0}

    for f in fixtures:
        h, a = f["home_team"], f["away_team"]
        ensure(h)
        ensure(a)
        
        # Robust status check (handle bytes or string)
        status = f.get("status", "")
        if isinstance(status, bytes):
            status = status.decode('utf-8', errors='replace')
            
        if status != "Played":
            continue
            
        hs, aw = int(f.get("home_score", 0)), int(f.get("away_score", 0))

        table[h]["mp"] += 1
        table[a]["mp"] += 1
        table[h]["gf"] += hs
        table[h]["ga"] += aw
        table[a]["gf"] += aw
        table[a]["ga"] += hs

        if hs > aw:
            table[h]["w"] += 1
            table[a]["l"] += 1
            table[h]["pts"] += 3
        elif aw > hs:
            table[a]["w"] += 1
            table[h]["l"] += 1
            table[a]["pts"] += 3
        else:
            table[h]["d"] += 1
            table[a]["d"] += 1
            table[h]["pts"] += 1
            table[a]["pts"] += 1

    for t in table.values():
        t["gd"] = t["gf"] - t["ga"]

    # UEFA Tie-breakers (simplified): Pts > GD > GF > Wins
    return sorted(table.values(), key=lambda x: (-x["pts"], -x["gd"], -x["gf"], -x["w"], x["team"].lower()))

async def get_tournament_fixtures(tournament_id: int, round_name: str = None) -> List[Dict[str, Any]]:
    """Get fixtures for a tournament round"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM tournament_fixtures WHERE tournament_id = ?"
        params = [tournament_id]
        if round_name:
            query += " AND round = ?"
            params.append(round_name)
        
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_tournament_fixture_by_id(fixture_id: int) -> Optional[Dict[str, Any]]:
    """Get a specific tournament fixture by ID"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tournament_fixtures WHERE id = ?", (fixture_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_team_coach_map(team_names: List[str]) -> Dict[str, Optional[int]]:
    """Return mapping team_name -> coach_id (None if not set / not found)."""
    if not team_names:
        return {}
    # de-dup while preserving original casing preference
    uniq = []
    seen = set()
    for t in team_names:
        tl = (t or "").lower()
        if tl and tl not in seen:
            seen.add(tl)
            uniq.append(t)

    placeholders = ",".join(["?"] * len(uniq))
    q = f"SELECT name, coach_id FROM teams WHERE LOWER(name) IN ({placeholders})"

    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(q, [t.lower() for t in uniq]) as cursor:
            rows = await cursor.fetchall()
            out = {t: None for t in uniq}
            for r in rows:
                out[r["name"]] = r["coach_id"]
            return out

async def get_tournament_fixture(tournament_id: int, team_a: str, team_b: str) -> Optional[Dict[str, Any]]:
    """Get a pending tournament fixture between two teams"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM tournament_fixtures 
            WHERE tournament_id = ? AND status = 'Pending'
            AND (
                (LOWER(home_team) = LOWER(?) AND LOWER(away_team) = LOWER(?))
                OR (LOWER(home_team) = LOWER(?) AND LOWER(away_team) = LOWER(?))
            )
            ORDER BY id ASC LIMIT 1
        """, (tournament_id, team_a, team_b, team_b, team_a)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def update_tournament_fixture_score(fixture_id: int, h_score: int, a_score: int):
    """Update a fixture score and status"""
    async with get_db() as db:
        await db.execute("""
            UPDATE tournament_fixtures 
            SET home_score = ?, away_score = ?, status = 'Played'
            WHERE id = ?
        """, (h_score, a_score, fixture_id))
        await db.commit()

async def get_aggregate_score(tournament_id: int, round_name: str, team_a: str, team_b: str) -> Dict[str, int]:
    """Calculate aggregate score for a tie between two teams in a specific round"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        # Find both legs
        async with db.execute("""
            SELECT * FROM tournament_fixtures 
            WHERE tournament_id = ? AND round = ?
            AND (
                (home_team = ? AND away_team = ?)
                OR (home_team = ? AND away_team = ?)
            )
        """, (tournament_id, round_name, team_a, team_b, team_b, team_a)) as cursor:
            rows = await cursor.fetchall()
            
            agg = {team_a: 0, team_b: 0, "legs_played": 0}
            for r in rows:
                if r["status"] == 'Played':
                    agg[r["home_team"]] += r["home_score"]
                    agg[r["away_team"]] += r["away_score"]
                    agg["legs_played"] += 1
            return agg

async def ensure_team_exists(team_name: str, league: str = 'Europe'):
    """Creates a team entry if it doesn't exist already."""
    slug = slugify(team_name)
    async with get_db() as db:
        async with db.execute("SELECT id FROM teams WHERE slug = ?", (slug,)) as cursor:
            if not await cursor.fetchone():
                await db.execute("""
                    INSERT INTO teams (name, budget, overall, played, won, drawn, lost, gf, ga, points, slug, league)
                    VALUES (?, 100000000, 0, 0, 0, 0, 0, 0, 0, 0, ?, ?)
                """, (team_name, slug, league))
                await db.commit()

async def save_research_players(team_name: str, players: List[Dict[str, Any]]):
    """Batch inserts researched players and updates team overall using TOP 18 rule."""
    async with get_db() as db:
        # 1. Save Players
        for p in players:
            p_name = p['name']
            p_slug = slugify(p_name)
            await db.execute("DELETE FROM players WHERE (slug = ? OR name = ?) AND team = ?", (p_slug, p_name, team_name))
            
            ovr = p.get('ovr') or p.get('overall', 0)
            pos = p.get('pos') or p.get('position', 'Unknown')
            age = p.get('age', 25)
            mv = p.get('market_value_eur') or p.get('market_value', 0)
            
            st = ovr
            await db.execute("""
                INSERT INTO players (name, team, position, overall, age, market_value, slug, pace, shooting, passing, defending, form_rating)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (p_name, team_name, pos, ovr, age, mv, p_slug, st, st, st, st))
        
        await db.commit()

        # 2. Update Team Overall (TOP 18 RULE)
        async with db.execute("SELECT overall FROM players WHERE team = ?", (team_name,)) as cursor:
            rows = await cursor.fetchall()
            all_ovrs = sorted([r[0] for r in rows], reverse=True)
            top_18 = all_ovrs[:18]
            if len(top_18) < 18:
                top_18.extend([70] * (18 - len(top_18)))
            
            avg_ovr = sum(top_18) / 18 if top_18 else 0
            await db.execute("UPDATE teams SET overall = ? WHERE name = ?", (int(avg_ovr), team_name))
            await db.commit()

async def get_random_referee() -> Optional[Dict[str, Any]]:
    """Return a random referee from the database"""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM referees ORDER BY RANDOM() LIMIT 1") as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def reset_league_standings():
    """Resets all league standings and deletes match history, fixtures, and stats."""
    async with get_db() as db:
        # Reset team stats
        await db.execute("""
            UPDATE teams 
            SET played = 0, won = 0, drawn = 0, lost = 0, 
                gf = 0, ga = 0, points = 0, form_streak = ''
        """)
        # Clear match history and fixtures
        await db.execute("DELETE FROM matches")
        await db.execute("DELETE FROM fixtures")
        await db.execute("DELETE FROM goal_scorers")
        
        # Clear player stats
        await db.execute("DELETE FROM player_stats")
        
        # Clear injuries & suspensions
        await db.execute("UPDATE players SET suspension_matches = 0, goals = 0, assists = 0, yellow_cards = 0, red_cards = 0")
        await db.execute("DELETE FROM injuries")
        
        await db.commit()
    return True

async def reset_europe_tournaments():
    """COMPREHENSIVE RESET for European tournaments"""
    async with get_db() as db:
        # 1. Clear Tournament Structure
        await db.execute("DELETE FROM tournament_fixtures")
        await db.execute("DELETE FROM tournament_standings")
        await db.execute("DELETE FROM tournaments")
        
        # 2. Clear Match History for Europe
        await db.execute("DELETE FROM match_scorers WHERE match_id IN (SELECT id FROM matches WHERE competition != 'League')")
        await db.execute("DELETE FROM matches WHERE competition != 'League'")
        
        # 3. Clear External Teams (Teams added just for Europe)
        # First find team IDs to delete players
        async with db.execute("SELECT id FROM teams WHERE is_external = 1") as cursor:
            ext_ids = [row[0] for row in await cursor.fetchall()]
            for tid in ext_ids:
                await db.execute("DELETE FROM players WHERE team_id = ?", (tid,))
        
        await db.execute("DELETE FROM teams WHERE is_external = 1")
        
        await db.commit()
    return True

async def get_all_teams_simple():
    """Returns a simple list of all team names for selection menus (Filtered for Super Lig)."""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        # Sadece Süper Lig takımlarını getir ki küme düşürme listesi şişmesin
        async with db.execute("SELECT name FROM teams WHERE league = 'Super Lig' ORDER BY name ASC") as cursor:
            rows = await cursor.fetchall()
            return [row["name"] for row in rows]

async def handle_promotion_relegation(relegated_names: List[str], promoted_names: List[str]):
    """Handles season transition by removing relegated teams and adding promoted ones."""
    async with get_db() as db:
        # Delete relegated teams
        for name in relegated_names:
            await db.execute("DELETE FROM teams WHERE name = ?", (name,))
        
        # Add promoted teams with default stats
        for name in promoted_names:
            await db.execute("""
                INSERT OR IGNORE INTO teams (name, overall, budget, league)
                VALUES (?, 75, 5000000, 'Super Lig')
            """, (name,))
        
        await db.commit()
    return True

async def setup_europe_from_gui(tournament_name: str, round_name: str, team_names: List[str], legs: int = 2):
    """Bridge function to setup a tournament from the GUI."""
    t_id = await create_tournament(tournament_name)
    # Clear existing fixtures for this round to avoid duplicates
    async with get_db() as db:
        await db.execute("DELETE FROM tournament_fixtures WHERE tournament_id = ? AND round = ?", (t_id, round_name))
        await db.commit()
    
    if round_name == "Lig Aşaması":
        return await setup_league_stage_from_gui(tournament_name, team_names)
    
    await create_tournament_fixtures(t_id, round_name, team_names, legs)
    return True

async def setup_league_stage_from_gui(t_name: str, manual_teams: List[str]):
    """Sets up a 36-team Swiss system league stage for Europe from GUI."""
    import random
    t_id = await create_tournament(t_name)
    
    # Realistic Giants for filling
    UCL_GIANTS = ["Real Madrid", "Manchester City", "Bayern München", "PSG", "Arsenal", "Inter", "Atletico", "Leverkusen", "Barcelona", "Dortmund", "Juventus", "Liverpool", "Milan", "Aston Villa", "Sporting", "Benfica", "Atalanta", "Feyenoord", "PSV", "Salzburg", "Celtic", "Monaco", "Stuttgart", "Girona", "Bologna", "Lille", "Brest", "Leipzig", "Club Brugge", "Shakhtar", "Crvena Zvezda", "Sparta Praha", "Dinamo Zagreb", "Sturm Graz", "Young Boys", "Slovan Bratislava"]
    UEL_GIANTS = ["AS Roma", "Man Utd", "Tottenham", "Ajax", "Lazio", "FC Porto", "Real Sociedad", "Lyon", "Frankfurt", "Marseille", "Villarreal", "Rangers", "Athletic Bilbao", "Nice", "Betis", "Olympiacos", "PAOK", "Braga", "Slavia Praha", "AZ", "Ludogorets", "Malmö", "FCSB", "Qarabağ", "Galatasaray", "Fenerbahçe", "Beşiktaş", "Union St Gilloise", "Dynamo Kyiv", "Ferencváros", "Bodø/Glimt", "Viktoria Plzeň", "Hoffenheim", "Anderlecht", "Midtjylland", "Maccabi Tel Aviv"]
    UECL_GIANTS = ["Chelsea", "Fiorentina", "Heidenheim", "Vitória SC", "Gent", "Legia", "Cercle Brugge", "Lugano", "Panathinaikos", "Copenhagen", "St Gallen", "Rapid Wien", "Djurgården", "Başakşehir", "Omonia", "APOEL", "Vikingur", "Larne", "Dinamo Minsk", "Noah", "Pafos", "Petrocub", "Jagiellonia", "Hearts", "Shamrock", "TNS", "Borac", "Celje", "Astana", "Mladá Boleslav", "Olimpija", "TSC", "Ballkani", "Pyunik", "Spartak Trnava", "Shkupi"]
    
    giants = UCL_GIANTS if t_name == "UCL" else (UEL_GIANTS if t_name == "UEL" else UECL_GIANTS)
    
    # 1. Fill to 36 teams
    current_teams = list(manual_teams)
    manual_low = [t.lower() for t in current_teams]
    for g in giants:
        if len(current_teams) >= 36: break
        if g.lower() not in manual_low:
            current_teams.append(g)
            manual_low.append(g.lower())
    
    while len(current_teams) < 36:
        current_teams.append(f"Avrupa Takımı {len(current_teams)+1}")

    # 2. Assign to Pots based on OVR
    team_data = []
    for t in current_teams:
        db_team = await search_team(t)
        ovr = db_team["overall"] if db_team else (85 if t in giants else 75)
        team_data.append({"name": db_team["name"] if db_team else t, "overall": ovr})
    
    team_data.sort(key=lambda x: x["overall"], reverse=True)
    pots = [team_data[i*9:(i+1)*9] for i in range(4)]
    
    # 3. Create Fixtures (Simplified Swiss Style: Each team plays 2 from each pot)
    # To keep it simple and reliable for GUI, we use a rotation-based matching
    async with get_db() as db:
        await db.execute("DELETE FROM tournament_fixtures WHERE tournament_id = ?", (t_id,))
        for p_idx in range(4): # For each pot
            pot = pots[p_idx]
            for i in range(9): # For each team in pot
                team = pot[i]["name"]
                # Match with 2 teams from each pot (including own pot)
                for opp_p_idx in range(4):
                    opp_pot = pots[opp_p_idx]
                    # Select 2 opponents (i+1 and i+2 mod 9)
                    opp1 = opp_pot[(i + 1) % 9]["name"]
                    opp2 = opp_pot[(i + 2) % 9]["name"]
                    
                    if opp1 != team:
                        await db.execute("INSERT INTO tournament_fixtures (tournament_id, round, home_team, away_team, leg) VALUES (?, ?, ?, ?, ?)",
                                        (t_id, "Lig Aşaması", team, opp1, 1))
                    if opp2 != team:
                        await db.execute("INSERT INTO tournament_fixtures (tournament_id, round, home_team, away_team, leg) VALUES (?, ?, ?, ?, ?)",
                                        (t_id, "Lig Aşaması", opp2, team, 1))
        await db.commit()
    return True

async def generate_league_fixtures():
    """Generates a perfect double round-robin fixture for Super Lig teams."""
    async with get_db() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT name FROM teams WHERE league = 'Super Lig' ORDER BY name ASC") as cursor:
            rows = await cursor.fetchall()
            team_names = [row["name"] for row in rows]
    
    if len(team_names) < 2:
        return False

    # Circle Method Algorithm
    def create_schedule(teams):
        if len(teams) % 2 != 0:
            teams.append("BAY")
        n = len(teams)
        schedule = []
        temp_teams = list(teams)
        
        # First half
        for r in range(n - 1):
            round_matches = []
            for i in range(n // 2):
                h, a = temp_teams[i], temp_teams[n - 1 - i]
                if h != "BAY" and a != "BAY":
                    if i == 0 and r % 2 == 1:
                        round_matches.append((a, h))
                    else:
                        round_matches.append((h, a))
            schedule.append(round_matches)
            temp_teams = [temp_teams[0]] + [temp_teams[-1]] + temp_teams[1:-1]
            
        # Second half (Reversed)
        second_half = []
        for r_matches in schedule:
            second_half.append([(a, h) for h, a in r_matches])
            
        return schedule + second_half

    full_schedule = create_schedule(team_names)
    
    # Save to database
    async with get_db() as db:
        # Clear existing fixtures first
        await db.execute("DELETE FROM fixtures")
        for r_idx, r_matches in enumerate(full_schedule, 1):
            for h, a in r_matches:
                await db.execute(
                    "INSERT INTO fixtures (round_no, home_team, away_team, status) VALUES (?, ?, ?, ?)",
                    (r_idx, h, a, "Pending")
                )
        await db.commit()
    return True

async def save_fixtures(fixtures: List[Dict]):
    """Helper to save a list of fixture dicts to the database."""
    async with get_db() as db:
        for f in fixtures:
            await db.execute(
                "INSERT INTO fixtures (round_no, home_team, away_team, status) VALUES (?, ?, ?, ?)",
                (f["round_no"], f["home_team"], f["away_team"], f.get("status", "Pending"))
            )
        await db.commit()
    return True
