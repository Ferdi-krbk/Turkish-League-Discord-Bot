import discord
from discord.ext import commands

class InfoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="yardim", aliases=["help", "yardım", "komutlar"])
    async def yardim_command(self, ctx):
        """Botun tüm komutlarını ve kullanım rehberini gösterir."""
        embed = discord.Embed(
            title="📺 LİG TV - MENAJERLİK PANELİ",
            description="Ligi sallamaya hazır mısın başkan? İşte tüm araçların:",
            color=0x2ecc71 # Radiant Green
        )
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/1165/1165187.png")

        embed.add_field(
            name="🏁 LİG MERKEZİ",
            value=(
                "📊 `!lig` : Puan Durumu\n"
                "📅 `!fikstur` : Maç Programı\n"
                "⚽ `!gol` : Krallık Yarışı\n"
                "🗞️ `!panorama` : Hafta Analizi"
            ),
            inline=True
        )

        embed.add_field(
            name="🏟️ MAÇ GÜNÜ",
            value=(
                "🎮 `!mac [Ev] [Dep]` : Hızlı Maç\n"
                "🎙️ `!canli [Ev] [Dep]` : Canlı Anlatım\n"
                "🚑 `!sakatlar` : Revir Raporu"
            ),
            inline=True
        )

        embed.add_field(
            name="💼 TRANSFER & EKONOMİ",
            value=(
                "🔍 `!ara [İsim]` : Oyuncu Fotoğraflı Scout\n"
                "🤝 `!teklif [İsim] [Bedel]` : Kulüple Pazarlık\n"
                "💶 `!maas [İsim] [Bedel]` : Oyuncuyla Pazarlık\n"
                "💰 `!butce` : Kasa Durumu\n"
                "💸 `!sat [İsim]` : Oyuncunu Sat"
            ),
            inline=False
        )

        if ctx.author.guild_permissions.administrator:
            embed.add_field(
                name="🛠️ YÖNETİM (ADMİN)",
                value="`!veriguncelle`, `!puanyukle`, `!taktik_yukle`, `!butce_ayarla`",
                inline=False
            )

        embed.set_footer(text="Bot Geliştirici Notu: İyi oyunlar dileriz! | © 2026")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(InfoCog(bot))
