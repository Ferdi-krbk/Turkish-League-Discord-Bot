"""
Match Simulation Command Cog for Turkish Super League Bot
Uses OpenRouter AI API for realistic match simulation
"""

import discord
from discord.ext import commands
import json
import os
import ast
import aiohttp
import re
import asyncio
import urllib.request
import urllib.parse
import random
from datetime import datetime
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from typing import Dict, List, Optional, Any
from core.media import MediaGenerator
from core import database
import aiosqlite
import config
from core.simulation import MatchSimulator
from core import ai
from core.graphics_engine import MatchGraphics
from core.logo_manager import LogoManager





class MatchCog(commands.Cog):
    """Cog for match simulation commands using OpenRouter AI"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.media_generator = MediaGenerator()
        self.simulator = MatchSimulator()
        self.graphics_engine = MatchGraphics()
        self.logo_manager = LogoManager()
        self.last_match_result = {} # Stores the most recent match for !manset


    def clean_tn(self, name):
        """Standardize team names for comparison with character normalization"""
        s = str(name).lower().strip().replace(" ", "").replace("spor", "").replace("fk", "").replace("as", "")
        translation = str.maketrans("çğıöşü", "cgiosu")
        return s.translate(translation)

    def _get_event_emoji(self, etype: str, index: int = 0) -> str:
        """Returns a relevant emoji for the event type with variety for generic events"""
        mapping = {
            "goal": "⚽", "penalty": "🎯", "penalty_missed": "❌", "penalty_saved": "🧤",
            "chance": "⚠️", "shot_on_target": "🥅", "hit_woodwork": "🎯",
            "yellow_card": "🟨", "red_card": "🟥", "var_check": "📺",
            "substitution": "🔄", "great_save": "🧤", "foul": "🦶", "block": "🛡️", "injury": "🚑",
            "offside": "🚩", "corner": "🚩", "tactic": "📋", "pressure": "🔥", "save": "🧤",
            "shot": "⚽", "header": "⚽", "cross": "👟", "tackle": "🦶", "interference": "✋",
            "atmosphere": "📣", "choreography": "🏳️", "manager_dispute": "🤬", "referee_talk": "🗣️", "fan_reaction": "🥁"
        }
        
        if etype in mapping:
            return mapping[etype]
            
        # Variety for unknown types
        variety = ["🔹", "🔸", "💠", "✨", "⚡", "📢", "🔥", "💨", "💢", "💥", "💎", "🔋", "🔘"]
        return variety[index % len(variety)]

    def _add_split_fields(self, embed, name, value, inline=False):
        """Splits values > 1024 chars into multiple fields to avoid Discord API errors"""
        if not value:
            return
        
        value = str(value)
        if len(value) <= 1024:
            embed.add_field(name=name, value=value, inline=inline)
            return

        # Split into chunks of ~1000 characters
        chunks = []
        while len(value) > 1000:
            # Try to split at a newline or space
            split_idx = value.rfind('\n', 0, 1000)
            if split_idx == -1:
                split_idx = value.rfind(' ', 0, 1000)
            if split_idx == -1:
                split_idx = 1000
            
            chunks.append(value[:split_idx].strip())
            value = value[split_idx:].strip()
        
        if value:
            chunks.append(value)

        for i, chunk in enumerate(chunks):
            field_name = name if i == 0 else f"{name} (Devam {i})"
            embed.add_field(name=field_name, value=chunk, inline=inline)

    @commands.command(name="cache_temizle", aliases=["bellek_temizle", "scout_temizle"])
    @commands.has_permissions(administrator=True)
    async def cache_temizle_command(self, ctx: commands.Context, *, team_name: str = None):
        """AI Scout önbelleğini temizler. Bir takım adı girilirse sadece o takımı, girilmezse tüm cache'i temizler."""
        if team_name:
            key = f"ext_squad_v2_{self._clean_name(team_name)}"
            await database.delete_scout_cache(key)
            await ctx.send(f"✅ **{team_name}** için AI önbelleği temizlendi. Bir sonraki maçta taze araştırma yapılacak.")
        else:
            await database.clear_all_scout_cache()
            await ctx.send("🧹 **Tüm AI Scout önbelleği temizlendi.**")

    def _clean_name(self, name):
        return name.lower().replace("ı", "i").replace("ç", "c").replace("ş", "s").replace("ğ", "g").replace("ü", "u").replace("ö", "o").strip()

    async def _find_team(self, name: str) -> Optional[Dict]:
        """Find team by name (database search with smart match)"""
        return await database.search_team(name)

    async def _find_fixture(self, team_a: str, team_b: str) -> Optional[Dict]:
        """Check if there is a pending fixture between these two teams with robust normalization and smart matching"""
        from core import database
        import aiosqlite

        # Normalize inputs
        norm_a = self.clean_tn(team_a)
        norm_b = self.clean_tn(team_b)

        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            # Tüm bekleyen fikstürleri en yakın haftadan başlayarak çekelim
            async with db.execute("SELECT * FROM fixtures WHERE status = 'Pending' ORDER BY round_no ASC") as cursor:
                rows = await cursor.fetchall()
                
                for row in rows:
                    fixture_h = self.clean_tn(row["home_team"])
                    fixture_a = self.clean_tn(row["away_team"])
                    
                    # Akıllı eşleşme (Shorthand destekli: 'fener' in 'fenerbahce')
                    match_h_a = (norm_a in fixture_h or fixture_h in norm_a)
                    match_a_b = (norm_b in fixture_a or fixture_a in norm_b)
                    
                    match_h_b = (norm_a in fixture_a or fixture_a in norm_a)
                    match_a_a = (norm_b in fixture_h or fixture_h in norm_b)
                    
                    if (match_h_a and match_a_b) or (match_h_b and match_a_a):
                        return dict(row)
        return None
        return None

    @commands.command(name="veriguncelle", aliases=["sync", "dataload"])
    @commands.has_permissions(administrator=True)
    async def veriguncelle_command(self, ctx: commands.Context):
        """JSON dosyasındaki güncel reyting ve takım verilerini veri tabanına işler."""
        wait_msg = await ctx.send("⌛ **Veri tabanı JSON ile senkronize ediliyor...**")
        try:
            await database.load_teams_from_json()
            await database.load_players_from_json()
            await wait_msg.edit(content="✅ **Senkronizasyon Başarılı!**\nJSON'daki tüm reyting ve kadro değişiklikleri veri tabanına ve maç motoruna işlendi.")
        except Exception as e:
            try:
                await wait_msg.edit(content=f"❌ **Senkronizasyon Hatası!**\n{e}")
            except: pass

    @commands.command(name="reyting_ayarla", aliases=["setrating", "reytingguncelle"])
    @commands.has_permissions(administrator=True)
    async def set_rating_command(self, ctx: commands.Context, team_name: str, new_rating: float):
        """Bir takımın baz reytingini (overall) hem DB hem JSON'da günceller."""
        team_data = await self._find_team(team_name)
        if not team_data:
            await ctx.send(f"❌ **{team_name}** isimli bir takım bulunamadı.")
            return

        old_rating = team_data.get('overall', 0)
        try:
            await database.update_team_overall(team_data['name'], new_rating)
            await ctx.send(
                f"✅ **Reyting Güncellendi!**\n"
                f"🏟️ **Takım:** {team_data['name']}\n"
                f"📈 **Eski Reyting:** {old_rating}\n"
                f"🔥 **Yeni Reyting:** {new_rating}\n\n"
                f"_Not: Veriler hem veri tabanına hem de teams.json dosyasına kalıcı olarak işlendi._"
            )
        except Exception as e:
            await ctx.send(f"❌ **Hata Oluştu:** {e}")

    @commands.command(name="reyting_hesapla", aliases=["reyting_guncelle", "otoreyting"])
    @commands.has_permissions(administrator=True)
    async def reyting_hesapla_command(self, ctx: commands.Context, *, team_name: str):
        """Bir takımın piyasa değerlerini (PD) senkronize eder ve oyuncu reytinglerini (Top 18) günceller."""
        team = await self._find_team(team_name)
        if not team:
            return await ctx.send(f"❌ **{team_name}** bulunamadı.")
            
        t_name = team['name']
        
        # 0. AKILLI SENKRONİZASYON (Market Value Sync from TXT)
        sync_msg = ""
        transfer_cog = self.bot.get_cog('TransferCog')
        if transfer_cog:
            updated, skipped = await transfer_cog._sync_pd_from_txt(t_name)
            if updated != -1:
                sync_msg = f"🔄 **PD Senkronizasyonu:** `{updated}` oyuncu güncellendi, `{skipped}` atlandı.\n"
            else:
                sync_msg = "⚠️ **Not:** Taktik dosyası bulunamadı, senkronizasyon atlandı.\n"

        old_val = team.get('overall', 0)
        new_val = await database.calculate_team_overall(t_name)
        
        await ctx.send(f"✅ **{t_name}** Reyting Analizi Tamamlandı!\n{sync_msg}📉 **Eski:** {old_val}\n📈 **Yeni:** {new_val}\n💡 _Not: En iyi 11 ve yedek ağırlıklı hibrit sistem baz alındı._")

    @commands.command(name="reyting_hesapla_hepsi", aliases=["reyting_guncelle_hepsi"])
    @commands.has_permissions(administrator=True)
    async def reyting_hesapla_hepsi_command(self, ctx: commands.Context):
        """Tüm lig takımlarının PD'lerini senkronize eder ve reytinglerini oyuncu kadrolarına göre günceller."""
        msg = await ctx.send("⌛ **Tüm lig için Akıllı Reyting Senkronizasyonu başlatılıyor...**")
        teams = await database.get_all_teams("Super Lig") # Only for Super Lig teams
        if not teams:
            return await msg.edit(content="❌ **Hata:** Lig takımları bulunamadı.")
            
        transfer_cog = self.bot.get_cog('TransferCog')
        count = 0
        for team in teams:
            t_name = team['name']
            # Loop içinde PD senk
            if transfer_cog:
                await transfer_cog._sync_pd_from_txt(t_name)
            
            await database.calculate_team_overall(t_name)
            count += 1
            
        await msg.edit(content=f"✅ **İşlem Tamamlandı!**\n🏟️ **{count}** takımın piyasa değerleri ve genel reytingleri (Hibrit Sistem) oyuncu kadrolarına göre senkronize edildi.")

    @commands.command(name="evrensel_senkronize", aliases=["universal_sync", "all_sync"])
    @commands.has_permissions(administrator=True)
    async def evrensel_senkronize_command(self, ctx: commands.Context):
        """TÜM veritabanını (Lig, Avrupa, Kupalar) yeni bareme göre senkronize eder."""
        msg = await ctx.send("🌐 **Evrensel Senkronizasyon Başlatılıyor...**\n_Tüm veritabanı (Oyuncular ve Takımlar) yeni bareme göre hizalanıyor._")
        
        # 1. Tüm takımları çek
        teams = await database.get_all_teams()
        if not teams:
            return await msg.edit(content="❌ Veritabanında takım bulunamadı.")
            
        results = {} # {league: [team_names]}
        total_count = 0
        
        for team in teams:
            t_name = team['name']
            t_league = team.get('league', 'Diğer')
            
            # Reyting hesapla (Otomatik oyuncu refresh dahildir)
            await database.calculate_team_overall(t_name)
            
            if t_league not in results:
                results[t_league] = []
            results[t_league].append(t_name)
            total_count += 1
            
        # 2. Rapor Hazırla
        report = f"✅ **Evrensel Senkronizasyon Tamamlandı!**\n📊 **Toplam İşlenen Takım:** `{total_count}`\n\n"
        
        for league, t_list in results.items():
            team_str = ", ".join([f"`{name}`" for name in t_list[:15]]) # İlk 15'i göster
            if len(t_list) > 15:
                team_str += f" ve {len(t_list)-15} daha..."
            report += f"📍 **{league}:** {team_str}\n"
            
        report += "\n💡 _Tüm oyuncu reytingleri piyasa değerlerine göre güncellendi ve takımlara yansıtıldı._"
        
        # Karakter limiti kontrolü
        if len(report) > 2000:
            # Parçalı gönder
            await msg.edit(content="✅ **İşlem Tamamlandı!** (Rapor uzunluğu nedeniyle parça parça gönderiliyor)")
            for i in range(0, len(report), 1900):
                await ctx.send(report[i:i+1900])
        else:
            await msg.edit(content=report)

    @commands.command(name="takimsec", aliases=["yonet", "takim_sec", "choose_team"])
    async def takimsec_command(self, ctx: commands.Context, team_name: str, role: str = "başkan"):
        """Yöneteceğiniz takımı ve rolünüzü (başkan/td) seçmenizi sağlar."""
        team_data = await self._find_team(team_name)
        if not team_data:
            return await ctx.send(f"❌ **{team_name}** isminde bir takım bulunamadı.")
        
        # Validasyon
        role = role.lower()
        if role not in ["başkan", "td"]:
            return await ctx.send("❌ **Geçersiz Rol!** Lütfen `başkan` veya `td` rollerinden birini seçin.")

        success = await database.set_team_role(team_data['name'], ctx.author.id, role)
        if success:
            role_display = "KULÜP BAŞKANI" if role == "başkan" else "TEKNİK DİREKTÖR"
            ui = [
                f"✅ **YÖNETİM GÖREVİ BAŞLADI!**",
                f"🏟️ **Takım:** {team_data['name']}",
                f"👤 **Yönetici:** {ctx.author.display_name}",
                f"🎭 **Rol:** {role_display}",
                f"💰 **Takım Bütçesi:** {team_data.get('budget', 0):,} €",
                f"🚀 Artık takımını yönetebilirsin!"
            ]
            await ctx.send("\n".join(ui))
        else:
            await ctx.send("❌ Bir hata oluştu, takım seçilemedi.")


    async def _get_external_squad(self, team_name: str, is_fast_sim: bool = False) -> tuple:
        """AI kullanarak yabancı takımın güncel (2026) kadrosunu ve bireysel oyuncu puanlarını araştır."""
        # 1. Önbellek ve Standart Anahtar Tanımı
        cache_key = f"ext_squad_v2_{self.clean_tn(team_name)}"

        # 0. Hızlı simülasyon ise veritabanındaki gerçek OVR'yi çekmeye çalış
        if is_fast_sim:
            async with database.get_db() as db:
                # Row factory'i güvenli bir şekilde ayarla
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT overall FROM teams WHERE name = ?", (team_name,)) as cur:
                    row = await cur.fetchone()
                    # Eğer Row factory başarılı olduysa row["overall"], olmadıysa row[0]
                    if row:
                        try:
                            real_ovr = row["overall"]
                        except (TypeError, IndexError):
                            real_ovr = row[0]
                    else:
                        real_ovr = 75.0
            return f"{team_name} Kadrosu (Simülasyon)", 500.0, real_ovr

        # 1. YEREL DOSYA KONTROLÜ (Öncelikli Kaynak)
        tactic_path = os.path.join("data", "tactics", f"{team_name}.txt")
        if os.path.exists(tactic_path):
            try:
                with open(tactic_path, "r", encoding="utf-8") as f:
                    content = f.read()
                t_text, l_text, t_val, t_ovr = self._parse_tactic_file(content)
                # Taktik dosyasından dinamik hesaplanan OVR'yi kullan
                final_squad = l_text if l_text else t_text
                # Safe print for Windows encoding
                safe_team = team_name.encode('ascii', 'ignore').decode('ascii')
                print(f"DEBUG: [LOCAL_FILE_LOAD] {safe_team} verisi yuklendi. OVR: {t_ovr}")
                return f"GUNCEL {team_name} KADROSU (YEDEK): " + final_squad[:1200], t_val, t_ovr
            except Exception as e:
                print(f"DEBUG: Local file load failed for {team_name}: {e}")

        # 2. Önbellek kontrolü
        cached = await database.get_scout_cache(cache_key)
        if cached:
            print(f"DEBUG: [AI_RESEARCH_CACHE] {team_name} verisi önbellekten çekildi.")
            return cached.get("squad_text", ""), cached.get("total_value_m", 50.0), cached.get("avg_ovr") or 75.0

        print(f"DEBUG: [AI_RESEARCH] {team_name} için 'Kadro Eşdeğeri' sade analiz başlıyor...")
        
        try:
            db_players = await database.get_team_players(team_name)
            
            # Transfer cog vasıtasıyla araştırıp yazdırmak için:
            if not db_players or len(db_players) < 11:
                transfer_cog = self.bot.get_cog('TransferCog')
                if transfer_cog:
                    print(f"DEBUG: DB'de yeterli oyuncu yok. TransferCog web-scraper kullanılıyor...")
                    squad_list = await transfer_cog._research_squad_web(team_name)
                    if squad_list:
                        # Since it's already List[Dict] with overall/market_value_eur, save directly
                        await database.save_research_players(team_name, squad_list)
                        db_players = await database.get_team_players(team_name)

            if db_players and len(db_players) > 0:
                blacklist = ["benzema", "kroos", "ronaldo", "ramos", "casemiro", "asensio", "bale", "messi", "neymar", "pele", "maradona"]
                
                filtered_players = []
                for p in db_players:
                    p_name = p.get("name", "").lower()
                    if not any(b in p_name for b in blacklist):
                        filtered_players.append(p)
                
                if not filtered_players: return "Kadro bulunamadı.", 100.0, 75.0

                # Kadro textini ve ortalama OVR'yi oluştur
                squad_text = ", ".join([f"{p.get('name', 'Bilinmeyen')} ({p.get('overall') or 80})" for p in filtered_players])
                
                total_val = 0.0
                total_ovr = 0
                for p in filtered_players:
                    try:
                        val = p.get('market_value') or p.get('market_value_eur', 50000000)
                        if val is None: val = 50000000
                        total_val += float(val) / 1000000.0
                    except:
                        total_val += 50.0
                        
                    try:
                        p_ovr = int(p.get('overall') or 0)
                        total_ovr += p_ovr if p_ovr > 0 else 75.0
                    except:
                        total_ovr += 75.0
                        
                sorted_players = sorted(filtered_players, key=lambda x: int(x.get('overall') or 80), reverse=True)
                top_11 = sorted_players[:11]
                bench_7 = sorted_players[11:18]
                
                avg_11 = sum(int(p.get('overall') or 70) for p in top_11) / 11 if top_11 else 70
                avg_bench = sum(int(p.get('overall') or 70) for p in bench_7) / 7 if bench_7 else avg_11
                # Veritabanı ile uyumlu olması için %70-%30 oranına çekildi
                avg_ovr = round((avg_11 * 0.70) + (avg_bench * 0.30), 1)

                
                # Kadro textini optimize et (Sadece Top 18)
                optimized_squad_text = ", ".join([f"{p.get('name', 'Bilinmeyen')} ({p.get('overall') or 80})" for p in sorted_players[:18]])
                
                final_data = {
                    "squad_text": f"GÜNCEL {team_name} KADROSU (YIL 2026): " + optimized_squad_text,
                    "total_value_m": total_val if total_val > 0 else 500.0,
                    "avg_ovr": avg_ovr
                }
                
                await database.save_scout_cache(cache_key, final_data)
                return final_data["squad_text"], final_data["total_value_m"], final_data["avg_ovr"]
                
        except Exception as e:
            print(f"DEBUG: AI Research V2 failed for {team_name}: {e}")

        # Bilgi bulunamadıysa (Gerçek maçlarda düşük puan, hızlı simde Tier puanı)
        return f"{team_name} Kadrosu - Bilgi bulunamadı (Araştırma Başarısız).", 100.0, 75.0

    def _parse_tactic_file(self, file_text: str) -> tuple:
        """Parses player values from tactical txt and returns (all_text, lineup_text, total_val_m, team_ovr)"""
        import re
        
        # 1. Temel text ayıklama
        lines = file_text.split("\n")
        # AI'nın taktikleri TAMAMINI okuması için limiti kaldırdık. Artık dosya ne kadar uzunsa o kadarını okuyacak.
        all_text = file_text


        lineup_lines = []
        is_lineup = False
        
        # 2. Oyuncu ve Değer Ayıklama Logic
        player_ovrs = []
        total_val_m = 0.0
        
        for line in lines:
            line_clean = line.strip()
            if not line_clean: continue
            
            # Lineup bloğunu birleştir
            if any(x in line_clean.upper() for x in ["İLK 11", "LINEUP", "XI", "YEDEK", "KULÜBESİ", "KADRO"]):
                is_lineup = True
                lineup_lines.append(line_clean)
                continue
            
            # Taktik başlığı gelince lineup biter (Eğer | yoksa)
            if is_lineup and (":" in line_clean and "|" not in line_clean) and not any(x in line_clean.upper() for x in ["İLK 11", "LINEUP", "XI", "YEDEK", "KULÜBESİ"]):
                 # Bazı dosyalarda açıklama satırları olabilir, tamamen kesme
                 pass
            
            # Eğer satırda | veya : varsa ve oyuncu gibi duruyorsa lineup say
            is_player_line = "|" in line_clean or (":" in line_clean and len(line_clean.split(":")) == 2 and len(line_clean.split(":")[1].strip()) > 3)
            
            if is_player_line:
                lineup_lines.append(line_clean)
                
                # OVR Analizi (Esnek format: Oyuncu | ... | Değer | ...)
                parts = [p.strip() for p in line_clean.split("|")] if "|" in line_clean else [p.strip() for p in line_clean.split(":")]
                
                # Değer Ayıkla
                mv_m = 0.0
                for part in parts:
                    if any(x in part.upper() for x in ["M", "K", "€", "BİN"]):
                        mv_m = database.parse_market_value(part) / 1_000_000.0
                        break
                
                if mv_m > 0:
                    total_val_m += mv_m
                    ovr = self._estimate_ovr_from_val(mv_m * 1_000_000)
                    player_ovrs.append(ovr)
                else:
                    # Değer bulunamadıysa ama oyuncu satırıysa (Varsayılan 78 Masterclass için)
                    if len(parts) >= 2:
                        player_ovrs.append(78)

        # 3. Team OVR Hesaplama (Yerel Dosyalarda Tüm Oyuncuların Eşit Ortalaması)
        team_ovr = 75.0
        if player_ovrs:
            # Kullanıcı talebi: TXT olanlarda direkt hepsinin ortalamasını al
            team_ovr = round(sum(player_ovrs) / len(player_ovrs), 1)

        lineup_text = "\n".join(lineup_lines)
        return all_text, lineup_text, total_val_m, team_ovr

    def _estimate_ovr_from_val(self, value_eur: float) -> int:
        """Kadro analizi için ORİJİNAL baremi taklit eder. (120M = 90 Scale)"""
        if value_eur <= 0: return 62
        vm = value_eur / 1_000_000.0
        
        # ORIGINAL BAREM (scratch/final_sync_to_db.py referanslı)
        if vm >= 120.0: res = 90 + min(6, int((vm - 120) / 20))
        elif vm >= 80.0: res = 86 + int((vm - 80) / 40 * 4)
        elif vm >= 50.0: res = 83 + int((vm - 50) / 30 * 3)
        elif vm >= 30.0: res = 80 + int((vm - 30) / 20 * 3)
        elif vm >= 15.0: res = 75 + int((vm - 15) / 15 * 4)
        elif vm >= 5.0: res = 70 + int((vm - 5) / 10 * 5)
        elif vm >= 1.0: res = 67 + int((vm - 1) / 4 * 6)
        else: res = 62
        
        return min(99, res)

    def _estimate_val_from_ovr(self, ovr: float) -> float:
        """OVR'den tahmini piyasa değeri (M €) üretir (Eksponansiyel Büyüme)"""
        import math
        if ovr < 60: return 1.0
        if ovr < 70: return 1.0 + (ovr - 60) * 0.4 # 60-70: 1M-5M
        if ovr < 75: return 5.0 + (ovr - 70) * 3.0 # 70-75: 5M-20M
        if ovr < 80: return 20.0 + (ovr - 75) * 46.0 # 75-80: 20M-250M
        
        # 80 Üzeri: Eksponansiyel Patlama (Elite Teams)
        # 80 OVR = 250M
        # 85 OVR = 1.0B+
        # 90 OVR = 3.0B+
        mult = math.exp((ovr - 80) * 0.4)
        res_m = 250.0 * mult
        return round(res_m, 1)

    async def _simulate_match_ai(self, team_a_name: str, team_a_tactics: str,
                                         team_b_name: str, team_b_tactics: str,
                                         importance: str = "Normal",
                                         weather: str = "Clear",
                                         lineup_a: str = "", lineup_b: str = "",
                                         rating_a: int = 80, rating_b: int = 80,
                                         max_a: int = 90, max_b: int = 90,
                                         min_a: int = 70, min_b: int = 70,
                                         suggested_a: int = 80, suggested_b: int = 80,
                                         formation_a: str = "", formation_b: str = "",
                                         has_tactic_a: bool = False, has_tactic_b: bool = False,
                                         value_a: float = 0.0, value_b: float = 0.0,
                                         is_tournament: bool = False, leg: int = 1,
                                         agg_context: dict = None,
                                         match_flow: str = None,
                                         luck_scenario: str = None,
                                         is_ext_a: bool = False,
                                         is_ext_b: bool = False,
                                         round_no: int = None) -> Optional[Dict]:
        """Send tactics to Gemini or Groq AI API and get detailed match simulation"""

        import random
        # Fetch a random referee from the DB
        referee = await database.get_random_referee()
        ref_name = referee.get("name", "Bilinmiyor") if referee else "Bilinmiyor"
        ref_personality = referee.get("personality", "Standart bir yönetim tarzı.") if referee else "Standart."
        ref_strictness = referee.get("strictness", 5) if referee else 5
        ref_var = referee.get("var_freq", 5) if referee else 5

        # Gemini icin herhangi bir budama yapmiyoruz (Sınırsız Taktik!)
        # Budama sadece Groq fallback (yedek motor) icin asagida yapilacak.

        # Rastgele seed - AI'in her seferinde farkli sonuc uretmesi icin
        # --- ZEKİ AKIŞ SENARYOSU SEÇİCİ (SMART SCENARIO SELECTOR) ---
        balanced_flows = [
            "SABIR MAÇI (Gole kadar kilidin açılmadığı, son yarım saatte gelen galibiyet veya mağlubiyet)",
            "DENGELİ SAVAŞ (Karşılıklı gollerin olduğu ama sonunda bir tarafın ağır bastığı maç)",
            "DURAN TOP SAVAŞI (Akan oyunda gol olmayan, tüm gollerin korner veya serbest vuruştan geldiği maç)",
            "TAKTİKSEL KİLİT (Savunmaların kusursuz olduğu, tek bir hatanın sonucu belirlediği düşük skorlu maç)",
            "SON DAKİKA ADALETİ (Maç boyu ezen takımın golü bulamadığı ama 90+5'te gelen golle kazandığı veya kaybettiği senaryo)",
            "ORTA SAHA SATRANCI (Gereksiz risklerden kaçınılan, iki takımın da birbirini orta alanda kilitlediği yüksek gerilimli maç)",
            "KALECİLERİN DÜELLOSU (Her iki kalede de inanılmaz kurtarışların yapıldığı, kalecilerin devleştiği maç)",
            "KEMİK SESLERİ (Fiziksel mücadelenin ve sertliğin teknik oyunun önüne geçtiği maç)",
            "DÜĞÜMÜ ÇÖZEN HAMLE (70 dakika boyunca kilitlenen maçın bir oyuncu değişikliğiyle bir anda çözülmesi)",
            "SON SİPER SAVUNMASI (Bir tarafın sürekli yüklendiği, diğer tarafın etten duvar örüp kontrayla vurduğu maç)",
            "STRATEJİK BEKLEYİŞ (Düşük tempolu başlayan ama son çeyrekte iki tarafın da tüm riskleri aldığı heyecan dolu kapanış)",
            "TEKNİK DİREKTÖR SAVAŞI (Kenardan gelen müdahalelerin maçın kaderini satranç hamlesi gibi değiştirdiği akış)"
        ]
        
        favorite_flows = [
            "CLEAN SHEET DOMINATION (Favorinin gol yemeden net galibiyet aldığı senaryo)",
            "ERKEN BLITZ (Favorinin ilk 20 dakikada 2-3 gol bulup maçı kopardığı senaryo)",
            "İLK YARI FİŞİ ÇEKME (Maçın ilk 45 dakikasında işi bitiren, ikinci yarıda tempoyu rölantiye alan favori)",
            "DEPLASMAN SOĞUKLUĞU (Favori deplasman ekibinin disiplinli oyunuyla sessizce kazandığı senaryo)",
            "YEDEKLERİN GÜNÜ (70'e kadar berabere giden maçın oyuna giren yedeğin golleriyle farklı bitmesi)",
            "TAKTIKSEL ÜSTÜNLÜK (Teknik direktör hamlelerinin fark yarattığı ve favorinin oyunu domine ederek kazandığı senaryo)",
            "ŞOK BASKIN (Maç başlar başlamaz gelen peş peşe şok gollerle rakibin oyun planını alt üst eden favori)",
            "HIZLI HÜCUM ŞÖLENİ (Kontra ataklarla rakibini her yakaladığında cezalandıran ve farka giden dominant oyun)",
            "ACIMASIZ BİTİRİCİLİK (Favorinin girdiği her pozisyonu gole çevirdiği, rakibi psikolojik olarak bitirdiği maç)",
            "DİSİPLİNLİ KUŞATMA (Rakibi kendi yarı sahasına hapseden ve sabırla golleri bulan profesyonel favori galibiyeti)",
            "GÖVDE GÖSTERİSİ (Yıldız oyuncuların şov yaptığı, tribünlerin mest olduğu görkemli bir galibiyet)",
            "KLASİK DOMİNASYON (Favorinin maçı başından sonuna kadar kontrol altında tuttuğu galibiyet)"
        ]
        
        blowout_flows = [
            "TARİHİ HEZİMET (Hiçbir direnç gösteremeyen zayıf rakibe karşı tarihi bir farka gidilen maç)",
            "GOL OLUP YAĞMA (Favorinin her atağının gol olduğu, rakibin adeta sahada olmadığı hezimet)",
            "TEK TARAFLI BOĞUCU OYUN (Zayıf rakibin kalesinden çıkamadığı ve farkın açıldığı maç)",
            "TOPYEKÜN SALDIRI (Favorinin bir an bile durmadığı, rakibi kendi yarı sahasına hapsettiği ve farka koştuğu maç)",
            "RUHSAL ÇÖKÜŞ (İlk golden sonra direnci tamamen kırılan zayıf rakibe karşı oynanan tek kale maç)",
            "ANTRENMAN MAÇI (Favorinin çok rahat oynadığı, pas trafiğiyle rakibi yorduğu ve çok rahat farka gittiği senaryo)",
            "DURDURULAMAZ HÜCUM HATTI (Forvetlerin her dokunuşunun gol olduğu, savunmanın çaresiz kaldığı dominant maç)",
            "REKOR KIRAN SKOR (Tarihe geçecek kadar çok golün atıldığı, zayıf rakibin adeta sahadan silindiği hezimet)",
            "HAT-TRICK GECESİ (Favori takımın yıldız forvetinin tek başına rakibi dağıttığı epik performans)",
            "GÜÇ GÖSTERİSİ (Aralarındaki devasa kalite farkını her dakika sahaya yansıtan dominant bir hezimet)"
        ]
        
        chaos_flows = [
            "ŞOK GERİ DÖNÜŞ (Farklı mağlubiyetten beraberliğe yada galibiyete uzanan dramatik comeback)",
            "GOL YAĞMURU (Savunmaların çöktüğü, her atağın tehlike olduğu ve çılgın bir skorla biten maç)",
            "VAR KARMAŞASI (İptal edilen goller ve penaltılar yüzünden skorun sürekli değiştiği kaotik akış)",
            "GERİ DÖNÜŞÜN EŞİĞİ (Bir takımın farkla öne geçtiği, rakibin yaklaştığı ama sonunda farkın tekrar açıldığı maç)",
            "KABÜS BAŞLANGIÇ (Bir takımın ilk 10 dakikada farkla yenik duruma düşüp sonra direnç gösterdiği dram)",
            "KIRMIZI KART FIRTINASI (Peş peşe gelen kartlarla iki takımın da eksik kaldığı ve taktiklerin çöktüğü kaos)",
            "90+ MUCİZESİ (Maçın son düdüğüne saniyeler kala gelen imkansız bir golle tüm dengelerin değiştiği anlar)",
            "KALECİ HATASI KOMEDİSİ (Kalecilerin akılalmaz hatalarının maçı bir komediye veya drama çevirdiği senaryo)",
            "VAR'DAN DÖNEN HAYATLAR (Son dakikada VAR kararıyla iptal edilen veya verilen penaltının kader belirlediği maç)",
            "FIRTINA GİBİ DÖNÜŞ (İkinci yarıda bambaşka bir kimlikle sahaya çıkan takımın mucizevi geri dönüşü)",
            "ADRENALİN PATLAMASI (Düşük tempolu başlayıp son 15 dakikada 3-4 golün atıldığı, her şeyin birbirine girdiği anlar)"
        ]
        
        wildcard_flows = [
            "BEKLENMEDİK ÇÖKÜŞ (Dengeli maçta bir tarafın şok bir şekilde dağıldığı farklı mağlubiyet senaryosu)",
            "SÜRPRİZ YENİLGİ (Favori takımın her şeyi yapmasına rağmen şanssızlıklarla kaybettiği şok skor)",
            "90+5 YIKIMI (Maçın berabere biteceği sanılırken son saniyede gelen golle gelen mağlubiyet veya galibiyet)",
            "Son dakikaya kadar baskın oynayan tarafın son dakika yediği gol ile yenilmesi."
        ]

        # 1. TEMEL DEĞERLER VE REYTİNG ANALİZİ
        if rating_a == "Belirsiz" or rating_b == "Belirsiz":
            rating_gap = "Belirsiz"
            balance_instruction = "Denge Analizi: Takımların gücü tam olarak bilinmiyor. Lütfen verilen kadrolardaki oyuncuların kalitelerini temel bir veri olarak al ama KESİNLİKLE bir takımı diğerine mühürlenmiş galip ilan etme. Sürpriz ihtimalini her zaman saklı tut."
        else:
            rating_gap = abs(rating_a - rating_b)
            if rating_gap >= 15:
                stronger = team_a_name if rating_a > rating_b else team_b_name
                balance_instruction = f"Realizm Analizi: {stronger} takımı kağıt üstünde ÇOK DAHA GÜÇLÜ duruyor ({rating_gap} puan fark). Bu seviyedeki bir farkta sürprizler (Beraberlik/Mağlubiyet) ancak mucizevi kaleci performansları veya ağır taktiksel hatalarla çok nadir gerçekleşebilir. {stronger} takımının net hakimiyetini ve kalite farkını yansıt."
            elif rating_gap >= 8:
                stronger = team_a_name if rating_a > rating_b else team_b_name
                balance_instruction = f"Realizm Analizi: {stronger} takımı favori ({rating_gap} puan fark). Ancak dengeli bir maç kurgula, sürprizleri tamamen dışlama."
            else:
                balance_instruction = f"Denge Analizi: Takımlar güç olarak birbirine çok yakındır ({rating_gap} puan fark). Maçın galibini tamamen sahadaki taktiksel savaş ve şans belirleyecek."

        # 2. ÜRETİCİLER (SEEDS) VE MİZAÇLAR
        match_id_seed = random.randint(1000, 9999)
        possession_seed = random.randint(35, 65)
        chaos_level = random.randint(1, 10) 


        # --- KONTROLLÜ MAÇ AKIŞI (TORBA) ---
        # Eğer dışarıdan senaryo verilmediyse (Geriye uyumluluk için)
        if not match_flow:
            balanced_flows = [
                "DENGELİ SAVAŞ (Orta saha mücadelesinin yoğun olduğu, taktiklerin konuştuğu bir maç)",
                "KEMİK SESLERİ (Fiziksel mücadelenin ve sertliğin teknik oyunun önüne geçtiği, duran topların önemli olduğu senaryo)",
                "SATRANÇ MAÇI (İki hocanın birbirini kilitlemeye çalıştığı, hata yapanın kaybedeceği düşük tempolu maç)",
                "KAOTİK ORTA SAHA (Pas trafiğinin sürekli kesildiği, topun bir o kalede bir bu kalede olduğu ama kalitenin düştüğü anlar)"
            ]
            
            chaos_flows = [
                "KAOS VE KIRMIZI KART (Beklenmedik bir sertlik veya tartışma sonucu oyunun çığırından çıktığı senaryo)",
                "VAR KAOSU (Kritik anlarda gelen VAR kararlarının hem moralleri hem de skoru alt üst ettiği maç)",
                "HAKEM HATALARI (Tartışmalı kararların maçın kaderini etkilediği, gerilimin tırmandığı anlar)",
                "ADRENALİN PATLAMASI (Düşük tempolu başlayıp son 15 dakikada 3-4 golün atıldığı, her şeyin birbirine girdiği anlar)"
            ]

            match_flow = random.choice(balanced_flows + chaos_flows)

        print(f"DEBUG: [AI_CORE] Torbadan Gelen Maç Akışı -> {match_flow}")
        
        # Artık ağırlıkları AI belirleyecek
        weights = "AI tarafından taktik ve kadroya göre dinamik belirlensin."

        variety_instruction = ""
        if chaos_level > 8:
            variety_instruction = "SKOR PATLAMASI (EXTREME VARIETY): Bu maçta skor tablosu yerinden oynayabilir! 4-4, 5-2, 6-1, 0-5 gibi uç noktaları ve çılgın skorları kovala. Sürprizlere, kırmızı kartlara ve inanılmaz geri dönüşlere sonuna kadar İZİN VER! Rutinden çık, bizi şaşırt."
        elif chaos_level > 5:
            variety_instruction = "YÜKSEK ÇEŞİTLİLİK: Standart skorlardan (1-0, 2-1) kaçın. 3-1, 2-2, 4-2, 3-0 gibi net ve çeşitli skorlar üret. Maçın hikayesi skorun coşkusuyla örtüşsün."
        else:
            variety_instruction = "GERÇEKÇİ VE DENGELİ ÇEŞİTLİLİK: Skorlar gerçekçi olsun ama yine de monotonluktan kaçın. Sahadaki rütbe ve kaliteyi skora yansıt."
        
        # Ekstra varyasyon için maç senaryosu (Etkileyici ama yıkıcı olmayan olaylar)
        scenarios = [
            "Favori takım bugün çok şanssız, topları direkten dönüyor.",
            "Zayıf olan takımın kalecisi bugün kariyer maçını oynuyor, her şeyi kurtarıyor.",
            "Maç çok sert geçiyor, fiziksel mücadele ve fauller ön planda.",
            "Zayıf takım maça fırtına gibi başlıyor, erken golle favoriyi sarsıyor.",
            "Hava koşulları teknik takımları zorluyor, zemin çok ağır.",
            "Son dakika golleri veya tartışmalı VAR kararları tansiyonu yükseltiyor.",
            "Favori savunmada beklenmedik bir bireysel hata yapıyor ama oyunu bırakmıyor.",
            "Underdog takımın hocası maç içinde cesur bir taktik değişikliği ile dengeyi bozuyor.",
            "Hakemin tartışmalı faul düdükleri iki tarafı da geriyor ve hırslandırıyor.",
            "Kritik bir oyuncunun hafif sakatlığı taktiksel bir esnekliğe zorluyor."
        ]
        luck_scenario = random.choice(scenarios)

        # 5. TOURNAMENT CONTEXT (YENİ)
        tournament_info = ""
        if is_tournament:
            tournament_info = f"\n=== TURNUVA BAĞLAMI ({importance}) ===\n"
            tournament_info += f"Tür: Eleme Usulü (Knockout) | Maç: {leg}. Ayak\n"
            if leg == 2 and agg_context:
                first_leg = "Bilinmiyor"
                if isinstance(agg_context, dict):
                    first_leg = agg_context.get('first_leg_score', 'Bilinmiyor')
                elif isinstance(agg_context, (list, tuple)) and len(agg_context) > 0:
                    # Fallback for unexpected tuple format
                    first_leg = str(agg_context[0])
                
                tournament_info += f"İLK MAÇ SKORU: {first_leg}\n"
                tournament_info += "!!! KRİTİK MATEMATİK KURALI !!!\n"
                tournament_info += "1. Bu maçın 90 dakika skoru ile ilk maç skorunu TOPLA (Aggregate).\n"
                tournament_info += "2. Eğer TOPLAM SKOR (Aggregate) EŞİT DEĞİLSE: Maç 90 dakikada biter. KESİNLİKLE uzatma veya penaltı yapma!\n"
                tournament_info += "3. Eğer TOPLAM SKOR (Aggregate) EŞİT İSE: Maç 30 dk UZATMALARA gider. Uzatmalarda da eşitlik bozulmazsa PENALTI ATIŞLARINA geçilir.\n"
                tournament_info += "4. Sadece EŞİTLİK durumunda 'is_extra_time': true yap ve 'penalties' listesini doldur. Mutlaka bir TUR ATLAYAN (final_winner) belirle!\n"
            else:
                tournament_info += "Bu eşleşmenin ilk maçı."

        # --- DERBİ GARANTİSİ (GS vs BJK) ---
        derby_bias = ""
        is_league = "Lig" in importance or not is_tournament
        if is_league:
            tn_a = self.clean_tn(team_a_name)
            tn_b = self.clean_tn(team_b_name)
            rivals = ["galatasaray", "fenerbahce", "trabzonspor","kocaelispor"]
            if tn_a == "besiktas" and tn_b in rivals:
                derby_bias = f"\n[DSK - ÖZEL TALİMAT]: Bu bir Süper Lig derbisidir. Beşiktaş'ın sahadan MUTLAK GALİBİYETLE ayrılması gerekmektedir. Oyun çekişmeli geçse bile final skoru Beşiktaş lehine olmalıdır. Beraberlik veya mağlubiyet kabul edilemez.\n"
            elif tn_b == "besiktas" and tn_a in rivals:
                derby_bias = f"\n[DSK - ÖZEL TALİMAT]: Bu bir Süper Lig derbisidir. Beşiktaş'ın sahadan MUTLAK GALİBİYETLE ayrılması gerekmektedir. Oyun çekişmeli geçse bile final skoru Beşiktaş lehine olmalıdır. Beraberlik veya mağlubiyet kabul edilemez.\n"

        # --- SCRIPTED MATCH (Kocaelispor vs Beşiktaş - Hafta 10) ---
        scripted_bias = ""
        if round_no == 10:
            tn_a = self.clean_tn(team_a_name)
            tn_b = self.clean_tn(team_b_name)
            if (tn_a == "kocaelispor" and tn_b == "besiktas") or (tn_a == "besiktas" and tn_b == "kocaelispor"):
                scripted_bias = f"\n[DSK - ÖZEL SENARYO]: Bu maç 10. haftanın en kritik maçıdır. Beşiktaş bu maçı KESİNLİKLE son dakika (85' sonrası) golüyle kazanmalıdır. Maç boyu skor dengede gidebilir veya Kocaelispor öne geçebilir ancak final skoru Beşiktaş galibiyeti olmalı ve galibiyet golü mutlaka son dakikalarda gelmelidir. Bu bir senaryo gereğidir, Beşiktaş galibiyeti şarttır.\n"

        
        # --- NARRATIVE PERSONALITY SYSTEM ---
        commentary_styles = [
            "Dramatic Peter Drury style (Poetic, high-energy, every moment feels like destiny)",
            "Classic Martin Tyler style (Balanced, legendary, focusing on key narratives)",
            "Tactical Jamie Carragher & Gary Neville style (Focus on positioning and technical blunders)",
            "Radio-style BBC 5 Live (Fast-paced, descriptive, extremely immersive)",
            "Cinematic Sports Documentary style (Deeply emotional, slow-build, epic scale)",
            "UCL Nights Glow (Premium, orchestral atmosphere, high prestige)",
            "Chaos & Passion style (Aggressive, fan-centric, shouting at every goal like a South American commentator)",
            "Analytical Mastermind style (Focusing on expected goals, tactical shifts, and individual player heatmaps)"
        ]
        chosen_style = random.choice(commentary_styles)

        # ==========================================
        # 1. PREMIUM PROMPT (GEMINI - CINEMATIC, DEEP & ANALYTICAL)
        # ==========================================
        ext_info = ""
        if is_ext_a or is_ext_b:
            ext_info = "DİKKAT: Bu bir DIŞ MAÇ (European/International). Takım verileri güncel web araştırmasına dayalıdır.\n"
            if is_ext_a: ext_info += f"- {team_a_name} bir dış takımdır.\n"
            if is_ext_b: ext_info += f"- {team_b_name} bir dış takımdır.\n"

        prompt_premium = f"""
{ext_info}
{derby_bias}
{scripted_bias}
Match #{match_id_seed} - You are a legendary football historian and tactical mastermind.
MATCH SPIRIT: This isn't just a match report; it must be the most epic football narrative of the 2026 season.

- **MATCH NARRATIVE RULES [CRITICAL]**:
    1. **EPIC DENSITY (20-25 EVENTS)**: The match must feel like a living story. Include at least 20-25 unique events. Don't just report goals; describe incredible saves, tactical fouls, fan choreographies, manager disputes, and shifts in momentum. (At least 20-25 events).
    2. **DESCRIPTIVE EVENTS [MANDATORY]**: EVERY event (not just goals) must have a 2-3 sentence description. If it's a yellow card, describe the foul and the player's reaction. If it's a save, describe the goalkeeper's flight. NEVER use one-sentence generic descriptions.
    3. **GOAL MASTERPIECES**: Each goal must be a 3-4 sentence masterpiece describing the build-up, technical execution, and the stadium's explosion.
    4. **REALISM GUARD**: If GPR difference is < 12, keep the score gap within 3 goals (e.g. 3-0, 2-2) unless there are red cards.
    5. **SYNCED GOALS**: Every goal in 'goals' MUST be in 'events' with a deeply detailed 'description'.
    6. **NO SPOILERS [CRITICAL]**: DO NOT start the match with a barrage of repetitive fouls or yellow cards for a specific team just to signal they are "frustrated" or losing. Keep the first 15-20 minutes focused on tactical play, stadium atmosphere, and close chances. The winner should NOT be obvious from the opening events.
    7. **ATMOSPHERIC EVENTS [NEW]**: Include at least 2-3 events that are NOT about the ball (e.g., a massive choreography at kickoff, a heated argument between the manager and the 4th official, a VAR tension moment, or a dramatic fan reaction). Use types like 'atmosphere', 'choreography', 'manager_dispute', or 'referee_talk'.

ATTENTION: THE CURRENT DATE IS APRIL 1, 2026! 
{tournament_info}
MATCH FLOW SCENARIO (ABSOLUTE CONSTITUTION - MANDATORY): {match_flow}
[DSK - SENARYO EGEMENLİĞİ]: 
1. Bu senaryo senin KUTSAL REHBERİNDİR. Tüm maç anlatımı ve 'events' (olaylar) listesi bu senaryonun ruhunu ve teknik detaylarını yansıtmak ZORUNDADIR. 
2. Eğer senaryo 'ERKEN BLITZ' diyorsa ilk 20 dakikada mutlaka goller olmalı. Eğer 'KALECİ HATASI' diyorsa 'events' içinde mutlaka fahiş bir kaleci hatası betimlenmeli.
3. Anlatım (narrative) ve istatistikler (xg, possession) bu senaryoyla asla çelişmemeli. Senaryoyu sadece bir başlık olarak değil, tüm hikayenin omurgası olarak kullan.
CHAOS LEVEL: {chaos_level}/10 | SPECIAL CONDITION: {luck_scenario}
{balance_instruction} | {variety_instruction}

=== TÜRKÇE ANLATIM VE TAKTİKSEL DERİNLİK ===
1. TÜRK FUTBOL JARGONU: 'Doksanlara takılan top', 'Tabela değişiyor', 'Kontra atak', 'Savunmada büyük açik', 'Tribünler tek ses' gibi gerçek Türk spor medyası terimlerini kullan.
2. PSİKOLOJİK DERİNLİK: Önemli bir hatadan sonra oyuncunun yaşadığı hayal kırıklığını veya gol sonrası stadyumdaki coşkuyu betimle.
3. ATMOSFER: Sahadaki meşalelerden, yedek kulübesindeki teknik direktörün çılgınlar gibi verdiği taktiklere kadar her detay anlatımda yer alsın.

=== KADRO VE TAKTİK VERİLERİ ===
EV SAHİBİ: {team_a_name}
[BAŞLANGIÇ_EV_SAHİBİ]
{team_a_tactics}
{lineup_a}
[BİTİŞ_EV_SAHİBİ]

DEPLASMAN: {team_b_name}
[BAŞLANGIÇ_DEPLASMAN]
{team_b_tactics}
{lineup_b}
[BİTİŞ_DEPLASMAN]

=== MAÇ KOŞULLARI ===
Önem: {importance} | Hava: {weather} | Baz GPR: {team_a_name} ({suggested_a}) vs {team_b_name} ({suggested_b})

=== JSON FORMATI (SADECE JSON döndür) ===
{{
    "home_team": "{team_a_name}",
    "away_team": "{team_b_name}",
    "apr_home": 85,
    "apr_away": 82,
    "apr_reason": "Taktiksel analiz.",
    "home_score": 0,
    "away_score": 0,
    "goals": [
        {{"minute": 23, "player": "Oyuncu Adı", "team": "Takım", "type": "regular", "assist": "Asistçi"}}
    ],
    "events": [
        {{"minute": 15, "type": "goal", "team": "Takım", "player": "Oyuncu", "description": "GOLÜN HİKAYESİ: ... (En az 3-4 cümle)"}},
        {{"minute": 32, "type": "great_save", "team": "Takım", "player": "Oyuncu", "description": "KURTARIŞIN HİKAYESİ: ... (En az 2-3 cümle, kalecinin hamlesini ve tribünlerin alkışını anlat)"}},
        {{"minute": 44, "type": "hit_woodwork", "team": "Takım", "player": "Oyuncu", "description": "DİREKTEN DÖNEN TOPUN HİKAYESİ: ... (En az 2-3 cümle, vuruşun şiddetini ve stadyumdaki 'ah' sesini betimle)"}}
    ],
    "motm": {{"player": "Maçın Adamı", "team": "Takım", "rating": 9.2}},
    "tactical_summary": "TEKNİK RAPOR: ...",
    "pre_match_media": {{ "headline": "...", "home_fan_tweet": "...", "away_fan_tweet": "..." }},
    "first_half_summary": "...",
    "half_time_media": {{ "headline": "...", "home_fan_tweet": "...", "away_fan_tweet": "..." }},
    "second_half_summary": "...",
    "formation_a": "4-2-3-1", "formation_b": "4-4-2",
    "tactic_a": "High Press", "tactic_b": "Counter",
    "possession_home": 54, "possession_away": 46,
    "shots_home": 17, "shots_away": 11,
    "shots_on_target_home": 7, "shots_on_target_away": 3,
    "pass_accuracy_home": 82, "pass_accuracy_away": 78,
    "offsides_home": 2, "offsides_away": 3,
    "xg_home": 1.45, "xg_away": 0.82,
    "corners_home": 6, "corners_away": 4,
    "fouls_home": 12, "fouls_away": 15,
    "var_events": ["..."],
    "is_extra_time": false, "extra_time_score": "0-0",
    "penalties": [],
    "final_winner": "..."
}}
"""

        # ==========================================
        # 2. FAST PROMPT (GROQ - OPTIMIZED)
        # ==========================================
        prompt_fast = f"""
{ext_info}
{derby_bias}
{scripted_bias}
MATCH: {team_a_name} vs {team_b_name} | SCENARIO: {match_flow}
CRITICAL: Generate AT LEAST 12-15 events. NEVER use generic phrases like 'steps up to the plate'. 
VARIETY: Event descriptions must be unique. Every minute should describe a different tactical action, player movement, or stadium detail. ABSOLUTELY avoid repetitive sentences.
NO SPOILERS: Avoid repetitive early fouls or cards that signal the winner too early. Keep the start of the match neutral and unpredictable.
ATMOSPHERE: Include 1-2 events about the fans, choreographies, or manager reactions to make the match feel alive.

=== KADROLAR VE TAKTİKLER ===
EV SAHİBİ: {team_a_name}
[BAŞLANGIÇ_EV_SAHİBİ]
{team_a_tactics}
{lineup_a}
[BİTİŞ_EV_SAHİBİ]

DEPLASMAN: {team_b_name}
[BAŞLANGIÇ_DEPLASMAN]
{team_b_tactics}
{lineup_b}
[BİTİŞ_DEPLASMAN]

GPR: {suggested_a} - {suggested_b} | CHAOS: {chaos_level}/10 | {balance_instruction}

=== MANTIKSAL TUTARLILIK VE JSON ===
1. SKOR: 'home_score' ve 'away_score' değerleri listedeki gol sayısıyla tam olarak uyuşmalıdır.
2. İSTATİSTİK: İsabetli şut >= gol sayısı olmalıdır.
3. DİL: Kesinlikle TÜRKÇE. İngilizce, Portekizce veya başka bir dil kullanma.

ONLY return JSON:
{{
    "home_team": "{team_a_name}",
    "away_team": "{team_b_name}",
    "apr_home": 85, "apr_away": 82, "apr_reason": "...",
    "home_score": 0, "away_score": 0,
    "goals": [ ... ],
    "events": [ {{"minute": 5, "type": "goal", "team": "...", "description": "DETAYLI GOL ANLATIMI..."}} ],
    "motm": {{ ... }}, "tactical_summary": "...",
    "pre_match_media": {{ ... }}, "first_half_summary": "...", "half_time_media": {{ ... }}, "second_half_summary": "...",
    "formation_a": "...", "formation_b": "...", "tactic_a": "...", "tactic_b": "...",
    "possession_home": 47, "possession_away": 53, "shots_home": 14, "shots_away": 16,
    "shots_on_target_home": 5, "shots_on_target_away": 7,
    "pass_accuracy_home": 80, "pass_accuracy_away": 82, "xg_home": 1.1, "xg_away": 1.4,
    "var_events": [], "is_extra_time": false, "penalties": [], "final_winner": "..."
}}
"""

        # --- STRATEJİK BONUS VE BOOST SİSTEMİ ---
        boost_info = []
        if "beşiktaş" in team_a_name.lower():
            boost_info.append("Beşiktaş (Saha içi organizasyonu ve direnci yüksek)")
        if "beşiktaş" in team_b_name.lower():
            boost_info.append("Beşiktaş (Saha içi organizasyonu ve direnci yüksek)")
        if "beşiktaş" in team_a_name.lower() and "galatasaray" in team_b_name.lower():
            boost_info.append("🔴 ÖZEL TALİMAT: Beşiktaş derbide KESİNLİKLE yenilmemeli, ya kazanmalı ya da berabere kalmalıdır. Beşiktaş'ın oyun üstünlüğünü simüle et.")
        
        boost_msg = f"KRİTİK: {', '.join(boost_info)} bonusu devreye alınmıştır. Bu takımları sahada daha organize ve dirençli göster." if boost_info else ""

        system_prompt_premium = f"Sen '{chosen_style}' üslubuna sahip, efsanevi bir Türk futbol yorumcusu ve analistisin. {boost_msg}"
        
        system_prompt_fast = (
            f"Sen '{chosen_style}' üslubunda, heyecan dolu bir Türk spor spikerisin. {boost_msg}\n"
            "DİL KURALLARI (KESİN):\n"
            "1. SADECE TÜRKÇE: Maç olayları, özetler ve açıklamalar tamamen Türkçe olmalıdır.\n"
            "2. DOĞAL ANLATIM: Robotik çevirilerden kaçın. Türk futbolunun ruhuna uygun terimler (kaleyi yokladı, direkleri dövdü vb.) kullan.\n"
            "3. ÇEŞİTLİLİK: Her dakika farklı bir olayı betimle.\n"
            "SADECE geçerli JSON döndür."
        )

        # --- AI GENERATION WITH CENTRAL CASCADE ---
        result = await ai.generate_content(
            prompt=prompt_premium,
            system=system_prompt_premium,
            temp=1.05,
            tokens=8000,
            is_json=True,
            label=f"{team_a_name} - {team_b_name}",
            prompt_fallback=prompt_fast,
            system_fallback=system_prompt_fast
        )
        if result:
            # --- LOGIC GUARD: SANITY CHECK & PLAYER RECOVERY ---
            import re
            
            # 1. Extract player names from lineups to replace "Bilinmeyen" or Tactical headers
            def get_names(lineup_str):
                names = []
                for line in lineup_str.split('\n'):
                    if '|' in line:
                        # Extract part before first '|'
                        name_part = line.split('|')[0].strip()
                        # Remove leading bullets, emojis, or numbers like "1. " or "→"
                        clean_name = re.sub(r'^[^\w\s]+', '', name_part) 
                        clean_name = re.sub(r'^[\d\.]+\s+', '', clean_name).strip()
                        if clean_name and len(clean_name) > 2:
                            names.append(clean_name)
                return names
            
            p_a = get_names(lineup_a)
            p_b = get_names(lineup_b)
            
            # (Narrative Sync logic remains same...)
            existing_goal_mins = [int(g.get("minute", -1)) for g in result.get("goals", [])]
            for e in result.get("events", []):
                e_desc = e.get("description", "").lower()
                e_type = e.get("type", "").lower()
                e_min = int(e.get("minute", -1))
                
                goal_triggers = ["gol attı", "topu ağlara gönderdi", "skoru yaptı", "skoru değiştirdi", "fileleri havalandırdı"]
                is_goal_text = any(x in e_desc for x in goal_triggers)
                
                if (e_type == "goal" or is_goal_text) and e_min not in existing_goal_mins:
                    new_goal = {
                        "minute": e_min,
                        "team": e.get("team", "home"),
                        "player": e.get("player", "Oyuncu"),
                        "type": "goal"
                    }
                    if "goals" not in result: result["goals"] = []
                    result["goals"].append(new_goal)
                    existing_goal_mins.append(e_min)

            # Re-calculate Score (Logic Guard handles stats...)
            final_home = 0
            final_away = 0
            h_clean_name = team_a_name.lower().replace("fk", "").strip()
            a_clean_name = team_b_name.lower().replace("fk", "").strip()
            
            for g in result.get("goals", []):
                g_team = str(g.get("team", "") or "").lower()
                is_h = any(x in g_team for x in [h_clean_name, "home", "ev sahibi"])
                if is_h: final_home += 1
                else: final_away += 1
            
            result["home_score"] = final_home
            result["away_score"] = final_away

            # Correct impossible stats (Ensure numeric types)
            try:
                h_s, a_s = int(final_home), int(final_away)
                sot_h = int(result.get("shots_on_target_home", 0) or 0)
                s_h = int(result.get("shots_home", 0) or 0)
                if h_s > 0 and sot_h < h_s: sot_h = h_s + random.randint(0, 2)
                if s_h < sot_h: s_h = sot_h + random.randint(2, 6)
                result["shots_on_target_home"], result["shots_home"] = sot_h, s_h
    
                sot_a = int(result.get("shots_on_target_away", 0) or 0)
                s_a = int(result.get("shots_away", 0) or 0)
                if a_s > 0 and sot_a < a_s: sot_a = a_s + random.randint(0, 2)
                if s_a < sot_a: s_a = sot_a + random.randint(2, 6)
                result["shots_on_target_away"], result["shots_away"] = sot_a, s_a
                
                pos_h = float(result.get("possession_home", 50) or 50)
                result["possession_home"] = pos_h
                result["possession_away"] = 100.0 - pos_h
            except Exception as e:
                print(f"DEBUG: Stats correction error: {e}")
                # Fallback to defaults if something is really broken
                result["shots_home"], result["shots_away"] = 12, 10
                result["shots_on_target_home"], result["shots_on_target_away"] = 5, 4
                result["possession_home"], result["possession_away"] = 50.0, 50.0
            
            # 3. Replace "Bilinmeyen" or Tactical Headers with real players
            def fix_players(items, team_names):
                if not team_names: return
                # Headers like "STRATEJİK VİZYON" are often long and contain tactical words
                bad_keywords = ["bilinmeyen", "unknown", "oyuncu", "bilinmiyor", "vizyon", "stratejik", "duvar", "taktik", "plan", "operasyon"]
                for item in items:
                    pname = str(item.get("player", "") or "").lower()
                    # If name is generic, tactical, or abnormally long, replace it.
                    if not pname or any(x in pname for x in bad_keywords) or len(pname) > 28:
                        item["player"] = random.choice(team_names)

            for g in result.get("goals", []):
                t_low = str(g.get("team", "") or "").lower()
                is_a_team = any(x in t_low for x in [h_clean_name, "home", "ev sahibi"])
                fix_players([g], p_a if is_a_team else p_b)

            for e in result.get("events", []):
                t_low = str(e.get("team", "") or "").lower()
                is_a_team = any(x in t_low for x in [h_clean_name, "home", "ev sahibi"])
                fix_players([e], p_a if is_a_team else p_b)

            result["referee_name"] = ref_name
            result["match_flow"] = match_flow
            result["chaos_level"] = chaos_level
            result["apr_home"] = max(min(result.get("apr_home", rating_a), max_a), min_a)
            result["apr_away"] = max(min(result.get("apr_away", rating_b), max_b), min_b)
            result["squad_a"] = lineup_a
            result["squad_b"] = lineup_b
            return result

        print("DEBUG: Tüm Gemini modelleri başarısız oldu!")
        return None

    async def _run_live_simulation(self, ctx, result: dict, competition: str):
        """Run a 75-second natural live simulation with Pre-match and HT media"""
        import asyncio
        import discord
        import random
        
        home_team = result.get("home_team", "Ev Sahibi")
        away_team = result.get("away_team", "Deplasman")
        
        home_clean = self.clean_tn(home_team)
        away_clean = self.clean_tn(away_team)

        # 1. Mevcut olayları topla
        all_moments = []
        event_minutes = [e.get("minute") for e in result.get("events", [])]
        
        for i, e in enumerate(result.get("events", [])):
            etype = e.get("type", "")
            emoji = self._get_event_emoji(etype, i)
            
            desc = f"{emoji} {e.get('description', 'Önemli bir an!')}"
            
            if etype == "penalty":
                is_goal = False
                e_team_clean = self.clean_tn(e.get("team", ""))
                for g in result.get("goals", []):
                    if abs(int(g.get("minute", 0)) - int(e["minute"])) <= 2:
                        g_team_clean = self.clean_tn(g.get("team", ""))
                        if g_team_clean in e_team_clean or e_team_clean in g_team_clean:
                            is_goal = True
                            break
                        if any(x in e_team_clean.lower() for x in ["home", "ev", "host"]) and g_team_clean == home_clean:
                            is_goal = True
                            break
                if is_goal:
                    desc += " **[GOL!]**"
                else:
                    desc += " **[KAÇTI!]**"
            elif etype in ["penalty_missed", "penalty_saved"]:
                desc += " **[KAÇTI!]**"

            all_moments.append({
                "minute": e["minute"], 
                "type": etype, 
                "team": e.get("team", ""),
                "desc": desc
            })

        # 2. KRİTİK GOL KURTARMA (AI eksik bildirdiyse)
        goal_fallbacks = [
            "⚽ **GOOOL!** {player} ceza sahası dışından mermi gibi vurdu, ağlar sarsılıyor! ({team})",
            "⚽ **GOOOL!** {player} kaleciyle karşı karşıya soğukkanlı bir vuruşla topu ağlara gönderdi! ({team})",
            "⚽ **GOOOL!** Kornerden gelen topa {player} kafayı vurdu ve fileleri havalandırdı! ({team})",
            "⚽ **GOOOL!** {player} rakiplerini tek tek ipe dizdi, enfes bir bitiriş! ({team})",
            "⚽ **GOOOL!** Dönen topu {player} tamamladı, stadyum ayakta! ({team})",
            "⚽ **GOOOL!** {player} kalecinin uzanamayacağı köşeye imzasını attı! ({team})",
            "⚽ **GOOOL!** {player} adeta 'buradayım' dedi ve takımını öne geçirdi! ({team})",
            "⚽ **GOOOL!** Akıl dolu bir plase! {player} topu ağlara bıraktı! ({team})",
            "⚽ **GOOOL!** {player} savunma hatasını affetmedi, skoru değiştirdi! ({team})",
            "⚽ **GOOOL!** Müthiş bir vuruş! {player} tribünleri coşturuyor! ({team})"
        ]

        for g in result.get("goals", []):
            g_min = g.get("minute")
            has_goal_event = any(m["minute"] == g_min and m["type"] in ["goal", "penalty"] for m in all_moments)
            if not has_goal_event:
                g_team = g.get("team", "Bilinmeyen")
                player_name = g.get("player", "Oyuncu")
                fallback_template = random.choice(goal_fallbacks)
                all_moments.append({
                    "minute": g_min,
                    "type": "goal",
                    "team": g_team,
                    "desc": fallback_template.format(player=player_name, team=g_team)
                })
            
        all_moments.sort(key=lambda x: x["minute"])
        
        base_delay = 50 / max(len(all_moments), 1)
        base_delay = max(1.8, min(base_delay, 5.0)) 
        
        current_h_score = 0
        current_a_score = 0
        ticker = []
        
        def get_stats_text(p_h, p_a, s_h, s_a, sot_h, sot_a):
            return f"📊 **Topla Oynama:** %{p_h} - %{p_a}\n🥅 **Şut:** {s_h}({sot_h}) - {s_a}({sot_a})"

        # 1. MAÇ ÖNÜ (PRE-MATCH) PHASE
        pm_media = result.get("pre_match_media", {})
        pre_embed = discord.Embed(
            title=f"⏳ MAÇ ÖNÜ: {home_team} vs {away_team}",
            description=f"🎤 **MAÇ ÖNÜ ANALİZ BÜLTENİ:**\n{pm_media.get('headline', 'Dev maç için geri sayım başladı!')}",
            color=0x34495e
        )
        self._add_split_fields(
            embed=pre_embed,
            name=f"🐦 Taraftar Sesi ({home_team})", 
            value=f"\"{pm_media.get('home_fan_tweet', 'Saldırın!')}\"", 
            inline=True
        )
        self._add_split_fields(
            embed=pre_embed,
            name=f"🐦 Taraftar Sesi ({away_team})", 
            value=f"\"{pm_media.get('away_fan_tweet', 'Yeneceğiz!')}\"", 
            inline=True
        )
        pre_embed.set_footer(text=f"📺 {competition} | Atmosfer harika, başlama vuruşu bekleniyor...")
        live_msg = await ctx.send(embed=pre_embed)
        await asyncio.sleep(12) # Maç önü (12 sn)
        
        # 2. MAÇ BAŞLANGICI
        live_embed = discord.Embed(
            title=f"🏟️ {home_team} 0 - 0 {away_team} (0')",
            description="🎬 **MAÇ BAŞLADI!** Başlama vuruşuyla birlikte heyecan dorukta.",
            color=0x95a5a6
        )
        live_embed.set_footer(text=f"🔴 CANLI | {competition} | 75 Saniyelik Maç Keyfi")
        try:
            await live_msg.edit(embed=live_embed)
        except: pass
        await asyncio.sleep(3)
        
        half_time_shown = False
        
        for i, moment in enumerate(all_moments):
            minute = moment["minute"]
            
            # DEVRE ARASI (45')
            if minute > 45 and not half_time_shown:
                ht_media = result.get("half_time_media", {})
                ht_summary = result.get("first_half_summary", "Kıran kırana bir mücadele!")
                
                ht_embed = discord.Embed(
                    title=f"🏟️ {home_team} {current_h_score} - {current_a_score} {away_team} (DEVRE ARASI)",
                    description=f"📝 **TEKNİK VE TAKTİKSEL DEVRE ARASI RAPORU:**\n{ht_summary}",
                    color=0x34495e
                )
                
                # İstatistikleri AI'nın final istatistiklerini baz alarak devre arasına orantıla (Daha gerçekçi)
                # Sadece olayları saymak yerine, AI'nın hedeflediği toplam şutun bir kısmını (yaklaşık %45) burada göster
                intended_s_h = result.get("shots_home", 0)
                intended_s_a = result.get("shots_away", 0)
                intended_sot_h = result.get("shots_on_target_home", 0)
                intended_sot_a = result.get("shots_on_target_away", 0)
                
                # O ana kadarki golleri de ekleyelim
                ratio = random.uniform(0.35, 0.55)
                s_h = int(intended_s_h * ratio)
                s_a = int(intended_s_a * ratio)
                sot_h = int(intended_sot_h * ratio)
                sot_a = int(intended_sot_a * ratio)
                
                # Minimum garanti: Skor kadar şut olmalı ve 0-0'ı önleyelim
                s_h = max(s_h, current_h_score, random.randint(1, 4))
                s_a = max(s_a, current_a_score, random.randint(1, 4))
                sot_h = max(sot_h, current_h_score, random.randint(0, min(s_h, 2)))
                sot_a = max(sot_a, current_a_score, random.randint(0, min(s_a, 2)))

                p_h = result.get("possession_home", 50)
                p_a = result.get("possession_away", 50)
                
                ht_embed.add_field(name="📊 Mevcut İstatistikler", value=get_stats_text(p_h, p_a, s_h, s_a, sot_h, sot_a), inline=False)
                
                if ht_media:
                    self._add_split_fields(embed=ht_embed, name="📰 Soyunma Odası Kulisleri", value=f"\"{ht_media.get('headline', 'Hocalar sinirli!')}\"", inline=False)
                    self._add_split_fields(embed=ht_embed, name=f"🐦 {home_team} Fan", value=pm_media.get('home_fan_tweet', 'İkinci yarı haydi!'), inline=True)
                    self._add_split_fields(embed=ht_embed, name=f"🐦 {away_team} Fan", value=pm_media.get('away_fan_tweet', 'Bastırın!'), inline=True)
                
                ht_embed.set_footer(text=f"🔴 {competition} | Takımlar sahaya dönmek üzere...")
                try:
                    await live_msg.edit(embed=ht_embed)
                except: pass
                
                await asyncio.sleep(12) # HT Mola (12 sn)
                half_time_shown = True
                
                live_embed.description = "🔄 **İKİNCİ YARI BAŞLIYOR!** Hakem düdüğünü çaldı."
                try:
                    await live_msg.edit(embed=live_embed)
                except: pass
                await asyncio.sleep(3)
                
            # Skoru güncelle (GÜVENLİ VE SENKRONİZE LİSTEDEN)
            # Sadece bu dakikada gerçekleşen golleri bul ve skora ekle
            # Bir golün birden fazla kez sayılmaması için kontrol
            for g in result.get("goals", []):
                if g.get("minute") == minute and not g.get("_processed"):
                    g_team_clean = self.clean_tn(g.get("team", ""))
                    # Daha esnek eşleşme: Birbirlerinin içinde geçme durumuna bak
                    is_h = (g_team_clean in home_clean or home_clean in g_team_clean)
                    is_a = (g_team_clean in away_clean or away_clean in g_team_clean)
                    
                    # Eğer isimden bulamadıysa "home/away" veya "ev/dep" anahtar kelimelerine bak
                    if not is_h and not is_a:
                        t_low = g.get("team", "").lower()
                        if any(x in t_low for x in ["home", "ev sahibi", "evsa", "host"]): is_h = True
                        elif any(x in t_low for x in ["away", "deplasman", "dep", "guest"]): is_a = True

                    if is_h:
                        current_h_score += 1
                    elif is_a:
                        current_a_score += 1
                    else:
                        # Son çare: Eğer hala çözemediyse, ev sahibi lehine varsaymak yerine 
                        # AI'nın team_a/team_b ayrımına güvenelim (Eğer home_team literal ise)
                        if g.get("team") == home_team: current_h_score += 1
                        else: current_a_score += 1 # En azından hata payını azaltıyoruz
                        
                    g["_processed"] = True # İşlendi olarak işaretle
            
            ticker.append(f"**{minute}'** {moment['desc']}")
            if len(ticker) > 4: ticker.pop(0)
            
            live_embed.title = f"🏟️ {home_team} {current_h_score} - {current_a_score} {away_team} ({minute}')"
            live_embed.description = "\n\n".join(ticker)
            live_embed.color = 0xf1c40f if (moment["type"] in ["goal", "penalty"]) else 0x95a5a6
                
            try: 
                await live_msg.edit(embed=live_embed)
            except: pass
            
            current_delay = base_delay + random.uniform(-0.5, 1.0)
            if minute > 85: current_delay += 1.0
            await asyncio.sleep(max(1.8, current_delay))
            
        # Maç Sonu
        live_embed.title = f"🏟️ {home_team} {current_h_score} - {current_a_score} {away_team} (MS)"
        live_embed.description = f"🏁 **MAÇ BİTTİ!**\nSon düdük geliyor: **{current_h_score}-{current_a_score}**"
        live_embed.color = 0x2ecc71 if current_h_score == current_a_score else (0x3498db if current_h_score > current_a_score else 0xe74c3c)
        try:
            await live_msg.edit(embed=live_embed)
        except: pass
        await asyncio.sleep(5)
        
        return live_msg

    # --- AUTOMATED CHANNEL UPDATES SYSTEM ---

    def _get_automated_channel(self, guild, search_term: str):
        """Finds a channel that contains the search term in its name (case-insensitive)"""
        if not guild: return None
        search_term = search_term.lower()
        for channel in guild.text_channels:
            if search_term in channel.name.lower():
                return channel
        return None

    async def _edit_or_send_table(self, channel, embed: discord.Embed):
        """Edits the last bot message in a channel or sends a new one to keep tables clean"""
        async for message in channel.history(limit=20):
            if message.author == self.bot.user and message.embeds:
                # Check if this embed has the same title or "Table" signature
                if message.embeds[0].title == embed.title or "TABLO" in (message.embeds[0].title or ""):
                    await message.edit(embed=embed)
                    return
        # If no previous message found, send a new one
        await channel.send(embed=embed)

    async def update_league_channels(self, guild, is_week_end=False):
        """Fully refreshes all league-related channels with current data"""
        if not guild: return

        # 1. PUAN DURUMU (EDIT)
        ch_table = self._get_automated_channel(guild, "puan-durumu")
        if ch_table:
            teams = await database.get_all_teams(league='Super Lig')
            if teams:
                embed = discord.Embed(title="🏆 TÜRKİYE SÜPER LİGİ PUAN DURUMU", color=0xf1c40f, timestamp=datetime.now())
                table_rows = []
                for i, team in enumerate(teams, 1):
                    icon = "🏆" if i == 1 else "🥈" if i == 2 else "🇪🇺" if i <= 4 else "🟢" if i == 5 else "🔴" if i >= 17 else "⚪"
                    av = team["gf"] - team["ga"]
                    av_str = f"+{av}" if av > 0 else str(av)
                    name = team['name'][:18]
                    table_rows.append(f"{icon} `{i:<2}| {name:<20}| {team['played']:>2} | {team['won']:>1}| {team['drawn']:>1}| {team['lost']:>1}| {av_str:>3}| {team['points']:>2}`")
                embed.description = "```text\nS | Takım               | O  | G | B | M | AV | P\n──|─────────────────────|────|───|───|───|────|───```\n" + "\n".join(table_rows)
                embed.set_footer(text="🏆 Şampiyonlar Ligi | 🥈 ŞL Elemeleri | 🇪🇺 Avrupa Ligi | 🟢 Konfederasyon | 🔴 Küme Düşme")
                await self._edit_or_send_table(ch_table, embed)

        # 2. GOL KRALLIĞI (EDIT)
        ch_goals = self._get_automated_channel(guild, "gol-kralligi")
        if ch_goals:
            scorers = await database.get_top_scorers(limit=10, competition='League')
            if scorers:
                embed = discord.Embed(title="👟 TÜRKİYE SÜPER LİGİ - GOL KRALLIĞI", color=0xe74c3c, timestamp=datetime.now())
                scorers_text = ""
                for i, s in enumerate(scorers, 1):
                    icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🎖️"
                    scorers_text += f"{icon} ` {i:>2}. ` **{s['player_name']}**\n┗— 🏟️ `{s['team']}` | ⚽ **{s['goals']} Gol**\n"
                embed.description = scorers_text
                embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/5351/5351505.png")
                await self._edit_or_send_table(ch_goals, embed)

        # 3. ASİST KRALLIĞI (EDIT)
        ch_assists = self._get_automated_channel(guild, "asist-kralligi")
        if ch_assists:
            assists = await database.get_top_assists(limit=10, competition='League')
            if assists:
                embed = discord.Embed(title="🎯 TÜRKİYE SÜPER LİGİ - ASİST KRALLIĞI", color=0x3498db, timestamp=datetime.now())
                assists_text = ""
                for i, a in enumerate(assists, 1):
                    icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "✨"
                    assists_text += f"{icon} ` {i:>2}. ` **{a['player_name']}**\n┗— 🏟️ `{a['team']}` | 🎯 **{a['assists']} Asist**\n"
                embed.description = assists_text
                embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/5351/5351505.png")
                await self._edit_or_send_table(ch_assists, embed)

        # 4. FİKSTÜR (EDIT)
        ch_fix = self._get_automated_channel(guild, "fikstur")
        if ch_fix:
            all_fix = await database.get_fixtures()
            if all_fix:
                # Get latest/current round
                latest_r = await database.get_latest_played_round()
                target_r = latest_r if latest_r > 0 else 1
                round_matches = [f for f in all_fix if f["round_no"] == target_r]
                if round_matches:
                    embed = discord.Embed(title=f"📅 LİG TV | {target_r}. HAFTA PROGRAMI", color=0x3498db, timestamp=datetime.now())
                    match_list = ""
                    for f in round_matches:
                        icon = "✅" if str(f.get("status", "")).strip().lower() == "played" else "🏟️"
                        score = f"**{f.get('home_score', 0)} - {f.get('away_score', 0)}**" if icon == "✅" else "vs"
                        match_list += f"{icon} `{f['home_team']}` {score} `{f['away_team']}`\n"
                    embed.description = match_list
                    await self._edit_or_send_table(ch_fix, embed)

        # 5. CEZALILAR (EDIT)
        ch_susp = self._get_automated_channel(guild, "cezalı-oyuncu")
        if ch_susp:
            async with database.get_db() as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT name, team, yellow_cards, suspension_matches FROM players WHERE suspension_matches > 0 OR yellow_cards % 4 == 3 ORDER BY team ASC") as cursor:
                    all_p = [dict(row) for row in await cursor.fetchall()]
            if all_p:
                embed = discord.Embed(title="⚖️ Süper Lig - Ceza & Kart Raporu", color=0x9b59b6, timestamp=datetime.now())
                susp_text = ""
                for p in all_p:
                    status = f"❌ {p['suspension_matches']} MAÇ" if p["suspension_matches"] > 0 else "🟨 SINIRDA"
                    susp_text += f"• **{p['name']}** ({p['team']}) - {status}\n"
                embed.description = susp_text
                await self._edit_or_send_table(ch_susp, embed)

        # 6. HABERLER / PANORAMA (NEW MESSAGE) - DISABLED AS PER USER REQUEST
        # ch_news = self._get_automated_channel(guild, "haberler")
        # if ch_news:
        #     if is_week_end:
        #         # Send Full Panorama as a new message
        #         latest_r = await database.get_latest_played_round()
        #         if latest_r > 0:
        #             # Capture current context to simulate for panorama_command
        #             class FakeCtx:
        #                 def __init__(self, guild, author, bot, channel):
        #                     self.guild = guild
        #                     self.author = author
        #                     self.bot = bot
        #                     self.channel = channel
        #                 async def send(self, *args, **kwargs):
        #                     return await self.channel.send(*args, **kwargs)
        #                 async def invoke(self, *args, **kwargs): pass
        #             
        #             await self.panorama_command.callback(self, FakeCtx(guild, guild.me, self.bot, ch_news), round_no=latest_r)
        #     else:
        #         # For single match, optionally send a "Flash News"
        #         if self.last_match_result:
        #             res = self.last_match_result
        #             embed = discord.Embed(
        #                 title=f"🗞️ FLAŞ HABER: {res['home_team']} vs {res['away_team']}",
        #                 description=f"**SKOR:** {res['home_score']} - {res['away_score']}\n\nMaçın ardından tüm istatistikler güncellendi. Detaylı analizler haber kanalımızda!",
        #                 color=0xe67e22
        #             )
        #             await ch_news.send(embed=embed)


    def _format_match_result(self, result: Dict, competition: str = "League") -> List[discord.Embed]:
        """Format match result as a list of Discord Embeds for a premium look"""
        import discord
        
        home_team = result.get("home_team", "Ev Sahibi")
        away_team = result.get("away_team", "Deplasman")
        home_score = result.get("home_score", 0)
        away_score = result.get("away_score", 0)
        
        # Maç sonucuna göre renk seçimi
        embed_color = 0x2ecc71 # Yeşil (Beraberlik)
        if home_score > away_score: embed_color = 0x3498db # Mavi (Ev Sahibi Galip)
        elif away_score > home_score: embed_color = 0xe74c3c # Kırmızı (Deplasman Galip)
        
        # Turnuva detayı (Aggregate)
        agg_text = ""
        is_tournament = result.get("is_tournament", False)
        if is_tournament:
            leg = result.get("leg", 1)
            agg_context = result.get("agg_context")
            if leg == 2 and agg_context:
                agg_text = f"\n📊 **Toplam Skor:** {agg_context.get('total_home', 0)} - {agg_context.get('total_away', 0)}"
        
        # 1. ANA EMBED: Skor ve Temel İstatistikler
        main_title = f"🏟️ {home_team} {home_score} - {away_score} {away_team}"
        if getattr(result, "is_trial", False) or "Hazirlik" in competition or "Hazırlık" in competition:
             main_title = "🧪 [DENEME MAÇI] " + main_title

        main_embed = discord.Embed(
            title=main_title,
            description=f"🏆 **{competition}** | 🌤️ {result.get('weather', 'Açık')}{agg_text}\n"
                        f"🏁 **Hakem:** {result.get('referee_name', 'Bilinmiyor')}\n" + "─" * 20,
            color=embed_color
        )
        
        # Goller (Ayrı bir alan)
        goals = result.get("goals", [])
        if goals:
            goal_list = []
            for g in goals:
                emoji = {"penalty": "🎯", "free_kick": "📍", "own_goal": "❌"}.get(g.get("type", "regular"), "⚽")
                assist_txt = f" (Asist: **{g.get('assist')}**)" if g.get("assist") and str(g.get("assist")).lower() != "none" else ""
                goal_list.append(f"**{g['minute']}'** {emoji} {g.get('player', 'Bilinmeyen')} ({g['team']}){assist_txt}")
            self._add_split_fields(embed=main_embed, name="⚽ GOLLER", value="\n".join(goal_list), inline=False)
        else:
            main_embed.add_field(name="⚽ GOLLER", value="*Gol sesi çıkmadı.*", inline=False)

        # Kırmızı Kartlar (Varsa göster)
        red_cards = [e for e in result.get("events", []) if e.get("type") == "red_card"]
        if red_cards:
            rc_list = [f"**{rc['minute']}'** 🟥 {rc.get('player', 'Bilinmeyen')} ({rc['team']})" for rc in red_cards]
            main_embed.add_field(name="🟥 KIRMIZI KARTLAR", value="\n".join(rc_list), inline=False)

        # İstatistikler (Yan yana)
        main_embed.add_field(
            name="📊 İSTATİSTİKLER", 
            value=f"**Topla Oynama:** %{result.get('possession_home', 50)} - %{result.get('possession_away', 50)}\n"
                  f"**Şut (İsabet):** {result.get('shots_home', 0)}({result.get('shots_on_target_home', 0)}) - {result.get('shots_away', 0)}({result.get('shots_on_target_away', 0)})",
            inline=False
        )

        # UZATMALAR VE PENALTILAR (YENİ)
        if result.get("is_extra_time"):
            et_score = result.get("extra_time_score", "0-0")
            main_embed.add_field(name="⏰ UZATMALAR", value=f"Uzatma Sonucu: **{et_score}**", inline=False)
            
            penalties = result.get("penalties", [])
            if penalties:
                pen_text = ""
                for p in penalties:
                    emoji = "✅" if p["result"] == "scored" else "❌"
                    pen_text += f"{p['team']} | {p['player']} | {emoji}\n"
                self._add_split_fields(embed=main_embed, name="🥅 PENALTI ATIŞLARI", value=f"```{pen_text}```", inline=False)

        # TUR ATLAYAN (Prominent)
        # Sadece Kupa veya Turnuva maçlarında göster (Lig veya Hazırlık maçlarında gösterme)
        skip_advancing = any(x in (competition or "Normal").lower() for x in ["lig", "hazirlik", "hazırlık", "league", "deneme"])
        if result.get("final_winner") and not skip_advancing:
            winner_name = result["final_winner"]
            is_final = result.get("round", "").lower() == "final"
            field_name = "👑 ŞAMPİYON" if is_final else "👑 TUR ATLAYAN"
            
            # Ana embed açıklamasının tepsine ekle veya ayrı bir alan yap
            main_embed.description = f"🎉 **{winner_name} {field_name.split()[-1].lower()}!**\n" + main_embed.description
            main_embed.add_field(name=field_name, value=f"🏆 **{winner_name}**", inline=False)

        # 2. OLAYLAR EMBED
        events_embed = discord.Embed(title="🎬 Maçın Hikayesi (Genel Olaylar)", color=embed_color)
        
        all_events = []
        for i, e in enumerate(result.get("events", [])):
            etype = e.get("type", "")
            emoji = self._get_event_emoji(etype, i)
            all_events.append({"minute": e["minute"], "emoji": emoji, "desc": e.get("description", "")})
            
        all_events.sort(key=lambda x: x["minute"])
        
        event_text = ""
        for e in all_events:
            line = f"**{e['minute']}'** {e['emoji']} {e['desc']}\n\n"
            if len(event_text) + len(line) < 3800: # Embed açıklama sınırı
                event_text += line
        
        events_embed.description = event_text if event_text else "*Maçta kayda değer başka olay yaşanmadı.*"
        
        # 2.5 VAR OLAYLARI (YENİ)
        var_events = result.get("var_events", [])
        if var_events:
            var_text = "\n".join([f"📺 **VAR:** {e}" for e in var_events])
            self._add_split_fields(embed=events_embed, name="🖥️ VAR İNCELEMELERİ", value=var_text, inline=False)

        # 3. ANALİZ VE MOTM EMBED
        analysis_embed = discord.Embed(title="📋 Teknik Analiz & Maç Sonu", color=embed_color)
        
        # Dizilişler
        analysis_embed.add_field(name="🎮 Dizilişler", value=f"🏠 {home_team}: {result.get('formation_a', '4-4-2')}\n🚌 {away_team}: {result.get('formation_b', '4-4-2')}", inline=True)
        
        # GPR & OVR Detaylı (Analizden gelen veriler)
        # Always define apr_h/apr_a first so footer never gets a NameError
        apr_h = result.get('apr_home', 0)
        apr_a = result.get('apr_away', 0)
        pm_stats = result.get("pre_match_stats")
        if pm_stats:
            h = pm_stats.get("home", {})
            a = pm_stats.get("away", {})
            analysis_embed.add_field(
                name="📊 GÜÇ KIYASLAMASI (ANALİZ)",
                value=f"🏠 **{home_team}**: OVR `{h.get('ovr',0)}` | GPR `{h.get('gpr',0)}` | Tactic `+{h.get('boost',0)}`\n"
                      f"🚌 **{away_team}**: OVR `{a.get('ovr',0)}` | GPR `{a.get('gpr',0)}` | Tactic `+{a.get('boost',0)}`",
                inline=False
            )
        else:
            analysis_embed.add_field(
                name="⚖️ Performans Reytingleri (GPR)", 
                value=f"🏠 **{home_team}:** {apr_h}\n🚌 **{away_team}:** {apr_a}", 
                inline=True
            )

        # Maçın Adamı
        motm = result.get("motm", {})
        rating = motm.get("rating", 0)
        stars = "⭐" * int(rating / 2) if rating > 0 else "⭐⭐⭐⭐"
        analysis_embed.add_field(name="🏆 Maçın Adamı", value=f"**{motm.get('player', 'Bilinmeyen')}** ({motm.get('team', '')})\nReyting: {rating}/10 {stars}", inline=True)

        # KADRO DEĞERİ KIYASLAMASI (YENİ)
        val_a = result.get("value_a", 0.0)
        val_b = result.get("value_b", 0.0)
        if val_a > 0 or val_b > 0:
            diff = val_a - val_b
            diff_str = f"+{diff:.1f}" if diff > 0 else f"{diff:.1f}"
            comparison_text = f"🏠 **Ev Sahibi:** {val_a:.1f} M €\n🚌 **Deplasman:** {val_b:.1f} M €\n📊 **Fark:** {diff_str} M €"
            analysis_embed.add_field(name="💰 Kadro Değeri Kıyaslaması", value=comparison_text, inline=False)
        
        # Alt bilgi
        footer_text = f"⚖️ GPR: {apr_h} - {apr_a}"
        if "match_temperament" in result:
            footer_text += f" | 🎭 Mizaç: {result['match_temperament']} | 🔥 Kaos: {result.get('chaos_level', 0)}/10"
        analysis_embed.set_footer(text=footer_text)

        return [main_embed, events_embed, analysis_embed]

    def _format_media_reactions(self, match_result: Dict) -> discord.Embed:
        """Format media reactions generated by the AI (now offloaded to Gemma)"""
        media = match_result.get("media_reactions", {})
        
        embed = discord.Embed(title="📱 Sosyal Medya ve Basın", color=0x95a5a6)
        
        # Manşet
        self._add_split_fields(embed=embed, name="📰 BASIN MANŞETİ", value=f"📌 **{media.get('headline', 'Müthiş Mücadele!')}**", inline=False)
        
        # Teknik Direktörler
        h_hoca = media.get('home_manager_quote', 'Maç bitti.')
        a_hoca = media.get('away_manager_quote', 'İyi oynadık.')
        self._add_split_fields(
            embed=embed,
            name="🎤 TEKNİK DİREKTÖR AÇIKLAMALARI", 
            value=f"🏠 **{match_result.get('home_team')}:** \"{h_hoca}\"\n"
                  f"🚌 **{match_result.get('away_team')}:** \"{a_hoca}\"", 
            inline=False
        )
        
        # Taraftar Tweetleri
        all_fans = media.get("fan_comments_home", []) + media.get("fan_comments_away", [])
        if all_fans:
            fan_text = "\n".join([f"💬 {c}" for c in all_fans[:4]])
            self._add_split_fields(embed=embed, name="📣 TARAFTAR REAKSİYONLARI", value=fan_text, inline=False)
            
        return embed

    def _format_fizio_romano_tweet(self, match_result: Dict) -> discord.Embed:
        """Format a separate tweet-styled embed for Fizio Romano"""
        media = match_result.get("media_reactions", {})
        tweet_content = media.get("fizio_romano_news", "Maç sonrası sıcak gelişmeler bekleniyor... #BreakingNews")
        
        # Twitter Blue Color: 0x1DA1F2
        embed = discord.Embed(
            description=f"🚨 **#BreakingNews**\n\n{tweet_content}",
            color=0x1DA1F2
        )
        
        embed.set_author(name="Fizio Romano 🐦 (@FizioRomano)", icon_url="https://i.imgur.com/G5iU7Bf.png") 
        embed.set_footer(text="Twitter / X Platformu • Az önce • 🚨 HERE WE GO!")
        
        return embed

    async def _generate_media_reactions(self, match_result: Dict) -> Dict:
        """Uses Google Gemini (Gemma 3-27B) to generate media buzz and Fizio Romano tweets"""
        
        # Maç özetini referans alarak sosyal medya reaksiyonları üret
        summary = match_result.get('second_half_summary', '')
        
        prompt = f"""
Maç Sonucu: {match_result.get('home_team')} {match_result.get('home_score')} - {match_result.get('away_score')} {match_result.get('away_team')}
Önem: {match_result.get('importance', 'Normal')} | Kazanan: {match_result.get('final_winner', 'Yok')}
Maç Özeti: {summary}

=== GÜNCEL KADROLAR (BURADAKİ İSİMLERİ KULLAN) ===
Ev Sahibi ({match_result.get('home_team')}): {match_result.get('squad_a', 'Bilinmiyor')}
Deplasman ({match_result.get('away_team')}): {match_result.get('squad_b', 'Bilinmiyor')}

Sen profesyonel bir Türk spor medyası ve sosyal medya analistisin. 
DİKKAT: ŞU ANKİ TARİH 1 NİSAN 2026. BÜTÜN DÜNYA FUTBOLU 2026 SEZONUNDADIR!
Yukarıdaki maç sonucuna ve özete göre; çarpıcı gazete manşetleri, teknik direktör açıklamaları ve taraftar tweetleri üretmelisin.
ÖZELLİKLE: 'Fizio Romano' (@FabrizioRomano) üslubuyla bir 'HERE WE GO!' haberi eklerken SADECE yukarıda verilen GÜNCEL KADROLARDAKİ oyuncuları kullan. 2024 veya öncesinden kalma eski isimleri veya rastgele oyuncuları uydurma. 2026 dünyasındayız!

SADECE aşağıdaki JSON formatında bir cevap ver:
{{
    "headline": "Fanatik/Fotomaç stili ÇARPICI ve AGRESİF bir manşet.",
    "fizio_romano_news": "Fizio Romano üslubuyla; transfer dedikodusu veya kulüp kaosu. 'HERE WE GO!' mutlaka geçsin.",
    "home_manager_quote": "Ev sahibi teknik direktörün açıklaması.",
    "away_manager_quote": "Deplasman teknik direktörün açıklaması.",
    "fan_comments_home": ["Ev sahibi taraftar tweeti 1", "Ev sahibi taraftar tweeti 2"],
    "fan_comments_away": ["Deplasman taraftar tweeti 1", "Deplasman taraftar tweeti 2"]
}}
"""
        # --- AI GENERATION WITH 3-TIER CASCADE ---
        result = await ai.generate_content(
            prompt=prompt,
            system="Sen profesyonel bir Türk spor medyası ve sosyal medya analistisin. SADECE JSON formatında cevap ver.",
            temp=0.8,
            is_json=True,
            label=f"Media: {match_result.get('home_team', 'H')} - {match_result.get('away_team', 'A')}",
            attempts=1,
            timeout=30,
            provider="groq"
        )
        
        if result:
            return result
            
        # Fallback (Eğer AI patlarsa)
        return {
            "headline": f"{match_result.get('home_team')} vs {match_result.get('away_team')} Maçı Tamamlandı!",
            "fizio_romano_news": "Maç sonrası sıcak gelişmeler bekleniyor... #BreakingNews",
            "home_manager_quote": "İyi mücadele ettik.",
            "away_manager_quote": "Önümüzdeki maçlara bakacağız.",
            "fan_comments_home": ["Güzel maç oldu."],
            "fan_comments_away": ["Tebrikler."]
        }

    async def _get_tactical_scores(self, home_team: str, home_tactics: str, away_team: str, away_tactics: str) -> Dict[str, Any]:
        """Evaluates tactics using AI and returns scores from 0 to 6."""
        prompt = f"""
Saha Kenarı Taktiksel Analiz Müellifi olarak görevlendirildin.
Aşağıda iki takımın maç öncesi sunduğu detaylı taktik/kadro metinleri yer alıyor.

🏠 Ev Sahibi ({home_team}):
{home_tactics[:2000]}

🚌 Deplasman ({away_team}):
{away_tactics[:2000]}

GÖREV: Bu taktiklerin 'derinliğini', 'gerçekçiliğini', 'stratejik tutarlılığını' ve 'detay seviyesini' analiz et. 
KRİTİK KURAL: Eğer bir takımın metni SADECE kadrodan (oyuncu isimleri, mevkiler, değerler vb.) ibaretse ve hiçbir detaylı taktiksel felsefe, maç içi senaryo veya doktrin içermiyorsa, o takıma KESİNLİKLE TAM OLARAK 4 puan vermelisin! 3 veya 5 puan verilmemelidir.
ÖZELLİKLE: 'Positional Play', 'Zonal Overload', 'Geri Dönüş Senaryoları' gibi detaylı oyun kurallarını, harika oyuncu tanımlamalarını ve detaylı felsefeleri içeren GERÇEK Taktik Doktrinlerine ise 5, 6 veya 7 puan vermekten çekinme.

SADECE aşağıdaki JSON formatında cevap ver:
{{
  "home_tactical_score": [0-7],
  "away_tactical_score": [0-7],
  "reasoning_short": "Kısa bir gerekçe (max 15 kelime)"
}}
"""
        result = await ai.generate_content(
            prompt=prompt,
            system="Sen profesyonel bir futbol taktik analistisin. SADECE JSON formatında cevap ver.",
            temp=0.4,
            is_json=True,
            label=f"Tactical Analysis: {home_team} vs {away_team}",
            attempts=1,
            timeout=25,
            provider="auto"
        )
        
        if result:
            try:
                return {
                    "home": min(7, max(0, int(result.get("home_tactical_score", 0)))),
                    "away": min(7, max(0, int(result.get("away_tactical_score", 0)))),
                    "reason": result.get("reasoning_short", "Analiz tamamlandı.")
                }
            except:
                pass
        
        return {"home": 0, "away": 0, "reason": "Analiz başarısız."}

    async def _smart_parse_match_query(self, query: str) -> tuple:
        """
        Smartly parse the match command query to extract home team, away team, 
        importance, weather AND live flag.
        
        Example: "Real Madrid Beşiktaş Derby Rain Live" 
        -> ("Real Madrid", "Beşiktaş", "Derby", "Rain", True)
        """
        if not query:
            return None, None, "Normal", "Clear", False

        # 1. Temizleme
        query = query.strip()
        if query.lower().startswith("!mac "):
            query = query[5:].strip()

        # 1.5 Turnuva anahtarlarını takım adından ayır (WORLD_CUP, UCL, UEL, UECL vb.)
        # Not: Bu fonksiyon "competition" döndürmüyor; sadece team_name'a yapışmasını engelliyoruz.
        tournament_tokens = {
            "WORLD_CUP", "WORLDCUP", "WORLD", "WC",
            "UCL", "UEL", "UECL", "UWCL",
        }
        found_tournament_token = None
        query_words = [w.strip(",. ") for w in query.split() if w.strip(",. ")]
        filtered = []
        for w in query_words:
            if w.upper() in tournament_tokens:
                found_tournament_token = w.upper()
                continue
            filtered.append(w)
        query = " ".join(filtered)
        
        # 2. Anahtar kelimeler
        importance_keywords = [
            "Normal", "Derby", "Final", "Kritik", "Dostluk", "Kupa", "Derbi", "Süper Kupa", 
            "Friendly", "Lig", "League", "UEL", "UCL", "UECL", "UWCL", "Avrupa", "Europe", 
            "Champions League", "Europa League", "Konferans", "Conference", "Uluslararası", 
            "International", "Milli", "World Cup", "Euro", "Hazırlık"
        ]
        weather_keywords = ["Clear", "Rain", "Snow", "Cloudy", "Rainy", "Snowy", "Windy", "Wind", "Açık", "Yağmurlu", "Karlı", "Bulutlu", "Güneşli", "Sunny"]
        live_keywords = ["Live", "Canlı", "Canli"]
        league_keywords = ["Lig", "League"]
        is_live = False

        # Default importance from token if found
        importance = found_tournament_token if found_tournament_token else "Normal"
        
        # 3. Ayraç Kontrolü (vs, -, v)
        separators = [r"\s+vs\s+", r"\s*-\s*", r"\s*–\s*", r"\s*—\s*", r"\s+v\s+"]
        for sep in separators:
            parts = re.split(sep, query, flags=re.IGNORECASE)
            if len(parts) >= 2:
                home_team = parts[0].strip()
                rest = " ".join(parts[1:]).strip()
                
                # 'rest' içinden önem/hava ayıklama
                rest_words = rest.split()
                away_team_words = []
                # importance already has default from token
                weather = "Clear"
                
                for word in rest_words:
                    word_clean = word.strip(",. ")
                    if any(word_clean.lower() == k.lower() for k in importance_keywords):
                        importance = word_clean.capitalize()
                    elif any(word_clean.lower() == k.lower() for k in weather_keywords):
                        weather = word_clean.capitalize()
                    elif any(word_clean.lower() == k.lower() for k in live_keywords):
                        is_live = True
                    elif word_clean.upper() in tournament_tokens:
                        # ignore tournament tokens if user wrote them after team
                        continue
                    else:
                        away_team_words.append(word)
                
                away_team = " ".join(away_team_words)
                return home_team, away_team, importance, weather, is_live

        # 4. Ayraç yoksa Heuristic Split
        words = query.split()
        if len(words) < 2:
            return query, None, "Normal", "Clear", is_live
            
        # Sondan başlayarak keywords ayıkla
        # importance already has default from token
        weather = "Clear"
        
        # En fazla son 3 kelimeye bak (örneğin: Lig Rainy Live)
        for _ in range(4):
            if not words: break
            last_word = words[-1].strip(",. ").lower()
            if any(last_word == k.lower() for k in ["Derbi", "Derby", "Normal", "Kritik", "Klasik", "Hazırlık", "Hazirlik", "Friendly", "UCL", "UEL", "UECL", "WORLD_CUP", "WORLD CUP"]):
                importance = words.pop().capitalize()
            elif any(last_word == k.lower() for k in ["Clear", "Sunny", "Rainy", "Snowy", "Cloudy"]):
                weather = words.pop().capitalize()
            elif any(last_word == k.lower() for k in ["Live", "Canlı", "Canli"]):
                is_live = True
                words.pop()
            elif any(last_word == k.lower() for k in ["Lig", "League"]):
                # 'Lig' kelimesini önem derecesine ata ama takımdan çıkar
                importance = "Lig"
                words.pop()
            else:
                break
        
        if len(words) < 2:
            return " ".join(words), None, importance, weather, is_live

        # 5. En iyi bölme noktasını bul (Bilinen Takımlara Göre)
        max_score = -1
        best_split = len(words) // 2
        
        for i in range(1, len(words)):
            team_a_name = " ".join(words[:i])
            team_b_name = " ".join(words[i:])
            
            score = 0
            # Takım A Kontrolü
            match_a = await self._find_team(team_a_name)
            if match_a:
                if match_a['name'].lower() == team_a_name.lower(): score += 15 
                else: score += 5 
            
            # Takım B Kontrolü
            match_b = await self._find_team(team_b_name)
            if match_b:
                if match_b['name'].lower() == team_b_name.lower(): score += 15
                else: score += 5
                
            if score > max_score:
                max_score = score
                best_split = i
        
        home_team = " ".join(words[:best_split])
        away_team = " ".join(words[best_split:])
        return home_team, away_team, importance, weather, is_live

    async def _get_squad_data(self, team_name: str, lineup_text: str) -> tuple[float, float]:
        """Kadro metninden veya DB'den EN İYİ 18 oyuncunun OVR ortalamasını VE Toplam PD'sini hesaplar"""
        import re
        all_players = [] # List of (ovr, mv) tuples

        # 1. Veritabanından Oyuncuları Oku (Sadece TAM EŞLEŞME ve CEZALI OLMAYANLAR)
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            # Takımın oyuncularını çek (LIKE yerine TAM EŞLEŞME - v6)
            async with db.execute(
                "SELECT overall, market_value FROM players WHERE LOWER(team) = LOWER(?) AND suspension_matches = 0", 
                (team_name,)
            ) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    if row["overall"]:
                        mv_str = str(row["market_value"] or "0")
                        mv_int = database.parse_market_value(mv_str)
                        all_players.append((int(row["overall"]), mv_int))
        
        if not all_players:
            return 0.0, 0.0

        # EN DEĞERLİ 18 OYUNCU MANTIĞI:
        # İndex'e göre değil, OVR'ye göre sırala (Global Reset Fix)
        all_players.sort(key=lambda x: x[0], reverse=True)
        
        # İlk 11 (As Kadro)
        top_11 = all_players[:11]
        while len(top_11) < 11:
            top_11.append((70, 0)) # Eksikse 70 OVR / 0 PD tamamla
            
        # Sonraki 7 (Yedekler)
        next_7 = all_players[11:18]
        while len(next_7) < 7:
            next_7.append((70, 0))
            
        # Ağırlıklı OVR Ortalama: İlk 11 %80, Yedekler %20
        avg_11_ovr = sum(p[0] for p in top_11) / 11
        avg_7_ovr = sum(p[0] for p in next_7) / 7
        final_ovr = (avg_11_ovr * 0.8) + (avg_7_ovr * 0.2)

        # Toplam Değer (Milyon € cinsinden)
        total_mv = sum(p[1] for p in top_11) + sum(p[1] for p in next_7)
        final_val_m = total_mv / 1_000_000.0

        return round(final_ovr, 1), round(final_val_m, 1)

    @commands.command(name="mac", aliases=["maç", "match"])
    async def mac_command(self, ctx: commands.Context, *, query: str = None):
        """
        Iki takim arasinda detayli mac simule et (Admin Only)
        Kullanim: !mac [Takim A] vs [Takim B] [onem] [hava]
        """
        def format_currency(val_m):
            if val_m >= 1000: return f"{val_m/1000.0:.2f}B €"
            return f"{val_m:.1f}M €"
        # Trial maçı değilse ve admin değilse engelle
        is_trial = getattr(ctx, "is_trial", False)
        if not is_trial and not ctx.author.guild_permissions.administrator:
            raise commands.MissingPermissions(["administrator"])

        if not query:
            await ctx.send(
                "❌ **Eksik bilgi!**\n\n"
                "**Kullanım:** `!mac [Takım A] vs [Takım B] [Önem] [Hava]`\n"
                "**İpucu:** Kelime sayısı fazlaysa araya `vs` veya `-` koyabilirsin.\n\n"
                "**Örnekler:**\n"
                "`!mac Galatasaray Fenerbahçe Derby Clear`\n"
                "`!mac Real Madrid - Beşiktaş Normal Rain`\n\n"
                "📁 **Taktik + İlk 11 dosyalarını (.txt) mesaja ekleyebilirsin!**"
            )
            return

        # Detect tournament tokens before smart-parse strips them from team names
        q_upper = (query or "").upper()
        is_world_cup = any(tok in q_upper for tok in ["WORLD_CUP", "WORLDCUP", "WORLD CUP", "WC"])

        team_a, team_b, importance, weather, is_live = await self._smart_parse_match_query(query)

        # --- Resolve Canonical Names Early ---
        team_a = await database.resolve_canonical_team(team_a)
        team_b = await database.resolve_canonical_team(team_b)

        # Eklentileri kontrol et
        txt_files = [att for att in ctx.message.attachments if att.filename.endswith('.txt')]

        team_a_data = await self._find_team(team_a)
        team_b_data = await self._find_team(team_b)

        if not team_a_data:
            team_a_data = {"name": team_a.title(), "is_external": True}
        else:
            # Check if squad is empty (even if team exists in DB)
            async with aiosqlite.connect(database.DB_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM players WHERE LOWER(team) LIKE ?", (f"%{team_a_data['name'][:5].lower()}%",)) as cursor:
                    p_count = (await cursor.fetchone())[0]
                    if p_count < 5: # If very few or no players, treat as external for research
                        team_a_data["is_external"] = True

        if not team_b_data:
            team_b_data = {"name": team_b.title(), "is_external": True}
        else:
            # Check if squad is empty (even if team exists in DB)
            async with aiosqlite.connect(database.DB_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM players WHERE LOWER(team) LIKE ?", (f"%{team_b_data['name'][:5].lower()}%",)) as cursor:
                    p_count = (await cursor.fetchone())[0]
                    if p_count < 5: # If very few or no players, treat as external for research
                        team_b_data["is_external"] = True

        # --- GÜVENLİK KİLİDİ ---
        fixture = await self._find_fixture(team_a_data['name'], team_b_data['name'])
        if not is_trial:
            latest_round = await database.get_latest_played_round()
            
            # TURNUVA KONTROLÜ (Kilidi kırmak için)
            is_explicit_tournament = any(kw in (importance or "Normal").upper() for kw in ["UCL", "UEL", "UECL", "AVRUPA", "KUPA"])
            
            if fixture and not is_explicit_tournament:
                round_no = fixture.get("round_no", 0)
                if round_no > latest_round + 1:
                    await ctx.send(
                        f"⚠️ **DUR! GÜVENLİK KİLİDİ DEVREDE!**\n\n"
                        f"Şu an lig **{latest_round}. haftada.** Oynamaya çalıştığın maç **{round_no}. haftaya** ait.\n"
                        f"Lütfen sırayla ilerle veya bu maçı hazırlık maçı (`!hazirlik`) olarak yap."
                    )
                    return
            
        # --- TURNUVA ANALİZİ ---
        is_tourney = getattr(ctx, "is_tournament", False)
        t_fixture = getattr(ctx, "tournament_fixture", None)
        agg_ctx = getattr(ctx, "agg_context", None)
        comp_name = getattr(ctx, "competition_name", importance)
        if is_world_cup:
            comp_name = "WORLD_CUP"
        t_id = None
        t_round = None
        
        # BUG FIX: Eğer bir LİG FİKSTÜRÜ (fixture) zaten bulunmuşsa, turnuva araması yapma.
        if not is_tourney and not is_trial and not fixture:
            t_keywords = ["UCL", "UEL", "UECL", "WORLD_CUP"]
            found_t = "WORLD_CUP" if is_world_cup else next((k for k in t_keywords if k in (importance or "Normal").upper()), None)

            async def _try_bind_tournament_fixture(tournament_key: str) -> bool:
                nonlocal is_tourney, t_fixture, t_id, t_round, comp_name, agg_ctx
                t_id_found = await database.get_tournament_by_name(tournament_key)
                if not t_id_found:
                    return False
                async with aiosqlite.connect(database.DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        """
                        SELECT * FROM tournament_fixtures
                        WHERE tournament_id = ? AND status = 'Pending'
                          AND (
                                (REPLACE(LOWER(home_team), '-', ' ') = REPLACE(LOWER(?), '-', ' ') AND REPLACE(LOWER(away_team), '-', ' ') = REPLACE(LOWER(?), '-', ' '))
                             OR (REPLACE(LOWER(home_team), '-', ' ') = REPLACE(LOWER(?), '-', ' ') AND REPLACE(LOWER(away_team), '-', ' ') = REPLACE(LOWER(?), '-', ' '))
                          )
                        ORDER BY id ASC LIMIT 1
                        """,
                        (t_id_found, team_a_data["name"], team_b_data["name"], team_b_data["name"], team_a_data["name"]),
                    ) as cursor:
                        row = await cursor.fetchone()
                if not row:
                    return False

                is_tourney = True
                t_fixture = dict(row)
                t_id = t_id_found
                t_round = t_fixture["round"]
                comp_name = tournament_key

                agg_ctx = await database.get_aggregate_score(t_id, t_fixture["round"], team_a_data["name"], team_b_data["name"])
                if agg_ctx:
                    agg_ctx["first_leg_score"] = f"{agg_ctx.get(team_a_data['name'], 0)}-{agg_ctx.get(team_b_data['name'], 0)}"
                return True

            # 1) Kullanıcı açıkça turnuva anahtarı verdiyse önce onu dene
            if found_t:
                await _try_bind_tournament_fixture(found_t)

            # 2) Kullanıcı turnuva anahtarını yazmayı unutmuş olabilir.
            #    Eğer lig fikstürü yoksa ve hala turnuvaya bağlanmadıysak:
            #    - Aynı iki takım için *tek* bir pending turnuva fikstürü varsa ona bağlan.
            #    - Birden fazla varsa ve WORLD_CUP varsa onu tercih et (en yaygın senaryo).
            if not is_tourney:
                async with aiosqlite.connect(database.DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        """
                        SELECT tf.*, t.name as tournament_name
                        FROM tournament_fixtures tf
                        JOIN tournaments t ON t.id = tf.tournament_id
                        WHERE tf.status = 'Pending'
                          AND (
                                (LOWER(tf.home_team) = LOWER(?) AND LOWER(tf.away_team) = LOWER(?))
                             OR (LOWER(tf.home_team) = LOWER(?) AND LOWER(tf.away_team) = LOWER(?))
                          )
                        ORDER BY tf.id ASC
                        """,
                        (team_a_data["name"], team_b_data["name"], team_b_data["name"], team_a_data["name"]),
                    ) as cursor:
                        candidates = [dict(r) for r in await cursor.fetchall()]

                if len(candidates) >= 1:
                    # Birden fazla aday varsa (rövanşlı maçlar), ilk bekleyen maçı seç (Leg 1 -> Leg 2)
                    row = candidates[0]
                    is_tourney = True
                    t_fixture = row
                    t_id = row["tournament_id"]
                    t_round = row["round"]
                    comp_name = row.get("tournament_name") or comp_name
                    agg_ctx = await database.get_aggregate_score(t_id, t_round, team_a_data["name"], team_b_data["name"])
                    if agg_ctx:
                        agg_ctx["first_leg_score"] = f"{agg_ctx.get(team_a_data['name'], 0)}-{agg_ctx.get(team_b_data['name'], 0)}"
                        comp_name = "WORLD_CUP"
                        agg_ctx = await database.get_aggregate_score(t_id, t_round, team_a_data["name"], team_b_data["name"])
                        if agg_ctx:
                            agg_ctx["first_leg_score"] = f"{agg_ctx.get(team_a_data['name'], 0)}-{agg_ctx.get(team_b_data['name'], 0)}"
        else:
            # Turnuva ID'sini bul (Daha esnek arama: 'UEL - Yarı Final' -> 'UEL')
            search_name = comp_name
            t_keywords = ["UCL", "UEL", "UECL", "WORLD_CUP"]
            for kw in t_keywords:
                if kw in (comp_name or "Normal").upper():
                    search_name = kw
                    break
            
            t_id = await database.get_tournament_by_name(search_name)
            t_round = t_fixture['round'] if t_fixture else None

        # Bekleme mesajı erken atılır çünkü arama uzun sürebilir
        # Bekleme mesajı (Premium Embed)
        load_embed = discord.Embed(
            title="🏟️ Maç Günü Hazırlıkları",
            description=f"⚔️ **{team_a_data['name']} vs {team_b_data['name']}**\n\n"
                        f"🔄 **Durum:** Taktikler ve kadrolar inceleniyor...\n"
                        f"⏳ _AI simülasyonu 10-30 saniye sürebilir._",
            color=0x2b2d31
        )
        load_embed.set_footer(text="Premium Match Engine v4.0 • AI-Powered Narrative")
        wait_msg = await ctx.send(embed=load_embed)
        
        external_squad_a = ""
        external_value_a = 0.0
        external_ovr_a = 0
        external_squad_b = ""
        external_value_b = 0.0
        external_ovr_b = 0

        if team_a_data.get("is_external"):
            external_squad_a, external_value_a, external_ovr_a = await self._get_external_squad(team_a_data['name'])
        if team_b_data.get("is_external"):
            external_squad_b, external_value_b, external_ovr_b = await self._get_external_squad(team_b_data['name'])

        # Taktik ve kadro dosyalarını oku
        team_a_tactics = ""
        team_b_tactics = ""
        lineup_a = ""
        lineup_b = ""
        value_a = external_value_a
        value_b = external_value_b
        rating_a = 0.0
        rating_b = 0.0

        if txt_files:
            parsed_files = []
            for file in txt_files:
                await file.seek(0)
                content = await file.read()
                file_text = content.decode('utf-8')
                filename_lower = file.filename.lower()
                tactics_part, lineup_part, value_part, rating_part = self._parse_tactic_file(file_text)
                parsed_files.append({"filename": filename_lower, "tactics": tactics_part, "lineup": lineup_part, "value": value_part, "rating": rating_part})

            # Normalizasyon fonksiyonu (ç -> c, ş -> s vb.)
            def normalize(s):
                s = s.lower().strip()
                translation = str.maketrans("çğıöşü", "cgiosu")
                return s.translate(translation)

            # Dosya adına göre eşleştir (Çok daha esnek ve akıllı)
            for pf in parsed_files:
                norm_filename = normalize(pf["filename"])
                norm_team_a = normalize(team_a)
                norm_team_b = normalize(team_b)
                official_a = normalize(team_a_data['name']) if team_a_data else ""
                official_b = normalize(team_b_data['name']) if team_b_data else ""
                
                # Takım A için eşleşme kontrolü
                matches_a = (norm_team_a in norm_filename or (official_a and official_a in norm_filename))
                # Takım B için eşleşme kontrolü
                matches_b = (norm_team_b in norm_filename or (official_b and official_b in norm_filename))

                if matches_a and not matches_b:
                    team_a_tactics = pf["tactics"]
                    lineup_a = pf["lineup"] if pf["lineup"] else pf["tactics"]
                    value_a = pf.get("value", 0.0)
                    rating_a = pf.get("rating", 0.0)
                elif matches_b and not matches_a:
                    team_b_tactics = pf["tactics"]
                    lineup_b = pf["lineup"] if pf["lineup"] else pf["tactics"]
                    value_b = pf.get("value", 0.0)
                    rating_b = pf.get("rating", 0.0)

            # Eşleşmeyen dosyalar varsa varsayılanlara bak
            if not team_a_tactics:
                stored_a = self._get_stored_tactic(team_a_data["name"])
                if stored_a:
                    team_a_tactics, lineup_a, value_a, rating_a = self._parse_tactic_file(stored_a)
                else:
                    print(f"DEBUG: {team_a_data['name']} için kayıtlı taktik bulunamadı.")

            if not team_b_tactics:
                stored_b = self._get_stored_tactic(team_b_data["name"])
                if stored_b:
                    team_b_tactics, lineup_b, value_b, rating_b = self._parse_tactic_file(stored_b)
                else:
                    print(f"DEBUG: {team_b_data['name']} için kayıtlı taktik bulunamadı.")

            # Hala boş olan takım için varsayılan (Son Çare)
            current_year = __import__('datetime').datetime.now().year
            
            if not team_a_tactics:
                if team_a_data.get("is_external"):
                    team_a_tactics = f"{team_a_data['name']} - Dengeli Oyun"
                    lineup_a = f"DİKKAT YIL {current_year}!\n{external_squad_a}"
                else:
                    team_a_tactics = f"{team_a_data['name']} - Varsayılan taktikler\nDiziliş: 4-2-3-1"
                    lineup_a = f"[JENERİK KADRO - OYUNCU BULAMIYORSAN İSİM UYDURMA, SADECE TAKIM ADINI KULLAN: {team_a_data['name']}]"
            
            if not team_b_tactics:
                if team_b_data.get("is_external"):
                    team_b_tactics = f"{team_b_data['name']} - Kontra Atak"
                    lineup_b = f"DİKKAT YIL {current_year}!\n{external_squad_b}"
                else:
                    team_b_tactics = f"{team_b_data['name']} - Varsayılan taktikler\nDiziliş: 4-4-2"
                    lineup_b = f"[JENERİK KADRO - OYUNCU BULAMIYORSAN İSİM UYDURMA, SADECE TAKIM ADINI KULLAN: {team_b_data['name']}]"
        else:
            # 📁 ÖNCELİK 1: Yerel depolama (Dosya eklenmemişse direkt buraya bakar)
            current_year = __import__('datetime').datetime.now().year
            
            # Team A yerel ara
            stored_a = self._get_stored_tactic(team_a_data["name"])
            if stored_a:
                team_a_tactics, lineup_a, value_a, rating_a = self._parse_tactic_file(stored_a)
                if not lineup_a: lineup_a = team_a_tactics
            else:
                # Varsayılan
                if team_a_data.get("is_external"):
                    team_a_tactics = f"{team_a_data['name']} - Dengeli Oyun"
                    lineup_a = f"DİKKAT YIL {current_year}!\n{external_squad_a}"
                    value_a = external_value_a
                else:
                    team_a_tactics = f"{team_a_data['name']} - Varsayılan taktikler\nDiziliş: 4-2-3-1"
                    lineup_a = f"[JENERİK KADRO - OYUNCU BULAMIYORSAN İSİM UYDURMA, SADECE TAKIM ADINI KULLAN: {team_a_data['name']}]"
                    # Fallback (Dinamik): OVR'ye göre değer biç
                    value_a = self._estimate_val_from_ovr(team_a_data.get('overall', 75))
            
            # Team B yerel ara
            stored_b = self._get_stored_tactic(team_b_data["name"])
            if stored_b:
                team_b_tactics, lineup_b, value_b, rating_b = self._parse_tactic_file(stored_b)
                if not lineup_b: lineup_b = team_b_tactics
            else:
                # Varsayılan
                if team_b_data.get("is_external"):
                    team_b_tactics = f"{team_b_data['name']} - Kontra Atak"
                    lineup_b = f"DİKKAT YIL {current_year}!\n{external_squad_b}"
                    value_b = external_value_b
                else:
                    team_b_tactics = f"{team_b_data['name']} - Varsayılan taktikler\nDiziliş: 4-4-2"
                    lineup_b = f"[JENERİK KADRO - OYUNCU BULAMIYORSAN İSİM UYDURMA, SADECE TAKIM ADINI KULLAN: {team_b_data['name']}]"
                    # Fallback (Dinamik): OVR'ye göre değer biç
                    value_b = self._estimate_val_from_ovr(team_b_data.get('overall', 75))

        # Taktik stringine Takımın FORM (Momentum) durumunu da ekleyelim ki AI görsün
        form_a = await database.get_team_form_streak(team_a_data["name"])
        form_b = await database.get_team_form_streak(team_b_data["name"])
        if form_a:
            team_a_tactics = f"[TAKIMIN SON MAÇLARDAKİ FORMU: {form_a} (W=Galibiyet, L=Mağlubiyet. Buna göre moralini ve GPR'sini dinamik ayarla!)]\n\n" + team_a_tactics
        if form_b:
            team_b_tactics = f"[TAKIMIN SON MAÇLARDAKİ FORMU: {form_b} (W=Galibiyet, L=Mağlubiyet. Buna göre moralini ve GPR'sini dinamik ayarla!)]\n\n" + team_b_tactics

        # --- CEZA KONTROLÜ (SUSPENSIONS) ---
        suspended_a = await database.get_suspended_players(team_a_data["name"])
        suspended_b = await database.get_suspended_players(team_b_data["name"])
        
        suspension_info = ""
        if any(s["suspension_matches"] > 0 for s in suspended_a) or any(s["suspension_matches"] > 0 for s in suspended_b):
            suspension_info = "\n\n❌ **DİKKAT: CEZALI OYUNCULAR (BU MAÇTA KESİNLİKLE OYNAYAMAZLAR, DİKKATE AL!):**\n"
            for s in suspended_a:
                if s["suspension_matches"] > 0:
                    suspension_info += f"- {team_a_data['name']}: {s['name']}\n"
            for s in suspended_b:
                if s["suspension_matches"] > 0:
                    suspension_info += f"- {team_b_data['name']}: {s['name']}\n"
        
        team_a_tactics += suspension_info
        team_b_tactics += suspension_info
        # ----------------------------------

        # --- DEĞER VE REYTİNG MOTORU (GELİŞMİŞ) ---
        # 0. Akıllı Değer Bulma: Önce DB'ye bak, yoksa Scout Önbelleğine bak, o da yoksa formül kullan.
        
        async def fetch_realistic_value(team_data_obj, ext_val, current_calculated_ovr):
            # Eğer research'ten (external_value) veri geldiyse onu kullan
            if ext_val and ext_val > 0: return ext_val
            
            # OVR Bazlı Tahmin (Önce OVR'ye bakalım, çok yüksekse 40M-50M gibi cacheleri direkt ezsin)
            ovr_basis = current_calculated_ovr if current_calculated_ovr > 0 else team_data_obj.get("overall", 75)
            estimated = self._estimate_val_from_ovr(ovr_basis)
            
            # Değilse Scout Cache'e bak
            cache_key = f"ext_squad_v2_{self.clean_tn(team_data_obj['name'])}"
            cached = await database.get_scout_cache(cache_key)
            if cached and cached.get("total_value_m"):
                cached_val = cached["total_value_m"]
                # VALIDATION: Eğer cache verisi OVR'ye göre absürt derecede düşükse (Örn: 80+ OVR iken < 100M) ez.
                if ovr_basis > 80 and cached_val < 100:
                    print(f"DEBUG: [Valuation] {team_data_obj['name']} için önbellek verisi GERÇEKSİZ (OVR: {ovr_basis}, Cache: {cached_val}M). Formül devrede.")
                    return estimated
                    
                print(f"DEBUG: [Valuation] {team_data_obj['name']} için scout önbelleğinden değer çekildi: {cached_val}M")
                return cached_val
            
            # O da yoksa bütçeye bak
            db_budget = team_data_obj.get("budget", 0)
            if db_budget and db_budget > 1000000:
                return db_budget / 1000000.0
                
            return estimated

        # --- OVR-ODAKLI REYTİNG MOTORU (YENİ SİSTEM) ---
        # 1. İlk 11 OVR Ortalamasını ve Değerini Hesapla (Lokal TXT varsa önceliklidir!)
        calculated_ovr_a, db_val_a = await self._get_squad_data(team_a_data["name"], lineup_a)
        calculated_ovr_b, db_val_b = await self._get_squad_data(team_b_data["name"], lineup_b)

        # 2. Değerlemeyi FİNAL OVR üzerinden yap (Smart Fallback & Cache Check)
        if db_val_a > 0:
            value_a = db_val_a
        else:
            value_a = await fetch_realistic_value(team_a_data, external_value_a, calculated_ovr_a)

        if db_val_b > 0:
            value_b = db_val_b
        else:
            value_b = await fetch_realistic_value(team_b_data, external_value_b, calculated_ovr_b)

        # Dış takım ise AI araştırmasından gelen taze OVR'yi baz al (Debug panelinde doğru görünmesi için)
        if team_a_data.get("is_external") and external_ovr_a > 0:
            calculated_ovr_a = float(external_ovr_a)
        if team_b_data.get("is_external") and external_ovr_b > 0:
            calculated_ovr_b = float(external_ovr_b)

        # Rating Belirleme (KIYASLAMA MODU)
        if team_a_data.get("is_external"):
            # AI tarafından araştırılan OVR'yi kullan, yoksa fallback yap
            rating_a = external_ovr_a if external_ovr_a > 0 else self._get_smart_ovr(team_a_data['name'])
        else:
            # ÖNEMLİ: Artık sabit takım overall'ı yerine hesaplanan OVR ortalamasını kullanıyoruz!
            rating_a = calculated_ovr_a

        if team_b_data.get("is_external"):
            rating_b = external_ovr_b if external_ovr_b > 0 else self._get_smart_ovr(team_b_data['name'])
        else:
            rating_b = calculated_ovr_b

        # --- VALIDATION: Ensure OVR was found ---
        if rating_a <= 0 or rating_b <= 0:
            missing_team = team_a_data["name"] if rating_a <= 0 else team_b_data["name"]
            await wait_msg.delete()
            return await ctx.send(
                f"❌ **HATA: Kadro Verisi Bulunamadı!**\n\n"
                f"**{missing_team}** takımı için ne veritabanında ne de web araştırmasında güncel bir kadro/reyting verisine ulaşılamadı. "
                f"Maç otomatik 75 OVR ile oynatılmayacak. Lütfen takım ismini kontrol et veya manuel kadro yükle."
            )

        # --- STRATEGIC BOOSTS & MORALE (MATHEMATICAL MOTOR) ---
        # Morale Boosts
        # Morale Boosts (Enforce numeric types to prevent TypeError)
        try:
            moral_a = float(team_a_data.get("morale_boost", 0) or 0)
            moral_b = float(team_b_data.get("morale_boost", 0) or 0)
        except:
            moral_a, moral_b = 0.0, 0.0
            
        rating_a = float(rating_a or 75) + moral_a
        rating_b = float(rating_b or 75) + moral_b
        
        # --- ÖZEL TAKIM BONUSLARI (MATEMATİKSEL MOTOR) ---
        
        # 2. Kocaelispor Genel Bonusu (+1)
        try:
            if "kocaelispor" in team_a_data["name"].lower():
                rating_a = float(rating_a) + 1.0
                print("🟢 Kocaelispor'a +1 performans bonusu eklendi.")
            if "kocaelispor" in team_b_data["name"].lower():
                rating_b = float(rating_b) + 1.0
                print("🟢 Kocaelispor'a +1 performans bonusu eklendi.")
        except Exception as e:
            print(f"DEBUG: Performance bonus error: {e}")

        # 3. BEŞİKTAŞ GÜÇ BONUSU (KALDIRILDI - Sadece AI Taktik Puanı Alacak)
        bjk_bonus_a = 0
        bjk_bonus_b = 0
        # --- GPR HARD LIMITS VE BONUSLAR ---
        has_tactic_a = bool(stored_a)
        has_tactic_b = bool(stored_b)

        # BAZ GPR HESABI (Dinamik Bonuslar Dahil)
        suggested_a = float(rating_a or 75)
        suggested_b = float(rating_b or 75)
        
        # 1. Ev Sahibi / Tarafsız Saha Belirleme
        is_neutral = False
        if is_tourney and t_fixture and any(x in str(t_fixture.get("round", "")).lower() for x in ["final", "tarafsiz", "neutral"]):
            is_neutral = True
        if any(x in (importance or "Normal").lower() for x in ["final", "tarafsiz", "neutral"]):
            is_neutral = True
            
        # 1. Ev Sahibi Atmosfer Bonusu (SADECE Ev Sahibine +2, Tarafsız Sahada Uygulanmaz)
        if not is_neutral:
            suggested_a = float(suggested_a) + 2.0
            print(f"🏟️ EV SAHİBİ AVANTAJI (+2) UYGULANDI.")
        else:
            print(f"🏟️ TARAFSIZ SAHA: Ev sahibi avantajı uygulanmadı.")

        # 2. Taktik Bonusu & AI Analizi
        tactic_bonus_a = 0
        tactic_bonus_b = 0
        tactical_reason = "Taktik analiz jenerik."

        if has_tactic_a or has_tactic_b:
            # Taktiklerden en az biri varsa AI'dan puan iste
            eval_a = team_a_tactics if has_tactic_a else "Standart jenerik taktik."
            eval_b = team_b_tactics if has_tactic_b else "Standart jenerik taktik."
            
            scores = await self._get_tactical_scores(team_a_data["name"], eval_a, team_b_data["name"], eval_b)
            tactical_reason = scores.get("reason", "Analiz tamamlandı.")

            # Taktiği olan AI puanını alır (Empty Tactic / Roster Only = +4), olmayan sabit 2-3
            # AVRUPA TAKIMI BONUSU: Eğer taktiği yoksa ama Avrupa takımıysa (Europe ligi), default 4.5 boost verilir.
            is_euro_a = team_a_data.get("league") == "Europe" or (is_tourney and team_a_data.get("is_external"))
            is_euro_b = team_b_data.get("league") == "Europe" or (is_tourney and team_b_data.get("is_external"))
            # Sadece Beşiktaş için 7 sabitlendi, diğerleri AI puanına bırakıldı (max(4,...) kaldırıldı)
            tactic_bonus_a = scores.get("home", 0) if has_tactic_a else (4.5 if is_euro_a else random.randint(2, 3))
            tactic_bonus_b = scores.get("away", 0) if has_tactic_b else (4.5 if is_euro_b else random.randint(2, 3))

            
            # --- BEŞİKTAŞ SPECIAL RULE: Always 7 Tactical Boost ---
            if "beşiktaş" in team_a_data["name"].lower():
                tactic_bonus_a = 7
                print("🦅 Beşiktaş için taktik boostu 7 olarak sabitlendi.")
            if "beşiktaş" in team_b_data["name"].lower():
                tactic_bonus_b = 7
                print("🦅 Beşiktaş için taktik boostu 7 olarak sabitlendi.")

            if is_euro_a and not has_tactic_a and "beşiktaş" not in team_a_data["name"].lower(): print(f"🇪🇺 {team_a_data['name']} (Europe) için +4.5 default taktik boostu uygulandı.")
            if is_euro_b and not has_tactic_b and "beşiktaş" not in team_b_data["name"].lower(): print(f"🇪🇺 {team_b_data['name']} (Europe) için +4.5 default taktik boostu uygulandı.")
            
            tactical_reason = scores.get("reason", "Analiz tamamlandı.")
        else:
            # İkisinin de taktiği yoksa
            is_euro_a = team_a_data.get("league") == "Europe" or (is_tourney and team_a_data.get("is_external"))
            is_euro_b = team_b_data.get("league") == "Europe" or (is_tourney and team_b_data.get("is_external"))
            
            tactic_bonus_a = 4.5 if is_euro_a else random.randint(2, 3)
            tactic_bonus_b = 4.5 if is_euro_b else random.randint(2, 3)
            
            # --- BEŞİKTAŞ SPECIAL RULE: Always 7 Tactical Boost ---
            if "beşiktaş" in team_a_data["name"].lower():
                tactic_bonus_a = 7
                print("🦅 Beşiktaş için taktik boostu 7 olarak sabitlendi.")
            if "beşiktaş" in team_b_data["name"].lower():
                tactic_bonus_b = 7
                print("🦅 Beşiktaş için taktik boostu 7 olarak sabitlendi.")
            
            if is_euro_a: print(f"🇪🇺 {team_a_data['name']} (Europe) için +4.5 default taktik boostu uygulandı.")
            if is_euro_b: print(f"🇪🇺 {team_b_data['name']} (Europe) için +4.5 default taktik boostu uygulandı.")
            
            tactical_reason = "Her iki takım da standart jenerik taktikle sahada."

        try:
            suggested_a = float(suggested_a) + float(tactic_bonus_a or 0)
            suggested_b = float(suggested_b) + float(tactic_bonus_b or 0)
        except Exception as e:
            print(f"DEBUG: Tactic bonus conversion error: {e}")
            suggested_a = float(suggested_a)
            suggested_b = float(suggested_b)

        # --- GPR HARD LIMITS (MAĞDURİYET ÖNLEME AYARLARI) ---
        # ÖNEMLİ: r_gap artık tüm bonuslar eklenmiş FİNAL GPR üzerinden hesaplanır.
        r_gap = abs(suggested_a - suggested_b)
        gap = suggested_a - suggested_b
        
        # Base Offsets (Narrowed)
        off_max_a, off_min_a = (8, 4) if has_tactic_a else (6, 2)
        off_max_b, off_min_b = (6, 6) if has_tactic_b else (5, 5)

        # GPR GAP DISIPLINI: Fark büyüdükçe sürpriz marjını daralt
        if r_gap > 8:
            # Fark 8'den büyükse, güçlünün tabanı yükselir, zayıfın tavanı çöker
            if gap > 0: # Team A güçlü
                off_min_a = 2
                off_max_b = 3
            else: # Team B güçlü
                off_max_a = 3
                off_min_b = 2

        if r_gap > 15:
            # 15+ Fark (Ezici Üstünlük): Sürpriz ihtimali %5'lere çekilir
            if gap > 0:
                off_min_a = 0.5 # Güçlü takım neredeyse hiç hata yapmaz
                off_max_b = 1.0 # Zayıf takımın mucize tavanı kilitlendi
            else:
                off_max_a = 1.0
                off_min_b = 0.5
        
        if r_gap > 20:
            # 20+ Fark (Mutlak Hakimiyet): Sürpriz kapısı teknik olarak kapalı
            if gap > 0:
                off_min_a = 0.0
                off_max_b = 0.5
            else:
                off_max_a = 0.5
                off_min_b = 0.0

        max_gpr_a = min(99, rating_a + off_max_a)
        min_gpr_a = max(10, rating_a - off_min_a)
        max_gpr_b = min(99, rating_b + off_max_b)
        min_gpr_b = max(10, rating_b - off_min_b)


        # --- TORBADAN MAÇ SENARYOSU SEÇİMİ (GAP BAZLI DARALTILMIŞ) ---
        balanced_flows = [
            "DENGELİ SAVAŞ (Orta saha mücadelesinin yoğun olduğu, taktiklerin konuştuğu bir maç kurgula)",
            "KEMİK SESLERİ (Fiziksel mücadelenin ve sertliğin teknik oyunun önüne geçtiği, duran topların belirleyici olduğu senaryo)",
            "SATRANÇ MAÇI (İki hocanın birbirini kilitlemeye çalıştığı, hata yapanın kaybedeceği düşük tempolu ama gergin maç)",
            "KAOTİK ORTA SAHA (Pas trafiğinin sürekli kesildiği, topun bir o kalede bir bu kalede olduğu ama kalitenin düştüğü anlar)",
            "KORA KOR MÜCADELE (İki takımın da geri adım atmadığı, her ikili mücadelenin kıvılcım çıkardığı maç)",
            "ORTA SAHA BOĞUŞMASI (Oyunun merkezde kilitlendiği, iki tarafın da birbirini orta alanda eritmeye çalıştığı senaryo)",
            "TAKTİKSEL KİLİT (Savunmaların kusursuz olduğu, tek bir hatanın sonucu belirlediği düşük skorlu maç)",
            "NEFES KESEN DÜELLO (Karşılıklı atakların hiç bitmediği, her an gol olabilecekmiş gibi hissettiren yüksek tempolu maç)",
            "SİNİR HARBİ (Oyuncuların birbirini provoke ettiği, hakemin sürekli oyunu durdurmak zorunda kaldığı gergin akış)",
            "DİRENÇLİ SAVUNMALAR (Hücumların duvara çarptığı, savunma oyuncularının etten duvar ördüğü ve kalecilerin devleştiği maç)",
            "TAM BİR TAKTİK PANORAMASI (Dizilişlerin ve oyuncu rollerinin maçın kaderini saniye saniye değiştirdiği teknik maç)",
            "AMANSIZ PRES SAVAŞI (İki takımın da rakibine nefes aldırmadığı, en ufak bir hatanın cezalandırılmayı beklediği maç)",
            "GOL YOK MÜCADELE ÇOK (Skor tabelası değişmese de sahadaki hırsın ve mücadelenin en üst seviyede olduğu senaryo)",
            "STRATEJİK BEKLEYİŞ (Düşük tempolu başlayan ama son çeyrekte iki tarafın da tüm riskleri aldığı heyecan dolu kapanış)"
        
        ]
        
        chaos_flows = [
            "KAOS VE KIRMIZI KART (Beklenmedik bir sertlik sonucu gelen kartın tüm dengeleri alt üst ettiği dramatik akış)",
            "VAR KAOSU (İptal edilen goller ve tartışmalı penaltılar yüzünden skorun sürekli değiştiği sinir bozucu maç)",
            "HAKEM HATALARI (Zemin, hava ve hakem üçlüsünün birleşip maçı kontrolden çıkardığı tartışmalı senaryo)",
            "ADRENALİN PATLAMASI (Düşük tempolu başlayıp son 15 dakikada 3-4 golün atıldığı, her şeyin birbirine girdiği anlar)",
            "TARAFTAR BASKISI VE İSYAN (Tribünlerin hakem ve rakip üzerinde kurduğu muazzam baskının oyunu etkilemesi)",
            "SAHA İÇİ KAVGA (İkili mücadelelerin bir anda gerginliğe ve itiş kakışa dönüştüğü, kartların havada uçuştuğu maç)",
            "İNANILMAZ BİREYSEL HATALAR (Kaleci ve savunmanın peş peşe yaptığı komik hataların gollerle sonuçlandığı kaos)",
            "TEKNİK DİREKTÖR ÇILDIRDI (Kenar yönetiminin hakemle girdiği diyaloglar yüzünden tribüne gönderildiği ve takımın dağıldığı anlar)",
            "PEŞ PEŞE ÇIKAN KIRMIZI KARTLAR (Disiplinin tamamen kaybolduğu, takımların eksik kaldığı ve maçın 'mahalle maçına' döndüğü senaryo)",
            "AKILALMAZ BİR GERİ DÖNÜŞ (Farklı mağlup durumdaki takımın taraftarının da desteğiyle imkansızı başlattığı isyan maçı)"
        ]
        
        favorite_flows = [
            "CLEAN SHEET DOMINATION (Favorinin gol yemeden net galibiyet aldığı, savunmada hiç boşluk vermediği senaryo)",
            "ERKEN BLITZ (Favorinin ilk 20 dakikada 2-3 gol bulup rakibin gardını tamamen düşürdüğü dominant maç)",
            "DEPLASMAN SOĞUKLUĞU (Favori deplasman ekibinin disiplinli oyunuyla rakip tribünleri susturduğu profesyonel galibiyet)",
            "YEDEKLERİN GÜNÜ (70'e kadar berabere giden maçın oyuna giren yedeğin golleriyle bir anda farklı bitmesi)",
            "TEK KALE MAÇ (Favorinin rakip kalede kamp kurduğu, istatistiklerin tavan yaptığı ama skorun sabırla geldiği maç)",
            "KLAS FARKI (Bireysel yeteneklerin ön plana çıktığı, yıldız oyuncuların tek başına maçı çözdüğü elit performans)",
            "GÖVDE GÖSTERİSİ (Şampiyonluk adayı takımın rakiplerine korku saldığı, her hattıyla kusursuz oynadığı maç)",
            "TOPA SAHİP OLMA DOMİNASYONU (Rakibe topu göstermeyen, yüzlerce pasın yapıldığı teknik bir ders niteliğinde galibiyet)",
            "USTALIK ESERİ (Teknik direktörün tüm hamlelerinin tuttuğu, rakibin her planının boşa çıkarıldığı stratejik zafer)",
            "RÖLANTİYE ALINMIŞ BİR ZAFER (İlk yarıda skoru bulan favorinin ikinci yarıda tempoyu düşürüp maçı rahatça bitirmesi)"
        ]
        
        blowout_flows = [
            "TARİHİ HEZİMET (Hiçbir direnç gösteremeyen zayıf rakibe karşı tarihi bir farka gidilen acımasız maç)",
            "TEK TARAFLI BOĞUCU OYUN (Zayıf rakibin kalesinden çıkamadığı ve her atağın tehlike yarattığı yıkıcı senaryo)",
            "HER ATAK GOL (Favori takımın her şutunun gol olduğu, rakibin adeta sahada olmadığı moral bozucu hezimet)",
            "BEYAZ HAVLU ATILDI (İlk golden sonra direnci tamamen kırılan zayıf rakibe karşı oynanan tek kale antrenman maçı)",
            "DEFANSIN ÇÖKÜŞÜ (Savunma hattının iflas ettiği, kalecinin her şutta kalesinde gol gördüğü kabus gibi bir akşam)",
            "MERHAMETSİZ SALDIRI (Skor kaç olursa olsun favorinin durmadığı, rakibi sahadan sildiği dominant bir infaz)",
            "TARİHE GEÇEN BİR SKOR (Yıllarca unutulmayacak kadar büyük bir farkın atıldığı, her dakikanın gol koktuğu maç)",
            "GÜÇ GÖSTERİSİ (Aralarındaki devasa kalite farkını her dakika sahaya yansıtan, forvetlerin gol rekoru kırdığı maç)"
        ]

        wildcard_flows = [
            "BEKLENMEDİK ÇÖKÜŞ (Dengeli giden maçta bir tarafın şok bir şekilde dağıldığı senaryo)",
            "SÜRPRİZ YENİLGİ (Favorinin her şeyi yapmasına rağmen şanssızlıklarla kaybettiği şok skor)",
            "90+5 YIKIMI (Maçın berabere biteceği sanılırken son saniyede gelen golle gelen mağlubiyet)",
            "SON DAKİKA ŞOKU (Son ana kadar baskın oynayan tarafın kontradan yediği golle yıkılması)",
            "GERİ DÖNÜŞÜN EŞİĞİ (Bir takımın farkla öne geçtiği, rakibin yaklaştığı ama nefesinin yetmediği maç)",
            "GOL DÜELLOSU (Savunmaların unutulduğu, her atağın golle sonuçlandığı çılgın bir 3-3 veya 4-3 senaryosu)",
            "YILDIZIN GECESİ (Bir oyuncunun hat-trick veya inanılmaz asistlerle maçı tek başına domine etmesi)",
            "KALECİ HATALARI (İki kalecinin de formsuz olduğu, basit şutların bile gol olduğu ilginç bir akış)"
        ]
        
        # --- DİNAMİK ŞANS VE AKIŞ YÖNETİMİ (LUCK 4.0) ---
        # Güç farkı azaldıkça (Derbi havası) sürpriz ihtimali artar.
        if r_gap < 3:    luck_threshold = 0.15  # Derbi/Eşit: %15
        elif r_gap < 8:  luck_threshold = 0.10  # Kora Kor: %10
        elif r_gap < 15: luck_threshold = 0.05  # Rekabetçi: %5
        else:            luck_threshold = 0.02  # Favori Net: %2

        is_extreme = random.random() < luck_threshold
        luck_gpr_bonus_a = 0
        luck_gpr_bonus_b = 0

        # 1. EXTREME SCENARIOS (%15-%30) - KAOS VE SÜRPRİZ BURADA DOĞAR
        extreme_scenarios = [
            {"text": "🍀 [KRİTİK] Favori çok şanssız, toplar direkten dönüyor.", "a": -3, "b": 1, "chaos": 4},
            {"text": "🍀 [KRİTİK] Kaleci bugün devleşiyor, kalede adeta etten duvar var.", "a": 3, "b": -2, "chaos": 2},
            {"text": "🍀 [KRİTİK] Zayıf takım maça fırtına gibi başlıyor, favori şaşkın.", "a": -2, "b": 4, "chaos": 6},
            {"text": "🍀 [KRİTİK] Hava koşulları teknik takımları zorluyor, zemin ağır.", "a": -2, "b": -2, "chaos": 5},
            {"text": "🍀 [KRİTİK] Erken gelen kırmızı kart tüm planları alt üst ediyor.", "a": -4, "b": 2, "chaos": 8},
            {"text": "🍀 [KRİTİK] Taraftarın yoğun ıslık protestosu favoriyi demoralize ediyor.", "a": -3, "b": 1, "chaos": 5},
            {"text": "🍀 [KRİTİK] Favori takımın yıldızı maçın başında sakatlanarak çıkıyor.", "a": -4, "b": 2, "chaos": 4},
            {"text": "🍀 [KRİTİK] Yedek kalecinin hayatının maçı; imkansızları çıkarıyor.", "a": 3, "b": -2, "chaos": 4},
            {"text": "🍀 [KRİTİK] Stoperler bugün inanılmaz hatalar yapıyor, defans hattı zayıf.", "a": -3, "b": -3, "chaos": 7},
            {"text": "🍀 [KRİTİK] Tartışmalı bir VAR kararı saha içini ve tribünleri geriyor.", "a": 0, "b": 0, "chaos": 6}
        ]

        # 2. STANDARD SCENARIOS (%70-%85) - SAKİN VE RATING ODAKLI
        standard_scenarios = [
            {"text": "Hava güneşli, zemin futbol için çok ideal.", "a": 0, "b": 0, "chaos": 1},
            {"text": "Sakin bir atmosferde, taktik disiplinin ön planda olduğu bir maç.", "a": 0, "b": 0, "chaos": 2},
            {"text": "Tribünler bugün çok coşkulu, görsel şölen eşliğinde bir başlangıç.", "a": 0, "b": 0, "chaos": 4},
            {"text": "Takımlar kontrollü başlıyor, orta saha mücadelesi yoğun.", "a": 0, "b": 0, "chaos": 3},
            {"text": "Hafif yağışlı bir hava, top hızlanıyor ama zemin hala iyi.", "a": 0, "b": 0, "chaos": 5},
            {"text": "İki hoca da birbirini çok iyi analiz etmiş, satranç maçı tadında.", "a": 0, "b": 0, "chaos": 3},
            {"text": "Saha kenarında ve tribünlerde dostane bir hava hakim.", "a": 0, "b": 0, "chaos": 2},
            {"text": "Savunma hatları çok konsantre, hata yapmamak için büyük çaba var.", "a": 0, "b": 0, "chaos": 2},
            {"text": "Orta saha boğuşması yoğun, iki taraf da fiziksel olarak diri.", "a": 0, "b": 0, "chaos": 6},
            {"text": "Maçın başından beri karşılıklı saygı ve centilmenlik ön planda.", "a": 0, "b": 0, "chaos": 1}
        ]

        if is_extreme:
            # Şans Faktörü: Ekstrem havuzdan seçilir ve GPR etkilenir
            scenario_obj = random.choice(extreme_scenarios)
            luck_gpr_bonus_a = float(scenario_obj.get("a", 0) or 0)
            luck_gpr_bonus_b = float(scenario_obj.get("b", 0) or 0)
            suggested_a = float(suggested_a) + luck_gpr_bonus_a
            suggested_b = float(suggested_b) + luck_gpr_bonus_b
            chosen_luck = scenario_obj["text"]
            
            # Maç Akışı: Wildcard (Sürpriz/Şok) havuzundan seçilir
            chosen_flow = random.choice(wildcard_flows)
            print(f"🔥 EKSTREM MOD AKTİF (Şans: %{luck_threshold*100:.0f}): {chosen_luck}")
        else:
            # Şans Faktörü: Standart havuzdan seçilir, GPR etkilenmez
            scenario_obj = random.choice(standard_scenarios)
            chosen_luck = scenario_obj["text"]
            
            # Maç Akışı: Güç farkına göre Normal havuzlardan seçilir (Wildcard YASAK)
            if r_gap < 12: pool = balanced_flows + chaos_flows
            elif r_gap < 18: pool = favorite_flows + balanced_flows
            else: pool = blowout_flows + favorite_flows
            
            chosen_flow = random.choice(pool)
            print(f"⚖️ STANDART MOD AKTİF (Şans: %{luck_threshold*100:.0f}): {chosen_flow}")

        # 15+ Farkta Akışı Yönlendir (Hangi takım lehine olduğunu AI'ya fısılda)
        if r_gap >= 15:
            stronger_team = team_a_data["name"] if rating_a > rating_b else team_b_data["name"]
            chosen_flow = f"{chosen_flow} ({stronger_team} LEHİNE)"

        # Store stats for the final result embed (moved from pre-match guide)
        result_stats = {
            "home": {"ovr": calculated_ovr_a, "val": format_currency(value_a), "gpr": suggested_a, "boost": tactic_bonus_a+moral_a+bjk_bonus_a},
            "away": {"ovr": calculated_ovr_b, "val": format_currency(value_b), "gpr": suggested_b, "boost": tactic_bonus_b+moral_b+bjk_bonus_b}
        }
        
        # Konsol logu için kalsın
        print("\n" + "="*60)
        print(f"🏟️  MAÇ ANALİZİ: {team_a_data['name']} vs {team_b_data['name']}")
        print(f"🏠 {team_a_data['name']} | GPR: {suggested_a} | Boost: {tactic_bonus_a+moral_a+bjk_bonus_a}")
        print(f"🚌 {team_b_data['name']} | GPR: {suggested_b} | Boost: {tactic_bonus_b+moral_b+bjk_bonus_b}")
        print("="*60 + "\n")



        # Diziliş tespiti (NameError fix için)
        import re
        def get_formation(text):
            match = re.search(r"(?:Diziliş|Formation):\s*([0-9-]{3,7})", text, re.IGNORECASE)
            return match.group(1) if match else "4-4-2"

        f_a = get_formation(team_a_tactics)
        f_b = get_formation(team_b_tactics)

        # OpenRouter AI API ile simülasyon (Dinamik bekleme mesajı ile)
        async def update_wait_msg(msg):
            import random
            steps = [
                "🏟️ Stat ışıkları yakılıyor...",
                "📋 Kadrolar ve taktikler analiz ediliyor...",
                "⚖️ GPR ve atmosfer etkisi hesaplanıyor...",
                "⚽ Toplar şişiriliyor ve zemin kontrol ediliyor...",
                "📰 Basın ve sosyal medya beklentileri ölçülüyor...",
                "🕵️ Gözlemci raporları inceleniyor..."
            ]
            random.shuffle(steps)
            for step in steps:
                try:
                    current_embed = msg.embeds[0]
                    current_embed.description = f"⚔️ **{team_a_data['name']} vs {team_b_data['name']}**\n\n" \
                                                f"🔄 **Durum:** {step}\n" \
                                                f"⏳ _Lütfen bekleyin, maç kurgulanıyor..._"
                    await msg.edit(embed=current_embed)
                    await asyncio.sleep(4)
                except: break

        wait_task = asyncio.create_task(update_wait_msg(wait_msg))

        # (is_tourney, t_fixture, agg_ctx, comp_name yukarida manuel mod icin zaten set edildi)

        try:
            result = await self._simulate_match_ai(
                team_a_data["name"], team_a_tactics,
                team_b_data["name"], team_b_tactics,
                comp_name if is_tourney else importance, weather,
                lineup_a, lineup_b,
                rating_a, rating_b,
                max_gpr_a, max_gpr_b, min_gpr_a, min_gpr_b,
                suggested_a, suggested_b,
                f_a, f_b,
                has_tactic_a, has_tactic_b,
                value_a, value_b,
                is_tournament=is_tourney,
                leg=t_fixture.get("leg", 1) if (t_fixture and isinstance(t_fixture, dict)) else 1,
                agg_context=agg_ctx,
                match_flow=chosen_flow,
                luck_scenario=chosen_luck,
                is_ext_a=team_a_data.get("is_external", False),
                is_ext_b=team_b_data.get("is_external", False),
                round_no=fixture.get("round_no") if fixture else None
            )
        finally:
            wait_task.cancel()

        if is_tourney and t_fixture and isinstance(t_fixture, dict):
            # Update tournament fixture score in DB only (post will happen after embeds are sent)
            h_s = result.get("home_score", 0) if isinstance(result, dict) else 0
            a_s = result.get("away_score", 0) if isinstance(result, dict) else 0
            t_id_val = t_fixture.get("id")
            if t_id_val:
                await database.update_tournament_fixture_score(t_id_val, h_s, a_s)

        await wait_msg.delete()

        if not result:
            await ctx.send("❌ **Maç simülasyonu sırasında bir hata oluştu!**\nLütfen API anahtarını kontrol edin veya tekrar deneyin.")
            return

        # Skoru gol listesinden yeniden hesapla (AI tutarsizligini onle)
        if not isinstance(result, dict):
            await ctx.send("❌ **HATA:** Maç verisi geçersiz bir formatta (tuple) döndü. Lütfen tekrar deneyin.")
            return

        result["pre_match_stats"] = result_stats # Inject stats for embed
        goals = result.get("goals", [])
        # AI tarafında eksik anahtar gelirse hata almamak için orjinal isimleri ekleyelim
        result["home_team"] = result.get("home_team", team_a_data["name"])
        result["away_team"] = result.get("away_team", team_b_data["name"])
        
        home_team_name = result["home_team"]
        away_team_name = result["away_team"]

        # --- GÜVENLİK KİLİDİ: Beşiktaş 10. Hafta Garantisi ---
        current_round = fixture.get("round_no") if fixture else None
        if current_round == 10:
            tn_h = self.clean_tn(home_team_name)
            tn_a = self.clean_tn(away_team_name)
            if (tn_h == "kocaelispor" and tn_a == "besiktas") or (tn_h == "besiktas" and tn_a == "kocaelispor"):
                # Golleri sayalım
                h_goals = 0
                a_goals = 0
                h_clean = self.clean_tn(home_team_name)
                a_clean = self.clean_tn(away_team_name)
                for g in result.get("goals", []):
                    gt_clean = self.clean_tn(g.get("team", ""))
                    if gt_clean in h_clean or h_clean in gt_clean: h_goals += 1
                    elif gt_clean in a_clean or a_clean in gt_clean: a_goals += 1
                
                # Galibiyet kontrolü
                is_h_bjk = (tn_h == "besiktas")
                bjk_won = (is_h_bjk and h_goals > a_goals) or (not is_h_bjk and a_goals > h_goals)
                
                if not bjk_won:
                    # AI talimatı dinlemediyse, manuel olarak 90+4'te galibiyet golünü ÇAK!
                    win_team = home_team_name if is_h_bjk else away_team_name
                    # Kadrodan bir golcü seçelim (veya jenerik)
                    scorer = "Beşiktaş Yıldızı"
                    if is_h_bjk and lineup_a:
                        names = re.findall(r"([A-Z][a-z]+ [A-Z][a-z]+)", lineup_a)
                        if names: scorer = random.choice(names)
                    elif not is_h_bjk and lineup_b:
                        names = re.findall(r"([A-Z][a-z]+ [A-Z][a-z]+)", lineup_b)
                        if names: scorer = random.choice(names)
                    
                    new_goal = {"minute": 94, "player": scorer, "team": win_team, "type": "regular"}
                    result.setdefault("goals", []).append(new_goal)
                    
                    new_event = {
                        "minute": 94, "type": "goal", "team": win_team, "player": scorer,
                        "description": f"⚽ **İNANILMAZ BİR AN!** Maçın son saniyelerinde {scorer} sahneye çıkıyor! Beşiktaş taraftarı çılgına dönmüş durumda, bu gol şampiyonluk yolunda altın değerinde! (Scripted Victory)"
                    }
                    result.setdefault("events", []).append(new_event)
                    print(f"⚠️ SAFETY: Beşiktaş Week 10 victory forced manually!")

        if goals:
            real_home = 0
            real_away = 0
            h_clean = self.clean_tn(home_team_name)
            a_clean = self.clean_tn(away_team_name)
            
            for g in goals:
                g_team = g.get("team", "")
                gt_clean = self.clean_tn(g_team)
                
                # İsim bazlı kontrol
                is_h = (gt_clean in h_clean or h_clean in gt_clean)
                is_a = (gt_clean in a_clean or a_clean in gt_clean)
                
                # Anahtar kelime bazlı kontrol
                if not is_h and not is_a:
                    t_low = str(g_team or "").lower()
                    if any(x in t_low for x in ["home", "ev sahibi", "evsa", "host"]): is_h = True
                    elif any(x in t_low for x in ["away", "deplasman", "dep", "guest"]): is_a = True
                
                if is_h: real_home += 1
                elif is_a: real_away += 1
                else: 
                    # Literal check
                    if g_team == home_team_name: real_home += 1
                    else: real_away += 1
                    
            result["home_score"] = real_home
            result["away_score"] = real_away

        if is_live:
            # Canlı Simülasyonu Başlat
            await self._run_live_simulation(ctx, result, "Lig" if importance == "Lig" else importance)
            
        # --- VERİTABANI KAYDI VE ETKİLER ---
        is_trial = getattr(ctx, "is_trial", False)
        match_id = 0
        competition = importance

        if not is_trial:
            # Maçı veritabanına kaydet
            match_id, competition = await database.record_match(
                home_team_name, away_team_name,
                result.get("home_score", 0),
                result.get("away_score", 0),
                importance, weather,
                goals,
                leg=t_fixture["leg"] if (is_tourney and t_fixture) else None,
                events=result.get("events", [])
            )
        else:
            competition = "Hazırlık (Deneme)"
            # Deneme maçı olduğunu sonuçlara işle
            result["is_trial"] = True

        # Değerleri formatlayıcıya ilet (KADRO DEĞERİ)
        result["value_a"] = value_a
        result["value_b"] = value_b
        
        # --- TUR ATLAYAN HESAPLAMA (Programatik) ---
        if is_tourney and t_fixture and not is_trial:
            is_final = t_fixture["round"].lower() == "final"
            # Final ise direkt bu maçın kazananına bak (Uzatma/Penaltı dahil)
            if is_final:
                # result zaten AI tarafından 'final_winner' ile dönebilir ama biz garantileyelim
                h_s = result.get("home_score", 0)
                a_s = result.get("away_score", 0)
                if h_s > a_s: result["final_winner"] = home_team_name
                elif a_s > h_s: result["final_winner"] = away_team_name
            # Leg 2 ise Aggrecate bak
            elif t_fixture.get("leg") == 2:
                agg = await database.get_aggregate_score(t_fixture["tournament_id"], t_fixture["round"], home_team_name, away_team_name)
                total_h = agg.get(home_team_name, 0)
                total_a = agg.get(away_team_name, 0)
                
                if total_h > total_a:
                    result["final_winner"] = home_team_name
                elif total_a > total_h:
                    result["final_winner"] = away_team_name
                else:
                    # Eşitlik durumunda AI'nın 'final_winner' alanını kontrol et
                    if not result.get("final_winner") or result.get("final_winner") == "...":
                        # AI belirlememiş, Mikro-Simülasyon yap
                        # OVR üzerinden şans belirle
                        weight_h = 50 + (rating_a - rating_b) * 0.5
                        p_h = random.randint(3, 5)
                        p_a = random.randint(3, 5)
                        if p_h == p_a:
                            if random.random() * 100 < weight_h: p_h += 1
                            else: p_a += 1
                        
                        f_winner = home_team_name if p_h > p_a else away_team_name
                        result["final_winner"] = f_winner
                        result["is_extra_time"] = True
                        result["extra_time_score"] = "Eşitlik bozulmadı (Penaltılar: {}-{})".format(p_h, p_a)
                
                # Turnuva turunu ve verileri formatlayıcıya hazırlayalım
                result["is_tournament"] = True
                result["leg"] = t_fixture["leg"]
                result["agg_context"] = agg_ctx if 'agg_ctx' in locals() else None
                result["round"] = t_fixture["round"]

        # Sonuçları gönder (Premium Embed)
        embeds = self._format_match_result(result, competition)
        for embed in embeds:
            await ctx.send(embed=embed)

        # AUTO-POST TO TOURNAMENT CHANNEL (after embeds sent so score is already revealed)
        if is_tourney and t_fixture and isinstance(t_fixture, dict):
            tournament_cog = self.bot.get_cog("Kupa")
            if tournament_cog:
                await asyncio.sleep(2)  # Small delay to ensure embeds are fully delivered
                self.bot.loop.create_task(tournament_cog._post_to_tournament_channel(ctx, comp_name))

        # --- GÖRSEL MAÇ SONUCU OLUŞTURUCU (AUTO-LOGO INTEGRATION) ---
        try:
            # Otomatik Logo İndirme (Eğer yoksa)
            await self.logo_manager.get_league_logo()
            await self.logo_manager.get_team_logo(home_team_name)
            await self.logo_manager.get_team_logo(away_team_name)
            
            # Verileri Hazırla
            stats_payload = {
                "Shots": [result.get('shots_home', 0), result.get('shots_away', 0)],
                "Shots on Target": [result.get('shots_on_target_home', 0), result.get('shots_on_target_away', 0)],
                "Possession": [result.get('possession_home', 50), result.get('possession_away', 50)],
                "Pass Accuracy": [result.get('pass_accuracy_home', 80), result.get('pass_accuracy_away', 80)],
                "Fouls": [result.get('fouls_home', 10), result.get('fouls_away', 10)],
                "Corners": [result.get('corners_home', 5), result.get('corners_away', 5)],
                "Offsides": [result.get('offsides_home', 1), result.get('offsides_away', 1)],
                "xG (Beklenen Gol)": [result.get('xg_home', 0.0), result.get('xg_away', 0.0)]
            }
            
            events_payload = []
            for g in result.get("goals", []):
                events_payload.append({"minute": g['minute'], "type": "goal", "player": g.get('player', 'Bilinmeyen'), "team": g['team']})
            for e in result.get("events", []):
                if "card" in e.get("type", ""):
                    events_payload.append({"minute": e['minute'], "type": e['type'], "player": e.get('player', 'Bilinmeyen'), "team": e.get('team', '')})
            
            # Tarihe göre sırala
            events_payload.sort(key=lambda x: x['minute'])
            
            # Additional metadata for V3
            attendance = f"{random.randint(15000, 45000):,}".replace(",", ".")
            stadium = "BAHÇEŞEHİR OKULLARI STADYUMU" if "Alanya" in home_team_name else "ÜLKER STADYUMU" if "Fener" in home_team_name else "RAMS PARK" if "Galata" in home_team_name else "TÜPRAŞ STADYUMU" if "Beşiktaş" in home_team_name else "TÜRKİYE SÜPER LİGİ STADYUMU"
            
            graphic_data = {
                "home_team": home_team_name,
                "away_team": away_team_name,
                "home_score": result.get("home_score", 0),
                "away_score": result.get("away_score", 0),
                "stadium": stadium,
                "attendance": attendance,
                "stats": stats_payload,
                "events": events_payload,
                "motm": result.get("motm", {"player": "N/A", "rating": 0})
            }
            
            # Görseli Üret
            img_io = self.graphics_engine.generate_match_summary(graphic_data)
            await ctx.send(file=discord.File(img_io, filename=f"match_result_{home_team_name}_{away_team_name}.png"))
        except Exception as e:
            print(f"DEBUG: Match Graphic generation failed: {e}")

        # --- MEDYA REAKSİYONLARI (TASARRUF MODU: DEVRE DIŞI) ---
        media_reactions = {}
        # User requested to skip AI reactions to save API calls
        skip_media = True 
        
        result["media_reactions"] = media_reactions
        
        # Medya Embedi (Sadece AI verisi varsa)
        if media_reactions:
            media_embed = self._format_media_reactions(result)
            await ctx.send(embed=media_embed)
            
            # Fizio Romano Standalone Tweet!
            tweet_embed = self._format_fizio_romano_tweet(result)
            await ctx.send(embed=tweet_embed)
        
        # --- API SAVE (CACHING) NEWS ---
        if not is_trial:
            # Haberleri match_id ile ilişkilendirerek kaydet
            try:
                cache_data = {
                    "headline": result.get("media_reactions", {}).get("headline"),
                    "fizio": result.get("media_reactions", {}).get("fizio_romano_news"),
                    "var": result.get("var_events", [])
                }
                import json
                await database.save_scout_cache(f"news_{match_id}", cache_data)
            except Exception as e:
                print(f"DEBUG: News cache saving failed: {e}")

            # --- RESET MORALE BOOST ---
            try:
                if moral_a != 0:
                    await database.reset_morale_boost(home_team_name)
                if moral_b != 0:
                    await database.reset_morale_boost(away_team_name)
            except Exception as e:
                print(f"DEBUG: Morale reset failed: {e}")

        # --- PERSISTENCE & AUTO-HIGHLIGHTS ---
        self.last_match_result = result
        
        # 9. AUTOMATED CHANNEL UPDATES (SINGLE MATCH)
        try:
            await self.update_league_channels(ctx.guild, is_week_end=False)
        except Exception as e:
            print(f"DEBUG: Automated single match update failed: {e}")

        if importance == "Derby":
            await ctx.send("🔥 **DERBİ ÖZEL: Maçın dev manşetleri ve galeri hazırlanıyor...** 📸")
            await asyncio.sleep(3)
            await ctx.invoke(self.bot.get_command("manset"))

        # --- AUTOMATED TOURNAMENT ROUND SIMULATION (AUTO-FINISH MATCHDAY) ---
        if is_tourney and t_fixture:
            t_id = t_fixture["tournament_id"]
            t_round = t_fixture["round"]
            current_leg = t_fixture.get("leg", 1)
            
            # KRİTİK: Eğer bu turda/haftada hala oynanmamış başka bir TÜRK TAKIMI varsa simülasyonu başlatma.
            import config
            turkish_names = [t.lower() for t in config.TURKISH_TEAMS]
            
            has_pending_turkish = False
            async with aiosqlite.connect(database.DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT id FROM tournament_fixtures 
                    WHERE tournament_id = ? AND round = ? AND status = 'Pending'
                      AND (LOWER(home_team) IN ({}) OR LOWER(away_team) IN ({}))
                """.format(','.join(['?']*len(turkish_names)), ','.join(['?']*len(turkish_names))), 
                (t_id, t_round, *turkish_names, *turkish_names)) as cursor:
                    row_p = await cursor.fetchone()
                    if row_p: has_pending_turkish = True

            if not has_pending_turkish:
                print(f"DEBUG: [Tournament] Temsilcilerimizin maçları bitti, {comp_name} - {t_round} geri kalanı simüle ediliyor...")
                await self.simulate_remaining_tournament_round(ctx, t_id, t_round, comp_name, leg=current_leg)
            else:
                print(f"DEBUG: [Tournament] Hala bekleyen temsilci maçı var, otomatik simülasyon bekleniyor.")

    @commands.command(name="kupa_sim", aliases=["kupasim", "tournament_sim", "sim"])
    async def kupa_sim_command(self, ctx: commands.Context, tournament_name: str = None, leg: str = "1"):
        """
        Bir turnuva turundaki tüm oynanmamış maçları simüle eder.
        Kullanım: !kupa_sim [Turnuva] [Ayak]
        Örnek: !kupa_sim UECL 1
        """
        if not tournament_name:
            return await ctx.send("❌ **Eksik bilgi!**\nKullanım: `!kupa_sim [Turnuva] [Ayak]`\nÖrnek: `!kupa_sim UEL 1`")

        # Leg'i sayıya çevirmeyi dene
        try:
            leg_int = int(leg)
        except ValueError:
            return await ctx.send(f"❌ **HATA:** Ayak (leg) bir sayı olmalıdır! (Girdiğin: `{leg}`)")

        t_id = await database.get_tournament_by_name(tournament_name)
        if not t_id:
            # Alternatif arama (UEL - Yarı Final vs için)
            search_name = tournament_name
            for kw in ["UCL", "UEL", "UECL"]:
                if kw in tournament_name.upper():
                    search_name = kw
                    break
            t_id = await database.get_tournament_by_name(search_name)
            
        if not t_id:
            return await ctx.send(f"❌ **HATA:** `{tournament_name}` isimli turnuva bulunamadı.")
            
        # O anki aktif turu bul (Pending olan ilk maça bak)
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT round FROM tournament_fixtures WHERE tournament_id = ? AND status = 'Pending' LIMIT 1", (t_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return await ctx.send(f"✅ **{tournament_name}** turnuvasında zaten beklemede olan maç yok!")
                t_round = row["round"]
        
        await self.simulate_remaining_tournament_round(ctx, t_id, t_round, tournament_name, leg=leg_int)
        # Final mesajı zaten simulate_remaining_tournament_round gönderiyor artık

    @commands.command(name="hazirlik", aliases=["hazırlık", "friendly", "deneme"])
    async def hazirlik_command(self, ctx: commands.Context, *, query: str = None):
        """
        Deneme amaçlı hazırlık maçı yapar. 
        Bu maç hiçbir veriyi etkilemez (Puan durumu, istatistik, bütçe değişmez).

        Kullanım: !hazirlik [Takım A] vs [Takım B] [hava]
        Örnek: !hazirlik Galatasaray vs Real Madrid Clear
        """
        if not query:
            return await ctx.send("❌ **Eksik bilgi!**\nKullanım: `!hazirlik [Takım A] vs [Takım B] [Hava]`")

        # Bu komut bir deneme maçıdır
        ctx.is_trial = True
        
        # Hazırlık anahtar kelimesini ekleyelim ki AI prompt'u ona göre ayarlasın
        if "hazırlık" not in query.lower() and "friendly" not in query.lower():
            query += " Hazırlık"
            
        # Mevcut mac_command logic'ini admin kontrolü olmadan çalıstıralım
        # mac_command içinde admin kontrolü @decorator seviyesinde olduğu için 
        # direkt çağırmak yerine içeride is_trial kontrolü ekleyeceğiz veya 
        # mantığı ayıracaktık. 
        # Ancak en güvenlisi mac_command decorator'ünden @commands.has_permissions'ı kaldırıp 
        # fonksiyon başında kontrol etmek.
        
        await ctx.invoke(self.mac_command, query=query)

    @commands.command(name="puanyukle", aliases=["puan_kur", "tablo_ayarla", "setstandings"])
    @commands.has_permissions(administrator=True)
    async def puanyukle_command(self, ctx: commands.Context, *, data: str):
        """Metin halindeki puan tablosunu veritabanına yükler. 
        Format: Takım | O | G | B | M | AG | YG | P
        Veya: Takım O GD P (Basit format)
        """
        lines = data.strip().split('\n')
        updated_teams = 0
        errors = []

        # Takım ismi eşleştirme haritası (Kısaltmalar için)
        alias_map = {
            "FB": "Fenerbahçe", "GS": "Galatasaray", "BJK": "Beşiktaş", "TS": "Trabzonspor",
            "SAM": "Samsunspor", "KNY": "Konyaspor", "BFK": "Başakşehir", "ANT": "Antalyaspor",
            "ALY": "Alanyaspor", "KOC": "Kocaelispor", "KAY": "Kayserispor", "EYP": "Eyüpspor",
            "GFK": "Gaziantep FK", "GOZ": "Göztepe", "CRS": "Rizespor", "KSP": "Kasımpaşa",
            "GEN": "Gençlerbirliği", "FKG": "Fatih Karagümrük", "SİV": "Sivasspor", "ADS": "Adana Demirspor"
        }

        await ctx.send("⌛ **Puan tablosu işleniyor...**")

        for line in lines:
            if "|" in line:
                # Format: Takım | O | G | B | M | AG | YG | P
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 8:
                    try:
                        name = parts[0]
                        name = alias_map.get(name.upper(), name)
                        played, won, drawn, lost = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
                        gf, ga, points = int(parts[5]), int(parts[6]), int(parts[7])
                        await database.update_team_full_stats(name, played, won, drawn, lost, gf, ga, points)
                        updated_teams += 1
                    except ValueError:
                        continue
            else:
                # Daha basit bir format deneyelim (Esnek ayrıştırma)
                # Örn: FB 2 7 6 (Takım O AV P)
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        name = parts[0]
                        name = alias_map.get(name.upper(), name)
                        played = int(parts[1])
                        # GD (AV) ve P yeterli olabilir ama veritabanı tam istatistik istiyor.
                        # Basit modda G/B/M'yi puan üzerinden tahmin edelim
                        points = int(parts[-1])
                        gd = int(parts[-2])
                        
                        won = points // 3
                        drawn = points % 3
                        lost = played - won - drawn
                        # GF/GA'yı GD üzerinden hayali bir dağılımla yapalım (veya 0 bırakalım)
                        gf = gd if gd > 0 else 0
                        ga = abs(gd) if gd < 0 else 0
                        
                        await database.update_team_full_stats(name, played, won, drawn, lost, gf, ga, points)
                        updated_teams += 1
                    except (ValueError, IndexError):
                        continue

        if updated_teams > 0:
            msg = f"✅ **Puan tablosu güncellendi!**\nToplam {updated_teams} takımın verileri işlendi."
            if errors:
                msg += f"\n\n⚠️ **Hatalar:**\n" + "\n".join(errors[:5])
            await ctx.send(msg)
            # Sıralamayı göster
            await ctx.invoke(self.bot.get_command("standings"))
        else:
            await ctx.send("❌ **Puan tablosu işlenemedi!** Lütfen formatı kontrol edin.")

    @commands.command(name="golyukle", aliases=["gol_yukle", "setgoals", "gol_kralligi_ayarla"])
    @commands.has_permissions(administrator=True)
    async def golyukle_command(self, ctx: commands.Context, *, data: str):
        """Gol krallığı verilerini yükler.
        Format: Oyuncu | Takım | Gol
        Örn: Icardi | Galatasaray | 15
        """
        lines = data.strip().split('\n')
        updated_players = 0
        errors = []

        await ctx.send("⌛ **Gol krallığı verileri işleniyor...**")

        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            for line in lines:
                if "|" not in line: continue
                
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    try:
                        p_name = parts[0]
                        t_name = parts[1]
                        goals = int(parts[2])
                        
                        # Takım ismini alias_map'ten geçir
                        alias_map = {
                            "FB": "Fenerbahçe", "GS": "Galatasaray", "BJK": "Beşiktaş", "TS": "Trabzonspor",
                            "SAM": "Samsunspor", "KNY": "Konyaspor", "BFK": "Başakşehir", "ANT": "Antalyaspor",
                            "ALY": "Alanyaspor", "KOC": "Kocaelispor", "KAY": "Kayserispor", "EYP": "Eyüpspor",
                            "GFK": "Gaziantep FK", "GOZ": "Göztepe", "CRS": "Rizespor", "KSP": "Kasımpaşa",
                            "GEN": "Gençlerbirliği", "FKG": "Fatih Karagümrük", "SİV": "Sivasspor", "ADS": "Adana Demirspor"
                        }
                        t_name = alias_map.get(t_name.upper(), t_name)
                        
                        # AKILLI EŞLEŞTİRME: Veritabanında bu takımda bu isme benzer biri var mı?
                        exist_player = None
                        # Önce tam eşleşme (Case-insensitive)
                        async with db.execute("SELECT name FROM players WHERE LOWER(name) = LOWER(?) AND team = ?", (p_name, t_name)) as cursor:
                            row = await cursor.fetchone()
                            if row: exist_player = row["name"]
                        
                        # Yoksa kısmi eşleşme (C. Ndiaye -> Cherif Ndiaye)
                        if not exist_player:
                            # C. Ndiaye gibi kısaltmaları temizleyip sadece soyadıyla ara
                            search_q = p_name.split(".")[-1].strip() if "." in p_name else p_name
                            
                            async with db.execute("SELECT name FROM players WHERE name LIKE ? AND team = ?", (f"%{search_q}%", t_name)) as cursor:
                                row = await cursor.fetchone()
                                if row: exist_player = row["name"]
                        
                        target_name = exist_player if exist_player else p_name
                        # DİKKAT: Artık veritabanı fonksiyonu eskisini tamamen silip 
                        # sadece senin verdiğin rakamı SET ediyor.
                        await database.update_player_full_stats(target_name, t_name, goals)
                        updated_players += 1
                    except Exception as e:
                        errors.append(f"Hata: {line} -> {e}")

        if updated_players > 0:
            msg = f"✅ **Gol krallığı güncellendi!**\nToplam {updated_players} oyuncunun verileri işlendi."
            if errors:
                msg += f"\n\n⚠️ **Hatalar:**\n" + "\n".join(errors[:5])
            await ctx.send(msg)
            # Gol krallığını göster
            await ctx.invoke(self.bot.get_command("topscorers"))
        else:
            await ctx.send("❌ **Gol verileri işlenemedi!** Lütfen formatı kontrol edin (Oyuncu | Takım | Gol).")

    @commands.command(name="goltemizle", aliases=["golleri_sil", "resetgoals", "gol_sifirla"])
    @commands.has_permissions(administrator=True)
    async def goltemizle_command(self, ctx: commands.Context):
        """Ligdeki tüm gol kayıtlarını sıfırlar."""
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute("DELETE FROM goal_scorers")
            await db.execute("UPDATE players SET goals = 0, assists = 0")
            await db.commit()
        await ctx.send("🧹 **Tüm gol krallığı verileri sıfırlandı!** Artık `!golyukle` ile tertemiz başlayabilirsin.")

    @commands.command(name="standings", aliases=["puan", "table", "lig", "ligde"])
    async def standings_command(self, ctx: commands.Context):
        """Lig durumunu göster"""
        # SADECE SÜPER LİG TAKIMLARINI GETİR (UCL/UEL/UECL VE SİLİNENLER HARİÇ)
        teams = await database.get_all_teams(league='Super Lig')

        if not teams:
            await ctx.send("📊 **Lig tablosu henüz boş.** İlk maçları simüle edin!")
            return

        embed = discord.Embed(
            title="🏆 TÜRKİYE SÜPER LİGİ PUAN DURUMU",
            description="```text\nS | Takım               | O  | G | B | M | AV | P\n──|─────────────────────|────|───|───|───|────|───```",
            color=0xf1c40f, # Vivid Gold
            timestamp=datetime.now()
        )
        
        table_rows = []
        for i, team in enumerate(teams, 1):
            # Avrupa Potası ve Küme Düşme İkonları
            if i == 1: icon = "🏆" # Champion
            elif i == 2: icon = "🥈" # UCL
            elif i <= 4: icon = "🇪🇺" # UEL
            elif i <= 5: icon = "🟢" # UECL
            elif i >= 17: icon = "🔴" # Relegation
            else: icon = "⚪"
            
            av = team["gf"] - team["ga"]
            av_str = f"+{av}" if av > 0 else str(av)
            
            # Hizalama (Pading)
            name = team['name'][:18]
            row = (
                f"{icon} `{i:<2}| {name:<20}| {team['played']:>2} | {team['won']:>1}| {team['drawn']:>1}| {team['lost']:>1}| {av_str:>3}| {team['points']:>2}`"
            )
            table_rows.append(row)

        table_content = "\n".join(table_rows)
        self._add_split_fields(embed, "📋 Güncel Tablo", table_content, inline=False)
            
        embed.set_footer(text="🏆 Şampiyonlar Ligi | 🥈 ŞL Elemeleri | 🇪🇺 Avrupa Ligi | 🟢 Konfederasyon | 🔴 Küme Düşme")
        await ctx.send(embed=embed)

    @commands.command(name="topscorers", aliases=["gol", "scorers"])
    async def topscorers_command(self, ctx: commands.Context):
        """Gol krallığı listesini göster (Sadece Süper Lig Golleri)"""
        scorers = await database.get_top_scorers(limit=10, competition='League')

        if not scorers:
            await ctx.send("⚽ Gol kralı listesi henüz boş. Maçlar simüle edilmedi.")
            return

        embed = discord.Embed(
            title="👟 TÜRKİYE SÜPER LİGİ - GOL KRALLIĞI",
            description="Sezonun en keskin ayakları ve krallık yarışı! ⚽🔥\n━━━━━━━━━━━━━━━━━━━━",
            color=0xe74c3c, # Passionate Red
            timestamp=datetime.now()
        )
        
        scorers_text = ""
        for i, scorer in enumerate(scorers, 1):
            icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🎖️"
            scorers_text += f"{icon} ` {i:>2}. ` **{scorer['player_name']}**\n┗— 🏟️ `{scorer['team']}` | ⚽ **{scorer['goals']} Gol**\n"

        self._add_split_fields(embed, "👑 ALTIN AYAKKABI YARIŞI", scorers_text, inline=False)
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/5351/5351505.png")
        embed.set_footer(text="Resmi Gol Krallığı Listesi | Süper Lig 2026")
        await ctx.send(embed=embed)

    @commands.command(name="topassists", aliases=["asist", "assists", "asistler"])
    async def topassists_command(self, ctx: commands.Context):
        """Asist krallığı listesini göster (Sadece Süper Lig Asistleri)"""
        assists = await database.get_top_assists(limit=10, competition='League')

        if not assists:
            await ctx.send("👟 Asist listesi henüz boş. Pozisyonlar işlenmedi.")
            return

        embed = discord.Embed(
            title="🎯 TÜRKİYE SÜPER LİGİ - ASİST KRALLIĞI",
            description="Ligi besleyen orkestra şefleri ve asist krallığı! ⚽✨\n━━━━━━━━━━━━━━━━━━━━",
            color=0x3498db, # Elegant Blue
            timestamp=datetime.now()
        )
        
        assists_text = ""
        for i, assist in enumerate(assists, 1):
            icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "✨"
            assists_text += f"{icon} ` {i:>2}. ` **{assist['player_name']}**\n┗— 🏟️ `{assist['team']}` | 🎯 **{assist['assists']} Asist**\n"

        self._add_split_fields(embed, "👑 ASİST KRALLIĞI YARIŞI", assists_text, inline=False)
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/5351/5351505.png")
        embed.set_footer(text="Resmi Asist Krallığı Listesi | Süper Lig 2026")
        await ctx.send(embed=embed)

    @commands.command(name="cezalılar", aliases=["cezalilar", "kartlar", "suspensions"])
    async def suspended_players(self, ctx, *, team_name: str = None):
        """Ligdeki cezalı oyuncuları ve kart sınırında olanları listeler."""
        if team_name:
            team_data = await database.get_team_by_name(team_name)
            if not team_data:
                await ctx.send(f"❌ **{team_name}** adında bir takım bulunamadı.")
                return
            
            players = await database.get_suspended_players(team_data["name"])
            embed = discord.Embed(
                title=f"⚖️ {team_data['name']} - Ceza Raporu",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            
            suspended_list = [p for p in players if p["suspension_matches"] > 0]
            warning_list = [p for p in players if p["yellow_cards"] % 4 == 3]
            
            if suspended_list:
                val = "\n".join([f"❌ **{p['name']}** ({p['suspension_matches']} Maç)" for p in suspended_list])
                self._add_split_fields(embed=embed, name="🚫 Cezalı Oyuncular", value=val, inline=False)
            
            if warning_list:
                val = "\n".join([f"⚠️ **{p['name']}** ({p['yellow_cards']} Sarı Kart)" for p in warning_list])
                self._add_split_fields(embed=embed, name="🟨 Kart Sınırındakiler", value=val, inline=False)
                
            if not suspended_list and not warning_list:
                embed.description = "Bu takımda cezalı veya sınırda oyuncu bulunmuyor."
                
            embed.set_footer(text="Türkiye Süper Ligi Ceza Sistemi")
            await ctx.send(embed=embed)
        else:
            # Tüm ligi göster
            async with database.get_db() as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT name, team, yellow_cards, red_cards, suspension_matches 
                    FROM players 
                    WHERE suspension_matches > 0 OR yellow_cards % 4 == 3
                    ORDER BY team ASC, suspension_matches DESC
                """) as cursor:
                    all_p = [dict(row) for row in await cursor.fetchall()]
            
            if not all_p:
                await ctx.send("✅ **Ligde şu an cezalı veya kart sınırında oyuncu bulunmuyor.**")
                return
            
            embed = discord.Embed(
                title="⚖️ Süper Lig - Ceza & Kart Raporu",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            
            current_team = ""
            field_val = ""
            for p in all_p:
                team_display = p["team"].title()
                if team_display != current_team:
                    if current_team:
                        self._add_split_fields(embed=embed, name=f"🏟️ {current_team}", value=field_val, inline=False)
                    current_team = team_display
                    field_val = ""
                
                status = f"❌ {p['suspension_matches']} MAÇ CEZA" if p["suspension_matches"] > 0 else "🟨 SINIRDA"
                field_val += f"• **{p['name']}** ({status} - {p['yellow_cards']}YK)\n"
            
            if field_val:
                self._add_split_fields(embed=embed, name=f"🏟️ {current_team}", value=field_val, inline=False)
                
            embed.set_footer(text="4 Sarı Kart = 1 Maç Ceza | Kırmızı Kart = 2 Maç Ceza")
            await ctx.send(embed=embed)

    @commands.command(name="fiksturyukle", aliases=["fiksturekle"])
    @commands.has_permissions(administrator=True)
    async def fiksturyukle_command(self, ctx: commands.Context, *, content: str):
        """
        Manuel fikstür yüklemesi yapar.
        Format: Hafta | Ev Sahibi | Deplasman (Her satıra bir maç)
        """
        lines = content.strip().split("\n")
        fixtures = []
        errors = []
        
        for line in lines:
            line = line.strip()
            if not line or "|" not in line: continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                try:
                    round_no = int(parts[0])
                    home = parts[1]
                    away = parts[2]
                    
                    # İSİM NORMALİZASYONU
                    async with aiosqlite.connect(database.DB_PATH) as db:
                        db.row_factory = aiosqlite.Row
                        # Home team find
                        async with db.execute("SELECT name FROM teams WHERE name LIKE ? OR LOWER(name) = LOWER(?)", (f"%{home}%", home)) as cursor:
                            row = await cursor.fetchone()
                            if row: home = row["name"]
                        # Away team find
                        async with db.execute("SELECT name FROM teams WHERE name LIKE ? OR LOWER(name) = LOWER(?)", (f"%{away}%", away)) as cursor:
                            row = await cursor.fetchone()
                            if row: away = row["name"]

                    fixtures.append({"round_no": round_no, "home_team": home, "away_team": away})
                except Exception as e:
                    errors.append(f"Hata: {line} -> {e}")
        
        if fixtures:
            await database.save_fixtures(fixtures)
            msg = f"✅ **{len(fixtures)} maç fikstüre eklendi!**"
            if errors: msg += f"\n⚠️ **Hatalar:**\n" + "\n".join(errors[:3])
            await ctx.send(msg)
        else:
            await ctx.send("❌ **Maç yüklenemedi!** Lütfen formatı kontrol edin: `Hafta | Ev Sahibi | Deplasman`")

    @commands.command(name="fikstur", aliases=["maclar", "schedule"])
    async def fikstur_command(self, ctx: commands.Context, round_no: int = None):
        """Haftalık fikstürü gösterir."""
        # Eğer hafta belirtilmediyse (veya 0 ise) tümünü veya en yakınını bulalım
        fixtures = await database.get_fixtures(round_no)
        
        if not fixtures:
            await ctx.send("📅 **Fikstür henüz oluşturulmamış!** `!fiksturu_tamamla` veya `!fiksturyukle` kullanın.")
            return

        # Hafta belirtilmemişse en küçük haftayı göster
        if not round_no:
            round_no = min([f["round_no"] for f in fixtures])
        
        embed = discord.Embed(
            title=f"📅 LİG TV | {round_no}. HAFTA PROGRAMI",
            description=f"Haftanın tüm karşılaşmaları ve canlı sonuçlar.\n━━━━━━━━━━━━━━━━━━━━",
            color=0x3498db # Sky Blue
        )
        
        round_matches = [f for f in fixtures if f["round_no"] == round_no]
        if not round_matches:
            await ctx.send(f"📅 **{round_no}. hafta için maç kaydı bulunamadı.**")
            return

        match_list = ""
        for f in round_matches:
            status_icon = "🏟️"
            score_text = "vs"
            
            if str(f.get("status", "")).strip().lower() == "played":
                status_icon = "✅"
                score_text = f"**{f.get('home_score', 0)} - {f.get('away_score', 0)}**"
            
            match_list += f"{status_icon} `{f['home_team']}` {score_text} `{f['away_team']}`\n"
        
        self._add_split_fields(embed, "🏟️ KARŞILAŞMALAR", match_list, inline=False)
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3211/3211029.png")
        embed.set_footer(text=f"📜 Haftayı oynatmak için: !haftayi_oynat {round_no}")
        await ctx.send(embed=embed)

    @commands.command(name="manset", aliases=["galeri", "ozet", "highlights", "recap"])
    async def manset_command(self, ctx: commands.Context):
        """Maçın en kritik anlarını AI ile görselleştirir (Match Highlights Reel)"""
        if not self.last_match_result:
            return await ctx.send("❌ **Henüz oynanmış bir maç bulunamadı başkan!** Önce bir maç yaptır, sonra manşetleri basalım.")

        await ctx.send("📸 **Maçın en ateşli anları film şeridi gibi hazırlanıyor...** 🎞️")
        
        res = self.last_match_result
        highlights = self.media_generator.generate_highlight_prompts(res)
        
        if not highlights:
            return await ctx.send("⚠️ Maçta görselleştirilecek kadar büyük bir olay yaşanmadı, sönük geçti.")

        # Display highlights one by one with a cinematic feel
        for i, h in enumerate(highlights, 1):
            embed = discord.Embed(
                title=f"🎬 MAÇIN MANŞETİ #{i}",
                description=f"{h['caption']}\n\n*\"{random.choice(['İnanılmaz bir an!', 'Tarih yazıldı!', 'Sokaklar bu anı konuşacak!', 'Nefesler kesildi!'])}\"*",
                color=0xe67e22 # Orange
            )
            embed.set_image(url=h["image_url"])
            embed.set_footer(text=f"🎥 Highlights Reel | {res['home_team']} vs {res['away_team']}")
            
            await ctx.send(embed=embed)
            await asyncio.sleep(2) # Brief pause between frames

        await ctx.send(f"✅ **{res['home_team']} - {res['away_team']} maç manşetleri tamamlandı!** 🦁🦅🔥")

    @commands.command(name="panorama", aliases=["hafta_ozeti", "panoroma", "summary"])
    @commands.has_permissions(administrator=True)
    async def panorama_command(self, ctx: commands.Context, round_no: int = None):
        """Haftalık lig özetini (Altın 11, Sürprizler, Analiz) yapay zeka ile oluşturur."""
        await ctx.send("🔄 **Haftanın sonuçları analiz ediliyor ve panorama hazırlanıyor...** ⚽📜")

        # 1. Hafta numarasını belirle
        if not round_no:
            round_no = await database.get_latest_played_round()
            if not round_no:
                await ctx.send("❌ Henüz oynanmış bir hafta bulunamadı!")
                return

        # 2. Sonuçları getir
        results = await database.get_round_results(round_no)
        if not results:
            await ctx.send(f"❌ {round_no}. hafta için henüz hiç maç oynanmamış!")
            return

        # 3. AI için verileri topla
        BIG_TEAMS = ["Galatasaray", "Fenerbahçe", "Beşiktaş", "Trabzonspor"]
        data_text = f"TÜRKİYE SÜPER LİGİ {round_no}. HAFTA SONUÇLARI:\n"
        scorers_pool = [] # Altın 11 için adaylar
        
        for r in results:
            h_team = r['home_team']
            a_team = r['away_team']
            is_big_match = h_team in BIG_TEAMS and a_team in BIG_TEAMS
            match_label = "🔥 [DERBİ/DEV MAÇ] 🔥" if is_big_match else ""
            
            data_text += f"- {match_label} {h_team} {r['home_score']} - {r['away_score']} {a_team}\n"
            match_goals = r.get('goals', [])
            data_text += "  Goller: " + ", ".join([f"{g['player_name']} ({g['minute']}')" for g in match_goals]) + "\n"
            
            for g in match_goals:
                scorers_pool.append({"name": g['player_name'], "team": g['team']})

        # 3. Haftanın Takımı & En İyilerini Bul (Galip Takımlar ve Yıldızlar)
        winners = []
        for r in results:
            if r['home_score'] > r['away_score']: winners.append(r['home_team'])
            elif r['away_score'] > r['home_score']: winners.append(r['away_team'])
            else: # Beraberlik durumunda ikisini de aday yapabiliriz ama sadece birer yıldız
                winners.append(r['home_team'])
                winners.append(r['away_team'])
        
        # Aday Havuzu Oluştur
        scorers_pool = []
        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            # Gol atanlar zaten aday
            for r in results:
                for g in r['goals']:
                    scorers_pool.append({"name": g['player_name'], "team": g['team'], "type": "Scorer"})

            # Kazananlardan Kaleci ve Defans ve Orta Saha Yıldızlarını Bul
            for team in set(winners):
                # En iyi Kaleci
                async with db.execute("SELECT name, position FROM players WHERE team = ? AND position = 'GK' ORDER BY overall DESC LIMIT 1", (team,)) as cursor:
                    gk = await cursor.fetchone()
                    if gk: scorers_pool.append({"name": gk['name'], "team": team, "pos": "GK"})
                # En iyi 2 Defans
                async with db.execute("SELECT name, position FROM players WHERE team = ? AND position = 'DF' ORDER BY overall DESC LIMIT 2", (team,)) as cursor:
                    dfs = await cursor.fetchall()
                    for df in dfs: scorers_pool.append({"name": df['name'], "team": team, "pos": df['position']})
                # En iyi 2 Orta Saha
                async with db.execute("SELECT name, position FROM players WHERE team = ? AND position = 'MF' ORDER BY overall DESC LIMIT 2", (team,)) as cursor:
                    mfs = await cursor.fetchall()
                    for mf in mfs: scorers_pool.append({"name": mf['name'], "team": team, "pos": mf['position']})

        # ADAY OYUNCULARIN MEVKİLERİNİ ÇEK (Hallusinasyon Önleme)
        pool_text = "\nHAFTANIN ÖNE ÇIKAN ADAYLARI (ALTIN 11 İÇİN SADECE BUNLARI KULLAN!):\n"
        unique_pool = {}
        for p in scorers_pool:
            unique_pool[p['name']] = p
            
        for p_name, p_info in unique_pool.items():
            if 'pos' in p_info:
                pos = p_info['pos']
            else: # Golcüler için mevki bul
                async with aiosqlite.connect(database.DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute("SELECT position FROM players WHERE (name = ? OR name LIKE ?) AND team = ?", (p_name, f"%{p_name}%", p_info['team'])) as cursor:
                        row = await cursor.fetchone()
                        pos = row['position'] if (row and row['position'] and row['position'].strip()) else "ST"
            pool_text += f"- {p_name} ({p_info['team']}) -> Mevki: {pos}\n"

        # Puan durumu (İlk 10)
        teams = await database.get_all_teams()
        standings_text = "GÜNCEL PUAN DURUMU (İLK 10):\n"
        for i, t in enumerate(teams[:10], 1):
            standings_text += f"{i}. {t['name']} - {t['points']} Puan\n"

        # Gol Krallığı
        top_scorers = await database.get_top_scorers(5)
        scorers_text = "GOL KRALLIĞI YARIŞI:\n"
        for s in top_scorers:
            scorers_text += f"- {s['player_name']} ({s['team']}): {s['goals']} Gol\n"

        # Gelecek Hafta Fikstürü (Preview için)
        next_fixtures = await database.get_fixtures(round_no + 1)
        next_fx_text = "GELECEK HAFTANIN (BİR SONRAKİ RAUND) MAÇLARI:\n"
        for f in next_fixtures:
            next_fx_text += f"- {f['home_team']} vs {f['away_team']}\n"

        # 4. Premium AI Prompt
        prompt = f"""
Sen Türkiye'nin en popüler, en çok okunan magazinel spor gazetesi editörüsün! (Örn: Fanatik/Fotomaç manşetçisi). 
Aşağıdaki verilere dayanarak {round_no}. haftanın panoraması için tam bir "SPOR SAYFASI" hazırla. Dilin çok hırslı, heyecanlı ve tam bir "gazete manşeti" tadında olsun.

=== VERİLER ===
{data_text}
{standings_text}
{scorers_text}
{pool_text}
{next_fx_text}

=== ÖNEMLİ: GAZETE YAPILANDIRMASI ===
Kritik Kurallar:
1. **ALTIN 11'DE KESİNLİKLE OYUNCU İSMİ YERİNE TAKIM İSMİ (RIZESPOR VB.) YAZMA!** Sadece 'ADAYLAR' listesindeki gerçek oyuncu isimlerini kullan.
2. Altın 11'e (Kaleci, Defans, Orta Saha) sadece o hafta maçını kazanan takımların aday listesindeki yıldızlarını koy.
3. Mevkilere (GK, DF, MF, FW) sadık kal. (None) yazma!

Yanıtını aşağıda belirtilen etiketlerle (Markers) bölümlere ayır!

[[MANŞET]] -> [FLAŞ! / ÖZEL!] ile başlayan, haftanın en vurucu başlığı ve özet haberi.
[[ANALİZ]] -> [SAHADA SAVAŞ VAR!] başlıklı, maçların taktiksel ve dramatik analizleri.
[[ÖDÜLLER]] -> [HAFTANIN ENLERİ] başlığıyla; Haftanın Takımı, Teknik Direktörü ve Haftanın Oyuncusu.
[[ALTIN-11]] -> [ŞAMPİYONLAR KARMASI] başlığıyla Altın 11. (Mevkilere sadık kal, gerçek isimleri kullan!).
Kadro Şablonu:
```text
             [GK: İsim]
  [DF: İsim] [DF: İsim] [DF: İsim] [DF: İsim]
        [MF: İsim] [MF: İsim] [MF: İsim]
    [FW: İsim] [FW: İsim] [FW: İsim]
```
[[KULİS]] -> [ÖZEL HABER / SOSYAL MEDYA] 3-4 adet komik taraftar tweeti ve Erman Toroğlu tarzı sert bir hakem yorumu ("ERMAN TOROĞLU HAKEM PORNO MU İZLİYOR KARDEŞİM YA DİYECEK.").
[[GELECEK]] -> [FALCI DİYOR Kİ!] Gelecek haftanın en büyük maçına dair kehanet ve yazarın son notu.
"""

        # AI Çağrısı (Merkezi Cascade Sistemi)
        try:
            raw_text = await ai.generate_content(
                prompt=prompt,
                system="Sen profesyonel bir Türk spor gazetesi editörüsün.",
                temp=0.8,
                tokens=4096,
                is_json=False,  # Panorama özel markerlar kullandığı için ham metin alıyoruz
                label=f"Panorama: Hafta {round_no}",
                provider="auto",
                attempts=3,
                timeout=50
            )

            if not raw_text:
                await ctx.send("❌ Yapay zeka servislerine (Gemini/Groq/OR) şu an erişilemiyor. Lütfen biraz sonra tekrar deneyin.")
                return

            # --- EMBED OLUŞTURMA VE PARSING ---
            def get_section(tag, text):
                import re
                pattern = rf"\[\[{tag}\]\](.*?)(?=\[\[|$)"
                match = re.search(pattern, text, re.DOTALL)
                return match.group(1).strip() if match else ""

            manset = get_section("MANŞET", raw_text)
            analiz = get_section("ANALİZ", raw_text)
            oduller = get_section("ÖDÜLLER", raw_text)
            kadro = get_section("ALTIN-11", raw_text)
            kulis = get_section("KULİS", raw_text) # Sosyal Medya + Hakem
            gelecek = get_section("GELECEK", raw_text)

            # --- TEK VE GÜÇLÜ BİR EMBED OLUŞTURMA ---
            embed = discord.Embed(
                title=f"🗞️ AMUNKO GAZETESİ - {round_no}. HAFTA ÖZEL",
                description=f"**{manset}**",
                color=0xe67e22 # Newspaper Orange
            )
            embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/21/21601.png") # Newspaper icon
            
            if analiz:
                self._add_split_fields(embed=embed, name="🏟️ SAHADA SAVAŞ VAR!", value=analiz, inline=False)
            
            if oduller:
                self._add_split_fields(embed=embed, name="🏆 HAFTANIN ENLERİ", value=oduller, inline=False)
            
            if kadro:
                self._add_split_fields(embed=embed, name="🏟️ ŞAMPİYONLAR KARMASI (ALTIN 11)", value=f"```text\n{kadro}\n```", inline=False)
            
            if kulis:
                self._add_split_fields(embed=embed, name="🗣️ ÖZEL HABER & HAKEM ODASI", value=kulis, inline=False)

            if gelecek:
                self._add_split_fields(embed=embed, name="🔮 FALCI DİYOR Kİ!", value=gelecek, inline=False)

            embed.set_footer(text="Süper Lig Panorama | © 2026")
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"❌ Panorama oluşturulurken hata: {e}")

    async def _get_team_best_ovr(self, team_name: str) -> tuple:
        """Determines the best OVR and if a tactic file exists for a team."""
        stored = self._get_stored_tactic(team_name)
        has_tactic = False
        ovr = 0
        
        if stored:
            has_tactic = True
            _, lineup_text, _, _ = self._parse_tactic_file(stored)
            # Use the hybrid average logic (File + DB Top 18)
            ovr, _ = await self._get_squad_data(team_name, lineup_text)
        
        if ovr <= 0:
            team_data = await self._find_team(team_name)
            if team_data and team_data.get("overall", 0) > 0:
                ovr = team_data["overall"]
            else:
                ovr = 75.0
        
        return int(ovr), has_tactic

    def _fast_match_math_logic(self, name_h, ovr_h, has_t_h, name_a, ovr_a, has_t_a, round_no=None):
        """Mathematical core of the simulation using GPR Gap discipline."""
        import random
        # 1. Base Ratings (including home bonus)
        rating_h = ovr_h + 2 + (4 if has_t_h else random.randint(2, 3)) # Home bonus + Tactic
        rating_a = ovr_a + (4 if has_t_a else random.randint(2, 3))
        
        gap = rating_h - rating_a
        r_gap = abs(gap)
        
        # 2. Gap Discipline (Mirroring main engine)
        off_max_h, off_min_h = (8, 4) if has_t_h else (6, 2)
        off_max_a, off_min_a = (6, 6) if has_t_a else (5, 5)
        
        if r_gap > 8:
            if gap > 0:
                off_min_h = 2; off_max_a = 3
            else:
                off_max_h = 3; off_min_a = 3
        
        if r_gap > 12:
            if gap > 0:
                off_min_h = 1; off_max_a = 2
            else:
                off_max_h = 2; off_min_a = 1
                
        # 3. Performance Score (GPR)
        gpr_h = random.randint(max(10, rating_h - off_min_h), min(99, rating_h + off_max_h))
        gpr_a = random.randint(max(10, rating_a - off_min_a), min(99, rating_a + off_max_a))
        
        # 4. Result Generation (Refined Weight Pool)
        def gpr_to_goals(gpr, opp_gpr):
            diff = gpr - opp_gpr
            r_gap = abs(diff)
            
            # Ezici Üstünlük (25+ Fark) - Sadece burada 5-6 gole izin ver
            if diff > 25: return random.choices([3, 4, 5, 6], [20, 40, 30, 10])[0]
            # Net Favori (15-25 Fark)
            if diff > 15: return random.choices([1, 2, 3, 4, 5], [15, 35, 30, 15, 5])[0]
            # Favori (8-15 Fark)
            if diff > 8: return random.choices([0, 1, 2, 3, 4], [10, 40, 30, 15, 5])[0]
            # Rekabetçi (3-8 Fark) 
            if diff > 3: return random.choices([0, 1, 2, 3], [30, 45, 15, 10])[0]
            # Kora Kor / Altın Sürpriz (-3 ile 3 Fark)
            if diff > -3: return random.choices([0, 1, 2], [45, 45, 10])[0]
            # Zayıf / Underdog (Negatif Fark)
            return random.choices([0, 1], [85, 15])[0]

        score_h = gpr_to_goals(gpr_h, gpr_a)
        score_a = gpr_to_goals(gpr_a, gpr_h)
        
        # --- SCRIPTED MATCH (Kocaelispor vs Beşiktaş - Hafta 10) ---
        if round_no == 10:
            tn_h = self.clean_tn(name_h)
            tn_a = self.clean_tn(name_a)
            if (tn_h == "kocaelispor" and tn_a == "besiktas"):
                if score_a <= score_h: score_a = score_h + 1 # Beşiktaş wins
            elif (tn_h == "besiktas" and tn_a == "kocaelispor"):
                if score_h <= score_a: score_h = score_a + 1 # Beşiktaş wins

        # Realistic caps
        if gpr_h > 94 and score_h < 2: score_h = 2
        if gpr_a > 94 and score_a < 2: score_a = 2
        
        return score_h, score_a, gpr_h, gpr_a

    @commands.command(name="haftayi_oynat", aliases=["haftayi_simule_et", "play_week", "simulate_week"])
    @commands.has_permissions(administrator=True)
    async def haftayi_oynat_command(self, ctx: commands.Context, round_no: int = None):
        """Belirtilen haftanın tüm 'Pending' maçlarını 0-API (Hızlı) simüle eder."""
        if not round_no:
            fixtures = await database.get_fixtures()
            pending_rounds = sorted(list(set([f["round_no"] for f in fixtures if f["status"] == "Pending"])))
            if not pending_rounds:
                return await ctx.send("📅 **Oynanacak maç kalmadı!**")
            round_no = pending_rounds[0]
        else:
            latest = await database.get_latest_played_round()
            if round_no > latest + 1:
                return await ctx.send(f"⚠️ Lig şu an {latest}. haftada. Önce {latest+1}. haftayı oynatmalısın.")

        round_matches = [f for f in await database.get_fixtures() if f["round_no"] == round_no and f["status"] == "Pending"]
        if not round_matches:
            return await ctx.send(f"📅 **{round_no}. hafta için oynanacak Pending maç bulunamadı.**")

        status_msg = await ctx.send(f"🔄 **{round_no}. HAFTA BAŞLIYOR!** TOPLAM {len(round_matches)} MAÇ API HARCAMADAN SİMÜLE EDİLİYOR... ⚽⚡")
        
        results = []
        for match in round_matches:
            h_name = match["home_team"]
            a_name = match["away_team"]
            
            # Fetch Ratings with Scenario Discipline
            ovr_h, has_t_h = await self._get_team_best_ovr(h_name)
            ovr_a, has_t_a = await self._get_team_best_ovr(a_name)
            
            # Math-Core Sim
            score_h, score_a, gpr_h, gpr_a = self._fast_match_math_logic(h_name, ovr_h, has_t_h, a_name, ovr_a, has_t_a, round_no=round_no)
            
            # Record result
            await database.record_match(h_name, a_name, score_h, score_a, "Lig", "Clear", [], events=[])
            
            # Store result line
            results.append(f"• **{h_name} {score_h} - {score_a} {a_name}** | *(GPR: {gpr_h}-{gpr_a})* | 📊 *OVR: {ovr_h}-{ovr_a}*")
            await asyncio.sleep(0.1)

        embed = discord.Embed(
            title=f"📅 {round_no}. Hafta Maç Sonuçları",
            description="\n".join(results),
            color=0xf1c40f # Gold
        )
        embed.set_footer(text="Bu hafta '0-API Fast Sim' (Gap-Discipline) ile simüle edilmiştir. 🤖⚽")
        await status_msg.edit(content=None, embed=embed)
        await ctx.send(f"✅ **{round_no}. HAFTA TAMAMLANDI!** Puan durumu güncellendi.")
        
        # 8. AUTOMATED CHANNEL UPDATES (WEEK END)
        try:
            await self.update_league_channels(ctx.guild, is_week_end=True)
        except Exception as e:
            print(f"DEBUG: Weekly automated update failed: {e}")

    @commands.command(name="fiksturu_tamamla")
    @commands.has_permissions(administrator=True)
    async def fiksturu_tamamla_command(self, ctx: commands.Context):
        """Mevcut maçlara bakarak ligin geri kalanını otomatik eşleştirir."""
        await ctx.send("🔄 **Fikstür analiz ediliyor...**")
        
        teams_data = await database.get_all_teams()
        team_names = sorted([t["name"] for t in teams_data])
        
        if len(team_names) < 2:
            await ctx.send("❌ Yeterli takım yok!")
            return
            
        all_fixtures = await database.get_fixtures()
        max_round_in_db = max([f["round_no"] for f in all_fixtures]) if all_fixtures else 0
        
        # Oynanan/Planlanan tüm eşleşmeleri (H,A) not et
        played_pairs = set()
        fixture_map = {} # (round, team) -> is_playing
        for f in all_fixtures:
            played_pairs.add((f["home_team"], f["away_team"]))
            fixture_map[(f["round_no"], f["home_team"])] = True
            fixture_map[(f["round_no"], f["away_team"])] = True
            
        # Tüm olası eşleşmeleri (Home ve Away olmak üzere 2 maç her ikili için)
        potential_matches = []
        for t1 in team_names:
            for t2 in team_names:
                if t1 != t2:
                    if (t1, t2) not in played_pairs:
                        potential_matches.append((t1, t2))
        
        import random
        random.shuffle(potential_matches)
        
        # Toplam hafta sayısı (18 takım için 34 hafta)
        total_rounds = (len(team_names) - 1) * 2
        new_fixtures = []
        
        # DAHA GÜÇLÜ: Circle Method (Döner Koltuk) Algoritması
        def generate_perfect_circle_fixtures(teams):
            if len(teams) % 2 != 0:
                teams.append("BAY")
            n = len(teams)
            schedule = []
            
            # İlk yarı (n-1 hafta)
            temp_teams = list(teams)
            for r in range(n - 1):
                round_matches = []
                for i in range(n // 2):
                    h, a = temp_teams[i], temp_teams[n - 1 - i]
                    if h != "BAY" and a != "BAY":
                        # Sabit takım için ev/dep dengesi
                        if i == 0 and r % 2 == 1:
                            round_matches.append((a, h))
                        else:
                            round_matches.append((h, a))
                schedule.append(round_matches)
                # Saat yönünde döndür (ilk eleman hariç)
                temp_teams = [temp_teams[0]] + [temp_teams[-1]] + temp_teams[1:-1]
            
            # İkinci yarı (Rövanşlar)
            second_half = []
            for r_matches in schedule:
                second_half.append([(a, h) for h, a in r_matches])
            
            return schedule + second_half

        perfect_schedule = generate_perfect_circle_fixtures(team_names)
        
        # Database'e kaydet (Mevcut fikstürün üzerine yazabilir veya kontrol edebiliriz)
        # Burada en güvenlisi: Mevcut (Manuel) girilenlerin eşleşmelerini 'Played' veya 'Scheduled' olarak işaretleyip,
        # geri kalanları bu mükemmel listeden doldurmak.
        
        # Ama şu an en basit ve sağlamı: Tümünü mükemmel liste ile baştan oluşturmak.
        final_fixtures = []
        for r_idx, r_matches in enumerate(perfect_schedule, 1):
            for h, a in r_matches:
                # Eğer bu eşleşme veritabanında zaten varsa (manuel girildiyse) kopyasını ekleme
                if (h, a) not in played_pairs:
                    final_fixtures.append({"round_no": r_idx, "home_team": h, "away_team": a})
                    played_pairs.add((h, a)) # Artık bunu 'var' sayıyoruz

        if final_fixtures:
            await database.save_fixtures(final_fixtures)
            await ctx.send(f"📅 **Mükemmel Fikstür Oluşturuldu!** Toplam {len(final_fixtures)} yeni maç eklendi.")
            
            all_fixtures = await database.get_fixtures()
            max_r = max([f["round_no"] for f in all_fixtures])
            await ctx.send(f"📊 Lig tam olarak **{max_r} hafta** sürecek ve her takım her rakibiyle 1 evinde 1 deplasmanda oynayacak.")
        else:
            await ctx.send("⚠️ Tüm eşleşmeler zaten fikstürde var.")

    @commands.command(name="fikstursil")
    @commands.has_permissions(administrator=True)
    async def fikstursil_command(self, ctx: commands.Context):
        """Fikstürü tamamen temizler."""
        await database.clear_fixtures()
        await ctx.send("🗑️ **Fikstür tamamen temizlendi.**")

    @commands.command(name="taktik_yukle", aliases=["ty", "settactic", "uploadtactic", "taktikguncelle", "taktikkaydet"])
    @commands.check_any(commands.has_permissions(administrator=True), commands.has_any_role("Teknik Direktör", "Teknik Direktor"))
    async def taktik_yukle_command(self, ctx: commands.Context, team_name: str = None):
        """Bir takımın varsayılan taktiğini/dizilişini (.txt) sisteme yükler.
        Kullanım: !taktik_yukle [Takım] (Dosyayı mesaja ekleyin)
        """
        if not team_name or not ctx.message.attachments:
            await ctx.send("❌ **Yanlış kullanım!** Takım ismini yazmalı ve taktik .txt dosyasını mesaja eklemelisin.\nÖrnek: `!taktik_yukle Galatasaray` (Dosya ekli)")
            return

        team_data = await self._find_team(team_name)
        if not team_data:
            await ctx.send(f"❌ **{team_name}** veritabanında bulunamadı!")
            return

        att = ctx.message.attachments[0]
        if not att.filename.endswith('.txt'):
            await ctx.send("❌ Sadece `.txt` uzantılı taktik dosyaları kabul edilir.")
            return

        # Dosyayı kaydet
        content = await att.read()
        os.makedirs(os.path.join("data", "tactics"), exist_ok=True)
        path = os.path.join("data", "tactics", f"{team_data['name']}.txt")
        
        with open(path, "wb") as f:
            f.write(content)
            
        await ctx.send(f"✅ **{team_data['name']}** için yeni taktik başarıyla kaydedildi! 📋")

    @commands.command(name="taktik_sil")
    @commands.has_permissions(administrator=True)
    async def taktik_sil_command(self, ctx: commands.Context, team_name: str = None):
        """Bir takımın kayıtlı taktiğini siler."""
        if not team_name:
            await ctx.send("❓ Hangi takımın taktiğini silmek istiyorsun?")
            return

        team_data = await self._find_team(team_name)
        if not team_data:
            await ctx.send(f"❌ **{team_name}** bulunamadı.")
            return

        path = os.path.join("data", "tactics", f"{team_data['name']}.txt")
        if os.path.exists(path):
            os.remove(path)
            await ctx.send(f"🗑️ **{team_data['name']}** taktiği sistemden silindi.")
        else:
            await ctx.send(f"⚠️ **{team_data['name']}** için zaten kayıtlı bir taktik bulunmuyor.")

    def _get_stored_tactic(self, team_name: str) -> Optional[str]:
        """Yerel depolamadan taktik dosyasını oku (Zeki Arama - Case Insensitive)."""
        folder = os.path.join("data", "tactics")
        if not os.path.exists(folder):
            return None
            
        def normalize(s):
            s = s.lower().strip()
            translation = str.maketrans("çğıöşü", "cgiosu")
            return s.translate(translation)

        target_norm = normalize(team_name)
        
        # Klasördeki tüm dosyaları tara
        for filename in os.listdir(folder):
            if filename.endswith(".txt"):
                file_stem = filename[:-4] # .txt kısmını at
                if normalize(file_stem) == target_norm:
                    path = os.path.join(folder, filename)
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            print(f"DEBUG: [Tactic Match] {team_name} matched with {filename}")
                            return f.read()
                    except Exception as e:
                        print(f"Error reading tactic for {team_name}: {e}")
        return None


    async def simulate_remaining_tournament_round(self, ctx, t_id: int, round_name: str, tournament_name: str, leg: int = 1):
        """Simulates all other pending matches in the same tournament round AND LEG using non-AI logic with Big Team Bias."""
        import random
        
        # DEV TAKIMLAR LİSTESİ (KORUMA ALTINDAKİLER)
        BIG_TEAMS = [
            "Real Madrid", "Manchester City", "Bayern Munich", "PSG", "Arsenal", 
            "Liverpool", "Barcelona", "Inter", "Juventus", "AC Milan", "Atletico Madrid",
            "Galatasaray", "Fenerbahçe", "Beşiktaş", "Trabzonspor", "Kocaelispor"
        ]

        async with aiosqlite.connect(database.DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            # SADECE BU TURDAKİ VE BU AYAKTAKİ (LEG) Bekleyen maçları bul
            if str(round_name).strip().lower().startswith("group ") or "lig aşaması" in str(round_name).lower():
                async with db.execute(
                    """
                    SELECT * FROM tournament_fixtures
                    WHERE tournament_id = ? AND round = ? AND leg = ? AND status = 'Pending'
                    """,
                    (t_id, round_name, leg),
                ) as cursor:
                    pending = await cursor.fetchall()
            else:
                search_pattern = f"{round_name[:3]}%"
                async with db.execute(
                    """
                    SELECT * FROM tournament_fixtures
                    WHERE tournament_id = ? AND round LIKE ? AND leg = ? AND status = 'Pending'
                    """,
                    (t_id, search_pattern, leg),
                ) as cursor:
                    pending = await cursor.fetchall()

        if not pending:
            return

        status_msg = await ctx.send(f"🔄 **{tournament_name} - {round_name}** turundaki diğer maçlar akıllı bot tarafından simüle ediliyor... 🤖")
        
        results = []
        for row in pending:
            match = dict(row)
            try:
                h_team = match["home_team"]
                a_team = match["away_team"]
                current_leg = match.get("leg", 1)
                
                # KOCAELİSPOR MAÇLARINI ATLA (Sadece kullanıcı oynasın)
                if "Kocaelispor" in [h_team, a_team]:
                    print(f"DEBUG: Skipping Kocaelispor match: {h_team} vs {a_team}")
                    continue

                # 1. Ratingleri bul (Önce DB'den, yoksa Akıllı Tahmin'den)
                h_data = await database.get_team(h_team)
                a_data = await database.get_team(a_team)
                
                h_ovr = h_data["overall"] if (h_data and h_data.get("overall", 0) > 0) else 75.0
                a_ovr = a_data["overall"] if (a_data and a_data.get("overall", 0) > 0) else 75.0
                
                # Zero-Division Guard
                h_ovr = max(10, h_ovr) 
                a_ovr = max(10, a_ovr)
                
                # 2. BÜYÜK TAKIM BİAS (KORUMA) SİSTEMİ
                h_bias = 1.0
                a_bias = 1.0
                
                if any(bt in h_team for bt in BIG_TEAMS): h_bias += 0.25
                if any(bt in a_team for bt in BIG_TEAMS): a_bias += 0.25
                
                # 3. Skor üret (Weighted Poisson-ish)
                # Baz gol ihtimalleri (Power/Bias etkili)
                h_strength = (h_ovr * h_bias) / 75.0
                a_strength = (a_ovr * a_bias) / 75.0
                
                # Gol Ağırlıkları: Zayıf takımın 5-6 atma ihtimali neredeyse yok edildi. 
                # Güçlü takımın (h_strength > 1.2) gol atma ihtimali korunurken, 0-1-2 gol havuzu zenginleştirildi.
                
                # FINAL KONTROLÜ (Neutral Ground): Final maçlarında deplasman dezavantajı (a_weights) uygulanmaz.
                is_final_round = "final" in str(round_name).lower() and "çeyrek" not in str(round_name).lower() and "yarı" not in str(round_name).lower()
                
                h_weights = [max(5, 20/h_strength), 35*h_strength, 20*h_strength, 10, 3, 1]
                a_weights = h_weights if is_final_round else [max(5, 30/a_strength), 40*a_strength, 15*a_strength, 7, 2, 1]
                
                h_goals = random.choices([0, 1, 2, 3, 4, 5], weights=h_weights)[0]
                a_goals = random.choices([0, 1, 2, 3, 4, 5], weights=a_weights)[0]
                
                # 4. Kaydet
                sync_name = tournament_name
                for kw in ["UCL", "UEL", "UECL"]:
                    if kw in tournament_name.upper():
                        sync_name = kw
                        break

                await database.record_match(h_team, a_team, h_goals, a_goals, sync_name, "Clear", [], leg=current_leg, events=[])
                
                # 5. Görselleştirme
                line_text = f"• {h_team} {h_goals} - {a_goals} {a_team}"
                if any(bt in h_team for bt in BIG_TEAMS) and h_goals >= a_goals: line_text = "🛡️ " + line_text
                elif any(bt in a_team for bt in BIG_TEAMS) and a_goals >= h_goals: line_text += " 🛡️"
                
                results.append(line_text)
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"ERROR Simulation {h_team} vs {a_team}: {e}")
                continue
        
        if not results:
            return await status_msg.edit(content="✅ Diğer tüm önemli maçlar oynamaya hazır durumda.")

        embed = discord.Embed(
            title=f"🤖 {tournament_name} - {round_name} Diğer Sonuçlar",
            description="\n".join(results),
            color=0x3498db
        )
        embed.set_footer(text="Bu maçlar büyük takımları kollayan 'Akıllı Bot' tarafından simüle edilmiştir. (🛡️ = Favori Kazandı/Berabere)")
        await status_msg.edit(content=None, embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(MatchCog(bot))

