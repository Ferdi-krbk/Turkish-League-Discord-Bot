import sqlite3
import os
import re
import random

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

def slugify(text):
    if not text: return ""
    text = text.lower()
    chars = {'ç': 'c', 'ş': 's', 'ğ': 'g', 'ü': 'u', 'ö': 'o', 'ı': 'i', 'İ': 'i'}
    for k, v in chars.items():
        text = text.replace(k, v)
    text = re.sub(r'[^a-z0-9]', '', text)
    return text

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

def calculate_ovr(mv):
    """Calibrated OVR based on 30M+ = 82+ standard"""
    val_m = mv / 1_000_000.0
    if val_m >= 120.0: res = 90
    elif val_m >= 80.0: res = 87
    elif val_m >= 50.0: res = 84
    elif val_m >= 30.0: res = 82
    elif val_m >= 15.0: res = 78
    elif val_m >= 5.0: res = 73
    elif val_m >= 1.0: res = 68
    else: res = 65
    return res + random.randint(0, 1)

def reseed():
    print("--- Global Reseed: Top 18 OVR Enforcement ---")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Clear players and European teams first
    print("Purging all players and European teams...")
    cursor.execute("DELETE FROM players")
    cursor.execute("DELETE FROM teams WHERE league IN ('Europe', 'UCL', 'UEL', 'UECL')")
    cursor.execute("DELETE FROM tournament_fixtures")
    cursor.execute("DELETE FROM tournaments")

    # 1. Process teams from tactics dir
    for filename in os.listdir(tactics_dir):
        if not filename.endswith('.txt'): continue
        
        team_name = filename.replace('.txt', '')
        file_path = os.path.join(tactics_dir, filename)
        try:
            with open(file_path, 'r', encoding='utf-8') as f: content = f.read()
        except:
            with open(file_path, 'r', encoding='latin-1') as f: content = f.read()

        league_tag = 'Super Lig' if team_name in TEAM_STATS else 'Europe'
        stats = TEAM_STATS.get(team_name, (0,0,0,0,0,0))
        
        # Check if team exists
        cursor.execute("SELECT played, won, drawn, lost, gf, ga, points FROM teams WHERE name = ?", (team_name,))
        existing_team = cursor.fetchone()

        if existing_team:
            # Preserve standings
            cursor.execute("""
                UPDATE teams SET league = ?, slug = ? WHERE name = ?
            """, (league_tag, slugify(team_name), team_name))
        else:
            # Insert new team with defaults/hardcoded stats
            cursor.execute("""
                INSERT INTO teams (name, played, won, drawn, lost, gf, ga, points, league, slug)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (team_name, stats[0], stats[1], stats[2], stats[3], stats[4] if stats[4]>0 else 0, abs(stats[4]) if stats[4]<0 else 0, stats[5], league_tag, slugify(team_name)))

        # Insert Players
        team_ovrs = []
        lines = content.split('\n')
        for line in lines:
            if '|' in line:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 2:
                    p_name = parts[0]
                    p_pos = parts[1]
                    p_val = parse_market_value(parts[3]) if len(parts) >= 4 else 0
                    p_ovr = calculate_ovr(p_val)
                    p_slug = slugify(p_name)
                    team_ovrs.append(p_ovr)
                    
                    cursor.execute("""
                        INSERT INTO players (name, team, position, overall, age, market_value, slug)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (p_name, team_name, p_pos, p_ovr, 25, p_val, p_slug))

        # Update Team Overall (TOP 18 RULE)
        # Determine League for Ratio
        cursor.execute("SELECT league FROM teams WHERE name = ?", (team_name,))
        row = cursor.fetchone()
        league = row[0] if row else 'Europe'
        is_turkish = league in ['Super Lig', '1. Lig']

        # Weighted Average: Top 11 + Bench 7
        top_11 = top_18[:11]
        bench_7 = top_18[11:18]
        
        avg_11 = sum(top_11) / 11 if top_11 else 75
        avg_bench = sum(bench_7) / 7 if bench_7 else avg_11
        
        if is_turkish:
            # Türk takımları için klasik oran (%70-%30)
            weighted_avg = (avg_11 * 0.7) + (avg_bench * 0.3)
        else:
            # Avrupa takımları için as kadro odaklı oran (%85-%15)
            weighted_avg = (avg_11 * 0.85) + (avg_bench * 0.15)

        cursor.execute("UPDATE teams SET overall = ? WHERE name = ?", (int(weighted_avg), team_name))

    print("DONE! All team overalls calculated based on TOP 18 rule.")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    reseed()
