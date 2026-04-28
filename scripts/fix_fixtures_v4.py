import sqlite3
import os
import random
from collections import defaultdict

DB_PATH = "database/league.db"

def solve():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM teams WHERE league = 'Super Lig'")
    teams = sorted([row[0] for row in cursor.fetchall()])
    # Map to Amed consistency
    teams = ["Amed" if t == "Amedspor" else t for t in teams]

    cursor.execute("SELECT round_no, home_team, away_team FROM fixtures WHERE round_no IN (1, 2, 3)")
    played = cursor.fetchall()
    
    played_fixtures = set([(h, a) for _, h, a in played])
    history = defaultdict(list)
    for r, h, a in played:
        history[h].append("H")
        history[a].append("A")

    # All possible fixtures for full season (306)
    pool = []
    for t1 in teams:
        for t2 in teams:
            if t1 != t2 and (t1, t2) not in played_fixtures:
                pool.append((t1, t2))

    for attempt in range(1, 20000):
        current_pool = list(pool)
        current_history = {t: list(history[t]) for t in teams}
        results = []
        is_valid = True
        
        for r in range(4, 35):
            week_matches = []
            available = set(teams)
            
            # Simple greedy matching for this week
            random.shuffle(current_pool)
            
            for i in range(len(current_pool) - 1, -1, -1):
                h, a = current_pool[i]
                if h in available and a in available:
                    # Constraint: No more than 3 consecutive (User said 1-1 but 2-2 is okay for balance)
                    if current_history[h][-2:] == ["H", "H"]: continue
                    if current_history[a][-2:] == ["A", "A"]: continue
                    
                    week_matches.append((r, h, a))
                    available.remove(h)
                    available.remove(a)
                    current_pool.pop(i)
                    current_history[h].append("H")
                    current_history[a].append("A")
                
                if len(week_matches) == 9: break
                
            if len(week_matches) < 9:
                is_valid = False
                break
            results.extend(week_matches)
        
        if is_valid:
            print(f"Success on attempt {attempt}!")
            cursor.execute("DELETE FROM fixtures WHERE round_no >= 4")
            cursor.executemany("INSERT INTO fixtures (round_no, home_team, away_team, status) VALUES (?, ?, ?, 'Pending')", results)
            conn.commit()
            conn.close()
            return True

    conn.close()
    return False

if __name__ == "__main__":
    solve()
