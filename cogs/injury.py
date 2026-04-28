"""
Injury Command Cog for Turkish Super League Bot
Handles !sakatlik command for player injuries
"""

import discord
from discord.ext import commands
import json
import os
import random
from typing import Dict, Optional
from datetime import datetime, timedelta

from core.media import MediaGenerator
from core import database


class InjuryCog(commands.Cog):
    """Cog for injury commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.media_generator = MediaGenerator()
        self.teams = {}
        self.players = []
        self._load_data()

    def _load_data(self):
        """Load teams and players data"""
        teams_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "teams.json")
        players_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "players.json")

        if os.path.exists(teams_path):
            with open(teams_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.teams = {t["name"]: t for t in data["teams"]}

        if os.path.exists(players_path):
            with open(players_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.players = {p["name"]: p for p in data["players"]}

    def _find_team(self, name: str) -> Optional[Dict]:
        """Find team by name (case-insensitive, partial match)"""
        name_lower = name.lower()
        for team_name in self.teams:
            if name_lower in team_name.lower() or team_name.lower() in name_lower:
                return self.teams[team_name]
        return None

    def _find_player(self, name: str) -> Optional[Dict]:
        """Find player by name"""
        name_lower = name.lower()
        for player_name, player_data in self.players.items():
            if name_lower in player_name.lower() or player_name.lower() in name_lower:
                return player_data
        return None

    def _generate_injury(self, player: Dict) -> Dict:
        """Generate a realistic injury"""
        # Injury types with typical durations
        injury_types = {
            # Minor injuries (1-2 weeks)
            "Kas zorlanması": (1, 2),
            "Adale yırtığı": (1, 2),
            "Ayak bileği burkulması": (1, 3),
            "Kontüzyon": (1, 1),

            # Moderate injuries (3-6 weeks)
            "Hamstring yırtığı": (3, 5),
            "Diz burkulması": (2, 4),
            "Kas yırtığı": (3, 6),
            "Ayak bileği incinmesi": (2, 4),

            # Severe injuries (6+ weeks)
            "ACL yırtığı": (20, 30),
            "Menisküs yırtığı": (6, 10),
            "Kırık": (8, 12),
            "Ciddi diz sakatlığı": (10, 16),
            "Aşil tendonu": (16, 24),
        }

        # Weight random selection (more minor injuries)
        weights = {
            "Kas zorlanması": 25,
            "Adale yırtığı": 15,
            "Ayak bileği burkulması": 20,
            "Kontüzyon": 15,
            "Hamstring yırtığı": 10,
            "Diz burkulması": 8,
            "Kas yırtığı": 5,
            "Ayak bileği incinmesi": 8,
            "ACL yırtığı": 2,
            "Menisküs yırtığı": 3,
            "Kırık": 2,
            "Ciddi diz sakatlığı": 2,
            "Aşil tendonu": 1,
        }

        injury_type = random.choices(
            list(injury_types.keys()),
            weights=list(weights.values())
        )[0]

        min_weeks, max_weeks = injury_types[injury_type]
        duration = random.randint(min_weeks, max_weeks)

        return {
            "type": injury_type,
            "duration": duration,
            "severity": "hafif" if duration <= 2 else "orta" if duration <= 5 else "ciddi"
        }

    def _parse_injury_input(self, content: str) -> Optional[str]:
        """Parse injury input to get player name"""
        lines = content.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            line_lower = line.lower()

            if line_lower.startswith("player:"):
                return line.split(":", 1)[1].strip()

        # If no "Player:" prefix, treat whole content as player name
        return content.strip()

    def _format_injury_result(self, player: Dict, injury: Dict) -> str:
        """Format injury result"""
        output = []

        output.append(f"🏥 **SAKATLIK HABERİ** 🏥")
        output.append(f"```")
        output.append(f"{player.get('name', 'Bilinmeyen')}")
        output.append(f"```")

        output.append(f"\n🩹 **SAKATLIK TİPİ:** {injury['type']}")
        output.append(f"📅 **SAKATLIK SÜRESİ:** {injury['duration']} hafta")
        output.append(f"⚠️ **DURUM:** {injury['severity'].upper()}")

        # Return date
        return_date = datetime.now() + timedelta(weeks=injury['duration'])
        output.append(f"📅 **BEKLENEN DÖNÜŞ:** {return_date.strftime('%d %B %Y')}")

        # Impact analysis
        output.append(f"\n📊 **ETKİ ANALİZİ:**")
        output.append(f"• Takım: {player.get('team', 'Bilinmeyen')}")
        output.append(f"• Pozisyon: {player.get('position', 'N/A')}")
        output.append(f"• Oyuncu değeri: {player.get('overall', 'N/A')} OVR")

        if injury['severity'] == "ciddi":
            output.append(f"• ⚠️ Takım için BÜYÜK kayıp!")
        elif injury['severity'] == "orta":
            output.append(f"• Takım rotasyonunu etkileyecek")
        else:
            output.append(f"• Kısa süreli yokluk, rotasyon ile idare edilir")

        # Media reaction
        media_reaction = self.media_generator.generate_injury_reaction(
            player.get('name', 'Oyuncu'),
            player.get('team', 'Takım'),
            injury['type'],
            injury['duration']
        )
        output.append(f"\n📰 **MEDYA:** {media_reaction}")

        return "\n".join(output)

    @commands.command(name="sakatlik", aliases=["injury", "sakatlık"])
    async def sakatlik_command(self, ctx: commands.Context, *, content: str = None):
        """
        Generate a player injury

        Usage: !sakatlik
        Player: [Player Name]

        Or simply: !sakatlik [Player Name]
        """
        if not content:
            await ctx.send(
                "❌ **Eksik bilgi!**\n"
                "Lütfen sakatlanan oyuncunun adını girin:\n"
                "```\n"
                "!sakatlik Player: [Oyuncu Adı]\n"
                "veya\n"
                "!sakatlik [Oyuncu Adı]\n"
                "```"
            )
            return

        # Parse input
        player_name = self._parse_injury_input(content)

        if not player_name:
            await ctx.send("❌ **Geçersiz giriş!** Oyuncu adını kontrol edin.")
            return

        # Find player
        player = self._find_player(player_name)
        if not player:
            # Create a generic player if not found
            player = {
                "name": player_name,
                "team": "Bilinmeyen",
                "position": random.choice(["ST", "CM", "CB", "GK"]),
                "overall": random.randint(70, 80)
            }

        # Generate injury
        injury = self._generate_injury(player)

        # Record injury in database
        await database.record_injury(
            player["name"],
            player.get("team", "Bilinmeyen"),
            injury["type"],
            injury["duration"]
        )

        # Send result
        result_output = self._format_injury_result(player, injury)
        await ctx.send(result_output)

    @commands.command(name="injuries", aliases=["sakatliklar", "injurieslist"])
    async def injuries_list_command(self, ctx: commands.Context):
        """Show current injuries"""
        await ctx.send(
            "🏥 **Mevcut Sakatlıklar**\n"
            "Sakatlık kayıtları veritabanında tutulmaktadır.\n"
            "Yeni sakatlık için `!sakatlik` komutunu kullanın."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(InjuryCog(bot))
