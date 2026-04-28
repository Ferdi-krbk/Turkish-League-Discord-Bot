import sqlite3
import os
import random
from collections import defaultdict

DB_PATH = "database/league.db"

def fix_fixtures():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM teams WHERE league = 'Super Lig'")
    teams = [row[0] for row in cursor.fetchall()]

    def get_fixture_name(name):
        return "Amed" if name == "Amedspor" else name

    fixture_teams = [get_fixture_name(t) for t in teams]
    num_teams = len(fixture_teams)

    cursor.execute("SELECT round_no, home_team, away_team FROM fixtures WHERE round_no IN (1, 2, 3) ORDER BY round_no")
    played_fixtures = cursor.fetchall()
    
    played_set = set([(h, a) for _, h, a in played_fixtures])
    team_history = defaultdict(list)
    for r, h, a in played_fixtures:
        team_history[h].append("H")
        team_history[a].append("A")

    all_possible = []
    for t1 in fixture_teams:
        for t2 in fixture_teams:
            if t1 != t2:
                if (t1, t2) not in played_set:
                    all_possible.append((t1, t2))

    def try_gen():
        pool = list(all_possible)
        history = {t: list(team_history[t]) for t in fixture_teams}
        results = []

        for r in range(4, 35):
            available = set(fixture_teams)
            round_matches = []
            
            # Heuristic: Sort pool by how much teams need a specific H/A status
            # But for simplicity, just shuffle and filter
            candidates = list(pool)
            random.shuffle(candidates)
            
            for h, a in candidates:
                if h in available and a in available:
                    h_last = history[h][-1] if history[h] else None
                    a_last = history[a][-1] if history[a] else None
                    
                    # Hard Constraint: No more than 2 consecutive H/A
                    if history[h][-2:] == ["H", "H"]: continue
                    if history[a][-2:] == ["A", "A"]: continue
                    
                    # Semi-Hard: Try to alternate
                    if r < 34 and random.random() < 0.8: # Allow some flexibility to prevent deadends
                        if h_last == "H" or a_last == "A": continue

                    round_matches.append((r, h, a))
                    available.remove(h)
                    available.remove(a)
                    history[h].append("H")
                    history[a].append("A")
                    
                    # Remove from pool
                    # For performance, we'll filter pool after round is done
            
            if len(round_matches) < 9: return None
            
            # Update pool
            matches_set = set([(h, a) for _, h, a in round_matches])
            pool = [p for p in pool if p not in matches_set]
            results.extend(round_matches)
            
        return results

    for attempt in range(1, 5001):
        res = try_gen()
        if res:
            print(f"Success on attempt {attempt}!")
            cursor.execute("DELETE FROM fixtures WHERE round_no >= 4")
            cursor.executemany("INSERT INTO fixtures (round_no, home_team, away_team, status) VALUES (?, ?, ?, 'Pending')", res)
            conn.commit()
            conn.close()
            return True
            
    conn.close()
    return False

if __name__ == "__main__":
    if fix_fixtures():
        print("Fixtures fixed!")
    else:
        print("Failed.")
