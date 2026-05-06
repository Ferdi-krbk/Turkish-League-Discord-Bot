import sqlite3

DB_PATH = "database/league.db"

def setup_europe():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Turnuvaları oluştur
    tournaments = [('UCL',), ('UEL',), ('UECL',)]
    cursor.executemany("INSERT OR IGNORE INTO tournaments (name) VALUES (?)", tournaments)
    
    # Tournament ID'lerini al
    cursor.execute("SELECT id, name FROM tournaments")
    t_ids = {name: id for id, name in cursor.fetchall()}

    # 2. Maçları hazırla (Son 16 Turu)
    # GS -> UCL, FB -> UEL, JK-TS-Başak -> UECL
    fixtures = [
        # UCL
        (t_ids['UCL'], 'Son 16', 'Galatasaray SK', 'Real Madrid', 1, 'Pending'),
        (t_ids['UCL'], 'Son 16', 'Real Madrid', 'Galatasaray SK', 2, 'Pending'),
        
        # UEL
        (t_ids['UEL'], 'Son 16', 'Fenerbahçe SK', 'Tottenham Hotspur', 1, 'Pending'),
        (t_ids['UEL'], 'Son 16', 'Tottenham Hotspur', 'Fenerbahçe SK', 2, 'Pending'),
        
        # UECL
        (t_ids['UECL'], 'Son 16', 'Beşiktaş', 'Chelsea FC', 1, 'Pending'),
        (t_ids['UECL'], 'Son 16', 'Chelsea FC', 'Beşiktaş', 2, 'Pending'),
        
        (t_ids['UECL'], 'Son 16', 'Trabzonspor', 'AC Fiorentina', 1, 'Pending'),
        (t_ids['UECL'], 'Son 16', 'AC Fiorentina', 'Trabzonspor', 2, 'Pending'),
        
        (t_ids['UECL'], 'Son 16', 'Başakşehir FK', 'SS Lazio', 1, 'Pending'),
        (t_ids['UECL'], 'Son 16', 'SS Lazio', 'Başakşehir FK', 2, 'Pending')
    ]

    # 3. Fikstürü temizle ve ekle
    cursor.execute("DELETE FROM tournament_fixtures")
    cursor.executemany("""
        INSERT INTO tournament_fixtures 
        (tournament_id, round, home_team, away_team, leg, status) 
        VALUES (?, ?, ?, ?, ?, ?)
    """, fixtures)

    conn.commit()
    conn.close()
    print("AVRUPA ARENASI HAZIR!")
    print("UCL: Galatasaray vs Real Madrid")
    print("UEL: Fenerbahçe vs Tottenham")
    print("UECL: Beşiktaş vs Chelsea, Trabzonspor vs Fiorentina, Başakşehir vs Lazio")

if __name__ == "__main__":
    setup_europe()
