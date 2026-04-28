import os
import json
import sqlite3

# Relegated teams to be permanently removed
to_remove = ['Rizespor', 'Eyüpspor', 'Gençlerbirliği']
db_path = "database/league.db"
tactics_dir = "data/tactics"
teams_json = "data/teams.json"

def cleanup():
    print("--- FULL SYSTEM CLEANUP & FRESH AI START ---")
    
    # 1. Delete Tactics Files (Relegated)
    if os.path.exists(tactics_dir):
        for f in os.listdir(tactics_dir):
            name = f.replace('.txt', '')
            if name in to_remove:
                try:
                    os.remove(os.path.join(tactics_dir, f))
                    print(f"Deleted tactic file: {f}")
                except Exception as e:
                    print(f"Error deleting {f}: {e}")

    # 2. Cleanup Database
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Remove relegated
        for name in to_remove:
            cursor.execute("DELETE FROM teams WHERE name = ?", (name,))
            cursor.execute("DELETE FROM players WHERE team = ?", (name,))
            
        # Clear European Squads and Cache to trigger FRESH AI research with new 82+ rules
        print("Purging European squads and AI cache for fresh research...")
        
        # We delete players of ANY team in European leagues so they get re-researched
        cursor.execute("DELETE FROM players WHERE team IN (SELECT name FROM teams WHERE league IN ('UCL', 'UEL', 'UECL', 'Europe'))")
        
        # Clear all squad research cache
        cursor.execute("DELETE FROM scout_cache WHERE query LIKE 'ext_squad_v2%'")
        
        # Reset European team overalls to 0 so they don't show stale values
        cursor.execute("UPDATE teams SET overall = 0 WHERE league IN ('UCL', 'UEL', 'UECL', 'Europe')")
        
        conn.commit()
        conn.close()
        print("Database cleared for fresh AI research.")

    # 3. Cleanup teams.json
    if os.path.exists(teams_json):
        try:
            with open(teams_json, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            original_count = len(data.get('teams', []))
            data['teams'] = [t for t in data['teams'] if t['name'] not in to_remove]
            new_count = len(data['teams'])
            
            with open(teams_json, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            print(f"cleaned teams.json: {original_count} -> {new_count} teams.")
        except Exception as e:
            print(f"Error cleaning teams.json: {e}")

if __name__ == "__main__":
    cleanup()
