import sqlite3
import os
import re

db_path = "database/league.db"
tactics_dir = "data/tactics"

# Stats from User's Table (O, G, B, M, AV, P)
TEAM_STATS = {
    "Galatasaray": (2, 2, 0, 0, 6, 6),
    "Kocaelispor": (2, 2, 0, 0, 6, 6),
    "Trabzonspor": (2, 2, 0, 0, 4, 6),
    "Konyaspor": (2, 2, 0, 0, 4, 6),
    "Göztepe": (2, 2, 0, 0, 4, 6),
    "Samsunspor": (2, 2, 0, 0, 3, 6),
    "Kasımpaşa": (2, 1, 1, 0, 1, 4),
    "Beşiktaş": (2, 1, 0, 1, 2, 3),
    "Başakşehir": (2, 1, 0, 1, 1, 3),
    "Gaziantep FK": (2, 1, 0, 1, -3, 3),
    "Amedspor": (2, 1, 0, 1, -4, 3),
    "Erokspor": (2, 0, 1, 1, -2, 1),
    "Antalyaspor": (2, 0, 0, 2, -3, 0),
    "Kayserispor": (2, 0, 0, 2, -3, 0),
    "Alanyaspor": (2, 0, 0, 2, -3, 0),
    "Fatih Karagümrük": (2, 0, 0, 2, -3, 0),
    "Fenerbahçe": (2, 0, 0, 2, -4, 0),
    "Erzurumspor": (2, 0, 0, 2, -6, 0)
}

def parse_market_value(mv_str):
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
        multiplier = 1_000
        mv_str = mv_str.replace('B', '')
    
    if ',' in mv_str and '.' in mv_str:
        mv_str = mv_str.replace(',', '')
    elif ',' in mv_str:
        if re.search(r',\d{3}', mv_str):
            mv_str = mv_str.replace(',', '')
        else:
            mv_str = mv_str.replace(',', '.')
            
    mv_str = mv_str.strip('.,')
    
    try:
        return int(float(mv_str) * multiplier)
    except:
        return 0

def reseed():
    print("--- League Reseed & Synchronization ---")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. World Cup & National Team Purge
    print("Purging World Cup & European Teams...")
    cursor.execute("DELETE FROM tournaments WHERE name = 'WORLD_CUP'")
    cursor.execute("DELETE FROM tournament_fixtures")
    cursor.execute("DELETE FROM players WHERE team IN (SELECT name FROM teams WHERE league IN ('Europe', 'UCL', 'UEL', 'UECL'))")
    cursor.execute("DELETE FROM teams WHERE league IN ('Europe', 'UCL', 'UEL', 'UECL')")
    
    # 2. Add Missing European Teams from Fixtures
    print("Syncing European Teams from Fixtures...")
    cursor.execute("SELECT DISTINCT home_team, tournament_id FROM tournament_fixtures WHERE tournament_id IN (1, 5, 7)")
    euro_rows = cursor.fetchall()
    for name, tid in euro_rows:
        league_tag = 'UCL' if tid == 1 else 'UEL' if tid == 5 else 'UECL'
        # Only add if not a Super Lig team
        if name not in TEAM_STATS:
            cursor.execute("INSERT OR IGNORE INTO teams (name, league) VALUES (?, ?)", (name, league_tag))

    # 3. Reseed Teams and Players from Tactic Files
    print("Processing Tactic Files...")
    for filename in os.listdir(tactics_dir):
        if not filename.endswith('.txt'): continue
        
        team_name = filename.replace('.txt', '')
        # Handle encoding for Windows/Turkish characters
        # Some files might be Başakşehir.txt etc.
        # We find the matching key in TEAM_STATS or assume generic
        
        file_path = os.path.join(tactics_dir, filename)
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Update Team Entity
        league_tag = 'Super Lig' if team_name in TEAM_STATS or any(k in team_name for k in TEAM_STATS) else 'Europe'
        stats = TEAM_STATS.get(team_name, (0,0,0,0,0,0))
        
        cursor.execute("""
            INSERT OR REPLACE INTO teams (name, played, won, drawn, lost, gf, ga, points, league)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (team_name, stats[0], stats[1], stats[2], stats[3], stats[4] if stats[4]>0 else 0, abs(stats[4]) if stats[4]<0 else 0, stats[5], league_tag))

        # Clear existing players for this team to re-sync
        cursor.execute("DELETE FROM players WHERE team = ?", (team_name,))

        # Parse Players (Simple line-based parser)
        # Format: Name | Pos | Age | Value
        lines = content.split('\n')
        for line in lines:
            if '|' in line:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 2:
                    p_name = parts[0]
                    p_pos = parts[1]
                    p_age = 25
                    p_val = 0
                    if len(parts) >= 3:
                        try: p_age = int(re.search(r'\d+', parts[2]).group())
                        except: pass
                    if len(parts) >= 4:
                        p_val = parse_market_value(parts[3])
                    
                    cursor.execute("""
                        INSERT INTO players (name, team, position, overall, age, goals, assists, market_value)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (p_name, team_name, p_pos, 75, p_age, 0, 0, p_val))

    print("Success: Database re-seeded and synchronized.")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    reseed()
