import asyncio
import sys
import os

# Add the project root to sys.path to import core.database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import database

async def main():
    home_team = "Başakşehir"
    away_team = "Erokspor"
    home_score = 1
    away_score = 2
    importance = "Lig"
    
    print(f"Recording: {home_team} {home_score} - {away_score} {away_team}...")
    
    # 1. Update Team Stats
    # winner = away_team, loser = home_team, drawn = False
    await database.update_team_stats(home_team, False, False, True, home_score, away_score)
    await database.update_team_stats(away_team, True, False, False, away_score, home_score)
    
    # 2. Record Match in matches table & Update Fixture
    # record_match handles matches table, goal_scorers (empty here), budget, and fixtures (if names match)
    match_id, comp = await database.record_match(
        home_team, away_team, home_score, away_score, importance
    )
    
    print(f"SUCCESS! Match recorded with ID {match_id} in {comp}. Fixture updated if found.")

if __name__ == "__main__":
    asyncio.run(main())
