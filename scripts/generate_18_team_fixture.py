import sqlite3
import random
from collections import defaultdict

DB_PATH = "database/league.db"

def generate_fixture():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Takımları al (18 takım)
    cursor.execute("SELECT name FROM teams WHERE league = 'Super Lig' LIMIT 18")
    teams = [row[0] for row in cursor.fetchall()]
    
    if len(teams) < 18:
        print(f"HATA: 18 takım gerekiyor.")
        conn.close()
        return

    # 2. Temizlik
    cursor.execute("DELETE FROM fixtures")
    cursor.execute("UPDATE teams SET played=0, won=0, drawn=0, lost=0, gf=0, ga=0, points=0, form_streak=''")
    
    n = len(teams)
    temp_teams = list(teams)
    
    # Circle Method ile 17 haftalık eşleşmeler
    rounds = []
    for i in range(n - 1):
        matches = []
        for j in range(n // 2):
            t1 = temp_teams[j]
            t2 = temp_teams[n - 1 - j]
            matches.append([t1, t2])
        rounds.append(matches)
        temp_teams.insert(1, temp_teams.pop())

    # 3. Akıllı Ev/Dep Ataması
    # Takımları iki ana gruba ayırıyoruz (Biri HHAA, diğeri AAHH ritminde başlasın)
    # Bu çakışmaları minimize eder.
    team_patterns = {}
    for i, t in enumerate(teams):
        if i % 2 == 0:
            team_patterns[t] = "HHAA"
        else:
            team_patterns[t] = "AAHH"

    history = {t: [] for t in teams}
    final_first_half = []

    def get_preferred(team_name, week_idx):
        pattern = team_patterns[team_name]
        # week_idx 0,1,2,3...
        pos = week_idx % 4
        return pattern[pos]

    for week_idx in range(n - 1):
        round_no = week_idx + 1
        matches = rounds[week_idx]
        
        # Bu haftaki atamalar
        assigned_this_week = set()
        
        # Önce çakışma olmayanları (biri H diğeri A isteyenleri) ata
        conflicts = []
        for t1, t2 in matches:
            p1 = get_preferred(t1, week_idx)
            p2 = get_preferred(t2, week_idx)
            
            if p1 != p2:
                home = t1 if p1 == "H" else t2
                away = t2 if p1 == "H" else t1
                final_first_half.append((round_no, home, away))
                history[home].append("H")
                history[away].append("A")
            else:
                conflicts.append((t1, t2, p1)) # p1 = p2 (H veya A)

        # Çakışmaları çöz (Dengeye göre)
        for t1, t2, pref in conflicts:
            # H/A sayılarına bak, kimin daha çok ihtiyacı var
            h1_count = history[t1].count("H")
            h2_count = history[t2].count("H")
            
            if h1_count < h2_count:
                home, away = t1, t2
            elif h2_count < h1_count:
                home, away = t2, t1
            else:
                # Eşitse rastgele
                if random.random() > 0.5:
                    home, away = t1, t2
                else:
                    home, away = t2, t1
            
            final_first_half.append((round_no, home, away))
            history[home].append("H")
            history[away].append("A")

    # 4. İkinci yarı (Mirror)
    final_fixtures = list(final_first_half)
    for round_no, home, away in final_first_half:
        final_fixtures.append((round_no + 17, away, home))

    # 5. Kaydet
    cursor.executemany(
        "INSERT INTO fixtures (round_no, home_team, away_team, status) VALUES (?, ?, ?, 'Pending')",
        final_fixtures
    )
    
    conn.commit()
    conn.close()
    print("BAŞARILI: 18 takımlı '2 Ev - 2 Dep' odaklı fikstür oluşturuldu.")

if __name__ == "__main__":
    generate_fixture()
