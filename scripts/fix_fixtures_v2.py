import sqlite3
import os
import random
from collections import defaultdict

DB_PATH = "database/league.db"

def fix_fixtures():
    if not os.path.exists(DB_PATH):
        print(f"Error: {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Get all teams and handle Amed/Amedspor name mapping
    cursor.execute("SELECT name FROM teams WHERE league = 'Super Lig'")
    teams = [row[0] for row in cursor.fetchall()]
    
    # Mapping for consistency (fixtures uses 'Amed')
    def get_fixture_name(name):
        return "Amed" if name == "Amedspor" else name

    fixture_teams = [get_fixture_name(t) for t in teams]
    num_teams = len(fixture_teams)
    
    if num_teams != 18:
        print(f"Warning: Found {num_teams} teams, expected 18.")

    # 2. Get Week 1-3 fixtures
    cursor.execute("SELECT round_no, home_team, away_team FROM fixtures WHERE round_no IN (1, 2, 3) ORDER BY round_no")
    played_fixtures = cursor.fetchall()
    
    played_pairings = set()
    team_history = defaultdict(list)
    
    for r, h, a in played_fixtures:
        pair = tuple(sorted((h, a)))
        played_pairings.add(pair)
        team_history[h].append("H")
        team_history[a].append("A")

    print(f"Preserved {len(played_pairings)} pairings in weeks 1-3.")

    # 3. Generate all 306 possible fixtures for the full season
    # (Every team plays every other team once at home and once away)
    full_fixture_pool = []
    for t1 in fixture_teams:
        for t2 in fixture_teams:
            if t1 != t2:
                full_fixture_pool.append((t1, t2))
    
    # Remove the 27 already played
    # Need to be exact about who was home/away in 1-3
    played_fixtures_set = set([(h, a) for _, h, a in played_fixtures])
    remaining_pool = [f for f in full_fixture_pool if f not in played_fixtures_set]
    
    print(f"Assigning {len(remaining_pool)} fixtures to weeks 4-34...")

    def try_generate():
        pool = list(remaining_pool)
        history = {t: list(team_history[t]) for t in fixture_teams}
        all_new_fixtures = []

        for r in range(4, 35):
            available_this_round = set(fixture_teams)
            matches_this_round = []
            
            # Greedy matching for this round
            random.shuffle(pool)
            
            # Optimization: Sort pool to prioritize home-desiring teams?
            # For now, just greedy-random with retry
            attempts = 0
            while len(matches_this_round) < 9 and attempts < 300:
                found = False
                for i, (h, a) in enumerate(pool):
                    if h in available_this_round and a in available_this_round:
                        # H/A Balancing
                        last_h = history[h][-1] if history[h] else None
                        last_a = history[a][-1] if history[a] else None
                        
                        # Ideal: h was Away, a was Home
                        if last_h == "A" and last_a == "H":
                            # Perfect
                            pass
                        elif (last_h == "A") or (last_a == "H"):
                            # Acceptable
                            pass
                        elif r > 4: # If not week 4, be stricter?
                            if random.random() > 0.3: continue # Try to find better match
                        
                        matches_this_round.append((r, h, a))
                        available_this_round.remove(h)
                        available_this_round.remove(a)
                        pool.pop(i)
                        history[h].append("H")
                        history[a].append("A")
                        found = True
                        break
                if not found: break
                attempts += 1
            
            if len(matches_this_round) < 9:
                return None # Failed round
            
            all_new_fixtures.extend(matches_this_round)
        
        return all_new_fixtures

    # 4. Success-loop
    final_fixtures = None
    for attempt in range(1, 2001):
        final_fixtures = try_generate()
        if final_fixtures:
            print(f"Full season schedule found on attempt {attempt}!")
            break
    
    if not final_fixtures:
        print("Failed to generate schedule after 2000 attempts.")
        return False

    # 6. Database Update
    cursor.execute("DELETE FROM fixtures WHERE round_no >= 4")
    cursor.executemany("INSERT INTO fixtures (round_no, home_team, away_team, status) VALUES (?, ?, ?, 'Pending')", final_fixtures)

    conn.commit()
    conn.close()
    print("Database updated successfully.")
    return True

if __name__ == "__main__":
    fix_fixtures()
