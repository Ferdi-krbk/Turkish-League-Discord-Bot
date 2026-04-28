"""
Match Simulation Engine for Turkish Super League Bot
Handles match logic, tactics, formations, and event generation
"""

import random
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime

# Formation bonuses: (defense_bonus, attack_bonus, midfield_bonus)
FORMATION_BONUSES = {
    "4-4-2": (0.05, 0.03, 0.02),      # Balanced
    "4-2-3-1": (0.02, 0.04, 0.04),    # Modern, good midfield control
    "4-3-3": (0.0, 0.05, 0.03),       # Attacking
    "3-5-2": (0.03, 0.02, 0.06),      # Midfield dominance
    "3-4-3": (-0.02, 0.08, 0.02),     # Very attacking, weak defense
    "5-3-2": (0.08, -0.02, 0.0),      # Very defensive
    "4-1-4-1": (0.04, 0.02, 0.04),    # Defensive midfield
    "4-2-2-2": (0.02, 0.04, 0.02),    # Narrow attack
    "3-4-1-2": (0.04, 0.03, 0.03),    # Balanced with striker
    "4-5-1": (0.06, 0.0, 0.04),       # Defensive, counter setup
}

# Tactic interactions: attacker vs defender -> modifier
TACTIC_INTERACTIONS = {
    ("High Press", "Balanced"): 0.08,
    ("High Press", "Defensive"): 0.05,
    ("High Press", "Counter"): -0.10,    # Counter punishes high press
    ("High Press", "Attacking"): 0.03,
    ("Counter", "Attacking"): 0.12,       # Counter destroys attacking teams
    ("Counter", "High Press"): 0.10,
    ("Counter", "Balanced"): 0.02,
    ("Counter", "Defensive"): -0.03,      # Hard to counter parked bus
    ("Attacking", "Defensive"): -0.08,    # Struggles vs low block
    ("Attacking", "High Press"): -0.03,
    ("Attacking", "Counter"): -0.12,
    ("Attacking", "Balanced"): 0.04,
    ("Defensive", "Attacking"): 0.08,
    ("Defensive", "High Press"): -0.05,
    ("Defensive", "Counter"): 0.03,
    ("Defensive", "Balanced"): 0.02,
    ("Balanced", "Defensive"): -0.02,
    ("Balanced", "Attacking"): -0.04,
    ("Balanced", "Counter"): -0.02,
    ("Balanced", "High Press"): -0.03,
}

VALID_TACTICS = ["Defensive", "Balanced", "Attacking", "High Press", "Counter"]
VALID_POSITIONS = ["GK", "RB", "CB", "LB", "CM", "CAM", "RW", "LW", "ST"]


