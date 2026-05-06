import sqlite3

DB_PATH = "database/league.db"

# Kullanıcının listesi (Transfer Bütçeleri - Milyon €)
budget_data = {
    "Galatasaray SK": 35.0,
    "Fenerbahçe SK": 25.0,
    "Beşiktaş": 20.0,
    "Trabzonspor": 12.0,
    "Samsunspor": 6.0,
    "Gaziantep FK": 4.5,
    "Göztepe": 4.5,
    "Kocaelispor": 3.5,
    "Başakşehir FK": 3.5,
    "Erzurumspor": 2.5, # Eyüpspor yerine Erzurumspor'u kullanıyoruz
    "Rizespor": 3.0,
    "Konyaspor": 2.5,
    "Alanyaspor": 2.0,
    "Fatih Karagümrük": 1.5,
    "Gençlerbirliği SK": 1.5,
    "Kayserispor": 1.0,
    "Kasımpaşa": 0.75, # 0.5 - 1.0 ortalaması
    "Antalyaspor": 0.75  # 0.5 - 1.0 ortalaması
}

def update_budgets():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Bütçe aralıklarını belirle (Maaş bütçesi hesabı için)
    min_tb = 0.75
    max_tb = 35.0
    min_sb = 3.0
    max_sb = 10.0

    for team, tb in budget_data.items():
        # Transfer bütçesini tam sayıya çevir (Euro)
        tb_euro = int(tb * 1_000_000)
        
        # Maaş bütçesi (Oranlı: Min 3M, Max 10M)
        # Formül: min_sb + (tb - min_tb) / (max_tb - min_tb) * (max_sb - min_sb)
        ratio = (tb - min_tb) / (max_tb - min_tb)
        sb = min_sb + (ratio * (max_sb - min_sb))
        sb_euro = int(sb * 1_000_000)

        # Veritabanını güncelle
        # Not: Takım isimlerini DB'deki halleriyle (LIKE) eşleştiriyoruz
        cursor.execute("""
            UPDATE teams 
            SET budget = ?, salary_budget = ? 
            WHERE name LIKE ?
        """, (tb_euro, sb_euro, f"%{team.split(' ')[0]}%"))
        
        if cursor.rowcount > 0:
            print(f"GÜNCELLENDİ: {team} -> Trans: {tb}M €, Maaş: {round(sb, 2)}M €")
        else:
            print(f"UYARI: {team} veritabanında bulunamadı!")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    update_budgets()
