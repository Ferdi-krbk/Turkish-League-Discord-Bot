import sqlite3
import os

# Database path
DB_PATH = os.path.join(os.getcwd(), "database", "league.db")

TURKISH_TEAMS = [
    "Galatasaray", "Samsunspor", "Beşiktaş", "Kocaelispor", "Göztepe", 
    "Konyaspor", "Trabzonspor", "Fenerbahçe", "Erokspor", "Kasımpaşa", 
    "Gaziantep FK", "Alanyaspor", "Başakşehir", "Erzurumspor", "Antalyaspor", 
    "Amedspor", "Kayserispor", "Fatih Karagümrük"
]

def fix_league_categories():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 1. First, set ALL teams to 'Europe' (Reset)
        print("Resetting all teams to 'Europe'...")
        cursor.execute("UPDATE teams SET league = 'Europe'")
        
        # 2. Set the 18 Turkish teams to 'Super Lig'
        print(f"Updating {len(TURKISH_TEAMS)} Turkish teams to 'Super Lig'...")
        for team in TURKISH_TEAMS:
            # Case-insensitive update using slug or LIKE to be safe
            cursor.execute("UPDATE teams SET league = 'Super Lig' WHERE name = ? OR name LIKE ?", (team, team))
            if cursor.rowcount == 0:
                print(f"Warning: Team '{team}' not found in database.")
            else:
                print(f"Updated: {team}")

        conn.commit()
        print("Successfully synchronized league categories.")
        
        # 3. Final count check
        cursor.execute("SELECT league, COUNT(*) FROM teams GROUP BY league")
        stats = cursor.fetchall()
        print("\nFinal Stats:")
        for league, count in stats:
            print(f"- {league}: {count} teams")

    except Exception as e:
        print(f"An error occurred: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    fix_league_categories()
