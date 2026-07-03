"""Ham aylık CSV'leri temiz Parquet'e çevirir (CSV → veri/islenmis/).

Kullanım:
    python kaynak/ingest.py                # veri/ham/ altındaki tüm ayları işler
    python kaynak/ingest.py 202301 202302  # sadece verilen ayları işler
    python kaynak/ingest.py --force 202410 # bütünlük kontrolünü atla (bilinçli!)

Temizlik kuralları:
- transition_hour: "00".."23" string → TINYINT
- Boş string'ler NULL'a çevrilir (town, line_name, station_poi_desc_cd, line)
- Kolon adları kaynaktakiyle aynı bırakılır (izlenebilirlik; bkz. veri/VERI_SOZLUGU.md)
- Ham veri ASLA değiştirilmez; çıktı ZSTD sıkıştırmalı Parquet

Koruma: Portalda eksik/bozuk ay dosyaları var (ör. Ekim 2024). Ayın tüm
günleri yeterli satırla mevcut değilse dosya DÖNÜŞTÜRÜLMEZ — analizlere
sessizce eksik veri sızmasın. Pandemi dönemi (2020-21) gibi gerçekten sönük
yıllar için eşiği --esik ile düşürün ya da --force kullanın.

Not: Zaten dönüştürülmüş aylar atlanır (çıktı dosyası varsa). Yeniden üretmek
için önce veri/islenmis/ altındaki ilgili parquet'i sil.
"""

import argparse
import calendar
import sys
from pathlib import Path

import duckdb

PROJE_KOKU = Path(__file__).resolve().parent.parent
RAW = PROJE_KOKU / "veri" / "ham"
PROCESSED = PROJE_KOKU / "veri" / "islenmis"


def donustur(csv_path: Path, parquet_path: Path) -> None:
    duckdb.sql(f"""
        COPY (
            SELECT
                transition_date,
                CAST(transition_hour AS TINYINT)          AS transition_hour,
                CAST(transport_type_id AS TINYINT)        AS transport_type_id,
                road_type,
                NULLIF(TRIM(line), '')                    AS line,
                transfer_type,
                CAST(number_of_passage AS INTEGER)        AS number_of_passage,
                CAST(number_of_passenger AS INTEGER)      AS number_of_passenger,
                product_kind,
                transaction_type_desc,
                NULLIF(TRIM(town), '')                    AS town,
                NULLIF(TRIM(line_name), '')               AS line_name,
                NULLIF(TRIM(station_poi_desc_cd), '')     AS station_poi_desc_cd
            FROM read_csv('{csv_path}', header=true)
        ) TO '{parquet_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)


def tam_mi(csv_path: Path, min_satir_per_gun: int) -> bool:
    """Ayın tüm günleri 24 saat ve yeterli satırla mevcut mu?"""
    gunler = duckdb.sql(f"""
        SELECT transition_date, COUNT(DISTINCT transition_hour) AS saat,
               COUNT(*) AS satir
        FROM '{csv_path}' GROUP BY 1
    """).fetchall()
    ilk_gun = min(g for g, _, _ in gunler)
    ay_gun = calendar.monthrange(ilk_gun.year, ilk_gun.month)[1]
    tam = [g for g, saat, satir in gunler
           if saat == 24 and satir >= min_satir_per_gun]
    return len(tam) == ay_gun


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("aylar", nargs="*", help="YYYYMM listesi; boşsa hepsi")
    p.add_argument("--force", action="store_true",
                   help="bütünlük kontrolünü atla")
    p.add_argument("--esik", type=int, default=100_000,
                   help="gün başına asgari satır (varsayılan 100000)")
    args = p.parse_args()

    csvler = sorted(RAW.glob("hourly_transportation_*.csv"))
    if args.aylar:
        csvler = [p_ for p_ in csvler if p_.stem.split("_")[-1] in args.aylar]
    if not csvler:
        sys.exit(f"veri/ham/ altında işlenecek CSV yok (filtre: {args.aylar or 'yok'})")

    for csv_path in csvler:
        ay = csv_path.stem.split("_")[-1]
        parquet_path = PROCESSED / f"hourly_{ay}.parquet"
        if parquet_path.exists():
            print(f"{ay}: zaten var, atlandı")
            continue
        if not args.force and not tam_mi(csv_path, args.esik):
            print(f"{ay}: EKSİK/BOZUK — dönüştürülmedi "
                  f"(detay: python scriptler/validate_csv.py {csv_path})")
            continue
        donustur(csv_path, parquet_path)
        mb_in = csv_path.stat().st_size / 1e6
        mb_out = parquet_path.stat().st_size / 1e6
        print(f"{ay}: {mb_in:,.0f} MB CSV → {mb_out:,.0f} MB Parquet")


if __name__ == "__main__":
    main()
