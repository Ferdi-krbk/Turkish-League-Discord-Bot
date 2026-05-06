import discord
from discord.ext import commands
import aiosqlite
from core import database
from typing import Optional, Dict

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="sifirla", aliases=["reset", "lig_sifirla", "lig_sıfırla"])
    @commands.has_permissions(administrator=True)
    async def sifirla_command(self, ctx, confirmation: str = None):
        """
        Ligi, maçları ve kupaları tamamen sıfırlar (Bütçeler ve Kadrolar Kalır).
        
        Kullanım: !sifirla onay
        """
        if confirmation != "onay":
            embed = discord.Embed(
                title="⚠️ KRİTİK UYARI: LİG SIFIRLAMA",
                description=(
                    "Bu komut ligdeki tüm ilerlemeyi **KALICI OLARAK** silecektir!\n\n"
                    "**Neler Sıfırlanacak?**\n"
                    "✅ Puan Durumu (Galibiyet, Beraberlik, Mağlubiyet, Puan)\n"
                    "✅ Gol ve Asist Krallığı verileri\n"
                    "✅ Tüm Fikstür ve Avrupa Kupaları (Turnuvalar)\n"
                    "✅ Avrupa Takımları ve Oyuncuları (Yabancı takımlar silinir)\n"
                    "✅ Maç Geçmişi, Transferler ve Sakatlıklar\n\n"
                    "**Neler Korunacak?**\n"
                    "❌ Takım Bütçeleri (Kasa durumu değişmez)\n"
                    "❌ Oyuncu Kadroları (Yaptığınız tüm transferler ve OVR düzenlemeleri kalır)\n\n"
                    "Emin misin başkan? Devam etmek için: `!sifirla onay` yazmalısın."
                ),
                color=0xe74c3c # Alizarin Red
            )
            await ctx.send(embed=embed)
            return

        # Sıfırlama işlemi başlıyor
        msg = await ctx.send("⏳ **Sistem sıfırlanıyor, lütfen bekle...**")
        
        try:
            async with aiosqlite.connect(database.DB_PATH) as db:
                # 1. Rekabetçi Geçmişi ve İstatistikleri Sil
                await db.execute("DELETE FROM matches")
                await db.execute("DELETE FROM goal_scorers")
                await db.execute("DELETE FROM injuries")
                await db.execute("DELETE FROM transfers")
                await db.execute("DELETE FROM scout_cache")
                
                # 2. Fikstür ve Turnuvaları Sil
                await db.execute("DELETE FROM fixtures")
                await db.execute("DELETE FROM tournament_fixtures")
                await db.execute("DELETE FROM tournaments")
                
                # 3. Puan Durumunu Sıfırla (Bütçeye dokunma)
                await db.execute("""
                    UPDATE teams 
                    SET played = 0, won = 0, drawn = 0, lost = 0, 
                        gf = 0, ga = 0, points = 0, form_streak = ''
                    WHERE league NOT IN ('Europe', 'UCL', 'UEL', 'UECL')
                """)
                
                # 4. Avrupa Takımlarını ve Oyuncularını Kökten Sil (Yeni sezon için)
                # Bu takımlar turnuva kurulduğunda tekrar eklenecek.
                await db.execute("""
                    DELETE FROM players 
                    WHERE team IN (SELECT name FROM teams WHERE league IN ('Europe', 'UCL', 'UEL', 'UECL'))
                """)
                await db.execute("DELETE FROM teams WHERE league IN ('Europe', 'UCL', 'UEL', 'UECL')")
                
                # 5. Oyuncu Cezalarını Sıfırla
                await db.execute("UPDATE players SET suspension_matches = 0")
                
                await db.commit()

            embed = discord.Embed(
                title="✅ SİSTEM SIFIRLANDI",
                description=(
                    "Lig tablosu, istatistikler ve kupalar başarıyla sıfırlandı.\n\n"
                    "**Yeni Sezon İçin Hazırız!**\n"
                    "📍 Bütçeler ve Kadrolar korundu.\n"
                    "📅 Yeni fikstür oluşturmak için `!fikstur` komutunu kullanabilirsin."
                ),
                color=0x2ecc71 # Radiant Green
            )
            embed.set_footer(text="© 2026 LİG TV Yazılım Servisleri")
            await msg.edit(content=None, embed=embed)
            
        except Exception as e:
            await msg.edit(content=f"❌ **Hata oluştu:** {e}")

    async def _find_team(self, name: str) -> Optional[Dict]:
        """Basit SQL tabanlı takım arama yardımcısı"""
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM teams WHERE LOWER(name) LIKE ? OR LOWER(slug) = ?", 
                (f"%{(name or '').lower()}%", (name or '').lower())
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    @commands.command(name="lig_dusur", aliases=["lig_düşür", "düşür", "dusur"])
    @commands.has_permissions(administrator=True)
    async def lig_dusur_command(self, ctx, *, team_name: str):
        """Bir takımı Süper Lig'den düşürür (1. Lig'e taşır)."""
        team = await self._find_team(team_name)
        if not team:
            await ctx.send(f"❌ **Hata:** `{team_name}` adında bir takım bulunamadı.")
            return

        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute("UPDATE teams SET league = '1. Lig' WHERE id = ?", (team['id'],))
            await db.commit()

        embed = discord.Embed(
            title="📉 KÜME DÜŞÜRME",
            description=f"**{team['name']}** takımı başarıyla Süper Lig'den düşürüldü ve 1. Lig'e taşındı.",
            color=0xe67e22 # Carrot Orange
        )
        await ctx.send(embed=embed)

    @commands.command(name="lig_ekle", aliases=["lig_yükselt", "ekle"])
    @commands.has_permissions(administrator=True)
    async def lig_ekle_command(self, ctx, *, team_name: str):
        """Bir takımı Süper Lig'e ekler/yükseltir."""
        team = await self._find_team(team_name)
        if not team:
            await ctx.send(f"❌ **Hata:** `{team_name}` adında bir takım bulunamadı.")
            return

        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute("UPDATE teams SET league = 'Super Lig' WHERE id = ?", (team['id'],))
            await db.commit()

        embed = discord.Embed(
            title="📈 LİGE YÜKSELME",
            description=f"**{team['name']}** takımı başarıyla Süper Lig'e dahil edildi.",
            color=0x3498db # Peter River Blue
        )
        await ctx.send(embed=embed)
    
    @commands.command(name="toplu_ekle", aliases=["bulk_import", "tümünü_ekle", "tumunu_ekle"])
    @commands.has_permissions(administrator=True)
    async def toplu_ekle_command(self, ctx):
        """data/tactics klasöründeki tüm TXT dosyalarını takım olarak lige ekler."""
        msg = await ctx.send("📂 **Taktik klasörü taranıyor...**")
        
        tactics_dir = os.path.join(database.BASE_PATH, "data", "tactics")
        if not os.path.exists(tactics_dir):
            return await msg.edit(content="❌ **Hata:** `data/tactics` klasörü bulunamadı.")
            
        added_count = 0
        skipped_count = 0
        
        files = [f for f in os.listdir(tactics_dir) if f.endswith(".txt")]
        
        for filename in files:
            team_name = filename.replace(".txt", "").strip()
            # Veritabanına ekle (Eğer yoksa)
            try:
                await database.ensure_team_exists(team_name, 'Super Lig')
                added_count += 1
            except Exception as e:
                print(f"DEBUG: Error adding {team_name}: {e}")
                skipped_count += 1
                
        embed = discord.Embed(
            title="📂 TOPLU İÇE AKTARMA TAMAMLANDI",
            description=(
                f"✅ **Eklenen Takım Sayısı:** `{added_count}`\n"
                f"⚠️ **Atlanan/Hatalı:** `{skipped_count}`\n\n"
                "Artık tüm bu takımlar puan durumunda (`!lig`) görünecektir."
            ),
            color=0x9b59b6 # Amethyst Purple
        )
        await msg.edit(content=None, embed=embed)

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