class MatchSimulator:
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.home_advantage = self.config.get("default_home_advantage", 0.15)
        self.derby_variance = self.config.get("derby_variance", 0.25)

    def parse_lineup(self, lineup_text: str) -> Tuple[str, str, Dict[str, str]]:
        """Parse lineup text into formation, tactic, and player positions"""
        lines = [l.strip() for l in lineup_text.strip().split('\n') if l.strip()]

        formation = "4-4-2"  # Default
        tactic = "Balanced"  # Default
        players = {}

        import re
        formation_found = False
        for line in lines:
            lower_line = line.lower()
            
            # 1. Etiketli Kontrol (Diziliş: 4-4-2 veya Ana Diziliş: 4-4-2 vb)
            is_formation_label = lower_line.startswith("formation:") or \
                                 lower_line.startswith("diziliş:") or \
                                 lower_line.startswith("ana diziliş:") or \
                                 "diziliş:" in lower_line
            
            if not formation_found and is_formation_label:
                formation = line.split(":", 1)[1].strip()
                formation_found = True
            # 2. Otomatik Desen Kontrolü (4-4-2 veya 4-2-3-1 gibi desenler)
            elif not formation_found and re.search(r'\d-\d-\d(-\d)?', line):
                match = re.search(r'\d-\d-\d(-\d)?', line)
                formation = match.group(0)
                formation_found = True
            
            if lower_line.startswith("tactic:") or lower_line.startswith("taktik:"):
                tactic = line.split(":", 1)[1].strip()
            
            # Normalization for Turkish/English positions
            pos_map = {
                "GK": "GK", "KALECI": "GK", "KALE": "GK",
                "CB": "CB", "STOPER": "CB", "DEFANS": "CB",
                "RB": "RB", "SAĞ BEK": "RB", "SAG BEK": "RB",
                "LB": "LB", "SOL BEK": "LB",
                "CM": "CM", "ORTA SAHA": "CM", "MERKEZ": "CM",
                "CDM": "CDM", "ÖN LIBERO": "CDM", "ON LIBERO": "CDM",
                "CAM": "CAM", "OFANSIF": "CAM", "10 NUMARA": "CAM",
                "RW": "RW", "SAĞ KANAT": "RW", "SAG KANAT": "RW",
                "LW": "LW", "SOL KANAT": "LW",
                "ST": "ST", "FORVET": "ST", "SANTRAFOR": "ST"
            }

            if ":" in line and not line.lower().startswith("team:"):
                # Parse position: player_name
                parts = line.split(":", 1)
                if len(parts) == 2:
                    raw_pos = parts[0].strip().upper()
                    name = parts[1].strip()
                    
                    pos = pos_map.get(raw_pos, raw_pos)
                    
                    if pos in VALID_POSITIONS or pos in ["CM"] and len(players.get("CM", "").split(",")) < 2:
                        if pos == "CM" and "CM" in players:
                            players[pos] = players[pos] + "," + name
                        else:
                            players[pos] = name

        return formation, tactic, players

    def calculate_team_strength(self, players: Dict[str, str], formation: str,
                                 tactic: str, team_overall: int,
                                 player_db: List[Dict], is_home: bool = False) -> float:
        """Calculate team strength based on players, formation, and tactics"""
        if not player_db:
            # Fallback if no player database
            strength = team_overall / 100.0
            if is_home:
                strength += self.home_advantage
            return strength

        # Build player lookup
        player_lookup = {p["name"]: p for p in player_db}

        total_rating = 0
        count = 0

        for pos, names in players.items():
            for name in names.split(","):
                name = name.strip()
                if name in player_lookup:
                    p = player_lookup[name]
                    # Weight by position relevance
                    if pos == "GK":
                        rating = p.get("defending", 50) * 0.8 + p.get("passing", 50) * 0.2
                    elif pos in ["CB", "RB", "LB"]:
                        rating = p.get("defending", 50) * 0.7 + p.get("pace", 50) * 0.2 + p.get("passing", 50) * 0.1
                    elif pos in ["CM", "CAM"]:
                        rating = p.get("passing", 50) * 0.6 + p.get("shooting", 50) * 0.2 + p.get("pace", 50) * 0.2
                    elif pos in ["RW", "LW", "ST"]:
                        rating = p.get("shooting", 50) * 0.6 + p.get("pace", 50) * 0.25 + p.get("passing", 50) * 0.15
                    else:
                        rating = p.get("overall", 50)

                    total_rating += rating
                    count += 1
                else:
                    # Unknown player - assume average
                    total_rating += 70
                    count += 1

        base_strength = (total_rating / max(count, 1)) / 100.0

        # Apply formation bonus
        if formation in FORMATION_BONUSES:
            form_bonus = sum(FORMATION_BONUSES[formation])
            base_strength *= (1 + form_bonus)

        # Apply tactic bonus
        if tactic == "Attacking":
            base_strength *= 1.05  # +5% attack
        elif tactic == "Defensive":
            base_strength *= 1.03  # +3% defense
        elif tactic == "High Press":
            base_strength *= 1.04
        elif tactic == "Counter":
            base_strength *= 1.02

        # Apply Home Advantage
        if is_home:
            base_strength += self.home_advantage

        return base_strength

    def calculate_gpr(self, base_rating: int, formation: str, tactic: str, is_home: bool = False) -> int:
        """
        Calculate suggested GPR (Global Player Rating).
        Under new logic, this only adds the Home Advantage (+3).
        Tactical scoring is handled by AI.
        """
        gpr = base_rating
        
        # Home Advantage (Fixed +3 as per AI prompt rules)
        if is_home:
            gpr += 3
            
        return gpr

    def get_tactic_modifier(self, tactic_a: str, tactic_b: str) -> Tuple[float, float]:
        """Get tactic interaction modifiers for both teams"""
        # Check direct interactions
        mod_a = TACTIC_INTERACTIONS.get((tactic_a, tactic_b), 0.0)
        mod_b = TACTIC_INTERACTIONS.get((tactic_b, tactic_a), 0.0)

        return mod_a, mod_b
