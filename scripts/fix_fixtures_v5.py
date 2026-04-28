import sqlite3
import random
from collections import defaultdict

DB_PATH = "database/league.db"

def solve_schedule():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM teams WHERE league = 'Super Lig'")
    teams = sorted([row[0] for row in cursor.fetchall()])
    teams = ["Amed" if t == "Amedspor" else t for t in teams]

    cursor.execute("SELECT round_no, home_team, away_team FROM fixtures WHERE round_no IN (1, 2, 3)")
    played = cursor.fetchall()

    played_edges = set()
    history = defaultdict(list)
    for r, h, a in played:
        # Ignore rounds, just care about edges
        played_edges.add(tuple(sorted((h, a))))
        history[h].append("H")
        history[a].append("A")

    # The missing edges for the first half
    missing_edges = []
    for i in range(len(teams)):
        for j in range(i+1, len(teams)):
            t1, t2 = teams[i], teams[j]
            edge = tuple(sorted((t1, t2)))
            if edge not in played_edges:
                missing_edges.append(edge)

    # We need to partition missing_edges into 14 disjoint sets (rounds 4 to 17)
    # Each set must be a perfect matching of the 18 teams.
    rounds = [[] for _ in range(14)] # Index 0=Week 4, ... 13=Week 17
    
    # Pre-calculate adjacent teams (remaining opponents)
    adj = {t: set() for t in teams}
    for e in missing_edges:
        adj[e[0]].add(e[1])
        adj[e[1]].add(e[0])

    def solve_rounds(edge_list):
        # We try to fill one round at a time
        round_matchings = []
        
        def backtrack_round(round_idx, remaining_edges_in_graph):
            if round_idx == 14:
                return True
            
            # For the current round, we need to pick 9 disjoint edges
            def find_matching(edges_pool, current_matching, used_teams_this_round):
                if len(current_matching) == 9:
                    round_matchings.append(current_matching)
                    # Proceed to next round
                    next_edges = [e for e in remaining_edges_in_graph if e not in current_matching]
                    if backtrack_round(round_idx + 1, next_edges):
                        return True
                    # Backtrack
                    round_matchings.pop()
                    return False

                # Heuristic: pick a team not used yet, preferring one with fewest remaining edges in pool
                unused = [t for t in teams if t not in used_teams_this_round]
                if not unused: return False
                
                # Pick t1
                t1 = unused[0]
                
                # Possible t2s
                possible_t2 = [t for t in unused if t != t1 and tuple(sorted((t1, t))) in edges_pool]
                random.shuffle(possible_t2) # add randomness
                
                for t2 in possible_t2:
                    edge = tuple(sorted((t1, t2)))
                    current_matching.append(edge)
                    used_teams_this_round.add(t1)
                    used_teams_this_round.add(t2)
                    
                    if find_matching(edges_pool, current_matching, used_teams_this_round):
                        return True
                    
                    current_matching.pop()
                    used_teams_this_round.remove(t1)
                    used_teams_this_round.remove(t2)

                return False

            return find_matching(remaining_edges_in_graph, [], set())

        success = backtrack_round(0, edge_list)
        return round_matchings if success else None

    print("Attempting to find 1-factorization for weeks 4-17...")
    first_half_schedule = None
    for attempt in range(10):
        # Randomize edges to get different search trees
        shuffled_edges = list(missing_edges)
        random.shuffle(shuffled_edges)
        first_half_schedule = solve_rounds(shuffled_edges)
        if first_half_schedule:
            print(f"Found valid matching on attempt {attempt+1}!")
            break

    if not first_half_schedule:
        print("Failed to partition remaining games into weeks 4-17.")
        conn.close()
        return

    # Now we assign Home/Away status for Weeks 4-17 to minimize H/A streaks
    final_fixtures = []
    
    for round_idx, matching in enumerate(first_half_schedule):
        round_no = 4 + round_idx
        for t1, t2 in matching:
            # Decide home/away
            h1 = history[t1]
            h2 = history[t2]
            
            # Simple streak check
            streak1 = 0
            if len(h1) >= 2 and h1[-1] == "H" and h1[-2] == "H": streak1 = 2 # Has 2 homes
            elif len(h1) >= 2 and h1[-1] == "A" and h1[-2] == "A": streak1 = -2 # Has 2 aways
            
            streak2 = 0
            if len(h2) >= 2 and h2[-1] == "H" and h2[-2] == "H": streak2 = 2
            elif len(h2) >= 2 and h2[-1] == "A" and h2[-2] == "A": streak2 = -2

            # Give t1 Home if they really need it
            if streak1 == -2 or streak2 == 2:
                home, away = t1, t2
            elif streak1 == 2 or streak2 == -2:
                home, away = t2, t1
            else:
                last1 = h1[-1] if h1 else None
                last2 = h2[-1] if h2 else None
                if last1 == "A" and last2 != "A":
                    home, away = t1, t2
                elif last2 == "A" and last1 != "A":
                    home, away = t2, t1
                else:
                    home, away = (t1, t2) if random.random() > 0.5 else (t2, t1)

            final_fixtures.append((round_no, home, away))
            history[home].append("H")
            history[away].append("A")

    # Generate Weeks 18-34 as mirror of Weeks 1-17
    # Fetch 1-3 again, we need exactly who was home and away
    cursor.execute("SELECT round_no, home_team, away_team FROM fixtures WHERE round_no IN (1, 2, 3)")
    first_3 = cursor.fetchall()
    
    all_first_half = list(first_3) + final_fixtures
    
    second_half_fixtures = []
    for r, h, a in all_first_half:
        second_half_fixtures.append((r + 17, a, h))

    cursor.execute("DELETE FROM fixtures WHERE round_no >= 4")
    
    cursor.executemany("INSERT INTO fixtures (round_no, home_team, away_team, status) VALUES (?, ?, ?, 'Pending')", final_fixtures)
    cursor.executemany("INSERT INTO fixtures (round_no, home_team, away_team, status) VALUES (?, ?, ?, 'Pending')", second_half_fixtures)
    
    conn.commit()
    conn.close()
    print("Successfully generated and saved all fixtures for Weeks 4-34!")

if __name__ == "__main__":
    solve_schedule()
