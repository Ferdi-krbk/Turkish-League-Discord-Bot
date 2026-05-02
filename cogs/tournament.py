import discord
from discord.ext import commands
import aiosqlite
from core import database
from typing import List, Optional
import re

# Realistic Giant Teams for Automatic Filling (Only Foreign Giants)
# Realistic Giant Teams for Automatic Filling (36 teams each for the New League System)
UCL_GIANTS = [
    "Real Madrid", "Manchester City", "Bayern München", "Paris Saint-Germain", "Arsenal", 
    "Inter Milan", "Atletico Madrid", "Bayer Leverkusen", "Barcelona", "Borussia Dortmund", 
    "Juventus", "Liverpool", "AC Milan", "Aston Villa", "Sporting CP", "Benfica",
    "Atalanta", "Feyenoord", "PSV Eindhoven", "RB Salzburg", "Celtic", "AS Monaco", 
    "VfB Stuttgart", "Girona", "Bologna", "Lille OSC", "Stade Brest", "RB Leipzig", 
    "Club Brugge", "Shakhtar Donetsk", "Crvena Zvezda", "Sparta Praha", "Dinamo Zagreb", 
    "Sturm Graz", "Young Boys", "Slovan Bratislava"
]
UEL_GIANTS = [
    "AS Roma", "Manchester United", "Tottenham Hotspur", "Ajax", "Lazio", 
    "FC Porto", "Real Sociedad", "Olympique Lyon", "Eintracht Frankfurt", "Marseille", 
    "Villarreal", "Rangers", "Athletic Bilbao", "OGC Nice", "Real Betis", 
    "Olympiacos", "PAOK", "SC Braga", "Slavia Praha", "AZ Alkmaar", 
    "Ludogorets", "Malmö FF", "FCSB", "Qarabağ FK", "Galatasaray", 
    "Fenerbahçe", "Beşiktaş", "Union St Gilloise", "Dynamo Kyiv", "Ferencváros", 
    "Bodø/Glimt", "Viktoria Plzeň", "Hoffenheim", "Anderlecht", "Midtjylland", 
    "Maccabi Tel Aviv", "Genk", "Stade Rennais", "SC Freiburg", "Hearts",
    "Sheriff Tiraspol", "Servette FC", "Sivasspor", "HJK Helsinki", "Molde FK"
]
UECL_GIANTS = [
    "Chelsea", "Fiorentina", "Heidenheim", "Vitória SC", 
    "Gent", "Legia Warszawa", "Cercle Brugge", "FC Lugano", "Panathinaikos",
    "FC Copenhagen", "St Gallen", "SK Rapid Wien", 
    "Djurgården", "İstanbul Başakşehir", "Omonia Nicosia", "APOEL Nicosia", "Vikingur", 
    "Larne FC", "Dinamo Minsk", "FC Noah", "Pafos FC", "Petrocub Hîncești", 
    "Jagiellonia", "Heart of Midlothian", "Shamrock Rovers", "The New Saints", "Borac Banja Luka", 
    "NK Celje", "Astana", "Mladá Boleslav", "Olimpija Ljubljana", 
    "TSC Bačka Topola", "Ballkani", "Pyunik", "Spartak Trnava", "Shkupi"
]

