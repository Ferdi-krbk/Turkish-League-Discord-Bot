import asyncio
import aiosqlite
import random
import math
from typing import List, Optional, Dict, Any

# Note: We need a specialized function to advance tournament rounds without a Discord context
async def advance_tournament_round_logic(tournament_id: int):
    """
    Core logic to advance a tournament round. 
    1. Check all matches in the current round.
    2. Simulate pending ones (fast sim).
    3. Calculate aggregate winners.
    4. Handle ties with ET/Penalties.
    5. Create next round fixtures.
    """
    from core import database # Circular import prevention
    
    # Get fixtures
    fixtures = await database.get_tournament_fixtures(tournament_id)
    if not fixtures:
        return {"status": "error", "message": "Fikstür bulunamadı."}
        
    current_round = fixtures[-1]["round"]
    
    # 1. Fast Sim Pending
    pending = [f for f in fixtures if f["status"] == "Pending" and f["round"] == current_round]
    if pending:
        team_names = list({t for f in pending for t in [f["home_team"], f["away_team"]]})
        all_ovrs = {}
        async with database.get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(f"SELECT name, overall FROM teams WHERE name IN ({','.join(['?']*len(team_names))})", team_names) as cur:
                for r in await cur.fetchall(): all_ovrs[r["name"]] = r["overall"]

            results = []
            for f in pending:
                ovr_h, ovr_a = all_ovrs.get(f["home_team"], 75), all_ovrs.get(f["away_team"], 75)
                diff = (ovr_h + 2) - ovr_a
                l_h, l_a = max(0.3, 1.0 + diff*0.03), max(0.3, 1.0 - diff*0.03)
                
                def get_g(l):
                    r, c = random.random(), 0
                    for g in range(8):
                        p = (math.exp(-l) * l**g) / math.factorial(g)
                        c += p
                        if r <= c: return g
                    return 0
                results.append((get_g(l_h), get_g(l_a), f["id"]))
            
            await db.executemany("UPDATE tournament_fixtures SET home_score=?, away_score=?, status='Played' WHERE id=?", results)
            await db.commit()
            
        # Refresh fixtures
        fixtures = await database.get_tournament_fixtures(tournament_id, current_round)

    # 2. Calculate Winners
    processed, winners = set(), []
    for f in fixtures:
        if f["round"] != current_round: continue
        tk = tuple(sorted([f["home_team"], f["away_team"]]))
        if tk in processed: continue
        
        agg = await database.get_aggregate_score(tournament_id, current_round, f["home_team"], f["away_team"])
        h_name, a_name = f["home_team"], f["away_team"]
        h_total, a_total = agg.get(h_name, 0), agg.get(a_name, 0)
        
        if h_total > a_total:
            winner = h_name
        elif a_total > h_total:
            winner = a_name
        else:
            # Penalties/ET simulation for tie
            all_teams_db = await database.get_all_teams()
            ovr_dict = {t["name"]: t["overall"] for t in all_teams_db if t["name"] in [h_name, a_name]}
            ovr_h, ovr_a = ovr_dict.get(h_name, 75), ovr_dict.get(a_name, 75)
            
            # Simple weighted coin flip for tie-break in GUI
            weight_h = 50 + (ovr_h - ovr_a) * 0.5
            winner = h_name if random.random() * 100 < weight_h else a_name
            
        winners.append(winner)
        processed.add(tk)

    # 3. Create Next Round
    count = len(winners)
    nr = {16: "Son 16", 8: "Çeyrek Final", 4: "Yarı Final", 2: "Final"}.get(count)
    
    if not nr:
        if count == 1: return {"status": "success", "message": f"Turnuva bitti! Şampiyon: {winners[0]}"}
        return {"status": "error", "message": f"Kazanan sayısı ({count}) geçersiz."}

    await database.create_tournament_fixtures(tournament_id, nr, winners, legs=(1 if nr == "Final" else 2))
    return {"status": "success", "message": f"{current_round} bitti, {nr} kuraları çekildi!"}
