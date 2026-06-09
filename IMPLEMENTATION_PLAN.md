# Implementation Plan: ShortsCup AI — YT-Shorts Trend Tracker & Dashboard

## Context (Neden / Amaç)
2026 Dünya Kupası ile ilgili viral YouTube Shorts'ları otomatik bulup Velocity (hız) ve
Engagement (etkileşim) metriklerine göre puanlayan, sonucu koyu temalı `dashboard.html` olarak
basan hafif bir pipeline. Dizin boş (sadece `CLAUDE.md`), Python 3.12.2 + pip hazır → sıfırdan.

**Kararlar (kullanıcı onaylı):**
- `youtube-search-python` KULLANILMAYACAK. Hem arama hem metadata **tek elden `yt-dlp`**.
  (CLAUDE.md "Discovery" kuralından bilinçli sapma → gerekçe: kararlılık + engel riski yok.)
- `TEST_MODE` varsayılan **açık**: kategori başına ilk 1-2 keyword, keyword başına 10-15 video.
- Öncelik: stabil veri + doğru renk kodları (kırmızı/sarı/gri). Dashboard cilası ikinci planda.

---

## Dizin Yapısı
```
shorts_analyzer/
├── __init__.py
├── config.py
├── analyzer_engine.py
├── report_generator.py
├── main.py
└── requirements.txt
dashboard.html          # üretilen çıktı (proje kökü)
```

---

## 1. `requirements.txt`
```
yt-dlp
pandas
```

---

## 2. `config.py` — tüm sabitler tek yerde

```python
# Keyword kategorileri (CLAUDE.md'den)
TOURNAMENT_KEYWORDS = ["World Cup 2026 qualifiers", "World Cup 2026 goals", "Road to 2026 World Cup"]
PLAYER_TRANSFER_KEYWORDS = ["Football transfer news shorts", "Here we go football shorts",
                            "Arda Guler Turkey skills", "Mbappe France 2026"]
ALGORITHM_HOOKS = ["Football shorts edit", "Football rare moments", "Prime football edits"]

KEYWORD_CATEGORIES = {
    "TOURNAMENT": TOURNAMENT_KEYWORDS,
    "PLAYER_TRANSFER": PLAYER_TRANSFER_KEYWORDS,
    "ALGORITHM_HOOKS": ALGORITHM_HOOKS,
}

# Çalışma ayarları
RESULTS_PER_KEYWORD = 15
MAX_DURATION = 60            # Shorts garantisi: duration <= 60 sn
MIN_DELAY, MAX_DELAY = 2, 4  # random.uniform gecikme

# IP-güvenli test modu
TEST_MODE = True
TEST_MODE_KEYWORDS_PER_CATEGORY = 2
TEST_MODE_RESULTS_PER_KEYWORD = 10

# Sınıflandırma eşikleri
VELOCITY_CRITICAL = 3000
ENGAGEMENT_CRITICAL = 6      # yüzde
VELOCITY_POTENTIAL = 1000

# Sınıf → görsel eşleme (emoji, hex, tailwind bg class, etiket)
CLASSIFICATION = {
    "CRITICAL":  {"label": "CRITICAL TREND", "emoji": "🔴", "hex": "#ef4444", "pill": "bg-red-500"},
    "POTENTIAL": {"label": "POTENTIAL",      "emoji": "🟡", "hex": "#eab308", "pill": "bg-yellow-500"},
    "SKIP":      {"label": "SKIP",           "emoji": "⚪", "hex": "#64748b", "pill": "bg-slate-500"},
}

# yt-dlp ortak ayarları
YDL_META_OPTS = {"quiet": True, "no_warnings": True, "extract_flat": False, "skip_download": True}
YDL_SEARCH_OPTS = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}

OUTPUT_HTML = "dashboard.html"
```

`get_active_keywords()` yardımcı fonksiyonu: `TEST_MODE` açıksa her kategoriden ilk
`TEST_MODE_KEYWORDS_PER_CATEGORY` keyword'ü, kapalıysa hepsini düz liste olarak döndürür.

---

## 3. `analyzer_engine.py` — `AnalyzerEngine` sınıfı

**Sorumluluk:** keşif → metadata → metrik → sınıflandırma → sıralı DataFrame.

Metodlar:
- `__init__(self)` — config'ten ayarları yükle; aktif `RESULTS_PER_KEYWORD`'ü TEST_MODE'a göre seç.
- `_search(self, keyword) -> list[str]`
  - `YoutubeDL(YDL_SEARCH_OPTS).extract_info(f"ytsearch{N}:{keyword}", download=False)`
  - `entries`'ten video ID/`url` listesi çıkar (flat). Hata olursa boş liste + log, devam.
