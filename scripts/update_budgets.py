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
    "Erzurumspor": 2.5,
    "Rizespor": 3.0,
    "Konyaspor": 2.5,
    "Alanyaspor": 2.0,
    "Fatih Karagümrük": 1.5,
    "Gençlerbirliği SK": 1.5,
    "Kayserispor": 1.0,
    "Kasımpaşa": 0.75,
    "Antalyaspor": 0.75
}

def update_combined_budgets():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    min_tb = 0.75
    max_tb = 35.0
    min_sb = 3.0
    max_sb = 10.0

    for team, tb in budget_data.items():
        # Maaş bütçesi hesabı
        ratio = (tb - min_tb) / (max_tb - min_tb)
        sb = min_sb + (ratio * (max_sb - min_sb))
        
        # İKİSİNİ TOPLA
        total_combined = tb + sb
        total_euro = int(total_combined * 1_000_000)

        # Veritabanında SADECE 'budget' sütununa yaz (Salary_budget'ı 0 yapabiliriz veya bırakabiliriz)
        cursor.execute("""
            UPDATE teams 
            SET budget = ?, salary_budget = 0
            WHERE name LIKE ?
        """, (total_euro, f"%{team.split(' ')[0]}%"))
        
        if cursor.rowcount > 0:
            print(f"BİRLEŞTİRİLDİ: {team} -> {round(total_combined, 2)}M € (Trans: {tb}M + Maaş: {round(sb, 2)}M)")
        else:
            print(f"UYARI: {team} bulunamadı!")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    update_combined_budgets()