class TournamentCog(commands.Cog, name="Kupa"):
    def __init__(self, bot):
        self.bot = bot

    def _add_split_fields(self, embed, name, value, inline=False):
        """Splits values > 1024 chars into multiple fields to avoid Discord API errors"""
        if not value: return
        value = str(value)
        if len(value) <= 1024:
            embed.add_field(name=name, value=value, inline=inline)
            return

        chunks = []
        val_to_split = value
        while len(val_to_split) > 1000:
            split_idx = val_to_split.rfind('\n', 0, 1000)
            if split_idx == -1: split_idx = val_to_split.rfind(' ', 0, 1000)
            if split_idx == -1: split_idx = 1000
            chunks.append(val_to_split[:split_idx].strip())
            val_to_split = val_to_split[split_idx:].strip()
        if val_to_split: chunks.append(val_to_split)

        for i, chunk in enumerate(chunks):
            field_name = name if i == 0 else f"{name} (Devam {i})"
            embed.add_field(name=field_name, value=chunk, inline=inline)

    def _normalize_round_name(self, r_name: str) -> str:
        """Standardizes tournament round names to prevent duplicates like 'Ceyrek' and 'Çeyrek Final'"""
        if not r_name: return r_name
        r_low = r_name.lower().strip()
        
        if any(x in r_low for x in ["ceyrek", "çeyrek", "quarter"]): return "Çeyrek Final"
        if any(x in r_low for x in ["yarı", "yari", "semi"]): return "Yarı Final"
        if any(x in r_low for x in ["son 16", "round of 16"]): return "Son 16"
        if r_low == "final": return "Final"
        
        return r_name.title()

    @commands.command(name="turnuva_hazirla", aliases=["kupa_kur", "tournament_setup"])
    @commands.has_permissions(administrator=True)
    async def turnuva_hazirla_command(self, ctx, tournament_name: str, round_name: str, *teams: str):
        """
        Kupa/Turnuva turu hazırlar. Eksik takımları otomatik devlerle doldurur.
        Kullanım: !turnuva_hazirla <ucl|uel|uecl> "Çeyrek Final" Takım1 ...
        """
        import random
        t_name = tournament_name.upper()
        if t_name not in ["UCL", "UEL", "UECL"]:
            return await ctx.send("❌ **Hata:** Geçerli bir turnuva adı girin (UCL, UEL, UECL).")

        # 1. Tur ismini ve takımları akıllıca ayrıştır (Boşluklu tur isimleri için)
        current_round = round_name
        current_teams = list(teams)
        
        # Eğer kullanıcı "Çeyrek Final" yerine sadece "Çeyrek" yazdıysa ve ilk "takım" "Final" ise birleştir
        if current_round.lower() in ["çeyrek", "yarı", "round", "son"] and current_teams:
            next_word = current_teams[0].lower()
            if next_word in ["final", "16", "of"]:
                current_round = f"{round_name} {current_teams.pop(0)}"

        round_map = {
            "son 16": 16, "round of 16": 16, "son16": 16,
            "çeyrek final": 8, "quarter final": 8, "çeyrek": 8,
            "yarı final": 4, "semi final": 4, "yarı": 4,
            "final": 2
        }
        
        normalized_round = current_round.lower()
        required_count = round_map.get(normalized_round, len(current_teams))
        if required_count % 2 != 0: required_count += 1 # Çift sayıya zorla
        
        # 2. Eksik varsa devlerle doldur
        if len(current_teams) < required_count:
            giants = UCL_GIANTS if t_name == "UCL" else (UEL_GIANTS if t_name == "UEL" else UECL_GIANTS)
            available_giants = [g for g in giants if g.lower() not in [t.lower() for t in current_teams]]
            
            needed = required_count - len(current_teams)
            to_add = random.sample(available_giants, min(needed, len(available_giants)))
            current_teams.extend(to_add)

        if len(current_teams) < 2 or len(current_teams) % 2 != 0:
            return await ctx.send(f"❌ **Hata:** Takım sayısı yetersiz veya tek sayı ({len(current_teams)}).")

        # Turnuvayı oluştur veya ID'sini al
        t_id = await database.create_tournament(t_name)
        
        # Mevcut turdaki tüm fikstürleri temizle
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute("DELETE FROM tournament_fixtures WHERE tournament_id = ? AND round = ?", (t_id, current_round))
            await db.commit()

        # Fikstürleri oluştur
        await database.create_tournament_fixtures(t_id, current_round, current_teams)
        
        # Sayıları düzgün hesaplayalım
        manual_count = len(teams)
        if current_round != round_name: # Eğer birleştirme yapıldıysa (Çeyrek Final gibi)
            manual_count -= 1 

        auto_count = len(current_teams) - manual_count

        await ctx.send(f"🏆 **{t_name} - {current_round}** başarıyla hazırlandı!\n✅ **{len(current_teams)}** takım eşleşti ({manual_count} manuel, {auto_count} otomatik dev).")
        await ctx.invoke(self.bot.get_command("kupa_fikstur"), tournament_name=t_name, round_name=current_round)

    @commands.command(name="lig_asamasi_kur", aliases=["league_stage_setup", "ucl_lig_kur"])
    @commands.has_permissions(administrator=True)
    async def lig_asamasi_kur_command(self, ctx, tournament_name: str, *teams: str):
        """
        36 takımlı yeni UEFA Lig Aşaması (Swiss System) kurasını çeker.
        Kullanım: !lig_asamasi_kur <ucl|uel|uecl> Takım1 Takım2 ...
        """
        import random
        t_name = tournament_name.upper()
        if t_name not in ["UCL", "UEL", "UECL"]:
            return await ctx.send("❌ **Hata:** Geçerli bir turnuva adı girin (UCL, UEL, UECL).")

        await ctx.send(f"🔄 **{t_name} Lig Aşaması** kuraları çekiliyor... (36 takım, 4 torba)")

        # 1. Takım Listesini Hazırla
        current_teams = list(teams)
        manual_names_lower = [t.lower() for t in current_teams]

        # A. Veritabanından Elitleri çek — SADECE o turnuvanın listesindeki takımlar
        # (UEL'de UECL takımları çıkmasın diye giants_list ile kesişim yapıyoruz)
        giants_list_for_db = UCL_GIANTS if t_name == "UCL" else (UEL_GIANTS if t_name == "UEL" else UECL_GIANTS)
        giants_lower_set = {g.lower() for g in giants_list_for_db}
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT name FROM teams WHERE tier = 'Elite'") as cursor:
                rows = await cursor.fetchall()
                db_elites = [r["name"] for r in rows if r["name"].lower() in giants_lower_set]

        # Elitleri ekle (turnuvaya uygun olanları, TR kontrolüyle)
        random.shuffle(db_elites)
        for e in db_elites:
            if len(current_teams) >= 36: break
            if e.lower() not in manual_names_lower:
                current_teams.append(e)
                manual_names_lower.append(e.lower())

        # B. Hala 36 değilse Gerçek Avrupa Devleri (Lists) ile tamamla
        if len(current_teams) < 36:
            giants_list = giants_list_for_db  # Zaten yukarıda doğru liste seçildi
            random.shuffle(giants_list)
            
            # TR Takımları Listesi (Sızmayı önlemek için)
            tr_blacklist = [
                "galatasaray", "fenerbahçe", "beşiktaş", "başakşehir", "trabzonspor",
                "kayserispor", "kocaelispor", "samsunspor", "sivasspor", "amed sk",
                "kasımpaşa", "gaziantep fk", "fatih karagümrük", "adana demirspor",
                "antalyaspor", "hatayspor", "rizespor", "alanyaspor", "giresunspor",
                "erzurumspor", "boluspor", "altay", "ankaragücü", "çaykur rizespor"
            ]
            
            for g in giants_list:
                if len(current_teams) >= 36: break
                g_low = g.lower()
                # Eğer dev takım TR takımıysa ve manuel yazılmamışsa GEÇ
                if g_low in tr_blacklist and g_low not in manual_names_lower:
                    continue
                if g_low not in manual_names_lower:
                    current_teams.append(g)
                    manual_names_lower.append(g_low)

        # C. SON ÇARE: Jenerik isimler (Dünyada takım bitmişse)
        while len(current_teams) < 36:
            current_teams.append(f"Avrupa Takımı {len(current_teams)+1}")

        # 2. Takımları Güce Göre Sırala ve Torbalara Ayır (İSİM NORMALİZASYONU)
        team_data = []
        for t in current_teams:
            db_team = await database.search_team(t)
            # Kritik: Veritabanındaki 'Resmi İsmi'ni kullan (Kocaeli vs Kocaelispor hatası için)
            official_name = db_team["name"] if db_team else t
            ovr = db_team["overall"] if db_team else 75
            team_data.append({"name": official_name, "overall": ovr})
        
        # Tekrarla (Duplicate) kontrolü (Normalizasyon sonrası oluşmuş olabilir)
        seen_names = set()
        final_team_data = []
        for td in team_data:
            if td["name"] not in seen_names:
                final_team_data.append(td)
                seen_names.add(td["name"])
        
        # 36'ya tamamla (Normalizasyon sonrası eksildiyse)
        while len(final_team_data) < 36:
            final_team_data.append({"name": f"Avrupa Takımı {len(final_team_data)+1}", "overall": 70})
            
        final_team_data.sort(key=lambda x: x["overall"], reverse=True)
        pots = [final_team_data[i*9:(i+1)*9] for i in range(4)]
        pot_names = [[t["name"] for t in p] for p in pots]

        # 3. MAÇ ÇEKİMİ + DAĞITIM (V13 - Deterministik, Tekrar Yok)
        # Her gün 2 torba çifti birbirine karşı oynar: tam 18 maç, SIFIR çakışma.
        # Aynı takım çifti HİÇBİR ZAMAN iki kez eşleşmez.
        # MD1-MD2: Pot0 vs Pot1, Pot2 vs Pot3
        # MD3-MD4: Pot0 vs Pot2, Pot1 vs Pot3
        # MD5-MD6: Pot0 vs Pot3, Pot1 vs Pot2
        # MD7-MD8: Tekrar (farklı offset garantisiyle)
        
        all_teams_list = [t["name"] for t in final_team_data]
        pot_names_fixed = [all_teams_list[i*9:(i+1)*9] for i in range(4)]
        
        import asyncio
        
        def _build_schedule_v13(teams_list, pots):
            import random as rnd
            day_structure = [
                (0, 1, 2, 3), (0, 1, 2, 3), 
                (0, 2, 1, 3), (0, 2, 1, 3), 
                (0, 3, 1, 2), (0, 3, 1, 2), 
                (0, 1, 2, 3), (0, 2, 1, 3)
            ]
            shuffled_pots = {}
            for pi in range(4):
                shuffled_pots[pi] = pots[pi][:]
                rnd.shuffle(shuffled_pots[pi])
            
            pair_usage = {}
            md_fixtures = {}
            for day_idx, (pa, pb, pc, pd) in enumerate(day_structure):
                r = day_idx + 1
                matches = []
                for p1, p2 in [(pa, pb), (pc, pd)]:
                    k = tuple(sorted([p1, p2]))
                    usage = pair_usage.get(k, 0)
                    pair_usage[k] = usage + 1
                    pot1, pot2 = shuffled_pots[p1], shuffled_pots[p2]
                    for i in range(9):
                        j = (i + usage) % 9
                        if (p1 < p2 and usage % 2 == 0) or (p1 > p2 and usage % 2 == 1):
                            matches.append({"home": pot1[i], "away": pot2[j]})
                        else:
                            matches.append({"home": pot2[j], "away": pot1[i]})
                md_fixtures[r] = matches

            # Katı Doğrulama
            for r, mlist in md_fixtures.items():
                day_seen = set()
                for m in mlist:
                    if m["home"] in day_seen or m["away"] in day_seen: return None
                    day_seen.add(m["home"])
                    day_seen.add(m["away"])
            return md_fixtures

        result = None
        for _ in range(100):
            result = _build_schedule_v13(all_teams_list, pot_names_fixed)
            if result: break
        
        if result is None:
            return await ctx.send("Kura Hatasi: Matematiksel cozum bulunamadi. Lutfen tekrar deneyin.")
        
        md_fixtures = result
        final_success = True






        
        # 4. Veritabanı Kayıt (Agresif Temizlik ve 8 Haftalık Doğrulama)
        t_id = await database.create_tournament(t_name)
        async with aiosqlite.connect(database.DB_PATH) as db:
            # Mevcut turnuva fikstürlerini kökten temizle (Eski kuralardan iz kalmasın)
            await db.execute("DELETE FROM tournament_fixtures WHERE tournament_id = ?", (t_id,))
            
            # Dağıtımı kontrol et: Her takımın 8 maçı var mı?
            final_fixtures = []
            for md, fx_list in md_fixtures.items():
                r_name = f"Lig Aşaması - MD{md}"
                for fx in fx_list:
                    final_fixtures.append((t_id, r_name, fx["home"], fx["away"]))
            
            # Veritabanına toplu ekleme
            await db.executemany(
                "INSERT INTO tournament_fixtures (tournament_id, round, home_team, away_team, leg) VALUES (?, ?, ?, ?, 1)",
                final_fixtures
            )
            await db.commit()

        # Doğrulama Mesajı
        total_generated = len(final_fixtures)
        print(f"DEBUG: {t_name} için toplam {total_generated} maç veritabanına kaydedildi.")

        # Sonuç Embed
        embed = discord.Embed(title=f"🏆 {t_name} Lig Aşaması Kurası", color=0x3498db)
        embed.description = "36 takım 4 torbaya ayrıldı. Her takım 8 maçlık fikstürünü aldı."
        
        for i, p in enumerate(pots, 1):
            p_text = ", ".join([t["name"] for t in p])
            embed.add_field(name=f"Torba {i}", value=f"```{p_text}```", inline=False)
        
        await ctx.send(embed=embed)
        await ctx.send(f"✅ Fikstürler oluşturuldu! Maçları görmek için:\n👉 Bir takımın fikstürü: `!ucl_fikstur Galatasaray`\n👉 Tüm haftanın programı: `!ucl_hafta_fikstur 1` (Matchday 1 için)")

    @commands.command(name="lig_asamasi_tablo", aliases=["ucl_tablo", "uel_tablo", "uecl_tablo", "lig_tablosu"])
    async def lig_asamasi_tablo_command(self, ctx, tournament_name: str = None):
        """36 takımlı UEFA Lig Aşaması puan durumunu gösterir."""
        # Akıllı Argüman: Alias kullanıldıysa ismi otomatik çek
        invoked = ctx.invoked_with.lower()
        if not tournament_name:
            if "ucl" in invoked: tournament_name = "UCL"
            elif "uel" in invoked: tournament_name = "UEL"
            elif "uecl" in invoked: tournament_name = "UECL"
            else:
                return await ctx.send("❓ Hangi turnuvanın tablosuna bakmak istiyorsun? Örn: `!ucl_tablo` veya `!uel_tablo`")
        
        t_name = tournament_name.upper()
        t_id = await database.get_tournament_by_name(t_name)
        if not t_id:
            return await ctx.send(f"❌ **{t_name}** turnuvası bulunamadı.")

        standings = await database.get_tournament_league_standings(t_id)
        if not standings:
            return await ctx.send("📅 Henüz lig aşaması maçları oynanmamış veya fikstür yok.")

        # Sayfalı embed veya mega tablo (Discord limitleri nedeniyle 36 takımı bölerek gösterelim)
        # İlk 18 takım ve ikinci 18 takım
        embeds = []
        for i in range(0, 36, 12): # 12'şerli 3 parça
            chunk = standings[i:i+12]
            if not chunk: break
            
            embed = discord.Embed(
                title=f"📊 {t_name} Lig Aşaması - Puan Durumu ({i+1}-{i+len(chunk)})", 
                color=0x2ecc71 if i == 0 else (0xe67e22 if i == 12 else 0x95a5a6)
            )
            
            table_lines = ["` #  Takım             O  G  B  M  AV  P`"]
            for idx, s in enumerate(chunk, start=i+1):
                name = (s["team"][:15]).ljust(15)
                line = f"`{idx:2}. {name} {s['mp']:2} {s['w']:2} {s['d']:2} {s['l']:2} {s['gd']:3} {s['pts']:2}`"
                table_lines.append(line)
            
            embed.description = "\n".join(table_lines)
            if i == 0:
                embed.set_footer(text="İlk 8 direkt Son 16'ya yükselir. 9-24 Play-off oynar.")
            embeds.append(embed)

        for e in embeds:
            await ctx.send(embed=e)

    @commands.command(name="lig_fikstur", aliases=["uefa_fikstur", "md_fikstur", "ucl_fikstur", "uel_fikstur", "uecl_fikstur"])
    async def lig_fikstur_command(self, ctx, team_name: str = None):
        """36 takımlı lig aşamasında bir takımın 8 haftalık fikstürünü gösterir."""
        if not team_name:
            return await ctx.send("❓ Hangi takımın fikstürüne bakmak istiyorsun? Örn: `!ucl_fikstur Galatasaray`")

        # Turnuvaları tara (UCL, UEL, UECL)
        fixtures = []
        found_tournament = ""
        
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            # Takımın ismini normalize et veya DB'den tam halini bul
            target_team = team_name
            async with db.execute("SELECT name FROM teams WHERE name LIKE ? OR LOWER(name) = LOWER(?)", (f"%{team_name}%", team_name)) as cursor:
                t_row = await cursor.fetchone()
                if t_row: target_team = t_row["name"]

            async with db.execute("""
                SELECT tf.*, t.name as t_name
                FROM tournament_fixtures tf
                JOIN tournaments t ON t.id = tf.tournament_id
                WHERE (LOWER(tf.home_team) = LOWER(?) OR LOWER(tf.away_team) = LOWER(?))
                  AND tf.round LIKE 'Lig Aşaması - MD%'
                ORDER BY tf.round ASC
            """, (target_team, target_team)) as cursor:
                rows = await cursor.fetchall()
                fixtures = [dict(r) for r in rows]
                if fixtures: found_tournament = fixtures[0]["t_name"]

        if not fixtures:
            return await ctx.send(f"📅 **{target_team}** için Avrupa'da (UCL/UEL/UECL) bir lig fikstürü bulunamadı.")

        embed = discord.Embed(
            title=f"📅 {found_tournament} Fikstürü: {target_team}",
            description=f"{target_team} takımının Avrupa yolculuğu! (Matchday 1-8)\n━━━━━━━━━━━━━━━━━━━━",
            color=0x1abc9c
        )
        
        match_list = ""
        for f in fixtures:
            # MD numarasını 'Lig Aşaması - MDx' içinden çek
            md_label = f["round"].split("-")[-1].strip()
            status_icon = "🏟️"
            score_text = "vs"
            if f["status"] == "Played":
                status_icon = "✅"
                score_text = f"**{f['home_score']} - {f['away_score']}**"
            
            opp = f["away_team"] if f["home_team"] == target_team else f["home_team"]
            venue = "🏠 (E)" if f["home_team"] == target_team else "🚌 (D)"
            
            match_list += f"{status_icon} **{md_label}:** {venue} {target_team} {score_text} {opp}\n"

        embed.add_field(name="🏟️ KARŞILAŞMALAR", value=match_list, inline=False)
        embed.set_footer(text="Lig aşamasında ilk 8 direkt üst tura çıkar.")
        await ctx.send(embed=embed)

    @commands.command(name="lig_asamasi_fiksturler", aliases=["md_tum_fiksturler", "ucl_hafta_fikstur", "uel_hafta_fikstur", "uecl_hafta_fikstur"])
    async def lig_asamasi_fiksturler_command(self, ctx, *args):
        """36 takımlı lig aşamasında bir haftadaki (Matchday) tüm maçları gösterir."""
        # Akıllı Argüman Yönetimi: Alias kullanıldıysa turnuva adını otomatik çek
        invoked = ctx.invoked_with.lower()
        t_name = None
        matchday = None

        if "ucl" in invoked: t_name = "UCL"
        elif "uel" in invoked: t_name = "UEL"
        elif "uecl" in invoked: t_name = "UECL"

        if t_name:
            # Örn: !ucl_hafta_fikstur 1 -> t_name="UCL", matchday=1
            if args:
                try: matchday = int(args[0])
                except: pass
        else:
            # Örn: !lig_asamasi_fiksturler UCL 1
            if len(args) >= 1: t_name = args[0].upper()
            if len(args) >= 2:
                try: matchday = int(args[1])
                except: pass

        if not t_name or not matchday:
            return await ctx.send("❌ Eksik bilgi! Kullanım: `!ucl_hafta_fikstur 1` veya `!lig_asamasi_fiksturler UCL 1` şeklinde olmalı.")

        t_id = await database.get_tournament_by_name(t_name)
        if not t_id:
            return await ctx.send(f"❌ **{t_name}** turnuvası bulunamadı.")

        rn = f"Lig Aşaması - MD{matchday}"
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM tournament_fixtures 
                WHERE tournament_id = ? AND round = ?
                ORDER BY home_team ASC
            """, (t_id, rn)) as cursor:
                fixtures = [dict(r) for r in await cursor.fetchall()]

        if not fixtures:
            return await ctx.send(f"📅 **{t_name} - {rn}** için fikstür bulunamadı.")

        embed = discord.Embed(
            title=f"📅 {t_name} - {rn} Tüm Maçlar",
            color=0x3498db
        )
        
        match_list = ""
        for f in fixtures:
            status_icon = "🏟️"
            score_text = "vs"
            if f["status"] == "Played":
                status_icon = "✅"
                score_text = f"**{f['home_score']} - {f['away_score']}**"
            
            match_list += f"{status_icon} {f['home_team']} {score_text} {f['away_team']}\n"

        # Split into multiple fields if too long
        if len(match_list) > 1024:
            self._add_split_fields(embed, "🏟️ MAÇLAR", match_list)
        else:
            embed.description = match_list
            
        await ctx.send(embed=embed)

    def _get_smart_ovr(self, team_name: str) -> int:
        """AI kullanmadan, takım ismine göre tahmini bir OVR döner (0 API Maliyeti)."""
        tn = team_name.lower()
        if any(x in tn for x in ["beta", "test"]): return 50
        
        # 0 as fallback to trigger the "Squad Not Found" error
        return 0

    @commands.command(name="lig_md_oyna", aliases=["ucl_md", "uel_md", "uecl_md", "lig_hafta"])
    @commands.has_permissions(administrator=True)
    async def lig_md_oyna_command(self, ctx, *args):
        """
        MD'deki tüm TD'siz maçları API tasarruflu hızlı sim ile oynatır.
        """
        import asyncio, random, math
        
        # Akıllı Argüman Yönetimi: Alias kullanıldıysa turnuva adını otomatik çek
        invoked = ctx.invoked_with.lower()
        t_name = None
        matchday = None

        if "ucl" in invoked: t_name = "UCL"
        elif "uel" in invoked: t_name = "UEL"
        elif "uecl" in invoked: t_name = "UECL"

        if t_name:
            # Örn: !ucl_md 1 -> tournament_name="UCL", matchday=1
            if args:
                try: matchday = int(args[0])
                except: pass
        else:
            # Örn: !lig_md_oyna UECL 1
            if len(args) >= 1: t_name = args[0].upper()
            if len(args) >= 2:
                try: matchday = int(args[1])
                except: pass

        if not t_name:
            return await ctx.send("❌ Turnuva adı belirtilmeli. Örn: `!lig_md_oyna UECL 1` veya direkt `!uecl_md 1`")

        t_id = await database.get_tournament_by_name(t_name)
        if not t_id:
            return await ctx.send(f"❌ **{t_name}** turnuvası bulunamadı.")

        all_fx = await database.get_tournament_fixtures(t_id)

        # Matchday belirtilmemişse beklemede olan ilk MD'yi bul
        if matchday is None:
            for i in range(1, 9):
                rn_check = f"Lig Aşaması - MD{i}"
                if any(f.get("round") == rn_check and f.get("status") == "Pending" for f in all_fx):
                    matchday = i
                    break
        
        if matchday is None:
            return await ctx.send(f"✅ **{t_name}** turnuvasında oynanacak beklemede olan 'Lig Aşaması' maçı kalmamış.")

        if not (1 <= matchday <= 8):
            return await ctx.send("❌ Matchday 1-8 arasında olmalı. Örn: `!ucl_md 1`")

        rn = f"Lig Aşaması - MD{matchday}"
        all_fx = await database.get_tournament_fixtures(t_id)
        md_fx = [f for f in all_fx if f.get("round") == rn]

        if not md_fx:
            return await ctx.send(f"❌ **{rn}** için fikstür bulunamadı.")

        pending = [f for f in md_fx if f.get("status") == "Pending"]
        if not pending:
            return await ctx.send(f"✅ **{rn}** zaten tamamen oynanmış.")

        # TD'li ve TD'siz maçları ayır
        team_names = list({t for f in pending for t in [f["home_team"], f["away_team"]]})
        coach_map = await database.get_team_coach_map(team_names)

        td_matches  = [f for f in pending if coach_map.get(f["home_team"]) or coach_map.get(f["away_team"])]
        auto_matches = [f for f in pending if not coach_map.get(f["home_team"]) and not coach_map.get(f["away_team"])]

        if td_matches:
            td_list = "\n".join([f"⚽ **{f['home_team']} vs {f['away_team']}** — sen oynarsın" for f in td_matches])
            await ctx.send(f"⏳ **{rn}** — TD'li maçlar (sen oynarsın):\n{td_list}")

        if not auto_matches:
            return await ctx.send("ℹ️ Bu MD'de otomatik oynatılacak maç yok (hepsinde TD var).")

        await ctx.send(f"⚡ **{rn}** — {len(auto_matches)} maç hızlı sim ile oynatılıyor... (0 API çağrısı)")

        # === HIZLI SIM (API Çağrısız) ===
        def fast_sim(ovr_home: int, ovr_away: int) -> tuple:
            """OVR farkına dayalı istatistiksel skor üreteci."""
            diff = (ovr_home + 2) - ovr_away  # +2 ev avantajı
            home_str = max(0.3, min(2.5, 1.0 + diff * 0.03))
            away_str = max(0.3, min(2.5, 1.0 - diff * 0.03))

            # Poisson benzeri gol dağılımı
            def rand_goals(strength):
                r = random.random()
                probs = []
                cumulative = 0
                lam = strength
                for g in range(8):
                    p = (math.exp(-lam) * lam**g) / math.factorial(g)
                    cumulative += p
                    probs.append(cumulative)
                    if r <= cumulative:
                        return g
                return 0
            return rand_goals(home_str), rand_goals(away_str)

        # Takım OVR'larını toplu çek
        all_team_ovrs = {}
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            for f in auto_matches:
                for tname in [f["home_team"], f["away_team"]]:
                    if tname not in all_team_ovrs:
                        async with db.execute("SELECT overall FROM teams WHERE LOWER(name) = LOWER(?)", (tname,)) as cur:
                            row = await cur.fetchone()
                            # Akıllı Fallback: DB'de yoksa veya 0 ise tahmini OVR kullan
                            db_ovr = row["overall"] if (row and row["overall"]) else 0
                            all_team_ovrs[tname] = db_ovr if db_ovr > 0 else self._get_smart_ovr(tname)

        # Maçları sim et ve DB'ye kaydet
        results = []
        played_in_this_md = set()
        async with aiosqlite.connect(database.DB_PATH) as db:
            for f in auto_matches:
                h_name, a_name = f["home_team"], f["away_team"]
                
                # ÇİFT MAÇ ÖNLEME (Garantör)
                if h_name in played_in_this_md or a_name in played_in_this_md:
                    print(f"DEBUG: {h_name} veya {a_name} bu matchday de zaten oynadı. Atlanıyor.")
                    continue

                ovr_h = all_team_ovrs.get(h_name) or self._get_smart_ovr(h_name)
                ovr_a = all_team_ovrs.get(a_name) or self._get_smart_ovr(a_name)
                h_score, a_score = fast_sim(ovr_h, ovr_a)

                await db.execute(
                    "UPDATE tournament_fixtures SET home_score=?, away_score=?, status='Played' WHERE id=?",
                    (h_score, a_score, f["id"])
                )
                results.append((h_name, a_name, h_score, a_score))
                played_in_this_md.add(h_name)
                played_in_this_md.add(a_name)
            await db.commit()

        # Sonuç embed
        embed = discord.Embed(
            title=f"⚡ {t_name} — {rn} Sonuçları",
            color=0x2ecc71
        )
        result_lines = []
        for h, a, hs, as_ in results:
            if hs > as_:
                line = f"🟢 **{h} {hs}-{as_} {a}**"
            elif hs < as_:
                line = f"🔴 {h} {hs}-{as_} **{a}**"
            else:
                line = f"🟡 {h} {hs}-{as_} {a}"
            result_lines.append(line)

        embed.description = "\n".join(result_lines)
        embed.set_footer(text=f"📊 Güncel tablo: !lig_asamasi_tablo {t_name}")
        await ctx.send(embed=embed)


    # ---------------- TOURNAMENT PROGRESSION (SMART UNIFIED) ----------------

    @commands.command(name="turnuva_ilerle", aliases=["ilerle", "atla", "next", "tur_atla", "lig_ilerle", "lig_r16", "kupa_atla", "ucl_ilerle", "uel_ilerle", "uecl_ilerle"])
    @commands.has_permissions(administrator=True)
    async def turnuva_ilerle_command(self, ctx, tournament_name: str):
        """Turnuvada bir sonraki aşamaya akıllıca geçer."""
        t_name = tournament_name.upper()
        t_id = await database.get_tournament_by_name(t_name)
        if not t_id:
            return await ctx.send(f"❌ **{t_name}** turnuvası bulunamadı.")

        # 1. Mevcut en son turu bul
        async with database.get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT DISTINCT round FROM tournament_fixtures 
                WHERE tournament_id = ? ORDER BY id DESC LIMIT 1
            """, (t_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return await ctx.send("📅 Turnuvada henüz hiç maç/fikstür yok.")
                current_round = row["round"]

        # 2. Mantıksal Yönlendirme
        if "Lig Aşaması" in current_round:
            await self._logic_league_to_playoff(ctx, t_id, t_name)
        elif current_round == "Playoff":
            await self._logic_playoff_to_r16(ctx, t_id, t_name)
        else:
            await self._logic_knockout_progression(ctx, t_id, t_name, current_round)

    async def _logic_league_to_playoff(self, ctx, t_id, t_name):
        """Lig aşamasından Playoff'a geçiş mantığı."""
        fixtures = await database.get_tournament_fixtures(t_id)
        lig_fx = [f for f in fixtures if "Lig Aşaması" in f["round"]]
        pending = [f for f in lig_fx if f["status"] == "Pending"]
        
        if pending:
            return await ctx.send(f"⚠️ Lig aşamasında hala **{len(pending)}** oynanmamış maç var!")

        standings = await database.get_tournament_league_standings(t_id)
        if len(standings) < 24:
            return await ctx.send(f"❌ Sıralama için yetersiz takım ({len(standings)}).")

        top8 = [s["team"] for s in standings[:8]]
        playoff_teams = [s["team"] for s in standings[8:24]]

        playoff_fixtures = []
        for i in range(8):
            home, away = playoff_teams[i], playoff_teams[15 - i]
            playoff_fixtures.append((home, away))

        async with database.get_db() as db:
            await db.execute("DELETE FROM tournament_fixtures WHERE tournament_id = ? AND round = 'Playoff'", (t_id,))
            for home, away in playoff_fixtures:
                await db.execute("INSERT INTO tournament_fixtures (tournament_id, round, home_team, away_team, leg) VALUES (?, 'Playoff', ?, ?, 1)", (t_id, away, home))
                await db.execute("INSERT INTO tournament_fixtures (tournament_id, round, home_team, away_team, leg) VALUES (?, 'Playoff', ?, ?, 2)", (t_id, home, away))
            await db.commit()

        embed = discord.Embed(title=f"🏆 {t_name} — Lig Aşaması Tamamlandı!", color=0xf39c12)
        embed.add_field(name="✅ Direkt Son 16 (1-8.)", value=", ".join(top8), inline=False)
        embed.add_field(name="⚔️ Playoff Turu (9-24.)", value="8 eşleşme (çift maç) oluşturuldu.", inline=False)
        await ctx.send(embed=embed)

    async def _logic_playoff_to_r16(self, ctx, t_id, t_name):
        """Playofflardan Son 16'ya geçiş (Otomatik simülasyon destekli)."""
        async with database.get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tournament_fixtures WHERE tournament_id = ? AND round = 'Playoff' AND status = 'Pending'", (t_id,)) as cur:
                pending = await cur.fetchall()
            
            if pending:
                await ctx.send(f"⚡ Playoff turunda bekleyen **{len(pending)}** maç hızlı simülasyonla tamamlanıyor...")
                import random, math
                
                team_names = list({t for f in pending for t in [f["home_team"], f["away_team"]]})
                all_ovrs = {}
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

        standings = await database.get_tournament_league_standings(t_id)
        top8 = [s["team"] for s in standings[:8]]
        
        fixtures = await database.get_tournament_fixtures(t_id, "Playoff")
        processed, winners = set(), []
        for f in fixtures:
            tk = tuple(sorted([f["home_team"], f["away_team"]]))
            if tk in processed: continue
            agg = await database.get_aggregate_score(t_id, "Playoff", f["home_team"], f["away_team"])
            winners.append(f["home_team"] if agg[f["home_team"]] > agg[f["away_team"]] else f["away_team"])
            processed.add(tk)

        all_teams = top8 + winners
        import random
        random.shuffle(all_teams)
        
        async with database.get_db() as db:
            await db.execute("DELETE FROM tournament_fixtures WHERE tournament_id = ? AND round = 'Son 16'", (t_id,))
            await db.commit()
            
        await database.create_tournament_fixtures(t_id, "Son 16", all_teams, legs=2)
        await ctx.send(f"🏆 {t_name} — Son 16 eşleşmeleri oluşturuldu! (Top 8 + Playoff Galipleri)")

    async def _logic_knockout_progression(self, ctx, t_id, t_name, current_round):
        """Standard eleme turu atlatma (R16 -> QF -> SF -> F)."""
        fixtures = await database.get_tournament_fixtures(t_id, current_round)
        
        # Oynanmamış maçları otomatik simüle et (Hızlı Sim)
        pending = [f for f in fixtures if f["status"] == "Pending"]
        if pending:
            sim_list = []
            for f in pending:
                sim_list.append(f"• {f['home_team']} vs {f['away_team']} (Leg {f['leg']})")
            
            await ctx.send(f"⚠️ **{current_round}** turunda oynanmamış **{len(pending)}** maç tespit edildi. Otomatik simüle ediliyor...\n" + "\n".join(sim_list))
            
            async with database.get_db() as db:
                db.row_factory = aiosqlite.Row
                import random, math
                
                team_names = list({t for f in pending for t in [f["home_team"], f["away_team"]]})
                all_ovrs = {}
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
            
            # Fikstürleri yeniden çek
            fixtures = await database.get_tournament_fixtures(t_id, current_round)

        processed, winners = set(), []
        penalty_notices = []
        
        for f in fixtures:
            tk = tuple(sorted([f["home_team"], f["away_team"]]))
            if tk in processed: continue
            
            agg = await database.get_aggregate_score(t_id, current_round, f["home_team"], f["away_team"])
            h_name, a_name = f["home_team"], f["away_team"]
            
            h_total = agg.get(h_name, 0)
            a_total = agg.get(a_name, 0)
            
            if h_total > a_total:
                winner = h_name
            elif a_total > h_total:
                winner = a_name
            else:
                # Toplam skor eşit -> Uzatmalar ve Penaltılar (Simülasyon)
                
                # Sadece Son 16 ve sonrası için detaylı simülasyon (R16=16, QF=8, SF=4, F=2)
                is_major_round = any(x in current_round for x in ["Son 16", "Çeyrek", "Yarı", "Final", "Playoff"])
                
                if is_major_round:
                    all_teams_db = await database.get_all_teams()
                    ovr_dict = {t["name"]: t["overall"] for t in all_teams_db if t["name"] in [h_name, a_name]}
                    ovr_h = ovr_dict.get(h_name, 75)
                    ovr_a = ovr_dict.get(a_name, 75)
                    
                    # 1. Uzatmalar (30 dk)
                    # OVR farkına göre gol ihtimali
                    diff = (ovr_h + 2) - ovr_a 
                    et_h_prob = 0.15 + (diff * 0.01)
                    et_a_prob = 0.15 - (diff * 0.01)
                    
                    et_h_goals = 1 if random.random() < et_h_prob else 0
                    et_a_goals = 1 if random.random() < et_a_prob else 0
                    
                    if et_h_goals != et_a_goals:
                        winner = h_name if et_h_goals > et_a_goals else a_name
                        penalty_notices.append(f"⏰ **{h_name} vs {a_name}** eşleşmesinde toplam skor eşit (**{h_total}-{a_total}**). Uzatmalarda gelen skorla (**{et_h_goals}-{et_a_goals}**) **{winner}** turu geçti!")
                    else:
                        # 2. Penaltılar
                        # OVR farkı penaltılarda daha az etkilidir ama hala vardır
                        weight_h = 50 + (ovr_h - ovr_a) * 0.3
                        
                        # Penaltı skorlarını simüle et (Gerçekçi skorlar: 4-5, 3-1 vb)
                        p_h = random.randint(3, 5)
                        p_a = random.randint(3, 5)
                        if p_h == p_a:
                            # Eşitlik durumunda ani ölüm (sudden death)
                            if random.random() * 100 < weight_h: p_h += 1
                            else: p_a += 1
                        
                        winner = h_name if p_h > p_a else a_name
                        penalty_notices.append(f"🥅 **{h_name} vs {a_name}** eşleşmesinde toplam skor eşit (**{h_total}-{a_total}**). Uzatmalar da berabere bitti! Penaltı atışları sonucu (**{p_h}-{p_a}**) **{winner}** turu geçti!")
                else:
                    # Minor turlar için (varsa) eski mantık
                    winner = h_name if random.random() > 0.5 else a_name
            
            winners.append(winner)
            processed.add(tk)

        if penalty_notices:
            await ctx.send("\n".join(penalty_notices))

        count = len(winners)
        nr = {16: "Son 16", 8: "Çeyrek Final", 4: "Yarı Final", 2: "Final"}.get(count)
        
        if not nr: return await ctx.send(f"❌ Kazanan sayısı ({count}) geçersiz.")

        await database.create_tournament_fixtures(t_id, nr, winners, legs=(1 if nr == "Final" else 2))
        await ctx.send(f"🚀 {t_name} — **{current_round}** bitti, **{nr}** kuraları çekildi!")


    @commands.command(name="kupa_fikstur", aliases=["kupa_tablo", "bracket"])
    async def kupa_fikstur_command(self, ctx, tournament_name: str, *, round_name: str = None):
        """Kupa fikstürünü ve aggregate skorları gösterir."""
        t_id = await database.get_tournament_by_name(tournament_name.upper())
        if not t_id:
            return await ctx.send(f"❌ **{tournament_name}** isimli bir turnuva bulunamadı.")

        fixtures = await database.get_tournament_fixtures(t_id, round_name)
        if not fixtures:
            return await ctx.send("📅 Henüz fikstür oluşturulmamış.")

        rounds = {}
        for f in fixtures:
            r = self._normalize_round_name(f["round"])
            if r not in rounds: rounds[r] = []
            rounds[r].append(f)

        if not round_name and rounds:
            latest_round = self._normalize_round_name(fixtures[-1]["round"])
            rounds = {latest_round: rounds[latest_round]}

        embed = discord.Embed(title=f"🏆 {tournament_name.upper()} - Turnuva Durumu", color=0x3498db)
        round_order = ["Son 16", "Çeyrek Final", "Yarı Final", "Final"]
        sorted_rounds = sorted(rounds.keys(), key=lambda x: round_order.index(x) if x in round_order else 99)

        for r_name in sorted_rounds:
            r_matches = rounds[r_name]
            match_lines = []
            processed_ties = set()
            for f in r_matches:
                tie_key = tuple(sorted([f["home_team"], f["away_team"]]))
                if tie_key in processed_ties: continue
                
                tie_matches = [m for m in r_matches if tuple(sorted([m["home_team"], m["away_team"]])) == tie_key]
                tie_matches.sort(key=lambda x: x["leg"])
                
                leg1 = tie_matches[0]
                leg2 = tie_matches[1] if len(tie_matches) > 1 else None
                status_emoji = "✅" if all(m["status"] == "Played" for m in tie_matches) else "⏳"
                line = f"{status_emoji} **{leg1['home_team']} vs {leg1['away_team']}**"
                if not leg2:
                    line += f"\n   ↳ Skor: {leg1['home_score']}-{leg1['away_score']}"
                else:
                    line += f"\n   ↳ 1. Maç: {leg1['home_score']}-{leg1['away_score']} | 2. Maç: {leg2['home_score']}-{leg2['away_score']}"
                    agg = await database.get_aggregate_score(t_id, f["round"], leg1['home_team'], leg1['away_team'])
                    line += f"\n   ↳ **Toplam: {agg[leg1['home_team']]}-{agg[leg1['away_team']]}**"
                
                match_lines.append(line + "\n")
                processed_ties.add(tie_key)
            self._add_split_fields(embed=embed, name=f"📍 {r_name}", value="\n".join(match_lines) or "Maç yok.", inline=False)
        await ctx.send(embed=embed)



    @commands.command(name="kupa_mac", aliases=["turnuva_mac", "cup_match"])
    @commands.has_permissions(administrator=True)
    async def kupa_mac_command(self, ctx, fixture_id: int):
        """Specific bir kupa maçını simüle eder."""
        fixture = await database.get_tournament_fixture_by_id(fixture_id)
        if not fixture:
            return await ctx.send(f"❌ ID: {fixture_id} numaralı fikstür bulunamadı.")

        if fixture["status"] == "Played":
            return await ctx.send("⚠️ Bu maç zaten oynanmış.")

        # Turnuva ismini al
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT name FROM tournaments WHERE id = ?", (fixture["tournament_id"],)) as cursor:
                row = await cursor.fetchone()
                t_name = row[0] if row else "Cup"

        # Maç komutunu simüle etmek için context'e verileri ekliyoruz
        # MatchCog.mac_command bu verileri kullanarak tournament logic çalıştıracak.
        ctx.is_tournament = True
        ctx.tournament_fixture = fixture
        ctx.competition_name = t_name
        
        # Eğer 2. maç ise aggregate context hazırla
        if fixture["leg"] == 2:
            agg = await database.get_aggregate_score(fixture["tournament_id"], fixture["round"], fixture["home_team"], fixture["away_team"])
            # İlk maç skorunu bulalım (Aggregate içinde var)
            # Ama AI'ya "Bir önceki maç sonucu şuydu" demek için formatlayalım.
            # İlk maçı bul (Ev sahibi 2. maçın deplasmanıydı)
            async with aiosqlite.connect(database.DB_PATH) as db:
                async with db.execute("""
                    SELECT * FROM tournament_fixtures 
                    WHERE tournament_id = ? AND round = ? AND leg = 1 
                    AND home_team = ? AND away_team = ?
                """, (fixture["tournament_id"], fixture["round"], fixture["away_team"], fixture["home_team"])) as cursor:
                    leg1 = await cursor.fetchone()
                    if leg1:
                        ctx.agg_context = {
                            "first_leg_score": f"{leg1['home_score']}-{leg1['away_score']} ({leg1['home_team']} galibiyeti)" if leg1['home_score'] > leg1['away_score'] else (f"{leg1['home_score']}-{leg1['away_score']} (Beraberlik)" if leg1['home_score'] == leg1['away_score'] else f"{leg1['home_score']}-{leg1['away_score']} ({leg1['away_team']} galibiyeti)"),
                            "total_home": agg[fixture["home_team"]],
                            "total_away": agg[fixture["away_team"]]
                        }
        else:
            ctx.agg_context = None

        # mac_command'ı çağır
        match_cog = self.bot.get_cog("MatchCog")
        if not match_cog:
            return await ctx.send("❌ Error: MatchCog not found.")
        
        query = f"{fixture['home_team']} vs {fixture['away_team']} {t_name}"
        await ctx.invoke(match_cog.mac_command, query=query)

    async def _post_to_tournament_channel(self, ctx, tournament_name: str):
        """Automatically finds the correct channel and posts the fixture list."""
        t_upper = tournament_name.upper()
        
        # Channel Name Mapping
        channel_map = {
            "UCL": ["ucl-maçlar", "ucl-maclar", "sampiyonlar-ligi"],
            "UEL": ["avrupa-maçlar", "avrupa-maclar", "uel-maclar"],
            "UECL": ["konferans-maçlar", "konferans-maclar", "uecl-maclar"]
        }
        
        target_names = channel_map.get(t_upper, [])
        if not target_names: return

        # Find channel by name
        target_channel = None
        for channel in ctx.guild.text_channels:
            if any(name in channel.name.lower() for name in target_names):
                target_channel = channel
                break
        
        if not target_channel:
            print(f"DEBUG: [Tournament] Target channel for {t_upper} not found in guild.")
            return

        # Generate the fixture embed (Reuse logic from kupa_fikstur_command but for channel)
        t_id = await database.get_tournament_by_name(t_upper)
        if not t_id: return
        
        fixtures = await database.get_tournament_fixtures(t_id)
        if not fixtures: return
        # Defensive: ensure all rows are plain dicts
        fixtures = [dict(f) if not isinstance(f, dict) else f for f in fixtures]

        rounds = {}
        for f in fixtures:
            r = self._normalize_round_name(f["round"])
            if r not in rounds: rounds[r] = []
            rounds[r].append(f)

        # 1. Turnuvadaki TÜM Türk takımlarını bul
        import config
        turkish_names = [t.lower() for t in config.TURKISH_TEAMS]
        
        participating_turkish_teams = []
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT DISTINCT home_team FROM tournament_fixtures 
                WHERE tournament_id = ? AND LOWER(home_team) IN ({})
            """.format(','.join(['?']*len(turkish_names))), (t_id, *turkish_names)) as cursor:
                rows = await cursor.fetchall()
                participating_turkish_teams = [r["home_team"] for r in rows]

        if not participating_turkish_teams:
            print(f"DEBUG: [Tournament] No Turkish teams participating in {t_upper}.")
            return

        # 2. Her takım için AYRI bir "Yolculuk" embed'i hazırla ve gönder
        for target_team in participating_turkish_teams:
            fixtures = []
            async with aiosqlite.connect(database.DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT * FROM tournament_fixtures
                    WHERE tournament_id = ? 
                      AND (LOWER(home_team) = LOWER(?) OR LOWER(away_team) = LOWER(?))
                      AND round LIKE 'Lig Aşaması - MD%'
                    ORDER BY round ASC
                """, (t_id, target_team, target_team)) as cursor:
                    rows = await cursor.fetchall()
                    fixtures = [dict(r) for r in rows]

            if not fixtures: continue

            embed = discord.Embed(
                title=f"📅 {t_upper} YOLCULUĞU: {target_team}",
                description=f"**{target_team}** temsilcimizin Avrupa serüveni! (Matchday 1-8)\n━━━━━━━━━━━━━━━━━━━━",
                color=0x1abc9c
            )
            
            match_list = ""
            for f in fixtures:
                md_label = f["round"].split("-")[-1].strip()
                status_icon = "🏟️"
                score_text = "vs"
                if f["status"] == "Played":
                    status_icon = "✅"
                    score_text = f"**{f['home_score']} - {f['away_score']}**"
                
                is_home = f["home_team"] == target_team
                opp = f["away_team"] if is_home else f["home_team"]
                venue = "🏠 (E)" if is_home else "🚌 (D)"
                
                # Natural home/away order: if Turkish team is away, opponent is on left
                if is_home:
                    match_list += f"{status_icon} **{md_label}:** {venue} {target_team} {score_text} {opp}\n"
                else:
                    match_list += f"{status_icon} **{md_label}:** {venue} {opp} {score_text} {target_team}\n"

            embed.add_field(name="🏟️ KARŞILAŞMALAR", value=match_list, inline=False)
            embed.set_footer(text=f"Son Güncelleme: {discord.utils.format_dt(discord.utils.utcnow(), 'R')}")
            
            await target_channel.send(embed=embed)
            print(f"DEBUG: [Tournament] Journey for {target_team} posted to #{target_channel.name}")
        
        # Phase 3 (Bracket Summary) was removed per user request to only show individual team journeys.
        pass

    @commands.command(name="kupa_paylas", aliases=["kupa_kanal", "share_fixture"])
    @commands.has_permissions(administrator=True)
    async def kupa_paylas_command(self, ctx, tournament_name: str):
        """Turnuva fikstürünü ilgili Discord kanalına manuel olarak postlar."""
        await self._post_to_tournament_channel(ctx, tournament_name)
        await ctx.send(f"✅ **{tournament_name.upper()}** fikstürü ilgili kanalda paylaşıldı!")

async def setup(bot):
    await bot.add_cog(TournamentCog(bot))