- `_fetch_metadata(self, video_url) -> dict | None`
  - `YoutubeDL(YDL_META_OPTS).extract_info(video_url, download=False)`
  - Çek: `view_count`, `like_count`, `channel`/`uploader`, `timestamp`, `upload_date`,
    `duration`, `title`, `webpage_url`.
  - Exception/timeout → `None` döndür (üst katman atlar).
- `_compute_age_hours(self, info) -> float`
  - `timestamp` varsa: `(now - datetime.fromtimestamp(ts))` saat cinsinden.
  - yoksa `upload_date` (YYYYMMDD) → o günün başlangıcı.
  - **Sıfıra bölme koruması:** `max(age_hours, 1.0)`.
- `_classify(self, velocity, engagement) -> str`
  - `velocity > 3000 and engagement > 6` → CRITICAL
  - `elif velocity > 1000` → POTENTIAL
  - `else` → SKIP
- `run(self) -> pandas.DataFrame`
  - `get_active_keywords()` üzerinde döngü; her keyword için `_search`.
  - Her video için `random.uniform(MIN_DELAY, MAX_DELAY)` bekle → `_fetch_metadata`.
  - Filtre: `duration is not None and duration <= MAX_DURATION`.
  - Eksik veri güvenliği: `views = view_count or 0`, `likes = like_count or 0`.
    `views == 0` ise satırı atla (velocity/engagement anlamsız).
  - `velocity = views / age_hours`, `engagement = (likes/views)*100`.
  - `keyword` alanını da satıra ekle (Top Keyword kartı için).
  - Tüm satırları DataFrame'e koy, `Velocity` azalan sırala, döndür.
  - Konsola özet: toplam taranan, critical sayısı.

Notlar:
- Tek `YoutubeDL` örneği context manager ile her çağrıda açılıp kapanır (basit + güvenli).
- Tüm ağ çağrıları try/except içinde; bir video patlasa bile pipeline devam eder.

---

## 4. `report_generator.py` — `ReportGenerator` sınıfı

**Sorumluluk:** DataFrame → `dashboard.html`.

- `__init__(self, df)`
- `_build_metric_cards(self) -> str`
  - Total Scraped = `len(df)`
  - Critical Trends = `(df.classification == "CRITICAL").sum()`
  - Top Keyword = en çok CRITICAL/yüksek velocity üreten `keyword` (mode veya groupby max).
- `_build_rows(self) -> str`
  - Her satır için: sıra no, title (kısalt), channel, Velocity (yuvarlanmış),
    Engagement % (1 ondalık), renkli pill (`CLASSIFICATION[...]["pill"]` + emoji),
    "Watch Short ↗" butonu (`<a href="{webpage_url}" target="_blank">`).
  - **Güvenlik:** `title`, `channel` → `html.escape(...)`.
- `generate(self) -> None`
  - f-string HTML iskeleti:
    - `<head>` içinde `<script src="https://cdn.tailwindcss.com"></script>`
    - body bg `#0f172a`, kart/tablo `#1e293b`, metin `#f8fafc`/`#94a3b8`
    - üst 3 metrik kartı + responsive leaderboard tablo
  - `dashboard.html`'i UTF-8 yaz (Windows → `encoding="utf-8"`).

---

## 5. `main.py` — orkestratör
```python
from shorts_analyzer.analyzer_engine import AnalyzerEngine
from shorts_analyzer.report_generator import ReportGenerator

def main():
    df = AnalyzerEngine().run()
    if df.empty:
        print("Hiç video bulunamadı / hepsi filtrelendi.")
        return
    ReportGenerator(df).generate()
    print(f"dashboard.html üretildi — {len(df)} video.")

if __name__ == "__main__":
    main()
```
Üst düzey try/except ile beklenmedik hataları yakalayıp anlamlı mesaj basar.

---

## Doğrulama (Verification)
1. `pip install -r shorts_analyzer/requirements.txt`
2. `TEST_MODE=True` ile `python -m shorts_analyzer.main` → kategori başına 1-2 keyword,
   ~10 video; hatasız `dashboard.html` üretmeli.
3. `dashboard.html` tarayıcıda: 3 metrik kartı, Velocity'ye göre sıralı tablo,
   doğru renk pill'leri, çalışan "Watch Short ↗" linkleri.
4. Renk kodu doğrulaması (kritik): eşiklere göre kırmızı/sarı/gri beklenen videolara denk gelmeli.
5. Edge-case: çok yeni / like'ı gizli video pipeline'ı çökertmemeli (atlanır ya da güvenli işlenir).
6. Stabil olunca `TEST_MODE=False` → tam tarama.

## Kapsam Dışı
Video kırpma/birleştirme, ses sentezi — pipeline doğrulanana kadar yapılmayacak (CLAUDE.md §6).
