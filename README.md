<div align="center">
  
# 🏆 Turkish Super League Discord Bot

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Discord.py](https://img.shields.io/badge/discord.py-v2.3+-5865F2.svg?style=for-the-badge&logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![OpenRouter](https://img.shields.io/badge/AI_Powered-OpenRouter-FF5A5F.svg?style=for-the-badge&logo=openai&logoColor=white)](https://openrouter.ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

> Türk Süper Lig Roleplay (RP) sunucuları için geliştirilmiş, **Yapay Zeka (AI) destekli** son derece gerçekçi bir futbol simülasyon ve yönetim botudur. 

</div>

---

## ✨ Özellikler

- 🤖 **Yapay Zeka Destekli Maç Simülasyonu** (`!mac`): OpenRouter modellerini kullanarak takımların taktiklerini analiz eder, 15-25+ olay içeren aşırı detaylı ve gerçekçi maç senaryoları üretir.
- 💰 **Gelişmiş Transfer Sistemi** (`!transfer`): Gerçekçi transfer bedelleri, bütçe yönetimi ve medyanın transfere verdiği tepkileri simüle eder.
- 🏥 **Sakatlık & Ceza Mekanikleri** (`!sakatlik`): Oyuncu sakatlıkları ve takım üzerindeki etkilerini dinamik olarak hesaplar.
- 📰 **Medya & Basın Sistemi**: Türk spor medyası tarzında flaş manşetler, teknik direktör açıklamaları ve taraftar reaksiyonları üretir.
- 📊 **Lig Yönetimi**:
  - `!standings`: Otomatik güncellenen canlı lig tablosu
  - `!topscorers`: Detaylı gol krallığı takibi
- ⚡ **Hızlı ve Güvenilir**: SQLite tabanlı hafif veritabanı altyapısıyla kesintisiz veri yönetimi sağlar.

---

## 🚀 Kurulum

### 1. Gereksinimleri Yükleyin
Projeyi klonlayın ve gerekli Python paketlerini yükleyin:

```bash
git clone https://github.com/Ferdi-krbk/Turkish-League-Discord-Bot.git
cd turkish-league-bot
pip install -r requirements.txt
```

### 2. Discord Bot Ayarları
1. [Discord Developer Portal](https://discord.com/developers/applications)'a gidin.
2. Yeni bir "Application" oluşturun ve "Bot" sekmesinden **Token** alın.
3. Botunuzu sunucuya davet edin (OAuth2 -> URL Generator).

### 3. Yapay Zeka (API) Entegrasyonu
1. [OpenRouter](https://openrouter.ai/keys) adresinden ücretsiz API Key oluşturun.
2. Proje dizininde bulunan `config.py` veya `.env` dosyasını güncelleyin:

```python
BOT_TOKEN = "BURAYA_DISCORD_BOT_TOKEN_GELECEK"
OPENROUTER_API_KEY = "sk-or-xxxxxxxxxxxxx"  # OpenRouter API Key
OPENROUTER_MODEL = "qwen/qwen-max"          # Tavsiye edilen model
```

### 4. Botu Başlatın
```bash
python main.py
```
*(Windows kullanıcıları `botu_baslat.bat` dosyasına çift tıklayarak da botu aktif edebilirler.)*

---

## 🎮 Kullanım Rehberi

### ⚽ Maç Simülasyonu (AI Destekli)

```text
!mac [Takım A] [Takım B] [Önem Derecesi] [Hava Durumu]
```

**Örnek Kullanım:**
```text
!mac Galatasaray Fenerbahçe Derby Clear
```

💡 *İpucu: Komutu kullanırken mesaja her takım için 1 adet (toplam 2) taktik dosyası (.txt) eklerseniz, AI bu taktikleri okur ve skoru/olayları buna göre belirler!*

**AI'nin Ürettiği Çıktı İçeriği:**
- 🥅 Gerçekçi maç skoru (Örn: 2-1, 1-1, 0-0, 3-2 vb.)
- ⏱️ Dakika dakika detaylı olaylar (Goller, direkten dönen toplar, müthiş kurtarışlar, VAR kararları)
- 📋 Taktiksel analiz ve istatistikler (Topla oynama oranları)
- 🌟 Maçın Adamı (Rating sistemiyle)
- 🗞️ Flaş manşetler ve taraftar yorumları

### 💸 Transfer Komutu
```text
!transfer
Player: [Oyuncu Adı]
From: [Satan Takım]
To: [Alan Takım]
```

### 🏆 Diğer Komutlar
- `!standings`: Güncel puan durumunu gösterir.
- `!topscorers`: Ligi domine eden golcüleri listeler.
- `!sakatlik`: Belirtilen oyuncunun sağlık durumunu sorgular/belirler.

---

## 📁 Proje Yapısı

```
turkish-league-bot/
├── main.py              # Botun ana başlatıcı dosyası
├── config.py            # Konfigürasyon ve API anahtarları
├── botu_baslat.bat      # Windows için hızlı başlatma betiği
├── cogs/                # Discord.py Cogs (Komut Modülleri)
│   ├── match.py         # Maç ve AI motoru
│   ├── transfer.py      # Transfer sistemi
│   └── injury.py        # Sakatlık modülü
├── core/                # Çekirdek Sistemler
│   ├── database.py      # Veritabanı yöneticisi
│   └── media.py         # Basın/Medya motoru
├── data/                # Statik Veriler & Taktikler
│   └── tactics/         # Takımların oyun planları (.txt)
└── README.md            # Proje dökümantasyonu
```

---

## 🤝 Katkıda Bulunma
Projeye katkıda bulunmak isterseniz bir **Pull Request (PR)** açabilir veya karşılaştığınız sorunları **Issues** sekmesinde belirtebilirsiniz.

## 📄 Lisans
Bu proje **MIT Lisansı** ile lisanslanmıştır. Daha fazla bilgi için `LICENSE` dosyasına göz atabilirsiniz.
