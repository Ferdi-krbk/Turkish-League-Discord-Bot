import sqlite3

DB_PATH = "database/league.db"

def setup_europe_full_league_phase():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Turnuvaları oluştur
    tournaments = [('UCL',), ('UEL',), ('UECL',)]
    cursor.executemany("INSERT OR IGNORE INTO tournaments (name) VALUES (?)", tournaments)
    
    cursor.execute("SELECT id, name FROM tournaments")
    t_ids = {name: id for id, name in cursor.fetchall()}

    # 2. Lig Aşaması Maçları (Her takıma tam 8 maç: 4H, 4A)
    fixtures = [
        # GALATASARAY (UCL)
        (t_ids['UCL'], 'Lig Aşaması', 'Galatasaray SK', 'Real Madrid', 1, 'Pending'),
        (t_ids['UCL'], 'Lig Aşaması', 'Galatasaray SK', 'Arsenal FC', 1, 'Pending'),
        (t_ids['UCL'], 'Lig Aşaması', 'Galatasaray SK', 'Juventus', 1, 'Pending'),
        (t_ids['UCL'], 'Lig Aşaması', 'Galatasaray SK', 'PSV Eindhoven', 1, 'Pending'),
        (t_ids['UCL'], 'Lig Aşaması', 'Bayern München', 'Galatasaray SK', 1, 'Pending'),
        (t_ids['UCL'], 'Lig Aşaması', 'SL Benfica', 'Galatasaray SK', 1, 'Pending'),
        (t_ids['UCL'], 'Lig Aşaması', 'Shakhtar Donetsk', 'Galatasaray SK', 1, 'Pending'),
        (t_ids['UCL'], 'Lig Aşaması', 'AS Monaco', 'Galatasaray SK', 1, 'Pending'),

        # FENERBAHÇE (UEL)
        (t_ids['UEL'], 'Lig Aşaması', 'Fenerbahçe SK', 'Manchester United', 1, 'Pending'),
        (t_ids['UEL'], 'Lig Aşaması', 'Fenerbahçe SK', 'Olympique Lyon', 1, 'Pending'),
        (t_ids['UEL'], 'Lig Aşaması', 'Fenerbahçe SK', 'Rangers FC', 1, 'Pending'),
        (t_ids['UEL'], 'Lig Aşaması', 'Fenerbahçe SK', 'PAOK', 1, 'Pending'),
        (t_ids['UEL'], 'Lig Aşaması', 'FC Porto', 'Fenerbahçe SK', 1, 'Pending'),
        (t_ids['UEL'], 'Lig Aşaması', 'Athletic Bilbao', 'Fenerbahçe SK', 1, 'Pending'),
        (t_ids['UEL'], 'Lig Aşaması', 'Ferencvaros', 'Fenerbahçe SK', 1, 'Pending'),
        (t_ids['UEL'], 'Lig Aşaması', 'TSG Hoffenheim', 'Fenerbahçe SK', 1, 'Pending'),

        # BEŞİKTAŞ (UECL)
        (t_ids['UECL'], 'Lig Aşaması', 'Beşiktaş', 'Chelsea FC', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Beşiktaş', 'Real Betis', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Beşiktaş', 'Vikingur', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Beşiktaş', 'FC Astana', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'FC Copenhagen', 'Beşiktaş', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Legia Warsaw', 'Beşiktaş', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'St. Gallen', 'Beşiktaş', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Noah FC', 'Beşiktaş', 1, 'Pending'),

        # TRABZONSPOR (UECL)
        (t_ids['UECL'], 'Lig Aşaması', 'Trabzonspor', 'AC Fiorentina', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Trabzonspor', 'Heidenheim', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Trabzonspor', 'Djurgarden', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Trabzonspor', 'Borac Banja Luka', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Panathinaikos', 'Trabzonspor', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'KAA Gent', 'Trabzonspor', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Omonia Nicosia', 'Trabzonspor', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'NK Celje', 'Trabzonspor', 1, 'Pending'),

        # BAŞAKŞEHİR (UECL)
        (t_ids['UECL'], 'Lig Aşaması', 'Başakşehir FK', 'SS Lazio', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Başakşehir FK', 'Molde FK', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Başakşehir FK', 'Petrocub', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Başakşehir FK', 'Dinamo Minsk', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Cercle Brugge', 'Başakşehir FK', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'APOEL Nicosia', 'Başakşehir FK', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Jagiellonia', 'Başakşehir FK', 1, 'Pending'),
        (t_ids['UECL'], 'Lig Aşaması', 'Larne FC', 'Başakşehir FK', 1, 'Pending'),
    ]

    # 3. Temizlik ve Kayıt
    cursor.execute("DELETE FROM tournament_fixtures")
    cursor.executemany("""
        INSERT INTO tournament_fixtures 
        (tournament_id, round, home_team, away_team, leg, status) 
        VALUES (?, ?, ?, ?, ?, ?)
    """, fixtures)

    conn.commit()
    conn.close()
    print("AVRUPA LİG AŞAMASI (TAM FORMAT - 8 MAÇ) BAŞLATILDI!")
    print("Toplam 40 Avrupa maçı fikstüre eklendi.")

if __name__ == "__main__":
    setup_europe_full_league_phase()
