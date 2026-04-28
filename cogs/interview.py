import discord
from discord.ext import commands
import aiohttp
import json
import asyncio
from core import database
import config
import random
from core import ai

class InterviewCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_interviews = {} # user_id: {team, history}

    async def _get_ai_response(self, system_prompt: str, user_prompt: str, label: str = "Interview"):
        """
        Helper to get AI response with 3-tier fallback.
        """
        is_json_required = "JSON" in system_prompt or "JSON" in user_prompt
        
        return await ai.generate_content(
            prompt=user_prompt,
            system=system_prompt,
            temp=0.8,
            is_json=is_json_required,
            label=label,
            provider="auto",
            attempts=2,
            timeout=35
        )

    @commands.command(name="basin", aliases=["röportaj", "interview", "basin_toplantisi"])
    async def basin_command(self, ctx: commands.Context, *, team_name: str = None):
        """Ardışık 5 sorudan oluşan derinlemesine basın toplantısı."""
        if not team_name:
            await ctx.send("❓ **Hangi takımın teknik direktörü olarak konuşacaksın?**\nKullanım: `!basin <takım_ismi>`")
            return

        # Takımı bul
        team_data = await database.search_team(team_name)
        if not team_data:
            await ctx.send(f"❌ **'{team_name}'** isimle bir takım bulunamadı.")
            return
        
        real_team_name = team_data["name"]

        # 1. Maç Bağlamını Hazırla
        recent_matches = await database.get_recent_matches(5)
        last_match = None
        for m in recent_matches:
            if m["home_team"] == real_team_name or m["away_team"] == real_team_name:
                last_match = m
                break
        
        next_fix = await database.get_next_fixture(real_team_name)
        
        # Senaryoyu belirle
        interview_type = "post-match"
        if next_fix and (not last_match or last_match["id"] < 0):
             interview_type = "pre-match"
        
        match_info = ""
        if interview_type == "post-match" and last_match:
            is_home = last_match["home_team"] == real_team_name
            opponent = last_match["away_team"] if is_home else last_match["home_team"]
            score = f"{last_match['home_score']}-{last_match['away_score']}"
            winner = last_match["home_team"] if last_match["home_score"] > last_match["away_score"] else (last_match["away_team"] if last_match["away_score"] > last_match["home_score"] else "Berabere")
            
            # Golcüleri veri tabanından çek (Hallüsinasyon önleyici)
            scorers_rows = await database.get_match_scorers(last_match["id"])
            scorers_list = ", ".join([f"{s['player_name']} ({s['team']})" for s in scorers_rows]) if scorers_rows else "Gol yok."

            match_info = f"MAÇ SKORU: {last_match['home_team']} {score} {last_match['away_team']}\nKAZANAN: {winner}\nMAÇIN TÜM GOLLERİ: {scorers_list}\n"
            title_prefix = "🎤 Maç Sonu Basın Toplantısı"
        else:
            if not next_fix:
                await ctx.send(f"📅 **{real_team_name}** için aktif bir bağlam bulunamadı.")
                return
            opponent = next_fix["away_team"] if next_fix["home_team"] == real_team_name else next_fix["home_team"]
            match_info = f"GELECEK MAÇ: {next_fix['home_team']} vs {next_fix['away_team']}. Rakip: {opponent}."
            title_prefix = "🎤 Maç Önü Basın Toplantısı"

        # 2. Döngüyü Başlat (3 Soru)
        history = []
        squad = await database.get_team_players(real_team_name)
        player_names = ", ".join([p["name"] for p in random.sample(squad, min(len(squad), 5))]) if squad else "Kadro bilgisi yok."

        self.active_interviews[ctx.author.id] = {"team": real_team_name, "history": history}
        
        initial_msg = await ctx.send(f"🎤 **{real_team_name} teknik direktörü basın odasına giriyor. Basın toplantısı başlıyor...**")
        await asyncio.sleep(2.0)

        topics_pool = [
            "Taktiksel Diziliş ve Teknik Hatalar",
            "Oyuncu Değişikliklerinin Zamanlaması ve Etkisi",
            "Bireysel Performans Odaklı: " + player_names,
            "Transfer Dedikoduları ve Kulüp Atmosferi",
            "Yönetim Kurulu ile Yaşanan Gerginlikler",
            "Sakatlıklar ve Fiziksel Durum",
            "Hakem Kararları ve VAR Tartışmaları"
        ]
        random.shuffle(topics_pool)
        topics = ["Maçın Genel Özeti ve Skor Analizi", topics_pool[0], "Gelecek Vizyonu ve Camia Mesajı"]

        personas = [
            "Agresif ve kışkırtıcı bir muhabir",
            "Analitik, istatistik ve diziliş odaklı bir blogger",
            "Duygusal bir yerel gazeteci",
            "Zorlayıcı sorular soran bir duayen",
            "Modern futbol savunucusu, teknik bir muhabir"
        ]

        for i in range(1, 4):
            current_topic = topics[i-1]
            current_persona = random.choice(personas)
            
            system_prompt = f"""Sen deneyimli bir Türk spor medyası profesyonelisin ve şu an bir basın toplantısındasın.
Karakterin: {current_persona}. 
MUHABİR KİMLİĞİ: Kendine bir isim ve kanal uydur (Örn: 'Caner Tekin - beIN Sports').

KRİTİK TALİMATLAR:
1. GERÇEKLİK: Sana verilen MAÇ BİLGİSİ'ne %100 sadık kal. Kaybeden takıma kazandınız deyip saçmalama. İstatistikleri (goller, kartlar) doğru yorumla.
2. ÜSLUP: Kesinlikle bir yapay zeka gibi değil, gerçek bir spor muhabiri gibi konuş. 'TD'ye bu üslupla...' gibi teknik ifadeleri KESİNLİKLE kullanma. Doğrudan soruya gir.
3. TÜRKÇE: 'Gollere sahip olmak' veya 'Maçın tadını çıkarmak' gibi İngilizce'den devşirme çeviri ifadeleri asla kullanma. Gerçek Türk futbol jargonunu (tabela, kontra, baskı, hakem hataları) kullan.
4. KISA VE ETKİLİ: Soruyu çok uzatıp teknik direktörü bayıltma. Tek bir ana konuya odaklan ve cevabını beklediğin kışkırtıcı veya analitik soruyu sor.
"""
            
            history_text = "\n".join([f"Soru: {h['q']}\nCevap: {h['a']}" for h in history])
            user_prompt = f"BAĞLAM: {match_info}\nTUR: {i}/5. KONU: {current_topic}.\n\nGEÇMİŞ:\n{history_text}\n\nTD'ye bu üslupla {current_topic} hakkında doğrudan bir soru sor."
            
            async with ctx.typing():
                question = await self._get_ai_response(system_prompt, user_prompt, label=f"Interview: {real_team_name}")
                if not question:
                    fallbacks = [
                        f"Hocam, {current_topic} hakkında neler söylemek istersiniz?",
                        f"Peki hocam, {current_topic} konusundaki düşünceleriniz neler?",
                        f"Hocam, özellikle {current_topic} noktasına değinirsek, neler ekleyebilirsiniz?"
                    ]
                    question = random.choice(fallbacks)

            # Discord Embed Description limit is 4096. 
            # We'll put the whole text there for maximum space.
            embed = discord.Embed(
                title=f"🎬 {title_prefix} (Soru {i}/3)",
                description=f"📍 **Basın Odası - Canlı**\n" + "─" * 25 + f"\n\n***\"{question}\"***",
                color=0x3498db
            )
            embed.set_author(name="Canlı Yayın", icon_url="https://i.imgur.com/83pZpG1.png")
            embed.set_footer(text="Cevabını doğrudan yazabilirsin (120s)...")
            
            # If the text is somehow > 4000 (very rare), we split it and send chunks
            if len(question) > 3500:
                chunks = [question[i:i+1900] for i in range(0, len(question), 1900)]
                await ctx.send(embed=embed)
                for chunk in chunks[1:]:
                    await ctx.send(f"🎙️ **(Muhabir Devam Ediyor):** \"{chunk}\"")
            else:
                await ctx.send(embed=embed)

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            try:
                msg = await self.bot.wait_for("message", check=check, timeout=120.0)
                answer = msg.content
                history.append({"q": question, "a": answer})
                
                if any(x in answer.lower() for x in ["teşekkür", "toplantı bitmiş", "sağol"]):
                    await ctx.send("🏁 **Teknik direktör basın toplantısını sonlandırdı.**")
                    break

            except asyncio.TimeoutError:
                await ctx.send("⏱️ **Cevap gelmediği için basın toplantısı sona erdi.**")
                return

        # 3. Final Değerlendirme
        await ctx.send("⌛ **Analiz ediliyor...**")
        eval_system = "Futbol yönetim uzmanısın. TD'nin toplam performansını değerlendir. JSON: {'eval': 'açıklama', 'boost': -2 ile +2 arası tam sayı}"
        eval_history = "\n".join([f"M: {h['q']}\nTD: {h['a']}" for h in history])
        eval_prompt = f"Bağlam: {match_info}\nRöportaj:\n{eval_history}\n\nTakım moraline etkisini analiz et."
        
        async with ctx.typing():
            eval_raw = await self._get_ai_response(eval_system, eval_prompt, label=f"Interview Eval: {real_team_name}")
        
        boost = 0
        desc = "Analiz bitti."
        
        try:
            # 1. Clean up the raw response
            clean_eval = eval_raw.strip()
            
            # 2. Try to extract JSON/Dict block
            import re, ast
            # Regex for anything inside curly braces
            match = re.search(r'(\{.*\})', clean_eval.replace("\n", " "), re.DOTALL)
            if match:
                content = match.group(1)
                try:
                    # Try strict JSON first
                    import json
                    res = json.loads(content)
                    boost = res.get("boost", 0)
                    desc = res.get("eval", "Analiz tamamlandı.")
                except:
                    # Fallback to ast.literal_eval for single-quote dictionaries or malformed JSON
                    try:
                        res = ast.literal_eval(content)
                        boost = res.get("boost", 0)
                        desc = res.get("eval", "Analiz tamamlandı.")
                    except:
                        # If still failing, try to find the "eval" text manually
                        eval_match = re.search(r"['\"]eval['\"]\s*:\s*['\"](.*?)['\"]\s*,\s*['\"]boost", content, re.DOTALL)
                        if eval_match:
                            desc = eval_match.group(1)
                        else:
                            desc = clean_eval
            else:
                desc = clean_eval
            
            # 3. Final cleanup: If desc still contains dict-like strings, remove them
            if "{'eval':" in str(desc) or '{"eval":' in str(desc):
                # Hard cleanup
                desc = re.sub(r'\{.*\}', '', str(desc)).strip()
                if not desc: desc = "Analiz başarıyla tamamlandı."

        except Exception as e:
            print(f"DEBUG: Interview Eval Error: {e}")
            desc = eval_raw if eval_raw else "Analiz bitti."

        # Support for very long evaluations
        if len(desc) > 3800:
            desc = desc[:3800] + "..."

        boost = min(max(boost, -2), 2)
        await database.update_morale_boost(real_team_name, boost)

        res_embed = discord.Embed(title="📊 Basın Toplantısı Karnesi", description=f"_{desc}_", color=0x2ecc71 if boost >= 0 else 0xe74c3c)
        emoji = "📈" if boost > 0 else ("📉" if boost < 0 else "➖")
        res_embed.add_field(name=f"{emoji} Moral Etkisi", value=f"**{'+' if boost > 0 else ''}{boost} GPR**")
        await ctx.send(embed=res_embed)
        
        if ctx.author.id in self.active_interviews:
            del self.active_interviews[ctx.author.id]

async def setup(bot):
    await bot.add_cog(InterviewCog(bot))
